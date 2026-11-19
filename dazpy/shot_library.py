"""Common cinematic shots, coverage and continuity rules on top of :mod:`dazpy.shots`.

Every builder here is pure: it takes actor root positions (``Vec3``, the
floor point under a standing figure, as :meth:`~dazpy.DazNode.position`
reports it) and returns :class:`~dazpy.shots.Shot` /
:class:`~dazpy.shots.CoveragePlan` models. :func:`~dazpy.shots.apply_shot`
(or :func:`apply_coverage`) puts them into a live scene; pass the same
*positions* mapping as its ``subjects``.

What it covers:

* **Shot types** -- :func:`establishing`, :func:`master`, :func:`two_shot`,
  :func:`single` (medium / close-up / ... of one actor), :func:`insert`,
  :func:`pov`, :func:`over_the_shoulder`, and :func:`shot_reverse_shot`.
* **The 180-degree rule** -- a :class:`LineOfAction` between two actors
  picks the side every camera stays on; :func:`check_axis` reports a camera
  that crosses it and :func:`check_thirty_degree` a jump cut. Shot/reverse
  pairs built on one line keep eyelines matched (A looks screen-right,
  B screen-left, or the mirror).
* **Composition** -- :func:`headroom_anchor` (eyes on the upper third) and
  :func:`lead_room` (look room in front of a subject's gaze).
* **Camera moves** -- :func:`push_in` / :func:`pull_out` between shot
  sizes, :func:`arc` around a subject, and :func:`camera_move` (dolly,
  truck, pedestal, crane, pan, tilt, handheld) from a camera's current pose.
* **Focus** -- :func:`rack_focus` / :func:`with_rack_focus`.
* **Coverage** -- :func:`subject_coverage` presets for one actor,
  :func:`dialogue_coverage` for two, and :func:`conversation` cutting a
  list of :class:`DialogueBeat` between them.
* **Naming** -- :func:`shot_name` gives every shot a consistent id that is
  also a valid scene-recipe key.

Units are DAZ native: centimetres, Y-up, degrees, timeline frames.
"""

from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Mapping, Optional, Sequence as Seq, Tuple, Union

from .math3 import Quat, Vec3
from ._shot_geometry import spherical_offset
from .shots import (
    DEFAULT_ASPECT, DEFAULT_FRAME_WIDTH_MM, SHOT_SIZES,
    CameraKeyframe, CoveragePlan, FocusKey, FocusPull, Framing, GazeBeat, Keyframed, Lens, Orbit,
    Placement, Sequence, Shot, Storyboard, apply_shot, framing_distance, framing_transform,
)

if TYPE_CHECKING:
    from ._camera import DazCamera
    from ._scene import DazScene

Positions = Mapping[str, Vec3]
Rotation = Tuple[float, float, float]

#: Eye height above a standing Genesis-scale actor's root (cm); the
#: ``close_up`` anchor of :data:`~dazpy.shots.SHOT_SIZES`.
EYE_HEIGHT_CM = 160.0

#: Over-the-shoulder camera offsets from the foreground actor's head (cm):
#: behind them (away from the subject), out to the camera side, below eyes.
OTS_BACK_CM = 60.0
OTS_SIDE_CM = 35.0
OTS_DROP_CM = 10.0

#: How far a clean single swings off the partner's eyeline toward the camera side.
SINGLE_OFFSET_DEG = 25.0

#: Default lenses per shot family (mm).
DEFAULT_LENSES: Mapping[str, float] = {
    "establishing": 24.0, "master": 35.0, "two_shot": 50.0, "single": 85.0, "ots": 50.0,
    "pov": 35.0, "insert": 100.0, "move": 50.0,
}

#: Shot-id abbreviations, per kind or shot size.
SHOT_ABBREVIATIONS: Mapping[str, str] = {
    "establishing": "EST", "master": "MST", "two_shot": "2S", "ots": "OTS", "single": "SGL",
    "insert": "INS", "pov": "POV", "push_in": "PUSH", "pull_out": "PULL", "arc": "ARC", "move": "MOVE",
    "extreme_wide": "EWS", "wide": "WS", "full_body": "FS", "medium_wide": "MWS", "medium": "MS",
    "medium_close_up": "MCU", "close_up": "CU", "extreme_close_up": "ECU",
}

_UP = Vec3(0.0, 1.0, 0.0)
_KEY_MAX = 64


# ---- naming ---------------------------------------------------------------

def _slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9-]+", "-", str(text)).strip("-")
    return s or "x"


def shot_name(kind: str, subject: Optional[str] = None, over: Optional[str] = None, *,
              tag: Optional[str] = None, scene: Optional[Union[int, str]] = None,
              index: Optional[int] = None) -> str:
    """A consistent shot id: ``[SC<scene>_][<index>_]<ABBR>[_<tag>][_<subject>][_over_<over>]``.

    *kind* is a key of :data:`SHOT_ABBREVIATIONS` (a shot kind or size); any
    other string is used upper-cased. Names are reduced to ``[A-Za-z0-9-]``
    so the id is a valid scene-recipe key (at most 64 characters).

    Examples: ``shot_name("ots", "bob", over="alice")`` -> ``"OTS_bob_over_alice"``;
    ``shot_name("close_up", "anna", scene=3, index=12)`` -> ``"SC3_012_CU_anna"``.
    """
    parts = []
    if scene is not None:
        parts.append(f"SC{_slug(scene)}")
    if index is not None:
        parts.append(f"{index:03d}")
    parts.append(SHOT_ABBREVIATIONS.get(kind) or _slug(kind).upper())
    if tag:
        parts.append(_slug(tag))
    if subject:
        parts.append(_slug(subject))
    if over:
        parts += ["over", _slug(over)]
    return "_".join(parts)[:_KEY_MAX]


# ---- geometry helpers -----------------------------------------------------

def _flat(v: Vec3) -> Vec3:
    return Vec3(v.x, 0.0, v.z)


def _azimuth(direction: Vec3) -> float:
    """Azimuth (see :func:`~dazpy._shot_geometry.spherical_offset`) of a horizontal direction."""
    return math.degrees(math.atan2(direction.x, direction.z))


def _eye(root: Vec3, eye_height: float = EYE_HEIGHT_CM) -> Vec3:
    return Vec3(root.x, root.y + eye_height, root.z)


def _screen_right(position: Vec3, aim: Vec3) -> Optional[Vec3]:
    right = (aim - position).cross(_UP)
    return right.normalize() if right.length() > 1e-9 else None


#: Horizontal screen positions (-1 = left edge, +1 = right edge) of the
#: rule-of-thirds and golden-section verticals.
THIRD_X = 1.0 / 3.0
GOLDEN_X = 1.0 - 2.0 * (1.0 - 2.0 / (1.0 + math.sqrt(5.0)))  # ~0.236: a 0.382 / 0.618 split


def compose_aim(position: Vec3, target: Vec3, screen_x: float, focal_length: float, *,
                frame_width_mm: float = DEFAULT_FRAME_WIDTH_MM) -> Vec3:
    """The aim point that puts *target* at horizontal screen position *screen_x*.

    *screen_x* runs from ``-1`` (left edge) to ``+1`` (right edge); ``0`` is
    centred, :data:`THIRD_X` the right third, :data:`GOLDEN_X` the right
    golden section. The camera turns, it does not move.
    """
    right = _screen_right(position, target)
    if right is None or not screen_x:
        return target
    half_width = position.distance(target) * frame_width_mm / focal_length / 2.0
    return target - right * (screen_x * half_width)


def _lens(lens: Optional[Union[Lens, float]], family: str) -> Lens:
    if lens is None:
        return Lens(focal_length=DEFAULT_LENSES[family])
    return Lens(focal_length=float(lens)) if isinstance(lens, (int, float)) else lens


def _pos(positions: Positions, key: str) -> Vec3:
    try:
        return positions[key]
    except KeyError:
        raise ValueError(f"no position for {key!r}") from None


@dataclass(frozen=True)
class LineOfAction:
    """The 180-degree line between actors *a* and *b*, and the side cameras keep to.

    Args:
        a, b: Actor keys.
        a_pos, b_pos: Their root positions (only X/Z matter).
        side: ``+1`` or ``-1`` -- which half-plane the cameras stand in.
            ``+1`` is to *a*'s right as *a* faces *b* (``+X`` when
            *a*->*b* runs along ``-Z``).
    """

    a: str
    b: str
    a_pos: Vec3
    b_pos: Vec3
    side: int = 1

    def __post_init__(self) -> None:
        if self.a == self.b:
            raise ValueError("a line of action needs two different actors")
        if self.side not in (1, -1):
            raise ValueError("side must be +1 or -1")
        if _flat(self.b_pos - self.a_pos).length() < 1e-6:
            raise ValueError(f"{self.a!r} and {self.b!r} stand on the same spot; no line of action")

    @classmethod
    def between(cls, positions: Positions, a: str, b: str, side: int = 1) -> "LineOfAction":
        """The line between keys *a* and *b* of *positions*."""
        return cls(a, b, _pos(positions, a), _pos(positions, b), side)

    @property
    def direction(self) -> Vec3:
        """Unit horizontal direction from *a* to *b*."""
        return _flat(self.b_pos - self.a_pos).normalize()

    @property
    def normal(self) -> Vec3:
        """Unit horizontal direction from the line toward the camera side."""
        d = self.direction
        return Vec3(-d.z, 0.0, d.x) * self.side

    @property
    def midpoint(self) -> Vec3:
        return (self.a_pos + self.b_pos) * 0.5

    @property
    def separation(self) -> float:
        return _flat(self.b_pos - self.a_pos).length()

    def flipped(self) -> "LineOfAction":
        """The same line with cameras on the other side (a deliberate cross)."""
        return replace(self, side=-self.side)

    def position(self, key: str) -> Vec3:
        if key == self.a:
            return self.a_pos
        if key == self.b:
            return self.b_pos
        raise ValueError(f"{key!r} is not on this line (actors: {self.a!r}, {self.b!r})")

    def other(self, key: str) -> str:
        self.position(key)
        return self.b if key == self.a else self.a

    def side_of(self, point: Vec3, tolerance_cm: float = 1.0) -> int:
        """``+1`` / ``-1`` for the half-plane *point* is in, ``0`` within *tolerance_cm* of the line."""
        d = self.direction
        rel = _flat(point - self.a_pos)
        offset = d.x * rel.z - d.z * rel.x  # signed distance; > 0 on the side=+1 half-plane
        if abs(offset) <= tolerance_cm:
            return 0
        return 1 if offset > 0 else -1


# ---- composition ----------------------------------------------------------

def headroom_anchor(size: str, eye_height: float = EYE_HEIGHT_CM) -> float:
    """Aim height (cm above the root) that puts a standing actor's eyes on the upper third.

    Pass it as :attr:`~dazpy.shots.Framing.anchor_cm`. The frame height at a
    size's fitted distance is its :data:`~dazpy.shots.SHOT_SIZES` fit height,
    so the eyes sit a sixth of that above the frame centre.
    """
    return max(0.0, eye_height - SHOT_SIZES[size][0] / 6.0)


def lead_room(camera_position: Vec3, aim: Vec3, facing: Vec3, threshold: float = 0.15) -> str:
    """The :data:`~dazpy.shots.COMPOSITIONS` value that leaves room in front of a gaze.

    A subject looking screen-right goes on the left third and vice versa;
    one looking (nearly) into or away from the lens stays centred.

    Args:
        camera_position, aim: The camera pose.
        facing: Direction the subject looks (any length; only X/Z matter).
        threshold: Minimum sideways component (of the unit facing) for an off-centre composition.
    """
    right = _screen_right(camera_position, aim)
    f = _flat(facing)
    if right is None or f.length() < 1e-9:
        return "center"
    lateral = f.normalize().dot(right)
    if lateral > threshold:
        return "left_third"
    if lateral < -threshold:
        return "right_third"
    return "center"


#: Width (cm) added to two actors' separation for their bodies when fitting a two-shot.
BODY_WIDTH_CM = 60.0


def _fit_distance(size: str, separation_cm: float, focal_length: float, frame_width_mm: float,
                  aspect: float) -> Optional[float]:
    """The distance that fits two actors *separation_cm* apart across the frame,
    or ``None`` when the size's own fitted distance already does (which keeps
    the shot recipe-expressible)."""
    by_width = (separation_cm + BODY_WIDTH_CM) * focal_length / frame_width_mm
    by_size = framing_distance(size, focal_length, frame_width_mm=frame_width_mm, aspect=aspect)
    return by_width if by_width > by_size else None


# ---- shot types -----------------------------------------------------------

def _side_framing(line: LineOfAction, family: str, size: str, *, lens: Optional[Union[Lens, float]],
                  elevation_deg: Optional[float], id: Optional[str], frame_range: Optional[Tuple[int, int]],
                  frame_width_mm: float, aspect: float, **shot_kw: Any) -> Shot:
    ln = _lens(lens, family)
    framing = Framing(
        subjects=(line.a, line.b), size=size, azimuth_deg=_azimuth(line.normal), elevation_deg=elevation_deg,
        distance_cm=_fit_distance(size, line.separation, ln.focal_length, frame_width_mm, aspect),
    )
    return Shot(id=id or shot_name(family, f"{line.a}-{line.b}"), camera=framing, lens=ln,
                frame_range=frame_range, **shot_kw)


def establishing(line: LineOfAction, *, size: str = "extreme_wide", elevation_deg: float = 10.0,
                 lens: Optional[Union[Lens, float]] = None, id: Optional[str] = None,
                 frame_range: Optional[Tuple[int, int]] = None, frame_width_mm: float = DEFAULT_FRAME_WIDTH_MM,
                 aspect: float = DEFAULT_ASPECT) -> Shot:
    """A wide, slightly high shot of both actors from the camera side of the line."""
    return _side_framing(line, "establishing", size, lens=lens, elevation_deg=elevation_deg, id=id,
                         frame_range=frame_range, frame_width_mm=frame_width_mm, aspect=aspect)


def master(line: LineOfAction, *, size: str = "wide", lens: Optional[Union[Lens, float]] = None,
           id: Optional[str] = None, frame_range: Optional[Tuple[int, int]] = None,
           frame_width_mm: float = DEFAULT_FRAME_WIDTH_MM, aspect: float = DEFAULT_ASPECT) -> Shot:
    """The master: both actors, perpendicular to the line, at eye level."""
    return _side_framing(line, "master", size, lens=lens, elevation_deg=None, id=id,
                         frame_range=frame_range, frame_width_mm=frame_width_mm, aspect=aspect)


def two_shot(line: LineOfAction, *, size: str = "medium_wide", lens: Optional[Union[Lens, float]] = None,
             id: Optional[str] = None, frame_range: Optional[Tuple[int, int]] = None,
             frame_width_mm: float = DEFAULT_FRAME_WIDTH_MM, aspect: float = DEFAULT_ASPECT) -> Shot:
    """A two-shot: both actors at *size* (widened if they stand too far apart to fit)."""
    return _side_framing(line, "two_shot", size, lens=lens, elevation_deg=None, id=id,
                         frame_range=frame_range, frame_width_mm=frame_width_mm, aspect=aspect)


def single(line: LineOfAction, subject: str, *, size: str = "medium_close_up",
           lens: Optional[Union[Lens, float]] = None, offset_deg: float = SINGLE_OFFSET_DEG,
           angle: str = "eye_level", headroom: bool = False, lead: bool = True,
           id: Optional[str] = None, frame_range: Optional[Tuple[int, int]] = None) -> Shot:
    """A clean single of *subject*, from near their partner's eyeline on the camera side.

    Args:
        line: The line of action; *subject* must be on it.
        size: Shot size.
        offset_deg: How far the camera swings off the partner's eyeline
            toward the camera side (0 = straight down the eyeline).
        angle: Named camera angle.
        headroom: Aim with :func:`headroom_anchor` (eyes on the upper third).
        lead: Compose with :func:`lead_room` toward the partner.
    """
    to_partner = _flat(line.position(line.other(subject)) - line.position(subject)).normalize()
    a = math.radians(offset_deg)
    direction = to_partner * math.cos(a) + line.normal * math.sin(a)
    composition = lead_room(direction, Vec3(0.0, 0.0, 0.0), to_partner) if lead else "center"
    framing = Framing(subjects=(subject,), size=size, angle=angle, azimuth_deg=_azimuth(direction),
                      composition=composition, anchor_cm=headroom_anchor(size) if headroom else None)
    return Shot(id=id or shot_name(size, subject), camera=framing, lens=_lens(lens, "single"),
                frame_range=frame_range)


def over_the_shoulder(line: LineOfAction, foreground: str, subject: str, *,
                      lens: Optional[Union[Lens, float]] = None, back_cm: float = OTS_BACK_CM,
                      side_cm: float = OTS_SIDE_CM, drop_cm: float = OTS_DROP_CM,
                      eye_height: float = EYE_HEIGHT_CM, compose: bool = True,
                      frame_width_mm: float = DEFAULT_FRAME_WIDTH_MM, id: Optional[str] = None,
                      frame_range: Optional[Tuple[int, int]] = None) -> Shot:
    """Over *foreground*'s shoulder onto *subject*, from the camera side of the line.

    The camera stands *back_cm* behind the foreground actor's head and
    *side_cm* out toward the camera side, a little below eye level. With
    *compose*, the subject's eyes land on the third of the frame opposite
    the foreground shoulder.
    """
    if {foreground, subject} != {line.a, line.b}:
        raise ValueError(f"over_the_shoulder needs the line's two actors, got {foreground!r} and {subject!r}")
    ln = _lens(lens, "ots")
    fg = line.position(foreground)
    behind = _flat(fg - line.position(subject)).normalize()
    head = _eye(fg, eye_height - drop_cm)
    position = head + behind * back_cm + line.normal * side_cm
    target = _eye(line.position(subject), eye_height)
    aim = target
    right = _screen_right(position, target)
    if compose and right is not None:
        # The foreground shoulder is on the -normal side of the camera; the subject goes opposite.
        screen_side = 1.0 if line.normal.dot(right) > 0 else -1.0
        aim = compose_aim(position, target, screen_side * THIRD_X, ln.focal_length, frame_width_mm=frame_width_mm)
    return Shot(id=id or shot_name("ots", subject, over=foreground),
                camera=Placement(position=position, look_at=aim), lens=ln, frame_range=frame_range)


def shot_reverse_shot(line: LineOfAction, *, lens: Optional[Union[Lens, float]] = None,
                      frame_ranges: Optional[Tuple[Tuple[int, int], Tuple[int, int]]] = None,
                      **ots_kw: Any) -> Tuple[Shot, Shot]:
    """The OTS pair: onto *b* over *a*, and the reverse onto *a* over *b*, both on the line's side."""
    r1, r2 = frame_ranges if frame_ranges is not None else (None, None)
    return (over_the_shoulder(line, line.a, line.b, lens=lens, frame_range=r1, **ots_kw),
            over_the_shoulder(line, line.b, line.a, lens=lens, frame_range=r2, **ots_kw))


def pov(positions: Positions, viewer: str, target: Union[str, Vec3], *,
        lens: Optional[Union[Lens, float]] = None, eye_height: float = EYE_HEIGHT_CM,
        forward_cm: float = 10.0, id: Optional[str] = None,
        frame_range: Optional[Tuple[int, int]] = None) -> Shot:
    """*viewer*'s point of view: from their eyes toward *target* (an actor key's eyes, or a point)."""
    aim = _eye(_pos(positions, target), eye_height) if isinstance(target, str) else target
    eye = _eye(_pos(positions, viewer), eye_height)
    toward = aim - eye
    position = eye + toward.normalize() * forward_cm if toward.length() > forward_cm else eye
    label = target if isinstance(target, str) else None
    return Shot(id=id or shot_name("pov", viewer, tag=f"at-{label}" if label else None),
                camera=Placement(position=position, look_at=aim), lens=_lens(lens, "pov"),
                frame_range=frame_range)


def insert(point: Vec3, *, size: str = "extreme_close_up", azimuth_deg: float = 0.0,
           elevation_deg: float = 30.0, line: Optional[LineOfAction] = None,
           lens: Optional[Union[Lens, float]] = None, name: str = "detail", id: Optional[str] = None,
           frame_range: Optional[Tuple[int, int]] = None) -> Shot:
    """An insert: a tight shot of a detail at *point* (a prop, a hand), looking down at it.

    With *line*, the camera azimuth comes from the line's camera side
    (keeping the insert on the same side as the coverage) instead of *azimuth_deg*.
    """
    az = _azimuth(line.normal) if line is not None else azimuth_deg
    framing = Framing(subjects=(point,), size=size, azimuth_deg=az, elevation_deg=elevation_deg)
    return Shot(id=id or shot_name("insert", name), camera=framing, lens=_lens(lens, "insert"),
                frame_range=frame_range)


# ---- camera moves ---------------------------------------------------------

def _wrap_deg(a: float) -> float:
    a = math.fmod(a + 180.0, 360.0)
    return (a + 360.0 if a < 0 else a) - 180.0


def euler_from_quaternion(q: Union[Quat, Mapping[str, float]]) -> Rotation:
    """Camera Euler ``(x, y, z)`` degrees for Studio's world rotation quaternion.

    *q* holds DzQuat components: the ``{"x", "y", "z", "w"}`` dict
    :attr:`~dazpy.DazNode.rotation` returns, or a :class:`~dazpy.math3.Quat`
    built from it. DzQuat's ``(x, y, z)`` are the negation (conjugate) of
    :meth:`Quat.from_euler <dazpy.math3.Quat.from_euler>`'s for the same
    rotation (live-verified), so they are conjugated here. The result is in
    :func:`canonical_rotation` form.
    """
    if not isinstance(q, Quat):
        q = Quat.from_dict(q)
    return canonical_rotation(q.conjugate().to_euler(order="ZYX"))


def canonical_rotation(rotation: Rotation) -> Rotation:
    """The equivalent camera Euler with pitch (``x``) in ``[-90, 90]``.

    ``aimAt`` can leave a camera at e.g. ``(-177, 73, 180)``, which faces the
    same way as ``(3, 107, 0)``; adding a pan to the first form turns the
    wrong way. Uses the identity ``(x, y, z) == (x + 180, 180 - y, z + 180)``.
    """
    x, y, z = (_wrap_deg(float(a)) for a in rotation)
    if abs(x) > 90.0:
        x, y, z = _wrap_deg(x + 180.0), _wrap_deg(180.0 - y), _wrap_deg(z + 180.0)
    return (x, y, z)


def forward_from_rotation(rotation: Rotation) -> Vec3:
    """Unit view direction of a camera with Euler *rotation* (the inverse of ``look_at_euler``).

    A Studio camera's ``(x, y, z)`` rotation channels compose as
    ``Quat.from_euler(x, y, z, "ZYX")`` (live-verified, roll included).
    """
    m = Quat.from_euler(float(rotation[0]), float(rotation[1]), float(rotation[2]), order="ZYX").to_matrix()
    return Vec3(-m[0][2], -m[1][2], -m[2][2]).normalize()


def look_rotation(position: Vec3, aim: Vec3, roll_deg: float = 0.0) -> Rotation:
    """Camera Euler ``(x, y, z)`` that looks from *position* at *aim*, rolled
    *roll_deg* about the view axis -- a dutch angle. Positive roll tips the
    camera's top toward screen-left (:func:`camera_up`), as Studio's own
    ``ZRotate`` does on an unturned camera.

    Use it as :attr:`~dazpy.shots.Placement.rotation` when a shot needs roll,
    which ``look_at`` aiming can't express.
    """
    from ._shot_geometry import look_at_euler
    pitch, yaw, _ = look_at_euler(position, aim)
    if not roll_deg:
        return (pitch, yaw, 0.0)
    q = Quat.from_euler(pitch, yaw, 0.0, order="ZYX").multiply(Quat.from_euler(0.0, 0.0, roll_deg, order="ZYX"))
    return canonical_rotation(q.to_euler(order="ZYX"))


def camera_up(rotation: Rotation) -> Vec3:
    """Unit up direction (screen top) of a camera with Euler *rotation*."""
    m = Quat.from_euler(float(rotation[0]), float(rotation[1]), float(rotation[2]), order="ZYX").to_matrix()
    return Vec3(m[0][1], m[1][1], m[2][1]).normalize()


def aim_from_rotation(position: Vec3, rotation: Rotation, distance: float = 100.0) -> Vec3:
    """The point *distance* ahead of a camera at *position* with *rotation*."""
    return position + forward_from_rotation(rotation) * distance


#: Default *amount* per :func:`camera_move` kind (cm, or degrees for pan/tilt).
MOVE_DEFAULTS: Mapping[str, float] = {
    "dolly_in": 200.0, "dolly_out": 200.0, "truck_left": 100.0, "truck_right": 100.0,
    "pedestal_up": 50.0, "pedestal_down": 50.0, "crane_up": 100.0, "crane_down": 100.0,
    "pan_left": 45.0, "pan_right": 45.0, "tilt_up": 20.0, "tilt_down": 20.0, "handheld": 2.0,
}
CAMERA_MOVES: Tuple[str, ...] = tuple(MOVE_DEFAULTS)


def camera_move(kind: str, position: Vec3, rotation: Union[Rotation, Quat, Mapping[str, float]], *,
                start: int, end: int,
                amount: Optional[float] = None, lens: Optional[Union[Lens, float]] = None,
                id: Optional[str] = None, seed: int = 0, step: int = 3) -> Shot:
    """A camera move from the pose (*position*, *rotation*), keyed at *start* and *end*.

    *rotation* is Euler degrees, or Studio's world quaternion
    (:attr:`~dazpy.DazNode.rotation`'s dict; see :func:`euler_from_quaternion`).

    Kinds (see :data:`MOVE_DEFAULTS` for each default *amount*):

    * ``dolly_in`` / ``dolly_out`` -- along the horizontal view direction (cm).
    * ``truck_left`` / ``truck_right`` -- sideways (cm).
    * ``pedestal_up`` / ``pedestal_down``, ``crane_up`` / ``crane_down`` -- vertically
      (cm); a crane is a bigger pedestal by default.
    * ``pan_left`` / ``pan_right`` -- yaw (degrees); ``tilt_up`` / ``tilt_down`` -- pitch.
    * ``handheld`` -- seeded, repeatable jitter every *step* frames;
      *amount* is the position amplitude (cm), rotation jitter is half that in degrees.

    Every keyframe carries an explicit rotation, so the move never re-aims;
    *rotation* is first put in :func:`canonical_rotation` form.
    """
    if kind not in MOVE_DEFAULTS:
        raise ValueError(f"unknown camera move {kind!r}; valid: {', '.join(CAMERA_MOVES)}")
    if end <= start:
        raise ValueError("end must be > start")
    amt = MOVE_DEFAULTS[kind] if amount is None else float(amount)
    rot = euler_from_quaternion(rotation) if isinstance(rotation, (Quat, Mapping))         else canonical_rotation(rotation)  # type: ignore[arg-type]
    forward = forward_from_rotation(rot)
    flat = _flat(forward)
    track = flat.normalize() if flat.length() > 1e-6 else forward
    right = track.cross(_UP).normalize() if flat.length() > 1e-6 else Vec3(1.0, 0.0, 0.0)

    keys: List[CameraKeyframe]
    if kind == "handheld":
        rng = random.Random(seed)
        keys = [CameraKeyframe(start, position, rotation=rot)]
        frame = start + step
        while frame < end:
            jitter = Vec3(rng.uniform(-amt, amt), rng.uniform(-amt, amt), rng.uniform(-amt, amt))
            rj = amt * 0.5
            keys.append(CameraKeyframe(frame, position + jitter, rotation=(
                rot[0] + rng.uniform(-rj, rj), rot[1] + rng.uniform(-rj, rj), rot[2] + rng.uniform(-rj, rj))))
            frame += step
        keys.append(CameraKeyframe(end, position, rotation=rot))
    else:
        end_pos, end_rot = position, rot
        if kind in ("dolly_in", "dolly_out"):
            end_pos = position + track * (amt if kind == "dolly_in" else -amt)
        elif kind in ("truck_left", "truck_right"):
            end_pos = position + right * (amt if kind == "truck_right" else -amt)
        elif kind in ("pedestal_up", "pedestal_down", "crane_up", "crane_down"):
            end_pos = position + _UP * (amt if kind.endswith("_up") else -amt)
        elif kind in ("pan_left", "pan_right"):
            end_rot = (rot[0], rot[1] + (amt if kind == "pan_left" else -amt), rot[2])
        else:  # tilt
            end_rot = (rot[0] + (amt if kind == "tilt_up" else -amt), rot[1], rot[2])
        keys = [CameraKeyframe(start, position, rotation=rot), CameraKeyframe(end, end_pos, rotation=end_rot)]
    return Shot(id=id or shot_name("move", tag=kind), camera=Placement(position=position, rotation=rot),
                lens=_lens(lens, "move"), movement=Keyframed(keyframes=tuple(keys)), frame_range=(start, end))


def _size_pose(positions: Positions, subject: str, size: str, azimuth_deg: float, focal_length: float,
               frame_width_mm: float, aspect: float) -> Tuple[Vec3, Vec3]:
    framing = Framing(subjects=(subject,), size=size, azimuth_deg=azimuth_deg)
    return framing_transform([(_pos(positions, subject), True)], framing, focal_length,
                             frame_width_mm=frame_width_mm, aspect=aspect)


def push_in(positions: Positions, subject: str, *, start: int, end: int, from_size: str = "wide",
            to_size: str = "close_up", azimuth_deg: float = 0.0, line: Optional[LineOfAction] = None,
            lens: Optional[Union[Lens, float]] = None, id: Optional[str] = None,
            frame_width_mm: float = DEFAULT_FRAME_WIDTH_MM, aspect: float = DEFAULT_ASPECT) -> Shot:
    """A dolly from *from_size* to *to_size* on *subject*, re-aiming as the frame tightens.

    The camera direction is *azimuth_deg*, or a clean-single angle when a
    *line* is given (*subject* must be on it).
    """
    if end <= start:
        raise ValueError("end must be > start")
    ln = _lens(lens, "move")
    if line is not None:
        az = single(line, subject, lead=False).camera.azimuth_deg  # type: ignore[union-attr]
    else:
        az = azimuth_deg
    p0, a0 = _size_pose(positions, subject, from_size, az, ln.focal_length, frame_width_mm, aspect)
    p1, a1 = _size_pose(positions, subject, to_size, az, ln.focal_length, frame_width_mm, aspect)
    kind = "push_in" if framing_distance(to_size, 1.0) < framing_distance(from_size, 1.0) else "pull_out"
    return Shot(id=id or shot_name(kind, subject), camera=Placement(position=p0, look_at=a0), lens=ln,
                movement=Keyframed(keyframes=(CameraKeyframe(start, p0, look_at=a0),
                                              CameraKeyframe(end, p1, look_at=a1))),
                frame_range=(start, end))


def pull_out(positions: Positions, subject: str, *, start: int, end: int, from_size: str = "close_up",
             to_size: str = "wide", **kw: Any) -> Shot:
    """:func:`push_in` in reverse: from *from_size* back out to *to_size*."""
    return push_in(positions, subject, start=start, end=end, from_size=from_size, to_size=to_size, **kw)


def arc(subject: str, *, start: int, end: int, radius: float = 250.0, start_azimuth_deg: float = 0.0,
        end_azimuth_deg: float = 360.0, elevation_deg: float = 10.0,
        target_offset_cm: float = SHOT_SIZES["medium"][1], lens: Optional[Union[Lens, float]] = None,
        id: Optional[str] = None, step_deg: Optional[float] = None,
        positions: Optional[Positions] = None) -> Shot:
    """An arc (orbit) around actor *subject*.

    By default it is an :class:`~dazpy.shots.Orbit`, baked one placement per
    frame by :func:`~dazpy.shots.apply_shot` (exact, but a few calls per
    frame). With *step_deg* it is a :class:`~dazpy.shots.Keyframed` move
    with a waypoint every *step_deg* degrees (and at both ends) that Studio
    interpolates -- far cheaper for long shots; needs *positions*.

    An arc that sweeps across the line of action crosses it on purpose;
    :func:`check_axis` reports it.
    """
    ln = _lens(lens, "move")
    shot_id = id or shot_name("arc", subject)
    if step_deg is not None:
        if step_deg <= 0:
            raise ValueError("step_deg must be > 0")
        if end <= start:
            raise ValueError("end must be > start")
        target = _resolve(subject, positions, target_offset_cm)
        span = end_azimuth_deg - start_azimuth_deg
        n = max(1, int(math.ceil(abs(span) / step_deg)))
        frames = sorted({start + round((end - start) * i / n) for i in range(n + 1)})
        keys = []
        for f in frames:
            t = (f - start) / (end - start)
            p = spherical_offset(target, start_azimuth_deg + span * t, elevation_deg, radius)
            keys.append(CameraKeyframe(f, p, look_at=target))
        return Shot(id=shot_id, camera=Placement(position=keys[0].position, look_at=target), lens=ln,
                    movement=Keyframed(keyframes=tuple(keys)), frame_range=(start, end))
    return Shot(id=shot_id, camera=Framing(subjects=(subject,)),
                lens=ln,
                movement=Orbit(radius=radius, elevation_deg=elevation_deg, start_azimuth_deg=start_azimuth_deg,
                               end_azimuth_deg=end_azimuth_deg, frame_start=start, frame_end=end,
                               target_offset_cm=target_offset_cm),
                frame_range=(start, end))


# ---- focus ----------------------------------------------------------------

def focus_point(target: Union[str, Vec3], positions: Optional[Positions] = None,
                eye_height: float = EYE_HEIGHT_CM) -> Vec3:
    """Where to focus on *target*: an actor key's eyes, or a point as given."""
    if isinstance(target, str):
        if positions is None:
            raise ValueError(f"focus target {target!r} is a key but no positions were given")
        return _eye(_pos(positions, target), eye_height)
    return target


def rack_focus(camera_position: Vec3, from_target: Union[str, Vec3, float], to_target: Union[str, Vec3, float],
               *, start: int, end: int, positions: Optional[Positions] = None, hold_from: int = 0,
               hold_to: int = 0, eye_height: float = EYE_HEIGHT_CM) -> FocusPull:
    """A rack focus from *from_target* to *to_target* between *start* and *end*.

    Targets are actor keys (focus on the eyes), points, or focal distances
    (cm). The pull runs from ``start + hold_from`` to ``end - hold_to``; a
    hold that leaves no time to pull is dropped.
    """
    if end <= start:
        raise ValueError("end must be > start")

    def dist(t: Union[str, Vec3, float]) -> float:
        if isinstance(t, (int, float)):
            return float(t)
        return max(1.0, camera_position.distance(focus_point(t, positions, eye_height)))

    d0, d1 = dist(from_target), dist(to_target)
    pull_start, pull_end = start + max(0, hold_from), end - max(0, hold_to)
    if pull_start >= pull_end:
        pull_start, pull_end = start, end
    keys = [FocusKey(start, d0)]
    if pull_start > start:
        keys.append(FocusKey(pull_start, d0))
    keys.append(FocusKey(pull_end, d1))
    if pull_end < end:
        keys.append(FocusKey(end, d1))
    return FocusPull(keys=tuple(keys))


def camera_position(shot: Shot, positions: Optional[Positions] = None, *,
                    frame_width_mm: float = DEFAULT_FRAME_WIDTH_MM, aspect: float = DEFAULT_ASPECT) -> Vec3:
    """Where *shot*'s camera stands (its first position, for a move)."""
    return camera_positions(shot, positions, frame_width_mm=frame_width_mm, aspect=aspect)[0]


def with_rack_focus(shot: Shot, from_target: Union[str, Vec3, float], to_target: Union[str, Vec3, float], *,
                    start: int, end: int, positions: Optional[Positions] = None, f_stop: Optional[float] = None,
                    **kw: Any) -> Shot:
    """*shot* with a :func:`rack_focus` measured from its camera position, depth of field on."""
    pull = rack_focus(camera_position(shot, positions), from_target, to_target, start=start, end=end,
                      positions=positions, **kw)
    lens = replace(shot.lens, depth_of_field=True, f_stop=f_stop if f_stop is not None else shot.lens.f_stop)
    return replace(shot, focus=pull, lens=lens)


# ---- continuity -----------------------------------------------------------

def _resolve(t: Any, positions: Optional[Positions], offset: float) -> Vec3:
    if isinstance(t, str):
        if positions is None:
            raise ValueError(f"target {t!r} is a key but no positions were given")
        p = _pos(positions, t)
        return Vec3(p.x, p.y + offset, p.z)
    if isinstance(t, Vec3):
        return Vec3(t.x, t.y + offset, t.z) if offset else t
    pos = getattr(t, "position", None)
    if pos is None:
        raise ValueError("live node targets need a position")
    v = Vec3.from_dict(pos)
    return Vec3(v.x, v.y + offset, v.z)


def _framing_pose(f: Framing, focal_length: float, positions: Optional[Positions], frame_width_mm: float,
                  aspect: float) -> Tuple[Vec3, Vec3]:
    points = [(_resolve(s, positions, 0.0), not isinstance(s, Vec3)) for s in f.subjects]
    return framing_transform(points, f, focal_length, frame_width_mm=frame_width_mm, aspect=aspect)


def camera_positions(shot: Shot, positions: Optional[Positions] = None, *,
                     frame_width_mm: float = DEFAULT_FRAME_WIDTH_MM, aspect: float = DEFAULT_ASPECT,
                     orbit_step_deg: float = 10.0) -> List[Vec3]:
    """Every position *shot*'s camera passes through: one for a static shot, each
    waypoint of a :class:`~dazpy.shots.Keyframed` move, samples along an
    :class:`~dazpy.shots.Orbit`."""
    m, c = shot.movement, shot.camera
    if isinstance(m, Keyframed):
        return [kf.position for kf in m.keyframes]
    if isinstance(m, Orbit):
        target_ref = c.subjects[0] if isinstance(c, Framing) else c.look_at
        if target_ref is None:
            raise ValueError(f"shot {shot.id!r}: an Orbit needs a target")
        target = _resolve(target_ref, positions, m.target_offset_cm)
        span = m.end_azimuth_deg - m.start_azimuth_deg
        n = max(1, int(math.ceil(abs(span) / orbit_step_deg)))
        return [spherical_offset(target, m.start_azimuth_deg + span * i / n, m.elevation_deg, m.radius)
                for i in range(n + 1)]
    if isinstance(c, Framing):
        return [_framing_pose(c, shot.lens.focal_length, positions, frame_width_mm, aspect)[0]]
    return [c.position]


def _static_pose(shot: Shot, positions: Optional[Positions], frame_width_mm: float,
                 aspect: float) -> Optional[Tuple[Vec3, Vec3]]:
    if shot.movement is not None:
        return None
    c = shot.camera
    if isinstance(c, Framing):
        return _framing_pose(c, shot.lens.focal_length, positions, frame_width_mm, aspect)
    if c.look_at is not None:
        return c.position, _resolve(c.look_at, positions, c.look_at_offset_cm)
    if c.rotation is not None:
        return c.position, aim_from_rotation(c.position, c.rotation)
    return None


@dataclass(frozen=True)
class ContinuityIssue:
    """A continuity problem: ``kind`` is ``"axis"`` (a camera crosses the line of
    action) or ``"thirty_degree"`` (a jump cut between near-identical setups)."""

    kind: str
    shot_id: str
    message: str
    other_shot_id: Optional[str] = None


def check_axis(shots: Iterable[Shot], line: LineOfAction, positions: Optional[Positions] = None, *,
               tolerance_cm: float = 1.0, frame_width_mm: float = DEFAULT_FRAME_WIDTH_MM,
               aspect: float = DEFAULT_ASPECT) -> List[ContinuityIssue]:
    """Shots whose camera stands (or moves) on the wrong side of *line*.

    A camera on the line itself (a neutral shot) is allowed.
    """
    issues = []
    for shot in shots:
        sides = {line.side_of(p, tolerance_cm) for p in camera_positions(
            shot, positions, frame_width_mm=frame_width_mm, aspect=aspect)}
        if -line.side in sides:
            moving = shot.movement is not None and len(sides - {0}) > 1
            what = "moves across" if moving else "is on the wrong side of"
            issues.append(ContinuityIssue("axis", shot.id,
                                          f"camera {what} the {line.a}-{line.b} line of action"))
    return issues


def check_thirty_degree(shots: Seq[Shot], positions: Optional[Positions] = None, *, min_angle_deg: float = 30.0,
                        same_subject_cm: float = 50.0, size_ratio: float = 1.33,
                        frame_width_mm: float = DEFAULT_FRAME_WIDTH_MM,
                        aspect: float = DEFAULT_ASPECT) -> List[ContinuityIssue]:
    """Consecutive static shots (in cut order) of the same subject whose camera
    angle changes by less than *min_angle_deg* without a clear size change --
    a jump cut.

    Two setups count as the same subject when their aim points are within
    *same_subject_cm*, and as the same size when their camera distances
    differ by less than a factor of *size_ratio*.
    """
    issues = []
    poses = [_static_pose(s, positions, frame_width_mm, aspect) for s in shots]
    for (s0, p0), (s1, p1) in zip(zip(shots, poses), zip(shots[1:], poses[1:])):
        if p0 is None or p1 is None or p0[1].distance(p1[1]) > same_subject_cm:
            continue
        v0, v1 = p0[0] - p0[1], p1[0] - p1[1]
        d0, d1 = v0.length(), v1.length()
        if d0 < 1e-6 or d1 < 1e-6 or max(d0, d1) / min(d0, d1) >= size_ratio:
            continue
        angle = math.degrees(math.acos(max(-1.0, min(1.0, v0.dot(v1) / (d0 * d1)))))
        if angle < min_angle_deg:
            issues.append(ContinuityIssue(
                "thirty_degree", s1.id,
                f"cut from {s0.id!r} moves the camera only {angle:.0f} degrees at a similar size", s0.id))
    return issues


def check_continuity(shots: Seq[Shot], positions: Optional[Positions] = None, *,
                     line: Optional[LineOfAction] = None, **kw: Any) -> List[ContinuityIssue]:
    """:func:`check_axis` (when *line* is given) plus :func:`check_thirty_degree`, in cut order."""
    shots = list(shots)
    geo = {k: kw[k] for k in ("frame_width_mm", "aspect") if k in kw}
    issues = check_axis(shots, line, positions, **geo) if line is not None else []
    return issues + check_thirty_degree(shots, positions, **kw)


def plan_line(plan: CoveragePlan, positions: Positions, *, frame_width_mm: float = DEFAULT_FRAME_WIDTH_MM,
              aspect: float = DEFAULT_ASPECT) -> Optional[LineOfAction]:
    """The plan's line of action, its side taken from the first shot that is off the line."""
    if plan.axis is None:
        return None
    line = LineOfAction.between(positions, *plan.axis)
    for shot in plan.all_shots():
        for p in camera_positions(shot, positions, frame_width_mm=frame_width_mm, aspect=aspect):
            s = line.side_of(p)
            if s:
                return replace(line, side=s)
    return line


def check_plan(plan: CoveragePlan, positions: Positions, **kw: Any) -> List[ContinuityIssue]:
    """:func:`check_continuity` for every sequence of *plan*, against the plan's axis."""
    geo = {k: kw[k] for k in ("frame_width_mm", "aspect") if k in kw}
    line = plan_line(plan, positions, **geo)
    issues: List[ContinuityIssue] = []
    for seq in plan.sequences:
        issues += check_continuity(seq.shots, positions, line=line, **kw)
    return issues


# ---- coverage -------------------------------------------------------------

#: :func:`subject_coverage` presets: (kind tag, size, angle, azimuth offset deg, lens mm).
COVERAGE_PRESETS: Mapping[str, Tuple[Tuple[Optional[str], str, str, float, float], ...]] = {
    "standard": ((None, "wide", "eye_level", 0.0, 35.0), (None, "medium", "eye_level", 0.0, 50.0),
                 (None, "close_up", "eye_level", 0.0, 85.0)),
    "interview": ((None, "medium", "eye_level", 0.0, 50.0), ("left", "medium_close_up", "eye_level", -30.0, 85.0),
                  ("right", "medium_close_up", "eye_level", 30.0, 85.0)),
    "dramatic": ((None, "wide", "eye_level", 0.0, 35.0), ("low", "medium", "low", 0.0, 50.0),
                 ("high", "medium", "high", 0.0, 50.0), ("profile", "medium_close_up", "eye_level", 90.0, 85.0)),
    "action": ((None, "wide", "eye_level", 0.0, 28.0), (None, "medium", "eye_level", 0.0, 50.0),
               ("three-quarter", "medium_wide", "eye_level", -45.0, 35.0), ("hero", "medium", "low", 0.0, 35.0)),
}


def subject_coverage(subject: str, *, preset: str = "standard", azimuth_deg: float = 0.0,
                     plan_id: Optional[str] = None, headroom: bool = False) -> CoveragePlan:
    """Single-actor coverage from :data:`COVERAGE_PRESETS`, around *azimuth_deg* (0 = the actor's ``+Z`` side)."""
    if preset not in COVERAGE_PRESETS:
        raise ValueError(f"unknown coverage preset {preset!r}; valid: {', '.join(COVERAGE_PRESETS)}")
    shots = tuple(
        Shot(id=shot_name(size, subject, tag=tag),
             camera=Framing(subjects=(subject,), size=size, angle=angle, azimuth_deg=azimuth_deg + offset,
                            anchor_cm=headroom_anchor(size) if headroom else None),
             lens=Lens(focal_length=mm))
        for tag, size, angle, offset, mm in COVERAGE_PRESETS[preset])
    pid = plan_id or f"{_slug(subject)}_{preset}"
    return CoveragePlan(id=pid, subjects=(subject,), sequences=(Sequence(id=pid, shots=shots),))


def dialogue_coverage(line: LineOfAction, *, plan_id: Optional[str] = None,
                      include: Iterable[str] = ("master", "two_shot", "ots", "singles"),
                      single_size: str = "close_up", **kw: Any) -> CoveragePlan:
    """Standard two-actor coverage on one side of *line*: master, two-shot,
    the OTS shot/reverse pair and the clean singles (pick with *include*).

    *kw* (``frame_width_mm``, ``aspect``) goes to the framing builders.
    """
    include = tuple(include)
    unknown = set(include) - {"master", "two_shot", "ots", "singles"}
    if unknown:
        raise ValueError(f"unknown coverage part(s): {sorted(unknown)}")
    shots: List[Shot] = []
    if "master" in include:
        shots.append(master(line, **kw))
    if "two_shot" in include:
        shots.append(two_shot(line, **kw))
    if "ots" in include:
        shots += shot_reverse_shot(line, frame_width_mm=kw.get("frame_width_mm", DEFAULT_FRAME_WIDTH_MM))
    if "singles" in include:
        shots += [single(line, line.a, size=single_size), single(line, line.b, size=single_size)]
    pid = plan_id or f"{_slug(line.a)}_{_slug(line.b)}_dialogue"
    return CoveragePlan(id=pid, subjects=(line.a, line.b), axis=(line.a, line.b),
                        sequences=(Sequence(id=pid, shots=tuple(shots)),))


@dataclass(frozen=True)
class DialogueBeat:
    """*speaker* talks from frame *start* to *end* (inclusive); *line* is the dialogue text."""

    speaker: str
    start: int
    end: int
    line: Optional[str] = None

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("DialogueBeat.end must be >= start")


def conversation(line: LineOfAction, beats: Iterable[DialogueBeat], *, plan_id: str = "conversation",
                 style: str = "ots", establish_frames: int = 0, single_size: str = "medium_close_up",
                 lens: Optional[Union[Lens, float]] = None, **kw: Any) -> CoveragePlan:
    """Cut a conversation between the line's two actors, one shot per beat.

    Each beat is covered on the speaker -- over the listener's shoulder
    (``style="ots"``) or in a clean single (``style="singles"``) -- from the
    same side of the line, so eyelines match across the cuts. Every shot
    carries its frame range, gaze beats (speaker and listener look at each
    other) and the dialogue as storyboard text.

    Args:
        establish_frames: When > 0, open on a master for this many frames
            at the start of the first beat (which then starts after it).
        kw: ``frame_width_mm`` / ``aspect`` for the framing builders.
    """
    if style not in ("ots", "singles"):
        raise ValueError("style must be 'ots' or 'singles'")
    beats = list(beats)
    if not beats:
        raise ValueError("a conversation needs at least one beat")
    for i, b in enumerate(beats):
        if b.speaker not in (line.a, line.b):
            raise ValueError(f"beat {i}: speaker {b.speaker!r} is not {line.a!r} or {line.b!r}")
        if i and b.start <= beats[i - 1].end:
            raise ValueError(f"beat {i} starts at {b.start}, before beat {i - 1} ends ({beats[i - 1].end})")
    shots: List[Shot] = []
    if establish_frames > 0:
        first = beats[0]
        est_end = min(first.end, first.start + establish_frames - 1)
        shots.append(master(line, id=shot_name("master", f"{line.a}-{line.b}", index=0),
                            frame_range=(first.start, est_end), **kw))
        if est_end >= first.end:
            beats = beats[1:]
        else:
            beats[0] = replace(first, start=est_end + 1)
    fw = kw.get("frame_width_mm", DEFAULT_FRAME_WIDTH_MM)
    for i, b in enumerate(beats, start=1):
        listener = line.other(b.speaker)
        rng = (b.start, b.end)
        if style == "ots":
            s = over_the_shoulder(line, listener, b.speaker, lens=lens, frame_width_mm=fw, frame_range=rng,
                                  id=shot_name("ots", b.speaker, over=listener, index=i))
        else:
            s = single(line, b.speaker, size=single_size, lens=lens, frame_range=rng,
                       id=shot_name(single_size, b.speaker, index=i))
        shots.append(replace(
            s, gaze=(GazeBeat(b.start, b.speaker, listener), GazeBeat(b.start, listener, b.speaker)),
            storyboard=Storyboard(dialogue=b.line, beat=f"{b.speaker} speaks")))
    return CoveragePlan(id=plan_id, subjects=(line.a, line.b), axis=(line.a, line.b),
                        sequences=(Sequence(id=plan_id, shots=tuple(shots)),))


# ---- apply ----------------------------------------------------------------

def apply_coverage(scene: "DazScene", plan: Union[CoveragePlan, Iterable[Shot]], *,
                   subjects: Optional[Mapping[str, Any]] = None,
                   cameras: Optional[Mapping[str, "DazCamera"]] = None,
                   frame_width_mm: float = DEFAULT_FRAME_WIDTH_MM,
                   aspect: float = DEFAULT_ASPECT) -> Dict[str, "DazCamera"]:
    """Apply every shot of *plan* on its own camera, named and labelled after the shot id.

    Args:
        cameras: Existing cameras to reuse, by shot id; others are created.
        subjects: As for :func:`~dazpy.shots.apply_shot` -- usually the same
            positions mapping the shots were built from.

    Returns:
        ``{shot id: camera}`` in plan order.
    """
    shots = plan.all_shots() if isinstance(plan, CoveragePlan) else tuple(plan)
    out: Dict[str, "DazCamera"] = {}
    for shot in shots:
        existing = (cameras or {}).get(shot.id)
        cam = existing if existing is not None else scene.create_camera(shot.id)
        if existing is None:
            cam.label = shot.id  # a scripted camera's label is empty on Studio 4
        out[shot.id] = apply_shot(scene, shot, camera=cam, subjects=subjects,
                                  frame_width_mm=frame_width_mm, aspect=aspect)
    return out


__all__ = [
    "EYE_HEIGHT_CM", "BODY_WIDTH_CM", "OTS_BACK_CM", "OTS_SIDE_CM", "OTS_DROP_CM", "SINGLE_OFFSET_DEG", "DEFAULT_LENSES",
    "SHOT_ABBREVIATIONS", "MOVE_DEFAULTS", "CAMERA_MOVES", "COVERAGE_PRESETS",
    "shot_name", "LineOfAction", "headroom_anchor", "lead_room", "THIRD_X", "GOLDEN_X", "compose_aim",
    "establishing", "master", "two_shot", "single", "over_the_shoulder", "shot_reverse_shot", "pov", "insert",
    "euler_from_quaternion", "canonical_rotation", "forward_from_rotation", "look_rotation", "camera_up", "aim_from_rotation", "camera_move", "push_in", "pull_out", "arc",
    "focus_point", "rack_focus", "camera_position", "camera_positions", "with_rack_focus",
    "ContinuityIssue", "check_axis", "check_thirty_degree", "check_continuity", "plan_line", "check_plan",
    "subject_coverage", "dialogue_coverage", "DialogueBeat", "conversation", "apply_coverage",
]
