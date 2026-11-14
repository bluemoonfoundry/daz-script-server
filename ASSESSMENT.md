# DazScript Server Assessment

## Executive assessment

`daz-script-server` is a strong lower-level execution platform for DAZ Studio. Its native plugin handles main-thread execution, authentication, rate limiting, asynchronous jobs, rendering, SSE scene events, and a broad typed Python SDK.

It is not yet a complete end-user scene-production platform. The main gaps are:

- the HTTP contract is not sufficiently self-describing for robust MCP clients;
- asynchronous jobs do not provide fully truthful cancellation or granular progress;
- artifacts depend on a shared filesystem;
- the SDK exposes useful cinematic primitives but not a production-level shot/sequence model;
- the MCP server contains considerably more cinematic orchestration than the core SDK.

The recommended architecture is to keep MCP as a sidecar. The DAZ plugin should remain the execution plane, `dazpy` should own the canonical protocol client and typed domain primitives, and the MCP server should translate natural-language intent into validated scene/shot plans.

## Current strengths

- Strong threading discipline around DAZ Studio's main Qt thread.
- Secure-by-default localhost operation with token authentication, IP filtering, rate limiting, body validation, and audit logging.
- Synchronous and asynchronous script execution with polling, long-polling, cancellation, TTL cleanup, and bounded queues.
- Render submission for single images, batches, and animation ranges.
- SSE streams for scene events and render lifecycle events.
- Broad `dazpy` coverage: scene graph, figures, bones, morphs, materials, geometry, animation, poses, interaction/IK, rendering, lighting, checkpoints, batching, and undo groups.
- Existing cinematic primitives for static shots, orbit cameras, subject framing, animated camera keyframes, three-point lighting, and HDRI environments.
- Good unit coverage: the selected script-server test run completed with 795 passed and 4 skipped.

## Prioritized recommendations

### P0 — Correctness and resource protection

#### 1. Apply request-size limits to every mutating endpoint

The configured `BodySizeMiddleware` is attached to synchronous `/execute`, but async execution, registered async scripts, and render endpoints use a base middleware chain without it. This permits oversized JSON payloads to bypass the configured body limit.

Evidence:

- [src/DzScriptServerPane.cpp:915](src/DzScriptServerPane.cpp#L915)
- [src/DzScriptServerPane.cpp:921](src/DzScriptServerPane.cpp#L921)
- [src/DzScriptServerPane.cpp:1020](src/DzScriptServerPane.cpp#L1020)
- [src/DzScriptServerPane.cpp:1058](src/DzScriptServerPane.cpp#L1058)

Recommendation:

- Apply body limits to all request bodies.
- Add endpoint-specific limits for scripts, render batches, animation ranges, and report metadata.
- Reject oversized bodies before JSON parsing or main-thread work.
- Add regression tests for each endpoint family.

#### 2. Make asynchronous cancellation semantics explicit and truthful

Queued jobs can be cancelled. Running renders can request `killRender()`. Running arbitrary DazScript, however, cannot be forcibly interrupted safely. The request tracker can report `cancelled` before the underlying operation has actually stopped.

Evidence:

- [src/AsyncRequestManager.cpp:476](src/AsyncRequestManager.cpp#L476)
- [include/AsyncRequestManager.h:124](include/AsyncRequestManager.h#L124)

Recommendation:

- Distinguish `cancel_requested`, `cancelled`, and `completed_after_cancel_request`.
- Document that arbitrary running scripts are cooperative-cancellation only.
- Add a script-side cancellation flag or execution context for long-running recipes.
- Preserve the final underlying outcome in job history.

#### 3. Improve job progress reporting

Single-frame render progress currently provides start and terminal events but no intermediate percentage. General script progress only exists when the script writes a JSONL report file.

Evidence:

- [src/DzScriptServerPane.cpp:1181](src/DzScriptServerPane.cpp#L1181)
- [src/AsyncRequestManager.cpp:150](src/AsyncRequestManager.cpp#L150)

Recommendation:

- Define a standard job-report protocol with phases, progress, logs, warnings, and outputs.
- Add heartbeat timestamps and “last activity” information.
- Report animation-frame progress natively.
- Provide explicit `progress_supported` and `progress_source` fields.

### P1 — MCP and API integration

#### 4. Add a machine-readable capabilities endpoint

The plugin exposes `/status`, `/health`, and `/metrics`, but no endpoint describing the actual feature set, limits, SDK version, render engines, optional routes, or registered-script schema.

Add `GET /capabilities` containing:

- API and plugin versions;
- DAZ Studio/SDK version;
- supported endpoint and feature flags;
- maximum body/script/batch limits;
- available render engines;
- async and SSE support;
- schema version and compatibility hash.

This lets the MCP server adapt instead of relying on hard-coded assumptions.

#### 5. Keep OpenAPI, implementation, and SDK contracts synchronized

`POST /scene/save-copy` is implemented and documented in the README but is absent from `openapi.yaml`. The OpenAPI version also differs from the package version.

Evidence:

- [src/DzScriptServerPane.cpp:1082](src/DzScriptServerPane.cpp#L1082)
- [README.md:427](README.md#L427)
- [openapi.yaml:25](openapi.yaml#L25)

Recommendation:

- Add an automated route-to-OpenAPI parity check.
- Generate or validate SDK endpoint coverage from the OpenAPI contract.
- Add API version negotiation and deprecation metadata.
- Include companion-plugin routes in a discoverable extension registry.

#### 6. Add authenticated artifact transfer

Async results and output manifests currently expose paths. The sibling MCP server must share a filesystem with DAZ Studio to return images or files.

Recommendation:

- Add authenticated artifact handles rather than exposing arbitrary paths.
- Provide `GET /artifacts/{job_id}/{artifact_id}` with range support and content metadata.
- Add thumbnail/preview generation for images.
- Restrict downloads to artifacts declared by the originating job.

#### 7. Add stable request identity and idempotency

MCP workflows frequently retry after timeouts or DAZ Studio restarts. The current API has request IDs but no client-supplied idempotency key, correlation ID, scene/session ID, or operation ownership.

Recommendation:

- Accept `Idempotency-Key` on job submission.
- Return `correlation_id`, `scene_revision`, and `server_instance_id`.
- Add a consistent structured error envelope across HTTP and script failures.
- Make retry safety explicit per operation.

### P1 — Rendering and production reliability

#### 8. Finish live validation of render-engine behavior

The render implementation contains TODOs for engine switching and Iray sample configuration, and the SDK uses render-element assumptions that require live verification.

Evidence:

- [src/DzScriptServerPane.cpp:1999](src/DzScriptServerPane.cpp#L1999)
- [dazpy/_render.py:204](dazpy/_render.py#L204)

Recommendation:

- Add live smoke tests for Iray, Filament, and viewport rendering on DS4 and DS6.
- Read back every mutated render setting.
- Avoid relying on fixed render-element indexes where a named lookup is possible.
- Return a verified engine/result state rather than assuming the requested engine was applied.

#### 9. Add a production recipe boundary

The current escape hatch is arbitrary DazScript or a file-backed `.dsa` job. That is powerful but difficult to validate, preview, retry, or explain to end users.

Introduce a declarative recipe format with:

```yaml
scene:
  assets: []
  actors: []
  blocking: []
  lighting: {}
  cameras: []
  shots: []
render:
  outputs: []
  quality: preview
```

The server or SDK should support validate, dry-run, apply, observe, and materialize operations for this format.

#### 10. Define checkpoint and rollback scope

Current checkpoints are useful but selective and session-bound. They do not represent a full transactional scene state.

Recommendation:

- Clearly separate pose checkpoints from full scene backups.
- Support save-copy before destructive recipes.
- Include materials, HDRI/environment settings, node additions/deletions, and render settings where feasible.
- Return a verification report after restore.
- Use explicit “best effort” semantics when a node no longer exists.

### P2 — Cinematic and end-user functionality

#### 11. Promote cinematic primitives into a canonical shot model

The core SDK currently provides:

- static shot placement;
- orbit camera motion;
- named-distance subject framing;
- animated camera keyframes;
- three-point lighting;
- HDRI environment setup.

Evidence:

- [dazpy/cinematics.py:77](dazpy/cinematics.py#L77)
- [dazpy/cinematics.py:175](dazpy/cinematics.py#L175)
- [dazpy/cinematics.py:265](dazpy/cinematics.py#L265)
- [dazpy/cinematics.py:358](dazpy/cinematics.py#L358)
- [dazpy/lighting.py:110](dazpy/lighting.py#L110)

Add typed models for:

- `Shot`, `Sequence`, and `CoveragePlan`;
- shot size, angle, lens, movement, composition, and eyeline;
- camera rigs and focus pulls;
- blocking, facing, gaze, and interaction beats;
- lighting continuity and mood presets;
- storyboard frames and per-shot metadata;
- render outputs and review thumbnails.

#### 12. Add common cinematic idioms

High-value built-in operations include:

- establishing shot, master shot, medium, close-up, insert, POV, profile, two-shot;
- over-the-shoulder and shot/reverse-shot coverage;
- 180-degree axis and eyeline continuity;
- dolly, truck, crane, push-in, pull-out, pan, tilt, and orbit moves;
- rack focus and focus-distance automation;
- rule-of-thirds, headroom, lead-room, and horizon composition;
- conversation beats, gaze targets, pauses, reactions, and turn-taking;
- deterministic naming for cameras, lights, shots, and render outputs.

The sibling MCP server already contains many of these concepts in its cinematic tools. They should be backed by reusable `dazpy`/recipe primitives instead of remaining MCP-only script implementations.

#### 13. Integrate content discovery with scene production

End users need to find and load compatible figures, wardrobe, props, environments, poses, and expressions. This functionality currently belongs primarily to the sibling content-browser/MCP ecosystem rather than the script server.

Recommendation:

- Define a shared asset reference format.
- Add asset search, compatibility checks, and resolved-path metadata.
- Make recipes declare asset requirements before mutation.
- Return provenance for every loaded asset.

#### 14. Add deterministic scene validation

Before rendering, validate:

- missing assets and nodes;
- figure collisions and interpenetration;
- camera framing and clipping;
- missing or contradictory lighting;
- render-engine availability;
- output-path collisions;
- animation range and keyframe consistency;
- continuity violations between shots.

## MCP integration model

The existing sidecar split is appropriate:

```text
MCP client
   ↓ MCP tools/resources
daz-mcp-server
   ↓ dazpy typed client
daz-script-server HTTP API
   ↓ main-thread execution
DAZ Studio
```

The sibling MCP server already demonstrates useful patterns:

- registered scripts are re-registered after a DAZ Studio restart;
- compact and expert tool profiles reduce model-facing complexity;
- scene events are consumed through the existing SSE stream;
- workflow tools provide job submission, observation, recipe materialization, and artifact fetching.

The next step should be to formalize the boundaries with capabilities, schemas, artifacts, idempotency, and recipe execution rather than embedding MCP directly into the C++ plugin.

## Quality and delivery observations

- The Python SDK unit/API selection passed 795 tests with 4 expected skips.
- The native build compiled the changed C++ translation units but failed at link time because the configured output path under `X:\DAZNext\...` was unavailable.
- The native build emitted a `size_t`-to-`int` conversion warning and a C-linkage/UDT warning in `pluginmain.cpp`; these should be cleaned up for warning-free builds.
- CI builds the plugin and runs Python unit tests, but there is no dependable automated live DAZ Studio smoke matrix for API, render-engine, and MCP integration behavior.
- The sibling MCP test suite should be a separate quality gate; the selected run exposed a failure in async file-execution error mapping.

## Suggested implementation order

1. Enforce body limits on all endpoints and clarify cancellation semantics.
2. Add capabilities, correlation/idempotency fields, and standardized errors.
3. Repair OpenAPI/version drift and add protocol parity tests.
4. Add secure artifact transfer and richer job progress.
5. Validate render-engine behavior on every supported SDK/platform.
6. Introduce the declarative scene/shot recipe model.
7. Move MCP cinematic orchestration onto those typed recipe primitives.
8. Add content discovery, scene validation, continuity checks, and review thumbnails.
