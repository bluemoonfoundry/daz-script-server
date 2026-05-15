from __future__ import annotations

from ._node import DazNode
from ._script_builder import ScriptBuilder


class DazLight(DazNode):
    """Proxy for a ``DzLight`` node.

    Extends :class:`~dazpy.DazNode` with light-specific properties.
    """

    @property
    def intensity(self) -> float | None:
        """Light intensity / brightness (read/write)."""
        return self.get_property("Intensity")

    @intensity.setter
    def intensity(self, value: float) -> None:
        self.set_property("Intensity", float(value))

    @property
    def color(self) -> dict | None:
        """Diffuse colour as ``{"r", "g", "b"}`` (0–255 range, read-only).

        Use :meth:`set_color` to change.
        """
        script = ScriptBuilder.node_body(
            self._identifier,
            """
            var c = _node.getDiffuseColor();
            return {r: c.red, g: c.green, b: c.blue};
            """
        )
        return self._client.execute(script).value

    def set_color(self, r: float, g: float, b: float) -> None:
        """Set the diffuse colour.

        Args:
            r: Red component (0–255).
            g: Green component (0–255).
            b: Blue component (0–255).
        """
        script = ScriptBuilder.node_body(
            self._identifier,
            f"var p = _node.findPropertyByLabel('Diffuse Color');"
            f"if (p) p.setValue(new Color({int(r)}, {int(g)}, {int(b)}));"
        )
        self._client.execute(script)

    @property
    def shadow_type(self) -> str | None:
        """Shadow rendering mode string (read-only)."""
        return self.get_property("Shadow Type")

    @property
    def illumination(self) -> str | None:
        """Illumination type string (read-only)."""
        return self.get_property("Illumination")

    def is_on(self) -> bool:
        """Return ``True`` if this light is currently active."""
        script = ScriptBuilder.node_body(self._identifier, "return _node.isOn();")
        return bool(self._client.execute(script).value)

    def is_directional(self) -> bool:
        """Return ``True`` if this is a directional (infinite) light."""
        script = ScriptBuilder.node_body(self._identifier, "return _node.isDirectional();")
        return bool(self._client.execute(script).value)

    def is_area_light(self) -> bool:
        """Return ``True`` if this is an area (surface) light."""
        script = ScriptBuilder.node_body(self._identifier, "return _node.isAreaLight();")
        return bool(self._client.execute(script).value)

    def direction(self) -> dict | None:
        """Return the world-space direction vector ``{"x", "y", "z"}``.

        Returns ``None`` when the light is not directional.
        """
        script = ScriptBuilder.node_body(
            self._identifier,
            "if (!_node.isDirectional()) return null;"
            "var d = _node.getWSDirection(); return {x: d.x, y: d.y, z: d.z};"
        )
        return self._client.execute(script).value
