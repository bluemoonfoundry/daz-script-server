"""Executor for scene-recipe plans with compensating rollback (spec §5.4).

:func:`execute` runs a :class:`RecipePlan` through a :class:`SceneOps`.  Every
mutation is journaled with its compensation; on any failure the journal is
walked in reverse, so a failed apply leaves the scene as it was (dazpy's
``UndoGroup`` cannot revert, so this is real compensation).

Order of work:

1. ``create`` / ``take_over`` / ``preset`` / ``fit`` / ``modify`` /
   ``set_environment`` / ``adopt`` / ``release`` steps;
2. ownership records for every created, taken-over, fitted, modified or
   adopted entity, and the actors' ``done`` logs (``RecipePlan.done_log``);
3. ``unparent`` / ``unfit`` / ``delete`` steps (removals, after everything
   that can still fail and be undone);
4. the manifest, last (skipped when the plan has no steps and the manifest
   would not change).

Compensations: create → delete every created node; modify → write the step's
prior values back (journaled *before* the write, so a write that fails halfway
is restored too); set_environment → write back the pre-apply environment (the
step's prior, or one ``observe_environment`` taken just before when the plan
has none); record write → write the previous record back (records on nodes
created by this apply are not compensated, since those nodes are deleted);
release → write the removed record back and restore the ``<recipe id>:`` label
(a release strips that prefix from a label the user has not changed);
unparent → reparent exactly the nodes it moved (by key), unless their owner
has already been deleted (a refused unparent moved nothing and is not undone).
v2 compensations: take_over → write the figure's prior channel values back
and remove the record written on it (the figure itself is never deleted);
fit → delete the whole fitted group in one ``unfit``; unfit → ``restore`` the
removed items from their source files onto the figure (a failed reload is in
``rollback_errors``; after a rollback every removed item not restored, no
source or failed reload, is an ``unrestorable_removal`` warning and its unfit
step stays in ``ApplyResult.steps``); preset on a node not created by
this apply → cannot be undone, reported in ``rollback_errors``.  A failure
before the removal phase leaves the one-shot unfit targets untouched (they
have not run).  Children a wearing ``unparent`` moved out of an item stay at
scene root when that item's unfit is rolled back (the restored item is a new
node).  Group deletes are one checked ``unfit`` of every surviving node
(``owner_recipe``: refused, and the apply rolled back, when any member still
has a descendant the recipe does not own).

Done log: an actor record keeps its earlier ``done`` entries when the recipe
replaces the actor (new asset).  An actor deleted by hand and re-created loses
them (the record lived on the deleted node).
Plan deletes are checked deletes (``owner_recipe``): a node that still has a
descendant the recipe does not own is not deleted, the apply fails and rolls
back instead.  Deletes cannot be undone: a failure in the delete phase leaves the deletes
already done in place, reports them in ``ApplyResult.steps`` and as
``deleted_not_restored`` warnings.  Compensations that fail are collected in
``rollback_errors``, never raised.

Records (controller rulings): a created node's record holds every desired
channel plus ``"_create"`` and a fresh ``observe``; a modified entity's record
is merged per channel (only changed channels get new desired + fresh observed
values); an adopted channel stores the new desired value and the step's prior
(live) value.  The manifest lists every recipe entity with an owned node after
apply (a released path is dropped unless this apply created a new node for
it), ``deleted = plan.tombstones``, and the environment record (new when the
environment was written or adopted, else the previous one).

Known v1 gap: recipe-owned nodes parented under a node being deleted are not
handled specially (they go with it).
"""

from __future__ import annotations

import copy
import dataclasses
from dataclasses import dataclass
from functools import partial
from typing import Any
from collections.abc import Callable

from ._recipe_desired import DesiredEntity
from ._recipe_diff import (CREATE_KEY, ENVIRONMENT_PATH, PRESETS_CHANNEL, Conflict, RecipePlan,
                           Step)
from ._recipe_json import to_jsonable
from ._recipe_fitted import is_data_file
from ._recipe_ops import SceneOps
from ._recipe_store import EntityRecord, LiveState, Manifest
from ._recipe_validate import RecipeIssue
from ._scene_check import CheckReport
from .exceptions import DazError

_ENV_CHANNEL = "environment"
_REMOVAL_OPS = ("unparent", "unfit", "delete")
_RECORD_OPS = ("create", "take_over", "preset", "fit", "modify", "set_environment", "adopt")


def _member_record(rec: EntityRecord, name: str) -> EntityRecord:
    """The record group member *name* carries, rebuilt from another member's
    (they differ only in ``primary``)."""
    primary = bool(rec.members) and name == rec.members[0]
    source = dict(rec.source, primary=primary) if rec.source else rec.source
    return dataclasses.replace(rec, primary=primary, source=source)


def _cannot_undo(message: str) -> None:
    raise DazError(message)


@dataclass(frozen=True)
class ApplyResult:
    """Outcome of :func:`execute`.

    ``steps`` are the steps in effect afterwards: every plan step on success;
    after a rollback, only the deletes that ran (they cannot be undone) and the
    one-shot unfits whose removed items were not all restored, and
    ``overwritten`` / ``kept`` are empty.
    ``failed_step`` is None when the failure happened while writing records or
    the manifest (``error`` then says which).
    ``check``: the scene check run before the manifest is written
    (``apply(..., require_clean=True)``); when it has errors the apply rolls back.
    """

    applied: bool
    steps: tuple[Step, ...]
    conflicts: tuple[Conflict, ...]
    warnings: tuple[RecipeIssue, ...]
    overwritten: tuple[str, ...]
    kept: tuple[str, ...]
    rolled_back: bool = False
    failed_step: Step | None = None
    error: str | None = None
    rollback_errors: tuple[str, ...] = ()
    check: CheckReport | None = None

    def to_dict(self) -> dict:
        return to_jsonable(self)


class _CheckFailed(Exception):
    def __init__(self, report: CheckReport) -> None:
        self.report = report
        super().__init__(f"{len(report.errors)} error(s): " + "; ".join(
            f"{f.subject}: [{f.code}] {f.message}" for f in report.errors))


class _Run:
    def __init__(self, plan: RecipePlan, desired: dict[str, DesiredEntity], live: LiveState,
                 ops: SceneOps, recipe_id: str, recipe_version: int,
                 verify: Callable[[], CheckReport] | None = None) -> None:
        self.plan, self.desired, self.live, self.ops = plan, desired, live, ops
        self.recipe_id, self.recipe_version = recipe_id, recipe_version
        self.verify = verify
        self.check: CheckReport | None = None
        self.journal: list[tuple[str, Callable[[], object]]] = []
        self.created: dict[str, list[str]] = {}   # created or fitted nodes, primary first
        self.taken: dict[str, str] = {}           # taken-over figure per actor path
        self.native: dict[str, tuple[str, ...]] = {}  # created node's native descendants
        self.done_for: dict[str, list[dict]] = {}
        for actor, entry in plan.done_log:
            self.done_for.setdefault(actor, []).append(entry)
        self.deleted_steps: list[Step] = []
        # executed one-shot unfits with the removed items not (yet) restorable
        self.unfits_run: list[tuple[Step, list[dict]]] = []
        self.deleted_nodes: set[str] = set()
        self.released: set[str] = set()
        self.current: Step | None = None
        self.context = ""
        self.env_record = live.manifest.environment if live.manifest else None

    def undo(self, label: str, fn: Callable[[], object]) -> None:
        self.journal.append((label, fn))

    def node_for(self, path: str) -> str:
        """The node *path* has now: created / taken over in this run, else live."""
        if path in self.created:
            return self.created[path][0]
        if path in self.taken:
            return self.taken[path]
        entity = self.live.entities.get(path)
        if entity is None:
            raise DazError(f"{path} has no node in the scene")
        return entity.node_name

    # ── steps ─────────────────────────────────────────────────────────────────

    def perform(self, step: Step) -> None:
        ops = self.ops
        if step.op == "create":
            d = self.desired[step.path]
            names = ops.create(d)
            for name in names:
                self.undo(f"delete created node {name!r} ({step.path})",
                          partial(ops.delete, name))
            self.created[step.path] = list(names)
            # Captured now, before presets and fits of this run add children
            # (fitted items are parented under the figure): only what the asset
            # loaded with is native (final review I6).
            self.native[step.path] = tuple(ops.native_descendants(names[0]))
            ops.set_channels(names[0], d.kind, step.channels)
        elif step.op == "modify":
            node, kind = step.node, self.desired[step.path].kind
            prior = {ch: v for ch, v in (step.prior or {}).items() if v is not None}
            if prior:
                self.undo(f"restore {step.path} ({', '.join(prior)}) on {node!r}",
                          lambda: ops.set_channels(node, kind, prior))
            ops.set_channels(node, kind, step.channels)
        elif step.op == "set_environment":
            env_prior = (step.prior or {}).get(_ENV_CHANNEL)
            if env_prior is None:
                env_prior = ops.observe_environment()
            if env_prior is not None:
                restore = env_prior
                self.undo("restore the scene environment", lambda: ops.set_environment(restore))
            ops.set_environment(step.channels[_ENV_CHANNEL])
        elif step.op == "take_over":
            node = step.node
            ops.take_over(node)
            if step.channels:
                observed = ops.observe(node, "actor")
                prior = {ch: observed[ch] for ch in step.channels if observed.get(ch) is not None}
                if prior:
                    self.undo(f"restore {step.path} ({', '.join(prior)}) on {node!r}",
                              partial(ops.set_channels, node, "actor", prior))
                ops.set_channels(node, "actor", step.channels)
            self.taken[step.path] = node
        elif step.op == "preset":
            node = self.node_for(step.path)
            paths = list(step.channels[PRESETS_CHANNEL]["paths"])
            if step.path not in self.created:  # a created node is deleted on rollback
                self.undo(f"undo presets on {node!r}", partial(
                    _cannot_undo, f"preset(s) {paths} applied to {node!r} cannot be undone"))
            ops.apply_presets(node, paths)
        elif step.op == "fit":
            d = self.desired[step.path]
            figure = self.node_for(d.create["fit_to"])
            names = list(ops.fit(d, figure))
            if not names:
                raise DazError(f"{step.path}: fitting added no node")
            self.undo(f"remove fitted group {names} ({step.path})", partial(ops.unfit, names))
            self.created[step.path] = names
        elif step.op == "unfit":
            u = step.channels["unfit"]
            figure, names = self.node_for(u["actor"]), list(u["names"])
            # hand items are addressed by elementID: ref and must still follow the
            # actor's figure (final review C1)
            ops.unfit(names, figure=figure)
            self.deleted_nodes.update(names)
            # Items with no known .duf were warned about at plan time
            # (unrestorable_removal) and are skipped on rollback; a .dsf data URI is
            # never a restore source (spec 8.7, 15.2).
            restorable = [r for r in u["removed"]
                          if r.get("source_path") and not is_data_file(r["source_path"])]
            # reported after a rollback unless restored (final review I8)
            lost = [r for r in u["removed"] if r not in restorable]
            self.unfits_run.append((step, lost))
            sources = [r["source_path"] for r in restorable]
            if sources:
                def restore_removed(sources=sources, figure=figure, restorable=restorable, lost=lost):
                    try:
                        ops.restore(sources, figure)
                    except Exception:
                        lost.extend(restorable)
                        raise
                self.undo(f"restore removed items {sources} onto {figure!r}", restore_removed)
        elif step.op == "release":
            entity = self.live.entities[step.path]
            node = step.node
            group = step.channels.get("group")
            for name in (list(group["names"]) if group else [node]):
                prev = entity.record if name == entity.node_name else _member_record(
                    entity.record, name)
                self.undo(f"restore the ownership record of {step.path} on {name!r}",
                          partial(ops.write_record, name, prev))
                ops.remove_record(name)
            self.released.add(step.path)
            # A kept node gives up the "<recipe id>:" label, so a node the recipe
            # creates for the same path later is the only one carrying it.
            prefix = f"{self.recipe_id}:"
            old = entity.label
            if old and old.startswith(prefix) and len(old) > len(prefix):
                new = old[len(prefix):]
                self.undo(f"restore the label {old!r} on {node!r}",
                          lambda: ops.relabel(node, new, old))
                ops.relabel(node, old, new)
        elif step.op == "unparent":
            names, owner = list(step.channels["children"]["names"]), step.node
            # unparent moves nothing unless every name is found, so it is undone
            # only once it succeeded, and exactly the nodes it moved go back.
            moved = ops.unparent(owner, names)

            def reparent() -> None:
                if owner not in self.deleted_nodes:
                    ops.reparent(moved, owner)

            self.undo(f"reparent {names} under {owner!r}", reparent)
        elif step.op == "delete":
            group = step.channels.get("group")
            if group:  # a fitted group: one checked exact-selection delete of every node
                names = list(group["names"])
                ops.unfit(names, owner_recipe=self.recipe_id)
                self.deleted_nodes.update(names)
            else:
                ops.delete(step.node, owner_recipe=self.recipe_id)
                self.deleted_nodes.add(step.node)
            self.deleted_steps.append(step)
        # adopt: nothing to write to Studio; handled by write_records

    # ── records / manifest ────────────────────────────────────────────────────

    def record(self, path: str, desired: dict, observed: dict,
               native: tuple[str, ...] = ()) -> EntityRecord:
        return EntityRecord(self.recipe_id, path, self.recipe_version, desired, observed, native)

    def with_done(self, path: str, rec: EntityRecord) -> EntityRecord:
        """*rec* with this run's done-log entries for actor *path* appended."""
        if path not in self.done_for:
            return rec
        return dataclasses.replace(rec, done=tuple(rec.done) + tuple(
            copy.deepcopy(self.done_for[path])))

    def write_records(self, steps: list[Step]) -> None:
        by_path: dict[str, list[Step]] = {}
        for s in steps:
            if s.op in _RECORD_OPS:
                by_path.setdefault(s.path, []).append(s)
        for path in self.done_for:  # the done-log alone also rewrites an actor's record
            if path in by_path or path in self.created or path in self.taken \
                    or path in self.live.entities:
                by_path.setdefault(path, [])
        for path, path_steps in by_path.items():
            self.context = f"writing the ownership record for {path}"
            if path == ENVIRONMENT_PATH:
                self.env_record = self.merged(path, path_steps, self.env_record, None)
            elif path in self.created:
                self.write_created(path)
            elif path in self.taken:
                self.write_taken(path)
            else:
                entity = self.live.entities[path]
                new = self.with_done(path, self.merged(path, path_steps, entity.record,
                                                       entity.node_name))
                node, prev = entity.node_name, entity.record
                self.undo(f"restore the ownership record of {path} on {node!r}",
                          partial(self.ops.write_record, node, prev))
                self.ops.write_record(node, new)
        self.context = ""

    def write_created(self, path: str) -> None:
        d = self.desired[path]
        names = self.created[path]
        node = names[0]
        desired = copy.deepcopy(d.channels)
        desired[CREATE_KEY] = copy.deepcopy(d.create)
        if d.kind == "item":
            self.write_group(path, d, names, desired)
            return
        rec = self.record(path, desired, self.ops.observe(node, d.kind), self.native[path])
        old = self.live.entities.get(path)
        if old is not None:  # a replace: one-shot entries already done stay done (spec 6.4)
            rec = dataclasses.replace(rec, done=tuple(copy.deepcopy(old.record.done)))
        if d.create.get("source") is not None:
            rec = dataclasses.replace(rec, source=copy.deepcopy(d.create["source"]))
        self.ops.write_record(node, self.with_done(path, rec))

    def write_group(self, path: str, d: DesiredEntity, names: list[str], desired: dict) -> None:
        """One record per fitted node (spec 6.6, 9).  Items are not observed:
        they follow their figure, so their transform is never a hand edit."""
        actor_key = d.create["fit_to"].split(".", 1)[1]
        uris = self.ops.asset_uris(names)
        for i, name in enumerate(names):
            source = dict(copy.deepcopy(d.create.get("source") or {}),
                          fitted_to=actor_key, group=path, primary=i == 0)
            self.ops.write_record(name, dataclasses.replace(
                self.record(path, copy.deepcopy(desired), {}, self.ops.native_descendants(name)),
                source=source, group=path, primary=i == 0, members=tuple(names),
                asset_uri=uris.get(name)))

    def write_taken(self, path: str) -> None:
        d = self.desired[path]
        node = self.taken[path]
        desired = copy.deepcopy(d.channels)
        desired[CREATE_KEY] = copy.deepcopy(d.create)
        rec = dataclasses.replace(self.record(path, desired, self.ops.observe(node, d.kind)),
                                  adopted_from_scene=True,
                                  source=copy.deepcopy(d.create.get("source")))
        self.undo(f"remove the ownership record of {path} from {node!r}",
                  partial(self.ops.remove_record, node))
        self.ops.write_record(node, self.with_done(path, rec))

    def merged(self, path: str, steps: list[Step], prev: EntityRecord | None,
               node: str | None) -> EntityRecord:
        """*prev* with the channels *steps* changed replaced (per-channel merge)."""
        desired: dict[str, Any] = copy.deepcopy(prev.desired) if prev else {}
        observed: dict[str, Any] = copy.deepcopy(prev.observed) if prev else {}
        fresh: dict | None = None
        for s in steps:
            for ch, value in s.channels.items():
                desired[ch] = copy.deepcopy(value)
                if ch == PRESETS_CHANNEL:
                    continue  # presets are not observable
                if s.op == "adopt":
                    observed[ch] = copy.deepcopy((s.prior or {}).get(ch))
                elif path == ENVIRONMENT_PATH:
                    observed[ch] = self.ops.observe_environment()
                else:
                    if fresh is None:
                        assert node is not None  # only the environment has no node
                        fresh = self.ops.observe(node, self.desired[path].kind)
                    observed[ch] = fresh.get(ch)
        if prev is None:
            return self.record(path, desired, observed)
        # keep provenance, group and done-log fields (v2) of the previous record,
        # except the preset resolutions when the presets changed (re-used by later
        # resolutions, spec 5)
        source = prev.source
        if any(PRESETS_CHANNEL in s.channels for s in steps) and path in self.desired:
            presets = (self.desired[path].create.get("source") or {}).get("presets")
            if presets is not None:
                source = dict(copy.deepcopy(prev.source or {}), presets=copy.deepcopy(presets))
        return dataclasses.replace(prev, recipe_id=self.recipe_id,
                                   recipe_version=self.recipe_version,
                                   desired=desired, observed=observed, source=source)

    def write_manifest(self) -> None:
        gone = {s.path for s in self.deleted_steps} | self.released
        built = set(self.created) | set(self.taken)
        entities = [p for p in self.live.entities if p not in gone or p in built]
        entities += [p for p in (*self.created, *self.taken) if p not in entities]
        new = Manifest(self.recipe_id, tuple(entities), self.env_record,
                       tuple(self.plan.tombstones))
        old = self.live.manifest
        if not self.plan.steps and old is not None and (
                set(old.entities), old.environment, set(old.deleted)) == (
                set(new.entities), new.environment, set(new.deleted)):
            return  # the apply changed nothing: skip the write
        self.context = "writing the recipe manifest"
        self.ops.write_manifest(new)
        self.context = ""

    # ── driver ────────────────────────────────────────────────────────────────

    def run(self) -> ApplyResult:
        plan = self.plan
        mutations = [s for s in plan.steps if s.op not in _REMOVAL_OPS]
        removals = [s for s in plan.steps if s.op in _REMOVAL_OPS]
        try:
            for step in mutations:
                self.current = step
                self.perform(step)
            self.current = None
            self.write_records(mutations)
            for step in removals:
                self.current = step
                self.perform(step)
            self.current = None
            if self.verify is not None:
                self.context = "scene check"
                self.check = self.verify()
                if not self.check.ok:
                    raise _CheckFailed(self.check)
                self.context = ""
            self.write_manifest()
        except Exception as e:  # noqa: BLE001 - any failure triggers compensation
            return self.rollback(e)
        return ApplyResult(True, plan.steps, plan.conflicts, plan.warnings, plan.overwritten,
                           plan.kept, check=self.check)

    def rollback(self, exc: Exception) -> ApplyResult:
        errors: list[str] = []
        for label, fn in reversed(self.journal):
            try:
                fn()
            except Exception as e:  # noqa: BLE001 - reported, never raised
                errors.append(f"{label}: {e}")
        error = str(exc) if self.current is not None or not self.context else f"{self.context}: {exc}"
        partial = tuple(RecipeIssue(
            path=s.path, code="deleted_not_restored",
            message=f"{s.path} (node {s.node_name!r}) was deleted before the apply failed; "
                    "deletions cannot be rolled back.") for s in self.deleted_steps)
        lost = [(s, items) for s, items in self.unfits_run if items]
        partial += tuple(RecipeIssue(
            path=s.path, code="unrestorable_removal",
            message=f"{', '.join(repr(r.get('label')) for r in items)} removed by {s.path} "
                    "before the apply failed could not be restored (no source file, or "
                    "the reload failed).") for s, items in lost)
        steps = tuple(s for s in self.plan.steps
                      if s in self.deleted_steps or any(s is u for u, _ in lost))
        return ApplyResult(False, steps, self.plan.conflicts,
                           self.plan.warnings + partial, (), (), rolled_back=True,
                           failed_step=self.current, error=error, rollback_errors=tuple(errors),
                           check=self.check)


def execute(plan: RecipePlan, desired: dict[str, DesiredEntity], live: LiveState, ops: SceneOps,
            *, recipe_id: str, recipe_version: int,
            verify: Callable[[], CheckReport] | None = None) -> ApplyResult:
    """Run *plan* through *ops*; roll back by compensation on any failure.

    *verify*, when given, runs after every step (deletes included) and before
    the manifest is written; a report with errors rolls the apply back like any
    other failure (deletes stay done, as ``deleted_not_restored`` warnings).

    A blocked plan executes nothing and writes nothing (no records, no manifest).
    """
    if plan.blocked:
        return ApplyResult(False, (), plan.conflicts, plan.warnings, (), ())
    return _Run(plan, desired, live, ops, recipe_id, recipe_version, verify).run()
