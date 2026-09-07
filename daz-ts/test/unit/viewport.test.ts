import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazViewport } from "../../src/viewport.js";
import { ScriptBuilder } from "../../src/scriptBuilder.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}
afterEach(() => vi.unstubAllGlobals());
function stubSeq(...values: unknown[]) {
  const fetchMock = vi.fn();
  for (const v of values) fetchMock.mockResolvedValueOnce(jsonResponse({ success: true, result: v, output: [], request_id: "r", duration_ms: 0 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
function scriptOf(fetchMock: ReturnType<typeof vi.fn>, callIndex = 0): string {
  return JSON.parse(fetchMock.mock.calls[callIndex][1].body as string).script;
}
function iife(body: string): string {
  return `(function(){\n${body}\n})()`;
}

describe("DazViewport basics", () => {
  it("isAvailable() checks if an active 3D viewport is accessible", async () => {
    const fetchMock = stubSeq(true);
    const vp = new DazViewport(new DazClient({ token: "" }));
    const available = await vp.isAvailable();
    expect(available).toBe(true);
    expect(scriptOf(fetchMock)).toBe(
      iife("var vp = MainWindow.getViewportMgr().getActiveViewport().get3DViewport(); return (vp !== null && vp !== undefined);"),
    );
  });

  it("drawStyle() returns the current draw style label", async () => {
    const fetchMock = stubSeq("NVIDIA Iray");
    const vp = new DazViewport(new DazClient({ token: "" }));
    const style = await vp.drawStyle();
    expect(style).toBe("NVIDIA Iray");
    expect(scriptOf(fetchMock)).toBe(
      iife("var vp = MainWindow.getViewportMgr().getActiveViewport().get3DViewport(); if (!vp) return null; return vp.getUserDrawStyle();"),
    );
  });

  it("getSize() returns viewport dimensions", async () => {
    const fetchMock = stubSeq({ width: 800, height: 600 });
    const vp = new DazViewport(new DazClient({ token: "" }));
    const size = await vp.getSize();
    expect(size).toEqual({ width: 800, height: 600 });
    expect(scriptOf(fetchMock)).toBe(
      iife(`
            var vp = MainWindow.getViewportMgr().getActiveViewport().get3DViewport();
            if (!vp) return null;
            var r = vp.geometry;
            return {width: r.width, height: r.height};
        `),
    );
  });

  it("setDrawStyle resolves a friendly alias ('iray' -> 'NVIDIA Iray') before sending", async () => {
    const fetchMock = stubSeq({ before: "Wireframe", after: "NVIDIA Iray" });
    const vp = new DazViewport(new DazClient({ token: "" }));
    await vp.setDrawStyle("iray");
    expect(scriptOf(fetchMock)).toBe(
      iife(`
            var vp = MainWindow.getViewportMgr().getActiveViewport().get3DViewport();
            if (!vp) return null;
            var before = vp.getUserDrawStyle();
            vp.setUserDrawStyle("NVIDIA Iray");
            return {before: before, after: vp.getUserDrawStyle()};
        `),
    );
  });

  it("setDrawStyle passes an unrecognized raw label straight through", async () => {
    const fetchMock = stubSeq({ before: "X", after: "Custom Style" });
    const vp = new DazViewport(new DazClient({ token: "" }));
    await vp.setDrawStyle("Custom Style");
    expect(scriptOf(fetchMock)).toBe(
      iife(`
            var vp = MainWindow.getViewportMgr().getActiveViewport().get3DViewport();
            if (!vp) return null;
            var before = vp.getUserDrawStyle();
            vp.setUserDrawStyle("Custom Style");
            return {before: before, after: vp.getUserDrawStyle()};
        `),
    );
  });

  it("setDrawStyle throws ValueError-equivalent when the style silently didn't change and wasn't already applied", async () => {
    stubSeq({ before: "Wireframe", after: "Wireframe" });
    const vp = new DazViewport(new DazClient({ token: "" }));
    await expect(vp.setDrawStyle("not_a_real_style")).rejects.toThrow(/Unknown viewport draw style/);
  });

  it("setSize throws — Dz3DViewport doesn't expose resize via DazScript", () => {
    const vp = new DazViewport(new DazClient({ token: "" }));
    expect(() => vp.setSize(800, 600)).toThrow(/not supported/);
  });
});

describe("DazViewport.capture", () => {
  it("hideOverlays (default) issues two script calls: prepare (returns prior state) then finish (captures and restores)", async () => {
    const fetchMock = vi.fn();
    const prevState = {
      axesOn: true, floorStyle: 1, showPoseTool: false, aspectOn: true, thirdsGuideOn: false, toolBarMode: 0,
      selectionName: null, selectionSkeletonName: null, tnVisible: true, envVisible: true,
    };
    fetchMock.mockResolvedValueOnce(jsonResponse({ success: true, result: prevState, output: [], request_id: "r1", duration_ms: 0 }));
    fetchMock.mockResolvedValueOnce(jsonResponse({ success: true, result: "C:/out.png", output: [], request_id: "r2", duration_ms: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    const vp = new DazViewport(new DazClient({ token: "" }));
    const path = await vp.capture("C:/out.png", { convergenceWait: 0 });

    expect(path).toBe("C:/out.png");
    expect(fetchMock).toHaveBeenCalledTimes(2);

    // Construct expected scripts using same approach as implementation
    const VIEWPORT_EXPR = "MainWindow.getViewportMgr().getActiveViewport().get3DViewport()";
    const bgCaptureJs = "";
    const bgApplyJs = "";
    const bgReturnField = "";

    const expectedPrepareScript = ScriptBuilder.iife(`
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

    expect(scriptOf(fetchMock, 0)).toBe(expectedPrepareScript);

    const jsPath = ScriptBuilder.escapeString("C:/out.png");
    const restoreBgJs = "";
    const expectedFinishScript = ScriptBuilder.iife(`
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

    expect(scriptOf(fetchMock, 1)).toBe(expectedFinishScript);
  });

  it("hideOverlays: false skips the selection/overlay bookkeeping and still returns the saved path", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce(jsonResponse({ success: true, result: { ok: true }, output: [], request_id: "r1", duration_ms: 0 }));
    fetchMock.mockResolvedValueOnce(jsonResponse({ success: true, result: "C:/out.png", output: [], request_id: "r2", duration_ms: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    const vp = new DazViewport(new DazClient({ token: "" }));
    const path = await vp.capture("C:/out.png", { hideOverlays: false, convergenceWait: 0 });
    expect(path).toBe("C:/out.png");

    // Construct expected scripts using same approach as implementation
    const VIEWPORT_EXPR = "MainWindow.getViewportMgr().getActiveViewport().get3DViewport()";
    const bgCaptureJs = "";
    const bgApplyJs = "";
    const bgReturnField = "";

    const expectedPrepareScript = ScriptBuilder.iife(`
            var vp = ${VIEWPORT_EXPR};
            if (!vp) return null;
            ${bgCaptureJs}
            ${bgApplyJs}
            vp.updateGL();
            return {"ok": true${bgReturnField}};
        `);

    expect(scriptOf(fetchMock, 0)).toBe(expectedPrepareScript);

    const jsPath = ScriptBuilder.escapeString("C:/out.png");
    const restoreBgJs2 = "";
    const expectedFinishScript = ScriptBuilder.iife(`
            var vp = ${VIEWPORT_EXPR};
            if (!vp) return null;
            vp.updateGL();
            var img = vp.captureImage();
            ${restoreBgJs2}
            vp.updateGL();
            if (!img) return null;
            img.save(${jsPath});
            return ${jsPath};
        `);

    expect(scriptOf(fetchMock, 1)).toBe(expectedFinishScript);
  });

  it("falls back to the input path when the final script returns null (viewport became unavailable)", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce(jsonResponse({ success: true, result: null, output: [], request_id: "r1", duration_ms: 0 }));
    fetchMock.mockResolvedValueOnce(jsonResponse({ success: true, result: null, output: [], request_id: "r2", duration_ms: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    const vp = new DazViewport(new DazClient({ token: "" }));
    expect(await vp.capture("C:/out.png", { convergenceWait: 0 })).toBe("C:/out.png");
  });
});
