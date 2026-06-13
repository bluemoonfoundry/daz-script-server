"""DAZ Studio Script Server example: render from every camera in the scene in one pass.

PURPOSE
-------
This script is a demonstration of what the DAZ Studio Script Server makes
possible.  It iterates all cameras in the live DAZ Studio scene and renders
from each one in turn, saving the output as <camera_label>.png in a chosen
directory.

It is an *example*, not a production multi-pass render manager.  A full
pipeline would also handle render layers, lighting rigs per camera, and
output EXR compositing.  The goal here is to show that Python can enumerate
scene cameras and drive the render engine to cover multiple angles in a
single script run — useful for storyboarding, product shots, or coverage
renders.

WHAT IT DEMONSTRATES
--------------------
  - Listing all cameras in the live scene (DazScene.cameras)
  - Filtering cameras by label via --cameras
  - Setting render resolution and triggering a render for each camera
  - Sanitising camera labels into safe filenames for output

ENVIRONMENT SETUP
-----------------
1. DAZ Studio must be running with the DazScriptServer plugin loaded and its
   HTTP server active (default: 127.0.0.1:18811).  You can verify it is
   responding with:

       curl http://127.0.0.1:18811/health

2. Install the Python dependencies in a virtual environment:

       python -m venv .venv
       .venv\\Scripts\\activate          # Windows
       # source .venv/bin/activate     # macOS / Linux
       pip install requests

3. Install or develop-install the dazpy SDK (from the repo root):

       pip install -e .

4. Open a scene in DAZ Studio with one or more cameras, then run:

       python docs/examples/rendering/multi_camera_render.py

Usage:
    python multi_camera_render.py
    python multi_camera_render.py --out C:/renders --width 1920 --height 1080
    python multi_camera_render.py --cameras "Front" "Side" "Hero Shot"
"""

import argparse
import os
import re

from dazpy import DazScene, DazRenderSettings


def safe_filename(label: str) -> str:
    return re.sub(r'[^\w\-]', '_', label).strip('_') or "camera"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
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

    print(f"Rendering {len(cameras)} camera(s) → {args.out}")

    for cam in cameras:
        label = cam.label or cam.name
        out_path = os.path.join(args.out, f"{safe_filename(label)}.png")
        render.output_path = out_path
        render.render(camera_name=cam.name)
        print(f"  {label} → {out_path}")

    print("Done.")
