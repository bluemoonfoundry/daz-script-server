from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence

from ._client import DazClient
from ._node import _FIND_NUMERIC_JS, _NODE_INFO_JS, DazNode, NodeIdentifier, NodeInfo
from ._script_builder import ScriptBuilder

if TYPE_CHECKING:
    from ._camera import DazCamera
    from ._scene_check import CheckReport
    from ._interaction import FigureRigProfile, InteractionRecipe, PreparedInteractionResult
    from ._light import DazLight
    from ._skeleton import DazSkeleton
    from ._undo import UndoGroup


@dataclass(frozen=True)
class ViewportCamera:
    """Snapshot of the camera the active 3D viewport is looking through.

    Attributes:
        label: The camera's label (e.g. ``"Perspective View"``, ``"Camera 1"``).
        name: The camera's internal name.
        in_scene: ``False`` for Studio's built-in view cameras (Perspective,
            Front, Top, ...), which are not scene nodes.
        position: World-space ``(x, y, z)`` at the time of the call.
        camera: A :class:`~dazpy.DazCamera` proxy when *in_scene*, else ``None``.
    """

    label: str
    name: str
    in_scene: bool
    position: tuple[float, float, float]
    camera: "DazCamera | None" = None


# JS: resolve a node reference (elementID, Parent/Label path, or a unique
# label/name). Returns {node} | {missing: ref} | {ambiguous, count, matches}.
# Needs _NODE_INFO_JS.
_RESOLVE_JS = """
            function _resolve(s) {
                if (/^[0-9]+$/.test(s)) {
                    var byId = Scene.findNodeByElementID(parseInt(s, 10));
                    return byId ? {node: byId} : {missing: s};
                }
                var slash = s.lastIndexOf("/");
                if (slash > 0) {
                    var parent = _resolve(s.substring(0, slash));
                    if (!parent.node) return parent;
                    var part = s.substring(slash + 1), child = null;
                    if (typeof parent.node.findNodeChildByLabel === "function")
                        child = parent.node.findNodeChildByLabel(part, true);
                    if (!child && typeof parent.node.findNodeChild === "function")
                        child = parent.node.findNodeChild(part, true);
                    return child ? {node: child} : {missing: s};
                }
                var matches = [];
                for (var i = 0; i < Scene.getNumNodes(); i++) {
                    var n = Scene.getNode(i);
                    if (n && (n.getLabel() === s || n.getName() === s)) matches.push(n);
                }
                if (matches.length === 1) return {node: matches[0]};
                if (matches.length === 0) return {missing: s};
                var info = [];
                for (var k = 0; k < matches.length && k < 12; k++) info.push(_nodeInfo(matches[k]));
                return {ambiguous: s, count: matches.length, matches: info};
            }
"""


@dataclass(frozen=True)
class CameraInfo:
    """One scene camera, from :meth:`DazScene.camera_info`."""

    index: int
    label: str
    name: str
    type: str
    element_id: int
    position: tuple[float, float, float]
    focal_length: float | None


@dataclass(frozen=True)
class LightInfo:
    """One scene light, from :meth:`DazScene.light_info`.

    ``flux`` is the light's "Flux" property (``None`` for light types
    without one); ``on`` is whether the node is visible.
    """

    index: int
    label: str
    name: str
    type: str
    element_id: int
    position: tuple[float, float, float]
    flux: float | None
    on: bool


@dataclass(frozen=True)
class BatchPropertyResult:
    """One operation's outcome from :meth:`DazScene.set_numeric_properties`."""

    ok: bool
    node: str | None
    property: str | None = None
    value: float | None = None
    error: str | None = None


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
                // DzLight inherits DzCamera: test lights first.
                if (n.inherits("DzSkeleton")) { nodeType = "DzSkeleton"; }
                else if (n.inherits("DzLight")) { nodeType = "DzLight"; }
                else if (n.inherits("DzCamera")) { nodeType = "DzCamera"; }
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

    # DzLight inherits DzCamera, so lights must be tested before cameras.
    _NODE_CLASSES = ("DzSkeleton", "DzLight", "DzCamera")

    def _typed_node(self, identifier: NodeIdentifier, class_name: str) -> DazNode:
        from ._skeleton import DazSkeleton
        from ._camera import DazCamera
        from ._light import DazLight
        cls = {"DzSkeleton": DazSkeleton, "DzCamera": DazCamera, "DzLight": DazLight}.get(
            class_name, DazNode)
        return cls(self._client, identifier)

    def resolve_node(self, ref: str | int) -> DazNode:
        """Resolve a node reference the way users and agents write them, in one call.

        *ref* may be:

        - an elementID (``4217`` or ``"4217"``),
        - a ``Parent/Label`` path (each step a label or name; the child is
          searched recursively under the parent), or
        - a label or internal name, which must match exactly one node.

        Returns:
            A proxy bound to the node's elementID (so later calls can't drift
            to a same-named node), typed :class:`~dazpy.DazSkeleton`,
            :class:`~dazpy.DazCamera`, :class:`~dazpy.DazLight` or
            :class:`~dazpy.DazNode`.

        Raises:
            ValueError: If *ref* is empty.
            NodeNotFoundError: If nothing matches.
            AmbiguousNodeError: If a label/name matches several nodes; its
                ``matches`` list the candidates with their elementIDs.
        """
        from .exceptions import AmbiguousNodeError, NodeNotFoundError
        text = str(ref).strip() if ref is not None else ""
        if not text:
            raise ValueError("resolve_node: a node reference is required")
        script = ScriptBuilder.iife(_NODE_INFO_JS + _RESOLVE_JS + f"""
            var r = _resolve({json.dumps(text)});
            if (r.node) {{
                var t = "DzNode", kinds = {json.dumps(list(self._NODE_CLASSES))};
                for (var c = 0; c < kinds.length; c++) if (r.node.inherits(kinds[c])) {{ t = kinds[c]; break; }}
                return {{status: "ok", element_id: r.node.elementID, type: t}};
            }}
            if (r.ambiguous) return {{status: "ambiguous", ref: r.ambiguous, count: r.count, matches: r.matches}};
            return {{status: "missing", ref: r.missing}};
        """)
        raw = self._client.execute(script).value or {"status": "missing", "ref": text}
        if raw["status"] == "ok":
            ident = NodeIdentifier(str(int(raw["element_id"])), kind="element_id")
            return self._typed_node(ident, raw.get("type", "DzNode"))
        if raw["status"] == "ambiguous":
            raise AmbiguousNodeError(
                raw.get("ref", text), int(raw.get("count", 0)),
                [NodeInfo._from_raw(m) for m in raw.get("matches", [])],
            )
        missing = raw.get("ref", text)
        detail = f" (no node at {missing!r})" if missing != text else ""
        raise NodeNotFoundError(f"Node not found: {text!r}{detail}")

    def set_numeric_properties(
        self, operations: Sequence[tuple[str | int, str, float]]
    ) -> list[BatchPropertyResult]:
        """Set many numeric properties across nodes in one call.

        Each operation is ``(node_ref, property_name, value)``: *node_ref*
        as for :meth:`resolve_node`, *property_name* matched like
        :meth:`DazNode.set_numeric_property` (exact, case-insensitive; locked
        properties are unlocked). A failing operation doesn't stop the
        others; its result carries the error.
        """
        ops = [{"node": str(n), "prop": str(p), "value": float(v)} for n, p, v in operations]
        if not ops:
            return []
        script = ScriptBuilder.iife(_NODE_INFO_JS + _RESOLVE_JS + _FIND_NUMERIC_JS + f"""
            var _ops = {json.dumps(ops)}, _out = [];
            for (var i = 0; i < _ops.length; i++) {{
                var op = _ops[i];
                try {{
                    var r = _resolve(op.node);
                    if (r.ambiguous) throw new Error("Ambiguous node '" + op.node + "' (" + r.count +
                        " matches). Use elementID or Parent/Label.");
                    if (!r.node) throw new Error("Node not found: " + op.node);
                    var h = _findNumeric(r.node, op.prop.toLowerCase(), false);
                    if (!h) throw new Error("Property not found: " + op.prop);
                    var p = h.prop;
                    if (!p.inherits("DzNumericProperty")) throw new Error("Property is not numeric: " + op.prop);
                    if (typeof p.lock === "function" && p.isLocked && p.isLocked()) p.lock(false);
                    p.setValue(op.value);
                    _out.push({{ok: true, node: r.node.getLabel(), property: p.getLabel(), value: p.getValue()}});
                }} catch (e) {{
                    _out.push({{ok: false, node: null, error: e.message || String(e)}});
                }}
            }}
            return _out;
        """)
        raw = self._client.execute(script).value or []
        return [BatchPropertyResult(bool(r.get("ok")), r.get("node"), r.get("property"),
                                    r.get("value"), r.get("error")) for r in raw]

    def find_nodes(self, query: str) -> list[NodeInfo]:
        """Every node whose label or internal name equals *query* exactly.

        Use it to list same-labelled nodes and pick one by
        :attr:`NodeInfo.element_id`.
        """
        script = ScriptBuilder.iife(_NODE_INFO_JS + f"""
            var q = {json.dumps(query)}, out = [];
            for (var i = 0; i < Scene.getNumNodes(); i++) {{
                var n = Scene.getNode(i);
                if (n && (n.getLabel() === q || n.getName() === q)) out.push(_nodeInfo(n));
            }}
            return out;
        """)
        return [NodeInfo._from_raw(r) for r in self._client.execute(script).value or []]

    def content_path(self, relative: str) -> str | None:
        """Resolve a content-library-relative path to an absolute path.

        Searches every configured content directory, as Studio does for
        asset references (e.g. ``"Shader Presets/Iray/DAZ Uber/!Iray Uber Base.duf"``).

        Returns:
            The absolute path, or ``None`` if no content directory has it.
        """
        script = ScriptBuilder.iife(
            f"return App.getContentMgr().getAbsolutePath({json.dumps(relative)}, false, \"\") || \"\";"
        )
        return self._client.execute(script).value or None

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

    def check(self, camera: str | None = None, *, engine: str | None = None,
              resolution: tuple[int, int] | None = None,
              allow_crop: bool = False) -> "CheckReport":
        """Pre-render checks for a render from *camera* (one Studio script).

        Checks that each visible figure (top-level, not fitted to another) is
        inside the camera's frame, and that something will light the render.
        Findings (see :class:`~dazpy.CheckFinding`):

        - ``subject_out_of_frame`` (warning): part of a figure's bounding box is
          outside the frame; ``sides`` says which edges (a head or feet cut off
          shows as ``top`` / ``bottom``). The box is loose, so an outstretched
          arm can trigger it with nothing visible cut off.
        - ``subject_not_in_frame`` (warning): a figure is entirely out of frame.
        - ``no_subject_in_frame`` (error): the scene has figures and the camera
          sees none of them.
        - ``no_light`` (error): no light is on with non-zero intensity, the
          environment does not light the scene (mode Scene Only, or intensity
          0) and the camera headlamp is off. Not checked for the OpenGL engines.
        - ``camera_not_found`` (error): no camera has that label.

        Args:
            camera: Camera label; ``None`` checks the active viewport camera
                (what :func:`dazpy.render` renders from by default).
            engine: Engine the render will use (``"iray"``, ``"filament"``,
                ``"viewport"``); default: the active engine.
            resolution: ``(width, height)`` of the render; default: the render
                settings' aspect ratio.
            allow_crop: Drop the two framing warnings (a deliberate crop).
        """
        from ._scene_check import check_scene
        return check_scene(self._client, camera, engine=engine, resolution=resolution,
                           allow_crop=allow_crop)

    def cameras(self) -> list["DazCamera"]:
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

    def lights(self) -> list["DazLight"]:
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

    def viewport_camera(self) -> ViewportCamera | None:
        """Return the camera the active 3D viewport is looking through.

        This is often one of Studio's built-in view cameras (``"Perspective
        View"``), which is not a scene node and so is not in :meth:`cameras`;
        :attr:`ViewportCamera.in_scene` says which kind it is.

        Returns:
            A :class:`ViewportCamera` snapshot, or ``None`` when there is no
            active 3D viewport (e.g. Studio is running without a main window).
        """
        from ._camera import DazCamera
        script = ScriptBuilder.iife("""
            var _vm = (typeof MainWindow !== "undefined" && MainWindow) ? MainWindow.getViewportMgr() : null;
            var _vp = _vm ? _vm.getActiveViewport() : null;
            var _v3 = _vp ? _vp.get3DViewport() : null;
            var _cam = _v3 ? _v3.getCamera() : null;
            if (!_cam) return null;
            var _p = _cam.getWSPos();
            return {label: _cam.getLabel(), name: _cam.getName(),
                    in_scene: _cam.isInScene(), position: [_p.x, _p.y, _p.z]};
        """)
        raw = self._client.execute(script).value
        if not raw:
            return None
        in_scene = bool(raw.get("in_scene"))
        pos = raw.get("position") or [0.0, 0.0, 0.0]
        return ViewportCamera(
            label=raw.get("label", ""),
            name=raw.get("name", ""),
            in_scene=in_scene,
            position=(float(pos[0]), float(pos[1]), float(pos[2])),
            camera=DazCamera(self._client, NodeIdentifier(raw["name"])) if in_scene else None,
        )

    def set_viewport_camera(self, camera: "DazCamera | str") -> str | None:
        """Look through *camera* in the active 3D viewport.

        *camera* is a :class:`~dazpy.DazCamera`, or a label: a scene camera's,
        or one of Studio's built-in view cameras (``"Perspective View"``,
        ``"Front View"``, ...), which are not scene nodes.

        Returns:
            The label of the camera the viewport used before.

        Raises:
            NodeNotFoundError: If *camera* is not in the scene.
            TypeError: If the node is not a camera.
            RuntimeError: If there is no active 3D viewport.
        """
        from .exceptions import NodeNotFoundError
        if isinstance(camera, str):
            label = json.dumps(camera)
            locator = f"""(function(){{
                for (var i = 0; i < Scene.getNumCameras(); i++)
                    if (Scene.getCamera(i).getLabel() === {label}) return Scene.getCamera(i);
                var vm = (typeof MainWindow !== "undefined" && MainWindow) ? MainWindow.getViewportMgr() : null;
                if (vm) for (var j = 0; j < vm.getNumViewCameras(); j++)
                    if (vm.getViewCamera(j).getLabel() === {label}) return vm.getViewCamera(j);
                return null;
            }})()"""
            ref = camera
        else:
            locator, ref = camera._locator, camera._identifier.value
        script = ScriptBuilder.iife(f"""
            var _cam = {locator};
            if (!_cam) return {{status: "missing"}};
            if (!_cam.inherits("DzCamera")) return {{status: "not_camera"}};
            var _vm = (typeof MainWindow !== "undefined" && MainWindow) ? MainWindow.getViewportMgr() : null;
            var _vp = _vm ? _vm.getActiveViewport() : null;
            var _v3 = _vp ? _vp.get3DViewport() : null;
            if (!_v3) return {{status: "no_viewport"}};
            var _prev = _v3.getCamera();
            _v3.setCamera(_cam);
            return {{status: "ok", previous: _prev ? _prev.getLabel() : null}};
        """)
        raw = self._client.execute(script).value or {"status": "missing"}
        if raw["status"] == "missing":
            raise NodeNotFoundError(f"Camera not found: {ref!r}")
        if raw["status"] == "not_camera":
            raise TypeError(f"Node is not a camera: {ref!r}")
        if raw["status"] == "no_viewport":
            raise RuntimeError("No active 3D viewport")
        return raw.get("previous")

    def camera_info(self) -> list[CameraInfo]:
        """Every scene camera with position and focal length, in one call."""
        script = ScriptBuilder.iife("""
            var out = [];
            for (var i = 0; i < Scene.getNumCameras(); i++) {
                var c = Scene.getCamera(i), p = c.getWSPos();
                var fl = c.getFocalLengthControl ? c.getFocalLengthControl() : null;
                out.push({index: i, label: c.getLabel(), name: c.getName(), type: c.className(),
                          element_id: c.elementID, position: [p.x, p.y, p.z],
                          focal_length: fl ? fl.getValue() : null});
            }
            return out;
        """)
        return [CameraInfo(r["index"], r["label"], r["name"], r["type"], int(r["element_id"]),
                           tuple(float(v) for v in r["position"]), r.get("focal_length"))  # type: ignore[arg-type]
                for r in self._client.execute(script).value or []]

    def light_info(self) -> list[LightInfo]:
        """Every scene light with position, flux and on/off state, in one call."""
        script = ScriptBuilder.iife("""
            var out = [];
            for (var i = 0; i < Scene.getNumLights(); i++) {
                var l = Scene.getLight(i), p = l.getWSPos(), f = l.findProperty("Flux");
                out.push({index: i, label: l.getLabel(), name: l.getName(), type: l.className(),
                          element_id: l.elementID, position: [p.x, p.y, p.z],
                          flux: f ? f.getValue() : null, on: l.isVisible()});
            }
            return out;
        """)
        return [LightInfo(r["index"], r["label"], r["name"], r["type"], int(r["element_id"]),
                          tuple(float(v) for v in r["position"]), r.get("flux"),  # type: ignore[arg-type]
                          bool(r.get("on", True)))
                for r in self._client.execute(script).value or []]

    def find_camera_by_label(self, label: str) -> "DazCamera":
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

    def create_camera(self, name: str | None = None) -> "DazCamera":
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
            return cam.elementID;
        """)
        # Bound by elementID: without a name Studio leaves getName() empty,
        # and a name lookup would be ambiguous or fail.
        element_id = self._client.execute(script).value
        return DazCamera(self._client, NodeIdentifier(str(int(element_id)), kind="element_id"))

    def create_light(self, light_type: str, name: str | None = None) -> "DazLight":
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
            return light.elementID;
        """)
        # Bound by elementID: without a name Studio leaves getName() empty.
        element_id = self._client.execute(script).value
        return DazLight(self._client, NodeIdentifier(str(int(element_id)), kind="element_id"))

    def create_group(
        self,
        name: str,
        label: str | None = None,
        position: tuple[float, float, float] | None = None,
    ) -> DazNode:
        """Create an empty group node (``DzGroupNode``) and add it to the scene.

        Use it as a parent for nodes that move together, such as a camera rig.

        Args:
            name: Internal name for the new group.
            label: The label shown in the Scene panel (default: *name*).  It is
                set after the node is added: on DS4 a label set before
                ``Scene.addNode`` does not stick on a scripted node.
            position: Optional world-space position ``(x, y, z)`` in cm.

        Returns:
            A :class:`~dazpy.DazNode` proxy for the new group, by the name
            Studio gave it.

        Raises:
            ValueError: If *name* is empty.
        """
        if not name:
            raise ValueError("create_group needs a non-empty name")
        name_js = ScriptBuilder.escape_string(name)
        label_js = ScriptBuilder.escape_string(name if label is None else label)
        place = ""
        if position is not None:
            x, y, z = (float(v) for v in position)
            place = f"g.setWSPos(new DzVec3({x}, {y}, {z}));"
        script = ScriptBuilder.iife(f"""
            var g = new DzGroupNode();
            g.setName({name_js});
            Scene.addNode(g);
            g.setLabel({label_js});
            {place}
            return g.getName();
        """)
        created_name = self._client.execute(script).value
        return DazNode(self._client, NodeIdentifier(created_name))

    def find_light_by_label(self, label: str) -> "DazLight":
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

    def skeletons(self) -> list["DazSkeleton"]:
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

    def find_skeleton(
        self, name: str, *, retry_attempts: int = 3, retry_delay: float = 0.15
    ) -> "DazSkeleton":
        """Find a skeleton by its internal name.

        Args:
            name: Internal name of the skeleton node (e.g. ``"Genesis9"``).
                  To look up by the user-visible label shown in the Scene panel
                  (e.g. ``"Genesis 9"``), use :meth:`find_skeleton_by_label`.
            retry_attempts: Number of ``Scene.getSkeletonList()`` lookups to
                try before concluding the skeleton is really absent.
                ``Scene.getSkeletonList()`` has been observed to transiently
                omit a skeleton that is present under load from a burst of
                other main-thread script calls (see daz-script-server-xtkd)
                -- a momentary miss is retried rather than immediately
                raised. Set to ``1`` to disable retrying.
            retry_delay: Base seconds to sleep between retries (each attempt
                after the first waits ``retry_delay * attempt_number``).

        Returns:
            A :class:`~dazpy.DazSkeleton` proxy.

        Raises:
            NodeNotFoundError: If no skeleton with that name exists after
                *retry_attempts* lookups.
        """
        import time

        from ._skeleton import DazSkeleton
        from .exceptions import NodeNotFoundError
        lookup = ScriptBuilder.iife(f"""
            var skels = Scene.getSkeletonList();
            for (var i = 0; i < skels.length; i++) {{
                if (skels[i].getName() === {ScriptBuilder.escape_string(name)}) return true;
            }}
            return false;
        """)
        found = False
        for attempt in range(retry_attempts):
            if self._client.execute(lookup).value:
                found = True
                break
            if attempt < retry_attempts - 1:
                time.sleep(retry_delay * (attempt + 1))
        if not found:
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

    def find_skeleton_by_label(self, label: str) -> "DazSkeleton":
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
        ``name``, ``label``, ``position`` (the figure node's world position,
        ``{"x", "y", "z"}``), and ``bones`` — a list of dicts with ``name``,
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
                        rotation_order: _b.getRotationOrder().toString(),
                        local_position: {{x: _lpos.x, y: _lpos.y, z: _lpos.z}},
                        world_position: {{x: _wpos.x, y: _wpos.y, z: _wpos.z}},
                        local_euler: {{
                            x: _b.getXRotControl().getValue(),
                            y: _b.getYRotControl().getValue(),
                            z: _b.getZRotControl().getValue()
                        }}
                    }});
                }}
                var _spos = _skel.getWSPos();
                _result.push({{
                    name: _skel.getName(),
                    label: _skel.getLabel(),
                    position: {{x: _spos.x, y: _spos.y, z: _spos.z}},
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
        recipe: "InteractionRecipe",
        *,
        rig_profiles: dict[str, "FigureRigProfile"] | None = None,
        align_limb_targets: bool = False,
        max_iterations: int | None = None,
        step_degrees: float = 1.0,
        damping: float = 0.25,
        tolerance: float = 0.15,
    ) -> "PreparedInteractionResult":
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

    def undo(self, label: str) -> "UndoGroup":
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

    def load(self, path: str, *, replace: bool = False) -> None:
        """Load a scene file, merging it into the current scene by default.

        Args:
            path: Absolute path to the ``.daz`` or ``.duf`` file on the server
                host.
            replace: Clear the current scene first, so the file replaces it.
                Done as ``Scene.clear()`` then a merge rather than
                ``DzScene.OpenNew``, which can raise a modal "save changes?"
                prompt that blocks the script server. Unsaved changes are
                discarded.
        """
        clear = "Scene.clear(); " if replace else ""
        script = ScriptBuilder.iife(
            # DzScene.MergeFile (= 2 on DS4); 0 and OpenNew (1) replace the scene.
            f"{clear}Scene.loadScene({ScriptBuilder.escape_string(path)}, DzScene.MergeFile);"
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
        from ._client import _authentication_error
        from .exceptions import DazError
        resp = self._client._post("/scene/save-copy", {"path": path})
        if resp.status_code in (401, 403):
            raise _authentication_error(resp)
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

        This is a plain synchronous call: FBX export is a native DAZ Studio
        exporter (``DzFbxExporter``), so there's no async job to poll.

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
        overrides: dict[str, object] = {
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
        overrides: dict[str, object] = {
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
        script = ScriptBuilder.iife("UndoStack.undo();")
        self._client.execute(script)

    def redo_last(self) -> None:
        """Step forward one level in DAZ Studio's undo stack.

        Equivalent to pressing Ctrl+Y / Edit > Redo in DAZ Studio.
        Has no effect if there is nothing to redo.
        """
        script = ScriptBuilder.iife("UndoStack.redo();")
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
        memorized_pose: bool = False,
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
            memorized_pose: If ``True``, sets the active engine's
                ``startFromMemorizedPose`` global simulation setting before
                simulating, so pose-based bulge corrections are computed
                against the engine's memorized reference pose instead of the
                figure's live pose. Mirrors the "Start Bulge from Memorized
                Pose" checkbox in DAZ Studio's Simulation Settings pane.
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
        memorized_flag = "true" if memorized_pose else "false"
        if nodes:
            node_exprs = ",".join(ScriptBuilder.find_node_expr(n._identifier) for n in nodes)
            body = f"""
                var mgr = App.getSimulationMgr();
                var engine = mgr.getActiveSimulationEngine();
                if (!engine) return {{"error": "no_active_engine"}};
                engine.getGlobalSimulationSettings().startFromMemorizedPose = {memorized_flag};
                var err = engine.customSimulate([{node_exprs}]);
                return {{"error": err ? String(err) : null}};
            """
        else:
            body = f"""
                var mgr = App.getSimulationMgr();
                var engine = mgr.getActiveSimulationEngine();
                if (!engine) return {{"error": "no_active_engine"}};
                engine.getGlobalSimulationSettings().startFromMemorizedPose = {memorized_flag};
                var err = mgr.simulate();
                return {{"error": err ? String(err) : null}};
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
