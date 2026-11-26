"""SceneOps: the scene mutations a recipe apply needs, and the dazpy-backed adapter.

:class:`SceneOps` is the seam between the executor (``_recipe_apply``) and DAZ
Studio, so the executor and its rollback can be tested against a fake.
:class:`DazSceneOps` implements it with dazpy primitives.

File paths (assets, pose presets, HDRI maps) are resolved Studio-side by the
one shared :func:`resolve_files`; only dazpy pose JSON files are read, and
checked, client-side.  ``create`` supports single-root assets only (v1): a load
adding several root nodes is removed again and raises.

Channel shapes accepted by ``set_channels`` (desired and observed alike):

- ``transform``: ``{position, rotation}`` (set_position + set_rotation), or a
  camera's desired ``{position, aim, rotation}`` (set_position, then
  ``aim_at`` when ``aim`` is set, else set_rotation);
- ``optics``: ``{focal_length, depth_of_field, focal_distance}`` (None skipped);
- ``output``: ``{intensity, color}``;
Channels are written pose first, so a pose preset's root transform never
overrides the recipe's ``transform``.

- ``pose``: ``{"pose_path": p}`` (``.duf``/``.dsf`` Daz preset: resolved like an
  asset, figure made primary selection, ``ContentMgr.openFile(path, true)``,
  previous primary selection restored;
  ``.json``: ``poses.apply_pose``; None = no-op; other extensions raise) or
  ``{"snapshot": DazPose.to_dict()}`` (``DazPose.apply_full``, keeping the
  figure's current node-transform props: snapshots do not carry them).

``set_environment`` takes the desired environment (``mode`` is a label, applied
through ``apply_hdri_environment``) or an observed one (``mode`` is the raw enum
int, written back with ``setValue(int)`` for rollback).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Protocol
from collections.abc import Callable, Iterable

from ._camera import DazCamera
from ._light import DazLight
from ._node import DazNode, NodeIdentifier
from ._pose import DazPose
from ._recipe_desired import DesiredEntity, EntityKind
from ._recipe_store import (NODE_TRANSFORM_PROPS, EntityRecord, Manifest, owned_by,
                            foreign_descendants,
                            observe_environment_script, observe_node_script, observed_channels,
                            remove_record_script, subtree_script, write_manifest_script,
                            write_record_script)
from ._render import DazRenderSettings
from ._script_builder import ScriptBuilder
from ._skeleton import DazSkeleton
from .exceptions import DazError, NodeNotFoundError
from .lighting import HDRIEnvironment, apply_hdri_environment
from .poses import apply_pose

if TYPE_CHECKING:
    from ._client import DazClient
    from ._scene import DazScene


class SceneOps(Protocol):
    def create(self, entity: DesiredEntity) -> list[str]:
        """Create *entity*'s node(s); return their names, the owned root first."""

    def set_channels(self, node_name: str, kind: EntityKind, channels: dict[str, dict]) -> None:
        """Write desired- or observed-shaped channel values to the node."""

    def observe(self, node_name: str, kind: EntityKind) -> dict[str, dict]:
        """Read the node's observed channels (the shapes ``read_live`` reports)."""

    def native_descendants(self, node_name: str) -> tuple[str, ...]:
        """Names of the node's non-bone descendants (called right after create, so
        everything below a fresh node came with its asset)."""

    def set_environment(self, values: dict) -> None:
        """Write a desired- or observed-shaped environment."""

    def observe_environment(self) -> dict | None:
        """Read the scene environment (None when Studio exposes none)."""

    def unparent(self, owner_name: str, child_names: list[str]) -> list[str]:
        """Move the named descendants of *owner_name* to scene root (world transform kept).

        Returns the keys of the nodes it moved, for :meth:`reparent`.  Raises,
        having moved nothing, when a name is not found under the owner.
        """

    def reparent(self, child_keys: list[str], parent_name: str) -> None:
        """Move the root nodes with *child_keys* under *parent_name*, preserving
        world transform (undoes unparent)."""

    def delete(self, node_name: str, owner_recipe: str | None = None) -> None:
        """Remove the node from the scene.

        With *owner_recipe*, first verify that no descendant foreign to that
        recipe remains (raise instead of deleting a user's node).
        """

    def write_record(self, node_name: str, record: EntityRecord) -> None: ...

    def remove_record(self, node_name: str) -> None:
        """Remove the ownership record (release: the node stays, unowned)."""

    def relabel(self, node_name: str, from_label: str, to_label: str) -> None:
        """Set the node's label to *to_label* if it is still *from_label* (else no-op)."""

    def write_manifest(self, manifest: Manifest) -> None: ...

    def take_over(self, node_name: str) -> None:
        """Validate that *node_name* exists; changes nothing in the scene."""

    def apply_presets(self, node_name: str, paths: list[str]) -> None:
        """Apply Daz pose/preset files to the figure, in order (it is the sole
        primary selection while each opens; the prior selection is restored)."""

    def fit(self, entity: DesiredEntity, figure_name: str) -> list[str]:
        """Load ``entity.create["asset_path"]`` and fit every node it adds to the
        figure; return all added root names, the primary first.  Raises, with
        everything it added removed, when an added root cannot be fitted."""

    def unfit(self, node_names: list[str]) -> None:
        """Delete the named nodes (and their subtrees) in one exact-selection delete."""

    def restore(self, source_paths: list[str], figure_name: str) -> list[str]:
        """Reload each source file and fit it to the figure (undoes a removal);
        return the new root names."""


# HTTP timeout for a call that opens a content file (asset merge-load, pose
# preset).  The client default (30s) is too short for the first load after
# Studio starts: on DS4 a Genesis 9 load takes ~15s warm but 19-32s cold, and a
# timeout there rolls the whole apply back (y33z).
ASSET_LOAD_TIMEOUT_S = 300.0

# Node keys: element ID when the API exposes it (survives duplicate names),
# else the node name.
_KEY_JS = """
function _key(n) {
    return (typeof n.getElementID === "function") ? String(n.getElementID()) : n.getName();
}"""

# Keys of every node in the scene (not just roots), so a create can find and,
# on failure, remove everything it added.
_SNAPSHOT_SCRIPT = ScriptBuilder.iife(f"""// recipe:snapshot{_KEY_JS}
var _nodes = Scene.getNodeList(), _out = [];
for (var _i = 0; _i < _nodes.length; _i++) _out.push(_key(_nodes[_i]));
return _out;""")


def _load_asset_script(path: str) -> str:
    """Merge-load *path* with nothing selected.

    Loading a figure while another figure is selected makes Studio pop a modal
    "replace the selected figure or add a new one" dialog, which blocks the main
    thread (and the server) until someone clicks it.  The previous selection is
    not restored: a recipe apply rewrites the scene anyway.
    """
    return ScriptBuilder.iife(f"""// recipe:load
Scene.selectAllNodes(false);
Scene.loadScene({ScriptBuilder.escape_string(path)}, DzScene.MergeFile);
return true;""")


# Nodes are removed with Studio's own "Delete Selected Item(s)" action on an
# exact selection, never Scene.removeNode: on DS4, Scene.removeNode on a Genesis 9
# figure hangs Studio while unfollowing its eyebrow cards (the action does not).
# The action removes each selected node's whole subtree.
_DELETE_SELECTED_JS = """
function _deleteSelected(_nodes) {
    var _a = MainWindow.getActionMgr().findAction("DzDeleteAction");
    if (!_a) throw new Error("Daz Studio's DzDeleteAction is not available");
    Scene.selectAllNodes(false);
    for (var _s = 0; _s < _nodes.length; _s++) _nodes[_s].select(true);
    if (!_nodes.length) return 0;
    Scene.setPrimarySelection(_nodes[0]);
    var _n0 = Scene.getNumNodes();
    _a.trigger();
    return _n0 - Scene.getNumNodes();
}"""


def _delete_script(node_name: str) -> str:
    """Delete *node_name* and its subtree; true when a node of that name went away."""
    name = ScriptBuilder.escape_string(node_name)
    return ScriptBuilder.iife(f"""// recipe:delete{_DELETE_SELECTED_JS}
function _count() {{
    var _l = Scene.getNodeList(), _c = 0;
    for (var _i = 0; _i < _l.length; _i++) if (_l[_i].getName() === {name}) _c++;
    return _c;
}}
var _n = Scene.findNode({name});
if (!_n) return false;
var _was = _count();
_deleteSelected([_n]);
return _count() < _was;""")


def _cleanup_script(before: list[str]) -> str:
    """Remove every node whose key is not in *before*; return how many were removed."""
    return ScriptBuilder.iife(f"""// recipe:cleanup{_KEY_JS}{_DELETE_SELECTED_JS}
var _before = {{}}, _keys = {ScriptBuilder.to_js(before)};
for (var _k = 0; _k < _keys.length; _k++) _before[_keys[_k]] = true;
var _nodes = Scene.getNodeList(), _tops = [];
for (var _i = 0; _i < _nodes.length; _i++) {{
    var _n = _nodes[_i], _p = _n.getNodeParent();
    // the top of each added subtree: new, under nothing or under a pre-existing node
    if (!_before[_key(_n)] && (!_p || _before[_key(_p)])) _tops.push(_n);
}}
return _deleteSelected(_tops);""")


def _pose_preset_script(node_name: str, path: str) -> str:
    """Select *node_name* as primary, merge-open the Daz pose preset at *path*,
    then restore the previous primary selection (or deselect the figure)."""
    esc = ScriptBuilder.escape_string
    return ScriptBuilder.iife(f"""
var _node = Scene.findNode({esc(node_name)});
if (!_node) return "node_not_found";
var _prev = Scene.getPrimarySelection();
Scene.setPrimarySelection(_node);
try {{
    return !!App.getContentMgr().openFile({esc(path)}, true);
}} finally {{
    if (_prev) Scene.setPrimarySelection(_prev);
    else _node.select(false);
}}""")


# The figure node's own transform controls (DzNode.get<X>Control()).
_NODE_XFORM_CONTROLS = ("XPos", "YPos", "ZPos", "XRot", "YRot", "ZRot",
                        "XScale", "YScale", "ZScale", "Scale")


def _read_node_xform_script(node_name: str) -> str:
    """``{control: value}`` for the node's ten transform controls, or null."""
    return ScriptBuilder.iife(f"""// recipe:read-xform
var _node = Scene.findNode({ScriptBuilder.escape_string(node_name)});
if (!_node) return null;
var _c = {ScriptBuilder.to_js(list(_NODE_XFORM_CONTROLS))}, _out = {{}};
for (var _i = 0; _i < _c.length; _i++) _out[_c[_i]] = _node["get" + _c[_i] + "Control"]().getValue();
return _out;""")


def _write_node_xform_script(node_name: str, values: dict) -> str:
    """Set the node's transform controls from ``{control: value}``; false if no node."""
    return ScriptBuilder.iife(f"""// recipe:write-xform
var _node = Scene.findNode({ScriptBuilder.escape_string(node_name)});
if (!_node) return false;
// An array, not for-in over an object: Studio 6's script engine enumerates
// inherits/className/deleteLater/name on plain objects too.
var _v = {ScriptBuilder.to_js([[c, values[c]] for c in _NODE_XFORM_CONTROLS if c in values])};
for (var _i = 0; _i < _v.length; _i++) _node["get" + _v[_i][0] + "Control"]().setValue(_v[_i][1]);
return true;""")


_POSE_PRESET_EXTS = (".duf", ".dsf")
_POSE_JSON_EXTS = (".json",)


def _check_pose_ext(path: str) -> None:
    """DazError unless *path* is a Daz pose preset or a dazpy pose JSON file."""
    if os.path.splitext(path)[1].lower() not in _POSE_PRESET_EXTS + _POSE_JSON_EXTS:
        raise DazError(f"Unsupported pose file {path!r}; supported: Daz pose presets "
                       f"({', '.join(_POSE_PRESET_EXTS)}) or dazpy pose JSON "
                       f"({', '.join(_POSE_JSON_EXTS)})")


def _claim_script(before: list[str], label: str | None) -> str:
    """New root nodes since *before*: make their names unique, label the first
    (no label change when *label* is None)."""
    esc = ScriptBuilder.escape_string
    fallback = label if label is not None else "node"
    set_label = f"if (_new.length) _new[0].setLabel({esc(label)});" if label is not None else ""
    return ScriptBuilder.iife(f"""// recipe:claim{_KEY_JS}
var _before = {{}}, _keys = {ScriptBuilder.to_js(before)};
for (var _k = 0; _k < _keys.length; _k++) _before[_keys[_k]] = true;
var _nodes = Scene.getNodeList(), _new = [];
for (var _i = 0; _i < _nodes.length; _i++) {{
    var n = _nodes[_i];
    if (!n.getNodeParent() && !_before[_key(n)]) _new.push(n);
}}
function _count(name) {{
    var c = 0;
    for (var j = 0; j < _nodes.length; j++) if (_nodes[j].getName() === name) c++;
    return c;
}}
var _names = [];
for (var _m = 0; _m < _new.length; _m++) {{
    var nm = _new[_m].getName();
    if (!nm) {{
        // DS4 gives a new camera/light a label but no name; later steps find nodes by name.
        nm = {esc(fallback)}.replace(/[^A-Za-z0-9_]/g, "_");
        _new[_m].setName(nm);
        _nodes = Scene.getNodeList();
    }}
    if (_count(nm) > 1) {{
        var r = 1;
        while (Scene.findNode(nm + "_r" + r)) r++;
        _new[_m].setName(nm + "_r" + r);
    }}
    _names.push(_new[_m].getName());
}}
{set_label}
return _names;""")


# Provisional until the Task 1 live probe confirms these calls.
def _fit_script(names: list[str], figure_name: str) -> str:
    """Fit each named scene-root node that is a figure to *figure_name*: follow
    it and parent it under it.  Returns ``{error, fitted, unfitted}``.

    Added non-figure roots (a prop in an outfit preset) stay unfitted.
    """
    esc = ScriptBuilder.escape_string
    return ScriptBuilder.iife(f"""// recipe:fit
var _fig = Scene.findNode({esc(figure_name)});
if (!_fig) return {{error: {esc(figure_name)} + ": figure not found", fitted: [], unfitted: []}};
var _names = {ScriptBuilder.to_js(names)}, _fitted = [], _unfitted = [];
for (var _i = 0; _i < _names.length; _i++) {{
    var _n = Scene.findNode(_names[_i]);
    if (_n && _n.inherits("DzFigure")) {{
        _n.setFollowTarget(_fig);
        _fig.addNodeChild(_n, true);
        _fitted.push(_names[_i]);
    }} else _unfitted.push(_names[_i]);
}}
return {{error: "", fitted: _fitted, unfitted: _unfitted}};""")


def _unfit_script(names: list[str]) -> str:
    """Delete the named nodes with one exact-selection DzDeleteAction; returns the missing names."""
    return ScriptBuilder.iife(f"""// recipe:unfit{_DELETE_SELECTED_JS}
var _names = {ScriptBuilder.to_js(names)}, _nodes = [], _missing = [];
for (var _i = 0; _i < _names.length; _i++) {{
    var _n = Scene.findNode(_names[_i]);
    if (_n) _nodes.push(_n); else _missing.push(_names[_i]);
}}
if (!_missing.length) _deleteSelected(_nodes);
return _missing;""")


def _exists_script(node_name: str) -> str:
    return ScriptBuilder.iife(f"""// recipe:exists
return !!Scene.findNode({ScriptBuilder.escape_string(node_name)});""")


def is_local_pose_file(path: str) -> bool:
    """True for a dazpy pose JSON file, read client-side by ``poses.apply_pose``."""
    return os.path.splitext(path)[1].lower() in _POSE_JSON_EXTS


def resolve_script(paths: list[str]) -> str:
    """One script mapping every path to its absolute file, or ``""`` (never opens a file).

    A leading ``/`` is a content path: ``findFile`` over every content directory
    (two-argument form, then the one-argument form), falling back to
    ``DzFileInfo`` because it may also be a macOS absolute path.  Any other
    path must be an existing absolute file (``DzFileInfo``).
    """
    return ScriptBuilder.iife(f"""// recipe:resolve
var _paths = {ScriptBuilder.to_js(paths)}, _out = {{}};
var _cm = App.getContentMgr();
function _resolve(_p) {{
    if (_p.charAt(0) === "/") {{
        var _f = "";
        try {{ _f = _cm.findFile(_p, DzContentMgr.AllDirs); }} catch (e) {{ _f = ""; }}
        if (!_f) _f = _cm.findFile(_p);
        if (_f) return String(_f);
    }}
    return new DzFileInfo(_p).exists() ? _p : "";
}}
for (var _i = 0; _i < _paths.length; _i++) _out[_paths[_i]] = _resolve(_paths[_i]);
return _out;""")


def resolve_files(client: DazClient, paths: Iterable[str]) -> dict[str, str]:
    """``{path: absolute file or ""}`` for Studio-side files, in one script call.

    The one resolver ``validate`` and :class:`DazSceneOps` share.  Paths are
    never checked with ``os.path``: they live on the Studio host.  (dazpy pose
    JSON files are the exception, see :func:`is_local_pose_file`; callers check
    those client-side.)  Raises :class:`DazError` when Studio returns no result.
    """
    unique = sorted(set(paths))
    if not unique:
        return {}
    found = client.execute(resolve_script(unique)).value
    if not isinstance(found, dict):
        raise DazError("Daz Studio returned no result for the file-existence check "
                       f"({len(unique)} file(s)); nothing was reported missing")
    return {p: str(found.get(p) or "") for p in unique}


def _unparent_script(owner_name: str, child_names: list[str]) -> str:
    """Move the named descendants of *owner_name* to scene root, keeping world transform.

    Children are found in the owner's subtree, never by a scene-wide name
    lookup, and never match a bone.  A listed node under another listed node
    moves with it (the user's own hierarchy is kept).  Nothing moves unless
    every name is found.  Returns ``{errors, moved}``: the keys of the nodes
    actually moved to root, which ``_reparent_script`` takes back.
    """
    owner = ScriptBuilder.escape_string(owner_name)
    return ScriptBuilder.iife(f"""// recipe:unparent{_KEY_JS}
var _owner = Scene.findNode({owner});
if (!_owner) return {{errors: [{owner} + ": owner not found"], moved: []}};
var _names = {ScriptBuilder.to_js(child_names)}, _all = _owner.getNodeChildren(true);
var _picked = {{}}, _nodes = [], _errs = [];
for (var _i = 0; _i < _names.length; _i++) {{
    var _n = null;
    for (var _j = 0; _j < _all.length; _j++)
        if (_all[_j].getName() === _names[_i] && !_all[_j].inherits("DzBone")
                && !_picked[_key(_all[_j])]) {{ _n = _all[_j]; break; }}
    if (!_n) {{ _errs.push(_names[_i] + ": not found under " + {owner}); continue; }}
    _picked[_key(_n)] = true;
    _nodes.push(_n);
}}
if (_errs.length) return {{errors: _errs, moved: []}};
var _ownerKey = _key(_owner), _moved = [];
for (var _k = 0; _k < _nodes.length; _k++) {{
    var _inner = false;
    for (var _p = _nodes[_k].getNodeParent(); _p && _key(_p) !== _ownerKey; _p = _p.getNodeParent())
        if (_picked[_key(_p)]) {{ _inner = true; break; }}
    if (_inner) continue;
    var _old = _nodes[_k].getNodeParent();
    if (_old) {{ _old.removeNodeChild(_nodes[_k], true); _moved.push(_key(_nodes[_k])); }}
}}
return {{errors: [], moved: _moved}};""")


def _reparent_script(child_keys: list[str], parent_name: str) -> str:
    """Move the root nodes with *child_keys* under *parent_name* (undoes ``_unparent_script``).

    Nodes are found by the keys ``_unparent_script`` returned, never by name,
    so a same-named root node elsewhere in the scene is never picked up.
    """
    parent = ScriptBuilder.escape_string(parent_name)
    return ScriptBuilder.iife(f"""// recipe:reparent{_KEY_JS}
var _parent = Scene.findNode({parent});
if (!_parent) return [{parent} + ": parent not found"];
var _keys = {ScriptBuilder.to_js(child_keys)}, _nodes = Scene.getNodeList(), _found = {{}}, _errs = [];
for (var _i = 0; _i < _nodes.length; _i++) {{
    var _k = _key(_nodes[_i]);
    if (!_nodes[_i].getNodeParent() && _keys.indexOf(_k) >= 0 && !_found[_k]) _found[_k] = _nodes[_i];
}}
for (var _j = 0; _j < _keys.length; _j++)
    if (!_found[_keys[_j]]) _errs.push(_keys[_j] + ": moved node not found at scene root");
for (var _m in _found) if (_found.hasOwnProperty(_m)) _parent.addNodeChild(_found[_m], true);
return _errs;""")


def _relabel_script(node_name: str, from_label: str, to_label: str) -> str:
    """Relabel the node only while its label is still *from_label*; false if no node."""
    esc = ScriptBuilder.escape_string
    return ScriptBuilder.iife(f"""// recipe:relabel
var _node = Scene.findNode({esc(node_name)});
if (!_node) return false;
if (_node.getLabel() === {esc(from_label)}) _node.setLabel({esc(to_label)});
return true;""")


class DazSceneOps:
    """:class:`SceneOps` backed by dazpy primitives on *scene*."""

    def __init__(self, scene: DazScene) -> None:
        self._scene = scene
        self._client = scene._client

    # ── create / delete ───────────────────────────────────────────────────────

    def create(self, entity: DesiredEntity) -> list[str]:
        make: Callable[[], object]
        if entity.kind in ("actor", "prop"):
            path = self._resolve_asset(entity.create["asset_path"])
            make = lambda: self._client.execute(  # noqa: E731
                _load_asset_script(path), timeout=ASSET_LOAD_TIMEOUT_S)
        elif entity.kind == "camera":
            make = self._scene.create_camera
        elif entity.kind == "light":
            make = lambda: self._scene.create_light(entity.create["light_type"])  # noqa: E731
        else:
            raise DazError(f"{entity.path}: kind {entity.kind!r} has no node to create")
        before = self._client.execute(_SNAPSHOT_SCRIPT).value or []
        # Anything failing after the snapshot (a load that times out after adding
        # nodes, the label/rename claim) removes whatever was added, then re-raises.
        try:
            make()
            names = self._client.execute(_claim_script(before, entity.label)).value or []
        except Exception as e:
            self._remove_added(before, entity.path, e)
            raise
        if not names or not all(names):
            what = "added no root node to the scene" if not names else "left a root node with no name"
            err = DazError(f"{entity.path}: creating it {what}; every node it added was removed")
            self._remove_added(before, entity.path, err)
            raise err
        if len(names) > 1:
            source = entity.create.get("asset_path") or entity.path
            err = DazError(f"asset {source} loads {len(names)} root nodes; scene recipes v1 "
                           "support single-root assets (every node it added was removed)")
            self._remove_added(before, entity.path, err)
            raise err
        return list(names)

    def _remove_added(self, before: list[str], path: str, cause: Exception) -> None:
        """Remove every node added since *before* (a create that cannot be owned)."""
        try:
            self._client.execute(_cleanup_script(before))
        except Exception as e:
            raise DazError(f"{path}: create failed ({cause}) and removing the nodes it added "
                           f"also failed: {e}") from cause

    def _resolve_asset(self, path: str) -> str:
        """Absolute file path for *path* on the Studio host; DazError when missing (never opens it)."""
        found = resolve_files(self._client, [path])[path]
        if found:
            return found
        where = "in any content directory" if path.startswith("/") else "on the Daz Studio host"
        raise DazError(f"Asset not found {where}: {path}")

    def delete(self, node_name: str, owner_recipe: str | None = None) -> None:
        if owner_recipe is not None:
            sub = self._client.execute(subtree_script(node_name)).value
            if sub is None:
                raise NodeNotFoundError(f"Cannot delete, node not found: {node_name!r}")
            own = owned_by(sub.get("record"), owner_recipe)
            foreign = foreign_descendants(sub.get("children") or [], owner_recipe,
                                          own.native if own else ())
            if foreign:
                raise DazError(f"Refusing to delete {node_name!r}: it still has descendants the "
                               f"recipe does not own ({', '.join(foreign)})")
        if not self._client.execute(_delete_script(node_name)).value:
            raise DazError(f"Could not delete node {node_name!r} (not found or not removed)")

    def unparent(self, owner_name: str, child_names: list[str]) -> list[str]:
        out = self._client.execute(_unparent_script(owner_name, list(child_names))).value
        if not isinstance(out, dict):
            raise DazError(f"unparent failed: Daz Studio returned no result for {owner_name!r}")
        if out.get("errors"):
            raise DazError(f"unparent failed: {'; '.join(map(str, out['errors']))}")
        return [str(k) for k in out.get("moved") or []]

    def reparent(self, child_keys: list[str], parent_name: str) -> None:
        errors = self._client.execute(_reparent_script(list(child_keys), parent_name)).value
        if errors:
            raise DazError(f"reparent failed: {'; '.join(map(str, errors))}")

    # ── channels ──────────────────────────────────────────────────────────────

    def set_channels(self, node_name: str, kind: EntityKind, channels: dict[str, dict]) -> None:
        ident = NodeIdentifier(node_name)
        # Pose first: a pose preset can carry a root transform, which the
        # recipe's transform must then override.
        for name in sorted(channels, key=lambda ch: ch != "pose"):
            value = channels[name]
            if name == "transform":
                self._set_transform(ident, kind, value)
            elif name == "optics":
                cam = DazCamera(self._client, ident)
                if value.get("focal_length") is not None:
                    cam.focal_length = value["focal_length"]
                if value.get("depth_of_field") is not None:
                    cam.depth_of_field = value["depth_of_field"]
                if value.get("focal_distance") is not None:
                    cam.focal_distance = value["focal_distance"]
            elif name == "output":
                light = DazLight(self._client, ident)
                if value.get("intensity") is not None:
                    light.intensity = value["intensity"]
                if value.get("color") is not None:
                    light.set_color(*value["color"])
            elif name == "pose":
                self._apply_pose(node_name, ident, value)
            else:
                raise DazError(f"{node_name}: unknown channel {name!r}")

    def _apply_pose(self, node_name: str, ident: NodeIdentifier, value: dict) -> None:
        """Apply a pose channel without moving the figure node.

        The ``transform`` channel owns the node transform. Pose presets often
        carry one too (prop-interaction poses place the figure), so the node's
        own transform controls are read before the pose and written back
        after it; a changed ``transform`` channel is applied after this.
        """
        path = value.get("pose_path") if "snapshot" not in value else None
        if "snapshot" not in value and path is None:
            return
        if path is not None:
            _check_pose_ext(path)   # before any Studio round trip
        saved = self._client.execute(_read_node_xform_script(node_name)).value
        if saved is None:
            raise NodeNotFoundError(f"Cannot apply pose, node not found: {node_name!r}")
        skeleton = DazSkeleton(self._client, ident)
        if path is None:
            self._apply_snapshot(skeleton, value["snapshot"])
        else:
            self._apply_pose_path(node_name, skeleton, path)
        if self._client.execute(_write_node_xform_script(node_name, saved)).value is not True:
            raise NodeNotFoundError(f"Node disappeared while posing: {node_name!r}")

    @staticmethod
    def _apply_snapshot(skeleton: DazSkeleton, s: dict) -> None:
        """``apply_full`` *s*, keeping the figure's current node transform.

        Snapshots exclude the node-transform props (the ``transform`` channel
        owns them) and ``apply_full`` zeroes every prop it is not given, so the
        current values are read back and passed through unchanged.
        """
        current = DazPose.capture(skeleton)
        props = {k: v for k, v in s["props"].items() if k not in NODE_TRANSFORM_PROPS}
        props.update({k: v for k, v in current.props.items() if k in NODE_TRANSFORM_PROPS})
        DazPose(figure=s["figure"], bones=s["bones"], morphs=s["morphs"],
                props=props).apply_full(skeleton)

    def _apply_pose_path(self, node_name: str, skeleton: DazSkeleton, path: str) -> None:
        ext = os.path.splitext(path)[1].lower()
        if ext in _POSE_JSON_EXTS:
            apply_pose(skeleton, path)
        elif ext in _POSE_PRESET_EXTS:
            resolved = self._resolve_asset(path)
            result = self._client.execute(_pose_preset_script(node_name, resolved),
                                          timeout=ASSET_LOAD_TIMEOUT_S).value
            if result == "node_not_found":
                raise NodeNotFoundError(f"Cannot apply pose preset, node not found: {node_name!r}")
            if result is not True:
                raise DazError(f"Daz Studio failed to open pose preset {resolved!r} on {node_name!r}")
        else:
            _check_pose_ext(path)

    def _set_transform(self, ident: NodeIdentifier, kind: EntityKind, t: dict) -> None:
        node = DazCamera(self._client, ident) if kind == "camera" else DazNode(self._client, ident)
        if "position" in t:
            node.set_position(*t["position"])
        if isinstance(node, DazCamera) and t.get("aim") is not None:
            node.aim_at(*t["aim"])
        elif t.get("rotation") is not None:
            node.set_rotation(*t["rotation"])

    def native_descendants(self, node_name: str) -> tuple[str, ...]:
        sub = self._client.execute(subtree_script(node_name)).value
        if sub is None:
            raise NodeNotFoundError(f"Node not found: {node_name!r}")
        # Nothing below a fresh node is owned by anyone: every non-bone name.
        return tuple(foreign_descendants(sub.get("children") or [], ""))

    def observe(self, node_name: str, kind: EntityKind) -> dict[str, dict]:
        info = self._client.execute(observe_node_script(node_name)).value
        if not info:
            raise NodeNotFoundError(f"Node not found: {node_name!r}")
        return observed_channels(self._client, node_name, kind, info)

    # ── environment ───────────────────────────────────────────────────────────

    def set_environment(self, values: dict) -> None:
        rs = DazRenderSettings(self._client)
        if isinstance(values.get("mode"), str):
            apply_hdri_environment(rs, HDRIEnvironment(
                image_path=values["image_path"], intensity=values["intensity"],
                rotation_deg=values["rotation_deg"], mode=values["mode"],
                draw_dome=values["draw_dome"]))
            return
        # Observed shape (rollback): raw values, mode as the enum int.
        if values.get("image_path"):
            rs._set_environment_map(values["image_path"])
        for prop, key in (("Environment Intensity", "intensity"), ("Dome Rotation", "rotation_deg"),
                          ("Environment Mode", "mode"), ("Draw Dome", "draw_dome")):
            if values.get(key) is not None:
                rs._set_environment_property(prop, values[key])
        if not values.get("image_path"):
            # Clearing a map is never attempted: setMap-style calls can raise a
            # modal dialog and hang Studio.  Report it instead (-> rollback_errors).
            raise DazError("environment map could not be restored: the scene had no map before")

    def observe_environment(self) -> dict | None:
        holder = DazRenderSettings(self._client)._environment_holder()
        return self._client.execute(observe_environment_script(holder)).value

    # ── records ───────────────────────────────────────────────────────────────

    def write_record(self, node_name: str, record: EntityRecord) -> None:
        if self._client.execute(write_record_script(node_name, record)).value is False:
            raise NodeNotFoundError(f"Cannot write ownership record, node not found: {node_name!r}")

    def remove_record(self, node_name: str) -> None:
        if self._client.execute(remove_record_script(node_name)).value is False:
            raise DazError(f"Cannot release {node_name!r}: node or ownership record not found")

    def relabel(self, node_name: str, from_label: str, to_label: str) -> None:
        if self._client.execute(_relabel_script(node_name, from_label, to_label)).value is False:
            raise NodeNotFoundError(f"Cannot relabel, node not found: {node_name!r}")

    def write_manifest(self, manifest: Manifest) -> None:
        self._client.execute(write_manifest_script(manifest))

    # ── take over, presets, fitting ───────────────────────────────────────────

    def take_over(self, node_name: str) -> None:
        if not self._client.execute(_exists_script(node_name)).value:
            raise NodeNotFoundError(f"Cannot take over, node not found: {node_name!r}")

    def apply_presets(self, node_name: str, paths: list[str]) -> None:
        for path in paths:
            resolved = self._resolve_asset(path)
            result = self._client.execute(_pose_preset_script(node_name, resolved),
                                          timeout=ASSET_LOAD_TIMEOUT_S).value
            if result == "node_not_found":
                raise NodeNotFoundError(f"Cannot apply preset, node not found: {node_name!r}")
            if result is not True:
                raise DazError(f"Daz Studio failed to open preset {resolved!r} on {node_name!r}")

    def fit(self, entity: DesiredEntity, figure_name: str) -> list[str]:
        return self._load_and_fit(entity.create["asset_path"], entity.label, figure_name,
                                  entity.path)

    def restore(self, source_paths: list[str], figure_name: str) -> list[str]:
        names: list[str] = []
        for path in source_paths:
            names += self._load_and_fit(path, None, figure_name, path)
        return names

    def unfit(self, node_names: list[str]) -> None:
        missing = self._client.execute(_unfit_script(list(node_names))).value
        if missing:
            raise DazError(f"Cannot remove, node(s) not found: {', '.join(map(str, missing))}")

    def _load_and_fit(self, asset_path: str, label: str | None, figure_name: str,
                      where: str) -> list[str]:
        """Load with nothing selected, then fit every added root to the figure.

        Anything not fitted (or any failure after the snapshot) removes all
        the nodes the load added.
        """
        path = self._resolve_asset(asset_path)
        before = self._client.execute(_SNAPSHOT_SCRIPT).value or []
        try:
            self._client.execute(_load_asset_script(path), timeout=ASSET_LOAD_TIMEOUT_S)
            names = self._client.execute(_claim_script(before, label)).value or []
            if not names or not all(names):
                raise DazError(f"{where}: loading it added no named root node to the scene; "
                               "every node it added was removed")
            out = self._client.execute(_fit_script(list(names), figure_name)).value
            if not isinstance(out, dict):
                raise DazError(f"{where}: Daz Studio returned no result for the fit; "
                               "every node it added was removed")
            if out.get("error"):
                raise DazError(f"{where}: {out['error']}; every node it added was removed")
            stray = [n for n in names if n not in (out.get("fitted") or [])]
            if stray:
                raise DazError(f"{asset_path}: loading it added nodes that are not fitted to "
                               f"{figure_name}: {', '.join(stray)}; every node it added was removed")
        except Exception as e:
            self._remove_added(before, where, e)
            raise
        return list(names)
