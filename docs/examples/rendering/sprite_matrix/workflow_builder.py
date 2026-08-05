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
    face_detailer_enabled: bool = True,
    face_detailer_denoise: float = 0.25,
    face_detailer_guide_size: float = 512.0,
    face_detailer_bbox_dilation: int = 100,
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
        face_model_ref, face_clip_ref = ["1b", 0], ["1b", 1]
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
        face_model_ref, face_clip_ref = ["1", 0], ["1", 1]

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

    if face_detailer_enabled:
        # Second pass: detect the face in the stylized output (node "7"), but
        # then swap the crop's pixel source to the ORIGINAL beauty render
        # (node "2", the real Daz-rendered face) via SetDefaultImageForSEGS
        # before refining -- crucial, since refining the already-stylized
        # crop at low denoise would just polish whatever face the main pass
        # already invented rather than pulling it back toward the real
        # identity (confirmed: this was the bug in an earlier FaceDetailer-
        # only version of this pass). SEGSDetailer re-stylizes that real-face
        # crop at a lower denoise than the main pass using plain
        # (non-ControlNet) conditioning -- the body-scale normal/depth/
        # lineart maps don't correspond to the cropped/upscaled face
        # coordinate space -- then SEGSPaste composites it back into the
        # stylized body with feathering.
        #
        # The face detector's bbox only covers eyes/nose/mouth/forehead, not
        # the crown of the hair, so a small dilation leaves a visible color
        # seam at the hairline (the un-refined main pass invents its own
        # hair color above the pasted region) -- confirmed live. A generous
        # bbox_dilation pushes the refined/pasted region up through the
        # whole head.
        workflow["62"]["inputs"]["dilation"] = int(face_detailer_bbox_dilation)
        workflow["64"]["inputs"]["model"] = face_model_ref
        workflow["64"]["inputs"]["clip"] = face_clip_ref
        workflow["65"]["inputs"]["steps"] = int(steps)
        workflow["65"]["inputs"]["cfg"] = float(cfg)
        workflow["65"]["inputs"]["denoise"] = float(face_detailer_denoise)
        workflow["65"]["inputs"]["guide_size"] = float(face_detailer_guide_size)
        workflow["65"]["inputs"]["seed"] = int(seed)
        workflow["8"]["inputs"]["images"] = ["66", 0]
    else:
        for node_id in ("60", "62", "63", "64", "65", "66"):
            del workflow[node_id]

    return workflow
