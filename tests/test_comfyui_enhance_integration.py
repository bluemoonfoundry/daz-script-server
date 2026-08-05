"""Integration tests for the comfyui_enhance example pipeline.

Skipped automatically when DAZ Studio / ComfyUI is not reachable.

Run standalone:  python tests/test_comfyui_enhance_integration.py
Via runner:      python tests.py integration
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "docs", "examples", "rendering", "comfyui_enhance"
))

# docs/examples/rendering/sprite_matrix/workflow_builder.py shares this module
# name; evict any stale cached entry so this file always gets its own.
sys.modules.pop("workflow_builder", None)

import requests as _req

from dazpy import DazClient, DazViewport
from comfyui_client import ComfyUIClient, ComfyUIError
from workflow_builder import build as build_workflow

# ── Server availability ────────────────────────────────────────────────────────

_DAZ_UP = False
_COMFYUI_UP = False
_DAZ_VIEWPORT_UP = False

try:
    _r = _req.get("http://127.0.0.1:18811/status", timeout=2)
    _DAZ_UP = _r.status_code == 200
except Exception:
    pass

if _DAZ_UP:
    try:
        _daz_client = DazClient()
        _vp = DazViewport(_daz_client)
        _DAZ_VIEWPORT_UP = _vp.is_available()
    except Exception:
        pass

try:
    _cr = _req.get("http://127.0.0.1:8188/system_stats", timeout=2)
    _COMFYUI_UP = _cr.status_code == 200
except Exception:
    pass

skip_no_daz = unittest.skipUnless(_DAZ_VIEWPORT_UP, "DAZ Studio viewport not available")
skip_no_comfyui = unittest.skipUnless(_COMFYUI_UP, "ComfyUI not reachable at 127.0.0.1:8188")


class TestViewportCaptureIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = DazClient()
        cls.vp = DazViewport(cls.client)

    @skip_no_daz
    def test_capture_writes_file(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        try:
            result = self.vp.capture(path)
            self.assertEqual(result, path)
            self.assertTrue(os.path.isfile(path))
            self.assertGreater(os.path.getsize(path), 0)
        finally:
            if os.path.exists(path):
                os.unlink(path)


class TestComfyUIRoundTripIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.comfy = ComfyUIClient()

    @skip_no_comfyui
    def test_system_stats(self):
        stats = self.comfy.get_system_stats()
        self.assertIsInstance(stats, dict)

    @skip_no_comfyui
    def test_upload_queue_wait_download(self):
        # Create a minimal PNG (1×1 white pixel) as the source image
        png_1x1 = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
            b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
            b"\xd5N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(png_1x1)
            src_path = f.name

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            out_path = f.name

        try:
            image_ref = self.comfy.upload_image(src_path)
            self.assertIsInstance(image_ref, str)
            self.assertTrue(len(image_ref) > 0)

            workflow = build_workflow(image_ref, denoise=0.45, steps=20)
            prompt_id = self.comfy.queue_prompt(workflow)
            self.assertIsInstance(prompt_id, str)

            result_path = self.comfy.save_result(prompt_id, out_path, timeout=120.0)
            self.assertEqual(result_path, out_path)
            self.assertTrue(os.path.isfile(out_path))
            self.assertGreater(os.path.getsize(out_path), 0)
        finally:
            for p in (src_path, out_path):
                if os.path.exists(p):
                    os.unlink(p)


if __name__ == "__main__":
    if not _DAZ_UP and not _COMFYUI_UP:
        print("SKIP: Neither DAZ Studio nor ComfyUI is reachable")
        sys.exit(0)
    unittest.main(verbosity=2)
