# dazpy Script-Call Batching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut the number of independent DazScript evaluations dazpy issues for repeated transforms, property writes, pose operations, and convenience helpers, without changing existing synchronous semantics.

**Architecture:** Each fix replaces a Python-side loop of `client.execute()` calls with one generated DazScript IIFE that does the looping/iteration inside Studio. High-level bulk APIs (`set_transform`, `set_properties`, `set_state`) are added alongside existing single-field setters. `Batch` gets a new `add_operation()`/`add_prelude()` primitive so future helpers can compose into an explicit batch instead of writing raw JS fragments. Async batch submission reuses the existing `/execute/async` endpoint — no C++ route changes needed, since `Batch` already collapses N operations into one script. C++ changes are confined to Task 6 (main-thread wait / batch-size metrics).

**Tech Stack:** Python 3 (dazpy SDK), `unittest`/`unittest.mock`, C++17 (DAZ Studio SDK 4/6, Qt4/Qt6), `httplib`.

**Spec:** `docs/superpowers/plans/2026-08-21-script-call-batching.md` (design spec this plan implements — read it first; this plan is the step-by-step execution of its Tasks 1–7).

## Global Constraints

- DazScript execution happens only on Studio's main thread; nothing in this plan may call DAZ API objects from Python or from an HTTP worker thread.
- A batch is one DazScript evaluation → one `/execute` or `/execute/async` HTTP request. Never loop over multiple independent evaluations to "batch" something.
- Do not implicitly batch ordinary property reads/writes — `get_property()`/`set_property()` must keep returning/applying immediately, one call each.
- Do not touch the Studio-busy fast-fail design (`docs/superpowers/specs/2026-07-22-studio-busy-handling-design.md`).
- Preserve raw-vs-computed value rules already documented in `dazpy/_pose.py` (~lines 117–125) around `DzERCLink` and `setRawValue()` vs `setValue()` — Task 3C must not silently change which one a given write path uses.
- No new automatic retry or implicit global request serialization.
- C++ changes must build under both `./build.sh build --clean` (SDK4) and `./build.sh build --sdk-version 6 --clean` (SDK6) before being considered done — there is no C++ unit-test harness in this repo (only `test_securerandom.cpp`, a standalone), so C++ correctness is verified by build + the manual Studio smoke test in Task 6, not by automated tests.

---

## Task 1 — Call-count baseline tests

**Files:**
- Modify: `tests/test_dazpy.py`

**Interfaces:**
- Consumes: existing `dazpy._client.DazClient`, `dazpy.poses.reset_transforms`, `dazpy.poses.zero_figure`, `dazpy._element.DazElement.snapshot`, `dazpy._skeleton.DazSkeleton`, `dazpy._batch.Batch` (all pre-existing).
- Produces: nothing new — this task only adds tests that pin down current `client.execute.call_count` values so Tasks 2–4 have a before/after to diff against. These tests are expected to be **edited down** (not left green forever) as each helper is fixed in Task 2/3 — each Task 2/3 test step explicitly updates the matching assertion here.

Existing test file already has a `_make_client(value)` helper used throughout `TestBatch` (`tests/test_dazpy.py:502`) that returns a `MagicMock` client whose `.execute()` returns an `ExecutionResult`-shaped mock. Confirm its exact shape before writing new tests:

- [ ] **Step 1: Read the existing `_make_client` helper**

Run: search `tests/test_dazpy.py` for `def _make_client` and read its body (it is used by `TestBatch` and the interaction-adapter tests already). Reuse it verbatim for the new tests below — do not write a second mock helper.

- [ ] **Step 2: Write baseline characterization tests**

Add a new test class to `tests/test_dazpy.py`:

```python
class TestCallCountBaseline(unittest.TestCase):
    """Pins down pre-batching call counts. Update these assertions in the
    same commit that fixes the corresponding helper in Task 2/3 — do not
    let this class silently mask a regression by staying loose."""

    def test_snapshot_issues_one_call_per_field_before_fix(self):
        client = _make_client(1.0)
        from dazpy._element import DazElement
        el = DazElement(client, "Scene.findNode('Fig')")
        el.snapshot(["Smile", "Blink", "EyesClosed"])
        self.assertEqual(client.execute.call_count, 3)

    def test_reset_transforms_issues_three_calls_before_fix(self):
        client = _make_client(None)
        from dazpy._node import DazNode, NodeIdentifier
        from dazpy.poses import reset_transforms
        node = DazNode(client, NodeIdentifier("name", "Camera"))
        reset_transforms(node)
        self.assertEqual(client.execute.call_count, 3)

    def test_zero_figure_default_issues_four_calls_before_fix(self):
        client = MagicMock()
        client.execute.side_effect = [
            _result({"Hip": [0, 0, 0]}),   # bone_rotations()
            _result({"Smile": 0.5}),        # morph_values(nonzero_only=True)
            _result(None),                  # set_bone_rotations()
            _result(None),                  # set_morph_values()
        ]
        from dazpy._skeleton import DazSkeleton
        from dazpy._node import NodeIdentifier
        from dazpy.poses import zero_figure
        skel = DazSkeleton(client, NodeIdentifier("name", "Genesis9"))
        zero_figure(skel)
        self.assertEqual(client.execute.call_count, 4)

    def test_batch_add_issues_one_call_for_two_ops(self):
        client = _make_client({"_r0": 10, "_r1": 5})
        from dazpy._batch import Batch
        with Batch(client) as b:
            b.add(["var _r0 = Scene.getNumNodes();"])
            b.add(["var _r1 = Scene.getFrame();"])
        self.assertEqual(client.execute.call_count, 1)
```

Add the small `_result(value)` helper next to `_make_client` if it does not already exist:

```python
def _result(value):
    r = MagicMock()
    r.value = value
    return r
```

- [ ] **Step 3: Run and confirm the baseline is captured**

Run: `python -m pytest tests/test_dazpy.py -k TestCallCountBaseline -v`
Expected: all 4 tests PASS, proving current (pre-fix) call counts.

- [ ] **Step 4: Commit**

```bash
git add tests/test_dazpy.py
git commit -m "test: characterize dazpy script call counts before batching"
```

---

## Task 2A — Single-call `DazElement.snapshot()`

**Files:**
- Modify: `dazpy/_element.py:115-127`
- Modify: `tests/test_dazpy.py` (`TestCallCountBaseline.test_snapshot_issues_one_call_per_field_before_fix`)

**Interfaces:**
- Consumes: `ScriptBuilder.iife(body: str) -> str` (`dazpy/_script_builder.py:10`), `self._locator: str`, `self._client.execute(script) -> ExecutionResult`.
- Produces: `DazElement.snapshot(fields: list[str]) -> dict` — same public signature and return shape as before (unchanged).

- [ ] **Step 1: Write the failing test**

In `tests/test_dazpy.py`, add to a `TestDazElementSnapshot` class (new):

```python
class TestDazElementSnapshot(unittest.TestCase):
    def test_snapshot_issues_exactly_one_call(self):
        client = _make_client({"Smile": 0.8, "Blink": 0.0, "EyesClosed": None})
        from dazpy._element import DazElement
        el = DazElement(client, "Scene.findNode('Fig')")
        result = el.snapshot(["Smile", "Blink", "EyesClosed"])
        self.assertEqual(client.execute.call_count, 1)
        self.assertEqual(result, {"Smile": 0.8, "Blink": 0.0, "EyesClosed": None})

    def test_snapshot_escapes_labels_with_quotes_and_backslashes(self):
        client = _make_client({})
        from dazpy._element import DazElement
        el = DazElement(client, "Scene.findNode('Fig')")
        el.snapshot(['Weird "Label"', "Back\\slash"])
        script = client.execute.call_args[0][0]
        self.assertIn(json.dumps('Weird "Label"'), script)
        self.assertIn(json.dumps("Back\\slash"), script)

    def test_snapshot_missing_owner_returns_none_for_all_fields(self):
        client = _make_client(None)  # script's top-level `if (!obj) return null;`
        from dazpy._element import DazElement
        el = DazElement(client, "Scene.findNode('Missing')")
        result = el.snapshot(["Smile", "Blink"])
        self.assertEqual(result, {"Smile": None, "Blink": None})
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_dazpy.py -k TestDazElementSnapshot -v`
Expected: `test_snapshot_issues_exactly_one_call` FAILS — `call_count` is 3, not 1 (current loop-based implementation).

- [ ] **Step 3: Implement the single-call version**

Replace `dazpy/_element.py:115-127`:

```python
def snapshot(self, fields: list[str]) -> dict:
    """Read and cache a set of property values in a single call.

    Args:
        fields: Property labels to read.

    Returns:
        A dict mapping each label to its current value. Missing owner or
        missing property both resolve to ``None`` for the affected label(s).
    """
    cache = object.__getattribute__(self, "_cache")
    fields_json = json.dumps(fields)
    script = ScriptBuilder.iife(f"""
        var obj = {self._locator};
        if (!obj) return null;
        var _fields = {fields_json};
        var _result = {{}};
        for (var i = 0; i < _fields.length; i++) {{
            var prop = obj.findPropertyByLabel(_fields[i]);
            _result[_fields[i]] = prop ? prop.getValue() : null;
        }}
        return _result;
    """)
    values = self._client.execute(script).value or {}
    for field in fields:
        cache[field] = values.get(field)
    return {f: cache[f] for f in fields}
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_dazpy.py -k TestDazElementSnapshot -v`
Expected: all 3 tests PASS.

- [ ] **Step 5: Update the Task 1 baseline assertion**

In `TestCallCountBaseline`, delete `test_snapshot_issues_one_call_per_field_before_fix` (its premise — "one call per field" — is now false; it's superseded by `TestDazElementSnapshot.test_snapshot_issues_exactly_one_call`).

- [ ] **Step 6: Run full dazpy unit suite**

Run: `python -m pytest tests/test_dazpy.py -q`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add dazpy/_element.py tests/test_dazpy.py
git commit -m "perf: make DazElement.snapshot() a single DazScript evaluation"
```

---

## Task 2B — Single-call `reset_transforms()` via `DazNode.set_transform()`

This task is folded together with Task 3A (`set_transform()` is the primitive; `reset_transforms()` becomes a one-line caller) because `reset_transforms()` cannot be fixed without the bulk-transform method existing first. Implementing it twice (once ad hoc, once as the real API) would violate DRY.

**Files:**
- Modify: `dazpy/_node.py` (add `set_transform` near `set_scale`, `set_local_position`, `set_local_rotation`)
- Modify: `dazpy/poses.py:34-44`
- Modify: `tests/test_dazpy.py`

**Interfaces:**
- Consumes: `ScriptBuilder.node_body(identifier, body) -> str` (`dazpy/_script_builder.py:30`), `self._identifier: NodeIdentifier`.
- Produces: `DazNode.set_transform(position=None, rotation=None, scale=None) -> None` — every argument optional; omitted components are left untouched; no-op if all three are `None`.

- [ ] **Step 1: Write the failing tests**

```python
class TestDazNodeSetTransform(unittest.TestCase):
    def test_all_components_issue_one_call(self):
        client = _make_client(None)
        from dazpy._node import DazNode, NodeIdentifier
        node = DazNode(client, NodeIdentifier("name", "Camera"))
        node.set_transform(position=(1.0, 2.0, 3.0), rotation=(4.0, 5.0, 6.0), scale=(1.5, 1.5, 1.5))
        self.assertEqual(client.execute.call_count, 1)
        script = client.execute.call_args[0][0]
        self.assertIn("setLocalPos", script)
        self.assertIn("getXRotControl", script)
        self.assertIn("getXScaleControl", script)

    def test_omitted_component_not_present_in_script(self):
        client = _make_client(None)
        from dazpy._node import DazNode, NodeIdentifier
        node = DazNode(client, NodeIdentifier("name", "Camera"))
        node.set_transform(position=(1.0, 2.0, 3.0))
        script = client.execute.call_args[0][0]
        self.assertIn("setLocalPos", script)
        self.assertNotIn("getXRotControl", script)
        self.assertNotIn("getXScaleControl", script)

    def test_no_arguments_is_a_noop(self):
        client = _make_client(None)
        from dazpy._node import DazNode, NodeIdentifier
        node = DazNode(client, NodeIdentifier("name", "Camera"))
        node.set_transform()
        client.execute.assert_not_called()


class TestResetTransforms(unittest.TestCase):
    def test_reset_transforms_issues_exactly_one_call(self):
        client = _make_client(None)
        from dazpy._node import DazNode, NodeIdentifier
        from dazpy.poses import reset_transforms
        node = DazNode(client, NodeIdentifier("name", "Camera"))
        reset_transforms(node)
        self.assertEqual(client.execute.call_count, 1)
        script = client.execute.call_args[0][0]
        self.assertIn("setLocalPos", script)
        self.assertIn("getXRotControl", script)
        self.assertIn("getXScaleControl", script)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_dazpy.py -k "TestDazNodeSetTransform or TestResetTransforms" -v`
Expected: FAIL — `set_transform` does not exist yet (`AttributeError`).

- [ ] **Step 3: Implement `DazNode.set_transform()`**

Add to `dazpy/_node.py`, near `set_scale` (`dazpy/_node.py:130-145`):

```python
def set_transform(
    self,
    position: tuple[float, float, float] | None = None,
    rotation: tuple[float, float, float] | None = None,
    scale: tuple[float, float, float] | None = None,
) -> None:
    """Set any combination of local position, rotation, and scale in one call.

    Every argument is optional. Omitted components are left untouched.
    Equivalent to calling :meth:`set_local_position`, :meth:`set_local_rotation`,
    and/or :meth:`set_scale` individually, but round-trips only once.

    Args:
        position: ``(x, y, z)`` local-space position, or ``None`` to leave unchanged.
        rotation: ``(x, y, z)`` Euler rotation in degrees, or ``None`` to leave unchanged.
        scale: ``(x, y, z)`` per-axis scale, or ``None`` to leave unchanged.
    """
    lines = []
    if position is not None:
        x, y, z = position
        lines.append(f"_node.setLocalPos(new DzVec3({x}, {y}, {z}));")
    if rotation is not None:
        x, y, z = rotation
        lines.append(
            f"_node.getXRotControl().setValue({x}); "
            f"_node.getYRotControl().setValue({y}); "
            f"_node.getZRotControl().setValue({z});"
        )
    if scale is not None:
        x, y, z = scale
        lines.append(
            f"_node.getXScaleControl().setValue({x}); "
            f"_node.getYScaleControl().setValue({y}); "
            f"_node.getZScaleControl().setValue({z});"
        )
    if not lines:
        return
    script = ScriptBuilder.node_body(self._identifier, "\n".join(lines))
    self._client.execute(script)
```

- [ ] **Step 4: Rewrite `reset_transforms()`**

Replace `dazpy/poses.py:34-44`:

```python
def reset_transforms(node: "DazNode") -> None:
    """Reset *node*'s local position and rotation to zero, and scale to 1.0.

    Works on any :class:`~dazpy.DazNode` — camera, prop, or figure root.
    Uses a single DazScript evaluation via :meth:`~dazpy.DazNode.set_transform`.

    Args:
        node: The node to reset.
    """
    node.set_transform(
        position=(0.0, 0.0, 0.0),
        rotation=(0.0, 0.0, 0.0),
        scale=(1.0, 1.0, 1.0),
    )
```

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest tests/test_dazpy.py -k "TestDazNodeSetTransform or TestResetTransforms" -v`
Expected: all PASS.

- [ ] **Step 6: Update the Task 1 baseline**

Delete `test_reset_transforms_issues_three_calls_before_fix` from `TestCallCountBaseline` (superseded by `TestResetTransforms.test_reset_transforms_issues_exactly_one_call`).

- [ ] **Step 7: Run full suite and commit**

```bash
python -m pytest tests/test_dazpy.py -q
git add dazpy/_node.py dazpy/poses.py tests/test_dazpy.py
git commit -m "feat: add DazNode.set_transform() and rebuild reset_transforms() on it"
```

This also completes **Task 3A** from the spec (node transforms bulk API) — no separate task needed.

---

## Task 2C — Single-call default `zero_figure()`

**Files:**
- Modify: `dazpy/poses.py:47-89`
- Modify: `tests/test_dazpy.py`

**Interfaces:**
- Consumes: `self._skeleton_body(body) -> str` is private to `DazSkeleton`; `zero_figure()` is a free function in `poses.py`, so it must call through public/semi-public skeleton surface. Add a small private helper method on `DazSkeleton` for this rather than reaching into `_skeleton_body` from outside the class.
- Produces: `DazSkeleton._zero_bones_and_morphs() -> None` (new, private — same module-private convention as `_skeleton_body`), called by `zero_figure()`.

Reminder from the spec (`docs/superpowers/plans/2026-08-21-script-call-batching.md` Task 2C): only the **default** (`include_props=False`) path changes. The `include_props=True` path stays on `DazPose.apply_full()` unchanged — do not touch it.

- [ ] **Step 1: Write the failing test**

```python
class TestZeroFigureDefaultPath(unittest.TestCase):
    def test_default_mode_issues_exactly_one_call(self):
        client = _make_client(None)
        from dazpy._skeleton import DazSkeleton
        from dazpy._node import NodeIdentifier
        from dazpy.poses import zero_figure
        skel = DazSkeleton(client, NodeIdentifier("name", "Genesis9"))
        zero_figure(skel)
        self.assertEqual(client.execute.call_count, 1)
        script = client.execute.call_args[0][0]
        self.assertIn("getAllBones", script)
        self.assertIn("DzMorph", script)

    def test_default_mode_zeroes_bones_and_nonzero_morphs_only(self):
        client = _make_client(None)
        from dazpy._skeleton import DazSkeleton
        from dazpy._node import NodeIdentifier
        from dazpy.poses import zero_figure
        skel = DazSkeleton(client, NodeIdentifier("name", "Genesis9"))
        zero_figure(skel)
        script = client.execute.call_args[0][0]
        # Bone rotation controls are set to 0, not read-then-compared.
        self.assertIn("setValue(0)", script)

    def test_include_props_true_still_uses_apply_full(self):
        client = _make_client(None)
        from dazpy._skeleton import DazSkeleton
        from dazpy._node import NodeIdentifier
        from dazpy.poses import zero_figure
        skel = DazSkeleton(client, NodeIdentifier("name", "Genesis9"))
        with patch("dazpy._pose.DazPose.apply_full") as mock_apply_full:
            zero_figure(skel, include_props=True)
        mock_apply_full.assert_called_once()
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_dazpy.py -k TestZeroFigureDefaultPath -v`
Expected: `test_default_mode_issues_exactly_one_call` FAILS — current implementation makes 4 calls (2 reads via `bone_rotations()`/`morph_values()`, 2 writes via `set_bone_rotations()`/`set_morph_values()`).

- [ ] **Step 3: Add the single-script zeroing method to `DazSkeleton`**

Add to `dazpy/_skeleton.py`, near `set_bone_rotations`/`set_morph_values`:

```python
def _zero_bones_and_morphs(self) -> None:
    """Drive every bone rotation to 0 and every non-zero DzMorph to 0, in
    one DazScript evaluation. Used by :func:`~dazpy.poses.zero_figure`'s
    default (``include_props=False``) path — does not touch node-level
    properties or the figure root transform.
    """
    script = self._skeleton_body("""
        var _bones = _node.getAllBones();
        for (var i = 0; i < _bones.length; i++) {
            var _b = _bones[i];
            _b.getXRotControl().setValue(0);
            _b.getYRotControl().setValue(0);
            _b.getZRotControl().setValue(0);
        }
        var _obj = _node.getObject();
        if (_obj) {
            for (var j = 0; j < _obj.getNumModifiers(); j++) {
                var _m = _obj.getModifier(j);
                if (_m.className() === "DzMorph") {
                    var _ch = _m.getValueChannel();
                    if (Math.abs(_ch.getValue()) > 0.0001) {
                        _ch.setValue(0);
                    }
                }
            }
        }
    """)
    self._client.execute(script)
```

- [ ] **Step 4: Rewrite `zero_figure()`'s default branch**

In `dazpy/poses.py`, replace lines 84-88 (the `zero_bones`/`zero_morphs`/`set_bone_rotations`/`set_morph_values` block) — keep everything above it (the docstring and the `include_props` branch) unchanged:

```python
    if include_props:
        pose = DazPose(figure=skeleton._identifier.value, bones={}, morphs={}, props={})
        pose.apply_full(skeleton)
        return

    skeleton._zero_bones_and_morphs()
```

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest tests/test_dazpy.py -k TestZeroFigureDefaultPath -v`
Expected: all PASS.

- [ ] **Step 6: Update the Task 1 baseline**

Delete `test_zero_figure_default_issues_four_calls_before_fix` from `TestCallCountBaseline`.

- [ ] **Step 7: Run full suite and commit**

```bash
python -m pytest tests/test_dazpy.py -q
git add dazpy/_skeleton.py dazpy/poses.py tests/test_dazpy.py
git commit -m "perf: zero_figure() default path uses one DazScript evaluation"
```

---

## Task 3B — `DazElement.set_properties()` bulk write

**Files:**
- Modify: `dazpy/_element.py` (add near `set_property`, `dazpy/_element.py:44-60`)
- Modify: `tests/test_dazpy.py`

**Interfaces:**
- Consumes: `ScriptBuilder.iife`, `self._locator`.
- Produces: `DazElement.set_properties(values: dict[str, object]) -> dict[str, bool]` — returns `{label: True}` for labels that resolved to a real property, `{label: False}` for labels that did not (mirrors `set_property`'s `{"error": "property_not_found"}` semantics but keyed per-label instead of failing the whole call).

- [ ] **Step 1: Write the failing tests**

```python
class TestDazElementSetProperties(unittest.TestCase):
    def test_multiple_mutations_issue_one_call(self):
        client = _make_client({"Smile": True, "Blink": True})
        from dazpy._element import DazElement
        el = DazElement(client, "Scene.findNode('Fig')")
        result = el.set_properties({"Smile": 0.8, "Blink": 0.2})
        self.assertEqual(client.execute.call_count, 1)
        self.assertEqual(result, {"Smile": True, "Blink": True})

    def test_missing_property_reported_false(self):
        client = _make_client({"Smile": True, "Nonexistent": False})
        from dazpy._element import DazElement
        el = DazElement(client, "Scene.findNode('Fig')")
        result = el.set_properties({"Smile": 0.8, "Nonexistent": 1.0})
        self.assertEqual(result, {"Smile": True, "Nonexistent": False})

    def test_labels_with_quotes_backslashes_newlines_are_json_safe(self):
        client = _make_client({})
        from dazpy._element import DazElement
        el = DazElement(client, "Scene.findNode('Fig')")
        el.set_properties({'Weird "Label"': 1, "Multi\nLine": 2, "Back\\Slash": 3})
        script = client.execute.call_args[0][0]
        # json.dumps of the whole values dict must appear verbatim, proving
        # no manual string concatenation was used for the mutation payload.
        payload = json.dumps({'Weird "Label"': 1, "Multi\nLine": 2, "Back\\Slash": 3})
        self.assertIn(payload, script)
        self.assertNotIn("for (var _label in", "")  # placeholder to keep flake happy; real assertion below
        self.assertIn("_data.hasOwnProperty" if "_data.hasOwnProperty" in script else "hasOwnProperty", script)
```

(Drop the placeholder `assertNotIn` line above when writing the real file — it exists only to flag that the loop-membership check must use `hasOwnProperty`, matching the pattern already used in `set_bone_rotations`/`set_morph_values`. Write the test as:)

```python
    def test_labels_with_quotes_backslashes_newlines_are_json_safe(self):
        client = _make_client({})
        from dazpy._element import DazElement
        el = DazElement(client, "Scene.findNode('Fig')")
        el.set_properties({'Weird "Label"': 1, "Multi\nLine": 2, "Back\\Slash": 3})
        script = client.execute.call_args[0][0]
        payload = json.dumps({'Weird "Label"': 1, "Multi\nLine": 2, "Back\\Slash": 3})
        self.assertIn(payload, script)
        self.assertIn("hasOwnProperty", script)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_dazpy.py -k TestDazElementSetProperties -v`
Expected: FAIL — `set_properties` does not exist (`AttributeError`).

- [ ] **Step 3: Implement `set_properties()`**

Add to `dazpy/_element.py`, after `set_property` (`dazpy/_element.py:60`):

```python
def set_properties(self, values: dict[str, object]) -> dict[str, bool]:
    """Set multiple property values by display label in one call.

    Args:
        values: ``{label: value}``. Each value must be JSON-serialisable.

    Returns:
        ``{label: True}`` for labels that resolved to a real property and
        were written, ``{label: False}`` for labels that did not resolve.
    """
    data_json = json.dumps(values)
    script = ScriptBuilder.iife(f"""
        var obj = {self._locator};
        if (!obj) return null;
        var _data = {data_json};
        var _result = {{}};
        for (var _label in _data) {{
            if (!_data.hasOwnProperty(_label)) continue;
            var prop = obj.findPropertyByLabel(_label);
            if (prop) {{
                prop.setValue(_data[_label]);
                _result[_label] = true;
            }} else {{
                _result[_label] = false;
            }}
        }}
        return _result;
    """)
    return self._client.execute(script).value or {}
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_dazpy.py -k TestDazElementSetProperties -v`
Expected: all PASS.

- [ ] **Step 5: Run full suite and commit**

```bash
python -m pytest tests/test_dazpy.py -q
git add dazpy/_element.py tests/test_dazpy.py
git commit -m "feat: add DazElement.set_properties() for one-call bulk property writes"
```

---

## Task 3C — `DazSkeleton.set_state()` combined bone/morph/prop write

**Files:**
- Modify: `dazpy/_skeleton.py` (add near `set_bone_rotations`/`set_morph_values`, `dazpy/_skeleton.py:224-447`)
- Modify: `tests/test_dazpy.py`

**Interfaces:**
- Consumes: `self._skeleton_body(body) -> str`.
- Produces: `DazSkeleton.set_state(bones: dict | None = None, morphs: dict | None = None, props: dict | None = None) -> None`.

Before writing code, read `dazpy/_pose.py` around lines 117-125 (the `DzERCLink` comment) to confirm which write method (`setValue()` vs `setRawValue()`) each of `bones`/`morphs`/`props` should use in `set_state()`. `set_bone_rotations()` and `set_morph_values()` already use plain `setValue()` — `set_state()` must match those two exactly for `bones`/`morphs` (it is explicitly a combination of the existing two calls, not a new value-writing strategy). The `props` argument writes node-level properties the same way `set_property()` does (`prop.setValue(...)`) — this is a new capability the current class does not have; it is not a raw/computed distinction covered by the ERC comment, since node properties are not routed through `DazPose.apply_full()`'s ERC-avoidance logic. Document this explicitly in the docstring so a future reader does not assume `set_state(props=...)` is ERC-safe the way `apply_full()` is.

- [ ] **Step 1: Read `dazpy/_pose.py:100-140` to confirm the ERC comment's scope**

Run: read the file section; confirm it applies to `DazPose.apply_full()` and node-property ERC links specifically, not to `set_bone_rotations`/`set_morph_values`. Record the finding as a one-line code comment in Step 3 rather than re-deriving it later.

- [ ] **Step 2: Write the failing tests**

```python
class TestDazSkeletonSetState(unittest.TestCase):
    def test_all_three_kinds_issue_one_call(self):
        client = _make_client(None)
        from dazpy._skeleton import DazSkeleton
        from dazpy._node import NodeIdentifier
        skel = DazSkeleton(client, NodeIdentifier("name", "Genesis9"))
        skel.set_state(
            bones={"Hip": (0.0, 0.0, 0.0)},
            morphs={"Smile": 0.8},
            props={"Scale": 100.0},
        )
        self.assertEqual(client.execute.call_count, 1)
        script = client.execute.call_args[0][0]
        self.assertIn("getAllBones", script)
        self.assertIn("DzMorph", script)
        self.assertIn("getNumProperties", script)

    def test_omitted_kind_not_present_in_script(self):
        client = _make_client(None)
        from dazpy._skeleton import DazSkeleton
        from dazpy._node import NodeIdentifier
        skel = DazSkeleton(client, NodeIdentifier("name", "Genesis9"))
        skel.set_state(bones={"Hip": (0.0, 0.0, 0.0)})
        script = client.execute.call_args[0][0]
        self.assertIn("getAllBones", script)
        self.assertNotIn("DzMorph", script)
        self.assertNotIn("getNumProperties", script)

    def test_all_omitted_is_a_noop(self):
        client = _make_client(None)
        from dazpy._skeleton import DazSkeleton
        from dazpy._node import NodeIdentifier
        skel = DazSkeleton(client, NodeIdentifier("name", "Genesis9"))
        skel.set_state()
        client.execute.assert_not_called()

    def test_bone_and_morph_names_with_quotes_are_json_safe(self):
        client = _make_client(None)
        from dazpy._skeleton import DazSkeleton
        from dazpy._node import NodeIdentifier
        skel = DazSkeleton(client, NodeIdentifier("name", "Genesis9"))
        skel.set_state(bones={'Weird "Bone"': (1.0, 2.0, 3.0)}, morphs={"Back\\Slash": 0.5})
        script = client.execute.call_args[0][0]
        self.assertIn(json.dumps({'Weird "Bone"': [1.0, 2.0, 3.0]}), script)
        self.assertIn(json.dumps({"Back\\Slash": 0.5}), script)
```

- [ ] **Step 3: Run to verify failure**

Run: `python -m pytest tests/test_dazpy.py -k TestDazSkeletonSetState -v`
Expected: FAIL — `set_state` does not exist.

- [ ] **Step 4: Implement `set_state()`**

Add to `dazpy/_skeleton.py`:

```python
def set_state(
    self,
    bones: dict[str, tuple | list] | None = None,
    morphs: dict[str, float] | None = None,
    props: dict[str, object] | None = None,
) -> None:
    """Set bone rotations, morph values, and/or node properties in one call.

    Equivalent to calling :meth:`set_bone_rotations`, :meth:`set_morph_values`,
    and/or repeated :meth:`~dazpy.DazElement.set_property` calls, but
    round-trips only once. Each argument is independently optional.

    ``bones``/``morphs`` use plain ``setValue()`` writes, matching
    :meth:`set_bone_rotations`/:meth:`set_morph_values` exactly — this method
    does not change which write path those two use. ``props`` also uses plain
    ``setValue()`` (like :meth:`~dazpy.DazElement.set_property`); it is NOT
    routed through :meth:`~dazpy.DazPose.apply_full`'s ``DzERCLink``-avoidance
    logic (see ``dazpy/_pose.py`` ~lines 117-125), so on ERC-driven node
    properties this can double-apply a controller contribution the same way
    :meth:`~dazpy.DazElement.set_property` already can.

    Args:
        bones: ``{bone_name: (x, y, z)}`` Euler degrees. Bones not named are unchanged.
        morphs: ``{morph_name: float}``. Morphs not named are unchanged.
        props: ``{property_label: value}`` node-level properties. Properties
            not named are unchanged.
    """
    lines = []
    if bones:
        bones_json = json.dumps({k: list(v) for k, v in bones.items()})
        lines.append(f"""
            var _bonesData = {bones_json};
            var _allBones = _node.getAllBones();
            for (var i = 0; i < _allBones.length; i++) {{
                var _b = _allBones[i];
                var _bn = _b.getName();
                if (_bonesData.hasOwnProperty(_bn)) {{
                    var _r = _bonesData[_bn];
                    _b.getXRotControl().setValue(_r[0]);
                    _b.getYRotControl().setValue(_r[1]);
                    _b.getZRotControl().setValue(_r[2]);
                }}
            }}
        """)
    if morphs:
        morphs_json = json.dumps(morphs)
        lines.append(f"""
            var _morphsData = {morphs_json};
            var _obj = _node.getObject();
            if (_obj) {{
                for (var j = 0; j < _obj.getNumModifiers(); j++) {{
                    var _m = _obj.getModifier(j);
                    if (_m.className() === "DzMorph" && _morphsData.hasOwnProperty(_m.getName())) {{
                        _m.getValueChannel().setValue(_morphsData[_m.getName()]);
                    }}
                }}
            }}
        """)
    if props:
        props_json = json.dumps(props)
        lines.append(f"""
            var _propsData = {props_json};
            for (var k = 0; k < _node.getNumProperties(); k++) {{
                var _p = _node.getProperty(k);
                var _pl = _p.getLabel();
                if (_propsData.hasOwnProperty(_pl)) {{
                    _p.setValue(_propsData[_pl]);
                }}
            }}
        """)
    if not lines:
        return
    script = self._skeleton_body("\n".join(lines))
    self._client.execute(script)
```

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest tests/test_dazpy.py -k TestDazSkeletonSetState -v`
Expected: all PASS.

- [ ] **Step 6: Run full suite and commit**

```bash
python -m pytest tests/test_dazpy.py -q
git add dazpy/_skeleton.py tests/test_dazpy.py
git commit -m "feat: add DazSkeleton.set_state() for combined bone/morph/property writes"
```

---

## Task 4 — Extend `Batch` with `add_operation()`, `add_prelude()`, and limits

**Files:**
- Modify: `dazpy/_batch.py`
- Modify: `dazpy/exceptions.py` (add `BatchLimitExceededError`)
- Modify: `tests/test_dazpy.py`

**Interfaces:**
- Consumes: nothing new from other modules.
- Produces:
  - `Batch(client, max_operations: int = 500, max_script_length: int = 900_000)` — new optional limit params (defaults chosen to stay comfortably under the server's default 1MB script-length cap noted in `CLAUDE.md`; leaves headroom for JSON overhead).
  - `Batch.add_prelude(prelude_key: str, lines: list[str]) -> None` — registers a shared setup block, emitted once per unique `prelude_key` regardless of how many operations reference it.
  - `Batch.add_operation(body_lines: list[str], result_expression: str) -> BatchFuture` — like `add()`, but the caller supplies `result_expression` directly instead of having to know the internally generated `_r{n}` key name. This is the fix for the existing `add()` docstring's own broken example (`dazpy/_batch.py:39-44` shows lines that assign to `pos`/`name`, but `_build_script()` references `_r0`/`_r1` — those never match unless the caller manually names their variable `_r0`). `add_operation()` removes that footgun: the builder assigns `result_expression`'s value to the correct key itself.
  - `BatchLimitExceededError(DazError)` in `dazpy/exceptions.py`, raised by `execute()` before any HTTP call when operation count or script length exceeds the configured limit.

- [ ] **Step 1: Write the failing tests**

```python
class TestBatchAddOperation(unittest.TestCase):
    def test_add_operation_resolves_without_caller_guessing_key(self):
        client = _make_client({"_r0": 42})
        from dazpy._batch import Batch
        batch = Batch(client)
        future = batch.add_operation(
            body_lines=["var x = 20 + 22;"],
            result_expression="x",
        )
        batch.execute()
        self.assertEqual(future.value, 42)
        script = client.execute.call_args[0][0]
        self.assertIn("var _r0 = x;", script)

    def test_shared_prelude_emitted_once_for_two_operations(self):
        client = _make_client({"_r0": 1, "_r1": 2})
        from dazpy._batch import Batch
        batch = Batch(client)
        batch.add_prelude("node:Fig", ["var _node_Fig = Scene.findNode('Fig');"])
        batch.add_operation(body_lines=[], result_expression="_node_Fig.getXRotControl().getValue()")
        batch.add_prelude("node:Fig", ["var _node_Fig = Scene.findNode('Fig');"])  # same key, second call
        batch.add_operation(body_lines=[], result_expression="_node_Fig.getYRotControl().getValue()")
        batch.execute()
        script = client.execute.call_args[0][0]
        self.assertEqual(script.count("Scene.findNode('Fig')"), 1)
        self.assertEqual(client.execute.call_count, 1)

    def test_read_after_write_order_preserved(self):
        client = _make_client({"_r0": None, "_r1": 99})
        from dazpy._batch import Batch
        batch = Batch(client)
        write_future = batch.add_operation(body_lines=["var _v = 99;"], result_expression="null")
        read_future = batch.add_operation(body_lines=[], result_expression="_v")
        batch.execute()
        script = client.execute.call_args[0][0]
        self.assertLess(script.index("var _v = 99;"), script.index("var _r1 = _v;"))

    def test_operation_count_limit_raises_before_execute(self):
        client = _make_client({})
        from dazpy._batch import Batch
        from dazpy.exceptions import BatchLimitExceededError
        batch = Batch(client, max_operations=2)
        batch.add_operation(body_lines=[], result_expression="1")
        batch.add_operation(body_lines=[], result_expression="2")
        with self.assertRaises(BatchLimitExceededError):
            batch.add_operation(body_lines=[], result_expression="3")
        client.execute.assert_not_called()

    def test_script_length_limit_raises_on_execute(self):
        client = _make_client({})
        from dazpy._batch import Batch
        from dazpy.exceptions import BatchLimitExceededError
        batch = Batch(client, max_script_length=50)
        batch.add_operation(body_lines=["var x = 1;" * 20], result_expression="x")
        with self.assertRaises(BatchLimitExceededError):
            batch.execute()
        client.execute.assert_not_called()

    def test_existing_raw_add_still_works_unmodified(self):
        # Regression guard: add_operation()/add_prelude() must not change add()'s behavior.
        client = _make_client({"_r0": 10, "_r1": 5})
        from dazpy._batch import Batch
        with Batch(client) as batch:
            f_count = batch.add(["var _r0 = Scene.getNumNodes();"])
            f_frame = batch.add(["var _r1 = Scene.getFrame();"])
        self.assertEqual(f_count.value, 10)
        self.assertEqual(f_frame.value, 5)
        client.execute.assert_called_once()
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_dazpy.py -k TestBatchAddOperation -v`
Expected: FAIL — `add_operation`, `add_prelude`, `max_operations`, `max_script_length`, `BatchLimitExceededError` do not exist yet. `test_existing_raw_add_still_works_unmodified` should already PASS (it exercises only existing behavior) — confirm that one passes now, before any implementation changes, so a later failure is attributable to your edit.

- [ ] **Step 3: Add `BatchLimitExceededError`**

In `dazpy/exceptions.py`, after `MaterialError` (end of file):

```python
class BatchLimitExceededError(DazError):
    """Raised by :meth:`~dazpy.Batch.execute` (or ``add_operation``, for the
    operation-count limit) when a batch would exceed its configured
    operation-count or generated-script-length limit.

    Raised client-side before any HTTP call, so an oversized batch never
    reaches Studio's main thread.
    """
```

- [ ] **Step 4: Implement `add_prelude`, `add_operation`, and limits in `Batch`**

Replace `dazpy/_batch.py` in full:

```python
from __future__ import annotations

from ._client import DazClient
from .exceptions import BatchLimitExceededError

DEFAULT_MAX_OPERATIONS = 500
DEFAULT_MAX_SCRIPT_LENGTH = 900_000  # stays under the server's default 1MB script cap


class BatchFuture:
    """Placeholder for a single result within a :class:`Batch` execution.

    Created by :meth:`Batch.add` or :meth:`Batch.add_operation`; the
    :attr:`value` property blocks until the batch has been executed.
    """

    def __init__(self, key: str):
        self._key = key
        self._resolved = False
        self._value = None

    @property
    def value(self) -> object:
        """The result value.

        Raises:
            RuntimeError: If :meth:`Batch.execute` has not been called yet.
        """
        if not self._resolved:
            raise RuntimeError("Batch has not been executed yet")
        return self._value

    def _resolve(self, value: object) -> None:
        self._value = value
        self._resolved = True


class Batch:
    """Collect multiple DazScript operations and execute them in a single HTTP round-trip.

    Usage as a context manager (recommended)::

        with Batch(client) as b:
            pos_future  = b.add(["var pos = Scene.findNode('Figure').getWSPos();",
                                  "var pos = [pos.x, pos.y, pos.z];"])
            name_future = b.add(["var name = Scene.findNode('Figure').getName();"])
        # Both futures resolved after the `with` block
        print(pos_future.value, name_future.value)

    Or manually::

        b = Batch(client)
        f = b.add(["var x = 42;"])
        b.execute()
        print(f.value)

    High-level helpers that generate operations programmatically should use
    :meth:`add_operation` instead of :meth:`add` — it does not require the
    caller to know the internally generated result-variable name, and
    :meth:`add_prelude` lets multiple operations share one setup block (e.g.
    a node lookup) emitted only once.

    Args:
        client: The :class:`~dazpy.DazClient` to use.
        max_operations: Maximum number of queued operations before
            :meth:`add_operation` raises :class:`~dazpy.exceptions.BatchLimitExceededError`.
        max_script_length: Maximum generated script length (characters)
            before :meth:`execute` raises :class:`~dazpy.exceptions.BatchLimitExceededError`.
    """

    def __init__(
        self,
        client: DazClient,
        max_operations: int = DEFAULT_MAX_OPERATIONS,
        max_script_length: int = DEFAULT_MAX_SCRIPT_LENGTH,
    ):
        self._client = client
        self._ops: list[tuple[str, list[str], BatchFuture]] = []
        self._preludes: dict[str, list[str]] = {}
        self._prelude_order: list[str] = []
        self._counter = 0
        self._max_operations = max_operations
        self._max_script_length = max_script_length

    def add(self, lines: list[str]) -> BatchFuture:
        """Queue a list of DazScript lines to be included in the batch.

        The last line in *lines* should assign the desired result to a
        variable named after the internally generated key (``_r0``, ``_r1``,
        ... in call order) — inspect a prior :meth:`execute` call's generated
        script if the exact naming matters, or prefer :meth:`add_operation`,
        which does not require guessing the key name.

        Args:
            lines: DazScript source lines (no ``return`` needed).

        Returns:
            A :class:`BatchFuture` that resolves after :meth:`execute`.
        """
        key = f"_r{self._counter}"
        self._counter += 1
        future = BatchFuture(key)
        self._ops.append((key, lines, future))
        return future

    def add_prelude(self, prelude_key: str, lines: list[str]) -> None:
        """Register a shared setup block, emitted once per unique *prelude_key*.

        Call this before :meth:`add_operation` calls whose bodies depend on
        the prelude's bound variable(s) (e.g. a node lookup bound to
        ``_node_Fig``). Repeated calls with the same *prelude_key* are no-ops
        after the first — use this instead of re-emitting an identical lookup
        once per operation.

        Args:
            prelude_key: Stable identifier for this setup block (e.g.
                ``"node:Fig"``). Callers must pick keys that collide exactly
                when — and only when — the generated lines are identical.
            lines: DazScript source lines for the shared setup.
        """
        if prelude_key not in self._preludes:
            self._preludes[prelude_key] = list(lines)
            self._prelude_order.append(prelude_key)

    def add_operation(self, body_lines: list[str], result_expression: str) -> BatchFuture:
        """Queue an operation whose result the builder assigns internally.

        Unlike :meth:`add`, the caller does not need to know the generated
        key name — pass the JS expression that yields the result
        (*result_expression*, e.g. a variable set inside *body_lines*, or a
        literal expression), and the builder emits
        ``var _rN = <result_expression>;`` itself.

        Args:
            body_lines: DazScript source lines with no trailing result
                assignment (side effects only, e.g. property writes).
            result_expression: A JS expression evaluated once, immediately
                after *body_lines* run, and used as this operation's result.
                Mutation-only operations should pass ``"null"``.

        Returns:
            A :class:`BatchFuture` that resolves after :meth:`execute`.

        Raises:
            BatchLimitExceededError: If this call would exceed the batch's
                configured ``max_operations``.
        """
        if len(self._ops) >= self._max_operations:
            raise BatchLimitExceededError(
                f"Batch already has {len(self._ops)} operations "
                f"(max_operations={self._max_operations})"
            )
        key = f"_r{self._counter}"
        self._counter += 1
        future = BatchFuture(key)
        lines = list(body_lines) + [f"var {key} = {result_expression};"]
        self._ops.append((key, lines, future))
        return future

    def _build_script(self) -> str:
        body_lines = []
        for prelude_key in self._prelude_order:
            body_lines.extend(self._preludes[prelude_key])
        return_parts = []
        for key, lines, _ in self._ops:
            body_lines.extend(lines)
            return_parts.append(f'"{key}": {key}')
        return_obj = "{" + ", ".join(return_parts) + "}"
        body_lines.append(f"return {return_obj};")
        body = "\n".join(body_lines)
        return f"(function(){{\n{body}\n}})()"

    def execute(self) -> None:
        """Execute all queued operations in a single HTTP request and resolve all futures.

        Raises:
            BatchLimitExceededError: If the generated script exceeds
                ``max_script_length``. Raised before any HTTP call.
        """
        if not self._ops:
            return
        script = self._build_script()
        if len(script) > self._max_script_length:
            raise BatchLimitExceededError(
                f"Generated batch script is {len(script)} characters "
                f"(max_script_length={self._max_script_length})"
            )
        result = self._client.execute(script)
        data = result.value or {}
        for key, _, future in self._ops:
            future._resolve(data.get(key))

    def __enter__(self) -> "Batch":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is None:
            self.execute()
        return False
```

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest tests/test_dazpy.py -k "TestBatchAddOperation or TestBatch" -v`
Expected: all PASS, including the original `TestBatch` class (`tests/test_dazpy.py:502`) unchanged.

- [ ] **Step 6: Run full suite and commit**

```bash
python -m pytest tests/test_dazpy.py -q
git add dazpy/_batch.py dazpy/exceptions.py tests/test_dazpy.py
git commit -m "feat: extend Batch with add_operation(), add_prelude(), and size limits"
```

---

## Task 5 — One-request async batch submission

**Design decision, validated against the code:** the spec (Task 5) says "prefer reusing the existing async request shape... only add a new `/execute/batch/async` route if the existing payload cannot express the required operation metadata." It cannot't — `Batch._build_script()` (Task 4) already collapses N operations into one script string with a keyed result object; `DazClient.execute_async_submit(script, args)` (`dazpy/_client.py:264-301`) already accepts exactly that shape and submits it as one `AsyncRequestManager::AsyncRequest` (confirmed: `AsyncExecuteHandler` in `src/RequestHandlers.cpp:232-260` and the `/execute/async` route registration in `src/DzScriptServerPane.cpp:1018-1022` take one script + args, no per-operation metadata). **No C++ changes are needed for this task.** `execute_batch_async()` is a pure Python composition of `Batch` + `DazClient.execute_async_submit`.

**Files:**
- Modify: `dazpy/_client.py`
- Modify: `dazpy/_client_aio.py` (defines the real public async class `AsyncDazClient`, exported via `dazpy/aio.py` — do not invent a `DazClientAio` name)
- Modify: `dazpy/_batch.py` (expose the script-building logic for reuse — see Step 3)
- Modify: `tests/test_dazpy.py`
- Modify: `tests/test_dazpy_aio.py`

**Interfaces:**
- Consumes: `Batch._build_script()` (private today; Step 3 promotes a version of it to a free function both `Batch` and the new client methods can call without instantiating a full `Batch`). `tests/test_dazpy_aio.py` already defines `_client_with_mock_http()` and `_mock_resp()` helpers (lines 20-40) and uses `pytest.mark.asyncio` with plain `class Test...:` (not `unittest.IsolatedAsyncioTestCase`) — reuse both helpers verbatim.
- Produces:
  - `DazClient.execute_batch_async(operations: list[dict], args: object = None) -> str` — each `operations[i]` is `{"body_lines": [...], "result_expression": "..."}` (mirrors `add_operation`'s parameters); returns the `request_id` from one `/execute/async` submission.
  - `AsyncDazClient.execute_batch_async(...)` (in `dazpy/_client_aio.py`) — same shape, `async def`.

- [ ] **Step 1: Write the failing tests**

```python
class TestExecuteBatchAsync(unittest.TestCase):
    def test_submits_one_request_for_multiple_operations(self):
        client = DazClient(token="")
        client._session = MagicMock()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"request_id": "batch-async-1", "status": "queued"}
        response.headers = {}
        client._session.post.return_value = response

        request_id = client.execute_batch_async([
            {"body_lines": ["var x = 1;"], "result_expression": "x"},
            {"body_lines": ["var y = 2;"], "result_expression": "y"},
        ])

        self.assertEqual(request_id, "batch-async-1")
        client._session.post.assert_called_once()
        call_args = client._session.post.call_args
        self.assertEqual(call_args[0][0], "http://127.0.0.1:18811/execute/async")
        submitted_script = call_args[1]["json"]["script"]
        self.assertIn("var x = 1;", submitted_script)
        self.assertIn("var y = 2;", submitted_script)
        self.assertIn('"_r0"', submitted_script)
        self.assertIn('"_r1"', submitted_script)

    def test_passes_args_through(self):
        client = DazClient(token="")
        client._session = MagicMock()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"request_id": "batch-async-2", "status": "queued"}
        response.headers = {}
        client._session.post.return_value = response

        client.execute_batch_async(
            [{"body_lines": [], "result_expression": "1"}],
            args={"mode": "probe"},
        )

        submitted_payload = client._session.post.call_args[1]["json"]
        self.assertEqual(submitted_payload["args"], {"mode": "probe"})
```

Add to `tests/test_dazpy_aio.py`, reusing the file's existing `_client_with_mock_http()` / `_mock_resp()` helpers (`tests/test_dazpy_aio.py:20-40`) and its `pytest.mark.asyncio` + plain-class style (see `TestAsyncDazClientExecute`, `tests/test_dazpy_aio.py:43-90`):

```python
class TestAsyncDazClientExecuteBatchAsync:
    @pytest.mark.asyncio
    async def test_submits_one_request_for_multiple_operations(self):
        client, mock_http = _client_with_mock_http()
        mock_http.post.return_value = _mock_resp(
            json_data={"request_id": "batch-async-1", "status": "queued"}
        )

        request_id = await client.execute_batch_async([
            {"body_lines": ["var x = 1;"], "result_expression": "x"},
            {"body_lines": ["var y = 2;"], "result_expression": "y"},
        ])

        assert request_id == "batch-async-1"
        mock_http.post.assert_awaited_once()
        args, kwargs = mock_http.post.call_args
        assert args[0] == "http://127.0.0.1:18811/execute/async"
        submitted_script = kwargs["json"]["script"]
        assert "var x = 1;" in submitted_script
        assert "var y = 2;" in submitted_script
        assert '"_r0"' in submitted_script
        assert '"_r1"' in submitted_script

    @pytest.mark.asyncio
    async def test_passes_args_through(self):
        client, mock_http = _client_with_mock_http()
        mock_http.post.return_value = _mock_resp(
            json_data={"request_id": "batch-async-2", "status": "queued"}
        )

        await client.execute_batch_async(
            [{"body_lines": [], "result_expression": "1"}],
            args={"mode": "probe"},
        )

        _, kwargs = mock_http.post.call_args
        assert kwargs["json"]["args"] == {"mode": "probe"}
```

- [ ] **Step 2: Confirm the mocking pattern still matches**

Run: re-read `tests/test_dazpy_aio.py:20-40` once more immediately before writing the test above into the file — `_client_with_mock_http()`/`_mock_resp()` are the exact fixtures every other test in that file uses; do not add a second mocking mechanism.

- [ ] **Step 3: Run to verify failure**

Run: `python -m pytest tests/test_dazpy.py -k TestExecuteBatchAsync -v`
Expected: FAIL — `execute_batch_async` does not exist yet.

- [ ] **Step 4: Promote script-building to a reusable function**

In `dazpy/_batch.py`, extract the return-object-building logic from `Batch._build_script()` into a module-level function both `Batch` and the new client methods can call:

```python
def build_operations_script(operations: list[tuple[list[str], str]]) -> str:
    """Build one IIFE script from a list of (body_lines, result_expression) pairs.

    Shared by :meth:`Batch._build_script` and
    :meth:`~dazpy.DazClient.execute_batch_async` so both produce scripts with
    identical shape (keyed return object over ``_r0``, ``_r1``, ...).
    """
    body_lines = []
    return_parts = []
    for i, (lines, result_expression) in enumerate(operations):
        key = f"_r{i}"
        body_lines.extend(lines)
        body_lines.append(f"var {key} = {result_expression};")
        return_parts.append(f'"{key}": {key}')
    return_obj = "{" + ", ".join(return_parts) + "}"
    body_lines.append(f"return {return_obj};")
    body = "\n".join(body_lines)
    return f"(function(){{\n{body}\n}})()"
```

Then simplify `Batch._build_script()` to delegate to it for the operation-only case, keeping `add()`'s raw-line behavior (which does NOT auto-assign a result expression) separate — `Batch._build_script()` still needs its own logic because `add()`-created ops don't carry a `result_expression`, only `add_operation()`-created ones do internally already assign their own `var {key} = ...;` line as part of `lines`. **Do not change `Batch._build_script()`'s behavior in this step** — it already works after Task 4; `build_operations_script()` is purely new, for `execute_batch_async()`'s use, and must not be wired into `Batch` itself. (This avoids a risky refactor of already-tested code within this task.)

- [ ] **Step 5: Implement `DazClient.execute_batch_async()`**

Add to `dazpy/_client.py`, after `execute_file_async_submit` (`dazpy/_client.py:303-322`):

```python
def execute_batch_async(self, operations: list[dict], args: object = None) -> str:
    """Submit multiple operations as one async request (one queue slot, one script).

    Args:
        operations: List of ``{"body_lines": [...], "result_expression": "..."}``
            dicts — same shape as :meth:`~dazpy.Batch.add_operation`'s arguments.
        args: Optional argument passed to the combined script.

    Returns:
        The server-assigned ``request_id``. Poll it like any other async
        request; the result's ``result`` field is a dict keyed ``"_r0"``,
        ``"_r1"``, ... in submission order.
    """
    from ._batch import build_operations_script

    pairs = [(op["body_lines"], op["result_expression"]) for op in operations]
    script = build_operations_script(pairs)
    return self.execute_async_submit(script, args=args)
```

- [ ] **Step 6: Implement `AsyncDazClient.execute_batch_async()`**

Add to `dazpy/_client_aio.py`, inside the `AsyncDazClient` class, after `execute_file_async_submit`:

```python
async def execute_batch_async(self, operations: list[dict], args: object = None) -> str:
    """Submit multiple operations as one async request. See :meth:`dazpy.DazClient.execute_batch_async`."""
    from ._batch import build_operations_script

    pairs = [(op["body_lines"], op["result_expression"]) for op in operations]
    script = build_operations_script(pairs)
    return await self.execute_async_submit(script, args=args)
```

- [ ] **Step 7: Run to verify it passes**

Run: `python -m pytest tests/test_dazpy.py -k TestExecuteBatchAsync -v && python -m pytest tests/test_dazpy_aio.py -k TestAsyncDazClientExecuteBatchAsync -v`
Expected: all PASS.

- [ ] **Step 8: Run full suites and commit**

```bash
python -m pytest tests/test_dazpy.py -q
python -m pytest tests/test_dazpy_aio.py -q
git add dazpy/_client.py dazpy/_client_aio.py dazpy/_batch.py tests/test_dazpy.py tests/test_dazpy_aio.py
git commit -m "feat: submit multi-operation async batches as one /execute/async request"
```

---

## Task 6 — Main-thread wait and batch-size metrics (C++)

No C++ test harness exists in this repo beyond `test_securerandom.cpp` (a standalone). Per the Global Constraints, this task is verified by: (a) a clean build under both SDK configurations, (b) the manual Studio smoke test at the end of this plan. There are no `- [ ] Write failing test` steps here — follow the edit steps below, then build.

**Files:**
- Modify: `include/MetricsCollector.h`
- Modify: `src/MetricsCollector.cpp` (find it — same directory as the header; not read yet in this session, so confirm its current `recordRequest`/`saveToSettings` bodies before editing so new fields follow the same style)
- Modify: `include/DzScriptServerPane.h` (the `handleExecuteRequest` declaration — add an `acceptedAtMs` parameter)
- Modify: `src/DzScriptServerPane.cpp:1527` (`handleExecuteRequest`) and the `getMetricsJson()` builder (`src/DzScriptServerPane.cpp:2878+`)
- Modify: `src/RequestHandlers.cpp:152-164` (`ExecuteScriptHandler::handle`, the `/execute` sync route — capture the pre-dispatch timestamp here)

**Interfaces:**
- Consumes: `QDateTime::currentMSecsSinceEpoch()` (thread-safe, callable from HTTP worker threads — unlike `QTime::currentTime()`, which `handleExecuteRequest` already uses locally after crossing to the main thread; do not use `QTime` from the HTTP thread).
- Produces:
  - `MetricsCollector::recordMainThreadWait(qint64 waitMs)` — new method, mutex-protected like `recordRequest`.
  - `MetricsCollector::getAvgMainThreadWaitMs() const` / `getMaxMainThreadWaitMs() const` — new accessors.
  - `/metrics` JSON gains `"avg_main_thread_wait_ms"` and `"max_main_thread_wait_ms"` fields, additive only — do not rename or remove any existing `/metrics` field (`total_requests`, `successful_requests`, `failed_requests`, `auth_failures`, `active_requests`, `uptime_seconds`, `success_rate` per `src/DzScriptServerPane.cpp:2878-2900+`).

- [ ] **Step 1: Read `src/MetricsCollector.cpp` before editing**

Run: read the file to see `recordRequest`'s exact mutex-lock pattern (`QMutexLocker` vs manual `lock()`/`unlock()`) and `saveToSettings`'s key-naming convention. Match both exactly for the new fields — do not introduce a second locking style in the same class.

- [ ] **Step 2: Add wait-time tracking fields and methods to `MetricsCollector`**

In `include/MetricsCollector.h`, add to the public section (after `recordAuthFailure`):

```cpp
    // Records how long a synchronous /execute request waited between the
    // HTTP thread issuing the BlockingQueuedConnection call and
    // handleExecuteRequest() starting to run on the main thread.
    void recordMainThreadWait(qint64 waitMs);

    qint64 getAvgMainThreadWaitMs() const;
    qint64 getMaxMainThreadWaitMs() const;
```

And to the private section:

```cpp
    qint64 m_nMainThreadWaitSamples;
    qint64 m_nMainThreadWaitSumMs;
    qint64 m_nMainThreadWaitMaxMs;
```

Initialize the three new fields to `0` in the constructor (in `src/MetricsCollector.cpp`, matching wherever `m_nTotal` etc. are currently zeroed), and implement:

```cpp
void MetricsCollector::recordMainThreadWait(qint64 waitMs)
{
    QMutexLocker locker(&m_mutex); // match whatever locking style recordRequest() uses
    m_nMainThreadWaitSamples++;
    m_nMainThreadWaitSumMs += waitMs;
    if (waitMs > m_nMainThreadWaitMaxMs) m_nMainThreadWaitMaxMs = waitMs;
}

qint64 MetricsCollector::getAvgMainThreadWaitMs() const
{
    QMutexLocker locker(&m_mutex);
    return m_nMainThreadWaitSamples > 0 ? m_nMainThreadWaitSumMs / m_nMainThreadWaitSamples : 0;
}

qint64 MetricsCollector::getMaxMainThreadWaitMs() const
{
    QMutexLocker locker(&m_mutex);
    return m_nMainThreadWaitMaxMs;
}
```

(Adjust the locker type/pattern to match `src/MetricsCollector.cpp`'s existing style from Step 1 if it differs from `QMutexLocker`.)

- [ ] **Step 3: Thread the accepted-at timestamp from the HTTP thread into `handleExecuteRequest`**

In `include/DzScriptServerPane.h`, find `handleExecuteRequest`'s declaration and add a parameter:

```cpp
Q_INVOKABLE HttpResult handleExecuteRequest(const QByteArray& jsonBody, const QByteArray& clientIP, qint64 acceptedAtMs);
```

(Match whatever `Q_INVOKABLE`/access-specifier convention the existing declaration already uses — this only adds one trailing `qint64` parameter.)

In `src/RequestHandlers.cpp:152-164` (`ExecuteScriptHandler::handle`), capture the timestamp on the HTTP thread just before dispatch:

```cpp
void ExecuteScriptHandler::handle(HttpContext& ctx)
{
    if (respondIfMainThreadBusy(m_pPane, ctx)) return;
    qint64 acceptedAtMs = QDateTime::currentMSecsSinceEpoch();
    QByteArray bodyBytes(ctx.body.c_str(), (int)ctx.body.size());
    QByteArray ipBytes(ctx.remoteAddr.c_str(), (int)ctx.remoteAddr.size());
    HttpResult result;
    QMetaObject::invokeMethod(m_pPane, "handleExecuteRequest",
        Qt::BlockingQueuedConnection,
        Q_RETURN_ARG(HttpResult, result),
        Q_ARG(QByteArray, bodyBytes),
        Q_ARG(QByteArray, ipBytes),
        Q_ARG(qint64, acceptedAtMs));
    ctx.respond(result.first, std::string(result.second.constData(), result.second.size()));
}
```

In `src/DzScriptServerPane.cpp:1527`, update the signature and record the wait at entry:

```cpp
HttpResult DzScriptServerPane::handleExecuteRequest(const QByteArray& jsonBody, const QByteArray& clientIP, qint64 acceptedAtMs)
{
	QTime startTime = QTime::currentTime();
	qint64 dispatchedAtMs = QDateTime::currentMSecsSinceEpoch();
	m_metrics.recordMainThreadWait(dispatchedAtMs - acceptedAtMs);
	QString clientIPStr = QString::fromUtf8(clientIP.constData(), clientIP.size());
	QString requestId = MetricsCollector::generateRequestId();
	// ... rest unchanged
```

- [ ] **Step 4: Expose the new fields in `/metrics`**

In `src/DzScriptServerPane.cpp`, in `getMetricsJson()` (starting `src/DzScriptServerPane.cpp:2878`), add after the existing `uptime` line and before closing the JSON object — follow the exact `std::string s +=` concatenation style already used in that function (do not introduce a JSON library dependency here; the function is explicitly hand-built `std::string` because it runs on httplib worker threads where Qt string ops are unsafe, per the comment at `src/DzScriptServerPane.cpp:2880`):

```cpp
	s += ",\"avg_main_thread_wait_ms\":";
	s += std::to_string((long long)m_metrics.getAvgMainThreadWaitMs());
	s += ",\"max_main_thread_wait_ms\":";
	s += std::to_string((long long)m_metrics.getMaxMainThreadWaitMs());
```

Insert this immediately before the closing `s += "}";` of `getMetricsJson()` — read the full function body first to find its actual closing brace, since only its opening ~15 lines were inspected while writing this plan.

- [ ] **Step 5: Check every other caller of `handleExecuteRequest`**

Run: `grep -rn "handleExecuteRequest" src/ include/` — the async path and any other code that might invoke it directly (not just `ExecuteScriptHandler`) must also pass an `acceptedAtMs` argument now that the signature changed, or the build will fail. If another caller exists, apply the same "capture `QDateTime::currentMSecsSinceEpoch()` right before dispatch" pattern there.

- [ ] **Step 6: Build both SDK configurations**

Run: `./build.sh build --clean` (SDK4)
Expected: builds cleanly, no signature-mismatch errors.

Run: `./build.sh build --sdk-version 6 --clean` (SDK6)
Expected: builds cleanly.

- [ ] **Step 7: Commit**

```bash
git add include/MetricsCollector.h src/MetricsCollector.cpp include/DzScriptServerPane.h src/DzScriptServerPane.cpp src/RequestHandlers.cpp
git commit -m "feat: expose main-thread wait time in /metrics"
```

---

## Task 7 — Documentation

**Files:**
- Modify: `docs/api/batch.rst`
- Modify: `docs/quickstart.rst`

**Interfaces:** none (docs only).

- [ ] **Step 1: Read the current `docs/api/batch.rst`**

Run: read the file to match its existing `autoclass`/prose style before adding to it.

- [ ] **Step 2: Document `add_operation()`, `add_prelude()`, limits, and `execute_batch_async()`**

Add to `docs/api/batch.rst` (structure to match whatever the file's existing sections look like — at minimum, cover):

- The distinction between one HTTP request and one DazScript evaluation (a `Batch` of 20 operations is still 1 evaluation; two separate `Batch.execute()` calls are 2 evaluations).
- That batching reduces main-thread handoff/parse/HTTP overhead per operation, but Studio still executes every operation's JS serially inside one script — it does not parallelize scene mutations.
- `add_operation()` vs `add()`: prefer `add_operation()` for anything generated programmatically; it doesn't require guessing the internal `_rN` key.
- `add_prelude()`: emitted once per unique key, useful when several operations share a lookup (e.g. the same node).
- Whole-batch failure: if any operation throws, the entire batch's `/execute` call fails and no partial results are available — there is no rollback of scene mutations already applied by earlier operations in the same script.
- `max_operations` / `max_script_length` and `BatchLimitExceededError`, raised client-side before any HTTP call.
- `execute_batch_async()` on `DazClient`/`AsyncDazClient`: same one-script guarantee as `Batch`, but submitted to `/execute/async` and tracked as one queue item — poll with `get_request_status()`/`get_request_result()` as usual; results are keyed `"_r0"`, `"_r1"`, ... by submission order.

- [ ] **Step 3: Add a before/after example to `docs/quickstart.rst`**

Add one example showing a bone/property update via the old per-field loop vs. the new bulk API, e.g.:

```python
# Before: one HTTP round-trip per bone
for name, rot in bone_rotations.items():
    skeleton.set_bone_rotations({name: rot})  # (illustrative — the old call already accepted a dict)

# After: one HTTP round-trip for bones + morphs + properties together
skeleton.set_state(bones=bone_rotations, morphs=morph_values, props={"Scale": 100.0})
```

- [ ] **Step 4: Document when to prefer async request IDs**

Add a short paragraph to `docs/quickstart.rst` or `docs/api/batch.rst`: prefer `execute_batch_async()`/`Batch` submitted via async over synchronous `Batch.execute()` when the combined script's expected duration is long enough that holding an HTTP worker thread and a blocking client call is wasteful — poll instead of blocking. Reference the existing async endpoints table in `CLAUDE.md` (`/execute/async`, `/requests/:id/status`, `/requests/:id/result?wait=true`).

- [ ] **Step 5: Commit**

```bash
git add docs/api/batch.rst docs/quickstart.rst
git commit -m "docs: document dazpy batching, limits, and async batch submission"
```

---

## Validation sequence

Run after each task above, and again at the end:

```bash
python -m pytest tests/test_dazpy.py -q
python -m pytest tests/test_dazpy_aio.py -q
python -m pytest tests/test_dazpy_integration.py -q
```

The integration suite should gracefully skip when Studio is unavailable. Per `[[feedback_dont_run_full_integration_suite_live]]`-style caution already in this repo's session memory, do not run the full `test_dazpy_integration.py` against a live Studio instance without scoping with `-k` — a prior full run froze/white-screened DAZ Studio.

If any C++ code changed (Task 6), build both SDK configurations:

```bash
./build.sh build --clean
./build.sh build --sdk-version 6 --clean
```

### Manual Studio smoke test (Task 6, after both builds succeed)

1. Install the built plugin (`./build.sh install --clean`, Studio must not be running) and start DAZ Studio with the Script Server pane open, metrics enabled.
2. Load a scene with a rigged figure. Run 20 individual `set_bone_rotations()`/`set_property()` calls via a throwaway script and record `GET /metrics`'s `avg_main_thread_wait_ms` / `max_main_thread_wait_ms` before and after.
3. Run the equivalent 20 mutations as one `Batch` (`add_operation` + `add_prelude`) and compare total wall time and `/metrics` deltas.
4. Submit the same batch via `execute_batch_async()`; poll `GET /requests/:id/status` until `completed`, then `GET /requests/:id/result` and confirm the keyed `_r0..._r19` result shape.
5. While a scene load or render is active, issue a sync `/execute` call and confirm the existing `503 STUDIO_BUSY` fast-fail still returns immediately (no change from this plan) and does not enqueue duplicate work.
6. Deliberately include one throwing operation inside a `Batch` and confirm the whole batch reports failure (an exception from `client.execute()`), with no partial-result contract implied.

---

## Acceptance criteria

- [ ] `snapshot()`, `reset_transforms()`, and default-mode `zero_figure()` each issue exactly one `client.execute()` call regardless of field/component count (Tasks 2A–2C).
- [ ] `DazNode.set_transform()`, `DazElement.set_properties()`, `DazSkeleton.set_state()` exist, are one-call, and have optional/omittable arguments (Tasks 2B/3B/3C).
- [ ] `Batch.add()` and all pre-existing `TestBatch` tests remain green; `Batch.add_operation()`/`add_prelude()` are additive (Task 4).
- [ ] `Batch` enforces `max_operations` and `max_script_length`, raising `BatchLimitExceededError` client-side before any HTTP call (Task 4).
- [ ] `DazClient.execute_batch_async()` / `AsyncDazClient.execute_batch_async()` submit exactly one `/execute/async` request regardless of operation count, with no new C++ route (Task 5).
- [ ] `/metrics` gains `avg_main_thread_wait_ms`/`max_main_thread_wait_ms` without renaming/removing any existing field; both SDK builds succeed (Task 6).
- [ ] `docs/api/batch.rst` and `docs/quickstart.rst` document one-evaluation-per-batch, whole-batch failure/no-rollback, size limits, and async batch submission (Task 7).
- [ ] No implicit batching was added to ordinary `get_property()`/`set_property()`/single-field setters.

## Suggested implementation commits

1. `test: characterize dazpy script call counts before batching`
2. `perf: make DazElement.snapshot() a single DazScript evaluation`
3. `feat: add DazNode.set_transform() and rebuild reset_transforms() on it`
4. `perf: zero_figure() default path uses one DazScript evaluation`
5. `feat: add DazElement.set_properties() for one-call bulk property writes`
6. `feat: add DazSkeleton.set_state() for combined bone/morph/property writes`
7. `feat: extend Batch with add_operation(), add_prelude(), and size limits`
8. `feat: submit multi-operation async batches as one /execute/async request`
9. `feat: expose main-thread wait time in /metrics`
10. `docs: document dazpy batching, limits, and async batch submission`

Each commit is independently testable — revert one without obscuring failures in another.
