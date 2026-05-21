from __future__ import annotations

import json

from ._client import DazClient
from ._script_builder import ScriptBuilder


class UndoGroup:
    """Context manager that groups DAZ Studio operations into a single undo step.

    On successful exit the changes are committed with ``acceptUndo(label)``.
    If an exception propagates, ``cancelUndo()`` is called instead.

    Obtain via :meth:`DazScene.undo` rather than constructing directly::

        with scene.undo("Rotate arm"):
            skel.find_bone("r_forearm").set_local_rotation(0, 0, 45)

    Args:
        client: The :class:`~dazpy.DazClient` to use.
        label: The label shown in DAZ Studio's Edit > Undo menu.
    """

    def __init__(self, client: DazClient, label: str):
        self._client = client
        self._label = label

    def __enter__(self) -> "UndoGroup":
        script = ScriptBuilder.iife("beginUndo();")
        self._client.execute(script)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is None:
            script = ScriptBuilder.iife(f"acceptUndo({json.dumps(self._label)});")
        else:
            script = ScriptBuilder.iife("cancelUndo();")
        self._client.execute(script)
        return False
