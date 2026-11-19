"""Domain-level camera shot builders built on the DazCamera/DazScene primitives.

Provides :func:`apply_static_shot` for a single camera placement/framing,
:func:`apply_orbit_camera` for a per-frame orbit sweep around a target,
:func:`apply_frame_subject` for distance-preset framing of a subject, and
:func:`apply_animated_shot` for a camera move driven by real DAZ Studio
keyframes (:meth:`~dazpy.DazNode.set_position_at_frame` /
:meth:`~dazpy.DazNode.set_rotation_at_frame`) rather than a per-frame
setValue bake — DAZ Studio interpolates between the given waypoints itself.

Each builder is a thin adapter over the typed models in :mod:`dazpy.shots`:
``spec.to_shot()`` gives the equivalent :class:`~dazpy.shots.Shot`, and the
``apply_*`` functions are :func:`~dazpy.shots.apply_shot` on it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .math3 import Vec3
from .shots import (
    CameraKeyframe,
    AspectSettings,
    Framing,
    Keyframed,
    Lens,
    Orbit,
    Placement,
    Shot,
    apply_shot,
)

if TYPE_CHECKING:
    from ._camera import DazCamera
    from ._node import DazNode
    from ._scene import DazScene


@dataclass(frozen=True)
class CinematicStaticShot:
    """A single camera placement and optics configuration.

    Args:
        position: World-space camera position.
        look_at: Aim target passed to :meth:`~dazpy.DazCamera.aim_at`. A
            :class:`~dazpy.DazNode` is resolved via its
            :attr:`~dazpy.DazNode.position`, raised by *look_at_offset_cm*.
            Ignored if ``None``; in that case *rotation* (if set) is used
            instead.
        look_at_offset_cm: Vertical offset (cm) applied when resolving
            *look_at* — see :func:`~dazpy._shot_geometry.resolve_target`.
            Defaults to ``0.0`` since this API already takes an explicit
            *position*/*look_at* the caller fully controls.
        rotation: Explicit ``(x, y, z)`` degrees passed to
            :meth:`~dazpy.DazNode.set_rotation`. Ignored if *look_at* is set.
        focal_length: Passed to :attr:`~dazpy.DazCamera.focal_length`.
        depth_of_field: Passed to :attr:`~dazpy.DazCamera.depth_of_field`.
        focal_distance: Passed to :attr:`~dazpy.DazCamera.focal_distance`
            when not ``None``; otherwise DAZ's current value is untouched.
        aspect_width: Passed to :attr:`~dazpy.DazCamera.aspect_width` when
            not ``None``.
        aspect_height: Passed to :attr:`~dazpy.DazCamera.aspect_height` when
            not ``None``.
        pixels_width: Passed to :attr:`~dazpy.DazCamera.pixels_width` when
            not ``None``.
        pixels_height: Passed to :attr:`~dazpy.DazCamera.pixels_height` when
            not ``None``.
    """

    position: Vec3
    look_at: "Vec3 | DazNode | None" = None
    look_at_offset_cm: float = 0.0
    rotation: tuple[float, float, float] | None = None
    focal_length: float = 50.0
    depth_of_field: bool = False
    focal_distance: float | None = None
    aspect_width: float | None = None
    aspect_height: float | None = None
    pixels_width: int | None = None
    pixels_height: int | None = None

    def to_shot(self, shot_id: str = "static") -> Shot:
        """The equivalent :class:`~dazpy.shots.Shot`."""
        aspect = AspectSettings(self.aspect_width, self.aspect_height, self.pixels_width, self.pixels_height)
        return Shot(
            id=shot_id,
            camera=Placement(position=self.position, look_at=self.look_at,
                             look_at_offset_cm=self.look_at_offset_cm, rotation=self.rotation),
            lens=Lens(focal_length=self.focal_length, depth_of_field=self.depth_of_field,
                      focal_distance=self.focal_distance),
            aspect=None if aspect == AspectSettings() else aspect,
        )


def apply_static_shot(
    scene: "DazScene",
    shot: CinematicStaticShot,
    *,
    camera: "DazCamera | None" = None,
    name: str | None = None,
) -> "DazCamera":
    """Place and configure a camera for *shot* in a single HTTP-round-trip set.

    Args:
        scene: A :class:`~dazpy.DazScene`. Only used to create a new camera
            when *camera* is ``None``.
        shot: The placement/optics configuration.
        camera: An existing :class:`~dazpy.DazCamera` to reuse/mutate.
            When ``None`` (the default), a new camera is created via
            ``scene.create_camera(name)``.
        name: Optional name for a newly created camera. Ignored when
            *camera* is given.

    Returns:
        The configured :class:`~dazpy.DazCamera` (either *camera* or the
        newly created one).
    """
    return apply_shot(scene, shot.to_shot(), camera=camera, name=name)


@dataclass(frozen=True)
class OrbitCamera:
    """A camera sweeping around a target across a frame range.

    Writes a static per-frame placement at each timeline frame — this is
    **not** a real interpolated keyframe animation (see the module
    docstring). Whether the sweep persists as visible motion when scrubbing
    the timeline afterward depends on DAZ Studio's key/animation mode at
    call time; that's the caller's responsibility.

    Args:
        target: The point to orbit around, as a
            :class:`~dazpy.math3.Vec3` world position or a
            :class:`~dazpy.DazNode` (its :attr:`~dazpy.DazNode.position`,
            raised by *target_offset_cm*, is used).
        radius: Orbit radius from the target, in DAZ Studio units (cm).
        elevation_deg: Constant elevation angle throughout the orbit — see
            :func:`~dazpy._shot_geometry.spherical_offset`.
        start_azimuth_deg: Azimuth at *frame_start*.
        end_azimuth_deg: Azimuth at *frame_end*. Azimuth is linearly
            interpolated between the two across the frame range. Note the
            class defaults sweep a full 0-360 degrees, which gives
            *frame_start* and *frame_end* the same azimuth (a duplicate
            endpoint) -- callers wanting a seamless loop should use e.g.
            ``end_azimuth_deg=356.0`` or ``frame_end=frame_start+89``
            instead of a full 360.
        frame_start: First timeline frame (inclusive).
        frame_end: Last timeline frame (inclusive). Must be ``>=``
            *frame_start*.
        focal_length: Passed to :attr:`~dazpy.DazCamera.focal_length` once,
            before the per-frame sweep.
        target_offset_cm: Vertical offset (cm) applied when resolving
            *target* — see :func:`~dazpy._shot_geometry.resolve_target`.
            Defaults to ``25.0`` (chest height) since a figure's resolved
            position is generally its root/hip joint and a close orbit
            radius aimed straight at it risks clipping the head.
    """

    target: "Vec3 | DazNode"
    radius: float
    elevation_deg: float = 15.0
    start_azimuth_deg: float = 0.0
    end_azimuth_deg: float = 360.0
    frame_start: int = 0
    frame_end: int = 90
    focal_length: float = 50.0
    target_offset_cm: float = 25.0

    def to_shot(self, shot_id: str = "orbit") -> Shot:
        """The equivalent :class:`~dazpy.shots.Shot`.

        Raises:
            ValueError: If *frame_end* is less than *frame_start*.
        """
        return Shot(
            id=shot_id,
            camera=Framing(subjects=(self.target,), size="medium"),
            lens=Lens(focal_length=self.focal_length),
            movement=Orbit(radius=self.radius, elevation_deg=self.elevation_deg,
                           start_azimuth_deg=self.start_azimuth_deg, end_azimuth_deg=self.end_azimuth_deg,
                           frame_start=self.frame_start, frame_end=self.frame_end,
                           target_offset_cm=self.target_offset_cm),
        )


def apply_orbit_camera(
    scene: "DazScene",
    orbit: OrbitCamera,
    *,
    camera: "DazCamera | None" = None,
    name: str | None = None,
) -> "DazCamera":
    """Sweep a camera around *orbit.target* across its frame range.

    Side effects: this widens/sets the scene's animation range to
    ``[orbit.frame_start, orbit.frame_end]`` via
    :meth:`~dazpy.DazScene.set_anim_range` -- without this, DAZ Studio's
    ``Scene.setFrame()`` clamps to the scene's existing animation range
    (typically 0-30 on a fresh scene), silently overwriting later frames
    onto the clamped one. The scene's timeline frame is also left parked at
    *orbit.frame_end* when this function returns -- it is not restored to
    whatever frame was current beforehand.

    Args:
        scene: A :class:`~dazpy.DazScene`. Used to create a new camera when
            *camera* is ``None``, and to widen the animation range to cover
            the orbit's frame range.
        orbit: The orbit configuration.
        camera: An existing :class:`~dazpy.DazCamera` to reuse/mutate.
            When ``None`` (the default), a new camera is created via
            ``scene.create_camera(name)``.
        name: Optional name for a newly created camera. Ignored when
            *camera* is given.

    Returns:
        The configured :class:`~dazpy.DazCamera`.

    Raises:
        ValueError: If ``orbit.frame_end`` is less than ``orbit.frame_start``.
    """
    return apply_shot(scene, orbit.to_shot(), camera=camera, name=name)


_SHOT_DISTANCES = {"close_up": 60.0, "medium": 150.0, "full_body": 300.0}
_SHOT_TARGET_OFFSETS_CM = {"close_up": 45.0, "medium": 25.0, "full_body": 0.0}


@dataclass(frozen=True)
class FrameSubject:
    """A camera framing a subject at a named shot distance.

    Args:
        subject: The point to frame, as a :class:`~dazpy.math3.Vec3` world
            position or a :class:`~dazpy.DazNode` (its
            :attr:`~dazpy.DazNode.position`, raised by *target_offset_cm*,
            is used).
        shot_type: One of ``"close_up"``, ``"medium"``, ``"full_body"`` —
            maps to a preset distance via a module-level table.
        azimuth_deg: Camera azimuth around the subject — see
            :func:`~dazpy._shot_geometry.spherical_offset`.
        elevation_deg: Camera elevation around the subject.
        focal_length: Passed to :attr:`~dazpy.DazCamera.focal_length`.
        target_offset_cm: Vertical offset (cm) applied when resolving
            *subject* — see :func:`~dazpy._shot_geometry.resolve_target`.
            ``None`` (the default) uses the *shot_type*'s entry in
            ``_SHOT_TARGET_OFFSETS_CM`` (tighter shots aim higher, to
            compensate for a figure's resolved position being its
            root/hip joint rather than chest/head height).
    """

    subject: "Vec3 | DazNode"
    shot_type: str = "medium"
    azimuth_deg: float = 0.0
    elevation_deg: float = 10.0
    focal_length: float = 50.0
    target_offset_cm: float | None = None

    def to_shot(self, shot_id: str = "frame_subject") -> Shot:
        """The equivalent :class:`~dazpy.shots.Shot`.

        Keeps this builder's fixed, focal-length-independent distances and
        aim offsets (``distance_cm`` / ``anchor_cm``) rather than the
        focal-fitted :data:`~dazpy.shots.SHOT_SIZES`.

        Raises:
            ValueError: If *shot_type* is not one of ``"close_up"``,
                ``"medium"``, ``"full_body"``.
        """
        if self.shot_type not in _SHOT_DISTANCES:
            raise ValueError(
                f"Invalid FrameSubject.shot_type {self.shot_type!r}; must be one of {sorted(_SHOT_DISTANCES)}"
            )
        offset = self.target_offset_cm if self.target_offset_cm is not None else _SHOT_TARGET_OFFSETS_CM[self.shot_type]
        return Shot(
            id=shot_id,
            camera=Framing(subjects=(self.subject,), size=self.shot_type, azimuth_deg=self.azimuth_deg,
                           elevation_deg=self.elevation_deg, distance_cm=_SHOT_DISTANCES[self.shot_type],
                           anchor_cm=offset),
            lens=Lens(focal_length=self.focal_length),
        )


def apply_frame_subject(
    scene: "DazScene",
    frame: FrameSubject,
    *,
    camera: "DazCamera | None" = None,
    name: str | None = None,
) -> "DazCamera":
    """Place and aim a camera to frame *frame.subject* at its shot distance.

    Args:
        scene: A :class:`~dazpy.DazScene`. Only used to create a new camera
            when *camera* is ``None``.
        frame: The framing configuration.
        camera: An existing :class:`~dazpy.DazCamera` to reuse/mutate.
            When ``None`` (the default), a new camera is created via
            ``scene.create_camera(name)``.
        name: Optional name for a newly created camera. Ignored when
            *camera* is given.

    Returns:
        The configured :class:`~dazpy.DazCamera`.

    Raises:
        ValueError: If ``frame.shot_type`` is not one of ``"close_up"``,
            ``"medium"``, ``"full_body"``.
    """
    return apply_shot(scene, frame.to_shot(), camera=camera, name=name)


@dataclass(frozen=True)
class CinematicAnimatedShot:
    """A camera move driven by real DAZ Studio keyframes.

    Unlike :class:`OrbitCamera` (which bakes a value on every timeline
    frame), this writes one keyframe per :class:`CameraKeyframe` waypoint
    and lets DAZ Studio interpolate the frames in between via its own
    animation curves.

    Args:
        keyframes: The waypoints, in ascending, unique *frame* order (at
            least two). Either every waypoint must specify an orientation
            (*look_at* or *rotation*) or none must — a partial mix would
            leave the rotation curve keyed at only some waypoints, holding
            a stale orientation between them.
        focal_length: Passed to :attr:`~dazpy.DazCamera.focal_length` once,
            before the keyframes are written.
        depth_of_field: Passed to :attr:`~dazpy.DazCamera.depth_of_field`
            once.
        focal_distance: Passed to :attr:`~dazpy.DazCamera.focal_distance`
            once, when not ``None``; otherwise DAZ's current value is
            untouched.
    """

    keyframes: tuple[CameraKeyframe, ...]
    focal_length: float = 50.0
    depth_of_field: bool = False
    focal_distance: float | None = None

    def to_shot(self, shot_id: str = "animated") -> Shot:
        """The equivalent :class:`~dazpy.shots.Shot`.

        Raises:
            ValueError: See :func:`apply_animated_shot`.
        """
        move = Keyframed(keyframes=tuple(self.keyframes))
        return Shot(
            id=shot_id,
            camera=Placement(position=move.keyframes[0].position),
            lens=Lens(focal_length=self.focal_length, depth_of_field=self.depth_of_field,
                      focal_distance=self.focal_distance),
            movement=move,
        )


def apply_animated_shot(
    scene: "DazScene",
    shot: CinematicAnimatedShot,
    *,
    camera: "DazCamera | None" = None,
    name: str | None = None,
) -> "DazCamera":
    """Write *shot.keyframes* as real DAZ Studio keyframes on a camera.

    Side effects: clears any existing keys on the camera's position
    controls (via :meth:`~dazpy.DazNode.clear_position_keys`) before
    writing the new curve — a freshly created camera can already carry a
    default key from creation time, which would otherwise distort
    interpolation/extrapolation around the new keyframes. Rotation
    controls are cleared the same way, but only if at least one keyframe
    specifies an orientation.

    Args:
        scene: A :class:`~dazpy.DazScene`. Only used to create a new camera
            when *camera* is ``None``.
        shot: The keyframe sequence and optics configuration.
        camera: An existing :class:`~dazpy.DazCamera` to reuse/mutate.
            When ``None`` (the default), a new camera is created via
            ``scene.create_camera(name)``.
        name: Optional name for a newly created camera. Ignored when
            *camera* is given.

    Returns:
        The configured :class:`~dazpy.DazCamera`.

    Raises:
        ValueError: If fewer than two keyframes are given, if their
            *frame* values are not strictly ascending, or if only some
            keyframes specify an orientation (*look_at*/*rotation*).
    """
    return apply_shot(scene, shot.to_shot(), camera=camera, name=name)
