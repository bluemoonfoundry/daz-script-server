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
    face_detailer_denoise: float = 0.35,
    face_detailer_guide_size: float = 512.0,
    face_detailer_bbox_dilation: int = 100,
    face_detailer_faceid_weight: float = 1.0,
    face_detailer_controlnet_normal_weight: float = 1.0,
    face_detailer_controlnet_depth_weight: float = 0.8,
    face_detailer_controlnet_lineart_weight: float = 0.6,
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
        # Second pass: detect the face in the stylized output (node "7"),
        # refine that rectangular hint into a true head/hair silhouette via
        # SAM (SAMLoader + SAMDetectorCombined + MaskToSEGS), then run
        # SEGSDetailer on it using a model patched with IPAdapter FaceID
        # (IPAdapterInsightFaceLoader + IPAdapterUnifiedLoaderFaceID +
        # IPAdapterFaceID) conditioned on the ORIGINAL Daz beauty render
        # (node "2") as the identity reference photo.
        #
        # This replaced an earlier version that sourced the crop's pixels
        # from the real beauty render via SetDefaultImageForSEGS and relied
        # on a low denoise (0.15) to stay close to the source face. A live
        # four-way comparison (denoise 0.15/0.20, with/without a reinforced
        # hatching prompt) confirmed that approach had a hard ceiling: at
        # low denoise there's no room for the model to add the heavy ink
        # cross-hatching the body gets at its own 0.35 denoise, regardless
        # of prompt wording, producing a visibly smoother/more photoreal
        # face than the stylized body. Raising denoise enough to close that
        # gap is roughly where identity drift was already confirmed to
        # reappear with the old mechanism -- FaceID embedding conditioning
        # decouples identity from denoise, so this pass can now run at a
        # denoise that actually matches the body's stylization.
        #
        # UltralyticsDetectorProvider's face_yolov8m.pt is bbox-only (no real
        # segmentation), so BboxDetectorSEGS's mask is a plain rectangle.
        # That caused two live-confirmed problems: too small a dilation
        # leaves a color seam at the hairline, but enlarging dilation enough
        # to cover the hair also pulls in surrounding black background,
        # which SEGSDetailer then subtly re-stylizes into a visible
        # rectangular "box" against the clean main-pass background. Fix:
        # refine that rectangular hint into an actual head/hair silhouette
        # via SAM before SEGSDetailer. bbox_expansion (in
        # workflow_controlnet.json, on SAMDetectorCombined) controls how
        # generous a search HINT SAM gets -- kept large so it reliably finds
        # the whole head/hair. Its own `dilation` and SEGSPaste's `feather`,
        # however, must stay small: even after SAM produces a true
        # silhouette, dilating/feathering it wider than a few pixels
        # re-encodes a thin ring of background through the VAE round trip,
        # which comes back very slightly darker than the untouched
        # background -- a subtle but real "blacker than black" halo,
        # confirmed live via pixel sampling (background pixels dipped to
        # ~[1,1,0] against a ~[5,4,4] ambient black).
        #
        # SEGSDetailer's basic_pipe carries the raw, un-conditioned prompt
        # (node "4"/"5" straight into ToBasicPipe) -- the main pass's own
        # ControlNetApply chain (22->32->42) is never in that path, since it
        # conditions the whole-image KSampler's positive conditioning object,
        # not anything SEGSDetailer's per-segment re-sampling can see. That
        # left this pass with ZERO ControlNet guidance even after FaceID
        # conditioning fixed identity: nothing forced it to draw the ink
        # cross-hatching the body gets, so it rendered visibly flatter/
        # shinier skin regardless of denoise or faceid_weight (confirmed
        # live: a seam was visible at the neck/collar boundary in real
        # abby_b/jason_a renders). Fixed by attaching per-segment ControlNet
        # info directly onto the SEGS list via Impact Pack's
        # ImpactControlNetApplyAdvancedSEGS (nodes "73"/"74"/"75"), which
        # internally crops/resizes the same normal/depth/lineart maps the
        # main pass uses to match each segment's crop_region -- exactly the
        # coordinate-space correspondence a full ControlNetApply can't
        # provide (the crop is a different resolution/coordinate space than
        # the body-scale condition images). SEGSDetailer picks up this
        # per-segment info automatically; no change needed there.
        workflow["62"]["inputs"]["dilation"] = int(face_detailer_bbox_dilation)
        workflow["71"]["inputs"]["model"] = face_model_ref
        workflow["64"]["inputs"]["clip"] = face_clip_ref
        workflow["72"]["inputs"]["weight"] = float(face_detailer_faceid_weight)
        workflow["73"]["inputs"]["strength"] = float(face_detailer_controlnet_normal_weight)
        workflow["74"]["inputs"]["strength"] = float(face_detailer_controlnet_depth_weight)
        workflow["75"]["inputs"]["strength"] = float(face_detailer_controlnet_lineart_weight)
        workflow["65"]["inputs"]["steps"] = int(steps)
        workflow["65"]["inputs"]["cfg"] = float(cfg)
        workflow["65"]["inputs"]["denoise"] = float(face_detailer_denoise)
        workflow["65"]["inputs"]["guide_size"] = float(face_detailer_guide_size)
        workflow["65"]["inputs"]["seed"] = int(seed)
        workflow["8"]["inputs"]["images"] = ["66", 0]
    else:
        for node_id in ("60", "62", "64", "65", "66", "67", "68", "69", "70", "71", "72", "73", "74", "75"):
            del workflow[node_id]

    return workflow
