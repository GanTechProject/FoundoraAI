import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";

const manifestBytes = await readFile(
  new URL("runtime-manifest.json", import.meta.url),
);
const manifest = JSON.parse(manifestBytes);
const manifestSha256 = createHash("sha256").update(manifestBytes).digest("hex");
const dockerfile = await readFile(
  new URL("Dockerfile", import.meta.url),
  "utf8",
);
const harness = await readFile(new URL("runtime.mjs", import.meta.url), "utf8");
const lockfile = JSON.parse(
  await readFile(new URL("package-lock.json", import.meta.url), "utf8"),
);
const seccompBytes = await readFile(
  new URL("seccomp-profile.json", import.meta.url),
);
const seccomp = JSON.parse(seccompBytes);
const pythonContracts = await readFile(
  new URL("../api/src/foundora/sandbox/contracts.py", import.meta.url),
  "utf8",
);

test("runtime dependencies and image are pinned to the reviewed manifest", () => {
  assert.equal(
    manifestSha256,
    "ab73f13726b30608c83a212d7cf762ee2b74986f535680377560db69286d8601",
  );
  assert.equal(manifest.playwright_version, "1.62.0");
  assert.equal(
    lockfile.packages["node_modules/playwright"].version,
    manifest.playwright_version,
  );
  assert.equal(
    lockfile.packages["node_modules/playwright-core"].version,
    manifest.playwright_version,
  );
  assert.match(
    dockerfile,
    new RegExp(`FROM ${manifest.base_image.replaceAll("/", "\\/")}`),
  );
  assert.match(dockerfile, new RegExp(manifestSha256));
  assert.match(pythonContracts, new RegExp(manifestSha256));
});

test("seccomp profile is fail closed and pins browser namespace rules", () => {
  assert.equal(
    createHash("sha256").update(seccompBytes).digest("hex"),
    manifest.seccomp_profile_sha256,
  );
  assert.equal(seccomp.defaultAction, "SCMP_ACT_ERRNO");
  const namespaceRule = seccomp.syscalls.find(
    (entry) => entry.comment === "Allow create user namespaces",
  );
  assert.equal(namespaceRule.action, "SCMP_ACT_ALLOW");
  assert.deepEqual(namespaceRule.names, ["clone", "setns", "unshare"]);
});

test("fixed harness enables Chromium sandbox and exposes no command override", () => {
  assert.match(dockerfile, /USER pwuser/);
  assert.match(
    dockerfile,
    /ENTRYPOINT \["node", "\/opt\/foundora\/runtime\/runtime\.mjs"\]/,
  );
  assert.match(harness, /chromiumSandbox: true/);
  assert.doesNotMatch(harness, /--no-sandbox/);
  assert.doesNotMatch(dockerfile, /CMD /);
});

test("adversarial fixture corpus remains complete", async () => {
  const fixtureNames = [
    "cpu",
    "environment",
    "filesystem",
    "javascript-error",
    "memory",
    "network",
    "output",
    "passing",
    "processes",
    "timeout",
  ];
  for (const name of fixtureNames) {
    const fixture = await readFile(
      new URL(`fixtures/${name}/index.html`, import.meta.url),
      "utf8",
    );
    assert.match(fixture, /<!doctype html>/i);
  }
});
