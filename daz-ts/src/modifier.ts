import { DazElement } from "./element.js";
import { ScriptBuilder } from "./scriptBuilder.js";

/**
 * Proxy for a `DzModifier` (constraint, formula, etc.) on a node, obtained
 * via `DazNode.modifiers()`/`.findModifier()`. Morph/blendshape modifiers
 * are returned as the more specific {@link DazMorph} automatically; dForce
 * simulation modifiers as {@link DazDForce}.
 */
export class DazModifier extends DazElement {
  /** User-visible display label of this modifier (read-only). */
  async modifierLabel(): Promise<string | null> {
    const script = ScriptBuilder.iife(`var m = ${this.locator}; return m ? m.getLabel() : null;`);
    return (await this.client.execute(script)).value as string | null;
  }

  /** Whether this modifier is currently active (read/write). */
  async enabled(): Promise<boolean | null> {
    const script = ScriptBuilder.iife(`var m = ${this.locator}; return m ? m.isEnabled() : null;`);
    return (await this.client.execute(script)).value as boolean | null;
  }

  async setEnabled(value: boolean): Promise<void> {
    const script = ScriptBuilder.iife(`var m = ${this.locator}; if (m) m.setEnabled(${ScriptBuilder.serializeArg(value)});`);
    await this.client.execute(script);
  }
}
