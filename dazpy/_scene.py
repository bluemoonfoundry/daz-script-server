from __future__ import annotations

from ._client import DazClient
from ._node import DazNode, NodeIdentifier
from ._script_builder import ScriptBuilder


class DazScene:
    """High-level proxy for the active DAZ Studio scene (``Scene`` global).

    This is the primary entry point for inspecting and manipulating the scene.
    All methods execute DazScript on the server and return Python objects.

    Args:
        client: Optional :class:`~dazpy.DazClient` to use.  A default client
            connecting to ``127.0.0.1:18811`` is created when omitted.

    Example::

        from dazpy import DazScene

        scene = DazScene()
        print(scene.num_nodes(), "nodes in scene")
        figure = scene.find_skeleton_by_label("Genesis 9")
    """

    def __init__(self, client: DazClient | None = None):
        self._client = client or DazClient()

    def nodes(self) -> list[DazNode]:
        """Return all top-level and child nodes in the scene.

        The returned list contains typed subclass instances: :class:`~dazpy.DazSkeleton`
        for figures, :class:`~dazpy.DazCamera`, :class:`~dazpy.DazLight`, and
        :class:`~dazpy.DazNode` for everything else.

        Returns:
            Ordered list of scene nodes (same order as DAZ Studio's scene panel).
        """
        # Use QObject::inherits() for robust subclass detection (e.g. DzFigure extends DzSkeleton).
        script = ScriptBuilder.iife("""
            var result = [];
            for (var i = 0; i < Scene.getNumNodes(); i++) {
                var n = Scene.getNode(i);
                var nodeType = "DzNode";
                if (n.inherits("DzSkeleton")) { nodeType = "DzSkeleton"; }
                else if (n.inherits("DzCamera")) { nodeType = "DzCamera"; }
                else if (n.inherits("DzLight")) { nodeType = "DzLight"; }
                result.push({name: n.getName(), className: nodeType});
            }
            return result;
        """)
        items = self._client.execute(script).value or []
        from ._skeleton import DazSkeleton
        from ._camera import DazCamera
        from ._light import DazLight
        _NODE_CLASS_MAP = {
            "DzSkeleton": DazSkeleton,
            "DzCamera": DazCamera,
            "DzLight": DazLight,
        }
        return [
            _NODE_CLASS_MAP.get(item["className"], DazNode)(self._client, NodeIdentifier(item["name"]))
            for item in items
        ]

    def find_node(self, name: str) -> DazNode:
        """Find a scene node by its internal name.

        Args:
            name: The ``getName()`` string of the node.

        Returns:
            A :class:`~dazpy.DazNode` proxy for the node.

        Raises:
            NodeNotFoundError: If no node with that name exists in the scene.
        """
        from .exceptions import NodeNotFoundError
        node = DazNode(self._client, NodeIdentifier(name, kind="name"))
        exists = ScriptBuilder.iife(
            f"return !!Scene.findNode({ScriptBuilder.escape_string(name)});"
        )
        if not self._client.execute(exists).value:
            raise NodeNotFoundError(f"Node not found: {name!r}")
        return node

    def find_node_by_label(self, label: str) -> DazNode:
        """Find a scene node by its user-visible label.

        The returned proxy is anchored to the node's internal *name* so it
        remains stable if the label is later changed.

        Args:
            label: The ``getLabel()`` string shown in the Scene panel.

        Returns:
            A :class:`~dazpy.DazNode` proxy.

        Raises:
            NodeNotFoundError: If no node with that label exists.
        """
        from .exceptions import NodeNotFoundError
        exists = ScriptBuilder.iife(
            f"return !!Scene.findNodeByLabel({ScriptBuilder.escape_string(label)});"
        )
        if not self._client.execute(exists).value:
            raise NodeNotFoundError(f"Node with label not found: {label!r}")
        # Keep kind="label" — nodes with the same asset type share the same internal
        # name, so resolving to getName() would collapse distinct nodes into one.
        return DazNode(self._client, NodeIdentifier(label, kind="label"))

    def num_nodes(self) -> int:
        """Return the total number of nodes in the scene."""
        script = ScriptBuilder.iife("return Scene.getNumNodes();")
        return self._client.execute(script).value or 0

    def cameras(self) -> list["DazCamera"]:  # noqa: F821
        """Return all camera nodes in the scene."""
        from ._camera import DazCamera
        script = ScriptBuilder.iife("""
            var names = [];
            for (var i = 0; i < Scene.getNumCameras(); i++) {
                names.push(Scene.getCamera(i).getName());
            }
            return names;
        """)
        names = self._client.execute(script).value or []
        return [DazCamera(self._client, NodeIdentifier(n)) for n in names]

    def lights(self) -> list["DazLight"]:  # noqa: F821
        """Return all light nodes in the scene."""
        from ._light import DazLight
        script = ScriptBuilder.iife("""
            var names = [];
            for (var i = 0; i < Scene.getNumLights(); i++) {
                names.push(Scene.getLight(i).getName());
            }
            return names;
        """)
        names = self._client.execute(script).value or []
        return [DazLight(self._client, NodeIdentifier(n)) for n in names]

    def skeletons(self) -> list["DazSkeleton"]:  # noqa: F821
        """Return all skeleton (figure) nodes in the scene."""
        from ._skeleton import DazSkeleton
        script = ScriptBuilder.iife("""
            var names = [];
            var skels = Scene.getSkeletonList();
            for (var i = 0; i < skels.length; i++) {
                names.push(skels[i].getName());
            }
            return names;
        """)
        names = self._client.execute(script).value or []
        return [DazSkeleton(self._client, NodeIdentifier(n)) for n in names]

    def find_skeleton(self, name: str) -> "DazSkeleton":  # noqa: F821
        """Find a skeleton by its internal name.

        Args:
            name: Internal name of the skeleton node (e.g. ``"Genesis9"``).
                  To look up by the user-visible label shown in the Scene panel
                  (e.g. ``"Genesis 9"``), use :meth:`find_skeleton_by_label`.

        Returns:
            A :class:`~dazpy.DazSkeleton` proxy.

        Raises:
            NodeNotFoundError: If no skeleton with that name exists.
        """
        from ._skeleton import DazSkeleton
        from .exceptions import NodeNotFoundError
        lookup = ScriptBuilder.iife(f"""
            var skels = Scene.getSkeletonList();
            for (var i = 0; i < skels.length; i++) {{
                if (skels[i].getName() === {ScriptBuilder.escape_string(name)}) return true;
            }}
            return false;
        """)
        if not self._client.execute(lookup).value:
            hint = ScriptBuilder.iife("""
                var info = [];
                var skels = Scene.getSkeletonList();
                for (var i = 0; i < skels.length; i++) {
                    info.push(skels[i].getName() + "|" + skels[i].getLabel());
                }
                return info;
            """)
            pairs = self._client.execute(hint).value or []
            if pairs:
                available = ", ".join(
                    f"{n!r} (label: {l!r})" for entry in pairs
                    for n, _, l in [entry.partition("|")]
                )
                raise NodeNotFoundError(
                    f"Skeleton not found: {name!r}. "
                    f"Available skeletons: {available}. "
                    f"Tip: use find_skeleton_by_label() to search by the Scene-panel label."
                )
            raise NodeNotFoundError(f"Skeleton not found: {name!r} (no skeletons in scene).")
        return DazSkeleton(self._client, NodeIdentifier(name))

    def find_skeleton_by_label(self, label: str) -> "DazSkeleton":  # noqa: F821
        """Find a skeleton by its user-visible label.

        Args:
            label: Label shown in the Scene panel.

        Returns:
            A :class:`~dazpy.DazSkeleton` proxy.

        Raises:
            NodeNotFoundError: If no skeleton with that label exists.
        """
        from ._skeleton import DazSkeleton
        from .exceptions import NodeNotFoundError
        exists_script = ScriptBuilder.iife(
            f"return !!Scene.findSkeletonByLabel({ScriptBuilder.escape_string(label)});"
        )
        if not self._client.execute(exists_script).value:
            raise NodeNotFoundError(f"Skeleton with label not found: {label!r}")
        # Keep kind="label" so _skeleton_body matches on getLabel(), not getName().
        # Multiple figures of the same type share the same internal name (e.g. both
        # Genesis 9 figures have getName() == "Genesis 9"), so name-based lookup
        # would silently resolve both to the first figure in the scene.
        return DazSkeleton(self._client, NodeIdentifier(label, kind="label"))

    def num_skeletons(self) -> int:
        """Return the total number of skeleton nodes in the scene."""
        script = ScriptBuilder.iife("return Scene.getNumSkeletons();")
        return self._client.execute(script).value or 0

    def all_node_transforms(self) -> list[dict]:
        """Return world-space transforms for every node in a single call.

        Returns:
            A list of dicts, each with keys ``"name"``, ``"label"``,
            ``"position"`` (``[x, y, z]``), ``"rotation"`` (``[x, y, z]``),
            and ``"visible"``.
        """
        script = ScriptBuilder.iife("""
            var result = [];
            for (var i = 0; i < Scene.getNumNodes(); i++) {
                var n = Scene.getNode(i);
                var pos = n.getWSPos();
                var rot = n.getWSRot();
                result.push({
                    name: n.getName(),
                    label: n.getLabel(),
                    position: [pos.x, pos.y, pos.z],
                    rotation: [rot.x, rot.y, rot.z],
                    visible: n.isVisible()
                });
            }
            return result;
        """)
        return self._client.execute(script).value or []

    def node_tree(self) -> list[dict]:
        """Return the full scene hierarchy as a nested list of dicts.

        Returns:
            Root-level nodes, each a dict with ``"name"``, ``"label"``, and
            ``"children"`` (recursively nested).
        """
        script = ScriptBuilder.iife("""
            function nodeToDict(n) {
                var children = [];
                for (var i = 0; i < n.getNumNodeChildren(); i++) {
                    children.push(nodeToDict(n.getNodeChild(i)));
                }
                return {name: n.getName(), label: n.getLabel(), children: children};
            }
            var roots = [];
            for (var i = 0; i < Scene.getNumNodes(); i++) {
                var n = Scene.getNode(i);
                if (!n.getNodeParent()) roots.push(nodeToDict(n));
            }
            return roots;
        """)
        return self._client.execute(script).value or []

    def selected_nodes(self) -> list[DazNode]:
        """Return the currently selected nodes."""
        script = ScriptBuilder.iife("""
            var nodes = Scene.getSelectedNodeList();
            var names = [];
            for (var i = 0; i < nodes.length; i++) {
                names.push(nodes[i].getName());
            }
            return names;
        """)
        names = self._client.execute(script).value or []
        return [DazNode(self._client, NodeIdentifier(n)) for n in names]

    def primary_selection(self) -> DazNode | None:
        """Return the primary selected node, or ``None`` if nothing is selected."""
        script = ScriptBuilder.iife(
            "var n = Scene.getPrimarySelection(); return n ? n.getName() : null;"
        )
        name = self._client.execute(script).value
        if name is None:
            return None
        return DazNode(self._client, NodeIdentifier(name))

    def set_primary_selection(self, node: DazNode) -> None:
        """Set the primary selection to *node*.

        Args:
            node: The node to select.
        """
        find_expr = ScriptBuilder.find_node_expr(node._identifier)
        script = ScriptBuilder.iife(f"Scene.setPrimarySelection({find_expr});")
        self._client.execute(script)

    def select_all(self, on: bool = True) -> None:
        """Select or deselect all nodes.

        Args:
            on: ``True`` to select all, ``False`` to deselect all.
        """
        flag = "true" if on else "false"
        script = ScriptBuilder.iife(f"Scene.selectAllNodes({flag});")
        self._client.execute(script)

    def undo(self, label: str) -> "UndoGroup":  # noqa: F821
        """Return a context manager that groups all enclosed changes into a single undo step.

        Args:
            label: The label shown in DAZ Studio's Edit > Undo menu.

        Returns:
            A :class:`~dazpy.UndoGroup` context manager.

        Example::

            with scene.undo("Move figure"):
                node.set_position(100, 0, 0)
        """
        from ._undo import UndoGroup
        return UndoGroup(self._client, label)

    def frame(self) -> int:
        """Return the current timeline frame number."""
        script = ScriptBuilder.iife("return Scene.getFrame();")
        return self._client.execute(script).value or 0

    def set_frame(self, frame: int) -> None:
        """Jump to a specific timeline frame.

        Args:
            frame: Zero-based frame number.
        """
        script = ScriptBuilder.iife(f"Scene.setFrame({int(frame)});")
        self._client.execute(script)

    # ── Scene I/O ──────────────────────────────────────────────────────────────

    def load(self, path: str) -> None:
        """Load a scene file (merge mode — does not clear the existing scene).

        Args:
            path: Absolute path to the ``.daz`` or ``.duf`` file on the server
                host.
        """
        script = ScriptBuilder.iife(
            f"Scene.loadScene({ScriptBuilder.escape_string(path)}, 0);"
        )
        self._client.execute(script)

    def save(self, path: str) -> None:
        """Save the scene to a file.

        Args:
            path: Absolute destination path on the server host.
        """
        script = ScriptBuilder.iife(
            f"Scene.saveScene({ScriptBuilder.escape_string(path)});"
        )
        self._client.execute(script)

    def filename(self) -> str:
        """Return the file path of the currently loaded scene, or an empty string."""
        script = ScriptBuilder.iife("return Scene.getFilename();")
        return self._client.execute(script).value or ""

    def needs_save(self) -> bool:
        """Return ``True`` if the scene has unsaved changes."""
        script = ScriptBuilder.iife("return Scene.needsSave();")
        return bool(self._client.execute(script).value)

    # ── Playback range ─────────────────────────────────────────────────────────

    def play_range(self) -> dict:
        """Return the playback range as ``{"start": int, "end": int}`` (frames)."""
        script = ScriptBuilder.iife(
            "var r = Scene.getPlayRange();"
            "var step = Scene.getTimeStep();"
            "return {start: Math.round(r.start / step), end: Math.round(r.end / step)};"
        )
        return self._client.execute(script).value or {"start": 0, "end": 0}

    def set_play_range(self, start: int, end: int) -> None:
        """Set the playback range in frames.

        Args:
            start: First frame of the play range.
            end: Last frame of the play range.
        """
        script = ScriptBuilder.iife(
            f"var step = Scene.getTimeStep();"
            f"Scene.setPlayRange(new DzTimeRange({int(start)} * step, {int(end)} * step));"
        )
        self._client.execute(script)

    def anim_range(self) -> dict:
        """Return the animation range as ``{"start": int, "end": int}`` (frames)."""
        script = ScriptBuilder.iife(
            "var r = Scene.getAnimRange();"
            "var step = Scene.getTimeStep();"
            "return {start: Math.round(r.start / step), end: Math.round(r.end / step)};"
        )
        return self._client.execute(script).value or {"start": 0, "end": 0}

    def set_anim_range(self, start: int, end: int) -> None:
        """Set the animation range in frames.

        Args:
            start: First frame.
            end: Last frame.
        """
        script = ScriptBuilder.iife(
            f"var step = Scene.getTimeStep();"
            f"Scene.setAnimRange(new DzTimeRange({int(start)} * step, {int(end)} * step));"
        )
        self._client.execute(script)

    # ── Playback state ─────────────────────────────────────────────────────────

    def is_playing(self) -> bool:
        """Return ``True`` if the scene is currently playing back."""
        script = ScriptBuilder.iife("return Scene.isPlaying();")
        return bool(self._client.execute(script).value)

    def loop_playback(self, on: bool) -> None:
        """Enable or disable looping playback.

        Args:
            on: ``True`` to enable looping, ``False`` to disable.
        """
        flag = "true" if on else "false"
        script = ScriptBuilder.iife(f"Scene.loopPlayback({flag});")
        self._client.execute(script)
