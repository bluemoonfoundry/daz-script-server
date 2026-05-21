"""DAZ Studio Script Server example: clip, blend, and assemble animation clips.

PURPOSE
-------
This script is a demonstration of what the DAZ Studio Script Server makes
possible.  It treats captured animation files (produced by animation_frame_dump.py)
as editable clips — extracting sub-ranges, crossfading between two takes,
concatenating sequences end-to-end, and scrubbing to individual frames to apply
them as live poses.

It is an *example*, not a non-linear editor.  A production tool would handle
spline retiming, root-motion extraction, and multi-layer blending.  The goal
here is to show that Python can edit animation data entirely offline — all of the
clip operations run without any HTTP calls — and that the result can be pushed
back to a live DAZ Studio figure in a single call when needed.

WHAT IT DEMONSTRATES
--------------------
  - Extracting a sub-range of frames (DazAnimation.clip)
  - Crossfading between two clips frame-by-frame (DazAnimation.blend)
  - Concatenating two clips end-to-end (DazAnimation.append)
  - Extracting a single frame as a DazPose (DazAnimation.as_pose)
  - Applying a single frame directly to a live figure (DazAnimation.apply)
  - Natural Python indexing: len(anim) and anim[i]

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

4. Produce animation files with animation_frame_dump.py, then run:

       python docs/examples/animation_mixing.py clip   --anim walk.json --start 10 --end 40 --out walk_loop.json
       python docs/examples/animation_mixing.py blend  --a walk.json --b run.json --t 0.5 --out trot.json
       python docs/examples/animation_mixing.py append --a intro.json --b main.json --out full.json
       python docs/examples/animation_mixing.py apply  --anim walk.json --frame 0 --figure "Genesis 9"

Usage:
    python animation_mixing.py clip   --anim <file> --start <frame> --end <frame> --out <file>
    python animation_mixing.py blend  --a <file> --b <file> --t <0-1> --out <file>
    python animation_mixing.py append --a <file> --b <file> --out <file>
    python animation_mixing.py apply  --anim <file> --frame <index> [--figure <label>]
"""

import argparse
import sys

from dazpy import DazAnimation, DazScene

if __name__ == "__main__":
    # ── CLI ───────────────────────────────────────────────────────────────────────

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    clip_p = sub.add_parser("clip", help="Extract a frame sub-range")
    clip_p.add_argument("--anim",  required=True, help="Source animation JSON")
    clip_p.add_argument("--start", type=int, required=True,
                        help="First scene frame (inclusive)")
    clip_p.add_argument("--end",   type=int, required=True,
                        help="Last scene frame (inclusive)")
    clip_p.add_argument("--out",   required=True, help="Output JSON path")

    blend_p = sub.add_parser("blend", help="Crossfade between two clips")
    blend_p.add_argument("--a",   required=True, help="Clip A (t=0) JSON")
    blend_p.add_argument("--b",   required=True, help="Clip B (t=1) JSON")
    blend_p.add_argument("--t",   type=float, default=0.5, help="Blend weight 0.0–1.0")
    blend_p.add_argument("--out", required=True, help="Output JSON path")

    append_p = sub.add_parser("append", help="Concatenate two clips end-to-end")
    append_p.add_argument("--a",   required=True, help="First clip JSON")
    append_p.add_argument("--b",   required=True, help="Second clip JSON (appended after A)")
    append_p.add_argument("--out", required=True, help="Output JSON path")

    apply_p = sub.add_parser("apply", help="Apply one frame to a live figure")
    apply_p.add_argument("--anim",   required=True,       help="Animation JSON")
    apply_p.add_argument("--frame",  type=int, default=0,
                         help="Python index into the clip (0 = first frame)")
    apply_p.add_argument("--figure", default=None,
                         help="Figure label (default: taken from animation file)")

    args = parser.parse_args()

    # ── clip ──────────────────────────────────────────────────────────────────────

    if args.cmd == "clip":
        anim = DazAnimation.load(args.anim)
        print(f"Loaded  : {anim!r}")

        # clip() filters by scene frame number (the 'frame' key stored in each
        # entry), not by Python list index.  Both endpoints are inclusive.
        clipped = anim.clip(args.start, args.end)
        clipped.save(args.out)

        print(f"Clipped : frames {args.start}–{args.end}  "
              f"({len(clipped)} of {len(anim)} frames kept)")
        print(f"Saved   : {args.out}")

    # ── blend ─────────────────────────────────────────────────────────────────────

    elif args.cmd == "blend":
        anim_a = DazAnimation.load(args.a)
        anim_b = DazAnimation.load(args.b)
        print(f"Clip A  : {anim_a!r}")
        print(f"Clip B  : {anim_b!r}")

        if anim_a.bones != anim_b.bones:
            sys.exit(f"Error: clips have different bone lists "
                     f"({len(anim_a.bones)} vs {len(anim_b.bones)} bones).  "
                     f"Both must be captured from the same skeleton.")

        # blend() lerps every rotation component and every morph value frame by
        # frame.  t=0.0 produces a copy of A; t=1.0 produces a copy of B.
        # If the clips have different lengths, the result is truncated to the shorter one.
        blended = anim_a.blend(anim_b, args.t)
        blended.save(args.out)

        print(f"Blended : t={args.t:.2f}  →  {len(blended)} frames")
        print(f"Saved   : {args.out}")

    # ── append ────────────────────────────────────────────────────────────────────

    elif args.cmd == "append":
        anim_a = DazAnimation.load(args.a)
        anim_b = DazAnimation.load(args.b)
        print(f"Clip A  : {anim_a!r}")
        print(f"Clip B  : {anim_b!r}")

        if anim_a.bones != anim_b.bones:
            sys.exit(f"Error: clips have different bone lists — both must be from the same skeleton.")

        # append() renumbers clip B's frames so they start immediately after A's
        # last frame, then returns a new clip containing all frames from both.
        combined = anim_a.append(anim_b)
        combined.save(args.out)

        fr = combined.frame_range
        print(f"Combined: {len(combined)} frames  "
              f"(range {fr['start']}–{fr['end']})")
        print(f"Saved   : {args.out}")

    # ── apply ─────────────────────────────────────────────────────────────────────

    elif args.cmd == "apply":
        anim = DazAnimation.load(args.anim)
        figure_label = args.figure or anim.figure
        if not figure_label:
            sys.exit("Error: cannot determine figure label — use --figure.")

        # Python indexing: len(anim) is the frame count; anim[i] is the frame dict.
        if not (-len(anim) <= args.frame < len(anim)):
            sys.exit(f"Error: --frame {args.frame} is out of range "
                     f"(clip has {len(anim)} frames, indices 0–{len(anim)-1}).")

        frame_data = anim[args.frame]
        print(f"Loaded  : {anim!r}")
        print(f"Applying: Python index {args.frame}  "
              f"(scene frame {frame_data['frame']})  →  {figure_label!r}")

        scene = DazScene()
        try:
            figure = scene.find_skeleton_by_label(figure_label)
        except Exception:
            sys.exit(f"Error: figure {figure_label!r} not found in scene.")

        # as_pose() extracts the frame as a DazPose (sparse — zero bones omitted).
        # apply() then sends one HTTP call setting only channels present in the pose.
        # Equivalent to: anim.apply(figure, frame_index=args.frame)
        pose = anim.as_pose(args.frame)
        pose.apply(figure)

        print(f"  Set {len(pose.bones)} bone rotations, "
              f"{len(pose.morphs)} morph values → {figure_label!r}")
        print("Done.")
