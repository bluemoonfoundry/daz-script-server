# CLAUDE.md

Handoff: `D:\OpenCode\Projects\daz-mcp-dev-handoff.md`
Bug-Katalog: `D:\Devpinkcharakter\docs\daz-mcp-bridge-bugs.md`

This file provides guidance to Claude Code when working with this repository.

## Project Overview

DazScriptServer is a DAZ Studio plugin (`.dll`/`.dylib`) that embeds an HTTP server inside DAZ Studio, enabling remote execution of DazScript code via HTTP POST requests with JSON responses.

## Build Commands

Requires DAZ Studio 4.5+ SDK (or the Daz Studio 6.25+ SDK) and CMake.

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

**Test clients:** `test-simple.py`, `tests.py`, `test-client.js`, `test-client.ps1`

## Architecture

### Threading Model (CRITICAL)

- **Main Qt thread**: GUI, script execution via `DzScript`, DAZ API calls, and
  access to thread-affine `QObject` instances
- **HTTP workers**: middleware plus synchronous parsing/validation; Studio 6
  async queue submission may use local instances of documented reentrant Qt
  Core value classes

**IMPORTANT:** HTTP handlers run on raw `std::thread`s (not Qt threads).
Synchronous execution crosses to `handleExecuteRequest()` via
`Qt::BlockingQueuedConnection`. On Studio 6, async script submission may parse
and validate with local reentrant Qt Core values, then submit to mutex-protected
services without blocking on the main thread. Studio 4 must keep submission on
the main thread because `JsonStd::parseObject()` uses `QScriptEngine` there.
The same split applies to structured job reports: Studio 6 may ingest JSONL
from polling workers for live observation, while Studio 4 parses the final
report from `markCompleted()` on the main thread after script execution returns.
Neither path may touch GUI objects, `DzScript`, the DAZ API, or shared mutable
state from a worker. Settings used by an async handler are snapshotted before
the server starts.

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
13. Return `{ success, result, output[], error, request_id }`

### Key Classes

| Class | Location | Purpose |
|---|---|---|
| `DzScriptServerPane` | `src/DzScriptServerPane.cpp` | Main pane: GUI + server + request handling |
| `ServerListenThread` | `src/DzScriptServerPane.cpp` | QThread wrapper for httplib |
| `SecureRandom` | `src/SecureRandom.cpp` | Crypto-secure RNG (OS APIs) |
| `JsonBuilder` | `src/JsonBuilder.cpp` | Type-safe JSON with auto-escaping |
| `ServerConfig` | `include/DzScriptServerPane.h` | Centralized config constants |

### HTTP API Endpoints

**Sync:** `/status`, `/health`, `/metrics`, `/execute`, `/scripts/*`
**Async:** `/execute/async`, `/scripts/:id/async`, `/requests/*`

Default: `127.0.0.1:18811`

**Status codes:** 200 (OK), 400 (Bad Request), 401 (Unauthorized), 403 (Forbidden/IP blocked), 413 (Body too large), 429 (Rate limit/concurrent limit)

**Authentication:** Token via `X-API-Token` header or `Authorization: Bearer <token>`. Auto-generated securely, stored in `~/.daz3d/dazscriptserver_token.txt` (chmod 600).

**POST /execute** accepts:
- `scriptFile`: Absolute path to `.dsa` file (for `include()`/`getScriptFileName()`)
- `script`: Inline DazScript code
- `args`: Optional object, accessible via `getArguments()[0]`

**Script Registry** (in-memory, session-only):
- `POST /scripts/register`: `{"name":"id","description":"...","script":"..."}` (name is ID, overwrites existing)
- `POST /scripts/:id/execute`: Execute registered script
- Script names: 1-64 chars, alphanumeric/hyphens/underscores

**Async endpoints:** Return `request_id` immediately. Poll `/requests/:id/status` or use `GET /requests/:id/result?wait=true` for long-poll. Status: `queued`, `running`, `completed`, `failed`, `cancelled`. TTL: 1 hour cleanup.

### Dependencies & Build

- **DAZ Studio SDK 4.5+**: Qt 4.8, `dzcore`
- **cpp-httplib**: Header-only (`src/httplib.h`), compression disabled
- **Windows**: Links `ws2_32`, `advapi32` (CryptoAPI)
- **Unix/macOS**: `/dev/urandom` for SecureRandom
- **MSVC flags**: `/MD /U_DEBUG` (force MT runtime, disable debug macros)

## Security Features

**Authentication:** 32-byte hex tokens (128-bit) via `SecureRandom` (OS crypto APIs). Stored in `~/.daz3d/dazscriptserver_token.txt` (chmod 600). Thread-safe (loaded once, read-only).

**IP Whitelist:** Exact match, comma-separated list. Default disabled. Checked after concurrent limit, before rate limiting/auth.

**Rate Limiting:** Per-IP sliding window (default: 60 req/60s). QMutex-protected. Periodic cleanup (every 100 requests).

**Input Validation:**
- Body size: 1-50 MB (default 5MB) → HTTP 413
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
**Auth:** Enabled by default, token auto-generated
**Whitelist/Rate limit:** Disabled by default

See `README.md` for full API reference and `FUTURE_ENHANCEMENTS.md` for planned features.


<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:7510c1e2 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->
