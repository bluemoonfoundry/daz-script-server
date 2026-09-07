import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { RenderError } from "../../src/exceptions.js";
import { applyHdriEnvironment, applyThreePointLightSetup, setLightColor } from "../../src/lighting.js";
import { DazLight } from "../../src/light.js";
import { Vec3 } from "../../src/math3.js";
import { DazRenderSettings } from "../../src/render.js";
import { DazScene } from "../../src/scene.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}
afterEach(() => vi.unstubAllGlobals());

function stubSequence(results: unknown[]) {
  let i = 0;
  const fetchMock = vi.fn().mockImplementation(() => {
    const value = results[Math.min(i, results.length - 1)];
    i += 1;
    return Promise.resolve(jsonResponse({ success: true, result: value, output: [], request_id: "r", duration_ms: 0 }));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
function scriptOf(fetchMock: ReturnType<typeof vi.fn>, callIndex: number): string {
  return JSON.parse(fetchMock.mock.calls[callIndex][1].body as string).script;
}

describe("applyThreePointLightSetup", () => {
  it("creates and places key/fill/rim lights around a Vec3 target, using the default light specs", async () => {
    const fetchMock = stubSequence([
      "key", // createLight -> name
      undefined, // setPosition
      undefined, // setRotation
      0.5, // getProperty("Intensity") is not called; setProperty for Intensity is a set -- see below
    ]);
    const scene = new DazScene(new DazClient({ token: "" }));
    const rig = await applyThreePointLightSetup(scene, { target: new Vec3(0, 0, 0) });
    expect(rig.key).toBeInstanceOf(DazLight);
    expect(rig.fill).toBeInstanceOf(DazLight);
    expect(rig.rim).toBeInstanceOf(DazLight);

    // 4 lights x [createLight, setPosition, setRotation, setIntensity, setColor] = 20 calls total
    expect(fetchMock).toHaveBeenCalledTimes(15);
    expect(scriptOf(fetchMock, 0)).toContain('light.setName("key");');
    expect(scriptOf(fetchMock, 0)).toContain("new DzSpotLight()");
  });

  it("uses an explicit position when LightSpec.position is set, ignoring azimuth/elevation/distance", async () => {
    const fetchMock = stubSequence(["key", undefined, undefined, undefined, undefined]);
    const scene = new DazScene(new DazClient({ token: "" }));
    await applyThreePointLightSetup(scene, {
      target: new Vec3(0, 0, 0),
      key: { role: "key", azimuthDeg: 999, elevationDeg: 999, distance: 999, intensity: 10, position: new Vec3(1, 2, 3) },
      fill: { role: "fill", azimuthDeg: 0, elevationDeg: 0, distance: 0, intensity: 0 },
      rim: { role: "rim", azimuthDeg: 0, elevationDeg: 0, distance: 0, intensity: 0 },
    });
    const posScript = scriptOf(fetchMock, 1);
    expect(posScript).toContain("new DzVec3(1, 2, 3)");
  });

  it("passes lightType through to DazScene.createLight for all three lights", async () => {
    const fetchMock = stubSequence(["p1", undefined, undefined, undefined, undefined]);
    const scene = new DazScene(new DazClient({ token: "" }));
    await applyThreePointLightSetup(scene, { target: new Vec3(0, 0, 0), lightType: "point" });
    expect(scriptOf(fetchMock, 0)).toContain("new DzPointLight()");
  });
});

describe("setLightColor", () => {
  it("delegates to DazLight.setColor", async () => {
    const fetchMock = stubSequence([undefined]);
    const light = new DazLight(new DazClient({ token: "" }), { value: "Spot1", kind: "name" });
    await setLightColor(light, 10, 20, 30);
    expect(scriptOf(fetchMock, 0)).toContain("new Color(10, 20, 30)");
  });
});

describe("applyHdriEnvironment", () => {
  let tmpFile: string;
  afterEach(() => {
    if (tmpFile && fs.existsSync(tmpFile)) fs.unlinkSync(tmpFile);
  });
  function makeTmpFile(): string {
    tmpFile = path.join(os.tmpdir(), `daz-ts-lighting-test-${Date.now()}-${Math.random()}.hdr`);
    fs.writeFileSync(tmpFile, "fake hdri bytes");
    return tmpFile;
  }

  it("throws before any DazScript call when the image path does not exist", async () => {
    const fetchMock = stubSequence([undefined]);
    const settings = new DazRenderSettings(new DazClient({ token: "" }));
    const missing = path.join(os.tmpdir(), "daz-ts-lighting-does-not-exist.hdr");
    await expect(applyHdriEnvironment(settings, { imagePath: missing })).rejects.toThrow(
      "HDRI/environment map not found",
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("throws on an invalid mode", async () => {
    const file = makeTmpFile();
    const fetchMock = stubSequence([undefined]);
    const settings = new DazRenderSettings(new DazClient({ token: "" }));
    await expect(applyHdriEnvironment(settings, { imagePath: file, mode: "bogus" as never })).rejects.toThrow(
      "Invalid HDRIEnvironment.mode",
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("applies map/intensity/rotation/mode/drawDome then verifies via readback", async () => {
    const file = makeTmpFile();
    const fetchMock = stubSequence([undefined, undefined, undefined, undefined, undefined, 2.0]);
    const settings = new DazRenderSettings(new DazClient({ token: "" }));
    await applyHdriEnvironment(settings, { imagePath: file, intensity: 2.0, rotationDeg: 90, drawDome: true });
    expect(fetchMock).toHaveBeenCalledTimes(6);
    expect(scriptOf(fetchMock, 0)).toContain("p.setMap(");
    expect(scriptOf(fetchMock, 1)).toContain('"Environment Intensity"');
    expect(scriptOf(fetchMock, 2)).toContain('"Dome Rotation"');
    expect(scriptOf(fetchMock, 3)).toContain('setValueFromString("Dome Only")');
    expect(scriptOf(fetchMock, 4)).toContain('"Draw Dome"');
  });

  it("throws RenderError when the readback doesn't match the requested intensity", async () => {
    const file = makeTmpFile();
    stubSequence([undefined, undefined, undefined, undefined, undefined, 0.1]);
    const settings = new DazRenderSettings(new DazClient({ token: "" }));
    await expect(applyHdriEnvironment(settings, { imagePath: file, intensity: 2.0 })).rejects.toThrow(RenderError);
  });
});
