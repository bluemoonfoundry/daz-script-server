// daz-ts/test/unit/rigProfile.test.ts
import { describe, expect, it } from "vitest";
import { AxisLimit, BoneProfile, addVec3, averageVec3, midpointVec3, subVec3 } from "../../src/rigProfile.js";

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
