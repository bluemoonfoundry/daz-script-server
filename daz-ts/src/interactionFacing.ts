// daz-ts/src/interactionFacing.ts

/**
 * Staging geometry: contact points, the facing planner, wrap paths and limb
 * reach. Mirrors dazpy's `_interaction_facing.py`. Depends on `rigProfile.ts`,
 * `interactionTargets.ts` and `interactionSolve.ts`; `interactionPlan.ts`
 * (which imports this module) is only imported as a type.
 */

import type { Vector3 } from "./rigProfile.js";
import {
  addVec3,
  ANCHOR_SURFACE_RADIUS,
  BoneProfile,
  FigureRigProfile,
  lengthVec3,
  lookupRigProfile,
  midpointVec3,
  ResolvedInteractionTarget,
  scaleVec3,
  sideFromName,
  subVec3,
} from "./rigProfile.js";
import { alignmentChainNames } from "./interactionSolve.js";
import { FootTarget, HandTarget, LookAtTarget } from "./interactionTargets.js";
import type { InteractionPlan } from "./interactionPlan.js";

// ── contact geometry ─────────────────────────────────────────────────────────

/** Root of the effector's alignment chain (shoulder for a hand, hip for a foot). */
function limbRootBone(profile: FigureRigProfile, effectorBone: string): string | null {
  const chain = profile.suggestPrimaryChain(effectorBone);
  const chainNames = chain !== null ? alignmentChainNames(profile, chain) : [];
  return chainNames.length > 0 ? chainNames[0] : null;
}

export function limbRootOffset(profile: FigureRigProfile, effectorBone: string): Vector3 | null {
  const root = limbRootBone(profile, effectorBone);
  return root !== null ? profile.boneOffset(root) : null;
}

/** Unit direction from a target joint toward the source limb root, horizontal when possible. */
function approachDirection(joint: Vector3, root: Vector3): Vector3 | null {
  const horizontal: Vector3 = [root[0] - joint[0], 0, root[2] - joint[2]];
  const flat = lengthVec3(horizontal);
  if (flat >= 1e-6) return scaleVec3(horizontal, 1 / flat);
  const full = subVec3(root, joint);
  const length = lengthVec3(full);
  return length >= 1e-6 ? scaleVec3(full, 1 / length) : null;
}

/** How far to move the source figure (staged at `sourcePosition`) away from `joint`. */
export function standoffShift(joint: Vector3, sourcePosition: Vector3, rootOffset: Vector3 | null, standoff: number): Vector3 {
  if (standoff <= 0) return [0, 0, 0];
  const root = rootOffset !== null ? addVec3(sourcePosition, rootOffset)! : sourcePosition;
  const direction = approachDirection(joint, root);
  return direction !== null ? scaleVec3(direction, standoff) : [0, 0, 0];
}

/**
 * Pull `target.targetPoint` back toward the source limb by
 * `target.surfaceStandoff`. The approach direction runs (horizontally, as
 * staging does) from the target joint to the root of the source limb's
 * alignment chain (shoulder for a hand, hip for a foot), at its staged
 * position, so the effector stops on the near side of the partner's body.
 * Falls back to the figure origin; returns the point unchanged when neither
 * position is known or they coincide.
 */
export function surfaceContactPoint(profile: FigureRigProfile, target: ResolvedInteractionTarget, sourceShift: Vector3 | null): Vector3 {
  const point = target.targetPoint!;
  const rootBone = limbRootBone(profile, target.boneName);
  let root: Vector3 | null = rootBone !== null ? profile.bone(rootBone).worldPosition : null;
  if (root === null && profile.figurePosition !== null) root = [profile.figurePosition[0], point[1], profile.figurePosition[2]];
  if (root === null) return point;
  if (sourceShift !== null) root = addVec3(root, sourceShift)!;
  return pullTowardRoot(point, root, target.surfaceStandoff);
}

/** `point` moved `standoff` toward `root` (horizontally when possible), never past the root: on overlapping figures that would aim behind the source. */
export function pullTowardRoot(point: Vector3, root: Vector3, standoff: number): Vector3 {
  if (standoff <= 0) return point;
  const direction = approachDirection(point, root);
  if (direction === null) return point;
  const reach = Math.min(standoff, lengthVec3(subVec3(root, point)));
  return addVec3(point, scaleVec3(direction, reach))!;
}

// ── facing ───────────────────────────────────────────────────────────────────

/** Fraction of an arm's reach a faced partner is staged to need: short of full extension, where IK steps stall. */
export const FACING_REACH_FRACTION = 0.85;
/** The same for a leg (kick): nearly extended, since a folded high kick is hard for the solver to find from a straight rest leg. */
export const FACING_FOOT_REACH_FRACTION = 0.95;
/** Closest two faced figures' origins are staged (cm): two torso radii plus clearance. */
export const FACING_MIN_SEPARATION = 2 * ANCHOR_SURFACE_RADIUS.spine + 6;
export const FACING_MAX_SEPARATION = 400;
/** A mutual hand-to-hand meeting point sits this fraction of the arm's reach below the shoulder joints (about navel height). */
const MEETING_DROP_FRACTION = 0.8;
/** Chain segments shorter than this (cm) are joint offsets (twist bones, etc.), not limb segments. */
const LIMB_SEGMENT_MIN_LENGTH = 2;

/** A partner figure turned to face another before staging. */
export interface FacingAssignment {
  /** The figure it faces (which keeps its own orientation). */
  anchor: string;
  /** Degrees added to the partner's Y rotation. */
  yawDegrees: number;
}

const FORWARD_ANCHOR_PAIRS: ReadonlyArray<readonly [string, string]> = [
  ["l_shoulder", "r_shoulder"],
  ["l_knee", "r_knee"],
  ["l_foot", "r_foot"],
];

export function anchorBoneOffset(profile: FigureRigProfile, anchorName: string): Vector3 | null {
  const anchor = profile.anchor(anchorName);
  return anchor === null ? null : profile.boneOffset(anchor.boneName);
}

/**
 * Horizontal unit vector a figure faces, from its left/right shoulders (then
 * knees, then feet): left minus right, crossed with up. A Genesis figure at
 * rest faces +Z. Null when no pair resolves.
 */
export function figureForward(profile: FigureRigProfile): Vector3 | null {
  for (const [left, right] of FORWARD_ANCHOR_PAIRS) {
    const l = anchorBoneOffset(profile, left);
    const r = anchorBoneOffset(profile, right);
    if (l === null || r === null) continue;
    const across: Vector3 = [l[0] - r[0], 0, l[2] - r[2]];
    const length = lengthVec3(across);
    if (length < 1e-6) continue;
    return [-across[2] / length, 0, across[0] / length];
  }
  return null;
}

/** Rotate `v` by `degrees` about +Y (right-handed: +90 turns +Z into +X), as a figure's Y rotation does. */
export function rotateAboutY(v: Vector3, degrees: number): Vector3 {
  const radians = (degrees * Math.PI) / 180;
  const c = Math.cos(radians);
  const s = Math.sin(radians);
  return [v[0] * c + v[2] * s, v[1], -v[0] * s + v[2] * c];
}

function yawOf(direction: Vector3): number {
  return (Math.atan2(direction[0], direction[2]) * 180) / Math.PI;
}

function wrapDegrees(degrees: number): number {
  const wrapped = ((((degrees + 180) % 360) + 360) % 360) - 180;
  return wrapped === -180 ? 180 : wrapped;
}

/** A copy of `profile` with the figure turned `degrees` about its origin: bone world positions (and, without a figure position, local offsets) rotated. */
export function rotateRigProfile(profile: FigureRigProfile, degrees: number): FigureRigProfile {
  const pivot = profile.figurePosition ?? [0, 0, 0];
  const turn = (p: Vector3 | null): Vector3 | null => (p === null ? null : addVec3(pivot, rotateAboutY(subVec3(p, pivot), degrees)));
  const bones = profile.bones.map((bone) =>
    BoneProfile.fromDict({
      ...bone.toDict(),
      worldPosition: turn(bone.worldPosition),
      localPosition: profile.figurePosition === null && bone.localPosition !== null ? rotateAboutY(bone.localPosition, degrees) : bone.localPosition,
    }),
  );
  return new FigureRigProfile({
    figureLabel: profile.figureLabel,
    family: profile.family,
    bones,
    metadata: { ...profile.metadata, facingYawDegrees: degrees },
    figurePosition: profile.figurePosition,
  });
}

/** Closer than this (cm, horizontally), a look-only partner faces back along its anchor's forward instead of toward its origin. */
const LOOK_TOWARD_MIN_DISTANCE = 1;

/**
 * Which figures to turn to face a partner. A pair qualifies when both have a
 * `LookAtTarget`. When a hand/foot target links them (the hug, kiss,
 * handshake and fight recipes) the partner turns to face back along its
 * anchor's forward and `buildPosePatch` stages it in front. Lookers no limb
 * target links (face_each_other) pair up in actor order and the partner just
 * turns in place toward its anchor. The pair's earlier actor (in
 * `plan.actors`) keeps its orientation; the other turns to face it. A figure
 * turns at most once.
 */
export function planFacing(plan: InteractionPlan, rigProfiles: Record<string, FigureRigProfile>): Record<string, FacingAssignment> {
  const lookers = new Set<FigureRigProfile>();
  for (const constraint of plan.constraints) {
    if (!(constraint instanceof LookAtTarget)) continue;
    const profile = lookupRigProfile(rigProfiles, constraint.figureLabel);
    if (profile !== null) lookers.add(profile);
  }
  const actorOrder = (label: string): number => {
    const profile = lookupRigProfile(rigProfiles, label);
    const index = plan.actors.findIndex((actor) => lookupRigProfile(rigProfiles, actor) === profile);
    return index < 0 ? Number.POSITIVE_INFINITY : index;
  };
  const facing: Record<string, FacingAssignment> = {};
  const involved = new Set<FigureRigProfile>();
  for (const constraint of plan.constraints) {
    if (!(constraint instanceof HandTarget || constraint instanceof FootTarget) || !constraint.targetFigure || !constraint.targetAnchor) continue;
    const source = lookupRigProfile(rigProfiles, constraint.figureLabel);
    const target = lookupRigProfile(rigProfiles, constraint.targetFigure);
    if (source === null || target === null || source === target || !lookers.has(source) || !lookers.has(target)) continue;
    const sourceFirst = actorOrder(constraint.figureLabel) <= actorOrder(constraint.targetFigure);
    const [anchorLabel, partnerLabel] = sourceFirst ? [constraint.figureLabel, constraint.targetFigure] : [constraint.targetFigure, constraint.figureLabel];
    const [anchorProfile, partnerProfile] = sourceFirst ? [source, target] : [target, source];
    if (involved.has(partnerProfile)) continue;
    const anchorForward = figureForward(anchorProfile);
    const partnerForward = figureForward(partnerProfile);
    if (anchorForward === null || partnerForward === null) continue;
    facing[partnerLabel] = { anchor: anchorLabel, yawDegrees: wrapDegrees(yawOf(scaleVec3(anchorForward, -1)) - yawOf(partnerForward)) };
    involved.add(partnerProfile);
    involved.add(anchorProfile);
  }

  // Look-only pairs (face_each_other): lookers no limb target links, paired
  // in actor order. Nothing stages them, so the partner turns in place toward
  // its anchor's origin (or, when the origins coincide, to face back along
  // the anchor's forward).
  const pending: Array<{ label: string; profile: FigureRigProfile }> = [];
  for (const actor of plan.actors) {
    const profile = lookupRigProfile(rigProfiles, actor);
    if (profile === null || !lookers.has(profile) || involved.has(profile) || pending.some((p) => p.profile === profile)) continue;
    pending.push({ label: actor, profile });
  }
  for (let i = 0; i + 1 < pending.length; i += 2) {
    const anchor = pending[i];
    const partner = pending[i + 1];
    const partnerForward = figureForward(partner.profile);
    if (partnerForward === null) continue;
    let toward: Vector3 | null = null;
    if (anchor.profile.figurePosition !== null && partner.profile.figurePosition !== null) {
      const gap = subVec3(anchor.profile.figurePosition, partner.profile.figurePosition);
      if (Math.hypot(gap[0], gap[2]) >= LOOK_TOWARD_MIN_DISTANCE) toward = [gap[0], 0, gap[2]];
    }
    if (toward === null) {
      const anchorForward = figureForward(anchor.profile);
      if (anchorForward === null) continue;
      toward = scaleVec3(anchorForward, -1);
    }
    facing[partner.label] = { anchor: anchor.label, yawDegrees: wrapDegrees(yawOf(toward) - yawOf(partnerForward)) };
  }
  return facing;
}

/** `rigProfiles` with each faced partner's profile (under every key it has) replaced by its turned copy. */
export function applyFacing(rigProfiles: Record<string, FigureRigProfile>, facing: Record<string, FacingAssignment>): Record<string, FigureRigProfile> {
  const turned = { ...rigProfiles };
  for (const [partnerLabel, assignment] of Object.entries(facing)) {
    const original = lookupRigProfile(rigProfiles, partnerLabel);
    if (original === null) continue;
    const rotated = rotateRigProfile(original, assignment.yawDegrees);
    for (const [key, profile] of Object.entries(rigProfiles)) {
      if (profile === original) turned[key] = rotated;
    }
  }
  return turned;
}

/**
 * Limb geometry with the figure origin at `base`: `chainRoot` is the
 * alignment chain's first bone (where the standoff pull aims, as in
 * `surfaceContactPoint`); `reachRoot` starts the limb's last two long
 * segments (the upper-arm or thigh joint) and `reach` is the path length
 * from it to the effector. Torso links (spine -> collar) barely add reach, so
 * counting them would stage partners out of range.
 */
export function limbGeometry(profile: FigureRigProfile, effectorBone: string, base: Vector3 | null): { chainRoot: Vector3; reachRoot: Vector3; reach: number } | null {
  if (base === null) return null;
  const chain = profile.suggestPrimaryChain(effectorBone);
  const names = chain !== null ? [...alignmentChainNames(profile, chain), effectorBone] : [];
  if (names.length < 2) return null;
  const offsets = names.map((name) => profile.boneOffset(name));
  if (offsets.some((offset) => offset === null)) return null;
  const points = offsets as Vector3[];
  let reach = 0;
  let longSegments = 0;
  let rootIndex = 0;
  for (let i = points.length - 1; i > 0 && longSegments < 2; i--) {
    const segment = lengthVec3(subVec3(points[i], points[i - 1]));
    reach += segment;
    if (segment >= LIMB_SEGMENT_MIN_LENGTH) longSegments++;
    rootIndex = i - 1;
  }
  return { chainRoot: addVec3(base, points[0])!, reachRoot: addVec3(base, points[rootIndex])!, reach };
}

/** Where two hands reaching for each other meet: horizontally between both shoulders, `MEETING_DROP_FRACTION` of the mean reach below them. */
export function meetingPoint(rootA: Vector3, lengthA: number, rootB: Vector3, lengthB: number): Vector3 {
  const middle = midpointVec3(rootA, rootB);
  return [middle[0], middle[1] - MEETING_DROP_FRACTION * ((lengthA + lengthB) / 2), middle[2]];
}

/** Where an effector stops (and, for a wrap, the points it passes and where its fingertips aim). */
export interface ContactGeometry {
  root: Vector3;
  joint: Vector3;
  stop: Vector3;
  limbLength: number;
  /** A wrap's points around the partner, reached in turn before `stop`. */
  waypoints: Vector3[];
  /** Where a wrapped hand's fingertips aim. */
  fingerPoint: Vector3 | null;
}

// Wrap geometry (cm) in the partner's frame: [lateral (out from the spine
// toward the target shoulder's side), back (behind the line between the
// shoulder anchors)], at WRAP_DROP below the shoulder anchor. The effector
// passes WRAP_SIDE_POINTS around the partner's side, under its arm, then
// stops at WRAP_BACK_POINT on the upper back; the fingertips aim at
// WRAP_FINGER_POINT, across the back toward the spine.
export const WRAP_DROP = 16;
/** Origin-to-origin distance (cm) a wrapped partner is staged at. */
export const WRAP_SEPARATION = 26;
export const WRAP_SIDE_POINTS: ReadonlyArray<readonly [number, number]> = [
  [25, -6],
  [24, 4],
];
export const WRAP_BACK_POINT: readonly [number, number] = [14, 10];
export const WRAP_FINGER_POINT: readonly [number, number] = [2, 10];
/** How far (degrees, per axis from rest) a wrapped hand may bend to lay its fingers on the back. */
export const WRAP_HAND_LIMIT = 70;

/**
 * A wrap around `partner` (origin at `partnerBase`) on `targetAnchor`'s
 * side: the waypoints, the effector's stop on its back, and where the
 * fingertips aim. Null when the partner's facing, shoulder anchors or side
 * are unknown.
 */
export function wrapPath(partner: FigureRigProfile, partnerBase: Vector3 | null, targetAnchor: string): { waypoints: Vector3[]; back: Vector3; fingers: Vector3 } | null {
  if (partnerBase === null) return null;
  const forward = figureForward(partner);
  const joint = anchorBoneOffset(partner, targetAnchor);
  const left = anchorBoneOffset(partner, "l_shoulder");
  const right = anchorBoneOffset(partner, "r_shoulder");
  const side = sideFromName(targetAnchor);
  if (forward === null || joint === null || left === null || right === null || (side !== "left" && side !== "right")) return null;
  const outward: Vector3 = side === "left" ? [forward[2], 0, -forward[0]] : [-forward[2], 0, forward[0]];
  const spine: Vector3 = [partnerBase[0] + (left[0] + right[0]) / 2, partnerBase[1] + joint[1] - WRAP_DROP, partnerBase[2] + (left[2] + right[2]) / 2];
  const at = ([lateral, back]: readonly [number, number]): Vector3 => [
    spine[0] + outward[0] * lateral - forward[0] * back,
    spine[1],
    spine[2] + outward[2] * lateral - forward[2] * back,
  ];
  return { waypoints: WRAP_SIDE_POINTS.map(at), back: at(WRAP_BACK_POINT), fingers: at(WRAP_FINGER_POINT) };
}

/** The descendant of `boneName` farthest from it (a hand's fingertip), or null. */
export function farthestDescendant(profile: FigureRigProfile, boneName: string): string | null {
  const names = new Set(profile.boneNames());
  const origin = names.has(boneName) ? profile.bone(boneName).worldPosition : null;
  if (origin === null) return null;
  let best: { distance: number; name: string } | null = null;
  for (const bone of profile.bones) {
    if (bone.name === boneName || bone.worldPosition === null || bone.isHelper) continue;
    let parent = bone.parentName;
    const seen = new Set<string>();
    while (parent !== null && parent !== boneName && !seen.has(parent) && names.has(parent)) {
      seen.add(parent);
      parent = profile.bone(parent).parentName;
    }
    if (parent !== boneName) continue;
    const distance = lengthVec3(subVec3(bone.worldPosition, origin));
    if (best === null || distance > best.distance) best = { distance, name: bone.name };
  }
  return best?.name ?? null;
}
