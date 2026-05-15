from __future__ import annotations

from ._node import DazNode, NodeIdentifier
from ._script_builder import ScriptBuilder


class DazBone(DazNode):
    @property
    def local_rotation(self) -> dict | None:
        script = ScriptBuilder.node_body(
            self._identifier,
            "var r = _node.getLocalRot(); return {x: r.x, y: r.y, z: r.z, w: r.w};"
        )
        return self._client.execute(script).value

    def set_local_rotation(self, x: float, y: float, z: float) -> None:
        script = ScriptBuilder.node_body(
            self._identifier,
            f"_node.getXRotControl().setValue({float(x)}); "
            f"_node.getYRotControl().setValue({float(y)}); "
            f"_node.getZRotControl().setValue({float(z)});"
        )
        self._client.execute(script)

    @property
    def local_position(self) -> dict | None:
        script = ScriptBuilder.node_body(
            self._identifier,
            "var p = _node.getLocalPos(); return {x: p.x, y: p.y, z: p.z};"
        )
        return self._client.execute(script).value

    @property
    def rotation_order(self) -> str | None:
        script = ScriptBuilder.node_body(
            self._identifier,
            "return _node.getRotationOrder();"
        )
        return self._client.execute(script).value

    def get_skeleton(self) -> "DazSkeleton | None":  # noqa: F821
        from ._skeleton import DazSkeleton
        script = ScriptBuilder.node_body(
            self._identifier,
            "var s = _node.getSkeleton(); return s ? s.getName() : null;"
        )
        name = self._client.execute(script).value
        if name is None:
            return None
        return DazSkeleton(self._client, NodeIdentifier(name))
