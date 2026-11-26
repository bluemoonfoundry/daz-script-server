"""Shared issue type and path helpers for recipe validation (no dazpy imports beyond JSON)."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Any
from collections.abc import Iterable

from ._recipe_json import to_jsonable


@dataclass(frozen=True)
class RecipeIssue:
    path: str
    code: str
    message: str
    allowed: tuple[str, ...] | None = None
    suggestion: str | None = None

    def to_dict(self) -> dict:
        return to_jsonable(self)


def _closest(name: Any, candidates: Iterable[str]) -> str | None:
    if not isinstance(name, str):
        return None
    m = difflib.get_close_matches(name, list(candidates), n=1, cutoff=0.6)
    return m[0] if m else None


def _join(base: str, name: str) -> str:
    return f"{base}.{name}" if base else name
