import assert from "node:assert/strict";
import test from "node:test";
import { Buffer } from "node:buffer";
import { createHash, randomUUID } from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { canonicalJson, sha256 } from "../src/canonical.mjs";
import { validateExecuteEnvelope } from "../src/contracts.mjs";
import { buildSourceTar } from "../src/engine.mjs";
import { ReceiptStore } from "../src/receipts.mjs";
import {
  classifyHarnessOutcome,
  parseHarness,
  SandboxRunner,
} from "../src/runner.mjs";

function envelope() {
  const content = "<!doctype html><html><body><main>ok</main></body></html>";
  const bytes = Buffer.from(content);
  const fileHash = sha256(bytes);
  const files = [
    {
      content,
      media_type: "text/html",
      path: "index.html",
      sha256: fileHash,
      size_bytes: bytes.length,
    },
  ];
  const tree = createHash("sha256")
    .update("index.html\0")
    .update(`${fileHash}\0`)
    .digest("hex");
  const archive = Buffer.from(canonicalJson({ contract_version: 1, files }));
  const payload = {
    execution_id: randomUUID(),
    business_id: randomUUID(),
    website_project_id: randomUUID(),
    website_project_version: 1,
    website_specification_id: randomUUID(),
    website_specification_version: 1,
    profile_id: "static-website",
    profile_version: 1,
    source_digest: tree,
    build_digest: tree,
    source_archive_sha256: sha256(archive),
    source_archive_size_bytes: archive.length,
    routes: ["/"],
  };
  return {
    contract_version: 1,
    operation: "execute",
    request: {
      contract_version: 1,
      payload,
      request_digest: sha256(Buffer.from(canonicalJson(payload))),
    },
    source_archive: {
      data: archive.toString("base64"),
      encoding: "base64",
      media_type: "application/vnd.foundora.sandbox-source+json",
    },
  };
}

test("canonical JSON is stable and the execute envelope pins its source", () => {
  const value = envelope();
  const validated = validateExecuteEnvelope(value);
  assert.equal(
    validated.payload.execution_id,
    value.request.payload.execution_id,
  );
  assert.equal(validated.files[0].path, "index.html");
});

test("unknown fields and digest changes fail closed", () => {
  const extra = envelope();
  extra.command = ["sh"];
  assert.throws(() => validateExecuteEnvelope(extra), /undeclared/);

  const changed = envelope();
  changed.request.payload.routes = ["/missing"];
  assert.throws(() => validateExecuteEnvelope(changed), /request digest/);
});

test("source tar contains no host path and is deterministically bounded", () => {
  const validated = validateExecuteEnvelope(envelope());
  const first = buildSourceTar(validated.files, validated.payload.routes);
  const second = buildSourceTar(validated.files, validated.payload.routes);
  assert.deepEqual(first, second);
  assert.ok(first.includes(Buffer.from("site/index.html")));
  assert.ok(first.includes(Buffer.from("foundora-input/routes.json")));
  assert.ok(first.length < 10_000);
});

test("harness results reject undeclared and out-of-bound evidence", () => {
  const result = {
    contract_version: 1,
    duration_ms: 10,
    route_results: [
      {
        document_ready_state: "complete",
        execution_marker: true,
        http_status: 200,
        route: "/",
        runtime_errors: [],
        script_count: 1,
        status: "passed",
      },
    ],
    status: "passed",
  };
  assert.equal(parseHarness(JSON.stringify(result), ["/"]).allPassed, true);
  result.route_results[0].override = true;
  assert.throws(() => parseHarness(JSON.stringify(result), ["/"]), /malformed/);
  delete result.route_results[0].override;
  result.duration_ms = 60_001;
  assert.throws(
    () => parseHarness(JSON.stringify(result), ["/"]),
    /contract version/,
  );
});

test("a bounded browser allocation failure is classified as resource exhaustion", () => {
  const outcome = classifyHarnessOutcome(1, {
    allPassed: false,
    route_results: [
      {
        runtime_errors: ["page: Array buffer allocation failed"],
      },
    ],
  });

  assert.deepEqual(outcome, {
    outcome: "resource_exhausted",
    reason: "memory allocation failed under the fixed ceiling",
  });
});

test("janitor reconciles an interrupted receipt only after zero resources", async () => {
  const receipt = {
    execution_id: randomUUID(),
    status: "running",
    state: "running",
    cleanup: {
      status: "pending",
      cleanup_attempts: 0,
      final_labeled_resource_count: null,
      receipt_digest: null,
      started_at: null,
      finished_at: null,
    },
  };
  const resources = [
    {
      Id: "child",
      Labels: { "foundora.sandbox.execution": receipt.execution_id },
      resourceType: "container",
    },
    {
      Id: "source",
      Labels: { "foundora.sandbox.execution": receipt.execution_id },
      resourceType: "volume",
    },
  ];
  const engine = {
    async listManaged(executionId = null) {
      return resources.filter(
        (item) =>
          executionId === null ||
          item.Labels["foundora.sandbox.execution"] === executionId,
      );
    },
    async removeResource(resource) {
      resources.splice(resources.indexOf(resource), 1);
    },
  };
  const store = {
    async list() {
      return [receipt];
    },
    async write(value) {
      Object.assign(receipt, structuredClone(value));
    },
  };
  const runner = new SandboxRunner({ engine, store });
  assert.equal(await runner.janitor(), 2);
  assert.equal(receipt.status, "infrastructure_failed");
  assert.equal(receipt.cleanup.status, "verified");
  assert.equal(receipt.cleanup.final_labeled_resource_count, 0);
  assert.deepEqual(runner.metricsSnapshot(), {
    launches: 0,
    replays: 0,
    rejected_requests: 0,
    request_digest_conflicts: 0,
    cancellation_requests: 0,
    cleanup_attempts: 0,
    cleanup_failures: 0,
    janitor_runs: 1,
    janitor_removals: 2,
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
  });
});

test("readiness resolves the reviewed image and exposes only bounded counters", async () => {
  const engine = {
    async ping() {},
    async resolveRuntime() {
      return `sha256:${"a".repeat(64)}`;
    },
  };
  const runner = new SandboxRunner({ engine, store: {} });
  const readiness = await runner.readiness();
  assert.equal(readiness.status, "ready");
  assert.equal(readiness.runtime_image_id, `sha256:${"a".repeat(64)}`);
  assert.equal(readiness.metrics.readiness_checks, 1);
  assert.equal(readiness.metrics.readiness_failures, 0);
  assert.equal(JSON.stringify(readiness).includes("token"), false);
});

test("receipt corruption fails closed during reconciliation", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "foundora-receipts-"));
  try {
    const store = new ReceiptStore(root);
    await fs.writeFile(path.join(root, `${randomUUID()}.json`), "{broken\n");
    await assert.rejects(() => store.list(), SyntaxError);
  } finally {
    await fs.rm(root, { recursive: true });
  }
});

test("malformed runtime output still reaches a verified zero-resource terminal receipt", async () => {
  const value = envelope();
  const validated = validateExecuteEnvelope(value);
  const writes = [];
  const engine = {
    async resolveRuntime() {
      return `sha256:${"b".repeat(64)}`;
    },
    async prepareSource() {
      return `foundora-sandbox-source-${validated.payload.execution_id}`;
    },
    async create() {
      return { id: "child", name: "child" };
    },
    async inspect() {
      return { State: { OOMKilled: false } };
    },
    validateControls() {
      return { network_mode: "none" };
    },
    async start() {},
    async wait() {
      return 0;
    },
    async logs() {
      return {
        stdout: "not-json\n",
        stderr: "",
        stdout_sha256: sha256(Buffer.from("not-json\n")),
        stderr_sha256: sha256(Buffer.alloc(0)),
      };
    },
    async removeContainer() {},
    async removeVolume() {},
    async listManaged() {
      return [];
    },
  };
  const store = {
    async read() {
      return null;
    },
    async write(receipt) {
      writes.push(structuredClone(receipt));
    },
  };

  const result = await new SandboxRunner({ engine, store }).execute(validated);

  assert.equal(result.receipt.status, "infrastructure_failed");
  assert.equal(result.receipt.cleanup.status, "verified");
  assert.equal(result.receipt.cleanup.final_labeled_resource_count, 0);
  assert.equal(result.receipt.container_id, null);
  assert.equal(result.receipt.source_volume_name, null);
  assert.match(result.receipt.cleanup.receipt_digest, /^[a-f0-9]{64}$/);
  assert.ok(writes.some((receipt) => receipt.state === "cleaning"));
});

test("the fixed wall watchdog stops a hung child and verifies cleanup", async () => {
  const validated = validateExecuteEnvelope(envelope());
  let waitCalls = 0;
  let stopCalls = 0;
  const engine = {
    async resolveRuntime() {
      return `sha256:${"c".repeat(64)}`;
    },
    async prepareSource() {
      return `foundora-sandbox-source-${validated.payload.execution_id}`;
    },
    async create() {
      return { id: "hung-child", name: "hung-child" };
    },
    async inspect() {
      return { State: { OOMKilled: false } };
    },
    validateControls() {
      return { wall_timeout_seconds: 60 };
    },
    async start() {},
    async wait() {
      waitCalls += 1;
      if (waitCalls === 1) return new Promise(() => undefined);
      return 143;
    },
    async stop() {
      stopCalls += 1;
    },
    async removeContainer() {},
    async removeVolume() {},
    async listManaged() {
      return [];
    },
  };
  const store = {
    async read() {
      return null;
    },
    async write() {},
  };
  assert.throws(
    () => new SandboxRunner({ engine, store, wallTimeoutMs: 60_001 }),
    /between 1 and 60000ms/,
  );

  const result = await new SandboxRunner({
    engine,
    store,
    wallTimeoutMs: 5,
  }).execute(validated);

  assert.equal(result.receipt.status, "timed_out");
  assert.equal(result.receipt.termination_reason, "wall timeout exceeded");
  assert.equal(result.receipt.exit_code, 143);
  assert.equal(stopCalls, 1);
  assert.equal(result.receipt.cleanup.status, "verified");
  assert.equal(result.receipt.cleanup.final_labeled_resource_count, 0);
});
