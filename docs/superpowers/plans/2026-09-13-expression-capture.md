# Facial Expression Capture/Application Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--expression-image` to `pose_transfer_photo.py` so a photo's facial
expression (extracted via MediaPipe `FaceLandmarker` blendshapes) can be applied
to a Genesis 9 figure's `facs_bs_*`/`facs_ctrl_*` morphs, on top of an already-
solved body pose, producing one output variant per (photo x expression image).

**Architecture:** Two new pure/near-pure modules
(`expression_mapping.py` — static ARKit-to-DAZ-morph table + two pure functions,
fully unit-testable; `face_landmarks.py` — MediaPipe extraction wrapper,
mirrors the existing `hand_landmarks.py` pattern, live-only) plus a
restructuring of `pose_transfer_photo.py`'s per-photo output loop to fan out
over expression variants.

**Tech Stack:** Python, MediaPipe Tasks API (`FaceLandmarker`,
`output_face_blendshapes=True`), dazpy (`DazSkeleton.set_morph_values`,
`.morph_values`), pytest.

**Spec:** `docs/superpowers/specs/2026-09-13-expression-capture-design.md`

## Global Constraints

- No new pip dependencies — `mediapipe>=0.10.0`, `opencv-python>=4.8.0`,
  `numpy>=1.24.0` in `ai_vision/pose_transfer_photo/requirements.txt` already
  cover everything needed (verbatim from spec's Components section).
- `ARKIT_TO_DAZ_MORPH` values are exactly the 49 entries verified live against
  Genesis 9 ("Jason Cross") on 2026-09-13 (spec's "Spike findings" /
  "expression_mapping.py" sections) — do not add, rename, or guess new entries.
- `eyeWideLeft`, `eyeWideRight`, `tongueOut` are the only unmapped ARKit
  categories (spec, verbatim) — must appear in `UNMAPPED_ARKIT_CATEGORIES`,
  nowhere else.
- Do not reuse or modify `ai_vision/expression_transfer/expression_transfer.py`
  (spec's "Relationship to expression_transfer.py" section) — separate
  technique, separate morph vocabulary, left untouched.
- `--dforce` simulation runs once per photo, before the expression-variant
  loop, never once per variant (spec, verbatim — re-simulating per expression
  would multiply wall-clock cost for no physical benefit).
- Follow this repo's existing pedagogical comment style in
  `pose_transfer_photo.py`/`hand_landmarks.py`/`finger_ik.py`: docstrings and
  inline comments explain *why* a non-obvious choice was made (unlike this
  plan's own home repo's terser default convention) — new code in this
  feature should read the same way.
- Test style: plain `pytest` functions (`def test_...():`), no test classes —
  matches `test_finger_ik.py`/`test_pinocchio_ik.py` in this same directory.
- All file paths below are relative to
  `Y:/working/BlueMoonFoundry/daz-script-server-examples/ai_vision/pose_transfer_photo/`
  unless stated otherwise.

---

## Task 1: `expression_mapping.py` — ARKit-to-DAZ-morph mapping (pure, unit-tested)

**Files:**
- Create: `expression_mapping.py`
- Test: `test_expression_mapping.py`

**Interfaces:**
- Produces (consumed by Task 3):
  - `ARKIT_TO_DAZ_MORPH: dict[str, list[str]]`
  - `UNMAPPED_ARKIT_CATEGORIES: frozenset[str]`
  - `daz_morph_values(blendshapes: dict[str, float], scale: float = 1.0) -> dict[str, float]`
  - `warn_unmapped_categories(blendshapes: dict[str, float], threshold: float = 0.1) -> list[str]`

- [ ] **Step 1: Write the failing tests**

Create `test_expression_mapping.py`:

```python
from __future__ import annotations

import expression_mapping as em

# The full 52-category ARKit blendshape set MediaPipe FaceLandmarker outputs.
ALL_ARKIT_CATEGORIES = [
    "browDownLeft", "browDownRight", "browInnerUp", "browOuterUpLeft", "browOuterUpRight",
    "cheekPuff", "cheekSquintLeft", "cheekSquintRight",
    "eyeBlinkLeft", "eyeBlinkRight", "eyeLookDownLeft", "eyeLookDownRight", "eyeLookInLeft",
    "eyeLookInRight", "eyeLookOutLeft", "eyeLookOutRight", "eyeLookUpLeft", "eyeLookUpRight",
    "eyeSquintLeft", "eyeSquintRight", "eyeWideLeft", "eyeWideRight",
    "jawForward", "jawLeft", "jawOpen", "jawRight",
    "mouthClose", "mouthDimpleLeft", "mouthDimpleRight", "mouthFrownLeft", "mouthFrownRight",
    "mouthFunnel", "mouthLeft", "mouthLowerDownLeft", "mouthLowerDownRight",
    "mouthPressLeft", "mouthPressRight", "mouthPucker", "mouthRight",
    "mouthRollLower", "mouthRollUpper", "mouthShrugLower", "mouthShrugUpper",
    "mouthSmileLeft", "mouthSmileRight", "mouthStretchLeft", "mouthStretchRight",
    "mouthUpperUpLeft", "mouthUpperUpRight", "noseSneerLeft", "noseSneerRight", "tongueOut",
]


def test_full_arkit_set_has_52_categories():
    assert len(ALL_ARKIT_CATEGORIES) == 52


def test_mapping_plus_unmapped_covers_every_arkit_category_exactly_once():
    covered = set(em.ARKIT_TO_DAZ_MORPH) | em.UNMAPPED_ARKIT_CATEGORIES
    assert covered == set(ALL_ARKIT_CATEGORIES)
    assert not (set(em.ARKIT_TO_DAZ_MORPH) & em.UNMAPPED_ARKIT_CATEGORIES)


def test_unmapped_categories_are_exactly_the_three_documented_gaps():
    assert em.UNMAPPED_ARKIT_CATEGORIES == frozenset({"eyeWideLeft", "eyeWideRight", "tongueOut"})


def test_mapping_values_are_nonempty_lists_of_globally_unique_daz_names():
    seen: set[str] = set()
    for category, daz_names in em.ARKIT_TO_DAZ_MORPH.items():
        assert daz_names, f"{category} maps to an empty list"
        for name in daz_names:
            assert name.startswith(("facs_bs_", "facs_ctrl_")), f"{name} unexpected prefix"
            assert name not in seen, f"{name} mapped from more than one ARKit category"
            seen.add(name)


def test_daz_morph_values_zeros_every_mapped_morph_when_blendshapes_empty():
    values = em.daz_morph_values({})
    assert values["facs_bs_JawOpen"] == 0.0
    assert values["facs_bs_MouthSmileLeft"] == 0.0
    assert all(v == 0.0 for v in values.values())
    # every DAZ name referenced anywhere in the table must be present, zeroed
    all_daz_names = {n for names in em.ARKIT_TO_DAZ_MORPH.values() for n in names}
    assert set(values) == all_daz_names


def test_daz_morph_values_applies_score_and_scale():
    values = em.daz_morph_values({"jawOpen": 0.6}, scale=0.5)
    assert values["facs_bs_JawOpen"] == 0.3


def test_daz_morph_values_splits_bilateral_arkit_category_to_both_daz_morphs():
    values = em.daz_morph_values({"browInnerUp": 0.8})
    assert values["facs_bs_BrowInnerUpLeft"] == 0.8
    assert values["facs_bs_BrowInnerUpRight"] == 0.8


def test_daz_morph_values_ignores_unmapped_categories():
    values = em.daz_morph_values({"tongueOut": 1.0, "eyeWideLeft": 1.0})
    assert all(name.startswith(("facs_bs_", "facs_ctrl_")) for name in values)


def test_warn_unmapped_categories_reports_above_threshold_only_sorted():
    blendshapes = {"tongueOut": 0.5, "eyeWideLeft": 0.05, "eyeWideRight": 0.2}
    assert em.warn_unmapped_categories(blendshapes, threshold=0.1) == ["eyeWideRight", "tongueOut"]


def test_warn_unmapped_categories_empty_when_nothing_active():
    assert em.warn_unmapped_categories({}) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd Y:/working/BlueMoonFoundry/daz-script-server-examples/ai_vision/pose_transfer_photo && python -m pytest test_expression_mapping.py -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'expression_mapping'`

- [ ] **Step 3: Write `expression_mapping.py`**

```python
"""ARKit blendshape category -> Genesis 9 base-rig facs_bs_*/facs_ctrl_*
morph mapping for pose_transfer_photo.py's --expression-image flag.

Verified live against a Genesis 9 figure ("Jason Cross") on 2026-09-13: all
66 DAZ morph names referenced below were confirmed present via
figure.morphs() before this table was written (see
docs/superpowers/specs/2026-09-13-expression-capture-design.md in the
daz-script-server repo for the verification method, in case this table ever
needs re-checking against a different Genesis 9 install or generation).

DAZ's base rig splits several of MediaPipe's *bilateral* ARKit categories
(one score covering both sides, or upper+lower) into 2-4 separate
Left/Right and/or Upper/Lower morphs -- e.g. ARKit's single "mouthClose"
becomes facs_bs_MouthCloseUpperLeft/Right + facs_bs_MouthCloseLowerLeft/
Right. Applying the same ARKit score to every DAZ name in such a group is
the simplest faithful translation and matches how a symmetric real-world
expression actually looks on this rig.

Three ARKit categories have no Genesis 9 base-rig equivalent at all:
eyeWideLeft/Right (no upper-eyelid-raise blendshape) and tongueOut (the
tongue isn't blendshape-driven on this rig) -- see UNMAPPED_ARKIT_CATEGORIES.
"""
from __future__ import annotations

ARKIT_TO_DAZ_MORPH: dict[str, list[str]] = {
    "browDownLeft": ["facs_bs_BrowDownLeft"],
    "browDownRight": ["facs_bs_BrowDownRight"],
    "browInnerUp": ["facs_bs_BrowInnerUpLeft", "facs_bs_BrowInnerUpRight"],
    "browOuterUpLeft": ["facs_bs_BrowOuterUpLeft"],
    "browOuterUpRight": ["facs_bs_BrowOuterUpRight"],
    "cheekPuff": ["facs_bs_CheekPuffLeft", "facs_bs_CheekPuffRight"],
    "cheekSquintLeft": ["facs_bs_CheekSquintLeft"],
    "cheekSquintRight": ["facs_bs_CheekSquintRight"],
    "eyeBlinkLeft": ["facs_bs_EyeBlinkLeft"],
    "eyeBlinkRight": ["facs_bs_EyeBlinkRight"],
    "eyeLookDownLeft": ["facs_bs_EyeLookDownLeft"],
    "eyeLookDownRight": ["facs_bs_EyeLookDownRight"],
    "eyeLookInLeft": ["facs_bs_EyeLookInLeft"],
    "eyeLookInRight": ["facs_bs_EyeLookInRight"],
    "eyeLookOutLeft": ["facs_bs_EyeLookOutLeft"],
    "eyeLookOutRight": ["facs_bs_EyeLookOutRight"],
    "eyeLookUpLeft": ["facs_bs_EyeLookUpLeft"],
    "eyeLookUpRight": ["facs_bs_EyeLookUpRight"],
    "eyeSquintLeft": ["facs_bs_EyeSquintLeft"],
    "eyeSquintRight": ["facs_bs_EyeSquintRight"],
    "jawForward": ["facs_bs_JawForward"],
    "jawLeft": ["facs_bs_JawLeft"],
    "jawOpen": ["facs_bs_JawOpen"],
    "jawRight": ["facs_bs_JawRight"],
    "mouthClose": [
        "facs_bs_MouthCloseUpperLeft", "facs_bs_MouthCloseUpperRight",
        "facs_bs_MouthCloseLowerLeft", "facs_bs_MouthCloseLowerRight",
    ],
    "mouthDimpleLeft": ["facs_bs_MouthDimpleLeft"],
    "mouthDimpleRight": ["facs_bs_MouthDimpleRight"],
    "mouthFrownLeft": ["facs_bs_MouthFrownLeft"],
    "mouthFrownRight": ["facs_bs_MouthFrownRight"],
    "mouthFunnel": [
        "facs_bs_MouthFunnelUpperLeft", "facs_bs_MouthFunnelUpperRight",
        "facs_bs_MouthFunnelLowerLeft", "facs_bs_MouthFunnelLowerRight",
    ],
    "mouthLeft": ["facs_bs_MouthLeft"],
    "mouthLowerDownLeft": ["facs_bs_MouthLowerDownLeft"],
    "mouthLowerDownRight": ["facs_bs_MouthLowerDownRight"],
    "mouthPressLeft": ["facs_bs_MouthPressUpperLeft", "facs_bs_MouthPressLowerLeft"],
    "mouthPressRight": ["facs_bs_MouthPressUpperRight", "facs_bs_MouthPressLowerRight"],
    "mouthPucker": [
        "facs_bs_MouthPurseUpperLeft", "facs_bs_MouthPurseUpperRight",
        "facs_bs_MouthPurseLowerLeft", "facs_bs_MouthPurseLowerRight",
    ],
    "mouthRight": ["facs_bs_MouthRight"],
    "mouthRollLower": ["facs_bs_MouthRollLowerLeft", "facs_bs_MouthRollLowerRight"],
    "mouthRollUpper": ["facs_bs_MouthRollUpperLeft", "facs_bs_MouthRollUpperRight"],
    "mouthShrugLower": ["facs_bs_MouthShrugLowerLeft", "facs_bs_MouthShrugLowerRight"],
    "mouthShrugUpper": ["facs_bs_MouthShrugUpperLeft", "facs_bs_MouthShrugUpperRight"],
    "mouthSmileLeft": ["facs_bs_MouthSmileLeft"],
    "mouthSmileRight": ["facs_bs_MouthSmileRight"],
    "mouthStretchLeft": ["facs_bs_MouthStretchLeft"],
    "mouthStretchRight": ["facs_bs_MouthStretchRight"],
    "mouthUpperUpLeft": ["facs_bs_MouthUpperUpLeft"],
    "mouthUpperUpRight": ["facs_bs_MouthUpperUpRight"],
    "noseSneerLeft": ["facs_bs_NoseSneerLeft"],
    "noseSneerRight": ["facs_bs_NoseSneerRight"],
}

UNMAPPED_ARKIT_CATEGORIES = frozenset({"eyeWideLeft", "eyeWideRight", "tongueOut"})


def daz_morph_values(blendshapes: dict[str, float], scale: float = 1.0) -> dict[str, float]:
    """Convert MediaPipe blendshape scores to a DazSkeleton.set_morph_values() payload.

    Every DAZ morph named anywhere in ARKIT_TO_DAZ_MORPH is included, even at
    0.0 for a category absent from *blendshapes* -- this lets a caller apply
    a fresh expression variant with a single set_morph_values() call, with no
    separate "zero out the previous variant" pass and no need to track what
    an earlier variant touched.
    """
    values: dict[str, float] = {}
    for category, daz_names in ARKIT_TO_DAZ_MORPH.items():
        score = blendshapes.get(category, 0.0) * scale
        for daz_name in daz_names:
            values[daz_name] = score
    return values


def warn_unmapped_categories(blendshapes: dict[str, float], threshold: float = 0.1) -> list[str]:
    """Return UNMAPPED_ARKIT_CATEGORIES entries scored above *threshold* in
    *blendshapes*, sorted -- for the caller to warn about a source photo
    whose expression relies on a category this rig can't represent (e.g. a
    wide-eyed look, whose intensity is otherwise silently dropped).
    """
    return sorted(
        category for category in UNMAPPED_ARKIT_CATEGORIES
        if blendshapes.get(category, 0.0) > threshold
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest test_expression_mapping.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
cd Y:/working/BlueMoonFoundry/daz-script-server-examples
git add ai_vision/pose_transfer_photo/expression_mapping.py ai_vision/pose_transfer_photo/test_expression_mapping.py
git commit -m "feat(expression-capture): add ARKit-to-DAZ facs_bs_* morph mapping"
```

---

## Task 2: `face_landmarks.py` — MediaPipe FaceLandmarker blendshape extraction

**Files:**
- Create: `face_landmarks.py`

**Interfaces:**
- Consumes: nothing from Task 1 (independent extraction step; Task 3 wires
  its output into Task 1's `daz_morph_values`).
- Produces (consumed by Task 3): `extract_blendshapes(image_path: str) -> dict[str, float]`

No automated test file — mirrors `hand_landmarks.py`, which also has none:
this module's only real behavior is a live MediaPipe call, verified manually
(Step 3 below), same as the existing hand-landmark extraction module.

- [ ] **Step 1: Write `face_landmarks.py`**

```python
"""MediaPipe FaceLandmarker blendshape extraction for pose_transfer_photo.py's
--expression-image flag. Mirrors hand_landmarks.py's pattern (auto-downloaded
model, Tasks API) but returns ARKit-style blendshape *scores* directly from
output_face_blendshapes, rather than raw landmark geometry -- see
expression_mapping.py for how these scores map onto Genesis 9's facs_bs_*
morphs.
"""
from __future__ import annotations

import os
import sys
import urllib.request

import cv2
import mediapipe as mp

_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_landmarker/face_landmarker/float16/1/face_landmarker.task"
)
_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "face_landmarker.task")


def _ensure_model() -> str:
    if not os.path.exists(_MODEL_PATH):
        print(f"Downloading face landmarker model -> {_MODEL_PATH}")
        urllib.request.urlretrieve(_MODEL_URL, _MODEL_PATH)
    return _MODEL_PATH


def extract_blendshapes(image_path: str) -> dict[str, float]:
    """Decode an image and return MediaPipe FaceLandmarker's 52 ARKit-style
    blendshape scores (0-1) for the first detected face, keyed by category
    name (e.g. "jawOpen", "mouthSmileLeft").

    Raises SystemExit if the image cannot be loaded or no face is detected.
    Unlike extract_hand_world_landmarks (where a missing hand in an otherwise
    good photo is normal and just means "skip this hand"), an
    --expression-image with no visible face is a real configuration error --
    same severity as extract_world_landmarks' "no pose detected" in the body
    pipeline, not a per-side skip.
    """
    img = cv2.imread(image_path)
    if img is None:
        sys.exit(f"Cannot load image: {image_path!r}")
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    FaceLandmarker = mp.tasks.vision.FaceLandmarker
    FaceLandmarkerOptions = mp.tasks.vision.FaceLandmarkerOptions
    BaseOptions = mp.tasks.BaseOptions
    RunningMode = mp.tasks.vision.RunningMode

    options = FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=_ensure_model()),
        running_mode=RunningMode.IMAGE,
        num_faces=1,
        output_face_blendshapes=True,
    )

    with FaceLandmarker.create_from_options(options) as landmarker:
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = landmarker.detect(mp_image)

    if not result.face_blendshapes:
        sys.exit(f"No face detected in image: {image_path!r}")

    return {category.category_name: category.score for category in result.face_blendshapes[0]}
```

- [ ] **Step 2: Manual smoke test (no DAZ Studio needed yet)**

Run against any photo with a clear, visible face (a selfie-style headshot is
fine):

```bash
cd Y:/working/BlueMoonFoundry/daz-script-server-examples/ai_vision/pose_transfer_photo
python -c "
from face_landmarks import extract_blendshapes
scores = extract_blendshapes('PATH_TO_A_TEST_PHOTO.jpg')
print(len(scores), 'categories')
print(sorted(scores.items(), key=lambda kv: -kv[1])[:5])
"
```

Expected: prints `52 categories` (downloading `face_landmarker.task` to this
directory on first run) and the 5 highest-scoring categories — for a neutral
expression these should all be near 0; for a smiling photo,
`mouthSmileLeft`/`mouthSmileRight` should be prominent.

- [ ] **Step 3: Commit**

```bash
cd Y:/working/BlueMoonFoundry/daz-script-server-examples
git add ai_vision/pose_transfer_photo/face_landmarks.py
git commit -m "feat(expression-capture): add MediaPipe FaceLandmarker blendshape extraction"
```

(`face_landmarker.task` itself is a downloaded binary artifact — check
whether this directory's `.gitignore` already excludes `*.task` the way it
does for `hand_landmarker.task`/`pose_landmarker_lite.task` before staging;
if those two are untracked in `git status`, leave the new one untracked too.)

---

## Task 3: Wire `--expression-image` into `pose_transfer_photo.py`

**Files:**
- Modify: `pose_transfer_photo.py`

**Interfaces:**
- Consumes:
  - `expression_mapping.daz_morph_values(blendshapes, scale) -> dict[str, float]` (Task 1)
  - `expression_mapping.warn_unmapped_categories(blendshapes, threshold) -> list[str]` (Task 1)
  - `face_landmarks.extract_blendshapes(image_path) -> dict[str, float]` (Task 2)
- Produces: `apply_expression(figure, blendshapes: dict[str, float], scale: float) -> None`
  (new function, called only from the main loop added in this task)

No unit test file — this task's logic branches entirely on live DAZ Studio
state (`figure.set_morph_values`, `figure.morph_values`) and the existing
body-pose/finger IK machinery it wires into is already only manually tested
in this file. Verification is a live smoke test (Step 8).

- [ ] **Step 1: Add module-level imports**

In `pose_transfer_photo.py`, find:

```python
from dazpy import DazClient, DazRenderSettings, DazScene
from dazpy.exceptions import DazBusyError
from dazpy.poses import zero_figure
```

Replace with:

```python
from dazpy import DazClient, DazRenderSettings, DazScene
from dazpy.exceptions import DazBusyError
from dazpy.poses import zero_figure

import expression_mapping
import face_landmarks
```

(Unlike `finger_ik`/`hand_landmarks`, which are imported lazily inside
`process_photo()` because `--fingers` additionally requires the separate
Pinocchio conda environment, `face_landmarks`/`expression_mapping` only need
`mediapipe`/`cv2`, already imported unconditionally at the top of this file
— so a top-level import here doesn't add any new always-on dependency.)

- [ ] **Step 2: Add the two new CLI arguments**

Find:

```python
    parser.add_argument("--fingers", action="store_true",
                        help="Also pose fingers from the same photo via MediaPipe HandLandmarker "
                             "(requires --backend pinocchio and wrist targets enabled)")
```

Replace with:

```python
    parser.add_argument("--fingers", action="store_true",
                        help="Also pose fingers from the same photo via MediaPipe HandLandmarker "
                             "(requires --backend pinocchio and wrist targets enabled)")
    parser.add_argument("--expression-image", metavar="PATH", action="append", default=None,
                        help="Extract a facial expression from this image (MediaPipe FaceLandmarker "
                             "blendshapes) and apply it to the figure's facs_bs_*/facs_ctrl_* morphs, "
                             "holding body pose (and --dforce result) fixed. Repeatable -- each path "
                             "produces its own output variant against the SAME solved body pose "
                             "(cross product: every photo x every --expression-image). Omit entirely "
                             "to keep current behavior (no expression touched, one variant per photo).")
    parser.add_argument("--expression-scale", type=float, default=1.0,
                        help="Extra multiplier on extracted blendshape scores before applying "
                             "(default: 1.0), same idea as --scale for body pose.")
```

- [ ] **Step 3: Add `apply_expression()`**

Find the end of `process_photo()` (its `return {...}` statement) followed by
the `# ── batch output actions` section comment:

```python
    return {
        "image": image_path,
        "figure": figure_label,
        "figure_obj": figure,
        "limb_error": final_error,
        "finger_error": finger_errors,
    }


# ── batch output actions ────────────────────────────────────────────────────
```

Insert the new function between them:

```python
    return {
        "image": image_path,
        "figure": figure_label,
        "figure_obj": figure,
        "limb_error": final_error,
        "finger_error": finger_errors,
    }


def apply_expression(figure, blendshapes: dict[str, float], scale: float) -> None:
    """Set figure's facial morphs from extracted MediaPipe blendshape scores.

    Always writes every DAZ morph named in expression_mapping.ARKIT_TO_DAZ_MORPH,
    including zeros for categories absent from *blendshapes* -- this is what
    lets each --expression-image variant in the main loop below start from a
    clean slate without a separate "zero expression" pass or tracking what a
    previous variant touched.
    """
    figure.set_morph_values(expression_mapping.daz_morph_values(blendshapes, scale))


# ── batch output actions ────────────────────────────────────────────────────
```

- [ ] **Step 4: Add a `stem` override to `save_pose_preset`, and capture morphs too**

Find:

```python
def save_pose_preset(figure, image_path: str, output_dir: str) -> str:
    """Save the figure's current pose-channel angles as a small JSON file.

    Not a native DAZ Studio .duf pose preset -- writing one of those goes
    through content-library save dialogs that can pop a blocking modal (see
    this project's own crash notes on live DazScript dialogs), which isn't
    safe to drive unattended across a batch of photos. This captures the
    same information (every posed bone's X/Y/Z rotation) in a format any
    later step can re-apply via `figure.set_bone_rotations()` without going
    near DAZ Studio's UI.
    """
    poses_dir = os.path.join(output_dir, "poses")
    os.makedirs(poses_dir, exist_ok=True)
    path = os.path.join(poses_dir, f"{_stem(image_path)}.json")
    rotations = _call_with_busy_retry(figure.bone_rotations)
    with open(path, "w") as f:
        json.dump({name: list(xyz) for name, xyz in rotations.items()}, f, indent=2)
    return path
```

Replace with:

```python
def save_pose_preset(figure, image_path: str, output_dir: str, *, stem: str | None = None) -> str:
    """Save the figure's current bone rotations AND nonzero morphs as a small JSON file.

    Not a native DAZ Studio .duf pose preset -- writing one of those goes
    through content-library save dialogs that can pop a blocking modal (see
    this project's own crash notes on live DazScript dialogs), which isn't
    safe to drive unattended across a batch of photos. This captures the
    same information any later step needs to reapply the result without
    going near DAZ Studio's UI: every posed bone's X/Y/Z rotation (via
    figure.set_bone_rotations()) plus every currently-nonzero morph (via
    figure.set_morph_values()) -- the latter added alongside
    --expression-image, since a facs_bs_* expression is morph-driven and was
    previously silently dropped from this file entirely.

    *stem* overrides the output filename stem (default: the photo's own
    filename stem) -- used by the --expression-image loop so each expression
    variant of one photo gets its own file instead of overwriting the last.
    """
    poses_dir = os.path.join(output_dir, "poses")
    os.makedirs(poses_dir, exist_ok=True)
    path = os.path.join(poses_dir, f"{stem or _stem(image_path)}.json")
    rotations = _call_with_busy_retry(figure.bone_rotations)
    morphs = _call_with_busy_retry(lambda: figure.morph_values(nonzero_only=True))
    with open(path, "w") as f:
        json.dump({
            "bones": {name: list(xyz) for name, xyz in rotations.items()},
            "morphs": morphs,
        }, f, indent=2)
    return path
```

**Note:** this changes the saved JSON's shape from a flat
`{bone_name: [x, y, z]}` to `{"bones": {...}, "morphs": {...}}`. Confirmed
via `grep -rn "poses/" --include=*.py` across `daz-script-server-examples`
(excluding `.worktrees/`) that nothing in this repo reads these files back —
they're a write-only artifact for external consumption — so this is safe to
change without a migration path.

- [ ] **Step 5: Add a `stem` override to `render_photo` and `export_mesh`**

Find:

```python
def render_photo(
    client: DazClient, image_path: str, output_dir: str, camera_labels: list[str] | None = None
) -> list[str]:
```

Replace its signature line with:

```python
def render_photo(
    client: DazClient, image_path: str, output_dir: str, camera_labels: list[str] | None = None,
    *, stem: str | None = None,
) -> list[str]:
```

A few lines below in the same function, find:

```python
        path = os.path.join(out_dir, f"{_stem(image_path)}.png")
```

Replace with:

```python
        path = os.path.join(out_dir, f"{stem or _stem(image_path)}.png")
```

Then find:

```python
def export_mesh(scene: "DazScene", image_path: str, output_dir: str) -> str:
    meshes_dir = os.path.join(output_dir, "meshes")
    os.makedirs(meshes_dir, exist_ok=True)
    path = os.path.join(meshes_dir, f"{_stem(image_path)}.obj")
    _call_with_busy_retry(lambda: scene.export_obj(path, selected_only=False))
    return path
```

Replace with:

```python
def export_mesh(scene: "DazScene", image_path: str, output_dir: str, *, stem: str | None = None) -> str:
    meshes_dir = os.path.join(output_dir, "meshes")
    os.makedirs(meshes_dir, exist_ok=True)
    path = os.path.join(meshes_dir, f"{stem or _stem(image_path)}.obj")
    _call_with_busy_retry(lambda: scene.export_obj(path, selected_only=False))
    return path
```

- [ ] **Step 6: Add an `expression` column to `write_stats_csv`**

Find:

```python
        writer.writerow(["image", "figure"] + limb_names + ["converged", "note"])
        for r in results:
            row = [r["image"], r["figure"]]
```

Replace with:

```python
        writer.writerow(["image", "figure", "expression"] + limb_names + ["converged", "note"])
        for r in results:
            row = [r["image"], r["figure"], r.get("expression", "")]
```

A few lines below, find:

```python
        for f_ in (failures or []):
            row = [f_["image"], f_["figure"]] + [""] * len(limb_names) + ["error", f_["reason"]]
            writer.writerow(row)
```

Replace with:

```python
        for f_ in (failures or []):
            row = [f_["image"], f_["figure"], ""] + [""] * len(limb_names) + ["error", f_["reason"]]
            writer.writerow(row)
```

- [ ] **Step 7: Restructure the main loop to fan out over expression variants**

Find the entire block from `results: list[dict] = []` through the end of the
`for i, image_path in enumerate(...)` loop body (just before
`if args.stats_csv:`):

```python
    results: list[dict] = []
    failures: list[dict] = []
    for i, image_path in enumerate(image_paths, start=1):
        if args.batch:
            print(f"\n[{i}/{len(image_paths)}] {image_path}")
            figure = _call_with_busy_retry(lambda: scene.find_skeleton_by_label(args.figure))
            _call_with_busy_retry(lambda: zero_figure(figure))

        if args.batch:
            # process_photo() (via extract_world_landmarks()/calibrate()/etc.)
            # uses sys.exit() for per-photo problems like "no pose detected"
            # or "degenerate detection" -- correct for a single-image run
            # (a real error, exit the process), wrong for a batch: one
            # unprocessable photo (extreme crop/angle, occluded figure,
            # stylized art the pose model can't read) shouldn't abort every
            # photo after it. Catch it here, record why, and move on.
            try:
                result = process_photo(image_path, args.figure, scene, client, args)
            except SystemExit as exc:
                reason = str(exc.code) if exc.code is not None else "unknown error"
                print(f"  SKIPPED: {reason}")
                failures.append({"image": image_path, "figure": args.figure, "reason": reason})
                continue
        else:
            result = process_photo(image_path, args.figure, scene, client, args)

        result["tolerance"] = args.tolerance
        results.append(result)

        if args.save_poses:
            path = save_pose_preset(result["figure_obj"], image_path, args.output_dir)
            print(f"  saved pose -> {path}")
        if args.dforce:
            print(f"  simulating dForce ({'memorized' if args.dforce_memorize else 'live'} pose)...")
            _call_with_busy_retry(lambda: simulate_dforce(scene, args.dforce_memorize))
        if args.render:
            paths = render_photo(client, image_path, args.output_dir, args.camera)
            for path in paths:
                print(f"  rendered -> {path}")
        if args.export_mesh:
            path = export_mesh(scene, image_path, args.output_dir)
            print(f"  exported mesh -> {path}")
```

Replace with:

```python
    results: list[dict] = []
    failures: list[dict] = []
    for i, image_path in enumerate(image_paths, start=1):
        if args.batch:
            print(f"\n[{i}/{len(image_paths)}] {image_path}")
            figure = _call_with_busy_retry(lambda: scene.find_skeleton_by_label(args.figure))
            _call_with_busy_retry(lambda: zero_figure(figure))

        if args.batch:
            # process_photo() (via extract_world_landmarks()/calibrate()/etc.)
            # uses sys.exit() for per-photo problems like "no pose detected"
            # or "degenerate detection" -- correct for a single-image run
            # (a real error, exit the process), wrong for a batch: one
            # unprocessable photo (extreme crop/angle, occluded figure,
            # stylized art the pose model can't read) shouldn't abort every
            # photo after it. Catch it here, record why, and move on.
            try:
                result = process_photo(image_path, args.figure, scene, client, args)
            except SystemExit as exc:
                reason = str(exc.code) if exc.code is not None else "unknown error"
                print(f"  SKIPPED: {reason}")
                failures.append({"image": image_path, "figure": args.figure, "reason": reason})
                continue
        else:
            result = process_photo(image_path, args.figure, scene, client, args)

        result["tolerance"] = args.tolerance

        # --dforce runs once per PHOTO, before any expression variant below --
        # re-simulating cloth/hair per expression would multiply the already-
        # dominant dForce wall-clock cost with no physical benefit (expression
        # morphs don't move cloth/hair-relevant geometry).
        if args.dforce:
            print(f"  simulating dForce ({'memorized' if args.dforce_memorize else 'live'} pose)...")
            _call_with_busy_retry(lambda: simulate_dforce(scene, args.dforce_memorize))

        # Fan out over expression variants, each holding the SAME solved body
        # pose (+ dForce result) above fixed. [None] preserves today's single
        # no-expression variant when --expression-image isn't passed at all.
        for expr_path in (args.expression_image or [None]):
            variant_result = dict(result)
            variant_result["expression"] = ""
            variant_stem = _stem(image_path)

            if expr_path is not None:
                variant_stem = f"{variant_stem}__{_stem(expr_path)}"
                variant_result["expression"] = expr_path
                print(f"  Applying expression from {expr_path!r}...")
                # A face-less expression photo is a per-VARIANT skip -- the
                # photo's body pose (and any other expression variants for
                # it) are still valid and should still produce output.
                try:
                    blendshapes = face_landmarks.extract_blendshapes(expr_path)
                except SystemExit as exc:
                    reason = str(exc.code) if exc.code is not None else "unknown error"
                    print(f"    SKIPPED: {reason}")
                    failures.append({
                        "image": image_path, "figure": args.figure,
                        "reason": f"expression {expr_path!r}: {reason}",
                    })
                    continue
                unmapped = expression_mapping.warn_unmapped_categories(blendshapes)
                if unmapped:
                    print(f"    Warning: unmapped ARKit categories with signal: {unmapped}",
                          file=sys.stderr)
                with scene.undo("Apply photo expression"):
                    apply_expression(result["figure_obj"], blendshapes, args.expression_scale)

            results.append(variant_result)

            if args.save_poses:
                path = save_pose_preset(result["figure_obj"], image_path, args.output_dir, stem=variant_stem)
                print(f"  saved pose -> {path}")
            if args.render:
                paths = render_photo(client, image_path, args.output_dir, args.camera, stem=variant_stem)
                for path in paths:
                    print(f"  rendered -> {path}")
            if args.export_mesh:
                path = export_mesh(scene, image_path, args.output_dir, stem=variant_stem)
                print(f"  exported mesh -> {path}")
```

- [ ] **Step 8: Live smoke test**

With DAZ Studio running, the DazScriptServer plugin active, and a scene
containing a Genesis 9 figure zeroed to neutral pose:

```bash
cd Y:/working/BlueMoonFoundry/daz-script-server-examples/ai_vision/pose_transfer_photo
python pose_transfer_photo.py BODY_PHOTO.jpg --figure "Jason Cross" \
    --expression-image SMILING_PHOTO.jpg --save-poses --output-dir smoke_output
```

Expected:
- Body pose applies as before (unchanged console output through the
  "Final per-limb error" section).
- `  Applying expression from ...` prints, no `SKIPPED`/`Warning` lines for a
  clear frontal smiling photo.
- `smoke_output/poses/<body_stem>__<expression_stem>.json` is written and
  contains both a `"bones"` and a `"morphs"` key, the latter with nonzero
  entries for `facs_bs_MouthSmileLeft`/`facs_bs_MouthSmileRight`.
- In DAZ Studio, the figure's face visibly smiles while the body pose is
  unchanged from before the expression was applied.
- Re-run without `--expression-image`: output filename reverts to
  `<body_stem>.json` (no `__` suffix) and the `"morphs"` key is empty/near-
  empty (whatever was already nonzero on the figure at rest) — confirms
  default (no-flag) behavior is otherwise unaffected.

- [ ] **Step 9: Run the existing test suite to confirm nothing broke**

Run: `python -m pytest test_finger_ik.py test_pinocchio_ik.py test_expression_mapping.py -v`
Expected: PASS (import of `pose_transfer_photo` inside `test_finger_ik.py`
must still succeed with the new top-level `expression_mapping`/
`face_landmarks` imports in place)

- [ ] **Step 10: Commit**

```bash
cd Y:/working/BlueMoonFoundry/daz-script-server-examples
git add ai_vision/pose_transfer_photo/pose_transfer_photo.py
git commit -m "feat(expression-capture): add --expression-image to pose_transfer_photo.py"
```

---

## Task 4: Update `README.md`

**Files:**
- Modify: `README.md` (in `ai_vision/pose_transfer_photo/`)

**Interfaces:** none (documentation only)

- [ ] **Step 1: Add expression usage to the Usage section**

Find the existing batch usage block near the end of the README's Usage
section (the `--batch DIR` example with `--save-poses`/`--stats-csv`), and
add directly after it:

```markdown
    # --expression-image PATH: apply a facial expression extracted from a
    # separate photo (MediaPipe FaceLandmarker blendshapes -> Genesis 9
    # facs_bs_*/facs_ctrl_* morphs), holding body pose fixed. Repeatable --
    # each path produces its own output variant against the SAME solved body
    # pose. Combine with --batch for a full N-photos x M-expressions grid.
    python pose_transfer_photo.py photo.jpg \
        --expression-image smile.jpg --expression-image surprised.jpg \
        --save-poses --render --output-dir batch_output/
```

- [ ] **Step 2: Add a short "Facial expression" subsection**

Find the "What You'll Learn" section's bullet list and add one bullet:

```markdown
- Mapping MediaPipe FaceLandmarker's ARKit-style blendshape output onto a
  different rig's own morph vocabulary (Genesis 9's facs_bs_* set splits
  several bilateral ARKit categories into separate Left/Right and/or
  Upper/Lower morphs) via a small static lookup table, rather than assuming
  the two naming schemes line up 1:1
```

- [ ] **Step 3: Commit**

```bash
cd Y:/working/BlueMoonFoundry/daz-script-server-examples
git add ai_vision/pose_transfer_photo/README.md
git commit -m "docs(expression-capture): document --expression-image in pose_transfer_photo README"
```

---

## Task 5: Close out the beads issue

**Files:** none (tracking only)

- [ ] **Step 1: Verify all prior tasks' commits are present**

Run: `cd Y:/working/BlueMoonFoundry/daz-script-server-examples && git log --oneline -5`
Expected: commits from Tasks 1-4 all present, in order.

- [ ] **Step 2: Push the examples repo**

```bash
cd Y:/working/BlueMoonFoundry/daz-script-server-examples
git push
```

- [ ] **Step 3: Close `daz-script-server-hb5t.4`**

```bash
cd Y:/working/BlueMoonFoundry/daz-script-server
bd close daz-script-server-hb5t.4 --reason="Implemented --expression-image in pose_transfer_photo.py: MediaPipe FaceLandmarker blendshapes -> Genesis 9 facs_bs_*/facs_ctrl_* morphs, see docs/superpowers/specs/2026-09-13-expression-capture-design.md and docs/superpowers/plans/2026-09-13-expression-capture.md"
```

- [ ] **Step 4: Push this repo (design/plan docs + beads state)**

```bash
cd Y:/working/BlueMoonFoundry/daz-script-server
git pull --rebase
git push
git status
```

Expected: `git status` shows "up to date with origin".
