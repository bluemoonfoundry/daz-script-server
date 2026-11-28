"""Compatibility check from CMS metadata, before anything is loaded (read-only).

``compat_script`` reads asset-database metadata only and returns this JSON
shape, the only thing the Python side depends on::

    {path: {"bases": [str], "known": bool, "provides": str | null, "type": str | null}}

``bases`` are the figure bases the file is made for; ``provides`` is the base a
figure file itself defines (its ``compatibilityBase``). ``known`` is false when
the asset database has no record for the file.  ``type`` is the file's CMS
``contentType`` (spec 15.2), used to refuse presets that are not presets.
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
    # the figure base the file itself defines (a figure's compatibilityBase), if any
    provides: str | None = None
    # the file's CMS contentType (e.g. "Actor/Character", "Preset/Character")
    type: str | None = None


def compat_script(paths: list[str]) -> str:
    """Read-only script reporting each file's compatibilities from the asset database."""
    esc = ScriptBuilder.escape_string
    paths_js = "[" + ", ".join(esc(p) for p in paths) + "]"
    # Confirmed on DS4 by the Task 1 live probe (spec 15); DS6 pending.
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
    var bases = [], provides = null, ctype = null;
    for (var _j = 0; found && _j < found.length; _j++) {{
        var a = found[_j];
        _add(a.compatibilities, bases);
        _add(a.vendorCompatibilities, bases);
        _add(a.userCompatibilities, bases);
        if (!provides && a.compatibilityBase) provides = String(a.compatibilityBase);
        if (!ctype && a.contentType) ctype = String(a.contentType);
    }}
    _out[p] = {{bases: bases, known: !!(found && found.length), provides: provides, type: ctype}};
}}
return _out;""")


def _read_raw(client: DazClient, paths: list[str]) -> dict[str, dict]:
    if not paths:
        return {}
    return client.execute(compat_script(paths)).value or {}


def read_compat(client: DazClient, paths: list[str]) -> dict[str, CompatInfo]:
    """Compatibilities per file; files the database does not know come back ``known=False``.

    ``provides`` is filled too, so one call also answers :func:`base_of_asset`
    for figure files."""
    raw = _read_raw(client, paths)
    out: dict[str, CompatInfo] = {}
    for p in paths:
        e = raw.get(p) or {}
        bases = tuple(str(b) for b in e.get("bases") or ())
        out[p] = CompatInfo(p, bases, bool(e.get("known")) and bool(bases),
                            str(e["provides"]) if e.get("provides") else None,
                            str(e["type"]) if e.get("type") else None)
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


# Content types a preset file must not have: figures (``Actor`` / the figure
# file's ``Actor/Character``, spec 15.2), fitted items, wearables presets and
# props are loaded as content, and opening one with the figure selected can pop
# Studio's modal "replace the selected figure" dialog.  Other ``Actor/...``
# types (e.g. a shape) stay allowed.
_NOT_PRESET_TYPES = ("Actor/Character", "Follower", "Prop", "Preset/Wearables")


def _type_is(ctype: str, prefix: str) -> bool:
    c, p = ctype.strip().casefold(), prefix.casefold()
    return c == p or c.startswith(p + "/")


def _not_a_preset(ctype: str) -> bool:
    return ctype.strip().casefold() == "actor" or any(_type_is(ctype, t) for t in _NOT_PRESET_TYPES)


def check_preset_types(presets: Mapping[str, ResolvedAsset], info: Mapping[str, CompatInfo]
                       ) -> tuple[list[RecipeIssue], list[RecipeIssue]]:
    """(errors ``invalid_asset_ref``, warnings ``compatibility_unknown``) for presets
    by their content type (final review I7), before anything is opened.

    The CMS ``contentType`` decides, else the type the finder reported.  A file
    the database knows but gives no type warns; an unknown file already warns
    from :func:`check_compat`."""
    errors: list[RecipeIssue] = []
    warnings: list[RecipeIssue] = []
    for rpath, asset in presets.items():
        ci = info.get(asset.path)
        ctype = (ci.type if ci is not None else None) or asset.type
        name = asset.product or asset.path
        if not ctype:
            if ci is not None and ci.known:
                warnings.append(RecipeIssue(rpath, "compatibility_unknown",
                                            f"cannot verify {name} is a preset: the asset "
                                            "database gives it no content type"))
            continue
        if _not_a_preset(ctype):
            errors.append(RecipeIssue(
                rpath, "invalid_asset_ref",
                f"{name} is {ctype} content, not a preset; figures belong in 'asset', "
                "hair, clothing and outfits in 'wearing', props in 'props'"))
    return errors, warnings
