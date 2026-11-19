/**
 * Pure camera/lighting placement math shared by `cinematics.ts` and
 * `lighting.ts`. Mirrors dazpy's `_shot_geometry.py` exactly. No
 * DazScript/HTTP involved.
 */

import type { DazNode } from "./node.js";
import { Vec3 } from "./math3.js";

/**
 * Return a point `distance` away from `target`, at the given angles.
 *
 * `azimuthDeg=0, elevationDeg=0` sits on the target's `+Z` side. Increasing
 * `azimuthDeg` sweeps from `+Z` toward `+X`. `elevationDeg` tilts the offset
 * up toward `+Y`; at `elevationDeg=90` the result is directly above the
 * target regardless of azimuth.
 */
export function sphericalOffset(target: Vec3, azimuthDeg: number, elevationDeg: number, distance: number): Vec3 {
  const az = (azimuthDeg * Math.PI) / 180;
  const el = (elevationDeg * Math.PI) / 180;
  const horizontal = Math.cos(el);
  const direction = new Vec3(horizontal * Math.sin(az), Math.sin(el), horizontal * Math.cos(az));
  return target.add(direction.mul(distance));
}

/**
 * Return `(x, y, z)` world-space Euler degrees aiming `fromPos` at `toPos`.
 *
 * Suitable for passing directly to `DazNode.setRotation`. A node positioned
 * via {@link sphericalOffset} with `azimuthDeg=0, elevationDeg=0` and aimed
 * with this function at the same target gets rotation `(0, 0, 0)` -- i.e.
 * the unrotated rest pose is defined as facing `-Z`. Roll (`z`) is always
 * `0.0`.
 *
 * The yaw sign was confirmed empirically against a live DAZ Studio session
 * (see beads issue daz-script-server-bu86): a distant light rotated to
 * `y=+90` reports `DazLight.direction()` of `(-1, 0, ~0)`, matching this
 * function's convention.
 */
export function lookAtEuler(fromPos: Vec3, toPos: Vec3): [number, number, number] {
  const direction = toPos.sub(fromPos).normalize();
  const horizontalDist = Math.sqrt(direction.x * direction.x + direction.z * direction.z);
  const pitch = (Math.atan2(direction.y, horizontalDist) * 180) / Math.PI;
  const yaw = horizontalDist < 1e-9 ? 0.0 : (Math.atan2(-direction.x, -direction.z) * 180) / Math.PI;
  return [pitch, yaw, 0.0];
}

/**
 * Resolve `target` to a {@link Vec3}, raised by `verticalOffsetCm`.
 *
 * If `target` is already a {@link Vec3}, it is used as-is (before the
 * offset). If it's a `DazNode`, its `position()` is read and converted via
 * `Vec3.fromDict`.
 *
 * `verticalOffsetCm` is added to the resolved Y (DAZ Studio's up axis)
 * component. This exists primarily to compensate for the fact that a
 * figure's `DazNode.position` is generally its root/hip joint, not its
 * center of mass or head -- framing code that wants to aim higher (e.g.
 * chest/head height for a tight shot) passes a positive offset here rather
 * than aiming straight at the hip.
 *
 * @throws Error If `target` is a node and its position is unavailable (e.g.
 * the node no longer exists in the scene).
 */
export async function resolveTarget(target: Vec3 | DazNode, verticalOffsetCm = 0.0): Promise<Vec3> {
  let base: Vec3;
  if (target instanceof Vec3) {
    base = target;
  } else {
    const position = await target.position();
    if (position === null) {
      throw new Error("resolveTarget: target node has no position (it may not exist in the scene)");
    }
    base = Vec3.fromDict(position);
  }
  if (verticalOffsetCm === 0.0) {
    return base;
  }
  return new Vec3(base.x, base.y + verticalOffsetCm, base.z);
}
