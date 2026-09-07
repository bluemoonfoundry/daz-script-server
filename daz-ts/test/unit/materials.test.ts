import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { MaterialError } from "../../src/exceptions.js";
import { DazMaterial } from "../../src/material.js";
import {
  applyIrayMaterial,
  applyTextureMap,
  getSurfaceProperty,
  setSurfaceProperty,
} from "../../src/materials.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}
afterEach(() => vi.unstubAllGlobals());
function stub(value: unknown) {
  const fetchMock = vi
    .fn()
    .mockImplementation(() =>
      Promise.resolve(jsonResponse({ success: true, result: value, output: [], request_id: "r", duration_ms: 0 })),
    );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
function scriptOf(fetchMock: ReturnType<typeof vi.fn>, callIndex = 0): string {
  return JSON.parse(fetchMock.mock.calls[callIndex][1].body as string).script;
}

function material(): DazMaterial {
  return new DazMaterial(new DazClient({ token: "" }), "Scene.findNode(\"Torso\").getMaterial(0)");
}

let tmpFile: string;
function makeTmpFile(): string {
  tmpFile = path.join(os.tmpdir(), `daz-ts-materials-test-${Date.now()}-${Math.random()}.png`);
  fs.writeFileSync(tmpFile, "fake image bytes");
  return tmpFile;
}
afterEach(() => {
  if (tmpFile && fs.existsSync(tmpFile)) fs.unlinkSync(tmpFile);
});

describe("getSurfaceProperty / setSurfaceProperty", () => {
  it("getSurfaceProperty returns the value on success", async () => {
    stub({ success: true, value: 0.75 });
    const value = await getSurfaceProperty(material(), "Glossy Roughness");
    expect(value).toBe(0.75);
  });

  it("getSurfaceProperty throws MaterialError when the property is not found", async () => {
    stub({ error: "property_not_found" });
    await expect(getSurfaceProperty(material(), "Nonexistent")).rejects.toThrow(MaterialError);
  });

  it("setSurfaceProperty generates the exact set-channel script", async () => {
    const fetchMock = stub({ success: true });
    await setSurfaceProperty(material(), { label: "Cutout Opacity", value: 0.5 });
    const script = scriptOf(fetchMock);
    expect(script).toContain('var p = m.findPropertyByLabel("Cutout Opacity");');
    expect(script).toContain("p.setValue(0.5);");
  });

  it("setSurfaceProperty throws MaterialError when the material is not found", async () => {
    stub({ error: "material_not_found" });
    await expect(setSurfaceProperty(material(), { label: "X", value: 1 })).rejects.toThrow(
      'Failed to set Iray channel "X": material_not_found',
    );
  });
});

describe("applyTextureMap", () => {
  it("validates the path is absolute before any DazScript call", async () => {
    const fetchMock = stub({ success: true });
    await expect(applyTextureMap(material(), { channel: "base_color", filePath: "relative/path.png" })).rejects.toThrow(
      "Texture map path must be absolute",
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("validates the file exists before any DazScript call", async () => {
    const fetchMock = stub({ success: true });
    const missing = path.join(os.tmpdir(), "daz-ts-materials-does-not-exist.png");
    await expect(applyTextureMap(material(), { channel: "base_color", filePath: missing })).rejects.toThrow(
      "Texture map not found",
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("resolves the channel key to its display label and calls setMap()", async () => {
    const file = makeTmpFile();
    const fetchMock = stub({ success: true });
    await applyTextureMap(material(), { channel: "normal", filePath: file });
    const script = scriptOf(fetchMock);
    expect(script).toContain('var p = m.findPropertyByLabel("Normal Map");');
    expect(script).toContain(`p.setMap(${JSON.stringify(file)});`);
  });

  it("passes an unknown channel key through as a literal display label", async () => {
    const file = makeTmpFile();
    const fetchMock = stub({ success: true });
    await applyTextureMap(material(), { channel: "Custom Label", filePath: file });
    expect(scriptOf(fetchMock)).toContain('var p = m.findPropertyByLabel("Custom Label");');
  });
});

describe("applyIrayMaterial", () => {
  it("applies typed fields, then textures, then properties, in that order", async () => {
    const file = makeTmpFile();
    const fetchMock = stub({ success: true });
    await applyIrayMaterial(material(), {
      baseColor: [255, 0, 0],
      roughness: 0.3,
      textures: [{ channel: "base_color", filePath: file }],
      properties: [{ label: "Cutout Opacity", value: 0.9 }],
    });
    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(scriptOf(fetchMock, 0)).toContain('m.findPropertyByLabel("Base Color")');
    expect(scriptOf(fetchMock, 0)).toContain("p.setValue([255,0,0]);");
    expect(scriptOf(fetchMock, 1)).toContain('m.findPropertyByLabel("Glossy Roughness")');
    expect(scriptOf(fetchMock, 2)).toContain("p.setMap(");
    expect(scriptOf(fetchMock, 3)).toContain('m.findPropertyByLabel("Cutout Opacity")');
    expect(scriptOf(fetchMock, 3)).toContain("p.setValue(0.9);");
  });

  it("skips undefined typed fields", async () => {
    const fetchMock = stub({ success: true });
    await applyIrayMaterial(material(), { metallicWeight: 0.1 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(scriptOf(fetchMock, 0)).toContain('m.findPropertyByLabel("Metallicity")');
  });

  it("validates all texture paths before any DazScript call is made", async () => {
    const fetchMock = stub({ success: true });
    await expect(
      applyIrayMaterial(material(), { textures: [{ channel: "base_color", filePath: "relative.png" }] }),
    ).rejects.toThrow("Texture map path must be absolute");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
