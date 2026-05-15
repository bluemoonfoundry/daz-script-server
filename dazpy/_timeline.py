from __future__ import annotations

from ._client import DazClient
from ._script_builder import ScriptBuilder


class DazTimeline:
    def __init__(self, client: DazClient | None = None):
        self._client = client or DazClient()

    @property
    def frame(self) -> int | None:
        script = ScriptBuilder.iife("return Scene.getFrame();")
        return self._client.execute(script).value

    @frame.setter
    def frame(self, value: int) -> None:
        script = ScriptBuilder.iife(f"Scene.setFrame({int(value)});")
        self._client.execute(script)

    @property
    def time(self) -> int | None:
        """Current time in DAZ ticks (use frame for frame-based access)."""
        script = ScriptBuilder.iife("return Scene.getTime().valueOf();")
        return self._client.execute(script).value

    @property
    def time_step(self) -> float | None:
        script = ScriptBuilder.iife("return Scene.getTimeStep();")
        return self._client.execute(script).value

    @property
    def frame_range(self) -> dict | None:
        script = ScriptBuilder.iife("""
            return {
                start: Scene.getAnimRange().start,
                end: Scene.getAnimRange().end
            };
        """)
        return self._client.execute(script).value

    def play(self) -> None:
        script = ScriptBuilder.iife("Scene.play();")
        self._client.execute(script)

    def pause(self) -> None:
        script = ScriptBuilder.iife("Scene.stop();")
        self._client.execute(script)
