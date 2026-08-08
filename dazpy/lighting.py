"""Domain-level lighting rigs built on the DazLight/DazScene primitives.

Provides :func:`apply_three_point_light_setup` for creating a conventional
key/fill/rim light rig around a target, either via angle/distance placement
or explicit world-space positions.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .math3 import Vec3

if TYPE_CHECKING:
    from ._light import DazLight
    from ._node import DazNode
    from ._render import DazRenderSettings
    from ._scene import DazScene


def _spherical_offset(
    target: Vec3, azimuth_deg: float, elevation_deg: float, distance: float
) -> Vec3:
    """Return a point *distance* away from *target*, at the given angles.

    ``azimuth_deg=0, elevation_deg=0`` sits on the target's ``+Z`` side.
    Increasing ``azimuth_deg`` sweeps from ``+Z`` toward ``+X``.
    ``elevation_deg`` tilts the offset up toward ``+Y``; at ``elevation_deg=90``
    the result is directly above the target regardless of azimuth.
    """
    az = math.radians(azimuth_deg)
    el = math.radians(elevation_deg)
    horizontal = math.cos(el)
    direction = Vec3(horizontal * math.sin(az), math.sin(el), horizontal * math.cos(az))
    return target + direction * distance


def _look_at_euler(from_pos: Vec3, to_pos: Vec3) -> tuple[float, float, float]:
    """Return ``(x, y, z)`` world-space Euler degrees aiming *from_pos* at *to_pos*.

    Suitable for passing directly to :meth:`~dazpy.DazNode.set_rotation`. A
    light positioned via :func:`_spherical_offset` with ``azimuth_deg=0,
    elevation_deg=0`` and aimed with this function at the same target gets
    rotation ``(0, 0, 0)`` — i.e. a light's unrotated rest pose is defined as
    facing ``-Z``. Roll (``z``) is always ``0.0``; lights have no meaningful
    "up" for aiming purposes.

    The yaw sign was confirmed empirically against a live DAZ Studio session
    (see beads issue daz-script-server-bu86): a distant light rotated to
    ``y=+90`` reports :meth:`~dazpy.DazLight.direction` of ``(-1, 0, ~0)``,
    matching this function's convention.
    """
    direction = (to_pos - from_pos).normalize()
    horizontal_dist = math.sqrt(direction.x * direction.x + direction.z * direction.z)
    pitch = math.degrees(math.atan2(direction.y, horizontal_dist))
    if horizontal_dist < 1e-9:
        yaw = 0.0
    else:
        yaw = math.degrees(math.atan2(-direction.x, -direction.z))
    return (pitch, yaw, 0.0)


@dataclass(frozen=True)
class LightSpec:
    """One light's placement and output within a rig.

    Args:
        role: Informational label, e.g. ``"key"``, ``"fill"``, ``"rim"``.
        azimuth_deg: See :func:`_spherical_offset`. Ignored if *position* is set.
        elevation_deg: See :func:`_spherical_offset`. Ignored if *position* is set.
        distance: Distance from the target, in DAZ Studio units (cm).
            Ignored if *position* is set.
        intensity: Passed straight to :attr:`~dazpy.DazLight.intensity`.
        color: ``(r, g, b)`` in the 0-255 range, passed to
            :meth:`~dazpy.DazLight.set_color`.
        position: Explicit world-space override. When set, *azimuth_deg*,
            *elevation_deg*, and *distance* are ignored entirely.
    """

    role: str
    azimuth_deg: float
    elevation_deg: float
    distance: float
    intensity: float
    color: tuple[int, int, int] = (255, 255, 255)
    position: Vec3 | None = None


_DEFAULT_KEY = LightSpec(role="key", azimuth_deg=45.0, elevation_deg=30.0, distance=150.0, intensity=100.0)
_DEFAULT_FILL = LightSpec(role="fill", azimuth_deg=-45.0, elevation_deg=15.0, distance=150.0, intensity=50.0)
_DEFAULT_RIM = LightSpec(role="rim", azimuth_deg=180.0, elevation_deg=45.0, distance=150.0, intensity=75.0)


@dataclass(frozen=True)
class ThreePointLightSetup:
    """Input spec for a three-point light rig.

    Args:
        target: The point to light, as a :class:`~dazpy.math3.Vec3` world
            position or a :class:`~dazpy.DazNode` (its
            :attr:`~dazpy.DazNode.position` is used).
        key: Key light placement/output. Defaults to a 45deg/30deg key light.
        fill: Fill light placement/output. Defaults to a -45deg/15deg fill light.
        rim: Rim light placement/output. Defaults to a 180deg/45deg rim light.
        light_type: Forwarded to :meth:`~dazpy.DazScene.create_light` for all
            three lights — one of ``"spot"``, ``"point"``, ``"distant"``.
    """

    target: Vec3 | DazNode
    key: LightSpec = _DEFAULT_KEY
    fill: LightSpec = _DEFAULT_FILL
    rim: LightSpec = _DEFAULT_RIM
    light_type: str = "spot"


@dataclass(frozen=True)
class ThreePointLightRig:
    """Handles to the three lights created by :func:`apply_three_point_light_setup`."""

    key: DazLight
    fill: DazLight
    rim: DazLight


def _resolve_target(target: Vec3 | DazNode) -> Vec3:
    if isinstance(target, Vec3):
        return target
    position = target.position
    if position is None:
        raise ValueError("ThreePointLightSetup target node has no position (it may not exist in the scene)")
    return Vec3.from_dict(position)


def _resolve_light_position(target: Vec3, spec: LightSpec) -> Vec3:
    if spec.position is not None:
        return spec.position
    return _spherical_offset(target, spec.azimuth_deg, spec.elevation_deg, spec.distance)


def _place_light(scene: DazScene, target: Vec3, spec: LightSpec, light_type: str) -> DazLight:
    light = scene.create_light(light_type, name=spec.role)
    pos = _resolve_light_position(target, spec)
    light.set_position(pos.x, pos.y, pos.z)
    pitch, yaw, roll = _look_at_euler(pos, target)
    light.set_rotation(pitch, yaw, roll)
    light.intensity = spec.intensity
    light.set_color(*spec.color)
    return light


def apply_three_point_light_setup(scene: DazScene, setup: ThreePointLightSetup) -> ThreePointLightRig:
    """Create and place a key/fill/rim light rig around *setup.target*.

    Args:
        scene: A :class:`~dazpy.DazScene`.
        setup: The rig configuration.

    Returns:
        A :class:`ThreePointLightRig` with handles to the three created lights.
    """
    target = _resolve_target(setup.target)
    key_light = _place_light(scene, target, setup.key, setup.light_type)
    fill_light = _place_light(scene, target, setup.fill, setup.light_type)
    rim_light = _place_light(scene, target, setup.rim, setup.light_type)
    return ThreePointLightRig(key=key_light, fill=fill_light, rim=rim_light)


@dataclass(frozen=True)
class HDRIEnvironment:
    """Image-based (HDRI/dome) lighting configuration.

    Args:
        image_path: Absolute path to an HDRI/environment map on disk. Must
            exist -- validated by :func:`apply_hdri_environment` before any
            DazScript call is made.
        intensity: Passed to the Iray "Environment Intensity" property.
        rotation_deg: Passed to the Iray "Dome Rotation" property.
        mode: One of ``"dome_only"``, ``"dome_and_scene"``, ``"scene_only"``.
            Maps to the DazScript "Environment Mode" enum. Procedural
            Sun-Sky mode is intentionally not exposed here.
        draw_dome: Whether the dome image is visible as a backdrop in the
            viewport/render (Iray "Draw Dome"), independent of whether it
            lights the scene.
        resolution: Iray "Environment Lighting Resolution" (IBL sampling
            quality). ``None`` leaves DAZ Studio's current value untouched.
    """

    image_path: str
    intensity: float = 1.0
    rotation_deg: float = 0.0
    mode: str = "dome_only"
    draw_dome: bool = False
    resolution: int | None = None
