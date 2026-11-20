# AxisRemap (Coordinate-System Conversion) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `AxisRemap` utility to `dazpy/math3.py` that converts `Vec3`, `Quat`, and `BoundingBox` values between axis conventions (e.g. DAZ Studio's Y-up to a Z-up target), addressing GitHub issue #31 item 4 (`daz-script-server-okpk`).

**Architecture:** A single immutable `AxisRemap` class, built from a 3-axis spec string per output axis (e.g. `x='x', y='-z', z='y'`). Internally it builds a 3×3 signed-permutation matrix once at construction, and exposes `apply_vec3`, `apply_quat` (rejecting reflections), and `apply_bbox`. No new files, no new dependencies — everything lives in the existing dependency-free `dazpy/math3.py` alongside `Vec3`/`Quat`/`BoundingBox`, following that file's existing patterns (`__slots__`, immutability via blocked `__setattr__`, module-level `_snake_case` helper functions for matrix math, Google-style docstrings).

**Tech Stack:** Pure Python (stdlib `math` only), `unittest.TestCase` tests following the existing `tests/test_dazpy.py` convention.

## Global Constraints

- Zero external dependencies — `dazpy/math3.py` must remain pure-Python/stdlib only.
- `AxisRemap` instances are immutable (same pattern as `Vec3`/`Quat`/`BoundingBox`: `__slots__` + `__setattr__` raising `AttributeError`).
- No app-specific helpers (no Blender/Unreal names beyond the one built-in `Y_UP_TO_Z_UP` preset, no camera/figure-orientation fixups) — generic axis-remap only, per user decision during brainstorming.
- `apply_quat` must reject reflective (determinant `-1`) remaps with `ValueError`; `apply_vec3`/`apply_bbox` must work for any valid remap, proper or reflective.
- Public API surface: `AxisRemap` class with `apply_vec3(Vec3) -> Vec3`, `apply_quat(Quat) -> Quat`, `apply_bbox(BoundingBox) -> BoundingBox`, plus the `Y_UP_TO_Z_UP` preset constant. Export both from `dazpy/__init__.py`.

---

### Task 1: Axis-spec parsing, validation, and `apply_vec3`

**Files:**
- Modify: `dazpy/math3.py` (append near the end, after `BoundingBox`)
- Test: `tests/test_math3.py` (new file)

**Interfaces:**
- Produces: `AxisRemap.__init__(self, x: str, y: str, z: str)`, `AxisRemap.apply_vec3(self, v: Vec3) -> Vec3`, module-level helper `_parse_axis_spec(spec: str) -> tuple[int, float]`, module-level helper `_mat3_det(m: list[list[float]]) -> float`.
- Internal state later tasks depend on: `self._specs` (tuple of 3 `(source_index: int, sign: float)` pairs, one per output axis in x,y,z order), `self._matrix` (3×3 `list[list[float]]`, row-major, `self._matrix[row][col]`), `self._det` (float, `+1.0` or `-1.0`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_math3.py`:

```python
"""
Unit tests for dazpy.math3 — AxisRemap coordinate-space conversion.

No server or DAZ Studio required.

Run standalone:  python tests/test_math3.py
Via runner:      python tests.py unit
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from dazpy.math3 import AxisRemap, Vec3


class TestAxisRemapConstruction(unittest.TestCase):
    def test_identity_remap_is_valid(self):
        remap = AxisRemap(x="x", y="y", z="z")
        self.assertEqual(remap.apply_vec3(Vec3(1, 2, 3)), Vec3(1, 2, 3))

    def test_rejects_invalid_axis_name(self):
        with self.assertRaises(ValueError):
            AxisRemap(x="q", y="y", z="z")

    def test_rejects_duplicate_axis_reference(self):
        with self.assertRaises(ValueError):
            AxisRemap(x="y", y="y", z="z")

    def test_rejects_missing_axis_reference(self):
        # x and y both read from 'x' (duplicate), 'z' never referenced.
        with self.assertRaises(ValueError):
            AxisRemap(x="x", y="x", z="y")

    def test_accepts_signed_axis_names(self):
        remap = AxisRemap(x="-x", y="y", z="z")
        self.assertEqual(remap.apply_vec3(Vec3(1, 2, 3)), Vec3(-1, 2, 3))

    def test_is_immutable(self):
        remap = AxisRemap(x="x", y="y", z="z")
        with self.assertRaises(AttributeError):
            remap._det = 5.0


class TestAxisRemapApplyVec3(unittest.TestCase):
    def test_y_up_to_z_up_preset_maps_up_to_z(self):
        remap = AxisRemap(x="x", y="-z", z="y")
        self.assertEqual(remap.apply_vec3(Vec3(0, 1, 0)), Vec3(0, 0, 1))

    def test_y_up_to_z_up_preset_maps_forward_to_negative_y(self):
        remap = AxisRemap(x="x", y="-z", z="y")
        self.assertEqual(remap.apply_vec3(Vec3(0, 0, 1)), Vec3(0, -1, 0))

    def test_reflection_remap_applies_to_vec3(self):
        # Swapping x and y with no sign flip is a reflection (det == -1),
        # but apply_vec3 must still work.
        remap = AxisRemap(x="y", y="x", z="z")
        self.assertEqual(remap.apply_vec3(Vec3(1, 2, 3)), Vec3(2, 1, 3))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_math3.py -v`
Expected: `ImportError: cannot import name 'AxisRemap' from 'dazpy.math3'` (or collection error) — `AxisRemap` doesn't exist yet.

- [ ] **Step 3: Implement `AxisRemap` construction, validation, and `apply_vec3`**

Append to `dazpy/math3.py`, after the `BoundingBox` class (after line 611, before end of file):

```python
# ── AxisRemap ─────────────────────────────────────────────────────────────────

_AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


def _parse_axis_spec(spec: str) -> tuple[int, float]:
    """Parse an axis spec like ``"x"``, ``"-y"``, ``"+z"`` into ``(index, sign)``."""
    if not isinstance(spec, str) or not spec:
        raise ValueError(f"Invalid axis spec {spec!r}; expected one of x, y, z, -x, -y, -z")
    sign = 1.0
    name = spec
    if name[0] in "+-":
        sign = -1.0 if name[0] == "-" else 1.0
        name = name[1:]
    if name not in _AXIS_INDEX:
        raise ValueError(f"Invalid axis spec {spec!r}; expected one of x, y, z, -x, -y, -z")
    return _AXIS_INDEX[name], sign


def _mat3_det(m: list) -> float:
    """Determinant of a 3x3 matrix given as ``m[row][col]``."""
    return (
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    )


class AxisRemap:
    """Converts :class:`Vec3`, :class:`Quat`, and :class:`BoundingBox` values
    between axis conventions (e.g. Y-up to Z-up).

    A generic signed-axis-permutation remap — no application-specific
    knowledge (Blender/Unreal naming, camera or figure orientation fixups)
    is baked in beyond the :data:`Y_UP_TO_Z_UP` preset.

    Each of *x*, *y*, *z* names which source axis (optionally signed) the
    corresponding output axis is derived from. All three of the source
    axes ``x``, ``y``, ``z`` must be referenced exactly once (signs aside).

    Example::

        # DAZ Studio (Y-up) -> Blender-style Z-up
        remap = AxisRemap(x="x", y="-z", z="y")
        blender_pos = remap.apply_vec3(daz_pos)

    Args:
        x: Source axis for the output X component, e.g. ``"x"`` or ``"-z"``.
        y: Source axis for the output Y component.
        z: Source axis for the output Z component.
    """

    __slots__ = ("_specs", "_matrix", "_det", "_rotation_quat")

    def __init__(self, x: str, y: str, z: str) -> None:
        specs = (_parse_axis_spec(x), _parse_axis_spec(y), _parse_axis_spec(z))
        used = sorted(idx for idx, _ in specs)
        if used != [0, 1, 2]:
            raise ValueError(
                "AxisRemap must reference each of x, y, z exactly once "
                f"(got x={x!r}, y={y!r}, z={z!r})"
            )
        matrix = [[0.0, 0.0, 0.0] for _ in range(3)]
        for row, (idx, sign) in enumerate(specs):
            matrix[row][idx] = sign
        object.__setattr__(self, "_specs", specs)
        object.__setattr__(self, "_matrix", matrix)
        object.__setattr__(self, "_det", _mat3_det(matrix))
        object.__setattr__(self, "_rotation_quat", None)

    def __setattr__(self, name, value):
        raise AttributeError("AxisRemap is immutable")

    def __repr__(self) -> str:
        axes = "xyz"
        parts = []
        for idx, sign in self._specs:
            parts.append(("-" if sign < 0 else "") + axes[idx])
        return f"AxisRemap(x={parts[0]!r}, y={parts[1]!r}, z={parts[2]!r})"

    # ── application ───────────────────────────────────────────────────────────

    def apply_vec3(self, v: "Vec3") -> "Vec3":
        """Remap a vector or point. Works for any remap, proper or reflective."""
        comps = (v.x, v.y, v.z)
        out = [comps[idx] * sign for idx, sign in self._specs]
        return Vec3(out[0], out[1], out[2])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_math3.py -v`
Expected: All tests in `TestAxisRemapConstruction` and `TestAxisRemapApplyVec3` PASS.

- [ ] **Step 5: Commit**

```bash
git add dazpy/math3.py tests/test_math3.py
git commit -m "feat(math3): add AxisRemap construction, validation, and apply_vec3"
```

---

### Task 2: `apply_quat` (matrix-to-quaternion conversion + reflection rejection)

**Files:**
- Modify: `dazpy/math3.py`
- Test: `tests/test_math3.py`

**Interfaces:**
- Consumes: `AxisRemap._specs`, `AxisRemap._matrix`, `AxisRemap._det`, `AxisRemap._rotation_quat` from Task 1. `Quat.multiply`, `Quat.conjugate` (existing, `dazpy/math3.py:400-418`).
- Produces: `AxisRemap.apply_quat(self, q: Quat) -> Quat`, module-level helper `_mat3_to_quat(m: list[list[float]]) -> Quat`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_math3.py` (add import of `Quat` and a new test class):

```python
from dazpy.math3 import AxisRemap, Quat, Vec3  # replace the existing import line
```

```python
class TestAxisRemapApplyQuat(unittest.TestCase):
    def test_identity_remap_leaves_quat_unchanged(self):
        remap = AxisRemap(x="x", y="y", z="z")
        q = Quat.from_axis_angle(Vec3(0, 1, 0), 90)
        result = remap.apply_quat(q)
        self.assertAlmostEqual(result.x, q.x, places=9)
        self.assertAlmostEqual(result.y, q.y, places=9)
        self.assertAlmostEqual(result.z, q.z, places=9)
        self.assertAlmostEqual(result.w, q.w, places=9)

    def test_y_up_to_z_up_rotates_rotation_axis_consistently(self):
        # A rotation about the Y-up "up" axis should become a rotation about
        # the Z-up "up" axis, applied to the correspondingly-remapped vector.
        remap = AxisRemap(x="x", y="-z", z="y")
        q = Quat.from_axis_angle(Vec3(0, 1, 0), 90)  # rotate 90 deg around Y-up
        v = Vec3(1, 0, 0)

        rotated_then_remapped = remap.apply_vec3(q.rotate(v))
        remapped_then_rotated = remap.apply_quat(q).rotate(remap.apply_vec3(v))

        self.assertAlmostEqual(rotated_then_remapped.x, remapped_then_rotated.x, places=9)
        self.assertAlmostEqual(rotated_then_remapped.y, remapped_then_rotated.y, places=9)
        self.assertAlmostEqual(rotated_then_remapped.z, remapped_then_rotated.z, places=9)

    def test_reflection_remap_rejects_apply_quat(self):
        remap = AxisRemap(x="y", y="x", z="z")  # det == -1
        q = Quat.identity()
        with self.assertRaises(ValueError):
            remap.apply_quat(q)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_math3.py -v`
Expected: `TestAxisRemapApplyQuat` tests FAIL with `AttributeError: 'AxisRemap' object has no attribute 'apply_quat'`.

- [ ] **Step 3: Implement `_mat3_to_quat` and `apply_quat`**

Add `_mat3_to_quat` right after `_mat3_det` in `dazpy/math3.py`:

```python
def _mat3_to_quat(m: list) -> "Quat":
    """Convert a 3x3 rotation matrix (``m[row][col]``, det == +1) to a unit quaternion."""
    trace = m[0][0] + m[1][1] + m[2][2]
    if trace > 0:
        s = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * s
        x = (m[2][1] - m[1][2]) / s
        y = (m[0][2] - m[2][0]) / s
        z = (m[1][0] - m[0][1]) / s
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2.0
        w = (m[2][1] - m[1][2]) / s
        x = 0.25 * s
        y = (m[0][1] + m[1][0]) / s
        z = (m[0][2] + m[2][0]) / s
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2.0
        w = (m[0][2] - m[2][0]) / s
        x = (m[0][1] + m[1][0]) / s
        y = 0.25 * s
        z = (m[1][2] + m[2][1]) / s
    else:
        s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2.0
        w = (m[1][0] - m[0][1]) / s
        x = (m[0][2] + m[2][0]) / s
        y = (m[1][2] + m[2][1]) / s
        z = 0.25 * s
    return Quat(x, y, z, w)
```

In `AxisRemap.__init__`, replace the last two `object.__setattr__` lines (the ones setting `_det` and `_rotation_quat` from Task 1) with:

```python
        det = _mat3_det(matrix)
        object.__setattr__(self, "_det", det)
        object.__setattr__(
            self, "_rotation_quat", _mat3_to_quat(matrix) if det > 0 else None
        )
```

(This replaces the two lines `object.__setattr__(self, "_det", _mat3_det(matrix))` and `object.__setattr__(self, "_rotation_quat", None)` from Task 1.)

Add `apply_quat` to `AxisRemap`, directly after `apply_vec3`:

```python
    def apply_quat(self, q: "Quat") -> "Quat":
        """Remap a rotation.

        Raises:
            ValueError: If this remap is a reflection (determinant ``-1``).
                Reflections cannot be represented by a quaternion; use
                :meth:`apply_vec3` for vectors/points instead.
        """
        if self._rotation_quat is None:
            raise ValueError(
                "AxisRemap represents a reflection (determinant -1); cannot "
                "remap a Quat. Use apply_vec3 for vectors/points instead."
            )
        r = self._rotation_quat
        return r.multiply(q).multiply(r.conjugate())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_math3.py -v`
Expected: All tests PASS, including `TestAxisRemapApplyQuat`.

- [ ] **Step 5: Commit**

```bash
git add dazpy/math3.py tests/test_math3.py
git commit -m "feat(math3): add AxisRemap.apply_quat with reflection rejection"
```

---

### Task 3: `apply_bbox`

**Files:**
- Modify: `dazpy/math3.py`
- Test: `tests/test_math3.py`

**Interfaces:**
- Consumes: `AxisRemap.apply_vec3` (Task 1), `BoundingBox.__init__(self, min: Vec3, max: Vec3)` (existing, `dazpy/math3.py:527`).
- Produces: `AxisRemap.apply_bbox(self, b: BoundingBox) -> BoundingBox`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_math3.py` (add `BoundingBox` to the import line, then add):

```python
from dazpy.math3 import AxisRemap, BoundingBox, Quat, Vec3  # replace the existing import line
```

```python
class TestAxisRemapApplyBbox(unittest.TestCase):
    def test_identity_remap_leaves_bbox_unchanged(self):
        remap = AxisRemap(x="x", y="y", z="z")
        box = BoundingBox(Vec3(-1, -2, -3), Vec3(1, 2, 3))
        result = remap.apply_bbox(box)
        self.assertEqual(result.min, box.min)
        self.assertEqual(result.max, box.max)

    def test_sign_flip_keeps_min_max_correctly_ordered(self):
        # y='-z' -> negating z means the box's old z-max becomes the new
        # y-min, so apply_bbox must re-sort per axis, not just remap corners.
        remap = AxisRemap(x="x", y="-z", z="y")
        box = BoundingBox(Vec3(0, 0, 0), Vec3(1, 2, 3))
        result = remap.apply_bbox(box)
        self.assertEqual(result.min, Vec3(0, -3, 0))
        self.assertEqual(result.max, Vec3(1, 0, 2))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_math3.py -v`
Expected: `TestAxisRemapApplyBbox` tests FAIL with `AttributeError: 'AxisRemap' object has no attribute 'apply_bbox'`.

- [ ] **Step 3: Implement `apply_bbox`**

Add to `AxisRemap`, directly after `apply_quat`:

```python
    def apply_bbox(self, b: "BoundingBox") -> "BoundingBox":
        """Remap a bounding box.

        Both corners are remapped and the result is re-sorted per axis,
        since a sign-flipping remap can swap which corner is the minimum
        on a given axis.
        """
        p1 = self.apply_vec3(b.min)
        p2 = self.apply_vec3(b.max)
        lo = Vec3(min(p1.x, p2.x), min(p1.y, p2.y), min(p1.z, p2.z))
        hi = Vec3(max(p1.x, p2.x), max(p1.y, p2.y), max(p1.z, p2.z))
        return BoundingBox(lo, hi)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_math3.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add dazpy/math3.py tests/test_math3.py
git commit -m "feat(math3): add AxisRemap.apply_bbox"
```

---

### Task 4: `Y_UP_TO_Z_UP` preset, package exports, and module docstring

**Files:**
- Modify: `dazpy/math3.py`
- Modify: `dazpy/__init__.py`
- Test: `tests/test_math3.py`

**Interfaces:**
- Consumes: `AxisRemap` (Task 1-3).
- Produces: `dazpy.math3.Y_UP_TO_Z_UP` (an `AxisRemap` instance), re-exported as `dazpy.AxisRemap` and `dazpy.Y_UP_TO_Z_UP`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_math3.py`:

```python
class TestYUpToZUpPreset(unittest.TestCase):
    def test_preset_matches_manual_equivalent(self):
        manual = AxisRemap(x="x", y="-z", z="y")
        from dazpy.math3 import Y_UP_TO_Z_UP
        self.assertEqual(Y_UP_TO_Z_UP.apply_vec3(Vec3(1, 2, 3)), manual.apply_vec3(Vec3(1, 2, 3)))

    def test_preset_importable_from_dazpy_package(self):
        from dazpy import AxisRemap as PkgAxisRemap
        from dazpy import Y_UP_TO_Z_UP as PkgPreset
        self.assertIsInstance(PkgPreset, PkgAxisRemap)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_math3.py -v`
Expected: FAIL with `ImportError: cannot import name 'Y_UP_TO_Z_UP' from 'dazpy.math3'`.

- [ ] **Step 3: Add the preset and wire up exports**

At the end of `dazpy/math3.py`, after the `AxisRemap` class:

```python
#: Converts DAZ Studio's Y-up convention to a Z-up convention (e.g. Blender,
#: glTF-consuming tools that were themselves converted to Z-up). Up (+Y)
#: becomes +Z; DAZ's forward (+Z) becomes -Y.
Y_UP_TO_Z_UP = AxisRemap(x="x", y="-z", z="y")
```

In `dazpy/__init__.py`, change line 79:

```python
from .math3 import Vec3, Quat, BoundingBox
```

to:

```python
from .math3 import Vec3, Quat, BoundingBox, AxisRemap, Y_UP_TO_Z_UP
```

And in the `__all__` list, change the block at lines 166-168:

```python
    "Vec3",
    "Quat",
    "BoundingBox",
```

to:

```python
    "Vec3",
    "Quat",
    "BoundingBox",
    "AxisRemap",
    "Y_UP_TO_Z_UP",
```

Also update the module docstring at the top of `dazpy/math3.py` (lines 1-24) to mention `AxisRemap` — add this paragraph after the existing "Typical usage" code block (after line 23, before the closing `"""` on line 24):

```

    # Convert a DAZ Studio (Y-up) position to a Z-up convention
    from dazpy.math3 import Y_UP_TO_Z_UP
    zup_pos = Y_UP_TO_Z_UP.apply_vec3(pos)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_math3.py -v`
Expected: All tests in `tests/test_math3.py` PASS.

Then run the full existing dazpy unit suite to confirm the `__init__.py` export change didn't break anything:

Run: `python -m pytest tests/test_dazpy.py -v`
Expected: All tests PASS (no regressions from the new imports/exports).

- [ ] **Step 5: Commit**

```bash
git add dazpy/math3.py dazpy/__init__.py tests/test_math3.py
git commit -m "feat(math3): add Y_UP_TO_Z_UP preset and export AxisRemap from dazpy package"
```

---

### Task 5: Close out the tracking issue

**Files:**
- None (bookkeeping only).

- [ ] **Step 1: Run the full test suite one more time**

Run: `python -m pytest tests/test_math3.py tests/test_dazpy.py -v`
Expected: All PASS.

- [ ] **Step 2: Close the beads issue**

```bash
bd close daz-script-server-okpk --reason="Added AxisRemap to dazpy/math3.py: apply_vec3/apply_quat/apply_bbox with reflection rejection, Y_UP_TO_Z_UP preset, exported from dazpy package."
```

- [ ] **Step 3: Push**

```bash
git pull --rebase
git push
git status
```

Expected: `git status` shows "up to date with origin" and no uncommitted changes.
