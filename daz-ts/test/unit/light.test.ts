import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazLight } from "../../src/light.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

afterEach(() => vi.unstubAllGlobals());

function stub(value: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ success: true, result: value, output: [], request_id: "r", duration_ms: 0 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("DazLight", () => {
  it("intensity getter uses findPropertyByLabel", async () => {
    const fetchMock = stub(100);
    const light = new DazLight(new DazClient({ token: "" }), { value: "Spotlight1", kind: "name" });
    await light.intensity();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\n" +
      "            var obj = Scene.findNode(\"Spotlight1\");\n" +
      "            if (!obj) return null;\n" +
      "            var prop = obj.findPropertyByLabel(\"Intensity\");\n" +
      "            if (!prop) return null;\n" +
      "            return prop.getValue();\n" +
      "        \n" +
      "})()"
    );
  });

  it("intensity setter uses findPropertyByLabel with serialized value", async () => {
    const fetchMock = stub(null);
    const light = new DazLight(new DazClient({ token: "" }), { value: "Spotlight1", kind: "name" });
    await light.setIntensity(100);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\n" +
      "            var obj = Scene.findNode(\"Spotlight1\");\n" +
      "            if (!obj) return {\"error\": \"not_found\"};\n" +
      "            var prop = obj.findPropertyByLabel(\"Intensity\");\n" +
      "            if (!prop) return {\"error\": \"property_not_found\"};\n" +
      "            prop.setValue(100);\n" +
      "            return {\"success\": true};\n" +
      "        \n" +
      "})()"
    );
  });

  it("color getter reads getDiffuseColor", async () => {
    const fetchMock = stub({ r: 255, g: 255, b: 200 });
    const light = new DazLight(new DazClient({ token: "" }), { value: "Spotlight1", kind: "name" });
    await light.color();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Spotlight1");\nif (!_node) return null;\n' +
      "            var c = _node.getDiffuseColor();\n" +
      "            return {r: c.red, g: c.green, b: c.blue};\n" +
      "        \n" +
      "})()"
    );
  });

  it("setColor finds Color property and calls setColorValue with Color object", async () => {
    const fetchMock = stub(null);
    const light = new DazLight(new DazClient({ token: "" }), { value: "Spotlight1", kind: "name" });
    await light.setColor(1, 2, 3);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Spotlight1");\nif (!_node) return null;\nvar p = _node.findPropertyByLabel(\'Color\'); if (p) p.setColorValue(new Color(1, 2, 3));\n})()'
    );
  });

  it("shadowType getter uses findPropertyByLabel", async () => {
    const fetchMock = stub("raytrace");
    const light = new DazLight(new DazClient({ token: "" }), { value: "Spotlight1", kind: "name" });
    await light.shadowType();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\n" +
      "            var obj = Scene.findNode(\"Spotlight1\");\n" +
      "            if (!obj) return null;\n" +
      "            var prop = obj.findPropertyByLabel(\"Shadow Type\");\n" +
      "            if (!prop) return null;\n" +
      "            return prop.getValue();\n" +
      "        \n" +
      "})()"
    );
  });

  it("illumination getter uses findPropertyByLabel", async () => {
    const fetchMock = stub("diffuse");
    const light = new DazLight(new DazClient({ token: "" }), { value: "Spotlight1", kind: "name" });
    await light.illumination();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\n" +
      "            var obj = Scene.findNode(\"Spotlight1\");\n" +
      "            if (!obj) return null;\n" +
      "            var prop = obj.findPropertyByLabel(\"Illumination\");\n" +
      "            if (!prop) return null;\n" +
      "            return prop.getValue();\n" +
      "        \n" +
      "})()"
    );
  });

  it("isOn calls _node.isOn()", async () => {
    const fetchMock = stub(true);
    const light = new DazLight(new DazClient({ token: "" }), { value: "Spotlight1", kind: "name" });
    await light.isOn();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Spotlight1");\nif (!_node) return null;\nreturn _node.isOn();\n})()'
    );
  });

  it("isDirectional calls _node.isDirectional()", async () => {
    const fetchMock = stub(true);
    const light = new DazLight(new DazClient({ token: "" }), { value: "Spotlight1", kind: "name" });
    await light.isDirectional();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Spotlight1");\nif (!_node) return null;\nreturn _node.isDirectional();\n})()'
    );
  });

  it("isAreaLight calls _node.isAreaLight()", async () => {
    const fetchMock = stub(false);
    const light = new DazLight(new DazClient({ token: "" }), { value: "Spotlight1", kind: "name" });
    await light.isAreaLight();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Spotlight1");\nif (!_node) return null;\nreturn _node.isAreaLight();\n})()'
    );
  });

  it("direction returns null when light is not directional", async () => {
    const fetchMock = stub(null);
    const light = new DazLight(new DazClient({ token: "" }), { value: "PointLight1", kind: "name" });
    expect(await light.direction()).toBeNull();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("PointLight1");\nif (!_node) return null;\nif (!_node.isDirectional()) return null; var d = _node.getWSDirection(); return {x: d.x, y: d.y, z: d.z};\n})()'
    );
  });

  it("direction returns {x, y, z} when light is directional", async () => {
    const fetchMock = stub({ x: 1, y: 0, z: 0 });
    const light = new DazLight(new DazClient({ token: "" }), { value: "Spotlight1", kind: "name" });
    expect(await light.direction()).toEqual({ x: 1, y: 0, z: 0 });
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Spotlight1");\nif (!_node) return null;\nif (!_node.isDirectional()) return null; var d = _node.getWSDirection(); return {x: d.x, y: d.y, z: d.z};\n})()'
    );
  });
});
