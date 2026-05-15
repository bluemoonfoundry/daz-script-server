from __future__ import annotations

import json

from ._element import DazElement
from ._script_builder import ScriptBuilder


class DazProperty(DazElement):
    """Proxy for a ``DzProperty`` on any ``DzElement``.

    Provides typed read/write access to a single named property, including
    keyframe support for animated properties.

    Args:
        client: The :class:`~dazpy.DazClient` for remote calls.
        owner_locator: JavaScript expression that evaluates to the owning
            ``DzElement``.
        property_label: The ``getLabel()`` string of the property.
    """

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
        """Current property value (read/write)."""
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
        """The display label of this property (read-only)."""
        script = ScriptBuilder.iife(
            f"var p = {self._locator}; return p ? p.getLabel() : null;"
        )
        return self._client.execute(script).value

    @property
    def min(self) -> float | None:
        """Minimum allowed value (read-only; ``None`` if not applicable)."""
        script = ScriptBuilder.iife(
            f"var p = {self._locator}; return (p && p.getMin) ? p.getMin() : null;"
        )
        return self._client.execute(script).value

    @property
    def max(self) -> float | None:
        """Maximum allowed value (read-only; ``None`` if not applicable)."""
        script = ScriptBuilder.iife(
            f"var p = {self._locator}; return (p && p.getMax) ? p.getMax() : null;"
        )
        return self._client.execute(script).value

    def set_key(self, time: float, value: object) -> None:
        """Set a keyframe for this property.

        Args:
            time: The keyframe time in DAZ ticks.
            value: The property value at that keyframe.
        """
        serialized = ScriptBuilder.serialize_arg(value)
        script = ScriptBuilder.iife(f"""
            var p = {self._locator};
            if (p && p.setKey) p.setKey({time}, {serialized});
        """)
        self._client.execute(script)

    @property
    def is_animated(self) -> bool | None:
        """``True`` if this property has keyframe animation data (read-only)."""
        script = ScriptBuilder.iife(
            f"var p = {self._locator}; return p ? p.isAnimated() : null;"
        )
        return self._client.execute(script).value
