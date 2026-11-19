import { describe, expect, it } from "vitest";
import {
  AsyncExecutionError,
  AuthenticationError,
  BatchLimitExceededError,
  ConcurrencyLimitError,
  ConnectionError,
  DazBusyError,
  DazError,
  DazTimeoutError,
  MaterialError,
  NodeNotFoundError,
  RenderError,
  ScriptError,
  ScriptRuntimeError,
  ScriptSyntaxError,
  StudioBusyError,
} from "../../src/exceptions.js";

describe("exception hierarchy", () => {
  it("DazError is the base of every exception and extends Error", () => {
    const e = new DazError("boom");
    expect(e).toBeInstanceOf(Error);
    expect(e.message).toBe("boom");
  });

  it("StudioBusyError and ConcurrencyLimitError extend DazBusyError with reason/retryAfter", () => {
    const busy = new StudioBusyError("busy", "scene is loading", 3.5);
    expect(busy).toBeInstanceOf(DazBusyError);
    expect(busy).toBeInstanceOf(DazError);
    expect(busy.reason).toBe("scene is loading");
    expect(busy.retryAfter).toBe(3.5);

    const limit = new ConcurrencyLimitError("too many requests");
    expect(limit).toBeInstanceOf(DazBusyError);
    expect(limit.retryAfter).toBe(2.0); // default
  });

  it("ScriptSyntaxError and ScriptRuntimeError extend ScriptError and carry diagnostic info", () => {
    const err = new ScriptRuntimeError(
      "Line 3: TypeError: x is not a function",
      "1+1;\n2+2;\nx();",
      "req-123",
      ["log line 1", "log line 2"],
    );
    expect(err).toBeInstanceOf(ScriptError);
    expect(err.script).toContain("x();");
    expect(err.requestId).toBe("req-123");
    expect(err.output).toEqual(["log line 1", "log line 2"]);
    expect(err.diagnostic).toContain("   1: 1+1;");
    expect(err.diagnostic).toContain("   3: x();");
    expect(err.diagnostic).toContain("TypeError");
    expect(err.diagnostic).toContain("Captured output:");
    expect(err.diagnostic).toContain("request_id: req-123");

    const syntaxErr = new ScriptSyntaxError("SyntaxError: unexpected token");
    expect(syntaxErr).toBeInstanceOf(ScriptError);
  });

  it("AsyncExecutionError and RenderError carry requestId", () => {
    const e1 = new AsyncExecutionError("failed", "req-1");
    expect(e1.requestId).toBe("req-1");
    const e2 = new RenderError("render failed", "req-2");
    expect(e2.requestId).toBe("req-2");
  });

  it("MaterialError carries requestId", () => {
    const e = new MaterialError("bad material", "req-3");
    expect(e.requestId).toBe("req-3");
  });

  it("simple leaf exceptions extend DazError", () => {
    for (const Cls of [ConnectionError, AuthenticationError, DazTimeoutError, NodeNotFoundError, BatchLimitExceededError]) {
      const e = new Cls("x");
      expect(e).toBeInstanceOf(DazError);
    }
  });
});
