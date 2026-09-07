import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazBone } from "../../src/bone.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}
afterEach(() => vi.unstubAllGlobals());

function stub(value: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ success: true, result: value, output: [], request_id: "r", duration_ms: 0 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("DazBone", () => {
  it("fromLocator wraps a pre-built skeleton-relative locator and keeps its name as identifier", async () => {
    stub([10, 20, 30]);
    const bone = DazBone.fromLocator(new DazClient({ token: "" }), "BONELOC", "r_forearm");
    expect(bone.identifier).toEqual({ value: "r_forearm", kind: "name" });
    await bone.localEuler();
  });

  it("localEuler reads the three rotation controls via a node-body-from-locator wrapper", async () => {
    const fetchMock = stub([1, 2, 3]);
    const bone = DazBone.fromLocator(new DazClient({ token: "" }), "BONELOC", "r_forearm");
    expect(await bone.localEuler()).toEqual([1, 2, 3]);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\nvar _node = BONELOC;\nif (!_node) return null;\n" +
      "return [_node.getXRotControl().getValue(), _node.getYRotControl().getValue(), _node.getZRotControl().getValue()];\n})()",
    );
  });

  it("setLocalRotation writes all three rotation controls with exact-string assertion", async () => {
    const fetchMock = stub(null);
    const bone = DazBone.fromLocator(new DazClient({ token: "" }), "BONELOC", "r_forearm");
    await bone.setLocalRotation(1, 2, 3);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\nvar _node = BONELOC;\nif (!_node) return null;\n" +
      "_node.getXRotControl().setValue(1); _node.getYRotControl().setValue(2); _node.getZRotControl().setValue(3);\n})()",
    );
  });

  it("localRotation reads the quaternion rotation", async () => {
    const fetchMock = stub({ x: 0, y: 0, z: 0.7071, w: 0.7071 });
    const bone = DazBone.fromLocator(new DazClient({ token: "" }), "BONELOC", "r_forearm");
    expect(await bone.localRotation()).toEqual({ x: 0, y: 0, z: 0.7071, w: 0.7071 });
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\nvar _node = BONELOC;\nif (!_node) return null;\n" +
      "var r = _node.getLocalRot(); return {x: r.x, y: r.y, z: r.z, w: r.w};\n})()",
    );
  });

  it("localPosition reads the local position as {x, y, z}", async () => {
    const fetchMock = stub({ x: 1.5, y: 2.5, z: 3.5 });
    const bone = DazBone.fromLocator(new DazClient({ token: "" }), "BONELOC", "r_forearm");
    expect(await bone.localPosition()).toEqual({ x: 1.5, y: 2.5, z: 3.5 });
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\nvar _node = BONELOC;\nif (!_node) return null;\n" +
      "var p = _node.getLocalPos(); return {x: p.x, y: p.y, z: p.z};\n})()",
    );
  });

  it("rotationOrder reads the rotation order string", async () => {
    const fetchMock = stub("XYZ");
    const bone = DazBone.fromLocator(new DazClient({ token: "" }), "BONELOC", "r_forearm");
    expect(await bone.rotationOrder()).toEqual("XYZ");
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\nvar _node = BONELOC;\nif (!_node) return null;\n" +
      "return _node.getRotationOrder();\n})()",
    );
  });

  it("getSkeleton returns null when getSkeleton() resolves to nothing", async () => {
    stub(null);
    const bone = DazBone.fromLocator(new DazClient({ token: "" }), "BONELOC", "r_forearm");
    expect(await bone.getSkeleton()).toBeNull();
  });
});
