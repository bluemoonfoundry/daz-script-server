from __future__ import annotations

import json

from ._node import DazNode, NodeIdentifier
from ._script_builder import ScriptBuilder


class DazSkeleton(DazNode):
    """Proxy for a ``DzSkeleton`` (a rigged figure such as Genesis 9).

    Extends :class:`~dazpy.DazNode` with bone-access helpers.
    """

    def _skeleton_body(self, body: str) -> str:
        # Scene.findNode() returns DzNode which lacks DzSkeleton methods like
        # findBone(). Retrieve a properly typed DzSkeleton by iterating
        # getSkeletonList(), which is the only proven-typed accessor in the API.
        kind = self._identifier.kind
        value = json.dumps(self._identifier.value)
        if kind == "label":
            match = f"_skels[_i].getLabel() === {value}"
        else:
            match = f"_skels[_i].getName() === {value}"
        lookup = (
            f"var _node = null;"
            f" var _skels = Scene.getSkeletonList();"
            f" for (var _i = 0; _i < _skels.length; _i++) {{"
            f" if ({match}) {{ _node = _skels[_i]; break; }} }}"
        )
        return ScriptBuilder.iife(f"{lookup}\nif (!_node) return null;\n{body}")

    def _bone_locator(self, bone_name: str) -> str:
        """Build a JS locator that resolves a bone through this specific skeleton.

        Uses the skeleton list rather than Scene.findNode() so that two figures
        with the same internal name (e.g. two Genesis 9 figures) are kept distinct.
        """
        kind = self._identifier.kind
        value = json.dumps(self._identifier.value)
        match = (
            f"_skels[_i].getLabel() === {value}"
            if kind == "label"
            else f"_skels[_i].getName() === {value}"
        )
        return (
            f"(function(){{"
            f"var _skel=null,_skels=Scene.getSkeletonList();"
            f"for(var _i=0;_i<_skels.length;_i++){{if({match}){{_skel=_skels[_i];break;}}}}"
            f"return _skel?_skel.findBone({json.dumps(bone_name)}):null;"
            f"}})()"
        )

    def bones(self) -> list["DazBone"]:  # noqa: F821
        """Return all bones in this skeleton."""
        from ._bone import DazBone
        script = self._skeleton_body(
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
        return [DazBone._from_locator(self._client, self._bone_locator(n), n) for n in names]

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
        script = self._skeleton_body(
            f"var b = _node.findBone({ScriptBuilder.escape_string(name)}); return b ? b.getName() : null;"
        )
        result = self._client.execute(script).value
        if result is None:
            raise NodeNotFoundError(f"Bone not found: {name!r}")
        return DazBone._from_locator(self._client, self._bone_locator(result), result)

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
        script = self._skeleton_body(
            f"var b = _node.findBoneByLabel({ScriptBuilder.escape_string(label)}); return b ? b.getName() : null;"
        )
        result = self._client.execute(script).value
        if result is None:
            raise NodeNotFoundError(f"Bone with label not found: {label!r}")
        return DazBone._from_locator(self._client, self._bone_locator(result), result)

    def num_bones(self) -> int:
        """Return the total number of bones in this skeleton."""
        script = self._skeleton_body("return _node.getAllBones().length;")
        return self._client.execute(script).value or 0

    def follow_target(self) -> "DazSkeleton | None":
        """Return the IK follow-target skeleton, or ``None`` if not set."""
        script = self._skeleton_body(
            "var t = _node.getFollowTarget(); return t ? t.getName() : null;"
        )
        name = self._client.execute(script).value
        if name is None:
            return None
        return DazSkeleton(self._client, NodeIdentifier(name))
