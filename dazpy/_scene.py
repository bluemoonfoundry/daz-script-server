from __future__ import annotations

from ._client import DazClient
from ._node import DazNode, NodeIdentifier
from ._script_builder import ScriptBuilder


class DazScene:
    def __init__(self, client: DazClient | None = None):
        self._client = client or DazClient()

    def nodes(self) -> list[DazNode]:
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
        from .exceptions import NodeNotFoundError
        node = DazNode(self._client, NodeIdentifier(name, kind="name"))
        exists = ScriptBuilder.iife(
            f"return !!Scene.findNode({ScriptBuilder.escape_string(name)});"
        )
        if not self._client.execute(exists).value:
            raise NodeNotFoundError(f"Node not found: {name!r}")
        return node

    def find_node_by_label(self, label: str) -> DazNode:
        from .exceptions import NodeNotFoundError
        exists = ScriptBuilder.iife(
            f"return !!Scene.findNodeByLabel({ScriptBuilder.escape_string(label)});"
        )
        if not self._client.execute(exists).value:
            raise NodeNotFoundError(f"Node with label not found: {label!r}")
        # Resolve to internal name for stable identity
        name_script = ScriptBuilder.iife(
            f"var n = Scene.findNodeByLabel({ScriptBuilder.escape_string(label)});"
            "return n ? n.getName() : null;"
        )
        name = self._client.execute(name_script).value
        return DazNode(self._client, NodeIdentifier(name or label))

    def num_nodes(self) -> int:
        script = ScriptBuilder.iife("return Scene.getNumNodes();")
        return self._client.execute(script).value or 0

    def cameras(self) -> list["DazCamera"]:  # noqa: F821
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
        from ._skeleton import DazSkeleton
        from .exceptions import NodeNotFoundError
        exists = ScriptBuilder.iife(
            f"return !!Scene.findSkeleton({ScriptBuilder.escape_string(name)});"
        )
        if not self._client.execute(exists).value:
            raise NodeNotFoundError(f"Skeleton not found: {name!r}")
        return DazSkeleton(self._client, NodeIdentifier(name))

    def find_skeleton_by_label(self, label: str) -> "DazSkeleton":  # noqa: F821
        from ._skeleton import DazSkeleton
        from .exceptions import NodeNotFoundError
        name_script = ScriptBuilder.iife(
            f"var s = Scene.findSkeletonByLabel({ScriptBuilder.escape_string(label)}); return s ? s.getName() : null;"
        )
        name = self._client.execute(name_script).value
        if name is None:
            raise NodeNotFoundError(f"Skeleton with label not found: {label!r}")
        return DazSkeleton(self._client, NodeIdentifier(name))

    def num_skeletons(self) -> int:
        script = ScriptBuilder.iife("return Scene.getNumSkeletons();")
        return self._client.execute(script).value or 0

    def all_node_transforms(self) -> list[dict]:
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
        script = ScriptBuilder.iife(
            "var n = Scene.getPrimarySelection(); return n ? n.getName() : null;"
        )
        name = self._client.execute(script).value
        if name is None:
            return None
        return DazNode(self._client, NodeIdentifier(name))

    def set_primary_selection(self, node: DazNode) -> None:
        find_expr = ScriptBuilder.find_node_expr(node._identifier)
        script = ScriptBuilder.iife(f"Scene.setPrimarySelection({find_expr});")
        self._client.execute(script)

    def select_all(self, on: bool = True) -> None:
        flag = "true" if on else "false"
        script = ScriptBuilder.iife(f"Scene.selectAllNodes({flag});")
        self._client.execute(script)

    def undo(self, label: str) -> "UndoGroup":  # noqa: F821
        from ._undo import UndoGroup
        return UndoGroup(self._client, label)

    def frame(self) -> int:
        script = ScriptBuilder.iife("return Scene.getFrame();")
        return self._client.execute(script).value or 0

    def set_frame(self, frame: int) -> None:
        script = ScriptBuilder.iife(f"Scene.setFrame({int(frame)});")
        self._client.execute(script)

    # ── Scene I/O ──────────────────────────────────────────────────────────────

    def load(self, path: str) -> None:
        script = ScriptBuilder.iife(
            f"Scene.loadScene({ScriptBuilder.escape_string(path)}, 0);"
        )
        self._client.execute(script)

    def save(self, path: str) -> None:
        script = ScriptBuilder.iife(
            f"Scene.saveScene({ScriptBuilder.escape_string(path)});"
        )
        self._client.execute(script)

    def filename(self) -> str:
        script = ScriptBuilder.iife("return Scene.getFilename();")
        return self._client.execute(script).value or ""

    def needs_save(self) -> bool:
        script = ScriptBuilder.iife("return Scene.needsSave();")
        return bool(self._client.execute(script).value)

    # ── Playback range ─────────────────────────────────────────────────────────

    def play_range(self) -> dict:
        script = ScriptBuilder.iife(
            "var r = Scene.getPlayRange();"
            "var step = Scene.getTimeStep();"
            "return {start: Math.round(r.start / step), end: Math.round(r.end / step)};"
        )
        return self._client.execute(script).value or {"start": 0, "end": 0}

    def set_play_range(self, start: int, end: int) -> None:
        script = ScriptBuilder.iife(
            f"var step = Scene.getTimeStep();"
            f"Scene.setPlayRange(new DzTimeRange({int(start)} * step, {int(end)} * step));"
        )
        self._client.execute(script)

    def set_anim_range(self, start: int, end: int) -> None:
        script = ScriptBuilder.iife(
            f"var step = Scene.getTimeStep();"
            f"Scene.setAnimRange(new DzTimeRange({int(start)} * step, {int(end)} * step));"
        )
        self._client.execute(script)

    # ── Playback state ─────────────────────────────────────────────────────────

    def is_playing(self) -> bool:
        script = ScriptBuilder.iife("return Scene.isPlaying();")
        return bool(self._client.execute(script).value)

    def loop_playback(self, on: bool) -> None:
        flag = "true" if on else "false"
        script = ScriptBuilder.iife(f"Scene.loopPlayback({flag});")
        self._client.execute(script)
