/** High-level render API -- convenience wrappers over `/render` and `/render/batch`. */

import { DazClient, parseSseStream } from "./client.js";
import { DazTimeoutError, RenderError } from "./exceptions.js";

/** A figure and the morph values to apply before rendering. */
export interface FigureMorphs {
  name: string | null;
  morphs?: Record<string, number>;
}

/** A single output variant for batch rendering. */
export interface RenderVariantSpec {
  outputPath: string;
  figure?: string;
  morphs?: Record<string, number>;
  figures?: FigureMorphs[];
  width?: number;
  height?: number;
  camera?: string;
  engine?: string;
}

/** Shared defaults applied to all variants in a batch render. */
export interface RenderBaseSpec {
  figure?: string;
  morphs?: Record<string, number>;
  figures?: FigureMorphs[];
  width?: number;
  height?: number;
  camera?: string;
  engine?: string;
}

/** Result of a single render operation. */
export interface RenderResult {
  success: boolean;
  outputPath: string;
  fileSizeBytes: number;
  durationMs: number;
  error: string;
  requestId: string;
}

function sleepMs(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function figuresToPayload(figures: FigureMorphs[]): Array<{ name: string | null; morphs: Record<string, number> }> {
  return figures.map((f) => ({ name: f.name, morphs: f.morphs ?? {} }));
}

function variantToDict(v: RenderVariantSpec): Record<string, unknown> {
  const d: Record<string, unknown> = { output_path: v.outputPath };
  if (v.figures && v.figures.length > 0) {
    d.figures = figuresToPayload(v.figures);
  } else if (v.figure) {
    d.figure = v.figure;
    if (v.morphs) d.morphs = v.morphs;
  }
  if (v.width && v.height) {
    d.width = v.width;
    d.height = v.height;
  }
  if (v.camera) d.camera = v.camera;
  if (v.engine) d.engine = v.engine;
  return d;
}

function baseToDict(b: RenderBaseSpec): Record<string, unknown> {
  const d: Record<string, unknown> = {};
  if (b.figures && b.figures.length > 0) {
    d.figures = figuresToPayload(b.figures);
  } else if (b.figure) {
    d.figure = b.figure;
    if (b.morphs) d.morphs = b.morphs;
  }
  if (b.width && b.height) {
    d.width = b.width;
    d.height = b.height;
  }
  if (b.camera) d.camera = b.camera;
  if (b.engine) d.engine = b.engine;
  return d;
}

/**
 * Wait for a render to complete using the SSE progress stream.
 *
 * Falls back to request-result long-polling if the SSE stream cannot be
 * established or ends without a `complete`/`error` event.
 *
 * `onProgress`, if given, is called with the raw `"progress"` event payload
 * (e.g. `{request_id, percent, frame, total_frames}` for animation renders;
 * single-shot renders only get one such event at 0% when the render starts
 * -- the DAZ SDK exposes no intra-frame percent signal).
 */
async function waitRenderSse(
  client: DazClient,
  requestId: string,
  timeoutMs: number,
  onProgress?: (data: Record<string, unknown>) => void,
): Promise<RenderResult> {
  const deadline = Date.now() + timeoutMs;

  try {
    const resp = await client.streamRenderProgress(requestId, timeoutMs + 5_000);
    if (resp !== null) {
      for await (const { event, data } of parseSseStream(resp)) {
        if (Date.now() > deadline) break;
        let parsed: Record<string, unknown>;
        try {
          parsed = JSON.parse(data) as Record<string, unknown>;
        } catch {
          parsed = { _raw: data };
        }
        if (event === "complete") {
          return {
            success: true,
            outputPath: (parsed.output_path as string) ?? "",
            fileSizeBytes: parsed.file_size_bytes !== undefined ? Number(parsed.file_size_bytes) : -1,
            durationMs: parsed.duration_ms !== undefined ? Number(parsed.duration_ms) : 0,
            error: "",
            requestId,
          };
        }
        if (event === "error") {
          throw new RenderError((parsed.error as string) ?? "Render failed", requestId);
        }
        if (event === "progress" && onProgress !== undefined) {
          onProgress(parsed);
        }
      }
    }
  } catch (e) {
    if (e instanceof RenderError || e instanceof DazTimeoutError) {
      throw e;
    }
    // SSE unavailable -- fall through to polling.
  }

  // Polling fallback.
  while (Date.now() < deadline) {
    const remainingSec = Math.max(1, Math.ceil((deadline - Date.now()) / 1000));
    const data = await client.getRequestResult(requestId, true, Math.min(30, remainingSec));
    if (data.success !== undefined && data.success !== null) {
      if (!data.success) {
        throw new RenderError((data.error as string) ?? "Render failed", requestId);
      }
      const resultVal = data.result;
      const outPath = typeof resultVal === "object" && resultVal !== null ? ((resultVal as Record<string, unknown>).output_path as string) ?? "" : "";
      return {
        success: true,
        outputPath: outPath,
        fileSizeBytes: -1,
        durationMs: data.duration_ms !== undefined ? Number(data.duration_ms) : 0,
        error: "",
        requestId,
      };
    }
    const status = data.status;
    if (status === "failed") {
      throw new RenderError((data.error as string) ?? "Render failed", requestId);
    }
    if (status === "cancelled") {
      throw new RenderError("Render was cancelled", requestId);
    }
    await sleepMs(500);
  }

  throw new DazTimeoutError(`Render timed out after ${timeoutMs / 1000}s (requestId=${JSON.stringify(requestId)})`);
}

/** Options for {@link render}. */
export interface RenderCallOptions {
  /** Label of the figure to configure morphs on. */
  figure?: string;
  /** Morph values to apply `{label: value}`. Only used when `figure` is set. */
  morphs?: Record<string, number>;
  /** List of {@link FigureMorphs} for multi-figure scenes. Mutually exclusive with `figure`. */
  figures?: FigureMorphs[];
  /** Image width in pixels (must be paired with `height`). */
  width?: number;
  /** Image height in pixels (must be paired with `width`). */
  height?: number;
  /** Camera label to render from. Defaults to the active viewport camera. */
  camera?: string;
  /** Render engine (`"iray"`, `"viewport"`, `"filament"`). */
  engine?: string;
  /** Iray sample count (0 = use scene default). */
  iraySamples?: number;
  /** If `true`, reset all figure morph values to defaults before applying `morphs`. */
  resetMorphs?: boolean;
  /**
   * If `true` (default), await until the render completes and return a
   * fully populated {@link RenderResult}. If `false`, return immediately
   * after the job is accepted; the result will have `fileSizeBytes: -1` and
   * `durationMs: 0`.
   */
  wait?: boolean;
  /** Maximum milliseconds to wait when `wait` is `true`. Default `300000` (5 minutes). */
  timeoutMs?: number;
  /** Optional callback invoked with each `"progress"` SSE event's raw payload while waiting. */
  onProgress?: (data: Record<string, unknown>) => void;
}

/**
 * Render the DAZ Studio scene to `outputPath`.
 *
 * Uses the SSE progress stream (`GET /render/:id/progress`) when available;
 * falls back to long-poll on `/requests/:id/result` otherwise.
 *
 * @throws RenderError If the render fails.
 * @throws DazTimeoutError If `timeoutMs` is exceeded.
 * @throws ConnectionError If the server cannot be reached.
 * @throws AuthenticationError On HTTP 401/403.
 *
 * @example
 * ```ts
 * const client = new DazClient();
 * const result = await render(client, "C:\\tmp\\out.png", { width: 1920, height: 1080 });
 * console.log(result.outputPath, result.fileSizeBytes);
 * ```
 */
export async function render(client: DazClient, outputPath: string, opts: RenderCallOptions = {}): Promise<RenderResult> {
  const {
    figure,
    morphs,
    figures,
    width = 0,
    height = 0,
    camera = "",
    engine = "",
    iraySamples = 0,
    resetMorphs = false,
    wait = true,
    timeoutMs = 300_000,
    onProgress,
  } = opts;

  const data = await client.renderSubmit(outputPath, {
    figure,
    morphs,
    figures: figures !== undefined ? figuresToPayload(figures) : undefined,
    width,
    height,
    camera,
    engine,
    iraySamples,
    resetMorphs,
  });
  const requestId = (data.request_id as string) ?? "";

  if (!wait) {
    return { success: true, outputPath, fileSizeBytes: -1, durationMs: 0, error: "", requestId };
  }

  return waitRenderSse(client, requestId, timeoutMs, onProgress);
}

/** Options for {@link renderVariants}. */
export interface RenderVariantsOptions {
  /** Optional callback called with `(completed, total)` after each render finishes. */
  onProgress?: (completed: number, total: number) => void;
  /** Maximum total milliseconds to wait for all renders to finish. Default `300000` (5 minutes). */
  timeoutMs?: number;
}

/**
 * Render multiple variants via `POST /render/batch`.
 *
 * Submits all variants in a single batch request, then waits for each
 * render to complete sequentially, calling `onProgress` after each one
 * finishes.
 *
 * @returns A list of {@link RenderResult} in the same order as `variants`.
 * If a variant fails, its result will have `success: false` and `error`
 * set; subsequent variants are still attempted.
 * @throws DazTimeoutError If `timeoutMs` is exceeded.
 * @throws ConnectionError If the server cannot be reached.
 * @throws AuthenticationError On HTTP 401/403.
 *
 * @example
 * ```ts
 * const client = new DazClient();
 * const results = await renderVariants(
 *   client,
 *   [
 *     { outputPath: "C:\\tmp\\smile.png", figure: "Genesis 9", morphs: { Smile: 1.0 } },
 *     { outputPath: "C:\\tmp\\neutral.png", figure: "Genesis 9" },
 *   ],
 *   { width: 1920, height: 1080, engine: "iray" },
 *   { onProgress: (done, total) => console.log(`${done}/${total}`) },
 * );
 * ```
 */
export async function renderVariants(
  client: DazClient,
  variants: RenderVariantSpec[],
  base?: RenderBaseSpec,
  opts: RenderVariantsOptions = {},
): Promise<RenderResult[]> {
  const { onProgress, timeoutMs = 300_000 } = opts;
  const variantsPayload = variants.map(variantToDict);
  const basePayload = base !== undefined ? baseToDict(base) : undefined;

  const data = await client.renderBatchSubmit(variantsPayload, basePayload);
  const requestIds = (data.request_ids as string[]) ?? [];
  const total = requestIds.length;

  const results: RenderResult[] = [];
  const deadline = Date.now() + timeoutMs;
  let completed = 0;

  for (let i = 0; i < requestIds.length; i++) {
    const requestId = requestIds[i];
    const remainingMs = Math.max(1_000, deadline - Date.now());
    let result: RenderResult;
    try {
      result = await waitRenderSse(client, requestId, remainingMs);
    } catch (e) {
      if (e instanceof RenderError) {
        result = {
          success: false,
          outputPath: i < variants.length ? variants[i].outputPath : "",
          fileSizeBytes: -1,
          durationMs: 0,
          error: e.message,
          requestId,
        };
      } else {
        throw e;
      }
    }
    results.push(result);
    completed += 1;
    if (onProgress !== undefined) {
      onProgress(completed, total);
    }
  }

  return results;
}
