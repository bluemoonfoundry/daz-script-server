// daz-ts/test/unit/interactionSolve.test.ts
//
// Expected numbers below were produced by running dazpy's `_interaction.py`
// (`_damped_least_squares_step`, `_invert_3x3`, `_align_single_limb_batch`)
// on the same inputs, so these tests are the cross-implementation check the
// sf7y acceptance criterion asks for. Tolerance: 1e-9 absolute.
import { describe, expect, it } from "vitest";
import {
  LimbAlignmentResult,
  alignFootTarget,
  alignHandTarget,
  alignSingleLimbTarget,
  alignmentChainNames,
  dampedLeastSquaresStep,
  invert3x3,
  rotationWithAxisLimits,
} from "../../src/interactionSolve.js";
import { HandTarget, InteractionRecipe, LimbAlignmentResult as ReexportedResult, SolveOptions, prepareInteractionRecipe } from "../../src/interactionPlan.js";
import { AxisLimit, BoneProfile, FigureRigProfile, ResolvedInteractionTarget } from "../../src/rigProfile.js";
import type { AxisName, Rotation3, Vector3 } from "../../src/rigProfile.js";

const TOL = 9; // toBeCloseTo digits -> |diff| < 0.5e-9

function expectVecClose(actual: number[] | null, expected: number[]): void {
  expect(actual).not.toBeNull();
  expect(actual!).toHaveLength(expected.length);
  actual!.forEach((v, i) => expect(v).toBeCloseTo(expected[i], TOL));
}

// ── numerics ─────────────────────────────────────────────────────────────────

describe("invert3x3", () => {
  it("matches dazpy for an invertible matrix", () => {
    const inv = invert3x3([
      [4, 7, 2],
      [3, 6, 1],
      [2, 5, 3],
    ]);
    expectVecClose(inv![0], [1.4444444444444444, -1.222222222222222, -0.5555555555555556]);
    expectVecClose(inv![1], [-0.7777777777777777, 0.8888888888888888, 0.2222222222222222]);
    expectVecClose(inv![2], [0.3333333333333333, -0.6666666666666666, 0.3333333333333333]);
  });

  it("returns null for a singular matrix", () => {
    expect(
      invert3x3([
        [1, 2, 3],
        [2, 4, 6],
        [1, 1, 1],
      ]),
    ).toBeNull();
  });
});

describe("dampedLeastSquaresStep (cross-checked against dazpy)", () => {
  it("identity columns: delta = e / (1 + λ)", () => {
    expectVecClose(dampedLeastSquaresStep([[1, 0, 0], [0, 1, 0], [0, 0, 1]], [1, 2, 3], 0.25), [0.8, 1.6, 2.4000000000000004]);
  });

  it("two-bone (6-column) chain", () => {
    const columns: Vector3[] = [
      [0.5, -1.2, 0.3],
      [2.0, 0.1, -0.7],
      [-0.4, 0.9, 1.1],
      [0.05, 0.6, -0.2],
      [1.3, -0.3, 0.8],
      [0.0, 0.2, 0.4],
    ];
    expectVecClose(dampedLeastSquaresStep(columns, [3.5, -1.25, 2.0], 0.25), [
      0.8837435069821917, 0.5553530945925151, 0.45764328542751753, -0.307307876156799, 1.5369300023070425, 0.28753933980732616,
    ]);
  });

  it("a zero column gets a zero delta", () => {
    expectVecClose(dampedLeastSquaresStep([[0.12, 0.0, -0.31], [0, 0, 0], [0.44, 0.19, 0.07]], [-2.0, 0.5, 1.0], 0.5), [-0.8531582218244226, 0.0, -0.9371995362118984]);
  });

  it("returns null for a rank-deficient undamped system and for no columns", () => {
    expect(dampedLeastSquaresStep([[1, 1, 1]], [1, 1, 1], 0.0)).toBeNull();
    expect(dampedLeastSquaresStep([], [1, 1, 1], 0.25)).toBeNull();
  });
});

describe("rotationWithAxisLimits", () => {
  it("clamps only the limited axes", () => {
    const limits = { x: new AxisLimit("x", -5, 5), z: new AxisLimit("z", 0, 10) };
    expect(rotationWithAxisLimits([12, 99, -3], limits)).toEqual([5, 99, 0]);
  });

  it("returns the rotation unchanged with no limits", () => {
    const rotation: Rotation3 = [1, 2, 3];
    expect(rotationWithAxisLimits(rotation, {})).toBe(rotation);
    expect(rotationWithAxisLimits(rotation, null)).toBe(rotation);
  });
});

// ── fixtures ─────────────────────────────────────────────────────────────────

const ARM_NAMES = ["hip", "spine1", "r_shoulder", "r_upperarm", "r_forearm", "r_hand"];

function armProfile(extraLimits: Record<string, Partial<Record<AxisName, AxisLimit>>> = {}): FigureRigProfile {
  return new FigureRigProfile({
    figureLabel: "Genesis 9",
    family: "genesis_9",
    bones: ARM_NAMES.map(
      (name, i) =>
        new BoneProfile({
          name,
          parentName: i ? ARM_NAMES[i - 1] : null,
          axisLimits: { ...(name === "r_forearm" ? { x: new AxisLimit("x", -5, 5) } : {}), ...(extraLimits[name] ?? {}) },
        }),
    ),
  });
}

const COLUMNS: Vector3[] = [
  [0.5, -1.2, 0.3],
  [2.0, 0.1, -0.7],
  [-0.4, 0.9, 1.1],
  [0.05, 0.6, -0.2],
  [1.3, -0.3, 0.8],
  [0.0, 0.2, 0.4],
  [0.7, 0.7, 0.0],
  [-0.2, 0.0, 1.5],
  [0.3, -0.9, 0.1],
  [1.0, 0.4, -0.6],
  [0.1, 1.1, 0.2],
  [-0.8, 0.3, 0.5],
];
const P0: Vector3 = [10, 100, 5];

/** A skeleton whose effector moves linearly with chain rotations (constant Jacobian) -- the same model the dazpy reference run used. */
class LinearSkeleton {
  readonly identifier = { value: "Genesis9" };
  rot: Record<string, Rotation3> = Object.fromEntries(ARM_NAMES.map((n) => [n, [0, 0, 0] as Rotation3]));
  calls: string[] = [];
  jacobianResult: "ok" | "null" | "short" = "ok";

  constructor(private readonly profile?: FigureRigProfile) {}

  async label(): Promise<string | null> {
    return "Genesis 9";
  }
  async boneMetadata(): Promise<Array<Record<string, unknown>>> {
    this.calls.push("meta");
    return ARM_NAMES.map((name, i) => ({ name, label: name, parent_name: i ? ARM_NAMES[i - 1] : null }));
  }
  async boneRotations(): Promise<Record<string, Rotation3>> {
    this.calls.push("rot");
    return { ...this.rot };
  }
  async setBoneRotations(data: Record<string, Rotation3>): Promise<void> {
    this.calls.push("set");
    Object.assign(this.rot, data);
  }
  async evaluatePoseJacobian(chain: string[], _effector: string, _step: number) {
    this.calls.push("jac");
    if (this.jacobianResult === "null") return null;
    const p: Vector3 = [...P0];
    chain.forEach((name, bi) => {
      for (let a = 0; a < 3; a++) for (let k = 0; k < 3; k++) p[k] += COLUMNS[bi * 3 + a][k] * this.rot[name][a];
    });
    const columns = this.jacobianResult === "short" ? COLUMNS.slice(0, 3) : COLUMNS;
    return { basePosition: p, columns: columns.map((c) => [...c] as Vector3) };
  }
}

function handTarget(point: Vector3 | null): ResolvedInteractionTarget {
  return new ResolvedInteractionTarget({ figureLabel: "Genesis 9", anchorName: "r_hand", boneName: "r_hand", targetPoint: point });
}

function expectRotationsClose(actual: Record<string, Rotation3>, expected: Record<string, number[]>): void {
  expect(Object.keys(actual).sort()).toEqual(Object.keys(expected).sort());
  for (const [name, rotation] of Object.entries(expected)) expectVecClose(actual[name], rotation);
}

// ── chain selection ──────────────────────────────────────────────────────────

describe("alignmentChainNames", () => {
  it("drops the effector and caps a hand chain to its 4 nearest ancestors", () => {
    const profile = armProfile();
    expect(alignmentChainNames(profile, profile.suggestPrimaryChain("r_hand")!)).toEqual(["spine1", "r_shoulder", "r_upperarm", "r_forearm"]);
  });

  it("skips helper bones", () => {
    const profile = new FigureRigProfile({
      figureLabel: "G",
      family: "genesis_9",
      bones: [
        new BoneProfile({ name: "hip" }),
        new BoneProfile({ name: "r_upperarm", parentName: "hip" }),
        new BoneProfile({ name: "r_forearm_helper", parentName: "r_upperarm", isHelper: true }),
        new BoneProfile({ name: "r_hand", parentName: "r_forearm_helper" }),
      ],
    });
    expect(alignmentChainNames(profile, profile.suggestPrimaryChain("r_hand")!)).toEqual(["hip", "r_upperarm"]);
  });
});

// ── alignSingleLimbTarget ────────────────────────────────────────────────────

describe("alignSingleLimbTarget (cross-checked against dazpy's batch path)", () => {
  it("converges in 3 iterations with the default options", async () => {
    const skeleton = new LinearSkeleton();
    const result = await alignSingleLimbTarget(skeleton, armProfile(), handTarget([14, 97, 9]));

    expect(result.chain).toEqual(["spine1", "r_shoulder", "r_upperarm", "r_forearm"]);
    expect(result.iterations).toBe(3);
    expect(result.converged).toBe(true);
    expect(result.initialError).toBeCloseTo(6.4031242374328485, TOL);
    expect(result.finalError).toBeCloseTo(0.1371542972269411, TOL);
    expectRotationsClose(result.appliedRotations, {
      spine1: [1.2303432340422855, 0.5763949007169444, 0.32869579514599767],
      r_shoulder: [-0.46835567187808724, 1.76360868753273, 0.27954387917184614],
      r_upperarm: [0.09316380695447844, 1.3053344847398058, 0.7545023347301526],
      r_forearm: [-0.13149930138176333, -0.311095038886547, -0.19543160625658096],
    });
    expect(result.diagnostics).toEqual({ stepDegrees: 1.0, damping: 0.25, tolerance: 0.15, path: "batch" });
    // one rotation read, then jacobian -> (set, jacobian) per stepping iteration
    expect(skeleton.calls).toEqual(["rot", "jac", "set", "jac", "set", "jac"]);
  });

  it("honours stepDegrees/maxIterations overrides", async () => {
    const result = await alignSingleLimbTarget(new LinearSkeleton(), armProfile(), handTarget([14, 97, 9]), { maxIterations: 40, stepDegrees: 2.0 });
    expect(result.iterations).toBe(3);
    expect(result.converged).toBe(true);
    expect(result.finalError).toBeCloseTo(0.015393964956181352, TOL);
    expectVecClose(result.appliedRotations.r_shoulder, [-0.47738033525613127, 1.7982801624972282, 0.28615776020366224]);
  });

  it("clamps to axis limits and reports non-convergence at the iteration cap", async () => {
    const skeleton = new LinearSkeleton();
    const profile = armProfile({ r_upperarm: { y: new AxisLimit("y", -0.5, 0.5) } });
    const result = await alignSingleLimbTarget(skeleton, profile, handTarget([14, 97, 9]), { maxIterations: 2 });

    expect(result.iterations).toBe(2);
    expect(result.converged).toBe(false);
    expect(result.finalError).toBeCloseTo(1.1177249718826479, TOL);
    expectRotationsClose(result.appliedRotations, {
      spine1: [1.2571338924249025, 0.5481797586954834, 0.39376956303451627],
      r_shoulder: [-0.48239952103557626, 1.8271035734939804, 0.30479099927262565],
      r_upperarm: [0.09731924512455335, 0.5, 0.7658971439806357],
      r_forearm: [-0.16264113077339268, -0.3002553763615881, -0.17086722478860922],
    });
    expect(skeleton.calls).toEqual(["rot", "jac", "set", "jac", "set", "jac"]);
  });

  it("returns already_aligned without writing rotations when inside tolerance", async () => {
    const skeleton = new LinearSkeleton();
    const result = await alignSingleLimbTarget(skeleton, armProfile(), handTarget([10.05, 100, 5]));
    expect(result.converged).toBe(true);
    expect(result.iterations).toBe(0);
    expect(result.initialError).toBeCloseTo(0.05, TOL);
    expect(result.diagnostics.reason).toBe("already_aligned");
    expect(result.appliedRotations.spine1).toEqual([0, 0, 0]);
    expect(skeleton.calls).toEqual(["rot", "jac"]);
  });

  it("reports missing_target_point and missing_chain without any HTTP calls", async () => {
    const skeleton = new LinearSkeleton();
    const noPoint = await alignSingleLimbTarget(skeleton, armProfile(), handTarget(null));
    expect(noPoint.diagnostics.reason).toBe("missing_target_point");

    const unknownBone = new ResolvedInteractionTarget({ figureLabel: "Genesis 9", anchorName: "x", boneName: "nope", targetPoint: [0, 0, 0] });
    const noChain = await alignSingleLimbTarget(skeleton, armProfile(), unknownBone);
    expect(noChain.diagnostics.reason).toBe("missing_chain");
    expect(noChain.chain).toEqual([]);
    expect(skeleton.calls).toEqual([]);
  });

  it("reports missing_effector_position when the jacobian is null", async () => {
    const skeleton = new LinearSkeleton();
    skeleton.jacobianResult = "null";
    const result = await alignSingleLimbTarget(skeleton, armProfile(), handTarget([14, 97, 9]));
    expect(result.diagnostics.reason).toBe("missing_effector_position");
    expect(result.converged).toBe(false);
  });

  it("reports jacobian_shape_mismatch instead of stepping with missing columns", async () => {
    const skeleton = new LinearSkeleton();
    skeleton.jacobianResult = "short";
    const result = await alignSingleLimbTarget(skeleton, armProfile(), handTarget([14, 97, 9]));
    expect(result.diagnostics).toEqual({ reason: "jacobian_shape_mismatch", expectedColumns: 12, actualColumns: 3 });
    expect(skeleton.calls).not.toContain("set");
  });
});

// ── alignHandTarget / alignFootTarget ────────────────────────────────────────

describe("alignHandTarget / alignFootTarget", () => {
  it("alignHandTarget builds the rig profile from boneMetadata and aligns r_hand", async () => {
    const skeleton = new LinearSkeleton();
    const result = await alignHandTarget(skeleton, [14, 97, 9]);
    expect(result).toBeInstanceOf(LimbAlignmentResult);
    expect(result.figureLabel).toBe("Genesis 9");
    expect(result.anchorName).toBe("r_hand");
    expect(result.effectorBone).toBe("r_hand");
    expect(result.converged).toBe(true);
    expect(skeleton.calls[0]).toBe("meta");
  });

  it("alignFootTarget throws when the rig has no foot anchor", async () => {
    await expect(alignFootTarget(new LinearSkeleton(), [0, 0, 0])).rejects.toThrow(/Anchor not found/);
  });

  it("a null target point yields missing_target_point, not a pull toward the origin", async () => {
    const skeleton = new LinearSkeleton();
    const result = await alignHandTarget(skeleton, null);
    expect(result.diagnostics.reason).toBe("missing_target_point");
    expect(skeleton.calls).toEqual(["meta"]);
  });
});

// ── PreparedInteractionRecipe wiring ─────────────────────────────────────────

describe("PreparedInteractionRecipe.alignLimbTargets", () => {
  function sceneWith(skeleton: LinearSkeleton) {
    const lookups: string[] = [];
    return {
      lookups,
      findSkeletonByLabel: async (label: string) => {
        lookups.push(label);
        return Object.assign(skeleton, { setPosition: async () => {} });
      },
    };
  }

  it("apply({alignLimbTargets: true}) runs one IK pass per resolved point target", async () => {
    const recipe = new InteractionRecipe({
      kind: "custom",
      actors: ["Genesis 9"],
      constraints: [new HandTarget({ figureLabel: "Genesis 9", anchorName: "r_hand", targetPoint: [14, 97, 9] })],
    });
    const prepared = prepareInteractionRecipe(recipe, { "Genesis 9": armProfile() });
    const skeleton = new LinearSkeleton();
    const scene = sceneWith(skeleton);

    const result = await prepared.apply(scene as any, { alignLimbTargets: true });

    expect(result.alignmentResults).toHaveLength(1);
    expect(result.alignmentResults[0]).toBeInstanceOf(ReexportedResult);
    expect(result.alignmentResults[0].converged).toBe(true);
    expect(result.alignmentResults[0].finalError).toBeCloseTo(0.1371542972269411, TOL);
  });

  it("falls back to plan.options.maxIterations when no override is given", async () => {
    const recipe = new InteractionRecipe({
      kind: "custom",
      actors: ["Genesis 9"],
      constraints: [new HandTarget({ figureLabel: "Genesis 9", anchorName: "r_hand", targetPoint: [14, 97, 9] })],
      options: new SolveOptions({ maxIterations: 1 }),
    });
    const prepared = prepareInteractionRecipe(recipe, { "Genesis 9": armProfile() });
    const results = await prepared.alignLimbTargets(sceneWith(new LinearSkeleton()) as any);
    expect(results[0].iterations).toBe(1);
    expect(results[0].converged).toBe(false);

    const overridden = await prepared.alignLimbTargets(sceneWith(new LinearSkeleton()) as any, { maxIterations: 12 });
    expect(overridden[0].iterations).toBe(3);
  });

  it("skips resolved targets without a target point", async () => {
    const recipe = new InteractionRecipe({
      kind: "custom",
      actors: ["Genesis 9"],
      constraints: [new HandTarget({ figureLabel: "Genesis 9", anchorName: "r_hand" })],
    });
    const prepared = prepareInteractionRecipe(recipe, { "Genesis 9": armProfile() });
    expect(prepared.resolvedTargets[0].targetPoint).toBeNull();
    const scene = sceneWith(new LinearSkeleton());
    expect(await prepared.alignLimbTargets(scene as any)).toEqual([]);
    expect(scene.lookups).toEqual([]);
  });
});
