/**
 * Helpers for building injection-safe DazScript source strings.
 *
 * Every value interpolated into a generated script MUST go through
 * {@link ScriptBuilder.escapeString} or {@link ScriptBuilder.serializeArg} —
 * never concatenated raw. This is the port's core injection-safety
 * invariant (mirrors dazpy's `json.dumps()`-based escaping).
 */
export class ScriptBuilder {
  /** Return `value` as a JSON string literal, safe to embed in DazScript source. */
  static escapeString(value: string): string {
    return JSON.stringify(value);
  }

  /** Wrap `body` in an immediately-invoked function expression. */
  static iife(body: string): string {
    return `(function(){\n${body}\n})()`;
  }

  /**
   * Serialize an arbitrary argument value for embedding in generated
   * DazScript source. Booleans and numbers become bare literals; strings
   * and everything else are JSON-encoded.
   */
  static serializeArg(value: unknown): string {
    if (typeof value === "boolean") {
      return value ? "true" : "false";
    }
    if (typeof value === "number") {
      return String(value);
    }
    return JSON.stringify(value);
  }
}
