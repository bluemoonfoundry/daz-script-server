/**
 * Pure TypeScript 3D math for DAZ Studio workflows.
 *
 * No external dependencies. Mirrors dazpy's `math3.py` exactly, providing
 * {@link Vec3}, {@link Quat}, {@link BoundingBox}, and {@link AxisRemap}
 * with direct support for the dict shapes returned by the daz-ts API
 * (once Phase 2 proxy classes exist).
 */

// ── Vec3 ──────────────────────────────────────────────────────────────────

/** Immutable 3-component vector. All methods return new {@link Vec3} instances. */
export class Vec3 {
  readonly x: number;
  readonly y: number;
  readonly z: number;

  constructor(x: number, y: number, z: number) {
    this.x = x;
    this.y = y;
    this.z = z;
  }

  static fromDict(d: { x: number; y: number; z: number }): Vec3 {
    return new Vec3(d.x, d.y, d.z);
  }

  static fromList(v: number[]): Vec3 {
    return new Vec3(v[0], v[1], v[2]);
  }

  static zero(): Vec3 {
    return new Vec3(0, 0, 0);
  }

  toDict(): { x: number; y: number; z: number } {
    return { x: this.x, y: this.y, z: this.z };
  }

  toList(): number[] {
    return [this.x, this.y, this.z];
  }

  add(other: Vec3): Vec3 {
    return new Vec3(this.x + other.x, this.y + other.y, this.z + other.z);
  }

  sub(other: Vec3): Vec3 {
    return new Vec3(this.x - other.x, this.y - other.y, this.z - other.z);
  }

  mul(scalar: number): Vec3 {
    return new Vec3(this.x * scalar, this.y * scalar, this.z * scalar);
  }

  div(scalar: number): Vec3 {
    return new Vec3(this.x / scalar, this.y / scalar, this.z / scalar);
  }

  neg(): Vec3 {
    return new Vec3(-this.x, -this.y, -this.z);
  }

  equals(other: Vec3): boolean {
    return this.x === other.x && this.y === other.y && this.z === other.z;
  }

  dot(other: Vec3): number {
    return this.x * other.x + this.y * other.y + this.z * other.z;
  }

  cross(other: Vec3): Vec3 {
    return new Vec3(
      this.y * other.z - this.z * other.y,
      this.z * other.x - this.x * other.z,
      this.x * other.y - this.y * other.x,
    );
  }

  lengthSq(): number {
    return this.x * this.x + this.y * this.y + this.z * this.z;
  }

  length(): number {
    return Math.sqrt(this.lengthSq());
  }

  normalize(): Vec3 {
    const mag = this.length();
    if (mag < 1e-10) {
      return new Vec3(0, 0, 0);
    }
    return this.div(mag);
  }

  distanceSq(other: Vec3): number {
    return this.sub(other).lengthSq();
  }

  distance(other: Vec3): number {
    return Math.sqrt(this.distanceSq(other));
  }

  lerp(other: Vec3, t: number): Vec3 {
    return new Vec3(
      this.x + (other.x - this.x) * t,
      this.y + (other.y - this.y) * t,
      this.z + (other.z - this.z) * t,
    );
  }

  /** Reflect this vector about `normal` (must be unit length). */
  reflect(normal: Vec3): Vec3 {
    return this.sub(normal.mul(2 * this.dot(normal)));
  }
}

// ── Quat ──────────────────────────────────────────────────────────────────

type RotationOrder = "XYZ" | "XZY" | "YXZ" | "YZX" | "ZXY" | "ZYX";

function eulerToQuat(hx: number, hy: number, hz: number, order: RotationOrder): [number, number, number, number] {
  const cx = Math.cos(hx), sx = Math.sin(hx);
  const cy = Math.cos(hy), sy = Math.sin(hy);
  const cz = Math.cos(hz), sz = Math.sin(hz);

  switch (order) {
    case "XYZ":
      return [sx*cy*cz + cx*sy*sz, cx*sy*cz - sx*cy*sz, cx*cy*sz + sx*sy*cz, cx*cy*cz - sx*sy*sz];
    case "XZY":
      return [sx*cy*cz - cx*sy*sz, cx*sy*cz - sx*cy*sz, cx*cy*sz + sx*sy*cz, cx*cy*cz + sx*sy*sz];
    case "YXZ":
      return [sx*cy*cz + cx*sy*sz, cx*sy*cz - sx*cy*sz, cx*cy*sz - sx*sy*cz, cx*cy*cz + sx*sy*sz];
    case "YZX":
      return [sx*cy*cz + cx*sy*sz, cx*sy*cz + sx*cy*sz, cx*cy*sz - sx*sy*cz, cx*cy*cz - sx*sy*sz];
    case "ZXY":
      return [sx*cy*cz - cx*sy*sz, cx*sy*cz + sx*cy*sz, cx*cy*sz + sx*sy*cz, cx*cy*cz - sx*sy*sz];
    case "ZYX":
      // dazpy's math3.py has a sign bug here; verified correct via Hamilton-product
      // derivation — see daz-script-server-z0c1. w should be `+ sx*sy*sz`, not `-`.
      return [sx*cy*cz - cx*sy*sz, cx*sy*cz + sx*cy*sz, cx*cy*sz - sx*sy*cz, cx*cy*cz + sx*sy*sz];
    default:
      throw new Error(`Unknown rotation order: ${String(order)}. Expected one of XYZ XZY YXZ YZX ZXY ZYX.`);
  }
}

function quatToEuler(m: number[][], order: RotationOrder): [number, number, number] {
  const SAFE = 1.0 - 1e-6;
  const clamp = (v: number) => Math.max(-1, Math.min(1, v));
  const deg = (r: number) => (r * 180) / Math.PI;

  switch (order) {
    case "XYZ": {
      const sy = clamp(m[0][2]);
      const y = deg(Math.asin(sy));
      if (Math.abs(sy) < SAFE) {
        return [deg(Math.atan2(-m[1][2], m[2][2])), y, deg(Math.atan2(-m[0][1], m[0][0]))];
      }
      return [deg(Math.atan2(m[2][1], m[1][1])), y, 0];
    }
    case "XZY": {
      const sz = clamp(-m[0][1]);
      const z = deg(Math.asin(sz));
      if (Math.abs(sz) < SAFE) {
        return [deg(Math.atan2(m[2][1], m[1][1])), deg(Math.atan2(m[0][2], m[0][0])), z];
      }
      return [deg(Math.atan2(-m[1][2], m[2][2])), 0, z];
    }
    case "YXZ": {
      const sx = clamp(-m[1][2]);
      const x = deg(Math.asin(sx));
      if (Math.abs(sx) < SAFE) {
        return [x, deg(Math.atan2(m[0][2], m[2][2])), deg(Math.atan2(m[1][0], m[1][1]))];
      }
      return [x, deg(Math.atan2(-m[0][1], m[0][0])), 0];
    }
    case "YZX": {
      const sz = clamp(m[1][0]);
      const z = deg(Math.asin(sz));
      if (Math.abs(sz) < SAFE) {
        return [deg(Math.atan2(-m[1][2], m[1][1])), deg(Math.atan2(-m[2][0], m[0][0])), z];
      }
      return [deg(Math.atan2(m[0][1], m[2][1])), 0, z];
    }
    case "ZXY": {
      const sx = clamp(m[2][1]);
      const x = deg(Math.asin(sx));
      if (Math.abs(sx) < SAFE) {
        return [x, deg(Math.atan2(-m[2][0], m[2][2])), deg(Math.atan2(-m[0][1], m[1][1]))];
      }
      return [x, deg(Math.atan2(m[0][2], m[0][0])), 0];
    }
    case "ZYX": {
      const sy = clamp(-m[2][0]);
      const y = deg(Math.asin(sy));
      if (Math.abs(sy) < SAFE) {
        return [deg(Math.atan2(m[2][1], m[2][2])), y, deg(Math.atan2(m[1][0], m[0][0]))];
      }
      return [deg(Math.atan2(-m[0][1], m[1][1])), y, 0];
    }
    default:
      throw new Error(`Unknown rotation order: ${String(order)}. Expected one of XYZ XZY YXZ YZX ZXY ZYX.`);
  }
}

/**
 * Unit quaternion representing a 3D rotation.
 *
 * Stored as `(x, y, z, w)` — imaginary components first, scalar last —
 * matching the dict format returned by the DAZ Studio Script Server API.
 * All methods return new {@link Quat} instances.
 */
export class Quat {
  readonly x: number;
  readonly y: number;
  readonly z: number;
  readonly w: number;

  constructor(x: number, y: number, z: number, w: number) {
    this.x = x;
    this.y = y;
    this.z = z;
    this.w = w;
  }

  static identity(): Quat {
    return new Quat(0, 0, 0, 1);
  }

  static fromDict(d: { x: number; y: number; z: number; w: number }): Quat {
    return new Quat(d.x, d.y, d.z, d.w);
  }

  /** Create from Euler angles in degrees using intrinsic rotations (DAZ Studio's bone-rotation convention). */
  static fromEuler(x: number, y: number, z: number, order: RotationOrder = "XYZ"): Quat {
    const hx = ((x * Math.PI) / 180) * 0.5;
    const hy = ((y * Math.PI) / 180) * 0.5;
    const hz = ((z * Math.PI) / 180) * 0.5;
    const [qx, qy, qz, qw] = eulerToQuat(hx, hy, hz, order);
    return new Quat(qx, qy, qz, qw);
  }

  static fromAxisAngle(axis: Vec3, angleDeg: number): Quat {
    const n = axis.normalize();
    const half = ((angleDeg * Math.PI) / 180) * 0.5;
    const s = Math.sin(half);
    return new Quat(n.x * s, n.y * s, n.z * s, Math.cos(half));
  }

  toDict(): { x: number; y: number; z: number; w: number } {
    return { x: this.x, y: this.y, z: this.z, w: this.w };
  }

  /** Return the equivalent 3x3 rotation matrix (row-major, right-handed). */
  toMatrix(): number[][] {
    const { x, y, z, w } = this;
    const x2 = 2 * x * x, y2 = 2 * y * y, z2 = 2 * z * z;
    const xy = 2 * x * y, xz = 2 * x * z, yz = 2 * y * z;
    const wx = 2 * w * x, wy = 2 * w * y, wz = 2 * w * z;
    return [
      [1 - y2 - z2, xy - wz, xz + wy],
      [xy + wz, 1 - x2 - z2, yz - wx],
      [xz - wy, yz + wx, 1 - x2 - y2],
    ];
  }

  /** Extract Euler angles in degrees. Inverse of {@link fromEuler} for the same `order`. */
  toEuler(order: RotationOrder = "XYZ"): [number, number, number] {
    return quatToEuler(this.toMatrix(), order);
  }

  /** Hamilton product `this * other`. */
  multiply(other: Quat): Quat {
    const { x: ax, y: ay, z: az, w: aw } = this;
    const { x: bx, y: by, z: bz, w: bw } = other;
    return new Quat(
      aw * bx + ax * bw + ay * bz - az * by,
      aw * by - ax * bz + ay * bw + az * bx,
      aw * bz + ax * by - ay * bx + az * bw,
      aw * bw - ax * bx - ay * by - az * bz,
    );
  }

  conjugate(): Quat {
    return new Quat(-this.x, -this.y, -this.z, this.w);
  }

  length(): number {
    return Math.sqrt(this.x ** 2 + this.y ** 2 + this.z ** 2 + this.w ** 2);
  }

  normalize(): Quat {
    const mag = this.length();
    if (mag < 1e-10) {
      return Quat.identity();
    }
    return new Quat(this.x / mag, this.y / mag, this.z / mag, this.w / mag);
  }

  dot(other: Quat): number {
    return this.x * other.x + this.y * other.y + this.z * other.z + this.w * other.w;
  }

  /** Rotate vector `v` by this quaternion (sandwich product `q * v * q⁻¹`). */
  rotate(v: Vec3): Vec3 {
    const { x: qx, y: qy, z: qz, w: qw } = this;
    const { x: vx, y: vy, z: vz } = v;
    const tx = 2 * (qy * vz - qz * vy);
    const ty = 2 * (qz * vx - qx * vz);
    const tz = 2 * (qx * vy - qy * vx);
    return new Vec3(vx + qw * tx + qy * tz - qz * ty, vy + qw * ty + qz * tx - qx * tz, vz + qw * tz + qx * ty - qy * tx);
  }

  /** Spherical linear interpolation. Always takes the shortest arc. */
  slerp(other: Quat, t: number): Quat {
    let o = other;
    let d = this.dot(o);
    if (d < 0) {
      o = new Quat(-o.x, -o.y, -o.z, -o.w);
      d = -d;
    }
    d = Math.min(1, d);

    if (d > 0.9995) {
      const result = new Quat(
        this.x + t * (o.x - this.x),
        this.y + t * (o.y - this.y),
        this.z + t * (o.z - this.z),
        this.w + t * (o.w - this.w),
      );
      return result.normalize();
    }

    const theta0 = Math.acos(d);
    const sinTheta0 = Math.sin(theta0);
    const theta = theta0 * t;
    const sinTheta = Math.sin(theta);
    const cosTheta = Math.cos(theta);

    const s0 = cosTheta - (d * sinTheta) / sinTheta0;
    const s1 = sinTheta / sinTheta0;

    return new Quat(s0 * this.x + s1 * o.x, s0 * this.y + s1 * o.y, s0 * this.z + s1 * o.z, s0 * this.w + s1 * o.w);
  }

  equals(other: Quat): boolean {
    return this.x === other.x && this.y === other.y && this.z === other.z && this.w === other.w;
  }
}

// ── BoundingBox ───────────────────────────────────────────────────────────

/** Axis-aligned bounding box. */
export class BoundingBox {
  readonly min: Vec3;
  readonly max: Vec3;

  constructor(min: Vec3, max: Vec3) {
    this.min = min;
    this.max = max;
  }

  static fromDict(d: { min: { x: number; y: number; z: number }; max: { x: number; y: number; z: number } }): BoundingBox {
    return new BoundingBox(Vec3.fromDict(d.min), Vec3.fromDict(d.max));
  }

  static fromPoints(points: Vec3[]): BoundingBox {
    if (points.length === 0) {
      throw new Error("fromPoints requires at least one point");
    }
    const xs = points.map((p) => p.x);
    const ys = points.map((p) => p.y);
    const zs = points.map((p) => p.z);
    return new BoundingBox(
      new Vec3(Math.min(...xs), Math.min(...ys), Math.min(...zs)),
      new Vec3(Math.max(...xs), Math.max(...ys), Math.max(...zs)),
    );
  }

  toDict(): { min: { x: number; y: number; z: number }; max: { x: number; y: number; z: number } } {
    return { min: this.min.toDict(), max: this.max.toDict() };
  }

  get center(): Vec3 {
    return new Vec3((this.min.x + this.max.x) * 0.5, (this.min.y + this.max.y) * 0.5, (this.min.z + this.max.z) * 0.5);
  }

  get size(): Vec3 {
    return this.max.sub(this.min);
  }

  get volume(): number {
    const s = this.size;
    return s.x * s.y * s.z;
  }

  contains(point: Vec3): boolean {
    return (
      this.min.x <= point.x && point.x <= this.max.x &&
      this.min.y <= point.y && point.y <= this.max.y &&
      this.min.z <= point.z && point.z <= this.max.z
    );
  }

  overlaps(other: BoundingBox): boolean {
    return (
      this.min.x <= other.max.x && this.max.x >= other.min.x &&
      this.min.y <= other.max.y && this.max.y >= other.min.y &&
      this.min.z <= other.max.z && this.max.z >= other.min.z
    );
  }

  expand(amount: number): BoundingBox {
    const v = new Vec3(amount, amount, amount);
    return new BoundingBox(this.min.sub(v), this.max.add(v));
  }

  union(other: BoundingBox): BoundingBox {
    return new BoundingBox(
      new Vec3(Math.min(this.min.x, other.min.x), Math.min(this.min.y, other.min.y), Math.min(this.min.z, other.min.z)),
      new Vec3(Math.max(this.max.x, other.max.x), Math.max(this.max.y, other.max.y), Math.max(this.max.z, other.max.z)),
    );
  }
}

// ── AxisRemap ─────────────────────────────────────────────────────────────

const AXIS_INDEX: Record<string, number> = { x: 0, y: 1, z: 2 };

function parseAxisSpec(spec: string): [number, number] {
  if (!spec) {
    throw new Error(`Invalid axis spec ${JSON.stringify(spec)}; expected one of x, y, z, -x, -y, -z`);
  }
  let sign = 1;
  let name = spec;
  if (name[0] === "+" || name[0] === "-") {
    sign = name[0] === "-" ? -1 : 1;
    name = name.slice(1);
  }
  if (!(name in AXIS_INDEX)) {
    throw new Error(`Invalid axis spec ${JSON.stringify(spec)}; expected one of x, y, z, -x, -y, -z`);
  }
  return [AXIS_INDEX[name], sign];
}

function mat3Det(m: number[][]): number {
  return (
    m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) -
    m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) +
    m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
  );
}

function mat3ToQuat(m: number[][]): Quat {
  const trace = m[0][0] + m[1][1] + m[2][2];
  let x: number, y: number, z: number, w: number;
  if (trace > 0) {
    const s = Math.sqrt(trace + 1.0) * 2.0;
    w = 0.25 * s;
    x = (m[2][1] - m[1][2]) / s;
    y = (m[0][2] - m[2][0]) / s;
    z = (m[1][0] - m[0][1]) / s;
  } else if (m[0][0] > m[1][1] && m[0][0] > m[2][2]) {
    const s = Math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2.0;
    w = (m[2][1] - m[1][2]) / s;
    x = 0.25 * s;
    y = (m[0][1] + m[1][0]) / s;
    z = (m[0][2] + m[2][0]) / s;
  } else if (m[1][1] > m[2][2]) {
    const s = Math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2.0;
    w = (m[0][2] - m[2][0]) / s;
    x = (m[0][1] + m[1][0]) / s;
    y = 0.25 * s;
    z = (m[1][2] + m[2][1]) / s;
  } else {
    const s = Math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2.0;
    w = (m[1][0] - m[0][1]) / s;
    x = (m[0][2] + m[2][0]) / s;
    y = (m[1][2] + m[2][1]) / s;
    z = 0.25 * s;
  }
  return new Quat(x, y, z, w);
}

/**
 * Converts {@link Vec3}, {@link Quat}, and {@link BoundingBox} values
 * between axis conventions (e.g. Y-up to Z-up).
 *
 * A generic signed-axis-permutation remap. Each of `x`, `y`, `z` names
 * which source axis (optionally signed) the corresponding output axis is
 * derived from. All three source axes must be referenced exactly once
 * (signs aside).
 */
export class AxisRemap {
  private readonly specs: Array<[number, number]>;
  private readonly rotationQuat: Quat | null;

  constructor(x: string, y: string, z: string) {
    const specs: Array<[number, number]> = [parseAxisSpec(x), parseAxisSpec(y), parseAxisSpec(z)];
    const used = specs.map(([idx]) => idx).sort();
    if (used.join(",") !== "0,1,2") {
      throw new Error(`AxisRemap must reference each of x, y, z exactly once (got x=${x}, y=${y}, z=${z})`);
    }
    const matrix: number[][] = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
    specs.forEach(([idx, sign], row) => {
      matrix[row][idx] = sign;
    });
    const det = mat3Det(matrix);
    this.specs = specs;
    this.rotationQuat = det > 0 ? mat3ToQuat(matrix) : null;
  }

  /** Remap a vector or point. Works for any remap, proper or reflective. */
  applyVec3(v: Vec3): Vec3 {
    const comps = [v.x, v.y, v.z];
    const out = this.specs.map(([idx, sign]) => comps[idx] * sign);
    return new Vec3(out[0], out[1], out[2]);
  }

  /**
   * Remap a rotation.
   * @throws {Error} If this remap is a reflection (determinant -1). Use
   * {@link applyVec3} for vectors/points instead.
   */
  applyQuat(q: Quat): Quat {
    if (this.rotationQuat === null) {
      throw new Error(
        "AxisRemap represents a reflection (determinant -1); cannot remap a Quat. Use applyVec3 for vectors/points instead.",
      );
    }
    const r = this.rotationQuat;
    return r.multiply(q).multiply(r.conjugate());
  }

  /** Remap a bounding box. Both corners are remapped and re-sorted per axis. */
  applyBbox(b: BoundingBox): BoundingBox {
    const p1 = this.applyVec3(b.min);
    const p2 = this.applyVec3(b.max);
    const lo = new Vec3(Math.min(p1.x, p2.x), Math.min(p1.y, p2.y), Math.min(p1.z, p2.z));
    const hi = new Vec3(Math.max(p1.x, p2.x), Math.max(p1.y, p2.y), Math.max(p1.z, p2.z));
    return new BoundingBox(lo, hi);
  }
}

/**
 * Converts DAZ Studio's Y-up convention to a Z-up convention (e.g. Blender,
 * glTF-consuming tools converted to Z-up). Up (+Y) becomes +Z; DAZ's
 * forward (+Z) becomes -Y.
 */
export const Y_UP_TO_Z_UP = new AxisRemap("x", "-z", "y");
