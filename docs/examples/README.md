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
| [character_state.py](#character_statepy) | Character | Saves and restores morphs, expression controls, and bone rotations | No |
| [pose_transfer.py](#pose_transferpy) | Character | Copies a pose from one figure to another in a single undo step | No |
| [animation_frame_dump.py](#animation_frame_dumppy) | Character | Exports bone rotations and morph values for every animation frame | No |
| [turntable.py](#turntablepy) | Rendering | Renders a 360° turntable by stepping Y rotation across N frames | Yes |
| [multi_camera_render.py](#multi_camera_renderpy) | Rendering | Renders from every camera in the scene to separate files | Yes |
| [material_color_variations.py](#material_color_variationspy) | Rendering | Renders the same scene with a list of diffuse colour swatches | Yes |
| [batch_render_morph_variations.py](#batch_render_morph_variationspy) | Rendering | Renders a matrix of morph value combinations | Yes |
| [dataset_generator.py](#dataset_generatorpy) | ML / Data | Generates a randomised render dataset with JSON sidecar for LoRA training | Yes |
| [pose_interpolation.py](#pose_interpolationpy) | Animation | Interpolates between two saved states with easing curves and renders each step | Yes |
| [expression_transfer.py](#expression_transferpy) | AI / Vision | Extracts a facial expression from a photo using MediaPipe and applies it to a Genesis 9 figure | No |

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
