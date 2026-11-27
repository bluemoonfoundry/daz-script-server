#!/usr/bin/env python
"""Live probe of the Daz Studio APIs scene recipe v2 depends on (5d6f.21, Task 1).

Not a unit test (``tests.py`` does not collect it).  Prints one JSON document.

Phases:
  1. read-only: CMS metadata (findAssetsForFile, products), searchForAssets /
     searchForProducts shape and timing, the content-type vocabulary;
  2. ``--load`` only: loads the figure (scene must be empty, or already hold a
     figure labelled ``--figure-label`` from an earlier run), then the hair and
     the wearables preset with fitting method (a) nothing selected +
     setFollowTarget/parent and method (b) figure as sole primary selection;
  3. read-only: runs the provisional dazpy scripts (StudioFinder, compat,
     figures readback, getAssetUriForNode drift) against the live scene.

Safety: every load passes only the absolute path ``resolve_files`` returned
(a content-relative path makes ``Scene.loadScene`` pop a modal), and the load
script re-checks ``DzFileInfo.exists`` first.  The ``--g8-hair-path`` item is
only ever read from the asset database, never loaded.  Method (b) runs only for items whose metadata says they fit the
figure.  Every load clears the selection first (except method (b), which
selects only the figure).  Nothing is deleted.  A load that does not return
within ``--load-timeout`` is reported as a possible modal and the probe stops.

Usage:
  python tests/live_probe_asset_apis.py --figure-label Abby \\
      --hair-path "/People/Genesis 9/Hair/Daz Originals/Kara Ponytail/Kara Ponytail.duf" \\
      --outfit-path "/People/Genesis 9/Clothing/Daz Originals/Detective Outfit/Detective !Outfit.duf" \\
      --g8-hair-path "/People/Genesis 8 Female/Hair/Goldtassel/Cafe Curls/Cafe Curls.duf" \\
      [--load] [--out probe.json]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dazpy  # noqa: E402
from dazpy._recipe_ops import resolve_files  # noqa: E402
from dazpy._script_builder import ScriptBuilder  # noqa: E402

TO_JS = ScriptBuilder.to_js

# Shared helpers, prepended to every probe body.
_HELPERS = r"""
function _s(v) { return (v === null || v === undefined) ? null : String(v); }
function _arr(v) { var o = []; if (!v) return o; for (var i = 0; i < v.length; i++) o.push(String(v[i])); return o; }
// DS4 has no getElementID(); elementID is a numeric property.  Names repeat when a
// file is loaded twice, so a name key would hide the second load's nodes.
function _key(n) {
    if (typeof n.getElementID === "function") return String(n.getElementID());
    if (n.elementID !== undefined) return String(n.elementID);
    return n.getName();
}
function _pump(r, getN, maxMs) {
    var t0 = new Date().getTime(), immediate = getN(r), last = immediate, stableAt = t0, firstAt = null;
    while (true) {
        processEvents();
        var n = getN(r), now = new Date().getTime();
        if (n > 0 && firstAt === null) firstAt = now - t0;
        if (n !== last) { last = n; stableAt = now; }
        if (n > 0 && now - stableAt > 750) break;
        if (now - t0 > maxMs) break;
    }
    return {immediate: immediate, n: last, first_ms: firstAt, total_ms: new Date().getTime() - t0};
}
function _asset(a) {
    var p = null;
    try { p = a.getProduct(); } catch (e) { p = null; }
    return {asset_name: _s(a.assetName), relative_file_path: _s(a.getRelativeFilePath()),
            local_file: _s(a.getAsLocalFile()), original_path: _s(a.originalPath),
            original_filename: _s(a.originalFilename), content_type: _s(a.contentType),
            compatibility_base: _s(a.compatibilityBase), compatibilities: _arr(a.compatibilities),
            vendor_compatibilities: _arr(a.vendorCompatibilities),
            user_compatibilities: _arr(a.userCompatibilities),
            product_name: _s(a.productName), product_id: _s(a.productID), store_id: _s(a.storeID),
            product_guid: _s(a.productGUID), is_installed: a.isInstalled,
            has_assetID_method: typeof a.assetID, has_getAsFilePath: typeof a.getAsFilePath,
            product: p ? {title: _s(p.title), token: _s(p.token), store: _s(p.store),
                          guid: _s(p.guid), container_name: _s(p.getContainerName())} : null};
}
function _pres(n) {
    var p = (typeof n.getPresentation === "function") ? n.getPresentation() : null;
    if (!p) return null;
    // DS4: autoFitBase is a property, not the method the docs show.
    var afb = (typeof p.autoFitBase === "function") ? _s(p.autoFitBase()) : _s(p.autoFitBase);
    return {type: _s(p.type), preferredBase: _s(p.preferredBase), extendedBases: _arr(p.extendedBases),
            autoFitBase: afb, autoFitBase_is_function: typeof p.autoFitBase === "function",
            label: _s(p.label)};
}
function _collision(n) {
    var out = [], obj = (typeof n.getObject === "function") ? n.getObject() : null;
    if (!obj) return out;
    for (var i = 0; i < obj.getNumModifiers(); i++) {
        var m = obj.getModifier(i), pr = m.findProperty ? m.findProperty("Collision Item") : null;
        if (pr) { var v = pr.getValue(); out.push({modifier: _s(m.getName()), collision_item: v ? _s(v.getName()) : null}); }
    }
    return out;
}
function _desc(n) {
    var mgr = App.getAssetMgr(), ft = (typeof n.getFollowTarget === "function") ? n.getFollowTarget() : null;
    var par = n.getNodeParent(), uri = null, base = null, t4n = null;
    try { uri = _s(mgr.getAssetUriForNode(n)); } catch (e) { uri = "ERROR: " + e; }
    try { base = _s(mgr.getCompatibilityBasePathForNode(n)); } catch (e2) { base = "ERROR: " + e2; }
    try { t4n = _s(mgr.getTypeForNode(n)); } catch (e3) { t4n = "ERROR: " + e3; }
    return {name: n.getName(), label: n.getLabel(), element_id: _s(n.elementID),
            has_getElementID: typeof n.getElementID, class_name: _s(n.className()),
            is_figure: n.inherits("DzFigure"), is_skeleton: n.inherits("DzSkeleton"),
            presentation: _pres(n), type_for_node: t4n, follow_target: ft ? ft.getName() : null,
            parent: par ? par.getName() : null, asset_uri: uri, compatibility_base_path: base,
            collision: _collision(n)};
}
function _findLabel(label) {
    var all = Scene.getNodeList(), hits = [];
    for (var i = 0; i < all.length; i++) {
        var n = all[i], ft = (typeof n.getFollowTarget === "function") ? n.getFollowTarget() : null;
        if (n.inherits("DzFigure") && !ft && n.getLabel() === label) hits.push(n);
    }
    return hits;
}
"""


class ProbeError(Exception):
    pass


class Probe:
    def __init__(self, client: dazpy.DazClient, load_timeout: float) -> None:
        self.client = client
        self.load_timeout = load_timeout

    def js(self, body: str, timeout: float = 60.0):
        """Run *body* (try/catch-wrapped); errors come back as {"error": ...}."""
        script = ScriptBuilder.iife(_HELPERS + "\ntry {\n" + body +
                                    "\n} catch (e) { return {error: String(e), line: e.lineNumber}; }")
        t0 = time.monotonic()
        try:
            # After a load/fit Studio reports busy for a while; wait it out, but a
            # main thread busy for minutes may be a modal, so stop then.
            value = self.client.execute(script, timeout=timeout, retry_on_busy=True,
                                        max_wait=120.0).value
        except dazpy.exceptions.StudioBusyError as e:
            raise ProbeError(f"Studio still busy after 120s (possible modal); probe stopped: {e}") from e
        except Exception as e:  # timeouts included
            elapsed = time.monotonic() - t0
            if elapsed >= timeout * 0.95:
                raise ProbeError(f"no reply after {elapsed:.0f}s: POSSIBLE MODAL DIALOG in Studio; "
                                 "probe stopped") from e
            return {"error": f"{type(e).__name__}: {e}"}
        return value


# ── phase 1: read-only metadata and search ────────────────────────────────────

def probe_env(p: Probe) -> dict:
    return p.js("""
var cm = App.getContentMgr(), dirs = [];
for (var i = 0; i < cm.getNumContentDirectories(); i++) dirs.push(_s(cm.getContentDirectoryPath(i)));
return {version: _s(App.longVersionString), cms_connected: App.getAssetMgr().isConnectedToCMS(),
        num_nodes: Scene.getNumNodes(), num_selected: Scene.getNumSelectedNodes(), content_dirs: dirs};""")


def probe_files(p: Probe, paths: dict[str, str], figure_base_hint: str | None) -> dict:
    return p.js(f"""
var paths = {TO_JS(paths)}, mgr = App.getAssetMgr(), cm = App.getContentMgr(), out = {{}};
for (var role in paths) {{
    var path = paths[role], rel = path.charAt(0) === "/" ? path.substring(1) : path;
    var abs = _s(cm.findFile(path));
    var relBack = null;
    try {{ relBack = abs ? _s(cm.getRelativePath(abs, true)) : null; }} catch (e) {{ relBack = "ERROR: " + e; }}
    var withSlash = mgr.findAssetsForFile(path, true, true);
    var noSlash = mgr.findAssetsForFile(rel, true, true);
    var assets = [];
    for (var i = 0; noSlash && i < noSlash.length; i++) assets.push(_asset(noSlash[i]));
    var prods = [];
    try {{
        var fp = mgr.findProductsForFile(rel);
        for (var j = 0; fp && j < fp.length; j++) prods.push({{title: _s(fp[j].title), token: _s(fp[j].token)}});
    }} catch (e2) {{ prods = "ERROR: " + e2; }}
    var tcf = null;
    try {{ tcf = _s(mgr.getTypeForContentFile(abs || path)); }} catch (e3) {{ tcf = "ERROR: " + e3; }}
    out[role] = {{path: path, find_file: abs, get_relative_path: relBack,
                 n_with_leading_slash: withSlash ? withSlash.length : null,
                 n_without_leading_slash: noSlash ? noSlash.length : null,
                 assets: assets, products_for_file: prods, type_for_content_file: tcf}};
}}
return out;""")


def probe_search(p: Probe, phrase: str) -> dict:
    return p.js(f"""
var mgr = App.getAssetMgr(), out = {{}};
var A = function (r) {{ return r.getNumAssets(); }}, K = function (r) {{ return r.getNumChildContainers(); }};
function sample(r, k) {{
    var s = [];
    for (var i = 0; i < Math.min(r.getNumAssets(), k); i++) {{
        var a = r.getAsset(i);
        s.push({{relative_file_path: _s(a.getRelativeFilePath()), content_type: _s(a.contentType),
                compatibilities: _arr(a.compatibilities), product_name: _s(a.productName),
                product_id: _s(a.productID)}});
    }}
    return s;
}}
var r = mgr.searchForAssets({TO_JS(phrase)}, [], [], [], 0);
out.result_class = _s(r.className());
out.plain = _pump(r, A, 10000);
out.plain.has_more = r.hasMoreSearchResults();
out.plain.sample = sample(r, 3);
var rf = mgr.searchForAssets({TO_JS(phrase)}, [], ["/Genesis 9/Base"], ["Follower/Hair"], 0);
out.g9base_hair = _pump(rf, A, 10000);
out.g9base_hair.sample = sample(rf, 5);
var rt = mgr.searchForAssets("", [], [], ["Follower/Hair"], 0);
out.empty_phrase_type_hair = _pump(rt, A, 10000);
var rb = mgr.searchForAssets({TO_JS(phrase)}, [], [], ["Follower/Not-A-Type"], 0);
out.unknown_type_filter = _pump(rb, A, 10000);
var re = mgr.searchForAssets("", [], ["/Genesis 9/Base"], [], 0);
out.empty_phrase_g9base = _pump(re, A, 30000);
try {{
    var p5 = mgr.searchForProducts({TO_JS(phrase)}, [], [], [], 0);
    out.search_products_5_args = {{ok: true, kids: p5 ? p5.getNumChildContainers() : null}};
}} catch (e) {{ out.search_products_5_args = {{ok: false, error: String(e)}}; }}
var p6 = mgr.searchForProducts("Genesis 9 Starter Essentials", [], [], [], 1, 0);
out.search_products_6_args = _pump(p6, K, 10000);
var kids = p6.getChildContainers(), ps = [];
for (var k = 0; k < Math.min(kids.length, 5); k++)
    ps.push({{container_name: _s(kids[k].getContainerName()), title: _s(kids[k].title),
             token: _s(kids[k].token), num_assets: kids[k].getNumAssets()}});
out.search_products_6_args.sample = ps;
var byName = mgr.findProductsByName("Genesis 9 Starter Essentials");
out.find_products_by_name = [];
for (var b = 0; byName && b < byName.length; b++) {{
    var pr = byName[b], pa = mgr.searchForProductAssets(pr, "", [], [], [], 0);
    var pump = _pump(pa, A, 10000);
    out.find_products_by_name.push({{title: _s(pr.title), token: _s(pr.token),
        num_assets_direct: pr.getNumAssets(), product_assets_search: pump}});
}}
var bySku = mgr.findProductByStoreToken("DAZ 3D", "86958");
out.find_product_by_store_token = bySku ? {{title: _s(bySku.title), token: _s(bySku.token),
    num_assets_direct: bySku.getNumAssets(),
    first_asset: bySku.getNumAssets() ? _asset(bySku.getAsset(0)) : null}} : null;
out.sort_enums = {{NoSort: DzAssetMgr.NoSort, NameSort: DzAssetMgr.NameSort,
                  InstalledState: DzAssetMgr.InstalledState, NotInstalledState: DzAssetMgr.NotInstalledState}};
return out;""", timeout=180)


def probe_types(p: Probe) -> dict:
    return p.js("""
var mgr = App.getAssetMgr(), out = [];
for (var i = 1; i < 600; i++) {
    var t = _s(mgr.getType(i));
    if (t && /^(Actor|Follower|Preset\\/Wearables|Preset\\/Character)/.test(t)) out.push(t);
}
return {types: out, isHairType: mgr.isHairType("Follower/Hair"),
        isClothingType_shirt: mgr.isClothingType("Follower/Wardrobe/Shirt"),
        isFollowingType_wearables: mgr.isFollowingType("Preset/Wearables")};""")


# ── phase 2: loads ────────────────────────────────────────────────────────────

def load_figure(p: Probe, path: str, label: str) -> dict:
    existing = p.js(f"""
var hits = _findLabel({TO_JS(label)}), all = Scene.getNodeList(), others = 0;
// Studio creates its render-settings nodes lazily; they do not make a scene non-scratch.
for (var i = 0; i < all.length; i++)
    if (!all[i].inherits("DzTonemapperNode") && !all[i].inherits("DzEnvironmentNode")) others++;
return {{n: hits.length, num_nodes: others, desc: hits.length ? _desc(hits[0]) : null}};""")
    if existing.get("n") == 1:
        return {"reused": True, "figure": existing["desc"]}
    if existing.get("n", 0) > 1:
        raise ProbeError(f"{existing['n']} figures labelled {label!r}; refusing")
    if existing.get("num_nodes"):
        raise ProbeError("scene is not empty and holds no figure labelled "
                         f"{label!r}; refusing to load into a scene that is not a scratch scene")
    return p.js(f"""
if (!new DzFileInfo({TO_JS(path)}).exists()) return {{error: "not an existing absolute file, not loaded: " + {TO_JS(path)}}};
Scene.selectAllNodes(false);
var t0 = new Date().getTime();
Scene.loadScene({TO_JS(path)}, DzScene.MergeFile);
var ms = new Date().getTime() - t0, all = Scene.getNodeList(), roots = [], fig = null;
for (var i = 0; i < all.length; i++) if (!all[i].getNodeParent()) roots.push(all[i]);
for (var j = 0; j < roots.length; j++) if (roots[j].inherits("DzFigure")) {{ fig = roots[j]; break; }}
if (!fig) return {{error: "no figure root after load"}};
fig.setLabel({TO_JS(label)});
var fol = [];
for (var k = 0; k < all.length; k++) {{
    var ft = (typeof all[k].getFollowTarget === "function") ? all[k].getFollowTarget() : null;
    if (ft && ft == fig) fol.push(_desc(all[k]));  // == : wrappers of one node are not ===
}}
return {{reused: false, load_ms: ms, num_roots: roots.length, figure: _desc(fig), figure_followers: fol}};""",
                timeout=p.load_timeout)


def load_item(p: Probe, path: str, label: str, method: str) -> dict:
    """Load *path* with method "a" (nothing selected) or "b" (figure primary selection);
    report what the load added, then (method a) fit each added figure root."""
    select = ("Scene.selectAllNodes(false);" if method == "a" else
              "Scene.selectAllNodes(false); Scene.setPrimarySelection(fig);")
    loaded = p.js(f"""
var hits = _findLabel({TO_JS(label)});
if (hits.length !== 1) return {{error: hits.length + " figures labelled " + {TO_JS(label)}}};
if (!new DzFileInfo({TO_JS(path)}).exists()) return {{error: "not an existing absolute file, not loaded: " + {TO_JS(path)}}};
var fig = hits[0], before = {{}}, all0 = Scene.getNodeList();
for (var i = 0; i < all0.length; i++) before[_key(all0[i])] = true;
{select}
var selBefore = [], sl = Scene.getSelectedNodeList();
for (var q = 0; q < sl.length; q++) selBefore.push(sl[q].getName());
var t0 = new Date().getTime();
Scene.loadScene({TO_JS(path)}, DzScene.MergeFile);
var ms = new Date().getTime() - t0, all = Scene.getNodeList(), added = [], top = [], extra = [];
for (var j = 0; j < all.length; j++) if (!before[_key(all[j])]) added.push(all[j]);
var addedKeys = {{}};
for (var a = 0; a < added.length; a++) addedKeys[_key(added[a])] = true;
for (var b = 0; b < added.length; b++) {{
    var par = added[b].getNodeParent();
    if (!par || !addedKeys[_key(par)]) top.push(_desc(added[b]));
    else if (!added[b].inherits("DzBone")) extra.push({{name: added[b].getName(), label: added[b].getLabel(),
        class_name: _s(added[b].className()), parent: par.getName()}});
}}
var selAfter = [], sl2 = Scene.getSelectedNodeList();
for (var r = 0; r < sl2.length; r++) selAfter.push(sl2[r].getName());
return {{method: {TO_JS(method)}, load_ms: ms, selection_before_load: selBefore, selection_after_load: selAfter,
        num_added: added.length, top_level_added: top, non_bone_descendants_added: extra}};""",
                  timeout=p.load_timeout)
    out = {"load": loaded}
    if method == "a" and isinstance(loaded, dict) and not loaded.get("error"):
        roots = [n["name"] for n in loaded.get("top_level_added") or [] if n.get("parent") is None]
        out["fit"] = p.js(f"""
var fig = _findLabel({TO_JS(label)})[0], names = {TO_JS(roots)}, res = [];
for (var i = 0; i < names.length; i++) {{
    var n = null, all = Scene.getNodeList();
    for (var j = 0; j < all.length; j++) if (all[j].getName() === names[i] && !all[j].getNodeParent()) {{ n = all[j]; break; }}
    if (!n) {{ res.push({{name: names[i], error: "not found at root"}}); continue; }}
    if (!n.inherits("DzFigure")) {{ res.push({{name: names[i], skipped: "not a DzFigure"}}); continue; }}
    n.setFollowTarget(fig);
    fig.addNodeChild(n, true);
    res.push(_desc(n));
}}
Scene.selectAllNodes(false);
return res;""")
    else:
        p.js("Scene.selectAllNodes(false); return true;")
    return out


def compatible(meta: dict, figure_base: str | None) -> bool:
    if not figure_base:
        return False
    fb = figure_base.casefold()
    for a in meta.get("assets") or []:
        for b in a.get("compatibilities") or []:
            b = b.casefold().rstrip("/")
            if fb == b or fb.startswith(b + "/"):
                return True
    return False


# ── phase 3: provisional dazpy scripts against the live scene ─────────────────

def probe_followers(p: Probe, label: str) -> dict:
    """Read-only: every node following the labelled figure, and wrapper equality."""
    return p.js(f"""
var hits = _findLabel({TO_JS(label)});
if (hits.length !== 1) return {{error: hits.length + " figures labelled " + {TO_JS(label)}}};
var fig = hits[0], all = Scene.getNodeList(), out = [], strict = 0, loose = 0, nested = [];
for (var i = 0; i < all.length; i++) {{
    var ft = (typeof all[i].getFollowTarget === "function") ? all[i].getFollowTarget() : null;
    if (!ft) continue;
    if (ft === fig) strict++;
    if (ft == fig) {{ loose++; out.push(_desc(all[i])); }}
    else nested.push({{name: all[i].getName(), label: all[i].getLabel(), follow_target: ft.getName()}});
}}
return {{figure: _desc(fig), followers_strict_eq: strict, followers_loose_eq: loose,
        followers: out, followers_of_other_nodes: nested}};""")


def run_provisional(client: dazpy.DazClient, label: str, paths: dict[str, str]) -> dict:
    from dazpy import _asset_compat, _asset_finder, _recipe_fitted, recipe

    def attempt(fn):
        try:
            return fn()
        except Exception as e:
            return {"exception": f"{type(e).__name__}: {e}", "trace": traceback.format_exc(limit=2)}

    out: dict = {}
    finder = _asset_finder.StudioFinder(client)
    out["studio_finder_search_ponytail_hair"] = attempt(
        lambda: [c.__dict__ for c in finder.search("ponytail", type="hair", limit=5)])
    out["studio_finder_product_files"] = attempt(
        lambda: [c.__dict__ for c in finder.product_files(product="Genesis 9 Starter Essentials")][:5])
    out["read_compat"] = attempt(lambda: {
        k: v.__dict__ for k, v in _asset_compat.read_compat(client, list(paths.values())).items()})
    out["base_of_asset_figure"] = attempt(lambda: _asset_compat.base_of_asset(client, paths["figure"]))
    figs = attempt(lambda: _recipe_fitted.read_figures(client, [label], []))
    if isinstance(figs, dict) and "exception" not in figs:
        figs = {k: [{"name": f.name, "label": f.label, "compat_base": f.compat_base,
                     "items": [{"name": i.name, "label": i.label, "type": i.type,
                                "source_path": i.source_path,
                                "same_file_as_hair": recipe._same_file(i.source_path or "", paths["hair"]),
                                "same_file_as_outfit": recipe._same_file(i.source_path or "",
                                                                         paths["outfit"]),
                                "foreign": list(i.foreign_children)} for i in f.items]}
                    for f in v] for k, v in figs.items()}
    out["read_figures"] = figs
    out["read_figure_labels"] = attempt(lambda: _recipe_fitted.read_figure_labels(client))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--figure-label", default="Abby")
    ap.add_argument("--figure-path", default="/People/Genesis 9/Genesis 9.duf")
    ap.add_argument("--hair-path", required=True, help="compatible hair (content path)")
    ap.add_argument("--outfit-path", required=True, help="compatible wearables preset (content path)")
    ap.add_argument("--g8-hair-path", required=True, help="incompatible item: metadata only, never loaded")
    ap.add_argument("--search-phrase", default="ponytail")
    ap.add_argument("--load", action="store_true",
                    help="phase 2: load into the scratch scene (empty, or holding the probe figure)")
    ap.add_argument("--load-timeout", type=float, default=240.0)
    ap.add_argument("--steps", default="hair_a,outfit_a,hair_b,outfit_b",
                    help="load steps to run (resume a run without reloading earlier items)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=18811)
    ap.add_argument("--out", help="also write the JSON here")
    args = ap.parse_args(argv)

    client = dazpy.DazClient(host=args.host, port=args.port)
    p = Probe(client, args.load_timeout)
    paths = {"figure": args.figure_path, "hair": args.hair_path, "outfit": args.outfit_path,
             "g8_hair": args.g8_hair_path}
    report: dict = {"args": vars(args)}
    try:
        report["env"] = probe_env(p)
        # Every load uses only the absolute path resolve_files returns (findFile over
        # the content dirs, then DzFileInfo.exists; never opens a file).  Loading a
        # content-relative path pops a "could not find file" modal.  The G8 item is
        # resolved for the record only; it is never loaded.
        report["resolved"] = resolve_files(client, list(paths.values()))
        report["files"] = probe_files(p, paths, None)
        report["search"] = probe_search(p, args.search_phrase)
        report["content_types"] = probe_types(p)
        if args.load:
            absolute = report["resolved"]
            missing = [paths[r] for r in ("figure", "hair", "outfit") if not absolute.get(paths[r])]
            if missing:
                raise ProbeError(f"not found (not loaded): {', '.join(missing)}")
            fig = load_figure(p, absolute[paths["figure"]], args.figure_label)
            report["figure"] = fig
            if not isinstance(fig, dict) or fig.get("error"):
                raise ProbeError(f"figure load failed: {fig}")
            base = (fig.get("figure") or {}).get("compatibility_base_path")
            files = report["files"]
            report["item_compatible_from_metadata"] = {
                role: compatible(files.get(role) or {}, base) for role in ("hair", "outfit", "g8_hair")}
            loads: dict = {}
            for step in [x.strip() for x in args.steps.split(",") if x.strip()]:
                role, method = step.rsplit("_", 1)
                if role not in ("hair", "outfit") or method not in ("a", "b"):
                    raise ProbeError(f"unknown step {step!r} (the G8 item is never loaded)")
                key = f"{role}_method_{method}"
                if method == "b" and not report["item_compatible_from_metadata"][role]:
                    loads[key] = {"skipped": "not compatible per metadata; method (b) not tested"}
                    continue
                loads[key] = load_item(p, absolute[paths[role]], args.figure_label, method)
            report["loads"] = loads
            report["g8_hair"] = "metadata only (see files.g8_hair); never loaded"
        report["followers"] = probe_followers(p, args.figure_label)
        report["provisional"] = run_provisional(client, args.figure_label, paths)
        report["final_scene"] = p.js("return {num_nodes: Scene.getNumNodes(), "
                                     "num_selected: Scene.getNumSelectedNodes()};")
    except ProbeError as e:
        report["stopped"] = str(e)
    text = json.dumps(report, indent=1, default=str)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
    return 1 if "stopped" in report else 0


if __name__ == "__main__":
    sys.exit(main())
