"""Ownership records, manifest and live readback for scene recipes.

Every node a recipe creates carries a Daz element data item
(:data:`DATA_ITEM_NAME`) whose ``record`` setting is an :class:`EntityRecord`
JSON string: who owns the node, plus the last-applied (``desired``) and
last-observed (``observed``) channel values.  A scene-level data item
(``dazpy.scene_recipe.<recipe_id>``) holds the :class:`Manifest`.

This is the data-item backend.  Another backend only has to provide the same
three script builders and a ``read_live`` returning :class:`LiveState`.
Nodes are addressed by Daz node name (``getName()``), assumed unique per scene.

Observed-channel conventions (controller ruling): ``transform.position`` is
world (``getWSPos``); ``transform.rotation`` is the node's LOCAL X/Y/Z rotation
controls, i.e. what ``DazNode.set_rotation`` writes.  Recipe nodes are created
at scene root so the two coincide unless the user re-parents them.  The
environment ``mode`` is observed as the raw enum int and must be written back
with ``setValue(int)``.  Entity ``kind`` comes from the record's path prefix,
not the node class (a rigged prop is still a prop).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from ._node import NodeIdentifier
from ._recipe_desired import EntityKind
from ._render import DazRenderSettings
from ._script_builder import ScriptBuilder

if TYPE_CHECKING:
    from ._client import DazClient

DATA_ITEM_NAME = "dazpy.scene_recipe"
_RECORD_KEY = "record"
_MANIFEST_KEY = "manifest"


def scene_item_name(recipe_id: str) -> str:
    """Name of the scene-level data item holding *recipe_id*'s manifest."""
    return f"{DATA_ITEM_NAME}.{recipe_id}"


@dataclass(frozen=True)
class EntityRecord:
    """Ownership + last-applied/last-observed channel values for one entity."""

    recipe_id: str
    path: str
    recipe_version: int
    desired: dict[str, dict]
    observed: dict[str, dict]

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, s: str) -> "EntityRecord":
        d = json.loads(s)
        return cls(recipe_id=d["recipe_id"], path=d["path"],
                   recipe_version=int(d["recipe_version"]),
                   desired=d.get("desired") or {}, observed=d.get("observed") or {})


@dataclass(frozen=True)
class Manifest:
    """Every entity path a recipe owns (including ones whose node is gone)."""

    recipe_id: str
    entities: tuple[str, ...]
    environment: EntityRecord | None

    def to_json(self) -> str:
        return json.dumps({
            "recipe_id": self.recipe_id,
            "entities": list(self.entities),
            "environment": json.loads(self.environment.to_json()) if self.environment else None,
        }, sort_keys=True)

    @classmethod
    def from_json(cls, s: str) -> "Manifest":
        d = json.loads(s)
        env = d.get("environment")
        return cls(recipe_id=d["recipe_id"], entities=tuple(d.get("entities") or ()),
                   environment=EntityRecord.from_json(json.dumps(env)) if env else None)


@dataclass(frozen=True)
class LiveEntity:
    path: str
    node_name: str
    kind: EntityKind
    record: EntityRecord
    observed: dict[str, dict]
    foreign_children: tuple[str, ...]
    element_id: int | None = None


@dataclass(frozen=True)
class LiveState:
    manifest: Manifest | None
    entities: dict[str, LiveEntity]
    environment_observed: dict | None


# ── script builders ───────────────────────────────────────────────────────────

def write_record_script(node_name: str, record: EntityRecord) -> str:
    """Script attaching *record* to the node, replacing any existing record."""
    esc = ScriptBuilder.escape_string
    return ScriptBuilder.iife(f"""
var _node = Scene.findNode({esc(node_name)});
if (!_node) return false;
var _old = _node.findDataItem({esc(DATA_ITEM_NAME)});
if (_old) _node.removeDataItem(_old);
var _item = new DzSimpleElementData({esc(DATA_ITEM_NAME)}, true);
_item.getSettings().setStringValue({esc(_RECORD_KEY)}, {esc(record.to_json())});
_node.addDataItem(_item);
return true;""")


def remove_record_script(node_name: str) -> str:
    """Script removing the ownership record from the node (no-op if absent)."""
    esc = ScriptBuilder.escape_string
    return ScriptBuilder.iife(f"""
var _node = Scene.findNode({esc(node_name)});
if (!_node) return false;
var _old = _node.findDataItem({esc(DATA_ITEM_NAME)});
if (!_old) return false;
_node.removeDataItem(_old);
return true;""")


def write_manifest_script(m: Manifest) -> str:
    """Script writing the scene-level manifest (updated in place when present)."""
    esc = ScriptBuilder.escape_string
    name = esc(scene_item_name(m.recipe_id))
    return ScriptBuilder.iife(f"""
var _item = Scene.findDataItem({name});
if (!_item) {{
    _item = new DzSimpleSceneData({name}, true);
    Scene.addDataItem(_item);
}}
_item.getSettings().setStringValue({esc(_MANIFEST_KEY)}, {esc(m.to_json())});
return true;""")


def _read_script(recipe_id: str, environment_holder: str) -> str:
    esc = ScriptBuilder.escape_string
    return ScriptBuilder.iife(f"""
function _rec(n) {{
    var it = n.findDataItem({esc(DATA_ITEM_NAME)});
    return it ? it.getSettings().getStringValue({esc(_RECORD_KEY)}) : null;
}}
function _prop(n, label) {{
    var p = n.findPropertyByLabel(label);
    return p ? p.getValue() : null;
}}
function _tree(n) {{
    var kids = n.getNodeChildren(false), out = [];
    for (var k = 0; k < kids.length; k++)
        out.push({{name: kids[k].getName(), record: _rec(kids[k]),
                  bone: kids[k].inherits("DzBone"), children: _tree(kids[k])}});
    return out;
}}
var _out = {{manifest: null, environment: null, nodes: []}};
var _mi = Scene.findDataItem({esc(scene_item_name(recipe_id))});
if (_mi) _out.manifest = _mi.getSettings().getStringValue({esc(_MANIFEST_KEY)});
var _holder = {environment_holder};
if (_holder) {{
    var _p = function(name) {{ var q = _holder.findProperty(name); return q ? q.getValue() : null; }};
    var _map = _p("Environment Map");
    _out.environment = {{
        intensity: _p("Environment Intensity"), rotation_deg: _p("Dome Rotation"),
        mode: _p("Environment Mode"), draw_dome: _p("Draw Dome"),
        image_path: (_map && _map.getFilename) ? _map.getFilename() : _map
    }};
}}
var _nodes = Scene.getNodeList();
for (var _i = 0; _i < _nodes.length; _i++) {{
    var n = _nodes[_i];
    var record = _rec(n);
    if (!record) continue;
    var p = n.getWSPos();
    var info = {{
        name: n.getName(), record: record,
        element_id: (typeof n.getElementID === "function") ? n.getElementID() : null,
        is_camera: n.inherits("DzCamera"), is_light: n.inherits("DzLight"),
        position: [p.x, p.y, p.z],
        rotation: [n.getXRotControl().getValue(), n.getYRotControl().getValue(),
                   n.getZRotControl().getValue()],
        optics: null, output: null, children: []
    }};
    if (info.is_camera) {{
        info.optics = {{focal_length: n.focalLength,
                        depth_of_field: _prop(n, "Depth of Field"),
                        focal_distance: n.focalDistance}};
    }} else if (info.is_light) {{
        var c = n.getDiffuseColor();
        info.output = {{intensity: _prop(n, "Intensity"), color: [c.red, c.green, c.blue]}};
    }}
    info.children = _tree(n);
    _out.nodes.push(info);
}}
return _out;""")


# ── readback ──────────────────────────────────────────────────────────────────

def _owned_by(record_json: str | None, recipe_id: str) -> EntityRecord | None:
    if not record_json:
        return None
    try:
        rec = EntityRecord.from_json(record_json)
    except (ValueError, KeyError, TypeError):
        return None
    return rec if rec.recipe_id == recipe_id else None


_KIND_PREFIXES = (("actors.", "actor"), ("props.", "prop"), ("cameras.", "camera"),
                  ("lighting.lights.", "light"), ("lighting.rigs.", "light"))


def _kind_from_path(path: str) -> str | None:
    for prefix, kind in _KIND_PREFIXES:
        if path.startswith(prefix):
            return kind
    return None


def _foreign(children: list, recipe_id: str) -> list[str]:
    """Descendant names not owned by *recipe_id*.

    Bones are never candidates but are walked (items parented to a bone count).
    A descendant owned by this recipe is not foreign and owns its own subtree,
    so it is not descended into.
    """
    out: list[str] = []
    for c in children:
        if c.get("bone"):
            out += _foreign(c.get("children") or [], recipe_id)
        elif _owned_by(c.get("record"), recipe_id) is None:
            out.append(c["name"])
            out += _foreign(c.get("children") or [], recipe_id)
    return out


def read_live(client: "DazClient", recipe_id: str) -> LiveState:
    """Read every node owned by *recipe_id* in one script call.

    Plus one ``DazPose.capture`` per actor with a record.  Nodes whose record
    belongs to another recipe, or is unparseable, are ignored.
    """
    from ._pose import DazPose
    from ._skeleton import DazSkeleton

    holder = DazRenderSettings(client)._environment_holder()
    payload = client.execute(_read_script(recipe_id, holder)).value or {}

    manifest = None
    if payload.get("manifest"):
        try:
            manifest = Manifest.from_json(payload["manifest"])
        except (ValueError, KeyError, TypeError):
            manifest = None

    entities: dict[str, LiveEntity] = {}
    for n in payload.get("nodes") or []:
        rec = _owned_by(n.get("record"), recipe_id)
        if rec is None:
            continue
        kind = _kind_from_path(rec.path)
        if kind is None:
            continue
        observed: dict[str, dict] = {
            "transform": {"position": n["position"], "rotation": n["rotation"]}}
        if n.get("optics") is not None:
            observed["optics"] = n["optics"]
        if n.get("output") is not None:
            observed["output"] = n["output"]
        if kind == "actor":
            pose = DazPose.capture(DazSkeleton(client, NodeIdentifier(n["name"])))
            observed["pose"] = {"snapshot": pose.to_dict()}
        foreign = tuple(_foreign(n.get("children") or [], recipe_id))
        entities[rec.path] = LiveEntity(
            path=rec.path, node_name=n["name"], kind=kind, record=rec,
            observed=observed, foreign_children=foreign, element_id=n.get("element_id"))

    env = payload.get("environment") if manifest and manifest.environment else None
    return LiveState(manifest=manifest, entities=entities, environment_observed=env)
