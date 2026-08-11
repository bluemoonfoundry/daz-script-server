from __future__ import annotations

import math
from typing import TYPE_CHECKING

from .math3 import Vec3

if TYPE_CHECKING:
    from ._node import DazNode


def spherical_offset(
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


def look_at_euler(from_pos: Vec3, to_pos: Vec3) -> tuple[float, float, float]:
    """Return ``(x, y, z)`` world-space Euler degrees aiming *from_pos* at *to_pos*.

    Suitable for passing directly to :meth:`~dazpy.DazNode.set_rotation`. A
    node positioned via :func:`spherical_offset` with ``azimuth_deg=0,
    elevation_deg=0`` and aimed with this function at the same target gets
    rotation ``(0, 0, 0)`` — i.e. the unrotated rest pose is defined as
    facing ``-Z``. Roll (``z``) is always ``0.0``.

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


def resolve_target(target: "Vec3 | DazNode", vertical_offset_cm: float = 0.0) -> Vec3:
    """Resolve *target* to a :class:`~dazpy.math3.Vec3`, raised by *vertical_offset_cm*.

    If *target* is already a :class:`~dazpy.math3.Vec3`, it is used as-is
    (before the offset). If it's a :class:`~dazpy.DazNode`, its
    :attr:`~dazpy.DazNode.position` is read and converted via
    :meth:`~dazpy.math3.Vec3.from_dict`.

    *vertical_offset_cm* is added to the resolved Y (DAZ Studio's up axis)
    component. This exists primarily to compensate for the fact that a
    figure's :class:`~dazpy.DazNode.position` is generally its root/hip
    joint, not its center of mass or head — framing code that wants to aim
    higher (e.g. chest/head height for a tight shot) passes a positive
    offset here rather than aiming straight at the hip.

    Raises:
        ValueError: If *target* is a node and its position is unavailable
            (e.g. the node no longer exists in the scene).
    """
    if isinstance(target, Vec3):
        base = target
    else:
        position = target.position
        if position is None:
            raise ValueError("resolve_target: target node has no position (it may not exist in the scene)")
        base = Vec3.from_dict(position)
    if vertical_offset_cm == 0.0:
        return base
    return Vec3(base.x, base.y + vertical_offset_cm, base.z)
