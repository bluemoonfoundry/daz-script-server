# Changelog

All notable changes to DazScript Server are documented here.

## [Unreleased]

### Added

- **daz-ts:** `MIN_SERVER_VERSION` (2.11, the oldest plugin daz-ts needs)
  and `DazClient.checkServerVersion()`, which reads `GET /status` and returns
  a `VersionCheck` (`compatible`, upgrade `message`). Unlike dazpy, daz-ts
  never checks on its own; call it when you want to know.
- `SECURITY.md` (supported versions, private vulnerability reporting, scope)
  and a docs index at `docs/README.md`. Plans for shipped features moved to
  `docs/superpowers/plans/archive/`.
- **daz-ts on npm:** the package is now `@bluemoonfoundry/daz-ts`
  (`npm install @bluemoonfoundry/daz-ts`; imports change from `"daz-ts"`).
  It has its own release train: a `daz-ts-v<version>` tag publishes it from
  `publish-daz-ts.yml` via npm trusted publishing with provenance.
  `scripts/check_daz_ts_version.py` keeps the tag, `package.json` and
  `package-lock.json` in step. The release tarball is now
  `bluemoonfoundry-daz-ts-*.tgz`.

### Changed

- **dazpy / daz-ts:** the hug recipe's arms now wrap around the partner
  instead of reaching for the front of its shoulder. Hand targets gain
  `wrap` (`HandTarget(..., wrap=True)` / `{ wrap: true }`): the arm passes
  two waypoints beside the partner's ribs, under its arm, then stops on the
  upper back. A hand-only pass turns the fingertips across the back toward
  the spine, bending at most `WRAP_HAND_LIMIT` (70 degrees) per axis. A
  wrapped partner is staged at `WRAP_SEPARATION` (26 cm, origin to origin),
  inside the 30 cm reach minimum. Live DS6, 2 x Genesis 9: both arms
  converge (39.4 -> 0.13 cm). Each wrist ends 10.8 cm behind the partner's
  spine, each elbow 18 cm out to the side (outside the ribs), and the
  fingertips 1.2 cm from the spine. `alignSingleLimbTarget` takes an
  explicit `chain` option.
- **dazpy / daz-ts:** the face_each_other recipe now turns the second actor
  in place to face the first figure's origin (or, when both stand at the same
  spot, to face back along the first figure's heading). It moves nobody and
  runs no IK. Before, it validated but left both figures as they were. The
  pose patch's `figureYawDegrees` / `figure_yaw_degrees` carries the turn.
- **dazpy / daz-ts:** the hug, kiss, handshake and fight interaction recipes
  now turn the second actor to face the first before staging and place it
  straight in front, at a distance the limbs can reach (0.85 of an arm's
  reach from the shoulder joint, 0.95 of a leg's from the hip). Before, staging only moved figures sideways, so in a hug or kiss
  the second actor's hand had to reach behind its own body. Handshake hands
  now aim at one meeting point between the two figures. In the kiss recipe,
  B's hand now goes to A's opposite shoulder (`r_shoulder` for B's
  `l_hand`), not the cross-body one. The pose patch has
  a new `figureYawDegrees` / `figure_yaw_degrees` field. Applying it needs a
  skeleton with `localEuler`/`setRotation` (`local_euler`/`set_rotation`),
  which `DazSkeleton` has. Touch and sit staging is unchanged (y1td).

### Fixed

- **dazpy / daz-ts:** `DazViewport.capture` failed on Studio 6 ("Property
  'updateGL' ... is not a function"): Qt6's `Dz3DViewport` has no
  `updateGL()`. The capture scripts now call `update()` when `updateGL()` is
  missing.
- **dazpy / daz-ts:** `AuthenticationError` (HTTP 401/403) now keeps the
  server's `ErrorResponse` fields: `status_code`/`error_code`/`detail`/
  `retryable` in dazpy, `statusCode`/`errorCode`/`detail`/`retryable` in
  daz-ts (e.g. `AUTH_INVALID_TOKEN`, `IP_NOT_WHITELISTED`). The message uses
  the server's `error` text when the body is JSON.

## [2.15.0] - 2026-11-19

dazpy-only release. The plugin binaries are rebuilt with the new version
number; no plugin code changed, and plugin 2.12.x users need not upgrade.
2.14.0 was tagged in this changelog but never published to PyPI or GitHub
Releases; its changes ship in this release.

### Added

- **daz-ts 0.1.0**, a TypeScript/Node.js (>= 18) SDK in `daz-ts/`: the
  counterpart to dazpy, at parity with its client, batching, scene-graph
  proxies, rendering, pose/animation/scene-state capture, and the poses,
  materials, lighting and cinematics helpers. Interaction/IK posing is not
  ported yet. daz-ts versions independently of the plugin and dazpy. It is
  built and unit-tested in CI and attached to GitHub releases as
  `daz-ts-*.tgz`; it is not on the npm registry yet.
- **`dazpy.shots`**: typed, JSON-serialisable `Shot`, `Sequence` and
  `CoveragePlan` models (shot size, angle, lens, composition, orbit/keyframed
  movement, focus pulls, blocking and gaze beats, lighting continuity,
  storyboard metadata, render outputs) and `apply_shot()`. The
  `dazpy.cinematics` builders now run through it (same API and behaviour;
  each gains `to_shot()`). Static shots and coverage plans convert to scene
  recipe cameras and shots (`Shot.to_recipe()`,
  `CoveragePlan.merge_into_recipe()`). New `DazCamera.set_focal_distance_at_frame()`
  / `clear_focal_distance_keys()` for focus pulls.
- **`dazpy.shot_library`**: common cinematic shots on top of `dazpy.shots` --
  establishing, master, two-shot, clean singles, insert, POV, over-the-shoulder
  and shot/reverse-shot pairs; a `LineOfAction` that keeps every camera on one
  side of the 180-degree line (eyelines match across cuts) with `check_axis`,
  `check_thirty_degree` and `check_plan`; headroom and lead-room composition;
  push-in/pull-out, arc and dolly/truck/pedestal/crane/pan/tilt/handheld moves;
  rack focus and depth-of-field limits; single-actor coverage presets,
  two-actor dialogue coverage and `conversation()` cutting dialogue beats; consistent `shot_name()` ids;
  `compose_aim()` (thirds / golden section), `look_rotation()` with dutch roll,
  and camera-pose helpers that accept `DazNode.rotation`'s quaternion.
  `apply_shot()` gains `clear_keys=False` so successive moves on one camera chain.
- **Scene recipe cameras** (additive, still `recipe_version` 1): `shot_type`
  accepts `extreme_wide`, `wide`, `medium_wide`, `medium_close_up` and
  `extreme_close_up` as well; new `angle` (`eye_level`, `high`, `low`,
  `birds_eye`, `worms_eye`; exclusive with `elevation_deg`) and `composition`
  (`center`, `left_third`, `right_third`) for framing cameras.

## [2.14.0] - 2026-11-18

dazpy-only release. The plugin binaries are rebuilt with the new version
number; no plugin code changed, and plugin 2.12.x users need not upgrade.

### Fixed

- **`DazScene.undo_last()` / `redo_last()`** called `App.getUndoStack()`,
  which DazScript doesn't have, so both failed. They now use the global
  `UndoStack`.
- **Bone rotation order was always `""`.** `DazBone.rotation_order`,
  `DazSkeleton.bone_metadata()` and `DazScene.scene_snapshot()` returned the
  `DzRotationOrder` object, which serializes to an empty string. They now
  return the real per-bone order (e.g. `"YZX"`, `"XZY"`). Code that reads
  `rotation_order`, including the interaction/IK helpers, now gets real values.

### Added

- `DazScene.run_dforce_simulation(memorized_pose=...)` sets the active
  simulation engine's `startFromMemorizedPose` global setting before
  simulating. It mirrors the "Start Bulge from Memorized Pose" checkbox in
  DAZ Studio's Simulation Settings pane.
- `DazSkeleton.bone_metadata()` entries carry `rest_orientation` (the bone's
  rest quaternion, `x/y/z/w`) and `axis_limits` (live `min`/`max` per rotation
  axis).

## [2.13.0] - 2026-11-16

dazpy-only release. The plugin binaries are rebuilt with the new version
number; no plugin code changed, and plugin 2.12.x users need not upgrade.

### Changed

- **dazpy plugin version check.** The check now compares the plugin against
  `dazpy.MIN_SERVER_VERSION` (the oldest plugin this dazpy needs, currently
  2.12) instead of dazpy's own version, so a dazpy-only release no longer tells
  users to upgrade an unchanged plugin. It re-checks after a dropped connection
  and when the plugin's `X-Server-Instance-Id` changes (Studio restarted), and a
  check that couldn't reach Studio no longer counts as done. The warning names
  the plugin's address and puts upgrading the plugin first, and is emitted once
  per running plugin.

### Added

- `dazpy.VersionCheck` and `client.version_check`: the latest check's plugin
  and dazpy versions, the minimum, the URL checked, `compatible`, and an upgrade
  `message`.
- `on_version_check=` on `DazClient` and `AsyncDazClient`: a callback receiving
  every completed check, so apps (such as an MCP server) can show it where
  their users look.
- `dazpy.MIN_SERVER_VERSION`.

## [2.12.0] - 2026-11-15

### Added

- **Scene recipes (5d6f.18).** New `dazpy.recipe` module: `validate`, `plan`,
  `apply`, `observe` and `render` over a versioned JSON scene description
  (`schemas/scene-recipe.v1.schema.json`, also shipped as dazpy package data and
  returned by `recipe_schema()`). Apply is incremental and three-way: it
  compares the recipe, the last-applied state and the live scene, keeps hand
  tweaks with a `hand_tweak_kept` warning, and reports conflicts
  (`on_conflict="ask" | "recipe_wins" | "scene_wins"`, per-path `resolutions`).
  A failed apply rolls back by compensation. Sync only; no `dazpy.aio`
  variants. Includes `docs/examples/recipes/g9-portrait.json`, live tests
  (`tests/test_recipe_live.py`) and `docs/scene_recipes.rst`.

- **`DazClient.waiting_out_busy(max_wait)`.** A context manager: within it,
  this client's calls on the current thread (including those the node and
  scene proxies make) retry a busy Studio as if passed `retry_on_busy=True`.
  Studio 6 reports busy briefly after a load or clear; the recipe functions
  use it (up to 120 s per call).

### Fixed

- **`DazScene.load` now merges, as documented.** It passed load mode `0`
  which Studio treats as open (it replaced the current scene); it now passes
  `DzScene.MergeFile`. Callers that relied on it clearing the scene should
  clear first.

## [2.11.0] - 2026-11-15

### Added

- **Companion-plugin discovery registry.** Plugins can name themselves with
  `registerCompanionPlugin(name, version, description)` and attribute routes
  with a 5th `pluginName` argument to `registerPluginRoute()` (the 4-argument
  form still works). `GET /capabilities` adds `companion_plugins`: each plugin's
  name, version, description and routes; unattributed routes are grouped by
  handler class with `"registered": false`. `plugin_routes` entries gain
  `plugin`. The parity check's hand-kept route list moved to
  `companion_plugins.json`, and `check_openapi_parity.py --live URL` checks a
  running server's companion routes against it and `openapi.yaml`.

- **Artifact thumbnails.** `GET /artifacts/{id}/{artifact_id}?thumbnail=<px>`
  returns a scaled PNG (or JPEG with `format=jpeg`) of an image artifact: the
  longest edge fits in 16-1024 px, the aspect ratio is kept, and nothing is
  upscaled. The HTTP worker reads the file. Decoding and scaling run on the
  main thread through a queued call with a 10 s timeout, and the server
  answers `503 STUDIO_BUSY` while Studio is busy, so no request hangs behind
  a render. Results are cached per file size/mtime (`X-Thumbnail-Cache`).
  Artifacts that can't be thumbnailed return the new `422
  THUMBNAIL_UNSUPPORTED`. `GET /artifacts/{id}` entries gain
  `thumbnail_supported`. `/capabilities` adds `features.artifact_thumbnails`,
  `thumbnail_source_formats` and `limits.thumbnail_min_px` / `_max_px` /
  `_max_source_mb`. dazpy adds `get_artifact_thumbnail()` on `DazClient` and
  `AsyncDazClient`.

- **Job liveness and progress metadata.** Status, result and `GET /requests`
  records now carry `progress_supported`, `progress_source`
  (`frames` / `report` / `none`), `last_activity_at` and, while the job is
  active, `idle_ms`. Activity comes from job start, frame boundaries,
  report-file writes (so `{"type":"heartbeat"}` keeps a long step alive),
  printed lines on Studio 4, and completion. New `/capabilities` flags:
  `job_activity`, `animation_frame_progress`.

- **Per-frame progress for `/render/animation` on Studio 6.** Studio 6 shims
  `print()`, so the `[DAZPY_FRAME]` marker never reached the server and
  animation renders reported no progress until they finished. The animation
  script now also writes a server-owned frame report that polling workers read
  live. On both SDKs `observation.progress` reports frame N of M (`frame`,
  `current`, `total`, `phase`, `message`). The SSE frame events are still
  Studio 4 only.

- **Live smoke-test matrix: `tests/smoke_live.py`.** A scoped check against a
  running DAZ Studio covering API basics, async jobs, both SSE streams, one
  64×64 render per engine (Iray / Filament / viewport), and optionally the
  vangard-daz-mcp tools. Render settings are snapshotted, read back after every
  change (job readback plus an independent live read), and restored. `--record`
  writes a per-release × SDK report to `docs/smoke-results/`. A
  `workflow_dispatch` workflow (`live-smoke.yml`) runs it on a self-hosted
  runner. See `docs/LIVE_SMOKE.md`.

- **dazpy covers every documented operation.** `DazClient` and
  `AsyncDazClient` add `list_scripts()` (`GET /scripts`),
  `delete_script(name, missing_ok=False)` (`DELETE /scripts/{id}`) and
  `export_geometry_frames(frames, ...)` (`POST /geometry/frames`), which decodes
  the binary DZGF payload into a `GeometryFrames` object (`frame(n)`,
  `bone(name)`, `raw` bytes for numpy). `parse_geometry_frames()` is exported
  for callers that fetch the payload themselves.

- **Artifact downloads: `GET /artifacts/{id}` and
  `GET /artifacts/{id}/{artifact_id}`.** Clients no longer need to share a
  filesystem with DAZ Studio to fetch job outputs. Only files the job declared
  can be downloaded: `reportFile` outputs, plus the image(s) a render job wrote,
  which now also appear in its output manifest. Manifest entries gain a stable
  `artifact_id` and a `url`. Downloads support byte ranges (206 / 416) and
  `HEAD`, and go through the IP whitelist and auth. New error codes:
  `404 ARTIFACT_NOT_FOUND` and `410 ARTIFACT_UNAVAILABLE`. dazpy adds
  `list_artifacts()`, `download_artifact()` and `download_artifacts()` to
  `DazClient` and `AsyncDazClient`.

- **`GET /capabilities` discovery endpoint.** Returns the plugin, DAZ Studio,
  SDK and Qt versions, every route (including companion-plugin routes), feature
  flags, the current body/script/batch/animation/queue limits, rate limit and
  security settings, and the render engines read live from `DzRenderMgr`.
  `compatibility_hash` changes only when routes, feature flags or the schema
  change. While DAZ Studio is busy the server returns its last snapshot instead
  of 503. dazpy adds `DazClient.capabilities()` and
  `AsyncDazClient.capabilities()`.

- **`Idempotency-Key` on job submission.** `/execute/async`,
  `/scripts/{id}/async`, `/render`, `/render/batch` and `/render/animation`
  accept the header. A retry with the same route, body and key within an hour
  returns the original response (`idempotent_replay: true`) instead of queueing
  a second job. Reusing a key with a different body returns
  `422 IDEMPOTENCY_KEY_REUSED`. A retry while the first request is still being
  handled returns `409 IDEMPOTENCY_KEY_IN_FLIGHT`.

- **Server identity and correlation IDs.** Every response carries an
  `X-Server-Instance-Id` header, a new random ID on each server start. It is
  also reported on `/status`, `/health`, `/capabilities` and every job
  response, so clients can detect a restart. Job routes accept
  `X-Correlation-Id` (or generate one) and echo it, and async job records store
  it. `/status`, `/health` and job responses also report `scene_revision`, a
  counter of observed scene changes and executed scripts.

- **Retry safety documented per operation** in the README and `openapi.yaml`.

- dazpy: every `*_submit` method takes `idempotency_key=` and
  `correlation_id=`, and `ServerResponseError` gains `.retryable`.

- **`DazSceneState` restore report and optional full-scene backup.**
  `DazSceneState.apply()` now also returns `skipped` (one
  `{"kind", "name", "reason"}` entry per figure, camera, light or fit target
  deleted since capture), `complete` and `backup`. `restored` and `errors`
  are unchanged, and skipped nodes still appear in `errors`.
  `DazSceneState.capture(scene, backup_path=...)` writes a `save_copy()`
  backup before capturing and keeps the result in `.backup` (round-trips
  through `to_dict()`/`from_dict()`). The README's new "Pose Checkpoints vs.
  Full Scene Backups" section lists what a checkpoint does and does not
  cover.

- **Configurable stuck job timeout.** A new **Stuck Job Timeout** setting under
  Advanced Limits (5–1440 minutes, default 30) sets how long an async job can
  run before it is reported as `stale`. It applies immediately, without
  restarting the server.

- **Daz Studio 6.26 on macOS.** Releases ship
  `libdsp_DazScriptServer-ds6.26-macos.dylib`, built against the 6.26 macOS SDK.
  The single x86_64 build serves both Intel and Apple Silicon Macs, since
  Studio 6 runs under Rosetta 2. The macOS DS6 output now keeps the `lib`
  prefix (`libdsp_DazScriptServer.dylib`), matching the SDK samples
  ([#51](https://github.com/bluemoonfoundry/daz-script-server/issues/51)).

### Changed

- **`GET /render/{id}/progress` streams animation frame events on Studio 6.**
  Studio 6 shims `print()`, so the `[DAZPY_FRAME]` marker never reached the
  stream there. The SSE handler now polls the job's server-owned frame report,
  every 0.5 s, the same source job status uses, and emits `progress` events
  (`percent`, `frame`, `total_frames`) as Studio 4 already did. Frames faster
  than 0.5 s are merged into an event for the latest frame. Frame events
  are never duplicated or reordered, and a subscriber that joins mid-render
  first gets the latest frame. The OpenAPI example payloads for this stream now
  match what the server sends.

- **`DazSceneState.apply()` treats only `NodeNotFoundError` as a missing
  skeleton.** Any other lookup failure is now reported as
  `Failed to look up skeleton <name>: …` in `errors` instead of
  `Skeleton not found`, and is not listed in `skipped`.

- **One error format everywhere.** Every failure now returns
  `{"success": false, "error_code", "error", "retryable", "detail"?}`. This
  replaces the bare `{"success": false, "error": "…"}` bodies from unknown
  request IDs, render-cancel misuse, registry deletes and companion-plugin
  404/503 responses. httplib's own empty-body errors (404, 400, 500) get the
  same JSON. Sync and async script failures keep HTTP 200 and now include
  `error_code: "SCRIPT_ERROR"` (or `JOB_CANCELLED` / `JOB_STALE` for jobs).
  New codes: `REQUEST_NOT_FOUND`, `ROUTE_NOT_FOUND`, `NOT_A_RENDER_REQUEST`,
  `REQUEST_ALREADY_FINISHED`, `BAD_REQUEST`, `IDEMPOTENCY_KEY_IN_FLIGHT`,
  `IDEMPOTENCY_KEY_REUSED`, `SCRIPT_ERROR`, `JOB_CANCELLED`, `JOB_STALE`. The
  `error` text for unknown request IDs changed, so clients should branch on
  `error_code` instead.

- `/capabilities` `compatibility_hash` changes, because new feature flags
  were added (`idempotency_key`, `correlation_id`, `server_instance_id`,
  `scene_revision`, `error_envelope`).

- **dazpy finds Iray render settings by class, not by position.** Iray
  Canvases and the HDRI/environment helpers used to read
  `getRenderElementObjects()[1]` and `[3]`. They now look for
  `DzIrayPropertyHolder` and `DzEnvironmentNode` by class, then by label.
  Only if neither matches do they fall back to the old index, and then they
  raise a `RuntimeWarning`. Checked live on DAZ Studio 6.26. Those groups only
  exist while the render type is Software (Iray); in viewport mode they are
  absent, the canvas/environment calls return `None` or do nothing as before,
  and the error messages now say to switch to Iray.

- **Cancelling a running job no longer claims it was cancelled.** A running
  script can't be interrupted, so cancelling it now returns
  `cancel_requested` (render jobs also get `killRender()`). When the script
  returns, the status becomes what really happened: `cancelled` (render
  aborted), `completed_after_cancel_request` (result kept) or `failed`. Jobs
  that run past the stuck job timeout become `stale` instead of a permanent
  `failed`, and change to `completed_after_stale` if they finish later.
  `cancel_requested_at` and `stale_at` stay in responses. Clients that treated
  the cancel response's `"cancelled"` as final should poll for the outcome.

### Fixed

- **Request body limit on every route.** The configured Max Request Body Size
  was only checked on `POST /execute`, after httplib had already buffered up to
  100 MB. The server now passes the limit to httplib, which stops reading at the
  cap and returns 413 `BODY_TOO_LARGE` on every route.

- **IP whitelist and rate limiter on every authenticated route.**
  `/scripts/register`, `DELETE /scripts/:id`, `/requests/*`,
  `/render/:id/cancel`, `/render/:id/progress`, `/scene/save-copy`,
  `/geometry/frames` and `/scene/events` only checked the token. They now run
  the IP whitelist too, and the POST/DELETE routes are rate limited. Polling and
  streaming GETs are not rate limited.

- **Companion-plugin routes now require authentication.** Routes registered via
  `registerPluginRoute()` used to run no checks at all, so they were reachable
  without a token. They now go through the same IP whitelist, token check and
  (for non-GET methods) rate limit and body limit as built-in routes.
  Unregistered paths still return 404.

- **`iray_samples` is applied instead of ignored.** `/render` and
  `/render/batch` accepted `iray_samples` but never used it. It now sets Iray's
  Max Samples for that render only (the previous value is restored afterwards),
  and the job result reports `requested`, `applied`, `previous` and
  `restored`. Invalid values, or `iray_samples` with a viewport or Filament
  engine, return 400; a job whose render isn't actually Iray fails instead of
  rendering at the scene default.

### Removed

- **USD export routes and their dazpy methods**, until the daz-bridge-usd
  companion plugin is ready. `POST /export/usd` and `GET /export/usd/{id}` are
  no longer documented in `openapi.yaml` or declared in
  `companion_plugins.json`, and `export_usd_submit()` /
  `get_usd_export_status()` are gone from `DazClient` and `AsyncDazClient`.

- The `DS6_MACOS_ENABLED` repository variable gate on macOS DS6 release builds.

## [2.10.1] - 2026-11-12

### Added

- dazpy: `DazClient` and `AsyncDazClient` check the server version on their
  first request and emit `ServerVersionWarning` when the plugin's major.minor
  is older than dazpy's (e.g. a Studio 6.25 user on plugin v2.9.3 with a newer
  dazpy). Best-effort and non-blocking; opt out with `check_version=False`.
  New `DazClient.server_version` / `AsyncDazClient.get_server_version()`.

- dazpy: `DazClient` and `AsyncDazClient` now own registered-script
  registration and execution (`register_script`, `execute_registered`,
  `execute_registered_async_submit`), detailed script/render cancellation
  (`cancel_request_detail`), long-poll timeout policy, and generic server-error
  mapping through the new `ServerResponseError`. Status, health, metrics,
  request management, exports, and async SSE streams all use the same typed
  authentication, connection, timeout, busy, and server-response errors, so
  integrations can depend on dazpy instead of duplicating endpoint URLs, wire
  payloads, and error handling. Contributed by @abrady
  ([#38](https://github.com/bluemoonfoundry/daz-script-server/pull/38)).

### Changed

- dazpy: `status()`, `health()`, `metrics()`, `list_requests()`, the request
  status/result calls, and the USD export calls now raise
  `ServerResponseError` (a `DazError`) for any unhandled 4xx/5xx response.
  Previously only 401/403 raised and other error responses were returned as
  plain dicts. 404 on request status/result and USD export status still returns
  `{"status": "not_found"}`.

### Documentation

- README (also the PyPI project page): added "What's New" sections for
  v2.9.1 to v2.10.1, which were missing, so the newest release notes no longer
  stop at v2.9.0. Install instructions now point to PyPI instead of a pinned
  2.9.0 wheel.
- Documented `POST /geometry/frames` (added in 2.9.3) in the README and
  `openapi.yaml`. `openapi.yaml`'s `info.version` was stuck at 2.9.1.

### CI

- `scripts/check_version_consistency.py` checks that the version in
  `pyproject.toml` matches `dazpy/__init__.py`, `docs/conf.py`,
  `include/common_version.h`, `openapi.yaml`, the README badge and newest
  "What's New" section, and the newest CHANGELOG entry. It runs in CI, and
  tagged releases also check the tag against it before publishing to PyPI or
  creating the GitHub release. PyPI publishing uses `skip-existing`, so before
  this a tag without a matching bump appeared to succeed while PyPI kept the
  previous upload and README.

## [2.10.0] - 2026-11-12

**Daz Studio 6 builds now require Studio 6.26.** Studio 6.25 users: stay on
v2.9.3 and `pip install dazpy==2.9.3`. No HTTP API or dazpy API changes.

### Fixed

- Emit the SDK-provided version tag for Windows Studio 6 plugins when the
  SDK supports it. Rebuilding with SDK 6.26.2026.27900 or newer resolves the
  "it has no SDK version tag" loader rejection in Studio 6.26
  ([bluemoonfoundry/daz-script-server#45](https://github.com/bluemoonfoundry/daz-script-server/issues/45)).

### Changed

- **Daz Studio 6 builds now target Studio 6.26 only.** Studio 6.26 loads only
  plugins built against SDK 6.26.2026.27900, and Studio 6.25 rejects plugins
  built against newer SDKs, so no single DS6 binary can serve both. Release
  assets are renamed `dsp_DazScriptServer-ds6.26-*`. **Studio 6.25 users should
  stay on v2.9.3**, the last 6.25-compatible release, and pin the client with
  `pip install dazpy==2.9.3` (dazpy does not yet check the server version).
- CI fails DS6 builds whose plugin lacks a `DzPluginSDKVersionTag` matching the
  SDK it was compiled against (`scripts/check_sdk_tag.py`).
- macOS DS6 release builds are paused until the 6.26 macOS SDK is available
  (re-enable with the `DS6_MACOS_ENABLED` repository variable).

## [2.9.3] - 2026-10-21

### Structured async job observation

Async script submissions may name a per-job `reportFile`. The server truncates
it at submission, incrementally ingests its JSONL events while Daz's main thread
is occupied, and exposes one `observation` record through status and result:
structured progress, the most recent 100 log entries with truncation metadata,
and a deduplicated output manifest. Request lists carry a bounded observation
summary. Both `DazClient` and `AsyncDazClient` accept `report_file=` for inline
and file-backed async jobs. Live report ingestion is available on Studio 6;
Studio 4 parses the final report on the main thread after execution returns.

### `POST /geometry/frames` — binary deformed-vertex export

Returns the deformed figure mesh (optionally a vertex/surface subset) plus
world-space bone origins for a list of frames as one `application/octet-stream`
payload. Only the figure is re-evaluated per frame, not the whole scene; ~9ms
per frame on a dressed Genesis 8 figure vs. ~232ms/frame for the equivalent
DazScript loop, with bit-identical values.

### Fixed

- DS6 leaves `mgr[renderFinished(bool)]` undefined, so a chained `.connect()`
  threw before `doRender()` could run. The signal is now bound only if it
  exists; otherwise a completed `doRender()` is treated as success.
- Plugin-route responses were sent through the `const char*` overload of
  `set_content()`, which calls `strlen()` internally and silently truncated
  any response body at its first NUL byte. The body length is now passed
  explicitly.

## [2.9.2] - 2026-08-21

### dazpy script-call batching

`Batch` gains `add_operation()`/`add_prelude()` with configurable size
limits, plus `DazElement.snapshot()`/`set_properties()`,
`DazNode.set_transform()`, `DazSkeleton.set_state()`, a single-call
`zero_figure()` default path, and one-request async batch submission via
`execute_batch_async()`. Main-thread wait time is now exposed in
`GET /metrics`. See `docs/api/batch.rst` and `docs/quickstart.rst` for
usage and the whole-batch failure/no-rollback semantics.

### Fixed

`DazScene.find_skeleton()` now retries `Scene.getSkeletonList()` on a
transient miss instead of immediately raising `NodeNotFoundError` -- the
lookup has been observed to momentarily omit a skeleton that is actually
present, under load from a burst of other main-thread script calls.

## [2.9.1] - 2026-08-20

### Async script-file jobs

`POST /execute/async` now implements the `scriptFile` form already described
by the API schema. File-backed requests keep the path in the queue and call
`DzScript::loadFromFile()` when execution starts, preserving
`getScriptFileName()` and relative `include()` behavior instead of flattening
the file to inline source. `DazClient` and `AsyncDazClient` expose this as
`execute_file_async_submit()`; the existing status/result/list/cancel methods
manage the returned request id.

On Studio 6, the result-capturing `evaluate()` wrapper now forwards the
request's explicit filename; Studio otherwise treats the wrapper as anonymous
source and returns an empty `getScriptFileName()`. Script enqueue
handlers also submit directly from the HTTP worker into the mutex-protected
queue on Studio 6, so a new async request returns while Daz's main thread is
occupied and can be cancelled before it starts. Studio 4 retains main-thread
submission because its JSON fallback uses `QScriptEngine`. UI logging remains
queued to the main thread.

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
Plan: `docs/superpowers/plans/archive/2026-07-22-studio-busy-handling.md`.

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

## [2.5.0] - 2026-06-11

### Added

- **Interaction posing (dazpy):** places two figures together (seated,
  touching, kissing, combat stances). `build_sit_recipe`, `build_touch_recipe`,
  `build_kiss_recipe` and `build_fight_recipe` take two figure labels and
  return a JSON-serialisable `InteractionRecipe`, applied with
  `DazScene.apply_interaction_recipe()`.
- **IK limb alignment (dazpy):** `align_hand_target()` / `align_foot_target()`
  move a hand or foot to a world-space target with an iterative Jacobian
  solver and report `converged` and `final_error`.
- **Bulk scene snapshot (dazpy):** `DazScene.scene_snapshot()` returns every
  skeleton's bone world positions in one HTTP call;
  `build_rig_profiles_from_snapshot()` builds rig data from it.

### Fixed

- Body measurements: torso loop selection is centroid-weighted, so arm
  cross-sections no longer inflate A-pose chest measurements (~70 cm
  overestimate). The fallback for unlabelled figures rejects outlier slices,
  and `--figure-type G9F` (or `G9M`, `G8F`, ...) forces a calibration entry.

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
