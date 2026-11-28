"""dazpy unit tests: DazAnimation capture and clip operations.

Mock-based; no server or DAZ Studio required.
Shared fakes live in tests/dazpy_fakes.py.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dazpy._node import NodeIdentifier
from dazpy_fakes import mock_client


class TestDazAnimation(unittest.TestCase):
    """Unit tests for DazAnimation — no server required."""

    def _make_skeleton(self, capture_result=None):
        from dazpy._skeleton import DazSkeleton
        client = mock_client(capture_result)
        skel = DazSkeleton(client, NodeIdentifier("Genesis 9", kind="label"))
        return skel, client

    def _sample_result(self, n_frames=3, n_bones=2, with_morphs=False):
        bones = ["hip", "spine"][:n_bones]
        frames = []
        for f in range(n_frames):
            frame = {
                "frame": f,
                "rotations": [[0.0, float(f), 0.0]] * n_bones,
                "morphs": {"PHMSmile": 0.5} if with_morphs else {},
            }
            frames.append(frame)
        return {
            "figure": "Genesis 9",
            "frame_range": {"start": 0, "end": n_frames - 1},
            "bones": bones,
            "frames": frames,
        }

    # ── capture script generation ─────────────────────────────────────────────

    def test_capture_executes_single_call(self):
        from dazpy import DazAnimation
        skel, client = self._make_skeleton(self._sample_result())
        DazAnimation.capture(skel)
        self.assertEqual(client.execute.call_count, 1)

    def test_capture_single_call_also_with_morphs(self):
        from dazpy import DazAnimation
        skel, client = self._make_skeleton(self._sample_result(with_morphs=True))
        DazAnimation.capture(skel, include_morphs=True)
        self.assertEqual(client.execute.call_count, 1)

    def test_capture_script_contains_getAllBones(self):
        from dazpy import DazAnimation
        skel, client = self._make_skeleton(self._sample_result())
        DazAnimation.capture(skel)
        script = client.execute.call_args[0][0]
        self.assertIn("getAllBones", script)

    def test_capture_script_scrubs_frames(self):
        from dazpy import DazAnimation
        skel, client = self._make_skeleton(self._sample_result())
        DazAnimation.capture(skel)
        script = client.execute.call_args[0][0]
        self.assertIn("setFrame", script)
        self.assertIn("getPlayRange", script)

    def test_capture_script_restores_original_frame(self):
        from dazpy import DazAnimation
        skel, client = self._make_skeleton(self._sample_result())
        DazAnimation.capture(skel)
        script = client.execute.call_args[0][0]
        self.assertIn("_origFrame", script)
        self.assertIn("Scene.setFrame(_origFrame)", script)

    def test_capture_script_morph_detection_disabled_by_default(self):
        from dazpy import DazAnimation
        skel, client = self._make_skeleton(self._sample_result())
        DazAnimation.capture(skel)
        script = client.execute.call_args[0][0]
        self.assertIn("if (false)", script)

    def test_capture_script_morph_detection_enabled(self):
        from dazpy import DazAnimation
        skel, client = self._make_skeleton(self._sample_result(with_morphs=True))
        DazAnimation.capture(skel, include_morphs=True)
        script = client.execute.call_args[0][0]
        self.assertIn("if (true)", script)
        self.assertIn("isVaryingMorph", script)
        self.assertIn("getValueChannel", script)

    def test_capture_raises_on_null_result(self):
        from dazpy import DazAnimation
        from dazpy.exceptions import NodeNotFoundError
        skel, _ = self._make_skeleton(None)
        with self.assertRaises(NodeNotFoundError):
            DazAnimation.capture(skel)

    def test_capture_returns_animation_with_correct_attributes(self):
        from dazpy import DazAnimation
        skel, _ = self._make_skeleton(self._sample_result(n_frames=5, n_bones=2))
        anim = DazAnimation.capture(skel)
        self.assertEqual(anim.figure, "Genesis 9")
        self.assertEqual(anim.frame_count, 5)
        self.assertEqual(anim.bone_count, 2)
        self.assertEqual(anim.frame_range, {"start": 0, "end": 4})

    # ── serialisation ─────────────────────────────────────────────────────────

    def test_to_dict_round_trip(self):
        from dazpy import DazAnimation
        skel, _ = self._make_skeleton(self._sample_result())
        anim = DazAnimation.capture(skel)
        d = anim.to_dict()
        self.assertIn("figure", d)
        self.assertIn("bones", d)
        self.assertIn("frames", d)
        self.assertIn("frame_range", d)

    def test_save_load_round_trip(self):
        import os, tempfile
        from dazpy import DazAnimation
        skel, _ = self._make_skeleton(self._sample_result(n_frames=4, n_bones=2))
        anim = DazAnimation.capture(skel)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            anim.save(path)
            loaded = DazAnimation.load(path)
            self.assertEqual(loaded.figure, anim.figure)
            self.assertEqual(loaded.bones, anim.bones)
            self.assertEqual(loaded.frame_count, anim.frame_count)
            self.assertEqual(loaded.frame_range, anim.frame_range)
        finally:
            os.unlink(path)

    def test_load_tolerates_missing_keys(self):
        import json, tempfile, os
        from dazpy import DazAnimation
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump({"figure": "MyFig"}, f)
            path = f.name
        try:
            anim = DazAnimation.load(path)
            self.assertEqual(anim.figure, "MyFig")
            self.assertEqual(anim.bones, [])
            self.assertEqual(anim.frames, [])
        finally:
            os.unlink(path)

    # ── properties ───────────────────────────────────────────────────────────

    def test_frame_count(self):
        from dazpy import DazAnimation
        skel, _ = self._make_skeleton(self._sample_result(n_frames=7))
        anim = DazAnimation.capture(skel)
        self.assertEqual(anim.frame_count, 7)

    def test_bone_count(self):
        from dazpy import DazAnimation
        skel, _ = self._make_skeleton(self._sample_result(n_bones=2))
        anim = DazAnimation.capture(skel)
        self.assertEqual(anim.bone_count, 2)

    def test_repr(self):
        from dazpy import DazAnimation
        skel, _ = self._make_skeleton(self._sample_result(n_frames=3, n_bones=2))
        anim = DazAnimation.capture(skel)
        r = repr(anim)
        self.assertIn("Genesis 9", r)
        self.assertIn("frames=3", r)
        self.assertIn("bones=2", r)


class TestDazAnimationClipOps(unittest.TestCase):
    """Tests for clip, blend, as_pose, apply, append, __len__, __getitem__."""

    def _make_anim(self, num_frames=3, start=0, bones=None, morph_sequence=None):
        from dazpy import DazAnimation
        bones = bones or ["hip", "rForeArm"]
        frames = []
        for i in range(num_frames):
            rotations = [[float(i), 0.0, 0.0] for _ in bones]
            morphs = morph_sequence[i] if morph_sequence else {}
            frames.append({"frame": start + i, "rotations": rotations, "morphs": morphs})
        return DazAnimation(
            figure="Genesis 9",
            frame_range={"start": start, "end": start + num_frames - 1},
            bones=bones,
            frames=frames,
        )

    # ── clip ─────────────────────────────────────────────────────────────────

    def test_clip_returns_frames_in_range(self):
        anim = self._make_anim(5, start=0)
        c = anim.clip(1, 3)
        self.assertEqual(len(c.frames), 3)
        self.assertEqual(c.frames[0]["frame"], 1)
        self.assertEqual(c.frames[-1]["frame"], 3)

    def test_clip_updates_frame_range(self):
        anim = self._make_anim(5, start=0)
        c = anim.clip(2, 4)
        self.assertEqual(c.frame_range["start"], 2)
        self.assertEqual(c.frame_range["end"], 4)

    def test_clip_preserves_bones(self):
        anim = self._make_anim(5)
        c = anim.clip(0, 2)
        self.assertEqual(c.bones, anim.bones)

    def test_clip_empty_when_out_of_range(self):
        anim = self._make_anim(3, start=0)
        c = anim.clip(10, 20)
        self.assertEqual(len(c.frames), 0)

    def test_clip_full_range_equals_original_count(self):
        anim = self._make_anim(4, start=0)
        c = anim.clip(0, 3)
        self.assertEqual(len(c.frames), 4)

    def test_clip_figure_preserved(self):
        anim = self._make_anim(3)
        c = anim.clip(0, 1)
        self.assertEqual(c.figure, anim.figure)

    # ── blend ─────────────────────────────────────────────────────────────────

    def test_blend_t0_equals_self_rotations(self):
        from dazpy import DazAnimation
        a = self._make_anim(2, bones=["hip"])
        b = DazAnimation("Genesis 9", {"start": 0, "end": 1}, ["hip"],
                         [{"frame": 0, "rotations": [[100.0, 0.0, 0.0]], "morphs": {}},
                          {"frame": 1, "rotations": [[200.0, 0.0, 0.0]], "morphs": {}}])
        blended = a.blend(b, 0.0)
        self.assertAlmostEqual(blended.frames[0]["rotations"][0][0],
                               a.frames[0]["rotations"][0][0])

    def test_blend_t1_equals_other_rotations(self):
        from dazpy import DazAnimation
        a = self._make_anim(2, bones=["hip"])
        b = DazAnimation("Genesis 9", {"start": 0, "end": 1}, ["hip"],
                         [{"frame": 0, "rotations": [[100.0, 0.0, 0.0]], "morphs": {}},
                          {"frame": 1, "rotations": [[200.0, 0.0, 0.0]], "morphs": {}}])
        blended = a.blend(b, 1.0)
        self.assertAlmostEqual(blended.frames[0]["rotations"][0][0], 100.0)

    def test_blend_midpoint_averages_rotations(self):
        from dazpy import DazAnimation
        a = DazAnimation("G9", {"start": 0, "end": 0}, ["hip"],
                         [{"frame": 0, "rotations": [[0.0, 0.0, 0.0]], "morphs": {}}])
        b = DazAnimation("G9", {"start": 0, "end": 0}, ["hip"],
                         [{"frame": 0, "rotations": [[20.0, 0.0, 0.0]], "morphs": {}}])
        blended = a.blend(b, 0.5)
        self.assertAlmostEqual(blended.frames[0]["rotations"][0][0], 10.0)

    def test_blend_morph_union_of_keys(self):
        from dazpy import DazAnimation
        a = DazAnimation("G9", {"start": 0, "end": 0}, ["hip"],
                         [{"frame": 0, "rotations": [[0.0, 0.0, 0.0]], "morphs": {"smile": 1.0}}])
        b = DazAnimation("G9", {"start": 0, "end": 0}, ["hip"],
                         [{"frame": 0, "rotations": [[0.0, 0.0, 0.0]], "morphs": {"frown": 1.0}}])
        blended = a.blend(b, 0.5)
        self.assertAlmostEqual(blended.frames[0]["morphs"].get("smile", 0.0), 0.5)
        self.assertAlmostEqual(blended.frames[0]["morphs"].get("frown", 0.0), 0.5)

    def test_blend_different_bones_raises(self):
        a = self._make_anim(2, bones=["hip"])
        b = self._make_anim(2, bones=["rForeArm"])
        with self.assertRaises(ValueError):
            a.blend(b, 0.5)

    def test_blend_truncates_to_shorter_clip(self):
        a = self._make_anim(3, bones=["hip"])
        b = self._make_anim(2, bones=["hip"])
        blended = a.blend(b, 0.5)
        self.assertEqual(len(blended.frames), 2)

    def test_blend_frame_numbers_from_self(self):
        a = self._make_anim(2, start=10, bones=["hip"])
        b = self._make_anim(2, start=0, bones=["hip"])
        blended = a.blend(b, 0.5)
        self.assertEqual(blended.frames[0]["frame"], 10)

    # ── as_pose ───────────────────────────────────────────────────────────────

    def test_as_pose_returns_daz_pose(self):
        from dazpy import DazPose
        pose = self._make_anim(3).as_pose(1)
        self.assertIsInstance(pose, DazPose)

    def test_as_pose_figure_matches(self):
        anim = self._make_anim(2)
        self.assertEqual(anim.as_pose(0).figure, anim.figure)

    def test_as_pose_sparse_bones_zero_excluded(self):
        from dazpy import DazAnimation
        anim = DazAnimation(
            "G9", {"start": 0, "end": 0}, ["hip", "rForeArm"],
            [{"frame": 0, "rotations": [[0.0, 0.0, 0.0], [45.0, 0.0, 0.0]], "morphs": {}}]
        )
        pose = anim.as_pose(0)
        self.assertNotIn("hip", pose.bones)
        self.assertIn("rForeArm", pose.bones)

    def test_as_pose_includes_morphs(self):
        from dazpy import DazAnimation
        anim = DazAnimation(
            "G9", {"start": 0, "end": 0}, ["hip"],
            [{"frame": 0, "rotations": [[0.0, 0.0, 0.0]], "morphs": {"smile": 0.8}}]
        )
        self.assertAlmostEqual(anim.as_pose(0).morphs.get("smile"), 0.8)

    def test_as_pose_default_index_zero(self):
        anim = self._make_anim(3)
        pose = anim.as_pose()
        self.assertEqual(pose.figure, anim.figure)

    def test_as_pose_props_empty(self):
        anim = self._make_anim(2)
        self.assertEqual(anim.as_pose(0).props, {})

    # ── apply ─────────────────────────────────────────────────────────────────

    def test_apply_calls_skeleton_client_once(self):
        from dazpy._skeleton import DazSkeleton
        anim = self._make_anim(2)
        client = mock_client(True)
        skel = DazSkeleton(client, NodeIdentifier("Genesis 9", kind="label"))
        anim.apply(skel, frame_index=0)
        self.assertEqual(client.execute.call_count, 1)

    def test_apply_script_contains_bone_names(self):
        from dazpy import DazAnimation
        from dazpy._skeleton import DazSkeleton
        anim = DazAnimation(
            "G9", {"start": 0, "end": 0}, ["rForeArm"],
            [{"frame": 0, "rotations": [[45.0, 0.0, 0.0]], "morphs": {}}]
        )
        client = mock_client(True)
        skel = DazSkeleton(client, NodeIdentifier("G9"))
        anim.apply(skel, frame_index=0)
        script = client.execute.call_args[0][0]
        self.assertIn("rForeArm", script)
        self.assertIn("45.0", script)

    # ── append ────────────────────────────────────────────────────────────────

    def test_append_total_frame_count(self):
        a = self._make_anim(3, start=0)
        b = self._make_anim(2, start=0)
        self.assertEqual(len(a.append(b).frames), 5)

    def test_append_renumbers_b_frames(self):
        a = self._make_anim(3, start=0)  # frames 0,1,2
        b = self._make_anim(2, start=5)  # frames 5,6 → should become 3,4
        result = a.append(b)
        self.assertEqual(result.frames[3]["frame"], 3)
        self.assertEqual(result.frames[4]["frame"], 4)

    def test_append_frame_range_updated(self):
        a = self._make_anim(3, start=0)  # end=2
        b = self._make_anim(2, start=0)  # end=1 → becomes 3,4
        result = a.append(b)
        self.assertEqual(result.frame_range["start"], 0)
        self.assertEqual(result.frame_range["end"], 4)

    def test_append_different_bones_raises(self):
        a = self._make_anim(2, bones=["hip"])
        b = self._make_anim(2, bones=["rForeArm"])
        with self.assertRaises(ValueError):
            a.append(b)

    def test_append_preserves_self_figure(self):
        a = self._make_anim(2)
        b = self._make_anim(2)
        self.assertEqual(a.append(b).figure, a.figure)

    def test_append_empty_self_returns_other(self):
        from dazpy import DazAnimation
        empty = DazAnimation("G9", {"start": 0, "end": 0}, ["hip"], [])
        b = self._make_anim(2, bones=["hip"])
        result = empty.append(b)
        self.assertEqual(len(result.frames), 2)

    # ── __len__ / __getitem__ ─────────────────────────────────────────────────

    def test_len(self):
        self.assertEqual(len(self._make_anim(5)), 5)

    def test_getitem_returns_frame_dict(self):
        anim = self._make_anim(3)
        frame = anim[0]
        self.assertIn("rotations", frame)
        self.assertIn("frame", frame)

    def test_getitem_negative_index(self):
        anim = self._make_anim(3, start=0)
        self.assertEqual(anim[-1]["frame"], 2)

    def test_getitem_out_of_range_raises(self):
        anim = self._make_anim(2)
        with self.assertRaises(IndexError):
            _ = anim[99]


if __name__ == "__main__":
    unittest.main()
