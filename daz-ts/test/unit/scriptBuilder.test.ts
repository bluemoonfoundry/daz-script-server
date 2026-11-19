import { describe, expect, it } from "vitest";
import type { NodeIdentifier } from "../../src/node.js";
import { ScriptBuilder } from "../../src/scriptBuilder.js";

describe("ScriptBuilder", () => {
  it("escapeString produces a JSON-quoted, embeddable string literal", () => {
    expect(ScriptBuilder.escapeString("hello")).toBe('"hello"');
    expect(ScriptBuilder.escapeString('a"b\\c')).toBe('"a\\"b\\\\c"');
    expect(ScriptBuilder.escapeString("line1\nline2")).toBe('"line1\\nline2"');
  });

  it("iife wraps a body in an immediately-invoked function expression", () => {
    expect(ScriptBuilder.iife("return 1;")).toBe("(function(){\nreturn 1;\n})()");
  });

  it("serializeArg formats booleans as bare true/false", () => {
    expect(ScriptBuilder.serializeArg(true)).toBe("true");
    expect(ScriptBuilder.serializeArg(false)).toBe("false");
  });

  it("serializeArg formats numbers as bare literals", () => {
    expect(ScriptBuilder.serializeArg(42)).toBe("42");
    expect(ScriptBuilder.serializeArg(3.14)).toBe("3.14");
  });

  it("serializeArg formats strings as JSON-quoted literals", () => {
    expect(ScriptBuilder.serializeArg("hi")).toBe('"hi"');
  });

  it("serializeArg falls back to JSON.stringify for objects and arrays", () => {
    expect(ScriptBuilder.serializeArg({ a: 1, b: "x" })).toBe('{"a":1,"b":"x"}');
    expect(ScriptBuilder.serializeArg([1, 2, 3])).toBe("[1,2,3]");
    expect(ScriptBuilder.serializeArg(null)).toBe("null");
  });
});

describe("ScriptBuilder node helpers", () => {
  it("findNodeExpr uses Scene.findNode for kind 'name'", () => {
    const id: NodeIdentifier = { value: "Genesis9", kind: "name" };
    expect(ScriptBuilder.findNodeExpr(id)).toBe('Scene.findNode("Genesis9")');
  });

  it("findNodeExpr uses Scene.findNodeByLabel for kind 'label'", () => {
    const id: NodeIdentifier = { value: "Genesis 9", kind: "label" };
    expect(ScriptBuilder.findNodeExpr(id)).toBe('Scene.findNodeByLabel("Genesis 9")');
  });

  it("nodeBody wraps body with a null-checked _node binding", () => {
    const id: NodeIdentifier = { value: "Genesis9", kind: "name" };
    expect(ScriptBuilder.nodeBody(id, "return _node.getLabel();")).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\nreturn _node.getLabel();\n})()',
    );
  });

  it("nodeBodyFromLocator wraps body around a pre-built locator", () => {
    expect(ScriptBuilder.nodeBodyFromLocator("LOC", "return 1;")).toBe(
      "(function(){\nvar _node = LOC;\nif (!_node) return null;\nreturn 1;\n})()",
    );
  });

  it("skeletonLookup matches by label when kind is 'label', by name otherwise, without wrapping in an IIFE", () => {
    const byLabel: NodeIdentifier = { value: "Genesis 9", kind: "label" };
    expect(ScriptBuilder.skeletonLookup(byLabel)).toBe(
      'var _skel=null,_skels=Scene.getSkeletonList();for(var _i=0;_i<_skels.length;_i++){if(_skels[_i].getLabel() === "Genesis 9"){_skel=_skels[_i];break;}}',
    );
    const byName: NodeIdentifier = { value: "Genesis9", kind: "name" };
    expect(ScriptBuilder.skeletonLookup(byName)).toBe(
      'var _skel=null,_skels=Scene.getSkeletonList();for(var _i=0;_i<_skels.length;_i++){if(_skels[_i].getName() === "Genesis9"){_skel=_skels[_i];break;}}',
    );
  });

  it("skeletonLookupAsNode matches like skeletonLookup but binds _node instead of _skel", () => {
    const byLabel: NodeIdentifier = { value: "Genesis 9", kind: "label" };
    expect(ScriptBuilder.skeletonLookupAsNode(byLabel)).toBe(
      'var _node=null,_skels=Scene.getSkeletonList();for(var _i=0;_i<_skels.length;_i++){if(_skels[_i].getLabel() === "Genesis 9"){_node=_skels[_i];break;}}',
    );
    const byName: NodeIdentifier = { value: "Genesis9", kind: "name" };
    expect(ScriptBuilder.skeletonLookupAsNode(byName)).toBe(
      'var _node=null,_skels=Scene.getSkeletonList();for(var _i=0;_i<_skels.length;_i++){if(_skels[_i].getName() === "Genesis9"){_node=_skels[_i];break;}}',
    );
  });
});
