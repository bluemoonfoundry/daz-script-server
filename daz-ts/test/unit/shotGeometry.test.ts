import { describe, expect, it } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazNode } from "../../src/node.js";
import { Vec3 } from "../../src/math3.js";
import { lookAtEuler, resolveTarget, sphericalOffset } from "../../src/shotGeometry.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function stub(value: unknown) {
  return async () => jsonResponse({ success: true, result: value, output: [], request_id: "r", duration_ms: 0 });
}

describe("sphericalOffset", () => {
  it("azimuth=0, elevation=0 sits on the target's +Z side", () => {
    const target = new Vec3(0, 0, 0);
    const result = sphericalOffset(target, 0, 0, 100);
    expect(result.x).toBeCloseTo(0);
    expect(result.y).toBeCloseTo(0);
    expect(result.z).toBeCloseTo(100);
  });

  it("elevation=90 sits directly above the target regardless of azimuth", () => {
    const target = new Vec3(1, 2, 3);
    const result = sphericalOffset(target, 45, 90, 50);
    expect(result.x).toBeCloseTo(1);
    expect(result.y).toBeCloseTo(52);
    expect(result.z).toBeCloseTo(3);
  });

  it("azimuth=90 sweeps toward +X", () => {
    const result = sphericalOffset(new Vec3(0, 0, 0), 90, 0, 10);
    expect(result.x).toBeCloseTo(10);
    expect(result.y).toBeCloseTo(0);
    expect(result.z).toBeCloseTo(0);
  });
});

describe("lookAtEuler", () => {
  it("returns (0, 0, 0) for a node placed via sphericalOffset(az=0, el=0) aimed back at target", () => {
    const target = new Vec3(0, 0, 0);
    const from = sphericalOffset(target, 0, 0, 100);
    const [pitch, yaw, roll] = lookAtEuler(from, target);
    expect(pitch).toBeCloseTo(0);
    expect(yaw).toBeCloseTo(0);
    expect(roll).toBe(0.0);
  });

  it("yaw sign matches DazLight.direction() convention (y=+90 -> direction (-1,0,~0))", () => {
    const from = new Vec3(0, 0, 0);
    const to = new Vec3(-1, 0, 0);
    const [, yaw] = lookAtEuler(from, to);
    expect(yaw).toBeCloseTo(90);
  });

  it("yaw is 0 when direction is purely vertical (horizontalDist ~ 0)", () => {
    const [pitch, yaw, roll] = lookAtEuler(new Vec3(0, 0, 0), new Vec3(0, 5, 0));
    expect(pitch).toBeCloseTo(90);
    expect(yaw).toBe(0.0);
    expect(roll).toBe(0.0);
  });
});

describe("resolveTarget", () => {
  it("returns a Vec3 target as-is when verticalOffsetCm is 0", async () => {
    const v = new Vec3(1, 2, 3);
    const result = await resolveTarget(v);
    expect(result).toBe(v);
  });

  it("adds verticalOffsetCm to the Y component of a Vec3 target", async () => {
    const result = await resolveTarget(new Vec3(1, 2, 3), 10);
    expect(result.x).toBe(1);
    expect(result.y).toBe(12);
    expect(result.z).toBe(3);
  });

  it("resolves a DazNode target via position(), raised by verticalOffsetCm", async () => {
    globalThis.fetch = stub({ x: 1, y: 2, z: 3 }) as unknown as typeof fetch;
    const node = new DazNode(new DazClient({ token: "" }), { value: "Camera1", kind: "name" });
    const result = await resolveTarget(node, 5);
    expect(result.x).toBe(1);
    expect(result.y).toBe(7);
    expect(result.z).toBe(3);
  });

  it("throws if the DazNode target has no position", async () => {
    globalThis.fetch = stub(null) as unknown as typeof fetch;
    const node = new DazNode(new DazClient({ token: "" }), { value: "Missing", kind: "name" });
    await expect(resolveTarget(node)).rejects.toThrow(
      "resolveTarget: target node has no position (it may not exist in the scene)",
    );
  });
});
