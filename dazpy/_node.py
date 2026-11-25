from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional, Sequence

from ._element import DazElement
from ._script_builder import ScriptBuilder

#: Segment kinds accepted by :meth:`DazNode.set_transform_key_interpolation`.
TRANSFORM_KEY_KINDS = ("linear", "constant", "smooth", "hermite")

# _kiApply(control, frames, kinds, fastStart, fastEnd): see
# DazNode.set_transform_key_interpolation. Hermite tangents are value per tick
# (live-verified on Studio 6.26: a two-key fast-end move samples exactly t^2).
# Studio's own TCB tangent drops to zero after a non-TCB key, so eased moves
# write every segment as Hermite rather than mixing. The type is written with
# setValue(tm, value, interp, p0, p1, p2) on the key's own value: Studio 4.24
# ignores setKeyInterpolationType on an existing key (live-verified).
_KEY_INTERP_JS = (
    "function _kiFast(s, m) { var q = 2 * s - m; "
    "if (s > 0) return Math.min(Math.max(q, s), 3 * s); "
    "if (s < 0) return Math.max(Math.min(q, s), 3 * s); return 0; }\n"
    "function _kiApply(c, F, K, fs, fe) {\n"
    "  var n = F.length, ts = Scene.getTimeStep(), t = [], v = [], T = [], i, k;\n"
    "  for (k = 0; k < n; k++) { t.push(F[k] * ts); v.push(c.getValue(t[k])); }\n"
    "  function sl(a) { return (v[a + 1] - v[a]) / (t[a + 1] - t[a]); }\n"
    "  for (k = 1; k < n - 1; k++) T[k] = (v[k + 1] - v[k - 1]) / (t[k + 1] - t[k - 1]);\n"
    "  T[0] = (fs && n > 1) ? _kiFast(sl(0), n > 2 ? T[1] : 0) : 0;\n"
    "  T[n - 1] = (fe && n > 1) ? _kiFast(sl(n - 2), n > 2 ? T[n - 2] : 0) : 0;\n"
    "  for (k = 0; k < n; k++) {\n"
    "    if (!K[k]) continue;\n"
    "    i = c.findKeyIndex(t[k]); if (i < 0 || c.getKeyTime(i) != t[k]) continue;\n"
    "    if (K[k] == \"linear\") c.setValue(t[k], v[k], DzProperty.InterpLinear, 0, 0, 0);\n"
    "    else if (K[k] == \"constant\") c.setValue(t[k], v[k], DzProperty.InterpConstant, 0, 0, 0);\n"
    "    else if (K[k] == \"smooth\" || k == n - 1) c.setValue(t[k], v[k], DzProperty.InterpTCB, 0, 0, 0);\n"
    "    else c.setValue(t[k], v[k], DzProperty.InterpHermite, T[k], T[k + 1], 0);\n"
    "  }\n"
    "}\n"
)

if TYPE_CHECKING:
    from ._material import DazMaterial, MaterialInfo
    from ._modifier import DazModifier
    from ._morph import DazMorph
    from ._dforce import DazDForce
    from ._client import DazClient
    from ._property import DazProperty


@dataclass
class NodeIdentifier:
    """Identifies a scene node by name or label.

    Attributes:
        value: The name or label string used to look up the node.
        kind: Either ``"name"`` (uses ``Scene.findNode()``) or ``"label"``
            (uses ``Scene.findNodeByLabel()``).
    """

    value: str
    kind: str = "name"  # "name" or "label"


@dataclass(frozen=True)
class NodeInfo:
    """Identity of a scene node, as returned by :meth:`DazScene.find_nodes`,
    :meth:`DazNode.describe` and :class:`~dazpy.exceptions.AmbiguousNodeError`.

    Attributes:
        label: Display label.
        name: Internal name.
        type: DazScript class name (``"DzFigure"``, ``"DzNode"``, ...).
        element_id: Studio's per-session unique id; stable while the scene is open.
        parent: Parent node's label, or ``None`` at the scene root.
        num_children: Direct child count (``None`` where not collected).
    """

    label: str
    name: str
    type: str
    element_id: int
    parent: str | None
    num_children: int | None = None

    @classmethod
    def _from_raw(cls, raw: dict) -> "NodeInfo":
        return cls(
            label=raw.get("label", ""),
            name=raw.get("name", ""),
            type=raw.get("type", ""),
            element_id=int(raw.get("element_id", 0)),
            parent=raw.get("parent"),
            num_children=raw.get("num_children"),
        )


@dataclass(frozen=True)
class PropertyDetails:
    """One node property with its metadata, from :meth:`DazNode.property_details`.

    ``value``/``min``/``max``/``default`` are ``None`` where they don't apply
    (non-numeric properties; ``value`` is kept for string properties).
    """

    label: str
    name: str
    type: str
    value: Any
    min: float | None
    max: float | None
    default: Any
    path: str
    is_animatable: bool

    @classmethod
    def _from_raw(cls, r: dict) -> "PropertyDetails":
        return cls(r["label"], r["name"], r["type"], r.get("value"), r.get("min"),
                   r.get("max"), r.get("default"), r.get("path", ""),
                   bool(r.get("is_animatable")))


_PROPERTY_KINDS = ("all", "numeric", "transform", "morph", "bool", "string")

_PROPERTY_DETAIL_JS = """
    var _TRANSFORMS = {XTranslate: 1, YTranslate: 1, ZTranslate: 1, XRotate: 1, YRotate: 1,
                       ZRotate: 1, Scale: 1, XScale: 1, YScale: 1, ZScale: 1};
    function _detail(p) {
        var cls = p.className(), num = p.inherits("DzNumericProperty");
        var str = cls === "DzStringProperty";
        return {label: p.getLabel(), name: p.getName(), type: cls,
                value: (num || str) ? p.getValue() : null,
                min: (num && p.getMin) ? p.getMin() : null,
                max: (num && p.getMax) ? p.getMax() : null,
                default: (num && p.getDefaultValue) ? p.getDefaultValue() : null,
                path: p.getPath ? p.getPath() : "",
                is_animatable: p.canAnimate ? p.canAnimate() : false};
    }
    function _kindOf(p) {
        var cls = p.className(), num = p.inherits("DzNumericProperty");
        return {numeric: num, transform: _TRANSFORMS[p.getName()] === 1,
                bool: cls === "DzBoolProperty", string: cls === "DzStringProperty"};
    }
"""


@dataclass(frozen=True)
class MorphInfo:
    """One ``DzMorph`` on a node, from :meth:`DazNode.morph_info`."""

    name: str
    label: str
    value: float
    path: str


@dataclass(frozen=True)
class NumericPropertyWrite:
    """Result of :meth:`DazNode.set_numeric_property`: the property that was
    written and the value read back after the write."""

    label: str
    name: str
    value: float


# JS: collect every numeric channel on _node in search order -- node
# properties, then each modifier's value channel and its own properties.
_NUMERIC_CHANNELS_JS = """
    function _numericChannels(node) {
        var out = [];
        function add(p, alias) {
            if (p && p.inherits("DzNumericProperty")) out.push({prop: p, alias: alias || null});
        }
        var i, j, m;
        for (i = 0; i < node.getNumProperties(); i++) add(node.getProperty(i));
        var obj = (typeof node.getObject === "function") ? node.getObject() : null;
        if (obj && typeof obj.getNumModifiers === "function") {
            for (i = 0; i < obj.getNumModifiers(); i++) {
                m = obj.getModifier(i);
                if (!m) continue;
                if (typeof m.getValueChannel === "function") add(m.getValueChannel(), m);
                if (typeof m.getNumProperties === "function") {
                    for (j = 0; j < m.getNumProperties(); j++) add(m.getProperty(j));
                }
            }
        }
        return out;
    }
"""

# JS: find a property on `node` whose label or name equals `want` (lowercased),
# or contains it when `substring`. Searches node properties, then each
# modifier (a morph matched by its own name/label resolves to its value
# channel) and the modifier's properties. Returns {prop, owner} or null;
# owner is the modifier when matched through one.
_FIND_NUMERIC_JS = """
    function _findNumeric(node, want, substring) {
        function names(p, alias) {
            var out = [p.getLabel().toLowerCase(), p.getName().toLowerCase()];
            if (alias) { out.push(alias.getLabel().toLowerCase()); out.push(alias.getName().toLowerCase()); }
            return out;
        }
        function scan(test) {
            var i, j, k, n, p, obj, m, ch;
            for (i = 0; i < node.getNumProperties(); i++) {
                p = node.getProperty(i); n = names(p, null);
                for (j = 0; j < n.length; j++) if (test(n[j])) return {prop: p, owner: null};
            }
            obj = (typeof node.getObject === "function") ? node.getObject() : null;
            if (!obj || typeof obj.getNumModifiers !== "function") return null;
            for (i = 0; i < obj.getNumModifiers(); i++) {
                m = obj.getModifier(i);
                if (!m) continue;
                ch = (typeof m.getValueChannel === "function") ? m.getValueChannel() : null;
                if (ch) {
                    n = names(ch, m);
                    for (j = 0; j < n.length; j++) if (test(n[j])) return {prop: ch, owner: m};
                }
                if (typeof m.getNumProperties === "function") {
                    for (k = 0; k < m.getNumProperties(); k++) {
                        p = m.getProperty(k); n = names(p, null);
                        for (j = 0; j < n.length; j++) if (test(n[j])) return {prop: p, owner: null};
                    }
                }
            }
            return null;
        }
        var hit = scan(function (s) { return s === want; });
        if (!hit && substring) hit = scan(function (s) { return s.indexOf(want) !== -1; });
        return hit;
    }
"""

_NODE_INFO_JS = """
    function _nodeInfo(n) {
        var p = n.getNodeParent ? n.getNodeParent() : null;
        return {label: n.getLabel(), name: n.getName(), type: n.className(),
                element_id: n.elementID, parent: p ? p.getLabel() : null,
                num_children: n.getNumNodeChildren()};
    }
"""


@dataclass(frozen=True)
class NumericCandidateMatch:
    """One slot's outcome from :meth:`DazNode.set_numeric_candidates`.

    Attributes:
        candidates: The names tried, in order.
        requested: The value the slot asked for.
        matched: The candidate name that resolved, or ``None`` if none did.
        source: ``"property"`` (a node-level property, e.g. an expression
            controller dial) or ``"modifier"`` (a morph's value channel);
            ``None`` when nothing matched.
        value: The value read back after the write (``None`` when nothing
            matched). Can differ from *requested* if the dial clamps.
    """

    candidates: tuple[str, ...]
    requested: float
    matched: str | None
    source: str | None
    value: float | None

    @property
    def found(self) -> bool:
        return self.matched is not None


class DazNode(DazElement):
    """Proxy for a ``DzNode`` in the active DAZ Studio scene.

    Provides access to transforms, hierarchy, visibility, materials,
    modifiers, and geometry.  Instances are typically obtained from
    :class:`~dazpy.DazScene` rather than constructed directly.

    All properties that read from the server may return ``None`` if the node
    no longer exists in the scene.

    Args:
        client: The :class:`~dazpy.DazClient` for remote calls.
        identifier: Identifies the underlying ``DzNode``.
    """

    _identifier: NodeIdentifier

    def __init__(self, client: "DazClient", identifier: NodeIdentifier):
        locator = ScriptBuilder.find_node_expr(identifier)
        super().__init__(client, locator)
        object.__setattr__(self, "_identifier", identifier)

    @property
    def label(self) -> str | None:
        """User-visible display label shown in the Scene panel (read/write)."""
        script = ScriptBuilder.node_body_from_locator(self._locator, "return _node.getLabel();")
        return self._client.execute(script).value

    @label.setter
    def label(self, value: str) -> None:
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            f"_node.setLabel({json.dumps(value)});"
        )
        self._client.execute(script)

    @property
    def name(self) -> str | None:
        """Internal node name used to look up the node (read-only)."""
        script = ScriptBuilder.node_body_from_locator(self._locator, "return _node.getName();")
        return self._client.execute(script).value

    @property
    def position(self) -> dict | None:
        """World-space position as ``{"x": float, "y": float, "z": float}`` (read-only).

        Use :meth:`set_position` to change.
        """
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            "var p = _node.getWSPos(); return {x: p.x, y: p.y, z: p.z};"
        )
        return self._client.execute(script).value

    def set_position(self, x: float, y: float, z: float) -> None:
        """Set the world-space position of this node.

        Args:
            x: X coordinate in DAZ Studio units (centimetres by default).
            y: Y coordinate.
            z: Z coordinate.
        """
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            f"_node.setWSPos(new DzVec3({x}, {y}, {z}));"
        )
        self._client.execute(script)

    @property
    def rotation(self) -> dict | None:
        """World-space rotation as ``{"x", "y", "z", "w"}`` quaternion (read-only).

        Use :meth:`set_rotation` to change (accepts Euler angles in degrees).
        """
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            "var r = _node.getWSRot(); return {x: r.x, y: r.y, z: r.z, w: r.w};"
        )
        return self._client.execute(script).value

    @property
    def general_scale(self) -> float | None:
        """Uniform scale factor (read-only)."""
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            "return _node.getScaleControl().getValue();"
        )
        return self._client.execute(script).value

    @property
    def scale(self) -> dict | None:
        """Per-axis and uniform scale as ``{"x", "y", "z", "general"}`` (read-only).

        Use :meth:`set_scale` to change the per-axis values.
        """
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            "return {x: _node.getXScaleControl().getValue(), y: _node.getYScaleControl().getValue(), z: _node.getZScaleControl().getValue(), general: _node.getScaleControl().getValue()};"
        )
        return self._client.execute(script).value

    def set_scale(self, x: float, y: float, z: float) -> None:
        """Set per-axis local scale.

        Does not affect the general/uniform scale dial (:attr:`general_scale`)
        — DAZ Studio tracks per-axis and uniform scale as separate controls.

        Args:
            x: X-axis scale factor (1.0 = unscaled).
            y: Y-axis scale factor.
            z: Z-axis scale factor.
        """
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            f"_node.getXScaleControl().setValue({x}); _node.getYScaleControl().setValue({y}); _node.getZScaleControl().setValue({z});"
        )
        self._client.execute(script)

    def set_transform(
        self,
        position: tuple[float, float, float] | None = None,
        rotation: tuple[float, float, float] | None = None,
        scale: tuple[float, float, float] | None = None,
    ) -> None:
        """Set any combination of local position, rotation, and scale in one call.

        Every argument is optional. Omitted components are left untouched.
        Equivalent to calling :meth:`set_local_position`, :meth:`set_local_rotation`,
        and/or :meth:`set_scale` individually, but round-trips only once.

        Args:
            position: ``(x, y, z)`` local-space position, or ``None`` to leave unchanged.
            rotation: ``(x, y, z)`` Euler rotation in degrees, or ``None`` to leave unchanged.
            scale: ``(x, y, z)`` per-axis scale, or ``None`` to leave unchanged.
        """
        lines = []
        if position is not None:
            x, y, z = position
            lines.append(f"_node.setLocalPos(new DzVec3({x}, {y}, {z}));")
        if rotation is not None:
            x, y, z = rotation
            lines.append(
                f"_node.getXRotControl().setValue({x}); "
                f"_node.getYRotControl().setValue({y}); "
                f"_node.getZRotControl().setValue({z});"
            )
        if scale is not None:
            x, y, z = scale
            lines.append(
                f"_node.getXScaleControl().setValue({x}); "
                f"_node.getYScaleControl().setValue({y}); "
                f"_node.getZScaleControl().setValue({z});"
            )
        if not lines:
            return
        script = ScriptBuilder.node_body_from_locator(self._locator, "\n".join(lines))
        self._client.execute(script)

    @property
    def visible(self) -> bool | None:
        """General visibility flag (read/write).

        Affects both viewport and render visibility unless overridden by the
        per-channel visibility setters.
        """
        script = ScriptBuilder.node_body_from_locator(self._locator, "return _node.isVisible();")
        return self._client.execute(script).value

    @visible.setter
    def visible(self, value: bool) -> None:
        flag = "true" if value else "false"
        script = ScriptBuilder.node_body_from_locator(self._locator, f"_node.setVisible({flag});")
        self._client.execute(script)

    @property
    def parent(self) -> DazNode | None:
        """Parent node in the scene hierarchy, or ``None`` for root nodes."""
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            "var p = _node.getNodeParent(); return p ? p.getName() : null;"
        )
        name = self._client.execute(script).value
        if name is None:
            return None
        return DazNode(self._client, NodeIdentifier(name))

    @property
    def children(self) -> list[DazNode]:
        """Direct child nodes."""
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            """
            var names = [];
            for (var i = 0; i < _node.getNumNodeChildren(); i++) {
                names.push(_node.getNodeChild(i).getName());
            }
            return names;
            """
        )
        names = self._client.execute(script).value or []
        return [DazNode(self._client, NodeIdentifier(n)) for n in names]

    def delete(self) -> bool:
        """Remove this node from the scene entirely.

        Returns:
            ``True`` if the node was found and removed, ``False`` otherwise.
        """
        script = ScriptBuilder.node_body_from_locator(self._locator, "return Scene.removeNode(_node);")
        return bool(self._client.execute(script).value)

    def hierarchy(self, max_depth: int | None = None) -> dict:
        """Return the descendant tree under this node, in one call.

        Args:
            max_depth: Levels to include below this node (this node is level
                0). ``None`` or ``0`` means unlimited.

        Returns:
            ``{"node": label, "hierarchy": {...}, "total_descendants": int}``,
            each entry ``{"label", "name", "type", "element_id", "children"}``
            (``children`` omitted on leaves). ``total_descendants`` counts
            the children visited, including those at the depth limit.

        Raises:
            NodeNotFoundError: If this node is not in the scene.
        """
        from .exceptions import NodeNotFoundError
        depth = int(max_depth) if max_depth else 0
        script = ScriptBuilder.node_body_from_locator(self._locator, f"""
            var _maxDepth = {depth};
            var _total = 0;
            function _build(n, depth) {{
                if (_maxDepth > 0 && depth >= _maxDepth) return null;
                var info = {{label: n.getLabel(), name: n.getName(), type: n.className(),
                             element_id: n.elementID}};
                var children = [];
                for (var i = 0; i < n.getNumNodeChildren(); i++) {{
                    _total++;
                    var c = _build(n.getNodeChild(i), depth + 1);
                    if (c) children.push(c);
                }}
                if (children.length > 0) info.children = children;
                return info;
            }}
            var _h = _build(_node, 0);
            return {{node: _node.getLabel(), hierarchy: _h, total_descendants: _total}};
        """)
        result = self._client.execute(script).value
        if result is None:
            raise NodeNotFoundError(f"Node not found: {self._identifier.value!r}")
        return result

    def unparent(self, *, preserve_world_transform: bool = True) -> None:
        """Detach this node from its parent so it sits at the scene root.

        A no-op for a node that is already at the root.

        Args:
            preserve_world_transform: Keep the node's world-space transform
                (default), adjusting its local values; ``False`` keeps the
                local values, which may move it in world space.

        Raises:
            :class:`~dazpy.exceptions.ScriptRuntimeError`: If Studio refuses
                the detach.
        """
        from .exceptions import ScriptRuntimeError
        in_place = "true" if preserve_world_transform else "false"
        script = ScriptBuilder.node_body_from_locator(self._locator, f"""
            var _parent = _node.getNodeParent();
            if (!_parent) return null;
            var _err = _parent.removeNodeChild(_node, {in_place});
            var _errNum = _err ? _err.valueOf() : 0;
            return _errNum !== 0 ? ("DzError code " + _errNum) : null;
        """)
        result = self._client.execute(script).value
        if result:
            raise ScriptRuntimeError(f"unparent failed: {result}")

    def reparent(self, new_parent: "DazNode", *, preserve_world_transform: bool = True) -> None:
        """Move this node to a new position in the scene hierarchy.

        Detaches the node from its current parent (if any) and attaches it
        as a child of *new_parent*, following the ``removeNodeChild`` /
        ``addNodeChild`` DazScript pattern.

        Args:
            new_parent: The node to reparent under.
            preserve_world_transform: When ``True`` (default), the node keeps
                its current world-space position/rotation/scale, adjusting
                its local transform to compensate. When ``False``, the
                node's local transform values are left unchanged, which may
                move it in world space.

        Raises:
            :class:`~dazpy.exceptions.ScriptRuntimeError`: If the reparent
                operation fails (e.g. *new_parent* cannot be found, or would
                create a cycle).
        """
        from .exceptions import ScriptRuntimeError
        parent_expr = new_parent._locator
        in_place = "true" if preserve_world_transform else "false"
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            f"""
            var _newParent = {parent_expr};
            if (!_newParent) return "new parent not found";
            var _oldParent = _node.getNodeParent();
            if (_oldParent) _oldParent.removeNodeChild(_node, {in_place});
            var _err = _newParent.addNodeChild(_node, {in_place});
            var _errNum = _err ? _err.valueOf() : 0;
            return _errNum !== 0 ? ("DzError code " + _errNum) : null;
            """
        )
        result = self._client.execute(script).value
        if result:
            raise ScriptRuntimeError(f"reparent failed: {result}")

    @staticmethod
    def _modifier_class_for(class_name: str):
        from ._modifier import DazModifier
        from ._morph import DazMorph
        from ._dforce import DazDForce
        if class_name == "DzMorph":
            return DazMorph
        if class_name == "DzDForceModifier":
            return DazDForce
        return DazModifier

    def _modifier_locator(self, modifier_name: str) -> str:
        return (
            f"(function(){{"
            f" var _o = {self._locator};"
            f" _o = _o ? _o.getObject() : null;"
            f" return _o ? _o.findModifier({json.dumps(modifier_name)}) : null;"
            f"}})()"
        )

    def modifiers(self) -> list["DazModifier"]:
        """Return all modifiers (morphs, constraints, etc.) on this node.

        Returns:
            A list of :class:`~dazpy.DazMorph` and :class:`~dazpy.DazModifier`
            instances.
        """
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            """
            var obj = _node.getObject();
            if (!obj) return [];
            var mods = [];
            for (var i = 0; i < obj.getNumModifiers(); i++) {
                var m = obj.getModifier(i);
                mods.push({name: m.getName(), className: m.className()});
            }
            return mods;
            """
        )
        items = self._client.execute(script).value or []
        result = []
        for item in items:
            loc = self._modifier_locator(item["name"])
            cls = self._modifier_class_for(item["className"])
            result.append(cls(self._client, loc))
        return result

    def find_modifier(self, name: str) -> "DazModifier | None":
        """Find a modifier by internal name.

        Args:
            name: The ``getName()`` string of the modifier.

        Returns:
            A :class:`~dazpy.DazMorph` or :class:`~dazpy.DazModifier`, or
            ``None`` if not found.
        """
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            f"""
            var obj = _node.getObject();
            if (!obj) return null;
            var m = obj.findModifier({json.dumps(name)});
            return m ? {{name: m.getName(), className: m.className()}} : null;
            """
        )
        result = self._client.execute(script).value
        if result is None:
            return None
        loc = self._modifier_locator(result["name"])
        return self._modifier_class_for(result["className"])(self._client, loc)

    def _material_locator(self, material_name: str) -> str:
        return (
            f"(function(){{"
            f" var _n = {self._locator};"
            f" if (!_n) return null;"
            f" var _o = _n.getObject();"
            f" if (!_o) return null;"
            f" var _s = _o.getCurrentShape();"
            f" return _s ? _s.findMaterial({json.dumps(material_name)}) : null;"
            f"}})()"
        )

    def materials(self) -> list["DazMaterial"]:
        """Return all surface materials on this node's current shape."""
        from ._material import DazMaterial
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            """
            var obj = _node.getObject();
            if (!obj) return [];
            var shape = obj.getCurrentShape();
            if (!shape) return [];
            var names = [];
            for (var i = 0; i < shape.getNumMaterials(); i++) {
                names.push(shape.getMaterial(i).getName());
            }
            return names;
            """
        )
        names = self._client.execute(script).value or []
        return [DazMaterial(self._client, self._material_locator(n)) for n in names]

    def material_info(self) -> list["MaterialInfo"]:
        """Index, name, label and shader class of every surface zone, in one call."""
        from ._material import MaterialInfo
        script = ScriptBuilder.node_body_from_locator(self._locator, """
            var obj = _node.getObject ? _node.getObject() : null;
            var shape = obj ? obj.getCurrentShape() : null;
            if (!shape) return [];
            var out = [];
            for (var i = 0; i < shape.getNumMaterials(); i++) {
                var m = shape.getMaterial(i);
                out.push({index: i, name: m.getName(),
                          label: (typeof m.getLabel === "function") ? m.getLabel() : m.getName(),
                          shader: m.className()});
            }
            return out;
        """)
        raw = self._client.execute(script).value or []
        return [MaterialInfo(int(r["index"]), r["name"], r["label"], r["shader"]) for r in raw]

    def resolve_material(self, ref: str) -> "DazMaterial":
        """Find a surface zone by label, then by internal name.

        Raises:
            NodeNotFoundError: If this node is not in the scene.
            MaterialError: If the node has no surfaces or no zone matches;
                the message lists the available zone labels.
        """
        from ._material import DazMaterial
        from .exceptions import MaterialError, NodeNotFoundError
        script = ScriptBuilder.node_body_from_locator(self._locator, f"""
            var _want = {json.dumps(ref)};
            var obj = _node.getObject ? _node.getObject() : null;
            var shape = obj ? obj.getCurrentShape() : null;
            if (!shape) return {{status: "no_shape"}};
            var byName = null, labels = [];
            for (var i = 0; i < shape.getNumMaterials(); i++) {{
                var m = shape.getMaterial(i);
                var lbl = (typeof m.getLabel === "function") ? m.getLabel() : m.getName();
                if (lbl === _want) return {{status: "ok", name: m.getName()}};
                if (!byName && m.getName() === _want) byName = m.getName();
                labels.push(lbl);
            }}
            if (byName) return {{status: "ok", name: byName}};
            return {{status: "missing", available: labels}};
        """)
        raw = self._client.execute(script).value
        if raw is None:
            raise NodeNotFoundError(f"Node not found: {self._identifier.value!r}")
        if raw["status"] == "no_shape":
            raise MaterialError("Node has no surfaces")
        if raw["status"] == "missing":
            raise MaterialError(
                f"Material {ref!r} not found. Available: {', '.join(raw.get('available', []))}"
            )
        return DazMaterial(self._client, self._material_locator(raw["name"]))

    def apply_surface_preset(
        self,
        path: str,
        *,
        map_paths: Sequence[str] | None = None,
        allow_missing: bool = False,
    ) -> list["MaterialInfo"]:
        """Apply a material or shader preset ``.duf`` to every surface of this node.

        Selects this node alone and every one of its surfaces (preset
        application acts on the selected surfaces; with only the node
        selected ``openFile`` reports success and changes nothing), then
        opens the preset through the content manager.

        Args:
            path: Absolute path to the preset file.
            map_paths: Texture paths the preset references (absolute or
                content-relative). Checked first: if any is missing the
                preset is not opened, because Studio's Missing Files dialog
                would block the script server.
            allow_missing: Open the preset even when maps are missing.

        Returns:
            :class:`MaterialInfo` for every surface after the preset applied.

        Raises:
            NodeNotFoundError: If this node is not in the scene.
            MaterialError: If maps are missing, or Studio fails to open the preset.
        """
        from ._material import MaterialInfo
        from .exceptions import MaterialError, NodeNotFoundError
        script = ScriptBuilder.node_body_from_locator(self._locator, f"""
            var _maps = {json.dumps(list(map_paths or []))};
            var _allowMissing = {"true" if allow_missing else "false"};
            var _missing = [];
            for (var i = 0; i < _maps.length; i++) {{
                var rel = _maps[i];
                if (!rel) continue;
                var fi = new DzFileInfo(rel);
                if (fi.exists()) continue;
                var abs = App.getContentMgr().getAbsolutePath(rel, true, "");
                if (abs && new DzFileInfo(abs).exists()) continue;
                _missing.push(rel);
            }}
            if (_missing.length && !_allowMissing) return {{status: "missing_maps", missing: _missing}};
            Scene.selectAllNodes(false);
            _node.select(true);
            var _obj = _node.getObject ? _node.getObject() : null;
            var _shape = _obj ? _obj.getCurrentShape() : null;
            if (_shape) for (var s = 0; s < _shape.getNumMaterials(); s++) _shape.getMaterial(s).select(true);
            var _ok = App.getContentMgr().openFile({json.dumps(path)}, new DzFileIOSettings(), false);
            if (!_ok) return {{status: "open_failed"}};
            var out = [];
            _shape = _obj ? _obj.getCurrentShape() : null;
            if (_shape) for (var j = 0; j < _shape.getNumMaterials(); j++) {{
                var m = _shape.getMaterial(j);
                out.push({{index: j, name: m.getName(), label: m.getLabel(), shader: m.className()}});
            }}
            return {{status: "ok", materials: out}};
        """)
        raw = self._client.execute(script).value
        if raw is None:
            raise NodeNotFoundError(f"Node not found: {self._identifier.value!r}")
        if raw["status"] == "missing_maps":
            raise MaterialError(
                "Missing texture files (preset not opened, to avoid Studio's Missing "
                f"Files dialog): {', '.join(raw.get('missing', []))}"
            )
        if raw["status"] == "open_failed":
            raise MaterialError(f"Studio failed to apply the preset: {path}")
        return [MaterialInfo(int(m["index"]), m["name"], m["label"], m["shader"])
                for m in raw.get("materials", [])]

    def find_material(self, name: str) -> "DazMaterial | None":
        """Find a surface material by name.

        Args:
            name: The material's ``getName()`` string.

        Returns:
            A :class:`~dazpy.DazMaterial` proxy, or ``None`` if not found.
        """
        from ._material import DazMaterial
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            f"""
            var obj = _node.getObject();
            if (!obj) return null;
            var shape = obj.getCurrentShape();
            if (!shape) return null;
            var m = shape.findMaterial({json.dumps(name)});
            return m ? m.getName() : null;
            """
        )
        result = self._client.execute(script).value
        if result is None:
            return None
        return DazMaterial(self._client, self._material_locator(result))

    def find_modifier_by_label(self, label: str) -> "DazModifier | None":
        """Find a modifier by its user-visible label (the name shown in the DAZ UI).

        DAZ Studio morphs have both an internal name (e.g. ``"PHMSmileFull"``) and a
        display label (e.g. ``"Smile Full Face"``).  :meth:`find_modifier` matches the
        internal name; this method matches the label instead.

        Args:
            label: The ``getLabel()`` string shown in the Parameters pane.

        Returns:
            A :class:`~dazpy.DazMorph` or :class:`~dazpy.DazModifier`, or
            ``None`` if no modifier with that label exists.
        """
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            f"""
            var obj = _node.getObject();
            if (!obj) return null;
            for (var i = 0; i < obj.getNumModifiers(); i++) {{
                var m = obj.getModifier(i);
                if (m.getLabel() === {json.dumps(label)}) {{
                    return {{name: m.getName(), className: m.className()}};
                }}
            }}
            return null;
            """
        )
        result = self._client.execute(script).value
        if result is None:
            return None
        loc = self._modifier_locator(result["name"])
        return self._modifier_class_for(result["className"])(self._client, loc)

    def find_property(self, name: str) -> "DazProperty | None":
        """Find a node-level property by its internal name.

        This searches properties directly on the node (via ``DzNode::findProperty``),
        which covers pose controls, FACS dials, and other parameter channels that are
        **not** geometry modifiers and therefore invisible to :meth:`find_modifier`.

        Args:
            name: The ``getName()`` / ID string of the property (e.g.
                ``"facs_ctrl_SmileFullFace"``).

        Returns:
            A :class:`~dazpy.DazProperty` proxy, or ``None`` if not found.
        """
        from ._property import DazProperty
        locator = (
            f"(function(){{var _n={self._locator};"
            f"return _n ? _n.findProperty({json.dumps(name)}) : null;}})()"
        )
        exists = self._client.execute(
            ScriptBuilder.iife(f"return !!({locator});")
        ).value
        if not exists:
            return None
        return DazProperty._from_locator(self._client, locator)

    @property
    def element_id(self) -> int | None:
        """Studio's unique ``elementID`` for this node (``None`` if not in the scene).

        ``NodeIdentifier(str(node.element_id), kind="element_id")`` addresses
        the node unambiguously even when labels repeat.
        """
        script = ScriptBuilder.node_body_from_locator(self._locator, "return _node.elementID;")
        value = self._client.execute(script).value
        return None if value is None else int(value)

    def describe(self) -> NodeInfo:
        """Return this node's label, name, type, elementID, parent and child count.

        Raises:
            NodeNotFoundError: If this node is not in the scene.
        """
        from .exceptions import NodeNotFoundError
        script = ScriptBuilder.node_body_from_locator(
            self._locator, _NODE_INFO_JS + "return _nodeInfo(_node);"
        )
        raw = self._client.execute(script).value
        if raw is None:
            raise NodeNotFoundError(f"Node not found: {self._identifier.value!r}")
        return NodeInfo._from_raw(raw)

    def numeric_properties(self, include_modifiers: bool = False) -> dict[str, object]:
        """Every numeric property on the node, in one call: ``{label: value}``.

        Args:
            include_modifiers: Also collect the object's modifier stack (morph
                value channels and modifier properties), where most of a
                figure's dials live. A property reached twice is reported
                once; when two properties share a label, the first in search
                order (node, then modifiers) wins. (Morph value channels are
                all named ``Value``, so labels are the only usable key.)
                Default ``False`` keeps
                :meth:`DazElement.numeric_properties`' node-only behaviour.

        Returns:
            ``{label: value}``, or ``{}`` if the node is not in the scene.
        """
        if not include_modifiers:
            return super().numeric_properties()
        script = ScriptBuilder.node_body_from_locator(self._locator, _NUMERIC_CHANNELS_JS + """
            var _all = _numericChannels(_node), _out = {};
            for (var _i = 0; _i < _all.length; _i++) {
                var _p = _all[_i].prop;
                if (!_out.hasOwnProperty(_p.getLabel())) _out[_p.getLabel()] = _p.getValue();
            }
            return _out;
        """)
        return dict(self._client.execute(script).value or {})

    def set_numeric_property(
        self,
        name: str,
        value: float,
        *,
        substring_fallback: bool = False,
        unlock: bool = True,
    ) -> NumericPropertyWrite:
        """Set a numeric property found by label or name, searching modifiers too.

        Searches node-level properties, then each modifier (a morph matched
        by its own name or label resolves to its value channel) and the
        modifier's properties, matching label or name exactly
        (case-insensitive). With *substring_fallback*, a second pass accepts
        the first property whose label or name contains *name*.

        Args:
            name: Property label or internal name.
            value: Value to write.
            substring_fallback: Accept a substring match when nothing matches exactly.
            unlock: Unlock a locked property before writing (Studio ignores
                writes to locked properties).

        Returns:
            :class:`NumericPropertyWrite` with the matched label, the name
            (the morph's name when matched through a morph, since its value
            channel is always called ``Value``) and the value read back.

        Raises:
            NodeNotFoundError: If this node is not in the scene.
            PropertyNotFoundError: If no property matches.
            TypeError: If the match is not numeric.
        """
        from .exceptions import NodeNotFoundError, PropertyNotFoundError
        script = ScriptBuilder.node_body_from_locator(self._locator, _FIND_NUMERIC_JS + f"""
            var _want = {json.dumps(name.lower())};
            var _substring = {"true" if substring_fallback else "false"};
            var _unlock = {"true" if unlock else "false"};
            var _found = _findNumeric(_node, _want, _substring);
            var _hit = _found ? _found.prop : null, _owner = _found ? _found.owner : null;
            if (!_hit) return {{status: "missing"}};
            if (!_hit.inherits("DzNumericProperty")) return {{status: "not_numeric", label: _hit.getLabel()}};
            if (_unlock && typeof _hit.lock === "function" && _hit.isLocked && _hit.isLocked()) _hit.lock(false);
            _hit.setValue({float(value)!r});
            return {{status: "ok", label: _hit.getLabel(),
                     name: _owner ? _owner.getName() : _hit.getName(), value: _hit.getValue()}};
        """)
        raw = self._client.execute(script).value
        if raw is None:
            raise NodeNotFoundError(f"Node not found: {self._identifier.value!r}")
        if raw.get("status") == "missing":
            raise PropertyNotFoundError(f"Property not found: {name!r} on {self._identifier.value!r}")
        if raw.get("status") == "not_numeric":
            raise TypeError(f"Property is not numeric: {raw.get('label', name)!r}")
        return NumericPropertyWrite(label=raw["label"], name=raw["name"], value=raw["value"])

    def property_details(self, kind: str = "all") -> list[PropertyDetails]:
        """Node-level properties with type, value, range, default, group path
        and animatability, in one call.

        Args:
            kind: ``"all"``, ``"numeric"``, ``"transform"`` (translate, rotate
                and scale channels), ``"morph"`` (numeric, not a transform),
                ``"bool"`` or ``"string"``.

        Raises:
            ValueError: For any other *kind*.
        """
        if kind not in _PROPERTY_KINDS:
            raise ValueError(f"kind must be one of {', '.join(_PROPERTY_KINDS)}; got {kind!r}")
        script = ScriptBuilder.node_body_from_locator(self._locator, _PROPERTY_DETAIL_JS + f"""
            var _kind = {json.dumps(kind)}, _out = [];
            for (var i = 0; i < _node.getNumProperties(); i++) {{
                var p = _node.getProperty(i), k = _kindOf(p);
                var keep = _kind === "all" || (_kind === "morph" ? (k.numeric && !k.transform) : k[_kind]);
                if (keep) _out.push(_detail(p));
            }}
            return _out;
        """)
        return [PropertyDetails._from_raw(r) for r in self._client.execute(script).value or []]

    def property_detail(self, name: str) -> PropertyDetails:
        """Metadata for one node-level property, by label or name (case-insensitive).

        Raises:
            NodeNotFoundError: If this node is not in the scene.
            PropertyNotFoundError: If no node-level property matches.
        """
        from .exceptions import NodeNotFoundError, PropertyNotFoundError
        script = ScriptBuilder.node_body_from_locator(self._locator, _PROPERTY_DETAIL_JS + f"""
            var _want = {json.dumps(name.lower())};
            for (var i = 0; i < _node.getNumProperties(); i++) {{
                var p = _node.getProperty(i);
                if (p.getLabel().toLowerCase() === _want || p.getName().toLowerCase() === _want)
                    return {{status: "ok", detail: _detail(p)}};
            }}
            return {{status: "missing"}};
        """)
        raw = self._client.execute(script).value
        if raw is None:
            raise NodeNotFoundError(f"Node not found: {self._identifier.value!r}")
        if raw["status"] != "ok":
            raise PropertyNotFoundError(f"Property not found: {name!r}")
        return PropertyDetails._from_raw(raw["detail"])

    def find_numeric_property(self, name: str) -> "DazProperty":
        """Return the numeric property whose label or name is *name* (case-insensitive).

        Searches like :meth:`set_numeric_property` (node properties, then
        the modifier stack), exact matches only. The proxy re-finds the
        property by the same rule on every call.

        Raises:
            PropertyNotFoundError: If nothing matches, or the match is not numeric.
        """
        from ._property import DazProperty
        from .exceptions import PropertyNotFoundError
        locator = (
            "(function(){" + _FIND_NUMERIC_JS
            + f"var _node = {self._locator}; if (!_node) return null;"
            + f" var _h = _findNumeric(_node, {json.dumps(name.lower())}, false);"
            + ' return (_h && _h.prop.inherits("DzNumericProperty")) ? _h.prop : null;})()'
        )
        if not self._client.execute(ScriptBuilder.iife(f"return !!({locator});")).value:
            raise PropertyNotFoundError(
                f"Numeric property not found: {name!r} on {self._identifier.value!r}")
        return DazProperty._from_locator(self._client, locator)

    def morph_info(
        self, pattern: str | None = None, include_zero: bool = False
    ) -> list[MorphInfo]:
        """List the node's ``DzMorph`` modifiers with label, value and group path.

        Args:
            pattern: Case-insensitive substring of the morph's name or label;
                ``None`` lists every morph.
            include_zero: Include morphs whose value is exactly 0.

        Returns:
            :class:`MorphInfo` per matching morph (``[]`` if the node has no
            object or is not in the scene).
        """
        script = ScriptBuilder.node_body_from_locator(self._locator, f"""
            var _pat = {json.dumps((pattern or "").lower())};
            var _includeZero = {"true" if include_zero else "false"};
            var _obj = (typeof _node.getObject === "function") ? _node.getObject() : null;
            if (!_obj) return [];
            var _out = [];
            for (var _i = 0; _i < _obj.getNumModifiers(); _i++) {{
                var _m = _obj.getModifier(_i);
                if (!_m || _m.className() !== "DzMorph") continue;
                var _n = _m.getName(), _l = _m.getLabel();
                if (_pat && _n.toLowerCase().indexOf(_pat) === -1 &&
                        _l.toLowerCase().indexOf(_pat) === -1) continue;
                var _ch = _m.getValueChannel(), _v = _ch.getValue();
                if (!_includeZero && _v === 0) continue;
                var _path = "";
                try {{ var _g = _ch.getPropertyGroup(); if (_g) _path = _g.getPath(); }} catch (e) {{}}
                _out.push({{name: _n, label: _l, value: _v, path: _path}});
            }}
            return _out;
        """)
        raw = self._client.execute(script).value or []
        return [MorphInfo(r["name"], r["label"], r["value"], r.get("path", "")) for r in raw]

    def set_numeric_candidates(
        self, slots: Sequence[tuple[Sequence[str], float]]
    ) -> list[NumericCandidateMatch]:
        """Set numeric dials chosen from per-slot candidate names, in one call.

        Each slot is ``(candidate_names, value)``. The first candidate that
        resolves on this node is set to *value* and read back; later
        candidates in that slot are ignored. This handles dials whose names
        differ between figure generations or products, e.g. a smile that is
        ``"Smile"`` on Genesis 9 but something else on another figure.

        A name resolves, in order, as a node-level property name
        (``findProperty``: expression and pose controller dials), then a
        node-level property label, then a ``DzMorph`` modifier name or
        label (its value channel). Only numeric properties count.

        Writes use plain ``setValue()``, like
        :meth:`~dazpy.DazElement.set_property`.

        Args:
            slots: ``[(names, value), ...]``. *names* must be a sequence of
                strings, not a bare string.

        Returns:
            One :class:`NumericCandidateMatch` per slot, in order.

        Raises:
            TypeError: If a slot's names is a bare string.
            NodeNotFoundError: If this node is not in the scene.
        """
        from .exceptions import NodeNotFoundError

        normalized: list[tuple[tuple[str, ...], float]] = []
        for names, value in slots:
            if isinstance(names, str):
                raise TypeError(
                    "set_numeric_candidates: each slot's names must be a list of "
                    f"strings, got the bare string {names!r}"
                )
            normalized.append((tuple(str(n) for n in names), float(value)))
        if not normalized:
            return []
        payload = json.dumps([{"names": list(n), "value": v} for n, v in normalized])
        script = ScriptBuilder.node_body_from_locator(self._locator, f"""
            var _slots = {payload};
            var _mods = null;
            function _numeric(p) {{ return p && p.inherits("DzNumericProperty") ? p : null; }}
            function _modChannel(n) {{
                if (_mods === null) {{
                    _mods = {{byName: {{}}, byLabel: {{}}}};
                    var _obj = _node.getObject ? _node.getObject() : null;
                    if (_obj) {{
                        for (var _i = 0; _i < _obj.getNumModifiers(); _i++) {{
                            var _m = _obj.getModifier(_i);
                            if (!_m || _m.className() !== "DzMorph") continue;
                            var _ch = _m.getValueChannel();
                            if (!_mods.byName.hasOwnProperty(_m.getName())) _mods.byName[_m.getName()] = _ch;
                            if (!_mods.byLabel.hasOwnProperty(_m.getLabel())) _mods.byLabel[_m.getLabel()] = _ch;
                        }}
                    }}
                }}
                if (_mods.byName.hasOwnProperty(n)) return _numeric(_mods.byName[n]);
                if (_mods.byLabel.hasOwnProperty(n)) return _numeric(_mods.byLabel[n]);
                return null;
            }}
            var _out = [];
            for (var _s = 0; _s < _slots.length; _s++) {{
                var _slot = _slots[_s];
                var _hit = null;
                for (var _c = 0; _c < _slot.names.length && !_hit; _c++) {{
                    var _n = _slot.names[_c];
                    var _p = _numeric(_node.findProperty(_n)) || _numeric(_node.findPropertyByLabel(_n));
                    if (_p) {{ _hit = {{name: _n, source: "property", prop: _p}}; break; }}
                    _p = _modChannel(_n);
                    if (_p) {{ _hit = {{name: _n, source: "modifier", prop: _p}}; break; }}
                }}
                if (_hit) {{
                    _hit.prop.setValue(_slot.value);
                    _out.push({{matched: _hit.name, source: _hit.source, value: _hit.prop.getValue()}});
                }} else {{
                    _out.push({{matched: null, source: null, value: null}});
                }}
            }}
            return _out;
        """)
        raw = self._client.execute(script).value
        if raw is None:
            raise NodeNotFoundError(f"Node not found: {self._identifier.value!r}")
        return [
            NumericCandidateMatch(
                candidates=names,
                requested=value,
                matched=r.get("matched"),
                source=r.get("source"),
                value=r.get("value"),
            )
            for (names, value), r in zip(normalized, raw)
        ]

    def find_property_by_label(self, label: str) -> "DazProperty | None":
        """Find a node-level property by its user-visible label.

        Equivalent to :meth:`find_property` but matches on ``getLabel()`` instead
        of ``getName()``.  Use this when you know the label shown in the DAZ Studio
        Parameters pane (e.g. ``"Smile Full Face"``) but not the internal ID.

        Args:
            label: The ``getLabel()`` string shown in the Parameters pane.

        Returns:
            A :class:`~dazpy.DazProperty` proxy, or ``None`` if not found.
        """
        from ._property import DazProperty
        locator = (
            f"(function(){{var _n={self._locator};"
            f"return _n ? _n.findPropertyByLabel({json.dumps(label)}) : null;}})()"
        )
        exists = self._client.execute(
            ScriptBuilder.iife(f"return !!({locator});")
        ).value
        if not exists:
            return None
        return DazProperty._from_locator(self._client, locator)

    def morphs(self) -> list["DazMorph"]:
        """Return only the morph modifiers on this node (convenience filter)."""
        from ._morph import DazMorph
        return [m for m in self.modifiers() if isinstance(m, DazMorph)]

    def dforce_modifiers(self) -> list["DazDForce"]:
        """Return only the dForce simulation modifiers on this node (convenience filter)."""
        from ._dforce import DazDForce
        return [m for m in self.modifiers() if isinstance(m, DazDForce)]

    def set_rotation(self, x: float, y: float, z: float) -> None:
        """Set the world-space rotation using Euler angles in degrees.

        Args:
            x: Rotation around the X axis in degrees.
            y: Rotation around the Y axis in degrees.
            z: Rotation around the Z axis in degrees.
        """
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            f"_node.getXRotControl().setValue({x}); _node.getYRotControl().setValue({y}); _node.getZRotControl().setValue({z});"
        )
        self._client.execute(script)

    def set_position_at_frame(self, frame: int, x: float, y: float, z: float) -> None:
        """Write a real keyframe for world-space position at timeline *frame*.

        Unlike :meth:`set_position`, this writes an actual animation curve
        key (via ``DzNode.setWSPos(tm, pos)``) rather than the "current"
        value — the position at frames between keys is DAZ Studio's own
        interpolation, not something the caller has to bake per-frame.

        *frame* is converted to DAZ Studio time ticks via the scene's
        current ``Scene.getTimeStep()`` (ticks per frame), not a hardcoded
        constant — that value depends on the scene's frame rate.

        Args:
            frame: Timeline frame number for this keyframe.
            x: X coordinate in DAZ Studio units (centimetres by default).
            y: Y coordinate.
            z: Z coordinate.
        """
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            f"var _tm = {int(frame)} * Scene.getTimeStep(); "
            f"_node.setWSPos(_tm, new DzVec3({x}, {y}, {z}));"
        )
        self._client.execute(script)

    def set_rotation_at_frame(self, frame: int, x: float, y: float, z: float) -> None:
        """Write a real keyframe for world-space Euler rotation at timeline *frame*.

        Companion to :meth:`set_position_at_frame` — see its docstring for
        the tick-conversion note. Writes to the same per-axis rotation
        controls as :meth:`set_rotation`, but as a keyed value at *frame*
        rather than the "current" value.

        Args:
            frame: Timeline frame number for this keyframe.
            x: Rotation around the X axis in degrees.
            y: Rotation around the Y axis in degrees.
            z: Rotation around the Z axis in degrees.
        """
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            f"var _tm = {int(frame)} * Scene.getTimeStep(); "
            f"_node.getXRotControl().setDoubleValue(_tm, {x}); "
            f"_node.getYRotControl().setDoubleValue(_tm, {y}); "
            f"_node.getZRotControl().setDoubleValue(_tm, {z});"
        )
        self._client.execute(script)

    def clear_position_keys(self) -> None:
        """Remove all keyframes from this node's X/Y/Z position controls.

        Newly-created nodes can already carry a default key (e.g. a preset
        camera position at its creation time); call this before writing a
        fresh animated curve with :meth:`set_position_at_frame`, otherwise
        the leftover default key distorts interpolation/extrapolation
        around the new keys.
        """
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            "_node.getXPosControl().deleteAllKeys(); "
            "_node.getYPosControl().deleteAllKeys(); "
            "_node.getZPosControl().deleteAllKeys();"
        )
        self._client.execute(script)

    def clear_rotation_keys(self) -> None:
        """Remove all keyframes from this node's X/Y/Z rotation controls.

        See :meth:`clear_position_keys` — same rationale, for orientation.
        """
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            "_node.getXRotControl().deleteAllKeys(); "
            "_node.getYRotControl().deleteAllKeys(); "
            "_node.getZRotControl().deleteAllKeys();"
        )
        self._client.execute(script)

    def set_transform_key_interpolation(
        self,
        frames: Sequence[int],
        kinds: Sequence[Optional[str]],
        *,
        rotation: bool = True,
        fast_start: bool = False,
        fast_end: bool = False,
    ) -> None:
        """Set how Studio interpolates this node's position (and rotation) keys.

        Low-level; :class:`~dazpy.shots.Keyframed` ``easing`` and
        :class:`~dazpy.shots.CameraKeyframe` ``interpolation`` build the
        arguments for a camera move. ``kinds[k]`` sets the segment from the key
        at ``frames[k]`` to the next key in *frames*, on every X/Y/Z position
        control (and rotation control when *rotation*):

        - ``"linear"``: straight line (``DzProperty.InterpLinear``).
        - ``"constant"``: hold, then jump (``InterpConstant``).
        - ``"smooth"``: Studio's default curve (``InterpTCB``, tension,
          continuity and bias 0): Catmull-Rom tangents at interior keys, zero
          at the first and last key.
        - ``"hermite"``: ``InterpHermite`` with the same Catmull-Rom tangents
          computed per control, except at an end flagged *fast_start* /
          *fast_end*, whose tangent is the quadratic one (``2*slope - tangent
          at the other end of the segment``) clamped to between the segment's
          average slope and three times it, so the move neither stops there
          nor reverses. A two-key move with *fast_end* is exactly ``t**2``
          (ease in); with *fast_start*, ``2t - t**2`` (ease out).
        - ``None``: leave the key as it is.

        Tangents use only the keys in *frames*. Keys missing on a control are
        skipped; the last key's kind affects nothing after it.

        Args:
            frames: Frame numbers of existing keys, strictly ascending.
            kinds: One entry per frame.
            rotation: Also set the X/Y/Z rotation controls.
            fast_start: Leave the first key at speed (``"hermite"`` only).
            fast_end: Arrive at the last key at speed (``"hermite"`` only).

        Raises:
            ValueError: Lengths differ, frames are not strictly ascending, or a
                kind is unknown.
        """
        frames = [int(f) for f in frames]
        kinds = list(kinds)
        if len(frames) != len(kinds):
            raise ValueError(f"frames ({len(frames)}) and kinds ({len(kinds)}) must have the same length")
        if any(b <= a for a, b in zip(frames, frames[1:])):
            raise ValueError("frames must be strictly ascending")
        bad = [k for k in kinds if k is not None and k not in TRANSFORM_KEY_KINDS]
        if bad:
            raise ValueError(f"unknown key interpolation {bad[0]!r} (allowed: {', '.join(TRANSFORM_KEY_KINDS)})")
        axes = ("Pos", "Rot") if rotation else ("Pos",)
        controls = ", ".join(f"_node.get{a}{c}Control()" for c in axes for a in "XYZ")
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            _KEY_INTERP_JS
            + f"var _F = {json.dumps(frames)}, _K = {json.dumps(kinds)}, _C = [{controls}];\n"
            f"for (var _c = 0; _c < _C.length; _c++) "
            f"_kiApply(_C[_c], _F, _K, {ScriptBuilder.serialize_arg(bool(fast_start))}, "
            f"{ScriptBuilder.serialize_arg(bool(fast_end))});"
        )
        self._client.execute(script)

    @property
    def local_position(self) -> dict | None:
        """Local-space position as ``{"x", "y", "z"}`` (read-only)."""
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            "var p = _node.getLocalPos(); return {x: p.x, y: p.y, z: p.z};"
        )
        return self._client.execute(script).value

    def set_local_position(self, x: float, y: float, z: float) -> None:
        """Set the local-space position of this node.

        Args:
            x: X coordinate relative to the parent.
            y: Y coordinate.
            z: Z coordinate.
        """
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            f"_node.setLocalPos(new DzVec3({x}, {y}, {z}));"
        )
        self._client.execute(script)

    @property
    def local_euler(self) -> tuple[float, float, float] | None:
        """Local-space rotation as an ``(x, y, z)`` tuple of Euler angles in degrees.

        Reads the rotation controls written by :meth:`set_local_rotation`, so the
        two are exact inverses.

        Returns:
            ``(x, y, z)`` in degrees, or ``None`` if the node cannot be found.
        """
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            "return [_node.getXRotControl().getValue(), "
            "_node.getYRotControl().getValue(), "
            "_node.getZRotControl().getValue()];"
        )
        result = self._client.execute(script).value
        if result is None:
            return None
        return (result[0], result[1], result[2])

    @property
    def local_rotation(self) -> dict | None:
        """Local-space rotation as ``{"x", "y", "z", "w"}`` quaternion (read-only)."""
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            "var r = _node.getLocalRot(); return {x: r.x, y: r.y, z: r.z, w: r.w};"
        )
        return self._client.execute(script).value

    def set_local_rotation(self, x: float, y: float, z: float) -> None:
        """Set the local-space rotation using Euler angles in degrees.

        Args:
            x: Rotation around the local X axis in degrees.
            y: Rotation around the local Y axis in degrees.
            z: Rotation around the local Z axis in degrees.
        """
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            f"_node.getXRotControl().setValue({x}); _node.getYRotControl().setValue({y}); _node.getZRotControl().setValue({z});"
        )
        self._client.execute(script)

    def is_selected(self) -> bool:
        """Return ``True`` if this node is currently selected."""
        script = ScriptBuilder.node_body_from_locator(self._locator, "return _node.isSelected();")
        return bool(self._client.execute(script).value)

    def select(self, on: bool = True) -> None:
        """Select or deselect this node.

        Args:
            on: ``True`` to select, ``False`` to deselect.
        """
        flag = "true" if on else "false"
        script = ScriptBuilder.node_body_from_locator(self._locator, f"_node.select({flag});")
        self._client.execute(script)

    def is_in_scene(self) -> bool:
        """Return ``True`` if this node is still part of the active scene."""
        script = ScriptBuilder.node_body_from_locator(self._locator, "return _node.isInScene();")
        return bool(self._client.execute(script).value)

    def is_root(self) -> bool:
        """Return ``True`` if this node has no parent (top-level node)."""
        script = ScriptBuilder.node_body_from_locator(self._locator, "return _node.isRootNode();")
        return bool(self._client.execute(script).value)

    def is_visible_in_render(self) -> bool:
        """Return ``True`` if this node is visible in render output."""
        script = ScriptBuilder.node_body_from_locator(self._locator, "return _node.isVisibleInRender();")
        return bool(self._client.execute(script).value)

    def set_visible_in_render(self, on: bool) -> None:
        """Set render visibility.

        Args:
            on: ``True`` to show in render, ``False`` to hide.
        """
        flag = "true" if on else "false"
        script = ScriptBuilder.node_body_from_locator(self._locator, f"_node.setVisibleInRender({flag});")
        self._client.execute(script)

    def is_visible_in_viewport(self) -> bool:
        """Return ``True`` if this node is visible in the 3D viewport."""
        script = ScriptBuilder.node_body_from_locator(self._locator, "return _node.isVisibleInViewport();")
        return bool(self._client.execute(script).value)

    def set_visible_in_viewport(self, on: bool) -> None:
        """Set viewport visibility.

        Args:
            on: ``True`` to show, ``False`` to hide.
        """
        flag = "true" if on else "false"
        script = ScriptBuilder.node_body_from_locator(self._locator, f"_node.setVisibleInViewport({flag});")
        self._client.execute(script)

    def bounding_box(self) -> dict | None:
        """Return the world-space axis-aligned bounding box.

        Returns:
            A dict ``{"min": {"x", "y", "z"}, "max": {"x", "y", "z"}}`` or
            ``None`` if the node has no geometry.
        """
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            "var bb = _node.getWSBoundingBox(); return {min: {x: bb.min.x, y: bb.min.y, z: bb.min.z}, max: {x: bb.max.x, y: bb.max.y, z: bb.max.z}};"
        )
        return self._client.execute(script).value

    def fit_to(self, figure: "DazNode") -> str:
        """Fit this clothing/hair/prop node to a base figure.

        For figure-based conforming clothing and hair (nodes exposing
        ``setFollowTarget``/``followSkeleton``), this sets the follow
        relationship so the item deforms with the figure's pose. For plain
        props/accessories, it falls back to parenting the item under the
        figure, preserving its current world-space transform.

        Args:
            figure: The target base figure node. Must already be loaded
                into the scene.

        Returns:
            The DazScript API used: ``"setFollowTarget"``,
            ``"followSkeleton"``, or ``"addNodeChild"`` (parenting fallback).

        Raises:
            NodeNotFoundError: If this node or *figure* cannot be found.
        """
        from .exceptions import NodeNotFoundError
        figure_expr = figure._locator
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            f"""
            var _figure = {figure_expr};
            if (!_figure) return null;
            var _method;
            if (typeof _node.setFollowTarget === 'function') {{
                _node.setFollowTarget(_figure);
                _method = "setFollowTarget";
            }} else if (typeof _node.followSkeleton === 'function') {{
                _node.followSkeleton(_figure);
                _method = "followSkeleton";
            }} else {{
                _figure.addNodeChild(_node, true);
                _method = "addNodeChild";
            }}
            return _method;
            """
        )
        result = self._client.execute(script).value
        if result is None:
            raise NodeNotFoundError(
                "Could not fit node to figure: one of the nodes was not found."
            )
        return result

    def unfit(self) -> dict:
        """Remove this node's fitting relationship with its figure.

        Clears any follow-target relationship (conforming clothing/hair)
        and detaches this node from its parent skeleton (props), leaving it
        as a free-standing scene node at its current world position.

        Returns:
            A dict with keys:

            - ``"previous_figure"`` — internal name of the figure this node
              was fitted to, or ``None`` if it had no fitting relationship.
            - ``"actions"`` — list of operations performed (e.g.
              ``["cleared follow target", "detached from parent"]``), or
              ``[]`` if nothing was fitted.
        """
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            """
            var _prevFigure = null;
            var _actions = [];
            if (typeof _node.getFollowTarget === 'function') {
                var _ft = _node.getFollowTarget();
                if (_ft) {
                    _prevFigure = _ft.getName();
                    if (typeof _node.setFollowTarget === 'function') {
                        _node.setFollowTarget(null);
                        _actions.push("cleared follow target");
                    }
                }
            }
            var _parent = _node.getNodeParent();
            if (_parent && _parent.inherits && _parent.inherits("DzSkeleton")) {
                _prevFigure = _prevFigure || _parent.getName();
                _parent.removeNodeChild(_node, true);
                _actions.push("detached from parent");
            }
            return {previous_figure: _prevFigure, actions: _actions};
            """
        )
        return self._client.execute(script).value or {"previous_figure": None, "actions": []}

    def fitted_items(self) -> list["DazNode"]:
        """Return all clothing, hair, and prop nodes fitted to this figure.

        A node counts as fitted if it either follows this node (figure-based
        conforming clothing/hair) or is directly parented to it (props and
        accessories).

        Returns:
            A list of :class:`~dazpy.DazNode` proxies for each fitted item.
        """
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            """
            var _fitted = [];
            var _numNodes = Scene.getNumNodes();
            for (var i = 0; i < _numNodes; i++) {
                var _n = Scene.getNode(i);
                if (!_n || _n === _node) continue;
                var _isFitted = false;
                if (typeof _n.getFollowTarget === 'function') {
                    var _ft = _n.getFollowTarget();
                    if (_ft && _ft.elementID === _node.elementID) _isFitted = true;
                }
                if (!_isFitted && typeof _n.getNodeParent === 'function') {
                    var _p = _n.getNodeParent();
                    if (_p && _p.elementID === _node.elementID) _isFitted = true;
                }
                if (_isFitted) _fitted.push(_n.getName());
            }
            return _fitted;
            """
        )
        names = self._client.execute(script).value or []
        return [DazNode(self._client, NodeIdentifier(n)) for n in names]

    @property
    def geometry_vertex_count(self) -> int | None:
        """Total vertex count of this node's current geometry, or ``None``."""
        script = ScriptBuilder.node_body_from_locator(
            self._locator,
            """
            var obj = _node.getObject();
            if (!obj) return null;
            var shape = obj.getCurrentShape();
            if (!shape) return null;
            var geo = shape.getGeometry();
            if (!geo) return null;
            return geo.getNumVertices();
            """
        )
        return self._client.execute(script).value
