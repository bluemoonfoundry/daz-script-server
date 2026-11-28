// daz-ts/src/interactionTargets.ts

/**
 * Interaction constraint types: pose, hand/foot anchor, contact, look-at and
 * balance targets. Ports the target half of dazpy's `_interaction_profile.py`.
 * Depends only on `rigProfile.ts`.
 */

import type { AnchorTargetLike, Rotation3, Vector3 } from "./rigProfile.js";

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
