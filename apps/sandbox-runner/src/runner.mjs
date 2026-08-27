import { Buffer } from "node:buffer";
import { canonicalJson, sha256 } from "./canonical.mjs";

const TERMINAL = new Set([
  "succeeded",
  "failed",
  "cancelled",
  "timed_out",
  "resource_exhausted",
  "infrastructure_failed",
  "cleanup_failed",
]);

function now() {
  return new Date().toISOString();
}

function boundedReason(value) {
  return (
    String(value)
      .replaceAll(/[\r\n\t]+/g, " ")
      .slice(0, 120) || "unknown"
  );
}

function emptyHash() {
  return sha256(Buffer.alloc(0));
}

function exactObjectKeys(value, expected) {
  return (
    value !== null &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.keys(value).sort().join(",") === [...expected].sort().join(",")
  );
}

export function parseHarness(stdout, routes) {
  let value;
  try {
    value = JSON.parse(stdout.trim());
  } catch {
    throw new Error("Runtime result is not valid JSON");
  }
  if (
    !exactObjectKeys(value, [
      "contract_version",
      "duration_ms",
      "route_results",
      "status",
    ]) ||
    value.contract_version !== 1 ||
    !["passed", "failed"].includes(value.status) ||
    !Number.isInteger(value.duration_ms) ||
    value.duration_ms < 0 ||
    value.duration_ms > 60_000 ||
    !Array.isArray(value.route_results) ||
    value.route_results.length !== routes.length
  ) {
    throw new Error("Runtime result does not match contract version 1");
  }
  const results = value.route_results.map((item, index) => {
    if (
      !exactObjectKeys(item, [
        "document_ready_state",
        "execution_marker",
        "http_status",
        "route",
        "runtime_errors",
        "script_count",
        "status",
      ]) ||
      item.route !== routes[index] ||
      !["passed", "failed"].includes(item.status) ||
      ![null, "loading", "interactive", "complete"].includes(
        item.document_ready_state,
      ) ||
      typeof item.execution_marker !== "boolean" ||
      (!Number.isInteger(item.http_status) && item.http_status !== null) ||
      (Number.isInteger(item.http_status) &&
        (item.http_status < 100 || item.http_status > 599)) ||
      !Number.isInteger(item.script_count) ||
      item.script_count < 0 ||
      item.script_count > 1_000 ||
      !Array.isArray(item.runtime_errors) ||
      item.runtime_errors.length > 32 ||
      item.runtime_errors.some(
        (error) => typeof error !== "string" || error.length > 500,
      )
    ) {
      throw new Error("Runtime route result is malformed");
    }
    return {
      route: item.route,
      status: item.status,
      http_status: Number.isInteger(item.http_status) ? item.http_status : null,
      document_ready_state: item.document_ready_state ?? null,
      script_count: Number.isInteger(item.script_count) ? item.script_count : 0,
      runtime_errors: item.runtime_errors,
    };
  });
  const allPassed = results.every(
    (item) =>
      item.status === "passed" &&
      item.http_status === 200 &&
      item.document_ready_state === "complete" &&
      item.runtime_errors.length === 0,
  );
  if ((value.status === "passed") !== allPassed) {
    throw new Error("Runtime status disagrees with route evidence");
  }
  return { duration_ms: value.duration_ms, route_results: results, allPassed };
}

export function classifyHarnessOutcome(exitCode, harness) {
  const memoryAllocationFailed = harness.route_results.some((route) =>
    route.runtime_errors.includes("page: Array buffer allocation failed"),
  );
  if (memoryAllocationFailed) {
    return {
      outcome: "resource_exhausted",
      reason: "memory allocation failed under the fixed ceiling",
    };
  }
  if (exitCode === 0 && harness.allPassed) {
    return { outcome: "succeeded", reason: "completed" };
  }
  return { outcome: "failed", reason: "runtime checks failed" };
}

export class SandboxRunner {
  constructor({ engine, store, wallTimeoutMs = 60_000 }) {
    if (
      !Number.isInteger(wallTimeoutMs) ||
      wallTimeoutMs < 1 ||
      wallTimeoutMs > 60_000
    ) {
      throw new Error("Runner wall timeout must be between 1 and 60000ms");
    }
    this.engine = engine;
    this.store = store;
    this.wallTimeoutMs = wallTimeoutMs;
    this.active = new Map();
    this.claims = new Map();
    this.metrics = {
      launches: 0,
      replays: 0,
      rejected_requests: 0,
      request_digest_conflicts: 0,
      cancellation_requests: 0,
      cleanup_attempts: 0,
      cleanup_failures: 0,
      janitor_runs: 0,
      janitor_removals: 0,
      readiness_checks: 0,
      readiness_failures: 0,
      duration_ms_total: 0,
      remaining_labeled_resources: 0,
      outcomes: {
        succeeded: 0,
        failed: 0,
        cancelled: 0,
        timed_out: 0,
        resource_exhausted: 0,
        infrastructure_failed: 0,
        cleanup_failed: 0,
      },
    };
  }

  metricsSnapshot() {
    return structuredClone(this.metrics);
  }

  recordRejection() {
    this.metrics.rejected_requests += 1;
  }

  recordTerminal(receipt) {
    if (Object.hasOwn(this.metrics.outcomes, receipt.status))
      this.metrics.outcomes[receipt.status] += 1;
    this.metrics.cleanup_attempts += receipt.cleanup.cleanup_attempts;
    this.metrics.cleanup_failures += Number(
      receipt.cleanup.status === "failed",
    );
    this.metrics.duration_ms_total += receipt.duration_ms;
    this.metrics.remaining_labeled_resources =
      receipt.cleanup.final_labeled_resource_count ?? 0;
  }

  async readiness() {
    this.metrics.readiness_checks += 1;
    try {
      await this.engine.ping();
      const runtimeImageId = await this.engine.resolveRuntime();
      return {
        status: "ready",
        protocol_version: 1,
        runtime_image_id: runtimeImageId,
        metrics: this.metricsSnapshot(),
      };
    } catch (error) {
      this.metrics.readiness_failures += 1;
      throw error;
    }
  }

  async execute(validated) {
    const executionId = validated.payload.execution_id;
    const requestDigest = validated.request.request_digest;
    const sourceArchiveSha256 = validated.payload.source_archive_sha256;
    const claimed = this.claims.get(executionId);
    if (claimed !== undefined) {
      const receipt =
        claimed.receipt ??
        (await new Promise((resolve) => claimed.waiters.push(resolve)));
      if (receipt === null)
        throw new Error("Concurrent execution receipt creation failed");
      if (
        claimed.requestDigest !== requestDigest ||
        claimed.sourceArchiveSha256 !== sourceArchiveSha256
      ) {
        this.metrics.request_digest_conflicts += 1;
        return { conflict: true, receipt };
      }
      this.metrics.replays += 1;
      return {
        pending: !TERMINAL.has(receipt.status),
        receipt,
      };
    }
    const claim = {
      requestDigest,
      sourceArchiveSha256,
      receipt: null,
      waiters: [],
    };
    this.claims.set(executionId, claim);
    let receipt;
    try {
      const existing = await this.store.read(executionId);
      if (existing !== null) {
        claim.receipt = existing;
        for (const resolve of claim.waiters) resolve(existing);
        if (
          existing.request_digest !== requestDigest ||
          existing.source_archive_sha256 !== sourceArchiveSha256
        ) {
          this.metrics.request_digest_conflicts += 1;
          return { conflict: true, receipt: existing };
        }
        this.metrics.replays += 1;
        if (TERMINAL.has(existing.status)) return { receipt: existing };
        return { pending: true, receipt: existing };
      }
      receipt = {
        contract_version: 1,
        execution_id: executionId,
        request_digest: validated.request.request_digest,
        source_archive_sha256: validated.payload.source_archive_sha256,
        profile_id: "static-website",
        profile_version: 1,
        state: "received",
        status: "pending",
        runtime_image_id: null,
        container_id: null,
        source_volume_name: null,
        effective_limits: null,
        effective_limits_digest: null,
        termination_reason: "runner did not start",
        exit_code: null,
        duration_ms: 0,
        route_results: [],
        process_results: null,
        stdout_excerpt: "",
        stderr_excerpt: "",
        stdout_sha256: emptyHash(),
        stderr_sha256: emptyHash(),
        cleanup: {
          status: "pending",
          cleanup_attempts: 0,
          final_labeled_resource_count: null,
          receipt_digest: null,
          started_at: null,
          finished_at: null,
        },
        cancel_requested_at: null,
        created_at: now(),
        started_at: null,
        finished_at: null,
        acknowledged_at: null,
      };
      await this.store.write(receipt);
      claim.receipt = receipt;
      for (const resolve of claim.waiters) resolve(receipt);
    } catch (error) {
      for (const resolve of claim.waiters) resolve(null);
      throw error;
    } finally {
      this.claims.delete(executionId);
    }
    const control = {
      cancelled: false,
      cancelRequestedAt: null,
      containerId: null,
    };
    const operation = this.run(validated, receipt, control).finally(() => {
      this.active.delete(executionId);
    });
    this.active.set(executionId, { control, operation });
    this.metrics.launches += 1;
    const completed = await operation;
    this.recordTerminal(completed);
    return { receipt: completed };
  }

  async run(validated, receipt, control) {
    const started = Date.now();
    let outcome = "infrastructure_failed";
    let reason = "runner infrastructure failed";
    let container = null;
    let sourceVolume = null;
    let exitCode = null;
    let routeResults = [];
    let logs = {
      stdout: "",
      stderr: "",
      stdout_sha256: emptyHash(),
      stderr_sha256: emptyHash(),
    };
    let effectiveLimits = null;
    try {
      const imageId = await this.engine.resolveRuntime();
      receipt.runtime_image_id = imageId;
      receipt.state = "creating";
      await this.store.write(receipt);
      if (control.cancelled) {
        outcome = "cancelled";
        reason = "cancelled before child creation";
      } else {
        sourceVolume = await this.engine.prepareSource(
          validated.payload.execution_id,
          imageId,
          validated.files,
          validated.payload.routes,
        );
        receipt.source_volume_name = sourceVolume;
        await this.store.write(receipt);
        container = await this.engine.create(
          validated.payload.execution_id,
          validated.request.request_digest,
          imageId,
          sourceVolume,
        );
        control.containerId = container.id;
        receipt.container_id = container.id;
        await this.store.write(receipt);
        const inspected = await this.engine.inspect(container.id);
        effectiveLimits = this.engine.validateControls(
          inspected,
          imageId,
          sourceVolume,
        );
        receipt.effective_limits = effectiveLimits;
        receipt.effective_limits_digest = sha256(
          Buffer.from(canonicalJson(effectiveLimits)),
        );
        if (control.cancelled) {
          outcome = "cancelled";
          reason = "cancelled before child start";
        } else {
          await this.engine.start(container.id);
          receipt.state = "running";
          receipt.started_at = now();
          await this.store.write(receipt);
          const wait = this.engine
            .wait(container.id)
            .then((code) => ({ code, timedOut: false }));
          let timeoutHandle;
          const timeout = new Promise((resolve) => {
            timeoutHandle = setTimeout(
              () => resolve({ code: null, timedOut: true }),
              this.wallTimeoutMs,
            );
          });
          let termination;
          try {
            termination = await Promise.race([wait, timeout]);
          } finally {
            clearTimeout(timeoutHandle);
          }
          if (termination.timedOut) {
            await this.engine.stop(container.id);
            exitCode = await this.engine.wait(container.id);
            outcome = "timed_out";
            reason = "wall timeout exceeded";
          } else {
            exitCode = termination.code;
            const stopped = await this.engine.inspect(container.id);
            logs = await this.engine.logs(container.id);
            if (control.cancelled) {
              outcome = "cancelled";
              reason = "owner cancellation requested";
            } else if (stopped.State?.OOMKilled) {
              outcome = "resource_exhausted";
              reason = "memory ceiling exhausted";
            } else {
              const harness = parseHarness(
                logs.stdout,
                validated.payload.routes,
              );
              routeResults = harness.route_results;
              ({ outcome, reason } = classifyHarnessOutcome(exitCode, harness));
            }
          }
        }
      }
    } catch (error) {
      outcome = control.cancelled ? "cancelled" : "infrastructure_failed";
      reason = control.cancelled
        ? "owner cancellation requested"
        : boundedReason(error.message);
      if (!control.cancelled) {
        receipt.process_results = {
          infrastructure_error: String(error.message)
            .replaceAll(/[\r\n\t]+/g, " ")
            .slice(0, 500),
        };
      }
    } finally {
      receipt.state = "cleaning";
      receipt.cleanup.started_at = now();
      await this.store.write(receipt);
      let cleanupError = null;
      for (let attempt = 1; attempt <= 3; attempt += 1) {
        receipt.cleanup.cleanup_attempts = attempt;
        try {
          if (container !== null)
            await this.engine.removeContainer(container.id);
          if (sourceVolume !== null)
            await this.engine.removeVolume(sourceVolume);
          let remaining = await this.engine.listManaged(
            validated.payload.execution_id,
          );
          for (const item of remaining) await this.engine.removeResource(item);
          remaining = await this.engine.listManaged(
            validated.payload.execution_id,
          );
          receipt.cleanup.final_labeled_resource_count = remaining.length;
          if (remaining.length === 0) break;
        } catch (error) {
          cleanupError = error;
        }
      }
      receipt.cleanup.finished_at = now();
      if (receipt.cleanup.final_labeled_resource_count === 0) {
        receipt.cleanup.status = "verified";
      } else {
        receipt.cleanup.status = "failed";
        receipt.process_results = {
          ...(receipt.process_results ?? {}),
          original_outcome: outcome,
        };
        outcome = "cleanup_failed";
        reason = boundedReason(
          cleanupError?.message ?? "cleanup could not prove zero resources",
        );
      }
      receipt.cleanup.receipt_digest = sha256(
        Buffer.from(
          canonicalJson({
            execution_id: validated.payload.execution_id,
            status: receipt.cleanup.status,
            attempts: receipt.cleanup.cleanup_attempts,
            resources: receipt.cleanup.final_labeled_resource_count,
            finished_at: receipt.cleanup.finished_at,
          }),
        ),
      );
      receipt.state = "terminal";
      receipt.status = outcome;
      receipt.termination_reason = boundedReason(reason);
      receipt.exit_code = Number.isInteger(exitCode) ? exitCode : null;
      receipt.duration_ms = Math.min(Date.now() - started, 120_000);
      receipt.route_results = routeResults;
      receipt.stdout_excerpt = logs.stdout.slice(0, 65_536);
      receipt.stderr_excerpt = logs.stderr.slice(0, 65_536);
      receipt.stdout_sha256 = logs.stdout_sha256;
      receipt.stderr_sha256 = logs.stderr_sha256;
      receipt.cancel_requested_at ??= control.cancelRequestedAt;
      receipt.finished_at = now();
      receipt.container_id = null;
      receipt.source_volume_name = null;
      await this.store.write(receipt);
    }
    return receipt;
  }

  async inspect(executionId) {
    return this.store.read(executionId);
  }

  async cancel(executionId) {
    this.metrics.cancellation_requests += 1;
    let receipt = await this.store.read(executionId);
    const claim = this.claims.get(executionId);
    if (receipt === null && claim !== undefined) {
      receipt =
        claim.receipt ??
        (await new Promise((resolve) => claim.waiters.push(resolve)));
    }
    if (receipt === null) return this.verifyAbsent(executionId);
    if (TERMINAL.has(receipt.status)) return receipt;
    receipt.cancel_requested_at = now();
    await this.store.write(receipt);
    const active = this.active.get(executionId);
    if (active !== undefined) {
      active.control.cancelled = true;
      active.control.cancelRequestedAt = receipt.cancel_requested_at;
      if (active.control.containerId !== null)
        await this.engine.stop(active.control.containerId);
    }
    return receipt;
  }

  async verifyAbsent(executionId) {
    if (this.active.has(executionId) || this.claims.has(executionId)) {
      throw new Error("Cannot prove absence while an execution is active");
    }
    const startedAt = now();
    let remaining = await this.engine.listManaged(executionId);
    let attempts = 0;
    for (
      let attempt = 1;
      attempt <= 3 && remaining.length !== 0;
      attempt += 1
    ) {
      attempts = attempt;
      for (const item of remaining) await this.engine.removeResource(item);
      remaining = await this.engine.listManaged(executionId);
    }
    if (remaining.length !== 0) {
      throw new Error("Runner could not prove execution resource absence");
    }
    const finishedAt = now();
    return {
      contract_version: 1,
      execution_id: executionId,
      status: "absent",
      cleanup: {
        status: "verified",
        cleanup_attempts: Math.max(attempts, 1),
        final_labeled_resource_count: 0,
        receipt_digest: sha256(
          Buffer.from(
            canonicalJson({
              execution_id: executionId,
              absent: true,
              attempts: Math.max(attempts, 1),
              resources: 0,
              finished_at: finishedAt,
            }),
          ),
        ),
        started_at: startedAt,
        finished_at: finishedAt,
      },
    };
  }

  async acknowledge(executionId) {
    const receipt = await this.store.read(executionId);
    if (receipt === null) return null;
    if (!TERMINAL.has(receipt.status))
      throw new Error("Only terminal receipts can be acknowledged");
    receipt.acknowledged_at = now();
    await this.store.write(receipt);
    return receipt;
  }

  async janitor() {
    this.metrics.janitor_runs += 1;
    const resources = await this.engine.listManaged();
    let removed = 0;
    for (const resource of resources) {
      const executionId = resource.Labels?.["foundora.sandbox.execution"];
      if (executionId && this.active.has(executionId)) continue;
      await this.engine.removeResource(resource);
      removed += 1;
    }
    const receipts = await this.store.list();
    for (const receipt of receipts) {
      if (
        TERMINAL.has(receipt.status) ||
        this.active.has(receipt.execution_id)
      ) {
        continue;
      }
      const remaining = await this.engine.listManaged(receipt.execution_id);
      if (remaining.length !== 0) {
        throw new Error("Janitor could not prove zero execution resources");
      }
      receipt.state = "terminal";
      receipt.status = "infrastructure_failed";
      receipt.termination_reason =
        "startup janitor reconciled an interrupted run";
      receipt.finished_at = now();
      receipt.container_id = null;
      receipt.source_volume_name = null;
      receipt.cleanup.status = "verified";
      receipt.cleanup.cleanup_attempts += 1;
      receipt.cleanup.final_labeled_resource_count = 0;
      receipt.cleanup.started_at ??= now();
      receipt.cleanup.finished_at = now();
      receipt.cleanup.receipt_digest = sha256(
        Buffer.from(
          canonicalJson({
            execution_id: receipt.execution_id,
            janitor: true,
            resources: 0,
          }),
        ),
      );
      await this.store.write(receipt);
    }
    this.metrics.janitor_removals += removed;
    this.metrics.remaining_labeled_resources = (
      await this.engine.listManaged()
    ).length;
    return removed;
  }
}
