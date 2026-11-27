"""Pure three-way diff and conflict policy for scene recipes (spec §5.2-5.4).

:func:`diff` compares, per entity and per channel:

- **desired**: what the recipe wants now (:class:`DesiredEntity`);
- **base**: what the last apply recorded (``EntityRecord.desired`` for the
  recipe side, ``EntityRecord.observed`` for the scene side);
- **live**: what the scene shows now (``LiveEntity.observed``).

"Recipe changed" compares desired with ``record.desired``; "hand-tweaked"
compares live with ``record.observed`` (both shapes are like-for-like).  The
result is a :class:`RecipePlan`: the ordered steps an executor runs, every
conflict found, warnings for hand edits kept, and whether ``ask`` blocked the
whole apply.  No client, no I/O.

Step semantics for the executor:

- ``create``: ``channels`` = all desired channels; look up ``create`` info
  (asset path, light type) in the desired dict by ``path``.
- ``modify`` / ``set_environment``: write ``channels`` (desired values) to
  Studio; ``prior`` = live observed values of those channels, for rollback.
- ``adopt``: write nothing to Studio; rewrite the record so
  ``desired[ch] = channels[ch]`` and ``observed[ch] = prior[ch]``.
- ``release``: remove the ownership record from ``node_name`` and drop the
  path from the manifest (unless a ``create`` for the same path gives it a new
  node).  The node stays in the scene, no longer owned.  Emitted when a
  removal conflict is resolved ``"scene"``; reversible (the executor restores
  the record on rollback).
- ``unparent``: move ``channels["children"]["names"]`` to scene root
  (preserving world transform) before the entity's ``delete``.
- ``delete``: delete the node (runs last; cannot be rolled back).

v2 steps (spec 6.2-6.6, 8):

- ``take_over``: adopt the existing scene figure ``node_name`` (from the
  :class:`WearingPlan`); write ``channels`` (only what the recipe sets: never
  presets, no pose when the recipe gives none) and record it with
  ``adopted_from_scene``.
- ``preset``: apply ``channels["presets"]["paths"]`` in order to the actor's
  node (created / taken over in this run, else ``node_name``).
- ``fit``: load the item's asset and fit it to its actor (``create["fit_to"]``:
  the node created or taken over in this run, else the live actor node).
- ``unfit``: one-shot removal of non-owned items, ``channels["unfit"]`` =
  ``{actor, entry, op, names, removed}``; rollback reloads ``removed`` from
  their source paths.  The matching done-log entry is in ``RecipePlan.done_log``.
- ``delete`` / ``release`` of a fitted group carry ``channels["group"]["names"]``
  (every surviving group node); a group delete is one exact-selection delete.

Item replace detection compares ``asset_path`` / ``fit_to`` only (``source``
metadata such as the answering finder never triggers a replace).  A taken-over
actor (record ``adopted_from_scene``) is never replaced or deleted: removing it
from the recipe releases it and the records of its fitted items.  A missing
member of an owned group is ``deleted_in_scene`` for the item path.

Record contract: when writing an entity's record the executor stores
``DesiredEntity.create`` (asset path, light type) in ``EntityRecord.desired``
under the reserved key ``"_create"``.  A changed create-info is a **replace**:
the old node goes through the same checks as a removal (hand tweak →
``removed_from_recipe``, foreign children → ``has_foreign_children``); unless
that conflict is unresolved, a ``create`` step builds the new node with every
desired channel, and the old node is deleted (``"recipe"`` / no conflict) or
released (``"scene"``).
A record without ``"_create"`` is treated as unchanged (no replace).

Duplicate records (``LiveState.duplicates``: several nodes carry one record
path) are never modified, deleted or released under any policy: the path gets
a ``duplicate_record`` warning and a ``duplicate_record`` conflict, which
blocks under ``ask`` and which neither ``on_conflict`` nor ``resolutions`` can
resolve (only removing the extra node can).  Under ``recipe_wins`` /
``scene_wins`` the rest of the plan proceeds without that path.

Conflict paths are ``<entity path>.<channel>`` for ``modified`` and the entity
path for the other kinds; ``resolutions`` are keyed the same way (channel
paths, never property paths).  Resolution keys that match no conflict (or
accepted hand deletion) produce an ``unknown_resolution`` warning.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal
from collections.abc import Mapping

from ._pose import DazPose
from ._recipe_desired import DesiredEntity
from ._recipe_json import to_jsonable
from ._recipe_store import DuplicateRecord, LiveEntity, LiveState, strip_node_transform
from ._recipe_validate import RecipeIssue
from ._scene_state import _DEFAULT_VERIFY_TOLERANCE, _pose_mismatches

if TYPE_CHECKING:  # _recipe_wearing imports Conflict from this module
    from ._recipe_wearing import WearingPlan

OnConflict = Literal["ask", "recipe_wins", "scene_wins"]
Resolution = Literal["recipe", "scene"]
ConflictKind = Literal["modified", "removed_from_recipe", "deleted_in_scene", "has_foreign_children",
                       "duplicate_record"]
StepOp = Literal["create", "take_over", "preset", "fit", "modify", "set_environment", "adopt",
                 "release", "unparent", "unfit", "delete"]

ENVIRONMENT_PATH = "lighting.environment"
CREATE_KEY = "_create"
PRESETS_CHANNEL = "presets"
_ON_CONFLICT_VALUES = ("ask", "recipe_wins", "scene_wins")
_RESOLUTION_VALUES = ("recipe", "scene")
_ENVIRONMENT_CHANNEL = "environment"
_POSE_CHANNEL = "pose"
_MAX_DRIFTED = 5
# Channels where desired and observed are directly comparable key-by-key, so
# "live already equals desired" can be detected (controller ruling 3).
_NO_SHORTCUT_CHANNELS = (_POSE_CHANNEL, _ENVIRONMENT_CHANNEL)
# Removals run last (spec 8): they cannot be undone (an unfit only by reloading).
_STEP_ORDER: dict[str, int] = {op: i for i, op in enumerate(
    ("create", "take_over", "preset", "fit", "modify", "set_environment", "adopt", "release",
     "unparent", "unfit", "delete"))}


def is_item_path(path: str) -> bool:
    """``actors.<a>.wearing.<key>``: a fitted item entity."""
    return path.startswith("actors.") and ".wearing." in path


def item_actor(path: str) -> str:
    """The actor path an item path belongs to."""
    return path.split(".wearing.", 1)[0]


def _create_identity(create: Any) -> Any:
    """Create-info without ``source`` provenance (which never means a new asset)."""
    if isinstance(create, dict):
        return {k: v for k, v in create.items() if k != "source"}
    return create


def _group(entity: LiveEntity) -> dict:
    return {"group": {"names": list(entity.group_nodes)}} if entity.group_nodes else {}


@dataclass(frozen=True)
class Conflict:
    path: str
    kind: ConflictKind
    desired: object
    base: object
    live: object

    def to_dict(self) -> dict:
        return to_jsonable(self)


@dataclass(frozen=True)
class Step:
    op: StepOp
    path: str
    channels: dict[str, dict]
    prior: dict[str, dict] | None
    node_name: str | None

    @property
    def node(self) -> str:
        """``node_name`` for ops on an existing node (modify, release, unparent,
        delete), where the planner always sets it."""
        if self.node_name is None:
            raise ValueError(f"{self.op} step for {self.path} has no node_name")
        return self.node_name

    def to_dict(self) -> dict:
        return to_jsonable(self)


@dataclass(frozen=True)
class RecipePlan:
    steps: tuple[Step, ...]
    conflicts: tuple[Conflict, ...]
    warnings: tuple[RecipeIssue, ...]
    blocked: bool
    overwritten: tuple[str, ...]
    kept: tuple[str, ...]
    # The complete new value for Manifest.deleted (accepted hand deletions).
    tombstones: tuple[str, ...] = ()
    # (actor path, done entry) to append to that actor's record ``done`` log.
    done_log: tuple[tuple[str, dict], ...] = ()

    def to_dict(self) -> dict:
        return to_jsonable(self)


# ── comparison ────────────────────────────────────────────────────────────────

def _equal(a: Any, b: Any, tol: float) -> bool:
    """Recursive compare: numbers within *tol*, sequences elementwise, dicts by key."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= tol
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_equal(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_equal(a[k], b[k], tol) for k in a)
    return a == b


def _pose_drift(base: Any, live: Any, tol: float) -> list[str]:
    """Drifted pose channels between two observed ``{"snapshot": ...}`` values.

    Node-transform props are ignored on both sides (records written before
    they were stripped from snapshots still carry them).
    """
    if not (isinstance(base, dict) and isinstance(live, dict)
            and "snapshot" in base and "snapshot" in live):
        return [] if base == live else ["pose snapshot missing"]
    return _pose_mismatches(DazPose(**strip_node_transform(base["snapshot"])),
                            DazPose(**strip_node_transform(live["snapshot"])), tol)


def _observed_differs(channel: str, base: Any, live: Any, tol: float) -> bool:
    if channel == _POSE_CHANNEL:
        return bool(_pose_drift(base, live, tol))
    return not _equal(base, live, tol)


def _live_equals_desired(channel: str, desired: Any, live: Any, tol: float) -> bool:
    if channel in _NO_SHORTCUT_CHANNELS:
        return False
    if not (isinstance(desired, dict) and isinstance(live, dict)):
        return False
    return all(k in live and _equal(v, live[k], tol) for k, v in desired.items())


def _tweaked_channels(entity: LiveEntity, tol: float) -> list[str]:
    base = entity.record.observed
    return [ch for ch in base
            if _observed_differs(ch, base.get(ch), entity.observed.get(ch), tol)]


# ── planning ──────────────────────────────────────────────────────────────────

class _Planner:
    def __init__(self, on_conflict: OnConflict, resolutions: Mapping[str, Resolution] | None,
                 tolerance: float) -> None:
        self.on_conflict = on_conflict
        self.resolutions = dict(resolutions or {})
        self.tol = tolerance
        self.steps: list[Step] = []
        self.conflicts: list[Conflict] = []
        self.warnings: list[RecipeIssue] = []
        self.overwritten: list[str] = []
        self.kept: list[str] = []
        self.tombstones: list[str] = []
        # Paths a resolution may legitimately name: conflicts + accepted deletions.
        self.targets: list[str] = []
        # v2 state
        self.live: LiveState | None = None
        self.duplicated: set[str] = set()
        self.take_overs: dict[str, str] = {}
        self.rebuilt: set[str] = set()      # paths that get a new node in this run
        self.retired: dict[str, str] = {}   # path -> "delete" | "release" (its old node)
        self.done_log: list[tuple[str, dict]] = []

    def resolution_for(self, path: str) -> Resolution | None:
        self.targets.append(path)
        if path in self.resolutions:
            return self.resolutions[path]
        defaults: dict[str, Resolution] = {"recipe_wins": "recipe", "scene_wins": "scene"}
        return defaults.get(self.on_conflict)

    def conflict(self, c: Conflict) -> Resolution | None:
        """Record *c*; return how it resolves (None = unresolved under ``ask``)."""
        self.conflicts.append(c)
        res = self.resolution_for(c.path)
        if res == "recipe":
            self.overwritten.append(c.path)
        elif res == "scene":
            self.kept.append(c.path)
        return res

    def warn(self, path: str, code: str, message: str) -> None:
        self.warnings.append(RecipeIssue(path=path, code=code, message=message))

    def step(self, op: StepOp, path: str, channels: dict, prior: dict | None,
             node_name: str | None) -> None:
        self.steps.append(Step(op, path, channels, prior, node_name))

    # entity in recipe and in scene: per-channel three-way compare
    def compare(self, d: DesiredEntity, path: str, record_desired: dict, record_observed: dict,
                live_observed: dict, node_name: str | None, write_op: StepOp) -> None:
        write: dict = {}
        adopt: dict = {}
        for ch, want in d.channels.items():
            if ch == PRESETS_CHANNEL:
                continue  # see presets()
            base = record_desired.get(ch)
            obs_base, obs_live = record_observed.get(ch), live_observed.get(ch)
            changed = ch not in record_desired or not _equal(want, base, self.tol)
            tweaked = _observed_differs(ch, obs_base, obs_live, self.tol)
            chpath = f"{path}.{ch}"
            if changed and not tweaked:
                write[ch] = want
            elif tweaked and not changed:
                self.warn(chpath, "hand_tweak_kept",
                          f"{chpath} was edited in the scene; keeping the scene value.")
            elif changed and tweaked:
                if _live_equals_desired(ch, want, obs_live, self.tol):
                    adopt[ch] = want
                    continue
                live_report = ({"drifted": _pose_drift(obs_base, obs_live, self.tol)[:_MAX_DRIFTED]}
                               if ch == _POSE_CHANNEL else obs_live)
                res = self.conflict(Conflict(chpath, "modified", want, base, live_report))
                if res == "recipe":
                    write[ch] = want
                elif res == "scene":
                    adopt[ch] = want
        if write:
            self.step(write_op, path, write, {ch: live_observed.get(ch) for ch in write}, node_name)
        if adopt:
            self.step("adopt", path, adopt, {ch: live_observed.get(ch) for ch in adopt}, node_name)

    def build(self, path: str, d: DesiredEntity) -> bool:
        """Emit the steps giving *path* a new node: create, take-over or fit
        (+ presets).  False when an item has no actor node to fit to."""
        if d.kind == "item":
            if not self.can_fit(d):
                return False
            self.step("fit", path, {}, None, None)
            self.rebuilt.add(path)
            return True
        channels = {ch: v for ch, v in d.channels.items() if ch != PRESETS_CHANNEL}
        node = self.take_overs.get(path)
        if node is not None:
            # Only what the recipe sets: no pose write when it names no pose.
            write = {ch: v for ch, v in channels.items()
                     if not (ch == _POSE_CHANNEL and isinstance(v, dict)
                             and "pose_path" in v and v["pose_path"] is None)}
            self.step("take_over", path, write, None, node)
        else:
            self.step("create", path, channels, None, None)
        self.rebuilt.add(path)
        if (d.channels.get(PRESETS_CHANNEL) or {}).get("paths"):
            self.step("preset", path, {PRESETS_CHANNEL: d.channels[PRESETS_CHANNEL]}, None, node)
        return True

    def actor_has_node(self, actor: str) -> bool:
        """Will *actor* have a node after this run (live and kept, or built now)?"""
        if actor in self.rebuilt:
            return True
        assert self.live is not None
        return (actor in self.live.entities and actor not in self.duplicated
                and actor not in self.retired)

    def can_fit(self, d: DesiredEntity) -> bool:
        actor = d.create.get("fit_to") or item_actor(d.path)
        if self.actor_has_node(actor):
            return True
        self.warn(d.path, "hand_deleted_kept",
                  f"{d.path} is not fitted: its actor {actor} has no node in the scene "
                  "(its deletion was accepted or is unresolved).")
        return False

    def present(self, path: str, d: DesiredEntity, live: LiveState, owned: set,
                tombstoned: set) -> None:
        entity = live.entities.get(path)
        if d.kind == "item" and entity is not None:
            self.present_item(d, entity)
        elif entity is not None:
            r = entity.record
            old_create = r.desired.get(CREATE_KEY)
            # A taken-over actor's base figure is never replaced (spec 6.2).
            if (not r.adopted_from_scene and old_create is not None
                    and not _equal(_create_identity(old_create), _create_identity(d.create),
                                   self.tol)):
                self.replace(d, entity)
                return
            self.compare(d, path, r.desired, r.observed, entity.observed, entity.node_name, "modify")
            self.presets(d, path, r.desired, entity.node_name)
        elif path in tombstoned:
            if self.resolution_for(path) == "recipe":
                self.overwritten.append(path)
                self.build(path, d)
            else:
                self.tombstones.append(path)
                self.warn(path, "hand_deleted_kept",
                          f"{path} was deleted in the scene earlier and that deletion was accepted; "
                          "not recreating it.")
        elif path in owned:
            res = self.conflict(Conflict(path, "deleted_in_scene", d.channels, None, None))
            if res == "recipe":
                self.build(path, d)
            elif res == "scene":
                self.tombstones.append(path)
        else:
            self.build(path, d)

    def present_item(self, d: DesiredEntity, entity: LiveEntity) -> None:
        path = entity.path
        if entity.missing_members:
            # Any group node deleted by hand: the item counts as deleted (spec 6.6).
            res = self.conflict(Conflict(
                path, "deleted_in_scene", d.create, None,
                {"missing_members": list(entity.missing_members),
                 "surviving": list(entity.group_nodes)}))
            if res == "recipe":
                if self.can_fit(d) and self.retire(
                        entity, d.create, f"{path}: the surviving group nodes were kept in the "
                        "scene (no longer owned by the recipe) and the item fitted again."):
                    self.step("fit", path, {}, None, None)
                    self.rebuilt.add(path)
            elif res == "scene":
                self.tombstones.append(path)
                self.step("release", path, _group(entity), None, entity.node_name)
                self.retired[path] = "release"
            return
        old = entity.record.desired.get(CREATE_KEY)
        actor = d.create.get("fit_to") or item_actor(path)
        changed = old is not None and not _equal(_create_identity(old),
                                                 _create_identity(d.create), self.tol)
        if not changed and actor not in self.rebuilt:
            return
        if not self.can_fit(d):
            return
        if self.retired.get(actor) == "release":
            # The old actor node stays in the scene unowned; so do its items.
            self.step("release", path, _group(entity), None, entity.node_name)
            self.retired[path] = "release"
        elif not self.retire(entity, dict(d.channels, **{CREATE_KEY: d.create}),
                             f"{path} changed asset in the recipe; the existing item was kept in "
                             "the scene (no longer owned by the recipe) and a new one fitted."):
            return
        self.step("fit", path, {}, None, None)
        self.rebuilt.add(path)

    def presets(self, d: DesiredEntity, path: str, record_desired: dict,
                node_name: str | None) -> None:
        """Preset list changes: apply the new list in order when anything was
        added or reordered; dropped presets are not undone (warning)."""
        want = list((d.channels.get(PRESETS_CHANNEL) or {}).get("paths") or [])
        base = list((record_desired.get(PRESETS_CHANNEL) or {}).get("paths") or [])
        if want == base:
            return
        dropped = [x for x in base if x not in want]
        if dropped:
            self.warn(f"{path}.presets", "preset_dropped",
                      f"Preset(s) {', '.join(map(repr, dropped))} were removed from {path}; "
                      "presets cannot be undone, so their effect stays on the figure.")
        added = [x for x in want if x not in base]
        reordered = [x for x in want if x in base] != [x for x in base if x in want]
        value = {PRESETS_CHANNEL: {"paths": want}}
        if added or reordered:
            self.step("preset", path, value, None, node_name)
        else:  # only drops: record-only catch-up, nothing is applied to the figure
            self.step("adopt", path, value, {PRESETS_CHANNEL: None}, node_name)

    def removed(self, entity: LiveEntity) -> None:
        if entity.record.adopted_from_scene:
            # A taken-over actor is never deleted (spec 6.2): release it.
            self.warn(entity.path, "removed_entity_kept",
                      f"{entity.path} was taken over from the scene; removing it from the recipe "
                      "releases it (it is never deleted).")
            self.step("release", entity.path, {}, None, entity.node_name)
            self.retired[entity.path] = "release"
            return
        self.retire(entity, None, f"{entity.path} was removed from the recipe but kept in the "
                                  "scene; the recipe no longer owns it.")

    def removed_item(self, entity: LiveEntity) -> None:
        if self.retired.get(item_actor(entity.path)) == "release":
            # The actor stays in the scene unowned: its fitted items become hand content too.
            self.warn(entity.path, "removed_entity_kept",
                      f"{entity.path} stays in the scene with its released actor; the recipe no "
                      "longer owns it.")
            self.step("release", entity.path, _group(entity), None, entity.node_name)
            self.retired[entity.path] = "release"
            return
        self.removed(entity)

    def wearing(self, w: WearingPlan) -> None:
        """One-shot unfits, their conflicts and the done-log (spec 6.4)."""
        skip: set[str] = set()
        for c in w.conflicts:
            res = self.conflict(c)
            if res == "scene":
                skip.add(c.path)
            elif res == "recipe" and c.kind == "has_foreign_children":
                owner = c.base.get("node") if isinstance(c.base, dict) else None
                if owner is None:
                    raise ValueError(f"wearing conflict {c.path} names no node to unparent from")
                names = list(c.live) if isinstance(c.live, (list, tuple)) else []
                self.step("unparent", c.path, {"children": {"names": names}}, None, owner)
        for u in w.unfits:
            epath = f"{u.actor_path}.wearing.{u.entry}"
            # Never on an actor whose old node is retired (re-evaluated next apply).
            if (epath in skip or not self.actor_has_node(u.actor_path)
                    or u.actor_path in self.retired):
                continue
            op = _entry_op(u.entry)
            self.step("unfit", epath, {"unfit": {
                "actor": u.actor_path, "entry": u.entry, "op": op,
                "names": list(u.node_names), "removed": [dict(r) for r in u.removed]}}, None, None)
            self.done_log.append((u.actor_path, {"entry": u.entry, "op": op,
                                                 "removed": [dict(r) for r in u.removed]}))
        for actor, entry in w.done_entries:
            if self.actor_has_node(actor):
                self.done_log.append((actor, {"entry": entry, "op": _entry_op(entry),
                                              "removed": []}))

    def replace(self, d: DesiredEntity, entity: LiveEntity) -> None:
        """Create-info changed: retire the old node and create the new one."""
        desired = dict(d.channels, **{CREATE_KEY: d.create})
        if self.retire(entity, desired,
                       f"{entity.path} changed asset/type in the recipe; the existing node was "
                       "kept in the scene (no longer owned by the recipe) and a new one created."):
            self.build(entity.path, d)

    def retire(self, entity: LiveEntity, desired: object, kept_message: str) -> bool:
        """Delete *entity*'s node, or release it when a removal conflict keeps it.

        Returns False only when the conflict is unresolved (nothing emitted).
        """
        path = entity.path
        kind: ConflictKind | None
        if entity.foreign_children:
            kind = "has_foreign_children"
            live_report: object = {"foreign_children": list(entity.foreign_children)}
        elif _tweaked_channels(entity, self.tol):
            kind, live_report = "removed_from_recipe", entity.observed
        else:
            kind = None
        if kind is not None:
            res = self.conflict(Conflict(path, kind, desired, entity.record.desired, live_report))
            if res is None:
                return False
            if res == "scene":
                self.warn(path, "removed_entity_kept", kept_message)
                self.step("release", path, _group(entity), None, entity.node_name)
                self.retired[path] = "release"
                return True
        if entity.foreign_children:
            self.step("unparent", path, {"children": {"names": list(entity.foreign_children)}},
                      None, entity.node_name)
        # A fitted group goes in one delete of all its surviving nodes.
        self.step("delete", path, _group(entity), None, entity.node_name)
        self.retired[path] = "delete"
        return True

    def duplicate(self, dup: DuplicateRecord, d: DesiredEntity | None, live: LiveState) -> None:
        """Report a path recorded on several nodes; touch none of them."""
        path = dup.path
        self.targets.append(path)
        nodes = ", ".join(f"{n!r} (element id {i})" for n, i in zip(dup.node_names, dup.element_ids))
        self.warn(path, "duplicate_record",
                  f"{path} is recorded on {len(dup.node_names)} nodes: {nodes} (a node duplicated "
                  "in Daz Studio copies its recipe record). The recipe changes none of them; "
                  "delete the extra node(s) to resolve this. No policy or resolution can.")
        self.conflicts.append(Conflict(
            path, "duplicate_record", d.channels if d is not None else None,
            live.entities[path].record.desired,
            {"nodes": list(dup.node_names), "element_ids": list(dup.element_ids)}))

    def environment(self, d: DesiredEntity | None, live: LiveState) -> None:
        record = live.manifest.environment if live.manifest else None
        if d is None:
            if record is not None:
                self.warn(ENVIRONMENT_PATH, "environment_left_in_scene",
                          "The environment was removed from the recipe; the scene's environment "
                          "settings are left as they are.")
            return
        live_obs = ({_ENVIRONMENT_CHANNEL: live.environment_observed}
                    if live.environment_observed is not None else {})
        if record is None:
            self.step("set_environment", ENVIRONMENT_PATH, dict(d.channels),
                      dict(live_obs) or None, None)
            return
        self.compare(d, ENVIRONMENT_PATH, record.desired, record.observed, live_obs, None,
                     "set_environment")


def _entry_op(entry: str) -> str:
    """The done-log ``op`` for a wearing entry id (``remove.<i>`` or a key)."""
    return "remove" if entry.startswith("remove.") else "replace"


def _sort_key(s: Step) -> tuple[int, int]:
    # Item groups are deleted before actors (fitted items are parented under them).
    return _STEP_ORDER[s.op], 0 if s.op == "delete" and is_item_path(s.path) else 1


def diff(desired: dict[str, DesiredEntity], live: LiveState, *, on_conflict: OnConflict = "ask",
         resolutions: Mapping[str, Resolution] | None = None,
         tolerance: float = _DEFAULT_VERIFY_TOLERANCE,
         wearing: WearingPlan | None = None) -> RecipePlan:
    """Plan an apply of *desired* onto *live* under the caller's conflict policy.

    Under ``ask``, any conflict not covered by *resolutions* blocks the whole
    plan: ``blocked=True`` and no steps (all conflicts and warnings are still
    reported).

    *wearing* (v2) supplies take-overs, one-shot unfits, their conflicts (which
    block under ``ask`` like any other) and warnings.  A wearing plan with
    errors is refused (``ValueError``): those must stop the apply before diff.
    """
    if on_conflict not in _ON_CONFLICT_VALUES:
        raise ValueError(f"on_conflict={on_conflict!r} is invalid; allowed values: "
                         f"{', '.join(map(repr, _ON_CONFLICT_VALUES))}")
    for key, value in (resolutions or {}).items():
        if value not in _RESOLUTION_VALUES:
            raise ValueError(f"resolutions[{key!r}]={value!r} is invalid; allowed values: "
                             f"{', '.join(map(repr, _RESOLUTION_VALUES))}")
    if wearing is not None and wearing.errors:
        raise ValueError("the wearing plan has errors ("
                         + "; ".join(f"{e.path}: {e.code}" for e in wearing.errors)
                         + "); they must stop the apply before diff")
    p = _Planner(on_conflict, resolutions, tolerance)
    manifest = live.manifest
    owned = set(manifest.entities) if manifest else set()
    owned |= set(live.entities)
    tombstoned = set(manifest.deleted) if manifest else set()

    duplicated = {dup.path for dup in live.duplicates}
    p.live, p.duplicated = live, duplicated
    if wearing is not None:
        p.take_overs = {t.actor_path: t.node_name for t in wearing.take_overs}
        p.warnings.extend(wearing.warnings)
    # Actors come before their items in *desired*, so an item sees its actor's fate.
    for path, d in desired.items():
        if path != ENVIRONMENT_PATH and path not in duplicated:
            p.present(path, d, live, owned, tombstoned)
    gone = [e for path, e in live.entities.items()
            if path not in desired and path not in duplicated]
    for entity in gone:  # actors (and v1 entities) first: an item follows its actor's fate
        if not is_item_path(entity.path):
            p.removed(entity)
    for entity in gone:
        if is_item_path(entity.path):
            p.removed_item(entity)
    if wearing is not None:
        p.wearing(wearing)
    for dup in live.duplicates:
        p.duplicate(dup, desired.get(dup.path), live)
    p.environment(desired.get(ENVIRONMENT_PATH), live)

    conflict_paths = [c.path for c in p.conflicts]
    for key in p.resolutions:
        if key not in p.targets:
            p.warn(key, "unknown_resolution",
                   f"Resolution {key!r} matches no conflict and was ignored. Resolution keys are "
                   "channel paths like '<entity>.<channel>' (e.g. 'cameras.cu.transform'), or the "
                   "entity path for removal/deletion conflicts. Conflict paths in this plan: "
                   f"{', '.join(conflict_paths) if conflict_paths else '(none)'}.")

    blocked = on_conflict == "ask" and any(
        c.kind == "duplicate_record" or c.path not in p.resolutions for c in p.conflicts)
    if blocked:
        return RecipePlan((), tuple(p.conflicts), tuple(p.warnings), True, (), (), ())
    steps = tuple(sorted(p.steps, key=_sort_key))
    return RecipePlan(steps, tuple(p.conflicts), tuple(p.warnings), False,
                      tuple(p.overwritten), tuple(p.kept), tuple(p.tombstones),
                      tuple(p.done_log))
