/**
 * An in-memory pose checkpoint: figure poses plus camera and light placement.
 * Mirrors dazpy's `_scene_state.py`.
 */

import { DazBusyError, NodeNotFoundError } from "./exceptions.js";
import { DazPose, type DazPoseDict } from "./pose.js";
import { ScriptBuilder } from "./scriptBuilder.js";
import type { DazScene } from "./scene.js";
import type { DazSkeleton } from "./skeleton.js";
import { sleep } from "./sleep.js";

const TRANSFORM_KEYS = ["XTranslate", "YTranslate", "ZTranslate", "XRotate", "YRotate", "ZRotate", "Scale"];
const LIGHT_EXTRA_KEYS = ["Flux", "Shadow Softness", "Spread Angle"];
const DEFAULT_VERIFY_TOLERANCE = 0.05;
const DEFAULT_MAX_VERIFY_RETRIES = 2;
const FOLLOW_TARGET_RETRY_MAX_WAIT = 30.0;

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
      await sleep(Math.min(backoff * 1000, remainingMs));
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
  backup?: Record<string, unknown> | null;
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

/** Options for {@link DazSceneState.capture}. */
export interface CaptureOptions {
  /**
   * If given, first write a full-scene backup to this absolute path on the
   * server host via {@link DazScene.saveCopy}, before anything else is
   * captured. Use it before destructive work (deleting nodes, changing
   * materials or render settings), which this checkpoint cannot undo. The
   * save-copy result is kept in {@link DazSceneState.backup} and reported
   * again by {@link DazSceneState.apply}. If the backup fails, the error is
   * thrown and nothing is captured.
   */
  backupPath?: string;
}

/** A node in the checkpoint that no longer exists in the scene. */
export interface SkippedNode {
  /**
   * `follow_target` means the skeleton was restored but the figure it was
   * fitted to is gone, so the fit was not restored.
   */
  kind: "skeleton" | "camera" | "light" | "follow_target";
  name: string;
  reason: "not_found";
}

/** Verification report returned by {@link DazSceneState.apply}. */
export interface ApplyResult {
  /** Names applied (skeletons read back and verified). */
  restored: string[];
  /** Nodes no longer in the scene. Each also has a line in `errors`. */
  skipped: SkippedNode[];
  /** Every problem, skips included. */
  errors: string[];
  /** `true` only if nothing was skipped or failed. */
  complete: boolean;
  /** `saveCopy()` result from `capture(scene, { backupPath })`, or `null`. */
  backup: Record<string, unknown> | null;
}

/**
 * An in-memory pose checkpoint: figure poses plus camera and light placement.
 *
 * This is not a full scene snapshot. For anything it does not cover, take a
 * full-scene backup with {@link DazScene.saveCopy}, or pass `backupPath` to
 * {@link DazSceneState.capture} to do both at once.
 *
 * Captured, for nodes that exist at capture time:
 *
 * - every skeleton (figure): bone rotations, morph values and the figure
 *   node's own numeric properties (see {@link DazPose});
 * - every skeleton's fit-to (follow) target;
 * - every camera: X/Y/Z translate, X/Y/Z rotate and Scale;
 * - every light: the same transform channels, plus Flux, Shadow Softness and
 *   Spread Angle.
 *
 * Not captured:
 *
 * - materials and surface properties;
 * - HDRI / environment and render settings;
 * - nodes added or deleted after capture (restore never creates or deletes
 *   nodes; missing ones are reported as skipped);
 * - props and any other node that is not a skeleton, camera or light;
 * - bone translations, keyframes / animation, and any other camera or light
 *   property (focal length, color, etc.).
 *
 * Everything is captured and restored via each property's raw (pre-ERC) value, so
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
  /**
   * Result of the {@link DazScene.saveCopy} call made by
   * `capture(scene, { backupPath })`, or `null` if no full-scene backup was taken.
   */
  readonly backup: Record<string, unknown> | null;

  constructor(
    skeletonPoses: Record<string, DazPose>,
    cameraTransforms: Record<string, Record<string, number>>,
    lightTransforms: Record<string, Record<string, number>>,
    lightExtra: Record<string, Record<string, number>>,
    followTargets: Record<string, string | null> = {},
    backup: Record<string, unknown> | null = null,
  ) {
    this.skeletonPoses = skeletonPoses;
    this.cameraTransforms = cameraTransforms;
    this.lightTransforms = lightTransforms;
    this.lightExtra = lightExtra;
    this.followTargets = followTargets;
    this.backup = backup;
  }

  // ── construction ──────────────────────────────────────────────────────

  /** Capture the current state of every skeleton, camera, and light in `scene`. */
  static async capture(scene: DazScene, opts: CaptureOptions = {}): Promise<DazSceneState> {
    const backup = opts.backupPath !== undefined ? await scene.saveCopy(opts.backupPath) : null;

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
      backup,
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
      backup: this.backup,
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
      data.backup ?? null,
    );
  }

  // ── apply ─────────────────────────────────────────────────────────────

  /**
   * Apply this snapshot's skeleton poses, camera transforms, and light
   * properties back onto `scene` in a small, fixed number of HTTP calls.
   *
   * Restore is best effort. A skeleton, camera or light that no longer
   * exists in the scene (deleted or renamed since capture) is skipped and
   * listed in `skipped`, and the rest of the checkpoint is still applied.
   * Nothing is recreated: this restores values, not the scene graph. To get
   * deleted nodes back, reload the full-scene backup taken by
   * `capture(scene, { backupPath })`.
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
   *
   * Each skipped node also has a line in `errors`, so a caller that treats
   * any `errors` entry as a failed restore stays safe.
   */
  async apply(scene: DazScene, opts: ApplyOptions = {}): Promise<ApplyResult> {
    const { maxVerifyRetries = DEFAULT_MAX_VERIFY_RETRIES, verifyTolerance = DEFAULT_VERIFY_TOLERANCE } = opts;
    const client = scene.getClient();
    const restored: string[] = [];
    const skipped: SkippedNode[] = [];
    const errors: string[] = [];
    const resolvedSkeletons: Record<string, DazSkeleton> = {};

    const skip = (kind: SkippedNode["kind"], name: string, message: string): void => {
      skipped.push({ kind, name, reason: "not_found" });
      errors.push(message);
    };

    for (const [name, pose] of Object.entries(this.skeletonPoses)) {
      let skel: DazSkeleton;
      try {
        skel = await scene.findSkeleton(name);
        resolvedSkeletons[name] = skel;
      } catch (exc) {
        if (exc instanceof NodeNotFoundError) {
          skip("skeleton", name, `Skeleton not found: ${name}`);
        } else {
          errors.push(`Failed to look up skeleton ${name}: ${exc instanceof Error ? exc.message : String(exc)}`);
        }
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
          let targetSkel = resolvedSkeletons[targetName];
          if (targetSkel === undefined) {
            try {
              targetSkel = await scene.findSkeleton(targetName);
            } catch (exc) {
              if (!(exc instanceof NodeNotFoundError)) {
                throw exc;
              }
              skip(
                "follow_target",
                name,
                `Follow-target ${targetName} of skeleton ${name} not found; fit not restored`,
              );
              continue;
            }
          }
          const target = targetSkel;
          await retryOnBusy(() => skel.fitTo(target));
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
                    if (!transforms.hasOwnProperty(key)) continue;
                    var p = node.findProperty(key);
                    if (p) _rawSet(p, transforms[key]);
                }
            }
            var restored = [];
            var skipped = [];
            var errors = [];

            for (var name in _camTransforms) {
                if (!_camTransforms.hasOwnProperty(name)) continue;
                var c = Scene.findNode(name);
                if (!c) {
                    skipped.push({kind: "camera", name: name, reason: "not_found"});
                    errors.push("Camera not found: " + name);
                    continue;
                }
                _applyTransforms(c, _camTransforms[name]);
                restored.push(name);
            }

            for (var lname in _lightTransforms) {
                if (!_lightTransforms.hasOwnProperty(lname)) continue;
                var l = Scene.findNode(lname);
                if (!l) {
                    skipped.push({kind: "light", name: lname, reason: "not_found"});
                    errors.push("Light not found: " + lname);
                    continue;
                }
                _applyTransforms(l, _lightTransforms[lname]);
                var extra = _lightExtra[lname] || {};
                for (var ek in extra) {
                    if (!extra.hasOwnProperty(ek)) continue;
                    var ep = l.findProperty(ek);
                    if (ep) _rawSet(ep, extra[ek]);
                }
                restored.push(lname);
            }

            return {restored: restored, skipped: skipped, errors: errors};
        `);
    const nodeResult = ((await client.execute(restoreScript, undefined, {
      retryOnBusy: true,
      maxWait: FOLLOW_TARGET_RETRY_MAX_WAIT,
    })).value as { restored?: string[]; skipped?: SkippedNode[]; errors?: string[] }) ?? { restored: [], errors: [] };
    restored.push(...(nodeResult.restored ?? []));
    skipped.push(...(nodeResult.skipped ?? []));
    errors.push(...(nodeResult.errors ?? []));

    return { restored, skipped, errors, complete: errors.length === 0, backup: this.backup };
  }

  // ── dunder ────────────────────────────────────────────────────────────

  toString(): string {
    return (
      `DazSceneState(skeletons=${Object.keys(this.skeletonPoses).length}, ` +
      `cameras=${Object.keys(this.cameraTransforms).length}, lights=${Object.keys(this.lightTransforms).length})`
    );
  }
}
