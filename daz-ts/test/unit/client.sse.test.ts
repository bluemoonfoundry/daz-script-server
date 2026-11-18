import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient, parseSseStream } from "../../src/client.js";
import { AuthenticationError, ConnectionError, DazTimeoutError } from "../../src/exceptions.js";

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
  it("returns the streaming Response when the endpoint responds 200", async () => {
    const fakeResponse = new Response(sseBodyStream(["data: {}\n\n"]), { status: 200 });
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse);
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const resp = await client.streamRenderProgress("req-1");

    expect(resp?.status).toBe(200);
    expect(await resp!.text()).toBe("data: {}\n\n");
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/render/req-1/progress");
  });

  it("returns null when the endpoint answers with a non-auth error status", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 404 })));
    const client = new DazClient({ token: "" });
    expect(await client.streamRenderProgress("req-1")).toBeNull();
  });

  it("throws ConnectionError when the server is unreachable and AuthenticationError on 401", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("network down"))
      .mockResolvedValueOnce(new Response("bad token", { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await expect(client.streamRenderProgress("req-1")).rejects.toBeInstanceOf(ConnectionError);
    await expect(client.streamRenderProgress("req-2")).rejects.toBeInstanceOf(AuthenticationError);
  });

  it("timeoutMs bounds reading the stream, not just connecting", async () => {
    // A body that never ends: one event, then silence. fetch() honours the
    // abort signal for the body too, so stub it the same way.
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init: RequestInit) => {
        const signal = init.signal as AbortSignal;
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(new TextEncoder().encode("data: {}\n\n"));
            signal.addEventListener("abort", () => controller.error(signal.reason));
          },
        });
        return Promise.resolve(new Response(body, { status: 200 }));
      }),
    );

    const client = new DazClient({ token: "" });
    const resp = await client.streamRenderProgress("req-1", { timeoutMs: 20 });
    const reading = (async () => {
      for await (const _evt of parseSseStream(resp!)) {
        // drain until the timeout fires
      }
    })();
    await expect(reading).rejects.toBeInstanceOf(DazTimeoutError);
  });

  it("an external AbortSignal cancels the stream", async () => {
    const fetchMock = vi.fn((_url: string, init: RequestInit) => {
      const signal = init.signal as AbortSignal;
      return new Promise<Response>((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(signal.reason));
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const controller = new AbortController();
    const client = new DazClient({ token: "" });
    const opening = client.streamRenderProgress("req-1", { signal: controller.signal });
    const reason = new Error("stop");
    controller.abort(reason);
    await expect(opening).rejects.toBe(reason);
  });

  it("removes its listener from the caller's signal once the stream ends", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(sseBodyStream(["data: {}\n\n"]), { status: 200 })));
    const controller = new AbortController();
    const removeSpy = vi.spyOn(controller.signal, "removeEventListener");

    const client = new DazClient({ token: "" });
    const resp = await client.streamRenderProgress("req-1", { signal: controller.signal, timeoutMs: 60_000 });
    await resp!.text();

    expect(removeSpy).toHaveBeenCalledWith("abort", expect.any(Function));
  });

  it("closes the connection when the consumer stops reading early", async () => {
    let cancelled = false;
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(new TextEncoder().encode("data: 1\n\ndata: 2\n\n"));
      },
      cancel() {
        cancelled = true;
      },
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, { status: 200 })));

    const client = new DazClient({ token: "" });
    const resp = await client.streamSceneEvents();
    for await (const _evt of parseSseStream(resp!)) {
      break;
    }
    expect(cancelled).toBe(true);
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

  it("accepts CRLF and CR line endings, including a CRLF split across chunks", async () => {
    const response = new Response(
      sseBodyStream(['event: a\r\ndata: 1\r', '\n\r\n', 'data: 2\r\rdata: 3\n\n']),
      { status: 200 },
    );
    const events: Array<{ event: string; data: string }> = [];
    for await (const evt of parseSseStream(response)) {
      events.push(evt);
    }
    expect(events).toEqual([
      { event: "a", data: "1" },
      { event: "message", data: "2" },
      { event: "message", data: "3" },
    ]);
  });

  it("flushes an event whose terminating CR is the last byte of the stream", async () => {
    const response = new Response(sseBodyStream(["data: x\r\r"]), { status: 200 });
    const events: Array<{ event: string; data: string }> = [];
    for await (const evt of parseSseStream(response)) {
      events.push(evt);
    }
    expect(events).toEqual([{ event: "message", data: "x" }]);
  });
});
