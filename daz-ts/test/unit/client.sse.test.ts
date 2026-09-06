import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient, parseSseStream } from "../../src/client.js";

afterEach(() => {
  vi.unstubAllGlobals();
});

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

describe("DazClient.streamRenderProgress", () => {
  it("returns the raw Response when the endpoint responds 200", async () => {
    const fakeResponse = new Response(sseBodyStream(["data: {}\n\n"]), { status: 200 });
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse);
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const resp = await client.streamRenderProgress("req-1");

    expect(resp).toBe(fakeResponse);
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/render/req-1/progress");
  });

  it("returns null when the endpoint is unavailable or errors", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("", { status: 404 }))
      .mockRejectedValueOnce(new TypeError("network down"));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    expect(await client.streamRenderProgress("req-1")).toBeNull();
    expect(await client.streamRenderProgress("req-2")).toBeNull();
  });
});

describe("DazClient.streamSceneEvents", () => {
  it("joins categories into a comma-separated filter query param when provided", async () => {
    const fakeResponse = new Response(sseBodyStream(["data: {}\n\n"]), { status: 200 });
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse);
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await client.streamSceneEvents(["node", "camera"]);

    const [url] = fetchMock.mock.calls[0];
    const parsed = new URL(url as string);
    expect(parsed.pathname).toBe("/scene/events");
    expect(parsed.searchParams.get("filter")).toBe("node,camera");
  });

  it("omits the filter param when categories is not provided", async () => {
    const fakeResponse = new Response(sseBodyStream(["data: {}\n\n"]), { status: 200 });
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse);
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await client.streamSceneEvents();

    const [url] = fetchMock.mock.calls[0];
    expect(new URL(url as string).search).toBe("");
  });
});

describe("parseSseStream", () => {
  it("yields parsed event/data pairs from an SSE byte stream, skipping keepalive comments", async () => {
    const response = new Response(
      sseBodyStream([
        ": keepalive\n\n",
        'event: node\ndata: {"id":"1"}\n\n',
        'data: {"id":"2"}\n\n',
      ]),
      { status: 200 },
    );

    const events: Array<{ event: string; data: string }> = [];
    for await (const evt of parseSseStream(response)) {
      events.push(evt);
    }

    expect(events).toEqual([
      { event: "node", data: '{"id":"1"}' },
      { event: "message", data: '{"id":"2"}' },
    ]);
  });
});
