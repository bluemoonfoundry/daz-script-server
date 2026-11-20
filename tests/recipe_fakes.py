"""Shared fakes for scene-recipe tests (not a test module).

``fake_client`` returns a mock DazClient whose ``execute`` answers the live
readback script from canned nodes/manifest and the ``DazPose.capture`` script
from canned poses.  Build the canned data with ``rec``, ``man`` and ``node``.
"""

from __future__ import annotations

import copy as _copy
import dataclasses as _dc
import json
from unittest.mock import MagicMock

from dazpy._recipe_desired import DesiredEntity
from dazpy._recipe_store import EntityRecord, LiveEntity, LiveState, Manifest
from dazpy._result import ExecutionResult


def rec(recipe_id: str, path: str, desired: dict | None = None, observed: dict | None = None,
        recipe_version: int = 1) -> EntityRecord:
    """An EntityRecord with empty channels unless given."""
    return EntityRecord(recipe_id, path, recipe_version, desired or {}, observed or {})


def man(recipe_id: str, entities: list[str], environment: EntityRecord | None = None) -> Manifest:
    """A Manifest listing *entities* (paths)."""
    return Manifest(recipe_id, tuple(entities), environment)


def node(name: str, record: EntityRecord | None, *, kind: str = "prop", label: str | None = None,
         element_id: int = 1, position=(0.0, 0.0, 0.0), rotation=(0.0, 0.0, 0.0),
         optics: dict | None = None, output: dict | None = None,
         children: list[dict] | None = None, bone: bool = False,
         camera: bool = False, light: bool = False) -> dict:
    """One canned node as the readback script reports it.

    ``kind`` is ignored by the reader (derived from the record path); ``bone``
    marks a DzBone child.  ``children`` are other ``node(...)`` results (record may be None = foreign).
    A node with ``record=None`` is only meaningful as a child.
    """
    return {
        "name": name, "label": label or name, "element_id": element_id,
        "record": record.to_json() if record else None, "kind": kind,
        "position": list(position), "rotation": list(rotation),
        "optics": optics, "output": output,
        "is_camera": camera, "is_light": light, "bone": bone,
        "children": [{"name": c["name"], "record": c["record"], "bone": c["bone"],
                      "children": c["children"]} for c in children or []],
    }


def fake_client(nodes: list[dict] | None = None, manifest: Manifest | None = None,
                environment: dict | None = None, pose: dict | None = None) -> MagicMock:
    """A mock client for ``read_live``.

    Top-level nodes with ``record=None`` are dropped, like the real script
    (only recorded nodes are reported).  Scripts are recorded in
    ``client.execute.call_args_list``.
    """
    payload = {
        "manifest": manifest.to_json() if manifest else None,
        "environment": environment,
        "nodes": [n for n in nodes or [] if n["record"]],
    }
    pose_payload = pose or {"bones": {}, "morphs": {}, "props": {}}

    def execute(script, *a, **kw):
        return ExecutionResult(value=pose_payload if "getAllBones" in script else payload)

    client = MagicMock()
    client.execute.side_effect = execute
    return client


# ── pure-diff helpers (Task 6; reused by later tasks) ────────────────────────

RID = "r1"
ENV_PATH = "lighting.environment"
_EMPTY_POSE = {"figure": "Genesis 9", "bones": {}, "morphs": {}, "props": {}}


def d_actor(name: str, position=(0.0, 0.0, 0.0), rotation=(0.0, 0.0, 0.0),
            pose_path: str | None = None) -> DesiredEntity:
    return DesiredEntity(f"actors.{name}", "actor", f"{RID}:{name}", {"asset_path": "/g9.duf"},
                         {"transform": {"position": tuple(position), "rotation": tuple(rotation)},
                          "pose": {"pose_path": pose_path}})


def d_prop(name: str, position=(0.0, 0.0, 0.0), rotation=(0.0, 0.0, 0.0)) -> DesiredEntity:
    return DesiredEntity(f"props.{name}", "prop", f"{RID}:{name}", {"asset_path": "/ball.duf"},
                         {"transform": {"position": tuple(position), "rotation": tuple(rotation)}})


def d_camera(name: str, position=(0.0, 150.0, 300.0), aim=(0.0, 150.0, 0.0),
             focal_length: float = 65.0) -> DesiredEntity:
    return DesiredEntity(f"cameras.{name}", "camera", f"{RID}:{name}", {},
                         {"transform": {"position": tuple(position), "aim": tuple(aim), "rotation": None},
                          "optics": {"focal_length": float(focal_length), "depth_of_field": False,
                                     "focal_distance": None}})


def d_light(name: str, position=(100.0, 200.0, 100.0), rotation=(-30.0, 45.0, 0.0),
            intensity: float = 1.0, color=(255, 255, 255)) -> DesiredEntity:
    return DesiredEntity(f"lighting.lights.{name}", "light", f"{RID}:{name}", {"light_type": "spot"},
                         {"transform": {"position": tuple(position), "rotation": tuple(rotation)},
                          "output": {"intensity": float(intensity), "color": tuple(color)}})


def d_environment(intensity: float = 1.0, rotation_deg: float = 0.0, mode: str = "dome_and_scene",
                  image_path: str | None = "/hdri/sky.hdr", draw_dome: bool = True) -> DesiredEntity:
    return DesiredEntity(ENV_PATH, "environment", f"{RID}:environment", {},
                         {"environment": {"type": "hdri", "image_path": image_path,
                                          "intensity": float(intensity),
                                          "rotation_deg": float(rotation_deg), "mode": mode,
                                          "draw_dome": bool(draw_dome)}})


def ds(*entities: DesiredEntity) -> dict:
    """A desired-state dict (as compute_desired returns) from DesiredEntity values."""
    return {e.path: e for e in entities}


def observed_for(e: DesiredEntity) -> dict:
    """What readback would report right after a faithful apply of *e*."""
    ch = e.channels
    out: dict = {}
    if "transform" in ch:
        rot = ch["transform"].get("rotation")
        out["transform"] = {"position": list(ch["transform"]["position"]),
                            "rotation": list(rot) if rot is not None else [0.0, 0.0, 0.0]}
    if "optics" in ch:
        out["optics"] = dict(ch["optics"])
    if "output" in ch:
        out["output"] = {"intensity": ch["output"]["intensity"], "color": list(ch["output"]["color"])}
    if "pose" in ch:
        out["pose"] = {"snapshot": _copy.deepcopy(_EMPTY_POSE)}
    if "environment" in ch:
        env = ch["environment"]
        out["environment"] = {"intensity": env["intensity"], "rotation_deg": env["rotation_deg"],
                              "mode": 0, "draw_dome": env["draw_dome"], "image_path": env["image_path"]}
    return out


def live_matching(D: dict, *, deleted: tuple = ()) -> LiveState:
    """LiveState as if *D* was applied and nothing has changed since."""
    entities: dict = {}
    env_rec = None
    env_obs = None
    for path, e in D.items():
        obs = observed_for(e)
        rdesired = _copy.deepcopy(e.channels)
        if e.kind != "environment":
            rdesired["_create"] = _copy.deepcopy(e.create)  # executor's record contract
        r = rec(RID, path, rdesired, _copy.deepcopy(obs))
        if e.kind == "environment":
            env_rec, env_obs = r, _copy.deepcopy(obs["environment"])
            continue
        entities[path] = LiveEntity(path=path, node_name=e.label, kind=e.kind, record=r,
                                    observed=_copy.deepcopy(obs), foreign_children=())
    paths = [p for p in D if p != ENV_PATH]
    return LiveState(manifest=Manifest(RID, tuple(paths), env_rec, tuple(deleted)),
                     entities=entities, environment_observed=env_obs)


def tweak_value(channel: str, value: dict) -> dict:
    """*value* (an observed channel) with an unmistakable hand edit applied."""
    v = _copy.deepcopy(value)
    if channel == "transform":
        v["position"][0] += 25.0
    elif channel == "pose":
        v["snapshot"]["bones"]["rForeArm"] = [0.0, 0.0, -45.0]
    elif channel == "optics":
        v["focal_length"] += 20.0
    elif channel == "output":
        v["intensity"] += 0.5
    elif channel == "environment":
        v["intensity"] += 1.0
    else:
        raise ValueError(channel)
    return v


def with_observed(live: LiveState, path: str, channel: str, value) -> LiveState:
    """*live* with entity *path*'s observed *channel* replaced by *value*."""
    if path == ENV_PATH:
        return LiveState(live.manifest, live.entities, value)
    ents = dict(live.entities)
    e = ents[path]
    obs = _copy.deepcopy(e.observed)
    obs[channel] = value
    ents[path] = LiveEntity(e.path, e.node_name, e.kind, e.record, obs, e.foreign_children,
                            e.element_id)
    return LiveState(live.manifest, ents, live.environment_observed)


def live_tweaked(D: dict, path: str, channel: str, *, live: LiveState | None = None) -> LiveState:
    """``live_matching(D)`` (or *live*) with one hand edit on *path*.*channel*."""
    live = live or live_matching(D)
    current = (live.environment_observed if path == ENV_PATH
               else live.entities[path].observed[channel])
    return with_observed(live, path, channel, tweak_value(channel, current))


def live_without(live: LiveState, path: str) -> LiveState:
    """*live* with entity *path*'s node deleted by hand (still in the manifest)."""
    ents = {p: e for p, e in live.entities.items() if p != path}
    return LiveState(live.manifest, ents, live.environment_observed)


def live_with_children(D: dict, path: str = "actors.anna", names=("Shirt",),
                       *, live: LiveState | None = None) -> LiveState:
    """``live_matching(D)`` (or *live*) where the user parented *names* under *path*."""
    live = live or live_matching(D)
    ents = dict(live.entities)
    e = ents[path]
    ents[path] = LiveEntity(e.path, e.node_name, e.kind, e.record, e.observed, tuple(names),
                            e.element_id)
    return LiveState(live.manifest, ents, live.environment_observed)


def live_with_duplicate(live: LiveState, path: str, copy_name: str = "copy", copy_id: int = 2
                        ) -> LiveState:
    """*live* where a second node (e.g. a Studio duplicate) carries *path*'s record."""
    from dazpy._recipe_store import DuplicateRecord
    e = live.entities[path]
    dup = DuplicateRecord(path, (e.node_name, copy_name), (e.element_id, copy_id))
    return LiveState(live.manifest, live.entities, live.environment_observed, (dup,))


# ── executor fakes (Task 7) ──────────────────────────────────────────────────

def labelled(L: LiveState, path: str, label: str) -> LiveState:
    """*L* with the node at *path* reporting *label* as its current label."""
    ents = dict(L.entities)
    ents[path] = _dc.replace(ents[path], label=label)
    return _dc.replace(L, entities=ents)


class FakeOps:
    """A SceneOps that records every call and fails on chosen calls.

    ``fail_on`` is ``(method, n)`` or a list of them: the *n*-th call (1-based,
    counting calls made during rollback too) of *method* raises *exc*
    (default ``RuntimeError``).  ``calls`` holds ``(method, first arg)`` (just
    ``(method,)`` for argument-less calls); ``calls_with_args`` holds every
    argument, deep-copied.  ``create`` returns ``create_names[path]`` (default
    ``[entity.label]``); ``observe`` returns ``observed[node]`` (default
    :data:`FAKE_OBSERVED`); ``observe_environment`` returns *environment*;
    ``native_descendants`` returns ``native[node]`` (default ``()``);
    ``unparent`` returns ``moved[owner]`` (default: the child names, as keys).
    """

    def __init__(self, fail_on=None, exc: Exception | None = None, *,
                 create_names: dict | None = None, observed: dict | None = None,
                 environment: dict | None = None, native: dict | None = None,
                 moved: dict | None = None) -> None:
        if fail_on is None:
            fail_on = []
        elif isinstance(fail_on, tuple):
            fail_on = [fail_on]
        self.fail_on = list(fail_on)
        self.exc = exc
        self.create_names = create_names or {}
        self.observed = observed or {}
        self.environment = environment
        self.native = native or {}
        self.moved = moved or {}
        self.calls: list[tuple] = []
        self.calls_with_args: list[tuple] = []
        self._counts: dict[str, int] = {}

    def _call(self, method: str, *args):
        self._counts[method] = self._counts.get(method, 0) + 1
        self.calls.append((method, args[0]) if args else (method,))
        self.calls_with_args.append((method, *_copy.deepcopy(args)))
        if (method, self._counts[method]) in self.fail_on:
            raise self.exc if self.exc is not None else RuntimeError(f"{method} failed")

    def methods(self) -> list[str]:
        return [c[0] for c in self.calls]

    def create(self, entity):
        self._call("create", entity.path)
        return list(self.create_names.get(entity.path, [entity.label]))

    def set_channels(self, node_name, kind, channels):
        self._call("set_channels", node_name, kind, channels)

    def observe(self, node_name, kind):
        self._call("observe", node_name, kind)
        return _copy.deepcopy(self.observed.get(node_name, FAKE_OBSERVED))

    def native_descendants(self, node_name):
        self._call("native_descendants", node_name)
        return tuple(self.native.get(node_name, ()))

    def set_environment(self, values):
        self._call("set_environment", values)

    def observe_environment(self):
        self._call("observe_environment")
        return _copy.deepcopy(self.environment)

    def unparent(self, owner_name, child_names):
        self._call("unparent", owner_name, child_names)
        return list(self.moved.get(owner_name, child_names))

    def reparent(self, child_names, parent_name):
        self._call("reparent", child_names, parent_name)

    def delete(self, node_name, owner_recipe=None):
        # calls_with_args carries owner_recipe only when given (checked deletes)
        self._call("delete", *((node_name,) if owner_recipe is None else (node_name, owner_recipe)))

    def write_record(self, node_name, record):
        self._call("write_record", node_name, record)

    def remove_record(self, node_name):
        self._call("remove_record", node_name)

    def relabel(self, node_name, from_label, to_label):
        self._call("relabel", node_name, from_label, to_label)

    def write_manifest(self, manifest):
        self._call("write_manifest", manifest)


FAKE_OBSERVED = {"transform": {"position": [1.0, 2.0, 3.0], "rotation": [0.0, 0.0, 0.0]}}


def scripted_client(*responses) -> MagicMock:
    """A mock DazClient answering scripts by substring.

    *responses* are ``(substring, value)`` pairs; the first whose substring is
    in the script wins (``value`` may be a callable taking the script).
    Unmatched scripts return ``None``, except the node-transform read/write
    around a pose (``recipe:read-xform`` / ``recipe:write-xform``), which
    succeed by default.  Scripts land in ``client.scripts``.
    """
    client = MagicMock()
    client.scripts = []
    defaults = (("recipe:read-xform", {"XPos": 0.0}), ("recipe:write-xform", True))

    def execute(script, *a, **kw):
        client.scripts.append(script)
        for sub, value in tuple(responses) + defaults:
            if sub in script:
                return ExecutionResult(value=value(script) if callable(value) else value)
        return ExecutionResult(value=None)

    client.execute.side_effect = execute
    return client


# ── facade fakes (Task 8) ────────────────────────────────────────────────────

def empty_live() -> LiveState:
    """A scene the recipe has never been applied to."""
    return LiveState(manifest=None, entities={}, environment_observed=None)


class FakeScene:
    """Stands in for a ``DazScene`` in facade tests.

    ``_client`` answers the batched file-resolve script (every path exists
    except *missing_files*) and records scripts in ``_client.scripts``.  Facade
    tests patch ``dazpy.recipe.read_live`` / ``DazSceneOps`` with
    :func:`patch_facade`, so ``live`` is what the facade reads and ``ops`` (a
    :class:`FakeOps`) is what it writes through.
    """

    def __init__(self, live: LiveState, missing_files=(), ops: "FakeOps | None" = None) -> None:
        self.live = live
        self.ops = ops or FakeOps()
        self.missing = set(missing_files)
        self._client = scripted_client(("recipe:resolve", self._resolve))
        self._client.scene = self

    def _resolve(self, script: str) -> dict:
        import re
        paths = json.loads(re.search(r"var _paths = (\[.*?\]),", script).group(1))
        return {p: ("" if p in self.missing else p) for p in paths}

    def tweak(self, path: str, channel: str) -> None:
        """Hand-edit *path*'s observed *channel* in the live state."""
        self.live = live_tweaked(None, path, channel, live=self.live)


def fake_scene(live: LiveState | None = None, *, missing_files=(),
               ops: "FakeOps | None" = None) -> FakeScene:
    return FakeScene(live if live is not None else empty_live(), missing_files, ops)


def patch_facade(test) -> None:
    """Route ``dazpy.recipe`` reads/writes to the FakeScene's ``live``/``ops`` for *test*."""
    from unittest.mock import patch
    for target, repl in (("dazpy.recipe.read_live", lambda client, rid: client.scene.live),
                         ("dazpy.recipe.DazSceneOps", lambda scene: scene.ops)):
        p = patch(target, side_effect=repl)
        p.start()
        test.addCleanup(p.stop)


# ── simulated Studio (final fix wave) ────────────────────────────────────────

_SIM_TRANSFORM_PROPS = ("XTranslate", "YTranslate", "ZTranslate", "XRotate", "YRotate", "ZRotate")
_SIM_NAMES = {"actor": "Genesis 9", "prop": "Prop", "camera": "Camera", "light": "Light"}


def sim_pose_bones(path: str) -> dict:
    """The bone rotations the simulated pose file *path* 'contains' (deterministic)."""
    n = float(sum(map(ord, path)) % 40 + 5)
    return {"lForeArm": [0.0, 0.0, n], "rShin": [n / 2, 0.0, 0.0]}


class SimStudio:
    """A tiny in-memory DAZ Studio for end-to-end facade round trips.

    It is both the ``scene`` passed to the facade (``_client``) and the
    :class:`SceneOps` the facade writes through (patch ``DazSceneOps`` with
    :func:`patch_sim`).  Records and manifests are stored as the real JSON
    strings, and ``_client`` answers the real ``read_live`` script and the real
    ``DazPose.capture`` script, so a test exercises store -> record JSON ->
    read_live parse -> diff exactly as against Studio.  A figure's capture
    reports its node transform as XTranslate/.../Scale props, like Studio.
    """

    def __init__(self, missing_files=(), asset_parts=()) -> None:
        # asset_parts: suffixes of the child nodes every created actor loads with
        # (Genesis 9's eyes, mouth...), named "<root><suffix>".
        self.asset_parts = tuple(asset_parts)
        self.nodes: dict[str, dict] = {}
        self.items: dict[str, str] = {}
        self.environment: dict | None = None
        self.missing = set(missing_files)
        self.fail_on: tuple | None = None
        self._next_id = 100
        self._counts: dict[str, int] = {}
        self._client = MagicMock()
        self._client.execute.side_effect = self._execute

    # ── helpers for tests ────────────────────────────────────────────────────

    def by_label(self, label: str) -> dict:
        hits = [n for n in self.nodes.values() if n["label"] == label]
        assert len(hits) == 1, (label, [n["name"] for n in hits])
        return hits[0]

    def add_node(self, name: str, *, parent: str | None = None, label: str | None = None,
                 record: str | None = None, kind: str = "prop") -> dict:
        self._next_id += 1
        n = {"name": name, "label": label or name, "kind": kind, "element_id": self._next_id,
             "position": [0.0, 0.0, 0.0], "rotation": [0.0, 0.0, 0.0], "bones": {}, "morphs": {},
             "props": {}, "optics": None, "output": None, "record": record, "parent": parent}
        if kind == "camera":
            n["optics"] = {"focal_length": 50.0, "depth_of_field": False, "focal_distance": 300.0}
        if kind == "light":
            n["output"] = {"intensity": 1.0, "color": [255, 255, 255]}
        self.nodes[name] = n
        return n

    def _unique(self, base: str) -> str:
        name, i = base, 2
        while name in self.nodes:
            name, i = f"{base} {i}", i + 1
        return name

    def _maybe_fail(self, method: str) -> None:
        self._counts[method] = self._counts.get(method, 0) + 1
        if self.fail_on == (method, self._counts[method]):
            raise RuntimeError(f"{method} failed")

    def _children(self, name: str) -> list[dict]:
        return [n for n in self.nodes.values() if n["parent"] == name]

    def _capture_props(self, n: dict) -> dict:
        raw = dict(zip(_SIM_TRANSFORM_PROPS, list(n["position"]) + list(n["rotation"])))
        raw["Scale"] = 1.0
        raw.update(n["props"])
        return {k: v for k, v in raw.items() if abs(v) > 0.0001}

    def _info(self, n: dict) -> dict:
        return {"is_camera": n["kind"] == "camera", "is_light": n["kind"] == "light",
                "position": list(n["position"]), "rotation": list(n["rotation"]),
                "optics": _copy.deepcopy(n["optics"]), "output": _copy.deepcopy(n["output"])}

    def _tree(self, name: str) -> list[dict]:
        return [{"name": c["name"], "record": c["record"], "bone": False,
                 "children": self._tree(c["name"])} for c in self._children(name)]

    # ── the client ───────────────────────────────────────────────────────────

    def _execute(self, script, *a, **kw):
        import re
        if "recipe:resolve" in script:
            paths = json.loads(re.search(r"var _paths = (\[.*?\]),", script).group(1))
            return ExecutionResult(value={p: ("" if p in self.missing else p) for p in paths})
        if "getAllBones" in script:
            name = json.loads(re.search(r'getName\(\) === (".*?")\)', script).group(1))
            n = self.nodes.get(name)
            if n is None:
                return ExecutionResult(value=None)
            return ExecutionResult(value={"bones": _copy.deepcopy(n["bones"]),
                                          "morphs": _copy.deepcopy(n["morphs"]),
                                          "props": self._capture_props(n)})
        if "_tree(" in script and "Scene.getNodeList()" in script:
            manifest = next((v for k, v in self.items.items() if json.dumps(k) in script), None)
            nodes = []
            for n in self.nodes.values():
                if not n["record"]:
                    continue
                info = self._info(n)
                info.update(name=n["name"], label=n["label"], record=n["record"],
                            element_id=n["element_id"], children=self._tree(n["name"]))
                nodes.append(info)
            return ExecutionResult(value={"manifest": manifest, "environment": self.environment,
                                          "nodes": nodes})
        return ExecutionResult(value=None)

    # ── SceneOps ─────────────────────────────────────────────────────────────

    def create(self, entity):
        self._maybe_fail("create")
        n = self.add_node(self._unique(_SIM_NAMES[entity.kind]), label=entity.label,
                          kind=entity.kind)
        if entity.kind == "actor":
            for part in self.asset_parts:
                self.add_node(n["name"] + part, parent=n["name"])
        return [n["name"]]

    def set_channels(self, node_name, kind, channels):
        self._maybe_fail("set_channels")
        n = self.nodes[node_name]
        for name in sorted(channels, key=lambda c: c != "pose"):
            v = channels[name]
            if name == "transform":
                n["position"] = [float(x) for x in v["position"]]
                if v.get("aim") is not None:
                    n["rotation"] = [0.0, 0.0, 0.0]
                elif v.get("rotation") is not None:
                    n["rotation"] = [float(x) for x in v["rotation"]]
            elif name == "optics":
                n["optics"].update({k: x for k, x in v.items() if x is not None})
            elif name == "output":
                n["output"].update({k: (list(x) if k == "color" else x) for k, x in v.items()
                                    if x is not None})
            elif name == "pose":
                if "snapshot" in v:
                    s = v["snapshot"]
                    n["bones"], n["morphs"] = _copy.deepcopy(s["bones"]), _copy.deepcopy(s["morphs"])
                    n["props"] = {k: x for k, x in s["props"].items()
                                  if k not in _SIM_TRANSFORM_PROPS + ("Scale",)}
                elif v.get("pose_path") is not None:
                    n["bones"] = sim_pose_bones(v["pose_path"])

    def observe(self, node_name, kind):
        from dazpy._recipe_store import observed_channels
        return observed_channels(self._client, node_name, kind, self._info(self.nodes[node_name]))

    def native_descendants(self, node_name):
        from dazpy._recipe_store import foreign_descendants
        return tuple(foreign_descendants(self._tree(node_name), ""))

    def set_environment(self, values):
        self._maybe_fail("set_environment")
        self.environment = {"intensity": values["intensity"], "rotation_deg": values["rotation_deg"],
                            "mode": 0 if isinstance(values["mode"], str) else values["mode"],
                            "draw_dome": values["draw_dome"], "image_path": values["image_path"]}

    def observe_environment(self):
        return _copy.deepcopy(self.environment)

    def unparent(self, owner_name, child_names):
        self._maybe_fail("unparent")
        for name in child_names:
            self.nodes[name]["parent"] = None
        return list(child_names)  # keys: the sim's node names

    def reparent(self, child_names, parent_name):
        for name in child_names:
            self.nodes[name]["parent"] = parent_name

    def delete(self, node_name, *a, **kw):
        self._maybe_fail("delete")
        for c in self._children(node_name):
            self.delete(c["name"])
        del self.nodes[node_name]

    def write_record(self, node_name, record):
        self._maybe_fail("write_record")
        self.nodes[node_name]["record"] = record.to_json()

    def remove_record(self, node_name):
        self._maybe_fail("remove_record")
        self.nodes[node_name]["record"] = None

    def relabel(self, node_name, from_label, to_label):
        if self.nodes[node_name]["label"] == from_label:
            self.nodes[node_name]["label"] = to_label

    def write_manifest(self, manifest):
        from dazpy._recipe_store import scene_item_name
        self._maybe_fail("write_manifest")
        self.items[scene_item_name(manifest.recipe_id)] = manifest.to_json()


def patch_sim(test) -> None:
    """Route ``dazpy.recipe``'s writes through the SimStudio passed as the scene."""
    from unittest.mock import patch
    p = patch("dazpy.recipe.DazSceneOps", side_effect=lambda scene: scene)
    p.start()
    test.addCleanup(p.stop)
