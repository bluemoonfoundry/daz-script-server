import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient, FINAL_REQUEST_STATUSES } from "../../src/client.js";
import { AuthenticationError, ConnectionError, DazError, DazTimeoutError } from "../../src/exceptions.js";
import { jsonResponse } from "../helpers.js";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DazClient async job methods", () => {
  it("executeAsyncSubmit posts to /execute/async and returns request_id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ request_id: "abc123" }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const id = await client.executeAsyncSubmit("1+1;", { x: 1 });

    expect(id).toBe("abc123");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/execute/async");
    expect(JSON.parse(init.body as string)).toEqual({ script: "1+1;", args: { x: 1 } });
  });

  it("executeFileAsyncSubmit posts {scriptFile} to /execute/async", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ request_id: "abc456" }));
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
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ status: "running", progress: 0.5 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const status = await client.getRequestStatus("req-1");

    expect(status).toEqual({ status: "running", progress: 0.5 });
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/requests/req-1/status");
  });

  it("getRequestResult adds wait/timeout query params when wait=true", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ success: true, result: 5 }));
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
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ success: true, result: 5 }));
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

  it("cancelRequestDetail returns cancel_requested for a running script without cancelled_at", async () => {
    const body = {
      request_id: "req-1",
      status: "cancel_requested",
      message: "Cancel requested; the script is still running",
      cancel_requested_at: "2026-11-18T10:00:00",
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(body));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const resp = await client.cancelRequestDetail("req-1");

    expect(resp).toEqual(body);
    expect(resp.cancelled_at).toBeUndefined();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/requests/req-1");
    expect(init.method).toBe("DELETE");
  });

  it("cancelRequestDetail routes rnd- IDs to POST /render/{id}/cancel", async () => {
    const body = {
      request_id: "rnd-1",
      status: "cancelled",
      message: "Cancelled",
      cancel_requested_at: "2026-11-18T10:00:00",
      cancelled_at: "2026-11-18T10:00:00",
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(body));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    expect((await client.cancelRequestDetail("rnd-1")).status).toBe("cancelled");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/render/rnd-1/cancel");
    expect(init.method).toBe("POST");
  });

  it("cancelRequestDetail throws DazError for an unknown request and ConnectionError when unreachable", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ success: false, error_code: "REQUEST_NOT_FOUND", error: "Request not found", retryable: false }, 404),
      )
      .mockRejectedValueOnce(new TypeError("network down"));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const err = await client.cancelRequestDetail("req-x").catch((e) => e);
    expect(err).toBeInstanceOf(DazError);
    expect(err.message).toBe("Request not found");
    await expect(client.cancelRequestDetail("req-y")).rejects.toBeInstanceOf(ConnectionError);
  });

  it("FINAL_REQUEST_STATUSES excludes the non-final cancel_requested and stale", () => {
    expect([...FINAL_REQUEST_STATUSES].sort()).toEqual([
      "cancelled",
      "completed",
      "completed_after_cancel_request",
      "completed_after_stale",
      "failed",
    ]);
  });

  it("getRequestStatus/getRequestResult throw AuthenticationError on 401 instead of a JSON parse error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => new Response("token expired", { status: 401 })));
    const client = new DazClient({ token: "" });
    await expect(client.getRequestStatus("req-1")).rejects.toBeInstanceOf(AuthenticationError);
    await expect(client.getRequestResult("req-1", true)).rejects.toBeInstanceOf(AuthenticationError);
  });

  it("getRequestResult with wait=true allows the long-poll wait plus margin, not just the client timeout", async () => {
    vi.useFakeTimers();
    try {
      let signal: AbortSignal | undefined;
      vi.stubGlobal(
        "fetch",
        vi.fn((_url: string, init: RequestInit) => {
          signal = init.signal as AbortSignal;
          return new Promise<Response>((resolve, reject) => {
            signal!.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
            setTimeout(() => resolve(jsonResponse({ status: "running" })), 25_000);
          });
        }),
      );
      const client = new DazClient({ token: "", timeoutMs: 1_000 });
      const pending = client.getRequestResult("req-1", true, 30);
      await vi.advanceTimersByTimeAsync(25_000);
      await expect(pending).resolves.toEqual({ status: "running" });
      expect(signal?.aborted).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it("the client timeout also bounds reading the response body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init: RequestInit) => {
        const signal = init.signal as AbortSignal;
        // Headers arrive at once; the body never finishes.
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(new TextEncoder().encode('{"status":'));
            signal.addEventListener("abort", () => controller.error(new DOMException("aborted", "AbortError")));
          },
        });
        return Promise.resolve(new Response(body, { status: 200 }));
      }),
    );
    const client = new DazClient({ token: "", timeoutMs: 20 });
    await expect(client.getRequestStatus("req-1")).rejects.toBeInstanceOf(DazTimeoutError);
  });
});
