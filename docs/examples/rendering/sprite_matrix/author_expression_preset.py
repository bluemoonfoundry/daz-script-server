"""Capture the current Daz Studio facial morph dials into the expression
preset library.

Usage:
    python author_expression_preset.py --name calm --figure "Genesis 9" \
        --library C:/presets/expressions [--force]

Workflow: dial in the facial expression by hand in the live Daz Studio
session (body pose is ignored), then run this script to save it as a named
preset the sprite matrix spec can reference.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dazpy import DazClient, DazScene

from presets import ExpressionPreset


def main() -> None:
    p = argparse.ArgumentParser(description="Capture the current Daz facial expression into a named preset")
    p.add_argument("--name", required=True, help="Preset name (used as the JSON filename)")
    p.add_argument("--figure", required=True, help="Figure label to capture (e.g. 'Genesis 9')")
    p.add_argument("--library", required=True, metavar="DIR", help="Expression library directory")
    p.add_argument("--force", action="store_true", help="Overwrite an existing preset")
    args = p.parse_args()

    dest = os.path.join(args.library, f"{args.name}.json")
    if os.path.isfile(dest) and not args.force:
        print(f"ERROR: {dest} already exists; pass --force to overwrite", file=sys.stderr)
        sys.exit(1)

    client = DazClient()
    scene = DazScene(client)
    skeleton = scene.find_skeleton_by_label(args.figure)

    expression = ExpressionPreset.capture(skeleton)
    os.makedirs(args.library, exist_ok=True)
    expression.save(dest)
    print(f"Saved expression preset: {dest} ({len(expression.morphs)} morphs)")


if __name__ == "__main__":
    main()
