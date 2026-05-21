"""DAZ Studio Script Server example: render multiple morph variations in a batch.

PURPOSE
-------
This script is a demonstration of what the DAZ Studio Script Server makes
possible.  It connects to a running DAZ Studio instance, dials two expression
morphs on a Genesis 9 figure to a series of pre-defined values, and renders
each combination to a numbered PNG — all driven entirely from Python with no
manual UI interaction.

It is an *example*, not a production render pipeline.  Real pipelines would
parameterise the morph list, use configurable output paths, and handle missing
morphs gracefully.  The goal here is to show that the script server lets you
drive morphs and the DAZ render engine from plain Python.

WHAT IT DEMONSTRATES
--------------------
  - Finding a skeleton in the live scene by label (DazScene.find_skeleton_by_label)
  - Locating named expression morphs on a figure (find_property_by_label)
  - Setting render resolution via DazRenderSettings
  - Looping over value combinations, setting morph values, and triggering renders

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

4. Open a scene in DAZ Studio containing a Genesis 9 figure, then run this
   script from the repo root or from the docs/examples directory:

       python docs/examples/batch_render_morph_variations.py

Usage:
    python batch_render_morph_variations.py
"""

import argparse

from dazpy import DazClient, DazScene, DazRenderSettings

VARIANTS = [
    # (Smile Full Face, SO Fear Worry)
    (0.0, 0.0),   # neutral
    (0.5, 0.3),   # mild smile with slight worry
    (1.0, 0.8),   # full smile with strong worry
]

OUT_DIR = "y:/tmp"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.parse_args()

    # ── connect ───────────────────────────────────────────────────────────────────

    print("Connecting to DAZ Studio…")
    scene  = DazScene()
    render = DazRenderSettings()
    figure = scene.find_skeleton_by_label("Genesis 9")
    print(f"  Found figure: {figure.label!r}")

    # ── locate morphs ─────────────────────────────────────────────────────────────

    smile = figure.find_property_by_label("Smile Full Face")
    brow  = figure.find_property_by_label("SO Fear Worry")

    if smile is None:
        raise SystemExit("Error: morph 'Smile Full Face' not found on figure.")
    if brow is None:
        raise SystemExit("Error: morph 'SO Fear Worry' not found on figure.")

    print(f"  Morphs located: 'Smile Full Face', 'SO Fear Worry'")

    # ── render setup ──────────────────────────────────────────────────────────────

    render.set_resolution(1920, 1080)
    print(f"  Render resolution: 1920 × 1080")
    print(f"  Output directory : {OUT_DIR}")
    print(f"\nRendering {len(VARIANTS)} variant(s)…\n")

    # ── render loop ───────────────────────────────────────────────────────────────

    for i, (s, b) in enumerate(VARIANTS):
        out_path = f"{OUT_DIR}/variant_{i:03d}.png"

        print(f"[{i+1}/{len(VARIANTS)}] Setting morphs:")
        print(f"  Smile Full Face = {s:.1f}")
        print(f"  SO Fear Worry   = {b:.1f}")

        smile.value = s
        brow.value  = b

        print(f"  Rendering → {out_path}")
        render.output_path = out_path
        render.render()
        print(f"  Done.\n")

    print(f"All {len(VARIANTS)} variants written to {OUT_DIR}/")
    for i in range(len(VARIANTS)):
        print(f"  {OUT_DIR}/variant_{i:03d}.png")
