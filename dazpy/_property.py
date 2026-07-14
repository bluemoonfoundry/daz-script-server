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

    @classmethod
    def _from_locator(cls, client: "DazClient", locator: str) -> "DazProperty":  # noqa: F821
        """Construct a DazProperty from a pre-built JavaScript locator expression."""
        from ._element import DazElement
        prop = object.__new__(cls)
        DazElement.__init__(prop, client, locator)
        return prop

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

    def get_keys(self) -> list[dict]:
        """List all keyframes on this property's animation curve.

        Returns:
            A list of ``{"time": float, "value": object}`` dicts, one per
            keyframe, ordered by time. Empty list if the property has no
            keys or doesn't support keyframing.
        """
        script = ScriptBuilder.iife(f"""
            var p = {self._locator};
            if (!p || !p.getNumKeys) return [];
            var n = p.getNumKeys();
            var keys = [];
            for (var i = 0; i < n; i++) {{
                var t = p.getKeyTime(i);
                keys.push({{ time: t, value: p.getDoubleValue(t) }});
            }}
            return keys;
        """)
        return self._client.execute(script).value

    def remove_key(self, time: float) -> None:
        """Remove a single keyframe at the given time.

        Args:
            time: The keyframe time in DAZ ticks. If no key exists at
                exactly this time, this is a no-op.
        """
        script = ScriptBuilder.iife(f"""
            var p = {self._locator};
            if (p && p.deleteKeys) p.deleteKeys({time}, {time});
        """)
        self._client.execute(script)

    def clear_keys(self) -> None:
        """Remove all keyframes from this property's animation curve."""
        script = ScriptBuilder.iife(f"""
            var p = {self._locator};
            if (p && p.deleteAllKeys) p.deleteAllKeys();
        """)
        self._client.execute(script)
