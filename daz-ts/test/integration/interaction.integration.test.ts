// daz-ts/test/integration/interaction.integration.test.ts
//
// Phase 5C live check: canned recipes through DazScene.applyInteractionRecipe
// on two Genesis 9 figures. Gated on DAZ_SERVER_URL and on the scene already
// holding figures labelled "Genesis 9" and "Genesis 9 (2)" (load them in
// Studio first; the suite skips otherwise). Each test starts both figures in
// the rest pose at their original positions; the original pose is restored
// at the end.
//
//   DAZ_SERVER_URL=http://127.0.0.1:18811 npx vitest run test/integration/interaction.integration.test.ts
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazScene } from "../../src/scene.js";
import {
  buildFaceEachOtherRecipe,
  buildFightRecipe,
  buildHandshakeRecipe,
  buildHugRecipe,
  buildKissRecipe,
  buildSitRecipe,
  buildTouchRecipe,
  figureForward,
  type PreparedInteractionResult,
} from "../../src/interactionPlan.js";
import type { LimbAlignmentResult } from "../../src/interactionSolve.js";
import { buildRigProfilesFromSnapshot, type Vector3 } from "../../src/rigProfile.js";

const SERVER_URL = process.env.DAZ_SERVER_URL;
const A = "Genesis 9";
const B = "Genesis 9 (2)";
const IK_TIMEOUT = 600_000;
// Faced staging (y1td) puts partners at a realistic distance, so limbs start
// far from their targets: 2-degree steps, with headroom over the ~110 the kick needs.
const IK = { alignLimbTargets: true, maxIterations: 160, stepDegrees: 2 };

type Saved = {
  position: { x: number; y: number; z: number } | null;
  euler: [number, number, number] | null;
  rotations: Record<string, [number, number, number]>;
};

const distance = (a: Vector3, b: Vector3) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

describe.skipIf(!SERVER_URL)("daz-ts Phase 5C recipes against a live DAZ Studio server", () => {
  let scene: DazScene;
  let ready = false;
  const saved = new Map<string, Saved>();

  beforeAll(async () => {
    const url = new URL(SERVER_URL!);
    scene = new DazScene(new DazClient({ host: url.hostname, port: Number(url.port) || 18811 }));
    const labels = (await scene.sceneSnapshot()).map((s) => s.label);
    ready = labels.includes(A) && labels.includes(B);
    if (!ready) return;
    for (const label of [A, B]) {
      const skeleton = await scene.findSkeletonByLabel(label);
      saved.set(label, { position: await skeleton.position(), euler: await skeleton.localEuler(), rotations: await skeleton.boneRotations() });
    }
  });

  async function reset(pose: "rest" | "original"): Promise<void> {
    for (const [label, state] of saved) {
      const skeleton = await scene.findSkeletonByLabel(label);
      const rotations = pose === "original" ? state.rotations : Object.fromEntries(Object.keys(state.rotations).map((bone) => [bone, [0, 0, 0] as [number, number, number]]));
      await skeleton.setBoneRotations(rotations);
      if (state.position) await skeleton.setPosition(state.position.x, state.position.y, state.position.z);
      // Facing recipes turn the second actor; undo that too.
      if (state.euler) await skeleton.setRotation(...state.euler);
    }
  }

  beforeEach(() => reset("rest"));
  afterAll(() => reset("original"));

  /** Live world position of a bone, read back from Studio. */
  async function boneWorld(label: string, bone: string): Promise<Vector3> {
    const [entry] = await scene.sceneSnapshot([label]);
    const raw = (entry.bones as Array<Record<string, any>>).find((b) => b.name === bone)!;
    const p = raw.world_position;
    return [p.x, p.y, p.z];
  }

  /** Every IK pass converged (or started aligned), and Studio's read-back effector position matches the reported final error. */
  async function expectAligned(result: PreparedInteractionResult, count: number): Promise<LimbAlignmentResult[]> {
    expect(result.prepared.validationIssues.map((i) => i.message)).toEqual([]);
    expect(result.alignmentResults).toHaveLength(count);
    for (const r of result.alignmentResults) {
      expect(r.finalError).not.toBeNull();
      // Staging alone can already satisfy a target (e.g. handshake from the
      // rest pose): IK then reports already_aligned and changes nothing.
      if (r.diagnostics.reason === "already_aligned") expect(r.finalError!).toBeLessThan(0.15);
      else expect(r.finalError!).toBeLessThan(r.initialError!);
      expect(r.converged, `${r.figureLabel} ${r.effectorBone}: ${r.initialError} -> ${r.finalError} cm`).toBe(true);
      const live = await boneWorld(r.figureLabel, r.effectorBone);
      expect(Math.abs(distance(live, r.targetPoint!) - r.finalError!)).toBeLessThan(0.5);
    }
    return result.alignmentResults;
  }

  it("face_each_other: turns B in place toward A, moves nobody, runs no IK", async () => {
    if (!ready) return;
    const before = await (await scene.findSkeletonByLabel(B)).position();
    const result = await scene.applyInteractionRecipe(buildFaceEachOtherRecipe(A, B), IK);
    expect(result.prepared.isValid).toBe(true);
    expect(result.posePatch.figurePositions).toEqual({});
    expect(result.alignmentResults).toEqual([]);
    expect(Object.keys(result.posePatch.figureYawDegrees)).toEqual([B]);
    const live = await (await scene.findSkeletonByLabel(B)).position();
    expect(distance([live!.x, live!.y, live!.z], [before!.x, before!.y, before!.z])).toBeLessThan(0.01);
    // B's live shoulders now face A's origin (or back along A's forward when the origins coincide).
    const profiles = buildRigProfilesFromSnapshot(await scene.sceneSnapshot([A, B]));
    const forward = figureForward(profiles[B])!;
    const a = profiles[A].figurePosition!;
    const b = profiles[B].figurePosition!;
    const gap = Math.hypot(a[0] - b[0], a[2] - b[2]);
    const expected = gap >= 1 ? [(a[0] - b[0]) / gap, (a[2] - b[2]) / gap] : [-figureForward(profiles[A])![0], -figureForward(profiles[A])![2]];
    expect(forward[0] * expected[0] + forward[2] * expected[1]).toBeGreaterThan(0.999);
  });

  it("touch: stages both figures on the floor and IK brings A's hand to B's shoulder", async () => {
    if (!ready) return;
    const result = await scene.applyInteractionRecipe(buildTouchRecipe(A, B), IK);
    const [r] = await expectAligned(result, 1);
    expect(r.converged).toBe(true);
    for (const label of [A, B]) {
      const staged = result.posePatch.figurePositions[label];
      const live = await (await scene.findSkeletonByLabel(label)).position();
      expect(distance([live!.x, live!.y, live!.z], staged)).toBeLessThan(0.01);
      expect(live!.y).toBeCloseTo(0, 3);
    }
    // The hand stops short of B's shoulder joint (surface standoff), not inside it.
    expect(r.diagnostics.surfaceStandoff).toBeGreaterThan(0);
    console.log(`touch: ${r.iterations} it, error ${r.initialError!.toFixed(2)} -> ${r.finalError!.toFixed(2)} cm`);
  }, IK_TIMEOUT);

  for (const [name, build] of [
    ["handshake", () => buildHandshakeRecipe(A, B)],
    ["hug", () => buildHugRecipe(A, B)],
    ["kiss", () => buildKissRecipe(A, B)],
  ] as const) {
    it(`${name}: faces the figures, and both hands converge`, async () => {
      if (!ready) return;
      const result = await scene.applyInteractionRecipe(build(), IK);
      const results = await expectAligned(result, 2);
      expect(results.map((r) => r.figureLabel)).toEqual([A, B]);
      // B was turned to face A: its hips' forward (arm IK leaves the thighs alone) points back at A.
      const [l, r] = [await boneWorld(B, "l_thigh"), await boneWorld(B, "r_thigh")];
      const forward = [-(l[2] - r[2]), l[0] - r[0]];
      const [a, b] = [await (await scene.findSkeletonByLabel(A)).position(), await (await scene.findSkeletonByLabel(B)).position()];
      const toward = [a!.x - b!.x, a!.z - b!.z];
      const cos = (forward[0] * toward[0] + forward[1] * toward[1]) / (Math.hypot(...forward) * Math.hypot(...toward));
      expect(cos).toBeGreaterThan(0.95);
      for (const r of results) console.log(`${name} ${r.figureLabel} ${r.effectorBone}: ${r.iterations} it, ${r.initialError!.toFixed(2)} -> ${r.finalError!.toFixed(2)} cm, converged=${r.converged}`);
    }, IK_TIMEOUT);
  }

  it("fight (punch): A's hand IK targets B's head", async () => {
    if (!ready) return;
    const [r] = await expectAligned(await scene.applyInteractionRecipe(buildFightRecipe(A, B), IK), 1);
    expect(r.figureLabel).toBe(A);
    console.log(`fight: ${r.iterations} it, ${r.initialError!.toFixed(2)} -> ${r.finalError!.toFixed(2)} cm, converged=${r.converged}`);
  }, IK_TIMEOUT);

  it("fight (kick): a foot strike runs leg IK", async () => {
    if (!ready) return;
    // Genesis 9 has no `chest` anchor (its chest bones are spine3/spine4), so aim at `spine`.
    const [r] = await expectAligned(await scene.applyInteractionRecipe(buildFightRecipe(A, B, { strikeAnchor: "r_foot", targetAnchor: "spine" }), IK), 1);
    expect(r.effectorBone).toMatch(/foot/);
    console.log(`kick: ${r.iterations} it, ${r.initialError!.toFixed(2)} -> ${r.finalError!.toFixed(2)} cm, converged=${r.converged}`);
  }, IK_TIMEOUT);

  // The pelvis BalanceTarget sets the height; dazpy's sit recipe also aims both
  // feet at the seat point (no support points given), and staging averages
  // X/Z across all three, so the hip lands near (not exactly on) the seat.
  it("sit: stages the figure with its pelvis at seat height, near the seat", async () => {
    if (!ready) return;
    const seat: Vector3 = [0, 45, 60];
    const result = await scene.applyInteractionRecipe(buildSitRecipe(A, { seatPoint: seat }));
    expect(result.prepared.validationIssues.map((i) => i.message)).toEqual([]);
    const live = await (await scene.findSkeletonByLabel(A)).position();
    expect(distance([live!.x, live!.y, live!.z], result.posePatch.figurePositions[A])).toBeLessThan(0.01);
    const pelvisBone = result.prepared.rigProfiles[A].anchor("pelvis")!.boneName;
    const pelvis = await boneWorld(A, pelvisBone);
    console.log(`sit: pelvis bone ${pelvisBone} at ${pelvis.map((v) => v.toFixed(2))}, seat ${seat}`);
    expect(pelvis[1]).toBeCloseTo(seat[1], 1);
    expect(distance([pelvis[0], 0, pelvis[2]], [seat[0], 0, seat[2]])).toBeLessThan(10);
  });
});
