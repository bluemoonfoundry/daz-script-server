import { afterEach, describe, expect, it, vi } from "vitest";
import { sleep } from "../../src/sleep.js";

describe("sleep", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("takes milliseconds, not seconds", async () => {
    vi.useFakeTimers();
    let done = false;
    const p = sleep(250).then(() => {
      done = true;
    });
    await vi.advanceTimersByTimeAsync(249);
    expect(done).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await p;
    expect(done).toBe(true);
  });
});
