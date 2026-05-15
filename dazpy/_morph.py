from __future__ import annotations

from ._modifier import DazModifier
from ._script_builder import ScriptBuilder


class DazMorph(DazModifier):
    """Proxy for a ``DzMorph`` blendshape slider on a node.

    Returned by :meth:`DazNode.morphs` and :meth:`DazNode.find_modifier` when
    the underlying DAZ modifier is a ``DzMorph``.
    """

    @property
    def value(self) -> float | None:
        """Current morph strength (typically 0.0–1.0, read/write)."""
        script = ScriptBuilder.iife(
            f"var m = {self._locator}; return m ? m.getValueChannel().getValue() : null;"
        )
        return self._client.execute(script).value

    @value.setter
    def value(self, v: float) -> None:
        script = ScriptBuilder.iife(
            f"var m = {self._locator}; if (m) m.getValueChannel().setValue({float(v)});"
        )
        self._client.execute(script)

    @property
    def min(self) -> float | None:
        """Minimum allowed value for this morph channel (read-only)."""
        script = ScriptBuilder.iife(
            f"var m = {self._locator}; return m ? m.getValueChannel().getMin() : null;"
        )
        return self._client.execute(script).value

    @property
    def max(self) -> float | None:
        """Maximum allowed value for this morph channel (read-only)."""
        script = ScriptBuilder.iife(
            f"var m = {self._locator}; return m ? m.getValueChannel().getMax() : null;"
        )
        return self._client.execute(script).value
