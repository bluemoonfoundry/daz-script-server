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
  asset, figure made primary selection, ``ContentMgr.openFile(path, true)``;
  ``.json``: ``poses.apply_pose``; None = no-op; other extensions raise) or
  ``{"snapshot": DazPose.to_dict()}`` (``DazPose.apply_full``, keeping the
  figure's current node-transform props: snapshots do not carry them).

``set_environment`` takes the desired environment (``mode`` is a label, applied
through ``apply_hdri_environment``) or an observed one (``mode`` is the raw enum
int, written back with ``setValue(int)`` for rollback).
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Iterable, Protocol

from ._camera import DazCamera
from ._light import DazLight
from ._node import DazNode, NodeIdentifier
from ._pose import DazPose
from ._recipe_desired import DesiredEntity, EntityKind
from ._recipe_store import (NODE_TRANSFORM_PROPS, EntityRecord, Manifest, foreign_descendants,
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

    def set_environment(self, values: dict) -> None:
        """Write a desired- or observed-shaped environment."""

    def observe_environment(self) -> dict | None:
        """Read the scene environment (None when Studio exposes none)."""

    def unparent(self, owner_name: str, child_names: list[str]) -> None:
        """Move the named descendants of *owner_name* to scene root (world transform kept)."""

    def reparent(self, child_names: list[str], parent_name: str) -> None:
        """Move the nodes under *parent_name*, preserving world transform (undoes unparent)."""

    def delete(self, node_name: str, owner_recipe: str | None = None) -> None:
        """Remove the node from the scene.

        With *owner_recipe*, first verify that no descendant foreign to that
        recipe remains (raise instead of deleting a user's node).
        """

    def write_record(self, node_name: str, record: EntityRecord) -> None: ...

    def remove_record(self, node_name: str) -> None:
        """Remove the ownership record (release: the node stays, unowned)."""

    def write_manifest(self, manifest: Manifest) -> None: ...


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


def _cleanup_script(before: list[str]) -> str:
    """Remove every node whose key is not in *before*; return how many were removed."""
    return ScriptBuilder.iife(f"""// recipe:cleanup{_KEY_JS}
var _before = {{}}, _keys = {json.dumps(before)};
for (var _k = 0; _k < _keys.length; _k++) _before[_keys[_k]] = true;
var _nodes = Scene.getNodeList(), _new = [];
for (var _i = 0; _i < _nodes.length; _i++) if (!_before[_key(_nodes[_i])]) _new.push(_nodes[_i]);
var _removed = 0;
for (var _j = _new.length - 1; _j >= 0; _j--) if (Scene.removeNode(_new[_j])) _removed++;
return _removed;""")


def _pose_preset_script(node_name: str, path: str) -> str:
    """Select *node_name* as primary and merge-open the Daz pose preset at *path*."""
    esc = ScriptBuilder.escape_string
    return ScriptBuilder.iife(f"""
var _node = Scene.findNode({esc(node_name)});
if (!_node) return "node_not_found";
Scene.setPrimarySelection(_node);
return !!App.getContentMgr().openFile({esc(path)}, true);""")


_POSE_PRESET_EXTS = (".duf", ".dsf")
_POSE_JSON_EXTS = (".json",)


def _claim_script(before: list[str], label: str) -> str:
    """New root nodes since *before*: make their names unique, label the first."""
    esc = ScriptBuilder.escape_string
    return ScriptBuilder.iife(f"""// recipe:claim{_KEY_JS}
var _before = {{}}, _keys = {json.dumps(before)};
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
    if (_count(nm) > 1) {{
        var r = 1;
        while (Scene.findNode(nm + "_r" + r)) r++;
        _new[_m].setName(nm + "_r" + r);
    }}
    _names.push(_new[_m].getName());
}}
if (_new.length) _new[0].setLabel({esc(label)});
return _names;""")


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
var _paths = {json.dumps(paths)}, _out = {{}};
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


def resolve_files(client: "DazClient", paths: Iterable[str]) -> dict[str, str]:
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
    lookup.  A listed node under another listed node moves with it (the user's
    own hierarchy is kept).  Nothing moves unless every name is found.
    """
    owner = ScriptBuilder.escape_string(owner_name)
    return ScriptBuilder.iife(f"""// recipe:unparent{_KEY_JS}
var _owner = Scene.findNode({owner});
if (!_owner) return [{owner} + ": owner not found"];
var _names = {json.dumps(child_names)}, _all = _owner.getNodeChildren(true);
var _picked = {{}}, _nodes = [], _errs = [];
for (var _i = 0; _i < _names.length; _i++) {{
    var _n = null;
    for (var _j = 0; _j < _all.length; _j++)
        if (_all[_j].getName() === _names[_i] && !_picked[_key(_all[_j])]) {{ _n = _all[_j]; break; }}
    if (!_n) {{ _errs.push(_names[_i] + ": not found under " + {owner}); continue; }}
    _picked[_key(_n)] = true;
    _nodes.push(_n);
}}
if (_errs.length) return _errs;
var _ownerKey = _key(_owner);
for (var _k = 0; _k < _nodes.length; _k++) {{
    var _inner = false;
    for (var _p = _nodes[_k].getNodeParent(); _p && _key(_p) !== _ownerKey; _p = _p.getNodeParent())
        if (_picked[_key(_p)]) {{ _inner = true; break; }}
    if (_inner) continue;
    var _old = _nodes[_k].getNodeParent();
    if (_old) _old.removeNodeChild(_nodes[_k], true);
}}
return [];""")


def _reparent_script(child_names: list[str], parent_name: str) -> str:
    """Move root nodes named *child_names* under *parent_name* (undoes ``_unparent_script``).

    A name not at scene root is fine when it sits under one of the moved
    nodes (it went along with that ancestor).
    """
    parent = ScriptBuilder.escape_string(parent_name)
    return ScriptBuilder.iife(f"""// recipe:reparent
var _parent = Scene.findNode({parent});
if (!_parent) return [{parent} + ": parent not found"];
var _names = {json.dumps(child_names)}, _nodes = Scene.getNodeList(), _roots = {{}}, _errs = [];
for (var _i = 0; _i < _nodes.length; _i++) {{
    var _nm = _nodes[_i].getName();
    if (!_nodes[_i].getNodeParent() && _names.indexOf(_nm) >= 0 && !_roots[_nm]) _roots[_nm] = _nodes[_i];
}}
for (var _j = 0; _j < _names.length; _j++) {{
    if (_roots[_names[_j]]) continue;
    var _inside = false;
    for (var _r in _roots) {{
        var _kids = _roots[_r].getNodeChildren(true);
        for (var _k = 0; _k < _kids.length; _k++) if (_kids[_k].getName() === _names[_j]) _inside = true;
    }}
    if (!_inside) _errs.push(_names[_j] + ": not found at scene root");
}}
for (var _m in _roots) _parent.addNodeChild(_roots[_m], true);
return _errs;""")


class DazSceneOps:
    """:class:`SceneOps` backed by dazpy primitives on *scene*."""

    def __init__(self, scene: "DazScene") -> None:
        self._scene = scene
        self._client = scene._client

    # ── create / delete ───────────────────────────────────────────────────────

    def create(self, entity: DesiredEntity) -> list[str]:
        if entity.kind in ("actor", "prop"):
            path = self._resolve_asset(entity.create["asset_path"])
            make = lambda: self._scene.load(path)  # noqa: E731
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
        if not names:
            err = DazError(f"{entity.path}: creating it added no root node to the scene; "
                           "every node it added was removed")
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
            tree = self._client.execute(subtree_script(node_name)).value
            if tree is None:
                raise NodeNotFoundError(f"Cannot delete, node not found: {node_name!r}")
            foreign = foreign_descendants(tree, owner_recipe)
            if foreign:
                raise DazError(f"Refusing to delete {node_name!r}: it still has descendants the "
                               f"recipe does not own ({', '.join(foreign)})")
        if not DazNode(self._client, NodeIdentifier(node_name)).delete():
            raise DazError(f"Could not delete node {node_name!r} (not found or not removed)")

    def unparent(self, owner_name: str, child_names: list[str]) -> None:
        self._check_moved("unparent", _unparent_script(owner_name, list(child_names)))

    def reparent(self, child_names: list[str], parent_name: str) -> None:
        self._check_moved("reparent", _reparent_script(list(child_names), parent_name))

    def _check_moved(self, what: str, script: str) -> None:
        errors = self._client.execute(script).value
        if errors:
            raise DazError(f"{what} failed: {'; '.join(map(str, errors))}")

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
                skeleton = DazSkeleton(self._client, ident)
                if "snapshot" in value:
                    self._apply_snapshot(skeleton, value["snapshot"])
                elif value.get("pose_path") is not None:
                    self._apply_pose_path(node_name, skeleton, value["pose_path"])
            else:
                raise DazError(f"{node_name}: unknown channel {name!r}")

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
            result = self._client.execute(_pose_preset_script(node_name, resolved)).value
            if result == "node_not_found":
                raise NodeNotFoundError(f"Cannot apply pose preset, node not found: {node_name!r}")
            if result is not True:
                raise DazError(f"Daz Studio failed to open pose preset {resolved!r} on {node_name!r}")
        else:
            raise DazError(f"Unsupported pose file {path!r}; supported: Daz pose presets "
                           f"({', '.join(_POSE_PRESET_EXTS)}) or dazpy pose JSON "
                           f"({', '.join(_POSE_JSON_EXTS)})")

    def _set_transform(self, ident: NodeIdentifier, kind: EntityKind, t: dict) -> None:
        node = DazCamera(self._client, ident) if kind == "camera" else DazNode(self._client, ident)
        node.set_position(*t["position"])
        if kind == "camera" and t.get("aim") is not None:
            node.aim_at(*t["aim"])
        elif t.get("rotation") is not None:
            node.set_rotation(*t["rotation"])

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

    def write_manifest(self, manifest: Manifest) -> None:
        self._client.execute(write_manifest_script(manifest))
