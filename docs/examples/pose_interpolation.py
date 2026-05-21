"""DAZ Studio Script Server example: interpolate between two saved character states and render each step.

PURPOSE
-------
This script is a demonstration of what the DAZ Studio Script Server makes
possible.  It loads two character state files produced by character_state.py,
interpolates all bone rotations, morph values, and FACS node properties across
N steps using a configurable easing curve, and renders each step to a numbered
PNG.

It is an *example*, not a production animation tool.  A full system would
handle multiple keyframes, spline interpolation, and timeline baking.  The
goal here is to show that Python can own the animation math entirely — easing,
lerp, step count — while DAZ Studio simply receives and applies the result at
each frame, with no knowledge of the interpolation loop happening outside it.

WHAT IT DEMONSTRATES
--------------------
  - Loading two character state JSON files (produced by character_state.py)
  - Interpolating bone rotations, shape morphs, and node properties with lerp
  - Applying several configurable easing curves (linear, ease_in_out, bounce, etc.)
  - Pushing the full interpolated state to DAZ Studio in a single HTTP call per step
  - Rendering each interpolated frame and restoring state A on exit
  - Printing an ffmpeg command to assemble the frames into a video

SIMPLIFICATION NOTE
-------------------
An earlier version of this script implemented the interpolation loop by hand:
a lerp() scalar helper, a lerp_state() function that manually merged two raw
JSON dicts (iterating bone/morph/prop keys and computing weighted averages), and
an apply_state() function that built a DazScript string at runtime — one inline
findBone() / findModifier() call per channel, joined with string concatenation,
then sent as a single HTTP payload.

That approach mixed interpolation math with script-generation concerns and
duplicated logic already present in character_state.py.

The three helpers are now replaced by two DazPose methods:
    pose_a.lerp(pose_b, t)   →  was: lerp() + lerp_state() operating on raw dicts
    blended.apply(figure)    →  was: apply_state() building per-channel DazScript

The apply() call still sends exactly one HTTP request per rendered frame; the
script it generates inside DazPose injects bone/morph data as a JSON object and
loops server-side, which is both cleaner and immune to script-length blowup on
figures with many active morphs.

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

4. Produce two state files with character_state.py, then run:

       python docs/examples/pose_interpolation.py --a neutral.json --b smile.json --steps 10

Usage:
    python pose_interpolation.py --a neutral.json --b smile.json --steps 10
    python pose_interpolation.py --a neutral.json --b smile.json \\
        --steps 30 --ease ease_in_out --out C:/interpolation --width 1920 --height 1080
"""

import argparse
import os
import sys

from dazpy import DazPose, DazRenderSettings, DazScene

# ── easing functions ───────────────────────────────────────────────────────────
# All take t in [0, 1] and return a value in [0, 1].

EASING = {
    "linear":            lambda t: t,
    "ease_in":           lambda t: t ** 2,
    "ease_out":          lambda t: 1 - (1 - t) ** 2,
    "ease_in_out":       lambda t: 3*t**2 - 2*t**3,
    "ease_in_cubic":     lambda t: t ** 3,
    "ease_out_cubic":    lambda t: 1 - (1 - t) ** 3,
    "ease_in_out_cubic": lambda t: 4*t**3 if t < 0.5 else 1 - (-2*t + 2)**3 / 2,
    "bounce_out": lambda t: (
        7.5625*t*t if t < 1/2.75 else
        7.5625*(t - 1.5/2.75)**2 + 0.75 if t < 2/2.75 else
        7.5625*(t - 2.25/2.75)**2 + 0.9375 if t < 2.5/2.75 else
        7.5625*(t - 2.625/2.75)**2 + 0.984375
    ),
}

if __name__ == "__main__":
    # ── CLI ────────────────────────────────────────────────────────────────────────

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--a",     required=True, help="State A JSON file (start pose)")
    parser.add_argument("--b",     required=True, help="State B JSON file (end pose)")
    parser.add_argument("--steps", type=int, default=10,
                        help="Number of frames to render (includes A and B)")
    parser.add_argument("--ease",  default="ease_in_out", choices=sorted(EASING),
                        help="Easing function (default: ease_in_out)")
    parser.add_argument("--out",   default="y:/tmp/interpolation")
    parser.add_argument("--width",  type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--figure", default=None,
                        help="Override figure label (default: taken from state A file)")
    args = parser.parse_args()

    if args.steps < 2:
        raise SystemExit("--steps must be at least 2 (start and end).")

    pose_a = DazPose.load(args.a)
    pose_b = DazPose.load(args.b)

    figure_label = args.figure or pose_a.figure
    if not figure_label:
        raise SystemExit("Could not determine figure label — use --figure.")

    scene = DazScene()
    try:
        figure = scene.find_skeleton_by_label(figure_label)
    except Exception:
        sys.exit(f"Error: figure {figure_label!r} not found in scene.")

    os.makedirs(args.out, exist_ok=True)

    render = DazRenderSettings(scene._client)
    render.set_resolution(args.width, args.height)

    ease_fn = EASING[args.ease]

    print(f"Interpolating {args.steps} steps ({args.ease}) → {args.out}")
    print(f"  A: {args.a}  ({len(pose_a.bones)} bones, "
          f"{len(pose_a.morphs)} morphs, {len(pose_a.props)} props)")
    print(f"  B: {args.b}  ({len(pose_b.bones)} bones, "
          f"{len(pose_b.morphs)} morphs, {len(pose_b.props)} props)\n")

    try:
        for i in range(args.steps):
            t_linear = i / (args.steps - 1)
            t_eased  = ease_fn(t_linear)

            pose_a.lerp(pose_b, t_eased).apply(figure)

            out_path = os.path.join(args.out, f"frame_{i:03d}.png")
            render.output_path = out_path
            render.render()
            print(f"  [{i+1}/{args.steps}] t={t_linear:.3f} → eased={t_eased:.3f}  {out_path}")

    finally:
        # Restore state A so DAZ Studio is left at the starting pose.
        pose_a.apply(figure)
        print("\nRestored state A.")

    print(f"\nDone. {args.steps} frames in {args.out}")
    print(f"If you have ffmpeg installed and want to create an animation, copy and paste this command:\n")
    print(f"ffmpeg -framerate 24 -i \"{os.path.join(args.out, 'frame_%03d.png')}\" interpolation.mp4")
