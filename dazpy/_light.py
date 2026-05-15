from __future__ import annotations

from ._node import DazNode
from ._script_builder import ScriptBuilder


class DazLight(DazNode):
    @property
    def intensity(self) -> float | None:
        return self.get_property("Intensity")

    @intensity.setter
    def intensity(self, value: float) -> None:
        self.set_property("Intensity", float(value))

    @property
    def color(self) -> dict | None:
        script = ScriptBuilder.node_body(
            self._identifier,
            """
            var c = _node.getDiffuseColor();
            return {r: c.red, g: c.green, b: c.blue};
            """
        )
        return self._client.execute(script).value

    def set_color(self, r: float, g: float, b: float) -> None:
        script = ScriptBuilder.node_body(
            self._identifier,
            f"var p = _node.findPropertyByLabel('Diffuse Color');"
            f"if (p) p.setValue(new Color({int(r)}, {int(g)}, {int(b)}));"
        )
        self._client.execute(script)

    @property
    def shadow_type(self) -> str | None:
        return self.get_property("Shadow Type")

    @property
    def illumination(self) -> str | None:
        return self.get_property("Illumination")

    def is_on(self) -> bool:
        script = ScriptBuilder.node_body(self._identifier, "return _node.isOn();")
        return bool(self._client.execute(script).value)

    def is_directional(self) -> bool:
        script = ScriptBuilder.node_body(self._identifier, "return _node.isDirectional();")
        return bool(self._client.execute(script).value)

    def is_area_light(self) -> bool:
        script = ScriptBuilder.node_body(self._identifier, "return _node.isAreaLight();")
        return bool(self._client.execute(script).value)

    def direction(self) -> dict | None:
        script = ScriptBuilder.node_body(
            self._identifier,
            "if (!_node.isDirectional()) return null;"
            "var d = _node.getWSDirection(); return {x: d.x, y: d.y, z: d.z};"
        )
        return self._client.execute(script).value
