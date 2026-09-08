# daz-ts Phase 5A: Rig Profiles + Interaction Plan Data Model — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the pure data/logic half of dazpy's `_interaction.py` to daz-ts: rig-profile detection (`rigProfile.ts`) and the interaction-plan/recipe data model including coarse pose-patch staging (`interactionPlan.ts`), with no live IK yet (that's Phase 5B, `daz-script-server-sf7y.2`).

**Architecture:** Two new files, `daz-ts/src/rigProfile.ts` (leaf module — no imports from `skeleton.ts`/`scene.ts`, only structural interfaces) and `daz-ts/src/interactionPlan.ts` (imports types from `rigProfile.ts`). Every multi-field data type uses a `readonly` public field + single options-object constructor + `toDict()`/`static fromDict()`, matching the existing `DazPose`/`DazSceneState` convention. `Vector3`/`Rotation3` are `[number, number, number]` tuples, matching `skeleton.ts`'s existing `boneRotations()` convention.

**Tech Stack:** TypeScript (strict, ES2022, NodeNext modules), Vitest.

**Spec:** `docs/superpowers/specs/2026-09-07-daz-ts-phase5-interaction-design.md`

## Global Constraints

- No new file in this plan may `import` from `skeleton.ts` or `scene.ts` — only structural interfaces (defined in `rigProfile.ts`) may describe what a live skeleton/scene must support. This is what lets `scene.ts`/`skeleton.ts` later import `interactionPlan.ts`/`interactionSolve.ts` without a cycle.
- All public data types use camelCase fields and a single options-object constructor (`new BoneProfile({ name: "hip" })`), never long positional-parameter lists — matches the `DazPoseDict`/`DazSceneStateDict` camelCase convention (the wire keys returned by `boneMetadata()`/`sceneSnapshot()` scripts are snake_case server-side JSON — `parent_name`, `rotation_order`, `local_position`, `world_position`, `local_euler` — and get translated to camelCase fields when parsed; do not confuse the two).
- Only the **batch** IK-adjacent primitives are referenced (`boneMetadata()`, `setPosition()`); no per-bone-property fallback path is ported (see spec's "Simplification" section).
- `npm test` (== `vitest run test/unit`) must pass after every task; `npm run build` (== `tsc -p tsconfig.json`) must type-check clean after every task.
- All new public symbols get exported from `src/index.ts` under a new `// ── Phase 5A: ... ──` section (Task 9), not incrementally per task.

---

## Task 1: `rigProfile.ts` — types, name-matching helpers, vector math, `AxisLimit`, `BoneProfile`

**Files:**
- Create: `daz-ts/src/rigProfile.ts`
- Test: `daz-ts/test/unit/rigProfile.test.ts`

**Interfaces:**
- Produces: `Vector3 = [number, number, number]`, `Rotation3 = [number, number, number]`, `AxisName = "x"|"y"|"z"`, `ChainSide = "left"|"right"|"center"|"unknown"`, `ChainRole = "arm"|"leg"|"spine"|"neck"|"head"|"hand"|"foot"|"pelvis"|"custom"`, `AnchorRole = "pelvis"|"spine"|"chest"|"neck"|"head"|"shoulder"|"elbow"|"hand"|"knee"|"foot"|"custom"`; `RigMetadataSource`, `RigSkeletonSource`, `RigSceneSource` interfaces; vector helpers `addVec3`, `subVec3`, `midpointVec3`, `averageVec3`, `scaleVec3`, `dotVec3`, `lengthVec3`, `clamp`; `AxisLimit`, `AxisLimitDict`; `BoneProfile`, `BoneProfileDict`, `BoneProfileInit`.

- [ ] **Step 1: Write the failing test**

```ts
// daz-ts/test/unit/rigProfile.test.ts
import { describe, expect, it } from "vitest";
import { AxisLimit, BoneProfile, addVec3, averageVec3, midpointVec3, subVec3 } from "../../src/rigProfile.js";

describe("rigProfile vector helpers", () => {
  it("addVec3 sums two vectors and passes through when one side is null", () => {
    expect(addVec3([1, 2, 3], [4, 5, 6])).toEqual([5, 7, 9]);
    expect(addVec3(null, [4, 5, 6])).toEqual([4, 5, 6]);
    expect(addVec3([1, 2, 3], null)).toEqual([1, 2, 3]);
  });

  it("subVec3 subtracts componentwise", () => {
    expect(subVec3([4, 5, 6], [1, 2, 3])).toEqual([3, 3, 3]);
  });

  it("midpointVec3 averages two points", () => {
    expect(midpointVec3([0, 0, 0], [2, 4, 6])).toEqual([1, 2, 3]);
  });

  it("averageVec3 returns null for an empty/undefined list, else the componentwise mean", () => {
    expect(averageVec3(undefined)).toBeNull();
    expect(averageVec3([])).toBeNull();
    expect(averageVec3([[0, 0, 0], [2, 2, 2], [4, 4, 4]])).toEqual([2, 2, 2]);
  });
});

describe("AxisLimit", () => {
  it("round-trips through toDict/fromDict", () => {
    const limit = new AxisLimit("x", -45, 45, 10, 0.5);
    const restored = AxisLimit.fromDict(limit.toDict());
    expect(restored.axis).toBe("x");
    expect(restored.minDegrees).toBe(-45);
    expect(restored.maxDegrees).toBe(45);
    expect(restored.preferredDegrees).toBe(10);
    expect(restored.weight).toBe(0.5);
  });

  it("defaults preferredDegrees to 0 and weight to 1", () => {
    const limit = new AxisLimit("y", -10, 10);
    expect(limit.preferredDegrees).toBe(0);
    expect(limit.weight).toBe(1);
  });
});

describe("BoneProfile", () => {
  it("round-trips through toDict/fromDict including axisLimits", () => {
    const bone = new BoneProfile({
      name: "l_forearm",
      label: "Left Forearm",
      parentName: "l_shoulder",
      rotationOrder: "XYZ",
      localPosition: [1, 0, 0],
      worldPosition: [10, 0, 0],
      restRotation: [0, 0, 0],
      axisLimits: { x: new AxisLimit("x", -160, 160) },
      isTwist: false,
      isHelper: false,
    });
    const restored = BoneProfile.fromDict(bone.toDict());
    expect(restored.name).toBe("l_forearm");
    expect(restored.parentName).toBe("l_shoulder");
    expect(restored.localPosition).toEqual([1, 0, 0]);
    expect(restored.axisLimits.x?.minDegrees).toBe(-160);
  });

  it("defaults optional fields to null/empty", () => {
    const bone = new BoneProfile({ name: "hip" });
    expect(bone.label).toBeNull();
    expect(bone.parentName).toBeNull();
    expect(bone.localPosition).toBeNull();
    expect(bone.axisLimits).toEqual({});
    expect(bone.isTwist).toBe(false);
    expect(bone.isHelper).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- test/unit/rigProfile.test.ts`
Expected: FAIL — `Cannot find module '../../src/rigProfile.js'`

- [ ] **Step 3: Write minimal implementation**

```ts
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
  ): Promise<{ base_position: Vector3; columns: Vector3[] } | null>;
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- test/unit/rigProfile.test.ts`
Expected: PASS (7 tests)

- [ ] **Step 5: Run the type checker**

Run: `npm run build`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add daz-ts/src/rigProfile.ts daz-ts/test/unit/rigProfile.test.ts
git commit -m "feat(daz-ts): add rigProfile.ts vector math, AxisLimit, BoneProfile"
```

---

## Task 2: `FigureRigProfile` + name-matching heuristics + anchor resolution

**Files:**
- Modify: `daz-ts/src/rigProfile.ts`
- Modify: `daz-ts/test/unit/rigProfile.test.ts`

**Interfaces:**
- Consumes: `Vector3`, `AxisName`, `ChainSide`, `ChainRole`, `AnchorRole`, `BoneProfile`, `addVec3`, `asVector3` (Task 1)
- Produces: `BoneChain`, `BoneChainDict`; `InteractionAnchor`, `InteractionAnchorDict`; `ResolvedInteractionTarget`, `ResolvedInteractionTargetDict`; `AnchorTargetLike` (structural interface consumed later by `interactionPlan.ts`'s `HandTarget`/`FootTarget`); `FigureRigProfile`, `FigureRigProfileDict`; `lookupRigProfile(rigProfiles, label)`; `sideFromName(name)`.

- [ ] **Step 1: Write the failing test**

```ts
// append to daz-ts/test/unit/rigProfile.test.ts
import {
  BoneProfile,
  FigureRigProfile,
  InteractionAnchor,
  lookupRigProfile,
} from "../../src/rigProfile.js";

function genesis9Bones(): BoneProfile[] {
  const hip = new BoneProfile({ name: "hip" });
  const spine = new BoneProfile({ name: "spine", parentName: "hip" });
  const chest = new BoneProfile({ name: "chest", parentName: "spine" });
  const neck = new BoneProfile({ name: "neck", parentName: "chest" });
  const head = new BoneProfile({ name: "head", parentName: "neck" });
  const lHand = new BoneProfile({ name: "l_hand", label: "Left Hand", parentName: "chest" });
  const rHand = new BoneProfile({ name: "r_hand", label: "Right Hand", parentName: "chest" });
  const lFoot = new BoneProfile({ name: "l_foot", label: "Left Foot", parentName: "hip" });
  const rFoot = new BoneProfile({ name: "r_foot", label: "Right Foot", parentName: "hip" });
  return [hip, spine, chest, neck, head, lHand, rHand, lFoot, rFoot];
}

function genesis38Bones(): BoneProfile[] {
  const hip = new BoneProfile({ name: "hip" });
  const spine = new BoneProfile({ name: "abdomenLower", parentName: "hip" });
  const chest = new BoneProfile({ name: "chestLower", parentName: "abdomenLower" });
  const lCollar = new BoneProfile({ name: "lCollar", parentName: "chestLower" });
  const rCollar = new BoneProfile({ name: "rCollar", parentName: "chestLower" });
  const lForearmBend = new BoneProfile({ name: "lForearmBend", parentName: "lCollar" });
  const rForearmBend = new BoneProfile({ name: "rForearmBend", parentName: "rCollar" });
  const lHand = new BoneProfile({ name: "lHand", label: "Left Hand", parentName: "lForearmBend" });
  const rHand = new BoneProfile({ name: "rHand", label: "Right Hand", parentName: "rForearmBend" });
  const lFoot = new BoneProfile({ name: "lFoot", label: "Left Foot", parentName: "hip" });
  const rFoot = new BoneProfile({ name: "rFoot", label: "Right Foot", parentName: "hip" });
  return [hip, spine, chest, lCollar, rCollar, lForearmBend, rForearmBend, lHand, rHand, lFoot, rFoot];
}

describe("FigureRigProfile", () => {
  it("ancestry/chainTo return root-to-bone order", () => {
    const profile = new FigureRigProfile({ figureLabel: "Genesis 9", family: "genesis_9", bones: genesis9Bones() });
    expect(profile.chainTo("head")).toEqual(["hip", "spine", "chest", "neck", "head"]);
  });

  it("anchorMap resolves canonical snake_case anchors for Genesis 9 naming", () => {
    const profile = new FigureRigProfile({ figureLabel: "Genesis 9", family: "genesis_9", bones: genesis9Bones() });
    const anchors = profile.anchorMap();
    expect(anchors.get("l_hand")?.boneName).toBe("l_hand");
    expect(anchors.get("r_hand")?.boneName).toBe("r_hand");
    expect(anchors.get("l_foot")?.role).toBe("foot");
    expect(profile.anchor("r_hand")).toBeInstanceOf(InteractionAnchor);
  });

  it("anchorMap resolves camelCase Genesis 3/8 bone names via canonical anchor keys", () => {
    const profile = new FigureRigProfile({ figureLabel: "Bob Genesis 8", family: "genesis_3_8", bones: genesis38Bones() });
    const anchors = profile.anchorMap();
    expect(anchors.get("r_hand")?.boneName).toBe("rHand");
    expect(anchors.get("l_hand")?.boneName).toBe("lHand");
    expect(anchors.get("l_foot")?.boneName).toBe("lFoot");
    expect(anchors.get("r_foot")?.boneName).toBe("rFoot");
  });

  it("suggestPrimaryChain classifies a hand bone into a hand-role chain ending at that bone", () => {
    const profile = new FigureRigProfile({ figureLabel: "Genesis 9", family: "genesis_9", bones: genesis9Bones() });
    const chain = profile.suggestPrimaryChain("r_hand");
    expect(chain?.role).toBe("hand");
    expect(chain?.effectorBone).toBe("r_hand");
    expect(chain?.bones).toEqual(["hip", "spine", "chest", "r_hand"]);
  });

  it("suggestPrimaryChain returns null for an unknown bone", () => {
    const profile = new FigureRigProfile({ figureLabel: "Genesis 9", family: "genesis_9", bones: genesis9Bones() });
    expect(profile.suggestPrimaryChain("nonexistent")).toBeNull();
  });

  it("requireAnchor throws for an unknown anchor name", () => {
    const profile = new FigureRigProfile({ figureLabel: "Genesis 9", family: "genesis_9", bones: genesis9Bones() });
    expect(() => profile.requireAnchor("tail")).toThrow(/Anchor not found/);
  });

  it("resolveAnchorTarget resolves a same-figure hand target and applies the offset", () => {
    const bones = genesis9Bones();
    const rHandIndex = bones.findIndex((b) => b.name === "r_hand");
    bones[rHandIndex] = new BoneProfile({ ...bones[rHandIndex], localPosition: [10, 20, 30] } as any);
    const profile = new FigureRigProfile({ figureLabel: "Genesis 9", family: "genesis_9", bones });
    const resolved = profile.resolveAnchorTarget({
      figureLabel: "Genesis 9",
      anchorName: "r_hand",
      targetPoint: [1, 2, 3],
      offset: [0.5, 0, -0.5],
    });
    expect(resolved.boneName).toBe("r_hand");
    expect(resolved.targetPoint).toEqual([1.5, 2, 2.5]);
    expect(resolved.targetBone).toBeNull();
  });

  it("toDict/fromDict round-trips a full profile", () => {
    const profile = new FigureRigProfile({ figureLabel: "Genesis 9", family: "genesis_9", bones: genesis9Bones() });
    const restored = FigureRigProfile.fromDict(profile.toDict());
    expect(restored.figureLabel).toBe("Genesis 9");
    expect(restored.family).toBe("genesis_9");
    expect(restored.boneNames()).toEqual(profile.boneNames());
  });
});

describe("lookupRigProfile", () => {
  it("matches by exact key, then by compact-name alias", () => {
    const profile = new FigureRigProfile({ figureLabel: "Genesis 9", family: "genesis_9", bones: [] });
    const table = { "Genesis 9": profile };
    expect(lookupRigProfile(table, "Genesis 9")).toBe(profile);
    expect(lookupRigProfile(table, "Genesis9")).toBe(profile);
    expect(lookupRigProfile(table, "Nobody")).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- test/unit/rigProfile.test.ts`
Expected: FAIL — `FigureRigProfile`/`InteractionAnchor`/`lookupRigProfile` are not exported

- [ ] **Step 3: Write minimal implementation**

Append to `daz-ts/src/rigProfile.ts`:

```ts
// ── name-matching heuristics ─────────────────────────────────────────────────

function normalizeName(value: string | null | undefined): string {
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

export function looksLikeHelper(name: string, label?: string | null): boolean {
  const lowered = `${name} ${label ?? ""}`.toLowerCase();
  return ["helper", "end", "end point", "endpoint"].some((token) => lowered.includes(token));
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

  constructor(init: {
    figureLabel: string;
    anchorName: string;
    boneName: string;
    targetPoint?: Vector3 | null;
    targetFigure?: string | null;
    targetAnchor?: string | null;
    targetBone?: string | null;
    offset?: Vector3;
  }) {
    this.figureLabel = init.figureLabel;
    this.anchorName = init.anchorName;
    this.boneName = init.boneName;
    this.targetPoint = init.targetPoint ?? null;
    this.targetFigure = init.targetFigure ?? null;
    this.targetAnchor = init.targetAnchor ?? null;
    this.targetBone = init.targetBone ?? null;
    this.offset = init.offset ?? [0, 0, 0];
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
  ["l_shoulder", "arm", "left", ["shoulder", "clavicle", "upper_arm"]],
  ["r_shoulder", "arm", "right", ["shoulder", "clavicle", "upper_arm"]],
  ["l_thigh", "leg", "left", ["thigh", "upper_leg"]],
  ["r_thigh", "leg", "right", ["thigh", "upper_leg"]],
];

const ANCHOR_PATTERNS: ReadonlyArray<[string, AnchorRole, ChainSide, readonly string[]]> = [
  ["pelvis", "pelvis", "center", ["pelvis", "hip"]],
  ["spine", "spine", "center", ["spine", "abdomen", "torso"]],
  ["chest", "chest", "center", ["chest", "upperchest", "thorax"]],
  ["neck", "neck", "center", ["neck"]],
  ["head", "head", "center", ["head"]],
  ["l_shoulder", "shoulder", "left", ["shoulder", "clavicle"]],
  ["r_shoulder", "shoulder", "right", ["shoulder", "clavicle"]],
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
}

/** A DAZ figure expressed as a solver-friendly rig profile. */
export class FigureRigProfile {
  readonly figureLabel: string;
  readonly family: string;
  readonly bones: BoneProfile[];
  readonly metadata: Record<string, unknown>;
  private readonly index: Map<string, number>;

  constructor(init: { figureLabel: string; family: string; bones?: BoneProfile[]; metadata?: Record<string, unknown> }) {
    this.figureLabel = init.figureLabel;
    this.family = init.family;
    this.bones = init.bones ?? [];
    this.metadata = init.metadata ?? {};
    this.index = new Map(this.bones.map((bone, i) => [bone.name, i]));
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
    else if (["shoulder", "clavicle", "arm", "forearm", "elbow"].some((t) => lowered.includes(t))) role = "arm";
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
      const bone = this.findTerminalBone([[role, side, tokens]]);
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

    if (targetFigure && targetAnchor && rigProfiles) {
      const targetProfile = lookupRigProfile(rigProfiles, targetFigure);
      if (targetProfile) targetBone = targetProfile.requireAnchor(targetAnchor).boneName;
    }
    if (targetPoint === null && targetFigure && targetAnchor && rigProfiles) {
      const targetProfile = lookupRigProfile(rigProfiles, targetFigure);
      if (targetProfile) targetPoint = anchorWorldPointHint(targetProfile, targetAnchor);
    }

    targetPoint = addVec3(targetPoint, target.offset ?? [0, 0, 0]);

    return new ResolvedInteractionTarget({
      figureLabel: this.figureLabel,
      anchorName: anchor.name,
      boneName: anchor.boneName,
      targetPoint,
      targetFigure,
      targetAnchor,
      targetBone,
      offset: target.offset ?? [0, 0, 0],
    });
  }

  toDict(): FigureRigProfileDict {
    return {
      figureLabel: this.figureLabel,
      family: this.family,
      bones: this.bones.map((bone) => bone.toDict()),
      metadata: { ...this.metadata },
    };
  }

  static fromDict(data: Partial<FigureRigProfileDict>): FigureRigProfile {
    return new FigureRigProfile({
      figureLabel: data.figureLabel ?? "",
      family: data.family ?? "generic",
      bones: (data.bones ?? []).map((item) => BoneProfile.fromDict(item)),
      metadata: { ...(data.metadata ?? {}) },
    });
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- test/unit/rigProfile.test.ts`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Run the type checker**

Run: `npm run build`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add daz-ts/src/rigProfile.ts daz-ts/test/unit/rigProfile.test.ts
git commit -m "feat(daz-ts): add FigureRigProfile, anchor resolution, name-matching heuristics"
```

---

## Task 3: `buildRigProfile` / `buildRigProfilesFromSnapshot`

**Files:**
- Modify: `daz-ts/src/rigProfile.ts`
- Modify: `daz-ts/test/unit/rigProfile.test.ts`

**Interfaces:**
- Consumes: `RigMetadataSource` (Task 1), `BoneProfile`, `FigureRigProfile`, `detectFigureFamily`, `looksLikeTwist`, `looksLikeHelper`, `asVector3` (Tasks 1-2)
- Produces: `defaultAxisLimitsForBone(name)`, `buildRigProfile(skeleton)`, `buildRigProfilesFromSnapshot(snapshot)`

- [ ] **Step 1: Write the failing test**

```ts
// append to daz-ts/test/unit/rigProfile.test.ts
import { AxisLimit, buildRigProfile, buildRigProfilesFromSnapshot, defaultAxisLimitsForBone } from "../../src/rigProfile.js";

function fakeMetadataSkeleton(identifierValue: string, label: string | null, bones: Array<Record<string, unknown>>) {
  return {
    identifier: { value: identifierValue },
    label: async () => label,
    boneMetadata: async () => bones,
  };
}

describe("defaultAxisLimitsForBone", () => {
  it("returns loose limits for a forearm bone, spanning both positive and negative degrees", () => {
    const limits = defaultAxisLimitsForBone("r_forearm");
    expect(limits.x).toBeInstanceOf(AxisLimit);
    expect(limits.x!.minDegrees).toBeLessThan(0);
    expect(limits.x!.maxDegrees).toBeGreaterThan(0);
  });

  it("returns {} for a bone name matching no preset", () => {
    expect(defaultAxisLimitsForBone("some_prop_root")).toEqual({});
  });
});

describe("buildRigProfile", () => {
  it("detects genesis_9 family and resolves snake_case anchors from boneMetadata()", async () => {
    const skeleton = fakeMetadataSkeleton("Genesis9", "Genesis 9", [
      { name: "hip", label: "Hip", parent_name: null, rotation_order: "XYZ", local_position: [0, 0, 0], world_position: [0, 0, 0], local_euler: [0, 0, 0] },
      { name: "l_hand", label: "Left Hand", parent_name: "hip", local_position: [1, 0, 0] },
      { name: "r_hand", label: "Right Hand", parent_name: "hip", local_position: [-1, 0, 0] },
      { name: "l_foot", label: "Left Foot", parent_name: "hip" },
      { name: "r_foot", label: "Right Foot", parent_name: "hip" },
    ]);
    const profile = await buildRigProfile(skeleton);
    expect(profile.figureLabel).toBe("Genesis 9");
    expect(profile.family).toBe("genesis_9");
    expect(profile.anchor("r_hand")?.boneName).toBe("r_hand");
    expect(profile.bone("l_hand").localPosition).toEqual([1, 0, 0]);
  });

  it("falls back to the identifier value when label() returns null", async () => {
    const skeleton = fakeMetadataSkeleton("Genesis9", null, [{ name: "hip", parent_name: null }]);
    const profile = await buildRigProfile(skeleton);
    expect(profile.figureLabel).toBe("Genesis9");
  });
});

describe("buildRigProfilesFromSnapshot", () => {
  it("builds one profile per skeleton, keyed by both label and internal name", () => {
    const snapshot = [
      {
        name: "Genesis9",
        label: "Genesis 9",
        bones: [
          { name: "hip", label: "Hip", parent_name: null },
          { name: "r_hand", label: "Right Hand", parent_name: "hip" },
        ],
      },
    ];
    const profiles = buildRigProfilesFromSnapshot(snapshot);
    expect(profiles["Genesis 9"]).toBeDefined();
    expect(profiles["Genesis9"]).toBe(profiles["Genesis 9"]);
    expect(profiles["Genesis 9"].anchor("r_hand")?.boneName).toBe("r_hand");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- test/unit/rigProfile.test.ts`
Expected: FAIL — `buildRigProfile`/`buildRigProfilesFromSnapshot`/`defaultAxisLimitsForBone` are not exported

- [ ] **Step 3: Write minimal implementation**

Append to `daz-ts/src/rigProfile.ts`:

```ts
// ── default axis limits ──────────────────────────────────────────────────────

const AXIS_LIMIT_PRESETS: ReadonlyArray<[readonly string[], Partial<Record<AxisName, [number, number]>>]> = [
  [["head", "neck"], { x: [-70, 70], y: [-85, 85], z: [-45, 45] }],
  [["shoulder", "clavicle", "upper_arm"], { x: [-120, 120], y: [-120, 120], z: [-140, 140] }],
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
  const bones = raw.map((item) => boneProfileFromRaw(item));
  const family = detectFigureFamily(bones.map((bone) => bone.name));
  return new FigureRigProfile({
    figureLabel,
    family,
    bones,
    metadata: { boneCount: bones.length, source: "daz-ts" },
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
    const profile = new FigureRigProfile({ figureLabel: label, family, bones, metadata: { boneCount: bones.length, source: "snapshot" } });
    profiles[label] = profile;
    if (name && name !== label) profiles[name] = profile;
  }
  return profiles;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- test/unit/rigProfile.test.ts`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Run the type checker**

Run: `npm run build`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add daz-ts/src/rigProfile.ts daz-ts/test/unit/rigProfile.test.ts
git commit -m "feat(daz-ts): add buildRigProfile/buildRigProfilesFromSnapshot"
```

---

## Task 4: `interactionPlan.ts` — constraint types, `ValidationIssue`, `SolveOptions`

**Files:**
- Create: `daz-ts/src/interactionPlan.ts`
- Test: `daz-ts/test/unit/interactionPlan.test.ts`

**Interfaces:**
- Consumes: `Vector3`, `Rotation3`, `AnchorTargetLike` (from `rigProfile.ts`, Task 2)
- Produces: `PoseTarget`, `HandTarget`, `FootTarget`, `ContactTarget`, `LookAtTarget`, `BalanceTarget` (each with `toDict()`), `InteractionConstraint` union type, `ValidationIssue`, `SolveOptions`, `SolveBackend`, `SolveOptionsDict`

- [ ] **Step 1: Write the failing test**

```ts
// daz-ts/test/unit/interactionPlan.test.ts
import { describe, expect, it } from "vitest";
import {
  BalanceTarget,
  ContactTarget,
  FootTarget,
  HandTarget,
  LookAtTarget,
  PoseTarget,
  SolveOptions,
  ValidationIssue,
} from "../../src/interactionPlan.js";

describe("constraint types", () => {
  it("PoseTarget.toDict carries kind and optional fields", () => {
    const target = new PoseTarget({ figureLabel: "Genesis 9", boneName: "r_hand", orientation: [0, 0, 0] });
    expect(target.toDict()).toEqual({
      kind: "PoseTarget",
      figureLabel: "Genesis 9",
      boneName: "r_hand",
      position: null,
      orientation: [0, 0, 0],
    });
  });

  it("HandTarget/FootTarget default offset to [0,0,0] and carry their own kind", () => {
    const hand = new HandTarget({ figureLabel: "Genesis 9", anchorName: "r_hand", targetPoint: [1, 2, 3] });
    const foot = new FootTarget({ figureLabel: "Genesis 9", anchorName: "l_foot", targetFigure: "Partner", targetAnchor: "r_hand" });
    expect(hand.kind).toBe("HandTarget");
    expect(hand.offset).toEqual([0, 0, 0]);
    expect(foot.kind).toBe("FootTarget");
    expect(foot.toDict().targetAnchor).toBe("r_hand");
  });

  it("ContactTarget/LookAtTarget/BalanceTarget toDict shapes", () => {
    const contact = new ContactTarget({ sourceFigure: "A", sourceBone: "r_hand", targetFigure: "B", targetBone: "chest" });
    expect(contact.toDict().kind).toBe("ContactTarget");

    const lookAt = new LookAtTarget({ figureLabel: "A", boneName: "head", targetPoint: [0, 1, 2] });
    expect(lookAt.toDict()).toEqual({ kind: "LookAtTarget", figureLabel: "A", boneName: "head", targetPoint: [0, 1, 2] });

    const balance = new BalanceTarget({ figureLabel: "A", pelvisBone: "hip", supportPoints: [[0, 0, 0]] });
    expect(balance.toDict().kind).toBe("BalanceTarget");
    expect(balance.centerOfMassHint).toBeNull();
  });
});

describe("ValidationIssue", () => {
  it("toDict carries all fields", () => {
    const issue = new ValidationIssue("error", "Genesis 9", 2, "Unknown bone");
    expect(issue.toDict()).toEqual({ severity: "error", figureLabel: "Genesis 9", constraintIndex: 2, message: "Unknown bone" });
  });
});

describe("SolveOptions", () => {
  it("defaults match dazpy's SolveOptions defaults", () => {
    const options = new SolveOptions();
    expect(options.toDict()).toEqual({
      backend: "auto",
      maxIterations: 100,
      useJointLimits: true,
      restPoseWeight: 0.15,
      contactWeight: 1.0,
      positionWeight: 1.0,
      orientationWeight: 0.25,
    });
  });

  it("round-trips through toDict/fromDict with overrides", () => {
    const options = new SolveOptions({ backend: "auto", maxIterations: 25 });
    const restored = SolveOptions.fromDict(options.toDict());
    expect(restored.backend).toBe("auto");
    expect(restored.maxIterations).toBe(25);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- test/unit/interactionPlan.test.ts`
Expected: FAIL — `Cannot find module '../../src/interactionPlan.js'`

- [ ] **Step 3: Write minimal implementation**

```ts
// daz-ts/src/interactionPlan.ts

/**
 * Interaction-plan data model: constraints (pose/anchor/contact/look-at/
 * balance targets), `InteractionPlan`/`InteractionRecipe`, validation,
 * target resolution, and coarse pose-patch staging. Ports the non-solver
 * half of dazpy's `_interaction.py`. Live IK alignment (`alignLimbTargets`)
 * is filled in by `interactionSolve.ts` in Phase 5B
 * (`daz-script-server-sf7y.2`) -- this file only stages figure positions.
 */

import type { AnchorTargetLike, FigureRigProfile, RigSceneSource, Vector3, Rotation3 } from "./rigProfile.js";
import { addVec3, averageVec3, lookupRigProfile, midpointVec3, subVec3 } from "./rigProfile.js";

// ── constraint types ─────────────────────────────────────────────────────────

export interface PoseTargetDict {
  kind: "PoseTarget";
  figureLabel: string;
  boneName: string;
  position: Vector3 | null;
  orientation: Rotation3 | null;
}

export class PoseTarget {
  readonly kind = "PoseTarget" as const;
  readonly figureLabel: string;
  readonly boneName: string;
  readonly position: Vector3 | null;
  readonly orientation: Rotation3 | null;

  constructor(init: { figureLabel: string; boneName: string; position?: Vector3 | null; orientation?: Rotation3 | null }) {
    this.figureLabel = init.figureLabel;
    this.boneName = init.boneName;
    this.position = init.position ?? null;
    this.orientation = init.orientation ?? null;
  }

  toDict(): PoseTargetDict {
    return { kind: this.kind, figureLabel: this.figureLabel, boneName: this.boneName, position: this.position, orientation: this.orientation };
  }
}

export interface AnchorTargetInit {
  figureLabel: string;
  anchorName: string;
  targetFigure?: string | null;
  targetAnchor?: string | null;
  targetPoint?: Vector3 | null;
  offset?: Vector3;
}

export interface AnchorTargetDict {
  kind: "HandTarget" | "FootTarget";
  figureLabel: string;
  anchorName: string;
  targetFigure: string | null;
  targetAnchor: string | null;
  targetPoint: Vector3 | null;
  offset: Vector3;
}

abstract class AnchorTargetBase implements AnchorTargetLike {
  abstract readonly kind: "HandTarget" | "FootTarget";
  readonly figureLabel: string;
  readonly anchorName: string;
  readonly targetFigure: string | null;
  readonly targetAnchor: string | null;
  readonly targetPoint: Vector3 | null;
  readonly offset: Vector3;

  constructor(init: AnchorTargetInit) {
    this.figureLabel = init.figureLabel;
    this.anchorName = init.anchorName;
    this.targetFigure = init.targetFigure ?? null;
    this.targetAnchor = init.targetAnchor ?? null;
    this.targetPoint = init.targetPoint ?? null;
    this.offset = init.offset ?? [0, 0, 0];
  }

  toDict(): AnchorTargetDict {
    return {
      kind: this.kind,
      figureLabel: this.figureLabel,
      anchorName: this.anchorName,
      targetFigure: this.targetFigure,
      targetAnchor: this.targetAnchor,
      targetPoint: this.targetPoint,
      offset: this.offset,
    };
  }
}

/** Place a hand anchor against another anchor or world point. */
export class HandTarget extends AnchorTargetBase {
  readonly kind = "HandTarget" as const;
}

/** Place a foot anchor against another anchor, world point, or floor. */
export class FootTarget extends AnchorTargetBase {
  readonly kind = "FootTarget" as const;
}

export interface ContactTargetDict {
  kind: "ContactTarget";
  sourceFigure: string;
  sourceBone: string;
  targetFigure: string | null;
  targetBone: string | null;
  targetPoint: Vector3 | null;
}

/** Keep one figure bone in contact with a target figure or world point. */
export class ContactTarget {
  readonly kind = "ContactTarget" as const;
  readonly sourceFigure: string;
  readonly sourceBone: string;
  readonly targetFigure: string | null;
  readonly targetBone: string | null;
  readonly targetPoint: Vector3 | null;

  constructor(init: { sourceFigure: string; sourceBone: string; targetFigure?: string | null; targetBone?: string | null; targetPoint?: Vector3 | null }) {
    this.sourceFigure = init.sourceFigure;
    this.sourceBone = init.sourceBone;
    this.targetFigure = init.targetFigure ?? null;
    this.targetBone = init.targetBone ?? null;
    this.targetPoint = init.targetPoint ?? null;
  }

  toDict(): ContactTargetDict {
    return {
      kind: this.kind,
      sourceFigure: this.sourceFigure,
      sourceBone: this.sourceBone,
      targetFigure: this.targetFigure,
      targetBone: this.targetBone,
      targetPoint: this.targetPoint,
    };
  }
}

export interface LookAtTargetDict {
  kind: "LookAtTarget";
  figureLabel: string;
  boneName: string;
  targetPoint: Vector3;
}

/** Aim a bone toward a point in space. */
export class LookAtTarget {
  readonly kind = "LookAtTarget" as const;
  readonly figureLabel: string;
  readonly boneName: string;
  readonly targetPoint: Vector3;

  constructor(init: { figureLabel: string; boneName: string; targetPoint: Vector3 });
  constructor(figureLabel: string, boneName: string, targetPoint: Vector3);
  constructor(
    initOrFigureLabel: { figureLabel: string; boneName: string; targetPoint: Vector3 } | string,
    boneName?: string,
    targetPoint?: Vector3,
  ) {
    if (typeof initOrFigureLabel === "string") {
      this.figureLabel = initOrFigureLabel;
      this.boneName = boneName!;
      this.targetPoint = targetPoint!;
    } else {
      this.figureLabel = initOrFigureLabel.figureLabel;
      this.boneName = initOrFigureLabel.boneName;
      this.targetPoint = initOrFigureLabel.targetPoint;
    }
  }

  toDict(): LookAtTargetDict {
    return { kind: this.kind, figureLabel: this.figureLabel, boneName: this.boneName, targetPoint: this.targetPoint };
  }
}

export interface BalanceTargetDict {
  kind: "BalanceTarget";
  figureLabel: string;
  pelvisBone: string;
  supportPoints: Vector3[];
  centerOfMassHint: Vector3 | null;
}

/** Stabilize a figure around a support surface or center-of-mass hint. */
export class BalanceTarget {
  readonly kind = "BalanceTarget" as const;
  readonly figureLabel: string;
  readonly pelvisBone: string;
  readonly supportPoints: Vector3[];
  readonly centerOfMassHint: Vector3 | null;

  constructor(init: { figureLabel: string; pelvisBone: string; supportPoints?: Vector3[]; centerOfMassHint?: Vector3 | null }) {
    this.figureLabel = init.figureLabel;
    this.pelvisBone = init.pelvisBone;
    this.supportPoints = init.supportPoints ?? [];
    this.centerOfMassHint = init.centerOfMassHint ?? null;
  }

  toDict(): BalanceTargetDict {
    return {
      kind: this.kind,
      figureLabel: this.figureLabel,
      pelvisBone: this.pelvisBone,
      supportPoints: this.supportPoints.map((p) => [...p] as Vector3),
      centerOfMassHint: this.centerOfMassHint,
    };
  }
}

export type InteractionConstraint = PoseTarget | HandTarget | FootTarget | ContactTarget | LookAtTarget | BalanceTarget;

// ── ValidationIssue ──────────────────────────────────────────────────────────

export interface ValidationIssueDict {
  severity: "error" | "warning";
  figureLabel: string | null;
  constraintIndex: number;
  message: string;
}

/** A problem found while validating an interaction plan. */
export class ValidationIssue {
  constructor(
    readonly severity: "error" | "warning",
    readonly figureLabel: string | null,
    readonly constraintIndex: number,
    readonly message: string,
  ) {}

  toDict(): ValidationIssueDict {
    return { severity: this.severity, figureLabel: this.figureLabel, constraintIndex: this.constraintIndex, message: this.message };
  }
}

// ── SolveOptions ─────────────────────────────────────────────────────────────

export type SolveBackend = "scipy" | "pinocchio" | "ikpy" | "auto";

export interface SolveOptionsDict {
  backend: SolveBackend;
  maxIterations: number;
  useJointLimits: boolean;
  restPoseWeight: number;
  contactWeight: number;
  positionWeight: number;
  orientationWeight: number;
}

/** Tunable options for the solver phase (`interactionSolve.ts`, Phase 5B). */
export class SolveOptions {
  readonly backend: SolveBackend;
  readonly maxIterations: number;
  readonly useJointLimits: boolean;
  readonly restPoseWeight: number;
  readonly contactWeight: number;
  readonly positionWeight: number;
  readonly orientationWeight: number;

  constructor(init: Partial<SolveOptionsDict> = {}) {
    this.backend = init.backend ?? "auto";
    this.maxIterations = init.maxIterations ?? 100;
    this.useJointLimits = init.useJointLimits ?? true;
    this.restPoseWeight = init.restPoseWeight ?? 0.15;
    this.contactWeight = init.contactWeight ?? 1.0;
    this.positionWeight = init.positionWeight ?? 1.0;
    this.orientationWeight = init.orientationWeight ?? 0.25;
  }

  toDict(): SolveOptionsDict {
    return {
      backend: this.backend,
      maxIterations: this.maxIterations,
      useJointLimits: this.useJointLimits,
      restPoseWeight: this.restPoseWeight,
      contactWeight: this.contactWeight,
      positionWeight: this.positionWeight,
      orientationWeight: this.orientationWeight,
    };
  }

  static fromDict(data: Partial<SolveOptionsDict>): SolveOptions {
    return new SolveOptions(data);
  }
}
```

`RigSceneSource`, `FigureRigProfile`, `addVec3`, `averageVec3`, `lookupRigProfile`, `midpointVec3`, `subVec3` are imported now for use starting Task 6-8; unused-import errors are fine to ignore until then since `tsconfig.json` has no `noUnusedLocals` -- **do not** add that compiler option as part of this plan.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- test/unit/interactionPlan.test.ts`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Run the type checker**

Run: `npm run build`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add daz-ts/src/interactionPlan.ts daz-ts/test/unit/interactionPlan.test.ts
git commit -m "feat(daz-ts): add interaction constraint types, ValidationIssue, SolveOptions"
```

---

## Task 5: `InteractionPlan` (validate/resolveTargets/toDict/fromDict) + `resolveInteractionTarget`

**Files:**
- Modify: `daz-ts/src/interactionPlan.ts`
- Modify: `daz-ts/test/unit/interactionPlan.test.ts`

**Interfaces:**
- Consumes: constraint types + `ValidationIssue`/`SolveOptions` (Task 4); `FigureRigProfile`, `lookupRigProfile`, `asVector3`, `ResolvedInteractionTarget` (from `rigProfile.ts`)
- Produces: `InteractionPlan`, `InteractionPlanDict`, `resolveInteractionTarget(target, rigProfiles)`

- [ ] **Step 1: Write the failing test**

```ts
// append to daz-ts/test/unit/interactionPlan.test.ts
import { BoneProfile, FigureRigProfile } from "../../src/rigProfile.js";
import { HandTarget, FootTarget, InteractionPlan, LookAtTarget, PoseTarget, resolveInteractionTarget } from "../../src/interactionPlan.js";

function genesis9Profile(): FigureRigProfile {
  return new FigureRigProfile({
    figureLabel: "Genesis 9",
    family: "genesis_9",
    bones: [
      new BoneProfile({ name: "hip" }),
      new BoneProfile({ name: "r_hand", parentName: "hip" }),
      new BoneProfile({ name: "l_foot", parentName: "hip" }),
      new BoneProfile({ name: "head", parentName: "hip" }),
    ],
  });
}

describe("InteractionPlan", () => {
  it("validate + round-trip: a fully-valid plan produces no issues", () => {
    const plan = new InteractionPlan({
      actors: ["Genesis 9"],
      constraints: [
        new PoseTarget({ figureLabel: "Genesis 9", boneName: "r_hand", orientation: [0, 0, 0] }),
        new LookAtTarget({ figureLabel: "Genesis 9", boneName: "head", targetPoint: [0, 1, 2] }),
        new HandTarget({ figureLabel: "Genesis 9", anchorName: "r_hand", targetPoint: [1, 2, 3] }),
        new FootTarget({ figureLabel: "Genesis 9", anchorName: "l_foot", targetFigure: "Genesis 9", targetAnchor: "r_hand" }),
      ],
    });

    const data = plan.toDict();
    const restored = InteractionPlan.fromDict(data);
    const issues = restored.validate({ "Genesis 9": genesis9Profile() });

    expect(data.constraints).toHaveLength(4);
    expect(issues).toEqual([]);
  });

  it("validate reports an error for a missing bone", () => {
    const profile = new FigureRigProfile({ figureLabel: "Genesis 9", family: "genesis_9", bones: [new BoneProfile({ name: "hip" })] });
    const plan = new InteractionPlan({
      actors: ["Genesis 9"],
      constraints: [new PoseTarget({ figureLabel: "Genesis 9", boneName: "r_hand", orientation: [0, 0, 0] })],
    });

    const issues = plan.validate({ "Genesis 9": profile });

    expect(issues).toHaveLength(1);
    expect(issues[0].severity).toBe("error");
    expect(issues[0].message).toContain("r_hand");
  });

  it("resolveTargets resolves HandTarget/FootTarget constraints only", () => {
    const plan = new InteractionPlan({
      actors: ["Genesis 9"],
      constraints: [
        new PoseTarget({ figureLabel: "Genesis 9", boneName: "r_hand" }),
        new HandTarget({ figureLabel: "Genesis 9", anchorName: "r_hand", targetPoint: [1, 2, 3] }),
      ],
    });
    const resolved = plan.resolveTargets({ "Genesis 9": genesis9Profile() });
    expect(resolved).toHaveLength(1);
    expect(resolved[0].boneName).toBe("r_hand");
  });
});

describe("resolveInteractionTarget", () => {
  it("resolves a same-figure target", () => {
    const bones = [
      new BoneProfile({ name: "hip" }),
      new BoneProfile({ name: "r_hand", parentName: "hip", localPosition: [10, 20, 30] }),
    ];
    const profile = new FigureRigProfile({ figureLabel: "Genesis 9", family: "genesis_9", bones });
    const resolved = resolveInteractionTarget(
      new HandTarget({ figureLabel: "Genesis 9", anchorName: "r_hand", targetPoint: [1, 2, 3], offset: [0.5, 0, -0.5] }),
      { "Genesis 9": profile },
    );
    expect(resolved.boneName).toBe("r_hand");
    expect(resolved.targetPoint).toEqual([1.5, 2, 2.5]);
    expect(resolved.targetBone).toBeNull();
  });

  it("resolves a cross-figure target and finds the target bone", () => {
    const sourceProfile = new FigureRigProfile({
      figureLabel: "Genesis 9",
      family: "genesis_9",
      bones: [new BoneProfile({ name: "hip" }), new BoneProfile({ name: "r_hand", parentName: "hip" })],
    });
    const targetProfile = new FigureRigProfile({
      figureLabel: "Partner",
      family: "genesis_9",
      bones: [new BoneProfile({ name: "hip" }), new BoneProfile({ name: "r_hand", parentName: "hip", localPosition: [4, 5, 6] })],
    });

    const resolved = resolveInteractionTarget(
      new FootTarget({ figureLabel: "Genesis 9", anchorName: "r_hand", targetFigure: "Partner", targetAnchor: "r_hand" }),
      { "Genesis 9": sourceProfile, Partner: targetProfile },
    );

    expect(resolved.targetFigure).toBe("Partner");
    expect(resolved.targetBone).toBe("r_hand");
    expect(resolved.targetPoint).toEqual([4, 5, 6]);
  });

  it("throws for an unknown figure", () => {
    expect(() => resolveInteractionTarget(new HandTarget({ figureLabel: "Nobody", anchorName: "r_hand" }), {})).toThrow(/Unknown figure/);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- test/unit/interactionPlan.test.ts`
Expected: FAIL — `InteractionPlan`/`resolveInteractionTarget` are not exported

- [ ] **Step 3: Write minimal implementation**

Replace Task 4's import line at the top of `daz-ts/src/interactionPlan.ts` with:

```ts
import type { AnchorTargetLike, FigureRigProfile, RigSceneSource, Vector3, Rotation3 } from "./rigProfile.js";
import { addVec3, asVector3, averageVec3, lookupRigProfile, midpointVec3, subVec3, ResolvedInteractionTarget } from "./rigProfile.js";
```

(`FigureRigProfile` moves from a type-only import to also being used as a parameter type here; `ResolvedInteractionTarget` is now imported as a value since `InteractionPlan.resolveTargets`/`resolveInteractionTarget` construct and return it.)

```ts
// ── InteractionPlan ──────────────────────────────────────────────────────────

export interface InteractionPlanDict {
  actors: string[];
  constraints: Array<Record<string, unknown>>;
  options: SolveOptionsDict;
  metadata: Record<string, unknown>;
}

export interface InteractionPlanInit {
  actors: string[];
  constraints?: InteractionConstraint[];
  options?: SolveOptions;
  metadata?: Record<string, unknown>;
}

/** A collection of interaction constraints across one or more figures. */
export class InteractionPlan {
  readonly actors: string[];
  readonly constraints: InteractionConstraint[];
  readonly options: SolveOptions;
  readonly metadata: Record<string, unknown>;

  constructor(init: InteractionPlanInit) {
    this.actors = [...init.actors];
    this.constraints = init.constraints ? [...init.constraints] : [];
    this.options = init.options ?? new SolveOptions();
    this.metadata = init.metadata ?? {};
  }

  toDict(): InteractionPlanDict {
    return {
      actors: [...this.actors],
      constraints: this.constraints.map((c) => c.toDict()),
      options: this.options.toDict(),
      metadata: { ...this.metadata },
    };
  }

  static fromDict(data: Partial<InteractionPlanDict>): InteractionPlan {
    const constraints: InteractionConstraint[] = [];
    for (const item of data.constraints ?? []) {
      const kind = item.kind as string | undefined;
      if (kind === "PoseTarget") {
        constraints.push(
          new PoseTarget({
            figureLabel: String(item.figureLabel ?? ""),
            boneName: String(item.boneName ?? ""),
            position: asVector3(item.position),
            orientation: asVector3(item.orientation),
          }),
        );
      } else if (kind === "HandTarget" || kind === "FootTarget") {
        const init = {
          figureLabel: String(item.figureLabel ?? ""),
          anchorName: String(item.anchorName ?? ""),
          targetFigure: (item.targetFigure as string | null | undefined) ?? null,
          targetAnchor: (item.targetAnchor as string | null | undefined) ?? null,
          targetPoint: asVector3(item.targetPoint),
          offset: asVector3(item.offset) ?? ([0, 0, 0] as Vector3),
        };
        constraints.push(kind === "HandTarget" ? new HandTarget(init) : new FootTarget(init));
      } else if (kind === "ContactTarget") {
        constraints.push(
          new ContactTarget({
            sourceFigure: String(item.sourceFigure ?? ""),
            sourceBone: String(item.sourceBone ?? ""),
            targetFigure: (item.targetFigure as string | null | undefined) ?? null,
            targetBone: (item.targetBone as string | null | undefined) ?? null,
            targetPoint: asVector3(item.targetPoint),
          }),
        );
      } else if (kind === "LookAtTarget") {
        const targetPoint = asVector3(item.targetPoint);
        if (targetPoint === null) continue;
        constraints.push(new LookAtTarget({ figureLabel: String(item.figureLabel ?? ""), boneName: String(item.boneName ?? ""), targetPoint }));
      } else if (kind === "BalanceTarget") {
        const rawSupport = (item.supportPoints as unknown[] | undefined) ?? [];
        constraints.push(
          new BalanceTarget({
            figureLabel: String(item.figureLabel ?? ""),
            pelvisBone: String(item.pelvisBone ?? ""),
            supportPoints: rawSupport.map((p) => asVector3(p)).filter((p): p is Vector3 => p !== null),
            centerOfMassHint: asVector3(item.centerOfMassHint),
          }),
        );
      }
    }
    return new InteractionPlan({
      actors: [...(data.actors ?? [])],
      constraints,
      options: SolveOptions.fromDict(data.options ?? {}),
      metadata: { ...(data.metadata ?? {}) },
    });
  }

  /** Validate that every referenced figure/bone/anchor exists. Never throws -- unresolvable references become `ValidationIssue`s. */
  validate(rigProfiles: Record<string, FigureRigProfile>): ValidationIssue[] {
    const issues: ValidationIssue[] = [];
    this.constraints.forEach((constraint, index) => {
      if (constraint instanceof PoseTarget || constraint instanceof LookAtTarget) {
        const profile = lookupRigProfile(rigProfiles, constraint.figureLabel);
        if (profile === null) {
          issues.push(new ValidationIssue("error", constraint.figureLabel, index, `Unknown figure ${constraint.figureLabel}`));
          return;
        }
        if (!profile.boneNames().includes(constraint.boneName)) {
          issues.push(new ValidationIssue("error", constraint.figureLabel, index, `Unknown bone ${constraint.boneName} on figure ${constraint.figureLabel}`));
        }
      } else if (constraint instanceof ContactTarget) {
        const profile = lookupRigProfile(rigProfiles, constraint.sourceFigure);
        if (profile === null) {
          issues.push(new ValidationIssue("error", constraint.sourceFigure, index, `Unknown source figure ${constraint.sourceFigure}`));
          return;
        }
        if (!profile.boneNames().includes(constraint.sourceBone)) {
          issues.push(new ValidationIssue("error", constraint.sourceFigure, index, `Unknown source bone ${constraint.sourceBone} on figure ${constraint.sourceFigure}`));
        }
        if (constraint.targetFigure && constraint.targetBone) {
          const targetProfile = lookupRigProfile(rigProfiles, constraint.targetFigure);
          if (targetProfile === null) {
            issues.push(new ValidationIssue("error", constraint.targetFigure, index, `Unknown target figure ${constraint.targetFigure}`));
          } else if (!targetProfile.boneNames().includes(constraint.targetBone)) {
            issues.push(new ValidationIssue("error", constraint.targetFigure, index, `Unknown target bone ${constraint.targetBone} on figure ${constraint.targetFigure}`));
          }
        }
      } else if (constraint instanceof BalanceTarget) {
        const profile = lookupRigProfile(rigProfiles, constraint.figureLabel);
        if (profile === null) {
          issues.push(new ValidationIssue("error", constraint.figureLabel, index, `Unknown figure ${constraint.figureLabel}`));
          return;
        }
        if (!profile.boneNames().includes(constraint.pelvisBone)) {
          issues.push(new ValidationIssue("error", constraint.figureLabel, index, `Unknown pelvis bone ${constraint.pelvisBone} on figure ${constraint.figureLabel}`));
        }
      } else if (constraint instanceof HandTarget || constraint instanceof FootTarget) {
        const profile = lookupRigProfile(rigProfiles, constraint.figureLabel);
        if (profile === null) {
          issues.push(new ValidationIssue("error", constraint.figureLabel, index, `Unknown figure ${constraint.figureLabel}`));
          return;
        }
        if (!profile.anchorNames().includes(constraint.anchorName)) {
          issues.push(new ValidationIssue("error", constraint.figureLabel, index, `Unknown anchor ${constraint.anchorName} on figure ${constraint.figureLabel}`));
        }
        if (constraint.targetFigure && constraint.targetAnchor) {
          const targetProfile = lookupRigProfile(rigProfiles, constraint.targetFigure);
          if (targetProfile === null) {
            issues.push(new ValidationIssue("error", constraint.targetFigure, index, `Unknown target figure ${constraint.targetFigure}`));
          } else if (!targetProfile.anchorNames().includes(constraint.targetAnchor)) {
            issues.push(new ValidationIssue("error", constraint.targetFigure, index, `Unknown target anchor ${constraint.targetAnchor} on figure ${constraint.targetFigure}`));
          }
        }
      }
    });
    return issues;
  }

  /** Resolve every `HandTarget`/`FootTarget` constraint into concrete anchors and points. */
  resolveTargets(rigProfiles: Record<string, FigureRigProfile>): ResolvedInteractionTarget[] {
    const resolved: ResolvedInteractionTarget[] = [];
    for (const constraint of this.constraints) {
      if (constraint instanceof HandTarget || constraint instanceof FootTarget) {
        const profile = lookupRigProfile(rigProfiles, constraint.figureLabel);
        if (profile === null) continue;
        resolved.push(resolveInteractionTarget(constraint, rigProfiles));
      }
    }
    return resolved;
  }
}

/** Resolve a hand/foot interaction target against the available rig profiles. Throws if the figure is unknown. */
export function resolveInteractionTarget(target: AnchorTargetLike, rigProfiles: Record<string, FigureRigProfile>): ResolvedInteractionTarget {
  const profile = lookupRigProfile(rigProfiles, target.figureLabel);
  if (profile === null) throw new Error(`Unknown figure for target resolution: ${target.figureLabel}`);
  return profile.resolveAnchorTarget(target, rigProfiles);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- test/unit/interactionPlan.test.ts`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Run the type checker**

Run: `npm run build`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add daz-ts/src/interactionPlan.ts daz-ts/test/unit/interactionPlan.test.ts
git commit -m "feat(daz-ts): add InteractionPlan validate/resolveTargets, resolveInteractionTarget"
```

---

## Task 6: `InteractionRecipe`

**Files:**
- Modify: `daz-ts/src/interactionPlan.ts`
- Modify: `daz-ts/test/unit/interactionPlan.test.ts`

**Interfaces:**
- Consumes: `InteractionPlan`, `InteractionConstraint`, `SolveOptions` (Tasks 4-5)
- Produces: `RecipeKind`, `InteractionRecipe`, `InteractionRecipeDict`

- [ ] **Step 1: Write the failing test**

```ts
// append to daz-ts/test/unit/interactionPlan.test.ts
import { HandTarget, InteractionRecipe } from "../../src/interactionPlan.js";

describe("InteractionRecipe", () => {
  it("toPlan carries actors/constraints/options/metadata", () => {
    const recipe = new InteractionRecipe({
      kind: "touch",
      actors: ["Genesis 9", "Partner"],
      constraints: [new HandTarget({ figureLabel: "Genesis 9", anchorName: "r_hand", targetFigure: "Partner", targetAnchor: "l_shoulder" })],
      metadata: { scenario: "contact" },
    });
    const plan = recipe.toPlan();
    expect(plan.actors).toEqual(["Genesis 9", "Partner"]);
    expect(plan.constraints).toHaveLength(1);
  });

  it("round-trips through toDict/fromDict, preserving kind and constraint types", () => {
    const recipe = new InteractionRecipe({
      kind: "touch",
      actors: ["Genesis 9", "Partner"],
      constraints: [new HandTarget({ figureLabel: "Genesis 9", anchorName: "r_hand", targetFigure: "Partner", targetAnchor: "l_shoulder" })],
      metadata: { scenario: "contact" },
    });
    const restored = InteractionRecipe.fromDict(recipe.toDict());
    expect(restored.kind).toBe("touch");
    expect(restored.actors).toEqual(["Genesis 9", "Partner"]);
    expect(restored.constraints).toHaveLength(1);
    expect(restored.constraints[0]).toBeInstanceOf(HandTarget);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- test/unit/interactionPlan.test.ts`
Expected: FAIL — `InteractionRecipe` is not exported

- [ ] **Step 3: Write minimal implementation**

Append to `daz-ts/src/interactionPlan.ts`:

```ts
// ── InteractionRecipe ────────────────────────────────────────────────────────

export type RecipeKind = "sit" | "touch" | "kiss" | "fight" | "handshake" | "hug" | "face_each_other" | "custom";

export interface InteractionRecipeDict extends InteractionPlanDict {
  kind: RecipeKind;
}

export interface InteractionRecipeInit {
  kind: RecipeKind;
  actors: string[];
  constraints?: InteractionConstraint[];
  options?: SolveOptions;
  metadata?: Record<string, unknown>;
}

/** A higher-level interaction preset that expands into an interaction plan. Recipe builders (`buildSitRecipe`, etc.) land in Phase 5C. */
export class InteractionRecipe {
  readonly kind: RecipeKind;
  readonly actors: string[];
  readonly constraints: InteractionConstraint[];
  readonly options: SolveOptions;
  readonly metadata: Record<string, unknown>;

  constructor(init: InteractionRecipeInit) {
    this.kind = init.kind;
    this.actors = [...init.actors];
    this.constraints = init.constraints ? [...init.constraints] : [];
    this.options = init.options ?? new SolveOptions();
    this.metadata = init.metadata ?? {};
  }

  toPlan(): InteractionPlan {
    return new InteractionPlan({ actors: [...this.actors], constraints: [...this.constraints], options: this.options, metadata: { ...this.metadata } });
  }

  toDict(): InteractionRecipeDict {
    return { kind: this.kind, ...this.toPlan().toDict() };
  }

  static fromDict(data: Partial<InteractionRecipeDict>): InteractionRecipe {
    const plan = InteractionPlan.fromDict(data);
    return new InteractionRecipe({ kind: data.kind ?? "custom", actors: plan.actors, constraints: plan.constraints, options: plan.options, metadata: plan.metadata });
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- test/unit/interactionPlan.test.ts`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Run the type checker**

Run: `npm run build`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add daz-ts/src/interactionPlan.ts daz-ts/test/unit/interactionPlan.test.ts
git commit -m "feat(daz-ts): add InteractionRecipe"
```

---

## Task 7: `InteractionPosePatch` + `LimbAlignmentResult` (data type) + `PreparedInteractionResult`

**Files:**
- Modify: `daz-ts/src/interactionPlan.ts`
- Modify: `daz-ts/test/unit/interactionPlan.test.ts`

**Interfaces:**
- Consumes: `RigSceneSource`, `ResolvedInteractionTarget`, `Vector3`, `Rotation3` (from `rigProfile.ts`)
- Produces: `InteractionPosePatch`, `InteractionPosePatchDict`, `LimbAlignmentResult`, `LimbAlignmentResultDict` (a data type -- the real IK loop that produces one is `interactionSolve.ts`'s job in Phase 5B), `PreparedInteractionResult`

- [ ] **Step 1: Write the failing test**

```ts
// append to daz-ts/test/unit/interactionPlan.test.ts
import { InteractionPosePatch, LimbAlignmentResult, PreparedInteractionResult, ResolvedInteractionTarget } from "../../src/interactionPlan.js";

describe("InteractionPosePatch", () => {
  it("apply() calls setPosition once per figure via findSkeletonByLabel", async () => {
    const calls: Array<{ label: string; position: [number, number, number] }> = [];
    const scene = {
      findSkeletonByLabel: async (label: string) => ({
        setPosition: async (x: number, y: number, z: number) => {
          calls.push({ label, position: [x, y, z] });
        },
      }),
    } as any;

    const patch = new InteractionPosePatch({ figurePositions: { "Genesis 9": [1.5, 1.5, 1.5] } });
    await patch.apply(scene);

    expect(calls).toEqual([{ label: "Genesis 9", position: [1.5, 1.5, 1.5] }]);
  });

  it("toDict carries figurePositions/unresolvedTargets/diagnostics", () => {
    const patch = new InteractionPosePatch({
      figurePositions: { "Genesis 9": [1, 2, 3] },
      unresolvedTargets: [new ResolvedInteractionTarget({ figureLabel: "Partner", anchorName: "r_hand", boneName: "r_hand" })],
      diagnostics: { figureCount: 1 },
    });
    const dict = patch.toDict();
    expect(dict.figurePositions["Genesis 9"]).toEqual([1, 2, 3]);
    expect(dict.unresolvedTargets).toHaveLength(1);
    expect(dict.diagnostics.figureCount).toBe(1);
  });
});

describe("LimbAlignmentResult", () => {
  it("toDict round-trip-shape carries every field with sensible defaults", () => {
    const result = new LimbAlignmentResult({ figureLabel: "Genesis 9", anchorName: "l_hand", effectorBone: "l_hand", chain: ["hip", "l_hand"] });
    expect(result.iterations).toBe(0);
    expect(result.converged).toBe(false);
    expect(result.toDict().chain).toEqual(["hip", "l_hand"]);
  });
});

describe("PreparedInteractionResult", () => {
  it("toDict nests prepared/posePatch/alignmentResults", () => {
    // Constructed directly here; PreparedInteractionRecipe wiring is Task 8.
    const patch = new InteractionPosePatch({ figurePositions: { A: [0, 0, 0] } });
    const fakePrepared = { toDict: () => ({ stub: true }) } as any;
    const result = new PreparedInteractionResult({ prepared: fakePrepared, posePatch: patch });
    expect(result.toDict().posePatch.figurePositions.A).toEqual([0, 0, 0]);
    expect(result.alignmentResults).toEqual([]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- test/unit/interactionPlan.test.ts`
Expected: FAIL — `InteractionPosePatch`/`LimbAlignmentResult`/`PreparedInteractionResult` are not exported

- [ ] **Step 3: Write minimal implementation**

Append to `daz-ts/src/interactionPlan.ts`:

```ts
// ── InteractionPosePatch ─────────────────────────────────────────────────────

export interface InteractionPosePatchDict {
  figurePositions: Record<string, Vector3>;
  unresolvedTargets: ReturnType<ResolvedInteractionTarget["toDict"]>[];
  diagnostics: Record<string, unknown>;
}

/** A coarse figure-placement patch built from a prepared interaction. Only translates figures -- does not solve bone rotations. */
export class InteractionPosePatch {
  readonly figurePositions: Record<string, Vector3>;
  readonly unresolvedTargets: ResolvedInteractionTarget[];
  readonly diagnostics: Record<string, unknown>;

  constructor(init: { figurePositions?: Record<string, Vector3>; unresolvedTargets?: ResolvedInteractionTarget[]; diagnostics?: Record<string, unknown> } = {}) {
    this.figurePositions = init.figurePositions ?? {};
    this.unresolvedTargets = init.unresolvedTargets ?? [];
    this.diagnostics = init.diagnostics ?? {};
  }

  async apply(scene: Pick<RigSceneSource, "findSkeletonByLabel">): Promise<void> {
    for (const [figureLabel, position] of Object.entries(this.figurePositions)) {
      const skeleton = await scene.findSkeletonByLabel(figureLabel);
      await skeleton.setPosition(position[0], position[1], position[2]);
    }
  }

  toDict(): InteractionPosePatchDict {
    return {
      figurePositions: { ...this.figurePositions },
      unresolvedTargets: this.unresolvedTargets.map((t) => t.toDict()),
      diagnostics: { ...this.diagnostics },
    };
  }
}

// ── LimbAlignmentResult ──────────────────────────────────────────────────────

export interface LimbAlignmentResultDict {
  figureLabel: string;
  anchorName: string;
  effectorBone: string;
  chain: string[];
  targetPoint: Vector3 | null;
  iterations: number;
  converged: boolean;
  initialError: number | null;
  finalError: number | null;
  appliedRotations: Record<string, Rotation3>;
  diagnostics: Record<string, unknown>;
}

/** Result data for a single live target-alignment pass. Produced by `interactionSolve.ts` (Phase 5B); the data shape lives here since `interactionPlan.ts` also needs it (`PreparedInteractionResult.alignmentResults`). */
export class LimbAlignmentResult {
  readonly figureLabel: string;
  readonly anchorName: string;
  readonly effectorBone: string;
  readonly chain: string[];
  readonly targetPoint: Vector3 | null;
  readonly iterations: number;
  readonly converged: boolean;
  readonly initialError: number | null;
  readonly finalError: number | null;
  readonly appliedRotations: Record<string, Rotation3>;
  readonly diagnostics: Record<string, unknown>;

  constructor(init: {
    figureLabel: string;
    anchorName: string;
    effectorBone: string;
    chain: string[];
    targetPoint?: Vector3 | null;
    iterations?: number;
    converged?: boolean;
    initialError?: number | null;
    finalError?: number | null;
    appliedRotations?: Record<string, Rotation3>;
    diagnostics?: Record<string, unknown>;
  }) {
    this.figureLabel = init.figureLabel;
    this.anchorName = init.anchorName;
    this.effectorBone = init.effectorBone;
    this.chain = [...init.chain];
    this.targetPoint = init.targetPoint ?? null;
    this.iterations = init.iterations ?? 0;
    this.converged = init.converged ?? false;
    this.initialError = init.initialError ?? null;
    this.finalError = init.finalError ?? null;
    this.appliedRotations = init.appliedRotations ?? {};
    this.diagnostics = init.diagnostics ?? {};
  }

  toDict(): LimbAlignmentResultDict {
    return {
      figureLabel: this.figureLabel,
      anchorName: this.anchorName,
      effectorBone: this.effectorBone,
      chain: [...this.chain],
      targetPoint: this.targetPoint,
      iterations: this.iterations,
      converged: this.converged,
      initialError: this.initialError,
      finalError: this.finalError,
      appliedRotations: { ...this.appliedRotations },
      diagnostics: { ...this.diagnostics },
    };
  }
}

// ── PreparedInteractionResult ────────────────────────────────────────────────

/** The result of applying a prepared recipe as a live staging pass. `prepared` is typed loosely here (full type declared in Task 8) to avoid a forward reference. */
export class PreparedInteractionResult {
  readonly prepared: { toDict(): Record<string, unknown> };
  readonly posePatch: InteractionPosePatch;
  alignmentResults: LimbAlignmentResult[];

  constructor(init: { prepared: { toDict(): Record<string, unknown> }; posePatch: InteractionPosePatch; alignmentResults?: LimbAlignmentResult[] }) {
    this.prepared = init.prepared;
    this.posePatch = init.posePatch;
    this.alignmentResults = init.alignmentResults ?? [];
  }

  toDict() {
    return {
      prepared: this.prepared.toDict(),
      posePatch: this.posePatch.toDict(),
      alignmentResults: this.alignmentResults.map((r) => r.toDict()),
    };
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- test/unit/interactionPlan.test.ts`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Run the type checker**

Run: `npm run build`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add daz-ts/src/interactionPlan.ts daz-ts/test/unit/interactionPlan.test.ts
git commit -m "feat(daz-ts): add InteractionPosePatch, LimbAlignmentResult, PreparedInteractionResult"
```

---

## Task 8: `PreparedInteractionRecipe` (`buildPosePatch`/`apply`/`alignLimbTargets` stub) + `prepareInteractionRecipe`

**Files:**
- Modify: `daz-ts/src/interactionPlan.ts`
- Modify: `daz-ts/test/unit/interactionPlan.test.ts`

**Interfaces:**
- Consumes: everything from Tasks 4-7
- Produces: `PreparedInteractionRecipe`, `AlignLimbTargetsOptions`, `ApplyOptions`, `prepareInteractionRecipe(recipe, rigProfiles)`

This is the fiddliest piece: `buildPosePatch()` ports `PreparedInteractionRecipe.build_pose_patch` from `_interaction.py:929-1058` — it stages each figure's world position from `BalanceTarget` and resolved `HandTarget`/`FootTarget` constraints, averaging multiple contributions per figure and handling four same/cross-figure placement cases (see the spec's `interactionPlan.ts` section for the full case breakdown). Get the numeric test in Step 1 passing exactly — it pins the one case (`build_touch_recipe`-shaped, both figures unplaced) dazpy's own test suite uses as its canonical regression check.

- [ ] **Step 1: Write the failing test**

```ts
// append to daz-ts/test/unit/interactionPlan.test.ts
import { BalanceTarget, InteractionRecipe, PreparedInteractionRecipe, prepareInteractionRecipe } from "../../src/interactionPlan.js";

function touchRigProfiles() {
  const sourceProfile = new FigureRigProfile({
    figureLabel: "Genesis 9",
    family: "genesis_9",
    bones: [new BoneProfile({ name: "hip" }), new BoneProfile({ name: "r_hand", parentName: "hip", localPosition: [1, 2, 3] })],
  });
  const targetProfile = new FigureRigProfile({
    figureLabel: "Partner",
    family: "genesis_9",
    bones: [new BoneProfile({ name: "hip" }), new BoneProfile({ name: "l_shoulder", parentName: "hip", localPosition: [4, 5, 6] })],
  });
  return { "Genesis 9": sourceProfile, Partner: targetProfile };
}

describe("prepareInteractionRecipe", () => {
  it("compiles a recipe: validates, resolves targets, and records diagnostics", () => {
    const recipe = new InteractionRecipe({
      kind: "touch",
      actors: ["Genesis 9", "Partner"],
      constraints: [new HandTarget({ figureLabel: "Genesis 9", anchorName: "r_hand", targetFigure: "Partner", targetAnchor: "l_shoulder" })],
    });
    const prepared = prepareInteractionRecipe(recipe, touchRigProfiles());

    expect(prepared).toBeInstanceOf(PreparedInteractionRecipe);
    expect(prepared.isValid).toBe(true);
    expect(prepared.diagnostics.recipeKind).toBe("touch");
    expect(prepared.diagnostics.resolvedTargetCount).toBe(1);
    expect(prepared.resolvedTargets[0].boneName).toBe("r_hand");
    expect(prepared.resolvedTargets[0].targetBone).toBe("l_shoulder");
    expect(prepared.resolvedTargets[0].targetPoint).toEqual([4, 5, 6]);
  });

  it("accepts compact figure aliases in the rig-profile table", () => {
    const profile = new FigureRigProfile({
      figureLabel: "Genesis 9",
      family: "genesis_9",
      bones: [new BoneProfile({ name: "hip" }), new BoneProfile({ name: "r_hand", parentName: "hip" })],
    });
    const recipe = new InteractionRecipe({
      kind: "custom",
      actors: ["Genesis 9"],
      constraints: [new HandTarget({ figureLabel: "Genesis 9", anchorName: "r_hand", targetPoint: [1, 2, 3] })],
    });
    const prepared = prepareInteractionRecipe(recipe, { Genesis9: profile });
    expect(prepared.isValid).toBe(true);
    expect(prepared.rigProfiles.Genesis9.figureLabel).toBe("Genesis 9");
  });
});

describe("PreparedInteractionRecipe.apply", () => {
  it("moves both figures to the midpoint between the resolved anchor pair (contact-center staging)", async () => {
    const recipe = new InteractionRecipe({
      kind: "touch",
      actors: ["Genesis 9", "Partner"],
      constraints: [new HandTarget({ figureLabel: "Genesis 9", anchorName: "r_hand", targetFigure: "Partner", targetAnchor: "l_shoulder" })],
    });
    const prepared = prepareInteractionRecipe(recipe, touchRigProfiles());

    const calls: Array<{ label: string; position: [number, number, number] }> = [];
    const scene = {
      findSkeletonByLabel: async (label: string) => ({
        setPosition: async (x: number, y: number, z: number) => {
          calls.push({ label, position: [x, y, z] });
        },
      }),
    } as any;

    const result = await prepared.apply(scene);

    expect(calls).toEqual([
      { label: "Genesis 9", position: [1.5, 1.5, 1.5] },
      { label: "Partner", position: [-1.5, -1.5, -1.5] },
    ]);
    expect(result.posePatch.diagnostics.figureCount).toBe(2);
    expect(result.posePatch.diagnostics.unresolvedTargetCount).toBe(0);
    expect(result.alignmentResults).toEqual([]);
  });

  it("stages a BalanceTarget figure toward its support-point centroid", async () => {
    const profile = new FigureRigProfile({
      figureLabel: "Genesis 9",
      family: "genesis_9",
      bones: [new BoneProfile({ name: "hip", localPosition: [0, 0, 0] })],
    });
    const recipe = new InteractionRecipe({
      kind: "sit",
      actors: ["Genesis 9"],
      constraints: [new BalanceTarget({ figureLabel: "Genesis 9", pelvisBone: "hip", centerOfMassHint: [0, 1, 2] })],
    });
    const prepared = prepareInteractionRecipe(recipe, { "Genesis 9": profile });

    const calls: Array<[number, number, number]> = [];
    const scene = { findSkeletonByLabel: async () => ({ setPosition: async (x: number, y: number, z: number) => { calls.push([x, y, z]); } }) } as any;
    await prepared.apply(scene);

    expect(calls).toEqual([[0, 1, 2]]);
  });

  it("apply({alignLimbTargets: true}) returns no alignment results in 5A (interactionSolve.ts lands in 5B)", async () => {
    const recipe = new InteractionRecipe({
      kind: "touch",
      actors: ["Genesis 9", "Partner"],
      constraints: [new HandTarget({ figureLabel: "Genesis 9", anchorName: "r_hand", targetFigure: "Partner", targetAnchor: "l_shoulder" })],
    });
    const prepared = prepareInteractionRecipe(recipe, touchRigProfiles());
    const scene = { findSkeletonByLabel: async () => ({ setPosition: async () => {} }) } as any;

    const result = await prepared.apply(scene, { alignLimbTargets: true });

    expect(result.alignmentResults).toEqual([]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- test/unit/interactionPlan.test.ts`
Expected: FAIL — `PreparedInteractionRecipe`/`prepareInteractionRecipe` are not exported

- [ ] **Step 3: Write minimal implementation**

Append to `daz-ts/src/interactionPlan.ts`:

```ts
// ── PreparedInteractionRecipe ────────────────────────────────────────────────

export interface AlignLimbTargetsOptions {
  maxIterations?: number | null;
  stepDegrees?: number;
  damping?: number;
  tolerance?: number;
}

export interface ApplyOptions extends AlignLimbTargetsOptions {
  alignLimbTargets?: boolean;
}

/** A compiled recipe ready for a live DAZ session (or a future solver pass). */
export class PreparedInteractionRecipe {
  readonly recipe: InteractionRecipe;
  readonly plan: InteractionPlan;
  readonly resolvedTargets: ResolvedInteractionTarget[];
  readonly rigProfiles: Record<string, FigureRigProfile>;
  readonly validationIssues: ValidationIssue[];
  readonly diagnostics: Record<string, unknown>;

  constructor(init: {
    recipe: InteractionRecipe;
    plan: InteractionPlan;
    resolvedTargets?: ResolvedInteractionTarget[];
    rigProfiles?: Record<string, FigureRigProfile>;
    validationIssues?: ValidationIssue[];
    diagnostics?: Record<string, unknown>;
  }) {
    this.recipe = init.recipe;
    this.plan = init.plan;
    this.resolvedTargets = init.resolvedTargets ?? [];
    this.rigProfiles = init.rigProfiles ?? {};
    this.validationIssues = init.validationIssues ?? [];
    this.diagnostics = init.diagnostics ?? {};
  }

  get isValid(): boolean {
    return !this.validationIssues.some((issue) => issue.severity === "error");
  }

  toDict() {
    return {
      recipe: this.recipe.toDict(),
      plan: this.plan.toDict(),
      resolvedTargets: this.resolvedTargets.map((t) => t.toDict()),
      rigProfiles: Object.fromEntries(Object.entries(this.rigProfiles).map(([label, profile]) => [label, profile.toDict()])),
      validationIssues: this.validationIssues.map((issue) => issue.toDict()),
      diagnostics: { ...this.diagnostics },
    };
  }

  /**
   * Build a coarse live-placement patch from the prepared recipe.
   *
   * Intentionally conservative: only translates figures so their anchors
   * are staged near their requested targets. Does not solve bone rotations
   * (that's `alignLimbTargets`, Phase 5B).
   */
  buildPosePatch(): InteractionPosePatch {
    const figurePositions: Record<string, Vector3[]> = {};
    const unresolved: ResolvedInteractionTarget[] = [];

    const appendPosition = (label: string, point: Vector3): void => {
      (figurePositions[label] ??= []).push(point);
    };
    const firstLocalAnchorPosition = (profile: FigureRigProfile, anchorName: string): Vector3 | null => {
      const anchor = profile.anchor(anchorName);
      if (anchor === null) return null;
      return profile.bone(anchor.boneName).localPosition;
    };
    const currentFigurePosition = (label: string): Vector3 | null => averageVec3(figurePositions[label]);

    for (const constraint of this.plan.constraints) {
      if (!(constraint instanceof BalanceTarget)) continue;
      const profile = lookupRigProfile(this.rigProfiles, constraint.figureLabel);
      if (profile === null) continue;
      const pelvisAnchor = profile.anchor(constraint.pelvisBone);
      if (pelvisAnchor === null) {
        unresolved.push(new ResolvedInteractionTarget({ figureLabel: constraint.figureLabel, anchorName: constraint.pelvisBone, boneName: constraint.pelvisBone }));
        continue;
      }
      const pelvisBone = profile.bone(pelvisAnchor.boneName);
      let targetPoint = constraint.centerOfMassHint;
      if (targetPoint === null && constraint.supportPoints.length > 0) {
        targetPoint = averageVec3(constraint.supportPoints);
      }
      if (targetPoint === null || pelvisBone.localPosition === null) {
        unresolved.push(new ResolvedInteractionTarget({ figureLabel: constraint.figureLabel, anchorName: constraint.pelvisBone, boneName: pelvisAnchor.boneName, targetPoint }));
        continue;
      }
      appendPosition(constraint.figureLabel, subVec3(targetPoint, pelvisBone.localPosition));
    }

    for (const resolved of this.resolvedTargets) {
      const profile = lookupRigProfile(this.rigProfiles, resolved.figureLabel);
      if (profile === null) {
        unresolved.push(resolved);
        continue;
      }
      const sourceAnchor = profile.anchor(resolved.anchorName);
      if (sourceAnchor === null) {
        unresolved.push(resolved);
        continue;
      }
      const sourceBone = profile.bone(sourceAnchor.boneName);
      if (sourceBone.localPosition === null) {
        unresolved.push(resolved);
        continue;
      }
      const targetProfile = resolved.targetFigure ? lookupRigProfile(this.rigProfiles, resolved.targetFigure) : null;
      const targetLocal = targetProfile && resolved.targetAnchor ? firstLocalAnchorPosition(targetProfile, resolved.targetAnchor) : null;
      const sourceBase = currentFigurePosition(resolved.figureLabel);
      const targetBase = resolved.targetFigure ? currentFigurePosition(resolved.targetFigure) : null;

      if (targetProfile !== null && resolved.targetFigure !== null) {
        if (targetBase !== null && resolved.targetPoint !== null && sourceBase === null) {
          const worldTarget = addVec3(targetBase, resolved.targetPoint)!;
          appendPosition(resolved.figureLabel, subVec3(worldTarget, sourceBone.localPosition));
          continue;
        }
        if (targetLocal !== null) {
          if (sourceBase === null && targetBase === null) {
            const contactCenter = midpointVec3(sourceBone.localPosition, targetLocal);
            appendPosition(resolved.figureLabel, subVec3(contactCenter, sourceBone.localPosition));
            appendPosition(resolved.targetFigure, subVec3(contactCenter, targetLocal));
          } else if (sourceBase === null && targetBase !== null) {
            const targetWorld = addVec3(targetBase, targetLocal)!;
            appendPosition(resolved.figureLabel, subVec3(targetWorld, sourceBone.localPosition));
          } else if (sourceBase !== null && targetBase === null) {
            const sourceWorld = addVec3(sourceBase, sourceBone.localPosition);
            if (sourceWorld !== null) appendPosition(resolved.targetFigure, subVec3(sourceWorld, targetLocal));
          }
          continue;
        }
      }

      if (resolved.targetPoint === null) {
        unresolved.push(resolved);
        continue;
      }
      appendPosition(resolved.figureLabel, subVec3(resolved.targetPoint, sourceBone.localPosition));
    }

    const averagedPositions: Record<string, Vector3> = {};
    for (const [label, points] of Object.entries(figurePositions)) {
      averagedPositions[label] = averageVec3(points)!;
    }

    return new InteractionPosePatch({
      figurePositions: averagedPositions,
      unresolvedTargets: unresolved,
      diagnostics: { figureCount: Object.keys(averagedPositions).length, unresolvedTargetCount: unresolved.length },
    });
  }

  async apply(scene: RigSceneSource, opts: ApplyOptions = {}): Promise<PreparedInteractionResult> {
    const patch = this.buildPosePatch();
    await patch.apply(scene);
    const result = new PreparedInteractionResult({ prepared: this, posePatch: patch });
    if (opts.alignLimbTargets) {
      result.alignmentResults = await this.alignLimbTargets(scene, opts);
    }
    return result;
  }

  /**
   * Apply live limb alignment for resolved hand/foot targets.
   *
   * Real IK solving lands in `interactionSolve.ts` (Phase 5B,
   * `daz-script-server-sf7y.2`) -- until then this returns no results
   * regardless of how many hand/foot targets were resolved.
   */
  async alignLimbTargets(_scene: RigSceneSource, _opts: AlignLimbTargetsOptions = {}): Promise<LimbAlignmentResult[]> {
    return [];
  }
}

export function prepareInteractionRecipe(recipe: InteractionRecipe, rigProfiles: Record<string, FigureRigProfile>): PreparedInteractionRecipe {
  const plan = recipe.toPlan();
  const validationIssues = plan.validate(rigProfiles);
  const resolvedTargets = plan.resolveTargets(rigProfiles);
  return new PreparedInteractionRecipe({
    recipe,
    plan,
    resolvedTargets,
    rigProfiles: { ...rigProfiles },
    validationIssues,
    diagnostics: {
      recipeKind: recipe.kind,
      actorCount: recipe.actors.length,
      constraintCount: recipe.constraints.length,
      resolvedTargetCount: resolvedTargets.length,
    },
  });
}
```

Also update `PreparedInteractionResult`'s constructor parameter type (Task 7) from the loose `{ toDict(): Record<string, unknown> }` shape to `PreparedInteractionRecipe` now that it exists — change:

```ts
readonly prepared: { toDict(): Record<string, unknown> };
```

to:

```ts
readonly prepared: PreparedInteractionRecipe;
```

in both the field declaration and the constructor parameter, in both `PreparedInteractionResult` (Task 7) and any place it's referenced. Re-run Task 7's tests after this change (the `fakePrepared` object with just `toDict()` will now fail type-checking under `npm run build` — update that test to construct a real, minimal `PreparedInteractionRecipe` instead: `prepareInteractionRecipe(new InteractionRecipe({ kind: "custom", actors: [] }), {})`).

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- test/unit/interactionPlan.test.ts`
Expected: PASS (all tests in the file, including the updated Task 7 `PreparedInteractionResult` test)

- [ ] **Step 5: Run the type checker**

Run: `npm run build`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add daz-ts/src/interactionPlan.ts daz-ts/test/unit/interactionPlan.test.ts
git commit -m "feat(daz-ts): add PreparedInteractionRecipe.buildPosePatch/apply, prepareInteractionRecipe"
```

---

## Task 9: `index.ts` exports + full-suite verification

**Files:**
- Modify: `daz-ts/src/index.ts`

**Interfaces:**
- Consumes: every public symbol from Tasks 1-8

- [ ] **Step 1: Add the Phase 5A export block**

Append to the end of `daz-ts/src/index.ts`:

```ts
// ── Phase 5A: interaction rig profiles + plan data model ───────────────────

export {
  AxisLimit,
  BoneChain,
  BoneProfile,
  FigureRigProfile,
  InteractionAnchor,
  ResolvedInteractionTarget,
  addVec3,
  averageVec3,
  buildRigProfile,
  buildRigProfilesFromSnapshot,
  clamp,
  defaultAxisLimitsForBone,
  detectFigureFamily,
  dotVec3,
  lengthVec3,
  lookupRigProfile,
  looksLikeHelper,
  looksLikeTwist,
  midpointVec3,
  scaleVec3,
  sideFromName,
  subVec3,
} from "./rigProfile.js";
export type {
  AnchorRole,
  AnchorTargetLike,
  AxisLimitDict,
  AxisName,
  BoneChainDict,
  BoneProfileDict,
  ChainRole,
  ChainSide,
  FigureRigProfileDict,
  InteractionAnchorDict,
  ResolvedInteractionTargetDict,
  RigMetadataSource,
  RigSceneSource,
  RigSkeletonSource,
  Rotation3,
  Vector3,
} from "./rigProfile.js";

export {
  BalanceTarget,
  ContactTarget,
  FootTarget,
  HandTarget,
  InteractionPlan,
  InteractionPosePatch,
  InteractionRecipe,
  LimbAlignmentResult,
  LookAtTarget,
  PoseTarget,
  PreparedInteractionRecipe,
  PreparedInteractionResult,
  SolveOptions,
  ValidationIssue,
  prepareInteractionRecipe,
  resolveInteractionTarget,
} from "./interactionPlan.js";
export type {
  AlignLimbTargetsOptions,
  AnchorTargetDict,
  ApplyOptions,
  BalanceTargetDict,
  ContactTargetDict,
  InteractionConstraint,
  InteractionPlanDict,
  InteractionPosePatchDict,
  InteractionRecipeDict,
  LimbAlignmentResultDict,
  LookAtTargetDict,
  PoseTargetDict,
  RecipeKind,
  SolveBackend,
  SolveOptionsDict,
  ValidationIssueDict,
} from "./interactionPlan.js";
```

- [ ] **Step 2: Run the type checker**

Run: `npm run build`
Expected: no errors — this also catches any export name that doesn't match what Tasks 1-8 actually defined.

- [ ] **Step 3: Run the full unit test suite**

Run: `npm test`
Expected: PASS — every test file in `test/unit`, old and new, green.

- [ ] **Step 4: Commit**

```bash
git add daz-ts/src/index.ts
git commit -m "feat(daz-ts): export Phase 5A public API from index.ts"
```

- [ ] **Step 5: Update beads**

```bash
bd close daz-script-server-sf7y.1 --reason="rig profiles + interaction plan data model ported and tested"
bd update daz-script-server-sf7y.2 --claim
```

---

## Self-review notes (already applied above)

- **Spec coverage:** every `rigProfile.ts`/`interactionPlan.ts` item listed in the spec's Architecture section has a task (Tasks 1-3 = `rigProfile.ts`; Tasks 4-8 = `interactionPlan.ts`). The spec's explicit note that `PreparedInteractionRecipe.apply`/`alignLimbTargets` ship as pose-patch-only stubs in 5A is implemented in Task 8 exactly as described, with a comment pointing at Phase 5B.
- **Module boundary:** confirmed no task imports `skeleton.ts` or `scene.ts` — `RigSkeletonSource`/`RigSceneSource` (Task 1) are the only contact points, and `DazSkeleton`/`DazScene` will satisfy them structurally once `scene.ts` is wired up in Phase 5C.
- **Type consistency:** `PreparedInteractionResult.prepared`'s type is tightened from a loose structural shape (Task 7, before `PreparedInteractionRecipe` exists) to the real class (Task 8) — call this out explicitly during execution since it also requires touching Task 7's own test.
- **No placeholders:** `alignLimbTargets`'s `return []` body is a real, working, tested implementation (Task 8's test asserts the empty-array behavior explicitly) documented as an interim scope boundary, not a TODO.
