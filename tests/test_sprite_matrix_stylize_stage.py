"""Unit tests for tests/fixtures/rendering/sprite_matrix/stylize_stage.py's
FaceID-execution-error fallback. No live servers required -- ComfyUIClient
and the EXR conversion functions are mocked.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "rendering", "comfyui_enhance"
))
_SPRITE_MATRIX_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "rendering", "sprite_matrix"
)
sys.path.insert(0, _SPRITE_MATRIX_DIR)

for _mod in ("stylize_stage", "workflow_builder", "config", "schema", "paths", "canvas_convert", "comfyui_client"):
    sys.modules.pop(_mod, None)

from comfyui_client import ComfyUIExecutionError  # noqa: E402
from config import ComfyUIStageConfig, PipelineConfig  # noqa: E402
from schema import ComboEntry  # noqa: E402
import stylize_stage  # noqa: E402


def _make_cfg(output_dir: str, *, face_detailer_enabled: bool = True) -> PipelineConfig:
    cfg = PipelineConfig(output_dir=output_dir)
    cfg.comfyui = ComfyUIStageConfig(
        checkpoint="gn.safetensors",
        controlnet_model="controlnet-union-sdxl-1.0.safetensors",
        face_detailer_enabled=face_detailer_enabled,
    )
    cfg.combos = [ComboEntry(id="combo1", pose="standing", expression="calm")]
    return cfg


def _touch_render_inputs(output_dir: str, combo_id: str, camera: str) -> None:
    import paths

    for path in (
        paths.beauty_path(output_dir, combo_id, camera),
        paths.canvas_path(output_dir, combo_id, camera, "Normal", "Normal"),
        paths.canvas_path(output_dir, combo_id, camera, "Depth", "Depth"),
    ):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "wb").close()


class TestRunStylizeStageFaceIdFallback(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        _touch_render_inputs(self.tmpdir.name, "combo1", "front")
        _touch_render_inputs(self.tmpdir.name, "combo1", "back")

    def test_retries_without_face_detailer_on_execution_error(self):
        exec_error = ComfyUIExecutionError("pid1", "IPAdapterFaceID", "InsightFace: No face detected.")
        mock_comfy = MagicMock()
        mock_comfy.upload_image.return_value = "ref.png"
        mock_comfy.queue_prompt.return_value = "pid"
        mock_comfy.save_result.side_effect = [exec_error, None]

        with patch("stylize_stage.convert_normal_exr_to_png", return_value="normal.png"), \
             patch("stylize_stage.convert_depth_exr_to_png", return_value="depth.png"), \
             patch("stylize_stage.derive_lineart", return_value="lineart.png"), \
             patch("stylize_stage.ComfyUIClient", return_value=mock_comfy):
            cfg = _make_cfg(self.tmpdir.name, face_detailer_enabled=True)
            summary = stylize_stage.run_stylize_stage(cfg, only_camera="front")

        self.assertEqual(summary.stylized, 1)
        self.assertEqual(summary.failed, 0)
        result = summary.results[0]
        self.assertEqual(result.status, "stylized")
        self.assertIn("face-identity pass skipped", result.note)
        self.assertIn("No face detected", result.note)
        # First call built with face_detailer_enabled=True, retry with False.
        self.assertEqual(mock_comfy.save_result.call_count, 2)

    def test_does_not_retry_when_face_detailer_already_disabled(self):
        exec_error = ComfyUIExecutionError("pid1", "KSampler", "CUDA out of memory")
        mock_comfy = MagicMock()
        mock_comfy.upload_image.return_value = "ref.png"
        mock_comfy.queue_prompt.return_value = "pid"
        mock_comfy.save_result.side_effect = exec_error

        with patch("stylize_stage.convert_normal_exr_to_png", return_value="normal.png"), \
             patch("stylize_stage.convert_depth_exr_to_png", return_value="depth.png"), \
             patch("stylize_stage.derive_lineart", return_value="lineart.png"), \
             patch("stylize_stage.ComfyUIClient", return_value=mock_comfy):
            cfg = _make_cfg(self.tmpdir.name, face_detailer_enabled=False)
            summary = stylize_stage.run_stylize_stage(cfg, only_camera="front")

        self.assertEqual(summary.failed, 1)
        self.assertEqual(summary.stylized, 0)
        self.assertIn("CUDA out of memory", summary.results[0].error)
        self.assertEqual(mock_comfy.save_result.call_count, 1)

    def test_no_note_when_no_retry_needed(self):
        mock_comfy = MagicMock()
        mock_comfy.upload_image.return_value = "ref.png"
        mock_comfy.queue_prompt.return_value = "pid"
        mock_comfy.save_result.return_value = None

        with patch("stylize_stage.convert_normal_exr_to_png", return_value="normal.png"), \
             patch("stylize_stage.convert_depth_exr_to_png", return_value="depth.png"), \
             patch("stylize_stage.derive_lineart", return_value="lineart.png"), \
             patch("stylize_stage.ComfyUIClient", return_value=mock_comfy):
            cfg = _make_cfg(self.tmpdir.name, face_detailer_enabled=True)
            summary = stylize_stage.run_stylize_stage(cfg, only_camera="front")

        self.assertEqual(summary.stylized, 1)
        self.assertEqual(summary.results[0].note, "")
        self.assertEqual(mock_comfy.save_result.call_count, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
