"""Scene recipes: validate, plan, apply and observe a declarative scene description.

A :class:`~dazpy._recipe_model.SceneRecipe` (or its dict form, see
:func:`recipe_schema`) describes the desired scene. This module is the public
facade over the layers below it:

- :func:`validate` - offline checks, plus (given a scene) that every asset,
  pose and HDRI file exists;
- :func:`plan` - what an apply would do, without touching the scene;
- :func:`apply` - validate, re-read the live scene, diff, execute with rollback;
- :func:`observe` - how the scene differs from the recipe now.

Every result type has a JSON-safe ``to_dict()``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from typing import TYPE_CHECKING, Mapping

from ._recipe_apply import ApplyResult, execute
from ._recipe_desired import compute_desired
from ._recipe_diff import Conflict, OnConflict, RecipePlan, Resolution, diff
from ._recipe_json import to_jsonable
from ._recipe_model import SceneRecipe
from ._recipe_ops import DazSceneOps, exists_script
from ._recipe_store import LiveState, read_live
from ._recipe_validate import RecipeIssue, ValidationReport, file_not_found, validate_offline
from .exceptions import RecipeValidationError

if TYPE_CHECKING:
    from ._scene import DazScene

__all__ = ["ObserveReport", "apply", "observe", "plan", "recipe_schema", "validate"]

_SCHEMA_VERSIONS = (1,)


@dataclass(frozen=True)
class ObserveReport:
    """How the scene stands against a recipe.

    ``applied``: the recipe has a manifest in the scene. ``drift``: hand edits
    kept (``hand_tweak_kept``) and hand deletions (``deleted_in_scene``).
    ``pending``: what an apply would change if the recipe won every conflict
    (``<entity>.<channel>`` for modified/environment channels, the entity path
    for creates, unparents and deletes). ``in_sync``: applied, with no pending
    change, drift or conflict.
    """

    applied: bool
    in_sync: bool
    drift: tuple[RecipeIssue, ...]
    pending: tuple[str, ...]
    conflicts: tuple[Conflict, ...]

    def to_dict(self) -> dict:
        return to_jsonable(self)


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


def validate(recipe: SceneRecipe | dict, scene: "DazScene | None" = None) -> ValidationReport:
    """Validate *recipe*; with *scene*, also check its files exist (one Studio script).

    Adds ``file_not_found`` at ``assets.<k>.path``, ``actors.<k>.pose`` and
    ``lighting.environment.image_path``. The existence check is skipped while the
    recipe has offline errors.
    """
    report = validate_offline(_as_dict(recipe))
    if scene is None or not report.ok:
        return report
    model = recipe if isinstance(recipe, SceneRecipe) else SceneRecipe.from_dict(recipe)
    refs = _file_refs(model)
    if not refs:
        return report
    found = scene._client.execute(exists_script(sorted({f for _, f in refs}))).value or {}
    missing = tuple(file_not_found(path, f) for path, f in refs if not found.get(f, False))
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


def plan(recipe: SceneRecipe | dict, scene: "DazScene", *, on_conflict: OnConflict = "ask",
         resolutions: Mapping[str, Resolution] | None = None) -> RecipePlan:
    """What :func:`apply` would do now. Reads the scene, changes nothing.

    Raises :class:`RecipeValidationError` for an offline-invalid recipe; does not
    check that files exist (that is :func:`validate` / :func:`apply`).
    """
    model = _checked(recipe, None)
    desired, live = _read(model, scene)
    return diff(desired, live, on_conflict=on_conflict, resolutions=resolutions)


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
        elif s.op in ("create", "unparent", "delete"):
            out.append(s.path)
    return tuple(dict.fromkeys(out))


def observe(recipe: SceneRecipe | dict, scene: "DazScene") -> ObserveReport:
    """Compare *scene* with *recipe* without changing anything."""
    model = _checked(recipe, None)
    desired, live = _read(model, scene)
    p = diff(desired, live, on_conflict="recipe_wins")
    drift = tuple(w for w in p.warnings if w.code == "hand_tweak_kept") + tuple(
        RecipeIssue(c.path, "deleted_in_scene",
                    f"{c.path} was deleted in the scene; apply would recreate it.")
        for c in p.conflicts if c.kind == "deleted_in_scene")
    pending = _pending(p)
    applied = live.manifest is not None
    return ObserveReport(applied=applied, in_sync=applied and not (pending or drift or p.conflicts),
                         drift=drift, pending=pending, conflicts=p.conflicts)
