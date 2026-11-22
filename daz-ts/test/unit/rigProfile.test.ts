// daz-ts/test/unit/rigProfile.test.ts
import { describe, expect, it } from "vitest";
import {
  addVec3,
  averageVec3,
  AxisLimit,
  BoneProfile,
  buildRigProfile,
  buildRigProfilesFromSnapshot,
  defaultAxisLimitsForBone,
  FigureRigProfile,
  InteractionAnchor,
  lookupRigProfile,
  looksLikeHelper,
  midpointVec3,
  subVec3,
} from "../../src/rigProfile.js";

describe("rigProfile vector helpers", () => {
  it("addVec3 sums two vectors and passes through when one side is null", () => {
    expect(addVec3([1, 2, 3], [4, 5, 6])).toEqual([5, 7, 9]);
    expect(addVec3(null, [4, 5, 6])).toEqual([4, 5, 6]);
    expect(addVec3([1, 2, 3], null)).toEqual([1, 2, 3]);
  });

  it("subVec3 subtracts componentwise", () => {
    expect(subVec3([4, 5, 6], [1, 2, 3])).toEqual([3, 3, 3]);
  });

  it("midpointVec3 averages two points", () => {
    expect(midpointVec3([0, 0, 0], [2, 4, 6])).toEqual([1, 2, 3]);
  });

  it("averageVec3 returns null for an empty/undefined list, else the componentwise mean", () => {
    expect(averageVec3(undefined)).toBeNull();
    expect(averageVec3([])).toBeNull();
    expect(averageVec3([[0, 0, 0], [2, 2, 2], [4, 4, 4]])).toEqual([2, 2, 2]);
  });
});

describe("AxisLimit", () => {
  it("round-trips through toDict/fromDict", () => {
    const limit = new AxisLimit("x", -45, 45, 10, 0.5);
    const restored = AxisLimit.fromDict(limit.toDict());
    expect(restored.axis).toBe("x");
    expect(restored.minDegrees).toBe(-45);
    expect(restored.maxDegrees).toBe(45);
    expect(restored.preferredDegrees).toBe(10);
    expect(restored.weight).toBe(0.5);
  });

  it("defaults preferredDegrees to 0 and weight to 1", () => {
    const limit = new AxisLimit("y", -10, 10);
    expect(limit.preferredDegrees).toBe(0);
    expect(limit.weight).toBe(1);
  });
});

describe("BoneProfile", () => {
  it("round-trips through toDict/fromDict including axisLimits", () => {
    const bone = new BoneProfile({
      name: "l_forearm",
      label: "Left Forearm",
      parentName: "l_shoulder",
      rotationOrder: "XYZ",
      localPosition: [1, 0, 0],
      worldPosition: [10, 0, 0],
      restRotation: [0, 0, 0],
      axisLimits: { x: new AxisLimit("x", -160, 160) },
      isTwist: false,
      isHelper: false,
    });
    const restored = BoneProfile.fromDict(bone.toDict());
    expect(restored.name).toBe("l_forearm");
    expect(restored.parentName).toBe("l_shoulder");
    expect(restored.localPosition).toEqual([1, 0, 0]);
    expect(restored.axisLimits.x?.minDegrees).toBe(-160);
  });

  it("defaults optional fields to null/empty", () => {
    const bone = new BoneProfile({ name: "hip" });
    expect(bone.label).toBeNull();
    expect(bone.parentName).toBeNull();
    expect(bone.localPosition).toBeNull();
    expect(bone.axisLimits).toEqual({});
    expect(bone.isTwist).toBe(false);
    expect(bone.isHelper).toBe(false);
  });
});


function genesis9Bones(): BoneProfile[] {
  const hip = new BoneProfile({ name: "hip" });
  const spine = new BoneProfile({ name: "spine", parentName: "hip" });
  const chest = new BoneProfile({ name: "chest", parentName: "spine" });
  const neck = new BoneProfile({ name: "neck", parentName: "chest" });
  const head = new BoneProfile({ name: "head", parentName: "neck" });
  const lHand = new BoneProfile({ name: "l_hand", label: "Left Hand", parentName: "chest" });
  const rHand = new BoneProfile({ name: "r_hand", label: "Right Hand", parentName: "chest" });
  const lFoot = new BoneProfile({ name: "l_foot", label: "Left Foot", parentName: "hip" });
  const rFoot = new BoneProfile({ name: "r_foot", label: "Right Foot", parentName: "hip" });
  return [hip, spine, chest, neck, head, lHand, rHand, lFoot, rFoot];
}

function genesis38Bones(): BoneProfile[] {
  const hip = new BoneProfile({ name: "hip" });
  const spine = new BoneProfile({ name: "abdomenLower", parentName: "hip" });
  const chest = new BoneProfile({ name: "chestLower", parentName: "abdomenLower" });
  const lCollar = new BoneProfile({ name: "lCollar", parentName: "chestLower" });
  const rCollar = new BoneProfile({ name: "rCollar", parentName: "chestLower" });
  const lForearmBend = new BoneProfile({ name: "lForearmBend", parentName: "lCollar" });
  const rForearmBend = new BoneProfile({ name: "rForearmBend", parentName: "rCollar" });
  const lHand = new BoneProfile({ name: "lHand", label: "Left Hand", parentName: "lForearmBend" });
  const rHand = new BoneProfile({ name: "rHand", label: "Right Hand", parentName: "rForearmBend" });
  const lFoot = new BoneProfile({ name: "lFoot", label: "Left Foot", parentName: "hip" });
  const rFoot = new BoneProfile({ name: "rFoot", label: "Right Foot", parentName: "hip" });
  return [hip, spine, chest, lCollar, rCollar, lForearmBend, rForearmBend, lHand, rHand, lFoot, rFoot];
}

describe("FigureRigProfile", () => {
  it("ancestry/chainTo return root-to-bone order", () => {
    const profile = new FigureRigProfile({ figureLabel: "Genesis 9", family: "genesis_9", bones: genesis9Bones() });
    expect(profile.chainTo("head")).toEqual(["hip", "spine", "chest", "neck", "head"]);
  });

  it("anchorMap resolves canonical snake_case anchors for Genesis 9 naming", () => {
    const profile = new FigureRigProfile({ figureLabel: "Genesis 9", family: "genesis_9", bones: genesis9Bones() });
    const anchors = profile.anchorMap();
    expect(anchors.get("l_hand")?.boneName).toBe("l_hand");
    expect(anchors.get("r_hand")?.boneName).toBe("r_hand");
    expect(anchors.get("l_foot")?.role).toBe("foot");
    expect(profile.anchor("r_hand")).toBeInstanceOf(InteractionAnchor);
  });

  it("anchorMap resolves camelCase Genesis 3/8 bone names via canonical anchor keys", () => {
    const profile = new FigureRigProfile({ figureLabel: "Bob Genesis 8", family: "genesis_3_8", bones: genesis38Bones() });
    const anchors = profile.anchorMap();
    expect(anchors.get("r_hand")?.boneName).toBe("rHand");
    expect(anchors.get("l_hand")?.boneName).toBe("lHand");
    expect(anchors.get("l_foot")?.boneName).toBe("lFoot");
    expect(anchors.get("r_foot")?.boneName).toBe("rFoot");
  });

  it("suggestPrimaryChain classifies a hand bone into a hand-role chain ending at that bone", () => {
    const profile = new FigureRigProfile({ figureLabel: "Genesis 9", family: "genesis_9", bones: genesis9Bones() });
    const chain = profile.suggestPrimaryChain("r_hand");
    expect(chain?.role).toBe("hand");
    expect(chain?.effectorBone).toBe("r_hand");
    expect(chain?.bones).toEqual(["hip", "spine", "chest", "r_hand"]);
  });

  it("suggestPrimaryChain returns null for an unknown bone", () => {
    const profile = new FigureRigProfile({ figureLabel: "Genesis 9", family: "genesis_9", bones: genesis9Bones() });
    expect(profile.suggestPrimaryChain("nonexistent")).toBeNull();
  });

  it("requireAnchor throws for an unknown anchor name", () => {
    const profile = new FigureRigProfile({ figureLabel: "Genesis 9", family: "genesis_9", bones: genesis9Bones() });
    expect(() => profile.requireAnchor("tail")).toThrow(/Anchor not found/);
  });

  it("resolveAnchorTarget resolves a same-figure hand target and applies the offset", () => {
    const bones = genesis9Bones();
    const rHandIndex = bones.findIndex((b) => b.name === "r_hand");
    bones[rHandIndex] = new BoneProfile({ ...bones[rHandIndex], localPosition: [10, 20, 30] } as any);
    const profile = new FigureRigProfile({ figureLabel: "Genesis 9", family: "genesis_9", bones });
    const resolved = profile.resolveAnchorTarget({
      figureLabel: "Genesis 9",
      anchorName: "r_hand",
      targetPoint: [1, 2, 3],
      offset: [0.5, 0, -0.5],
    });
    expect(resolved.boneName).toBe("r_hand");
    expect(resolved.targetPoint).toEqual([1.5, 2, 2.5]);
    expect(resolved.targetBone).toBeNull();
  });

  it("toDict/fromDict round-trips a full profile", () => {
    const profile = new FigureRigProfile({ figureLabel: "Genesis 9", family: "genesis_9", bones: genesis9Bones() });
    const restored = FigureRigProfile.fromDict(profile.toDict());
    expect(restored.figureLabel).toBe("Genesis 9");
    expect(restored.family).toBe("genesis_9");
    expect(restored.boneNames()).toEqual(profile.boneNames());
  });
});

describe("lookupRigProfile", () => {
  it("matches by exact key, then by compact-name alias", () => {
    const profile = new FigureRigProfile({ figureLabel: "Genesis 9", family: "genesis_9", bones: [] });
    const table = { "Genesis 9": profile };
    expect(lookupRigProfile(table, "Genesis 9")).toBe(profile);
    expect(lookupRigProfile(table, "Genesis9")).toBe(profile);
    expect(lookupRigProfile(table, "Nobody")).toBeNull();
  });
});

function fakeMetadataSkeleton(identifierValue: string, label: string | null, bones: Array<Record<string, unknown>>) {
  return {
    identifier: { value: identifierValue },
    label: async () => label,
    boneMetadata: async () => bones,
  };
}

describe("defaultAxisLimitsForBone", () => {
  it("returns loose limits for a forearm bone, spanning both positive and negative degrees", () => {
    const limits = defaultAxisLimitsForBone("r_forearm");
    expect(limits.x).toBeInstanceOf(AxisLimit);
    expect(limits.x!.minDegrees).toBeLessThan(0);
    expect(limits.x!.maxDegrees).toBeGreaterThan(0);
  });

  it("returns {} for a bone name matching no preset", () => {
    expect(defaultAxisLimitsForBone("some_prop_root")).toEqual({});
  });
});

describe("buildRigProfile", () => {
  it("detects genesis_9 family and resolves snake_case anchors from boneMetadata()", async () => {
    const skeleton = fakeMetadataSkeleton("Genesis9", "Genesis 9", [
      { name: "hip", label: "Hip", parent_name: null, rotation_order: "XYZ", local_position: [0, 0, 0], world_position: [0, 0, 0], local_euler: [0, 0, 0] },
      { name: "l_hand", label: "Left Hand", parent_name: "hip", local_position: [1, 0, 0] },
      { name: "r_hand", label: "Right Hand", parent_name: "hip", local_position: [-1, 0, 0] },
      { name: "l_foot", label: "Left Foot", parent_name: "hip" },
      { name: "r_foot", label: "Right Foot", parent_name: "hip" },
    ]);
    const profile = await buildRigProfile(skeleton);
    expect(profile.figureLabel).toBe("Genesis 9");
    expect(profile.family).toBe("genesis_9");
    expect(profile.anchor("r_hand")?.boneName).toBe("r_hand");
    expect(profile.bone("l_hand").localPosition).toEqual([1, 0, 0]);
  });

  it("falls back to the identifier value when label() returns null", async () => {
    const skeleton = fakeMetadataSkeleton("Genesis9", null, [{ name: "hip", parent_name: null }]);
    const profile = await buildRigProfile(skeleton);
    expect(profile.figureLabel).toBe("Genesis9");
  });
});

describe("buildRigProfilesFromSnapshot", () => {
  it("builds one profile per skeleton, keyed by both label and internal name", () => {
    const snapshot = [
      {
        name: "Genesis9",
        label: "Genesis 9",
        bones: [
          { name: "hip", label: "Hip", parent_name: null },
          { name: "r_hand", label: "Right Hand", parent_name: "hip" },
        ],
      },
    ];
    const profiles = buildRigProfilesFromSnapshot(snapshot);
    expect(profiles["Genesis 9"]).toBeDefined();
    expect(profiles["Genesis9"]).toBe(profiles["Genesis 9"]);
    expect(profiles["Genesis 9"].anchor("r_hand")?.boneName).toBe("r_hand");
  });
});

describe("FigureRigProfile bone ownership", () => {
  it("copies the bones array so later caller pushes cannot desync the bone index", () => {
    const bones = [new BoneProfile({ name: "hip" })];
    const profile = new FigureRigProfile({ figureLabel: "A", family: "generic", bones });
    bones.push(new BoneProfile({ name: "l_hand", parentName: "hip" }));
    expect(profile.boneNames()).toEqual(["hip"]);
    expect(profile.anchorNames()).not.toContain("l_hand");
  });
});

describe("Genesis 8 limb classification (i9b6)", () => {
  it("looksLikeHelper treats 'end' as a whole word, so *Bend bones are not helpers", () => {
    for (const [name, label] of [
      ["lForearmBend", "Left Forearm Bend"],
      ["rShldrBend", "Right Shoulder Bend"],
      ["lThighBend", "Left Thigh Bend"],
    ]) {
      expect(looksLikeHelper(name, label), name).toBe(false);
    }
    for (const [name, label] of [
      ["lEyeEnd", null],
      ["hand_end", null],
      ["tip", "End Point"],
      ["Endpoint", null],
      ["hipHelper", null],
    ] as const) {
      expect(looksLikeHelper(name, label), name).toBe(true);
    }
  });

  it("maps lShldrBend to the shoulder anchor, arm chain, and arm axis limits", async () => {
    const raw: Array<Record<string, unknown>> = [
      { name: "hip", label: "Hip", parent_name: null },
      { name: "chestUpper", label: "Chest Upper", parent_name: "hip" },
    ];
    for (const [side, word] of [["l", "Left"], ["r", "Right"]]) {
      raw.push(
        { name: `${side}Collar`, label: `${word} Collar`, parent_name: "chestUpper" },
        { name: `${side}ShldrBend`, label: `${word} Shoulder Bend`, parent_name: `${side}Collar` },
        { name: `${side}ShldrTwist`, label: `${word} Shoulder Twist`, parent_name: `${side}ShldrBend` },
        { name: `${side}ForearmBend`, label: `${word} Forearm Bend`, parent_name: `${side}ShldrTwist` },
        { name: `${side}ForearmTwist`, label: `${word} Forearm Twist`, parent_name: `${side}ForearmBend` },
        { name: `${side}Hand`, label: `${word} Hand`, parent_name: `${side}ForearmTwist` },
      );
    }
    const profile = await buildRigProfile(fakeMetadataSkeleton("Genesis8Male", "Bob Genesis 8", raw));

    expect(profile.bone("lForearmBend").isHelper).toBe(false);
    expect(profile.bone("lShldrBend").isHelper).toBe(false);
    expect(profile.anchor("l_shoulder")?.boneName).toBe("lShldrBend");
    expect(profile.anchor("r_shoulder")?.boneName).toBe("rShldrBend");
    const armEffectors = profile.chainSuggestions().filter((c) => c.role === "arm").map((c) => c.effectorBone).sort();
    expect(armEffectors).toEqual(["lShldrBend", "rShldrBend"]);
    expect(profile.suggestPrimaryChain("lShldrBend")?.role).toBe("arm");
    expect(Object.keys(profile.bone("lShldrBend").axisLimits).length).toBeGreaterThan(0);
  });
});
