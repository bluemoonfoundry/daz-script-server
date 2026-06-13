"""DAZ Studio Script Server example: apply a facial expression from a photo to a Genesis 9 figure.

PURPOSE
-------
This script is a demonstration of what the DAZ Studio Script Server makes
possible.  It extracts 478 face landmarks from a source image using MediaPipe
FaceLandmarker, computes Action Unit (AU) magnitudes from the landmark
geometry entirely in Python, maps them to Genesis 9 FACS HD property labels,
and sends a single HTTP call to DAZ Studio to apply the expression.

It is an *example*, not a production facial capture tool.  A real system would
account for head pose, partial occlusion, and per-user AU calibration.  The
goal here is to show that the script server lets Python use any ML inference
library and apply the results to a live DAZ figure without any DAZ plugin
development.

WHAT IT DEMONSTRATES
--------------------
  - Running MediaPipe FaceLandmarker inference in Python (auto-downloads the
    model file on first run)
  - Computing Action Unit magnitudes from pixel-space landmark geometry
    (eye blink, wide, brow up/down, jaw open, smile, frown)
  - Mapping AUs to DAZ FACS HD property labels via a configurable FACS_MAP
  - Applying all FACS values to the live figure in a single HTTP call
  - Listing available FACS properties on the figure (--list-properties) to
    help adapt the map to other FACS products (ARKit, etc.)
  - Debug output showing matched/unmatched property labels

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
       pip install requests mediapipe opencv-python numpy

3. Install or develop-install the dazpy SDK (from the repo root):

       pip install -e .

4. Open a scene in DAZ Studio containing a Genesis 9 figure with FACS HD
   applied, then run:

       python docs/examples/ai_vision/expression_transfer.py photo.jpg

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
import os
import sys
import urllib.request

import cv2
import mediapipe as mp
import numpy as np

from dazpy import DazClient

# ── model setup ────────────────────────────────────────────────────────────────
# mediapipe >= 0.10 uses the Tasks API and requires a model file.
# We download it automatically on first use.
_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_landmarker/face_landmarker/float16/1/face_landmarker.task"
)
_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "face_landmarker.task")


def _ensure_model() -> str:
    if not os.path.exists(_MODEL_PATH):
        print(f"Downloading face landmarker model → {_MODEL_PATH}")
        urllib.request.urlretrieve(_MODEL_URL, _MODEL_PATH)
    return _MODEL_PATH

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
# Genesis 9 base FACS uses "AU XX Description Left/Right" label convention.
# Run --debug or --list-properties --search <term> if values still don't apply —
# installed FACS products vary, and you may need to adjust these labels.

FACS_MAP: dict[str, tuple[str, float]] = {
    "eye_blink_l":     ("AU 45 Blink Left",                1.0),
    "eye_blink_r":     ("AU 45 Blink Right",               1.0),
    "eye_wide_l":      ("Eye Wide Left",                   0.8),
    "eye_wide_r":      ("Eye Wide Right",                  0.8),
    "brow_inner_up_l": ("AU 01 Inner Brow Raiser Left",    0.9),
    "brow_inner_up_r": ("AU 01 Inner Brow Raiser Right",   0.9),
    "brow_outer_up_l": ("AU 02 Outer Brow Raiser Left",    0.9),
    "brow_outer_up_r": ("AU 02 Outer Brow Raiser Right",   0.9),
    "brow_down_l":     ("AU 04 Brow Lowerer Left",         0.9),
    "brow_down_r":     ("AU 04 Brow Lowerer Right",        0.9),
    "jaw_open":        ("AU 26 Jaw Drop",                  1.0),
    "mouth_smile_l":   ("AU 12 Lip Corner Puller Left",    0.9),
    "mouth_smile_r":   ("AU 12 Lip Corner Puller Right",   0.9),
    "mouth_frown_l":   ("AU 15 Lip Corner Depressor Left", 0.9),
    "mouth_frown_r":   ("AU 15 Lip Corner Depressor Right",0.9),
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
    debug: bool = False,
) -> dict[str, float]:
    """Apply AU values to Genesis 9 FACS properties in a single HTTP call.

    Iterates all numeric skeleton properties once to build a label→property
    map in DazScript, then sets each mapped value.  Returns the count of
    properties that were actually matched and set.

    Args:
        client: Active DazClient.
        figure_label: Label of the target figure in DAZ Studio.
        aus: AU key → magnitude in [0, 1].
        scale: Global multiplier applied after per-AU scale factors.
        reset: Zero all mapped FACS properties before applying.
        debug: Return full diagnostics instead of just the match count.

    Returns:
        Dict of property label → applied value (for logging).
    """
    targets: dict[str, float] = {}
    for au_key, (label, au_scale) in FACS_MAP.items():
        if reset or aus.get(au_key, 0.0) != 0.0:
            targets[label] = round(_clamp(aus.get(au_key, 0.0) * au_scale * scale), 4)

    targets_js = "{" + ",".join(f"{json.dumps(k)}:{v}" for k, v in targets.items()) + "}"

    script = f"""(function(){{
        {_skel_lookup(figure_label)}
        if (!_skel) return null;
        var targets = {targets_js};
        var matched = [], all_labels = [];
        for (var i = 0; i < _skel.getNumProperties(); i++) {{
            var p = _skel.getProperty(i);
            if (!p) continue;
            var lbl = p.getLabel ? p.getLabel() : null;
            if (!lbl) continue;
            all_labels.push(lbl);
            if (targets.hasOwnProperty(lbl)) {{
                if (p.setValue) p.setValue(targets[lbl]);
                matched.push(lbl);
            }}
        }}
        return {{matched: matched, total_props: all_labels.length, all_labels: all_labels}};
    }})()"""

    result = client.execute(script).value
    if result is None:
        sys.exit(f"Error: figure {figure_label!r} not found in scene.")

    matched_labels = result.get("matched", [])
    total_props    = result.get("total_props", 0)
    all_labels     = result.get("all_labels", [])

    if debug:
        print(f"\nDebug: {total_props} properties on skeleton.")
        missing = [lbl for lbl in targets if lbl not in matched_labels]
        if matched_labels:
            print(f"  Matched ({len(matched_labels)}): {matched_labels}")
        if missing:
            print(f"  Not found ({len(missing)}): {missing}")
        if missing and all_labels:
            # For each unmatched label show skeleton properties that share a
            # meaningful word.  Directional/positional words are excluded because
            # they appear in thousands of unrelated property names.
            _SKIP = {"left", "right", "up", "down", "inner", "outer", "the",
                     "and", "for", "open", "close"}
            print("\n  Candidate properties for unmatched labels:")
            for target_lbl in missing:
                keywords = {w.lower() for w in target_lbl.split()
                            if len(w) >= 3 and w.lower() not in _SKIP}
                candidates = [lbl for lbl in all_labels
                              if any(kw in lbl.lower() for kw in keywords)]
                if candidates:
                    print(f"    {target_lbl!r}  (keywords: {sorted(keywords)}):")
                    for c in sorted(set(candidates))[:10]:
                        print(f"      {c!r}")
                else:
                    print(f"    {target_lbl!r}: (no candidates — try: "
                          f"--list-properties --search {target_lbl.split()[0].lower()!r})")

    if not matched_labels:
        print(
            f"\nWarning: 0 of {len(targets)} FACS properties matched on {figure_label!r} "
            f"({total_props} skeleton properties searched).\n"
            "Run --list-properties or --debug to see available labels, then\n"
            "update FACS_MAP at the top of this file.",
            file=sys.stderr,
        )

    return targets


# ── image → landmarks ──────────────────────────────────────────────────────────

def extract_landmarks(image_path: str) -> list[tuple[float, float]]:
    """Decode an image and return 478 pixel-space face landmarks.

    Uses the mediapipe Tasks API (mediapipe >= 0.10).  Downloads the
    face_landmarker.task model file to the same directory on first run.

    Raises SystemExit if the image cannot be loaded or no face is detected.
    """
    img = cv2.imread(image_path)
    if img is None:
        sys.exit(f"Cannot load image: {image_path!r}")

    h, w = img.shape[:2]
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    FaceLandmarker = mp.tasks.vision.FaceLandmarker
    FaceLandmarkerOptions = mp.tasks.vision.FaceLandmarkerOptions
    BaseOptions = mp.tasks.BaseOptions
    RunningMode = mp.tasks.vision.RunningMode

    options = FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=_ensure_model()),
        running_mode=RunningMode.IMAGE,
        num_faces=1,
    )

    with FaceLandmarker.create_from_options(options) as landmarker:
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = landmarker.detect(mp_image)

    if not result.face_landmarks:
        sys.exit("No face detected in image.")

    lms = result.face_landmarks[0]
    return [(lm.x * w, lm.y * h) for lm in lms]


if __name__ == "__main__":
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
    parser.add_argument("--search", metavar="TERM",
                        help="Filter --list-properties output (case-insensitive substring)")
    parser.add_argument("--debug", action="store_true",
                        help="Print which FACS labels matched/missed and all skeleton property labels")
    args = parser.parse_args()

    client = DazClient()

    if args.list_properties:
        props = list_properties(client, args.figure)
        if props is None:
            sys.exit(f"Figure {args.figure!r} not found in scene.")
        if args.search:
            term = args.search.lower()
            props = [p for p in props if term in p["label"].lower()]
            print(f"{len(props)} properties matching {args.search!r} on {args.figure!r}:\n")
        else:
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

    applied = apply_expression(
        client, args.figure, aus, scale=args.scale, reset=args.reset, debug=args.debug
    )

    active = {label: v for label, v in applied.items() if v > 0.005}
    print(f"\nApplied {len(active)} active FACS properties to {args.figure!r}:")
    for label, value in active.items():
        print(f"  {label}: {value:.3f}")
    if not active:
        print("  (no active properties — try a more expressive photo or increase --scale)")
