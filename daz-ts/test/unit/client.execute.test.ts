import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import {
  AuthenticationError,
  ConnectionError,
  ScriptRuntimeError,
  ScriptSyntaxError,
  StudioBusyError,
} from "../../src/exceptions.js";

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DazClient construction", () => {
  it("uses 127.0.0.1:18811 by default and an explicit empty token disables auth", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(200, { success: true, result: 2, output: [], request_id: "r1", duration_ms: 1.2 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await client.execute("1+1;");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/execute");
    expect((init.headers as Record<string, string>)["X-API-Token"]).toBeUndefined();
  });

  it("sends an explicit token as the X-API-Token header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(200, { success: true, result: null, output: [], request_id: "r1", duration_ms: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "secret-token" });
    await client.execute("1;");

    const [, init] = fetchMock.mock.calls[0];
    expect((init.headers as Record<string, string>)["X-API-Token"]).toBe("secret-token");
  });
});

describe("DazClient.execute", () => {
  it("posts {script} and returns a mapped ExecutionResult on success", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(200, { success: true, result: 4, output: ["hi"], request_id: "req-1", duration_ms: 5.5 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const result = await client.execute("2+2;");

    expect(result).toEqual({
      value: 4,
      output: ["hi"],
      requestId: "req-1",
      success: true,
      error: "",
      durationMs: 5.5,
    });
    const [, init] = fetchMock.mock.calls[0];
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ script: "2+2;" });
  });

  it("includes args in the payload when provided", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(200, { success: true, result: null, output: [], request_id: "", duration_ms: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await client.execute("f();", { count: 3 });

    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body as string)).toEqual({ script: "f();", args: { count: 3 } });
  });

  it("throws ScriptSyntaxError when success is false and error mentions SyntaxError", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(200, { success: false, error: "Line 1: SyntaxError: unexpected token", output: [], request_id: "r2" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await expect(client.execute("(;")).rejects.toBeInstanceOf(ScriptSyntaxError);
  });

  it("throws ScriptRuntimeError when success is false and error does not mention SyntaxError", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(200, { success: false, error: "Line 1: TypeError: x is not a function", output: ["log"], request_id: "r3" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const err = await client.execute("x();").catch((e) => e);
    expect(err).toBeInstanceOf(ScriptRuntimeError);
    expect(err.script).toBe("x();");
    expect(err.requestId).toBe("r3");
    expect(err.output).toEqual(["log"]);
  });

  it("throws AuthenticationError on HTTP 401", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("bad token", { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "bad" });
    await expect(client.execute("1;")).rejects.toBeInstanceOf(AuthenticationError);
  });

  it("throws StudioBusyError on HTTP 503 with STUDIO_BUSY error_code", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(503, { error: "busy", error_code: "STUDIO_BUSY", detail: "scene is loading" }, { "Retry-After": "4" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const err = await client.execute("1;").catch((e) => e);
    expect(err).toBeInstanceOf(StudioBusyError);
    expect(err.reason).toBe("scene is loading");
    expect(err.retryAfter).toBe(4);
  });

  it("throws ConnectionError when fetch rejects with a network failure", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("fetch failed"));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await expect(client.execute("1;")).rejects.toBeInstanceOf(ConnectionError);
  });
});

describe("DazClient.executeFile", () => {
  it("posts {scriptFile} (not {script}) and maps the response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(200, { success: true, result: "ok", output: [], request_id: "r4", duration_ms: 2 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const result = await client.executeFile("C:\\scripts\\a.dsa");

    expect(result.value).toBe("ok");
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body as string)).toEqual({ scriptFile: "C:\\scripts\\a.dsa" });
  });
});
