"""Unit tests for docs/examples/rendering/sprite_matrix/schema.py.

No live servers required.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

_SPRITE_MATRIX_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "docs", "examples", "rendering", "sprite_matrix"
)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, _SPRITE_MATRIX_DIR)

from schema import SpecValidationError, load_spec  # noqa: E402


def _write_preset(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


class SpecFixture:
    """Builds a valid spec + preset library in a temp dir, editable per-test."""

    def __init__(self, tmpdir: str):
        self.tmpdir = tmpdir
        self.pose_dir = os.path.join(tmpdir, "poses")
        self.expr_dir = os.path.join(tmpdir, "expressions")
        _write_preset(os.path.join(self.pose_dir, "standing.json"), {"figure": "Genesis 9", "bones": {}, "morphs": {}, "props": {}})
        _write_preset(os.path.join(self.expr_dir, "calm.json"), {"figure": "Genesis 9", "morphs": {}})

    def spec_dict(self, **overrides) -> dict:
        base = {
            "scene_path": "C:/scenes/hero.duf",
            "sprite": {"figure_label": "Genesis 9"},
            "output_dir": "output",
            "pose_library_dir": self.pose_dir,
            "expression_library_dir": self.expr_dir,
            "cameras": {
                "front": {"label": "Character Camera - Front"},
                "back": {"label": "Character Camera - Back"},
            },
            "render": {"width": 1536, "height": 2048, "canvases": ["Normal", "Depth"]},
            "comfyui": {
                "checkpoint": "gn.safetensors",
                "denoise": 0.35,
                "controlnet": {
                    "model": "controlnet-union-sdxl-1.0.safetensors",
                    "normal": {"weight": 0.6},
                    "depth": {"weight": 0.5},
                    "lineart": {"weight": 0.4},
                },
            },
            "combos": [{"pose": "standing", "expression": "calm"}],
        }
        base.update(overrides)
        return base

    def write_spec(self, data: dict) -> str:
        path = os.path.join(self.tmpdir, "spec.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return path


class TestLoadSpecValid(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.fixture = SpecFixture(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_valid_spec_loads(self):
        path = self.fixture.write_spec(self.fixture.spec_dict())
        cfg = load_spec(path)
        self.assertEqual(cfg.figure_label, "Genesis 9")
        self.assertEqual(len(cfg.combos), 1)
        self.assertEqual(cfg.combos[0].id, "standing__calm")

    def test_controlnet_model_parsed(self):
        path = self.fixture.write_spec(self.fixture.spec_dict())
        cfg = load_spec(path)
        self.assertEqual(cfg.comfyui.controlnet_model, "controlnet-union-sdxl-1.0.safetensors")
        self.assertAlmostEqual(cfg.comfyui.controlnet_normal.weight, 0.6)
        self.assertAlmostEqual(cfg.comfyui.controlnet_depth.weight, 0.5)
        self.assertAlmostEqual(cfg.comfyui.controlnet_lineart.weight, 0.4)

    def test_output_dir_resolved_relative_to_spec(self):
        path = self.fixture.write_spec(self.fixture.spec_dict())
        cfg = load_spec(path)
        self.assertTrue(os.path.isabs(cfg.output_dir))
        self.assertEqual(os.path.basename(cfg.output_dir), "output")

    def test_explicit_combo_id_used(self):
        data = self.fixture.spec_dict()
        data["combos"] = [{"pose": "standing", "expression": "calm", "id": "My Combo"}]
        path = self.fixture.write_spec(data)
        cfg = load_spec(path)
        self.assertEqual(cfg.combos[0].id, "my_combo")

    def test_overrides_parsed(self):
        data = self.fixture.spec_dict()
        data["combos"] = [{"pose": "standing", "expression": "calm", "overrides": {"morphs": {"X": 0.5}}}]
        path = self.fixture.write_spec(data)
        cfg = load_spec(path)
        self.assertEqual(cfg.combos[0].overrides, {"morphs": {"X": 0.5}})


class TestLoadSpecInvalid(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.fixture = SpecFixture(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_pose_preset_rejected(self):
        data = self.fixture.spec_dict()
        data["combos"] = [{"pose": "does_not_exist", "expression": "calm"}]
        path = self.fixture.write_spec(data)
        with self.assertRaises(SpecValidationError):
            load_spec(path)

    def test_missing_expression_preset_rejected(self):
        data = self.fixture.spec_dict()
        data["combos"] = [{"pose": "standing", "expression": "does_not_exist"}]
        path = self.fixture.write_spec(data)
        with self.assertRaises(SpecValidationError):
            load_spec(path)

    def test_duplicate_combo_id_rejected(self):
        data = self.fixture.spec_dict()
        data["combos"] = [
            {"pose": "standing", "expression": "calm"},
            {"pose": "standing", "expression": "calm"},
        ]
        path = self.fixture.write_spec(data)
        with self.assertRaises(SpecValidationError):
            load_spec(path)

    def test_missing_figure_label_rejected(self):
        data = self.fixture.spec_dict()
        data["sprite"] = {}
        path = self.fixture.write_spec(data)
        with self.assertRaises(SpecValidationError):
            load_spec(path)

    def test_empty_combos_rejected(self):
        data = self.fixture.spec_dict()
        data["combos"] = []
        path = self.fixture.write_spec(data)
        with self.assertRaises(SpecValidationError):
            load_spec(path)

    def test_denoise_out_of_range_rejected(self):
        data = self.fixture.spec_dict()
        data["comfyui"]["denoise"] = 1.5
        path = self.fixture.write_spec(data)
        with self.assertRaises(SpecValidationError):
            load_spec(path)

    def test_controlnet_weight_out_of_range_rejected(self):
        data = self.fixture.spec_dict()
        data["comfyui"]["controlnet"]["normal"]["weight"] = -0.1
        path = self.fixture.write_spec(data)
        with self.assertRaises(SpecValidationError):
            load_spec(path)

    def test_missing_controlnet_model_rejected(self):
        data = self.fixture.spec_dict()
        del data["comfyui"]["controlnet"]["model"]
        path = self.fixture.write_spec(data)
        with self.assertRaises(SpecValidationError):
            load_spec(path)

    def test_missing_camera_label_rejected(self):
        data = self.fixture.spec_dict()
        data["cameras"] = {"front": {"label": ""}, "back": {"label": "Back"}}
        path = self.fixture.write_spec(data)
        with self.assertRaises(SpecValidationError):
            load_spec(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
