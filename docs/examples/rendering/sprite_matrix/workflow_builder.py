from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

_TEMPLATE_PATH = Path(__file__).with_name("workflow_controlnet.json")


def stable_seed(base_seed: int, combo_id: str, camera: str) -> int:
    """Deterministic per-combo seed so identical inputs reproduce identical
    output on rerun -- keeps the resume-by-file-existence contract coherent
    (a skipped combo would have produced the same image anyway)."""
    digest = hashlib.sha256(f"{base_seed}:{combo_id}:{camera}".encode("utf-8")).hexdigest()
    return (base_seed + int(digest[:8], 16)) % (2**32)


def build_controlnet_workflow(
    *,
    beauty_image_ref: str,
    normal_image_ref: str,
    depth_image_ref: str,
    lineart_image_ref: str,
    checkpoint_name: str,
    lora_name: str,
    lora_strength: float,
    denoise: float,
    steps: int,
    cfg: float,
    seed: int,
    positive_prompt: str,
    negative_prompt: str,
    controlnet_model: str,
    controlnet_normal_weight: float,
    controlnet_depth_weight: float,
    controlnet_lineart_weight: float,
) -> dict:
    """Return a ComfyUI API-format prompt dict ready for queue_prompt()."""
    with open(_TEMPLATE_PATH) as f:
        workflow = json.load(f)
    workflow = copy.deepcopy(workflow)

    workflow["1"]["inputs"]["ckpt_name"] = checkpoint_name

    if lora_name:
        workflow["1b"]["inputs"]["lora_name"] = lora_name
        workflow["1b"]["inputs"]["strength_model"] = float(lora_strength)
        workflow["1b"]["inputs"]["strength_clip"] = float(lora_strength)
    else:
        # ComfyUI's LoraLoader has no valid empty-string option when zero
        # LoRAs are installed (its dropdown enum is simply []), so an unused
        # loader node fails prompt validation outright rather than being a
        # harmless no-op. Drop the node and rewire its consumers straight to
        # the checkpoint's MODEL/CLIP outputs instead.
        del workflow["1b"]
        workflow["4"]["inputs"]["clip"] = ["1", 1]
        workflow["5"]["inputs"]["clip"] = ["1", 1]
        workflow["6"]["inputs"]["model"] = ["1", 0]

    workflow["2"]["inputs"]["image"] = beauty_image_ref
    workflow["20"]["inputs"]["image"] = normal_image_ref
    workflow["30"]["inputs"]["image"] = depth_image_ref
    workflow["40"]["inputs"]["image"] = lineart_image_ref

    workflow["4"]["inputs"]["text"] = positive_prompt
    workflow["5"]["inputs"]["text"] = negative_prompt

    workflow["50"]["inputs"]["control_net_name"] = controlnet_model
    workflow["22"]["inputs"]["strength"] = float(controlnet_normal_weight)
    workflow["32"]["inputs"]["strength"] = float(controlnet_depth_weight)
    workflow["42"]["inputs"]["strength"] = float(controlnet_lineart_weight)

    workflow["6"]["inputs"]["steps"] = int(steps)
    workflow["6"]["inputs"]["cfg"] = float(cfg)
    workflow["6"]["inputs"]["denoise"] = float(denoise)
    workflow["6"]["inputs"]["seed"] = int(seed)

    return workflow
