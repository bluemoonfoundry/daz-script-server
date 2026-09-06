import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import {
  AuthenticationError,
  ConnectionError,
  ConcurrencyLimitError,
  DazBusyError,
  DazTimeoutError,
  ScriptRuntimeError,
  ScriptSyntaxError,
  StudioBusyError,
} from "./exceptions.js";
import type { ExecutionResult } from "./result.js";

const TOKEN_FILE = path.join(os.homedir(), ".daz3d", "dazscriptserver_token.txt");
const DEFAULT_HOST = "127.0.0.1";
const DEFAULT_PORT = 18811;

function loadToken(): string {
  try {
    return fs.readFileSync(TOKEN_FILE, "utf-8").trim();
  } catch {
    return "";
  }
}

function parseRetryAfter(headers: Headers): number {
  const raw = headers.get("Retry-After");
  const value = raw !== null ? Number.parseFloat(raw) : NaN;
  return Number.isFinite(value) ? value : 2.0;
}

/**
 * Check the response status and raise an exception for errors, or return the parsed body for caller reuse.
 * Callers must use the returned value instead of re-reading the response body, since Node's fetch only allows one read.
 * @returns undefined if status < 400, or the parsed JSON body if >= 400 and no exception was thrown.
 */
async function raiseForError(resp: Response): Promise<Record<string, unknown> | undefined> {
  const status = resp.status;
  if (status === 401 || status === 403) {
    const text = await resp.text();
    throw new AuthenticationError(`HTTP ${status}: ${text.slice(0, 200)}`);
  }
  if (status < 400) {
    return undefined;
  }
  const data = (await resp.json()) as Record<string, unknown>;
  const errorCode = (data.error_code as string) ?? "";
  const errorMsg = (data.error as string) ?? `HTTP ${status}`;
  const retryAfter = parseRetryAfter(resp.headers);
  if (errorCode === "STUDIO_BUSY") {
    throw new StudioBusyError(errorMsg, (data.detail as string) ?? errorMsg, retryAfter);
  }
  if (errorCode === "CONCURRENT_LIMIT_EXCEEDED") {
    throw new ConcurrencyLimitError(errorMsg, errorMsg, retryAfter);
  }
  return data;
}

async function mapResponse(resp: Response, script = ""): Promise<ExecutionResult> {
  const errData = await raiseForError(resp);
  const data = errData ?? ((await resp.json()) as Record<string, unknown>);
  const requestId = (data.request_id as string) ?? "";

  if (data.success === false) {
    const errorMsg = (data.error as string) ?? "Script failed";
    const output = (data.output as string[]) ?? [];
    if (errorMsg.includes("SyntaxError")) {
      throw new ScriptSyntaxError(errorMsg, script, requestId, output);
    }
    throw new ScriptRuntimeError(errorMsg, script, requestId, output);
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

function sleep(seconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, seconds * 1000));
}

/**
 * Parse a Server-Sent-Events HTTP response body into `{event, data}` pairs.
 *
 * Lines starting with `:` are keepalive comments and are skipped. An event
 * block with no explicit `event:` line defaults to `"message"`, matching
 * the SSE specification.
 */
export async function* parseSseStream(response: Response): AsyncGenerator<{ event: string; data: string }> {
  const body = response.body;
  if (!body) {
    return;
  }
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });

      let boundary: number;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const rawEvent = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);

        let eventName = "message";
        const dataLines: string[] = [];
        for (const line of rawEvent.split("\n")) {
          if (line.startsWith(":") || line === "") {
            continue;
          }
          if (line.startsWith("event:")) {
            eventName = line.slice("event:".length).trim();
          } else if (line.startsWith("data:")) {
            dataLines.push(line.slice("data:".length).trim());
          }
        }
        if (dataLines.length > 0) {
          yield { event: eventName, data: dataLines.join("\n") };
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/** Options accepted by the {@link DazClient} constructor. */
export interface DazClientOptions {
  /** Hostname or IP address of the Script Server. Default `"127.0.0.1"`. */
  host?: string;
  /** Listening port of the Script Server. Default `18811`. */
  port?: number;
  /**
   * API token. Pass `""` to disable authentication, or omit/`null` to
   * auto-load from `~/.daz3d/dazscriptserver_token.txt`.
   */
  token?: string | null;
  /** Per-request HTTP timeout in milliseconds. Default `30000`. */
  timeoutMs?: number;
}

/** Options accepted by "submit"-style methods that support busy-retry. */
export interface RetryOptions {
  /**
   * If `true`, transparently retry with backoff when the server reports
   * `StudioBusyError`/`ConcurrencyLimitError`, instead of raising immediately.
   */
  retryOnBusy?: boolean;
  /**
   * Maximum total seconds to retry when `retryOnBusy` is `true`, before
   * re-throwing the busy error.
   */
  maxWait?: number;
}

/** Options accepted by {@link DazClient.renderSubmit}. */
export interface RenderSubmitOptions extends RetryOptions {
  figure?: string;
  morphs?: Record<string, number>;
  figures?: Array<{ name: string; morphs?: Record<string, number> }>;
  width?: number;
  height?: number;
  camera?: string;
  engine?: string;
  iraySamples?: number;
  resetMorphs?: boolean;
}

/** Options accepted by {@link DazClient.exportUsdSubmit}. */
export interface ExportUsdOptions {
  includeGeometry?: boolean;
  includeMaterials?: boolean;
  includeSkeleton?: boolean;
  includeMorphs?: boolean;
  includeLights?: boolean;
  includeCamera?: boolean;
}

/**
 * HTTP client for the DAZ Studio Script Server.
 *
 * Handles authentication, request serialization, and response mapping for
 * all server endpoints. The token is loaded automatically from
 * `~/.daz3d/dazscriptserver_token.txt` when `token` is omitted.
 *
 * Unlike dazpy (which needs separate `DazClient`/`AsyncDazClient` classes
 * for Python's sync/async split), a single `DazClient` covers both cases
 * via `async`/`await`.
 */
export class DazClient {
  private readonly baseUrl: string;
  private readonly token: string;
  private readonly timeoutMs: number;

  constructor(options: DazClientOptions = {}) {
    const { host = DEFAULT_HOST, port = DEFAULT_PORT, token = null, timeoutMs = 30_000 } = options;
    this.baseUrl = `http://${host}:${port}`;
    this.token = token !== null ? token : loadToken();
    this.timeoutMs = timeoutMs;
  }

  private get headers(): Record<string, string> {
    return this.token ? { "X-API-Token": this.token } : {};
  }

  private async fetchWithTimeout(url: string, init: RequestInit): Promise<Response> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      return await fetch(url, { ...init, signal: controller.signal });
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") {
        throw new DazTimeoutError(`Request timed out after ${this.timeoutMs / 1000}s`);
      }
      const message = e instanceof Error ? e.message : String(e);
      throw new ConnectionError(`Cannot reach DAZ Studio at ${this.baseUrl}: ${message}`);
    } finally {
      clearTimeout(timer);
    }
  }

  private post(pathname: string, payload: unknown): Promise<Response> {
    return this.fetchWithTimeout(`${this.baseUrl}${pathname}`, {
      method: "POST",
      headers: { ...this.headers, "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  private get(pathname: string, params?: Record<string, string>): Promise<Response> {
    const url = new URL(`${this.baseUrl}${pathname}`);
    if (params) {
      for (const [k, v] of Object.entries(params)) {
        url.searchParams.set(k, v);
      }
    }
    return this.fetchWithTimeout(url.toString(), { method: "GET", headers: this.headers });
  }

  private async delete_(pathname: string): Promise<Response | null> {
    try {
      return await this.fetchWithTimeout(`${this.baseUrl}${pathname}`, { method: "DELETE", headers: this.headers });
    } catch {
      return null;
    }
  }

  private async withBusyRetry<T>(fn: () => Promise<T>, retryOnBusy: boolean, maxWait: number): Promise<T> {
    if (!retryOnBusy) {
      return fn();
    }
    const deadline = Date.now() + maxWait * 1000;
    let backoff = 1.0;
    for (;;) {
      try {
        return await fn();
      } catch (e) {
        if (!(e instanceof DazBusyError)) {
          throw e;
        }
        const remainingMs = deadline - Date.now();
        if (remainingMs <= 0) {
          throw e;
        }
        await sleep(Math.min(backoff, remainingMs / 1000));
        backoff = Math.min(backoff + 1.0, 5.0);
      }
    }
  }

  /**
   * Execute a DazScript string synchronously.
   *
   * @param script - DazScript source code to execute.
   * @param args - Optional value passed into the script as `getArguments()[0]`. Must be JSON-serializable.
   */
  async execute(script: string, args?: unknown, opts: RetryOptions = {}): Promise<ExecutionResult> {
    const { retryOnBusy = false, maxWait = 30.0 } = opts;
    const payload: Record<string, unknown> = { script };
    if (args !== undefined) {
      payload.args = args;
    }
    return this.withBusyRetry(
      async () => mapResponse(await this.post("/execute", payload), script),
      retryOnBusy,
      maxWait,
    );
  }

  /**
   * Execute a `.dsa` script file that resides on the DAZ Studio host.
   *
   * @param scriptFile - Absolute path to the `.dsa` file on the server host.
   * @param args - Optional argument passed to the script.
   */
  async executeFile(scriptFile: string, args?: unknown, opts: RetryOptions = {}): Promise<ExecutionResult> {
    const { retryOnBusy = false, maxWait = 30.0 } = opts;
    const payload: Record<string, unknown> = { scriptFile };
    if (args !== undefined) {
      payload.args = args;
    }
    return this.withBusyRetry(
      async () => mapResponse(await this.post("/execute", payload)),
      retryOnBusy,
      maxWait,
    );
  }

  /**
   * Submit a script for asynchronous execution and return immediately.
   *
   * @returns The server-assigned `requestId`. Use it with {@link getRequestStatus}
   * or {@link getRequestResult} to poll for the outcome.
   */
  async executeAsyncSubmit(script: string, args?: unknown, opts: RetryOptions = {}): Promise<string> {
    const { retryOnBusy = false, maxWait = 30.0 } = opts;
    const payload: Record<string, unknown> = { script };
    if (args !== undefined) {
      payload.args = args;
    }
    return this.withBusyRetry(
      async () => {
        const resp = await this.post("/execute/async", payload);
        const data = (await raiseForError(resp)) ?? ((await resp.json()) as Record<string, unknown>);
        return (data.request_id as string) ?? "";
      },
      retryOnBusy,
      maxWait,
    );
  }

  /**
   * Submit a host-side `.dsa` file for asynchronous execution.
   *
   * The file is loaded by DAZ Studio when the queued job starts, preserving
   * its filename for `getScriptFileName()` and relative `include()` calls.
   */
  async executeFileAsyncSubmit(scriptFile: string, args?: unknown, opts: RetryOptions = {}): Promise<string> {
    const { retryOnBusy = false, maxWait = 30.0 } = opts;
    const payload: Record<string, unknown> = { scriptFile };
    if (args !== undefined) {
      payload.args = args;
    }
    return this.withBusyRetry(
      async () => {
        const resp = await this.post("/execute/async", payload);
        const data = (await raiseForError(resp)) ?? ((await resp.json()) as Record<string, unknown>);
        return (data.request_id as string) ?? "";
      },
      retryOnBusy,
      maxWait,
    );
  }

  /**
   * Submit multiple operations as one async request (one queue slot, one script).
   *
   * @param operations - `{bodyLines, resultExpression}` pairs — same shape as {@link Batch.addOperation}'s arguments.
   * @returns The server-assigned `requestId`. Poll it like any other async
   * request; the result's `result` field is a dict keyed `"_r0"`, `"_r1"`, ... in submission order.
   */
  async executeBatchAsync(
    operations: Array<{ body_lines: string[]; result_expression: string }>,
    args?: unknown,
  ): Promise<string> {
    const { buildOperationsScript } = await import("./batch.js");
    const pairs: Array<[string[], string]> = operations.map((op) => [op.body_lines, op.result_expression]);
    const script = buildOperationsScript(pairs);
    return this.executeAsyncSubmit(script, args);
  }

  /**
   * Return the current status of an async request.
   *
   * @returns A dict with at least a `status` key: `"queued"`, `"running"`,
   * `"completed"`, `"failed"`, `"cancelled"`, or `"not_found"`.
   */
  async getRequestStatus(requestId: string): Promise<Record<string, unknown>> {
    const resp = await this.get(`/requests/${requestId}/status`);
    if (resp.status === 404) {
      return { status: "not_found" };
    }
    return (await resp.json()) as Record<string, unknown>;
  }

  /**
   * Fetch the result of a completed async request.
   *
   * @param wait - If `true`, the server long-polls until the request completes or `waitTimeout` is reached.
   * @param waitTimeout - Maximum seconds the server should wait (only relevant when `wait` is `true`).
   */
  async getRequestResult(requestId: string, wait = false, waitTimeout = 30): Promise<Record<string, unknown>> {
    const params: Record<string, string> = {};
    if (wait) {
      params.wait = "true";
      params.timeout = String(waitTimeout);
    }
    const resp = await this.get(`/requests/${requestId}/result`, Object.keys(params).length ? params : undefined);
    if (resp.status === 404) {
      return { status: "not_found" };
    }
    return (await resp.json()) as Record<string, unknown>;
  }

  /**
   * List all tracked async requests (script and render) with their status.
   *
   * @param status - Optional filter: `"queued"`, `"running"`, `"completed"`, `"failed"`, `"cancelled"`.
   */
  async listRequests(status?: string): Promise<Record<string, unknown>> {
    const resp = await this.get("/requests", status ? { status } : undefined);
    if (resp.status === 401 || resp.status === 403) {
      throw new AuthenticationError(`HTTP ${resp.status}: ${(await resp.text()).slice(0, 200)}`);
    }
    return (await resp.json()) as Record<string, unknown>;
  }

  /**
   * Cancel a queued or running async request.
   *
   * @returns `true` if the server confirmed cancellation, `false` otherwise.
   */
  async cancelRequest(requestId: string): Promise<boolean> {
    const resp = await this.delete_(`/requests/${requestId}`);
    return resp !== null && resp.status === 200;
  }

  // ── Render ──────────────────────────────────────────────────────────────

  /** Submit a render job and return immediately. */
  async renderSubmit(outputPath: string, opts: RenderSubmitOptions = {}): Promise<Record<string, unknown>> {
    const { figure, morphs, figures, width, height, camera, engine, iraySamples, resetMorphs, retryOnBusy = false, maxWait = 30.0 } = opts;
    const payload: Record<string, unknown> = { output_path: outputPath };
    if (width && height) {
      payload.width = width;
      payload.height = height;
    }
    if (camera) payload.camera = camera;
    if (engine) payload.engine = engine;
    if (iraySamples) payload.iray_samples = iraySamples;
    if (resetMorphs) payload.reset_morphs = true;
    if (figures !== undefined) {
      payload.figures = figures;
    } else if (figure) {
      payload.figure = figure;
      if (morphs) payload.morphs = morphs;
    }

    return this.withBusyRetry(
      async () => {
        const resp = await this.post("/render", payload);
        return (await raiseForError(resp)) ?? ((await resp.json()) as Record<string, unknown>);
      },
      retryOnBusy,
      maxWait,
    );
  }

  /** Submit a batch render job (multiple variants sharing optional defaults) and return immediately. */
  async renderBatchSubmit(
    variants: Array<Record<string, unknown>>,
    base?: Record<string, unknown>,
    opts: RetryOptions = {},
  ): Promise<Record<string, unknown>> {
    const { retryOnBusy = false, maxWait = 30.0 } = opts;
    const payload: Record<string, unknown> = { variants };
    if (base) payload.base = base;

    return this.withBusyRetry(
      async () => {
        const resp = await this.post("/render/batch", payload);
        return (await raiseForError(resp)) ?? ((await resp.json()) as Record<string, unknown>);
      },
      retryOnBusy,
      maxWait,
    );
  }

  /** Submit an animation render job spanning a frame range and return immediately. */
  async renderAnimationSubmit(
    outputPath: string,
    startFrame: number,
    endFrame: number,
    opts: RetryOptions & { framePadding?: number; width?: number; height?: number; camera?: string; engine?: string } = {},
  ): Promise<Record<string, unknown>> {
    const { framePadding = 4, width, height, camera, engine, retryOnBusy = false, maxWait = 30.0 } = opts;
    const payload: Record<string, unknown> = {
      output_path: outputPath,
      start_frame: startFrame,
      end_frame: endFrame,
      frame_padding: framePadding,
    };
    if (width && height) {
      payload.width = width;
      payload.height = height;
    }
    if (camera) payload.camera = camera;
    if (engine) payload.engine = engine;

    return this.withBusyRetry(
      async () => {
        const resp = await this.post("/render/animation", payload);
        return (await raiseForError(resp)) ?? ((await resp.json()) as Record<string, unknown>);
      },
      retryOnBusy,
      maxWait,
    );
  }

  /** Cancel a queued or running render job. */
  async cancelRender(requestId: string): Promise<boolean> {
    try {
      const resp = await this.fetchWithTimeout(`${this.baseUrl}/render/${requestId}/cancel`, {
        method: "POST",
        headers: this.headers,
      });
      return resp.status === 200;
    } catch {
      return false;
    }
  }

  /**
   * Open the SSE progress stream for a render request.
   *
   * @returns The raw streaming `Response` on success, `null` if the
   * endpoint is unavailable. Pass the result to {@link parseSseStream} to
   * consume it, and remember to let the body drain or cancel the reader.
   */
  async streamRenderProgress(requestId: string, streamTimeoutMs = 305_000): Promise<Response | null> {
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), streamTimeoutMs);
      const resp = await fetch(`${this.baseUrl}/render/${requestId}/progress`, {
        headers: this.headers,
        signal: controller.signal,
      }).finally(() => clearTimeout(timer));
      return resp.status === 200 ? resp : null;
    } catch {
      return null;
    }
  }

  /**
   * Open the SSE stream for general scene-change events (`GET /scene/events`).
   *
   * @param categories - Optional subset of event categories to subscribe to
   * (`"node"`, `"skeleton"`, `"light"`, `"camera"`, `"selection"`, `"scene"`,
   * `"time"`, `"render"`). Omit to subscribe to all categories.
   * @param streamTimeoutMs - Socket timeout in milliseconds. Omit to wait
   * indefinitely — the server sends a keepalive comment every 15 seconds.
   */
  async streamSceneEvents(categories?: string[], streamTimeoutMs?: number): Promise<Response | null> {
    try {
      const url = new URL(`${this.baseUrl}/scene/events`);
      if (categories && categories.length > 0) {
        url.searchParams.set("filter", categories.join(","));
      }
      const controller = new AbortController();
      const timer = streamTimeoutMs !== undefined ? setTimeout(() => controller.abort(), streamTimeoutMs) : undefined;
      const resp = await fetch(url.toString(), { headers: this.headers, signal: controller.signal }).finally(() => {
        if (timer) clearTimeout(timer);
      });
      return resp.status === 200 ? resp : null;
    } catch {
      return null;
    }
  }

  // ── USD export ──────────────────────────────────────────────────────────

  /** Submit a USD export job and return immediately. */
  async exportUsdSubmit(outputPath: string, opts: ExportUsdOptions = {}): Promise<Record<string, unknown>> {
    const {
      includeGeometry = true,
      includeMaterials = true,
      includeSkeleton = false,
      includeMorphs = false,
      includeLights = false,
      includeCamera = false,
    } = opts;
    const payload = {
      outputPath,
      includeGeometry,
      includeMaterials,
      includeSkeleton,
      includeMorphs,
      includeLights,
      includeCamera,
    };
    const resp = await this.post("/export/usd", payload);
    if (resp.status === 401 || resp.status === 403) {
      throw new AuthenticationError(`HTTP ${resp.status}: ${(await resp.text()).slice(0, 200)}`);
    }
    return (await resp.json()) as Record<string, unknown>;
  }

  /** Poll the status of a USD export job. */
  async getUsdExportStatus(jobId: string): Promise<Record<string, unknown>> {
    const resp = await this.get(`/export/usd/${jobId}`);
    if (resp.status === 401 || resp.status === 403) {
      throw new AuthenticationError(`HTTP ${resp.status}: ${(await resp.text()).slice(0, 200)}`);
    }
    if (resp.status === 404) {
      return { job_id: jobId, status: "not_found" };
    }
    return (await resp.json()) as Record<string, unknown>;
  }

  // ── Server health ───────────────────────────────────────────────────────

  /** Return the server status dict from `GET /status`. */
  async status(): Promise<Record<string, unknown>> {
    const resp = await this.get("/status");
    if (resp.status === 401 || resp.status === 403) {
      throw new AuthenticationError(`HTTP ${resp.status}: ${(await resp.text()).slice(0, 200)}`);
    }
    return (await resp.json()) as Record<string, unknown>;
  }

  /** Return the health check dict from `GET /health`. */
  async health(): Promise<Record<string, unknown>> {
    const resp = await this.get("/health");
    if (resp.status === 401 || resp.status === 403) {
      throw new AuthenticationError(`HTTP ${resp.status}: ${(await resp.text()).slice(0, 200)}`);
    }
    return (await resp.json()) as Record<string, unknown>;
  }

  /** Return the metrics dict from `GET /metrics`. */
  async metrics(): Promise<Record<string, unknown>> {
    const resp = await this.get("/metrics");
    if (resp.status === 401 || resp.status === 403) {
      throw new AuthenticationError(`HTTP ${resp.status}: ${(await resp.text()).slice(0, 200)}`);
    }
    return (await resp.json()) as Record<string, unknown>;
  }
}
