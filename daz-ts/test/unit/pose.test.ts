import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { NodeNotFoundError } from "../../src/exceptions.js";
import { DazPose } from "../../src/pose.js";
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

const skeletonLookup =
  'var _skel=null,_skels=Scene.getSkeletonList();for(var _i=0;_i<_skels.length;_i++){if(_skels[_i].getName() === "Genesis9"){_skel=_skels[_i];break;}}';

function skel(): DazSkeleton {
  return new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
}

describe("DazPose.capture", () => {
  it("generates the exact capture script and returns a populated DazPose", async () => {
    const fetchMock = stub({ bones: { hip: [0, 2.3, 0] }, morphs: { PHMSmileFull: 0.8 }, props: {} });
    const pose = await DazPose.capture(skel());
    expect(pose.figure).toBe("Genesis9");
    expect(pose.bones).toEqual({ hip: [0, 2.3, 0] });
    expect(pose.morphs).toEqual({ PHMSmileFull: 0.8 });
    expect(pose.props).toEqual({});
    const script = scriptOf(fetchMock);
    expect(script.startsWith(`(function(){\n\n            ${skeletonLookup}\n            if (!_skel) return null;`)).toBe(
      true,
    );
    expect(script).toContain("getRawValue");
    expect(script).toContain('m.className() === "DzMorph"');
  });

  it("throws NodeNotFoundError when the skeleton lookup returns null", async () => {
    stub(null);
    await expect(DazPose.capture(skel())).rejects.toThrow(NodeNotFoundError);
  });
});

describe("DazPose.toDict / fromDict", () => {
  it("round-trips figure/bones/morphs/props", () => {
    const pose = new DazPose("Genesis9", { hip: [1, 2, 3] }, { Smile: 0.5 }, { Scale: 1.2 });
    const dict = pose.toDict();
    expect(dict).toEqual({ figure: "Genesis9", bones: { hip: [1, 2, 3] }, morphs: { Smile: 0.5 }, props: { Scale: 1.2 } });
    const restored = DazPose.fromDict(dict);
    expect(restored.figure).toBe("Genesis9");
    expect(restored.bones).toEqual({ hip: [1, 2, 3] });
  });

  it("fromDict defaults missing fields", () => {
    const restored = DazPose.fromDict({});
    expect(restored).toEqual(new DazPose("", {}, {}, {}));
  });
});

describe("DazPose.lerp", () => {
  it("interpolates bones/morphs/props, treating missing keys as zero", () => {
    const a = new DazPose("A", { hip: [0, 0, 0] }, { Smile: 0.0 }, {});
    const b = new DazPose("B", { hip: [10, 0, 0], chest: [0, 5, 0] }, { Smile: 1.0 }, { Scale: 2.0 });
    const mid = a.lerp(b, 0.5);
    expect(mid.figure).toBe("A");
    expect(mid.bones.hip).toEqual([5, 0, 0]);
    expect(mid.bones.chest).toEqual([0, 2.5, 0]);
    expect(mid.morphs.Smile).toBe(0.5);
    expect(mid.props.Scale).toBe(1.0);
  });

  it("t=0 yields self, t=1 yields other", () => {
    const a = new DazPose("A", { hip: [1, 2, 3] }, { Smile: 0.2 }, {});
    const b = new DazPose("B", { hip: [4, 5, 6] }, { Smile: 0.8 }, {});
    expect(a.lerp(b, 0).bones.hip).toEqual([1, 2, 3]);
    expect(a.lerp(b, 1).bones.hip).toEqual([4, 5, 6]);
  });
});

describe("DazPose.apply", () => {
  it("generates the exact apply script with retryOnBusy defaulting to true", async () => {
    const fetchMock = stub(true);
    const pose = new DazPose("Genesis9", { hip: [1, 2, 3] }, { Smile: 0.5 }, { Scale: 1.0 });
    await pose.apply(skel());
    const script = scriptOf(fetchMock);
    expect(script).toContain('var _bones  = {"hip":[1,2,3]};');
    expect(script).toContain('var _morphs = {"Smile":0.5};');
    expect(script).toContain('var _props  = {"Scale":1};');
    expect(script).toContain("if (xyz !== undefined)");
    expect(script).not.toContain("xyz = _bones[b.getName()] || [0, 0, 0]");
  });

  it("rounds channel values to 6 decimal places", async () => {
    const fetchMock = stub(true);
    const pose = new DazPose("G", { hip: [1 / 3, 0, 0] }, {}, {});
    await pose.apply(skel());
    expect(scriptOf(fetchMock)).toContain('"hip":[0.333333,0,0]');
  });
});

describe("DazPose.applyFull", () => {
  it("generates the exact applyFull script that zeros absent channels", async () => {
    const fetchMock = stub(true);
    const pose = new DazPose("Genesis9", { hip: [1, 2, 3] }, {}, {});
    await pose.applyFull(skel());
    const script = scriptOf(fetchMock);
    expect(script).toContain("var xyz = _bones[b.getName()] || [0, 0, 0];");
    expect(script).toContain("var _v = (v !== undefined) ? v : 0;");
  });
});

describe("DazPose.toString", () => {
  it("summarizes figure and channel counts", () => {
    const pose = new DazPose("Genesis9", { hip: [1, 0, 0] }, { Smile: 0.5, Frown: 0.1 }, {});
    expect(pose.toString()).toBe('DazPose(figure="Genesis9", bones=1, morphs=2, props=0)');
  });
});
