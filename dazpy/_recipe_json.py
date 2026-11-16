"""JSON-safe conversion shared by every scene-recipe result type's ``to_dict()``."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any


def to_jsonable(value: Any) -> Any:
    """Recursively convert *value* to plain ``json.dumps``-able data.

    Dataclasses become dicts, tuples/lists/sets become lists, mappings become
    dicts with string keys.  Anything else that is not a JSON scalar is a bug in
    the caller's data and raises ``TypeError`` rather than being stringified.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(v) for v in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError(f"{type(value).__name__} is not JSON-serializable")
