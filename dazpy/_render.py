from __future__ import annotations

import json

from ._client import DazClient
from ._script_builder import ScriptBuilder

# Access path: App.getRenderMgr() → DzRenderMgr
# Render options: mgr.getRenderOptions() → DzRenderOptions
# imageSize is a QSize value type — read via .width/.height, write back by
# calling setWidth/setHeight on the copy then reassigning opts.imageSize.


class DazRenderSettings:
    def __init__(self, client: DazClient | None = None):
        self._client = client or DazClient()

    def _render_mgr(self) -> str:
        return "App.getRenderMgr()"

    def is_available(self) -> bool:
        """Return True if the render manager is accessible."""
        script = ScriptBuilder.iife(f"""
            var mgr = {self._render_mgr()};
            return (mgr !== null && mgr !== undefined);
        """)
        result = self._client.execute(script).value
        return bool(result)

    def is_rendering(self) -> bool:
        """Return True if a render is currently in progress."""
        script = ScriptBuilder.iife(f"""
            var mgr = {self._render_mgr()};
            if (!mgr) return false;
            return mgr.isRendering();
        """)
        return bool(self._client.execute(script).value)

    @property
    def resolution(self) -> dict | None:
        """Return the render image size as {{width, height}}."""
        script = ScriptBuilder.iife(f"""
            var mgr = {self._render_mgr()};
            if (!mgr) return null;
            var opts = mgr.getRenderOptions();
            var sz = opts.imageSize;
            return {{width: sz.width, height: sz.height}};
        """)
        return self._client.execute(script).value

    def set_resolution(self, width: int, height: int) -> None:
        """Set the render image size in pixels."""
        w, h = int(width), int(height)
        # QSize is exposed as a constructor in DazScript; plain object literals
        # are not coerced, so new QSize(w, h) is required.
        script = ScriptBuilder.iife(f"""
            var mgr = {self._render_mgr()};
            if (!mgr) return;
            var opts = mgr.getRenderOptions();
            opts.imageSize = new QSize({w}, {h});
            opts.applyChanges();
        """)
        self._client.execute(script)

    @property
    def output_path(self) -> str | None:
        """Return the filename set for rendered images."""
        script = ScriptBuilder.iife(f"""
            var mgr = {self._render_mgr()};
            if (!mgr) return null;
            return mgr.getRenderOptions().renderImgFilename;
        """)
        return self._client.execute(script).value

    @output_path.setter
    def output_path(self, path: str) -> None:
        script = ScriptBuilder.iife(f"""
            var mgr = {self._render_mgr()};
            if (!mgr) return;
            var opts = mgr.getRenderOptions();
            opts.renderImgFilename = {json.dumps(path)};
            opts.applyChanges();
        """)
        self._client.execute(script)

    @property
    def gamma(self) -> float | None:
        """Return the gamma correction value."""
        script = ScriptBuilder.iife(f"""
            var mgr = {self._render_mgr()};
            if (!mgr) return null;
            var opts = mgr.getRenderOptions();
            return opts.gamma;
        """)
        return self._client.execute(script).value

    @gamma.setter
    def gamma(self, value: float) -> None:
        script = ScriptBuilder.iife(f"""
            var mgr = {self._render_mgr()};
            if (!mgr) return;
            var opts = mgr.getRenderOptions();
            opts.gamma = {float(value)};
            opts.applyChanges();
        """)
        self._client.execute(script)

    @property
    def double_sided(self) -> bool | None:
        """Return whether polygons are rendered as double-sided."""
        script = ScriptBuilder.iife(f"""
            var mgr = {self._render_mgr()};
            if (!mgr) return null;
            return mgr.getRenderOptions().doubleSided;
        """)
        result = self._client.execute(script).value
        return None if result is None else bool(result)

    @double_sided.setter
    def double_sided(self, value: bool) -> None:
        js_bool = "true" if value else "false"
        script = ScriptBuilder.iife(f"""
            var mgr = {self._render_mgr()};
            if (!mgr) return;
            var opts = mgr.getRenderOptions();
            opts.doubleSided = {js_bool};
            opts.applyChanges();
        """)
        self._client.execute(script)

    def render(self) -> bool:
        """Trigger a render. Returns True if the render was started successfully."""
        script = ScriptBuilder.iife(f"""
            var mgr = {self._render_mgr()};
            if (!mgr) return false;
            return mgr.doRender();
        """)
        return bool(self._client.execute(script).value)

    def has_render(self) -> bool:
        """Return True if there is a completed render available to save."""
        script = ScriptBuilder.iife(f"""
            var mgr = {self._render_mgr()};
            if (!mgr) return false;
            return mgr.hasRender();
        """)
        return bool(self._client.execute(script).value)
