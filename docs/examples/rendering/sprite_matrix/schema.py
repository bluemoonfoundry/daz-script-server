"""Spec JSON parsing and validation for the sprite matrix pipeline.

See README.md for the full JSON schema documentation.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from config import ComfyUIStageConfig, ControlNetPassConfig, PipelineConfig, RenderStageConfig


class SpecValidationError(ValueError):
    pass


@dataclass
class ComboEntry:
    id: str
    pose: str
    expression: str
    overrides: dict = field(default_factory=dict)


def _sanitize_id(text: str) -> str:
    text = text.strip().lower().replace(" ", "_")
    return re.sub(r"[^a-z0-9_-]", "", text)


def _combo_id(entry: dict) -> str:
    explicit = entry.get("id")
    if explicit:
        return _sanitize_id(str(explicit))
    return _sanitize_id(f"{entry.get('pose', '')}__{entry.get('expression', '')}")


def _parse_combos(raw_combos: list, errors: list[str]) -> list[ComboEntry]:
    combos: list[ComboEntry] = []
    seen_ids: set[str] = set()
    for i, entry in enumerate(raw_combos):
        pose = entry.get("pose")
        expression = entry.get("expression")
        if not pose:
            errors.append(f"combos[{i}]: missing required field 'pose'")
        if not expression:
            errors.append(f"combos[{i}]: missing required field 'expression'")
        if not pose or not expression:
            continue

        combo_id = _combo_id(entry)
        if combo_id in seen_ids:
            errors.append(f"combos[{i}]: duplicate combo id {combo_id!r}")
            continue
        seen_ids.add(combo_id)

        overrides = entry.get("overrides", {})
        if overrides and not isinstance(overrides, dict):
            errors.append(f"combos[{i}]: 'overrides' must be an object")
            overrides = {}

        combos.append(ComboEntry(id=combo_id, pose=pose, expression=expression, overrides=overrides))
    return combos


def _require_unit_range(value: float, field_name: str, errors: list[str]) -> None:
    if not isinstance(value, (int, float)) or not (0.0 <= float(value) <= 1.0):
        errors.append(f"{field_name} must be in [0, 1], got {value!r}")


def _parse_controlnet_pass(raw: dict, field_name: str, errors: list[str]) -> ControlNetPassConfig:
    weight = raw.get("weight", 0.5)
    _require_unit_range(weight, f"comfyui.controlnet.{field_name}.weight", errors)
    return ControlNetPassConfig(weight=float(weight))


def load_spec(path: str | Path) -> PipelineConfig:
    """Load and validate a sprite matrix spec JSON file.

    Raises:
        SpecValidationError: If the spec fails any validation check. The
            exception message lists every problem found, not just the first.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    errors: list[str] = []

    scene_path = data.get("scene_path", "")
    sprite = data.get("sprite", {})
    figure_label = sprite.get("figure_label", "")
    if not figure_label:
        errors.append("sprite.figure_label is required")

    output_dir = data.get("output_dir", "")
    if not output_dir:
        errors.append("output_dir is required")

    pose_library_dir = data.get("pose_library_dir", "")
    expression_library_dir = data.get("expression_library_dir", "")
    if not pose_library_dir:
        errors.append("pose_library_dir is required")
    if not expression_library_dir:
        errors.append("expression_library_dir is required")

    cameras = data.get("cameras", {})
    front_label = cameras.get("front", {}).get("label", "")
    back_label = cameras.get("back", {}).get("label", "")
    if not front_label:
        errors.append("cameras.front.label is required")
    if not back_label:
        errors.append("cameras.back.label is required")

    render_raw = data.get("render", {})
    render_cfg = RenderStageConfig(
        width=int(render_raw.get("width", 1536)),
        height=int(render_raw.get("height", 2048)),
        engine=render_raw.get("engine", "iray"),
        quality_preset=render_raw.get("quality_preset", "good"),
        canvases=tuple(render_raw.get("canvases", ["Normal", "Depth"])),
    )
    if render_cfg.width <= 0 or render_cfg.height <= 0:
        errors.append("render.width and render.height must be positive")

    comfy_raw = data.get("comfyui", {})
    lora_raw = comfy_raw.get("lora", {})
    controlnet_raw = comfy_raw.get("controlnet", {})
    denoise = comfy_raw.get("denoise", 0.35)
    _require_unit_range(denoise, "comfyui.denoise", errors)
    lora_strength = lora_raw.get("strength", 0.8)
    controlnet_model = controlnet_raw.get("model", "")
    if not controlnet_model:
        errors.append("comfyui.controlnet.model is required")

    face_detailer_raw = comfy_raw.get("face_detailer", {})
    face_detailer_denoise = face_detailer_raw.get("denoise", 0.15)
    _require_unit_range(face_detailer_denoise, "comfyui.face_detailer.denoise", errors)

    comfy_cfg = ComfyUIStageConfig(
        checkpoint=comfy_raw.get("checkpoint", "graphicNovelStyleXL.safetensors"),
        lora_name=lora_raw.get("name", ""),
        lora_strength=float(lora_strength),
        denoise=float(denoise),
        base_seed=int(comfy_raw.get("base_seed", 0)),
        steps=int(comfy_raw.get("steps", 24)),
        cfg=float(comfy_raw.get("cfg", 7.0)),
        controlnet_model=controlnet_model,
        controlnet_normal=_parse_controlnet_pass(controlnet_raw.get("normal", {}), "normal", errors),
        controlnet_depth=_parse_controlnet_pass(controlnet_raw.get("depth", {}), "depth", errors),
        controlnet_lineart=_parse_controlnet_pass(controlnet_raw.get("lineart", {}), "lineart", errors),
        face_detailer_enabled=bool(face_detailer_raw.get("enabled", True)),
        face_detailer_denoise=float(face_detailer_denoise),
        face_detailer_guide_size=float(face_detailer_raw.get("guide_size", 512.0)),
        face_detailer_bbox_dilation=int(face_detailer_raw.get("bbox_dilation", 100)),
        positive_prompt=comfy_raw.get("positive_prompt", ComfyUIStageConfig.positive_prompt),
        negative_prompt=comfy_raw.get("negative_prompt", ComfyUIStageConfig.negative_prompt),
    )

    raw_combos = data.get("combos", [])
    if not raw_combos:
        errors.append("combos must contain at least one entry")
    combos = _parse_combos(raw_combos, errors)

    base_dir = os.path.dirname(os.path.abspath(str(path)))

    def _resolve(p: str) -> str:
        return p if os.path.isabs(p) else os.path.join(base_dir, p)

    if pose_library_dir and expression_library_dir:
        for combo in combos:
            pose_path = os.path.join(_resolve(pose_library_dir), f"{combo.pose}.json")
            expr_path = os.path.join(_resolve(expression_library_dir), f"{combo.expression}.json")
            if not os.path.isfile(pose_path):
                errors.append(f"combo {combo.id!r}: pose preset not found: {pose_path}")
            if not os.path.isfile(expr_path):
                errors.append(f"combo {combo.id!r}: expression preset not found: {expr_path}")

    if errors:
        raise SpecValidationError(
            f"{len(errors)} error(s) in spec {path}:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    return PipelineConfig(
        scene_path=scene_path,
        figure_label=figure_label,
        output_dir=_resolve(output_dir),
        pose_library_dir=_resolve(pose_library_dir),
        expression_library_dir=_resolve(expression_library_dir),
        camera_front_label=front_label,
        camera_back_label=back_label,
        render=render_cfg,
        comfyui=comfy_cfg,
        combos=combos,
    )
