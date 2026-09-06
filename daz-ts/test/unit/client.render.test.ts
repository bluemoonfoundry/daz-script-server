import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { AuthenticationError } from "../../src/exceptions.js";

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

describe("DazClient USD export methods", () => {
  it("exportUsdSubmit posts camelCase wire fields with documented defaults", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { job_id: "j1", status: "queued" }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await client.exportUsdSubmit("C:\\out.usda");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/export/usd");
    expect(JSON.parse(init.body as string)).toEqual({
      outputPath: "C:\\out.usda",
      includeGeometry: true,
      includeMaterials: true,
      includeSkeleton: false,
      includeMorphs: false,
      includeLights: false,
      includeCamera: false,
    });
  });

  it("getUsdExportStatus returns not_found on 404 and throws on 401", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("", { status: 404 }))
      .mockResolvedValueOnce(new Response("nope", { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    expect(await client.getUsdExportStatus("j1")).toEqual({ job_id: "j1", status: "not_found" });
    await expect(client.getUsdExportStatus("j2")).rejects.toBeInstanceOf(AuthenticationError);
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
