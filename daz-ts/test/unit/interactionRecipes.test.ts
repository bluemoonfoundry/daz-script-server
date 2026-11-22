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
  InteractionRecipe,
  PreparedInteractionResult,
} from "../../src/interactionPlan.js";
import { BoneProfile, FigureRigProfile } from "../../src/rigProfile.js";
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
      anchor("HandTarget", "B", "l_hand", { targetFigure: "A", targetAnchor: "l_shoulder" }),
    ]);
    expect(recipe.metadata).toEqual({ interaction: "kiss" });
  });

  it("mirrors sides for a left-hand lead", () => {
    const dicts = constraintsOf(buildKissRecipe("A", "B", { aAnchor: "l_hand" }));
    expect(dicts[2]).toMatchObject({ anchorName: "l_hand", targetAnchor: "r_shoulder" });
    expect(dicts[3]).toMatchObject({ anchorName: "r_hand", targetAnchor: "r_shoulder" });
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
  it("each hand reaches the partner's far shoulder", () => {
    const recipe = buildHugRecipe("A", "B", { bAnchor: "l_hand" });
    expect(recipe.kind).toBe("hug");
    expect(constraintsOf(recipe)).toEqual([
      lookAt("A"),
      lookAt("B"),
      anchor("HandTarget", "A", "r_hand", { targetFigure: "B", targetAnchor: "l_shoulder" }),
      anchor("HandTarget", "B", "l_hand", { targetFigure: "A", targetAnchor: "r_shoulder" }),
    ]);
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
  const scene = {
    skeletons: vi.fn(async () => []),
    sceneSnapshot: vi.fn(async () => snapshot as Array<Record<string, unknown>>),
    findSkeletonByLabel: vi.fn(async (label: string) => ({
      setPosition: async (x: number, y: number, z: number) => {
        positions.push({ label, position: [x, y, z] });
      },
    })),
  };
  return { scene, positions };
}

describe("applyInteractionRecipeToScene", () => {
  it("builds rig profiles from one sceneSnapshot() call, then stages every actor", async () => {
    const { scene, positions } = fakeScene([snapshotEntry("Genesis 9", -100), snapshotEntry("Partner", 100)]);

    const result = await applyInteractionRecipeToScene(scene as any, buildHandshakeRecipe("Genesis 9", "Partner"));

    expect(result).toBeInstanceOf(PreparedInteractionResult);
    expect(scene.sceneSnapshot).toHaveBeenCalledTimes(1);
    expect(result.prepared.isValid).toBe(true);
    expect(result.prepared.resolvedTargets).toHaveLength(2);
    expect(positions.map((p) => p.label).sort()).toEqual(["Genesis 9", "Partner"]);
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
