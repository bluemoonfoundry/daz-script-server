from __future__ import annotations

import json

from ._client import DazClient
from ._script_builder import ScriptBuilder

_VIEWPORT_EXPR = (
    "MainWindow.getViewportMgr().getActiveViewport().get3DViewport()"
)


class DazViewport:
    def __init__(self, client: DazClient | None = None):
        self._client = client or DazClient()

    def is_available(self) -> bool:
        """Return True if an active 3D viewport is accessible."""
        script = ScriptBuilder.iife(f"""
            var vp = {_VIEWPORT_EXPR};
            return (vp !== null && vp !== undefined);
        """)
        return bool(self._client.execute(script).value)

    def get_size(self) -> dict | None:
        """Return the viewport dimensions as {{width, height}}."""
        script = ScriptBuilder.iife(f"""
            var vp = {_VIEWPORT_EXPR};
            if (!vp) return null;
            var r = vp.geometry;
            return {{width: r.width, height: r.height}};
        """)
        return self._client.execute(script).value

    def set_size(self, width: int, height: int) -> None:
        """Not supported — Dz3DViewport does not expose resize via DazScript.

        Resize the DAZ Studio viewport window manually before calling capture().
        """
        raise NotImplementedError(
            "Viewport resize via DazScript is not supported. "
            "Resize the DAZ Studio viewport window manually."
        )

    def capture(
        self,
        path: str,
        width: int | None = None,
        height: int | None = None,
    ) -> str:
        """Capture the active 3D viewport to a PNG or JPEG file.

        *width* and *height* are accepted for API compatibility but ignored —
        Dz3DViewport does not expose resize via DazScript.  Set the viewport
        size in DAZ Studio before calling this method if a specific resolution
        is needed.  The output path is returned as confirmation.
        """
        js_path = json.dumps(path)
        script = ScriptBuilder.iife(f"""
            var vp = {_VIEWPORT_EXPR};
            if (!vp) return null;
            var img = vp.captureImage();
            if (!img) return null;
            img.save({js_path});
            return {js_path};
        """)
        result = self._client.execute(script).value
        return str(result) if result is not None else path
