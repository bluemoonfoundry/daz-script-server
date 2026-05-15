from __future__ import annotations

from ._client import DazClient
from ._script_builder import ScriptBuilder


class DazTimeline:
    """Timeline and playback control for the active DAZ Studio scene.

    A thin wrapper around the ``Scene`` playback API.  For most use-cases
    :class:`~dazpy.DazScene` provides the same frame / range methods; use
    ``DazTimeline`` when you want a focused object dedicated to animation
    control.

    Args:
        client: Optional :class:`~dazpy.DazClient`.  Defaults to a new client
            at ``127.0.0.1:18811``.
    """

    def __init__(self, client: DazClient | None = None):
        self._client = client or DazClient()

    @property
    def frame(self) -> int | None:
        """Current timeline frame (read/write)."""
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
        """Number of DAZ ticks per frame (read-only)."""
        script = ScriptBuilder.iife("return Scene.getTimeStep();")
        return self._client.execute(script).value

    @property
    def frame_range(self) -> dict | None:
        """Animation range as ``{"start": int, "end": int}`` in frames (read-only)."""
        script = ScriptBuilder.iife("""
            return {
                start: Scene.getAnimRange().start,
                end: Scene.getAnimRange().end
            };
        """)
        return self._client.execute(script).value

    def play(self) -> None:
        """Start playback."""
        script = ScriptBuilder.iife("Scene.play();")
        self._client.execute(script)

    def pause(self) -> None:
        """Stop / pause playback."""
        script = ScriptBuilder.iife("Scene.stop();")
        self._client.execute(script)
