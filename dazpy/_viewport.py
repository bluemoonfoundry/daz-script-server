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
        hide_overlays: bool = True,
    ) -> str:
        """Capture the active 3D viewport to a PNG or JPEG file.

        When *hide_overlays* is True (default), axes, floor grid, pose tool,
        and aspect frame are temporarily disabled before capture and restored
        afterwards.  Pass False to capture the viewport exactly as it appears.

        *width* and *height* are accepted for API compatibility but ignored —
        Dz3DViewport does not expose resize via DazScript.
        """
        js_path = json.dumps(path)
        if hide_overlays:
            script = ScriptBuilder.iife(f"""
                var vp = {_VIEWPORT_EXPR};
                if (!vp) return null;

                // Save viewport overlay state
                var prevAxes        = vp.axesOn;
                var prevFloor       = vp.floorStyle;
                var prevPose        = vp.showPoseTool;
                var prevAspect      = vp.aspectOn;
                var prevThirds      = vp.thirdsGuideOn;
                var prevToolBarMode = vp.toolBarMode;

                // Save scene state
                var prevSelection = Scene.getPrimarySelection();
                var tnNode = Scene.findNodeByLabel("Tonemapper Options");
                var envNode = Scene.findNodeByLabel("Environment Options");
                var prevTnVisible  = tnNode  ? tnNode.isVisibleInViewport()  : null;
                var prevEnvVisible = envNode ? envNode.isVisibleInViewport() : null;

                // Hide overlays
                vp.axesOn        = false;
                vp.floorStyle    = 0;
                vp.showPoseTool  = false;
                vp.aspectOn      = false;
                vp.thirdsGuideOn = false;
                vp.toolBarMode   = 0;

                // Deselect and hide env nodes
                Scene.setPrimarySelection(null);
                if (tnNode)  tnNode.setVisibleInViewport(false);
                if (envNode) envNode.setVisibleInViewport(false);

                vp.updateGL();

                var img = vp.captureImage();

                // Restore all state
                vp.axesOn        = prevAxes;
                vp.floorStyle    = prevFloor;
                vp.showPoseTool  = prevPose;
                vp.aspectOn      = prevAspect;
                vp.thirdsGuideOn = prevThirds;
                vp.toolBarMode   = prevToolBarMode;

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
                var img = vp.captureImage();
                if (!img) return null;
                img.save({js_path});
                return {js_path};
            """)
        result = self._client.execute(script).value
        return str(result) if result is not None else path
