"""Scene recipes: validate, plan, apply and observe a declarative scene description.

A :class:`~dazpy._recipe_model.SceneRecipe` (or its dict form, see
:func:`recipe_schema`) describes the desired scene. This module is the public
facade over the layers below it:

- :func:`validate` - offline checks, plus (given a scene) that every asset,
  pose and HDRI file exists;
- :func:`plan` - what an apply would do, without touching the scene;
- :func:`apply` - validate, re-read the live scene, diff, execute with rollback;
- :func:`observe` - how the scene differs from the recipe now;
- :func:`check` - pre-render checks (framing, lighting) for the recipe's shots;
- :func:`render` - render the recipe's shots from an applied scene;
- :func:`pin` - the recipe with every asset reference's resolution filled in.

Recipes using v2 asset features (``find`` / ``product`` / ``sku`` references,
pins, taken-over actors, presets, ``wearing``) go through the v2 pipeline (spec
section 8): references are resolved (re-using the resolution recorded on the
scene's nodes while a reference is unchanged), presets and fitted items are
checked against their actor's figure from asset metadata, and any resolution,
compatibility or wearing error raises :class:`RecipeValidationError` before the
scene changes. Other recipes run exactly as in v1: no finder, no compatibility
read.

Every result type has a JSON-safe ``to_dict()``.
"""

from __future__ import annotations

import dataclasses
import functools
import json
import os
from dataclasses import dataclass
from importlib import resources
from typing import TYPE_CHECKING
from collections.abc import Mapping, Sequence

from urllib.parse import unquote

from ._asset_compat import check_compat, check_preset_types, is_compatible, read_compat
from ._asset_finder import AssetCandidate, AssetFinder, select_finder
from ._asset_ref import AssetRef, ResolvedPin
from ._asset_resolve import ResolvedAsset, recipe_refs, resolve_refs
from ._recipe_apply import ApplyResult, execute
from . import _render_api as render_api
from ._recipe_desired import DesiredEntity, compute_desired
from ._recipe_diff import (Conflict, OnConflict, RecipePlan, Resolution, diff, is_item_path,
                           item_actor)
from ._recipe_fitted import FigureInfo, read_figure_labels, read_figures
from ._recipe_json import to_jsonable
from ._recipe_model import AssetSpec, SceneRecipe
from ._recipe_wearing import WearingPlan, plan_wearing
from ._recipe_ops import DazSceneOps, is_local_pose_file, resolve_files
from ._recipe_store import LiveState, read_live
from ._recipe_validate import RecipeIssue, ValidationReport, file_not_found, validate_offline
from ._render_api import RenderResult
from ._scene_check import (CheckFinding, CheckReport, engine_name, findings_for_camera, gather,
                           lighting_findings)
from ._client import DazClient
from ._script_builder import ScriptBuilder
from .exceptions import RecipeNotAppliedError, RecipeValidationError, SceneCheckError

if TYPE_CHECKING:
    from ._scene import DazScene

__all__ = ["ObserveReport", "ShotRender", "apply", "check", "observe", "pin", "plan",
           "recipe_schema", "render", "validate"]

_SCHEMA_VERSIONS = (1, 2)


@dataclass(frozen=True)
class ObserveReport:
    """How the scene stands against a recipe.

    ``applied``: the recipe has a manifest in the scene. ``drift``: hand edits
    kept (``hand_tweak_kept``), hand deletions (``deleted_in_scene``) and fitted
    items whose node now comes from another file than the one recorded
    (``source_changed``, e.g. swapped by hand).
    ``pending``: what an apply would change if the recipe won every conflict
    (``<entity>.<channel>`` for modified/environment channels, the entity path
    for creates, releases, unparents and deletes). ``in_sync``: applied, with no pending
    change, drift or conflict.
    """

    applied: bool
    in_sync: bool
    drift: tuple[RecipeIssue, ...]
    pending: tuple[str, ...]
    conflicts: tuple[Conflict, ...]

    def to_dict(self) -> dict:
        return to_jsonable(self)


# How long one recipe call waits out a busy Studio (Studio 6 reports busy for a
# moment after a load or clear while it streams in background content; failing
# there would roll an apply back halfway).
RECIPE_BUSY_WAIT_S = 120.0


def _patient(fn):
    """Run *fn* with its scene's client waiting out busy replies (see
    :meth:`DazClient.waiting_out_busy`).  The scene is the second argument."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        scene = args[1] if len(args) > 1 else kwargs.get("scene")
        client = getattr(scene, "_client", None)
        if not isinstance(client, DazClient):
            return fn(*args, **kwargs)
        with client.waiting_out_busy(RECIPE_BUSY_WAIT_S):
            return fn(*args, **kwargs)
    return wrapper


def recipe_schema(version: int = 1) -> dict:
    """The JSON Schema for recipe documents of *version* (shipped as package data)."""
    if version not in _SCHEMA_VERSIONS:
        raise ValueError(f"unsupported recipe schema version {version!r}; "
                         f"available: {', '.join(map(str, _SCHEMA_VERSIONS))}")
    text = (resources.files("dazpy") / "schemas" / f"scene-recipe.v{version}.schema.json"
            ).read_text(encoding="utf-8")
    return json.loads(text)


def _as_dict(recipe: SceneRecipe | dict) -> dict:
    return recipe.to_dict() if isinstance(recipe, SceneRecipe) else recipe


def _file_refs(recipe: SceneRecipe, *, assets: bool = True) -> list[tuple[str, str]]:
    """``(recipe path, file)`` for every file the recipe makes Studio open.

    Without *assets* only poses and the HDRI (the v2 pipeline resolves asset
    references itself)."""
    refs = [(f"assets.{k}.path", a.ref.path) for k, a in recipe.assets.items()
            if assets and a.ref.path is not None]
    refs += [(f"actors.{k}.pose", a.pose) for k, a in recipe.actors.items() if a.pose]
    if recipe.environment is not None:
        refs.append(("lighting.environment.image_path", recipe.environment.image_path))
    return refs


def _missing_files(model: SceneRecipe, scene: DazScene, *,
                   assets: bool = True) -> tuple[RecipeIssue, ...]:
    """``file_not_found`` for every file of :func:`_file_refs` Studio cannot find."""
    refs = _file_refs(model, assets=assets)
    if not refs:
        return ()
    local = {f for path, f in refs if path.endswith(".pose") and is_local_pose_file(f)}
    found = resolve_files(scene._client, [f for _, f in refs if f not in local])
    found.update({f: f if os.path.isfile(f) else "" for f in local})
    return tuple(file_not_found(path, f) for path, f in refs if not found.get(f))


# ── v2 pipeline: resolve, figures, compatibility ──────────────────────────────

def _uses_v2(model: SceneRecipe) -> bool:
    """Every ``recipe_version: 2`` recipe takes the v2 pipeline (so inline asset
    paths are resolved, i.e. existence-checked); v1 recipes keep the v1 path."""
    return model.recipe_version >= 2


class _LazyFinder:
    """An :class:`AssetFinder` that picks the real one (:func:`select_finder`,
    which may probe the content browser) only when a reference needs it.

    ``name`` is ``"path"`` until then; ``warnings`` collects ``finder_fallback``.
    """

    def __init__(self, client: DazClient, explicit: AssetFinder | None) -> None:
        self._client, self._explicit = client, explicit
        self._finder: AssetFinder | None = None
        self.warnings: list[RecipeIssue] = []

    @property
    def name(self) -> str:
        return self._finder.name if self._finder is not None else "path"

    # Per-search state of the real finder, read by resolution after each search
    # (``search_incomplete``, truncated results); False until one is picked.
    @property
    def timed_out(self) -> bool:
        return bool(getattr(self._finder, "timed_out", False))

    @property
    def truncated(self) -> bool:
        return bool(getattr(self._finder, "truncated", False))

    def _get(self) -> AssetFinder:
        if self._finder is None:
            self._finder, issues = select_finder(self._client, self._explicit)
            self.warnings.extend(issues)
        return self._finder

    def search(self, phrase: str, *, type: str | None, limit: int = 10) -> list[AssetCandidate]:
        return self._get().search(phrase, type=type, limit=limit)

    def product_files(self, *, sku: str | None = None,
                      product: str | None = None) -> list[AssetCandidate]:
        return self._get().product_files(sku=sku, product=product)


def _prior(live: LiveState) -> dict[str, dict]:
    """Recorded resolutions (``EntityRecord.source``) keyed like :func:`recipe_refs`."""
    out: dict[str, dict] = {}
    for path, entity in live.entities.items():
        source = entity.record.source
        if not source:
            continue
        if is_item_path(path):
            out[path] = source
            continue
        if source.get("path"):
            out[f"{path}.asset"] = source
        for i, preset in enumerate(source.get("presets") or ()):  # actor records, by index
            if isinstance(preset, dict):
                out[f"{path}.presets[{i}]"] = preset
    return out


@dataclass
class _Checked:
    """What the v2 pipeline learned before planning (see :func:`_resolve_and_check`)."""

    resolved: dict[str, ResolvedAsset]
    figures: dict[str, list[FigureInfo]]
    errors: list[RecipeIssue]
    warnings: list[RecipeIssue]
    finder: str


def _resolve(client: DazClient, model: SceneRecipe, live: LiveState,
             finder: AssetFinder | None) -> _Checked:
    """Resolve every reference; the figures involved are read first, so a
    ``find`` for an actor's preset or item is narrowed by that figure's base."""
    labels, owned = _figure_keys(model, live)
    figures = read_figures(client, labels, owned) if labels or owned else {}
    lazy = _LazyFinder(client, finder)
    report = resolve_refs(client, recipe_refs(model), lazy, _prior(live),
                          narrow=_find_narrower(client, model, live, figures))
    return _Checked(dict(report.resolved), figures, list(report.errors),
                    lazy.warnings + list(report.warnings), lazy.name)


def _find_narrower(client: DazClient, model: SceneRecipe, live: LiveState,
                   figures: Mapping[str, list[FigureInfo]]):
    """The :data:`~dazpy._asset_resolve.Narrower` for *model* (spec 5).

    The target base is the actor's live figure's, else (an actor to be created)
    the base its asset file provides.  One ``read_compat`` per narrowed ``find``
    answers its candidates and, the first time, the actor asset's base."""
    provides: dict[str, str | None] = {}

    def narrow(p: str, cands: list, known: Mapping[str, str]):
        key = p.split(".")[1] if p.startswith("actors.") and not p.endswith(".asset") else None
        if key is None or key not in model.actors:
            return cands, (), None
        figs = _actor_figures(model, key, live, figures)
        target, asset = None, None
        if len(figs) == 1:
            target = figs[0].compat_base
        elif not figs:
            asset = known.get(f"actors.{key}.asset")
        if not target and asset is None:
            return cands, (), None
        paths = {c.path for c in cands}
        if asset is not None and asset not in provides:
            paths.add(asset)
        info = read_compat(client, sorted(paths))
        if asset is not None:
            if asset not in provides:
                provides[asset] = info[asset].provides
            target = provides[asset]
        if not target:
            return cands, (), None
        kept, dropped = [], []
        for c in cands:
            ci = info[c.path]
            if ci.known and not is_compatible(target, ci.bases):
                dropped.append((c, ci.bases))
            else:
                kept.append(c)
        return kept, dropped, target

    return narrow


def _figure_keys(model: SceneRecipe, live: LiveState) -> tuple[list[str], list[str]]:
    """``(labels, owned node names)`` the pipeline needs figures for: take-over
    labels of actors not owned yet, and owned actors with presets / wearing or
    fitted items in the scene."""
    labels = sorted({a.node for k, a in model.actors.items()
                     if a.node is not None and f"actors.{k}" not in live.entities})
    actors = {f"actors.{k}" for k, a in model.actors.items() if a.node or a.presets or a.wearing}
    actors |= {item_actor(p) for p in live.entities if is_item_path(p)}
    owned = sorted({live.entities[a].node_name for a in actors if a in live.entities})
    return labels, owned


def _actor_figures(model: SceneRecipe, key: str, live: LiveState,
                   figures: Mapping[str, list[FigureInfo]]) -> list[FigureInfo]:
    entity = live.entities.get(f"actors.{key}")
    if entity is not None:
        return [f for f in figures.get(entity.node_name, []) if f.is_node(entity.node_name)]
    node = model.actors[key].node
    return list(figures.get(node, [])) if node is not None else []


def _item_keys(model: SceneRecipe, key: str) -> list[str]:
    """The resolution keys of actor *key*'s presets and fitted items (as recipe_refs)."""
    actor = model.actors[key]
    return [f"actors.{key}.presets[{i}]" for i in range(len(actor.presets))] + [
        f"actors.{key}.wearing.{w.key}" for w in actor.wearing
        if w.op in ("add", "replace") and w.ref is not None]


def _resolve_and_check(client: DazClient, model: SceneRecipe, live: LiveState,
                       finder: AssetFinder | None, *, compat: bool = True) -> _Checked:
    """Resolve every reference, read the figures involved, and (with *compat*)
    check each actor's presets and fitted items against its figure's base."""
    chk = _resolve(client, model, live, finder)
    if not compat:
        return chk
    items = {k: {p: chk.resolved[p] for p in _item_keys(model, k) if p in chk.resolved}
             for k in model.actors}
    items = {k: v for k, v in items.items() if v}
    if not items:
        return chk
    # One metadata read answers the items' compatibilities and, for actors to be
    # created, the base their figure file provides.
    figure_base: dict[str, str | None] = {}
    from_asset: dict[str, str] = {}
    for key in items:
        figs = _actor_figures(model, key, live, chk.figures)
        asset = chk.resolved.get(f"actors.{key}.asset")
        if len(figs) == 1:
            figure_base[key] = figs[0].compat_base
        elif figs or asset is None:
            figure_base[key] = None  # ambiguous take-over (reported by the wearing plan) / unknown
        else:
            from_asset[key] = asset.path
    paths = {r.path for v in items.values() for r in v.values()} | set(from_asset.values())
    info = read_compat(client, sorted(paths))
    for key, path in from_asset.items():
        figure_base[key] = info[path].provides
    for key, its in items.items():
        errors, warnings = check_compat(figure_base[key], its, info)
        chk.errors += errors
        chk.warnings += warnings
        errors, warnings = check_preset_types(
            {p: r for p, r in its.items() if ".presets[" in p}, info)
        chk.errors += errors
        chk.warnings += warnings
    return chk


def _raise_if(errors: Sequence[RecipeIssue], warnings: Sequence[RecipeIssue]) -> None:
    if errors:
        raise RecipeValidationError(ValidationReport(ok=False, errors=tuple(errors),
                                                     warnings=tuple(warnings)))


# ── validate / plan / apply / observe ─────────────────────────────────────────

@_patient
def validate(recipe: SceneRecipe | dict, scene: DazScene | None = None, *,
             finder: AssetFinder | None = None) -> ValidationReport:
    """Validate *recipe*; with *scene*, also check its files exist (one Studio script).

    Adds ``file_not_found`` at ``assets.<k>.path``, ``actors.<k>.pose`` and
    ``lighting.environment.image_path``. The existence check is skipped while the
    recipe has offline errors. Files are resolved on the Studio host in one script
    (content paths through the content manager), except dazpy pose ``.json``
    files: ``poses.apply_pose`` reads those on the client, so they are checked
    there. Raises :class:`~dazpy.exceptions.DazError` if Studio returns no
    result for the check.

    For a recipe using v2 asset features, with *scene*, also resolves every
    asset reference (through *finder*, else the content browser named by
    ``DAZ_BROWSER_URL`` when reachable, else Studio's content database) and
    checks presets and fitted items against their actor's figure: resolution
    errors (``asset_not_found``, ``ambiguous_asset``,
    ``content_database_unavailable``), ``incompatible_asset`` errors and
    ``compatibility_unknown`` / ``finder_fallback`` / ``pin_*`` warnings. A
    created actor's base comes from its asset's metadata; a taken-over one's
    from the live figure. Asset files are reported by the resolution (at the
    reference's path, e.g. ``actors.<k>.asset``), not as ``file_not_found``.
    """
    report = validate_offline(_as_dict(recipe))
    if scene is None or not report.ok:
        return report
    model = recipe if isinstance(recipe, SceneRecipe) else SceneRecipe.from_dict(recipe)
    v2 = _uses_v2(model)
    missing = _missing_files(model, scene, assets=not v2)
    if not v2:
        if not missing:
            return report
        return ValidationReport(ok=False, errors=report.errors + missing, warnings=report.warnings)
    chk = _resolve_and_check(scene._client, model, read_live(scene._client, model.id), finder)
    errors = report.errors + missing + tuple(chk.errors)
    return ValidationReport(ok=not errors, errors=errors,
                            warnings=report.warnings + tuple(chk.warnings))


def _checked(recipe: SceneRecipe | dict, scene: DazScene | None) -> SceneRecipe:
    report = validate(recipe, scene)
    if not report.ok:
        raise RecipeValidationError(report)
    return recipe if isinstance(recipe, SceneRecipe) else SceneRecipe.from_dict(recipe)


def _read(model: SceneRecipe, scene: DazScene) -> tuple[dict, LiveState]:
    return compute_desired(model), read_live(scene._client, model.id)


def _plan(model: SceneRecipe, scene: DazScene, on_conflict: OnConflict,
          resolutions: Mapping[str, Resolution] | None, finder: AssetFinder | None
          ) -> tuple[RecipePlan, dict[str, DesiredEntity], LiveState]:
    """The plan for *model* (offline-valid) against the scene now, with the
    desired state and live state it was made from."""
    if not _uses_v2(model):
        desired, live = _read(model, scene)
        return diff(desired, live, on_conflict=on_conflict, resolutions=resolutions), desired, live
    client = scene._client
    live = read_live(client, model.id)
    chk = _resolve_and_check(client, model, live, finder)
    labels, _ = _figure_keys(model, live)
    unmatched = any(not chk.figures.get(label) for label in labels)
    wearing = plan_wearing(model, chk.figures, live,
                           read_figure_labels(client) if unmatched else ())
    _raise_if(chk.errors + list(wearing.errors), chk.warnings + list(wearing.warnings))
    desired = compute_desired(model, chk.resolved)
    p = diff(desired, live, on_conflict=on_conflict, resolutions=resolutions, wearing=wearing)
    # diff already carries the wearing warnings
    return (dataclasses.replace(p, warnings=tuple(chk.warnings) + p.warnings, finder=chk.finder),
            desired, live)


@_patient
def plan(recipe: SceneRecipe | dict, scene: DazScene, *, on_conflict: OnConflict = "ask",
         resolutions: Mapping[str, Resolution] | None = None,
         finder: AssetFinder | None = None) -> RecipePlan:
    """What :func:`apply` would do now. Reads the scene, changes nothing.

    Raises :class:`RecipeValidationError` for an offline-invalid recipe and, for
    a v2 recipe, for any resolution, compatibility or wearing error (see
    :func:`validate`); does not check that pose / HDRI files exist (that is
    :func:`validate` / :func:`apply`). ``RecipePlan.finder`` names the finder
    that answered (``"path"`` when no reference needed one); resolution and
    compatibility warnings are in ``RecipePlan.warnings``.
    """
    model = _checked(recipe, None)
    return _plan(model, scene, on_conflict, resolutions, finder)[0]


@_patient
def apply(recipe: SceneRecipe | dict, scene: DazScene, *, on_conflict: OnConflict = "ask",
          resolutions: Mapping[str, Resolution] | None = None,
          finder: AssetFinder | None = None, require_clean: bool = False) -> ApplyResult:
    """Apply *recipe* to *scene*, re-planning against the scene's current state.

    Raises :class:`RecipeValidationError` (before touching the scene) when the
    recipe is invalid offline or names a missing file, or (v2) has any
    resolution, compatibility or wearing error (see :func:`plan`). A conflict under
    ``on_conflict="ask"`` returns ``applied=False`` with the conflicts and writes
    nothing; a failure part-way rolls back (see :class:`ApplyResult`).

    With *require_clean*, :func:`check` runs on the applied scene before the
    manifest is written; errors roll the apply back (``applied=False``,
    ``rolled_back=True``) and ``ApplyResult.check`` holds the report either way.
    """
    report = validate_offline(_as_dict(recipe))
    if not report.ok:
        raise RecipeValidationError(report)
    model = recipe if isinstance(recipe, SceneRecipe) else SceneRecipe.from_dict(recipe)
    missing = _missing_files(model, scene, assets=not _uses_v2(model))
    _raise_if(report.errors + missing, report.warnings)
    the_plan, desired, live = _plan(model, scene, on_conflict, resolutions, finder)
    verify = (lambda: _check_shots(model, read_live(scene._client, model.id), scene._client,
                                   model.shots)) if require_clean else None
    return execute(the_plan, desired, live, DazSceneOps(scene),
                   recipe_id=model.id, recipe_version=model.recipe_version, verify=verify)


_PENDING_NODE_OPS = ("create", "take_over", "fit", "unfit", "preset", "release", "unparent",
                     "delete")


def _pending(the_plan: RecipePlan) -> tuple[str, ...]:
    out: list[str] = []
    for s in the_plan.steps:
        if s.op in ("modify", "set_environment"):
            out += [f"{s.path}.{ch}" for ch in s.channels]
        elif s.op in _PENDING_NODE_OPS:
            out.append(s.path)
    return tuple(dict.fromkeys(out))


@_patient
def observe(recipe: SceneRecipe | dict, scene: DazScene, *,
            finder: AssetFinder | None = None) -> ObserveReport:
    """Compare *scene* with *recipe* without changing anything.

    Diffs as if the recipe won every conflict, except that hand deletions
    already accepted (tombstoned in the manifest) stay accepted: they are not
    pending recreates. A recipe-owned fitted item whose node now comes from
    another file than its recorded source is ``source_changed`` drift. Raises
    :class:`RecipeValidationError` when a v2 reference cannot be resolved.
    """
    model = _checked(recipe, None)
    return _observe(model, scene, finder)[0]


def _observe(model: SceneRecipe, scene: DazScene,
             finder: AssetFinder | None) -> tuple[ObserveReport, dict, LiveState]:
    """The observation, with the desired and live state it compares."""
    if not _uses_v2(model):
        desired, live = _read(model, scene)
        return _observation(desired, live), desired, live
    client = scene._client
    live = read_live(client, model.id)
    chk = _resolve_and_check(client, model, live, finder, compat=False)
    _raise_if(chk.errors, chk.warnings)
    wearing = plan_wearing(model, chk.figures, live)
    desired = compute_desired(model, chk.resolved)
    # an observation reports, it never refuses: wearing errors only stop plan/apply
    report = _observation(desired, live, dataclasses.replace(wearing, errors=()))
    drift = _source_drift(live, chk.figures)
    if drift:
        report = dataclasses.replace(report, drift=report.drift + drift, in_sync=False)
    return report, desired, live


def _observation(desired: dict, live: LiveState,
                 wearing: WearingPlan | None = None) -> ObserveReport:
    accepted: dict[str, Resolution] = {p: "scene" for p in (live.manifest.deleted if live.manifest else ())
                if p in desired and p not in live.entities}
    p = diff(desired, live, on_conflict="recipe_wins", resolutions=accepted, wearing=wearing)
    drift = tuple(w for w in p.warnings if w.code == "hand_tweak_kept") + tuple(
        RecipeIssue(c.path, "deleted_in_scene",
                    f"{c.path} was deleted in the scene; apply would recreate it.")
        for c in p.conflicts if c.kind == "deleted_in_scene")
    pending = _pending(p)
    applied = live.manifest is not None
    return ObserveReport(applied=applied, in_sync=applied and not (pending or drift or p.conflicts),
                         drift=drift, pending=pending, conflicts=p.conflicts)


def _norm_file(path: str) -> str:
    return unquote(path).replace("\\", "/").strip().casefold()


def _same_file(live_uri: str, recorded: str) -> bool:
    """Do two ``getAssetUriForNode`` file parts name the same data file?"""
    return _norm_file(live_uri.split("#", 1)[0]) == _norm_file(recorded.split("#", 1)[0])


def _source_drift(live: LiveState, figures: Mapping[str, list[FigureInfo]]
                  ) -> tuple[RecipeIssue, ...]:
    """``source_changed`` for owned fitted items whose live data file differs from
    the one recorded at fit time (spec section 9). Gone items are
    ``deleted_in_scene`` instead.

    Both sides are ``getAssetUriForNode`` file parts (the node's ``.dsf``), never the
    ``.duf`` the recipe names (spec 15.2): a record without ``asset_uri`` (written
    before it was recorded) is never drift."""
    out: list[RecipeIssue] = []
    for path, entity in live.entities.items():
        if not is_item_path(path):
            continue
        actor = live.entities.get(item_actor(path))
        if actor is None:
            continue
        # the item under its own actor's figure: item node names repeat across figures
        item = next((it for f in figures.get(actor.node_name, []) if f.is_node(actor.node_name)
                     for it in f.items if it.name == entity.node_name), None)
        want = entity.record.asset_uri
        if not want or item is None or item.source_path is None:
            continue
        if not _same_file(item.source_path, want):
            out.append(RecipeIssue(
                path, "source_changed",
                f"{path} (node {entity.node_name!r}) now comes from {item.source_path!r}, "
                f"not the recorded {want!r}; it was swapped in the scene."))
    return tuple(out)


# ── pin ──────────────────────────────────────────────────────────────────────

def _pinned(ref: AssetRef, r: ResolvedAsset) -> AssetRef:
    return dataclasses.replace(ref, resolved=ResolvedPin(r.path, r.sku, r.product, r.asset_id))


def _pin_model(model: SceneRecipe, resolved: Mapping[str, ResolvedAsset]) -> SceneRecipe:
    assets = dict(model.assets)

    def pin_asset(value, rp: str):
        r = resolved.get(rp)
        if r is None or value is None:
            return value
        if isinstance(value, str):
            if value in model.assets:  # a key: pin the shared ``assets`` entry
                assets[value] = AssetSpec(_pinned(model.assets[value].ref, r))
                return value
            return _pinned(AssetRef(path=value), r)
        return _pinned(value, r)

    actors = {}
    for k, a in model.actors.items():
        presets = tuple(_pinned(ref, resolved[f"actors.{k}.presets[{i}]"])
                        for i, ref in enumerate(a.presets))
        wearing = tuple(
            dataclasses.replace(w, ref=_pinned(w.ref, resolved[f"actors.{k}.wearing.{w.key}"]))
            if w.op in ("add", "replace") and w.ref is not None else w for w in a.wearing)
        actors[k] = dataclasses.replace(a, asset=pin_asset(a.asset, f"actors.{k}.asset"),
                                        presets=presets, wearing=wearing)
    props = {k: dataclasses.replace(p, asset=pin_asset(p.asset, f"props.{k}.asset"))
             for k, p in model.props.items()}
    return dataclasses.replace(model, recipe_version=2, assets=assets, actors=actors, props=props)


@_patient
def pin(recipe: SceneRecipe | dict, scene: DazScene, *, finder: AssetFinder | None = None) -> dict:
    """*recipe* as a dict with every asset reference's ``resolved`` pin filled in.

    References resolve as in :func:`plan` (recorded resolutions first, then pins,
    then the finder); string references become objects. Pins are a v2 feature,
    so a v1 recipe comes back as ``recipe_version: 2``. Raises
    :class:`RecipeValidationError` when a reference cannot be resolved.
    """
    model = _checked(recipe, None)
    chk = _resolve(scene._client, model, read_live(scene._client, model.id), finder)
    _raise_if(chk.errors, chk.warnings)
    return _pin_model(model, chk.resolved).to_dict()


def _pick(model: SceneRecipe, shot, name: str):
    """A shot's render setting *name*, else the recipe's top-level one."""
    own = shot.render
    return (getattr(own, name, None) if own is not None else None) or getattr(model.render, name)


def _camera_label(model: SceneRecipe, live: LiveState, key: str) -> str:
    camera = live.entities.get(f"cameras.{key}")
    return camera.label if camera is not None and camera.label else f"{model.id}:{key}"


def _choose(model: SceneRecipe, shots: Sequence[str] | None) -> list:
    known = [s.id for s in model.shots]
    if shots is None:
        return list(model.shots)
    unknown = [i for i in dict.fromkeys(shots) if i not in known]
    if unknown:
        raise ValueError(f"unknown shot id(s): {', '.join(unknown)}; "
                         f"valid shot ids: {', '.join(known) or '(none)'}")
    wanted = set(shots)
    return [s for s in model.shots if s.id in wanted]


def _check_shots(model: SceneRecipe, live: LiveState, client, chosen: Sequence) -> CheckReport:
    """Framing per shot, lighting once per distinct result (one Studio script)."""
    labels = [_camera_label(model, live, s.camera) for s in chosen]
    data = gather(client, labels or [None])
    active = engine_name(data.get("engine"))
    framing: list[CheckFinding] = []
    lighting: dict[tuple, list] = {}
    for shot, cam in zip(chosen, data["cameras"]):
        res = _pick(model, shot, "resolution")
        framing += findings_for_camera(data, cam, aspect=res[0] / res[1] if res else None,
                                       allow_crop=shot.allow_crop, shot=shot.id)
        for f in lighting_findings(_pick(model, shot, "engine") or active, data["lights"],
                                   data.get("environment"), bool(cam.get("headlamp"))):
            lighting.setdefault((f.code, f.message), []).append((shot.id, f))
    if not chosen:
        for f in lighting_findings(active, data["lights"], data.get("environment")):
            lighting.setdefault((f.code, f.message), []).append((None, f))
    out = list(framing)
    for hits in lighting.values():
        if len(hits) == len(chosen) or not chosen:
            out.append(hits[0][1])  # every shot alike: report once, shot=None
        else:
            out += [dataclasses.replace(f, shot=sid) for sid, f in hits]
    return CheckReport(tuple(out))


@_patient
def check(recipe: SceneRecipe | dict, scene: DazScene, *,
          shots: Sequence[str] | None = None) -> CheckReport:
    """Pre-render checks for the recipe's shots (all, or the ids in *shots*).

    For each shot, from its camera (found like :func:`render` finds it) with
    the shot's resolution: are the figures in frame (``subject_out_of_frame`` /
    ``subject_not_in_frame`` warnings, skipped when the shot sets
    ``allow_crop``; ``no_subject_in_frame`` error; ``camera_not_found`` error
    when the camera is not in the scene, e.g. before :func:`apply`). Then, per
    the shot's engine, will anything light the render (``no_light`` error,
    reported once with ``shot=None`` when every shot agrees). With no shots,
    only lighting is checked, for the active engine. See
    :meth:`dazpy.DazScene.check` for the codes. Raises ``ValueError`` for
    unknown shot ids.
    """
    model = _checked(recipe, None)
    chosen = _choose(model, shots)
    return _check_shots(model, read_live(scene._client, model.id), scene._client, chosen)


@dataclass(frozen=True)
class ShotRender:
    """One rendered shot: its id, the camera label used, the output path, the render result."""

    shot_id: str
    camera_label: str
    output: str
    result: RenderResult

    def to_dict(self) -> dict:
        return to_jsonable(self)


def _parent_dir(path: str) -> str:
    """The directory part of a Studio-host path (either separator); ``""`` if none."""
    cut = max(path.rfind("/"), path.rfind("\\"))
    return path[:cut] if cut > 0 else ""


def _mkdir_script(dirs: Sequence[str]) -> str:
    esc = ScriptBuilder.escape_string
    lines = [f"new DzDir({esc(d)}).mkpath({esc(d)});" for d in dirs]
    return ScriptBuilder.iife("\n".join(lines + ["return true;"]))


def _covers(entity_path: str, path: str) -> bool:
    return path == entity_path or path.startswith(entity_path + ".")


def _guard(report: ObserveReport, camera_keys: Sequence[str]) -> None:
    if not report.applied:
        raise RecipeNotAppliedError("recipe is not applied to this scene; call apply first", report)
    if report.conflicts:
        raise RecipeNotAppliedError(
            "recipe has unresolved conflicts with the scene: "
            + ", ".join(c.path for c in report.conflicts), report)
    for key in dict.fromkeys(camera_keys):
        hit = [i.path for i in report.drift if _covers(f"cameras.{key}", i.path)]
        if hit:
            raise RecipeNotAppliedError(
                f"camera {key!r} was changed in the scene ({', '.join(hit)}); "
                "apply the recipe or pass force=True", report)
    if report.pending:
        raise RecipeNotAppliedError("recipe has unapplied changes; call apply first", report)


@_patient
def render(recipe: SceneRecipe | dict, scene: DazScene, *, shots: Sequence[str] | None = None,
           force: bool = False, wait: bool = True, timeout: float = 300.0,
           require_clean: bool = False, finder: AssetFinder | None = None) -> list[ShotRender]:
    """Render the recipe's shots (all, or the ids in *shots*) in recipe order.

    Each shot renders from the recipe's camera node, found through its ownership
    record and passed to Studio by its current label (``"<recipe.id>:<camera
    key>"`` unless renamed in Studio; that label too when the camera is missing
    and *force* is set), with the top-level ``render`` settings overridden by
    the shot's own; anything
    unset is passed as ``0`` / ``""`` so Studio uses the scene default. The output
    folders are created on the Studio host first.

    Unless *force*, raises :class:`RecipeNotAppliedError` when the recipe is not
    applied, has conflicts or unapplied changes, or a rendered shot's camera was
    changed or deleted in the scene. Raises ``ValueError`` for unknown shot ids.
    With *require_clean* (independent of *force*), runs :func:`check` on the
    chosen shots first and raises :class:`~dazpy.exceptions.SceneCheckError`
    if it finds errors; nothing is rendered.

    A ``recipe_version: 2`` recipe's asset references are resolved first (as in
    :func:`observe`, through *finder* when given), so this can raise
    :class:`RecipeValidationError` when one cannot be resolved.
    """
    model = _checked(recipe, None)
    chosen = _choose(model, shots)
    report, _, live = _observe(model, scene, finder)
    if not force:
        _guard(report, [s.camera for s in chosen])
    if not chosen:
        return []
    if require_clean:
        check = _check_shots(model, live, scene._client, chosen)
        if not check.ok:
            raise SceneCheckError(check)
    dirs = list(dict.fromkeys(d for d in (_parent_dir(s.output) for s in chosen) if d))
    if dirs:
        scene._client.execute(_mkdir_script(dirs))
    out: list[ShotRender] = []
    for shot in chosen:
        width, height = _pick(model, shot, "resolution") or (0, 0)
        label = _camera_label(model, live, shot.camera)
        result = render_api.render(
            scene._client, shot.output, camera=label, engine=_pick(model, shot, "engine") or "",
            width=width, height=height, iray_samples=_pick(model, shot, "iray_samples") or 0,
            wait=wait, timeout=timeout)
        out.append(ShotRender(shot.id, label, shot.output, result))
    return out
