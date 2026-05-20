"""DAZ Studio Script Server example: render a 360-degree turntable of a figure.

PURPOSE
-------
This script is a demonstration of what the DAZ Studio Script Server makes
possible.  It rotates a figure around its local Y axis in even increments and
renders each step to a numbered PNG, producing the frames needed for a
turntable video — all without touching DAZ Studio's UI or the timeline.

It is an *example*, not a production turntable tool.  A full turntable system
would also handle camera orbit (instead of object rotation), HDRI rotation for
consistent lighting, and background transparency.  The goal here is to show
that the script server lets Python drive the DAZ render engine in a loop to
produce a multi-frame sequence from a single posed scene.

WHAT IT DEMONSTRATES
--------------------
  - Reading a figure's existing local rotation to preserve X and Z while
    rotating only Y (so a posed character stays posed through the spin)
  - Setting a figure's rotation and triggering a render for each step
  - Restoring the original rotation on exit, even if the run is interrupted
  - Printing an ffmpeg command to assemble the frames into a video

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

4. Open a scene in DAZ Studio containing the target figure, then run:

       python docs/examples/turntable.py

Usage:
    python turntable.py
    python turntable.py --figure "My Character" --steps 72 --out C:/turntable
"""

import argparse
import os

from dazpy import DazScene, DazRenderSettings

parser = argparse.ArgumentParser()
parser.add_argument("--figure", default="Genesis 9", help="Figure label in the Scene panel")
parser.add_argument("--steps",  type=int, default=36, help="Number of frames for a full 360°")
parser.add_argument("--out",    default="y:/tmp/turntable", help="Output directory")
parser.add_argument("--width",  type=int, default=1920)
parser.add_argument("--height", type=int, default=1080)
args = parser.parse_args()

os.makedirs(args.out, exist_ok=True)

scene  = DazScene()
render = DazRenderSettings()
figure = scene.find_skeleton_by_label(args.figure)

# Preserve the figure's current X and Z so a posed character stays posed.
orig = figure.local_euler or (0.0, 0.0, 0.0)
rx, _, rz = orig

render.set_resolution(args.width, args.height)

step_deg = 360.0 / args.steps

try:
    for i in range(args.steps):
        ry = i * step_deg
        figure.set_local_rotation(rx, ry, rz)
        render.output_path = os.path.join(args.out, f"frame_{i:03d}.png")
        render.render()
        print(f"[{i+1}/{args.steps}] {ry:.1f}°")
finally:
    # Always restore the original rotation, even if the run is interrupted.
    figure.set_local_rotation(*orig)

print(f"\nDone. {args.steps} frames in {args.out}")
print (f"If you have ffmpeg installed and want to create an animation, copy and paste this command:\n")
print(f"ffmpeg -framerate 24 -i \"{os.path.join(args.out, 'frame_%03d.png')}\" turntable.mp4")
