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
    Uses a single DazScript evaluation via :meth:`~dazpy.DazNode.set_transform`.

    Args:
        node: The node to reset.
    """
    node.set_transform(
        position=(0.0, 0.0, 0.0),
        rotation=(0.0, 0.0, 0.0),
        scale=(1.0, 1.0, 1.0),
    )


def zero_figure(skeleton: "DazSkeleton", *, include_props: bool = False) -> None:
    """Drive every bone rotation and morph on *skeleton* to zero.

    The default (``include_props=False``) is what guarantees this function
    never touches the figure's root position/rotation/scale — use
    :func:`reset_transforms` for that instead.

    Args:
        skeleton: The figure to zero.
        include_props: When ``True``, node-level numeric properties are also
            zeroed, via :meth:`~dazpy.DazPose.apply_full`. This is **opt-in**,
            not the default: ``apply_full`` writes 0 for every property
            returned by the figure's node-property enumeration that is
            *absent* from the pose it's given, and every other caller passes
            a captured pose whose ``props`` dict already contains those
            values. ``zero_figure`` instead passes an empty ``props={}``, so
            with ``include_props=True`` that "absent → 0" fallback can drive
            built-in transform-adjacent dials — e.g. the figure's general
            Scale property (see the DzERCLink comment in ``dazpy/_pose.py``
            around line 117-125) — to 0, contradicting the "does not touch
            root transform" guarantee. Only pass ``True`` if you know your
            rig doesn't route transforms through its node-property list.

            The two modes also differ in how they write ERC-driven channels:
            the ``True`` path goes through :meth:`~dazpy.DazPose.apply_full`,
            which prefers ``setRawValue()`` writes to avoid double-applying
            :class:`DzERCLink` controller contributions (see the comment in
            ``dazpy/_pose.py`` around line 117-125). The ``False`` path uses
            :meth:`~dazpy.DazSkeleton.set_bone_rotations` /
            :meth:`~dazpy.DazSkeleton.set_morph_values`, which use plain
            ``setValue()`` writes. On ERC-driven channels the two modes can
            therefore leave the figure in different end states.
    """
    if include_props:
        pose = DazPose(figure=skeleton._identifier.value, bones={}, morphs={}, props={})
        pose.apply_full(skeleton)
        return

    skeleton._zero_bones_and_morphs()
