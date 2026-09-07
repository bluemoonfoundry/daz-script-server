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
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Camera");\nif (!_node) return null;\nreturn _node.focalLength;\n})()'
    );
  });

  it("focalLength setter writes _node.focalLength = value with serialized value", async () => {
    const fetchMock = stub(null);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.setFocalLength(50);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Camera");\nif (!_node) return null;\n_node.focalLength = 50;\n})()'
    );
  });

  it("fov getter calls _node.getFieldOfView()", async () => {
    const fetchMock = stub(45);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.fov();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Camera");\nif (!_node) return null;\nreturn _node.getFieldOfView();\n})()'
    );
  });

  it("depthOfField getter uses findPropertyByLabel", async () => {
    const fetchMock = stub(true);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.depthOfField();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\n" +
      "            var obj = Scene.findNode(\"Camera\");\n" +
      "            if (!obj) return null;\n" +
      "            var prop = obj.findPropertyByLabel(\"Depth of Field\");\n" +
      "            if (!prop) return null;\n" +
      "            return prop.getValue();\n" +
      "        \n" +
      "})()"
    );
  });

  it("depthOfField setter uses findPropertyByLabel with serialized value", async () => {
    const fetchMock = stub(null);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.setDepthOfField(true);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\n" +
      "            var obj = Scene.findNode(\"Camera\");\n" +
      "            if (!obj) return {\"error\": \"not_found\"};\n" +
      "            var prop = obj.findPropertyByLabel(\"Depth of Field\");\n" +
      "            if (!prop) return {\"error\": \"property_not_found\"};\n" +
      "            prop.setValue(true);\n" +
      "            return {\"success\": true};\n" +
      "        \n" +
      "})()"
    );
  });

  it("lensShiftX getter uses findPropertyByLabel", async () => {
    const fetchMock = stub(1.5);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.lensShiftX();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\n" +
      "            var obj = Scene.findNode(\"Camera\");\n" +
      "            if (!obj) return null;\n" +
      "            var prop = obj.findPropertyByLabel(\"Lens Shift X (mm)\");\n" +
      "            if (!prop) return null;\n" +
      "            return prop.getValue();\n" +
      "        \n" +
      "})()"
    );
  });

  it("lensShiftX setter uses findPropertyByLabel with serialized value", async () => {
    const fetchMock = stub(null);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.setLensShiftX(1.5);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\n" +
      "            var obj = Scene.findNode(\"Camera\");\n" +
      "            if (!obj) return {\"error\": \"not_found\"};\n" +
      "            var prop = obj.findPropertyByLabel(\"Lens Shift X (mm)\");\n" +
      "            if (!prop) return {\"error\": \"property_not_found\"};\n" +
      "            prop.setValue(1.5);\n" +
      "            return {\"success\": true};\n" +
      "        \n" +
      "})()"
    );
  });

  it("lensShiftY getter uses findPropertyByLabel", async () => {
    const fetchMock = stub(0.8);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.lensShiftY();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\n" +
      "            var obj = Scene.findNode(\"Camera\");\n" +
      "            if (!obj) return null;\n" +
      "            var prop = obj.findPropertyByLabel(\"Lens Shift Y (mm)\");\n" +
      "            if (!prop) return null;\n" +
      "            return prop.getValue();\n" +
      "        \n" +
      "})()"
    );
  });

  it("lensShiftY setter uses findPropertyByLabel with serialized value", async () => {
    const fetchMock = stub(null);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.setLensShiftY(0.8);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\n" +
      "            var obj = Scene.findNode(\"Camera\");\n" +
      "            if (!obj) return {\"error\": \"not_found\"};\n" +
      "            var prop = obj.findPropertyByLabel(\"Lens Shift Y (mm)\");\n" +
      "            if (!prop) return {\"error\": \"property_not_found\"};\n" +
      "            prop.setValue(0.8);\n" +
      "            return {\"success\": true};\n" +
      "        \n" +
      "})()"
    );
  });

  it("fStop getter uses findPropertyByLabel", async () => {
    const fetchMock = stub(5.6);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.fStop();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\n" +
      "            var obj = Scene.findNode(\"Camera\");\n" +
      "            if (!obj) return null;\n" +
      "            var prop = obj.findPropertyByLabel(\"F/Stop\");\n" +
      "            if (!prop) return null;\n" +
      "            return prop.getValue();\n" +
      "        \n" +
      "})()"
    );
  });

  it("fStop setter uses findPropertyByLabel with serialized value", async () => {
    const fetchMock = stub(null);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.setFStop(5.6);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\n" +
      "            var obj = Scene.findNode(\"Camera\");\n" +
      "            if (!obj) return {\"error\": \"not_found\"};\n" +
      "            var prop = obj.findPropertyByLabel(\"F/Stop\");\n" +
      "            if (!prop) return {\"error\": \"property_not_found\"};\n" +
      "            prop.setValue(5.6);\n" +
      "            return {\"success\": true};\n" +
      "        \n" +
      "})()"
    );
  });

  it("apertureBlades getter uses findPropertyByLabel", async () => {
    const fetchMock = stub(6);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.apertureBlades();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\n" +
      "            var obj = Scene.findNode(\"Camera\");\n" +
      "            if (!obj) return null;\n" +
      "            var prop = obj.findPropertyByLabel(\"Aperture Blades\");\n" +
      "            if (!prop) return null;\n" +
      "            return prop.getValue();\n" +
      "        \n" +
      "})()"
    );
  });

  it("apertureBlades setter truncates value and uses findPropertyByLabel", async () => {
    const fetchMock = stub(null);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.setApertureBlades(6.7);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\n" +
      "            var obj = Scene.findNode(\"Camera\");\n" +
      "            if (!obj) return {\"error\": \"not_found\"};\n" +
      "            var prop = obj.findPropertyByLabel(\"Aperture Blades\");\n" +
      "            if (!prop) return {\"error\": \"property_not_found\"};\n" +
      "            prop.setValue(6);\n" +
      "            return {\"success\": true};\n" +
      "        \n" +
      "})()"
    );
  });

  it("apertureBladeRotation getter uses findPropertyByLabel", async () => {
    const fetchMock = stub(45);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.apertureBladeRotation();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\n" +
      "            var obj = Scene.findNode(\"Camera\");\n" +
      "            if (!obj) return null;\n" +
      "            var prop = obj.findPropertyByLabel(\"Aperture Blade Rotation\");\n" +
      "            if (!prop) return null;\n" +
      "            return prop.getValue();\n" +
      "        \n" +
      "})()"
    );
  });

  it("apertureBladeRotation setter uses findPropertyByLabel with serialized value", async () => {
    const fetchMock = stub(null);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.setApertureBladeRotation(45);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\n" +
      "            var obj = Scene.findNode(\"Camera\");\n" +
      "            if (!obj) return {\"error\": \"not_found\"};\n" +
      "            var prop = obj.findPropertyByLabel(\"Aperture Blade Rotation\");\n" +
      "            if (!prop) return {\"error\": \"property_not_found\"};\n" +
      "            prop.setValue(45);\n" +
      "            return {\"success\": true};\n" +
      "        \n" +
      "})()"
    );
  });

  it("frameWidth getter calls _node.frameWidth", async () => {
    const fetchMock = stub(36);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.frameWidth();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Camera");\nif (!_node) return null;\nreturn _node.frameWidth;\n})()'
    );
  });

  it("focalDistance getter calls _node.focalDistance", async () => {
    const fetchMock = stub(100);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.focalDistance();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Camera");\nif (!_node) return null;\nreturn _node.focalDistance;\n})()'
    );
  });

  it("focalDistance setter writes _node.focalDistance with serialized value", async () => {
    const fetchMock = stub(null);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.setFocalDistance(100);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Camera");\nif (!_node) return null;\n_node.focalDistance = 100;\n})()'
    );
  });

  it("aspectWidth getter calls _node.aspectWidth", async () => {
    const fetchMock = stub(1.777);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.aspectWidth();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Camera");\nif (!_node) return null;\nreturn _node.aspectWidth;\n})()'
    );
  });

  it("aspectWidth setter writes _node.aspectWidth with serialized value", async () => {
    const fetchMock = stub(null);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.setAspectWidth(1.777);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Camera");\nif (!_node) return null;\n_node.aspectWidth = 1.777;\n})()'
    );
  });

  it("aspectHeight getter calls _node.aspectHeight", async () => {
    const fetchMock = stub(1);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.aspectHeight();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Camera");\nif (!_node) return null;\nreturn _node.aspectHeight;\n})()'
    );
  });

  it("aspectHeight setter writes _node.aspectHeight with serialized value", async () => {
    const fetchMock = stub(null);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.setAspectHeight(1);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Camera");\nif (!_node) return null;\n_node.aspectHeight = 1;\n})()'
    );
  });

  it("pixelsWidth getter calls _node.pixelsWidth", async () => {
    const fetchMock = stub(1920);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.pixelsWidth();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Camera");\nif (!_node) return null;\nreturn _node.pixelsWidth;\n})()'
    );
  });

  it("pixelsWidth setter truncates value and writes _node.pixelsWidth", async () => {
    const fetchMock = stub(null);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.setPixelsWidth(1920);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Camera");\nif (!_node) return null;\n_node.pixelsWidth = 1920;\n})()'
    );
  });

  it("pixelsHeight getter calls _node.pixelsHeight", async () => {
    const fetchMock = stub(1080);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.pixelsHeight();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Camera");\nif (!_node) return null;\nreturn _node.pixelsHeight;\n})()'
    );
  });

  it("pixelsHeight setter truncates value and writes _node.pixelsHeight", async () => {
    const fetchMock = stub(null);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.setPixelsHeight(1080);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Camera");\nif (!_node) return null;\n_node.pixelsHeight = 1080;\n})()'
    );
  });

  it("nearClippingPlane getter calls _node.nearClippingPlane", async () => {
    const fetchMock = stub(0.001);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.nearClippingPlane();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Camera");\nif (!_node) return null;\nreturn _node.nearClippingPlane;\n})()'
    );
  });

  it("farClippingPlane getter calls _node.farClippingPlane", async () => {
    const fetchMock = stub(10000);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.farClippingPlane();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Camera");\nif (!_node) return null;\nreturn _node.farClippingPlane;\n})()'
    );
  });

  it("aimAt creates DzVec3 with serialized arguments", async () => {
    const fetchMock = stub(null);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.aimAt(1, 2, 3);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Camera");\nif (!_node) return null;\n_node.aimAt(new DzVec3(1, 2, 3));\n})()'
    );
  });

  it("focalPoint returns world-space focal point object", async () => {
    const fetchMock = stub({ x: 10, y: 20, z: 30 });
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.focalPoint();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Camera");\nif (!_node) return null;\nvar fp = _node.getFocalPoint(); return {x: fp.x, y: fp.y, z: fp.z};\n})()'
    );
  });

  it("isViewCamera calls _node.isViewCamera()", async () => {
    const fetchMock = stub(true);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.isViewCamera();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Camera");\nif (!_node) return null;\nreturn _node.isViewCamera();\n})()'
    );
  });
});
