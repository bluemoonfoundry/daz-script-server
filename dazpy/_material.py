from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ._element import DazElement
from ._script_builder import ScriptBuilder

if TYPE_CHECKING:
    from ._client import DazClient


@dataclass(frozen=True)
class MaterialInfo:
    """One surface zone: its index on the shape (``None`` when unknown, as
    from :meth:`DazMaterial.describe`), name, label and shader class."""

    index: int | None
    name: str
    label: str
    shader: str


@dataclass(frozen=True)
class MaterialProperty:
    """One property on a material, from :meth:`DazMaterial.property_values`.

    Attributes:
        type: ``"numeric"``, ``"color"`` (value ``"#rrggbb"``), ``"image"``
            (value the map's file path, or ``None``) or ``"unknown"`` (value
            ``None``).
    """

    name: str
    label: str
    type: str
    value: Any


@dataclass(frozen=True)
class MaterialPropertyWrite:
    """Result of :meth:`DazMaterial.set_property_value`, with the value read back."""

    label: str
    type: str
    value: Any


_HEX_COLOR = re.compile(r"^#?[0-9a-fA-F]{6}$")

# JS helpers: read a color property as "#rrggbb" across DS4/DS6 color APIs,
# and describe a material.
_MATERIAL_JS = """
    function _toHex(n) {
        var v = Math.round(n); if (v < 0) v = 0; if (v > 255) v = 255;
        return ("0" + v.toString(16)).slice(-2);
    }
    function _chan(col, name) { var v = col[name]; return typeof v === "function" ? v.call(col) : v; }
    function _colorHex(col) {
        if (!col) return null;
        var r = _chan(col, "red"), g = _chan(col, "green"), b = _chan(col, "blue");
        if (r <= 1 && g <= 1 && b <= 1) { r *= 255; g *= 255; b *= 255; }
        return "#" + _toHex(r) + _toHex(g) + _toHex(b);
    }
    function _readColor(prop) {
        try {
            if (typeof prop.getFloatColorValue === "function") {
                var fc = prop.getFloatColorValue();
                if (fc && typeof fc.getColor === "function") { var qc = fc.getColor(); if (qc) return _colorHex(qc); }
                if (fc) return _colorHex(fc);
            }
        } catch (e1) {}
        try { if (typeof prop.getColorValue === "function") return _colorHex(prop.getColorValue()); } catch (e2) {}
        return null;
    }
    function _isColor(prop) { return prop.inherits("DzColorProperty") || prop.inherits("DzFloatColorProperty"); }
"""


class DazMaterial(DazElement):
    """Proxy for a ``DzMaterial`` surface on a DAZ Studio node.

    Instances are obtained via :meth:`DazNode.materials` or
    :meth:`DazNode.find_material`.
    """

    def __init__(self, client: DazClient, locator: str):
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
            f"var m = {self._locator}; if (m) m.setBaseOpacity({ScriptBuilder.js_num(value)});"
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
            f"var m = {self._locator}; if (m) m.setSmoothingAngle({ScriptBuilder.js_num(value)});"
        )
        self._client.execute(script)

    def is_opaque(self) -> bool | None:
        """Return ``True`` if the material is fully opaque (opacity == 1.0)."""
        script = ScriptBuilder.iife(
            f"var m = {self._locator}; return m ? m.isOpaque() : null;"
        )
        return self._client.execute(script).value

    # ── whole-material helpers (one call each) ───────────────────────────────

    def describe(self) -> MaterialInfo:
        """Return this material's index, name, label and shader class.

        Raises:
            MaterialError: If the material is not found.
        """
        from .exceptions import MaterialError
        script = ScriptBuilder.iife(f"""
            var m = {self._locator};
            if (!m) return null;
            var idx = -1, s = m.getShape ? m.getShape() : null;
            if (s) for (var i = 0; i < s.getNumMaterials(); i++) if (s.getMaterial(i) === m) {{ idx = i; break; }}
            var lbl = (typeof m.getLabel === "function") ? m.getLabel() : m.getName();
            return {{index: idx, name: m.getName(), label: lbl, shader: m.className()}};
        """)
        raw = self._client.execute(script).value
        if raw is None:
            raise MaterialError("Material not found")
        index = int(raw["index"])
        return MaterialInfo(index if index >= 0 else None, raw["name"], raw["label"], raw["shader"])

    def property_values(self) -> list[MaterialProperty]:
        """Every property on the material with its type and value, in one call.

        Colors come back as ``"#rrggbb"``; image properties as the map's file
        path (``None`` when no map is set).
        """
        script = ScriptBuilder.iife(_MATERIAL_JS + f"""
            var m = {self._locator};
            if (!m) return null;
            var out = [];
            for (var i = 0; i < m.getNumProperties(); i++) {{
                var p = m.getProperty(i);
                var e = {{name: p.getName(), label: p.getLabel(), type: "unknown", value: null}};
                if (_isColor(p)) {{ e.type = "color"; e.value = _readColor(p); }}
                else if (p.inherits("DzNumericProperty")) {{ e.type = "numeric"; e.value = p.getValue(); }}
                else if (p.inherits("DzImageProperty")) {{
                    e.type = "image";
                    try {{ var img = p.getValue(); e.value = img ? img.getFilename() : null; }} catch (x) {{ e.value = null; }}
                }}
                out.push(e);
            }}
            return out;
        """)
        raw = self._client.execute(script).value or []
        return [MaterialProperty(r["name"], r["label"], r["type"], r["value"]) for r in raw]

    def set_property_value(self, name: str, value: Any) -> MaterialPropertyWrite:
        """Set a numeric or color property found by internal name, then label.

        Args:
            name: Property name or label (``"Diffuse Color"``, ``"Base Color"``).
            value: A number for numeric properties; ``"#RRGGBB"`` for colors.

        Returns:
            :class:`MaterialPropertyWrite` with the label, type and value read back.

        Raises:
            ValueError: If a color value is not ``#RRGGBB`` (checked before
                the call when *value* is a string).
            MaterialError: If the material or property is missing, or the
                property is neither numeric nor color.
        """
        from .exceptions import MaterialError
        rgb = "null"
        if isinstance(value, str):
            if not _HEX_COLOR.match(value.strip()):
                try:
                    float(value)
                except ValueError:
                    raise ValueError(f"Color values must be '#RRGGBB', got {value!r}") from None
            else:
                h = value.strip().lstrip("#")
                rgb = ScriptBuilder.to_js([int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)])
        num = "null"
        if not isinstance(value, str) or rgb == "null":
            try:
                num = repr(float(value))
            except (TypeError, ValueError):
                raise ValueError(f"Numeric value expected, got {value!r}") from None
        script = ScriptBuilder.iife(_MATERIAL_JS + f"""
            var m = {self._locator};
            if (!m) return {{status: "no_material"}};
            var want = {ScriptBuilder.to_js(name)};
            var p = m.findProperty(want) || m.findPropertyByLabel(want);
            if (!p) return {{status: "missing"}};
            var rgb = {rgb}, num = {num};
            if (_isColor(p)) {{
                if (!rgb) return {{status: "needs_color", label: p.getLabel()}};
                p.setColorValue(new QColor(rgb[0], rgb[1], rgb[2]));
                return {{status: "ok", label: p.getLabel(), type: "color", value: _readColor(p)}};
            }}
            if (p.inherits("DzNumericProperty")) {{
                if (num === null) return {{status: "needs_number", label: p.getLabel()}};
                p.setValue(num);
                return {{status: "ok", label: p.getLabel(), type: "numeric", value: p.getValue()}};
            }}
            return {{status: "unsupported", label: p.getLabel()}};
        """)
        raw = self._client.execute(script).value or {"status": "no_material"}
        status = str(raw.get("status"))
        if status == "ok":
            return MaterialPropertyWrite(raw["label"], raw["type"], raw["value"])
        messages = {
            "no_material": "Material not found",
            "missing": f"Property not found: {name}",
            "needs_color": f"Property {raw.get('label')!r} is a color; pass '#RRGGBB'",
            "needs_number": f"Property {raw.get('label')!r} is numeric; pass a number",
            "unsupported": f"Property {raw.get('label')!r} is not a settable color or numeric property",
        }
        raise MaterialError(messages.get(status, f"Failed to set {name!r}"))

    def copy_from(self, source: DazMaterial) -> tuple[int, int]:
        """Copy every property value from *source* onto matching properties here.

        Properties are matched by internal name. Returns ``(copied, skipped)``,
        where skipped counts source properties with no match here or whose
        value Studio refused.

        Raises:
            MaterialError: If either material is not found.
        """
        from .exceptions import MaterialError
        script = ScriptBuilder.iife(f"""
            var _src = {source._locator};
            var _dst = {self._locator};
            if (!_src || !_dst) return null;
            var copied = 0, skipped = 0;
            for (var i = 0; i < _src.getNumProperties(); i++) {{
                var sp = _src.getProperty(i);
                if (!sp) continue;
                var dp = _dst.findProperty(sp.getName());
                if (!dp || typeof sp.getValue !== "function" || typeof dp.setValue !== "function") {{ skipped++; continue; }}
                try {{ dp.setValue(sp.getValue()); copied++; }} catch (e) {{ skipped++; }}
            }}
            return {{copied: copied, skipped: skipped}};
        """)
        raw = self._client.execute(script).value
        if raw is None:
            raise MaterialError("Source or destination material not found")
        return int(raw["copied"]), int(raw["skipped"])
