from __future__ import annotations

import json

from ._client import DazClient
from ._script_builder import ScriptBuilder

_VIEWPORT_EXPR = (
    "MainWindow.getViewportMgr().getActiveViewport().get3DViewport()"
)

# Friendly aliases for Dz3DViewport.setUserDrawStyle()'s label strings.
# Confirmed against a live instance: setUserDrawStyle() takes the exact
# label shown in the viewport's draw-style dropdown and silently no-ops
# (leaves the style unchanged) if the label isn't recognized -- there's no
# script-queryable enumeration of valid labels, so this list is empirical,
# not derived from an SDK enum. A raw label string (e.g. "NVIDIA Iray") is
# also accepted directly.
_DRAW_STYLE_ALIASES = {
    "wire_bounding_box": "Wire Bounding Box",
    "wireframe": "Wireframe",
    "smooth_shaded": "Smooth Shaded",
    "texture_shaded": "Texture Shaded",
    "iray": "NVIDIA Iray",
}


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

    def draw_style(self) -> str | None:
        """Return the viewport's current draw style label (e.g. "NVIDIA Iray")."""
        script = ScriptBuilder.iife(f"""
            var vp = {_VIEWPORT_EXPR};
            if (!vp) return null;
            return vp.getUserDrawStyle();
        """)
        return self._client.execute(script).value

    def set_draw_style(self, style: str) -> None:
        """Set the viewport's draw style (preview quality, e.g. "Wireframe" .. "NVIDIA Iray").

        Accepts a friendly alias (see ``_DRAW_STYLE_ALIASES``: "wireframe",
        "wire_bounding_box", "smooth_shaded", "texture_shaded", "iray") or a
        raw DAZ Studio label such as "NVIDIA Iray" directly.

        Raises:
            ValueError: If the style isn't recognized. ``setUserDrawStyle()``
                silently no-ops on an unknown label rather than erroring, so
                this reads the style back afterward and raises if it didn't
                change (and wasn't already the requested style).
        """
        resolved = _DRAW_STYLE_ALIASES.get(style.strip().lower(), style)
        script = ScriptBuilder.iife(f"""
            var vp = {_VIEWPORT_EXPR};
            if (!vp) return null;
            var before = vp.getUserDrawStyle();
            vp.setUserDrawStyle({json.dumps(resolved)});
            return {{before: before, after: vp.getUserDrawStyle()}};
        """)
        result = self._client.execute(script).value
        if result is None:
            return
        if result["after"] != resolved and result["after"] == result["before"]:
            raise ValueError(f"Unknown viewport draw style: {style!r}")

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
        hide_overlays: bool = True,
        backdrop_color: tuple[int, int, int] | None = None,
    ) -> str:
        """Capture the active 3D viewport to a PNG or JPEG file.

        When *hide_overlays* is True (default), axes, floor grid, pose tool,
        and aspect frame are temporarily disabled before capture and restored
        afterwards.  Pass False to capture the viewport exactly as it appears.

        *backdrop_color* sets the viewport background to an (R, G, B) colour
        for the duration of the capture, then restores the original.  Useful
        for background-removal workflows — pick a colour that contrasts with
        the subject (e.g. ``(0, 255, 0)`` for green screen).

        *width* and *height* are accepted for API compatibility but ignored —
        Dz3DViewport does not expose resize via DazScript.
        """
        js_path = json.dumps(path)

        if backdrop_color is not None:
            r, g, b = int(backdrop_color[0]), int(backdrop_color[1]), int(backdrop_color[2])
            js_hex = json.dumps(f"#{r:02x}{g:02x}{b:02x}")
            set_bg = f"var prevBg = vp.background; vp.background = new QColor({js_hex});"
            restore_bg = "vp.background = prevBg;"
        else:
            set_bg = ""
            restore_bg = ""

        if hide_overlays:
            script = ScriptBuilder.iife(f"""
                var vp = {_VIEWPORT_EXPR};
                if (!vp) return null;

                var prevAxes        = vp.axesOn;
                var prevFloor       = vp.floorStyle;
                var prevPose        = vp.showPoseTool;
                var prevAspect      = vp.aspectOn;
                var prevThirds      = vp.thirdsGuideOn;
                var prevToolBarMode = vp.toolBarMode;

                var prevSelection = Scene.getPrimarySelection();
                var tnNode  = Scene.findNodeByLabel("Tonemapper Options");
                var envNode = Scene.findNodeByLabel("Environment Options");
                var prevTnVisible  = tnNode  ? tnNode.isVisibleInViewport()  : null;
                var prevEnvVisible = envNode ? envNode.isVisibleInViewport() : null;

                vp.axesOn        = false;
                vp.floorStyle    = 0;
                vp.showPoseTool  = false;
                vp.aspectOn      = false;
                vp.thirdsGuideOn = false;
                vp.toolBarMode   = 0;
                {set_bg}

                Scene.setPrimarySelection(null);
                if (tnNode)  tnNode.setVisibleInViewport(false);
                if (envNode) envNode.setVisibleInViewport(false);

                vp.updateGL();
                var img = vp.captureImage();

                vp.axesOn        = prevAxes;
                vp.floorStyle    = prevFloor;
                vp.showPoseTool  = prevPose;
                vp.aspectOn      = prevAspect;
                vp.thirdsGuideOn = prevThirds;
                vp.toolBarMode   = prevToolBarMode;
                {restore_bg}

                Scene.setPrimarySelection(prevSelection);
                if (tnNode  && prevTnVisible  !== null) tnNode.setVisibleInViewport(prevTnVisible);
                if (envNode && prevEnvVisible !== null) envNode.setVisibleInViewport(prevEnvVisible);

                vp.updateGL();

                if (!img) return null;
                img.save({js_path});
                return {js_path};
            """)
        else:
            script = ScriptBuilder.iife(f"""
                var vp = {_VIEWPORT_EXPR};
                if (!vp) return null;
                {set_bg}
                vp.updateGL();
                var img = vp.captureImage();
                {restore_bg}
                vp.updateGL();
                if (!img) return null;
                img.save({js_path});
                return {js_path};
            """)
        result = self._client.execute(script).value
        return str(result) if result is not None else path

    def capture_sprite(
        self,
        path: str,
        width: int | None = None,
        height: int | None = None,
        backdrop_color: tuple[int, int, int] | None = None,
    ) -> str:
        """Capture the viewport and remove the background, saving a transparent PNG.

        Uses alpha matting for clean edges including interior gaps (e.g. between
        arms and body).  Leave *backdrop_color* as None to use the current
        viewport background, or pass an (R, G, B) tuple to temporarily override
        it for the capture.

        Requires the ``rembg`` package (``pip install rembg``).
        The output path should end in ``.png`` to preserve the alpha channel.
        """
        try:
            from rembg import remove as rembg_remove, new_session
        except ImportError as exc:
            raise ImportError(
                "capture_sprite() requires rembg: pip install rembg"
            ) from exc

        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp_path = f.name
        try:
            self.capture(tmp_path, width=width, height=height, backdrop_color=backdrop_color)
            with open(tmp_path, "rb") as f:
                input_data = f.read()
        finally:
            os.unlink(tmp_path)

        session = new_session("u2net")
        output_data = rembg_remove(
            input_data,
            session=session,
            alpha_matting=True,
            alpha_matting_foreground_threshold=240,
            alpha_matting_background_threshold=10,
            alpha_matting_erode_size=10,
        )
        with open(path, "wb") as f:
            f.write(output_data)
        return path
