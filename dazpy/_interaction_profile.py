"""Figure rig profiles: bone/chain/anchor model, interaction targets, rig building."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, TYPE_CHECKING
from collections.abc import Sequence

from .math3 import Vec3

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
    "hip",
    "elbow",
    "hand",
    "knee",
    "foot",
    "custom",
]


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


def _lookup_rig_profile(rig_profiles: dict[str, FigureRigProfile], label: str | None) -> FigureRigProfile | None:
    if label is None:
        return None
    if label in rig_profiles:
        return rig_profiles[label]
    compact = _compact_name(label)
    for key, profile in rig_profiles.items():
        if _compact_name(key) == compact:
            return profile
    return None


# ── tuple vector helpers ─────────────────────────────────────────────────────
# Profiles, targets and solver state keep points as plain ``Vector3`` tuples
# (they serialise straight to JSON); the arithmetic itself is math3.Vec3's.


def _vec3(v: Vector3) -> Vec3:
    return Vec3(v[0], v[1], v[2])


def _tuple3(v: Vec3) -> Vector3:
    return (v.x, v.y, v.z)


def _vec3_add(a: Vector3, b: Vector3) -> Vector3:
    return _tuple3(_vec3(a) + _vec3(b))


def _vec3_add_optional(a: Vector3 | None, b: Vector3 | None) -> Vector3 | None:
    if a is None:
        return b
    if b is None:
        return a
    return _vec3_add(a, b)


def _vec3_sub(a: Vector3, b: Vector3) -> Vector3:
    return _tuple3(_vec3(a) - _vec3(b))


def _vec3_scale(v: Vector3, scale: float) -> Vector3:
    return _tuple3(_vec3(v) * scale)


def _vec3_dot(a: Vector3, b: Vector3) -> float:
    return _vec3(a).dot(_vec3(b))


def _vec3_length(v: Vector3) -> float:
    return _vec3(v).length()


def _vec3_midpoint(a: Vector3, b: Vector3) -> Vector3:
    return _tuple3((_vec3(a) + _vec3(b)) / 2.0)


def _vec3_average(points: list[Vector3] | None) -> Vector3 | None:
    if not points:
        return None
    total = Vec3.zero()
    for point in points:
        total = total + _vec3(point)
    return _tuple3(total / len(points))


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
    "hip": 9.0,
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
    def from_dict(cls, data: dict) -> AxisLimit:
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
    def from_dict(cls, data: dict) -> BoneProfile:
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
            return _vec3_sub(bone.world_position, self.figure_position)
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
        for _role, side, tokens in candidates:
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
        for _anchor_name, role, side, tokens in candidates:
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
        # Fallbacks are tried last: Genesis 9 has no chest-named bone; its
        # spine3 sits where Genesis 8's chestLower does.
        fallback: dict[str, tuple[str, ...]] = {"chest": ("spine3",)}
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
            # The hip joint is the thigh's origin (G9 l_thigh, G8 lThighBend).
            ("l_hip", "hip", "left", ("thigh",)),
            ("r_hip", "hip", "right", ("thigh",)),
            ("l_foot", "foot", "left", ("foot", "toe", "ankle")),
            ("r_foot", "foot", "right", ("foot", "toe", "ankle")),
        ]
        for key, role, side, tokens in patterns:
            candidates = [(role, side, tokens)]
            if key in preferred:
                candidates.insert(0, (role, side, preferred[key]))
            if key in fallback:
                candidates.append((role, side, fallback[key]))
            bone = self._find_terminal_bone(candidates)
            if bone is None:
                continue
            anchors[key] = InteractionAnchor(name=key, bone_name=bone.name, role=role, side=side)
        return anchors

    def anchor(self, name: str) -> InteractionAnchor | None:
        return self.anchor_map().get(name)

    def anchor_names(self) -> list[str]:
        return sorted(self.anchor_map().keys())

    def anchor_or_bone(self, name: str) -> str | None:
        """Resolve an anchor key (``pelvis``) or a raw bone name (``hip``) to a bone name."""
        anchor = self.anchor(name)
        if anchor is not None:
            return anchor.bone_name
        return name if name in self._index else None

    def require_anchor(self, name: str) -> InteractionAnchor:
        anchor = self.anchor(name)
        if anchor is None:
            raise KeyError(f"Anchor not found in rig profile: {name!r}")
        return anchor

    def resolve_anchor_target(
        self,
        target: AnchorTarget,
        rig_profiles: dict[str, FigureRigProfile] | None = None,
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
            target_point = _vec3_add_optional(target_point, target.offset)

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
    def from_dict(cls, data: dict) -> FigureRigProfile:
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


def build_rig_profiles_from_snapshot(snapshot: list[dict]) -> dict[str, FigureRigProfile]:
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


def build_rig_profile(skeleton: DazSkeleton) -> FigureRigProfile:
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
