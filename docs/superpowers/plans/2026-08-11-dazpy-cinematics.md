# dazpy.cinematics (Static Shots Slice) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `dazpy.cinematics` with `CinematicStaticShot`, `OrbitCamera`, and `FrameSubject` — static/per-frame camera placement built on existing `DazCamera`/`DazScene`/`DazTimeline` primitives, with a hip-joint-clipping-safe default framing offset.

**Architecture:** Extract the spherical-placement math (`_spherical_offset`, `_look_at_euler`, target resolution) that already lives in `dazpy/lighting.py` into a new shared private module `dazpy/_shot_geometry.py`, extending target resolution with a `vertical_offset_cm` parameter. Then build `dazpy/cinematics.py` on top of it, following the frozen-dataclass-spec + `apply_*` function convention already used by `dazpy/lighting.py` and `dazpy/poses.py`.

**Tech Stack:** Python 3.10+ (dataclasses, `from __future__ import annotations`), `unittest` (mock-client style tests in `tests/test_dazpy.py`), no new third-party dependencies.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-11-dazpy-cinematics-design.md` — every task below implements a section of it.
- No new DazScript surface — only `DazScene.create_camera`, `DazCamera` optics properties, `DazNode.set_position`/`set_rotation`, `DazCamera.aim_at`, `DazTimeline.frame`, and `Vec3` math.
- `CinematicAnimatedShot` is explicitly out of scope for this plan (separate follow-up issue).
- Existing `dazpy.lighting` public behavior and its test assertions must be unaffected by the `_shot_geometry.py` extraction — only the internal helper location changes.
- Follow existing conventions: frozen `@dataclass`, private module-level helpers prefixed `_` where module-private, mock-client-style tests with fake camera/scene classes (see `_FakeLightingLight`/`_FakeLightingScene` in `tests/test_dazpy.py` around line 5562).
- Beads issue: `daz-script-server-p1af`. Do not close it after this plan — `dazpy.materials` and `CinematicAnimatedShot` remain open follow-ups.

---

## File Structure

- **Create:** `dazpy/_shot_geometry.py` — shared spherical-placement math (`spherical_offset`, `look_at_euler`, `resolve_target`), extracted from `dazpy/lighting.py`.
- **Modify:** `dazpy/lighting.py` — replace its local `_spherical_offset`/`_look_at_euler`/`_resolve_target` definitions with imports from `_shot_geometry.py` (aliased back to the same private names so its own call sites and any external `from dazpy.lighting import _spherical_offset` usage keep working unchanged).
- **Create:** `dazpy/cinematics.py` — `CinematicStaticShot`, `OrbitCamera`, `FrameSubject` dataclasses; `apply_static_shot`, `apply_orbit_camera`, `apply_frame_subject` functions; private `_resolve_camera` helper.
- **Modify:** `dazpy/__init__.py` — export the six new `cinematics` symbols.
- **Modify:** `tests/test_dazpy.py` — move `TestLightingMath`'s pure-math tests to a new `TestShotGeometryMath` class importing from `dazpy._shot_geometry`, add `resolve_target` offset tests, add `TestCinematicStaticShot`, `TestOrbitCamera`, `TestFrameSubject`, `TestCinematicsExports` classes.

---

## Task 1: Extract shared shot-geometry math into `dazpy/_shot_geometry.py`

**Files:**
- Create: `dazpy/_shot_geometry.py`
- Modify: `dazpy/lighting.py:1-65` (imports and the three helper function definitions)
- Test: `tests/test_dazpy.py` (replace `TestLightingMath` class, ~line 5497-5559)

**Interfaces:**
- Consumes: `dazpy.math3.Vec3` (existing), `dazpy._node.DazNode` (existing, for `TYPE_CHECKING` only).
- Produces: `dazpy._shot_geometry.spherical_offset(target: Vec3, azimuth_deg: float, elevation_deg: float, distance: float) -> Vec3`, `dazpy._shot_geometry.look_at_euler(from_pos: Vec3, to_pos: Vec3) -> tuple[float, float, float]`, `dazpy._shot_geometry.resolve_target(target: Vec3 | DazNode, vertical_offset_cm: float = 0.0) -> Vec3`. These three names are what Tasks 2-4 import.

- [ ] **Step 1: Write the failing tests for the new module**

Open `tests/test_dazpy.py`, find the `class TestLightingMath(unittest.TestCase):` block (currently ~line 5497) running through `test_look_at_euler_handles_directly_above_without_error` (~line 5559, just before `class _FakeLightingLight`). Replace that entire class with:

```python
class TestShotGeometryMath(unittest.TestCase):
    def test_spherical_offset_at_zero_azimuth_elevation(self):
        from dazpy._shot_geometry import spherical_offset
        from dazpy.math3 import Vec3
        result = spherical_offset(Vec3(0, 0, 0), azimuth_deg=0.0, elevation_deg=0.0, distance=150.0)
        self.assertAlmostEqual(result.x, 0.0, places=6)
        self.assertAlmostEqual(result.y, 0.0, places=6)
        self.assertAlmostEqual(result.z, 150.0, places=6)

    def test_spherical_offset_at_90_azimuth(self):
        from dazpy._shot_geometry import spherical_offset
        from dazpy.math3 import Vec3
        result = spherical_offset(Vec3(0, 0, 0), azimuth_deg=90.0, elevation_deg=0.0, distance=150.0)
        self.assertAlmostEqual(result.x, 150.0, places=6)
        self.assertAlmostEqual(result.y, 0.0, places=6)
        self.assertAlmostEqual(result.z, 0.0, places=6)

    def test_spherical_offset_at_90_elevation_ignores_azimuth(self):
        from dazpy._shot_geometry import spherical_offset
        from dazpy.math3 import Vec3
        result = spherical_offset(Vec3(0, 0, 0), azimuth_deg=45.0, elevation_deg=90.0, distance=150.0)
        self.assertAlmostEqual(result.x, 0.0, places=6)
        self.assertAlmostEqual(result.y, 150.0, places=6)
        self.assertAlmostEqual(result.z, 0.0, places=6)

    def test_spherical_offset_is_relative_to_target(self):
        from dazpy._shot_geometry import spherical_offset
        from dazpy.math3 import Vec3
        result = spherical_offset(Vec3(10, 20, 30), azimuth_deg=0.0, elevation_deg=0.0, distance=150.0)
        self.assertAlmostEqual(result.x, 10.0, places=6)
        self.assertAlmostEqual(result.y, 20.0, places=6)
        self.assertAlmostEqual(result.z, 180.0, places=6)

    def test_look_at_euler_default_offset_is_zero_rotation(self):
        from dazpy._shot_geometry import look_at_euler
        from dazpy.math3 import Vec3
        x, y, z = look_at_euler(Vec3(0, 0, 150), Vec3(0, 0, 0))
        self.assertAlmostEqual(x, 0.0, places=6)
        self.assertAlmostEqual(y, 0.0, places=6)
        self.assertAlmostEqual(z, 0.0, places=6)

    def test_look_at_euler_yaws_toward_90_azimuth_offset(self):
        from dazpy._shot_geometry import look_at_euler
        from dazpy.math3 import Vec3
        x, y, z = look_at_euler(Vec3(150, 0, 0), Vec3(0, 0, 0))
        self.assertAlmostEqual(x, 0.0, places=6)
        self.assertAlmostEqual(y, 90.0, places=6)
        self.assertAlmostEqual(z, 0.0, places=6)

    def test_look_at_euler_pitches_up_when_light_is_above(self):
        from dazpy._shot_geometry import look_at_euler
        from dazpy.math3 import Vec3
        x, y, z = look_at_euler(Vec3(0, 150, 0), Vec3(0, 0, 0))
        self.assertAlmostEqual(x, -90.0, places=6)
        self.assertAlmostEqual(z, 0.0, places=6)

    def test_look_at_euler_handles_directly_above_without_error(self):
        # Degenerate case: horizontal component is exactly zero, yaw must
        # default to 0.0 rather than raising or returning NaN.
        from dazpy._shot_geometry import look_at_euler
        from dazpy.math3 import Vec3
        x, y, z = look_at_euler(Vec3(0, 150, 0), Vec3(0, 0, 0))
        self.assertEqual(y, 0.0)

    def test_resolve_target_returns_vec3_unchanged_with_zero_offset(self):
        from dazpy._shot_geometry import resolve_target
        from dazpy.math3 import Vec3
        result = resolve_target(Vec3(10, 20, 30))
        self.assertAlmostEqual(result.x, 10.0, places=6)
        self.assertAlmostEqual(result.y, 20.0, places=6)
        self.assertAlmostEqual(result.z, 30.0, places=6)

    def test_resolve_target_applies_vertical_offset_to_vec3(self):
        from dazpy._shot_geometry import resolve_target
        from dazpy.math3 import Vec3
        result = resolve_target(Vec3(10, 20, 30), vertical_offset_cm=25.0)
        self.assertAlmostEqual(result.x, 10.0, places=6)
        self.assertAlmostEqual(result.y, 45.0, places=6)
        self.assertAlmostEqual(result.z, 30.0, places=6)

    def test_resolve_target_applies_vertical_offset_to_daznode_position(self):
        from dazpy._shot_geometry import resolve_target

        class _Node:
            position = {"x": 1.0, "y": 2.0, "z": 3.0}

        result = resolve_target(_Node(), vertical_offset_cm=10.0)
        self.assertAlmostEqual(result.x, 1.0, places=6)
        self.assertAlmostEqual(result.y, 12.0, places=6)
        self.assertAlmostEqual(result.z, 3.0, places=6)

    def test_resolve_target_raises_value_error_when_node_has_no_position(self):
        from dazpy._shot_geometry import resolve_target

        class _DeletedNode:
            position = None

        with self.assertRaisesRegex(ValueError, "no position"):
            resolve_target(_DeletedNode())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_dazpy.py::TestShotGeometryMath -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dazpy._shot_geometry'` (or `ImportError`).

- [ ] **Step 3: Create `dazpy/_shot_geometry.py`**

```python
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from .math3 import Vec3

if TYPE_CHECKING:
    from ._node import DazNode


def spherical_offset(
    target: Vec3, azimuth_deg: float, elevation_deg: float, distance: float
) -> Vec3:
    """Return a point *distance* away from *target*, at the given angles.

    ``azimuth_deg=0, elevation_deg=0`` sits on the target's ``+Z`` side.
    Increasing ``azimuth_deg`` sweeps from ``+Z`` toward ``+X``.
    ``elevation_deg`` tilts the offset up toward ``+Y``; at ``elevation_deg=90``
    the result is directly above the target regardless of azimuth.
    """
    az = math.radians(azimuth_deg)
    el = math.radians(elevation_deg)
    horizontal = math.cos(el)
    direction = Vec3(horizontal * math.sin(az), math.sin(el), horizontal * math.cos(az))
    return target + direction * distance


def look_at_euler(from_pos: Vec3, to_pos: Vec3) -> tuple[float, float, float]:
    """Return ``(x, y, z)`` world-space Euler degrees aiming *from_pos* at *to_pos*.

    Suitable for passing directly to :meth:`~dazpy.DazNode.set_rotation`. A
    node positioned via :func:`spherical_offset` with ``azimuth_deg=0,
    elevation_deg=0`` and aimed with this function at the same target gets
    rotation ``(0, 0, 0)`` — i.e. the unrotated rest pose is defined as
    facing ``-Z``. Roll (``z``) is always ``0.0``.

    The yaw sign was confirmed empirically against a live DAZ Studio session
    (see beads issue daz-script-server-bu86): a distant light rotated to
    ``y=+90`` reports :meth:`~dazpy.DazLight.direction` of ``(-1, 0, ~0)``,
    matching this function's convention.
    """
    direction = (to_pos - from_pos).normalize()
    horizontal_dist = math.sqrt(direction.x * direction.x + direction.z * direction.z)
    pitch = math.degrees(math.atan2(direction.y, horizontal_dist))
    if horizontal_dist < 1e-9:
        yaw = 0.0
    else:
        yaw = math.degrees(math.atan2(-direction.x, -direction.z))
    return (pitch, yaw, 0.0)


def resolve_target(target: "Vec3 | DazNode", vertical_offset_cm: float = 0.0) -> Vec3:
    """Resolve *target* to a :class:`~dazpy.math3.Vec3`, raised by *vertical_offset_cm*.

    If *target* is already a :class:`~dazpy.math3.Vec3`, it is used as-is
    (before the offset). If it's a :class:`~dazpy.DazNode`, its
    :attr:`~dazpy.DazNode.position` is read and converted via
    :meth:`~dazpy.math3.Vec3.from_dict`.

    *vertical_offset_cm* is added to the resolved Y (DAZ Studio's up axis)
    component. This exists primarily to compensate for the fact that a
    figure's :class:`~dazpy.DazNode.position` is generally its root/hip
    joint, not its center of mass or head — framing code that wants to aim
    higher (e.g. chest/head height for a tight shot) passes a positive
    offset here rather than aiming straight at the hip.

    Raises:
        ValueError: If *target* is a node and its position is unavailable
            (e.g. the node no longer exists in the scene).
    """
    if isinstance(target, Vec3):
        base = target
    else:
        position = target.position
        if position is None:
            raise ValueError("resolve_target: target node has no position (it may not exist in the scene)")
        base = Vec3.from_dict(position)
    if vertical_offset_cm == 0.0:
        return base
    return Vec3(base.x, base.y + vertical_offset_cm, base.z)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_dazpy.py::TestShotGeometryMath -v`
Expected: PASS (12 tests).

- [ ] **Step 5: Refactor `dazpy/lighting.py` to use the shared module**

Open `dazpy/lighting.py`. Replace lines 1-65 (module docstring imports through the end of `_look_at_euler`, i.e. everything up to but not including `@dataclass(frozen=True)\nclass LightSpec:`) with:

```python
"""Domain-level lighting rigs built on the DazLight/DazScene primitives.

Provides :func:`apply_three_point_light_setup` for creating a conventional
key/fill/rim light rig around a target, either via angle/distance placement
or explicit world-space positions. Also provides :func:`apply_hdri_environment`
for image-based (HDRI/dome) lighting via :class:`HDRIEnvironment`.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .exceptions import RenderError
from .math3 import Vec3
from ._shot_geometry import spherical_offset as _spherical_offset
from ._shot_geometry import look_at_euler as _look_at_euler

if TYPE_CHECKING:
    from ._light import DazLight
    from ._node import DazNode
    from ._render import DazRenderSettings
    from ._scene import DazScene
```

This drops the local `_spherical_offset`/`_look_at_euler` function bodies
entirely (they now live in `_shot_geometry.py`) while keeping the same
private names available at `dazpy.lighting._spherical_offset` /
`dazpy.lighting._look_at_euler`, so every other call site in
`lighting.py` (e.g. `_place_light`) and any existing test that does
`from dazpy.lighting import ThreePointLightSetup, apply_three_point_light_setup, _spherical_offset`
keeps working unchanged.

Do **not** touch `_resolve_target` in `lighting.py` (the function starting
`def _resolve_target(target: Vec3 | DazNode) -> Vec3:`) — leave it defined
locally as-is. `lighting.py` doesn't need the new `vertical_offset_cm`
parameter, and its existing tests (`test_apply_resolves_dazNode_target_via_position`,
`test_apply_raises_value_error_when_target_node_has_no_position`) assert
against this exact local function, so replacing it risks a signature/behavior
mismatch for no benefit — light rigs don't have a hip-clipping problem to fix.

- [ ] **Step 6: Run the full lighting + shot-geometry test suite**

Run: `python -m pytest tests/test_dazpy.py::TestShotGeometryMath tests/test_dazpy.py::TestThreePointLightSetup tests/test_dazpy.py::TestHDRIEnvironment tests/test_dazpy.py::TestLightingExports -v`
Expected: PASS, all tests green (no regressions in existing lighting behavior).

- [ ] **Step 7: Commit**

```bash
git add dazpy/_shot_geometry.py dazpy/lighting.py tests/test_dazpy.py
git commit -m "$(cat <<'EOF'
refactor(dazpy): extract shot-placement math into _shot_geometry.py

Moves spherical_offset/look_at_euler out of lighting.py into a shared
module so cinematics.py can reuse them without duplicating the math.
Adds resolve_target(vertical_offset_cm=...) for cinematics' hip-joint
framing fix; lighting.py's own _resolve_target is left untouched since
it has no clipping problem to solve.
EOF
)"
```

---

## Task 2: `CinematicStaticShot` and `apply_static_shot`

**Files:**
- Create: `dazpy/cinematics.py`
- Test: `tests/test_dazpy.py` (new classes, appended after the lighting test classes / before `if __name__ == "__main__":`)

**Interfaces:**
- Consumes: `dazpy._shot_geometry.resolve_target` (Task 1), `dazpy.math3.Vec3` (existing), `dazpy._scene.DazScene` / `dazpy._camera.DazCamera` (existing, `TYPE_CHECKING` only).
- Produces: `dazpy.cinematics.CinematicStaticShot` dataclass, `dazpy.cinematics.apply_static_shot(scene, shot, *, camera=None, name=None) -> DazCamera`, private `dazpy.cinematics._resolve_camera(scene, camera, name) -> DazCamera` (used by Tasks 3 and 4 too).

- [ ] **Step 1: Write the failing tests**

Add near the end of `tests/test_dazpy.py`, just before `if __name__ == "__main__":`:

```python
class _FakeCinematicsCamera:
    def __init__(self, name: str | None = None):
        self.name = name
        self.position_calls: list[tuple[float, float, float]] = []
        self.rotation_calls: list[tuple[float, float, float]] = []
        self.aim_at_calls: list[tuple[float, float, float]] = []
        self.focal_length: float | None = None
        self.depth_of_field: bool | None = None
        self.focal_distance: float | None = None
        self.aspect_width: float | None = None
        self.aspect_height: float | None = None
        self.pixels_width: int | None = None
        self.pixels_height: int | None = None
        self._client = MagicMock()

    def set_position(self, x, y, z):
        self.position_calls.append((x, y, z))

    def set_rotation(self, x, y, z):
        self.rotation_calls.append((x, y, z))

    def aim_at(self, x, y, z):
        self.aim_at_calls.append((x, y, z))


class _FakeCinematicsScene:
    def __init__(self):
        self.created: list[_FakeCinematicsCamera] = []

    def create_camera(self, name: str | None = None) -> _FakeCinematicsCamera:
        cam = _FakeCinematicsCamera(name)
        self.created.append(cam)
        return cam


class TestCinematicStaticShot(unittest.TestCase):
    def test_defaults(self):
        from dazpy.cinematics import CinematicStaticShot
        from dazpy.math3 import Vec3
        shot = CinematicStaticShot(position=Vec3(0, 0, 150))
        self.assertIsNone(shot.look_at)
        self.assertEqual(shot.look_at_offset_cm, 0.0)
        self.assertIsNone(shot.rotation)
        self.assertEqual(shot.focal_length, 50.0)
        self.assertFalse(shot.depth_of_field)
        self.assertIsNone(shot.focal_distance)
        self.assertIsNone(shot.aspect_width)
        self.assertIsNone(shot.aspect_height)
        self.assertIsNone(shot.pixels_width)
        self.assertIsNone(shot.pixels_height)

    def test_is_frozen(self):
        from dazpy.cinematics import CinematicStaticShot
        from dazpy.math3 import Vec3
        shot = CinematicStaticShot(position=Vec3(0, 0, 150))
        with self.assertRaises(Exception):
            shot.focal_length = 85.0

    def test_apply_creates_new_camera_when_none_given(self):
        from dazpy.cinematics import CinematicStaticShot, apply_static_shot
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        shot = CinematicStaticShot(position=Vec3(0, 0, 150))
        cam = apply_static_shot(scene, shot, name="Shot 1")
        self.assertEqual(len(scene.created), 1)
        self.assertIs(cam, scene.created[0])
        self.assertEqual(cam.name, "Shot 1")

    def test_apply_reuses_given_camera(self):
        from dazpy.cinematics import CinematicStaticShot, apply_static_shot
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        existing = _FakeCinematicsCamera("MyCam")
        shot = CinematicStaticShot(position=Vec3(0, 0, 150))
        cam = apply_static_shot(scene, shot, camera=existing)
        self.assertIs(cam, existing)
        self.assertEqual(len(scene.created), 0)

    def test_apply_sets_position(self):
        from dazpy.cinematics import CinematicStaticShot, apply_static_shot
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        shot = CinematicStaticShot(position=Vec3(1.0, 2.0, 3.0))
        cam = apply_static_shot(scene, shot)
        self.assertEqual(cam.position_calls, [(1.0, 2.0, 3.0)])

    def test_apply_calls_aim_at_when_look_at_vec3_given(self):
        from dazpy.cinematics import CinematicStaticShot, apply_static_shot
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        shot = CinematicStaticShot(position=Vec3(0, 0, 150), look_at=Vec3(0, 0, 0))
        cam = apply_static_shot(scene, shot)
        self.assertEqual(cam.aim_at_calls, [(0.0, 0.0, 0.0)])
        self.assertEqual(cam.rotation_calls, [])

    def test_apply_applies_look_at_offset_to_daznode_target(self):
        from dazpy.cinematics import CinematicStaticShot, apply_static_shot
        from dazpy.math3 import Vec3

        class _Node:
            position = {"x": 0.0, "y": 100.0, "z": 0.0}

        scene = _FakeCinematicsScene()
        shot = CinematicStaticShot(position=Vec3(0, 0, 150), look_at=_Node(), look_at_offset_cm=20.0)
        cam = apply_static_shot(scene, shot)
        self.assertEqual(cam.aim_at_calls, [(0.0, 120.0, 0.0)])

    def test_apply_calls_set_rotation_when_only_rotation_given(self):
        from dazpy.cinematics import CinematicStaticShot, apply_static_shot
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        shot = CinematicStaticShot(position=Vec3(0, 0, 150), rotation=(10.0, 20.0, 30.0))
        cam = apply_static_shot(scene, shot)
        self.assertEqual(cam.rotation_calls, [(10.0, 20.0, 30.0)])
        self.assertEqual(cam.aim_at_calls, [])

    def test_apply_touches_neither_orientation_when_both_none(self):
        from dazpy.cinematics import CinematicStaticShot, apply_static_shot
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        shot = CinematicStaticShot(position=Vec3(0, 0, 150))
        cam = apply_static_shot(scene, shot)
        self.assertEqual(cam.aim_at_calls, [])
        self.assertEqual(cam.rotation_calls, [])

    def test_apply_always_writes_focal_length_and_depth_of_field(self):
        from dazpy.cinematics import CinematicStaticShot, apply_static_shot
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        shot = CinematicStaticShot(position=Vec3(0, 0, 150), focal_length=85.0, depth_of_field=True)
        cam = apply_static_shot(scene, shot)
        self.assertEqual(cam.focal_length, 85.0)
        self.assertTrue(cam.depth_of_field)

    def test_apply_writes_optional_fields_only_when_not_none(self):
        from dazpy.cinematics import CinematicStaticShot, apply_static_shot
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        shot = CinematicStaticShot(position=Vec3(0, 0, 150))
        cam = apply_static_shot(scene, shot)
        self.assertIsNone(cam.focal_distance)
        self.assertIsNone(cam.aspect_width)
        self.assertIsNone(cam.aspect_height)
        self.assertIsNone(cam.pixels_width)
        self.assertIsNone(cam.pixels_height)

    def test_apply_writes_all_optional_fields_when_given(self):
        from dazpy.cinematics import CinematicStaticShot, apply_static_shot
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        shot = CinematicStaticShot(
            position=Vec3(0, 0, 150), focal_distance=175.0,
            aspect_width=16.0, aspect_height=9.0,
            pixels_width=1920, pixels_height=1080,
        )
        cam = apply_static_shot(scene, shot)
        self.assertEqual(cam.focal_distance, 175.0)
        self.assertEqual(cam.aspect_width, 16.0)
        self.assertEqual(cam.aspect_height, 9.0)
        self.assertEqual(cam.pixels_width, 1920)
        self.assertEqual(cam.pixels_height, 1080)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_dazpy.py::TestCinematicStaticShot -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dazpy.cinematics'`.

- [ ] **Step 3: Create `dazpy/cinematics.py`**

```python
"""Domain-level camera shot builders built on the DazCamera/DazScene primitives.

Provides :func:`apply_static_shot` for a single camera placement/framing,
:func:`apply_orbit_camera` for a per-frame orbit sweep around a target, and
:func:`apply_frame_subject` for distance-preset framing of a subject. All
three write static per-frame placements, not real interpolated keyframes —
see the module's design spec for why (``CinematicAnimatedShot`` is a
separate, deferred follow-up).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .math3 import Vec3
from ._shot_geometry import resolve_target, spherical_offset

if TYPE_CHECKING:
    from ._camera import DazCamera
    from ._node import DazNode
    from ._scene import DazScene


def _resolve_camera(scene: "DazScene", camera: "DazCamera | None", name: str | None) -> "DazCamera":
    if camera is not None:
        return camera
    return scene.create_camera(name)


@dataclass(frozen=True)
class CinematicStaticShot:
    """A single camera placement and optics configuration.

    Args:
        position: World-space camera position.
        look_at: Aim target passed to :meth:`~dazpy.DazCamera.aim_at`. A
            :class:`~dazpy.DazNode` is resolved via its
            :attr:`~dazpy.DazNode.position`, raised by *look_at_offset_cm*.
            Ignored if ``None``; in that case *rotation* (if set) is used
            instead.
        look_at_offset_cm: Vertical offset (cm) applied when resolving
            *look_at* — see :func:`~dazpy._shot_geometry.resolve_target`.
            Defaults to ``0.0`` since this API already takes an explicit
            *position*/*look_at* the caller fully controls.
        rotation: Explicit ``(x, y, z)`` degrees passed to
            :meth:`~dazpy.DazNode.set_rotation`. Ignored if *look_at* is set.
        focal_length: Passed to :attr:`~dazpy.DazCamera.focal_length`.
        depth_of_field: Passed to :attr:`~dazpy.DazCamera.depth_of_field`.
        focal_distance: Passed to :attr:`~dazpy.DazCamera.focal_distance`
            when not ``None``; otherwise DAZ's current value is untouched.
        aspect_width: Passed to :attr:`~dazpy.DazCamera.aspect_width` when
            not ``None``.
        aspect_height: Passed to :attr:`~dazpy.DazCamera.aspect_height` when
            not ``None``.
        pixels_width: Passed to :attr:`~dazpy.DazCamera.pixels_width` when
            not ``None``.
        pixels_height: Passed to :attr:`~dazpy.DazCamera.pixels_height` when
            not ``None``.
    """

    position: Vec3
    look_at: "Vec3 | DazNode | None" = None
    look_at_offset_cm: float = 0.0
    rotation: tuple[float, float, float] | None = None
    focal_length: float = 50.0
    depth_of_field: bool = False
    focal_distance: float | None = None
    aspect_width: float | None = None
    aspect_height: float | None = None
    pixels_width: int | None = None
    pixels_height: int | None = None


def apply_static_shot(
    scene: "DazScene",
    shot: CinematicStaticShot,
    *,
    camera: "DazCamera | None" = None,
    name: str | None = None,
) -> "DazCamera":
    """Place and configure a camera for *shot* in a single HTTP-round-trip set.

    Args:
        scene: A :class:`~dazpy.DazScene`. Only used to create a new camera
            when *camera* is ``None``.
        shot: The placement/optics configuration.
        camera: An existing :class:`~dazpy.DazCamera` to reuse/mutate.
            When ``None`` (the default), a new camera is created via
            ``scene.create_camera(name)``.
        name: Optional name for a newly created camera. Ignored when
            *camera* is given.

    Returns:
        The configured :class:`~dazpy.DazCamera` (either *camera* or the
        newly created one).
    """
    cam = _resolve_camera(scene, camera, name)
    cam.set_position(shot.position.x, shot.position.y, shot.position.z)
    if shot.look_at is not None:
        target = resolve_target(shot.look_at, vertical_offset_cm=shot.look_at_offset_cm)
        cam.aim_at(target.x, target.y, target.z)
    elif shot.rotation is not None:
        cam.set_rotation(*shot.rotation)
    cam.focal_length = shot.focal_length
    cam.depth_of_field = shot.depth_of_field
    if shot.focal_distance is not None:
        cam.focal_distance = shot.focal_distance
    if shot.aspect_width is not None:
        cam.aspect_width = shot.aspect_width
    if shot.aspect_height is not None:
        cam.aspect_height = shot.aspect_height
    if shot.pixels_width is not None:
        cam.pixels_width = shot.pixels_width
    if shot.pixels_height is not None:
        cam.pixels_height = shot.pixels_height
    return cam
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_dazpy.py::TestCinematicStaticShot -v`
Expected: PASS (11 tests).

- [ ] **Step 5: Commit**

```bash
git add dazpy/cinematics.py tests/test_dazpy.py
git commit -m "feat(dazpy): add cinematics.CinematicStaticShot / apply_static_shot"
```

---

## Task 3: `OrbitCamera` and `apply_orbit_camera`

**Files:**
- Modify: `dazpy/cinematics.py` (append)
- Test: `tests/test_dazpy.py` (append, after `TestCinematicStaticShot`)

**Interfaces:**
- Consumes: `_resolve_camera` (Task 2), `resolve_target`/`spherical_offset` (Task 1), `dazpy._timeline.DazTimeline` (existing — constructor `DazTimeline(client)`, `.frame` setter issues `Scene.setFrame({int(value)});` via `client.execute`).
- Produces: `dazpy.cinematics.OrbitCamera` dataclass, `dazpy.cinematics.apply_orbit_camera(scene, orbit, *, camera=None, name=None) -> DazCamera`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dazpy.py`, after `TestCinematicStaticShot`:

```python
class TestOrbitCamera(unittest.TestCase):
    def test_defaults(self):
        from dazpy.cinematics import OrbitCamera
        from dazpy.math3 import Vec3
        orbit = OrbitCamera(target=Vec3(0, 0, 0), radius=200.0)
        self.assertEqual(orbit.elevation_deg, 15.0)
        self.assertEqual(orbit.start_azimuth_deg, 0.0)
        self.assertEqual(orbit.end_azimuth_deg, 360.0)
        self.assertEqual(orbit.frame_start, 0)
        self.assertEqual(orbit.frame_end, 90)
        self.assertEqual(orbit.focal_length, 50.0)
        self.assertEqual(orbit.target_offset_cm, 25.0)

    def test_apply_creates_new_camera_when_none_given(self):
        from dazpy.cinematics import OrbitCamera, apply_orbit_camera
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        orbit = OrbitCamera(target=Vec3(0, 0, 0), radius=200.0, frame_start=0, frame_end=2)
        cam = apply_orbit_camera(scene, orbit, name="Orbit Cam")
        self.assertEqual(len(scene.created), 1)
        self.assertIs(cam, scene.created[0])

    def test_apply_reuses_given_camera(self):
        from dazpy.cinematics import OrbitCamera, apply_orbit_camera
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        existing = _FakeCinematicsCamera("MyCam")
        orbit = OrbitCamera(target=Vec3(0, 0, 0), radius=200.0, frame_start=0, frame_end=2)
        cam = apply_orbit_camera(scene, orbit, camera=existing)
        self.assertIs(cam, existing)
        self.assertEqual(len(scene.created), 0)

    def test_apply_sets_focal_length_once(self):
        from dazpy.cinematics import OrbitCamera, apply_orbit_camera
        from dazpy.math3 import Vec3
        cam = _FakeCinematicsCamera()
        scene = _FakeCinematicsScene()
        orbit = OrbitCamera(target=Vec3(0, 0, 0), radius=200.0, frame_start=0, frame_end=2, focal_length=35.0)
        apply_orbit_camera(scene, orbit, camera=cam)
        self.assertEqual(cam.focal_length, 35.0)

    def test_apply_steps_timeline_frame_for_every_frame_inclusive(self):
        from dazpy.cinematics import OrbitCamera, apply_orbit_camera
        from dazpy.math3 import Vec3
        cam = _FakeCinematicsCamera()
        scene = _FakeCinematicsScene()
        orbit = OrbitCamera(target=Vec3(0, 0, 0), radius=200.0, frame_start=5, frame_end=8)
        apply_orbit_camera(scene, orbit, camera=cam)
        scripts = [call.args[0] for call in cam._client.execute.call_args_list]
        self.assertEqual(len(scripts), 4)
        for frame, script in zip(range(5, 9), scripts):
            self.assertIn(f"Scene.setFrame({frame})", script)

    def test_apply_writes_one_position_and_aim_at_per_frame(self):
        from dazpy.cinematics import OrbitCamera, apply_orbit_camera
        from dazpy.math3 import Vec3
        cam = _FakeCinematicsCamera()
        scene = _FakeCinematicsScene()
        orbit = OrbitCamera(target=Vec3(0, 0, 0), radius=200.0, frame_start=0, frame_end=3)
        apply_orbit_camera(scene, orbit, camera=cam)
        self.assertEqual(len(cam.position_calls), 4)
        self.assertEqual(len(cam.aim_at_calls), 4)

    def test_apply_interpolates_azimuth_linearly_across_frames(self):
        from dazpy.cinematics import OrbitCamera, apply_orbit_camera
        from dazpy._shot_geometry import spherical_offset
        from dazpy.math3 import Vec3
        cam = _FakeCinematicsCamera()
        scene = _FakeCinematicsScene()
        orbit = OrbitCamera(
            target=Vec3(0, 0, 0), radius=200.0, elevation_deg=0.0,
            start_azimuth_deg=0.0, end_azimuth_deg=90.0,
            frame_start=0, frame_end=2, target_offset_cm=0.0,
        )
        apply_orbit_camera(scene, orbit, camera=cam)
        expected_mid = spherical_offset(Vec3(0, 0, 0), 45.0, 0.0, 200.0)
        x, y, z = cam.position_calls[1]
        self.assertAlmostEqual(x, expected_mid.x, places=6)
        self.assertAlmostEqual(y, expected_mid.y, places=6)
        self.assertAlmostEqual(z, expected_mid.z, places=6)

    def test_apply_resolves_daznode_target_with_offset(self):
        from dazpy.cinematics import OrbitCamera, apply_orbit_camera
        from dazpy.math3 import Vec3

        class _Node:
            position = {"x": 0.0, "y": 0.0, "z": 0.0}

        cam = _FakeCinematicsCamera()
        scene = _FakeCinematicsScene()
        orbit = OrbitCamera(target=_Node(), radius=200.0, frame_start=0, frame_end=0, target_offset_cm=30.0)
        apply_orbit_camera(scene, orbit, camera=cam)
        self.assertEqual(cam.aim_at_calls, [(0.0, 30.0, 0.0)])

    def test_apply_single_frame_range_uses_start_azimuth(self):
        from dazpy.cinematics import OrbitCamera, apply_orbit_camera
        from dazpy._shot_geometry import spherical_offset
        from dazpy.math3 import Vec3
        cam = _FakeCinematicsCamera()
        scene = _FakeCinematicsScene()
        orbit = OrbitCamera(
            target=Vec3(0, 0, 0), radius=200.0, elevation_deg=0.0,
            start_azimuth_deg=10.0, end_azimuth_deg=350.0,
            frame_start=7, frame_end=7, target_offset_cm=0.0,
        )
        apply_orbit_camera(scene, orbit, camera=cam)
        expected = spherical_offset(Vec3(0, 0, 0), 10.0, 0.0, 200.0)
        x, y, z = cam.position_calls[0]
        self.assertAlmostEqual(x, expected.x, places=6)
        self.assertAlmostEqual(z, expected.z, places=6)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_dazpy.py::TestOrbitCamera -v`
Expected: FAIL — `ImportError: cannot import name 'OrbitCamera' from 'dazpy.cinematics'`.

- [ ] **Step 3: Append `OrbitCamera` and `apply_orbit_camera` to `dazpy/cinematics.py`**

Add `from ._timeline import DazTimeline` to the top-level (non-`TYPE_CHECKING`) imports — it's needed at runtime, not just for type hints — so the import block becomes:

```python
from .math3 import Vec3
from ._shot_geometry import resolve_target, spherical_offset
from ._timeline import DazTimeline
```

Then append after `apply_static_shot`:

```python
def _lerp(start: float, end: float, t: float) -> float:
    return start + (end - start) * t


@dataclass(frozen=True)
class OrbitCamera:
    """A camera sweeping around a target across a frame range.

    Writes a static per-frame placement at each timeline frame — this is
    **not** a real interpolated keyframe animation (see the module
    docstring). Whether the sweep persists as visible motion when scrubbing
    the timeline afterward depends on DAZ Studio's key/animation mode at
    call time; that's the caller's responsibility.

    Args:
        target: The point to orbit around, as a
            :class:`~dazpy.math3.Vec3` world position or a
            :class:`~dazpy.DazNode` (its :attr:`~dazpy.DazNode.position`,
            raised by *target_offset_cm*, is used).
        radius: Orbit radius from the target, in DAZ Studio units (cm).
        elevation_deg: Constant elevation angle throughout the orbit — see
            :func:`~dazpy._shot_geometry.spherical_offset`.
        start_azimuth_deg: Azimuth at *frame_start*.
        end_azimuth_deg: Azimuth at *frame_end*. Azimuth is linearly
            interpolated between the two across the frame range.
        frame_start: First timeline frame (inclusive).
        frame_end: Last timeline frame (inclusive).
        focal_length: Passed to :attr:`~dazpy.DazCamera.focal_length` once,
            before the per-frame sweep.
        target_offset_cm: Vertical offset (cm) applied when resolving
            *target* — see :func:`~dazpy._shot_geometry.resolve_target`.
            Defaults to ``25.0`` (chest height) since a figure's resolved
            position is generally its root/hip joint and a close orbit
            radius aimed straight at it risks clipping the head.
    """

    target: "Vec3 | DazNode"
    radius: float
    elevation_deg: float = 15.0
    start_azimuth_deg: float = 0.0
    end_azimuth_deg: float = 360.0
    frame_start: int = 0
    frame_end: int = 90
    focal_length: float = 50.0
    target_offset_cm: float = 25.0


def apply_orbit_camera(
    scene: "DazScene",
    orbit: OrbitCamera,
    *,
    camera: "DazCamera | None" = None,
    name: str | None = None,
) -> "DazCamera":
    """Sweep a camera around *orbit.target* across its frame range.

    Args:
        scene: A :class:`~dazpy.DazScene`. Only used to create a new camera
            when *camera* is ``None``.
        orbit: The orbit configuration.
        camera: An existing :class:`~dazpy.DazCamera` to reuse/mutate.
            When ``None`` (the default), a new camera is created via
            ``scene.create_camera(name)``.
        name: Optional name for a newly created camera. Ignored when
            *camera* is given.

    Returns:
        The configured :class:`~dazpy.DazCamera`.
    """
    cam = _resolve_camera(scene, camera, name)
    target = resolve_target(orbit.target, vertical_offset_cm=orbit.target_offset_cm)
    cam.focal_length = orbit.focal_length
    timeline = DazTimeline(cam._client)
    frame_count = orbit.frame_end - orbit.frame_start
    for frame in range(orbit.frame_start, orbit.frame_end + 1):
        t = (frame - orbit.frame_start) / frame_count if frame_count > 0 else 0.0
        azimuth = _lerp(orbit.start_azimuth_deg, orbit.end_azimuth_deg, t)
        pos = spherical_offset(target, azimuth, orbit.elevation_deg, orbit.radius)
        timeline.frame = frame
        cam.set_position(pos.x, pos.y, pos.z)
        cam.aim_at(target.x, target.y, target.z)
    return cam
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_dazpy.py::TestOrbitCamera -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add dazpy/cinematics.py tests/test_dazpy.py
git commit -m "feat(dazpy): add cinematics.OrbitCamera / apply_orbit_camera"
```

---

## Task 4: `FrameSubject` and `apply_frame_subject`

**Files:**
- Modify: `dazpy/cinematics.py` (append)
- Test: `tests/test_dazpy.py` (append, after `TestOrbitCamera`)

**Interfaces:**
- Consumes: `_resolve_camera`, `resolve_target`, `spherical_offset` (Tasks 1-2).
- Produces: `dazpy.cinematics.FrameSubject` dataclass, `dazpy.cinematics.apply_frame_subject(scene, frame, *, camera=None, name=None) -> DazCamera`, module constants `_SHOT_DISTANCES`, `_SHOT_TARGET_OFFSETS_CM`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dazpy.py`, after `TestOrbitCamera`:

```python
class TestFrameSubject(unittest.TestCase):
    def test_defaults(self):
        from dazpy.cinematics import FrameSubject
        from dazpy.math3 import Vec3
        frame = FrameSubject(subject=Vec3(0, 0, 0))
        self.assertEqual(frame.shot_type, "medium")
        self.assertEqual(frame.azimuth_deg, 0.0)
        self.assertEqual(frame.elevation_deg, 10.0)
        self.assertEqual(frame.focal_length, 50.0)
        self.assertIsNone(frame.target_offset_cm)

    def test_apply_creates_new_camera_when_none_given(self):
        from dazpy.cinematics import FrameSubject, apply_frame_subject
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        frame = FrameSubject(subject=Vec3(0, 0, 0))
        cam = apply_frame_subject(scene, frame, name="Close Up")
        self.assertEqual(len(scene.created), 1)
        self.assertIs(cam, scene.created[0])

    def test_apply_reuses_given_camera(self):
        from dazpy.cinematics import FrameSubject, apply_frame_subject
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        existing = _FakeCinematicsCamera("MyCam")
        frame = FrameSubject(subject=Vec3(0, 0, 0))
        cam = apply_frame_subject(scene, frame, camera=existing)
        self.assertIs(cam, existing)
        self.assertEqual(len(scene.created), 0)

    def test_apply_resolves_each_shot_type_to_documented_distance(self):
        from dazpy.cinematics import FrameSubject, apply_frame_subject, _SHOT_DISTANCES
        from dazpy._shot_geometry import spherical_offset
        from dazpy.math3 import Vec3
        for shot_type, distance in _SHOT_DISTANCES.items():
            with self.subTest(shot_type=shot_type):
                cam = _FakeCinematicsCamera()
                scene = _FakeCinematicsScene()
                frame = FrameSubject(subject=Vec3(0, 0, 0), shot_type=shot_type, elevation_deg=0.0, target_offset_cm=0.0)
                apply_frame_subject(scene, frame, camera=cam)
                expected = spherical_offset(Vec3(0, 0, 0), 0.0, 0.0, distance)
                x, y, z = cam.position_calls[0]
                self.assertAlmostEqual(x, expected.x, places=6)
                self.assertAlmostEqual(z, expected.z, places=6)

    def test_apply_uses_shot_type_default_offset_when_none(self):
        from dazpy.cinematics import FrameSubject, apply_frame_subject, _SHOT_TARGET_OFFSETS_CM
        from dazpy.math3 import Vec3
        for shot_type, offset in _SHOT_TARGET_OFFSETS_CM.items():
            with self.subTest(shot_type=shot_type):
                cam = _FakeCinematicsCamera()
                scene = _FakeCinematicsScene()
                frame = FrameSubject(subject=Vec3(0, 0, 0), shot_type=shot_type, azimuth_deg=0.0, elevation_deg=0.0)
                apply_frame_subject(scene, frame, camera=cam)
                self.assertAlmostEqual(cam.aim_at_calls[0][1], offset, places=6)

    def test_apply_honors_explicit_target_offset_override(self):
        from dazpy.cinematics import FrameSubject, apply_frame_subject
        from dazpy.math3 import Vec3
        cam = _FakeCinematicsCamera()
        scene = _FakeCinematicsScene()
        frame = FrameSubject(subject=Vec3(0, 0, 0), shot_type="close_up", target_offset_cm=5.0)
        apply_frame_subject(scene, frame, camera=cam)
        self.assertAlmostEqual(cam.aim_at_calls[0][1], 5.0, places=6)

    def test_apply_raises_value_error_on_unknown_shot_type(self):
        from dazpy.cinematics import FrameSubject, apply_frame_subject
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        frame = FrameSubject(subject=Vec3(0, 0, 0), shot_type="extreme_wide")
        with self.assertRaises(ValueError):
            apply_frame_subject(scene, frame)

    def test_apply_sets_focal_length(self):
        from dazpy.cinematics import FrameSubject, apply_frame_subject
        from dazpy.math3 import Vec3
        cam = _FakeCinematicsCamera()
        scene = _FakeCinematicsScene()
        frame = FrameSubject(subject=Vec3(0, 0, 0), focal_length=135.0)
        apply_frame_subject(scene, frame, camera=cam)
        self.assertEqual(cam.focal_length, 135.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_dazpy.py::TestFrameSubject -v`
Expected: FAIL — `ImportError: cannot import name 'FrameSubject' from 'dazpy.cinematics'`.

- [ ] **Step 3: Append `FrameSubject` and `apply_frame_subject` to `dazpy/cinematics.py`**

```python
_SHOT_DISTANCES = {"close_up": 60.0, "medium": 150.0, "full_body": 300.0}
_SHOT_TARGET_OFFSETS_CM = {"close_up": 45.0, "medium": 25.0, "full_body": 0.0}


@dataclass(frozen=True)
class FrameSubject:
    """A camera framing a subject at a named shot distance.

    Args:
        subject: The point to frame, as a :class:`~dazpy.math3.Vec3` world
            position or a :class:`~dazpy.DazNode` (its
            :attr:`~dazpy.DazNode.position`, raised by *target_offset_cm*,
            is used).
        shot_type: One of ``"close_up"``, ``"medium"``, ``"full_body"`` —
            maps to a preset distance via a module-level table.
        azimuth_deg: Camera azimuth around the subject — see
            :func:`~dazpy._shot_geometry.spherical_offset`.
        elevation_deg: Camera elevation around the subject.
        focal_length: Passed to :attr:`~dazpy.DazCamera.focal_length`.
        target_offset_cm: Vertical offset (cm) applied when resolving
            *subject* — see :func:`~dazpy._shot_geometry.resolve_target`.
            ``None`` (the default) uses the *shot_type*'s entry in
            ``_SHOT_TARGET_OFFSETS_CM`` (tighter shots aim higher, to
            compensate for a figure's resolved position being its
            root/hip joint rather than chest/head height).
    """

    subject: "Vec3 | DazNode"
    shot_type: str = "medium"
    azimuth_deg: float = 0.0
    elevation_deg: float = 10.0
    focal_length: float = 50.0
    target_offset_cm: float | None = None


def apply_frame_subject(
    scene: "DazScene",
    frame: FrameSubject,
    *,
    camera: "DazCamera | None" = None,
    name: str | None = None,
) -> "DazCamera":
    """Place and aim a camera to frame *frame.subject* at its shot distance.

    Args:
        scene: A :class:`~dazpy.DazScene`. Only used to create a new camera
            when *camera* is ``None``.
        frame: The framing configuration.
        camera: An existing :class:`~dazpy.DazCamera` to reuse/mutate.
            When ``None`` (the default), a new camera is created via
            ``scene.create_camera(name)``.
        name: Optional name for a newly created camera. Ignored when
            *camera* is given.

    Returns:
        The configured :class:`~dazpy.DazCamera`.

    Raises:
        ValueError: If ``frame.shot_type`` is not one of ``"close_up"``,
            ``"medium"``, ``"full_body"``.
    """
    if frame.shot_type not in _SHOT_DISTANCES:
        raise ValueError(
            f"Invalid FrameSubject.shot_type {frame.shot_type!r}; must be one of {sorted(_SHOT_DISTANCES)}"
        )
    cam = _resolve_camera(scene, camera, name)
    offset = frame.target_offset_cm if frame.target_offset_cm is not None else _SHOT_TARGET_OFFSETS_CM[frame.shot_type]
    target = resolve_target(frame.subject, vertical_offset_cm=offset)
    pos = spherical_offset(target, frame.azimuth_deg, frame.elevation_deg, _SHOT_DISTANCES[frame.shot_type])
    cam.set_position(pos.x, pos.y, pos.z)
    cam.aim_at(target.x, target.y, target.z)
    cam.focal_length = frame.focal_length
    return cam
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_dazpy.py::TestFrameSubject -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add dazpy/cinematics.py tests/test_dazpy.py
git commit -m "feat(dazpy): add cinematics.FrameSubject / apply_frame_subject"
```

---

## Task 5: Export from `dazpy/__init__.py`

**Files:**
- Modify: `dazpy/__init__.py:80-101` (imports) and `dazpy/__init__.py:172-193` (`__all__`)
- Test: `tests/test_dazpy.py` (append, after `TestFrameSubject`)

**Interfaces:**
- Consumes: `CinematicStaticShot`, `OrbitCamera`, `FrameSubject`, `apply_static_shot`, `apply_orbit_camera`, `apply_frame_subject` (Tasks 2-4).
- Produces: top-level `dazpy.CinematicStaticShot` etc.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dazpy.py`, after `TestFrameSubject`:

```python
class TestCinematicsExports(unittest.TestCase):
    def test_cinematics_symbols_importable_from_top_level_package(self):
        import dazpy
        self.assertTrue(hasattr(dazpy, "CinematicStaticShot"))
        self.assertTrue(hasattr(dazpy, "OrbitCamera"))
        self.assertTrue(hasattr(dazpy, "FrameSubject"))
        self.assertTrue(hasattr(dazpy, "apply_static_shot"))
        self.assertTrue(hasattr(dazpy, "apply_orbit_camera"))
        self.assertTrue(hasattr(dazpy, "apply_frame_subject"))
        self.assertIn("CinematicStaticShot", dazpy.__all__)
        self.assertIn("OrbitCamera", dazpy.__all__)
        self.assertIn("FrameSubject", dazpy.__all__)
        self.assertIn("apply_static_shot", dazpy.__all__)
        self.assertIn("apply_orbit_camera", dazpy.__all__)
        self.assertIn("apply_frame_subject", dazpy.__all__)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_dazpy.py::TestCinematicsExports -v`
Expected: FAIL — `AssertionError: False is not true` (no `CinematicStaticShot` attribute).

- [ ] **Step 3: Add the exports**

In `dazpy/__init__.py`, immediately after the existing `from .poses import apply_pose, reset_transforms, zero_figure` line (line 88), add:

```python
from .cinematics import (
    CinematicStaticShot,
    OrbitCamera,
    FrameSubject,
    apply_static_shot,
    apply_orbit_camera,
    apply_frame_subject,
)
```

In the `__all__` list, immediately after `"zero_figure",` (currently line 180), add:

```python
    "CinematicStaticShot",
    "OrbitCamera",
    "FrameSubject",
    "apply_static_shot",
    "apply_orbit_camera",
    "apply_frame_subject",
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_dazpy.py::TestCinematicsExports -v`
Expected: PASS.

- [ ] **Step 5: Run the entire test file to confirm no regressions**

Run: `python -m pytest tests/test_dazpy.py -v`
Expected: PASS, every test green (existing suite plus all new cinematics/shot-geometry tests).

- [ ] **Step 6: Commit**

```bash
git add dazpy/__init__.py tests/test_dazpy.py
git commit -m "feat(dazpy): export cinematics symbols from top-level package"
```

---

## Task 6: Update the beads issue

**Files:** none (beads CLI only)

- [ ] **Step 1: Update `daz-script-server-p1af` notes**

```bash
bd update daz-script-server-p1af --notes="dazpy.cinematics static-shots slice shipped (CinematicStaticShot/apply_static_shot, OrbitCamera/apply_orbit_camera, FrameSubject/apply_frame_subject) -- see docs/superpowers/specs/2026-08-11-dazpy-cinematics-design.md and docs/superpowers/plans/2026-08-11-dazpy-cinematics.md. Includes a vertical_offset_cm framing fix for hip-joint root positions (dazpy/_shot_geometry.py resolve_target). Remaining GH #31 domain submodules: dazpy.materials. CinematicAnimatedShot deferred to a separate follow-up pending DazScript keyframe API research."
```

Do not close the issue — `dazpy.materials` and `CinematicAnimatedShot` remain open slices of this same issue.

- [ ] **Step 2: Push**

```bash
git push
```
