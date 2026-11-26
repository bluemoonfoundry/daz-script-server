"""Compatibility check from CMS metadata, before anything is loaded (read-only).

``compat_script`` reads asset-database metadata only and returns this JSON
shape, the only thing the Python side depends on::

    {path: {"bases": [str], "known": bool, "provides": str | null}}

``bases`` are the figure bases the file is made for; ``provides`` is the base a
figure file itself defines (its ``compatibilityBase``). ``known`` is false when
the asset database has no record for the file.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ._asset_resolve import ResolvedAsset
from ._recipe_issue import RecipeIssue
from ._script_builder import ScriptBuilder

if TYPE_CHECKING:
    from .client import DazClient


@dataclass(frozen=True)
class CompatInfo:
    path: str
    bases: tuple[str, ...]
    known: bool


def compat_script(paths: list[str]) -> str:
    """Read-only script reporting each file's compatibilities from the asset database."""
    esc = ScriptBuilder.escape_string
    paths_js = "[" + ", ".join(esc(p) for p in paths) + "]"
    # Provisional until the Task 1 live probe confirms these calls.
    return ScriptBuilder.iife(f"""// recipe:compat
var _paths = {paths_js}, _out = {{}};
var _mgr = App.getAssetMgr(), _cms = App.getContentMgr();
function _add(list, into) {{
    if (!list) return;
    for (var i = 0; i < list.length; i++) {{
        var s = String(list[i]);
        if (s && into.indexOf(s) < 0) into.push(s);
    }}
}}
for (var _i = 0; _i < _paths.length; _i++) {{
    var p = _paths[_i], rel = p;
    if (_cms && typeof _cms.getRelativePath === "function") {{
        var r = _cms.getRelativePath(p, true);
        if (r) rel = String(r);
    }}
    var found = _mgr ? _mgr.findAssetsForFile(rel, true, true) : [];
    var bases = [], provides = null;
    for (var _j = 0; found && _j < found.length; _j++) {{
        var a = found[_j];
        _add(a.compatibilities, bases);
        _add(a.vendorCompatibilities, bases);
        _add(a.userCompatibilities, bases);
        if (!provides && a.compatibilityBase) provides = String(a.compatibilityBase);
    }}
    _out[p] = {{bases: bases, known: !!(found && found.length), provides: provides}};
}}
return _out;""")


def _read_raw(client: DazClient, paths: list[str]) -> dict[str, dict]:
    if not paths:
        return {}
    return client.execute(compat_script(paths)).value or {}


def read_compat(client: DazClient, paths: list[str]) -> dict[str, CompatInfo]:
    """Compatibilities per file; files the database does not know come back ``known=False``."""
    raw = _read_raw(client, paths)
    out: dict[str, CompatInfo] = {}
    for p in paths:
        e = raw.get(p) or {}
        bases = tuple(str(b) for b in e.get("bases") or ())
        out[p] = CompatInfo(p, bases, bool(e.get("known")) and bool(bases))
    return out


def base_of_asset(client: DazClient, path: str) -> str | None:
    """The figure base an asset provides (for an actor the recipe will create), or None."""
    return (_read_raw(client, [path]).get(path) or {}).get("provides") or None


def _norm(base: str) -> str:
    return base.strip().replace("\\", "/").rstrip("/").casefold()


def is_compatible(target_base: str, item_bases: tuple[str, ...]) -> bool:
    """True if *target_base* equals one of *item_bases* or lies beneath it (``/`` boundaries)."""
    target = _norm(target_base)
    for b in item_bases:
        nb = _norm(b)
        if target == nb or target.startswith(nb + "/"):
            return True
    return False


def _actor_key(path: str) -> str:
    m = re.match(r"actors\.([^.\[]+)", path)
    return m.group(1) if m else path


def check_compat(target_base: str | None, items: Mapping[str, ResolvedAsset],
                 info: Mapping[str, CompatInfo]
                 ) -> tuple[list[RecipeIssue], list[RecipeIssue]]:
    """(errors ``incompatible_asset``, warnings ``compatibility_unknown``) per recipe path."""
    errors: list[RecipeIssue] = []
    warnings: list[RecipeIssue] = []
    for rpath, asset in items.items():
        name = asset.product or asset.path
        ci = info.get(asset.path)
        if target_base is None or ci is None or not ci.known:
            why = "the actor's base is unknown" if target_base is None \
                else "the asset database has no compatibility record"
            warnings.append(RecipeIssue(rpath, "compatibility_unknown",
                                        f"cannot verify {name}: {why}"))
        elif not is_compatible(target_base, ci.bases):
            errors.append(RecipeIssue(
                rpath, "incompatible_asset",
                f"{name} is made for {', '.join(ci.bases)}; "
                f"actor '{_actor_key(rpath)}' is {target_base}"))
    return errors, warnings
