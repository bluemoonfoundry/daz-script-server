# Sprite Matrix Pipeline

Given a Daz Studio scene with one sprite already loaded (a specific outfit,
A-pose) and a JSON spec describing a matrix of pose x expression
combinations, this pipeline renders front and over-the-shoulder (back)
camera angles for every combo, then stylizes each render into a
"graphic-novel naturalism" look via ComfyUI.

## How it works

1. **Render stage** (`render_stage.py`): for each combo, restores the scene
   to a pristine baseline, applies the named pose preset + named expression
   preset + any per-combo overrides, then renders the beauty image plus
   Normal and Depth Iray Canvas passes (AOVs) from both cameras.
2. **Stylize stage** (`stylize_stage.py`): converts the Normal/Depth EXR
   canvases to PNG, derives a Canny/lineart pass from the beauty render, and
   submits a ComfyUI img2img workflow conditioned on all three passes plus a
   fixed checkpoint/LoRA, so pose/structure stays locked to the Daz render
   while the graphic-novel look comes from Stable Diffusion. All three
   passes are conditioned through a single SDXL **union** ControlNet model
   (e.g. `controlnet-union-sdxl-1.0.safetensors`), loaded once and re-tagged
   per pass via ComfyUI's `SetUnionControlNetType` node (`normal`, `depth`,
   `canny/lineart/anime_lineart/mlsd`) -- not three separate per-type models.
3. **Face identity pass** (enabled by default, `comfyui.face_detailer` in the
   spec / `--face-detailer`/`--no-face-detailer` for `render_shot.py`): the
   main pass has little resolution or conditioning signal to keep a small
   face recognizable, so it detects the face in the stylized output and
   re-runs the sampler on just that region. Because the face detector
   (`UltralyticsDetectorProvider`/`bbox/face_yolov8m.pt`) only produces a
   rectangular bounding box, that rectangle is refined into an actual
   head/hair silhouette via SAM (`SAMLoader` + `SAMDetectorCombined` +
   `MaskToSEGS`) before refining -- a plain rectangular mask either cuts off
   the hair (leaving a hair-color seam at the boundary) or, if dilated
   enough to cover it, pulls in surrounding background that gets subtly
   re-stylized into a visible box artifact. Both were confirmed live before
   adding the SAM step. Requires ComfyUI's Impact Pack with the
   separately-installed
   [Impact-Subpack](https://github.com/ltdrdata/ComfyUI-Impact-Subpack)
   (`UltralyticsDetectorProvider`), a `bbox/face_yolov8m.pt` model in
   `models/ultralytics/bbox/`, and a SAM model (e.g.
   `sam_vit_b_01ec64.pth`) in `models/sams/`.

   Identity is preserved via **IPAdapter FaceID** conditioning, not by
   starting the crop from real source pixels. The refinement's sampling
   model is patched with a face-recognition embedding (via `insightface`,
   `IPAdapterInsightFaceLoader` -> `IPAdapterUnifiedLoaderFaceID` ->
   `IPAdapterFaceID`) extracted from the original Daz beauty render, so the
   face pass can run at a denoise that actually matches the body's own
   stylization instead of needing to stay low to avoid drifting off the
   real photo. An earlier version sourced the crop's pixels from the real
   beauty render (`SetDefaultImageForSEGS`) and relied on low denoise
   (`0.15`) alone for identity; a live comparison confirmed that had a hard
   ceiling -- at low denoise there's no room for the ink cross-hatching the
   body gets at its own denoise, producing a visibly smoother/more
   photoreal face than the stylized body. FaceID conditioning decouples the
   two, so the default `face_detailer.denoise` is now `0.35` (matching the
   body pass) -- see the `faceid_weight` entry below for the resulting
   trade-off.

   **Known limitation:** the FaceID embedding encodes facial features only,
   not hair color. Since the crop still covers hair (needed to avoid the
   seam artifact above) but the pass no longer starts from real pixels,
   hair color is unconstrained during refinement and can drift from the
   source -- confirmed live on a grey-haired test character, whose hair
   rendered brown/blonde across the entire tested denoise/`faceid_weight`
   grid. This is a known, accepted trade-off of this mechanism, not a bug
   to be tuned away with these knobs.

### Single-shot variant (`render_shot.py`)

For a one-off render -- no combo matrix, no pose/expression preset library,
no JSON spec -- use `render_shot.py` instead of `main.py`. It assumes the
pose and expression are already set up by hand in the live scene and starts
directly at the render step:

```bash
python render_shot.py --name shot001 --output-dir C:/output/hero_sprites --dry-run

python render_shot.py --name shot001 --output-dir C:/output/hero_sprites \
    --checkpoint graphicNovelStyleXL.safetensors --lora-name gn_ink_v2.safetensors \
    --controlnet-model controlnet-union-sdxl-1.0.safetensors
```

All spec fields (resolution, engine, quality preset, camera labels, ComfyUI
checkpoint/LoRA/ControlNet models and weights, prompts) are plain CLI flags
instead -- run `python render_shot.py --help` for the full list. `--camera
front|back|both` (default `both`), `--stage all|render|stylize`, `--force`,
and `--dry-run` work the same as `main.py`. Outputs land in the same
`<output_dir>/renders/<name>/...` / `<output_dir>/stylized/<name>/...`
layout as the batch pipeline (with `<name>` in place of `<combo_id>`), so a
one-off shot and a batch run can safely share an `output_dir`, and both are
resumable the same way (skip if the output file already exists).

Both stages are resumable: before doing any unit of work (one combo x one
camera x one stage) they check whether the output file already exists and
skip if so. There is no separate manifest -- a plain rerun of the same
command is self-healing after a crash or partial failure.

## Prerequisites

- DAZ Studio running with the DazScriptServer plugin, and the sprite scene
  already open (outfit loaded, in A-pose). The pipeline does **not** load
  the scene file itself -- `dazpy`'s `Scene.load()` is merge-mode (adds to
  the current scene rather than replacing it), so calling it automatically
  risks duplicating the figure.
- The scene must contain two named cameras for front and back/OTS shots
  (see `cameras.front.label` / `cameras.back.label` in the spec).
- A running ComfyUI instance with your graphic-novel-style checkpoint, LoRA,
  and an SDXL union ControlNet model (e.g. `controlnet-union-sdxl-1.0.safetensors`)
  installed -- one model conditions all three passes (normal, depth,
  lineart) via ComfyUI's `SetUnionControlNetType` node.
- For the face identity pass (on by default): ComfyUI's Impact Pack plus the
  separately-installed [Impact-Subpack](https://github.com/ltdrdata/ComfyUI-Impact-Subpack)
  custom node (provides `UltralyticsDetectorProvider`), a
  `bbox/face_yolov8m.pt` model in `models/ultralytics/bbox/`, and a SAM
  model (e.g. `sam_vit_b_01ec64.pth`, loadable via Impact Pack's built-in
  `SAMLoader`) in `models/sams/`. Disable via
  `comfyui.face_detailer.enabled: false` in the spec, or
  `--no-face-detailer` for `render_shot.py`, if these aren't installed.
- Also for the face identity pass: [ComfyUI_IPAdapter_plus](https://github.com/cubiq/ComfyUI_IPAdapter_plus)
  with the `insightface` Python package installed into ComfyUI's own
  Python environment (`pip install insightface`; the default provider is
  `"CPU"` to avoid an additional CUDA-build `onnxruntime` dependency), plus
  the FaceID SDXL model files from
  [h94/IP-Adapter-FaceID](https://huggingface.co/h94/IP-Adapter-FaceID):
  `ip-adapter-faceid-plusv2_sdxl.bin` in `models/ipadapter/` and
  `ip-adapter-faceid-plusv2_sdxl_lora.safetensors` in `models/loras/`. Also
  requires a ViT-H CLIP vision model in `models/clip_vision/` whose
  filename IPAdapter_plus recognizes (matching `ViT-H-14`/`s32B-b79K`, or
  `ipadapter`+`sd15` -- e.g. `CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors`);
  if you already have a same-content file under a different name, a
  same-volume hardlink under the expected name works and needs no
  ComfyUI restart.
- `pip install -r requirements.txt` (plus `dazpy` itself).

## Authoring pose and expression presets

Presets are captured by hand, once, ahead of a batch run:

```bash
# Pose the character by hand in the live Daz Studio session, then:
python author_pose_preset.py --name standing_neutral --figure "Genesis 9" --library C:/presets/poses

# Dial in a facial expression by hand (body pose is untouched), then:
python author_expression_preset.py --name calm --figure "Genesis 9" --library C:/presets/expressions
```

Pose presets are plain `dazpy.DazPose` JSON (bones + morphs + props).
Expression presets are a parallel type that only stores morph values, so
applying an expression never disturbs the body pose applied just before it.

## Spec JSON schema

See `example_spec.json` for a full example. Key fields:

- `scene_path` -- documentation/logging only; the pipeline does not load it.
- `sprite.figure_label` -- the figure's label in the Daz scene (e.g.
  `"Genesis 9"`).
- `output_dir`, `pose_library_dir`, `expression_library_dir` -- relative
  paths are resolved against the spec file's directory.
- `cameras.front.label` / `cameras.back.label` -- must match camera node
  labels already present in the scene.
- `render` -- resolution, engine, Iray quality preset, and which canvases
  (AOVs) to render (`Normal`, `Depth`).
- `comfyui` -- checkpoint, LoRA, denoise, base seed, steps, cfg, prompts,
  `controlnet` (a single union `model` shared by all three passes plus
  per-pass `normal`/`depth`/`lineart` `weight`), and `face_detailer`
  (`enabled`, `denoise`, `guide_size`, `bbox_dilation`, `faceid_weight` --
  the identity-preservation pass; defaults to on with `denoise: 0.35`,
  `bbox_dilation: 100`, `faceid_weight: 1.0`). Identity comes from an
  IPAdapter FaceID embedding (see "Face identity pass" above), which
  decouples it from `denoise` -- so `denoise` can now match the body pass's
  own stylization level instead of staying low. `0.35` was picked after a
  live comparison grid (`denoise` in `0.25`/`0.35` x `faceid_weight` in
  `0.8`/`1.0`/`1.2`) run against two different characters: it produced
  ink-hatching texture on the face comparable to the body without visible
  identity loss at any tested `faceid_weight`. `faceid_weight` controls
  IPAdapter FaceID's own conditioning strength (0 = no identity
  conditioning, higher = stronger identity lock); `1.0` was kept as the
  default since `0.8`/`1.0`/`1.2` were visually indistinguishable in the
  tested grid. `bbox_dilation` needs to be generous: the face detector's
  bbox stops at the hairline, so a small value leaves a visible color seam
  where the refined region ends and the un-refined main pass's invented
  hair color begins -- note that a generous dilation also means hair color
  is subject to the identity pass's own drift; see the known limitation
  above.
- `combos` -- an explicit list of `{pose, expression, overrides?, id?}`
  entries (not a pose x expression cross product). `pose` and `expression`
  must resolve to files in the preset libraries. `overrides` is an optional
  `{"bones": {...}, "morphs": {...}, "props": {...}}` dict layered on top of
  the named presets (applied last, so overrides always win). `id` defaults
  to `f"{pose}__{expression}"` (sanitized) and disambiguates repeated
  pose+expression pairs with different overrides.

## Running

```bash
# Validate the spec and see the expanded work plan without touching either server:
python main.py --spec spec.json --dry-run

# Full run: render then stylize every combo x camera:
python main.py --spec spec.json

# Iterate on ComfyUI prompt/LoRA tuning without re-rendering Daz:
python main.py --spec spec.json --stage stylize --force

# Debug a single failed combo:
python main.py --spec spec.json --combo combat_ready__angry --camera front --force
```

Exit code is `0` if every combo x camera succeeded or was skipped, `1` if
any failed -- but the run never aborts partway through a large matrix
(failures are logged and the run continues), except a failed scene-baseline
restore between combos, which aborts the whole run since a broken baseline
could silently corrupt every subsequent combo.

## Output layout

```
<output_dir>/renders/<combo_id>/front.png
<output_dir>/renders/<combo_id>/front_canvases/front-Normal-Normal.exr
<output_dir>/renders/<combo_id>/front_canvases/front-Depth-Depth.exr
<output_dir>/renders/<combo_id>/front_canvases/front-Normal-converted.png   (derived)
<output_dir>/renders/<combo_id>/front_canvases/front-Depth-converted.png   (derived)
<output_dir>/renders/<combo_id>/front_lineart/front.png                   (derived)
<output_dir>/stylized/<combo_id>/front.png
```
(and the equivalent `back.*` files.)

## Testing

```bash
pytest tests/test_sprite_matrix_schema.py tests/test_sprite_matrix_paths.py \
       tests/test_sprite_matrix_presets.py tests/test_sprite_matrix_workflow_builder.py

# Requires a live Daz Studio + ComfyUI; skipped automatically otherwise:
pytest tests/test_sprite_matrix_integration.py
```
