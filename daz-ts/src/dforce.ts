import { DazModifier } from "./modifier.js";
import { ScriptBuilder } from "./scriptBuilder.js";

/**
 * Proxy for a `DzDForceModifier` (cloth/hair dForce simulation modifier).
 * Tunables not covered here (e.g. "Dynamics Strength") are reachable via
 * the inherited `DazElement.getProperty`/`.setProperty`.
 */
export class DazDForce extends DazModifier {
  /** Whether the simulated result is frozen onto the mesh (read/write) — DAZ Studio's equivalent of "baking" a dForce result. */
  async freezeSimulation(): Promise<boolean | null> {
    const script = ScriptBuilder.iife(`
            var m = ${this.locator};
            if (!m) return null;
            var p = m.findPropertyByLabel("Freeze Simulation");
            return p ? p.getValue() : null;
        `);
    return (await this.client.execute(script)).value as boolean | null;
  }

  async setFreezeSimulation(value: boolean): Promise<void> {
    const script = ScriptBuilder.iife(`
            var m = ${this.locator};
            if (!m) return;
            var p = m.findPropertyByLabel("Freeze Simulation");
            if (p) p.setValue(${ScriptBuilder.serializeArg(value)});
        `);
    await this.client.execute(script);
  }

  /** Bake the current simulated result onto the mesh. */
  async freeze(): Promise<void> {
    await this.setFreezeSimulation(true);
  }

  /** Release a frozen simulation so it resumes following the dForce solve. */
  async unfreeze(): Promise<void> {
    await this.setFreezeSimulation(false);
  }
}
