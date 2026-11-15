"""Shared fakes for scene-recipe tests (not a test module).

``fake_client`` returns a mock DazClient whose ``execute`` answers the live
readback script from canned nodes/manifest and the ``DazPose.capture`` script
from canned poses.  Build the canned data with ``rec``, ``man`` and ``node``.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from dazpy._recipe_store import EntityRecord, Manifest
from dazpy._result import ExecutionResult


def rec(recipe_id: str, path: str, desired: dict | None = None, observed: dict | None = None,
        recipe_version: int = 1) -> EntityRecord:
    """An EntityRecord with empty channels unless given."""
    return EntityRecord(recipe_id, path, recipe_version, desired or {}, observed or {})


def man(recipe_id: str, entities: list[str], environment: EntityRecord | None = None) -> Manifest:
    """A Manifest listing *entities* (paths)."""
    return Manifest(recipe_id, tuple(entities), environment)


def node(name: str, record: EntityRecord | None, *, kind: str = "prop", label: str | None = None,
         element_id: int = 1, position=(0.0, 0.0, 0.0), rotation=(0.0, 0.0, 0.0),
         optics: dict | None = None, output: dict | None = None,
         children: list[dict] | None = None, bone: bool = False,
         camera: bool = False, light: bool = False) -> dict:
    """One canned node as the readback script reports it.

    ``kind`` is ignored by the reader (derived from the record path); ``bone``
    marks a DzBone child.  ``children`` are other ``node(...)`` results (record may be None = foreign).
    A node with ``record=None`` is only meaningful as a child.
    """
    return {
        "name": name, "label": label or name, "element_id": element_id,
        "record": record.to_json() if record else None, "kind": kind,
        "position": list(position), "rotation": list(rotation),
        "optics": optics, "output": output,
        "is_camera": camera, "is_light": light, "bone": bone,
        "children": [{"name": c["name"], "record": c["record"], "bone": c["bone"],
                      "children": c["children"]} for c in children or []],
    }


def fake_client(nodes: list[dict] | None = None, manifest: Manifest | None = None,
                environment: dict | None = None, pose: dict | None = None) -> MagicMock:
    """A mock client for ``read_live``.

    Top-level nodes with ``record=None`` are dropped, like the real script
    (only recorded nodes are reported).  Scripts are recorded in
    ``client.execute.call_args_list``.
    """
    payload = {
        "manifest": manifest.to_json() if manifest else None,
        "environment": environment,
        "nodes": [n for n in nodes or [] if n["record"]],
    }
    pose_payload = pose or {"bones": {}, "morphs": {}, "props": {}}

    def execute(script, *a, **kw):
        return ExecutionResult(value=pose_payload if "getAllBones" in script else payload)

    client = MagicMock()
    client.execute.side_effect = execute
    return client
