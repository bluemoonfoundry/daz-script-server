import type { DazClient } from "./client.js";
import { DazElement } from "./element.js";
import { ScriptBuilder } from "./scriptBuilder.js";

/**
 * Proxy for a `DzProperty` on any `DzElement`. Typed read/write access to a
 * single named property, including keyframe support for animated properties.
 */
export class DazProperty extends DazElement {
  constructor(client: DazClient, ownerLocator: string, propertyLabel: string) {
    const locator =
      `(function(){` +
      `var obj = ${ownerLocator};` +
      `return obj ? obj.findPropertyByLabel(${ScriptBuilder.escapeString(propertyLabel)}) : null;` +
      `})()`;
    super(client, locator);
  }

  /** Construct a `DazProperty` from a pre-built DazScript locator expression. */
  static fromLocator(client: DazClient, locator: string): DazProperty {
    const prop = Object.create(DazProperty.prototype) as DazProperty;
    (prop as any).client = client;
    (prop as any).locator = locator;
    (prop as any).cache = new Map();
    return prop;
  }

  /** Current property value (read/write). */
  async value(): Promise<unknown> {
    const script = ScriptBuilder.iife(`var p = ${this.locator}; return p ? p.getValue() : null;`);
    return (await this.client.execute(script)).value;
  }

  async setValue(v: unknown): Promise<void> {
    const script = ScriptBuilder.iife(`var p = ${this.locator}; if (p) p.setValue(${ScriptBuilder.serializeArg(v)});`);
    await this.client.execute(script);
  }

  /**
   * This property's own dial value, excluding any `DzERCLink` contributions.
   *
   * A property driven by one or more `DzERCLink` controllers computes
   * {@link value} as `rawValue` plus every controller's contribution — a
   * `value()`/`setValue()` snapshot/restore round trip is therefore *not*
   * idempotent for such properties (the captured post-ERC total gets
   * written back into the raw slot, then the links add their contribution
   * again on top). Use `rawValue`/`setRawValue` for exact round trips.
   * Falls back to `getValue()`/`setValue()` for property types without a
   * raw accessor.
   */
  async rawValue(): Promise<unknown> {
    const script = ScriptBuilder.iife(
      "            var p = " + this.locator + ";\n" +
      "            if (!p) return null;\n" +
      '            return (typeof p.getRawValue === "function") ? p.getRawValue() : p.getValue();'
    );
    return (await this.client.execute(script)).value;
  }

  async setRawValue(v: unknown): Promise<void> {
    const serialized = ScriptBuilder.serializeArg(v);
    const script = ScriptBuilder.iife(
      "            var p = " + this.locator + ";\n" +
      "            if (!p) return;\n" +
      '            if (typeof p.setRawValue === "function") { p.setRawValue(' + serialized + "); }\n" +
      "            else { p.setValue(" + serialized + "); }"
    );
    await this.client.execute(script);
  }

  /** The display label of this property (read-only). */
  async label(): Promise<string | null> {
    const script = ScriptBuilder.iife(`var p = ${this.locator}; return p ? p.getLabel() : null;`);
    return (await this.client.execute(script)).value as string | null;
  }

  /** Minimum allowed value (read-only; `null` if not applicable). */
  async min(): Promise<number | null> {
    const script = ScriptBuilder.iife(`var p = ${this.locator}; return (p && p.getMin) ? p.getMin() : null;`);
    return (await this.client.execute(script)).value as number | null;
  }

  /** Maximum allowed value (read-only; `null` if not applicable). */
  async max(): Promise<number | null> {
    const script = ScriptBuilder.iife(`var p = ${this.locator}; return (p && p.getMax) ? p.getMax() : null;`);
    return (await this.client.execute(script)).value as number | null;
  }

  /**
   * Set a keyframe for this (numeric) property via `DzNumericProperty.setDoubleValue(tm, val)` —
   * the DazScript keyframe surface confirmed live against a running DAZ Studio instance.
   * `DzProperty.setKey()`/`.addKey()` do not exist on a live property and silently write nothing.
   */
  async setKey(time: number, value: number): Promise<void> {
    const script = ScriptBuilder.iife(
      "            var p = " + this.locator + ";\n" +
      "            if (p && p.setDoubleValue) p.setDoubleValue(" + time + ", " + value + ");"
    );
    await this.client.execute(script);
  }

  /**
   * `true` if this property has keyframe animation data (read-only).
   * Implemented as `getNumKeys() > 0` — `DzProperty.isAnimated()` does not
   * exist on a live property and raises `ScriptRuntimeError` on every access.
   */
  async isAnimated(): Promise<boolean | null> {
    const script = ScriptBuilder.iife(
      "            var p = " + this.locator + ";\n" +
      "            if (!p || !p.getNumKeys) return null;\n" +
      "            return p.getNumKeys() > 0;"
    );
    return (await this.client.execute(script)).value as boolean | null;
  }

  /** List all keyframes on this property's animation curve, ordered by time. */
  async getKeys(): Promise<Array<{ time: number; value: unknown }>> {
    const script = ScriptBuilder.iife(
      "            var p = " + this.locator + ";\n" +
      "            if (!p || !p.getNumKeys) return [];\n" +
      "            var n = p.getNumKeys();\n" +
      "            var keys = [];\n" +
      "            for (var i = 0; i < n; i++) {\n" +
      "                var t = p.getKeyTime(i);\n" +
      "                keys.push({ time: t.valueOf(), value: p.getDoubleValue(t) });\n" +
      "            }\n" +
      "            return keys;"
    );
    return ((await this.client.execute(script)).value as Array<{ time: number; value: unknown }>) ?? [];
  }

  /** Remove a single keyframe at the given time (no-op if no key exists exactly there). */
  async removeKey(time: number): Promise<void> {
    const script = ScriptBuilder.iife(
      "            var p = " + this.locator + ";\n" +
      "            if (p && p.deleteKeys) p.deleteKeys(new DzTimeRange(" + time + ", " + time + "));"
    );
    await this.client.execute(script);
  }

  /** Remove all keyframes from this property's animation curve. */
  async clearKeys(): Promise<void> {
    const script = ScriptBuilder.iife(
      "            var p = " + this.locator + ";\n" +
      "            if (p && p.deleteAllKeys) p.deleteAllKeys();"
    );
    await this.client.execute(script);
  }
}
