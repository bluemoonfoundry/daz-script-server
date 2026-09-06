import type { DazClient } from "./client.js";
import { BatchLimitExceededError } from "./exceptions.js";

export const DEFAULT_MAX_OPERATIONS = 500;
export const DEFAULT_MAX_SCRIPT_LENGTH = 900_000; // stays under the server's default 1MB script cap

/**
 * Build one IIFE script from a list of `[bodyLines, resultExpression]` pairs.
 *
 * Shared by {@link Batch}'s internal script builder and
 * {@link DazClient.executeBatchAsync} so both produce scripts with an
 * identical shape (keyed return object over `_r0`, `_r1`, ...).
 */
export function buildOperationsScript(operations: Array<[string[], string]>): string {
  const bodyLines: string[] = [];
  const returnParts: string[] = [];
  operations.forEach(([lines, resultExpression], i) => {
    const key = `_r${i}`;
    bodyLines.push(...lines);
    bodyLines.push(`var ${key} = ${resultExpression};`);
    returnParts.push(`"${key}": ${key}`);
  });
  const returnObj = `{${returnParts.join(", ")}}`;
  bodyLines.push(`return ${returnObj};`);
  const body = bodyLines.join("\n");
  return `(function(){\n${body}\n})()`;
}

/**
 * Placeholder for a single result within a {@link Batch} execution.
 *
 * Created by {@link Batch.add} or {@link Batch.addOperation}; the `value`
 * getter throws until the batch has been executed.
 */
export class BatchFuture {
  private resolved = false;
  private resultValue: unknown = undefined;

  constructor(private readonly key: string) {}

  /** The result value. Throws if {@link Batch.execute} has not been called yet. */
  get value(): unknown {
    if (!this.resolved) {
      throw new Error("Batch has not been executed yet");
    }
    return this.resultValue;
  }

  /** @internal */
  _resolve(value: unknown): void {
    this.resultValue = value;
    this.resolved = true;
  }

  /** @internal */
  get _key(): string {
    return this.key;
  }
}

/** Options accepted by the {@link Batch} constructor. */
export interface BatchOptions {
  /** Max queued operations before {@link Batch.addOperation} throws {@link BatchLimitExceededError}. */
  maxOperations?: number;
  /** Max generated script length (characters) before {@link Batch.execute} throws {@link BatchLimitExceededError}. */
  maxScriptLength?: number;
}

/**
 * Collect multiple DazScript operations and execute them in a single HTTP round-trip.
 *
 * Semantics (preserved exactly from dazpy, do not "improve" silently):
 * execution is **serial**, there is **no parallelism**, and the batch is
 * **not transactional** — if any operation throws, the whole call fails
 * the same way a single failing `execute()` call would, and earlier
 * mutations already applied to the live scene are **not** rolled back.
 * Order destructive/hard-to-recover operations last.
 *
 * @example
 * ```ts
 * const batch = new Batch(client);
 * const posFuture = batch.addOperation(
 *   ["var n = Scene.findNode('Figure');", "var p = [n.getWSPos().x, n.getWSPos().y, n.getWSPos().z];"],
 *   "p",
 * );
 * await batch.execute();
 * console.log(posFuture.value);
 * ```
 */
export class Batch {
  private readonly client: DazClient;
  private readonly ops: Array<{ key: string; lines: string[]; future: BatchFuture }> = [];
  private readonly preludes = new Map<string, string[]>();
  private readonly preludeOrder: string[] = [];
  private counter = 0;
  private readonly maxOperations: number;
  private readonly maxScriptLength: number;

  constructor(client: DazClient, options: BatchOptions = {}) {
    this.client = client;
    this.maxOperations = options.maxOperations ?? DEFAULT_MAX_OPERATIONS;
    this.maxScriptLength = options.maxScriptLength ?? DEFAULT_MAX_SCRIPT_LENGTH;
  }

  /**
   * Queue DazScript lines to be included in the batch.
   *
   * The last line in `lines` should assign the desired result to a
   * variable named after the internally generated key (`_r0`, `_r1`, ...
   * in call order). Prefer {@link addOperation}, which does not require
   * guessing the key name.
   */
  add(lines: string[]): BatchFuture {
    const key = `_r${this.counter++}`;
    const future = new BatchFuture(key);
    this.ops.push({ key, lines: [...lines], future });
    return future;
  }

  /**
   * Register a shared setup block, emitted once per unique `preludeKey`.
   *
   * Call this before {@link addOperation} calls whose bodies depend on the
   * prelude's bound variable(s). Repeated calls with the same `preludeKey`
   * are no-ops after the first.
   */
  addPrelude(preludeKey: string, lines: string[]): void {
    if (!this.preludes.has(preludeKey)) {
      this.preludes.set(preludeKey, [...lines]);
      this.preludeOrder.push(preludeKey);
    }
  }

  /**
   * Queue an operation whose result the builder assigns internally.
   *
   * @param bodyLines - DazScript source lines with no trailing result assignment.
   * @param resultExpression - A JS expression evaluated once after `bodyLines`
   * run, used as this operation's result. Mutation-only operations should pass `"null"`.
   * @throws {BatchLimitExceededError} If this call would exceed `maxOperations`.
   */
  addOperation(bodyLines: string[], resultExpression: string): BatchFuture {
    if (this.ops.length >= this.maxOperations) {
      throw new BatchLimitExceededError(
        `Batch already has ${this.ops.length} operations (maxOperations=${this.maxOperations})`,
      );
    }
    const key = `_r${this.counter++}`;
    const future = new BatchFuture(key);
    const lines = [...bodyLines, `var ${key} = ${resultExpression};`];
    this.ops.push({ key, lines, future });
    return future;
  }

  private buildScript(): string {
    const bodyLines: string[] = [];
    for (const preludeKey of this.preludeOrder) {
      bodyLines.push(...(this.preludes.get(preludeKey) ?? []));
    }
    const returnParts: string[] = [];
    for (const { key, lines } of this.ops) {
      bodyLines.push(...lines);
      returnParts.push(`"${key}": ${key}`);
    }
    const returnObj = `{${returnParts.join(", ")}}`;
    bodyLines.push(`return ${returnObj};`);
    const body = bodyLines.join("\n");
    return `(function(){\n${body}\n})()`;
  }

  /**
   * Execute all queued operations in a single HTTP request and resolve every future.
   *
   * @throws {BatchLimitExceededError} If the generated script exceeds
   * `maxScriptLength`. Raised before any HTTP call.
   */
  async execute(): Promise<void> {
    if (this.ops.length === 0) {
      return;
    }
    const script = this.buildScript();
    if (script.length > this.maxScriptLength) {
      throw new BatchLimitExceededError(
        `Generated batch script is ${script.length} characters (maxScriptLength=${this.maxScriptLength})`,
      );
    }
    const result = await this.client.execute(script);
    const data = (result.value as Record<string, unknown>) ?? {};
    for (const { key, future } of this.ops) {
      future._resolve(data[key]);
    }
  }
}
