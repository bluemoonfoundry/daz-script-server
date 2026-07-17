from __future__ import annotations

import json

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

    def find_camera_by_label(self, label: str) -> "DazCamera":  # noqa: F821
        """Find a camera by its user-visible label.

        Args:
            label: The label shown in the Scene panel (e.g. ``"Camera 1"``).
                This is the same value accepted by the ``camera`` parameter of
                :func:`~dazpy._render_api.render`.

        Returns:
            A :class:`~dazpy.DazCamera` proxy.

        Raises:
            NodeNotFoundError: If no camera with that label exists.
        """
        from ._camera import DazCamera
        from .exceptions import NodeNotFoundError
        exists = ScriptBuilder.iife(
            f"return !!Scene.findCameraByLabel({ScriptBuilder.escape_string(label)});"
        )
        if not self._client.execute(exists).value:
            raise NodeNotFoundError(f"Camera with label not found: {label!r}")
        return DazCamera(self._client, NodeIdentifier(label, kind="label"))

    _LIGHT_TYPE_CLASSES = {
        "spot": "DzSpotLight",
        "point": "DzPointLight",
        "distant": "DzDistantLight",
    }

    def create_camera(self, name: str | None = None) -> "DazCamera":  # noqa: F821
        """Create a new basic camera node and add it to the scene.

        Args:
            name: Optional internal name for the new camera. When omitted,
                DAZ Studio assigns its default name (e.g. ``"Camera"``,
                de-duplicated as ``"Camera 2"`` etc.).

        Returns:
            A :class:`~dazpy.DazCamera` proxy for the newly created camera.
        """
        from ._camera import DazCamera
        name_expr = ScriptBuilder.escape_string(name) if name is not None else "null"
        script = ScriptBuilder.iife(f"""
            var cam = new DzBasicCamera();
            if ({name_expr} !== null) cam.setName({name_expr});
            Scene.addNode(cam);
            return cam.getName();
        """)
        created_name = self._client.execute(script).value
        return DazCamera(self._client, NodeIdentifier(created_name))

    def create_light(self, light_type: str, name: str | None = None) -> "DazLight":  # noqa: F821
        """Create a new light node and add it to the scene.

        Args:
            light_type: One of ``"spot"``, ``"point"``, or ``"distant"``.
            name: Optional internal name for the new light. When omitted,
                DAZ Studio assigns its default name.

        Returns:
            A :class:`~dazpy.DazLight` proxy for the newly created light.

        Raises:
            ValueError: If *light_type* is not a recognised light type.
        """
        from ._light import DazLight
        class_name = self._LIGHT_TYPE_CLASSES.get(light_type)
        if class_name is None:
            raise ValueError(
                f"Unknown light_type {light_type!r}; expected one of "
                f"{sorted(self._LIGHT_TYPE_CLASSES)}"
            )
        name_expr = ScriptBuilder.escape_string(name) if name is not None else "null"
        script = ScriptBuilder.iife(f"""
            var light = new {class_name}();
            if ({name_expr} !== null) light.setName({name_expr});
            Scene.addNode(light);
            return light.getName();
        """)
        created_name = self._client.execute(script).value
        return DazLight(self._client, NodeIdentifier(created_name))

    def find_light_by_label(self, label: str) -> "DazLight":  # noqa: F821
        """Find a light by its user-visible label.

        Args:
            label: The label shown in the Scene panel (e.g. ``"Distant Light 1"``).

        Returns:
            A :class:`~dazpy.DazLight` proxy.

        Raises:
            NodeNotFoundError: If no light with that label exists.
        """
        from ._light import DazLight
        from .exceptions import NodeNotFoundError
        exists = ScriptBuilder.iife(
            f"return !!Scene.findLightByLabel({ScriptBuilder.escape_string(label)});"
        )
        if not self._client.execute(exists).value:
            raise NodeNotFoundError(f"Light with label not found: {label!r}")
        return DazLight(self._client, NodeIdentifier(label, kind="label"))

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

    def scene_snapshot(
        self,
        skeleton_labels: list[str] | None = None,
    ) -> list[dict]:
        """Return full skeleton and bone metadata for the scene in one HTTP call.

        Each entry in the returned list represents one skeleton and contains:
        ``name``, ``label``, and ``bones`` — a list of dicts with ``name``,
        ``label``, ``parent_name``, ``rotation_order``, ``local_position``,
        ``world_position``, and ``local_euler``.

        Pass to :func:`~dazpy.build_rig_profiles_from_snapshot` to build
        solver-ready :class:`~dazpy.FigureRigProfile` objects without any
        additional HTTP calls.

        Args:
            skeleton_labels: Optional list of skeleton names or labels to
                include.  ``None`` returns every skeleton in the scene.

        Returns:
            List of skeleton snapshot dicts, one per matching skeleton.
        """
        filter_js = json.dumps(skeleton_labels) if skeleton_labels is not None else "null"
        script = ScriptBuilder.iife(f"""
            var _filter = {filter_js};
            var _skels = Scene.getSkeletonList();
            var _result = [];
            for (var _s = 0; _s < _skels.length; _s++) {{
                var _skel = _skels[_s];
                if (_filter !== null) {{
                    var _found = false;
                    for (var _f = 0; _f < _filter.length; _f++) {{
                        if (_filter[_f] === _skel.getName() || _filter[_f] === _skel.getLabel()) {{
                            _found = true; break;
                        }}
                    }}
                    if (!_found) continue;
                }}
                var _bones = _skel.getAllBones();
                var _boneList = [];
                for (var _i = 0; _i < _bones.length; _i++) {{
                    var _b = _bones[_i];
                    var _parent = _b.getNodeParent();
                    var _parentName = null;
                    if (_parent && _parent.className && _parent.className() === "DzBone") {{
                        _parentName = _parent.getName();
                    }}
                    var _lpos = _b.getLocalPos();
                    var _wpos = _b.getWSPos();
                    _boneList.push({{
                        name: _b.getName(),
                        label: _b.getLabel(),
                        parent_name: _parentName,
                        rotation_order: _b.getRotationOrder(),
                        local_position: {{x: _lpos.x, y: _lpos.y, z: _lpos.z}},
                        world_position: {{x: _wpos.x, y: _wpos.y, z: _wpos.z}},
                        local_euler: {{
                            x: _b.getXRotControl().getValue(),
                            y: _b.getYRotControl().getValue(),
                            z: _b.getZRotControl().getValue()
                        }}
                    }});
                }}
                _result.push({{
                    name: _skel.getName(),
                    label: _skel.getLabel(),
                    bones: _boneList
                }});
            }}
            return _result;
        """)
        return self._client.execute(script).value or []

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

    def node_hierarchy(self, root: str | None = None, max_depth: int | None = None) -> dict:
        """Return the descendant tree rooted at a single node, in one HTTP call.

        Unlike :meth:`node_tree` (every root-level node in the scene), this
        starts at one named node -- typically a figure -- and includes a
        ``type`` (DazScript class name) on every entry and an optional
        recursion-depth limit, which matters for deep skeletons (Genesis
        figures have 100+ bones).

        Args:
            root: Display label or internal name of the root node. Searched
                by label first, then internal name.
            max_depth: Maximum recursion depth. ``None`` or ``0`` means
                unlimited.

        Returns:
            ``{"node": label, "hierarchy": {...}, "total_descendants": int}``
            where ``hierarchy`` is ``{"label", "name", "type", "children": [...]}``
            (``children`` omitted for leaf nodes).

        Raises:
            NodeNotFoundError: If *root* cannot be found.
        """
        from .exceptions import NodeNotFoundError
        root_json = json.dumps(root)
        depth_js = str(int(max_depth)) if max_depth else "0"
        script = ScriptBuilder.iife(f"""
            var _rootLabel = {root_json};
            var _node = Scene.findNodeByLabel(_rootLabel);
            if (!_node) _node = Scene.findNode(_rootLabel);
            if (!_node) return null;

            var _maxDepth = {depth_js};
            var _totalDescendants = 0;

            function _build(n, depth) {{
                if (_maxDepth > 0 && depth >= _maxDepth) return null;
                var info = {{label: n.getLabel(), name: n.getName(), type: n.className()}};
                var children = [];
                for (var i = 0; i < n.getNumNodeChildren(); i++) {{
                    _totalDescendants++;
                    var childInfo = _build(n.getNodeChild(i), depth + 1);
                    if (childInfo) children.push(childInfo);
                }}
                if (children.length > 0) info.children = children;
                return info;
            }}

            var hierarchy = _build(_node, 0);
            return {{node: _node.getLabel(), hierarchy: hierarchy, total_descendants: _totalDescendants}};
        """)
        result = self._client.execute(script).value
        if result is None:
            raise NodeNotFoundError(f"Node not found: {root!r}")
        return result

    def overview(self) -> dict:
        """Return a lightweight, top-level snapshot of the scene in one HTTP call.

        Root-level figures, all cameras, all lights, the open scene file,
        and the primary selection -- enough to orient an agent without
        enumerating every node (use :meth:`nodes` or :meth:`node_tree` for
        that).

        Returns:
            ``{"scene_file", "selected_node", "figures", "cameras", "lights", "total_nodes"}``.
            ``figures``/``cameras``/``lights`` are lists of
            ``{"name", "label", "type"}`` (``type`` omitted for cameras).
            Follower figures (eyelashes, tear surfaces, etc. parented under
            another figure rather than the scene root) are excluded from
            ``figures``.
        """
        script = ScriptBuilder.iife("""
            var figures = [];
            for (var i = 0; i < Scene.getNumSkeletons(); i++) {
                var s = Scene.getSkeleton(i);
                var parent = s.getNodeParent();
                if (parent && parent.inherits("DzFigure")) continue;
                figures.push({name: s.getName(), label: s.getLabel(), type: s.className()});
            }
            var cameras = [];
            for (var i = 0; i < Scene.getNumCameras(); i++) {
                var c = Scene.getCamera(i);
                cameras.push({name: c.getName(), label: c.getLabel()});
            }
            var lights = [];
            for (var i = 0; i < Scene.getNumLights(); i++) {
                var l = Scene.getLight(i);
                lights.push({name: l.getName(), label: l.getLabel(), type: l.className()});
            }
            var sel = Scene.getPrimarySelection();
            return {
                scene_file: Scene.getFilename(),
                selected_node: sel ? sel.getLabel() : null,
                figures: figures,
                cameras: cameras,
                lights: lights,
                total_nodes: Scene.getNumNodes()
            };
        """)
        return self._client.execute(script).value or {
            "scene_file": "", "selected_node": None, "figures": [], "cameras": [], "lights": [], "total_nodes": 0,
        }

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

    def apply_interaction_recipe(
        self,
        recipe: "InteractionRecipe",  # noqa: F821
        *,
        rig_profiles: dict[str, "FigureRigProfile"] | None = None,  # noqa: F821
        align_limb_targets: bool = False,
        max_iterations: int | None = None,
        step_degrees: float = 1.0,
        damping: float = 0.25,
        tolerance: float = 0.15,
    ) -> "PreparedInteractionResult":  # noqa: F821
        """Prepare and apply an interaction recipe against the current scene."""

        from ._interaction import apply_interaction_recipe_to_scene

        return apply_interaction_recipe_to_scene(
            self,
            recipe,
            rig_profiles=rig_profiles,
            align_limb_targets=align_limb_targets,
            max_iterations=max_iterations,
            step_degrees=step_degrees,
            damping=damping,
            tolerance=tolerance,
        )

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

    def save_copy(self, path: str) -> dict:
        """Save a copy of the scene to *path* without changing the scene's current
        file or dirty state — equivalent to a "Save a Copy As…" operation.

        For clean scenes the plugin performs a simple file copy (zero DAZ state
        change).  For scenes with unsaved changes it serialises via
        ``Scene.saveScene()`` and immediately restores the original filename; as
        a side effect unsaved changes are also written to the original file
        (unavoidable without the ``doSave(saveOnly=true)`` API, which is
        compiled out of current DAZ Studio 4.x builds).

        Args:
            path: Absolute destination path on the server host (e.g.
                ``"C:/backups/scene_v2.duf"``).

        Returns:
            ``{"ok": True, "path": str, "source": str, "method": str}`` where
            *method* is ``"copy"`` (file copy, no serialisation) or
            ``"serialize"`` / ``"serialize+restore"`` (required when the scene
            has unsaved changes).

        Raises:
            :class:`~dazpy.exceptions.DazError`: on server-side failure (non-2xx response).
            :class:`~dazpy.exceptions.AuthenticationError`: on HTTP 401/403.
            :class:`~dazpy.exceptions.ConnectionError`: if the server is unreachable.
        """
        from .exceptions import AuthenticationError, DazError
        resp = self._client._post("/scene/save-copy", {"path": path})
        if resp.status_code in (401, 403):
            raise AuthenticationError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        if not resp.ok:
            body = resp.json() if resp.content else {}
            msg = body.get("error") or body.get("detail") or resp.text[:200]
            raise DazError(f"save_copy failed ({resp.status_code}): {msg}")
        return resp.json()

    def _export_via_native_exporter(self, exporter_class: str, path: str, overrides: dict) -> None:
        """Run one of DAZ Studio's built-in file exporters (``DzExportMgr``).

        Confirmed against a live instance: ``App.getExportMgr()`` registers
        exporters by class name (e.g. ``"DzFbxExporter"``, ``"DzObjExporter"``)
        and each exposes ``getDefaultOptions(DzFileIOSettings*)`` /
        ``writeFile(path, settings)``. Defaults are seeded from the exporter
        itself, then *overrides* are applied by Python type (bool -> setBoolValue,
        int -> setIntValue, float -> setFloatValue, else -> setStringValue).
        ``RunSilent`` must be forced to 1 or the native exporter shows a modal
        options dialog, which would hang the main thread the HTTP handler
        blocks on.
        """
        settings_calls = []
        for key, value in overrides.items():
            js_key = json.dumps(key)
            if isinstance(value, bool):
                settings_calls.append(f"settings.setBoolValue({js_key}, {'true' if value else 'false'});")
            elif isinstance(value, int):
                settings_calls.append(f"settings.setIntValue({js_key}, {value});")
            elif isinstance(value, float):
                settings_calls.append(f"settings.setFloatValue({js_key}, {value});")
            else:
                settings_calls.append(f"settings.setStringValue({js_key}, {json.dumps(str(value))});")

        script = ScriptBuilder.iife(f"""
            var mgr = App.getExportMgr();
            var exp = mgr.findExporterByClassName({json.dumps(exporter_class)});
            if (!exp) return;
            var settings = new DzFileIOSettings();
            exp.getDefaultOptions(settings);
            {' '.join(settings_calls)}
            exp.writeFile({json.dumps(path)}, settings);
        """)
        self._client.execute(script)

    def export_fbx(
        self,
        path: str,
        *,
        selected_only: bool = False,
        include_figures: bool = True,
        include_props: bool = False,
        include_lights: bool = False,
        include_cameras: bool = False,
        include_animations: bool = False,
        embed_textures: bool = True,
        options: dict | None = None,
    ) -> None:
        """Export the scene to an FBX file via DAZ Studio's built-in FBX exporter.

        This is a plain synchronous call, unlike
        :meth:`~dazpy.DazClient.export_usd_submit` -- FBX export is a native
        DAZ Studio exporter (``DzFbxExporter``) rather than a custom C++
        pipeline, so there's no async job to poll.

        Args:
            path: Absolute destination path on the DAZ Studio host (should
                end in ``.fbx``).
            selected_only: Export only the selected node(s).
            include_figures: Include figures (default ``True``).
            include_props: Include prop nodes.
            include_lights: Include scene lights.
            include_cameras: Include cameras.
            include_animations: Include the current animation take.
            embed_textures: Embed texture maps into the FBX file (default ``True``).
            options: Additional raw ``DzFileIOSettings`` overrides (e.g.
                ``{"Format": "FBX 2014 -- Binary"}``), applied on top of the
                exporter's own defaults and the named args above. See
                ``DzFbxExporter.getDefaultOptions()`` for the full set of keys.
        """
        overrides = {
            "IncludeSelectedOnly": selected_only,
            "IncludeFigures": include_figures,
            "IncludeProps": include_props,
            "IncludeLights": include_lights,
            "IncludeCameras": include_cameras,
            "IncludeAnimations": include_animations,
            "EmbedTextures": embed_textures,
        }
        overrides.update(options or {})
        overrides["RunSilent"] = 1
        self._export_via_native_exporter("DzFbxExporter", path, overrides)

    def export_obj(
        self,
        path: str,
        *,
        selected_only: bool = False,
        ignore_invisible: bool = True,
        include_normals: bool = False,
        collect_maps: bool = False,
        options: dict | None = None,
    ) -> None:
        """Export the scene to an OBJ file via DAZ Studio's built-in OBJ exporter.

        This is a plain synchronous call -- see :meth:`export_fbx` for why
        this doesn't follow the USD export module's async job pattern.

        Args:
            path: Absolute destination path on the DAZ Studio host (should
                end in ``.obj``).
            selected_only: Export only the selected node(s).
            ignore_invisible: Skip nodes hidden in the viewport (default
                ``True``, matches the exporter's own default).
            include_normals: Write vertex normals (``WriteVN``).
            collect_maps: Copy referenced texture maps next to the
                ``.obj``/``.mtl`` instead of referencing their original paths.
            options: Additional raw ``DzFileIOSettings`` overrides, applied
                on top of the exporter's own defaults and the named args
                above. See ``DzObjExporter.getDefaultOptions()`` for the
                full set of keys.
        """
        overrides = {
            "SelectedOnly": selected_only,
            "IgnoreInvisible": ignore_invisible,
            "WriteVN": include_normals,
            "CollectMaps": collect_maps,
        }
        overrides.update(options or {})
        overrides["RunSilent"] = 1
        self._export_via_native_exporter("DzObjExporter", path, overrides)

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

    # ── Undo / Redo ────────────────────────────────────────────────────────────

    def undo_last(self) -> None:
        """Step back one level in DAZ Studio's undo stack.

        Equivalent to pressing Ctrl+Z / Edit > Undo in DAZ Studio.
        Has no effect if the undo stack is empty.

        Note: this steps the global undo stack.  To group a series of changes
        into a single undoable operation use :meth:`undo` (the context manager).
        """
        script = ScriptBuilder.iife("App.getUndoStack().undo();")
        self._client.execute(script)

    def redo_last(self) -> None:
        """Step forward one level in DAZ Studio's undo stack.

        Equivalent to pressing Ctrl+Y / Edit > Redo in DAZ Studio.
        Has no effect if there is nothing to redo.
        """
        script = ScriptBuilder.iife("App.getUndoStack().redo();")
        self._client.execute(script)

    # ── dForce simulation ──────────────────────────────────────────────────────

    def is_simulating(self) -> bool:
        """Return ``True`` if a dForce simulation is currently running."""
        script = ScriptBuilder.iife("return App.getSimulationMgr().isSimulating();")
        return bool(self._client.execute(script).value)

    def clear_dforce_simulation(self) -> None:
        """Discard all cached dForce simulation data for the active engine."""
        script = ScriptBuilder.iife("App.getSimulationMgr().clearSimulation();")
        self._client.execute(script)

    def run_dforce_simulation(
        self,
        nodes: list[DazNode] | None = None,
        *,
        wait: bool = True,
        timeout: float = 300.0,
    ) -> str | None:
        """Run a dForce simulation using the active simulation engine.

        Args:
            nodes: Optional subset of nodes to simulate via
                ``DzSimulationEngine.customSimulate()``. ``None`` (default)
                simulates the whole scene via ``DzSimulationMgr.simulate()``,
                which follows the frame range configured in the Simulation
                Settings pane.
            wait: If ``True`` (default), block until the simulation finishes,
                using the async execute-and-poll endpoint since dForce runs can
                take minutes. If ``False``, submit the job and return
                immediately.
            timeout: Maximum seconds to wait when *wait* is ``True``.

        Returns:
            ``None`` when *wait* is ``True`` (the simulation already finished
            by the time this call returns). When *wait* is ``False``, the
            ``request_id`` of the submitted async job — poll it with
            :meth:`~dazpy.DazClient.get_request_status` /
            :meth:`~dazpy.DazClient.get_request_result`.

        Raises:
            :class:`~dazpy.exceptions.ScriptRuntimeError`: If the simulation
                engine reports an error.
        """
        if nodes:
            node_exprs = ",".join(ScriptBuilder.find_node_expr(n._identifier) for n in nodes)
            body = f"""
                var mgr = App.getSimulationMgr();
                var engine = mgr.getActiveSimulationEngine();
                if (!engine) return {{"error": "no_active_engine"}};
                var err = engine.customSimulate([{node_exprs}]);
                return {{"error": err ? String(err) : null}};
            """
        else:
            body = """
                var mgr = App.getSimulationMgr();
                var err = mgr.simulate();
                return {"error": err ? String(err) : null};
            """
        script = ScriptBuilder.iife(body)

        if not wait:
            return self._client.execute_async_submit(script)

        from ._polling import execute_long
        from .exceptions import ScriptRuntimeError
        result = execute_long(self._client, script, timeout=timeout)
        data = result.value or {}
        if data.get("error"):
            raise ScriptRuntimeError(f"dForce simulation failed: {data['error']}")
        return None
