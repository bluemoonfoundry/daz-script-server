// daz-ts/test/unit/interactionPlan.test.ts
import { describe, expect, it } from "vitest";
import {
  BalanceTarget,
  ContactTarget,
  FootTarget,
  HandTarget,
  LookAtTarget,
  PoseTarget,
  SolveOptions,
  ValidationIssue,
} from "../../src/interactionPlan.js";

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
