from __future__ import annotations

from ._node import DazNode, NodeIdentifier
from ._script_builder import ScriptBuilder


class DazSkeleton(DazNode):
    """Proxy for a ``DzSkeleton`` (a rigged figure such as Genesis 9).

    Extends :class:`~dazpy.DazNode` with bone-access helpers.
    """

    def bones(self) -> list["DazBone"]:  # noqa: F821
        """Return all bones in this skeleton."""
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
        """Find a bone by its internal name.

        Args:
            name: The ``getName()`` string of the bone (e.g. ``"rForeArm"``).

        Returns:
            A :class:`~dazpy.DazBone` proxy.

        Raises:
            NodeNotFoundError: If no bone with that name exists.
        """
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
        """Find a bone by its user-visible label.

        Args:
            label: The ``getLabel()`` string of the bone.

        Returns:
            A :class:`~dazpy.DazBone` proxy.

        Raises:
            NodeNotFoundError: If no bone with that label exists.
        """
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
        """Return the total number of bones in this skeleton."""
        script = ScriptBuilder.node_body(
            self._identifier,
            "return _node.getAllBones().length;"
        )
        return self._client.execute(script).value or 0

    def follow_target(self) -> "DazSkeleton | None":
        """Return the IK follow-target skeleton, or ``None`` if not set."""
        script = ScriptBuilder.node_body(
            self._identifier,
            "var t = _node.getFollowTarget(); return t ? t.getName() : null;"
        )
        name = self._client.execute(script).value
        if name is None:
            return None
        return DazSkeleton(self._client, NodeIdentifier(name))
