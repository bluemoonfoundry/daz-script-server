import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazTimeline } from "../../src/timeline.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}
afterEach(() => vi.unstubAllGlobals());
function stub(value: unknown) {
  const fetchMock = vi
    .fn()
    .mockResolvedValue(jsonResponse({ success: true, result: value, output: [], request_id: "r", duration_ms: 0 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
function scriptOf(fetchMock: ReturnType<typeof vi.fn>, callIndex = 0): string {
  return JSON.parse(fetchMock.mock.calls[callIndex][1].body as string).script;
}

describe("DazTimeline", () => {
  it("frame() reads Scene.getFrame()", async () => {
    const fetchMock = stub(12);
    const timeline = new DazTimeline(new DazClient({ token: "" }));
    expect(await timeline.frame()).toBe(12);
    expect(scriptOf(fetchMock)).toBe("(function(){\nreturn Scene.getFrame();\n})()");
  });

  it("setFrame() calls Scene.setFrame() with a truncated integer literal", async () => {
    const fetchMock = stub(null);
    const timeline = new DazTimeline(new DazClient({ token: "" }));
    await timeline.setFrame(42);
    expect(scriptOf(fetchMock)).toBe("(function(){\nScene.setFrame(42);\n})()");
  });

  it("setFrame() truncates a non-integer value via Math.trunc before serializing", async () => {
    const fetchMock = stub(null);
    const timeline = new DazTimeline(new DazClient({ token: "" }));
    await timeline.setFrame(42.9);
    expect(scriptOf(fetchMock)).toBe("(function(){\nScene.setFrame(42);\n})()");
  });

  it("time() reads Scene.getTime().valueOf()", async () => {
    const fetchMock = stub(1440);
    const timeline = new DazTimeline(new DazClient({ token: "" }));
    expect(await timeline.time()).toBe(1440);
    expect(scriptOf(fetchMock)).toBe("(function(){\nreturn Scene.getTime().valueOf();\n})()");
  });

  it("timeStep() reads Scene.getTimeStep()", async () => {
    const fetchMock = stub(4800);
    const timeline = new DazTimeline(new DazClient({ token: "" }));
    expect(await timeline.timeStep()).toBe(4800);
    expect(scriptOf(fetchMock)).toBe("(function(){\nreturn Scene.getTimeStep();\n})()");
  });

  it("frameRange() reads Scene.getAnimRange() start/end", async () => {
    const fetchMock = stub({ start: 0, end: 90 });
    const timeline = new DazTimeline(new DazClient({ token: "" }));
    expect(await timeline.frameRange()).toEqual({ start: 0, end: 90 });
    expect(scriptOf(fetchMock)).toBe(
      "(function(){\nreturn { start: Scene.getAnimRange().start, end: Scene.getAnimRange().end };\n})()",
    );
  });

  it("play() calls Scene.play()", async () => {
    const fetchMock = stub(null);
    const timeline = new DazTimeline(new DazClient({ token: "" }));
    await timeline.play();
    expect(scriptOf(fetchMock)).toBe("(function(){\nScene.play();\n})()");
  });

  it("pause() calls Scene.stop()", async () => {
    const fetchMock = stub(null);
    const timeline = new DazTimeline(new DazClient({ token: "" }));
    await timeline.pause();
    expect(scriptOf(fetchMock)).toBe("(function(){\nScene.stop();\n})()");
  });

  it("constructs a default client when none is provided", () => {
    expect(() => new DazTimeline()).not.toThrow();
  });
});
