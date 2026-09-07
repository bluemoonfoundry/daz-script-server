import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { RenderError, DazTimeoutError } from "../../src/exceptions.js";
import { render, renderVariants } from "../../src/renderApi.js";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function sseBodyStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("render()", () => {
  it("submits then completes from a 'complete' SSE event", async () => {
    const fetchMock = vi.fn();
    // /render submit
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { request_id: "r1", status: "queued" }));
    // /render/r1/progress SSE stream
    fetchMock.mockResolvedValueOnce(
      new Response(
        sseBodyStream(['event: complete\ndata: {"output_path":"C:\\\\out.png","file_size_bytes":1234,"duration_ms":500}\n\n']),
        { status: 200 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const result = await render(client, "C:\\out.png", { width: 512, height: 512 });

    expect(result).toEqual({
      success: true,
      outputPath: "C:\\out.png",
      fileSizeBytes: 1234,
      durationMs: 500,
      error: "",
      requestId: "r1",
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [submitUrl] = fetchMock.mock.calls[0];
    expect(submitUrl).toBe("http://127.0.0.1:18811/render");
  });

  it("throws RenderError from an 'error' SSE event", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { request_id: "r1", status: "queued" }));
    fetchMock.mockResolvedValueOnce(
      new Response(sseBodyStream(['event: error\ndata: {"error":"Camera not found"}\n\n']), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await expect(render(client, "C:\\out.png")).rejects.toThrow(RenderError);
  });

  it("invokes onProgress for 'progress' SSE events before completing", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { request_id: "r1", status: "queued" }));
    fetchMock.mockResolvedValueOnce(
      new Response(
        sseBodyStream([
          'event: progress\ndata: {"percent":25,"frame":1,"total_frames":4}\n\n',
          'event: complete\ndata: {"output_path":"C:\\\\out.png"}\n\n',
        ]),
        { status: 200 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const progressEvents: Array<Record<string, unknown>> = [];
    const client = new DazClient({ token: "" });
    await render(client, "C:\\out.png", { onProgress: (data) => progressEvents.push(data) });

    expect(progressEvents).toEqual([{ percent: 25, frame: 1, total_frames: 4 }]);
  });

  it("falls back to result polling when the SSE endpoint is unavailable", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { request_id: "r1", status: "queued" }));
    // streamRenderProgress returns null (404) -> falls through to polling
    fetchMock.mockResolvedValueOnce(new Response("", { status: 404 }));
    // getRequestResult(wait=true) -> completed
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, { success: true, result: { output_path: "C:\\out.png" }, duration_ms: 750 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const result = await render(client, "C:\\out.png");

    expect(result).toEqual({
      success: true,
      outputPath: "C:\\out.png",
      fileSizeBytes: -1,
      durationMs: 750,
      error: "",
      requestId: "r1",
    });
  });

  it("polling fallback throws RenderError when the request result reports failure", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { request_id: "r1", status: "queued" }));
    fetchMock.mockResolvedValueOnce(new Response("", { status: 404 }));
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { success: false, error: "Out of memory" }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await expect(render(client, "C:\\out.png")).rejects.toThrow(RenderError);
  });

  it("returns immediately without waiting when wait=false", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(200, { request_id: "r1", status: "queued" }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const result = await render(client, "C:\\out.png", { wait: false });

    expect(result).toEqual({
      success: true,
      outputPath: "C:\\out.png",
      fileSizeBytes: -1,
      durationMs: 0,
      error: "",
      requestId: "r1",
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("renderVariants()", () => {
  it("submits a batch and waits for each variant's SSE completion in order", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { request_ids: ["r1", "r2"] }));
    fetchMock.mockResolvedValueOnce(
      new Response(sseBodyStream(['event: complete\ndata: {"output_path":"C:\\\\a.png"}\n\n']), { status: 200 }),
    );
    fetchMock.mockResolvedValueOnce(
      new Response(sseBodyStream(['event: complete\ndata: {"output_path":"C:\\\\b.png"}\n\n']), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const progressCalls: Array<[number, number]> = [];
    const client = new DazClient({ token: "" });
    const results = await renderVariants(
      client,
      [
        { outputPath: "C:\\a.png", figure: "Genesis 9", morphs: { Smile: 1.0 } },
        { outputPath: "C:\\b.png", figure: "Genesis 9" },
      ],
      { width: 1920, height: 1080, engine: "iray" },
      { onProgress: (done, total) => progressCalls.push([done, total]) },
    );

    expect(results.map((r) => r.outputPath)).toEqual(["C:\\a.png", "C:\\b.png"]);
    expect(results.every((r) => r.success)).toBe(true);
    expect(progressCalls).toEqual([
      [1, 2],
      [2, 2],
    ]);

    const [batchUrl, batchInit] = fetchMock.mock.calls[0];
    expect(batchUrl).toBe("http://127.0.0.1:18811/render/batch");
    expect(JSON.parse(batchInit.body as string)).toEqual({
      variants: [
        { output_path: "C:\\a.png", figure: "Genesis 9", morphs: { Smile: 1.0 } },
        { output_path: "C:\\b.png", figure: "Genesis 9" },
      ],
      base: { width: 1920, height: 1080, engine: "iray" },
    });
  });

  it("records a failed variant but still attempts the rest", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { request_ids: ["r1", "r2"] }));
    fetchMock.mockResolvedValueOnce(
      new Response(sseBodyStream(['event: error\ndata: {"error":"bad morph"}\n\n']), { status: 200 }),
    );
    fetchMock.mockResolvedValueOnce(
      new Response(sseBodyStream(['event: complete\ndata: {"output_path":"C:\\\\b.png"}\n\n']), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const results = await renderVariants(client, [{ outputPath: "C:\\a.png" }, { outputPath: "C:\\b.png" }]);

    expect(results[0]).toEqual({
      success: false,
      outputPath: "C:\\a.png",
      fileSizeBytes: -1,
      durationMs: 0,
      error: "bad morph",
      requestId: "r1",
    });
    expect(results[1].success).toBe(true);
  });
});
