import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { AsyncExecutionError, DazTimeoutError } from "../../src/exceptions.js";
import { executeLong } from "../../src/polling.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("executeLong", () => {
  it("submits async then returns a mapped result once the poll reports success", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ request_id: "req-1" })) // /execute/async
      .mockResolvedValueOnce(jsonResponse({ success: true, result: 42, output: ["ok"], duration_ms: 100 })); // /requests/:id/result
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const result = await executeLong(client, "longRunning();");

    expect(result).toEqual({
      value: 42,
      output: ["ok"],
      requestId: "req-1",
      success: true,
      error: "",
      durationMs: 100,
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("throws AsyncExecutionError when the polled result reports success: false", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ request_id: "req-1" }))
      .mockResolvedValueOnce(jsonResponse({ success: false, error: "boom" }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await expect(executeLong(client, "x();")).rejects.toBeInstanceOf(AsyncExecutionError);
  });

  it("throws AsyncExecutionError when the request is reported cancelled", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ request_id: "req-1" }))
      .mockResolvedValueOnce(jsonResponse({ status: "cancelled" }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const err = await executeLong(client, "x();").catch((e) => e);
    expect(err).toBeInstanceOf(AsyncExecutionError);
    expect(err.message).toMatch(/cancelled/i);
  });

  it("polls again on a non-terminal status before eventually succeeding", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ request_id: "req-1" }))
      .mockResolvedValueOnce(jsonResponse({ status: "running" }))
      .mockResolvedValueOnce(jsonResponse({ success: true, result: "done", output: [], duration_ms: 5 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const result = await executeLong(client, "x();", undefined, { pollIntervalMs: 1 });

    expect(result.value).toBe("done");
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("throws DazTimeoutError when the timeout elapses before completion", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ request_id: "req-1" }))
      .mockImplementation(() => jsonResponse({ status: "running" }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await expect(
      executeLong(client, "x();", undefined, { timeoutMs: 5, pollIntervalMs: 1 }),
    ).rejects.toBeInstanceOf(DazTimeoutError);
  });
});
