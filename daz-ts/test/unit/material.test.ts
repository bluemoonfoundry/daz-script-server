import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazMaterial } from "../../src/material.js";

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

describe("DazMaterial", () => {
  it("materialName reads via getName()", async () => {
    const fetchMock = stubExecute("DefaultMaterial");
    const client = new DazClient({ token: "" });
    const mat = new DazMaterial(client, "MLOC");
    const result = await mat.materialName();
    expect(result).toBe("DefaultMaterial");
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe("(function(){\nvar m = MLOC; return m ? m.getName() : null;\n})()");
  });

  it("diffuseColor reads {r,g,b} from getDiffuseColor()", async () => {
    const fetchMock = stubExecute({ r: 255, g: 0, b: 0 });
    const client = new DazClient({ token: "" });
    const mat = new DazMaterial(client, "MLOC");
    const result = await mat.diffuseColor();
    expect(result).toEqual({ r: 255, g: 0, b: 0 });
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\n" +
      "            var m = MLOC;\n" +
      "            if (!m) return null;\n" +
      "            var c = m.getDiffuseColor();\n" +
      "            return {r: c.red, g: c.green, b: c.blue};\n" +
      "        \n})()",
    );
  });

  it("setDiffuseColor accepts an object {r,g,b} and builds a new Color(...)", async () => {
    const fetchMock = stubExecute(null);
    const client = new DazClient({ token: "" });
    const mat = new DazMaterial(client, "MLOC");
    await mat.setDiffuseColor({ r: 10, g: 20, b: 30 });
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\n" +
      "            var m = MLOC;\n" +
      "            if (!m) return;\n" +
      "            var c = new Color(10, 20, 30);\n" +
      "            m.setDiffuseColor(c);\n" +
      "        \n})()",
    );
  });

  it("setDiffuseColor accepts a plain array [r,g,b] and builds a new Color(...)", async () => {
    const fetchMock = stubExecute(null);
    const client = new DazClient({ token: "" });
    const mat = new DazMaterial(client, "MLOC");
    await mat.setDiffuseColor([10, 20, 30]);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\n" +
      "            var m = MLOC;\n" +
      "            if (!m) return;\n" +
      "            var c = new Color(10, 20, 30);\n" +
      "            m.setDiffuseColor(c);\n" +
      "        \n})()",
    );
  });

  it("opacity getter reads via getBaseOpacity()", async () => {
    const fetchMock = stubExecute(0.5);
    const client = new DazClient({ token: "" });
    const mat = new DazMaterial(client, "MLOC");
    const result = await mat.opacity();
    expect(result).toBe(0.5);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe("(function(){\nvar m = MLOC; return m ? m.getBaseOpacity() : null;\n})()");
  });

  it("setOpacity writes via setBaseOpacity", async () => {
    const fetchMock = stubExecute(null);
    const client = new DazClient({ token: "" });
    const mat = new DazMaterial(client, "MLOC");
    await mat.setOpacity(0.5);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe("(function(){\nvar m = MLOC; if (m) m.setBaseOpacity(0.5);\n})()");
  });

  it("colorMap reads the texture filename or null", async () => {
    const fetchMock = stubExecute("/path/to/texture.png");
    const client = new DazClient({ token: "" });
    const mat = new DazMaterial(client, "MLOC");
    const result = await mat.colorMap();
    expect(result).toBe("/path/to/texture.png");
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\n" +
      "            var m = MLOC;\n" +
      "            if (!m) return null;\n" +
      "            var t = m.getColorMap();\n" +
      "            return t ? t.getFilename() : null;\n" +
      "        \n})()",
    );
  });

  it("isSmoothingOn reads via isSmoothingOn()", async () => {
    const fetchMock = stubExecute(true);
    const client = new DazClient({ token: "" });
    const mat = new DazMaterial(client, "MLOC");
    const result = await mat.isSmoothingOn();
    expect(result).toBe(true);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe("(function(){\nvar m = MLOC; return m ? m.isSmoothingOn() : null;\n})()");
  });

  it("smoothingAngle reads via getSmoothingAngle()", async () => {
    const fetchMock = stubExecute(45);
    const client = new DazClient({ token: "" });
    const mat = new DazMaterial(client, "MLOC");
    const result = await mat.smoothingAngle();
    expect(result).toBe(45);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe("(function(){\nvar m = MLOC; return m ? m.getSmoothingAngle() : null;\n})()");
  });

  it("setSmoothingAngle writes via setSmoothingAngle", async () => {
    const fetchMock = stubExecute(null);
    const client = new DazClient({ token: "" });
    const mat = new DazMaterial(client, "MLOC");
    await mat.setSmoothingAngle(60);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe("(function(){\nvar m = MLOC; if (m) m.setSmoothingAngle(60);\n})()");
  });

  it("isOpaque reads via isOpaque()", async () => {
    const fetchMock = stubExecute(true);
    const client = new DazClient({ token: "" });
    const mat = new DazMaterial(client, "MLOC");
    const result = await mat.isOpaque();
    expect(result).toBe(true);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe("(function(){\nvar m = MLOC; return m ? m.isOpaque() : null;\n})()");
  });
});
