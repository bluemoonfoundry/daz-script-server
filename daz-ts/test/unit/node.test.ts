import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazDForce } from "../../src/dforce.js";
import { DazMaterial } from "../../src/material.js";
import { DazModifier } from "../../src/modifier.js";
import { DazMorph } from "../../src/morph.js";
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

describe("DazNode modifiers/materials/fitting", () => {
  it("modifiers() dispatches DzMorph -> DazMorph, DzDForceModifier -> DazDForce, else DazModifier", async () => {
    const fetchMock = stub([
      { name: "PHMSmile", className: "DzMorph" },
      { name: "Cloth Sim", className: "DzDForceModifier" },
      { name: "SomeConstraint", className: "DzMorphMod" },
    ]);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const mods = await node.modifiers();
    expect(mods[0]).toBeInstanceOf(DazMorph);
    expect(mods[1]).toBeInstanceOf(DazDForce);
    expect(mods[2]).toBeInstanceOf(DazModifier);
    expect(mods[2]).not.toBeInstanceOf(DazMorph);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\n\n            var obj = _node.getObject();\n            if (!obj) return [];\n            var mods = [];\n            for (var i = 0; i < obj.getNumModifiers(); i++) {\n                var m = obj.getModifier(i);\n                mods.push({name: m.getName(), className: m.className()});\n            }\n            return mods;\n            \n})()',
    );
  });

  it("materials() returns DazMaterial instances located via getCurrentShape().findMaterial()", async () => {
    const fetchMock = stub(["Skin", "Eyes"]);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const mats = await node.materials();
    expect(mats).toHaveLength(2);
    expect(mats[0]).toBeInstanceOf(DazMaterial);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\n\n            var obj = _node.getObject();\n            if (!obj) return [];\n            var shape = obj.getCurrentShape();\n            if (!shape) return [];\n            var names = [];\n            for (var i = 0; i < shape.getNumMaterials(); i++) {\n                names.push(shape.getMaterial(i).getName());\n            }\n            return names;\n            \n})()',
    );
  });

  it("findModifier returns null when the server reports no match", async () => {
    const fetchMock = stub(null);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await node.findModifier("Missing")).toBeNull();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\n\n            var obj = _node.getObject();\n            if (!obj) return null;\n            var m = obj.findModifier("Missing");\n            return m ? {name: m.getName(), className: m.className()} : null;\n            \n})()',
    );
  });

  it("findModifierByLabel returns a typed modifier via getLabel() matching", async () => {
    const fetchMock = stub({ name: "PHMSmile", className: "DzMorph" });
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const found = await node.findModifierByLabel("Smile");
    expect(found).toBeInstanceOf(DazMorph);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\n\n            var obj = _node.getObject();\n            if (!obj) return null;\n            for (var i = 0; i < obj.getNumModifiers(); i++) {\n                var m = obj.getModifier(i);\n                if (m.getLabel() === "Smile") {\n                    return {name: m.getName(), className: m.className()};\n                }\n            }\n            return null;\n            \n})()',
    );
  });

  it("findMaterial returns a DazMaterial located via getCurrentShape().findMaterial()", async () => {
    const fetchMock = stub("Skin");
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const found = await node.findMaterial("Skin");
    expect(found).toBeInstanceOf(DazMaterial);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\n\n            var obj = _node.getObject();\n            if (!obj) return null;\n            var shape = obj.getCurrentShape();\n            if (!shape) return null;\n            var m = shape.findMaterial("Skin");\n            return m ? m.getName() : null;\n            \n})()',
    );
  });

  it("findProperty resolves to a DazProperty when the locator exists on the node", async () => {
    const fetchMock = stub(true);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const prop = await node.findProperty("XRotate");
    expect(prop).not.toBeNull();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nreturn !!((function(){var _n=Scene.findNode("Genesis9");return _n ? _n.findProperty("XRotate") : null;})());\n})()',
    );
  });

  it("findProperty returns null when the existence check reports falsy", async () => {
    stub(false);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await node.findProperty("Missing")).toBeNull();
  });

  it("findPropertyByLabel resolves to a DazProperty when the locator exists on the node", async () => {
    const fetchMock = stub(true);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const prop = await node.findPropertyByLabel("X Rotate");
    expect(prop).not.toBeNull();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nreturn !!((function(){var _n=Scene.findNode("Genesis9");return _n ? _n.findPropertyByLabel("X Rotate") : null;})());\n})()',
    );
  });

  it("morphs() filters modifiers() down to DazMorph instances", async () => {
    stub([
      { name: "PHMSmile", className: "DzMorph" },
      { name: "Cloth Sim", className: "DzDForceModifier" },
    ]);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const morphs = await node.morphs();
    expect(morphs).toHaveLength(1);
    expect(morphs[0]).toBeInstanceOf(DazMorph);
  });

  it("dforceModifiers() filters modifiers() down to DazDForce instances", async () => {
    stub([
      { name: "PHMSmile", className: "DzMorph" },
      { name: "Cloth Sim", className: "DzDForceModifier" },
    ]);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const sims = await node.dforceModifiers();
    expect(sims).toHaveLength(1);
    expect(sims[0]).toBeInstanceOf(DazDForce);
  });

  it("boundingBox() reads getWSBoundingBox() as {min,max}", async () => {
    const fetchMock = stub({ min: { x: 0, y: 0, z: 0 }, max: { x: 1, y: 1, z: 1 } });
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await node.boundingBox()).toEqual({ min: { x: 0, y: 0, z: 0 }, max: { x: 1, y: 1, z: 1 } });
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\nvar bb = _node.getWSBoundingBox(); return {min: {x: bb.min.x, y: bb.min.y, z: bb.min.z}, max: {x: bb.max.x, y: bb.max.y, z: bb.max.z}};\n})()',
    );
  });

  it("fitTo returns the DazScript API name the server used", async () => {
    const fetchMock = stub("setFollowTarget");
    const node = new DazNode(new DazClient({ token: "" }), { value: "Shirt", kind: "name" });
    const figure = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await node.fitTo(figure)).toBe("setFollowTarget");
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Shirt");\nif (!_node) return null;\n\n            var _figure = Scene.findNode("Genesis9");\n            if (!_figure) return null;\n            var _method;\n            if (typeof _node.setFollowTarget === \'function\') {\n                _node.setFollowTarget(_figure);\n                _method = "setFollowTarget";\n            } else if (typeof _node.followSkeleton === \'function\') {\n                _node.followSkeleton(_figure);\n                _method = "followSkeleton";\n            } else {\n                _figure.addNodeChild(_node, true);\n                _method = "addNodeChild";\n            }\n            return _method;\n            \n})()',
    );
  });

  it("fitTo raises NodeNotFoundError-style rejection when the script returns null", async () => {
    stub(null);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Shirt", kind: "name" });
    const figure = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await expect(node.fitTo(figure)).rejects.toThrow(/not found/);
  });

  it("unfit() defaults previousFigure to null and actions to [] when nothing was fitted", async () => {
    const fetchMock = stub(null);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Prop", kind: "name" });
    expect(await node.unfit()).toEqual({ previousFigure: null, actions: [] });
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Prop");\nif (!_node) return null;\n\n            var _prevFigure = null;\n            var _actions = [];\n            if (typeof _node.getFollowTarget === \'function\') {\n                var _ft = _node.getFollowTarget();\n                if (_ft) {\n                    _prevFigure = _ft.getName();\n                    if (typeof _node.setFollowTarget === \'function\') {\n                        _node.setFollowTarget(null);\n                        _actions.push("cleared follow target");\n                    }\n                }\n            }\n            var _parent = _node.getNodeParent();\n            if (_parent && _parent.inherits && _parent.inherits("DzSkeleton")) {\n                _prevFigure = _prevFigure || _parent.getName();\n                _parent.removeNodeChild(_node, true);\n                _actions.push("detached from parent");\n            }\n            return {previous_figure: _prevFigure, actions: _actions};\n        \n})()',
    );
  });

  it("unfit() surfaces the previous figure and actions reported by the server", async () => {
    stub({ previous_figure: "Genesis9", actions: ["cleared follow target"] });
    const node = new DazNode(new DazClient({ token: "" }), { value: "Shirt", kind: "name" });
    expect(await node.unfit()).toEqual({ previousFigure: "Genesis9", actions: ["cleared follow target"] });
  });

  it("fittedItems() maps each returned name to a DazNode", async () => {
    const fetchMock = stub(["Shirt", "Pants"]);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const items = await node.fittedItems();
    expect(items.map((n) => n.identifier)).toEqual([
      { value: "Shirt", kind: "name" },
      { value: "Pants", kind: "name" },
    ]);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\n\n            var _fitted = [];\n            var _numNodes = Scene.getNumNodes();\n            for (var i = 0; i < _numNodes; i++) {\n                var _n = Scene.getNode(i);\n                if (!_n || _n === _node) continue;\n                var _isFitted = false;\n                if (typeof _n.getFollowTarget === \'function\') {\n                    var _ft = _n.getFollowTarget();\n                    if (_ft && _ft.elementID === _node.elementID) _isFitted = true;\n                }\n                if (!_isFitted && typeof _n.getNodeParent === \'function\') {\n                    var _p = _n.getNodeParent();\n                    if (_p && _p.elementID === _node.elementID) _isFitted = true;\n                }\n                if (_isFitted) _fitted.push(_n.getName());\n            }\n            return _fitted;\n            \n})()',
    );
  });

  it("geometryVertexCount() reads getGeometry().getNumVertices()", async () => {
    const fetchMock = stub(1234);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await node.geometryVertexCount()).toBe(1234);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\n\n            var obj = _node.getObject();\n            if (!obj) return null;\n            var shape = obj.getCurrentShape();\n            if (!shape) return null;\n            var geo = shape.getGeometry();\n            if (!geo) return null;\n            return geo.getNumVertices();\n        \n})()',
    );
  });
});
