from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ._element import DazElement
from ._script_builder import ScriptBuilder

if TYPE_CHECKING:
    from ._client import DazClient


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

    _owner_locator: str
    _property_label: str

    def __init__(self, client: "DazClient", owner_locator: str, property_label: str):
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
    def _from_locator(cls, client: "DazClient", locator: str) -> "DazProperty":
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
    def raw_value(self) -> object:
        """This property's own dial value, excluding any DzERCLink contributions.

        A property driven by one or more ``DzERCLink`` controllers (for
        example a character's "Scale" dial fed by dozens of linked morphs)
        computes :attr:`value` as ``raw_value`` plus every controller's
        contribution. Reading and writing :attr:`value` in a save/restore
        round trip is therefore *not* idempotent for such properties: the
        captured (post-ERC) total gets written back into the raw slot on
        restore, and the ERC links add their contribution again on top,
        inflating the property a little more on every cycle.

        Use ``raw_value`` instead of :attr:`value` whenever you need a
        snapshot/restore round trip to be exact — it reads and writes only
        the property's own baseline and is unaffected by ERC links either
        way. For properties without ERC links, ``raw_value`` and
        :attr:`value` are identical. Falls back to :attr:`value` for
        property types that don't expose a raw accessor (e.g. non-numeric
        properties).
        """
        script = ScriptBuilder.iife(f"""
            var p = {self._locator};
            if (!p) return null;
            return (typeof p.getRawValue === "function") ? p.getRawValue() : p.getValue();
        """)
        return self._client.execute(script).value

    @raw_value.setter
    def raw_value(self, v: object) -> None:
        serialized = ScriptBuilder.serialize_arg(v)
        script = ScriptBuilder.iife(f"""
            var p = {self._locator};
            if (!p) return;
            if (typeof p.setRawValue === "function") {{ p.setRawValue({serialized}); }}
            else {{ p.setValue({serialized}); }}
        """)
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

    def set_key(self, time: float, value: float) -> None:
        """Set a keyframe for this (numeric) property.

        Writes via ``DzNumericProperty.setDoubleValue(tm, val)`` — the
        DazScript keyframe surface confirmed live against a running DAZ
        Studio instance (see ``dazpy.cinematics.apply_animated_shot``,
        which uses the same call). ``DzProperty.setKey()``/``addKey()``,
        which earlier versions of this method called, do not exist on a
        live property and silently wrote nothing.

        Args:
            time: The keyframe time in DAZ ticks.
            value: The numeric property value at that keyframe. Non-numeric
                properties (color, string, enum, ...) are not supported —
                this is a no-op for a property without ``setDoubleValue``.
        """
        script = ScriptBuilder.iife(f"""
            var p = {self._locator};
            if (p && p.setDoubleValue) p.setDoubleValue({time}, {float(value)});
        """)
        self._client.execute(script)

    @property
    def is_animated(self) -> bool | None:
        """``True`` if this property has keyframe animation data (read-only).

        Implemented as ``getNumKeys() > 0`` — ``DzProperty.isAnimated()``,
        which this property called previously, does not exist on a live
        property and raised a ``ScriptRuntimeError`` on every access.
        """
        script = ScriptBuilder.iife(f"""
            var p = {self._locator};
            if (!p || !p.getNumKeys) return null;
            return p.getNumKeys() > 0;
        """)
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
                keys.push({{ time: t.valueOf(), value: p.getDoubleValue(t) }});
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
            if (p && p.deleteKeys) p.deleteKeys(new DzTimeRange({time}, {time}));
        """)
        self._client.execute(script)

    def clear_keys(self) -> int:
        """Remove all keyframes from this property's animation curve.

        Returns:
            How many keys were removed.
        """
        script = ScriptBuilder.iife(f"""
            var p = {self._locator};
            if (!p || !p.deleteAllKeys) return 0;
            var n = p.getNumKeys ? p.getNumKeys() : 0;
            p.deleteAllKeys();
            return n;
        """)
        return int(self._client.execute(script).value or 0)

    # ── frame-based keys (frames convert with Scene.getTimeStep()) ──────────

    def set_key_at_frame(self, frame: int, value: float) -> float | None:
        """Key *value* at timeline *frame* and return the value read back there.

        Unlike :meth:`set_key`, which takes DzTime ticks, *frame* is converted
        with the scene's ticks-per-frame (``Scene.getTimeStep()``).
        """
        script = ScriptBuilder.iife(f"""
            var p = {self._locator};
            if (!p || !p.setDoubleValue) return null;
            var _tm = {int(frame)} * Scene.getTimeStep();
            p.setDoubleValue(_tm, {float(value)!r});
            return p.getDoubleValue(_tm);
        """)
        return self._client.execute(script).value

    def keys_by_frame(self) -> list[tuple[float, float]]:
        """Every key as ``(frame, value)``, frames converted from ticks.

        A key between whole frames comes back with a fractional frame.
        """
        script = ScriptBuilder.iife(f"""
            var p = {self._locator};
            if (!p || !p.getNumKeys) return [];
            var _step = Scene.getTimeStep().valueOf(), out = [];
            for (var i = 0; i < p.getNumKeys(); i++) {{
                var t = p.getKeyTime(i);
                out.push([t.valueOf() / _step, p.getDoubleValue(t)]);
            }}
            return out;
        """)
        return [(k[0], k[1]) for k in self._client.execute(script).value or []]

    def remove_key_at_frame(self, frame: int) -> bool:
        """Remove the key at *frame*; ``False`` if there was none."""
        script = ScriptBuilder.iife(f"""
            var p = {self._locator};
            if (!p || !p.getNumKeys) return false;
            var _tm = {int(frame)} * Scene.getTimeStep();
            var before = p.getNumKeys();
            p.deleteKeys(new DzTimeRange(_tm, _tm));
            return p.getNumKeys() < before;
        """)
        return bool(self._client.execute(script).value)
