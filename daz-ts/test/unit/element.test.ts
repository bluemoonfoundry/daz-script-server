import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazElement } from "../../src/element.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DazElement", () => {
  it("getProperty builds an IIFE that looks up findPropertyByLabel and returns its value", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ success: true, result: 42, output: [], request_id: "r1", duration_ms: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const el = new DazElement(client, "Scene.findNode(\"Genesis9\")");
    const result = await el.getProperty("Scale");

    expect(result).toBe(42);
    const [, init] = fetchMock.mock.calls[0];
    const script = JSON.parse(init.body as string).script;
    expect(script).toBe(
      '(function(){\n' +
      '            var obj = Scene.findNode("Genesis9");\n' +
      '            if (!obj) return null;\n' +
      '            var prop = obj.findPropertyByLabel("Scale");\n' +
      '            if (!prop) return null;\n' +
      '            return prop.getValue();\n' +
      '        \n})()'
    );
  });

  it("setProperty serializes the value via ScriptBuilder.serializeArg", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ success: true, result: null, output: [], request_id: "r2", duration_ms: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const el = new DazElement(client, "Scene.findNode(\"Genesis9\")");
    await el.setProperty("Scale", 1.5);

    const [, init] = fetchMock.mock.calls[0];
    const script = JSON.parse(init.body as string).script;
    expect(script).toContain('prop.setValue(1.5);');
    expect(script).toContain('findPropertyByLabel("Scale")');
  });

  it("className returns null when the locator resolves to nothing", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ success: true, result: null, output: [], request_id: "r3", duration_ms: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const el = new DazElement(client, "Scene.findNode(\"Missing\")");
    expect(await el.className()).toBeNull();
    const [, init] = fetchMock.mock.calls[0];
    const script = JSON.parse(init.body as string).script;
    expect(script).toBe('(function(){\nvar obj = Scene.findNode("Missing"); return obj ? obj.className() : null;\n})()');
  });
});
