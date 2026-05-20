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
import json
import sys

from dazpy import DazClient, DazScene

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--figure", default="Genesis 9")
parser.add_argument("--out",    default="anim.json")
parser.add_argument("--morphs", action="store_true", help="Also capture non-zero morph values per frame")
args = parser.parse_args()

client = DazClient()
scene  = DazScene(client)

play_range    = scene.play_range()
original_frame = scene.frame()

figure_label = json.dumps(args.figure)

# ── step 1: collect animated morph names (fast, no frame scrubbing) ───────────
animated_morph_names = []
if args.morphs:
    probe = client.execute(f"""(function(){{
        var skel = null, skels = Scene.getSkeletonList();
        for (var i = 0; i < skels.length; i++) {{
            if (skels[i].getLabel() === {figure_label}) {{ skel = skels[i]; break; }}
        }}
        if (!skel) return null;
        function isVaryingMorph(ch) {{
            var n = ch.getNumKeys();
            if (n < 2) return false;
            var first = ch.getKeyValue(0);
            for (var k = 1; k < n; k++) {{
                if (Math.abs(ch.getKeyValue(k) - first) > 0.0001) return true;
            }}
            return false;
        }}
        var names = [], obj = skel.getObject();
        if (obj) {{
            for (var i = 0; i < obj.getNumModifiers(); i++) {{
                var m = obj.getModifier(i);
                if (m.className() === "DzMorph" && isVaryingMorph(m.getValueChannel()))
                    names.push(["morph", m.getName()]);
            }}
        }}
        for (var i = 0; i < skel.getNumProperties(); i++) {{
            var p = skel.getProperty(i);
            if (p && p.getNumKeys && isVaryingMorph(p))
                names.push(["prop", p.getName()]);
        }}
        return names;
    }})()""").value
    if probe is None:
        sys.exit(f"Error: figure {args.figure!r} not found in scene.")
    animated_morph_names = probe
    print(f"Found {len(animated_morph_names)} animated morph(s): {animated_morph_names}")

# ── step 2: scrub frames ───────────────────────────────────────────────────────
morph_names_js = json.dumps(animated_morph_names)

script = f"""(function(){{
    var label       = {figure_label};
    var morphNames  = {morph_names_js};

    // Find skeleton by label
    var skel = null;
    var skels = Scene.getSkeletonList();
    for (var i = 0; i < skels.length; i++) {{
        if (skels[i].getLabel() === label) {{ skel = skels[i]; break; }}
    }}
    if (!skel) return null;

    // Build ordered bone list once
    var allBones = skel.getAllBones();
    var boneNames = [];
    for (var i = 0; i < allBones.length; i++) boneNames.push(allBones[i].getName());

    // Returns true only if the morph's key values actually vary (not just keyed-but-static).
    function isVaryingMorph(ch) {{
        var n = ch.getNumKeys();
        if (n < 2) return false;
        var first = ch.getKeyValue(0);
        for (var k = 1; k < n; k++) {{
            if (Math.abs(ch.getKeyValue(k) - first) > 0.0001) return true;
        }}
        return false;
    }}

    // Resolve animated channels once — each entry is [name, channel].
    // morphNames entries are [type, name] where type is "morph" or "prop".
    var animatedChannels = [];
    if (morphNames.length > 0) {{
        var obj = skel.getObject();
        for (var i = 0; i < morphNames.length; i++) {{
            var type = morphNames[i][0], name = morphNames[i][1];
            if (type === "morph" && obj) {{
                var m = obj.findModifier(name);
                if (m) animatedChannels.push([name, m.getValueChannel()]);
            }} else if (type === "prop") {{
                var p = skel.findProperty(name);
                if (p) animatedChannels.push([name, p]);
            }}
        }}
    }}

    var step  = Scene.getTimeStep();
    var range = Scene.getPlayRange();
    var start = Math.round(range.start / step);
    var end   = Math.round(range.end   / step);

    var frames = [];

    for (var f = start; f <= end; f++) {{
        Scene.setFrame(f);

        // Bone rotations — parallel list matching boneNames index
        var rotations = [];
        for (var i = 0; i < allBones.length; i++) {{
            var b = allBones[i];
            rotations.push([
                b.getXRotControl().getValue(),
                b.getYRotControl().getValue(),
                b.getZRotControl().getValue()
            ]);
        }}

        // Animated properties — geometry morphs and node-level properties combined
        var morphs = {{}};
        for (var i = 0; i < animatedChannels.length; i++) {{
            var v = animatedChannels[i][1].getValue();
            if (Math.abs(v) > 0.0001) morphs[animatedChannels[i][0]] = v;
        }}

        frames.push({{frame: f, rotations: rotations, morphs: morphs}});
    }}

    return {{
        figure:      label,
        frame_range: {{start: start, end: end}},
        bones:       boneNames,
        frames:      frames
    }};
}})()"""

print(f"Capturing frames {play_range['start']}–{play_range['end']} for {args.figure!r}...")
result = client.execute(script).value

if result is None:
    sys.exit(f"Error: figure {args.figure!r} not found in scene.")

# Restore the frame DAZ Studio was on before the dump
scene.set_frame(original_frame)

with open(args.out, "w") as f:
    json.dump(result, f, indent=2)

n_frames = len(result["frames"])
n_bones  = len(result["bones"])
print(f"Wrote {n_frames} frames × {n_bones} bones → {args.out}")
if args.morphs:
    animated_morphs = {k for fr in result["frames"] for k in fr["morphs"]}
    print(f"Captured {len(animated_morphs)} animated morph(s)")
