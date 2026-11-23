// daz-ts/src/rigProfile.ts

/**
 * Rig-profile detection: turns a live DAZ figure (or a scene-snapshot bone
 * list) into a solver-friendly `FigureRigProfile` -- canonical anchors,
 * bone-chain suggestions, and per-bone axis limits. Ports dazpy's
 * `_interaction.py` rig-profile layer, batch-only: every daz-ts
 * `DazSkeleton` always has `boneMetadata()`, so the per-bone-property
 * fallback dazpy needs for non-batch skeletons is not ported.
 *
 * This module and `interactionPlan.ts` never import `skeleton.ts`/
 * `scene.ts` directly -- they describe what they need from a live figure/
 * scene via the structural interfaces below (`RigSkeletonSource`,
 * `RigSceneSource`), which `DazSkeleton`/`DazScene` satisfy without either
 * side needing to import the other.
 */

export type Vector3 = [number, number, number];
export type Rotation3 = [number, number, number];
export type AxisName = "x" | "y" | "z";
export type ChainSide = "left" | "right" | "center" | "unknown";
export type ChainRole = "arm" | "leg" | "spine" | "neck" | "head" | "hand" | "foot" | "pelvis" | "custom";
export type AnchorRole =
  | "pelvis"
  | "spine"
  | "chest"
  | "neck"
  | "head"
  | "shoulder"
  | "elbow"
  | "hand"
  | "knee"
  | "foot"
  | "custom";

/** What the interaction package needs to build a rig profile from a live figure. */
export interface RigMetadataSource {
  readonly identifier: { value: string };
  label(): Promise<string | null>;
  boneMetadata(): Promise<Array<Record<string, unknown>>>;
  /** World position of the figure node. Optional: without it, bone offsets fall back to `localPosition`. */
  position?(): Promise<{ x: number; y: number; z: number } | null>;
}

/** Everything the interaction package needs from a live skeleton (superset of {@link RigMetadataSource}). */
export interface RigSkeletonSource extends RigMetadataSource {
  boneRotations(): Promise<Record<string, Rotation3>>;
  setBoneRotations(data: Record<string, Rotation3>): Promise<void>;
  evaluatePoseJacobian(
    chainBoneNames: string[],
    effectorBoneName: string,
    stepDegrees: number,
  ): Promise<{ basePosition: Vector3; columns: Vector3[] } | null>;
  setPosition(x: number, y: number, z: number): Promise<void>;
  /** Node Euler rotation (degrees). Optional; staging needs it (with `setRotation`) only to turn faced figures. */
  localEuler?(): Promise<[number, number, number] | null>;
  setRotation?(x: number, y: number, z: number): Promise<void>;
}

/** Everything the interaction package needs from a live scene. */
export interface RigSceneSource {
  skeletons(): Promise<RigSkeletonSource[]>;
  findSkeletonByLabel(label: string): Promise<RigSkeletonSource>;
  sceneSnapshot(skeletonLabels?: string[]): Promise<Array<Record<string, unknown>>>;
}

// ── vector math ────────────────────────────────────────────────────────────

export function addVec3(a: Vector3 | null, b: Vector3 | null): Vector3 | null {
  if (a === null) return b;
  if (b === null) return a;
  return [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
}

export function subVec3(a: Vector3, b: Vector3): Vector3 {
  return [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
}

export function midpointVec3(a: Vector3, b: Vector3): Vector3 {
  return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2];
}

export function averageVec3(points: Vector3[] | null | undefined): Vector3 | null {
  if (!points || points.length === 0) return null;
  const n = points.length;
  let sx = 0;
  let sy = 0;
  let sz = 0;
  for (const p of points) {
    sx += p[0];
    sy += p[1];
    sz += p[2];
  }
  return [sx / n, sy / n, sz / n];
}

export function scaleVec3(v: Vector3, scale: number): Vector3 {
  return [v[0] * scale, v[1] * scale, v[2] * scale];
}

export function dotVec3(a: Vector3, b: Vector3): number {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

export function lengthVec3(v: Vector3): number {
  return Math.sqrt(dotVec3(v, v));
}

export function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

/** Best-effort parse of a `[x,y,z]` array or `{x,y,z}` object into a `Vector3`. Returns null for anything else. */
export function asVector3(value: unknown): Vector3 | null {
  if (value == null) return null;
  if (Array.isArray(value) && value.length === 3) {
    return [Number(value[0]), Number(value[1]), Number(value[2])];
  }
  if (typeof value === "object") {
    const v = value as Record<string, unknown>;
    if ("x" in v && "y" in v && "z" in v) {
      return [Number(v.x), Number(v.y), Number(v.z)];
    }
  }
  return null;
}

// ── AxisLimit ────────────────────────────────────────────────────────────────

/** A single-axis joint limit in degrees. */
export interface AxisLimitDict {
  axis: AxisName;
  minDegrees: number;
  maxDegrees: number;
  preferredDegrees: number;
  weight: number;
}

export class AxisLimit {
  constructor(
    readonly axis: AxisName,
    readonly minDegrees: number,
    readonly maxDegrees: number,
    readonly preferredDegrees: number = 0.0,
    readonly weight: number = 1.0,
  ) {}

  toDict(): AxisLimitDict {
    return {
      axis: this.axis,
      minDegrees: this.minDegrees,
      maxDegrees: this.maxDegrees,
      preferredDegrees: this.preferredDegrees,
      weight: this.weight,
    };
  }

  static fromDict(data: Partial<AxisLimitDict>): AxisLimit {
    return new AxisLimit(
      data.axis ?? "x",
      Number(data.minDegrees ?? 0.0),
      Number(data.maxDegrees ?? 0.0),
      Number(data.preferredDegrees ?? 0.0),
      Number(data.weight ?? 1.0),
    );
  }
}

// ── BoneProfile ──────────────────────────────────────────────────────────────

/** Metadata for a single figure bone -- the bone relationship and DAZ-specific control data needed for interaction posing. */
export interface BoneProfileDict {
  name: string;
  label: string | null;
  parentName: string | null;
  rotationOrder: string | null;
  localPosition: Vector3 | null;
  worldPosition: Vector3 | null;
  restRotation: Rotation3 | null;
  axisLimits: Record<string, AxisLimitDict>;
  isTwist: boolean;
  isHelper: boolean;
}

export interface BoneProfileInit {
  name: string;
  label?: string | null;
  parentName?: string | null;
  rotationOrder?: string | null;
  localPosition?: Vector3 | null;
  worldPosition?: Vector3 | null;
  restRotation?: Rotation3 | null;
  axisLimits?: Partial<Record<AxisName, AxisLimit>>;
  isTwist?: boolean;
  isHelper?: boolean;
}

export class BoneProfile {
  readonly name: string;
  readonly label: string | null;
  readonly parentName: string | null;
  readonly rotationOrder: string | null;
  readonly localPosition: Vector3 | null;
  readonly worldPosition: Vector3 | null;
  readonly restRotation: Rotation3 | null;
  readonly axisLimits: Partial<Record<AxisName, AxisLimit>>;
  readonly isTwist: boolean;
  readonly isHelper: boolean;

  constructor(init: BoneProfileInit) {
    this.name = init.name;
    this.label = init.label ?? null;
    this.parentName = init.parentName ?? null;
    this.rotationOrder = init.rotationOrder ?? null;
    this.localPosition = init.localPosition ?? null;
    this.worldPosition = init.worldPosition ?? null;
    this.restRotation = init.restRotation ?? null;
    this.axisLimits = init.axisLimits ?? {};
    this.isTwist = init.isTwist ?? false;
    this.isHelper = init.isHelper ?? false;
  }

  toDict(): BoneProfileDict {
    const axisLimits: Record<string, AxisLimitDict> = {};
    for (const [axis, limit] of Object.entries(this.axisLimits)) {
      if (limit) axisLimits[axis] = limit.toDict();
    }
    return {
      name: this.name,
      label: this.label,
      parentName: this.parentName,
      rotationOrder: this.rotationOrder,
      localPosition: this.localPosition,
      worldPosition: this.worldPosition,
      restRotation: this.restRotation,
      axisLimits,
      isTwist: this.isTwist,
      isHelper: this.isHelper,
    };
  }

  static fromDict(data: Partial<BoneProfileDict>): BoneProfile {
    const axisLimits: Partial<Record<AxisName, AxisLimit>> = {};
    for (const [axis, limit] of Object.entries(data.axisLimits ?? {})) {
      axisLimits[axis as AxisName] = AxisLimit.fromDict(limit);
    }
    return new BoneProfile({
      name: data.name ?? "",
      label: data.label ?? null,
      parentName: data.parentName ?? null,
      rotationOrder: data.rotationOrder ?? null,
      localPosition: data.localPosition ?? null,
      worldPosition: data.worldPosition ?? null,
      restRotation: data.restRotation ?? null,
      axisLimits,
      isTwist: data.isTwist ?? false,
      isHelper: data.isHelper ?? false,
    });
  }
}

// ── name-matching heuristics ─────────────────────────────────────────────────

export function normalizeName(value: string | null | undefined): string {
  const text = (value ?? "").trim().toLowerCase();
  return text.replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}

function compactName(value: string | null | undefined): string {
  const text = (value ?? "").trim().toLowerCase();
  return text.replace(/[\s_-]+/g, "");
}

export function detectFigureFamily(boneNames: string[]): string {
  const names = boneNames.map((n) => n.trim().toLowerCase());
  const has = (pred: (n: string) => boolean) => names.some(pred);
  if (has((n) => n.startsWith("r_") || n.startsWith("l_"))) {
    if (
      has((n) => n.includes("forearm")) ||
      has((n) => n.endsWith("_twist")) ||
      has((n) => n.includes("_hand")) ||
      has((n) => n.includes("_foot"))
    ) {
      return "genesis_9";
    }
  }
  if (has((n) => n.includes("forearmbend"))) return "genesis_3_8";
  if (has((n) => n.includes("forearm"))) return "genesis_1_2";
  return "generic";
}

export function looksLikeTwist(name: string, label?: string | null): boolean {
  const lowered = `${name} ${label ?? ""}`.toLowerCase();
  return lowered.includes("twist") || lowered.endsWith("bendtwist");
}

/** Split a bone name/label into lowercase words (camelCase, snake_case, spaces). */
function nameWords(text: string): string[] {
  return text.replace(/([a-z0-9])([A-Z])/g, "$1 $2").toLowerCase().match(/[a-z0-9]+/g) ?? [];
}

export function looksLikeHelper(name: string, label?: string | null): boolean {
  // 'end' must be a whole word: substring matching flagged every Genesis 3/8
  // *Bend bone (lForearmBend, lShldrBend, lThighBend) as a helper.
  const text = `${name} ${label ?? ""}`;
  if (text.toLowerCase().includes("helper")) return true;
  return nameWords(text).some((word) => word === "end" || word === "endpoint");
}

export function sideFromName(name: string): ChainSide {
  const lowered = normalizeName(name);
  if (lowered.startsWith("l_") || lowered.startsWith("left_")) return "left";
  if (lowered.startsWith("r_") || lowered.startsWith("right_")) return "right";
  // camelCase prefix: rHand, lFoot, rForearmBend (Genesis 3/8 naming)
  if (name.length > 1 && name[0] === "l" && /^[A-Z]$/.test(name[1])) return "left";
  if (name.length > 1 && name[0] === "r" && /^[A-Z]$/.test(name[1])) return "right";
  if (["center_", "c_", "spine", "pelvis", "hip", "head", "neck", "chest"].some((p) => lowered.startsWith(p))) {
    return "center";
  }
  return "unknown";
}

function matchAny(name: string, tokens: readonly string[]): boolean {
  const lowered = normalizeName(name);
  return tokens.some((token) => lowered.includes(token));
}

function sideMatches(name: string, side: ChainSide): boolean {
  if (side === "center" || side === "unknown") return true;
  return sideFromName(name) === side;
}

// ── BoneChain / InteractionAnchor / ResolvedInteractionTarget ───────────────

/** A solver-friendly chain extracted from a figure rig. */
export interface BoneChainDict {
  figureLabel: string;
  role: ChainRole;
  side: ChainSide;
  bones: string[];
  effectorBone: string;
  metadata: Record<string, unknown>;
}

export class BoneChain {
  readonly figureLabel: string;
  readonly role: ChainRole;
  readonly side: ChainSide;
  readonly bones: string[];
  readonly effectorBone: string;
  readonly metadata: Record<string, unknown>;

  constructor(init: {
    figureLabel: string;
    role: ChainRole;
    side: ChainSide;
    bones: string[];
    effectorBone: string;
    metadata?: Record<string, unknown>;
  }) {
    this.figureLabel = init.figureLabel;
    this.role = init.role;
    this.side = init.side;
    this.bones = [...init.bones];
    this.effectorBone = init.effectorBone;
    this.metadata = init.metadata ?? {};
  }

  toDict(): BoneChainDict {
    return {
      figureLabel: this.figureLabel,
      role: this.role,
      side: this.side,
      bones: [...this.bones],
      effectorBone: this.effectorBone,
      metadata: { ...this.metadata },
    };
  }
}

/** A canonical anchor on a figure used for interaction planning. */
export interface InteractionAnchorDict {
  name: string;
  boneName: string;
  role: AnchorRole;
  side: ChainSide;
}

export class InteractionAnchor {
  readonly name: string;
  readonly boneName: string;
  readonly role: AnchorRole;
  readonly side: ChainSide;

  constructor(init: { name: string; boneName: string; role: AnchorRole; side?: ChainSide }) {
    this.name = init.name;
    this.boneName = init.boneName;
    this.role = init.role;
    this.side = init.side ?? "unknown";
  }

  toDict(): InteractionAnchorDict {
    return { name: this.name, boneName: this.boneName, role: this.role, side: this.side };
  }
}

/** A fully resolved anchor target, ready for solver consumption. */
export interface ResolvedInteractionTargetDict {
  figureLabel: string;
  anchorName: string;
  boneName: string;
  targetPoint: Vector3 | null;
  targetFigure: string | null;
  targetAnchor: string | null;
  targetBone: string | null;
  offset: Vector3;
  surfaceStandoff: number;
}

export class ResolvedInteractionTarget {
  readonly figureLabel: string;
  readonly anchorName: string;
  readonly boneName: string;
  readonly targetPoint: Vector3 | null;
  readonly targetFigure: string | null;
  readonly targetAnchor: string | null;
  readonly targetBone: string | null;
  readonly offset: Vector3;
  /**
   * How far the effector bone stops short of `targetPoint` (cm). `targetPoint`
   * is the target anchor's joint centre (plus `offset`); the standoff is
   * applied at alignment time, toward the source limb, once staging has
   * fixed where the figures stand.
   */
  readonly surfaceStandoff: number;

  constructor(init: {
    figureLabel: string;
    anchorName: string;
    boneName: string;
    targetPoint?: Vector3 | null;
    targetFigure?: string | null;
    targetAnchor?: string | null;
    targetBone?: string | null;
    offset?: Vector3;
    surfaceStandoff?: number;
  }) {
    this.figureLabel = init.figureLabel;
    this.anchorName = init.anchorName;
    this.boneName = init.boneName;
    this.targetPoint = init.targetPoint ?? null;
    this.targetFigure = init.targetFigure ?? null;
    this.targetAnchor = init.targetAnchor ?? null;
    this.targetBone = init.targetBone ?? null;
    this.offset = init.offset ?? [0, 0, 0];
    this.surfaceStandoff = init.surfaceStandoff ?? 0;
  }

  toDict(): ResolvedInteractionTargetDict {
    return {
      figureLabel: this.figureLabel,
      anchorName: this.anchorName,
      boneName: this.boneName,
      targetPoint: this.targetPoint,
      targetFigure: this.targetFigure,
      targetAnchor: this.targetAnchor,
      targetBone: this.targetBone,
      offset: this.offset,
      surfaceStandoff: this.surfaceStandoff,
    };
  }
}

/** Structural shape of a `HandTarget`/`FootTarget` (defined in `interactionPlan.ts`) as consumed by {@link FigureRigProfile.resolveAnchorTarget}. */
export interface AnchorTargetLike {
  figureLabel: string;
  anchorName: string;
  targetFigure?: string | null;
  targetAnchor?: string | null;
  targetPoint?: Vector3 | null;
  offset?: Vector3;
  surfaceStandoff?: number | null;
}

function anchorWorldPointHint(profile: FigureRigProfile, anchorName: string): Vector3 | null {
  const anchor = profile.anchor(anchorName);
  if (anchor === null) return null;
  const bone = profile.bone(anchor.boneName);
  if (bone.worldPosition !== null) return bone.worldPosition;
  if (bone.localPosition !== null) return bone.localPosition;
  return null;
}

export function lookupRigProfile(
  rigProfiles: Record<string, FigureRigProfile>,
  label: string | null | undefined,
): FigureRigProfile | null {
  if (label == null) return null;
  if (label in rigProfiles) return rigProfiles[label];
  const compact = compactName(label);
  for (const [key, profile] of Object.entries(rigProfiles)) {
    if (compactName(key) === compact) return profile;
  }
  return null;
}

// ── FigureRigProfile ─────────────────────────────────────────────────────────

const CHAIN_SUGGESTION_CANDIDATES: ReadonlyArray<[string, ChainRole, ChainSide, readonly string[]]> = [
  ["pelvis", "pelvis", "center", ["pelvis", "hip"]],
  ["spine", "spine", "center", ["spine", "abdomen", "torso"]],
  ["head", "head", "center", ["head"]],
  ["neck", "neck", "center", ["neck"]],
  ["l_hand", "hand", "left", ["hand"]],
  ["r_hand", "hand", "right", ["hand"]],
  ["l_foot", "foot", "left", ["foot", "toe"]],
  ["r_foot", "foot", "right", ["foot", "toe"]],
  ["l_shoulder", "arm", "left", ["shoulder", "shldr", "clavicle", "upper_arm"]],
  ["r_shoulder", "arm", "right", ["shoulder", "shldr", "clavicle", "upper_arm"]],
  ["l_thigh", "leg", "left", ["thigh", "upper_leg"]],
  ["r_thigh", "leg", "right", ["thigh", "upper_leg"]],
];

const SHOULDER_JOINT_TOKENS = ["upperarm", "upper_arm", "shldrbend"] as const;
const KNEE_JOINT_TOKENS = ["shin", "calf", "knee"] as const;

/**
 * Anchor tokens tried before {@link ANCHOR_PATTERNS}: Genesis 9's `l_shoulder`
 * bone is the clavicle (origin by the sternum), so the shoulder anchor is the
 * upper-arm joint; `*thigh` starts at the hip, so the knee is the shin.
 */
const PREFERRED_ANCHOR_TOKENS: Readonly<Record<string, readonly string[]>> = {
  l_shoulder: SHOULDER_JOINT_TOKENS,
  r_shoulder: SHOULDER_JOINT_TOKENS,
  l_knee: KNEE_JOINT_TOKENS,
  r_knee: KNEE_JOINT_TOKENS,
};

/** Approximate body radius (cm, adult figure) from an anchor's joint centre to its skin. */
export const ANCHOR_SURFACE_RADIUS: Readonly<Record<AnchorRole, number>> = {
  pelvis: 12,
  spine: 12,
  chest: 12,
  neck: 6,
  head: 10,
  shoulder: 6,
  elbow: 4,
  hand: 3,
  knee: 5,
  foot: 5,
  custom: 0,
};

/** Wrist-to-fingers / ankle-to-toes reach (cm) when the profile has no descendant positions. */
export const EFFECTOR_REACH_FALLBACK: Readonly<{ hand: number; foot: number }> = { hand: 15, foot: 12 };

const ANCHOR_PATTERNS: ReadonlyArray<[string, AnchorRole, ChainSide, readonly string[]]> = [
  ["pelvis", "pelvis", "center", ["pelvis", "hip"]],
  ["spine", "spine", "center", ["spine", "abdomen", "torso"]],
  ["chest", "chest", "center", ["chest", "upperchest", "thorax"]],
  ["neck", "neck", "center", ["neck"]],
  ["head", "head", "center", ["head"]],
  ["l_shoulder", "shoulder", "left", ["shoulder", "shldr", "clavicle"]],
  ["r_shoulder", "shoulder", "right", ["shoulder", "shldr", "clavicle"]],
  ["l_elbow", "elbow", "left", ["elbow", "forearm"]],
  ["r_elbow", "elbow", "right", ["elbow", "forearm"]],
  ["l_hand", "hand", "left", ["hand", "wrist"]],
  ["r_hand", "hand", "right", ["hand", "wrist"]],
  ["l_knee", "knee", "left", ["knee", "thigh"]],
  ["r_knee", "knee", "right", ["knee", "thigh"]],
  ["l_foot", "foot", "left", ["foot", "toe", "ankle"]],
  ["r_foot", "foot", "right", ["foot", "toe", "ankle"]],
];

/** Plain-object schema matching {@link FigureRigProfile.toDict}/{@link FigureRigProfile.fromDict}. */
export interface FigureRigProfileDict {
  figureLabel: string;
  family: string;
  bones: BoneProfileDict[];
  metadata: Record<string, unknown>;
  figurePosition: Vector3 | null;
}

/** A DAZ figure expressed as a solver-friendly rig profile. */
export class FigureRigProfile {
  readonly figureLabel: string;
  readonly family: string;
  readonly bones: BoneProfile[];
  readonly metadata: Record<string, unknown>;
  /** World position of the figure node itself (what `setPosition` moves). */
  readonly figurePosition: Vector3 | null;
  private readonly index: Map<string, number>;

  constructor(init: { figureLabel: string; family: string; bones?: BoneProfile[]; metadata?: Record<string, unknown>; figurePosition?: Vector3 | null }) {
    this.figureLabel = init.figureLabel;
    this.family = init.family;
    this.bones = [...(init.bones ?? [])];
    this.metadata = init.metadata ?? {};
    this.figurePosition = init.figurePosition ?? null;
    this.index = new Map(this.bones.map((bone, i) => [bone.name, i]));
  }

  /**
   * Offset of a bone from the figure's origin, in world axes:
   * `worldPosition - figurePosition` when both are known (live profiles),
   * else `localPosition` (what hand-built profiles use for this offset). Live
   * `localPosition` is the bone's translation channel -- zero on an unposed
   * figure -- not an offset.
   */
  boneOffset(name: string): Vector3 | null {
    const bone = this.bone(name);
    if (this.figurePosition !== null && bone.worldPosition !== null) return subVec3(bone.worldPosition, this.figurePosition);
    return bone.localPosition;
  }

  /**
   * Distance from a bone to its farthest descendant (wrist to finger joints,
   * ankle to toes). Null when the bone or its descendants have no world
   * positions.
   */
  effectorReach(boneName: string): number | null {
    const origin = this.bone(boneName).worldPosition;
    if (origin === null) return null;
    let reach: number | null = null;
    for (const bone of this.bones) {
      if (bone.name === boneName || bone.worldPosition === null) continue;
      let parent = bone.parentName;
      const seen = new Set<string>();
      while (parent !== null && parent !== boneName && !seen.has(parent) && this.index.has(parent)) {
        seen.add(parent);
        parent = this.bones[this.index.get(parent)!].parentName;
      }
      if (parent !== boneName) continue;
      const distance = lengthVec3(subVec3(bone.worldPosition, origin));
      reach = reach === null ? distance : Math.max(reach, distance);
    }
    return reach;
  }

  boneNames(): string[] {
    return this.bones.map((bone) => bone.name);
  }

  bone(name: string): BoneProfile {
    const i = this.index.get(name);
    if (i === undefined) throw new Error(`Bone not found in rig profile: ${name}`);
    return this.bones[i];
  }

  /** Root-to-bone ancestry for the named bone. */
  ancestry(boneName: string): BoneProfile[] {
    const chain: BoneProfile[] = [];
    let current = this.bone(boneName);
    const seen = new Set<string>();
    for (;;) {
      if (seen.has(current.name)) throw new Error(`Cycle detected in rig profile around ${current.name}`);
      seen.add(current.name);
      chain.push(current);
      if (current.parentName === null) break;
      current = this.bone(current.parentName);
    }
    chain.reverse();
    return chain;
  }

  chainTo(boneName: string): string[] {
    return this.ancestry(boneName).map((bone) => bone.name);
  }

  chainFor(boneName: string, role: ChainRole, side: ChainSide = "unknown"): BoneChain {
    return new BoneChain({ figureLabel: this.figureLabel, role, side, bones: this.chainTo(boneName), effectorBone: boneName });
  }

  private findTerminalBone(candidates: ReadonlyArray<[ChainRole | AnchorRole, ChainSide, readonly string[]]>): BoneProfile | null {
    for (const [, side, tokens] of candidates) {
      for (const bone of this.bones) {
        if (matchAny(bone.name, tokens) && sideMatches(bone.name, side)) return bone;
      }
    }
    return null;
  }

  /** Solver-friendly chain suggestions for the major interaction lanes. */
  chainSuggestions(): BoneChain[] {
    const suggestions: BoneChain[] = [];
    for (const [, role, side, tokens] of CHAIN_SUGGESTION_CANDIDATES) {
      const terminal = this.findTerminalBone([[role, side, tokens]]);
      if (terminal === null) continue;
      suggestions.push(this.chainFor(terminal.name, role, side));
    }
    return suggestions;
  }

  /** A solver chain for a specific effector bone, classified by name heuristics. */
  suggestPrimaryChain(boneName: string): BoneChain | null {
    if (!this.index.has(boneName)) return null;
    const bone = this.bone(boneName);
    const side = sideFromName(bone.name);
    const lowered = normalizeName(bone.name);
    let role: ChainRole;
    if (lowered.includes("hand") || lowered.endsWith("wrist")) role = "hand";
    else if (lowered.includes("foot") || lowered.includes("toe")) role = "foot";
    else if (lowered.includes("head")) role = "head";
    else if (lowered.includes("neck")) role = "neck";
    else if (["thigh", "leg", "shin", "calf"].some((t) => lowered.includes(t))) role = "leg";
    else if (["shoulder", "shldr", "clavicle", "arm", "forearm", "elbow"].some((t) => lowered.includes(t))) role = "arm";
    else if (["spine", "abdomen", "torso", "chest", "pelvis", "hip"].some((t) => lowered.includes(t))) {
      role = ["spine", "abdomen", "torso", "chest"].some((t) => lowered.includes(t)) ? "spine" : "pelvis";
    } else {
      role = "custom";
    }
    return this.chainFor(boneName, role, side);
  }

  /** Canonical interaction anchors for the figure -- an opinionated, stable adapter layer for solver work. */
  anchorMap(): Map<string, InteractionAnchor> {
    const anchors = new Map<string, InteractionAnchor>();
    for (const [key, role, side, tokens] of ANCHOR_PATTERNS) {
      const preferred = PREFERRED_ANCHOR_TOKENS[key];
      const bone = this.findTerminalBone(preferred ? [[role, side, preferred], [role, side, tokens]] : [[role, side, tokens]]);
      if (bone === null) continue;
      anchors.set(key, new InteractionAnchor({ name: key, boneName: bone.name, role, side }));
    }
    return anchors;
  }

  anchor(name: string): InteractionAnchor | null {
    return this.anchorMap().get(name) ?? null;
  }

  anchorNames(): string[] {
    return [...this.anchorMap().keys()].sort();
  }

  requireAnchor(name: string): InteractionAnchor {
    const anchor = this.anchor(name);
    if (anchor === null) throw new Error(`Anchor not found in rig profile: ${name}`);
    return anchor;
  }

  /** Resolve an anchor target into concrete bones and an optional world point. */
  resolveAnchorTarget(target: AnchorTargetLike, rigProfiles?: Record<string, FigureRigProfile>): ResolvedInteractionTarget {
    const anchor = this.requireAnchor(target.anchorName);
    let targetPoint = target.targetPoint ?? null;
    const targetFigure = target.targetFigure ?? null;
    const targetAnchor = target.targetAnchor ?? null;
    let targetBone: string | null = null;
    let targetRole: AnchorRole | null = null;
    let anchorPointHint = false;

    if (targetFigure && targetAnchor && rigProfiles) {
      const targetProfile = lookupRigProfile(rigProfiles, targetFigure);
      if (targetProfile) {
        const resolved = targetProfile.requireAnchor(targetAnchor);
        targetBone = resolved.boneName;
        targetRole = resolved.role;
      }
    }
    if (targetPoint === null && targetFigure && targetAnchor && rigProfiles) {
      const targetProfile = lookupRigProfile(rigProfiles, targetFigure);
      if (targetProfile) {
        targetPoint = anchorWorldPointHint(targetProfile, targetAnchor);
        anchorPointHint = targetPoint !== null;
      }
    }

    // Only an anchor's joint-centre hint needs pushing out to the skin; an
    // explicit targetPoint is taken as the contact point itself.
    let surfaceStandoff = 0;
    if (target.surfaceStandoff !== undefined && target.surfaceStandoff !== null) surfaceStandoff = Math.max(0, target.surfaceStandoff);
    else if (anchorPointHint && targetRole !== null) surfaceStandoff = this.defaultSurfaceStandoff(anchor, targetRole);

    // The offset shifts a resolved point; it is not a point on its own.
    // Leaving targetPoint null lets buildPosePatch report the target as
    // unresolved and alignSingleLimbTarget return missing_target_point.
    if (targetPoint !== null) targetPoint = addVec3(targetPoint, target.offset ?? [0, 0, 0]);

    return new ResolvedInteractionTarget({
      figureLabel: this.figureLabel,
      anchorName: anchor.name,
      boneName: anchor.boneName,
      targetPoint,
      targetFigure,
      targetAnchor,
      targetBone,
      offset: target.offset ?? [0, 0, 0],
      surfaceStandoff,
    });
  }

  /**
   * Joint-to-joint gap for skin contact: target body radius + the source
   * effector's reach. A hand or foot effector is its wrist/ankle joint, so it
   * stops a whole hand/foot short of the skin; hand-to-hand (handshake) stops
   * half a hand short so the palms meet.
   */
  private defaultSurfaceStandoff(source: InteractionAnchor, targetRole: AnchorRole): number {
    let reach: number;
    if (source.role === "hand" || source.role === "foot") {
      reach = this.effectorReach(source.boneName) ?? EFFECTOR_REACH_FALLBACK[source.role];
    } else {
      reach = ANCHOR_SURFACE_RADIUS[source.role];
    }
    if (source.role === "hand" && targetRole === "hand") return reach * 0.5;
    return ANCHOR_SURFACE_RADIUS[targetRole] + reach;
  }

  toDict(): FigureRigProfileDict {
    return {
      figureLabel: this.figureLabel,
      family: this.family,
      bones: this.bones.map((bone) => bone.toDict()),
      metadata: { ...this.metadata },
      figurePosition: this.figurePosition,
    };
  }

  static fromDict(data: Partial<FigureRigProfileDict>): FigureRigProfile {
    return new FigureRigProfile({
      figureLabel: data.figureLabel ?? "",
      family: data.family ?? "generic",
      bones: (data.bones ?? []).map((item) => BoneProfile.fromDict(item)),
      metadata: { ...(data.metadata ?? {}) },
      figurePosition: asVector3(data.figurePosition),
    });
  }
}

// ── default axis limits ──────────────────────────────────────────────────────

const AXIS_LIMIT_PRESETS: ReadonlyArray<[readonly string[], Partial<Record<AxisName, [number, number]>>]> = [
  [["head", "neck"], { x: [-70, 70], y: [-85, 85], z: [-45, 45] }],
  [["shoulder", "shldr", "clavicle", "upper_arm"], { x: [-120, 120], y: [-120, 120], z: [-140, 140] }],
  [["forearm", "hand"], { x: [-160, 160], y: [-120, 120], z: [-160, 160] }],
  [["thigh", "shin", "calf"], { x: [-140, 140], y: [-80, 80], z: [-140, 140] }],
  [["foot", "toe"], { x: [-70, 70], y: [-45, 45], z: [-70, 70] }],
  [["spine", "abdomen", "chest", "hip", "pelvis"], { x: [-45, 45], y: [-45, 45], z: [-45, 45] }],
];

/** Loose, solver-friendly axis limits for a given bone name. */
export function defaultAxisLimitsForBone(name: string): Partial<Record<AxisName, AxisLimit>> {
  const key = normalizeName(name);
  for (const [tokens, ranges] of AXIS_LIMIT_PRESETS) {
    if (tokens.some((token) => key.includes(token))) {
      const limits: Partial<Record<AxisName, AxisLimit>> = {};
      for (const [axis, range] of Object.entries(ranges) as Array<[AxisName, [number, number]]>) {
        limits[axis] = new AxisLimit(axis, range[0], range[1]);
      }
      return limits;
    }
  }
  return {};
}

function boneProfileFromRaw(item: Record<string, unknown>): BoneProfile {
  const name = String(item.name ?? "");
  const label = (item.label as string | null | undefined) ?? null;
  return new BoneProfile({
    name,
    label,
    parentName: (item.parent_name as string | null | undefined) ?? null,
    rotationOrder: (item.rotation_order as string | null | undefined) ?? null,
    localPosition: asVector3(item.local_position),
    worldPosition: asVector3(item.world_position),
    restRotation: asVector3(item.local_euler),
    axisLimits: defaultAxisLimitsForBone(name),
    isTwist: looksLikeTwist(name, label),
    isHelper: looksLikeHelper(name, label),
  });
}

/** Inspect a live DAZ skeleton (one `boneMetadata()` HTTP call) and build a solver-friendly rig profile. */
export async function buildRigProfile(skeleton: RigMetadataSource): Promise<FigureRigProfile> {
  const label = await skeleton.label();
  const figureLabel = label ?? skeleton.identifier.value;
  const raw = await skeleton.boneMetadata();
  // Bone world positions only become figure-relative offsets with the
  // figure's own world position (one extra call).
  const figurePosition = skeleton.position ? asVector3(await skeleton.position()) : null;
  const bones = raw.map((item) => boneProfileFromRaw(item));
  const family = detectFigureFamily(bones.map((bone) => bone.name));
  return new FigureRigProfile({
    figureLabel,
    family,
    bones,
    metadata: { boneCount: bones.length, source: "daz-ts" },
    figurePosition,
  });
}

/**
 * Build rig profiles for every skeleton from a `sceneSnapshot()` result --
 * one HTTP call for every figure in the scene. Both the figure label and
 * internal name are stored as keys so lookup tolerates either.
 */
export function buildRigProfilesFromSnapshot(snapshot: Array<Record<string, unknown>>): Record<string, FigureRigProfile> {
  const profiles: Record<string, FigureRigProfile> = {};
  for (const skelData of snapshot) {
    const name = String(skelData.name ?? "");
    const label = (skelData.label as string | undefined) || name;
    const rawBones = (skelData.bones as Array<Record<string, unknown>> | undefined) ?? [];
    const bones = rawBones.map((item) => boneProfileFromRaw(item));
    const family = detectFigureFamily(bones.map((bone) => bone.name));
    const profile = new FigureRigProfile({ figureLabel: label, family, bones, metadata: { boneCount: bones.length, source: "snapshot" }, figurePosition: asVector3(skelData.position) });
    profiles[label] = profile;
    if (name && name !== label) profiles[name] = profile;
  }
  return profiles;
}
