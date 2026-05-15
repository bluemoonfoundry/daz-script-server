from __future__ import annotations

from ._element import DazElement
from ._script_builder import ScriptBuilder


class DazModifier(DazElement):
    """Proxy for a ``DzModifier`` (constraint, formula, etc.) on a node.

    Instances are obtained via :meth:`DazNode.modifiers` or
    :meth:`DazNode.find_modifier`.  For morph/blendshape modifiers, the more
    specific :class:`~dazpy.DazMorph` subclass is returned automatically.
    """

    def __init__(self, client: "DazClient", locator: str):  # noqa: F821
        super().__init__(client, locator)

    @property
    def modifier_label(self) -> str | None:
        """User-visible display label of this modifier (read-only)."""
        script = ScriptBuilder.iife(
            f"var m = {self._locator}; return m ? m.getLabel() : null;"
        )
        return self._client.execute(script).value

    @property
    def enabled(self) -> bool | None:
        """Whether this modifier is currently active (read/write)."""
        script = ScriptBuilder.iife(
            f"var m = {self._locator}; return m ? m.isEnabled() : null;"
        )
        return self._client.execute(script).value

    @enabled.setter
    def enabled(self, value: bool) -> None:
        flag = "true" if value else "false"
        script = ScriptBuilder.iife(
            f"var m = {self._locator}; if (m) m.setEnabled({flag});"
        )
        self._client.execute(script)
