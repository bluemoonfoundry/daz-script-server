# Migration Guide: v1.x → v2.0

## Overview

v2.0 is a **backward-compatible** release. The HTTP API, response shapes,
authentication mechanism, and configuration settings are identical to v1.3.
You do not need to change any client code to upgrade.

The changes are entirely internal: a comprehensive refactor of the plugin's
C++ internals to fix thread-safety issues, eliminate the god-object
anti-pattern, and improve long-term maintainability.

---

## Upgrade Steps

1. **Stop the server** in DAZ Studio (click "Stop Server" in the pane).
2. **Close DAZ Studio.**
3. **Replace the plugin file** in the DAZ Studio plugins folder:
   - Windows: `C:\Program Files\DAZ 3D\DAZStudio4\plugins\DazScriptServer.dll`
   - macOS: `/Applications/DAZ 3D/DAZStudio4/plugins/DazScriptServer.dylib`
4. **Restart DAZ Studio.**
5. **Open the pane** (Window → Panes → Daz Script Server).
6. **Start the server.**

Your API token and all settings are preserved — they are stored in QSettings
and the token file, both of which are untouched by a plugin replacement.

---

## What Changed

### Fixed: Concurrent Request Race Condition

**Symptom in v1.x:** Under heavy load, more than the configured maximum number
of concurrent requests could slip through simultaneously, causing DAZ Studio to
slow down or crash.

**Fix in v2.0:** The active-request counter is now incremented and decremented
atomically under a `QMutex`. The limit is enforced before any work begins.

**Impact on you:** None. If your client was hitting the old limit reliably, it
will continue to receive HTTP 429 at the correct threshold.

### Fixed: Memory Safety on Script Errors

**Symptom in v1.x:** In rare error paths, `DzScript` objects could be deleted
from an HTTP thread instead of the main Qt thread, leading to intermittent
crashes or heap corruption.

**Fix in v2.0:** `DzScript` destruction is always routed to the main thread
via `Qt::BlockingQueuedConnection`.

**Impact on you:** Scripts that previously caused plugin crashes may now fail
cleanly with an error response instead.

### Fixed: Signal/Slot Leak

**Symptom in v1.x:** In early-return error paths (auth failure, rate limit,
etc.) a `print()` capture connection was sometimes left connected, causing
stray output from later requests to appear in unrelated responses.

**Fix in v2.0:** The connection is always explicitly disconnected before
returning.

**Impact on you:** The `output` array in responses will no longer contain
stale lines from a previous request in rare race conditions.

---

## Breaking Changes

There are **no breaking changes** to:

- HTTP endpoints or URL paths
- Request body schemas
- Response body schemas
- HTTP status codes
- Authentication mechanism (`X-API-Token` / `Authorization: Bearer`)
- Token file location (`~/.daz3d/dazscriptserver_token.txt`)
- Settings storage (QSettings keys unchanged)
- Script registry behavior

---

## New in v2.0

v2.0 does not add new HTTP endpoints — all new endpoints were introduced in
v1.2 and v1.3. The additions in this release are:

- `openapi.yaml` — machine-readable API specification
- `ARCHITECTURE.md` — component and threading diagrams
- `CONTRIBUTING.md` — developer guide
- `CHANGELOG.md` — full version history

---

## Rollback

To roll back to v1.3:

1. Stop the server and close DAZ Studio.
2. Replace the plugin file with the v1.3 binary from the
   [GitHub Releases](https://github.com/bluemoonfoundry/daz-script-server/releases)
   page.
3. Restart DAZ Studio.

Your token and settings are unaffected.

---

## Troubleshooting

### Server does not start after upgrade

Check the DAZ Studio log for CRT or symbol errors. If you see heap-mismatch
messages, ensure you downloaded the correct binary for your DAZ Studio version.
The `/MD` (multi-threaded DLL) CRT flag must match what DAZ Studio uses.

### Settings appear reset

Settings are stored in QSettings under the key
`DAZ 3D / DazScriptServer`. If a key is missing, the plugin writes the
default value and continues — it never deletes existing keys. If all settings
appear reset, check that the QSettings backend (Registry on Windows,
plist on macOS) was not cleared by a third-party tool.

### Token regenerated unexpectedly

The plugin only regenerates the token if the token file is missing or empty.
It does not regenerate on version upgrades. If your token changed, check that
`~/.daz3d/dazscriptserver_token.txt` was not deleted or replaced.
