"""Scene-recipe data-item persistence spike (5d6f.18, Task 1).

Verifies that the ownership records dazpy.recipe stores in Daz data items
survive a scene save, clear and reload, plus a few behaviours the recipe
store depends on.  Kept as a diagnostic.

    python scripts/spikes/recipe_data_item_spike.py --phase write --scene-path C:/temp/recipe_spike.duf
    python scripts/spikes/recipe_data_item_spike.py --phase read  --scene-path C:/temp/recipe_spike.duf
    python scripts/spikes/recipe_data_item_spike.py --phase probe   # extra checks, needs Genesis 9 installed

``read`` clears the scene first (Scene.clear(), no save prompt), then loads.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from dazpy import DazClient, DazScene  # noqa: E402
from dazpy._script_builder import ScriptBuilder  # noqa: E402

G9 = "/People/Genesis 9/Genesis 9.duf"

_WRITE = """
var node = new DzNode();
node.setName("recipe_spike");
node.setLabel("recipe-spike");
Scene.addNode(node);
var d = new DzSimpleElementData("dazpy.scene_recipe", true);
d.getSettings().setStringValue("record", '{"probe":42}');
node.addDataItem(d);
var s = new DzSimpleSceneData("dazpy.scene_recipe.spike", true);
s.getSettings().setStringValue("manifest", '{"probe":7}');
Scene.addDataItem(s);
return true;
"""

_READ = """
var node = Scene.findNodeByLabel("recipe-spike");
var it = node ? node.findDataItem("dazpy.scene_recipe") : null;
var s = Scene.findDataItem("dazpy.scene_recipe.spike");
return {
  node_found: !!node,
  record: it ? it.getSettings().getStringValue("record") : null,
  manifest: s ? s.getSettings().getStringValue("manifest") : null
};
"""


def _run(client: DazClient, body: str):
    res = client.execute(ScriptBuilder.iife(body))
    if not res.success:
        raise SystemExit(f"script failed: {res.error}")
    return res.value


def _clear(client: DazClient) -> None:
    _run(client, "Scene.clear(); return true;")


def phase_write(client: DazClient, scene_path: str) -> None:
    _clear(client)
    _run(client, _WRITE)
    DazScene(client).save(scene_path)
    print(f"wrote probe items and saved {scene_path}")


def phase_read(client: DazClient, scene_path: str) -> None:
    _clear(client)
    DazScene(client).load(scene_path)
    out = _run(client, _READ)
    print(json.dumps(out, indent=2))
    ok = out.get("record") == '{"probe":42}' and out.get("manifest") == '{"probe":7}'
    print("PERSISTED: Y" if ok else "PERSISTED: N")


def _resolve(client: DazClient, rel: str) -> str | None:
    esc = ScriptBuilder.escape_string(rel)
    return _run(client, f"""
var cm = App.getContentMgr();
var p = cm.findFile({esc}, DzContentMgr.AllDirs);
if (!p) p = cm.findFile({esc});
return p || null;
""")


_LOAD = """
var before = {};
for (var i = 0; i < Scene.getNumNodes(); i++) before[Scene.getNode(i).elementID] = true;
// A figure loaded while another is selected pops a modal replace/add dialog.
Scene.selectAllNodes(false);
var ok = App.getContentMgr().openFile(%s, true);
var roots = [], added = [];
for (var i = 0; i < Scene.getNumNodes(); i++) {
  var n = Scene.getNode(i);
  if (before[n.elementID]) continue;
  added.push(n.name);
  if (!n.getNodeParent()) roots.push(n.name);
}
return {ok: ok, roots: roots, added_count: added.length};
"""

_CHILDREN = """
var n = Scene.findNode(%s);
var out = [];
function walk(p) {
  for (var i = 0; i < p.getNumNodeChildren(); i++) {
    var c = p.getNodeChild(i);
    out.push({name: c.name, cls: c.className(), bone: c.inherits("DzBone"),
              figure: c.inherits("DzFigure"),
              follow: (c.inherits("DzFigure") && c.getFollowTarget) ? String(c.getFollowTarget() ? c.getFollowTarget().name : "") : ""});
    if (!c.inherits("DzBone")) walk(c);
  }
}
if (n) walk(n);
return out.filter(function(x){ return !x.bone; });
"""

_DUP = """
var n = Scene.findNode(%s);
Scene.selectAllNodes(false);
n.select(true);
Scene.setPrimarySelection(n);
var before = Scene.getNumNodes();
var act = MainWindow.getActionMgr().findAction("DzDuplicateNodeAction");
if (!act) return {error: "no DzDuplicateNodeAction"};
act.trigger();
var copy = Scene.getPrimarySelection();
if (!copy || copy === n) return {error: "duplicate made no new selection", count_delta: Scene.getNumNodes() - before};
var it = copy.findDataItem("dazpy.scene_recipe");
return {copy: copy.name, copy_has_item: !!it,
        record: it ? it.getSettings().getStringValue("record") : null};
"""


def phase_probe(client: DazClient, duplicate: bool = False) -> None:
    report: dict = {}
    path = _resolve(client, G9)
    report["g9_resolved"] = path
    if not path:
        print(json.dumps(report, indent=2))
        raise SystemExit("Genesis 9 not found in the content library")
    _clear(client)
    esc = ScriptBuilder.escape_string(path)
    first = _run(client, _LOAD % esc)
    second = _run(client, _LOAD % esc)
    report["load_roots"] = [first, second]
    report["unique_root_names"] = (len(first["roots"]) == 1 and len(second["roots"]) == 1
                                   and first["roots"][0] != second["roots"][0])
    root = first["roots"][0]
    report["non_bone_descendants"] = _run(client, _CHILDREN % ScriptBuilder.escape_string(root))
    if not duplicate:
        print(json.dumps(report, indent=2))
        return
    # Tag the first figure, then duplicate it and see if the record travels.
    # Opt-in (--duplicate): triggers a UI action, unverified for dialogs.
    _run(client, f"""
var n = Scene.findNode({ScriptBuilder.escape_string(root)});
var d = new DzSimpleElementData("dazpy.scene_recipe", true);
d.getSettings().setStringValue("record", '{{"probe":"dup"}}');
n.addDataItem(d);
return true;""")
    report["duplicate"] = _run(client, _DUP % ScriptBuilder.escape_string(root))
    print(json.dumps(report, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default="http://127.0.0.1:18811")
    ap.add_argument("--token-file", default=None)
    ap.add_argument("--phase", choices=["write", "read", "probe"], required=True)
    ap.add_argument("--duplicate", action="store_true",
                    help="probe: also trigger Duplicate Node(s) on a tagged figure")
    ap.add_argument("--scene-path", default="C:/temp/recipe_spike.duf")
    a = ap.parse_args()
    kwargs = {}
    if a.token_file:
        with open(a.token_file, encoding="utf-8") as f:
            kwargs["token"] = f.read().strip()
    host, _, port = a.url.split("//", 1)[-1].partition(":")
    client = DazClient(host=host, port=int(port or 18811), timeout=300, **kwargs)
    if a.phase == "write":
        phase_write(client, a.scene_path)
    elif a.phase == "read":
        phase_read(client, a.scene_path)
    else:
        phase_probe(client, a.duplicate)


if __name__ == "__main__":
    main()
