import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { UndoGroup, withUndo } from "../../src/undo.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}
afterEach(() => vi.unstubAllGlobals());
function stub() {
  const fetchMock = vi
    .fn()
    .mockImplementation(() =>
      Promise.resolve(jsonResponse({ success: true, result: null, output: [], request_id: "r", duration_ms: 0 })),
    );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function iife(body: string): string {
  return `(function(){\n${body}\n})()`;
}

describe("UndoGroup", () => {
  it("begin() calls beginUndo(), commit() calls acceptUndo(label)", async () => {
    const fetchMock = stub();
    const group = new UndoGroup(new DazClient({ token: "" }), "Move figure");
    await group.begin();
    await group.commit();
    const scripts = fetchMock.mock.calls.map((c) => JSON.parse(c[1].body as string).script);
    expect(scripts[0]).toBe(iife("beginUndo();"));
    expect(scripts[1]).toBe(iife('acceptUndo("Move figure");'));
  });

  it("cancel() calls cancelUndo()", async () => {
    const fetchMock = stub();
    const group = new UndoGroup(new DazClient({ token: "" }), "x");
    await group.cancel();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(iife("cancelUndo();"));
  });
});

describe("withUndo", () => {
  it("commits on success and returns fn's result", async () => {
    const fetchMock = stub();
    const client = new DazClient({ token: "" });
    const result = await withUndo(client, "Rotate arm", async () => 42);
    expect(result).toBe(42);
    const scripts = fetchMock.mock.calls.map((c) => JSON.parse(c[1].body as string).script);
    expect(scripts[0]).toBe(iife("beginUndo();"));
    expect(scripts[1]).toBe(iife('acceptUndo("Rotate arm");'));
  });

  it("cancels and rethrows when fn throws", async () => {
    const fetchMock = stub();
    const client = new DazClient({ token: "" });
    await expect(
      withUndo(client, "x", async () => {
        throw new Error("boom");
      }),
    ).rejects.toThrow("boom");
    const scripts = fetchMock.mock.calls.map((c) => JSON.parse(c[1].body as string).script);
    expect(scripts[0]).toBe(iife("beginUndo();"));
    expect(scripts[1]).toBe(iife("cancelUndo();"));
  });
});
