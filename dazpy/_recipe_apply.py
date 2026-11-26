"""Executor for scene-recipe plans with compensating rollback (spec §5.4).

:func:`execute` runs a :class:`RecipePlan` through a :class:`SceneOps`.  Every
mutation is journaled with its compensation; on any failure the journal is
walked in reverse, so a failed apply leaves the scene as it was (dazpy's
``UndoGroup`` cannot revert, so this is real compensation).

Order of work:

1. ``create`` / ``modify`` / ``set_environment`` / ``adopt`` / ``release``
   steps;
2. ownership records for every created, modified or adopted entity;
3. ``unparent`` / ``delete`` steps (irreversible, so after everything that can
   still fail and be undone);
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
from dataclasses import dataclass
from functools import partial
from typing import Any
from collections.abc import Callable

from ._recipe_desired import DesiredEntity
from ._recipe_diff import CREATE_KEY, ENVIRONMENT_PATH, Conflict, RecipePlan, Step
from ._recipe_json import to_jsonable
from ._recipe_ops import SceneOps
from ._recipe_store import EntityRecord, LiveState, Manifest
from ._recipe_validate import RecipeIssue
from ._scene_check import CheckReport

_ENV_CHANNEL = "environment"
_REMOVAL_OPS = ("unparent", "delete")


@dataclass(frozen=True)
class ApplyResult:
    """Outcome of :func:`execute`.

    ``steps`` are the steps in effect afterwards: every plan step on success;
    after a rollback, only the deletes that ran (they cannot be undone), and
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
        self.journal: list[tuple[str, Callable[[], None]]] = []
        self.created: dict[str, list[str]] = {}
        self.deleted_steps: list[Step] = []
        self.deleted_nodes: set[str] = set()
        self.released: set[str] = set()
        self.current: Step | None = None
        self.context = ""
        self.env_record = live.manifest.environment if live.manifest else None

    def undo(self, label: str, fn: Callable[[], None]) -> None:
        self.journal.append((label, fn))

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
        elif step.op == "release":
            entity = self.live.entities[step.path]
            node, prev = step.node, entity.record
            self.undo(f"restore the ownership record of {step.path} on {node!r}",
                      lambda: ops.write_record(node, prev))
            ops.remove_record(node)
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
            ops.delete(step.node, owner_recipe=self.recipe_id)
            self.deleted_nodes.add(step.node)
            self.deleted_steps.append(step)
        # adopt: nothing to write to Studio; handled by write_records

    # ── records / manifest ────────────────────────────────────────────────────

    def record(self, path: str, desired: dict, observed: dict,
               native: tuple[str, ...] = ()) -> EntityRecord:
        return EntityRecord(self.recipe_id, path, self.recipe_version, desired, observed, native)

    def write_records(self, steps: list[Step]) -> None:
        by_path: dict[str, list[Step]] = {}
        for s in steps:
            if s.op in ("create", "modify", "set_environment", "adopt"):
                by_path.setdefault(s.path, []).append(s)
        for path, path_steps in by_path.items():
            self.context = f"writing the ownership record for {path}"
            if path == ENVIRONMENT_PATH:
                self.env_record = self.merged(path, path_steps, self.env_record, None)
            elif path in self.created:
                self.write_created(path)
            else:
                entity = self.live.entities[path]
                new = self.merged(path, path_steps, entity.record, entity.node_name)
                node, prev = entity.node_name, entity.record
                self.undo(f"restore the ownership record of {path} on {node!r}",
                          partial(self.ops.write_record, node, prev))
                self.ops.write_record(node, new)
        self.context = ""

    def write_created(self, path: str) -> None:
        d = self.desired[path]
        node = self.created[path][0]
        desired = copy.deepcopy(d.channels)
        desired[CREATE_KEY] = copy.deepcopy(d.create)
        self.ops.write_record(node, self.record(path, desired, self.ops.observe(node, d.kind),
                                                self.ops.native_descendants(node)))

    def merged(self, path: str, steps: list[Step], prev: EntityRecord | None,
               node: str | None) -> EntityRecord:
        """*prev* with the channels *steps* changed replaced (per-channel merge)."""
        desired: dict[str, Any] = copy.deepcopy(prev.desired) if prev else {}
        observed: dict[str, Any] = copy.deepcopy(prev.observed) if prev else {}
        fresh: dict | None = None
        for s in steps:
            for ch, value in s.channels.items():
                desired[ch] = copy.deepcopy(value)
                if s.op == "adopt":
                    observed[ch] = copy.deepcopy((s.prior or {}).get(ch))
                elif path == ENVIRONMENT_PATH:
                    observed[ch] = self.ops.observe_environment()
                else:
                    if fresh is None:
                        assert node is not None  # only the environment has no node
                        fresh = self.ops.observe(node, self.desired[path].kind)
                    observed[ch] = fresh.get(ch)
        return self.record(path, desired, observed, prev.native if prev else ())

    def write_manifest(self) -> None:
        gone = {s.path for s in self.deleted_steps} | self.released
        entities = [p for p in self.live.entities if p not in gone or p in self.created]
        entities += [p for p in self.created if p not in entities]
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
        return ApplyResult(False, tuple(self.deleted_steps), self.plan.conflicts,
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
