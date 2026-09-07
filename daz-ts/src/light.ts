import { DazNode } from "./node.js";
import { ScriptBuilder } from "./scriptBuilder.js";

/** Proxy for a `DzLight` node. Extends `DazNode` with light-specific properties. */
export class DazLight extends DazNode {
  async intensity(): Promise<number | null> {
    return (await this.getProperty("Intensity")) as number | null;
  }

  async setIntensity(value: number): Promise<void> {
    await this.setProperty("Intensity", value);
  }

  /** Diffuse colour as `{r, g, b}` (0-255, read-only; use {@link setColor} to change). */
  async color(): Promise<{ r: number; g: number; b: number } | null> {
    const script = this.nodeScript("            var c = _node.getDiffuseColor();\n            return {r: c.red, g: c.green, b: c.blue};\n        ");
    return (await this.client.execute(script)).value as { r: number; g: number; b: number } | null;
  }

  async setColor(r: number, g: number, b: number): Promise<void> {
    const script = this.nodeScript(
      `var p = _node.findPropertyByLabel('Color'); if (p) p.setColorValue(new Color(${ScriptBuilder.serializeArg(Math.trunc(r))}, ${ScriptBuilder.serializeArg(Math.trunc(g))}, ${ScriptBuilder.serializeArg(Math.trunc(b))}));`
    );
    await this.client.execute(script);
  }

  async shadowType(): Promise<string | null> {
    return (await this.getProperty("Shadow Type")) as string | null;
  }

  async illumination(): Promise<string | null> {
    return (await this.getProperty("Illumination")) as string | null;
  }

  async isOn(): Promise<boolean> {
    return Boolean((await this.client.execute(this.nodeScript("return _node.isOn();"))).value);
  }

  async isDirectional(): Promise<boolean> {
    return Boolean((await this.client.execute(this.nodeScript("return _node.isDirectional();"))).value);
  }

  async isAreaLight(): Promise<boolean> {
    return Boolean((await this.client.execute(this.nodeScript("return _node.isAreaLight();"))).value);
  }

  /** World-space direction vector `{x, y, z}`, or `null` when the light is not directional. */
  async direction(): Promise<{ x: number; y: number; z: number } | null> {
    const script = this.nodeScript(
      "if (!_node.isDirectional()) return null; var d = _node.getWSDirection(); return {x: d.x, y: d.y, z: d.z};"
    );
    return (await this.client.execute(script)).value as { x: number; y: number; z: number } | null;
  }
}
