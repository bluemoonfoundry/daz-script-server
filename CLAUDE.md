# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Project Overview

DazScriptServer is a DAZ Studio plugin (`.dll`/`.dylib`) that embeds an HTTP server inside DAZ Studio, enabling remote execution of DazScript code via HTTP POST requests with JSON responses.

## Build Commands

Requires DAZ Studio 4.5+ SDK (or the current Daz Studio 6 SDK — 6.26.2026.27900; Studio 6.25 support ended at v2.9.3) and CMake.

```bash
# Basic build (DAZ Studio 4.x, default)
./build.sh

# Common options
./build.sh install --clean           # Install to DAZ Studio (must not be running)
./build.sh build --clean --debug     # Clean debug build
./build.sh release v1.3.0           # Create GitHub release

# DAZ Studio 6.x (Qt6) build
./build.sh build --sdk-version 6 --clean
```

Set `DAZ_STUDIO_EXE_DIR` in `.env` for automatic installation. Default: `C:\Program Files (x86)\DAZ\Studio4\plugins\`

### DAZ Studio 6 (Qt6) builds

SDK6 changed how Daz distributes the dev kit: it ships `dzcore`/`dzsdkmemory`
only — no Qt `.lib`/`.cmake` files at all. Building against SDK6 requires a
separate Qt6 devkit matching the Qt6 minor version DAZ Studio 6 bundles
(check `Qt6Core.dll`'s file version in the DAZ Studio 6 install dir). Install
one via [aqtinstall](https://github.com/miurahr/aqtinstall) (scriptable, also
used in CI):

```bash
pip install aqtinstall
aqt install-qt windows desktop 6.10.3 win64_msvc2022_64 -m qt5compat
```

Then set `DAZ_SDK_DIR_V6` and `QT6_DIR` in `.env` (see `.env` for the exact
variable names/format) and run `./build.sh build --sdk-version 6`. At
*runtime* the plugin resolves Qt6 symbols against DAZ Studio 6's own bundled
DLLs already loaded in-process — the separate devkit is only needed to link
at build time. `--sdk-version 4` and `--sdk-version 6` use separate build
directories (`build/` vs `build-sdk6/`), so switching between them never
reuses a stale CMake cache from the other SDK.

**Tests:** `python tests.py unit|api|integration` (unit needs no server),
`python tests/test_performance.py [--quick]`. Example clients: `test-client.js`,
`test-client.ps1`

**Live smoke matrix:** `python tests/smoke_live.py` (DS4/DS6 × Iray/Filament/viewport,
engine readback after every change, `--record` per release). Use it instead of
the full live integration suite. See `docs/LIVE_SMOKE.md`.

## Architecture

### Threading Model (CRITICAL)

HTTP handlers run on raw `std::thread`s, not Qt threads. `DzScript`,
`QScriptEngine`, GUI objects and every DAZ API call belong to the main Qt
thread. Read the rules in
[`ARCHITECTURE.md` → Threading Model](ARCHITECTURE.md#threading-model) before
changing any code that crosses threads; they cover the Studio 4 vs Studio 6
async-submission split, job reports and settings snapshots.

### Request Flow (POST /execute)

HTTP handler → validation/auth → emit signal → `handleExecuteRequest()` (main thread) →
1. Check concurrent limit (429 if exceeded)
2. Check IP whitelist if enabled (403 if blocked)
3. Check rate limit if enabled (429 if exceeded)
4. Validate body size (413 if > 5MB default)
5. Validate token if auth enabled (401 if invalid)
6. Generate request ID (8-char UUID)
7. Parse JSON with `QScriptEngine` (400 if malformed)
8. Validate input (script length, scriptFile/script presence, file exists)
9. Wrap script in IIFE, inject `args` as JSON literal
10. Capture output via `onMessagePosted()`
11. Execute via `DzScript`, measure duration
12. Update metrics, log request
13. Return `{ success, result, output[], error, request_id }` (+ `error_code`/`retryable` on failure; `runJobRoute()` stamps `server_instance_id`, `correlation_id`, `scene_revision`)

### Key Classes

| Class | Location | Purpose |
|---|---|---|
| `DzScriptServerPane` | `src/DzScriptServerPane.cpp` | Main pane: GUI + server + request handling |
| `ServerListenThread` | `src/DzScriptServerPane.cpp` | QThread wrapper for httplib |
| `SecureRandom` | `src/SecureRandom.cpp` | Crypto-secure RNG (OS APIs) |
| `JsonBuilder` | `src/JsonBuilder.cpp` | Type-safe JSON with auto-escaping |
| `ServerConfig` | `include/DzScriptServerPane.h` | Centralized config constants |
| `ArtifactRoutes` | `src/ArtifactRoutes.cpp` | `GET /artifacts` list/download handlers |
| `ArtifactRoots` | `src/ArtifactRoots.cpp` | Artifact trust boundary (allowed folders) |
| `Capabilities` | `src/Capabilities.cpp` | `GET /capabilities` document + route table |
| `PluginRouteRegistry` | `src/PluginRouteRegistry.cpp` | Companion-plugin routes and matching |
| `ScriptRegistry` | `src/ScriptRegistry.cpp` | Session-only registered scripts |

### HTTP API Endpoints

`openapi.yaml` is the route list: CI keeps it in parity with `setupRoutes()`
(see **OpenAPI parity** below), so read it rather than a hand-kept list here.
It also documents artifact manifest and Range/HEAD behavior.

Default: `127.0.0.1:18811`

**Status codes:** 200 (OK), 400 (Bad Request), 401 (Unauthorized), 403 (Forbidden: IP blocked, or artifact outside the allowed artifact folders), 404 (Unknown script/request/route/artifact), 409 (Idempotency key in flight), 413 (Body too large), 410 (Declared artifact file gone), 422 (Idempotency key reused), 429 (Rate limit/concurrent limit), 503 (Studio busy/queue full)

**Errors:** every failure body is `ErrorResponse` (`include/ErrorResponse.h`):
`{success:false, error_code, error, retryable, detail?}`. Never hand-build an
error body; add an `ErrorCode` instead. Script/job failures stay HTTP 200 with
`error_code` `SCRIPT_ERROR` / `JOB_CANCELLED` / `JOB_STALE`.

**Job routes** (`/execute`, `/scripts/{id}/execute`, async + render submission)
go through `runJobRoute()`: write chain → `X-Correlation-Id` → `Idempotency-Key`
(`IdempotencyCache`, async/render submission only) → handler → identity stamp.

**Authentication:** Token via `X-API-Token` header or `Authorization: Bearer <token>`. Auto-generated securely, stored in `~/.daz3d/dazscriptserver_token.txt` (chmod 600).

**POST /execute** accepts:
- `scriptFile`: Absolute path to `.dsa` file (for `include()`/`getScriptFileName()`)
- `script`: Inline DazScript code
- `args`: Optional object, accessible via `getArguments()[0]`

**Script Registry** (in-memory, session-only):
- `POST /scripts/register`: `{"name":"id","description":"...","script":"..."}` (name is ID, overwrites existing)
- `POST /scripts/{id}/execute`: Execute registered script
- Script names: 1-64 chars, alphanumeric/hyphens/underscores

**Async endpoints:** Return `request_id` immediately. Poll `/requests/{id}/status` or use `GET /requests/{id}/result?wait=true` for long-poll. Status: `queued`, `running`, `completed`, `failed`, `cancelled`. TTL: 1 hour cleanup.

### Dependencies & Build

- **DAZ Studio SDK 4.5+**: Qt 4.8, `dzcore`
- **cpp-httplib**: Header-only (`src/httplib.h`), compression disabled
- **Windows**: Links `ws2_32`, `advapi32` (CryptoAPI)
- **Unix/macOS**: `/dev/urandom` for SecureRandom
- **MSVC flags**: `/MD /U_DEBUG` (force MT runtime, disable debug macros)

## Security Features

**Authentication:** 32-byte hex tokens (128-bit) via `SecureRandom` (OS crypto APIs). Stored in `~/.daz3d/dazscriptserver_token.txt` (chmod 600). Thread-safe (loaded once, read-only).

**IP Whitelist:** Exact match, comma-separated list. Default disabled. Checked after concurrent limit, before rate limiting/auth, on every authenticated route.

**Middleware chains:** every authenticated route runs exactly one of two chains
(`setupRoutes()`): `m_pWriteChain` (IP whitelist → rate limit → body size → auth)
for all POST/DELETE routes, `m_pReadChain` (IP whitelist → auth) for polling GETs
and SSE streams. Companion-plugin routes (`applyPluginRoutes()` catch-alls) pick
the chain by method after route matching. `tests/test_route_security.py` (unit
suite) enforces this. New routes must use one of them.

**OpenAPI parity:** every route in `setupRoutes()` must have a matching path +
method in `openapi.yaml`, and vice versa. Companion-plugin routes are declared in
`companion_plugins.json` (read by `scripts/check_openapi_parity.py`; `--live URL`
checks a running server's `/capabilities` against it) and documented with tag
`CompanionPlugins`. SDK calls (dazpy, daz-ts) to endpoints the spec
doesn't document also fail. CI runs the script (`openapi-parity` job, which
posts SDK coverage to the job summary), as does `tests/test_openapi_parity.py`.

**Rate Limiting:** Per-IP sliding window (default: 60 req/60s). QMutex-protected. Periodic cleanup (every 100 requests).

**Input Validation:**
- Body size: 1-50 MB (default 5MB) → HTTP 413. Enforced on every route by
  httplib `set_payload_max_length` while the body is read (JSON body via
  `set_error_handler`), plus `BodySizeMiddleware` in the write chain
- Script length: 100-10240 KB (default 1MB) → HTTP 400
- JSON parsing with line numbers
- Script file: absolute path, exists, is file

**Request Management:**
- Concurrent limit: 5-50 (default 10) → HTTP 429
- Request IDs: 8-char UUID
- Thread-safe counters (mutex-protected)
- Logging format: `[HH:mm:ss] [client_ip] [status] [duration_ms] [request_id] script_identifier`

**Observability:** `/health` and `/metrics` endpoints. All settings persist via QSettings.

## Configuration Defaults

**Limits:** 10 concurrent requests, 5MB body, 1MB script, 60 req/60s rate limit
**Constants:** 1000 log lines, 10000 captured lines, cleanup every 100 requests
**Stuck job timeout:** 30 min (UI-configurable 5–1440, applied live) → async job reported `stale`
**Auth:** Enabled by default, token auto-generated
**Whitelist/Rate limit:** Disabled by default

See `README.md` for the full API reference.

## Issue Tracking and Session Completion

The beads (`bd`) workflow and the session-close checklist live in
`AGENTS.md`, which other coding agents read too:

@AGENTS.md
