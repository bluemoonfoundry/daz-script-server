"""Generate a randomised render dataset for AI/ML training (e.g. LoRA).

Randomises a set of expression morphs on a Genesis 9 figure and renders
each variation to a numbered PNG file.  Morph values are saved alongside
the images as a JSON sidecar so the dataset is fully reproducible.

Usage:
    python dataset_generator.py [--count 100] [--out C:/dataset] [--size 512]
"""

import argparse
import json
import os
import random

from dazpy import DazScene, DazRenderSettings

parser = argparse.ArgumentParser()
parser.add_argument("--count", type=int, default=10)
parser.add_argument("--out",   default="y:/tmp/")
parser.add_argument("--size",  type=int, default=512)
args = parser.parse_args()

os.makedirs(args.out, exist_ok=True)

scene  = DazScene()
render = DazRenderSettings()
figure = scene.find_skeleton_by_label("Genesis 9")

MORPH_LABELS = [
    "Smile Full Face",
    "Mouth Open",
    "Brows Up",
    "Brows Down",
    "Eyes Closed",
    "Cheeks Puff",
]

morphs = {label: figure.find_property_by_label(label) for label in MORPH_LABELS}
missing = [label for label, prop in morphs.items() if prop is None]
if missing:
    print(f"Warning: morphs not found and will be skipped: {missing}")
    morphs = {k: v for k, v in morphs.items() if v is not None}

render.set_resolution(args.size, args.size)

metadata = []

for i in range(args.count):
    values = {label: round(random.random(), 4) for label in morphs}

    with scene.undo(f"Dataset sample {i}"):
        for label, prop in morphs.items():
            prop.value = values[label]

        img_path = os.path.join(args.out, f"img_{i:04d}.png")
        render.output_path = img_path
        render.render()

    metadata.append({"file": os.path.basename(img_path), "morphs": values})
    print(f"[{i+1}/{args.count}] {img_path}")

with open(os.path.join(args.out, "metadata.json"), "w") as f:
    json.dump(metadata, f, indent=2)

print(f"\nDone. {args.count} images written to {args.out}")
