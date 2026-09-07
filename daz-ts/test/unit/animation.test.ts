import { afterEach, describe, expect, it, vi } from "vitest";
import { DazAnimation } from "../../src/animation.js";
import { DazClient } from "../../src/client.js";
import { NodeNotFoundError } from "../../src/exceptions.js";
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

const CAPTURE_RESULT = {
  figure: "Genesis 9",
  frame_range: { start: 0, end: 2 },
  bones: ["hip"],
  frames: [
    { frame: 0, rotations: [[0, 0, 0]], morphs: {} },
    { frame: 1, rotations: [[5, 0, 0]], morphs: { Smile: 0.5 } },
    { frame: 2, rotations: [[10, 0, 0]], morphs: {} },
  ],
};

describe("DazAnimation.capture", () => {
  it("generates a script that scrubs the play range and restores the original frame", async () => {
    const fetchMock = stub(CAPTURE_RESULT);
    const anim = await DazAnimation.capture(skel());
    expect(anim.figure).toBe("Genesis 9");
    expect(anim.frameRange).toEqual({ start: 0, end: 2 });
    expect(anim.bones).toEqual(["hip"]);
    expect(anim.frames).toHaveLength(3);
    const script = scriptOf(fetchMock);
    expect(script).toContain("if (false) {"); // includeMorphs defaults to false
    expect(script).toContain("var _origFrame = Scene.getFrame();");
    expect(script).toContain("Scene.setFrame(_origFrame);");
  });

  it("passes includeMorphs=true through to the generated script", async () => {
    const fetchMock = stub(CAPTURE_RESULT);
    await DazAnimation.capture(skel(), true);
    expect(scriptOf(fetchMock)).toContain("if (true) {");
  });

  it("throws NodeNotFoundError when the skeleton is not found", async () => {
    stub(null);
    await expect(DazAnimation.capture(skel())).rejects.toThrow(NodeNotFoundError);
  });
});

describe("DazAnimation.clip", () => {
  it("keeps only frames within [start, end] inclusive", () => {
    const anim = new DazAnimation("G", { start: 0, end: 2 }, ["hip"], CAPTURE_RESULT.frames);
    const clipped = anim.clip(1, 2);
    expect(clipped.frames.map((f) => f.frame)).toEqual([1, 2]);
    expect(clipped.frameRange).toEqual({ start: 1, end: 2 });
  });

  it("falls back to the requested range when no frames match", () => {
    const anim = new DazAnimation("G", { start: 0, end: 2 }, ["hip"], CAPTURE_RESULT.frames);
    const clipped = anim.clip(10, 20);
    expect(clipped.frames).toEqual([]);
    expect(clipped.frameRange).toEqual({ start: 10, end: 20 });
  });
});

describe("DazAnimation.blend", () => {
  it("interpolates rotations and morphs frame-by-frame", () => {
    const a = new DazAnimation("G", { start: 0, end: 1 }, ["hip"], [
      { frame: 0, rotations: [[0, 0, 0]], morphs: { Smile: 0.0 } },
      { frame: 1, rotations: [[0, 0, 0]], morphs: {} },
    ]);
    const b = new DazAnimation("G", { start: 0, end: 1 }, ["hip"], [
      { frame: 0, rotations: [[10, 0, 0]], morphs: { Smile: 1.0 } },
      { frame: 1, rotations: [[10, 0, 0]], morphs: {} },
    ]);
    const blended = a.blend(b, 0.5);
    expect(blended.frames[0].rotations).toEqual([[5, 0, 0]]);
    expect(blended.frames[0].morphs).toEqual({ Smile: 0.5 });
  });

  it("throws when bone lists differ", () => {
    const a = new DazAnimation("G", { start: 0, end: 0 }, ["hip"], []);
    const b = new DazAnimation("G", { start: 0, end: 0 }, ["chest"], []);
    expect(() => a.blend(b, 0.5)).toThrow("Cannot blend animations with different bone lists (1 vs 1 bones)");
  });

  it("truncates to the shorter clip when frame counts differ", () => {
    const a = new DazAnimation("G", { start: 0, end: 1 }, ["hip"], [
      { frame: 0, rotations: [[0, 0, 0]], morphs: {} },
      { frame: 1, rotations: [[0, 0, 0]], morphs: {} },
    ]);
    const b = new DazAnimation("G", { start: 0, end: 0 }, ["hip"], [{ frame: 0, rotations: [[10, 0, 0]], morphs: {} }]);
    const blended = a.blend(b, 1.0);
    expect(blended.frames).toHaveLength(1);
  });
});

describe("DazAnimation.asPose / apply", () => {
  it("extracts a sparse pose from the given frame index", () => {
    const anim = new DazAnimation("G", { start: 0, end: 2 }, ["hip"], CAPTURE_RESULT.frames);
    const pose = anim.asPose(1);
    expect(pose.figure).toBe("G");
    expect(pose.bones).toEqual({ hip: [5, 0, 0] });
    expect(pose.morphs).toEqual({ Smile: 0.5 });
  });

  it("omits bones whose rotation is all-zero", () => {
    const anim = new DazAnimation("G", { start: 0, end: 0 }, ["hip"], [
      { frame: 0, rotations: [[0, 0, 0]], morphs: {} },
    ]);
    expect(anim.asPose(0).bones).toEqual({});
  });

  it("apply() delegates to asPose(frameIndex).apply(skeleton)", async () => {
    const fetchMock = stub(true);
    const anim = new DazAnimation("Genesis9", { start: 0, end: 0 }, ["hip"], [
      { frame: 0, rotations: [[5, 0, 0]], morphs: {} },
    ]);
    await anim.apply(skel(), 0);
    expect(scriptOf(fetchMock)).toContain('"hip":[5,0,0]');
  });
});

describe("DazAnimation.append", () => {
  it("shifts the appended clip's frame numbers to follow this animation's last frame", () => {
    const a = new DazAnimation("G", { start: 0, end: 1 }, ["hip"], [
      { frame: 0, rotations: [[0, 0, 0]], morphs: {} },
      { frame: 1, rotations: [[1, 0, 0]], morphs: {} },
    ]);
    const b = new DazAnimation("G", { start: 0, end: 1 }, ["hip"], [
      { frame: 0, rotations: [[2, 0, 0]], morphs: {} },
      { frame: 1, rotations: [[3, 0, 0]], morphs: {} },
    ]);
    const joined = a.append(b);
    expect(joined.frames.map((f) => f.frame)).toEqual([0, 1, 2, 3]);
    expect(joined.frameRange).toEqual({ start: 0, end: 3 });
  });

  it("returns other's frames unchanged when this animation is empty", () => {
    const a = new DazAnimation("G", { start: 0, end: 0 }, ["hip"], []);
    const b = new DazAnimation("G", { start: 5, end: 6 }, ["hip"], [{ frame: 5, rotations: [[0, 0, 0]], morphs: {} }]);
    const joined = a.append(b);
    expect(joined.frameRange).toEqual({ start: 5, end: 6 });
  });

  it("throws when bone lists differ", () => {
    const a = new DazAnimation("G", { start: 0, end: 0 }, ["hip"], []);
    const b = new DazAnimation("G", { start: 0, end: 0 }, ["chest"], []);
    expect(() => a.append(b)).toThrow("Cannot append animations with different bone lists (1 vs 1 bones)");
  });
});

describe("DazAnimation convenience", () => {
  it("frameCount and boneCount reflect the stored data", () => {
    const anim = new DazAnimation("G", { start: 0, end: 2 }, ["hip", "chest"], CAPTURE_RESULT.frames);
    expect(anim.frameCount).toBe(3);
    expect(anim.boneCount).toBe(2);
  });

  it("toString summarizes figure/frames/bones/range", () => {
    const anim = new DazAnimation("Genesis 9", { start: 0, end: 90 }, ["hip"], []);
    expect(anim.toString()).toBe('DazAnimation(figure="Genesis 9", frames=0, bones=1, range=0–90)');
  });
});
