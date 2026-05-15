"""Render from every camera in the scene and save each to a named file.

Iterates scene.cameras(), renders from each one in turn, and saves the
output to <out>/<camera_label>.png.  Useful for covering multiple angles
in a single script run (storyboarding, product shots, etc.).

Usage:
    python multi_camera_render.py
    python multi_camera_render.py --out C:/renders --width 1920 --height 1080
    python multi_camera_render.py --cameras "Front" "Side" "Hero Shot"
"""

import argparse
import os
import re

from dazpy import DazScene, DazRenderSettings

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--out",     default="y:/tmp/multicam", help="Output directory")
parser.add_argument("--width",   type=int, default=1920)
parser.add_argument("--height",  type=int, default=1080)
parser.add_argument("--cameras", nargs="+", metavar="LABEL",
                    help="Render only these cameras (by label). Default: all cameras.")
args = parser.parse_args()

os.makedirs(args.out, exist_ok=True)

scene  = DazScene()
render = DazRenderSettings()

cameras = scene.cameras()
if not cameras:
    raise SystemExit("No cameras found in the scene.")

if args.cameras:
    cameras = [c for c in cameras if c.label in args.cameras]
    if not cameras:
        raise SystemExit(f"None of the specified cameras found. Available: "
                         f"{[c.label for c in scene.cameras()]}")

render.set_resolution(args.width, args.height)

def safe_filename(label: str) -> str:
    return re.sub(r'[^\w\-]', '_', label).strip('_') or "camera"

print(f"Rendering {len(cameras)} camera(s) → {args.out}")

for cam in cameras:
    label = cam.label or cam.name
    out_path = os.path.join(args.out, f"{safe_filename(label)}.png")
    render.output_path = out_path
    render.render(camera_name=cam.name)
    print(f"  {label} → {out_path}")

print("Done.")
