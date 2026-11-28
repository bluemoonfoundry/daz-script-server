"""Planning of actor take-over and one-shot replace/remove selectors (spec 6.2, 6.4).

Pure: consumes the live figure readback and the recipe's ownership state, never
touches the scene. ``add`` entries need no planning here.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping, Sequence

from ._content_types import type_matches
from ._recipe_diff import Conflict, _unpinned
from ._recipe_issue import RecipeIssue, _closest
from ._recipe_fitted import FigureInfo, FittedItem, is_data_file
from ._recipe_model import SceneRecipe, TypeSelector, WearingEntry, actor_ref
from ._recipe_store import LiveState


@dataclass(frozen=True)
class TakeOver:
    actor_path: str
    node_name: str  # figure to adopt (no record yet): its elementID: ref (C1), else its name


@dataclass(frozen=True)
class Unfit:
    actor_path: str
    entry: str
    node_names: tuple[str, ...]  # matched items: their elementID: refs (C1), else names
    removed: tuple[dict, ...]  # {"label", "type", "source_path"} for the done-log and restore


@dataclass(frozen=True)
class WearingPlan:
    take_overs: tuple[TakeOver, ...] = ()
    unfits: tuple[Unfit, ...] = ()
    errors: tuple[RecipeIssue, ...] = ()
    conflicts: tuple[Conflict, ...] = ()
    warnings: tuple[RecipeIssue, ...] = ()
    # (actor_path, entry id) pairs that become done without an Unfit (ignored / add-fallback)
    done_entries: tuple[tuple[str, str], ...] = ()


def entry_id(entry: WearingEntry, index: int) -> str:
    """The id recorded in an actor's ``done`` log: the key, or for a ``remove``
    its selector (``remove.type=<T>`` / ``remove.label=<label>``), so the id
    survives reordering the ``wearing`` list (final review I5)."""
    if entry.op == "remove":
        t = entry.target
        return f"remove.type={t.type}" if isinstance(t, TypeSelector) else f"remove.label={t}"
    return entry.key or f"{entry.op}.{index}"


def _legacy_id(entry: WearingEntry, index: int) -> str | None:
    """The positional ``remove.<index>`` id done logs written before I5 hold."""
    return f"remove.{index}" if entry.op == "remove" else None


def _matches(selector, item: FittedItem) -> bool:
    if isinstance(selector, TypeSelector):
        return type_matches(selector.type, item.type)
    return item.label == selector


def plan_wearing(recipe: SceneRecipe, figures: Mapping[str, list[FigureInfo]],
                 live: LiveState, scene_labels: Sequence[str] = ()) -> WearingPlan:
    take_overs: list[TakeOver] = []
    unfits: list[Unfit] = []
    errors: list[RecipeIssue] = []
    conflicts: list[Conflict] = []
    warnings: list[RecipeIssue] = []
    done_entries: list[tuple[str, str]] = []

    all_figures = [f for fs in figures.values() for f in fs]
    all_labels = sorted(set(scene_labels) or {f.label for f in all_figures})
    for key, actor in recipe.actors.items():
        path = f"actors.{key}"
        entity = live.entities.get(path)
        record = entity.record if entity is not None else None
        figure: FigureInfo | None = None
        skip_entries = False

        if entity is not None:
            figure = next((f for f in all_figures if f.is_node(entity.node_name)), None)
            skip_entries = figure is None  # gone/relabelled: the diff reports deleted_in_scene
            requested = (record.source or {}).get("requested") if record else None
            ref = actor_ref(recipe, key)
            # compared without the 'resolved' pin: pin() then apply() is no change (I3)
            if (record is not None and record.adopted_from_scene and requested is not None
                    and ref is not None
                    and _unpinned(requested) != _unpinned(ref.to_dict())):
                errors.append(RecipeIssue(
                    f"{path}.node", "take_over_asset_changed",
                    f"Actor {key!r} was taken over from the scene, but its asset reference "
                    f"changed since; remove the node or restore the original asset."))
        elif actor.node is not None:
            matches = figures.get(actor.node, [])
            if len(matches) == 1:
                figure = matches[0]
                take_overs.append(TakeOver(path, figure.ref))
            elif len(matches) > 1:
                errors.append(RecipeIssue(
                    f"{path}.node", "ambiguous_node",
                    f"{len(matches)} figures are labelled {actor.node!r}; rename all but one.",
                    allowed=tuple(f.name for f in matches)))
                skip_entries = True
            else:
                near = next((lb for lb in all_labels if lb.lower() == actor.node.lower()), None)
                near = near or _closest(actor.node, all_labels)
                if actor.asset is None:
                    errors.append(RecipeIssue(
                        f"{path}.node", "node_not_found",
                        f"No figure labelled {actor.node!r} in the scene and the actor has no asset to create.",
                        suggestion=near))
                    skip_entries = True
                elif near is not None:
                    warnings.append(RecipeIssue(
                        f"{path}.node", "similar_node_label",
                        f"No figure labelled {actor.node!r}; the actor will be created. "
                        f"Did you mean {near!r}? Labels match exactly.",
                        suggestion=near))

        done = {d.get("entry") for d in (record.done if record else ())}
        items = [it for it in (figure.items if figure else ())
                 if not (it.record is not None and it.record.recipe_id == recipe.id)]

        seen: set[str] = set()
        for index, entry in enumerate(actor.wearing):
            if skip_entries or entry.op == "add":
                continue
            eid = entry_id(entry, index)
            if eid in done or eid in seen or _legacy_id(entry, index) in done:
                continue  # a repeated identical remove is the same one-shot
            seen.add(eid)
            epath = f"{path}.wearing.{eid}"
            hit = [it for it in items if _matches(entry.target, it)]
            if not hit:
                if entry.if_missing != "error":
                    done_entries.append((path, eid))
                else:
                    code = "replace_target_missing" if entry.op == "replace" else "remove_target_missing"
                    errors.append(RecipeIssue(
                        epath, code,
                        f"Nothing on {key!r} matches {_describe(entry.target)}.",
                        allowed=tuple(it.label for it in items) or None))
                continue
            hit_refs = {it.ref for it in hit}
            items = [it for it in items if it.ref not in hit_refs]
            unfits.append(Unfit(
                path, eid, tuple(it.ref for it in hit),
                tuple({"label": it.label, "type": it.type, "source_path": restore_source(it)}
                      for it in hit)))
            for it in hit:
                # every non-asset descendant goes with the delete: a matched item is
                # never recipe-owned, so nothing below it is part of an owned entity (C2)
                foreign = tuple(it.foreign_children)
                if foreign:
                    # one conflict (and resolution key) per matched item; base names the
                    # item (by ref), so a "recipe" resolution can unparent from it.  The
                    # key shows the name unless another match shares it.
                    shared = sum(1 for x in hit if x.name == it.name) > 1
                    key = it.ref if shared else it.name
                    conflicts.append(Conflict(f"{epath}[{key}]", "has_foreign_children",
                                              _describe(entry.target), {"node": it.ref, "entry": epath},
                                              list(foreign)))
                if restore_source(it) is None:
                    warnings.append(RecipeIssue(
                        epath, "unrestorable_removal",
                        f"{it.label!r} has no known source file; it cannot be restored once removed."))

    return WearingPlan(tuple(take_overs), tuple(unfits), tuple(errors), tuple(conflicts),
                       tuple(warnings), tuple(done_entries))


def restore_source(item: FittedItem) -> str | None:
    """The ``.duf`` a removed item can be reloaded from, or None (spec 8.7).

    Only an item carrying a recipe record knows its source: the record's
    ``source.resolved.path`` (else ``source.path``).  Hand content has none; its
    live ``getAssetUriForNode`` value is a ``.dsf`` data file and is never used."""
    src = (item.record.source if item.record else None) or {}
    path = (src.get("resolved") or {}).get("path") or src.get("path")
    return str(path) if path and not is_data_file(str(path)) else None


def _describe(selector) -> str:
    return f"type {selector.type!r}" if isinstance(selector, TypeSelector) else repr(selector)
