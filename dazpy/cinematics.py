"""Domain-level camera shot builders built on the DazCamera/DazScene primitives.

Provides :func:`apply_static_shot` for a single camera placement/framing,
:func:`apply_orbit_camera` for a per-frame orbit sweep around a target, and
:func:`apply_frame_subject` for distance-preset framing of a subject. All
three write static per-frame placements, not real interpolated keyframes —
see the module's design spec for why (``CinematicAnimatedShot`` is a
separate, deferred follow-up).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .math3 import Vec3
from ._shot_geometry import resolve_target, spherical_offset
from ._timeline import DazTimeline

if TYPE_CHECKING:
    from ._camera import DazCamera
    from ._node import DazNode
    from ._scene import DazScene


def _resolve_camera(scene: "DazScene", camera: "DazCamera | None", name: str | None) -> "DazCamera":
    if camera is not None:
        return camera
    return scene.create_camera(name)


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
    cam = _resolve_camera(scene, camera, name)
    cam.set_position(shot.position.x, shot.position.y, shot.position.z)
    if shot.look_at is not None:
        target = resolve_target(shot.look_at, vertical_offset_cm=shot.look_at_offset_cm)
        cam.aim_at(target.x, target.y, target.z)
    elif shot.rotation is not None:
        cam.set_rotation(*shot.rotation)
    cam.focal_length = shot.focal_length
    cam.depth_of_field = shot.depth_of_field
    if shot.focal_distance is not None:
        cam.focal_distance = shot.focal_distance
    if shot.aspect_width is not None:
        cam.aspect_width = shot.aspect_width
    if shot.aspect_height is not None:
        cam.aspect_height = shot.aspect_height
    if shot.pixels_width is not None:
        cam.pixels_width = shot.pixels_width
    if shot.pixels_height is not None:
        cam.pixels_height = shot.pixels_height
    return cam


def _lerp(start: float, end: float, t: float) -> float:
    return start + (end - start) * t


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
            interpolated between the two across the frame range.
        frame_start: First timeline frame (inclusive).
        frame_end: Last timeline frame (inclusive).
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


def apply_orbit_camera(
    scene: "DazScene",
    orbit: OrbitCamera,
    *,
    camera: "DazCamera | None" = None,
    name: str | None = None,
) -> "DazCamera":
    """Sweep a camera around *orbit.target* across its frame range.

    Args:
        scene: A :class:`~dazpy.DazScene`. Only used to create a new camera
            when *camera* is ``None``.
        orbit: The orbit configuration.
        camera: An existing :class:`~dazpy.DazCamera` to reuse/mutate.
            When ``None`` (the default), a new camera is created via
            ``scene.create_camera(name)``.
        name: Optional name for a newly created camera. Ignored when
            *camera* is given.

    Returns:
        The configured :class:`~dazpy.DazCamera`.
    """
    cam = _resolve_camera(scene, camera, name)
    target = resolve_target(orbit.target, vertical_offset_cm=orbit.target_offset_cm)
    cam.focal_length = orbit.focal_length
    timeline = DazTimeline(cam._client)
    frame_count = orbit.frame_end - orbit.frame_start
    for frame in range(orbit.frame_start, orbit.frame_end + 1):
        t = (frame - orbit.frame_start) / frame_count if frame_count > 0 else 0.0
        azimuth = _lerp(orbit.start_azimuth_deg, orbit.end_azimuth_deg, t)
        pos = spherical_offset(target, azimuth, orbit.elevation_deg, orbit.radius)
        timeline.frame = frame
        cam.set_position(pos.x, pos.y, pos.z)
        cam.aim_at(target.x, target.y, target.z)
    return cam


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
    if frame.shot_type not in _SHOT_DISTANCES:
        raise ValueError(
            f"Invalid FrameSubject.shot_type {frame.shot_type!r}; must be one of {sorted(_SHOT_DISTANCES)}"
        )
    cam = _resolve_camera(scene, camera, name)
    offset = frame.target_offset_cm if frame.target_offset_cm is not None else _SHOT_TARGET_OFFSETS_CM[frame.shot_type]
    target = resolve_target(frame.subject, vertical_offset_cm=offset)
    pos = spherical_offset(target, frame.azimuth_deg, frame.elevation_deg, _SHOT_DISTANCES[frame.shot_type])
    cam.set_position(pos.x, pos.y, pos.z)
    cam.aim_at(target.x, target.y, target.z)
    cam.focal_length = frame.focal_length
    return cam
