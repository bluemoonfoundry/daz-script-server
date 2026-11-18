# Facial expression capture/application from image(s) (design)

Tracked as beads issue `daz-script-server-hb5t.4` (child of epic `daz-script-server-hb5t`:
extend `pose_transfer_photo` with dForce, multi-camera, hand posing, facial expression).

## Context

`pose_transfer_photo.py` (in `daz-script-server-examples/ai_vision/pose_transfer_photo/`)
already extracts body pose (MediaPipe `PoseLandmarker`) and, with `--fingers`,
hand pose (MediaPipe `HandLandmarker`) from a photo and applies both to a
Genesis 9 figure via IK. This design adds a third, independent axis:
**facial expression**, extracted from one or more separate photos and applied
while holding body pose (and any `--dforce` sim result) fixed.

Per the parent issue's own notes, this was the least-scaffolded of the four
planned extensions — no expression-specific dazpy API, no face-landmark
extraction module, and an open question of whether to target expression
morphs or facial bones. A live spike against the running DAZ Studio instance
(figure "Jason Cross", Genesis 9) resolved the open questions below.

## Spike findings

Genesis 9's base rig ships an unprefixed `facs_bs_*`/`facs_ctrl_*` blendshape
set (199 morphs, confirmed present via `figure.morphs()` — not a vendor
add-on) that is essentially Apple ARKit's standard 52-category facial
blendshape set, the same set MediaPipe's `FaceLandmarker` outputs natively.
The two sets don't align name-for-name: DAZ splits several of ARKit's
bilateral categories (`browInnerUp`, `cheekPuff`, `mouthPucker`, `mouthClose`,
`mouthFunnel`, `mouthRollLower/Upper`, `mouthShrugLower/Upper`,
`mouthPressLeft/Right`) into 2-4 separate Left/Right and/or Upper/Lower
morphs. A static mapping table (below) resolves this cleanly: **49 of 52**
ARKit categories map onto DAZ morphs that were verified to exist on the live
figure; the remaining 3 (`eyeWideLeft`, `eyeWideRight`, `tongueOut`) have no
base-rig equivalent (no upper-eyelid-raise blendshape; tongue isn't
blendshape-driven) and are treated as unmapped.

This confirms the representation choice: **expression morphs**, not facial
bones. No new dazpy primitives are needed — `DazSkeleton.set_morph_values(data:
dict[str, float])` (existing, `dazpy/_skeleton.py`) already sets an arbitrary
subset of morphs in one HTTP call.

## Relationship to `ai_vision/expression_transfer/expression_transfer.py`

A pre-existing, actively-maintained standalone example already applies photo
expressions to Genesis 9 (last touched 2026-09-12, 4 commits). It takes a
different technical approach: hand-rolled Action-Unit magnitudes computed
from raw 478-point face-mesh geometry, mapped to **Genesis 9 FACS HD**
property *labels* (e.g. `"AU 01 Inner Brow Raiser Left"`, a separate paid
Daz product) via `property.getLabel()` string matching, applied through raw
DazScript. It covers ~15 AUs and is not integrated into
`pose_transfer_photo.py`'s batch loop at all.

Decision (confirmed with the user 2026-09-13): keep this design as specified
— native MediaPipe `FaceLandmarker` blendshapes mapped to base-rig
`facs_bs_*`/`facs_ctrl_*` morphs (no paid add-on required, verified live,
49/52 ARKit coverage) — and leave `expression_transfer.py` untouched as its
own separate example. The two scripts solve the same problem with
genuinely different techniques and target different morph vocabularies;
forcing shared code between them isn't worth it. Do not reuse
`expression_transfer.py`'s AU computation, FACS_MAP, or `apply_expression()`
in this feature's implementation.

## Goals

- Extract a face's expression from a photo via MediaPipe `FaceLandmarker`'s
  blendshape output.
- Apply it to a Genesis 9 figure's `facs_bs_*`/`facs_ctrl_*` morphs, additively
  after body pose (+ `--dforce`, + `--fingers`) is already solved, without
  perturbing any of that.
- Support one or more `--expression-image` photos per run, each producing its
  own output variant against the *same* solved body pose (cross product:
  N photos x M expression images -> N x M variants when both are batched,
  or 1 x M when a single `--image` is given).
- Fold into the existing `--batch`/`--save-poses`/`--render`/`--export-mesh`/
  `--stats-csv` output machinery without breaking current (no
  `--expression-image`) behavior.

## Non-goals

- Facial bone-driven expression (ERC/bone-based rigs) — flagged in the parent
  issue as a much larger lift; morphs cover the same practical ground for a
  v1 and match MediaPipe's native output shape.
- Video/temporal expression tracking — single still image in, single
  expression state out, same granularity as the existing body-pose path.
- New dazpy primitives — `set_morph_values` already covers what's needed.
- Solving `eyeWideLeft/Right`/`tongueOut` some other way (e.g. finding a
  vendor-specific equivalent morph) — out of scope; documented as unmapped.

## Components

### `face_landmarks.py` (new file, alongside `hand_landmarks.py`)

Mirrors `hand_landmarks.py`'s pattern exactly: MediaPipe Tasks API, auto-
downloaded model file, one function.

```python
def extract_blendshapes(image_path: str) -> dict[str, float]:
    """Decode an image and return MediaPipe FaceLandmarker's 52 blendshape
    scores (0-1) for the first detected face, keyed by ARKit category name.

    Raises SystemExit if the image cannot be loaded or no face is detected
    (an expression-source image with no face is a real config error, same
    severity as "no pose detected" in extract_world_landmarks — unlike a
    missing hand in extract_hand_world_landmarks, there's no legitimate
    "expression photo with no visible face" case to tolerate).
    """
```

Uses `FaceLandmarkerOptions(output_face_blendshapes=True, num_faces=1)`, model
`face_landmarker.task` (Google's official float16 model, same
`storage.googleapis.com/mediapipe-models/...` host as the pose/hand models
already used). Returns `{category.category_name: category.score for category
in result.face_blendshapes[0]}`.

### `expression_mapping.py` (new file)

Pure data + two small pure functions — no DAZ Studio dependency, fully unit-
testable in isolation.

```python
# ARKit category name -> one or more facs_bs_*/facs_ctrl_* DAZ morph names.
# Built and verified against a live Genesis 9 figure ("Jason Cross") on
# 2026-09-13 -- see this file's own module docstring for the verification
# method if the mapping ever needs re-checking against a different generation.
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
    "mouthClose": ["facs_bs_MouthCloseUpperLeft", "facs_bs_MouthCloseUpperRight",
                   "facs_bs_MouthCloseLowerLeft", "facs_bs_MouthCloseLowerRight"],
    "mouthDimpleLeft": ["facs_bs_MouthDimpleLeft"],
    "mouthDimpleRight": ["facs_bs_MouthDimpleRight"],
    "mouthFrownLeft": ["facs_bs_MouthFrownLeft"],
    "mouthFrownRight": ["facs_bs_MouthFrownRight"],
    "mouthFunnel": ["facs_bs_MouthFunnelUpperLeft", "facs_bs_MouthFunnelUpperRight",
                    "facs_bs_MouthFunnelLowerLeft", "facs_bs_MouthFunnelLowerRight"],
    "mouthLeft": ["facs_bs_MouthLeft"],
    "mouthLowerDownLeft": ["facs_bs_MouthLowerDownLeft"],
    "mouthLowerDownRight": ["facs_bs_MouthLowerDownRight"],
    "mouthPressLeft": ["facs_bs_MouthPressUpperLeft", "facs_bs_MouthPressLowerLeft"],
    "mouthPressRight": ["facs_bs_MouthPressUpperRight", "facs_bs_MouthPressLowerRight"],
    "mouthPucker": ["facs_bs_MouthPurseUpperLeft", "facs_bs_MouthPurseUpperRight",
                    "facs_bs_MouthPurseLowerLeft", "facs_bs_MouthPurseLowerRight"],
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

# ARKit categories with no Genesis 9 base-rig equivalent (see module docstring).
UNMAPPED_ARKIT_CATEGORIES = frozenset({"eyeWideLeft", "eyeWideRight", "tongueOut"})


def daz_morph_values(blendshapes: dict[str, float], scale: float = 1.0) -> dict[str, float]:
    """Convert MediaPipe blendshape scores to a DAZ set_morph_values() payload.

    Every DAZ morph named anywhere in ARKIT_TO_DAZ_MORPH is included, even at
    0.0, for categories absent from *blendshapes* or scored 0 -- the caller
    (apply_expression) relies on this to "zero out" a previous expression
    variant with a single set_morph_values() call rather than tracking what
    was previously applied. A category also present in
    UNMAPPED_ARKIT_CATEGORIES is silently ignored (see
    warn_unmapped_categories for the one-time diagnostic).
    """


def warn_unmapped_categories(blendshapes: dict[str, float], threshold: float = 0.1) -> list[str]:
    """Return the subset of UNMAPPED_ARKIT_CATEGORIES scored above *threshold*
    in *blendshapes*, for the caller to print a warning about (e.g. a source
    photo with a wide-eyed expression, whose intensity is silently dropped).
    """
```

### `apply_expression` (new function in `pose_transfer_photo.py`)

```python
def apply_expression(figure, blendshapes: dict[str, float], scale: float) -> None:
    """Set figure's facial morphs from extracted blendshape scores.

    Always writes every mapped DAZ morph (see daz_morph_values) in one
    set_morph_values() call, including zeros -- this is what lets each
    expression variant in the cross-product loop start from a clean slate
    without a separate "zero expression" pass or tracking what the previous
    variant touched.
    """
    figure.set_morph_values(expression_mapping.daz_morph_values(blendshapes, scale))
```

Wrapped in `scene.undo("Apply photo expression")` at the call site, same
pattern as the finger-pose block.

## CLI integration

New arguments:

```
--expression-image PATH   (repeatable / action="append")
    One or more source images to extract a facial expression from and apply
    to the figure, holding body pose (and --dforce result) fixed. Each
    produces its own output variant. Omit to keep current behavior
    unchanged (no expression touched).

--expression-scale FLOAT  (default 1.0)
    Extra multiplier on extracted blendshape scores before applying, same
    idea as --scale for body pose.
```

### `process_photo()` restructuring

Body pose (+ `--fingers`) solve and `--dforce` simulation stay exactly as
today, running once per photo. What follows becomes a loop over expression
variants:

```python
expression_images = args.expression_image or [None]   # [None] = today's single no-expression variant
for expr_path in expression_images:
    variant_stem = _stem(image_path) if expr_path is None else f"{_stem(image_path)}__{_stem(expr_path)}"
    if expr_path is not None:
        print(f"  Applying expression from {expr_path!r}...")
        blendshapes = face_landmarks.extract_blendshapes(expr_path)
        unmapped = expression_mapping.warn_unmapped_categories(blendshapes)
        if unmapped:
            print(f"    Warning: unmapped ARKit categories with signal: {unmapped}", file=sys.stderr)
        with scene.undo("Apply photo expression"):
            apply_expression(figure, blendshapes, args.expression_scale)
    # existing --save-poses / --render / --export-mesh calls move here,
    # keyed by variant_stem instead of _stem(image_path) directly
```

`--dforce` is deliberately **outside** this loop (runs once per photo, before
it) — re-simulating cloth/hair per expression variant would multiply the
already-dominant dForce wall-clock cost by M for no physical benefit
(expression doesn't move cloth/hair-relevant geometry).

`save_pose_preset`/`render_photo`/`export_mesh` take `variant_stem` in place
of deriving `_stem(image_path)` internally — smallest-diff way to keep their
existing "one file per photo" contract while supporting "one file per
photo x expression variant."

### Batch failure handling

A `--batch` photo where body-pose extraction fails is skipped today (existing
`SystemExit` catch). An expression image with no detected face is a **per-
variant** skip within an otherwise-successful photo (`process_photo` catches
it around each iteration of the expression loop, not the whole function) —
mirrors how a missing body pose vs. a missing hand are already handled at
different granularities in the existing code.

### `--stats-csv`

Add an `expression` column (source expression image path, or empty for the
no-expression variant) so each row still identifies exactly one output
variant.

## Testing

- **Unit** (`test_expression_mapping.py`, no DAZ Studio needed): every
  `ARKIT_TO_DAZ_MORPH` value is a non-empty list; the key set plus
  `UNMAPPED_ARKIT_CATEGORIES` equals the full 52-category ARKit set (catches
  silent drops if MediaPipe's category list ever changes); `daz_morph_values`
  zeros every mapped morph even when `blendshapes` is empty or partial;
  `warn_unmapped_categories` respects `threshold`.
- **Live smoke test** (manual, mirrors this design's own spike): apply a
  known-expression photo (e.g. a clear smile) via the live server, read back
  `figure.morph_values()` for `facs_bs_MouthSmileLeft/Right`, confirm nonzero.
- No new coverage needed in `daz-script-server`'s own C++ test suite — this
  entire feature lives in the Python examples repo and touches no server-
  side code (`set_morph_values` already exists and is exercised).

## Open items for the implementation plan

- Exact MediaPipe model URL/filename for `face_landmarker.task` (float16
  variant, same host pattern as pose/hand models) — confirm the current
  canonical URL when implementing, models are occasionally revisioned.
- Decide whether `--expression-image` should validate face-detection success
  for *all* images up front (like `--camera` validates labels before the
  batch starts) or lazily per-variant (like body-pose failures today) — this
  design assumes lazy/per-variant, consistent with existing error handling,
  but worth confirming during planning.
