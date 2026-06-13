"""DAZ Studio Script Server example: mirror your facial expression onto a Genesis 9 figure in real time.

PURPOSE
-------
This script is a demonstration of what the DAZ Studio Script Server makes
possible.  It captures frames from a webcam, runs MediaPipe FaceLandmarker
inference on each frame, computes Action Unit (AU) magnitudes from the landmark
geometry, and pushes FACS property values to a live DAZ Studio figure over HTTP
at a configurable rate — producing real-time expression mirroring.

It is an *example*, not a production performance-capture tool.  A real system
would use hardware-accelerated GPU inference, audio sync, and a direct render
pipeline.  The goal here is to show that the script server's low-latency HTTP
API is fast enough to drive live facial animation from an external process at
usable frame rates.

Pairs naturally with DAZ's Face Transfer 2: create a 3D version of yourself
with that tool, then use this script to drive its expressions live.

WHAT IT DEMONSTRATES
--------------------
  - Capturing webcam frames with OpenCV and running MediaPipe FaceLandmarker
    in VIDEO mode for each frame
  - Computing Action Unit magnitudes from landmark geometry (shared calibration
    with expression_transfer.py)
  - Applying exponential moving average (EMA) smoothing to reduce jitter
  - Rate-limiting DAZ Studio updates to a configurable --fps ceiling
  - Drawing a live AU bar overlay and landmark dots on the preview window
  - Zeroing all FACS morphs on exit so the figure returns to neutral

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
   applied, connect a webcam, then run:

       python docs/examples/ai_vision/webcam_expression_mirror.py

Usage:
    python webcam_expression_mirror.py
    python webcam_expression_mirror.py --figure "Genesis 9" --scale 0.8
    python webcam_expression_mirror.py --camera 1 --fps 15
    python webcam_expression_mirror.py --smooth 0.7
    python webcam_expression_mirror.py --no-preview
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from collections import deque

import cv2
import mediapipe as mp
import numpy as np

from dazpy import DazClient

# ── model setup ────────────────────────────────────────────────────────────────

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
# MediaPipe canonical indices — anatomical left/right (not image left/right).
# Matches expression_transfer.py exactly so AU calibration is shared.

L_EYE_TOP, L_EYE_BOT = 159, 145
L_EYE_OUT, L_EYE_IN  =  33, 133
R_EYE_TOP, R_EYE_BOT = 386, 374
R_EYE_OUT, R_EYE_IN  = 263, 362

L_BROW_IN,  L_BROW_MID,  L_BROW_OUT  = 107, 55,  46
R_BROW_IN,  R_BROW_MID,  R_BROW_OUT  = 336, 285, 276

MOUTH_L,   MOUTH_R    =  61, 291
LIP_UP_IN, LIP_DN_IN  =  13,  14

FACE_TOP, FACE_BOT = 10, 152

# Subset drawn in the preview — the tracked feature points only
_PREVIEW_POINTS = [
    L_EYE_TOP, L_EYE_BOT, L_EYE_OUT, L_EYE_IN,
    R_EYE_TOP, R_EYE_BOT, R_EYE_OUT, R_EYE_IN,
    L_BROW_IN, L_BROW_MID, L_BROW_OUT,
    R_BROW_IN, R_BROW_MID, R_BROW_OUT,
    MOUTH_L, MOUTH_R, LIP_UP_IN, LIP_DN_IN,
]

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
# Identical to expression_transfer.py — calibration constants are shared.

def compute_aus(lm: list[tuple[float, float]]) -> dict[str, float]:
    """Compute Action Unit magnitudes from pixel-space face mesh landmarks."""
    face_h = _dist(lm[FACE_TOP], lm[FACE_BOT]) or 1.0
    face_w = _dist(lm[L_EYE_OUT], lm[R_EYE_OUT]) or 1.0
    aus: dict[str, float] = {}

    OPEN_EAR = 0.28
    l_ear = _ear(lm, L_EYE_TOP, L_EYE_BOT, L_EYE_OUT, L_EYE_IN)
    r_ear = _ear(lm, R_EYE_TOP, R_EYE_BOT, R_EYE_OUT, R_EYE_IN)
    aus["eye_blink_l"] = _clamp(1.0 - l_ear / OPEN_EAR)
    aus["eye_blink_r"] = _clamp(1.0 - r_ear / OPEN_EAR)
    aus["eye_wide_l"]  = _clamp((l_ear - OPEN_EAR) / 0.12)
    aus["eye_wide_r"]  = _clamp((r_ear - OPEN_EAR) / 0.12)

    BROW_IN_NEUTRAL, BROW_IN_RANGE = 0.060, 0.050
    aus["brow_inner_up_l"] = _clamp(
        ((lm[L_EYE_IN][1] - lm[L_BROW_IN][1]) / face_h - BROW_IN_NEUTRAL) / BROW_IN_RANGE
    )
    aus["brow_inner_up_r"] = _clamp(
        ((lm[R_EYE_IN][1] - lm[R_BROW_IN][1]) / face_h - BROW_IN_NEUTRAL) / BROW_IN_RANGE
    )

    BROW_OUT_NEUTRAL, BROW_OUT_RANGE = 0.065, 0.050
    aus["brow_outer_up_l"] = _clamp(
        ((lm[L_EYE_OUT][1] - lm[L_BROW_OUT][1]) / face_h - BROW_OUT_NEUTRAL) / BROW_OUT_RANGE
    )
    aus["brow_outer_up_r"] = _clamp(
        ((lm[R_EYE_OUT][1] - lm[R_BROW_OUT][1]) / face_h - BROW_OUT_NEUTRAL) / BROW_OUT_RANGE
    )

    BROW_CONV_NEUTRAL, BROW_CONV_RANGE = 0.40, 0.14
    brow_conv = _dist(lm[L_BROW_IN], lm[R_BROW_IN]) / face_w
    brow_down = _clamp((BROW_CONV_NEUTRAL - brow_conv) / BROW_CONV_RANGE)
    aus["brow_down_l"] = brow_down
    aus["brow_down_r"] = brow_down

    JAW_NEUTRAL, JAW_RANGE = 0.018, 0.090
    aus["jaw_open"] = _clamp(
        (_dist(lm[LIP_UP_IN], lm[LIP_DN_IN]) / face_h - JAW_NEUTRAL) / JAW_RANGE
    )

    SMILE_NEUTRAL, SMILE_RANGE = 0.44, 0.12
    mouth_w = _dist(lm[MOUTH_L], lm[MOUTH_R]) / face_w
    smile = _clamp((mouth_w - SMILE_NEUTRAL) / SMILE_RANGE)
    aus["mouth_smile_l"] = smile
    aus["mouth_smile_r"] = smile

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
# Targets Genesis 9 base FACS HD label convention.
# Run expression_transfer.py --list-properties to discover labels for your
# installed product, then update this map to match.

FACS_MAP: dict[str, tuple[str, float]] = {
    "eye_blink_l":     ("AU 45 Blink Left",                 1.0),
    "eye_blink_r":     ("AU 45 Blink Right",                1.0),
    "eye_wide_l":      ("Eye Wide Left",                    0.8),
    "eye_wide_r":      ("Eye Wide Right",                   0.8),
    "brow_inner_up_l": ("AU 01 Inner Brow Raiser Left",     0.9),
    "brow_inner_up_r": ("AU 01 Inner Brow Raiser Right",    0.9),
    "brow_outer_up_l": ("AU 02 Outer Brow Raiser Left",     0.9),
    "brow_outer_up_r": ("AU 02 Outer Brow Raiser Right",    0.9),
    "brow_down_l":     ("AU 04 Brow Lowerer Left",          0.9),
    "brow_down_r":     ("AU 04 Brow Lowerer Right",         0.9),
    "jaw_open":        ("AU 26 Jaw Drop",                   1.0),
    "mouth_smile_l":   ("AU 12 Lip Corner Puller Left",     0.9),
    "mouth_smile_r":   ("AU 12 Lip Corner Puller Right",    0.9),
    "mouth_frown_l":   ("AU 15 Lip Corner Depressor Left",  0.9),
    "mouth_frown_r":   ("AU 15 Lip Corner Depressor Right", 0.9),
}

# Short display names for the preview overlay
_AU_SHORT: dict[str, str] = {
    "eye_blink_l":     "Blink L",
    "eye_blink_r":     "Blink R",
    "eye_wide_l":      "Wide L",
    "eye_wide_r":      "Wide R",
    "brow_inner_up_l": "BrowIn L",
    "brow_inner_up_r": "BrowIn R",
    "brow_outer_up_l": "BrowOut L",
    "brow_outer_up_r": "BrowOut R",
    "brow_down_l":     "BrowDn L",
    "brow_down_r":     "BrowDn R",
    "jaw_open":        "Jaw",
    "mouth_smile_l":   "Smile L",
    "mouth_smile_r":   "Smile R",
    "mouth_frown_l":   "Frown L",
    "mouth_frown_r":   "Frown R",
}

# ── DazScript helpers ──────────────────────────────────────────────────────────

def _skel_lookup(label: str) -> str:
    e = json.dumps(label)
    return (
        f"var _skel=null,_skels=Scene.getSkeletonList();"
        f"for(var _i=0;_i<_skels.length;_i++){{"
        f"if(_skels[_i].getLabel()==={e}){{_skel=_skels[_i];break;}}}}"
    )


def _push_facs(
    client: DazClient,
    figure_label: str,
    aus: dict[str, float],
    scale: float,
) -> bool:
    """Send one batch of FACS values to DAZ Studio. Returns True on success."""
    targets: dict[str, float] = {
        label: round(_clamp(aus.get(au_key, 0.0) * au_scale * scale), 4)
        for au_key, (label, au_scale) in FACS_MAP.items()
    }
    targets_js = "{" + ",".join(f"{json.dumps(k)}:{v}" for k, v in targets.items()) + "}"

    script = f"""(function(){{
        {_skel_lookup(figure_label)}
        if (!_skel) return false;
        var t = {targets_js};
        for (var i = 0; i < _skel.getNumProperties(); i++) {{
            var p = _skel.getProperty(i);
            if (p && p.getLabel && t.hasOwnProperty(p.getLabel()))
                p.setValue(t[p.getLabel()]);
        }}
        return true;
    }})()"""

    try:
        return bool(client.execute(script).value)
    except Exception:
        return False


def _zero_facs(client: DazClient, figure_label: str) -> None:
    _push_facs(client, figure_label, {}, scale=0.0)


# ── preview overlay ────────────────────────────────────────────────────────────

_PANEL_W   = 190   # width of the right-side AU panel
_LABEL_W   = 120   # pixels reserved for AU label text
_BAR_MAX_W =  60   # maximum bar fill width
_ROW_H     =  18   # vertical spacing per AU row

def _draw_overlay(
    frame: np.ndarray,
    lms: list[tuple[float, float]] | None,
    aus: dict[str, float],
    capture_fps: float,
    daz_fps: float,
    daz_ok: bool,
) -> None:
    """Draw landmark dots, AU bars, and status info onto frame in-place."""
    h, w = frame.shape[:2]

    # Semi-transparent dark panel on the right for AU bars
    panel_x = max(0, w - _PANEL_W)
    overlay = frame.copy()
    cv2.rectangle(overlay, (panel_x, 0), (w, min(h, len(FACS_MAP) * _ROW_H + 24)),
                  (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

    # Key landmark dots
    if lms:
        for idx in _PREVIEW_POINTS:
            x, y = int(lms[idx][0]), int(lms[idx][1])
            cv2.circle(frame, (x, y), 3, (0, 220, 60), -1)
        face_text, face_color = "FACE DETECTED", (0, 220, 60)
    else:
        face_text, face_color = "NO FACE", (30, 100, 220)

    # AU bar chart
    for i, au_key in enumerate(FACS_MAP):
        y0 = i * _ROW_H + 4
        y1 = y0 + _ROW_H - 2
        v  = aus.get(au_key, 0.0)
        bw = int(v * _BAR_MAX_W)

        cv2.putText(frame, _AU_SHORT[au_key],
                    (panel_x + 2, y0 + 13),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.36, (190, 190, 190), 1)

        bar_x0 = panel_x + _LABEL_W
        cv2.rectangle(frame, (bar_x0, y0 + 2), (bar_x0 + _BAR_MAX_W, y1 - 2),
                      (55, 55, 55), -1)
        if bw > 0:
            color = (0, int(180 * (1 - v)), int(220 * v + 60))
            cv2.rectangle(frame, (bar_x0, y0 + 2), (bar_x0 + bw, y1 - 2), color, -1)

    # Status strip (bottom-left)
    strip_y = h - 4
    cv2.putText(frame, face_text,
                (8, strip_y - 44), cv2.FONT_HERSHEY_SIMPLEX, 0.6, face_color, 2)
    cv2.putText(frame, f"cam {capture_fps:.0f} fps  |  daz {daz_fps:.0f} fps",
                (8, strip_y - 22), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (180, 180, 180), 1)
    daz_label = "DAZ OK" if daz_ok else "DAZ: connection error"
    daz_color = (0, 200, 60) if daz_ok else (30, 80, 220)
    cv2.putText(frame, daz_label, (8, strip_y - 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.48, daz_color, 1)
    cv2.putText(frame, "Q to quit", (w - _PANEL_W - 75, strip_y - 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.40, (120, 120, 120), 1)


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--figure",     default="Genesis 9",
                        help="DAZ figure label (default: 'Genesis 9')")
    parser.add_argument("--scale",      type=float, default=1.0,
                        help="Global expression scale factor (default: 1.0)")
    parser.add_argument("--camera",     type=int, default=0,
                        help="OpenCV camera index (default: 0)")
    parser.add_argument("--fps",        type=float, default=10.0,
                        help="Max DAZ Studio updates per second (default: 10)")
    parser.add_argument("--smooth",     type=float, default=0.5,
                        help="EMA smoothing factor 0–0.95: 0 = off, 0.9 = heavy (default: 0.5)")
    parser.add_argument("--no-preview", action="store_true",
                        help="Run headless — no OpenCV window (Ctrl+C to stop)")
    args = parser.parse_args()

    _ensure_model()
    client = DazClient()

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        sys.exit(f"Cannot open camera {args.camera}.")

    FaceLandmarker        = mp.tasks.vision.FaceLandmarker
    FaceLandmarkerOptions = mp.tasks.vision.FaceLandmarkerOptions
    BaseOptions           = mp.tasks.BaseOptions
    RunningMode           = mp.tasks.vision.RunningMode

    options = FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=_MODEL_PATH),
        running_mode=RunningMode.VIDEO,
        num_faces=1,
    )

    ema: dict[str, float] = {}
    send_interval = 1.0 / max(args.fps, 0.5)
    last_send     = 0.0
    daz_ok        = True

    cap_ts:  deque[float] = deque(maxlen=30)   # for camera fps
    daz_ts:  deque[float] = deque(maxlen=20)   # for actual daz update rate

    print(f"Mirroring to {args.figure!r} — up to {args.fps:.0f} DAZ updates/s.")
    if args.no_preview:
        print("Running headless. Press Ctrl+C to stop.")
    else:
        print("Preview window open. Press Q to stop.")

    try:
        with FaceLandmarker.create_from_options(options) as landmarker:
            while True:
                ret, frame = cap.read()
                if not ret:
                    print("Camera read failed — exiting.")
                    break

                frame = cv2.flip(frame, 1)          # mirror so it feels like a selfie
                h, w  = frame.shape[:2]
                ts_ms = int(time.monotonic() * 1000)

                rgb    = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                result = landmarker.detect_for_video(mp_img, ts_ms)

                lms: list[tuple[float, float]] | None = None
                if result.face_landmarks:
                    lms     = [(lm.x * w, lm.y * h) for lm in result.face_landmarks[0]]
                    raw_aus = compute_aus(lms)
                    alpha   = _clamp(args.smooth, 0.0, 0.95)
                    for k, v in raw_aus.items():
                        ema[k] = alpha * ema.get(k, v) + (1.0 - alpha) * v

                    now = time.monotonic()
                    if now - last_send >= send_interval:
                        daz_ok    = _push_facs(client, args.figure, ema, args.scale)
                        last_send = now
                        daz_ts.append(now)

                now = time.perf_counter()
                cap_ts.append(now)
                cap_fps = ((len(cap_ts) - 1) / (cap_ts[-1] - cap_ts[0])
                           if len(cap_ts) >= 2 else 0.0)
                daz_fps = ((len(daz_ts) - 1) / (daz_ts[-1] - daz_ts[0])
                           if len(daz_ts) >= 2 else 0.0)

                if not args.no_preview:
                    _draw_overlay(frame, lms, ema, cap_fps, daz_fps, daz_ok)
                    cv2.imshow("Expression Mirror", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
                else:
                    active = sum(1 for v in ema.values() if v > 0.01)
                    print(
                        f"\r  cam {cap_fps:4.1f} fps  "
                        f"daz {daz_fps:4.1f} fps  "
                        f"{active:2d} active AUs  "
                        f"{'DAZ OK ' if daz_ok else 'DAZ ERR'}",
                        end="", flush=True,
                    )

    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        if not args.no_preview:
            cv2.destroyAllWindows()
        print("\nZeroing FACS morphs...", flush=True)
        _zero_facs(client, args.figure)
        print("Done.")


if __name__ == "__main__":
    main()
