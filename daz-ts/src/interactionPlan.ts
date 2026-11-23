// daz-ts/src/interactionPlan.ts

/**
 * Interaction-plan data model: constraints (pose/anchor/contact/look-at/
 * balance targets), `InteractionPlan`/`InteractionRecipe`, validation,
 * target resolution, and coarse pose-patch staging. Ports the non-solver
 * half of dazpy's `_interaction.py`. Live IK alignment
 * (`PreparedInteractionRecipe.alignLimbTargets`) delegates to the solver in
 * `interactionSolve.ts`.
 */

import type { AnchorTargetLike, RigSceneSource, Vector3, Rotation3 } from "./rigProfile.js";
import {
  addVec3,
  ANCHOR_SURFACE_RADIUS,
  asVector3,
  averageVec3,
  BoneProfile,
  buildRigProfilesFromSnapshot,
  FigureRigProfile,
  lengthVec3,
  lookupRigProfile,
  midpointVec3,
  normalizeName,
  scaleVec3,
  sideFromName,
  subVec3,
  ResolvedInteractionTarget,
} from "./rigProfile.js";
import { alignmentChainNames, alignSingleLimbTarget, LimbAlignmentResult, type AlignOptions } from "./interactionSolve.js";

// `LimbAlignmentResult` lives in interactionSolve.ts (which must not import
// this file); re-exported here so Phase 5A import paths keep working.
export { LimbAlignmentResult } from "./interactionSolve.js";
export type { LimbAlignmentResultDict } from "./interactionSolve.js";

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
  /**
   * How far the effector joint stops short of the target (cm). Null/omitted
   * picks one for anchor-to-anchor targets: the target anchor's body radius
   * plus the effector's hand/foot length, so the hand lands on the skin
   * instead of inside the partner. 0 aims at the joint centre. Explicit
   * `targetPoint` targets default to 0.
   */
  surfaceStandoff?: number | null;
  /**
   * Reach around the target anchor's side (a shoulder) to the partner's
   * upper back: the effector passes waypoints beside the partner's ribs,
   * under its arm, then stops on its back, and the hand turns to lie across
   * it. (The solver has no collision, so a direct reach would pass through
   * the body.) `surfaceStandoff` and `offset` do not apply.
   */
  wrap?: boolean;
}

export interface AnchorTargetDict {
  kind: "HandTarget" | "FootTarget";
  figureLabel: string;
  anchorName: string;
  targetFigure: string | null;
  targetAnchor: string | null;
  targetPoint: Vector3 | null;
  offset: Vector3;
  surfaceStandoff: number | null;
  wrap: boolean;
}

abstract class AnchorTargetBase implements AnchorTargetLike {
  abstract readonly kind: "HandTarget" | "FootTarget";
  readonly figureLabel: string;
  readonly anchorName: string;
  readonly targetFigure: string | null;
  readonly targetAnchor: string | null;
  readonly targetPoint: Vector3 | null;
  readonly offset: Vector3;
  readonly surfaceStandoff: number | null;
  readonly wrap: boolean;

  constructor(init: AnchorTargetInit) {
    this.figureLabel = init.figureLabel;
    this.anchorName = init.anchorName;
    this.targetFigure = init.targetFigure ?? null;
    this.targetAnchor = init.targetAnchor ?? null;
    this.targetPoint = init.targetPoint ?? null;
    this.offset = init.offset ?? [0, 0, 0];
    this.surfaceStandoff = init.surfaceStandoff ?? null;
    this.wrap = init.wrap ?? false;
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
      surfaceStandoff: this.surfaceStandoff,
      wrap: this.wrap,
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

/** Tunable solver options. `alignLimbTargets` reads `maxIterations`; the other fields are carried for parity with dazpy. */
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
      constraints: this.constraints.map((c) => ({ ...c.toDict() })),
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
          surfaceStandoff: typeof item.surfaceStandoff === "number" ? item.surfaceStandoff : null,
          wrap: item.wrap === true,
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
        if (profile.anchorOrBone(constraint.pelvisBone) === null) {
          issues.push(new ValidationIssue("error", constraint.figureLabel, index, `Unknown pelvis anchor or bone ${constraint.pelvisBone} on figure ${constraint.figureLabel}`));
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

  /**
   * Resolve every `HandTarget`/`FootTarget` constraint into concrete anchors and points.
   * Targets whose figure, anchor or target anchor does not exist are skipped
   * (`validate()` reports them as issues) rather than thrown, unlike dazpy.
   */
  resolveTargets(rigProfiles: Record<string, FigureRigProfile>): ResolvedInteractionTarget[] {
    const resolved: ResolvedInteractionTarget[] = [];
    for (const constraint of this.constraints) {
      if (constraint instanceof HandTarget || constraint instanceof FootTarget) {
        const profile = lookupRigProfile(rigProfiles, constraint.figureLabel);
        if (profile === null || profile.anchor(constraint.anchorName) === null) continue;
        if (constraint.targetFigure && constraint.targetAnchor) {
          const targetProfile = lookupRigProfile(rigProfiles, constraint.targetFigure);
          if (targetProfile !== null && targetProfile.anchor(constraint.targetAnchor) === null) continue;
        }
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

/** A higher-level interaction preset that expands into an interaction plan. Build one directly or with a canned builder (`buildSitRecipe`, `buildHugRecipe`, ...). */
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

// ── InteractionPosePatch ─────────────────────────────────────────────────────

export interface InteractionPosePatchDict {
  figurePositions: Record<string, Vector3>;
  figureYawDegrees: Record<string, number>;
  unresolvedTargets: ReturnType<ResolvedInteractionTarget["toDict"]>[];
  diagnostics: Record<string, unknown>;
}

/**
 * A coarse figure-placement patch built from a prepared interaction: figure
 * translations, plus yaw turns for figures staged to face a partner. Does not
 * solve bone rotations.
 */
export class InteractionPosePatch {
  readonly figurePositions: Record<string, Vector3>;
  /** Figure label -> degrees to add to the figure's Y rotation (turning it to face its partner). */
  readonly figureYawDegrees: Record<string, number>;
  readonly unresolvedTargets: ResolvedInteractionTarget[];
  readonly diagnostics: Record<string, unknown>;

  constructor(
    init: {
      figurePositions?: Record<string, Vector3>;
      figureYawDegrees?: Record<string, number>;
      unresolvedTargets?: ResolvedInteractionTarget[];
      diagnostics?: Record<string, unknown>;
    } = {},
  ) {
    this.figurePositions = init.figurePositions ?? {};
    this.figureYawDegrees = init.figureYawDegrees ?? {};
    this.unresolvedTargets = init.unresolvedTargets ?? [];
    this.diagnostics = init.diagnostics ?? {};
  }

  async apply(scene: Pick<RigSceneSource, "findSkeletonByLabel">): Promise<void> {
    for (const [figureLabel, yaw] of Object.entries(this.figureYawDegrees)) {
      if (Math.abs(yaw) < 1e-6) continue;
      const skeleton = await scene.findSkeletonByLabel(figureLabel);
      if (!skeleton.localEuler || !skeleton.setRotation) throw new Error(`Cannot turn ${figureLabel} to face its partner: skeleton has no localEuler/setRotation`);
      const [x, y, z] = (await skeleton.localEuler()) ?? [0, 0, 0];
      await skeleton.setRotation(x, y + yaw, z);
    }
    for (const [figureLabel, position] of Object.entries(this.figurePositions)) {
      const skeleton = await scene.findSkeletonByLabel(figureLabel);
      await skeleton.setPosition(position[0], position[1], position[2]);
    }
  }

  toDict(): InteractionPosePatchDict {
    return {
      figurePositions: { ...this.figurePositions },
      figureYawDegrees: { ...this.figureYawDegrees },
      unresolvedTargets: this.unresolvedTargets.map((t) => t.toDict()),
      diagnostics: { ...this.diagnostics },
    };
  }
}

// ── PreparedInteractionResult ────────────────────────────────────────────────

/** The result of applying a prepared recipe as a live staging pass. */
export class PreparedInteractionResult {
  readonly prepared: PreparedInteractionRecipe;
  readonly posePatch: InteractionPosePatch;
  alignmentResults: LimbAlignmentResult[];

  constructor(init: { prepared: PreparedInteractionRecipe; posePatch: InteractionPosePatch; alignmentResults?: LimbAlignmentResult[] }) {
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

// ── PreparedInteractionRecipe ────────────────────────────────────────────────

export interface AlignLimbTargetsOptions {
  maxIterations?: number | null;
  stepDegrees?: number;
  damping?: number;
  tolerance?: number;
  /**
   * Figure label -> how far staging moved that figure. Shifts targets that
   * point at another figure's anchor, whose point was resolved before
   * staging. `apply()` passes this.
   */
  figureDisplacements?: Record<string, Vector3>;
}

export interface InteractionApplyOptions extends AlignLimbTargetsOptions {
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
  /**
   * Partner figure label -> the figure it is turned to face, and by how
   * much. `rigProfiles` (and so `resolvedTargets`) already have these turns
   * applied; `buildPosePatch` stages each partner a limb target links in
   * front of its anchor (a look-only partner is only turned).
   */
  readonly facing: Record<string, FacingAssignment>;

  constructor(init: {
    recipe: InteractionRecipe;
    plan: InteractionPlan;
    resolvedTargets?: ResolvedInteractionTarget[];
    rigProfiles?: Record<string, FigureRigProfile>;
    validationIssues?: ValidationIssue[];
    diagnostics?: Record<string, unknown>;
    facing?: Record<string, FacingAssignment>;
  }) {
    this.recipe = init.recipe;
    this.plan = init.plan;
    this.resolvedTargets = init.resolvedTargets ?? [];
    this.rigProfiles = init.rigProfiles ?? {};
    this.validationIssues = init.validationIssues ?? [];
    this.diagnostics = init.diagnostics ?? {};
    this.facing = init.facing ?? {};
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
      facing: Object.fromEntries(Object.entries(this.facing).map(([label, f]) => [label, { ...f }])),
    };
  }

  /**
   * Build a coarse live-placement patch from the prepared recipe.
   *
   * Intentionally conservative: translates figures so their anchors are
   * staged near their requested targets. Hand/foot targets move figures in
   * X/Z only and keep their height (IK handles reach); a `BalanceTarget` also
   * sets height. A faced partner (see `facing`) is turned and placed straight
   * in front of its anchor figure, as far as the shortest limb between them
   * comfortably reaches. Does not solve bone rotations (that's
   * `alignLimbTargets`).
   */
  buildPosePatch(): InteractionPosePatch {
    // Each staged position records whether it sets the figure's height.
    // Hand/foot targets are floor-locked (X/Z only; IK handles reach), a
    // BalanceTarget (sit) sets full 3D.
    const figurePositions: Record<string, Array<{ point: Vector3; setsHeight: boolean }>> = {};
    const unresolved: ResolvedInteractionTarget[] = [];

    const floorHeight = (label: string): number => lookupRigProfile(this.rigProfiles, label)?.figurePosition?.[1] ?? 0;
    const appendPosition = (label: string, point: Vector3, setsHeight = false): void => {
      (figurePositions[label] ??= []).push({ point, setsHeight });
    };
    const stagedPosition = (label: string | null): Vector3 | null => {
      const entries = label ? figurePositions[label] : undefined;
      if (!label || !entries || entries.length === 0) return null;
      const xz = averageVec3(entries.map((e) => e.point))!;
      const heights = entries.filter((e) => e.setsHeight).map((e) => e.point[1]);
      const y = heights.length > 0 ? heights.reduce((a, b) => a + b, 0) / heights.length : floorHeight(label);
      return [xz[0], y, xz[2]];
    };

    for (const constraint of this.plan.constraints) {
      if (!(constraint instanceof BalanceTarget)) continue;
      const profile = lookupRigProfile(this.rigProfiles, constraint.figureLabel);
      if (profile === null) continue;
      const pelvisBone = profile.anchorOrBone(constraint.pelvisBone);
      if (pelvisBone === null) {
        unresolved.push(new ResolvedInteractionTarget({ figureLabel: constraint.figureLabel, anchorName: constraint.pelvisBone, boneName: constraint.pelvisBone }));
        continue;
      }
      const pelvisOffset = profile.boneOffset(pelvisBone);
      let targetPoint = constraint.centerOfMassHint;
      if (targetPoint === null && constraint.supportPoints.length > 0) {
        targetPoint = averageVec3(constraint.supportPoints);
      }
      if (targetPoint === null || pelvisOffset === null) {
        unresolved.push(new ResolvedInteractionTarget({ figureLabel: constraint.figureLabel, anchorName: constraint.pelvisBone, boneName: pelvisBone, targetPoint }));
        continue;
      }
      appendPosition(constraint.figureLabel, subVec3(targetPoint, pelvisOffset), true);
    }

    // Faced pairs: the partner goes straight in front of its anchor figure.
    const facedTargets = new Set<ResolvedInteractionTarget>();
    const figureYawDegrees: Record<string, number> = {};
    for (const [partnerLabel, assignment] of Object.entries(this.facing)) {
      figureYawDegrees[partnerLabel] = assignment.yawDegrees;
      const anchorProfile = lookupRigProfile(this.rigProfiles, assignment.anchor);
      const partnerProfile = lookupRigProfile(this.rigProfiles, partnerLabel);
      if (anchorProfile === null || partnerProfile === null || partnerProfile.figurePosition === null) continue;
      const forward = figureForward(anchorProfile);
      const anchorBase = stagedPosition(assignment.anchor) ?? anchorProfile.figurePosition;
      if (forward === null || anchorBase === null) continue;
      const partnerY = partnerProfile.figurePosition[1];
      const partnerBase = (d: number): Vector3 => [anchorBase[0] + forward[0] * d, partnerY, anchorBase[2] + forward[2] * d];
      const between = this.resolvedTargets.filter((t) => {
        const source = lookupRigProfile(this.rigProfiles, t.figureLabel);
        const target = lookupRigProfile(this.rigProfiles, t.targetFigure);
        return t.targetAnchor !== null && ((source === anchorProfile && target === partnerProfile) || (source === partnerProfile && target === anchorProfile));
      });
      const separations: number[] = [];
      for (const target of between) {
        const separation = this.facedSeparation(target, (d) => new Map([[anchorProfile, anchorBase], [partnerProfile, partnerBase(d)]]));
        // A wrap sets its own (embrace) distance; reaches keep two torsos apart.
        if (separation !== null) separations.push(target.wrap ? separation : Math.max(FACING_MIN_SEPARATION, separation));
      }
      if (separations.length === 0) continue;
      const separation = Math.min(...separations);
      appendPosition(partnerLabel, partnerBase(separation));
      between.forEach((t) => facedTargets.add(t));
    }

    for (const resolved of this.resolvedTargets) {
      if (facedTargets.has(resolved)) continue;
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
      const sourceOffset = profile.boneOffset(sourceAnchor.boneName);
      if (sourceOffset === null) {
        unresolved.push(resolved);
        continue;
      }
      const targetProfile = resolved.targetFigure ? lookupRigProfile(this.rigProfiles, resolved.targetFigure) : null;
      const targetOffset = targetProfile && resolved.targetAnchor ? anchorBoneOffset(targetProfile, resolved.targetAnchor) : null;
      const sourceBase = stagedPosition(resolved.figureLabel);
      const targetBase = stagedPosition(resolved.targetFigure);

      if (targetProfile !== null && resolved.targetFigure !== null) {
        if (targetBase !== null && resolved.targetPoint !== null && sourceBase === null) {
          const worldTarget = addVec3(targetBase, resolved.targetPoint)!;
          appendPosition(resolved.figureLabel, subVec3(worldTarget, sourceOffset));
          continue;
        }
        if (targetOffset !== null) {
          // Stage the effector a surface standoff short of the target joint,
          // on the source limb's side, so IK starts at the contact point
          // instead of folding the arm back to it.
          const rootOffset = limbRootOffset(profile, sourceAnchor.boneName);
          const standoff = resolved.surfaceStandoff;
          if (sourceBase === null && targetBase === null) {
            const contactCenter = midpointVec3(sourceOffset, targetOffset);
            const sourcePosition = subVec3(contactCenter, sourceOffset);
            const targetPosition = subVec3(contactCenter, targetOffset);
            const gap = standoffShift(contactCenter, sourcePosition, rootOffset, standoff);
            appendPosition(resolved.figureLabel, addVec3(sourcePosition, scaleVec3(gap, 0.5))!);
            appendPosition(resolved.targetFigure, subVec3(targetPosition, scaleVec3(gap, 0.5)));
          } else if (sourceBase === null && targetBase !== null) {
            const targetWorld = addVec3(targetBase, targetOffset)!;
            const sourcePosition = subVec3(targetWorld, sourceOffset);
            appendPosition(resolved.figureLabel, addVec3(sourcePosition, standoffShift(targetWorld, sourcePosition, rootOffset, standoff))!);
          } else if (sourceBase !== null && targetBase === null) {
            const sourceWorld = addVec3(sourceBase, sourceOffset)!;
            const gap = standoffShift(sourceWorld, sourceBase, rootOffset, standoff);
            appendPosition(resolved.targetFigure, subVec3(subVec3(sourceWorld, targetOffset), gap));
          }
          continue;
        }
      }

      if (resolved.targetPoint === null) {
        unresolved.push(resolved);
        continue;
      }
      appendPosition(resolved.figureLabel, subVec3(resolved.targetPoint, sourceOffset));
    }

    const averagedPositions: Record<string, Vector3> = {};
    for (const label of Object.keys(figurePositions)) {
      averagedPositions[label] = stagedPosition(label)!;
    }

    return new InteractionPosePatch({
      figurePositions: averagedPositions,
      figureYawDegrees,
      unresolvedTargets: unresolved,
      diagnostics: { figureCount: Object.keys(averagedPositions).length, unresolvedTargetCount: unresolved.length },
    });
  }

  async apply(scene: Pick<RigSceneSource, "findSkeletonByLabel">, opts: InteractionApplyOptions = {}): Promise<PreparedInteractionResult> {
    const patch = this.buildPosePatch();
    await patch.apply(scene);
    const result = new PreparedInteractionResult({ prepared: this, posePatch: patch });
    if (opts.alignLimbTargets) {
      result.alignmentResults = await this.alignLimbTargets(scene, { ...opts, figureDisplacements: this.stagingDisplacements(patch) });
    }
    return result;
  }

  /** How far `patch` moves each figure whose original position is known. */
  private stagingDisplacements(patch: InteractionPosePatch): Record<string, Vector3> {
    const displacements: Record<string, Vector3> = {};
    for (const [label, position] of Object.entries(patch.figurePositions)) {
      const figurePosition = lookupRigProfile(this.rigProfiles, label)?.figurePosition ?? null;
      if (figurePosition !== null) displacements[label] = subVec3(position, figurePosition);
    }
    return displacements;
  }

  /**
   * Apply live limb alignment for resolved hand/foot targets: one
   * `alignSingleLimbTarget` IK pass per target that has a target point and a
   * known rig profile, in resolution order.
   */
  async alignLimbTargets(scene: Pick<RigSceneSource, "findSkeletonByLabel">, opts: AlignLimbTargetsOptions = {}): Promise<LimbAlignmentResult[]> {
    const results: LimbAlignmentResult[] = [];
    for (let resolved of this.resolvedTargets) {
      if (resolved.targetPoint === null) continue;
      const shift = this.displacementFor(resolved, opts.figureDisplacements);
      if (shift !== null) resolved = new ResolvedInteractionTarget({ ...resolved, targetPoint: addVec3(resolved.targetPoint, shift) });
      const skeleton = await scene.findSkeletonByLabel(resolved.figureLabel);
      const profile = lookupRigProfile(this.rigProfiles, resolved.figureLabel);
      if (profile === null) continue;
      const jointPoint = resolved.targetPoint!;
      const solve = {
        maxIterations: opts.maxIterations || this.plan.options.maxIterations,
        stepDegrees: opts.stepDegrees,
        damping: opts.damping,
        tolerance: opts.tolerance,
      };
      if (resolved.wrap) {
        const wrapped = await this.alignWrap(skeleton, profile, resolved, this.stagedBases(opts.figureDisplacements), solve);
        if (wrapped !== null) {
          results.push(wrapped);
          continue;
        }
      }
      // Hand-to-hand both ways (handshake): both hands meet halfway instead
      // of chasing each other's rest positions.
      const meeting = this.mutualTarget(resolved) !== null ? this.contactGeometry(resolved, this.stagedBases(opts.figureDisplacements)) : null;
      if (meeting !== null) {
        resolved = new ResolvedInteractionTarget({ ...resolved, targetPoint: meeting.stop });
      } else if (resolved.surfaceStandoff > 0) {
        const sourceShift = this.profileDisplacement(profile, opts.figureDisplacements);
        resolved = new ResolvedInteractionTarget({ ...resolved, targetPoint: surfaceContactPoint(profile, resolved, sourceShift) });
      }
      const result = await alignSingleLimbTarget(skeleton, profile, resolved, solve);
      if (meeting !== null) result.diagnostics.meetingPoint = meeting.joint;
      if (resolved.surfaceStandoff > 0) {
        result.diagnostics.surfaceStandoff = resolved.surfaceStandoff;
        result.diagnostics.targetJointPoint = jointPoint;
      }
      results.push(result);
    }
    return results;
  }

  /**
   * IK passes for a wrap target: through each waypoint around the partner,
   * then to the stop on its back; then the hand turns to lie across the back.
   * Returns the last arm pass, with iterations and initial error covering
   * all of them. Null when the wrap geometry is unknown (the caller falls
   * back to a direct reach).
   */
  private async alignWrap(
    skeleton: Awaited<ReturnType<RigSceneSource["findSkeletonByLabel"]>>,
    profile: FigureRigProfile,
    resolved: ResolvedInteractionTarget,
    bases: Map<FigureRigProfile, Vector3>,
    solve: AlignOptions,
  ): Promise<LimbAlignmentResult | null> {
    const geometry = this.contactGeometry(resolved, bases);
    if (geometry === null || geometry.waypoints.length === 0) return null;
    const passes: LimbAlignmentResult[] = [];
    for (const point of [...geometry.waypoints, geometry.stop]) {
      passes.push(await alignSingleLimbTarget(skeleton, profile, new ResolvedInteractionTarget({ ...resolved, targetPoint: point }), solve));
    }
    const final = passes[passes.length - 1];
    const diagnostics: Record<string, unknown> = {
      ...final.diagnostics,
      wrapWaypoints: geometry.waypoints,
      waypointErrors: passes.slice(0, -1).map((p) => p.finalError),
    };
    if (geometry.fingerPoint !== null) Object.assign(diagnostics, await aimWrapHand(skeleton, profile, resolved.boneName, geometry.fingerPoint, solve));
    return new LimbAlignmentResult({
      figureLabel: final.figureLabel,
      anchorName: final.anchorName,
      effectorBone: final.effectorBone,
      chain: final.chain,
      targetPoint: final.targetPoint,
      iterations: passes.reduce((total, p) => total + p.iterations, 0),
      converged: final.converged,
      initialError: passes[0].initialError,
      finalError: final.finalError,
      appliedRotations: final.appliedRotations,
      diagnostics,
    });
  }

  /** The reverse target of a hand/foot-to-hand/foot target (B's hand -> A's hand for A's hand -> B's hand), if the plan has one. */
  private mutualTarget(target: ResolvedInteractionTarget): ResolvedInteractionTarget | null {
    if (target.targetFigure === null || target.targetAnchor === null) return null;
    const source = lookupRigProfile(this.rigProfiles, target.figureLabel);
    const partner = lookupRigProfile(this.rigProfiles, target.targetFigure);
    if (source === null || partner === null || source === partner) return null;
    return (
      this.resolvedTargets.find(
        (other) =>
          other !== target &&
          other.anchorName === target.targetAnchor &&
          other.targetAnchor === target.anchorName &&
          lookupRigProfile(this.rigProfiles, other.figureLabel) === partner &&
          lookupRigProfile(this.rigProfiles, other.targetFigure) === source,
      ) ?? null
    );
  }

  /** Figure origins after staging: each profile's position plus its displacement. */
  private stagedBases(displacements: Record<string, Vector3> | undefined): Map<FigureRigProfile, Vector3> {
    const bases = new Map<FigureRigProfile, Vector3>();
    for (const profile of new Set(Object.values(this.rigProfiles))) {
      if (profile.figurePosition === null) continue;
      bases.set(profile, addVec3(profile.figurePosition, this.profileDisplacement(profile, displacements))!);
    }
    return bases;
  }

  /**
   * Where `target`'s effector should stop with the figures' origins at
   * `bases` (unlisted figures stay put): the target joint pulled back toward
   * the source limb root by the surface standoff. For a mutual hand-to-hand
   * pair the joint is the meeting point between both shoulders. Also returns
   * the reach root (shoulder/hip joint) and the limb's reach. Null when the
   * geometry is unknown.
   */
  private contactGeometry(target: ResolvedInteractionTarget, bases: Map<FigureRigProfile, Vector3>): ContactGeometry | null {
    const source = lookupRigProfile(this.rigProfiles, target.figureLabel);
    const partner = lookupRigProfile(this.rigProfiles, target.targetFigure);
    if (source === null || partner === null || target.targetAnchor === null) return null;
    const limb = limbGeometry(source, target.boneName, bases.get(source) ?? source.figurePosition);
    if (limb === null) return null;
    const partnerBase = bases.get(partner) ?? partner.figurePosition;
    if (target.wrap) {
      const path = wrapPath(partner, partnerBase, target.targetAnchor);
      if (path === null) return null;
      return { root: limb.reachRoot, joint: path.back, stop: path.back, limbLength: limb.reach, waypoints: path.waypoints, fingerPoint: path.fingers };
    }
    let joint: Vector3 | null = null;
    const mutual = this.mutualTarget(target);
    if (mutual !== null) {
      const other = limbGeometry(partner, mutual.boneName, partnerBase);
      if (other !== null) joint = meetingPoint(limb.reachRoot, limb.reach, other.reachRoot, other.reach);
    } else {
      const offset = anchorBoneOffset(partner, target.targetAnchor);
      if (offset !== null && partnerBase !== null) joint = addVec3(addVec3(partnerBase, offset), target.offset);
    }
    if (joint === null) return null;
    return { root: limb.reachRoot, joint, stop: pullTowardRoot(joint, limb.chainRoot, target.surfaceStandoff), limbLength: limb.reach, waypoints: [], fingerPoint: null };
  }

  /**
   * How far in front of its anchor a faced partner can stand (origin to
   * origin, cm) for `target`'s limb to reach its stop point at
   * `FACING_REACH_FRACTION` (`FACING_FOOT_REACH_FRACTION` for a leg) of its
   * reach. `basesAt(d)` places the figures
   * for separation `d`. Never closer than `FACING_MIN_SEPARATION`.
   */
  private facedSeparation(target: ResolvedInteractionTarget, basesAt: (d: number) => Map<FigureRigProfile, Vector3>): number | null {
    // Reach doesn't bound a wrap: its arm must get its elbow beside the
    // partner's ribs, which only an embrace distance allows.
    if (target.wrap) return WRAP_SEPARATION;
    const role = lookupRigProfile(this.rigProfiles, target.figureLabel)?.suggestPrimaryChain(target.boneName)?.role;
    const fraction = role === "foot" || role === "leg" ? FACING_FOOT_REACH_FRACTION : FACING_REACH_FRACTION;
    const gapAt = (d: number): { gap: number; reach: number } | null => {
      const geometry = this.contactGeometry(target, basesAt(d));
      return geometry === null ? null : { gap: lengthVec3(subVec3(geometry.stop, geometry.root)), reach: geometry.limbLength * fraction };
    };
    let low = FACING_MIN_SEPARATION;
    let high = FACING_MAX_SEPARATION;
    const atLow = gapAt(low);
    if (atLow === null) return null;
    if (atLow.gap >= atLow.reach) return low;
    const atHigh = gapAt(high)!;
    if (atHigh.gap <= atHigh.reach) return high;
    for (let i = 0; i < 40; i++) {
      const mid = (low + high) / 2;
      const atMid = gapAt(mid)!;
      if (atMid.gap <= atMid.reach) low = mid;
      else high = mid;
    }
    return low;
  }

  /** Staging displacement of `profile`'s figure (matched by profile, so aliases work). */
  private profileDisplacement(profile: FigureRigProfile, displacements: Record<string, Vector3> | undefined): Vector3 | null {
    for (const [label, displacement] of Object.entries(displacements ?? {})) {
      if (lookupRigProfile(this.rigProfiles, label) === profile) return displacement;
    }
    return null;
  }

  /** Staging displacement of the figure a cross-figure anchor target points at (matched by resolved profile, so aliases work). */
  private displacementFor(resolved: ResolvedInteractionTarget, displacements: Record<string, Vector3> | undefined): Vector3 | null {
    if (!displacements || !resolved.targetFigure || !resolved.targetAnchor) return null;
    const targetProfile = lookupRigProfile(this.rigProfiles, resolved.targetFigure);
    if (targetProfile === null) return null;
    for (const [label, displacement] of Object.entries(displacements)) {
      if (lookupRigProfile(this.rigProfiles, label) === targetProfile) return displacement;
    }
    return null;
  }
}

/** Root of the effector's alignment chain (shoulder for a hand, hip for a foot). */
function limbRootBone(profile: FigureRigProfile, effectorBone: string): string | null {
  const chain = profile.suggestPrimaryChain(effectorBone);
  const chainNames = chain !== null ? alignmentChainNames(profile, chain) : [];
  return chainNames.length > 0 ? chainNames[0] : null;
}

function limbRootOffset(profile: FigureRigProfile, effectorBone: string): Vector3 | null {
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
function standoffShift(joint: Vector3, sourcePosition: Vector3, rootOffset: Vector3 | null, standoff: number): Vector3 {
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
function surfaceContactPoint(profile: FigureRigProfile, target: ResolvedInteractionTarget, sourceShift: Vector3 | null): Vector3 {
  const point = target.targetPoint!;
  const rootBone = limbRootBone(profile, target.boneName);
  let root: Vector3 | null = rootBone !== null ? profile.bone(rootBone).worldPosition : null;
  if (root === null && profile.figurePosition !== null) root = [profile.figurePosition[0], point[1], profile.figurePosition[2]];
  if (root === null) return point;
  if (sourceShift !== null) root = addVec3(root, sourceShift)!;
  return pullTowardRoot(point, root, target.surfaceStandoff);
}

/** `point` moved `standoff` toward `root` (horizontally when possible), never past the root: on overlapping figures that would aim behind the source. */
function pullTowardRoot(point: Vector3, root: Vector3, standoff: number): Vector3 {
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
const FACING_MAX_SEPARATION = 400;
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

function anchorBoneOffset(profile: FigureRigProfile, anchorName: string): Vector3 | null {
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
function applyFacing(rigProfiles: Record<string, FigureRigProfile>, facing: Record<string, FacingAssignment>): Record<string, FigureRigProfile> {
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
function limbGeometry(profile: FigureRigProfile, effectorBone: string, base: Vector3 | null): { chainRoot: Vector3; reachRoot: Vector3; reach: number } | null {
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
function meetingPoint(rootA: Vector3, lengthA: number, rootB: Vector3, lengthB: number): Vector3 {
  const middle = midpointVec3(rootA, rootB);
  return [middle[0], middle[1] - MEETING_DROP_FRACTION * ((lengthA + lengthB) / 2), middle[2]];
}

/** Where an effector stops (and, for a wrap, the points it passes and where its fingertips aim). */
interface ContactGeometry {
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
function wrapPath(partner: FigureRigProfile, partnerBase: Vector3 | null, targetAnchor: string): { waypoints: Vector3[]; back: Vector3; fingers: Vector3 } | null {
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
function farthestDescendant(profile: FigureRigProfile, boneName: string): string | null {
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

/**
 * Turn a wrapped hand (its bone alone) so its fingertips lie across the
 * partner's back. The wrist stays put; each axis is held within
 * `WRAP_HAND_LIMIT` of rest. Returns diagnostics; empty when the hand has no
 * finger bones.
 */
async function aimWrapHand(
  skeleton: Awaited<ReturnType<RigSceneSource["findSkeletonByLabel"]>>,
  profile: FigureRigProfile,
  handBone: string,
  fingerPoint: Vector3,
  solve: AlignOptions,
): Promise<Record<string, unknown>> {
  const tip = farthestDescendant(profile, handBone);
  if (tip === null) return {};
  const aim = new ResolvedInteractionTarget({ figureLabel: profile.figureLabel, anchorName: handBone, boneName: tip, targetPoint: fingerPoint });
  const result = await alignSingleLimbTarget(skeleton, profile, aim, { chain: [handBone], maxIterations: 40, stepDegrees: solve.stepDegrees, damping: solve.damping, tolerance: 1 });
  const rotation = result.appliedRotations[handBone];
  if (!rotation) return { handAim: result.diagnostics.reason ?? "no_rotation" };
  const clamped = rotation.map((value) => Math.max(-WRAP_HAND_LIMIT, Math.min(WRAP_HAND_LIMIT, value))) as Rotation3;
  const wasClamped = clamped.some((value, i) => value !== rotation[i]);
  if (wasClamped) await skeleton.setBoneRotations({ [handBone]: clamped });
  return { handAimBone: tip, handAimRotation: clamped, handAimClamped: wasClamped };
}

/**
 * Compile a recipe against rig profiles: plan facing (turned partners' profiles
 * replace the originals in `rigProfiles`), validate, and resolve targets.
 */
export function prepareInteractionRecipe(recipe: InteractionRecipe, rigProfiles: Record<string, FigureRigProfile>): PreparedInteractionRecipe {
  const plan = recipe.toPlan();
  const facing = planFacing(plan, rigProfiles);
  const profiles = applyFacing(rigProfiles, facing);
  const validationIssues = plan.validate(profiles);
  const resolvedTargets = plan.resolveTargets(profiles);
  return new PreparedInteractionRecipe({
    recipe,
    plan,
    resolvedTargets,
    rigProfiles: profiles,
    validationIssues,
    facing,
    diagnostics: {
      recipeKind: recipe.kind,
      actorCount: recipe.actors.length,
      constraintCount: recipe.constraints.length,
      resolvedTargetCount: resolvedTargets.length,
      facedFigureCount: Object.keys(facing).length,
    },
  });
}

// ── scene integration ────────────────────────────────────────────────────────

export interface ApplyInteractionRecipeOptions extends InteractionApplyOptions {
  /** Pre-built rig profiles keyed by figure label; omit to build them from one `sceneSnapshot()` call. */
  rigProfiles?: Record<string, FigureRigProfile>;
}

/**
 * Prepare and apply an interaction recipe against a live scene: builds rig
 * profiles from `scene.sceneSnapshot()` (one HTTP call) unless
 * `opts.rigProfiles` is given, then `prepareInteractionRecipe(...).apply()`.
 * Unknown figures/anchors surface as `result.prepared.validationIssues`, not
 * exceptions. `DazScene.applyInteractionRecipe` delegates here.
 */
export async function applyInteractionRecipeToScene(
  scene: Pick<RigSceneSource, "sceneSnapshot" | "findSkeletonByLabel">,
  recipe: InteractionRecipe,
  opts: ApplyInteractionRecipeOptions = {},
): Promise<PreparedInteractionResult> {
  const { rigProfiles, ...applyOpts } = opts;
  const profiles = rigProfiles ?? buildRigProfilesFromSnapshot(await scene.sceneSnapshot());
  return prepareInteractionRecipe(recipe, profiles).apply(scene, applyOpts);
}

// ── recipe builders ──────────────────────────────────────────────────────────

/** The opposite-side shoulder anchor to `anchorName` (right hand -> left shoulder). */
function farShoulder(anchorName: string): string {
  return sideFromName(anchorName) === "right" ? "l_shoulder" : "r_shoulder";
}

function mutualLookAt(actorA: string, actorB: string): LookAtTarget[] {
  return [new LookAtTarget(actorA, "head", [0, 0, 0]), new LookAtTarget(actorB, "head", [0, 0, 0])];
}

function targetAnchorFromStrikeAnchor(anchorName: string): string {
  const lowered = normalizeName(anchorName);
  if (lowered.includes("hand")) return "l_shoulder";
  if (lowered.includes("foot")) return "l_hip";
  return "chest";
}

/** Build a seat/lean preset for a single character. */
export function buildSitRecipe(
  actorLabel: string,
  opts: { seatPoint?: Vector3 | null; supportPoints?: Vector3[] | null; footAnchors?: [string, string] } = {},
): InteractionRecipe {
  const seatPoint = opts.seatPoint ?? null;
  const supportPoints = opts.supportPoints ?? [];
  const constraints: InteractionConstraint[] = [
    new BalanceTarget({
      figureLabel: actorLabel,
      pelvisBone: "pelvis",
      supportPoints: supportPoints.length > 0 ? [...supportPoints] : seatPoint === null ? [] : [seatPoint],
      centerOfMassHint: seatPoint,
    }),
  ];
  (opts.footAnchors ?? ["l_foot", "r_foot"]).forEach((anchorName, index) => {
    const targetPoint = supportPoints.length > 0 ? supportPoints[Math.min(index, supportPoints.length - 1)] : seatPoint;
    constraints.push(new FootTarget({ figureLabel: actorLabel, anchorName, targetPoint }));
  });
  return new InteractionRecipe({ kind: "sit", actors: [actorLabel], constraints, metadata: { seatPoint: seatPoint ? [...seatPoint] : null } });
}

/** Build a touch/contact preset between two figures. */
export function buildTouchRecipe(
  sourceLabel: string,
  targetLabel: string,
  opts: { sourceAnchor?: string; targetAnchor?: string; targetPoint?: Vector3 | null } = {},
): InteractionRecipe {
  const sourceAnchor = opts.sourceAnchor ?? "r_hand";
  const targetAnchor = opts.targetAnchor ?? "l_shoulder";
  return new InteractionRecipe({
    kind: "touch",
    actors: [sourceLabel, targetLabel],
    constraints: [new HandTarget({ figureLabel: sourceLabel, anchorName: sourceAnchor, targetFigure: targetLabel, targetAnchor, targetPoint: opts.targetPoint ?? null })],
    metadata: { sourceAnchor, targetAnchor },
  });
}

/**
 * Build a face-to-face preset with a stabilizing contact plan: mutual
 * look-at, A's `aAnchor` hand on B's opposite shoulder, and B's mirrored hand
 * on A's opposite shoulder (each hand straight ahead once they face each
 * other). (dazpy's `b_anchor` parameter is always overwritten from
 * `a_anchor`'s side, so it is not offered here.)
 */
export function buildKissRecipe(actorA: string, actorB: string, opts: { aAnchor?: string } = {}): InteractionRecipe {
  const aAnchor = opts.aAnchor ?? "r_hand";
  const right = sideFromName(aAnchor) === "right";
  const shoulder = right ? "l_shoulder" : "r_shoulder";
  return new InteractionRecipe({
    kind: "kiss",
    actors: [actorA, actorB],
    constraints: [
      ...mutualLookAt(actorA, actorB),
      new HandTarget({ figureLabel: actorA, anchorName: aAnchor, targetFigure: actorB, targetAnchor: shoulder }),
      new HandTarget({ figureLabel: actorB, anchorName: right ? "l_hand" : "r_hand", targetFigure: actorA, targetAnchor: right ? "r_shoulder" : "l_shoulder" }),
    ],
    metadata: { interaction: "kiss" },
  });
}

/** Build a mirrored hand-to-hand greeting preset for two figures. */
export function buildHandshakeRecipe(actorA: string, actorB: string, opts: { aAnchor?: string; bAnchor?: string } = {}): InteractionRecipe {
  const aAnchor = opts.aAnchor ?? "r_hand";
  const bAnchor = opts.bAnchor ?? "r_hand";
  return new InteractionRecipe({
    kind: "handshake",
    actors: [actorA, actorB],
    constraints: [
      ...mutualLookAt(actorA, actorB),
      new HandTarget({ figureLabel: actorA, anchorName: aAnchor, targetFigure: actorB, targetAnchor: bAnchor }),
      new HandTarget({ figureLabel: actorB, anchorName: bAnchor, targetFigure: actorA, targetAnchor: aAnchor }),
    ],
    metadata: { interaction: "handshake" },
  });
}

/** Build a mutual arms-around-each-other embrace: each arm wraps the partner's side (toward its far shoulder) and the hand rests on its upper back. */
export function buildHugRecipe(actorA: string, actorB: string, opts: { aAnchor?: string; bAnchor?: string } = {}): InteractionRecipe {
  const aAnchor = opts.aAnchor ?? "r_hand";
  const bAnchor = opts.bAnchor ?? "r_hand";
  return new InteractionRecipe({
    kind: "hug",
    actors: [actorA, actorB],
    constraints: [
      ...mutualLookAt(actorA, actorB),
      new HandTarget({ figureLabel: actorA, anchorName: aAnchor, targetFigure: actorB, targetAnchor: farShoulder(aAnchor), wrap: true }),
      new HandTarget({ figureLabel: actorB, anchorName: bAnchor, targetFigure: actorA, targetAnchor: farShoulder(bAnchor), wrap: true }),
    ],
    metadata: { interaction: "hug" },
  });
}

/** Build a mutual eye-contact preset for two figures, with no limb contact. */
export function buildFaceEachOtherRecipe(actorA: string, actorB: string): InteractionRecipe {
  return new InteractionRecipe({
    kind: "face_each_other",
    actors: [actorA, actorB],
    constraints: mutualLookAt(actorA, actorB),
    metadata: { interaction: "face_each_other" },
  });
}

/**
 * Build a simple strike/contact preset for fight choreography. A strike
 * anchor containing "foot" becomes a `FootTarget` (kick); anything else a
 * `HandTarget`. `metadata.strikeTarget` records dazpy's suggested defender
 * anchor for the strike type (hand -> `l_shoulder`, foot -> `l_hip`, else
 * `chest`); the constraint itself aims at `targetAnchor`.
 */
export function buildFightRecipe(attacker: string, defender: string, opts: { strikeAnchor?: string; targetAnchor?: string } = {}): InteractionRecipe {
  const strikeAnchor = opts.strikeAnchor ?? "r_hand";
  const targetAnchor = opts.targetAnchor ?? "head";
  const init: AnchorTargetInit = { figureLabel: attacker, anchorName: strikeAnchor, targetFigure: defender, targetAnchor };
  const strike = normalizeName(strikeAnchor).includes("foot") ? new FootTarget(init) : new HandTarget(init);
  return new InteractionRecipe({
    kind: "fight",
    actors: [attacker, defender],
    constraints: [strike, ...mutualLookAt(attacker, defender)],
    metadata: { strikeAnchor, targetAnchor, strikeTarget: targetAnchorFromStrikeAnchor(strikeAnchor) },
  });
}
