from __future__ import annotations

import copy
import json
import random
from pathlib import Path

_TEMPLATE_PATH = Path(__file__).with_name("workflow.json")

_DEFAULT_POSITIVE = (
    "photorealistic, sharp focus, high detail, 8k, "
    "professional photography, clean lighting"
)
_DEFAULT_NEGATIVE = (
    "(blurry, low quality, noise, artifact, watermark:1.4), "
    "painterly, cartoon, drawing"
)


def build(
    image_ref: str,
    checkpoint_name: str = "v1-5-pruned-emaonly.ckpt",
    denoise: float = 0.45,
    steps: int = 20,
    positive_prompt: str = _DEFAULT_POSITIVE,
    negative_prompt: str = _DEFAULT_NEGATIVE,
    seed: int | None = None,
) -> dict:
    """Return a ComfyUI API-format prompt dict ready for queue_prompt()."""
    with open(_TEMPLATE_PATH) as f:
        workflow = json.load(f)

    workflow = copy.deepcopy(workflow)

    workflow["1"]["inputs"]["ckpt_name"] = checkpoint_name
    workflow["2"]["inputs"]["image"] = image_ref
    workflow["4"]["inputs"]["text"] = positive_prompt
    workflow["5"]["inputs"]["text"] = negative_prompt
    workflow["6"]["inputs"]["steps"] = int(steps)
    workflow["6"]["inputs"]["denoise"] = float(denoise)
    workflow["6"]["inputs"]["seed"] = seed if seed is not None else random.randint(0, 2**32 - 1)

    return workflow
