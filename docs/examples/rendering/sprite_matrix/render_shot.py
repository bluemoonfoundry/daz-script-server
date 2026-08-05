"""Single-shot variant of the sprite matrix pipeline: starts at the render
step, assuming the pose and expression are already set up by hand in the
live Daz Studio scene.

No JSON spec, no pose/expression preset library, no combo matrix -- just a
named shot, rendered from front and/or back camera and (optionally)
stylized via the same ComfyUI multi-ControlNet graphic-novel workflow used
by the batch pipeline. Outputs land in the same directory layout as
main.py's combo-driven runs (`<output_dir>/renders/<name>/...`,
`<output_dir>/stylized/<name>/...`), so a one-off shot and a batch run can
share an output_dir without colliding, and both are resumable the same way
(skip if the output file already exists).

Usage:
    python render_shot.py --name shot001 --output-dir C:/output/hero_sprites \
        --stage all --checkpoint graphicNovelStyleXL.safetensors \
        --lora-name gn_ink_v2.safetensors --controlnet-normal-model control-normal-xl.safetensors \
        --controlnet-depth-model control-depth-xl.safetensors --controlnet-lineart-model control-lineart-xl.safetensors
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "comfyui_enhance"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import paths
from config import CAMERAS, ComfyUIStageConfig, PipelineConfig, RenderStageConfig


def _parse_args() -> argparse.Namespace:
    defaults = PipelineConfig()
    comfy_defaults = ComfyUIStageConfig()
    render_defaults = RenderStageConfig()

    p = argparse.ArgumentParser(
        description="Render (and optionally stylize) a single shot from the current Daz scene state"
    )
    p.add_argument("--name", required=True, help="Shot id, used as the output directory/file name")
    p.add_argument("--output-dir", required=True, metavar="DIR")
    p.add_argument("--stage", choices=["all", "render", "stylize"], default="all")
    p.add_argument("--camera", choices=["front", "back", "both"], default="both")
    p.add_argument("--camera-front-label", default=defaults.camera_front_label)
    p.add_argument("--camera-back-label", default=defaults.camera_back_label)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true")

    p.add_argument("--daz-url", default=defaults.daz_url)
    p.add_argument("--daz-render-timeout-secs", type=float, default=defaults.daz_render_timeout_secs)
    p.add_argument("--comfyui-url", default=defaults.comfyui_url)

    p.add_argument("--width", type=int, default=render_defaults.width)
    p.add_argument("--height", type=int, default=render_defaults.height)
    p.add_argument("--engine", default=render_defaults.engine)
    p.add_argument("--quality-preset", default=render_defaults.quality_preset)
    p.add_argument(
        "--canvases",
        default=",".join(render_defaults.canvases),
        help="Comma-separated Iray Canvas types to render (e.g. Normal,Depth)",
    )

    p.add_argument("--checkpoint", default=comfy_defaults.checkpoint)
    p.add_argument("--lora-name", default=comfy_defaults.lora_name)
    p.add_argument("--lora-strength", type=float, default=comfy_defaults.lora_strength)
    p.add_argument("--denoise", type=float, default=comfy_defaults.denoise)
    p.add_argument("--base-seed", type=int, default=comfy_defaults.base_seed)
    p.add_argument("--steps", type=int, default=comfy_defaults.steps)
    p.add_argument("--cfg", type=float, default=comfy_defaults.cfg)
    p.add_argument("--positive-prompt", default=comfy_defaults.positive_prompt)
    p.add_argument("--negative-prompt", default=comfy_defaults.negative_prompt)
    p.add_argument(
        "--controlnet-model",
        default=comfy_defaults.controlnet_model,
        help="Single SDXL union ControlNet model, re-tagged per pass via SetUnionControlNetType "
        "(e.g. controlnet-union-sdxl-1.0.safetensors)",
    )
    p.add_argument("--controlnet-normal-weight", type=float, default=comfy_defaults.controlnet_normal.weight)
    p.add_argument("--controlnet-depth-weight", type=float, default=comfy_defaults.controlnet_depth.weight)
    p.add_argument("--controlnet-lineart-weight", type=float, default=comfy_defaults.controlnet_lineart.weight)

    return p.parse_args()


def _fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def _cameras_for(arg: str) -> tuple[str, ...]:
    return CAMERAS if arg == "both" else (arg,)


def _camera_label(args: argparse.Namespace, camera: str) -> str:
    return args.camera_front_label if camera == "front" else args.camera_back_label


def render_shot(args: argparse.Namespace, canvases: tuple[str, ...]) -> bool:
    from dazpy import DazClient, DazRenderSettings

    client = DazClient(
        host=args.daz_url.replace("http://", "").split(":")[0],
        port=int(args.daz_url.rsplit(":", 1)[-1]),
        timeout=args.daz_render_timeout_secs,
    )
    rs = DazRenderSettings(client)
    rs.set_active_engine(args.engine)
    rs.set_quality_preset(args.quality_preset)
    rs.set_resolution(args.width, args.height)
    rs.canvases_enabled = bool(canvases)
    for canvas_name in canvases:
        rs.add_canvas(canvas_name, canvas_name)

    any_failed = False
    for camera in _cameras_for(args.camera):
        if not args.force and paths.render_outputs_exist(args.output_dir, args.name, camera, canvases):
            print(f"render {args.name} {camera} ... SKIP (exists)")
            continue

        out_path = paths.beauty_path(args.output_dir, args.name, camera)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        t0 = time.monotonic()
        try:
            rs.output_path = out_path
            outcome = rs.render(camera_label=_camera_label(args, camera))
            if not outcome.success:
                raise RuntimeError(f"doRender() reported failure (output_path={outcome.output_path!r})")
        except Exception as exc:  # noqa: BLE001 - continue-and-log per camera
            any_failed = True
            print(f"render {args.name} {camera} ... FAIL: {exc}", file=sys.stderr)
            continue
        duration_ms = (time.monotonic() - t0) * 1000
        print(f"render {args.name} {camera} ... OK ({duration_ms:.0f}ms)")

    return not any_failed


def stylize_shot(args: argparse.Namespace) -> bool:
    from canvas_convert import convert_depth_exr_to_png, convert_normal_exr_to_png, derive_lineart
    from comfyui_client import ComfyUIClient
    from workflow_builder import build_controlnet_workflow, stable_seed

    comfy = ComfyUIClient(base_url=args.comfyui_url)
    any_failed = False

    for camera in _cameras_for(args.camera):
        out_path = paths.stylized_path(args.output_dir, args.name, camera)
        if not args.force and os.path.isfile(out_path):
            print(f"stylize {args.name} {camera} ... SKIP (exists)")
            continue

        t0 = time.monotonic()
        try:
            beauty = paths.beauty_path(args.output_dir, args.name, camera)
            normal_exr = paths.canvas_path(args.output_dir, args.name, camera, "Normal", "Normal")
            depth_exr = paths.canvas_path(args.output_dir, args.name, camera, "Depth", "Depth")
            for required in (beauty, normal_exr, depth_exr):
                if not os.path.isfile(required):
                    raise FileNotFoundError(f"missing render input: {required}")

            normal_png = convert_normal_exr_to_png(normal_exr, paths.normal_png_path(args.output_dir, args.name, camera))
            depth_png = convert_depth_exr_to_png(depth_exr, paths.depth_png_path(args.output_dir, args.name, camera))
            lineart_png = derive_lineart(beauty, paths.lineart_path(args.output_dir, args.name, camera))

            beauty_ref = comfy.upload_image(beauty)
            normal_ref = comfy.upload_image(normal_png)
            depth_ref = comfy.upload_image(depth_png)
            lineart_ref = comfy.upload_image(lineart_png)

            workflow = build_controlnet_workflow(
                beauty_image_ref=beauty_ref,
                normal_image_ref=normal_ref,
                depth_image_ref=depth_ref,
                lineart_image_ref=lineart_ref,
                checkpoint_name=args.checkpoint,
                lora_name=args.lora_name,
                lora_strength=args.lora_strength,
                denoise=args.denoise,
                steps=args.steps,
                cfg=args.cfg,
                seed=stable_seed(args.base_seed, args.name, camera),
                positive_prompt=args.positive_prompt,
                negative_prompt=args.negative_prompt,
                controlnet_model=args.controlnet_model,
                controlnet_normal_weight=args.controlnet_normal_weight,
                controlnet_depth_weight=args.controlnet_depth_weight,
                controlnet_lineart_weight=args.controlnet_lineart_weight,
            )
            prompt_id = comfy.queue_prompt(workflow)
            comfy.save_result(prompt_id, out_path, timeout=300.0)
        except Exception as exc:  # noqa: BLE001 - continue-and-log per camera
            any_failed = True
            print(f"stylize {args.name} {camera} ... FAIL: {exc}", file=sys.stderr)
            continue

        duration_ms = (time.monotonic() - t0) * 1000
        print(f"stylize {args.name} {camera} ... OK ({duration_ms:.0f}ms)")

    return not any_failed


def main() -> None:
    args = _parse_args()
    canvases = tuple(c.strip() for c in args.canvases.split(",") if c.strip())

    if args.dry_run:
        print("=== Dry run ===")
        print(f"  Daz server:     {args.daz_url}")
        print(f"  ComfyUI server: {args.comfyui_url}")
        print(f"  Output dir:     {args.output_dir}")
        print(f"  Shot:           {args.name}  Cameras: {list(_cameras_for(args.camera))}")
        for camera in _cameras_for(args.camera):
            beauty = paths.beauty_path(args.output_dir, args.name, camera)
            stylized = paths.stylized_path(args.output_dir, args.name, camera)
            render_done = paths.render_outputs_exist(args.output_dir, args.name, camera, canvases)
            stylize_done = os.path.isfile(stylized)
            print(
                f"  {camera:5s} render={'SKIP' if render_done else 'DO  '} ({beauty}) "
                f"stylize={'SKIP' if stylize_done else 'DO  '} ({stylized})"
            )
        print("\n  (dry run -- no actions taken)")
        return

    ok = True
    if args.stage in ("all", "render"):
        ok = render_shot(args, canvases) and ok
    if args.stage in ("all", "stylize"):
        ok = stylize_shot(args) and ok

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
