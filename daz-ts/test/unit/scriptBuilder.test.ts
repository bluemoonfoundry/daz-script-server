import { describe, expect, it } from "vitest";
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
