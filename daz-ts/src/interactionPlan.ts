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
