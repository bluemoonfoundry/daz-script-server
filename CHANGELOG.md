# Changelog

All notable changes to DazScript Server are documented here.

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
