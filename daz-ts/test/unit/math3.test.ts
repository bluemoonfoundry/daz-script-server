import { describe, expect, it } from "vitest";
import { AxisRemap, BoundingBox, Quat, Vec3, Y_UP_TO_Z_UP } from "../../src/math3.js";

function approxEqual(a: number, b: number, eps = 1e-9): boolean {
  return Math.abs(a - b) < eps;
}

describe("Vec3", () => {
  it("constructs from dict/list and round-trips to dict/list", () => {
    const v = Vec3.fromDict({ x: 1, y: 2, z: 3 });
    expect(v.toDict()).toEqual({ x: 1, y: 2, z: 3 });
    expect(Vec3.fromList([4, 5, 6]).toList()).toEqual([4, 5, 6]);
  });

  it("supports add/sub/scale/negate", () => {
    const a = new Vec3(1, 2, 3);
    const b = new Vec3(4, 5, 6);
    expect(a.add(b).toList()).toEqual([5, 7, 9]);
    expect(b.sub(a).toList()).toEqual([3, 3, 3]);
    expect(a.mul(2).toList()).toEqual([2, 4, 6]);
    expect(a.div(2).toList()).toEqual([0.5, 1, 1.5]);
    expect(a.neg().toList()).toEqual([-1, -2, -3]);
  });

  it("computes dot, cross, length, and normalize", () => {
    const a = new Vec3(1, 0, 0);
    const b = new Vec3(0, 1, 0);
    expect(a.dot(b)).toBe(0);
    expect(a.cross(b).toList()).toEqual([0, 0, 1]);
    expect(new Vec3(3, 4, 0).length()).toBe(5);
    expect(Vec3.zero().normalize().toList()).toEqual([0, 0, 0]);
    expect(new Vec3(5, 0, 0).normalize().toList()).toEqual([1, 0, 0]);
  });

  it("computes distance and lerp", () => {
    const a = new Vec3(0, 0, 0);
    const b = new Vec3(10, 0, 0);
    expect(a.distance(b)).toBe(10);
    expect(a.lerp(b, 0.5).toList()).toEqual([5, 0, 0]);
  });

  it("reflects a vector about a unit normal", () => {
    const v = new Vec3(1, -1, 0);
    const n = new Vec3(0, 1, 0);
    expect(v.reflect(n).toList()).toEqual([1, 1, 0]);
  });
});

describe("Quat", () => {
  it("identity has no rotation effect", () => {
    const q = Quat.identity();
    const v = new Vec3(1, 2, 3);
    const rotated = q.rotate(v);
    expect(approxEqual(rotated.x, v.x)).toBe(true);
    expect(approxEqual(rotated.y, v.y)).toBe(true);
    expect(approxEqual(rotated.z, v.z)).toBe(true);
  });

  it("from_euler/to_euler round-trips for a simple XYZ rotation", () => {
    const q = Quat.fromEuler(30, 45, 60, "XYZ");
    const [x, y, z] = q.toEuler("XYZ");
    expect(approxEqual(x, 30, 1e-6)).toBe(true);
    expect(approxEqual(y, 45, 1e-6)).toBe(true);
    expect(approxEqual(z, 60, 1e-6)).toBe(true);
  });

  it("from_euler/to_euler round-trips for ZYX order (regression for w-sign fix)", () => {
    const cases: Array<[number, number, number]> = [
      [10, 20, 15],
      [-25, 40, -60],
    ];
    for (const [x, y, z] of cases) {
      const q = Quat.fromEuler(x, y, z, "ZYX");
      const [rx, ry, rz] = q.toEuler("ZYX");
      expect(approxEqual(rx, x, 1e-6)).toBe(true);
      expect(approxEqual(ry, y, 1e-6)).toBe(true);
      expect(approxEqual(rz, z, 1e-6)).toBe(true);
    }
  });

  it("fromAxisAngle rotates a vector 90 degrees around Z", () => {
    const q = Quat.fromAxisAngle(new Vec3(0, 0, 1), 90);
    const rotated = q.rotate(new Vec3(1, 0, 0));
    expect(approxEqual(rotated.x, 0, 1e-9)).toBe(true);
    expect(approxEqual(rotated.y, 1, 1e-9)).toBe(true);
    expect(approxEqual(rotated.z, 0, 1e-9)).toBe(true);
  });

  it("slerp interpolates and always takes the shortest arc", () => {
    const a = Quat.identity();
    const b = Quat.fromAxisAngle(new Vec3(0, 0, 1), 180);
    const mid = a.slerp(b, 0.5);
    const [, , z] = mid.toEuler("XYZ");
    expect(approxEqual(Math.abs(z), 90, 1e-6)).toBe(true);
  });

  it("multiply composes rotations and conjugate inverts a unit quaternion", () => {
    const q = Quat.fromAxisAngle(new Vec3(0, 0, 1), 45);
    const inv = q.conjugate();
    const identity = q.multiply(inv);
    expect(approxEqual(identity.w, 1, 1e-9)).toBe(true);
    expect(approxEqual(identity.x, 0, 1e-9)).toBe(true);
  });
});

describe("BoundingBox", () => {
  it("computes center, size, and volume", () => {
    const bbox = new BoundingBox(new Vec3(0, 0, 0), new Vec3(2, 4, 6));
    expect(bbox.center.toList()).toEqual([1, 2, 3]);
    expect(bbox.size.toList()).toEqual([2, 4, 6]);
    expect(bbox.volume).toBe(48);
  });

  it("contains and overlaps report correctly", () => {
    const a = new BoundingBox(new Vec3(0, 0, 0), new Vec3(10, 10, 10));
    const b = new BoundingBox(new Vec3(5, 5, 5), new Vec3(15, 15, 15));
    const c = new BoundingBox(new Vec3(20, 20, 20), new Vec3(30, 30, 30));
    expect(a.contains(new Vec3(5, 5, 5))).toBe(true);
    expect(a.contains(new Vec3(20, 20, 20))).toBe(false);
    expect(a.overlaps(b)).toBe(true);
    expect(a.overlaps(c)).toBe(false);
  });

  it("fromPoints computes the tight bounding box", () => {
    const bbox = BoundingBox.fromPoints([new Vec3(1, 5, -2), new Vec3(-3, 0, 8)]);
    expect(bbox.min.toList()).toEqual([-3, 0, -2]);
    expect(bbox.max.toList()).toEqual([1, 5, 8]);
  });

  it("expand and union grow the box as expected", () => {
    const a = new BoundingBox(new Vec3(0, 0, 0), new Vec3(1, 1, 1));
    expect(a.expand(1).min.toList()).toEqual([-1, -1, -1]);
    expect(a.expand(1).max.toList()).toEqual([2, 2, 2]);

    const b = new BoundingBox(new Vec3(5, 5, 5), new Vec3(6, 6, 6));
    const union = a.union(b);
    expect(union.min.toList()).toEqual([0, 0, 0]);
    expect(union.max.toList()).toEqual([6, 6, 6]);
  });
});

describe("AxisRemap", () => {
  it("Y_UP_TO_Z_UP swaps Y and Z with the documented sign convention", () => {
    const pos = new Vec3(1, 2, 3);
    const remapped = Y_UP_TO_Z_UP.applyVec3(pos);
    expect(remapped.toList()).toEqual([1, -3, 2]);
  });

  it("rejects a remap that does not reference each axis exactly once", () => {
    expect(() => new AxisRemap("x", "x", "z")).toThrow();
  });

  it("applyQuat throws for a reflective (determinant -1) remap", () => {
    const reflect = new AxisRemap("x", "y", "-z"); // det = -1
    expect(() => reflect.applyQuat(Quat.identity())).toThrow(/reflection/i);
    // apply_vec3 still works for a reflective remap
    expect(reflect.applyVec3(new Vec3(1, 2, 3)).toList()).toEqual([1, 2, -3]);
  });

  it("applyQuat rotates correctly for a proper (determinant +1) remap", () => {
    const remap = Y_UP_TO_Z_UP;
    const q = Quat.fromAxisAngle(new Vec3(0, 1, 0), 90); // rotation around DAZ's up axis
    const remappedQuat = remap.applyQuat(q);
    // Rotating a remapped vector by the remapped quat should equal remapping the rotated vector.
    const v = new Vec3(1, 0, 0);
    const lhs = remap.applyVec3(q.rotate(v));
    const rhs = remappedQuat.rotate(remap.applyVec3(v));
    expect(approxEqual(lhs.x, rhs.x, 1e-9)).toBe(true);
    expect(approxEqual(lhs.y, rhs.y, 1e-9)).toBe(true);
    expect(approxEqual(lhs.z, rhs.z, 1e-9)).toBe(true);
  });

  it("applyBbox remaps and re-sorts corners", () => {
    const bbox = new BoundingBox(new Vec3(0, 0, 0), new Vec3(1, 2, 3));
    const remapped = Y_UP_TO_Z_UP.applyBbox(bbox);
    expect(remapped.min.x).toBeLessThanOrEqual(remapped.max.x);
    expect(remapped.min.y).toBeLessThanOrEqual(remapped.max.y);
    expect(remapped.min.z).toBeLessThanOrEqual(remapped.max.z);
  });
});
