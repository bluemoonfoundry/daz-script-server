"""DAZ Studio Script Server example: dump bone rotations and morph values for every animation frame.

PURPOSE
-------
This script is a demonstration of what the DAZ Studio Script Server makes
possible.  It captures the full animation of a DAZ Studio figure — every bone
rotation and optionally every animated morph — across all frames in the play
range, and writes the result to a structured JSON file.

It is an *example*, not a production motion-capture export tool.  A real
exporter would handle multiple figures, finger bones, object-level channels,
and binary output formats.  The goal here is to show that the script server
can scrub a DAZ timeline from Python, collecting per-frame data at the speed
of a single HTTP call.

WHAT IT DEMONSTRATES
--------------------
  - Scrubbing through every frame using Scene.setFrame() inside a single
    DazScript call (no Python round-trip per frame)
  - Building a compact parallel-list encoding: a bone-name index plus
    per-frame rotation arrays, keeping payload size proportional to bones
    rather than bones × frames
  - Optionally detecting and capturing only the morphs whose values actually
    vary across the timeline (not just any keyed channel)
  - Restoring the original timeline frame after the dump

SIMPLIFICATION NOTE
-------------------
An earlier version of this script built two separate raw DazScript strings in
Python and sent them as two HTTP calls:

  Step 1 (morph probe, optional): a DazScript f-string that looped over all
  modifiers and node properties, defined an isVaryingMorph() helper inline, and
  returned a [[type, name], ...] list to Python.  Python then serialised that
  list back to JSON to inject it into the second script.

  Step 2 (frame scrub): a second DazScript f-string that re-defined the same
  isVaryingMorph() helper, re-found the skeleton by label, resolved the
  injected morph names back to live channel objects, then looped over every
  frame calling Scene.setFrame() and collecting rotations and morph values.
  Restoring the original frame was a third call made from Python after the
  script returned.

Both scripts are now encapsulated in DazAnimation.capture(), which combines
them into a single HTTP call:
  - Morph detection is inlined at the top of the frame-scrub script behind a
    JS `if (true/false)` guard, eliminating the Python round-trip that passed
    names between the two scripts.
  - Scene.setFrame(_origFrame) is called at the end of the script itself, so
    frame restore is guaranteed even if the Python caller never reaches that
    line.

Output format:
    {
      "figure": "Genesis 9",
      "frame_range": {"start": 0, "end": 90},
      "bones": ["hip", "rForeArm", ...],
      "frames": [
        {"frame": 0, "rotations": [[x,y,z], ...], "morphs": {"PHMSmile": 0.5}},
        ...
      ]
    }

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

4. Open a scene in DAZ Studio with an animated Genesis 9 figure, then run:

       python docs/examples/animation_frame_dump.py --figure "Genesis 9" --out anim.json

Usage:
    python animation_frame_dump.py --figure "Genesis 9" --out anim.json
    python animation_frame_dump.py --figure "Genesis 9" --out anim.json --morphs
"""

import argparse
import sys

from dazpy import DazAnimation, DazScene

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--figure", default="Genesis 9")
    parser.add_argument("--out",    default="anim.json")
    parser.add_argument("--morphs", action="store_true",
                        help="Also capture non-zero morph values per frame")
    args = parser.parse_args()

    scene = DazScene()
    try:
        figure = scene.find_skeleton_by_label(args.figure)
    except Exception:
        sys.exit(f"Error: figure {args.figure!r} not found in scene.")

    play_range = scene.play_range()
    print(f"Capturing frames {play_range['start']}–{play_range['end']} for {args.figure!r}...")

    anim = DazAnimation.capture(figure, include_morphs=args.morphs)
    anim.save(args.out)

    print(f"Wrote {anim.frame_count} frames × {anim.bone_count} bones → {args.out}")
    if args.morphs:
        animated_morphs = {k for fr in anim.frames for k in fr["morphs"]}
        print(f"Captured {len(animated_morphs)} animated morph(s)")
