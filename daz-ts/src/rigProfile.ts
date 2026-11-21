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
