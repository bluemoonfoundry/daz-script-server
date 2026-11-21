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
import { addVec3, asVector3, averageVec3, lookupRigProfile, midpointVec3, subVec3, ResolvedInteractionTarget } from "./rigProfile.js";

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
