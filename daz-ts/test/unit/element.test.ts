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

  it("setProperty serializes the value via ScriptBuilder.serializeArg and builds exact IIFE", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ success: true, result: null, output: [], request_id: "r2", duration_ms: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const el = new DazElement(client, "Scene.findNode(\"Genesis9\")");
    await el.setProperty("Scale", 1.5);

    const [, init] = fetchMock.mock.calls[0];
    const script = JSON.parse(init.body as string).script;
    expect(script).toBe(
      '(function(){\n' +
      '            var obj = Scene.findNode("Genesis9");\n' +
      '            if (!obj) return {"error": "not_found"};\n' +
      '            var prop = obj.findPropertyByLabel("Scale");\n' +
      '            if (!prop) return {"error": "property_not_found"};\n' +
      '            prop.setValue(1.5);\n' +
      '            return {"success": true};\n' +
      '        \n})()'
    );
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

  it("setProperties serializes object data via JSON.stringify and returns success dict", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ success: true, result: { Scale: true, XRotate: false }, output: [], request_id: "r4", duration_ms: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const el = new DazElement(client, "Scene.findNode(\"Figure\")");
    const result = await el.setProperties({ Scale: 2.0, XRotate: 45.0 });

    expect(result).toEqual({ Scale: true, XRotate: false });
    const [, init] = fetchMock.mock.calls[0];
    const script = JSON.parse(init.body as string).script;
    expect(script).toBe(
      '(function(){\n' +
      '            var obj = Scene.findNode("Figure");\n' +
      '            if (!obj) return null;\n' +
      '            var _data = {"Scale":2,"XRotate":45};\n' +
      '            var _result = {};\n' +
      '            for (var _label in _data) {\n' +
      '                if (!_data.hasOwnProperty(_label)) continue;\n' +
      '                var prop = obj.findPropertyByLabel(_label);\n' +
      '                if (prop) {\n' +
      '                    prop.setValue(_data[_label]);\n' +
      '                    _result[_label] = true;\n' +
      '                } else {\n' +
      '                    _result[_label] = false;\n' +
      '                }\n' +
      '            }\n' +
      '            return _result;\n' +
      '        \n})()'
    );
  });

  it("listProperties returns metadata array with label/name/type for each property", async () => {
    const mockProps = [
      { label: "X Position", name: "xpos", type: "DzNumericProperty" },
      { label: "Y Position", name: "ypos", type: "DzNumericProperty" },
      { label: "Visibility", name: "visible", type: "DzBoolProperty" },
    ];
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ success: true, result: mockProps, output: [], request_id: "r5", duration_ms: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const el = new DazElement(client, "Scene.findNode(\"Bone\")");
    const result = await el.listProperties();

    expect(result).toEqual(mockProps);
    const [, init] = fetchMock.mock.calls[0];
    const script = JSON.parse(init.body as string).script;
    expect(script).toBe(
      '(function(){\n' +
      '            var obj = Scene.findNode("Bone");\n' +
      '            if (!obj) return null;\n' +
      '            var result = [];\n' +
      '            for (var i = 0; i < obj.getNumProperties(); i++) {\n' +
      '                var p = obj.getProperty(i);\n' +
      '                result.push({"label": p.getLabel(), "name": p.getName(), "type": p.className()});\n' +
      '            }\n' +
      '            return result;\n' +
      '        \n})()'
    );
  });

  it("numericProperties filters and returns only numeric properties as dict", async () => {
    const mockNumeric = { "X Position": 10.5, "Y Position": 20.0, "Z Position": 30.5 };
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ success: true, result: mockNumeric, output: [], request_id: "r6", duration_ms: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const el = new DazElement(client, "Scene.findNode(\"Bone\")");
    const result = await el.numericProperties();

    expect(result).toEqual(mockNumeric);
    const [, init] = fetchMock.mock.calls[0];
    const script = JSON.parse(init.body as string).script;
    expect(script).toBe(
      '(function(){\n' +
      '            var obj = Scene.findNode("Bone");\n' +
      '            if (!obj) return null;\n' +
      '            var result = {};\n' +
      '            for (var i = 0; i < obj.getNumProperties(); i++) {\n' +
      '                var p = obj.getProperty(i);\n' +
      '                if (p.inherits("DzNumericProperty")) {\n' +
      '                    result[p.getLabel()] = p.getValue();\n' +
      '                }\n' +
      '            }\n' +
      '            return result;\n' +
      '        \n})()'
    );
  });

  it("snapshot reads multiple properties in one call and caches them", async () => {
    const mockSnapshot = { Scale: 1.5, XRotate: 0.0, Visibility: true };
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ success: true, result: mockSnapshot, output: [], request_id: "r7", duration_ms: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const el = new DazElement(client, "Scene.findNode(\"Figure\")");
    const result = await el.snapshot(["Scale", "XRotate", "Visibility"]);

    expect(result).toEqual(mockSnapshot);
    const [, init] = fetchMock.mock.calls[0];
    const script = JSON.parse(init.body as string).script;
    expect(script).toBe(
      '(function(){\n' +
      '            var obj = Scene.findNode("Figure");\n' +
      '            if (!obj) return null;\n' +
      '            var _fields = ["Scale","XRotate","Visibility"];\n' +
      '            var _result = {};\n' +
      '            for (var i = 0; i < _fields.length; i++) {\n' +
      '                var prop = obj.findPropertyByLabel(_fields[i]);\n' +
      '                _result[_fields[i]] = prop ? prop.getValue() : null;\n' +
      '            }\n' +
      '            return _result;\n' +
      '        \n})()'
    );
  });

  it("refresh clears the cache so next snapshot re-fetches", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ success: true, result: { Scale: 1.5 }, output: [], request_id: "r8a", duration_ms: 0 }),
    );
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ success: true, result: { Scale: 2.0 }, output: [], request_id: "r8b", duration_ms: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const el = new DazElement(client, "Scene.findNode(\"Figure\")");

    // First snapshot populates cache
    const result1 = await el.snapshot(["Scale"]);
    expect(result1).toEqual({ Scale: 1.5 });
    expect(fetchMock.mock.calls.length).toBe(1);

    // refresh() clears the cache
    el.refresh();

    // Second snapshot re-fetches (does not reuse cache)
    const result2 = await el.snapshot(["Scale"]);
    expect(result2).toEqual({ Scale: 2.0 });
    expect(fetchMock.mock.calls.length).toBe(2);
  });
});
