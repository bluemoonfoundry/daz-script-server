"""Unit tests for tests/fixtures/rendering/sprite_matrix/workflow_builder.py."""
from __future__ import annotations

import os
import sys
import unittest

_SPRITE_MATRIX_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "rendering", "sprite_matrix"
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
            "60", "62", "64", "65", "66", "67", "68", "69", "70", "71", "72", "73", "74", "75",
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
            "UltralyticsDetectorProvider",
            "BboxDetectorSEGS",
            "SAMLoader",
            "SAMDetectorCombined",
            "MaskToSEGS",
            "IPAdapterInsightFaceLoader",
            "IPAdapterUnifiedLoaderFaceID",
            "IPAdapterFaceID",
            "ToBasicPipe",
            "SEGSDetailer",
            "SEGSPaste",
            "ImpactControlNetApplyAdvancedSEGS",
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

    def test_face_detailer_also_rewired_to_checkpoint(self):
        self.assertEqual(self.wf["71"]["inputs"]["model"], ["1", 0])
        self.assertEqual(self.wf["64"]["inputs"]["clip"], ["1", 1])


class TestBuildControlnetWorkflowFaceDetailer(unittest.TestCase):
    def test_enabled_by_default(self):
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertIn("65", wf)
        self.assertEqual(wf["8"]["inputs"]["images"], ["66", 0])

    def test_bbox_detector_uses_face_yolo_model(self):
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertEqual(wf["60"]["inputs"]["model_name"], "bbox/face_yolov8m.pt")
        self.assertEqual(wf["62"]["inputs"]["bbox_detector"], ["60", 0])

    def test_detects_on_stylized_output(self):
        # Detection runs on the stylized composite (node "7") so crop
        # coordinates match the image SEGSPaste ultimately pastes into.
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertEqual(wf["62"]["inputs"]["image"], ["7", 0])

    def test_segs_detailer_does_not_use_old_setdefaultimage_swap(self):
        # No more SetDefaultImageForSEGS pixel-source swap -- identity comes
        # from FaceID embedding conditioning on the model, not from sourcing
        # crop pixels from the real beauty render. (segs now flows through
        # the ControlNet-on-SEGS chain before reaching SEGSDetailer -- see
        # TestBuildControlnetWorkflowFaceDetailerControlNet for that wiring.)
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertNotIn("63", wf)

    def test_faceid_conditioned_on_original_beauty_render(self):
        # The identity reference photo for FaceID's embedding extraction is
        # the ORIGINAL Daz beauty render (node "2"), not the stylized output
        # -- this is what anchors identity now that SetDefaultImageForSEGS
        # is gone.
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertEqual(wf["72"]["inputs"]["image"], ["2", 0])
        self.assertEqual(wf["72"]["inputs"]["insightface"], ["70", 0])
        self.assertEqual(wf["72"]["inputs"]["model"], ["71", 0])
        self.assertEqual(wf["72"]["inputs"]["ipadapter"], ["71", 1])

    def test_faceid_patched_model_feeds_basic_pipe(self):
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertEqual(wf["64"]["inputs"]["model"], ["72", 0])

    def test_faceid_weight_configurable(self):
        wf = build_controlnet_workflow(**{**_DEFAULT_KWARGS, "face_detailer_faceid_weight": 0.75})
        self.assertAlmostEqual(wf["72"]["inputs"]["weight"], 0.75)

    def test_faceid_fixed_literals_present(self):
        # provider/preset/lora_strength are fixed (not config knobs) per the
        # design spec -- only weight is tunable. Guards against the fixed
        # values silently disappearing/changing during future edits.
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertEqual(wf["70"]["inputs"]["provider"], "CPU")
        self.assertEqual(wf["71"]["inputs"]["preset"], "FACEID PLUS V2")
        self.assertEqual(wf["71"]["inputs"]["provider"], "CPU")
        self.assertAlmostEqual(wf["71"]["inputs"]["lora_strength"], 0.6)

    def test_sam_refines_bbox_into_precise_silhouette(self):
        # UltralyticsDetectorProvider's face_yolov8m.pt is bbox-only, so
        # BboxDetectorSEGS's mask is a plain rectangle. A dilation generous
        # enough to cover the hair also pulls in surrounding background,
        # which SEGSDetailer then visibly re-stylizes into a rectangular
        # "box" artifact against the clean background (confirmed live).
        # SAM refines that rectangular hint into an actual head/hair
        # silhouette before SEGSDetailer.
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertEqual(wf["67"]["inputs"]["model_name"], "sam_vit_b_01ec64.pth")
        self.assertEqual(wf["68"]["inputs"]["sam_model"], ["67", 0])
        self.assertEqual(wf["68"]["inputs"]["segs"], ["62", 0])
        self.assertEqual(wf["68"]["inputs"]["image"], ["7", 0])
        self.assertEqual(wf["69"]["inputs"]["mask"], ["68", 0])
        self.assertFalse(wf["69"]["inputs"]["bbox_fill"])

    def test_sam_mask_dilation_and_paste_feather_stay_tight(self):
        # Even with a true SAM silhouette, dilating/feathering it wider than
        # a few pixels re-encodes a thin ring of background through the VAE
        # round trip, which comes back very slightly darker than the
        # untouched background -- a subtle "blacker than black" halo,
        # confirmed live via pixel sampling. bbox_expansion (the search hint
        # SAM gets) can stay generous, but SAMDetectorCombined's own
        # dilation and SEGSPaste's feather must stay small.
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertEqual(wf["68"]["inputs"]["dilation"], 10)
        self.assertEqual(wf["66"]["inputs"]["feather"], 2)

    def test_wired_to_lora_model_and_clip_when_lora_present(self):
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertEqual(wf["71"]["inputs"]["model"], ["1b", 0])
        self.assertEqual(wf["64"]["inputs"]["clip"], ["1b", 1])

    def test_uses_plain_non_controlnet_conditioning(self):
        # Body-scale normal/depth/lineart maps don't correspond to the
        # cropped/upscaled face coordinate space, so the basic_pipe must use
        # the raw CLIPTextEncode outputs, not the ControlNet-chained ones.
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertEqual(wf["64"]["inputs"]["positive"], ["4", 0])
        self.assertEqual(wf["64"]["inputs"]["negative"], ["5", 0])

    def test_denoise_and_guide_size_configurable(self):
        wf = build_controlnet_workflow(**{**_DEFAULT_KWARGS, "face_detailer_denoise": 0.15, "face_detailer_guide_size": 768.0})
        self.assertAlmostEqual(wf["65"]["inputs"]["denoise"], 0.15)
        self.assertAlmostEqual(wf["65"]["inputs"]["guide_size"], 768.0)

    def test_bbox_dilation_default_is_generous(self):
        # A small dilation leaves the crown of the hair outside the
        # refined/pasted region, producing a visible color seam at the
        # hairline (confirmed live) -- default must be generous, not the
        # node's own tiny default of 10.
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertEqual(wf["62"]["inputs"]["dilation"], 100)

    def test_bbox_dilation_configurable(self):
        wf = build_controlnet_workflow(**{**_DEFAULT_KWARGS, "face_detailer_bbox_dilation": 150})
        self.assertEqual(wf["62"]["inputs"]["dilation"], 150)

    def test_uses_same_seed_as_main_pass(self):
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertEqual(wf["65"]["inputs"]["seed"], wf["6"]["inputs"]["seed"])

    def test_paste_targets_stylized_output(self):
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertEqual(wf["66"]["inputs"]["image"], ["7", 0])
        self.assertEqual(wf["66"]["inputs"]["segs"], ["65", 0])

    def test_disabled_removes_nodes_and_reverts_save_image(self):
        wf = build_controlnet_workflow(**{**_DEFAULT_KWARGS, "face_detailer_enabled": False})
        for node_id in ("60", "62", "64", "65", "66", "67", "68", "69", "70", "71", "72", "73", "74", "75"):
            self.assertNotIn(node_id, wf)
        self.assertEqual(wf["8"]["inputs"]["images"], ["7", 0])
        types = {v["class_type"] for v in wf.values()}
        for class_type in (
            "UltralyticsDetectorProvider", "BboxDetectorSEGS", "SAMLoader",
            "SAMDetectorCombined", "MaskToSEGS", "SEGSDetailer", "SEGSPaste",
            "IPAdapterInsightFaceLoader", "IPAdapterUnifiedLoaderFaceID", "IPAdapterFaceID",
            "ImpactControlNetApplyAdvancedSEGS",
        ):
            self.assertNotIn(class_type, types)


class TestBuildControlnetWorkflowFaceDetailerControlNet(unittest.TestCase):
    def test_segs_detailer_reads_segs_from_controlnet_chain(self):
        # "65"'s segs now comes from the end of the ControlNet-on-SEGS
        # chain (node "75"), not directly from MaskToSEGS (node "69") --
        # the chain inserts per-segment ControlNet conditioning in between.
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertEqual(wf["65"]["inputs"]["segs"], ["75", 0])

    def test_controlnet_chain_wired_in_order(self):
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertEqual(wf["73"]["inputs"]["segs"], ["69", 0])
        self.assertEqual(wf["74"]["inputs"]["segs"], ["73", 0])
        self.assertEqual(wf["75"]["inputs"]["segs"], ["74", 0])

    def test_controlnet_chain_reuses_main_pass_retagged_controlnets(self):
        # Reuses the SAME SetUnionControlNetType outputs (21/31/41) the main
        # pass uses -- no separate ControlNetLoader/SetUnionControlNetType
        # for the face pass, which would load the model a second time.
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertEqual(wf["73"]["inputs"]["control_net"], ["21", 0])
        self.assertEqual(wf["74"]["inputs"]["control_net"], ["31", 0])
        self.assertEqual(wf["75"]["inputs"]["control_net"], ["41", 0])

    def test_controlnet_chain_reuses_main_pass_source_images(self):
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertEqual(wf["73"]["inputs"]["control_image"], ["20", 0])
        self.assertEqual(wf["74"]["inputs"]["control_image"], ["30", 0])
        self.assertEqual(wf["75"]["inputs"]["control_image"], ["40", 0])

    def test_controlnet_weights_configurable(self):
        wf = build_controlnet_workflow(**{
            **_DEFAULT_KWARGS,
            "face_detailer_controlnet_normal_weight": 0.9,
            "face_detailer_controlnet_depth_weight": 0.7,
            "face_detailer_controlnet_lineart_weight": 0.5,
        })
        self.assertAlmostEqual(wf["73"]["inputs"]["strength"], 0.9)
        self.assertAlmostEqual(wf["74"]["inputs"]["strength"], 0.7)
        self.assertAlmostEqual(wf["75"]["inputs"]["strength"], 0.5)

    def test_controlnet_weights_default(self):
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertAlmostEqual(wf["73"]["inputs"]["strength"], 1.4)
        self.assertAlmostEqual(wf["74"]["inputs"]["strength"], 1.1)
        self.assertAlmostEqual(wf["75"]["inputs"]["strength"], 0.9)

    def test_controlnet_chain_fixed_percent_literals(self):
        # start_percent/end_percent are fixed (not config knobs) per the
        # design spec.
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        for node_id in ("73", "74", "75"):
            self.assertAlmostEqual(wf[node_id]["inputs"]["start_percent"], 0.0)
            self.assertAlmostEqual(wf[node_id]["inputs"]["end_percent"], 1.0)


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
