import { afterEach, describe, expect, it, vi } from "vitest";
import { Batch, buildOperationsScript } from "../../src/batch.js";
import { DazClient } from "../../src/client.js";
import { BatchLimitExceededError } from "../../src/exceptions.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("buildOperationsScript", () => {
  it("builds one IIFE returning a keyed object over _r0, _r1, ...", () => {
    const script = buildOperationsScript([
      [["var x = 1;"], "x"],
      [["var y = 2;"], "y"],
    ]);
    expect(script).toBe(
      '(function(){\nvar x = 1;\nvar _r0 = x;\nvar y = 2;\nvar _r1 = y;\nreturn {"_r0": _r0, "_r1": _r1};\n})()',
    );
  });
});

describe("BatchFuture", () => {
  it("throws when .value is read before the batch executes", async () => {
    const client = new DazClient({ token: "" });
    const batch = new Batch(client);
    const future = batch.addOperation(["var x = 1;"], "x");
    expect(() => future.value).toThrow(/has not been executed/i);
  });
});

describe("Batch", () => {
  it("issues exactly one HTTP call for multiple operations and resolves every future", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ success: true, result: { _r0: 42, _r1: "hi" }, output: [], request_id: "r1", duration_ms: 1 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const batch = new Batch(client);
    const f1 = batch.addOperation(["var a = 40 + 2;"], "a");
    const f2 = batch.addOperation(["var b = 'hi';"], "b");
    await batch.execute();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(f1.value).toBe(42);
    expect(f2.value).toBe("hi");
  });

  it("does nothing (no HTTP call) when execute() is called with no queued operations", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const batch = new Batch(client);
    await batch.execute();

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("as an async context-like helper: execute() resolves futures added via add()", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ success: true, result: { _r0: [1, 2, 3] }, output: [], request_id: "r1", duration_ms: 1 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const batch = new Batch(client);
    const future = batch.add(["var _r0 = [1,2,3];"]);
    await batch.execute();

    expect(future.value).toEqual([1, 2, 3]);
  });

  it("emits a shared prelude only once even when referenced by multiple operations", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ success: true, result: { _r0: 1, _r1: 2 }, output: [], request_id: "r1", duration_ms: 1 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const batch = new Batch(client);
    batch.addPrelude("node:Fig", ["var _node = Scene.findNode('Fig');"]);
    batch.addPrelude("node:Fig", ["var _node = Scene.findNode('Fig');"]); // no-op, same key
    batch.addOperation(["var a = 1;"], "a");
    batch.addOperation(["var b = 2;"], "b");
    await batch.execute();

    const [, init] = fetchMock.mock.calls[0];
    const script = JSON.parse(init.body as string).script as string;
    const occurrences = script.split("Scene.findNode('Fig')").length - 1;
    expect(occurrences).toBe(1);
  });

  it("addOperation raises BatchLimitExceededError client-side once maxOperations is reached", () => {
    const client = new DazClient({ token: "" });
    const batch = new Batch(client, { maxOperations: 1 });
    batch.addOperation(["var a = 1;"], "a");
    expect(() => batch.addOperation(["var b = 2;"], "b")).toThrow(BatchLimitExceededError);
  });

  it("execute() raises BatchLimitExceededError before any HTTP call when the script is too long", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const batch = new Batch(client, { maxScriptLength: 10 });
    batch.addOperation(["var a = 1;"], "a");

    await expect(batch.execute()).rejects.toBeInstanceOf(BatchLimitExceededError);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("DazClient.executeBatchAsync", () => {
  it("builds one combined script and submits it via /execute/async", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ request_id: "async-1" }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const id = await client.executeBatchAsync([
      { bodyLines: ["var a = 1;"], resultExpression: "a" },
      { bodyLines: ["var b = 2;"], resultExpression: "b" },
    ]);

    expect(id).toBe("async-1");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/execute/async");
    const body = JSON.parse(init.body as string);
    expect(body.script).toContain("_r0");
    expect(body.script).toContain("_r1");
  });
});
