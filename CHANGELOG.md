# Changelog

All notable changes to DazScript Server are documented here.

## [2.7.0] - Unreleased

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

### Fixed

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
