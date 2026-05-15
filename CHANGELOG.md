# Changelog

All notable changes to DazScript Server are documented here.

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
