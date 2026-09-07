# daz-ts

TypeScript SDK for [DazScriptServer](../README.md), the HTTP server plugin
that embeds an HTTP API inside DAZ Studio for remotely executing DazScript
code. `daz-ts` is the Node.js/TypeScript counterpart to
[`dazpy`](../dazpy), the mature Python SDK — same wire protocol, same
server, a single `DazClient` class (no sync/async split; `async`/`await`
covers both). Phase 1 shipped the client core (`execute`, async job
submission/polling, batching, render/USD submission, SSE plumbing) plus a
dependency-free `math3` module. Phase 2 (below) adds the scene-graph proxy
layer (nodes, materials, skeletons, etc.).

## Install

`daz-ts` is not published to the public npm registry. Install it as a git
dependency (npm runs the package's `prepare` script automatically, which
builds `dist/`):

```bash
npm install github:<owner>/<repo>#<branch-or-tag> --workspace-path daz-ts
# or, pointing at a subdirectory of this monorepo:
npm install "github:<owner>/<repo>#<ref>:daz-ts"
```

Alternatively, download the `daz-ts-*.tgz` tarball attached to a
[GitHub release](../../../releases) and install it directly:

```bash
npm install ./daz-ts-0.1.0.tgz
```

Requires Node.js >= 18 (for built-in `fetch`/`AbortController`).

## Auth

Same convention as `dazpy`: requests carry an `X-API-Token` header. By
default, `DazClient` auto-loads the token from
`~/.daz3d/dazscriptserver_token.txt` (the file DazScriptServer writes on
first run). You can also pass a token explicitly, or pass `token: ""` to
disable authentication (only if the server has auth disabled too):

```ts
import { DazClient } from "daz-ts";

const client = new DazClient(); // auto-loads token from ~/.daz3d/...
const explicit = new DazClient({ token: "your-token-here" });
const noAuth = new DazClient({ token: "" });
```

`DazClientOptions` also accepts `host` (default `"127.0.0.1"`), `port`
(default `18811`), and `timeoutMs` (default `30000`).

## Usage

### `DazClient.execute()`

Run a DazScript string synchronously and get back its result, captured
console output, and timing:

```ts
import { DazClient } from "daz-ts";

const client = new DazClient();

const result = await client.execute("2 + 2;");
console.log(result.value); // 4
console.log(result.output); // string[] of captured log lines
console.log(result.durationMs);
```

Pass a JSON-serializable `args` value as the script's `getArguments()[0]`:

```ts
await client.execute("var n = getArguments()[0].count; n * 2;", { count: 21 });
```

Script errors and busy/authentication failures throw typed exceptions
(`ScriptSyntaxError`, `ScriptRuntimeError`, `StudioBusyError`,
`ConcurrencyLimitError`, `AuthenticationError`, `ConnectionError`,
`DazTimeoutError`, ...) — see `src/exceptions.ts` for the full hierarchy.
Any method that accepts a trailing `{ retryOnBusy, maxWait }` option
(`RetryOptions`) will transparently retry with linear backoff on
`StudioBusyError`/`ConcurrencyLimitError` instead of throwing immediately:

```ts
await client.execute("doSomethingSlow();", undefined, { retryOnBusy: true, maxWait: 30 });
```

### `Batch`

Collect multiple operations and run them as a single HTTP round-trip
(one script, one `/execute` call). Execution is **serial**, with **no
parallelism** and **no transactionality** — a failing operation fails the
whole call, and earlier mutations already applied to the live scene are
**not** rolled back:

```ts
import { Batch, DazClient } from "daz-ts";

const client = new DazClient();
const batch = new Batch(client); // options: { maxOperations, maxScriptLength }

const nameFuture = batch.addOperation(["var n = Scene.findNode('Genesis9');"], "n.getLabel()");
const posFuture = batch.addOperation(
  ["var n = Scene.findNode('Genesis9');", "var p = n.getWSPos();"],
  "[p.x, p.y, p.z]",
);

await batch.execute(); // one HTTP call resolves every future

console.log(nameFuture.value, posFuture.value);
```

`addPrelude(preludeKey, lines)` registers a shared setup block emitted once
per unique key, useful when several operations depend on the same lookup.
`DazClient.executeBatchAsync(operations, args?)` submits the same
single-script batch shape to the async endpoint (`/execute/async`) for
long-running batches — poll it like any other async request.

### `executeLong()`

Run a potentially long-running script via the async endpoint, with polling
handled for you:

```ts
import { executeLong } from "daz-ts";

const result = await executeLong(client, "renderEverything();", undefined, {
  timeoutMs: 300_000, // default 120000
  pollIntervalMs: 500, // default 500
});
```

It submits the script with `executeAsyncSubmit`, then long-polls
`/requests/:id/result` until the script completes, fails, is cancelled, or
`timeoutMs` elapses (throwing `AsyncExecutionError` or `DazTimeoutError`
respectively).

## What else is here

- `math3.ts` — dependency-free `Vec3`, `Quat`, `BoundingBox`, `AxisRemap`
  math utilities (no HTTP coupling).
- `ScriptBuilder` — the injection-safety helpers (`escapeString`, `iife`,
  `serializeArg`) used internally to build generated DazScript source; every
  injected string goes through `JSON.stringify`.
- Render/USD-export submission methods (`renderSubmit`, `renderBatchSubmit`,
  `renderAnimationSubmit`, `exportUsdSubmit`, ...) and SSE streaming helpers
  (`streamRenderProgress`, `streamSceneEvents`, `parseSseStream`) on
  `DazClient` — see `src/client.ts` for full signatures.

## Phase 2: Scene Graph Proxies

Phase 2 adds a scene-graph proxy layer on top of the Phase 1 client core —
typed, promise-based wrappers around DAZ Studio's `DzNode`/`DzElement`
object model, ported from `dazpy`'s equivalent classes. Every property
getter/setter is an async method pair (`foo()`/`setFoo()`) rather than a TS
accessor, since accessors can't be `async`.

- `DazElement` — base proxy for any `DzElement`-derived object (locator
  resolution and property get/set by label).
- `DazProperty` — a single node/material property (`value()`, `setValue()`,
  keyframe helpers, and the `rawValue`/`setDoubleValue`/`getNumKeys` gotchas
  ported from dazpy).
- `DazNode`, `NodeIdentifier` — the general scene-node proxy (transforms,
  visibility, selection, parenting, `findProperty()`) and the `{value, kind}`
  shape used to resolve nodes by name or label.
- `DazScene` — the primary entry point: node/camera/light/skeleton
  factories, selection, bulk scene snapshots (`overview()`,
  `sceneSnapshot()`, `allNodeTransforms()`, `nodeTree()`,
  `nodeHierarchy()`), scene I/O (`load()`, `save()`, `exportFbx()`,
  `exportObj()`), playback/frame range, dForce simulation, and
  `undo()`/`UndoGroup` integration.
- `DazSkeleton` — figure proxy: bones, pose/morph values, bone-rotation
  bake, IK-free pose evaluation.
- `DazBone` — a single skeleton bone (rotation, local/world position).
- `DazCamera` — camera-specific node proxy (focal length, FOV, DOF).
- `DazLight` — light-specific node proxy (intensity, color, shadow
  settings).
- `DazMaterial` — a single surface's material properties.
- `DazModifier`, `DazMorph`, `DazDForce` — modifier-stack proxies: general
  modifiers, ERC morphs, and dForce simulation modifiers.
- `DazGeometry` — a node's resolved mesh geometry (vertex positions,
  bounding box, posed vs. unposed).
- `DazViewport` — the active 3D viewport (draw style, size, `capture()`).
- `DazTimeline` — the global timeline (current frame, frame range,
  play/pause).
- `UndoGroup`, `withUndo` — group a series of changes into a single undo
  step; `withUndo(client, label, fn)` is the TS equivalent of dazpy's
  `with scene.undo(label): ...` context manager (TS has no `with`
  statement).

`capture_sprite()` (dazpy's `rembg`-based background removal) and
IK-dependent methods (`DazSkeleton.handToTarget`/`.footToTarget`,
`DazScene.applyInteractionRecipe`) are out of scope for this phase — they
require the Phase 5 IK solver.

See `test/integration/proxies.integration.test.ts` for a live-server
integration suite covering these classes (gated on `DAZ_SERVER_URL`, same
pattern as Phase 1's `client.integration.test.ts`; run with
`DAZ_SERVER_URL=http://127.0.0.1:18811 npm run test:integration`).

See `docs/superpowers/specs/2026-09-06-daz-ts-design.md` (in the repo root)
for the full design spec and phased roadmap.

## Phase 3: Rendering

Phase 3 adds live Render Settings control and high-level render helpers on
top of Phase 1's raw job-queue client methods, ported from `dazpy`'s
`_render.py` and `_render_api(_aio).py`.

- `DazRenderSettings` — talks directly to DAZ Studio's render manager
  (`App.getRenderMgr()`) via `DazClient.execute()`: engine selection
  (`activeEngine()`/`setActiveEngine()`, plus the stricter
  `renderEngineState()`/`setRenderEngine()` pair that requires an exact live
  readback before reporting success), resolution, output path, gamma,
  double-sided rendering, Iray quality (`maxSamples`, `maxTimeSecs`,
  `quality`, `setQualityPreset()`), Iray Canvases (`listCanvases()`,
  `addCanvas()`, `removeCanvas()`, `canvasOutputPaths()`), and `render()` /
  `renderAndWait()`, which drive `DzRenderMgr.doRender()` synchronously and
  resolve from its `renderFinished(bool)` signal rather than trusting
  `doRender()`'s own (undocumented, unreliable-on-cancel) return value.
- `Canvas`, `RenderOutcome` — plain result types for the above. Unlike
  dazpy's `RenderOutcome` (which overrides `__bool__`), TS callers must
  check `.success` explicitly.
- `render()`, `renderVariants()` (in `renderApi.ts`) — high-level helpers
  over the HTTP `/render` and `/render/batch` job-queue endpoints already on
  `DazClient` (`renderSubmit`, `renderBatchSubmit`, `streamRenderProgress`).
  Both wait for completion via the SSE progress stream
  (`GET /render/:id/progress`), falling back to long-poll on
  `/requests/:id/result` if the stream is unavailable or ends without a
  `complete`/`error` event. `renderVariants()` submits every variant in one
  batch request, then awaits each in order, recording a failed variant's
  error without aborting the rest.
- USD export submission/status (`DazClient.exportUsdSubmit`,
  `getUsdExportStatus`) was already ported in Phase 1 alongside the other
  job-queue endpoints — see `src/client.ts`.

`DazRenderSettings`'s environment-map/property methods
(`getEnvironmentProperty`, `setEnvironmentProperty`,
`setEnvironmentPropertyFromString`, `setEnvironmentMap`) are exposed
primarily for the Phase 4 `lighting.ts` domain helper, mirroring dazpy's
`lighting.py` usage of `_render.py`'s equivalent internal methods.

## Phase 4: Capture/Restore and Domain Helpers

Phase 4 ports dazpy's checkpoint/restore primitives and its higher-level
domain-helper modules, which apply typed configuration objects to the Phase
2/3 proxies rather than wrapping them in new classes ("typed data +
`apply()` function", matching dazpy's own module-function style for these).

- `DazPose` (`pose.ts`, from `_pose.py`) — a figure's complete pose
  (sparse bone rotations, morphs, node properties), captured/applied via
  each channel's *raw* (pre-ERC) value so repeated capture/apply cycles stay
  idempotent even on `DzERCLink`-driven dials. `capture()`/`apply()`/
  `applyFull()` are async (one HTTP call each); `lerp()`/`toDict()`/
  `fromDict()`/`save()`/`load()` are pure/local.
- `DazSceneState` (`sceneState.ts`, from `_scene_state.py`) — a full scene
  checkpoint: every skeleton's `DazPose`, plus camera/light transforms and a
  few extra light properties, restored in a small fixed number of HTTP
  calls. `apply()` independently verifies each skeleton restore with a
  fresh `DazPose.capture()` read-back (retrying up to `maxVerifyRetries`
  times on mismatch) since a 200 response can reflect a restore DAZ
  Studio's main thread only partially executed under contention, and
  restores each skeleton's conform/fit-to relationship via the real
  `followTarget()`/`fitTo()`/`unfit()` API rather than trusting
  `DazPose.applyFull()`'s generic property write-back.
- `DazAnimation` (`animation.ts`, from `_animation.py`) — a captured
  timeline clip (parallel-list bone rotations + optional varying-morph
  detection per frame). `capture()`/`apply()` are async; `clip()`/`blend()`/
  `asPose()`/`append()` are pure.
- `shotGeometry.ts` (from `_shot_geometry.py`) — pure camera/light placement
  math (`sphericalOffset`, `lookAtEuler`, `resolveTarget`) shared by
  `lighting.ts` and `cinematics.ts`. `resolveTarget` is async in TS (unlike
  Python's synchronous property access) since resolving a `DazNode` target
  requires an HTTP round-trip via `position()`.
- `poses.ts` (from `poses.py`) — `applyPose`, `resetTransforms`,
  `zeroFigure` convenience wrappers over `DazPose`/`DazNode`/`DazSkeleton`.
- `materials.ts` (from `materials.py`) — `IrayMaterial`/`TextureMap`/
  `SurfaceProperty` typed specs plus `applyIrayMaterial`/`applyTextureMap`/
  `getSurfaceProperty`/`setSurfaceProperty` over `DazMaterial`. Texture
  paths are validated (absolute + exists on disk) before any DazScript call
  is made, since an invalid path passed to the underlying `setMap()` can
  hang or crash DAZ Studio via a blocking file-not-found dialog.
- `lighting.ts` (from `lighting.py`) — `applyThreePointLightSetup` (key/
  fill/rim rig via `shotGeometry`) and `applyHdriEnvironment` (drives
  `DazRenderSettings`'s environment-holder methods, verifying the apply via
  an "Environment Intensity" readback).
- `cinematics.ts` (from `cinematics.py`) — `applyStaticShot`,
  `applyOrbitCamera` (a per-frame sweep via `scene.setFrame()`, **not** real
  keyframes — widens the scene's animation range as a documented side
  effect), `applyFrameSubject` (shot-distance presets), and
  `applyAnimatedShot` (real DAZ Studio keyframes via
  `setPositionAtFrame`/`setRotationAtFrame`, letting DAZ Studio interpolate).
- `sceneEvents.ts` (from `_scene_events.py`) — `watchSceneEvents`/
  `waitForSceneEvent`, typed SSE parsing over `GET /scene/events`, reusing
  `client.ts`'s `parseSseStream`/`streamSceneEvents` already added in
  Phase 3 for the render-progress stream.

Client-side input validation (file existence, path shape) happens in every
domain helper that touches user-supplied filesystem paths (`materials.ts`,
`lighting.ts`'s `applyHdriEnvironment`), matching dazpy's
blocking-dialog-avoidance pattern — a bad path reaching DAZ Studio's
underlying `setMap()`/environment-map call can hang or crash the app via a
modal file-not-found dialog rather than raising a script error.

Not ported in Phase 4: `_interaction.py` (multi-figure IK posing) — that's
Phase 5 (`daz-script-server-sf7y`).
