"""Shared asset reference: a path string or an object naming content by path/sku/product/find."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

from ._recipe_issue import RecipeIssue, _closest, _join

_FIELDS = ("path", "product", "sku", "find", "file", "type", "resolved")
_SELECTORS = ("path", "product", "sku", "find")
_PIN_FIELDS = ("path", "sku", "product", "asset_id")


@dataclass(frozen=True)
class ResolvedPin:
    path: str
    sku: str | None = None
    product: str | None = None
    asset_id: str | None = None

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in _PIN_FIELDS if getattr(self, k) is not None}


@dataclass(frozen=True)
class AssetRef:
    path: str | None = None
    product: str | None = None
    sku: str | None = None
    find: str | None = None
    file: str | None = None
    type: str | None = None
    resolved: ResolvedPin | None = None

    @property
    def kind(self) -> Literal["path", "sku", "product", "find"]:
        """Which selector decides resolution: path > sku > product > find."""
        for name in ("path", "sku", "product", "find"):
            if getattr(self, name) is not None:
                return name  # type: ignore[return-value]
        raise ValueError("asset reference has none of path, sku, product, find")

    def to_dict(self) -> dict | str:
        d = {k: getattr(self, k) for k in _FIELDS[:-1] if getattr(self, k) is not None}
        if self.resolved is not None:
            d["resolved"] = self.resolved.to_dict()
        if list(d) == ["path"]:
            return self.path  # type: ignore[return-value]
        return d


def parse_ref(value: str | Mapping) -> AssetRef:
    """Build an AssetRef from a validated string or mapping."""
    if isinstance(value, str):
        return AssetRef(path=value)
    kwargs = {k: value[k] for k in _FIELDS[:-1] if k in value}
    pin = value.get("resolved")
    if pin is not None:
        kwargs["resolved"] = ResolvedPin(**{k: pin[k] for k in _PIN_FIELDS if k in pin})
    return AssetRef(**kwargs)


def _object_issues(value: Mapping, path: str, fields: tuple[str, ...]) -> list[RecipeIssue]:
    out: list[RecipeIssue] = []
    for k in value:
        if k not in fields:
            out.append(RecipeIssue(_join(path, str(k)), "unknown_field", f"unknown field '{k}'",
                                   allowed=tuple(sorted(fields)),
                                   suggestion=_closest(k, fields)))
    return out


def _string_issue(value: object, path: str) -> RecipeIssue | None:
    if not isinstance(value, str):
        return RecipeIssue(path, "invalid_type", "expected a string")
    if not value:
        return RecipeIssue(path, "invalid_type", "expected a non-empty string")
    return None


def ref_issues(value: object, path: str) -> list[RecipeIssue]:
    """Validate an asset reference; issues are RecipeIssue with paths under *path*."""
    if isinstance(value, str):
        issue = _string_issue(value, path)
        return [issue] if issue else []
    if not isinstance(value, Mapping):
        return [RecipeIssue(path, "invalid_type", "expected a string or an object")]
    out = _object_issues(value, path, _FIELDS)
    for k in _FIELDS[:-1]:
        if k in value:
            issue = _string_issue(value[k], _join(path, k))
            if issue:
                out.append(issue)
    pin = value.get("resolved")
    if "resolved" in value:
        pp = _join(path, "resolved")
        if not isinstance(pin, Mapping):
            out.append(RecipeIssue(pp, "invalid_type", "expected an object"))
        else:
            out += _object_issues(pin, pp, _PIN_FIELDS)
            if "path" not in pin:
                out.append(RecipeIssue(pp, "invalid_asset_ref", "'resolved' requires 'path'"))
            for k in _PIN_FIELDS:
                if k in pin:
                    issue = _string_issue(pin[k], _join(pp, k))
                    if issue:
                        out.append(issue)
    if not any(k in value for k in _SELECTORS):
        out.insert(0, RecipeIssue(
            path, "invalid_asset_ref",
            "an asset reference needs at least one of path, product, sku, find",
            allowed=_SELECTORS))
    return out
