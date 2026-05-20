"""DAZ Studio Script Server example: capture a pose from one figure and apply it to another.

PURPOSE
-------
This script is a demonstration of what the DAZ Studio Script Server makes
possible.  It reads every bone's local Euler rotation from a source figure in
a single pass, then applies matching rotations to a destination figure inside
a single undo step — so the full transfer is undoable with Ctrl+Z in DAZ Studio.

It is an *example*, not a full pose-library tool.  A production pose system
would handle finger bones, morph dials, node-level properties, and file-based
pose storage.  The goal here is to show that the script server exposes enough
of the DAZ rig to perform non-trivial skeleton operations from Python.

WHAT IT DEMONSTRATES
--------------------
  - Finding figures by label in the live scene (DazScene.find_skeleton_by_label)
  - Reading per-bone local Euler rotations (DzBone.local_euler)
  - Writing bone rotations with set_local_rotation
  - Wrapping multiple DAZ calls in a single named undo step (scene.undo context manager)

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

4. Open a scene in DAZ Studio containing two Genesis 9 figures labelled
   "Genesis 9" and "Genesis 9-2", then run:

       python docs/examples/pose_transfer.py

Usage:
    python pose_transfer.py
"""

from dazpy import DazScene

scene = DazScene()

src = scene.find_skeleton_by_label("Genesis 9")
dst = scene.find_skeleton_by_label("Genesis 9-2")

# Capture pose — local_euler returns (x, y, z) in degrees, the same values
# written by set_local_rotation, so round-tripping is lossless.
pose = {bone.name: bone.local_euler for bone in src.bones()}

with scene.undo("Transfer pose"):
    for bone in dst.bones():
        angles = pose.get(bone.name)
        if angles:
            bone.set_local_rotation(*angles)

print(f"Transferred {len(pose)} bone rotations from {src.label!r} to {dst.label!r}")
