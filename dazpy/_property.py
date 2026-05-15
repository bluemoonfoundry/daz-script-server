from __future__ import annotations

import json

from ._element import DazElement
from ._script_builder import ScriptBuilder


class DazProperty(DazElement):
    """Proxy for a DzProperty on any DzElement."""

    def __init__(self, client: "DazClient", owner_locator: str, property_label: str):  # noqa: F821
        locator = (
            f"(function(){{"
            f"var obj = {owner_locator};"
            f"return obj ? obj.findPropertyByLabel({json.dumps(property_label)}) : null;"
            f"}})()"
        )
        super().__init__(client, locator)
        object.__setattr__(self, "_owner_locator", owner_locator)
        object.__setattr__(self, "_property_label", property_label)

    @property
    def value(self) -> object:
        script = ScriptBuilder.iife(
            f"var p = {self._locator}; return p ? p.getValue() : null;"
        )
        return self._client.execute(script).value

    @value.setter
    def value(self, v: object) -> None:
        serialized = ScriptBuilder.serialize_arg(v)
        script = ScriptBuilder.iife(
            f"var p = {self._locator}; if (p) p.setValue({serialized});"
        )
        self._client.execute(script)

    @property
    def label(self) -> str | None:
        script = ScriptBuilder.iife(
            f"var p = {self._locator}; return p ? p.getLabel() : null;"
        )
        return self._client.execute(script).value

    @property
    def min(self) -> float | None:
        script = ScriptBuilder.iife(
            f"var p = {self._locator}; return (p && p.getMin) ? p.getMin() : null;"
        )
        return self._client.execute(script).value

    @property
    def max(self) -> float | None:
        script = ScriptBuilder.iife(
            f"var p = {self._locator}; return (p && p.getMax) ? p.getMax() : null;"
        )
        return self._client.execute(script).value

    def set_key(self, time: float, value: object) -> None:
        serialized = ScriptBuilder.serialize_arg(value)
        script = ScriptBuilder.iife(f"""
            var p = {self._locator};
            if (p && p.setKey) p.setKey({time}, {serialized});
        """)
        self._client.execute(script)

    @property
    def is_animated(self) -> bool | None:
        script = ScriptBuilder.iife(
            f"var p = {self._locator}; return p ? p.isAnimated() : null;"
        )
        return self._client.execute(script).value
