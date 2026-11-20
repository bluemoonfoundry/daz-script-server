import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import {
  AuthenticationError,
  ConnectionError,
  DazError,
  ScriptRuntimeError,
  ScriptSyntaxError,
  StudioBusyError,
} from "../../src/exceptions.js";
import { jsonResponse } from "../helpers.js";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DazClient construction", () => {
  it("uses 127.0.0.1:18811 by default and an explicit empty token disables auth", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ success: true, result: 2, output: [], request_id: "r1", duration_ms: 1.2 }),
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
      jsonResponse({ success: true, result: null, output: [], request_id: "r1", duration_ms: 0 }),
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
      jsonResponse({ success: true, result: 4, output: ["hi"], request_id: "req-1", duration_ms: 5.5 }),
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
      jsonResponse({ success: true, result: null, output: [], request_id: "", duration_ms: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await client.execute("f();", { count: 3 });

    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body as string)).toEqual({ script: "f();", args: { count: 3 } });
  });

  it("throws ScriptSyntaxError when success is false and error mentions SyntaxError", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ success: false, error: "Line 1: SyntaxError: unexpected token", output: [], request_id: "r2" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await expect(client.execute("(;")).rejects.toBeInstanceOf(ScriptSyntaxError);
  });

  it("throws ScriptRuntimeError when success is false and error does not mention SyntaxError", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ success: false, error: "Line 1: TypeError: x is not a function", output: ["log"], request_id: "r3" }),
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

  it("keeps ErrorResponse fields on AuthenticationError (W13)", async () => {
    const body = {
      success: false,
      error_code: "AUTH_INVALID_TOKEN",
      error: "Invalid API token",
      retryable: false,
      detail: "token mismatch",
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(body, 401)));
    const client = new DazClient({ token: "bad" });
    const err = (await client.execute("1;").catch((e: unknown) => e)) as AuthenticationError;
    expect(err).toBeInstanceOf(AuthenticationError);
    expect(err.statusCode).toBe(401);
    expect(err.errorCode).toBe("AUTH_INVALID_TOKEN");
    expect(err.detail).toBe("token mismatch");
    expect(err.retryable).toBe(false);
    expect(err.message).toBe("HTTP 401: Invalid API token");
  });

  it("keeps ErrorResponse fields on 403 from direct-check routes and falls back to text", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ error_code: "IP_NOT_WHITELISTED", error: "IP not allowed" }, 403)),
    );
    const client = new DazClient({ token: "" });
    const err = (await client.status().catch((e: unknown) => e)) as AuthenticationError;
    expect(err.statusCode).toBe(403);
    expect(err.errorCode).toBe("IP_NOT_WHITELISTED");
    expect(err.detail).toBe("");

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("Unauthorized", { status: 401 })));
    const plain = (await client.execute("1;").catch((e: unknown) => e)) as AuthenticationError;
    expect(plain.errorCode).toBe("");
    expect(plain.message).toBe("HTTP 401: Unauthorized");
  });

  it("throws StudioBusyError on HTTP 503 with STUDIO_BUSY error_code", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ error: "busy", error_code: "STUDIO_BUSY", detail: "scene is loading" }, 503, { "Retry-After": "4" }),
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

  it("throws ScriptRuntimeError on generic HTTP 200 with success: false and no recognized error_code", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ success: false, error: "malformed script", output: ["log"], request_id: "r5" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const err = await client.execute("bad script").catch((e) => e);
    expect(err).toBeInstanceOf(ScriptRuntimeError);
    expect(err.message).toBe("malformed script");
    expect(err.output).toEqual(["log"]);
  });

  it("maps response body correctly even when raiseForError consumes it for error checking", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ success: false, error: "some error", output: [], request_id: "r6" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const err = await client.execute("1;").catch((e) => e);
    expect(err).toBeInstanceOf(ScriptRuntimeError);
    expect(err.message).toBe("some error");
    expect(err.requestId).toBe("r6");
  });

  it("maps a non-JSON error body (e.g. a 502 from a proxy) to DazError, not a JSON parse error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("<html>Bad Gateway</html>", { status: 502, statusText: "Bad Gateway" })),
    );
    const client = new DazClient({ token: "" });
    const err = await client.execute("1;").catch((e) => e);
    expect(err).toBeInstanceOf(DazError);
    expect(err).not.toBeInstanceOf(SyntaxError);
    expect(err.message).toBe("HTTP 502: <html>Bad Gateway</html>");
  });
});

describe("DazClient.executeFile", () => {
  it("posts {scriptFile} (not {script}) and maps the response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ success: true, result: "ok", output: [], request_id: "r4", duration_ms: 2 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const result = await client.executeFile("C:\\scripts\\a.dsa");

    expect(result.value).toBe("ok");
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body as string)).toEqual({ scriptFile: "C:\\scripts\\a.dsa" });
  });
});
