import { describe, expect, it } from "vitest";

import { isReadinessPayload, toServiceViews } from "./readiness";

describe("readiness payload handling", () => {
  it("accepts and maps real component states", () => {
    const payload = {
      status: "ready" as const,
      checks: {
        postgresql: { status: "up" as const },
        redis: { status: "up" as const, detail: "PONG" },
      },
    };

    expect(isReadinessPayload(payload)).toBe(true);
    expect(toServiceViews(payload)).toEqual([
      { name: "postgresql", status: "up", detail: "Reachable" },
      { name: "redis", status: "up", detail: "PONG" },
    ]);
  });

  it("rejects an invented or malformed state", () => {
    expect(
      isReadinessPayload({
        status: "ready",
        checks: { redis: { status: "maybe" } },
      }),
    ).toBe(false);
  });
});
