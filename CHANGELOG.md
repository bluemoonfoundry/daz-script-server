# Changelog

All notable changes to DazScript Server are documented here.

## [Unreleased]

### Async script-file jobs

`POST /execute/async` now implements the `scriptFile` form already described
by the API schema. File-backed requests keep the path in the queue and call
`DzScript::loadFromFile()` when execution starts, preserving
`getScriptFileName()` and relative `include()` behavior instead of flattening
the file to inline source. `DazClient` and `AsyncDazClient` expose this as
`execute_file_async_submit()`; the existing status/result/list/cancel methods
manage the returned request id.

## [2.9.0] - 2026-08-16

### Added

- **dazpy.cinematics — CinematicStaticShot, OrbitCamera, FrameSubject,
  CinematicAnimatedShot** — domain-level camera-shot builders on top of
  `DazCamera`/`DazScene`. `apply_static_shot()` places/aims/configures a
  camera in one call (position, `look_at` target or explicit rotation,
  focal length, depth of field, aspect/pixel dimensions).
  `apply_orbit_camera()` sweeps a camera around a target across a frame
  range by baking a per-frame position/aim on every timeline frame
  (widening the scene's animation range as needed so `Scene.setFrame()`
  doesn't clamp past frame 30 on a fresh scene). `apply_frame_subject()`
  frames a subject at a named shot distance (`close_up` / `medium` /
  `full_body`). `apply_animated_shot()` (`CinematicAnimatedShot`) is the
  interpolated-keyframe counterpart to `OrbitCamera` — it writes real DAZ
  Studio keyframes at each `CameraKeyframe` waypoint
  (`set_position_at_frame()`/`set_rotation_at_frame()`) and lets DAZ Studio
  interpolate between them via its own animation curves, instead of a
  per-frame bake.
- **dazpy.lighting — ThreePointLightSetup, HDRIEnvironment** —
  `apply_three_point_light_setup()` creates and places a conventional
  key/fill/rim light rig around a target (`Vec3` or `DazNode`), via
  angle/distance spherical placement or explicit world-space positions per
  light. `apply_hdri_environment()` (`HDRIEnvironment`) applies image-based
  dome lighting — environment map, intensity, dome rotation,
  dome/scene/both mode, dome visibility, and IBL sampling resolution —
  validating the image path exists before any DazScript call (an invalid
  path passed to the underlying `setMap()` can hang or crash DAZ Studio via
  a blocking file-not-found dialog) and verifying a post-apply
  "Environment Intensity" readback so a silent no-op on an unexpected DAZ
  Studio build surfaces as a `RenderError` instead of failing invisibly.
- **dazpy.poses — apply_pose, reset_transforms, zero_figure** — `apply_pose()`
  applies a `DazPose` (or loads one from a JSON path first) to a skeleton in
  one call. `reset_transforms()` zeroes a node's local position/rotation and
  resets scale to 1.0. `zero_figure()` drives every bone rotation and morph
  on a skeleton to zero without touching the figure's root transform by
  default; an opt-in `include_props=True` also zeroes node-level numeric
  properties via `DazPose.apply_full()` for rigs that route transforms
  through built-in dials, at the cost of that root-transform guarantee.
- **dazpy.math3.AxisRemap** — a generic signed-axis-permutation converter
  for `Vec3`/`Quat`/`BoundingBox` between coordinate conventions (e.g. DAZ
  Studio's Y-up to Blender/glTF-style Z-up), with a ready-made
  `Y_UP_TO_Z_UP` preset. Reflective remaps (determinant `-1`) are supported
  for vectors/bounding boxes but correctly rejected for `apply_quat()`,
  since a reflection has no quaternion representation.
- **DazSkeleton.bone_rotations_quat()** — returns local-space quaternion
  rotations for every bone in one HTTP round-trip (`{bone: {x, y, z, w}}`),
  as an alternative to `bone_rotations()` for callers who will compose the
  result with another rotation (e.g. via `AxisRemap.apply_quat()`) — this
  avoids the per-bone Euler rotation-order ambiguity that
  `DazBone.rotation_order` would otherwise require tracking.
- **dazpy.DazCamera — aperture / bokeh controls** — `f_stop` (DOF blur
  intensity, backed by the "F/Stop" property), `aperture_blades` (bokeh
  blade count; `0` = circular, 3+ = polygonal), and
  `aperture_blade_rotation` (polygon rotation angle), completing the last
  item split off from #20. Property labels confirmed against a live DAZ
  Studio instance. (GH #25)
- **dazpy.materials — IrayMaterial, TextureMap, SurfaceProperty** —
  declarative Iray Uber Base material setup built on `DazMaterial`:
  `apply_iray_material()` sets base color, metallic, roughness, glossy
  reflectivity, cutout opacity, bump, and top coat weight, plus texture-slot
  assignment (`apply_texture_map()`, with file-existence validation before
  any DazScript call) and generic named-channel get/set
  (`get_surface_property()`/`set_surface_property()`) for channels not
  covered by the typed fields. (GH #31)
- **Frame-level progress streaming for animation renders** — the
  `GET /render/:id/progress` SSE stream now emits a progress event at each
  frame boundary during an animation render, instead of only start/terminal
  events. `buildAnimationRenderScript()` prints a `[DAZPY_FRAME] n/total`
  marker right before each frame's `doRender()` call;
  `DzScriptServerPane::onMessagePosted()` intercepts it (only while a render
  is actually running) and reports it via `RenderProgressBroker::
  notifyProgress()` as `percent = 100 * (frame-1) / total`. The DAZ SDK
  exposes no `renderProgress(int)` signal and Iray posts no parseable
  intra-frame progress text through the debug-message channel, so this
  print-marker is the only real progress source available — single-frame
  renders still only get the 0% start / terminal finish events. (GH #31)

### Async client — `dazpy.aio.AsyncDazClient`

New `dazpy.aio` module with `AsyncDazClient`, an `httpx.AsyncClient`-backed
mirror of `DazClient`'s full method surface (`execute`, `execute_file`,
async submit/status/result/list/cancel, render submit/batch/animation, USD
export, server-health endpoints) as `async def` methods, including
`asyncio`-native `retry_on_busy`/`max_wait` backoff and an async context
manager (`async with AsyncDazClient() as client:`) for connection-pool
lifecycle. Requires the optional `httpx` dependency (`pip install
dazpy[aio]`). Removes the need for async callers (FastAPI, FastMCP,
ComfyUI, Temporal) to wrap synchronous `DazClient` calls in
`asyncio.to_thread()`.

### `DazClient` connection pooling + `close()`

`DazClient` now uses a pooled `requests.Session` for connection reuse
instead of a fresh connection per call, and gained `close()` and context
manager support (`with DazClient() as client:`), mirroring
`AsyncDazClient`'s connection-lifecycle handling.

### Fix: `/scene/save-copy`'s clean-scene fast path had no busy coverage

Live testing plus code inspection (`daz-script-server-aaa`) found that
`/scene/save-copy` completely bypassed `SceneSaving` busy tracking when the
scene was already clean: that branch calls `QFile::copy()` directly and
never touches `DzScene::saveScene()`, so the `sceneSaveStarting`/`sceneSaved`
signals that drive busy detection never fired — any request landing during
that copy got no `503 STUDIO_BUSY` fast-fail at all. (A live SSE capture
confirmed the *dirty*-scene branch, which does call `saveScene()`, fires
these signals reliably — the gap was specific to the clean-scene shortcut.)
`SceneEventBroker::enterBusy()`/`exitBusy()` are now public, and
`handleSaveCopy()` brackets its entire body (both branches) with an RAII
`BusyScope` guard, giving explicit, signal-independent busy coverage for
this handler.

### Fix: render success reporting trusted `doRender()`'s undocumented return value

`doRender()`'s C++ signature is `bool doRender(...)`, but the DAZ SDK's own
docs have no "Returns:" section for it at all -- its return value is
unspecified. `dazpy.DazRenderSettings.render()` guessed at its meaning
(`err === 0 || err === true`) and was found, live, to report `success: true`
for a render the user cancelled mid-progress from the DAZ Studio UI. The
async render endpoints (`/render/submit`, `/render/animation`, backing
`DazClient.render_submit()`/`render_animation_submit()`) were worse --
`buildRenderScript()`/`buildAnimationRenderScript()` in
`src/DzScriptServerPane.cpp` didn't check the return value at all and
hardcoded `success: true` unconditionally.

Both now derive success from `DzRenderMgr.renderFinished(bool succeeded)`,
the SDK's explicit, named completion signal -- already trusted elsewhere in
this codebase (`SceneEventBroker.cpp`) as the "guaranteed exit path" that
fires correctly across error/cancel cases. The animation loop tracks
per-frame success and reports the AND of all frames.

### Fix: `render()` "clown render" when Iray Canvases are enabled (GH #32)

`DzIrayPropertyHolder.findCanvasDefinition(name, true)` implicitly
reassigns the `Active Canvas` enum property to whichever canvas was most
recently created/looked-up (confirmed against a live instance). Once any
non-Beauty canvas (Depth, MaterialID, ...) existed, `doRender()` would save
that canvas's pass as the primary output file instead of the true beauty
image -- producing a flat, per-material-region "clown render" in place of
the expected beauty render. Manual use via the Render Settings UI didn't
hit this because the UI's canvas list keeps `Active Canvas` on Beauty
unless a user deliberately changes it.

`DazRenderSettings.render()` now forces `Active Canvas` back to `Beauty`
(creating it if missing) immediately before `doRender()` whenever
`renderToCanvases` is on, guaranteeing the primary saved output always
matches the method's documented "render the scene" contract regardless of
what canvases were added or last touched.

### Fix: SDK6 (Qt6) nightly build failed on `QtCore/qregexp.h`

`QRegExp` was removed from Qt6 Core in favor of the separate `Qt5Compat`
module, which lives under a different include path
(`QtCore5Compat/qregexp.h`, not `QtCore/qregexp.h`) — breaking the nightly
SDK6 build with a missing-header error on all three Qt6 platforms (Windows,
macOS Intel, macOS Apple Silicon). The one `QRegExp` use (parsing
`[DAZPY_FRAME] n/total` progress markers) now uses `QRegularExpression`
when building against SDK6, guarded by the existing `DAZ_SDK_MAJOR_VERSION`
pattern; SDK4 keeps `QRegExp`, since it targets Qt 4.8, which predates
`QRegularExpression` entirely.

### Changed: example scripts moved to `daz-script-server-examples`

The example scripts formerly under this repo's `docs/examples/` now live in
their own repo,
[daz-script-server-examples](https://github.com/bluemoonfoundry/daz-script-server-examples),
kept up to date with the current `dazpy` API and organized by category with
per-example READMEs. `docs/examples/` now just points there.
`sprite_matrix` and `comfyui_enhance` are the exception — this repo's own
test suite imports them directly as unit-test fixtures, so they moved to
`tests/fixtures/rendering/` instead; the examples repo carries its own
documented, standalone copies of both for general use.

## [2.8.1] - 2026-07-24

### Truthful Iray/Viewport render-engine selector

`DazRenderSettings.render_engine_state()` reads `DzRenderOptions.renderType`
and the active renderer class/name as separate facts, returning a schema-1
record with a normalized `verified_iray` / `verified_non_iray` /
`unavailable` status and field-level live-readback provenance. A retained
`NVIDIA Iray` active-renderer name never overrides a Viewport/OpenGL
`renderType`.

`DazRenderSettings.set_render_engine("iray" | "viewport")` is an explicit
persistent setter that selects the registered `DzIrayRenderer` plus
`Software` for Iray, or `ScreenShot` for Viewport, applies the change, and
returns only after exact readback. Missing renderers, mutation/apply
faults, malformed replies, and readback disagreement raise `RenderError`;
unknown engine names raise `ValueError` before dispatch.

The `engine` field on `/render`, `/render/batch`, and `/render/animation`
also accepts `viewport` and uses the same fail-closed mutation/readback
rules.

## [2.8.0] - 2026-07-23

DAZ Studio's Qt main thread is single-threaded: if a user drives DAZ Studio
through its own UI (loading a scene, saving, clearing the scene, rendering)
at the same time the HTTP API is in use, requests that need the main thread
used to block indefinitely via `Qt::BlockingQueuedConnection`, with no
timeout and no signal to the caller.

`/execute`, `/scripts/:id/execute`, the async-enqueue endpoints, and the
render-submit endpoints (`/render`, `/render/batch`, `/render/animation`)
now check DAZ Studio's busy state first and fail fast with `503` and
`error_code: "STUDIO_BUSY"` (plus a `Retry-After` header) instead of
hanging. Busy state is tracked via `SceneEventBroker`'s existing `DzScene`
signal connections (scene load/save/clear, render — start/finish pairs).

`dazpy` gains a `DazBusyError` exception hierarchy — `StudioBusyError`
(503) and `ConcurrencyLimitError` (429) — each carrying `reason` and
`retry_after`. This also fixes a pre-existing bug where `429
CONCURRENT_LIMIT_EXCEEDED` responses were misreported as
`ScriptRuntimeError`. Opt-in `retry_on_busy`/`max_wait` keyword arguments
(capped linear backoff, off by default) are available on `execute`,
`execute_file`, `execute_async_submit`, `render_submit`,
`render_batch_submit`, and `render_animation_submit`.

Design: `docs/superpowers/specs/2026-07-22-studio-busy-handling-design.md`.
Plan: `docs/superpowers/plans/2026-07-22-studio-busy-handling.md`.

## [2.7.2] - 2026-07-19

No functional changes to `dazpy`'s behavior. `2.7.1`'s version bump missed
three places still reading `2.7.0`: `dazpy.__version__` itself (already
baked into the published `2.7.1` wheel, which is why this needed a new
version rather than a doc-only fix), `openapi.yaml`'s `info.version` plus
two response examples, and the plugin's own `DZSRV_VERSION_STR`
(`common_version.h` — what `/status`/`/health` actually return at
runtime). All three now correctly say `2.7.2`.

## [2.7.1] - 2026-07-19

No functional changes. The `2.7.0` dazpy wheel was uploaded to PyPI before
a README fix landed (see `2.7.0` below), and PyPI has no way to update an
already-published version's metadata/description — the project page stayed
stuck showing pre-`2.7.0` text. Republished under a new version to fix the
displayed description; `2.7.1`'s dazpy source is identical to `2.7.0`'s.
Plugin binaries are rebuilt and retagged alongside it since this repo's
release pipeline ties both to one version number, but contain no code
changes either.

## [2.7.0] - 2026-07-19

### Added

- **`DazRenderSettings` Iray Canvas support** (`list_canvases()`,
  `add_canvas()`, `remove_canvas()`, `canvases_enabled`,
  `canvas_output_paths()`) — enumerate, create, and remove Iray Canvases
  (normal/depth/material-ID/etc. passes) and resolve their output file paths
  for a given render, closing GitHub issue #19's Canvas gap. Backed by
  `App.getRenderMgr().getRenderElementObjects()[1]`, confirmed against a live
  DAZ Studio instance — no server-side changes needed.
- **`DazScene.create_camera()` / `DazScene.create_light()`** — factory
  methods to create new camera and light nodes and add them to the scene,
  returning `DazCamera`/`DazLight` wrappers usable with the rest of the
  existing API (`set_position`, `aim_at`, `set_color`, etc). `create_light()`
  accepts `"spot"`, `"point"`, or `"distant"`.
- **`DazNode.delete()` / `DazNode.reparent()`** — remove a node from the
  scene entirely, or move it to a new parent in the hierarchy via the
  `removeNodeChild`/`addNodeChild` pattern, optionally preserving its
  world-space transform (`preserve_world_transform=True` by default).
- **`DazProperty.raw_value`** — read/write a property's own dial value,
  excluding any `DzERCLink` controller contributions. Use this instead of
  `.value` whenever a save/restore round trip needs to be exact (see Fixed,
  below, for why `.value` is unsafe for that).
- **`DazScene.overview()`** — one-call top-level scene snapshot (root
  figures, cameras, lights, open scene file, primary selection, node count).
- **`DazScene.node_hierarchy(root, max_depth=None)`** — one-call descendant
  tree rooted at a single named node (typically a figure), with a `type` on
  every entry and an optional recursion-depth limit. Complements the
  existing `node_tree()`, which always starts from every scene root.
- **`DazSceneState`** — full scene checkpoint: every skeleton's complete
  pose (via `DazPose`, so bone-level, not just the root transform) plus
  camera and light transforms/key properties, captured and restored via
  `raw_value` throughout so repeated capture/apply cycles are idempotent.
- **`DazCamera.lens_shift_x` / `.lens_shift_y`** — read/write properties
  backed by `DzCamera`'s "Lens Shift X/Y (mm)" controls, the same values the
  render engine uses — needed for depth-based effects (fog, DOF-driven line
  weight) to match the actual render.
- **`DazScene.export_fbx()` / `.export_obj()`** — synchronous export via DAZ
  Studio's native `DzFbxExporter`/`DzObjExporter`, unlike the async job
  pattern `export_usd_submit()` uses — there's no custom pipeline behind
  these to poll on. `RunSilent` is forced on to avoid the native exporter's
  modal options dialog hanging the HTTP handler's thread.
- **`DazViewport.draw_style()` / `.set_draw_style()`** — controls the
  viewport's preview quality (Wireframe .. NVIDIA Iray) via
  `getUserDrawStyle()`/`setUserDrawStyle()`, distinct from
  `DazRenderSettings.active_engine()` below. `set_draw_style()` reads the
  style back after setting it and raises `ValueError` if it didn't take,
  since `setUserDrawStyle()` silently no-ops on an unrecognized label.
- **`DazRenderSettings.active_engine()` / `.set_active_engine()`** — query
  and switch the Render Settings "Engine" dropdown. Correctly distinguishes
  `DzRenderOptions.renderType` (which governs "viewport"/
  "multi_pass_opengl") from `renderMgr.getActiveRenderer()` (which only
  applies in Software mode) — the two are easy to conflate since the UI
  presents them as one dropdown. `set_active_engine()` raises `RenderError`
  for a pluggable renderer name that isn't registered (e.g. the Filament
  plugin not installed).
- **`DazRenderSettings` Iray quality/samples control** —
  `max_samples`/`max_time_secs`/`quality` properties and
  `set_quality_preset()` (draft/preview/good/final), backed by the active
  Iray renderer's property holder since these aren't exposed on
  `DzRenderOptions`. Plus `DazClient.list_requests()`, wrapping the existing
  `GET /requests` endpoint to list all tracked async requests by status.
- **Per-frame animation render submission** — `POST /render/animation` and
  `DazClient.render_animation_submit()`, mirroring the existing
  single-render pattern as one trackable async request that loops a
  start/end frame range, writing each frame to `output_path` with its
  `{frame}` token substituted (zero-padded).
- **`DazNode.fit_to()` / `.unfit()` / `.fitted_items()`** — clothing/prop
  fit-to-figure control, matching what `vangard-daz-mcp`'s hand-rolled
  fit/unfit/list-fitted scripts previously did outside `dazpy`.
- **`DazProperty.get_keys()` / `.remove_key()` / `.clear_keys()`** —
  keyframe curve introspection and single-key removal on an animated
  property, without hand-rolled DazScript.
- **dForce simulation control** — a `DazDForce` modifier proxy
  (`freeze_simulation`/`freeze()`/`unfreeze()`, backed by
  `DzDForceModifier`'s "Freeze Simulation" property), wired into `DazNode`'s
  modifier discrimination plus a new `dforce_modifiers()` filter, and
  `DazScene.run_dforce_simulation()` / `.is_simulating()` /
  `.clear_dforce_simulation()` driven by `DzSimulationMgr`. Long-running
  simulations use the existing async execute-and-poll path.
- **General scene-change event stream client** — `DazClient.
  stream_scene_events()` plus `dazpy/_scene_events.py`
  (`SceneEvent`/`watch_scene_events()`/`wait_for_scene_event()`), mirroring
  the existing render-progress stream so callers can watch or block on
  node/light/camera/selection/scene/time/render events over the server's
  existing `GET /scene/events` SSE endpoint without hand-rolling SSE
  parsing.
- **`DazElement.numeric_properties()` / `.class_name`** —
  `numeric_properties()` returns `{label: value}` for every numeric property
  on an element in one round trip, instead of needing one round trip per
  property after `list_properties()`. `class_name` exposes the DazScript
  class name (e.g. `"DzFigure"`) for any element.

### Fixed

- **ERC-inflation fix in `DazPose` didn't cover bone rotation channels** —
  the earlier fix that switched morphs and node properties to
  `getRawValue()`/`setRawValue()` left bone `XRotControl`/`YRotControl`/
  `ZRotControl` channels on plain `getValue()`/`setValue()`. For rigs where
  one bone's rotation is ERC-driven from another (e.g. auto-follow
  bend/twist ratios common on Genesis figures), repeated capture/apply
  cycles kept inflating that bone's rotation the same way the earlier fix
  addressed for morphs/props. `capture()`/`apply()`/`apply_full()` now
  feature-detect raw value support on bone rotation controls too.
- **`DazViewport.capture()` left state unrestored if the viewport
  disappeared mid-wait** — the finish script's `if (!vp) return null;` guard
  ran before *any* of the overlay/selection/Tonemapper restore lines, so if
  the active viewport became unavailable (closed/changed) during the real
  wall-clock `convergence_wait` sleep between the prepare and finish scripts,
  restoration was skipped entirely -- a state the old atomic single-script
  capture could never leave the viewport in. Scene-level restoration
  (primary selection, Tonemapper/Environment node visibility) no longer
  depends on `vp` and always runs; only the viewport-specific properties and
  the capture itself are skipped (returning no image) if `vp` is gone.
- **`DazViewport.capture()` couldn't restore a bone selection** — the
  two-pass capture's primary-selection restore serialises only the selected
  node's name across the prepare/finish round trip and re-resolves it via
  `Scene.findNode()`, which resolves top-level scene nodes but not bones or
  other non-node selectable items (e.g. a bone selected via the Joint
  Editor), so the original selection was silently lost after `capture()`.
  Now also captures the owning skeleton's name for bone selections
  (`isBoneSelectingNode()`/`getSkeleton()`) and falls back to
  `skeleton.findBone(name)` when the direct `findNode()` lookup misses.
- **`DazPose.apply_full()` didn't zero absent node properties** — the
  node-property loop only called `setValue`/`setRawValue` `if (v !==
  undefined)`, with no else-zero branch, unlike the bones loop (explicit
  `else setValue(0)`) and morphs loop (`_v = v !== undefined ? v : 0`) right
  above it in the same function. This broke the documented contract that
  `apply_full()` drives every channel absent from the pose to zero, and also
  affected `DazSceneState.apply()`'s "clean baseline" restore, which relies
  on `apply_full()`. Now matches the bones/morphs pattern.
- **`DazSceneState.apply()` didn't isolate `apply_full()` errors per
  skeleton** — the per-skeleton try/except only wrapped
  `scene.find_skeleton()`; a following `pose.apply_full(skel)` failure
  (transient HTTP/DazScript error, stale skeleton reference) propagated
  uncaught and aborted restoration of all remaining skeletons, cameras, and
  lights, contradicting the docstring's promise that failures are reported
  in `errors` rather than raising. Now `apply_full()` is wrapped in its own
  try/except so a single skeleton's failure is recorded and the loop
  continues.
- **`build_hug_recipe()` swapped far-shoulder targets between actors** — with
  mismatched anchors (e.g. `a_anchor="r_hand"`, `b_anchor="l_hand"`),
  actor_a's hand target used the far shoulder derived from actor_b's anchor
  side instead of actor_a's own, producing an anatomically wrong or
  self-intersecting embrace. Invisible with the default `r_hand`/`r_hand`
  anchors (both sides happen to compute the same far shoulder), which is all
  the prior test covered. Now each actor's far shoulder is derived from its
  own anchor's side.
- **`DazRenderSettings.render()` / `.render_and_wait()` broke truthiness
  callers** — these switched from returning `bool` to a `RenderOutcome`
  dataclass with no `__bool__`, so existing code written against the old
  contract (`if rs.render():`, including downstream projects like
  `vangard-daz-mcp`) always evaluated truthy and silently treated failed
  renders as successful. `RenderOutcome.__bool__` now reflects `success`, so
  `if rs.render():` behaves the same as before; use `.success`/`.output_path`
  directly if you need the full outcome.
- **`DazViewport.capture(..., backdrop_color=...)` raised `ReferenceError`
  restoring the background** — the two-pass capture's finish script
  referenced the JS variable `prevBg`, but `prevBg` was only declared in the
  separate prepare-script `execute()` call (a different HTTP round trip with
  no shared JS scope), so restoring the background always threw. `prevBg` is
  now round-tripped through Python (returned from the prepare script as
  plain JSON, alongside `axesOn`/`selectionName`/etc.) and substituted
  directly into the finish script.

- **`DazPose.capture()` / `.apply()` / `.apply_full()` inflate ERC-driven
  properties on every round trip** — node-level properties captured via
  `getValue()` (e.g. a "Scale" dial fed by dozens of `DzERCLink`-linked
  morphs) return the post-ERC computed total, but `apply()`/`apply_full()`
  wrote that total back via `setValue()`, which sets the property's raw
  slot — so the ERC links add their contribution again on top. Each
  capture/apply cycle compounded the drift (observed inflating a custom
  character's Scale dial from 100% to 270% over a handful of cycles in
  `daz-mcp-server`'s test suite, via its use of `daz_save_pose`/
  `daz_load_pose`). Now uses `getRawValue()`/`setRawValue()` (see
  `DazProperty.raw_value` above) for props and morphs, which round-trip
  correctly regardless of ERC links.

- **`/render` camera selection** — the native render endpoint called
  `App.getViewportMgr()` when a `cameraName` was supplied, which is undefined
  in this DAZ Studio version and made every camera-targeted render fail
  immediately with a `TypeError`. Switched to `MainWindow.getViewportMgr()`,
  matching the pattern already used by `dazpy`'s own render/viewport helpers.
- **`/render` black output with `cameraName`** — after the above fix, renders
  submitted with an explicit camera completed without error but produced a
  black image, because the render camera actually read by `doRender()` comes
  from `opts.camera`, not the viewport's active camera. The endpoint only
  updated the viewport (`setActiveCamera`) and never set `opts.camera`, so
  the renderer used a stale/null camera. Now sets both, matching
  `dazpy/_render.py` and this repo's own camera-preset scripts. Affects both
  `/render` and `/render/batch` (they share `buildRenderScript()`).
- **`DazClient.status()` / `.health()` / `.metrics()` misreported auth
  failures** — these called the internal `_get()` helper directly without
  the 401/403 check `execute()`/`render_submit()`/etc. already had, so a 401
  with no response body surfaced as a raw JSON-decode error instead of
  `AuthenticationError`.
- **`ScriptError` dropped captured output on failure** — callers building
  diagnostics from a failed script (e.g. `daz-mcp-server`'s `daz_execute`)
  lost the `print()` output that led up to the error. `ScriptError`/
  `ScriptRuntimeError`/`ScriptSyntaxError` now accept and surface an
  optional `output` list via `.diagnostic`.
- **Dropped the unsupported `3delight` render engine option** — DAZ Studio
  no longer ships 3Delight; removed it from the engine allow-list and docs
  so a render request naming it fails fast with a clear error instead of
  silently mapping to a renderer that isn't there.

## [2.6.0] - 2026-06-27

### Added

- **DAZ Studio 6 (Qt6) plugin** — new build target (`--sdk-version 6`) linking
  against the DS6 SDK and the matching Qt6 devkit. At runtime the plugin resolves
  Qt6 symbols against DAZ Studio 6's own bundled DLLs; the devkit is only needed
  at link time. See `CLAUDE.md` for `aqtinstall`-based setup.
- **Multi-platform release artifacts** — DS4 and DS6 plugins for Windows,
  macOS Intel, and macOS Apple Silicon are now included in the standard release
  (previously nightly-only). Six artifacts per release:
  `DazScriptServer-ds{4,6}-{windows,macos-Intel,macos-AppleSilicon}.{dll,dylib}`.
- **`POST /scene/save-copy`** — save the current scene to a new path without
  changing the scene's internal filename pointer or dirty flag. Uses
  `QFile::copy()` for clean scenes (byte-identical file, zero state change) and
  a serialise-then-restore approach for dirty scenes. Response includes a
  `method` field (`"copy"`, `"serialize"`, or `"serialize+restore"`).
- **`DazScene.save_copy(path)`** — Python wrapper around the new endpoint.
  See `docs/examples/fundamentals/scene_save_copy.py` for `--compare` /
  `--dry-run` usage.
- **`DazViewport`** — new dazpy class for capturing the DAZ Studio viewport
  programmatically: `capture(path)`, `capture(path, backdrop_color=(R,G,B))`,
  `capture_sprite(path)` (alpha-matted via u2net), `get_size()`, `set_size(w,h)`,
  `is_available()`.
- **`examples/capture_viewport.py`** — CLI for all three capture modes
  (`raw` / `clean` / `sprite`) with `--mode`, `--output`, `--backdrop`,
  `--no-alpha-matting`, `--daz-url`, and `--dry-run` flags.
- **ComfyUI enhancement pipeline** (`examples/comfyui_enhance/`) — end-to-end
  DAZ Studio → ComfyUI img2img pipeline: captures the viewport, uploads to
  ComfyUI, queues an SDXL img2img workflow, streams progress, and saves the
  enhanced result. Includes `--checkpoint`, `--dry-run`, and `--no-watch` flags.
- **Body measurements — 19 new measurements** in
  `docs/examples/body_measurements.py` for G8, G8.1, and G9 figures:
  - *9 vertical lengths:* total height, inseam, torso length, arm length,
    thigh, shin, forearm, upper arm, head height.
  - *10 circumferences:* neck, chest, underbust, waist, high hip, hip, thigh,
    knee, calf, ankle.
  - *2 breadths:* shoulder width, across-back and across-chest.
  - Pass `--figure-type G9F` (or `G8F`, `G9M`, etc.) to force calibration when
    the scene label lacks a gender keyword.
- **Jupyter notebook** (`notebooks/dazpy_intro.ipynb`) — interactive dazpy
  exploration against a live DAZ Studio instance. Launch with `./notebook.sh`
  (macOS/Linux) or `.\notebook.ps1` (Windows). Sections: Quick Connect → Scene
  Info → Move/Rotate Nodes → Render → API Browser → Jupyter Introspection →
  ipywidgets Bone Rotator → Morph/Property Explorer → Scene Tree Pretty-Printer.
- **PyPI publishing** — `dazpy` is now published to PyPI automatically on each
  tagged release via OIDC (no stored API keys).

### Fixed

- Fixed hang on server stop: listener thread is now joined before the
  `httplib::Server` object is destroyed, preventing a crash/deadlock when
  toggling the server off while requests are in flight.
- Fixed body measurement bone name mismatches for G8.1 waist/underbust anchors,
  G9 neck circumference anchor, and G9 shoulder-width bones.
- Fixed 3D sleeve length calculation (was using a 2D projection, underestimating
  sleeve length on posed figures).
- Fixed high-bust anchor placed above the bust peak rather than at the shoulder
  on some G9 figures.

## [2.4.0] - 2026-05-25

### Added

- **`POST /render`** — submit a DAZ Studio render job and receive a `request_id`
  for async tracking. Accepts `width`, `height`, `output_path`, and optional
  per-figure morph overrides (`figure_morphs`).
- **`GET /render/:id/progress`** — Server-Sent Events stream that delivers
  real-time render progress for a job: `stage`, `progress` (0–1), `elapsed_ms`,
  and `output_path` on completion.
- **`POST /render/batch`** — submit multiple render variants in a single request.
  Each variant can override morphs and output path; renders execute sequentially
  on the DAZ Studio main thread.
- **Plugin route registration interface** — companion plugins can register their
  own HTTP routes into the running server via a `DzScriptServerPane` pointer
  published on `qApp`. Supports path parameters (e.g. `/export/:id/status`).
- **`POST /render/:id/cancel`** — cancel a queued or running render job by its
  `request_id`. Returns 400 if the ID belongs to a non-render request, so callers
  get a clear error rather than silently cancelling the wrong job.
- **`dazpy` render API** — `render()`, `render_variants()`, `RenderVariant`, and
  `FigureMorphs` — high-level Python wrappers around the new render endpoints with
  SSE progress streaming and result polling.
- **`RenderResult.request_id`** — the `request_id` is now populated on the result
  returned by `render(..., wait=False)`, enabling cancellation via
  `client.cancel_render(result.request_id)`.
- **`DazClient.cancel_render(request_id)`** — cancel a render job by ID.
- **`DazScene.find_camera_by_label(label)`** and
  **`DazScene.find_light_by_label(label)`** — look up a camera or light by its
  Scene-panel label. `find_camera_by_label` returns the same label string accepted
  by the `camera` parameter of `render()`.
- **`DazScene.undo_last()`** and **`DazScene.redo_last()`** — step the DAZ Studio
  undo stack programmatically (equivalent to Ctrl+Z / Ctrl+Y). Distinct from the
  existing `scene.undo()` context manager, which groups changes into a single step.
- **`docs/examples/vn_render_workflow.py`** — four visual-novel render patterns
  (basic, batch morphs, interleaved scene setup, multi-figure) with full inline
  documentation.
- **`docs/examples/README.md`** — index and usage guide for all example scripts.

### Fixed

- CRT heap mismatch crash when the catch-all route dispatcher forwarded to a
  companion plugin compiled against a different MSVC runtime (`msvcr100` vs
  `ucrtbase`). Route data now flows through `QByteArray`/`QMap<QString,QString>`
  instead of `std::string`.
- Companion plugin routes were silently dropped when the route was registered
  after the server had already started listening.
- Data race in the catch-all dispatcher under concurrent requests.
- Increased job-completion poll timeout to 300 s for long-running export jobs.

## [2.3.0] - 2026-05-21

### Added

- **`GET /scene/events`** — Server-Sent Events stream that delivers real-time
  DAZ Studio scene-change notifications to connected clients.  Supported event
  categories: `node`, `skeleton`, `light`, `camera`, `selection`, `scene`,
  `time`, `render`.  Use the optional `?filter=` query parameter to subscribe
  to a subset of categories.
- **`SceneEventBroker`** — internal Qt class that connects to all `DzScene`
  signals and dispatches JSON-serialized events to per-client queues.
  High-frequency signals (`timeChanging`, `nodeSelectionListChanged`) are
  debounced (150 ms / 50 ms) to prevent flooding during playback or
  multi-select operations.
- **Keepalive comments** — a `:keepalive` SSE comment is sent every 3 seconds
  of idle time so clients can reliably detect disconnects.

## [2.2.0] - 2026-05-20

### Added

- **`dazpy._pose` — `DazPose`** — snapshot and restore full skeleton poses in
  one call.  Supports named save slots, linear interpolation between poses, and
  local/world-space round-tripping.
- **`dazpy._animation` — `DazAnimation`** — read and write keyframe animation
  data.  Covers per-bone rotation/translation tracks, timeline range queries,
  frame stepping, and baking sampled poses to keyframes.
- **`dazpy.math3` — `Vec3`, `Quat`, `BoundingBox`** — lightweight value types
  for 3-D math returned by the SDK (bone positions, bounding volumes, rotations).
- **`DazGeometry.vertex_positions_posed()`** and
  **`DazGeometry.vertex_positions_posed_all()`** — fetch world-space deformed
  vertex positions from the object's cached geometry pipeline (skinning + morphs
  already applied).
- **`docs/examples/scene_to_usd.py`** — export a live DAZ Studio scene to
  Pixar USD.  Captures fully posed mesh vertices, cameras, lights, PBR materials,
  and strand hair as `UsdGeom.BasisCurves`.  Optional `--morphs` flag writes
  blend shapes as `UsdSkel` targets.
- **`docs/examples/bvh_import.py`** — parse a BVH motion-capture file and apply
  each frame to a DAZ skeleton, with automatic bone-name mapping.
- **`docs/examples/bvh_discover.py`** — inspect a loaded DAZ figure and print
  its bone hierarchy to help build BVH-to-DAZ bone maps.
- **`docs/examples/bvh_bone_maps.py`** — canonical BVH ↔ DAZ bone-name tables
  for Genesis 8 / Genesis 9; importable by other scripts.
- **`docs/examples/animation_mixing.py`** — blend two stored poses at a
  configurable weight and apply the result to a live figure.
- **`docs/examples/batch_operations.py`** — run a sequence of scene mutations
  (morph dials, material swaps, camera moves) as a single batched HTTP request.
- **`docs/examples/geometry_analysis.py`** — query mesh vertex count, bounding
  box, and posed vertex positions for a named figure.
- **`docs/examples/keyframe_baking.py`** — sample a figure's pose at every frame
  and write explicit rotation keyframes, replacing any procedural animation.
- **API docs** — new Sphinx pages for `DazPose`, `DazAnimation`, `Vec3`, `Quat`,
  and `BoundingBox`; updated `docs/api/index.rst` toctree.
- **Test suite** — `tests_dazpy.py` (unit) and `tests_dazpy_integration.py`
  (integration, requires a live DAZ Studio instance).
- **`__main__` guards and `--help`** — every script in `docs/examples/` now has
  an `if __name__ == "__main__":` guard and an argparse `--help` entry, making
  the examples safe to import as modules and self-documenting at the command line.

---

## [2.1.0] - 2026-05-15

### Added

- **`webcam_expression_mirror.py`** — live webcam expression mirroring example.
  Streams MediaPipe face landmarks to a Genesis 9 figure's FACS morph controls
  at up to 10 fps.  Features EMA smoothing, a live AU bar chart overlay,
  headless (`--no-preview`) mode, and automatic morph reset on exit.
- **`include/JsonStd.h`** — header-only `JsonStd` namespace consolidating all
  `std::string` JSON helpers (`escape`, `variantToJson`, `msecToIso`,
  `currentTime`, `qstrToStd`).  Eliminates five copies of identical helper
  functions spread across `AsyncRequestManager`, `DzScriptServerPane`,
  `RequestHandlers`, `IPWhitelistService`, and `RequestValidator`.

### Fixed

- **`dazpy.__version__`** was hardcoded to `"0.1.0"` regardless of the
  installed package version.  Now correctly returns `"2.1.0"`.

---

## [2.0.0] - 2026-05-14

### Summary

v2.0 is a complete internal rewrite of the plugin. The external HTTP API is
fully backward-compatible with v1.x; only the plugin internals were overhauled.

### Architecture

- **Extracted `AuthenticationService`** — token load, validation, and
  regeneration moved out of the main pane class
- **Extracted `RateLimiterService`** — per-IP sliding-window rate limiting as
  a standalone, thread-safe component
- **Extracted `IPWhitelistService`** — exact-match IP filtering with
  mutex-protected state
- **Extracted `MetricsCollector`** — uptime, counters, and success rate in one
  place
- **`AsyncRequestManager` subsystem** — dedicated class for the full async
  request lifecycle (queue, status, result, cancellation, TTL cleanup)
- **Request handler architecture** — `RequestContext`, `RequestValidator`, and
  `RequestProcessor` replace the monolithic dispatch code in `DzScriptServerPane`
- **Settings management** — `ServerSettings` / `ServerConfig` centralise all
  defaults, ranges, and QSettings keys; eliminates magic numbers throughout

### Fixed

- **Active-request race condition** — `m_nActiveRequests` is now atomically
  incremented/decremented under `QMutex`; concurrent HTTP threads could
  previously bypass the concurrency limit
- **DzScript memory safety** — `DzScript` objects are now destroyed on the
  main Qt thread via `Qt::BlockingQueuedConnection`; previously raw
  `delete` could be called from HTTP threads, violating Qt object-tree rules
- **`killRender()` threading** — cancel signal now routes through the main
  thread instead of being called directly from an HTTP thread
- **Signal/slot leak on error paths** — `onMessagePosted` connections are
  always disconnected even when early-return paths fire

### Testing

- 72-test Python integration suite (`tests.py`)
- Performance benchmark suite (`test-performance.py`) with `--quick` mode
  for CI
- Windows/macOS cross-compilation verified in CI

---

## [1.3.0] - 2026-02-10

### Added

- **Async execution** — `POST /execute/async`, `POST /scripts/:id/async`,
  `GET /requests/:id/status`, `GET /requests/:id/result`, `DELETE /requests/:id`,
  `GET /requests`
- Long-poll support via `GET /requests/:id/result?wait=true`
- Automatic TTL cleanup: completed/failed/cancelled requests purged after 1 hour

---

## [1.2.0] - 2025-11-20

### Added

- **IP Whitelist** — exact-match per-IP access control (HTTP 403 on block)
- **Per-IP rate limiting** — sliding window algorithm; configurable max
  requests and time window (HTTP 429 on violation)
- **Script Registry** — `POST /scripts/register`, `GET /scripts`,
  `POST /scripts/:id/execute`, `DELETE /scripts/:id`; in-memory, session-scoped
- Active request counter in UI ("Active Requests: X / Y")
- Auto-start option: start server when pane opens
- Configurable concurrent request limit, body size limit, script length limit
- All settings persisted via QSettings

### Changed

- Improved error messages with actionable guidance
- JavaScript/Node.js and PowerShell client examples added

---

## [1.1.0] - 2025-09-05

### Added

- **`GET /metrics`** — total requests, success/failure counts, success rate,
  uptime; counters persist across restarts via QSettings
- **`GET /health`** — structured health check for load balancers and uptime
  monitors
- Request IDs (8-character UUID) included in every response and log entry

---

## [1.0.0] - 2025-06-01

### Added

- Initial release
- `POST /execute` — inline script (`script`) and file-based (`scriptFile`)
  execution with optional `args`
- `GET /status` — liveness check
- Token-based authentication (`X-API-Token` / `Authorization: Bearer`)
- Token auto-generated via OS crypto APIs; stored at
  `~/.daz3d/dazscriptserver_token.txt` with `chmod 600` on Unix/macOS
- Configurable host, port, and execution timeout
- Output capture (`print()` → `output[]` array)
- Request log with timestamps, IP, status, duration, and request ID
- Windows (`CryptoAPI`) and macOS/Linux (`/dev/urandom`) secure RNG
- `JsonBuilder` — type-safe JSON construction with auto-escaping
