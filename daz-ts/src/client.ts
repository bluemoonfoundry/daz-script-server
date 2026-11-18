import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import {
  ArtifactError,
  AuthenticationError,
  ConnectionError,
  ConcurrencyLimitError,
  DazBusyError,
  DazError,
  DazTimeoutError,
  ScriptRuntimeError,
  ScriptSyntaxError,
  StudioBusyError,
} from "./exceptions.js";
import { buildOperationsScript } from "./batch.js";
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
  // An intermediary (proxy, 502 gateway) or an early httplib rejection can
  // send a non-JSON body; read it as text so it still maps to a DazError.
  const text = await resp.text();
  let data: Record<string, unknown>;
  try {
    const parsed: unknown = JSON.parse(text);
    data = typeof parsed === "object" && parsed !== null && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : {};
  } catch {
    throw new DazError(`HTTP ${status}: ${text.slice(0, 200) || resp.statusText}`);
  }
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

/** Throw ArtifactError (or AuthenticationError/busy errors) for a rejected artifact request. */
async function throwArtifactError(resp: Response): Promise<void> {
  if (resp.status < 400) return;
  if (resp.status === 416) {
    throw new ArtifactError("Requested range is outside the artifact (HTTP 416)", 416);
  }
  const data = await raiseForError(resp);
  const code = (data?.error_code as string) ?? "";
  const msg = (data?.error as string) ?? `HTTP ${resp.status}`;
  throw new ArtifactError(msg, resp.status, code);
}

/** Base name safe to join under a download directory (no separators, no `..`). */
export function safeArtifactFilename(name: string): string {
  const base = name.replace(/\\/g, "/").split("/").pop() ?? "";
  // eslint-disable-next-line no-control-regex
  const cleaned = base.replace(/[:*?"<>|\x00-\x1f]/g, "_");
  return cleaned.replace(/[. ]/g, "") === "" ? "artifact" : cleaned;
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
 * the SSE specification. Lines may end in LF, CRLF or CR, as the
 * specification allows; DazScriptServer itself sends LF.
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
      // Normalize CRLF/CR to LF. A trailing CR is held back: it may be the
      // first half of a CRLF split across chunks.
      const heldCr = buffer.endsWith("\r");
      buffer = (heldCr ? buffer.slice(0, -1) : buffer).replace(/\r\n?/g, "\n") + (heldCr ? "\r" : "");

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
  figures?: Array<{ name: string | null; morphs?: Record<string, number> }>;
  width?: number;
  height?: number;
  camera?: string;
  engine?: string;
  iraySamples?: number;
  resetMorphs?: boolean;
}

/** Options accepted by {@link DazClient.streamRenderProgress} and {@link DazClient.streamSceneEvents}. */
export interface StreamOptions {
  /**
   * Maximum lifetime of the whole stream in milliseconds, not just time to
   * first byte: when it elapses the connection is aborted and the pending
   * read (including one inside {@link parseSseStream}) rejects with
   * `DazTimeoutError`. Omit for no limit.
   */
  timeoutMs?: number;
  /** Aborts the connection (and any pending read) when signalled. */
  signal?: AbortSignal;
}

/** A route listed by `GET /capabilities`. Paths use `{id}` placeholders. */
export interface CapabilityRoute {
  method: string;
  path: string;
  auth: boolean;
  kind?: "json" | "sse" | "binary";
  /** Companion-plugin routes only: class name of the registering QObject. */
  owner?: string;
}

/**
 * Document returned by `GET /capabilities` (schema_version 1). Clients must
 * ignore unknown keys; feature flags and limits may gain entries over time.
 */
export interface ServerCapabilities {
  schema_version: number;
  /** Changes only when the schema, route table or feature flags change. */
  compatibility_hash: string;
  server: { name: string; version: string };
  studio: { version: string; sdk_version: string; sdk_major: number; qt_version: string; qt_build_version: string };
  routes: CapabilityRoute[];
  plugin_routes: CapabilityRoute[];
  features: Record<string, boolean>;
  limits: Record<string, number>;
  rate_limit: { enabled: boolean; max_requests: number; window_seconds: number; applies_to: string };
  security: { auth_enabled: boolean; auth_headers: string[]; ip_whitelist_enabled: boolean };
  render_engines: {
    registered: { class_name: string; name: string; active: boolean }[];
    /** Values `renderSubmit({ engine })` accepts right now. */
    selectable: string[];
    active_class: string | null;
    /** "snapshot" when the server answered from its cache because Studio was busy. */
    source: "live" | "snapshot";
    read_at: string;
  };
}

/**
 * An output a job declared, as listed by `GET /artifacts/{id}`. The same
 * fields minus the file metadata appear in the job's
 * `observation.output_manifest.outputs`.
 */
export interface Artifact {
  /** Stable ID (position in the manifest). */
  artifact_id: string;
  /** Download path, `/artifacts/{requestId}/{artifact_id}`. */
  url: string;
  /** Host filesystem path as declared by the job. */
  path: string;
  /** Declared kind; render jobs use `"render"` and `"frame"`. */
  kind?: string;
  label?: string;
  metadata?: Record<string, unknown>;
  /** The declared path is an absolute, existing regular file. */
  available: boolean;
  /** Size in bytes, or `null` when unavailable. */
  size: number | null;
  content_type: string;
  filename: string;
}

/** Response of `GET /artifacts/{id}`. */
export interface ArtifactList {
  success: boolean;
  request_id: string;
  status: string;
  count: number;
  artifacts: Artifact[];
}

/**
 * Status of an async request (`openapi.yaml` `RequestStatus`).
 *
 * Final: `completed`, `failed`, `cancelled`, `completed_after_cancel_request`,
 * `completed_after_stale`. Not final: `cancel_requested` (cancel asked while
 * the script was running; scripts can't be interrupted) and `stale` (running
 * past the Stuck Job Timeout; reported with `success: false` and ends
 * long-polls, but changes to the real outcome if the script returns).
 * `cancelled` means the work really stopped: it never started, or a render
 * was aborted.
 */
export type RequestStatus =
  | "queued"
  | "running"
  | "cancel_requested"
  | "stale"
  | "completed"
  | "failed"
  | "cancelled"
  | "completed_after_cancel_request"
  | "completed_after_stale";

/** The final {@link RequestStatus} values; a request in one of these never changes again. */
export const FINAL_REQUEST_STATUSES: ReadonlySet<RequestStatus> = new Set<RequestStatus>([
  "completed",
  "failed",
  "cancelled",
  "completed_after_cancel_request",
  "completed_after_stale",
]);

/** Body of `DELETE /requests/{id}` and `POST /render/{id}/cancel`. */
export interface CancelResponse {
  request_id: string;
  /** `cancelled` only when the request was still queued; otherwise its current status. Poll it for the real outcome. */
  status: "cancelled" | "cancel_requested" | "stale";
  message: string;
  cancel_requested_at: string;
  /** Present only when `status` is `cancelled`. */
  cancelled_at?: string;
}

/** Options accepted by {@link DazClient.downloadArtifact}. */
export interface DownloadArtifactOptions {
  /** Inclusive byte range `[start, end]`; omit `end` for "to the end of the file". */
  range?: [number, number?];
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

  /**
   * `fetch` with `timeoutMs` (default: the client's) bounding the whole
   * exchange, body included: the body is read into memory before the timer is
   * cleared, so callers' `resp.json()`/`resp.text()` can't hang afterwards.
   * Pass `stream: true` to get the live body back instead (only
   * time-to-headers is bounded then), for downloads that shouldn't be buffered.
   */
  private async fetchWithTimeout(
    url: string,
    init: RequestInit,
    { timeoutMs = this.timeoutMs, stream = false }: { timeoutMs?: number; stream?: boolean } = {},
  ): Promise<Response> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const resp = await fetch(url, { ...init, signal: controller.signal });
      if (stream) {
        return resp;
      }
      const body = resp.status === 204 || resp.status === 304 ? null : await resp.arrayBuffer();
      return new Response(body, { status: resp.status, statusText: resp.statusText, headers: resp.headers });
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") {
        throw new DazTimeoutError(`Request timed out after ${timeoutMs / 1000}s`);
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

  private get(pathname: string, params?: Record<string, string>, timeoutMs?: number): Promise<Response> {
    const url = new URL(`${this.baseUrl}${pathname}`);
    if (params) {
      for (const [k, v] of Object.entries(params)) {
        url.searchParams.set(k, v);
      }
    }
    return this.fetchWithTimeout(url.toString(), { method: "GET", headers: this.headers }, { timeoutMs });
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
    operations: Array<{ bodyLines: string[]; resultExpression: string }>,
    args?: unknown,
  ): Promise<string> {
    const pairs: Array<[string[], string]> = operations.map((op) => [op.bodyLines, op.resultExpression]);
    const script = buildOperationsScript(pairs);
    return this.executeAsyncSubmit(script, args);
  }

  /**
   * Return the current status of an async request.
   *
   * @returns A dict with at least a `status` key: a {@link RequestStatus}, or
   * `"not_found"`. `cancel_requested` and `stale` are not final: a running
   * script can't be interrupted, so once it returns the status changes to its
   * real outcome.
   */
  async getRequestStatus(requestId: string): Promise<Record<string, unknown>> {
    const resp = await this.get(`/requests/${requestId}/status`);
    if (resp.status === 404) {
      return { status: "not_found" };
    }
    return (await raiseForError(resp)) ?? ((await resp.json()) as Record<string, unknown>);
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
    const resp = await this.get(
      `/requests/${requestId}/result`,
      Object.keys(params).length ? params : undefined,
      wait ? (waitTimeout + 10) * 1000 : undefined,
    );
    if (resp.status === 404) {
      return { status: "not_found" };
    }
    return (await raiseForError(resp)) ?? ((await resp.json()) as Record<string, unknown>);
  }

  /**
   * List all tracked async requests (script and render) with their status.
   *
   * @param status - Optional filter: any {@link RequestStatus} (e.g. `"running"`, `"cancel_requested"`).
   */
  async listRequests(status?: RequestStatus): Promise<Record<string, unknown>> {
    const resp = await this.get("/requests", status ? { status } : undefined);
    if (resp.status === 401 || resp.status === 403) {
      throw new AuthenticationError(`HTTP ${resp.status}: ${(await resp.text()).slice(0, 200)}`);
    }
    return (await resp.json()) as Record<string, unknown>;
  }

  /**
   * Cancel a script or render request and return the server's response.
   *
   * Render requests (`rnd-` IDs) go to `POST /render/{id}/cancel`; others to
   * `DELETE /requests/{id}`. A queued request comes back `cancelled`; a
   * running one comes back `cancel_requested` (or `stale`), so poll it for
   * the real outcome.
   *
   * @throws {DazError} If the server rejects the cancel (e.g. unknown request).
   */
  async cancelRequestDetail(requestId: string): Promise<CancelResponse> {
    const resp = requestId.startsWith("rnd-")
      ? await this.post(`/render/${requestId}/cancel`, {})
      : await this.delete_(`/requests/${requestId}`);
    if (resp === null) {
      throw new ConnectionError(`Could not reach the server to cancel ${requestId}`);
    }
    const errData = await raiseForError(resp);
    if (errData !== undefined) {
      throw new DazError((errData.error as string) ?? `HTTP ${resp.status}`);
    }
    return (await resp.json()) as CancelResponse;
  }

  /**
   * Cancel a queued or running async request.
   *
   * @returns `true` if the server accepted the cancel, `false` otherwise. A
   * queued request is cancelled at once; a running one only becomes
   * `cancel_requested` (scripts can't be interrupted), so poll the request
   * for its real outcome.
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
   * Open an SSE stream. The timeout and the caller's signal stay attached to
   * the returned body, so they bound reading the stream, not just connecting.
   */
  private async openStream(url: string, opts: StreamOptions): Promise<Response | null> {
    const { timeoutMs, signal } = opts;
    const controller = new AbortController();
    if (signal) {
      if (signal.aborted) {
        controller.abort(signal.reason);
      } else {
        signal.addEventListener("abort", () => controller.abort(signal.reason), { once: true });
      }
    }
    let timer: ReturnType<typeof setTimeout> | undefined;
    if (timeoutMs !== undefined) {
      timer = setTimeout(
        () => controller.abort(new DazTimeoutError(`Stream timed out after ${timeoutMs / 1000}s`)),
        timeoutMs,
      );
      // Don't keep the process alive just to abort a stream nobody is reading.
      timer.unref?.();
    }
    let resp: Response;
    try {
      resp = await fetch(url, { headers: this.headers, signal: controller.signal });
    } catch (e) {
      clearTimeout(timer);
      if (e instanceof DazTimeoutError || (signal?.aborted && e === signal.reason)) {
        throw e;
      }
      const message = e instanceof Error ? e.message : String(e);
      throw new ConnectionError(`Cannot reach DAZ Studio at ${this.baseUrl}: ${message}`);
    }
    if (resp.status === 401 || resp.status === 403) {
      clearTimeout(timer);
      throw new AuthenticationError(`HTTP ${resp.status}: ${(await resp.text()).slice(0, 200)}`);
    }
    if (resp.status !== 200) {
      clearTimeout(timer);
      await resp.body?.cancel();
      return null;
    }
    return resp;
  }

  /**
   * Open the SSE progress stream for a render request.
   *
   * @returns The raw streaming `Response` on success, or `null` if the server
   * answers with any other non-auth status (e.g. 404: no such render, or a
   * server without the endpoint), so callers can fall back to polling. Pass
   * the result to {@link parseSseStream} to consume it, and let the body
   * drain or cancel the reader.
   * @throws {AuthenticationError} On HTTP 401/403.
   * @throws {ConnectionError} If the server can't be reached.
   * @throws {DazTimeoutError} If `opts.timeoutMs` elapses (also from reads of the body).
   */
  async streamRenderProgress(requestId: string, opts: StreamOptions = {}): Promise<Response | null> {
    return this.openStream(`${this.baseUrl}/render/${requestId}/progress`, opts);
  }

  /**
   * Open the SSE stream for general scene-change events (`GET /scene/events`).
   *
   * @param categories - Optional subset of event categories to subscribe to
   * (`"node"`, `"skeleton"`, `"light"`, `"camera"`, `"selection"`, `"scene"`,
   * `"time"`, `"render"`). Omit to subscribe to all categories.
   * @param opts - Stream lifetime / abort signal. With no `timeoutMs` the
   * stream stays open until the caller stops reading — the server sends a
   * keepalive comment every 15 seconds.
   * @returns The raw streaming `Response`, or `null` on a non-auth, non-200 status.
   * @throws {AuthenticationError} On HTTP 401/403.
   * @throws {ConnectionError} If the server can't be reached.
   * @throws {DazTimeoutError} If `opts.timeoutMs` elapses (also from reads of the body).
   */
  async streamSceneEvents(categories?: string[], opts: StreamOptions = {}): Promise<Response | null> {
    const url = new URL(`${this.baseUrl}/scene/events`);
    if (categories && categories.length > 0) {
      url.searchParams.set("filter", categories.join(","));
    }
    return this.openStream(url.toString(), opts);
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

  /**
   * Return the server's capabilities document from `GET /capabilities`:
   * versions, routes, feature flags, current limits and the render engines
   * registered right now. Servers that predate the endpoint answer 404, which
   * throws a `DazError`; 401/403 throw `AuthenticationError`, and 503 before
   * the server has a snapshot throws `StudioBusyError`.
   */
  /**
   * List the files an async job declared (`GET /artifacts/{id}`): outputs
   * from its `reportFile` plus the image(s) a render job wrote, each with
   * size, content type and availability. Use with {@link downloadArtifact}
   * when the client can't see DAZ Studio's filesystem.
   */
  async listArtifacts(requestId: string): Promise<ArtifactList> {
    const resp = await this.get(`/artifacts/${encodeURIComponent(requestId)}`);
    await throwArtifactError(resp);
    return (await resp.json()) as ArtifactList;
  }

  /**
   * Download one declared artifact (`GET /artifacts/{id}/{artifact_id}`).
   * Returns the bytes, or, when `dest` is given, streams them into that file
   * and returns its path. `range` sends an HTTP `Range` header (206 reply).
   * Rejections throw {@link ArtifactError}; 401/403 throw `AuthenticationError`.
   */
  async downloadArtifact(requestId: string, artifactId: string | number, opts?: DownloadArtifactOptions): Promise<Buffer>;
  async downloadArtifact(
    requestId: string,
    artifactId: string | number,
    dest: string,
    opts?: DownloadArtifactOptions,
  ): Promise<string>;
  async downloadArtifact(
    requestId: string,
    artifactId: string | number,
    destOrOpts?: string | DownloadArtifactOptions,
    maybeOpts?: DownloadArtifactOptions,
  ): Promise<Buffer | string> {
    const dest = typeof destOrOpts === "string" ? destOrOpts : undefined;
    const opts = (typeof destOrOpts === "string" ? maybeOpts : destOrOpts) ?? {};
    const headers: Record<string, string> = { ...this.headers };
    if (opts.range) {
      const [start, end] = opts.range;
      if (!Number.isInteger(start) || start < 0 || (end !== undefined && (!Number.isInteger(end) || end < start))) {
        throw new RangeError(`invalid range [${start}, ${end}]`);
      }
      headers.Range = `bytes=${start}-${end ?? ""}`;
    }
    const url = `${this.baseUrl}/artifacts/${encodeURIComponent(requestId)}/${encodeURIComponent(String(artifactId))}`;
    // Artifacts can be large: stream the body rather than buffering it, so
    // the client timeout covers only time-to-headers here.
    const resp = await this.fetchWithTimeout(url, { method: "GET", headers }, { stream: true });
    await throwArtifactError(resp);
    if (dest === undefined) {
      return Buffer.from(await resp.arrayBuffer());
    }
    if (!resp.body) {
      await fs.promises.writeFile(dest, Buffer.alloc(0));
    } else {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      await pipeline(Readable.fromWeb(resp.body as any), fs.createWriteStream(dest));
    }
    return dest;
  }

  /**
   * Download every available artifact of a job into `destDir`, named
   * `<artifact_id>_<filename>` so equal base names can't collide. Returns the
   * written paths in manifest order.
   */
  async downloadArtifacts(requestId: string, destDir: string): Promise<string[]> {
    await fs.promises.mkdir(destDir, { recursive: true });
    const written: string[] = [];
    for (const entry of (await this.listArtifacts(requestId)).artifacts ?? []) {
      if (!entry.available) continue;
      const aid = String(entry.artifact_id);
      const name = safeArtifactFilename(entry.filename || "artifact");
      written.push(await this.downloadArtifact(requestId, aid, path.join(destDir, `${aid}_${name}`)));
    }
    return written;
  }

  async capabilities(): Promise<ServerCapabilities> {
    const resp = await this.get("/capabilities");
    const errData = await raiseForError(resp);
    if (errData) {
      const msg = (errData.error as string) ?? `HTTP ${resp.status}`;
      throw new DazError(`capabilities failed (${resp.status}): ${msg}`);
    }
    return (await resp.json()) as ServerCapabilities;
  }

  /**
   * Save a copy of the scene to `path` without changing the scene's current
   * file or dirty state (like "Save a Copy As..."). See dazpy's
   * `DazScene.save_copy` for the copy-vs-serialize tradeoff this makes
   * server-side.
   */
  async sceneSaveCopy(path: string): Promise<Record<string, unknown>> {
    const resp = await this.post("/scene/save-copy", { path });
    if (resp.status === 401 || resp.status === 403) {
      throw new AuthenticationError(`HTTP ${resp.status}: ${(await resp.text()).slice(0, 200)}`);
    }
    if (!resp.ok) {
      const body = (await resp.json().catch(() => ({}))) as Record<string, unknown>;
      const msg = (body.error as string) ?? (body.detail as string) ?? `HTTP ${resp.status}`;
      throw new DazError(`sceneSaveCopy failed (${resp.status}): ${msg}`);
    }
    return (await resp.json()) as Record<string, unknown>;
  }
}
