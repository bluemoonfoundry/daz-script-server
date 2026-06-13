from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field


def _read_daz_token() -> str:
    token_path = os.path.expanduser("~/.daz3d/dazscriptserver_token.txt")
    try:
        with open(token_path) as f:
            return f.read().strip()
    except OSError:
        return ""


@dataclass
class PipelineConfig:
    daz_url: str = "http://127.0.0.1:18811"
    daz_token: str = field(default_factory=_read_daz_token)
    comfyui_url: str = "http://127.0.0.1:8188"
    watch_dir: str = field(default_factory=tempfile.gettempdir)
    output_dir: str = field(default_factory=tempfile.gettempdir)
    snapshot_width: int = 1024
    snapshot_height: int = 1024
    denoise_strength: float = 0.45
    checkpoint_name: str = "v1-5-pruned-emaonly.ckpt"
    steps: int = 20
