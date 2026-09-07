import * as fs from "node:fs";
import * as path from "node:path";
import type { DazClient } from "./client.js";
import { DazClient as DazClientImpl } from "./client.js";
import { RenderError } from "./exceptions.js";
import { ScriptBuilder } from "./scriptBuilder.js";

// Access path: App.getRenderMgr() -> DzRenderMgr
// Render options: mgr.getRenderOptions() -> DzRenderOptions
// imageSize is a QSize value type -- read via .width/.height, write back by
// calling setWidth/setHeight on the copy then reassigning opts.imageSize.
//
// Iray-specific quality/samples settings (Max Samples, Max Time, Rendering
// Quality, ...) are not exposed on DzRenderOptions or DzIrayRenderer directly
// -- they live on the active renderer's property holder:
// mgr.getActiveRenderer().getPropertyHolder().findProperty("Max Samples").
// Confirmed against a live DAZ Studio instance; property names match the
// labels shown in the Render Settings pane's Advanced tab.

const RENDER_MGR = "App.getRenderMgr()";

/**
 * Mirrors the engineMap in DzScriptServerPane.cpp's render script builder --
 * keep in sync. 3Delight is no longer supported by DAZ Studio and excluded.
 */
const ENGINE_CLASS_TO_NAME: Record<string, string> = {
  DzIrayRenderer: "iray",
  DzFilamentRenderer: "filament",
};
const ENGINE_NAME_TO_CLASS: Record<string, string> = Object.fromEntries(
  Object.entries(ENGINE_CLASS_TO_NAME).map(([k, v]) => [v, k]),
);

/** The two non-pluggable `DzRenderOptions.renderType` modes (see {@link DazRenderSettings.activeEngine} for why these are distinct from the `DzRenderer` plugin lookup). */
const NON_SOFTWARE_ENGINES = new Set(["viewport", "multi_pass_opengl"]);

const ENGINE_SELECTOR_SCHEMA = 1;
const ENGINE_MUTATION_SCHEMA = 1;
const ENGINE_SELECTOR_METHOD = "render_settings_engine_selector";
const RENDER_TYPE_NAMES: Record<number, string> = { 0: "ScreenShot", 1: "HardwareAssisted", 2: "Software" };

interface EngineReadbackFacts {
  read_schema?: number;
  ok?: boolean;
  reason?: string | null;
  render_type?: number | null;
  active_renderer_class?: string | null;
  active_renderer_name?: string | null;
}

function engineStateUnavailable(
  reason: string,
  opts: {
    renderType?: number | null;
    activeRendererClass?: string | null;
    activeRendererName?: string | null;
    factsObserved?: boolean;
  } = {},
): Record<string, unknown> {
  const { renderType = null, activeRendererClass = null, activeRendererName = null, factsObserved = false } = opts;
  const provenanceKind = factsObserved ? "live_readback" : "unavailable";
  return {
    selector_schema: ENGINE_SELECTOR_SCHEMA,
    status: "unavailable",
    engine: null,
    method: ENGINE_SELECTOR_METHOD,
    reason,
    render_type: {
      raw: renderType,
      name: renderType !== null ? (RENDER_TYPE_NAMES[renderType] ?? null) : null,
      provenance: { kind: provenanceKind, source: "DzRenderOptions.renderType" },
    },
    active_renderer: {
      class_name: activeRendererClass,
      name: activeRendererName,
      provenance: { kind: provenanceKind, source: "DzRenderMgr.getActiveRenderer" },
    },
  };
}

/** Normalize one bounded live read without inferring from renderer identity alone. */
function normalizeEngineReadback(raw: unknown): Record<string, unknown> {
  if (typeof raw !== "object" || raw === null || (raw as EngineReadbackFacts).read_schema !== 1) {
    return engineStateUnavailable("malformed_readback");
  }
  const facts = raw as EngineReadbackFacts;
  if (facts.ok !== true) {
    let reason = facts.reason;
    if (reason !== "render_manager_unavailable" && reason !== "render_options_unavailable" && reason !== "probe_failed") {
      reason = "probe_failed";
    }
    return engineStateUnavailable(reason);
  }

  const renderType = facts.render_type;
  const rendererClass = facts.active_renderer_class;
  const rendererName = facts.active_renderer_name;
  if (
    typeof renderType !== "number" ||
    (rendererClass !== null && rendererClass !== undefined && typeof rendererClass !== "string") ||
    (rendererName !== null && rendererName !== undefined && typeof rendererName !== "string")
  ) {
    return engineStateUnavailable("malformed_readback");
  }

  const state = engineStateUnavailable("unknown_render_type", {
    renderType,
    activeRendererClass: rendererClass ?? null,
    activeRendererName: rendererName ?? null,
    factsObserved: true,
  });
  if (renderType === 0 || renderType === 1) {
    Object.assign(state, { status: "verified_non_iray", engine: "viewport_gl", reason: "non_iray_engine" });
  } else if (renderType === 2 && rendererClass === "DzIrayRenderer") {
    Object.assign(state, { status: "verified_iray", engine: "iray", reason: null });
  } else if (renderType === 2 && rendererClass !== null && rendererClass !== undefined) {
    Object.assign(state, { status: "verified_non_iray", engine: "other_non_iray", reason: "non_iray_engine" });
  } else if (renderType === 2) {
    (state as Record<string, unknown>).reason = "active_renderer_unavailable";
  }
  return state;
}

const QUALITY_PRESETS: Record<string, { maxSamples: number; maxTime: number; qualityEnable: boolean; quality?: number }> = {
  draft: { maxSamples: 100, maxTime: 300, qualityEnable: false },
  preview: { maxSamples: 500, maxTime: 900, qualityEnable: true, quality: 2.0 },
  good: { maxSamples: 1500, maxTime: 3600, qualityEnable: true, quality: 1.0 },
  final: { maxSamples: 5000, maxTime: 7200, qualityEnable: true, quality: 1.0 },
};

// Iray Canvases (Render Settings > Advanced > Canvases) are not exposed on
// DzIrayRenderer/DzRenderOptions at all -- they live on a separate
// DzIrayPropertyHolder returned as element [1] of
// App.getRenderMgr().getRenderElementObjects(), confirmed against a live
// DAZ Studio instance:
//
//   holder.renderToCanvases            -- bool, master on/off for all canvas output
//   holder.getNumCanvasDefinitions()    -- int
//   holder.getCanvasDefinition(i)       -- canvas object
//   holder.findCanvasDefinition(name, createIfMissing) -- canvas object or null
//   holder.removeCanvasDefinition(canvas)
//
//   canvas.name                        -- e.g. "Canvas1", auto-generated but editable
//   canvas.canvasType                  -- int enum (Beauty, Normal, Depth, MaterialID, ...)
//   canvas.canvasTypeToString(int) / canvasTypeFromString(string)
//
// canvas.processingDisabled exists but does NOT gate render output (confirmed
// it still renders when true) -- do not rely on it for per-canvas enable/disable.
//
// Each enabled canvas is written to
//   <output_dir>/<basename>_canvases/<basename>-<canvasName>-<canvasType>.exr
// alongside the main render output (confirmed empirically; not queryable via
// script, so canvasOutputPaths() below derives it from this convention).
//
// UI widgets in the Render Settings pane do not repaint after a scripted
// property write -- MainWindow.getPaneMgr().findPane("DzRenderSettingsPane")
// .refresh() must be called after any scripted change for the UI to reflect
// it. Every write in this module does so as standard practice.

/** An Iray Canvas definition (extra render pass alongside the beauty image). */
export interface Canvas {
  name: string;
  canvasType: string;
  index: number;
}

/**
 * Result of a {@link DazRenderSettings.render} call.
 *
 * Unlike dazpy's `RenderOutcome` (which overrides `__bool__` so old
 * bool-returning callers keep working), TS callers must check `.success`
 * explicitly -- there is no operator-overload equivalent.
 */
export interface RenderOutcome {
  success: boolean;
  outputPath: string | null;
}

/** Options for {@link DazRenderSettings.render}. `cameraName` and `cameraLabel` are mutually exclusive. */
export interface RenderOptions {
  /**
   * Internal name of the camera node to render from. Internal names are not
   * guaranteed unique -- e.g. duplicating a camera node in the Scene panel
   * copies its internal name too, only the display label is forced unique --
   * so this can silently resolve to the wrong node when duplicates exist.
   * Prefer `cameraLabel` unless you specifically need name-based lookup.
   */
  cameraName?: string;
  /**
   * User-visible label of the camera node to render from (the same value
   * shown in the Scene panel, resolved via `Scene.findCameraByLabel()`).
   * Labels are kept unique by DAZ Studio even when internal names collide,
   * so this is the more reliable way to target a specific camera. When
   * neither `cameraName` nor `cameraLabel` is given, the active viewport
   * camera is used.
   */
  cameraLabel?: string;
}

/**
 * Live control of DAZ Studio's Render Settings pane: engine selection,
 * resolution, gamma, Iray quality presets, Iray Canvases, and a
 * `render()` helper that drives `DzRenderMgr.doRender()` synchronously and
 * waits for its `renderFinished(bool)` signal.
 *
 * This talks directly to the DazScript render manager (`App.getRenderMgr()`)
 * via {@link DazClient.execute}, distinct from the HTTP `/render` job-queue
 * endpoints exposed on {@link DazClient} itself (`renderSubmit`,
 * `renderBatchSubmit`, ...) and the {@link render}/{@link renderVariants}
 * helpers in `renderApi.ts` that submit to that queue.
 */
export class DazRenderSettings {
  private readonly client: DazClient;

  constructor(client?: DazClient) {
    this.client = client ?? new DazClientImpl();
  }

  private irayPropertyHolderExpr(): string {
    return `${RENDER_MGR}.getActiveRenderer().getPropertyHolder()`;
  }

  private async getIrayProperty(name: string): Promise<unknown> {
    const script = ScriptBuilder.iife(`
            var holder = ${this.irayPropertyHolderExpr()};
            if (!holder) return null;
            var p = holder.findProperty(${ScriptBuilder.escapeString(name)});
            return p ? p.getValue() : null;
        `);
    return (await this.client.execute(script)).value;
  }

  private async setIrayProperty(name: string, value: unknown): Promise<void> {
    const script = ScriptBuilder.iife(`
            var holder = ${this.irayPropertyHolderExpr()};
            if (!holder) return;
            var p = holder.findProperty(${ScriptBuilder.escapeString(name)});
            if (p) p.setValue(${ScriptBuilder.serializeArg(value)});
        `);
    await this.client.execute(script);
  }

  /**
   * Index 3 of the 4 fixed render element groups (General Render, Iray,
   * Tonemapper, Environment) -- confirmed against a live instance alongside
   * index 1 (see {@link irayRenderOptionsHolderExpr}).
   */
  private environmentHolderExpr(): string {
    return `${RENDER_MGR}.getRenderElementObjects()[3]`;
  }

  /** Read an Environment-holder property by label (e.g. `"Environment Intensity"`, `"Dome Rotation"`). Primarily for domain-helper use (see `lighting.ts`). */
  async getEnvironmentProperty(name: string): Promise<unknown> {
    const script = ScriptBuilder.iife(`
            var holder = ${this.environmentHolderExpr()};
            if (!holder) return null;
            var p = holder.findProperty(${ScriptBuilder.escapeString(name)});
            return p ? p.getValue() : null;
        `);
    return (await this.client.execute(script)).value;
  }

  /** Set an Environment-holder property by label. Primarily for domain-helper use (see `lighting.ts`). */
  async setEnvironmentProperty(name: string, value: unknown): Promise<void> {
    const script = ScriptBuilder.iife(`
            var holder = ${this.environmentHolderExpr()};
            if (!holder) return;
            var p = holder.findProperty(${ScriptBuilder.escapeString(name)});
            if (p) p.setValue(${ScriptBuilder.serializeArg(value)});
        `);
    await this.client.execute(script);
  }

  /** Set an Environment-holder property from a string value via `setValueFromString()`. Primarily for domain-helper use. */
  async setEnvironmentPropertyFromString(name: string, value: string): Promise<void> {
    const script = ScriptBuilder.iife(`
            var holder = ${this.environmentHolderExpr()};
            if (!holder) return;
            var p = holder.findProperty(${ScriptBuilder.escapeString(name)});
            if (p) p.setValueFromString(${ScriptBuilder.escapeString(value)});
        `);
    await this.client.execute(script);
  }

  /**
   * Set the "Environment Map" (HDRI) path, validating it against the local
   * filesystem before sending `setMap()`.
   *
   * Requires an absolute path: a local existence check against a relative
   * path resolves against this process's cwd, not DAZ Studio's, so a
   * relative path could pass this check yet still resolve to a different
   * (or unresolvable) file in DAZ Studio -- reproducing the blocking
   * file-not-found dialog this validation exists to prevent (see
   * `feedback_dazscript_blocking_dialogs` in project memory). The existence
   * check validates against the local/client-side filesystem, which is
   * correct when DAZ Studio and this client are co-located but will
   * misbehave against a remote DAZ Studio server.
   */
  async setEnvironmentMap(mapPath: string): Promise<void> {
    if (!path.isAbsolute(mapPath)) {
      throw new Error(`HDRI/environment map path must be absolute: ${mapPath}`);
    }
    if (!fs.existsSync(mapPath) || !fs.statSync(mapPath).isFile()) {
      throw new Error(`HDRI/environment map not found: ${mapPath}`);
    }
    const script = ScriptBuilder.iife(`
            var holder = ${this.environmentHolderExpr()};
            if (!holder) return;
            var p = holder.findProperty(${ScriptBuilder.escapeString("Environment Map")});
            if (p) p.setMap(${ScriptBuilder.escapeString(mapPath)});
        `);
    await this.client.execute(script);
  }

  /**
   * Canvas definitions live on this holder, not on
   * `getActiveRenderer().getPropertyHolder()` -- confirmed against a live
   * instance; index 1 is "NVIDIA Iray Render Options" among the 4 fixed
   * render element groups (General Render, Iray, Tonemapper, Environment).
   */
  private irayRenderOptionsHolderExpr(): string {
    return `${RENDER_MGR}.getRenderElementObjects()[1]`;
  }

  private static refreshRenderSettingsPaneScript(): string {
    return 'var _pane = MainWindow.getPaneMgr().findPane("DzRenderSettingsPane");if (_pane) _pane.refresh();';
  }

  /** `true` if the render manager is accessible. */
  async isAvailable(): Promise<boolean> {
    const script = ScriptBuilder.iife(`
            var mgr = ${RENDER_MGR};
            return (mgr !== null && mgr !== undefined);
        `);
    return Boolean((await this.client.execute(script)).value);
  }

  /** `true` if a render is currently in progress. */
  async isRendering(): Promise<boolean> {
    const script = ScriptBuilder.iife(`
            var mgr = ${RENDER_MGR};
            if (!mgr) return false;
            return mgr.isRendering();
        `);
    return Boolean((await this.client.execute(script)).value);
  }

  /** DazScript body returning bounded raw selector and renderer facts. */
  private static engineReadbackBody(): string {
    return `
            function _readEngineFacts() {
                try {
                    var mgr = App.getRenderMgr();
                    if (!mgr) return {
                        read_schema: 1, ok: false,
                        reason: "render_manager_unavailable",
                        render_type: null,
                        active_renderer_class: null,
                        active_renderer_name: null
                    };
                    var opts = mgr.getRenderOptions();
                    if (!opts) return {
                        read_schema: 1, ok: false,
                        reason: "render_options_unavailable",
                        render_type: null,
                        active_renderer_class: null,
                        active_renderer_name: null
                    };
                    var renderer = mgr.getActiveRenderer();
                    return {
                        read_schema: 1, ok: true, reason: null,
                        render_type: Number(opts.renderType),
                        active_renderer_class: renderer ? String(renderer.className()) : null,
                        active_renderer_name: renderer ? String(renderer.getName()) : null
                    };
                } catch (_readError) {
                    return {
                        read_schema: 1, ok: false, reason: "probe_failed",
                        render_type: null,
                        active_renderer_class: null,
                        active_renderer_name: null
                    };
                }
            }
        `;
  }

  /**
   * Return truthful Render Settings engine facts and a normalized verdict.
   *
   * `DzRenderOptions.renderType` is the effective render-operation selector.
   * The active renderer class/name is returned as a separate fact and only
   * participates in normalization when `renderType` is `Software`. In
   * particular, an Iray active-renderer name cannot turn a ScreenShot or
   * HardwareAssisted operation into an Iray verdict.
   */
  async renderEngineState(): Promise<Record<string, unknown>> {
    const script = ScriptBuilder.iife(`${DazRenderSettings.engineReadbackBody()}\nreturn _readEngineFacts();`);
    return normalizeEngineReadback((await this.client.execute(script)).value);
  }

  /**
   * Persist `"iray"` or `"viewport"` and require exact live readback.
   *
   * This is an explicit persistent setter, not a transactional render
   * helper. It calls `applyChanges()` so the selected render operation is
   * written via DAZ's settings manager. Any lookup, mutation, apply, or
   * readback failure throws {@link RenderError}; unknown engine names never
   * silently continue.
   */
  async setRenderEngine(engine: string): Promise<Record<string, unknown>> {
    const requested = engine.trim().toLowerCase();
    if (requested !== "iray" && requested !== "viewport") {
      throw new Error(`Unknown render engine ${JSON.stringify(engine)}; expected 'iray' or 'viewport'`);
    }
    const requestedJs = ScriptBuilder.escapeString(requested);

    const script = ScriptBuilder.iife(`
            ${DazRenderSettings.engineReadbackBody()}
                var requested = ${requestedJs};
                var mgr = App.getRenderMgr();
                if (!mgr) return {
                    mutation_schema: 1, ok: false,
                    requested_engine: requested, persisted: false,
                    reason: "render_manager_unavailable", readback: _readEngineFacts()
                };
                var opts = mgr.getRenderOptions();
                if (!opts) return {
                    mutation_schema: 1, ok: false,
                    requested_engine: requested, persisted: false,
                    reason: "render_options_unavailable", readback: _readEngineFacts()
                };
                try {
                    if (requested === "iray") {
                        var iray = mgr.findRenderer("DzIrayRenderer");
                        if (!iray) return {
                            mutation_schema: 1, ok: false,
                            requested_engine: requested, persisted: false,
                            reason: "iray_renderer_unavailable", readback: _readEngineFacts()
                        };
                        mgr.setActiveRenderer(iray);
                        opts.renderType = opts.Software;
                    } else {
                        opts.renderType = opts.ScreenShot;
                    }
                    opts.applyChanges();
                } catch (_mutationError) {
                    return {
                        mutation_schema: 1, ok: false,
                        requested_engine: requested, persisted: false,
                        reason: "mutation_failed", readback: _readEngineFacts()
                    };
                }
                var readback = _readEngineFacts();
                var matches = readback.ok && (
                    (requested === "iray"
                        && readback.render_type === Number(opts.Software)
                        && readback.active_renderer_class === "DzIrayRenderer")
                    || (requested === "viewport"
                        && readback.render_type === Number(opts.ScreenShot))
                );
                return {
                    mutation_schema: 1, ok: matches,
                    requested_engine: requested, persisted: matches,
                    reason: matches ? null : "readback_mismatch",
                    readback: readback
                };
        `);

    const raw = (await this.client.execute(script)).value as Record<string, unknown> | null;
    if (raw === null || typeof raw !== "object" || raw.mutation_schema !== 1) {
      throw new RenderError("Render engine mutation failed: malformed_response");
    }
    const readback = normalizeEngineReadback(raw.readback);
    const expected =
      requested === "iray"
        ? readback.status === "verified_iray" &&
          readback.engine === "iray" &&
          (readback.render_type as Record<string, unknown>)?.raw === 2 &&
          (readback.active_renderer as Record<string, unknown>)?.class_name === "DzIrayRenderer"
        : readback.status === "verified_non_iray" &&
          readback.engine === "viewport_gl" &&
          (readback.render_type as Record<string, unknown>)?.raw === 0;

    if (raw.ok !== true || raw.requested_engine !== requested || raw.persisted !== true || !expected) {
      let reason = raw.reason as string | undefined;
      const knownReasons = new Set([
        "render_manager_unavailable",
        "render_options_unavailable",
        "iray_renderer_unavailable",
        "mutation_failed",
        "readback_mismatch",
      ]);
      if (!reason || !knownReasons.has(reason)) {
        reason = "readback_mismatch";
      }
      throw new RenderError(`Render engine mutation failed: ${reason}`);
    }
    return {
      mutation_schema: ENGINE_MUTATION_SCHEMA,
      success: true,
      requested_engine: requested,
      persisted: true,
      reason: null,
      readback,
    };
  }

  /**
   * Return the active render engine name.
   *
   * The Render Settings pane's "Engine" dropdown conflates two separate
   * DazScript concepts, confirmed against a live instance:
   * `DzRenderOptions.renderType` is a 3-value enum (ScreenShot,
   * HardwareAssisted, Software) picking *how* the scene is rendered; only
   * when it's `Software` does `renderMgr.getActiveRenderer()` (the
   * pluggable Iray/Filament/... renderer) apply. Returns `"viewport"` or
   * `"multi_pass_opengl"` for the first two modes, otherwise the mapped
   * engine name (e.g. `"iray"`, `"filament"`), falling back to the raw
   * DazScript class name (e.g. `"DzIrayRenderer"`) if it isn't one of the
   * known engines.
   */
  async activeEngine(): Promise<string | null> {
    const script = ScriptBuilder.iife(`
            var mgr = ${RENDER_MGR};
            if (!mgr) return null;
            var opts = mgr.getRenderOptions();
            if (opts.renderType === opts.ScreenShot) return "viewport";
            if (opts.renderType === opts.HardwareAssisted) return "multi_pass_opengl";
            var renderer = mgr.getActiveRenderer();
            return renderer ? renderer.className() : null;
        `);
    const className = (await this.client.execute(script)).value as string | null;
    if (className === null) return null;
    return ENGINE_CLASS_TO_NAME[className] ?? className;
  }

  /**
   * Set the active render engine.
   *
   * @param engine `"viewport"` or `"multi_pass_opengl"` to switch
   * `DzRenderOptions.renderType` to one of the two non-pluggable modes, or a
   * pluggable renderer name (e.g. `"iray"`, `"filament"`, or a raw
   * DazScript class name like `"DzIrayRenderer"`) to set `renderType` to
   * `Software` and activate that renderer.
   * @throws RenderError If a pluggable renderer name doesn't resolve to a
   * renderer registered with the render manager (e.g. the Filament plugin
   * isn't installed).
   */
  async setActiveEngine(engine: string): Promise<void> {
    const normalized = engine.trim();
    const lower = normalized.toLowerCase();

    if (NON_SOFTWARE_ENGINES.has(lower)) {
      const renderTypeExpr = lower === "viewport" ? "opts.ScreenShot" : "opts.HardwareAssisted";
      const script = ScriptBuilder.iife(`
                var mgr = ${RENDER_MGR};
                if (!mgr) return false;
                var opts = mgr.getRenderOptions();
                opts.renderType = ${renderTypeExpr};
                opts.applyChanges();
                ${DazRenderSettings.refreshRenderSettingsPaneScript()}
                return true;
            `);
      await this.client.execute(script);
      return;
    }

    const engineClass = ENGINE_NAME_TO_CLASS[lower] ?? normalized;
    const script = ScriptBuilder.iife(`
            var mgr = ${RENDER_MGR};
            if (!mgr) return false;
            var renderer = mgr.findRenderer(${ScriptBuilder.escapeString(engineClass)});
            if (!renderer) return false;
            var opts = mgr.getRenderOptions();
            opts.renderType = opts.Software;
            opts.applyChanges();
            mgr.setActiveRenderer(renderer);
            ${DazRenderSettings.refreshRenderSettingsPaneScript()}
            return true;
        `);
    const found = (await this.client.execute(script)).value;
    if (!found) {
      throw new RenderError(`Render engine not available: ${JSON.stringify(engine)} (class ${JSON.stringify(engineClass)})`);
    }
  }

  /** Return the render image size as `{width, height}`. */
  async resolution(): Promise<{ width: number; height: number } | null> {
    const script = ScriptBuilder.iife(`
            var mgr = ${RENDER_MGR};
            if (!mgr) return null;
            var opts = mgr.getRenderOptions();
            var sz = opts.imageSize;
            return {width: sz.width, height: sz.height};
        `);
    return (await this.client.execute(script)).value as { width: number; height: number } | null;
  }

  /**
   * Set the render image size in pixels.
   *
   * `QSize` is exposed as a constructor in DazScript; plain object literals
   * are not coerced, so `new QSize(w, h)` is required.
   */
  async setResolution(width: number, height: number): Promise<void> {
    const w = Math.trunc(width);
    const h = Math.trunc(height);
    const script = ScriptBuilder.iife(`
            var mgr = ${RENDER_MGR};
            if (!mgr) return;
            var opts = mgr.getRenderOptions();
            opts.imageSize = new QSize(${w}, ${h});
            opts.applyChanges();
        `);
    await this.client.execute(script);
  }

  /** Return the filename set for rendered images. */
  async outputPath(): Promise<string | null> {
    const script = ScriptBuilder.iife(`
            var mgr = ${RENDER_MGR};
            if (!mgr) return null;
            return mgr.getRenderOptions().renderImgFilename;
        `);
    return (await this.client.execute(script)).value as string | null;
  }

  async setOutputPath(outPath: string): Promise<void> {
    const script = ScriptBuilder.iife(`
            var mgr = ${RENDER_MGR};
            if (!mgr) return;
            var opts = mgr.getRenderOptions();
            opts.renderImgFilename = ${ScriptBuilder.escapeString(outPath)};
            opts.applyChanges();
        `);
    await this.client.execute(script);
  }

  /** Return the gamma correction value. */
  async gamma(): Promise<number | null> {
    const script = ScriptBuilder.iife(`
            var mgr = ${RENDER_MGR};
            if (!mgr) return null;
            var opts = mgr.getRenderOptions();
            return opts.gamma;
        `);
    return (await this.client.execute(script)).value as number | null;
  }

  async setGamma(value: number): Promise<void> {
    const script = ScriptBuilder.iife(`
            var mgr = ${RENDER_MGR};
            if (!mgr) return;
            var opts = mgr.getRenderOptions();
            opts.gamma = ${Number(value)};
            opts.applyChanges();
        `);
    await this.client.execute(script);
  }

  /** Return whether polygons are rendered as double-sided. */
  async doubleSided(): Promise<boolean | null> {
    const script = ScriptBuilder.iife(`
            var mgr = ${RENDER_MGR};
            if (!mgr) return null;
            return mgr.getRenderOptions().doubleSided;
        `);
    const result = (await this.client.execute(script)).value;
    return result === null || result === undefined ? null : Boolean(result);
  }

  async setDoubleSided(value: boolean): Promise<void> {
    const jsBool = value ? "true" : "false";
    const script = ScriptBuilder.iife(`
            var mgr = ${RENDER_MGR};
            if (!mgr) return;
            var opts = mgr.getRenderOptions();
            opts.doubleSided = ${jsBool};
            opts.applyChanges();
        `);
    await this.client.execute(script);
  }

  /**
   * Render the scene to {@link outputPath}.
   *
   * DAZ Studio's `doRender()` only writes to disk when `renderImgToId` is
   * set to `DzRenderOptions.DirectToFile` and the camera is applied to both
   * the render options and the active viewport before the call.
   *
   * @returns A {@link RenderOutcome} with `success` and the resolved
   * `outputPath` actually written by `doRender()` (`opts.renderImgFilename`
   * after the call).
   * @throws Error If both `cameraName` and `cameraLabel` are given.
   */
  async render(opts: RenderOptions = {}): Promise<RenderOutcome> {
    const { cameraName, cameraLabel } = opts;
    if (cameraName !== undefined && cameraLabel !== undefined) {
      throw new Error("Pass at most one of cameraName or cameraLabel");
    }
    let camExpr: string;
    if (cameraLabel !== undefined) {
      camExpr = `Scene.findCameraByLabel(${ScriptBuilder.escapeString(cameraLabel)})`;
    } else if (cameraName !== undefined) {
      camExpr = `Scene.findCamera(${ScriptBuilder.escapeString(cameraName)})`;
    } else {
      camExpr = "MainWindow.getViewportMgr().getActiveViewport().get3DViewport().getCamera()";
    }

    const script = ScriptBuilder.iife(`
            var mgr = ${RENDER_MGR};
            if (!mgr) return {success: false, output_path: null};
            var cam = ${camExpr};
            if (!cam) return {success: false, output_path: null};
            var opts = mgr.getRenderOptions();
            opts.camera = cam;
            opts.renderImgToId = DzRenderOptions.DirectToFile;
            // findCanvasDefinition(name, true) implicitly reassigns the
            // "Active Canvas" property to whatever canvas was most recently
            // created/looked-up (confirmed against a live instance). Once
            // any non-Beauty canvas exists (Depth, MaterialID, ...), doRender()
            // saves *that* canvas's pass to the primary output file instead
            // of the true beauty image -- the "clown render" bug (GH #32).
            // Force it back to Beauty right before rendering so the primary
            // output always matches this method's documented contract,
            // regardless of what canvases were added or last touched.
            var canvasHolder = ${this.irayRenderOptionsHolderExpr()};
            if (canvasHolder && canvasHolder.renderToCanvases) {
                var beautyCanvas = canvasHolder.findCanvasDefinition("Beauty", true);
                beautyCanvas.canvasType = beautyCanvas.canvasTypeFromString("Beauty");
                var activeCanvasProp = canvasHolder.findProperty("Active Canvas");
                if (activeCanvasProp) activeCanvasProp.setValueFromString("Beauty");
            }
            var vp = MainWindow.getViewportMgr().getActiveViewport().get3DViewport();
            var prevCam = vp ? vp.getCamera() : null;
            if (vp) vp.setCamera(cam);
            // doRender()'s own return value is undocumented in the SDK (no
            // "Returns:" section at all) and was found to report success even
            // for a render the user cancelled mid-progress via the DAZ Studio
            // UI. DzRenderMgr.renderFinished(bool succeeded) is the SDK's
            // explicit, named completion signal -- SceneEventBroker.cpp
            // already relies on it as the "guaranteed exit path" that fires
            // correctly across error/cancel cases -- so capture it directly
            // instead of guessing at doRender()'s return code.
            var renderSucceeded = null;
            function _onRenderFinished(succeeded) { renderSucceeded = succeeded; }
            mgr["renderFinished(bool)"].connect(_onRenderFinished);
            try {
                mgr.doRender(opts);
            } finally {
                mgr["renderFinished(bool)"].disconnect(_onRenderFinished);
            }
            if (vp && prevCam) vp.setCamera(prevCam);
            return {
                success: renderSucceeded === true,
                output_path: mgr.getRenderOptions().renderImgFilename
            };
        `);
    const result = ((await this.client.execute(script)).value as { success?: boolean; output_path?: string | null } | null) ?? {};
    return {
      success: Boolean(result.success ?? false),
      outputPath: result.output_path ?? null,
    };
  }

  /**
   * Alias for {@link render} kept for parity with dazpy's backwards-compatible name.
   * `doRender()` is synchronous in DAZ Studio so no polling is required.
   */
  async renderAndWait(): Promise<RenderOutcome> {
    return this.render();
  }

  /** `true` if there is a completed render available to save. */
  async hasRender(): Promise<boolean> {
    const script = ScriptBuilder.iife(`
            var mgr = ${RENDER_MGR};
            if (!mgr) return false;
            return mgr.hasRender();
        `);
    return Boolean((await this.client.execute(script)).value);
  }

  /** Iray progressive rendering sample cap (`Max Samples` in the Advanced tab). */
  async maxSamples(): Promise<number | null> {
    const result = await this.getIrayProperty("Max Samples");
    return result === null || result === undefined ? null : Number(result);
  }

  async setMaxSamples(value: number): Promise<void> {
    await this.setIrayProperty("Max Samples", Math.trunc(value));
  }

  /** Iray progressive rendering time cap in seconds (`Max Time` in the Advanced tab). */
  async maxTimeSecs(): Promise<number | null> {
    const result = await this.getIrayProperty("Max Time");
    return result === null || result === undefined ? null : Number(result);
  }

  async setMaxTimeSecs(value: number): Promise<void> {
    await this.setIrayProperty("Max Time", Math.trunc(value));
  }

  /** Iray `Rendering Quality` convergence target (higher converges further). */
  async quality(): Promise<number | null> {
    const result = await this.getIrayProperty("Rendering Quality");
    return result === null || result === undefined ? null : Number(result);
  }

  async setQuality(value: number): Promise<void> {
    await this.setIrayProperty("Rendering Quality", Number(value));
  }

  /**
   * Apply a named Iray quality preset, controlling sample count and render time.
   *
   * @param preset One of `"draft"`, `"preview"`, `"good"`, `"final"`
   * (fastest/lowest quality to slowest/highest quality).
   * @throws Error If `preset` is not a recognized preset name.
   */
  async setQualityPreset(preset: string): Promise<void> {
    const settings = QUALITY_PRESETS[preset];
    if (settings === undefined) {
      throw new Error(`Unknown quality preset ${JSON.stringify(preset)}; expected one of ${JSON.stringify(Object.keys(QUALITY_PRESETS).sort())}`);
    }
    await this.setIrayProperty("Max Samples", settings.maxSamples);
    await this.setIrayProperty("Max Time", settings.maxTime);
    await this.setIrayProperty("Rendering Quality Enable", settings.qualityEnable);
    if (settings.quality !== undefined) {
      await this.setIrayProperty("Rendering Quality", settings.quality);
    }
  }

  /** Master on/off switch for all Iray Canvas output (`Render to Canvases`). */
  async canvasesEnabled(): Promise<boolean | null> {
    const script = ScriptBuilder.iife(`
            var holder = ${this.irayRenderOptionsHolderExpr()};
            if (!holder) return null;
            return holder.renderToCanvases;
        `);
    const result = (await this.client.execute(script)).value;
    return result === null || result === undefined ? null : Boolean(result);
  }

  async setCanvasesEnabled(value: boolean): Promise<void> {
    const jsBool = value ? "true" : "false";
    const script = ScriptBuilder.iife(`
            var holder = ${this.irayRenderOptionsHolderExpr()};
            if (!holder) return;
            holder.renderToCanvases = ${jsBool};
            ${DazRenderSettings.refreshRenderSettingsPaneScript()}
        `);
    await this.client.execute(script);
  }

  /** List the Iray Canvases currently configured on the active render. */
  async listCanvases(): Promise<Canvas[]> {
    const script = ScriptBuilder.iife(`
            var holder = ${this.irayRenderOptionsHolderExpr()};
            if (!holder) return [];
            var result = [];
            var n = holder.getNumCanvasDefinitions();
            for (var i = 0; i < n; i++) {
                var c = holder.getCanvasDefinition(i);
                result.push({
                    name: c.name,
                    canvasType: c.canvasTypeToString(c.canvasType),
                    index: c.index
                });
            }
            return result;
        `);
    return ((await this.client.execute(script)).value as Canvas[] | null) ?? [];
  }

  /**
   * Add (or reconfigure) an Iray Canvas by name.
   *
   * @param name Canvas name. If a canvas with this name already exists it
   * is reconfigured to `canvasType` rather than duplicated.
   * @param canvasType One of `"Beauty"`, `"Diffuse"`, `"Specular"`,
   * `"Glossy"`, `"Emission"`, `"LightGroup"`, `"EnvironmentLighting"`,
   * `"LPE"`, `"Irradiance"`, `"Alpha"`, `"Shadow"`, `"AmbientOcclusion"`,
   * `"Distance"`, `"Depth"`, `"MaterialTag"`, `"MaterialID"`, `"ObjectID"`,
   * `"Normal"`, `"TextureCoordinate"`, `"BSDFWeight"`,
   * `"ConvergenceHeatmap"`, `"PostToon"`, `"WorldPosition"`.
   * @throws RenderError If the render manager or Iray property holder is unavailable.
   */
  async addCanvas(name: string, canvasType: string): Promise<Canvas> {
    const script = ScriptBuilder.iife(`
            var holder = ${this.irayRenderOptionsHolderExpr()};
            if (!holder) return null;
            var c = holder.findCanvasDefinition(${ScriptBuilder.escapeString(name)}, true);
            c.canvasType = c.canvasTypeFromString(${ScriptBuilder.escapeString(canvasType)});
            ${DazRenderSettings.refreshRenderSettingsPaneScript()}
            return {
                name: c.name,
                canvasType: c.canvasTypeToString(c.canvasType),
                index: c.index
            };
        `);
    const result = (await this.client.execute(script)).value as Canvas | null;
    if (result === null) {
      throw new RenderError("Failed to add canvas: render manager or Iray property holder unavailable");
    }
    return result;
  }

  /**
   * Remove a configured Iray Canvas by name.
   * @returns `true` if a matching canvas was found and removed, `false` if no canvas with `name` exists.
   */
  async removeCanvas(name: string): Promise<boolean> {
    const script = ScriptBuilder.iife(`
            var holder = ${this.irayRenderOptionsHolderExpr()};
            if (!holder) return false;
            var c = holder.findCanvasDefinition(${ScriptBuilder.escapeString(name)}, false);
            if (!c) return false;
            holder.removeCanvasDefinition(c);
            ${DazRenderSettings.refreshRenderSettingsPaneScript()}
            return true;
        `);
    return Boolean((await this.client.execute(script)).value);
  }

  /**
   * Return each configured canvas's resolved output file path for a render to `outputPath`.
   *
   * Derived from DAZ Studio's naming convention -- canvases are written to
   * `<dir>/<basename>_canvases/<basename>-<canvasName>-<canvasType>.exr`
   * alongside the main render output. Confirmed empirically against a live
   * render; DazScript does not expose these paths directly, so this is
   * computed rather than queried.
   *
   * @param outputPath The path passed as the main render's `outputPath`
   * (i.e. what {@link setOutputPath} would be called with).
   * @returns A map from each canvas's name to its resolved output path.
   */
  async canvasOutputPaths(outputPath: string): Promise<Record<string, string>> {
    const sepIdx = Math.max(outputPath.lastIndexOf("/"), outputPath.lastIndexOf("\\"));
    const directory = sepIdx >= 0 ? outputPath.slice(0, sepIdx) : "";
    const filename = outputPath.slice(sepIdx + 1);
    const dotIdx = filename.lastIndexOf(".");
    const basename = dotIdx >= 0 ? filename.slice(0, dotIdx) : filename;
    const sep = sepIdx >= 0 ? outputPath[sepIdx] : "/";
    const prefix = directory ? `${directory}${sep}` : "";
    const canvasesDir = `${basename}_canvases`;

    const canvases = await this.listCanvases();
    const result: Record<string, string> = {};
    for (const canvas of canvases) {
      result[canvas.name] = `${prefix}${canvasesDir}${sep}${basename}-${canvas.name}-${canvas.canvasType}.exr`;
    }
    return result;
  }
}
