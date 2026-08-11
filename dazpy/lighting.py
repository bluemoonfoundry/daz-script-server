"""Domain-level lighting rigs built on the DazLight/DazScene primitives.

Provides :func:`apply_three_point_light_setup` for creating a conventional
key/fill/rim light rig around a target, either via angle/distance placement
or explicit world-space positions. Also provides :func:`apply_hdri_environment`
for image-based (HDRI/dome) lighting via :class:`HDRIEnvironment`.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .exceptions import RenderError
from .math3 import Vec3
from ._shot_geometry import spherical_offset as _spherical_offset
from ._shot_geometry import look_at_euler as _look_at_euler
from ._shot_geometry import resolve_target as _resolve_target

if TYPE_CHECKING:
    from ._light import DazLight
    from ._node import DazNode
    from ._render import DazRenderSettings
    from ._scene import DazScene


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


_HDRI_MODE_LABELS = {
    "dome_only": "Dome Only",
    "dome_and_scene": "Dome and Scene",
    "scene_only": "Scene Only",
}


def apply_hdri_environment(render_settings: DazRenderSettings, env: HDRIEnvironment) -> None:
    """Apply image-based (HDRI/dome) lighting via *render_settings*.

    Args:
        render_settings: A :class:`~dazpy.DazRenderSettings`.
        env: The environment configuration.

    Raises:
        FileNotFoundError: If ``env.image_path`` does not exist on disk.
            Checked before any DazScript call is made -- an invalid path
            passed to the underlying ``setMap()`` call can hang or crash
            DAZ Studio via a blocking file-not-found dialog.
        ValueError: If ``env.mode`` is not one of ``"dome_only"``,
            ``"dome_and_scene"``, ``"scene_only"``.
        RenderError: If a post-apply readback of "Environment Intensity"
            doesn't match *env.intensity*. All of this module's environment
            writes go through ``DazRenderSettings._environment_holder()``,
            which assumes ``getRenderElementObjects()[3]`` is always the
            Environment property holder -- confirmed on one live DAZ Studio
            4.x instance only. If that index is wrong on a different DAZ
            Studio version, every write above silently no-ops (matching the
            existing ``if (!holder) return;`` pattern) with no exception, so
            this readback is what actually catches it.
    """
    if not os.path.isfile(env.image_path):
        raise FileNotFoundError(f"HDRI/environment map not found: {env.image_path}")
    if env.mode not in _HDRI_MODE_LABELS:
        raise ValueError(
            f"Invalid HDRIEnvironment.mode {env.mode!r}; must be one of {sorted(_HDRI_MODE_LABELS)}"
        )
    render_settings._set_environment_map(env.image_path)
    render_settings._set_environment_property("Environment Intensity", env.intensity)
    render_settings._set_environment_property("Dome Rotation", env.rotation_deg)
    render_settings._set_environment_property_from_string("Environment Mode", _HDRI_MODE_LABELS[env.mode])
    render_settings._set_environment_property("Draw Dome", env.draw_dome)
    if env.resolution is not None:
        render_settings._set_environment_property("Environment Lighting Resolution", env.resolution)

    readback = render_settings._get_environment_property("Environment Intensity")
    if readback is None or not math.isclose(float(readback), env.intensity, rel_tol=1e-6, abs_tol=1e-6):
        raise RenderError(
            "HDRI environment apply failed verification: 'Environment Intensity' "
            f"readback ({readback!r}) does not match the requested value "
            f"({env.intensity!r}). The environment property holder "
            "(getRenderElementObjects()[3]) may be unavailable or at a "
            "different index on this DAZ Studio version/build -- the HDRI "
            "was likely never applied."
        )
