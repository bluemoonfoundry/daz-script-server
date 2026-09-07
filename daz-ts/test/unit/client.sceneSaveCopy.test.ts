import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { AuthenticationError, DazError } from "../../src/exceptions.js";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}
afterEach(() => vi.unstubAllGlobals());

describe("DazClient.sceneSaveCopy", () => {
  it("posts {path} to /scene/save-copy and returns the parsed body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { ok: true, path: "C:/out.duf", source: "copy", method: "copy" }));
    vi.stubGlobal("fetch", fetchMock);
    const client = new DazClient({ token: "" });
    const result = await client.sceneSaveCopy("C:/out.duf");
    expect(result).toEqual({ ok: true, path: "C:/out.duf", source: "copy", method: "copy" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/scene/save-copy");
    expect(JSON.parse(init.body as string)).toEqual({ path: "C:/out.duf" });
  });

  it("throws AuthenticationError on HTTP 401/403", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("no", { status: 403 }));
    vi.stubGlobal("fetch", fetchMock);
    const client = new DazClient({ token: "" });
    await expect(client.sceneSaveCopy("x")).rejects.toBeInstanceOf(AuthenticationError);
  });

  it("throws DazError on other non-2xx statuses, including the server error message", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(500, { error: "disk full" }));
    vi.stubGlobal("fetch", fetchMock);
    const client = new DazClient({ token: "" });
    const err = await client.sceneSaveCopy("x").catch((e) => e);
    expect(err).toBeInstanceOf(DazError);
    expect(err.message).toContain("disk full");
  });
});
