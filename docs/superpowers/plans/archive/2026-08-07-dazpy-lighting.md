# dazpy.lighting (Three-Point Light Rig) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `dazpy.lighting` submodule providing `apply_three_point_light_setup()`, which builds a conventional key/fill/rim light rig around a target using either angle/distance placement (default) or explicit world-space positions (override).

**Architecture:** A single new file, `dazpy/lighting.py`, following the existing `dazpy/_interaction.py` convention: frozen dataclasses describing the desired rig (`LightSpec`, `ThreePointLightSetup`) plus a standalone `apply_three_point_light_setup(scene, setup) -> ThreePointLightRig` function that drives the existing `DazScene`/`DazLight`/`DazNode` primitives. Two private pure-math helpers (`_spherical_offset`, `_look_at_euler`) do the geometry and have no DazScript/client dependency, so they're tested with plain numeric assertions.

**Tech Stack:** Python 3.10+ (repo already uses `from __future__ import annotations` and `X | None` syntax), stdlib `dataclasses` and `math`, existing `dazpy.math3.Vec3`.

## Global Constraints

- Spec source: `docs/superpowers/specs/2026-08-07-dazpy-lighting-design.md`.
- `HDRIEnvironment` is explicitly out of scope for this plan (separate future issue).
- `SetLightColor` is explicitly out of scope — already covered by `DazLight.set_color()`.
- Follow existing dazpy conventions: `from __future__ import annotations`, Google-style docstrings, `@dataclass(frozen=True)` for spec/result types (matches `dazpy/_interaction.py`).
- Tests go in `tests/test_dazpy.py` (mock-based, no server/DAZ Studio required), matching the file's existing `unittest.TestCase` structure and `_make_client`/fake-object patterns.
- Run tests with: `python tests/test_dazpy.py` or `python -m pytest tests/test_dazpy.py -v -k lighting`.

---

### Task 1: Pure math helpers — `_spherical_offset` and `_look_at_euler`

**Files:**
- Create: `dazpy/lighting.py`
- Test: `tests/test_dazpy.py` (new `TestLightingMath` class, appended near the end of the file)

**Interfaces:**
- Consumes: `dazpy.math3.Vec3` (`.x`, `.y`, `.z`, `__add__`, `__sub__`, `__mul__`, `.normalize()` — all already exist in `dazpy/math3.py`).
- Produces (for later tasks):
  - `_spherical_offset(target: Vec3, azimuth_deg: float, elevation_deg: float, distance: float) -> Vec3`
  - `_look_at_euler(from_pos: Vec3, to_pos: Vec3) -> tuple[float, float, float]` — returns `(x_deg, y_deg, z_deg)` ready to pass straight into `DazNode.set_rotation(x, y, z)`.

Convention (document this in the docstrings, it's load-bearing for Task 2's defaults):
- `azimuth_deg=0, elevation_deg=0` places the offset point on the target's `+Z` side, i.e. `target + Vec3(0, 0, distance)`.
- Increasing `azimuth_deg` sweeps from `+Z` toward `+X` (so `azimuth_deg=90` gives `target + Vec3(distance, 0, 0)`).
- `elevation_deg` tilts the offset up toward `+Y`; `elevation_deg=90` gives `target + Vec3(0, distance, 0)` regardless of azimuth.
- `_look_at_euler` returns `(pitch, yaw, 0.0)` such that a light sitting at the `azimuth=0, elevation=0` offset and aimed at the target gets rotation `(0.0, 0.0, 0.0)` — i.e. the light's rest orientation (no rotation) is defined as facing `-Z`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dazpy.py`:

```python
class TestLightingMath(unittest.TestCase):
    def test_spherical_offset_at_zero_azimuth_elevation(self):
        from dazpy.lighting import _spherical_offset
        from dazpy.math3 import Vec3
        result = _spherical_offset(Vec3(0, 0, 0), azimuth_deg=0.0, elevation_deg=0.0, distance=150.0)
        self.assertAlmostEqual(result.x, 0.0, places=6)
        self.assertAlmostEqual(result.y, 0.0, places=6)
        self.assertAlmostEqual(result.z, 150.0, places=6)

    def test_spherical_offset_at_90_azimuth(self):
        from dazpy.lighting import _spherical_offset
        from dazpy.math3 import Vec3
        result = _spherical_offset(Vec3(0, 0, 0), azimuth_deg=90.0, elevation_deg=0.0, distance=150.0)
        self.assertAlmostEqual(result.x, 150.0, places=6)
        self.assertAlmostEqual(result.y, 0.0, places=6)
        self.assertAlmostEqual(result.z, 0.0, places=6)

    def test_spherical_offset_at_90_elevation_ignores_azimuth(self):
        from dazpy.lighting import _spherical_offset
        from dazpy.math3 import Vec3
        result = _spherical_offset(Vec3(0, 0, 0), azimuth_deg=45.0, elevation_deg=90.0, distance=150.0)
        self.assertAlmostEqual(result.x, 0.0, places=6)
        self.assertAlmostEqual(result.y, 150.0, places=6)
        self.assertAlmostEqual(result.z, 0.0, places=6)

    def test_spherical_offset_is_relative_to_target(self):
        from dazpy.lighting import _spherical_offset
        from dazpy.math3 import Vec3
        result = _spherical_offset(Vec3(10, 20, 30), azimuth_deg=0.0, elevation_deg=0.0, distance=150.0)
        self.assertAlmostEqual(result.x, 10.0, places=6)
        self.assertAlmostEqual(result.y, 20.0, places=6)
        self.assertAlmostEqual(result.z, 180.0, places=6)

    def test_look_at_euler_default_offset_is_zero_rotation(self):
        from dazpy.lighting import _look_at_euler
        from dazpy.math3 import Vec3
        x, y, z = _look_at_euler(Vec3(0, 0, 150), Vec3(0, 0, 0))
        self.assertAlmostEqual(x, 0.0, places=6)
        self.assertAlmostEqual(y, 0.0, places=6)
        self.assertAlmostEqual(z, 0.0, places=6)

    def test_look_at_euler_yaws_toward_90_azimuth_offset(self):
        from dazpy.lighting import _look_at_euler
        from dazpy.math3 import Vec3
        x, y, z = _look_at_euler(Vec3(150, 0, 0), Vec3(0, 0, 0))
        self.assertAlmostEqual(x, 0.0, places=6)
        self.assertAlmostEqual(y, -90.0, places=6)
        self.assertAlmostEqual(z, 0.0, places=6)

    def test_look_at_euler_pitches_up_when_light_is_above(self):
        from dazpy.lighting import _look_at_euler
        from dazpy.math3 import Vec3
        x, y, z = _look_at_euler(Vec3(0, 150, 0), Vec3(0, 0, 0))
        self.assertAlmostEqual(x, -90.0, places=6)
        self.assertAlmostEqual(z, 0.0, places=6)

    def test_look_at_euler_handles_directly_above_without_error(self):
        # Degenerate case: horizontal component is exactly zero, yaw must
        # default to 0.0 rather than raising or returning NaN.
        from dazpy.lighting import _look_at_euler
        from dazpy.math3 import Vec3
        x, y, z = _look_at_euler(Vec3(0, 150, 0), Vec3(0, 0, 0))
        self.assertEqual(y, 0.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dazpy.py -v -k TestLightingMath`
Expected: FAIL with `ModuleNotFoundError: No module named 'dazpy.lighting'` (the file doesn't exist yet).

- [ ] **Step 3: Write `dazpy/lighting.py` with the math helpers**

```python
"""Domain-level lighting rigs built on the DazLight/DazScene primitives.

Provides :func:`apply_three_point_light_setup` for creating a conventional
key/fill/rim light rig around a target, either via angle/distance placement
or explicit world-space positions.
"""

from __future__ import annotations

import math

from .math3 import Vec3


def _spherical_offset(
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


def _look_at_euler(from_pos: Vec3, to_pos: Vec3) -> tuple[float, float, float]:
    """Return ``(x, y, z)`` world-space Euler degrees aiming *from_pos* at *to_pos*.

    Suitable for passing directly to :meth:`~dazpy.DazNode.set_rotation`. A
    light positioned via :func:`_spherical_offset` with ``azimuth_deg=0,
    elevation_deg=0`` and aimed with this function at the same target gets
    rotation ``(0, 0, 0)`` — i.e. a light's unrotated rest pose is defined as
    facing ``-Z``. Roll (``z``) is always ``0.0``; lights have no meaningful
    "up" for aiming purposes.
    """
    direction = (to_pos - from_pos).normalize()
    horizontal_dist = math.sqrt(direction.x * direction.x + direction.z * direction.z)
    pitch = math.degrees(math.atan2(direction.y, horizontal_dist))
    if horizontal_dist < 1e-9:
        yaw = 0.0
    else:
        yaw = math.degrees(math.atan2(direction.x, -direction.z))
    return (pitch, yaw, 0.0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_dazpy.py -v -k TestLightingMath`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add dazpy/lighting.py tests/test_dazpy.py
git commit -m "Add pure-math helpers for dazpy.lighting three-point rig"
```

---

### Task 2: `LightSpec` / `ThreePointLightSetup` / `ThreePointLightRig` dataclasses + `apply_three_point_light_setup`

**Files:**
- Modify: `dazpy/lighting.py` (append to the file created in Task 1)
- Test: `tests/test_dazpy.py` (new `TestThreePointLightSetup` class, appended after `TestLightingMath`)

**Interfaces:**
- Consumes:
  - `_spherical_offset`, `_look_at_euler` from Task 1 (same file, no import needed).
  - `Vec3` from `dazpy.math3` (already imported in Task 1).
  - Duck-typed `scene` argument: any object with `create_light(light_type: str) -> <light>`, matching `dazpy.DazScene.create_light`.
  - Duck-typed `<light>` objects returned by `create_light`: must support `set_position(x, y, z)`, `set_rotation(x, y, z)`, a settable `.intensity` attribute, and `set_color(r, g, b)` — matching `dazpy.DazLight`.
  - Duck-typed `target` when it's a node: must expose `.position` returning `{"x": float, "y": float, "z": float}` — matching `dazpy.DazNode.position`.
- Produces (for later tasks / for users):
  - `LightSpec(role, azimuth_deg, elevation_deg, distance, intensity, color=(255,255,255), position=None)`
  - `ThreePointLightSetup(target, key=<default>, fill=<default>, rim=<default>, light_type="spot")`
  - `ThreePointLightRig(key, fill, rim)`
  - `apply_three_point_light_setup(scene, setup: ThreePointLightSetup) -> ThreePointLightRig`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dazpy.py`:

```python
class _FakeLight:
    def __init__(self, light_type: str):
        self.light_type = light_type
        self.position_calls: list[tuple[float, float, float]] = []
        self.rotation_calls: list[tuple[float, float, float]] = []
        self.color_calls: list[tuple[int, int, int]] = []
        self.intensity: float | None = None

    def set_position(self, x, y, z):
        self.position_calls.append((x, y, z))

    def set_rotation(self, x, y, z):
        self.rotation_calls.append((x, y, z))

    def set_color(self, r, g, b):
        self.color_calls.append((r, g, b))


class _FakeScene:
    def __init__(self):
        self.created: list[_FakeLight] = []

    def create_light(self, light_type: str) -> _FakeLight:
        light = _FakeLight(light_type)
        self.created.append(light)
        return light


class _FakeTargetNode:
    def __init__(self, x: float, y: float, z: float):
        self.position = {"x": x, "y": y, "z": z}


class TestThreePointLightSetup(unittest.TestCase):
    def test_default_specs_have_expected_angles_and_intensities(self):
        from dazpy.lighting import ThreePointLightSetup
        from dazpy.math3 import Vec3
        setup = ThreePointLightSetup(target=Vec3(0, 0, 0))
        self.assertEqual(setup.key.role, "key")
        self.assertEqual(setup.key.azimuth_deg, 45.0)
        self.assertEqual(setup.key.elevation_deg, 30.0)
        self.assertEqual(setup.key.intensity, 100.0)
        self.assertEqual(setup.fill.role, "fill")
        self.assertEqual(setup.fill.azimuth_deg, -45.0)
        self.assertEqual(setup.fill.intensity, 50.0)
        self.assertEqual(setup.rim.role, "rim")
        self.assertEqual(setup.rim.azimuth_deg, 180.0)
        self.assertEqual(setup.rim.intensity, 75.0)
        self.assertEqual(setup.light_type, "spot")

    def test_light_spec_is_frozen(self):
        from dazpy.lighting import LightSpec
        spec = LightSpec(role="key", azimuth_deg=0.0, elevation_deg=0.0, distance=1.0, intensity=1.0)
        with self.assertRaises(Exception):
            spec.intensity = 2.0

    def test_apply_creates_three_lights_of_configured_type(self):
        from dazpy.lighting import ThreePointLightSetup, apply_three_point_light_setup
        from dazpy.math3 import Vec3
        scene = _FakeScene()
        setup = ThreePointLightSetup(target=Vec3(0, 0, 0), light_type="distant")
        apply_three_point_light_setup(scene, setup)
        self.assertEqual(len(scene.created), 3)
        self.assertTrue(all(light.light_type == "distant" for light in scene.created))

    def test_apply_returns_rig_in_key_fill_rim_order(self):
        from dazpy.lighting import ThreePointLightSetup, apply_three_point_light_setup
        from dazpy.math3 import Vec3
        scene = _FakeScene()
        setup = ThreePointLightSetup(target=Vec3(0, 0, 0))
        rig = apply_three_point_light_setup(scene, setup)
        self.assertIs(rig.key, scene.created[0])
        self.assertIs(rig.fill, scene.created[1])
        self.assertIs(rig.rim, scene.created[2])

    def test_apply_sets_position_rotation_intensity_color_from_spec(self):
        from dazpy.lighting import LightSpec, ThreePointLightSetup, apply_three_point_light_setup
        from dazpy.math3 import Vec3
        scene = _FakeScene()
        key_spec = LightSpec(
            role="key", azimuth_deg=0.0, elevation_deg=0.0, distance=150.0,
            intensity=88.0, color=(200, 210, 220),
        )
        setup = ThreePointLightSetup(target=Vec3(0, 0, 0), key=key_spec)
        rig = apply_three_point_light_setup(scene, setup)
        self.assertEqual(len(rig.key.position_calls), 1)
        x, y, z = rig.key.position_calls[0]
        self.assertAlmostEqual(x, 0.0, places=6)
        self.assertAlmostEqual(y, 0.0, places=6)
        self.assertAlmostEqual(z, 150.0, places=6)
        self.assertEqual(len(rig.key.rotation_calls), 1)
        self.assertAlmostEqual(rig.key.rotation_calls[0][0], 0.0, places=6)
        self.assertAlmostEqual(rig.key.rotation_calls[0][1], 0.0, places=6)
        self.assertEqual(rig.key.intensity, 88.0)
        self.assertEqual(rig.key.color_calls, [(200, 210, 220)])

    def test_apply_resolves_dazNode_target_via_position(self):
        from dazpy.lighting import ThreePointLightSetup, apply_three_point_light_setup, _spherical_offset
        from dazpy.math3 import Vec3
        scene = _FakeScene()
        node = _FakeTargetNode(10.0, 20.0, 30.0)
        setup = ThreePointLightSetup(target=node)
        rig = apply_three_point_light_setup(scene, setup)
        # key defaults to azimuth=45, elevation=30, distance=150 relative to (10, 20, 30)
        expected = _spherical_offset(Vec3(10.0, 20.0, 30.0), 45.0, 30.0, 150.0)
        x, y, z = rig.key.position_calls[0]
        self.assertAlmostEqual(x, expected.x, places=6)
        self.assertAlmostEqual(y, expected.y, places=6)
        self.assertAlmostEqual(z, expected.z, places=6)

    def test_apply_honors_explicit_position_override(self):
        from dazpy.lighting import LightSpec, ThreePointLightSetup, apply_three_point_light_setup
        from dazpy.math3 import Vec3
        scene = _FakeScene()
        override_spec = LightSpec(
            role="key", azimuth_deg=999.0, elevation_deg=999.0, distance=999.0,
            intensity=50.0, position=Vec3(1.0, 2.0, 3.0),
        )
        setup = ThreePointLightSetup(target=Vec3(0, 0, 0), key=override_spec)
        rig = apply_three_point_light_setup(scene, setup)
        self.assertEqual(rig.key.position_calls[0], (1.0, 2.0, 3.0))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dazpy.py -v -k TestThreePointLightSetup`
Expected: FAIL with `ImportError` (`LightSpec`, `ThreePointLightSetup`, etc. don't exist yet).

- [ ] **Step 3: Append the dataclasses and `apply_three_point_light_setup` to `dazpy/lighting.py`**

```python
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._light import DazLight
    from ._node import DazNode
    from ._scene import DazScene


@dataclass(frozen=True)
class LightSpec:
    """One light's placement and output within a rig.

    Args:
        role: Informational label, e.g. ``"key"``, ``"fill"``, ``"rim"``.
        azimuth_deg: See :func:`_spherical_offset`. Ignored if *position* is set.
        elevation_deg: See :func:`_spherical_offset`. Ignored if *position* is set.
        distance: Distance from the target, in DAZ Studio units (cm).
            Ignored if *position* is set.
        intensity: Passed straight to :attr:`~dazpy.DazLight.intensity`.
        color: ``(r, g, b)`` in the 0-255 range, passed to
            :meth:`~dazpy.DazLight.set_color`.
        position: Explicit world-space override. When set, *azimuth_deg*,
            *elevation_deg*, and *distance* are ignored entirely.
    """

    role: str
    azimuth_deg: float
    elevation_deg: float
    distance: float
    intensity: float
    color: tuple[int, int, int] = (255, 255, 255)
    position: Vec3 | None = None


_DEFAULT_KEY = LightSpec(role="key", azimuth_deg=45.0, elevation_deg=30.0, distance=150.0, intensity=100.0)
_DEFAULT_FILL = LightSpec(role="fill", azimuth_deg=-45.0, elevation_deg=15.0, distance=150.0, intensity=50.0)
_DEFAULT_RIM = LightSpec(role="rim", azimuth_deg=180.0, elevation_deg=45.0, distance=150.0, intensity=75.0)


@dataclass(frozen=True)
class ThreePointLightSetup:
    """Input spec for a three-point light rig.

    Args:
        target: The point to light, as a :class:`~dazpy.math3.Vec3` world
            position or a :class:`~dazpy.DazNode` (its
            :attr:`~dazpy.DazNode.position` is used).
        key: Key light placement/output. Defaults to a 45deg/30deg key light.
        fill: Fill light placement/output. Defaults to a -45deg/15deg fill light.
        rim: Rim light placement/output. Defaults to a 180deg/45deg rim light.
        light_type: Forwarded to :meth:`~dazpy.DazScene.create_light` for all
            three lights — one of ``"spot"``, ``"point"``, ``"distant"``.
    """

    target: "Vec3 | DazNode"
    key: LightSpec = _DEFAULT_KEY
    fill: LightSpec = _DEFAULT_FILL
    rim: LightSpec = _DEFAULT_RIM
    light_type: str = "spot"


@dataclass(frozen=True)
class ThreePointLightRig:
    """Handles to the three lights created by :func:`apply_three_point_light_setup`."""

    key: "DazLight"
    fill: "DazLight"
    rim: "DazLight"


def _resolve_target(target: "Vec3 | DazNode") -> Vec3:
    if isinstance(target, Vec3):
        return target
    return Vec3.from_dict(target.position)


def _resolve_light_position(target: Vec3, spec: LightSpec) -> Vec3:
    if spec.position is not None:
        return spec.position
    return _spherical_offset(target, spec.azimuth_deg, spec.elevation_deg, spec.distance)


def _place_light(scene: "DazScene", target: Vec3, spec: LightSpec, light_type: str) -> "DazLight":
    light = scene.create_light(light_type)
    pos = _resolve_light_position(target, spec)
    light.set_position(pos.x, pos.y, pos.z)
    pitch, yaw, roll = _look_at_euler(pos, target)
    light.set_rotation(pitch, yaw, roll)
    light.intensity = spec.intensity
    light.set_color(*spec.color)
    return light


def apply_three_point_light_setup(scene: "DazScene", setup: ThreePointLightSetup) -> ThreePointLightRig:
    """Create and place a key/fill/rim light rig around *setup.target*.

    Args:
        scene: A :class:`~dazpy.DazScene`.
        setup: The rig configuration.

    Returns:
        A :class:`ThreePointLightRig` with handles to the three created lights.
    """
    target = _resolve_target(setup.target)
    key_light = _place_light(scene, target, setup.key, setup.light_type)
    fill_light = _place_light(scene, target, setup.fill, setup.light_type)
    rim_light = _place_light(scene, target, setup.rim, setup.light_type)
    return ThreePointLightRig(key=key_light, fill=fill_light, rim=rim_light)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_dazpy.py -v -k "TestLightingMath or TestThreePointLightSetup"`
Expected: PASS (all tests from Task 1 and Task 2)

- [ ] **Step 5: Commit**

```bash
git add dazpy/lighting.py tests/test_dazpy.py
git commit -m "Add ThreePointLightSetup dataclasses and apply_three_point_light_setup"
```

---

### Task 3: Export from `dazpy/__init__.py`

**Files:**
- Modify: `dazpy/__init__.py`
- Test: `tests/test_dazpy.py` (new `TestLightingExports` class, appended after `TestThreePointLightSetup`)

**Interfaces:**
- Consumes: `LightSpec`, `ThreePointLightSetup`, `ThreePointLightRig`, `apply_three_point_light_setup` from `dazpy/lighting.py` (Task 2).
- Produces: top-level `dazpy.LightSpec`, `dazpy.ThreePointLightSetup`, `dazpy.ThreePointLightRig`, `dazpy.apply_three_point_light_setup`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dazpy.py`:

```python
class TestLightingExports(unittest.TestCase):
    def test_lighting_symbols_importable_from_top_level_package(self):
        import dazpy
        self.assertTrue(hasattr(dazpy, "LightSpec"))
        self.assertTrue(hasattr(dazpy, "ThreePointLightSetup"))
        self.assertTrue(hasattr(dazpy, "ThreePointLightRig"))
        self.assertTrue(hasattr(dazpy, "apply_three_point_light_setup"))
        self.assertIn("LightSpec", dazpy.__all__)
        self.assertIn("ThreePointLightSetup", dazpy.__all__)
        self.assertIn("ThreePointLightRig", dazpy.__all__)
        self.assertIn("apply_three_point_light_setup", dazpy.__all__)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dazpy.py -v -k TestLightingExports`
Expected: FAIL (`AssertionError`, `hasattr(dazpy, "LightSpec")` is `False`)

- [ ] **Step 3: Add the import and `__all__` entries**

In `dazpy/__init__.py`, after the existing `from .math3 import Vec3, Quat, BoundingBox` line (line 79):

```python
from .lighting import (
    LightSpec,
    ThreePointLightSetup,
    ThreePointLightRig,
    apply_three_point_light_setup,
)
```

In the `__all__` list, after the `"BoundingBox",` entry (line 160):

```python
    "LightSpec",
    "ThreePointLightSetup",
    "ThreePointLightRig",
    "apply_three_point_light_setup",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dazpy.py -v -k TestLightingExports`
Expected: PASS

- [ ] **Step 5: Run the full unit test suite to confirm no regressions**

Run: `python tests/test_dazpy.py`
Expected: All tests pass (existing suite + the new lighting tests).

- [ ] **Step 6: Commit**

```bash
git add dazpy/__init__.py tests/test_dazpy.py
git commit -m "Export dazpy.lighting three-point rig API from top-level package"
```

---

## Post-implementation

- [ ] Close beads issue `daz-script-server-p1af`'s lighting slice, or update its description to note `ThreePointLightSetup`/`SetLightColor` are done and only `HDRIEnvironment` remains — file a new issue for `HDRIEnvironment` if one doesn't already exist, scoped to researching the actual DazScript IBL/dome API surface first.
- [ ] Update `dazpy/ROADMAP.md` if it tracks submodule status (check current content before editing).
