/**
 * Domain-level pose convenience wrappers built on the DazPose/DazNode/
 * DazSkeleton primitives. Mirrors dazpy's `poses.py`.
 */

import { DazPose } from "./pose.js";
import type { DazNode } from "./node.js";
import type { DazSkeleton } from "./skeleton.js";

/**
 * Apply `pose` to `skeleton` in a single HTTP call.
 *
 * @param pose A {@link DazPose} instance, or a path to a pose JSON file
 * (loaded via {@link DazPose.load} first).
 */
export async function applyPose(skeleton: DazSkeleton, pose: DazPose | string): Promise<void> {
  const resolved = typeof pose === "string" ? DazPose.load(pose) : pose;
  await resolved.apply(skeleton);
}

/**
 * Reset `node`'s local position and rotation to zero, and scale to 1.0.
 *
 * Works on any {@link DazNode} -- camera, prop, or figure root. Uses a
 * single DazScript evaluation via `DazNode.setTransform`.
 */
export async function resetTransforms(node: DazNode): Promise<void> {
  await node.setTransform({ position: [0.0, 0.0, 0.0], rotation: [0.0, 0.0, 0.0], scale: [1.0, 1.0, 1.0] });
}

/** Options for {@link zeroFigure}. */
export interface ZeroFigureOptions {
  /**
   * When `true`, node-level numeric properties are also zeroed, via
   * `DazPose.applyFull`. This is **opt-in**, not the default: `applyFull`
   * writes 0 for every property returned by the figure's node-property
   * enumeration that is *absent* from the pose it's given, and every other
   * caller passes a captured pose whose `props` already contains those
   * values. `zeroFigure` instead passes an empty `props`, so with
   * `includeProps: true` that "absent -> 0" fallback can drive built-in
   * transform-adjacent dials -- e.g. the figure's general Scale property
   * (see the DzERCLink comment in `pose.ts`'s `capture()`) -- to 0,
   * contradicting the "does not touch root transform" guarantee. Only pass
   * `true` if you know your rig doesn't route transforms through its
   * node-property list.
   *
   * The two modes also differ in how they write ERC-driven channels: the
   * `true` path goes through `DazPose.applyFull`, which prefers
   * `setRawValue()` writes to avoid double-applying `DzERCLink` controller
   * contributions. The `false` path uses `DazSkeleton.zeroBonesAndMorphs`,
   * which uses plain `setValue()` writes. On ERC-driven channels the two
   * modes can therefore leave the figure in different end states.
   */
  includeProps?: boolean;
}

/**
 * Drive every bone rotation and morph on `skeleton` to zero.
 *
 * The default (`includeProps: false`) is what guarantees this function
 * never touches the figure's root position/rotation/scale -- use
 * {@link resetTransforms} for that instead.
 */
export async function zeroFigure(skeleton: DazSkeleton, opts: ZeroFigureOptions = {}): Promise<void> {
  const { includeProps = false } = opts;
  if (includeProps) {
    const pose = new DazPose(skeleton.identifier.value, {}, {}, {});
    await pose.applyFull(skeleton);
    return;
  }
  await skeleton.zeroBonesAndMorphs();
}
