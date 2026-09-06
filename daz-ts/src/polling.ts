import type { DazClient } from "./client.js";
import type { ExecutionResult } from "./result.js";
import { AsyncExecutionError, DazTimeoutError } from "./exceptions.js";

/** Options accepted by {@link executeLong}. */
export interface ExecuteLongOptions {
  /** Maximum total wall-clock milliseconds to wait. Default `120000`. */
  timeoutMs?: number;
  /** Milliseconds to sleep between short polls when the server returns before the long-poll timeout. Default `500`. */
  pollIntervalMs?: number;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Execute a potentially long-running script via the async endpoint with polling.
 *
 * Submits `script` asynchronously, then polls `/requests/:id/result` with
 * long-polling until the script completes or `timeoutMs` is exceeded.
 *
 * @throws {AsyncExecutionError} If the script fails or the request is cancelled.
 * @throws {DazTimeoutError} If `timeoutMs` is exceeded before the script completes.
 */
export async function executeLong(
  client: DazClient,
  script: string,
  args?: unknown,
  options: ExecuteLongOptions = {},
): Promise<ExecutionResult> {
  const { timeoutMs = 120_000, pollIntervalMs = 500 } = options;
  const requestId = await client.executeAsyncSubmit(script, args);
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const waitTimeoutSeconds = Math.min(30, Math.floor((deadline - Date.now()) / 1000) + 1);
    const data = await client.getRequestResult(requestId, true, waitTimeoutSeconds);
    const status = data.status as string | undefined;

    if (data.success !== undefined) {
      if (!data.success) {
        throw new AsyncExecutionError((data.error as string) ?? "Async script failed", requestId);
      }
      return {
        value: data.result ?? null,
        output: (data.output as string[]) ?? [],
        requestId,
        success: true,
        error: "",
        durationMs: (data.duration_ms as number) ?? 0,
      };
    }
    if (status === "failed") {
      throw new AsyncExecutionError((data.error as string) ?? "Async script failed", requestId);
    }
    if (status === "cancelled") {
      throw new AsyncExecutionError("Request was cancelled", requestId);
    }
    await sleep(pollIntervalMs);
  }

  throw new DazTimeoutError(`Async execution timed out after ${timeoutMs / 1000}s (requestId=${requestId})`);
}
