/**
 * Domain-level lighting rigs built on the DazLight/DazScene primitives.
 * Mirrors dazpy's `lighting.py`.
 *
 * Provides {@link applyThreePointLightSetup} for creating a conventional
 * key/fill/rim light rig around a target, either via angle/distance
 * placement or explicit world-space positions. Also provides
 * {@link applyHdriEnvironment} for image-based (HDRI/dome) lighting via
 * {@link HDRIEnvironment}, and {@link setLightColor} as a submodule-level
 * entry point for the color-setting already available via
 * `DazLight.setColor`.
 */

import * as fs from "node:fs";
import { RenderError } from "./exceptions.js";
import { lookAtEuler, resolveTarget, sphericalOffset } from "./shotGeometry.js";
import { Vec3 } from "./math3.js";
import type { DazLight } from "./light.js";
import type { DazNode } from "./node.js";
import type { DazRenderSettings } from "./render.js";
import type { DazScene } from "./scene.js";

/**
 * One light's placement and output within a rig.
 *
 * @param role Informational label, e.g. `"key"`, `"fill"`, `"rim"`.
 * @param azimuthDeg See `sphericalOffset`. Ignored if `position` is set.
 * @param elevationDeg See `sphericalOffset`. Ignored if `position` is set.
 * @param distance Distance from the target, in DAZ Studio units (cm).
 * Ignored if `position` is set.
 * @param intensity Passed to `DazLight.setIntensity`.
 * @param color `(r, g, b)` in the 0-255 range, passed to `DazLight.setColor`.
 * @param position Explicit world-space override. When set, `azimuthDeg`,
 * `elevationDeg`, and `distance` are ignored entirely.
 */
export interface LightSpec {
  role: string;
  azimuthDeg: number;
  elevationDeg: number;
  distance: number;
  intensity: number;
  color?: [number, number, number];
  position?: Vec3;
}

const DEFAULT_KEY: LightSpec = { role: "key", azimuthDeg: 45.0, elevationDeg: 30.0, distance: 150.0, intensity: 100.0 };
const DEFAULT_FILL: LightSpec = { role: "fill", azimuthDeg: -45.0, elevationDeg: 15.0, distance: 150.0, intensity: 50.0 };
const DEFAULT_RIM: LightSpec = { role: "rim", azimuthDeg: 180.0, elevationDeg: 45.0, distance: 150.0, intensity: 75.0 };

/**
 * Input spec for a three-point light rig.
 *
 * @param target The point to light, as a {@link Vec3} world position or a
 * `DazNode` (its `position()` is used).
 * @param key Key light placement/output. Defaults to a 45deg/30deg key light.
 * @param fill Fill light placement/output. Defaults to a -45deg/15deg fill light.
 * @param rim Rim light placement/output. Defaults to a 180deg/45deg rim light.
 * @param lightType Forwarded to `DazScene.createLight` for all three lights
 * -- one of `"spot"`, `"point"`, `"distant"`.
 */
export interface ThreePointLightSetup {
  target: Vec3 | DazNode;
  key?: LightSpec;
  fill?: LightSpec;
  rim?: LightSpec;
  lightType?: "spot" | "point" | "distant";
}

/** Handles to the three lights created by {@link applyThreePointLightSetup}. */
export interface ThreePointLightRig {
  key: DazLight;
  fill: DazLight;
  rim: DazLight;
}

function resolveLightPosition(target: Vec3, spec: LightSpec): Vec3 {
  if (spec.position !== undefined) {
    return spec.position;
  }
  return sphericalOffset(target, spec.azimuthDeg, spec.elevationDeg, spec.distance);
}

async function placeLight(scene: DazScene, target: Vec3, spec: LightSpec, lightType: "spot" | "point" | "distant"): Promise<DazLight> {
  const light = await scene.createLight(lightType, spec.role);
  const pos = resolveLightPosition(target, spec);
  await light.setPosition(pos.x, pos.y, pos.z);
  const [pitch, yaw, roll] = lookAtEuler(pos, target);
  await light.setRotation(pitch, yaw, roll);
  await light.setIntensity(spec.intensity);
  const [r, g, b] = spec.color ?? [255, 255, 255];
  await light.setColor(r, g, b);
  return light;
}

/**
 * Create and place a key/fill/rim light rig around `setup.target`.
 *
 * @returns A {@link ThreePointLightRig} with handles to the three created lights.
 */
export async function applyThreePointLightSetup(scene: DazScene, setup: ThreePointLightSetup): Promise<ThreePointLightRig> {
  const target = await resolveTarget(setup.target);
  const lightType = setup.lightType ?? "spot";
  const keyLight = await placeLight(scene, target, setup.key ?? DEFAULT_KEY, lightType);
  const fillLight = await placeLight(scene, target, setup.fill ?? DEFAULT_FILL, lightType);
  const rimLight = await placeLight(scene, target, setup.rim ?? DEFAULT_RIM, lightType);
  return { key: keyLight, fill: fillLight, rim: rimLight };
}

/**
 * Image-based (HDRI/dome) lighting configuration.
 *
 * @param imagePath Absolute path to an HDRI/environment map on disk. Must
 * exist -- validated by {@link applyHdriEnvironment} before any DazScript
 * call is made.
 * @param intensity Passed to the Iray "Environment Intensity" property.
 * @param rotationDeg Passed to the Iray "Dome Rotation" property.
 * @param mode One of `"dome_only"`, `"dome_and_scene"`, `"scene_only"`. Maps
 * to the DazScript "Environment Mode" enum. Procedural Sun-Sky mode is
 * intentionally not exposed here.
 * @param drawDome Whether the dome image is visible as a backdrop in the
 * viewport/render (Iray "Draw Dome"), independent of whether it lights the
 * scene.
 * @param resolution Iray "Environment Lighting Resolution" (IBL sampling
 * quality). Omit to leave DAZ Studio's current value untouched.
 */
export interface HDRIEnvironment {
  imagePath: string;
  intensity?: number;
  rotationDeg?: number;
  mode?: "dome_only" | "dome_and_scene" | "scene_only";
  drawDome?: boolean;
  resolution?: number;
}

const HDRI_MODE_LABELS: Record<string, string> = {
  dome_only: "Dome Only",
  dome_and_scene: "Dome and Scene",
  scene_only: "Scene Only",
};

/**
 * Apply image-based (HDRI/dome) lighting via `renderSettings`.
 *
 * @throws Error If `env.imagePath` does not exist on disk. Checked before
 * any DazScript call is made -- an invalid path passed to the underlying
 * `setMap()` call can hang or crash DAZ Studio via a blocking
 * file-not-found dialog. Also thrown if `env.mode` is not one of
 * `"dome_only"`, `"dome_and_scene"`, `"scene_only"`.
 * @throws RenderError If a post-apply readback of "Environment Intensity"
 * doesn't match `env.intensity`. All of this module's environment writes go
 * through `DazRenderSettings`'s environment-holder methods, which assume
 * `getRenderElementObjects()[3]` is always the Environment property holder
 * -- confirmed on one live DAZ Studio 4.x instance only. If that index is
 * wrong on a different DAZ Studio version, every write above silently
 * no-ops with no exception, so this readback is what actually catches it.
 */
export async function applyHdriEnvironment(renderSettings: DazRenderSettings, env: HDRIEnvironment): Promise<void> {
  if (!fs.existsSync(env.imagePath) || !fs.statSync(env.imagePath).isFile()) {
    throw new Error(`HDRI/environment map not found: ${env.imagePath}`);
  }
  const mode = env.mode ?? "dome_only";
  if (!(mode in HDRI_MODE_LABELS)) {
    throw new Error(`Invalid HDRIEnvironment.mode ${JSON.stringify(mode)}; must be one of ${JSON.stringify(Object.keys(HDRI_MODE_LABELS).sort())}`);
  }
  const intensity = env.intensity ?? 1.0;
  await renderSettings.setEnvironmentMap(env.imagePath);
  await renderSettings.setEnvironmentProperty("Environment Intensity", intensity);
  await renderSettings.setEnvironmentProperty("Dome Rotation", env.rotationDeg ?? 0.0);
  await renderSettings.setEnvironmentPropertyFromString("Environment Mode", HDRI_MODE_LABELS[mode]);
  await renderSettings.setEnvironmentProperty("Draw Dome", env.drawDome ?? false);
  if (env.resolution !== undefined) {
    await renderSettings.setEnvironmentProperty("Environment Lighting Resolution", env.resolution);
  }

  const readback = await renderSettings.getEnvironmentProperty("Environment Intensity");
  if (readback === null || readback === undefined || Math.abs(Number(readback) - intensity) > 1e-6) {
    throw new RenderError(
      "HDRI environment apply failed verification: 'Environment Intensity' " +
        `readback (${JSON.stringify(readback)}) does not match the requested value ` +
        `(${JSON.stringify(intensity)}). The environment property holder ` +
        "(getRenderElementObjects()[3]) may be unavailable or at a " +
        "different index on this DAZ Studio version/build -- the HDRI " +
        "was likely never applied.",
    );
  }
}

/**
 * Set `light`'s diffuse color.
 *
 * A thin `lighting.ts`-level entry point for `DazLight.setColor`, so
 * color-setting is discoverable alongside {@link applyThreePointLightSetup}
 * and {@link applyHdriEnvironment} without needing to know the lower-level
 * `DazLight` primitive lives in a different module.
 */
export async function setLightColor(light: DazLight, r: number, g: number, b: number): Promise<void> {
  await light.setColor(r, g, b);
}
