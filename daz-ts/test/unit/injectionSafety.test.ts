import { afterEach, describe, expect, it, vi } from "vitest";
import { Batch } from "../../src/batch.js";
import { DazClient } from "../../src/client.js";
import { ScriptBuilder } from "../../src/scriptBuilder.js";
import { jsonResponse } from "../helpers.js";

afterEach(() => {
  vi.unstubAllGlobals();
});

const ADVERSARIAL_STRINGS = [
  `"; Scene.deleteAllNodes(); //`,
  "line1\nline2\r\nline3",
  "unicode: \u2028\u2029\u0000",
  "backslashes: \\\\ \\n \\\" ",
  "'single quotes' and \"double quotes\"",
  "</script><script>alert(1)</script>",
  "very-long-" + "x".repeat(10_000),
];

describe("injection safety", () => {
  it("ScriptBuilder.escapeString produces a value that JSON.parse recovers unchanged", () => {
    for (const input of ADVERSARIAL_STRINGS) {
      const escaped = ScriptBuilder.escapeString(input);
      expect(JSON.parse(escaped)).toBe(input);
      // The escaped form must not contain an unescaped double-quote or raw newline
      // that would break out of the string literal in generated DazScript.
      const inner = escaped.slice(1, -1);
      expect(inner).not.toMatch(/(?<!\\)"/);
      expect(inner).not.toMatch(/\n/);
    }
  });

  it("ScriptBuilder.serializeArg never lets adversarial strings escape their quotes", () => {
    for (const input of ADVERSARIAL_STRINGS) {
      const serialized = ScriptBuilder.serializeArg(input);
      expect(JSON.parse(serialized)).toBe(input);
    }
  });

  it("DazClient.execute JSON-encodes args, never string-concatenates them into the script", async () => {
    const fetchMock = vi.fn((_url: string, _init: RequestInit) =>
      jsonResponse({ success: true, result: null, output: [], request_id: "r1", duration_ms: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    for (const input of ADVERSARIAL_STRINGS) {
      await client.execute("f(getArguments()[0]);", input);
      const [, init] = fetchMock.mock.calls.at(-1)!;
      const body = JSON.parse(init.body as string);
      // args travels as a JSON payload field, never spliced into the script string.
      expect(body.args).toBe(input);
      expect(body.script).toBe("f(getArguments()[0]);");
    }
  });

  it("Batch.addOperation embeds adversarial result expressions without corrupting the combined script's JSON payload", async () => {
    const fetchMock = vi.fn((_url: string, _init: RequestInit) =>
      jsonResponse({ success: true, result: { _r0: "ok" }, output: [], request_id: "r1", duration_ms: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    for (const input of ADVERSARIAL_STRINGS.slice(0, 4)) {
      const batch = new Batch(client);
      const future = batch.addOperation([`var s = ${ScriptBuilder.escapeString(input)};`], "s");
      await batch.execute();
      const [, init] = fetchMock.mock.calls.at(-1)!;
      // The whole HTTP payload must remain valid JSON even though the script
      // string itself contains an embedded, escaped adversarial literal.
      expect(() => JSON.parse(init.body as string)).not.toThrow();
      void future;
    }
  });
});
