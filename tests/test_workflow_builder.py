"""Unit tests for examples/comfyui_enhance/workflow_builder.py."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "examples", "comfyui_enhance"))

from workflow_builder import build


class TestWorkflowBuilder(unittest.TestCase):
    def setUp(self):
        self.wf = build("input/snap.png")

    def test_required_node_keys(self):
        for key in ("1", "2", "3", "4", "5", "6", "7", "8"):
            self.assertIn(key, self.wf, f"Missing node {key}")

    def test_required_class_types(self):
        types = {v["class_type"] for v in self.wf.values()}
        for expected in (
            "CheckpointLoaderSimple",
            "LoadImage",
            "VAEEncode",
            "CLIPTextEncode",
            "KSampler",
            "VAEDecode",
            "SaveImage",
        ):
            self.assertIn(expected, types)

    def test_image_ref_substituted(self):
        self.assertEqual(self.wf["2"]["inputs"]["image"], "input/snap.png")

    def test_checkpoint_default(self):
        self.assertEqual(self.wf["1"]["inputs"]["ckpt_name"], "v1-5-pruned-emaonly.ckpt")

    def test_checkpoint_override(self):
        wf = build("img.png", checkpoint_name="custom.safetensors")
        self.assertEqual(wf["1"]["inputs"]["ckpt_name"], "custom.safetensors")

    def test_denoise_default(self):
        self.assertAlmostEqual(self.wf["6"]["inputs"]["denoise"], 0.45)

    def test_denoise_override(self):
        wf = build("img.png", denoise=0.75)
        self.assertAlmostEqual(wf["6"]["inputs"]["denoise"], 0.75)

    def test_steps_default(self):
        self.assertEqual(self.wf["6"]["inputs"]["steps"], 20)

    def test_steps_override(self):
        wf = build("img.png", steps=30)
        self.assertEqual(wf["6"]["inputs"]["steps"], 30)

    def test_positive_prompt_override(self):
        wf = build("img.png", positive_prompt="my prompt")
        self.assertEqual(wf["4"]["inputs"]["text"], "my prompt")

    def test_negative_prompt_override(self):
        wf = build("img.png", negative_prompt="bad stuff")
        self.assertEqual(wf["5"]["inputs"]["text"], "bad stuff")

    def test_seed_fixed(self):
        wf = build("img.png", seed=42)
        self.assertEqual(wf["6"]["inputs"]["seed"], 42)

    def test_seed_random_when_none(self):
        wf1 = build("img.png")
        wf2 = build("img.png")
        # Both are valid integers; very unlikely to collide
        self.assertIsInstance(wf1["6"]["inputs"]["seed"], int)
        self.assertIsInstance(wf2["6"]["inputs"]["seed"], int)

    def test_build_does_not_mutate_template(self):
        wf1 = build("img1.png", denoise=0.3)
        wf2 = build("img2.png", denoise=0.6)
        self.assertAlmostEqual(wf1["6"]["inputs"]["denoise"], 0.3)
        self.assertAlmostEqual(wf2["6"]["inputs"]["denoise"], 0.6)
        self.assertEqual(wf1["2"]["inputs"]["image"], "img1.png")
        self.assertEqual(wf2["2"]["inputs"]["image"], "img2.png")

    def test_ksampler_fixed_params(self):
        ks = self.wf["6"]["inputs"]
        self.assertEqual(ks["sampler_name"], "dpmpp_2m")
        self.assertEqual(ks["scheduler"], "karras")
        self.assertAlmostEqual(ks["cfg"], 7.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
