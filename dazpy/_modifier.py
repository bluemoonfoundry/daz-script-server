from __future__ import annotations

from ._element import DazElement
from ._script_builder import ScriptBuilder


class DazModifier(DazElement):
    """Proxy for a DzModifier on a given node."""

    def __init__(self, client: "DazClient", locator: str):  # noqa: F821
        super().__init__(client, locator)

    @property
    def modifier_label(self) -> str | None:
        script = ScriptBuilder.iife(
            f"var m = {self._locator}; return m ? m.getLabel() : null;"
        )
        return self._client.execute(script).value

    @property
    def enabled(self) -> bool | None:
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
