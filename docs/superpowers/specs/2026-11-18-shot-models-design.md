# Typed Shot / Sequence / CoveragePlan models — Design

**Issue:** daz-script-server-5d6f.19 (ASSESSMENT #11) · **Date:** 2026-11-18
**Depends on:** 5d6f.18 (scene recipes, shipped 2.12.0) · **Unblocks:** 5d6f.20 (shot library)

The user opted out of the design Q&A ("skip the questions and just start"), so
every decision below is the builder's call and is marked as such where it isn't
obvious from the code.

## 1. Intent

`dazpy/cinematics.py` has four separate, untyped-ish shot builders
(`CinematicStaticShot`, `OrbitCamera`, `FrameSubject`, `CinematicAnimatedShot`).
Recipe cameras (`_recipe_desired._camera`) have their own framing maths. Nothing
describes a *shot* as a whole: what it frames, how big, from what angle, through
what lens, how the camera moves, where focus goes, what it's for, and where it
renders. 5d6f.20 (OTS, shot/reverse, 180-degree rule, dolly/crane, rack focus)
needs that vocabulary to build on.

## 2. Goals / non-goals

**Goals (acceptance):**
- Typed, frozen, JSON-serialisable models: `Shot`, `Sequence`, `CoveragePlan`
  and their parts (lens, framing, placement, movement, focus pull, composition,
  blocking/gaze beats, lighting continuity, storyboard metadata, render output).
- Usable inside recipes: a static `Shot` / `CoveragePlan` converts to recipe
  `cameras` + `shots` entries, and a recipe camera converts to a `Shot`.
- One apply path, `apply_shot()`. The four existing builders keep their exact
  public API and behaviour but become thin adapters (`to_shot()` + `apply_shot`).
- Recipe camera framing and `apply_shot` framing share one geometry function.

**Non-goals (later issues):**
- Shot-library presets and coverage rules (OTS, 180-degree enforcement,
  dolly/crane builders) — 5d6f.20. `CoveragePlan.axis` is stored so .20 can
  enforce it.
- Animated cameras inside recipes. `shots[].movement` stays reserved in
  recipe_version 1; converting a moving shot or a focus pull to a recipe raises
  `ValueError`.
- Applying blocking/gaze beats and lighting continuity to the scene. They are
  data carried by the models for planners and later work; `apply_shot` ignores
  them (documented).
- Dutch/roll angles (would need live verification of Daz's camera Euler order).
- Pre-render framing checks — 5d6f.22.

## 3. Module and models (builder's call)

New public module `dazpy/shots.py`, re-exported from `dazpy`.

Targets are `str` (an actor/prop key, resolved through a `subjects` mapping at
apply time), `Vec3`, or a `DazNode`. A `DazNode` target is not serialisable:
`to_dict()` raises `TypeError` naming the field.

| Model | Fields |
|---|---|
| `Lens` | `focal_length=50`, `depth_of_field=False`, `focal_distance=None`, `f_stop=None` |
| `Framing` | `subjects` (1+ targets), `size` (`ShotSize`), `angle` (`CameraAngle`), `azimuth_deg=0`, `elevation_deg=None` (overrides `angle`), `composition` (`center`/`left_third`/`right_third`), `distance_cm=None` (overrides size fit), `anchor_cm=None` (overrides size anchor) |
| `Placement` | `position`, `look_at=None`, `look_at_offset_cm=0`, `rotation=None` |
| `Orbit` (movement) | `radius`, `elevation_deg=15`, `start_azimuth_deg=0`, `end_azimuth_deg=360`, `frame_start=0`, `frame_end=90`, `target_offset_cm=25`; target = the shot's subject |
| `Keyframed` (movement) | `keyframes: tuple[CameraKeyframe, ...]` (existing type, moved to `shots.py`, still importable from `cinematics`) |
| `FocusPull` | `keys: tuple[FocusKey(frame, focal_distance), ...]` (2+, ascending) |
| `GazeBeat` | `frame`, `actor` (key), `look_at` (target) |
| `BlockingBeat` | `frame`, `actor`, `position`, `facing=None`, `note=None` |
| `Storyboard` | `description=None`, `dialogue=None`, `beat=None`, `notes=None` |
| `RenderOutput` | `path`, `engine=None`, `resolution=None`, `iray_samples=None` |
| `Shot` | `id`, `camera: Framing \| Placement`, `lens`, `movement: None \| Orbit \| Keyframed`, `focus: FocusPull \| None`, `frame_range=None`, `aspect=None` (aspect/pixels from `CinematicStaticShot`), `blocking`, `gaze`, `lighting=None` (continuity key: names the lighting setup/rig the shot must match), `storyboard`, `output` |
| `Sequence` | `id`, `shots` (unique ids), `lighting=None`, `storyboard` |
| `CoveragePlan` | `id`, `subjects` (keys), `axis=None` (two subject keys = the line of action), `sequences`, `lighting=None`, `storyboard`; `all_shots()` |

`ShotSize`: `extreme_wide`, `wide`, `full_body`, `medium_wide`, `medium`,
`medium_close_up`, `close_up`, `extreme_close_up`. Each maps to a fit height
(cm of subject filling the frame vertically) and an anchor height (cm above the
actor root to aim at), extending the recipe's existing three-entry tables
without changing them (`full_body` 210/90, `medium` 100/130, `close_up` 40/160).

`CameraAngle` → elevation: `eye_level` 0, `high` 30, `low` −20, `birds_eye` 80,
`worms_eye` −45. Default `eye_level`. Recipe cameras keep their 10° default
elevation when `angle` is absent.

Serialisation: every model has `to_dict()` / `from_dict()`; union fields carry
a `kind` discriminator (`framing`/`placement`, `orbit`/`keyframed`); `Vec3`
serialises as `[x, y, z]`; default-valued fields are omitted (like
`SceneRecipe.to_dict`). `from_dict` rejects unknown fields and bad enums with
`ValueError` naming the dotted path.

## 4. Apply

`apply_shot(scene, shot, *, camera=None, name=None, subjects=None, frame_width_mm=36, aspect=3/4)`:

- **Framing**: aim = centroid of subjects (actor keys and `DazNode`s raised by
  the size's anchor; `Vec3` raised by `anchor_cm` only when given). Distance =
  `distance_cm` or `fit_height * focal / (frame_width_mm * aspect)` — the
  recipe formula. Composition shifts the aim point sideways by
  `distance * frame_width_mm / focal / 6` along camera-right so the subject sits
  on a third. Then `set_position` + `aim_at`.
- **Placement**: exactly what `apply_static_shot` does today.
- **Orbit / Keyframed**: exactly what `apply_orbit_camera` /
  `apply_animated_shot` do today.
- Lens, then aspect/pixels, applied as today. `f_stop` via `DazCamera.f_stop`.
- **FocusPull**: new `DazCamera.set_focal_distance_at_frame(frame, d)` and
  `clear_focal_distance_keys()` (via `getFocalDistanceControl()`); clears then
  writes one key per `FocusKey`, and turns DOF on.

The adapters: `FrameSubject` → `Framing` with `distance_cm` from its fixed
table and `anchor_cm` from its offset table (its distance is focal-independent,
and that's kept). Call order on the camera is preserved so the existing
`tests/test_dazpy.py` cinematics tests pass untouched.

## 5. Recipes

- Additive v1 schema change (no version bump, per the recipe design's rule):
  `cameras.*.shot_type` accepts the full `ShotSize` list; new optional
  `cameras.*.angle` (mutually exclusive with `elevation_deg`) and
  `cameras.*.composition`, framing cameras only. Both schema copies are updated
  together (the existing parity test guards that).
- `_recipe_desired._camera` computes framing through
  `shots.framing_transform()` — the same function `apply_shot` uses.
- `Shot.to_recipe(key)` → `(camera_dict, shot_dict | None)`; subjects must be
  keys or `Vec3` literals, movement/focus must be absent. `shot_from_recipe_camera(key, cam_dict)` goes the other way.
  `CoveragePlan.to_recipe_sections()` → `{"cameras": {...}, "shots": [...]}`;
  `merge_into_recipe(recipe_dict)` returns a new dict and raises on key clashes.
  Storyboard/blocking/gaze/lighting metadata is dropped in conversion (recipes
  have nowhere to put it in v1) — documented.

## 6. Tests and docs

- New `tests/test_shots.py` (unit, no Studio): round-trip every model,
  rejection paths, framing geometry vs the recipe tables, composition offset
  direction, focus pull calls, recipe conversion + `validate_offline` of the
  result, adapters producing the same calls as before.
- Existing cinematics tests in `tests/test_dazpy.py` and the recipe unit tests
  (`tests/test_recipe_*.py` minus live) must pass unchanged.
- One scoped live check if Studio is up: apply a focus pull on DS4/DS6 and read
  the keys back.
- Docs: `docs/api` entry for `dazpy.shots`, scene recipe page lists the new
  camera fields, CHANGELOG entry.
