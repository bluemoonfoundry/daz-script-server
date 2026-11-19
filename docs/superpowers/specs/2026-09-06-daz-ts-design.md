# daz-ts: TypeScript SDK for the DAZ Studio Script Server

## Context

`dazpy` (`daz-script-server/dazpy/`) is the mature Python SDK for
DazScriptServer's HTTP API — a ~13,500-line, 37-module package covering
client/execution, batching, a full scene-graph proxy layer, math/geometry
utilities, and higher-level domain helpers (poses, materials, lighting,
cinematics, multi-figure IK/interaction posing). It has no TypeScript/Node
equivalent, which blocks any consumer written in JS/TS (browser tooling,
Node automation scripts, front-end pipeline glue) from talking to
DazScriptServer without hand-writing raw HTTP calls and DazScript strings.

The goal is a `daz-ts` package, living alongside `dazpy` in this repo, that
reaches full parity with dazpy's public API over time, built in phases so
each phase is independently usable. This document is the spec for that
effort; implementation proceeds phase-by-phase, each phase getting its own
plan under `docs/superpowers/plans/`.

## Decisions (confirmed with user)

- **Location**: `daz-script-server/daz-ts/`, a sibling directory to
  `dazpy/`, inside this repo — not a standalone repo.
- **Scope**: full parity with dazpy, delivered in phases (see below), not a
  reduced "core-only" port.
- **Runtime**: Node.js only (>=18, for built-in `fetch`/`AbortController`).
  No browser support. Uses Node's `fs`/`os` for token loading; no browser
  `EventSource`.
- **Testing**: Vitest. Mirrors dazpy's test structure: fake-`fetch`-based
  unit tests asserting exact generated DazScript strings, plus a separate
  integration suite gated on an env var, skipping gracefully with no live
  server.
- **Distribution**: npm-packaged but not published to the public npm
  registry. Built in CI (new workflow analogous to
  `.github/workflows/build-dazpy.yml`) and attached to GitHub releases as a
  tarball; consumers install via GitHub/git dependency or the release
  artifact.
- **Versioning**: `daz-ts` starts at its own `0.1.0`. It does not mirror
  dazpy's version number — it's a fresh port on its own release train.

## Architecture

### Single client, no sync/async split

Python needed `DazClient` (sync, `requests`) and `AsyncDazClient` (async,
`httpx`) as separate classes because Python's sync/async are different
calling conventions. TypeScript doesn't have this problem — `async/await`
covers both, so `daz-ts` has **one** `DazClient` class, backed by Node's
built-in `fetch`. This eliminates an entire duplicated layer dazpy carries
(`_client.py` + `_client_aio.py`, `_render_api.py` + `_render_api_aio.py`).

### Auth

Same convention as dazpy: `X-API-Token` header, auto-loaded from
`~/.daz3d/dazscriptserver_token.txt` via Node `fs`/`os.homedir()` if not
passed explicitly to the constructor; pass `token: ""` to disable auth. A
machine already running DazScriptServer + dazpy needs no extra
configuration to also use daz-ts.

### Script generation & injection safety

Proxy classes (Phase 2+) hold `(client, locator: string)` — `locator` is a
DazScript expression string that resolves to the live object, exactly as
in `DazElement`. Every call builds a small IIFE:
`(function(){ ...body...; return <expr>; })()`, with every injected value
passed through `JSON.stringify` (the direct TS equivalent of dazpy's
`json.dumps()`-based `ScriptBuilder.escape_string`/`serialize_arg`). This is
the single most important invariant to carry over exactly — dazpy has a
dedicated `TestInjectionSafety` test class fuzzing adversarial strings, and
`daz-ts` needs the equivalent from day one, not bolted on later.

### Response mapping & exceptions

Port `exceptions.py`'s hierarchy 1:1 as TS classes extending `Error`:
- `DazError` (base)
  - `ConnectionError`, `AuthenticationError`
  - `DazBusyError` (base, carries `.reason` + `.retryAfter`, default 2.0)
    - `StudioBusyError` (HTTP 503, `STUDIO_BUSY`)
    - `ConcurrencyLimitError` (HTTP 429, `CONCURRENT_LIMIT_EXCEEDED`)
  - `ScriptError` (base, carries `.script`, `.requestId`, `.output`, a
    `.diagnostic` getter)
    - `ScriptSyntaxError`, `ScriptRuntimeError`
  - `DazTimeoutError` (named to avoid shadowing the built-in `Error`
    subclass name that Python's `TimeoutError` doesn't have to worry about)
  - `NodeNotFoundError`, `RenderError`, `BatchLimitExceededError`,
    `AsyncExecutionError`, `MaterialError`

Response envelope mapping matches dazpy's `_map_response`: HTTP 200 with
`success: false` and `"SyntaxError"` in the message → `ScriptSyntaxError`;
otherwise → `ScriptRuntimeError`.

### Busy/backoff retry

Port `_with_busy_retry` exactly: every "submit"-style method takes
`{ retryOnBusy?: boolean; maxWait?: number }` (default `false` / `30.0`);
linear backoff starting at 1.0s, +1.0s per retry, capped at 5.0s, until
`maxWait` elapses, then re-throw.

### Batching — non-transactional, single-script semantics preserved exactly

Port `Batch`/`BatchFuture` faithfully (see dazpy `_batch.py`):
- `new Batch(client, { maxOperations = 500, maxScriptLength = 900_000 })`
- `.add(lines): BatchFuture` and `.addOperation(bodyLines, resultExpression): BatchFuture`
  (preferred — builder assigns the `_rN` key)
- `.addPrelude(preludeKey, lines): void` — shared setup emitted once
- `.execute(): Promise<void>` — one combined IIFE, one `execute()` HTTP call, resolves all futures
- Throws `BatchLimitExceededError` client-side if the generated script
  exceeds `maxScriptLength`, before any HTTP call
- `BatchFuture.value` getter throws if accessed before `.execute()` resolves
- **Explicitly preserve, in TSDoc**: serial execution order, no
  parallelism, **no transactionality/rollback** — a failing operation fails
  the whole call and earlier mutations are not undone. This must not be
  "improved" silently; it's a server-side constraint, not a client design
  choice.
- `client.executeBatchAsync(operations, args?)` ports the non-blocking
  sibling (`/execute/async`) with the same one-script guarantee.

### Proxy / scene-graph layer (Phase 2+)

Direct, largely mechanical ports of dazpy's proxy classes onto the shared
locator-string base (`DazElement` equivalent), generating equivalent
DazScript. Method names and property shapes carry over as the literal
spec. Preserve documented gotchas found by dazpy against a *live* server,
not assumed from docs — e.g. `DazProperty.rawValue` (ERC-link-bypassing,
required for idempotent snapshot/restore), keyframes via `setDoubleValue`
not `setKey`/`addKey`, `isAnimated` via `getNumKeys() > 0` not a
nonexistent `isAnimated()`, and `DazScene.findSkeleton()`'s retry-on-
transient-miss logic (works around a real `getSkeletonList()` race).

### math3.ts

Pure, dependency-free port of `math3.py`'s `Vec3`, `Quat`, `BoundingBox`,
`AxisRemap` — no HTTP coupling at all. Implemented in Phase 1 (pulled
forward from its original "Phase 3" grouping in initial discussion)
because it has zero dependencies and is a prerequisite for Phase 4/5's
pose/animation/IK code.

### Domain helpers (Phase 4+)

`poses.ts`, `materials.ts`, `lighting.ts`, `cinematics.ts` follow dazpy's
"typed data + `apply*()` function" pattern: plain TS interfaces/readonly
types for the data, plus standalone `apply*()` functions that compose
proxy-class calls (via `Batch` where dazpy does). No deep class hierarchy
for these — composition over inheritance, matching the source.

### Interaction/IK (Phase 5) — highest risk

Ports `_interaction.py` (2063 lines): rig-profile detection across figure
families, bone-chain/axis-limit types, damped-least-squares Jacobian IK
solving for limb alignment, and canned two-figure recipe builders. Highest
risk/most work — its own sub-effort with its own plan once Phases 1–4 are
solid.

## Package layout

```
daz-ts/
  package.json          # name: daz-ts, type: module, main/types -> dist/
  tsconfig.json
  vitest.config.ts
  src/
    index.ts            # public re-exports, matches dazpy __init__.py surface
    exceptions.ts
    result.ts
    scriptBuilder.ts
    client.ts
    batch.ts
    polling.ts
    math3.ts
    element.ts, node.ts, skeleton.ts, bone.ts, camera.ts, light.ts,      # Phase 2
    material.ts, modifier.ts, morph.ts, dforce.ts, geometry.ts,          # Phase 2
    scene.ts, sceneState.ts, sceneEvents.ts,                             # Phase 2/4
    render.ts, renderApi.ts, viewport.ts, timeline.ts, undo.ts,          # Phase 2/3
    pose.ts, animation.ts, shotGeometry.ts, interaction.ts,              # Phase 4/5
    lighting.ts, materials.ts, cinematics.ts, poses.ts                   # Phase 4
  test/
    unit/                # vitest, fake-fetch based, mirrors test_dazpy.py structure
    integration/         # gated on DAZ_SERVER_URL env var, mirrors skip_no_daz
  .github/workflows/build-daz-ts.yml   # new, analogous to build-dazpy.yml
```

## Testing strategy

- **Unit tests (Vitest)**: stub `global.fetch` and assert the *exact*
  generated DazScript string plus request shape for each client
  method/proxy method — mirrors dazpy's `TestDazNodeScriptGeneration`-style
  test classes. Include an explicit injection-safety suite (adversarial
  strings through every string-typed parameter) and call-count regression
  tests for batched operations (`Batch`) analogous to dazpy's
  `TestCallCounts`.
- **Integration tests**: gated behind `DAZ_SERVER_URL` env var; skip
  gracefully (not fail) when unset or the server is unreachable, mirroring
  `skip_no_daz`. Used to validate assumptions against a *live* DAZ Studio
  instance — daz-ts should not trust the OpenAPI spec/DazScript docs alone
  for anything not yet validated live.

## Phased delivery plan

1. **Phase 1 — Client core** (`daz-script-server-xtni`): `DazClient`,
   `ExecutionResult`, exception hierarchy, `ScriptBuilder`,
   `Batch`/`BatchFuture`, async job methods, `executeLong` polling helper,
   SSE plumbing for `/render/{id}/progress` and `/scene/events`, render/USD
   submission methods on `DazClient` (no proxy dependency), and `math3.ts`.
2. **Phase 2 — Scene graph proxies** (`daz-script-server-56nz`):
   `DazElement`, `DazNode`, `NodeIdentifier`, `DazScene`, `DazSkeleton`,
   `DazBone`, `DazCamera`, `DazLight`, `DazMaterial`,
   `DazModifier`/`DazMorph`/`DazDForce`, `DazGeometry`, `DazViewport`,
   `DazTimeline`, `UndoGroup`.
3. **Phase 3 — Rendering** (`daz-script-server-37mg`): `DazRenderSettings`,
   `Canvas`, `RenderOutcome`, high-level `render()`/`renderVariants()`
   helpers.
4. **Phase 4 — Capture/restore & domain helpers** (`daz-script-server-5hn3`):
   `DazPose`, `DazAnimation`, `DazSceneState`, `poses.ts`, `materials.ts`,
   `lighting.ts`, `cinematics.ts`, `shotGeometry.ts`, `sceneEvents.ts`.
5. **Phase 5 — Interaction/IK** (`daz-script-server-sf7y`): `interaction.ts`.

Each phase has a beads epic child issue; this document is the umbrella
spec, not a substitute for per-phase implementation plans.

## Verification

- Each phase: `npm run build` (tsc, strict mode) and `npm test` (vitest
  unit suite) must pass before moving to the next phase.
- Unit suite must include exact-generated-script assertions and an
  injection-safety suite from Phase 1 onward — not deferred.
- Integration suite (gated) should be run manually against a live
  DAZ Studio + DazScriptServer instance at the end of each phase to catch
  live-API mismatches early.
- CI: new `.github/workflows/build-daz-ts.yml` builds and packages the
  tarball; wire into the existing release workflow so it attaches
  alongside the dazpy wheel/sdist and the compiled plugin binary.
