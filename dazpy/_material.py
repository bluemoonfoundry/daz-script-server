from __future__ import annotations

from ._element import DazElement
from ._script_builder import ScriptBuilder


class DazMaterial(DazElement):
    """Proxy for a ``DzMaterial`` surface on a DAZ Studio node.

    Instances are obtained via :meth:`DazNode.materials` or
    :meth:`DazNode.find_material`.
    """

    def __init__(self, client: "DazClient", locator: str):  # noqa: F821
        super().__init__(client, locator)

    @property
    def material_name(self) -> str | None:
        """Internal material name (read-only)."""
        script = ScriptBuilder.iife(
            f"var m = {self._locator}; return m ? m.getName() : null;"
        )
        return self._client.execute(script).value

    @property
    def diffuse_color(self) -> dict | None:
        """Diffuse colour as ``{"r", "g", "b"}`` (0–255, read/write).

        Can be set with a ``dict`` or a 3-tuple ``(r, g, b)``.
        """
        script = ScriptBuilder.iife(f"""
            var m = {self._locator};
            if (!m) return null;
            var c = m.getDiffuseColor();
            return {{r: c.red, g: c.green, b: c.blue}};
        """)
        return self._client.execute(script).value

    @diffuse_color.setter
    def diffuse_color(self, value: tuple | dict) -> None:
        if isinstance(value, dict):
            r, g, b = int(value["r"]), int(value["g"]), int(value["b"])
        else:
            r, g, b = int(value[0]), int(value[1]), int(value[2])
        script = ScriptBuilder.iife(f"""
            var m = {self._locator};
            if (!m) return;
            var c = new Color({r}, {g}, {b});
            m.setDiffuseColor(c);
        """)
        self._client.execute(script)

    @property
    def opacity(self) -> float | None:
        """Base opacity / transparency value (0.0 transparent – 1.0 opaque, read/write)."""
        script = ScriptBuilder.iife(
            f"var m = {self._locator}; return m ? m.getBaseOpacity() : null;"
        )
        return self._client.execute(script).value

    @opacity.setter
    def opacity(self, value: float) -> None:
        script = ScriptBuilder.iife(
            f"var m = {self._locator}; if (m) m.setBaseOpacity({float(value)});"
        )
        self._client.execute(script)

    def color_map(self) -> str | None:
        """Return the file path of the diffuse colour texture, or ``None``."""
        script = ScriptBuilder.iife(f"""
            var m = {self._locator};
            if (!m) return null;
            var t = m.getColorMap();
            return t ? t.getFilename() : null;
        """)
        return self._client.execute(script).value

    def is_smoothing_on(self) -> bool | None:
        """Return ``True`` if normal smoothing is enabled for this material."""
        script = ScriptBuilder.iife(
            f"var m = {self._locator}; return m ? m.isSmoothingOn() : null;"
        )
        return self._client.execute(script).value

    @property
    def smoothing_angle(self) -> float | None:
        """Normal smoothing angle in degrees (read/write)."""
        script = ScriptBuilder.iife(
            f"var m = {self._locator}; return m ? m.getSmoothingAngle() : null;"
        )
        return self._client.execute(script).value

    @smoothing_angle.setter
    def smoothing_angle(self, value: float) -> None:
        script = ScriptBuilder.iife(
            f"var m = {self._locator}; if (m) m.setSmoothingAngle({float(value)});"
        )
        self._client.execute(script)

    def is_opaque(self) -> bool | None:
        """Return ``True`` if the material is fully opaque (opacity == 1.0)."""
        script = ScriptBuilder.iife(
            f"var m = {self._locator}; return m ? m.isOpaque() : null;"
        )
        return self._client.execute(script).value
