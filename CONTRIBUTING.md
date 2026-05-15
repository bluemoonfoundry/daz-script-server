# Contributing to DazScript Server

Thank you for your interest in contributing!

## Before You Start

- Check the [open issues](https://github.com/bluemoonfoundry/daz-script-server/issues)
  to avoid duplicating work in progress.
- For significant changes, open an issue first so the design can be discussed
  before code is written.
- Review [`CLAUDE.md`](CLAUDE.md) for the threading model and architecture —
  violating the Qt main-thread rule is the most common source of crashes.

## Development Setup

### Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| DAZ Studio SDK | 4.5+ | [Download](https://www.daz3d.com/daz-studio-4-5-sdk) |
| CMake | 3.5+ | |
| MSVC | 2019 or 2022 | Windows only |
| Xcode / clang | Current | macOS only |
| Python | 3.8+ | For running tests |

### Build

```bash
# Configure
cmake -B build -S . -DDAZ_SDK_DIR="C:/path/to/DAZStudio4.5+ SDK"

# Build (Release)
cmake --build build --config Release

# Or use the convenience script
./build.sh
./build.sh build --clean --debug   # debug build
./build.sh install --clean         # build + copy to DAZ Studio (must be closed)
```

### Running Tests

```bash
# Start DAZ Studio and enable the plugin first, then:

# Full integration suite (72 tests)
python tests.py

# Quick smoke test
python test-simple.py

# Performance benchmarks
python test-performance.py
python test-performance.py --quick   # fewer iterations, suitable for CI
```

## Code Style

### C++

- Match the surrounding code's style — if a file uses 4-space indentation,
  use 4-space indentation.
- No auto-generated code comments ("This function does X"). Well-named
  identifiers are the documentation.
- Add a comment only for non-obvious WHY: hidden constraints, workarounds for
  specific bugs, surprising invariants.
- RAII for all resource ownership — no raw `new`/`delete` outside constructors.
- Qt objects: create on the main thread, destroy on the main thread.

### Threading Rules (Critical)

All `QScriptEngine`, `DzScript`, and DAZ API calls **must** happen on the
main Qt thread. HTTP handler callbacks run on raw `std::thread`s. Cross-thread
calls must use `Qt::BlockingQueuedConnection`.

See `CLAUDE.md` → "Threading Model" for the full explanation.

### Commit Messages

- Imperative mood: "Fix race condition in concurrent request counter" not
  "Fixed" or "Fixes"
- First line ≤ 72 characters
- Reference the issue number when applicable: `Fix #12: version bump to v2.0`

## Pull Request Checklist

- [ ] All existing tests pass (`python tests.py`)
- [ ] New behaviour has test coverage
- [ ] Threading model respected (no Qt calls from HTTP threads)
- [ ] No new magic numbers — add constants to `ServerConfig`
- [ ] `CHANGELOG.md` updated under `[Unreleased]`
- [ ] README updated if API surface changed
- [ ] `openapi.yaml` updated if API surface changed

## Architecture Overview

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for component diagrams and data-flow
descriptions.

Key classes:

| Class | File | Responsibility |
|-------|------|---------------|
| `DzScriptServerPane` | `src/DzScriptServerPane.cpp` | GUI + server lifecycle + request dispatch |
| `AuthenticationService` | `src/AuthenticationService.cpp` | Token generation, storage, validation |
| `RateLimiterService` | `src/RateLimiterService.cpp` | Per-IP sliding-window rate limiting |
| `IPWhitelistService` | `src/IPWhitelistService.cpp` | IP access control |
| `MetricsCollector` | `src/MetricsCollector.cpp` | Request counters and uptime |
| `AsyncRequestManager` | `src/AsyncRequestManager.cpp` | Async queue, status, TTL cleanup |
| `ServerListenThread` | `src/DzScriptServerPane.cpp` | QThread wrapper for httplib |
| `SecureRandom` | `src/SecureRandom.cpp` | OS crypto RNG |
| `JsonBuilder` | `src/JsonBuilder.cpp` | Type-safe JSON with auto-escaping |

## Reporting Bugs

Open a GitHub issue with:

1. DAZ Studio version and OS
2. Plugin version (`GET /status` → `version` field)
3. Steps to reproduce
4. Expected vs. actual behaviour
5. Relevant log output (UI request log or DAZ Studio log)

## Feature Requests

Open a GitHub issue describing:

1. The use case you are trying to address
2. The proposed API or configuration change
3. Any backward-compatibility implications

## License

By contributing you agree that your contributions will be licensed under the
[AGPL v3](LICENSE).
