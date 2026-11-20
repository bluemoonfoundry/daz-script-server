import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { AuthenticationError } from "../../src/exceptions.js";
import { evaluateServerVersion, MIN_SERVER_VERSION, parseVersion } from "../../src/version.js";
import { jsonResponse } from "../helpers.js";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("parseVersion", () => {
  it("reads major.minor and ignores the rest", () => {
    expect(parseVersion("2.15.0")).toEqual([2, 15]);
    expect(parseVersion("v2.11")).toEqual([2, 11]);
    expect(parseVersion(" 10.2.3-beta")).toEqual([10, 2]);
  });

  it("returns null for anything else", () => {
    expect(parseVersion("2")).toBeNull();
    expect(parseVersion("dev")).toBeNull();
    expect(parseVersion(2.15)).toBeNull();
    expect(parseVersion(undefined)).toBeNull();
  });
});

describe("evaluateServerVersion", () => {
  const url = "http://127.0.0.1:18811";

  it("accepts the minimum and anything newer, comparing numerically", () => {
    expect(evaluateServerVersion(url, { version: `${MIN_SERVER_VERSION}.0` }).compatible).toBe(true);
    expect(evaluateServerVersion(url, { version: "2.100.0" }).compatible).toBe(true);
    expect(evaluateServerVersion(url, { version: "3.0.0" }).compatible).toBe(true);
  });

  it("rejects an older plugin with upgrade advice", () => {
    const check = evaluateServerVersion(url, { version: "2.10.1", server_instance_id: "abc" });
    expect(check).toMatchObject({
      serverUrl: url,
      serverVersion: "2.10.1",
      minServerVersion: MIN_SERVER_VERSION,
      serverInstanceId: "abc",
      compatible: false,
    });
    expect(check.message).toContain("2.10.1");
    expect(check.message).toContain(MIN_SERVER_VERSION);
    expect(check.message).toContain(url);
    expect(evaluateServerVersion(url, { version: "1.99.0" }).compatible).toBe(false);
  });

  it("reports unknown when the version is missing or unparseable", () => {
    for (const status of [{}, { version: "dev" }, { version: 2 }, null, "nope"]) {
      const check = evaluateServerVersion(url, status);
      expect(check.compatible).toBeNull();
      expect(check.message).toBeNull();
      expect(check.serverInstanceId).toBeNull();
    }
  });
});

describe("DazClient.checkServerVersion", () => {
  it("GETs /status and evaluates its version", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ version: "2.9.3", server_instance_id: "i1" }));
    vi.stubGlobal("fetch", fetchMock);
    const client = new DazClient({ token: "t", port: 18812 });

    const check = await client.checkServerVersion();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("http://127.0.0.1:18812/status");
    expect(check.serverUrl).toBe("http://127.0.0.1:18812");
    expect(check.compatible).toBe(false);
    expect(check.serverInstanceId).toBe("i1");
  });

  it("propagates auth failures from /status", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("nope", { status: 401 })));
    await expect(new DazClient({ token: "t" }).checkServerVersion()).rejects.toBeInstanceOf(AuthenticationError);
  });
});
