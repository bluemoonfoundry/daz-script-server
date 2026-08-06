"""Stylization stage: iterate combos x {front, back}, feed beauty+AOVs+lineart
into ComfyUI's multi-ControlNet img2img workflow, resume-by-file-existence.

Reads render stage output files from disk -- independent of whether the
render stage just ran in the same process.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from comfyui_client import ComfyUIClient, ComfyUIExecutionError

import paths
from canvas_convert import convert_depth_exr_to_png, convert_normal_exr_to_png, derive_lineart
from config import CAMERAS, PipelineConfig
from workflow_builder import build_controlnet_workflow, stable_seed


@dataclass
class StylizeUnitResult:
    combo_id: str
    camera: str
    status: str  # "stylized", "skipped", "failed"
    duration_ms: float = 0.0
    error: str = ""
    note: str = ""  # non-fatal detail on an otherwise successful unit, e.g.
    # "face-identity pass skipped: <reason>" when the FaceID retry fires


@dataclass
class StylizeStageSummary:
    results: list[StylizeUnitResult] = field(default_factory=list)

    @property
    def stylized(self) -> int:
        return sum(1 for r in self.results if r.status == "stylized")

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.status == "skipped")

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == "failed")

    @property
    def failures(self) -> list[StylizeUnitResult]:
        return [r for r in self.results if r.status == "failed"]


def run_stylize_stage(
    cfg: PipelineConfig,
    *,
    force: bool = False,
    only_combo: str | None = None,
    only_camera: str | None = None,
    on_progress=None,
) -> StylizeStageSummary:
    comfy = ComfyUIClient(base_url=cfg.comfyui_url)

    combos = [c for c in cfg.combos if only_combo is None or c.id == only_combo]
    cameras = [c for c in CAMERAS if only_camera is None or c == only_camera]
    units = [(combo, camera) for combo in combos for camera in cameras]

    summary = StylizeStageSummary()
    total = len(units)

    for i, (combo, camera) in enumerate(units, start=1):
        out_path = paths.stylized_path(cfg.output_dir, combo.id, camera)
        if not force and os.path.isfile(out_path):
            summary.results.append(StylizeUnitResult(combo.id, camera, "skipped"))
            _report(on_progress, i, total, combo.id, camera, "SKIP (exists)")
            continue

        t0 = time.monotonic()
        note = ""
        try:
            beauty = paths.beauty_path(cfg.output_dir, combo.id, camera)
            normal_exr = paths.canvas_path(cfg.output_dir, combo.id, camera, "Normal", "Normal")
            depth_exr = paths.canvas_path(cfg.output_dir, combo.id, camera, "Depth", "Depth")
            for required in (beauty, normal_exr, depth_exr):
                if not os.path.isfile(required):
                    raise FileNotFoundError(f"missing render input: {required}")

            normal_png = convert_normal_exr_to_png(normal_exr, paths.normal_png_path(cfg.output_dir, combo.id, camera))
            depth_png = convert_depth_exr_to_png(depth_exr, paths.depth_png_path(cfg.output_dir, combo.id, camera))
            lineart_png = derive_lineart(beauty, paths.lineart_path(cfg.output_dir, combo.id, camera))

            beauty_ref = comfy.upload_image(beauty)
            normal_ref = comfy.upload_image(normal_png)
            depth_ref = comfy.upload_image(depth_png)
            lineart_ref = comfy.upload_image(lineart_png)

            def _run(face_detailer_enabled: bool) -> None:
                workflow = build_controlnet_workflow(
                    beauty_image_ref=beauty_ref,
                    normal_image_ref=normal_ref,
                    depth_image_ref=depth_ref,
                    lineart_image_ref=lineart_ref,
                    checkpoint_name=cfg.comfyui.checkpoint,
                    lora_name=cfg.comfyui.lora_name,
                    lora_strength=cfg.comfyui.lora_strength,
                    denoise=cfg.comfyui.denoise,
                    steps=cfg.comfyui.steps,
                    cfg=cfg.comfyui.cfg,
                    seed=stable_seed(cfg.comfyui.base_seed, combo.id, camera),
                    positive_prompt=cfg.comfyui.positive_prompt,
                    negative_prompt=cfg.comfyui.negative_prompt,
                    controlnet_model=cfg.comfyui.controlnet_model,
                    controlnet_normal_weight=cfg.comfyui.controlnet_normal.weight,
                    controlnet_depth_weight=cfg.comfyui.controlnet_depth.weight,
                    controlnet_lineart_weight=cfg.comfyui.controlnet_lineart.weight,
                    face_detailer_enabled=face_detailer_enabled,
                    face_detailer_denoise=cfg.comfyui.face_detailer_denoise,
                    face_detailer_guide_size=cfg.comfyui.face_detailer_guide_size,
                    face_detailer_bbox_dilation=cfg.comfyui.face_detailer_bbox_dilation,
                    face_detailer_faceid_weight=cfg.comfyui.face_detailer_faceid_weight,
                    face_detailer_controlnet_normal_weight=cfg.comfyui.face_detailer_controlnet_normal_weight,
                    face_detailer_controlnet_depth_weight=cfg.comfyui.face_detailer_controlnet_depth_weight,
                    face_detailer_controlnet_lineart_weight=cfg.comfyui.face_detailer_controlnet_lineart_weight,
                )
                prompt_id = comfy.queue_prompt(workflow)
                comfy.save_result(prompt_id, out_path, timeout=300.0)

            try:
                _run(cfg.comfyui.face_detailer_enabled)
            except ComfyUIExecutionError as exc:
                if not cfg.comfyui.face_detailer_enabled:
                    raise
                # The face-identity pass's IPAdapterFaceID node needs
                # InsightFace to find a face in the ORIGINAL beauty render;
                # that's not guaranteed (e.g. an over-the-shoulder/back
                # camera shot has no face at all). The old low-denoise
                # mechanism degraded past a missing face silently -- FaceID
                # conditioning cannot, since it's the exact thing that
                # crashes. Retry once with the whole pass off rather than
                # failing this unit outright.
                _run(False)
                note = f" (face-identity pass skipped: {exc})"
        except Exception as exc:  # noqa: BLE001 - continue-and-log per unit
            duration_ms = (time.monotonic() - t0) * 1000
            summary.results.append(StylizeUnitResult(combo.id, camera, "failed", duration_ms, str(exc)))
            _report(on_progress, i, total, combo.id, camera, f"FAIL: {exc}")
            continue

        duration_ms = (time.monotonic() - t0) * 1000
        summary.results.append(StylizeUnitResult(combo.id, camera, "stylized", duration_ms, note=note))
        _report(on_progress, i, total, combo.id, camera, f"OK ({duration_ms:.0f}ms){note}")

    return summary


def _report(on_progress, i, total, combo_id, camera, message) -> None:
    line = f"[{i}/{total}] stylize {combo_id} {camera} ... {message}"
    if on_progress is not None:
        on_progress(line)
    else:
        print(line)
