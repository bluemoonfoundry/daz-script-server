from __future__ import annotations

import os
from dataclasses import dataclass, field


def _read_daz_token() -> str:
    token_path = os.path.expanduser("~/.daz3d/dazscriptserver_token.txt")
    try:
        with open(token_path) as f:
            return f.read().strip()
    except OSError:
        return ""


@dataclass
class ControlNetPassConfig:
    weight: float = 0.5


@dataclass
class ComfyUIStageConfig:
    checkpoint: str = "graphicNovelStyleXL.safetensors"
    lora_name: str = ""
    lora_strength: float = 0.8
    denoise: float = 0.35
    base_seed: int = 0
    steps: int = 24
    cfg: float = 7.0
    # A single SDXL "union" ControlNet model (e.g. controlnet-union-sdxl-1.0.safetensors)
    # loaded once and re-tagged per pass via ComfyUI's SetUnionControlNetType node --
    # not three separate per-type models.
    controlnet_model: str = ""
    controlnet_normal: ControlNetPassConfig = field(
        default_factory=lambda: ControlNetPassConfig(weight=0.6)
    )
    controlnet_depth: ControlNetPassConfig = field(
        default_factory=lambda: ControlNetPassConfig(weight=0.5)
    )
    controlnet_lineart: ControlNetPassConfig = field(
        default_factory=lambda: ControlNetPassConfig(weight=0.4)
    )
    # FaceDetailer second pass: detects the face in the stylized output,
    # crops+upscales it, and re-runs KSampler on just that region at a lower
    # denoise than the main pass -- keeps identity closer to the real
    # Daz-rendered face. See workflow_builder.py.
    face_detailer_enabled: bool = True
    # Live-tuned in Task 7 of docs/superpowers/plans/2026-08-05-faceid-conditioning.md
    # by comparing a denoise x faceid_weight grid against two characters
    # (abby_b, jason_a) once FaceID conditioning decoupled identity from
    # denoise. 0.35 -- matching the main body pass's own denoise -- produced
    # ink-hatching texture on the face comparable to the body, closing the
    # earlier photoreal-face-on-hatched-body mismatch, without visible loss
    # of facial identity at any weight in the tested grid. Note: this pass's
    # SAM-refined crop covers hair as well as face (see
    # face_detailer_bbox_dilation below), and IPAdapter FaceID's embedding
    # only encodes facial features, not hair color -- so hair color is *not*
    # locked to the source and can drift under restyling (confirmed on
    # jason_a's grey hair rendering brown/blonde across the whole tested
    # denoise/weight grid, independent of both knobs). Accepted as a known
    # limitation of this mechanism; see README.md.
    face_detailer_denoise: float = 0.35
    face_detailer_guide_size: float = 512.0
    # Bbox dilation (pixels) around the detected face region before
    # refining/pasting -- the face detector's bbox stops at the hairline, so
    # a generous dilation is needed to push the refined region up through
    # the whole head and avoid a visible hair-color seam at the boundary.
    face_detailer_bbox_dilation: int = 100
    # IPAdapter FaceID's own conditioning strength (0 = no identity
    # conditioning, higher = stronger identity lock at the cost of the
    # model's freedom to stylize). Live-tuned in Task 7 alongside
    # face_detailer_denoise: weight 0.8/1.0/1.2 produced visually
    # indistinguishable identity fidelity across the tested grid, so 1.0
    # (the middle, safest value) was kept as the default.
    face_detailer_faceid_weight: float = 1.0
    positive_prompt: str = (
        "graphic novel illustration, bold ink linework, cel-shaded, "
        "dramatic hatching, naturalistic proportions"
    )
    negative_prompt: str = "photorealistic, 3d render, blurry, watermark"


@dataclass
class RenderStageConfig:
    width: int = 1536
    height: int = 2048
    engine: str = "iray"
    quality_preset: str = "good"
    canvases: tuple[str, ...] = ("Normal", "Depth")


@dataclass
class PipelineConfig:
    scene_path: str = ""
    figure_label: str = ""
    output_dir: str = ""
    pose_library_dir: str = ""
    expression_library_dir: str = ""
    camera_front_label: str = "Character Camera - Front"
    camera_back_label: str = "Character Camera - Back"

    daz_url: str = "http://127.0.0.1:18811"
    daz_token: str = field(default_factory=_read_daz_token)
    daz_render_timeout_secs: float = 3700.0
    comfyui_url: str = "http://127.0.0.1:8188"

    render: RenderStageConfig = field(default_factory=RenderStageConfig)
    comfyui: ComfyUIStageConfig = field(default_factory=ComfyUIStageConfig)

    combos: list = field(default_factory=list)

    def camera_label(self, camera: str) -> str:
        if camera == "front":
            return self.camera_front_label
        if camera == "back":
            return self.camera_back_label
        raise ValueError(f"Unknown camera {camera!r}; expected 'front' or 'back'")


CAMERAS: tuple[str, ...] = ("front", "back")
