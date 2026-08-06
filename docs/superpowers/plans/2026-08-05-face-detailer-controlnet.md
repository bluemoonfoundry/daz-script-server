# Per-Region ControlNet Conditioning for the Face-Identity Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the sprite matrix pipeline's face-identity pass its own per-region ControlNet conditioning (normal/depth/lineart, matched to the SAM-refined face crop) so its output actually matches the ink-hatched style of the main body pass, instead of rendering flat/shiny skin with no linework.

**Architecture:** Insert a chain of Impact Pack's `ImpactControlNetApplyAdvancedSEGS` nodes between `MaskToSEGS` (node `"69"`) and `SEGSDetailer` (node `"65"`) in `workflow_controlnet.json`, reusing the main pass's already-retagged ControlNet outputs and source images. `SEGSDetailer` consumes the resulting per-segment ControlNet info automatically; no other node in the chain changes.

**Tech Stack:** ComfyUI API-format JSON workflow (`workflow_controlnet.json`), Python workflow builder (`workflow_builder.py`), Python dataclass config (`config.py`/`schema.py`), no new external dependencies (Impact Pack is already installed).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-05-face-detailer-controlnet-design.md`
- The registered ComfyUI node name is `ImpactControlNetApplyAdvancedSEGS` (not `ControlNetApplyAdvancedSEGS` -- that's the Python class name only; confirmed live against a running ComfyUI's `/object_info` endpoint, and the wrong name fails prompt validation with `missing_node_type`).
- New node IDs `"73"`, `"74"`, `"75"` are reserved for the normal/depth/lineart `ImpactControlNetApplyAdvancedSEGS` chain, in that order.
- `start_percent`/`end_percent` on the new nodes stay fixed at `0.0`/`1.0` as JSON literals -- not config knobs (no evidence yet they need tuning, per the spec).
- New tunable knobs: `face_detailer_controlnet_normal_weight`, `face_detailer_controlnet_depth_weight`, `face_detailer_controlnet_lineart_weight` (float), following the exact naming/plumbing pattern `face_detailer_faceid_weight` already established: dataclass field on `ComfyUIStageConfig`, JSON key under `comfyui.face_detailer` in the spec (`controlnet_normal_weight`/`controlnet_depth_weight`/`controlnet_lineart_weight`, no `face_detailer_` prefix since they're already nested under `face_detailer`), CLI flag on `render_shot.py` (`--face-detailer-controlnet-normal-weight` etc.), keyword argument into `build_controlnet_workflow`.
- Provisional defaults (pending Task 5's live tuning): `1.0` (normal), `0.8` (depth), `0.6` (lineart) -- the spike's best-performing values, one notch above the main pass's own `0.6`/`0.5`/`0.4`.
- Disabled-branch node-deletion tuple in `workflow_builder.py` (the `else` branch when `face_detailer_enabled=False`) must include the three new node IDs.
- `sys.modules.pop` test-eviction pattern (already present in `tests/test_sprite_matrix_workflow_builder.py`) must be preserved -- don't remove it.
- No test should assert nothing (a test with no assertions, or a trivially-always-true assertion, is a defect per this project's review rubric).

---

### Task 1: Rewire `workflow_controlnet.json`

**Files:**
- Modify: `docs/examples/rendering/sprite_matrix/workflow_controlnet.json`

**Interfaces:**
- Produces: new nodes `"73"`, `"74"`, `"75"` (class_type `ImpactControlNetApplyAdvancedSEGS`) in the template, and node `"65"`'s `segs` input rewired to read from the new chain instead of directly from `"69"`. Task 2 depends on these exact node IDs and the class_type name.

- [ ] **Step 1: Insert the three new nodes**

Add these three entries to the JSON object (place them after node `"69"` and before node `"70"` for readability -- object key order doesn't affect ComfyUI, but keeps the file's existing top-to-bottom node-flow ordering convention):

```json
  "73": {
    "class_type": "ImpactControlNetApplyAdvancedSEGS",
    "inputs": {
      "segs": ["69", 0],
      "control_net": ["21", 0],
      "strength": "__FACE_DETAILER_CONTROLNET_NORMAL_WEIGHT__",
      "start_percent": 0.0,
      "end_percent": 1.0,
      "control_image": ["20", 0]
    }
  },
  "74": {
    "class_type": "ImpactControlNetApplyAdvancedSEGS",
    "inputs": {
      "segs": ["73", 0],
      "control_net": ["31", 0],
      "strength": "__FACE_DETAILER_CONTROLNET_DEPTH_WEIGHT__",
      "start_percent": 0.0,
      "end_percent": 1.0,
      "control_image": ["30", 0]
    }
  },
  "75": {
    "class_type": "ImpactControlNetApplyAdvancedSEGS",
    "inputs": {
      "segs": ["74", 0],
      "control_net": ["41", 0],
      "strength": "__FACE_DETAILER_CONTROLNET_LINEART_WEIGHT__",
      "start_percent": 0.0,
      "end_percent": 1.0,
      "control_image": ["40", 0]
    }
  },
```

`control_net` reuses the main pass's already-retagged `SetUnionControlNetType` outputs (`"21"` = normal-tagged, `"31"` = depth-tagged, `"41"` = lineart-tagged) -- do not add new `ControlNetLoader`/`SetUnionControlNetType` nodes, that would load the model a second time for no benefit. `control_image` reuses the same `LoadImage` nodes (`"20"`/`"30"`/`"40"`) the main pass already uses.

- [ ] **Step 2: Rewire `"65"` (SEGSDetailer) to read segs from the new chain**

Change node `"65"`'s `segs` input from:
```json
      "segs": ["69", 0],
```
to:
```json
      "segs": ["75", 0],
```

- [ ] **Step 3: Validate the JSON is well-formed**

Run:
```bash
cd Y:/working/BlueMoonFoundry/daz-script-server
python -c "import json; json.load(open('docs/examples/rendering/sprite_matrix/workflow_controlnet.json')); print('valid JSON')"
```
Expected: `valid JSON` with no traceback.

- [ ] **Step 4: Commit**

```bash
git add docs/examples/rendering/sprite_matrix/workflow_controlnet.json
git commit -m "Add per-region ControlNet chain for the face-identity pass"
```

---

### Task 2: Update `workflow_builder.py`

**Files:**
- Modify: `docs/examples/rendering/sprite_matrix/workflow_builder.py`

**Interfaces:**
- Consumes: nodes `"73"`/`"74"`/`"75"` from Task 1's template, with placeholder sentinels `__FACE_DETAILER_CONTROLNET_NORMAL_WEIGHT__`/`__FACE_DETAILER_CONTROLNET_DEPTH_WEIGHT__`/`__FACE_DETAILER_CONTROLNET_LINEART_WEIGHT__`.
- Produces: `build_controlnet_workflow(...)` gains three new keyword parameters `face_detailer_controlnet_normal_weight: float = 1.0`, `face_detailer_controlnet_depth_weight: float = 0.8`, `face_detailer_controlnet_lineart_weight: float = 0.6`. Task 3 (config plumbing) and Task 4 (tests) depend on these exact parameter names and defaults.

- [ ] **Step 1: Add the three new parameters to the function signature**

In `build_controlnet_workflow(...)`'s parameter list, add after `face_detailer_faceid_weight: float = 1.0,`:

```python
    face_detailer_controlnet_normal_weight: float = 1.0,
    face_detailer_controlnet_depth_weight: float = 0.8,
    face_detailer_controlnet_lineart_weight: float = 0.6,
```

- [ ] **Step 2: Wire the three new strength values inside the `if face_detailer_enabled:` branch**

Add these three lines immediately after the existing `workflow["72"]["inputs"]["weight"] = float(face_detailer_faceid_weight)` line:

```python
        workflow["73"]["inputs"]["strength"] = float(face_detailer_controlnet_normal_weight)
        workflow["74"]["inputs"]["strength"] = float(face_detailer_controlnet_depth_weight)
        workflow["75"]["inputs"]["strength"] = float(face_detailer_controlnet_lineart_weight)
```

- [ ] **Step 3: Add the new node IDs to the disabled-branch deletion tuple**

Change:
```python
        for node_id in ("60", "62", "64", "65", "66", "67", "68", "69", "70", "71", "72"):
            del workflow[node_id]
```
to:
```python
        for node_id in ("60", "62", "64", "65", "66", "67", "68", "69", "70", "71", "72", "73", "74", "75"):
            del workflow[node_id]
```

- [ ] **Step 4: Extend the explanatory comment block**

The existing comment block above the `if face_detailer_enabled:` body (starting `# Second pass: detect the face...`) currently ends with the "blacker than black halo" paragraph. Add one more paragraph after it, before the code resumes:

```python
        #
        # SEGSDetailer's basic_pipe carries the raw, un-conditioned prompt
        # (node "4"/"5" straight into ToBasicPipe) -- the main pass's own
        # ControlNetApply chain (22->32->42) is never in that path, since it
        # conditions the whole-image KSampler's positive conditioning object,
        # not anything SEGSDetailer's per-segment re-sampling can see. That
        # left this pass with ZERO ControlNet guidance even after FaceID
        # conditioning fixed identity: nothing forced it to draw the ink
        # cross-hatching the body gets, so it rendered visibly flatter/
        # shinier skin regardless of denoise or faceid_weight (confirmed
        # live: a seam was visible at the neck/collar boundary in real
        # abby_b/jason_a renders). Fixed by attaching per-segment ControlNet
        # info directly onto the SEGS list via Impact Pack's
        # ImpactControlNetApplyAdvancedSEGS (nodes "73"/"74"/"75"), which
        # internally crops/resizes the same normal/depth/lineart maps the
        # main pass uses to match each segment's crop_region -- exactly the
        # coordinate-space correspondence a full ControlNetApply can't
        # provide (the crop is a different resolution/coordinate space than
        # the body-scale condition images). SEGSDetailer picks up this
        # per-segment info automatically; no change needed there.
```

- [ ] **Step 5: Verify with a quick manual check**

Run:
```bash
cd Y:/working/BlueMoonFoundry/daz-script-server/docs/examples/rendering/sprite_matrix
python -c "
from workflow_builder import build_controlnet_workflow
wf = build_controlnet_workflow(
    beauty_image_ref='b.png', normal_image_ref='n.png', depth_image_ref='d.png', lineart_image_ref='l.png',
    checkpoint_name='gn.safetensors', lora_name='', lora_strength=0.8, denoise=0.35, steps=24, cfg=7.0, seed=1,
    positive_prompt='p', negative_prompt='n', controlnet_model='cnet.safetensors',
    controlnet_normal_weight=0.6, controlnet_depth_weight=0.5, controlnet_lineart_weight=0.4,
)
assert wf['73']['inputs']['strength'] == 1.0, wf['73']['inputs']['strength']
assert wf['74']['inputs']['strength'] == 0.8, wf['74']['inputs']['strength']
assert wf['75']['inputs']['strength'] == 0.6, wf['75']['inputs']['strength']
assert wf['65']['inputs']['segs'] == ['75', 0], wf['65']['inputs']['segs']
print('OK')
"
```
Expected: `OK` with no traceback.

- [ ] **Step 6: Commit**

```bash
cd Y:/working/BlueMoonFoundry/daz-script-server
git add docs/examples/rendering/sprite_matrix/workflow_builder.py
git commit -m "Wire per-region ControlNet strengths into workflow_builder.py"
```

---

### Task 3: Plumb the three new config knobs through config/schema/stage/CLI

**Files:**
- Modify: `docs/examples/rendering/sprite_matrix/config.py`
- Modify: `docs/examples/rendering/sprite_matrix/schema.py`
- Modify: `docs/examples/rendering/sprite_matrix/stylize_stage.py`
- Modify: `docs/examples/rendering/sprite_matrix/render_shot.py`
- Modify: `docs/examples/rendering/sprite_matrix/example_spec.json`

**Interfaces:**
- Consumes: `build_controlnet_workflow`'s three new parameters from Task 2 (`face_detailer_controlnet_normal_weight`, `face_detailer_controlnet_depth_weight`, `face_detailer_controlnet_lineart_weight`).
- Produces: `ComfyUIStageConfig.face_detailer_controlnet_normal_weight`/`_depth_weight`/`_lineart_weight` (all `float`), parsed from `comfyui.face_detailer.controlnet_normal_weight`/`controlnet_depth_weight`/`controlnet_lineart_weight` in the spec JSON, and CLI flags `--face-detailer-controlnet-normal-weight`/`--face-detailer-controlnet-depth-weight`/`--face-detailer-controlnet-lineart-weight` on `render_shot.py`.

- [ ] **Step 1: Add the three new fields to `config.py`**

In `ComfyUIStageConfig`, add after the existing `face_detailer_faceid_weight: float = 1.0` field:

```python
    # Per-region ControlNet conditioning strength for the face-identity
    # pass's SEGSDetailer sampling (normal/depth/lineart, matched to the
    # SAM-refined crop via Impact Pack's ImpactControlNetApplyAdvancedSEGS).
    # Without this, the face pass has zero ControlNet guidance and renders
    # visibly flatter/shinier skin than the ink-hatched body regardless of
    # denoise/faceid_weight -- see
    # docs/superpowers/plans/2026-08-05-face-detailer-controlnet.md. Live-
    # tuned in Task 5 of that plan; provisional defaults below (1.0/0.8/0.6)
    # are one notch above the main pass's own 0.6/0.5/0.4, per the spike
    # that motivated this plan.
    face_detailer_controlnet_normal_weight: float = 1.0
    face_detailer_controlnet_depth_weight: float = 0.8
    face_detailer_controlnet_lineart_weight: float = 0.6
```

- [ ] **Step 2: Parse the three new fields in `schema.py`**

After the existing line `face_detailer_faceid_weight = face_detailer_raw.get("faceid_weight", 1.0)`, add:

```python
    face_detailer_controlnet_normal_weight = face_detailer_raw.get("controlnet_normal_weight", 1.0)
    face_detailer_controlnet_depth_weight = face_detailer_raw.get("controlnet_depth_weight", 0.8)
    face_detailer_controlnet_lineart_weight = face_detailer_raw.get("controlnet_lineart_weight", 0.6)
```

In the `ComfyUIStageConfig(...)` constructor call, after the existing `face_detailer_faceid_weight=float(face_detailer_faceid_weight),` line, add:

```python
        face_detailer_controlnet_normal_weight=float(face_detailer_controlnet_normal_weight),
        face_detailer_controlnet_depth_weight=float(face_detailer_controlnet_depth_weight),
        face_detailer_controlnet_lineart_weight=float(face_detailer_controlnet_lineart_weight),
```

- [ ] **Step 3: Pass the three new fields through in `stylize_stage.py`**

Inside `run_stylize_stage`'s nested `_run(...)` function, in the `build_controlnet_workflow(...)` call, after the existing `face_detailer_faceid_weight=cfg.comfyui.face_detailer_faceid_weight,` line, add:

```python
                    face_detailer_controlnet_normal_weight=cfg.comfyui.face_detailer_controlnet_normal_weight,
                    face_detailer_controlnet_depth_weight=cfg.comfyui.face_detailer_controlnet_depth_weight,
                    face_detailer_controlnet_lineart_weight=cfg.comfyui.face_detailer_controlnet_lineart_weight,
```

- [ ] **Step 4: Add CLI flags and pass them through in `render_shot.py`**

After the existing `p.add_argument("--face-detailer-faceid-weight", ...)` block (the one ending with its `help=` string), add:

```python
    p.add_argument(
        "--face-detailer-controlnet-normal-weight",
        type=float,
        default=comfy_defaults.face_detailer_controlnet_normal_weight,
        help="Per-region ControlNet strength (normal map) for the face-identity pass",
    )
    p.add_argument(
        "--face-detailer-controlnet-depth-weight",
        type=float,
        default=comfy_defaults.face_detailer_controlnet_depth_weight,
        help="Per-region ControlNet strength (depth map) for the face-identity pass",
    )
    p.add_argument(
        "--face-detailer-controlnet-lineart-weight",
        type=float,
        default=comfy_defaults.face_detailer_controlnet_lineart_weight,
        help="Per-region ControlNet strength (lineart map) for the face-identity pass",
    )
```

Inside `stylize_shot`'s nested `_run(...)` function, in the `build_controlnet_workflow(...)` call, after the existing `face_detailer_faceid_weight=args.face_detailer_faceid_weight,` line, add:

```python
                    face_detailer_controlnet_normal_weight=args.face_detailer_controlnet_normal_weight,
                    face_detailer_controlnet_depth_weight=args.face_detailer_controlnet_depth_weight,
                    face_detailer_controlnet_lineart_weight=args.face_detailer_controlnet_lineart_weight,
```

- [ ] **Step 5: Update `example_spec.json`**

Change the `face_detailer` block from:
```json
    "face_detailer": {
      "enabled": true,
      "denoise": 0.35,
      "guide_size": 512,
      "bbox_dilation": 100,
      "faceid_weight": 1.0
    },
```
to:
```json
    "face_detailer": {
      "enabled": true,
      "denoise": 0.35,
      "guide_size": 512,
      "bbox_dilation": 100,
      "faceid_weight": 1.0,
      "controlnet_normal_weight": 1.0,
      "controlnet_depth_weight": 0.8,
      "controlnet_lineart_weight": 0.6
    },
```

- [ ] **Step 6: Verify**

```bash
cd Y:/working/BlueMoonFoundry/daz-script-server/docs/examples/rendering/sprite_matrix
python -m py_compile config.py schema.py stylize_stage.py render_shot.py workflow_builder.py
python main.py --spec example_spec.json --dry-run
```
Expected: `py_compile` produces no output (success); the dry-run prints the full expanded work plan with no traceback.

- [ ] **Step 7: Commit**

```bash
cd Y:/working/BlueMoonFoundry/daz-script-server
git add docs/examples/rendering/sprite_matrix/config.py docs/examples/rendering/sprite_matrix/schema.py docs/examples/rendering/sprite_matrix/stylize_stage.py docs/examples/rendering/sprite_matrix/render_shot.py docs/examples/rendering/sprite_matrix/example_spec.json
git commit -m "Add face-identity ControlNet weight config knobs"
```

---

### Task 4: Update unit tests

**Files:**
- Modify: `tests/test_sprite_matrix_workflow_builder.py`
- Modify: `tests/test_sprite_matrix_schema.py`

**Interfaces:**
- Consumes: `build_controlnet_workflow`'s new parameters (Task 2) and `ComfyUIStageConfig`'s new fields (Task 3).

- [ ] **Step 1: Fix the now-stale `test_segs_detailer_reads_segs_directly_from_masktosegs`**

This existing test in `TestBuildControlnetWorkflowFaceDetailer` currently
asserts `wf["65"]["inputs"]["segs"] == ["69", 0]` -- Task 1/2's rewiring
breaks this (node `"65"`'s `segs` now comes from `"75"`, the end of the new
ControlNet chain, not directly from `"69"`). Rename the test to reflect
what it's actually now guaranteeing and fix the assertion:

```python
    def test_segs_detailer_does_not_use_old_setdefaultimage_swap(self):
        # No more SetDefaultImageForSEGS pixel-source swap -- identity comes
        # from FaceID embedding conditioning on the model, not from sourcing
        # crop pixels from the real beauty render. (segs now flows through
        # the ControlNet-on-SEGS chain before reaching SEGSDetailer -- see
        # TestBuildControlnetWorkflowFaceDetailerControlNet for that wiring.)
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertNotIn("63", wf)
```

(The `wf["65"]["inputs"]["segs"] == ["75", 0]` assertion this test used to
make is superseded by
`TestBuildControlnetWorkflowFaceDetailerControlNet.test_segs_detailer_reads_segs_from_controlnet_chain`,
added in Step 3 below -- no coverage is lost, just relocated to the test
class that now owns that wiring.)

- [ ] **Step 2: Add nodes `"73"`/`"74"`/`"75"` to `test_required_node_keys`**

In `test_sprite_matrix_workflow_builder.py`'s `TestBuildControlnetWorkflow.test_required_node_keys`, change:
```python
            "60", "62", "64", "65", "66", "67", "68", "69", "70", "71", "72",
```
to:
```python
            "60", "62", "64", "65", "66", "67", "68", "69", "70", "71", "72", "73", "74", "75",
```

- [ ] **Step 3: Add `ImpactControlNetApplyAdvancedSEGS` to `test_required_class_types`**

In the same file's `test_required_class_types`, add `"ImpactControlNetApplyAdvancedSEGS",` to the tuple of expected class types (anywhere in the tuple; alongside `"SEGSDetailer"`/`"SEGSPaste"` keeps the face-pass-related entries grouped).

- [ ] **Step 4: Add a new test class for the ControlNet-on-SEGS wiring**

Add this new test class after `TestBuildControlnetWorkflowFaceDetailer` (i.e. after its last existing test method, before `TestStableSeed`):

```python
class TestBuildControlnetWorkflowFaceDetailerControlNet(unittest.TestCase):
    def test_segs_detailer_reads_segs_from_controlnet_chain(self):
        # "65"'s segs now comes from the end of the ControlNet-on-SEGS
        # chain (node "75"), not directly from MaskToSEGS (node "69") --
        # the chain inserts per-segment ControlNet conditioning in between.
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertEqual(wf["65"]["inputs"]["segs"], ["75", 0])

    def test_controlnet_chain_wired_in_order(self):
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertEqual(wf["73"]["inputs"]["segs"], ["69", 0])
        self.assertEqual(wf["74"]["inputs"]["segs"], ["73", 0])
        self.assertEqual(wf["75"]["inputs"]["segs"], ["74", 0])

    def test_controlnet_chain_reuses_main_pass_retagged_controlnets(self):
        # Reuses the SAME SetUnionControlNetType outputs (21/31/41) the main
        # pass uses -- no separate ControlNetLoader/SetUnionControlNetType
        # for the face pass, which would load the model a second time.
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertEqual(wf["73"]["inputs"]["control_net"], ["21", 0])
        self.assertEqual(wf["74"]["inputs"]["control_net"], ["31", 0])
        self.assertEqual(wf["75"]["inputs"]["control_net"], ["41", 0])

    def test_controlnet_chain_reuses_main_pass_source_images(self):
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertEqual(wf["73"]["inputs"]["control_image"], ["20", 0])
        self.assertEqual(wf["74"]["inputs"]["control_image"], ["30", 0])
        self.assertEqual(wf["75"]["inputs"]["control_image"], ["40", 0])

    def test_controlnet_weights_configurable(self):
        wf = build_controlnet_workflow(**{
            **_DEFAULT_KWARGS,
            "face_detailer_controlnet_normal_weight": 0.9,
            "face_detailer_controlnet_depth_weight": 0.7,
            "face_detailer_controlnet_lineart_weight": 0.5,
        })
        self.assertAlmostEqual(wf["73"]["inputs"]["strength"], 0.9)
        self.assertAlmostEqual(wf["74"]["inputs"]["strength"], 0.7)
        self.assertAlmostEqual(wf["75"]["inputs"]["strength"], 0.5)

    def test_controlnet_weights_default(self):
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertAlmostEqual(wf["73"]["inputs"]["strength"], 1.0)
        self.assertAlmostEqual(wf["74"]["inputs"]["strength"], 0.8)
        self.assertAlmostEqual(wf["75"]["inputs"]["strength"], 0.6)

    def test_controlnet_chain_fixed_percent_literals(self):
        # start_percent/end_percent are fixed (not config knobs) per the
        # design spec.
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        for node_id in ("73", "74", "75"):
            self.assertAlmostEqual(wf[node_id]["inputs"]["start_percent"], 0.0)
            self.assertAlmostEqual(wf[node_id]["inputs"]["end_percent"], 1.0)
```

- [ ] **Step 5: Update `test_disabled_removes_nodes_and_reverts_save_image`**

In `TestBuildControlnetWorkflowFaceDetailer` (or wherever this test currently lives -- it's the one asserting the disabled branch strips all face-pass nodes), change:
```python
        for node_id in ("60", "62", "64", "65", "66", "67", "68", "69", "70", "71", "72"):
            self.assertNotIn(node_id, wf)
```
to:
```python
        for node_id in ("60", "62", "64", "65", "66", "67", "68", "69", "70", "71", "72", "73", "74", "75"):
            self.assertNotIn(node_id, wf)
```
and add `"ImpactControlNetApplyAdvancedSEGS"` to the tuple of class types asserted absent (alongside `"IPAdapterFaceID"` etc.).

- [ ] **Step 6: Add config-knob assertions to `test_sprite_matrix_schema.py`**

In `test_face_detailer_defaults`, after the existing `self.assertAlmostEqual(cfg.comfyui.face_detailer_faceid_weight, 1.0)` line, add:
```python
        self.assertAlmostEqual(cfg.comfyui.face_detailer_controlnet_normal_weight, 1.0)
        self.assertAlmostEqual(cfg.comfyui.face_detailer_controlnet_depth_weight, 0.8)
        self.assertAlmostEqual(cfg.comfyui.face_detailer_controlnet_lineart_weight, 0.6)
```

In `test_face_detailer_overrides_parsed`, change the `data["comfyui"]["face_detailer"] = {...}` dict to add the three new keys:
```python
        data["comfyui"]["face_detailer"] = {
            "enabled": False, "denoise": 0.10, "guide_size": 768, "bbox_dilation": 150,
            "faceid_weight": 0.5, "controlnet_normal_weight": 0.3, "controlnet_depth_weight": 0.2,
            "controlnet_lineart_weight": 0.1,
        }
```
and after the existing `self.assertAlmostEqual(cfg.comfyui.face_detailer_faceid_weight, 0.5)` line, add:
```python
        self.assertAlmostEqual(cfg.comfyui.face_detailer_controlnet_normal_weight, 0.3)
        self.assertAlmostEqual(cfg.comfyui.face_detailer_controlnet_depth_weight, 0.2)
        self.assertAlmostEqual(cfg.comfyui.face_detailer_controlnet_lineart_weight, 0.1)
```

- [ ] **Step 7: Run the full test suite**

```bash
cd Y:/working/BlueMoonFoundry/daz-script-server
python -m pytest tests/test_sprite_matrix_*.py -q
```
Expected: all tests pass (previous baseline was 104 passed, 1 skipped; this task adds 7 new tests to `test_sprite_matrix_workflow_builder.py` -- Step 1's rename doesn't change the count -- and extends 2 existing tests in `test_sprite_matrix_schema.py` with more assertions -- expect 111 passed, 1 skipped).

- [ ] **Step 8: Commit**

```bash
git add tests/test_sprite_matrix_workflow_builder.py tests/test_sprite_matrix_schema.py
git commit -m "Add tests for face-identity ControlNet chain and config knobs"
```

---

### Task 5: Live verification, default tuning, docs, and final push

**Files:**
- Modify: `docs/examples/rendering/sprite_matrix/config.py` (finalize the three `face_detailer_controlnet_*_weight` defaults based on findings)
- Modify: `docs/examples/rendering/sprite_matrix/schema.py` (finalize matching fallback defaults)
- Modify: `docs/examples/rendering/sprite_matrix/README.md` (document the new ControlNet conditioning and its knobs)

**Interfaces:** N/A (verification + tuning task, no new interfaces)

- [ ] **Step 1: Run a real stylize against both existing test characters with a strength grid**

Reuse the render files already on disk at
`x:/Development/Abaddon/Study/gnn_studies/output/abby_b/renders/shot001/` and
`x:/Development/Abaddon/Study/gnn_studies/output/jason_a/renders/shot001/`
(beauty PNG + converted canvas PNGs + lineart already exist). Build and queue
several `face_detailer_controlnet_normal/depth/lineart_weight` combinations
directly via `build_controlnet_workflow` (the same ad-hoc-script pattern
used for the spike in this plan's own design work, and the earlier
denoise/faceid_weight grid in
`docs/superpowers/plans/2026-08-05-faceid-conditioning.md`'s Task 7), e.g.
try the provisional default (1.0/0.8/0.6) plus at least one stronger
combination (e.g. 1.4/1.1/0.9) and one weaker combination (e.g. 0.6/0.5/0.4,
matching the main pass exactly, to confirm the spike's finding that this is
worse than a stronger set). For each combination, crop to the face+neck
region (wide enough to see the collar boundary, not just the face) and
build a side-by-side comparison image (`cv2.hstack` + label, same pattern
used earlier this session), including the current pre-fix output as a
reference point.

Expected: at least one combination shows visibly increased ink-hatching
texture on the face and a neck/collar transition that no longer reads as a
visible seam, without reintroducing any previously-fixed artifact (hair-color
seam at the boundary, background box artifact, blacker-than-black halo --
re-examine the same regions those fixes targeted, since the face crop's
render path changed).

- [ ] **Step 2: Cross-check across both characters**

Confirm the chosen combination isn't overfit to one character -- compare the
same combination's result on both `abby_b` and `jason_a`.

- [ ] **Step 3: Pick final defaults and update the config**

Based on Steps 1-2, set `face_detailer_controlnet_normal_weight`,
`face_detailer_controlnet_depth_weight`, `face_detailer_controlnet_lineart_weight`
defaults in `config.py` (replacing the provisional `1.0`/`0.8`/`0.6` values
from Task 3 if a different combination wins) and the matching fallback
defaults in `schema.py`'s `load_spec`. Update the explanatory comment above
the three fields in `config.py` to describe what was actually observed
(mirroring the existing comment style for `face_detailer_denoise`/
`face_detailer_faceid_weight` -- state the finding, not just the numbers).

- [ ] **Step 4: Re-run the full sprite_matrix test suite**

```bash
cd Y:/working/BlueMoonFoundry/daz-script-server
python -m pytest tests/test_sprite_matrix_*.py -q
```
Expected: all tests pass. If Step 3 changed any default that a test asserts
against verbatim (`test_face_detailer_defaults` in
`test_sprite_matrix_schema.py`, `test_controlnet_weights_default` in
`test_sprite_matrix_workflow_builder.py`), update those assertions to match
the new defaults.

- [ ] **Step 5: Update `sprite_matrix/README.md`**

In the "Face identity pass" section (the same section documenting FaceID and
the hair-color-drift/no-face-detected limitations), add a paragraph
describing the new per-region ControlNet conditioning: what problem it
solves (flat/shiny face vs. hatched body), how it works
(`ImpactControlNetApplyAdvancedSEGS` attaching per-segment ControlNet info
to the SEGS list, reusing the main pass's normal/depth/lineart maps), and
mention the three new `face_detailer_controlnet_normal/depth/lineart_weight`
knobs alongside the existing `denoise`/`faceid_weight`/`bbox_dilation` in the
spec JSON schema section.

- [ ] **Step 6: Clean up any test/comparison output files**

```bash
rm -f x:/Development/Abaddon/Study/gnn_studies/output/abby_b/spike_*.png
rm -f x:/Development/Abaddon/Study/gnn_studies/output/abby_b/experiment_*.png
rm -f x:/Development/Abaddon/Study/gnn_studies/output/jason_a/spike_*.png
rm -f x:/Development/Abaddon/Study/gnn_studies/output/jason_a/experiment_*.png
```
(and equivalent cleanup for any comparison files written under the
scratchpad temp dir during Steps 1-2.)

- [ ] **Step 7: Final commit and push**

```bash
cd Y:/working/BlueMoonFoundry/daz-script-server
git add docs/examples/rendering/sprite_matrix/config.py docs/examples/rendering/sprite_matrix/schema.py docs/examples/rendering/sprite_matrix/README.md tests/test_sprite_matrix_schema.py tests/test_sprite_matrix_workflow_builder.py
git commit -m "Tune face-identity ControlNet defaults from live comparison across two characters"
git pull --rebase
git push
git status
```
Expected: `git status` reports "up to date with origin" and a clean working tree.

---

## Self-Review

**Spec coverage:**
- "Insert `ImpactControlNetApplyAdvancedSEGS` chain between MaskToSEGS and SEGSDetailer" (spec Architecture) -> Task 1 Steps 1-2. Covered.
- "Reuse the main pass's already-retagged ControlNet outputs and source images" (spec Architecture) -> Task 1 Step 1's exact node references (`["21",0]`/`["31",0]`/`["41",0]` for control_net, `["20",0]`/`["30",0]`/`["40",0]` for control_image). Covered.
- New config surface (three `face_detailer_controlnet_*_weight` knobs, `start_percent`/`end_percent` fixed) -> Task 3 (plumbing) + Task 5 (live-tuned final values); fixed literals confirmed by Task 4 Step 3's `test_controlnet_chain_fixed_percent_literals`. Covered.
- "No new external dependencies" (spec) -> no task installs anything; Task 1's Step 3 JSON validation and Task 2's Step 5 manual check are the only environment-touching verification, both against the already-installed Impact Pack. Covered.
- Testing/rollout plan step 4 ("check this doesn't reintroduce any previously-fixed artifact") -> folded into Task 5 Step 1's expected-outcome text. Covered.
- Testing/rollout plan step 5 (README update) -> Task 5 Step 5. Covered.

**Placeholder scan:** No "TBD"/"TODO"/"add appropriate handling" phrases. Task 5's live-tuning steps intentionally don't pin exact final weight numbers (that's the point of a live comparison task, same pattern as the prior FaceID plan's Task 7), but every other step has concrete code, exact file paths, and runnable commands.

**Type consistency:** `face_detailer_controlnet_normal_weight`/`_depth_weight`/`_lineart_weight`, all `float`, are named and typed identically across Task 2 (function signature), Task 3 (`config.py` field, `schema.py` parse, CLI flag), and Task 4 (test assertions) -- verified by re-reading each task's code blocks side by side during this review.

No gaps found requiring a new task; plan is complete for the spec.
