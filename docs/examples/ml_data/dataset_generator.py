"""DAZ Studio Script Server example: generate a randomised render dataset for AI/ML training.

PURPOSE
-------
This script is a demonstration of what the DAZ Studio Script Server makes
possible.  It randomises a set of expression morphs on a Genesis 9 figure
and renders each variation to a numbered PNG.  The morph values used for
each image are saved alongside the renders as a JSON sidecar, making the
dataset fully reproducible.

It is an *example*, not a production LoRA-dataset pipeline.  A real dataset
tool would add lighting variation, camera angle randomisation, background
swapping, and metadata in the correct training format.  The goal here is to
show that Python can drive DAZ Studio's render engine in an automated loop
to produce training data without any manual UI interaction.

WHAT IT DEMONSTRATES
--------------------
  - Finding named expression morphs on a figure by label
  - Randomising morph values with Python's random module
  - Setting morph values and triggering a render for each sample
  - Wrapping each render in an undo step so DAZ Studio stays clean
  - Writing a JSON metadata sidecar alongside the rendered images

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

4. Open a scene in DAZ Studio containing a Genesis 9 figure, then run:

       python docs/examples/ml_data/dataset_generator.py

Usage:
    python dataset_generator.py [--count 100] [--out C:/dataset] [--size 512]
"""

import argparse
import json
import os
import random

from dazpy import DazScene, DazRenderSettings

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
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
