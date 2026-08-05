"""Unit tests for docs/examples/rendering/sprite_matrix/presets.py.

No live servers required -- ExpressionPreset round-trip and override-layering
logic exercised as pure dict operations, without ever calling .apply().
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

_SPRITE_MATRIX_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "docs", "examples", "rendering", "sprite_matrix"
)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, _SPRITE_MATRIX_DIR)

from presets import ExpressionPreset, build_override_pose, merge_overrides  # noqa: E402


class TestExpressionPresetRoundTrip(unittest.TestCase):
    def test_save_load_round_trip(self):
        preset = ExpressionPreset(figure="Genesis 9", morphs={"Smile Full Face": 0.8, "Brow Lower": 0.2})
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            preset.save(path)
            loaded = ExpressionPreset.load(path)
            self.assertEqual(loaded.figure, "Genesis 9")
            self.assertEqual(loaded.morphs, preset.morphs)
        finally:
            os.unlink(path)

    def test_to_dict_has_no_bones_or_props(self):
        preset = ExpressionPreset(figure="Genesis 9", morphs={"X": 0.5})
        d = preset.to_dict()
        self.assertEqual(set(d.keys()), {"figure", "morphs"})

    def test_default_morphs_empty(self):
        preset = ExpressionPreset(figure="Genesis 9")
        self.assertEqual(preset.morphs, {})


class TestMergeOverrides(unittest.TestCase):
    def test_overrides_win_on_conflict(self):
        base = {"bones": {"hip": [0, 0, 0]}, "morphs": {"Smile": 0.1}, "props": {}}
        overrides = {"morphs": {"Smile": 0.9}}
        merged = merge_overrides(base, overrides)
        self.assertEqual(merged["morphs"]["Smile"], 0.9)
        self.assertEqual(merged["bones"]["hip"], [0, 0, 0])

    def test_overrides_add_new_keys(self):
        base = {"bones": {}, "morphs": {"Smile": 0.1}, "props": {}}
        overrides = {"morphs": {"BrowLower": 0.5}}
        merged = merge_overrides(base, overrides)
        self.assertEqual(merged["morphs"], {"Smile": 0.1, "BrowLower": 0.5})

    def test_empty_overrides_no_change(self):
        base = {"bones": {"hip": [0, 1, 2]}, "morphs": {"Smile": 0.1}, "props": {"x": 1.0}}
        merged = merge_overrides(base, {})
        self.assertEqual(merged, base)

    def test_does_not_mutate_base(self):
        base = {"bones": {}, "morphs": {"Smile": 0.1}, "props": {}}
        merge_overrides(base, {"morphs": {"Smile": 0.9}})
        self.assertEqual(base["morphs"]["Smile"], 0.1)


class TestBuildOverridePose(unittest.TestCase):
    def test_builds_pose_with_only_specified_channels(self):
        pose = build_override_pose("Genesis 9", {"morphs": {"BrowLower": 0.9}})
        self.assertEqual(pose.figure, "Genesis 9")
        self.assertEqual(pose.morphs, {"BrowLower": 0.9})
        self.assertEqual(pose.bones, {})
        self.assertEqual(pose.props, {})

    def test_empty_overrides_produce_empty_pose(self):
        pose = build_override_pose("Genesis 9", {})
        self.assertEqual(pose.bones, {})
        self.assertEqual(pose.morphs, {})
        self.assertEqual(pose.props, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
