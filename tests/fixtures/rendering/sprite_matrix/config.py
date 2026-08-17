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
    # Multiply-blend opacity for compositing the deterministic Canny lineart
    # pass back over the ComfyUI color output (0.0 = color output unchanged,
    # 1.0 = full multiply blend). See canvas_convert.py's multiply_blend().
    lineart_composite_opacity: float = 1.0
    # Canny edge-detection thresholds for canvas_convert.derive_lineart().
    # See that function's docstring for the live-tuning rationale (daz-
    # script-server-r5br/017n) -- 150/300 suppresses soft Iray shading
    # edges on faces that read as artifactual "pencil marks" once
    # composited, without losing structural linework.
    canny_low_threshold: int = 150
    canny_high_threshold: int = 300
    positive_prompt: str = (
        "graphic novel illustration, bold ink linework, cel-shaded, "
        "dramatic hatching, naturalistic proportions"
    )
    # Live-tuned against jason_a/abby_b (daz-script-server-r5br): the
    # Graphic_Novel LoRA at full strength draws harsh ink lines along facial
    # creases (brow ridge, under-eye, nasolabial fold) that read as
    # artifactual "pencil marks" rather than stylistic linework -- confirmed
    # via isolating lora_strength=0.0 (lines vanish) vs 0.8 (lines present)
    # with every ControlNet/composite setting held constant. Explicitly
    # suppressing that behavior in the negative prompt removes it cleanly on
    # both test characters without affecting the LoRA's ink-hatching texture
    # on clothing/body, and without any architecture change (no face-region
    # pass needed -- see daz-script-server-fsq8, abandoned after making the
    # face worse by reusing per-region ControlNet weights tuned for a
    # different, now-removed identity-conditioning mechanism).
    negative_prompt: str = (
        "photorealistic, 3d render, blurry, watermark, "
        "harsh facial crosshatching, heavy dark under-eye ink lines, "
        "dark eye bags, exaggerated brow line, pencil scribble on face, "
        "heavy facial ink shading, harsh nasolabial lines"
    )


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
