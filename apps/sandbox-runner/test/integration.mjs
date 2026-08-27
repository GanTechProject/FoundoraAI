import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import { Buffer } from "node:buffer";
import { createHash, randomUUID } from "node:crypto";
import { canonicalJson, sha256 } from "../src/canonical.mjs";

const ROOT = "/opt/foundora/sandbox-fixtures";
const TOKEN = process.env.FOUNDORA_SANDBOX_RUNNER_TOKEN;
const URL = "http://127.0.0.1:8080";
const MEDIA = new Map([
  [".html", "text/html"],
  [".css", "text/css"],
  [".js", "text/javascript"],
  [".json", "application/json"],
  [".txt", "text/plain"],
]);

async function files(root, relative = "") {
  const result = [];
  for (const entry of await fs.readdir(path.join(root, relative), {
    withFileTypes: true,
  })) {
    const child = path.posix.join(relative, entry.name);
    if (entry.isDirectory()) result.push(...(await files(root, child)));
    else {
      const content = await fs.readFile(path.join(root, child), "utf8");
      const encoded = Buffer.from(content);
      result.push({
        content,
        media_type: MEDIA.get(path.extname(child)),
        path: child,
        sha256: sha256(encoded),
        size_bytes: encoded.length,
      });
    }
  }
  return result.sort((left, right) => left.path.localeCompare(right.path));
}

function treeDigest(sourceFiles) {
  const hash = createHash("sha256");
  for (const file of sourceFiles) {
    hash.update(file.path);
    hash.update("\0");
    hash.update(file.sha256);
    hash.update("\0");
  }
  return hash.digest("hex");
}

async function envelope(fixture, executionId = randomUUID()) {
  const sourceFiles = await files(path.join(ROOT, fixture));
  const archive = Buffer.from(
    canonicalJson({ contract_version: 1, files: sourceFiles }),
  );
  const tree = treeDigest(sourceFiles);
  const payload = {
    execution_id: executionId,
    business_id: "20000000-0000-4000-8000-000000000002",
    website_project_id: "30000000-0000-4000-8000-000000000003",
    website_project_version: 1,
    website_specification_id: "40000000-0000-4000-8000-000000000004",
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

async function call(method, requestPath, body, token = TOKEN) {
  const response = await fetch(`${URL}${requestPath}`, {
    method,
    headers: {
      authorization: `Bearer ${token}`,
      "content-type": "application/json",
    },
    body: body === null ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(90_000),
  });
  return { status: response.status, body: await response.json() };
}

function assertVerifiedCleanup(receipt) {
  assert.equal(receipt.cleanup.status, "verified");
  assert.ok(receipt.cleanup.cleanup_attempts >= 1);
  assert.equal(receipt.cleanup.final_labeled_resource_count, 0);
  assert.match(receipt.cleanup.receipt_digest, /^[a-f0-9]{64}$/);
}

function assertFixedLimits(limits) {
  assert.deepEqual(limits, {
    cpu_nanos: 1_000_000_000,
    memory_bytes: 536_870_912,
    memory_swap_bytes: 536_870_912,
    pids_limit: 128,
    wall_timeout_seconds: 60,
    termination_grace_seconds: 3,
    tmpfs_bytes: 134_217_728,
    dev_shm_bytes: 134_217_728,
    combined_output_bytes: 1_048_576,
    network_mode: "none",
    read_only_root_filesystem: true,
    source_read_only: true,
    run_as_non_root: true,
    drop_all_capabilities: true,
    add_sys_chroot_capability: true,
    no_new_privileges: true,
    no_host_namespaces: true,
    no_devices: true,
    seccomp_profile_sha256:
      "17e2d449ab7c2c6fefc5b9f978224a49929864eb1d5a42f4f9002266c9300de2",
  });
}

function assertBoundedEvidence(receipt) {
  assert.ok(receipt.stdout_excerpt.length <= 65_536);
  assert.ok(receipt.stderr_excerpt.length <= 65_536);
  assert.match(receipt.stdout_sha256, /^[a-f0-9]{64}$/);
  assert.match(receipt.stderr_sha256, /^[a-f0-9]{64}$/);
  assert.equal(JSON.stringify(receipt).includes(TOKEN), false);
}

const unauthorized = await call(
  "POST",
  "/v1/executions",
  await envelope("passing"),
  "wrong",
);
assert.equal(unauthorized.status, 401);

const override = await envelope("passing");
override.command = ["sh"];
assert.equal((await call("POST", "/v1/executions", override)).status, 400);

const unknown = await envelope("passing");
unknown.request.payload.profile_id = "arbitrary";
assert.equal((await call("POST", "/v1/executions", unknown)).status, 400);

const absentExecutionId = randomUUID();
const absent = await call(
  "POST",
  `/v1/executions/${absentExecutionId}/cancel`,
  { contract_version: 1 },
);
assert.equal(absent.status, 200);
assert.equal(absent.body.status, "absent");
assertVerifiedCleanup(absent.body);

const passing = await envelope("passing");
const passed = await call("POST", "/v1/executions", passing);
assert.equal(passed.status, 200);
assert.equal(passed.body.status, "succeeded");
assertVerifiedCleanup(passed.body);
assertFixedLimits(passed.body.effective_limits);
assertBoundedEvidence(passed.body);
assert.match(passed.body.runtime_image_id, /^sha256:[a-f0-9]{64}$/);

const replay = await call("POST", "/v1/executions", passing);
assert.equal(replay.status, 200);
assert.equal(replay.body.request_digest, passed.body.request_digest);
assert.equal(replay.body.created_at, passed.body.created_at);

const conflict = structuredClone(passing);
conflict.request.payload.website_project_id = randomUUID();
conflict.request.request_digest = sha256(
  Buffer.from(canonicalJson(conflict.request.payload)),
);
assert.equal((await call("POST", "/v1/executions", conflict)).status, 409);

const concurrent = await envelope("passing");
const concurrentCalls = await Promise.all([
  call("POST", "/v1/executions", concurrent),
  call("POST", "/v1/executions", concurrent),
]);
assert.deepEqual(concurrentCalls.map((item) => item.status).sort(), [200, 202]);
assert.ok(
  concurrentCalls.every(
    (item) => item.body.request_digest === concurrent.request.request_digest,
  ),
);
const concurrentFinal = await call(
  "GET",
  `/v1/executions/${concurrent.request.payload.execution_id}`,
  null,
);
assert.equal(concurrentFinal.status, 200);
assert.equal(concurrentFinal.body.status, "succeeded");
assertVerifiedCleanup(concurrentFinal.body);

for (const fixture of [
  "javascript-error",
  "network",
  "environment",
  "filesystem",
  "processes",
  "output",
  "cpu",
]) {
  const result = await call("POST", "/v1/executions", await envelope(fixture));
  assert.equal(result.status, 200);
  assert.ok(
    ["failed", "resource_exhausted", "infrastructure_failed"].includes(
      result.body.status,
    ),
    `${fixture} unexpectedly returned ${result.body.status}`,
  );
  assertVerifiedCleanup(result.body);
  assertFixedLimits(result.body.effective_limits);
  assertBoundedEvidence(result.body);
}

const memory = await call("POST", "/v1/executions", await envelope("memory"));
assert.equal(memory.status, 200);
assert.equal(memory.body.status, "resource_exhausted");
assert.match(memory.body.termination_reason, /memory allocation failed/);
assertVerifiedCleanup(memory.body);
assertFixedLimits(memory.body.effective_limits);
assertBoundedEvidence(memory.body);

const cancellable = await envelope("timeout");
const executing = call("POST", "/v1/executions", cancellable);
await new Promise((resolve) => setTimeout(resolve, 750));
const cancellation = await call(
  "POST",
  `/v1/executions/${cancellable.request.payload.execution_id}/cancel`,
  { contract_version: 1 },
);
assert.equal(cancellation.status, 202);
const cancelled = await executing;
assert.equal(cancelled.status, 200);
assert.equal(cancelled.body.status, "cancelled");
assertVerifiedCleanup(cancelled.body);
assertBoundedEvidence(cancelled.body);

const acknowledged = await call(
  "POST",
  `/v1/executions/${passing.request.payload.execution_id}/acknowledge`,
  { contract_version: 1 },
);
assert.equal(acknowledged.status, 200);
assert.ok(acknowledged.body.acknowledged_at);

const readiness = await call("GET", "/health/ready", null);
assert.equal(readiness.status, 200);
assert.equal(readiness.body.status, "ready");
assert.ok(readiness.body.metrics.launches >= 11);
assert.ok(readiness.body.metrics.replays >= 2);
assert.ok(readiness.body.metrics.rejected_requests >= 3);
assert.ok(readiness.body.metrics.request_digest_conflicts >= 1);
assert.ok(readiness.body.metrics.cancellation_requests >= 2);
assert.ok(readiness.body.metrics.outcomes.succeeded >= 2);
assert.ok(readiness.body.metrics.outcomes.failed >= 7);
assert.ok(readiness.body.metrics.outcomes.cancelled >= 1);
assert.equal(readiness.body.metrics.cleanup_failures, 0);
assert.equal(readiness.body.metrics.remaining_labeled_resources, 0);
assert.equal(JSON.stringify(readiness.body).includes(TOKEN), false);

const receiptRoot = "/var/lib/foundora-sandbox/receipts";
const forbiddenCredentialNames =
  /OPENAI_API_KEY|GEMINI_API_KEY|ANTHROPIC_API_KEY|FOUNDORA_DATABASE_URL|FOUNDORA_REDIS_URL|FOUNDORA_SANDBOX_RUNNER_TOKEN/;
for (const receiptName of await fs.readdir(receiptRoot)) {
  if (!receiptName.endsWith(".json")) continue;
  const receiptBody = await fs.readFile(
    path.join(receiptRoot, receiptName),
    "utf8",
  );
  assert.equal(forbiddenCredentialNames.test(receiptBody), false);
}

process.stdout.write("Sandbox runner integration probes passed\n");
