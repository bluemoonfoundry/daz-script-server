// daz-ts/test/unit/interactionPlan.test.ts
import { describe, expect, it } from "vitest";
import {
  BalanceTarget,
  ContactTarget,
  FootTarget,
  HandTarget,
  InteractionPlan,
  LookAtTarget,
  PoseTarget,
  resolveInteractionTarget,
  SolveOptions,
  ValidationIssue,
} from "../../src/interactionPlan.js";
import { BoneProfile, FigureRigProfile } from "../../src/rigProfile.js";

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
});
