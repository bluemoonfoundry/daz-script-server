from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ._element import DazElement
from ._script_builder import ScriptBuilder

if TYPE_CHECKING:
    from ._material import DazMaterial
    from ._modifier import DazModifier
    from ._morph import DazMorph


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

    def __init__(self, client: "DazClient", identifier: NodeIdentifier):  # noqa: F821
        locator = ScriptBuilder.find_node_expr(identifier)
        super().__init__(client, locator)
        object.__setattr__(self, "_identifier", identifier)

    @property
    def label(self) -> str | None:
        """User-visible display label shown in the Scene panel (read/write)."""
        script = ScriptBuilder.node_body(self._identifier, "return _node.getLabel();")
        return self._client.execute(script).value

    @label.setter
    def label(self, value: str) -> None:
        script = ScriptBuilder.node_body(
            self._identifier,
            f"_node.setLabel({json.dumps(value)});"
        )
        self._client.execute(script)

    @property
    def name(self) -> str | None:
        """Internal node name used to look up the node (read-only)."""
        script = ScriptBuilder.node_body(self._identifier, "return _node.getName();")
        return self._client.execute(script).value

    @property
    def position(self) -> dict | None:
        """World-space position as ``{"x": float, "y": float, "z": float}`` (read-only).

        Use :meth:`set_position` to change.
        """
        script = ScriptBuilder.node_body(
            self._identifier,
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
        script = ScriptBuilder.node_body(
            self._identifier,
            f"_node.setWSPos(new DzVec3({x}, {y}, {z}));"
        )
        self._client.execute(script)

    @property
    def rotation(self) -> dict | None:
        """World-space rotation as ``{"x", "y", "z", "w"}`` quaternion (read-only).

        Use :meth:`set_rotation` to change (accepts Euler angles in degrees).
        """
        script = ScriptBuilder.node_body(
            self._identifier,
            "var r = _node.getWSRot(); return {x: r.x, y: r.y, z: r.z, w: r.w};"
        )
        return self._client.execute(script).value

    @property
    def general_scale(self) -> float | None:
        """Uniform scale factor (read-only)."""
        script = ScriptBuilder.node_body(
            self._identifier,
            "return _node.getScaleControl().getValue();"
        )
        return self._client.execute(script).value

    @property
    def scale(self) -> dict | None:
        """Per-axis and uniform scale as ``{"x", "y", "z", "general"}`` (read-only)."""
        script = ScriptBuilder.node_body(
            self._identifier,
            "return {x: _node.getXScaleControl().getValue(), y: _node.getYScaleControl().getValue(), z: _node.getZScaleControl().getValue(), general: _node.getScaleControl().getValue()};"
        )
        return self._client.execute(script).value

    @property
    def visible(self) -> bool | None:
        """General visibility flag (read/write).

        Affects both viewport and render visibility unless overridden by the
        per-channel visibility setters.
        """
        script = ScriptBuilder.node_body(self._identifier, "return _node.isVisible();")
        return self._client.execute(script).value

    @visible.setter
    def visible(self, value: bool) -> None:
        flag = "true" if value else "false"
        script = ScriptBuilder.node_body(self._identifier, f"_node.setVisible({flag});")
        self._client.execute(script)

    @property
    def parent(self) -> DazNode | None:
        """Parent node in the scene hierarchy, or ``None`` for root nodes."""
        script = ScriptBuilder.node_body(
            self._identifier,
            "var p = _node.getNodeParent(); return p ? p.getName() : null;"
        )
        name = self._client.execute(script).value
        if name is None:
            return None
        return DazNode(self._client, NodeIdentifier(name))

    @property
    def children(self) -> list[DazNode]:
        """Direct child nodes."""
        script = ScriptBuilder.node_body(
            self._identifier,
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
        from ._modifier import DazModifier
        from ._morph import DazMorph
        script = ScriptBuilder.node_body(
            self._identifier,
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
            if item["className"] == "DzMorph":
                result.append(DazMorph(self._client, loc))
            else:
                result.append(DazModifier(self._client, loc))
        return result

    def find_modifier(self, name: str) -> "DazModifier | None":
        """Find a modifier by internal name.

        Args:
            name: The ``getName()`` string of the modifier.

        Returns:
            A :class:`~dazpy.DazMorph` or :class:`~dazpy.DazModifier`, or
            ``None`` if not found.
        """
        from ._modifier import DazModifier
        from ._morph import DazMorph
        script = ScriptBuilder.node_body(
            self._identifier,
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
        if result["className"] == "DzMorph":
            return DazMorph(self._client, loc)
        return DazModifier(self._client, loc)

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
        script = ScriptBuilder.node_body(
            self._identifier,
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

    def find_material(self, name: str) -> "DazMaterial | None":
        """Find a surface material by name.

        Args:
            name: The material's ``getName()`` string.

        Returns:
            A :class:`~dazpy.DazMaterial` proxy, or ``None`` if not found.
        """
        from ._material import DazMaterial
        script = ScriptBuilder.node_body(
            self._identifier,
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
        from ._modifier import DazModifier
        from ._morph import DazMorph
        script = ScriptBuilder.node_body(
            self._identifier,
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
        if result["className"] == "DzMorph":
            return DazMorph(self._client, loc)
        return DazModifier(self._client, loc)

    def find_property(self, name: str) -> "DazProperty | None":  # noqa: F821
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

    def find_property_by_label(self, label: str) -> "DazProperty | None":  # noqa: F821
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

    def set_rotation(self, x: float, y: float, z: float) -> None:
        """Set the world-space rotation using Euler angles in degrees.

        Args:
            x: Rotation around the X axis in degrees.
            y: Rotation around the Y axis in degrees.
            z: Rotation around the Z axis in degrees.
        """
        script = ScriptBuilder.node_body(
            self._identifier,
            f"_node.getXRotControl().setValue({x}); _node.getYRotControl().setValue({y}); _node.getZRotControl().setValue({z});"
        )
        self._client.execute(script)

    @property
    def local_position(self) -> dict | None:
        """Local-space position as ``{"x", "y", "z"}`` (read-only)."""
        script = ScriptBuilder.node_body(
            self._identifier,
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
        script = ScriptBuilder.node_body(
            self._identifier,
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
        script = ScriptBuilder.node_body(
            self._identifier,
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
        script = ScriptBuilder.node_body(
            self._identifier,
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
        script = ScriptBuilder.node_body(
            self._identifier,
            f"_node.getXRotControl().setValue({x}); _node.getYRotControl().setValue({y}); _node.getZRotControl().setValue({z});"
        )
        self._client.execute(script)

    def is_selected(self) -> bool:
        """Return ``True`` if this node is currently selected."""
        script = ScriptBuilder.node_body(self._identifier, "return _node.isSelected();")
        return bool(self._client.execute(script).value)

    def select(self, on: bool = True) -> None:
        """Select or deselect this node.

        Args:
            on: ``True`` to select, ``False`` to deselect.
        """
        flag = "true" if on else "false"
        script = ScriptBuilder.node_body(self._identifier, f"_node.select({flag});")
        self._client.execute(script)

    def is_in_scene(self) -> bool:
        """Return ``True`` if this node is still part of the active scene."""
        script = ScriptBuilder.node_body(self._identifier, "return _node.isInScene();")
        return bool(self._client.execute(script).value)

    def is_root(self) -> bool:
        """Return ``True`` if this node has no parent (top-level node)."""
        script = ScriptBuilder.node_body(self._identifier, "return _node.isRootNode();")
        return bool(self._client.execute(script).value)

    def is_visible_in_render(self) -> bool:
        """Return ``True`` if this node is visible in render output."""
        script = ScriptBuilder.node_body(self._identifier, "return _node.isVisibleInRender();")
        return bool(self._client.execute(script).value)

    def set_visible_in_render(self, on: bool) -> None:
        """Set render visibility.

        Args:
            on: ``True`` to show in render, ``False`` to hide.
        """
        flag = "true" if on else "false"
        script = ScriptBuilder.node_body(self._identifier, f"_node.setVisibleInRender({flag});")
        self._client.execute(script)

    def is_visible_in_viewport(self) -> bool:
        """Return ``True`` if this node is visible in the 3D viewport."""
        script = ScriptBuilder.node_body(self._identifier, "return _node.isVisibleInViewport();")
        return bool(self._client.execute(script).value)

    def set_visible_in_viewport(self, on: bool) -> None:
        """Set viewport visibility.

        Args:
            on: ``True`` to show, ``False`` to hide.
        """
        flag = "true" if on else "false"
        script = ScriptBuilder.node_body(self._identifier, f"_node.setVisibleInViewport({flag});")
        self._client.execute(script)

    def bounding_box(self) -> dict | None:
        """Return the world-space axis-aligned bounding box.

        Returns:
            A dict ``{"min": {"x", "y", "z"}, "max": {"x", "y", "z"}}`` or
            ``None`` if the node has no geometry.
        """
        script = ScriptBuilder.node_body(
            self._identifier,
            "var bb = _node.getWSBoundingBox(); return {min: {x: bb.min.x, y: bb.min.y, z: bb.min.z}, max: {x: bb.max.x, y: bb.max.y, z: bb.max.z}};"
        )
        return self._client.execute(script).value

    @property
    def geometry_vertex_count(self) -> int | None:
        """Total vertex count of this node's current geometry, or ``None``."""
        script = ScriptBuilder.node_body(
            self._identifier,
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
