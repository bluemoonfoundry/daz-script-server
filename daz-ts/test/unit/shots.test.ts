/** Unit tests for shots.ts (typed Shot / Sequence / CoveragePlan models). Mirrors dazpy tests/test_shots.py. */

import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazCamera } from "../../src/camera.js";
import { Vec3 } from "../../src/math3.js";
import type { DazNode } from "../../src/node.js";
import {
  AspectSettings,
  BlockingBeat,
  CAMERA_ANGLES,
  CameraKeyframe,
  CoveragePlan,
  FocusKey,
  FocusPull,
  Framing,
  GazeBeat,
  Keyframed,
  Lens,
  Orbit,
  Placement,
  RenderOutput,
  SHOT_SIZES,
  Sequence,
  Shot,
  Storyboard,
  applyShot,
  framingDistance,
  framingTransform,
  shotFromRecipeCamera,
} from "../../src/shots.js";
import { jsonResponse } from "../helpers.js";
import { FakeCamera, FakeScene, asCamera, asScene } from "../shotFakes.js";

/** A node-like target: anything with a `position()` method. */
function fakeNode(position = { x: 10, y: 0, z: 0 }): DazNode {
  return { position: vi.fn(async () => position) } as unknown as DazNode;
}

const roundTrip = <T extends { toDict(): unknown }>(cls: { fromDict(d: unknown): T }, v: T) =>
  cls.fromDict(JSON.parse(JSON.stringify(v.toDict())));

function fullShot(): Shot {
  return new Shot({
    id: "anna_mcu",
    camera: new Framing({ subjects: ["anna"], size: "medium_close_up", angle: "low", azimuthDeg: 30, composition: "left_third" }),
    lens: new Lens({ focalLength: 85, depthOfField: true, focalDistance: 120, fStop: 2.8 }),
    focus: new FocusPull({ keys: [new FocusKey(0, 120.0), new FocusKey(24, 300.0)] }),
    frameRange: [0, 48],
    aspect: new AspectSettings({ pixelsWidth: 1920, pixelsHeight: 1080 }),
    blocking: [new BlockingBeat({ frame: 0, actor: "anna", position: new Vec3(0, 0, 0), facing: "ben", note: "enters" })],
    gaze: [new GazeBeat(12, "anna", "ben"), new GazeBeat(30, "anna", new Vec3(0, 160, 300))],
    lighting: "day_key",
    storyboard: new Storyboard({ description: "Anna reacts", dialogue: "No.", beat: "turn" }),
    output: new RenderOutput({ path: "C:/r/anna.png", engine: "iray", resolution: [1080, 1350], iraySamples: 100 }),
  });
}

describe("serialisation", () => {
  it("round-trips a full shot through JSON", () => {
    const shot = fullShot();
    const d = shot.toDict() as Record<string, any>;
    expect(roundTrip(Shot, shot).toDict()).toEqual(d);
    expect(d.camera.kind).toBe("framing");
    // dazpy's wire format: snake_case keys, [x, y, z] vectors.
    expect(d.lens).toEqual({ focal_length: 85, depth_of_field: true, focal_distance: 120, f_stop: 2.8 });
    expect(d.gaze[1].look_at).toEqual([0, 160, 300]);
    expect(d.frame_range).toEqual([0, 48]);
  });

  it("round-trips moving shots", () => {
    const orbit = new Shot({ id: "o", camera: new Placement({ position: new Vec3(0, 0, 0), lookAt: "anna" }), movement: new Orbit({ radius: 200, frameEnd: 10 }) });
    const keyed = new Shot({
      id: "k",
      camera: new Placement({ position: new Vec3(0, 100, 300) }),
      movement: new Keyframed({
        keyframes: [
          new CameraKeyframe({ frame: 0, position: new Vec3(0, 100, 300), lookAt: "anna" }),
          new CameraKeyframe({ frame: 24, position: new Vec3(0, 150, 200), lookAt: new Vec3(0, 140, 0), lookAtOffsetCm: 5 }),
        ],
      }),
    });
    for (const s of [orbit, keyed]) {
      const back = roundTrip(Shot, s);
      expect(back.toDict()).toEqual(s.toDict());
      expect(back.movement).toBeInstanceOf(s.movement!.constructor);
    }
  });

  it("omits defaults", () => {
    expect(new Shot({ id: "s", camera: new Framing({ subjects: ["a"] }) }).toDict()).toEqual({ id: "s", camera: { kind: "framing", subjects: ["a"] } });
  });

  it("loads a dazpy-written dict", () => {
    const shot = Shot.fromDict({
      id: "s",
      camera: { kind: "placement", position: [1, 2, 3], look_at: "anna", rotation: null },
      lens: { focal_length: 85 },
      movement: { kind: "orbit", radius: 100, frame_end: 10 },
    });
    expect((shot.camera as Placement).position.toList()).toEqual([1, 2, 3]);
    expect(shot.lens.focalLength).toBe(85);
    expect((shot.movement as Orbit).frameEnd).toBe(10);
  });

  it("round-trips a coverage plan", () => {
    const plan = new CoveragePlan({
      id: "cafe",
      subjects: ["anna", "ben"],
      axis: ["anna", "ben"],
      lighting: "day_key",
      sequences: [new Sequence({ id: "s1", shots: [fullShot()], lighting: "night" })],
      storyboard: new Storyboard({ notes: "keep left-to-right" }),
    });
    expect(roundTrip(CoveragePlan, plan).toDict()).toEqual(plan.toDict());
  });

  it("refuses to serialise a DazNode target, naming the path", () => {
    const shot = new Shot({ id: "s", camera: new Placement({ position: new Vec3(0, 0, 0), lookAt: fakeNode() }) });
    expect(() => shot.toDict()).toThrow(TypeError);
    expect(() => shot.toDict()).toThrow(/camera\.look_at/);
  });

  it("never reads a node target's position when building models", () => {
    const node = fakeNode();
    new Framing({ subjects: [node] });
    expect((node.position as unknown as ReturnType<typeof vi.fn>).mock.calls.length).toBe(0);
  });

  it.each([
    [{ id: "s", camera: { kind: "framing", subjects: ["a"], size: "huge" } }, /camera.*size/],
    [{ id: "s", camera: { kind: "framing", subjects: ["a"], zoom: 2 } }, /camera\.zoom: unknown/],
    [{ id: "s", camera: { subjects: ["a"] } }, /camera: needs 'kind'/],
    [{ id: "s", camera: { kind: "placement", position: [1, 2] } }, /camera\.position/],
    [
      { id: "s", camera: { kind: "framing", subjects: ["a"] }, focus: { keys: [{ frame: 5, focal_distance: 1 }, { frame: 2, focal_distance: 1 }] } },
      /focus.*ascending/,
    ],
  ])("fromDict errors name the path (%#)", (data, pattern) => {
    expect(() => Shot.fromDict(data)).toThrow(pattern);
  });

  it("enforces model invariants", () => {
    expect(() => new Framing({ subjects: [] })).toThrow();
    expect(() => new Lens({ focalLength: 0 })).toThrow();
    expect(
      () =>
        new Shot({
          id: "s",
          camera: new Framing({ subjects: ["a"] }),
          movement: new Keyframed({ keyframes: [new CameraKeyframe({ frame: 0, position: new Vec3(0, 0, 0) }), new CameraKeyframe({ frame: 1, position: new Vec3(1, 0, 0) })] }),
        }),
    ).toThrow();
    const a = new Shot({ id: "a", camera: new Framing({ subjects: ["x"] }) });
    expect(() => new Sequence({ id: "q", shots: [a, a] })).toThrow(/duplicate shot id/);
    expect(() => new CoveragePlan({ id: "p", subjects: ["anna"], axis: ["anna", "ben"] })).toThrow(/not in subjects/);
    expect(() => new CoveragePlan({ id: "p", sequences: [new Sequence({ id: "1", shots: [a] }), new Sequence({ id: "2", shots: [a] })] })).toThrow(
      /duplicate shot id/,
    );
  });

  it("falls back shot -> sequence -> plan for lighting continuity", () => {
    const own = new Shot({ id: "own", camera: new Framing({ subjects: ["x"] }), lighting: "a" });
    const seqLit = new Shot({ id: "seq", camera: new Framing({ subjects: ["x"] }) });
    const planLit = new Shot({ id: "plan", camera: new Framing({ subjects: ["x"] }) });
    const plan = new CoveragePlan({
      id: "p",
      lighting: "c",
      sequences: [new Sequence({ id: "1", shots: [own, seqLit], lighting: "b" }), new Sequence({ id: "2", shots: [planLit] })],
    });
    expect(plan.allShots().map((s) => plan.lightingFor(s))).toEqual(["a", "b", "c"]);
  });
});

describe("geometry", () => {
  it("keeps the recipe sizes", () => {
    expect(SHOT_SIZES.full_body).toEqual([210.0, 90.0]);
    expect(SHOT_SIZES.medium).toEqual([100.0, 130.0]);
    expect(SHOT_SIZES.close_up).toEqual([40.0, 160.0]);
  });

  it("fits the frame", () => {
    expect(framingDistance("close_up", 85)).toBeCloseTo((40 * 85) / 27, 9);
  });

  it("sets elevation from the angle unless overridden", () => {
    const f = new Framing({ subjects: ["a"], angle: "high" });
    expect(f.effectiveElevationDeg).toBe(CAMERA_ANGLES.high);
    expect(new Framing({ subjects: ["a"], angle: "high", elevationDeg: 5 }).effectiveElevationDeg).toBe(5);
    const [pos, aim] = framingTransform([[new Vec3(0, 0, 0), true]], f, 50);
    expect(pos.y).toBeGreaterThan(aim.y);
  });

  it("raises figure points but not Vec3 points", () => {
    const f = new Framing({ subjects: ["a", "b"], size: "medium" });
    const [, aim] = framingTransform([[new Vec3(0, 0, 0), true], [new Vec3(100, 0, 0), false]], f, 50);
    expect(aim.toList()).toEqual([50, 65, 0]);
  });

  it("turns the camera, not moves it, for a third composition", () => {
    const pt = [[new Vec3(0, 0, 0), true]] as const;
    const [pos, aim] = framingTransform(pt, new Framing({ subjects: ["a"], composition: "left_third" }), 50);
    const [cpos, caim] = framingTransform(pt, new Framing({ subjects: ["a"] }), 50);
    expect(pos.toList()).toEqual(cpos.toList());
    expect(aim.x - caim.x).toBeCloseTo((framingDistance("medium", 50) * 36) / 50 / 6, 9);
    const right = framingTransform(pt, new Framing({ subjects: ["a"], composition: "right_third" }), 50)[1];
    expect(right.x).toBeCloseTo(-aim.x, 9);
  });
});

describe("applyShot", () => {
  it("resolves framing keys through subjects", async () => {
    const scene = new FakeScene();
    const shot = new Shot({ id: "s", camera: new Framing({ subjects: ["anna"], size: "close_up" }), lens: new Lens({ focalLength: 85 }) });
    const cam = (await applyShot(asScene(scene), shot, { name: "CU", subjects: { anna: new Vec3(-60, 0, 0) } })) as unknown as FakeCamera;
    expect(scene.created[0][0]).toBe("CU");
    expect(cam.calls.find((c) => c[0] === "aimAt")).toEqual(["aimAt", -60, 160, 0]);
    expect(cam.calls).toContainEqual(["setFocalLength", 85]);
    expect(cam.calls.map((c) => c[0])).not.toContain("setDepthOfField");
  });

  it("raises a DazNode framing subject", async () => {
    const cam = (await applyShot(asScene(new FakeScene()), new Shot({ id: "s", camera: new Framing({ subjects: [fakeNode()], size: "medium" }) }))) as unknown as FakeCamera;
    expect(cam.calls.filter((c) => c[0] === "aimAt")).toEqual([["aimAt", 10, 130, 0]]);
  });

  it("rejects unresolved keys, and an Orbit without a target before creating a camera", async () => {
    await expect(applyShot(asScene(new FakeScene()), new Shot({ id: "s", camera: new Framing({ subjects: ["anna"] }) }))).rejects.toThrow(/anna/);
    const scene2 = new FakeScene();
    await expect(
      applyShot(asScene(scene2), new Shot({ id: "o", camera: new Placement({ position: new Vec3(0, 0, 0) }), movement: new Orbit({ radius: 1 }) })),
    ).rejects.toThrow(/Orbit needs a target/);
    expect(scene2.created).toEqual([]);
  });

  it("bakes an orbit per frame after widening the anim range", async () => {
    const scene = new FakeScene();
    const shot = new Shot({ id: "o", camera: new Framing({ subjects: ["anna"] }), movement: new Orbit({ radius: 100, frameStart: 2, frameEnd: 4 }) });
    const cam = (await applyShot(asScene(scene), shot, { subjects: { anna: new Vec3(0, 0, 0) } })) as unknown as FakeCamera;
    expect(scene.animRanges).toEqual([[2, 4]]);
    expect(scene.frames).toEqual([2, 3, 4]);
    expect(cam.calls.filter((c) => c[0] === "aimAt")).toEqual(Array(3).fill(["aimAt", 0, 25, 0]));
  });

  it("keys focal distance and enables DoF for a focus pull", async () => {
    const cam = new FakeCamera();
    await applyShot(asScene(new FakeScene()), fullShot(), { camera: asCamera(cam), subjects: { anna: new Vec3(0, 0, 0) } });
    expect(cam.calls.slice(-4)).toEqual([
      ["setDepthOfField", true],
      ["clearFocalDistanceKeys"],
      ["setFocalDistanceAtFrame", 0, 120],
      ["setFocalDistanceAtFrame", 24, 300],
    ]);
    expect(cam.calls).toContainEqual(["setFStop", 2.8]);
    expect(cam.calls).toContainEqual(["setPixelsWidth", 1920]);
  });

  it("keeps existing keys with clearKeys: false", async () => {
    const cam = new FakeCamera();
    const shot = new Shot({
      id: "k",
      camera: new Placement({ position: new Vec3(0, 0, 0) }),
      movement: new Keyframed({
        keyframes: [
          new CameraKeyframe({ frame: 0, position: new Vec3(0, 0, 0), rotation: [0, 0, 0] }),
          new CameraKeyframe({ frame: 9, position: new Vec3(1, 0, 0), rotation: [0, 5, 0] }),
        ],
      }),
      focus: new FocusPull({ keys: [new FocusKey(0, 100), new FocusKey(9, 200)] }),
    });
    await applyShot(asScene(new FakeScene()), shot, { camera: asCamera(cam), clearKeys: false });
    const names = cam.calls.map((c) => c[0]);
    for (const n of ["clearPositionKeys", "clearRotationKeys", "clearFocalDistanceKeys"]) expect(names).not.toContain(n);
    expect(names.filter((n) => n === "setPositionAtFrame").length).toBe(2);
    await applyShot(asScene(new FakeScene()), shot, { camera: asCamera(cam) });
    expect(cam.calls.map((c) => c[0])).toContain("clearPositionKeys");
  });

  it("resolves a keyframed lookAt key through subjects", async () => {
    const cam = new FakeCamera();
    const shot = new Shot({
      id: "k",
      camera: new Placement({ position: new Vec3(0, 100, 300) }),
      movement: new Keyframed({
        keyframes: [
          new CameraKeyframe({ frame: 0, position: new Vec3(0, 100, 300), lookAt: "anna", lookAtOffsetCm: 100 }),
          new CameraKeyframe({ frame: 10, position: new Vec3(0, 100, 200), lookAt: "anna", lookAtOffsetCm: 100 }),
        ],
      }),
    });
    await applyShot(asScene(new FakeScene()), shot, { camera: asCamera(cam), subjects: { anna: new Vec3(0, 0, 0) } });
    const rots = cam.calls.filter((c) => c[0] === "setRotationAtFrame");
    expect(rots.length).toBe(2);
    expect(rots[0][2]).toBeCloseTo(0, 9); // straight down -Z: no yaw
    expect(rots[0][1]).toBeCloseTo(0, 9); // level
  });
});

describe("DazCamera focal-distance keys", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("writes and clears focal-distance keys", async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(jsonResponse({ success: true, result: null, output: [], request_id: "r", duration_ms: 0 })),
    );
    vi.stubGlobal("fetch", fetchMock);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera 1", kind: "name" });
    await cam.setFocalDistanceAtFrame(12, 250);
    await cam.clearFocalDistanceKeys();
    const script = (i: number) => JSON.parse(fetchMock.mock.calls[i][1].body as string).script as string;
    expect(script(0)).toContain("12 * Scene.getTimeStep()");
    expect(script(0)).toContain("getFocalDistanceControl().setDoubleValue(_tm, 250)");
    expect(script(1)).toContain("getFocalDistanceControl().deleteAllKeys()");
  });
});

describe("recipe conversion", () => {
  const BASE = {
    recipe_version: 1,
    id: "cafe",
    assets: { g9: { path: "/People/G9.duf" } },
    actors: { anna: { asset: "g9", position: [-60, 0, 0] }, ben: { asset: "g9", position: [60, 0, 0] } },
  };

  function plan(): CoveragePlan {
    const two = new Shot({
      id: "two",
      camera: new Framing({ subjects: ["anna", "ben"], size: "wide", angle: "high" }),
      lens: new Lens({ focalLength: 35 }),
      output: new RenderOutput({ path: "C:/r/two.png" }),
    });
    const ots = new Shot({
      id: "ots",
      camera: new Placement({ position: new Vec3(80, 160, 80), lookAt: "anna" }),
      lens: new Lens({ focalLength: 50, depthOfField: true, focalDistance: 150 }),
      output: new RenderOutput({ path: "C:/r/ots.png", resolution: [1080, 1350] }),
    });
    const cu = new Shot({
      id: "cu",
      camera: new Framing({ subjects: ["anna"], size: "close_up", elevationDeg: 5, composition: "left_third" }),
      lens: new Lens({ focalLength: 85 }),
      storyboard: new Storyboard({ description: "dropped in conversion" }),
    });
    return new CoveragePlan({ id: "cafe", subjects: ["anna", "ben"], axis: ["anna", "ben"], sequences: [new Sequence({ id: "s", shots: [two, ots, cu] })] });
  }

  it("merges into a recipe without touching the input", () => {
    const recipe = plan().mergeIntoRecipe(BASE) as Record<string, any>;
    expect(recipe.shots.map((s: { id: string }) => s.id)).toEqual(["two", "ots"]);
    expect(recipe.cameras.two.angle).toBe("high");
    expect(recipe.cameras.ots).toEqual({ position: [80, 160, 80], look_at: "anna", focal_length: 50, depth_of_field: true, focal_distance: 150 });
    expect(recipe.shots[1].render).toEqual({ resolution: [1080, 1350] });
    expect("cameras" in BASE).toBe(false);
  });

  it("round-trips the camera through a recipe", () => {
    for (const shot of plan().allShots()) {
      const [cam, spec] = shot.toRecipe();
      const back = shotFromRecipeCamera(shot.id, cam, spec);
      expect(back.camera.toDict()).toEqual(shot.camera.toDict());
      expect(back.output?.toDict()).toEqual(shot.output?.toDict());
      expect(back.lens.focalLength).toBe(shot.lens.focalLength);
    }
  });

  it("refuses clashes", () => {
    expect(() => plan().mergeIntoRecipe({ ...BASE, cameras: { two: { frame: "anna" } } })).toThrow(/two/);
  });

  it("refuses shots recipes can't express", () => {
    const moving = new Shot({ id: "m", camera: new Placement({ position: new Vec3(0, 0, 0), lookAt: "anna" }), movement: new Orbit({ radius: 100 }) });
    const pulled = new Shot({ id: "f", camera: new Framing({ subjects: ["anna"] }), focus: new FocusPull({ keys: [new FocusKey(0, 1), new FocusKey(1, 2)] }) });
    const vecSubject = new Shot({ id: "v", camera: new Framing({ subjects: [new Vec3(0, 0, 0)] }) });
    const node = new Shot({ id: "n", camera: new Framing({ subjects: [fakeNode()] }) });
    for (const s of [moving, pulled, vecSubject]) expect(() => s.toRecipe()).toThrow(Error);
    expect(() => node.toRecipe()).toThrow(TypeError);
  });

  it("keeps the recipe's ten degree default for a camera without angle", () => {
    const shot = shotFromRecipeCamera("c", { frame: "anna" });
    expect((shot.camera as Framing).effectiveElevationDeg).toBe(10.0);
    expect(shot.toRecipe()[0]).toEqual({ frame: "anna", elevation_deg: 10.0, focal_length: 50.0 });
  });
});
