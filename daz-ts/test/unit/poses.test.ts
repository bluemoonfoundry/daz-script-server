import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazNode } from "../../src/node.js";
import { DazPose } from "../../src/pose.js";
import { applyPose, resetTransforms, zeroFigure } from "../../src/poses.js";
import { DazSkeleton } from "../../src/skeleton.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}
afterEach(() => vi.unstubAllGlobals());
function stub(value: unknown) {
  const fetchMock = vi
    .fn()
    .mockImplementation(() =>
      Promise.resolve(jsonResponse({ success: true, result: value, output: [], request_id: "r", duration_ms: 0 })),
    );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
function scriptOf(fetchMock: ReturnType<typeof vi.fn>, callIndex = 0): string {
  return JSON.parse(fetchMock.mock.calls[callIndex][1].body as string).script;
}

function skel(): DazSkeleton {
  return new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
}

describe("applyPose", () => {
  it("applies a DazPose instance directly", async () => {
    const fetchMock = stub(true);
    const pose = new DazPose("Genesis9", { hip: [1, 0, 0] }, {}, {});
    await applyPose(skel(), pose);
    expect(scriptOf(fetchMock)).toContain('"hip":[1,0,0]');
  });

  it("loads a pose from a JSON file path before applying it", async () => {
    const fetchMock = stub(true);
    const tmpFile = path.join(os.tmpdir(), `daz-ts-pose-test-${Date.now()}.json`);
    fs.writeFileSync(tmpFile, JSON.stringify({ figure: "Genesis9", bones: { chest: [0, 5, 0] }, morphs: {}, props: {} }));
    try {
      await applyPose(skel(), tmpFile);
      expect(scriptOf(fetchMock)).toContain('"chest":[0,5,0]');
    } finally {
      fs.unlinkSync(tmpFile);
    }
  });
});

describe("resetTransforms", () => {
  it("generates the exact setTransform script for zero position/rotation and unit scale", async () => {
    const fetchMock = stub(undefined);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Camera1", kind: "name" });
    await resetTransforms(node);
    const script = scriptOf(fetchMock);
    expect(script).toContain("_node.setLocalPos(new DzVec3(0, 0, 0));");
    expect(script).toContain(
      "_node.getXRotControl().setValue(0); _node.getYRotControl().setValue(0); _node.getZRotControl().setValue(0);",
    );
    expect(script).toContain(
      "_node.getXScaleControl().setValue(1); _node.getYScaleControl().setValue(1); _node.getZScaleControl().setValue(1);",
    );
  });
});

describe("zeroFigure", () => {
  it("defaults to zeroing bones/morphs only, via DazSkeleton.zeroBonesAndMorphs()", async () => {
    const fetchMock = stub(undefined);
    await zeroFigure(skel());
    const script = scriptOf(fetchMock);
    expect(script).toContain('_b.getXRotControl().setValue(0);');
    expect(script).toContain('m.className() === "DzMorph"');
    expect(script).not.toContain("_props");
  });

  it("includeProps: true applies an empty pose via applyFull, zeroing every channel", async () => {
    const fetchMock = stub(true);
    await zeroFigure(skel(), { includeProps: true });
    const script = scriptOf(fetchMock);
    expect(script).toContain("var xyz = _bones[b.getName()] || [0, 0, 0];");
    expect(script).toContain("var _v = (v !== undefined) ? v : 0;");
  });
});
