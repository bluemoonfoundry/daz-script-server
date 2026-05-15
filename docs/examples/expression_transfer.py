"""Apply a facial expression from a photo to a Genesis 9 figure in DAZ Studio.

MediaPipe Face Mesh extracts 468 landmarks from the source image.  Python
computes landmark geometry into Action Unit (AU) magnitudes, maps them to
Genesis 9 FACS HD property values, and sends a single HTTP call to DAZ Studio.

What Python does that DazScript cannot:
  - Load and decode the image (any format OpenCV handles)
  - Run MediaPipe Face Mesh inference
  - Compute AU magnitudes from landmark geometry
  - Map AUs to DAZ FACS property labels with per-AU scale factors

What DAZ Studio does:
  - Receive one batch of property values
  - Apply them atomically to the live figure

Calibration note: AU magnitudes are computed relative to population-average
face proportions.  Use --scale to tune overall expressiveness.  Run
--list-properties to see exactly which FACS controls exist on your figure —
property labels vary between FACS products (FACS HD, ARKit, etc.), so you may
need to edit FACS_MAP to match what is installed.

Dependencies:
    pip install mediapipe opencv-python numpy

Usage:
    python expression_transfer.py photo.jpg
    python expression_transfer.py photo.jpg --figure "Genesis 9"
    python expression_transfer.py photo.jpg --scale 0.8
    python expression_transfer.py photo.jpg --no-reset
    python expression_transfer.py --list-properties
"""

from __future__ import annotations

import argparse
import json
import sys

import cv2
import mediapipe as mp
import numpy as np

from dazpy import DazClient

# ── landmark index constants ───────────────────────────────────────────────────
# MediaPipe Face Mesh canonical indices, from the person's perspective.
# "Left" = person's anatomical left, which appears on the IMAGE RIGHT in a
# frontal photo.

# Left eye (person's left, image right)
L_EYE_TOP, L_EYE_BOT = 159, 145
L_EYE_OUT, L_EYE_IN  = 33,  133

# Right eye (person's right, image left)
R_EYE_TOP, R_EYE_BOT = 386, 374
R_EYE_OUT, R_EYE_IN  = 263, 362

# Brows (inner = toward nose, outer = toward temple)
L_BROW_IN,  L_BROW_MID,  L_BROW_OUT  = 107, 55,  46
R_BROW_IN,  R_BROW_MID,  R_BROW_OUT  = 336, 285, 276

# Mouth
MOUTH_L, MOUTH_R       = 61,  291  # corners
LIP_UP_IN, LIP_DN_IN   = 13,  14   # inner upper / lower (jaw-open proxy)

# Face reference (forehead crown → chin)
FACE_TOP, FACE_BOT = 10, 152

# ── geometry helpers ───────────────────────────────────────────────────────────

def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return float(np.hypot(a[0] - b[0], a[1] - b[1]))


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _ear(lm: list, top: int, bot: int, out: int, inn: int) -> float:
    """Eye Aspect Ratio — ~0.28 when open, ~0.0 when closed."""
    h = _dist(lm[out], lm[inn])
    return _dist(lm[top], lm[bot]) / h if h > 0 else 0.0


# ── AU computation ─────────────────────────────────────────────────────────────

def compute_aus(lm: list[tuple[float, float]]) -> dict[str, float]:
    """Compute Action Unit magnitudes from pixel-space face mesh landmarks.

    All measurements are normalised by face height so the result is
    scale-invariant.  Returns values in [0, 1] where 0 = neutral / inactive.

    Calibration constants below are fit to typical frontal portrait photos.
    If results are systematically too strong or too weak, adjust --scale on
    the command line rather than editing these constants.
    """
    face_h = _dist(lm[FACE_TOP], lm[FACE_BOT]) or 1.0
    face_w = _dist(lm[L_EYE_OUT], lm[R_EYE_OUT]) or 1.0

    aus: dict[str, float] = {}

    # Eye blink (AU46): EAR → 0 as eye closes
    OPEN_EAR = 0.28
    l_ear = _ear(lm, L_EYE_TOP, L_EYE_BOT, L_EYE_OUT, L_EYE_IN)
    r_ear = _ear(lm, R_EYE_TOP, R_EYE_BOT, R_EYE_OUT, R_EYE_IN)
    aus["eye_blink_l"] = _clamp(1.0 - l_ear / OPEN_EAR)
    aus["eye_blink_r"] = _clamp(1.0 - r_ear / OPEN_EAR)

    # Eye wide (AU5): EAR exceeds the open baseline
    aus["eye_wide_l"] = _clamp((l_ear - OPEN_EAR) / 0.12)
    aus["eye_wide_r"] = _clamp((r_ear - OPEN_EAR) / 0.12)

    # Brow inner up (AU1): inner brow rises above inner eye corner.
    # Image y increases downward, so "above" = smaller y.
    # Gap = inner_eye_y − inner_brow_y (positive when brow is above eye corner).
    BROW_IN_NEUTRAL, BROW_IN_RANGE = 0.060, 0.050
    aus["brow_inner_up_l"] = _clamp(
        ((lm[L_EYE_IN][1] - lm[L_BROW_IN][1]) / face_h - BROW_IN_NEUTRAL) / BROW_IN_RANGE
    )
    aus["brow_inner_up_r"] = _clamp(
        ((lm[R_EYE_IN][1] - lm[R_BROW_IN][1]) / face_h - BROW_IN_NEUTRAL) / BROW_IN_RANGE
    )

    # Brow outer up (AU2): outer brow rises above outer eye corner
    BROW_OUT_NEUTRAL, BROW_OUT_RANGE = 0.065, 0.050
    aus["brow_outer_up_l"] = _clamp(
        ((lm[L_EYE_OUT][1] - lm[L_BROW_OUT][1]) / face_h - BROW_OUT_NEUTRAL) / BROW_OUT_RANGE
    )
    aus["brow_outer_up_r"] = _clamp(
        ((lm[R_EYE_OUT][1] - lm[R_BROW_OUT][1]) / face_h - BROW_OUT_NEUTRAL) / BROW_OUT_RANGE
    )

    # Brow down / furrow (AU4): inner brows converge horizontally
    BROW_CONV_NEUTRAL, BROW_CONV_RANGE = 0.40, 0.14
    brow_conv = _dist(lm[L_BROW_IN], lm[R_BROW_IN]) / face_w
    brow_down = _clamp((BROW_CONV_NEUTRAL - brow_conv) / BROW_CONV_RANGE)
    aus["brow_down_l"] = brow_down
    aus["brow_down_r"] = brow_down

    # Jaw open (AU26/27): inner-lip vertical gap
    JAW_NEUTRAL, JAW_RANGE = 0.018, 0.090
    aus["jaw_open"] = _clamp(
        (_dist(lm[LIP_UP_IN], lm[LIP_DN_IN]) / face_h - JAW_NEUTRAL) / JAW_RANGE
    )

    # Smile / lip corner pull (AU12): mouth width expands relative to face width
    SMILE_NEUTRAL, SMILE_RANGE = 0.44, 0.12
    mouth_w = _dist(lm[MOUTH_L], lm[MOUTH_R]) / face_w
    smile = _clamp((mouth_w - SMILE_NEUTRAL) / SMILE_RANGE)
    aus["mouth_smile_l"] = smile
    aus["mouth_smile_r"] = smile

    # Lip corner depress / frown (AU15): corners drop below the lip centre line
    lip_ctr_y = (lm[LIP_UP_IN][1] + lm[LIP_DN_IN][1]) / 2.0
    FROWN_NEUTRAL, FROWN_RANGE = 0.008, 0.030
    aus["mouth_frown_l"] = _clamp(
        ((lm[MOUTH_L][1] - lip_ctr_y) / face_h - FROWN_NEUTRAL) / FROWN_RANGE
    )
    aus["mouth_frown_r"] = _clamp(
        ((lm[MOUTH_R][1] - lip_ctr_y) / face_h - FROWN_NEUTRAL) / FROWN_RANGE
    )

    return aus


# ── FACS property mapping ──────────────────────────────────────────────────────
# Maps AU key → (DAZ property label, per-AU scale factor).
# Labels match the Parameters pane labels for Genesis 9 FACS HD Expressions.
# Run --list-properties to see what is actually on your figure, then update
# the labels here if your FACS product uses different names.

FACS_MAP: dict[str, tuple[str, float]] = {
    "eye_blink_l":     ("Eye Blink Left",      1.0),
    "eye_blink_r":     ("Eye Blink Right",     1.0),
    "eye_wide_l":      ("Eye Wide Left",       0.8),
    "eye_wide_r":      ("Eye Wide Right",      0.8),
    "brow_inner_up_l": ("Brow Inner Up Left",  0.9),
    "brow_inner_up_r": ("Brow Inner Up Right", 0.9),
    "brow_outer_up_l": ("Brow Outer Up Left",  0.9),
    "brow_outer_up_r": ("Brow Outer Up Right", 0.9),
    "brow_down_l":     ("Brow Down Left",      0.9),
    "brow_down_r":     ("Brow Down Right",     0.9),
    "jaw_open":        ("Jaw Open",            1.0),
    "mouth_smile_l":   ("Mouth Smile Left",    0.9),
    "mouth_smile_r":   ("Mouth Smile Right",   0.9),
    "mouth_frown_l":   ("Mouth Frown Left",    0.9),
    "mouth_frown_r":   ("Mouth Frown Right",   0.9),
}

# ── DazScript helpers ──────────────────────────────────────────────────────────

def _skel_lookup(label: str) -> str:
    e = json.dumps(label)
    return (
        f"var _skel=null,_skels=Scene.getSkeletonList();"
        f"for(var _i=0;_i<_skels.length;_i++){{"
        f"if(_skels[_i].getLabel()==={e}){{_skel=_skels[_i];break;}}}}"
    )


def list_properties(client: DazClient, figure_label: str) -> list[dict] | None:
    """Return all numeric node-level properties on the figure skeleton."""
    script = f"""(function(){{
        {_skel_lookup(figure_label)}
        if (!_skel) return null;
        var out = [];
        for (var i = 0; i < _skel.getNumProperties(); i++) {{
            var p = _skel.getProperty(i);
            if (p && p.getValue) {{
                var v = p.getValue();
                if (typeof v === "number")
                    out.push({{name: p.getName(), label: p.getLabel()}});
            }}
        }}
        return out;
    }})()"""
    return client.execute(script).value


def apply_expression(
    client: DazClient,
    figure_label: str,
    aus: dict[str, float],
    scale: float = 1.0,
    reset: bool = True,
) -> dict[str, float]:
    """Apply AU values to Genesis 9 FACS properties in a single HTTP call.

    Builds one DazScript that walks every mapped AU, locates the corresponding
    property by label, and sets it.  Missing properties are silently skipped —
    no error is raised if a label is not present on the figure.

    Args:
        client: Active DazClient.
        figure_label: Label of the target figure in DAZ Studio.
        aus: AU key → magnitude in [0, 1].
        scale: Global multiplier applied after per-AU scale factors.
        reset: Zero all mapped FACS properties before applying.  Set False
            to blend on top of an existing expression.

    Returns:
        Dict of property label → applied value (for logging).
    """
    lines: list[str] = []
    applied: dict[str, float] = {}

    for au_key, (label, au_scale) in FACS_MAP.items():
        value = round(_clamp(aus.get(au_key, 0.0) * au_scale * scale), 4)
        if reset or value != 0.0:
            escaped = json.dumps(label)
            lines.append(
                f"var _p=_skel.findPropertyByLabel({escaped});"
                f"if(_p&&_p.setValue)_p.setValue({value});"
            )
            applied[label] = value

    script = f"""(function(){{
        {_skel_lookup(figure_label)}
        if (!_skel) return false;
        {"".join(lines)}
        return true;
    }})()"""

    if not client.execute(script).value:
        sys.exit(f"Error: figure {figure_label!r} not found in scene.")

    return applied


# ── image → landmarks ──────────────────────────────────────────────────────────

def extract_landmarks(image_path: str) -> list[tuple[float, float]]:
    """Decode an image and return 468 pixel-space face mesh landmarks.

    Raises SystemExit if the image cannot be loaded or no face is detected.
    """
    img = cv2.imread(image_path)
    if img is None:
        sys.exit(f"Cannot load image: {image_path!r}")

    h, w = img.shape[:2]
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    face_mesh = mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
    )
    results = face_mesh.process(rgb)
    face_mesh.close()

    if not results.multi_face_landmarks:
        sys.exit("No face detected in image.")

    lms = results.multi_face_landmarks[0].landmark
    return [(lm.x * w, lm.y * h) for lm in lms]


# ── CLI ────────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(
    description=__doc__,
    formatter_class=argparse.RawDescriptionHelpFormatter,
)
parser.add_argument("image", nargs="?", help="Path to source image")
parser.add_argument("--figure",   default="Genesis 9",
                    help="DAZ figure label (default: 'Genesis 9')")
parser.add_argument("--scale",    type=float, default=1.0,
                    help="Global expression scale factor (default: 1.0)")
parser.add_argument("--no-reset", dest="reset", action="store_false",
                    help="Blend onto existing expression instead of zeroing first")
parser.add_argument("--list-properties", action="store_true",
                    help="List numeric properties on the figure and exit")
args = parser.parse_args()

client = DazClient()

if args.list_properties:
    props = list_properties(client, args.figure)
    if props is None:
        sys.exit(f"Figure {args.figure!r} not found in scene.")
    print(f"{len(props)} numeric properties on {args.figure!r}:\n")
    for p in sorted(props, key=lambda x: x["label"]):
        print(f"  {p['label']!r:40s}  ({p['name']})")
    sys.exit(0)

if not args.image:
    parser.error("image path required (or use --list-properties)")

landmarks = extract_landmarks(args.image)
aus = compute_aus(landmarks)

print(f"Action units from {args.image!r}:")
for k, v in aus.items():
    bar = "#" * int(v * 20)
    print(f"  {k:20s}  {v:.3f}  {bar}")

applied = apply_expression(client, args.figure, aus, scale=args.scale, reset=args.reset)

active = {label: v for label, v in applied.items() if v > 0.005}
print(f"\nApplied {len(active)} active FACS properties to {args.figure!r}:")
for label, value in active.items():
    print(f"  {label}: {value:.3f}")
if not active:
    print("  (no active properties — try a more expressive photo or increase --scale)")
