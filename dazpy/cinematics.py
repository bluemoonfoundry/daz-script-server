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
