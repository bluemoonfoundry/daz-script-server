"""Typed, serialisable shot models: :class:`Shot`, :class:`Sequence`, :class:`CoveragePlan`.

A :class:`Shot` describes one camera setup as a whole: what it frames
(:class:`Framing`) or where it stands (:class:`Placement`), through which
:class:`Lens`, how it moves (:class:`Orbit` / :class:`Keyframed`), where focus
goes (:class:`FocusPull`), and the planning data around it -- blocking and
gaze beats, the lighting setup it must match, storyboard notes and its render
output. :func:`apply_shot` puts a shot into a live scene; the
:mod:`dazpy.cinematics` builders are thin adapters over it.

Every model is a frozen dataclass with ``to_dict()`` / ``from_dict()``
(JSON-compatible; union fields carry a ``kind`` discriminator, default-valued
fields are omitted). Targets are an actor/prop key (``str``, resolved through
the ``subjects`` mapping of :func:`apply_shot`), a :class:`~dazpy.math3.Vec3`,
or a live :class:`~dazpy.DazNode` -- the last is not serialisable.

Static shots convert to and from scene-recipe camera entries
(:meth:`Shot.to_recipe`, :func:`shot_from_recipe_camera`,
:meth:`CoveragePlan.to_recipe_sections`, :meth:`CoveragePlan.merge_into_recipe`).

Units are DAZ native: centimetres, Y-up, degrees, timeline frames.
"""

from __future__ import annotations

import copy
from dataclasses import MISSING, dataclass, field, fields
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Iterable, Literal, Mapping, Optional, Tuple, Union

from .math3 import Vec3
from ._shot_geometry import look_at_euler, resolve_target, spherical_offset
from ._timeline import DazTimeline

if TYPE_CHECKING:
    from ._camera import DazCamera
    from ._node import DazNode
    from ._scene import DazScene

Target = Union[str, Vec3, "DazNode"]

ShotSize = Literal["extreme_wide", "wide", "full_body", "medium_wide", "medium",
                   "medium_close_up", "close_up", "extreme_close_up"]
CameraAngle = Literal["eye_level", "high", "low", "birds_eye", "worms_eye"]
Composition = Literal["center", "left_third", "right_third"]

#: Per shot size: (cm of subject that fills the frame height, cm above an
#: actor's root to aim at). Assumes a standing Genesis-scale (~175 cm) figure.
#: ``full_body`` / ``medium`` / ``close_up`` are the scene-recipe values.
SHOT_SIZES: Mapping[str, Tuple[float, float]] = {
    "extreme_wide": (600.0, 90.0),
    "wide": (350.0, 90.0),
    "full_body": (210.0, 90.0),
    "medium_wide": (140.0, 115.0),
    "medium": (100.0, 130.0),
    "medium_close_up": (60.0, 145.0),
    "close_up": (40.0, 160.0),
    "extreme_close_up": (15.0, 165.0),
}

#: Camera elevation (degrees above the aim point) per named angle.
CAMERA_ANGLES: Mapping[str, float] = {
    "eye_level": 0.0, "high": 30.0, "low": -20.0, "birds_eye": 80.0, "worms_eye": -45.0,
}

COMPOSITIONS: Tuple[str, ...] = ("center", "left_third", "right_third")

#: Daz camera "Frame Width" default (mm), and the height/width ratio used when
#: nothing sets a resolution -- the same defaults scene recipes use. Despite its
#: name, Studio applies Frame Width to the frame *height* at any aspect
#: (``getFieldOfView()`` is vertical); the frame width is ``frame_width_mm / aspect``.
DEFAULT_FRAME_WIDTH_MM = 36.0
DEFAULT_ASPECT = 3 / 4


# ---- serialisation helpers ----------------------------------------------

def _is_node(v: Any) -> bool:
    # Look on the type (or instance dict) so a real DazNode's ``position``
    # property -- an HTTP round trip -- is never evaluated here.
    if isinstance(v, (str, Vec3, tuple, list, dict, int, float, bool)) or v is None:
        return False
    return hasattr(type(v), "position") or "position" in getattr(v, "__dict__", {})


def _enc(v: Any, path: str) -> Any:
    if isinstance(v, Vec3):
        return [v.x, v.y, v.z]
    if isinstance(v, _Model):
        return v._dump(path)
    if isinstance(v, tuple):
        return [_enc(x, f"{path}[{i}]") for i, x in enumerate(v)]
    if _is_node(v):
        raise TypeError(f"{path}: a DazNode target can't be serialised; use an actor/prop key or [x, y, z]")
    return v


def _vec(v: Any, path: str) -> Vec3:
    if isinstance(v, Vec3):
        return v
    if isinstance(v, (list, tuple)) and len(v) == 3 and all(
            isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
        return Vec3(*v)
    raise ValueError(f"{path}: must be [x, y, z]")


def _opt_vec(v: Any, path: str) -> Optional[Vec3]:
    return None if v is None else _vec(v, path)


def _target(v: Any, path: str) -> Any:
    if isinstance(v, str):
        if not v:
            raise ValueError(f"{path}: an entity key must be non-empty")
        return v
    if _is_node(v):
        return v
    return _vec(v, path)


def _opt_target(v: Any, path: str) -> Any:
    return None if v is None else _target(v, path)


def _floats(n: int) -> Callable[[Any, str], Any]:
    def conv(v: Any, path: str) -> Any:
        if v is None:
            return None
        if not (isinstance(v, (list, tuple)) and len(v) == n):
            raise ValueError(f"{path}: must be an array of {n} numbers")
        return tuple(float(x) for x in v)
    return conv


def _tuple_of(cls: Any) -> Callable[[Any, str], tuple]:
    def conv(v: Any, path: str) -> tuple:
        if not isinstance(v, (list, tuple)):
            raise ValueError(f"{path}: must be an array")
        return tuple(cls._load(x, f"{path}[{i}]") for i, x in enumerate(v))
    return conv


def _opt(cls: Any) -> Callable[[Any, str], Any]:
    return lambda v, path: None if v is None else cls._load(v, path)


def _check_enum(value: Any, allowed: Iterable[str], path: str) -> None:
    allowed = tuple(allowed)
    if value not in allowed:
        raise ValueError(f"{path}: {value!r} is not one of {list(allowed)}")


class _Model:
    """Mixin: ``to_dict`` / ``from_dict`` driven by a per-class ``_codec``."""

    _codec: ClassVar[Mapping[str, Callable[[Any, str], Any]]] = {}
    _kind: ClassVar[Optional[str]] = None

    def _dump(self, path: str) -> dict:
        out: dict = {"kind": self._kind} if self._kind else {}
        for f in fields(self):  # type: ignore[arg-type]
            value = getattr(self, f.name)
            default = f.default if f.default is not MISSING else (
                f.default_factory() if f.default_factory is not MISSING else MISSING)  # type: ignore[misc]
            if default is not MISSING and value == default:
                continue
            out[f.name] = _enc(value, f"{path}.{f.name}" if path else f.name)
        return out

    def to_dict(self) -> dict:
        """JSON-compatible dict; default-valued fields are omitted.

        Raises:
            TypeError: If a target is a live :class:`~dazpy.DazNode`.
        """
        return self._dump("")

    @classmethod
    def _load(cls, data: Any, path: str) -> Any:
        if not isinstance(data, Mapping):
            raise ValueError(f"{path or cls.__name__}: must be an object")
        names = {f.name for f in fields(cls)}  # type: ignore[arg-type]
        kwargs = {}
        for k, v in data.items():
            p = f"{path}.{k}" if path else k
            if k == "kind" and cls._kind:
                if v != cls._kind:
                    raise ValueError(f"{p}: expected {cls._kind!r}, got {v!r}")
                continue
            if k not in names:
                raise ValueError(f"{p}: unknown field (allowed: {sorted(names)})")
            conv = cls._codec.get(k)
            kwargs[k] = conv(v, p) if conv else v
        try:
            return cls(**kwargs)
        except TypeError as exc:
            raise ValueError(f"{path or cls.__name__}: {exc}") from None
        except ValueError as exc:
            raise ValueError(f"{path}: {exc}" if path else str(exc)) from None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Any:
        """Build from a ``to_dict()``-shaped mapping.

        Raises:
            ValueError: Unknown field, bad enum, wrong ``kind`` or invalid
                value; the message starts with the dotted path.
        """
        return cls._load(data, "")


def _union(*classes: Any) -> Callable[[Any, str], Any]:
    by_kind = {c._kind: c for c in classes}

    def conv(v: Any, path: str) -> Any:
        if v is None:
            return None
        if isinstance(v, tuple(classes)):
            return v
        if not isinstance(v, Mapping) or v.get("kind") not in by_kind:
            raise ValueError(f"{path}: needs 'kind' of {sorted(by_kind)}")
        return by_kind[v["kind"]]._load(v, path)
    return conv


def _require_frames(frames: list, what: str, minimum: int = 2) -> None:
    if len(frames) < minimum:
        raise ValueError(f"{what} needs at least {minimum} entries")
    if frames != sorted(frames) or len(set(frames)) != len(frames):
        raise ValueError(f"{what} must have strictly ascending, unique frame numbers")


# ---- camera parts --------------------------------------------------------

@dataclass(frozen=True)
class Lens(_Model):
    """Camera optics. ``None`` fields leave Studio's current value untouched."""

    focal_length: float = 50.0
    depth_of_field: Optional[bool] = None
    focal_distance: Optional[float] = None
    f_stop: Optional[float] = None

    def __post_init__(self) -> None:
        if self.focal_length <= 0:
            raise ValueError("focal_length must be > 0")


@dataclass(frozen=True)
class Framing(_Model):
    """Frame one or more subjects at a named shot size.

    Args:
        subjects: One or more targets; the camera aims at their centroid.
            Keys and :class:`~dazpy.DazNode` targets are raised by the size's
            anchor height (they are assumed to be standing figures);
            :class:`~dazpy.math3.Vec3` targets only by *anchor_cm*.
        size: Shot size -- see :data:`SHOT_SIZES`.
        angle: Named camera angle -- see :data:`CAMERA_ANGLES`.
        azimuth_deg: Camera azimuth around the aim point (0 = the subject's
            ``+Z`` side; see :func:`~dazpy._shot_geometry.spherical_offset`).
        elevation_deg: Explicit elevation; overrides *angle* when set.
        composition: ``"left_third"`` / ``"right_third"`` places the subject on
            that third of the frame by turning the camera, not moving it.
        distance_cm: Explicit camera distance; overrides the size's fit.
        anchor_cm: Explicit aim height above every subject; overrides the
            size's anchor (and applies to ``Vec3`` subjects too).
    """

    _kind: ClassVar[str] = "framing"

    subjects: Tuple[Target, ...]
    size: str = "medium"
    angle: str = "eye_level"
    azimuth_deg: float = 0.0
    elevation_deg: Optional[float] = None
    composition: str = "center"
    distance_cm: Optional[float] = None
    anchor_cm: Optional[float] = None

    def __post_init__(self) -> None:
        if not isinstance(self.subjects, tuple):
            object.__setattr__(self, "subjects", (self.subjects,) if isinstance(self.subjects, (str, Vec3))
                               or _is_node(self.subjects) else tuple(self.subjects))
        if not self.subjects:
            raise ValueError("subjects needs at least one target")
        _check_enum(self.size, SHOT_SIZES, "size")
        _check_enum(self.angle, CAMERA_ANGLES, "angle")
        _check_enum(self.composition, COMPOSITIONS, "composition")
        if self.distance_cm is not None and self.distance_cm <= 0:
            raise ValueError("distance_cm must be > 0")

    @property
    def effective_elevation_deg(self) -> float:
        return self.elevation_deg if self.elevation_deg is not None else CAMERA_ANGLES[self.angle]


Framing._codec = {
    "subjects": lambda v, p: tuple(_target(x, f"{p}[{i}]") for i, x in enumerate(v))
    if isinstance(v, (list, tuple)) else (_target(v, p),),
}


@dataclass(frozen=True)
class Placement(_Model):
    """An explicit camera position, aimed at *look_at* or turned to *rotation*."""

    _kind: ClassVar[str] = "placement"

    position: Vec3
    look_at: Optional[Target] = None
    look_at_offset_cm: float = 0.0
    rotation: Optional[Tuple[float, float, float]] = None


Placement._codec = {"position": _vec, "look_at": _opt_target, "rotation": _floats(3)}


@dataclass(frozen=True)
class CameraKeyframe(_Model):
    """A single waypoint in an animated camera move (see :class:`Keyframed`).

    Args:
        frame: Timeline frame number for this waypoint.
        position: World-space camera position at *frame*.
        look_at: Aim target at *frame*. Ignored if ``None``; in that case
            *rotation* (if set) is used instead.
        look_at_offset_cm: Vertical offset (cm) applied when resolving
            *look_at* -- see :func:`~dazpy._shot_geometry.resolve_target`.
        rotation: Explicit ``(x, y, z)`` degrees for this waypoint. Ignored
            if *look_at* is set.
    """

    frame: int
    position: Vec3
    look_at: Optional[Target] = None
    look_at_offset_cm: float = 0.0
    rotation: Optional[Tuple[float, float, float]] = None


CameraKeyframe._codec = {"position": _vec, "look_at": _opt_target, "rotation": _floats(3)}


@dataclass(frozen=True)
class Orbit(_Model):
    """Movement: sweep around the shot's subject, baking one placement per frame.

    The orbit target is the shot's camera target: a :class:`Framing`'s first
    subject, or a :class:`Placement`'s ``look_at``. See
    :func:`dazpy.cinematics.apply_orbit_camera` for the side effects (anim
    range widened, timeline left at *frame_end*).
    """

    _kind: ClassVar[str] = "orbit"

    radius: float
    elevation_deg: float = 15.0
    start_azimuth_deg: float = 0.0
    end_azimuth_deg: float = 360.0
    frame_start: int = 0
    frame_end: int = 90
    target_offset_cm: float = 25.0

    def __post_init__(self) -> None:
        if self.frame_end < self.frame_start:
            raise ValueError(
                f"OrbitCamera.frame_end ({self.frame_end}) must be >= frame_start ({self.frame_start})")


@dataclass(frozen=True)
class Keyframed(_Model):
    """Movement: real Daz keyframes, one per waypoint; Studio interpolates between.

    Waypoints must be strictly ascending (at least two), and either every
    waypoint specifies an orientation (*look_at*/*rotation*) or none does.
    """

    _kind: ClassVar[str] = "keyframed"

    keyframes: Tuple[CameraKeyframe, ...]

    def __post_init__(self) -> None:
        if len(self.keyframes) < 2:
            raise ValueError("CinematicAnimatedShot.keyframes needs at least two waypoints")
        frames = [kf.frame for kf in self.keyframes]
        if frames != sorted(frames) or len(set(frames)) != len(frames):
            raise ValueError("CinematicAnimatedShot.keyframes must have strictly ascending, unique frame numbers")
        oriented = [kf.look_at is not None or kf.rotation is not None for kf in self.keyframes]
        if any(oriented) and not all(oriented):
            raise ValueError(
                "CinematicAnimatedShot.keyframes must either all specify an orientation "
                "(look_at/rotation) or none of them should")

    @property
    def has_orientation(self) -> bool:
        return self.keyframes[0].look_at is not None or self.keyframes[0].rotation is not None


Keyframed._codec = {"keyframes": _tuple_of(CameraKeyframe)}


@dataclass(frozen=True)
class FocusKey(_Model):
    frame: int
    focal_distance: float

    def __post_init__(self) -> None:
        if self.focal_distance <= 0:
            raise ValueError("focal_distance must be > 0")


@dataclass(frozen=True)
class FocusPull(_Model):
    """Keyed focal distance (a rack focus): at least two strictly ascending keys."""

    keys: Tuple[FocusKey, ...]

    def __post_init__(self) -> None:
        _require_frames([k.frame for k in self.keys], "FocusPull.keys")


FocusPull._codec = {"keys": _tuple_of(FocusKey)}


# ---- planning data (carried, not applied) --------------------------------

@dataclass(frozen=True)
class GazeBeat(_Model):
    """From *frame*, *actor* looks at *look_at*. Planning data; not applied yet."""

    frame: int
    actor: str
    look_at: Target


GazeBeat._codec = {"look_at": _target}


@dataclass(frozen=True)
class BlockingBeat(_Model):
    """At *frame*, *actor* stands at *position* (facing *facing*). Planning data; not applied yet."""

    frame: int
    actor: str
    position: Vec3
    facing: Optional[Target] = None
    note: Optional[str] = None


BlockingBeat._codec = {"position": _vec, "facing": _opt_target}


@dataclass(frozen=True)
class Storyboard(_Model):
    """Free-text storyboard metadata."""

    description: Optional[str] = None
    dialogue: Optional[str] = None
    beat: Optional[str] = None
    notes: Optional[str] = None


@dataclass(frozen=True)
class RenderOutput(_Model):
    """Where a shot renders, and per-shot render overrides (see :func:`dazpy.render_api.render`)."""

    path: str
    engine: Optional[str] = None
    resolution: Optional[Tuple[int, int]] = None
    iray_samples: Optional[int] = None

    def __post_init__(self) -> None:
        if not self.path:
            raise ValueError("path must be non-empty")
        if self.engine is not None:
            _check_enum(self.engine, ("iray", "filament", "viewport"), "engine")


RenderOutput._codec = {"resolution": lambda v, p: None if v is None else tuple(int(x) for x in _floats(2)(v, p))}


@dataclass(frozen=True)
class AspectSettings(_Model):
    """Camera aspect/pixel settings; ``None`` leaves Studio's value untouched."""

    aspect_width: Optional[float] = None
    aspect_height: Optional[float] = None
    pixels_width: Optional[int] = None
    pixels_height: Optional[int] = None


# ---- Shot / Sequence / CoveragePlan --------------------------------------

_CAMERA = _union(Framing, Placement)
_MOVEMENT = _union(Orbit, Keyframed)


@dataclass(frozen=True)
class Shot(_Model):
    """One camera setup and everything planned around it.

    Args:
        id: Stable shot id (also the recipe camera/shot key on conversion).
        camera: :class:`Framing` (auto-framed) or :class:`Placement` (explicit).
        lens: Optics.
        movement: ``None`` (static), :class:`Orbit` or :class:`Keyframed`.
        focus: Optional :class:`FocusPull`.
        frame_range: Optional ``(start, end)`` the shot covers on the timeline.
        aspect: Optional camera aspect/pixel settings.
        blocking: Actor blocking beats (planning data; not applied yet).
        gaze: Gaze beats (planning data; not applied yet).
        lighting: Lighting continuity key -- the lighting setup/rig this shot
            must match (planning data).
        storyboard: Storyboard metadata.
        output: Where the shot renders.
    """

    id: str
    camera: Union[Framing, Placement]
    lens: Lens = field(default_factory=Lens)
    movement: Optional[Union[Orbit, Keyframed]] = None
    focus: Optional[FocusPull] = None
    frame_range: Optional[Tuple[int, int]] = None
    aspect: Optional[AspectSettings] = None
    blocking: Tuple[BlockingBeat, ...] = ()
    gaze: Tuple[GazeBeat, ...] = ()
    lighting: Optional[str] = None
    storyboard: Optional[Storyboard] = None
    output: Optional[RenderOutput] = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("id must be non-empty")
        if not isinstance(self.camera, (Framing, Placement)):
            raise ValueError("camera must be a Framing or a Placement")
        if self.frame_range is not None and self.frame_range[1] < self.frame_range[0]:
            raise ValueError("frame_range end must be >= start")
        if isinstance(self.movement, Keyframed) and isinstance(self.camera, Framing):
            raise ValueError("a Keyframed move carries its own positions; use a Placement camera "
                             "(its first waypoint) instead of a Framing")

    @property
    def is_static(self) -> bool:
        return self.movement is None and self.focus is None

    def to_recipe(self) -> Tuple[dict, Optional[dict]]:
        """Scene-recipe ``(cameras[id] entry, shots[] entry or None)``.

        Only static shots convert (``shots[].movement`` is reserved in
        recipe_version 1). Framing subjects must be keys; explicit
        positions/aims must be keys or ``Vec3`` literals. Planning data
        (blocking, gaze, lighting continuity, storyboard) and aspect
        settings are not carried -- recipes have nowhere to put them.

        Raises:
            ValueError: The shot moves, pulls focus, frames a ``Vec3``, or
                uses a field recipes can't express.
            TypeError: A target is a live :class:`~dazpy.DazNode`.
        """
        if self.movement is not None:
            raise ValueError(f"shot {self.id!r}: camera movement is not supported in recipe_version 1")
        if self.focus is not None:
            raise ValueError(f"shot {self.id!r}: focus pulls are not supported in recipe_version 1")
        cam: dict = {}
        c = self.camera
        if isinstance(c, Framing):
            for i, s in enumerate(c.subjects):
                if not isinstance(s, str):
                    _enc(s, f"camera.subjects[{i}]")  # DazNode -> TypeError
                    raise ValueError(f"shot {self.id!r}: recipe framing subjects must be actor/prop keys")
            if c.distance_cm is not None or c.anchor_cm is not None:
                raise ValueError(f"shot {self.id!r}: distance_cm/anchor_cm can't be expressed in a recipe")
            cam["frame"] = c.subjects[0] if len(c.subjects) == 1 else list(c.subjects)
            if c.size != "medium":
                cam["shot_type"] = c.size
            if c.elevation_deg is not None:
                cam["elevation_deg"] = c.elevation_deg
            else:
                cam["angle"] = c.angle
            if c.azimuth_deg:
                cam["azimuth_deg"] = c.azimuth_deg
            if c.composition != "center":
                cam["composition"] = c.composition
        else:
            if c.look_at_offset_cm:
                raise ValueError(f"shot {self.id!r}: look_at_offset_cm can't be expressed in a recipe")
            cam["position"] = _enc(c.position, "camera.position")
            if c.look_at is not None:
                cam["look_at"] = _enc(c.look_at, "camera.look_at")
            elif c.rotation is not None:
                cam["rotation"] = list(c.rotation)
        lens = self.lens
        if lens.f_stop is not None:
            raise ValueError(f"shot {self.id!r}: f_stop can't be expressed in a recipe")
        cam["focal_length"] = lens.focal_length
        if lens.depth_of_field:
            cam["depth_of_field"] = True
        if lens.focal_distance is not None:
            cam["focal_distance"] = lens.focal_distance
        shot: dict[str, Any] | None = None
        if self.output is not None:
            shot = {"id": self.id, "camera": self.id, "output": self.output.path}
            render = {k: v for k, v in (("engine", self.output.engine),
                                        ("resolution", list(self.output.resolution) if self.output.resolution else None),
                                        ("iray_samples", self.output.iray_samples)) if v is not None}
            if render:
                shot["render"] = render
        return cam, shot


Shot._codec = {
    "camera": _CAMERA, "lens": lambda v, p: Lens._load(v, p), "movement": _MOVEMENT,
    "focus": _opt(FocusPull), "frame_range": lambda v, p: None if v is None else tuple(int(x) for x in _floats(2)(v, p)),
    "aspect": _opt(AspectSettings), "blocking": _tuple_of(BlockingBeat), "gaze": _tuple_of(GazeBeat),
    "storyboard": _opt(Storyboard), "output": _opt(RenderOutput),
}


def _unique_ids(shots: Iterable[Shot], what: str) -> None:
    seen: set = set()
    for s in shots:
        if s.id in seen:
            raise ValueError(f"{what}: duplicate shot id {s.id!r}")
        seen.add(s.id)


@dataclass(frozen=True)
class Sequence(_Model):
    """An ordered run of shots that cut together."""

    id: str
    shots: Tuple[Shot, ...] = ()
    lighting: Optional[str] = None
    storyboard: Optional[Storyboard] = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("id must be non-empty")
        _unique_ids(self.shots, f"sequence {self.id!r}")

    def shot(self, shot_id: str) -> Shot:
        for s in self.shots:
            if s.id == shot_id:
                return s
        raise KeyError(shot_id)


Sequence._codec = {"shots": _tuple_of(Shot), "storyboard": _opt(Storyboard)}


@dataclass(frozen=True)
class CoveragePlan(_Model):
    """How a scene is covered: its subjects, line of action and sequences.

    Args:
        id: Plan id.
        subjects: The actor keys the plan covers.
        axis: Optional pair of subject keys defining the line of action
            (the 180-degree line). Stored for the shot library to enforce.
        sequences: The sequences; shot ids are unique across the whole plan.
        lighting: Default lighting continuity key for shots that set none.
        storyboard: Storyboard metadata for the scene.
    """

    id: str
    subjects: Tuple[str, ...] = ()
    axis: Optional[Tuple[str, str]] = None
    sequences: Tuple[Sequence, ...] = ()
    lighting: Optional[str] = None
    storyboard: Optional[Storyboard] = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("id must be non-empty")
        if self.axis is not None:
            if len(self.axis) != 2 or self.axis[0] == self.axis[1]:
                raise ValueError("axis must name two different subjects")
            missing = [a for a in self.axis if a not in self.subjects]
            if missing:
                raise ValueError(f"axis names {missing} which are not in subjects")
        seq_ids = [s.id for s in self.sequences]
        if len(set(seq_ids)) != len(seq_ids):
            raise ValueError("duplicate sequence id")
        _unique_ids(self.all_shots(), f"coverage plan {self.id!r}")

    def all_shots(self) -> Tuple[Shot, ...]:
        return tuple(s for seq in self.sequences for s in seq.shots)

    def lighting_for(self, shot: Shot) -> Optional[str]:
        """The shot's lighting continuity key: its own, its sequence's, else the plan's."""
        if shot.lighting is not None:
            return shot.lighting
        for seq in self.sequences:
            if shot in seq.shots and seq.lighting is not None:
                return seq.lighting
        return self.lighting

    def to_recipe_sections(self) -> dict:
        """``{"cameras": {...}, "shots": [...]}`` for every shot, in plan order.

        Raises:
            ValueError / TypeError: See :meth:`Shot.to_recipe`.
        """
        cameras: dict = {}
        shots: list = []
        for s in self.all_shots():
            cam, spec = s.to_recipe()
            cameras[s.id] = cam
            if spec is not None:
                shots.append(spec)
        return {"cameras": cameras, "shots": shots}

    def merge_into_recipe(self, recipe: Mapping[str, Any]) -> dict:
        """A copy of *recipe* (a dict) with this plan's cameras and shots added.

        Raises:
            ValueError: A camera key or shot id already exists in *recipe*.
        """
        out = copy.deepcopy(dict(recipe))
        sections = self.to_recipe_sections()
        cams = out.setdefault("cameras", {})
        clash = sorted(set(cams) & set(sections["cameras"]))
        existing_shots = {s.get("id") for s in out.get("shots", [])}
        clash += sorted(existing_shots & {s["id"] for s in sections["shots"]})
        if clash:
            raise ValueError(f"recipe already has cameras/shots named {clash}")
        cams.update(sections["cameras"])
        if sections["shots"]:
            out.setdefault("shots", []).extend(sections["shots"])
        return out


CoveragePlan._codec = {
    "subjects": lambda v, p: tuple(v), "axis": lambda v, p: None if v is None else tuple(v),
    "sequences": _tuple_of(Sequence), "storyboard": _opt(Storyboard),
}


def shot_from_recipe_camera(key: str, camera: Mapping[str, Any],
                            shot: Optional[Mapping[str, Any]] = None) -> Shot:
    """Build a :class:`Shot` from a scene-recipe ``cameras[key]`` entry (and optional ``shots[]`` entry).

    Recipe framing cameras without ``angle`` keep the recipe's 10 degree
    default elevation (as an explicit ``elevation_deg``).
    """
    c = dict(camera)
    lens = Lens(focal_length=c.get("focal_length", 50.0), depth_of_field=c.get("depth_of_field", False),
                focal_distance=c.get("focal_distance"))
    if "frame" in c:
        frame = c["frame"]
        cam: Union[Framing, Placement] = Framing(
            subjects=(frame,) if isinstance(frame, str) else tuple(frame),
            size=c.get("shot_type", "medium"), angle=c.get("angle", "eye_level"),
            azimuth_deg=c.get("azimuth_deg", 0.0),
            elevation_deg=None if "angle" in c else c.get("elevation_deg", 10.0),
            composition=c.get("composition", "center"))
    else:
        look = c.get("look_at")
        cam = Placement(position=_vec(c["position"], "position"),
                        look_at=None if look is None else _target(look, "look_at"),
                        rotation=_floats(3)(c.get("rotation"), "rotation"))
    output = None
    if shot is not None:
        r = shot.get("render") or {}
        output = RenderOutput(path=shot["output"], engine=r.get("engine"),
                              resolution=tuple(r["resolution"]) if r.get("resolution") else None,
                              iray_samples=r.get("iray_samples"))
    return Shot(id=key, camera=cam, lens=lens, output=output)


# ---- geometry -------------------------------------------------------------

def framing_distance(size: str, focal_length: float, *, frame_width_mm: float = DEFAULT_FRAME_WIDTH_MM,
                     aspect: float = DEFAULT_ASPECT) -> float:
    """Distance at which *size*'s fit height fills the frame height at *focal_length*.

    Studio's Frame Width spans the frame height whatever the aspect, so the
    distance does not depend on *aspect* (kept for signature compatibility).
    """
    del aspect
    return SHOT_SIZES[size][0] * focal_length / frame_width_mm


def framing_transform(points: "Iterable[Tuple[Vec3, bool]]", framing: Framing, focal_length: float, *,
                      frame_width_mm: float = DEFAULT_FRAME_WIDTH_MM,
                      aspect: float = DEFAULT_ASPECT) -> Tuple[Vec3, Vec3]:
    """Camera ``(position, aim)`` for *framing* of already-resolved subject points.

    Args:
        points: ``(base point, is_figure)`` per subject. Figures are raised by
            the size's anchor height; other points only by
            ``framing.anchor_cm`` (which, when set, raises every point).
        framing: The framing spec.
        focal_length: Lens focal length (mm), used to fit the shot size.
        frame_width_mm: Camera "Frame Width" (mm), which Studio applies to
            the frame height.
        aspect: Frame height / width; sets the frame width for a third
            composition.
    """
    anchor_default = SHOT_SIZES[framing.size][1]
    raised = []
    for p, is_figure in points:
        a = framing.anchor_cm if framing.anchor_cm is not None else (anchor_default if is_figure else 0.0)
        raised.append(Vec3(p.x, p.y + a, p.z) if a else p)
    n = len(raised)
    center = Vec3(sum(p.x for p in raised) / n, sum(p.y for p in raised) / n, sum(p.z for p in raised) / n)
    distance = framing.distance_cm if framing.distance_cm is not None else framing_distance(
        framing.size, focal_length, frame_width_mm=frame_width_mm, aspect=aspect)
    position = spherical_offset(center, framing.azimuth_deg, framing.effective_elevation_deg, distance)
    if framing.composition == "center":
        return position, center
    forward = center - position
    right = forward.cross(Vec3(0.0, 1.0, 0.0))
    if right.length() < 1e-9:  # looking straight up/down: no horizon to slide along
        return position, center
    shift = distance * frame_width_mm / aspect / focal_length / 6.0  # a sixth of the frame width
    # Subject on the left third -> aim to its right, and vice versa.
    sign = 1.0 if framing.composition == "left_third" else -1.0
    return position, center + right.normalize() * (shift * sign)


def _resolve_point(t: Any, subjects: Optional[Mapping[str, Any]]) -> Tuple[Vec3, bool]:
    if isinstance(t, str):
        if subjects is None or t not in subjects:
            raise ValueError(f"subject {t!r} is a key but no 'subjects' mapping resolves it")
        resolved = subjects[t]
        if isinstance(resolved, Vec3):
            return resolved, True
        return resolve_target(resolved), True
    if isinstance(t, Vec3):
        return t, False
    return resolve_target(t), True


def _resolve_aim(t: Any, subjects: Optional[Mapping[str, Any]], offset: float) -> Vec3:
    if isinstance(t, str):
        p, _ = _resolve_point(t, subjects)
        return Vec3(p.x, p.y + offset, p.z) if offset else p
    return resolve_target(t, vertical_offset_cm=offset)


# ---- apply ----------------------------------------------------------------

def _apply_lens(cam: "DazCamera", lens: Lens) -> None:
    cam.focal_length = lens.focal_length
    if lens.depth_of_field is not None:
        cam.depth_of_field = lens.depth_of_field
    if lens.focal_distance is not None:
        cam.focal_distance = lens.focal_distance
    if lens.f_stop is not None:
        cam.f_stop = lens.f_stop


def _apply_aspect(cam: "DazCamera", aspect: Optional[AspectSettings]) -> None:
    if aspect is None:
        return
    for name in ("aspect_width", "aspect_height", "pixels_width", "pixels_height"):
        value = getattr(aspect, name)
        if value is not None:
            setattr(cam, name, value)


def _orbit_target(shot: Shot) -> Any:
    c = shot.camera
    if isinstance(c, Framing):
        return c.subjects[0]
    if c.look_at is None:
        raise ValueError(f"shot {shot.id!r}: an Orbit needs a target (a Framing subject or Placement.look_at)")
    return c.look_at


def apply_shot(
    scene: "DazScene",
    shot: Shot,
    *,
    camera: "DazCamera | None" = None,
    name: str | None = None,
    subjects: Optional[Mapping[str, Any]] = None,
    frame_width_mm: float = DEFAULT_FRAME_WIDTH_MM,
    aspect: float = DEFAULT_ASPECT,
    clear_keys: bool = True,
) -> "DazCamera":
    """Put *shot* into the scene on a camera and return the camera.

    Planning data (blocking, gaze, lighting continuity, storyboard, output)
    is not applied.

    Args:
        scene: A :class:`~dazpy.DazScene`; creates the camera when *camera*
            is ``None`` and widens the anim range for an :class:`Orbit`.
        shot: The shot.
        camera: An existing camera to reuse; otherwise one is created.
        name: Name for a newly created camera.
        subjects: Resolves key targets to a :class:`~dazpy.DazNode` or a
            :class:`~dazpy.math3.Vec3` (an actor root on the floor).
        frame_width_mm: Camera frame width used to fit a :class:`Framing`.
        aspect: Frame height / width used to fit a :class:`Framing`.
        clear_keys: Clear the camera's existing position/rotation (for a
            :class:`Keyframed` move) and focal-distance (for a focus pull)
            keys first. ``False`` adds the shot's keys to what is there, so
            successive moves on one camera chain.

    Raises:
        ValueError: A key target isn't in *subjects*, or an :class:`Orbit`
            has no target.
    """
    movement = shot.movement
    c = shot.camera
    if isinstance(movement, Orbit):
        target_ref = _orbit_target(shot)  # validate before touching the scene
    cam = camera if camera is not None else scene.create_camera(name)

    if isinstance(movement, Orbit):
        scene.set_anim_range(movement.frame_start, movement.frame_end)
        target = _resolve_aim(target_ref, subjects, movement.target_offset_cm)
        cam.focal_length = shot.lens.focal_length
        timeline = DazTimeline(cam._client)
        count = movement.frame_end - movement.frame_start
        for frame in range(movement.frame_start, movement.frame_end + 1):
            t = (frame - movement.frame_start) / count if count > 0 else 0.0
            az = movement.start_azimuth_deg + (movement.end_azimuth_deg - movement.start_azimuth_deg) * t
            pos = spherical_offset(target, az, movement.elevation_deg, movement.radius)
            timeline.frame = frame
            cam.set_position(pos.x, pos.y, pos.z)
            cam.aim_at(target.x, target.y, target.z)
    elif isinstance(movement, Keyframed):
        _apply_lens(cam, shot.lens)
        if clear_keys:
            cam.clear_position_keys()
            if movement.has_orientation:
                cam.clear_rotation_keys()
        for kf in movement.keyframes:
            cam.set_position_at_frame(kf.frame, kf.position.x, kf.position.y, kf.position.z)
            if kf.look_at is not None:
                target = _resolve_aim(kf.look_at, subjects, kf.look_at_offset_cm)
                cam.set_rotation_at_frame(kf.frame, *look_at_euler(kf.position, target))
            elif kf.rotation is not None:
                cam.set_rotation_at_frame(kf.frame, *kf.rotation)
    elif isinstance(c, Framing):
        points = [_resolve_point(s, subjects) for s in c.subjects]
        pos, aim = framing_transform(points, c, shot.lens.focal_length,
                                     frame_width_mm=frame_width_mm, aspect=aspect)
        cam.set_position(pos.x, pos.y, pos.z)
        cam.aim_at(aim.x, aim.y, aim.z)
        _apply_lens(cam, shot.lens)
    else:
        cam.set_position(c.position.x, c.position.y, c.position.z)
        if c.look_at is not None:
            target = _resolve_aim(c.look_at, subjects, c.look_at_offset_cm)
            cam.aim_at(target.x, target.y, target.z)
        elif c.rotation is not None:
            cam.set_rotation(*c.rotation)
        _apply_lens(cam, shot.lens)

    _apply_aspect(cam, shot.aspect)
    if shot.focus is not None:
        cam.depth_of_field = True
        if clear_keys:
            cam.clear_focal_distance_keys()
        for k in shot.focus.keys:
            cam.set_focal_distance_at_frame(k.frame, k.focal_distance)
    return cam


__all__ = [
    "Target", "ShotSize", "CameraAngle", "Composition", "SHOT_SIZES", "CAMERA_ANGLES", "COMPOSITIONS",
    "Lens", "Framing", "Placement", "CameraKeyframe", "Orbit", "Keyframed", "FocusKey", "FocusPull",
    "GazeBeat", "BlockingBeat", "Storyboard", "RenderOutput", "AspectSettings",
    "Shot", "Sequence", "CoveragePlan", "shot_from_recipe_camera",
    "framing_distance", "framing_transform", "apply_shot",
]
