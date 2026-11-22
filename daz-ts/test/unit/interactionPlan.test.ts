// daz-ts/test/unit/interactionPlan.test.ts
import { describe, expect, it } from "vitest";
import {
  BalanceTarget,
  ContactTarget,
  FootTarget,
  HandTarget,
  InteractionPlan,
  InteractionPosePatch,
  InteractionRecipe,
  LimbAlignmentResult,
  LookAtTarget,
  PoseTarget,
  PreparedInteractionRecipe,
  PreparedInteractionResult,
  prepareInteractionRecipe,
  resolveInteractionTarget,
  SolveOptions,
  ValidationIssue,
} from "../../src/interactionPlan.js";
import {
  BoneProfile,
  FigureRigProfile,
  ResolvedInteractionTarget,
} from "../../src/rigProfile.js";
import type { Vector3 } from "../../src/rigProfile.js";

describe("constraint types", () => {
  it("PoseTarget.toDict carries kind and optional fields", () => {
    const target = new PoseTarget({ figureLabel: "Genesis 9", boneName: "r_hand", orientation: [0, 0, 0] });
    expect(target.toDict()).toEqual({
      kind: "PoseTarget",
      figureLabel: "Genesis 9",
      boneName: "r_hand",
      position: null,
      orientation: [0, 0, 0],
    });
  });

  it("HandTarget/FootTarget default offset to [0,0,0] and carry their own kind", () => {
    const hand = new HandTarget({ figureLabel: "Genesis 9", anchorName: "r_hand", targetPoint: [1, 2, 3] });
    const foot = new FootTarget({ figureLabel: "Genesis 9", anchorName: "l_foot", targetFigure: "Partner", targetAnchor: "r_hand" });
    expect(hand.kind).toBe("HandTarget");
    expect(hand.offset).toEqual([0, 0, 0]);
    expect(foot.kind).toBe("FootTarget");
    expect(foot.toDict().targetAnchor).toBe("r_hand");
  });

  it("ContactTarget/LookAtTarget/BalanceTarget toDict shapes", () => {
    const contact = new ContactTarget({ sourceFigure: "A", sourceBone: "r_hand", targetFigure: "B", targetBone: "chest" });
    expect(contact.toDict().kind).toBe("ContactTarget");

    const lookAt = new LookAtTarget({ figureLabel: "A", boneName: "head", targetPoint: [0, 1, 2] });
    expect(lookAt.toDict()).toEqual({ kind: "LookAtTarget", figureLabel: "A", boneName: "head", targetPoint: [0, 1, 2] });

    const balance = new BalanceTarget({ figureLabel: "A", pelvisBone: "hip", supportPoints: [[0, 0, 0]] });
    expect(balance.toDict().kind).toBe("BalanceTarget");
    expect(balance.centerOfMassHint).toBeNull();
  });
});

describe("ValidationIssue", () => {
  it("toDict carries all fields", () => {
    const issue = new ValidationIssue("error", "Genesis 9", 2, "Unknown bone");
    expect(issue.toDict()).toEqual({ severity: "error", figureLabel: "Genesis 9", constraintIndex: 2, message: "Unknown bone" });
  });
});

describe("SolveOptions", () => {
  it("defaults match dazpy's SolveOptions defaults", () => {
    const options = new SolveOptions();
    expect(options.toDict()).toEqual({
      backend: "auto",
      maxIterations: 100,
      useJointLimits: true,
      restPoseWeight: 0.15,
      contactWeight: 1.0,
      positionWeight: 1.0,
      orientationWeight: 0.25,
    });
  });

  it("round-trips through toDict/fromDict with overrides", () => {
    const options = new SolveOptions({ backend: "auto", maxIterations: 25 });
    const restored = SolveOptions.fromDict(options.toDict());
    expect(restored.backend).toBe("auto");
    expect(restored.maxIterations).toBe(25);
  });
});

function genesis9Profile(): FigureRigProfile {
  return new FigureRigProfile({
    figureLabel: "Genesis 9",
    family: "genesis_9",
    bones: [
      new BoneProfile({ name: "hip" }),
      new BoneProfile({ name: "r_hand", parentName: "hip" }),
      new BoneProfile({ name: "l_foot", parentName: "hip" }),
      new BoneProfile({ name: "head", parentName: "hip" }),
    ],
  });
}

describe("InteractionPlan", () => {
  it("validate + round-trip: a fully-valid plan produces no issues", () => {
    const plan = new InteractionPlan({
      actors: ["Genesis 9"],
      constraints: [
        new PoseTarget({ figureLabel: "Genesis 9", boneName: "r_hand", orientation: [0, 0, 0] }),
        new LookAtTarget({ figureLabel: "Genesis 9", boneName: "head", targetPoint: [0, 1, 2] }),
        new HandTarget({ figureLabel: "Genesis 9", anchorName: "r_hand", targetPoint: [1, 2, 3] }),
        new FootTarget({ figureLabel: "Genesis 9", anchorName: "l_foot", targetFigure: "Genesis 9", targetAnchor: "r_hand" }),
      ],
    });

    const data = plan.toDict();
    const restored = InteractionPlan.fromDict(data);
    const issues = restored.validate({ "Genesis 9": genesis9Profile() });

    expect(data.constraints).toHaveLength(4);
    expect(issues).toEqual([]);
  });

  it("validate reports an error for a missing bone", () => {
    const profile = new FigureRigProfile({ figureLabel: "Genesis 9", family: "genesis_9", bones: [new BoneProfile({ name: "hip" })] });
    const plan = new InteractionPlan({
      actors: ["Genesis 9"],
      constraints: [new PoseTarget({ figureLabel: "Genesis 9", boneName: "r_hand", orientation: [0, 0, 0] })],
    });

    const issues = plan.validate({ "Genesis 9": profile });

    expect(issues).toHaveLength(1);
    expect(issues[0].severity).toBe("error");
    expect(issues[0].message).toContain("r_hand");
  });

  it("resolveTargets resolves HandTarget/FootTarget constraints only", () => {
    const plan = new InteractionPlan({
      actors: ["Genesis 9"],
      constraints: [
        new PoseTarget({ figureLabel: "Genesis 9", boneName: "r_hand" }),
        new HandTarget({ figureLabel: "Genesis 9", anchorName: "r_hand", targetPoint: [1, 2, 3] }),
      ],
    });
    const resolved = plan.resolveTargets({ "Genesis 9": genesis9Profile() });
    expect(resolved).toHaveLength(1);
    expect(resolved[0].boneName).toBe("r_hand");
  });
});

describe("resolveInteractionTarget", () => {
  it("resolves a same-figure target", () => {
    const bones = [
      new BoneProfile({ name: "hip" }),
      new BoneProfile({ name: "r_hand", parentName: "hip", localPosition: [10, 20, 30] }),
    ];
    const profile = new FigureRigProfile({ figureLabel: "Genesis 9", family: "genesis_9", bones });
    const resolved = resolveInteractionTarget(
      new HandTarget({ figureLabel: "Genesis 9", anchorName: "r_hand", targetPoint: [1, 2, 3], offset: [0.5, 0, -0.5] }),
      { "Genesis 9": profile },
    );
    expect(resolved.boneName).toBe("r_hand");
    expect(resolved.targetPoint).toEqual([1.5, 2, 2.5]);
    expect(resolved.targetBone).toBeNull();
  });

  it("resolves a cross-figure target and finds the target bone", () => {
    const sourceProfile = new FigureRigProfile({
      figureLabel: "Genesis 9",
      family: "genesis_9",
      bones: [new BoneProfile({ name: "hip" }), new BoneProfile({ name: "r_hand", parentName: "hip" })],
    });
    const targetProfile = new FigureRigProfile({
      figureLabel: "Partner",
      family: "genesis_9",
      bones: [new BoneProfile({ name: "hip" }), new BoneProfile({ name: "r_hand", parentName: "hip", localPosition: [4, 5, 6] })],
    });

    const resolved = resolveInteractionTarget(
      new FootTarget({ figureLabel: "Genesis 9", anchorName: "r_hand", targetFigure: "Partner", targetAnchor: "r_hand" }),
      { "Genesis 9": sourceProfile, Partner: targetProfile },
    );

    expect(resolved.targetFigure).toBe("Partner");
    expect(resolved.targetBone).toBe("r_hand");
    expect(resolved.targetPoint).toEqual([4, 5, 6]);
  });

  it("throws for an unknown figure", () => {
    expect(() => resolveInteractionTarget(new HandTarget({ figureLabel: "Nobody", anchorName: "r_hand" }), {})).toThrow(/Unknown figure/);
  });

  it("leaves targetPoint null when nothing resolved a point (i4yf: offset is not a point)", () => {
    const profiles = { "Genesis 9": genesis9Profile() };
    const noPoint = resolveInteractionTarget(new HandTarget({ figureLabel: "Genesis 9", anchorName: "r_hand", offset: [0.5, 0, 0] }), profiles);
    const unknownFigure = resolveInteractionTarget(
      new HandTarget({ figureLabel: "Genesis 9", anchorName: "r_hand", targetFigure: "Nobody", targetAnchor: "r_hand" }),
      profiles,
    );
    expect(noPoint.targetPoint).toBeNull();
    expect(unknownFigure.targetPoint).toBeNull();
  });

  it("buildPosePatch lists an unknown target figure as unresolved instead of staging at the origin", () => {
    const profile = new FigureRigProfile({
      figureLabel: "Genesis 9",
      family: "genesis_9",
      bones: [new BoneProfile({ name: "hip" }), new BoneProfile({ name: "r_hand", parentName: "hip", localPosition: [10, 20, 30] })],
    });
    const recipe = new InteractionRecipe({
      kind: "touch",
      actors: ["Genesis 9", "Nobody"],
      constraints: [new HandTarget({ figureLabel: "Genesis 9", anchorName: "r_hand", targetFigure: "Nobody", targetAnchor: "r_hand" })],
    });
    const patch = prepareInteractionRecipe(recipe, { "Genesis 9": profile }).buildPosePatch();
    expect(patch.figurePositions).toEqual({});
    expect(patch.unresolvedTargets).toHaveLength(1);
  });
});

describe("InteractionRecipe", () => {
  it("toPlan carries actors/constraints/options/metadata", () => {
    const recipe = new InteractionRecipe({
      kind: "touch",
      actors: ["Genesis 9", "Partner"],
      constraints: [new HandTarget({ figureLabel: "Genesis 9", anchorName: "r_hand", targetFigure: "Partner", targetAnchor: "l_shoulder" })],
      metadata: { scenario: "contact" },
    });
    const plan = recipe.toPlan();
    expect(plan.actors).toEqual(["Genesis 9", "Partner"]);
    expect(plan.constraints).toHaveLength(1);
  });

  it("round-trips through toDict/fromDict, preserving kind and constraint types", () => {
    const recipe = new InteractionRecipe({
      kind: "touch",
      actors: ["Genesis 9", "Partner"],
      constraints: [new HandTarget({ figureLabel: "Genesis 9", anchorName: "r_hand", targetFigure: "Partner", targetAnchor: "l_shoulder" })],
      metadata: { scenario: "contact" },
    });
    const restored = InteractionRecipe.fromDict(recipe.toDict());
    expect(restored.kind).toBe("touch");
    expect(restored.actors).toEqual(["Genesis 9", "Partner"]);
    expect(restored.constraints).toHaveLength(1);
    expect(restored.constraints[0]).toBeInstanceOf(HandTarget);
  });
});

describe("InteractionPosePatch", () => {
  it("apply() calls setPosition once per figure via findSkeletonByLabel", async () => {
    const calls: Array<{ label: string; position: [number, number, number] }> = [];
    const scene = {
      findSkeletonByLabel: async (label: string) => ({
        setPosition: async (x: number, y: number, z: number) => {
          calls.push({ label, position: [x, y, z] });
        },
      }),
    } as any;

    const patch = new InteractionPosePatch({ figurePositions: { "Genesis 9": [1.5, 1.5, 1.5] } });
    await patch.apply(scene);

    expect(calls).toEqual([{ label: "Genesis 9", position: [1.5, 1.5, 1.5] }]);
  });

  it("toDict carries figurePositions/unresolvedTargets/diagnostics", () => {
    const patch = new InteractionPosePatch({
      figurePositions: { "Genesis 9": [1, 2, 3] },
      unresolvedTargets: [new ResolvedInteractionTarget({ figureLabel: "Partner", anchorName: "r_hand", boneName: "r_hand" })],
      diagnostics: { figureCount: 1 },
    });
    const dict = patch.toDict();
    expect(dict.figurePositions["Genesis 9"]).toEqual([1, 2, 3]);
    expect(dict.unresolvedTargets).toHaveLength(1);
    expect(dict.diagnostics.figureCount).toBe(1);
  });
});

describe("LimbAlignmentResult", () => {
  it("toDict round-trip-shape carries every field with sensible defaults", () => {
    const result = new LimbAlignmentResult({ figureLabel: "Genesis 9", anchorName: "l_hand", effectorBone: "l_hand", chain: ["hip", "l_hand"] });
    expect(result.iterations).toBe(0);
    expect(result.converged).toBe(false);
    expect(result.toDict().chain).toEqual(["hip", "l_hand"]);
  });
});

describe("PreparedInteractionResult", () => {
  it("toDict nests prepared/posePatch/alignmentResults", () => {
    const patch = new InteractionPosePatch({ figurePositions: { A: [0, 0, 0] } });
    const prepared = prepareInteractionRecipe(new InteractionRecipe({ kind: "custom", actors: [] }), {});
    const result = new PreparedInteractionResult({ prepared, posePatch: patch });
    expect(result.toDict().prepared.diagnostics.recipeKind).toBe("custom");
    expect(result.toDict().posePatch.figurePositions.A).toEqual([0, 0, 0]);
    expect(result.alignmentResults).toEqual([]);
  });
});

function touchRigProfiles() {
  const sourceProfile = new FigureRigProfile({
    figureLabel: "Genesis 9",
    family: "genesis_9",
    bones: [new BoneProfile({ name: "hip" }), new BoneProfile({ name: "r_hand", parentName: "hip", localPosition: [1, 2, 3] })],
  });
  const targetProfile = new FigureRigProfile({
    figureLabel: "Partner",
    family: "genesis_9",
    bones: [new BoneProfile({ name: "hip" }), new BoneProfile({ name: "l_shoulder", parentName: "hip", localPosition: [4, 5, 6] })],
  });
  return { "Genesis 9": sourceProfile, Partner: targetProfile };
}

describe("prepareInteractionRecipe", () => {
  it("compiles a recipe: validates, resolves targets, and records diagnostics", () => {
    const recipe = new InteractionRecipe({
      kind: "touch",
      actors: ["Genesis 9", "Partner"],
      constraints: [new HandTarget({ figureLabel: "Genesis 9", anchorName: "r_hand", targetFigure: "Partner", targetAnchor: "l_shoulder" })],
    });
    const prepared = prepareInteractionRecipe(recipe, touchRigProfiles());

    expect(prepared).toBeInstanceOf(PreparedInteractionRecipe);
    expect(prepared.isValid).toBe(true);
    expect(prepared.diagnostics.recipeKind).toBe("touch");
    expect(prepared.diagnostics.resolvedTargetCount).toBe(1);
    expect(prepared.resolvedTargets[0].boneName).toBe("r_hand");
    expect(prepared.resolvedTargets[0].targetBone).toBe("l_shoulder");
    expect(prepared.resolvedTargets[0].targetPoint).toEqual([4, 5, 6]);
  });

  it("accepts compact figure aliases in the rig-profile table", () => {
    const profile = new FigureRigProfile({
      figureLabel: "Genesis 9",
      family: "genesis_9",
      bones: [new BoneProfile({ name: "hip" }), new BoneProfile({ name: "r_hand", parentName: "hip" })],
    });
    const recipe = new InteractionRecipe({
      kind: "custom",
      actors: ["Genesis 9"],
      constraints: [new HandTarget({ figureLabel: "Genesis 9", anchorName: "r_hand", targetPoint: [1, 2, 3] })],
    });
    const prepared = prepareInteractionRecipe(recipe, { Genesis9: profile });
    expect(prepared.isValid).toBe(true);
    expect(prepared.rigProfiles.Genesis9.figureLabel).toBe("Genesis 9");
  });
});

describe("PreparedInteractionRecipe.apply", () => {
  it("moves both figures to the midpoint between the resolved anchor pair (contact-center staging)", async () => {
    const recipe = new InteractionRecipe({
      kind: "touch",
      actors: ["Genesis 9", "Partner"],
      constraints: [new HandTarget({ figureLabel: "Genesis 9", anchorName: "r_hand", targetFigure: "Partner", targetAnchor: "l_shoulder" })],
    });
    const prepared = prepareInteractionRecipe(recipe, touchRigProfiles());

    const calls: Array<{ label: string; position: [number, number, number] }> = [];
    const scene = {
      findSkeletonByLabel: async (label: string) => ({
        setPosition: async (x: number, y: number, z: number) => {
          calls.push({ label, position: [x, y, z] });
        },
      }),
    } as any;

    const result = await prepared.apply(scene);

    // Hand/foot staging is floor-locked: X/Z only, height kept (0 when unknown).
    expect(calls).toEqual([
      { label: "Genesis 9", position: [1.5, 0, 1.5] },
      { label: "Partner", position: [-1.5, 0, -1.5] },
    ]);
    expect(result.posePatch.diagnostics.figureCount).toBe(2);
    expect(result.posePatch.diagnostics.unresolvedTargetCount).toBe(0);
    expect(result.alignmentResults).toEqual([]);
  });

  it("stages a BalanceTarget figure toward its support-point centroid", async () => {
    const profile = new FigureRigProfile({
      figureLabel: "Genesis 9",
      family: "genesis_9",
      bones: [new BoneProfile({ name: "hip", localPosition: [0, 0, 0] })],
    });
    const recipe = new InteractionRecipe({
      kind: "sit",
      actors: ["Genesis 9"],
      constraints: [new BalanceTarget({ figureLabel: "Genesis 9", pelvisBone: "pelvis", centerOfMassHint: [0, 1, 2] })],
    });
    const prepared = prepareInteractionRecipe(recipe, { "Genesis 9": profile });

    const calls: Array<[number, number, number]> = [];
    const scene = { findSkeletonByLabel: async () => ({ setPosition: async (x: number, y: number, z: number) => { calls.push([x, y, z]); } }) } as any;
    await prepared.apply(scene);

    expect(calls).toEqual([[0, 1, 2]]);
  });

  it("apply() without alignLimbTargets only stages figures (no IK calls)", async () => {
    const recipe = new InteractionRecipe({
      kind: "touch",
      actors: ["Genesis 9", "Partner"],
      constraints: [new HandTarget({ figureLabel: "Genesis 9", anchorName: "r_hand", targetFigure: "Partner", targetAnchor: "l_shoulder" })],
    });
    const prepared = prepareInteractionRecipe(recipe, touchRigProfiles());
    // No boneRotations/evaluatePoseJacobian on the fake: any IK call would throw.
    const scene = { findSkeletonByLabel: async () => ({ setPosition: async () => {} }) } as any;

    const result = await prepared.apply(scene);

    expect(result.alignmentResults).toEqual([]);
  });
});

// 6r3b: live boneMetadata/sceneSnapshot report localPosition as the bone's
// translation channel (zero on an unposed figure); offsets have to come from
// worldPosition - figurePosition.
function liveProfile(label: string, figurePosition: Vector3, worldPositions: Record<string, Vector3>): FigureRigProfile {
  const { hip = [0, 0, 0] as Vector3, ...rest } = worldPositions;
  return new FigureRigProfile({
    figureLabel: label,
    family: "genesis_9",
    figurePosition,
    bones: [
      new BoneProfile({ name: "hip", localPosition: [0, 0, 0], worldPosition: hip }),
      ...Object.entries(rest).map(([name, world]) => new BoneProfile({ name, parentName: "hip", localPosition: [0, 0, 0], worldPosition: world })),
    ],
  });
}

describe("staging from live-shaped profiles (6r3b)", () => {
  it("boneOffset is worldPosition - figurePosition, falling back to localPosition", () => {
    const profile = liveProfile("A", [10, 0, 5], { r_hand: [-41, 100, 7] });
    expect(profile.boneOffset("r_hand")).toEqual([-51, 100, 2]);
    const handBuilt = new FigureRigProfile({ figureLabel: "B", family: "genesis_9", bones: [new BoneProfile({ name: "r_hand", localPosition: [1, 2, 3] })] });
    expect(handBuilt.boneOffset("r_hand")).toEqual([1, 2, 3]);
  });

  it("figurePosition round-trips through toDict/fromDict", () => {
    const restored = FigureRigProfile.fromDict(liveProfile("A", [10, 0, 5], { r_hand: [-41, 100, 7] }).toDict());
    expect(restored.figurePosition).toEqual([10, 0, 5]);
    expect(restored.boneOffset("r_hand")).toEqual([-51, 100, 2]);
  });

  it("a live touch recipe separates the figures on the floor", () => {
    const profiles = {
      A: liveProfile("A", [0, 0, 0], { r_hand: [-51.5, 99.8, 2.3] }),
      B: liveProfile("B", [0, 0, 0], { l_shoulder: [3.5, 135.5, -3.6] }),
    };
    const recipe = new InteractionRecipe({ kind: "touch", actors: ["A", "B"], constraints: [new HandTarget({ figureLabel: "A", anchorName: "r_hand", targetFigure: "B", targetAnchor: "l_shoulder" })] });
    const { A: pa, B: pb } = prepareInteractionRecipe(recipe, profiles).buildPosePatch().figurePositions;
    expect([pa[1], pb[1]]).toEqual([0, 0]);
    expect(pa[0] - 51.5).toBeCloseTo(pb[0] + 3.5, 9);
    expect(pa[2] + 2.3).toBeCloseTo(pb[2] - 3.6, 9);
    expect(Math.abs(pa[0] - pb[0])).toBeGreaterThan(50);
  });

  it("floor lock keeps each figure's current height", () => {
    const profiles = { A: liveProfile("A", [0, 12, 0], { r_hand: [-51.5, 111.8, 2.3] }) };
    const recipe = new InteractionRecipe({ kind: "custom", actors: ["A"], constraints: [new HandTarget({ figureLabel: "A", anchorName: "r_hand", targetPoint: [0, 150, 40] })] });
    const patch = prepareInteractionRecipe(recipe, profiles).buildPosePatch();
    expect(patch.figurePositions.A[0]).toBeCloseTo(51.5, 9);
    expect(patch.figurePositions.A[1]).toBe(12);
    expect(patch.figurePositions.A[2]).toBeCloseTo(37.7, 9);
  });

  it("a BalanceTarget sets height and wins over the floor lock", () => {
    const profiles = { A: liveProfile("A", [0, 0, 0], { hip: [0, 95, 0], r_hand: [-51.5, 99.8, 2.3] }) };
    const recipe = new InteractionRecipe({
      kind: "sit",
      actors: ["A"],
      constraints: [
        new BalanceTarget({ figureLabel: "A", pelvisBone: "pelvis", centerOfMassHint: [0, 50, 0] }),
        new HandTarget({ figureLabel: "A", anchorName: "r_hand", targetPoint: [-51.5, 60, 2.3] }),
      ],
    });
    expect(prepareInteractionRecipe(recipe, profiles).buildPosePatch().figurePositions.A[1]).toBe(-45);
  });

  it("apply() shifts cross-figure targets by how far staging moved the target figure", async () => {
    const profiles = {
      A: liveProfile("A", [0, 0, 0], { r_hand: [-51.5, 99.8, 2.3] }),
      B: liveProfile("B", [0, 0, 0], { l_shoulder: [3.5, 135.5, -3.6] }),
    };
    const recipe = new InteractionRecipe({ kind: "touch", actors: ["A", "B"], constraints: [new HandTarget({ figureLabel: "A", anchorName: "r_hand", targetFigure: "B", targetAnchor: "l_shoulder" })] });
    const prepared = prepareInteractionRecipe(recipe, profiles);
    const moved: Record<string, Vector3> = {};
    const scene = {
      findSkeletonByLabel: async (label: string) => ({
        setPosition: async (x: number, y: number, z: number) => {
          moved[label] = [x, y, z];
        },
        boneRotations: async () => ({}),
        setBoneRotations: async () => {},
        evaluatePoseJacobian: async (chain: string[]) => ({ basePosition: [0, 0, 0] as Vector3, columns: chain.flatMap(() => [[1, 0, 0], [0, 1, 0], [0, 0, 1]] as Vector3[]) }),
      }),
    } as any;

    // The result records the target the solver was given.
    const result = await prepared.apply(scene, { alignLimbTargets: true, maxIterations: 1 });

    const target = result.alignmentResults[0].targetPoint!;
    expect(target[0]).toBeCloseTo(3.5 + moved.B[0], 9);
    expect(target[1]).toBeCloseTo(135.5 + moved.B[1], 9);
    expect(target[2]).toBeCloseTo(-3.6 + moved.B[2], 9);
    // ...which is where A's staged hand sits in X/Z.
    expect(target[0]).toBeCloseTo(moved.A[0] - 51.5, 9);
  });
});

describe("final-review fixes", () => {
  it("prepareInteractionRecipe reports a missing anchor as a validation issue instead of throwing", () => {
    const handless = new FigureRigProfile({ figureLabel: "Prop", family: "generic", bones: [new BoneProfile({ name: "root" })] });
    const recipe = new InteractionRecipe({
      kind: "touch",
      actors: ["Genesis 9", "Prop"],
      constraints: [
        new HandTarget({ figureLabel: "Genesis 9", anchorName: "r_hand", targetFigure: "Prop", targetAnchor: "head" }),
        new HandTarget({ figureLabel: "Prop", anchorName: "l_hand", targetPoint: [0, 0, 0] }),
      ],
    });
    const prepared = prepareInteractionRecipe(recipe, { "Genesis 9": genesis9Profile(), Prop: handless });
    expect(prepared.isValid).toBe(false);
    expect(prepared.validationIssues.map((i) => i.message)).toEqual([
      "Unknown target anchor head on figure Prop",
      "Unknown anchor l_hand on figure Prop",
    ]);
    expect(prepared.resolvedTargets).toEqual([]);
  });
});
