from __future__ import annotations

import json

from ._client import DazClient
from ._script_builder import ScriptBuilder


class UndoGroup:
    def __init__(self, client: DazClient, label: str):
        self._client = client
        self._label = label

    def __enter__(self) -> "UndoGroup":
        script = ScriptBuilder.iife(
            f"Scene.beginUndo(); Scene.setUndoLabel({json.dumps(self._label)});"
        )
        self._client.execute(script)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is None:
            script = ScriptBuilder.iife("Scene.acceptUndo();")
        else:
            script = ScriptBuilder.iife("Scene.cancelUndo();")
        self._client.execute(script)
        return False
