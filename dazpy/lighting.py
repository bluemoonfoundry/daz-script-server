"""Domain-level lighting rigs built on the DazLight/DazScene primitives.

Provides :func:`apply_three_point_light_setup` for creating a conventional
key/fill/rim light rig around a target, either via angle/distance placement
or explicit world-space positions.
"""

from __future__ import annotations

import math

from .math3 import Vec3


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
    """
    direction = (to_pos - from_pos).normalize()
    horizontal_dist = math.sqrt(direction.x * direction.x + direction.z * direction.z)
    pitch = math.degrees(math.atan2(direction.y, horizontal_dist))
    if horizontal_dist < 1e-9:
        yaw = 0.0
    else:
        yaw = math.degrees(math.atan2(direction.x, -direction.z))
    return (pitch, yaw, 0.0)
