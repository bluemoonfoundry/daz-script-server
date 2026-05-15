from __future__ import annotations

import json

from ._script_builder import ScriptBuilder


class DazElement:
    """Generic proxy for any DzElement subclass. Base class for all typed proxies."""

    def __init__(self, client: "DazClient", locator: str):  # noqa: F821
        object.__setattr__(self, "_client", client)
        object.__setattr__(self, "_locator", locator)
        object.__setattr__(self, "_cache", {})

    def get_property(self, label: str) -> object:
        script = ScriptBuilder.iife(f"""
            var obj = {self._locator};
            if (!obj) return null;
            var prop = obj.findPropertyByLabel({json.dumps(label)});
            if (!prop) return null;
            return prop.getValue();
        """)
        return self._client.execute(script).value

    def set_property(self, label: str, value: object) -> None:
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
        cache = object.__getattribute__(self, "_cache")
        for field in fields:
            cache[field] = self.get_property(field)
        return {f: cache[f] for f in fields}

    def refresh(self) -> None:
        object.__getattribute__(self, "_cache").clear()
