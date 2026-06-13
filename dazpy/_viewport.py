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
            var r = vp.geometry();
            return {{width: r.width, height: r.height}};
        """)
        return self._client.execute(script).value

    def set_size(self, width: int, height: int) -> None:
        """Resize the active 3D viewport."""
        w, h = int(width), int(height)
        script = ScriptBuilder.iife(f"""
            var vp = {_VIEWPORT_EXPR};
            if (!vp) return;
            vp.setFixedSize(new QSize({w}, {h}));
        """)
        self._client.execute(script)

    def capture(
        self,
        path: str,
        width: int | None = None,
        height: int | None = None,
    ) -> str:
        """Capture the active 3D viewport to a PNG or JPEG file.

        When *width* and *height* are given the viewport is temporarily resized
        before capture and restored afterwards.  The output path is returned as
        confirmation.
        """
        js_path = json.dumps(path)
        resize_before = ""
        resize_after = ""
        if width is not None and height is not None:
            w, h = int(width), int(height)
            resize_before = (
                f"var _prevSize = vp.geometry();"
                f"vp.setFixedSize(new QSize({w}, {h}));"
            )
            resize_after = (
                "vp.setFixedSize(new QSize(_prevSize.width, _prevSize.height));"
            )

        script = ScriptBuilder.iife(f"""
            var vp = {_VIEWPORT_EXPR};
            if (!vp) return null;
            {resize_before}
            vp.captureToFile({js_path});
            {resize_after}
            return {js_path};
        """)
        result = self._client.execute(script).value
        return str(result) if result is not None else path
