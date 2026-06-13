"""DAZ Studio Script Server example: bake driven animation to explicit keyframes.

PURPOSE
-------
This script is a demonstration of what the DAZ Studio Script Server makes
possible.  It reads the evaluated state of a figure's bone rotations and morphs
across the play range and stamps an explicit keyframe on each channel at each
frame — a process known as *keyframe baking*.

It is an *example*, not a production baking pipeline.  A full tool would also
handle object-level properties (translation, scale), shape-key drivers, and
secondary dynamics.  The goal here is to show that the script server can convert
constraint-driven or IK-driven animation into a self-contained clip that no
longer depends on any of the original drivers.

WHAT IT DEMONSTRATES
--------------------
  - Reading all bone rotations in a single HTTP call (DazSkeleton.bone_rotations)
  - Reading active morph values in a single HTTP call (DazSkeleton.morph_values)
  - Baking bone rotations across a frame range (DazSkeleton.bake_bone_rotations)
  - Baking morph channels across a frame range (DazSkeleton.bake_morphs)
  - Baking both channels together in one HTTP call (DazSkeleton.bake)

WHEN TO USE BAKING
------------------
  - After posing a figure with IK so the result survives removing the IK rig
  - After running a physics simulation to freeze the result on the timeline
  - Before exporting to a format that doesn't support DAZ constraints (FBX, BVH)
  - After using DazAnimation.apply() to push a captured clip back to the timeline

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

4. Open a scene in DAZ Studio with an animated figure, then run:

       python docs/examples/animation/keyframe_baking.py --figure "Genesis 9"

Usage:
    python keyframe_baking.py --figure "Genesis 9"
    python keyframe_baking.py --figure "Genesis 9" --morphs
    python keyframe_baking.py --figure "Genesis 9" --start 10 --end 90 --morphs
    python keyframe_baking.py --figure "Genesis 9" --preview
"""

import argparse
import sys

from dazpy import DazScene

if __name__ == "__main__":
    # ── CLI ───────────────────────────────────────────────────────────────────────

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--figure",  default="Genesis 9", help="Figure label")
    parser.add_argument("--start",   type=int, default=None,
                        help="First frame to bake (default: play range start)")
    parser.add_argument("--end",     type=int, default=None,
                        help="Last frame to bake (default: play range end)")
    parser.add_argument("--morphs",  action="store_true", help="Also bake morph channels")
    parser.add_argument("--preview", action="store_true",
                        help="Print current bone/morph state without baking")
    args = parser.parse_args()

    # ── connect and find figure ───────────────────────────────────────────────────

    scene = DazScene()
    try:
        figure = scene.find_skeleton_by_label(args.figure)
    except Exception:
        sys.exit(f"Error: figure {args.figure!r} not found in scene.")

    play_range = scene.play_range()
    bake_start = args.start if args.start is not None else play_range["start"]
    bake_end   = args.end   if args.end   is not None else play_range["end"]

    print(f"Figure : {args.figure!r}")
    print(f"Range  : frames {bake_start}–{bake_end}  "
          f"(play range {play_range['start']}–{play_range['end']})")
    print()

    # ── preview current state (one call each) ─────────────────────────────────────

    # bone_rotations() fetches all bone Euler angles in a single HTTP call — no
    # per-bone round-trips.  morph_values(nonzero_only=True) returns only the
    # morphs that are actually active, keeping output compact for heavy figures.
    rotations = figure.bone_rotations()
    non_zero_bones = {n: r for n, r in rotations.items() if any(abs(v) > 0.001 for v in r)}

    active_morphs = figure.morph_values(nonzero_only=True)

    print(f"Active bones  : {len(non_zero_bones)} of {len(rotations)} have non-zero rotation")
    for name, (x, y, z) in sorted(non_zero_bones.items()):
        print(f"  {name:<20}  x={x:+.2f}  y={y:+.2f}  z={z:+.2f}")

    print(f"\nActive morphs : {len(active_morphs)}")
    for name, val in sorted(active_morphs.items()):
        print(f"  {name:<30}  {val:.4f}")

    if args.preview:
        print("\n--preview mode: nothing was baked.")
        sys.exit(0)

    # ── bake ──────────────────────────────────────────────────────────────────────

    print()
    n_frames = bake_end - bake_start + 1

    if args.morphs:
        # bake() combines bones and morphs in a single HTTP call — the timeline is
        # scrubbed once, writing insertKey() on every channel at every frame.
        print(f"Baking bones + morphs across {n_frames} frames (one HTTP call)…")
        result = figure.bake(
            start=bake_start,
            end=bake_end,
            include_morphs=True,
        )
        print(f"  {result['bones_baked']} bones × {result['frames_baked']} frames = "
              f"{result['bones_baked'] * 3 * result['frames_baked']} keyframes written")
        print(f"  {result['morphs_baked']} morphs × {result['frames_baked']} frames = "
              f"{result['morphs_baked'] * result['frames_baked']} keyframes written")
    else:
        # bake_bone_rotations() bakes only rotation channels — useful when morphs
        # are driven by expression controls that should stay as controllers.
        print(f"Baking bone rotations across {n_frames} frames (one HTTP call)…")
        result = figure.bake_bone_rotations(start=bake_start, end=bake_end)
        print(f"  {result['bones_baked']} bones × {result['frames_baked']} frames = "
              f"{result['bones_baked'] * 3 * result['frames_baked']} keyframes written")
        print("  (morphs not baked — add --morphs to include them)")

    print("\nDone.  The animation is now stored as explicit keyframes in DAZ Studio.")
    print("You can safely remove IK rigs or expression drivers without losing the motion.")
