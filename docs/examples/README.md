# dazpy Examples

These scripts demonstrate how to use the `dazpy` Python SDK to control DAZ
Studio remotely.  Each one requires the **DazScriptServer plugin** to be
running inside DAZ Studio and `dazpy` installed in your Python environment.

```bash
pip install dazpy
```

Examples are organised into folders by topic.  Run them from the
`docs/examples/` directory:

```
docs/examples/
  fundamentals/   — raw scripting, scene inspection, batching
  character/      — pose, state, IK, animation dumps
  animation/      — keyframe baking, clip mixing, interpolation
  geometry/       — mesh analysis, body measurements
  export/         — USD export
  rendering/      — turntable, multi-cam, batch renders, VN workflows
  ml_data/        — dataset generation for ML training
  ai_vision/      — MediaPipe expression transfer, webcam mirroring
  bvh/            — BVH motion-capture import (in development)
```

Start with `fundamentals/raw_script.py` if you are new to the SDK.

---

## Quick reference

| Script | Folder | What Python does | Renders? |
|---|---|---|---|
| [raw_script.py](#raw_scriptpy) | fundamentals | Executes arbitrary DazScript and prints the result | No |
| [scene_event_monitor.py](#scene_event_monitorpy) | fundamentals | Streams real-time scene-change events via SSE (monitor / log / wait-for) | No |
| [scene_introspection.py](#scene_introspectionpy) | fundamentals | Dumps the full scene hierarchy and transforms as JSON | No |
| [scene_inventory.py](#scene_inventorypy) | fundamentals | Structured per-node audit (type, materials, vertex count, etc.) | No |
| [batch_operations.py](#batch_operationspy) | fundamentals | Reads multiple properties in one HTTP call using `Batch` | No |
| [scene_save_copy.py](#scene_save_copypy) | fundamentals | Saves a copy of the current scene to a new path without changing its filename or dirty state | No |
| [character_state.py](#character_statepy) | character | Saves and restores morphs, expression controls, and bone rotations | No |
| [pose_transfer.py](#pose_transferpy) | character | Copies a pose from one figure to another in a single undo step | No |
| [animation_frame_dump.py](#animation_frame_dumppy) | character | Exports bone rotations and morph values for every animation frame | No |
| [ik_bone_to_target.py](#ik_bone_to_targetpy) | character | Moves a bone toward a named target node using IK | No |
| [keyframe_baking.py](#keyframe_bakingpy) | animation | Bakes constraint-driven or IK-driven animation to explicit keyframes | No |
| [animation_mixing.py](#animation_mixingpy) | animation | Clips, crossfades, concatenates, and applies animation clips offline | No |
| [pose_interpolation.py](#pose_interpolationpy) | animation | Interpolates between two saved states with easing curves and renders each step | Yes |
| [geometry_analysis.py](#geometry_analysispy) | geometry | Inspects mesh metadata, bounding boxes, face groups, and exports triangulated geometry | No |
| [body_measurements.py](#body_measurementspy) | geometry | Computes height and bust / waist / hip circumferences from horizontal mesh slices | No |
| [scene_to_usd.py](#scene_to_usdpy) | export | Exports the live scene to a Pixar USD file (meshes, UVs, cameras, lights, hair) | No |
| [capture_viewport.py](#capture_viewportpy) | rendering | Captures the OpenGL viewport as a screenshot or transparent sprite PNG | No |
| [comfyui_enhance/main.py](#comfyui_enhancemainpy) | rendering | Captures a viewport snapshot and enhances it via a ComfyUI img2img workflow | No |
| [sprite_matrix/main.py](#sprite_matrixmainpy) | rendering | Batch-renders a pose x expression matrix (front + back camera) for one sprite and stylizes each via a ComfyUI multi-ControlNet graphic-novel workflow | Yes |
| [turntable.py](#turntablepy) | rendering | Renders a 360° turntable by stepping Y rotation across N frames | Yes |
| [multi_camera_render.py](#multi_camera_renderpy) | rendering | Renders from every camera in the scene to separate files | Yes |
| [material_color_variations.py](#material_color_variationspy) | rendering | Renders the same scene with a list of diffuse colour swatches | Yes |
| [batch_render_morph_variations.py](#batch_render_morph_variationspy) | rendering | Renders a matrix of morph value combinations | Yes |
| [vn_render_workflow.py](#vn_render_workflowpy) | rendering | Four VN pipeline patterns: single render, batch variants, interleaved scene setup, multi-figure | Yes |
| [dataset_generator.py](#dataset_generatorpy) | ml_data | Generates a randomised render dataset with JSON sidecar for LoRA training | Yes |
| [expression_transfer.py](#expression_transferpy) | ai_vision | Extracts a facial expression from a photo using MediaPipe and applies it to a Genesis 9 figure | No |
| [webcam_expression_mirror.py](#webcam_expression_mirrorpy) | ai_vision | Mirrors your live webcam expression onto a Genesis 9 figure in real time | No |

BVH / motion-capture examples (`bvh/bvh_import.py`, `bvh/bvh_discover.py`,
`bvh/bvh_bone_maps.py`) are under active development and not yet stable.

---

## Fundamentals

### scene_event_monitor.py

Connects to the `GET /scene/events` SSE stream and reacts to live DAZ Studio
activity — node additions, selection changes, time scrubs, scene loads, renders
starting/finishing — without polling or modifying the scene.

Three subcommands cover the most common patterns:

**monitor** — pretty-print events to the terminal as they arrive.  Each line
shows the local time, event type (colour-coded by category), and a short
payload summary.

```bash
python fundamentals/scene_event_monitor.py monitor
python fundamentals/scene_event_monitor.py monitor --filter node,selection
python fundamentals/scene_event_monitor.py monitor --filter render --quiet
```

**log** — append every event as a JSON object to a JSONL file.  Useful for
capturing a work session and replaying or analysing it offline.

```bash
python fundamentals/scene_event_monitor.py log --out session.jsonl
python fundamentals/scene_event_monitor.py log --out renders.jsonl --filter render
```

**wait-for** — block until one matching event arrives, print its data, and
exit 0.  Exits 1 on timeout.  Designed for shell scripts that need to
synchronise with DAZ Studio — for example, waiting for `render.finished`
before post-processing the output file.

```bash
python fundamentals/scene_event_monitor.py wait-for --type render.finished
python fundamentals/scene_event_monitor.py wait-for --type scene.loaded --timeout 60
```

| Argument | Subcommand | Default | Description |
|---|---|---|---|
| `--filter CATEGORIES` | monitor, log | all | Comma-separated category subset: `node`, `skeleton`, `light`, `camera`, `selection`, `scene`, `time`, `render` |
| `--quiet` | monitor | off | Print only event type names, not full formatted lines |
| `--out FILE` | log | *(required)* | Output JSONL file (appended, not overwritten) |
| `--type EVENT_TYPE` | wait-for | *(required)* | Exact event type to wait for, e.g. `render.finished`, `node.added` |
| `--timeout SECS` | wait-for | `300` | Give up after this many seconds |

All subcommands share `--host` (default `127.0.0.1`) and `--port` (default `18811`).

The API token is read automatically from `~/.daz3d/dazscriptserver_token.txt`
if authentication is enabled on the server.

---

### raw_script.py

Drop down to raw DazScript when the typed SDK doesn't expose what you need.
Executes an IIFE against the primary scene selection and pretty-prints the
JSON result.

```bash
python fundamentals/raw_script.py
```

No arguments.  Edit the script body inline to run your own DazScript.

---

### scene_introspection.py

Read-only dump of the entire scene hierarchy and world-space transforms.
Output is JSON and can be piped to `jq` or redirected to a file.

```bash
python fundamentals/scene_introspection.py
python fundamentals/scene_introspection.py | jq '.tree[0]'
```

No arguments.

---

### scene_inventory.py

Collects a structured report for every node in the scene — type, label,
world position, visibility, material names, vertex count, and (for figures)
bone and morph counts.  Everything is gathered in a single DazScript call.

Useful for pipeline QA, asset auditing, and debugging scene composition.

```bash
python fundamentals/scene_inventory.py
python fundamentals/scene_inventory.py --out inventory.json --pretty
```

| Argument | Default | Description |
|---|---|---|
| `--out FILE` | stdout | Write JSON to this file instead of stdout |
| `--pretty` | off | Pretty-print the JSON output |

---

### scene_save_copy.py

Saves a copy of the current scene to a new path — the Python equivalent of
DAZ Studio's "Save a Copy As…" menu option — without changing the scene's
internal filename or dirty flag.

For clean scenes the plugin performs a `QFile::copy()` with zero DAZ state
change; the copy is byte-identical to the original.  For scenes with unsaved
changes it serialises via `Scene.saveScene()` and immediately restores state.
The response `method` field (`"copy"`, `"serialize"`, or
`"serialize+restore"`) tells you which strategy was used.

```bash
python fundamentals/scene_save_copy.py --dest C:/backups/scene_v2.duf
python fundamentals/scene_save_copy.py --dest C:/backups/scene_v2.duf --compare
python fundamentals/scene_save_copy.py --dest C:/backups/scene_v2.duf --dry-run
```

| Argument | Default | Description |
|---|---|---|
| `--dest PATH` | *(required)* | Absolute destination path on the DAZ Studio host |
| `--compare` | off | After saving, print source/copy sizes and whether the files are byte-identical |
| `--dry-run` | off | Print the strategy that would be used without writing anything |
| `--host HOST` | `127.0.0.1` | Server host |
| `--port PORT` | `18811` | Server port |

**SDK features demonstrated:** `DazScene.save_copy()`, `DazScene.filename()`,
`DazScene.needs_save()`.

---

### batch_operations.py

Shows how `Batch` bundles multiple independent DazScript reads into a single
HTTP round-trip.  Reading label, bone count, and morph count for N figures
normally costs 3N calls; with `Batch` it costs 1.

Includes an optional `--compare` mode that runs the same reads the naive way
and prints the speedup ratio.

```bash
python fundamentals/batch_operations.py
python fundamentals/batch_operations.py --compare
```

| Argument | Default | Description |
|---|---|---|
| `--compare` | off | Also run the per-call version and print the call-count comparison |

**SDK features demonstrated:** `Batch`, `Batch.add()`, `BatchFuture.value`,
context-manager usage, `DazScene.skeletons()`.

---

## Character

### character_state.py

Saves a character's complete state — shape morphs, expression / FACS
controls, and bone rotations — to a JSON file.  Restores it on demand.
Only non-default values are stored so the file stays compact.

State files are the input format for `pose_interpolation.py`.

```bash
python character/character_state.py save    --figure "Genesis 9" --out state.json
python character/character_state.py restore --figure "Genesis 9" --file state.json
```

**save subcommand**

| Argument | Default | Description |
|---|---|---|
| `--figure LABEL` | `Genesis 9` | Figure label as shown in the Scene panel |
| `--out FILE` | `state.json` | Output JSON file |

**restore subcommand**

| Argument | Default | Description |
|---|---|---|
| `--figure LABEL` | *(from file)* | Override the figure label stored in the file |
| `--file FILE` | *(required)* | State JSON file to restore |

---

### pose_transfer.py

Reads every bone's local Euler rotation from a source figure in one pass,
then applies matching rotations to a destination figure inside a single undo
step (Ctrl+Z in DAZ Studio undoes the entire transfer).

Edit the `src` and `dst` labels at the top of the script before running.

```bash
python character/pose_transfer.py
```

No command-line arguments.

---

### animation_frame_dump.py

Scrubs through the timeline entirely inside DazScript — `Scene.setFrame()`
advances the playhead server-side, so the entire animation is captured in a
single HTTP call with no per-frame round-trips.

Output JSON contains a bone-name index and parallel rotation arrays to keep
the per-frame payload compact.

```bash
python character/animation_frame_dump.py --figure "Genesis 9" --out anim.json
python character/animation_frame_dump.py --figure "Genesis 9" --out anim.json --morphs
```

| Argument | Default | Description |
|---|---|---|
| `--figure LABEL` | `Genesis 9` | Figure label |
| `--out FILE` | `anim.json` | Output JSON file |
| `--morphs` | off | Also capture non-zero morph values per frame |

---

### ik_bone_to_target.py

Moves a specified bone on one figure toward a named target node using a
simple iterative IK approach — useful for quick posing, reach tests, and
interaction scripting.  Optionally restores the original pose afterward.

```bash
python character/ik_bone_to_target.py --source MadisonG9 --bone r_hand --target HandTarget
python character/ik_bone_to_target.py --source BobG8 --bone lFoot --target AliceG8 --restore
python character/ik_bone_to_target.py --source MadisonG9 --bone r_hand --target HandTarget --dry-run
```

| Argument | Default | Description |
|---|---|---|
| `--source LABEL` | *(required)* | Figure whose bone should move |
| `--bone NAME` | *(required)* | Effector bone to move toward the target |
| `--target LABEL` | *(required)* | Target scene node (any node — figure, prop, null) |
| `--restore` | off | Restore the original bone rotation after printing the result |
| `--dry-run` | off | Print what would happen without moving anything |

---

## Geometry

### geometry_analysis.py

Retrieves a figure's mesh metadata, computes axis-aligned bounding boxes for
both the rest and posed mesh, lists face and material groups with their face
counts, and demonstrates Python-side utilities such as quad-to-triangle
conversion and `Vec3`-wrapped vertex access.

All metadata is fetched in a single HTTP call.  Bounding boxes are computed
server-side (no vertex transfer needed).  `triangulate()` and `as_vec3()` are
pure Python — zero additional HTTP calls.

```bash
python geometry/geometry_analysis.py --figure "Genesis 9"
python geometry/geometry_analysis.py --figure "Genesis 9" --groups
python geometry/geometry_analysis.py --figure "Genesis 9" --triangulate --out tris.json
```

| Argument | Default | Description |
|---|---|---|
| `--figure LABEL` | `Genesis 9` | Figure label |
| `--groups` | off | Print face group and material group details with face counts |
| `--triangulate` | off | Fetch all faces and export an all-triangle mesh |
| `--out FILE` | `triangles.json` | Output path when `--triangulate` is used |

**SDK features demonstrated:** `DazGeometry.mesh_info()`,
`DazGeometry.bounding_box()`, `DazGeometry.bounding_box_posed()`,
`DazGeometry.face_group_faces()`, `DazGeometry.material_group_faces()`,
`DazGeometry.face_vertex_indices_all()`, `DazGeometry.vertex_positions_all()`,
`DazGeometry.triangulate()`, `DazGeometry.as_vec3()`,
`BoundingBox.center`, `BoundingBox.size`, `BoundingBox.volume`,
`BoundingBox.contains()`, `Vec3.distance()`.

---

### body_measurements.py

Computes practical body measurements for a selected figure by pulling the
posed mesh into Python, slicing it with horizontal planes, and measuring the
torso contour at each slice.  The example targets Genesis 8, Genesis 8.1,
and Genesis 9 figures, but the same approach works for other figures too.
Each reported measurement includes both centimeters and inches.

**Torso loop selection** — at heights where the arms are also present (such as
the bust and underbust), a horizontal plane intersects both the torso and the
arms, producing multiple disconnected loops.  The script scores each loop by
centroid distance from the body centerline (`|cx| * 2 + |cz|`) and picks the
lowest-scoring (most-centered) loop, reliably selecting the torso contour even
in an A-pose.  This replaces the naive approach of taking the largest loop,
which could pick up an arm cross-section and produce grossly inflated
measurements.

**Robust outlier rejection** — when calibration data is unavailable for a
figure (for example, a figure whose scene label contains no gender keyword),
the script falls back to a heuristic that selects the slice with the largest
perimeter within the search window.  Before selecting, it discards slices whose
perimeter is more than 1.35× the median across the window, preventing an
arm-inflated slice from being chosen as the bust peak.

For bust anchoring the script prefers left/right pectoral bones when present,
then falls back to the spine/chest chain.

**Calibration** — the script loads a table from
`body_measurements.calibration.json`, with entries for Genesis 9 Female/Male,
Genesis 8 Female/Male, and Genesis 8.1 Female/Male seeded from Measure Metrics
reference values.  You can edit that JSON file to tune targets without touching
the measurement code.  The script selects a calibration row by matching the
scene label (e.g. `"Genesis 9 Female"`).  For figures whose label does not
contain a gender keyword (e.g. a character named `"MadisonG9"`), the heuristic
fallback is used; pass `--figure-type G9F` (or `G9M`, `G8M`, `G8.1F`, etc.)
to force a specific calibration entry.

**Bra and clothing estimates** — when `--clothing` is passed on a female
figure, the script prints heuristic bra and dress size estimates in US, UK,
and EU sizing.  Bra band is computed using the standard US industry method:
round the underbust measurement to the nearest inch, then add 4 if even or
5 if odd — this always yields an even band number.  Cup is determined by
rounding the difference between bust and band to the nearest inch
(1″=A, 2″=B, 3″=C, 4″=D, 5″=DD, 6″=DDD/F, …).  Add `--pretty` for the
summary in compact table form, including a bra sanity-check table.

Best results come from a neutral A-pose or T-pose with the figure standing
upright in the scene.  The example uses bone heights as anchors when they are
available and falls back to simple height ratios otherwise.

**Dependency**
```bash
pip install trimesh
```

```bash
python geometry/body_measurements.py --figure "Genesis 9 Female"
python geometry/body_measurements.py --figure "MadisonG9" --figure-type G9F
python geometry/body_measurements.py --figure "Genesis 8" --out measurements.json
python geometry/body_measurements.py --figure "Genesis 8.1" --sample-step 0.25
python geometry/body_measurements.py --figure "Genesis 9 Female" --clothing --pretty
```

| Argument | Default | Description |
|---|---|---|
| `--figure LABEL` | `Genesis 9` | Figure label as shown in the Scene panel |
| `--figure-type TYPE` | auto-detect | Force calibration entry: `G9F`, `G9M`, `G8F`, `G8M`, `G8.1F`, `G8.1M` |
| `--sample-step CM` | `0.5` | Slice spacing when searching for local min/max circumferences |
| `--search-window CM` | `5.0` | Half-width of the bust / underbust / low-hip search window |
| `--torso-only` | off | Narrow the bust search band (centroid-based torso loop selection is always active) |
| `--clothing` | off | Print bra and dress size estimates |
| `--pretty` | off | Render summary as compact tables |
| `--out FILE` | `measurements.json` | Output JSON file for the computed measurements |

---

## Export

### scene_to_usd.py

Interrogates the live DAZ Studio scene through the HTTP API and writes a
Pixar USD file — without touching the DAZ Studio UI, loading extra plugins,
or modifying the scene.

Exports posed mesh vertices (skinning + morphs already applied), polygon
topology, the primary UV set, UsdPreviewSurface materials, strand-based hair
as `UsdGeom.BasisCurves`, cameras, and lights.  With `--morphs` the script
additionally exports active shape morphs as `UsdSkel` blend shapes.

**Dependencies** (in addition to `dazpy`):
```bash
pip install usd-core
```

```bash
python export/scene_to_usd.py --out scene.usda
python export/scene_to_usd.py --out scene.usda --morphs
python export/scene_to_usd.py --out scene.usdc --figure "Genesis 9"
```

| Argument | Default | Description |
|---|---|---|
| `--out FILE` | `scene.usda` | Output USD file (`.usda` = ASCII, `.usdc` = binary) |
| `--morphs` | off | Export active shape morphs as UsdSkel blend shapes |
| `--figure LABEL` | all figures | Export only the named figure |

**SDK features demonstrated:** `DazGeometry.bounding_box_posed()`,
`DazGeometry.face_vertex_indices_all()`, `DazGeometry.vertex_positions_all()`,
`DazGeometry.uv_positions_all()`, `DazScene.skeletons()`.

---

## Rendering

### capture_viewport.py

Captures the active DAZ Studio 3D viewport to a file without triggering an
iRay render.  Three modes cover the common use cases:

- **raw** — grab the viewport exactly as it appears on screen (overlays, gizmos, and all)
- **clean** — temporarily hide axes, floor grid, pose tool, thirds guide, toolbar, and
  environment/tonemapper nodes, deselect all, capture, then restore everything
- **sprite** — clean capture + AI background removal via `rembg`, producing a
  transparent PNG ready to use as a game or UI sprite

Background removal uses the `u2net` model with alpha matting enabled by default
for clean edges around hair and limb gaps.  An optional `--backdrop R,G,B`
override sets the viewport background colour during capture; leave it unset to
use the current scene background.

**Dependency (sprite mode only):**
```bash
pip install rembg
```

```bash
# Clean screenshot
python rendering/capture_viewport.py --output snap.png

# Transparent sprite
python rendering/capture_viewport.py --mode sprite --output sprite.png

# Sprite with custom backdrop colour
python rendering/capture_viewport.py --mode sprite --backdrop 0,0,255 --output sprite.png

# Faster sprite, lower edge quality
python rendering/capture_viewport.py --mode sprite --no-alpha-matting --output sprite.png

# Raw capture — no overlay hiding
python rendering/capture_viewport.py --mode raw --output raw.png

# Preview what would happen
python rendering/capture_viewport.py --mode sprite --output sprite.png --dry-run
```

| Argument | Default | Description |
|---|---|---|
| `--mode {raw,clean,sprite}` | `clean` | Capture mode |
| `--output PATH` | *(required)* | Output file path (`.png` recommended) |
| `--backdrop R,G,B` | *(unchanged)* | Override viewport background colour during capture |
| `--no-alpha-matting` | off | Sprite mode: disable alpha matting (faster, lower edge quality) |
| `--daz-url URL` | `http://127.0.0.1:18811` | DAZ Studio script server URL |
| `--dry-run` | off | Print the plan without executing |

**SDK features demonstrated:** `DazViewport.capture()`, `DazViewport.capture_sprite()`,
`DazViewport.is_available()`, `DazViewport.get_size()`.

---

### comfyui_enhance/main.py

End-to-end pipeline that captures the active DAZ Studio viewport and submits
the result to a local [ComfyUI](https://github.com/comfyanonymous/ComfyUI)
instance for img2img enhancement via a photorealistic diffusion model.

**Prerequisites:**
- DAZ Studio running with the DazScriptServer plugin
- ComfyUI running locally at `http://127.0.0.1:8188`
- A compatible checkpoint installed in ComfyUI (e.g. `juggernautXL_juggXIByRundiffusion.safetensors`)

**Dependencies:**
```bash
pip install requests watchdog Pillow
```

Edit `comfyui_enhance/config.py` to set your checkpoint name and other defaults
before running.

```bash
cd docs/examples/rendering/comfyui_enhance

# Full pipeline: capture viewport → submit to ComfyUI → save result
python main.py --output C:/tmp/enhanced.png --checkpoint juggernautXL_juggXIByRundiffusion.safetensors

# Skip capture, use an existing snapshot
python main.py --no-watch --snapshot-path C:/tmp/snap.png --output C:/tmp/enhanced.png

# Adjust denoise strength (lower = closer to original)
python main.py --no-watch --snapshot-path C:/tmp/snap.png --denoise 0.25 --output C:/tmp/enhanced.png

# Preview the plan without executing
python main.py --dry-run --output C:/tmp/enhanced.png
```

| Argument | Default | Description |
|---|---|---|
| `--output PATH` | *(required)* | Output path for the enhanced image |
| `--checkpoint NAME` | *(from config.py)* | ComfyUI checkpoint filename override |
| `--denoise FLOAT` | `0.45` | Denoise strength (0.0 = no change, 1.0 = full generation) |
| `--no-watch` | off | Skip file watcher; use `--snapshot-path` directly |
| `--snapshot-path PATH` | — | Existing snapshot to submit (requires `--no-watch`) |
| `--dry-run` | off | Print plan without executing |

**SDK features demonstrated:** `DazViewport.capture()`, `DazClient`.

---

### sprite_matrix/main.py

Production pipeline for one sprite: given a scene with the sprite already
loaded (a specific outfit, A-pose) and a JSON spec describing a matrix of
pose x expression combinations, renders front and over-the-shoulder (back)
camera angles for every combo -- beauty image plus Normal/Depth Iray Canvas
passes -- then stylizes each render into a "graphic-novel naturalism" look
via a ComfyUI multi-ControlNet (normal, depth, lineart) + LoRA img2img
workflow. Both stages are resumable (skip-by-file-existence), so a plain
rerun after a crash or partial failure is self-healing.

**Prerequisites:**
- DAZ Studio running with the DazScriptServer plugin, sprite scene already
  open with two named cameras (front + back/OTS)
- ComfyUI running locally at `http://127.0.0.1:8188` with your graphic-novel
  checkpoint, LoRA, and normal/depth/lineart ControlNet models installed
- Pose and expression presets pre-authored via `author_pose_preset.py` /
  `author_expression_preset.py`

**Dependencies:**
```bash
pip install -r sprite_matrix/requirements.txt
```

```bash
cd docs/examples/rendering/sprite_matrix

# Author presets by hand, once, ahead of a batch run
python author_pose_preset.py --name standing_neutral --figure "Genesis 9" --library C:/presets/poses
python author_expression_preset.py --name calm --figure "Genesis 9" --library C:/presets/expressions

# Validate the spec and preview the work plan without touching either server
python main.py --spec spec.json --dry-run

# Full run: render then stylize every combo x camera
python main.py --spec spec.json

# Iterate on ComfyUI prompt/LoRA tuning without re-rendering Daz
python main.py --spec spec.json --stage stylize --force
```

See [`sprite_matrix/README.md`](sprite_matrix/README.md) for the full JSON
spec schema and output layout.

**SDK features demonstrated:** `DazRenderSettings` (canvases/AOVs),
`DazPose`, `DazSceneState`, `DazScene.find_skeleton_by_label()`.

---

### turntable.py

Rotates a figure around its local Y axis in equal steps and renders each
frame to a numbered PNG.  Existing X and Z rotations are preserved so a
posed character stays posed throughout the spin.

Combine output frames into a video:
```bash
ffmpeg -framerate 24 -i frame_%03d.png turntable.mp4
```

```bash
python rendering/turntable.py
python rendering/turntable.py --figure "My Character" --steps 72 --out C:/turntable
```

| Argument | Default | Description |
|---|---|---|
| `--figure LABEL` | `Genesis 9` | Figure label |
| `--steps N` | `36` | Number of frames for a full 360° rotation |
| `--out DIR` | `y:/tmp/turntable` | Output directory |
| `--width PX` | `1920` | Render width in pixels |
| `--height PX` | `1080` | Render height in pixels |

---

### multi_camera_render.py

Iterates every camera in the scene (or a named subset) and renders from
each one to `<out>/<camera_label>.png`.  Useful for storyboarding and
covering multiple angles in a single run.

```bash
python rendering/multi_camera_render.py
python rendering/multi_camera_render.py --out C:/renders --width 1920 --height 1080
python rendering/multi_camera_render.py --cameras "Front" "Side" "Hero Shot"
```

| Argument | Default | Description |
|---|---|---|
| `--out DIR` | `y:/tmp/multicam` | Output directory |
| `--width PX` | `1920` | Render width |
| `--height PX` | `1080` | Render height |
| `--cameras LABEL …` | all cameras | Render only the named cameras |

---

### material_color_variations.py

Renders a node's material surface in multiple diffuse colours.  The
original colour is saved before the loop and restored afterward — including
if the run is interrupted.

```bash
python rendering/material_color_variations.py --node "Cube" --material "Default"
python rendering/material_color_variations.py \
    --node "Shirt" --material "Fabric" \
    --colors "#C0392B" "#2980B9" "#27AE60" \
    --out C:/swatches --width 1920 --height 1080
```

| Argument | Default | Description |
|---|---|---|
| `--node LABEL` | `Genesis 9` | Scene node whose material to modify |
| `--material NAME` | `Torso` | Material surface name |
| `--colors HEX …` | 8-colour palette | Hex colours to render (`#RRGGBB`) |
| `--out DIR` | `y:/tmp/color_variations` | Output directory |
| `--width PX` | `1920` | Render width |
| `--height PX` | `1080` | Render height |

---

### batch_render_morph_variations.py

Renders a small, hardcoded matrix of expression morph combinations.
Intended as a minimal starting template — edit the morph labels and value
pairs at the top of the file.

```bash
python rendering/batch_render_morph_variations.py
```

No command-line arguments.

---

### vn_render_workflow.py

Four patterns for VN (visual novel) render pipelines.  VN production
generates many renders of the same characters in different expressions,
costumes, or compositions.  Run `--pattern 0|A|B|C` to execute just one
pattern, or omit it to run all four in sequence.

```bash
python rendering/vn_render_workflow.py
python rendering/vn_render_workflow.py --pattern A
python rendering/vn_render_workflow.py --pattern B --figure "Hero" --out C:/vn/renders
python rendering/vn_render_workflow.py --pattern C --figure "Alice" --figure2 "Bob"
```

| Argument | Default | Description |
|---|---|---|
| `--pattern {0,A,B,C}` | all | Run only this pattern |
| `--out DIR` | `y:/tmp/vn` | Output directory |
| `--figure LABEL` | `Genesis 9` | Primary figure label |
| `--figure2 LABEL` | `Genesis 9.1` | Second figure (Pattern C only) |
| `--width PX` | `1920` | Render width |
| `--height PX` | `1080` | Render height |

#### Pattern 0 — Basic single render

The simplest case: render the scene as-is with no scene modifications.

```python
from dazpy import DazClient
from dazpy._render_api import render

client = DazClient()
result = render(client, r"C:\renders\frame.png", width=1920, height=1080)
print(result.output_path, result.file_size_bytes, result.duration_ms)
```

`render()` submits to `POST /render`, waits via the SSE progress stream
(`GET /render/:id/progress`), and falls back to long-poll if SSE is
unavailable.  The `RenderResult` dataclass carries `success`,
`output_path`, `file_size_bytes`, `duration_ms`, and `error`.

#### Pattern A — Batch morph variants

Use when all variants differ only in morph values.  A single
`POST /render/batch` submits the whole set; the server executes renders
sequentially in the async queue.

```python
from dazpy._render_api import FigureMorphs, RenderBase, RenderVariant, render_variants

variants = [
    RenderVariant(r"C:\vn\neutral.png",   figure="Genesis 9"),
    RenderVariant(r"C:\vn\smile.png",     figure="Genesis 9", morphs={"Smile Full Face": 1.0}),
    RenderVariant(r"C:\vn\sad.png",       figure="Genesis 9", morphs={"Mouth Frown": 0.8, "Brow Inner Up": 0.6}),
    RenderVariant(r"C:\vn\surprised.png", figure="Genesis 9", morphs={"Eyes Wide": 0.9, "Mouth Open": 0.5}),
]
base = RenderBase(width=1920, height=1080, engine="iray")

results = render_variants(
    client, variants, base,
    on_progress=lambda done, total: print(f"{done}/{total}"),
)
```

`render_variants()` returns a `list[RenderResult]` in the same order as
`variants`.  If one render fails its result has `success=False`; subsequent
variants are still attempted.

#### Pattern B — Interleaved scene setup

Use when variants differ in ways the render payload cannot express —
lighting intensity, prop visibility, backdrop colour, material properties,
environment settings, and so on.

```python
for out_path, light_intensity in variants:
    # Apply scene-level changes for this render.
    client.execute(f"""
        var fill = Scene.findNodeByLabel("Fill Light");
        var p = fill && fill.findPropertyByLabel("Intensity");
        if (p) p.setValue({light_intensity});
    """)

    # Render with morphs specified in the payload.
    result = render(client, out_path, figure="Genesis 9",
                    morphs={"Smile Full Face": 0.3},
                    width=1920, height=1080)
```

**Why this is safe — the sequential queue guarantee**

The render queue is sequential: render N+1 only starts after render N
completes.  When a render is executing on the main thread, any
`client.execute()` call you make from Python is queued and runs *after*
the current render finishes and *before* the next render starts.

```
[Python thread]                 [DAZ Studio main thread]
execute(setup for render N) --> apply setup N
render(out_N, ...)          --> (queued)  run render N → doRender()
execute(setup for N+1)      --> (blocked until render N completes)
                                apply setup N+1   ← runs here
render(out_N1, ...)         --> (queued)  run render N+1 → doRender()
```

Because `render()` blocks until completion by default, the loop body
always runs setup → render → next setup in the correct order.

**Transparent backgrounds**

The render API does not manipulate backdrop nodes.  Use `client.execute()`
to toggle environment visibility before each render:

```python
client.execute("""
    var env = Scene.findNodeByLabel("Environment");
    if (env) env.setVisible(false);
""")
result = render(client, out_path, ...)
client.execute("""
    var env = Scene.findNodeByLabel("Environment");
    if (env) env.setVisible(true);
""")
```

For iRay, set the backdrop mode to "Scene Only" (no environment sphere) via
the iRay render settings DazScript API to avoid per-render toggling.

#### Pattern C — Multi-figure scene

Use `FigureMorphs` to configure multiple characters in a single render
submission.  No extra scene changes are required.

```python
from dazpy._render_api import FigureMorphs, RenderBase, RenderVariant, render_variants

variants = [
    RenderVariant(
        r"C:\vn\both_neutral.png",
        figures=[
            FigureMorphs("Alice", morphs={}),
            FigureMorphs("Bob",   morphs={}),
        ],
    ),
    RenderVariant(
        r"C:\vn\alice_happy_bob_angry.png",
        figures=[
            FigureMorphs("Alice", morphs={"Smile Full Face": 1.0}),
            FigureMorphs("Bob",   morphs={"Anger": 0.8, "Brow Lower": 0.6}),
        ],
    ),
]
base = RenderBase(width=1920, height=1080, engine="iray")
results = render_variants(client, variants, base)
```

`FigureMorphs.name` must match the figure's label in the Scene panel.
Unknown morph labels are silently skipped by the server.

**SDK features demonstrated:** `render`, `render_variants`, `RenderVariant`,
`RenderBase`, `FigureMorphs`, `RenderResult`, `DazClient.execute`.

---

## ML / Data pipelines

### dataset_generator.py

Randomises a set of expression morphs on a Genesis 9 figure and renders
each variation to a numbered PNG.  A JSON sidecar is written alongside the
images so the dataset is fully reproducible.  Suitable as a starting point
for generating LoRA training data.

```bash
python ml_data/dataset_generator.py
python ml_data/dataset_generator.py --count 100 --out C:/dataset --size 512
```

| Argument | Default | Description |
|---|---|---|
| `--count N` | `10` | Number of randomised renders to produce |
| `--out DIR` | `y:/tmp/` | Output directory |
| `--size PX` | `512` | Render resolution (square) |

---

## Animation

### keyframe_baking.py

Reads the evaluated bone rotations and morph values of an animated figure
at the current frame, then bakes the full play range to explicit keyframes in
one HTTP call.  After baking, the animation no longer depends on IK rigs,
expression controllers, or other drivers — useful before FBX/BVH export or
after pushing a captured clip back to the timeline.

```bash
python animation/keyframe_baking.py --figure "Genesis 9"
python animation/keyframe_baking.py --figure "Genesis 9" --morphs
python animation/keyframe_baking.py --figure "Genesis 9" --start 10 --end 90 --morphs
python animation/keyframe_baking.py --figure "Genesis 9" --preview
```

| Argument | Default | Description |
|---|---|---|
| `--figure LABEL` | `Genesis 9` | Figure label |
| `--start N` | play range start | First frame to bake |
| `--end N` | play range end | Last frame to bake |
| `--morphs` | off | Also bake morph channels alongside bone rotations |
| `--preview` | off | Print current bone/morph state without writing any keyframes |

**SDK features demonstrated:** `DazSkeleton.bone_rotations()`,
`DazSkeleton.morph_values(nonzero_only=True)`,
`DazSkeleton.bake_bone_rotations()`, `DazSkeleton.bake_morphs()`,
`DazSkeleton.bake()`, `DazScene.play_range()`.

---

### animation_mixing.py

Treats captured animation files (from `animation_frame_dump.py`) as editable
clips.  All operations — clipping, crossfading, concatenation — run entirely
in Python with no HTTP calls.  The result can be pushed back to a live figure
in a single call when needed.

```bash
python animation/animation_mixing.py clip   --anim walk.json --start 10 --end 40 --out walk_loop.json
python animation/animation_mixing.py blend  --a walk.json --b run.json --t 0.5 --out trot.json
python animation/animation_mixing.py append --a intro.json --b main.json --out full.json
python animation/animation_mixing.py apply  --anim walk.json --frame 0 --figure "Genesis 9"
```

**clip** — extract a sub-range of frames (inclusive, by scene frame number)

| Argument | Default | Description |
|---|---|---|
| `--anim FILE` | *(required)* | Source animation JSON |
| `--start N` | *(required)* | First scene frame to keep |
| `--end N` | *(required)* | Last scene frame to keep |
| `--out FILE` | *(required)* | Output JSON path |

**blend** — crossfade between two clips frame-by-frame (`t=0` → A, `t=1` → B)

| Argument | Default | Description |
|---|---|---|
| `--a FILE` | *(required)* | Clip A (t=0) |
| `--b FILE` | *(required)* | Clip B (t=1) |
| `--t FLOAT` | `0.5` | Blend weight 0.0–1.0 |
| `--out FILE` | *(required)* | Output JSON path |

**append** — concatenate two clips end-to-end (B's frames renumbered to follow A)

| Argument | Default | Description |
|---|---|---|
| `--a FILE` | *(required)* | First clip |
| `--b FILE` | *(required)* | Second clip (appended after A) |
| `--out FILE` | *(required)* | Output JSON path |

**apply** — apply a single frame from a clip to a live figure (one HTTP call)

| Argument | Default | Description |
|---|---|---|
| `--anim FILE` | *(required)* | Animation JSON |
| `--frame N` | `0` | Python index into the clip (0 = first frame) |
| `--figure LABEL` | *(from file)* | Target figure label |

**SDK features demonstrated:** `DazAnimation.load()`, `DazAnimation.clip()`,
`DazAnimation.blend()`, `DazAnimation.append()`, `DazAnimation.as_pose()`,
`DazAnimation.apply()`, `len(anim)`, `anim[i]`, `DazPose.apply()`.

---

### pose_interpolation.py

Loads two state files produced by `character_state.py`, interpolates all
bone rotations, morph values, and FACS properties across N steps using a
configurable easing curve, and renders each frame.

Python owns all the animation math; DAZ Studio applies the result at each
step with no knowledge of the interpolation happening outside it.

Combine output frames into a video:
```bash
ffmpeg -framerate 24 -i frame_%03d.png interpolation.mp4
```

```bash
python animation/pose_interpolation.py --a neutral.json --b smile.json --steps 10
python animation/pose_interpolation.py --a neutral.json --b smile.json \
    --steps 30 --ease ease_in_out --out C:/interpolation \
    --width 1920 --height 1080
```

| Argument | Default | Description |
|---|---|---|
| `--a FILE` | *(required)* | Start state JSON (from `character_state.py save`) |
| `--b FILE` | *(required)* | End state JSON |
| `--steps N` | `10` | Number of frames including start and end |
| `--ease NAME` | `ease_in_out` | Easing curve: `linear`, `ease_in`, `ease_out`, `ease_in_out`, `ease_in_cubic`, `ease_out_cubic`, `ease_in_out_cubic`, `bounce_out` |
| `--out DIR` | `y:/tmp/interpolation` | Output directory |
| `--width PX` | `1920` | Render width |
| `--height PX` | `1080` | Render height |
| `--figure LABEL` | *(from state A)* | Override figure label |

---

## AI / Computer vision

### expression_transfer.py

Extracts a facial expression from a photo using **MediaPipe FaceLandmarker**,
computes Action Unit (AU) magnitudes from landmark geometry entirely in
Python, and applies the result to a Genesis 9 figure's FACS HD expression
controls in a single HTTP call.

Python does all the computer-vision work — image decoding, landmark
inference, AU geometry, and morph scaling.  DAZ Studio only receives the
final batch of property values.

**Dependencies** (in addition to `dazpy`):
```bash
pip install mediapipe opencv-python numpy
```

The MediaPipe face landmarker model (`face_landmarker.task`, ~1 MB) is
downloaded automatically to the `docs/examples/` directory on first run.

**FACS label calibration:** Property labels vary between FACS products.
The defaults target the Genesis 9 base FACS (`AU XX Description Left/Right`
convention).  If morphs don't apply, use `--list-properties` or `--debug`
to discover the correct labels for your installed product, then edit
`FACS_MAP` at the top of the script.

```bash
python ai_vision/expression_transfer.py photo.jpg
python ai_vision/expression_transfer.py photo.jpg --figure "Genesis 9" --scale 0.8
python ai_vision/expression_transfer.py --list-properties
python ai_vision/expression_transfer.py --list-properties --search blink
python ai_vision/expression_transfer.py photo.jpg --debug
```

| Argument | Default | Description |
|---|---|---|
| `image` | *(required unless `--list-properties`)* | Path to source image (JPEG, PNG, or any format OpenCV supports) |
| `--figure LABEL` | `Genesis 9` | Target figure label |
| `--scale FLOAT` | `1.0` | Global expression scale factor — reduce if morphs are over-driven |
| `--no-reset` | off | Blend onto the current expression instead of zeroing FACS first |
| `--list-properties` | off | List all numeric properties on the figure and exit |
| `--search TERM` | — | Filter `--list-properties` output by case-insensitive substring |
| `--debug` | off | Print which FACS labels matched/missed and suggest candidates |

---

### webcam_expression_mirror.py

Captures frames from your webcam, runs MediaPipe FaceLandmarker on each frame,
and streams the resulting FACS morph values to a Genesis 9 figure at up to
`--fps` updates per second.  The figure's expression updates live as your face
moves.

Pairs naturally with DAZ's **Face Transfer 2**: use that tool to build a 3D
version of yourself, then use this script to drive its expressions in real time.

Press **Q** in the preview window, or **Ctrl+C**, to stop.  FACS morphs are
zeroed on exit so the figure returns to a neutral expression.

**Dependencies** (in addition to `dazpy`):
```bash
pip install mediapipe opencv-python numpy
```

The MediaPipe face landmarker model (`face_landmarker.task`, ~1 MB) is
downloaded automatically to the `docs/examples/` directory on first run.

**FACS label calibration:** Uses the same `FACS_MAP` as `expression_transfer.py`.
Run `expression_transfer.py --list-properties` to discover labels for your
installed FACS product if morphs don't apply.

```bash
python ai_vision/webcam_expression_mirror.py
python ai_vision/webcam_expression_mirror.py --figure "Genesis 9" --scale 0.8
python ai_vision/webcam_expression_mirror.py --camera 1 --fps 15
python ai_vision/webcam_expression_mirror.py --smooth 0.7
python ai_vision/webcam_expression_mirror.py --no-preview
```

| Argument | Default | Description |
|---|---|---|
| `--figure LABEL` | `Genesis 9` | Target figure label |
| `--scale FLOAT` | `1.0` | Global expression scale factor |
| `--camera N` | `0` | OpenCV camera index (try `1`, `2`, … for external webcams) |
| `--fps N` | `10` | Max DAZ Studio updates per second |
| `--smooth FLOAT` | `0.5` | EMA smoothing: `0` = raw/responsive, `0.9` = very smooth |
| `--no-preview` | off | Run headless with no OpenCV window (Ctrl+C to stop) |
