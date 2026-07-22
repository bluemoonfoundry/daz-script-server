# DAZ Studio Busy Handling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make DazScriptServer fail fast (HTTP 503) instead of hanging indefinitely when DAZ Studio's main thread is busy (scene load/save/clear or render triggered from the DAZ Studio UI or elsewhere), and give the dazpy Python SDK a distinct, catchable exception for that condition with opt-in retry.

**Architecture:** `SceneEventBroker` already connects to `DzScene` signals (`sceneLoadStarting`/`sceneLoaded`, `sceneSaveStarting`/`sceneSaved`, `sceneClearStarting`/`sceneCleared`, `aboutToRender`/`renderFinished`) that fire synchronously on the main thread before the corresponding blocking work begins. Extend it with a lock-free atomic busy-state flag, add a new `STUDIO_BUSY` (503) error code, and check that flag at the top of every HTTP handler that would otherwise block on `Qt::BlockingQueuedConnection` with no timeout. On the Python side, add a `DazBusyError` exception hierarchy to dazpy, route both `503 STUDIO_BUSY` and the existing (currently misreported) `429 CONCURRENT_LIMIT_EXCEEDED` through it, and add an opt-in `retry_on_busy`/`max_wait` backoff loop.

**Tech Stack:** C++ (Qt 4.8/6.10, DAZ Studio SDK, cpp-httplib) for the server; Python 3.10+ (`requests`, `unittest`) for dazpy.

## Global Constraints

- Server changes must build against both SDK4 (Qt 4.8) and SDK6 (Qt 6.10) — use only `QAtomicInt` operations already proven portable in this codebase (`fetchAndAddOrdered`, `fetchAndStoreOrdered`), not `loadAcquire`/`storeRelease`/`load`/`store`, which aren't used anywhere else in the project.
- No new std::string built from `QString::toStdString()` may be stored or passed across the HTTP-thread/main-thread boundary (see project convention: avoids a CRT heap mismatch between Qt's msvcr100 and DazScriptServer's ucrtbase). String literals converted directly to `std::string` are unaffected and safe.
- This repo has no C++ unit test framework; C++ correctness is verified by a clean build plus one manual live-Studio smoke check, not automated tests.
- dazpy tests use `unittest.TestCase` with `unittest.mock.patch("dazpy._client._requests.post", ...)` — follow the existing `TestErrorMapping` pattern in `tests/test_dazpy.py`, run via `python tests.py unit` (no server/DAZ Studio needed).
- Do not implement daz-mcp-server changes — that's a separate repo with its own plan; this plan covers `daz-script-server` only (C++ server + `dazpy`).
- Work happens on a new local branch, not directly on `master`.

---

### Task 1: Create branch + SceneEventBroker busy-state tracking

**Files:**
- Modify: `include/SceneEventBroker.h`
- Modify: `src/SceneEventBroker.cpp`

**Interfaces:**
- Produces: `namespace MainThreadBusy { enum Reason { Idle, SceneLoading, SceneSaving, SceneClearing, Rendering }; std::string reasonMessage(Reason r); }` and `SceneEventBroker::isBusy() const -> bool`, `SceneEventBroker::busyReason() const -> MainThreadBusy::Reason` — consumed by Task 2/3.

- [ ] **Step 1: Create the branch**

```bash
git checkout -b feature/studio-busy-handling
```

- [ ] **Step 2: Add the `MainThreadBusy` namespace and atomic state to the header**

In `include/SceneEventBroker.h`, add after the existing includes (after line 9 `#include <QtCore/qtimer.h>`):

```cpp
#include <QtCore/qatomic.h>
#include <string>
```

Add after the `SceneEventFilter` namespace block (after its closing `}` before the `SubscriberQueue` section comment):

```cpp
// ─── Main-thread busy state ────────────────────────────────────────────────
// Tracks whether the main thread is currently inside a long synchronous
// operation (scene load/save/clear, render) so HTTP handlers can fail fast
// instead of blocking indefinitely on Qt::BlockingQueuedConnection.
namespace MainThreadBusy {
    enum Reason {
        Idle = 0,
        SceneLoading,
        SceneSaving,
        SceneClearing,
        Rendering
    };

    // Pure function over a plain literal — safe to call from any thread.
    inline std::string reasonMessage(Reason r) {
        switch (r) {
        case SceneLoading:  return "DAZ Studio is currently loading a scene";
        case SceneSaving:   return "DAZ Studio is currently saving a scene";
        case SceneClearing: return "DAZ Studio is currently clearing the scene";
        case Rendering:     return "DAZ Studio is currently rendering";
        default:            return "DAZ Studio is busy";
        }
    }
}
```

In the `SceneEventBroker` class body, add to the `public` section (right after `int subscriberCount() const;`):

```cpp
    // Thread-safe (QAtomicInt) — safe to call from any HTTP worker thread.
    bool isBusy() const {
        return m_busyState.fetchAndAddOrdered(0) != static_cast<int>(MainThreadBusy::Idle);
    }
    MainThreadBusy::Reason busyReason() const {
        return static_cast<MainThreadBusy::Reason>(m_busyState.fetchAndAddOrdered(0));
    }
```

Add to the `private` section (after `void dispatch(...)`, `QString makeEvent(...)`, `QString nodeInfoJson(...)` declarations):

```cpp
    void setBusyState(MainThreadBusy::Reason reason) {
        m_busyState.fetchAndStoreOrdered(static_cast<int>(reason));
    }
```

Add to the member variable list (after `bool m_started;`):

```cpp
    mutable QAtomicInt m_busyState;  // MainThreadBusy::Reason; written on main thread only
```

- [ ] **Step 3: Initialize the atomic in the constructor**

In `src/SceneEventBroker.cpp`, modify the constructor initializer list:

```cpp
SceneEventBroker::SceneEventBroker(QObject* parent)
    : QObject(parent)
    , m_pTimeDebounce(nullptr)
    , m_pSelectionDebounce(nullptr)
    , m_pendingTime(0)
    , m_started(false)
    , m_busyState(MainThreadBusy::Idle)
{
```

- [ ] **Step 4: Set/clear busy state in the existing scene-lifecycle slots**

In `src/SceneEventBroker.cpp`, modify each of these six slots to add one line each:

```cpp
void SceneEventBroker::onSceneLoadStarting() {
    setBusyState(MainThreadBusy::SceneLoading);
    dispatch(SceneEventFilter::Scene, makeEvent("scene.loading", "{}"));
}

void SceneEventBroker::onSceneLoaded() {
    setBusyState(MainThreadBusy::Idle);
    dispatch(SceneEventFilter::Scene, makeEvent("scene.loaded", "{}"));
}

void SceneEventBroker::onSceneSaveStarting(const QString& filename) {
    setBusyState(MainThreadBusy::SceneSaving);
    JsonBuilder j;
    j.startObject();
    j.addMember("filename", filename);
    j.finishObject();
    dispatch(SceneEventFilter::Scene, makeEvent("scene.saving", j.toString()));
}

void SceneEventBroker::onSceneSaved(const QString& filename) {
    setBusyState(MainThreadBusy::Idle);
    JsonBuilder j;
    j.startObject();
    j.addMember("filename", filename);
    j.finishObject();
    dispatch(SceneEventFilter::Scene, makeEvent("scene.saved", j.toString()));
}

void SceneEventBroker::onSceneClearStarting() {
    setBusyState(MainThreadBusy::SceneClearing);
    dispatch(SceneEventFilter::Scene, makeEvent("scene.clear_starting", "{}"));
}

void SceneEventBroker::onSceneCleared() {
    setBusyState(MainThreadBusy::Idle);
    dispatch(SceneEventFilter::Scene, makeEvent("scene.cleared", "{}"));
}
```

And the render slots:

```cpp
void SceneEventBroker::onAboutToRender(DzRenderer* /*r*/) {
    setBusyState(MainThreadBusy::Rendering);
    dispatch(SceneEventFilter::Render, makeEvent("render.started", "{}"));
}

void SceneEventBroker::onRenderFinished(DzRenderer* /*r*/) {
    setBusyState(MainThreadBusy::Idle);
    dispatch(SceneEventFilter::Render, makeEvent("render.finished", "{}"));
}
```

- [ ] **Step 5: Build to verify it compiles**

```bash
./build.sh build
```

Expected: build succeeds with no errors.

- [ ] **Step 6: Commit**

```bash
git add include/SceneEventBroker.h src/SceneEventBroker.cpp
git commit -m "feat: track main-thread busy state in SceneEventBroker"
```

---

### Task 2: STUDIO_BUSY error code + Retry-After header support

**Files:**
- Modify: `include/ErrorResponse.h`
- Modify: `src/ErrorResponse.cpp`
- Modify: `include/RequestHandler.h`
- Modify: `src/DzScriptServerPane.cpp`
- Modify: `include/DzScriptServerPane.h`

**Interfaces:**
- Consumes: `SceneEventBroker::isBusy()`, `SceneEventBroker::busyReason()`, `MainThreadBusy::reasonMessage()` from Task 1.
- Produces: `ErrorCode::STUDIO_BUSY`; `HttpContext::setHeader(name, value)`; `DzScriptServerPane::isMainThreadBusy() const -> bool`; `DzScriptServerPane::mainThreadBusyMessage() const -> std::string` — consumed by Task 3.

- [ ] **Step 1: Add the error code**

In `include/ErrorResponse.h`, add to the enum (after `SERVER_UNAVAILABLE,` in the `// 503 Service Unavailable` group):

```cpp
    // 503 Service Unavailable
    SERVER_UNAVAILABLE,
    STUDIO_BUSY,
```

- [ ] **Step 2: Wire the new code through `ErrorResponse.cpp`**

In `src/ErrorResponse.cpp`, add to `codeString()` (after the `SERVER_UNAVAILABLE` case):

```cpp
    case ErrorCode::SERVER_UNAVAILABLE:        return "SERVER_UNAVAILABLE";
    case ErrorCode::STUDIO_BUSY:               return "STUDIO_BUSY";
```

Add to `defaultMessage()` (after the `SERVER_UNAVAILABLE` case):

```cpp
    case ErrorCode::SERVER_UNAVAILABLE:
        return "Service temporarily unavailable";
    case ErrorCode::STUDIO_BUSY:
        return "DAZ Studio's main thread is busy; please retry shortly";
```

Add to `httpStatus()` (join the existing `SERVER_UNAVAILABLE` case):

```cpp
    case ErrorCode::SERVER_UNAVAILABLE:
    case ErrorCode::STUDIO_BUSY:
        return 503;
```

- [ ] **Step 3: Add response-header support to `HttpContext`**

In `include/RequestHandler.h`, add a member and helper to the `HttpContext` struct (after `std::map<std::string, std::string> queryParams;`):

```cpp
    std::map<std::string, std::string> responseHeaders;
```

Add a method (after `respond(...)`):

```cpp
    void setHeader(const std::string& name, const std::string& value) {
        responseHeaders[name] = value;
    }
```

- [ ] **Step 4: Apply response headers in `applyContext`**

In `src/DzScriptServerPane.cpp`, modify `applyContext` (around line 843):

```cpp
static void applyContext(const HttpContext& ctx, httplib::Response& res)
{
	res.status = ctx.responseStatus;
	if (!ctx.responseBody.empty())
		res.set_content(ctx.responseBody, "application/json");
	for (std::map<std::string, std::string>::const_iterator it = ctx.responseHeaders.begin();
	     it != ctx.responseHeaders.end(); ++it)
		res.set_header(it->first.c_str(), it->second.c_str());
}
```

- [ ] **Step 5: Add pane-level accessors**

In `include/DzScriptServerPane.h`, add after `std::string getMetricsJson() const;` (line 139):

```cpp
	// Main-thread busy state — called from HTTP threads (lock-free atomic read via SceneEventBroker)
	bool        isMainThreadBusy() const;
	std::string mainThreadBusyMessage() const;
```

In `src/DzScriptServerPane.cpp`, add after `getMetricsJson()`'s closing brace (after line 2717, before the `// ─── Async Execution (main thread) ───` comment):

```cpp

bool DzScriptServerPane::isMainThreadBusy() const
{
	return m_pEventBroker && m_pEventBroker->isBusy();
}

std::string DzScriptServerPane::mainThreadBusyMessage() const
{
	if (!m_pEventBroker) return "DAZ Studio is busy";
	return MainThreadBusy::reasonMessage(m_pEventBroker->busyReason());
}
```

- [ ] **Step 6: Build to verify it compiles**

```bash
./build.sh build
```

Expected: build succeeds with no errors.

- [ ] **Step 7: Commit**

```bash
git add include/ErrorResponse.h src/ErrorResponse.cpp include/RequestHandler.h \
        src/DzScriptServerPane.cpp include/DzScriptServerPane.h
git commit -m "feat: add STUDIO_BUSY error code and response header support"
```

---

### Task 3: Wire the busy check into affected HTTP handlers

**Files:**
- Modify: `src/RequestHandlers.cpp`

**Interfaces:**
- Consumes: `DzScriptServerPane::isMainThreadBusy()`, `DzScriptServerPane::mainThreadBusyMessage()`, `HttpContext::setHeader()`, `ErrorCode::STUDIO_BUSY` from Task 2.

- [ ] **Step 1: Add the shared busy-check helper**

In `src/RequestHandlers.cpp`, add after the `MiddlewareChain` section (after line 28, before `// ─── Concrete Middleware ───`):

```cpp
// ─── Shared busy-check helper ──────────────────────────────────────────────
// Called first by every handler that would otherwise block on
// Qt::BlockingQueuedConnection with no timeout. Returns true (and has
// already written the 503 response) if the main thread is currently busy.
static bool respondIfMainThreadBusy(DzScriptServerPane* pane, HttpContext& ctx)
{
    if (!pane->isMainThreadBusy()) return false;
    ctx.respond(503, ErrorResponse::build(ErrorCode::STUDIO_BUSY, pane->mainThreadBusyMessage()));
    ctx.setHeader("Retry-After", "2");
    return true;
}
```

- [ ] **Step 2: Add the check to `ExecuteScriptHandler::handle`**

```cpp
void ExecuteScriptHandler::handle(HttpContext& ctx)
{
    if (respondIfMainThreadBusy(m_pPane, ctx)) return;
    QByteArray bodyBytes(ctx.body.c_str(), (int)ctx.body.size());
```
(keep the rest of the existing body unchanged)

- [ ] **Step 3: Add the check to `ScriptExecuteHandler::handle`**

```cpp
void ScriptExecuteHandler::handle(HttpContext& ctx)
{
    if (respondIfMainThreadBusy(m_pPane, ctx)) return;
    std::string scriptText;
```
(keep the rest of the existing body unchanged)

- [ ] **Step 4: Add the check to `AsyncExecuteHandler::handle`**

```cpp
void AsyncExecuteHandler::handle(HttpContext& ctx)
{
    if (respondIfMainThreadBusy(m_pPane, ctx)) return;
    QByteArray bodyBytes(ctx.body.c_str(), (int)ctx.body.size());
```
(keep the rest of the existing body unchanged)

- [ ] **Step 5: Add the check to `AsyncScriptHandler::handle`**

```cpp
void AsyncScriptHandler::handle(HttpContext& ctx)
{
    if (respondIfMainThreadBusy(m_pPane, ctx)) return;
    std::string scriptText;
```
(keep the rest of the existing body unchanged)

- [ ] **Step 6: Add the check to `RenderHandler::handle`, `RenderBatchHandler::handle`, `RenderAnimationHandler::handle`**

```cpp
void RenderHandler::handle(HttpContext& ctx)
{
    if (respondIfMainThreadBusy(m_pPane, ctx)) return;
    QByteArray bodyBytes(ctx.body.c_str(), (int)ctx.body.size());
    HttpResult result;
    QMetaObject::invokeMethod(m_pPane, "handleAsyncRenderEnqueue",
        Qt::BlockingQueuedConnection,
        Q_RETURN_ARG(HttpResult, result),
        Q_ARG(QByteArray, bodyBytes));
    ctx.respond(result.first, std::string(result.second.constData(), result.second.size()));
}

RenderBatchHandler::RenderBatchHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void RenderBatchHandler::handle(HttpContext& ctx)
{
    if (respondIfMainThreadBusy(m_pPane, ctx)) return;
    QByteArray bodyBytes(ctx.body.c_str(), (int)ctx.body.size());
    HttpResult result;
    QMetaObject::invokeMethod(m_pPane, "handleAsyncRenderBatchEnqueue",
        Qt::BlockingQueuedConnection,
        Q_RETURN_ARG(HttpResult, result),
        Q_ARG(QByteArray, bodyBytes));
    ctx.respond(result.first, std::string(result.second.constData(), result.second.size()));
}

RenderAnimationHandler::RenderAnimationHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void RenderAnimationHandler::handle(HttpContext& ctx)
{
    if (respondIfMainThreadBusy(m_pPane, ctx)) return;
    QByteArray bodyBytes(ctx.body.c_str(), (int)ctx.body.size());
    HttpResult result;
    QMetaObject::invokeMethod(m_pPane, "handleAsyncRenderAnimationEnqueue",
        Qt::BlockingQueuedConnection,
        Q_RETURN_ARG(HttpResult, result),
        Q_ARG(QByteArray, bodyBytes));
    ctx.respond(result.first, std::string(result.second.constData(), result.second.size()));
}
```

- [ ] **Step 7: Build to verify it compiles**

```bash
./build.sh build
```

Expected: build succeeds with no errors.

- [ ] **Step 8: Commit**

```bash
git add src/RequestHandlers.cpp
git commit -m "feat: fail fast with 503 STUDIO_BUSY instead of blocking on a busy main thread"
```

---

### Task 4: Manual smoke verification (live DAZ Studio)

**Files:** none (verification only)

**Interfaces:** none — exercises Tasks 1-3 end-to-end.

- [ ] **Step 1: Install the built plugin and start DAZ Studio**

```bash
./build.sh install --clean
```

Then launch DAZ Studio and confirm the DazScriptServer pane shows the server running (default `127.0.0.1:18811`).

- [ ] **Step 2: Confirm the baseline (idle) case still works**

```bash
curl -s -X POST http://127.0.0.1:18811/execute \
  -H "X-API-Token: $(cat ~/.daz3d/dazscriptserver_token.txt)" \
  -H "Content-Type: application/json" \
  -d '{"script":"1+1;"}'
```

Expected: HTTP 200 with `{"success":true,"result":2,...}`.

- [ ] **Step 3: Trigger a busy state and confirm the fast 503**

In the DAZ Studio UI, start loading a scene of nontrivial size (or trigger a render via the UI's Render button on any loaded scene). While that is in progress, in a separate terminal run:

```bash
curl -s -o /dev/null -w "%{http_code} in %{time_total}s\n" -X POST http://127.0.0.1:18811/execute \
  -H "X-API-Token: $(cat ~/.daz3d/dazscriptserver_token.txt)" \
  -H "Content-Type: application/json" \
  -d '{"script":"1+1;"}'
```

Expected: `503` returned in well under 1 second (not hanging until the load/render finishes). Also run the same curl with `-i` instead of `-o /dev/null -w ...` once to confirm the body contains `"error_code":"STUDIO_BUSY"` and the response includes a `Retry-After: 2` header.

- [ ] **Step 4: Confirm normal operation resumes after the busy state clears**

Once the scene load/render finishes, repeat Step 2's curl command and confirm it again returns `200` with the correct result.

- [ ] **Step 5: Record the result**

No commit for this task (verification only) — proceed to Task 5 once all four expectations above are confirmed. If any step fails, stop and diagnose before continuing (see `superpowers:systematic-debugging`).

---

### Task 5: dazpy — `DazBusyError` hierarchy and `_raise_for_error` centralization

**Files:**
- Modify: `dazpy/exceptions.py`
- Modify: `dazpy/_client.py`
- Modify: `tests/test_dazpy.py`

**Interfaces:**
- Produces: `dazpy.exceptions.DazBusyError(DazError)` with `reason: str`, `retry_after: float`; `dazpy.exceptions.StudioBusyError(DazBusyError)`; `dazpy.exceptions.ConcurrencyLimitError(DazBusyError)`; `dazpy._client._raise_for_error(resp: requests.Response) -> None` — consumed by Task 6.

- [ ] **Step 1: Write the failing tests**

In `tests/test_dazpy.py`, add these methods to the existing `TestErrorMapping` class (after `test_script_syntax_error_line_number`, before `test_connection_error`):

```python
    def test_studio_busy_error_503(self):
        import requests as req
        resp = MagicMock(spec=req.Response)
        resp.status_code = 503
        resp.json.return_value = {
            "success": False,
            "error_code": "STUDIO_BUSY",
            "error": "DAZ Studio's main thread is busy; please retry shortly",
            "detail": "DAZ Studio is currently loading a scene",
        }
        resp.headers = {"Retry-After": "2"}
        resp.text = ""
        client = DazClient.__new__(DazClient)
        object.__setattr__(client, "_base", "http://127.0.0.1:18811")
        object.__setattr__(client, "_token", "")
        object.__setattr__(client, "_timeout", 30.0)
        with patch("dazpy._client._requests.post", return_value=resp):
            with self.assertRaises(exceptions.StudioBusyError) as ctx:
                client.execute("1+1;")
            self.assertIsInstance(ctx.exception, exceptions.DazBusyError)
            self.assertEqual(ctx.exception.retry_after, 2.0)
            self.assertIn("loading a scene", ctx.exception.reason)

    def test_concurrency_limit_error_429(self):
        import requests as req
        resp = MagicMock(spec=req.Response)
        resp.status_code = 429
        resp.json.return_value = {
            "success": False,
            "error_code": "CONCURRENT_LIMIT_EXCEEDED",
            "error": "Server busy: maximum concurrent requests reached, please retry",
        }
        resp.headers = {}
        resp.text = ""
        client = DazClient.__new__(DazClient)
        object.__setattr__(client, "_base", "http://127.0.0.1:18811")
        object.__setattr__(client, "_token", "")
        object.__setattr__(client, "_timeout", 30.0)
        with patch("dazpy._client._requests.post", return_value=resp):
            with self.assertRaises(exceptions.ConcurrencyLimitError) as ctx:
                client.execute("1+1;")
            self.assertIsInstance(ctx.exception, exceptions.DazBusyError)
            self.assertNotIsInstance(ctx.exception, exceptions.ScriptRuntimeError)
            self.assertEqual(ctx.exception.retry_after, 2.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest tests/test_dazpy.py -k "test_studio_busy_error_503 or test_concurrency_limit_error_429" -v
```

Expected: FAIL — `AttributeError: module 'dazpy.exceptions' has no attribute 'StudioBusyError'` (or the client raises `ScriptRuntimeError` instead of the expected type once the attribute exists but before `_client.py` is updated).

- [ ] **Step 3: Add the exception hierarchy**

In `dazpy/exceptions.py`, add after the `AuthenticationError` class (before `class ScriptError(DazError):`):

```python
class DazBusyError(DazError):
    """Base class for transient "DAZ Studio is busy, please retry" conditions.

    Attributes:
        reason: Human-readable explanation of why the server is busy.
        retry_after: Server-suggested seconds to wait before retrying.
    """

    def __init__(self, message: str, reason: str = "", retry_after: float = 2.0):
        super().__init__(message)
        self.reason = reason
        self.retry_after = retry_after


class StudioBusyError(DazBusyError):
    """Raised on HTTP 503 STUDIO_BUSY: DAZ Studio's main thread is occupied
    with a scene load, save, clear, or render and cannot service the request."""


class ConcurrencyLimitError(DazBusyError):
    """Raised on HTTP 429 CONCURRENT_LIMIT_EXCEEDED: too many requests are
    already in flight against the server."""
```

- [ ] **Step 4: Add `_raise_for_error` and route both error codes through it**

In `dazpy/_client.py`, replace lines 8-54 (from the `from .exceptions import` block through the end of `_map_response`) with:

```python
from .exceptions import (
    AuthenticationError,
    ConcurrencyLimitError,
    ConnectionError,
    DazBusyError,
    ScriptRuntimeError,
    ScriptSyntaxError,
    StudioBusyError,
    TimeoutError,
)
from ._result import ExecutionResult


_TOKEN_FILE = os.path.expanduser("~/.daz3d/dazscriptserver_token.txt")
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 18811


def _load_token() -> str:
    if os.path.exists(_TOKEN_FILE):
        with open(_TOKEN_FILE) as f:
            return f.read().strip()
    return ""


def _parse_retry_after(resp: _requests.Response) -> float:
    raw = resp.headers.get("Retry-After", "")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 2.0


def _raise_for_error(resp: _requests.Response) -> None:
    """Raise a typed exception for authentication or server-busy responses.

    Leaves 2xx responses (and DazScript's own success:false runtime/syntax
    errors, which use HTTP 200) for the caller to handle.
    """
    status = resp.status_code
    if status == 401 or status == 403:
        raise AuthenticationError(f"HTTP {status}: {resp.text[:200]}")
    if status < 400:
        return
    data = resp.json()
    error_code = data.get("error_code", "")
    error_msg = data.get("error") or f"HTTP {status}"
    retry_after = _parse_retry_after(resp)
    if error_code == "STUDIO_BUSY":
        raise StudioBusyError(error_msg, reason=data.get("detail", error_msg), retry_after=retry_after)
    if error_code == "CONCURRENT_LIMIT_EXCEEDED":
        raise ConcurrencyLimitError(error_msg, reason=error_msg, retry_after=retry_after)


def _map_response(resp: _requests.Response, script: str = "") -> ExecutionResult:
    _raise_for_error(resp)

    data = resp.json()
    request_id = data.get("request_id", "")

    if not data.get("success", True):
        error_msg = data.get("error", "Script failed")
        output = data.get("output", [])
        # SyntaxError comes from the parser; runtime errors (TypeError, ReferenceError,
        # Error, etc.) also include "Line N:" but never say "SyntaxError" explicitly.
        if "SyntaxError" in error_msg:
            raise ScriptSyntaxError(error_msg, script=script, request_id=request_id, output=output)
        raise ScriptRuntimeError(error_msg, script=script, request_id=request_id, output=output)

    return ExecutionResult(
        value=data.get("result"),
        output=data.get("output", []),
        request_id=request_id,
        success=True,
        error="",
        duration_ms=data.get("duration_ms", 0.0),
    )
```

(This removes the old inline `if status == 401 or status == 403: raise AuthenticationError(...)` from `_map_response` since `_raise_for_error` now handles it, and fixes the pre-existing bug where `429` fell through to `ScriptRuntimeError`.)

- [ ] **Step 5: Run the tests to verify they pass**

```bash
python -m pytest tests/test_dazpy.py -k "test_studio_busy_error_503 or test_concurrency_limit_error_429" -v
```

Expected: PASS (2 tests).

- [ ] **Step 6: Run the full existing dazpy unit suite to check for regressions**

```bash
python tests.py unit
```

Expected: all tests pass, including the pre-existing `test_auth_error_401`, `test_script_runtime_error`, `test_script_syntax_error_line_number`, and `test_connection_error` in `TestErrorMapping` (these exercise the code paths just refactored).

- [ ] **Step 7: Commit**

```bash
git add dazpy/exceptions.py dazpy/_client.py tests/test_dazpy.py
git commit -m "feat: add DazBusyError hierarchy and fix 429 misreported as ScriptRuntimeError"
```

---

### Task 6: dazpy — opt-in `retry_on_busy` for busy-prone methods

**Files:**
- Modify: `dazpy/_client.py`
- Modify: `tests/test_dazpy.py`

**Interfaces:**
- Consumes: `dazpy.exceptions.DazBusyError`, `dazpy._client._raise_for_error` from Task 5.
- Produces: `retry_on_busy: bool = False, max_wait: float = 30.0` keyword arguments on `DazClient.execute`, `execute_file`, `execute_async_submit`, `render_submit`, `render_batch_submit`, `render_animation_submit`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_dazpy.py`, add these methods to `TestErrorMapping` (after `test_concurrency_limit_error_429`):

```python
    def _busy_resp(self):
        import requests as req
        resp = MagicMock(spec=req.Response)
        resp.status_code = 503
        resp.json.return_value = {
            "success": False,
            "error_code": "STUDIO_BUSY",
            "error": "DAZ Studio's main thread is busy; please retry shortly",
            "detail": "DAZ Studio is currently rendering",
        }
        resp.headers = {"Retry-After": "1"}
        resp.text = ""
        return resp

    def _success_resp(self):
        import requests as req
        resp = MagicMock(spec=req.Response)
        resp.status_code = 200
        resp.json.return_value = {"success": True, "result": 2, "output": [], "request_id": "ok1"}
        resp.headers = {}
        resp.text = ""
        return resp

    def _busy_client(self):
        client = DazClient.__new__(DazClient)
        object.__setattr__(client, "_base", "http://127.0.0.1:18811")
        object.__setattr__(client, "_token", "")
        object.__setattr__(client, "_timeout", 30.0)
        return client

    def test_execute_without_retry_on_busy_raises_immediately(self):
        client = self._busy_client()
        with patch("dazpy._client._requests.post", return_value=self._busy_resp()) as post:
            with self.assertRaises(exceptions.StudioBusyError):
                client.execute("1+1;")
            self.assertEqual(post.call_count, 1)

    def test_execute_retry_on_busy_succeeds_after_retries(self):
        client = self._busy_client()
        responses = [self._busy_resp(), self._busy_resp(), self._success_resp()]
        with patch("dazpy._client._requests.post", side_effect=responses) as post:
            with patch("dazpy._client.time.sleep") as sleep:
                result = client.execute("1+1;", retry_on_busy=True, max_wait=10.0)
        self.assertEqual(result.value, 2)
        self.assertEqual(post.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_execute_retry_on_busy_gives_up_after_max_wait(self):
        client = self._busy_client()
        with patch("dazpy._client._requests.post", return_value=self._busy_resp()):
            with patch("dazpy._client.time.sleep"):
                with patch(
                    "dazpy._client.time.monotonic",
                    side_effect=[0.0, 0.0, 5.0, 11.0, 20.0, 20.0],
                ):
                    with self.assertRaises(exceptions.StudioBusyError):
                        client.execute("1+1;", retry_on_busy=True, max_wait=10.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest tests/test_dazpy.py -k "retry_on_busy" -v
```

Expected: FAIL — `TypeError: execute() got an unexpected keyword argument 'retry_on_busy'`.

- [ ] **Step 3: Add `import time` and the retry wrapper**

In `dazpy/_client.py`, add to the imports at the top (after `import re`):

```python
import time
```

Add this method to `DazClient` (after `_get`, before `execute`):

```python
    def _with_busy_retry(self, fn, retry_on_busy: bool, max_wait: float):
        """Run *fn* (a zero-arg callable), retrying on DazBusyError while
        *retry_on_busy* is true, up to *max_wait* seconds total."""
        if not retry_on_busy:
            return fn()
        deadline = time.monotonic() + max_wait
        backoff = 1.0
        while True:
            try:
                return fn()
            except DazBusyError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise
                time.sleep(min(backoff, remaining))
                backoff = min(backoff + 1.0, 5.0)
```

- [ ] **Step 4: Wire `execute` and `execute_file` through the retry wrapper**

Replace the bodies of `execute` and `execute_file` in `dazpy/_client.py`:

```python
    def execute(
        self, script: str, args: object = None, *, retry_on_busy: bool = False, max_wait: float = 30.0
    ) -> ExecutionResult:
        """Execute a DazScript string synchronously.

        Args:
            script: DazScript source code to execute.
            args: Optional value passed into the script as ``getArguments()[0]``.
                Must be JSON-serialisable.
            retry_on_busy: If ``True``, transparently retry with backoff when
                the server reports ``StudioBusyError``/``ConcurrencyLimitError``,
                instead of raising immediately.
            max_wait: Maximum total seconds to retry when *retry_on_busy* is
                ``True``, before re-raising the busy error.

        Returns:
            The execution result containing the script return value and any
            console output.

        Raises:
            ConnectionError: If the server cannot be reached.
            AuthenticationError: If the token is invalid or the IP is blocked.
            ScriptSyntaxError: If the script contains a parse error.
            ScriptRuntimeError: If the script raises a runtime exception.
            StudioBusyError: If DAZ Studio's main thread is busy and
                *retry_on_busy* is ``False`` or *max_wait* is exceeded.
            ConcurrencyLimitError: If too many concurrent requests are in
                flight and *retry_on_busy* is ``False`` or *max_wait* is
                exceeded.
            TimeoutError: If the request exceeds *timeout* seconds.
        """
        payload: dict = {"script": script}
        if args is not None:
            payload["args"] = args

        def _do():
            resp = self._post("/execute", payload)
            return _map_response(resp, script=script)

        return self._with_busy_retry(_do, retry_on_busy, max_wait)

    def execute_file(
        self, script_file: str, args: object = None, *, retry_on_busy: bool = False, max_wait: float = 30.0
    ) -> ExecutionResult:
        """Execute a ``.dsa`` script file that resides on the DAZ Studio host.

        Args:
            script_file: Absolute path to the ``.dsa`` file on the server host.
            args: Optional argument passed to the script.
            retry_on_busy: If ``True``, transparently retry with backoff when
                the server reports ``StudioBusyError``/``ConcurrencyLimitError``,
                instead of raising immediately.
            max_wait: Maximum total seconds to retry when *retry_on_busy* is
                ``True``, before re-raising the busy error.

        Returns:
            The execution result.

        Raises:
            ConnectionError: If the server cannot be reached.
            AuthenticationError: On auth failure.
            ScriptSyntaxError: On parse error.
            ScriptRuntimeError: On runtime error.
            StudioBusyError: If DAZ Studio's main thread is busy and
                *retry_on_busy* is ``False`` or *max_wait* is exceeded.
            ConcurrencyLimitError: If too many concurrent requests are in
                flight and *retry_on_busy* is ``False`` or *max_wait* is
                exceeded.
            TimeoutError: On HTTP timeout.
        """
        payload: dict = {"scriptFile": script_file}
        if args is not None:
            payload["args"] = args

        def _do():
            resp = self._post("/execute", payload)
            return _map_response(resp)

        return self._with_busy_retry(_do, retry_on_busy, max_wait)
```

- [ ] **Step 5: Wire `execute_async_submit` through `_raise_for_error` and the retry wrapper**

Replace the body of `execute_async_submit`:

```python
    def execute_async_submit(
        self, script: str, args: object = None, *, retry_on_busy: bool = False, max_wait: float = 30.0
    ) -> str:
        """Submit a script for asynchronous execution and return immediately.

        Args:
            script: DazScript source code.
            args: Optional argument for the script.
            retry_on_busy: If ``True``, transparently retry with backoff when
                the server reports ``StudioBusyError``/``ConcurrencyLimitError``,
                instead of raising immediately.
            max_wait: Maximum total seconds to retry when *retry_on_busy* is
                ``True``, before re-raising the busy error.

        Returns:
            The server-assigned ``request_id`` string.  Use it with
            :meth:`get_request_status` or :meth:`get_request_result` to poll
            for the outcome.

        Raises:
            ConnectionError: If the server cannot be reached.
            AuthenticationError: On auth failure.
            StudioBusyError: If DAZ Studio's main thread is busy and
                *retry_on_busy* is ``False`` or *max_wait* is exceeded.
            ConcurrencyLimitError: If too many concurrent requests are in
                flight and *retry_on_busy* is ``False`` or *max_wait* is
                exceeded.
        """
        payload: dict = {"script": script}
        if args is not None:
            payload["args"] = args

        def _do():
            resp = self._post("/execute/async", payload)
            _raise_for_error(resp)
            return resp.json().get("request_id", "")

        return self._with_busy_retry(_do, retry_on_busy, max_wait)
```

- [ ] **Step 6: Wire the three render-submit methods through `_raise_for_error` and the retry wrapper**

In `render_submit`, replace:

```python
        engine: str = "",
        iray_samples: int = 0,
        reset_morphs: bool = False,
    ) -> dict:
```

with:

```python
        engine: str = "",
        iray_samples: int = 0,
        reset_morphs: bool = False,
        retry_on_busy: bool = False,
        max_wait: float = 30.0,
    ) -> dict:
```

and add `retry_on_busy`/`max_wait` docstring entries plus `StudioBusyError`/`ConcurrencyLimitError` to its `Raises:` section (mirroring the pattern used in `execute`'s docstring above), then replace its final two lines:

```python
        resp = self._post("/render", payload)
        if resp.status_code in (401, 403):
            raise AuthenticationError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()
```

with:

```python
        def _do():
            resp = self._post("/render", payload)
            _raise_for_error(resp)
            return resp.json()

        return self._with_busy_retry(_do, retry_on_busy, max_wait)
```

In `render_batch_submit`, replace:

```python
    def render_batch_submit(self, variants: list, base: dict | None = None) -> dict:
```

with:

```python
    def render_batch_submit(
        self, variants: list, base: dict | None = None, *, retry_on_busy: bool = False, max_wait: float = 30.0
    ) -> dict:
```

add `retry_on_busy`/`max_wait` docstring entries plus `StudioBusyError`/`ConcurrencyLimitError` to its `Raises:` section (mirroring the pattern used in `execute`'s docstring above), then replace its final two lines:

```python
        resp = self._post("/render/batch", payload)
        if resp.status_code in (401, 403):
            raise AuthenticationError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()
```

with:

```python
        def _do():
            resp = self._post("/render/batch", payload)
            _raise_for_error(resp)
            return resp.json()

        return self._with_busy_retry(_do, retry_on_busy, max_wait)
```

In `render_animation_submit`, replace:

```python
        camera: str = "",
        engine: str = "",
    ) -> dict:
```

with:

```python
        camera: str = "",
        engine: str = "",
        retry_on_busy: bool = False,
        max_wait: float = 30.0,
    ) -> dict:
```

add `retry_on_busy`/`max_wait` docstring entries plus `StudioBusyError`/`ConcurrencyLimitError` to its `Raises:` section (mirroring the pattern used in `execute`'s docstring above), then replace its final two lines:

```python
        resp = self._post("/render/animation", payload)
        if resp.status_code in (401, 403):
            raise AuthenticationError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()
```

with:

```python
        def _do():
            resp = self._post("/render/animation", payload)
            _raise_for_error(resp)
            return resp.json()

        return self._with_busy_retry(_do, retry_on_busy, max_wait)
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
python -m pytest tests/test_dazpy.py -k "retry_on_busy" -v
```

Expected: PASS (3 tests).

- [ ] **Step 8: Run the full existing dazpy unit suite to check for regressions**

```bash
python tests.py unit
```

Expected: all tests pass — in particular any existing tests that call `render_submit`/`render_batch_submit`/`render_animation_submit`/`execute_async_submit` and assert on their return shape, since those methods' bodies changed.

- [ ] **Step 9: Commit**

```bash
git add dazpy/_client.py tests/test_dazpy.py
git commit -m "feat: add opt-in retry_on_busy/max_wait to busy-prone dazpy methods"
```

---

## Follow-ups (not part of this plan)

- **daz-mcp-server**: add a `DazBusyError` case to `_errors.py::handle_dazpy_error` (that repo), raising `ToolError(f"DAZ Studio is busy ({exc.reason}). Try again in a few seconds.")`. Needs its own plan in that repo, once this plan ships.
- Investigate why `GET /requests` reportedly hung in the originally observed session, despite not using `BlockingQueuedConnection` (see spec's non-goals).
