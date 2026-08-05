# FaceID Conditioning for the Sprite Matrix Face-Identity Pass

## Context

The sprite matrix pipeline (`docs/examples/rendering/sprite_matrix/`) stylizes
Daz Studio renders into a "graphic-novel naturalism" look via ComfyUI. A
second pass (`SEGSDetailer` on a SAM-refined head/hair silhouette) exists to
keep the face recognizable, since the main body pass has little resolution
or ControlNet conditioning signal to preserve a small face. That pass
currently works by sourcing its crop pixels from the *original* Daz beauty
render (via `SetDefaultImageForSEGS`) and running at a low denoise
(`face_detailer_denoise`, currently `0.15`) so the result stays close to the
real photo.

A live side-by-side experiment (four variants: denoise 0.15/0.20, with and
without a reinforced hatching prompt) showed this approach has a hard
ceiling: at low denoise the model has no room to add the heavy ink
cross-hatching the body gets at its own denoise (0.35), regardless of
prompt wording. The face ends up visibly smoother/more photoreal than the
heavily-stylized body — a "pasted-on" look. Raising denoise enough to close
that gap (~0.30+) is roughly where identity drift was already confirmed to
become visible in an earlier comparison, so low-denoise-for-identity and
enough-denoise-for-style-match are mutually exclusive with the current
mechanism.

**Goal**: decouple identity preservation from denoise, so the face pass can
run at a denoise that actually matches the body's stylization level while a
separate mechanism (an identity embedding) keeps the result recognizable as
the source character.

## Decisions

1. **IPAdapter FaceID over IPAdapter Plus Face.** The user chose to go
   straight to true FaceID (dedicated face-recognition embeddings via
   `insightface`) over the already-installed, lower-friction "Plus Face"
   variant (CLIP-vision similarity, weaker identity lock). This means taking
   on a new Python dependency (`insightface`) whose Windows wheel
   reliability is unverified in this environment — consistent with two
   earlier dependency chases this session (Impact-Subpack for
   `UltralyticsDetectorProvider`, though `mediapipe` was a dead end for a
   different feature). If `insightface` turns out to be unworkable on this
   Windows/Python 3.13 ComfyUI install, Plus Face is the documented fallback
   -- swap `IPAdapterUnifiedLoaderFaceID`/`IPAdapterFaceID` for the plain
   `IPAdapterUnifiedLoader`/`IPAdapterAdvanced` nodes against the
   already-installed `ip-adapter-plus-face_sdxl_vit-h.bin`.
2. **Replace, not augment.** Remove `SetDefaultImageForSEGS` (no more
   swapping the crop's pixel source to the real beauty render) and stop
   relying on low denoise for identity. Raise `face_detailer_denoise` toward
   the body's stylization level; identity comes from the FaceID embedding
   instead.

## Architecture

The existing spatial pipeline is unchanged -- it decides *where* to refine,
not *how*:

```
UltralyticsDetectorProvider (bbox/face_yolov8m.pt)
  -> BboxDetectorSEGS (detect on stylized output, node "7")
  -> SAMDetectorCombined (refine rectangle into a true head/hair silhouette)
  -> MaskToSEGS (bbox_fill=false, precise contour)
```

New conditioning chain, inserted before `ToBasicPipe`:

```
IPAdapterInsightFaceLoader (provider="CPU" -- avoids taking on a CUDA-build
                             onnxruntime dependency on top of insightface
                             itself; revisit if extraction proves too slow)
  -> INSIGHTFACE

IPAdapterUnifiedLoaderFaceID (model=<checkpoint+LoRA model>, preset="FACEID")
  -> patched MODEL, IPADAPTER
     (preset is a second live-tunable choice alongside denoise -- the
     "PORTRAIT (style transfer)" presets exist specifically for letting more
     style through while retaining identity, so may turn out to be a better
     starting point than plain "FACEID"; try both during step 4 below)

IPAdapterFaceID (
    model=<patched MODEL from unified loader>,
    ipadapter=<IPADAPTER from unified loader>,
    insightface=<INSIGHTFACE from insightface loader>,
    image=<ORIGINAL Daz beauty render, node "2" -- the identity reference photo>,
    weight=<new config knob, face_detailer_faceid_weight>,
  )
  -> FaceID-conditioned MODEL

ToBasicPipe(model=<FaceID-conditioned MODEL>, clip=<unchanged>, vae=<unchanged>,
            positive=<unchanged, node "4">, negative=<unchanged, node "5">)
  -> basic_pipe feeds SEGSDetailer exactly as today
```

`SetDefaultImageForSEGS` (node `"63"`) is deleted; `MaskToSEGS`'s output feeds
directly into `SEGSDetailer` as `segs`. `SEGSDetailer` itself, `SEGSPaste`,
and the halo-avoidance tuning (SAM `dilation=10`, paste `feather=2`) are
unchanged -- those fixed a spatial-blending problem orthogonal to identity
conditioning.

`insightface`'s own face-recognition model does not appear to need a
manually-placed file (no `model_name` input on `IPAdapterInsightFaceLoader`)
-- it's expected to auto-download on first use into insightface's own cache.
This is unverified until tried; if it fails to auto-download (e.g. no
outbound network access from that environment), the model will need to be
sourced and placed manually.

## Config surface

New fields on `ComfyUIStageConfig` (`config.py`) / `comfyui.face_detailer` in
the spec JSON / `render_shot.py` CLI flags, following the existing pattern:

- `face_detailer_faceid_weight: float` (new) -- `IPAdapterFaceID`'s `weight`
  parameter, default `1.0` pending live tuning.
- `face_detailer_denoise: float` (existing field, new default) -- re-tuned
  live once FaceID conditioning is working, expected to land somewhere
  toward the body's `0.35` rather than the current `0.15`.

Everything else in the new chain (insightface provider, FaceID preset,
`weight_faceidv2`, `weight_type`, `combine_embeds`, `start_at`/`end_at`,
`embeds_scaling`) stays as fixed defaults in `workflow_controlnet.json`,
matching how the rest of this pipeline handles non-tunable node parameters
(e.g. SAM's `threshold`, `bbox_expansion`).

## Testing / rollout plan

This is infrastructure-dependent in a way unit tests can't cover (needs a
live ComfyUI with `insightface` actually working). Plan:

1. Install `insightface` into ComfyUI's embedded Python; verify `import
   insightface` succeeds before touching the workflow graph.
2. Download the FaceID SDXL ipadapter model + companion LoRA from
   `h94/IP-Adapter-FaceID` into `models/ipadapter/`.
3. Wire the new nodes into `workflow_controlnet.json` /
   `workflow_builder.py`, gated the same way the rest of `face_detailer_*`
   is (single `face_detailer_enabled` toggle covers the whole pass, no
   separate FaceID on/off).
4. Live-verify against the same `abby_b` character and the earlier male
   test character: run the same four-variant-style denoise comparison
   (now with FaceID active) to find a new `face_detailer_denoise` default
   that closes the style gap without losing identity, since FaceID
   conditioning strength interacts with denoise rather than replacing the
   need to tune it.
5. Add/update unit tests for the new node wiring in
   `test_sprite_matrix_workflow_builder.py` (node presence, correct wiring,
   config knob plumbing) once the live-verified defaults are known.
6. Update `sprite_matrix/README.md` with the new dependency
   (`insightface` + FaceID model files) alongside the existing Impact
   Pack/Impact-Subpack/SAM prerequisites.

If `insightface` proves unworkable in this environment, fall back to
IPAdapter Plus Face per decision 1 above, and revise this spec's
Architecture section accordingly before continuing.
