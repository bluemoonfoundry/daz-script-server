import { DazModifier } from "./modifier.js";
import { ScriptBuilder } from "./scriptBuilder.js";

/** Proxy for a `DzMorph` blendshape slider, returned by `DazNode.morphs()`/`.findModifier()`. */
export class DazMorph extends DazModifier {
  /** Current morph strength (typically 0.0-1.0, read/write). */
  async value(): Promise<number | null> {
    const script = ScriptBuilder.iife(`var m = ${this.locator}; return m ? m.getValueChannel().getValue() : null;`);
    return (await this.client.execute(script)).value as number | null;
  }

  async setValue(v: number): Promise<void> {
    const script = ScriptBuilder.iife(`var m = ${this.locator}; if (m) m.getValueChannel().setValue(${ScriptBuilder.serializeArg(v)});`);
    await this.client.execute(script);
  }

  /** Minimum allowed value for this morph channel (read-only). */
  async min(): Promise<number | null> {
    const script = ScriptBuilder.iife(`var m = ${this.locator}; return m ? m.getValueChannel().getMin() : null;`);
    return (await this.client.execute(script)).value as number | null;
  }

  /** Maximum allowed value for this morph channel (read-only). */
  async max(): Promise<number | null> {
    const script = ScriptBuilder.iife(`var m = ${this.locator}; return m ? m.getValueChannel().getMax() : null;`);
    return (await this.client.execute(script)).value as number | null;
  }
}
