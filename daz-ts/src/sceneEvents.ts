/**
 * General scene-change event stream -- SSE-based watcher for `GET /scene/events`.
 * Mirrors dazpy's `_scene_events.py`.
 *
 * Mirrors the shape of the render-progress stream (`renderApi.ts`'s
 * `waitRenderSse`/`parseSseStream`) but for the broader set of scene-change
 * notifications DAZ Studio emits: nodes/skeletons/lights/cameras added or
 * removed, selection changes, time scrubs, scene load/save, and render
 * start/end.
 */

import { ConnectionError, DazTimeoutError } from "./exceptions.js";
import { DazClient, parseSseStream } from "./client.js";

const VALID_CATEGORIES = new Set(["node", "skeleton", "light", "camera", "selection", "scene", "time", "render"]);

/** A single scene-change event received from the SSE stream. */
export interface SceneEvent {
  type: string;
  ts: number;
  data: Record<string, unknown>;
}

async function* parseSceneEvents(response: Response): AsyncGenerator<SceneEvent> {
  for await (const { data } of parseSseStream(response)) {
    let raw: Record<string, unknown>;
    try {
      raw = JSON.parse(data) as Record<string, unknown>;
    } catch {
      continue;
    }
    yield {
      type: (raw.type as string) ?? "",
      ts: (raw.ts as number) ?? 0,
      data: (raw.data as Record<string, unknown>) ?? {},
    };
  }
}

/**
 * Yield {@link SceneEvent} objects as DAZ Studio reports scene changes.
 *
 * Opens an SSE connection to `GET /scene/events` and yields events as they
 * arrive, filtered server-side by `categories` and optionally client-side
 * by exact `eventTypes` (e.g. `["node.added", "node.removed"]`).
 *
 * The connection stays open until the caller stops iterating (e.g. via
 * `break`) or the server closes the stream.
 *
 * @param categories Optional subset of event categories to subscribe to
 * server-side. Omit to subscribe to all categories.
 * @param eventTypes Optional set of exact event types to keep; all others
 * are dropped client-side. Omit to yield every event received.
 * @param streamTimeoutMs Socket timeout in milliseconds. Omit to wait
 * indefinitely -- the server sends a keepalive comment every 15 seconds, so
 * the connection never idles out.
 *
 * @throws ConnectionError If the SSE endpoint could not be reached.
 *
 * @example
 * ```ts
 * const client = new DazClient();
 * for await (const event of watchSceneEvents(client, ["node", "selection"])) {
 *   console.log(event.type, event.data);
 *   if (event.type === "node.added") break;
 * }
 * ```
 */
export async function* watchSceneEvents(
  client: DazClient,
  categories?: string[],
  eventTypes?: string[],
  streamTimeoutMs?: number,
): AsyncGenerator<SceneEvent> {
  const resp = await client.streamSceneEvents(categories, streamTimeoutMs);
  if (resp === null) {
    throw new ConnectionError("Could not open /scene/events stream");
  }
  const eventTypeSet = eventTypes !== undefined ? new Set(eventTypes) : undefined;
  for await (const event of parseSceneEvents(resp)) {
    if (eventTypeSet !== undefined && !eventTypeSet.has(event.type)) {
      continue;
    }
    yield event;
  }
}

/**
 * Block until a scene event of `eventType` arrives, then return it.
 *
 * @param eventType Exact event type to wait for, e.g. `"node.added"` or
 * `"render.finished"`. The category prefix (text before the first `.`) is
 * used to narrow the server-side subscription.
 * @param timeoutMs Maximum milliseconds to wait. Default `300000` (5 minutes).
 *
 * @throws DazTimeoutError If `timeoutMs` elapses before a matching event arrives.
 * @throws ConnectionError If the SSE endpoint could not be reached.
 */
export async function waitForSceneEvent(client: DazClient, eventType: string, timeoutMs = 300_000): Promise<SceneEvent> {
  const category = eventType.split(".")[0];
  const categories = VALID_CATEGORIES.has(category) ? [category] : undefined;

  try {
    for await (const event of watchSceneEvents(client, categories, [eventType], timeoutMs + 5_000)) {
      return event;
    }
  } catch (e) {
    if (e instanceof ConnectionError) {
      throw e;
    }
    // stream read timed out or connection dropped -- fall through
  }

  throw new DazTimeoutError(`Timed out after ${timeoutMs / 1000}s waiting for ${JSON.stringify(eventType)}`);
}
