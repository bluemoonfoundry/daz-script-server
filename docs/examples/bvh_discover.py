"""DAZ Studio Script Server example: discover bone names for a loaded figure and emit a bvh_bone_maps entry.

PURPOSE
-------
This script is a demonstration of what the DAZ Studio Script Server makes
possible.  It connects to a running DAZ Studio instance, reads every bone
name from a specified figure, and emits a ready-to-paste CANONICAL_TO_DAZ
block for bvh_bone_maps.py — letting you verify or extend the bone-name
mapping tables for any DAZ generation without manually browsing the rig.

It is an *example*, not an automated retargeting wizard.  A production tool
would also handle finger chains and facial bones.  The goal here is to show
that the script server exposes the full figure skeleton to Python inspection,
making it easy to reverse-engineer the internal bone names needed to retarget
BVH mocap data.

WHAT IT DEMONSTRATES
--------------------
  - Querying all bones (name + label) from a figure in a single HTTP call
  - Auto-detecting the DAZ generation from characteristic probe bone names
  - Validating each canonical joint slot against the live figure's bone set
  - Printing a ready-to-paste CANONICAL_TO_DAZ dict block with MISSING markers
    for any bones that do not match the expected names
  - Optional --dump flag to print every bone in the figure for manual lookup

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

4. Load the target generation in DAZ Studio, then run:

       python docs/examples/bvh_discover.py --figure "Genesis 8 Female"

Usage:
    python bvh_discover.py --figure "Genesis 8 Female"
    python bvh_discover.py                        # uses primary selection
    python bvh_discover.py --figure "Genesis 9" --dump
    python bvh_discover.py --figure "Genesis 9" --generation genesis9
"""

import argparse
import json
import sys

from dazpy import DazClient, DazScene
from bvh_bone_maps import CANONICAL, CANONICAL_TO_DAZ

# ── candidate name lists for auto-detection ────────────────────────────────────
# Checked in order; first match determines the generation.

_GENERATION_PROBES: list[tuple[str, str]] = [
    # (probe bone name, generation key)
    ("l_thigh",      "genesis9"),
    ("lThighBend",   "genesis3"),   # also covers genesis8
    ("abdomen2",     "genesis2"),
    ("abdomen",      "genesis1"),
]

# ── DAZ queries ────────────────────────────────────────────────────────────────

def _all_bones(client: DazClient, figure_label: str) -> list[dict]:
    """Return [{name, label}] for every bone in the figure."""
    escaped = json.dumps(figure_label)
    script = f"""(function(){{
        var _skel=null, _skels=Scene.getSkeletonList();
        for(var i=0;i<_skels.length;i++){{
            if(_skels[i].getLabel()==={escaped}){{_skel=_skels[i];break;}}
        }}
        if(!_skel) return null;
        var bones=_skel.getAllBones(), out=[];
        for(var i=0;i<bones.length;i++){{
            out.push({{name:bones[i].getName(), label:bones[i].getLabel()}});
        }}
        return out;
    }})()"""
    return client.execute(script).value or []


def _primary_label(client: DazClient) -> str | None:
    script = ("(function(){var n=Scene.getPrimarySelection();"
              "return n?n.getLabel():null;})() ")
    return client.execute(script).value


def _bone_exists(bone_set: set[str], name: str) -> bool:
    return name in bone_set


def _detect_generation(bone_set: set[str]) -> str | None:
    for probe, gen in _GENERATION_PROBES:
        if probe in bone_set:
            return gen
    return None


if __name__ == "__main__":
    # ── main ───────────────────────────────────────────────────────────────────────

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--figure",     default=None,
                        help="Figure label (default: primary selection)")
    parser.add_argument("--dump",       action="store_true",
                        help="Print all bone names before the mapping")
    parser.add_argument("--generation", default=None,
                        choices=list(CANONICAL_TO_DAZ),
                        help="Override generation auto-detection")
    args = parser.parse_args()

    client = DazClient()
    scene  = DazScene(client)

    figure_label = args.figure or _primary_label(client)
    if not figure_label:
        sys.exit("No figure label — use --figure or select a figure in DAZ Studio.")

    bones = _all_bones(client, figure_label)
    if not bones:
        sys.exit(f"Figure {figure_label!r} not found or has no bones.")

    bone_names  = [b["name"]  for b in bones]
    bone_labels = {b["name"]: b["label"] for b in bones}
    bone_set    = set(bone_names)

    # ── detect generation ──────────────────────────────────────────────────────────

    generation = args.generation or _detect_generation(bone_set)
    if not generation:
        print("Could not auto-detect generation. Known probe bones not found.")
        print("Use --generation to specify, or check --dump output.")
        generation = "UNKNOWN"

    print(f"Figure : {figure_label}")
    print(f"Bones  : {len(bones)}")
    print(f"Generation detected: {generation}\n")

    # ── optional full dump ─────────────────────────────────────────────────────────

    if args.dump:
        print("── All bones (name → label) ──────────────────────────────────────")
        for b in bones:
            label_suffix = f"  # label: {b['label']}" if b["label"] != b["name"] else ""
            print(f"    {b['name']!r}{label_suffix}")
        print()

    # ── check each canonical joint against the live figure ────────────────────────

    reference = CANONICAL_TO_DAZ.get(generation, {})
    found:   list[tuple[str, str]] = []
    missing: list[tuple[str, str]] = []

    for canonical in CANONICAL:
        expected = reference.get(canonical)
        if expected is None:
            found.append((canonical, "None"))
            continue
        if _bone_exists(bone_set, expected):
            found.append((canonical, repr(expected)))
        else:
            missing.append((canonical, expected))

    # ── report ─────────────────────────────────────────────────────────────────────

    if missing:
        print("── MISSING bones (in map but not in figure) ──────────────────────")
        for canonical, expected in missing:
            print(f"  canonical={canonical!r}  expected DAZ name={expected!r}")
        print()

    # ── emit ready-to-paste CANONICAL_TO_DAZ block ────────────────────────────────

    gen_key = generation.lower().replace(" ", "")
    print(f'    # {figure_label} — verified by bvh_discover.py')
    print(f'    "{gen_key}": {{')
    for canonical, daz_repr in found:
        pad = " " * max(1, 34 - len(canonical))
        print(f'        "{canonical}":{pad}{daz_repr},')
    for canonical, expected in missing:
        pad = " " * max(1, 34 - len(canonical))
        print(f'        "{canonical}":{pad}None,  # MISSING: expected {expected!r}')
    print("    },")
