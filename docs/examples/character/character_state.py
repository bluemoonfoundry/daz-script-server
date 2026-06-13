"""DAZ Studio Script Server example: save and restore a character's complete state.

PURPOSE
-------
This script is a demonstration of what the DAZ Studio Script Server makes
possible.  It serialises a live DAZ Studio figure's full state — shape morphs,
expression/pose node properties, and bone rotations — to a compact JSON file,
then restores that state on demand.

It is an *example*, not a full scene-preset system.  A production tool would
handle animation timelines, material states, and nested figure hierarchies.
The goal here is to show that the script server exposes enough of the DAZ
figure model for Python to capture and replay character state without any
plugin-side storage.

WHAT IT DOES
------------
  - Reads all non-default DzMorph values from the figure's geometry object
  - Reads all non-default numeric node-level properties (FACS dials, etc.)
  - Reads all non-default bone XYZ rotations
  - Stores only non-zero values so the JSON stays small for morph-heavy figures
  - Restores morph, property, and bone values in a single HTTP call

SIMPLIFICATION NOTE
-------------------
An earlier version of this script implemented save_state() and restore_state()
by building raw DazScript strings in Python — one long script that looped over
modifier lists, a second that looped over bones, and inline findModifier() /
findBone() calls per channel for the restore path.  That approach required the
caller to know DazScript internals and was hard to reuse across examples.

Both operations are now handled by DazPose, which encapsulates the same scripts
internally:
    DazPose.capture(skeleton)  →  was: save_state() building two DazScript calls
    pose.apply(skeleton)       →  was: restore_state() building per-channel JS

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

       python docs/examples/character/character_state.py save --figure "Genesis 9" --out state.json

Usage:
    python character_state.py save    --figure "Genesis 9" --out state.json
    python character_state.py restore --figure "Genesis 9" --file state.json
"""

import argparse
import sys

from dazpy import DazPose, DazScene

if __name__ == "__main__":
    # ── CLI ───────────────────────────────────────────────────────────────────────

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    save_p = sub.add_parser("save")
    save_p.add_argument("--figure", default="Genesis 9")
    save_p.add_argument("--out",    default="state.json")

    restore_p = sub.add_parser("restore")
    restore_p.add_argument("--figure", default=None, help="Override figure label from file")
    restore_p.add_argument("--file",   required=True)

    args = parser.parse_args()
    scene = DazScene()

    if args.cmd == "save":
        try:
            figure = scene.find_skeleton_by_label(args.figure)
        except Exception:
            sys.exit(f"Error: figure {args.figure!r} not found in scene.")

        pose = DazPose.capture(figure)
        pose.save(args.out)
        print(f"Saved {len(pose.morphs)} morphs, {len(pose.props)} properties, "
              f"{len(pose.bones)} bones → {args.out}")

    elif args.cmd == "restore":
        pose = DazPose.load(args.file)
        if args.figure:
            pose.figure = args.figure

        try:
            figure = scene.find_skeleton_by_label(pose.figure)
        except Exception:
            sys.exit(f"Error: figure {pose.figure!r} not found in scene.")

        # apply() sets only the channels stored in the pose, leaving others
        # unchanged.  Use pose.apply_full(figure) instead to also zero every
        # bone and morph not present in the file (a complete clean reset).
        pose.apply(figure)
        print(f"Restored {len(pose.morphs)} morphs, {len(pose.props)} properties, "
              f"{len(pose.bones)} bones → {pose.figure!r}")
