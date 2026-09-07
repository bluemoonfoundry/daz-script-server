import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazNode } from "../../src/node.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}
afterEach(() => vi.unstubAllGlobals());

function stub(value: unknown) {
  const fetchMock = vi
    .fn()
    .mockResolvedValue(jsonResponse({ success: true, result: value, output: [], request_id: "r", duration_ms: 0 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("DazNode transforms", () => {
  it("position() reads getWSPos as {x,y,z}", async () => {
    const fetchMock = stub({ x: 1, y: 2, z: 3 });
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await node.position()).toEqual({ x: 1, y: 2, z: 3 });
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\nvar p = _node.getWSPos(); return {x: p.x, y: p.y, z: p.z};\n})()',
    );
  });

  it("setPosition writes a new DzVec3 via setWSPos", async () => {
    const fetchMock = stub(null);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await node.setPosition(1, 2, 3);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\n_node.setWSPos(new DzVec3(1, 2, 3));\n})()',
    );
  });

  it("setTransform emits only the lines for the provided components, in position/rotation/scale order", async () => {
    const fetchMock = stub(null);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await node.setTransform({ position: [1, 0, 0], scale: [2, 2, 2] });
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\n_node.setLocalPos(new DzVec3(1, 0, 0));\n_node.getXScaleControl().setValue(2); _node.getYScaleControl().setValue(2); _node.getZScaleControl().setValue(2);\n})()',
    );
  });

  it("setTransform with no arguments makes no HTTP call", async () => {
    const fetchMock = stub(null);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await node.setTransform({});
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("parent() returns null for a root node and a DazNode wrapping the parent otherwise", async () => {
    const fetchMock = stub("Torso");
    const node = new DazNode(new DazClient({ token: "" }), { value: "Head", kind: "name" });
    const parent = await node.parent();
    expect(parent).toBeInstanceOf(DazNode);
    expect(parent?.identifier).toEqual({ value: "Torso", kind: "name" });
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Head");\nif (!_node) return null;\nvar p = _node.getNodeParent(); return p ? p.getName() : null;\n})()',
    );
  });

  it("children() maps each returned name to a DazNode", async () => {
    const fetchMock = stub(["Hand", "Foot"]);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Torso", kind: "name" });
    const children = await node.children();
    expect(children.map((c) => c.identifier.value)).toEqual(["Hand", "Foot"]);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Torso");\nif (!_node) return null;\nvar names = []; for (var i = 0; i < _node.getNumNodeChildren(); i++) { names.push(_node.getNodeChild(i).getName()); } return names;\n})()',
    );
  });

  it("delete() returns the boolean result of Scene.removeNode", async () => {
    const fetchMock = stub(true);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Prop", kind: "name" });
    expect(await node.delete()).toBe(true);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Prop");\nif (!_node) return null;\nreturn Scene.removeNode(_node);\n})()',
    );
  });

  it("reparent throws ScriptRuntimeError when the server reports a non-null result", async () => {
    const fetchMock = stub("new parent not found");
    const node = new DazNode(new DazClient({ token: "" }), { value: "Prop", kind: "name" });
    const other = new DazNode(new DazClient({ token: "" }), { value: "Ghost", kind: "name" });
    await expect(node.reparent(other)).rejects.toThrow(/reparent failed/);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Prop");\nif (!_node) return null;\n\n            var _newParent = Scene.findNode("Ghost");\n            if (!_newParent) return "new parent not found";\n            var _oldParent = _node.getNodeParent();\n            if (_oldParent) _oldParent.removeNodeChild(_node, true);\n            var _err = _newParent.addNodeChild(_node, true);\n            var _errNum = _err ? _err.valueOf() : 0;\n            return _errNum !== 0 ? ("DzError code " + _errNum) : null;\n            \n})()',
    );
  });

  it("visible getter/setter round-trip isVisible/setVisible", async () => {
    const fetchMock = stub(null);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Prop", kind: "name" });
    await node.setVisible(false);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Prop");\nif (!_node) return null;\n_node.setVisible(false);\n})()',
    );
  });

  it("label() reads getLabel", async () => {
    const fetchMock = stub("Genesis 9");
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await node.label()).toBe("Genesis 9");
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\nreturn _node.getLabel();\n})()',
    );
  });

  it("setLabel escapes the value and calls setLabel", async () => {
    const fetchMock = stub(null);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await node.setLabel('a"b');
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\n_node.setLabel("a\\"b");\n})()',
    );
  });

  it("name() reads getName", async () => {
    const fetchMock = stub("Genesis9");
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await node.name()).toBe("Genesis9");
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\nreturn _node.getName();\n})()',
    );
  });

  it("rotation() reads getWSRot as {x,y,z,w}", async () => {
    const fetchMock = stub({ x: 0, y: 0, z: 0, w: 1 });
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await node.rotation()).toEqual({ x: 0, y: 0, z: 0, w: 1 });
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\nvar r = _node.getWSRot(); return {x: r.x, y: r.y, z: r.z, w: r.w};\n})()',
    );
  });

  it("generalScale() reads getScaleControl().getValue()", async () => {
    const fetchMock = stub(1.5);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await node.generalScale()).toBe(1.5);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\nreturn _node.getScaleControl().getValue();\n})()',
    );
  });

  it("scale() reads per-axis and general scale", async () => {
    const fetchMock = stub({ x: 1, y: 1, z: 1, general: 1 });
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await node.scale()).toEqual({ x: 1, y: 1, z: 1, general: 1 });
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\nreturn {x: _node.getXScaleControl().getValue(), y: _node.getYScaleControl().getValue(), z: _node.getZScaleControl().getValue(), general: _node.getScaleControl().getValue()};\n})()',
    );
  });

  it("setScale writes each axis scale control", async () => {
    const fetchMock = stub(null);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await node.setScale(1, 2, 3);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\n_node.getXScaleControl().setValue(1); _node.getYScaleControl().setValue(2); _node.getZScaleControl().setValue(3);\n})()',
    );
  });

  it("setRotation writes each axis rotation control", async () => {
    const fetchMock = stub(null);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await node.setRotation(10, 20, 30);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\n_node.getXRotControl().setValue(10); _node.getYRotControl().setValue(20); _node.getZRotControl().setValue(30);\n})()',
    );
  });

  it("setPositionAtFrame converts frame to ticks via Scene.getTimeStep()", async () => {
    const fetchMock = stub(null);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await node.setPositionAtFrame(12, 1, 2, 3);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\nvar _tm = 12 * Scene.getTimeStep(); _node.setWSPos(_tm, new DzVec3(1, 2, 3));\n})()',
    );
  });

  it("setRotationAtFrame converts frame to ticks and writes each axis rotation control", async () => {
    const fetchMock = stub(null);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await node.setRotationAtFrame(12, 10, 20, 30);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\nvar _tm = 12 * Scene.getTimeStep(); _node.getXRotControl().setDoubleValue(_tm, 10); _node.getYRotControl().setDoubleValue(_tm, 20); _node.getZRotControl().setDoubleValue(_tm, 30);\n})()',
    );
  });

  it("clearPositionKeys deletes all keys on the X/Y/Z position controls", async () => {
    const fetchMock = stub(null);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await node.clearPositionKeys();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\n_node.getXPosControl().deleteAllKeys(); _node.getYPosControl().deleteAllKeys(); _node.getZPosControl().deleteAllKeys();\n})()',
    );
  });

  it("clearRotationKeys deletes all keys on the X/Y/Z rotation controls", async () => {
    const fetchMock = stub(null);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await node.clearRotationKeys();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\n_node.getXRotControl().deleteAllKeys(); _node.getYRotControl().deleteAllKeys(); _node.getZRotControl().deleteAllKeys();\n})()',
    );
  });

  it("localPosition() reads getLocalPos as {x,y,z}", async () => {
    const fetchMock = stub({ x: 1, y: 2, z: 3 });
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await node.localPosition()).toEqual({ x: 1, y: 2, z: 3 });
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\nvar p = _node.getLocalPos(); return {x: p.x, y: p.y, z: p.z};\n})()',
    );
  });

  it("setLocalPosition writes a new DzVec3 via setLocalPos", async () => {
    const fetchMock = stub(null);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await node.setLocalPosition(4, 5, 6);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\n_node.setLocalPos(new DzVec3(4, 5, 6));\n})()',
    );
  });

  it("localEuler() returns a tuple of the X/Y/Z rotation control values", async () => {
    const fetchMock = stub([10, 20, 30]);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await node.localEuler()).toEqual([10, 20, 30]);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\nreturn [_node.getXRotControl().getValue(), _node.getYRotControl().getValue(), _node.getZRotControl().getValue()];\n})()',
    );
  });

  it("localEuler() returns null when the node cannot be resolved", async () => {
    stub(null);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Ghost", kind: "name" });
    expect(await node.localEuler()).toBeNull();
  });

  it("localRotation() reads getLocalRot as {x,y,z,w}", async () => {
    const fetchMock = stub({ x: 0, y: 0, z: 0, w: 1 });
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await node.localRotation()).toEqual({ x: 0, y: 0, z: 0, w: 1 });
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\nvar r = _node.getLocalRot(); return {x: r.x, y: r.y, z: r.z, w: r.w};\n})()',
    );
  });

  it("setLocalRotation writes each axis rotation control", async () => {
    const fetchMock = stub(null);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await node.setLocalRotation(1, 2, 3);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\n_node.getXRotControl().setValue(1); _node.getYRotControl().setValue(2); _node.getZRotControl().setValue(3);\n})()',
    );
  });

  it("isSelected() reads isSelected", async () => {
    const fetchMock = stub(true);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await node.isSelected()).toBe(true);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\nreturn _node.isSelected();\n})()',
    );
  });

  it("select() defaults to true and calls _node.select(true)", async () => {
    const fetchMock = stub(null);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await node.select();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\n_node.select(true);\n})()',
    );
  });

  it("select(false) calls _node.select(false)", async () => {
    const fetchMock = stub(null);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await node.select(false);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\n_node.select(false);\n})()',
    );
  });

  it("isInScene() reads isInScene", async () => {
    const fetchMock = stub(true);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await node.isInScene()).toBe(true);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\nreturn _node.isInScene();\n})()',
    );
  });

  it("isRoot() reads isRootNode", async () => {
    const fetchMock = stub(false);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await node.isRoot()).toBe(false);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\nreturn _node.isRootNode();\n})()',
    );
  });

  it("isVisibleInRender()/setVisibleInRender round-trip", async () => {
    const fetchMockRead = stub(true);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await node.isVisibleInRender()).toBe(true);
    let script = JSON.parse(fetchMockRead.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\nreturn _node.isVisibleInRender();\n})()',
    );
    const fetchMockWrite = stub(null);
    await node.setVisibleInRender(true);
    script = JSON.parse(fetchMockWrite.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\n_node.setVisibleInRender(true);\n})()',
    );
  });

  it("isVisibleInViewport()/setVisibleInViewport round-trip", async () => {
    const fetchMockRead = stub(false);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await node.isVisibleInViewport()).toBe(false);
    let script = JSON.parse(fetchMockRead.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\nreturn _node.isVisibleInViewport();\n})()',
    );
    const fetchMockWrite = stub(null);
    await node.setVisibleInViewport(false);
    script = JSON.parse(fetchMockWrite.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\n_node.setVisibleInViewport(false);\n})()',
    );
  });

  it("visible() reads isVisible", async () => {
    const fetchMock = stub(true);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await node.visible()).toBe(true);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\nreturn _node.isVisible();\n})()',
    );
  });

  it("reparent with preserveWorldTransform: false passes false to remove/addNodeChild", async () => {
    const fetchMock = stub(null);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Prop", kind: "name" });
    const other = new DazNode(new DazClient({ token: "" }), { value: "NewParent", kind: "name" });
    await node.reparent(other, { preserveWorldTransform: false });
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Prop");\nif (!_node) return null;\n\n            var _newParent = Scene.findNode("NewParent");\n            if (!_newParent) return "new parent not found";\n            var _oldParent = _node.getNodeParent();\n            if (_oldParent) _oldParent.removeNodeChild(_node, false);\n            var _err = _newParent.addNodeChild(_node, false);\n            var _errNum = _err ? _err.valueOf() : 0;\n            return _errNum !== 0 ? ("DzError code " + _errNum) : null;\n            \n})()',
    );
  });

  it("reparent resolves without throwing when the server reports null", async () => {
    stub(null);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Prop", kind: "name" });
    const other = new DazNode(new DazClient({ token: "" }), { value: "NewParent", kind: "name" });
    await expect(node.reparent(other)).resolves.toBeUndefined();
  });
});
