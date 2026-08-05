"""Integration tests for the sprite_matrix pipeline.

Skipped automatically when DAZ Studio / ComfyUI is not reachable, or when the
live Daz scene doesn't have a "Genesis 9" figure with "Character Camera -
Front" / "Character Camera - Back" cameras (the fixture this test expects the
operator to set up by hand, matching the pipeline's own prerequisite that the
sprite scene is already open).

Run standalone:  python tests/test_sprite_matrix_integration.py
Via runner:      pytest tests/test_sprite_matrix_integration.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

_REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_SPRITE_MATRIX_DIR = os.path.join(_REPO_ROOT, "docs", "examples", "rendering", "sprite_matrix")
_COMFYUI_ENHANCE_DIR = os.path.join(_REPO_ROOT, "docs", "examples", "rendering", "comfyui_enhance")
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, _COMFYUI_ENHANCE_DIR)
sys.path.insert(0, _SPRITE_MATRIX_DIR)

import requests as _req

from dazpy import DazClient, DazScene

_DAZ_UP = False
_COMFYUI_UP = False
_FIXTURE_SCENE_READY = False

try:
    _r = _req.get("http://127.0.0.1:18811/status", timeout=2)
    _DAZ_UP = _r.status_code == 200
except Exception:
    pass

if _DAZ_UP:
    try:
        _client = DazClient()
        _scene = DazScene(_client)
        _skel = _scene.find_skeleton_by_label("Genesis 9")
        _FIXTURE_SCENE_READY = _skel is not None
    except Exception:
        pass

try:
    _cr = _req.get("http://127.0.0.1:8188/system_stats", timeout=2)
    _COMFYUI_UP = _cr.status_code == 200
except Exception:
    pass

skip_no_daz = unittest.skipUnless(_DAZ_UP, "DAZ Studio not reachable at 127.0.0.1:18811")
skip_no_fixture_scene = unittest.skipUnless(
    _FIXTURE_SCENE_READY, "Live scene needs a 'Genesis 9' figure loaded for this test"
)
skip_no_comfyui = unittest.skipUnless(_COMFYUI_UP, "ComfyUI not reachable at 127.0.0.1:8188")


def _write_preset(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


class TestRenderStageResumeIntegration(unittest.TestCase):
    """Exercises the resume/idempotency contract against a live Daz Studio."""

    @skip_no_daz
    @skip_no_fixture_scene
    def test_second_run_skips_everything(self):
        from render_stage import run_render_stage
        from schema import load_spec

        with tempfile.TemporaryDirectory() as tmpdir:
            pose_dir = os.path.join(tmpdir, "poses")
            expr_dir = os.path.join(tmpdir, "expressions")
            _write_preset(os.path.join(pose_dir, "neutral.json"), {"figure": "Genesis 9", "bones": {}, "morphs": {}, "props": {}})
            _write_preset(os.path.join(expr_dir, "neutral.json"), {"figure": "Genesis 9", "morphs": {}})

            spec = {
                "scene_path": "unused",
                "sprite": {"figure_label": "Genesis 9"},
                "output_dir": os.path.join(tmpdir, "output"),
                "pose_library_dir": pose_dir,
                "expression_library_dir": expr_dir,
                "cameras": {
                    "front": {"label": "Character Camera - Front"},
                    "back": {"label": "Character Camera - Back"},
                },
                "render": {"width": 256, "height": 256, "quality_preset": "draft", "canvases": []},
                "comfyui": {"checkpoint": "unused.safetensors", "denoise": 0.35},
                "combos": [{"pose": "neutral", "expression": "neutral"}],
            }
            spec_path = os.path.join(tmpdir, "spec.json")
            with open(spec_path, "w") as f:
                json.dump(spec, f)

            cfg = load_spec(spec_path)

            first = run_render_stage(cfg, only_camera="front")
            self.assertEqual(first.failed, 0)
            self.assertEqual(first.rendered, 1)

            second = run_render_stage(cfg, only_camera="front")
            self.assertEqual(second.skipped, 1)
            self.assertEqual(second.rendered, 0)


class TestComfyUIControlnetWorkflowIntegration(unittest.TestCase):
    @skip_no_comfyui
    def test_system_stats(self):
        from comfyui_client import ComfyUIClient

        comfy = ComfyUIClient()
        stats = comfy.get_system_stats()
        self.assertIsInstance(stats, dict)


if __name__ == "__main__":
    if not _DAZ_UP and not _COMFYUI_UP:
        print("SKIP: Neither DAZ Studio nor ComfyUI is reachable")
        sys.exit(0)
    unittest.main(verbosity=2)
