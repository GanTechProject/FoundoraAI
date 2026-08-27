import path from "node:path";
import { Buffer } from "node:buffer";
import { createHash } from "node:crypto";
import {
  ContractError,
  canonicalJson,
  exactKeys,
  sha256,
} from "./canonical.mjs";

const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SHA = /^[a-f0-9]{64}$/;
const ROUTE = /^\/(?:[a-z0-9][a-z0-9_-]*\/?)*$/;
const MEDIA = new Map([
  [".html", "text/html"],
  [".css", "text/css"],
  [".js", "text/javascript"],
  [".json", "application/json"],
  [".txt", "text/plain"],
]);
const PAYLOAD_KEYS = [
  "execution_id",
  "business_id",
  "website_project_id",
  "website_project_version",
  "website_specification_id",
  "website_specification_version",
  "profile_id",
  "profile_version",
  "source_digest",
  "build_digest",
  "source_archive_sha256",
  "source_archive_size_bytes",
  "routes",
];

function positiveInteger(value, label) {
  if (!Number.isSafeInteger(value) || value < 1)
    throw new ContractError(`${label} is invalid`);
}

function digestTree(files) {
  const hash = createHash("sha256");
  for (const file of [...files].sort((left, right) =>
    left.path.localeCompare(right.path),
  )) {
    hash.update(file.path);
    hash.update("\0");
    hash.update(file.sha256);
    hash.update("\0");
  }
  return hash.digest("hex");
}

function routeFile(route) {
  return route === "/" ? "index.html" : `${route.slice(1)}/index.html`;
}

export function validateExecuteEnvelope(value) {
  exactKeys(
    value,
    ["contract_version", "operation", "request", "source_archive"],
    "envelope",
  );
  if (value.contract_version !== 1 || value.operation !== "execute") {
    throw new ContractError("execute envelope contract is unsupported");
  }
  exactKeys(
    value.request,
    ["contract_version", "payload", "request_digest"],
    "request",
  );
  if (
    value.request.contract_version !== 1 ||
    !SHA.test(value.request.request_digest)
  ) {
    throw new ContractError("request contract is invalid");
  }
  const payload = value.request.payload;
  exactKeys(payload, PAYLOAD_KEYS, "payload");
  for (const field of [
    "execution_id",
    "business_id",
    "website_project_id",
    "website_specification_id",
  ]) {
    if (typeof payload[field] !== "string" || !UUID.test(payload[field])) {
      throw new ContractError(`${field} is invalid`);
    }
  }
  positiveInteger(payload.website_project_version, "website_project_version");
  positiveInteger(
    payload.website_specification_version,
    "website_specification_version",
  );
  if (
    payload.profile_id !== "static-website" ||
    payload.profile_version !== 1
  ) {
    throw new ContractError("sandbox profile is unknown");
  }
  for (const field of [
    "source_digest",
    "build_digest",
    "source_archive_sha256",
  ]) {
    if (typeof payload[field] !== "string" || !SHA.test(payload[field])) {
      throw new ContractError(`${field} is invalid`);
    }
  }
  if (payload.source_digest !== payload.build_digest) {
    throw new ContractError(
      "static website source and build digests must match",
    );
  }
  if (
    !Number.isSafeInteger(payload.source_archive_size_bytes) ||
    payload.source_archive_size_bytes < 1 ||
    payload.source_archive_size_bytes > 768_000
  ) {
    throw new ContractError("source archive size is invalid");
  }
  if (
    !Array.isArray(payload.routes) ||
    payload.routes.length < 1 ||
    payload.routes.length > 16
  ) {
    throw new ContractError("routes are invalid");
  }
  const routeSet = new Set();
  for (const route of payload.routes) {
    if (
      typeof route !== "string" ||
      (route !== "/" && (!ROUTE.test(route) || route.endsWith("/"))) ||
      routeSet.has(route)
    ) {
      throw new ContractError("routes are not normalized and unique");
    }
    routeSet.add(route);
  }
  if (
    sha256(Buffer.from(canonicalJson(payload))) !== value.request.request_digest
  ) {
    throw new ContractError(
      "request digest does not match the canonical payload",
    );
  }
  exactKeys(
    value.source_archive,
    ["data", "encoding", "media_type"],
    "source_archive",
  );
  if (
    value.source_archive.encoding !== "base64" ||
    value.source_archive.media_type !==
      "application/vnd.foundora.sandbox-source+json" ||
    typeof value.source_archive.data !== "string"
  ) {
    throw new ContractError("source archive encoding is invalid");
  }
  const archive = Buffer.from(value.source_archive.data, "base64");
  if (
    archive.length !== payload.source_archive_size_bytes ||
    sha256(archive) !== payload.source_archive_sha256
  ) {
    throw new ContractError(
      "source archive does not match its pinned evidence",
    );
  }
  let bundle;
  try {
    bundle = JSON.parse(archive.toString("utf8"));
  } catch {
    throw new ContractError("source archive is not valid UTF-8 JSON");
  }
  if (!archive.equals(Buffer.from(canonicalJson(bundle)))) {
    throw new ContractError("source archive is not canonically encoded");
  }
  exactKeys(bundle, ["contract_version", "files"], "source bundle");
  if (bundle.contract_version !== 1 || !Array.isArray(bundle.files)) {
    throw new ContractError("source bundle contract is invalid");
  }
  if (bundle.files.length < 1 || bundle.files.length > 48) {
    throw new ContractError("source bundle file count is invalid");
  }
  const paths = new Set();
  let totalBytes = 0;
  for (const file of bundle.files) {
    exactKeys(
      file,
      ["content", "media_type", "path", "sha256", "size_bytes"],
      "source file",
    );
    const extension =
      typeof file.path === "string"
        ? path.posix.extname(file.path).toLowerCase()
        : "";
    if (
      typeof file.path !== "string" ||
      file.path.length > 240 ||
      file.path.startsWith("/") ||
      file.path.includes("\\") ||
      path.posix.normalize(file.path) !== file.path ||
      file.path
        .split("/")
        .some((part) => !part || part === "." || part === "..") ||
      paths.has(file.path) ||
      MEDIA.get(extension) !== file.media_type ||
      typeof file.content !== "string" ||
      !Number.isSafeInteger(file.size_bytes) ||
      typeof file.sha256 !== "string" ||
      !SHA.test(file.sha256)
    ) {
      throw new ContractError("source file metadata is invalid");
    }
    const content = Buffer.from(file.content, "utf8");
    if (
      content.length < 1 ||
      content.length > 96_000 ||
      content.length !== file.size_bytes
    ) {
      throw new ContractError("source file size is invalid");
    }
    if (sha256(content) !== file.sha256)
      throw new ContractError("source file hash is invalid");
    totalBytes += content.length;
    paths.add(file.path);
  }
  if (
    totalBytes > 512_000 ||
    digestTree(bundle.files) !== payload.source_digest
  ) {
    throw new ContractError("source tree does not match its pinned digest");
  }
  for (const route of payload.routes) {
    if (!paths.has(routeFile(route)))
      throw new ContractError("route has no source document");
  }
  return { request: value.request, payload, files: bundle.files, archive };
}

export function validateControlBody(value) {
  exactKeys(value, ["contract_version"], "control body");
  if (value.contract_version !== 1)
    throw new ContractError("control contract is unsupported");
}
