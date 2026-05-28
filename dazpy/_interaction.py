from __future__ import annotations

from dataclasses import dataclass, field
import re
import math
from typing import TYPE_CHECKING, Literal

from .math3 import Quat, Vec3

if TYPE_CHECKING:
    from ._skeleton import DazSkeleton


Rotation3 = tuple[float, float, float]
Vector3 = tuple[float, float, float]
SolveBackend = Literal["scipy", "pinocchio", "ikpy"]
ConstraintKind = Literal["pose_target", "contact", "look_at", "balance", "custom"]
AxisName = Literal["x", "y", "z"]
ChainSide = Literal["left", "right", "center", "unknown"]
ChainRole = Literal["arm", "leg", "spine", "neck", "head", "hand", "foot", "pelvis", "custom"]


def _normalize_name(value: str | None) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def _as_tuple3(value: object | None) -> Rotation3 | None:
    if value is None:
        return None
    if isinstance(value, tuple) and len(value) == 3:
        return (float(value[0]), float(value[1]), float(value[2]))
    if isinstance(value, list) and len(value) == 3:
        return (float(value[0]), float(value[1]), float(value[2]))
    return None


def _lower_name(value: str | None) -> str:
    return (value or "").strip().lower()


def _detect_figure_family(bone_names: list[str]) -> str:
    names = {_lower_name(name) for name in bone_names}
    if any(name.startswith(("r_", "l_")) for name in names):
        if any("forearm" in name for name in names):
            return "genesis_9"
        if any(name.endswith("_twist") for name in names):
            return "genesis_9"
    if any("_" in name for name in names):
        return "underscore_rig"
    if any("forearmbend" in name for name in names):
        return "genesis_3_8"
    if any("forearm" in name for name in names):
        return "genesis_1_2"
    return "generic"


def _looks_like_twist(name: str, label: str | None = None) -> bool:
    lowered = f"{name} {label or ''}".lower()
    return "twist" in lowered or lowered.endswith("bendtwist")


def _looks_like_helper(name: str, label: str | None = None) -> bool:
    lowered = f"{name} {label or ''}".lower()
    return any(token in lowered for token in ("helper", "end", "end point", "endpoint"))


def _side_from_name(name: str) -> ChainSide:
    lowered = _normalize_name(name)
    if lowered.startswith(("l_", "left_")) or lowered.startswith("l") and len(lowered) > 1 and lowered[1] == "_":
        return "left"
    if lowered.startswith(("r_", "right_")) or lowered.startswith("r") and len(lowered) > 1 and lowered[1] == "_":
        return "right"
    if lowered.startswith(("center_", "c_", "spine", "pelvis", "hip", "head", "neck")):
        return "center"
    return "unknown"


def _match_tokens(name: str, tokens: tuple[str, ...]) -> bool:
    lowered = _normalize_name(name)
    return all(token in lowered for token in tokens)


def _match_any(name: str, tokens: tuple[str, ...]) -> bool:
    lowered = _normalize_name(name)
    return any(token in lowered for token in tokens)


def _side_matches(name: str, side: ChainSide) -> bool:
    if side in ("center", "unknown"):
        return True
    return _side_from_name(name) == side


@dataclass(frozen=True)
class BoneProfile:
    """Metadata for a single figure bone.

    This is the adapter-facing representation we need before we can solve
    anything reliably.  It captures the bone relationship and the DAZ-specific
    control metadata that matters for interaction posing.
    """

    name: str
    label: str | None = None
    parent_name: str | None = None
    rotation_order: str | None = None
    local_position: Vector3 | None = None
    rest_rotation: Rotation3 | None = None
    axis_limits: dict[AxisName, "AxisLimit"] = field(default_factory=dict)
    is_twist: bool = False
    is_helper: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "parent_name": self.parent_name,
            "rotation_order": self.rotation_order,
            "local_position": list(self.local_position) if self.local_position else None,
            "rest_rotation": list(self.rest_rotation) if self.rest_rotation else None,
            "axis_limits": {axis: limit.to_dict() for axis, limit in self.axis_limits.items()},
            "is_twist": self.is_twist,
            "is_helper": self.is_helper,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BoneProfile":
        return cls(
            name=data.get("name", ""),
            label=data.get("label"),
            parent_name=data.get("parent_name"),
            rotation_order=data.get("rotation_order"),
            local_position=_as_tuple3(data.get("local_position")),
            rest_rotation=_as_tuple3(data.get("rest_rotation")),
            axis_limits={
                axis: AxisLimit.from_dict(limit)
                for axis, limit in dict(data.get("axis_limits", {})).items()
            },
            is_twist=bool(data.get("is_twist", False)),
            is_helper=bool(data.get("is_helper", False)),
        )


@dataclass(frozen=True)
class AxisLimit:
    """A single-axis joint limit in degrees."""

    axis: AxisName
    min_degrees: float
    max_degrees: float
    preferred_degrees: float = 0.0
    weight: float = 1.0

    def to_dict(self) -> dict:
        return {
            "axis": self.axis,
            "min_degrees": self.min_degrees,
            "max_degrees": self.max_degrees,
            "preferred_degrees": self.preferred_degrees,
            "weight": self.weight,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AxisLimit":
        return cls(
            axis=data.get("axis", "x"),
            min_degrees=float(data.get("min_degrees", 0.0)),
            max_degrees=float(data.get("max_degrees", 0.0)),
            preferred_degrees=float(data.get("preferred_degrees", 0.0)),
            weight=float(data.get("weight", 1.0)),
        )


@dataclass(frozen=True)
class BoneChain:
    """A solver-friendly chain extracted from a figure rig."""

    figure_label: str
    role: ChainRole
    side: ChainSide
    bones: list[str]
    effector_bone: str
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "figure_label": self.figure_label,
            "role": self.role,
            "side": self.side,
            "bones": list(self.bones),
            "effector_bone": self.effector_bone,
            "metadata": dict(self.metadata),
        }


@dataclass
class FigureRigProfile:
    """A DAZ figure expressed as a solver-friendly rig profile."""

    figure_label: str
    family: str
    bones: list[BoneProfile] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._index = {bone.name: i for i, bone in enumerate(self.bones)}

    def bone_names(self) -> list[str]:
        return [bone.name for bone in self.bones]

    def bone(self, name: str) -> BoneProfile:
        try:
            return self.bones[self._index[name]]
        except KeyError as exc:
            raise KeyError(f"Bone not found in rig profile: {name!r}") from exc

    def ancestry(self, bone_name: str) -> list[BoneProfile]:
        """Return root-to-bone ancestry for the named bone."""
        chain: list[BoneProfile] = []
        current = self.bone(bone_name)
        seen: set[str] = set()
        while True:
            if current.name in seen:
                raise ValueError(f"Cycle detected in rig profile around {current.name!r}")
            seen.add(current.name)
            chain.append(current)
            if current.parent_name is None:
                break
            current = self.bone(current.parent_name)
        chain.reverse()
        return chain

    def chain_to(self, bone_name: str) -> list[str]:
        return [bone.name for bone in self.ancestry(bone_name)]

    def chain_for(self, bone_name: str, role: ChainRole, side: ChainSide = "unknown") -> BoneChain:
        bones = self.chain_to(bone_name)
        return BoneChain(
            figure_label=self.figure_label,
            role=role,
            side=side,
            bones=bones,
            effector_bone=bone_name,
        )

    def _find_bone_by_predicate(self, predicate) -> BoneProfile | None:
        for bone in self.bones:
            if predicate(bone):
                return bone
        return None

    def _find_terminal_bone(self, candidates: list[tuple[ChainRole, ChainSide, tuple[str, ...]]]) -> BoneProfile | None:
        for role, side, tokens in candidates:
            for bone in self.bones:
                if _match_tokens(bone.name, tokens):
                    return bone
        return None

    def chain_suggestions(self) -> list[BoneChain]:
        """Return the main interaction chains this rig appears to support."""

        suggestions: list[BoneChain] = []
        templates = [
            ("arm", "left", (("hand",), ("forearm",), ("upper_arm",), ("clavicle",))),
            ("arm", "right", (("hand",), ("forearm",), ("upper_arm",), ("clavicle",))),
            ("leg", "left", (("foot",), ("shin",), ("thigh",), ("pelvis", "hip"))),
            ("leg", "right", (("foot",), ("shin",), ("thigh",), ("pelvis", "hip"))),
            ("spine", "center", (("head",), ("neck",), ("chest",), ("abdomen",), ("spine",), ("hip",))),
        ]
        for role, side, token_groups in templates:
            terminal = None
            for tokens in token_groups:
                terminal = self._find_bone_by_predicate(
                    lambda bone, toks=tokens, wanted_side=side: _match_tokens(bone.name, toks) and _side_matches(bone.name, wanted_side)
                )
                if terminal is not None:
                    break
            if terminal is None:
                continue
            suggestions.append(self.chain_for(terminal.name, role=role, side=side))
        return suggestions

    def suggest_primary_chain(self, bone_name: str | None = None) -> BoneChain | None:
        """Infer the most likely solver chain for a named bone or a rig default."""
        if bone_name is not None:
            bone = self.bone(bone_name)
            side = _side_from_name(bone.name)
            if _match_any(bone.name, ("hand",)):
                return self.chain_for(bone.name, role="hand", side=side)
            if _match_any(bone.name, ("foot", "toe")):
                return self.chain_for(bone.name, role="foot", side=side)
            if _match_any(bone.name, ("head",)):
                return self.chain_for(bone.name, role="head", side="center")
            if _match_any(bone.name, ("neck",)):
                return self.chain_for(bone.name, role="neck", side="center")
            if _match_any(bone.name, ("forearm", "upper_arm", "clavicle", "shoulder")):
                return self.chain_for(bone.name, role="arm", side=side)
            if _match_any(bone.name, ("shin", "thigh", "calf", "knee")):
                return self.chain_for(bone.name, role="leg", side=side)
            return self.chain_for(bone.name, role="custom", side=side)

        chains = self.chain_suggestions()
        return chains[0] if chains else None

    def to_dict(self) -> dict:
        return {
            "figure_label": self.figure_label,
            "family": self.family,
            "bones": [bone.to_dict() for bone in self.bones],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FigureRigProfile":
        return cls(
            figure_label=data.get("figure_label", ""),
            family=data.get("family", "generic"),
            bones=[BoneProfile.from_dict(item) for item in data.get("bones", [])],
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(frozen=True)
class PoseTarget:
    """A target for one bone or control chain."""

    figure_label: str
    bone_name: str
    position: Vector3 | None = None
    orientation: Rotation3 | None = None
    space: Literal["world", "local", "parent"] = "world"
    weight: float = 1.0


@dataclass(frozen=True)
class ContactTarget:
    """A soft contact between two actors or between an actor and a prop."""

    source_figure: str
    source_bone: str
    target_figure: str | None = None
    target_bone: str | None = None
    target_point: Vector3 | None = None
    normal: Vector3 | None = None
    offset: Vector3 | None = None
    weight: float = 1.0
    penetration_allowance: float = 0.0


@dataclass(frozen=True)
class LookAtTarget:
    """A gaze target for a head, neck, or eye chain."""

    figure_label: str
    bone_name: str
    target_point: Vector3
    weight: float = 1.0


@dataclass(frozen=True)
class BalanceTarget:
    """A balance and root-placement target for seated or standing poses."""

    figure_label: str
    pelvis_bone: str
    support_points: list[Vector3] = field(default_factory=list)
    center_of_mass_hint: Vector3 | None = None
    weight: float = 1.0


@dataclass
class SolveOptions:
    """Backend and weighting controls for pose solving."""

    backend: SolveBackend = "scipy"
    max_iterations: int = 100
    position_weight: float = 1.0
    orientation_weight: float = 1.0
    joint_limit_weight: float = 10.0
    rest_pose_weight: float = 0.5
    contact_weight: float = 2.0
    collision_weight: float = 5.0
    use_joint_limits: bool = True
    damping: float = 1e-3
    verbose: bool = False

    def to_dict(self) -> dict:
        return {
            "backend": self.backend,
            "max_iterations": self.max_iterations,
            "position_weight": self.position_weight,
            "orientation_weight": self.orientation_weight,
            "joint_limit_weight": self.joint_limit_weight,
            "rest_pose_weight": self.rest_pose_weight,
            "contact_weight": self.contact_weight,
            "collision_weight": self.collision_weight,
            "use_joint_limits": self.use_joint_limits,
            "damping": self.damping,
            "verbose": self.verbose,
        }


@dataclass
class InteractionPlan:
    """A solver-ready bundle of actors and constraints."""

    actors: list[str]
    constraints: list[PoseTarget | ContactTarget | LookAtTarget | BalanceTarget]
    options: SolveOptions = field(default_factory=SolveOptions)
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        def _constraint_to_dict(constraint: object) -> dict:
            data = dict(constraint.__dict__)
            data["kind"] = type(constraint).__name__
            return data

        return {
            "actors": list(self.actors),
            "constraints": [_constraint_to_dict(c) for c in self.constraints],
            "options": self.options.to_dict(),
            "metadata": dict(self.metadata),
        }

    def validate(self, rig_profiles: dict[str, FigureRigProfile]) -> list["ValidationIssue"]:
        """Validate the plan against known rig profiles.

        This does not solve anything yet. It only checks that each referenced
        figure and bone exists so the eventual solver can fail early with
        actionable diagnostics.
        """

        issues: list[ValidationIssue] = []

        for actor in self.actors:
            if actor not in rig_profiles:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        figure_label=actor,
                        constraint_index=-1,
                        message=f"No rig profile supplied for actor {actor!r}",
                    )
                )

        for index, constraint in enumerate(self.constraints):
            if isinstance(constraint, PoseTarget):
                profile = rig_profiles.get(constraint.figure_label)
                if profile is None:
                    issues.append(
                        ValidationIssue("error", constraint.figure_label, index, f"Unknown figure {constraint.figure_label!r}")
                    )
                    continue
                if constraint.bone_name not in profile.bone_names():
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            figure_label=constraint.figure_label,
                            constraint_index=index,
                            message=f"Unknown bone {constraint.bone_name!r} on figure {constraint.figure_label!r}",
                        )
                    )
            elif isinstance(constraint, ContactTarget):
                profile = rig_profiles.get(constraint.source_figure)
                if profile is None:
                    issues.append(
                        ValidationIssue("error", constraint.source_figure, index, f"Unknown source figure {constraint.source_figure!r}")
                    )
                    continue
                if constraint.source_bone not in profile.bone_names():
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            figure_label=constraint.source_figure,
                            constraint_index=index,
                            message=f"Unknown source bone {constraint.source_bone!r} on figure {constraint.source_figure!r}",
                        )
                    )
                if constraint.target_figure is not None and constraint.target_bone is not None:
                    target_profile = rig_profiles.get(constraint.target_figure)
                    if target_profile is None:
                        issues.append(
                            ValidationIssue(
                                severity="error",
                                figure_label=constraint.target_figure,
                                constraint_index=index,
                                message=f"Unknown target figure {constraint.target_figure!r}",
                            )
                        )
                    elif constraint.target_bone not in target_profile.bone_names():
                        issues.append(
                            ValidationIssue(
                                severity="error",
                                figure_label=constraint.target_figure,
                                constraint_index=index,
                                message=f"Unknown target bone {constraint.target_bone!r} on figure {constraint.target_figure!r}",
                            )
                        )
            elif isinstance(constraint, LookAtTarget):
                profile = rig_profiles.get(constraint.figure_label)
                if profile is None:
                    issues.append(
                        ValidationIssue("error", constraint.figure_label, index, f"Unknown figure {constraint.figure_label!r}")
                    )
                    continue
                if constraint.bone_name not in profile.bone_names():
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            figure_label=constraint.figure_label,
                            constraint_index=index,
                            message=f"Unknown look-at bone {constraint.bone_name!r} on figure {constraint.figure_label!r}",
                        )
                    )
            elif isinstance(constraint, BalanceTarget):
                profile = rig_profiles.get(constraint.figure_label)
                if profile is None:
                    issues.append(
                        ValidationIssue("error", constraint.figure_label, index, f"Unknown figure {constraint.figure_label!r}")
                    )
                    continue
                if constraint.pelvis_bone not in profile.bone_names():
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            figure_label=constraint.figure_label,
                            constraint_index=index,
                            message=f"Unknown pelvis bone {constraint.pelvis_bone!r} on figure {constraint.figure_label!r}",
                        )
                    )

        return issues


@dataclass
class SolveResult:
    """Result of a completed interaction solve."""

    success: bool
    pose_by_figure: dict[str, dict[str, Rotation3]] = field(default_factory=dict)
    morphs_by_figure: dict[str, dict[str, float]] = field(default_factory=dict)
    diagnostics: dict[str, object] = field(default_factory=dict)
    message: str = ""

    def apply(self, skeleton: "DazSkeleton", figure_label: str | None = None) -> None:
        """Apply the solved rotations to a live DAZ skeleton."""
        label = figure_label or getattr(skeleton, "label", None) or getattr(skeleton, "_identifier", None)
        key = getattr(label, "value", label)
        if key is None:
            raise ValueError("Could not determine figure label for SolveResult.apply()")
        rotations = self.pose_by_figure.get(str(key))
        if not rotations:
            return
        skeleton.set_bone_rotations(rotations)


@dataclass(frozen=True)
class ValidationIssue:
    """A problem found while validating an interaction plan."""

    severity: Literal["error", "warning"]
    figure_label: str | None
    constraint_index: int
    message: str

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "figure_label": self.figure_label,
            "constraint_index": self.constraint_index,
            "message": self.message,
        }


def default_axis_limits_for_bone(name: str, family: str = "generic") -> dict[AxisName, AxisLimit]:
    """Return loose, solver-friendly axis limits for a given bone name.

    These are intentionally conservative defaults. They are meant as a
    starting point for the solver layer, not as a claim about the full DAZ
    rigging limits for every installed asset.
    """

    key = _normalize_name(name)
    limits: dict[AxisName, AxisLimit] = {}
    presets: list[tuple[tuple[str, ...], dict[AxisName, tuple[float, float]]]] = [
        (("head", "neck"), {"x": (-70.0, 70.0), "y": (-85.0, 85.0), "z": (-45.0, 45.0)}),
        (("shoulder", "clavicle", "upper_arm"), {"x": (-120.0, 120.0), "y": (-120.0, 120.0), "z": (-140.0, 140.0)}),
        (("forearm", "hand"), {"x": (-160.0, 160.0), "y": (-120.0, 120.0), "z": (-160.0, 160.0)}),
        (("thigh", "shin", "calf"), {"x": (-140.0, 140.0), "y": (-80.0, 80.0), "z": (-140.0, 140.0)}),
        (("foot", "toe"), {"x": (-70.0, 70.0), "y": (-45.0, 45.0), "z": (-70.0, 70.0)}),
        (("spine", "abdomen", "chest", "hip", "pelvis"), {"x": (-45.0, 45.0), "y": (-45.0, 45.0), "z": (-45.0, 45.0)}),
    ]
    for tokens, ranges in presets:
        if any(token in key for token in tokens):
            for axis, (min_deg, max_deg) in ranges.items():
                limits[axis] = AxisLimit(axis=axis, min_degrees=min_deg, max_degrees=max_deg)
            break
    return limits


def _vec3_from_point(point: Vector3 | None) -> Vec3 | None:
    if point is None:
        return None
    return Vec3(float(point[0]), float(point[1]), float(point[2]))


def _point_from_dict(value: dict | None) -> Vector3 | None:
    if not value:
        return None
    try:
        return (float(value["x"]), float(value["y"]), float(value["z"]))
    except Exception:
        return None


def _coerce_target_point(
    scene: object,
    rig_profiles: dict[str, FigureRigProfile],
    constraint: PoseTarget | ContactTarget | LookAtTarget | BalanceTarget,
) -> tuple[Vector3 | None, str | None]:
    if isinstance(constraint, PoseTarget):
        return constraint.position, constraint.figure_label
    if isinstance(constraint, LookAtTarget):
        return constraint.target_point, constraint.figure_label
    if isinstance(constraint, BalanceTarget):
        if constraint.support_points:
            points = [Vec3(*pt) for pt in constraint.support_points]
            center = Vec3(
                sum(p.x for p in points) / len(points),
                sum(p.y for p in points) / len(points),
                sum(p.z for p in points) / len(points),
            )
            return (center.x, center.y, center.z), constraint.figure_label
        if constraint.center_of_mass_hint is not None:
            return constraint.center_of_mass_hint, constraint.figure_label
        return None, constraint.figure_label

    # Contact target
    if constraint.target_point is not None:
        return constraint.target_point, constraint.source_figure
    if constraint.target_figure and constraint.target_bone:
        target_skel = scene.find_skeleton_by_label(constraint.target_figure)
        target_bone = target_skel.find_bone(constraint.target_bone)
        return _point_from_dict(target_bone.position), constraint.source_figure
    return None, constraint.source_figure


def _solve_with_coordinate_descent(
    objective,
    x0: list[float],
    lower_bounds: list[float],
    upper_bounds: list[float],
    max_iterations: int,
) -> list[float]:
    x = list(x0)
    step = 10.0
    best = objective(x)
    for _ in range(max_iterations):
        improved = False
        for i in range(len(x)):
            current = x[i]
            candidates = [current, max(lower_bounds[i], min(upper_bounds[i], current + step)), max(lower_bounds[i], min(upper_bounds[i], current - step))]
            local_best = current
            local_score = best
            for candidate in candidates:
                trial = list(x)
                trial[i] = candidate
                score = objective(trial)
                if score < local_score:
                    local_score = score
                    local_best = candidate
            if local_best != current:
                x[i] = local_best
                best = local_score
                improved = True
        step *= 0.8
        if step < 0.1 or not improved:
            break
    return x


def _solve_position_target(
    skeleton: "DazSkeleton",
    profile: FigureRigProfile,
    chain: BoneChain,
    target_point: Vector3 | None,
    *,
    target_orientation: Rotation3 | None = None,
    options: SolveOptions | None = None,
) -> dict[str, Rotation3]:
    options = options or SolveOptions()
    if target_point is None:
        return {}

    bone_names = [name for name in chain.bones if name in profile.bone_names()]
    if not bone_names:
        return {}

    bones = [skeleton.find_bone(name) for name in bone_names]
    base_angles = [bone.local_euler or (0.0, 0.0, 0.0) for bone in bones]
    x0 = [angle for angles in base_angles for angle in angles]
    lower_bounds: list[float] = []
    upper_bounds: list[float] = []
    for name in bone_names:
        bone_profile = profile.bone(name)
        limits = bone_profile.axis_limits or default_axis_limits_for_bone(name, profile.family)
        for axis in ("x", "y", "z"):
            axis_limit = limits.get(axis)
            if axis_limit is None or not options.use_joint_limits:
                lower_bounds.append(-180.0)
                upper_bounds.append(180.0)
            else:
                lower_bounds.append(axis_limit.min_degrees)
                upper_bounds.append(axis_limit.max_degrees)

    target_vec = Vec3(*target_point)
    effector = bones[-1]

    def _apply_angles(flat_angles: list[float]) -> None:
        for index, bone in enumerate(bones):
            base = index * 3
            bone.set_local_rotation(flat_angles[base], flat_angles[base + 1], flat_angles[base + 2])

    def _residual_norm(flat_angles: list[float]) -> float:
        _apply_angles(flat_angles)
        pos = _point_from_dict(effector.position)
        if pos is None:
            return float("inf")
        current = Vec3(*pos)
        residual = current.distance(target_vec) * options.position_weight
        if target_orientation is not None:
            rotation_order = effector.rotation_order or "XYZ"
            current_q = Quat.from_dict(effector.rotation or {"x": 0, "y": 0, "z": 0, "w": 1})
            desired_q = Quat.from_euler(*target_orientation, order=rotation_order)
            delta = current_q.conjugate().multiply(desired_q)
            residual += math.sqrt(delta.x * delta.x + delta.y * delta.y + delta.z * delta.z) * options.orientation_weight
        for idx, value in enumerate(flat_angles):
            base_value = x0[idx]
            residual += abs(value - base_value) * options.rest_pose_weight * 0.01
            if options.use_joint_limits:
                if value < lower_bounds[idx]:
                    residual += (lower_bounds[idx] - value) * options.joint_limit_weight
                elif value > upper_bounds[idx]:
                    residual += (value - upper_bounds[idx]) * options.joint_limit_weight
        return residual

    final_angles = list(x0)
    try:
        from scipy.optimize import least_squares  # type: ignore

        result = least_squares(
            lambda flat: _residual_vector(flat, _apply_angles, effector, target_vec, x0, target_orientation, options, lower_bounds, upper_bounds),
            x0,
            bounds=(lower_bounds, upper_bounds),
            max_nfev=options.max_iterations,
        )
        final_angles = [float(v) for v in result.x]
    except Exception:
        final_angles = _solve_with_coordinate_descent(
            _residual_norm,
            x0,
            lower_bounds,
            upper_bounds,
            options.max_iterations,
        )

    _apply_angles(final_angles)
    return {
        bone.name or bone._identifier.value: tuple(bone.local_euler or (0.0, 0.0, 0.0))
        for bone in bones
    }


def _residual_vector(
    flat_angles: list[float],
    apply_angles,
    effector,
    target_vec: Vec3,
    x0: list[float],
    target_orientation: Rotation3 | None,
    options: SolveOptions,
    lower_bounds: list[float],
    upper_bounds: list[float],
) -> list[float]:
    apply_angles(list(flat_angles))
    pos = _point_from_dict(effector.position)
    if pos is None:
        return [1e6]
    current = Vec3(*pos)
    residuals = [
        (current.x - target_vec.x) * options.position_weight,
        (current.y - target_vec.y) * options.position_weight,
        (current.z - target_vec.z) * options.position_weight,
    ]
    if target_orientation is not None:
        rotation_order = effector.rotation_order or "XYZ"
        current_q = Quat.from_dict(effector.rotation or {"x": 0, "y": 0, "z": 0, "w": 1})
        desired_q = Quat.from_euler(*target_orientation, order=rotation_order)
        delta = current_q.conjugate().multiply(desired_q)
        residuals.extend([
            delta.x * options.orientation_weight,
            delta.y * options.orientation_weight,
            delta.z * options.orientation_weight,
        ])
    for idx, value in enumerate(flat_angles):
        base_value = x0[idx]
        residuals.append((value - base_value) * options.rest_pose_weight * 0.01)
        if options.use_joint_limits:
            if value < lower_bounds[idx]:
                residuals.append((lower_bounds[idx] - value) * options.joint_limit_weight)
            elif value > upper_bounds[idx]:
                residuals.append((value - upper_bounds[idx]) * options.joint_limit_weight)
    return residuals


def solve_interaction_plan(
    scene: object,
    plan: InteractionPlan,
    rig_profiles: dict[str, FigureRigProfile] | None = None,
    *,
    options: SolveOptions | None = None,
) -> SolveResult:
    """Solve an interaction plan against a live DAZ scene.

    The current implementation solves position-based targets using either
    SciPy's bounded nonlinear least squares or a pure-Python fallback.
    """

    options = options or plan.options
    if rig_profiles is None:
        rig_profiles = {
            skeleton.label or skeleton._identifier.value: build_rig_profile(skeleton)
            for skeleton in scene.skeletons()
        }

    validation_issues = plan.validate(rig_profiles)
    error_issues = [issue for issue in validation_issues if issue.severity == "error"]
    if error_issues:
        return SolveResult(
            success=False,
            diagnostics={"validation_issues": [issue.to_dict() for issue in validation_issues]},
            message="Plan validation failed",
        )

    figure_rotations: dict[str, dict[str, Rotation3]] = {
        label: {} for label in rig_profiles
    }
    diagnostics = {"validation_issues": [issue.to_dict() for issue in validation_issues], "steps": []}

    for constraint in plan.constraints:
        target_point, figure_label = _coerce_target_point(scene, rig_profiles, constraint)
        if figure_label is None:
            continue

        profile = rig_profiles.get(figure_label)
        if profile is None:
            continue

        skeleton = scene.find_skeleton_by_label(figure_label)
        if isinstance(constraint, BalanceTarget):
            if target_point is not None:
                center = Vec3(*target_point)
                skeleton.set_position(center.x, center.y, center.z)
                diagnostics["steps"].append({"kind": "balance", "figure": figure_label, "target": list(target_point)})
            continue

        if isinstance(constraint, ContactTarget) and constraint.target_figure and constraint.target_bone:
            chain = profile.suggest_primary_chain(constraint.source_bone)
            if chain is None:
                continue
            target_skel = scene.find_skeleton_by_label(constraint.target_figure)
            target_bone = target_skel.find_bone(constraint.target_bone)
            target_point = _point_from_dict(target_bone.position)
            if target_point is None:
                continue
            solved = _solve_position_target(
                skeleton,
                profile,
                chain,
                target_point,
                options=options,
            )
            figure_rotations[figure_label].update(solved)
            diagnostics["steps"].append({"kind": "contact", "figure": figure_label, "bone": constraint.source_bone, "target": list(target_point)})
            continue

        if isinstance(constraint, PoseTarget) or isinstance(constraint, LookAtTarget) or isinstance(constraint, ContactTarget):
            bone_name = constraint.bone_name if isinstance(constraint, (PoseTarget, LookAtTarget)) else constraint.source_bone
            chain = profile.suggest_primary_chain(bone_name) or profile.chain_for(bone_name, role="custom")
            orientation = constraint.orientation if isinstance(constraint, PoseTarget) else None
            if target_point is None:
                continue
            solved = _solve_position_target(
                skeleton,
                profile,
                chain,
                target_point,
                target_orientation=orientation,
                options=options,
            )
            figure_rotations[figure_label].update(solved)
            diagnostics["steps"].append({"kind": type(constraint).__name__, "figure": figure_label, "bone": bone_name, "target": list(target_point)})

    for label, skeleton_rotations in figure_rotations.items():
        if skeleton_rotations:
            skeleton = scene.find_skeleton_by_label(label)
            skeleton.set_bone_rotations(skeleton_rotations)

    return SolveResult(
        success=True,
        pose_by_figure=figure_rotations,
        diagnostics=diagnostics,
        message="Solved interaction plan",
    )


def build_rig_profile(skeleton: "DazSkeleton") -> FigureRigProfile:
    """Inspect a live DAZ skeleton and build a solver-friendly rig profile."""

    figure_label = skeleton.label or skeleton._identifier.value
    bones: list[BoneProfile] = []
    for bone in skeleton.bones():
        parent = bone.parent
        bones.append(
            BoneProfile(
                name=bone.name or bone._identifier.value,
                label=bone.label,
                parent_name=getattr(parent, "name", None) if parent else None,
                rotation_order=bone.rotation_order,
                local_position=_as_tuple3(bone.local_position),
                rest_rotation=_as_tuple3(bone.local_euler),
                axis_limits=default_axis_limits_for_bone(bone.name or bone._identifier.value),
                is_twist=_looks_like_twist(bone.name or bone._identifier.value, bone.label),
                is_helper=_looks_like_helper(bone.name or bone._identifier.value, bone.label),
            )
        )

    family = _detect_figure_family([bone.name for bone in bones])
    return FigureRigProfile(
        figure_label=figure_label or "",
        family=family,
        bones=bones,
        metadata={"bone_count": len(bones), "source": "dazpy"},
    )
