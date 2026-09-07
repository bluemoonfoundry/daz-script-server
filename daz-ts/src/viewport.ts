import type { DazClient } from "./client.js";
import { DazClient as DazClientImpl } from "./client.js";
import { ScriptBuilder } from "./scriptBuilder.js";

const VIEWPORT_EXPR = "MainWindow.getViewportMgr().getActiveViewport().get3DViewport()";

/**
 * Friendly aliases for `Dz3DViewport.setUserDrawStyle()`'s label strings.
 * Confirmed against a live instance: `setUserDrawStyle()` takes the exact
 * label shown in the viewport's draw-style dropdown and silently no-ops if
 * the label isn't recognized — empirical, not derived from an SDK enum. A
 * raw label string (e.g. `"NVIDIA Iray"`) is also accepted directly.
 */
const DRAW_STYLE_ALIASES: Record<string, string> = {
  wire_bounding_box: "Wire Bounding Box",
  wireframe: "Wireframe",
  smooth_shaded: "Smooth Shaded",
  texture_shaded: "Texture Shaded",
  iray: "NVIDIA Iray",
};

/** Viewport control: draw style, size query, and screenshot capture for DAZ Studio's active 3D viewport. */
export class DazViewport {
  private readonly client: DazClient;

  constructor(client?: DazClient) {
    this.client = client ?? new DazClientImpl();
  }

  /** `true` if an active 3D viewport is accessible. */
  async isAvailable(): Promise<boolean> {
    const script = ScriptBuilder.iife(`var vp = ${VIEWPORT_EXPR}; return (vp !== null && vp !== undefined);`);
    return Boolean((await this.client.execute(script)).value);
  }

  /** Current draw style label (e.g. `"NVIDIA Iray"`). */
  async drawStyle(): Promise<string | null> {
    const script = ScriptBuilder.iife(`var vp = ${VIEWPORT_EXPR}; if (!vp) return null; return vp.getUserDrawStyle();`);
    return (await this.client.execute(script)).value as string | null;
  }

  /**
   * Set the viewport's draw style (preview quality). Accepts a friendly
   * alias (`"wireframe"`, `"wire_bounding_box"`, `"smooth_shaded"`,
   * `"texture_shaded"`, `"iray"`) or a raw DAZ Studio label directly.
   * @throws Error if the style isn't recognized — `setUserDrawStyle()`
   * silently no-ops on an unknown label, so this reads the style back
   * afterward and throws if it didn't change (and wasn't already applied).
   */
  async setDrawStyle(style: string): Promise<void> {
    const resolved = DRAW_STYLE_ALIASES[style.trim().toLowerCase()] ?? style;
    const script = ScriptBuilder.iife(`
            var vp = ${VIEWPORT_EXPR};
            if (!vp) return null;
            var before = vp.getUserDrawStyle();
            vp.setUserDrawStyle(${ScriptBuilder.escapeString(resolved)});
            return {before: before, after: vp.getUserDrawStyle()};
        `);
    const result = (await this.client.execute(script)).value as { before: string; after: string } | null;
    if (result === null) return;
    if (result.after !== resolved && result.after === result.before) {
      throw new Error(`Unknown viewport draw style: ${JSON.stringify(style)}`);
    }
  }

  /** Viewport dimensions as `{width, height}`. */
  async getSize(): Promise<{ width: number; height: number } | null> {
    const script = ScriptBuilder.iife(`
            var vp = ${VIEWPORT_EXPR};
            if (!vp) return null;
            var r = vp.geometry;
            return {width: r.width, height: r.height};
        `);
    return (await this.client.execute(script)).value as { width: number; height: number } | null;
  }

  /**
   * Not supported — `Dz3DViewport` does not expose resize via DazScript.
   * Resize the DAZ Studio viewport window manually before calling {@link capture}.
   */
  setSize(_width: number, _height: number): never {
    throw new Error(
      "Viewport resize via DazScript is not supported. Resize the DAZ Studio viewport window manually.",
    );
  }

  /**
   * Capture the active 3D viewport to a PNG/JPEG file.
   *
   * Split into two script round-trips deliberately: every viewport-state
   * change this method makes to prepare the shot (toggling overlays,
   * deselecting, changing the backdrop) invalidates DAZ Studio's Iray
   * real-time preview and restarts its progressive convergence. A single
   * script that invalidates the preview and calls `captureImage()` on the
   * next line grabs the framebuffer at essentially sample 0-1 — confirmed
   * live to make fully-clothed figures look nude (clothing layers too
   * thin/transparent to resolve at that sample count). Waiting in this
   * method *before* calling a combined script wouldn't help, since the
   * invalidate-then-grab both happen inside one call with nothing outside
   * it to wait on — hence a real `convergenceWait` sleep between two
   * separate `execute()` calls: one to invalidate (and kick off a fresh
   * convergence pass), one to grab the now-converged frame and restore state.
   *
   * @param width,height Accepted for API compatibility but ignored — `Dz3DViewport` does not expose resize via DazScript.
   * @param hideOverlays When `true` (default), axes/floor/pose-tool/aspect-frame and the primary selection are hidden for the capture and restored after.
   * @param backdropColor Temporary `[r,g,b]` viewport background for the capture, restored after.
   * @param convergenceWait Seconds to sleep between the two passes (default `3.0`); `0` skips the wait (accepting a possibly-unconverged capture).
   */
  async capture(
    path: string,
    opts: {
      width?: number;
      height?: number;
      hideOverlays?: boolean;
      backdropColor?: [number, number, number];
      convergenceWait?: number;
    } = {},
  ): Promise<string> {
    const { hideOverlays = true, backdropColor, convergenceWait = 3.0 } = opts;
    const jsPath = ScriptBuilder.escapeString(path);

    const bgCaptureJs = backdropColor !== undefined ? "var prevBg = vp.background;" : "";
    let bgApplyJs = "";
    if (backdropColor !== undefined) {
      const [r, g, b] = backdropColor;
      const hex = `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b.toString(16).padStart(2, "0")}`;
      bgApplyJs = `vp.background = new QColor(${ScriptBuilder.escapeString(hex)});`;
    }
    const bgReturnField = backdropColor !== undefined ? ", bg: prevBg" : "";

    if (hideOverlays) {
      const prepareScript = ScriptBuilder.iife(`
                var vp = ${VIEWPORT_EXPR};
                if (!vp) return null;

                var prevAxes        = vp.axesOn;
                var prevFloor       = vp.floorStyle;
                var prevPose        = vp.showPoseTool;
                var prevAspect      = vp.aspectOn;
                var prevThirds      = vp.thirdsGuideOn;
                var prevToolBarMode = vp.toolBarMode;
                ${bgCaptureJs}

                var prevSelection = Scene.getPrimarySelection();
                var prevSelectionName = prevSelection ? prevSelection.getName() : null;
                var prevSelectionSkeletonName = null;
                if (prevSelection && prevSelection.isBoneSelectingNode && prevSelection.isBoneSelectingNode()) {
                    var _selSkel = prevSelection.getSkeleton ? prevSelection.getSkeleton() : null;
                    if (_selSkel) prevSelectionSkeletonName = _selSkel.getName();
                }
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
                ${bgApplyJs}

                Scene.setPrimarySelection(null);
                if (tnNode)  tnNode.setVisibleInViewport(false);
                if (envNode) envNode.setVisibleInViewport(false);

                vp.updateGL();

                return {
                    axesOn: prevAxes, floorStyle: prevFloor, showPoseTool: prevPose,
                    aspectOn: prevAspect, thirdsGuideOn: prevThirds, toolBarMode: prevToolBarMode,
                    selectionName: prevSelectionName,
                    selectionSkeletonName: prevSelectionSkeletonName,
                    tnVisible: prevTnVisible, envVisible: prevEnvVisible${bgReturnField}
                };
            `);
      const prevState = ((await this.client.execute(prepareScript)).value as Record<string, unknown>) ?? {};

      if (convergenceWait > 0) {
        await new Promise((resolve) => setTimeout(resolve, convergenceWait * 1000));
      }

      let restoreBgJs = "";
      if (backdropColor !== undefined && prevState.bg !== null && prevState.bg !== undefined) {
        const pb = prevState.bg as { r: number; g: number; b: number; a?: number };
        restoreBgJs = `vp.background = new QColor(${ScriptBuilder.serializeArg(Math.trunc(pb.r))}, ${ScriptBuilder.serializeArg(Math.trunc(pb.g))}, ${ScriptBuilder.serializeArg(Math.trunc(pb.b))}, ${ScriptBuilder.serializeArg(Math.trunc(pb.a ?? 255))});`;
      }

      // vp is deliberately re-fetched (not assumed available): it can become unavailable during the real
      // wall-clock convergenceWait sleep. Scene-level restoration always runs; only viewport-specific
      // properties and the capture itself are skipped if vp is gone.
      const finishScript = ScriptBuilder.iife(`
                var vp = ${VIEWPORT_EXPR};
                var prev = ${JSON.stringify(prevState)};
                var img = null;

                if (vp) {
                    vp.updateGL();
                    img = vp.captureImage();

                    vp.axesOn        = prev.axesOn;
                    vp.floorStyle    = prev.floorStyle;
                    vp.showPoseTool  = prev.showPoseTool;
                    vp.aspectOn      = prev.aspectOn;
                    vp.thirdsGuideOn = prev.thirdsGuideOn;
                    vp.toolBarMode   = prev.toolBarMode;
                    ${restoreBgJs}
                }

                var prevSel = null;
                if (prev.selectionName) {
                    prevSel = Scene.findNode(prev.selectionName);
                    if (!prevSel && prev.selectionSkeletonName) {
                        var _selSkel = Scene.findNode(prev.selectionSkeletonName);
                        if (_selSkel && _selSkel.findBone) prevSel = _selSkel.findBone(prev.selectionName);
                    }
                }
                Scene.setPrimarySelection(prevSel);
                var tnNode  = Scene.findNodeByLabel("Tonemapper Options");
                var envNode = Scene.findNodeByLabel("Environment Options");
                if (tnNode  && prev.tnVisible  !== null) tnNode.setVisibleInViewport(prev.tnVisible);
                if (envNode && prev.envVisible !== null) envNode.setVisibleInViewport(prev.envVisible);

                if (vp) vp.updateGL();

                if (!img) return null;
                img.save(${jsPath});
                return ${jsPath};
            `);
      const result = (await this.client.execute(finishScript)).value as string | null;
      return result ?? path;
    }

    const prepareScript = ScriptBuilder.iife(`
            var vp = ${VIEWPORT_EXPR};
            if (!vp) return null;
            ${bgCaptureJs}
            ${bgApplyJs}
            vp.updateGL();
            return {"ok": true${bgReturnField}};
        `);
    const prepResult = ((await this.client.execute(prepareScript)).value as Record<string, unknown>) ?? {};
    if (prepResult.ok && convergenceWait > 0) {
      await new Promise((resolve) => setTimeout(resolve, convergenceWait * 1000));
    }

    let restoreBgJs = "";
    if (backdropColor !== undefined && prepResult.bg !== null && prepResult.bg !== undefined) {
      const pb = prepResult.bg as { r: number; g: number; b: number; a?: number };
      restoreBgJs = `vp.background = new QColor(${ScriptBuilder.serializeArg(Math.trunc(pb.r))}, ${ScriptBuilder.serializeArg(Math.trunc(pb.g))}, ${ScriptBuilder.serializeArg(Math.trunc(pb.b))}, ${ScriptBuilder.serializeArg(Math.trunc(pb.a ?? 255))});`;
    }

    const finishScript = ScriptBuilder.iife(`
            var vp = ${VIEWPORT_EXPR};
            if (!vp) return null;
            vp.updateGL();
            var img = vp.captureImage();
            ${restoreBgJs}
            vp.updateGL();
            if (!img) return null;
            img.save(${jsPath});
            return ${jsPath};
        `);
    const result = (await this.client.execute(finishScript)).value as string | null;
    return result ?? path;
  }
}
