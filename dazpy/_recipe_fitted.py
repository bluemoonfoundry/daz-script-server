"""Live readback of figures and the items fitted to them (read-only).

A *fitted item* is a node whose follow target is the figure (clothing, hair,
shoes); the item's non-fitted, non-bone descendants are part of it unless they
carry a record of their own (those are reported as ``foreign_children``).

The script returns this JSON shape, the only thing the Python side depends on::

    {"figures": [{"name": str, "label": str, "record": str | null,
                  "compat_base": str | null,
                  "items": [{"name": str, "label": str, "type": str | null,
                             "source_path": str | null, "record": str | null,
                             "foreign": [str]}]}]}

Figures are every ``DzFigure`` whose label equals one of the requested labels
(exact, case-sensitive) plus the nodes named in ``owned_names``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ._recipe_store import DATA_ITEM_NAME, _RECORD_KEY, EntityRecord
from ._script_builder import ScriptBuilder

if TYPE_CHECKING:
    from ._client import DazClient


@dataclass(frozen=True)
class FittedItem:
    name: str
    label: str
    type: str | None
    source_path: str | None  # getAssetUriForNode file part
    record: EntityRecord | None
    foreign_children: tuple[str, ...]


@dataclass(frozen=True)
class FigureInfo:
    name: str
    label: str
    record: EntityRecord | None
    compat_base: str | None
    items: tuple[FittedItem, ...]


def figures_script(labels: list[str], owned_names: list[str]) -> str:
    """Read-only script reporting figures (by label / owned name) and their fitted items."""
    esc = ScriptBuilder.escape_string
    labels_js = "[" + ", ".join(esc(x) for x in labels) + "]"
    names_js = "[" + ", ".join(esc(x) for x in owned_names) + "]"
    # Confirmed on DS4 by the Task 1 live probe (spec 15); DS6 pending.
    return ScriptBuilder.iife(f"""// recipe:figures
var _labels = {labels_js}, _owned = {names_js};
function _rec(n) {{
    var it = n.findDataItem({esc(DATA_ITEM_NAME)});
    return it ? it.getSettings().getStringValue({esc(_RECORD_KEY)}) : null;
}}
function _follow(n) {{
    return (typeof n.getFollowTarget === "function") ? n.getFollowTarget() : null;
}}
function _foreign(n, out) {{
    var kids = n.getNodeChildren(false);
    for (var k = 0; k < kids.length; k++) {{
        var c = kids[k];
        if (_follow(c)) continue;
        if (!c.inherits("DzBone") && _rec(c)) out.push(c.getName());
        _foreign(c, out);
    }}
    return out;
}}
function _type(n) {{
    var p = (typeof n.getPresentation === "function") ? n.getPresentation() : null;
    return p ? p.type : null;
}}
function _source(n) {{
    var mgr = App.getAssetMgr();
    var uri = mgr ? String(mgr.getAssetUriForNode(n)) : "";
    var i = uri.indexOf("#");
    if (i >= 0) uri = uri.substring(0, i);
    return uri ? uri : null;
}}
var _all = Scene.getNodeList(), _figs = [], _seen = {{}};
function _add(n) {{
    if (_seen[n.getName()]) return;
    _seen[n.getName()] = true;
    _figs.push(n);
}}
for (var _i = 0; _i < _all.length; _i++) {{
    var node = _all[_i];
    if (!node.inherits("DzFigure") || _follow(node)) continue;  // followers are items
    for (var _j = 0; _j < _labels.length; _j++) {{
        var label = _labels[_j];
        if (node.getLabel() === label) _add(node);
    }}
}}
for (var _o = 0; _o < _owned.length; _o++) {{
    var owned = Scene.findNode(_owned[_o]);
    if (owned) _add(owned);
}}
var _out = {{figures: []}};
for (var _f = 0; _f < _figs.length; _f++) {{
    var fig = _figs[_f], mgr = App.getAssetMgr();
    var base = null;
    if (mgr && typeof mgr.getCompatibilityBasePathForNode === "function") {{
        var bp = mgr.getCompatibilityBasePathForNode(fig);
        base = bp ? String(bp) : null;
    }}
    var items = [];
    for (var _k = 0; _k < _all.length; _k++) {{
        var it = _all[_k];
        // ==, not ===: two wrappers of one node are never === (DS4, spec 15.2)
        if (it == fig || _follow(it) != fig) continue;
        items.push({{name: it.getName(), label: it.getLabel(), type: _type(it),
                    source_path: _source(it), record: _rec(it), foreign: _foreign(it, [])}});
    }}
    _out.figures.push({{name: fig.getName(), label: fig.getLabel(), record: _rec(fig),
                       compat_base: base, items: items}});
}}
return _out;""")


def _record(s: str | None) -> EntityRecord | None:
    if not s:
        return None
    try:
        return EntityRecord.from_json(s)
    except (ValueError, KeyError, TypeError):
        return None


def read_figures(client: DazClient, labels: list[str],
                 owned_names: list[str]) -> dict[str, list[FigureInfo]]:
    """Figures by exact label (``len > 1`` means ambiguous), plus owned figures by name.

    Keys are the requested labels (always present, possibly empty) and the
    ``owned_names``; a figure matching both appears under both.
    """
    payload = client.execute(figures_script(labels, owned_names)).value or {}
    infos = [FigureInfo(
        name=f["name"], label=f.get("label") or f["name"], record=_record(f.get("record")),
        compat_base=f.get("compat_base"),
        items=tuple(FittedItem(
            name=i["name"], label=i.get("label") or i["name"], type=i.get("type"),
            source_path=i.get("source_path") or None, record=_record(i.get("record")),
            foreign_children=tuple(i.get("foreign") or ())) for i in f.get("items") or []))
        for f in payload.get("figures") or []]
    out: dict[str, list[FigureInfo]] = {label: [] for label in labels}
    for info in infos:
        if info.label in out:
            out[info.label].append(info)
    for name in owned_names:
        out.setdefault(name, [])
        out[name] += [i for i in infos if i.name == name and i not in out[name]]
    return out


def figure_labels_script() -> str:
    """Read-only script listing the label of every non-follower figure in the scene."""
    # Confirmed on DS4 by the Task 1 live probe (spec 15); DS6 pending.
    return ScriptBuilder.iife("""// recipe:figure-labels
var _all = Scene.getNodeList(), _out = [];
for (var _i = 0; _i < _all.length; _i++) {
    var n = _all[_i];
    var f = (typeof n.getFollowTarget === "function") ? n.getFollowTarget() : null;
    if (n.inherits("DzFigure") && !f) _out.push(n.getLabel());
}
return _out;""")


def read_figure_labels(client: DazClient) -> list[str]:
    """Labels of all non-follower figures (for near-match hints only)."""
    value = client.execute(figure_labels_script()).value or []
    return [str(x) for x in value]
