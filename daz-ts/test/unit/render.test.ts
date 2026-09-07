import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { RenderError } from "../../src/exceptions.js";
import { DazRenderSettings } from "../../src/render.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}
afterEach(() => vi.unstubAllGlobals());
function stubSeq(...values: unknown[]) {
  const fetchMock = vi.fn();
  for (const v of values) {
    fetchMock.mockResolvedValueOnce(jsonResponse({ success: true, result: v, output: [], request_id: "r", duration_ms: 0 }));
  }
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
function scriptOf(fetchMock: ReturnType<typeof vi.fn>, callIndex = 0): string {
  return JSON.parse(fetchMock.mock.calls[callIndex][1].body as string).script;
}
function iife(body: string): string {
  return `(function(){\n${body}\n})()`;
}

describe("DazRenderSettings availability/state", () => {
  it("isAvailable() checks App.getRenderMgr()", async () => {
    const fetchMock = stubSeq(true);
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    expect(await rs.isAvailable()).toBe(true);
    expect(scriptOf(fetchMock)).toBe(
      iife(`
            var mgr = App.getRenderMgr();
            return (mgr !== null && mgr !== undefined);
        `),
    );
  });

  it("isRendering() reads mgr.isRendering()", async () => {
    const fetchMock = stubSeq(false);
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    expect(await rs.isRendering()).toBe(false);
    expect(scriptOf(fetchMock)).toBe(
      iife(`
            var mgr = App.getRenderMgr();
            if (!mgr) return false;
            return mgr.isRendering();
        `),
    );
  });

  it("hasRender() reads mgr.hasRender()", async () => {
    const fetchMock = stubSeq(true);
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    expect(await rs.hasRender()).toBe(true);
    expect(scriptOf(fetchMock)).toBe(
      iife(`
            var mgr = App.getRenderMgr();
            if (!mgr) return false;
            return mgr.hasRender();
        `),
    );
  });
});

describe("DazRenderSettings resolution/output/gamma/doubleSided", () => {
  it("resolution() reads {width, height} from imageSize", async () => {
    const fetchMock = stubSeq({ width: 1920, height: 1080 });
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    expect(await rs.resolution()).toEqual({ width: 1920, height: 1080 });
    expect(scriptOf(fetchMock)).toBe(
      iife(`
            var mgr = App.getRenderMgr();
            if (!mgr) return null;
            var opts = mgr.getRenderOptions();
            var sz = opts.imageSize;
            return {width: sz.width, height: sz.height};
        `),
    );
  });

  it("setResolution() truncates to int and builds new QSize(w, h)", async () => {
    const fetchMock = stubSeq(null);
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    await rs.setResolution(1920.7, 1080.2);
    expect(scriptOf(fetchMock)).toBe(
      iife(`
            var mgr = App.getRenderMgr();
            if (!mgr) return;
            var opts = mgr.getRenderOptions();
            opts.imageSize = new QSize(1920, 1080);
            opts.applyChanges();
        `),
    );
  });

  it("outputPath()/setOutputPath() read/write renderImgFilename", async () => {
    const fetchMock = stubSeq("C:\\out.png", null);
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    expect(await rs.outputPath()).toBe("C:\\out.png");
    await rs.setOutputPath("C:\\new.png");
    expect(scriptOf(fetchMock, 1)).toBe(
      iife(`
            var mgr = App.getRenderMgr();
            if (!mgr) return;
            var opts = mgr.getRenderOptions();
            opts.renderImgFilename = "C:\\\\new.png";
            opts.applyChanges();
        `),
    );
  });

  it("gamma()/setGamma() read/write opts.gamma", async () => {
    const fetchMock = stubSeq(2.2, null);
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    expect(await rs.gamma()).toBe(2.2);
    await rs.setGamma(2.4);
    expect(scriptOf(fetchMock, 1)).toBe(
      iife(`
            var mgr = App.getRenderMgr();
            if (!mgr) return;
            var opts = mgr.getRenderOptions();
            opts.gamma = 2.4;
            opts.applyChanges();
        `),
    );
  });

  it("doubleSided()/setDoubleSided() read/write opts.doubleSided", async () => {
    const fetchMock = stubSeq(null, null);
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    expect(await rs.doubleSided()).toBeNull();
    await rs.setDoubleSided(true);
    expect(scriptOf(fetchMock, 1)).toBe(
      iife(`
            var mgr = App.getRenderMgr();
            if (!mgr) return;
            var opts = mgr.getRenderOptions();
            opts.doubleSided = true;
            opts.applyChanges();
        `),
    );
  });
});

describe("DazRenderSettings Iray quality", () => {
  it("maxSamples()/setMaxSamples() proxy through the active renderer's property holder", async () => {
    const fetchMock = stubSeq(500, null);
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    expect(await rs.maxSamples()).toBe(500);
    await rs.setMaxSamples(1500);
    expect(scriptOf(fetchMock, 1)).toBe(
      iife(`
            var holder = App.getRenderMgr().getActiveRenderer().getPropertyHolder();
            if (!holder) return;
            var p = holder.findProperty("Max Samples");
            if (p) p.setValue(1500);
        `),
    );
  });

  it("setQualityPreset() writes Max Samples/Max Time/Rendering Quality Enable/Rendering Quality", async () => {
    const fetchMock = stubSeq(null, null, null, null);
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    await rs.setQualityPreset("good");
    expect(scriptOf(fetchMock, 0)).toContain('"Max Samples"');
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string).script).toContain("p.setValue(1500)");
    expect(JSON.parse(fetchMock.mock.calls[1][1].body as string).script).toContain("p.setValue(3600)");
    expect(JSON.parse(fetchMock.mock.calls[2][1].body as string).script).toContain("p.setValue(true)");
    expect(JSON.parse(fetchMock.mock.calls[3][1].body as string).script).toContain("p.setValue(1)");
  });

  it("setQualityPreset() throws on an unknown preset name without calling execute", async () => {
    const fetchMock = stubSeq();
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    await expect(rs.setQualityPreset("ultra")).rejects.toThrow(/Unknown quality preset/);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("DazRenderSettings render()", () => {
  it("renders with the active viewport camera by default and reports success from renderFinished", async () => {
    const fetchMock = stubSeq({ success: true, output_path: "C:\\out.png" });
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    const outcome = await rs.render();
    expect(outcome).toEqual({ success: true, outputPath: "C:\\out.png" });
    const script = scriptOf(fetchMock);
    expect(script).toContain("var cam = MainWindow.getViewportMgr().getActiveViewport().get3DViewport().getCamera();");
    expect(script).toContain('opts.renderImgToId = DzRenderOptions.DirectToFile;');
  });

  it("resolves the camera via findCameraByLabel when cameraLabel is given", async () => {
    const fetchMock = stubSeq({ success: true, output_path: "C:\\out.png" });
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    await rs.render({ cameraLabel: "Main Camera" });
    expect(scriptOf(fetchMock)).toContain('var cam = Scene.findCameraByLabel("Main Camera");');
  });

  it("resolves the camera via findCamera when cameraName is given", async () => {
    const fetchMock = stubSeq({ success: true, output_path: "C:\\out.png" });
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    await rs.render({ cameraName: "Camera1" });
    expect(scriptOf(fetchMock)).toContain('var cam = Scene.findCamera("Camera1");');
  });

  it("throws when both cameraName and cameraLabel are given, without calling execute", async () => {
    const fetchMock = stubSeq();
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    await expect(rs.render({ cameraName: "A", cameraLabel: "B" })).rejects.toThrow(
      "Pass at most one of cameraName or cameraLabel",
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("reports failure when renderFinished never fires success", async () => {
    const fetchMock = stubSeq({ success: false, output_path: "C:\\out.png" });
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    const outcome = await rs.render();
    expect(outcome).toEqual({ success: false, outputPath: "C:\\out.png" });
  });

  it("renderAndWait() is an alias for render()", async () => {
    const fetchMock = stubSeq({ success: true, output_path: "C:\\out.png" });
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    const outcome = await rs.renderAndWait();
    expect(outcome).toEqual({ success: true, outputPath: "C:\\out.png" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("DazRenderSettings canvases", () => {
  it("listCanvases() maps canvas definitions", async () => {
    const fetchMock = stubSeq([{ name: "Canvas1", canvasType: "Depth", index: 0 }]);
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    expect(await rs.listCanvases()).toEqual([{ name: "Canvas1", canvasType: "Depth", index: 0 }]);
    expect(scriptOf(fetchMock)).toContain("holder.getNumCanvasDefinitions()");
  });

  it("addCanvas() returns the resulting canvas", async () => {
    const fetchMock = stubSeq({ name: "Canvas1", canvasType: "Depth", index: 0 });
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    const canvas = await rs.addCanvas("Canvas1", "Depth");
    expect(canvas).toEqual({ name: "Canvas1", canvasType: "Depth", index: 0 });
    expect(scriptOf(fetchMock)).toContain('holder.findCanvasDefinition("Canvas1", true)');
  });

  it("addCanvas() throws RenderError when the holder is unavailable", async () => {
    const fetchMock = stubSeq(null);
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    await expect(rs.addCanvas("Canvas1", "Depth")).rejects.toThrow(RenderError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("removeCanvas() returns whether a canvas was found and removed", async () => {
    const fetchMock = stubSeq(true);
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    expect(await rs.removeCanvas("Canvas1")).toBe(true);
    expect(scriptOf(fetchMock)).toContain('holder.findCanvasDefinition("Canvas1", false)');
  });

  it("canvasOutputPaths() derives <dir>/<basename>_canvases/<basename>-<name>-<type>.exr per canvas", async () => {
    const fetchMock = stubSeq([
      { name: "Canvas1", canvasType: "Depth", index: 0 },
      { name: "Canvas2", canvasType: "MaterialID", index: 1 },
    ]);
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    const paths = await rs.canvasOutputPaths("C:\\renders\\shot01.png");
    expect(paths).toEqual({
      Canvas1: "C:\\renders\\shot01_canvases\\shot01-Canvas1-Depth.exr",
      Canvas2: "C:\\renders\\shot01_canvases\\shot01-Canvas2-MaterialID.exr",
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("canvasOutputPaths() handles a bare filename with no directory", async () => {
    const fetchMock = stubSeq([{ name: "Canvas1", canvasType: "Beauty", index: 0 }]);
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    const paths = await rs.canvasOutputPaths("out.png");
    expect(paths).toEqual({ Canvas1: "out_canvases/out-Canvas1-Beauty.exr" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("DazRenderSettings engine selection", () => {
  it("activeEngine() maps DzIrayRenderer to 'iray'", async () => {
    const fetchMock = stubSeq("DzIrayRenderer");
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    expect(await rs.activeEngine()).toBe("iray");
    expect(scriptOf(fetchMock)).toContain("if (opts.renderType === opts.ScreenShot) return \"viewport\";");
  });

  it("activeEngine() returns null when the render manager is unavailable", async () => {
    stubSeq(null);
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    expect(await rs.activeEngine()).toBeNull();
  });

  it("activeEngine() falls back to the raw class name for an unmapped renderer", async () => {
    stubSeq("DzSomeOtherRenderer");
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    expect(await rs.activeEngine()).toBe("DzSomeOtherRenderer");
  });

  it("setActiveEngine('viewport') sets renderType to ScreenShot without a renderer lookup", async () => {
    const fetchMock = stubSeq(null);
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    await rs.setActiveEngine("viewport");
    expect(scriptOf(fetchMock)).toContain("opts.renderType = opts.ScreenShot;");
    expect(scriptOf(fetchMock)).toContain('MainWindow.getPaneMgr().findPane("DzRenderSettingsPane")');
  });

  it("setActiveEngine('iray') looks up and activates the DzIrayRenderer", async () => {
    const fetchMock = stubSeq(true);
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    await rs.setActiveEngine("iray");
    expect(scriptOf(fetchMock)).toContain('mgr.findRenderer("DzIrayRenderer")');
  });

  it("setActiveEngine() throws RenderError when the renderer is not found", async () => {
    const fetchMock = stubSeq(false);
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    await expect(rs.setActiveEngine("filament")).rejects.toThrow(RenderError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("renderEngineState() normalizes a verified_iray readback", async () => {
    stubSeq({
      read_schema: 1,
      ok: true,
      reason: null,
      render_type: 2,
      active_renderer_class: "DzIrayRenderer",
      active_renderer_name: "NVIDIA Iray",
    });
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    const state = await rs.renderEngineState();
    expect(state.status).toBe("verified_iray");
    expect(state.engine).toBe("iray");
  });

  it("renderEngineState() reports 'unavailable' when the render manager can't be reached", async () => {
    stubSeq({
      read_schema: 1,
      ok: false,
      reason: "render_manager_unavailable",
      render_type: null,
      active_renderer_class: null,
      active_renderer_name: null,
    });
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    const state = await rs.renderEngineState();
    expect(state.status).toBe("unavailable");
    expect(state.reason).toBe("render_manager_unavailable");
  });

  it("setRenderEngine() resolves successfully on a matching readback", async () => {
    const fetchMock = stubSeq({
      mutation_schema: 1,
      ok: true,
      requested_engine: "iray",
      persisted: true,
      reason: null,
      readback: {
        read_schema: 1,
        ok: true,
        reason: null,
        render_type: 2,
        active_renderer_class: "DzIrayRenderer",
        active_renderer_name: "NVIDIA Iray",
      },
    });
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    const result = await rs.setRenderEngine("iray");
    expect(result.success).toBe(true);
    expect(result.persisted).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("setRenderEngine() throws RenderError when the readback doesn't match what was requested", async () => {
    stubSeq({
      mutation_schema: 1,
      ok: false,
      requested_engine: "iray",
      persisted: false,
      reason: "readback_mismatch",
      readback: {
        read_schema: 1,
        ok: true,
        reason: null,
        render_type: 0,
        active_renderer_class: null,
        active_renderer_name: null,
      },
    });
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    await expect(rs.setRenderEngine("iray")).rejects.toThrow(RenderError);
  });

  it("setRenderEngine() rejects an unknown engine name without calling execute", async () => {
    const fetchMock = stubSeq();
    const rs = new DazRenderSettings(new DazClient({ token: "" }));
    await expect(rs.setRenderEngine("filament")).rejects.toThrow(/Unknown render engine/);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
