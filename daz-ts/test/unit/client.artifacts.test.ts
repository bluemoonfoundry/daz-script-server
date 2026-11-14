import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient, safeArtifactFilename } from "../../src/client.js";
import { ArtifactError, AuthenticationError } from "../../src/exceptions.js";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DazClient artifacts (GET /artifacts/...)", () => {
  it("listArtifacts GETs /artifacts/{id}", async () => {
    const body = { success: true, request_id: "rnd-1", status: "completed", count: 0, artifacts: [] };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, body));
    vi.stubGlobal("fetch", fetchMock);

    await expect(new DazClient({ token: "" }).listArtifacts("rnd-1")).resolves.toEqual(body);
    expect(fetchMock.mock.calls[0][0]).toBe("http://127.0.0.1:18811/artifacts/rnd-1");
  });

  it("downloadArtifact returns bytes and sends no Range by default", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(new Uint8Array([1, 2, 3]), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const data = await new DazClient({ token: "t" }).downloadArtifact("rnd-1", 0);
    expect(Buffer.isBuffer(data)).toBe(true);
    expect([...data]).toEqual([1, 2, 3]);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/artifacts/rnd-1/0");
    expect(init.headers).toEqual({ "X-API-Token": "t" });
  });

  it("downloadArtifact sends Range headers", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response(new Uint8Array([9]), { status: 206 }));
    vi.stubGlobal("fetch", fetchMock);
    const client = new DazClient({ token: "" });

    await client.downloadArtifact("rnd-1", "0", { range: [0, 99] });
    await client.downloadArtifact("rnd-1", "0", { range: [100] });
    expect(fetchMock.mock.calls[0][1].headers.Range).toBe("bytes=0-99");
    expect(fetchMock.mock.calls[1][1].headers.Range).toBe("bytes=100-");
  });

  it("rejects invalid ranges before any request", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const client = new DazClient({ token: "" });
    await expect(client.downloadArtifact("rnd-1", "0", { range: [-1, 5] })).rejects.toBeInstanceOf(RangeError);
    await expect(client.downloadArtifact("rnd-1", "0", { range: [10, 2] })).rejects.toBeInstanceOf(RangeError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("downloadArtifact streams into dest", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("PNGDATA", { status: 200 })));
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "dazts-art-"));
    try {
      const dest = path.join(dir, "out.png");
      await expect(new DazClient({ token: "" }).downloadArtifact("rnd-1", "0", dest)).resolves.toBe(dest);
      expect(fs.readFileSync(dest, "utf8")).toBe("PNGDATA");
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  it("maps rejections to ArtifactError / AuthenticationError", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(404, { success: false, error_code: "ARTIFACT_NOT_FOUND", error: "nope" }))
      .mockResolvedValueOnce(jsonResponse(410, { success: false, error_code: "ARTIFACT_UNAVAILABLE", error: "gone" }))
      .mockResolvedValueOnce(new Response("", { status: 416 }))
      .mockResolvedValueOnce(new Response("bad token", { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);
    const client = new DazClient({ token: "" });

    const notFound = await client.downloadArtifact("rnd-1", "9").catch((e) => e);
    expect(notFound).toBeInstanceOf(ArtifactError);
    expect(notFound.statusCode).toBe(404);
    expect(notFound.errorCode).toBe("ARTIFACT_NOT_FOUND");

    const gone = await client.downloadArtifact("rnd-1", "1").catch((e) => e);
    expect(gone.statusCode).toBe(410);
    expect(gone.errorCode).toBe("ARTIFACT_UNAVAILABLE");

    const range = await client.downloadArtifact("rnd-1", "0", { range: [5000] }).catch((e) => e);
    expect(range).toBeInstanceOf(ArtifactError);
    expect(range.statusCode).toBe(416);

    await expect(client.listArtifacts("rnd-1")).rejects.toBeInstanceOf(AuthenticationError);
  });

  it("downloadArtifacts skips unavailable entries and sanitizes names", async () => {
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url.endsWith("/artifacts/rnd-1")) {
        return jsonResponse(200, {
          artifacts: [
            { artifact_id: "0", available: true, filename: "../../evil.png" },
            { artifact_id: "1", available: false, filename: "gone.png" },
            { artifact_id: "2", available: true, filename: "frame.png" },
          ],
        });
      }
      return new Response("x", { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "dazts-arts-"));
    try {
      const paths = await new DazClient({ token: "" }).downloadArtifacts("rnd-1", dir);
      expect(paths.map((p) => path.basename(p))).toEqual(["0_evil.png", "2_frame.png"]);
      expect(paths.every((p) => path.dirname(p) === dir)).toBe(true);
      expect(fetchMock.mock.calls.map((c) => c[0])).not.toContain("http://127.0.0.1:18811/artifacts/rnd-1/1");
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  it("safeArtifactFilename strips separators and dot names", () => {
    expect(safeArtifactFilename("a\\b\\c.png")).toBe("c.png");
    expect(safeArtifactFilename("..")).toBe("artifact");
    expect(safeArtifactFilename("foo:bar?.exr")).toBe("foo_bar_.exr");
  });
});
