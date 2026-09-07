import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazProperty } from "../../src/property.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubExecute(value: unknown): ReturnType<typeof vi.fn> {
  const fetchMock = vi
    .fn()
    .mockResolvedValue(jsonResponse({ success: true, result: value, output: [], request_id: "r1", duration_ms: 0 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("DazProperty", () => {
  it("constructor builds a findPropertyByLabel locator from the owner locator", async () => {
    const fetchMock = stubExecute(3);
    const client = new DazClient({ token: "" });
    const prop = new DazProperty(client, 'Scene.findNode("Genesis9")', "Scale");
    await prop.value();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar p = (function(){var obj = Scene.findNode("Genesis9");return obj ? obj.findPropertyByLabel("Scale") : null;})(); return p ? p.getValue() : null;\n})()',
    );
  });

  it("value getter/setter round-trip through getValue/setValue", async () => {
    const fetchMock = stubExecute(null);
    const client = new DazClient({ token: "" });
    const prop = DazProperty.fromLocator(client, "PLOC");
    await prop.setValue(2.5);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe("(function(){\nvar p = PLOC; if (p) p.setValue(2.5);\n})()");
  });

  it("rawValue reads getRawValue() when present, falling back to getValue()", async () => {
    const fetchMock = stubExecute(1.0);
    const client = new DazClient({ token: "" });
    const prop = DazProperty.fromLocator(client, "PLOC");
    await prop.rawValue();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\n" +
      "            var p = PLOC;\n" +
      "            if (!p) return null;\n" +
      '            return (typeof p.getRawValue === "function") ? p.getRawValue() : p.getValue();\n' +
      "})()",
    );
  });

  it("setRawValue uses setRawValue when available, falling back to setValue", async () => {
    const fetchMock = stubExecute(null);
    const client = new DazClient({ token: "" });
    const prop = DazProperty.fromLocator(client, "PLOC");
    await prop.setRawValue(1.5);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\n" +
      "            var p = PLOC;\n" +
      "            if (!p) return;\n" +
      '            if (typeof p.setRawValue === "function") { p.setRawValue(1.5); }\n' +
      "            else { p.setValue(1.5); }\n" +
      "})()",
    );
  });

  it("label reads the property's display label", async () => {
    const fetchMock = stubExecute("Scale");
    const client = new DazClient({ token: "" });
    const prop = DazProperty.fromLocator(client, "PLOC");
    const result = await prop.label();
    expect(result).toBe("Scale");
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe("(function(){\nvar p = PLOC; return p ? p.getLabel() : null;\n})()");
  });

  it("min returns the property's minimum value or null if not applicable", async () => {
    const fetchMock = stubExecute(0);
    const client = new DazClient({ token: "" });
    const prop = DazProperty.fromLocator(client, "PLOC");
    const result = await prop.min();
    expect(result).toBe(0);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe("(function(){\nvar p = PLOC; return (p && p.getMin) ? p.getMin() : null;\n})()");
  });

  it("max returns the property's maximum value or null if not applicable", async () => {
    const fetchMock = stubExecute(100);
    const client = new DazClient({ token: "" });
    const prop = DazProperty.fromLocator(client, "PLOC");
    const result = await prop.max();
    expect(result).toBe(100);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe("(function(){\nvar p = PLOC; return (p && p.getMax) ? p.getMax() : null;\n})()");
  });

  it("setKey writes via setDoubleValue, never setKey/addKey", async () => {
    const fetchMock = stubExecute(null);
    const client = new DazClient({ token: "" });
    const prop = DazProperty.fromLocator(client, "PLOC");
    await prop.setKey(240, 0.5);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\n" +
      "            var p = PLOC;\n" +
      "            if (p && p.setDoubleValue) p.setDoubleValue(240, 0.5);\n" +
      "})()",
    );
  });

  it("isAnimated is computed as getNumKeys() > 0, not a nonexistent isAnimated()", async () => {
    const fetchMock = stubExecute(true);
    const client = new DazClient({ token: "" });
    const prop = DazProperty.fromLocator(client, "PLOC");
    await prop.isAnimated();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\n" +
      "            var p = PLOC;\n" +
      "            if (!p || !p.getNumKeys) return null;\n" +
      "            return p.getNumKeys() > 0;\n" +
      "})()",
    );
  });

  it("getKeys returns array of {time, value} for all keyframes", async () => {
    const mockKeys = [
      { time: 0, value: 0.5 },
      { time: 240, value: 0.8 },
    ];
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ success: true, result: mockKeys, output: [], request_id: "r1", duration_ms: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const prop = DazProperty.fromLocator(client, "PLOC");
    const result = await prop.getKeys();
    expect(result).toEqual(mockKeys);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\n" +
      "            var p = PLOC;\n" +
      "            if (!p || !p.getNumKeys) return [];\n" +
      "            var n = p.getNumKeys();\n" +
      "            var keys = [];\n" +
      "            for (var i = 0; i < n; i++) {\n" +
      "                var t = p.getKeyTime(i);\n" +
      "                keys.push({ time: t.valueOf(), value: p.getDoubleValue(t) });\n" +
      "            }\n" +
      "            return keys;\n" +
      "})()",
    );
  });

  it("removeKey removes a single keyframe at the given time", async () => {
    const fetchMock = stubExecute(null);
    const client = new DazClient({ token: "" });
    const prop = DazProperty.fromLocator(client, "PLOC");
    await prop.removeKey(240);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\n" +
      "            var p = PLOC;\n" +
      "            if (p && p.deleteKeys) p.deleteKeys(new DzTimeRange(240, 240));\n" +
      "})()",
    );
  });

  it("clearKeys removes all keyframes from the property's animation curve", async () => {
    const fetchMock = stubExecute(null);
    const client = new DazClient({ token: "" });
    const prop = DazProperty.fromLocator(client, "PLOC");
    await prop.clearKeys();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\n" +
      "            var p = PLOC;\n" +
      "            if (p && p.deleteAllKeys) p.deleteAllKeys();\n" +
      "})()",
    );
  });

  it("value getter reads via getValue", async () => {
    const fetchMock = stubExecute(5.0);
    const client = new DazClient({ token: "" });
    const prop = DazProperty.fromLocator(client, "PLOC");
    const result = await prop.value();
    expect(result).toBe(5.0);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe("(function(){\nvar p = PLOC; return p ? p.getValue() : null;\n})()");
  });
});
