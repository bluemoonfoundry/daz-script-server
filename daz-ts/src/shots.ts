/**
 * Typed, serialisable shot models: {@link Shot}, {@link Sequence},
 * {@link CoveragePlan}. Mirrors dazpy's `shots.py`.
 *
 * A {@link Shot} describes one camera setup as a whole: what it frames
 * ({@link Framing}) or where it stands ({@link Placement}), through which
 * {@link Lens}, how it moves ({@link Orbit} / {@link Keyframed}), where focus
 * goes ({@link FocusPull}), and the planning data around it -- blocking and
 * gaze beats, the lighting setup it must match, storyboard notes and its
 * render output. {@link applyShot} puts a shot into a live scene.
 *
 * Every model is immutable with `toDict()` / `fromDict()`. The dict form is
 * **dazpy's wire format** (snake_case keys, `[x, y, z]` vectors, a `kind`
 * discriminator on union fields, default-valued fields omitted), so a plan
 * saved by either SDK loads in the other. Targets are an actor/prop key
 * (`string`, resolved through the `subjects` mapping of {@link applyShot}),
 * a {@link Vec3}, or a live `DazNode` -- the last is not serialisable.
 *
 * Static shots convert to and from scene-recipe camera entries
 * ({@link Shot.toRecipe}, {@link shotFromRecipeCamera},
 * {@link CoveragePlan.toRecipeSections}, {@link CoveragePlan.mergeIntoRecipe}).
 *
 * Units are DAZ native: centimetres, Y-up, degrees, timeline frames.
 */

import { Vec3 } from "./math3.js";
import { lookAtEuler, resolveTarget, sphericalOffset } from "./shotGeometry.js";
import type { DazCamera } from "./camera.js";
import type { DazNode, TransformKeyKind } from "./node.js";
import type { DazScene } from "./scene.js";

/** An actor/prop key, a world point, or a live node. */
export type Target = string | Vec3 | DazNode;
export type Rotation = readonly [number, number, number];

export type ShotSize =
  | "extreme_wide"
  | "wide"
  | "full_body"
  | "medium_wide"
  | "medium"
  | "medium_close_up"
  | "close_up"
  | "extreme_close_up";
export type CameraAngle = "eye_level" | "high" | "low" | "birds_eye" | "worms_eye";
export type Composition = "center" | "left_third" | "right_third";

/**
 * Per shot size: `[cm of subject that fills the frame height, cm above an
 * actor's root to aim at]`. Assumes a standing Genesis-scale (~175 cm)
 * figure. `full_body` / `medium` / `close_up` are the scene-recipe values.
 */
export const SHOT_SIZES: Readonly<Record<ShotSize, readonly [number, number]>> = Object.freeze({
  extreme_wide: [600.0, 90.0],
  wide: [350.0, 90.0],
  full_body: [210.0, 90.0],
  medium_wide: [140.0, 115.0],
  medium: [100.0, 130.0],
  medium_close_up: [60.0, 145.0],
  close_up: [40.0, 160.0],
  extreme_close_up: [15.0, 165.0],
});

/** Camera elevation (degrees above the aim point) per named angle. */
export const CAMERA_ANGLES: Readonly<Record<CameraAngle, number>> = Object.freeze({
  eye_level: 0.0,
  high: 30.0,
  low: -20.0,
  birds_eye: 80.0,
  worms_eye: -45.0,
});

export const COMPOSITIONS: readonly Composition[] = Object.freeze(["center", "left_third", "right_third"]);

/** {@link CameraKeyframe} `interpolation`: the segment to the next waypoint. */
export type KeyInterpolation = "linear" | "constant" | "smooth";
/** {@link Keyframed} `easing`: the whole move. */
export type CameraEasing = "linear" | "smooth" | "ease_in" | "ease_out";
export const KEY_INTERPOLATIONS: readonly KeyInterpolation[] = Object.freeze(["linear", "constant", "smooth"]);
export const CAMERA_EASINGS: readonly CameraEasing[] = Object.freeze(["linear", "smooth", "ease_in", "ease_out"]);

/** `[kinds, fastStart, fastEnd]` for `DazNode.setTransformKeyInterpolation`. */
export type KeyInterpolationPlan = [kinds: (TransformKeyKind | null)[], fastStart: boolean, fastEnd: boolean];

const EASING_KIND: Record<CameraEasing, TransformKeyKind> = {
  linear: "linear",
  smooth: "smooth",
  ease_in: "hermite",
  ease_out: "hermite",
};

/**
 * The interpolation plan for a keyframed move: one kind per waypoint (its own
 * `interpolation`, else the move's `easing`), or `null` when nothing asks for
 * one. Shared by {@link Keyframed.keyInterpolation} and `applyAnimatedShot`.
 */
export function keyInterpolationPlan(
  interpolations: readonly (KeyInterpolation | null | undefined)[],
  easing: CameraEasing | null | undefined,
): KeyInterpolationPlan | null {
  const base = easing ? EASING_KIND[easing] : null;
  const kinds = interpolations.map((k) => k ?? base);
  if (kinds.every((k) => k === null)) return null;
  return [kinds, easing === "ease_out", easing === "ease_in"];
}

/** Daz camera "Frame Width" default (mm). */
export const DEFAULT_FRAME_WIDTH_MM = 36.0;
/** Frame height/width used when nothing sets a resolution -- the scene-recipe default. */
export const DEFAULT_ASPECT = 3 / 4;

// ---- serialisation helpers ----------------------------------------------

type Dict = Record<string, unknown>;

function isDict(v: unknown): v is Dict {
  return typeof v === "object" && v !== null && !Array.isArray(v) && !(v instanceof Vec3);
}

/** A live node (anything with a `position()` method); its position is never read here. */
export function isNodeTarget(v: unknown): v is DazNode {
  return isDict(v) && typeof (v as { position?: unknown }).position === "function";
}

function repr(v: unknown): string {
  return typeof v === "string" ? `'${v}'` : JSON.stringify(v);
}

function encTarget(v: Target, path: string): string | number[] {
  if (typeof v === "string") return v;
  if (v instanceof Vec3) return [v.x, v.y, v.z];
  throw new TypeError(`${path}: a DazNode target can't be serialised; use an actor/prop key or [x, y, z]`);
}

function decVec(v: unknown, path: string): Vec3 {
  if (v instanceof Vec3) return v;
  if (Array.isArray(v) && v.length === 3 && v.every((x) => typeof x === "number")) {
    return new Vec3(v[0], v[1], v[2]);
  }
  throw new Error(`${path}: must be [x, y, z]`);
}

function decTarget(v: unknown, path: string): Target {
  if (typeof v === "string") {
    if (!v) throw new Error(`${path}: an entity key must be non-empty`);
    return v;
  }
  if (isNodeTarget(v)) return v;
  return decVec(v, path);
}

function decFloats(v: unknown, n: number, path: string): number[] {
  if (!(Array.isArray(v) && v.length === n && v.every((x) => typeof x === "number"))) {
    throw new Error(`${path}: must be an array of ${n} numbers`);
  }
  return v as number[];
}

/** `decFloats(v, 2)` typed as a pair. */
function decNumberPair(v: unknown, path: string): readonly [number, number] {
  const [a, b] = decFloats(v, 2, path);
  return [a, b];
}

/** `decFloats(v, 3)` typed as a {@link Rotation}. */
function decRotation(v: unknown, path: string): Rotation {
  const [x, y, z] = decFloats(v, 3, path);
  return [x, y, z];
}

/** A frozen copy of a {@link Rotation}. */
function frozenRotation(rotation: Rotation): Rotation {
  const copy: [number, number, number] = [rotation[0], rotation[1], rotation[2]];
  return Object.freeze(copy);
}

/** A frozen copy of a two-element tuple that keeps its tuple type. */
function frozenPair<T>(pair: readonly [T, T]): readonly [T, T] {
  const copy: [T, T] = [pair[0], pair[1]];
  return Object.freeze(copy);
}

function decArray(v: unknown, path: string): unknown[] {
  if (!Array.isArray(v)) throw new Error(`${path}: must be an array`);
  return v;
}

function join(path: string, key: string): string {
  return path ? `${path}.${key}` : key;
}

/** Check `data` is an object holding only `allowed` keys (plus a matching `kind`). */
function fields(data: unknown, path: string, name: string, allowed: readonly string[], kind?: string): Dict {
  if (!isDict(data)) throw new Error(`${path || name}: must be an object`);
  for (const [k, v] of Object.entries(data)) {
    const p = join(path, k);
    if (k === "kind" && kind) {
      if (v !== kind) throw new Error(`${p}: expected '${kind}', got ${repr(v)}`);
      continue;
    }
    if (!allowed.includes(k)) throw new Error(`${p}: unknown field (allowed: ${[...allowed].sort().join(", ")})`);
  }
  return data;
}

function required(d: Dict, key: string, path: string, name: string): unknown {
  if (d[key] === undefined) throw new Error(`${path || name}: missing required field '${key}'`);
  return d[key];
}

/** Run a constructor, prefixing its validation error with `path`. */
function construct<T>(path: string, make: () => T): T {
  try {
    return make();
  } catch (e) {
    if (path && e instanceof Error && !(e instanceof TypeError)) throw new Error(`${path}: ${e.message}`);
    throw e;
  }
}

function opt<T>(v: unknown, conv: (v: unknown) => T): T | null {
  return v === undefined || v === null ? null : conv(v);
}

function checkEnum(value: unknown, allowed: readonly string[], path: string): void {
  if (typeof value !== "string" || !allowed.includes(value)) {
    throw new Error(`${path}: ${repr(value)} is not one of [${allowed.map((a) => `'${a}'`).join(", ")}]`);
  }
}

function requireFrames(frames: number[], what: string, minimum = 2): void {
  if (frames.length < minimum) throw new Error(`${what} needs at least ${minimum} entries`);
  if (!ascendingUnique(frames)) throw new Error(`${what} must have strictly ascending, unique frame numbers`);
}

function ascendingUnique(frames: number[]): boolean {
  return frames.every((f, i) => i === 0 || f > frames[i - 1]);
}

/** Set `out[key]` unless `value` equals `dflt` (dazpy omits default-valued fields). */
function put(out: Dict, key: string, value: unknown, dflt: unknown = null): void {
  if (value === dflt) return;
  if (Array.isArray(value) && Array.isArray(dflt) && value.length === 0 && dflt.length === 0) return;
  out[key] = value;
}

// ---- camera parts --------------------------------------------------------

export interface LensInit {
  focalLength?: number;
  depthOfField?: boolean | null;
  focalDistance?: number | null;
  fStop?: number | null;
}

/** Camera optics. `null` fields leave Studio's current value untouched. */
export class Lens {
  readonly focalLength: number;
  readonly depthOfField: boolean | null;
  readonly focalDistance: number | null;
  readonly fStop: number | null;

  constructor(init: LensInit = {}) {
    this.focalLength = init.focalLength ?? 50.0;
    this.depthOfField = init.depthOfField ?? null;
    this.focalDistance = init.focalDistance ?? null;
    this.fStop = init.fStop ?? null;
    if (!(this.focalLength > 0)) throw new Error("focal_length must be > 0");
    Object.freeze(this);
  }

  with(patch: LensInit): Lens {
    return new Lens({ ...this, ...patch });
  }

  toDict(): Dict {
    const out: Dict = {};
    put(out, "focal_length", this.focalLength, 50.0);
    put(out, "depth_of_field", this.depthOfField);
    put(out, "focal_distance", this.focalDistance);
    put(out, "f_stop", this.fStop);
    return out;
  }

  static fromDict(data: unknown, path = ""): Lens {
    const d = fields(data, path, "Lens", ["focal_length", "depth_of_field", "focal_distance", "f_stop"]);
    return construct(path, () =>
      new Lens({
        focalLength: d.focal_length as number | undefined,
        depthOfField: d.depth_of_field as boolean | null | undefined,
        focalDistance: d.focal_distance as number | null | undefined,
        fStop: d.f_stop as number | null | undefined,
      }),
    );
  }
}

export interface FramingInit {
  subjects: Target | readonly Target[];
  size?: ShotSize;
  angle?: CameraAngle;
  azimuthDeg?: number;
  elevationDeg?: number | null;
  composition?: Composition;
  distanceCm?: number | null;
  anchorCm?: number | null;
}

/**
 * Frame one or more subjects at a named shot size.
 *
 * - `subjects`: one or more targets; the camera aims at their centroid. Keys
 *   and `DazNode` targets are raised by the size's anchor height (they are
 *   assumed to be standing figures); `Vec3` targets only by `anchorCm`.
 * - `azimuthDeg`: camera azimuth around the aim point (0 = the subject's
 *   `+Z` side; see `sphericalOffset`).
 * - `elevationDeg`: explicit elevation; overrides `angle` when set.
 * - `composition`: `"left_third"` / `"right_third"` places the subject on
 *   that third by turning the camera, not moving it.
 * - `distanceCm`: explicit camera distance; overrides the size's fit.
 * - `anchorCm`: explicit aim height above every subject; overrides the
 *   size's anchor (and applies to `Vec3` subjects too).
 */
export class Framing {
  readonly kind = "framing" as const;
  readonly subjects: readonly Target[];
  readonly size: ShotSize;
  readonly angle: CameraAngle;
  readonly azimuthDeg: number;
  readonly elevationDeg: number | null;
  readonly composition: Composition;
  readonly distanceCm: number | null;
  readonly anchorCm: number | null;

  constructor(init: FramingInit) {
    const s = init.subjects;
    this.subjects = Object.freeze(typeof s === "string" || s instanceof Vec3 || isNodeTarget(s) ? [s] : [...(s as readonly Target[])]);
    this.size = init.size ?? "medium";
    this.angle = init.angle ?? "eye_level";
    this.azimuthDeg = init.azimuthDeg ?? 0.0;
    this.elevationDeg = init.elevationDeg ?? null;
    this.composition = init.composition ?? "center";
    this.distanceCm = init.distanceCm ?? null;
    this.anchorCm = init.anchorCm ?? null;
    if (this.subjects.length === 0) throw new Error("subjects needs at least one target");
    checkEnum(this.size, Object.keys(SHOT_SIZES), "size");
    checkEnum(this.angle, Object.keys(CAMERA_ANGLES), "angle");
    checkEnum(this.composition, COMPOSITIONS, "composition");
    if (this.distanceCm !== null && this.distanceCm <= 0) throw new Error("distance_cm must be > 0");
    Object.freeze(this);
  }

  get effectiveElevationDeg(): number {
    return this.elevationDeg ?? CAMERA_ANGLES[this.angle];
  }

  with(patch: Partial<FramingInit>): Framing {
    return new Framing({ ...this, ...patch });
  }

  toDict(path = ""): Dict {
    const out: Dict = { kind: this.kind };
    out.subjects = this.subjects.map((s, i) => encTarget(s, `${join(path, "subjects")}[${i}]`));
    put(out, "size", this.size, "medium");
    put(out, "angle", this.angle, "eye_level");
    put(out, "azimuth_deg", this.azimuthDeg, 0.0);
    put(out, "elevation_deg", this.elevationDeg);
    put(out, "composition", this.composition, "center");
    put(out, "distance_cm", this.distanceCm);
    put(out, "anchor_cm", this.anchorCm);
    return out;
  }

  static fromDict(data: unknown, path = ""): Framing {
    const d = fields(data, path, "Framing", ["subjects", "size", "angle", "azimuth_deg", "elevation_deg", "composition", "distance_cm", "anchor_cm"], "framing");
    const raw = required(d, "subjects", path, "Framing");
    const sp = join(path, "subjects");
    const subjects = Array.isArray(raw) ? raw.map((x, i) => decTarget(x, `${sp}[${i}]`)) : [decTarget(raw, sp)];
    return construct(path, () =>
      new Framing({
        subjects,
        size: d.size as ShotSize | undefined,
        angle: d.angle as CameraAngle | undefined,
        azimuthDeg: d.azimuth_deg as number | undefined,
        elevationDeg: d.elevation_deg as number | null | undefined,
        composition: d.composition as Composition | undefined,
        distanceCm: d.distance_cm as number | null | undefined,
        anchorCm: d.anchor_cm as number | null | undefined,
      }),
    );
  }
}

export interface PlacementInit {
  position: Vec3;
  lookAt?: Target | null;
  lookAtOffsetCm?: number;
  rotation?: Rotation | null;
}

/** An explicit camera position, aimed at `lookAt` or turned to `rotation`. */
export class Placement {
  readonly kind = "placement" as const;
  readonly position: Vec3;
  readonly lookAt: Target | null;
  readonly lookAtOffsetCm: number;
  readonly rotation: Rotation | null;

  constructor(init: PlacementInit) {
    this.position = init.position;
    this.lookAt = init.lookAt ?? null;
    this.lookAtOffsetCm = init.lookAtOffsetCm ?? 0.0;
    this.rotation = init.rotation ? frozenRotation(init.rotation) : null;
    Object.freeze(this);
  }

  toDict(path = ""): Dict {
    const out: Dict = { kind: this.kind, position: this.position.toList() };
    if (this.lookAt !== null) out.look_at = encTarget(this.lookAt, join(path, "look_at"));
    put(out, "look_at_offset_cm", this.lookAtOffsetCm, 0.0);
    if (this.rotation !== null) out.rotation = [...this.rotation];
    return out;
  }

  static fromDict(data: unknown, path = ""): Placement {
    const d = fields(data, path, "Placement", ["position", "look_at", "look_at_offset_cm", "rotation"], "placement");
    const position = decVec(required(d, "position", path, "Placement"), join(path, "position"));
    const lookAt = opt(d.look_at, (v) => decTarget(v, join(path, "look_at")));
    const rotation = opt(d.rotation, (v) => decRotation(v, join(path, "rotation")));
    return construct(path, () => new Placement({ position, lookAt, lookAtOffsetCm: d.look_at_offset_cm as number | undefined, rotation }));
  }
}

export interface CameraKeyframeInit {
  frame: number;
  position: Vec3;
  lookAt?: Target | null;
  lookAtOffsetCm?: number;
  rotation?: Rotation | null;
  /**
   * How Studio moves from this waypoint to the next: `"linear"`, `"constant"`
   * (hold, then cut) or `"smooth"` (Studio's default curve). Overrides the
   * move's {@link Keyframed} `easing` for this segment; `null` follows it.
   * Ignored on the last waypoint.
   */
  interpolation?: KeyInterpolation | null;
}

/**
 * A single waypoint in an animated camera move (see {@link Keyframed}).
 * `lookAt` wins over `rotation` when both are set.
 */
export class CameraKeyframe {
  readonly frame: number;
  readonly position: Vec3;
  readonly lookAt: Target | null;
  readonly lookAtOffsetCm: number;
  readonly rotation: Rotation | null;
  readonly interpolation: KeyInterpolation | null;

  constructor(init: CameraKeyframeInit) {
    this.frame = init.frame;
    this.position = init.position;
    this.lookAt = init.lookAt ?? null;
    this.lookAtOffsetCm = init.lookAtOffsetCm ?? 0.0;
    this.rotation = init.rotation ? frozenRotation(init.rotation) : null;
    this.interpolation = init.interpolation ?? null;
    if (this.interpolation !== null) checkEnum(this.interpolation, KEY_INTERPOLATIONS, "interpolation");
    Object.freeze(this);
  }

  toDict(path = ""): Dict {
    const out: Dict = { frame: this.frame, position: this.position.toList() };
    if (this.lookAt !== null) out.look_at = encTarget(this.lookAt, join(path, "look_at"));
    put(out, "look_at_offset_cm", this.lookAtOffsetCm, 0.0);
    if (this.rotation !== null) out.rotation = [...this.rotation];
    put(out, "interpolation", this.interpolation);
    return out;
  }

  static fromDict(data: unknown, path = ""): CameraKeyframe {
    const d = fields(data, path, "CameraKeyframe", ["frame", "position", "look_at", "look_at_offset_cm", "rotation", "interpolation"]);
    const frame = required(d, "frame", path, "CameraKeyframe") as number;
    const position = decVec(required(d, "position", path, "CameraKeyframe"), join(path, "position"));
    const lookAt = opt(d.look_at, (v) => decTarget(v, join(path, "look_at")));
    const rotation = opt(d.rotation, (v) => decRotation(v, join(path, "rotation")));
    return construct(path, () =>
      new CameraKeyframe({
        frame,
        position,
        lookAt,
        lookAtOffsetCm: d.look_at_offset_cm as number | undefined,
        rotation,
        interpolation: d.interpolation as KeyInterpolation | null | undefined,
      }),
    );
  }
}

export interface OrbitInit {
  radius: number;
  elevationDeg?: number;
  startAzimuthDeg?: number;
  endAzimuthDeg?: number;
  frameStart?: number;
  frameEnd?: number;
  targetOffsetCm?: number;
}

/**
 * Movement: sweep around the shot's subject, baking one placement per frame.
 * The orbit target is a {@link Framing}'s first subject, or a
 * {@link Placement}'s `lookAt`. {@link applyShot} widens the anim range and
 * leaves the timeline at `frameEnd`.
 */
export class Orbit {
  readonly kind = "orbit" as const;
  readonly radius: number;
  readonly elevationDeg: number;
  readonly startAzimuthDeg: number;
  readonly endAzimuthDeg: number;
  readonly frameStart: number;
  readonly frameEnd: number;
  readonly targetOffsetCm: number;

  constructor(init: OrbitInit) {
    this.radius = init.radius;
    this.elevationDeg = init.elevationDeg ?? 15.0;
    this.startAzimuthDeg = init.startAzimuthDeg ?? 0.0;
    this.endAzimuthDeg = init.endAzimuthDeg ?? 360.0;
    this.frameStart = init.frameStart ?? 0;
    this.frameEnd = init.frameEnd ?? 90;
    this.targetOffsetCm = init.targetOffsetCm ?? 25.0;
    if (this.frameEnd < this.frameStart) {
      throw new Error(`OrbitCamera.frame_end (${this.frameEnd}) must be >= frame_start (${this.frameStart})`);
    }
    Object.freeze(this);
  }

  toDict(): Dict {
    const out: Dict = { kind: this.kind, radius: this.radius };
    put(out, "elevation_deg", this.elevationDeg, 15.0);
    put(out, "start_azimuth_deg", this.startAzimuthDeg, 0.0);
    put(out, "end_azimuth_deg", this.endAzimuthDeg, 360.0);
    put(out, "frame_start", this.frameStart, 0);
    put(out, "frame_end", this.frameEnd, 90);
    put(out, "target_offset_cm", this.targetOffsetCm, 25.0);
    return out;
  }

  static fromDict(data: unknown, path = ""): Orbit {
    const d = fields(data, path, "Orbit", ["radius", "elevation_deg", "start_azimuth_deg", "end_azimuth_deg", "frame_start", "frame_end", "target_offset_cm"], "orbit");
    const radius = required(d, "radius", path, "Orbit") as number;
    return construct(path, () =>
      new Orbit({
        radius,
        elevationDeg: d.elevation_deg as number | undefined,
        startAzimuthDeg: d.start_azimuth_deg as number | undefined,
        endAzimuthDeg: d.end_azimuth_deg as number | undefined,
        frameStart: d.frame_start as number | undefined,
        frameEnd: d.frame_end as number | undefined,
        targetOffsetCm: d.target_offset_cm as number | undefined,
      }),
    );
  }
}

/**
 * Movement: real Daz keyframes, one per waypoint; Studio interpolates between.
 * Waypoints must be strictly ascending (at least two), and either every
 * waypoint specifies an orientation (`lookAt`/`rotation`) or none does.
 *
 * `easing` shapes the whole move, on position and rotation:
 *
 * - `null`: leave Studio's interpolation as it is (new keys are smooth).
 * - `"linear"`: constant speed along each segment, sharp turns at waypoints.
 * - `"smooth"`: Studio's default curve: starts and stops gently, passes
 *   through interior waypoints without a speed jump.
 * - `"ease_in"`: starts gently, arrives at speed (a two-waypoint move is `t^2`).
 * - `"ease_out"`: leaves at speed, stops gently (`2t - t^2`).
 *
 * A waypoint's own {@link CameraKeyframe} `interpolation` overrides `easing`
 * for the segment after it. See `DazNode.setTransformKeyInterpolation` for the
 * curves.
 */
export class Keyframed {
  readonly kind = "keyframed" as const;
  readonly keyframes: readonly CameraKeyframe[];
  readonly easing: CameraEasing | null;

  constructor(init: { keyframes: readonly CameraKeyframe[]; easing?: CameraEasing | null }) {
    this.easing = init.easing ?? null;
    if (this.easing !== null) checkEnum(this.easing, CAMERA_EASINGS, "easing");
    this.keyframes = Object.freeze([...init.keyframes]);
    if (this.keyframes.length < 2) throw new Error("CinematicAnimatedShot.keyframes needs at least two waypoints");
    if (!ascendingUnique(this.keyframes.map((k) => k.frame))) {
      throw new Error("CinematicAnimatedShot.keyframes must have strictly ascending, unique frame numbers");
    }
    const oriented = this.keyframes.map((k) => k.lookAt !== null || k.rotation !== null);
    if (oriented.some(Boolean) && !oriented.every(Boolean)) {
      throw new Error(
        "CinematicAnimatedShot.keyframes must either all specify an orientation (look_at/rotation) or none of them should",
      );
    }
    Object.freeze(this);
  }

  get hasOrientation(): boolean {
    return this.keyframes[0].lookAt !== null || this.keyframes[0].rotation !== null;
  }

  /** `[kinds, fastStart, fastEnd]` for `DazNode.setTransformKeyInterpolation`, or `null` when nothing asks for one. */
  keyInterpolation(): KeyInterpolationPlan | null {
    return keyInterpolationPlan(this.keyframes.map((k) => k.interpolation), this.easing);
  }

  toDict(path = ""): Dict {
    const kp = join(path, "keyframes");
    const out: Dict = { kind: this.kind, keyframes: this.keyframes.map((k, i) => k.toDict(`${kp}[${i}]`)) };
    put(out, "easing", this.easing);
    return out;
  }

  static fromDict(data: unknown, path = ""): Keyframed {
    const d = fields(data, path, "Keyframed", ["keyframes", "easing"], "keyframed");
    const kp = join(path, "keyframes");
    const keyframes = decArray(required(d, "keyframes", path, "Keyframed"), kp).map((k, i) => CameraKeyframe.fromDict(k, `${kp}[${i}]`));
    return construct(path, () => new Keyframed({ keyframes, easing: d.easing as CameraEasing | null | undefined }));
  }
}

/** One focal-distance key of a {@link FocusPull}. */
export class FocusKey {
  readonly frame: number;
  readonly focalDistance: number;

  constructor(frame: number, focalDistance: number) {
    this.frame = frame;
    this.focalDistance = focalDistance;
    if (!(focalDistance > 0)) throw new Error("focal_distance must be > 0");
    Object.freeze(this);
  }

  toDict(): Dict {
    return { frame: this.frame, focal_distance: this.focalDistance };
  }

  static fromDict(data: unknown, path = ""): FocusKey {
    const d = fields(data, path, "FocusKey", ["frame", "focal_distance"]);
    const frame = required(d, "frame", path, "FocusKey") as number;
    const fd = required(d, "focal_distance", path, "FocusKey") as number;
    return construct(path, () => new FocusKey(frame, fd));
  }
}

/** Keyed focal distance (a rack focus): at least two strictly ascending keys. */
export class FocusPull {
  readonly keys: readonly FocusKey[];

  constructor(init: { keys: readonly FocusKey[] }) {
    this.keys = Object.freeze([...init.keys]);
    requireFrames(this.keys.map((k) => k.frame), "FocusPull.keys");
    Object.freeze(this);
  }

  toDict(): Dict {
    return { keys: this.keys.map((k) => k.toDict()) };
  }

  static fromDict(data: unknown, path = ""): FocusPull {
    const d = fields(data, path, "FocusPull", ["keys"]);
    const kp = join(path, "keys");
    const keys = decArray(required(d, "keys", path, "FocusPull"), kp).map((k, i) => FocusKey.fromDict(k, `${kp}[${i}]`));
    return construct(path, () => new FocusPull({ keys }));
  }
}

// ---- planning data (carried, not applied) --------------------------------

/** From `frame`, `actor` looks at `lookAt`. Planning data; not applied yet. */
export class GazeBeat {
  readonly frame: number;
  readonly actor: string;
  readonly lookAt: Target;

  constructor(frame: number, actor: string, lookAt: Target) {
    this.frame = frame;
    this.actor = actor;
    this.lookAt = lookAt;
    Object.freeze(this);
  }

  toDict(path = ""): Dict {
    return { frame: this.frame, actor: this.actor, look_at: encTarget(this.lookAt, join(path, "look_at")) };
  }

  static fromDict(data: unknown, path = ""): GazeBeat {
    const d = fields(data, path, "GazeBeat", ["frame", "actor", "look_at"]);
    const frame = required(d, "frame", path, "GazeBeat") as number;
    const actor = required(d, "actor", path, "GazeBeat") as string;
    const lookAt = decTarget(required(d, "look_at", path, "GazeBeat"), join(path, "look_at"));
    return new GazeBeat(frame, actor, lookAt);
  }
}

/** At `frame`, `actor` stands at `position` (facing `facing`). Planning data; not applied yet. */
export class BlockingBeat {
  readonly frame: number;
  readonly actor: string;
  readonly position: Vec3;
  readonly facing: Target | null;
  readonly note: string | null;

  constructor(init: { frame: number; actor: string; position: Vec3; facing?: Target | null; note?: string | null }) {
    this.frame = init.frame;
    this.actor = init.actor;
    this.position = init.position;
    this.facing = init.facing ?? null;
    this.note = init.note ?? null;
    Object.freeze(this);
  }

  toDict(path = ""): Dict {
    const out: Dict = { frame: this.frame, actor: this.actor, position: this.position.toList() };
    if (this.facing !== null) out.facing = encTarget(this.facing, join(path, "facing"));
    put(out, "note", this.note);
    return out;
  }

  static fromDict(data: unknown, path = ""): BlockingBeat {
    const d = fields(data, path, "BlockingBeat", ["frame", "actor", "position", "facing", "note"]);
    return new BlockingBeat({
      frame: required(d, "frame", path, "BlockingBeat") as number,
      actor: required(d, "actor", path, "BlockingBeat") as string,
      position: decVec(required(d, "position", path, "BlockingBeat"), join(path, "position")),
      facing: opt(d.facing, (v) => decTarget(v, join(path, "facing"))),
      note: (d.note as string | null | undefined) ?? null,
    });
  }
}

export interface StoryboardInit {
  description?: string | null;
  dialogue?: string | null;
  beat?: string | null;
  notes?: string | null;
}

/** Free-text storyboard metadata. */
export class Storyboard {
  readonly description: string | null;
  readonly dialogue: string | null;
  readonly beat: string | null;
  readonly notes: string | null;

  constructor(init: StoryboardInit = {}) {
    this.description = init.description ?? null;
    this.dialogue = init.dialogue ?? null;
    this.beat = init.beat ?? null;
    this.notes = init.notes ?? null;
    Object.freeze(this);
  }

  toDict(): Dict {
    const out: Dict = {};
    put(out, "description", this.description);
    put(out, "dialogue", this.dialogue);
    put(out, "beat", this.beat);
    put(out, "notes", this.notes);
    return out;
  }

  static fromDict(data: unknown, path = ""): Storyboard {
    const d = fields(data, path, "Storyboard", ["description", "dialogue", "beat", "notes"]);
    return new Storyboard(d as StoryboardInit);
  }
}

export type RenderEngine = "iray" | "filament" | "viewport";

/** Where a shot renders, and per-shot render overrides. */
export class RenderOutput {
  readonly path: string;
  readonly engine: RenderEngine | null;
  readonly resolution: readonly [number, number] | null;
  readonly iraySamples: number | null;

  constructor(init: { path: string; engine?: RenderEngine | null; resolution?: readonly [number, number] | null; iraySamples?: number | null }) {
    this.path = init.path;
    this.engine = init.engine ?? null;
    this.resolution = init.resolution ? frozenPair([Math.trunc(init.resolution[0]), Math.trunc(init.resolution[1])]) : null;
    this.iraySamples = init.iraySamples ?? null;
    if (!this.path) throw new Error("path must be non-empty");
    if (this.engine !== null) checkEnum(this.engine, ["iray", "filament", "viewport"], "engine");
    Object.freeze(this);
  }

  toDict(): Dict {
    const out: Dict = { path: this.path };
    put(out, "engine", this.engine);
    if (this.resolution !== null) out.resolution = [...this.resolution];
    put(out, "iray_samples", this.iraySamples);
    return out;
  }

  static fromDict(data: unknown, path = ""): RenderOutput {
    const d = fields(data, path, "RenderOutput", ["path", "engine", "resolution", "iray_samples"]);
    const p = required(d, "path", path, "RenderOutput") as string;
    const resolution = opt(d.resolution, (v) => decNumberPair(v, join(path, "resolution")));
    return construct(path, () =>
      new RenderOutput({ path: p, engine: d.engine as RenderEngine | null | undefined, resolution, iraySamples: d.iray_samples as number | null | undefined }),
    );
  }
}

export interface AspectSettingsInit {
  aspectWidth?: number | null;
  aspectHeight?: number | null;
  pixelsWidth?: number | null;
  pixelsHeight?: number | null;
}

/** Camera aspect/pixel settings; `null` leaves Studio's value untouched. */
export class AspectSettings {
  readonly aspectWidth: number | null;
  readonly aspectHeight: number | null;
  readonly pixelsWidth: number | null;
  readonly pixelsHeight: number | null;

  constructor(init: AspectSettingsInit = {}) {
    this.aspectWidth = init.aspectWidth ?? null;
    this.aspectHeight = init.aspectHeight ?? null;
    this.pixelsWidth = init.pixelsWidth ?? null;
    this.pixelsHeight = init.pixelsHeight ?? null;
    Object.freeze(this);
  }

  toDict(): Dict {
    const out: Dict = {};
    put(out, "aspect_width", this.aspectWidth);
    put(out, "aspect_height", this.aspectHeight);
    put(out, "pixels_width", this.pixelsWidth);
    put(out, "pixels_height", this.pixelsHeight);
    return out;
  }

  static fromDict(data: unknown, path = ""): AspectSettings {
    const d = fields(data, path, "AspectSettings", ["aspect_width", "aspect_height", "pixels_width", "pixels_height"]);
    return new AspectSettings({
      aspectWidth: d.aspect_width as number | null | undefined,
      aspectHeight: d.aspect_height as number | null | undefined,
      pixelsWidth: d.pixels_width as number | null | undefined,
      pixelsHeight: d.pixels_height as number | null | undefined,
    });
  }
}

// ---- Shot / Sequence / CoveragePlan --------------------------------------

export type ShotCamera = Framing | Placement;
export type ShotMovement = Orbit | Keyframed;

function decCamera(v: unknown, path: string): ShotCamera {
  if (v instanceof Framing || v instanceof Placement) return v;
  if (!isDict(v) || (v.kind !== "framing" && v.kind !== "placement")) {
    throw new Error(`${path}: needs 'kind' of ['framing', 'placement']`);
  }
  return v.kind === "framing" ? Framing.fromDict(v, path) : Placement.fromDict(v, path);
}

function decMovement(v: unknown, path: string): ShotMovement {
  if (v instanceof Orbit || v instanceof Keyframed) return v;
  if (!isDict(v) || (v.kind !== "orbit" && v.kind !== "keyframed")) {
    throw new Error(`${path}: needs 'kind' of ['keyframed', 'orbit']`);
  }
  return v.kind === "orbit" ? Orbit.fromDict(v, path) : Keyframed.fromDict(v, path);
}

/** A scene-recipe `cameras[id]` entry. */
export type RecipeCamera = Record<string, unknown>;
/** A scene-recipe `shots[]` entry. */
export type RecipeShot = { id: string; camera: string; output: string; render?: Record<string, unknown> };

export interface ShotInit {
  id: string;
  camera: ShotCamera;
  lens?: Lens;
  movement?: ShotMovement | null;
  focus?: FocusPull | null;
  frameRange?: readonly [number, number] | null;
  aspect?: AspectSettings | null;
  blocking?: readonly BlockingBeat[];
  gaze?: readonly GazeBeat[];
  lighting?: string | null;
  storyboard?: Storyboard | null;
  output?: RenderOutput | null;
}

/**
 * One camera setup and everything planned around it.
 *
 * - `id`: stable shot id (also the recipe camera/shot key on conversion).
 * - `camera`: {@link Framing} (auto-framed) or {@link Placement} (explicit).
 * - `movement`: `null` (static), {@link Orbit} or {@link Keyframed}.
 * - `frameRange`: optional `[start, end]` the shot covers on the timeline.
 * - `blocking`, `gaze`, `lighting` (continuity key), `storyboard`: planning
 *   data, carried but not applied.
 * - `output`: where the shot renders.
 */
export class Shot {
  readonly id: string;
  readonly camera: ShotCamera;
  readonly lens: Lens;
  readonly movement: ShotMovement | null;
  readonly focus: FocusPull | null;
  readonly frameRange: readonly [number, number] | null;
  readonly aspect: AspectSettings | null;
  readonly blocking: readonly BlockingBeat[];
  readonly gaze: readonly GazeBeat[];
  readonly lighting: string | null;
  readonly storyboard: Storyboard | null;
  readonly output: RenderOutput | null;

  constructor(init: ShotInit) {
    this.id = init.id;
    this.camera = init.camera;
    this.lens = init.lens ?? new Lens();
    this.movement = init.movement ?? null;
    this.focus = init.focus ?? null;
    this.frameRange = init.frameRange ? frozenPair(init.frameRange) : null;
    this.aspect = init.aspect ?? null;
    this.blocking = Object.freeze([...(init.blocking ?? [])]);
    this.gaze = Object.freeze([...(init.gaze ?? [])]);
    this.lighting = init.lighting ?? null;
    this.storyboard = init.storyboard ?? null;
    this.output = init.output ?? null;
    if (!this.id) throw new Error("id must be non-empty");
    if (!(this.camera instanceof Framing || this.camera instanceof Placement)) {
      throw new Error("camera must be a Framing or a Placement");
    }
    if (this.frameRange !== null && this.frameRange[1] < this.frameRange[0]) {
      throw new Error("frame_range end must be >= start");
    }
    if (this.movement instanceof Keyframed && this.camera instanceof Framing) {
      throw new Error("a Keyframed move carries its own positions; use a Placement camera (its first waypoint) instead of a Framing");
    }
    Object.freeze(this);
  }

  get isStatic(): boolean {
    return this.movement === null && this.focus === null;
  }

  /** A copy with `patch` applied (dazpy's `dataclasses.replace`). */
  with(patch: Partial<ShotInit>): Shot {
    return new Shot({ ...this, ...patch });
  }

  /**
   * JSON-compatible dict in dazpy's wire format; default-valued fields are omitted.
   * @throws TypeError If a target is a live `DazNode`.
   */
  toDict(): Dict {
    const out: Dict = { id: this.id, camera: this.camera.toDict("camera") };
    const lens = this.lens.toDict();
    if (Object.keys(lens).length) out.lens = lens;
    if (this.movement !== null) out.movement = this.movement instanceof Keyframed ? this.movement.toDict("movement") : this.movement.toDict();
    if (this.focus !== null) out.focus = this.focus.toDict();
    if (this.frameRange !== null) out.frame_range = [...this.frameRange];
    if (this.aspect !== null) out.aspect = this.aspect.toDict();
    if (this.blocking.length) out.blocking = this.blocking.map((b, i) => b.toDict(`blocking[${i}]`));
    if (this.gaze.length) out.gaze = this.gaze.map((g, i) => g.toDict(`gaze[${i}]`));
    put(out, "lighting", this.lighting);
    if (this.storyboard !== null) out.storyboard = this.storyboard.toDict();
    if (this.output !== null) out.output = this.output.toDict();
    return out;
  }

  /**
   * Build from a `toDict()`-shaped object.
   * @throws Error Unknown field, bad enum, wrong `kind` or invalid value; the
   * message starts with the dotted path.
   */
  static fromDict(data: unknown, path = ""): Shot {
    const d = fields(data, path, "Shot", ["id", "camera", "lens", "movement", "focus", "frame_range", "aspect", "blocking", "gaze", "lighting", "storyboard", "output"]);
    const p = (k: string) => join(path, k);
    const id = required(d, "id", path, "Shot") as string;
    const camera = decCamera(required(d, "camera", path, "Shot"), p("camera"));
    const lens = d.lens === undefined ? undefined : Lens.fromDict(d.lens, p("lens"));
    const movement = opt(d.movement, (v) => decMovement(v, p("movement")));
    const focus = opt(d.focus, (v) => FocusPull.fromDict(v, p("focus")));
    const frameRange = opt(d.frame_range, (v) => {
      const [start, end] = decNumberPair(v, p("frame_range"));
      return [Math.trunc(start), Math.trunc(end)] as const;
    });
    const aspect = opt(d.aspect, (v) => AspectSettings.fromDict(v, p("aspect")));
    const blocking = d.blocking === undefined ? [] : decArray(d.blocking, p("blocking")).map((b, i) => BlockingBeat.fromDict(b, `${p("blocking")}[${i}]`));
    const gaze = d.gaze === undefined ? [] : decArray(d.gaze, p("gaze")).map((g, i) => GazeBeat.fromDict(g, `${p("gaze")}[${i}]`));
    const storyboard = opt(d.storyboard, (v) => Storyboard.fromDict(v, p("storyboard")));
    const output = opt(d.output, (v) => RenderOutput.fromDict(v, p("output")));
    return construct(path, () =>
      new Shot({ id, camera, lens, movement, focus, frameRange, aspect, blocking, gaze, lighting: d.lighting as string | null | undefined, storyboard, output }),
    );
  }

  /**
   * Scene-recipe `[cameras[id] entry, shots[] entry or null]`.
   *
   * Only static shots convert (`shots[].movement` is reserved in
   * recipe_version 1). Framing subjects must be keys; explicit
   * positions/aims must be keys or `Vec3` literals. Planning data and aspect
   * settings are not carried.
   *
   * @throws Error The shot moves, pulls focus, frames a `Vec3`, or uses a
   * field recipes can't express.
   * @throws TypeError A target is a live `DazNode`.
   */
  toRecipe(): [RecipeCamera, RecipeShot | null] {
    if (this.movement !== null) throw new Error(`shot '${this.id}': camera movement is not supported in recipe_version 1`);
    if (this.focus !== null) throw new Error(`shot '${this.id}': focus pulls are not supported in recipe_version 1`);
    const cam: RecipeCamera = {};
    const c = this.camera;
    if (c instanceof Framing) {
      c.subjects.forEach((s, i) => {
        if (typeof s !== "string") {
          encTarget(s, `camera.subjects[${i}]`); // DazNode -> TypeError
          throw new Error(`shot '${this.id}': recipe framing subjects must be actor/prop keys`);
        }
      });
      if (c.distanceCm !== null || c.anchorCm !== null) {
        throw new Error(`shot '${this.id}': distance_cm/anchor_cm can't be expressed in a recipe`);
      }
      cam.frame = c.subjects.length === 1 ? c.subjects[0] : [...c.subjects];
      if (c.size !== "medium") cam.shot_type = c.size;
      if (c.elevationDeg !== null) cam.elevation_deg = c.elevationDeg;
      else cam.angle = c.angle;
      if (c.azimuthDeg) cam.azimuth_deg = c.azimuthDeg;
      if (c.composition !== "center") cam.composition = c.composition;
    } else {
      if (c.lookAtOffsetCm) throw new Error(`shot '${this.id}': look_at_offset_cm can't be expressed in a recipe`);
      cam.position = c.position.toList();
      if (c.lookAt !== null) cam.look_at = encTarget(c.lookAt, "camera.look_at");
      else if (c.rotation !== null) cam.rotation = [...c.rotation];
    }
    const lens = this.lens;
    if (lens.fStop !== null) throw new Error(`shot '${this.id}': f_stop can't be expressed in a recipe`);
    cam.focal_length = lens.focalLength;
    if (lens.depthOfField) cam.depth_of_field = true;
    if (lens.focalDistance !== null) cam.focal_distance = lens.focalDistance;
    let shot: RecipeShot | null = null;
    if (this.output !== null) {
      shot = { id: this.id, camera: this.id, output: this.output.path };
      const render: Record<string, unknown> = {};
      if (this.output.engine !== null) render.engine = this.output.engine;
      if (this.output.resolution !== null) render.resolution = [...this.output.resolution];
      if (this.output.iraySamples !== null) render.iray_samples = this.output.iraySamples;
      if (Object.keys(render).length) shot.render = render;
    }
    return [cam, shot];
  }
}

function uniqueIds(shots: readonly Shot[], what: string): void {
  const seen = new Set<string>();
  for (const s of shots) {
    if (seen.has(s.id)) throw new Error(`${what}: duplicate shot id '${s.id}'`);
    seen.add(s.id);
  }
}

/** An ordered run of shots that cut together. */
export class Sequence {
  readonly id: string;
  readonly shots: readonly Shot[];
  readonly lighting: string | null;
  readonly storyboard: Storyboard | null;

  constructor(init: { id: string; shots?: readonly Shot[]; lighting?: string | null; storyboard?: Storyboard | null }) {
    this.id = init.id;
    this.shots = Object.freeze([...(init.shots ?? [])]);
    this.lighting = init.lighting ?? null;
    this.storyboard = init.storyboard ?? null;
    if (!this.id) throw new Error("id must be non-empty");
    uniqueIds(this.shots, `sequence '${this.id}'`);
    Object.freeze(this);
  }

  /** @throws Error No shot with that id. */
  shot(shotId: string): Shot {
    const s = this.shots.find((x) => x.id === shotId);
    if (!s) throw new Error(`no shot '${shotId}' in sequence '${this.id}'`);
    return s;
  }

  toDict(path = ""): Dict {
    const out: Dict = { id: this.id };
    if (this.shots.length) {
      out.shots = this.shots.map((s, i) => {
        try {
          return s.toDict();
        } catch (e) {
          if (e instanceof TypeError) throw new TypeError(`${join(path, "shots")}[${i}].${e.message}`);
          throw e;
        }
      });
    }
    put(out, "lighting", this.lighting);
    if (this.storyboard !== null) out.storyboard = this.storyboard.toDict();
    return out;
  }

  static fromDict(data: unknown, path = ""): Sequence {
    const d = fields(data, path, "Sequence", ["id", "shots", "lighting", "storyboard"]);
    const sp = join(path, "shots");
    const shots = d.shots === undefined ? [] : decArray(d.shots, sp).map((s, i) => Shot.fromDict(s, `${sp}[${i}]`));
    const storyboard = opt(d.storyboard, (v) => Storyboard.fromDict(v, join(path, "storyboard")));
    return construct(path, () =>
      new Sequence({ id: required(d, "id", path, "Sequence") as string, shots, lighting: d.lighting as string | null | undefined, storyboard }),
    );
  }
}

export interface CoveragePlanInit {
  id: string;
  subjects?: readonly string[];
  axis?: readonly [string, string] | null;
  sequences?: readonly Sequence[];
  lighting?: string | null;
  storyboard?: Storyboard | null;
}

/**
 * How a scene is covered: its subjects, line of action and sequences.
 *
 * - `axis`: optional pair of subject keys defining the line of action (the
 *   180-degree line), enforced by the shot library's continuity checks.
 * - `sequences`: shot ids are unique across the whole plan.
 * - `lighting`: default lighting continuity key for shots that set none.
 */
export class CoveragePlan {
  readonly id: string;
  readonly subjects: readonly string[];
  readonly axis: readonly [string, string] | null;
  readonly sequences: readonly Sequence[];
  readonly lighting: string | null;
  readonly storyboard: Storyboard | null;

  constructor(init: CoveragePlanInit) {
    this.id = init.id;
    this.subjects = Object.freeze([...(init.subjects ?? [])]);
    this.axis = init.axis ? frozenPair(init.axis) : null;
    this.sequences = Object.freeze([...(init.sequences ?? [])]);
    this.lighting = init.lighting ?? null;
    this.storyboard = init.storyboard ?? null;
    if (!this.id) throw new Error("id must be non-empty");
    if (init.axis) {
      // init.axis, not this.axis: frozenPair drops extra entries an untyped caller passed.
      if (init.axis.length !== 2 || init.axis[0] === init.axis[1]) throw new Error("axis must name two different subjects");
      const missing = init.axis.filter((a) => !this.subjects.includes(a));
      if (missing.length) throw new Error(`axis names [${missing.map((m) => `'${m}'`).join(", ")}] which are not in subjects`);
    }
    const seqIds = this.sequences.map((s) => s.id);
    if (new Set(seqIds).size !== seqIds.length) throw new Error("duplicate sequence id");
    uniqueIds(this.allShots(), `coverage plan '${this.id}'`);
    Object.freeze(this);
  }

  allShots(): Shot[] {
    return this.sequences.flatMap((seq) => [...seq.shots]);
  }

  /** The shot's lighting continuity key: its own, its sequence's, else the plan's. */
  lightingFor(shot: Shot): string | null {
    if (shot.lighting !== null) return shot.lighting;
    for (const seq of this.sequences) {
      if (seq.lighting !== null && seq.shots.some((s) => s.id === shot.id)) return seq.lighting;
    }
    return this.lighting;
  }

  toDict(): Dict {
    const out: Dict = { id: this.id };
    if (this.subjects.length) out.subjects = [...this.subjects];
    if (this.axis !== null) out.axis = [...this.axis];
    if (this.sequences.length) out.sequences = this.sequences.map((s, i) => s.toDict(`sequences[${i}]`));
    put(out, "lighting", this.lighting);
    if (this.storyboard !== null) out.storyboard = this.storyboard.toDict();
    return out;
  }

  static fromDict(data: unknown, path = ""): CoveragePlan {
    const d = fields(data, path, "CoveragePlan", ["id", "subjects", "axis", "sequences", "lighting", "storyboard"]);
    const sp = join(path, "sequences");
    const sequences = d.sequences === undefined ? [] : decArray(d.sequences, sp).map((s, i) => Sequence.fromDict(s, `${sp}[${i}]`));
    return construct(path, () =>
      new CoveragePlan({
        id: required(d, "id", path, "CoveragePlan") as string,
        subjects: d.subjects === undefined ? [] : (decArray(d.subjects, join(path, "subjects")) as string[]),
        // Length and members are checked by the constructor (same messages as a direct call).
        axis: opt(d.axis, (v) => decArray(v, join(path, "axis")) as unknown as readonly [string, string]),
        sequences,
        lighting: d.lighting as string | null | undefined,
        storyboard: opt(d.storyboard, (v) => Storyboard.fromDict(v, join(path, "storyboard"))),
      }),
    );
  }

  /** `{cameras: {...}, shots: [...]}` for every shot, in plan order. See {@link Shot.toRecipe}. */
  toRecipeSections(): { cameras: Record<string, RecipeCamera>; shots: RecipeShot[] } {
    const cameras: Record<string, RecipeCamera> = {};
    const shots: RecipeShot[] = [];
    for (const s of this.allShots()) {
      const [cam, spec] = s.toRecipe();
      cameras[s.id] = cam;
      if (spec !== null) shots.push(spec);
    }
    return { cameras, shots };
  }

  /**
   * A deep copy of `recipe` with this plan's cameras and shots added.
   * @throws Error A camera key or shot id already exists in `recipe`.
   */
  mergeIntoRecipe(recipe: Record<string, unknown>): Record<string, unknown> {
    const out = structuredClone(recipe) as Record<string, unknown>;
    const sections = this.toRecipeSections();
    const cams = (out.cameras ??= {}) as Record<string, unknown>;
    const clash = Object.keys(cams).filter((k) => k in sections.cameras).sort();
    const existing = new Set(((out.shots as Array<{ id?: string }> | undefined) ?? []).map((s) => s.id));
    clash.push(...sections.shots.map((s) => s.id).filter((id) => existing.has(id)).sort());
    if (clash.length) throw new Error(`recipe already has cameras/shots named [${clash.map((c) => `'${c}'`).join(", ")}]`);
    Object.assign(cams, sections.cameras);
    if (sections.shots.length) ((out.shots ??= []) as unknown[]).push(...sections.shots);
    return out;
  }
}

/**
 * Build a {@link Shot} from a scene-recipe `cameras[key]` entry (and optional
 * `shots[]` entry). Recipe framing cameras without `angle` keep the recipe's
 * 10 degree default elevation (as an explicit `elevationDeg`).
 */
export function shotFromRecipeCamera(key: string, camera: Record<string, unknown>, shot?: Record<string, unknown> | null): Shot {
  const c = camera;
  const lens = new Lens({
    focalLength: (c.focal_length as number | undefined) ?? 50.0,
    depthOfField: (c.depth_of_field as boolean | undefined) ?? false,
    focalDistance: (c.focal_distance as number | undefined) ?? null,
  });
  let cam: ShotCamera;
  if ("frame" in c) {
    const frame = c.frame as string | string[];
    cam = new Framing({
      subjects: typeof frame === "string" ? [frame] : frame,
      size: (c.shot_type as ShotSize | undefined) ?? "medium",
      angle: (c.angle as CameraAngle | undefined) ?? "eye_level",
      azimuthDeg: (c.azimuth_deg as number | undefined) ?? 0.0,
      elevationDeg: "angle" in c ? null : ((c.elevation_deg as number | undefined) ?? 10.0),
      composition: (c.composition as Composition | undefined) ?? "center",
    });
  } else {
    cam = new Placement({
      position: decVec(c.position, "position"),
      lookAt: opt(c.look_at, (v) => decTarget(v, "look_at")),
      rotation: opt(c.rotation, (v) => decRotation(v, "rotation")),
    });
  }
  let output: RenderOutput | null = null;
  if (shot) {
    const r = (shot.render as Record<string, unknown> | undefined) ?? {};
    output = new RenderOutput({
      path: shot.output as string,
      engine: (r.engine as RenderEngine | undefined) ?? null,
      resolution: opt(r.resolution, (v) => decNumberPair(v, "render.resolution")),
      iraySamples: (r.iray_samples as number | undefined) ?? null,
    });
  }
  return new Shot({ id: key, camera: cam, lens, output });
}

// ---- geometry -------------------------------------------------------------

export interface FrameGeometry {
  /** Camera frame width (mm). Defaults to {@link DEFAULT_FRAME_WIDTH_MM}. */
  frameWidthMm?: number;
  /** Frame height / width. Defaults to {@link DEFAULT_ASPECT}. */
  aspect?: number;
}

/** Distance at which `size`'s fit height fills the frame height at `focalLength`. */
export function framingDistance(size: ShotSize, focalLength: number, geo: FrameGeometry = {}): number {
  return (SHOT_SIZES[size][0] * focalLength) / ((geo.frameWidthMm ?? DEFAULT_FRAME_WIDTH_MM) * (geo.aspect ?? DEFAULT_ASPECT));
}

/**
 * Camera `[position, aim]` for `framing` of already-resolved subject points.
 *
 * `points` holds `[base point, isFigure]` per subject. Figures are raised by
 * the size's anchor height; other points only by `framing.anchorCm` (which,
 * when set, raises every point).
 */
export function framingTransform(
  points: Iterable<readonly [Vec3, boolean]>,
  framing: Framing,
  focalLength: number,
  geo: FrameGeometry = {},
): [Vec3, Vec3] {
  const frameWidthMm = geo.frameWidthMm ?? DEFAULT_FRAME_WIDTH_MM;
  const anchorDefault = SHOT_SIZES[framing.size][1];
  const raised: Vec3[] = [];
  for (const [p, isFigure] of points) {
    const a = framing.anchorCm ?? (isFigure ? anchorDefault : 0.0);
    raised.push(a ? new Vec3(p.x, p.y + a, p.z) : p);
  }
  const n = raised.length;
  const center = new Vec3(
    raised.reduce((s, p) => s + p.x, 0) / n,
    raised.reduce((s, p) => s + p.y, 0) / n,
    raised.reduce((s, p) => s + p.z, 0) / n,
  );
  const distance = framing.distanceCm ?? framingDistance(framing.size, focalLength, geo);
  const position = sphericalOffset(center, framing.azimuthDeg, framing.effectiveElevationDeg, distance);
  if (framing.composition === "center") return [position, center];
  const right = center.sub(position).cross(new Vec3(0, 1, 0));
  if (right.length() < 1e-9) return [position, center]; // looking straight up/down: no horizon
  const shift = (distance * frameWidthMm) / focalLength / 6.0;
  // Subject on the left third -> aim to its right, and vice versa.
  const sign = framing.composition === "left_third" ? 1.0 : -1.0;
  return [position, center.add(right.normalize().mul(shift * sign))];
}

/** Resolves key targets for {@link applyShot}: an actor root `Vec3` or a live node. */
export type Subjects = Readonly<Record<string, Vec3 | DazNode>>;

async function resolvePoint(t: Target, subjects: Subjects | undefined): Promise<[Vec3, boolean]> {
  if (typeof t === "string") {
    const resolved = subjects?.[t];
    if (resolved === undefined) throw new Error(`subject '${t}' is a key but no 'subjects' mapping resolves it`);
    return [resolved instanceof Vec3 ? resolved : await resolveTarget(resolved), true];
  }
  if (t instanceof Vec3) return [t, false];
  return [await resolveTarget(t), true];
}

async function resolveAim(t: Target, subjects: Subjects | undefined, offset: number): Promise<Vec3> {
  if (typeof t === "string") {
    const [p] = await resolvePoint(t, subjects);
    return offset ? new Vec3(p.x, p.y + offset, p.z) : p;
  }
  return resolveTarget(t, offset);
}

// ---- apply ----------------------------------------------------------------

async function applyLens(cam: DazCamera, lens: Lens): Promise<void> {
  await cam.setFocalLength(lens.focalLength);
  if (lens.depthOfField !== null) await cam.setDepthOfField(lens.depthOfField);
  if (lens.focalDistance !== null) await cam.setFocalDistance(lens.focalDistance);
  if (lens.fStop !== null) await cam.setFStop(lens.fStop);
}

async function applyAspect(cam: DazCamera, aspect: AspectSettings | null): Promise<void> {
  if (aspect === null) return;
  if (aspect.aspectWidth !== null) await cam.setAspectWidth(aspect.aspectWidth);
  if (aspect.aspectHeight !== null) await cam.setAspectHeight(aspect.aspectHeight);
  if (aspect.pixelsWidth !== null) await cam.setPixelsWidth(aspect.pixelsWidth);
  if (aspect.pixelsHeight !== null) await cam.setPixelsHeight(aspect.pixelsHeight);
}

function orbitTarget(shot: Shot): Target {
  const c = shot.camera;
  if (c instanceof Framing) return c.subjects[0];
  if (c.lookAt === null) {
    throw new Error(`shot '${shot.id}': an Orbit needs a target (a Framing subject or Placement.lookAt)`);
  }
  return c.lookAt;
}

export interface ApplyShotOptions extends FrameGeometry {
  /** An existing camera to reuse; otherwise one is created. */
  camera?: DazCamera;
  /** Name for a newly created camera. */
  name?: string;
  /** Resolves key targets to an actor root `Vec3` or a live node. */
  subjects?: Subjects;
  /**
   * Clear the camera's existing position/rotation (for a {@link Keyframed}
   * move) and focal-distance (for a focus pull) keys first. `false` adds the
   * shot's keys to what is there, so successive moves on one camera chain.
   * Defaults to `true`.
   */
  clearKeys?: boolean;
}

/**
 * Put `shot` into the scene on a camera and return the camera. Planning data
 * (blocking, gaze, lighting continuity, storyboard, output) is not applied.
 *
 * @throws Error A key target isn't in `subjects`, or an {@link Orbit} has no
 * target (checked before any camera is created).
 */
export async function applyShot(scene: DazScene, shot: Shot, opts: ApplyShotOptions = {}): Promise<DazCamera> {
  const { subjects } = opts;
  const clearKeys = opts.clearKeys ?? true;
  const movement = shot.movement;
  const c = shot.camera;
  const target0 = movement instanceof Orbit ? orbitTarget(shot) : null; // validate before touching the scene
  const cam = opts.camera ?? (await scene.createCamera(opts.name));

  if (movement instanceof Orbit) {
    await scene.setAnimRange(movement.frameStart, movement.frameEnd);
    const target = await resolveAim(target0!, subjects, movement.targetOffsetCm);
    await cam.setFocalLength(shot.lens.focalLength);
    const count = movement.frameEnd - movement.frameStart;
    for (let frame = movement.frameStart; frame <= movement.frameEnd; frame++) {
      const t = count > 0 ? (frame - movement.frameStart) / count : 0.0;
      const az = movement.startAzimuthDeg + (movement.endAzimuthDeg - movement.startAzimuthDeg) * t;
      const pos = sphericalOffset(target, az, movement.elevationDeg, movement.radius);
      await scene.setFrame(frame);
      await cam.setPosition(pos.x, pos.y, pos.z);
      await cam.aimAt(target.x, target.y, target.z);
    }
  } else if (movement instanceof Keyframed) {
    await applyLens(cam, shot.lens);
    if (clearKeys) {
      await cam.clearPositionKeys();
      if (movement.hasOrientation) await cam.clearRotationKeys();
    }
    for (const kf of movement.keyframes) {
      await cam.setPositionAtFrame(kf.frame, kf.position.x, kf.position.y, kf.position.z);
      if (kf.lookAt !== null) {
        const target = await resolveAim(kf.lookAt, subjects, kf.lookAtOffsetCm);
        await cam.setRotationAtFrame(kf.frame, ...lookAtEuler(kf.position, target));
      } else if (kf.rotation !== null) {
        await cam.setRotationAtFrame(kf.frame, kf.rotation[0], kf.rotation[1], kf.rotation[2]);
      }
    }
    const plan = movement.keyInterpolation();
    if (plan !== null) {
      const [kinds, fastStart, fastEnd] = plan;
      await cam.setTransformKeyInterpolation(movement.keyframes.map((k) => k.frame), kinds, {
        rotation: movement.hasOrientation,
        fastStart,
        fastEnd,
      });
    }
  } else if (c instanceof Framing) {
    const points: Array<[Vec3, boolean]> = [];
    for (const s of c.subjects) points.push(await resolvePoint(s, subjects));
    const [pos, aim] = framingTransform(points, c, shot.lens.focalLength, opts);
    await cam.setPosition(pos.x, pos.y, pos.z);
    await cam.aimAt(aim.x, aim.y, aim.z);
    await applyLens(cam, shot.lens);
  } else {
    await cam.setPosition(c.position.x, c.position.y, c.position.z);
    if (c.lookAt !== null) {
      const target = await resolveAim(c.lookAt, subjects, c.lookAtOffsetCm);
      await cam.aimAt(target.x, target.y, target.z);
    } else if (c.rotation !== null) {
      await cam.setRotation(c.rotation[0], c.rotation[1], c.rotation[2]);
    }
    await applyLens(cam, shot.lens);
  }

  await applyAspect(cam, shot.aspect);
  if (shot.focus !== null) {
    await cam.setDepthOfField(true);
    if (clearKeys) await cam.clearFocalDistanceKeys();
    for (const k of shot.focus.keys) await cam.setFocalDistanceAtFrame(k.frame, k.focalDistance);
  }
  return cam;
}
