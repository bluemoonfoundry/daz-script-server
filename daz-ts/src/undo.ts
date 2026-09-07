import type { DazClient } from "./client.js";
import { ScriptBuilder } from "./scriptBuilder.js";

/**
 * Groups DAZ Studio operations into a single undo step. TypeScript has no
 * `with` statement, so this is not a context manager (unlike dazpy's
 * `UndoGroup`) — call {@link begin}, then either {@link commit} or
 * {@link cancel}, or prefer the {@link withUndo} helper / `DazScene.undo()`
 * which does this for you around a callback.
 */
export class UndoGroup {
  private readonly client: DazClient;
  private readonly label: string;

  constructor(client: DazClient, label: string) {
    this.client = client;
    this.label = label;
  }

  async begin(): Promise<void> {
    await this.client.execute(ScriptBuilder.iife("beginUndo();"));
  }

  /** Commit the grouped changes as a single undo step labeled per the constructor. */
  async commit(): Promise<void> {
    await this.client.execute(ScriptBuilder.iife(`acceptUndo(${ScriptBuilder.escapeString(this.label)});`));
  }

  /** Discard the undo grouping (the underlying changes are not reverted; this only cancels the *grouping*, matching dazpy's `cancelUndo()`). */
  async cancel(): Promise<void> {
    await this.client.execute(ScriptBuilder.iife("cancelUndo();"));
  }
}

/**
 * Run `fn` inside an {@link UndoGroup}: `begin()`, then `fn()`, then
 * `commit()` on success or `cancel()` (then rethrow) if `fn` throws —
 * the TS equivalent of dazpy's `with scene.undo(label): ...`.
 */
export async function withUndo<T>(client: DazClient, label: string, fn: () => Promise<T>): Promise<T> {
  const group = new UndoGroup(client, label);
  await group.begin();
  try {
    const result = await fn();
    await group.commit();
    return result;
  } catch (err) {
    await group.cancel();
    throw err;
  }
}
