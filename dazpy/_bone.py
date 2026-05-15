from __future__ import annotations

from ._element import DazElement
from ._node import DazNode, NodeIdentifier
from ._script_builder import ScriptBuilder


class DazBone(DazNode):
    """Proxy for a ``DzBone`` (a single joint within a :class:`~dazpy.DazSkeleton`).

    Extends :class:`~dazpy.DazNode` with bone-specific rotation helpers.
    """

    @classmethod
    def _from_locator(cls, client: "DazClient", locator: str, name: str) -> "DazBone":  # noqa: F821
        """Construct a DazBone from a pre-built skeleton-relative locator."""
        bone = object.__new__(cls)
        DazElement.__init__(bone, client, locator)
        object.__setattr__(bone, "_identifier", NodeIdentifier(name))
        return bone

    def _nb(self, body: str) -> str:
        return ScriptBuilder.node_body_from_locator(self._locator, body)

    @property
    def local_euler(self) -> tuple[float, float, float] | None:
        """Local-space rotation as an ``(x, y, z)`` tuple of Euler angles in degrees.

        Reads the same rotation controls written by :meth:`set_local_rotation`,
        so the two are exact inverses.

        Returns:
            ``(x, y, z)`` in degrees, or ``None`` if the bone cannot be found.
        """
        result = self._client.execute(self._nb(
            "return [_node.getXRotControl().getValue(), "
            "_node.getYRotControl().getValue(), "
            "_node.getZRotControl().getValue()];"
        )).value
        if result is None:
            return None
        return (result[0], result[1], result[2])

    @property
    def local_rotation(self) -> dict | None:
        """Local-space rotation as ``{"x", "y", "z", "w"}`` quaternion (read-only)."""
        return self._client.execute(self._nb(
            "var r = _node.getLocalRot(); return {x: r.x, y: r.y, z: r.z, w: r.w};"
        )).value

    def set_local_rotation(self, x: float, y: float, z: float) -> None:
        """Set the bone's local rotation using Euler angles in degrees.

        Args:
            x: Rotation around the local X axis.
            y: Rotation around the local Y axis.
            z: Rotation around the local Z axis.
        """
        self._client.execute(self._nb(
            f"_node.getXRotControl().setValue({float(x)}); "
            f"_node.getYRotControl().setValue({float(y)}); "
            f"_node.getZRotControl().setValue({float(z)});"
        ))

    @property
    def local_position(self) -> dict | None:
        """Local-space position as ``{"x", "y", "z"}`` (read-only)."""
        return self._client.execute(self._nb(
            "var p = _node.getLocalPos(); return {x: p.x, y: p.y, z: p.z};"
        )).value

    @property
    def rotation_order(self) -> str | None:
        """Rotation order string (e.g. ``"XYZ"``), or ``None``."""
        return self._client.execute(self._nb(
            "return _node.getRotationOrder();"
        )).value

    def get_skeleton(self) -> "DazSkeleton | None":  # noqa: F821
        """Return the parent :class:`~dazpy.DazSkeleton`, or ``None``."""
        from ._skeleton import DazSkeleton
        name = self._client.execute(self._nb(
            "var s = _node.getSkeleton(); return s ? s.getName() : null;"
        )).value
        if name is None:
            return None
        return DazSkeleton(self._client, NodeIdentifier(name))
