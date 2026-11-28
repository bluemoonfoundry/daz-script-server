"""Live readback of figures and the items fitted to them (read-only).

A *fitted item* is a node whose follow target is the figure (clothing, hair,
shoes).  Its ``foreign_children`` are every descendant not fitted by Studio
(followers are the item's own sub-parts), other than bones and the
``DzPushModifierWeightNode`` helper an outfit garment loads with: props the user
parented to it, recorded or not (spec 6.4, final review C2).

The script returns this JSON shape, the only thing the Python side depends on::

    {"figures": [{"name": str, "label": str, "element_id": str, "record": str | null,
                  "compat_base": str | null,
                  "items": [{"name": str, "label": str, "element_id": str,
                             "type": str | null, "source_path": str | null,
                             "record": str | null, "foreign": [str]}]}]}

Figures are every ``DzFigure`` whose label equals one of the requested labels
(exact, case-sensitive) plus the nodes named in ``owned_names`` (names or
``elementID:`` refs), each reported once (by element ID: names repeat when a
file is loaded twice, spec 15.4).  ``element_id`` is the node key (the element
ID on DS4/DS6); :attr:`FigureInfo.ref` / :attr:`FittedItem.ref` turn it into the
node ref recipe scripts address hand content by (final review C1).
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import unquote

from ._recipe_store import (DATA_ITEM_NAME, FIND_REF_JS, _RECORD_KEY, EntityRecord, eid_ref)
from ._script_builder import ScriptBuilder

if TYPE_CHECKING:
    from ._client import DazClient


def is_data_file(path: str | None) -> bool:
    """True for a Daz *data* file (``.dsf``, or under ``/data/``), the kind
    ``getAssetUriForNode`` reports (spec 15.2).  Never a loadable asset: loading
    one is untested and may prompt."""
    if not path:
        return False
    p = unquote(path.split("#", 1)[0]).replace("\\", "/").strip().casefold()
    return posixpath.splitext(p)[1] == ".dsf" or p.startswith("/data/")


@dataclass(frozen=True)
class FittedItem:
    name: str
    label: str
    type: str | None
    # getAssetUriForNode file part: the node's .dsf data file, never a restore source
    source_path: str | None
    record: EntityRecord | None
    foreign_children: tuple[str, ...]
    element_id: str | None = None

    @property
    def ref(self) -> str:
        """How scripts address this node: its ``elementID:`` ref, else its name."""
        return eid_ref(self.element_id) or self.name


@dataclass(frozen=True)
class FigureInfo:
    name: str
    label: str
    record: EntityRecord | None
    compat_base: str | None
    items: tuple[FittedItem, ...]
    element_id: str | None = None

    @property
    def ref(self) -> str:
        """How scripts address this node: its ``elementID:`` ref, else its name."""
        return eid_ref(self.element_id) or self.name

    def is_node(self, node: str) -> bool:
        """True when *node* (a name or node ref) names this figure."""
        return node in (self.name, self.ref)


# The node key, as ``_recipe_ops._KEY_JS`` (element ID; DS4 exposes it as a
# numeric property, spec 15.2; the name only as a last resort).
_KEY_JS = """
function _key(n) {
    if (typeof n.getElementID === "function") return String(n.getElementID());
    if (typeof n.elementID === "number") return String(n.elementID);
    return n.getName();
}"""


def figures_script(labels: list[str], owned_names: list[str]) -> str:
    """Read-only script reporting figures (by label / owned name) and their fitted items."""
    esc = ScriptBuilder.escape_string
    labels_js = "[" + ", ".join(esc(x) for x in labels) + "]"
    names_js = "[" + ", ".join(esc(x) for x in owned_names) + "]"
    # Confirmed on DS4 by the Task 1 live probe (spec 15); DS6 pending.
    return ScriptBuilder.iife(f"""// recipe:figures{_KEY_JS}{FIND_REF_JS}
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
        if (_follow(c)) continue;  // fitted by Studio: the item's own sub-parts
        // bones and the outfit's "Clothing Expander" helper are the asset's own (spec 15.4)
        if (!c.inherits("DzBone") && !c.inherits("DzPushModifierWeightNode"))
            out.push(c.getName());
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
    if (_seen[_key(n)]) return;
    _seen[_key(n)] = true;
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
    var owned = _findRef(_owned[_o]);
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
        items.push({{name: it.getName(), label: it.getLabel(), element_id: _key(it), type: _type(it),
                    source_path: _source(it), record: _rec(it), foreign: _foreign(it, [])}});
    }}
    _out.figures.push({{name: fig.getName(), label: fig.getLabel(), element_id: _key(fig),
                       record: _rec(fig),
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
            foreign_children=tuple(i.get("foreign") or ()),
            element_id=_eid(i.get("element_id"))) for i in f.get("items") or []),
        element_id=_eid(f.get("element_id")))
        for f in payload.get("figures") or []]
    out: dict[str, list[FigureInfo]] = {label: [] for label in labels}
    for info in infos:
        if info.label in out:
            out[info.label].append(info)
    for name in owned_names:
        out.setdefault(name, [])
        out[name] += [i for i in infos if i.is_node(name) and i not in out[name]]
    return out


def _eid(value: object) -> str | None:
    return str(value) if value not in (None, "") else None


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
