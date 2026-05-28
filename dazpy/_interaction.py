from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ._skeleton import DazSkeleton


Rotation3 = tuple[float, float, float]
Vector3 = tuple[float, float, float]
AxisName = Literal["x", "y", "z"]
ChainSide = Literal["left", "right", "center", "unknown"]
ChainRole = Literal["arm", "leg", "spine", "neck", "head", "hand", "foot", "pelvis", "custom"]
AnchorRole = Literal[
    "pelvis",
    "spine",
    "chest",
    "neck",
    "head",
    "shoulder",
    "elbow",
    "hand",
    "knee",
    "foot",
    "custom",
]
InteractionKind = Literal["PoseTarget", "ContactTarget", "LookAtTarget", "BalanceTarget", "HandTarget", "FootTarget"]


def _normalize_name(value: str | None) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def _lower_name(value: str | None) -> str:
    return (value or "").strip().lower()


def _as_tuple3(value: object | None) -> Rotation3 | None:
    if value is None:
        return None
    if isinstance(value, tuple) and len(value) == 3:
        return (float(value[0]), float(value[1]), float(value[2]))
    if isinstance(value, list) and len(value) == 3:
        return (float(value[0]), float(value[1]), float(value[2]))
    return None


def _add_vec3(a: Vector3 | None, b: Vector3 | None) -> Vector3 | None:
    if a is None:
        return b
    if b is None:
        return a
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _detect_figure_family(bone_names: list[str]) -> str:
    names = {_lower_name(name) for name in bone_names}
    if any(name.startswith(("r_", "l_")) for name in names):
        if any("forearm" in name for name in names) or any(name.endswith("_twist") for name in names) or any("_hand" in name for name in names) or any("_foot" in name for name in names):
            return "genesis_9"
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
    if lowered.startswith(("center_", "c_", "spine", "pelvis", "hip", "head", "neck", "chest")):
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
class BoneProfile:
    """Metadata for a single figure bone.

    This captures the bone relationship and the DAZ-specific control data we
    need before we can solve interaction posing reliably.
    """

    name: str
    label: str | None = None
    parent_name: str | None = None
    rotation_order: str | None = None
    local_position: Vector3 | None = None
    rest_rotation: Rotation3 | None = None
    axis_limits: dict[AxisName, AxisLimit] = field(default_factory=dict)
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


@dataclass(frozen=True)
class InteractionAnchor:
    """A canonical anchor on a figure used for interaction planning."""

    name: str
    bone_name: str
    role: AnchorRole
    side: ChainSide = "unknown"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "bone_name": self.bone_name,
            "role": self.role,
            "side": self.side,
        }


@dataclass(frozen=True)
class ResolvedInteractionTarget:
    """A fully resolved anchor target ready for solver consumption."""

    figure_label: str
    anchor_name: str
    bone_name: str
    target_point: Vector3 | None = None
    target_figure: str | None = None
    target_anchor: str | None = None
    target_bone: str | None = None
    offset: Vector3 = (0.0, 0.0, 0.0)

    def to_dict(self) -> dict:
        return {
            "figure_label": self.figure_label,
            "anchor_name": self.anchor_name,
            "bone_name": self.bone_name,
            "target_point": list(self.target_point) if self.target_point else None,
            "target_figure": self.target_figure,
            "target_anchor": self.target_anchor,
            "target_bone": self.target_bone,
            "offset": list(self.offset),
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
        return BoneChain(
            figure_label=self.figure_label,
            role=role,
            side=side,
            bones=self.chain_to(bone_name),
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
                if _match_any(bone.name, tokens) and _side_matches(bone.name, side):
                    return bone
        return None

    def chain_suggestions(self) -> list[BoneChain]:
        """Return solver-friendly chain suggestions for the major interaction lanes."""

        suggestions: list[BoneChain] = []
        candidates: list[tuple[str, ChainRole, ChainSide, tuple[str, ...]]] = [
            ("pelvis", "pelvis", "center", ("pelvis", "hip")),
            ("spine", "spine", "center", ("spine", "abdomen", "torso")),
            ("head", "head", "center", ("head",)),
            ("neck", "neck", "center", ("neck",)),
            ("l_hand", "hand", "left", ("hand",)),
            ("r_hand", "hand", "right", ("hand",)),
            ("l_foot", "foot", "left", ("foot", "toe")),
            ("r_foot", "foot", "right", ("foot", "toe")),
            ("l_shoulder", "arm", "left", ("shoulder", "clavicle", "upper_arm")),
            ("r_shoulder", "arm", "right", ("shoulder", "clavicle", "upper_arm")),
            ("l_thigh", "leg", "left", ("thigh", "upper_leg")),
            ("r_thigh", "leg", "right", ("thigh", "upper_leg")),
        ]
        for anchor_name, role, side, tokens in candidates:
            terminal = self._find_terminal_bone([(role, side, tokens)])
            if terminal is None:
                continue
            suggestions.append(self.chain_for(terminal.name, role=role, side=side))
        return suggestions

    def suggest_primary_chain(self, bone_name: str) -> BoneChain | None:
        """Return a solver chain for a specific effector bone."""

        if bone_name not in self._index:
            return None
        bone = self.bone(bone_name)
        side = _side_from_name(bone.name)
        lowered = _normalize_name(bone.name)
        if "hand" in lowered or lowered.endswith("wrist"):
            role: ChainRole = "hand"
        elif "foot" in lowered or "toe" in lowered:
            role = "foot"
        elif "head" in lowered:
            role = "head"
        elif "neck" in lowered:
            role = "neck"
        elif "thigh" in lowered or "leg" in lowered or "shin" in lowered or "calf" in lowered:
            role = "leg"
        elif "shoulder" in lowered or "clavicle" in lowered or "arm" in lowered or "forearm" in lowered or "elbow" in lowered:
            role = "arm"
        elif any(token in lowered for token in ("spine", "abdomen", "torso", "chest", "pelvis", "hip")):
            role = "spine" if "spine" in lowered or "abdomen" in lowered or "torso" in lowered or "chest" in lowered else "pelvis"
        else:
            role = "custom"
        return self.chain_for(bone_name, role=role, side=side)

    def anchor_map(self) -> dict[str, InteractionAnchor]:
        """Return the canonical interaction anchors for the figure.

        The returned map is intentionally opinionated: it prefers the bones
        that usually make the most sense for seating, touch, kisses, and
        punches/kicks.  It is designed to be a stable adapter layer for later
        solver work.
        """

        anchors: dict[str, InteractionAnchor] = {}
        patterns: list[tuple[str, AnchorRole, ChainSide, tuple[str, ...]]] = [
            ("pelvis", "pelvis", "center", ("pelvis", "hip")),
            ("spine", "spine", "center", ("spine", "abdomen", "torso")),
            ("chest", "chest", "center", ("chest", "upperchest", "thorax")),
            ("neck", "neck", "center", ("neck",)),
            ("head", "head", "center", ("head",)),
            ("l_shoulder", "shoulder", "left", ("shoulder", "clavicle")),
            ("r_shoulder", "shoulder", "right", ("shoulder", "clavicle")),
            ("l_elbow", "elbow", "left", ("elbow", "forearm")),
            ("r_elbow", "elbow", "right", ("elbow", "forearm")),
            ("l_hand", "hand", "left", ("hand", "wrist")),
            ("r_hand", "hand", "right", ("hand", "wrist")),
            ("l_knee", "knee", "left", ("knee", "thigh")),
            ("r_knee", "knee", "right", ("knee", "thigh")),
            ("l_foot", "foot", "left", ("foot", "toe", "ankle")),
            ("r_foot", "foot", "right", ("foot", "toe", "ankle")),
        ]
        for key, role, side, tokens in patterns:
            bone = self._find_terminal_bone([(role if role != "custom" else "custom", side, tokens)])
            if bone is None:
                continue
            anchors[key] = InteractionAnchor(name=key, bone_name=bone.name, role=role, side=side)
        return anchors

    def anchor(self, name: str) -> InteractionAnchor | None:
        return self.anchor_map().get(name)

    def anchor_names(self) -> list[str]:
        return sorted(self.anchor_map().keys())

    def require_anchor(self, name: str) -> InteractionAnchor:
        anchor = self.anchor(name)
        if anchor is None:
            raise KeyError(f"Anchor not found in rig profile: {name!r}")
        return anchor

    def resolve_anchor_target(
        self,
        target: AnchorTarget,
        rig_profiles: dict[str, "FigureRigProfile"] | None = None,
    ) -> ResolvedInteractionTarget:
        """Resolve an anchor target into concrete bones and an optional point."""

        anchor = self.require_anchor(target.anchor_name)
        target_point = target.target_point
        target_figure = target.target_figure
        target_anchor = target.target_anchor
        target_bone = None

        if target_figure and target_anchor and rig_profiles is not None:
            target_profile = rig_profiles.get(target_figure)
            if target_profile is not None:
                resolved = target_profile.require_anchor(target_anchor)
                target_bone = resolved.bone_name
        if target_point is None and target_figure is not None and target_anchor is not None and rig_profiles is not None:
            target_profile = rig_profiles.get(target_figure)
            if target_profile is not None:
                target_point = _anchor_world_point_hint(target_profile, target_anchor)

        target_point = _add_vec3(target_point, target.offset)

        return ResolvedInteractionTarget(
            figure_label=self.figure_label,
            anchor_name=anchor.name,
            bone_name=anchor.bone_name,
            target_point=target_point,
            target_figure=target_figure,
            target_anchor=target_anchor,
            target_bone=target_bone,
            offset=target.offset,
        )

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


@dataclass(frozen=True)
class PoseTarget:
    """Move a figure bone toward a specific position/orientation target."""

    figure_label: str
    bone_name: str
    position: Vector3 | None = None
    orientation: Rotation3 | None = None

    def to_dict(self) -> dict:
        return {
            "kind": "PoseTarget",
            "figure_label": self.figure_label,
            "bone_name": self.bone_name,
            "position": list(self.position) if self.position else None,
            "orientation": list(self.orientation) if self.orientation else None,
        }


@dataclass(frozen=True)
class AnchorTarget:
    """Target a canonical interaction anchor on a figure.

    This is the bridge between high-level interaction authoring and the
    actual DAZ bones used by the rig.  Hand and foot goals use this shape.
    """

    figure_label: str
    anchor_name: str
    target_figure: str | None = None
    target_anchor: str | None = None
    target_point: Vector3 | None = None
    offset: Vector3 = (0.0, 0.0, 0.0)

    def to_dict(self) -> dict:
        return {
            "kind": type(self).__name__,
            "figure_label": self.figure_label,
            "anchor_name": self.anchor_name,
            "target_figure": self.target_figure,
            "target_anchor": self.target_anchor,
            "target_point": list(self.target_point) if self.target_point else None,
            "offset": list(self.offset),
        }


@dataclass(frozen=True)
class HandTarget(AnchorTarget):
    """Place a hand anchor against another anchor or world point."""


@dataclass(frozen=True)
class FootTarget(AnchorTarget):
    """Place a foot anchor against another anchor, world point, or floor."""


@dataclass(frozen=True)
class ContactTarget:
    """Keep one figure bone in contact with a target figure or world point."""

    source_figure: str
    source_bone: str
    target_figure: str | None = None
    target_bone: str | None = None
    target_point: Vector3 | None = None

    def to_dict(self) -> dict:
        return {
            "kind": "ContactTarget",
            "source_figure": self.source_figure,
            "source_bone": self.source_bone,
            "target_figure": self.target_figure,
            "target_bone": self.target_bone,
            "target_point": list(self.target_point) if self.target_point else None,
        }


@dataclass(frozen=True)
class LookAtTarget:
    """Aim a bone toward a point in space."""

    figure_label: str
    bone_name: str
    target_point: Vector3

    def to_dict(self) -> dict:
        return {
            "kind": "LookAtTarget",
            "figure_label": self.figure_label,
            "bone_name": self.bone_name,
            "target_point": list(self.target_point),
        }


@dataclass(frozen=True)
class BalanceTarget:
    """Stabilize a figure around a support surface or center of mass hint."""

    figure_label: str
    pelvis_bone: str
    support_points: list[Vector3] = field(default_factory=list)
    center_of_mass_hint: Vector3 | None = None

    def to_dict(self) -> dict:
        return {
            "kind": "BalanceTarget",
            "figure_label": self.figure_label,
            "pelvis_bone": self.pelvis_bone,
            "support_points": [list(point) for point in self.support_points],
            "center_of_mass_hint": list(self.center_of_mass_hint) if self.center_of_mass_hint else None,
        }


@dataclass
class SolveOptions:
    """Tunable options for later solver phases."""

    backend: Literal["scipy", "pinocchio", "ikpy", "auto"] = "auto"
    max_iterations: int = 100
    use_joint_limits: bool = True
    rest_pose_weight: float = 0.15
    contact_weight: float = 1.0
    position_weight: float = 1.0
    orientation_weight: float = 0.25

    def to_dict(self) -> dict:
        return {
            "backend": self.backend,
            "max_iterations": self.max_iterations,
            "use_joint_limits": self.use_joint_limits,
            "rest_pose_weight": self.rest_pose_weight,
            "contact_weight": self.contact_weight,
            "position_weight": self.position_weight,
            "orientation_weight": self.orientation_weight,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SolveOptions":
        return cls(
            backend=data.get("backend", "auto"),
            max_iterations=int(data.get("max_iterations", 100)),
            use_joint_limits=bool(data.get("use_joint_limits", True)),
            rest_pose_weight=float(data.get("rest_pose_weight", 0.15)),
            contact_weight=float(data.get("contact_weight", 1.0)),
            position_weight=float(data.get("position_weight", 1.0)),
            orientation_weight=float(data.get("orientation_weight", 0.25)),
        )


@dataclass
class InteractionPlan:
    """A collection of interaction constraints across one or more figures."""

    actors: list[str]
    constraints: list[PoseTarget | ContactTarget | LookAtTarget | BalanceTarget | HandTarget | FootTarget] = field(default_factory=list)
    options: SolveOptions = field(default_factory=SolveOptions)
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "actors": list(self.actors),
            "constraints": [constraint.to_dict() for constraint in self.constraints],
            "options": self.options.to_dict(),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "InteractionPlan":
        constraints: list[PoseTarget | ContactTarget | LookAtTarget | BalanceTarget] = []
        for item in data.get("constraints", []):
            kind = item.get("kind")
            if kind == "PoseTarget":
                constraints.append(
                    PoseTarget(
                        figure_label=item.get("figure_label", ""),
                        bone_name=item.get("bone_name", ""),
                        position=_as_tuple3(item.get("position")),
                        orientation=_as_tuple3(item.get("orientation")),
                    )
                )
            elif kind == "HandTarget":
                constraints.append(
                    HandTarget(
                        figure_label=item.get("figure_label", ""),
                        anchor_name=item.get("anchor_name", ""),
                        target_figure=item.get("target_figure"),
                        target_anchor=item.get("target_anchor"),
                        target_point=_as_tuple3(item.get("target_point")),
                        offset=_as_tuple3(item.get("offset")) or (0.0, 0.0, 0.0),
                    )
                )
            elif kind == "FootTarget":
                constraints.append(
                    FootTarget(
                        figure_label=item.get("figure_label", ""),
                        anchor_name=item.get("anchor_name", ""),
                        target_figure=item.get("target_figure"),
                        target_anchor=item.get("target_anchor"),
                        target_point=_as_tuple3(item.get("target_point")),
                        offset=_as_tuple3(item.get("offset")) or (0.0, 0.0, 0.0),
                    )
                )
            elif kind == "ContactTarget":
                constraints.append(
                    ContactTarget(
                        source_figure=item.get("source_figure", ""),
                        source_bone=item.get("source_bone", ""),
                        target_figure=item.get("target_figure"),
                        target_bone=item.get("target_bone"),
                        target_point=_as_tuple3(item.get("target_point")),
                    )
                )
            elif kind == "LookAtTarget":
                target_point = _as_tuple3(item.get("target_point"))
                if target_point is None:
                    continue
                constraints.append(
                    LookAtTarget(
                        figure_label=item.get("figure_label", ""),
                        bone_name=item.get("bone_name", ""),
                        target_point=target_point,
                    )
                )
            elif kind == "BalanceTarget":
                constraints.append(
                    BalanceTarget(
                        figure_label=item.get("figure_label", ""),
                        pelvis_bone=item.get("pelvis_bone", ""),
                        support_points=[tuple(point) for point in item.get("support_points", [])],
                        center_of_mass_hint=_as_tuple3(item.get("center_of_mass_hint")),
                    )
                )
        return cls(
            actors=list(data.get("actors", [])),
            constraints=constraints,
            options=SolveOptions.from_dict(data.get("options", {})),
            metadata=dict(data.get("metadata", {})),
        )

    def validate(self, rig_profiles: dict[str, FigureRigProfile]) -> list[ValidationIssue]:
        """Validate that all referenced figures and bones exist."""

        issues: list[ValidationIssue] = []
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
                        ValidationIssue("error", constraint.figure_label, index, f"Unknown bone {constraint.bone_name!r} on figure {constraint.figure_label!r}")
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
                        ValidationIssue("error", constraint.figure_label, index, f"Unknown bone {constraint.bone_name!r} on figure {constraint.figure_label!r}")
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
                        ValidationIssue("error", constraint.source_figure, index, f"Unknown source bone {constraint.source_bone!r} on figure {constraint.source_figure!r}")
                    )
                if constraint.target_figure and constraint.target_bone:
                    target_profile = rig_profiles.get(constraint.target_figure)
                    if target_profile is None:
                        issues.append(
                            ValidationIssue("error", constraint.target_figure, index, f"Unknown target figure {constraint.target_figure!r}")
                        )
                    elif constraint.target_bone not in target_profile.bone_names():
                        issues.append(
                            ValidationIssue("error", constraint.target_figure, index, f"Unknown target bone {constraint.target_bone!r} on figure {constraint.target_figure!r}")
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
                            ValidationIssue("error", constraint.figure_label, index, f"Unknown pelvis bone {constraint.pelvis_bone!r} on figure {constraint.figure_label!r}")
                        )
            elif isinstance(constraint, (HandTarget, FootTarget)):
                profile = rig_profiles.get(constraint.figure_label)
                if profile is None:
                    issues.append(
                        ValidationIssue("error", constraint.figure_label, index, f"Unknown figure {constraint.figure_label!r}")
                    )
                    continue
                if constraint.anchor_name not in profile.anchor_names():
                        issues.append(
                            ValidationIssue("error", constraint.figure_label, index, f"Unknown anchor {constraint.anchor_name!r} on figure {constraint.figure_label!r}")
                        )
                if constraint.target_figure and constraint.target_anchor:
                    target_profile = rig_profiles.get(constraint.target_figure)
                    if target_profile is None:
                        issues.append(
                            ValidationIssue("error", constraint.target_figure, index, f"Unknown target figure {constraint.target_figure!r}")
                        )
                    elif constraint.target_anchor not in target_profile.anchor_names():
                        issues.append(
                            ValidationIssue("error", constraint.target_figure, index, f"Unknown target anchor {constraint.target_anchor!r} on figure {constraint.target_figure!r}")
                        )
        return issues

    def resolve_targets(self, rig_profiles: dict[str, FigureRigProfile]) -> list[ResolvedInteractionTarget]:
        """Resolve hand and foot goals into concrete anchors and points."""

        resolved: list[ResolvedInteractionTarget] = []
        for constraint in self.constraints:
            if isinstance(constraint, (HandTarget, FootTarget)):
                profile = rig_profiles.get(constraint.figure_label)
                if profile is None:
                    continue
                resolved.append(resolve_interaction_target(constraint, rig_profiles))
        return resolved


def default_axis_limits_for_bone(name: str, family: str = "generic") -> dict[AxisName, AxisLimit]:
    """Return loose, solver-friendly axis limits for a given bone name."""

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


def _anchor_world_point_hint(profile: FigureRigProfile, anchor_name: str) -> Vector3 | None:
    """Return the best available point hint for an anchor.

    Until the solver is wired in, this uses the bone's local position metadata
    if available.  That gives us a stable, reproducible target shape for hands
    and feet without pretending we already have world-space evaluation.
    """

    anchor = profile.anchor(anchor_name)
    if anchor is None:
        return None
    bone = profile.bone(anchor.bone_name)
    if bone.local_position is not None:
        return bone.local_position
    return None


def resolve_interaction_target(
    target: AnchorTarget,
    rig_profiles: dict[str, FigureRigProfile],
) -> ResolvedInteractionTarget:
    """Resolve a hand/foot interaction target against the available rig profiles."""

    profile = rig_profiles.get(target.figure_label)
    if profile is None:
        raise KeyError(f"Unknown figure for target resolution: {target.figure_label!r}")
    return profile.resolve_anchor_target(target, rig_profiles)


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
