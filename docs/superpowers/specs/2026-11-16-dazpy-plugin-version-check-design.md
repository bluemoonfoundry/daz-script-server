# dazpy plugin version check: minimum version, re-checks, readable result

Repo: daz-script-server (dazpy). Ships as **daz-script-server / dazpy 2.13.0**.
Status: design, awaiting approval.

## Why

dazpy talks to the DazScriptServer plugin running inside Daz Studio, at a host
and port the caller chooses (`DazClient(host, port)` / `AsyncDazClient(host,
port)`, default `127.0.0.1:18811`). The plugin is installed by hand into
Studio, so it can lag behind dazpy. When it does, newer features fail with
404s or odd errors and the user has no idea why.

dazpy already checks for this, but the check doesn't serve apps built on
dazpy, the daz-mcp-server in particular:

1. **It compares against dazpy's own version.** dazpy and the plugin share a
   version number, so a dazpy-only release (like this one) would tell everyone
   to upgrade a plugin that hasn't changed. That teaches people to ignore it.
2. **It runs once per client and never again.** If Studio was down at the
   first request, the check fails silently and is never retried. A long-lived
   client (the MCP server keeps one for its whole life) never notices the user
   restarting Studio with a new plugin, or with an old one.
3. **The only output is a Python warning.** Inside an MCP server that goes to
   stderr, where neither the user nor the AI sees it.
4. **The advice assumes a script author.** It offers "pip install an older
   dazpy" as an equal option, which is impossible when an app pins dazpy.

The decision (user's): fix it in dazpy so every client benefits, not in the
MCP server alone.

## Goals

- dazpy declares the **oldest plugin version it needs** and warns only when
  the connected plugin is older than that.
- The check **re-runs when the target may have changed**: after a connection
  failure recovers, and when the plugin's instance ID changes (Studio
  restarted).
- The latest result is **readable by code**, and callers can **register a
  callback**, so apps can show it where their users look.
- Plain scripts behave as today: a `ServerVersionWarning` when the plugin is
  too old.

## Non-goals

- No change to the plugin (C++) or the HTTP API. Everything needed already
  exists: `/status` returns `version` and `server_instance_id`, and every
  response carries an `X-Server-Instance-Id` header (post-routing hook,
  `src/DzScriptServerPane.cpp:694-700`).
- No refusal to run. A too-old plugin is reported, never blocked.
- No check that the plugin is *newer* than dazpy. The plugin API only gains
  things; an older dazpy against a newer plugin is fine.
- No patch-level comparison. Comparison stays major.minor.

## Anti-goals

- A warning that fires when nothing is wrong (plugin 2.12 + dazpy 2.13).
- Extra round trips on every request. The check costs one `GET /status` per
  (re)connection or instance change, not per call.
- A version check that can make a working request fail. Every failure inside
  the check is swallowed, as today.

## Design

### 1. Minimum plugin version

- New module constant in `dazpy/_version.py`: `MIN_SERVER_VERSION = "2.12"`
  (major.minor string). Exported from `dazpy` as `dazpy.MIN_SERVER_VERSION`.
- Starting value is **2.12** (user's decision): dazpy 2.13's newest dependency
  on plugin features is the 2.12 scene-recipe work. Plugin 2.12.0 is released
  (GitHub release + PyPI, tag `v2.12.0` on master `64a43d3`), so the "upgrade"
  advice points at something that exists.
- `warn_if_server_older` lives in the private `_version` module; it may be
  replaced or re-signatured freely, and existing tests that assert against
  `client_version()` are rewritten to the new rule (my call).
- Rule for later releases, written in the constant's docstring and in
  `CONTRIBUTING`/release notes: raise it only when dazpy starts calling a plugin
  route or field that older plugins lack. A dazpy-only release leaves it alone.
- `warn_if_server_older` (or its replacement) compares the plugin's
  `(major, minor)` against `parse_version(MIN_SERVER_VERSION)`, not against
  `client_version()`.

### 2. When the check runs

Both `DazClient` and `AsyncDazClient` keep the same rules:

- **First request:** as today, a best-effort `GET /status` before the
  first request.
- **Check that couldn't reach the server doesn't count.** If the `/status`
  call fails (connection error, timeout, unparseable body), the client stays
  "unchecked" and tries again before the next request.
- **After a connection failure:** when a request raises dazpy's
  `ConnectionError`/`TimeoutError` for transport reasons, the client marks
  itself unchecked; the next request re-checks.
- **Instance change:** the client remembers the `X-Server-Instance-Id` it last
  checked against. When a response arrives with a different value, the client
  marks itself unchecked; the check runs before the following request (not
  retroactively on the response just received).
- `check_version=False` still disables all of it.
- **No instance ID** (an old plugin, or a response without the header): the
  instance-change trigger is simply inactive; the client never re-checks on a
  `None` ID and never treats `None` → `None` as a change. Re-checks then come
  only from connection failures. (my call)

Async client: the re-check must not run concurrently with itself; if two
coroutines both see "unchecked", one does the check and the other waits for it
or skips (builder's choice, as long as only one `/status` goes out).

### 3. The readable result

A frozen dataclass in `dazpy/_version.py`, exported from `dazpy`:

```
VersionCheck
    server_url: str            # e.g. "http://192.168.1.20:18811"
    server_version: str | None # plugin version from /status, None if unknown
    min_server_version: str    # MIN_SERVER_VERSION at check time
    client_version: str        # dazpy.__version__
    server_instance_id: str | None
    compatible: bool | None    # None when the version is unknown/unparseable
    message: str | None        # human advice when compatible is False
```

- `client.version_check -> VersionCheck | None`: the latest result (`None`
  until a check has completed).
- `DazClient(..., on_version_check=callable)` / same for `AsyncDazClient`: an
  optional callback invoked with the `VersionCheck` after **every completed**
  check (compatible or not), so an app can both raise and clear a warning. For
  the async client the callback may be sync or async (builder's choice how to
  support it; documenting "sync only" is acceptable).
- Exceptions from the callback are swallowed (logged at debug via `logging`),
  per the anti-goal above.
- `ServerVersionWarning` is still emitted when `compatible is False`, once per
  distinct `(server_url, server_instance_id)`, so a re-check against the same
  running plugin doesn't repeat it. With no instance ID the key is
  `(server_url, server_version)`. (my call)
- `DazClient` may be used from several threads (the MCP server calls it via
  worker threads): the "checked" state and `version_check` updates are guarded
  by a lock, and the callback runs on whichever thread performed the check.
  This is documented on the callback parameter.
- The existing `server_version` property keeps working.

### 4. Message wording

When the plugin is too old:

> Daz Studio plugin at {server_url} is version {server_version}; dazpy
> {client_version} needs {min_server_version} or newer. Upgrade the
> DazScriptServer plugin in the Daz Studio instance at that address
> (https://github.com/bluemoonfoundry/daz-script-server/releases). If you
> can't, a dazpy release matching the plugin also works.

The plugin upgrade comes first; the older-dazpy route is a fallback sentence
without a pip command (apps that pin dazpy can't use it). `check_version=False`
is mentioned in the warning class docstring, not in the message.

## Release

- Version **2.13.0** across every version location
  (`scripts/check_version_consistency.py` lists them: `pyproject.toml`,
  `dazpy/__init__.py`, `docs/conf.py`, `include/common_version.h`,
  `openapi.yaml`). The plugin is rebuilt with the new number but has no code
  change; release notes say so.
- CHANGELOG `[2.13.0]` and README "What's New" entries, as for 2.11/2.12.
- Current docs that name the MCP server's old command (`README.md`,
  `docs/LIVE_SMOKE.md`) switch to `daz-mcp-server` in this release, worded so
  they hold once the MCP 0.8.0 rename ships. Past CHANGELOG entries and dated
  specs/plans stay as written.
- Release steps stop for the user at each outward action: push branch / open
  PR, merge (user), push tag `v2.13.0`. The builder verifies the workflow run,
  the GitHub release assets and the PyPI listing after the tag.
- Released the established way: merge to master by PR, then push the
  `v2.13.0` tag, which runs `release-tagged.yml` (build, version check, PyPI
  publish, GitHub release). Each push/tag needs the user's go-ahead.
- Live smoke for DS4 and DS6 per `docs/LIVE_SMOKE.md` is not required by this
  change (no plugin code change), but one scoped live check is: a client
  against the running plugin produces `compatible=True`, and restarting Studio
  triggers a re-check (instance ID changes).

## Tests (unit, no Studio)

- Plugin 2.12 + dazpy 2.13 → compatible, no warning.
- Plugin 2.11 → `compatible=False`, warning once, message names the URL and
  both versions.
- Unknown/unparseable version → `compatible=None`, no warning.
- `/status` unreachable on first request → no result, re-check before the next
  request.
- Transport failure then success → re-check happens.
- Changed `X-Server-Instance-Id` → re-check before the next request; same ID →
  none.
- Callback receives every completed check; a raising callback doesn't break the
  request.
- `check_version=False` → no `/status` calls at all.
- All of the above for `AsyncDazClient`, including only one `/status` under
  concurrent first requests.

## Left to the builder

- Internal structure (shared helper for both clients vs per-client code).
- How the async client serialises the re-check.
- Whether the async callback may be a coroutine.
- Exact docs placement (dazpy API docs page for the version check).
