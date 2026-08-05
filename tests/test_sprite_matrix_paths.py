"""Unit tests for docs/examples/rendering/sprite_matrix/paths.py.

No live servers required -- naming determinism + resume-check logic against
a temp dir with pre-created dummy files.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

_SPRITE_MATRIX_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "docs", "examples", "rendering", "sprite_matrix"
)
sys.path.insert(0, _SPRITE_MATRIX_DIR)

import paths  # noqa: E402


def _touch(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("x")


class TestPathNaming(unittest.TestCase):
    def test_beauty_path_deterministic(self):
        p1 = paths.beauty_path("/out", "combo_a", "front")
        p2 = paths.beauty_path("/out", "combo_a", "front")
        self.assertEqual(p1, p2)
        self.assertTrue(p1.endswith(os.path.join("renders", "combo_a", "front.png")))

    def test_stylized_path_separate_from_render(self):
        rendered = paths.beauty_path("/out", "combo_a", "front")
        stylized = paths.stylized_path("/out", "combo_a", "front")
        self.assertNotEqual(rendered, stylized)
        self.assertIn("stylized", stylized)

    def test_canvas_path_matches_daz_convention(self):
        p = paths.canvas_path("/out", "combo_a", "front", "Normal", "Normal")
        self.assertTrue(p.endswith(os.path.join("front_canvases", "front-Normal-Normal.exr")))

    def test_different_cameras_produce_different_paths(self):
        front = paths.beauty_path("/out", "combo_a", "front")
        back = paths.beauty_path("/out", "combo_a", "back")
        self.assertNotEqual(front, back)


class TestResumeChecks(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.output_dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_render_outputs_missing_returns_false(self):
        self.assertFalse(paths.render_outputs_exist(self.output_dir, "combo_a", "front", ("Normal", "Depth")))

    def test_render_outputs_partial_returns_false(self):
        _touch(paths.beauty_path(self.output_dir, "combo_a", "front"))
        _touch(paths.canvas_path(self.output_dir, "combo_a", "front", "Normal", "Normal"))
        # Depth canvas missing
        self.assertFalse(paths.render_outputs_exist(self.output_dir, "combo_a", "front", ("Normal", "Depth")))

    def test_render_outputs_complete_returns_true(self):
        _touch(paths.beauty_path(self.output_dir, "combo_a", "front"))
        _touch(paths.canvas_path(self.output_dir, "combo_a", "front", "Normal", "Normal"))
        _touch(paths.canvas_path(self.output_dir, "combo_a", "front", "Depth", "Depth"))
        self.assertTrue(paths.render_outputs_exist(self.output_dir, "combo_a", "front", ("Normal", "Depth")))

    def test_render_outputs_no_canvases_requested(self):
        _touch(paths.beauty_path(self.output_dir, "combo_a", "front"))
        self.assertTrue(paths.render_outputs_exist(self.output_dir, "combo_a", "front", ()))

    def test_stylized_output_missing_returns_false(self):
        self.assertFalse(paths.stylized_output_exists(self.output_dir, "combo_a", "front"))

    def test_stylized_output_present_returns_true(self):
        _touch(paths.stylized_path(self.output_dir, "combo_a", "front"))
        self.assertTrue(paths.stylized_output_exists(self.output_dir, "combo_a", "front"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
