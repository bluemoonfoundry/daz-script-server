"""Scene recipes: validate, plan, apply and observe a declarative scene description.

A :class:`~dazpy._recipe_model.SceneRecipe` (or its dict form, see
:func:`recipe_schema`) describes the desired scene. This module is the public
facade over the layers below it:

- :func:`validate` - offline checks, plus (given a scene) that every asset,
  pose and HDRI file exists;
- :func:`plan` - what an apply would do, without touching the scene;
- :func:`apply` - validate, re-read the live scene, diff, execute with rollback;
- :func:`observe` - how the scene differs from the recipe now;
- :func:`render` - render the recipe's shots from an applied scene.

Every result type has a JSON-safe ``to_dict()``.
"""

from __future__ import annotations

import functools
import json
import os
from dataclasses import dataclass
from importlib import resources
from typing import TYPE_CHECKING, Mapping, Sequence

from ._recipe_apply import ApplyResult, execute
from . import _render_api as render_api
from ._recipe_desired import compute_desired
from ._recipe_diff import Conflict, OnConflict, RecipePlan, Resolution, diff
from ._recipe_json import to_jsonable
from ._recipe_model import SceneRecipe
from ._recipe_ops import DazSceneOps, is_local_pose_file, resolve_files
from ._recipe_store import LiveState, read_live
from ._recipe_validate import RecipeIssue, ValidationReport, file_not_found, validate_offline
from ._render_api import RenderResult
from ._client import DazClient
from ._script_builder import ScriptBuilder
from .exceptions import RecipeNotAppliedError, RecipeValidationError

if TYPE_CHECKING:
    from ._scene import DazScene

__all__ = ["ObserveReport", "ShotRender", "apply", "observe", "plan", "recipe_schema", "render",
           "validate"]

_SCHEMA_VERSIONS = (1,)


@dataclass(frozen=True)
class ObserveReport:
    """How the scene stands against a recipe.

    ``applied``: the recipe has a manifest in the scene. ``drift``: hand edits
    kept (``hand_tweak_kept``) and hand deletions (``deleted_in_scene``).
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


def _file_refs(recipe: SceneRecipe) -> list[tuple[str, str]]:
    """``(recipe path, file)`` for every file the recipe makes Studio open."""
    refs = [(f"assets.{k}.path", a.path) for k, a in recipe.assets.items()]
    refs += [(f"actors.{k}.pose", a.pose) for k, a in recipe.actors.items() if a.pose]
    if recipe.environment is not None:
        refs.append(("lighting.environment.image_path", recipe.environment.image_path))
    return refs


@_patient
def validate(recipe: SceneRecipe | dict, scene: "DazScene | None" = None) -> ValidationReport:
    """Validate *recipe*; with *scene*, also check its files exist (one Studio script).

    Adds ``file_not_found`` at ``assets.<k>.path``, ``actors.<k>.pose`` and
    ``lighting.environment.image_path``. The existence check is skipped while the
    recipe has offline errors. Files are resolved on the Studio host in one script
    (content paths through the content manager), except dazpy pose ``.json``
    files: ``poses.apply_pose`` reads those on the client, so they are checked
    there. Raises :class:`~dazpy.exceptions.DazError` if Studio returns no
    result for the check.
    """
    report = validate_offline(_as_dict(recipe))
    if scene is None or not report.ok:
        return report
    model = recipe if isinstance(recipe, SceneRecipe) else SceneRecipe.from_dict(recipe)
    refs = _file_refs(model)
    if not refs:
        return report
    local = {f for path, f in refs if path.endswith(".pose") and is_local_pose_file(f)}
    found = resolve_files(scene._client, [f for _, f in refs if f not in local])
    found.update({f: f if os.path.isfile(f) else "" for f in local})
    missing = tuple(file_not_found(path, f) for path, f in refs if not found.get(f))
    if not missing:
        return report
    errors = report.errors + missing
    return ValidationReport(ok=False, errors=errors, warnings=report.warnings)


def _checked(recipe: SceneRecipe | dict, scene: "DazScene | None") -> SceneRecipe:
    report = validate(recipe, scene)
    if not report.ok:
        raise RecipeValidationError(report)
    return recipe if isinstance(recipe, SceneRecipe) else SceneRecipe.from_dict(recipe)


def _read(model: SceneRecipe, scene: "DazScene") -> tuple[dict, LiveState]:
    return compute_desired(model), read_live(scene._client, model.id)


@_patient
def plan(recipe: SceneRecipe | dict, scene: "DazScene", *, on_conflict: OnConflict = "ask",
         resolutions: Mapping[str, Resolution] | None = None) -> RecipePlan:
    """What :func:`apply` would do now. Reads the scene, changes nothing.

    Raises :class:`RecipeValidationError` for an offline-invalid recipe; does not
    check that files exist (that is :func:`validate` / :func:`apply`).
    """
    model = _checked(recipe, None)
    desired, live = _read(model, scene)
    return diff(desired, live, on_conflict=on_conflict, resolutions=resolutions)


@_patient
def apply(recipe: SceneRecipe | dict, scene: "DazScene", *, on_conflict: OnConflict = "ask",
          resolutions: Mapping[str, Resolution] | None = None) -> ApplyResult:
    """Apply *recipe* to *scene*, re-planning against the scene's current state.

    Raises :class:`RecipeValidationError` (before touching the scene) when the
    recipe is invalid offline or names a missing file. A conflict under
    ``on_conflict="ask"`` returns ``applied=False`` with the conflicts and writes
    nothing; a failure part-way rolls back (see :class:`ApplyResult`).
    """
    model = _checked(recipe, scene)
    desired, live = _read(model, scene)
    the_plan = diff(desired, live, on_conflict=on_conflict, resolutions=resolutions)
    return execute(the_plan, desired, live, DazSceneOps(scene),
                   recipe_id=model.id, recipe_version=model.recipe_version)


def _pending(the_plan: RecipePlan) -> tuple[str, ...]:
    out: list[str] = []
    for s in the_plan.steps:
        if s.op in ("modify", "set_environment"):
            out += [f"{s.path}.{ch}" for ch in s.channels]
        elif s.op in ("create", "release", "unparent", "delete"):
            out.append(s.path)
    return tuple(dict.fromkeys(out))


@_patient
def observe(recipe: SceneRecipe | dict, scene: "DazScene") -> ObserveReport:
    """Compare *scene* with *recipe* without changing anything.

    Diffs as if the recipe won every conflict, except that hand deletions
    already accepted (tombstoned in the manifest) stay accepted: they are not
    pending recreates.
    """
    model = _checked(recipe, None)
    return _observation(*_read(model, scene))


def _observation(desired: dict, live: LiveState) -> ObserveReport:
    accepted: dict[str, Resolution] = {p: "scene" for p in (live.manifest.deleted if live.manifest else ())
                if p in desired and p not in live.entities}
    p = diff(desired, live, on_conflict="recipe_wins", resolutions=accepted)
    drift = tuple(w for w in p.warnings if w.code == "hand_tweak_kept") + tuple(
        RecipeIssue(c.path, "deleted_in_scene",
                    f"{c.path} was deleted in the scene; apply would recreate it.")
        for c in p.conflicts if c.kind == "deleted_in_scene")
    pending = _pending(p)
    applied = live.manifest is not None
    return ObserveReport(applied=applied, in_sync=applied and not (pending or drift or p.conflicts),
                         drift=drift, pending=pending, conflicts=p.conflicts)


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
def render(recipe: SceneRecipe | dict, scene: "DazScene", *, shots: Sequence[str] | None = None,
           force: bool = False, wait: bool = True, timeout: float = 300.0) -> list[ShotRender]:
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
    """
    model = _checked(recipe, None)
    known = [s.id for s in model.shots]
    if shots is not None:
        unknown = [i for i in dict.fromkeys(shots) if i not in known]
        if unknown:
            raise ValueError(f"unknown shot id(s): {', '.join(unknown)}; "
                             f"valid shot ids: {', '.join(known) or '(none)'}")
        wanted = set(shots)
        chosen = [s for s in model.shots if s.id in wanted]
    else:
        chosen = list(model.shots)
    desired, live = _read(model, scene)
    if not force:
        _guard(_observation(desired, live), [s.camera for s in chosen])
    if not chosen:
        return []
    dirs = list(dict.fromkeys(d for d in (_parent_dir(s.output) for s in chosen) if d))
    if dirs:
        scene._client.execute(_mkdir_script(dirs))
    out: list[ShotRender] = []
    for shot in chosen:
        top, own = model.render, shot.render

        def pick(name: str):
            return (getattr(own, name, None) if own is not None else None) or getattr(top, name)

        width, height = pick("resolution") or (0, 0)
        camera = live.entities.get(f"cameras.{shot.camera}")
        label = (camera.label if camera is not None and camera.label
                 else f"{model.id}:{shot.camera}")
        result = render_api.render(
            scene._client, shot.output, camera=label, engine=pick("engine") or "",
            width=width, height=height, iray_samples=pick("iray_samples") or 0,
            wait=wait, timeout=timeout)
        out.append(ShotRender(shot.id, label, shot.output, result))
    return out
