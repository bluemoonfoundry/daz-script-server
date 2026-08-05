"""Sprite matrix pipeline: Daz pose/expression batch render + ComfyUI
graphic-novel stylization.

Usage:
    python main.py --spec spec.json [--stage all|render|stylize] [--dry-run]
                    [--force] [--combo ID] [--camera front|back]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "comfyui_enhance"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from schema import SpecValidationError, load_spec
from config import CAMERAS


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Sprite matrix: Daz batch render + ComfyUI graphic-novel stylization")
    p.add_argument("--spec", required=True, metavar="PATH", help="Path to the spec JSON file")
    p.add_argument("--stage", choices=["all", "render", "stylize"], default="all")
    p.add_argument("--dry-run", action="store_true", help="Print the expanded work plan without executing")
    p.add_argument("--force", action="store_true", help="Bypass resume/skip checks for this run")
    p.add_argument("--combo", metavar="ID", help="Restrict to a single combo id")
    p.add_argument("--camera", choices=list(CAMERAS), help="Restrict to a single camera")
    return p.parse_args()


def _fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def _dry_run(cfg, only_combo, only_camera) -> None:
    import os

    import paths

    combos = [c for c in cfg.combos if only_combo is None or c.id == only_combo]
    cameras = [c for c in CAMERAS if only_camera is None or c == only_camera]

    print("=== Dry run ===")
    print(f"  Daz server:     {cfg.daz_url}")
    print(f"  ComfyUI server: {cfg.comfyui_url}")
    print(f"  Output dir:     {cfg.output_dir}")
    print(f"  Combos:         {len(combos)}  Cameras: {cameras}")
    print()
    for combo in combos:
        for camera in cameras:
            beauty = paths.beauty_path(cfg.output_dir, combo.id, camera)
            stylized = paths.stylized_path(cfg.output_dir, combo.id, camera)
            render_done = paths.render_outputs_exist(cfg.output_dir, combo.id, camera, cfg.render.canvases)
            stylize_done = os.path.isfile(stylized)
            print(
                f"  {combo.id:40s} {camera:5s} "
                f"render={'SKIP' if render_done else 'DO  '} ({beauty}) "
                f"stylize={'SKIP' if stylize_done else 'DO  '} ({stylized})"
            )
    print("\n  (dry run -- no actions taken)")


def main() -> None:
    args = _parse_args()

    try:
        cfg = load_spec(args.spec)
    except SpecValidationError as exc:
        _fail(str(exc))
        return

    if args.dry_run:
        _dry_run(cfg, args.combo, args.camera)
        return

    render_summary = None
    stylize_summary = None

    if args.stage in ("all", "render"):
        from render_stage import run_render_stage

        print("=== Render stage ===")
        t0 = time.monotonic()
        render_summary = run_render_stage(cfg, force=args.force, only_combo=args.combo, only_camera=args.camera)
        elapsed = time.monotonic() - t0
        print(
            f"Render stage done in {elapsed:.1f}s: "
            f"{render_summary.rendered} rendered, {render_summary.skipped} skipped, {render_summary.failed} failed"
        )
        for f in render_summary.failures:
            print(f"  FAILED: {f.combo_id} {f.camera}: {f.error}", file=sys.stderr)

    if args.stage in ("all", "stylize"):
        from stylize_stage import run_stylize_stage

        print("\n=== Stylize stage ===")
        t0 = time.monotonic()
        stylize_summary = run_stylize_stage(cfg, force=args.force, only_combo=args.combo, only_camera=args.camera)
        elapsed = time.monotonic() - t0
        print(
            f"Stylize stage done in {elapsed:.1f}s: "
            f"{stylize_summary.stylized} stylized, {stylize_summary.skipped} skipped, {stylize_summary.failed} failed"
        )
        for f in stylize_summary.failures:
            print(f"  FAILED: {f.combo_id} {f.camera}: {f.error}", file=sys.stderr)

    any_failed = (render_summary and render_summary.failed) or (stylize_summary and stylize_summary.failed)
    sys.exit(1 if any_failed else 0)


if __name__ == "__main__":
    main()
