// daz-ts/test/integration/shots.integration.test.ts
//
// Live tests for shots.ts / shotLibrary.ts against DAZ Studio. Gated on
// DAZ_SERVER_URL:
//
//   DAZ_SERVER_URL=http://127.0.0.1:18811 npx vitest run test/integration/shots.integration.test.ts
//
// Each test applies a shot in Studio, reads the camera back with
// getWSPos(tm) / getWSRot(tm) / the focal-distance control at the keyed
// frames, and compares it with the library's pure prediction. The scene is
// not cleared: cameras are named ShotLive_* (coverage cameras after their
// shot ids) and deleted afterwards; the anim range and current frame are
// restored.
//
// The dazpy twin is tests/test_shots_live.py; keep the two scenario lists and
// tolerances in step.
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { DazClient } from "../../src/client.js";
import type { DazCamera } from "../../src/camera.js";
import { Quat, Vec3 } from "../../src/math3.js";
import { DazScene } from "../../src/scene.js";
import * as sl from "../../src/shotLibrary.js";
import { LineOfAction } from "../../src/shotLibrary.js";
import { Framing, Keyframed, Lens, Orbit, Placement, Shot, applyShot, framingTransform } from "../../src/shots.js";

const SERVER_URL = process.env.DAZ_SERVER_URL;
const PREFIX = "ShotLive_";
// Alice faces Bob along -Z, off the origin so nothing lines up by accident.
const POS = { alice: new Vec3(310, 0, -40), bob: new Vec3(330, 0, -160) };
const POS_TOL = 0.01; // cm
const DIR_TOL = 1e-4; // 1 - dot of unit directions (~0.8 degrees)

// One read-back script shared with the dazpy suite: world pose and focal
// distance of node NAME at each of FRAMES.
const READBACK = (name: string, frames: number[]) => `(function(){
  var n = Scene.findNode(${JSON.stringify(name)}); if (!n) return null;
  var step = Scene.getTimeStep(); var frames = ${JSON.stringify(frames)}; var out = [];
  for (var i = 0; i < frames.length; i++) {
    var tm = frames[i] * step; var p = n.getWSPos(tm, false); var q = n.getWSRot(tm, false);
    var fd = n.getFocalDistanceControl ? n.getFocalDistanceControl().getValue(tm) : null;
    out.push({frame: frames[i], pos: [p.x, p.y, p.z], rot: {x: q.x, y: q.y, z: q.z, w: q.w}, focal_distance: fd});
  }
  return out;
})()`;

const CLEANUP = (names: string[]) => `(function(){
  var gone = 0;
  for (var i = Scene.getNumNodes() - 1; i >= 0; i--) {
    var n = Scene.getNode(i); var name = n.getName();
    if (name.indexOf(${JSON.stringify(PREFIX)}) === 0 || ${JSON.stringify(names)}.indexOf(name) >= 0) { Scene.removeNode(n); gone++; }
  }
  return gone;
})()`;

type RawPose = { frame: number; pos: [number, number, number]; rot: { x: number; y: number; z: number; w: number }; focal_distance: number | null };
type Pose = { frame: number; pos: Vec3; forward: Vec3; up: Vec3; focalDistance: number | null };

const UP = new Vec3(0, 1, 0);

function expectVecClose(a: Vec3, b: Vec3, tol = POS_TOL): void {
  expect(a.distance(b), `${a.toList()} != ${b.toList()}`).toBeLessThan(tol);
}

function expectSameDirection(a: Vec3, b: Vec3): void {
  expect(1 - a.normalize().dot(b.normalize()), `${a.toList()} vs ${b.toList()}`).toBeLessThan(DIR_TOL);
}

describe.skipIf(!SERVER_URL)("daz-ts shots / shotLibrary against a live DAZ Studio server", () => {
  let client: DazClient;
  let scene: DazScene;
  let range0: { start: number; end: number };
  let frame0: number;
  let extraNames: string[] = [];

  const cleanup = (names: string[]) => client.execute(CLEANUP(names));
  const camera = (tag: string) => scene.createCamera(`${PREFIX}${tag}`);
  const line = (side = 1) => LineOfAction.between(POS, "alice", "bob", side);

  async function readback(cam: DazCamera, frames: number[]): Promise<Pose[]> {
    const data = (await client.execute(READBACK((await cam.name())!, frames))).value as RawPose[] | null;
    expect(data, "camera vanished").not.toBeNull();
    return data!.map((d) => {
      const q = Quat.fromDz(d.rot);
      return { frame: d.frame, pos: Vec3.fromList(d.pos), forward: q.rotate(new Vec3(0, 0, -1)).normalize(), up: q.rotate(UP).normalize(), focalDistance: d.focal_distance };
    });
  }

  beforeAll(async () => {
    const url = new URL(SERVER_URL!);
    client = new DazClient({ host: url.hostname, port: Number(url.port) || 18811 });
    scene = new DazScene(client);
    range0 = await scene.animRange();
    frame0 = await scene.frame();
    await cleanup([]);
  });

  afterEach(async () => {
    await cleanup(extraNames);
    extraNames = [];
  });

  afterAll(async () => {
    await scene.setAnimRange(range0.start, range0.end);
    await scene.setFrame(frame0);
  });

  // ---- static shots ------------------------------------------------------

  it("framing_single_close_up", async () => {
    const shot = sl.single(line(), "alice", { size: "close_up" });
    const cam = await applyShot(scene, shot, { camera: await camera("single"), subjects: POS });
    const [pos, aim] = framingTransform([[POS.alice, true]], shot.camera as Framing, shot.lens.focalLength);
    const [p] = await readback(cam, [0]);
    expectVecClose(p.pos, pos);
    expectSameDirection(p.forward, aim.sub(pos));
    expect(p.up.y).toBeGreaterThan(0.9); // aimAt leaves no roll
    expect(await cam.focalLength()).toBeCloseTo(85, 4);
  });

  it("framing_node_subject_is_raised", async () => {
    const target = await camera("target");
    await target.setPosition(250, 0, -90);
    const shot = new Shot({ id: "n", camera: new Framing({ subjects: [target], size: "medium", azimuthDeg: 40 }) });
    const cam = await applyShot(scene, shot, { camera: await camera("node") });
    const [pos, aim] = framingTransform([[new Vec3(250, 0, -90), true]], shot.camera as Framing, 50);
    const [p] = await readback(cam, [0]);
    expectVecClose(p.pos, pos);
    expectSameDirection(p.forward, aim.sub(pos));
  });

  it("over_the_shoulder_placement", async () => {
    const shot = sl.overTheShoulder(line(), "alice", "bob");
    const c = shot.camera as Placement;
    const cam = await applyShot(scene, shot, { camera: await camera("ots"), subjects: POS });
    const [p] = await readback(cam, [0]);
    expectVecClose(p.pos, c.position);
    expectSameDirection(p.forward, (c.lookAt as Vec3).sub(c.position));
    expect(line().sideOf(p.pos)).toBe(1);
  });

  it("dutch_rotation_rolls_toward_screen_left", async () => {
    const position = new Vec3(400, 150, 200);
    const aim = new Vec3(280, 140, -50);
    const rot = sl.lookRotation(position, aim, 15);
    const cam = await applyShot(scene, new Shot({ id: "d", camera: new Placement({ position, rotation: rot }) }), { camera: await camera("dutch") });
    const [p] = await readback(cam, [0]);
    expectSameDirection(p.forward, aim.sub(position));
    expectSameDirection(p.up, sl.cameraUp(rot));
    expect(p.up.dot(p.forward.cross(UP).normalize().neg())).toBeGreaterThan(0);
    const levelUp = sl.cameraUp(sl.lookRotation(position, aim));
    expect((Math.acos(Math.max(-1, Math.min(1, p.up.dot(levelUp)))) * 180) / Math.PI).toBeCloseTo(15, 1);
  });

  // ---- moves -------------------------------------------------------------

  it("camera_move_dolly_keys_both_ends", async () => {
    const shot = sl.cameraMove("dolly_in", new Vec3(320, 150, 200), [5, 20, 0], { start: 0, end: 24, amount: 120 });
    const cam = await applyShot(scene, shot, { camera: await camera("dolly") });
    const keys = (shot.movement as Keyframed).keyframes;
    (await readback(cam, [0, 24])).forEach((p, i) => {
      expectVecClose(p.pos, keys[i].position);
      expectSameDirection(p.forward, sl.forwardFromRotation(keys[i].rotation!));
    });
    const [mid] = await readback(cam, [12]);
    expect(mid.pos.distance(keys[0].position)).toBeLessThan(keys[0].position.distance(keys[1].position));
  });

  it("pan_from_studio_quaternion_turns_right", async () => {
    const cam = await camera("pan");
    await cam.setPosition(420, 150, 120);
    await cam.aimAt(300, 140, -100); // Studio may report this as a flipped (|x| > 90) Euler
    const [start] = await readback(cam, [0]);
    const shot = sl.cameraMove("pan_right", start.pos, (await cam.rotation())!, { start: 0, end: 20, amount: 20 });
    await applyShot(scene, shot, { camera: cam });
    const [p0, p1] = await readback(cam, [0, 20]);
    expectSameDirection(p0.forward, start.forward); // the quaternion read back as the same view
    expectSameDirection(p1.forward, sl.forwardFromRotation((shot.movement as Keyframed).keyframes.at(-1)!.rotation!));
    expect(p1.forward.sub(p0.forward).dot(p0.forward.cross(UP).normalize())).toBeGreaterThan(0);
  });

  it("push_in_reaims_at_each_key", async () => {
    const shot = sl.pushIn(POS, "bob", { start: 0, end: 30, line: line() });
    const cam = await applyShot(scene, shot, { camera: await camera("push"), subjects: POS });
    const keys = (shot.movement as Keyframed).keyframes;
    (await readback(cam, [0, 30])).forEach((p, i) => {
      expectVecClose(p.pos, keys[i].position);
      expectSameDirection(p.forward, (keys[i].lookAt as Vec3).sub(keys[i].position));
    });
    expect(sl.checkAxis([shot], line(), POS)).toEqual([]);
  });

  it("keyframed_arc_waypoints", async () => {
    const shot = sl.arc("alice", { start: 0, end: 24, stepDeg: 45, positions: POS, radius: 220, startAzimuthDeg: 30, endAzimuthDeg: 150 });
    const cam = await applyShot(scene, shot, { camera: await camera("arc"), subjects: POS });
    const keys = (shot.movement as Keyframed).keyframes;
    const target = keys[0].lookAt as Vec3;
    (await readback(cam, keys.map((k) => k.frame))).forEach((p, i) => {
      expectVecClose(p.pos, keys[i].position);
      expect(Math.abs(p.pos.distance(target) - 220)).toBeLessThan(POS_TOL);
      expectSameDirection(p.forward, target.sub(p.pos));
    });
  });

  it("orbit_bake_sets_range_and_parks_on_last_frame", async () => {
    const orbit = { radius: 200, frameStart: 0, frameEnd: 4 };
    const shot = new Shot({
      id: "o",
      camera: new Framing({ subjects: ["alice"] }),
      lens: new Lens({ focalLength: 35 }),
      movement: new Orbit({ ...orbit, startAzimuthDeg: 0, endAzimuthDeg: 80 }),
    });
    const cam = await applyShot(scene, shot, { camera: await camera("orbit"), subjects: POS });
    expect(await scene.animRange()).toEqual({ start: 0, end: 4 });
    expect(await scene.frame()).toBe(4);
    const [last] = sl.cameraPositions(new Shot({ id: "x", camera: shot.camera, movement: new Orbit({ ...orbit, startAzimuthDeg: 80, endAzimuthDeg: 80 }) }), POS);
    const [p] = await readback(cam, [4]);
    expectVecClose(p.pos, last);
    expect(await cam.focalLength()).toBeCloseTo(35, 4);
  });

  // ---- focus -------------------------------------------------------------

  it("rack_focus_keys_focal_distance", async () => {
    const shot = sl.withRackFocus(sl.overTheShoulder(line(), "alice", "bob"), "alice", "bob", {
      start: 0,
      end: 24,
      positions: POS,
      fStop: 2,
      holdFrom: 4,
      holdTo: 4,
    });
    const cam = await applyShot(scene, shot, { camera: await camera("rack"), subjects: POS });
    const keys = shot.focus!.keys;
    (await readback(cam, keys.map((k) => k.frame))).forEach((p, i) => {
      expect(Math.abs(p.focalDistance! - keys[i].focalDistance)).toBeLessThan(0.01);
    });
    expect(await cam.depthOfField()).toBe(true);
    expect(await cam.fStop()).toBeCloseTo(2, 4);
  });

  // ---- chaining and coverage --------------------------------------------

  it("clear_keys_false_chains_moves", async () => {
    const cam = await camera("chain");
    const home = new Vec3(300, 150, 250);
    const dolly = sl.cameraMove("dolly_in", home, [0, 0, 0], { start: 0, end: 10, amount: 50 });
    await applyShot(scene, dolly, { camera: cam });
    const mid = (dolly.movement as Keyframed).keyframes.at(-1)!.position;
    const truck = sl.cameraMove("truck_right", mid, [0, 0, 0], { start: 10, end: 20, amount: 40 });
    await applyShot(scene, truck, { camera: cam, clearKeys: false });
    const [p0, p10, p20] = await readback(cam, [0, 10, 20]);
    expectVecClose(p0.pos, home);
    expectVecClose(p10.pos, mid);
    expectVecClose(p20.pos, (truck.movement as Keyframed).keyframes.at(-1)!.position);
    await applyShot(scene, dolly, { camera: cam }); // clearKeys defaults to true: drops the truck keys
    expectVecClose((await readback(cam, [20]))[0].pos, mid);
  });

  it("apply_coverage_names_cameras_and_keeps_the_line", async () => {
    const plan = sl.dialogueCoverage(line(-1), { include: ["master", "ots"], planId: "ShotLive_cov" });
    const cams = await sl.applyCoverage(scene, plan, { subjects: POS });
    for (const cam of cams.values()) extraNames.push((await cam.name())!);
    expect([...cams.keys()]).toEqual(["MST_alice-bob", "OTS_bob_over_alice", "OTS_alice_over_bob"]);
    for (const [shotId, cam] of cams) {
      expect(await cam.label()).toBe(shotId);
      const [p] = await readback(cam, [0]);
      expect(line(-1).sideOf(p.pos), shotId).toBe(-1);
    }
  });
});
