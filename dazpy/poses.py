"""Domain-level pose convenience wrappers built on the DazPose/DazNode/DazSkeleton primitives.

Provides :func:`apply_pose`, :func:`zero_figure`, and :func:`reset_transforms`
so common pose operations don't require hand-assembling :class:`~dazpy.DazPose`
objects or knowing which primitive combination zeroes a figure or resets a
node's transform.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ._pose import DazPose

if TYPE_CHECKING:
    from ._node import DazNode
    from ._skeleton import DazSkeleton


def apply_pose(skeleton: "DazSkeleton", pose: "DazPose | str | Path") -> None:
    """Apply *pose* to *skeleton* in a single HTTP call.

    Args:
        skeleton: The figure to pose.
        pose: A :class:`~dazpy.DazPose` instance, or a path to a pose JSON
            file (loaded via :meth:`~dazpy.DazPose.load` first).
    """
    if isinstance(pose, (str, Path)):
        pose = DazPose.load(pose)
    pose.apply(skeleton)


def reset_transforms(node: "DazNode") -> None:
    """Reset *node*'s local position and rotation to zero, and scale to 1.0.

    Works on any :class:`~dazpy.DazNode` — camera, prop, or figure root.

    Args:
        node: The node to reset.
    """
    node.set_local_position(0.0, 0.0, 0.0)
    node.set_local_rotation(0.0, 0.0, 0.0)
    node.set_scale(1.0, 1.0, 1.0)
