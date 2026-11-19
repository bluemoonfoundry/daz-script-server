/**
 * Domain-level camera shot builders built on the DazCamera/DazScene
 * primitives. Mirrors dazpy's `cinematics.py`.
 *
 * Provides {@link applyStaticShot} for a single camera placement/framing,
 * {@link applyOrbitCamera} for a per-frame orbit sweep around a target,
 * {@link applyFrameSubject} for distance-preset framing of a subject, and
 * {@link applyAnimatedShot} for a camera move driven by real DAZ Studio
 * keyframes (`DazNode.setPositionAtFrame`/`setRotationAtFrame`) rather than
 * a per-frame setValue bake -- DAZ Studio interpolates between the given
 * waypoints itself.
 */

import { lookAtEuler, resolveTarget, sphericalOffset } from "./shotGeometry.js";
import { Vec3 } from "./math3.js";
import type { DazCamera } from "./camera.js";
import type { DazNode } from "./node.js";
import type { DazScene } from "./scene.js";

async function resolveCamera(scene: DazScene, camera: DazCamera | undefined, name: string | undefined): Promise<DazCamera> {
  if (camera !== undefined) {
    return camera;
  }
  return scene.createCamera(name);
}

/** A single camera placement and optics configuration. */
export interface CinematicStaticShot {
  /** World-space camera position. */
  position: Vec3;
  /**
   * Aim target passed to `DazCamera.aimAt`. A `DazNode` is resolved via its
   * `position()`, raised by `lookAtOffsetCm`. Omitted -> `rotation` (if
   * set) is used instead.
   */
  lookAt?: Vec3 | DazNode;
  /**
   * Vertical offset (cm) applied when resolving `lookAt` -- see
   * `resolveTarget`. Defaults to `0.0` since this API already takes an
   * explicit `position`/`lookAt` the caller fully controls.
   */
  lookAtOffsetCm?: number;
  /** Explicit `(x, y, z)` degrees passed to `DazNode.setRotation`. Ignored if `lookAt` is set. */
  rotation?: [number, number, number];
  /** Passed to `DazCamera.setFocalLength`. */
  focalLength?: number;
  /** Passed to `DazCamera.setDepthOfField`. */
  depthOfField?: boolean;
  /** Passed to `DazCamera.setFocalDistance` when set; otherwise DAZ's current value is untouched. */
  focalDistance?: number;
  /** Passed to `DazCamera.setAspectWidth` when set. */
  aspectWidth?: number;
  /** Passed to `DazCamera.setAspectHeight` when set. */
  aspectHeight?: number;
  /** Passed to `DazCamera.setPixelsWidth` when set. */
  pixelsWidth?: number;
  /** Passed to `DazCamera.setPixelsHeight` when set. */
  pixelsHeight?: number;
}

/** Options shared by every `apply*Shot`/`applyFrameSubject` call. */
export interface CameraTargetOptions {
  /** An existing `DazCamera` to reuse/mutate. Omit to create a new one via `scene.createCamera(name)`. */
  camera?: DazCamera;
  /** Optional name for a newly created camera. Ignored when `camera` is given. */
  name?: string;
}

/** Place and configure a camera for `shot` in a single HTTP-round-trip set. */
export async function applyStaticShot(scene: DazScene, shot: CinematicStaticShot, opts: CameraTargetOptions = {}): Promise<DazCamera> {
  const cam = await resolveCamera(scene, opts.camera, opts.name);
  await cam.setPosition(shot.position.x, shot.position.y, shot.position.z);
  if (shot.lookAt !== undefined) {
    const target = await resolveTarget(shot.lookAt, shot.lookAtOffsetCm ?? 0.0);
    await cam.aimAt(target.x, target.y, target.z);
  } else if (shot.rotation !== undefined) {
    await cam.setRotation(...shot.rotation);
  }
  await cam.setFocalLength(shot.focalLength ?? 50.0);
  await cam.setDepthOfField(shot.depthOfField ?? false);
  if (shot.focalDistance !== undefined) {
    await cam.setFocalDistance(shot.focalDistance);
  }
  if (shot.aspectWidth !== undefined) {
    await cam.setAspectWidth(shot.aspectWidth);
  }
  if (shot.aspectHeight !== undefined) {
    await cam.setAspectHeight(shot.aspectHeight);
  }
  if (shot.pixelsWidth !== undefined) {
    await cam.setPixelsWidth(shot.pixelsWidth);
  }
  if (shot.pixelsHeight !== undefined) {
    await cam.setPixelsHeight(shot.pixelsHeight);
  }
  return cam;
}

function lerp(start: number, end: number, t: number): number {
  return start + (end - start) * t;
}

/**
 * A camera sweeping around a target across a frame range.
 *
 * Writes a static per-frame placement at each timeline frame -- this is
 * **not** a real interpolated keyframe animation (see the module doc
 * comment). Whether the sweep persists as visible motion when scrubbing the
 * timeline afterward depends on DAZ Studio's key/animation mode at call
 * time; that's the caller's responsibility.
 */
export interface OrbitCamera {
  /** The point to orbit around, as a `Vec3` world position or a `DazNode` (its `position()`, raised by `targetOffsetCm`, is used). */
  target: Vec3 | DazNode;
  /** Orbit radius from the target, in DAZ Studio units (cm). */
  radius: number;
  /** Constant elevation angle throughout the orbit -- see `sphericalOffset`. Defaults to `15.0`. */
  elevationDeg?: number;
  /** Azimuth at `frameStart`. Defaults to `0.0`. */
  startAzimuthDeg?: number;
  /**
   * Azimuth at `frameEnd`. Azimuth is linearly interpolated between the two
   * across the frame range. Defaults to `360.0`, which gives `frameStart`
   * and `frameEnd` the same azimuth (a duplicate endpoint) -- callers
   * wanting a seamless loop should use e.g. `endAzimuthDeg: 356.0` or
   * `frameEnd: frameStart + 89` instead of a full 360.
   */
  endAzimuthDeg?: number;
  /** First timeline frame (inclusive). Defaults to `0`. */
  frameStart?: number;
  /** Last timeline frame (inclusive). Must be `>=` `frameStart`. Defaults to `90`. */
  frameEnd?: number;
  /** Passed to `DazCamera.setFocalLength` once, before the per-frame sweep. Defaults to `50.0`. */
  focalLength?: number;
  /**
   * Vertical offset (cm) applied when resolving `target` -- see
   * `resolveTarget`. Defaults to `25.0` (chest height) since a figure's
   * resolved position is generally its root/hip joint and a close orbit
   * radius aimed straight at it risks clipping the head.
   */
  targetOffsetCm?: number;
}

/**
 * Sweep a camera around `orbit.target` across its frame range.
 *
 * Side effects: this widens/sets the scene's animation range to
 * `[orbit.frameStart, orbit.frameEnd]` via `DazScene.setAnimRange` --
 * without this, DAZ Studio's `Scene.setFrame()` clamps to the scene's
 * existing animation range (typically 0-30 on a fresh scene), silently
 * overwriting later frames onto the clamped one. The scene's timeline frame
 * is also left parked at `orbit.frameEnd` when this function returns -- it
 * is not restored to whatever frame was current beforehand.
 *
 * @throws Error If `orbit.frameEnd` is less than `orbit.frameStart`.
 */
export async function applyOrbitCamera(scene: DazScene, orbit: OrbitCamera, opts: CameraTargetOptions = {}): Promise<DazCamera> {
  const frameStart = orbit.frameStart ?? 0;
  const frameEnd = orbit.frameEnd ?? 90;
  const elevationDeg = orbit.elevationDeg ?? 15.0;
  const startAzimuthDeg = orbit.startAzimuthDeg ?? 0.0;
  const endAzimuthDeg = orbit.endAzimuthDeg ?? 360.0;
  const focalLength = orbit.focalLength ?? 50.0;
  const targetOffsetCm = orbit.targetOffsetCm ?? 25.0;

  if (frameEnd < frameStart) {
    throw new Error(`OrbitCamera.frameEnd (${frameEnd}) must be >= frameStart (${frameStart})`);
  }
  const cam = await resolveCamera(scene, opts.camera, opts.name);
  await scene.setAnimRange(frameStart, frameEnd);
  const target = await resolveTarget(orbit.target, targetOffsetCm);
  await cam.setFocalLength(focalLength);
  const frameCount = frameEnd - frameStart;
  for (let frame = frameStart; frame <= frameEnd; frame++) {
    const t = frameCount > 0 ? (frame - frameStart) / frameCount : 0.0;
    const azimuth = lerp(startAzimuthDeg, endAzimuthDeg, t);
    const pos = sphericalOffset(target, azimuth, elevationDeg, orbit.radius);
    await scene.setFrame(frame);
    await cam.setPosition(pos.x, pos.y, pos.z);
    await cam.aimAt(target.x, target.y, target.z);
  }
  return cam;
}

const SHOT_DISTANCES: Record<string, number> = { close_up: 60.0, medium: 150.0, full_body: 300.0 };
const SHOT_TARGET_OFFSETS_CM: Record<string, number> = { close_up: 45.0, medium: 25.0, full_body: 0.0 };

/** A camera framing a subject at a named shot distance. */
export interface FrameSubject {
  /** The point to frame, as a `Vec3` world position or a `DazNode` (its `position()`, raised by `targetOffsetCm`, is used). */
  subject: Vec3 | DazNode;
  /** One of `"close_up"`, `"medium"`, `"full_body"` -- maps to a preset distance via a module-level table. Defaults to `"medium"`. */
  shotType?: "close_up" | "medium" | "full_body";
  /** Camera azimuth around the subject -- see `sphericalOffset`. Defaults to `0.0`. */
  azimuthDeg?: number;
  /** Camera elevation around the subject. Defaults to `10.0`. */
  elevationDeg?: number;
  /** Passed to `DazCamera.setFocalLength`. Defaults to `50.0`. */
  focalLength?: number;
  /**
   * Vertical offset (cm) applied when resolving `subject` -- see
   * `resolveTarget`. Omitted -> uses `shotType`'s entry in the target-offset
   * table (tighter shots aim higher, to compensate for a figure's resolved
   * position being its root/hip joint rather than chest/head height).
   */
  targetOffsetCm?: number;
}

/**
 * Place and aim a camera to frame `frame.subject` at its shot distance.
 *
 * @throws Error If `frame.shotType` is not one of `"close_up"`, `"medium"`, `"full_body"`.
 */
export async function applyFrameSubject(scene: DazScene, frame: FrameSubject, opts: CameraTargetOptions = {}): Promise<DazCamera> {
  const shotType = frame.shotType ?? "medium";
  if (!(shotType in SHOT_DISTANCES)) {
    throw new Error(`Invalid FrameSubject.shotType ${JSON.stringify(shotType)}; must be one of ${JSON.stringify(Object.keys(SHOT_DISTANCES).sort())}`);
  }
  const cam = await resolveCamera(scene, opts.camera, opts.name);
  const offset = frame.targetOffsetCm !== undefined ? frame.targetOffsetCm : SHOT_TARGET_OFFSETS_CM[shotType];
  const target = await resolveTarget(frame.subject, offset);
  const pos = sphericalOffset(target, frame.azimuthDeg ?? 0.0, frame.elevationDeg ?? 10.0, SHOT_DISTANCES[shotType]);
  await cam.setPosition(pos.x, pos.y, pos.z);
  await cam.aimAt(target.x, target.y, target.z);
  await cam.setFocalLength(frame.focalLength ?? 50.0);
  return cam;
}

/** A single waypoint in an animated camera move (see {@link CinematicAnimatedShot}). */
export interface CameraKeyframe {
  /** Timeline frame number for this waypoint. */
  frame: number;
  /** World-space camera position at `frame`. */
  position: Vec3;
  /** Aim target at `frame`, resolved the same way as `CinematicStaticShot.lookAt`. Omitted -> `rotation` (if set) is used instead. */
  lookAt?: Vec3 | DazNode;
  /** Vertical offset (cm) applied when resolving `lookAt` -- see `resolveTarget`. */
  lookAtOffsetCm?: number;
  /** Explicit `(x, y, z)` degrees for this waypoint. Ignored if `lookAt` is set. */
  rotation?: [number, number, number];
}

/**
 * A camera move driven by real DAZ Studio keyframes.
 *
 * Unlike {@link OrbitCamera} (which bakes a value on every timeline frame),
 * this writes one keyframe per {@link CameraKeyframe} waypoint and lets DAZ
 * Studio interpolate the frames in between via its own animation curves.
 */
export interface CinematicAnimatedShot {
  /**
   * The waypoints, in ascending, unique `frame` order (at least two). Either
   * every waypoint must specify an orientation (`lookAt` or `rotation`) or
   * none must -- a partial mix would leave the rotation curve keyed at only
   * some waypoints, holding a stale orientation between them.
   */
  keyframes: CameraKeyframe[];
  /** Passed to `DazCamera.setFocalLength` once, before the keyframes are written. Defaults to `50.0`. */
  focalLength?: number;
  /** Passed to `DazCamera.setDepthOfField` once. Defaults to `false`. */
  depthOfField?: boolean;
  /** Passed to `DazCamera.setFocalDistance` once, when set; otherwise DAZ's current value is untouched. */
  focalDistance?: number;
}

/**
 * Write `shot.keyframes` as real DAZ Studio keyframes on a camera.
 *
 * Side effects: clears any existing keys on the camera's position controls
 * (via `DazNode.clearPositionKeys`) before writing the new curve -- a
 * freshly created camera can already carry a default key from creation
 * time, which would otherwise distort interpolation/extrapolation around
 * the new keyframes. Rotation controls are cleared the same way, but only
 * if at least one keyframe specifies an orientation.
 *
 * @throws Error If fewer than two keyframes are given, if their `frame`
 * values are not strictly ascending, or if only some keyframes specify an
 * orientation (`lookAt`/`rotation`).
 */
export async function applyAnimatedShot(scene: DazScene, shot: CinematicAnimatedShot, opts: CameraTargetOptions = {}): Promise<DazCamera> {
  if (shot.keyframes.length < 2) {
    throw new Error("CinematicAnimatedShot.keyframes needs at least two waypoints");
  }
  const frames = shot.keyframes.map((kf) => kf.frame);
  const sorted = [...frames].sort((a, b) => a - b);
  const isStrictlyAscendingUnique = frames.every((f, i) => f === sorted[i]) && new Set(frames).size === frames.length;
  if (!isStrictlyAscendingUnique) {
    throw new Error("CinematicAnimatedShot.keyframes must have strictly ascending, unique frame numbers");
  }
  const hasOrientation = shot.keyframes.map((kf) => kf.lookAt !== undefined || kf.rotation !== undefined);
  const anyOriented = hasOrientation.some(Boolean);
  const allOriented = hasOrientation.every(Boolean);
  if (anyOriented && !allOriented) {
    throw new Error(
      "CinematicAnimatedShot.keyframes must either all specify an orientation (lookAt/rotation) or none of them should",
    );
  }

  const cam = await resolveCamera(scene, opts.camera, opts.name);
  await cam.setFocalLength(shot.focalLength ?? 50.0);
  await cam.setDepthOfField(shot.depthOfField ?? false);
  if (shot.focalDistance !== undefined) {
    await cam.setFocalDistance(shot.focalDistance);
  }

  await cam.clearPositionKeys();
  if (anyOriented) {
    await cam.clearRotationKeys();
  }

  for (const kf of shot.keyframes) {
    await cam.setPositionAtFrame(kf.frame, kf.position.x, kf.position.y, kf.position.z);
    if (kf.lookAt !== undefined) {
      const target = await resolveTarget(kf.lookAt, kf.lookAtOffsetCm ?? 0.0);
      const [x, y, z] = lookAtEuler(kf.position, target);
      await cam.setRotationAtFrame(kf.frame, x, y, z);
    } else if (kf.rotation !== undefined) {
      await cam.setRotationAtFrame(kf.frame, ...kf.rotation);
    }
  }
  return cam;
}
