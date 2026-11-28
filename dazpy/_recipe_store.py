"""Ownership records, manifest and live readback for scene recipes.

Every node a recipe creates carries a Daz element data item
(:data:`DATA_ITEM_NAME`) whose ``record`` setting is an :class:`EntityRecord`
JSON string: who owns the node, plus the last-applied (``desired``) and
last-observed (``observed``) channel values.  A scene-level data item
(``dazpy.scene_recipe.<recipe_id>``) holds the :class:`Manifest`.

This is the data-item backend.  Another backend only has to provide the same
three script builders and a ``read_live`` returning :class:`LiveState`.
Nodes the recipe created are addressed by Daz node name (``getName()``, made
unique when they were created).  Nodes it did not create (taken-over figures,
hand-loaded items) share names whenever a file is loaded twice, so they are
addressed by a *node ref* ``"elementID:<id>"`` (:func:`eid_ref`), the element ID
read from the scene; every recipe script resolves a ref by element ID
(:func:`find_node_js`), never by name (final review C1).

Observed-channel conventions (controller ruling): ``transform.position`` is
world (``getWSPos``); ``transform.rotation`` is the node's LOCAL X/Y/Z rotation
controls, i.e. what ``DazNode.set_rotation`` writes.  Recipe nodes are created
at scene root so the two coincide unless the user re-parents them.  The
environment ``mode`` is observed as the raw enum int and must be written back
with ``setValue(int)``.  Entity ``kind`` comes from the record's path prefix,
not the node class (a rigged prop is still a prop).

The observed ``pose`` snapshot excludes the figure node's own transform
properties (:data:`NODE_TRANSFORM_PROPS`): the node transform is the
``transform`` channel, so storing it twice would make every recipe move of an
actor look like a hand pose edit.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from collections.abc import Iterable
from typing import TYPE_CHECKING

from ._node import NodeIdentifier
from ._recipe_desired import EntityKind
from ._render import DazRenderSettings
from ._scene_state import _TRANSFORM_KEYS
from ._script_builder import ScriptBuilder
from .exceptions import DazError

if TYPE_CHECKING:
    from ._client import DazClient

DATA_ITEM_NAME = "dazpy.scene_recipe"
_RECORD_KEY = "record"
_MANIFEST_KEY = "manifest"


# Figure-node properties that are the node transform, not the pose.
NODE_TRANSFORM_PROPS: tuple[str, ...] = tuple(_TRANSFORM_KEYS)


def strip_node_transform(snapshot: dict) -> dict:
    """*snapshot* (a ``DazPose.to_dict()``) without the node-transform props."""
    out = dict(snapshot)
    out["props"] = {k: v for k, v in (snapshot.get("props") or {}).items()
                    if k not in NODE_TRANSFORM_PROPS}
    return out


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
    # Names of the non-bone descendants the asset loaded with (Genesis 9's eyes,
    # mouth, lashes...): part of the entity, never the user's foreign children.
    native: tuple[str, ...] = ()
    # Asset-ref provenance (spec section 9); omitted from JSON while at their defaults.
    source: dict | None = None
    group: str | None = None            # the record path when several nodes form one entity
    primary: bool = True                # the node a group is keyed on
    adopted_from_scene: bool = False
    members: tuple[str, ...] = ()       # every node name of the group as created, primary first
    # One-shot log on actor records: {"entry", "op", "removed": [{"label","type","source_path"}]}
    done: tuple[dict, ...] = ()
    # Fitted items: the node's getAssetUriForNode file part (its .dsf data file)
    # recorded at fit time, for source-change drift (spec 9, 15.2).
    asset_uri: str | None = None

    def to_json(self) -> str:
        d = asdict(self)
        for key, default in _RECORD_DEFAULTS.items():
            if d[key] == default or (key in ("done", "members") and not d[key]):
                del d[key]
        return json.dumps(d, sort_keys=True)

    @classmethod
    def from_json(cls, s: str) -> EntityRecord:
        d = json.loads(s)
        return cls(recipe_id=d["recipe_id"], path=d["path"],
                   recipe_version=int(d["recipe_version"]),
                   desired=d.get("desired") or {}, observed=d.get("observed") or {},
                   native=tuple(d.get("native") or ()),
                   source=d.get("source") or None, group=d.get("group") or None,
                   primary=bool(d.get("primary", True)),
                   adopted_from_scene=bool(d.get("adopted_from_scene", False)),
                   members=tuple(d.get("members") or ()),
                   done=tuple(d.get("done") or ()),
                   asset_uri=d.get("asset_uri") or None)


_RECORD_DEFAULTS: dict = {"source": None, "group": None, "primary": True,
                          "adopted_from_scene": False, "members": (), "done": (),
                          "asset_uri": None}


@dataclass(frozen=True)
class Manifest:
    """Every entity path a recipe owns (including ones whose node is gone).

    ``deleted`` lists paths whose hand deletion was accepted (``scene_wins`` or a
    ``"scene"`` resolution), so later applies don't recreate them.
    """

    recipe_id: str
    entities: tuple[str, ...]
    environment: EntityRecord | None
    deleted: tuple[str, ...] = ()

    def to_json(self) -> str:
        return json.dumps({
            "recipe_id": self.recipe_id,
            "entities": list(self.entities),
            "environment": json.loads(self.environment.to_json()) if self.environment else None,
            "deleted": list(self.deleted),
        }, sort_keys=True)

    @classmethod
    def from_json(cls, s: str) -> Manifest:
        d = json.loads(s)
        env = d.get("environment")
        return cls(recipe_id=d["recipe_id"], entities=tuple(d.get("entities") or ()),
                   environment=EntityRecord.from_json(json.dumps(env)) if env else None,
                   deleted=tuple(d.get("deleted") or ()))


@dataclass(frozen=True)
class LiveEntity:
    path: str
    node_name: str
    kind: EntityKind
    record: EntityRecord
    observed: dict[str, dict]
    foreign_children: tuple[str, ...]
    element_id: int | None = None
    label: str | None = None  # the node's current label (the user may have renamed it)
    group_nodes: tuple[str, ...] = ()  # surviving nodes of a group, primary first
    missing_members: tuple[str, ...] = ()  # recorded group members no longer in the scene
    # groups only: (member, its foreign children) for members that have any
    foreign_by_node: tuple[tuple[str, tuple[str, ...]], ...] = ()


@dataclass(frozen=True)
class DuplicateRecord:
    """Several nodes carry the same record path (e.g. a node duplicated in Studio).

    ``node_names`` / ``element_ids`` are in scene order; the first is the node
    :class:`LiveState` keys the :class:`LiveEntity` on.
    """

    path: str
    node_names: tuple[str, ...]
    element_ids: tuple[int | None, ...]


@dataclass(frozen=True)
class LiveState:
    manifest: Manifest | None
    entities: dict[str, LiveEntity]
    environment_observed: dict | None
    duplicates: tuple[DuplicateRecord, ...] = ()


# ── node refs ─────────────────────────────────────────────────────────────────

EID_PREFIX = "elementID:"

# The element ID of a node: getElementID() where it exists, else the numeric
# elementID property (DS4 has no getElementID(), spec 15.2); "" if neither.
_EID_OF_JS = ('((typeof {n}.getElementID === "function") ? String({n}.getElementID()) : '
              '(typeof {n}.elementID === "number" ? String({n}.elementID) : ""))')


def eid_ref(element_id: object) -> str | None:
    """The node ref for *element_id* (``"elementID:<id>"``), None when it is not
    a numeric id (e.g. a name that ``_key`` fell back to)."""
    text = str(element_id).strip() if element_id is not None else ""
    return f"{EID_PREFIX}{text}" if text.isdigit() else None


def is_eid_ref(ref: str) -> bool:
    return ref.startswith(EID_PREFIX) and ref[len(EID_PREFIX):].isdigit()


def node_ident(ref: str) -> NodeIdentifier:
    """The dazpy :class:`NodeIdentifier` for a node name or node ref."""
    if is_eid_ref(ref):
        return NodeIdentifier(ref[len(EID_PREFIX):], kind="element_id")
    return NodeIdentifier(ref)


def find_node_js(ref: str) -> str:
    """JS expression finding the node *ref* names: ``Scene.findNode(name)`` for a
    name (unchanged), a scan comparing element IDs for an ``elementID:`` ref."""
    if not is_eid_ref(ref):
        return f"Scene.findNode({ScriptBuilder.escape_string(ref)})"
    eid = ScriptBuilder.escape_string(ref[len(EID_PREFIX):])
    return ("(function(_id) { var _l = Scene.getNodeList(); "
            "for (var _q = 0; _q < _l.length; _q++) "
            f"if ({_EID_OF_JS.format(n='_l[_q]')} === _id) return _l[_q]; "
            f"return null; }})({eid})")


# JS ``_findRef(ref)``: find_node_js for refs held in a script variable.
FIND_REF_JS = f"""
function _findRef(_r) {{
    var _p = {ScriptBuilder.escape_string(EID_PREFIX)};
    if (_r.indexOf(_p) !== 0) return Scene.findNode(_r);
    var _id = _r.substring(_p.length), _l = Scene.getNodeList();
    for (var _q = 0; _q < _l.length; _q++)
        if ({_EID_OF_JS.format(n='_l[_q]')} === _id) return _l[_q];
    return null;
}}"""


# ── script builders ───────────────────────────────────────────────────────────

def write_record_script(node_name: str, record: EntityRecord) -> str:
    """Script attaching *record* to the node, replacing any existing record."""
    esc = ScriptBuilder.escape_string
    return ScriptBuilder.iife(f"""
var _node = {find_node_js(node_name)};
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
var _node = {find_node_js(node_name)};
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


# JS helpers shared by the full readback and the single-node / environment
# observe scripts, so both report channels with the same conventions.
_OBSERVE_JS = """
function _prop(n, label) {
    var p = n.findPropertyByLabel(label);
    return p ? p.getValue() : null;
}
function _observe(n) {
    var p = n.getWSPos();
    var info = {
        is_camera: n.inherits("DzCamera"), is_light: n.inherits("DzLight"),
        position: [p.x, p.y, p.z],
        rotation: [n.getXRotControl().getValue(), n.getYRotControl().getValue(),
                   n.getZRotControl().getValue()],
        optics: null, output: null
    };
    if (info.is_camera) {
        info.optics = {focal_length: n.focalLength,
                       depth_of_field: _prop(n, "Depth of Field"),
                       focal_distance: n.focalDistance};
    } else if (info.is_light) {
        var c = n.getDiffuseColor();
        info.output = {intensity: _prop(n, "Intensity"), color: [c.red, c.green, c.blue]};
    }
    return info;
}"""


def _environment_js(environment_holder: str) -> str:
    """JS function ``_environment()``: the Iray environment values, or null."""
    return f"""
function _environment() {{
    var _holder = {environment_holder};
    if (!_holder) return null;
    var _p = function(name) {{ var q = _holder.findProperty(name); return q ? q.getValue() : null; }};
    var _map = _p("Environment Map");
    return {{
        intensity: _p("Environment Intensity"), rotation_deg: _p("Dome Rotation"),
        mode: _p("Environment Mode"), draw_dome: _p("Draw Dome"),
        image_path: (_map && _map.getFilename) ? _map.getFilename() : _map
    }};
}}"""


def observe_node_script(node_name: str) -> str:
    """Script returning one node's observable channel values (null if missing)."""
    return ScriptBuilder.iife(f"""{_OBSERVE_JS}
var _n = {find_node_js(node_name)};
return _n ? _observe(_n) : null;""")


def observe_environment_script(environment_holder: str) -> str:
    """Script returning the scene's environment values (null without an Iray holder)."""
    return ScriptBuilder.iife(f"""{_environment_js(environment_holder)}
return _environment();""")


# JS: ``_rec(n)`` = the node's record JSON (or null); ``_tree(n)`` = its
# descendants as ``{name, record, bone, children}`` (the shape ``foreign_descendants`` walks).
_TREE_JS = f"""
function _rec(n) {{
    var it = n.findDataItem({ScriptBuilder.escape_string(DATA_ITEM_NAME)});
    return it ? it.getSettings().getStringValue({ScriptBuilder.escape_string(_RECORD_KEY)}) : null;
}}
function _tree(n) {{
    var kids = n.getNodeChildren(false), out = [];
    for (var k = 0; k < kids.length; k++)
        out.push({{name: kids[k].getName(), record: _rec(kids[k]),
                  bone: kids[k].inherits("DzBone"), children: _tree(kids[k])}});
    return out;
}}"""


def subtree_script(node_name: str) -> str:
    """Script returning ``{record, children}`` for the node: its own record JSON and
    its descendant tree (null if the node is missing)."""
    return ScriptBuilder.iife(f"""// recipe:subtree{_TREE_JS}
var _n = {find_node_js(node_name)};
return _n ? {{record: _rec(_n), children: _tree(_n)}} : null;""")


def _read_script(recipe_id: str, environment_holder: str) -> str:
    esc = ScriptBuilder.escape_string
    return ScriptBuilder.iife(f"""{_OBSERVE_JS}
{_environment_js(environment_holder)}
{_TREE_JS}
var _out = {{manifest: null, environment: _environment(), nodes: []}};
var _mi = Scene.findDataItem({esc(scene_item_name(recipe_id))});
if (_mi) _out.manifest = _mi.getSettings().getStringValue({esc(_MANIFEST_KEY)});
var _nodes = Scene.getNodeList();
for (var _i = 0; _i < _nodes.length; _i++) {{
    var n = _nodes[_i];
    var record = _rec(n);
    if (!record) continue;
    var info = _observe(n);
    info.name = n.getName();
    info.label = n.getLabel();
    info.record = record;
    info.element_id = (typeof n.getElementID === "function") ? n.getElementID() : null;
    info.key = {_EID_OF_JS.format(n="n")};
    info.children = _tree(n);
    _out.nodes.push(info);
}}
return _out;""")


def observed_channels(client: DazClient, node_name: str, kind: str, info: dict) -> dict[str, dict]:
    """Observed channels for one node from its ``_observe`` payload (+ pose capture for actors)."""
    from ._pose import DazPose
    from ._skeleton import DazSkeleton

    observed: dict[str, dict] = {
        "transform": {"position": info["position"], "rotation": info["rotation"]}}
    if info.get("optics") is not None:
        observed["optics"] = info["optics"]
    if info.get("output") is not None:
        observed["output"] = info["output"]
    if kind == "actor":
        pose = DazPose.capture(DazSkeleton(client, node_ident(node_name)))
        observed["pose"] = {"snapshot": strip_node_transform(pose.to_dict())}
    return observed


# ── readback ──────────────────────────────────────────────────────────────────

def owned_by(record_json: str | None, recipe_id: str) -> EntityRecord | None:
    if not record_json:
        return None
    try:
        rec = EntityRecord.from_json(record_json)
    except (ValueError, KeyError, TypeError):
        return None
    return rec if rec.recipe_id == recipe_id else None


_KIND_PREFIXES: tuple[tuple[str, EntityKind], ...] = (("actors.", "actor"), ("props.", "prop"), ("cameras.", "camera"),
                  ("lighting.lights.", "light"), ("lighting.rigs.", "light"))


def _kind_from_path(path: str) -> EntityKind | None:
    if path.startswith("actors.") and ".wearing." in path:
        return "item"  # a fitted item: no pose capture
    for prefix, kind in _KIND_PREFIXES:
        if path.startswith(prefix):
            return kind
    return None


def foreign_descendants(children: list, recipe_id: str,
                        native: Iterable[str] = ()) -> list[str]:
    """Descendant names not owned by *recipe_id*.

    Bones and *native* descendants (the ones the asset loaded with, see
    :attr:`EntityRecord.native`) are never candidates but are walked: an item
    parented to a bone or to a figure's eyes counts.  A descendant owned by this
    recipe is not foreign and owns its own subtree, so it is not descended into.
    """
    native = frozenset(native)
    out: list[str] = []
    for c in children:
        if c.get("bone") or c.get("name") in native:
            out += foreign_descendants(c.get("children") or [], recipe_id, native)
        elif owned_by(c.get("record"), recipe_id) is None:
            out.append(c["name"])
            out += foreign_descendants(c.get("children") or [], recipe_id, native)
    return out


def read_live(client: DazClient, recipe_id: str) -> LiveState:
    """Read every node owned by *recipe_id* in one script call.

    Plus one ``DazPose.capture`` per actor with a record.  Nodes whose record
    belongs to another recipe, or is unparseable, are ignored.  When several
    nodes carry the same record path, the entity is keyed on the first and the
    path is reported in ``LiveState.duplicates``.  Raises :class:`DazError`
    when the recipe's manifest exists but cannot be parsed (its tombstones
    would otherwise be silently lost).
    """
    holder = DazRenderSettings(client)._environment_holder()
    payload = client.execute(_read_script(recipe_id, holder)).value or {}

    manifest = None
    if payload.get("manifest"):
        try:
            manifest = Manifest.from_json(payload["manifest"])
        except (ValueError, KeyError, TypeError) as e:
            raise DazError(f"the scene's manifest for recipe {recipe_id!r} "
                           f"({scene_item_name(recipe_id)!r}) cannot be read ({e}); refusing to "
                           "plan without it, since accepted hand deletions would be lost") from e

    members: dict[str, list[tuple[dict, EntityRecord]]] = {}
    for n in payload.get("nodes") or []:
        rec = owned_by(n.get("record"), recipe_id)
        if rec is None:
            continue
        if _kind_from_path(rec.path) is None:
            continue
        members.setdefault(rec.path, []).append((n, rec))

    entities: dict[str, LiveEntity] = {}
    duplicates: list[DuplicateRecord] = []
    for path, found in members.items():
        kind = _kind_from_path(path)
        is_group = all(r.group == path for _, r in found)
        if is_group:  # primary first, otherwise scene order
            found = sorted(found, key=lambda m: not m[1].primary)
        n, rec = found[0]
        live_names = tuple(m["name"] for m, _ in found)
        # a taken-over figure was not named by the recipe: address it by element ID (C1)
        node_name = (eid_ref(n.get("key")) or n["name"]) if rec.adopted_from_scene else n["name"]
        observed = observed_channels(client, node_name, kind, n)
        # A group's foreign children are those of every member (one delete takes them all).
        by_node = tuple((m["name"], tuple(foreign_descendants(m.get("children") or [], recipe_id,
                                                              r.native)))
                        for m, r in (found if is_group else found[:1]))
        foreign = tuple(c for _, cs in by_node for c in cs)
        entities[path] = LiveEntity(
            path=path, node_name=node_name, kind=kind, record=rec,
            observed=observed, foreign_children=foreign, element_id=n.get("element_id"),
            label=n.get("label"),
            group_nodes=live_names if is_group else (),
            missing_members=(tuple(x for x in rec.members if x not in live_names)
                             if is_group else ()),
            foreign_by_node=tuple((n, cs) for n, cs in by_node if cs) if is_group else ())
        if len(found) > 1 and not is_group:
            duplicates.append(DuplicateRecord(
                path, tuple(m["name"] for m, _ in found),
                tuple(m.get("element_id") for m, _ in found)))
    env = payload.get("environment") if manifest and manifest.environment else None
    return LiveState(manifest=manifest, entities=entities, environment_observed=env,
                     duplicates=tuple(duplicates))
