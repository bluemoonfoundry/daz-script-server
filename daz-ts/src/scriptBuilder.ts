import type { NodeIdentifier } from "./node.js";

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

  /** DazScript expression that resolves `identifier` via `Scene.findNode`/`.findNodeByLabel`. */
  static findNodeExpr(identifier: NodeIdentifier): string {
    if (identifier.kind === "label") {
      return `Scene.findNodeByLabel(${ScriptBuilder.escapeString(identifier.value)})`;
    }
    return `Scene.findNode(${ScriptBuilder.escapeString(identifier.value)})`;
  }

  /** Wrap `body` in an IIFE that resolves `identifier` to `_node` and null-guards it. */
  static nodeBody(identifier: NodeIdentifier, body: string): string {
    const expr = ScriptBuilder.findNodeExpr(identifier);
    return ScriptBuilder.iife(`var _node = ${expr};\nif (!_node) return null;\n${body}`);
  }

  /** Like {@link nodeBody} but uses a pre-built DazScript locator expression for `_node`. */
  static nodeBodyFromLocator(locator: string, body: string): string {
    return ScriptBuilder.iife(`var _node = ${locator};\nif (!_node) return null;\n${body}`);
  }

  /**
   * Return a JS snippet (not wrapped in an IIFE) that finds a skeleton by
   * `identifier` and binds it to `_skel`. Embed at the top of a larger body
   * and follow with `if (!_skel) return null;`.
   */
  static skeletonLookup(identifier: NodeIdentifier): string {
    const value = ScriptBuilder.escapeString(identifier.value);
    const match =
      identifier.kind === "label" ? `_skels[_i].getLabel() === ${value}` : `_skels[_i].getName() === ${value}`;
    return (
      `var _skel=null,_skels=Scene.getSkeletonList();` +
      `for(var _i=0;_i<_skels.length;_i++){` +
      `if(${match}){_skel=_skels[_i];break;}}`
    );
  }

  /** Like {@link skeletonLookup} but binds the result to `_node` instead of `_skel`, for callers using the shared `_node`-based body convention. */
  static skeletonLookupAsNode(identifier: NodeIdentifier): string {
    const value = ScriptBuilder.escapeString(identifier.value);
    const match =
      identifier.kind === "label" ? `_skels[_i].getLabel() === ${value}` : `_skels[_i].getName() === ${value}`;
    return (
      `var _node=null,_skels=Scene.getSkeletonList();` +
      `for(var _i=0;_i<_skels.length;_i++){` +
      `if(${match}){_node=_skels[_i];break;}}`
    );
  }
}
