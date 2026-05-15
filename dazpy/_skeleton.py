from __future__ import annotations

from ._node import DazNode, NodeIdentifier
from ._script_builder import ScriptBuilder


class DazSkeleton(DazNode):
    def bones(self) -> list["DazBone"]:  # noqa: F821
        from ._bone import DazBone
        script = ScriptBuilder.node_body(
            self._identifier,
            """
            var bones = _node.getAllBones();
            var names = [];
            for (var i = 0; i < bones.length; i++) {
                names.push(bones[i].getName());
            }
            return names;
            """
        )
        names = self._client.execute(script).value or []
        return [DazBone(self._client, NodeIdentifier(n)) for n in names]

    def find_bone(self, name: str) -> "DazBone":  # noqa: F821
        from ._bone import DazBone
        from .exceptions import NodeNotFoundError
        script = ScriptBuilder.node_body(
            self._identifier,
            f"var b = _node.findBone({ScriptBuilder.escape_string(name)}); return b ? b.getName() : null;"
        )
        result = self._client.execute(script).value
        if result is None:
            raise NodeNotFoundError(f"Bone not found: {name!r}")
        return DazBone(self._client, NodeIdentifier(result))

    def find_bone_by_label(self, label: str) -> "DazBone":  # noqa: F821
        from ._bone import DazBone
        from .exceptions import NodeNotFoundError
        script = ScriptBuilder.node_body(
            self._identifier,
            f"var b = _node.findBoneByLabel({ScriptBuilder.escape_string(label)}); return b ? b.getName() : null;"
        )
        result = self._client.execute(script).value
        if result is None:
            raise NodeNotFoundError(f"Bone with label not found: {label!r}")
        return DazBone(self._client, NodeIdentifier(result))

    def num_bones(self) -> int:
        script = ScriptBuilder.node_body(
            self._identifier,
            "return _node.getAllBones().length;"
        )
        return self._client.execute(script).value or 0

    def follow_target(self) -> "DazSkeleton | None":
        script = ScriptBuilder.node_body(
            self._identifier,
            "var t = _node.getFollowTarget(); return t ? t.getName() : null;"
        )
        name = self._client.execute(script).value
        if name is None:
            return None
        return DazSkeleton(self._client, NodeIdentifier(name))
