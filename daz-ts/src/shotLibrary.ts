/**
 * Common cinematic shots, coverage and continuity rules on top of
 * `shots.ts`. Mirrors dazpy's `shot_library.py`.
 *
 * Every builder here is pure: it takes actor root positions (`Vec3`, the
 * floor point under a standing figure, as `DazNode.position()` reports it)
 * and returns {@link Shot} / {@link CoveragePlan} models. {@link applyShot}
 * (or {@link applyCoverage}) puts them into a live scene; pass the same
 * `positions` mapping as its `subjects`.
 *
 * - **Shot types** -- {@link establishing}, {@link master}, {@link twoShot},
 *   {@link single}, {@link insert}, {@link pov}, {@link overTheShoulder},
 *   {@link shotReverseShot}.
 * - **The 180-degree rule** -- a {@link LineOfAction} between two actors
 *   picks the side every camera stays on; {@link checkAxis} reports a camera
 *   that crosses it and {@link checkThirtyDegree} a jump cut.
 * - **Composition** -- {@link headroomAnchor}, {@link leadRoom}, {@link composeAim}.
 * - **Camera moves** -- {@link pushIn} / {@link pullOut}, {@link arc}, and
 *   {@link cameraMove} (dolly, truck, pedestal, crane, pan, tilt, handheld).
 * - **Focus** -- {@link rackFocus} / {@link withRackFocus}, {@link depthOfFieldLimits}.
 * - **Coverage** -- {@link subjectCoverage}, {@link dialogueCoverage},
 *   {@link conversation} cutting a list of {@link DialogueBeat}s.
 * - **Naming** -- {@link shotName}: a consistent id that is also a valid
 *   scene-recipe key.
 *
 * Differences from dazpy: continuity checks and other pure helpers take
 * key/`Vec3` targets only (dazpy can read a live node's position
 * synchronously; here that is an HTTP round trip, so a node target throws),
 * and `cameraMove("handheld")` uses its own seeded PRNG -- repeatable per
 * seed, but not the same jitter values as dazpy's `random.Random`.
 *
 * Units are DAZ native: centimetres, Y-up, degrees, timeline frames.
 */

import { Quat, Vec3 } from "./math3.js";
import { lookAtEuler, sphericalOffset } from "./shotGeometry.js";
import {
  CameraKeyframe,
  CoveragePlan,
  DEFAULT_FRAME_WIDTH_MM,
  FocusKey,
  FocusPull,
  Framing,
  GazeBeat,
  Keyframed,
  Lens,
  Orbit,
  Placement,
  SHOT_SIZES,
  Sequence,
  Shot,
  Storyboard,
  applyShot,
  framingDistance,
  framingTransform,
  isNodeTarget,
  type CameraAngle,
  type Composition,
  type FrameGeometry,
  type Rotation,
  type ShotSize,
  type Subjects,
  type Target,
} from "./shots.js";
import type { DazCamera } from "./camera.js";
import type { DazScene } from "./scene.js";

/** Actor key -> root position. */
export type Positions = Readonly<Record<string, Vec3>>;
/** A focal length in mm, or a full {@link Lens}. */
export type LensSpec = Lens | number;
/** A frame range `[start, end]`. */
export type FrameRange = readonly [number, number];

/** Eye height above a standing Genesis-scale actor's root (cm); the `close_up` anchor. */
export const EYE_HEIGHT_CM = 160.0;

/** Over-the-shoulder camera offsets from the foreground actor's head (cm). */
export const OTS_BACK_CM = 60.0;
export const OTS_SIDE_CM = 35.0;
export const OTS_DROP_CM = 10.0;

/** How far a clean single swings off the partner's eyeline toward the camera side. */
export const SINGLE_OFFSET_DEG = 25.0;

/** Default lenses per shot family (mm). */
export const DEFAULT_LENSES: Readonly<Record<string, number>> = Object.freeze({
  establishing: 24.0,
  master: 35.0,
  two_shot: 50.0,
  single: 85.0,
  ots: 50.0,
  pov: 35.0,
  insert: 100.0,
  move: 50.0,
});

/** Shot-id abbreviations, per kind or shot size. */
export const SHOT_ABBREVIATIONS: Readonly<Record<string, string>> = Object.freeze({
  establishing: "EST",
  master: "MST",
  two_shot: "2S",
  ots: "OTS",
  single: "SGL",
  insert: "INS",
  pov: "POV",
  push_in: "PUSH",
  pull_out: "PULL",
  arc: "ARC",
  move: "MOVE",
  extreme_wide: "EWS",
  wide: "WS",
  full_body: "FS",
  medium_wide: "MWS",
  medium: "MS",
  medium_close_up: "MCU",
  close_up: "CU",
  extreme_close_up: "ECU",
});

const UP = new Vec3(0, 1, 0);
const KEY_MAX = 64;
const DEG = Math.PI / 180;

// ---- naming ---------------------------------------------------------------

function slug(text: string | number): string {
  const s = String(text).replace(/[^A-Za-z0-9-]+/g, "-").replace(/^-+|-+$/g, "");
  return s || "x";
}

export interface ShotNameOptions {
  tag?: string | null;
  scene?: number | string | null;
  index?: number | null;
}

/**
 * A consistent shot id: `[SC<scene>_][<index>_]<ABBR>[_<tag>][_<subject>][_over_<over>]`.
 *
 * `kind` is a key of {@link SHOT_ABBREVIATIONS} (a shot kind or size); any
 * other string is used upper-cased. Names are reduced to `[A-Za-z0-9-]` so
 * the id is a valid scene-recipe key (at most 64 characters).
 *
 * `shotName("ots", "bob", "alice")` -> `"OTS_bob_over_alice"`;
 * `shotName("close_up", "anna", null, { scene: 3, index: 12 })` -> `"SC3_012_CU_anna"`.
 */
export function shotName(kind: string, subject?: string | null, over?: string | null, opts: ShotNameOptions = {}): string {
  const parts: string[] = [];
  if (opts.scene !== undefined && opts.scene !== null) parts.push(`SC${slug(opts.scene)}`);
  if (opts.index !== undefined && opts.index !== null) parts.push(String(opts.index).padStart(3, "0"));
  parts.push(SHOT_ABBREVIATIONS[kind] ?? slug(kind).toUpperCase());
  if (opts.tag) parts.push(slug(opts.tag));
  if (subject) parts.push(slug(subject));
  if (over) parts.push("over", slug(over));
  return parts.join("_").slice(0, KEY_MAX);
}

// ---- geometry helpers -----------------------------------------------------

function flat(v: Vec3): Vec3 {
  return new Vec3(v.x, 0, v.z);
}

/** Azimuth (see `sphericalOffset`) of a horizontal direction. */
function azimuth(direction: Vec3): number {
  return Math.atan2(direction.x, direction.z) / DEG;
}

function eye(root: Vec3, eyeHeight = EYE_HEIGHT_CM): Vec3 {
  return new Vec3(root.x, root.y + eyeHeight, root.z);
}

function screenRight(position: Vec3, aim: Vec3): Vec3 | null {
  const right = aim.sub(position).cross(UP);
  return right.length() > 1e-9 ? right.normalize() : null;
}

/** Horizontal screen position (-1 left edge .. +1 right edge) of the rule-of-thirds vertical. */
export const THIRD_X = 1.0 / 3.0;
/** Horizontal screen position of the golden-section vertical (~0.236: a 0.382 / 0.618 split). */
export const GOLDEN_X = 1.0 - 2.0 * (1.0 - 2.0 / (1.0 + Math.sqrt(5.0)));

/**
 * The aim point that puts `target` at horizontal screen position `screenX`
 * (`-1` left edge .. `+1` right edge; `0` centred, {@link THIRD_X} the right
 * third). The camera turns, it does not move.
 */
export function composeAim(position: Vec3, target: Vec3, screenX: number, focalLength: number, frameWidthMm = DEFAULT_FRAME_WIDTH_MM): Vec3 {
  const right = screenRight(position, target);
  if (right === null || !screenX) return target;
  const halfWidth = (position.distance(target) * frameWidthMm) / focalLength / 2.0;
  return target.sub(right.mul(screenX * halfWidth));
}

function lensOf(lens: LensSpec | null | undefined, family: string): Lens {
  if (lens === undefined || lens === null) return new Lens({ focalLength: DEFAULT_LENSES[family] });
  return typeof lens === "number" ? new Lens({ focalLength: lens }) : lens;
}

function posOf(positions: Positions, key: string): Vec3 {
  const p = positions[key];
  if (p === undefined) throw new Error(`no position for '${key}'`);
  return p;
}

/**
 * The 180-degree line between actors `a` and `b`, and the side cameras keep to.
 *
 * `side` is `+1` or `-1` -- which half-plane the cameras stand in. `+1` is
 * to `a`'s right as `a` faces `b` (`+X` when a->b runs along `-Z`).
 */
export class LineOfAction {
  readonly a: string;
  readonly b: string;
  readonly aPos: Vec3;
  readonly bPos: Vec3;
  readonly side: 1 | -1;

  constructor(a: string, b: string, aPos: Vec3, bPos: Vec3, side: number = 1) {
    if (a === b) throw new Error("a line of action needs two different actors");
    if (side !== 1 && side !== -1) throw new Error("side must be +1 or -1");
    if (flat(bPos.sub(aPos)).length() < 1e-6) throw new Error(`'${a}' and '${b}' stand on the same spot; no line of action`);
    this.a = a;
    this.b = b;
    this.aPos = aPos;
    this.bPos = bPos;
    this.side = side;
    Object.freeze(this);
  }

  /** The line between keys `a` and `b` of `positions`. */
  static between(positions: Positions, a: string, b: string, side: number = 1): LineOfAction {
    return new LineOfAction(a, b, posOf(positions, a), posOf(positions, b), side);
  }

  /** Unit horizontal direction from `a` to `b`. */
  get direction(): Vec3 {
    return flat(this.bPos.sub(this.aPos)).normalize();
  }

  /** Unit horizontal direction from the line toward the camera side. */
  get normal(): Vec3 {
    const d = this.direction;
    return new Vec3(-d.z, 0, d.x).mul(this.side);
  }

  get midpoint(): Vec3 {
    return this.aPos.add(this.bPos).mul(0.5);
  }

  get separation(): number {
    return flat(this.bPos.sub(this.aPos)).length();
  }

  /** A copy with `side` replaced. */
  withSide(side: number): LineOfAction {
    return new LineOfAction(this.a, this.b, this.aPos, this.bPos, side);
  }

  /** The same line with cameras on the other side (a deliberate cross). */
  flipped(): LineOfAction {
    return this.withSide(-this.side);
  }

  position(key: string): Vec3 {
    if (key === this.a) return this.aPos;
    if (key === this.b) return this.bPos;
    throw new Error(`'${key}' is not on this line (actors: '${this.a}', '${this.b}')`);
  }

  other(key: string): string {
    this.position(key);
    return key === this.a ? this.b : this.a;
  }

  /** `+1` / `-1` for the half-plane `point` is in, `0` within `toleranceCm` of the line. */
  sideOf(point: Vec3, toleranceCm = 1.0): -1 | 0 | 1 {
    const d = this.direction;
    const rel = flat(point.sub(this.aPos));
    const offset = d.x * rel.z - d.z * rel.x; // signed distance; > 0 on the side=+1 half-plane
    if (Math.abs(offset) <= toleranceCm) return 0;
    return offset > 0 ? 1 : -1;
  }
}

// ---- composition ----------------------------------------------------------

/**
 * Aim height (cm above the root) that puts a standing actor's eyes on the
 * upper third. Pass it as `Framing.anchorCm`.
 */
export function headroomAnchor(size: ShotSize, eyeHeight = EYE_HEIGHT_CM): number {
  return Math.max(0.0, eyeHeight - SHOT_SIZES[size][0] / 6.0);
}

/**
 * The composition that leaves room in front of a gaze: a subject looking
 * screen-right goes on the left third and vice versa; one looking (nearly)
 * into or away from the lens stays centred.
 *
 * @param facing Direction the subject looks (any length; only X/Z matter).
 * @param threshold Minimum sideways component (of the unit facing) for an off-centre composition.
 */
export function leadRoom(cameraPosition: Vec3, aim: Vec3, facing: Vec3, threshold = 0.15): Composition {
  const right = screenRight(cameraPosition, aim);
  const f = flat(facing);
  if (right === null || f.length() < 1e-9) return "center";
  const lateral = f.normalize().dot(right);
  if (lateral > threshold) return "left_third";
  if (lateral < -threshold) return "right_third";
  return "center";
}

/** Width (cm) added to two actors' separation for their bodies when fitting a two-shot. */
export const BODY_WIDTH_CM = 60.0;

/**
 * The distance that fits two actors `separationCm` apart across the frame, or
 * `null` when the size's own fitted distance already does (which keeps the
 * shot recipe-expressible).
 */
function fitDistance(size: ShotSize, separationCm: number, focalLength: number, geo: FrameGeometry): number | null {
  const byWidth = ((separationCm + BODY_WIDTH_CM) * focalLength) / (geo.frameWidthMm ?? DEFAULT_FRAME_WIDTH_MM);
  const bySize = framingDistance(size, focalLength, geo);
  return byWidth > bySize ? byWidth : null;
}

// ---- shot types -----------------------------------------------------------

/** Options shared by the both-actors builders. */
export interface SideShotOptions extends FrameGeometry {
  size?: ShotSize;
  lens?: LensSpec;
  id?: string;
  frameRange?: FrameRange | null;
}

function sideFraming(line: LineOfAction, family: string, size: ShotSize, elevationDeg: number | null, opts: SideShotOptions): Shot {
  const ln = lensOf(opts.lens, family);
  const camera = new Framing({
    subjects: [line.a, line.b],
    size,
    azimuthDeg: azimuth(line.normal),
    elevationDeg,
    distanceCm: fitDistance(size, line.separation, ln.focalLength, opts),
  });
  return new Shot({ id: opts.id ?? shotName(family, `${line.a}-${line.b}`), camera, lens: ln, frameRange: opts.frameRange ?? null });
}

/** A wide, slightly high shot of both actors from the camera side of the line. */
export function establishing(line: LineOfAction, opts: SideShotOptions & { elevationDeg?: number } = {}): Shot {
  return sideFraming(line, "establishing", opts.size ?? "extreme_wide", opts.elevationDeg ?? 10.0, opts);
}

/** The master: both actors, perpendicular to the line, at eye level. */
export function master(line: LineOfAction, opts: SideShotOptions = {}): Shot {
  return sideFraming(line, "master", opts.size ?? "wide", null, opts);
}

/** A two-shot: both actors at `size` (widened if they stand too far apart to fit). */
export function twoShot(line: LineOfAction, opts: SideShotOptions = {}): Shot {
  return sideFraming(line, "two_shot", opts.size ?? "medium_wide", null, opts);
}

export interface SingleOptions {
  size?: ShotSize;
  lens?: LensSpec;
  /** How far the camera swings off the partner's eyeline toward the camera side (0 = down the eyeline). */
  offsetDeg?: number;
  angle?: CameraAngle;
  /** Aim with {@link headroomAnchor} (eyes on the upper third). Defaults to `false`. */
  headroom?: boolean;
  /** Compose with {@link leadRoom} toward the partner. Defaults to `true`. */
  lead?: boolean;
  id?: string;
  frameRange?: FrameRange | null;
}

/** A clean single of `subject` (on `line`), from near their partner's eyeline on the camera side. */
export function single(line: LineOfAction, subject: string, opts: SingleOptions = {}): Shot {
  const size = opts.size ?? "medium_close_up";
  const toPartner = flat(line.position(line.other(subject)).sub(line.position(subject))).normalize();
  const a = (opts.offsetDeg ?? SINGLE_OFFSET_DEG) * DEG;
  const direction = toPartner.mul(Math.cos(a)).add(line.normal.mul(Math.sin(a)));
  const composition = (opts.lead ?? true) ? leadRoom(direction, new Vec3(0, 0, 0), toPartner) : "center";
  const camera = new Framing({
    subjects: [subject],
    size,
    angle: opts.angle ?? "eye_level",
    azimuthDeg: azimuth(direction),
    composition,
    anchorCm: opts.headroom ? headroomAnchor(size) : null,
  });
  return new Shot({ id: opts.id ?? shotName(size, subject), camera, lens: lensOf(opts.lens, "single"), frameRange: opts.frameRange ?? null });
}

export interface OverTheShoulderOptions {
  lens?: LensSpec;
  backCm?: number;
  sideCm?: number;
  dropCm?: number;
  eyeHeight?: number;
  /** Put the subject's eyes on the third opposite the foreground shoulder. Defaults to `true`. */
  compose?: boolean;
  frameWidthMm?: number;
  id?: string;
  frameRange?: FrameRange | null;
}

/**
 * Over `foreground`'s shoulder onto `subject`, from the camera side of the
 * line. The camera stands `backCm` behind the foreground actor's head and
 * `sideCm` out toward the camera side, a little below eye level.
 */
export function overTheShoulder(line: LineOfAction, foreground: string, subject: string, opts: OverTheShoulderOptions = {}): Shot {
  const pair = new Set([foreground, subject]);
  if (pair.size !== 2 || !pair.has(line.a) || !pair.has(line.b)) {
    throw new Error(`overTheShoulder needs the line's two actors, got '${foreground}' and '${subject}'`);
  }
  const eyeHeight = opts.eyeHeight ?? EYE_HEIGHT_CM;
  const ln = lensOf(opts.lens, "ots");
  const fg = line.position(foreground);
  const behind = flat(fg.sub(line.position(subject))).normalize();
  const head = eye(fg, eyeHeight - (opts.dropCm ?? OTS_DROP_CM));
  const position = head.add(behind.mul(opts.backCm ?? OTS_BACK_CM)).add(line.normal.mul(opts.sideCm ?? OTS_SIDE_CM));
  const target = eye(line.position(subject), eyeHeight);
  let aim = target;
  const right = screenRight(position, target);
  if ((opts.compose ?? true) && right !== null) {
    // The foreground shoulder is on the -normal side of the camera; the subject goes opposite.
    const screenSide = line.normal.dot(right) > 0 ? 1.0 : -1.0;
    aim = composeAim(position, target, screenSide * THIRD_X, ln.focalLength, opts.frameWidthMm ?? DEFAULT_FRAME_WIDTH_MM);
  }
  return new Shot({
    id: opts.id ?? shotName("ots", subject, foreground),
    camera: new Placement({ position, lookAt: aim }),
    lens: ln,
    frameRange: opts.frameRange ?? null,
  });
}

/** The OTS pair: onto `b` over `a`, and the reverse onto `a` over `b`, both on the line's side. */
export function shotReverseShot(
  line: LineOfAction,
  opts: Omit<OverTheShoulderOptions, "id" | "frameRange"> & { frameRanges?: readonly [FrameRange, FrameRange] } = {},
): [Shot, Shot] {
  const { frameRanges, ...ots } = opts;
  return [
    overTheShoulder(line, line.a, line.b, { ...ots, frameRange: frameRanges?.[0] ?? null }),
    overTheShoulder(line, line.b, line.a, { ...ots, frameRange: frameRanges?.[1] ?? null }),
  ];
}

/** `viewer`'s point of view: from their eyes toward `target` (an actor key's eyes, or a point). */
export function pov(
  positions: Positions,
  viewer: string,
  target: string | Vec3,
  opts: { lens?: LensSpec; eyeHeight?: number; forwardCm?: number; id?: string; frameRange?: FrameRange | null } = {},
): Shot {
  const eyeHeight = opts.eyeHeight ?? EYE_HEIGHT_CM;
  const forwardCm = opts.forwardCm ?? 10.0;
  const aim = typeof target === "string" ? eye(posOf(positions, target), eyeHeight) : target;
  const e = eye(posOf(positions, viewer), eyeHeight);
  const toward = aim.sub(e);
  const position = toward.length() > forwardCm ? e.add(toward.normalize().mul(forwardCm)) : e;
  const label = typeof target === "string" ? target : null;
  return new Shot({
    id: opts.id ?? shotName("pov", viewer, null, { tag: label ? `at-${label}` : null }),
    camera: new Placement({ position, lookAt: aim }),
    lens: lensOf(opts.lens, "pov"),
    frameRange: opts.frameRange ?? null,
  });
}

/**
 * An insert: a tight shot of a detail at `point` (a prop, a hand), looking
 * down at it. With `line`, the camera azimuth comes from the line's camera
 * side instead of `azimuthDeg`.
 */
export function insert(
  point: Vec3,
  opts: {
    size?: ShotSize;
    azimuthDeg?: number;
    elevationDeg?: number;
    line?: LineOfAction | null;
    lens?: LensSpec;
    name?: string;
    id?: string;
    frameRange?: FrameRange | null;
  } = {},
): Shot {
  const az = opts.line ? azimuth(opts.line.normal) : (opts.azimuthDeg ?? 0.0);
  const camera = new Framing({ subjects: [point], size: opts.size ?? "extreme_close_up", azimuthDeg: az, elevationDeg: opts.elevationDeg ?? 30.0 });
  return new Shot({
    id: opts.id ?? shotName("insert", opts.name ?? "detail"),
    camera,
    lens: lensOf(opts.lens, "insert"),
    frameRange: opts.frameRange ?? null,
  });
}

// ---- camera moves ---------------------------------------------------------

function wrapDeg(a: number): number {
  const r = (a + 180.0) % 360.0;
  return (r < 0 ? r + 360.0 : r) - 180.0;
}

/** A DzQuat dict (`DazNode.rotation()`'s value) or a {@link Quat} built from one. */
export type StudioQuat = Quat | { x: number; y: number; z: number; w: number };

/**
 * Camera Euler `[x, y, z]` degrees for Studio's world rotation quaternion.
 * DzQuat's `(x, y, z)` are the conjugate of `Quat.fromEuler`'s for the same
 * rotation (live-verified), so they are conjugated here. The result is in
 * {@link canonicalRotation} form.
 */
export function eulerFromQuaternion(q: StudioQuat): [number, number, number] {
  const quat = q instanceof Quat ? q : Quat.fromDict(q);
  return canonicalRotation(quat.conjugate().toEuler("ZYX"));
}

/**
 * The equivalent camera Euler with pitch (`x`) in `[-90, 90]`. `aimAt` can
 * leave a camera at e.g. `(-177, 73, 180)`, which faces the same way as
 * `(3, 107, 0)`; adding a pan to the first form turns the wrong way. Uses
 * the identity `(x, y, z) == (x + 180, 180 - y, z + 180)`.
 */
export function canonicalRotation(rotation: Rotation): [number, number, number] {
  let [x, y, z] = rotation.map(wrapDeg) as [number, number, number];
  if (Math.abs(x) > 90.0) [x, y, z] = [wrapDeg(x + 180.0), wrapDeg(180.0 - y), wrapDeg(z + 180.0)];
  return [x, y, z];
}

function cameraMatrix(rotation: Rotation): number[][] {
  return Quat.fromEuler(rotation[0], rotation[1], rotation[2], "ZYX").toMatrix();
}

/**
 * Unit view direction of a camera with Euler `rotation` (the inverse of
 * `lookAtEuler`). A Studio camera's rotation channels compose as
 * `Quat.fromEuler(x, y, z, "ZYX")` (live-verified, roll included).
 */
export function forwardFromRotation(rotation: Rotation): Vec3 {
  const m = cameraMatrix(rotation);
  return new Vec3(-m[0][2], -m[1][2], -m[2][2]).normalize();
}

/**
 * Camera Euler `[x, y, z]` that looks from `position` at `aim`, rolled
 * `rollDeg` about the view axis -- a dutch angle. Positive roll tips the
 * camera's top toward screen-left, as Studio's own `ZRotate` does on an
 * unturned camera. Use it as `Placement.rotation` when a shot needs roll.
 */
export function lookRotation(position: Vec3, aim: Vec3, rollDeg = 0.0): [number, number, number] {
  const [pitch, yaw] = lookAtEuler(position, aim);
  if (!rollDeg) return [pitch, yaw, 0.0];
  const q = Quat.fromEuler(pitch, yaw, 0.0, "ZYX").multiply(Quat.fromEuler(0.0, 0.0, rollDeg, "ZYX"));
  return canonicalRotation(q.toEuler("ZYX"));
}

/** Unit up direction (screen top) of a camera with Euler `rotation`. */
export function cameraUp(rotation: Rotation): Vec3 {
  const m = cameraMatrix(rotation);
  return new Vec3(m[0][1], m[1][1], m[2][1]).normalize();
}

/** The point `distance` ahead of a camera at `position` with `rotation`. */
export function aimFromRotation(position: Vec3, rotation: Rotation, distance = 100.0): Vec3 {
  return position.add(forwardFromRotation(rotation).mul(distance));
}

/** Default `amount` per {@link cameraMove} kind (cm, or degrees for pan/tilt). */
export const MOVE_DEFAULTS = Object.freeze({
  dolly_in: 200.0,
  dolly_out: 200.0,
  truck_left: 100.0,
  truck_right: 100.0,
  pedestal_up: 50.0,
  pedestal_down: 50.0,
  crane_up: 100.0,
  crane_down: 100.0,
  pan_left: 45.0,
  pan_right: 45.0,
  tilt_up: 20.0,
  tilt_down: 20.0,
  handheld: 2.0,
});
export type CameraMoveKind = keyof typeof MOVE_DEFAULTS;
export const CAMERA_MOVES: readonly CameraMoveKind[] = Object.freeze(Object.keys(MOVE_DEFAULTS) as CameraMoveKind[]);

/** mulberry32: a small seeded PRNG, uniform in [0, 1). */
function seededRandom(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export interface CameraMoveOptions {
  start: number;
  end: number;
  /** Distance (cm) or angle (degrees); defaults per kind from {@link MOVE_DEFAULTS}. */
  amount?: number;
  lens?: LensSpec;
  id?: string;
  /** `handheld` only: PRNG seed. Defaults to `0`. */
  seed?: number;
  /** `handheld` only: frames between jitter keys. Defaults to `3`. */
  step?: number;
}

/**
 * A camera move from the pose (`position`, `rotation`), keyed at `start` and `end`.
 *
 * `rotation` is Euler degrees, or Studio's world quaternion (see
 * {@link eulerFromQuaternion}). Kinds: `dolly_in`/`dolly_out` (along the
 * horizontal view direction), `truck_left`/`truck_right` (sideways),
 * `pedestal_*`/`crane_*` (vertical), `pan_*` (yaw), `tilt_*` (pitch), and
 * `handheld` -- seeded, repeatable jitter every `step` frames (`amount` is
 * the position amplitude in cm; rotation jitter is half that in degrees).
 *
 * Every keyframe carries an explicit rotation, so the move never re-aims.
 */
export function cameraMove(kind: CameraMoveKind, position: Vec3, rotation: Rotation | StudioQuat, opts: CameraMoveOptions): Shot {
  if (!(kind in MOVE_DEFAULTS)) throw new Error(`unknown camera move '${kind}'; valid: ${CAMERA_MOVES.join(", ")}`);
  const { start, end } = opts;
  if (end <= start) throw new Error("end must be > start");
  const amt = opts.amount ?? MOVE_DEFAULTS[kind];
  const rot = Array.isArray(rotation) ? canonicalRotation(rotation as Rotation) : eulerFromQuaternion(rotation as StudioQuat);
  const forward = forwardFromRotation(rot);
  const fl = flat(forward);
  const level = fl.length() > 1e-6;
  const track = level ? fl.normalize() : forward;
  const right = level ? track.cross(UP).normalize() : new Vec3(1, 0, 0);

  let keys: CameraKeyframe[];
  if (kind === "handheld") {
    const rnd = seededRandom(opts.seed ?? 0);
    const uniform = (lo: number, hi: number) => lo + (hi - lo) * rnd();
    const step = opts.step ?? 3;
    keys = [new CameraKeyframe({ frame: start, position, rotation: rot })];
    for (let frame = start + step; frame < end; frame += step) {
      const jitter = new Vec3(uniform(-amt, amt), uniform(-amt, amt), uniform(-amt, amt));
      const rj = amt * 0.5;
      keys.push(new CameraKeyframe({
        frame,
        position: position.add(jitter),
        rotation: [rot[0] + uniform(-rj, rj), rot[1] + uniform(-rj, rj), rot[2] + uniform(-rj, rj)],
      }));
    }
    keys.push(new CameraKeyframe({ frame: end, position, rotation: rot }));
  } else {
    let endPos = position;
    let endRot: Rotation = rot;
    if (kind === "dolly_in" || kind === "dolly_out") endPos = position.add(track.mul(kind === "dolly_in" ? amt : -amt));
    else if (kind === "truck_left" || kind === "truck_right") endPos = position.add(right.mul(kind === "truck_right" ? amt : -amt));
    else if (kind.startsWith("pedestal_") || kind.startsWith("crane_")) endPos = position.add(UP.mul(kind.endsWith("_up") ? amt : -amt));
    else if (kind === "pan_left" || kind === "pan_right") endRot = [rot[0], rot[1] + (kind === "pan_left" ? amt : -amt), rot[2]];
    else endRot = [rot[0] + (kind === "tilt_up" ? amt : -amt), rot[1], rot[2]];
    keys = [new CameraKeyframe({ frame: start, position, rotation: rot }), new CameraKeyframe({ frame: end, position: endPos, rotation: endRot })];
  }
  return new Shot({
    id: opts.id ?? shotName("move", null, null, { tag: kind }),
    camera: new Placement({ position, rotation: rot }),
    lens: lensOf(opts.lens, "move"),
    movement: new Keyframed({ keyframes: keys }),
    frameRange: [start, end],
  });
}

function sizePose(positions: Positions, subject: string, size: ShotSize, azimuthDeg: number, focalLength: number, geo: FrameGeometry): [Vec3, Vec3] {
  const framing = new Framing({ subjects: [subject], size, azimuthDeg });
  return framingTransform([[posOf(positions, subject), true]], framing, focalLength, geo);
}

export interface PushInOptions extends FrameGeometry {
  start: number;
  end: number;
  fromSize?: ShotSize;
  toSize?: ShotSize;
  /** Camera direction; ignored when `line` is given (a clean-single angle is used). */
  azimuthDeg?: number;
  line?: LineOfAction | null;
  lens?: LensSpec;
  id?: string;
}

/**
 * A dolly from `fromSize` (default `"wide"`) to `toSize` (default
 * `"close_up"`) on `subject`, re-aiming as the frame tightens. The camera
 * direction is `azimuthDeg`, or a clean-single angle when a `line` is given.
 */
export function pushIn(positions: Positions, subject: string, opts: PushInOptions): Shot {
  const { start, end } = opts;
  if (end <= start) throw new Error("end must be > start");
  const fromSize = opts.fromSize ?? "wide";
  const toSize = opts.toSize ?? "close_up";
  const ln = lensOf(opts.lens, "move");
  const az = opts.line ? (single(opts.line, subject, { lead: false }).camera as Framing).azimuthDeg : (opts.azimuthDeg ?? 0.0);
  const [p0, a0] = sizePose(positions, subject, fromSize, az, ln.focalLength, opts);
  const [p1, a1] = sizePose(positions, subject, toSize, az, ln.focalLength, opts);
  const kind = framingDistance(toSize, 1.0) < framingDistance(fromSize, 1.0) ? "push_in" : "pull_out";
  return new Shot({
    id: opts.id ?? shotName(kind, subject),
    camera: new Placement({ position: p0, lookAt: a0 }),
    lens: ln,
    movement: new Keyframed({
      keyframes: [new CameraKeyframe({ frame: start, position: p0, lookAt: a0 }), new CameraKeyframe({ frame: end, position: p1, lookAt: a1 })],
    }),
    frameRange: [start, end],
  });
}

/** {@link pushIn} in reverse: from `fromSize` (default `"close_up"`) back out to `toSize` (default `"wide"`). */
export function pullOut(positions: Positions, subject: string, opts: PushInOptions): Shot {
  return pushIn(positions, subject, { ...opts, fromSize: opts.fromSize ?? "close_up", toSize: opts.toSize ?? "wide" });
}

/** Python's `round()`: half to even. */
function roundHalfEven(x: number): number {
  const r = Math.round(x);
  return Math.abs(x % 1) === 0.5 && r % 2 !== 0 ? r - 1 : r;
}

export interface ArcOptions {
  start: number;
  end: number;
  radius?: number;
  startAzimuthDeg?: number;
  endAzimuthDeg?: number;
  elevationDeg?: number;
  targetOffsetCm?: number;
  lens?: LensSpec;
  id?: string;
  /** Keyframe a waypoint every `stepDeg` degrees instead of baking an {@link Orbit}; needs `positions`. */
  stepDeg?: number | null;
  positions?: Positions;
}

/**
 * An arc (orbit) around actor `subject`.
 *
 * By default it is an {@link Orbit}, baked one placement per frame by
 * {@link applyShot}. With `stepDeg` it is a {@link Keyframed} move with a
 * waypoint every `stepDeg` degrees (and at both ends) that Studio
 * interpolates -- far cheaper for long shots; needs `positions`. An arc that
 * sweeps across the line of action crosses it on purpose; {@link checkAxis}
 * reports it.
 */
export function arc(subject: string, opts: ArcOptions): Shot {
  const { start, end } = opts;
  const radius = opts.radius ?? 250.0;
  const startAz = opts.startAzimuthDeg ?? 0.0;
  const endAz = opts.endAzimuthDeg ?? 360.0;
  const elevationDeg = opts.elevationDeg ?? 10.0;
  const targetOffsetCm = opts.targetOffsetCm ?? SHOT_SIZES.medium[1];
  const ln = lensOf(opts.lens, "move");
  const id = opts.id ?? shotName("arc", subject);
  if (opts.stepDeg !== undefined && opts.stepDeg !== null) {
    if (opts.stepDeg <= 0) throw new Error("step_deg must be > 0");
    if (end <= start) throw new Error("end must be > start");
    const target = resolvePure(subject, opts.positions, targetOffsetCm);
    const span = endAz - startAz;
    const n = Math.max(1, Math.ceil(Math.abs(span) / opts.stepDeg));
    const frames = [...new Set(Array.from({ length: n + 1 }, (_, i) => start + roundHalfEven(((end - start) * i) / n)))].sort((x, y) => x - y);
    const keys = frames.map((f) => {
      const t = (f - start) / (end - start);
      return new CameraKeyframe({ frame: f, position: sphericalOffset(target, startAz + span * t, elevationDeg, radius), lookAt: target });
    });
    return new Shot({
      id,
      camera: new Placement({ position: keys[0].position, lookAt: target }),
      lens: ln,
      movement: new Keyframed({ keyframes: keys }),
      frameRange: [start, end],
    });
  }
  return new Shot({
    id,
    camera: new Framing({ subjects: [subject] }),
    lens: ln,
    movement: new Orbit({ radius, elevationDeg, startAzimuthDeg: startAz, endAzimuthDeg: endAz, frameStart: start, frameEnd: end, targetOffsetCm }),
    frameRange: [start, end],
  });
}

// ---- focus ----------------------------------------------------------------

/** An actor key (focus on the eyes), a point, or a focal distance (cm). */
export type FocusTarget = string | Vec3 | number;

/** Where to focus on `target`: an actor key's eyes, or a point as given. */
export function focusPoint(target: string | Vec3, positions?: Positions, eyeHeight = EYE_HEIGHT_CM): Vec3 {
  if (typeof target === "string") {
    if (!positions) throw new Error(`focus target '${target}' is a key but no positions were given`);
    return eye(posOf(positions, target), eyeHeight);
  }
  return target;
}

export interface RackFocusOptions {
  start: number;
  end: number;
  positions?: Positions;
  /** Frames to hold on `from` before the pull starts. */
  holdFrom?: number;
  /** Frames to hold on `to` after the pull ends. */
  holdTo?: number;
  eyeHeight?: number;
}

/**
 * A rack focus from `from` to `to` between `start` and `end`. The pull runs
 * from `start + holdFrom` to `end - holdTo`; a hold that leaves no time to
 * pull is dropped.
 */
export function rackFocus(cameraPos: Vec3, from: FocusTarget, to: FocusTarget, opts: RackFocusOptions): FocusPull {
  const { start, end } = opts;
  if (end <= start) throw new Error("end must be > start");
  const dist = (t: FocusTarget) =>
    typeof t === "number" ? t : Math.max(1.0, cameraPos.distance(focusPoint(t, opts.positions, opts.eyeHeight ?? EYE_HEIGHT_CM)));
  const d0 = dist(from);
  const d1 = dist(to);
  let pullStart = start + Math.max(0, opts.holdFrom ?? 0);
  let pullEnd = end - Math.max(0, opts.holdTo ?? 0);
  if (pullStart >= pullEnd) [pullStart, pullEnd] = [start, end];
  const keys = [new FocusKey(start, d0)];
  if (pullStart > start) keys.push(new FocusKey(pullStart, d0));
  keys.push(new FocusKey(pullEnd, d1));
  if (pullEnd < end) keys.push(new FocusKey(end, d1));
  return new FocusPull({ keys });
}

/** Circle of confusion (mm) for a 36 mm-wide frame -- the usual full-frame value. */
export const CIRCLE_OF_CONFUSION_MM = 0.03;

/**
 * `[near, far]` limits of acceptable sharpness (cm) for a lens focused at
 * `focalDistance` (cm). Thin-lens hyperfocal approximation; `far` is `null`
 * (infinity) at or beyond the hyperfocal distance.
 */
export function depthOfFieldLimits(focalLength: number, fStop: number, focalDistance: number, cocMm = CIRCLE_OF_CONFUSION_MM): [number, number | null] {
  if (focalLength <= 0 || fStop <= 0 || focalDistance <= 0) throw new Error("focal_length, f_stop and focal_distance must be > 0");
  const f = focalLength;
  const s = focalDistance * 10.0; // mm
  const hyperfocal = (f * f) / (fStop * cocMm) + f;
  const near = (hyperfocal * s) / (hyperfocal + (s - f));
  const far = s >= hyperfocal ? null : (hyperfocal * s) / (hyperfocal - (s - f));
  return [near / 10.0, far === null ? null : far / 10.0];
}

/** Where `shot`'s camera stands (its first position, for a move). */
export function cameraPosition(shot: Shot, positions?: Positions, geo: FrameGeometry = {}): Vec3 {
  return cameraPositions(shot, positions, geo)[0];
}

/** `shot` with a {@link rackFocus} measured from its camera position, depth of field on. */
export function withRackFocus(shot: Shot, from: FocusTarget, to: FocusTarget, opts: RackFocusOptions & { fStop?: number | null }): Shot {
  const pull = rackFocus(cameraPosition(shot, opts.positions), from, to, opts);
  const lens = shot.lens.with({ depthOfField: true, fStop: opts.fStop ?? shot.lens.fStop });
  return shot.with({ focus: pull, lens });
}

// ---- continuity -----------------------------------------------------------

function resolvePure(t: Target, positions: Positions | undefined, offset: number): Vec3 {
  if (typeof t === "string") {
    if (!positions) throw new Error(`target '${t}' is a key but no positions were given`);
    const p = posOf(positions, t);
    return new Vec3(p.x, p.y + offset, p.z);
  }
  if (t instanceof Vec3) return offset ? new Vec3(t.x, t.y + offset, t.z) : t;
  if (isNodeTarget(t)) throw new Error("live DazNode targets aren't supported here; pass actor keys with a positions mapping");
  throw new Error("target must be an actor key or a Vec3");
}

function framingPose(f: Framing, focalLength: number, positions: Positions | undefined, geo: FrameGeometry): [Vec3, Vec3] {
  const points = f.subjects.map((s) => [resolvePure(s, positions, 0.0), !(s instanceof Vec3)] as const);
  return framingTransform(points, f, focalLength, geo);
}

/**
 * Every position `shot`'s camera passes through: one for a static shot, each
 * waypoint of a {@link Keyframed} move, samples along an {@link Orbit}.
 */
export function cameraPositions(shot: Shot, positions?: Positions, geo: FrameGeometry & { orbitStepDeg?: number } = {}): Vec3[] {
  const m = shot.movement;
  const c = shot.camera;
  if (m instanceof Keyframed) return m.keyframes.map((kf) => kf.position);
  if (m instanceof Orbit) {
    const targetRef = c instanceof Framing ? c.subjects[0] : c.lookAt;
    if (targetRef === null) throw new Error(`shot '${shot.id}': an Orbit needs a target`);
    const target = resolvePure(targetRef, positions, m.targetOffsetCm);
    const span = m.endAzimuthDeg - m.startAzimuthDeg;
    const n = Math.max(1, Math.ceil(Math.abs(span) / (geo.orbitStepDeg ?? 10.0)));
    return Array.from({ length: n + 1 }, (_, i) => sphericalOffset(target, m.startAzimuthDeg + (span * i) / n, m.elevationDeg, m.radius));
  }
  if (c instanceof Framing) return [framingPose(c, shot.lens.focalLength, positions, geo)[0]];
  return [c.position];
}

function staticPose(shot: Shot, positions: Positions | undefined, geo: FrameGeometry): [Vec3, Vec3] | null {
  if (shot.movement !== null) return null;
  const c = shot.camera;
  if (c instanceof Framing) return framingPose(c, shot.lens.focalLength, positions, geo);
  if (c.lookAt !== null) return [c.position, resolvePure(c.lookAt, positions, c.lookAtOffsetCm)];
  if (c.rotation !== null) return [c.position, aimFromRotation(c.position, c.rotation)];
  return null;
}

export type ContinuityKind = "axis" | "thirty_degree";

/**
 * A continuity problem: `kind` is `"axis"` (a camera crosses the line of
 * action) or `"thirty_degree"` (a jump cut between near-identical setups).
 */
export class ContinuityIssue {
  constructor(
    readonly kind: ContinuityKind,
    readonly shotId: string,
    readonly message: string,
    readonly otherShotId: string | null = null,
  ) {
    Object.freeze(this);
  }
}

/**
 * Shots whose camera stands (or moves) on the wrong side of `line`. A camera
 * on the line itself (a neutral shot) is allowed.
 */
export function checkAxis(
  shots: Iterable<Shot>,
  line: LineOfAction,
  positions?: Positions,
  opts: FrameGeometry & { toleranceCm?: number } = {},
): ContinuityIssue[] {
  const issues: ContinuityIssue[] = [];
  for (const shot of shots) {
    const sides = new Set(cameraPositions(shot, positions, opts).map((p) => line.sideOf(p, opts.toleranceCm ?? 1.0)));
    if (sides.has(-line.side as -1 | 1)) {
      sides.delete(0);
      const moving = shot.movement !== null && sides.size > 1;
      const what = moving ? "moves across" : "is on the wrong side of";
      issues.push(new ContinuityIssue("axis", shot.id, `camera ${what} the ${line.a}-${line.b} line of action`));
    }
  }
  return issues;
}

export interface ThirtyDegreeOptions extends FrameGeometry {
  /** Minimum camera-angle change between cuts. Defaults to `30`. */
  minAngleDeg?: number;
  /** Aim points within this distance count as the same subject. Defaults to `50`. */
  sameSubjectCm?: number;
  /** Camera distances differing by less than this factor count as the same size. Defaults to `1.33`. */
  sizeRatio?: number;
}

/**
 * Consecutive static shots (in cut order) of the same subject whose camera
 * angle changes by less than `minAngleDeg` without a clear size change -- a
 * jump cut.
 */
export function checkThirtyDegree(shots: readonly Shot[], positions?: Positions, opts: ThirtyDegreeOptions = {}): ContinuityIssue[] {
  const minAngle = opts.minAngleDeg ?? 30.0;
  const sameSubject = opts.sameSubjectCm ?? 50.0;
  const sizeRatio = opts.sizeRatio ?? 1.33;
  const poses = shots.map((s) => staticPose(s, positions, opts));
  const issues: ContinuityIssue[] = [];
  for (let i = 1; i < shots.length; i++) {
    const p0 = poses[i - 1];
    const p1 = poses[i];
    if (p0 === null || p1 === null || p0[1].distance(p1[1]) > sameSubject) continue;
    const v0 = p0[0].sub(p0[1]);
    const v1 = p1[0].sub(p1[1]);
    const d0 = v0.length();
    const d1 = v1.length();
    if (d0 < 1e-6 || d1 < 1e-6 || Math.max(d0, d1) / Math.min(d0, d1) >= sizeRatio) continue;
    const angle = Math.acos(Math.max(-1.0, Math.min(1.0, v0.dot(v1) / (d0 * d1)))) / DEG;
    if (angle < minAngle) {
      issues.push(new ContinuityIssue(
        "thirty_degree",
        shots[i].id,
        `cut from '${shots[i - 1].id}' moves the camera only ${angle.toFixed(0)} degrees at a similar size`,
        shots[i - 1].id,
      ));
    }
  }
  return issues;
}

/** {@link checkAxis} (when `line` is given) plus {@link checkThirtyDegree}, in cut order. */
export function checkContinuity(
  shots: Iterable<Shot>,
  positions?: Positions,
  opts: ThirtyDegreeOptions & { line?: LineOfAction | null } = {},
): ContinuityIssue[] {
  const list = [...shots];
  const { line, ...rest } = opts;
  const geo = { frameWidthMm: opts.frameWidthMm, aspect: opts.aspect };
  const issues = line ? checkAxis(list, line, positions, geo) : [];
  return issues.concat(checkThirtyDegree(list, positions, rest));
}

/** The plan's line of action, its side taken from the first shot that is off the line. */
export function planLine(plan: CoveragePlan, positions: Positions, geo: FrameGeometry = {}): LineOfAction | null {
  if (plan.axis === null) return null;
  const line = LineOfAction.between(positions, plan.axis[0], plan.axis[1]);
  for (const shot of plan.allShots()) {
    for (const p of cameraPositions(shot, positions, geo)) {
      const s = line.sideOf(p);
      if (s) return line.withSide(s);
    }
  }
  return line;
}

/** {@link checkContinuity} for every sequence of `plan`, against the plan's axis. */
export function checkPlan(plan: CoveragePlan, positions: Positions, opts: ThirtyDegreeOptions = {}): ContinuityIssue[] {
  const line = planLine(plan, positions, opts);
  return plan.sequences.flatMap((seq) => checkContinuity(seq.shots, positions, { ...opts, line }));
}

// ---- coverage -------------------------------------------------------------

/** One {@link subjectCoverage} preset entry: `[kind tag, size, angle, azimuth offset deg, lens mm]`. */
export type CoveragePresetShot = readonly [string | null, ShotSize, CameraAngle, number, number];

/** {@link subjectCoverage} presets. */
export const COVERAGE_PRESETS: Readonly<Record<string, readonly CoveragePresetShot[]>> = Object.freeze({
  standard: [[null, "wide", "eye_level", 0.0, 35.0], [null, "medium", "eye_level", 0.0, 50.0], [null, "close_up", "eye_level", 0.0, 85.0]],
  interview: [[null, "medium", "eye_level", 0.0, 50.0], ["left", "medium_close_up", "eye_level", -30.0, 85.0], ["right", "medium_close_up", "eye_level", 30.0, 85.0]],
  dramatic: [[null, "wide", "eye_level", 0.0, 35.0], ["low", "medium", "low", 0.0, 50.0], ["high", "medium", "high", 0.0, 50.0], ["profile", "medium_close_up", "eye_level", 90.0, 85.0]],
  action: [[null, "wide", "eye_level", 0.0, 28.0], [null, "medium", "eye_level", 0.0, 50.0], ["three-quarter", "medium_wide", "eye_level", -45.0, 35.0], ["hero", "medium", "low", 0.0, 35.0]],
});

/** Single-actor coverage from {@link COVERAGE_PRESETS}, around `azimuthDeg` (0 = the actor's `+Z` side). */
export function subjectCoverage(subject: string, opts: { preset?: string; azimuthDeg?: number; planId?: string; headroom?: boolean } = {}): CoveragePlan {
  const preset = opts.preset ?? "standard";
  const entries = COVERAGE_PRESETS[preset];
  if (!entries) throw new Error(`unknown coverage preset '${preset}'; valid: ${Object.keys(COVERAGE_PRESETS).join(", ")}`);
  const az = opts.azimuthDeg ?? 0.0;
  const shots = entries.map(([tag, size, angle, offset, mm]) =>
    new Shot({
      id: shotName(size, subject, null, { tag }),
      camera: new Framing({ subjects: [subject], size, angle, azimuthDeg: az + offset, anchorCm: opts.headroom ? headroomAnchor(size) : null }),
      lens: new Lens({ focalLength: mm }),
    }),
  );
  const pid = opts.planId ?? `${slug(subject)}_${preset}`;
  return new CoveragePlan({ id: pid, subjects: [subject], sequences: [new Sequence({ id: pid, shots })] });
}

export type DialoguePart = "master" | "two_shot" | "ots" | "singles";

/**
 * Standard two-actor coverage on one side of `line`: master, two-shot, the
 * OTS shot/reverse pair and the clean singles (pick with `include`).
 */
export function dialogueCoverage(
  line: LineOfAction,
  opts: FrameGeometry & { planId?: string; include?: Iterable<DialoguePart>; singleSize?: ShotSize } = {},
): CoveragePlan {
  const include = [...(opts.include ?? ["master", "two_shot", "ots", "singles"])];
  const known = ["master", "two_shot", "ots", "singles"];
  const unknown = [...new Set(include.filter((p) => !known.includes(p)))].sort();
  if (unknown.length) throw new Error(`unknown coverage part(s): [${unknown.map((u) => `'${u}'`).join(", ")}]`);
  const geo: FrameGeometry = { frameWidthMm: opts.frameWidthMm, aspect: opts.aspect };
  const singleSize = opts.singleSize ?? "close_up";
  const shots: Shot[] = [];
  if (include.includes("master")) shots.push(master(line, geo));
  if (include.includes("two_shot")) shots.push(twoShot(line, geo));
  if (include.includes("ots")) shots.push(...shotReverseShot(line, { frameWidthMm: opts.frameWidthMm }));
  if (include.includes("singles")) shots.push(single(line, line.a, { size: singleSize }), single(line, line.b, { size: singleSize }));
  const pid = opts.planId ?? `${slug(line.a)}_${slug(line.b)}_dialogue`;
  return new CoveragePlan({ id: pid, subjects: [line.a, line.b], axis: [line.a, line.b], sequences: [new Sequence({ id: pid, shots })] });
}

/** `speaker` talks from frame `start` to `end` (inclusive); `line` is the dialogue text. */
export class DialogueBeat {
  readonly speaker: string;
  readonly start: number;
  readonly end: number;
  readonly line: string | null;

  constructor(speaker: string, start: number, end: number, line: string | null = null) {
    if (end < start) throw new Error("DialogueBeat.end must be >= start");
    this.speaker = speaker;
    this.start = start;
    this.end = end;
    this.line = line;
    Object.freeze(this);
  }
}

export interface ConversationOptions extends FrameGeometry {
  planId?: string;
  /** `"ots"` (over the listener's shoulder, the default) or `"singles"`. */
  style?: "ots" | "singles";
  /** When > 0, open on a master for this many frames at the start of the first beat. */
  establishFrames?: number;
  singleSize?: ShotSize;
  lens?: LensSpec;
}

/**
 * Cut a conversation between the line's two actors, one shot per beat.
 *
 * Each beat is covered on the speaker -- over the listener's shoulder or in
 * a clean single -- from the same side of the line, so eyelines match across
 * the cuts. Every shot carries its frame range, gaze beats (speaker and
 * listener look at each other) and the dialogue as storyboard text.
 */
export function conversation(line: LineOfAction, beats: Iterable<DialogueBeat>, opts: ConversationOptions = {}): CoveragePlan {
  const style = opts.style ?? "ots";
  if (style !== "ots" && style !== "singles") throw new Error("style must be 'ots' or 'singles'");
  let list = [...beats];
  if (!list.length) throw new Error("a conversation needs at least one beat");
  list.forEach((b, i) => {
    if (b.speaker !== line.a && b.speaker !== line.b) throw new Error(`beat ${i}: speaker '${b.speaker}' is not '${line.a}' or '${line.b}'`);
    if (i && b.start <= list[i - 1].end) throw new Error(`beat ${i} starts at ${b.start}, before beat ${i - 1} ends (${list[i - 1].end})`);
  });
  const planId = opts.planId ?? "conversation";
  const singleSize = opts.singleSize ?? "medium_close_up";
  const geo: FrameGeometry = { frameWidthMm: opts.frameWidthMm, aspect: opts.aspect };
  const shots: Shot[] = [];
  const establishFrames = opts.establishFrames ?? 0;
  if (establishFrames > 0) {
    const first = list[0];
    const estEnd = Math.min(first.end, first.start + establishFrames - 1);
    shots.push(master(line, { ...geo, id: shotName("master", `${line.a}-${line.b}`, null, { index: 0 }), frameRange: [first.start, estEnd] }));
    list = estEnd >= first.end ? list.slice(1) : [new DialogueBeat(first.speaker, estEnd + 1, first.end, first.line), ...list.slice(1)];
  }
  list.forEach((b, i0) => {
    const i = i0 + 1;
    const listener = line.other(b.speaker);
    const range: FrameRange = [b.start, b.end];
    const s = style === "ots"
      ? overTheShoulder(line, listener, b.speaker, { lens: opts.lens, frameWidthMm: opts.frameWidthMm, frameRange: range, id: shotName("ots", b.speaker, listener, { index: i }) })
      : single(line, b.speaker, { size: singleSize, lens: opts.lens, frameRange: range, id: shotName(singleSize, b.speaker, null, { index: i }) });
    shots.push(s.with({
      gaze: [new GazeBeat(b.start, b.speaker, listener), new GazeBeat(b.start, listener, b.speaker)],
      storyboard: new Storyboard({ dialogue: b.line, beat: `${b.speaker} speaks` }),
    }));
  });
  return new CoveragePlan({ id: planId, subjects: [line.a, line.b], axis: [line.a, line.b], sequences: [new Sequence({ id: planId, shots })] });
}

// ---- apply ----------------------------------------------------------------

export interface ApplyCoverageOptions extends FrameGeometry {
  /** As for {@link applyShot} -- usually the same positions mapping the shots were built from. */
  subjects?: Subjects;
  /** Existing cameras to reuse, by shot id; others are created. */
  cameras?: Readonly<Record<string, DazCamera>> | ReadonlyMap<string, DazCamera>;
}

/**
 * Apply every shot of `plan` on its own camera, named and labelled after the
 * shot id. Returns `shot id -> camera` in plan order.
 */
export async function applyCoverage(scene: DazScene, plan: CoveragePlan | Iterable<Shot>, opts: ApplyCoverageOptions = {}): Promise<Map<string, DazCamera>> {
  const shots = plan instanceof CoveragePlan ? plan.allShots() : [...plan];
  const lookup = (id: string): DazCamera | undefined => {
    const c = opts.cameras;
    if (!c) return undefined;
    return c instanceof Map ? c.get(id) : (c as Readonly<Record<string, DazCamera>>)[id];
  };
  const out = new Map<string, DazCamera>();
  for (const shot of shots) {
    const existing = lookup(shot.id);
    let cam = existing;
    if (cam === undefined) {
      cam = await scene.createCamera(shot.id);
      await cam.setLabel(shot.id); // a scripted camera's label is empty on Studio 4
    }
    out.set(shot.id, await applyShot(scene, shot, { camera: cam, subjects: opts.subjects, frameWidthMm: opts.frameWidthMm, aspect: opts.aspect }));
  }
  return out;
}
