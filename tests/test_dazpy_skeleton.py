"""dazpy unit tests: DazSkeleton / DazBone, poses, zero/reset, batch pose evaluation.

Mock-based; no server or DAZ Studio required.
Shared fakes live in tests/dazpy_fakes.py.
"""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dazpy._result import ExecutionResult
from dazpy._node import DazNode, NodeIdentifier
from dazpy._client import DazClient
from dazpy import exceptions
from dazpy_fakes import mock_client


class TestDazSkeletonScriptGeneration(unittest.TestCase):
    def setUp(self):
        from dazpy._skeleton import DazSkeleton
        self.DazSkeleton = DazSkeleton

    def _make_skeleton(self, return_value=None):
        client = mock_client(return_value)
        skel = self.DazSkeleton(client, NodeIdentifier("Genesis9"))
        return skel, client

    def test_bones_calls_getAllBones(self):
        skel, client = self._make_skeleton(["hip", "lShldrBend"])
        bones = skel.bones()
        self.assertEqual(len(bones), 2)
        script = client.execute.call_args[0][0]
        self.assertIn("getAllBones", script)

    def test_bones_returns_daz_bone_instances(self):
        from dazpy._bone import DazBone
        skel, client = self._make_skeleton(["hip"])
        bones = skel.bones()
        self.assertIsInstance(bones[0], DazBone)

    def test_bone_metadata_single_call(self):
        payload = [
            {
                "name": "hip",
                "label": "Hip",
                "parent_name": None,
                "rotation_order": "XYZ",
                "local_position": {"x": 0.0, "y": 0.0, "z": 0.0},
                "local_euler": {"x": 1.0, "y": 2.0, "z": 3.0},
            }
        ]
        skel, client = self._make_skeleton(payload)
        result = skel.bone_metadata()
        self.assertEqual(client.execute.call_count, 1)
        self.assertEqual(result[0]["name"], "hip")
        self.assertIsNone(result[0]["parent_name"])
        self.assertIn("getAllBones", client.execute.call_args[0][0])
        self.assertIn("getNodeParent", client.execute.call_args[0][0])

    def test_find_bone_calls_findBone(self):
        skel, client = self._make_skeleton("hip")
        skel.find_bone("hip")
        script = client.execute.call_args[0][0]
        self.assertIn("findBone", script)
        self.assertIn("hip", script)

    def test_find_bone_not_found_raises(self):
        skel, client = self._make_skeleton(None)
        with self.assertRaises(exceptions.NodeNotFoundError):
            skel.find_bone("nonexistent")

    def test_find_bone_by_label_calls_findBoneByLabel(self):
        skel, client = self._make_skeleton("hip")
        skel.find_bone_by_label("Hip")
        script = client.execute.call_args[0][0]
        self.assertIn("findBoneByLabel", script)

    def test_num_bones_calls_getAllBones_length(self):
        skel, client = self._make_skeleton(42)
        count = skel.num_bones()
        self.assertEqual(count, 42)
        script = client.execute.call_args[0][0]
        self.assertIn("getAllBones", script)
        self.assertIn("length", script)

    def test_follow_target_returns_skeleton(self):
        skel, client = self._make_skeleton("Genesis9_2")
        target = skel.follow_target()
        self.assertIsInstance(target, self.DazSkeleton)
        script = client.execute.call_args[0][0]
        self.assertIn("getFollowTarget", script)

    def test_follow_target_returns_none_when_null(self):
        skel, client = self._make_skeleton(None)
        target = skel.follow_target()
        self.assertIsNone(target)

    # ── bulk bone/morph fetch ─────────────────────────────────────────────────

    def test_bone_rotations_single_call(self):
        payload = {"hip": [1.0, 2.0, 3.0], "rForeArm": [0.0, 45.0, 0.0]}
        skel, client = self._make_skeleton(payload)
        result = skel.bone_rotations()
        self.assertEqual(client.execute.call_count, 1)
        self.assertEqual(result["hip"], (1.0, 2.0, 3.0))
        self.assertEqual(result["rForeArm"], (0.0, 45.0, 0.0))

    def test_bone_rotations_script_uses_getAllBones(self):
        skel, client = self._make_skeleton({"hip": [0, 0, 0]})
        skel.bone_rotations()
        script = client.execute.call_args[0][0]
        self.assertIn("getAllBones", script)
        self.assertIn("getXRotControl", script)
        self.assertIn("getYRotControl", script)
        self.assertIn("getZRotControl", script)

    def test_bone_rotations_returns_tuples(self):
        skel, client = self._make_skeleton({"hip": [10.0, 20.0, 30.0]})
        result = skel.bone_rotations()
        self.assertIsInstance(result["hip"], tuple)

    def test_bone_rotations_empty_skeleton(self):
        skel, client = self._make_skeleton({})
        result = skel.bone_rotations()
        self.assertEqual(result, {})

    def test_bone_rotations_null_returns_empty(self):
        skel, client = self._make_skeleton(None)
        result = skel.bone_rotations()
        self.assertEqual(result, {})

    def test_bone_rotations_quat_single_call(self):
        payload = {
            "hip": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
            "rForeArm": {"x": 0.1, "y": 0.2, "z": 0.3, "w": 0.9},
        }
        skel, client = self._make_skeleton(payload)
        result = skel.bone_rotations_quat()
        self.assertEqual(client.execute.call_count, 1)
        self.assertEqual(result["hip"], {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0})
        self.assertEqual(result["rForeArm"], {"x": 0.1, "y": 0.2, "z": 0.3, "w": 0.9})

    def test_bone_rotations_quat_script_uses_getLocalRot(self):
        skel, client = self._make_skeleton({"hip": {"x": 0, "y": 0, "z": 0, "w": 1}})
        skel.bone_rotations_quat()
        script = client.execute.call_args[0][0]
        self.assertIn("getAllBones", script)
        self.assertIn("getLocalRot", script)

    def test_bone_rotations_quat_empty_skeleton(self):
        skel, client = self._make_skeleton({})
        result = skel.bone_rotations_quat()
        self.assertEqual(result, {})

    def test_bone_rotations_quat_null_returns_empty(self):
        skel, client = self._make_skeleton(None)
        result = skel.bone_rotations_quat()
        self.assertEqual(result, {})

    def test_set_bone_rotations_single_call(self):
        skel, client = self._make_skeleton(None)
        skel.set_bone_rotations({"hip": (10, 20, 30), "rForeArm": (0, 45, 0)})
        self.assertEqual(client.execute.call_count, 1)

    def test_set_bone_rotations_script_injects_data(self):
        skel, client = self._make_skeleton(None)
        skel.set_bone_rotations({"hip": [5.0, 10.0, 15.0]})
        script = client.execute.call_args[0][0]
        self.assertIn("hip", script)
        self.assertIn("5.0", script)
        self.assertIn("getAllBones", script)
        self.assertIn("getXRotControl", script)
        self.assertIn("setValue", script)

    def test_set_bone_rotations_accepts_tuples_and_lists(self):
        skel, client = self._make_skeleton(None)
        skel.set_bone_rotations({"hip": (1, 2, 3), "lForeArm": [4, 5, 6]})
        script = client.execute.call_args[0][0]
        self.assertIn("hip", script)
        self.assertIn("lForeArm", script)

    def test_morph_values_single_call(self):
        payload = {"PHMSmile": 0.75, "PHMFrown": 0.0}
        skel, client = self._make_skeleton(payload)
        result = skel.morph_values()
        self.assertEqual(client.execute.call_count, 1)
        self.assertAlmostEqual(result["PHMSmile"], 0.75)

    def test_morph_values_script_checks_DzMorph(self):
        skel, client = self._make_skeleton({})
        skel.morph_values()
        script = client.execute.call_args[0][0]
        self.assertIn("DzMorph", script)
        self.assertIn("getNumModifiers", script)
        self.assertIn("getValueChannel", script)

    def test_morph_values_nonzero_only_injects_true(self):
        skel, client = self._make_skeleton({})
        skel.morph_values(nonzero_only=True)
        script = client.execute.call_args[0][0]
        self.assertIn("true", script)
        self.assertIn("0.0001", script)

    def test_morph_values_all_injects_false(self):
        skel, client = self._make_skeleton({})
        skel.morph_values(nonzero_only=False)
        script = client.execute.call_args[0][0]
        self.assertIn("false", script)

    def test_morph_values_null_returns_empty(self):
        skel, client = self._make_skeleton(None)
        result = skel.morph_values()
        self.assertEqual(result, {})

    def test_set_morph_values_single_call(self):
        skel, client = self._make_skeleton(None)
        skel.set_morph_values({"PHMSmile": 0.5, "PHMFrown": 0.25})
        self.assertEqual(client.execute.call_count, 1)

    def test_set_morph_values_script_injects_data(self):
        skel, client = self._make_skeleton(None)
        skel.set_morph_values({"PHMSmile": 0.8})
        script = client.execute.call_args[0][0]
        self.assertIn("PHMSmile", script)
        self.assertIn("0.8", script)
        self.assertIn("DzMorph", script)
        self.assertIn("setValue", script)

    def test_set_morph_values_empty_dict(self):
        skel, client = self._make_skeleton(None)
        skel.set_morph_values({})
        self.assertEqual(client.execute.call_count, 1)

    # ── keyframe baking ───────────────────────────────────────────────────────

    def test_bake_bone_rotations_single_call(self):
        skel, client = self._make_skeleton({"frames_baked": 10, "bones_baked": 50})
        result = skel.bake_bone_rotations()
        self.assertEqual(client.execute.call_count, 1)
        self.assertEqual(result["frames_baked"], 10)
        self.assertEqual(result["bones_baked"], 50)

    def test_bake_bone_rotations_script_uses_insertKey(self):
        skel, client = self._make_skeleton({"frames_baked": 1, "bones_baked": 1})
        skel.bake_bone_rotations()
        script = client.execute.call_args[0][0]
        self.assertIn("insertKey", script)
        self.assertIn("getXRotControl", script)
        self.assertIn("getYRotControl", script)
        self.assertIn("getZRotControl", script)

    def test_bake_bone_rotations_script_scrubs_timeline(self):
        skel, client = self._make_skeleton({"frames_baked": 1, "bones_baked": 1})
        skel.bake_bone_rotations()
        script = client.execute.call_args[0][0]
        self.assertIn("getTimeStep", script)
        self.assertIn("getPlayRange", script)
        self.assertIn("setFrame", script)

    def test_bake_bone_rotations_restores_original_frame(self):
        skel, client = self._make_skeleton({"frames_baked": 1, "bones_baked": 1})
        skel.bake_bone_rotations()
        script = client.execute.call_args[0][0]
        self.assertIn("_origFrame", script)
        self.assertIn("Scene.setFrame(_origFrame)", script)

    def test_bake_bone_rotations_injects_start_end(self):
        skel, client = self._make_skeleton({"frames_baked": 5, "bones_baked": 1})
        skel.bake_bone_rotations(start=10, end=14)
        script = client.execute.call_args[0][0]
        self.assertIn("10", script)
        self.assertIn("14", script)

    def test_bake_bone_rotations_null_uses_play_range(self):
        skel, client = self._make_skeleton({"frames_baked": 1, "bones_baked": 1})
        skel.bake_bone_rotations()
        script = client.execute.call_args[0][0]
        self.assertIn("null", script)
        self.assertIn("_prStart", script)

    def test_bake_bone_rotations_bone_names_filter(self):
        skel, client = self._make_skeleton({"frames_baked": 1, "bones_baked": 2})
        skel.bake_bone_rotations(bone_names=["hip", "rForeArm"])
        script = client.execute.call_args[0][0]
        self.assertIn("hip", script)
        self.assertIn("rForeArm", script)
        self.assertIn("hasOwnProperty", script)

    def test_bake_bone_rotations_none_filter_includes_all(self):
        skel, client = self._make_skeleton({"frames_baked": 1, "bones_baked": 5})
        skel.bake_bone_rotations(bone_names=None)
        script = client.execute.call_args[0][0]
        # null filter means all bones
        self.assertIn("_filter === null", script)

    def test_bake_morphs_single_call(self):
        skel, client = self._make_skeleton({"frames_baked": 5, "morphs_baked": 3})
        result = skel.bake_morphs()
        self.assertEqual(client.execute.call_count, 1)
        self.assertEqual(result["morphs_baked"], 3)

    def test_bake_morphs_script_uses_DzMorph_insertKey(self):
        skel, client = self._make_skeleton({"frames_baked": 1, "morphs_baked": 1})
        skel.bake_morphs()
        script = client.execute.call_args[0][0]
        self.assertIn("DzMorph", script)
        self.assertIn("getValueChannel", script)
        self.assertIn("insertKey", script)

    def test_bake_morphs_restores_original_frame(self):
        skel, client = self._make_skeleton({"frames_baked": 1, "morphs_baked": 0})
        skel.bake_morphs()
        script = client.execute.call_args[0][0]
        self.assertIn("_origFrame", script)

    def test_bake_morphs_morph_names_filter(self):
        skel, client = self._make_skeleton({"frames_baked": 1, "morphs_baked": 1})
        skel.bake_morphs(morph_names=["PHMSmile"])
        script = client.execute.call_args[0][0]
        self.assertIn("PHMSmile", script)
        self.assertIn("hasOwnProperty", script)

    def test_bake_morphs_injects_start_end(self):
        skel, client = self._make_skeleton({"frames_baked": 3, "morphs_baked": 1})
        skel.bake_morphs(start=5, end=7)
        script = client.execute.call_args[0][0]
        self.assertIn("5", script)
        self.assertIn("7", script)

    def test_bake_single_call_combined(self):
        payload = {"frames_baked": 10, "bones_baked": 50, "morphs_baked": 0}
        skel, client = self._make_skeleton(payload)
        result = skel.bake()
        self.assertEqual(client.execute.call_count, 1)
        self.assertIn("bones_baked", result)
        self.assertIn("morphs_baked", result)

    def test_bake_without_morphs_guard_is_false(self):
        skel, client = self._make_skeleton({"frames_baked": 1, "bones_baked": 1, "morphs_baked": 0})
        skel.bake(include_morphs=False)
        script = client.execute.call_args[0][0]
        self.assertIn("false", script)  # _withMorphs = false

    def test_bake_with_morphs_guard_is_true(self):
        skel, client = self._make_skeleton({"frames_baked": 1, "bones_baked": 1, "morphs_baked": 5})
        skel.bake(include_morphs=True)
        script = client.execute.call_args[0][0]
        self.assertIn("true", script)   # _withMorphs = true
        self.assertIn("DzMorph", script)

    def test_bake_scrubs_timeline_once(self):
        """bake() iterates frames once for both bones and morphs."""
        skel, client = self._make_skeleton({"frames_baked": 5, "bones_baked": 3, "morphs_baked": 2})
        skel.bake(start=0, end=4, include_morphs=True)
        # One HTTP call regardless of bone/morph count
        self.assertEqual(client.execute.call_count, 1)

    def test_bake_bone_filter_and_morph_filter_both_injected(self):
        skel, client = self._make_skeleton({"frames_baked": 1, "bones_baked": 1, "morphs_baked": 1})
        skel.bake(bone_names=["hip"], include_morphs=True, morph_names=["PHMSmile"])
        script = client.execute.call_args[0][0]
        self.assertIn("hip", script)
        self.assertIn("PHMSmile", script)

    def test_bake_returns_empty_dict_on_null(self):
        skel, client = self._make_skeleton(None)
        result = skel.bake()
        self.assertEqual(result, {})


class TestDazSkeletonBoneAxes(unittest.TestCase):
    """bone_names() and set_bone_axes() (5d6f.29: morph-tool primitives)."""

    def _make_skeleton(self, return_value=None):
        from dazpy._skeleton import DazSkeleton
        client = mock_client(return_value)
        return DazSkeleton(client, NodeIdentifier("Genesis 9", kind="label")), client

    def test_bone_names_single_call(self):
        skel, client = self._make_skeleton(["hip", "spine4", "head"])
        self.assertEqual(skel.bone_names(), ["hip", "spine4", "head"])
        self.assertEqual(client.execute.call_count, 1)
        self.assertIn("getAllBones", client.execute.call_args[0][0])

    def test_bone_names_missing_skeleton_is_empty(self):
        skel, _ = self._make_skeleton(None)
        self.assertEqual(skel.bone_names(), [])

    def test_set_bone_axes_writes_only_named_axes(self):
        skel, client = self._make_skeleton([])
        skel.set_bone_axes({"spine4": {"x": 5.0}, "l_upperarm": {"z": -5.0, "y": 1.5}})
        self.assertEqual(client.execute.call_count, 1)
        script = client.execute.call_args[0][0]
        payload = json.loads(script.split("var _data = ", 1)[1].split(";\n", 1)[0])
        self.assertEqual(payload, {"spine4": {"x": 5.0}, "l_upperarm": {"z": -5.0, "y": 1.5}})
        self.assertIn("getXRotControl", script)
        self.assertIn("hasOwnProperty", script)

    def test_set_bone_axes_returns_missing_bones(self):
        skel, _ = self._make_skeleton(["lShldr"])
        self.assertEqual(skel.set_bone_axes({"lShldr": {"z": 3}, "hip": {"x": 1}}), ["lShldr"])

    def test_set_bone_axes_missing_skeleton_reports_all_missing(self):
        skel, _ = self._make_skeleton(None)
        self.assertEqual(sorted(skel.set_bone_axes({"a": {"x": 1}, "b": {"y": 2}})), ["a", "b"])

    def test_set_bone_axes_rejects_unknown_axis(self):
        skel, client = self._make_skeleton([])
        with self.assertRaises(ValueError):
            skel.set_bone_axes({"hip": {"w": 1.0}})
        client.execute.assert_not_called()

    def test_set_bone_axes_empty_is_noop(self):
        skel, client = self._make_skeleton([])
        self.assertEqual(skel.set_bone_axes({}), [])
        client.execute.assert_not_called()


class TestDazBoneInheritedNodeMethods(unittest.TestCase):
    """Inherited DazNode methods on a bone must resolve the bone through its own
    skeleton, not Scene.findNode(name): every Genesis figure has a bone named
    'head', so a name lookup reads whichever figure Studio finds first."""

    def _bone(self, value=None):
        from dazpy._skeleton import DazSkeleton
        client = mock_client(["head"])
        skel = DazSkeleton(client, NodeIdentifier("Genesis 8 Female", kind="label"))
        bone = skel.bones()[0]
        client.execute.return_value = ExecutionResult(value=value, output=[], request_id="t")
        return bone, client

    def _assert_skeleton_relative(self, script):
        self.assertIn("getSkeletonList", script)
        self.assertIn('"Genesis 8 Female"', script)
        self.assertIn('findBone("head")', script)
        self.assertNotIn('Scene.findNode("head")', script)

    def test_position(self):
        bone, client = self._bone({"x": 100, "y": 150, "z": 0})
        bone.position
        self._assert_skeleton_relative(client.execute.call_args[0][0])

    def test_label_and_visibility(self):
        bone, client = self._bone("Head")
        bone.label
        self._assert_skeleton_relative(client.execute.call_args[0][0])
        bone.set_visible_in_viewport(True)
        self._assert_skeleton_relative(client.execute.call_args[0][0])

    def test_plain_node_lookup_unchanged(self):
        client = mock_client({"x": 0, "y": 0, "z": 0})
        DazNode(client, NodeIdentifier("Chair")).position
        self.assertIn('Scene.findNode("Chair")', client.execute.call_args[0][0])


class TestSkeletonLookAt(unittest.TestCase):
    def _skel(self, value):
        from dazpy._skeleton import DazSkeleton
        client = mock_client(value)
        return DazSkeleton(client, NodeIdentifier("4", kind="element_id")), client

    def test_look_at_one_call_parent_frame(self):
        skel, client = self._skel({"applied": [{"bone": "head", "x": -10.0, "y": 20.0}],
                                   "missing": ["l_eye"]})
        r = skel.look_at((0, 160, 200), [("head", 0.6), ("l_eye", 1.0)])
        self.assertEqual(client.execute.call_count, 1)
        self.assertEqual(r.applied[0].bone, "head")
        self.assertEqual(r.missing, ["l_eye"])
        script = client.execute.call_args[0][0]
        self.assertIn("getWSRot()", script)
        self.assertIn("getOrientation()", script)
        self.assertIn(".inverse().multVec(", script)
        self.assertIn('[["head", 0.6], ["l_eye", 1.0]]', script)

    def test_look_at_rejects_bad_weight(self):
        skel, client = self._skel(None)
        with self.assertRaises(ValueError):
            skel.look_at((0, 0, 0), [("head", 1.5)])
        client.execute.assert_not_called()

    def test_look_at_missing_skeleton(self):
        skel, _ = self._skel(None)
        with self.assertRaises(exceptions.NodeNotFoundError):
            skel.look_at((0, 0, 0), [("head", 1.0)])


class TestDazBoneScriptGeneration(unittest.TestCase):
    def setUp(self):
        from dazpy._bone import DazBone
        self.DazBone = DazBone

    def _make_bone(self, return_value=None):
        client = mock_client(return_value)
        bone = self.DazBone(client, NodeIdentifier("hip"))
        return bone, client

    def test_local_rotation_returns_xyzw(self):
        bone, client = self._make_bone({"x": 0.0, "y": 0.1, "z": 0.0, "w": 0.995})
        rot = bone.local_rotation
        self.assertIn("w", rot)
        script = client.execute.call_args[0][0]
        self.assertIn("getLocalRot", script)
        self.assertIn("r.w", script)

    def test_set_local_rotation_uses_axis_controls(self):
        bone, client = self._make_bone(None)
        bone.set_local_rotation(10.0, 20.0, 30.0)
        script = client.execute.call_args[0][0]
        self.assertIn("getXRotControl", script)
        self.assertIn("getYRotControl", script)
        self.assertIn("getZRotControl", script)
        self.assertIn("setValue", script)
        self.assertIn("10.0", script)
        self.assertIn("20.0", script)
        self.assertIn("30.0", script)

    def test_local_position_returns_xyz(self):
        bone, client = self._make_bone({"x": 1.0, "y": 2.0, "z": 3.0})
        pos = bone.local_position
        self.assertEqual(pos["x"], 1.0)
        script = client.execute.call_args[0][0]
        self.assertIn("getLocalPos", script)

    def test_rotation_order_calls_getRotationOrder(self):
        bone, client = self._make_bone("XYZ")
        order = bone.rotation_order
        self.assertEqual(order, "XYZ")
        script = client.execute.call_args[0][0]
        # getRotationOrder() returns a DzRotationOrder object, which
        # JSON-serializes to "" unless converted explicitly.
        self.assertIn("getRotationOrder().toString()", script)

    def test_get_skeleton_returns_daz_skeleton(self):
        from dazpy._skeleton import DazSkeleton
        bone, client = self._make_bone("Genesis9")
        skel = bone.get_skeleton()
        self.assertIsInstance(skel, DazSkeleton)
        script = client.execute.call_args[0][0]
        self.assertIn("getSkeleton", script)

    def test_get_skeleton_returns_none_when_null(self):
        bone, client = self._make_bone(None)
        skel = bone.get_skeleton()
        self.assertIsNone(skel)


class TestDazPose(unittest.TestCase):
    """Unit tests for DazPose — no server required."""

    def _make_skeleton(self, capture_result=None):
        from dazpy._skeleton import DazSkeleton
        client = mock_client(capture_result)
        skel = DazSkeleton(client, NodeIdentifier("Genesis 9", kind="label"))
        return skel, client

    # ── lerp (pure Python) ────────────────────────────────────────────────────

    def test_lerp_midpoint_bones(self):
        from dazpy import DazPose
        a = DazPose("fig", bones={"hip": [0.0, 0.0, 0.0]}, morphs={}, props={})
        b = DazPose("fig", bones={"hip": [10.0, 20.0, 30.0]}, morphs={}, props={})
        mid = a.lerp(b, 0.5)
        self.assertAlmostEqual(mid.bones["hip"][0], 5.0)
        self.assertAlmostEqual(mid.bones["hip"][1], 10.0)
        self.assertAlmostEqual(mid.bones["hip"][2], 15.0)

    def test_lerp_missing_key_treated_as_zero(self):
        from dazpy import DazPose
        a = DazPose("fig", bones={}, morphs={}, props={})
        b = DazPose("fig", bones={"rForeArm": [0.0, 0.0, -45.0]}, morphs={}, props={})
        mid = a.lerp(b, 0.5)
        self.assertAlmostEqual(mid.bones["rForeArm"][2], -22.5)

    def test_lerp_t0_equals_self(self):
        from dazpy import DazPose
        a = DazPose("fig", bones={"hip": [1.0, 2.0, 3.0]}, morphs={"smile": 0.8}, props={})
        b = DazPose("fig", bones={"hip": [9.0, 8.0, 7.0]}, morphs={"smile": 0.0}, props={})
        result = a.lerp(b, 0.0)
        self.assertAlmostEqual(result.bones["hip"][0], 1.0)
        self.assertAlmostEqual(result.morphs["smile"], 0.8)

    def test_lerp_t1_equals_other(self):
        from dazpy import DazPose
        a = DazPose("fig", bones={"hip": [0.0, 0.0, 0.0]}, morphs={"smile": 0.0}, props={})
        b = DazPose("fig", bones={"hip": [9.0, 8.0, 7.0]}, morphs={"smile": 1.0}, props={})
        result = a.lerp(b, 1.0)
        self.assertAlmostEqual(result.bones["hip"][0], 9.0)
        self.assertAlmostEqual(result.morphs["smile"], 1.0)

    def test_lerp_morphs_union_of_keys(self):
        from dazpy import DazPose
        a = DazPose("fig", bones={}, morphs={"morphA": 1.0}, props={})
        b = DazPose("fig", bones={}, morphs={"morphB": 1.0}, props={})
        mid = a.lerp(b, 0.5)
        self.assertIn("morphA", mid.morphs)
        self.assertIn("morphB", mid.morphs)
        self.assertAlmostEqual(mid.morphs["morphA"], 0.5)
        self.assertAlmostEqual(mid.morphs["morphB"], 0.5)

    def test_lerp_preserves_figure_label_from_self(self):
        from dazpy import DazPose
        a = DazPose("FigureA", bones={}, morphs={}, props={})
        b = DazPose("FigureB", bones={}, morphs={}, props={})
        result = a.lerp(b, 0.5)
        self.assertEqual(result.figure, "FigureA")

    # ── serialisation ─────────────────────────────────────────────────────────

    def test_to_dict_round_trip(self):
        from dazpy import DazPose
        pose = DazPose("fig", {"hip": [1.0, 2.0, 3.0]}, {"smile": 0.5}, {"facs": 0.3})
        d = pose.to_dict()
        restored = DazPose(d["figure"], d["bones"], d["morphs"], d["props"])
        self.assertEqual(restored.bones, pose.bones)
        self.assertEqual(restored.morphs, pose.morphs)
        self.assertEqual(restored.props, pose.props)

    def test_save_load_round_trip(self):
        import os, tempfile
        from dazpy import DazPose
        pose = DazPose("Genesis 9", {"hip": [0.0, 5.0, 0.0]}, {"PHMSmile": 0.7}, {"facs": 0.2})
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            pose.save(path)
            loaded = DazPose.load(path)
            self.assertEqual(loaded.figure, "Genesis 9")
            self.assertAlmostEqual(loaded.morphs["PHMSmile"], 0.7)
            self.assertEqual(loaded.bones["hip"], [0.0, 5.0, 0.0])
        finally:
            os.unlink(path)

    def test_load_tolerates_missing_keys(self):
        import json, tempfile, os
        from dazpy import DazPose
        data = {"figure": "MyFig"}
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump(data, f)
            path = f.name
        try:
            pose = DazPose.load(path)
            self.assertEqual(pose.figure, "MyFig")
            self.assertEqual(pose.bones, {})
            self.assertEqual(pose.morphs, {})
            self.assertEqual(pose.props, {})
        finally:
            os.unlink(path)

    # ── capture script generation ─────────────────────────────────────────────

    def test_capture_executes_single_call(self):
        from dazpy import DazPose
        skel, client = self._make_skeleton({"bones": {}, "morphs": {}, "props": {}})
        DazPose.capture(skel)
        self.assertEqual(client.execute.call_count, 1)

    def test_capture_script_contains_getAllBones(self):
        from dazpy import DazPose
        skel, client = self._make_skeleton({"bones": {}, "morphs": {}, "props": {}})
        DazPose.capture(skel)
        script = client.execute.call_args[0][0]
        self.assertIn("getAllBones", script)

    def test_capture_script_reads_morphs(self):
        from dazpy import DazPose
        skel, client = self._make_skeleton({"bones": {}, "morphs": {}, "props": {}})
        DazPose.capture(skel)
        script = client.execute.call_args[0][0]
        self.assertIn("getValueChannel", script)
        self.assertIn("DzMorph", script)

    def test_capture_bones_prefer_raw_value(self):
        # Regression: bone rotation controls can be ERC targets (e.g.
        # auto-follow bend/twist ratios), so capture() must feature-detect
        # getRawValue() for them the same way it already does for
        # morphs/props, instead of always reading the post-ERC getValue().
        from dazpy import DazPose
        skel, client = self._make_skeleton({"bones": {}, "morphs": {}, "props": {}})
        DazPose.capture(skel)
        script = client.execute.call_args[0][0]
        self.assertIn('typeof xc.getRawValue === "function"', script)
        self.assertIn('typeof yc.getRawValue === "function"', script)
        self.assertIn('typeof zc.getRawValue === "function"', script)

    def test_capture_raises_on_null_result(self):
        from dazpy import DazPose
        from dazpy.exceptions import NodeNotFoundError
        skel, _ = self._make_skeleton(None)
        with self.assertRaises(NodeNotFoundError):
            DazPose.capture(skel)

    def test_capture_returns_pose_with_correct_figure(self):
        from dazpy import DazPose
        skel, _ = self._make_skeleton({"bones": {"hip": [0, 5, 0]}, "morphs": {}, "props": {}})
        pose = DazPose.capture(skel)
        self.assertEqual(pose.figure, "Genesis 9")
        self.assertIn("hip", pose.bones)

    # ── apply script generation ───────────────────────────────────────────────

    def test_apply_executes_single_call(self):
        from dazpy import DazPose
        pose = DazPose("Genesis 9", {"hip": [0, 5, 0]}, {"smile": 0.5}, {})
        skel, client = self._make_skeleton(True)
        pose.apply(skel)
        self.assertEqual(client.execute.call_count, 1)

    def test_apply_script_contains_bone_data(self):
        from dazpy import DazPose
        pose = DazPose("Genesis 9", {"rForeArm": [0.0, 0.0, -45.0]}, {}, {})
        skel, client = self._make_skeleton(True)
        pose.apply(skel)
        script = client.execute.call_args[0][0]
        self.assertIn("rForeArm", script)
        self.assertIn("-45", script)
        self.assertIn("getXRotControl", script)

    def test_apply_bones_prefer_raw_value(self):
        # Regression: apply() must feature-detect setRawValue for bone
        # rotation controls too, not just morphs/props (see
        # test_capture_bones_prefer_raw_value).
        from dazpy import DazPose
        pose = DazPose("Genesis 9", {"rForeArm": [0.0, 0.0, -45.0]}, {}, {})
        skel, client = self._make_skeleton(True)
        pose.apply(skel)
        script = client.execute.call_args[0][0]
        self.assertIn('typeof xc.setRawValue === "function"', script)
        self.assertIn('typeof yc.setRawValue === "function"', script)
        self.assertIn('typeof zc.setRawValue === "function"', script)

    def test_apply_script_contains_morph_data(self):
        from dazpy import DazPose
        pose = DazPose("Genesis 9", {}, {"PHMSmile": 0.75}, {})
        skel, client = self._make_skeleton(True)
        pose.apply(skel)
        script = client.execute.call_args[0][0]
        self.assertIn("PHMSmile", script)
        self.assertIn("0.75", script)

    def test_apply_script_uses_json_injection(self):
        """apply() should inject bone/morph data as JSON dicts, not inline per-bone JS."""
        from dazpy import DazPose
        pose = DazPose("Genesis 9", {"hip": [1, 2, 3], "spine": [4, 5, 6]}, {}, {})
        skel, client = self._make_skeleton(True)
        pose.apply(skel)
        script = client.execute.call_args[0][0]
        # Should loop over getAllBones(), not call findBone() per bone
        self.assertIn("getAllBones", script)

    def test_apply_full_zeroes_absent_bones(self):
        from dazpy import DazPose
        pose = DazPose("Genesis 9", {}, {}, {})
        skel, client = self._make_skeleton(True)
        pose.apply_full(skel)
        script = client.execute.call_args[0][0]
        # Should fall back to [0, 0, 0] for bones not in the pose
        self.assertIn("_bones[b.getName()] || [0, 0, 0]", script)

    def test_apply_full_bones_prefer_raw_value(self):
        # Regression: bone rotation controls can be ERC targets (e.g.
        # auto-follow bend/twist ratios) just like morphs/props, so
        # apply_full() must feature-detect setRawValue for them too instead
        # of always using setValue(), which would re-inflate the total on
        # every capture/apply cycle.
        from dazpy import DazPose
        pose = DazPose("Genesis 9", {"hip": [1.0, 2.0, 3.0]}, {}, {})
        skel, client = self._make_skeleton(True)
        pose.apply_full(skel)
        script = client.execute.call_args[0][0]
        self.assertIn('typeof xc.setRawValue === "function"', script)
        self.assertIn('typeof yc.setRawValue === "function"', script)
        self.assertIn('typeof zc.setRawValue === "function"', script)

    def test_apply_full_zeroes_absent_node_properties(self):
        # Regression: unlike the bones (explicit else-zero) and morphs (`_v =
        # v !== undefined ? v : 0`) loops right above it, the node-property
        # loop only wrote a value `if (v !== undefined)`, leaving properties
        # absent from the captured pose unchanged instead of reverting to 0.
        from dazpy import DazPose
        pose = DazPose("Genesis 9", {}, {}, {})
        skel, client = self._make_skeleton(True)
        pose.apply_full(skel)
        script = client.execute.call_args[0][0]
        props_section = script[script.index("getNumProperties"):]
        self.assertIn("var _v = (v !== undefined) ? v : 0;", props_section)
        self.assertIn("setRawValue(_v)", props_section)
        self.assertIn("setValue(_v)", props_section)
        self.assertNotIn("if (v !== undefined)", props_section)

    def test_apply_full_skips_non_numeric_node_properties(self):
        # Regression (found live, DS 4.24): a figure carrying DzFileProperty
        # entries ("Preview Clothing Template", "Developer Tools") made
        # apply_full() call setValue(0) on them, and Studio rejected the whole
        # script ("Passing incompatible arguments to C++ functions"). capture()
        # only records number-valued properties, so apply_full() must only
        # zero those too -- which also leaves "Point At" / "Fit to" alone.
        from dazpy import DazPose
        pose = DazPose("Genesis 9", {}, {}, {})
        skel, client = self._make_skeleton(True)
        pose.apply_full(skel)
        script = client.execute.call_args[0][0]
        props_section = script[script.index("getNumProperties"):]
        guard = props_section.index('typeof _cur !== "number"')
        self.assertLess(guard, props_section.index("setValue(_v)"))

    # ── repr ──────────────────────────────────────────────────────────────────

    def test_repr(self):
        from dazpy import DazPose
        pose = DazPose("Genesis 9", {"hip": [0, 0, 0]}, {"smile": 0.5}, {})
        r = repr(pose)
        self.assertIn("Genesis 9", r)
        self.assertIn("bones=1", r)
        self.assertIn("morphs=1", r)


class TestApplyPose(unittest.TestCase):
    def _make_skeleton(self, capture_result=None):
        from dazpy._skeleton import DazSkeleton
        client = mock_client(capture_result)
        skel = DazSkeleton(client, NodeIdentifier("Genesis 9", kind="label"))
        return skel, client

    def test_apply_pose_with_dazpose_instance_delegates_to_apply(self):
        from dazpy.poses import apply_pose
        skeleton = MagicMock()
        pose = MagicMock()
        apply_pose(skeleton, pose)
        pose.apply.assert_called_once_with(skeleton)

    def test_apply_pose_with_dazpose_instance_does_not_call_load(self):
        from dazpy.poses import apply_pose
        from dazpy._pose import DazPose
        skeleton = MagicMock()
        pose = MagicMock()
        with patch.object(DazPose, "load") as mock_load:
            apply_pose(skeleton, pose)
        mock_load.assert_not_called()

    def test_apply_pose_with_path_loads_then_applies(self):
        import json
        import os
        import tempfile
        from dazpy.poses import apply_pose

        data = {"figure": "Genesis 9", "bones": {"hip": [0.0, 5.0, 0.0]}, "morphs": {}, "props": {}}
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump(data, f)
            path = f.name
        try:
            skel, client = self._make_skeleton(True)
            apply_pose(skel, path)
            self.assertEqual(client.execute.call_count, 1)
            script = client.execute.call_args[0][0]
            self.assertIn("hip", script)
        finally:
            os.unlink(path)

    def test_apply_pose_with_path_accepts_pathlib_path(self):
        import json
        import os
        import tempfile
        from pathlib import Path
        from dazpy.poses import apply_pose

        data = {"figure": "Genesis 9", "bones": {}, "morphs": {"PHMSmile": 0.5}, "props": {}}
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump(data, f)
            path = f.name
        try:
            skel, client = self._make_skeleton(True)
            apply_pose(skel, Path(path))
            script = client.execute.call_args[0][0]
            self.assertIn("PHMSmile", script)
        finally:
            os.unlink(path)


class TestResetTransforms(unittest.TestCase):
    def test_reset_transforms_calls_set_transform_once(self):
        from dazpy.poses import reset_transforms
        node = MagicMock()
        reset_transforms(node)
        node.set_transform.assert_called_once_with(
            position=(0.0, 0.0, 0.0),
            rotation=(0.0, 0.0, 0.0),
            scale=(1.0, 1.0, 1.0),
        )

    def test_reset_transforms_issues_exactly_one_call(self):
        from dazpy._node import DazNode
        from dazpy.poses import reset_transforms

        client = mock_client(None)
        node = DazNode(client, NodeIdentifier("SomeCamera"))
        reset_transforms(node)
        self.assertEqual(client.execute.call_count, 1)
        script = client.execute.call_args[0][0]
        self.assertIn("setLocalPos", script)
        self.assertIn("getXRotControl", script)
        self.assertIn("getXScaleControl", script)


class TestZeroFigure(unittest.TestCase):
    def _make_skeleton(self, capture_result=None):
        from dazpy._skeleton import DazSkeleton
        client = mock_client(capture_result)
        skel = DazSkeleton(client, NodeIdentifier("Genesis 9", kind="label"))
        return skel, client

    def test_include_props_true_zeroes_bones_morphs_and_props_via_apply_full(self):
        from dazpy.poses import zero_figure
        skel, client = self._make_skeleton(True)
        zero_figure(skel, include_props=True)
        self.assertEqual(client.execute.call_count, 1)
        script = client.execute.call_args[0][0]
        # apply_full()'s signature zeroing behavior — see DazPose.apply_full tests.
        self.assertIn("_bones[b.getName()] || [0, 0, 0]", script)
        self.assertIn("var _v = (v !== undefined) ? v : 0;", script)

    def test_include_props_true_does_not_touch_root_transform(self):
        from dazpy.poses import zero_figure
        skel, client = self._make_skeleton(True)
        zero_figure(skel, include_props=True)
        script = client.execute.call_args[0][0]
        self.assertNotIn("setLocalPos", script)
        self.assertNotIn("setWSPos", script)

    def test_default_zeroes_only_bones_and_morphs(self):
        """The new default (include_props omitted) must take the bones/morphs-only path,
        never the apply_full path — that's what guarantees root transform is untouched.
        Since Task 2C, this path is a single generated script (see
        TestZeroFigureDefaultPath), not per-bone/per-morph client calls."""
        from dazpy.poses import zero_figure
        skeleton = MagicMock()

        zero_figure(skeleton)

        skeleton._zero_bones_and_morphs.assert_called_once_with()

    def test_include_props_false_zeroes_only_bones_and_morphs(self):
        from dazpy.poses import zero_figure
        skeleton = MagicMock()

        zero_figure(skeleton, include_props=False)

        skeleton._zero_bones_and_morphs.assert_called_once_with()

    def test_include_props_false_does_not_use_dazpose(self):
        from dazpy.poses import zero_figure
        skeleton = MagicMock()

        zero_figure(skeleton, include_props=False)

        skeleton._client.execute.assert_not_called()


class TestPosesExports(unittest.TestCase):
    def test_poses_symbols_importable_from_top_level_package(self):
        import dazpy
        self.assertTrue(hasattr(dazpy, "apply_pose"))
        self.assertTrue(hasattr(dazpy, "reset_transforms"))
        self.assertTrue(hasattr(dazpy, "zero_figure"))
        self.assertIn("apply_pose", dazpy.__all__)
        self.assertIn("reset_transforms", dazpy.__all__)
        self.assertIn("zero_figure", dazpy.__all__)


class TestBatchPoseEvaluation(unittest.TestCase):
    """Tests for DazSkeleton.evaluate_pose() and evaluate_pose_jacobian()."""

    def _make_skeleton_client(self, return_value):
        from dazpy._skeleton import DazSkeleton
        client = mock_client(return_value)
        skel = DazSkeleton.__new__(DazSkeleton)
        from dazpy._node import NodeIdentifier
        object.__setattr__(skel, "_client", client)
        object.__setattr__(skel, "_identifier", NodeIdentifier("Genesis 9", kind="label"))
        return skel, client

    def test_evaluate_pose_script_contains_save_apply_restore(self):
        skel, client = self._make_skeleton_client({"r_hand": [10.0, 20.0, 30.0]})
        skel.evaluate_pose({"hip": (5.0, 0.0, 0.0)}, ["r_hand"])
        script = client.execute.call_args[0][0]
        self.assertIn("_originals", script)
        self.assertIn("getWSPos", script)
        self.assertIn('"hip"', script)
        self.assertIn('"r_hand"', script)

    def test_evaluate_pose_returns_typed_tuples(self):
        skel, client = self._make_skeleton_client({"r_hand": [1.0, 2.0, 3.0]})
        result = skel.evaluate_pose({"hip": (0.0, 0.0, 0.0)}, ["r_hand"])
        self.assertEqual(result, {"r_hand": (1.0, 2.0, 3.0)})

    def test_evaluate_pose_empty_response(self):
        skel, client = self._make_skeleton_client({})
        result = skel.evaluate_pose({}, [])
        self.assertEqual(result, {})

    def test_evaluate_pose_jacobian_script_contains_perturbation(self):
        skel, client = self._make_skeleton_client(
            {"base_position": [0.0, 150.0, 0.0], "columns": [[1.0, 0.0, 0.0]] * 9}
        )
        skel.evaluate_pose_jacobian(["hip", "spine", "chest"], "r_hand", step_degrees=2.0)
        script = client.execute.call_args[0][0]
        self.assertIn("getWSPos", script)
        self.assertIn("_columns", script)
        self.assertIn("setValue(_orig + _step)", script)
        self.assertIn("2.0", script)

    def test_evaluate_pose_jacobian_chain_serialized(self):
        skel, client = self._make_skeleton_client(
            {"base_position": [0.0, 0.0, 0.0], "columns": []}
        )
        skel.evaluate_pose_jacobian(["hip", "r_hand"], "r_hand")
        script = client.execute.call_args[0][0]
        self.assertIn('"hip"', script)
        self.assertIn('"r_hand"', script)

    def test_evaluate_pose_jacobian_returns_none_on_missing_effector(self):
        skel, client = self._make_skeleton_client(None)
        result = skel.evaluate_pose_jacobian(["hip"], "missing_bone")
        self.assertIsNone(result)

    def test_align_single_limb_uses_batch_path_when_client_present(self):
        """align_single_limb_target dispatches to batch path for real skeletons."""
        from dazpy import align_single_limb_target, FigureRigProfile, BoneProfile
        from dazpy._skeleton import DazSkeleton
        from dazpy._node import NodeIdentifier
        from dazpy._interaction import ResolvedInteractionTarget

        # Build a minimal profile
        hip = BoneProfile(name="hip")
        r_hand = BoneProfile(name="r_hand", parent_name="hip")
        profile = FigureRigProfile(figure_label="Test", family="genesis_9", bones=[hip, r_hand])

        target = ResolvedInteractionTarget(
            figure_label="Test",
            anchor_name="r_hand",
            bone_name="r_hand",
            target_point=(10.0, 150.0, 0.0),
        )

        call_log = []

        def _execute(script):
            call_log.append(script)
            if "getAllBones" in script and "_result" not in script and "_columns" not in script:
                # bone_rotations()
                return ExecutionResult(value={"hip": [0.0, 0.0, 0.0], "r_hand": [0.0, 0.0, 0.0]}, output=[], request_id="x")
            if "_columns" in script:
                # evaluate_pose_jacobian
                return ExecutionResult(
                    value={"base_position": [0.0, 150.0, 0.0], "columns": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]] * 2},
                    output=[], request_id="x",
                )
            # set_bone_rotations
            return ExecutionResult(value=None, output=[], request_id="x")

        client = MagicMock(spec=DazClient)
        client.execute.side_effect = _execute

        skel = DazSkeleton(client, NodeIdentifier("Test", kind="label"))

        result = align_single_limb_target(skel, profile, target)

        self.assertEqual(result.diagnostics.get("path"), "batch")
        self.assertIsNotNone(result.initial_error)

    def test_align_single_limb_batch_already_aligned(self):
        """Batch path returns converged immediately when already within tolerance."""
        from dazpy import align_single_limb_target, FigureRigProfile, BoneProfile
        from dazpy._skeleton import DazSkeleton
        from dazpy._node import NodeIdentifier
        from dazpy._interaction import ResolvedInteractionTarget

        hip = BoneProfile(name="hip")
        r_hand = BoneProfile(name="r_hand", parent_name="hip")
        profile = FigureRigProfile(figure_label="Test", family="genesis_9", bones=[hip, r_hand])

        target = ResolvedInteractionTarget(
            figure_label="Test",
            anchor_name="r_hand",
            bone_name="r_hand",
            target_point=(0.0, 150.0, 0.0),  # exactly at base_position
        )

        def _execute(script):
            if "_columns" in script:
                return ExecutionResult(
                    value={"base_position": [0.0, 150.0, 0.0], "columns": [[1, 0, 0]] * 6},
                    output=[], request_id="x",
                )
            return ExecutionResult(value={"hip": [0, 0, 0], "r_hand": [0, 0, 0]}, output=[], request_id="x")

        client = MagicMock(spec=DazClient)
        client.execute.side_effect = _execute

        skel = DazSkeleton(client, NodeIdentifier("Test", kind="label"))

        result = align_single_limb_target(skel, profile, target, tolerance=0.5)

        self.assertTrue(result.converged)
        self.assertEqual(result.iterations, 0)
        self.assertEqual(result.diagnostics.get("reason"), "already_aligned")


class TestZeroFigureDefaultPath(unittest.TestCase):
    def test_default_mode_issues_exactly_one_call(self):
        client = mock_client(None)
        from dazpy._skeleton import DazSkeleton
        from dazpy._node import NodeIdentifier
        from dazpy.poses import zero_figure
        skel = DazSkeleton(client, NodeIdentifier("name", "Genesis9"))
        zero_figure(skel)
        self.assertEqual(client.execute.call_count, 1)
        script = client.execute.call_args[0][0]
        self.assertIn("getAllBones", script)
        self.assertIn("DzMorph", script)

    def test_default_mode_zeroes_bones_and_nonzero_morphs_only(self):
        client = mock_client(None)
        from dazpy._skeleton import DazSkeleton
        from dazpy._node import NodeIdentifier
        from dazpy.poses import zero_figure
        skel = DazSkeleton(client, NodeIdentifier("name", "Genesis9"))
        zero_figure(skel)
        script = client.execute.call_args[0][0]
        self.assertIn("setValue(0)", script)

    def test_include_props_true_still_uses_apply_full(self):
        client = mock_client(None)
        from dazpy._skeleton import DazSkeleton
        from dazpy._node import NodeIdentifier
        from dazpy.poses import zero_figure
        skel = DazSkeleton(client, NodeIdentifier("name", "Genesis9"))
        with patch("dazpy._pose.DazPose.apply_full") as mock_apply_full:
            zero_figure(skel, include_props=True)
        mock_apply_full.assert_called_once()


class TestDazSkeletonSetState(unittest.TestCase):
    def test_all_three_kinds_issue_one_call(self):
        client = mock_client(None)
        from dazpy._skeleton import DazSkeleton
        from dazpy._node import NodeIdentifier
        skel = DazSkeleton(client, NodeIdentifier("name", "Genesis9"))
        skel.set_state(
            bones={"Hip": (0.0, 0.0, 0.0)},
            morphs={"Smile": 0.8},
            props={"Scale": 100.0},
        )
        self.assertEqual(client.execute.call_count, 1)
        script = client.execute.call_args[0][0]
        self.assertIn("getAllBones", script)
        self.assertIn("DzMorph", script)
        self.assertIn("getNumProperties", script)

    def test_omitted_kind_not_present_in_script(self):
        client = mock_client(None)
        from dazpy._skeleton import DazSkeleton
        from dazpy._node import NodeIdentifier
        skel = DazSkeleton(client, NodeIdentifier("name", "Genesis9"))
        skel.set_state(bones={"Hip": (0.0, 0.0, 0.0)})
        script = client.execute.call_args[0][0]
        self.assertIn("getAllBones", script)
        self.assertNotIn("DzMorph", script)
        self.assertNotIn("getNumProperties", script)

    def test_all_omitted_is_a_noop(self):
        client = mock_client(None)
        from dazpy._skeleton import DazSkeleton
        from dazpy._node import NodeIdentifier
        skel = DazSkeleton(client, NodeIdentifier("name", "Genesis9"))
        skel.set_state()
        client.execute.assert_not_called()

    def test_bone_and_morph_names_with_quotes_are_json_safe(self):
        client = mock_client(None)
        from dazpy._skeleton import DazSkeleton
        from dazpy._node import NodeIdentifier
        skel = DazSkeleton(client, NodeIdentifier("name", "Genesis9"))
        skel.set_state(bones={'Weird "Bone"': (1.0, 2.0, 3.0)}, morphs={"Back\\Slash": 0.5})
        script = client.execute.call_args[0][0]
        self.assertIn(json.dumps({'Weird "Bone"': [1.0, 2.0, 3.0]}), script)
        self.assertIn(json.dumps({"Back\\Slash": 0.5}), script)


if __name__ == "__main__":
    unittest.main()
