import { describe, expect, it } from "vitest";
import { DazClient } from "../../src/index.js";

const SERVER_URL = process.env.DAZ_SERVER_URL;

describe.skipIf(!SERVER_URL)("DazClient live integration", () => {
  it("executes a trivial script against a real DazScriptServer instance", async () => {
    const url = new URL(SERVER_URL!);
    const client = new DazClient({ host: url.hostname, port: Number(url.port) || 18811 });

    const result = await client.execute("1 + 1;");

    expect(result.success).toBe(true);
    expect(result.value).toBe(2);
  });

  it("round-trips server status", async () => {
    const url = new URL(SERVER_URL!);
    const client = new DazClient({ host: url.hostname, port: Number(url.port) || 18811 });

    const status = await client.status();

    expect(status).toHaveProperty("version");
  });
});
