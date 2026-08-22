from __future__ import annotations

import json

from ._script_builder import ScriptBuilder


class DazElement:
    """Generic proxy for any DzElement subclass. Base class for all typed proxies.

    You normally do not instantiate ``DazElement`` directly.  Use the
    typed subclasses (:class:`~dazpy.DazNode`, :class:`~dazpy.DazMaterial`,
    etc.) returned by :class:`~dazpy.DazScene` and related helpers instead.

    Args:
        client: The :class:`~dazpy.DazClient` used for all remote calls.
        locator: A JavaScript expression that evaluates to the underlying
            ``DzElement`` instance inside DAZ Studio.
    """

    def __init__(self, client: "DazClient", locator: str):  # noqa: F821
        object.__setattr__(self, "_client", client)
        object.__setattr__(self, "_locator", locator)
        object.__setattr__(self, "_cache", {})

    def get_property(self, label: str) -> object:
        """Return the current value of a property looked up by its display label.

        Args:
            label: The ``getLabel()`` string of the ``DzProperty``.

        Returns:
            The property value, or ``None`` if the property does not exist.
        """
        script = ScriptBuilder.iife(f"""
            var obj = {self._locator};
            if (!obj) return null;
            var prop = obj.findPropertyByLabel({json.dumps(label)});
            if (!prop) return null;
            return prop.getValue();
        """)
        return self._client.execute(script).value

    def set_property(self, label: str, value: object) -> None:
        """Set a property value by display label.

        Args:
            label: The ``getLabel()`` string of the ``DzProperty``.
            value: The new value.  Must be JSON-serialisable.
        """
        serialized = ScriptBuilder.serialize_arg(value)
        script = ScriptBuilder.iife(f"""
            var obj = {self._locator};
            if (!obj) return {{"error": "not_found"}};
            var prop = obj.findPropertyByLabel({json.dumps(label)});
            if (!prop) return {{"error": "property_not_found"}};
            prop.setValue({serialized});
            return {{"success": true}};
        """)
        self._client.execute(script)

    def set_properties(self, values: dict[str, object]) -> dict[str, bool]:
        """Set multiple property values by display label in one call.

        Args:
            values: ``{label: value}``. Each value must be JSON-serialisable.

        Returns:
            ``{label: True}`` for labels that resolved to a real property and
            were written, ``{label: False}`` for labels that did not resolve.
        """
        data_json = json.dumps(values)
        script = ScriptBuilder.iife(f"""
            var obj = {self._locator};
            if (!obj) return null;
            var _data = {data_json};
            var _result = {{}};
            for (var _label in _data) {{
                if (!_data.hasOwnProperty(_label)) continue;
                var prop = obj.findPropertyByLabel(_label);
                if (prop) {{
                    prop.setValue(_data[_label]);
                    _result[_label] = true;
                }} else {{
                    _result[_label] = false;
                }}
            }}
            return _result;
        """)
        return self._client.execute(script).value or {}

    def list_properties(self) -> list[dict]:
        """Return metadata for every property on this element.

        Returns:
            A list of dicts, each with keys ``"label"``, ``"name"``, and
            ``"type"`` (the DazScript class name of the property).
        """
        script = ScriptBuilder.iife(f"""
            var obj = {self._locator};
            if (!obj) return null;
            var result = [];
            for (var i = 0; i < obj.getNumProperties(); i++) {{
                var p = obj.getProperty(i);
                result.push({{"label": p.getLabel(), "name": p.getName(), "type": p.className()}});
            }}
            return result;
        """)
        return self._client.execute(script).value or []

    def numeric_properties(self) -> dict[str, object]:
        """Return every numeric property on this element as ``{label: value}``.

        Unlike :meth:`list_properties`, this fetches labels and current
        values for all numeric (float/int/bool) properties in a single HTTP
        round-trip — use it instead of calling :meth:`get_property` in a
        loop over ``list_properties()`` results.

        Returns:
            A dict mapping each numeric property's display label to its
            current value.
        """
        script = ScriptBuilder.iife(f"""
            var obj = {self._locator};
            if (!obj) return null;
            var result = {{}};
            for (var i = 0; i < obj.getNumProperties(); i++) {{
                var p = obj.getProperty(i);
                if (p.inherits("DzNumericProperty")) {{
                    result[p.getLabel()] = p.getValue();
                }}
            }}
            return result;
        """)
        return self._client.execute(script).value or {}

    @property
    def class_name(self) -> str | None:
        """The DazScript class name of this element (e.g. ``"DzFigure"``, ``"DzSpotLight"``)."""
        script = ScriptBuilder.iife(
            f"var obj = {self._locator}; return obj ? obj.className() : null;"
        )
        return self._client.execute(script).value

    def snapshot(self, fields: list[str]) -> dict:
        """Read and cache a set of property values in a single call.

        Args:
            fields: Property labels to read.

        Returns:
            A dict mapping each label to its current value. Missing owner or
            missing property both resolve to ``None`` for the affected label(s).
        """
        cache = object.__getattribute__(self, "_cache")
        fields_json = json.dumps(fields)
        script = ScriptBuilder.iife(f"""
            var obj = {self._locator};
            if (!obj) return null;
            var _fields = {fields_json};
            var _result = {{}};
            for (var i = 0; i < _fields.length; i++) {{
                var prop = obj.findPropertyByLabel(_fields[i]);
                _result[_fields[i]] = prop ? prop.getValue() : null;
            }}
            return _result;
        """)
        values = self._client.execute(script).value or {}
        for field in fields:
            cache[field] = values.get(field)
        return {f: cache[f] for f in fields}

    def refresh(self) -> None:
        """Clear the local property cache so the next read fetches live data."""
        object.__getattribute__(self, "_cache").clear()
