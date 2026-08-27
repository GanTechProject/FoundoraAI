import fs from "node:fs/promises";
import http from "node:http";
import { timingSafeEqual } from "node:crypto";
import { ContractError } from "./canonical.mjs";
import { validateControlBody, validateExecuteEnvelope } from "./contracts.mjs";
import { DockerEngine } from "./engine.mjs";
import { ReceiptStore } from "./receipts.mjs";
import { SandboxRunner } from "./runner.mjs";

const HOST = process.env.FOUNDORA_SANDBOX_RUNNER_HOST ?? "0.0.0.0";
const PORT = Number.parseInt(
  process.env.FOUNDORA_SANDBOX_RUNNER_PORT ?? "8080",
  10,
);
const TOKEN = process.env.FOUNDORA_SANDBOX_RUNNER_TOKEN ?? "";
const SOCKET =
  process.env.FOUNDORA_SANDBOX_ENGINE_SOCKET ?? "/var/run/docker.sock";
const RECEIPTS =
  process.env.FOUNDORA_SANDBOX_RECEIPT_PATH ??
  "/var/lib/foundora-sandbox/receipts";
const RUNTIME =
  process.env.FOUNDORA_SANDBOX_RUNTIME_IMAGE ??
  "foundora-sandbox-runtime:phase22";
const SECCOMP_PATH = "/opt/foundora/sandbox/seccomp-profile.json";
const SECCOMP_SHA256 =
  "17e2d449ab7c2c6fefc5b9f978224a49929864eb1d5a42f4f9002266c9300de2";
const MAX_BODY_BYTES = 1_200_000;
const EXECUTION_PATH =
  /^\/v1\/executions\/([0-9a-f-]{36})(?:\/(cancel|acknowledge))?$/i;

if (TOKEN.length < 32)
  throw new Error(
    "FOUNDORA_SANDBOX_RUNNER_TOKEN must contain at least 32 characters",
  );

function authorized(request) {
  const expected = Buffer.from(`Bearer ${TOKEN}`);
  const actual = Buffer.from(request.headers.authorization ?? "");
  return actual.length === expected.length && timingSafeEqual(actual, expected);
}

function send(response, status, body) {
  const data = Buffer.from(JSON.stringify(body));
  response.writeHead(status, {
    "cache-control": "no-store",
    "content-length": data.length,
    "content-type": "application/json",
    "x-content-type-options": "nosniff",
  });
  response.end(data);
}

function readJson(request) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    request.on("data", (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        reject(new ContractError("request body exceeds its boundary"));
        request.destroy();
        return;
      }
      chunks.push(chunk);
    });
    request.on("end", () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString("utf8")));
      } catch {
        reject(new ContractError("request body is not valid JSON"));
      }
    });
    request.on("error", reject);
  });
}

function audit(event, details = {}) {
  process.stdout.write(
    `${JSON.stringify({ timestamp: new Date().toISOString(), event, ...details })}\n`,
  );
}

const seccompBytes = await fs.readFile(SECCOMP_PATH);
const { sha256 } = await import("./canonical.mjs");
if (sha256(seccompBytes) !== SECCOMP_SHA256)
  throw new Error("Seccomp profile digest mismatch");
const engine = new DockerEngine({
  socketPath: SOCKET,
  seccompProfile: seccompBytes.toString("utf8"),
  seccompSha256: SECCOMP_SHA256,
  runtimeImage: RUNTIME,
});
const store = new ReceiptStore(RECEIPTS);
await store.initialize();
const runner = new SandboxRunner({ engine, store });
const startupJanitorRemovals = await runner.janitor();
audit("sandbox_janitor_completed", {
  trigger: "startup",
  removed_resources: startupJanitorRemovals,
});
await runner.readiness();

const server = http.createServer(async (request, response) => {
  try {
    if (request.method === "GET" && request.url === "/health/ready") {
      send(response, 200, await runner.readiness());
      return;
    }
    if (!authorized(request)) {
      runner.recordRejection();
      send(response, 401, { error: "unauthorized" });
      return;
    }
    if (request.method === "POST" && request.url === "/v1/executions") {
      const validated = validateExecuteEnvelope(await readJson(request));
      const result = await runner.execute(validated);
      if (result.conflict)
        send(response, 409, { error: "execution identity conflict" });
      else send(response, result.pending ? 202 : 200, result.receipt);
      audit("sandbox_execute", {
        execution_id: validated.payload.execution_id,
        status: result.receipt.status,
        replay: Boolean(result.pending || result.conflict),
        request_digest_conflict: Boolean(result.conflict),
        duration_ms: result.receipt.duration_ms,
        cleanup_status: result.receipt.cleanup.status,
        cleanup_attempts: result.receipt.cleanup.cleanup_attempts,
        remaining_resources:
          result.receipt.cleanup.final_labeled_resource_count,
      });
      return;
    }
    const match = EXECUTION_PATH.exec(request.url ?? "");
    if (match && request.method === "GET" && match[2] === undefined) {
      const receipt = await runner.inspect(match[1]);
      send(
        response,
        receipt === null ? 404 : 200,
        receipt ?? { error: "not found" },
      );
      return;
    }
    if (match && request.method === "POST" && match[2] === "cancel") {
      validateControlBody(await readJson(request));
      const receipt = await runner.cancel(match[1]);
      send(response, receipt.status === "absent" ? 200 : 202, receipt);
      audit("sandbox_cancel", { execution_id: match[1] });
      return;
    }
    if (match && request.method === "POST" && match[2] === "acknowledge") {
      validateControlBody(await readJson(request));
      const receipt = await runner.acknowledge(match[1]);
      send(
        response,
        receipt === null ? 404 : 200,
        receipt ?? { error: "not found" },
      );
      return;
    }
    send(response, 404, { error: "not found" });
  } catch (error) {
    const status = error instanceof ContractError ? 400 : 500;
    if (status === 400) runner.recordRejection();
    audit("sandbox_request_error", { error_type: error.constructor.name });
    send(response, status, {
      error: status === 400 ? error.message : "runner operation failed",
    });
  }
});

server.listen(PORT, HOST, () =>
  audit("sandbox_runner_started", { host: HOST, port: PORT }),
);
const janitor = setInterval(() => {
  runner
    .janitor()
    .then((removed) => {
      if (removed > 0)
        audit("sandbox_janitor_completed", {
          trigger: "periodic",
          removed_resources: removed,
        });
    })
    .catch((error) =>
      audit("sandbox_janitor_failed", { error_type: error.constructor.name }),
    );
}, 30_000);
janitor.unref();

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    server.close(() => process.exit(0));
    setTimeout(() => process.exit(1), 5_000).unref();
  });
}
