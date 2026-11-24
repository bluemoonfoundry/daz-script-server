// daz-ts/test/unit/interactionRecipes.test.ts
// Phase 5C: canned recipe builders + applyInteractionRecipeToScene /
// DazScene.applyInteractionRecipe. Expected constraint lists mirror dazpy's
// build_*_recipe output for the same inputs.
import { describe, expect, it, vi } from "vitest";
import {
  applyInteractionRecipeToScene,
  buildFaceEachOtherRecipe,
  buildFightRecipe,
  buildHandshakeRecipe,
  buildHugRecipe,
  buildKissRecipe,
  buildSitRecipe,
  buildTouchRecipe,
  FACING_MIN_SEPARATION,
  FACING_REACH_FRACTION,
  figureForward,
  WRAP_BACK_POINT,
  WRAP_FINGER_POINT,
  WRAP_HAND_LIMIT,
  WRAP_SEPARATION,
  WRAP_SIDE_POINTS,
  InteractionRecipe,
  planFacing,
  prepareInteractionRecipe,
  rotateAboutY,
  PreparedInteractionResult,
} from "../../src/interactionPlan.js";
import { BoneProfile, buildRigProfilesFromSnapshot, FigureRigProfile } from "../../src/rigProfile.js";
import { DazClient } from "../../src/client.js";
import { DazScene } from "../../src/scene.js";

const ORIGIN = [0, 0, 0];
const lookAt = (figureLabel: string) => ({ kind: "LookAtTarget", figureLabel, boneName: "head", targetPoint: ORIGIN });
const anchor = (kind: "HandTarget" | "FootTarget", figureLabel: string, anchorName: string, extra: Record<string, unknown> = {}) => ({
  kind,
  figureLabel,
  anchorName,
  targetFigure: null,
  targetAnchor: null,
  targetPoint: null,
  offset: [0, 0, 0],
  surfaceStandoff: null,
  wrap: false,
  ...extra,
});
const constraintsOf = (recipe: InteractionRecipe) => recipe.constraints.map((c) => c.toDict());

describe("buildSitRecipe", () => {
  it("balances on the seat point and plants both feet on it", () => {
    const recipe = buildSitRecipe("A", { seatPoint: [1, 2, 3] });
    expect(recipe.kind).toBe("sit");
    expect(recipe.actors).toEqual(["A"]);
    expect(constraintsOf(recipe)).toEqual([
      { kind: "BalanceTarget", figureLabel: "A", pelvisBone: "pelvis", supportPoints: [[1, 2, 3]], centerOfMassHint: [1, 2, 3] },
      anchor("FootTarget", "A", "l_foot", { targetPoint: [1, 2, 3] }),
      anchor("FootTarget", "A", "r_foot", { targetPoint: [1, 2, 3] }),
    ]);
    expect(recipe.metadata).toEqual({ seatPoint: [1, 2, 3] });
  });

  it("maps feet onto support points in order, reusing the last for extra feet", () => {
    const recipe = buildSitRecipe("A", { seatPoint: [0, 5, 0], supportPoints: [[1, 0, 0]], footAnchors: ["l_foot", "r_foot"] });
    const dicts = constraintsOf(recipe);
    expect(dicts[0]).toMatchObject({ supportPoints: [[1, 0, 0]], centerOfMassHint: [0, 5, 0] });
    expect(dicts[1]).toMatchObject({ anchorName: "l_foot", targetPoint: [1, 0, 0] });
    expect(dicts[2]).toMatchObject({ anchorName: "r_foot", targetPoint: [1, 0, 0] });
  });

  it("leaves feet untargeted and seat metadata null with no points", () => {
    const recipe = buildSitRecipe("A");
    const dicts = constraintsOf(recipe);
    expect(dicts[0]).toMatchObject({ supportPoints: [], centerOfMassHint: null });
    expect(dicts[1]).toMatchObject({ targetPoint: null });
    expect(recipe.metadata).toEqual({ seatPoint: null });
  });
});

describe("buildTouchRecipe", () => {
  it("defaults to right hand on the target's left shoulder", () => {
    const recipe = buildTouchRecipe("A", "B");
    expect(recipe.kind).toBe("touch");
    expect(recipe.actors).toEqual(["A", "B"]);
    expect(constraintsOf(recipe)).toEqual([anchor("HandTarget", "A", "r_hand", { targetFigure: "B", targetAnchor: "l_shoulder" })]);
    expect(recipe.metadata).toEqual({ sourceAnchor: "r_hand", targetAnchor: "l_shoulder" });
  });

  it("passes custom anchors and an explicit point through", () => {
    const recipe = buildTouchRecipe("A", "B", { sourceAnchor: "l_hand", targetAnchor: "head", targetPoint: [1, 2, 3] });
    expect(constraintsOf(recipe)[0]).toMatchObject({ anchorName: "l_hand", targetAnchor: "head", targetPoint: [1, 2, 3] });
  });
});

describe("buildKissRecipe", () => {
  it("mutual look-at plus each hand on the partner's opposite shoulder", () => {
    const recipe = buildKissRecipe("A", "B");
    expect(recipe.kind).toBe("kiss");
    expect(constraintsOf(recipe)).toEqual([
      lookAt("A"),
      lookAt("B"),
      anchor("HandTarget", "A", "r_hand", { targetFigure: "B", targetAnchor: "l_shoulder" }),
      anchor("HandTarget", "B", "l_hand", { targetFigure: "A", targetAnchor: "r_shoulder" }),
    ]);
    expect(recipe.metadata).toEqual({ interaction: "kiss" });
  });

  it("mirrors sides for a left-hand lead", () => {
    const dicts = constraintsOf(buildKissRecipe("A", "B", { aAnchor: "l_hand" }));
    expect(dicts[2]).toMatchObject({ anchorName: "l_hand", targetAnchor: "r_shoulder" });
    expect(dicts[3]).toMatchObject({ anchorName: "r_hand", targetAnchor: "l_shoulder" });
  });
});

describe("buildHandshakeRecipe", () => {
  it("mutual look-at plus hand-to-hand both ways", () => {
    const recipe = buildHandshakeRecipe("A", "B");
    expect(recipe.kind).toBe("handshake");
    expect(constraintsOf(recipe)).toEqual([
      lookAt("A"),
      lookAt("B"),
      anchor("HandTarget", "A", "r_hand", { targetFigure: "B", targetAnchor: "r_hand" }),
      anchor("HandTarget", "B", "r_hand", { targetFigure: "A", targetAnchor: "r_hand" }),
    ]);
    expect(recipe.metadata).toEqual({ interaction: "handshake" });
  });
});

describe("buildHugRecipe", () => {
  it("each arm wraps toward the partner's far shoulder", () => {
    const recipe = buildHugRecipe("A", "B", { bAnchor: "l_hand" });
    expect(recipe.kind).toBe("hug");
    expect(constraintsOf(recipe)).toEqual([
      lookAt("A"),
      lookAt("B"),
      anchor("HandTarget", "A", "r_hand", { targetFigure: "B", targetAnchor: "l_shoulder", wrap: true }),
      anchor("HandTarget", "B", "l_hand", { targetFigure: "A", targetAnchor: "r_shoulder", wrap: true }),
    ]);
    expect(InteractionRecipe.fromDict(recipe.toDict()).toDict()).toEqual(recipe.toDict());
    expect(recipe.metadata).toEqual({ interaction: "hug" });
  });
});

describe("buildFaceEachOtherRecipe", () => {
  it("is mutual look-at only", () => {
    const recipe = buildFaceEachOtherRecipe("A", "B");
    expect(recipe.kind).toBe("face_each_other");
    expect(constraintsOf(recipe)).toEqual([lookAt("A"), lookAt("B")]);
    expect(recipe.metadata).toEqual({ interaction: "face_each_other" });
  });
});

describe("buildFightRecipe", () => {
  it("punch: hand strike at the defender's head, then mutual look-at", () => {
    const recipe = buildFightRecipe("A", "B");
    expect(recipe.kind).toBe("fight");
    expect(constraintsOf(recipe)).toEqual([anchor("HandTarget", "A", "r_hand", { targetFigure: "B", targetAnchor: "head" }), lookAt("A"), lookAt("B")]);
    expect(recipe.metadata).toEqual({ strikeAnchor: "r_hand", targetAnchor: "head", strikeTarget: "l_shoulder" });
  });

  it("kick: a foot strike anchor becomes a FootTarget", () => {
    const recipe = buildFightRecipe("A", "B", { strikeAnchor: "r_foot", targetAnchor: "chest" });
    expect(recipe.constraints[0].toDict()).toEqual(anchor("FootTarget", "A", "r_foot", { targetFigure: "B", targetAnchor: "chest" }));
    expect(recipe.metadata.strikeTarget).toBe("l_hip");
  });

  it("every strike target resolves on Genesis 9 and Genesis 8 rigs (lb1i)", () => {
    const chain = (label: string, family: string, names: string[]) =>
      new FigureRigProfile({ figureLabel: label, family, bones: names.map((name, i) => new BoneProfile({ name, parentName: i === 0 ? null : names[0] })) });
    const g9 = chain("G9", "genesis_9", ["hip", "pelvis", "spine1", "spine2", "spine3", "spine4", "neck1", "head", "l_shoulder", "l_upperarm", "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot"]);
    const g8 = chain("G8", "genesis_3_8", ["hip", "pelvis", "abdomenLower", "abdomenUpper", "chestLower", "chestUpper", "neckLower", "head", "lCollar", "lShldrBend", "lThighBend", "lThighTwist", "lShin", "lFoot", "rThighBend", "rThighTwist", "rShin", "rFoot"]);
    const expected: Array<[FigureRigProfile, Record<string, string>]> = [
      [g9, { chest: "spine3", l_hip: "l_thigh", r_hip: "r_thigh", l_knee: "l_shin" }],
      [g8, { chest: "chestLower", l_hip: "lThighBend", r_hip: "rThighBend", l_knee: "lShin" }],
    ];
    for (const [profile, anchors] of expected) {
      for (const [name, bone] of Object.entries(anchors)) expect(profile.anchor(name)?.boneName, `${profile.figureLabel} ${name}`).toBe(bone);
      expect(profile.anchor("l_hip")?.role).toBe("hip");
      for (const strikeAnchor of ["r_hand", "r_foot", "head"]) {
        const target = buildFightRecipe("A", "B", { strikeAnchor }).metadata.strikeTarget as string;
        expect(profile.anchor(target), `${profile.figureLabel} ${strikeAnchor} -> ${target}`).not.toBeNull();
      }
    }
  });

  it("other strike anchors fall back to a hand constraint with a chest strike target", () => {
    const recipe = buildFightRecipe("A", "B", { strikeAnchor: "head" });
    expect(recipe.constraints[0].kind).toBe("HandTarget");
    expect(recipe.metadata.strikeTarget).toBe("chest");
  });
});

// ── scene integration ────────────────────────────────────────────────────────

function snapshotEntry(label: string, x: number) {
  const bone = (name: string, parent: string | null, world: [number, number, number]) => ({
    name,
    label: name,
    parent_name: parent,
    local_position: [0, 0, 0],
    world_position: world,
  });
  return {
    name: label.replace(/\s+/g, ""),
    label,
    position: [x, 0, 0],
    bones: [
      bone("hip", null, [x, 100, 0]),
      bone("r_shoulder", "hip", [x - 10, 145, 0]),
      bone("r_upperarm", "r_shoulder", [x - 20, 140, 0]),
      bone("r_hand", "r_upperarm", [x - 50, 100, 0]),
      bone("l_shoulder", "hip", [x + 10, 145, 0]),
      bone("l_upperarm", "l_shoulder", [x + 20, 140, 0]),
      bone("l_hand", "l_upperarm", [x + 50, 100, 0]),
      bone("head", "hip", [x, 165, 0]),
    ],
  };
}

function fakeScene(snapshot: unknown[]) {
  const positions: Array<{ label: string; position: number[] }> = [];
  const rotations: Array<{ label: string; rotation: number[] }> = [];
  const scene = {
    skeletons: vi.fn(async () => []),
    sceneSnapshot: vi.fn(async () => snapshot as Array<Record<string, unknown>>),
    findSkeletonByLabel: vi.fn(async (label: string) => ({
      setPosition: async (x: number, y: number, z: number) => {
        positions.push({ label, position: [x, y, z] });
      },
      localEuler: async () => [0, 10, 0] as [number, number, number],
      setRotation: async (x: number, y: number, z: number) => {
        rotations.push({ label, rotation: [x, y, z] });
      },
    })),
  };
  return { scene, positions, rotations };
}

describe("applyInteractionRecipeToScene", () => {
  it("builds rig profiles from one sceneSnapshot() call, then turns and stages the partner", async () => {
    const { scene, positions, rotations } = fakeScene([snapshotEntry("Genesis 9", -100), snapshotEntry("Partner", 100)]);

    const result = await applyInteractionRecipeToScene(scene as any, buildHandshakeRecipe("Genesis 9", "Partner"));

    expect(result).toBeInstanceOf(PreparedInteractionResult);
    expect(scene.sceneSnapshot).toHaveBeenCalledTimes(1);
    expect(result.prepared.isValid).toBe(true);
    expect(result.prepared.resolvedTargets).toHaveLength(2);
    // Handshake faces the figures: Genesis 9 stays put, Partner turns 180 and stands in front (+Z) of it.
    expect(rotations).toEqual([{ label: "Partner", rotation: [0, 190, 0] }]);
    expect(positions.map((p) => p.label)).toEqual(["Partner"]);
    const [x, y, z] = positions[0].position;
    expect(x).toBeCloseTo(-100, 9);
    expect(y).toBe(0);
    expect(z).toBeGreaterThanOrEqual(FACING_MIN_SEPARATION);
    expect(result.alignmentResults).toEqual([]);
  });

  it("uses supplied rigProfiles without touching sceneSnapshot()", async () => {
    const { scene } = fakeScene([]);
    const profile = new FigureRigProfile({ figureLabel: "A", family: "genesis_9", bones: [new BoneProfile({ name: "head", localPosition: [0, 0, 0] })] });

    const result = await applyInteractionRecipeToScene(scene as any, buildFaceEachOtherRecipe("A", "A"), { rigProfiles: { A: profile } });

    expect(scene.sceneSnapshot).not.toHaveBeenCalled();
    expect(result.prepared.rigProfiles.A).toBe(profile);
  });

  it("reports unknown actors as validation errors instead of throwing", async () => {
    const { scene } = fakeScene([snapshotEntry("Genesis 9", 0)]);

    const result = await applyInteractionRecipeToScene(scene as any, buildFaceEachOtherRecipe("Genesis 9", "Ghost"));

    expect(result.prepared.isValid).toBe(false);
    expect(result.prepared.validationIssues.some((issue) => issue.figureLabel === "Ghost")).toBe(true);
  });
});

describe("DazScene.applyInteractionRecipe", () => {
  it("delegates to applyInteractionRecipeToScene with the live scene", async () => {
    const scene = new DazScene(new DazClient({ token: "" }));
    const snapshot = vi.spyOn(scene, "sceneSnapshot").mockResolvedValue([snapshotEntry("Genesis 9", -100), snapshotEntry("Partner", 100)]);
    const staged: string[] = [];
    vi.spyOn(scene, "findSkeletonByLabel").mockImplementation(async (label: string) => ({ setPosition: async () => { staged.push(label); } }) as any);

    const result = await scene.applyInteractionRecipe(buildTouchRecipe("Genesis 9", "Partner"));

    expect(snapshot).toHaveBeenCalledTimes(1);
    expect(result.prepared.recipe.kind).toBe("touch");
    expect(staged.sort()).toEqual(["Genesis 9", "Partner"]);
  });
});

// ── facing (y1td) ────────────────────────────────────────────────────────────

describe("facing staging", () => {
  // Both figures face +Z, side by side: the rest-pose setup that left the
  // second actor's cross-body reach behind it.
  const profiles = () => buildRigProfilesFromSnapshot([snapshotEntry("Genesis 9", -100), snapshotEntry("Partner", 100)]);
  const distance = (a: number[], b: number[]) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

  it("rotateAboutY turns +Z into +X at +90 degrees", () => {
    const v = rotateAboutY([0, 5, 1], 90);
    expect(v[0]).toBeCloseTo(1, 12);
    expect(v[1]).toBe(5);
    expect(v[2]).toBeCloseTo(0, 12);
  });

  it("figureForward reads +Z from left/right shoulders", () => {
    expect(figureForward(profiles()["Genesis 9"])).toEqual([-0, 0, 1]);
  });

  it("turns the second actor of a recipe with mutual look-at; touch (no look-at) turns nobody", () => {
    for (const build of [buildHugRecipe, buildKissRecipe, buildHandshakeRecipe, buildFightRecipe]) {
      expect(planFacing(build("Genesis 9", "Partner").toPlan(), profiles())).toEqual({ Partner: { anchor: "Genesis 9", yawDegrees: 180 } });
    }
    expect(planFacing(buildTouchRecipe("Genesis 9", "Partner").toPlan(), profiles())).toEqual({});
  });

  it("face_each_other: the second actor turns in place toward the first (2dnz)", () => {
    // Partner at x=+100 faces +Z; Genesis 9 is at x=-100, so it turns to -X.
    const prepared = prepareInteractionRecipe(buildFaceEachOtherRecipe("Genesis 9", "Partner"), profiles());
    expect(prepared.facing).toEqual({ Partner: { anchor: "Genesis 9", yawDegrees: -90 } });
    expect(figureForward(prepared.rigProfiles.Partner)![0]).toBeCloseTo(-1, 12);
    const patch = prepared.buildPosePatch();
    expect(patch.figureYawDegrees).toEqual({ Partner: -90 });
    expect(patch.figurePositions).toEqual({});
  });

  it("face_each_other: coincident origins fall back to facing back along the first actor's forward", () => {
    const together = buildRigProfilesFromSnapshot([snapshotEntry("Genesis 9", 0), snapshotEntry("Partner", 0)]);
    expect(planFacing(buildFaceEachOtherRecipe("Genesis 9", "Partner").toPlan(), together)).toEqual({ Partner: { anchor: "Genesis 9", yawDegrees: 180 } });
  });

  it("hug: the turned partner stands in front at embrace distance (3shz)", () => {
    const prepared = prepareInteractionRecipe(buildHugRecipe("Genesis 9", "Partner"), profiles());
    expect(figureForward(prepared.rigProfiles.Partner)![2]).toBeCloseTo(-1, 12);
    const patch = prepared.buildPosePatch();
    expect(patch.figureYawDegrees).toEqual({ Partner: 180 });
    expect(Object.keys(patch.figurePositions)).toEqual(["Partner"]);
    const [x, y, z] = patch.figurePositions.Partner;
    expect([x, y]).toEqual([-100, 0]);
    // Wrapped arms stage the partner inside the reach minimum.
    expect(z).toBe(WRAP_SEPARATION);
    expect(z).toBeLessThan(FACING_MIN_SEPARATION);
    // B's right hand -> A's left shoulder is now on B's near side, not behind it.
    const bTarget = prepared.resolvedTargets[1];
    expect(bTarget.figureLabel).toBe("Partner");
    expect(bTarget.targetPoint![0]).toBeGreaterThan(-100);
  });

  it("hug: each arm passes the waypoints around the partner's side, then stops on its back", async () => {
    const prepared = prepareInteractionRecipe(buildHugRecipe("Genesis 9", "Partner"), profiles());
    const chains: string[][] = [];
    const scene = {
      findSkeletonByLabel: async () => ({
        setPosition: async () => {},
        localEuler: async () => [0, 0, 0] as [number, number, number],
        setRotation: async () => {},
        boneRotations: async () => ({}),
        setBoneRotations: async () => {},
        evaluatePoseJacobian: async (chain: string[]) => (chains.push(chain), { basePosition: [0, -500, 0], columns: chain.flatMap(() => [[1, 0, 0], [0, 1, 0], [0, 0, 1]]) }),
      }),
    };
    const result = await prepared.apply(scene as any, { alignLimbTargets: true, maxIterations: 1 });
    const partnerZ = result.posePatch.figurePositions.Partner[2];
    const [a, b] = result.alignmentResults;
    // A's right hand -> Partner's left shoulder. Partner faces -Z: its left is -X, its back +Z.
    const waypoints = a.diagnostics.wrapWaypoints as number[][];
    expect(waypoints).toHaveLength(WRAP_SIDE_POINTS.length);
    waypoints.forEach((point, i) => {
      expect(point[0]).toBeCloseTo(-100 - WRAP_SIDE_POINTS[i][0], 9);
      expect(point[2]).toBeCloseTo(partnerZ + WRAP_SIDE_POINTS[i][1], 9);
    });
    expect(a.targetPoint![0]).toBeCloseTo(-100 - WRAP_BACK_POINT[0], 9);
    expect(a.targetPoint![2]).toBeCloseTo(partnerZ + WRAP_BACK_POINT[1], 9);
    expect(a.targetPoint![1]).toBeLessThan(145);
    // One iteration per pass, summed; the first pass's starting error.
    expect(a.iterations).toBe(WRAP_SIDE_POINTS.length + 1);
    expect(a.initialError).toBeCloseTo(distance([0, -500, 0], waypoints[0]), 9);
    // B's right hand -> Genesis 9's left shoulder: Genesis 9 faces +Z, its left is +X, its back -Z.
    expect(b.targetPoint![0]).toBeCloseTo(-100 + WRAP_BACK_POINT[0], 9);
    expect(b.targetPoint![2]).toBeCloseTo(-WRAP_BACK_POINT[1], 9);
    // No finger bones in this rig: no hand-aim pass.
    expect(chains.every((chain) => chain.length > 1)).toBe(true);
  });

  it("hug: the wrapped hand alone turns its fingertips across the back, within the hand limit", async () => {
    const withFingers = (label: string, x: number) => {
      const entry = snapshotEntry(label, x);
      const tip = (name: string, parent: string, world: [number, number, number]) => ({ name, label: name, parent_name: parent, local_position: [0, 0, 0], world_position: world });
      entry.bones.push(tip("r_mid1", "r_hand", [x - 58, 94, 0]) as any, tip("r_mid3", "r_mid1", [x - 64, 88, 0]) as any);
      return entry;
    };
    const rigs = buildRigProfilesFromSnapshot([withFingers("Genesis 9", -100), withFingers("Partner", 100)]);
    const prepared = prepareInteractionRecipe(buildHugRecipe("Genesis 9", "Partner"), rigs);
    const aims: Array<{ chain: string[]; effector: string }> = [];
    const set: Array<Record<string, number[]>> = [];
    const scene = {
      findSkeletonByLabel: async () => ({
        setPosition: async () => {},
        localEuler: async () => [0, 0, 0] as [number, number, number],
        setRotation: async () => {},
        boneRotations: async () => ({}),
        setBoneRotations: async (rotations: Record<string, number[]>) => {
          set.push(rotations);
        },
        evaluatePoseJacobian: async (chain: string[], effector: string) => {
          if (chain.length === 1) aims.push({ chain, effector });
          // Huge columns: one step lands far past the limit, so the result must be clamped.
          return { basePosition: [0, -500, 0], columns: chain.flatMap(() => [[1, 0, 0], [0, 1, 0], [0, 0, 1]]) };
        },
      }),
    };
    const result = await prepared.apply(scene as any, { alignLimbTargets: true, maxIterations: 1, stepDegrees: 200 });
    expect(aims[0]).toEqual({ chain: ["r_hand"], effector: "r_mid3" });
    const [a] = result.alignmentResults;
    expect(a.diagnostics.handAimBone).toBe("r_mid3");
    expect(a.diagnostics.handAimClamped).toBe(true);
    const handSets = set.filter((r) => Object.keys(r).length === 1 && "r_hand" in r);
    const last = handSets[handSets.length - 1].r_hand;
    expect(last.every((v) => Math.abs(v) <= WRAP_HAND_LIMIT)).toBe(true);
    expect(WRAP_FINGER_POINT[0]).toBeLessThan(WRAP_BACK_POINT[0]); // fingertips aim nearer the spine than the wrist
  });

  it("handshake: both hands aim at one meeting point between the figures, within reach", async () => {
    const prepared = prepareInteractionRecipe(buildHandshakeRecipe("Genesis 9", "Partner"), profiles());
    const scene = {
      findSkeletonByLabel: async () => ({
        setPosition: async () => {},
        localEuler: async () => [0, 0, 0] as [number, number, number],
        setRotation: async () => {},
        boneRotations: async () => ({}),
        setBoneRotations: async () => {},
        // Effector parked far away: one iteration, then the step budget runs out.
        evaluatePoseJacobian: async (chain: string[]) => ({ basePosition: [0, -500, 0], columns: chain.flatMap(() => [[1, 0, 0], [0, 1, 0], [0, 0, 1]]) }),
      }),
    };
    const result = await prepared.apply(scene as any, { alignLimbTargets: true, maxIterations: 1 });
    const [a, b] = result.alignmentResults;
    expect(a.diagnostics.meetingPoint).toEqual(b.diagnostics.meetingPoint);
    const meeting = a.diagnostics.meetingPoint as number[];
    const partnerZ = result.posePatch.figurePositions.Partner[2];
    expect(meeting[0]).toBeCloseTo(-100, 9);
    expect(meeting[2]).toBeCloseTo(partnerZ / 2, 9);
    // Each wrist stops short of the meeting point, toward its own figure.
    expect(a.targetPoint![2]).toBeLessThan(meeting[2]);
    expect(b.targetPoint![2]).toBeGreaterThan(meeting[2]);
    // Reach runs from the start of the last two long segments (r_shoulder -> r_upperarm -> r_hand), not the hip.
    const reach = distance([-10, 145, 0], [-20, 140, 0]) + distance([-20, 140, 0], [-50, 100, 0]);
    expect(distance(a.targetPoint!, [-110, 145, 0])).toBeCloseTo(reach * FACING_REACH_FRACTION, 6);
  });
});
