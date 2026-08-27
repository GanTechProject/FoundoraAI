import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { chromium } from "playwright";

const CONTRACT_VERSION = 1;
const SITE_ROOT = "/site";
const INPUT_PATH = "/foundora-input/routes.json";
const HOST = "127.0.0.1";
const PORT = 4173;
const MAX_ROUTES = 16;
const MAX_ERRORS = 32;
const MAX_ERROR_CHARACTERS = 500;
const ROUTE_TIMEOUT_MS = 3_000;
const SETTLE_TIME_MS = 100;
const ROUTE_PATTERN = /^\/(?:[a-z0-9][a-z0-9_-]*\/?)*$/;

const CONTENT_TYPES = new Map([
  [".css", "text/css; charset=utf-8"],
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".txt", "text/plain; charset=utf-8"],
]);

function boundedError(value) {
  return String(value)
    .replace(/[\u0000-\u001f\u007f]/g, " ")
    .slice(0, MAX_ERROR_CHARACTERS);
}

function appendError(errors, value) {
  if (errors.length < MAX_ERRORS) {
    errors.push(boundedError(value));
  }
}

function validateRoute(route) {
  return (
    typeof route === "string" &&
    (route === "/" || (ROUTE_PATTERN.test(route) && !route.endsWith("/")))
  );
}

async function loadInput() {
  const raw = await readFile(INPUT_PATH, "utf8");
  const value = JSON.parse(raw);
  if (
    value === null ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    Object.keys(value).sort().join(",") !== "contract_version,routes" ||
    value.contract_version !== CONTRACT_VERSION ||
    !Array.isArray(value.routes) ||
    value.routes.length < 1 ||
    value.routes.length > MAX_ROUTES ||
    value.routes.some((route) => !validateRoute(route)) ||
    new Set(value.routes).size !== value.routes.length
  ) {
    throw new Error("Sandbox route input does not match contract version 1");
  }
  return Object.freeze([...value.routes]);
}

async function resolveSiteFile(requestPath) {
  const urlPath = decodeURIComponent(requestPath);
  const relative = urlPath.endsWith("/") ? `${urlPath}index.html` : urlPath;
  const candidate = path.resolve(SITE_ROOT, `.${relative}`);
  if (
    candidate !== SITE_ROOT &&
    !candidate.startsWith(`${SITE_ROOT}${path.sep}`)
  ) {
    return null;
  }
  let details;
  try {
    details = await stat(candidate);
  } catch {
    return null;
  }
  if (
    !details.isFile() ||
    !CONTENT_TYPES.has(path.extname(candidate).toLowerCase())
  ) {
    return null;
  }
  return candidate;
}

function startServer() {
  const server = createServer(async (request, response) => {
    try {
      const requestUrl = new URL(request.url ?? "/", `http://${HOST}:${PORT}`);
      const filename = await resolveSiteFile(requestUrl.pathname);
      if (filename === null) {
        response.writeHead(404, {
          "content-type": "text/plain; charset=utf-8",
        });
        response.end("Not found");
        return;
      }
      const body = await readFile(filename);
      response.writeHead(200, {
        "cache-control": "no-store",
        "content-length": body.length,
        "content-type": CONTENT_TYPES.get(path.extname(filename).toLowerCase()),
        "x-content-type-options": "nosniff",
      });
      response.end(body);
    } catch {
      response.writeHead(400, { "content-type": "text/plain; charset=utf-8" });
      response.end("Invalid request");
    }
  });
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(PORT, HOST, () => resolve(server));
  });
}

async function inspectRoute(browser, route) {
  const runtimeErrors = [];
  const page = await browser.newPage({
    acceptDownloads: false,
    serviceWorkers: "block",
  });
  page.on("console", (message) => {
    if (message.type() === "error") {
      appendError(runtimeErrors, `console: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) =>
    appendError(runtimeErrors, `page: ${error.message}`),
  );
  page.on("requestfailed", (request) => {
    const failure = request.failure();
    appendError(
      runtimeErrors,
      `request: ${request.url()} (${failure?.errorText ?? "failed"})`,
    );
  });
  await page.route("**/*", async (requestRoute) => {
    const requested = new URL(requestRoute.request().url());
    if (requested.origin === `http://${HOST}:${PORT}`) {
      await requestRoute.continue();
      return;
    }
    appendError(runtimeErrors, `blocked external request: ${requested.origin}`);
    await requestRoute.abort("blockedbyclient");
  });

  let httpStatus = null;
  let documentReadyState = null;
  let scriptCount = 0;
  let executionMarker = false;
  try {
    const response = await page.goto(`http://${HOST}:${PORT}${route}`, {
      timeout: ROUTE_TIMEOUT_MS,
      waitUntil: "load",
    });
    httpStatus = response?.status() ?? null;
    await page.waitForTimeout(SETTLE_TIME_MS);
    const pageFacts = await page.evaluate(() => ({
      documentReadyState: document.readyState,
      executionMarker: globalThis.__foundoraExecuted === true,
      scriptCount: document.scripts.length,
    }));
    documentReadyState = pageFacts.documentReadyState;
    executionMarker = pageFacts.executionMarker;
    scriptCount = pageFacts.scriptCount;
    if (httpStatus !== 200) {
      appendError(
        runtimeErrors,
        `route returned HTTP ${httpStatus ?? "unknown"}`,
      );
    }
  } catch (error) {
    appendError(runtimeErrors, error instanceof Error ? error.message : error);
  } finally {
    await page.close().catch(() => undefined);
  }

  return {
    document_ready_state: documentReadyState,
    execution_marker: executionMarker,
    http_status: httpStatus,
    route,
    runtime_errors: runtimeErrors,
    script_count: scriptCount,
    status:
      httpStatus === 200 &&
      documentReadyState === "complete" &&
      runtimeErrors.length === 0
        ? "passed"
        : "failed",
  };
}

async function main() {
  const started = performance.now();
  const routes = await loadInput();
  const server = await startServer();
  let browser;
  try {
    browser = await chromium.launch({
      chromiumSandbox: true,
      headless: true,
    });
    const routeResults = [];
    for (const route of routes) {
      routeResults.push(await inspectRoute(browser, route));
    }
    const passed = routeResults.every((item) => item.status === "passed");
    process.stdout.write(
      `${JSON.stringify({
        contract_version: CONTRACT_VERSION,
        duration_ms: Math.round(performance.now() - started),
        route_results: routeResults,
        status: passed ? "passed" : "failed",
      })}\n`,
    );
    process.exitCode = passed ? 0 : 1;
  } finally {
    await browser?.close().catch(() => undefined);
    await new Promise((resolve) => server.close(resolve));
  }
}

main().catch((error) => {
  process.stderr.write(
    `${boundedError(error instanceof Error ? error.message : error)}\n`,
  );
  process.exitCode = 2;
});
