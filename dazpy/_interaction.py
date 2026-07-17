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
RecipeKind = Literal["sit", "touch", "kiss", "fight", "handshake", "hug", "face_each_other", "custom"]


def _normalize_name(value: str | None) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def _compact_name(value: str | None) -> str:
    text = (value or "").strip().lower()
    return re.sub(r"[\s_\-]+", "", text)


def _lower_name(value: str | None) -> str:
    return (value or "").strip().lower()


def _as_tuple3(value: object | None) -> Rotation3 | None:
    if value is None:
        return None
    if isinstance(value, dict) and {"x", "y", "z"}.issubset(value.keys()):
        return (float(value["x"]), float(value["y"]), float(value["z"]))
    if isinstance(value, tuple) and len(value) == 3:
        return (float(value[0]), float(value[1]), float(value[2]))
    if isinstance(value, list) and len(value) == 3:
        return (float(value[0]), float(value[1]), float(value[2]))
    return None


def _lookup_rig_profile(rig_profiles: dict[str, "FigureRigProfile"], label: str | None) -> "FigureRigProfile" | None:
    if label is None:
        return None
    if label in rig_profiles:
        return rig_profiles[label]
    compact = _compact_name(label)
    for key, profile in rig_profiles.items():
        if _compact_name(key) == compact:
            return profile
    return None


def _add_vec3(a: Vector3 | None, b: Vector3 | None) -> Vector3 | None:
    if a is None:
        return b
    if b is None:
        return a
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub_vec3(a: Vector3, b: Vector3) -> Vector3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _midpoint_vec3(a: Vector3, b: Vector3) -> Vector3:
    return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0, (a[2] + b[2]) / 2.0)


def _average_vec3(points: list[Vector3] | None) -> Vector3 | None:
    if not points:
        return None
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
        sum(point[2] for point in points) / len(points),
    )


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
    if lowered.startswith(("l_", "left_")):
        return "left"
    if lowered.startswith(("r_", "right_")):
        return "right"
    # camelCase prefix: rHand, lFoot, rForearmBend (Genesis 3/8 naming)
    if len(name) > 1 and name[0] == "l" and name[1].isupper():
        return "left"
    if len(name) > 1 and name[0] == "r" and name[1].isupper():
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
    world_position: Vector3 | None = None
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
            "world_position": list(self.world_position) if self.world_position else None,
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
            world_position=_as_tuple3(data.get("world_position")),
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
            target_profile = _lookup_rig_profile(rig_profiles, target_figure)
            if target_profile is not None:
                resolved = target_profile.require_anchor(target_anchor)
                target_bone = resolved.bone_name
        if target_point is None and target_figure is not None and target_anchor is not None and rig_profiles is not None:
            target_profile = _lookup_rig_profile(rig_profiles, target_figure)
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
                profile = _lookup_rig_profile(rig_profiles, constraint.figure_label)
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
                profile = _lookup_rig_profile(rig_profiles, constraint.figure_label)
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
                profile = _lookup_rig_profile(rig_profiles, constraint.source_figure)
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
                    target_profile = _lookup_rig_profile(rig_profiles, constraint.target_figure)
                    if target_profile is None:
                        issues.append(
                            ValidationIssue("error", constraint.target_figure, index, f"Unknown target figure {constraint.target_figure!r}")
                        )
                    elif constraint.target_bone not in target_profile.bone_names():
                        issues.append(
                            ValidationIssue("error", constraint.target_figure, index, f"Unknown target bone {constraint.target_bone!r} on figure {constraint.target_figure!r}")
                        )
            elif isinstance(constraint, BalanceTarget):
                profile = _lookup_rig_profile(rig_profiles, constraint.figure_label)
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
                profile = _lookup_rig_profile(rig_profiles, constraint.figure_label)
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
                    target_profile = _lookup_rig_profile(rig_profiles, constraint.target_figure)
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
                profile = _lookup_rig_profile(rig_profiles, constraint.figure_label)
                if profile is None:
                    continue
                resolved.append(resolve_interaction_target(constraint, rig_profiles))
        return resolved


@dataclass
class InteractionRecipe:
    """A higher-level interaction preset that expands into an interaction plan."""

    kind: RecipeKind
    actors: list[str]
    constraints: list[PoseTarget | ContactTarget | LookAtTarget | BalanceTarget | HandTarget | FootTarget] = field(default_factory=list)
    options: SolveOptions = field(default_factory=SolveOptions)
    metadata: dict[str, object] = field(default_factory=dict)

    def to_plan(self) -> InteractionPlan:
        return InteractionPlan(
            actors=list(self.actors),
            constraints=list(self.constraints),
            options=self.options,
            metadata=dict(self.metadata),
        )

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "actors": list(self.actors),
            "constraints": [constraint.to_dict() for constraint in self.constraints],
            "options": self.options.to_dict(),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "InteractionRecipe":
        plan = InteractionPlan.from_dict(data)
        return cls(
            kind=data.get("kind", "custom"),
            actors=plan.actors,
            constraints=plan.constraints,
            options=plan.options,
            metadata=plan.metadata,
        )


@dataclass
class PreparedInteractionRecipe:
    """A compiled recipe ready for a live DAZ session or a future solver."""

    recipe: InteractionRecipe
    plan: InteractionPlan
    resolved_targets: list[ResolvedInteractionTarget] = field(default_factory=list)
    rig_profiles: dict[str, FigureRigProfile] = field(default_factory=dict)
    validation_issues: list[ValidationIssue] = field(default_factory=list)
    diagnostics: dict[str, object] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.validation_issues)

    def to_dict(self) -> dict:
        return {
            "recipe": self.recipe.to_dict(),
            "plan": self.plan.to_dict(),
            "resolved_targets": [target.to_dict() for target in self.resolved_targets],
            "rig_profiles": {label: profile.to_dict() for label, profile in self.rig_profiles.items()},
            "validation_issues": [issue.to_dict() for issue in self.validation_issues],
            "diagnostics": dict(self.diagnostics),
        }

    def build_pose_patch(self) -> "InteractionPosePatch":
        """Build a coarse live-placement patch from the prepared recipe.

        This is intentionally conservative: it only translates figures so their
        anchors are staged near their requested targets. It does not attempt to
        solve bone rotations yet.
        """

        figure_positions: dict[str, list[Vector3]] = {}
        unresolved: list[ResolvedInteractionTarget] = []

        def _append_position(label: str, point: Vector3) -> None:
            figure_positions.setdefault(label, []).append(point)

        def _first_local_anchor_position(profile: FigureRigProfile, anchor_name: str) -> Vector3 | None:
            anchor = profile.anchor(anchor_name)
            if anchor is None:
                return None
            bone = profile.bone(anchor.bone_name)
            return bone.local_position

        def _current_figure_position(label: str) -> Vector3 | None:
            return _average_vec3(figure_positions.get(label))

        for constraint in self.plan.constraints:
            if isinstance(constraint, BalanceTarget):
                profile = _lookup_rig_profile(self.rig_profiles, constraint.figure_label)
                if profile is None:
                    continue
                pelvis_anchor = profile.anchor(constraint.pelvis_bone)
                if pelvis_anchor is None:
                    unresolved.append(
                        ResolvedInteractionTarget(
                            figure_label=constraint.figure_label,
                            anchor_name=constraint.pelvis_bone,
                            bone_name=constraint.pelvis_bone,
                        )
                    )
                    continue
                pelvis_bone = profile.bone(pelvis_anchor.bone_name)
                target_point = constraint.center_of_mass_hint
                if target_point is None and constraint.support_points:
                    support = constraint.support_points
                    target_point = (
                        sum(point[0] for point in support) / len(support),
                        sum(point[1] for point in support) / len(support),
                        sum(point[2] for point in support) / len(support),
                    )
                if target_point is None or pelvis_bone.local_position is None:
                    unresolved.append(
                        ResolvedInteractionTarget(
                            figure_label=constraint.figure_label,
                            anchor_name=constraint.pelvis_bone,
                            bone_name=pelvis_anchor.bone_name,
                            target_point=target_point,
                        )
                    )
                    continue
                _append_position(
                    constraint.figure_label,
                    (
                        target_point[0] - pelvis_bone.local_position[0],
                        target_point[1] - pelvis_bone.local_position[1],
                        target_point[2] - pelvis_bone.local_position[2],
                    ),
                )

        for resolved in self.resolved_targets:
            profile = _lookup_rig_profile(self.rig_profiles, resolved.figure_label)
            if profile is None:
                unresolved.append(resolved)
                continue
            source_anchor = profile.anchor(resolved.anchor_name)
            if source_anchor is None:
                unresolved.append(resolved)
                continue
            source_bone = profile.bone(source_anchor.bone_name)
            if source_bone.local_position is None:
                unresolved.append(resolved)
                continue
            target_profile = _lookup_rig_profile(self.rig_profiles, resolved.target_figure) if resolved.target_figure else None
            target_local = _first_local_anchor_position(target_profile, resolved.target_anchor) if (target_profile and resolved.target_anchor) else None
            source_base = _current_figure_position(resolved.figure_label)
            target_base = _current_figure_position(resolved.target_figure) if resolved.target_figure else None

            if target_profile is not None and resolved.target_figure is not None:
                if target_base is not None and resolved.target_point is not None and source_base is None:
                    world_target = _add_vec3(target_base, resolved.target_point)
                    _append_position(resolved.figure_label, _sub_vec3(world_target, source_bone.local_position))
                    continue

                if target_local is not None:
                    if source_base is None and target_base is None:
                        contact_center = _midpoint_vec3(source_bone.local_position, target_local)
                        _append_position(resolved.figure_label, _sub_vec3(contact_center, source_bone.local_position))
                        _append_position(resolved.target_figure, _sub_vec3(contact_center, target_local))
                    elif source_base is None and target_base is not None:
                        target_world = _add_vec3(target_base, target_local)
                        _append_position(resolved.figure_label, _sub_vec3(target_world, source_bone.local_position))
                    elif source_base is not None and target_base is None:
                        source_world = _add_vec3(source_base, source_bone.local_position)
                        if source_world is not None:
                            _append_position(resolved.target_figure, _sub_vec3(source_world, target_local))
                    continue

            if resolved.target_point is None:
                unresolved.append(resolved)
                continue
            _append_position(
                resolved.figure_label,
                _sub_vec3(resolved.target_point, source_bone.local_position),
            )

        averaged_positions: dict[str, Vector3] = {}
        for label, points in figure_positions.items():
            averaged_positions[label] = (
                sum(point[0] for point in points) / len(points),
                sum(point[1] for point in points) / len(points),
                sum(point[2] for point in points) / len(points),
            )

        diagnostics = {
            "figure_count": len(averaged_positions),
            "unresolved_target_count": len(unresolved),
        }
        return InteractionPosePatch(
            figure_positions=averaged_positions,
            unresolved_targets=unresolved,
            diagnostics=diagnostics,
        )

    def apply(
        self,
        scene: object,
        *,
        align_limb_targets: bool = False,
        max_iterations: int | None = None,
        step_degrees: float = 1.0,
        damping: float = 0.25,
        tolerance: float = 0.15,
    ) -> "PreparedInteractionResult":
        """Apply the compiled recipe, optionally aligning a single limb chain."""

        patch = self.build_pose_patch()
        patch.apply(scene)
        result = PreparedInteractionResult(
            prepared=self,
            pose_patch=patch,
        )
        if align_limb_targets:
            result.alignment_results = self.align_limb_targets(
                scene,
                max_iterations=max_iterations,
                step_degrees=step_degrees,
                damping=damping,
                tolerance=tolerance,
            )
        return result

    def align_limb_targets(
        self,
        scene: object,
        *,
        max_iterations: int | None = None,
        step_degrees: float = 1.0,
        damping: float = 0.25,
        tolerance: float = 0.15,
    ) -> list["LimbAlignmentResult"]:
        """Apply live limb alignment for resolved hand and foot targets."""

        alignment_results: list[LimbAlignmentResult] = []
        for resolved in self.resolved_targets:
            if resolved.target_point is None:
                continue
            skeleton = scene.find_skeleton_by_label(resolved.figure_label)
            profile = _lookup_rig_profile(self.rig_profiles, resolved.figure_label)
            if profile is None:
                continue
            alignment_results.append(
                align_single_limb_target(
                    skeleton,
                    profile,
                    resolved,
                    max_iterations=max_iterations or self.plan.options.max_iterations,
                    step_degrees=step_degrees,
                    damping=damping,
                    tolerance=tolerance,
                )
            )
        return alignment_results


@dataclass
class InteractionPosePatch:
    """A coarse figure-placement patch built from a prepared interaction."""

    figure_positions: dict[str, Vector3] = field(default_factory=dict)
    unresolved_targets: list[ResolvedInteractionTarget] = field(default_factory=list)
    diagnostics: dict[str, object] = field(default_factory=dict)

    def apply(self, scene: object) -> None:
        for figure_label, position in self.figure_positions.items():
            skeleton = scene.find_skeleton_by_label(figure_label)
            skeleton.set_position(*position)

    def to_dict(self) -> dict:
        return {
            "figure_positions": {label: list(position) for label, position in self.figure_positions.items()},
            "unresolved_targets": [target.to_dict() for target in self.unresolved_targets],
            "diagnostics": dict(self.diagnostics),
        }


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


def _vec3_add(a: Vector3, b: Vector3) -> Vector3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _vec3_sub(a: Vector3, b: Vector3) -> Vector3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _vec3_scale(v: Vector3, scale: float) -> Vector3:
    return (v[0] * scale, v[1] * scale, v[2] * scale)


def _vec3_dot(a: Vector3, b: Vector3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _vec3_length(v: Vector3) -> float:
    return _vec3_dot(v, v) ** 0.5


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def _rotation_with_axis_limits(rotation: Rotation3, axis_limits: dict[AxisName, AxisLimit] | None) -> Rotation3:
    if not axis_limits:
        return rotation
    values = [rotation[0], rotation[1], rotation[2]]
    for index, axis in enumerate(("x", "y", "z")):
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


def _alignment_chain_names(profile: FigureRigProfile, chain: BoneChain) -> list[str]:
    candidates = [name for name in chain.bones if name in profile.bone_names()]
    candidates = [name for name in candidates if not profile.bone(name).is_helper]
    if len(candidates) <= 1:
        return candidates
    role_limits: dict[ChainRole, int] = {
        "hand": 4,
        "arm": 4,
        "foot": 4,
        "leg": 4,
        "head": 2,
        "neck": 2,
        "spine": 3,
        "pelvis": 2,
        "custom": 3,
    }
    limit = role_limits.get(chain.role, 3)
    return candidates[:-1][-limit:]


def _align_single_limb_batch(
    skeleton: "DazSkeleton",
    profile: FigureRigProfile,
    chain_names: list[str],
    target: ResolvedInteractionTarget,
    *,
    max_iterations: int = 12,
    step_degrees: float = 1.0,
    damping: float = 0.25,
    tolerance: float = 0.15,
) -> "LimbAlignmentResult":
    """Batch IK path: 2 HTTP calls per iteration via evaluate_pose_jacobian."""

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

    initial_error = _vec3_length(_vec3_sub(target.target_point, base_position))
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
        current_error = _vec3_sub(target.target_point, base_position)
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

        skeleton.set_bone_rotations(new_rotations)

        jac = skeleton.evaluate_pose_jacobian(chain_names, target.bone_name, step_degrees)
        if jac is None:
            break
        base_position = tuple(jac["base_position"])  # type: ignore[assignment]
        columns = [tuple(c) for c in jac["columns"]]  # type: ignore[misc]
        final_position = base_position

    final_error = _vec3_length(_vec3_sub(target.target_point, final_position))
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
    skeleton: "DazSkeleton",
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
            applied_rotations={bone.name: _as_tuple3(getattr(bone, "local_euler", None)) or (0.0, 0.0, 0.0) for bone in bones},
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
        for bone in bones:
            current_rotation = _as_tuple3(getattr(bone, "local_euler", None)) or (0.0, 0.0, 0.0)
            original_rotations[bone.name] = current_rotation
            profile_bone = profile.bone(bone.name)
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

        for bone_index, bone in enumerate(bones):
            current_rotation = original_rotations[bone.name]
            start = bone_index * 3
            next_rotation = (
                current_rotation[0] + delta[start],
                current_rotation[1] + delta[start + 1],
                current_rotation[2] + delta[start + 2],
            )
            profile_bone = profile.bone(bone.name)
            bone.set_local_rotation(*_rotation_with_axis_limits(next_rotation, profile_bone.axis_limits if profile_bone.axis_limits else None))

    final_position = _bone_world_position(effector)
    final_error = _vec3_length(_vec3_sub(target.target_point, final_position)) if final_position is not None else None
    applied_rotations = {
        bone.name: _as_tuple3(getattr(bone, "local_euler", None)) or (0.0, 0.0, 0.0)
        for bone in bones
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
    skeleton: "DazSkeleton",
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
    skeleton: "DazSkeleton",
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


@dataclass
class PreparedInteractionResult:
    """The result of applying a prepared recipe as a live staging pass."""

    prepared: PreparedInteractionRecipe
    pose_patch: InteractionPosePatch
    alignment_results: list[LimbAlignmentResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "prepared": self.prepared.to_dict(),
            "pose_patch": self.pose_patch.to_dict(),
            "alignment_results": [result.to_dict() for result in self.alignment_results],
        }


def prepare_interaction_recipe(
    recipe: InteractionRecipe,
    rig_profiles: dict[str, FigureRigProfile],
) -> PreparedInteractionRecipe:
    """Compile a recipe into a validated, resolved planning object.

    This is the next step toward a live-facing interaction system: it doesn't
    solve the pose yet, but it does normalize the recipe into concrete targets
    that a DAZ session or future solver can consume directly.
    """

    plan = recipe.to_plan()
    validation_issues = plan.validate(rig_profiles)
    resolved_targets = plan.resolve_targets(rig_profiles)
    diagnostics = {
        "recipe_kind": recipe.kind,
        "actor_count": len(recipe.actors),
        "constraint_count": len(recipe.constraints),
        "resolved_target_count": len(resolved_targets),
    }
    return PreparedInteractionRecipe(
        recipe=recipe,
        plan=plan,
        resolved_targets=resolved_targets,
        rig_profiles=dict(rig_profiles),
        validation_issues=validation_issues,
        diagnostics=diagnostics,
    )


def apply_interaction_recipe_to_scene(
    scene: object,
    recipe: InteractionRecipe,
    *,
    rig_profiles: dict[str, FigureRigProfile] | None = None,
    align_limb_targets: bool = False,
    max_iterations: int | None = None,
    step_degrees: float = 1.0,
    damping: float = 0.25,
    tolerance: float = 0.15,
) -> PreparedInteractionResult:
    """Prepare and apply an interaction recipe against a live scene object."""

    if rig_profiles is None:
        if not hasattr(scene, "skeletons"):
            raise TypeError("apply_interaction_recipe_to_scene expects a scene-like object")
        if hasattr(scene, "scene_snapshot") and hasattr(scene, "_client"):
            rig_profiles = build_rig_profiles_from_snapshot(scene.scene_snapshot())
        else:
            rig_profiles = {}
            for skeleton in scene.skeletons():
                profile = build_rig_profile(skeleton)
                rig_profiles[profile.figure_label] = profile
                if skeleton._identifier.value and skeleton._identifier.value != profile.figure_label:
                    rig_profiles[skeleton._identifier.value] = profile
    prepared = prepare_interaction_recipe(recipe, rig_profiles)
    return prepared.apply(
        scene,
        align_limb_targets=align_limb_targets,
        max_iterations=max_iterations,
        step_degrees=step_degrees,
        damping=damping,
        tolerance=tolerance,
    )


def _target_anchor_from_strike_anchor(anchor_name: str) -> str:
    lowered = _normalize_name(anchor_name)
    if "hand" in lowered:
        return "l_shoulder"
    if "foot" in lowered:
        return "l_hip"
    return "chest"


def build_sit_recipe(
    actor_label: str,
    *,
    seat_point: Vector3 | None = None,
    support_points: list[Vector3] | None = None,
    foot_anchors: tuple[str, str] = ("l_foot", "r_foot"),
) -> InteractionRecipe:
    """Build a seat/lean preset for a single character."""

    constraints: list[PoseTarget | ContactTarget | LookAtTarget | BalanceTarget | HandTarget | FootTarget] = [
        BalanceTarget(
            figure_label=actor_label,
            pelvis_bone="pelvis",
            support_points=list(support_points or ([] if seat_point is None else [seat_point])),
            center_of_mass_hint=seat_point,
        )
    ]
    for index, anchor_name in enumerate(foot_anchors):
        target_point = None
        if support_points:
            target_point = support_points[min(index, len(support_points) - 1)]
        elif seat_point is not None:
            target_point = seat_point
        constraints.append(
            FootTarget(
                figure_label=actor_label,
                anchor_name=anchor_name,
                target_point=target_point,
            )
        )
    return InteractionRecipe(
        kind="sit",
        actors=[actor_label],
        constraints=constraints,
        metadata={"seat_point": list(seat_point) if seat_point else None},
    )


def build_touch_recipe(
    source_label: str,
    target_label: str,
    *,
    source_anchor: str = "r_hand",
    target_anchor: str = "l_shoulder",
    target_point: Vector3 | None = None,
) -> InteractionRecipe:
    """Build a touch/contact preset between two figures."""

    return InteractionRecipe(
        kind="touch",
        actors=[source_label, target_label],
        constraints=[
            HandTarget(
                figure_label=source_label,
                anchor_name=source_anchor,
                target_figure=target_label,
                target_anchor=target_anchor,
                target_point=target_point,
            )
        ],
        metadata={
            "source_anchor": source_anchor,
            "target_anchor": target_anchor,
        },
    )


def build_kiss_recipe(
    actor_a: str,
    actor_b: str,
    *,
    a_anchor: str = "r_hand",
    b_anchor: str = "l_shoulder",
) -> InteractionRecipe:
    """Build a face-to-face interaction preset with a stabilizing contact plan."""

    b_anchor = "l_shoulder" if _side_from_name(a_anchor) == "right" else "r_shoulder"
    return InteractionRecipe(
        kind="kiss",
        actors=[actor_a, actor_b],
        constraints=[
            LookAtTarget(actor_a, "head", (0.0, 0.0, 0.0)),
            LookAtTarget(actor_b, "head", (0.0, 0.0, 0.0)),
            HandTarget(actor_a, a_anchor, target_figure=actor_b, target_anchor=b_anchor),
            HandTarget(actor_b, "l_hand" if _side_from_name(a_anchor) == "right" else "r_hand", target_figure=actor_a, target_anchor="l_shoulder" if _side_from_name(a_anchor) == "right" else "r_shoulder"),
        ],
        metadata={"interaction": "kiss"},
    )


def build_handshake_recipe(
    actor_a: str,
    actor_b: str,
    *,
    a_anchor: str = "r_hand",
    b_anchor: str = "r_hand",
) -> InteractionRecipe:
    """Build a mirrored hand-to-hand greeting preset for two figures."""

    return InteractionRecipe(
        kind="handshake",
        actors=[actor_a, actor_b],
        constraints=[
            LookAtTarget(actor_a, "head", (0.0, 0.0, 0.0)),
            LookAtTarget(actor_b, "head", (0.0, 0.0, 0.0)),
            HandTarget(actor_a, a_anchor, target_figure=actor_b, target_anchor=b_anchor),
            HandTarget(actor_b, b_anchor, target_figure=actor_a, target_anchor=a_anchor),
        ],
        metadata={"interaction": "handshake"},
    )


def build_hug_recipe(
    actor_a: str,
    actor_b: str,
    *,
    a_anchor: str = "r_hand",
    b_anchor: str = "r_hand",
) -> InteractionRecipe:
    """Build a mutual arms-around-each-other embrace preset for two figures."""

    a_far_shoulder = "l_shoulder" if _side_from_name(a_anchor) == "right" else "r_shoulder"
    b_far_shoulder = "l_shoulder" if _side_from_name(b_anchor) == "right" else "r_shoulder"
    return InteractionRecipe(
        kind="hug",
        actors=[actor_a, actor_b],
        constraints=[
            LookAtTarget(actor_a, "head", (0.0, 0.0, 0.0)),
            LookAtTarget(actor_b, "head", (0.0, 0.0, 0.0)),
            HandTarget(actor_a, a_anchor, target_figure=actor_b, target_anchor=a_far_shoulder),
            HandTarget(actor_b, b_anchor, target_figure=actor_a, target_anchor=b_far_shoulder),
        ],
        metadata={"interaction": "hug"},
    )


def build_face_each_other_recipe(actor_a: str, actor_b: str) -> InteractionRecipe:
    """Build a mutual eye-contact preset for two figures, with no limb contact."""

    return InteractionRecipe(
        kind="face_each_other",
        actors=[actor_a, actor_b],
        constraints=[
            LookAtTarget(actor_a, "head", (0.0, 0.0, 0.0)),
            LookAtTarget(actor_b, "head", (0.0, 0.0, 0.0)),
        ],
        metadata={"interaction": "face_each_other"},
    )


def build_fight_recipe(
    attacker: str,
    defender: str,
    *,
    strike_anchor: str = "r_hand",
    target_anchor: str = "head",
) -> InteractionRecipe:
    """Build a simple strike/contact preset for fight choreography."""

    strike_target = _target_anchor_from_strike_anchor(strike_anchor)
    strike_constraint: PoseTarget | ContactTarget | LookAtTarget | BalanceTarget | HandTarget | FootTarget
    if "foot" in _normalize_name(strike_anchor):
        strike_constraint = FootTarget(
            figure_label=attacker,
            anchor_name=strike_anchor,
            target_figure=defender,
            target_anchor=target_anchor,
        )
    else:
        strike_constraint = HandTarget(
            figure_label=attacker,
            anchor_name=strike_anchor,
            target_figure=defender,
            target_anchor=target_anchor,
        )
    return InteractionRecipe(
        kind="fight",
        actors=[attacker, defender],
        constraints=[
            strike_constraint,
            LookAtTarget(attacker, "head", (0.0, 0.0, 0.0)),
            LookAtTarget(defender, "head", (0.0, 0.0, 0.0)),
        ],
        metadata={
            "strike_anchor": strike_anchor,
            "target_anchor": target_anchor,
            "strike_target": strike_target,
        },
    )


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
    """Return the best available world-space point hint for an anchor.

    Prefers world_position from a scene snapshot; falls back to local_position
    as a rough proxy when only per-bone metadata is available.
    """

    anchor = profile.anchor(anchor_name)
    if anchor is None:
        return None
    bone = profile.bone(anchor.bone_name)
    if bone.world_position is not None:
        return bone.world_position
    if bone.local_position is not None:
        return bone.local_position
    return None


def resolve_interaction_target(
    target: AnchorTarget,
    rig_profiles: dict[str, FigureRigProfile],
) -> ResolvedInteractionTarget:
    """Resolve a hand/foot interaction target against the available rig profiles."""

    profile = _lookup_rig_profile(rig_profiles, target.figure_label)
    if profile is None:
        raise KeyError(f"Unknown figure for target resolution: {target.figure_label!r}")
    return profile.resolve_anchor_target(target, rig_profiles)


def build_rig_profiles_from_snapshot(snapshot: list[dict]) -> dict[str, "FigureRigProfile"]:
    """Build rig profiles for all skeletons from a scene_snapshot() result.

    Converts the bulk snapshot (one HTTP call) to the same dict used by
    prepare_interaction_recipe / apply_interaction_recipe_to_scene.  Both the
    figure label and internal name are stored as keys so lookup tolerates either.
    """

    profiles: dict[str, FigureRigProfile] = {}
    for skel_data in snapshot:
        name = skel_data.get("name", "")
        label = skel_data.get("label") or name
        bones: list[BoneProfile] = []
        for item in skel_data.get("bones", []):
            bones.append(
                BoneProfile(
                    name=item.get("name", ""),
                    label=item.get("label"),
                    parent_name=item.get("parent_name"),
                    rotation_order=item.get("rotation_order"),
                    local_position=_as_tuple3(item.get("local_position")),
                    world_position=_as_tuple3(item.get("world_position")),
                    rest_rotation=_as_tuple3(item.get("local_euler")),
                    axis_limits=default_axis_limits_for_bone(item.get("name", "")),
                    is_twist=_looks_like_twist(item.get("name", ""), item.get("label")),
                    is_helper=_looks_like_helper(item.get("name", ""), item.get("label")),
                )
            )
        family = _detect_figure_family([b.name for b in bones])
        profile = FigureRigProfile(
            figure_label=label,
            family=family,
            bones=bones,
            metadata={"bone_count": len(bones), "source": "snapshot"},
        )
        profiles[label] = profile
        if name and name != label:
            profiles[name] = profile
    return profiles


def build_rig_profile(skeleton: "DazSkeleton") -> FigureRigProfile:
    """Inspect a live DAZ skeleton and build a solver-friendly rig profile."""

    figure_label = skeleton.label or skeleton._identifier.value
    bones: list[BoneProfile] = []
    if hasattr(skeleton, "bone_metadata"):
        raw_bones = skeleton.bone_metadata()
        for item in raw_bones:
            bones.append(
                BoneProfile(
                    name=item.get("name", ""),
                    label=item.get("label"),
                    parent_name=item.get("parent_name"),
                    rotation_order=item.get("rotation_order"),
                    local_position=_as_tuple3(item.get("local_position")),
                    world_position=_as_tuple3(item.get("world_position")),
                    rest_rotation=_as_tuple3(item.get("local_euler")),
                    axis_limits=default_axis_limits_for_bone(item.get("name", "")),
                    is_twist=_looks_like_twist(item.get("name", ""), item.get("label")),
                    is_helper=_looks_like_helper(item.get("name", ""), item.get("label")),
                )
            )
    else:
        for bone in skeleton.bones():
            parent = bone.parent
            parent_name = getattr(parent, "name", None) if parent is not None else None
            root_names = {
                getattr(skeleton, "label", None),
                getattr(getattr(skeleton, "_identifier", None), "value", None),
            }
            if parent_name in root_names:
                parent_name = None
            bones.append(
                BoneProfile(
                    name=bone.name or bone._identifier.value,
                    label=bone.label,
                    parent_name=parent_name,
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
