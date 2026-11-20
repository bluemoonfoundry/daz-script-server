# dazpy Plugin Version Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** dazpy warns only when the connected plugin is older than the minimum it needs, re-checks when the target may have changed, and exposes the result to code; shipped as 2.13.0.

**Architecture:** All state and policy live in one new class, `VersionTracker`, in `dazpy/_version.py` (pure, thread-safe, no I/O). `DazClient` and `AsyncDazClient` each own a tracker and only do the I/O: ask the tracker whether to check, fetch `/status`, hand the result back, and report transport failures and `X-Server-Instance-Id` headers to it.

**Tech Stack:** Python 3.10+ (dazpy floor), `requests` (sync), `httpx` + `respx` (async tests), `unittest`/`pytest`.

**Spec:** `docs/superpowers/specs/2026-11-16-dazpy-plugin-version-check-design.md`

## Global Constraints

- `MIN_SERVER_VERSION = "2.12"`; compare plugin `(major, minor)` against it, never against `dazpy.__version__`.
- Release version `2.13.0` in every location `scripts/check_version_consistency.py` checks.
- No plugin (C++) or HTTP API changes.
- A version check must never make a request fail: every exception inside the check and the callback is swallowed (callback errors logged at `logging.debug`).
- `check_version=False` → no `/status` calls, no callbacks, no warnings.
- Warning text (exact, with `{}` fields filled):
  `Daz Studio plugin at {server_url} is version {server_version}; dazpy {client_version} needs {min_server_version} or newer. Upgrade the DazScriptServer plugin in the Daz Studio instance at that address (https://github.com/bluemoonfoundry/daz-script-server/releases). If you can't, a dazpy release matching the plugin also works.`
- Live Studio: never run the full integration suite; only the scoped check in Task 5, and only after the user says Studio is up.
- Every push, PR, merge and tag waits for the user's explicit go-ahead.

## Review Focus

1. Studio not running at the client's first request, started later → the next request re-checks and warns/clears correctly (Task 2, Task 3 tests).
2. Same old plugin, many reconnects → exactly one warning per running plugin, not one per re-check (Task 1 test).
3. Plugin without `X-Server-Instance-Id` / `server_instance_id` (or a mocked response whose `headers.get` returns a non-string) → no re-check loop: one `/status` across many requests (Task 1, Task 2 tests).
4. A callback that raises → the user's request still returns its result (Task 2 test).
5. Two concurrent first requests on the async client → one `/status` (Task 3 test).

---

### Task 1: `VersionCheck`, `MIN_SERVER_VERSION`, `VersionTracker`

**Files:**
- Modify: `dazpy/_version.py`
- Create: `tests/test_version_tracker.py`

**Interfaces:**
- Produces (all in `dazpy._version`):
  - `MIN_SERVER_VERSION: str = "2.12"` — docstring/comment: raise only when dazpy starts calling a plugin route or field older plugins lack.
  - `@dataclass(frozen=True) class VersionCheck` with fields, in order: `server_url: str`, `server_version: str | None`, `min_server_version: str`, `client_version: str`, `server_instance_id: str | None`, `compatible: bool | None`, `message: str | None`.
  - `evaluate_server_version(server_url: str, server_version: str | None, server_instance_id: str | None) -> VersionCheck` — `compatible` is `None` when either version doesn't parse, else `parse_version(server) >= parse_version(MIN_SERVER_VERSION)`; `message` is the Global Constraints text when `compatible is False`, else `None`. Reads `MIN_SERVER_VERSION` and `client_version()` at call time (tests patch them).
  - `class VersionTracker`:
    - `__init__(self, enabled: bool = True, on_version_check: Callable[[VersionCheck], object] | None = None)`
    - `latest -> VersionCheck | None` (property)
    - `claim_check() -> bool` — atomically: True (and marks in-progress) only if enabled, stale, and no check in progress.
    - `finish_check(check: VersionCheck | None) -> None` — clears in-progress. `None` (check failed) leaves it stale. Otherwise stores `latest`, clears stale, remembers `check.server_instance_id` (if a str), warns if `compatible is False` and its dedupe key is new, then calls the callback.
    - `mark_stale() -> None` — no-op when disabled.
    - `observe_instance(instance_id: object) -> None` — no-op when disabled or when `instance_id` isn't a non-empty `str`. If no instance is remembered yet, remember it. If it differs from the remembered one, mark stale.
  - Dedupe key: `(server_url, server_instance_id)` when the ID is a str, else `(server_url, server_version)`.
  - Lock: one `threading.Lock` guards all state; the warning and callback run **outside** the lock.
  - Warning: `warnings.warn(check.message, ServerVersionWarning, stacklevel=_first_external_stacklevel())`.
- Keep `parse_version`, `client_version`, `server_version_from_status`, `_first_external_stacklevel`. Add `server_instance_id_from_status(data: object) -> str | None` (the `server_instance_id` str field, else `None`). Leave `warn_if_server_older` in place until Task 4 (clients still import it).

- [ ] **Step 1: Write the failing tests** in `tests/test_version_tracker.py` (pytest style). Patch `dazpy._version.client_version` → `"2.13.0"`. Tests:
  - `test_evaluate_compatible_at_minimum`: `evaluate_server_version("http://h:1", "2.12.0", "i1")` → `compatible is True`, `message is None`, `min_server_version == "2.12"`, `client_version == "2.13.0"`, `server_instance_id == "i1"`.
  - `test_evaluate_newer_plugin_ok`: `"2.13.4"` and `"3.0.0"` → `compatible is True`.
  - `test_evaluate_older_plugin`: `"2.11.9"` → `compatible is False`; message contains `"http://h:1"`, `"2.11.9"`, `"2.13.0"`, `"2.12 or newer"`, `"daz-script-server/releases"`; message does **not** contain `"pip install"`.
  - `test_evaluate_unknown_version`: `None` and `"garbage"` → `compatible is None`, `message is None`.
  - `test_tracker_first_claim_then_busy`: new tracker: `claim_check()` True, second `claim_check()` False (in progress).
  - `test_tracker_failed_check_stays_stale`: claim, `finish_check(None)`, `claim_check()` True again; `latest is None`.
  - `test_tracker_success_not_stale`: claim, finish with a compatible check → `claim_check()` False; `latest` is that check.
  - `test_tracker_mark_stale_rechecks`: after success, `mark_stale()` → `claim_check()` True.
  - `test_tracker_instance_change_rechecks`: success with `server_instance_id="i1"`; `observe_instance("i1")` → `claim_check()` False; `observe_instance("i2")` → `claim_check()` True.
  - `test_tracker_ignores_missing_instance`: success with ID `None`; `observe_instance(None)`, `observe_instance(MagicMock())`, `observe_instance("")` → `claim_check()` False each time.
  - `test_tracker_first_observed_instance_is_remembered`: success with ID `None`; `observe_instance("i1")` → not stale; `observe_instance("i2")` → stale.
  - `test_tracker_warns_once_per_instance`: finish three incompatible checks with ID `"i1"` (claim before each, `mark_stale` between) under `warnings.catch_warnings(record=True)` + `simplefilter("always")` → exactly one `ServerVersionWarning`; then one with ID `"i2"` → a second warning.
  - `test_tracker_warns_once_without_instance`: two incompatible checks, ID `None`, same version → one warning.
  - `test_tracker_callback_every_check`: callback list-appends; finish compatible, then (stale, claim) incompatible → callback got both checks in order.
  - `test_tracker_callback_exception_swallowed`: callback raises `RuntimeError`; `finish_check(...)` does not raise; `latest` is set.
  - `test_tracker_disabled`: `VersionTracker(enabled=False)`: `claim_check()` False; `mark_stale()`/`observe_instance("x")` then `claim_check()` still False.
  - `test_claim_is_atomic_across_threads`: 20 threads call `claim_check()` on a fresh tracker via a `threading.Barrier` → exactly one True.

- [ ] **Step 2: Run to verify failure**
  Run: `python -m pytest tests/test_version_tracker.py -q`
  Expected: ImportError / failures for the missing names.

- [ ] **Step 3: Implement** the Interfaces above in `dazpy/_version.py`.

- [ ] **Step 4: Run to verify pass**
  Run: `python -m pytest tests/test_version_tracker.py -q`
  Expected: all pass.

- [ ] **Step 5: Commit**
  ```bash
  git add dazpy/_version.py tests/test_version_tracker.py
  git commit -m "feat(dazpy): VersionTracker and minimum plugin version"
  ```

### Task 2: `DazClient` uses the tracker

**Files:**
- Modify: `dazpy/_client.py` (`__init__` ~162-175, `_check_server_version` ~194-206, `server_version` ~208-216, `_post`/`_get`/`_delete` ~218-265, class docstring ~140-155)
- Test: `tests/test_dazpy.py` — rewrite `class TestServerVersionCheck` (~line 8293)

**Interfaces:**
- Consumes: Task 1's `VersionTracker`, `VersionCheck`, `evaluate_server_version`, `server_version_from_status`, `server_instance_id_from_status`.
- Produces:
  - `DazClient.__init__(..., check_version: bool = True, on_version_check: Callable[[VersionCheck], object] | None = None)` — new kwarg last. Docstring: callback runs after every completed check, on the thread that ran it; exceptions swallowed.
  - `self._versions = VersionTracker(enabled=check_version, on_version_check=on_version_check)`; class-level default `_versions = VersionTracker(enabled=False)` replaces `_version_checked` (instances built without `__init__` stay check-free).
  - `DazClient.version_check -> VersionCheck | None` property (`self._versions.latest`).
  - `server_version` property unchanged in behaviour; it also returns `latest.server_version` when a check has one.
  - `_check_server_version()`: `if not claim_check(): return`; GET `/status`; on any exception `finish_check(None)`; else `finish_check(evaluate_server_version(self._base, version, instance_id))`, where `instance_id` is the status JSON's `server_instance_id` or, failing that, the response's `X-Server-Instance-Id` header (only if a str).
  - `_post`/`_get`/`_delete`: on the three transport `except` branches call `self._versions.mark_stale()` before raising; on a returned response call `self._versions.observe_instance(resp.headers.get("X-Server-Instance-Id"))`.

- [ ] **Step 1: Rewrite the tests.** Keep the `_client(...)` helper; set `status.headers = {}` and `execute.headers = {}` by default, and let the helper take `status_side_effect` (a list of returns/exceptions for `session.get`) and `execute_headers`. Patch `dazpy._version.MIN_SERVER_VERSION` → `"2.12"` and `dazpy._version.client_version` → `"2.13.0"`. Tests:
  - `test_older_than_minimum_warns_once`: status `{"version": "2.11.0"}`; 3 executes → 1 warning containing `"2.11.0"` and `"2.12 or newer"`; `session.get.call_count == 1`; `client.version_check.compatible is False`; `client.server_version == "2.11.0"`.
  - `test_minimum_or_newer_does_not_warn`: `"2.12.0"`, `"2.12.7"`, `"2.13.0"`, `"3.0.0"` → no warning; `version_check.compatible is True`.
  - `test_plugin_one_minor_behind_dazpy_does_not_warn`: client version `"2.13.0"`, plugin `"2.12.0"` → no warning (the regression this release exists for).
  - `test_check_failures_are_ignored`: as today (`{}`, `"garbage"`, `ConnectionError` on `/status`) → no warning, `session.post` called once.
  - `test_unreachable_first_check_retries`: `session.get.side_effect = [requests.ConnectionError("down"), status(2.11.0)]`; execute twice → second execute triggers a second `/status` and one warning.
  - `test_transport_failure_triggers_recheck`: first execute ok (status 2.12.0, `get.call_count == 1`); next `session.post` raises `requests.ConnectionError` → `dazpy.exceptions.ConnectionError`; restore post; execute → `get.call_count == 2`.
  - `test_instance_change_triggers_recheck`: status `{"version": "2.12.0", "server_instance_id": "i1"}`; execute response header `X-Server-Instance-Id: i1` → no extra `/status`; switch execute header to `i2` → the **next** execute does `/status` again (`call_count == 2`).
  - `test_no_instance_id_no_loop`: status without ID, execute responses without header; 5 executes → `get.call_count == 1`.
  - `test_callback_receives_checks`: `on_version_check=seen.append`; execute → `len(seen) == 1` and `seen[0].server_url == "http://127.0.0.1:18811"`.
  - `test_callback_exception_does_not_break_request`: callback raises → `execute` returns its result normally.
  - `test_delete_as_first_request_checks_version`: keep (status 2.11.0).
  - `test_check_version_false_skips_status_call`: keep; also `client.version_check is None`.

- [ ] **Step 2: Run to verify failure**
  Run: `python -m pytest tests/test_dazpy.py -k TestServerVersionCheck -q`
  Expected: new tests fail (no `on_version_check`, old comparison).

- [ ] **Step 3: Implement** the Interfaces above in `dazpy/_client.py`.

- [ ] **Step 4: Run to verify pass, plus the whole unit file**
  Run: `python -m pytest tests/test_dazpy.py tests/test_version_tracker.py tests/test_recipe_facade.py -q`
  Expected: all pass (no live Studio needed; these files don't hit 18811).

- [ ] **Step 5: Commit**
  ```bash
  git add dazpy/_client.py tests/test_dazpy.py
  git commit -m "feat(dazpy): DazClient re-checks plugin version and exposes the result"
  ```

### Task 3: `AsyncDazClient` uses the tracker

**Files:**
- Modify: `dazpy/_client_aio.py` (`__init__` ~49-62, `_check_server_version` ~81-91, `get_server_version` ~93-100, `_post`/`_get`/`_delete` ~102-140)
- Test: `tests/test_dazpy_aio.py` — rewrite `class TestAsyncServerVersionCheck` (~line 483)

**Interfaces:**
- Consumes: Task 1 names; mirror Task 2's design.
- Produces: `AsyncDazClient.__init__(..., check_version: bool = True, on_version_check: Callable[[VersionCheck], object] | None = None)` (callback is a plain sync callable; documented as "sync only, runs on the event loop thread"); `version_check` property; same `_versions` class default; same transport/header hooks in `_post`/`_get`/`_delete` (`httpx.ConnectError`, `TimeoutException`, `HTTPError` branches call `mark_stale()`). Concurrency comes from `claim_check()`: a coroutine that can't claim proceeds without waiting.

- [ ] **Step 1: Rewrite the tests** (respx, base `http://127.0.0.1:18811`, same patches as Task 2):
  - `test_older_than_minimum_warns_once`: status 2.11.0; two executes → one warning, `status.call_count == 1`, `client.version_check.compatible is False`.
  - `test_plugin_one_minor_behind_does_not_warn`: plugin 2.12.0, client 2.13.0 → no warning.
  - `test_unreachable_first_check_retries`: `/status` side effect `[httpx.ConnectError("down"), Response(200, version 2.12.0)]` → after two executes `status.call_count == 2`.
  - `test_instance_change_triggers_recheck`: execute responses carry `X-Server-Instance-Id` `i1` then `i2` → `/status` called again before the third execute.
  - `test_concurrent_first_requests_single_status`: `/status` route uses an async side effect that `await asyncio.sleep(0.05)` before returning 2.12.0; `asyncio.gather` 5 executes → `status.call_count == 1`.
  - `test_callback_exception_does_not_break_request`.
  - Keep `test_delete_as_first_request_checks_version` (status 2.11.0) and `test_check_version_false_skips_status`.

- [ ] **Step 2: Run to verify failure**
  Run: `python -m pytest tests/test_dazpy_aio.py -k TestAsyncServerVersionCheck -q`
  Expected: failures.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run to verify pass**
  Run: `python -m pytest tests/test_dazpy_aio.py tests/test_version_tracker.py -q`
  Expected: all pass.

- [ ] **Step 5: Commit**
  ```bash
  git add dazpy/_client_aio.py tests/test_dazpy_aio.py
  git commit -m "feat(dazpy): AsyncDazClient re-checks plugin version and exposes the result"
  ```

### Task 4: Public API, cleanup and docs

**Files:**
- Modify: `dazpy/_version.py` (delete `warn_if_server_older`), `dazpy/__init__.py` (import + `__all__`), `dazpy/exceptions.py:160-170` (`ServerVersionWarning` docstring), `docs/api/client.rst`, `README.md:367-372` and `README.md:1204-1212`
- Test: `tests/test_version_tracker.py` (add export test)

**Interfaces:**
- Produces: `dazpy.VersionCheck`, `dazpy.MIN_SERVER_VERSION` exported (both in `__all__`).

- [ ] **Step 1: Failing test** `test_public_exports`: `from dazpy import VersionCheck, MIN_SERVER_VERSION`; `MIN_SERVER_VERSION == "2.12"`; both names in `dazpy.__all__`; `not hasattr(dazpy._version, "warn_if_server_older")`.
- [ ] **Step 2: Run** `python -m pytest tests/test_version_tracker.py -k public_exports -q` → FAIL.
- [ ] **Step 3: Implement**: exports; delete `warn_if_server_older` and any remaining import of it (`grep -rn warn_if_server_older dazpy tests` must be empty). `ServerVersionWarning` docstring: warned when the plugin is older than `dazpy.MIN_SERVER_VERSION`; upgrade the plugin; silence with `check_version=False` or `warnings` filters; drop the `pip install dazpy==2.9.3` sentence from the docstring and replace with "or use a dazpy release that matches the plugin". `docs/api/client.rst`: add `.. autoclass:: dazpy.VersionCheck` and a `.. autodata:: dazpy.MIN_SERVER_VERSION` entry next to `DazClient`. README: both version-check passages describe the minimum-version rule, re-checks (reconnect, Studio restart), `client.version_check`, `on_version_check`; keep `check_version=False`.
- [ ] **Step 4: Run** `python -m pytest tests/test_version_tracker.py tests/test_dazpy.py tests/test_dazpy_aio.py -q` → all pass. Docs build if Sphinx is installed: `python -m sphinx -b html -W -q docs docs/_build/html` → no warnings (skip and say so if Sphinx isn't available).
- [ ] **Step 5: Commit**
  ```bash
  git add dazpy/__init__.py dazpy/_version.py dazpy/exceptions.py docs/api/client.rst README.md tests/test_version_tracker.py
  git commit -m "docs(dazpy): document VersionCheck and the minimum plugin version"
  ```

### Task 5: Release 2.13.0

**Files:**
- Modify: `pyproject.toml`, `dazpy/__init__.py`, `docs/conf.py`, `include/common_version.h` (MAJOR/MINOR/REV and `DZSRV_VERSION_STR`), `openapi.yaml`, `README.md` (version badge, "What's New in v2.13.0" section + TOC link before v2.12.0, line ~190 MCP mention), `CHANGELOG.md` (`## [2.13.0] - <release date>` above 2.12.0), `docs/LIVE_SMOKE.md:20`

- [ ] **Step 1: Bump** every location to `2.13.0`.
- [ ] **Step 2: CHANGELOG / README.** `[2.13.0]`: Changed — version check now compares against `MIN_SERVER_VERSION` (2.12), re-checks after reconnect and Studio restart; Added — `VersionCheck`, `client.version_check`, `on_version_check`, `dazpy.MIN_SERVER_VERSION`; Note — "The plugin binaries are rebuilt with the new version number; no plugin code changed. Plugin 2.12.x users need not upgrade." README "What's New in v2.13.0" says the same in two or three lines. README ~190 and `docs/LIVE_SMOKE.md:20`: refer to the MCP server as `daz-mcp-server` (the package is being renamed from `vangard-daz-mcp`), worded so it's true before and after the MCP 0.8.0 release (e.g. "daz-mcp-server (formerly vangard-daz-mcp)").
- [ ] **Step 3: Verify**
  Run: `python scripts/check_version_consistency.py` → exit 0.
  Run: `python -m pytest tests/test_version_tracker.py tests/test_dazpy.py tests/test_dazpy_aio.py tests/test_recipe_facade.py tests/test_openapi_parity.py -q` → all pass.
- [ ] **Step 4: Commit**
  ```bash
  git add -A pyproject.toml dazpy/__init__.py docs/conf.py include/common_version.h openapi.yaml README.md CHANGELOG.md docs/LIVE_SMOKE.md
  git commit -m "chore: release 2.13.0"
  ```
- [ ] **Step 5: Scoped live check (ask the user to start Studio first; DS4 or DS6, the installed 2.12.0 plugin is fine).** From the worktree:
  ```python
  python -c "import dazpy; seen=[]; c=dazpy.DazClient(on_version_check=seen.append); c.execute('1;'); print(c.version_check)"
  ```
  Expected: `compatible=True`, `server_version='2.12.0'`, a non-empty `server_instance_id`, no warning. Then ask the user to restart Studio, run one more `execute` on a client kept alive in a REPL across the restart, and confirm a second `VersionCheck` with a different `server_instance_id`. Nothing else runs against Studio.
- [ ] **Step 6: Outward steps — each only after the user's go-ahead:** push `feat/dazpy-plugin-min-version` and open a PR to `master`; user merges; push tag `v2.13.0` on the merge commit. Then verify: `gh run list --workflow release-tagged.yml -L 1` succeeds, the GitHub release has 6 assets, and `pip index versions dazpy` lists 2.13.0. Record a bd note and close the tracking issue.
