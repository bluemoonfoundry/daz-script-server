"""DAZ-to-ComfyUI img2img enhancement pipeline.

Usage:
    python main.py [--output PATH] [--denoise FLOAT] [--no-watch] [--snapshot-path PATH] [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dazpy import DazClient, DazViewport

from config import PipelineConfig
from comfyui_client import ComfyUIClient
from file_watcher import FileWatcher
from workflow_builder import build as build_workflow


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="DAZ Studio → ComfyUI img2img enhancement")
    p.add_argument("--config", metavar="PATH", help="Path to config.py (unused; edit config.py directly)")
    p.add_argument("--output", metavar="PATH", help="Output path for enhanced image")
    p.add_argument("--denoise", type=float, help="Override denoise strength (0.0–1.0)")
    p.add_argument("--no-watch", action="store_true", help="Skip file watcher; use --snapshot-path directly")
    p.add_argument("--snapshot-path", metavar="PATH", help="Existing snapshot to submit (requires --no-watch)")
    p.add_argument("--checkpoint", metavar="NAME", help="Override ComfyUI checkpoint filename")
    p.add_argument("--dry-run", action="store_true", help="Print plan without executing")
    return p.parse_args()


def _fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    args = _parse_args()
    cfg = PipelineConfig()

    if args.denoise is not None:
        cfg.denoise_strength = args.denoise
    if args.checkpoint is not None:
        cfg.checkpoint_name = args.checkpoint

    snapshot_path = os.path.join(cfg.watch_dir, "daz_snapshot.png")
    output_path = args.output or os.path.join(cfg.output_dir, "daz_enhanced.png")

    if args.dry_run:
        print("=== Dry run ===")
        print(f"  DAZ server:     {cfg.daz_url}")
        print(f"  ComfyUI server: {cfg.comfyui_url}")
        print(f"  Snapshot path:  {snapshot_path}")
        print(f"  Output path:    {output_path}")
        print(f"  Checkpoint:     {cfg.checkpoint_name}")
        print(f"  Denoise:        {cfg.denoise_strength}")
        print(f"  Steps:          {cfg.steps}")
        print(f"  Watch dir:      {cfg.watch_dir}")
        print("  (dry run — no actions taken)")
        return

    # ── 1. Connect to DAZ Studio ──────────────────────────────────────────────
    print("Connecting to DAZ Studio...", end=" ", flush=True)
    try:
        daz_client = DazClient(host=cfg.daz_url.replace("http://", "").split(":")[0],
                                port=int(cfg.daz_url.rsplit(":", 1)[-1]),
                                token=cfg.daz_token or None)
        daz_viewport = DazViewport(daz_client)
        if not daz_viewport.is_available():
            _fail("DAZ Studio is reachable but no 3D viewport is open.")
    except Exception as exc:
        _fail(f"Cannot reach DAZ Studio at {cfg.daz_url}: {exc}")
    print("OK")

    # ── 2. Connect to ComfyUI ─────────────────────────────────────────────────
    print("Connecting to ComfyUI...", end=" ", flush=True)
    try:
        comfy = ComfyUIClient(base_url=cfg.comfyui_url)
        comfy.get_system_stats()
    except Exception as exc:
        _fail(f"Cannot reach ComfyUI at {cfg.comfyui_url}: {exc}")
    print("OK")

    # ── 3. Capture viewport ───────────────────────────────────────────────────
    if args.no_watch:
        if not args.snapshot_path:
            _fail("--no-watch requires --snapshot-path")
        snapshot_path = args.snapshot_path
        if not os.path.isfile(snapshot_path):
            _fail(f"Snapshot file not found: {snapshot_path}")
        print(f"Using existing snapshot: {snapshot_path}")
    else:
        watcher = FileWatcher()
        print(f"Capturing viewport to {snapshot_path}...")
        daz_viewport.capture(snapshot_path, width=cfg.snapshot_width, height=cfg.snapshot_height)
        print("Waiting for file...", end=" ", flush=True)
        try:
            snapshot_path = watcher.watch(cfg.watch_dir, pattern="daz_snapshot.png", timeout=30.0)
        except TimeoutError:
            _fail("Viewport capture did not produce a file within 30s.")
        print(f"OK ({snapshot_path})")

    # ── 4. Upload to ComfyUI ──────────────────────────────────────────────────
    print("Uploading image to ComfyUI...", end=" ", flush=True)
    try:
        image_ref = comfy.upload_image(snapshot_path)
    except Exception as exc:
        _fail(f"Upload failed: {exc}")
    print(f"OK ({image_ref})")

    # ── 5. Build and submit workflow ──────────────────────────────────────────
    print("Submitting workflow...", end=" ", flush=True)
    workflow = build_workflow(
        image_ref,
        checkpoint_name=cfg.checkpoint_name,
        denoise=cfg.denoise_strength,
        steps=cfg.steps,
    )
    try:
        prompt_id = comfy.queue_prompt(workflow)
    except Exception as exc:
        _fail(f"Failed to queue workflow: {exc}")
    print(f"OK (prompt_id={prompt_id})")

    # ── 6. Wait for result ────────────────────────────────────────────────────
    print("Waiting for ComfyUI to finish", end="", flush=True)
    t0 = time.monotonic()
    try:
        def _dot_progress() -> None:
            pass
        result_path = comfy.save_result(prompt_id, output_path, timeout=120.0)
    except TimeoutError:
        print()
        _fail("ComfyUI did not complete within 120s.")
    except Exception as exc:
        print()
        _fail(f"Failed to retrieve result: {exc}")
    elapsed = time.monotonic() - t0
    print(f" done ({elapsed:.1f}s)")

    # ── 7. Done ───────────────────────────────────────────────────────────────
    print(f"\nEnhanced image saved: {result_path}")


if __name__ == "__main__":
    main()
