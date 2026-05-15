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

    def snapshot(self, fields: list[str]) -> dict:
        """Read and cache a set of property values in a single call.

        Args:
            fields: Property labels to read.

        Returns:
            A dict mapping each label to its current value.
        """
        cache = object.__getattribute__(self, "_cache")
        for field in fields:
            cache[field] = self.get_property(field)
        return {f: cache[f] for f in fields}

    def refresh(self) -> None:
        """Clear the local property cache so the next read fetches live data."""
        object.__getattribute__(self, "_cache").clear()
