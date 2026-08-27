import { createHash } from "node:crypto";

function normalize(value) {
  if (Array.isArray(value)) return value.map(normalize);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, normalize(value[key])]),
    );
  }
  return value;
}

export function canonicalJson(value) {
  return JSON.stringify(normalize(value));
}

export function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

export function exactKeys(value, keys, label) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new ContractError(`${label} must be an object`);
  }
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (
    actual.length !== expected.length ||
    actual.some((key, index) => key !== expected[index])
  ) {
    throw new ContractError(`${label} has undeclared or missing fields`);
  }
}

export class ContractError extends Error {}
