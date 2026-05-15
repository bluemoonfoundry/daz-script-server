"""Render a 360° turntable of a figure.

Rotates the figure around its local Y axis in even steps and renders each
frame to a numbered PNG.  The figure's existing X and Z rotation are
preserved so a posed character stays posed throughout the spin.

Combine the output frames into a video with ffmpeg:
    ffmpeg -framerate 24 -i frame_%03d.png turntable.mp4

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
