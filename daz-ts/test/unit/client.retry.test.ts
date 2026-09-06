import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { StudioBusyError } from "../../src/exceptions.js";

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
}

function busyResponse(): Response {
  return jsonResponse(503, { error: "busy", error_code: "STUDIO_BUSY", detail: "scene is loading" });
}

function successResponse(): Response {
  return jsonResponse(200, { success: true, result: 42, output: [], request_id: "r1", duration_ms: 1 });
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("DazClient withBusyRetry (via execute)", () => {
  it("retryOnBusy: true retries after a StudioBusyError and eventually returns the success result", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(busyResponse()).mockResolvedValueOnce(successResponse());
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const resultPromise = client.execute("1+1;", undefined, { retryOnBusy: true, maxWait: 30 });

    // Let the first (busy) attempt run, then advance past the backoff sleep.
    await vi.advanceTimersByTimeAsync(1000);

    const result = await resultPromise;
    expect(result.value).toBe(42);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("backs off with increasing linear delays (1s, then 2s) across repeated busy responses", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(busyResponse())
      .mockResolvedValueOnce(busyResponse())
      .mockResolvedValueOnce(successResponse());
    vi.stubGlobal("fetch", fetchMock);

    const setTimeoutSpy = vi.spyOn(globalThis, "setTimeout");

    const client = new DazClient({ token: "" });
    const resultPromise = client.execute("1+1;", undefined, { retryOnBusy: true, maxWait: 30 });

    await vi.advanceTimersByTimeAsync(1000); // first backoff: 1s
    await vi.advanceTimersByTimeAsync(2000); // second backoff: 1+1=2s

    const result = await resultPromise;
    expect(result.value).toBe(42);
    expect(fetchMock).toHaveBeenCalledTimes(3);

    // Collect the delays passed to setTimeout that correspond to backoff sleeps
    // (i.e. not the per-request AbortController timeout, which uses timeoutMs=30000).
    const backoffDelays = setTimeoutSpy.mock.calls.map(([, delay]) => delay).filter((d) => d !== undefined && d < 30_000);
    expect(backoffDelays).toEqual([1000, 2000]);
  });

  it("re-throws the original StudioBusyError once maxWait elapses, without swallowing it", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => busyResponse());
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const resultPromise = client.execute("1+1;", undefined, { retryOnBusy: true, maxWait: 2 });

    const assertion = expect(resultPromise).rejects.toBeInstanceOf(StudioBusyError);
    await vi.advanceTimersByTimeAsync(10_000);
    await assertion;

    // Confirm it re-threw the busy error itself (message/reason intact), not some other error type.
    const err = await resultPromise.catch((e) => e);
    expect(err).toBeInstanceOf(StudioBusyError);
    expect(err.reason).toBe("scene is loading");
  });

  it("retryOnBusy: false (the default) does not retry - a single StudioBusyError propagates immediately", async () => {
    const fetchMock = vi.fn().mockResolvedValue(busyResponse());
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await expect(client.execute("1+1;")).rejects.toBeInstanceOf(StudioBusyError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
