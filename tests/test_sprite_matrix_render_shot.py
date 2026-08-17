"""Unit tests for tests/fixtures/rendering/sprite_matrix/render_shot.py's pure helpers.

No live servers required.
"""
from __future__ import annotations

import os
import sys
import unittest

_SPRITE_MATRIX_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "rendering", "sprite_matrix"
)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, _SPRITE_MATRIX_DIR)

# comfyui_enhance/config.py shares this module name (different PipelineConfig
# shape); evict any stale cached entry -- render_shot.py imports config at
# module load time, so this must run before the render_shot import below.
sys.modules.pop("config", None)

import render_shot  # noqa: E402


class _Args:
    def __init__(self, camera_front_label="Front", camera_back_label="Back"):
        self.camera_front_label = camera_front_label
        self.camera_back_label = camera_back_label


class TestCamerasFor(unittest.TestCase):
    def test_both_returns_both_cameras(self):
        self.assertEqual(render_shot._cameras_for("both"), ("front", "back"))

    def test_front_returns_front_only(self):
        self.assertEqual(render_shot._cameras_for("front"), ("front",))

    def test_back_returns_back_only(self):
        self.assertEqual(render_shot._cameras_for("back"), ("back",))


class TestCameraLabel(unittest.TestCase):
    def test_front_label(self):
        args = _Args(camera_front_label="Character Camera - Front")
        self.assertEqual(render_shot._camera_label(args, "front"), "Character Camera - Front")

    def test_back_label(self):
        args = _Args(camera_back_label="Character Camera - Back")
        self.assertEqual(render_shot._camera_label(args, "back"), "Character Camera - Back")


class TestArgParsingDefaults(unittest.TestCase):
    def test_defaults_match_pipeline_config(self):
        from config import PipelineConfig

        sys.argv = ["render_shot.py", "--name", "shot001", "--output-dir", "out"]
        args = render_shot._parse_args()
        defaults = PipelineConfig()
        self.assertEqual(args.camera_front_label, defaults.camera_front_label)
        self.assertEqual(args.camera_back_label, defaults.camera_back_label)
        self.assertEqual(args.daz_url, defaults.daz_url)
        self.assertEqual(args.comfyui_url, defaults.comfyui_url)
        self.assertEqual(args.camera, "both")
        self.assertEqual(args.stage, "all")

    def test_canvases_default_parses_to_normal_depth(self):
        sys.argv = ["render_shot.py", "--name", "shot001", "--output-dir", "out"]
        args = render_shot._parse_args()
        canvases = tuple(c.strip() for c in args.canvases.split(",") if c.strip())
        self.assertEqual(canvases, ("Normal", "Depth"))

    def test_canvases_override(self):
        sys.argv = ["render_shot.py", "--name", "shot001", "--output-dir", "out", "--canvases", "Normal"]
        args = render_shot._parse_args()
        canvases = tuple(c.strip() for c in args.canvases.split(",") if c.strip())
        self.assertEqual(canvases, ("Normal",))


if __name__ == "__main__":
    unittest.main(verbosity=2)
