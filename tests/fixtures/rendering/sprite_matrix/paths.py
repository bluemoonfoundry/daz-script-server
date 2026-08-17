"""Deterministic output paths and resume (file-exists) checks.

Pure functions only -- no I/O beyond os.path.isfile() checks. This is the
unit-testable surface for the pipeline's naming convention and resume logic.
"""
from __future__ import annotations

import os

CANVAS_NAME_BY_TYPE = {"Normal": "Normal", "Depth": "Depth"}


def _np(path: str) -> str:
    """Normalize to the OS-native separator.

    Mixed forward/backslashes (e.g. an output_dir passed with "/" on Windows,
    then os.path.join appending "\\" for the rest) confuse DAZ Studio's own
    canvas-path derivation -- confirmed live: a mixed-separator
    renderImgFilename caused Iray Canvas outputs to land under a doubled,
    nested directory instead of the documented "<basename>_canvases"
    convention. Every path handed to DazRenderSettings.output_path, and
    every path this module hands back for file-existence checks, must be
    fully normalized so it matches whatever DAZ Studio actually wrote.
    """
    return os.path.normpath(path)


def combo_dir(output_dir: str, combo_id: str) -> str:
    return _np(os.path.join(output_dir, "renders", combo_id))


def beauty_path(output_dir: str, combo_id: str, camera: str) -> str:
    return _np(os.path.join(combo_dir(output_dir, combo_id), f"{camera}.png"))


def canvas_dir(output_dir: str, combo_id: str, camera: str) -> str:
    return _np(os.path.join(combo_dir(output_dir, combo_id), f"{camera}_canvases"))


def canvas_path(output_dir: str, combo_id: str, camera: str, canvas_name: str, canvas_type: str) -> str:
    return _np(os.path.join(
        canvas_dir(output_dir, combo_id, camera),
        f"{camera}-{canvas_name}-{canvas_type}.exr",
    ))


def lineart_path(output_dir: str, combo_id: str, camera: str) -> str:
    return _np(os.path.join(combo_dir(output_dir, combo_id), f"{camera}_lineart", f"{camera}.png"))


def normal_png_path(output_dir: str, combo_id: str, camera: str) -> str:
    return _np(os.path.join(canvas_dir(output_dir, combo_id, camera), f"{camera}-Normal-converted.png"))


def depth_png_path(output_dir: str, combo_id: str, camera: str) -> str:
    return _np(os.path.join(canvas_dir(output_dir, combo_id, camera), f"{camera}-Depth-converted.png"))


def stylized_path(output_dir: str, combo_id: str, camera: str) -> str:
    return _np(os.path.join(output_dir, "stylized", combo_id, f"{camera}.png"))


def render_outputs_exist(output_dir: str, combo_id: str, camera: str, canvas_names: tuple[str, ...]) -> bool:
    """True if the beauty render and every requested canvas already exist on disk."""
    if not os.path.isfile(beauty_path(output_dir, combo_id, camera)):
        return False
    for canvas_name in canvas_names:
        canvas_type = CANVAS_NAME_BY_TYPE.get(canvas_name, canvas_name)
        if not os.path.isfile(canvas_path(output_dir, combo_id, camera, canvas_name, canvas_type)):
            return False
    return True


def stylized_output_exists(output_dir: str, combo_id: str, camera: str) -> bool:
    return os.path.isfile(stylized_path(output_dir, combo_id, camera))
