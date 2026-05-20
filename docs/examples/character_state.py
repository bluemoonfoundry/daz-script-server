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
  - Restores morph, property, and bone values in two HTTP calls per direction

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

       python docs/examples/character_state.py save --figure "Genesis 9" --out state.json

Usage:
    python character_state.py save    --figure "Genesis 9" --out state.json
    python character_state.py restore --figure "Genesis 9" --file state.json
"""

import argparse
import json
import sys

from dazpy import DazClient, DazScene

# ── helpers ───────────────────────────────────────────────────────────────────

def _skel_lookup(label: str) -> str:
    """Return the JS snippet that finds a skeleton by label into _skel."""
    escaped = json.dumps(label)
    return (
        f"var _skel=null,_skels=Scene.getSkeletonList();"
        f"for(var _i=0;_i<_skels.length;_i++){{"
        f"if(_skels[_i].getLabel()==={escaped}){{_skel=_skels[_i];break;}}}}"
    )


def save_state(client: DazClient, figure_label: str) -> dict:
    """Read all non-default morph, property, and bone values in two HTTP calls."""

    # ── morphs + node properties (one call) ───────────────────────────────────
    morph_prop_script = f"""(function(){{
        {_skel_lookup(figure_label)}
        if (!_skel) return null;

        var morphs = {{}};
        var obj = _skel.getObject();
        if (obj) {{
            for (var i = 0; i < obj.getNumModifiers(); i++) {{
                var m = obj.getModifier(i);
                if (m.className() === "DzMorph") {{
                    var v = m.getValueChannel().getValue();
                    if (Math.abs(v) > 0.0001) morphs[m.getName()] = v;
                }}
            }}
        }}

        var props = {{}};
        for (var i = 0; i < _skel.getNumProperties(); i++) {{
            var p = _skel.getProperty(i);
            if (p && p.getValue) {{
                var v = p.getValue();
                if (typeof v === "number" && Math.abs(v) > 0.0001)
                    props[p.getName()] = v;
            }}
        }}

        return {{morphs: morphs, props: props}};
    }})()"""

    # ── bone rotations (one call) ──────────────────────────────────────────────
    bone_script = f"""(function(){{
        {_skel_lookup(figure_label)}
        if (!_skel) return null;

        var bones = {{}};
        var all = _skel.getAllBones();
        for (var i = 0; i < all.length; i++) {{
            var b = all[i];
            var x = b.getXRotControl().getValue();
            var y = b.getYRotControl().getValue();
            var z = b.getZRotControl().getValue();
            if (Math.abs(x) > 0.0001 || Math.abs(y) > 0.0001 || Math.abs(z) > 0.0001)
                bones[b.getName()] = [x, y, z];
        }}
        return bones;
    }})()"""

    mp = client.execute(morph_prop_script).value
    if mp is None:
        sys.exit(f"Error: figure {figure_label!r} not found in scene.")

    bones = client.execute(bone_script).value or {}

    return {
        "figure":  figure_label,
        "morphs":  mp["morphs"],
        "props":   mp["props"],
        "bones":   bones,
    }


def restore_state(client: DazClient, state: dict) -> None:
    """Apply saved morph, property, and bone values in two HTTP calls."""

    figure_label = state["figure"]
    morphs = state.get("morphs", {})
    props  = state.get("props",  {})
    bones  = state.get("bones",  {})

    # ── morphs + node properties (one call) ───────────────────────────────────
    morph_lines = " ".join(
        f"var _m=obj.findModifier({json.dumps(name)});"
        f"if(_m)_m.getValueChannel().setValue({value});"
        for name, value in morphs.items()
    )
    prop_lines = " ".join(
        f"var _p=_skel.findProperty({json.dumps(name)});"
        f"if(_p&&_p.setValue)_p.setValue({value});"
        for name, value in props.items()
    )
    morph_prop_restore = f"""(function(){{
        {_skel_lookup(figure_label)}
        if (!_skel) return false;
        var obj = _skel.getObject();
        if (obj) {{ {morph_lines} }}
        {prop_lines}
        return true;
    }})()"""

    # ── bone rotations (one call) ──────────────────────────────────────────────
    bone_lines = " ".join(
        f"var _b=_skel.findBone({json.dumps(name)});"
        f"if(_b){{"
        f"_b.getXRotControl().setValue({xyz[0]});"
        f"_b.getYRotControl().setValue({xyz[1]});"
        f"_b.getZRotControl().setValue({xyz[2]});}}"
        for name, xyz in bones.items()
    )
    bone_restore = f"""(function(){{
        {_skel_lookup(figure_label)}
        if (!_skel) return false;
        {bone_lines}
        return true;
    }})()"""

    client.execute(morph_prop_restore)
    client.execute(bone_restore)


# ── CLI ───────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
sub = parser.add_subparsers(dest="cmd", required=True)

save_p = sub.add_parser("save")
save_p.add_argument("--figure", default="Genesis 9")
save_p.add_argument("--out",    default="state.json")

restore_p = sub.add_parser("restore")
restore_p.add_argument("--figure", default=None, help="Override figure label from file")
restore_p.add_argument("--file",   required=True)

args = parser.parse_args()
client = DazClient()

if args.cmd == "save":
    state = save_state(client, args.figure)
    with open(args.out, "w") as f:
        json.dump(state, f, indent=2)
    print(f"Saved {len(state['morphs'])} morphs, {len(state['props'])} properties, "
          f"{len(state['bones'])} bones → {args.out}")

elif args.cmd == "restore":
    with open(args.file) as f:
        state = json.load(f)
    if args.figure:
        state["figure"] = args.figure
    restore_state(client, state)
    print(f"Restored {len(state['morphs'])} morphs, {len(state['props'])} properties, "
          f"{len(state['bones'])} bones → {state['figure']!r}")
