# DAZ Studio Busy Handling — Design

## Problem

DazScriptServer assumes DAZ Studio's main thread is mostly idle, waiting to be
driven remotely. In practice, a user can drive DAZ Studio through its own UI
(loading scenes, rendering) at the same time an MCP/dazpy client is polling or
issuing commands — DAZ Studio is single-threaded with respect to the Qt main
thread, so the two compete for the same resource.

Every request that needs the main thread (`/execute`, `/scripts/:id/execute`,
async-enqueue endpoints, render-enqueue endpoints) is dispatched via
`QMetaObject::invokeMethod(..., Qt::BlockingQueuedConnection, ...)`
(`src/RequestHandlers.cpp`). This connection type has **no timeout**: the HTTP
worker thread blocks until the main thread's event loop processes the queued
call. If the main thread is busy with a long synchronous operation triggered
from the DAZ Studio UI (scene load, render, scene save/clear), the queued
event just waits — the HTTP thread hangs indefinitely, with no server-side
signal to the client.

Observed impact (from a live Claude Desktop + daz-mcp-server session): while
a user was manually loading scene files in the DAZ Studio UI, a scene-info
query hung for 4+ minutes with no response, and the LLM client had no way to
distinguish "Studio is busy" from "Studio is dead."

Compounding effects:
- `ActiveRequestSlot` is acquired *before* the blocking call and released only
  when it returns, so each stuck request permanently occupies one of
  `m_nMaxConcurrentRequests` (default 10) slots for as long as Studio is busy.
- No client-visible signal exists today to distinguish "busy, retry" from
  "broken."

Out of scope for this design: `GET /requests` and `GET /requests/:id/status`
read a mutex-protected in-memory map directly on the HTTP thread with no
main-thread hop, so they are not expected to be affected by this specific
cause. If they are independently found to hang under the same conditions,
that is a separate investigation.

## Goals

- A busy main thread produces a fast, unambiguous `503` response instead of
  an indefinite hang, following normal HTTP server conventions.
- The dazpy Python SDK surfaces this as a distinct, catchable exception —
  never mistaken for a DazScript runtime error.
- Retry is available but opt-in, not automatic by default, so callers (and
  the LLM driving them) stay informed rather than silently blocked.
- The MCP server (daz-mcp-server) surfaces the same signal to Claude as a
  clear, actionable tool error.
- Fix the adjacent, same-shaped bug where HTTP `429`
  (`CONCURRENT_LIMIT_EXCEEDED`) is today misreported by dazpy as a
  `ScriptRuntimeError`.

## Design

### 1. Server: busy detection & fast-fail (daz-script-server, C++)

`SceneEventBroker` (`src/SceneEventBroker.cpp`) already connects to
`DzScene` signals that fire synchronously on the main thread *before* the
corresponding blocking work begins:

- `sceneLoadStarting()` / `sceneLoaded()`
- `sceneSaveStarting(QString)` / `sceneSaved(QString)`
- `sceneClearStarting()` / `sceneCleared()`
- `aboutToRender(DzRenderer*)` / `renderFinished(DzRenderer*)`

Extend `SceneEventBroker` (reusing these existing connections rather than
duplicating them) with a lock-free busy-state tracker:

- A `QAtomicInt` state field, written only from the main thread inside the
  existing signal slots (`onSceneLoadStarting`, `onSceneSaveStarting`,
  `onSceneClearStarting`, `onAboutToRender`, and their `*Finished`/`*Loaded`/
  `*Saved`/`*Cleared` counterparts which reset it to idle).
- `bool isBusy() const` and `QString busyReason() const` accessors, safe to
  call from any HTTP worker thread (atomic load, no locking).
- A reason enum: `Idle`, `SceneLoading`, `SceneSaving`, `SceneClearing`,
  `Rendering`.
- A test-only setter (e.g. `#ifdef`-guarded or an explicit
  `forceBusyStateForTesting()`) so unit tests can exercise the fast-fail path
  without actually triggering a scene load.

New `ErrorCode::STUDIO_BUSY` in `ErrorResponse`, mapped to HTTP `503`, with a
reason-specific default message (e.g. "DAZ Studio is currently loading a
scene", "...rendering", "...saving a scene", "...clearing the scene").
Response includes a `Retry-After` header with a fixed short hint (e.g. `2`
seconds) — not a real time estimate, since scene loads vary widely.

Add a busy check as the first step inside every handler that performs a
`BlockingQueuedConnection` main-thread hop, before the `invokeMethod` call:

- `ExecuteScriptHandler::handle`
- `ScriptExecuteHandler::handle`
- `AsyncExecuteHandler::handle`
- `AsyncScriptHandler::handle`
- `RenderHandler::handle`
- `RenderBatchHandler::handle`
- `RenderAnimationHandler::handle`

If busy, return `503` immediately via `ErrorResponse::build(ErrorCode::STUDIO_BUSY, ...)`.
The `ActiveRequestSlot` concurrency slot (already acquired by the caller
before `handle()` runs, per existing flow in `DzScriptServerPane.cpp`) is
held only for the duration of this fast check, not indefinitely.

### 2. dazpy client (Python SDK)

New exception hierarchy in `dazpy/exceptions.py`:

```
DazError
└── DazBusyError            # new — base for "transient, please retry"
    ├── StudioBusyError     # HTTP 503, error_code == "STUDIO_BUSY"
    └── ConcurrencyLimitError  # HTTP 429, error_code == "CONCURRENT_LIMIT_EXCEEDED"
```

Both subclasses carry `reason: str` and `retry_after: float`.

`_map_response` (`dazpy/_client.py`) checks `error_code` for both
`STUDIO_BUSY` and `CONCURRENT_LIMIT_EXCEEDED` *before* the existing generic
`if not data.get("success", True): raise ScriptRuntimeError(...)` fallback,
so neither is ever misreported as a script failure. This also fixes the
existing bug where `429` responses are today raised as `ScriptRuntimeError`.

Default behavior: raise immediately, no retry — matches normal HTTP client
conventions and keeps the caller (and the LLM driving it) informed rather
than silently blocked.

Opt-in retry: every public method that can hit a busy endpoint (`execute`,
`execute_file`, `execute_async_submit`, `render_submit`,
`render_batch_submit`, `render_animation_submit`, and the registry-execute
path) gains `retry_on_busy: bool = False` and `max_wait: float = 30.0`
keyword arguments. Rather than duplicating a retry loop in every method, add
a private wrapper (e.g. `_post_retrying`) around `_post`/`_get` that:

1. Calls the underlying request.
2. On `DazBusyError`, sleeps using a capped linear backoff (e.g. 1s, 2s, 3s,
   capped at some max step), tracking elapsed time.
3. Retries until `max_wait` is exceeded, then re-raises the last
   `DazBusyError`.

### 3. MCP server (daz-mcp-server)

`_errors.py::handle_dazpy_error` is the single choke point every tool routes
through via `run_dazpy`. Add a case:

```python
if isinstance(exc, daz_exc.DazBusyError):
    raise ToolError(f"DAZ Studio is busy ({exc.reason}). Try again in a few seconds.") from exc
```

placed before the generic `ScriptRuntimeError`/`ScriptSyntaxError` case (so
it isn't shadowed — `DazBusyError` does not subclass `ScriptError`, so
ordering only matters for clarity, not correctness).

No MCP tool opts into `retry_on_busy=True` by default. This is a deliberate
choice: behavior stays predictable, and Claude sees a fast, clear signal it
can act on (wait, inform the user, try something else) rather than the tool
call silently blocking for up to `max_wait`.

### 4. Testing

- **C++**: Unit-test the busy-state tracker and `ErrorResponse::build(STUDIO_BUSY, ...)`
  using the test-only forced-busy setter — no live scene load required. Full
  end-to-end verification (actually loading a scene while hitting
  `/execute`) is a manual smoke test; this project does not run its full
  live-Studio integration suite in CI (see `test-simple.py`,
  `tests.py` usage patterns — manual invocation against a running Studio
  instance).
- **dazpy**: Mock HTTP responses for `_map_response` raising
  `StudioBusyError` / `ConcurrencyLimitError`, and for the `retry_on_busy`
  backoff/`max_wait` loop (assert retry count, elapsed-time bound, and that
  it re-raises after `max_wait`). No live Studio needed.
- **daz-mcp-server**: Unit test `handle_dazpy_error` mapping both
  `DazBusyError` subclasses to the expected `ToolError` text, using the
  existing respx-based test pattern in that repo.

## Non-goals / follow-ups

- Investigating why `GET /requests` (list) reportedly also hung in the
  observed session, despite not using `BlockingQueuedConnection` — tracked
  as a separate follow-up, not folded into this fix.
- MCP tools opting into `retry_on_busy=True` for specific high-value calls —
  left as a future enhancement, not built now.
- Changes to `daz-mcp-server` require a separate commit/PR in that repo;
  this document covers the design but implementation happens per-repo.
