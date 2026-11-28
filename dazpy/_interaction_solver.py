"""Damped-least-squares limb IK: align one limb's effector to a world target."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ._interaction_profile import (
    AxisLimit,
    AxisName,
    FigureRigProfile,
    FootTarget,
    HandTarget,
    ResolvedInteractionTarget,
    Rotation3,
    Vector3,
    _alignment_chain_names,
    _as_tuple3,
    _vec3_dot,
    _vec3_length,
    _vec3_scale,
    _vec3_sub,
    build_rig_profile,
    resolve_interaction_target,
)

if TYPE_CHECKING:
    from ._skeleton import DazSkeleton


@dataclass(frozen=True)
class LimbAlignmentResult:
    """Result data for a single live target-alignment pass."""

    figure_label: str
    anchor_name: str
    effector_bone: str
    chain: list[str]
    target_point: Vector3 | None
    iterations: int = 0
    converged: bool = False
    initial_error: float | None = None
    final_error: float | None = None
    applied_rotations: dict[str, Rotation3] = field(default_factory=dict)
    diagnostics: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "figure_label": self.figure_label,
            "anchor_name": self.anchor_name,
            "effector_bone": self.effector_bone,
            "chain": list(self.chain),
            "target_point": list(self.target_point) if self.target_point else None,
            "iterations": self.iterations,
            "converged": self.converged,
            "initial_error": self.initial_error,
            "final_error": self.final_error,
            "applied_rotations": {name: list(rotation) for name, rotation in self.applied_rotations.items()},
            "diagnostics": dict(self.diagnostics),
        }


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def _rotation_with_axis_limits(rotation: Rotation3, axis_limits: dict[AxisName, AxisLimit] | None) -> Rotation3:
    if not axis_limits:
        return rotation
    values = [rotation[0], rotation[1], rotation[2]]
    axes: tuple[AxisName, ...] = ("x", "y", "z")
    for index, axis in enumerate(axes):
        limit = axis_limits.get(axis)
        if limit is not None:
            values[index] = _clamp(values[index], limit.min_degrees, limit.max_degrees)
    return (values[0], values[1], values[2])


def _rotation_axis_value(rotation: Rotation3, axis: int) -> float:
    return rotation[axis]


def _set_rotation_axis(rotation: Rotation3, axis: int, value: float) -> Rotation3:
    values = [rotation[0], rotation[1], rotation[2]]
    values[axis] = value
    return (values[0], values[1], values[2])


def _invert_3x3(matrix: list[list[float]]) -> list[list[float]] | None:
    a, b, c = matrix[0]
    d, e, f = matrix[1]
    g, h, i = matrix[2]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(det) < 1e-9:
        return None
    inv_det = 1.0 / det
    return [
        [
            (e * i - f * h) * inv_det,
            (c * h - b * i) * inv_det,
            (b * f - c * e) * inv_det,
        ],
        [
            (f * g - d * i) * inv_det,
            (a * i - c * g) * inv_det,
            (c * d - a * f) * inv_det,
        ],
        [
            (d * h - e * g) * inv_det,
            (b * g - a * h) * inv_det,
            (a * e - b * d) * inv_det,
        ],
    ]


def _mul_3x3_vec(matrix: list[list[float]], vector: Vector3) -> Vector3:
    return (
        matrix[0][0] * vector[0] + matrix[0][1] * vector[1] + matrix[0][2] * vector[2],
        matrix[1][0] * vector[0] + matrix[1][1] * vector[1] + matrix[1][2] * vector[2],
        matrix[2][0] * vector[0] + matrix[2][1] * vector[1] + matrix[2][2] * vector[2],
    )


def _damped_least_squares_step(columns: list[Vector3], error: Vector3, damping: float) -> list[float] | None:
    if not columns:
        return None
    jj = [
        [0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0],
    ]
    for column in columns:
        jj[0][0] += column[0] * column[0]
        jj[0][1] += column[0] * column[1]
        jj[0][2] += column[0] * column[2]
        jj[1][0] += column[1] * column[0]
        jj[1][1] += column[1] * column[1]
        jj[1][2] += column[1] * column[2]
        jj[2][0] += column[2] * column[0]
        jj[2][1] += column[2] * column[1]
        jj[2][2] += column[2] * column[2]
    jj[0][0] += damping
    jj[1][1] += damping
    jj[2][2] += damping
    inv = _invert_3x3(jj)
    if inv is None:
        return None
    y = _mul_3x3_vec(inv, error)
    return [_vec3_dot(column, y) for column in columns]


def _bone_world_position(bone: object) -> Vector3 | None:
    return _as_tuple3(getattr(bone, "position", None))


def _align_single_limb_batch(
    skeleton: DazSkeleton,
    profile: FigureRigProfile,
    chain_names: list[str],
    target: ResolvedInteractionTarget,
    *,
    max_iterations: int = 12,
    step_degrees: float = 1.0,
    damping: float = 0.25,
    tolerance: float = 0.15,
) -> LimbAlignmentResult:
    """Batch IK path: 2 HTTP calls per iteration via evaluate_pose_jacobian."""

    target_point = target.target_point
    if target_point is None:  # align_single_limb_target returns before calling us
        raise ValueError("batch limb alignment needs a resolved target_point")

    all_rotations = skeleton.bone_rotations()
    current_rotations: dict[str, Rotation3] = {
        name: all_rotations.get(name, (0.0, 0.0, 0.0))
        for name in chain_names
    }

    jac = skeleton.evaluate_pose_jacobian(chain_names, target.bone_name, step_degrees)
    if jac is None:
        return LimbAlignmentResult(
            figure_label=target.figure_label,
            anchor_name=target.anchor_name,
            effector_bone=target.bone_name,
            chain=chain_names,
            target_point=target.target_point,
            diagnostics={"reason": "missing_effector_position"},
        )

    base_position: Vector3 = tuple(jac["base_position"])  # type: ignore[assignment]
    columns: list[Vector3] = [tuple(c) for c in jac["columns"]]  # type: ignore[misc]

    initial_error = _vec3_length(_vec3_sub(target_point, base_position))
    if initial_error <= tolerance:
        return LimbAlignmentResult(
            figure_label=target.figure_label,
            anchor_name=target.anchor_name,
            effector_bone=target.bone_name,
            chain=chain_names,
            target_point=target.target_point,
            iterations=0,
            converged=True,
            initial_error=initial_error,
            final_error=initial_error,
            applied_rotations=dict(current_rotations),
            diagnostics={"reason": "already_aligned"},
        )

    iterations = 0
    converged = False
    final_position: Vector3 = base_position

    for iteration in range(max_iterations):
        iterations = iteration + 1
        current_error = _vec3_sub(target_point, base_position)
        if _vec3_length(current_error) <= tolerance:
            converged = True
            final_position = base_position
            break

        delta = _damped_least_squares_step(columns, current_error, damping)
        if delta is None:
            break

        max_delta = max(abs(v) for v in delta) if delta else 0.0
        if max_delta > step_degrees:
            scale = step_degrees / max_delta
            delta = [v * scale for v in delta]

        new_rotations: dict[str, Rotation3] = {}
        for bone_index, name in enumerate(chain_names):
            curr = current_rotations[name]
            start = bone_index * 3
            next_rot: Rotation3 = (
                curr[0] + delta[start],
                curr[1] + delta[start + 1],
                curr[2] + delta[start + 2],
            )
            profile_bone = profile.bone(name)
            clamped = _rotation_with_axis_limits(next_rot, profile_bone.axis_limits or None)
            new_rotations[name] = clamped
            current_rotations[name] = clamped

        skeleton.set_bone_rotations(dict(new_rotations))

        jac = skeleton.evaluate_pose_jacobian(chain_names, target.bone_name, step_degrees)
        if jac is None:
            break
        base_position = tuple(jac["base_position"])  # type: ignore[assignment]
        columns = [tuple(c) for c in jac["columns"]]  # type: ignore[misc]
        final_position = base_position

    final_error = _vec3_length(_vec3_sub(target_point, final_position))
    return LimbAlignmentResult(
        figure_label=target.figure_label,
        anchor_name=target.anchor_name,
        effector_bone=target.bone_name,
        chain=chain_names,
        target_point=target.target_point,
        iterations=iterations,
        converged=converged,
        initial_error=initial_error,
        final_error=final_error,
        applied_rotations=dict(current_rotations),
        diagnostics={
            "step_degrees": step_degrees,
            "damping": damping,
            "tolerance": tolerance,
            "path": "batch",
        },
    )


def align_single_limb_target(
    skeleton: DazSkeleton,
    profile: FigureRigProfile,
    target: ResolvedInteractionTarget,
    *,
    max_iterations: int = 12,
    step_degrees: float = 1.0,
    damping: float = 0.25,
    tolerance: float = 0.15,
) -> LimbAlignmentResult:
    """Iteratively align a single limb chain to a resolved interaction target."""

    if target.target_point is None:
        return LimbAlignmentResult(
            figure_label=target.figure_label,
            anchor_name=target.anchor_name,
            effector_bone=target.bone_name,
            chain=[],
            target_point=None,
            diagnostics={"reason": "missing_target_point"},
        )

    chain = profile.suggest_primary_chain(target.bone_name)
    chain_names = _alignment_chain_names(profile, chain) if chain is not None else []
    if not chain_names:
        return LimbAlignmentResult(
            figure_label=target.figure_label,
            anchor_name=target.anchor_name,
            effector_bone=target.bone_name,
            chain=[],
            target_point=target.target_point,
            diagnostics={"reason": "missing_chain"},
        )

    if hasattr(skeleton, "evaluate_pose_jacobian") and hasattr(skeleton, "_client"):
        return _align_single_limb_batch(
            skeleton, profile, chain_names, target,
            max_iterations=max_iterations,
            step_degrees=step_degrees,
            damping=damping,
            tolerance=tolerance,
        )

    bones = [skeleton.find_bone(name) for name in chain_names]
    # Key by the bone's own name, falling back to the chain name it was found by.
    named_bones = [(bone.name or name, bone) for name, bone in zip(chain_names, bones)]
    effector = skeleton.find_bone(target.bone_name)
    base_position = _bone_world_position(effector)
    if base_position is None:
        return LimbAlignmentResult(
            figure_label=target.figure_label,
            anchor_name=target.anchor_name,
            effector_bone=target.bone_name,
            chain=chain_names,
            target_point=target.target_point,
            diagnostics={"reason": "missing_effector_position"},
        )

    current_error = _vec3_sub(target.target_point, base_position)
    initial_error = _vec3_length(current_error)
    if initial_error <= tolerance:
        return LimbAlignmentResult(
            figure_label=target.figure_label,
            anchor_name=target.anchor_name,
            effector_bone=target.bone_name,
            chain=chain_names,
            target_point=target.target_point,
            iterations=0,
            converged=True,
            initial_error=initial_error,
            final_error=initial_error,
            applied_rotations={name: _as_tuple3(getattr(bone, "local_euler", None)) or (0.0, 0.0, 0.0) for name, bone in named_bones},
            diagnostics={"reason": "already_aligned"},
        )

    iterations = 0
    converged = False
    for iteration in range(max_iterations):
        iterations = iteration + 1
        base_position = _bone_world_position(effector)
        if base_position is None:
            break
        current_error = _vec3_sub(target.target_point, base_position)
        if _vec3_length(current_error) <= tolerance:
            converged = True
            break

        columns: list[Vector3] = []
        original_rotations: dict[str, Rotation3] = {}
        for name, bone in named_bones:
            current_rotation = _as_tuple3(getattr(bone, "local_euler", None)) or (0.0, 0.0, 0.0)
            original_rotations[name] = current_rotation
            profile_bone = profile.bone(name)
            for axis in range(3):
                trial_rotation = _set_rotation_axis(current_rotation, axis, _rotation_axis_value(current_rotation, axis) + step_degrees)
                trial_rotation = _rotation_with_axis_limits(trial_rotation, profile_bone.axis_limits if profile_bone.axis_limits else None)
                bone.set_local_rotation(*trial_rotation)
                trial_position = _bone_world_position(effector)
                if trial_position is None:
                    columns.append((0.0, 0.0, 0.0))
                else:
                    columns.append(_vec3_scale(_vec3_sub(trial_position, base_position), 1.0 / step_degrees))
                bone.set_local_rotation(*current_rotation)

        delta = _damped_least_squares_step(columns, current_error, damping)
        if delta is None:
            break

        max_delta = max(abs(value) for value in delta) if delta else 0.0
        if max_delta > step_degrees:
            scale = step_degrees / max_delta
            delta = [value * scale for value in delta]

        for bone_index, (name, bone) in enumerate(named_bones):
            current_rotation = original_rotations[name]
            start = bone_index * 3
            next_rotation = (
                current_rotation[0] + delta[start],
                current_rotation[1] + delta[start + 1],
                current_rotation[2] + delta[start + 2],
            )
            profile_bone = profile.bone(name)
            bone.set_local_rotation(*_rotation_with_axis_limits(next_rotation, profile_bone.axis_limits if profile_bone.axis_limits else None))

    final_position = _bone_world_position(effector)
    final_error = _vec3_length(_vec3_sub(target.target_point, final_position)) if final_position is not None else None
    applied_rotations = {
        name: _as_tuple3(getattr(bone, "local_euler", None)) or (0.0, 0.0, 0.0)
        for name, bone in named_bones
    }
    return LimbAlignmentResult(
        figure_label=target.figure_label,
        anchor_name=target.anchor_name,
        effector_bone=target.bone_name,
        chain=chain_names,
        target_point=target.target_point,
        iterations=iterations,
        converged=converged,
        initial_error=initial_error,
        final_error=final_error,
        applied_rotations=applied_rotations,
        diagnostics={
            "step_degrees": step_degrees,
            "damping": damping,
            "tolerance": tolerance,
        },
    )


def align_hand_target(
    skeleton: DazSkeleton,
    target_point: object | None,
    *,
    source_anchor: str = "r_hand",
    max_iterations: int = 12,
    step_degrees: float = 1.0,
    damping: float = 0.25,
    tolerance: float = 0.15,
) -> LimbAlignmentResult:
    """Convenience wrapper for a live hand-to-point alignment."""

    if not hasattr(skeleton, "bones") or not hasattr(skeleton, "find_bone"):
        raise TypeError("align_hand_target expects a skeleton-like object")
    profile = build_rig_profile(skeleton)
    figure_label = profile.figure_label or skeleton.label or skeleton._identifier.value
    resolved = resolve_interaction_target(
        HandTarget(
            figure_label=figure_label,
            anchor_name=source_anchor,
            target_point=_as_tuple3(target_point),
        ),
        {figure_label: profile},
    )
    return align_single_limb_target(
        skeleton,
        profile,
        resolved,
        max_iterations=max_iterations,
        step_degrees=step_degrees,
        damping=damping,
        tolerance=tolerance,
    )


def align_foot_target(
    skeleton: DazSkeleton,
    target_point: object | None,
    *,
    source_anchor: str = "r_foot",
    max_iterations: int = 12,
    step_degrees: float = 1.0,
    damping: float = 0.25,
    tolerance: float = 0.15,
) -> LimbAlignmentResult:
    """Convenience wrapper for a live foot-to-point alignment."""

    if not hasattr(skeleton, "bones") or not hasattr(skeleton, "find_bone"):
        raise TypeError("align_foot_target expects a skeleton-like object")
    profile = build_rig_profile(skeleton)
    figure_label = profile.figure_label or skeleton.label or skeleton._identifier.value
    resolved = resolve_interaction_target(
        FootTarget(
            figure_label=figure_label,
            anchor_name=source_anchor,
            target_point=_as_tuple3(target_point),
        ),
        {figure_label: profile},
    )
    return align_single_limb_target(
        skeleton,
        profile,
        resolved,
        max_iterations=max_iterations,
        step_degrees=step_degrees,
        damping=damping,
        tolerance=tolerance,
    )
