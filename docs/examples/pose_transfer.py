"""Capture a pose from one figure and apply it to another.

Reads every bone's local Euler rotation from the source figure in a single
pass, then applies matching rotations to the destination figure inside a
single undo step so the transfer can be undone with Ctrl+Z in DAZ Studio.

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
