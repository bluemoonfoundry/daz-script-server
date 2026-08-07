"""EXR canvas -> PNG conversion for ComfyUI ingestion, and Canny/lineart
derivation from the beauty render.

ComfyUI's LoadImage node expects PNG/JPEG, not raw EXR, so the Normal/Depth
Iray Canvas outputs must be tonemapped to 8-bit PNG before upload. The third
ControlNet conditioning pass is Canny/lineart derived locally from the beauty
render via OpenCV rather than MaterialID (stock ControlNet models don't
understand DAZ's per-material-ID color palette).
"""
from __future__ import annotations

import os

# The official opencv-python wheel ships OpenEXR support disabled by default
# (hardening after historical OpenEXR CVEs) -- must opt in before cv2 loads
# its codec plugins. Safe here: these EXRs are Iray Canvas outputs this
# pipeline renders itself, not untrusted input.
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import cv2
import numpy as np


def convert_depth_exr_to_png(exr_path: str, png_path: str, *, near: float = 0.0, far: float | None = None) -> str:
    """Read a single-channel (or RGB-duplicated) Depth canvas EXR and write a
    normalized 8-bit grayscale PNG suitable for a depth ControlNet.

    Depth is linearly normalized into [0, 255] over [near, far]; far defaults
    to the maximum finite value present in the image so every render
    self-normalizes (recommended: pin `far` explicitly once the scene's
    camera-to-subject distance range is known, for consistent depth scale
    across a whole matrix).
    """
    img = cv2.imread(exr_path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(f"Could not read EXR: {exr_path}")
    if img.ndim == 3:
        img = img[:, :, 0]

    finite = img[np.isfinite(img)]
    resolved_far = far if far is not None else (float(finite.max()) if finite.size else 1.0)
    span = max(resolved_far - near, 1e-6)

    normalized = np.clip((img - near) / span, 0.0, 1.0)
    normalized = np.nan_to_num(normalized, nan=1.0, posinf=1.0, neginf=0.0)
    depth_8bit = (normalized * 255.0).astype(np.uint8)

    os.makedirs(os.path.dirname(png_path), exist_ok=True)
    cv2.imwrite(png_path, depth_8bit)
    return png_path


def convert_normal_exr_to_png(normal_path: str, png_path: str) -> str:
    """Read a world-space Normal canvas EXR (components in [-1, 1]) and write
    a standard RGB normal-map PNG (components remapped to [0, 255], OpenGL
    green-channel convention: +Y up).
    """
    img = cv2.imread(normal_path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(f"Could not read EXR: {normal_path}")
    if img.ndim != 3 or img.shape[2] < 3:
        raise ValueError(f"Expected a 3-channel normal EXR, got shape {img.shape}")

    # cv2 reads EXR as BGR; convert to RGB, remap [-1,1] -> [0,255].
    rgb = cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2RGB)
    remapped = np.clip((rgb * 0.5 + 0.5) * 255.0, 0, 255).astype(np.uint8)

    os.makedirs(os.path.dirname(png_path), exist_ok=True)
    # write back as BGR for cv2.imwrite
    cv2.imwrite(png_path, cv2.cvtColor(remapped, cv2.COLOR_RGB2BGR))
    return png_path


def derive_lineart(beauty_png_path: str, lineart_png_path: str, *, low_threshold: int = 80, high_threshold: int = 160) -> str:
    """Derive a Canny edge/lineart pass from the beauty render."""
    img = cv2.imread(beauty_png_path, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"Could not read beauty render: {beauty_png_path}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, low_threshold, high_threshold)
    # Invert so lines are dark-on-white, matching typical lineart ControlNet training data.
    inverted = cv2.bitwise_not(edges)

    os.makedirs(os.path.dirname(lineart_png_path), exist_ok=True)
    cv2.imwrite(lineart_png_path, inverted)
    return lineart_png_path


def multiply_blend(color_path: str, lineart_path: str, opacity: float, out_path: str) -> str:
    """Composite the (inverted, dark-on-white) lineart pass over a color
    render using a partial-opacity multiply blend.

    For lineart pixel L (0 = black line, 255 = white/no-line background) and
    color pixel C, a full multiply blend is ``C * L / 255``. `opacity`
    linearly interpolates between the unblended color (opacity=0) and the
    fully multiplied result (opacity=1):

        result = C * (1 - opacity) + (C * L / 255) * opacity

    lineart_path is expected to be the same dimensions as color_path (both
    derived from the same render); if not, the lineart is resized to match
    defensively. A single-channel (grayscale) lineart is broadcast to match
    color's channel count.
    """
    color = cv2.imread(color_path, cv2.IMREAD_COLOR)
    if color is None:
        raise FileNotFoundError(f"Could not read color image: {color_path}")
    lineart = cv2.imread(lineart_path, cv2.IMREAD_UNCHANGED)
    if lineart is None:
        raise FileNotFoundError(f"Could not read lineart image: {lineart_path}")

    if lineart.shape[:2] != color.shape[:2]:
        lineart = cv2.resize(lineart, (color.shape[1], color.shape[0]), interpolation=cv2.INTER_NEAREST)

    if lineart.ndim == 2:
        lineart = cv2.cvtColor(lineart, cv2.COLOR_GRAY2BGR)
    elif lineart.shape[2] != color.shape[2]:
        raise ValueError(f"Lineart channel count {lineart.shape[2]} incompatible with color channel count {color.shape[2]}")

    color_f = color.astype(np.float32)
    lineart_f = lineart.astype(np.float32)

    multiplied = color_f * lineart_f / 255.0
    blended = color_f * (1.0 - opacity) + multiplied * opacity
    result = np.clip(blended, 0, 255).astype(np.uint8)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    cv2.imwrite(out_path, result)
    return out_path
