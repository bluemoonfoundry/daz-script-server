#!/usr/bin/env python3
"""Check that openapi.yaml describes exactly the routes the server serves.

Fails (exit 1) when:
  * a route registered in ``setupRoutes()`` (src/DzScriptServerPane.cpp) has
    no matching path + method in openapi.yaml, or vice versa;
  * a companion-plugin route (``COMPANION_PLUGIN_ROUTES`` below) is missing
    from openapi.yaml, or is documented without the ``CompanionPlugins`` tag;
  * openapi.yaml documents a ``CompanionPlugins`` operation that no known
    plugin registers;
  * an SDK (dazpy, and daz-ts when its sources are present) calls an endpoint
    that openapi.yaml does not document.

Companion plugins live in other repos and register routes at runtime through
``registerPluginRoute()``, so their routes are listed here by hand. Pass
``--plugin-src NAME=DIR`` (e.g. ``daz-bridge-usd=../daz-bridge-usd``) to also
check that list against the plugin's own source.

``--sdk-report FILE`` writes a Markdown table of which documented operations
each SDK calls (``-`` for stdout). Gaps in SDK coverage are reported, not
failures.

Usage:
  python scripts/check_openapi_parity.py
  python scripts/check_openapi_parity.py --sdk-report -
  python scripts/check_openapi_parity.py --plugin-src daz-bridge-usd=../daz-bridge-usd
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PANE_CPP = ROOT / "src" / "DzScriptServerPane.cpp"
OPENAPI = ROOT / "openapi.yaml"
DAZPY_DIR = ROOT / "dazpy"
DAZ_TS_DIR = ROOT / "daz-ts" / "src"

PLUGIN_TAG = "CompanionPlugins"

# Routes companion plugins register via registerPluginRoute(). Keep in sync
# with each plugin's source; --plugin-src checks this list against it.
COMPANION_PLUGIN_ROUTES: dict[str, set[tuple[str, str]]] = {
    "daz-bridge-usd": {("POST", "/export/usd"), ("GET", "/export/usd/:id")},
}

HTTP_METHODS = ("GET", "POST", "PUT", "DELETE", "PATCH")

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

SERVER_ROUTE_RE = re.compile(r'm_pServer->(Get|Post|Put|Delete|Patch)\s*\(\s*"([^"]+)"')


def server_routes(src: str) -> set[Route]:
    start = src.index("void DzScriptServerPane::setupRoutes()")
    end = src.index("void DzScriptServerPane::applyPluginRoutes()", start)
    routes = set()
    for m in SERVER_ROUTE_RE.finditer(src[start:end]):
        routes.add((m.group(1).upper(), normalize(m.group(2))))
    return routes


# Matches the method literal followed closely by the path literal, the shape
# every registerPluginRoute() call site uses (daz-bridge-usd assigns them to
# QStrings on one line: `QString mPost = "POST", pPost = "/export/usd", ...`).
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

_ROUTE_PREFIX = r"/(?:status|health|metrics|capabilities|execute|scripts|requests|artifacts|render|scene|geometry|export)\b"

# dazpy: self._get("/x"), self._client._post(f"/x/{id}"), plus SSE streams
# opened as f"{self._base}/x" (GET; dazpy has no other raw-URL calls).
DAZPY_CALL_RE = re.compile(
    r'\._(get|post|put|delete|patch)\(\s*f?"(' + _ROUTE_PREFIX + r'[^"]*)"')
DAZPY_SSE_RE = re.compile(r'f"\{self\._base\}(' + _ROUTE_PREFIX + r'[^"]*)"')

# daz-ts: this.get("/x"), this.delete_(`/x/${id}`), and raw fetches of
# `${this.baseUrl}/x` whose method is the next `method: "X"` (default GET).
TS_CALL_RE = re.compile(
    r'\.(get|post|put|delete|patch)_?\(\s*["`](' + _ROUTE_PREFIX + r'[^"`]*)["`]')
TS_SSE_RE = re.compile(r'`\$\{this\.baseUrl\}(' + _ROUTE_PREFIX + r'[^`]*)`')
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
    errors: list[str] = []
    ops = openapi_operations(OPENAPI.read_text(encoding="utf-8"))
    documented = set(ops)
    server = server_routes(PANE_CPP.read_text(encoding="utf-8"))

    plugin_routes: set[Route] = set()
    for name, routes in COMPANION_PLUGIN_ROUTES.items():
        declared = {(m, normalize(p)) for m, p in routes}
        plugin_routes |= declared
        if name in plugin_src:
            actual = plugin_routes_from_source(plugin_src[name])
            if actual != declared:
                errors.append(
                    f"COMPANION_PLUGIN_ROUTES[{name!r}] is out of date with "
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
                      "(add them to COMPANION_PLUGIN_ROUTES):\n"
                      + fmt(plugin_docs - plugin_routes))

    sdks = collect_sdks()
    for name, calls in sdks.items():
        unknown = set(calls) - documented
        if unknown:
            where = "\n".join(f"    {m} {p}  ({', '.join(calls[(m, p)])})"
                              for m, p in sorted(unknown, key=lambda r: (r[1], r[0])))
            errors.append(f"{name} calls endpoints missing from openapi.yaml:\n{where}")
    return errors, ops, sdks


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sdk-report", metavar="FILE",
                    help="write the SDK coverage table as Markdown ('-' for stdout)")
    ap.add_argument("--plugin-src", action="append", default=[], metavar="NAME=DIR",
                    help="check a companion plugin's declared routes against its source")
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

    if args.sdk_report:
        report = sdk_report(ops, sdks)
        if args.sdk_report == "-":
            sys.stdout.write(report)
        else:
            Path(args.sdk_report).write_text(report, encoding="utf-8")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(f"OpenAPI parity OK: {len(ops)} operations "
          f"({len(COMPANION_PLUGIN_ROUTES)} companion plugin(s)); "
          f"SDKs checked: {', '.join(sdks)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
