"""Unit tests for dazpy._recipe_ops.DazSceneOps internals (no server needed)."""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from dazpy._recipe_ops import DazSceneOps  # noqa: E402
from dazpy.exceptions import NodeNotFoundError  # noqa: E402

SAVED = {"XPos": 0.0, "YPos": 0.0, "ZPos": 0.0, "XRot": 0.0, "YRot": 15.0, "ZRot": 0.0,
         "XScale": 1.0, "YScale": 1.0, "ZScale": 1.0, "Scale": 1.0}


def _ops(results):
    """DazSceneOps whose client answers execute() with *results* in order and
    records every script it was sent."""
    client = mock.Mock()
    client.execute.side_effect = [SimpleNamespace(value=v) for v in results]
    return DazSceneOps(SimpleNamespace(_client=client)), client


class TestPoseKeepsNodeTransform(unittest.TestCase):
    """5d6f.30 item 5: a pose preset can carry a root transform; the pose
    channel must not move the figure node (the transform channel owns it)."""

    def test_preset_pose_is_wrapped_in_read_and_restore(self):
        ops, client = _ops([SAVED, True, True])
        with mock.patch.object(DazSceneOps, "_resolve_asset", return_value="C:/p/pose.duf"):
            ops.set_channels("Genesis 9", "actor", {"pose": {"pose_path": "/Poses/pose.duf"}})
        scripts = [c.args[0] for c in client.execute.call_args_list]
        self.assertEqual(len(scripts), 3)
        self.assertIn("recipe:read-xform", scripts[0])
        self.assertIn("openFile", scripts[1])
        self.assertIn("recipe:write-xform", scripts[2])
        self.assertIn('["YRot", 15.0]', scripts[2])
        self.assertNotIn(" in _v)", scripts[2])  # no for-in: Studio 6 enumerates extra keys

    def test_changed_transform_still_wins_after_the_pose(self):
        ops, client = _ops([SAVED, True, True])
        with mock.patch.object(DazSceneOps, "_resolve_asset", return_value="C:/p/pose.duf"), \
             mock.patch.object(DazSceneOps, "_set_transform") as set_transform:
            set_transform.side_effect = lambda *a: client.execute("// set-transform")
            client.execute.side_effect = [SimpleNamespace(value=v) for v in (SAVED, True, True, None)]
            ops.set_channels("Genesis 9", "actor", {
                "transform": {"position": [10, 0, 0], "rotation": [0, 0, 0]},
                "pose": {"pose_path": "/Poses/pose.duf"},
            })
        scripts = [c.args[0] for c in client.execute.call_args_list]
        self.assertIn("recipe:write-xform", scripts[2])
        self.assertEqual(scripts[3], "// set-transform")

    def test_missing_node_raises_before_posing(self):
        ops, client = _ops([None])
        with self.assertRaises(NodeNotFoundError):
            ops.set_channels("Gone", "actor", {"pose": {"pose_path": "/Poses/pose.duf"}})
        self.assertEqual(client.execute.call_count, 1)


if __name__ == "__main__":
    unittest.main()
