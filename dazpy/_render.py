from __future__ import annotations

import json

from ._client import DazClient
from ._script_builder import ScriptBuilder

# Access path: App.getRenderMgr() → DzRenderMgr
# Render options: mgr.getRenderOptions() → DzRenderOptions
# imageSize is a QSize value type — read via .width/.height, write back by
# calling setWidth/setHeight on the copy then reassigning opts.imageSize.
#
# Iray-specific quality/samples settings (Max Samples, Max Time, Rendering
# Quality, ...) are not exposed on DzRenderOptions or DzIrayRenderer directly
# — they live on the active renderer's property holder:
# mgr.getActiveRenderer().getPropertyHolder().findProperty("Max Samples").
# Confirmed against a live DAZ Studio instance; property names match the
# labels shown in the Render Settings pane's Advanced tab.

# (max_samples, max_time_secs, quality, quality_enable)
_QUALITY_PRESETS = {
    "draft":   {"max_samples": 100,  "max_time": 300,  "quality_enable": False},
    "preview": {"max_samples": 500,  "max_time": 900,  "quality_enable": True, "quality": 2.0},
    "good":    {"max_samples": 1500, "max_time": 3600, "quality_enable": True, "quality": 1.0},
    "final":   {"max_samples": 5000, "max_time": 7200, "quality_enable": True, "quality": 1.0},
}


class DazRenderSettings:
    def __init__(self, client: DazClient | None = None):
        self._client = client or DazClient()

    def _render_mgr(self) -> str:
        return "App.getRenderMgr()"

    def _iray_property_holder(self) -> str:
        return f"{self._render_mgr()}.getActiveRenderer().getPropertyHolder()"

    def _get_iray_property(self, name: str):
        script = ScriptBuilder.iife(f"""
            var holder = {self._iray_property_holder()};
            if (!holder) return null;
            var p = holder.findProperty({json.dumps(name)});
            return p ? p.getValue() : null;
        """)
        return self._client.execute(script).value

    def _set_iray_property(self, name: str, value: object) -> None:
        serialized = ScriptBuilder.serialize_arg(value)
        script = ScriptBuilder.iife(f"""
            var holder = {self._iray_property_holder()};
            if (!holder) return;
            var p = holder.findProperty({json.dumps(name)});
            if (p) p.setValue({serialized});
        """)
        self._client.execute(script)

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

    def render(self, camera_name: str | None = None) -> bool:
        """Render the scene to :attr:`output_path`.

        DAZ Studio's ``doRender()`` only writes to disk when ``renderImgToId`` is set
        to ``DzRenderOptions.DirectToFile`` and the camera is applied to both the
        render options and the active viewport before the call.

        Args:
            camera_name: Internal name of the camera node to render from.  When
                omitted the active viewport camera is used.

        Returns:
            ``True`` if the render completed without error.
        """
        if camera_name is not None:
            cam_expr = f"Scene.findCamera({json.dumps(camera_name)})"
        else:
            cam_expr = (
                "MainWindow.getViewportMgr().getActiveViewport()"
                ".get3DViewport().getCamera()"
            )
        script = ScriptBuilder.iife(f"""
            var mgr = {self._render_mgr()};
            if (!mgr) return false;
            var cam = {cam_expr};
            if (!cam) return false;
            var opts = mgr.getRenderOptions();
            opts.camera = cam;
            opts.renderImgToId = DzRenderOptions.DirectToFile;
            var vp = MainWindow.getViewportMgr().getActiveViewport().get3DViewport();
            var prevCam = vp ? vp.getCamera() : null;
            if (vp) vp.setCamera(cam);
            var err = mgr.doRender(opts);
            if (vp && prevCam) vp.setCamera(prevCam);
            return (err === 0 || err === true);
        """)
        return bool(self._client.execute(script).value)

    def render_and_wait(
        self, poll_interval: float = 1.0, timeout: float = 600.0
    ) -> bool:
        """Alias for :meth:`render` kept for backwards compatibility.

        ``doRender()`` is synchronous in DAZ Studio so no polling is required.
        """
        return self.render()

    def has_render(self) -> bool:
        """Return True if there is a completed render available to save."""
        script = ScriptBuilder.iife(f"""
            var mgr = {self._render_mgr()};
            if (!mgr) return false;
            return mgr.hasRender();
        """)
        return bool(self._client.execute(script).value)

    @property
    def max_samples(self) -> int | None:
        """Iray progressive rendering sample cap (``Max Samples`` in the Advanced tab)."""
        result = self._get_iray_property("Max Samples")
        return None if result is None else int(result)

    @max_samples.setter
    def max_samples(self, value: int) -> None:
        self._set_iray_property("Max Samples", int(value))

    @property
    def max_time_secs(self) -> int | None:
        """Iray progressive rendering time cap in seconds (``Max Time`` in the Advanced tab)."""
        result = self._get_iray_property("Max Time")
        return None if result is None else int(result)

    @max_time_secs.setter
    def max_time_secs(self, value: int) -> None:
        self._set_iray_property("Max Time", int(value))

    @property
    def quality(self) -> float | None:
        """Iray ``Rendering Quality`` convergence target (higher converges further)."""
        result = self._get_iray_property("Rendering Quality")
        return None if result is None else float(result)

    @quality.setter
    def quality(self, value: float) -> None:
        self._set_iray_property("Rendering Quality", float(value))

    def set_quality_preset(self, preset: str) -> None:
        """Apply a named Iray quality preset, controlling sample count and render time.

        Args:
            preset: One of ``"draft"``, ``"preview"``, ``"good"``, ``"final"``
                (fastest/lowest quality to slowest/highest quality).

        Raises:
            ValueError: If *preset* is not a recognized preset name.
        """
        settings = _QUALITY_PRESETS.get(preset)
        if settings is None:
            raise ValueError(
                f"Unknown quality preset {preset!r}; expected one of "
                f"{sorted(_QUALITY_PRESETS)}"
            )
        self._set_iray_property("Max Samples", settings["max_samples"])
        self._set_iray_property("Max Time", settings["max_time"])
        self._set_iray_property("Rendering Quality Enable", settings["quality_enable"])
        if "quality" in settings:
            self._set_iray_property("Rendering Quality", settings["quality"])
