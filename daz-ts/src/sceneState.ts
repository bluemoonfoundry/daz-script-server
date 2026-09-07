/**
 * A full snapshot of scene state, suitable for a save/restore checkpoint.
 * Mirrors dazpy's `_scene_state.py`.
 */

import { DazBusyError } from "./exceptions.js";
import { DazPose, type DazPoseDict } from "./pose.js";
import { ScriptBuilder } from "./scriptBuilder.js";
import type { DazScene } from "./scene.js";
import type { DazSkeleton } from "./skeleton.js";

const TRANSFORM_KEYS = ["XTranslate", "YTranslate", "ZTranslate", "XRotate", "YRotate", "ZRotate", "Scale"];
const LIGHT_EXTRA_KEYS = ["Flux", "Shadow Softness", "Spread Angle"];
const DEFAULT_VERIFY_TOLERANCE = 0.05;
const DEFAULT_MAX_VERIFY_RETRIES = 2;
const FOLLOW_TARGET_RETRY_MAX_WAIT = 30.0;

function sleep(seconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, seconds * 1000));
}

/**
 * Run `fn`, retrying with backoff on {@link DazBusyError}.
 *
 * `followTarget()`/`fitTo()`/`unfit()` (unlike `DazPose.applyFull()`, which
 * takes its own retry-on-busy options) don't expose retry-on-busy directly,
 * but `apply()`'s follow-target restoration pass makes several of these
 * calls back-to-back per skeleton on top of the pose-restore/verify calls
 * already made for every skeleton in the scene -- under that load a single
 * skeleton's follow-target fix can transiently hit `StudioBusyError` even
 * though the overall restore succeeds for every other skeleton. This
 * mirrors `DazClient`'s internal busy-retry backoff without depending on it.
 */
async function retryOnBusy<T>(fn: () => Promise<T>, maxWait = FOLLOW_TARGET_RETRY_MAX_WAIT): Promise<T> {
  const deadline = Date.now() + maxWait * 1000;
  let backoff = 1.0;
  for (;;) {
    try {
      return await fn();
    } catch (e) {
      if (!(e instanceof DazBusyError)) {
        throw e;
      }
      const remainingMs = deadline - Date.now();
      if (remainingMs <= 0) {
        throw e;
      }
      await sleep(Math.min(backoff, remainingMs / 1000));
      backoff = Math.min(backoff + 1.0, 5.0);
    }
  }
}

const ZERO3: [number, number, number] = [0, 0, 0];

/**
 * Return a description of every channel where `actual` does not match
 * `expected` within `tolerance`, or an empty list if they match.
 *
 * Missing keys in either pose are treated as zero, matching {@link DazPose}'s
 * sparse (zero-omitted) storage.
 */
function poseMismatches(expected: DazPose, actual: DazPose, tolerance: number): string[] {
  const mismatches: string[] = [];

  for (const key of new Set([...Object.keys(expected.bones), ...Object.keys(actual.bones)])) {
    const exp = expected.bones[key] ?? ZERO3;
    const act = actual.bones[key] ?? ZERO3;
    if (exp.some((e, i) => Math.abs(e - act[i]) > tolerance)) {
      mismatches.push(`bone ${key} (expected ${JSON.stringify(exp)}, got ${JSON.stringify(act)})`);
    }
  }

  for (const key of new Set([...Object.keys(expected.morphs), ...Object.keys(actual.morphs)])) {
    const expV = expected.morphs[key] ?? 0.0;
    const actV = actual.morphs[key] ?? 0.0;
    if (Math.abs(expV - actV) > tolerance) {
      mismatches.push(`morph ${key} (expected ${expV}, got ${actV})`);
    }
  }

  for (const key of new Set([...Object.keys(expected.props), ...Object.keys(actual.props)])) {
    const expV = expected.props[key] ?? 0.0;
    const actV = actual.props[key] ?? 0.0;
    if (Math.abs(expV - actV) > tolerance) {
      mismatches.push(`prop ${key} (expected ${expV}, got ${actV})`);
    }
  }

  return mismatches;
}

// Shared JS snippet: read a property's own dial value rather than getValue()'s
// post-ERC computed total, for the same reason DazPose/DazProperty.rawValue
// do -- see DazPose.capture()'s comments for the full explanation.
const RAW_READ_JS = 'function _raw(p) { return (typeof p.getRawValue === "function") ? p.getRawValue() : p.getValue(); }';
const RAW_WRITE_JS =
  'function _rawSet(p, v) { ' +
  'if (typeof p.setRawValue === "function") { p.setRawValue(v); } else { p.setValue(v); } }';

/** Plain-object schema matching {@link DazSceneState.toDict}/{@link DazSceneState.fromDict}. */
export interface DazSceneStateDict {
  skeletons: Record<string, DazPoseDict>;
  cameras: Record<string, Record<string, number>>;
  lights: { transforms: Record<string, Record<string, number>>; extra: Record<string, Record<string, number>> };
  follow_targets: Record<string, string | null>;
}

/** Options for {@link DazSceneState.apply}. */
export interface ApplyOptions {
  /**
   * How many additional `applyFull` attempts to make for a skeleton whose
   * read-back doesn't verify, before giving up on it.
   */
  maxVerifyRetries?: number;
  /**
   * Per-channel tolerance (degrees for bones, raw value units for
   * morphs/props) allowed between the checkpoint and the read-back before
   * it's considered a mismatch.
   */
  verifyTolerance?: number;
}

/** Result of {@link DazSceneState.apply}. */
export interface ApplyResult {
  restored: string[];
  errors: string[];
}

/**
 * A full snapshot of scene state, suitable for a save/restore checkpoint.
 *
 * Captures every skeleton's complete pose (bone rotations, morphs, and
 * node-level properties -- see {@link DazPose}) plus transform and a handful
 * of key properties for every camera and light in the scene. Everything is
 * captured and restored via each property's raw (pre-ERC) value, so
 * repeated capture/apply cycles are idempotent even for properties driven
 * by `DzERCLink` controllers (e.g. a "Scale" dial fed by dozens of linked
 * morphs) -- see {@link DazPose} for why this matters.
 *
 * Skeletons, cameras, and lights are all keyed by their internal name (not
 * display label), since labels are user-editable and not guaranteed unique.
 *
 * Typical workflow:
 * ```ts
 * const scene = new DazScene();
 * const checkpoint = await DazSceneState.capture(scene);
 * // ...experimental changes
 * await checkpoint.apply(scene);
 * ```
 */
export class DazSceneState {
  readonly skeletonPoses: Record<string, DazPose>;
  readonly cameraTransforms: Record<string, Record<string, number>>;
  readonly lightTransforms: Record<string, Record<string, number>>;
  readonly lightExtra: Record<string, Record<string, number>>;
  /**
   * Each skeleton's conform/fit-to relationship (by target skeleton name,
   * or `null` if unfitted), captured and restored independently of
   * `DazPose`'s generic bones/morphs/props. `DazPose.applyFull()` writes
   * back every property on a skeleton, including the internal "FID_<name>"
   * property DAZ Studio uses to persist a conforming item's fit
   * registration -- rewriting that property (even to the exact value
   * captured) desyncs the live `getFollowTarget()` pointer without raising
   * any error. See daz-script-server-jz0e: a dedicated capture/restore pass
   * via the real `getFollowTarget()`/`setFollowTarget()` API is the only
   * reliable fix.
   */
  readonly followTargets: Record<string, string | null>;

  constructor(
    skeletonPoses: Record<string, DazPose>,
    cameraTransforms: Record<string, Record<string, number>>,
    lightTransforms: Record<string, Record<string, number>>,
    lightExtra: Record<string, Record<string, number>>,
    followTargets: Record<string, string | null> = {},
  ) {
    this.skeletonPoses = skeletonPoses;
    this.cameraTransforms = cameraTransforms;
    this.lightTransforms = lightTransforms;
    this.lightExtra = lightExtra;
    this.followTargets = followTargets;
  }

  // ── construction ──────────────────────────────────────────────────────

  /** Capture the current state of every skeleton, camera, and light in `scene`. */
  static async capture(scene: DazScene): Promise<DazSceneState> {
    const client = scene.getClient();
    const skeletonPoses: Record<string, DazPose> = {};
    const followTargets: Record<string, string | null> = {};
    for (const skel of await scene.skeletons()) {
      const name = skel.identifier.value;
      skeletonPoses[name] = await DazPose.capture(skel);
      const target = await skel.followTarget();
      followTargets[name] = target !== null ? target.identifier.value : null;
    }

    const camScript = ScriptBuilder.iife(`
            var _keys = ${JSON.stringify(TRANSFORM_KEYS)};
            ${RAW_READ_JS}
            function _captureTransforms(node) {
                var t = {};
                for (var i = 0; i < _keys.length; i++) {
                    var p = node.findProperty(_keys[i]);
                    if (p) t[_keys[i]] = _raw(p);
                }
                return t;
            }
            var result = {};
            for (var i = 0; i < Scene.getNumCameras(); i++) {
                var c = Scene.getCamera(i);
                result[c.getName()] = _captureTransforms(c);
            }
            return result;
        `);
    const cameraTransforms = ((await client.execute(camScript)).value as Record<string, Record<string, number>>) ?? {};

    const lightScript = ScriptBuilder.iife(`
            var _keys = ${JSON.stringify(TRANSFORM_KEYS)};
            var _extraKeys = ${JSON.stringify(LIGHT_EXTRA_KEYS)};
            ${RAW_READ_JS}
            function _captureTransforms(node) {
                var t = {};
                for (var i = 0; i < _keys.length; i++) {
                    var p = node.findProperty(_keys[i]);
                    if (p) t[_keys[i]] = _raw(p);
                }
                return t;
            }
            var transforms = {};
            var extra = {};
            for (var i = 0; i < Scene.getNumLights(); i++) {
                var l = Scene.getLight(i);
                var name = l.getName();
                transforms[name] = _captureTransforms(l);
                var e = {};
                for (var k = 0; k < _extraKeys.length; k++) {
                    var p = l.findProperty(_extraKeys[k]);
                    if (p) e[_extraKeys[k]] = _raw(p);
                }
                extra[name] = e;
            }
            return {transforms: transforms, extra: extra};
        `);
    const lightResult = ((await client.execute(lightScript)).value as {
      transforms?: Record<string, Record<string, number>>;
      extra?: Record<string, Record<string, number>>;
    }) ?? {};

    return new DazSceneState(
      skeletonPoses,
      cameraTransforms,
      lightResult.transforms ?? {},
      lightResult.extra ?? {},
      followTargets,
    );
  }

  // ── serialisation ─────────────────────────────────────────────────────

  /** Return this snapshot as a plain, JSON-serialisable dict. */
  toDict(): DazSceneStateDict {
    return {
      skeletons: Object.fromEntries(Object.entries(this.skeletonPoses).map(([name, pose]) => [name, pose.toDict()])),
      cameras: this.cameraTransforms,
      lights: { transforms: this.lightTransforms, extra: this.lightExtra },
      follow_targets: this.followTargets,
    };
  }

  /** Reconstruct a snapshot from {@link toDict}'s output. */
  static fromDict(data: Partial<DazSceneStateDict>): DazSceneState {
    const skeletons: Record<string, DazPose> = {};
    for (const [name, p] of Object.entries(data.skeletons ?? {})) {
      skeletons[name] = new DazPose(name, p.bones ?? {}, p.morphs ?? {}, p.props ?? {});
    }
    const lights = data.lights ?? { transforms: {}, extra: {} };
    return new DazSceneState(
      skeletons,
      data.cameras ?? {},
      lights.transforms ?? {},
      lights.extra ?? {},
      data.follow_targets ?? {},
    );
  }

  // ── apply ─────────────────────────────────────────────────────────────

  /**
   * Apply this snapshot's skeleton poses, camera transforms, and light
   * properties back onto `scene` in a small, fixed number of HTTP calls.
   *
   * Nodes that no longer exist in the scene are skipped and reported in
   * `errors` rather than raising -- matching the behaviour of the
   * registered-script checkpoint this class replaces.
   *
   * Each skeleton restore is independently verified: after
   * `pose.applyFull(skel)` returns, a fresh {@link DazPose.capture} is taken
   * and compared against the checkpoint. This guards against `applyFull()`
   * reporting success for a restore DAZ Studio's single-threaded main loop
   * only partially executed under contention (see dpi-mxq) -- the HTTP call
   * can return normally even though some bone/morph/prop writes never
   * happened. A skeleton whose read-back doesn't match is retried
   * (re-running `applyFull` and re-verifying) up to `maxVerifyRetries`
   * times before being reported in `errors` instead of `restored`, so
   * callers never trust an unverified result.
   */
  async apply(scene: DazScene, opts: ApplyOptions = {}): Promise<ApplyResult> {
    const { maxVerifyRetries = DEFAULT_MAX_VERIFY_RETRIES, verifyTolerance = DEFAULT_VERIFY_TOLERANCE } = opts;
    const client = scene.getClient();
    const restored: string[] = [];
    const errors: string[] = [];
    const resolvedSkeletons: Record<string, DazSkeleton> = {};

    for (const [name, pose] of Object.entries(this.skeletonPoses)) {
      let skel: DazSkeleton;
      try {
        skel = await scene.findSkeleton(name);
        resolvedSkeletons[name] = skel;
      } catch {
        errors.push(`Skeleton not found: ${name}`);
        continue;
      }

      let attempt = 0;
      let failed = false;
      let mismatches: string[] = [];
      for (;;) {
        try {
          await pose.applyFull(skel);
        } catch (exc) {
          errors.push(`Failed to restore skeleton ${name}: ${exc instanceof Error ? exc.message : String(exc)}`);
          failed = true;
          break;
        }

        let actual: DazPose;
        try {
          actual = await DazPose.capture(skel);
        } catch (exc) {
          errors.push(`Failed to verify restore of skeleton ${name}: ${exc instanceof Error ? exc.message : String(exc)}`);
          failed = true;
          break;
        }

        mismatches = poseMismatches(pose, actual, verifyTolerance);
        if (mismatches.length === 0 || attempt >= maxVerifyRetries) {
          break;
        }
        attempt += 1;
      }

      if (failed) {
        continue;
      }
      if (mismatches.length > 0) {
        errors.push(
          `Restore of skeleton ${name} did not verify after ${attempt + 1} attempt(s): ${mismatches.join("; ")}`,
        );
        continue;
      }
      restored.push(name);
    }

    // Restore each successfully-restored skeleton's conform/fit-to
    // relationship explicitly via the real getFollowTarget()/
    // setFollowTarget() API -- applyFull() above already wrote back this
    // skeleton's own "FID_*" property as part of its generic props
    // restore, but doing so does not reliably re-resolve the live
    // follow-target pointer (see daz-script-server-jz0e). Only touches
    // skeletons whose current follow-target doesn't already match what was
    // captured, to avoid redundant calls.
    for (const name of restored) {
      const skel = resolvedSkeletons[name];
      const targetName = this.followTargets[name] ?? null;
      try {
        const current = await retryOnBusy(() => skel.followTarget());
        const currentName = current !== null ? current.identifier.value : null;
        if (currentName === targetName) {
          continue;
        }
        if (targetName === null) {
          await retryOnBusy(() => skel.unfit());
        } else {
          const targetSkel = resolvedSkeletons[targetName] ?? (await scene.findSkeleton(targetName));
          await retryOnBusy(() => skel.fitTo(targetSkel));
        }
      } catch (exc) {
        errors.push(`Failed to restore follow-target for skeleton ${name}: ${exc instanceof Error ? exc.message : String(exc)}`);
      }
    }

    const restoreScript = ScriptBuilder.iife(`
            var _camTransforms = ${JSON.stringify(this.cameraTransforms)};
            var _lightTransforms = ${JSON.stringify(this.lightTransforms)};
            var _lightExtra = ${JSON.stringify(this.lightExtra)};
            ${RAW_WRITE_JS}
            function _applyTransforms(node, transforms) {
                for (var key in transforms) {
                    var p = node.findProperty(key);
                    if (p) _rawSet(p, transforms[key]);
                }
            }
            var restored = [];
            var errors = [];

            for (var name in _camTransforms) {
                var c = Scene.findNode(name);
                if (!c) { errors.push("Camera not found: " + name); continue; }
                _applyTransforms(c, _camTransforms[name]);
                restored.push(name);
            }

            for (var lname in _lightTransforms) {
                var l = Scene.findNode(lname);
                if (!l) { errors.push("Light not found: " + lname); continue; }
                _applyTransforms(l, _lightTransforms[lname]);
                var extra = _lightExtra[lname] || {};
                for (var ek in extra) {
                    var ep = l.findProperty(ek);
                    if (ep) _rawSet(ep, extra[ek]);
                }
                restored.push(lname);
            }

            return {restored: restored, errors: errors};
        `);
    const nodeResult = ((await client.execute(restoreScript, undefined, {
      retryOnBusy: true,
      maxWait: FOLLOW_TARGET_RETRY_MAX_WAIT,
    })).value as { restored?: string[]; errors?: string[] }) ?? { restored: [], errors: [] };
    restored.push(...(nodeResult.restored ?? []));
    errors.push(...(nodeResult.errors ?? []));

    return { restored, errors };
  }

  // ── dunder ────────────────────────────────────────────────────────────

  toString(): string {
    return (
      `DazSceneState(skeletons=${Object.keys(this.skeletonPoses).length}, ` +
      `cameras=${Object.keys(this.cameraTransforms).length}, lights=${Object.keys(this.lightTransforms).length})`
    );
  }
}
