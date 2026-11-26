"""Staging geometry: contact points, facing planner, wrap paths, limb reach."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from ._interaction_profile import (
    ANCHOR_SURFACE_RADIUS,
    FigureRigProfile,
    FootTarget,
    HandTarget,
    LookAtTarget,
    ResolvedInteractionTarget,
    Vector3,
    _alignment_chain_names,
    _lookup_rig_profile,
    _side_from_name,
    _vec3_add,
    _vec3_length,
    _vec3_midpoint,
    _vec3_scale,
    _vec3_sub,
)

if TYPE_CHECKING:
    from ._interaction_recipes import InteractionPlan


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
    middle = _vec3_midpoint(root_a, root_b)
    return (middle[0], middle[1] - _MEETING_DROP_FRACTION * ((length_a + length_b) / 2.0), middle[2])
