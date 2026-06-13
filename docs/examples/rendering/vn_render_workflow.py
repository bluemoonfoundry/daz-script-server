"""DAZ Studio Script Server example: VN (visual novel) render workflows.

PURPOSE
-------
Visual novel pipelines generate many renders of the same characters in different
expressions, costumes, or compositions.  This example demonstrates four patterns
that cover the common VN production cases:

  Pattern 0 — Basic single render
  Pattern A — Batch morph variants (submit all upfront, progress callback)
  Pattern B — Interleaved scene setup (complex changes between renders)
  Pattern C — Multi-figure scene (two characters, different expressions)

Each pattern is a standalone function.  Run with --pattern 0|A|B|C to execute
just that one, or omit --pattern to run all four in sequence.

CHOOSING A PATTERN
------------------
  Pattern A: Only morphs differ between renders, no lighting/prop changes.
             Use `render_variants()` — one batch POST, parallel queue execution.

  Pattern B: Lighting, backdrops, prop visibility, or material properties differ.
             Use a manual loop with `client.execute()` for scene setup between
             `render()` calls.  The render queue is sequential, so setup scripts
             submitted while one render is running will automatically execute
             after it completes and before the next render starts.

  Pattern C: Multiple figures in the scene each need different morph values.
             Use `FigureMorphs` inside a `RenderVariant` (or directly in
             `render()`).

TRANSPARENT BACKGROUNDS
-----------------------
The render API does not manipulate backdrop nodes — transparency is a scene-level
setting.  To produce renders with transparent backgrounds, use
`client.execute()` to disable the environment/backdrop before calling `render()`,
then re-enable it afterward:

    client.execute(\"\"\"
        var env = Scene.findNode("Environment");
        if (env) env.setVisible(false);
    \"\"\")
    result = render(client, out_path, ...)
    client.execute(\"\"\"
        var env = Scene.findNode("Environment");
        if (env) env.setVisible(true);
    \"\"\")

Alternatively, set the render output format to PNG and configure the iRay
backdrop to "Scene Only" (no environment sphere) via DazScript before
submitting each render.

ENVIRONMENT SETUP
-----------------
1. DAZ Studio must be running with the DazScriptServer plugin loaded and its
   HTTP server active (default: 127.0.0.1:18811).  Verify:

       curl http://127.0.0.1:18811/health

2. Install the Python dependencies:

       python -m venv .venv
       .venv\\Scripts\\activate          # Windows
       # source .venv/bin/activate     # macOS / Linux
       pip install requests

3. Install the dazpy SDK (from the repo root):

       pip install -e .

4. Open a scene in DAZ Studio with a Genesis 9 figure labelled "Genesis 9"
   (Patterns A, B, C also work with other figure labels — edit OUT_DIR and
   FIGURE at the top of the file).

       python docs/examples/rendering/vn_render_workflow.py
       python docs/examples/rendering/vn_render_workflow.py --pattern A

Usage:
    python vn_render_workflow.py [--pattern {0,A,B,C}] [--out DIR]
    [--figure LABEL] [--figure2 LABEL] [--width PX] [--height PX]
"""

from __future__ import annotations

import argparse
import os

import dazpy
from dazpy import DazClient
from dazpy._render_api import (
    FigureMorphs,
    RenderBase,
    RenderResult,
    RenderVariant,
    render,
    render_variants,
)

# ── Defaults (edit these for your scene) ─────────────────────────────────────

OUT_DIR  = "y:/tmp/vn"
FIGURE   = "Genesis 9"
FIGURE2  = "Genesis 9.1"   # used in Pattern C — must exist in scene
WIDTH    = 1920
HEIGHT   = 1080


# ── Pattern 0: Basic single render ───────────────────────────────────────────


def pattern_basic(client: DazClient, out_dir: str, figure: str, w: int, h: int) -> None:
    """Render the current scene once and print the result."""
    print("\n── Pattern 0: Basic single render ──")

    out_path = os.path.join(out_dir, "basic.png")
    result = render(client, out_path, width=w, height=h)

    _print_result(result)


# ── Pattern A: Batch morph variants ──────────────────────────────────────────


def pattern_a_batch_variants(
    client: DazClient, out_dir: str, figure: str, w: int, h: int
) -> None:
    """Render multiple morph combinations via /render/batch.

    This is the most efficient pattern when only morphs differ between renders:
    a single POST submits all variants, and the server executes them in order.
    Use `on_progress` to display a live completion counter.
    """
    print("\n── Pattern A: Batch morph variants ──")

    # Each variant specifies its own output path and morph values.
    # Morphs are applied server-side at render time; the live DAZ scene is
    # not modified.
    variants = [
        RenderVariant(
            output_path=os.path.join(out_dir, "A_neutral.png"),
            figure=figure,
        ),
        RenderVariant(
            output_path=os.path.join(out_dir, "A_smile.png"),
            figure=figure,
            morphs={"Smile Full Face": 1.0},
        ),
        RenderVariant(
            output_path=os.path.join(out_dir, "A_sad.png"),
            figure=figure,
            morphs={"Mouth Frown": 0.8, "Brow Inner Up": 0.6},
        ),
        RenderVariant(
            output_path=os.path.join(out_dir, "A_surprised.png"),
            figure=figure,
            morphs={"Eyes Wide": 0.9, "Mouth Open": 0.5, "Brow Inner Up": 0.8},
        ),
    ]

    # Shared base: resolution and engine apply to every variant.
    base = RenderBase(width=w, height=h, engine="iray")

    def on_progress(done: int, total: int) -> None:
        print(f"  [{done}/{total}] render complete")

    results = render_variants(client, variants, base, on_progress=on_progress, timeout=600)

    for i, result in enumerate(results):
        _print_result(result, label=f"variant {i}")


# ── Pattern B: Interleaved scene setup ───────────────────────────────────────


def pattern_b_interleaved(
    client: DazClient, out_dir: str, figure: str, w: int, h: int
) -> None:
    """Render variants that require scene changes between frames.

    Use this pattern when variants differ in ways the render payload cannot
    express — lighting intensity, prop visibility, backdrop colour, material
    properties, environment settings, etc.

    HOW IT WORKS
    ------------
    The render queue is sequential: render N+1 only starts after render N
    completes.  When a render is executing on the main thread, any
    `client.execute()` calls you make from Python are queued up and will
    run *after* the current render finishes and *before* the next render
    starts.

    This means you can safely interleave scene-setup scripts with render
    submissions without race conditions:

        [Python]               [DAZ Studio main thread]
        execute(setup_A)  -->  apply setup A
        submit render A   -->  (queued)
                               run render A script → doRender()
        execute(setup_B)  -->  (queued — blocked until render A completes)
                               apply setup B        ← runs after render A
        submit render B   -->  (queued)
                               run render B script → doRender()

    CAUTION: render_variants() does NOT interleave — it submits all variants
    upfront before any scene changes.  Pattern B requires a manual loop.
    """
    print("\n── Pattern B: Interleaved scene setup ──")

    # Define lighting states as DazScript snippets.
    # In a real pipeline these would also configure backdrops, prop
    # visibility, camera angles, etc.
    lighting_scenes = [
        ("B_day.png",    "// bright fill",   "setFillLightIntensity(1.0)"),
        ("B_dusk.png",   "// warm low fill", "setFillLightIntensity(0.3)"),
        ("B_night.png",  "// near dark",     "setFillLightIntensity(0.05)"),
    ]

    for filename, label, light_script in lighting_scenes:
        out_path = os.path.join(out_dir, filename)

        # 1. Apply scene setup for this render.
        #    If a render is currently executing, this call blocks until it
        #    completes — the setup script then runs immediately before the
        #    next render starts.
        _apply_lighting(client, light_script)

        # 2. Submit the render and wait for it to complete.
        #    Morphs and the output path come from the Python loop; the scene
        #    state (lighting, backdrop, etc.) comes from step 1 above.
        print(f"  Rendering {label} → {filename}")
        result = render(
            client, out_path,
            figure=figure,
            morphs={"Smile Full Face": 0.3},
            width=w, height=h,
            engine="iray",
            timeout=300,
        )
        _print_result(result, label=filename)


def _apply_lighting(client: DazClient, snippet: str) -> None:
    """Stub: apply a lighting configuration via DazScript.

    Replace the body with real DazScript that targets your scene's lights.
    The helper function names used here (`setFillLightIntensity`) are
    illustrative — use `Scene.findNodeByLabel("Fill Light")` and set the
    actual property on the DzDistantLight / DzSpotLight object.
    """
    # Example DazScript for a real scene:
    #
    #   var fill = Scene.findNodeByLabel("Fill Light");
    #   if (fill) {
    #       var intensityProp = fill.findPropertyByLabel("Intensity");
    #       if (intensityProp) intensityProp.setValue(0.3);
    #   }
    #
    # For this demonstration we just print the snippet instead.
    print(f"    scene setup: {snippet}")
    # Uncomment when targeting a real scene:
    # client.execute(f"""
    #     var fill = Scene.findNodeByLabel("Fill Light");
    #     if (fill) {{
    #         var p = fill.findPropertyByLabel("Intensity");
    #         if (p) p.setValue(0.3);
    #     }}
    # """)


# ── Pattern C: Multi-figure scene ────────────────────────────────────────────


def pattern_c_multi_figure(
    client: DazClient, out_dir: str, figure: str, figure2: str, w: int, h: int
) -> None:
    """Render a two-character scene with different expressions per character.

    `render_variants()` and `render()` accept a `figures` list of
    `FigureMorphs` objects so both characters can be configured in one render
    submission — no extra scene changes required.
    """
    print("\n── Pattern C: Multi-figure scene ──")

    # Four shots covering common VN dialogue expressions.
    variants = [
        RenderVariant(
            output_path=os.path.join(out_dir, "C_both_neutral.png"),
            figures=[
                FigureMorphs(name=figure,  morphs={}),
                FigureMorphs(name=figure2, morphs={}),
            ],
        ),
        RenderVariant(
            output_path=os.path.join(out_dir, "C_a_happy_b_neutral.png"),
            figures=[
                FigureMorphs(name=figure,  morphs={"Smile Full Face": 1.0}),
                FigureMorphs(name=figure2, morphs={}),
            ],
        ),
        RenderVariant(
            output_path=os.path.join(out_dir, "C_a_neutral_b_angry.png"),
            figures=[
                FigureMorphs(name=figure,  morphs={}),
                FigureMorphs(name=figure2, morphs={"Anger": 0.8, "Brow Lower": 0.6}),
            ],
        ),
        RenderVariant(
            output_path=os.path.join(out_dir, "C_both_surprised.png"),
            figures=[
                FigureMorphs(name=figure,  morphs={"Eyes Wide": 0.9, "Mouth Open": 0.4}),
                FigureMorphs(name=figure2, morphs={"Eyes Wide": 0.7, "Mouth Open": 0.6}),
            ],
        ),
    ]

    base = RenderBase(width=w, height=h, engine="iray")

    def on_progress(done: int, total: int) -> None:
        print(f"  [{done}/{total}] render complete")

    results = render_variants(client, variants, base, on_progress=on_progress, timeout=600)

    for i, result in enumerate(results):
        _print_result(result, label=f"variant {i}")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _print_result(result: RenderResult, label: str = "") -> None:
    tag = f" ({label})" if label else ""
    if result.success:
        size_kb = result.file_size_bytes / 1024 if result.file_size_bytes > 0 else 0
        print(f"  OK{tag}: {result.output_path}  {size_kb:.0f} KB  {result.duration_ms} ms")
    else:
        print(f"  FAIL{tag}: {result.error}")


# ── Entry point ───────────────────────────────────────────────────────────────


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--pattern", choices=["0", "A", "B", "C"],
        help="Run only this pattern (default: run all)"
    )
    parser.add_argument("--out",     default=OUT_DIR,   help="Output directory")
    parser.add_argument("--figure",  default=FIGURE,    help="Primary figure label")
    parser.add_argument("--figure2", default=FIGURE2,   help="Second figure label (Pattern C)")
    parser.add_argument("--width",   type=int, default=WIDTH,  help="Render width in pixels")
    parser.add_argument("--height",  type=int, default=HEIGHT, help="Render height in pixels")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    client = DazClient()
    print(f"Connected to DAZ Studio at {client._base}")
    print(f"Output directory: {args.out}")

    run_all = args.pattern is None
    p = args.pattern

    if run_all or p == "0":
        pattern_basic(client, args.out, args.figure, args.width, args.height)
    if run_all or p == "A":
        pattern_a_batch_variants(client, args.out, args.figure, args.width, args.height)
    if run_all or p == "B":
        pattern_b_interleaved(client, args.out, args.figure, args.width, args.height)
    if run_all or p == "C":
        pattern_c_multi_figure(client, args.out, args.figure, args.figure2, args.width, args.height)

    print("\nDone.")
