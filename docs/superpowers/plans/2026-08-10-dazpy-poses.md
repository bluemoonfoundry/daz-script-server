# dazpy.poses Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `dazpy.poses` with `apply_pose`, `zero_figure`, and `reset_transforms` — thin convenience wrappers over the existing `DazPose`/`DazNode`/`DazSkeleton` primitives, per the spec at `docs/superpowers/specs/2026-08-10-dazpy-poses-design.md`.

**Architecture:** One new flat module, `dazpy/poses.py` (matching the existing `dazpy/lighting.py` precedent — not a subpackage). Two of the three functions compose existing primitives with zero new DazScript. `reset_transforms` needs one new `DazNode` primitive (`set_scale`) added first, mirroring the existing `set_local_position`/`set_local_rotation` pattern in `dazpy/_node.py`.

**Tech Stack:** Python 3.12, `dataclasses`/`pathlib` stdlib only, `unittest`/`unittest.mock` for tests (mocked `DazClient`, no live DAZ Studio needed).

## Global Constraints

- Function names use `snake_case` (`apply_pose`, `zero_figure`, `reset_transforms`), not the PascalCase from GH #31 — matches every existing function in this codebase (`apply_three_point_light_setup`, `apply_hdri_environment`).
- No new DazScript beyond the one `set_scale` primitive — everything else composes existing `DazPose`/`DazNode`/`DazSkeleton` methods.
- `zero_figure` must never touch the figure's root position/rotation/scale — only bones/morphs/(optionally) node properties.
- All new tests go in `tests/test_dazpy.py` (already wired into the unit runner via `tests.py`) — no new test file, no runner changes needed.
- Every new public symbol must be exported from `dazpy/__init__.py` (both the `from .poses import ...` line and `__all__`).

---

### Task 1: `DazNode.set_scale` primitive

**Files:**
- Modify: `dazpy/_node.py` (add after the `scale` property, around line 125)
- Test: `tests/test_dazpy.py` (add to `TestDazNodeRotationAndSelection`, around line 2638)

**Interfaces:**
- Consumes: `ScriptBuilder.node_body(identifier, body)` (existing, used by every other `DazNode` setter in this file).
- Produces: `DazNode.set_scale(self, x: float, y: float, z: float) -> None` — used by Task 3's `reset_transforms`.

- [ ] **Step 1: Write the failing test**

Add this method to `TestDazNodeRotationAndSelection` in `tests/test_dazpy.py` (the class already has a `_node()` helper returning `(DazNode(client, NodeIdentifier("Genesis9")), client)` — reuse it):

```python
    def test_set_scale_uses_axis_controls(self):
        node, client = self._node(None)
        node.set_scale(1.5, 2.0, 0.5)
        script = client.execute.call_args[0][0]
        self.assertIn("getXScaleControl", script)
        self.assertIn("getYScaleControl", script)
        self.assertIn("getZScaleControl", script)
        self.assertIn("setValue", script)
        self.assertIn("1.5", script)
        self.assertIn("2.0", script)
        self.assertIn("0.5", script)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dazpy.py -k test_set_scale_uses_axis_controls -v`
Expected: FAIL with `AttributeError: 'DazNode' object has no attribute 'set_scale'`

- [ ] **Step 3: Write minimal implementation**

In `dazpy/_node.py`, add immediately after the `scale` property (after line 125, before the `visible` property):

```python
    def set_scale(self, x: float, y: float, z: float) -> None:
        """Set per-axis local scale.

        Does not affect the general/uniform scale dial (:attr:`general_scale`)
        — DAZ Studio tracks per-axis and uniform scale as separate controls.

        Args:
            x: X-axis scale factor (1.0 = unscaled).
            y: Y-axis scale factor.
            z: Z-axis scale factor.
        """
        script = ScriptBuilder.node_body(
            self._identifier,
            f"_node.getXScaleControl().setValue({x}); _node.getYScaleControl().setValue({y}); _node.getZScaleControl().setValue({z});"
        )
        self._client.execute(script)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dazpy.py -k test_set_scale_uses_axis_controls -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dazpy/_node.py tests/test_dazpy.py
git commit -m "feat(dazpy): add DazNode.set_scale primitive"
```

---

### Task 2: `dazpy.poses.apply_pose`

**Files:**
- Create: `dazpy/poses.py`
- Test: `tests/test_dazpy.py` (new `TestApplyPose` class, add after `TestDazPose` — insert before `class TestBatchPoseEvaluation` around line 4902)

**Interfaces:**
- Consumes: `DazPose.load(path) -> DazPose` and `DazPose.apply(skeleton) -> None` (existing, `dazpy/_pose.py`).
- Produces: `apply_pose(skeleton: DazSkeleton, pose: DazPose | str | Path) -> None`, importable from `dazpy.poses`. Used nowhere else in this plan, but is the module's first public symbol.

- [ ] **Step 1: Write the failing tests**

Add this class to `tests/test_dazpy.py`, directly above `class TestBatchPoseEvaluation(unittest.TestCase):`:

```python
class TestApplyPose(unittest.TestCase):
    def _make_skeleton(self, capture_result=None):
        from dazpy._skeleton import DazSkeleton
        client = _make_client(capture_result)
        skel = DazSkeleton(client, NodeIdentifier("Genesis 9", kind="label"))
        return skel, client

    def test_apply_pose_with_dazpose_instance_delegates_to_apply(self):
        from dazpy.poses import apply_pose
        skeleton = MagicMock()
        pose = MagicMock()
        apply_pose(skeleton, pose)
        pose.apply.assert_called_once_with(skeleton)

    def test_apply_pose_with_dazpose_instance_does_not_call_load(self):
        from dazpy.poses import apply_pose
        from dazpy._pose import DazPose
        skeleton = MagicMock()
        pose = MagicMock()
        with patch.object(DazPose, "load") as mock_load:
            apply_pose(skeleton, pose)
        mock_load.assert_not_called()

    def test_apply_pose_with_path_loads_then_applies(self):
        import json
        import os
        import tempfile
        from dazpy.poses import apply_pose

        data = {"figure": "Genesis 9", "bones": {"hip": [0.0, 5.0, 0.0]}, "morphs": {}, "props": {}}
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump(data, f)
            path = f.name
        try:
            skel, client = self._make_skeleton(True)
            apply_pose(skel, path)
            self.assertEqual(client.execute.call_count, 1)
            script = client.execute.call_args[0][0]
            self.assertIn("hip", script)
        finally:
            os.unlink(path)

    def test_apply_pose_with_path_accepts_pathlib_path(self):
        import json
        import os
        import tempfile
        from pathlib import Path
        from dazpy.poses import apply_pose

        data = {"figure": "Genesis 9", "bones": {}, "morphs": {"PHMSmile": 0.5}, "props": {}}
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump(data, f)
            path = f.name
        try:
            skel, client = self._make_skeleton(True)
            apply_pose(skel, Path(path))
            script = client.execute.call_args[0][0]
            self.assertIn("PHMSmile", script)
        finally:
            os.unlink(path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dazpy.py -k TestApplyPose -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dazpy.poses'`

- [ ] **Step 3: Write minimal implementation**

Create `dazpy/poses.py`:

```python
"""Domain-level pose convenience wrappers built on the DazPose/DazNode/DazSkeleton primitives.

Provides :func:`apply_pose`, :func:`zero_figure`, and :func:`reset_transforms`
so common pose operations don't require hand-assembling :class:`~dazpy.DazPose`
objects or knowing which primitive combination zeroes a figure or resets a
node's transform.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ._pose import DazPose

if TYPE_CHECKING:
    from ._node import DazNode
    from ._skeleton import DazSkeleton


def apply_pose(skeleton: "DazSkeleton", pose: "DazPose | str | Path") -> None:
    """Apply *pose* to *skeleton* in a single HTTP call.

    Args:
        skeleton: The figure to pose.
        pose: A :class:`~dazpy.DazPose` instance, or a path to a pose JSON
            file (loaded via :meth:`~dazpy.DazPose.load` first).
    """
    if isinstance(pose, (str, Path)):
        pose = DazPose.load(pose)
    pose.apply(skeleton)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_dazpy.py -k TestApplyPose -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add dazpy/poses.py tests/test_dazpy.py
git commit -m "feat(dazpy): add poses.apply_pose"
```

---

### Task 3: `dazpy.poses.reset_transforms`

**Files:**
- Modify: `dazpy/poses.py`
- Test: `tests/test_dazpy.py` (new `TestResetTransforms` class, add directly after `TestApplyPose`)

**Interfaces:**
- Consumes: `DazNode.set_local_position(x, y, z)`, `DazNode.set_local_rotation(x, y, z)` (existing, `dazpy/_node.py`), `DazNode.set_scale(x, y, z)` (Task 1).
- Produces: `reset_transforms(node: DazNode) -> None`, importable from `dazpy.poses`.

- [ ] **Step 1: Write the failing tests**

Add this class to `tests/test_dazpy.py`, directly after `TestApplyPose`:

```python
class TestResetTransforms(unittest.TestCase):
    def test_reset_transforms_calls_position_rotation_scale_setters(self):
        from dazpy.poses import reset_transforms
        node = MagicMock()
        reset_transforms(node)
        node.set_local_position.assert_called_once_with(0.0, 0.0, 0.0)
        node.set_local_rotation.assert_called_once_with(0.0, 0.0, 0.0)
        node.set_scale.assert_called_once_with(1.0, 1.0, 1.0)

    def test_reset_transforms_works_on_real_node(self):
        from dazpy._node import DazNode
        from dazpy.poses import reset_transforms

        client = _make_client(None)
        node = DazNode(client, NodeIdentifier("SomeCamera"))
        reset_transforms(node)
        self.assertEqual(client.execute.call_count, 3)
        scripts = [call.args[0] for call in client.execute.call_args_list]
        self.assertTrue(any("setLocalPos" in s for s in scripts))
        self.assertTrue(any("getXRotControl" in s for s in scripts))
        self.assertTrue(any("getXScaleControl" in s for s in scripts))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dazpy.py -k TestResetTransforms -v`
Expected: FAIL with `ImportError: cannot import name 'reset_transforms' from 'dazpy.poses'`

- [ ] **Step 3: Write minimal implementation**

Append to `dazpy/poses.py`:

```python
def reset_transforms(node: "DazNode") -> None:
    """Reset *node*'s local position and rotation to zero, and scale to 1.0.

    Works on any :class:`~dazpy.DazNode` — camera, prop, or figure root.

    Args:
        node: The node to reset.
    """
    node.set_local_position(0.0, 0.0, 0.0)
    node.set_local_rotation(0.0, 0.0, 0.0)
    node.set_scale(1.0, 1.0, 1.0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_dazpy.py -k TestResetTransforms -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add dazpy/poses.py tests/test_dazpy.py
git commit -m "feat(dazpy): add poses.reset_transforms"
```

---

### Task 4: `dazpy.poses.zero_figure`

**Files:**
- Modify: `dazpy/poses.py`
- Test: `tests/test_dazpy.py` (new `TestZeroFigure` class, add directly after `TestResetTransforms`)

**Interfaces:**
- Consumes: `DazPose(figure, bones, morphs, props)` constructor and `DazPose.apply_full(skeleton)` (existing, `dazpy/_pose.py`); `DazSkeleton.bone_rotations() -> dict[str, tuple]`, `DazSkeleton.morph_values() -> dict[str, float]`, `DazSkeleton.set_bone_rotations(dict)`, `DazSkeleton.set_morph_values(dict)` (existing, `dazpy/_skeleton.py`).
- Produces: `zero_figure(skeleton: DazSkeleton, *, include_props: bool = True) -> None`, importable from `dazpy.poses`.

- [ ] **Step 1: Write the failing tests**

Add this class to `tests/test_dazpy.py`, directly after `TestResetTransforms`:

```python
class TestZeroFigure(unittest.TestCase):
    def _make_skeleton(self, capture_result=None):
        from dazpy._skeleton import DazSkeleton
        client = _make_client(capture_result)
        skel = DazSkeleton(client, NodeIdentifier("Genesis 9", kind="label"))
        return skel, client

    def test_default_zeroes_bones_morphs_and_props_via_apply_full(self):
        from dazpy.poses import zero_figure
        skel, client = self._make_skeleton(True)
        zero_figure(skel)
        self.assertEqual(client.execute.call_count, 1)
        script = client.execute.call_args[0][0]
        # apply_full()'s signature zeroing behavior — see DazPose.apply_full tests.
        self.assertIn("_bones[b.getName()] || [0, 0, 0]", script)
        self.assertIn("var _v = (v !== undefined) ? v : 0;", script)

    def test_default_does_not_touch_root_transform(self):
        from dazpy.poses import zero_figure
        skel, client = self._make_skeleton(True)
        zero_figure(skel)
        script = client.execute.call_args[0][0]
        self.assertNotIn("setLocalPos", script)
        self.assertNotIn("setWSPos", script)

    def test_include_props_false_zeroes_only_bones_and_morphs(self):
        from dazpy.poses import zero_figure
        skeleton = MagicMock()
        skeleton.bone_rotations.return_value = {"hip": (1.0, 2.0, 3.0), "chest": (0.0, 5.0, 0.0)}
        skeleton.morph_values.return_value = {"PHMSmile": 0.8}

        zero_figure(skeleton, include_props=False)

        skeleton.set_bone_rotations.assert_called_once_with(
            {"hip": (0.0, 0.0, 0.0), "chest": (0.0, 0.0, 0.0)}
        )
        skeleton.set_morph_values.assert_called_once_with({"PHMSmile": 0.0})

    def test_include_props_false_does_not_use_dazpose(self):
        from dazpy.poses import zero_figure
        skeleton = MagicMock()
        skeleton.bone_rotations.return_value = {}
        skeleton.morph_values.return_value = {}

        zero_figure(skeleton, include_props=False)

        skeleton._client.execute.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dazpy.py -k TestZeroFigure -v`
Expected: FAIL with `ImportError: cannot import name 'zero_figure' from 'dazpy.poses'`

- [ ] **Step 3: Write minimal implementation**

Append to `dazpy/poses.py`:

```python
def zero_figure(skeleton: "DazSkeleton", *, include_props: bool = True) -> None:
    """Drive every bone rotation and morph on *skeleton* to zero.

    Does not touch the figure's root position/rotation/scale — use
    :func:`reset_transforms` for that.

    Args:
        skeleton: The figure to zero.
        include_props: When ``True`` (default), node-level numeric properties
            are also zeroed, via :meth:`~dazpy.DazPose.apply_full`. When
            ``False``, only bone rotations and morphs are zeroed, leaving
            node properties untouched.
    """
    if include_props:
        pose = DazPose(figure=skeleton._identifier.value, bones={}, morphs={}, props={})
        pose.apply_full(skeleton)
        return

    zero_bones = {name: (0.0, 0.0, 0.0) for name in skeleton.bone_rotations()}
    zero_morphs = {name: 0.0 for name in skeleton.morph_values()}
    skeleton.set_bone_rotations(zero_bones)
    skeleton.set_morph_values(zero_morphs)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_dazpy.py -k TestZeroFigure -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add dazpy/poses.py tests/test_dazpy.py
git commit -m "feat(dazpy): add poses.zero_figure"
```

---

### Task 5: Wire exports into `dazpy/__init__.py`

**Files:**
- Modify: `dazpy/__init__.py`
- Test: `tests/test_dazpy.py` (new `TestPosesExports` class, add directly after `TestZeroFigure`)

**Interfaces:**
- Consumes: `apply_pose`, `reset_transforms`, `zero_figure` from `dazpy.poses` (Tasks 2-4).
- Produces: `dazpy.apply_pose`, `dazpy.reset_transforms`, `dazpy.zero_figure` top-level symbols, and matching `dazpy.__all__` entries. Nothing downstream in this plan consumes these, but this is the contract external callers use (`from dazpy import apply_pose`).

- [ ] **Step 1: Write the failing test**

Add this class to `tests/test_dazpy.py`, directly after `TestZeroFigure`:

```python
class TestPosesExports(unittest.TestCase):
    def test_poses_symbols_importable_from_top_level_package(self):
        import dazpy
        self.assertTrue(hasattr(dazpy, "apply_pose"))
        self.assertTrue(hasattr(dazpy, "reset_transforms"))
        self.assertTrue(hasattr(dazpy, "zero_figure"))
        self.assertIn("apply_pose", dazpy.__all__)
        self.assertIn("reset_transforms", dazpy.__all__)
        self.assertIn("zero_figure", dazpy.__all__)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dazpy.py -k TestPosesExports -v`
Expected: FAIL — `dazpy` has no attribute `apply_pose`

- [ ] **Step 3: Wire the exports**

In `dazpy/__init__.py`, add after the existing `from .lighting import (...)` block (after line 87, before `from ._result import ExecutionResult`):

```python
from .poses import apply_pose, reset_transforms, zero_figure
```

In the `__all__` list, add after the `"apply_hdri_environment",` entry (after line 176):

```python
    "apply_pose",
    "reset_transforms",
    "zero_figure",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dazpy.py -k TestPosesExports -v`
Expected: PASS

- [ ] **Step 5: Run the full unit suite**

Run: `python -m pytest tests/test_dazpy.py -v`
Expected: All tests pass (existing tests + all new poses/set_scale tests), no regressions.

- [ ] **Step 6: Commit**

```bash
git add dazpy/__init__.py tests/test_dazpy.py
git commit -m "feat(dazpy): export poses.apply_pose/reset_transforms/zero_figure from top-level package"
```

---

## Post-implementation

After Task 5 is committed and the full suite is green, update beads issue `daz-script-server-p1af`:

```bash
bd update daz-script-server-p1af --notes="dazpy.poses shipped (apply_pose, reset_transforms, zero_figure) -- see docs/superpowers/specs/2026-08-10-dazpy-poses-design.md and docs/superpowers/plans/2026-08-10-dazpy-poses.md. Remaining GH #31 domain submodules: dazpy.cinematics, dazpy.materials."
```

Do not close the issue — `dazpy.cinematics` and `dazpy.materials` are still open slices of this same issue.
