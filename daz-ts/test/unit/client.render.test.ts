import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { AuthenticationError, DazError, StudioBusyError } from "../../src/exceptions.js";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DazClient render methods", () => {
  it("renderSubmit posts required + optional fields to /render", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { request_id: "r1", status: "queued", submitted_at: "now" }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await client.renderSubmit("C:\\out.png", {
      figure: "Genesis9",
      morphs: { Smile: 0.5 },
      width: 512,
      height: 512,
      camera: "MainCamera",
      engine: "iray",
    });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/render");
    expect(JSON.parse(init.body as string)).toEqual({
      output_path: "C:\\out.png",
      width: 512,
      height: 512,
      camera: "MainCamera",
      engine: "iray",
      figure: "Genesis9",
      morphs: { Smile: 0.5 },
    });
  });

  it("renderSubmit prefers figures[] over figure/morphs when both are given", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { request_id: "r1" }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await client.renderSubmit("C:\\out.png", {
      figure: "ignored",
      figures: [{ name: "Genesis9", morphs: { Smile: 1 } }],
    });

    const [, init] = fetchMock.mock.calls[0];
    const body = JSON.parse(init.body as string);
    expect(body.figures).toEqual([{ name: "Genesis9", morphs: { Smile: 1 } }]);
    expect(body.figure).toBeUndefined();
  });

  it("renderBatchSubmit posts variants and optional base", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { batch_id: "b1", request_ids: ["r1", "r2"], total: 2 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const result = await client.renderBatchSubmit(
      [{ output_path: "a.png" }, { output_path: "b.png" }],
      { width: 256, height: 256 },
    );

    expect(result).toEqual({ batch_id: "b1", request_ids: ["r1", "r2"], total: 2 });
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body as string)).toEqual({
      variants: [{ output_path: "a.png" }, { output_path: "b.png" }],
      base: { width: 256, height: 256 },
    });
  });

  it("renderAnimationSubmit posts frame range fields with default padding", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { request_id: "r1", status: "queued" }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await client.renderAnimationSubmit("C:\\anim\\f_{frame}.png", 1, 10);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/render/animation");
    expect(JSON.parse(init.body as string)).toEqual({
      output_path: "C:\\anim\\f_{frame}.png",
      start_frame: 1,
      end_frame: 10,
      frame_padding: 4,
    });
  });

  it("cancelRender posts to /render/{id}/cancel and returns a boolean", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    expect(await client.cancelRender("r1")).toBe(true);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/render/r1/cancel");
    expect(init.method).toBe("POST");
  });
});

describe("DazClient server health methods", () => {
  it("status/health/metrics GET their endpoints and throw AuthenticationError on 403", async () => {
    const fetchMock = vi.fn(async () => new Response("blocked", { status: 403 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await expect(client.status()).rejects.toBeInstanceOf(AuthenticationError);
    await expect(client.health()).rejects.toBeInstanceOf(AuthenticationError);
    await expect(client.metrics()).rejects.toBeInstanceOf(AuthenticationError);

    expect(fetchMock.mock.calls[0][0]).toBe("http://127.0.0.1:18811/status");
    expect(fetchMock.mock.calls[1][0]).toBe("http://127.0.0.1:18811/health");
    expect(fetchMock.mock.calls[2][0]).toBe("http://127.0.0.1:18811/metrics");
  });
});

describe("DazClient.capabilities", () => {
  it("GETs /capabilities and returns the document", async () => {
    const doc = { schema_version: 1, compatibility_hash: "0123456789abcdef", render_engines: { selectable: ["viewport"] } };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, doc));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await expect(client.capabilities()).resolves.toEqual(doc);
    expect(fetchMock.mock.calls[0][0]).toBe("http://127.0.0.1:18811/capabilities");
  });

  it("throws DazError on 404 from an older server", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(404, { error: "not found" })));
    const err = await new DazClient({ token: "" }).capabilities().catch((e) => e);
    expect(err).toBeInstanceOf(DazError);
    expect(String(err.message)).toContain("404");
  });

  it("throws AuthenticationError on 401 and StudioBusyError on 503", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("bad token", { status: 401 }))
      .mockResolvedValueOnce(jsonResponse(503, { error: "busy", error_code: "STUDIO_BUSY" }));
    vi.stubGlobal("fetch", fetchMock);
    const client = new DazClient({ token: "" });
    await expect(client.capabilities()).rejects.toBeInstanceOf(AuthenticationError);
    await expect(client.capabilities()).rejects.toBeInstanceOf(StudioBusyError);
  });
});
