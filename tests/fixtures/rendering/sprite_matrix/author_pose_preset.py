"""Capture the current Daz Studio pose into the pose preset library.

Usage:
    python author_pose_preset.py --name standing_neutral --figure "Genesis 9" \
        --library C:/presets/poses [--force]

Workflow: pose the character by hand in the live Daz Studio session, then run
this script to save it as a named preset the sprite matrix spec can reference.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from dazpy import DazClient, DazPose, DazScene


def main() -> None:
    p = argparse.ArgumentParser(description="Capture the current Daz pose into a named preset")
    p.add_argument("--name", required=True, help="Preset name (used as the JSON filename)")
    p.add_argument("--figure", required=True, help="Figure label to capture (e.g. 'Genesis 9')")
    p.add_argument("--library", required=True, metavar="DIR", help="Pose library directory")
    p.add_argument("--force", action="store_true", help="Overwrite an existing preset")
    args = p.parse_args()

    dest = os.path.join(args.library, f"{args.name}.json")
    if os.path.isfile(dest) and not args.force:
        print(f"ERROR: {dest} already exists; pass --force to overwrite", file=sys.stderr)
        sys.exit(1)

    client = DazClient()
    scene = DazScene(client)
    skeleton = scene.find_skeleton_by_label(args.figure)

    pose = DazPose.capture(skeleton)
    os.makedirs(args.library, exist_ok=True)
    pose.save(dest)
    print(f"Saved pose preset: {dest} ({len(pose.bones)} bones, {len(pose.morphs)} morphs)")


if __name__ == "__main__":
    main()
