from __future__ import annotations

import json
from dataclasses import dataclass

from ._client import DazClient
from ._script_builder import ScriptBuilder
from .exceptions import RenderError

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

# Mirrors the engineMap in DzScriptServerPane.cpp's render script builder --
# keep in sync. 3Delight is no longer supported by DAZ Studio and excluded.
_ENGINE_CLASS_TO_NAME = {
    "DzIrayRenderer": "iray",
    "DzFilamentRenderer": "filament",
}

# (max_samples, max_time_secs, quality, quality_enable)
_QUALITY_PRESETS = {
    "draft":   {"max_samples": 100,  "max_time": 300,  "quality_enable": False},
    "preview": {"max_samples": 500,  "max_time": 900,  "quality_enable": True, "quality": 2.0},
    "good":    {"max_samples": 1500, "max_time": 3600, "quality_enable": True, "quality": 1.0},
    "final":   {"max_samples": 5000, "max_time": 7200, "quality_enable": True, "quality": 1.0},
}

# Iray Canvases (Render Settings > Advanced > Canvases) are not exposed on
# DzIrayRenderer/DzRenderOptions at all -- they live on a separate
# DzIrayPropertyHolder returned as element [1] of
# App.getRenderMgr().getRenderElementObjects(), confirmed against a live
# DAZ Studio instance:
#
#   holder.renderToCanvases            -- bool, master on/off for all canvas output
#   holder.getNumCanvasDefinitions()    -- int
#   holder.getCanvasDefinition(i)       -- canvas object
#   holder.findCanvasDefinition(name, createIfMissing) -- canvas object or null
#   holder.removeCanvasDefinition(canvas)
#
#   canvas.name                        -- e.g. "Canvas1", auto-generated but editable
#   canvas.canvasType                  -- int enum (Beauty, Normal, Depth, MaterialID, ...)
#   canvas.canvasTypeToString(int) / canvasTypeFromString(string)
#
# canvas.processingDisabled exists but does NOT gate render output (confirmed
# it still renders when true) -- do not rely on it for per-canvas enable/disable.
#
# Each enabled canvas is written to
#   <output_dir>/<basename>_canvases/<basename>-<canvasName>-<canvasType>.exr
# alongside the main render output (confirmed empirically; not queryable via
# script, so canvas_output_paths() below derives it from this convention).
#
# UI widgets in the Render Settings pane do not repaint after a scripted
# property write -- MainWindow.getPaneMgr().findPane("DzRenderSettingsPane")
# .refresh() must be called after any scripted change for the UI to reflect
# it. Every write in this module does so as standard practice.


@dataclass
class Canvas:
    """An Iray Canvas definition (extra render pass alongside the beauty image)."""

    name: str
    canvas_type: str
    index: int


@dataclass
class RenderOutcome:
    """Result of a :meth:`DazRenderSettings.render` call."""

    success: bool
    output_path: str | None


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

    def _iray_render_options_holder(self) -> str:
        # Canvas definitions live on this holder, not on getActiveRenderer()
        # .getPropertyHolder() -- confirmed against a live instance; index 1
        # is "NVIDIA Iray Render Options" among the 4 fixed render element
        # groups (General Render, Iray, Tonemapper, Environment).
        return f"{self._render_mgr()}.getRenderElementObjects()[1]"

    @staticmethod
    def _refresh_render_settings_pane_script() -> str:
        return (
            'var _pane = MainWindow.getPaneMgr().findPane("DzRenderSettingsPane");'
            "if (_pane) _pane.refresh();"
        )

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

    def active_engine(self) -> str | None:
        """Return the active render engine name.

        The Render Settings pane's "Engine" dropdown conflates two separate
        DazScript concepts, confirmed against a live instance:
        ``DzRenderOptions.renderType`` is a 3-value enum (ScreenShot,
        HardwareAssisted, Software) picking *how* the scene is rendered;
        only when it's ``Software`` does ``renderMgr.getActiveRenderer()``
        (the pluggable Iray/Filament/... renderer) apply. Returns
        ``"viewport"`` or ``"multi_pass_opengl"`` for the first two modes,
        otherwise the mapped engine name (e.g. "iray", "filament"), falling
        back to the raw DazScript class name (e.g. "DzIrayRenderer") if it
        isn't one of the known engines.
        """
        script = ScriptBuilder.iife(f"""
            var mgr = {self._render_mgr()};
            if (!mgr) return null;
            var opts = mgr.getRenderOptions();
            if (opts.renderType === opts.ScreenShot) return "viewport";
            if (opts.renderType === opts.HardwareAssisted) return "multi_pass_opengl";
            var renderer = mgr.getActiveRenderer();
            return renderer ? renderer.className() : null;
        """)
        class_name = self._client.execute(script).value
        if class_name is None:
            return None
        return _ENGINE_CLASS_TO_NAME.get(class_name, class_name)

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

    def render(self, camera_name: str | None = None) -> RenderOutcome:
        """Render the scene to :attr:`output_path`.

        DAZ Studio's ``doRender()`` only writes to disk when ``renderImgToId`` is set
        to ``DzRenderOptions.DirectToFile`` and the camera is applied to both the
        render options and the active viewport before the call.

        Args:
            camera_name: Internal name of the camera node to render from.  When
                omitted the active viewport camera is used.

        Returns:
            A :class:`RenderOutcome` with ``success`` and the resolved
            ``output_path`` actually written by ``doRender()``
            (``opts.renderImgFilename`` after the call).
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
            if (!mgr) return {{success: false, output_path: null}};
            var cam = {cam_expr};
            if (!cam) return {{success: false, output_path: null}};
            var opts = mgr.getRenderOptions();
            opts.camera = cam;
            opts.renderImgToId = DzRenderOptions.DirectToFile;
            var vp = MainWindow.getViewportMgr().getActiveViewport().get3DViewport();
            var prevCam = vp ? vp.getCamera() : null;
            if (vp) vp.setCamera(cam);
            var err = mgr.doRender(opts);
            if (vp && prevCam) vp.setCamera(prevCam);
            return {{
                success: (err === 0 || err === true),
                output_path: mgr.getRenderOptions().renderImgFilename
            }};
        """)
        result = self._client.execute(script).value or {}
        return RenderOutcome(
            success=bool(result.get("success", False)),
            output_path=result.get("output_path"),
        )

    def render_and_wait(
        self, poll_interval: float = 1.0, timeout: float = 600.0
    ) -> RenderOutcome:
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

    @property
    def canvases_enabled(self) -> bool | None:
        """Master on/off switch for all Iray Canvas output (``Render to Canvases``)."""
        script = ScriptBuilder.iife(f"""
            var holder = {self._iray_render_options_holder()};
            if (!holder) return null;
            return holder.renderToCanvases;
        """)
        result = self._client.execute(script).value
        return None if result is None else bool(result)

    @canvases_enabled.setter
    def canvases_enabled(self, value: bool) -> None:
        js_bool = "true" if value else "false"
        script = ScriptBuilder.iife(f"""
            var holder = {self._iray_render_options_holder()};
            if (!holder) return;
            holder.renderToCanvases = {js_bool};
            {self._refresh_render_settings_pane_script()}
        """)
        self._client.execute(script)

    def list_canvases(self) -> list[Canvas]:
        """List the Iray Canvases currently configured on the active render."""
        script = ScriptBuilder.iife(f"""
            var holder = {self._iray_render_options_holder()};
            if (!holder) return [];
            var result = [];
            var n = holder.getNumCanvasDefinitions();
            for (var i = 0; i < n; i++) {{
                var c = holder.getCanvasDefinition(i);
                result.push({{
                    name: c.name,
                    canvas_type: c.canvasTypeToString(c.canvasType),
                    index: c.index
                }});
            }}
            return result;
        """)
        result = self._client.execute(script).value or []
        return [Canvas(**c) for c in result]

    def add_canvas(self, name: str, canvas_type: str) -> Canvas:
        """Add (or reconfigure) an Iray Canvas by name.

        Args:
            name: Canvas name. If a canvas with this name already exists it is
                reconfigured to *canvas_type* rather than duplicated.
            canvas_type: One of ``"Beauty"``, ``"Diffuse"``, ``"Specular"``,
                ``"Glossy"``, ``"Emission"``, ``"LightGroup"``,
                ``"EnvironmentLighting"``, ``"LPE"``, ``"Irradiance"``,
                ``"Alpha"``, ``"Shadow"``, ``"AmbientOcclusion"``,
                ``"Distance"``, ``"Depth"``, ``"MaterialTag"``,
                ``"MaterialID"``, ``"ObjectID"``, ``"Normal"``,
                ``"TextureCoordinate"``, ``"BSDFWeight"``,
                ``"ConvergenceHeatmap"``, ``"PostToon"``, ``"WorldPosition"``.

        Returns:
            The resulting :class:`Canvas`.

        Raises:
            RenderError: If the render manager or Iray property holder is
                unavailable.
        """
        script = ScriptBuilder.iife(f"""
            var holder = {self._iray_render_options_holder()};
            if (!holder) return null;
            var c = holder.findCanvasDefinition({json.dumps(name)}, true);
            c.canvasType = c.canvasTypeFromString({json.dumps(canvas_type)});
            {self._refresh_render_settings_pane_script()}
            return {{
                name: c.name,
                canvas_type: c.canvasTypeToString(c.canvasType),
                index: c.index
            }};
        """)
        result = self._client.execute(script).value
        if result is None:
            raise RenderError(
                "Failed to add canvas: render manager or Iray property holder unavailable"
            )
        return Canvas(**result)

    def remove_canvas(self, name: str) -> bool:
        """Remove a configured Iray Canvas by name.

        Returns:
            ``True`` if a matching canvas was found and removed, ``False`` if
            no canvas with *name* exists.
        """
        script = ScriptBuilder.iife(f"""
            var holder = {self._iray_render_options_holder()};
            if (!holder) return false;
            var c = holder.findCanvasDefinition({json.dumps(name)}, false);
            if (!c) return false;
            holder.removeCanvasDefinition(c);
            {self._refresh_render_settings_pane_script()}
            return true;
        """)
        return bool(self._client.execute(script).value)

    def canvas_output_paths(self, output_path: str) -> dict[str, str]:
        """Return each configured canvas's resolved output file path for a render to *output_path*.

        Derived from DAZ Studio's naming convention -- canvases are written to
        ``<dir>/<basename>_canvases/<basename>-<canvasName>-<canvasType>.exr``
        alongside the main render output. Confirmed empirically against a live
        render; DazScript does not expose these paths directly, so this is
        computed rather than queried.

        Args:
            output_path: The path passed as the main render's ``output_path``
                (i.e. what :attr:`output_path` would be set to).

        Returns:
            A dict mapping each canvas's name to its resolved output path.
        """
        sep_idx = max(output_path.rfind("/"), output_path.rfind("\\"))
        directory = output_path[:sep_idx] if sep_idx >= 0 else ""
        filename = output_path[sep_idx + 1:]
        dot_idx = filename.rfind(".")
        basename = filename[:dot_idx] if dot_idx >= 0 else filename
        sep = output_path[sep_idx] if sep_idx >= 0 else "/"
        prefix = f"{directory}{sep}" if directory else ""
        canvases_dir = f"{basename}_canvases"

        return {
            canvas.name: f"{prefix}{canvases_dir}{sep}{basename}-{canvas.name}-{canvas.canvas_type}.exr"
            for canvas in self.list_canvases()
        }
