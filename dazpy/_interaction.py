from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
import re
from typing import TYPE_CHECKING, Any, Callable, Literal, Sequence

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


def _as_optional_float(value: object | None) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]


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


def _name_words(text: str) -> list[str]:
    """Split a bone name/label into lowercase words (camelCase, snake_case, spaces)."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return re.findall(r"[a-z0-9]+", spaced.lower())


def _looks_like_helper(name: str, label: str | None = None) -> bool:
    # 'end' must be a whole word: substring matching flagged every Genesis 3/8
    # *Bend bone (lForearmBend, lShldrBend, lThighBend) as a helper.
    text = f"{name} {label or ''}"
    if "helper" in text.lower():
        return True
    return any(word in ("end", "endpoint") for word in _name_words(text))


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


_SHOULDER_JOINT_TOKENS = ("upperarm", "upper_arm", "shldrbend")
_KNEE_JOINT_TOKENS = ("shin", "calf", "knee")

ANCHOR_SURFACE_RADIUS: dict[str, float] = {
    "pelvis": 12.0,
    "spine": 12.0,
    "chest": 12.0,
    "neck": 6.0,
    "head": 10.0,
    "shoulder": 6.0,
    "elbow": 4.0,
    "hand": 3.0,
    "knee": 5.0,
    "foot": 5.0,
}
"""Approximate body radius (cm, adult figure) from an anchor's joint centre to its skin."""

EFFECTOR_REACH_FALLBACK: dict[str, float] = {"hand": 15.0, "foot": 12.0}
"""Wrist-to-fingers / ankle-to-toes reach (cm) when the profile has no descendant positions."""


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
    surface_standoff: float = 0.0
    """How far the effector bone stops short of ``target_point`` (cm).

    ``target_point`` is the target anchor's joint centre (plus ``offset``).
    The standoff is applied at alignment time, toward the source limb, once
    staging has fixed where the figures stand.
    """
    wrap: bool = False
    """Reach over the target anchor to the partner's back (see ``AnchorTarget.wrap``)."""

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
            "surface_standoff": self.surface_standoff,
            "wrap": self.wrap,
        }


@dataclass
class FigureRigProfile:
    """A DAZ figure expressed as a solver-friendly rig profile."""

    figure_label: str
    family: str
    bones: list[BoneProfile] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)
    figure_position: Vector3 | None = None
    """World position of the figure node itself (what ``set_position`` moves)."""

    def __post_init__(self) -> None:
        self._index = {bone.name: i for i, bone in enumerate(self.bones)}

    def bone_offset(self, name: str) -> Vector3 | None:
        """Offset of a bone from the figure's origin, in world axes.

        ``world_position - figure_position`` when both are known (live
        profiles). Otherwise falls back to ``local_position``, which hand-built
        profiles use for this offset. Live ``local_position`` is the bone's
        translation channel (zero on an unposed figure), not an offset.
        """
        bone = self.bone(name)
        if self.figure_position is not None and bone.world_position is not None:
            return _sub_vec3(bone.world_position, self.figure_position)
        return bone.local_position

    def effector_reach(self, bone_name: str) -> float | None:
        """Distance from a bone to its farthest descendant (wrist to finger joints, ankle to toes).

        None when the bone or its descendants have no world positions.
        """
        origin = self.bone(bone_name).world_position
        if origin is None:
            return None
        reach: float | None = None
        for bone in self.bones:
            if bone.name == bone_name or bone.world_position is None:
                continue
            parent = bone.parent_name
            seen: set[str] = set()
            while parent is not None and parent != bone_name and parent not in seen and parent in self._index:
                seen.add(parent)
                parent = self.bones[self._index[parent]].parent_name
            if parent != bone_name:
                continue
            distance = _vec3_length(_vec3_sub(bone.world_position, origin))
            reach = distance if reach is None else max(reach, distance)
        return reach

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

    def _find_terminal_bone(self, candidates: Sequence[tuple[str, ChainSide, tuple[str, ...]]]) -> BoneProfile | None:
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
            ("l_shoulder", "arm", "left", ("shoulder", "shldr", "clavicle", "upper_arm")),
            ("r_shoulder", "arm", "right", ("shoulder", "shldr", "clavicle", "upper_arm")),
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
        elif "shoulder" in lowered or "shldr" in lowered or "clavicle" in lowered or "arm" in lowered or "forearm" in lowered or "elbow" in lowered:
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
        # Preferred tokens are tried first: Genesis 9's ``l_shoulder`` bone is
        # the clavicle (origin by the sternum), so the shoulder anchor is the
        # upper-arm joint; ``*thigh`` starts at the hip, so the knee is the shin.
        preferred: dict[str, tuple[str, ...]] = {
            "l_shoulder": _SHOULDER_JOINT_TOKENS,
            "r_shoulder": _SHOULDER_JOINT_TOKENS,
            "l_knee": _KNEE_JOINT_TOKENS,
            "r_knee": _KNEE_JOINT_TOKENS,
        }
        patterns: list[tuple[str, AnchorRole, ChainSide, tuple[str, ...]]] = [
            ("pelvis", "pelvis", "center", ("pelvis", "hip")),
            ("spine", "spine", "center", ("spine", "abdomen", "torso")),
            ("chest", "chest", "center", ("chest", "upperchest", "thorax")),
            ("neck", "neck", "center", ("neck",)),
            ("head", "head", "center", ("head",)),
            ("l_shoulder", "shoulder", "left", ("shoulder", "shldr", "clavicle")),
            ("r_shoulder", "shoulder", "right", ("shoulder", "shldr", "clavicle")),
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
            candidates = [(role, side, tokens)]
            if key in preferred:
                candidates.insert(0, (role, side, preferred[key]))
            bone = self._find_terminal_bone(candidates)
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
        target_role: AnchorRole | None = None
        anchor_point_hint = False

        if target_figure and target_anchor and rig_profiles is not None:
            target_profile = _lookup_rig_profile(rig_profiles, target_figure)
            if target_profile is not None:
                resolved = target_profile.require_anchor(target_anchor)
                target_bone = resolved.bone_name
                target_role = resolved.role
        if target_point is None and target_figure is not None and target_anchor is not None and rig_profiles is not None:
            target_profile = _lookup_rig_profile(rig_profiles, target_figure)
            if target_profile is not None:
                target_point = _anchor_world_point_hint(target_profile, target_anchor)
                anchor_point_hint = target_point is not None

        if target.surface_standoff is not None:
            surface_standoff = max(0.0, float(target.surface_standoff))
        elif anchor_point_hint and target_role is not None:
            # Only an anchor's joint-centre hint needs pushing out to the skin;
            # an explicit target_point is taken as the contact point itself.
            surface_standoff = self._default_surface_standoff(anchor, target_role)
        else:
            surface_standoff = 0.0

        # The offset shifts a resolved point; it is not a point on its own.
        # Leaving target_point None lets build_pose_patch report the target as
        # unresolved and align_single_limb_target return missing_target_point.
        if target_point is not None:
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
            surface_standoff=surface_standoff,
            wrap=target.wrap,
        )

    def _default_surface_standoff(self, source: InteractionAnchor, target_role: AnchorRole) -> float:
        """Joint-to-joint gap for skin contact: target body radius + the source effector's reach.

        A hand or foot effector is its wrist/ankle joint, so it stops a whole
        hand/foot short of the skin; hand-to-hand (handshake) stops half a hand
        short so the palms meet.
        """
        if source.role in ("hand", "foot"):
            reach = self.effector_reach(source.bone_name)
            if reach is None:
                reach = EFFECTOR_REACH_FALLBACK[source.role]
        else:
            reach = ANCHOR_SURFACE_RADIUS.get(source.role, 0.0)
        if source.role == "hand" and target_role == "hand":
            return reach * 0.5
        return ANCHOR_SURFACE_RADIUS.get(target_role, 0.0) + reach

    def to_dict(self) -> dict:
        return {
            "figure_label": self.figure_label,
            "family": self.family,
            "bones": [bone.to_dict() for bone in self.bones],
            "metadata": dict(self.metadata),
            "figure_position": list(self.figure_position) if self.figure_position is not None else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FigureRigProfile":
        return cls(
            figure_label=data.get("figure_label", ""),
            family=data.get("family", "generic"),
            bones=[BoneProfile.from_dict(item) for item in data.get("bones", [])],
            metadata=dict(data.get("metadata", {})),
            figure_position=_as_tuple3(data.get("figure_position")),
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
    surface_standoff: float | None = None
    """How far the effector joint stops short of the target (cm).

    None (default) picks one for anchor-to-anchor targets: the target anchor's
    body radius plus the effector's hand/foot length, so the hand lands on the
    skin instead of inside the partner. 0 aims at the joint centre. Explicit
    ``target_point`` targets default to 0.
    """
    wrap: bool = False
    """Reach over the target anchor (a shoulder) to the partner's upper back.

    The effector goes first over the top of the shoulder, then down behind it
    (the solver has no collision, so a direct reach would pass through the
    body). ``surface_standoff`` and ``offset`` do not apply.
    """

    def to_dict(self) -> dict:
        return {
            "kind": type(self).__name__,
            "figure_label": self.figure_label,
            "anchor_name": self.anchor_name,
            "target_figure": self.target_figure,
            "target_anchor": self.target_anchor,
            "target_point": list(self.target_point) if self.target_point else None,
            "offset": list(self.offset),
            "surface_standoff": self.surface_standoff,
            "wrap": self.wrap,
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
        constraints: list[PoseTarget | ContactTarget | LookAtTarget | BalanceTarget | HandTarget | FootTarget] = []
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
                        surface_standoff=_as_optional_float(item.get("surface_standoff")),
                        wrap=bool(item.get("wrap", False)),
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
                        surface_standoff=_as_optional_float(item.get("surface_standoff")),
                        wrap=bool(item.get("wrap", False)),
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
    # Partner figure label -> the figure it is turned to face and by how much.
    # ``rig_profiles`` (and so ``resolved_targets``) already have these turns
    # applied; ``build_pose_patch`` stages each partner a limb target links in
    # front of its anchor (a look-only partner is only turned).
    facing: dict[str, "FacingAssignment"] = field(default_factory=dict)

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
            "facing": {label: assignment.to_dict() for label, assignment in self.facing.items()},
        }

    def build_pose_patch(self) -> "InteractionPosePatch":
        """Build a coarse live-placement patch from the prepared recipe.

        Intentionally conservative: translates figures so their anchors are
        staged near their requested targets (hand/foot targets in X/Z only, a
        ``BalanceTarget`` also sets height). A faced partner (see ``facing``)
        is turned and placed straight in front of its anchor figure, as far as
        the shortest limb between them comfortably reaches. Does not solve bone
        rotations (that's ``align_limb_targets``).
        """

        # Each staged position records whether it sets the figure's height.
        # Hand/foot targets are floor-locked (X/Z only; IK handles reach), a
        # BalanceTarget (sit) sets full 3D.
        figure_positions: dict[str, list[tuple[Vector3, bool]]] = {}
        unresolved: list[ResolvedInteractionTarget] = []

        def _floor_height(label: str) -> float:
            profile = _lookup_rig_profile(self.rig_profiles, label)
            if profile is not None and profile.figure_position is not None:
                return profile.figure_position[1]
            return 0.0

        def _append_position(label: str, point: Vector3, sets_height: bool = False) -> None:
            figure_positions.setdefault(label, []).append((point, sets_height))

        def _staged_position(label: str | None) -> Vector3 | None:
            if not label or not figure_positions.get(label):
                return None
            entries = figure_positions[label]
            xz = _average_vec3([point for point, _ in entries])
            assert xz is not None  # entries is non-empty
            heights = [point[1] for point, sets_height in entries if sets_height]
            y = sum(heights) / len(heights) if heights else _floor_height(label)
            return (xz[0], y, xz[2])

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
                pelvis_offset = profile.bone_offset(pelvis_anchor.bone_name)
                target_point = constraint.center_of_mass_hint
                if target_point is None and constraint.support_points:
                    target_point = _average_vec3(list(constraint.support_points))
                if target_point is None or pelvis_offset is None:
                    unresolved.append(
                        ResolvedInteractionTarget(
                            figure_label=constraint.figure_label,
                            anchor_name=constraint.pelvis_bone,
                            bone_name=pelvis_anchor.bone_name,
                            target_point=target_point,
                        )
                    )
                    continue
                _append_position(constraint.figure_label, _sub_vec3(target_point, pelvis_offset), sets_height=True)

        # Faced pairs: the partner goes straight in front of its anchor figure.
        faced_targets: set[int] = set()
        figure_yaw_degrees: dict[str, float] = {}
        for partner_label, assignment in self.facing.items():
            figure_yaw_degrees[partner_label] = assignment.yaw_degrees
            anchor_profile = _lookup_rig_profile(self.rig_profiles, assignment.anchor)
            partner_profile = _lookup_rig_profile(self.rig_profiles, partner_label)
            if anchor_profile is None or partner_profile is None or partner_profile.figure_position is None:
                continue
            forward = figure_forward(anchor_profile)
            anchor_base = _staged_position(assignment.anchor) or anchor_profile.figure_position
            if forward is None or anchor_base is None:
                continue
            faced = self._stage_faced_partner(anchor_profile, partner_profile, anchor_base, forward)
            if faced is None:
                continue
            partner_position, between = faced
            _append_position(partner_label, partner_position)
            faced_targets.update(id(target) for target in between)

        for resolved in self.resolved_targets:
            if id(resolved) in faced_targets:
                continue
            profile = _lookup_rig_profile(self.rig_profiles, resolved.figure_label)
            if profile is None:
                unresolved.append(resolved)
                continue
            source_anchor = profile.anchor(resolved.anchor_name)
            if source_anchor is None:
                unresolved.append(resolved)
                continue
            source_offset = profile.bone_offset(source_anchor.bone_name)
            if source_offset is None:
                unresolved.append(resolved)
                continue
            target_profile = _lookup_rig_profile(self.rig_profiles, resolved.target_figure) if resolved.target_figure else None
            target_offset = _anchor_bone_offset(target_profile, resolved.target_anchor) if (target_profile and resolved.target_anchor) else None
            source_base = _staged_position(resolved.figure_label)
            target_base = _staged_position(resolved.target_figure)

            if target_profile is not None and resolved.target_figure is not None:
                if target_base is not None and resolved.target_point is not None and source_base is None:
                    world_target = _vec3_add(target_base, resolved.target_point)
                    _append_position(resolved.figure_label, _sub_vec3(world_target, source_offset))
                    continue

                if target_offset is not None:
                    # Stage the effector a surface standoff short of the target
                    # joint, on the source limb's side, so IK starts at the
                    # contact point instead of folding the arm back to it.
                    root_offset = _limb_root_offset(profile, source_anchor.bone_name)
                    if source_base is None and target_base is None:
                        contact_center = _midpoint_vec3(source_offset, target_offset)
                        source_position = _sub_vec3(contact_center, source_offset)
                        target_position = _sub_vec3(contact_center, target_offset)
                        gap = _standoff_shift(contact_center, source_position, root_offset, resolved.surface_standoff)
                        _append_position(resolved.figure_label, _vec3_add(source_position, _vec3_scale(gap, 0.5)))
                        _append_position(resolved.target_figure, _vec3_sub(target_position, _vec3_scale(gap, 0.5)))
                    elif source_base is None and target_base is not None:
                        target_world = _vec3_add(target_base, target_offset)
                        source_position = _sub_vec3(target_world, source_offset)
                        gap = _standoff_shift(target_world, source_position, root_offset, resolved.surface_standoff)
                        _append_position(resolved.figure_label, _vec3_add(source_position, gap))
                    elif source_base is not None and target_base is None:
                        source_world = _vec3_add(source_base, source_offset)
                        target_world = _sub_vec3(source_world, target_offset)
                        gap = _standoff_shift(source_world, source_base, root_offset, resolved.surface_standoff)
                        _append_position(resolved.target_figure, _vec3_sub(target_world, gap))
                    continue

            if resolved.target_point is None:
                unresolved.append(resolved)
                continue
            _append_position(resolved.figure_label, _sub_vec3(resolved.target_point, source_offset))

        averaged_positions: dict[str, Vector3] = {}
        for label in figure_positions:
            staged = _staged_position(label)
            if staged is not None:
                averaged_positions[label] = staged
        diagnostics: dict[str, object] = {
            "figure_count": len(averaged_positions),
            "unresolved_target_count": len(unresolved),
        }
        return InteractionPosePatch(
            figure_positions=averaged_positions,
            figure_yaw_degrees=figure_yaw_degrees,
            unresolved_targets=unresolved,
            diagnostics=diagnostics,
        )

    def apply(
        self,
        scene: Any,
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
                figure_displacements=self._staging_displacements(patch),
            )
        return result

    def _staging_displacements(self, patch: "InteractionPosePatch") -> dict[str, Vector3]:
        """How far the patch moved each figure whose original position is known."""

        displacements: dict[str, Vector3] = {}
        for label, position in patch.figure_positions.items():
            profile = _lookup_rig_profile(self.rig_profiles, label)
            if profile is not None and profile.figure_position is not None:
                displacements[label] = _sub_vec3(position, profile.figure_position)
        return displacements

    def align_limb_targets(
        self,
        scene: Any,
        *,
        max_iterations: int | None = None,
        step_degrees: float = 1.0,
        damping: float = 0.25,
        tolerance: float = 0.15,
        figure_displacements: dict[str, Vector3] | None = None,
    ) -> list["LimbAlignmentResult"]:
        """Apply live limb alignment for resolved hand and foot targets.

        ``figure_displacements`` (label -> how far staging moved that figure)
        shifts targets that point at another figure's anchor, whose resolved
        point was captured before staging. ``apply`` passes it.
        """

        alignment_results: list[LimbAlignmentResult] = []
        for resolved in self.resolved_targets:
            if resolved.target_point is None:
                continue
            if figure_displacements and resolved.target_figure and resolved.target_anchor:
                # Match by resolved profile, so label aliases ("Genesis9") still match.
                target_profile = _lookup_rig_profile(self.rig_profiles, resolved.target_figure)
                shift = next(
                    (
                        displacement
                        for label, displacement in figure_displacements.items()
                        if target_profile is not None and _lookup_rig_profile(self.rig_profiles, label) is target_profile
                    ),
                    None,
                )
                if shift is not None:
                    resolved = replace(resolved, target_point=_vec3_add(resolved.target_point, shift))
            skeleton = scene.find_skeleton_by_label(resolved.figure_label)
            profile = _lookup_rig_profile(self.rig_profiles, resolved.figure_label)
            if profile is None:
                continue
            # Checked at the loop top, but replace() above drops mypy's narrowing.
            joint_point = resolved.target_point
            if joint_point is None:
                continue
            solve = dict(
                max_iterations=max_iterations or self.plan.options.max_iterations,
                step_degrees=step_degrees,
                damping=damping,
                tolerance=tolerance,
            )
            if resolved.wrap:
                wrapped = self._align_wrap(skeleton, profile, resolved, self._staged_bases(figure_displacements), solve)
                if wrapped is not None:
                    alignment_results.append(wrapped)
                    continue
            # Hand-to-hand both ways (handshake): both hands meet halfway
            # instead of chasing each other's rest positions.
            meeting = (
                self._contact_geometry(resolved, self._staged_bases(figure_displacements))
                if self._mutual_target(resolved) is not None
                else None
            )
            if meeting is not None:
                resolved = replace(resolved, target_point=meeting.stop)
            elif resolved.surface_standoff > 0.0:
                source_shift = _displacement_for_profile(self.rig_profiles, profile, figure_displacements)
                resolved = replace(resolved, target_point=_surface_contact_point(profile, resolved, source_shift))
            result = align_single_limb_target(
                skeleton,
                profile,
                resolved,
                max_iterations=max_iterations or self.plan.options.max_iterations,
                step_degrees=step_degrees,
                damping=damping,
                tolerance=tolerance,
            )
            if meeting is not None:
                result.diagnostics["meeting_point"] = list(meeting.joint)
            if resolved.surface_standoff > 0.0:
                result.diagnostics["surface_standoff"] = resolved.surface_standoff
                result.diagnostics["target_joint_point"] = list(joint_point)
            alignment_results.append(result)
        return alignment_results

    def _align_wrap(
        self,
        skeleton: Any,
        profile: FigureRigProfile,
        resolved: ResolvedInteractionTarget,
        bases: dict[int, Vector3],
        solve: dict[str, Any],
    ) -> "LimbAlignmentResult | None":
        """IK passes for a wrap target: through each waypoint around the partner, then to the stop on its back.

        Returns the last pass, with iterations and initial error covering all
        of them. None when the wrap geometry is unknown (the caller falls
        back to a direct reach).
        """
        geometry = self._contact_geometry(resolved, bases)
        if geometry is None or not geometry.waypoints:
            return None
        passes = [
            align_single_limb_target(skeleton, profile, replace(resolved, target_point=point), **solve)
            for point in (*geometry.waypoints, geometry.stop)
        ]
        final = passes[-1]
        diagnostics = dict(final.diagnostics)
        diagnostics.update(
            wrap_waypoints=[list(point) for point in geometry.waypoints],
            waypoint_errors=[p.final_error for p in passes[:-1]],
        )
        if geometry.finger_point is not None:
            diagnostics.update(self._aim_wrap_hand(skeleton, profile, resolved.bone_name, geometry.finger_point, solve))
        return replace(
            final,
            iterations=sum(p.iterations for p in passes),
            initial_error=passes[0].initial_error,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _aim_wrap_hand(
        skeleton: Any, profile: FigureRigProfile, hand_bone: str, finger_point: Vector3, solve: dict[str, Any]
    ) -> dict[str, object]:
        """Turn the wrapped hand (its bone alone) so its fingertips lie across the partner's back.

        The wrist stays put. Each axis is held within ``WRAP_HAND_LIMIT`` of
        rest. Returns diagnostics; empty when the hand has no finger bones or
        the skeleton has no batch Jacobian.
        """
        tip = _farthest_descendant(profile, hand_bone)
        if tip is None or not hasattr(skeleton, "evaluate_pose_jacobian"):
            return {}
        aim = ResolvedInteractionTarget(figure_label=profile.figure_label, anchor_name=hand_bone, bone_name=tip, target_point=finger_point)
        result = _align_single_limb_batch(
            skeleton, profile, [hand_bone], aim,
            max_iterations=40, step_degrees=solve["step_degrees"], damping=solve["damping"], tolerance=1.0,
        )
        rotation = result.applied_rotations.get(hand_bone)
        if rotation is None:
            return {"hand_aim": "no_rotation"}
        clamped = tuple(max(-WRAP_HAND_LIMIT, min(WRAP_HAND_LIMIT, value)) for value in rotation)
        if clamped != tuple(rotation):
            skeleton.set_bone_rotations({hand_bone: clamped})
        return {"hand_aim_bone": tip, "hand_aim_rotation": list(clamped), "hand_aim_clamped": clamped != tuple(rotation)}

    def _stage_faced_partner(
        self,
        anchor_profile: FigureRigProfile,
        partner_profile: FigureRigProfile,
        anchor_base: Vector3,
        forward: Vector3,
    ) -> tuple[Vector3, list[ResolvedInteractionTarget]] | None:
        """Partner origin straight in front of the anchor, and the targets between them.

        The separation is the shortest any limb between them comfortably
        reaches, but at least ``FACING_MIN_SEPARATION``. None when no target
        between them has known geometry.
        """
        assert partner_profile.figure_position is not None
        partner_y = partner_profile.figure_position[1]

        def _partner_base(d: float) -> Vector3:
            return (anchor_base[0] + forward[0] * d, partner_y, anchor_base[2] + forward[2] * d)

        def _bases_at(d: float) -> dict[int, Vector3]:
            return {id(anchor_profile): anchor_base, id(partner_profile): _partner_base(d)}

        pairs = ((anchor_profile, partner_profile), (partner_profile, anchor_profile))
        between = [
            target
            for target in self.resolved_targets
            if target.target_anchor is not None
            and any(
                _lookup_rig_profile(self.rig_profiles, target.figure_label) is source
                and _lookup_rig_profile(self.rig_profiles, target.target_figure) is dest
                for source, dest in pairs
            )
        ]
        separations: list[float] = []
        for target in between:
            separation = self._faced_separation(target, _bases_at)
            if separation is not None:
                # A wrap sets its own (embrace) distance; reaches keep two torsos apart.
                separations.append(separation if target.wrap else max(FACING_MIN_SEPARATION, separation))
        if not separations:
            return None
        return _partner_base(min(separations)), between

    def _mutual_target(self, target: ResolvedInteractionTarget) -> ResolvedInteractionTarget | None:
        """The reverse of a hand/foot-to-hand/foot target (B's hand -> A's hand for A's hand -> B's hand), if any."""
        if target.target_figure is None or target.target_anchor is None:
            return None
        source = _lookup_rig_profile(self.rig_profiles, target.figure_label)
        partner = _lookup_rig_profile(self.rig_profiles, target.target_figure)
        if source is None or partner is None or source is partner:
            return None
        for other in self.resolved_targets:
            if (
                other is not target
                and other.anchor_name == target.target_anchor
                and other.target_anchor == target.anchor_name
                and _lookup_rig_profile(self.rig_profiles, other.figure_label) is partner
                and _lookup_rig_profile(self.rig_profiles, other.target_figure) is source
            ):
                return other
        return None

    def _staged_bases(self, figure_displacements: dict[str, Vector3] | None) -> dict[int, Vector3]:
        """Figure origins after staging (profile id -> position plus displacement)."""
        bases: dict[int, Vector3] = {}
        for profile in self.rig_profiles.values():
            if profile.figure_position is None or id(profile) in bases:
                continue
            shift = _displacement_for_profile(self.rig_profiles, profile, figure_displacements)
            bases[id(profile)] = _vec3_add(profile.figure_position, shift) if shift is not None else profile.figure_position
        return bases

    def _contact_geometry(self, target: ResolvedInteractionTarget, bases: dict[int, Vector3]) -> "_ContactGeometry | None":
        """Where ``target``'s effector should stop with the figure origins at ``bases`` (keyed by profile id).

        The target joint pulled back toward the source limb root by the surface
        standoff; for a mutual hand-to-hand pair the joint is the meeting point
        between both shoulders. ``root`` is the reach root (shoulder/hip joint)
        and ``limb_length`` its reach. None when the geometry is unknown.
        """
        source = _lookup_rig_profile(self.rig_profiles, target.figure_label)
        partner = _lookup_rig_profile(self.rig_profiles, target.target_figure)
        if source is None or partner is None or target.target_anchor is None:
            return None
        limb = _limb_geometry(source, target.bone_name, bases.get(id(source), source.figure_position))
        if limb is None:
            return None
        chain_root, root, length = limb
        partner_base = bases.get(id(partner), partner.figure_position)
        if target.wrap:
            path = _wrap_path(partner, partner_base, target.target_anchor)
            if path is None:
                return None
            waypoints, back, fingers = path
            return _ContactGeometry(root=root, joint=back, stop=back, limb_length=length, waypoints=tuple(waypoints), finger_point=fingers)
        joint: Vector3 | None = None
        mutual = self._mutual_target(target)
        if mutual is not None:
            other = _limb_geometry(partner, mutual.bone_name, partner_base)
            if other is not None:
                joint = _meeting_point(root, length, other[1], other[2])
        else:
            offset = _anchor_bone_offset(partner, target.target_anchor)
            if offset is not None and partner_base is not None:
                joint = _vec3_add(_vec3_add(partner_base, offset), target.offset)
        if joint is None:
            return None
        return _ContactGeometry(root=root, joint=joint, stop=_pull_toward_root(joint, chain_root, target.surface_standoff), limb_length=length)

    def _faced_separation(
        self, target: ResolvedInteractionTarget, bases_at: Callable[[float], dict[int, Vector3]]
    ) -> float | None:
        """How far in front of its anchor a faced partner can stand (origin to origin, cm).

        The separation at which ``target``'s limb reaches its stop point at
        ``FACING_REACH_FRACTION`` (``FACING_FOOT_REACH_FRACTION`` for a leg) of
        its reach; ``bases_at(d)`` places the figures for separation ``d``.
        Never closer than ``FACING_MIN_SEPARATION``.
        """
        if target.wrap:
            # Reach doesn't bound a wrap: its arm must get its elbow beside the
            # partner's ribs, which only an embrace distance allows.
            return WRAP_SEPARATION
        profile = _lookup_rig_profile(self.rig_profiles, target.figure_label)
        chain = profile.suggest_primary_chain(target.bone_name) if profile is not None else None
        fraction = FACING_FOOT_REACH_FRACTION if chain is not None and chain.role in ("foot", "leg") else FACING_REACH_FRACTION

        def _gap(d: float) -> tuple[float, float] | None:
            geometry = self._contact_geometry(target, bases_at(d))
            if geometry is None:
                return None
            return _vec3_length(_vec3_sub(geometry.stop, geometry.root)), geometry.limb_length * fraction

        low, high = FACING_MIN_SEPARATION, _FACING_MAX_SEPARATION
        at_low = _gap(low)
        if at_low is None:
            return None
        if at_low[0] >= at_low[1]:
            return low
        at_high = _gap(high)
        assert at_high is not None
        if at_high[0] <= at_high[1]:
            return high
        for _ in range(40):
            mid = (low + high) / 2.0
            at_mid = _gap(mid)
            assert at_mid is not None
            if at_mid[0] <= at_mid[1]:
                low = mid
            else:
                high = mid
        return low


def _displacement_for_profile(
    rig_profiles: dict[str, FigureRigProfile],
    profile: FigureRigProfile,
    figure_displacements: dict[str, Vector3] | None,
) -> Vector3 | None:
    """Staging displacement of ``profile``'s figure, matched by profile so label aliases work."""
    for label, displacement in (figure_displacements or {}).items():
        if _lookup_rig_profile(rig_profiles, label) is profile:
            return displacement
    return None


def _limb_root_bone(profile: FigureRigProfile, effector_bone: str) -> str | None:
    """Root of the effector's alignment chain (shoulder for a hand, hip for a foot)."""
    chain = profile.suggest_primary_chain(effector_bone)
    chain_names = _alignment_chain_names(profile, chain) if chain is not None else []
    return chain_names[0] if chain_names else None


def _limb_root_offset(profile: FigureRigProfile, effector_bone: str) -> Vector3 | None:
    root = _limb_root_bone(profile, effector_bone)
    return profile.bone_offset(root) if root is not None else None


def _approach_direction(joint: Vector3, root: Vector3) -> Vector3 | None:
    """Unit direction from a target joint toward the source limb root, horizontal when possible."""
    horizontal = (root[0] - joint[0], 0.0, root[2] - joint[2])
    length = _vec3_length(horizontal)
    if length >= 1e-6:
        return _vec3_scale(horizontal, 1.0 / length)
    full = _vec3_sub(root, joint)
    length = _vec3_length(full)
    return _vec3_scale(full, 1.0 / length) if length >= 1e-6 else None


def _standoff_shift(joint: Vector3, source_position: Vector3, root_offset: Vector3 | None, standoff: float) -> Vector3:
    """How far to move the source figure (staged at ``source_position``) away from ``joint``."""
    if standoff <= 0.0:
        return (0.0, 0.0, 0.0)
    root = _vec3_add(source_position, root_offset) if root_offset is not None else source_position
    direction = _approach_direction(joint, root)
    return _vec3_scale(direction, standoff) if direction is not None else (0.0, 0.0, 0.0)


def _surface_contact_point(
    profile: FigureRigProfile,
    target: ResolvedInteractionTarget,
    source_shift: Vector3 | None,
) -> Vector3:
    """Pull ``target.target_point`` back toward the source limb by ``target.surface_standoff``.

    The approach direction runs (horizontally, as staging does) from the
    target joint to the root of the source limb's alignment chain (shoulder
    for a hand, hip for a foot), at its staged position, so the effector
    stops on the near side of the partner's body. Falls back to the figure
    origin; returns the point unchanged when neither position is known or
    they coincide.
    """
    point = target.target_point
    assert point is not None
    root_bone = _limb_root_bone(profile, target.bone_name)
    root = profile.bone(root_bone).world_position if root_bone is not None else None
    if root is None and profile.figure_position is not None:
        root = (profile.figure_position[0], point[1], profile.figure_position[2])
    if root is None:
        return point
    if source_shift is not None:
        root = _vec3_add(root, source_shift)
    return _pull_toward_root(point, root, target.surface_standoff)


def _pull_toward_root(point: Vector3, root: Vector3, standoff: float) -> Vector3:
    """``point`` moved ``standoff`` toward ``root`` (horizontally when possible), never past the root.

    Past the root would aim behind the source on overlapping figures.
    """
    if standoff <= 0.0:
        return point
    direction = _approach_direction(point, root)
    if direction is None:
        return point
    reach = min(standoff, _vec3_length(_vec3_sub(root, point)))
    return _vec3_add(point, _vec3_scale(direction, reach))


# ── facing ───────────────────────────────────────────────────────────────────

FACING_REACH_FRACTION = 0.85
"""Fraction of an arm's reach a faced partner is staged to need: short of full extension, where IK steps stall."""
FACING_FOOT_REACH_FRACTION = 0.95
"""The same for a leg (kick): nearly extended, since a folded high kick is hard for the solver to find from a straight rest leg."""
FACING_MIN_SEPARATION = 2 * ANCHOR_SURFACE_RADIUS["spine"] + 6
"""Closest two faced figures' origins are staged (cm): two torso radii plus clearance."""
_FACING_MAX_SEPARATION = 400.0
# A mutual hand-to-hand meeting point sits this fraction of the arm's reach
# below the shoulder joints (about navel height).
_MEETING_DROP_FRACTION = 0.8
# Chain segments shorter than this (cm) are joint offsets (twist bones, etc.), not limb segments.
_LIMB_SEGMENT_MIN_LENGTH = 2.0
_FORWARD_ANCHOR_PAIRS: tuple[tuple[str, str], ...] = (("l_shoulder", "r_shoulder"), ("l_knee", "r_knee"), ("l_foot", "r_foot"))


@dataclass(frozen=True)
class FacingAssignment:
    """A partner figure turned to face another before staging."""

    anchor: str  # the figure it faces (which keeps its own orientation)
    yaw_degrees: float  # degrees added to the partner's Y rotation

    def to_dict(self) -> dict:
        return {"anchor": self.anchor, "yaw_degrees": self.yaw_degrees}


@dataclass(frozen=True)
class _ContactGeometry:
    root: Vector3
    joint: Vector3
    stop: Vector3
    limb_length: float
    waypoints: tuple[Vector3, ...] = ()  # a wrap's points around the partner, reached in turn before ``stop``
    finger_point: Vector3 | None = None  # where a wrapped hand's fingertips aim


def _farthest_descendant(profile: FigureRigProfile, bone_name: str) -> str | None:
    """The descendant of ``bone_name`` farthest from it (a hand's fingertip), or None."""
    origin = profile.bone(bone_name).world_position if bone_name in profile.bone_names() else None
    if origin is None:
        return None
    best: tuple[float, str] | None = None
    for bone in profile.bones:
        if bone.name == bone_name or bone.world_position is None or bone.is_helper:
            continue
        parent = bone.parent_name
        seen: set[str] = set()
        while parent is not None and parent != bone_name and parent not in seen and parent in profile.bone_names():
            seen.add(parent)
            parent = profile.bone(parent).parent_name
        if parent != bone_name:
            continue
        distance = _vec3_length(_vec3_sub(bone.world_position, origin))
        if best is None or distance > best[0]:
            best = (distance, bone.name)
    return best[1] if best is not None else None


def _anchor_bone_offset(profile: FigureRigProfile, anchor_name: str) -> Vector3 | None:
    anchor = profile.anchor(anchor_name)
    return None if anchor is None else profile.bone_offset(anchor.bone_name)


# Wrap geometry (cm) in the partner's frame: lateral (out from the spine
# toward the target shoulder's side), back (behind the line between the
# shoulder anchors), at WRAP_DROP below the shoulder anchor. The effector
# passes these points around the partner's side, under its arm, then stops
# on the upper back.
WRAP_DROP = 16.0
# Origin-to-origin distance (cm) a wrapped partner is staged at.
WRAP_SEPARATION = 26.0
WRAP_SIDE_POINTS: tuple[tuple[float, float], ...] = ((25.0, -6.0), (24.0, 4.0))
WRAP_BACK_POINT: tuple[float, float] = (14.0, 10.0)
# Where the wrapped hand's fingertips aim (across the back toward the spine),
# and how far (degrees, per axis from rest) the hand may bend to get there.
WRAP_FINGER_POINT: tuple[float, float] = (2.0, 10.0)
WRAP_HAND_LIMIT = 70.0


def _wrap_path(partner: FigureRigProfile, partner_base: Vector3 | None, target_anchor: str) -> tuple[list[Vector3], Vector3, Vector3] | None:
    """A wrap around ``partner`` (origin at ``partner_base``) on ``target_anchor``'s side.

    The waypoints, the effector's stop on the partner's back, and where the
    fingertips aim.

    None when the partner's facing, shoulder anchors or side are unknown.
    """
    if partner_base is None:
        return None
    forward = figure_forward(partner)
    joint = _anchor_bone_offset(partner, target_anchor)
    left = _anchor_bone_offset(partner, "l_shoulder")
    right = _anchor_bone_offset(partner, "r_shoulder")
    side = _side_from_name(target_anchor)
    if forward is None or joint is None or left is None or right is None or side not in ("left", "right"):
        return None
    outward = (forward[2], 0.0, -forward[0]) if side == "left" else (-forward[2], 0.0, forward[0])
    spine = (partner_base[0] + (left[0] + right[0]) / 2.0, partner_base[1] + joint[1] - WRAP_DROP, partner_base[2] + (left[2] + right[2]) / 2.0)

    def _at(point: tuple[float, float]) -> Vector3:
        lateral, back = point
        return (spine[0] + outward[0] * lateral - forward[0] * back, spine[1], spine[2] + outward[2] * lateral - forward[2] * back)

    return [_at(point) for point in WRAP_SIDE_POINTS], _at(WRAP_BACK_POINT), _at(WRAP_FINGER_POINT)


def figure_forward(profile: FigureRigProfile) -> Vector3 | None:
    """Horizontal unit vector a figure faces, from its left/right shoulders (then knees, then feet).

    Left minus right, crossed with up; a Genesis figure at rest faces +Z.
    None when no pair resolves.
    """
    for left, right in _FORWARD_ANCHOR_PAIRS:
        l_offset = _anchor_bone_offset(profile, left)
        r_offset = _anchor_bone_offset(profile, right)
        if l_offset is None or r_offset is None:
            continue
        across = (l_offset[0] - r_offset[0], 0.0, l_offset[2] - r_offset[2])
        length = _vec3_length(across)
        if length < 1e-6:
            continue
        return (-across[2] / length, 0.0, across[0] / length)
    return None


def rotate_about_y(v: Vector3, degrees: float) -> Vector3:
    """Rotate ``v`` by ``degrees`` about +Y (right-handed: +90 turns +Z into +X), as a figure's Y rotation does."""
    radians = math.radians(degrees)
    c, s = math.cos(radians), math.sin(radians)
    return (v[0] * c + v[2] * s, v[1], -v[0] * s + v[2] * c)


def _yaw_of(direction: Vector3) -> float:
    return math.degrees(math.atan2(direction[0], direction[2]))


def _wrap_degrees(degrees: float) -> float:
    wrapped = (degrees + 180.0) % 360.0 - 180.0
    return 180.0 if wrapped == -180.0 else wrapped


def rotate_rig_profile(profile: FigureRigProfile, degrees: float) -> FigureRigProfile:
    """A copy of ``profile`` with the figure turned ``degrees`` about its origin.

    Bone world positions (and, without a figure position, local offsets) are rotated.
    """
    pivot = profile.figure_position or (0.0, 0.0, 0.0)

    def _turn(point: Vector3 | None) -> Vector3 | None:
        return None if point is None else _vec3_add(pivot, rotate_about_y(_vec3_sub(point, pivot), degrees))

    bones = [
        replace(
            bone,
            world_position=_turn(bone.world_position),
            local_position=(
                rotate_about_y(bone.local_position, degrees)
                if profile.figure_position is None and bone.local_position is not None
                else bone.local_position
            ),
        )
        for bone in profile.bones
    ]
    return replace(profile, bones=bones, metadata={**profile.metadata, "facing_yaw_degrees": degrees})


# Closer than this (cm, horizontally), a look-only partner faces back along its anchor's forward instead of toward its origin.
LOOK_TOWARD_MIN_DISTANCE = 1.0


def plan_facing(plan: "InteractionPlan", rig_profiles: dict[str, FigureRigProfile]) -> dict[str, FacingAssignment]:
    """Which figures to turn to face a partner.

    A pair qualifies when both have a ``LookAtTarget``. When a hand/foot
    target links them (the hug, kiss, handshake and fight recipes) the
    partner turns to face back along its anchor's forward and
    ``build_pose_patch`` stages it in front. Lookers no limb target links
    (face_each_other) pair up in actor order and the partner just turns in
    place toward its anchor. The pair's earlier actor (in ``plan.actors``)
    keeps its orientation; the other turns to face it. A figure turns at most
    once.
    """
    lookers: set[int] = set()
    for constraint in plan.constraints:
        if isinstance(constraint, LookAtTarget):
            profile = _lookup_rig_profile(rig_profiles, constraint.figure_label)
            if profile is not None:
                lookers.add(id(profile))

    def _actor_order(label: str) -> float:
        profile = _lookup_rig_profile(rig_profiles, label)
        for index, actor in enumerate(plan.actors):
            if _lookup_rig_profile(rig_profiles, actor) is profile:
                return float(index)
        return math.inf

    facing: dict[str, FacingAssignment] = {}
    involved: set[int] = set()
    for constraint in plan.constraints:
        if not isinstance(constraint, (HandTarget, FootTarget)) or not constraint.target_figure or not constraint.target_anchor:
            continue
        source = _lookup_rig_profile(rig_profiles, constraint.figure_label)
        target = _lookup_rig_profile(rig_profiles, constraint.target_figure)
        if source is None or target is None or source is target or id(source) not in lookers or id(target) not in lookers:
            continue
        source_first = _actor_order(constraint.figure_label) <= _actor_order(constraint.target_figure)
        anchor_label, partner_label = (
            (constraint.figure_label, constraint.target_figure) if source_first else (constraint.target_figure, constraint.figure_label)
        )
        anchor_profile, partner_profile = (source, target) if source_first else (target, source)
        if id(partner_profile) in involved:
            continue
        anchor_forward = figure_forward(anchor_profile)
        partner_forward = figure_forward(partner_profile)
        if anchor_forward is None or partner_forward is None:
            continue
        yaw = _wrap_degrees(_yaw_of(_vec3_scale(anchor_forward, -1.0)) - _yaw_of(partner_forward))
        facing[partner_label] = FacingAssignment(anchor=anchor_label, yaw_degrees=yaw)
        involved.update((id(partner_profile), id(anchor_profile)))

    # Look-only pairs (face_each_other): lookers no limb target links, paired
    # in actor order. Nothing stages them, so the partner turns in place toward
    # its anchor's origin (or, when the origins coincide, to face back along
    # the anchor's forward).
    pending: list[tuple[str, FigureRigProfile]] = []
    for actor in plan.actors:
        profile = _lookup_rig_profile(rig_profiles, actor)
        if profile is None or id(profile) not in lookers or id(profile) in involved or any(p is profile for _, p in pending):
            continue
        pending.append((actor, profile))
    for i in range(0, len(pending) - 1, 2):
        (anchor_label, anchor_profile), (partner_label, partner_profile) = pending[i], pending[i + 1]
        partner_forward = figure_forward(partner_profile)
        if partner_forward is None:
            continue
        toward: Vector3 | None = None
        if anchor_profile.figure_position is not None and partner_profile.figure_position is not None:
            gap = _vec3_sub(anchor_profile.figure_position, partner_profile.figure_position)
            if math.hypot(gap[0], gap[2]) >= LOOK_TOWARD_MIN_DISTANCE:
                toward = (gap[0], 0.0, gap[2])
        if toward is None:
            anchor_forward = figure_forward(anchor_profile)
            if anchor_forward is None:
                continue
            toward = _vec3_scale(anchor_forward, -1.0)
        facing[partner_label] = FacingAssignment(anchor=anchor_label, yaw_degrees=_wrap_degrees(_yaw_of(toward) - _yaw_of(partner_forward)))
    return facing


def _apply_facing(rig_profiles: dict[str, FigureRigProfile], facing: dict[str, FacingAssignment]) -> dict[str, FigureRigProfile]:
    """``rig_profiles`` with each faced partner's profile (under every key it has) replaced by its turned copy."""
    turned = dict(rig_profiles)
    for partner_label, assignment in facing.items():
        original = _lookup_rig_profile(rig_profiles, partner_label)
        if original is None:
            continue
        rotated = rotate_rig_profile(original, assignment.yaw_degrees)
        for key, profile in rig_profiles.items():
            if profile is original:
                turned[key] = rotated
    return turned


def _limb_geometry(profile: FigureRigProfile, effector_bone: str, base: Vector3 | None) -> tuple[Vector3, Vector3, float] | None:
    """Limb geometry with the figure origin at ``base``: ``(chain_root, reach_root, reach)``.

    ``chain_root`` is the alignment chain's first bone (where the standoff pull
    aims, as in ``_surface_contact_point``); ``reach_root`` starts the limb's
    last two long segments (the upper-arm or thigh joint) and ``reach`` is the
    path length from it to the effector. Torso links (spine -> collar) barely
    add reach, so counting them would stage partners out of range.
    """
    if base is None:
        return None
    chain = profile.suggest_primary_chain(effector_bone)
    names = [*_alignment_chain_names(profile, chain), effector_bone] if chain is not None else []
    if len(names) < 2:
        return None
    offsets = [profile.bone_offset(name) for name in names]
    points = [offset for offset in offsets if offset is not None]
    if len(points) != len(offsets):
        return None
    reach = 0.0
    long_segments = 0
    root_index = 0
    for i in range(len(points) - 1, 0, -1):
        if long_segments >= 2:
            break
        segment = _vec3_length(_vec3_sub(points[i], points[i - 1]))
        reach += segment
        if segment >= _LIMB_SEGMENT_MIN_LENGTH:
            long_segments += 1
        root_index = i - 1
    return _vec3_add(base, points[0]), _vec3_add(base, points[root_index]), reach


def _meeting_point(root_a: Vector3, length_a: float, root_b: Vector3, length_b: float) -> Vector3:
    """Where two hands reaching for each other meet: between both shoulders, ``_MEETING_DROP_FRACTION`` of the mean reach below them."""
    middle = _midpoint_vec3(root_a, root_b)
    return (middle[0], middle[1] - _MEETING_DROP_FRACTION * ((length_a + length_b) / 2.0), middle[2])


@dataclass
class InteractionPosePatch:
    """A coarse figure-placement patch built from a prepared interaction.

    Figure translations, plus yaw turns (degrees added to a figure's Y
    rotation) for figures staged to face a partner.
    """

    figure_positions: dict[str, Vector3] = field(default_factory=dict)
    unresolved_targets: list[ResolvedInteractionTarget] = field(default_factory=list)
    diagnostics: dict[str, object] = field(default_factory=dict)
    figure_yaw_degrees: dict[str, float] = field(default_factory=dict)

    def apply(self, scene: Any) -> None:
        for figure_label, yaw in self.figure_yaw_degrees.items():
            if abs(yaw) < 1e-6:
                continue
            skeleton = scene.find_skeleton_by_label(figure_label)
            if not hasattr(skeleton, "local_euler") or not hasattr(skeleton, "set_rotation"):
                raise TypeError(f"Cannot turn {figure_label} to face its partner: skeleton has no local_euler/set_rotation")
            x, y, z = skeleton.local_euler or (0.0, 0.0, 0.0)  # a property on DazNode
            skeleton.set_rotation(x, y + yaw, z)
        for figure_label, position in self.figure_positions.items():
            skeleton = scene.find_skeleton_by_label(figure_label)
            skeleton.set_position(*position)

    def to_dict(self) -> dict:
        return {
            "figure_positions": {label: list(position) for label, position in self.figure_positions.items()},
            "figure_yaw_degrees": dict(self.figure_yaw_degrees),
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
    # Turned partners' profiles replace the originals before resolution.
    facing = plan_facing(plan, rig_profiles)
    profiles = _apply_facing(rig_profiles, facing)
    validation_issues = plan.validate(profiles)
    resolved_targets = plan.resolve_targets(profiles)
    diagnostics: dict[str, object] = {
        "recipe_kind": recipe.kind,
        "actor_count": len(recipe.actors),
        "constraint_count": len(recipe.constraints),
        "resolved_target_count": len(resolved_targets),
        "faced_figure_count": len(facing),
    }
    return PreparedInteractionRecipe(
        recipe=recipe,
        plan=plan,
        resolved_targets=resolved_targets,
        rig_profiles=profiles,
        validation_issues=validation_issues,
        diagnostics=diagnostics,
        facing=facing,
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
            # B's mirrored hand on A's opposite shoulder: straight ahead once they face each other.
            HandTarget(actor_b, "l_hand" if _side_from_name(a_anchor) == "right" else "r_hand", target_figure=actor_a, target_anchor="r_shoulder" if _side_from_name(a_anchor) == "right" else "l_shoulder"),
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
    """Build a mutual arms-around-each-other embrace preset for two figures.

    Each arm wraps the partner's side (toward its far shoulder) and the hand
    rests on its upper back (``HandTarget.wrap``).
    """

    a_far_shoulder = "l_shoulder" if _side_from_name(a_anchor) == "right" else "r_shoulder"
    b_far_shoulder = "l_shoulder" if _side_from_name(b_anchor) == "right" else "r_shoulder"
    return InteractionRecipe(
        kind="hug",
        actors=[actor_a, actor_b],
        constraints=[
            LookAtTarget(actor_a, "head", (0.0, 0.0, 0.0)),
            LookAtTarget(actor_b, "head", (0.0, 0.0, 0.0)),
            HandTarget(actor_a, a_anchor, target_figure=actor_b, target_anchor=a_far_shoulder, wrap=True),
            HandTarget(actor_b, b_anchor, target_figure=actor_a, target_anchor=b_far_shoulder, wrap=True),
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
        (("shoulder", "shldr", "clavicle", "upper_arm"), {"x": (-120.0, 120.0), "y": (-120.0, 120.0), "z": (-140.0, 140.0)}),
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
            figure_position=_as_tuple3(skel_data.get("position")),
        )
        profiles[label] = profile
        if name and name != label:
            profiles[name] = profile
    return profiles


def build_rig_profile(skeleton: "DazSkeleton") -> FigureRigProfile:
    """Inspect a live DAZ skeleton and build a solver-friendly rig profile."""

    figure_label = skeleton.label or skeleton._identifier.value
    bones: list[BoneProfile] = []
    figure_position: Vector3 | None = None
    if hasattr(skeleton, "bone_metadata"):
        raw_bones = skeleton.bone_metadata()
        # Bone world positions only become figure-relative offsets with the
        # figure's own world position (one extra call).
        figure_position = _as_tuple3(getattr(skeleton, "position", None))
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
        figure_position=figure_position,
    )
