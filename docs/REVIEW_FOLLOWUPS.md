# Repo Review Follow-ups

Findings from the 2026-11-19 whole-repo review (code quality, docs, cleanup).
Work these on a machine with the DAZ Studio SDKs so every C++ change can be
built against SDK 4 and SDK 6 and exercised live, not guessed at.

**Already done on branch `chore/repo-review-cleanup`** (pushed, not yet built):

- `86e9de0` **C1**: `RenderProgressBroker` pushes to subscriber queues while
  holding `m_mutex`, which fixes a use-after-free when an SSE client
  disconnects while a render event is being pushed. Needs a build plus a
  live check (see "Verify C1" below).
- `ec6d7f5` **C2**: root `LICENSE` (AGPL v3 + section 7 DAZ SDK linking
  permission); MIT `dazpy/LICENSE`; `dazpy/README.md` as the PyPI
  description; `pyproject.toml` `readme`/`license-files`; README and
  CONTRIBUTING license sections. Open item: the other C++ contributors
  (S.Carton, Aaron, Black-Byte, RJ Purse, Viliam Fiedler) should agree to the
  section 7 permission. Mention it in the PR.

Each item below has a location, the problem, the fix, and how to verify it.
Line numbers are as of `ec6d7f5`.

## Verification baseline

Run these before and after each group of changes:

```bash
./build.sh build --sdk-version 4 --clean
./build.sh build --sdk-version 6 --clean
python tests.py unit                       # 1108 tests at ec6d7f5
python scripts/check_version_consistency.py
python scripts/check_openapi_parity.py
python tests/smoke_live.py                 # live DS4/DS6 matrix, see docs/LIVE_SMOKE.md
```

### Verify C1

1. Build and install. Start an animation render through `POST /render/animation`.
2. Open `GET /render/{id}/events` with `curl -N`. Kill curl mid-render, then
   reconnect and kill it again, several times. Also disconnect right as the
   render finishes.
3. Expected: Studio stays up and later renders still stream events.

---

## Warnings

### W1. About 25 test files never run in CI
- **Where:** `tests.py:53-70`, `.github/workflows/ci.yml:59-60`
- **Problem:** `tests.py unit` loads a hand-maintained list of modules.
  `test_shots`, `test_shot_library`, `test_version_tracker`, `test_render_api`,
  `test_recipe_*` (partly), `test_dsp_runner`, `test_workflow_builder`,
  `test_sprite_matrix_*`, `test_comfyui_client` and others never run.
- **Fix:** discover `tests/test_*.py`, with an explicit exclude list for suites
  that need a live server (`test_api`, `test_dazpy_integration`,
  `test_recipe_live`, `test_comfyui_enhance_integration`, `test_performance`).
- **Verify:** `python tests.py unit` count rises; fix or xfail whatever fails
  (see W2).

### W2. Three failing tests hidden by W1
- **Where:** `tests/test_sprite_matrix_schema.py:200-210`
- **Problem:** the three `test_face_detailer_*` tests expect
  `SpecValidationError` for `face_detailer` fields. Nothing in
  `tests/fixtures/rendering/sprite_matrix/schema.py` implements that.
- **Fix:** implement the validation, or delete/xfail the tests.

### W3. Test dependencies missing from `pyproject.toml`
- **Where:** `pyproject.toml` optional-dependencies
- **Problem:** `tests/test_dazpy_aio.py` needs `respx` and
  `tests/test_file_watcher.py` needs `watchdog`. Neither is declared, so both
  fail to import in CI.
- **Fix:** add a `test` extra (`respx`, `watchdog`, `jsonschema`, `httpx`) and
  have CI run `pip install -e ".[aio,test]"`.

### W4. No Python lint or type check in CI
- **Where:** `.github/workflows/ci.yml`
- **Problem:** pyflakes reports about 78 findings. The package ships `py.typed`
  but has undefined annotation names (`dazpy/_scene.py:120,133,146`,
  `_property.py:22`, `_bone.py:15`, `_script_builder.py:24`).
- **Fix:** add a `lint` job running `ruff check dazpy scripts tests` (F rules
  first), plus a non-blocking `mypy dazpy`.

### W5. Live settings toggles race with HTTP threads
- **Where:** `m_bEnabled` in `include/AuthenticationService.h:35`,
  `include/IPWhitelistService.h:23`, `include/RateLimiterService.h:31`. Written
  by UI handlers at `src/DzScriptServerPane.cpp:3659,3676,3686` while the
  server runs.
- **Problem:** the flags are plain `bool`s read by worker threads, which is a
  data race. CLAUDE.md says settings are snapshotted before start. The
  whitelist vector itself is only written in `onStartClicked`
  (`:571-572`) and `applySettings` (`:3595-3596`), both before the server runs.
- **Fix:** make the flags `std::atomic<bool>`, or stop applying the toggles
  live and snapshot them on start (update the UI and CLAUDE.md to match).
- **Verify:** toggle auth, whitelist and rate limit while a load loop hits
  `/execute`, on DS4 and DS6.

### W6. Token compare is not constant-time
- **Where:** `src/AuthenticationService.cpp:142` (`trimmed == m_sTokenStr`)
- **Fix:** check the length, then XOR-accumulate over every byte. Low practical
  risk (localhost binding, 128-bit token), but the fix is cheap.

### W7. Token file is briefly readable by other users
- **Where:** `src/AuthenticationService.cpp:106-118`
- **Problem:** the file is created with the default umask, written, and only
  then `chmod 600`.
- **Fix:** on POSIX, create it with `open(path, O_CREAT|O_WRONLY|O_TRUNC, 0600)`,
  or `fchmod` before writing.
- **Verify:** delete the token file, start Studio, check `ls -l` on
  `~/.daz3d/dazscriptserver_token.txt`.

### W8. Render SSE route hand-builds error bodies
- **Where:** `src/DzScriptServerPane.cpp:1716,1723,1731`
- **Problem:** returns `{"error":"..."}` with no `error_code`, `retryable` or
  `success:false`. CLAUDE.md requires `ErrorResponse` for every failure.
- **Fix:** use `ErrorResponse::build(ErrorCode::REQUEST_NOT_FOUND, ...)`.
- **Verify:** `curl /render/bogus/events` and `/render/rnd-nope/events`. Check
  both dazpy and daz-ts still handle the 404.

### W9. SSE events escape only `\` and `"`
- **Where:** `src/RenderProgressBroker.cpp:78-79,106-107`
- **Problem:** a newline in an error message or path breaks the JSON and the
  SSE framing.
- **Fix:** use `JsonStd::escape()` (`include/JsonStd.h:45`).

### W10. Staging directory leaks when commit fails
- **Where:** `src/DzPackageImporter.cpp:292-295`
- **Problem:** returns without removing `stage.stagingDir`, which breaks the
  contract in `include/ZipInstaller.h:59-60`.
- **Fix:** call `PortableFs::removeRecursively(stage.stagingDir)` before
  returning.

### W11. Zip entry-count check can be bypassed by sign wrap
- **Where:** `src/ZipInstaller.cpp:191`
- **Problem:** `static_cast<int>(numFiles) > m_limits.maxEntryCount` goes
  negative above INT_MAX. Only zip64 archives can reach it.
- **Fix:** compare as `mz_uint` or `qint64`.

### W12. `./build.sh --debug` still builds Release
- **Where:** `CMakeLists.txt:4`
  (`set(CMAKE_BUILD_TYPE "Release" CACHE STRING "" FORCE)`)
- **Fix:** drop `FORCE`, and default only when `CMAKE_BUILD_TYPE` is empty.
- **Verify:** `./build.sh build --clean --debug` produces a debug binary on both
  Windows (MSVC, multi-config) and macOS.

### W13. SDK auth errors drop the ErrorResponse fields
- **Where:** `dazpy/_client.py:86-87`, `daz-ts/src/client.ts:46-48`,
  `daz-ts/src/exceptions.ts:14`
- **Problem:** on 401/403 both SDKs throw `AuthenticationError` without parsing
  the body, so `error_code`, `retryable` and `detail` are lost.
- **Fix:** handle 401/403 like other errors and give `AuthenticationError`
  those fields in both SDKs.

### W14. Docs reference files that don't exist
- **Where:**
  - `test-simple.py`, `test-performance.py`: `README.md:3145-3147,3232-3236`,
    `CONTRIBUTING.md:50-54`, `CLAUDE.md:50`
  - `tests_dazpy.py`, `tests_dazpy_integration.py`:
    `README.md:1069,1682,1685,3111-3112,3223,3226`
  - `FUTURE_ENHANCEMENTS.md`: `CLAUDE.md:194`
- **Fix:** point at `python tests.py unit|api|integration` and
  `python tests/test_performance.py [--quick]`. Remove the
  `FUTURE_ENHANCEMENTS.md` reference (it was deleted in `f2337cb`).

### W15. CLAUDE.md endpoint list is incomplete
- **Where:** `CLAUDE.md:108-110`
- **Problem:** omits `/capabilities`, `/scene/*`, `/geometry/frames`,
  `/render/*`, and GET/DELETE on `/scripts` and `/requests`.
- **Fix:** replace the list with a pointer to `openapi.yaml`, which CI keeps in
  parity with the routes.

### W16. Stale planning and assessment docs at the repo root
- **Where:** `REFACTORING_PLAN.md`, `REFACTORING_SUMMARY.md` (`:290` says
  "awaiting Phase 1 approval" though the services exist), `ASSESSMENT.md`
  (self-described as stale), `INTERACTION_POSE_ROADMAP.md` (`:3` "This branch
  is building…"), `MIGRATION.md` (v1 to v2 only)
- **Fix:** move them to `docs/archive/` with a status line, or delete them;
  beads tracks the work. Keep the README link to MIGRATION.

### W17. The same content lives in several docs
- **Where:**
  - beads workflow: `AGENTS.md` and `CLAUDE.md`
  - threading rules: `CLAUDE.md`, `CONTRIBUTING.md:70`, `ARCHITECTURE.md`
  - release notes: README "What's New" (from `README.md:182`) and
    `CHANGELOG.md`
  - workflow docs: four files in `.github/workflows/`, one named
    `ARCHITECTURE.md` like the root file
- **Fix:** keep each topic in one canonical place and link to it. Delete
  `.github/workflows/IMPLEMENTATION_SUMMARY.md`. Note that
  `scripts/check_version_consistency.py:73` reads the newest README
  "What's New" heading, so update that script if you shrink the section.

---

## Easy fixes

I made each of these in a first pass and then discarded it, because the C++
couldn't be compiled. The notes record what I learned.

- **E1. Delete unreferenced root files:** `g8f_test.json`, `g9_test.json`,
  `package-lock.json` (empty; no root `package.json`). A grep found no
  references.
- **E2. `test_securerandom.cpp`:** not built by CMake, `build.sh` or CI, and its
  compile line doesn't work with this build. Delete it, or move it to
  `tests/cpp/` and wire it into CTest. It is the only C++ test (beads issue
  `72d8` notes this). Also update `REFACTORING_SUMMARY.md:62` if that file is
  kept.
- **E3. Dead `dpc` target:** `CMakeLists.txt:141-147`, plus
  `DAZ_SDK_DPC_RELATIVE_PATH` at `:76-81`. Nothing uses the `dpc` target, and
  its `FATAL_ERROR` can fail configure. Removing it is safe only if both SDK
  layouts still configure. Verify with clean builds on SDK 4 and SDK 6.
- **E4. Dead C++ code:**
  - `ZipInstaller::install()` and `struct Result` (`include/ZipInstaller.h:50-55,85-91`,
    `src/ZipInstaller.cpp:124-152`). No callers. The class comment at
    `ZipInstaller.h:32-36` mentions `install()`, so reword it too.
  - `AuthenticationService::setToken()` (`include/AuthenticationService.h:28`,
    `src/AuthenticationService.cpp:151-157`). No callers.
  - `errno.h` / `sys/syscall.h` in `src/SecureRandom.cpp:14-16`. Unused, but
    keep `unistd.h` (`usleep`).
- **E5. Token-load messages are dropped:** `src/DzScriptServerPane.cpp:271-276`
  calls `loadOrGenerateToken()` and `appendLog()`s the result before
  `m_pLogView` exists (created at `:475`). `appendLog()` returns early when
  `m_pLogView` is null (`:902`), so every token message is lost, including the
  "crypto API unavailable" error. The `if` body is empty and its comment is
  wrong.
  - **Fix:** keep the messages and `appendLog()` them after `updateUI()`
    (around `:519`).
  - **Verify:** delete the token file and start Studio. The "Generated new API
    token" line should appear in the pane log.
- **E6. Duplicate JSON escaper:** `ErrorResponse::jsonEscape()`
  (`src/ErrorResponse.cpp:177`, declared `include/ErrorResponse.h:97`) has the
  same output as `JsonStd::escape()` (`include/JsonStd.h:45`). The catch:
  `ErrorResponse.h` only includes `<string>`, while `JsonStd.h` pulls in
  QtCore and QtScript (DS4) / QJsonDocument (DS6). Including it from
  `ErrorResponse.cpp` is probably fine, but confirm both SDK builds. If it adds
  friction, move `escape()` into a small Qt-free header that both use.
- **E7. Magic numbers to `ServerConfig`** (`include/DzScriptServerPane.h:58`):
  - port `18811` (`DzScriptServerPane.cpp:239`) and timeout `30` (`:243`). These
    duplicate `include/ServerSettings.h:8-9`. Consider having one reference the
    other.
  - `wait(1000)` at `:755,821`
  - SSE `3000` / `500` at `:1665-1670,1748-1751,1767`. One constant drives both
    the pop timeout and the keepalive interval; keep it under httplib's 5 s
    write timeout.
  - MB-to-bytes at `:646` and `src/RequestHandlers.cpp:84`.
  - **Gotcha:** `tests/test_route_security.py:217-220`
    (`test_httplib_payload_limit_set_from_config`) regex-matches the literal
    `maxBodyBytes = static_cast<size_t>(m_nMaxBodySizeMB) * 1024 * 1024`.
    Update it if that expression changes.
- **E8. `.gitignore` additions:** `smoke-report.json` (`live-smoke.yml:44`),
  `sdk-coverage.md` (`ci.yml:30`), `dist-pack/` (`build-daz-ts.yml:38`),
  `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`.
- **E9. Shadowed test class and unused imports:**
  - `tests/test_dazpy.py` defines `TestResetTransforms` twice (`:6229` and
    `:8023`). The second hides the first, so its two tests never run. When
    revived, both fail: they assert the old three-setter / three-call
    behavior, while `dazpy/poses.py:34-47` `reset_transforms()` now makes one
    `set_transform()` call. Merge them into one class asserting
    `set_transform(position=(0,0,0), rotation=(0,0,0), scale=(1,1,1))` plus the
    existing one-call test. The suite then shows 1109 tests.
  - Unused imports:
    - `tests/test_dazpy.py:25-58` (`AnchorTarget`, `BoneChain`, `ContactTarget`,
      `InteractionAnchor`, `align_single_limb_target`,
      `apply_interaction_recipe_to_scene`)
    - `tests/test_dazpy_integration.py:19` (`DazPose`, `DazViewport`; both are
      re-imported locally later)
    - `tests/test_comfyui_client.py:11` (`call`)
    - `tests/test_shots.py:4` (`math`)
    - `tests/test_comfyui_enhance_integration.py:14,28` (`Path`, `ComfyUIError`)
- **E10. Stale test counts:** `README.md:3146` and `CONTRIBUTING.md:46` say
  "72 tests". That was the live API suite count in mid-2026; the unit suite is
  now about 1100. Drop the number.
- **E11. daz-ts relative link:** `daz-ts/README.md:17` links
  `../../../releases`, which only resolves on GitHub. Use
  `https://github.com/bluemoonfoundry/daz-script-server/releases`.
- **E12. Duplicate examples stub:** `docs/examples/MOVED.md` duplicates
  `docs/examples/README.md`; delete it.
  - Not a duplicate:
    `docs/superpowers/plans/archive/2026-08-21-script-call-batching-plan.md` is the
    step-by-step plan for the design spec in `…-batching.md`, and `-plan.md:11`
    links to it. Keep both.
- **E13. CI caching:**
  - `ci.yml:53-57`: add `cache: pip`, `cache-dependency-path: pyproject.toml`,
    and drop `[docs]` from the unit-test install (`docs.yml` still installs it).
  - `build-daz-ts.yml:19-21`: add `cache: npm`,
    `cache-dependency-path: daz-ts/package-lock.json`.

---

## Suggestions

- **S1. Split `src/DzScriptServerPane.cpp` (4355 lines).** Pieces that are
  already separate:
  - artifact routes (`:1122-1320`, already free `static` functions)
  - plugin route registry (`:1885-2080`)
  - script registry (`:2081-2143`)
  - health/metrics/capabilities builders (`:3729-~4114`)
  - settings load/save (`:3569-3660`)

  Do one extraction per PR, building both SDKs each time.
- **S2. Artifact trust boundary.** `src/ArtifactFile.cpp:27-62` checks path
  strings only. It doesn't stop symlinks or confine files to the job output
  directory, so a script can expose any readable file. That's no more access
  than scripts already have, but document it, or enforce it with a canonical
  path prefix check.
- **S3. Sleep-based waits in tests:** `tests/test_file_watcher.py:61,80,82,105`,
  `tests/test_api.py:315,581,709`, `tests/test_performance.py:121`. Replace
  with poll-until-deadline helpers.
- **S4. Pin release actions to SHAs**, especially
  `pypa/gh-action-pypi-publish@release/v1` at `release-tagged.yml:98` (a
  moving branch).
- **S5. Docs gaps:**
  - add `SECURITY.md` (vulnerability reporting)
  - add a docs index that links `docs/LIVE_SMOKE.md` and
    `docs/MCP_SERVER_DESIGN.md`
  - move plans for shipped features in `docs/superpowers/plans/` into an
    archive folder
- **S6. daz-ts server version check:** dazpy has `MIN_SERVER_VERSION`
  (`dazpy/_version.py:22`); daz-ts has nothing similar. Add one or document
  that it's absent.
- **S7. Path parameter style:** prose uses `:id` while `openapi.yaml` uses
  `{id}`. Standardize on `{id}`.

## Verified fine

These need no action:

- Zip extraction rejects path traversal and symlinks.
- Opening an artifact `fstat`s the already-open handle, so there's no race
  between check and open.
- Startup with an empty token rejects requests rather than allowing them.
- Versions agree on 2.15.0, and the `ServerConfig` defaults match the docs.
- OpenAPI parity holds (25 operations).
