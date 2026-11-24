/** Unit tests for shotLibrary.ts. Mirrors dazpy tests/test_shot_library.py. No Studio. */

import { describe, expect, it } from "vitest";
import { Quat, Vec3 } from "../../src/math3.js";
import { lookAtEuler } from "../../src/shotGeometry.js";
import { CoveragePlan, Framing, Keyframed, Orbit, Placement, SHOT_SIZES, Shot, framingTransform, type ShotSize } from "../../src/shots.js";
import * as sl from "../../src/shotLibrary.js";
import { DialogueBeat, LineOfAction } from "../../src/shotLibrary.js";
import { FakeCamera, FakeScene, asCamera, asScene } from "../shotFakes.js";

// Alice faces Bob along -Z; cameras on side +1 stand on +X.
const POS = { alice: new Vec3(0, 0, 0), bob: new Vec3(0, 0, -120) };
const KEY_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;

const line = (side = 1) => LineOfAction.between(POS, "alice", "bob", side);

/** [camera position, aim point] of a static shot. */
function pose(shot: Shot): [Vec3, Vec3] {
  const c = shot.camera;
  if (c instanceof Framing) {
    const pts = c.subjects.map((s) => (typeof s === "string" ? ([POS[s as keyof typeof POS], true] as const) : ([s as Vec3, false] as const)));
    return framingTransform(pts, c, shot.lens.focalLength);
  }
  return [c.position, c.lookAt as Vec3];
}

/** Normalised horizontal screen coordinate of `point` (tan of the angle off-axis). */
function screenX(cam: Vec3, aim: Vec3, point: Vec3): number {
  const fwd = aim.sub(cam).normalize();
  const right = fwd.cross(new Vec3(0, 1, 0)).normalize();
  const rel = point.sub(cam);
  return rel.dot(right) / rel.dot(fwd);
}

function gazeScreenDir(cam: Vec3, aim: Vec3, from: Vec3, to: Vec3): number {
  const right = aim.sub(cam).cross(new Vec3(0, 1, 0)).normalize();
  return Math.sign(to.sub(from).dot(right));
}

const eye = (key: keyof typeof POS) => new Vec3(POS[key].x, POS[key].y + sl.EYE_HEIGHT_CM, POS[key].z);
const vecClose = (a: Vec3, b: Vec3 | number[], digits = 6) => {
  const bl = Array.isArray(b) ? b : b.toList();
  a.toList().forEach((v, i) => expect(v).toBeCloseTo(bl[i], digits));
};

describe("naming", () => {
  it("formats", () => {
    expect(sl.shotName("ots", "bob", "alice")).toBe("OTS_bob_over_alice");
    expect(sl.shotName("close_up", "anna", null, { scene: 3, index: 12 })).toBe("SC3_012_CU_anna");
    expect(sl.shotName("medium", "Genesis 9", null, { tag: "low" })).toBe("MS_low_Genesis-9");
    expect(sl.shotName("whip")).toBe("WHIP");
  });

  it("produces recipe keys", () => {
    for (const name of [sl.shotName("ots", "Bob Smith!", "Alice.G9"), sl.shotName("pov", "x".repeat(80))]) expect(name).toMatch(KEY_RE);
  });
});

describe("LineOfAction", () => {
  it("knows its sides", () => {
    const ln = line();
    expect(ln.sideOf(new Vec3(100, 0, -60))).toBe(1);
    expect(ln.sideOf(new Vec3(-100, 0, -60))).toBe(-1);
    expect(ln.sideOf(new Vec3(0.5, 0, 300))).toBe(0);
    expect(ln.sideOf(ln.midpoint.add(ln.normal.mul(50)))).toBe(1);
    expect(line(-1).sideOf(line(-1).midpoint.add(line(-1).normal.mul(50)))).toBe(-1);
    expect(ln.flipped().side).toBe(-1);
    expect(ln.other("alice")).toBe("bob");
  });

  it("rejects invalid lines", () => {
    expect(() => new LineOfAction("a", "b", new Vec3(0, 0, 0), new Vec3(0, 50, 0))).toThrow();
    expect(() => new LineOfAction("a", "a", new Vec3(0, 0, 0), new Vec3(1, 0, 0))).toThrow();
    expect(() => line().other("carol")).toThrow();
    expect(() => line(0)).toThrow();
  });
});

describe("composition", () => {
  it("puts eyes on the upper third", () => {
    expect(sl.headroomAnchor("close_up")).toBeCloseTo(160 - 40 / 6, 9);
    expect(sl.headroomAnchor("extreme_wide", 50)).toBe(0);
  });

  it("leaves lead room", () => {
    const cam = new Vec3(0, 0, 300);
    const aim = new Vec3(0, 0, 0); // looking -Z; screen-right is +X
    expect(sl.leadRoom(cam, aim, new Vec3(1, 0, 0))).toBe("left_third");
    expect(sl.leadRoom(cam, aim, new Vec3(-1, 0, 0))).toBe("right_third");
    expect(sl.leadRoom(cam, aim, new Vec3(0, 0, 1))).toBe("center");
  });
});

describe("shot types", () => {
  it("keeps every coverage camera on the line side", () => {
    for (const side of [1, -1]) {
      const plan = sl.dialogueCoverage(line(side));
      for (const shot of plan.allShots()) expect(line(side).sideOf(sl.cameraPosition(shot, POS)), shot.id).toBe(side);
      expect(sl.checkAxis(plan.allShots(), line(side), POS)).toEqual([]);
      expect(sl.checkAxis(plan.allShots(), line(-side), POS).length).toBe(6);
    }
  });

  it("builds OTS geometry on the thirds", () => {
    const shot = sl.overTheShoulder(line(), "alice", "bob");
    expect(shot.id).toBe("OTS_bob_over_alice");
    const [cam, aim] = pose(shot);
    expect(cam.distance(POS.bob)).toBeGreaterThan(POS.alice.distance(POS.bob));
    expect(cam.y).toBeCloseTo(sl.EYE_HEIGHT_CM - sl.OTS_DROP_CM, 9);
    const half = 36.0 / 50.0 / 2;
    const bx = screenX(cam, aim, eye("bob")) / half;
    const ax = screenX(cam, aim, eye("alice")) / half;
    expect(Math.abs(bx)).toBeCloseTo(1 / 3, 2);
    expect(bx * ax).toBeLessThan(0);
  });

  it("matches eyelines in a shot/reverse pair", () => {
    const [s1, s2] = sl.shotReverseShot(line());
    const [c1, a1] = pose(s1);
    const [c2, a2] = pose(s2);
    expect(gazeScreenDir(c1, a1, eye("bob"), eye("alice"))).toBe(-gazeScreenDir(c2, a2, eye("alice"), eye("bob")));
  });

  it("breaks eyelines when the line is crossed", () => {
    const [s1] = sl.shotReverseShot(line());
    const [, s2] = sl.shotReverseShot(line(-1));
    const [c1, a1] = pose(s1);
    const [c2, a2] = pose(s2);
    expect(gazeScreenDir(c1, a1, eye("bob"), eye("alice"))).toBe(gazeScreenDir(c2, a2, eye("alice"), eye("bob")));
  });

  it("gives a single lead room toward the partner", () => {
    const shot = sl.single(line(), "alice", { size: "close_up" });
    expect(shot.id).toBe("CU_alice");
    const [cam, aim] = pose(shot);
    const looks = gazeScreenDir(cam, aim, eye("alice"), eye("bob"));
    const sx = screenX(cam, aim, new Vec3(0, SHOT_SIZES[(shot.camera as Framing).size][1], 0));
    expect(sx * looks).toBeLessThan(0);
    expect(shot.lens.focalLength).toBe(85);
  });

  it("applies headroom to a single", () => {
    const shot = sl.single(line(), "bob", { size: "medium", headroom: true, lead: false });
    expect((shot.camera as Framing).anchorCm).toBe(sl.headroomAnchor("medium"));
    expect((shot.camera as Framing).composition).toBe("center");
  });

  it("widens a two-shot for far-apart actors", () => {
    expect((sl.twoShot(line()).camera as Framing).distanceCm).toBeNull();
    const far = sl.twoShot(LineOfAction.between({ a: new Vec3(0, 0, 0), b: new Vec3(600, 0, 0) }, "a", "b"));
    expect((far.camera as Framing).distanceCm).toBeGreaterThan(600);
  });

  it("builds establishing and master shots", () => {
    const est = sl.establishing(line());
    const f = est.camera as Framing;
    expect([f.size, f.elevationDeg, est.lens.focalLength]).toEqual(["extreme_wide", 10, 24]);
    expect(f.azimuthDeg).toBeCloseTo(90, 9);
    expect(sl.master(line()).id).toBe("MST_alice-bob");
  });

  it("builds a POV", () => {
    const shot = sl.pov(POS, "alice", "bob");
    expect(shot.id).toBe("POV_at-bob_alice");
    const c = shot.camera as Placement;
    expect((c.lookAt as Vec3).toList()).toEqual(eye("bob").toList());
    expect(c.position.z).toBeCloseTo(-10, 9);
    expect(sl.pov(POS, "alice", new Vec3(0, 90, -50)).id).toBe("POV_alice");
  });

  it("builds an insert", () => {
    const shot = sl.insert(new Vec3(10, 95, -60), { name: "cup", line: line() });
    const f = shot.camera as Framing;
    expect([shot.id, f.size]).toEqual(["INS_cup", "extreme_close_up"]);
    expect(f.azimuthDeg).toBeCloseTo(90, 9);
    expect(pose(shot)[0].y).toBeGreaterThan(95);
  });

  it("requires the line's actors for OTS", () => {
    expect(() => sl.overTheShoulder(line(), "alice", "alice")).toThrow();
  });
});

describe("camera moves", () => {
  it("inverts lookAtEuler with forwardFromRotation", () => {
    for (const target of [new Vec3(100, 50, -30), new Vec3(-40, -20, 80), new Vec3(0, 0, -1)]) {
      vecClose(sl.forwardFromRotation(lookAtEuler(new Vec3(0, 0, 0), target)), target.normalize());
    }
  });

  it("matches Studio camera readbacks", () => {
    const cases: Array<[[number, number, number], number[]]> = [
      [[0, 33.69, 0], [-0.555, 0.0, -0.832]],
      [[2.74, -39.73, 0], [0.638, 0.048, -0.768]],
      [[-177.26, 72.89, 180], [-0.955, 0.048, 0.294]],
      [[-180, 85.35, -180], [-0.997, 0.0, 0.081]],
    ];
    for (const [rot, fwd] of cases) {
      const f = sl.forwardFromRotation(rot);
      vecClose(f, fwd, 2);
      expect(f.dot(sl.forwardFromRotation(sl.canonicalRotation(rot)))).toBeCloseTo(1, 9);
    }
  });

  it("canonicalises rotations", () => {
    const [x, y, z] = sl.canonicalRotation([-177.26, 72.89, 180]);
    expect(x).toBeCloseTo(2.74, 6);
    expect(y).toBeCloseTo(107.11, 6);
    expect(z).toBeCloseTo(0, 6);
    expect(sl.canonicalRotation([10, 370, -5])).toEqual([10, 10, -5]);
  });

  it("reads Studio quaternions", () => {
    const cases: Array<[number[], number[]]> = [
      [[10, 30, 0], [-0.0842, -0.2578, 0.0226, 0.9623]],
      [[-20, 120, 15], [0.1974, -0.8342, -0.2134, 0.4686]],
      [[5, -100, 0], [-0.028, 0.7653, -0.0334, 0.6422]],
    ];
    for (const [euler, [qx, qy, qz, qw]] of cases) {
      const got = sl.eulerFromQuaternion({ x: qx, y: qy, z: qz, w: qw });
      got.forEach((v, i) => expect(Math.abs(v - euler[i])).toBeLessThan(0.05));
    }
  });

  it("starts a move from a quaternion pose", () => {
    const q = Quat.fromEuler(-177.26, 72.89, 180, "ZYX").conjugate(); // as Studio reports it
    const e = sl.eulerFromQuaternion({ x: q.x, y: q.y, z: q.z, w: q.w });
    expect(e[0]).toBeCloseTo(2.74, 6);
    expect(sl.forwardFromRotation(e).dot(sl.forwardFromRotation([-177.26, 72.89, 180]))).toBeCloseTo(1, 9);
    const a = (sl.cameraMove("tilt_up", new Vec3(0, 0, 0), q, { start: 0, end: 5 }).movement as Keyframed).keyframes[0].rotation!;
    a.forEach((v, i) => expect(v).toBeCloseTo(e[i], 9));
  });

  it("pans right from a flipped Euler", () => {
    const shot = sl.cameraMove("pan_right", new Vec3(0, 0, 0), [-177.26, 72.89, 180], { start: 0, end: 10, amount: 10 });
    const [k0, k1] = (shot.movement as Keyframed).keyframes;
    const f0 = sl.forwardFromRotation(k0.rotation!);
    const f1 = sl.forwardFromRotation(k1.rotation!);
    expect(f1.sub(f0).dot(f0.cross(new Vec3(0, 1, 0)).normalize())).toBeGreaterThan(0);
  });

  const keys = (kind: sl.CameraMoveKind, extra: Partial<sl.CameraMoveOptions> = {}) => {
    const shot = sl.cameraMove(kind, new Vec3(0, 150, 300), [0, 0, 0], { start: 0, end: 60, ...extra });
    expect(shot.movement).toBeInstanceOf(Keyframed);
    expect(shot.frameRange).toEqual([0, 60]);
    return (shot.movement as Keyframed).keyframes;
  };

  it("translates", () => {
    vecClose(keys("dolly_in").at(-1)!.position, [0, 150, 100]);
    vecClose(keys("dolly_out", { amount: 50 }).at(-1)!.position, [0, 150, 350]);
    vecClose(keys("truck_right").at(-1)!.position, [100, 150, 300]);
    vecClose(keys("crane_up").at(-1)!.position, [0, 250, 300]);
    vecClose(keys("pedestal_down").at(-1)!.position, [0, 100, 300]);
  });

  it("rotates", () => {
    expect(sl.forwardFromRotation(keys("pan_right").at(-1)!.rotation!).x).toBeGreaterThan(0.5);
    expect(sl.forwardFromRotation(keys("tilt_up").at(-1)!.rotation!).y).toBeGreaterThan(0.3);
  });

  it("makes a repeatable handheld that returns home", () => {
    const dump = (ks: readonly { toDict(): unknown }[]) => ks.map((k) => k.toDict());
    const a = keys("handheld", { seed: 7 });
    expect(dump(a)).toEqual(dump(keys("handheld", { seed: 7 })));
    expect(dump(a)).not.toEqual(dump(keys("handheld", { seed: 8 })));
    expect(a[0].position.toList()).toEqual([0, 150, 300]);
    expect(a.at(-1)!.position.toList()).toEqual([0, 150, 300]);
    expect(a.every((k) => Math.abs(k.position.x) <= 2.0)).toBe(true);
    expect(a.map((k) => k.frame)).toEqual([0, 3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36, 39, 42, 45, 48, 51, 54, 57, 60]);
  });

  it("rejects bad moves", () => {
    expect(() => sl.cameraMove("zoom" as sl.CameraMoveKind, new Vec3(0, 0, 0), [0, 0, 0], { start: 0, end: 10 })).toThrow();
    expect(() => sl.cameraMove("dolly_in", new Vec3(0, 0, 0), [0, 0, 0], { start: 10, end: 10 })).toThrow();
  });

  it("pushes in and pulls out", () => {
    const push = sl.pushIn(POS, "bob", { start: 0, end: 48, azimuthDeg: 90 });
    const [k0, k1] = (push.movement as Keyframed).keyframes;
    expect(k0.position.distance(POS.bob)).toBeGreaterThan(k1.position.distance(POS.bob));
    expect((k1.lookAt as Vec3).y).toBeGreaterThan((k0.lookAt as Vec3).y);
    expect(push.id).toBe("PUSH_bob");
    const pull = sl.pullOut(POS, "bob", { start: 0, end: 48, line: line() });
    expect(pull.id).toBe("PULL_bob");
    expect(sl.checkAxis([pull], line(), POS)).toEqual([]);
  });

  it("reports an arc that crosses the line", () => {
    const full = sl.arc("alice", { start: 0, end: 90 });
    expect(full.movement).toBeInstanceOf(Orbit);
    const issues = sl.checkAxis([full], line(), POS);
    expect(issues.map((i) => i.kind)).toEqual(["axis"]);
    expect(issues[0].message).toContain("moves across");
    expect(sl.checkAxis([sl.arc("alice", { start: 0, end: 90, startAzimuthDeg: 20, endAzimuthDeg: 160 })], line(), POS)).toEqual([]);
  });
});

describe("primitives", () => {
  it("composes the aim", () => {
    const cam = new Vec3(0, 160, 300);
    const target = new Vec3(0, 160, 0);
    for (const x of [sl.THIRD_X, -sl.THIRD_X, sl.GOLDEN_X, 0]) {
      expect(screenX(cam, sl.composeAim(cam, target, x, 50), target) / (36 / 50 / 2)).toBeCloseTo(x, 6);
    }
    expect(sl.GOLDEN_X).toBeCloseTo(0.2361, 4);
  });

  it("rolls with lookRotation", () => {
    const cam = new Vec3(100, 150, 200);
    const aim = new Vec3(-20, 140, -50);
    const flat = sl.lookRotation(cam, aim);
    const dutch = sl.lookRotation(cam, aim, 15);
    const f0 = sl.forwardFromRotation(flat);
    const f1 = sl.forwardFromRotation(dutch);
    expect(f0.dot(f1)).toBeCloseTo(1, 9);
    expect(f1.dot(aim.sub(cam).normalize())).toBeCloseTo(1, 9);
    const u0 = sl.cameraUp(flat);
    const u1 = sl.cameraUp(dutch);
    expect((Math.acos(u0.dot(u1)) * 180) / Math.PI).toBeCloseTo(15, 6);
    expect(u1.dot(f0.cross(new Vec3(0, 1, 0)).normalize().neg())).toBeGreaterThan(0); // top tips screen-left
  });

  it("keyframes an arc", () => {
    const shot = sl.arc("alice", { start: 0, end: 120, stepDeg: 90, positions: POS, radius: 200 });
    const ks = (shot.movement as Keyframed).keyframes;
    expect(ks.map((k) => k.frame)).toEqual([0, 30, 60, 90, 120]);
    const target = new Vec3(0, SHOT_SIZES.medium[1], 0);
    for (const k of ks) {
      expect(k.position.distance(target)).toBeCloseTo(200, 6);
      expect((k.lookAt as Vec3).toList()).toEqual(target.toList());
    }
    expect(() => sl.arc("alice", { start: 0, end: 10, stepDeg: 0, positions: POS })).toThrow();
  });

  it("rounds keyframed arc frames half-to-even like dazpy", () => {
    // 5 frames over 2 steps: 2.5 -> 2 (Python round), not 3.
    const ks = (sl.arc("alice", { start: 0, end: 5, stepDeg: 180, positions: POS }).movement as Keyframed).keyframes;
    expect(ks.map((k) => k.frame)).toEqual([0, 2, 5]);
  });
});

describe("focus", () => {
  it("racks focus with holds", () => {
    const pull = sl.rackFocus(new Vec3(0, 160, 300), "alice", "bob", { start: 0, end: 60, positions: POS, holdFrom: 10, holdTo: 10 });
    expect(pull.keys.map((k) => [k.frame, Math.round(k.focalDistance)])).toEqual([[0, 300], [10, 300], [50, 420], [60, 420]]);
  });

  it("takes distances and collapses impossible holds", () => {
    const pull = sl.rackFocus(new Vec3(0, 0, 0), 100, 250, { start: 0, end: 10, holdFrom: 8, holdTo: 8 });
    expect(pull.keys.map((k) => [k.frame, k.focalDistance])).toEqual([[0, 100], [10, 250]]);
    expect(() => sl.rackFocus(new Vec3(0, 0, 0), "alice", 100, { start: 0, end: 10 })).toThrow();
  });

  it("computes depth-of-field limits", () => {
    const [near, far] = sl.depthOfFieldLimits(50, 2.8, 300);
    expect(Math.abs(near - 273.0)).toBeLessThan(0.5);
    expect(Math.abs(far! - 332.9)).toBeLessThan(0.5);
    expect(sl.depthOfFieldLimits(24, 11, 1000)[1]).toBeNull();
    expect(() => sl.depthOfFieldLimits(50, 0, 100)).toThrow();
  });

  it("adds a rack focus to a shot", () => {
    const shot = sl.withRackFocus(sl.overTheShoulder(line(), "alice", "bob"), "alice", "bob", { start: 0, end: 24, positions: POS, fStop: 2.0 });
    expect(shot.lens.depthOfField).toBe(true);
    expect(shot.lens.fStop).toBe(2.0);
    expect(shot.focus!.keys[0].focalDistance).toBeLessThan(shot.focus!.keys.at(-1)!.focalDistance);
  });
});

describe("continuity", () => {
  const ms = (az: number, size: ShotSize = "medium") => new Shot({ id: `s${az}${size}`, camera: new Framing({ subjects: ["bob"], size, azimuthDeg: az }) });

  it("enforces the thirty-degree rule", () => {
    const issues = sl.checkThirtyDegree([ms(0), ms(10)], POS);
    expect(issues.map((i) => [i.kind, i.shotId, i.otherShotId])).toEqual([["thirty_degree", "s10medium", "s0medium"]]);
    expect(sl.checkThirtyDegree([ms(0), ms(45)], POS)).toEqual([]);
    expect(sl.checkThirtyDegree([ms(0), ms(10, "close_up")], POS)).toEqual([]);
    expect(sl.checkThirtyDegree([ms(0), sl.single(line(), "alice")], POS)).toEqual([]);
  });

  it("combines axis and thirty-degree checks", () => {
    const kinds = sl.checkContinuity([ms(90), ms(95), ms(-90, "close_up")], POS, { line: line() }).map((i) => i.kind).sort();
    expect(kinds).toEqual(["axis", "thirty_degree"]);
  });

  it("infers the plan's side", () => {
    const plan = sl.dialogueCoverage(line(-1));
    expect(sl.planLine(plan, POS)!.side).toBe(-1);
    expect(sl.checkPlan(plan, POS)).toEqual([]);
    expect(sl.planLine(sl.subjectCoverage("bob"), POS)).toBeNull();
  });

  it("refuses live node targets in pure checks", () => {
    const node = { position: async () => ({ x: 0, y: 0, z: 0 }) } as never;
    const shot = new Shot({ id: "n", camera: new Framing({ subjects: [node] }) });
    expect(() => sl.cameraPositions(shot, POS)).toThrow(/positions mapping/);
  });
});

describe("coverage", () => {
  it("builds subject presets that round-trip", () => {
    for (const [preset, n] of [["standard", 3], ["interview", 3], ["dramatic", 4], ["action", 4]] as const) {
      const plan = sl.subjectCoverage("bob", { preset, azimuthDeg: 30 });
      expect(plan.allShots().length).toBe(n);
      expect(CoveragePlan.fromDict(JSON.parse(JSON.stringify(plan.toDict()))).toDict()).toEqual(plan.toDict());
    }
    expect(sl.subjectCoverage("bob", { preset: "dramatic" }).allShots().map((s) => s.id)).toEqual(["WS_bob", "MS_low_bob", "MS_high_bob", "MCU_profile_bob"]);
    expect(() => sl.subjectCoverage("bob", { preset: "nope" })).toThrow();
  });

  it("builds dialogue coverage that converts to a recipe", () => {
    const plan = sl.dialogueCoverage(line());
    expect(plan.allShots().map((s) => s.id)).toEqual(["MST_alice-bob", "2S_alice-bob", "OTS_bob_over_alice", "OTS_alice_over_bob", "CU_alice", "CU_bob"]);
    expect(Object.keys(plan.toRecipeSections().cameras).length).toBe(6);
    expect(sl.dialogueCoverage(line(), { include: ["ots"] }).allShots()[0].id).toBe("OTS_bob_over_alice");
    expect(() => sl.dialogueCoverage(line(), { include: ["drone" as sl.DialoguePart] })).toThrow();
  });

  it("cuts a conversation", () => {
    const beats = [new DialogueBeat("alice", 0, 47, "Where were you?"), new DialogueBeat("bob", 48, 95, "Out."), new DialogueBeat("alice", 96, 120)];
    const plan = sl.conversation(line(), beats, { establishFrames: 24 });
    const shots = plan.allShots();
    expect(shots.map((s) => [s.id, s.frameRange])).toEqual([
      ["000_MST_alice-bob", [0, 23]],
      ["001_OTS_alice_over_bob", [24, 47]],
      ["002_OTS_bob_over_alice", [48, 95]],
      ["003_OTS_alice_over_bob", [96, 120]],
    ]);
    expect(plan.axis).toEqual(["alice", "bob"]);
    expect(shots[1].storyboard!.dialogue).toBe("Where were you?");
    expect(shots[2].gaze.map((g) => [g.actor, g.lookAt])).toEqual([["bob", "alice"], ["alice", "bob"]]);
    expect(sl.checkPlan(plan, POS)).toEqual([]);
    expect(CoveragePlan.fromDict(JSON.parse(JSON.stringify(plan.toDict()))).toDict()).toEqual(plan.toDict());

    const singles = sl.conversation(line(-1), beats, { style: "singles" });
    expect(singles.allShots().map((s) => s.id)).toEqual(["001_MCU_alice", "002_MCU_bob", "003_MCU_alice"]);
    expect(sl.checkPlan(singles, POS)).toEqual([]);
  });

  it("lets the establishing shot swallow the first beat", () => {
    const plan = sl.conversation(line(), [new DialogueBeat("alice", 0, 10), new DialogueBeat("bob", 11, 20)], { establishFrames: 30 });
    expect(plan.allShots().map((s) => s.frameRange)).toEqual([[0, 10], [11, 20]]);
  });

  it("validates conversations", () => {
    expect(() => sl.conversation(line(), [])).toThrow();
    expect(() => sl.conversation(line(), [new DialogueBeat("carol", 0, 10)])).toThrow();
    expect(() => sl.conversation(line(), [new DialogueBeat("alice", 0, 10), new DialogueBeat("bob", 10, 20)])).toThrow();
    expect(() => sl.conversation(line(), [new DialogueBeat("alice", 0, 10)], { style: "wides" as "ots" })).toThrow();
    expect(() => new DialogueBeat("alice", 10, 0)).toThrow();
  });
});

describe("applyCoverage", () => {
  it("names and labels cameras after shots", async () => {
    const scene = new FakeScene();
    const cams = await sl.applyCoverage(asScene(scene), sl.dialogueCoverage(line(), { include: ["master", "ots"] }), { subjects: POS });
    expect([...cams.keys()]).toEqual(["MST_alice-bob", "OTS_bob_over_alice", "OTS_alice_over_bob"]);
    expect(scene.created.map(([n]) => n)).toEqual([...cams.keys()]);
    expect(scene.created[0][1].calls).toContainEqual(["setLabel", "MST_alice-bob"]);
  });

  it("reuses given cameras", async () => {
    const scene = new FakeScene();
    const existing = new FakeCamera();
    const cams = await sl.applyCoverage(asScene(scene), [sl.single(line(), "bob")], { subjects: POS, cameras: { MCU_bob: asCamera(existing) } });
    expect(cams.get("MCU_bob")).toBe(existing);
    expect(scene.created).toEqual([]);
  });
});
