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
- ``unparent``: move ``channels["children"]["names"]`` to scene root
  (preserving world transform) before the entity's ``delete``.
- ``delete``: delete the node (runs last; cannot be rolled back).

Conflict paths are ``<entity path>.<channel>`` for ``modified`` and the entity
path for the other kinds; ``resolutions`` are keyed the same way.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

from ._pose import DazPose
from ._recipe_desired import DesiredEntity
from ._recipe_store import LiveEntity, LiveState
from ._recipe_validate import RecipeIssue
from ._scene_state import _DEFAULT_VERIFY_TOLERANCE, _pose_mismatches

OnConflict = Literal["ask", "recipe_wins", "scene_wins"]
Resolution = Literal["recipe", "scene"]
ConflictKind = Literal["modified", "removed_from_recipe", "deleted_in_scene", "has_foreign_children"]
StepOp = Literal["create", "modify", "set_environment", "adopt", "unparent", "delete"]

ENVIRONMENT_PATH = "lighting.environment"
_ENVIRONMENT_CHANNEL = "environment"
_POSE_CHANNEL = "pose"
_MAX_DRIFTED = 5
# Channels where desired and observed are directly comparable key-by-key, so
# "live already equals desired" can be detected (controller ruling 3).
_NO_SHORTCUT_CHANNELS = (_POSE_CHANNEL, _ENVIRONMENT_CHANNEL)
_STEP_ORDER: dict[str, int] = {op: i for i, op in enumerate(
    ("create", "modify", "set_environment", "adopt", "unparent", "delete"))}


@dataclass(frozen=True)
class Conflict:
    path: str
    kind: ConflictKind
    desired: object
    base: object
    live: object


@dataclass(frozen=True)
class Step:
    op: StepOp
    path: str
    channels: dict[str, dict]
    prior: dict[str, dict] | None
    node_name: str | None


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
    """Drifted pose channels between two observed ``{"snapshot": ...}`` values."""
    if not (isinstance(base, dict) and isinstance(live, dict)
            and "snapshot" in base and "snapshot" in live):
        return [] if base == live else ["pose snapshot missing"]
    return _pose_mismatches(DazPose(**base["snapshot"]), DazPose(**live["snapshot"]), tol)


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

    def resolution_for(self, path: str) -> Resolution | None:
        if path in self.resolutions:
            return self.resolutions[path]
        return {"recipe_wins": "recipe", "scene_wins": "scene"}.get(self.on_conflict)

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

    def present(self, path: str, d: DesiredEntity, live: LiveState, owned: set,
                tombstoned: set) -> None:
        entity = live.entities.get(path)
        if entity is not None:
            r = entity.record
            self.compare(d, path, r.desired, r.observed, entity.observed, entity.node_name, "modify")
        elif path in tombstoned:
            if self.resolution_for(path) == "recipe":
                self.step("create", path, d.channels, None, None)
            else:
                self.tombstones.append(path)
                self.warn(path, "hand_deleted_kept",
                          f"{path} was deleted in the scene earlier and that deletion was accepted; "
                          "not recreating it.")
        elif path in owned:
            res = self.conflict(Conflict(path, "deleted_in_scene", d.channels, None, None))
            if res == "recipe":
                self.step("create", path, d.channels, None, None)
            elif res == "scene":
                self.tombstones.append(path)
        else:
            self.step("create", path, d.channels, None, None)

    def removed(self, entity: LiveEntity) -> None:
        path = entity.path
        if entity.foreign_children:
            res = self.conflict(Conflict(path, "has_foreign_children", None, entity.record.desired,
                                         {"foreign_children": list(entity.foreign_children)}))
            if res == "recipe":
                self.step("unparent", path, {"children": {"names": list(entity.foreign_children)}},
                          None, entity.node_name)
                self.step("delete", path, {}, None, entity.node_name)
            elif res == "scene":
                self.removed_kept(path)
        elif _tweaked_channels(entity, self.tol):
            res = self.conflict(Conflict(path, "removed_from_recipe", None, entity.record.desired,
                                         entity.observed))
            if res == "recipe":
                self.step("delete", path, {}, None, entity.node_name)
            elif res == "scene":
                self.removed_kept(path)
        else:
            self.step("delete", path, {}, None, entity.node_name)

    def removed_kept(self, path: str) -> None:
        self.warn(path, "removed_entity_kept",
                  f"{path} was removed from the recipe but kept in the scene.")

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


def diff(desired: dict[str, DesiredEntity], live: LiveState, *, on_conflict: OnConflict = "ask",
         resolutions: Mapping[str, Resolution] | None = None,
         tolerance: float = _DEFAULT_VERIFY_TOLERANCE) -> RecipePlan:
    """Plan an apply of *desired* onto *live* under the caller's conflict policy.

    Under ``ask``, any conflict not covered by *resolutions* blocks the whole
    plan: ``blocked=True`` and no steps (all conflicts and warnings are still
    reported).
    """
    p = _Planner(on_conflict, resolutions, tolerance)
    manifest = live.manifest
    owned = set(manifest.entities) if manifest else set()
    owned |= set(live.entities)
    tombstoned = set(manifest.deleted) if manifest else set()

    for path, d in desired.items():
        if path != ENVIRONMENT_PATH:
            p.present(path, d, live, owned, tombstoned)
    for path, entity in live.entities.items():
        if path not in desired:
            p.removed(entity)
    p.environment(desired.get(ENVIRONMENT_PATH), live)

    blocked = on_conflict == "ask" and any(c.path not in p.resolutions for c in p.conflicts)
    if blocked:
        return RecipePlan((), tuple(p.conflicts), tuple(p.warnings), True, (), (), ())
    steps = tuple(sorted(p.steps, key=lambda s: _STEP_ORDER[s.op]))
    return RecipePlan(steps, tuple(p.conflicts), tuple(p.warnings), False,
                      tuple(p.overwritten), tuple(p.kept), tuple(p.tombstones))
