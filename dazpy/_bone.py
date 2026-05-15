from __future__ import annotations

from ._node import DazNode, NodeIdentifier
from ._script_builder import ScriptBuilder


class DazBone(DazNode):
    """Proxy for a ``DzBone`` (a single joint within a :class:`~dazpy.DazSkeleton`).

    Extends :class:`~dazpy.DazNode` with bone-specific rotation helpers.
    """

    @property
    def local_rotation(self) -> dict | None:
        """Local-space rotation as ``{"x", "y", "z", "w"}`` quaternion (read-only)."""
        script = ScriptBuilder.node_body(
            self._identifier,
            "var r = _node.getLocalRot(); return {x: r.x, y: r.y, z: r.z, w: r.w};"
        )
        return self._client.execute(script).value

    def set_local_rotation(self, x: float, y: float, z: float) -> None:
        """Set the bone's local rotation using Euler angles in degrees.

        Args:
            x: Rotation around the local X axis.
            y: Rotation around the local Y axis.
            z: Rotation around the local Z axis.
        """
        script = ScriptBuilder.node_body(
            self._identifier,
            f"_node.getXRotControl().setValue({float(x)}); "
            f"_node.getYRotControl().setValue({float(y)}); "
            f"_node.getZRotControl().setValue({float(z)});"
        )
        self._client.execute(script)

    @property
    def local_position(self) -> dict | None:
        """Local-space position as ``{"x", "y", "z"}`` (read-only)."""
        script = ScriptBuilder.node_body(
            self._identifier,
            "var p = _node.getLocalPos(); return {x: p.x, y: p.y, z: p.z};"
        )
        return self._client.execute(script).value

    @property
    def rotation_order(self) -> str | None:
        """Rotation order string (e.g. ``"XYZ"``), or ``None``."""
        script = ScriptBuilder.node_body(
            self._identifier,
            "return _node.getRotationOrder();"
        )
        return self._client.execute(script).value

    def get_skeleton(self) -> "DazSkeleton | None":  # noqa: F821
        """Return the parent :class:`~dazpy.DazSkeleton`, or ``None``."""
        from ._skeleton import DazSkeleton
        script = ScriptBuilder.node_body(
            self._identifier,
            "var s = _node.getSkeleton(); return s ? s.getName() : null;"
        )
        name = self._client.execute(script).value
        if name is None:
            return None
        return DazSkeleton(self._client, NodeIdentifier(name))
