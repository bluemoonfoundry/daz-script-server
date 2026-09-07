import type { DazClient } from "./client.js";
import { ScriptBuilder } from "./scriptBuilder.js";

/**
 * Generic proxy for any `DzElement` subclass. Base class for every typed
 * proxy in this SDK (`DazNode`, `DazMaterial`, etc.).
 *
 * `locator` is a DazScript expression that evaluates to the underlying
 * `DzElement` instance inside DAZ Studio; every method wraps a small IIFE
 * around it via {@link ScriptBuilder.iife}.
 */
export class DazElement {
  protected readonly client: DazClient;
  protected readonly locator: string;
  private readonly cache = new Map<string, unknown>();

  constructor(client: DazClient, locator: string) {
    this.client = client;
    this.locator = locator;
  }

  /** Return the current value of a property looked up by its display label, or `null` if not found. */
  async getProperty(label: string): Promise<unknown> {
    const script = ScriptBuilder.iife(
            `            var obj = ${this.locator};
            if (!obj) return null;
            var prop = obj.findPropertyByLabel(${ScriptBuilder.escapeString(label)});
            if (!prop) return null;
            return prop.getValue();
        `
    );
    return (await this.client.execute(script)).value;
  }

  /** Set a property value by display label. `value` must be JSON-serializable. */
  async setProperty(label: string, value: unknown): Promise<void> {
    const serialized = ScriptBuilder.serializeArg(value);
    const script = ScriptBuilder.iife(`
            var obj = ${this.locator};
            if (!obj) return {"error": "not_found"};
            var prop = obj.findPropertyByLabel(${ScriptBuilder.escapeString(label)});
            if (!prop) return {"error": "property_not_found"};
            prop.setValue(${serialized});
            return {"success": true};
        `);
    await this.client.execute(script);
  }

  /**
   * Set multiple property values by display label in one call.
   * @returns `{label: true}` for labels that resolved to a real property and were written, `{label: false}` otherwise.
   */
  async setProperties(values: Record<string, unknown>): Promise<Record<string, boolean>> {
    const dataJson = JSON.stringify(values);
    const script = ScriptBuilder.iife(`
            var obj = ${this.locator};
            if (!obj) return null;
            var _data = ${dataJson};
            var _result = {};
            for (var _label in _data) {
                if (!_data.hasOwnProperty(_label)) continue;
                var prop = obj.findPropertyByLabel(_label);
                if (prop) {
                    prop.setValue(_data[_label]);
                    _result[_label] = true;
                } else {
                    _result[_label] = false;
                }
            }
            return _result;
        `);
    return ((await this.client.execute(script)).value as Record<string, boolean>) ?? {};
  }

  /** Return metadata (`label`/`name`/`type`) for every property on this element. */
  async listProperties(): Promise<Array<{ label: string; name: string; type: string }>> {
    const script = ScriptBuilder.iife(`
            var obj = ${this.locator};
            if (!obj) return null;
            var result = [];
            for (var i = 0; i < obj.getNumProperties(); i++) {
                var p = obj.getProperty(i);
                result.push({"label": p.getLabel(), "name": p.getName(), "type": p.className()});
            }
            return result;
        `);
    return ((await this.client.execute(script)).value as Array<{ label: string; name: string; type: string }>) ?? [];
  }

  /** Return every numeric property on this element as `{label: value}` in a single HTTP round-trip. */
  async numericProperties(): Promise<Record<string, unknown>> {
    const script = ScriptBuilder.iife(`
            var obj = ${this.locator};
            if (!obj) return null;
            var result = {};
            for (var i = 0; i < obj.getNumProperties(); i++) {
                var p = obj.getProperty(i);
                if (p.inherits("DzNumericProperty")) {
                    result[p.getLabel()] = p.getValue();
                }
            }
            return result;
        `);
    return ((await this.client.execute(script)).value as Record<string, unknown>) ?? {};
  }

  /** The DazScript class name of this element (e.g. `"DzFigure"`), or `null` if the locator resolves to nothing. */
  async className(): Promise<string | null> {
    const script = ScriptBuilder.iife(`var obj = ${this.locator}; return obj ? obj.className() : null;`);
    return (await this.client.execute(script)).value as string | null;
  }

  /**
   * Read and cache a set of property values in a single call.
   * Missing owner or missing property both resolve to `null` for the affected label(s).
   */
  async snapshot(fields: string[]): Promise<Record<string, unknown>> {
    const fieldsJson = JSON.stringify(fields);
    const script = ScriptBuilder.iife(`
            var obj = ${this.locator};
            if (!obj) return null;
            var _fields = ${fieldsJson};
            var _result = {};
            for (var i = 0; i < _fields.length; i++) {
                var prop = obj.findPropertyByLabel(_fields[i]);
                _result[_fields[i]] = prop ? prop.getValue() : null;
            }
            return _result;
        `);
    const values = ((await this.client.execute(script)).value as Record<string, unknown>) ?? {};
    for (const field of fields) {
      this.cache.set(field, values[field] ?? null);
    }
    const out: Record<string, unknown> = {};
    for (const field of fields) {
      out[field] = this.cache.get(field);
    }
    return out;
  }

  /** Clear the local property cache populated by {@link snapshot} so the next read fetches live data. */
  refresh(): void {
    this.cache.clear();
  }
}
