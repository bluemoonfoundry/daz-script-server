import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { AuthenticationError } from "../../src/exceptions.js";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DazClient async job methods", () => {
  it("executeAsyncSubmit posts to /execute/async and returns request_id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { request_id: "abc123" }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const id = await client.executeAsyncSubmit("1+1;", { x: 1 });

    expect(id).toBe("abc123");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/execute/async");
    expect(JSON.parse(init.body as string)).toEqual({ script: "1+1;", args: { x: 1 } });
  });

  it("executeFileAsyncSubmit posts {scriptFile} to /execute/async", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { request_id: "abc456" }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const id = await client.executeFileAsyncSubmit("C:\\a.dsa");

    expect(id).toBe("abc456");
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body as string)).toEqual({ scriptFile: "C:\\a.dsa" });
  });

  it("getRequestStatus returns {status: 'not_found'} on 404", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("", { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const status = await client.getRequestStatus("missing");

    expect(status).toEqual({ status: "not_found" });
  });

  it("getRequestStatus returns the parsed body on success", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { status: "running", progress: 0.5 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const status = await client.getRequestStatus("req-1");

    expect(status).toEqual({ status: "running", progress: 0.5 });
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/requests/req-1/status");
  });

  it("getRequestResult adds wait/timeout query params when wait=true", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { success: true, result: 5 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await client.getRequestResult("req-1", true, 15);

    const [url] = fetchMock.mock.calls[0];
    const parsed = new URL(url as string);
    expect(parsed.pathname).toBe("/requests/req-1/result");
    expect(parsed.searchParams.get("wait")).toBe("true");
    expect(parsed.searchParams.get("timeout")).toBe("15");
  });

  it("getRequestResult omits query params when wait is not requested", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { success: true, result: 5 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await client.getRequestResult("req-1");

    const [url] = fetchMock.mock.calls[0];
    const parsed = new URL(url as string);
    expect(parsed.search).toBe("");
  });

  it("listRequests passes an optional status filter and throws AuthenticationError on 401", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("nope", { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "bad" });
    await expect(client.listRequests("queued")).rejects.toBeInstanceOf(AuthenticationError);

    const [url] = fetchMock.mock.calls[0];
    expect(new URL(url as string).searchParams.get("status")).toBe("queued");
  });

  it("cancelRequest returns true on HTTP 200 and false otherwise", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("", { status: 200 }))
      .mockResolvedValueOnce(new Response("", { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    expect(await client.cancelRequest("req-1")).toBe(true);
    expect(await client.cancelRequest("req-2")).toBe(false);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/requests/req-1");
    expect(init.method).toBe("DELETE");
  });

  it("cancelRequest returns false on a network error", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("network down"));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    expect(await client.cancelRequest("req-1")).toBe(false);
  });
});
