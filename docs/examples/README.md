# dazpy Examples

These scripts demonstrate how to use the `dazpy` Python SDK to control DAZ
Studio remotely.  Each one requires the **DazScriptServer plugin** to be
running inside DAZ Studio and `dazpy` installed in your Python environment.

```bash
pip install dazpy
```

The examples are roughly ordered from simple to complex.  Start with
`raw_script.py` if you are new to the SDK.

---

## Quick reference

| Script | Category | What Python does | Renders? |
|---|---|---|---|
| [raw_script.py](#raw_scriptpy) | Fundamentals | Executes arbitrary DazScript and prints the result | No |
| [scene_introspection.py](#scene_introspectionpy) | Fundamentals | Dumps the full scene hierarchy and transforms as JSON | No |
| [scene_inventory.py](#scene_inventorypy) | Fundamentals | Structured per-node audit (type, materials, vertex count, etc.) | No |
| [batch_operations.py](#batch_operationspy) | Fundamentals | Reads multiple properties in one HTTP call using `Batch` | No |
| [character_state.py](#character_statepy) | Character | Saves and restores morphs, expression controls, and bone rotations | No |
| [pose_transfer.py](#pose_transferpy) | Character | Copies a pose from one figure to another in a single undo step | No |
| [animation_frame_dump.py](#animation_frame_dumppy) | Character | Exports bone rotations and morph values for every animation frame | No |
| [keyframe_baking.py](#keyframe_bakingpy) | Animation | Bakes constraint-driven or IK-driven animation to explicit keyframes | No |
| [animation_mixing.py](#animation_mixingpy) | Animation | Clips, crossfades, concatenates, and applies animation clips offline | No |
| [pose_interpolation.py](#pose_interpolationpy) | Animation | Interpolates between two saved states with easing curves and renders each step | Yes |
| [geometry_analysis.py](#geometry_analysispy) | Geometry | Inspects mesh metadata, bounding boxes, face groups, and exports triangulated geometry | No |
| [body_measurements.py](#body_measurementspy) | Geometry | Computes height and bust / waist / hip circumferences from horizontal mesh slices | No |
| [scene_to_usd.py](#scene_to_usdpy) | Export | Exports the live scene to a Pixar USD file (meshes, UVs, cameras, lights, hair) | No |
| [turntable.py](#turntablepy) | Rendering | Renders a 360° turntable by stepping Y rotation across N frames | Yes |
| [multi_camera_render.py](#multi_camera_renderpy) | Rendering | Renders from every camera in the scene to separate files | Yes |
| [material_color_variations.py](#material_color_variationspy) | Rendering | Renders the same scene with a list of diffuse colour swatches | Yes |
| [batch_render_morph_variations.py](#batch_render_morph_variationspy) | Rendering | Renders a matrix of morph value combinations | Yes |
| [dataset_generator.py](#dataset_generatorpy) | ML / Data | Generates a randomised render dataset with JSON sidecar for LoRA training | Yes |
| [expression_transfer.py](#expression_transferpy) | AI / Vision | Extracts a facial expression from a photo using MediaPipe and applies it to a Genesis 9 figure | No |
| [webcam_expression_mirror.py](#webcam_expression_mirrorpy) | AI / Vision | Mirrors your live webcam expression onto a Genesis 9 figure in real time | No |

BVH / motion-capture examples (`bvh_import.py`, `bvh_discover.py`,
`bvh_bone_maps.py`) are under active development and not yet stable.

---

## Fundamentals

### raw_script.py

Drop down to raw DazScript when the typed SDK doesn't expose what you need.
Executes an IIFE against the primary scene selection and pretty-prints the
JSON result.

```bash
python raw_script.py
```

No arguments.  Edit the script body inline to run your own DazScript.

---

### scene_introspection.py

Read-only dump of the entire scene hierarchy and world-space transforms.
Output is JSON and can be piped to `jq` or redirected to a file.

```bash
python scene_introspection.py
python scene_introspection.py | jq '.tree[0]'
```

No arguments.

---

### scene_inventory.py

Collects a structured report for every node in the scene — type, label,
world position, visibility, material names, vertex count, and (for figures)
bone and morph counts.  Everything is gathered in a single DazScript call.

Useful for pipeline QA, asset auditing, and debugging scene composition.

```bash
python scene_inventory.py
python scene_inventory.py --out inventory.json --pretty
```

| Argument | Default | Description |
|---|---|---|
| `--out FILE` | stdout | Write JSON to this file instead of stdout |
| `--pretty` | off | Pretty-print the JSON output |

---

### batch_operations.py

Shows how `Batch` bundles multiple independent DazScript reads into a single
HTTP round-trip.  Reading label, bone count, and morph count for N figures
normally costs 3N calls; with `Batch` it costs 1.

Includes an optional `--compare` mode that runs the same reads the naive way
and prints the speedup ratio.

```bash
python batch_operations.py
python batch_operations.py --compare
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
python character_state.py save    --figure "Genesis 9" --out state.json
python character_state.py restore --figure "Genesis 9" --file state.json
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
python pose_transfer.py
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
python animation_frame_dump.py --figure "Genesis 9" --out anim.json
python animation_frame_dump.py --figure "Genesis 9" --out anim.json --morphs
```

| Argument | Default | Description |
|---|---|---|
| `--figure LABEL` | `Genesis 9` | Figure label |
| `--out FILE` | `anim.json` | Output JSON file |
| `--morphs` | off | Also capture non-zero morph values per frame |

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
python geometry_analysis.py --figure "Genesis 9"
python geometry_analysis.py --figure "Genesis 9" --groups
python geometry_analysis.py --figure "Genesis 9" --triangulate --out tris.json
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
largest closed loop at each slice.  The example targets Genesis 8, Genesis 8.1,
and Genesis 9 figures, but the same approach works for other figures too.
Each reported measurement includes both centimeters and inches.
It also picks generation-specific torso anchors and offers a `--torso-only`
mode that filters obvious arm-spread outliers from the bust measurement.
For bust anchoring it prefers left/right pectoral bones when present, then
falls back to the spine/chest chain.
Bust is measured from the largest perimeter loop within a narrow band around
that anchor, which is closer to how tape-style measurements are usually taken.
The example loads a small calibration table from
`body_measurements.calibration.json`, with `Genesis 9 Female` seeded from the
provided Measure Metrics reference values.
You can edit that JSON file to tune the reference targets without touching the
measurement code.
The script detects the figure generation from the skeleton bones and uses the
scene label to choose a matching calibration entry when it can, so labels like
`Genesis 9 Male` or `Genesis 9 Female` will select the corresponding table row.
If you want to override that behavior explicitly, pass `--figure-type` with a
value like `G9M`, `G9F`, `G8M`, or `G8.1F`.
If you pass `--clothing` on a female figure, the example also prints heuristic
bra and dress size estimates in US, UK, and EU sizing.
Add `--pretty` if you want the summary rendered as compact tables, including a
small bra sanity-check table with bust, underbust, and difference values.

Best results come from a neutral A-pose or T-pose with the figure standing
upright in the scene.  The example uses bone heights as anchors when they are
available and falls back to simple height ratios otherwise.

**Dependency**
```bash
pip install trimesh
```

```bash
python body_measurements.py --figure "Genesis 9"
python body_measurements.py --figure "Genesis 8" --out measurements.json
python body_measurements.py --figure "Genesis 8.1" --sample-step 0.25
python body_measurements.py --figure "Genesis 9" --torso-only
```

| Argument | Default | Description |
|---|---|---|
| `--figure LABEL` | `Genesis 9` | Figure label as shown in the Scene panel |
| `--sample-step CM` | `0.5` | Slice spacing used when searching for local min/max circumferences |
| `--search-window CM` | `5.0` | Half-width of the bust / underbust / low-hip search window |
| `--torso-only` | off | Apply a robust bust selector that ignores obvious arm-spread outliers |
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
python scene_to_usd.py --out scene.usda
python scene_to_usd.py --out scene.usda --morphs
python scene_to_usd.py --out scene.usdc --figure "Genesis 9"
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

### turntable.py

Rotates a figure around its local Y axis in equal steps and renders each
frame to a numbered PNG.  Existing X and Z rotations are preserved so a
posed character stays posed throughout the spin.

Combine output frames into a video:
```bash
ffmpeg -framerate 24 -i frame_%03d.png turntable.mp4
```

```bash
python turntable.py
python turntable.py --figure "My Character" --steps 72 --out C:/turntable
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
python multi_camera_render.py
python multi_camera_render.py --out C:/renders --width 1920 --height 1080
python multi_camera_render.py --cameras "Front" "Side" "Hero Shot"
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
python material_color_variations.py --node "Cube" --material "Default"
python material_color_variations.py \
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
python batch_render_morph_variations.py
```

No command-line arguments.

---

## ML / Data pipelines

### dataset_generator.py

Randomises a set of expression morphs on a Genesis 9 figure and renders
each variation to a numbered PNG.  A JSON sidecar is written alongside the
images so the dataset is fully reproducible.  Suitable as a starting point
for generating LoRA training data.

```bash
python dataset_generator.py
python dataset_generator.py --count 100 --out C:/dataset --size 512
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
python keyframe_baking.py --figure "Genesis 9"
python keyframe_baking.py --figure "Genesis 9" --morphs
python keyframe_baking.py --figure "Genesis 9" --start 10 --end 90 --morphs
python keyframe_baking.py --figure "Genesis 9" --preview
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
python animation_mixing.py clip   --anim walk.json --start 10 --end 40 --out walk_loop.json
python animation_mixing.py blend  --a walk.json --b run.json --t 0.5 --out trot.json
python animation_mixing.py append --a intro.json --b main.json --out full.json
python animation_mixing.py apply  --anim walk.json --frame 0 --figure "Genesis 9"
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
python pose_interpolation.py --a neutral.json --b smile.json --steps 10
python pose_interpolation.py --a neutral.json --b smile.json \
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
python expression_transfer.py photo.jpg
python expression_transfer.py photo.jpg --figure "Genesis 9" --scale 0.8
python expression_transfer.py --list-properties
python expression_transfer.py --list-properties --search blink
python expression_transfer.py photo.jpg --debug
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
python webcam_expression_mirror.py
python webcam_expression_mirror.py --figure "Genesis 9" --scale 0.8
python webcam_expression_mirror.py --camera 1 --fps 15
python webcam_expression_mirror.py --smooth 0.7
python webcam_expression_mirror.py --no-preview
```

| Argument | Default | Description |
|---|---|---|
| `--figure LABEL` | `Genesis 9` | Target figure label |
| `--scale FLOAT` | `1.0` | Global expression scale factor |
| `--camera N` | `0` | OpenCV camera index (try `1`, `2`, … for external webcams) |
| `--fps N` | `10` | Max DAZ Studio updates per second |
| `--smooth FLOAT` | `0.5` | EMA smoothing: `0` = raw/responsive, `0.9` = very smooth |
| `--no-preview` | off | Run headless with no OpenCV window (Ctrl+C to stop) |
