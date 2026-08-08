# dazpy.lighting.HDRIEnvironment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `dazpy.lighting.HDRIEnvironment` and `apply_hdri_environment()`, letting a caller apply image-based (HDRI/dome) lighting to a DAZ Studio scene with one call, safely (no unvalidated paths reaching DazScript's `setMap()`).

**Architecture:** Two layers, matching the existing `ThreePointLightSetup` convention. A primitive layer (`DazRenderSettings` in `dazpy/_render.py`) gains generic get/set access to the Iray "Environment Options" render-element holder (`getRenderElementObjects()[3]`), mirroring the existing `_get_iray_property`/`_set_iray_property` pair which target a different holder. A domain layer (`dazpy/lighting.py`) gains a frozen `HDRIEnvironment` dataclass plus a standalone `apply_hdri_environment(render_settings, env)` function that validates inputs and drives the primitive layer — no class with an `.apply()` method.

**Tech Stack:** Python 3.10+ (repo already uses `from __future__ import annotations` and `X | None` syntax), stdlib `dataclasses`/`os`, existing `dazpy._script_builder.ScriptBuilder`.

## Global Constraints

- Spec source: `docs/superpowers/specs/2026-08-07-dazpy-hdri-environment-design.md`.
- `image_path` must be validated with `os.path.isfile()` *before* any DazScript call reaches `setMap()` — an invalid path passed to `setMap()` was confirmed live to hang the request and crash DAZ Studio (see spec's Context section).
- `mode` supports exactly `"dome_only"` / `"dome_and_scene"` / `"scene_only"`; Sun-Sky mode and `Dome Mode` (sphere/box shape) are explicitly out of scope.
- Follow existing dazpy conventions: `from __future__ import annotations`, Google-style docstrings, `@dataclass(frozen=True)` for the spec type.
- No new public `environment`-prefixed properties on `DazRenderSettings` — `HDRIEnvironment`/`apply_hdri_environment` in `lighting.py` is the sole public surface (spec's explicit design decision).
- Tests go in `tests/test_dazpy.py` (mock-based, no server/DAZ Studio required), matching the file's existing `unittest.TestCase` structure and `_make_client`/fake-object patterns.
- Run tests with: `python -m pytest tests/test_dazpy.py -v -k <keyword>` (never run the full file against a live DAZ Studio instance — see project memory on this).

---

### Task 1: Environment property-holder access on `DazRenderSettings`

**Files:**
- Modify: `dazpy/_render.py` (add methods to `DazRenderSettings`, after the existing `_set_iray_property` method at line 217, before `_iray_render_options_holder` at line 219)
- Test: `tests/test_dazpy.py` (new `TestDazRenderSettingsEnvironment` class, inserted at line 1766, immediately before `class TestDazSkeletonScriptGeneration(unittest.TestCase):`)

**Interfaces:**
- Consumes: `DazRenderSettings._render_mgr()` (existing, returns `"App.getRenderMgr()"`), `ScriptBuilder.iife`/`ScriptBuilder.serialize_arg` (existing).
- Produces (for Task 2 and Task 4):
  - `DazRenderSettings._environment_holder(self) -> str`
  - `DazRenderSettings._get_environment_property(self, name: str)`
  - `DazRenderSettings._set_environment_property(self, name: str, value: object) -> None`
  - `DazRenderSettings._set_environment_property_from_string(self, name: str, value: str) -> None`

- [ ] **Step 1: Write the failing tests**

Insert into `tests/test_dazpy.py` at line 1766 (immediately before `class TestDazSkeletonScriptGeneration(unittest.TestCase):`):

```python
class TestDazRenderSettingsEnvironment(unittest.TestCase):
    def setUp(self):
        from dazpy._render import DazRenderSettings
        self.DazRenderSettings = DazRenderSettings

    def _make_render(self, return_value=None):
        client = _make_client(return_value)
        return self.DazRenderSettings(client), client

    def test_environment_holder_uses_render_element_objects_index_3(self):
        rs, client = self._make_render(1.0)
        rs._get_environment_property("Environment Intensity")
        script = client.execute.call_args[0][0]
        self.assertIn("getRenderElementObjects()[3]", script)

    def test_get_environment_property_reads_named_property(self):
        rs, client = self._make_render(1.0)
        val = rs._get_environment_property("Environment Intensity")
        self.assertEqual(val, 1.0)
        script = client.execute.call_args[0][0]
        self.assertIn("findProperty", script)
        self.assertIn("Environment Intensity", script)
        self.assertIn("getValue", script)

    def test_set_environment_property_writes_named_property(self):
        rs, client = self._make_render(None)
        rs._set_environment_property("Environment Intensity", 2.5)
        script = client.execute.call_args[0][0]
        self.assertIn("Environment Intensity", script)
        self.assertIn("setValue", script)
        self.assertIn("2.5", script)

    def test_set_environment_property_from_string_uses_setValueFromString(self):
        rs, client = self._make_render(None)
        rs._set_environment_property_from_string("Environment Mode", "Dome Only")
        script = client.execute.call_args[0][0]
        self.assertIn("Environment Mode", script)
        self.assertIn("setValueFromString", script)
        self.assertIn("Dome Only", script)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dazpy.py -v -k TestDazRenderSettingsEnvironment`
Expected: FAIL (`AttributeError: 'DazRenderSettings' object has no attribute '_get_environment_property'` or similar) for all four tests.

- [ ] **Step 3: Implement the methods**

In `dazpy/_render.py`, insert after `_set_iray_property` (line 217) and before `_iray_render_options_holder` (line 219):

```python
    def _environment_holder(self) -> str:
        # Index 3 of the 4 fixed render element groups (General Render,
        # Iray, Tonemapper, Environment) -- confirmed against a live
        # instance alongside index 1 (see _iray_render_options_holder).
        return f"{self._render_mgr()}.getRenderElementObjects()[3]"

    def _get_environment_property(self, name: str):
        script = ScriptBuilder.iife(f"""
            var holder = {self._environment_holder()};
            if (!holder) return null;
            var p = holder.findProperty({json.dumps(name)});
            return p ? p.getValue() : null;
        """)
        return self._client.execute(script).value

    def _set_environment_property(self, name: str, value: object) -> None:
        serialized = ScriptBuilder.serialize_arg(value)
        script = ScriptBuilder.iife(f"""
            var holder = {self._environment_holder()};
            if (!holder) return;
            var p = holder.findProperty({json.dumps(name)});
            if (p) p.setValue({serialized});
        """)
        self._client.execute(script)

    def _set_environment_property_from_string(self, name: str, value: str) -> None:
        script = ScriptBuilder.iife(f"""
            var holder = {self._environment_holder()};
            if (!holder) return;
            var p = holder.findProperty({json.dumps(name)});
            if (p) p.setValueFromString({json.dumps(value)});
        """)
        self._client.execute(script)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_dazpy.py -v -k TestDazRenderSettingsEnvironment`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add dazpy/_render.py tests/test_dazpy.py
git commit -m "Add environment render-element property access to DazRenderSettings"
```

---

### Task 2: Safety-validated environment map setter

**Files:**
- Modify: `dazpy/_render.py` (add `import os` at top; add `_set_environment_map` method to `DazRenderSettings`, immediately after `_set_environment_property_from_string` from Task 1)
- Test: `tests/test_dazpy.py` (append to `TestDazRenderSettingsEnvironment` from Task 1)

**Interfaces:**
- Consumes: `DazRenderSettings._environment_holder()` (Task 1).
- Produces (for Task 4): `DazRenderSettings._set_environment_map(self, path: str) -> None` — raises `FileNotFoundError` if `path` is not an existing file; otherwise calls `.setMap(path)` on the "Environment Map" property.

- [ ] **Step 1: Write the failing tests**

Append to `TestDazRenderSettingsEnvironment` in `tests/test_dazpy.py`:

```python
    def test_set_environment_map_raises_when_file_missing(self):
        import tempfile
        rs, client = self._make_render(None)
        missing_path = os.path.join(tempfile.gettempdir(), "definitely_not_a_real_hdri_file.hdr")
        self.assertFalse(os.path.isfile(missing_path))
        with self.assertRaises(FileNotFoundError):
            rs._set_environment_map(missing_path)
        client.execute.assert_not_called()

    def test_set_environment_map_calls_setMap_when_file_exists(self):
        import tempfile
        rs, client = self._make_render(None)
        with tempfile.NamedTemporaryFile(suffix=".hdr") as f:
            rs._set_environment_map(f.name)
            script = client.execute.call_args[0][0]
            self.assertIn("Environment Map", script)
            self.assertIn("setMap", script)
            self.assertIn(f.name.replace("\\", "\\\\"), script)
```

Note: `tests/test_dazpy.py` already imports `os` at module scope (line 11), so no new top-level import is needed for `os.path.isfile`/`os.path.join` — only the local `import tempfile` inside each test.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dazpy.py -v -k test_set_environment_map`
Expected: FAIL (`AttributeError: 'DazRenderSettings' object has no attribute '_set_environment_map'`) for both tests.

- [ ] **Step 3: Implement the method**

Add `import os` to the top of `dazpy/_render.py` (after `import json` at line 3):

```python
import json
import os
```

Add to `DazRenderSettings`, immediately after `_set_environment_property_from_string`:

```python
    def _set_environment_map(self, path: str) -> None:
        if not os.path.isfile(path):
            raise FileNotFoundError(f"HDRI/environment map not found: {path}")
        script = ScriptBuilder.iife(f"""
            var holder = {self._environment_holder()};
            if (!holder) return;
            var p = holder.findProperty({json.dumps("Environment Map")});
            if (p) p.setMap({json.dumps(path)});
        """)
        self._client.execute(script)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_dazpy.py -v -k TestDazRenderSettingsEnvironment`
Expected: PASS (6 tests total in this class)

- [ ] **Step 5: Commit**

```bash
git add dazpy/_render.py tests/test_dazpy.py
git commit -m "Add file-existence-validated environment map setter to DazRenderSettings"
```

---

### Task 3: `HDRIEnvironment` dataclass

**Files:**
- Modify: `dazpy/lighting.py` (add `import os` and `HDRIEnvironment` dataclass; add `DazRenderSettings` to the `TYPE_CHECKING` import block)
- Test: `tests/test_dazpy.py` (new `TestHDRIEnvironment` class, appended immediately after `TestThreePointLightSetup`, before `class TestLightingExports(unittest.TestCase):`)

**Interfaces:**
- Consumes: nothing new.
- Produces (for Task 4): `HDRIEnvironment` frozen dataclass with fields `image_path: str`, `intensity: float = 1.0`, `rotation_deg: float = 0.0`, `mode: str = "dome_only"`, `draw_dome: bool = False`, `resolution: int | None = None`.

- [ ] **Step 1: Write the failing tests**

Insert into `tests/test_dazpy.py` immediately before `class TestLightingExports(unittest.TestCase):`:

```python
class TestHDRIEnvironment(unittest.TestCase):
    def test_defaults(self):
        from dazpy.lighting import HDRIEnvironment
        env = HDRIEnvironment(image_path="/tmp/studio.hdr")
        self.assertEqual(env.image_path, "/tmp/studio.hdr")
        self.assertEqual(env.intensity, 1.0)
        self.assertEqual(env.rotation_deg, 0.0)
        self.assertEqual(env.mode, "dome_only")
        self.assertFalse(env.draw_dome)
        self.assertIsNone(env.resolution)

    def test_is_frozen(self):
        from dazpy.lighting import HDRIEnvironment
        env = HDRIEnvironment(image_path="/tmp/studio.hdr")
        with self.assertRaises(Exception):
            env.intensity = 2.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dazpy.py -v -k TestHDRIEnvironment`
Expected: FAIL (`ImportError: cannot import name 'HDRIEnvironment'`) for both tests.

- [ ] **Step 3: Implement the dataclass**

In `dazpy/lighting.py`, change the imports at the top:

```python
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .math3 import Vec3

if TYPE_CHECKING:
    from ._light import DazLight
    from ._node import DazNode
    from ._render import DazRenderSettings
    from ._scene import DazScene
```

Add the dataclass at the end of the file (after `apply_three_point_light_setup`):

```python
@dataclass(frozen=True)
class HDRIEnvironment:
    """Image-based (HDRI/dome) lighting configuration.

    Args:
        image_path: Absolute path to an HDRI/environment map on disk. Must
            exist -- validated by :func:`apply_hdri_environment` before any
            DazScript call is made.
        intensity: Passed to the Iray "Environment Intensity" property.
        rotation_deg: Passed to the Iray "Dome Rotation" property.
        mode: One of ``"dome_only"``, ``"dome_and_scene"``, ``"scene_only"``.
            Maps to the DazScript "Environment Mode" enum. Procedural
            Sun-Sky mode is intentionally not exposed here.
        draw_dome: Whether the dome image is visible as a backdrop in the
            viewport/render (Iray "Draw Dome"), independent of whether it
            lights the scene.
        resolution: Iray "Environment Lighting Resolution" (IBL sampling
            quality). ``None`` leaves DAZ Studio's current value untouched.
    """

    image_path: str
    intensity: float = 1.0
    rotation_deg: float = 0.0
    mode: str = "dome_only"
    draw_dome: bool = False
    resolution: int | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_dazpy.py -v -k TestHDRIEnvironment`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add dazpy/lighting.py tests/test_dazpy.py
git commit -m "Add HDRIEnvironment dataclass"
```

---

### Task 4: `apply_hdri_environment` function

**Files:**
- Modify: `dazpy/lighting.py` (add `_HDRI_MODE_LABELS` constant and `apply_hdri_environment` function, after the `HDRIEnvironment` dataclass from Task 3)
- Test: `tests/test_dazpy.py` (append to `TestHDRIEnvironment` from Task 3)

**Interfaces:**
- Consumes: `HDRIEnvironment` (Task 3); `DazRenderSettings._set_environment_map`, `._set_environment_property`, `._set_environment_property_from_string` (Tasks 1-2).
- Produces (for Task 5): `apply_hdri_environment(render_settings: DazRenderSettings, env: HDRIEnvironment) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `TestHDRIEnvironment` in `tests/test_dazpy.py`:

```python
    def test_apply_raises_file_not_found_before_any_client_call(self):
        from dazpy._render import DazRenderSettings
        from dazpy.lighting import HDRIEnvironment, apply_hdri_environment
        import tempfile
        client = _make_client(None)
        rs = DazRenderSettings(client)
        missing_path = os.path.join(tempfile.gettempdir(), "definitely_not_a_real_hdri_file.hdr")
        self.assertFalse(os.path.isfile(missing_path))
        env = HDRIEnvironment(image_path=missing_path)
        with self.assertRaises(FileNotFoundError):
            apply_hdri_environment(rs, env)
        client.execute.assert_not_called()

    def test_apply_raises_value_error_on_invalid_mode_before_any_client_call(self):
        from dazpy._render import DazRenderSettings
        from dazpy.lighting import HDRIEnvironment, apply_hdri_environment
        import tempfile
        client = _make_client(None)
        rs = DazRenderSettings(client)
        with tempfile.NamedTemporaryFile(suffix=".hdr") as f:
            env = HDRIEnvironment(image_path=f.name, mode="sun_sky")
            with self.assertRaises(ValueError):
                apply_hdri_environment(rs, env)
        client.execute.assert_not_called()

    def test_apply_happy_path_sets_all_properties_in_order(self):
        from dazpy._render import DazRenderSettings
        from dazpy.lighting import HDRIEnvironment, apply_hdri_environment
        import tempfile
        client = _make_client(None)
        rs = DazRenderSettings(client)
        with tempfile.NamedTemporaryFile(suffix=".hdr") as f:
            env = HDRIEnvironment(
                image_path=f.name, intensity=1.5, rotation_deg=90.0,
                mode="dome_and_scene", draw_dome=True, resolution=1024,
            )
            apply_hdri_environment(rs, env)
            scripts = [call.args[0] for call in client.execute.call_args_list]
        self.assertEqual(len(scripts), 6)
        self.assertIn("setMap", scripts[0])
        self.assertIn("Environment Intensity", scripts[1])
        self.assertIn("1.5", scripts[1])
        self.assertIn("Dome Rotation", scripts[2])
        self.assertIn("90.0", scripts[2])
        self.assertIn("Environment Mode", scripts[3])
        self.assertIn("Dome and Scene", scripts[3])
        self.assertIn("Draw Dome", scripts[4])
        self.assertIn("true", scripts[4])
        self.assertIn("Environment Lighting Resolution", scripts[5])
        self.assertIn("1024", scripts[5])

    def test_apply_skips_resolution_property_when_none(self):
        from dazpy._render import DazRenderSettings
        from dazpy.lighting import HDRIEnvironment, apply_hdri_environment
        import tempfile
        client = _make_client(None)
        rs = DazRenderSettings(client)
        with tempfile.NamedTemporaryFile(suffix=".hdr") as f:
            env = HDRIEnvironment(image_path=f.name)
            apply_hdri_environment(rs, env)
            scripts = [call.args[0] for call in client.execute.call_args_list]
        self.assertEqual(len(scripts), 5)
        self.assertFalse(any("Environment Lighting Resolution" in s for s in scripts))

    def test_apply_maps_each_mode_to_correct_dazscript_label(self):
        from dazpy._render import DazRenderSettings
        from dazpy.lighting import HDRIEnvironment, apply_hdri_environment
        import tempfile
        expected = {
            "dome_only": "Dome Only",
            "dome_and_scene": "Dome and Scene",
            "scene_only": "Scene Only",
        }
        for mode, label in expected.items():
            with self.subTest(mode=mode):
                client = _make_client(None)
                rs = DazRenderSettings(client)
                with tempfile.NamedTemporaryFile(suffix=".hdr") as f:
                    env = HDRIEnvironment(image_path=f.name, mode=mode)
                    apply_hdri_environment(rs, env)
                    scripts = [call.args[0] for call in client.execute.call_args_list]
                mode_script = next(s for s in scripts if "Environment Mode" in s)
                self.assertIn(label, mode_script)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dazpy.py -v -k TestHDRIEnvironment`
Expected: FAIL (`ImportError: cannot import name 'apply_hdri_environment'`) for the five new tests; the two Task 3 tests still pass.

- [ ] **Step 3: Implement the function**

Add to `dazpy/lighting.py`, after the `HDRIEnvironment` dataclass:

```python
_HDRI_MODE_LABELS = {
    "dome_only": "Dome Only",
    "dome_and_scene": "Dome and Scene",
    "scene_only": "Scene Only",
}


def apply_hdri_environment(render_settings: DazRenderSettings, env: HDRIEnvironment) -> None:
    """Apply image-based (HDRI/dome) lighting via *render_settings*.

    Args:
        render_settings: A :class:`~dazpy.DazRenderSettings`.
        env: The environment configuration.

    Raises:
        FileNotFoundError: If ``env.image_path`` does not exist on disk.
            Checked before any DazScript call is made -- an invalid path
            passed to the underlying ``setMap()`` call can hang or crash
            DAZ Studio via a blocking file-not-found dialog.
        ValueError: If ``env.mode`` is not one of ``"dome_only"``,
            ``"dome_and_scene"``, ``"scene_only"``.
    """
    if not os.path.isfile(env.image_path):
        raise FileNotFoundError(f"HDRI/environment map not found: {env.image_path}")
    if env.mode not in _HDRI_MODE_LABELS:
        raise ValueError(
            f"Invalid HDRIEnvironment.mode {env.mode!r}; must be one of {sorted(_HDRI_MODE_LABELS)}"
        )
    render_settings._set_environment_map(env.image_path)
    render_settings._set_environment_property("Environment Intensity", env.intensity)
    render_settings._set_environment_property("Dome Rotation", env.rotation_deg)
    render_settings._set_environment_property_from_string("Environment Mode", _HDRI_MODE_LABELS[env.mode])
    render_settings._set_environment_property("Draw Dome", env.draw_dome)
    if env.resolution is not None:
        render_settings._set_environment_property("Environment Lighting Resolution", env.resolution)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_dazpy.py -v -k TestHDRIEnvironment`
Expected: PASS (7 tests total in this class)

- [ ] **Step 5: Commit**

```bash
git add dazpy/lighting.py tests/test_dazpy.py
git commit -m "Add apply_hdri_environment"
```

---

### Task 5: Package exports

**Files:**
- Modify: `dazpy/__init__.py` (add `HDRIEnvironment`, `apply_hdri_environment` to the `.lighting` import and `__all__`)
- Test: `tests/test_dazpy.py` (modify `TestLightingExports`)

**Interfaces:**
- Consumes: `HDRIEnvironment`, `apply_hdri_environment` (Tasks 3-4).
- Produces: nothing further downstream — this is the final task.

- [ ] **Step 1: Write the failing test**

In `tests/test_dazpy.py`, modify `TestLightingExports.test_lighting_symbols_importable_from_top_level_package` (currently at line 5447) to add these assertions:

```python
class TestLightingExports(unittest.TestCase):
    def test_lighting_symbols_importable_from_top_level_package(self):
        import dazpy
        self.assertTrue(hasattr(dazpy, "LightSpec"))
        self.assertTrue(hasattr(dazpy, "ThreePointLightSetup"))
        self.assertTrue(hasattr(dazpy, "ThreePointLightRig"))
        self.assertTrue(hasattr(dazpy, "apply_three_point_light_setup"))
        self.assertTrue(hasattr(dazpy, "HDRIEnvironment"))
        self.assertTrue(hasattr(dazpy, "apply_hdri_environment"))
        self.assertIn("LightSpec", dazpy.__all__)
        self.assertIn("ThreePointLightSetup", dazpy.__all__)
        self.assertIn("ThreePointLightRig", dazpy.__all__)
        self.assertIn("apply_three_point_light_setup", dazpy.__all__)
        self.assertIn("HDRIEnvironment", dazpy.__all__)
        self.assertIn("apply_hdri_environment", dazpy.__all__)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dazpy.py -v -k test_lighting_symbols_importable_from_top_level_package`
Expected: FAIL (`AssertionError: False is not true` on the `HDRIEnvironment` check)

- [ ] **Step 3: Add the exports**

In `dazpy/__init__.py`, find the existing lighting import block:

```python
from .lighting import (
    LightSpec,
    ThreePointLightSetup,
    ThreePointLightRig,
    apply_three_point_light_setup,
)
```

Replace with:

```python
from .lighting import (
    LightSpec,
    ThreePointLightSetup,
    ThreePointLightRig,
    apply_three_point_light_setup,
    HDRIEnvironment,
    apply_hdri_environment,
)
```

Find the corresponding entries in `__all__`:

```python
    "LightSpec",
    "ThreePointLightSetup",
    "ThreePointLightRig",
    "apply_three_point_light_setup",
```

Replace with:

```python
    "LightSpec",
    "ThreePointLightSetup",
    "ThreePointLightRig",
    "apply_three_point_light_setup",
    "HDRIEnvironment",
    "apply_hdri_environment",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dazpy.py -v -k test_lighting_symbols_importable_from_top_level_package`
Expected: PASS

- [ ] **Step 5: Run the full test file to confirm no regressions**

Run: `python -m pytest tests/test_dazpy.py -v`
Expected: PASS (all tests, including all new tests from Tasks 1-5)

- [ ] **Step 6: Commit**

```bash
git add dazpy/__init__.py tests/test_dazpy.py
git commit -m "Export HDRIEnvironment and apply_hdri_environment from dazpy package"
```

---

### Task 6: Close out the beads issue

**Files:** None (bookkeeping only).

- [ ] **Step 1: Close the issue**

```bash
bd close daz-script-server-x6sy --reason="Implemented HDRIEnvironment/apply_hdri_environment per docs/superpowers/specs/2026-08-07-dazpy-hdri-environment-design.md"
```

- [ ] **Step 2: Push**

```bash
git push
git status
```

Expected: working tree clean, branch up to date with origin.
