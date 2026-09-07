import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { ConnectionError, DazTimeoutError } from "../../src/exceptions.js";
import { waitForSceneEvent, watchSceneEvents } from "../../src/sceneEvents.js";

afterEach(() => vi.unstubAllGlobals());

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

async function collect<T>(gen: AsyncGenerator<T>): Promise<T[]> {
  const out: T[] = [];
  for await (const item of gen) out.push(item);
  return out;
}

describe("watchSceneEvents", () => {
  it("parses SSE data payloads into typed SceneEvent objects", async () => {
    const fakeResponse = new Response(
      sseBodyStream([
        'data: {"type":"node.added","ts":100,"data":{"name":"Cube"}}\n\n',
        'data: {"type":"selection.changed","ts":200,"data":{}}\n\n',
      ]),
      { status: 200 },
    );
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fakeResponse));

    const client = new DazClient({ token: "" });
    const events = await collect(watchSceneEvents(client));
    expect(events).toEqual([
      { type: "node.added", ts: 100, data: { name: "Cube" } },
      { type: "selection.changed", ts: 200, data: {} },
    ]);
  });

  it("filters client-side by eventTypes when given", async () => {
    const fakeResponse = new Response(
      sseBodyStream([
        'data: {"type":"node.added","ts":1,"data":{}}\n\n',
        'data: {"type":"node.removed","ts":2,"data":{}}\n\n',
      ]),
      { status: 200 },
    );
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fakeResponse));

    const client = new DazClient({ token: "" });
    const events = await collect(watchSceneEvents(client, undefined, ["node.removed"]));
    expect(events).toEqual([{ type: "node.removed", ts: 2, data: {} }]);
  });

  it("skips malformed JSON payloads instead of throwing", async () => {
    const fakeResponse = new Response(
      sseBodyStream(["data: not-json\n\n", 'data: {"type":"scene.saved","ts":1,"data":{}}\n\n']),
      { status: 200 },
    );
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fakeResponse));

    const client = new DazClient({ token: "" });
    const events = await collect(watchSceneEvents(client));
    expect(events).toEqual([{ type: "scene.saved", ts: 1, data: {} }]);
  });

  it("passes categories through to DazClient.streamSceneEvents as the filter param", async () => {
    const fakeResponse = new Response(sseBodyStream(["data: {}\n\n"]), { status: 200 });
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse);
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await collect(watchSceneEvents(client, ["node", "camera"]));
    const url = new URL(fetchMock.mock.calls[0][0] as string);
    expect(url.searchParams.get("filter")).toBe("node,camera");
  });

  it("throws ConnectionError when the SSE endpoint is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network down")));
    const client = new DazClient({ token: "" });
    await expect(collect(watchSceneEvents(client))).rejects.toThrow(ConnectionError);
  });
});

describe("waitForSceneEvent", () => {
  it("returns the first matching event and narrows the server-side category subscription", async () => {
    const fakeResponse = new Response(sseBodyStream(['data: {"type":"node.added","ts":1,"data":{}}\n\n']), {
      status: 200,
    });
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse);
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const event = await waitForSceneEvent(client, "node.added");
    expect(event).toEqual({ type: "node.added", ts: 1, data: {} });
    const url = new URL(fetchMock.mock.calls[0][0] as string);
    expect(url.searchParams.get("filter")).toBe("node");
  });

  it("does not narrow the server-side subscription for an unrecognized category prefix", async () => {
    const fakeResponse = new Response(sseBodyStream(['data: {"type":"custom.thing","ts":1,"data":{}}\n\n']), {
      status: 200,
    });
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse);
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await waitForSceneEvent(client, "custom.thing");
    const url = new URL(fetchMock.mock.calls[0][0] as string);
    expect(url.search).toBe("");
  });

  it("throws DazTimeoutError when the stream ends without a matching event", async () => {
    const fakeResponse = new Response(sseBodyStream(['data: {"type":"node.removed","ts":1,"data":{}}\n\n']), {
      status: 200,
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fakeResponse));

    const client = new DazClient({ token: "" });
    await expect(waitForSceneEvent(client, "node.added", 10)).rejects.toThrow(DazTimeoutError);
  });

  it("propagates ConnectionError instead of converting it to a timeout", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network down")));
    const client = new DazClient({ token: "" });
    await expect(waitForSceneEvent(client, "node.added", 10)).rejects.toThrow(ConnectionError);
  });
});
