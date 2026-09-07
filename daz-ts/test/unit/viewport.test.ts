import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazViewport } from "../../src/viewport.js";

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
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        success: true,
        result: {
          axesOn: true, floorStyle: 1, showPoseTool: false, aspectOn: true, thirdsGuideOn: false, toolBarMode: 0,
          selectionName: null, selectionSkeletonName: null, tnVisible: true, envVisible: true,
        },
        output: [], request_id: "r1", duration_ms: 0,
      }),
    );
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ success: true, result: "C:/out.png", output: [], request_id: "r2", duration_ms: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const vp = new DazViewport(new DazClient({ token: "" }));
    const path = await vp.capture("C:/out.png", { convergenceWait: 0 });

    expect(path).toBe("C:/out.png");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const prepareScript = scriptOf(fetchMock, 0);
    const finishScript = scriptOf(fetchMock, 1);
    expect(prepareScript).toContain("vp.axesOn        = false;");
    expect(finishScript).toContain("img = vp.captureImage();");
    expect(finishScript).toContain("prev.axesOn");
  });

  it("hideOverlays: false skips the selection/overlay bookkeeping and still returns the saved path", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce(jsonResponse({ success: true, result: { ok: true }, output: [], request_id: "r1", duration_ms: 0 }));
    fetchMock.mockResolvedValueOnce(jsonResponse({ success: true, result: "C:/out.png", output: [], request_id: "r2", duration_ms: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    const vp = new DazViewport(new DazClient({ token: "" }));
    const path = await vp.capture("C:/out.png", { hideOverlays: false, convergenceWait: 0 });
    expect(path).toBe("C:/out.png");
    const prepareScript = scriptOf(fetchMock, 0);
    expect(prepareScript).not.toContain("Scene.setPrimarySelection(null)");
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
