// daz-ts/src/interactionSolve.ts

/**
 * Live limb alignment: a damped-least-squares Jacobian IK solver that rotates
 * a bone chain so its effector reaches a resolved interaction target. Ports
 * the solver half of dazpy's `_interaction.py` (batch path only -- every
 * daz-ts skeleton has `evaluatePoseJacobian`, so dazpy's legacy
 * per-bone-perturbation fallback is not ported).
 *
 * Depends only on `rigProfile.ts`. `interactionPlan.ts` imports this module
 * (for `PreparedInteractionRecipe.alignLimbTargets`), never the reverse, so
 * `LimbAlignmentResult` lives here and `interactionPlan.ts` imports it as a
 * type.
 */

import type { AxisLimit, AxisName, BoneChain, ChainRole, FigureRigProfile, ResolvedInteractionTarget, RigMetadataSource, RigSkeletonSource, Rotation3, Vector3 } from "./rigProfile.js";
import { buildRigProfile, clamp, dotVec3, lengthVec3, subVec3 } from "./rigProfile.js";

/** What the solver needs from a live skeleton. `DazSkeleton` satisfies it structurally. */
export type JacobianSource = Pick<RigSkeletonSource, "boneRotations" | "setBoneRotations" | "evaluatePoseJacobian">;

/** What `alignHandTarget`/`alignFootTarget` need: rig metadata plus the solver calls. */
export type AlignableSkeleton = RigMetadataSource & JacobianSource;

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

/** Result data for a single live target-alignment pass. */
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

// ── numerics ─────────────────────────────────────────────────────────────────

export type Matrix3 = [Vector3, Vector3, Vector3];

const AXES: readonly AxisName[] = ["x", "y", "z"];

/** Clamp each Euler component (degrees) to the bone's per-axis limits, if any. */
export function rotationWithAxisLimits(rotation: Rotation3, axisLimits: Partial<Record<AxisName, AxisLimit>> | null | undefined): Rotation3 {
  if (!axisLimits || Object.keys(axisLimits).length === 0) return rotation;
  const values: Rotation3 = [rotation[0], rotation[1], rotation[2]];
  AXES.forEach((axis, index) => {
    const limit = axisLimits[axis];
    if (limit) values[index] = clamp(values[index], limit.minDegrees, limit.maxDegrees);
  });
  return values;
}

/** Closed-form 3x3 inverse; `null` when the matrix is (near-)singular (|det| < 1e-9). */
export function invert3x3(matrix: Matrix3): Matrix3 | null {
  const [a, b, c] = matrix[0];
  const [d, e, f] = matrix[1];
  const [g, h, i] = matrix[2];
  const det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g);
  if (Math.abs(det) < 1e-9) return null;
  const invDet = 1.0 / det;
  return [
    [(e * i - f * h) * invDet, (c * h - b * i) * invDet, (b * f - c * e) * invDet],
    [(f * g - d * i) * invDet, (a * i - c * g) * invDet, (c * d - a * f) * invDet],
    [(d * h - e * g) * invDet, (b * g - a * h) * invDet, (a * e - b * d) * invDet],
  ];
}

export function mul3x3Vec(matrix: Matrix3, vector: Vector3): Vector3 {
  return [
    matrix[0][0] * vector[0] + matrix[0][1] * vector[1] + matrix[0][2] * vector[2],
    matrix[1][0] * vector[0] + matrix[1][1] * vector[1] + matrix[1][2] * vector[2],
    matrix[2][0] * vector[0] + matrix[2][1] * vector[1] + matrix[2][2] * vector[2],
  ];
}

/**
 * One damped-least-squares step: `delta = J^T (J J^T + λI)^-1 e`.
 *
 * `columns` are the Jacobian's columns (d effector position / d joint
 * degree, one per chain-bone axis), so `J J^T` is always 3x3 regardless of
 * chain length. Returns one joint delta per column, or `null` when there are
 * no columns or the damped matrix is singular.
 */
export function dampedLeastSquaresStep(columns: Vector3[], error: Vector3, damping: number): number[] | null {
  if (columns.length === 0) return null;
  const jj: Matrix3 = [
    [0, 0, 0],
    [0, 0, 0],
    [0, 0, 0],
  ];
  for (const column of columns) {
    for (let r = 0; r < 3; r++) {
      for (let c = 0; c < 3; c++) jj[r][c] += column[r] * column[c];
    }
  }
  jj[0][0] += damping;
  jj[1][1] += damping;
  jj[2][2] += damping;
  const inv = invert3x3(jj);
  if (inv === null) return null;
  const y = mul3x3Vec(inv, error);
  return columns.map((column) => dotVec3(column, y));
}

// ── chain selection ──────────────────────────────────────────────────────────

const ROLE_CHAIN_LIMITS: Record<ChainRole, number> = {
  hand: 4,
  arm: 4,
  foot: 4,
  leg: 4,
  head: 2,
  neck: 2,
  spine: 3,
  pelvis: 2,
  custom: 3,
};

/**
 * The bones the solver actually rotates for a chain: known, non-helper bones,
 * excluding the effector itself (the chain's last bone), capped to the
 * nearest N ancestors for the chain's role.
 */
export function alignmentChainNames(profile: FigureRigProfile, chain: BoneChain): string[] {
  const known = new Set(profile.boneNames());
  const candidates = chain.bones.filter((name) => known.has(name) && !profile.bone(name).isHelper);
  if (candidates.length <= 1) return candidates;
  const limit = ROLE_CHAIN_LIMITS[chain.role] ?? 3;
  return candidates.slice(0, -1).slice(-limit);
}

// ── alignment ────────────────────────────────────────────────────────────────

export interface AlignOptions {
  maxIterations?: number;
  stepDegrees?: number;
  damping?: number;
  tolerance?: number;
  /** Bones to rotate, root first, instead of the chain the profile suggests for the effector (e.g. just a hand, to aim its fingers). */
  chain?: string[];
}

/**
 * Iteratively align a single limb chain to a resolved interaction target.
 *
 * Each iteration costs two HTTP calls: `setBoneRotations` with the clamped
 * step, then `evaluatePoseJacobian` for the new effector position and
 * columns. Never throws for expected failures -- the result's
 * `diagnostics.reason` names them (`missing_target_point`, `missing_chain`,
 * `missing_effector_position`, `jacobian_shape_mismatch`,
 * `already_aligned`).
 */
export async function alignSingleLimbTarget(
  skeleton: JacobianSource,
  profile: FigureRigProfile,
  target: ResolvedInteractionTarget,
  opts: AlignOptions = {},
): Promise<LimbAlignmentResult> {
  const maxIterations = opts.maxIterations ?? 12;
  const stepDegrees = opts.stepDegrees ?? 1.0;
  const damping = opts.damping ?? 0.25;
  const tolerance = opts.tolerance ?? 0.15;
  const base = { figureLabel: target.figureLabel, anchorName: target.anchorName, effectorBone: target.boneName };

  const targetPoint = target.targetPoint;
  if (targetPoint === null) {
    return new LimbAlignmentResult({ ...base, chain: [], targetPoint: null, diagnostics: { reason: "missing_target_point" } });
  }

  const chain = opts.chain ? null : profile.suggestPrimaryChain(target.boneName);
  const chainNames = opts.chain ? [...opts.chain] : chain !== null ? alignmentChainNames(profile, chain) : [];
  if (chainNames.length === 0) {
    return new LimbAlignmentResult({ ...base, chain: [], targetPoint, diagnostics: { reason: "missing_chain" } });
  }

  const allRotations = await skeleton.boneRotations();
  const currentRotations: Record<string, Rotation3> = {};
  for (const name of chainNames) {
    const rotation = allRotations[name];
    currentRotations[name] = rotation ? [rotation[0], rotation[1], rotation[2]] : [0, 0, 0];
  }
  const expectedColumns = chainNames.length * 3;

  let jac = await skeleton.evaluatePoseJacobian(chainNames, target.boneName, stepDegrees);
  if (jac === null) {
    return new LimbAlignmentResult({ ...base, chain: chainNames, targetPoint, diagnostics: { reason: "missing_effector_position" } });
  }
  if (jac.columns.length !== expectedColumns) {
    return new LimbAlignmentResult({
      ...base,
      chain: chainNames,
      targetPoint,
      diagnostics: { reason: "jacobian_shape_mismatch", expectedColumns, actualColumns: jac.columns.length },
    });
  }

  let basePosition: Vector3 = jac.basePosition;
  let columns: Vector3[] = jac.columns;

  const initialError = lengthVec3(subVec3(targetPoint, basePosition));
  if (initialError <= tolerance) {
    return new LimbAlignmentResult({
      ...base,
      chain: chainNames,
      targetPoint,
      iterations: 0,
      converged: true,
      initialError,
      finalError: initialError,
      appliedRotations: { ...currentRotations },
      diagnostics: { reason: "already_aligned" },
    });
  }

  let iterations = 0;
  let converged = false;
  let finalPosition: Vector3 = basePosition;

  for (let iteration = 0; iteration < maxIterations; iteration++) {
    iterations = iteration + 1;
    const currentError = subVec3(targetPoint, basePosition);
    if (lengthVec3(currentError) <= tolerance) {
      converged = true;
      finalPosition = basePosition;
      break;
    }

    let delta = dampedLeastSquaresStep(columns, currentError, damping);
    if (delta === null) break;

    const maxDelta = Math.max(...delta.map((v) => Math.abs(v)));
    if (maxDelta > stepDegrees) {
      const scale = stepDegrees / maxDelta;
      delta = delta.map((v) => v * scale);
    }

    const newRotations: Record<string, Rotation3> = {};
    chainNames.forEach((name, boneIndex) => {
      const current = currentRotations[name];
      const start = boneIndex * 3;
      const next: Rotation3 = [current[0] + delta![start], current[1] + delta![start + 1], current[2] + delta![start + 2]];
      const clamped = rotationWithAxisLimits(next, profile.bone(name).axisLimits);
      newRotations[name] = clamped;
      currentRotations[name] = clamped;
    });

    await skeleton.setBoneRotations(newRotations);

    jac = await skeleton.evaluatePoseJacobian(chainNames, target.boneName, stepDegrees);
    if (jac === null || jac.columns.length !== expectedColumns) break;
    basePosition = jac.basePosition;
    columns = jac.columns;
    finalPosition = basePosition;
  }

  const finalError = lengthVec3(subVec3(targetPoint, finalPosition));
  return new LimbAlignmentResult({
    ...base,
    chain: chainNames,
    targetPoint,
    iterations,
    converged,
    initialError,
    finalError,
    appliedRotations: { ...currentRotations },
    diagnostics: { stepDegrees, damping, tolerance, path: "batch" },
  });
}

export interface AlignAnchorOptions extends AlignOptions {
  /** Anchor on the skeleton to move (default `r_hand` / `r_foot`). */
  sourceAnchor?: string;
}

async function alignAnchorTarget(
  skeleton: AlignableSkeleton,
  targetPoint: Vector3 | null,
  defaultAnchor: string,
  opts: AlignAnchorOptions,
): Promise<LimbAlignmentResult> {
  const profile = await buildRigProfile(skeleton);
  const resolved = profile.resolveAnchorTarget(
    { figureLabel: profile.figureLabel, anchorName: opts.sourceAnchor ?? defaultAnchor, targetPoint, offset: [0, 0, 0] },
    { [profile.figureLabel]: profile },
  );
  return alignSingleLimbTarget(skeleton, profile, resolved, opts);
}

/** Rotate a skeleton's arm chain so its hand anchor (default `r_hand`) reaches a world point. Throws if the anchor does not exist on the rig. */
export function alignHandTarget(skeleton: AlignableSkeleton, targetPoint: Vector3 | null, opts: AlignAnchorOptions = {}): Promise<LimbAlignmentResult> {
  return alignAnchorTarget(skeleton, targetPoint, "r_hand", opts);
}

/** Rotate a skeleton's leg chain so its foot anchor (default `r_foot`) reaches a world point. Throws if the anchor does not exist on the rig. */
export function alignFootTarget(skeleton: AlignableSkeleton, targetPoint: Vector3 | null, opts: AlignAnchorOptions = {}): Promise<LimbAlignmentResult> {
  return alignAnchorTarget(skeleton, targetPoint, "r_foot", opts);
}
