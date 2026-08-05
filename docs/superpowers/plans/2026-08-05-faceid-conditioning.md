# FaceID Conditioning for Sprite Matrix Face-Identity Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the sprite matrix pipeline's low-denoise/real-pixel-source face identity pass with IPAdapter FaceID embedding conditioning, so the face pass can run at a denoise matching the body's stylization level while a face-recognition embedding (not low denoise) keeps the result identifiable as the source character.

**Architecture:** Keep the existing spatial detection chain (`UltralyticsDetectorProvider` → `BboxDetectorSEGS` → `SAMDetectorCombined` → `MaskToSEGS`) unchanged -- it decides *where* to refine. Remove `SetDefaultImageForSEGS` (node `"63"`). Insert `IPAdapterInsightFaceLoader` → `IPAdapterUnifiedLoaderFaceID` → `IPAdapterFaceID` before `ToBasicPipe`, patching the checkpoint+LoRA model with an identity embedding extracted from the original Daz beauty render (node `"2"`), before feeding it into `SEGSDetailer`.

**Tech Stack:** ComfyUI (`workflow_controlnet.json` API-format graph, `workflow_builder.py`), Python 3.12 (`dazpy`/sprite_matrix pipeline), `insightface` (new pip dependency in ComfyUI's embedded Python), IPAdapter FaceID SDXL model files.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-05-faceid-conditioning-design.md` -- read it before starting; this plan implements it verbatim.
- ComfyUI instance is at `http://127.0.0.1:8188`, embedded Python at `Y:/ai/ComfyUI_portable/ComfyUI_windows_portable/python_embeded/python.exe`, models root at `Y:/ai/ComfyUI_portable/ComfyUI_windows_portable/ComfyUI/models/`.
- `insightface` provider defaults to `"CPU"` (avoid a second CUDA-build dependency stacked on top of insightface itself).
- Fallback per spec decision 1: if `insightface` proves unworkable, swap to IPAdapter Plus Face (`IPAdapterUnifiedLoader`/`IPAdapterAdvanced` against the already-installed `ip-adapter-plus-face_sdxl_vit-h.bin`) -- flag this explicitly if Task 1 fails rather than silently improvising.
- Every code change must keep `docs/examples/rendering/sprite_matrix`'s existing pattern: fixed/non-tunable node parameters live as literals in `workflow_controlnet.json`; only parameters that plausibly need per-run tuning become `config.py`/`schema.py`/CLI-exposed knobs.
- Sprite matrix and comfyui_enhance both define `config.py`/`workflow_builder.py` with the same module name; any new test file must follow the existing `sys.modules.pop(...)` eviction pattern already used in `tests/test_sprite_matrix_workflow_builder.py`.

---

## File Structure

- Modify: `docs/examples/rendering/sprite_matrix/workflow_controlnet.json` -- remove `SetDefaultImageForSEGS` node, add 3 new IPAdapter FaceID nodes, rewire `ToBasicPipe`/`SEGSDetailer`.
- Modify: `docs/examples/rendering/sprite_matrix/workflow_builder.py` -- new `face_detailer_faceid_weight` parameter, updated node-deletion list, updated wiring comment.
- Modify: `docs/examples/rendering/sprite_matrix/config.py` -- new `face_detailer_faceid_weight` field on `ComfyUIStageConfig`, re-tuned `face_detailer_denoise` default (value pending Task 7's live comparison).
- Modify: `docs/examples/rendering/sprite_matrix/schema.py` -- parse the new field from `comfyui.face_detailer.faceid_weight`.
- Modify: `docs/examples/rendering/sprite_matrix/stylize_stage.py` -- pass the new field through to `build_controlnet_workflow`.
- Modify: `docs/examples/rendering/sprite_matrix/render_shot.py` -- new `--face-detailer-faceid-weight` CLI flag.
- Modify: `docs/examples/rendering/sprite_matrix/example_spec.json` -- document the new field.
- Modify: `docs/examples/rendering/sprite_matrix/README.md` -- document the new dependency (insightface + FaceID model files) and the new config knob.
- Modify: `tests/test_sprite_matrix_workflow_builder.py` -- update node-presence/wiring assertions for the new chain, remove assertions about the deleted `SetDefaultImageForSEGS` node.
- Modify: `tests/test_sprite_matrix_schema.py` -- add coverage for the new field.

No new files. This is a rewiring of one existing subsystem, not a new module.

---

### Task 1: Install and verify `insightface`

**Files:** none (environment setup only)

**Interfaces:** N/A

- [ ] **Step 1: Install insightface into ComfyUI's embedded Python**

Run:
```bash
"Y:/ai/ComfyUI_portable/ComfyUI_windows_portable/python_embeded/python.exe" -m pip install insightface
```

- [ ] **Step 2: Verify the import succeeds**

Run:
```bash
"Y:/ai/ComfyUI_portable/ComfyUI_windows_portable/python_embeded/python.exe" -c "import insightface; print(insightface.__version__)"
```
Expected: prints a version string with no traceback. If this fails (compilation error, missing wheel for Python 3.13, etc.), STOP and report back -- do not silently switch to the Plus Face fallback without confirming with the user first, per the Global Constraints fallback note.

- [ ] **Step 3: Restart ComfyUI and confirm the FaceID nodes are now usable**

After restarting ComfyUI, run:
```bash
curl -s "http://127.0.0.1:8188/object_info/IPAdapterInsightFaceLoader"
```
Expected: a JSON object (not `{}`) with a `provider` input listing `["CPU", "CUDA", "ROCM"]`. An empty `{}` means the node still isn't registering -- check ComfyUI's `user/comfyui.log` for an import error in the IPAdapter-plus custom node package (same diagnostic approach used earlier this session for the Impact-Subpack registration problem).

---

### Task 2: Download the FaceID SDXL model files

**Files:** none (model files, not repo files)

**Interfaces:** N/A

- [ ] **Step 1: Download the FaceID Plus V2 SDXL ipadapter weights**

Run:
```bash
mkdir -p "Y:/ai/ComfyUI_portable/ComfyUI_windows_portable/ComfyUI/models/ipadapter"
curl -sL -o "Y:/ai/ComfyUI_portable/ComfyUI_windows_portable/ComfyUI/models/ipadapter/ip-adapter-faceid-plusv2_sdxl.bin" "https://huggingface.co/h94/IP-Adapter-FaceID/resolve/main/ip-adapter-faceid-plusv2_sdxl.bin"
```

- [ ] **Step 2: Download its companion LoRA**

Run:
```bash
curl -sL -o "Y:/ai/ComfyUI_portable/ComfyUI_windows_portable/ComfyUI/models/loras/ip-adapter-faceid-plusv2_sdxl_lora.safetensors" "https://huggingface.co/h94/IP-Adapter-FaceID/resolve/main/ip-adapter-faceid-plusv2_sdxl_lora.safetensors"
```

- [ ] **Step 3: Verify both files downloaded as real binary content, not an HTML error page**

Run:
```bash
python3 -c "
for p in [
    'Y:/ai/ComfyUI_portable/ComfyUI_windows_portable/ComfyUI/models/ipadapter/ip-adapter-faceid-plusv2_sdxl.bin',
    'Y:/ai/ComfyUI_portable/ComfyUI_windows_portable/ComfyUI/models/loras/ip-adapter-faceid-plusv2_sdxl_lora.safetensors',
]:
    with open(p, 'rb') as f:
        head = f.read(8)
    import os
    print(p, os.path.getsize(p), head)
"
```
Expected: both files are multiple megabytes (not a tiny HTML error page) and their headers don't start with `b'<!DOCTYPE'` or `b'<html'`.

- [ ] **Step 4: Restart ComfyUI and confirm the model files are discoverable**

Run:
```bash
curl -s "http://127.0.0.1:8188/object_info/IPAdapterUnifiedLoaderFaceID"
```
Expected: the node's `preset` options list includes `"FACEID PLUS V2"` (this doesn't confirm the specific file loaded correctly, just that the node registered -- Task 6's live run is the real end-to-end check).

---

### Task 3: Rewire `workflow_controlnet.json`

**Files:**
- Modify: `docs/examples/rendering/sprite_matrix/workflow_controlnet.json`

**Interfaces:**
- Consumes: existing nodes `"1b"`/`"1"` (checkpoint+LoRA model), `"2"` (beauty `LoadImage`), `"4"`/`"5"` (prompt `CLIPTextEncode`), `"69"` (`MaskToSEGS` output).
- Produces: new nodes `"70"` (`IPAdapterInsightFaceLoader`), `"71"` (`IPAdapterUnifiedLoaderFaceID`), `"72"` (`IPAdapterFaceID`) for `workflow_builder.py` to wire dynamically in Task 4.

- [ ] **Step 1: Delete the `SetDefaultImageForSEGS` node**

In `workflow_controlnet.json`, delete this entire node (currently keyed `"63"`):
```json
"63": {
    "class_type": "SetDefaultImageForSEGS",
    "inputs": {
      "segs": ["69", 0],
      "image": ["2", 0],
      "override": true
    }
  },
```

- [ ] **Step 2: Add the three new IPAdapter FaceID nodes**

Insert after node `"69"` (`MaskToSEGS`):
```json
  "70": {
    "class_type": "IPAdapterInsightFaceLoader",
    "inputs": {
      "provider": "CPU"
    }
  },
  "71": {
    "class_type": "IPAdapterUnifiedLoaderFaceID",
    "inputs": {
      "model": ["1b", 0],
      "preset": "FACEID PLUS V2",
      "lora_strength": 0.6,
      "provider": "CPU"
    }
  },
  "72": {
    "class_type": "IPAdapterFaceID",
    "inputs": {
      "model": ["71", 0],
      "ipadapter": ["71", 1],
      "insightface": ["70", 0],
      "image": ["2", 0],
      "weight": "__FACE_DETAILER_FACEID_WEIGHT__",
      "weight_faceidv2": 1.0,
      "weight_type": "linear",
      "combine_embeds": "concat",
      "start_at": 0.0,
      "end_at": 1.0,
      "embeds_scaling": "V only"
    }
  },
```
`"71"`'s `"model"` value (`["1b", 0]`) is a placeholder -- `workflow_builder.py` overwrites it with `face_model_ref` in Task 4, exactly like it currently overwrites `"64"`'s `"model"` field today.

- [ ] **Step 3: Rewire `ToBasicPipe` (`"64"`) to use the FaceID-conditioned model**

Change:
```json
  "64": {
    "class_type": "ToBasicPipe",
    "inputs": {
      "model": ["1b", 0],
      "clip": ["1b", 1],
      "vae": ["1", 2],
      "positive": ["4", 0],
      "negative": ["5", 0]
    }
  },
```
to:
```json
  "64": {
    "class_type": "ToBasicPipe",
    "inputs": {
      "model": ["72", 0],
      "clip": ["1b", 1],
      "vae": ["1", 2],
      "positive": ["4", 0],
      "negative": ["5", 0]
    }
  },
```
(`"model"` is now fixed to `["72", 0]` since the FaceID-patched model already incorporates whatever `face_model_ref` was; `"clip"` stays a placeholder for `workflow_builder.py`'s existing per-LoRA rewiring, unchanged.)

- [ ] **Step 4: Rewire `SEGSDetailer` (`"65"`) to read segs directly from `MaskToSEGS`**

Change:
```json
      "segs": ["63", 0],
```
to:
```json
      "segs": ["69", 0],
```
inside node `"65"`'s `inputs`.

- [ ] **Step 5: Validate the JSON is well-formed**

Run:
```bash
python -c "import json; json.load(open('Y:/working/BlueMoonFoundry/daz-script-server/docs/examples/rendering/sprite_matrix/workflow_controlnet.json'))"
```
Expected: no output, no traceback (valid JSON).

---

### Task 4: Update `workflow_builder.py`

**Files:**
- Modify: `docs/examples/rendering/sprite_matrix/workflow_builder.py`

**Interfaces:**
- Consumes: `face_model_ref`/`face_clip_ref` (already computed earlier in the function based on `lora_name` presence).
- Produces: `build_controlnet_workflow(..., face_detailer_faceid_weight: float = 1.0, ...)` -- new keyword parameter; all existing callers (`stylize_stage.py`, `render_shot.py`) must be updated in Task 5 to pass it, but the default keeps old call sites working during incremental development.

- [ ] **Step 1: Add the new parameter to the function signature**

In `build_controlnet_workflow`, change:
```python
    face_detailer_enabled: bool = True,
    face_detailer_denoise: float = 0.15,
    face_detailer_guide_size: float = 512.0,
    face_detailer_bbox_dilation: int = 100,
) -> dict:
```
to:
```python
    face_detailer_enabled: bool = True,
    face_detailer_denoise: float = 0.15,
    face_detailer_guide_size: float = 512.0,
    face_detailer_bbox_dilation: int = 100,
    face_detailer_faceid_weight: float = 1.0,
) -> dict:
```

- [ ] **Step 2: Replace the `"64"["model"]` wiring with `"71"["model"]`, and set the FaceID weight**

In the `if face_detailer_enabled:` block, change:
```python
        workflow["62"]["inputs"]["dilation"] = int(face_detailer_bbox_dilation)
        workflow["64"]["inputs"]["model"] = face_model_ref
        workflow["64"]["inputs"]["clip"] = face_clip_ref
```
to:
```python
        workflow["62"]["inputs"]["dilation"] = int(face_detailer_bbox_dilation)
        workflow["71"]["inputs"]["model"] = face_model_ref
        workflow["64"]["inputs"]["clip"] = face_clip_ref
        workflow["72"]["inputs"]["weight"] = float(face_detailer_faceid_weight)
```
(`"64"["model"]` no longer needs setting here -- it's fixed to `["72", 0]` in the JSON template per Task 3 Step 3.)

- [ ] **Step 3: Update the node-deletion list for the disabled branch**

Change:
```python
    else:
        for node_id in ("60", "62", "63", "64", "65", "66", "67", "68", "69"):
            del workflow[node_id]
```
to:
```python
    else:
        for node_id in ("60", "62", "64", "65", "66", "67", "68", "69", "70", "71", "72"):
            del workflow[node_id]
```
(`"63"` removed since it no longer exists in the template; `"70"`, `"71"`, `"72"` added.)

- [ ] **Step 4: Update the explanatory comment**

Replace the comment block above the `if face_detailer_enabled:` line (the one starting `# Second pass: detect the face...` and ending with the "blacker than black halo" paragraph) with:
```python
        # Second pass: detect the face in the stylized output (node "7"),
        # refine that rectangular hint into a true head/hair silhouette via
        # SAM (SAMLoader + SAMDetectorCombined + MaskToSEGS), then run
        # SEGSDetailer on it using a model patched with IPAdapter FaceID
        # (IPAdapterInsightFaceLoader + IPAdapterUnifiedLoaderFaceID +
        # IPAdapterFaceID) conditioned on the ORIGINAL Daz beauty render
        # (node "2") as the identity reference photo.
        #
        # This replaced an earlier version that sourced the crop's pixels
        # from the real beauty render via SetDefaultImageForSEGS and relied
        # on a low denoise (0.15) to stay close to the source face. A live
        # four-way comparison (denoise 0.15/0.20, with/without a reinforced
        # hatching prompt) confirmed that approach had a hard ceiling: at
        # low denoise there's no room for the model to add the heavy ink
        # cross-hatching the body gets at its own 0.35 denoise, regardless
        # of prompt wording, producing a visibly smoother/more photoreal
        # face than the stylized body. Raising denoise enough to close that
        # gap is roughly where identity drift was already confirmed to
        # reappear with the old mechanism -- FaceID embedding conditioning
        # decouples identity from denoise, so this pass can now run at a
        # denoise that actually matches the body's stylization.
        #
        # UltralyticsDetectorProvider's face_yolov8m.pt is bbox-only (no real
        # segmentation), so BboxDetectorSEGS's mask is a plain rectangle.
        # That caused two live-confirmed problems: too small a dilation
        # leaves a color seam at the hairline, but enlarging dilation enough
        # to cover the hair also pulls in surrounding black background,
        # which SEGSDetailer then subtly re-stylizes into a visible
        # rectangular "box" against the clean main-pass background. Fix:
        # refine that rectangular hint into an actual head/hair silhouette
        # via SAM before SEGSDetailer. bbox_expansion (in
        # workflow_controlnet.json, on SAMDetectorCombined) controls how
        # generous a search HINT SAM gets -- kept large so it reliably finds
        # the whole head/hair. Its own `dilation` and SEGSPaste's `feather`,
        # however, must stay small: even after SAM produces a true
        # silhouette, dilating/feathering it wider than a few pixels
        # re-encodes a thin ring of background through the VAE round trip,
        # which comes back very slightly darker than the untouched
        # background -- a subtle but real "blacker than black" halo,
        # confirmed live via pixel sampling (background pixels dipped to
        # ~[1,1,0] against a ~[5,4,4] ambient black).
```

- [ ] **Step 5: Verify the file still compiles**

Run:
```bash
python -m py_compile "Y:/working/BlueMoonFoundry/daz-script-server/docs/examples/rendering/sprite_matrix/workflow_builder.py"
```
Expected: no output, no traceback.

- [ ] **Step 6: Commit**

```bash
git add docs/examples/rendering/sprite_matrix/workflow_controlnet.json docs/examples/rendering/sprite_matrix/workflow_builder.py
git commit -m "Wire IPAdapter FaceID into the sprite matrix face-identity pass"
```

---

### Task 5: Plumb the new config knob through config/schema/stages/CLI

**Files:**
- Modify: `docs/examples/rendering/sprite_matrix/config.py`
- Modify: `docs/examples/rendering/sprite_matrix/schema.py`
- Modify: `docs/examples/rendering/sprite_matrix/stylize_stage.py`
- Modify: `docs/examples/rendering/sprite_matrix/render_shot.py`
- Modify: `docs/examples/rendering/sprite_matrix/example_spec.json`

**Interfaces:**
- Consumes: `build_controlnet_workflow(..., face_detailer_faceid_weight: float, ...)` from Task 4.
- Produces: `ComfyUIStageConfig.face_detailer_faceid_weight: float` (default `1.0`), parsed from spec JSON key `comfyui.face_detailer.faceid_weight`, and CLI flag `--face-detailer-faceid-weight`.

- [ ] **Step 1: Add the field to `ComfyUIStageConfig`**

In `config.py`, after the existing `face_detailer_bbox_dilation` field, add:
```python
    # IPAdapter FaceID's own conditioning strength (0 = no identity
    # conditioning, higher = stronger identity lock at the cost of the
    # model's freedom to stylize). Live-tuned in Task 7 alongside
    # face_detailer_denoise -- the two interact.
    face_detailer_faceid_weight: float = 1.0
```

- [ ] **Step 2: Update the `face_detailer_denoise` default and its comment**

Replace:
```python
    # 0.15 chosen after live comparison against 0.25/0.15/0.10 side-by-side
    # with the real Daz beauty render: 0.25 showed visible identity drift
    # (heavier eyebrows, more angular jaw); 0.15 stayed close to the source
    # while still keeping visible ink-line/cel-shaded stylization.
    face_detailer_denoise: float = 0.15
```
with a placeholder noting Task 7 will set the real value (this step is intentionally provisional -- Task 7 supersedes it):
```python
    # Re-tuned in Task 7 of docs/superpowers/plans/2026-08-05-faceid-conditioning.md
    # once FaceID conditioning decouples identity from denoise -- expected
    # to land higher than the previous 0.15 (chosen back when low denoise
    # was the only identity-preservation mechanism available).
    face_detailer_denoise: float = 0.15
```

- [ ] **Step 3: Parse the new field in `schema.py`**

In `load_spec`, after the line `face_detailer_denoise = face_detailer_raw.get("denoise", 0.15)`, add:
```python
    face_detailer_faceid_weight = face_detailer_raw.get("faceid_weight", 1.0)
```
and in the `ComfyUIStageConfig(...)` constructor call, after `face_detailer_bbox_dilation=int(face_detailer_raw.get("bbox_dilation", 100)),`, add:
```python
        face_detailer_faceid_weight=float(face_detailer_faceid_weight),
```

- [ ] **Step 4: Pass it through in `stylize_stage.py`**

After `face_detailer_bbox_dilation=cfg.comfyui.face_detailer_bbox_dilation,` in the `build_controlnet_workflow(...)` call, add:
```python
                face_detailer_faceid_weight=cfg.comfyui.face_detailer_faceid_weight,
```

- [ ] **Step 5: Add the CLI flag in `render_shot.py`**

After the `--face-detailer-bbox-dilation` argument definition, add:
```python
    p.add_argument(
        "--face-detailer-faceid-weight",
        type=float,
        default=comfy_defaults.face_detailer_faceid_weight,
        help="IPAdapter FaceID conditioning strength for the face-identity pass "
        "(0 = no identity conditioning, higher = stronger identity lock)",
    )
```
And after `face_detailer_bbox_dilation=args.face_detailer_bbox_dilation,` in `stylize_shot`'s `build_controlnet_workflow(...)` call, add:
```python
                face_detailer_faceid_weight=args.face_detailer_faceid_weight,
```

- [ ] **Step 6: Document the field in `example_spec.json`**

In the `face_detailer` block, add `"faceid_weight": 1.0` alongside the existing `enabled`/`denoise`/`guide_size`/`bbox_dilation` fields.

- [ ] **Step 7: Verify everything still compiles and the example dry-run works**

Run:
```bash
cd "Y:/working/BlueMoonFoundry/daz-script-server"
python -m py_compile docs/examples/rendering/sprite_matrix/*.py
cd docs/examples/rendering/sprite_matrix
python main.py --spec example_spec.json --dry-run
```
Expected: `py_compile` produces no output; the dry-run prints the combo/camera work plan with no traceback.

- [ ] **Step 8: Commit**

```bash
cd "Y:/working/BlueMoonFoundry/daz-script-server"
git add docs/examples/rendering/sprite_matrix/config.py docs/examples/rendering/sprite_matrix/schema.py docs/examples/rendering/sprite_matrix/stylize_stage.py docs/examples/rendering/sprite_matrix/render_shot.py docs/examples/rendering/sprite_matrix/example_spec.json
git commit -m "Add face_detailer_faceid_weight config knob"
```

---

### Task 6: Update unit tests

**Files:**
- Modify: `tests/test_sprite_matrix_workflow_builder.py`
- Modify: `tests/test_sprite_matrix_schema.py`

**Interfaces:**
- Consumes: `build_controlnet_workflow` and `load_spec` from Tasks 4-5.

- [ ] **Step 1: Update `test_required_node_keys` and `test_required_class_types`**

In `TestBuildControlnetWorkflow`, change:
```python
    def test_required_node_keys(self):
        for key in (
            "1", "1b", "2", "3", "4", "5", "6", "7", "8",
            "20", "21", "22", "30", "31", "32", "40", "41", "42", "50",
            "60", "62", "63", "64", "65", "66", "67", "68", "69",
        ):
            self.assertIn(key, self.wf, f"Missing node {key}")
```
to:
```python
    def test_required_node_keys(self):
        for key in (
            "1", "1b", "2", "3", "4", "5", "6", "7", "8",
            "20", "21", "22", "30", "31", "32", "40", "41", "42", "50",
            "60", "62", "64", "65", "66", "67", "68", "69", "70", "71", "72",
        ):
            self.assertIn(key, self.wf, f"Missing node {key}")
```
and change:
```python
            "SetDefaultImageForSEGS",
            "ToBasicPipe",
```
to:
```python
            "IPAdapterInsightFaceLoader",
            "IPAdapterUnifiedLoaderFaceID",
            "IPAdapterFaceID",
            "ToBasicPipe",
```
in `test_required_class_types`.

- [ ] **Step 2: Run the two updated tests to see them fail against the old code**

(Skip this step if Tasks 3-4 are already applied -- this ordering assumes tests are updated after the implementation, matching how this pipeline's other features were built this session. If running standalone/out of order:)
Run:
```bash
cd "Y:/working/BlueMoonFoundry/daz-script-server"
python -m pytest tests/test_sprite_matrix_workflow_builder.py::TestBuildControlnetWorkflow::test_required_node_keys tests/test_sprite_matrix_workflow_builder.py::TestBuildControlnetWorkflow::test_required_class_types -v
```
Expected: PASS (Tasks 3-4 already implement the graph these tests check).

- [ ] **Step 3: Replace `test_crop_source_swapped_to_original_beauty_render` with a FaceID wiring test**

In `TestBuildControlnetWorkflowFaceDetailer`, replace:
```python
    def test_crop_source_swapped_to_original_beauty_render(self):
        # The whole point: refine pixels cropped from the REAL Daz render
        # (node "2"), not from the already-stylized/drifted output -- a
        # low-denoise refine of the wrong face would just polish the wrong
        # face rather than pull it back toward the real identity.
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertEqual(wf["63"]["inputs"]["segs"], ["69", 0])
        self.assertEqual(wf["63"]["inputs"]["image"], ["2", 0])
        self.assertTrue(wf["63"]["inputs"]["override"])
        self.assertEqual(wf["65"]["inputs"]["segs"], ["63", 0])
```
with:
```python
    def test_segs_detailer_reads_segs_directly_from_masktosegs(self):
        # No more SetDefaultImageForSEGS pixel-source swap -- identity now
        # comes from FaceID embedding conditioning on the model, not from
        # sourcing crop pixels from the real beauty render.
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertEqual(wf["65"]["inputs"]["segs"], ["69", 0])
        self.assertNotIn("63", wf)

    def test_faceid_conditioned_on_original_beauty_render(self):
        # The identity reference photo for FaceID's embedding extraction is
        # the ORIGINAL Daz beauty render (node "2"), not the stylized output
        # -- this is what anchors identity now that SetDefaultImageForSEGS
        # is gone.
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertEqual(wf["72"]["inputs"]["image"], ["2", 0])
        self.assertEqual(wf["72"]["inputs"]["insightface"], ["70", 0])
        self.assertEqual(wf["72"]["inputs"]["model"], ["71", 0])
        self.assertEqual(wf["72"]["inputs"]["ipadapter"], ["71", 1])

    def test_faceid_patched_model_feeds_basic_pipe(self):
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertEqual(wf["64"]["inputs"]["model"], ["72", 0])

    def test_faceid_weight_configurable(self):
        wf = build_controlnet_workflow(**{**_DEFAULT_KWARGS, "face_detailer_faceid_weight": 0.75})
        self.assertAlmostEqual(wf["72"]["inputs"]["weight"], 0.75)
```

- [ ] **Step 4: Update `test_wired_to_lora_model_and_clip_when_lora_present`**

Change:
```python
    def test_wired_to_lora_model_and_clip_when_lora_present(self):
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertEqual(wf["64"]["inputs"]["model"], ["1b", 0])
        self.assertEqual(wf["64"]["inputs"]["clip"], ["1b", 1])
```
to (the LoRA-patched model now feeds the FaceID unified loader, node `"71"`, not `"64"` directly):
```python
    def test_wired_to_lora_model_and_clip_when_lora_present(self):
        wf = build_controlnet_workflow(**_DEFAULT_KWARGS)
        self.assertEqual(wf["71"]["inputs"]["model"], ["1b", 0])
        self.assertEqual(wf["64"]["inputs"]["clip"], ["1b", 1])
```

- [ ] **Step 5: Update `TestBuildControlnetWorkflowNoLora.test_face_detailer_also_rewired_to_checkpoint`**

Change:
```python
    def test_face_detailer_also_rewired_to_checkpoint(self):
        self.assertEqual(self.wf["64"]["inputs"]["model"], ["1", 0])
        self.assertEqual(self.wf["64"]["inputs"]["clip"], ["1", 1])
```
to:
```python
    def test_face_detailer_also_rewired_to_checkpoint(self):
        self.assertEqual(self.wf["71"]["inputs"]["model"], ["1", 0])
        self.assertEqual(self.wf["64"]["inputs"]["clip"], ["1", 1])
```

- [ ] **Step 6: Update `test_disabled_removes_nodes_and_reverts_save_image`**

Change:
```python
    def test_disabled_removes_nodes_and_reverts_save_image(self):
        wf = build_controlnet_workflow(**{**_DEFAULT_KWARGS, "face_detailer_enabled": False})
        for node_id in ("60", "62", "63", "64", "65", "66", "67", "68", "69"):
            self.assertNotIn(node_id, wf)
        self.assertEqual(wf["8"]["inputs"]["images"], ["7", 0])
        types = {v["class_type"] for v in wf.values()}
        for class_type in (
            "UltralyticsDetectorProvider", "BboxDetectorSEGS", "SAMLoader",
            "SAMDetectorCombined", "MaskToSEGS", "SEGSDetailer", "SEGSPaste",
        ):
            self.assertNotIn(class_type, types)
```
to:
```python
    def test_disabled_removes_nodes_and_reverts_save_image(self):
        wf = build_controlnet_workflow(**{**_DEFAULT_KWARGS, "face_detailer_enabled": False})
        for node_id in ("60", "62", "64", "65", "66", "67", "68", "69", "70", "71", "72"):
            self.assertNotIn(node_id, wf)
        self.assertEqual(wf["8"]["inputs"]["images"], ["7", 0])
        types = {v["class_type"] for v in wf.values()}
        for class_type in (
            "UltralyticsDetectorProvider", "BboxDetectorSEGS", "SAMLoader",
            "SAMDetectorCombined", "MaskToSEGS", "SEGSDetailer", "SEGSPaste",
            "IPAdapterInsightFaceLoader", "IPAdapterUnifiedLoaderFaceID", "IPAdapterFaceID",
        ):
            self.assertNotIn(class_type, types)
```

- [ ] **Step 7: Add schema coverage for the new field**

In `tests/test_sprite_matrix_schema.py`, in `test_face_detailer_defaults`, add after the existing `bbox_dilation` assertion:
```python
        self.assertAlmostEqual(cfg.comfyui.face_detailer_faceid_weight, 1.0)
```
In `test_face_detailer_overrides_parsed`, add `"faceid_weight": 0.5` to the `face_detailer` dict under test, and add:
```python
        self.assertAlmostEqual(cfg.comfyui.face_detailer_faceid_weight, 0.5)
```

- [ ] **Step 8: Run the full sprite_matrix test suite**

Run:
```bash
cd "Y:/working/BlueMoonFoundry/daz-script-server"
python -m pytest tests/test_sprite_matrix_*.py -q
```
Expected: all tests pass (count will be a few more than the 83 passed / 1 skipped baseline from before this plan, due to the new tests added in Step 3 and Step 7).

- [ ] **Step 9: Commit**

```bash
git add tests/test_sprite_matrix_workflow_builder.py tests/test_sprite_matrix_schema.py
git commit -m "Update sprite matrix tests for IPAdapter FaceID wiring"
```

---

### Task 7: Live verification, default tuning, docs, and final push

**Files:**
- Modify: `docs/examples/rendering/sprite_matrix/config.py` (finalize `face_detailer_denoise` default, set based on findings)
- Modify: `docs/examples/rendering/sprite_matrix/schema.py` (finalize matching default)
- Modify: `docs/examples/rendering/sprite_matrix/README.md` (document the new dependency and knob)

**Interfaces:** N/A (verification + tuning task, no new interfaces)

- [ ] **Step 1: Run a real render + stylize against the existing `abby_b` character**

Reuse the render files already on disk at
`x:/Development/Abaddon/Study/gnn_studies/output/abby_b/renders/shot001/`
(beauty PNG + converted canvas PNGs + lineart already exist from the earlier
session). Build and queue several `face_detailer_denoise` /
`face_detailer_faceid_weight` combinations directly via
`build_controlnet_workflow` (the same ad-hoc-script pattern used earlier
this session for the four-variant denoise experiment), e.g. denoise in
`(0.25, 0.35)` crossed with faceid_weight in `(0.8, 1.0, 1.2)`, saving each
to a distinct file for comparison. Crop each result to the face region and
build a side-by-side comparison image (same `cv2.hstack` + label pattern
used for the earlier `denoise_compare2.png`), including the original beauty
render and the current 0.15-denoise/no-FaceID stylized result as reference
points. If no combination in that grid closes the style gap without losing
identity, also try swapping node `"71"`'s `preset` from `"FACEID PLUS V2"`
to `"FACEID PORTRAIT (style transfer)"` (per the spec's note that portrait
presets exist specifically to let more style through while retaining
identity) at a couple of denoise/weight points, before concluding the
approach needs further rework.

Expected: at least one combination shows both (a) visible ink-line/hatching
texture on the face comparable to the body, and (b) an identity that's
still clearly recognizable as the same character as the source beauty
render, without the earlier photoreal/plastic mismatch.

- [ ] **Step 2: Cross-check against the earlier male test character**

Re-render (or reuse existing render files if still on disk) the male
character used earlier this session (`shot001`, `Front Camera`/`Back
Camera`) and repeat the same comparison grid, to confirm the chosen
denoise/faceid_weight combination isn't overfit to one character's hair
color/features.

- [ ] **Step 3: Pick final defaults and update the config**

Based on Steps 1-2, set `face_detailer_denoise` and
`face_detailer_faceid_weight` defaults in `config.py` (replacing the
provisional `0.15`/`1.0` values from Tasks 4-5) and the matching fallback
defaults in `schema.py`'s `load_spec`. Update the explanatory comments
above both fields to describe what was actually observed (mirroring the
existing comment style for `face_detailer_bbox_dilation` -- state the
finding, not just the number).

- [ ] **Step 4: Re-run the full sprite_matrix test suite**

Run:
```bash
cd "Y:/working/BlueMoonFoundry/daz-script-server"
python -m pytest tests/test_sprite_matrix_*.py -q
```
Expected: all tests pass. If Step 3 changed any default that a test asserts against verbatim (e.g. a hardcoded `0.15` in `test_face_detailer_defaults`), update that assertion to match the new default.

- [ ] **Step 5: Update `sprite_matrix/README.md`**

Add `insightface` (pip package) and the FaceID SDXL model files
(`ip-adapter-faceid-plusv2_sdxl.bin` in `models/ipadapter/`,
`ip-adapter-faceid-plusv2_sdxl_lora.safetensors` in `models/loras/`) to the
Prerequisites section, alongside the existing Impact Pack/Impact-Subpack/SAM
entries. Update the "Face identity pass" section's description of *how*
identity is preserved (FaceID embedding, not low-denoise-from-real-pixels)
to match the new mechanism, and mention the new `face_detailer_faceid_weight`
knob alongside `denoise`/`guide_size`/`bbox_dilation` in the spec JSON
schema section.

- [ ] **Step 6: Clean up any test/comparison output files**

Run:
```bash
rm -f x:/Development/Abaddon/Study/gnn_studies/output/abby_b/experiment_*.png
```
(and equivalent cleanup for any comparison files written under the male
character's output directory or the scratchpad temp dir during Steps 1-2).

- [ ] **Step 7: Final commit and push**

```bash
cd "Y:/working/BlueMoonFoundry/daz-script-server"
git add docs/examples/rendering/sprite_matrix/config.py docs/examples/rendering/sprite_matrix/schema.py docs/examples/rendering/sprite_matrix/README.md tests/test_sprite_matrix_schema.py
git commit -m "Tune FaceID conditioning defaults from live comparison across two characters"
git pull --rebase
git push
git status
```
Expected: `git status` reports "up to date with origin" and a clean working tree.

---

## Self-Review

**Spec coverage:**
- "Replace, not augment" (spec Decision 2) → Task 3 Step 1 removes `SetDefaultImageForSEGS`; Task 3 Steps 3-4 rewire `ToBasicPipe`/`SEGSDetailer` off it. Covered.
- Architecture chain (spec's node-by-node diagram) → Task 3 Step 2 adds exactly `IPAdapterInsightFaceLoader` → `IPAdapterUnifiedLoaderFaceID` → `IPAdapterFaceID`, wired as specified. Covered.
- "insightface's face-recognition model... unverified until tried" (spec Architecture section) → Task 1 Step 2 is the verification point; Global Constraints calls out not silently falling back without confirming with the user. Covered.
- New config surface (`face_detailer_faceid_weight`, re-tuned `face_detailer_denoise`) → Task 5 (plumbing) + Task 7 (live-tuned final values). Covered.
- "preset is a second live-tunable choice alongside denoise" (spec, after self-review edit) → Task 3 hardcodes `"FACEID PLUS V2"` as a starting point; Task 7 Step 1 now explicitly calls out trying `"FACEID PORTRAIT (style transfer)"` as a fallback if the denoise/weight grid alone doesn't close the style gap (fixed inline during this self-review rather than adding a whole new task, since it's the same live-experiment mechanism with one more axis).
- Testing/rollout plan step 6 ("update unit tests... once live-verified defaults are known") → Task 6 updates wiring tests before Task 7 tunes defaults; Task 7 Step 4 catches any test that hardcoded the old default. Covered, just reordered slightly from the spec's literal step numbering (wiring tests don't need to wait for tuned defaults, only default-value tests do).
- Testing/rollout plan step 6 (README update) → Task 7 Step 5. Covered.
- Fallback to Plus Face if insightface fails → Global Constraints states it explicitly; not a task of its own since it's a conditional branch, not the primary path.

**Placeholder scan:** No "TBD"/"TODO"/"add appropriate handling" phrases. Task 7's live-tuning steps intentionally don't pin exact final denoise/weight numbers (that's the point of a live comparison task), but every other step has concrete code, exact file paths, and runnable commands.

**Type consistency:** `face_detailer_faceid_weight: float` is consistent across Task 4 (function signature), Task 5 (`config.py` field, `schema.py` parse, CLI flag), and Task 6 (test assertions) -- same name, same type, throughout.

Addressed the one gap found above by folding a preset-variation note into Task 7 Step 1 rather than adding a new task -- the plan is otherwise complete for the spec.
