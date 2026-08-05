"""Render stage: iterate combos x {front, back}, apply pose+expression+overrides,
render beauty + AOV canvases via dazpy.

Uses DazRenderSettings.render() (not the higher-level render_api.render()/
render_variants()) because canvas/AOV support only exists on the low-level
class -- see dazpy/_render.py.
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field

from dazpy import DazClient, DazRenderSettings, DazScene, DazSceneState

import paths
from config import CAMERAS, PipelineConfig
from presets import apply_combo
from render_util import render_beauty_and_canvases


@dataclass
class RenderUnitResult:
    combo_id: str
    camera: str
    status: str  # "rendered", "skipped", "failed"
    duration_ms: float = 0.0
    error: str = ""


@dataclass
class RenderStageSummary:
    results: list[RenderUnitResult] = field(default_factory=list)

    @property
    def rendered(self) -> int:
        return sum(1 for r in self.results if r.status == "rendered")

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.status == "skipped")

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == "failed")

    @property
    def failures(self) -> list[RenderUnitResult]:
        return [r for r in self.results if r.status == "failed"]


class BaselineRestoreError(RuntimeError):
    pass


def run_render_stage(
    cfg: PipelineConfig,
    *,
    force: bool = False,
    only_combo: str | None = None,
    only_camera: str | None = None,
    on_progress=None,
) -> RenderStageSummary:
    client = DazClient(
        host=cfg.daz_url.replace("http://", "").split(":")[0],
        port=int(cfg.daz_url.rsplit(":", 1)[-1]),
        token=cfg.daz_token or None,
        timeout=cfg.daz_render_timeout_secs,
    )
    scene = DazScene(client)
    skeleton = scene.find_skeleton_by_label(cfg.figure_label)

    baseline = DazSceneState.capture(scene)

    rs = DazRenderSettings(client)
    rs.set_active_engine(cfg.render.engine)
    rs.set_quality_preset(cfg.render.quality_preset)
    rs.set_resolution(cfg.render.width, cfg.render.height)
    for canvas_name in cfg.render.canvases:
        rs.add_canvas(canvas_name, canvas_name)

    combos = [c for c in cfg.combos if only_combo is None or c.id == only_combo]
    cameras = [c for c in CAMERAS if only_camera is None or c == only_camera]
    units = [(combo, camera) for combo in combos for camera in cameras]

    summary = RenderStageSummary()
    total = len(units)

    for i, (combo, camera) in enumerate(units, start=1):
        if not force and paths.render_outputs_exist(cfg.output_dir, combo.id, camera, cfg.render.canvases):
            summary.results.append(RenderUnitResult(combo.id, camera, "skipped"))
            _report(on_progress, i, total, combo.id, camera, "SKIP (exists)")
            continue

        restore = baseline.apply(scene)
        if restore["errors"]:
            raise BaselineRestoreError(
                f"Baseline restore failed before combo {combo.id!r}/{camera}: {restore['errors']}"
            )

        t0 = time.monotonic()
        try:
            apply_combo(skeleton, cfg.figure_label, cfg.pose_library_dir, cfg.expression_library_dir, combo)
            out_path = paths.beauty_path(cfg.output_dir, combo.id, camera)
            _ensure_parent_dir(out_path)
            outcome = render_beauty_and_canvases(
                rs,
                output_path=out_path,
                camera_label=cfg.camera_label(camera),
                canvases=cfg.render.canvases,
            )
            if not outcome.success:
                raise RuntimeError(f"doRender() reported failure (output_path={outcome.output_path!r})")
        except Exception as exc:  # noqa: BLE001 - continue-and-log per unit
            duration_ms = (time.monotonic() - t0) * 1000
            summary.results.append(RenderUnitResult(combo.id, camera, "failed", duration_ms, str(exc)))
            _report(on_progress, i, total, combo.id, camera, f"FAIL: {exc}")
            continue

        duration_ms = (time.monotonic() - t0) * 1000
        summary.results.append(RenderUnitResult(combo.id, camera, "rendered", duration_ms))
        _report(on_progress, i, total, combo.id, camera, f"OK ({duration_ms:.0f}ms)")

    final_restore = baseline.apply(scene)
    if final_restore["errors"]:
        print(f"WARNING: final baseline restore had errors: {final_restore['errors']}", file=sys.stderr)

    return summary


def _ensure_parent_dir(path: str) -> None:
    import os

    os.makedirs(os.path.dirname(path), exist_ok=True)


def _report(on_progress, i, total, combo_id, camera, message) -> None:
    line = f"[{i}/{total}] render {combo_id} {camera} ... {message}"
    if on_progress is not None:
        on_progress(line)
    else:
        print(line)
