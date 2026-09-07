import { DazElement } from "./element.js";
import { ScriptBuilder } from "./scriptBuilder.js";

/** Proxy for a `DzMaterial` surface, obtained via `DazNode.materials()`/`.findMaterial()`. */
export class DazMaterial extends DazElement {
  async materialName(): Promise<string | null> {
    const script = ScriptBuilder.iife(`var m = ${this.locator}; return m ? m.getName() : null;`);
    return (await this.client.execute(script)).value as string | null;
  }

  /** Diffuse colour as `{r, g, b}` (0-255, read/write via {@link setDiffuseColor}). */
  async diffuseColor(): Promise<{ r: number; g: number; b: number } | null> {
    const script = ScriptBuilder.iife(
      "            var m = " + this.locator + ";\n" +
      "            if (!m) return null;\n" +
      "            var c = m.getDiffuseColor();\n" +
      "            return {r: c.red, g: c.green, b: c.blue};\n" +
      "        "
    );
    return (await this.client.execute(script)).value as { r: number; g: number; b: number } | null;
  }

  async setDiffuseColor(value: { r: number; g: number; b: number } | [number, number, number]): Promise<void> {
    const [r, g, b] = Array.isArray(value) ? value : [value.r, value.g, value.b];
    const script = ScriptBuilder.iife(
      "            var m = " + this.locator + ";\n" +
      "            if (!m) return;\n" +
      "            var c = new Color(" + ScriptBuilder.serializeArg(Math.trunc(r)) + ", " + ScriptBuilder.serializeArg(Math.trunc(g)) + ", " + ScriptBuilder.serializeArg(Math.trunc(b)) + ");\n" +
      "            m.setDiffuseColor(c);\n" +
      "        "
    );
    await this.client.execute(script);
  }

  /** Base opacity/transparency (0.0 transparent - 1.0 opaque, read/write). */
  async opacity(): Promise<number | null> {
    const script = ScriptBuilder.iife(`var m = ${this.locator}; return m ? m.getBaseOpacity() : null;`);
    return (await this.client.execute(script)).value as number | null;
  }

  async setOpacity(value: number): Promise<void> {
    const script = ScriptBuilder.iife(`var m = ${this.locator}; if (m) m.setBaseOpacity(${ScriptBuilder.serializeArg(value)});`);
    await this.client.execute(script);
  }

  /** File path of the diffuse colour texture, or `null`. */
  async colorMap(): Promise<string | null> {
    const script = ScriptBuilder.iife(
      "            var m = " + this.locator + ";\n" +
      "            if (!m) return null;\n" +
      "            var t = m.getColorMap();\n" +
      "            return t ? t.getFilename() : null;\n" +
      "        "
    );
    return (await this.client.execute(script)).value as string | null;
  }

  async isSmoothingOn(): Promise<boolean | null> {
    const script = ScriptBuilder.iife(`var m = ${this.locator}; return m ? m.isSmoothingOn() : null;`);
    return (await this.client.execute(script)).value as boolean | null;
  }

  /** Normal smoothing angle in degrees (read/write). */
  async smoothingAngle(): Promise<number | null> {
    const script = ScriptBuilder.iife(`var m = ${this.locator}; return m ? m.getSmoothingAngle() : null;`);
    return (await this.client.execute(script)).value as number | null;
  }

  async setSmoothingAngle(value: number): Promise<void> {
    const script = ScriptBuilder.iife(`var m = ${this.locator}; if (m) m.setSmoothingAngle(${ScriptBuilder.serializeArg(value)});`);
    await this.client.execute(script);
  }

  /** `true` if the material is fully opaque (opacity == 1.0). */
  async isOpaque(): Promise<boolean | null> {
    const script = ScriptBuilder.iife(`var m = ${this.locator}; return m ? m.isOpaque() : null;`);
    return (await this.client.execute(script)).value as boolean | null;
  }
}
