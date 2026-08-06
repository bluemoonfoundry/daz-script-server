# Per-Region ControlNet Conditioning for the Face-Identity Pass

## Context

The sprite matrix pipeline (`docs/examples/rendering/sprite_matrix/`) recently
gained IPAdapter FaceID conditioning for its face-identity pass (see
`docs/superpowers/specs/2026-08-05-faceid-conditioning-design.md`), decoupling
identity preservation from denoise so the pass could run at a denoise
matching the main body pass (`0.35`) instead of a low value. That work closed
one gap but a live test against real renders (`abby_b`, `jason_a`) surfaced
another: even at matched denoise, the face still looks visibly flatter and
shinier than the heavily ink-hatched body, with an obvious seam at the
neck/collar boundary.

Root cause, confirmed by reading `workflow_controlnet.json` directly: node
`"64"` (`ToBasicPipe`, which feeds `SEGSDetailer`) wires its `positive`
conditioning straight from node `"4"` (`CLIPTextEncode`) -- the raw,
un-conditioned prompt. The main body pass's `ControlNetApply` chain (nodes
`"22"`->`"32"`->`"42"`, conditioned on the normal/depth/lineart maps) is never
in that path. The face-identity pass has **zero ControlNet guidance**, so
nothing forces it to draw the ink cross-hatching the body gets -- it's just
prompt + FaceID-conditioned diffusion, which naturally lands on smoother,
more painterly skin regardless of denoise or `faceid_weight` tuning. This is
a pre-existing gap from before the FaceID work (a comment in the code noted
the crop's coordinate space doesn't match the body-scale ControlNet images,
so ControlNet was skipped entirely for that pass) -- FaceID conditioning
didn't cause it, but also can't fix it, since it addresses identity, not
style.

## Decision

Use Impact Pack's `ImpactControlNetApplyAdvancedSEGS` node, which attaches
per-segment ControlNet conditioning directly onto a `SEGS` list -- internally
cropping/resizing a full-size `control_image` to match each segment's
`crop_region` (confirmed by reading the node's source,
`comfyui-impact-pack/modules/impact/segs_nodes.py`: it builds a
`ControlNetAdvancedWrapper` carrying `original_size`/`crop_region`, consumed
automatically by `SEGSDetailer.do_detail()` per-segment during sampling).
This is exactly the coordinate-space correspondence the original design
comment flagged as missing, solved by an existing node rather than custom
cropping code.

A live spike (three throwaway ComfyUI queues against `abby_b`'s front
render: baseline no-SEGS-ControlNet, weights matching the main pass's own
`0.6/0.5/0.4`, and `1.0/0.8/0.6`) confirmed this closes the gap: neck
hatching density and shadow definition visibly increase and better match
the sweater's linework as ControlNet strength increases, and `1.0/0.8/0.6`
clearly outperforms reusing the main pass's own weights directly -- the
cropped/upscaled face-region scale evidently wants stronger conditioning
than the full-body scale. Face skin itself remains comparatively smoother
than fabric even at the higher strength tested; this may be an inherent
property of skin having fewer natural edges for the lineart/depth/normal
maps to pick up on (vs. fabric folds), not necessarily a defect -- live
tuning in the implementation plan will establish how far this can
reasonably be pushed.

## Architecture

Insert a `ImpactControlNetApplyAdvancedSEGS` chain between `MaskToSEGS`
(node `"69"`) and `SEGSDetailer` (node `"65"`), reusing the main pass's
already-retagged `SetUnionControlNetType` outputs and source images:

```
"69" (MaskToSEGS, SEGS output)
  -> new "73" ImpactControlNetApplyAdvancedSEGS(
         segs=["69",0], control_net=["21",0] (normal-tagged),
         control_image=["20",0] (normal map), strength=<new knob>,
         start_percent=0.0, end_percent=1.0)
  -> new "74" ImpactControlNetApplyAdvancedSEGS(
         segs=["73",0], control_net=["31",0] (depth-tagged),
         control_image=["30",0] (depth map), strength=<new knob>,
         start_percent=0.0, end_percent=1.0)
  -> new "75" ImpactControlNetApplyAdvancedSEGS(
         segs=["74",0], control_net=["41",0] (lineart-tagged),
         control_image=["40",0] (lineart map), strength=<new knob>,
         start_percent=0.0, end_percent=1.0)
  -> "65" SEGSDetailer's segs input (replacing the current direct ["69",0] wiring)
```

`SEGSDetailer` itself is unchanged -- it already consumes per-segment
`control_net_wrapper` info automatically once present on the SEGS entries.
No other node in the existing face-identity chain (SAM refinement,
`IPAdapterFaceID`, `ToBasicPipe`) changes.

## Config surface

New fields on `ComfyUIStageConfig` (`config.py`) / `comfyui.face_detailer` in
the spec JSON / `render_shot.py` CLI flags, following the existing
`face_detailer_faceid_weight` pattern:

- `face_detailer_controlnet_normal_weight: float`
- `face_detailer_controlnet_depth_weight: float`
- `face_detailer_controlnet_lineart_weight: float`

Defaults pending live tuning in the implementation plan; the spike suggests
starting near `1.0`/`0.8`/`0.6`. `start_percent`/`end_percent` stay fixed at
`0.0`/`1.0` as JSON literals in `workflow_controlnet.json` -- no evidence yet
they need to be tunable, matching how the rest of this pipeline treats
non-tunable node parameters.

## Testing / rollout plan

1. Wire the new nodes into `workflow_controlnet.json` / `workflow_builder.py`,
   gated the same way as the rest of `face_detailer_*` (single
   `face_detailer_enabled` toggle covers the whole pass; the disabled-branch
   node-deletion tuple grows to include `"73"`/`"74"`/`"75"`).
2. Plumb the three new config knobs through `config.py`/`schema.py`/
   `stylize_stage.py`/`render_shot.py`/`example_spec.json`.
3. Update unit tests (`test_sprite_matrix_workflow_builder.py`,
   `test_sprite_matrix_schema.py`) for the new node wiring and config knobs.
4. Live-verify and tune defaults against the same two test characters
   (`abby_b`, `jason_a`) used for the FaceID tuning work -- a strength grid
   around the spike's promising `1.0/0.8/0.6` starting point, checking both
   the neck/collar seam and the face's own texture, plus a check that this
   doesn't reintroduce any previously-fixed artifact (hair-color seam,
   background box, blacker-than-black halo) since the face crop's rendering
   path is changing.
5. Update `sprite_matrix/README.md`'s "Face identity pass" section to
   describe the new ControlNet conditioning and its knobs, alongside the
   existing FaceID/hair-color-drift/no-face-detected documentation.

No new external dependencies -- `ImpactControlNetApplyAdvancedSEGS` is part
of the already-installed Impact Pack, confirmed live via ComfyUI's
`/object_info` endpoint.
