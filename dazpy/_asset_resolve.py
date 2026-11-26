"""Resolve asset references to absolute files: record reuse, pins, then path/sku/product/find."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from ._asset_finder import AssetCandidate, AssetFinder, FinderUnavailable
from ._asset_ref import AssetRef
from ._content_types import type_matches
from ._recipe_issue import RecipeIssue
from ._recipe_ops import resolve_files

if TYPE_CHECKING:
    from .client import DazClient
    from ._recipe_model import SceneRecipe

_MAX_LISTED = 10


@dataclass(frozen=True)
class ResolvedAsset:
    requested: AssetRef
    path: str  # absolute file on the Studio host
    sku: str | None
    product: str | None
    asset_id: str | None
    type: str | None
    finder: Literal["path", "studio", "content_browser", "pin", "record"]

    def to_dict(self) -> dict:
        d = {"requested": self.requested.to_dict(), "path": self.path, "sku": self.sku,
             "product": self.product, "asset_id": self.asset_id, "type": self.type,
             "finder": self.finder}
        return {k: v for k, v in d.items() if v is not None}


@dataclass(frozen=True)
class ResolveReport:
    resolved: dict[str, ResolvedAsset]
    errors: tuple[RecipeIssue, ...]
    warnings: tuple[RecipeIssue, ...]
    finder: str


def recipe_refs(recipe: SceneRecipe) -> list[tuple[str, AssetRef]]:
    """Every asset reference with its recipe path (poses and HDRIs are plain files, not refs)."""
    from ._recipe_model import actor_ref, prop_ref

    out: list[tuple[str, AssetRef]] = []
    for a, actor in recipe.actors.items():
        ref = actor_ref(recipe, a)
        if ref is not None:
            out.append((f"actors.{a}.asset", ref))
        out.extend((f"actors.{a}.presets[{i}]", r) for i, r in enumerate(actor.presets))
        out.extend((f"actors.{a}.wearing.{w.key}", w.ref) for w in actor.wearing
                   if w.op in ("add", "replace") and w.ref is not None)
    out.extend((f"props.{p}.asset", prop_ref(recipe, p)) for p in recipe.props)
    return out


def _same(a: str | None, b: str | None) -> bool:
    return (a or "").casefold() == (b or "").casefold()


def _file_matches(file: str, c: AssetCandidate) -> bool:
    want = file.replace("\\", "/").casefold().lstrip("/")
    got = c.path.replace("\\", "/").casefold()
    return (got.lstrip("/") == want or got.endswith("/" + want)
            or os.path.basename(got) == want)


def _from_candidate(ref: AssetRef, c: AssetCandidate, path: str, finder: str) -> ResolvedAsset:
    return ResolvedAsset(ref, path, c.sku, c.product, c.asset_id, c.type, finder)  # type: ignore[arg-type]


def resolve_refs(client: DazClient, refs: list[tuple[str, AssetRef]], finder: AssetFinder,
                 prior: Mapping[str, dict] | None = None) -> ResolveReport:
    prior = prior or {}
    errors: list[RecipeIssue] = []
    warnings: list[RecipeIssue] = []
    resolved: dict[str, ResolvedAsset] = {}

    # Phase 1: everything that names a concrete file already (path ref, record, pin).
    early: dict[str, str] = {}
    for p, ref in refs:
        rec = prior.get(p)
        if rec and rec.get("requested") == ref.to_dict() and rec.get("path"):
            early[f"{p}\0record"] = rec["path"]
        if ref.kind == "path":
            early[f"{p}\0path"] = ref.path  # type: ignore[assignment]
        elif ref.resolved is not None:
            early[f"{p}\0pin"] = ref.resolved.path
    found = resolve_files(client, early.values())

    def ok(p: str, tag: str) -> str:
        return found.get(early.get(f"{p}\0{tag}", ""), "")

    pending: list[tuple[str, AssetRef]] = []
    for p, ref in refs:
        rec = prior.get(p)
        if ok(p, "record"):
            resolved[p] = ResolvedAsset(ref, ok(p, "record"), rec.get("sku"), rec.get("product"),
                                        rec.get("asset_id"), rec.get("type"), "record")
        elif ref.kind == "path":
            if ok(p, "path"):
                resolved[p] = ResolvedAsset(ref, ok(p, "path"), None, None, None, ref.type, "path")
            else:
                errors.append(RecipeIssue(p, "asset_not_found", f"file not found: {ref.path}"))
        elif ok(p, "pin"):
            pin = ref.resolved
            if (ref.sku and pin.sku and ref.sku != pin.sku) or \
               (ref.product and pin.product and not _same(ref.product, pin.product)):
                warnings.append(RecipeIssue(p, "pin_mismatch",
                                            "resolved pin does not match the requested sku/product"))
            resolved[p] = ResolvedAsset(ref, ok(p, "pin"), pin.sku, pin.product, pin.asset_id,
                                        ref.type, "pin")
        else:
            if ref.resolved is not None:
                warnings.append(RecipeIssue(p, "pin_file_missing",
                                            f"pinned file not found, searching again: {ref.resolved.path}"))
            pending.append((p, ref))

    # Phase 2: ask the finder; every chosen candidate is then resolved in one call.
    chosen: dict[str, AssetCandidate] = {}
    for p, ref in pending:
        try:
            if ref.kind == "find":
                c = _pick_find(p, ref, finder, errors)
            else:
                c = _pick_product(p, ref, finder, errors)
        except FinderUnavailable as e:
            errors.append(RecipeIssue(p, "content_database_unavailable", str(e)))
            continue
        if c is not None:
            chosen[p] = c
    files = resolve_files(client, [c.path for c in chosen.values()])
    refmap = dict(refs)
    for p, c in chosen.items():
        if files.get(c.path):
            resolved[p] = _from_candidate(refmap[p], c, files[c.path], finder.name)
        else:
            errors.append(RecipeIssue(p, "asset_not_found", f"file not found: {c.path}"))
    return ResolveReport(resolved, tuple(errors), tuple(warnings), finder.name)


def _typed(ref: AssetRef, cands: list[AssetCandidate]) -> list[AssetCandidate]:
    return [c for c in cands if type_matches(ref.type, c.type)] if ref.type else cands


def _pick_product(p: str, ref: AssetRef, finder: AssetFinder,
                  errors: list[RecipeIssue]) -> AssetCandidate | None:
    cands = finder.product_files(sku=ref.sku, product=ref.product) if ref.sku \
        else finder.product_files(product=ref.product)
    if ref.file:
        cands = [c for c in cands if _file_matches(ref.file, c)]
    cands = _typed(ref, cands)
    what = ref.sku or ref.product
    if not cands:
        errors.append(RecipeIssue(p, "asset_not_found", f"no matching file in product {what}"))
        return None
    if len(cands) > 1:
        errors.append(RecipeIssue(
            p, "ambiguous_asset",
            f"product {what} has {len(cands)} matching files; add 'file' or 'type'",
            allowed=tuple(c.path for c in cands[:_MAX_LISTED])))
        return None
    return cands[0]


def _pick_find(p: str, ref: AssetRef, finder: AssetFinder,
               errors: list[RecipeIssue]) -> AssetCandidate | None:
    cands = _typed(ref, finder.search(ref.find, type=ref.type))  # type: ignore[arg-type]
    if not cands:
        errors.append(RecipeIssue(p, "asset_not_found", f"nothing found for {ref.find!r}"))
        return None
    exact = [c for c in cands if _same(c.product, ref.find)]
    if len(exact) == 1:
        return exact[0]
    if len(cands) == 1:
        return cands[0]
    errors.append(RecipeIssue(
        p, "ambiguous_asset", f"{len(cands)} candidates for {ref.find!r}; be more specific",
        allowed=tuple(f"{c.product} ({c.sku}): {c.path}" for c in cands[:_MAX_LISTED])))
    return None
