"""Unit tests for docs/examples/rendering/sprite_matrix/workflow_builder.py."""
from __future__ import annotations

import os
import sys
import unittest

_SPRITE_MATRIX_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "docs", "examples", "rendering", "sprite_matrix"
)
sys.path.insert(0, _SPRITE_MATRIX_DIR)

# comfyui_enhance/workflow_builder.py shares this module name; evict any
# stale cached entry so this file always gets its own.
sys.modules.pop("workflow_builder", None)

from workflow_builder import build_controlnet_workflow, stable_seed  # noqa: E402

_DEFAULT_KWARGS = dict(
    beauty_image_ref="beauty.png",
    normal_image_ref="normal.png",
    depth_image_ref="depth.png",
    lineart_image_ref="lineart.png",
    checkpoint_name="gn.safetensors",
    lora_name="gn_lora.safetensors",
    lora_strength=0.8,
    denoise=0.35,
    steps=24,
    cfg=7.0,
    seed=42,
    positive_prompt="graphic novel style",
    negative_prompt="photorealistic",
    controlnet_model="controlnet-union-sdxl-1.0.safetensors",
    controlnet_normal_weight=0.6,
    controlnet_depth_weight=0.5,
    controlnet_lineart_weight=0.4,
)


class TestBuildControlnetWorkflow(unittest.TestCase):
    def setUp(self):
        self.wf = build_controlnet_workflow(**_DEFAULT_KWARGS)

    def test_required_node_keys(self):
        for key in (
            "1", "1b", "2", "3", "4", "5", "6", "7", "8",
            "20", "21", "22", "30", "31", "32", "40", "41", "42", "50",
        ):
            self.assertIn(key, self.wf, f"Missing node {key}")

    def test_required_class_types(self):
        types = {v["class_type"] for v in self.wf.values()}
        for expected in (
            "CheckpointLoaderSimple",
            "LoraLoader",
            "LoadImage",
            "VAEEncode",
            "CLIPTextEncode",
            "ControlNetLoader",
            "SetUnionControlNetType",
            "ControlNetApply",
            "KSampler",
            "VAEDecode",
            "SaveImage",
        ):
            self.assertIn(expected, types)

    def test_only_one_controlnet_loader(self):
        # A single shared union model, not three separate loaders.
        loaders = [v for v in self.wf.values() if v["class_type"] == "ControlNetLoader"]
        self.assertEqual(len(loaders), 1)

    def test_checkpoint_and_lora_set(self):
        self.assertEqual(self.wf["1"]["inputs"]["ckpt_name"], "gn.safetensors")
        self.assertEqual(self.wf["1b"]["inputs"]["lora_name"], "gn_lora.safetensors")
        self.assertAlmostEqual(self.wf["1b"]["inputs"]["strength_model"], 0.8)
        self.assertAlmostEqual(self.wf["1b"]["inputs"]["strength_clip"], 0.8)

    def test_image_refs_substituted(self):
        self.assertEqual(self.wf["2"]["inputs"]["image"], "beauty.png")
        self.assertEqual(self.wf["20"]["inputs"]["image"], "normal.png")
        self.assertEqual(self.wf["30"]["inputs"]["image"], "depth.png")
        self.assertEqual(self.wf["40"]["inputs"]["image"], "lineart.png")

    def test_controlnet_model_and_weights(self):
        self.assertEqual(self.wf["50"]["inputs"]["control_net_name"], "controlnet-union-sdxl-1.0.safetensors")
        self.assertAlmostEqual(self.wf["22"]["inputs"]["strength"], 0.6)
        self.assertAlmostEqual(self.wf["32"]["inputs"]["strength"], 0.5)
        self.assertAlmostEqual(self.wf["42"]["inputs"]["strength"], 0.4)

    def test_union_type_tags_per_pass(self):
        self.assertEqual(self.wf["21"]["inputs"]["type"], "normal")
        self.assertEqual(self.wf["31"]["inputs"]["type"], "depth")
        self.assertEqual(self.wf["41"]["inputs"]["type"], "canny/lineart/anime_lineart/mlsd")
        # all three re-tag the same loaded model
        self.assertEqual(self.wf["21"]["inputs"]["control_net"], ["50", 0])
        self.assertEqual(self.wf["31"]["inputs"]["control_net"], ["50", 0])
        self.assertEqual(self.wf["41"]["inputs"]["control_net"], ["50", 0])

    def test_conditioning_chain_wired_through_all_controlnets(self):
        # positive conditioning: CLIPTextEncode(4) -> ControlNetApply(22) -> (32) -> (42) -> KSampler
        self.assertEqual(self.wf["22"]["inputs"]["conditioning"], ["4", 0])
        self.assertEqual(self.wf["32"]["inputs"]["conditioning"], ["22", 0])
        self.assertEqual(self.wf["42"]["inputs"]["conditioning"], ["32", 0])
        self.assertEqual(self.wf["6"]["inputs"]["positive"], ["42", 0])
        # negative conditioning is not run through ControlNet
        self.assertEqual(self.wf["6"]["inputs"]["negative"], ["5", 0])

    def test_sampler_params(self):
        ks = self.wf["6"]["inputs"]
        self.assertEqual(ks["steps"], 24)
        self.assertAlmostEqual(ks["cfg"], 7.0)
        self.assertAlmostEqual(ks["denoise"], 0.35)
        self.assertEqual(ks["seed"], 42)

    def test_prompts_substituted(self):
        self.assertEqual(self.wf["4"]["inputs"]["text"], "graphic novel style")
        self.assertEqual(self.wf["5"]["inputs"]["text"], "photorealistic")

    def test_build_does_not_mutate_template(self):
        wf1 = build_controlnet_workflow(**{**_DEFAULT_KWARGS, "denoise": 0.2})
        wf2 = build_controlnet_workflow(**{**_DEFAULT_KWARGS, "denoise": 0.9})
        self.assertAlmostEqual(wf1["6"]["inputs"]["denoise"], 0.2)
        self.assertAlmostEqual(wf2["6"]["inputs"]["denoise"], 0.9)


class TestBuildControlnetWorkflowNoLora(unittest.TestCase):
    """ComfyUI's LoraLoader rejects an empty lora_name outright when zero
    LoRAs are installed (its dropdown enum is []), so the node must be
    dropped entirely rather than wired in with an empty string."""

    def setUp(self):
        self.wf = build_controlnet_workflow(**{**_DEFAULT_KWARGS, "lora_name": ""})

    def test_lora_node_absent(self):
        self.assertNotIn("1b", self.wf)
        types = {v["class_type"] for v in self.wf.values()}
        self.assertNotIn("LoraLoader", types)

    def test_consumers_rewired_to_checkpoint(self):
        self.assertEqual(self.wf["4"]["inputs"]["clip"], ["1", 1])
        self.assertEqual(self.wf["5"]["inputs"]["clip"], ["1", 1])
        self.assertEqual(self.wf["6"]["inputs"]["model"], ["1", 0])


class TestStableSeed(unittest.TestCase):
    def test_deterministic_for_same_inputs(self):
        s1 = stable_seed(1000, "combo_a", "front")
        s2 = stable_seed(1000, "combo_a", "front")
        self.assertEqual(s1, s2)

    def test_differs_by_combo(self):
        s1 = stable_seed(1000, "combo_a", "front")
        s2 = stable_seed(1000, "combo_b", "front")
        self.assertNotEqual(s1, s2)

    def test_differs_by_camera(self):
        s1 = stable_seed(1000, "combo_a", "front")
        s2 = stable_seed(1000, "combo_a", "back")
        self.assertNotEqual(s1, s2)

    def test_differs_by_base_seed(self):
        s1 = stable_seed(1000, "combo_a", "front")
        s2 = stable_seed(2000, "combo_a", "front")
        self.assertNotEqual(s1, s2)

    def test_within_uint32_range(self):
        seed = stable_seed(1000, "combo_a", "front")
        self.assertGreaterEqual(seed, 0)
        self.assertLess(seed, 2**32)


if __name__ == "__main__":
    unittest.main(verbosity=2)
