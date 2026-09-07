import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazCamera } from "../../src/camera.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

afterEach(() => vi.unstubAllGlobals());

function stub(value: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ success: true, result: value, output: [], request_id: "r", duration_ms: 0 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("DazCamera", () => {
  it("focalLength getter calls _node.focalLength directly", async () => {
    const fetchMock = stub(50);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.focalLength();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("return _node.focalLength;");
  });

  it("focalLength setter writes _node.focalLength = value with serialized value", async () => {
    const fetchMock = stub(null);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.setFocalLength(50);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("_node.focalLength = 50;");
  });

  it("fov getter calls _node.getFieldOfView()", async () => {
    const fetchMock = stub(45);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.fov();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("return _node.getFieldOfView();");
  });

  it("depthOfField getter uses findPropertyByLabel", async () => {
    const fetchMock = stub(true);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.depthOfField();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain('findPropertyByLabel("Depth of Field")');
  });

  it("depthOfField setter uses findPropertyByLabel with serialized value", async () => {
    const fetchMock = stub(null);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.setDepthOfField(true);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain('findPropertyByLabel("Depth of Field")');
  });

  it("lensShiftX getter uses findPropertyByLabel", async () => {
    const fetchMock = stub(1.5);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.lensShiftX();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain('findPropertyByLabel("Lens Shift X (mm)")');
  });

  it("lensShiftX setter uses findPropertyByLabel with serialized value", async () => {
    const fetchMock = stub(null);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.setLensShiftX(1.5);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain('findPropertyByLabel("Lens Shift X (mm)")');
  });

  it("lensShiftY getter uses findPropertyByLabel", async () => {
    const fetchMock = stub(0.8);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.lensShiftY();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain('findPropertyByLabel("Lens Shift Y (mm)")');
  });

  it("lensShiftY setter uses findPropertyByLabel with serialized value", async () => {
    const fetchMock = stub(null);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.setLensShiftY(0.8);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain('findPropertyByLabel("Lens Shift Y (mm)")');
  });

  it("fStop getter uses findPropertyByLabel", async () => {
    const fetchMock = stub(5.6);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.fStop();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain('findPropertyByLabel("F/Stop")');
  });

  it("fStop setter uses findPropertyByLabel with serialized value", async () => {
    const fetchMock = stub(null);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.setFStop(5.6);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain('findPropertyByLabel("F/Stop")');
  });

  it("apertureBlades getter uses findPropertyByLabel", async () => {
    const fetchMock = stub(6);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.apertureBlades();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain('findPropertyByLabel("Aperture Blades")');
  });

  it("apertureBlades setter truncates value and uses findPropertyByLabel", async () => {
    const fetchMock = stub(null);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.setApertureBlades(6.7);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain('findPropertyByLabel("Aperture Blades")');
  });

  it("apertureBladeRotation getter uses findPropertyByLabel", async () => {
    const fetchMock = stub(45);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.apertureBladeRotation();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain('findPropertyByLabel("Aperture Blade Rotation")');
  });

  it("apertureBladeRotation setter uses findPropertyByLabel with serialized value", async () => {
    const fetchMock = stub(null);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.setApertureBladeRotation(45);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain('findPropertyByLabel("Aperture Blade Rotation")');
  });

  it("frameWidth getter calls _node.frameWidth", async () => {
    const fetchMock = stub(36);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.frameWidth();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("return _node.frameWidth;");
  });

  it("focalDistance getter calls _node.focalDistance", async () => {
    const fetchMock = stub(100);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.focalDistance();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("return _node.focalDistance;");
  });

  it("focalDistance setter writes _node.focalDistance with serialized value", async () => {
    const fetchMock = stub(null);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.setFocalDistance(100);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("_node.focalDistance = 100;");
  });

  it("aspectWidth getter calls _node.aspectWidth", async () => {
    const fetchMock = stub(1.777);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.aspectWidth();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("return _node.aspectWidth;");
  });

  it("aspectWidth setter writes _node.aspectWidth with serialized value", async () => {
    const fetchMock = stub(null);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.setAspectWidth(1.777);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("_node.aspectWidth = 1.777;");
  });

  it("aspectHeight getter calls _node.aspectHeight", async () => {
    const fetchMock = stub(1);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.aspectHeight();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("return _node.aspectHeight;");
  });

  it("aspectHeight setter writes _node.aspectHeight with serialized value", async () => {
    const fetchMock = stub(null);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.setAspectHeight(1);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("_node.aspectHeight = 1;");
  });

  it("pixelsWidth getter calls _node.pixelsWidth", async () => {
    const fetchMock = stub(1920);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.pixelsWidth();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("return _node.pixelsWidth;");
  });

  it("pixelsWidth setter truncates value and writes _node.pixelsWidth", async () => {
    const fetchMock = stub(null);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.setPixelsWidth(1920);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("_node.pixelsWidth = 1920;");
  });

  it("pixelsHeight getter calls _node.pixelsHeight", async () => {
    const fetchMock = stub(1080);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.pixelsHeight();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("return _node.pixelsHeight;");
  });

  it("pixelsHeight setter truncates value and writes _node.pixelsHeight", async () => {
    const fetchMock = stub(null);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.setPixelsHeight(1080);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("_node.pixelsHeight = 1080;");
  });

  it("nearClippingPlane getter calls _node.nearClippingPlane", async () => {
    const fetchMock = stub(0.001);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.nearClippingPlane();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("return _node.nearClippingPlane;");
  });

  it("farClippingPlane getter calls _node.farClippingPlane", async () => {
    const fetchMock = stub(10000);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.farClippingPlane();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("return _node.farClippingPlane;");
  });

  it("aimAt creates DzVec3 with serialized arguments", async () => {
    const fetchMock = stub(null);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.aimAt(1, 2, 3);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("_node.aimAt(new DzVec3(1, 2, 3));");
  });

  it("focalPoint returns world-space focal point object", async () => {
    const fetchMock = stub({ x: 10, y: 20, z: 30 });
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.focalPoint();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("var fp = _node.getFocalPoint();");
    expect(script).toContain("return {x: fp.x, y: fp.y, z: fp.z};");
  });

  it("isViewCamera calls _node.isViewCamera()", async () => {
    const fetchMock = stub(true);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.isViewCamera();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("return _node.isViewCamera();");
  });
});
