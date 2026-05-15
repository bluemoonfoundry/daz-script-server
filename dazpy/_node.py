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
    value: str
    kind: str = "name"  # "name" or "label"


class DazNode(DazElement):
    def __init__(self, client: "DazClient", identifier: NodeIdentifier):  # noqa: F821
        locator = ScriptBuilder.find_node_expr(identifier)
        super().__init__(client, locator)
        object.__setattr__(self, "_identifier", identifier)

    @property
    def label(self) -> str | None:
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
        script = ScriptBuilder.node_body(self._identifier, "return _node.getName();")
        return self._client.execute(script).value

    @property
    def position(self) -> dict | None:
        script = ScriptBuilder.node_body(
            self._identifier,
            "var p = _node.getWSPos(); return {x: p.x, y: p.y, z: p.z};"
        )
        return self._client.execute(script).value

    def set_position(self, x: float, y: float, z: float) -> None:
        script = ScriptBuilder.node_body(
            self._identifier,
            f"_node.setWSPos(new DzVec3({x}, {y}, {z}));"
        )
        self._client.execute(script)

    @property
    def rotation(self) -> dict | None:
        script = ScriptBuilder.node_body(
            self._identifier,
            "var r = _node.getWSRot(); return {x: r.x, y: r.y, z: r.z, w: r.w};"
        )
        return self._client.execute(script).value

    @property
    def general_scale(self) -> float | None:
        script = ScriptBuilder.node_body(
            self._identifier,
            "return _node.getScaleControl().getValue();"
        )
        return self._client.execute(script).value

    @property
    def scale(self) -> dict | None:
        script = ScriptBuilder.node_body(
            self._identifier,
            "return {x: _node.getXScaleControl().getValue(), y: _node.getYScaleControl().getValue(), z: _node.getZScaleControl().getValue(), general: _node.getScaleControl().getValue()};"
        )
        return self._client.execute(script).value

    @property
    def visible(self) -> bool | None:
        script = ScriptBuilder.node_body(self._identifier, "return _node.isVisible();")
        return self._client.execute(script).value

    @visible.setter
    def visible(self, value: bool) -> None:
        flag = "true" if value else "false"
        script = ScriptBuilder.node_body(self._identifier, f"_node.setVisible({flag});")
        self._client.execute(script)

    @property
    def parent(self) -> DazNode | None:
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

    def morphs(self) -> list["DazMorph"]:
        from ._morph import DazMorph
        return [m for m in self.modifiers() if isinstance(m, DazMorph)]

    def set_rotation(self, x: float, y: float, z: float) -> None:
        script = ScriptBuilder.node_body(
            self._identifier,
            f"_node.getXRotControl().setValue({x}); _node.getYRotControl().setValue({y}); _node.getZRotControl().setValue({z});"
        )
        self._client.execute(script)

    @property
    def local_position(self) -> dict | None:
        script = ScriptBuilder.node_body(
            self._identifier,
            "var p = _node.getLocalPos(); return {x: p.x, y: p.y, z: p.z};"
        )
        return self._client.execute(script).value

    def set_local_position(self, x: float, y: float, z: float) -> None:
        script = ScriptBuilder.node_body(
            self._identifier,
            f"_node.setLocalPos(new DzVec3({x}, {y}, {z}));"
        )
        self._client.execute(script)

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
            f"_node.getXRotControl().setValue({x}); _node.getYRotControl().setValue({y}); _node.getZRotControl().setValue({z});"
        )
        self._client.execute(script)

    def is_selected(self) -> bool:
        script = ScriptBuilder.node_body(self._identifier, "return _node.isSelected();")
        return bool(self._client.execute(script).value)

    def select(self, on: bool = True) -> None:
        flag = "true" if on else "false"
        script = ScriptBuilder.node_body(self._identifier, f"_node.select({flag});")
        self._client.execute(script)

    def is_in_scene(self) -> bool:
        script = ScriptBuilder.node_body(self._identifier, "return _node.isInScene();")
        return bool(self._client.execute(script).value)

    def is_root(self) -> bool:
        script = ScriptBuilder.node_body(self._identifier, "return _node.isRootNode();")
        return bool(self._client.execute(script).value)

    def is_visible_in_render(self) -> bool:
        script = ScriptBuilder.node_body(self._identifier, "return _node.isVisibleInRender();")
        return bool(self._client.execute(script).value)

    def set_visible_in_render(self, on: bool) -> None:
        flag = "true" if on else "false"
        script = ScriptBuilder.node_body(self._identifier, f"_node.setVisibleInRender({flag});")
        self._client.execute(script)

    def is_visible_in_viewport(self) -> bool:
        script = ScriptBuilder.node_body(self._identifier, "return _node.isVisibleInViewport();")
        return bool(self._client.execute(script).value)

    def set_visible_in_viewport(self, on: bool) -> None:
        flag = "true" if on else "false"
        script = ScriptBuilder.node_body(self._identifier, f"_node.setVisibleInViewport({flag});")
        self._client.execute(script)

    def bounding_box(self) -> dict | None:
        script = ScriptBuilder.node_body(
            self._identifier,
            "var bb = _node.getWSBoundingBox(); return {min: {x: bb.min.x, y: bb.min.y, z: bb.min.z}, max: {x: bb.max.x, y: bb.max.y, z: bb.max.z}};"
        )
        return self._client.execute(script).value

    def duplicate(self) -> "DazNode | None":
        script = ScriptBuilder.node_body(
            self._identifier,
            "var dup = _node.duplicate(false); return dup ? dup.getName() : null;"
        )
        name = self._client.execute(script).value
        if name is None:
            return None
        return DazNode(self._client, NodeIdentifier(name))

    @property
    def geometry_vertex_count(self) -> int | None:
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
