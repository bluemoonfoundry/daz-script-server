/**
 * Domain-level Iray Uber Base material setup built on the DazMaterial
 * primitive. Mirrors dazpy's `materials.py`.
 *
 * `DzMaterial` has no dedicated Iray property-holder indirection the way
 * `DzRenderMgr.getActiveRenderer().getPropertyHolder()` does for render
 * settings -- it inherits `findProperty`/`findPropertyByLabel` directly from
 * `DzElement`, and Iray Uber Base channels (Base Color, Metallic Weight,
 * Glossy Roughness, ...) are ordinary named properties on the material
 * itself. Texture-slot assignment goes through the *property* object's
 * `setMap(path)` (defined on `DzNumericProperty`), not through the
 * material. The channel labels in {@link CHANNEL_LABELS} are confirmed
 * against a live DAZ Studio instance -- see
 * `docs/superpowers/specs/2026-08-15-dazpy-materials-design.md` for details.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { MaterialError } from "./exceptions.js";
import { ScriptBuilder } from "./scriptBuilder.js";
import type { DazMaterial } from "./material.js";

// Iray Uber Base shader channel display labels -- confirmed against a live
// DAZ Studio instance (a prop's default Iray Uber Base material, and a
// Genesis 9 figure's eye-moisture/tear materials, both of which use the
// classic Uber Base shader rather than the PBRSkin variant). Note the label
// ("Metallicity", "Base Bump") can differ from the underlying property name
// ("Metallic Weight", "Bump Strength") -- findPropertyByLabel() matches on
// the former.
const CHANNEL_LABELS: Record<string, string> = {
  base_color: "Base Color",
  metallic_weight: "Metallicity",
  roughness: "Glossy Roughness",
  glossy_reflectivity: "Glossy Reflectivity",
  cutout_opacity: "Cutout Opacity",
  bump_strength: "Base Bump",
  top_coat_weight: "Top Coat Weight",
  normal: "Normal Map",
  bump: "Base Bump",
  diffuse: "Base Color",
  metallic: "Metallicity",
};

function channelLabel(channel: string): string {
  return CHANNEL_LABELS[channel] ?? channel;
}

/**
 * One texture-slot assignment for an Iray material channel.
 *
 * @param channel A key into the known Iray channel labels (e.g.
 * `"base_color"`, `"normal"`, `"bump"`, `"metallic"`, `"roughness"`,
 * `"cutout_opacity"`) or an arbitrary DazScript property display label not
 * in that table.
 * @param filePath Absolute path to an image file on disk. Must exist --
 * validated by {@link applyTextureMap} before any DazScript call is made,
 * since an invalid path passed to `setMap()` can hang or crash DAZ Studio
 * via a blocking file-not-found dialog.
 */
export interface TextureMap {
  channel: string;
  filePath: string;
}

/**
 * Generic named Iray surface-channel override, for channels not covered by
 * {@link IrayMaterial}'s typed fields.
 *
 * @param label The DazScript property display label (`getLabel()`).
 * @param value The value to set. Must be JSON-serialisable.
 */
export interface SurfaceProperty {
  label: string;
  value: unknown;
}

/**
 * Declarative Iray Uber Base material spec.
 *
 * Targets the classic Iray Uber Base shader specifically. Figures using the
 * PBRSkin shader variant (e.g. default Genesis 9 skin materials, which have
 * no `Cutout Opacity`/`Glossy Roughness` channels at all) need different
 * channel labels -- use {@link SurfaceProperty}/{@link setSurfaceProperty}
 * with PBRSkin's own labels instead.
 */
export interface IrayMaterial {
  /** `(r, g, b)` in the 0-255 range. */
  baseColor?: [number, number, number];
  /** 0.0-1.0. */
  metallicWeight?: number;
  /** 0.0-1.0 (Glossy Roughness). */
  roughness?: number;
  /** 0.0-1.0. */
  glossyReflectivity?: number;
  /** 0.0 (fully cut out) - 1.0 (opaque). */
  cutoutOpacity?: number;
  /** Bump map strength multiplier. */
  bumpStrength?: number;
  /** 0.0-1.0. */
  topCoatWeight?: number;
  /** Texture-slot assignments, applied after the typed fields above. */
  textures?: TextureMap[];
  /** Ad hoc named-channel overrides, applied last so they can supersede any typed field or texture set in the same call. */
  properties?: SurfaceProperty[];
}

function setChannelValue(material: DazMaterial, label: string, value: unknown): Promise<void> {
  return (async () => {
    const serialized = ScriptBuilder.serializeArg(value);
    const script = ScriptBuilder.iife(`
        var m = ${material.getLocator()};
        if (!m) return {"error": "material_not_found"};
        var p = m.findPropertyByLabel(${ScriptBuilder.escapeString(label)});
        if (!p) return {"error": "property_not_found"};
        p.setValue(${serialized});
        return {"success": true};
    `);
    const result = (await material.getClient().execute(script)).value as { success?: boolean; error?: string } | null;
    if (!result || result.success !== true) {
      const error = result?.error ?? "unknown_error";
      throw new MaterialError(`Failed to set Iray channel ${JSON.stringify(label)}: ${error}`);
    }
  })();
}

async function getChannelValue(material: DazMaterial, label: string): Promise<unknown> {
  const script = ScriptBuilder.iife(`
        var m = ${material.getLocator()};
        if (!m) return {"error": "material_not_found"};
        var p = m.findPropertyByLabel(${ScriptBuilder.escapeString(label)});
        if (!p) return {"error": "property_not_found"};
        return {"success": true, "value": p.getValue()};
    `);
  const result = (await material.getClient().execute(script)).value as
    | { success?: boolean; error?: string; value?: unknown }
    | null;
  if (!result || result.success !== true) {
    const error = result?.error ?? "unknown_error";
    throw new MaterialError(`Failed to read Iray channel ${JSON.stringify(label)}: ${error}`);
  }
  return result.value;
}

function validateTexturePath(filePath: string): void {
  if (!path.isAbsolute(filePath)) {
    throw new Error(`Texture map path must be absolute: ${filePath}`);
  }
  if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
    throw new Error(`Texture map not found: ${filePath}`);
  }
}

async function setChannelMap(material: DazMaterial, label: string, filePath: string): Promise<void> {
  validateTexturePath(filePath);
  const script = ScriptBuilder.iife(`
        var m = ${material.getLocator()};
        if (!m) return {"error": "material_not_found"};
        var p = m.findPropertyByLabel(${ScriptBuilder.escapeString(label)});
        if (!p) return {"error": "property_not_found"};
        p.setMap(${ScriptBuilder.escapeString(filePath)});
        return {"success": true};
    `);
  const result = (await material.getClient().execute(script)).value as { success?: boolean; error?: string } | null;
  if (!result || result.success !== true) {
    const error = result?.error ?? "unknown_error";
    throw new MaterialError(`Failed to set texture map on channel ${JSON.stringify(label)}: ${error}`);
  }
}

/**
 * Assign `texture` to `material`'s corresponding Iray channel.
 *
 * @throws Error If `texture.filePath` is not an absolute path, or does not
 * exist on disk. Checked before any DazScript call is made.
 * @throws MaterialError If the material or the resolved channel property
 * cannot be found on the live material.
 */
export async function applyTextureMap(material: DazMaterial, texture: TextureMap): Promise<void> {
  await setChannelMap(material, channelLabel(texture.channel), texture.filePath);
}

/**
 * Return the current value of the named Iray surface property.
 *
 * @throws MaterialError If the material or property cannot be found.
 */
export async function getSurfaceProperty(material: DazMaterial, label: string): Promise<unknown> {
  return getChannelValue(material, label);
}

/**
 * Set a single named Iray surface property.
 *
 * @throws MaterialError If the material or property cannot be found.
 */
export async function setSurfaceProperty(material: DazMaterial, prop: SurfaceProperty): Promise<void> {
  await setChannelValue(material, prop.label, prop.value);
}

const TYPED_FIELDS: Array<[keyof IrayMaterial, string]> = [
  ["baseColor", "base_color"],
  ["metallicWeight", "metallic_weight"],
  ["roughness", "roughness"],
  ["glossyReflectivity", "glossy_reflectivity"],
  ["cutoutOpacity", "cutout_opacity"],
  ["bumpStrength", "bump_strength"],
  ["topCoatWeight", "top_coat_weight"],
];

/**
 * Apply `spec` to `material` in typed-fields -> textures -> properties order.
 *
 * `undefined`-valued typed fields are skipped. `spec.properties` is applied
 * last, so it can supersede any typed field or texture set earlier in the
 * same call.
 *
 * @throws Error If any `spec.textures[*].filePath` is not absolute, or does
 * not exist on disk. All texture paths are validated before any DazScript
 * call is made, for the same reason as {@link applyTextureMap}.
 * @throws MaterialError If the material or a resolved channel property
 * cannot be found on the live material.
 */
export async function applyIrayMaterial(material: DazMaterial, spec: IrayMaterial): Promise<void> {
  for (const texture of spec.textures ?? []) {
    validateTexturePath(texture.filePath);
  }

  for (const [field, channel] of TYPED_FIELDS) {
    const value = spec[field];
    if (value !== undefined) {
      await setChannelValue(material, channelLabel(channel), value);
    }
  }

  for (const texture of spec.textures ?? []) {
    await setChannelMap(material, channelLabel(texture.channel), texture.filePath);
  }

  for (const prop of spec.properties ?? []) {
    await setChannelValue(material, prop.label, prop.value);
  }
}
