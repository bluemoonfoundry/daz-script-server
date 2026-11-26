#!/usr/bin/env python3
"""Check that openapi.yaml describes exactly the routes the server serves.

Fails (exit 1) when:
  * a route registered in ``setupRoutes()`` (src/PaneRoutes.cpp) has
    no matching path + method in openapi.yaml, or vice versa;
  * a registration in ``setupRoutes()`` doesn't pass its path as a string
    literal (so it can't be checked), or registers the same route twice;
  * a companion-plugin route (declared in ``companion_plugins.json``) is missing
    from openapi.yaml, or is documented without the ``CompanionPlugins`` tag;
  * openapi.yaml documents a ``CompanionPlugins`` operation that no known
    plugin registers;
  * an SDK (dazpy, and daz-ts when its sources are present) calls an endpoint
    that openapi.yaml does not document.

Companion plugins live in other repos and register routes at runtime through
``registerCompanionPlugin()`` / ``registerPluginRoute()``, so their routes are
declared in ``companion_plugins.json`` at the repo root. Pass
``--plugin-src NAME=DIR`` (e.g. ``my-exporter=../my-exporter``) to also
check a plugin's entry against its own source, and ``--live URL`` to check the
``companion_plugins`` a running server reports in ``GET /capabilities``
(token from ``DSS_API_TOKEN`` or ``~/.daz3d/dazscriptserver_token.txt``).

Exit 2 when ``--live`` can't reach the server; static errors and the SDK
report are still printed/written first.

``--sdk-report FILE`` writes a Markdown table of which documented operations
each SDK calls (``-`` for stdout). Gaps in SDK coverage are reported, not
failures.

Usage:
  python scripts/check_openapi_parity.py
  python scripts/check_openapi_parity.py --sdk-report -
  python scripts/check_openapi_parity.py --plugin-src my-exporter=../my-exporter
  python scripts/check_openapi_parity.py --live http://127.0.0.1:18811
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTES_CPP = ROOT / "src" / "PaneRoutes.cpp"
OPENAPI = ROOT / "openapi.yaml"
DAZPY_DIR = ROOT / "dazpy"
DAZ_TS_DIR = ROOT / "daz-ts" / "src"

PLUGIN_TAG = "CompanionPlugins"

COMPANION_REGISTRY = ROOT / "companion_plugins.json"


def load_companion_registry(path: Path = COMPANION_REGISTRY) -> dict[str, set[tuple[str, str]]]:
    """{plugin name: {(METHOD, path)}} from companion_plugins.json."""
    data = json.loads(path.read_text(encoding="utf-8"))
    registry: dict[str, set[tuple[str, str]]] = {}
    for plugin in data.get("plugins", []):
        name = plugin["name"]
        if name in registry:
            raise ValueError(f"{path.name}: plugin {name!r} declared twice")
        registry[name] = {(r["method"].upper(), r["path"]) for r in plugin.get("routes", [])}
    return registry


# Routes companion plugins register at runtime, from companion_plugins.json.
# --plugin-src checks an entry against the plugin's source; --live against a
# running server.
COMPANION_PLUGIN_ROUTES: dict[str, set[tuple[str, str]]] = load_companion_registry()

Route = tuple[str, str]  # (METHOD, normalized path)


def normalize(path: str) -> str:
    """Collapse every path-parameter spelling to ``{}``.

    httplib regex captures ``([^/]+)``, OpenAPI ``{id}``, plugin ``:id``,
    Python f-string ``{request_id}`` and JS template ``${requestId}``.
    """
    path = path.split("?", 1)[0]
    path = re.sub(r"\$\{[^}]*\}", "{}", path)  # before (...): may hold calls
    path = re.sub(r"\([^)]*\)", "{}", path)
    path = re.sub(r"\{[^}]*\}", "{}", path)
    path = re.sub(r":\w+", "{}", path)
    if len(path) > 1:
        path = path.rstrip("/")
    return path


# ─── Server side ─────────────────────────────────────────────────────────────

# Every httplib registration call in setupRoutes(), through any pointer or
# object (`m_pServer->Get(`, `srv->Post(`, `server.Delete(`). The path must
# follow as a string literal; anything else (a variable, a helper's argument,
# a loop) can't be read statically and fails the check instead of slipping by.
SERVER_CALL_RE = re.compile(r'(?:->|\.)\s*(Get|Post|Put|Delete|Patch|Options)\s*\(')
_PATH_LITERAL_RE = re.compile(r'\s*R?"([^"]+)"')


def server_routes(src: str) -> tuple[set[Route], list[str]]:
    """Return (routes, errors) for the registrations in setupRoutes()."""
    start = src.index("void DzScriptServerPane::setupRoutes()")
    end = src.index("\n}\n", start)  # the definition's closing brace at column 0
    body = src[start:end]
    first_line = src.count("\n", 0, start) + 1
    routes: set[Route] = set()
    unreadable: list[str] = []
    dupes: set[Route] = set()
    for m in SERVER_CALL_RE.finditer(body):
        line = first_line + body.count("\n", 0, m.start())
        lit = _PATH_LITERAL_RE.match(body, m.end())
        if not lit:
            arg = body[m.end():body.find("\n", m.end())].strip()
            unreadable.append(f"    line {line}: {m.group(1)}({arg}")
            continue
        path = lit.group(1)
        if path.startswith("(") and path.endswith(")"):
            path = path[1:-1]  # raw string R"(...)"
        key = (m.group(1).upper(), normalize(path))
        if key in routes:
            dupes.add(key)
        routes.add(key)
    errors = []
    if unreadable:
        errors.append("route registrations the parity check can't read in setupRoutes() "
                      "(pass the path as a string literal):\n" + "\n".join(unreadable))
    if dupes:
        errors.append("routes registered more than once in setupRoutes():\n" + fmt(dupes))
    return routes, errors


# Matches the method literal followed closely by the path literal, the shape
# every registerPluginRoute() call site uses (plugins typically assign them to
# QStrings on one line: `QString mPost = "POST", pPost = "/my/route", ...`).
PLUGIN_SRC_RE = re.compile(
    r'"(GET|POST|PUT|DELETE|PATCH)"[^"\n]{0,80}?"(/[^"\s]*)"')


def plugin_routes_from_source(src_dir: Path) -> set[Route]:
    routes = set()
    for f in sorted(src_dir.rglob("*.cpp")):
        text = f.read_text(encoding="utf-8", errors="replace")
        if "registerPluginRoute" not in text:
            continue
        for m in PLUGIN_SRC_RE.finditer(text):
            routes.add((m.group(1), normalize(m.group(2))))
    return routes


# ─── OpenAPI ─────────────────────────────────────────────────────────────────

def openapi_operations(text: str) -> dict[Route, dict]:
    """Return {(METHOD, path): {"path": raw, "tags": [...]}} from the paths block.

    A small line parser keyed on openapi.yaml's 2-space layout, so the check
    has no PyYAML dependency.
    """
    ops: dict[Route, dict] = {}
    in_paths = False
    path = None
    current = None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            in_paths = line.rstrip() == "paths:"
            path = current = None
            continue
        if not in_paths:
            continue
        m = re.match(r"^  (/\S*):\s*$", line)
        if m:
            path, current = m.group(1), None
            continue
        m = re.match(r"^    (get|post|put|delete|patch):\s*$", line)
        if m and path:
            key = (m.group(1).upper(), normalize(path))
            if key in ops:
                raise ValueError(f"duplicate OpenAPI operation {key[0]} {path}")
            current = ops[key] = {"path": path, "tags": []}
            continue
        if re.match(r"^    \S", line):
            current = None  # path-level key such as `parameters:`
            continue
        m = re.match(r"^      tags:\s*\[([^\]]*)\]", line)
        if m and current is not None:
            current["tags"] = [t.strip() for t in m.group(1).split(",") if t.strip()]
    return ops


# ─── SDKs ────────────────────────────────────────────────────────────────────

# Any absolute path literal. No hand-kept list of top-level segments: an SDK
# call to a brand-new prefix must still be compared against the spec. (The
# call shapes below are specific enough that this adds no false positives.)
_ROUTE_PATH = r'/[^"`\s{$]'

# dazpy: self._get("/x"), self._client._post(f"/x/{id}"), plus SSE streams
# opened as f"{self._base}/x" (GET; dazpy has no other raw-URL calls).
DAZPY_CALL_RE = re.compile(
    r'\._(get|post|put|delete|patch)\(\s*f?"(' + _ROUTE_PATH + r'[^"]*)"')
DAZPY_SSE_RE = re.compile(r'f"\{self\._base\}(' + _ROUTE_PATH + r'[^"]*)"')

# daz-ts: this.get("/x"), this.delete_(`/x/${id}`), and raw fetches of
# `${this.baseUrl}/x` whose method is the next `method: "X"` (default GET).
TS_CALL_RE = re.compile(
    r'\.(get|post|put|delete|patch)_?\(\s*["`](' + _ROUTE_PATH + r'[^"`]*)["`]')
TS_SSE_RE = re.compile(r'`\$\{this\.baseUrl\}(' + _ROUTE_PATH + r'[^`]*)`')
_FETCH_METHOD_RE = re.compile(r"""method:\s*["'](\w+)["']""")


def sdk_calls(src_dir: Path, pattern: str, call_re, sse_re) -> dict[Route, list[str]]:
    calls: dict[Route, list[str]] = {}
    for f in sorted(src_dir.rglob(pattern)):
        text = f.read_text(encoding="utf-8", errors="replace")
        rel = f.relative_to(ROOT).as_posix()
        for m in call_re.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            key = (m.group(1).upper(), normalize(m.group(2)))
            calls.setdefault(key, []).append(f"{rel}:{line}")
        for m in sse_re.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            method = "GET"
            if pattern == "*.ts":
                found = _FETCH_METHOD_RE.search(text, m.end(), m.end() + 300)
                if found:
                    method = found.group(1).upper()
            key = (method, normalize(m.group(1)))
            calls.setdefault(key, []).append(f"{rel}:{line}")
    return calls


def collect_sdks() -> dict[str, dict[Route, list[str]]]:
    sdks = {"dazpy": sdk_calls(DAZPY_DIR, "*.py", DAZPY_CALL_RE, DAZPY_SSE_RE)}
    if DAZ_TS_DIR.is_dir():
        sdks["daz-ts"] = sdk_calls(DAZ_TS_DIR, "*.ts", TS_CALL_RE, TS_SSE_RE)
    return sdks


def sdk_report(ops: dict[Route, dict], sdks: dict[str, dict[Route, list[str]]]) -> str:
    names = list(sdks)
    lines = ["# SDK endpoint coverage", "",
             "Operations in openapi.yaml and whether each SDK calls them.", ""]
    if "daz-ts" not in sdks:
        lines += ["_daz-ts sources not present in this checkout; not reported._", ""]
    lines.append("| Operation | " + " | ".join(names) + " |")
    lines.append("|---|" + "---|" * len(names))
    covered = {n: 0 for n in names}
    for key in sorted(ops, key=lambda k: (ops[k]["path"], k[0])):
        cells = []
        for n in names:
            if key in sdks[n]:
                covered[n] += 1
                cells.append("yes")
            else:
                cells.append("**no**")
        lines.append(f"| `{key[0]} {ops[key]['path']}` | " + " | ".join(cells) + " |")
    lines.append("")
    for n in names:
        lines.append(f"- {n}: {covered[n]}/{len(ops)} operations")
    return "\n".join(lines) + "\n"


# ─── Main ────────────────────────────────────────────────────────────────────

def fmt(routes) -> str:
    return "\n".join(f"    {m} {p}" for m, p in sorted(routes, key=lambda r: (r[1], r[0])))


def check(plugin_src: dict[str, Path]) -> tuple[list[str], dict[Route, dict], dict]:
    ops = openapi_operations(OPENAPI.read_text(encoding="utf-8"))
    documented = set(ops)
    server, errors = server_routes(ROUTES_CPP.read_text(encoding="utf-8"))

    plugin_routes: set[Route] = set()
    for name, routes in COMPANION_PLUGIN_ROUTES.items():
        declared = {(m, normalize(p)) for m, p in routes}
        plugin_routes |= declared
        if name in plugin_src:
            actual = plugin_routes_from_source(plugin_src[name])
            if actual != declared:
                errors.append(
                    f"companion_plugins.json entry {name!r} is out of date with "
                    f"{plugin_src[name]}:\n  source registers:\n{fmt(actual)}\n"
                    f"  list declares:\n{fmt(declared)}")

    clash = server & plugin_routes
    if clash:
        errors.append("routes both built in and claimed by a companion plugin:\n" + fmt(clash))

    builtin_docs = {k for k in documented if PLUGIN_TAG not in ops[k]["tags"]}
    plugin_docs = documented - builtin_docs

    if server - documented:
        errors.append("routes in setupRoutes() missing from openapi.yaml:\n"
                      + fmt(server - documented))
    if builtin_docs - server:
        errors.append("openapi.yaml operations not registered in setupRoutes() "
                      f"(tag companion-plugin routes [{PLUGIN_TAG}]):\n"
                      + fmt(builtin_docs - server))
    if plugin_routes - documented:
        errors.append("companion-plugin routes missing from openapi.yaml:\n"
                      + fmt(plugin_routes - documented))
    mistagged = (plugin_routes & documented) - plugin_docs
    if mistagged:
        errors.append(f"companion-plugin routes documented without tag [{PLUGIN_TAG}]:\n"
                      + fmt(mistagged))
    if plugin_docs - plugin_routes:
        errors.append(f"openapi.yaml [{PLUGIN_TAG}] operations no known plugin registers "
                      "(add them to companion_plugins.json):\n"
                      + fmt(plugin_docs - plugin_routes))

    sdks = collect_sdks()
    for name, calls in sdks.items():
        unknown = set(calls) - documented
        if unknown:
            where = "\n".join(f"    {m} {p}  ({', '.join(calls[(m, p)])})"
                              for m, p in sorted(unknown, key=lambda r: (r[1], r[0])))
            errors.append(f"{name} calls endpoints missing from openapi.yaml:\n{where}")
    return errors, ops, sdks


# ─── Live check against GET /capabilities ───────────────────────────────────

def _read_token() -> str | None:
    token = os.environ.get("DSS_API_TOKEN")
    if token:
        return token.strip()
    path = Path.home() / ".daz3d" / "dazscriptserver_token.txt"
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def fetch_capabilities(base_url: str, token: str | None) -> dict:
    req = urllib.request.Request(base_url.rstrip("/") + "/capabilities")
    if token:
        req.add_header("X-API-Token", token)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check_live(caps: dict, ops: dict[Route, dict]) -> tuple[list[str], list[str]]:
    """Compare a server's companion_plugins with companion_plugins.json and openapi.yaml.

    Returns (errors, notes). A route served by a registered plugin must be
    declared under that plugin's name and documented with the CompanionPlugins
    tag. Routes registered without a plugin name, and declared plugins that
    aren't loaded, are notes only: older plugins and partial installs are
    normal.
    """
    errors: list[str] = []
    notes: list[str] = []
    if "companion_plugins" not in caps:
        return (["server's /capabilities has no companion_plugins "
                 "(server older than the discovery registry?)"], notes)

    registry = {name: {(m, normalize(p)) for m, p in routes}
                for name, routes in COMPANION_PLUGIN_ROUTES.items()}
    seen: set[str] = set()
    for plugin in caps["companion_plugins"]:
        name = plugin.get("name")
        routes = {(r["method"].upper(), normalize(r["path"])) for r in plugin.get("routes", [])}
        if not plugin.get("registered"):
            notes.append(f"routes registered without a plugin name (owner {name}):\n" + fmt(routes))
            declared_anywhere = set().union(*registry.values()) if registry else set()
            if routes - declared_anywhere:
                errors.append(f"unattributed live routes (owner {name}) not in companion_plugins.json:\n"
                              + fmt(routes - declared_anywhere))
        else:
            seen.add(name)
            if name not in registry:
                errors.append(f"live companion plugin {name!r} (version {plugin.get('version')}) "
                              "is not declared in companion_plugins.json")
            elif routes != registry[name]:
                errors.append(f"live routes of {name!r} differ from companion_plugins.json:\n"
                              f"  server serves:\n{fmt(routes)}\n  file declares:\n{fmt(registry[name])}")
            if plugin.get("version") is None:
                notes.append(f"companion plugin {name!r} registered routes but no version")
        undocumented = {r for r in routes if r not in ops or PLUGIN_TAG not in ops[r]["tags"]}
        if undocumented:
            errors.append(f"live routes of {name!r} missing from openapi.yaml [{PLUGIN_TAG}]:\n"
                          + fmt(undocumented))
    for name in sorted(set(registry) - seen):
        notes.append(f"declared companion plugin {name!r} is not loaded on this server")
    return errors, notes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sdk-report", metavar="FILE",
                    help="write the SDK coverage table as Markdown ('-' for stdout)")
    ap.add_argument("--plugin-src", action="append", default=[], metavar="NAME=DIR",
                    help="check a companion plugin's declared routes against its source")
    ap.add_argument("--live", metavar="URL",
                    help="also check a running server's GET /capabilities companion_plugins")
    args = ap.parse_args(argv)

    plugin_src: dict[str, Path] = {}
    for item in args.plugin_src:
        name, _, d = item.partition("=")
        if name not in COMPANION_PLUGIN_ROUTES or not d:
            ap.error(f"--plugin-src {item!r}: expected one of "
                     f"{sorted(COMPANION_PLUGIN_ROUTES)}=DIR")
        if not Path(d).is_dir():
            ap.error(f"--plugin-src {item!r}: {d} is not a directory")
        plugin_src[name] = Path(d)

    errors, ops, sdks = check(plugin_src)

    # A failed --live fetch is reported with exit 2, but only after the static
    # errors and the SDK report, so it never hides drift found offline.
    live_failed = False
    if args.live:
        try:
            caps = fetch_capabilities(args.live, _read_token())
        except (urllib.error.URLError, OSError, ValueError) as exc:
            errors.append(f"--live {args.live}: could not read /capabilities: {exc}")
            live_failed = True
        else:
            live_errors, notes = check_live(caps, ops)
            errors += live_errors
            for n in notes:
                print(f"note: {n}", file=sys.stderr)

    if args.sdk_report:
        report = sdk_report(ops, sdks)
        if args.sdk_report == "-":
            sys.stdout.write(report)
        else:
            Path(args.sdk_report).write_text(report, encoding="utf-8")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 2 if live_failed else 1
    print(f"OpenAPI parity OK: {len(ops)} operations "
          f"({len(COMPANION_PLUGIN_ROUTES)} companion plugin(s)); "
          f"SDKs checked: {', '.join(sdks)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
