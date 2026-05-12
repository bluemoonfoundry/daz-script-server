# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Project Overview

DazScriptServer is a DAZ Studio plugin (`.dll`/`.dylib`) that embeds an HTTP server inside DAZ Studio, enabling remote execution of DazScript code via HTTP POST requests with JSON responses.

## Build Commands

Requires DAZ Studio 4.5+ SDK and CMake.

```bash
# Basic build
./build.sh

# Common options
./build.sh install --clean           # Install to DAZ Studio (must not be running)
./build.sh build --clean --debug     # Clean debug build
./build.sh release v1.3.0           # Create GitHub release
```

Set `DAZ_STUDIO_EXE_DIR` in `.env` for automatic installation. Default: `C:\Program Files (x86)\DAZ\Studio4\plugins\`

**Test clients:** `test-simple.py`, `tests.py`, `test-client.js`, `test-client.ps1`

## Architecture

### Threading Model (CRITICAL)

- **Main Qt thread**: GUI, script execution via `DzScript`, all Qt/DAZ API calls
- **HTTP thread**: `ServerListenThread` blocks on `httplib::Server::listen()`

**IMPORTANT:** HTTP handlers run on raw `std::thread`s (not Qt threads). Handlers must do minimal work (parse body), then invoke `handleExecuteRequest()` on main thread via `Qt::BlockingQueuedConnection`. All `QScriptEngine`, `DzScript`, and Qt operations MUST happen on the main thread.

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
