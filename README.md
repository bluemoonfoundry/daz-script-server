# DazScript Server

**Version 2.9.2** | DAZ Studio 4.5+ | DAZ Studio 6.25+ | Windows & macOS

[![Docs](https://img.shields.io/badge/docs-dazpy%20SDK-blue)](https://bluemoonfoundry.github.io/daz-script-server/)
[![HTTP API](https://img.shields.io/badge/docs-HTTP%20API%20reference-blue)](https://bluemoonfoundry.github.io/daz-script-server/api-reference/)

A production-ready DAZ Studio plugin that embeds a secure HTTP server inside DAZ Studio, enabling remote execution of DazScript via HTTP POST requests (or an optional Python library that wraps the interface and adds additional features) with JSON responses. Control DAZ Studio programmatically from external tools, automation scripts, and custom applications.

> [!NOTE]
> As of v2.6.0, plugins for DS4 and DS6 on Windows, MacOS Intel, and MacOS Apple Silicon are included as part of the standard release artifacts. Remember that if you want to use a newer version of the plugin you must remove any old DLL or dylib file first!
---

## 🚀 Quick Start

**Already have the plugin installed?**

1. Open DAZ Studio → **Window → Panes → Daz Script Server**
2. Click **Start Server** (default: `127.0.0.1:18811`)
3. Click **Copy** to copy your API token (optional, but recommended for public environments)

**Option A — dazpy Python SDK (recommended):**

```bash
pip install dazpy
```

```python
import time
from dazpy import DazClient, DazScene

client = DazClient()          # auto-loads token from ~/.daz3d/dazscriptserver_token.txt
scene  = DazScene(client)

print(scene.num_nodes(), "nodes in scene")

figure = scene.find_skeleton_by_label("Genesis 9")

bones = figure.bones()
print([b._identifier.value for b in bones if "neck" in b._identifier.value.lower()])

rots=[0,4,10,15,20]

for rot in rots:
    print (f"Set rotation {rot}")
    figure.find_bone("neck1").set_local_rotation(0, rot, 0)
    time.sleep(1)
```

**Option B — raw HTTP (any language):**

```python
import requests

response = requests.post(
    "http://127.0.0.1:18811/execute",
    json={"script": "(function(){ return 'Hello there from Daz Studio!'; })()"}
)
print(response.json())
```

**Need to get the plugin?** Jump to [Getting the Plugin](#getting-the-plugin) below.

---

## Examples

**Complete example collection:** [daz-script-server-examples repository](https://github.com/bluemoonfoundry/daz-script-server-examples)

Production-ready examples ranging from beginner tutorials to advanced pipeline implementations:
- **48 examples** across 9 categories
- Individual READMEs with skill level classification
- Requirements.txt per example
- Comprehensive searchable table

Categories: fundamentals, character, animation, rendering, geometry, export, ml_data, ai_vision, bvh

---

## 📋 Table of Contents

### Getting Started
- [Quick Start](#-quick-start)
- [Why This Exists](#why-this-exists)
- [What's New in v2.9.0](#whats-new-in-v290)
- [What's New in v2.8.0](#whats-new-in-v280)
- [What's New in v2.7.2](#whats-new-in-v272)
- [What's New in v2.7.1](#whats-new-in-v271)
- [What's New in v2.7.0](#whats-new-in-v270)
- [What's New in v2.6.0](#whats-new-in-v260)
- [What's New in v2.5.0](#whats-new-in-v250)
- [What's New in v2.4.0](#whats-new-in-v240)
- [What's New in v2.3.0](#whats-new-in-v230)
- [What's New in v2.2.0](#whats-new-in-v220)
- [What's New in v2.0.0](#whats-new-in-v200)
- [What's New in v1.3.0](#whats-new-in-v130)
- [What's New in v1.2.0](#whats-new-in-v120)
- [Requirements](#requirements)
- [Getting the Plugin](#getting-the-plugin)

### dazpy Python SDK
- [Overview](#-dazpy-python-sdk)
- [Installation](#installation)
- [Jupyter Notebook](#jupyter-notebook)
- [Connecting to DAZ Studio](#connecting-to-daz-studio)
- [Scene Graph](#scene-graph)
- [Figures — Skeletons and Bones](#figures--skeletons-and-bones)
- [Morphs](#morphs)
- [Materials](#materials)
- [Cameras and Lights](#cameras-and-lights)
- [Scene I/O and Timeline](#scene-io-and-timeline)
- [Geometry](#geometry)
- [Advanced: Batch, Undo, Async](#advanced-batch-undo-and-async)
- [Error Handling](#error-handling)
- [Testing dazpy](#testing-dazpy)

### Using the Plugin
- [Starting the Server](#starting-the-server)
- [Configuration](#-configuration)
- [API Reference](#-api-reference)
- [Script Registry](#-script-registry)
- [Async Operations](#-async-operations)
- [Scene Events (SSE)](#-scene-events-sse)
- [Client Examples](#-client-examples)

### Security & Best Practices
- [Security Features](#-security-features)
- [Security Best Practices](#-security-best-practices)
- [Troubleshooting](#-troubleshooting)

### Advanced Topics
- [Writing Scripts](#writing-scripts)
- [Performance Tuning](#performance-tuning)
- [Integration Patterns](#integration-patterns)
- [Reverse Proxy Setup](#reverse-proxy-setup-https)

### Reference
- [FAQ](#-frequently-asked-questions)
- [Contributing](#contributing)
- [License](#license--attribution)

### Additional Documentation
- [dazpy SDK Docs](https://bluemoonfoundry.github.io/daz-script-server/) — hosted on GitHub Pages
- [HTTP API Reference](https://bluemoonfoundry.github.io/daz-script-server/api-reference/) — hosted on GitHub Pages
- [OpenAPI Specification](openapi.yaml)
- [Architecture](ARCHITECTURE.md)
- [Migration Guide (v1.x → v2.0)](MIGRATION.md)
- [Changelog](CHANGELOG.md)
- [Contributing Guide](CONTRIBUTING.md)
- [Interaction Pose Roadmap](INTERACTION_POSE_ROADMAP.md)

---

## Why This Exists

DAZ Studio is powerful for 3D content creation, but automation is limited to manually running scripts. This plugin solves that by exposing REST endpoints (HTTP) for remote clients to, among other things, submit inline scripts to execute, which can return log output lines and a return object as JSON. 

**What You Can Do:**
- **Remote Automation** - Control DAZ Studio from Python, web apps, CI/CD pipelines
- **Programmatic Access** - Build custom tools that interact with scenes, assets, and rendering
- **Integration** - Connect to game engines, asset pipelines, batch processing systems
- **API-First Development** - Treat DAZ Studio as a service with HTTP APIs

**Common Use Cases:**
- Batch rendering and asset processing
- Asset management system integration
- Automated scene generation and testing
- Custom web-based controllers
- CI/CD pipelines for 3D content validation

---

## What's New in v2.9.0

### 🎬 dazpy.cinematics — camera shot builders

`dazpy.cinematics` packages common camera choreography on top of
`DazCamera`/`DazScene`: `apply_static_shot()` places/aims/configures a
camera in one call; `apply_orbit_camera()` sweeps a camera around a target
across a frame range; `apply_frame_subject()` frames a subject at a named
shot distance (`close_up` / `medium` / `full_body`); and
`apply_animated_shot()` writes real, interpolated DAZ Studio keyframes at a
sequence of waypoints instead of baking a value on every frame.

```python
from dazpy.cinematics import OrbitCamera, apply_orbit_camera

apply_orbit_camera(scene, OrbitCamera(target=figure, radius=250, frame_start=0, frame_end=90))
```

### 💡 dazpy.lighting — three-point rigs and HDRI environments

`apply_three_point_light_setup()` creates and places a key/fill/rim light
rig around a target in one call, via angle/distance placement or explicit
world-space positions per light. `apply_hdri_environment()` applies
image-based dome lighting — map, intensity, rotation, dome/scene mode,
visibility, and IBL resolution — validating the image path up front and
verifying a post-apply readback so a silent failure never passes as success.

### 🧍 dazpy.poses — apply_pose, reset_transforms, zero_figure

Common pose operations without hand-assembling a `DazPose`:
`apply_pose()` applies a pose object or a JSON file path directly to a
skeleton; `reset_transforms()` zeroes a node's local position/rotation and
resets scale to 1.0; `zero_figure()` drives every bone rotation and morph
to zero while leaving the figure's root transform untouched by default.

### 📐 dazpy.math3.AxisRemap — coordinate-space conversion

A generic signed-axis-permutation converter for `Vec3`/`Quat`/
`BoundingBox` between coordinate conventions, with a ready-made
`Y_UP_TO_Z_UP` preset for moving data from DAZ Studio (Y-up) into
Blender/glTF-style Z-up pipelines.

```python
from dazpy.math3 import Y_UP_TO_Z_UP

blender_pos = Y_UP_TO_Z_UP.apply_vec3(daz_pos)
```

### 🦴 DazSkeleton.bone_rotations_quat()

Returns local-space quaternion rotations for every bone in one HTTP
round-trip — the composable counterpart to `bone_rotations()` for callers
feeding the result into another rotation (e.g. `AxisRemap.apply_quat()`),
sidestepping the per-bone Euler rotation-order tracking that would
otherwise be required.

### 🎞️ Frame-level progress streaming for animation renders

The `GET /render/:id/progress` SSE stream now emits a progress event at
each frame boundary during an animation render, instead of only start/
terminal events — the DAZ SDK exposes no per-percent render progress
signal, so this frame-level marker is the most granular progress available.

### ⚡ Async client — `dazpy.aio.AsyncDazClient`

Async frameworks (FastAPI, FastMCP, ComfyUI custom nodes, asyncio/Temporal
workflows) previously had to wrap every `DazClient` call in
`asyncio.to_thread()` or hand-roll an `httpx.AsyncClient` wrapper.
`dazpy.aio.AsyncDazClient` mirrors `DazClient`'s full method surface —
`execute`, `execute_file`, inline/file async submit/status/result/list/cancel, render
submit/batch/animation, USD export, and server-health endpoints — as
native `async def` methods backed by `httpx.AsyncClient`, including the
same `retry_on_busy`/`max_wait` backoff semantics (via `asyncio.sleep`
instead of blocking `time.sleep`).

```python
from dazpy.aio import AsyncDazClient

async def main():
    async with AsyncDazClient() as client:
        request_id = await client.execute_file_async_submit("C:/jobs/pose-probe.dsa")
        result = await client.get_request_result(request_id, wait=True)
        print(result)
```

Requires the optional `httpx` dependency: `pip install dazpy[aio]`.

### `DazClient` connection pooling + `close()`

`DazClient` now issues requests through a pooled `requests.Session` instead
of a fresh connection per call, and supports `close()` / use as a context
manager (`with DazClient() as client:`) for symmetry with the new async
client's connection lifecycle.

### Truthful Iray/Viewport render-engine selector

`DazRenderSettings.render_engine_state()` now reads the effective
`DzRenderOptions.renderType` value and the active renderer class/name as separate
facts. Its schema-1 record includes the raw enum value/name, normalized
`verified_iray` / `verified_non_iray` / `unavailable` status, and field-level
live-readback provenance. A retained `NVIDIA Iray` active-renderer name never
overrides a Viewport/OpenGL `renderType`.

`DazRenderSettings.set_render_engine("iray" | "viewport")` is an explicit
persistent setter. It selects the registered `DzIrayRenderer` plus `Software` for
Iray, or `ScreenShot` for Viewport, calls `applyChanges()`, and returns only after
exact readback. Missing renderers, mutation/apply faults, malformed replies, and
readback disagreement raise `RenderError`; unknown engine names raise `ValueError`
before dispatch.

```python
settings = DazRenderSettings(client)
before = settings.render_engine_state()
change = settings.set_render_engine("iray")
assert change["readback"]["status"] == "verified_iray"
```

The `engine` field on `/render`, `/render/batch`, and `/render/animation` also
accepts `viewport` and uses the same fail-closed mutation/readback rules. These
operations intentionally persist the requested engine. DAZ documents `ScreenShot`
and `HardwareAssisted` as Viewport/OpenGL operations and `Software` as the active
software-renderer operation in the
[DzRenderOptions reference](https://docs.daz3d.com/public/software/dazstudio/4/referenceguide/scripting/api_reference/object_index/renderoptions_dz);
renderer lookup and activation are documented by
[DzRenderMgr](https://docs.daz3d.com/public/software/dazstudio/4/referenceguide/scripting/api_reference/object_index/rendermgr_dz).

---

## What's New in v2.8.0

### 🚦 Fail Fast When DAZ Studio Is Busy — `503 STUDIO_BUSY`

DAZ Studio's Qt main thread is single-threaded: if a user loads a scene,
saves, clears the scene, or renders through the DAZ Studio UI while the
server is also being driven remotely, requests that need the main thread
used to block indefinitely with no signal to the caller. `/execute`,
`/scripts/:id/execute`, the async-enqueue endpoints, and the render-submit
endpoints now check DAZ Studio's busy state first and return `503` with
`error_code: "STUDIO_BUSY"` (plus a `Retry-After` header) immediately
instead of hanging.

`dazpy` surfaces this as a new exception hierarchy — `DazBusyError`, with
`StudioBusyError` (503) and `ConcurrencyLimitError` (429) subclasses, each
carrying `reason` and `retry_after`. This also fixes a pre-existing bug
where `429 CONCURRENT_LIMIT_EXCEEDED` responses were misreported as
`ScriptRuntimeError`, as if the script itself had failed.

```python
from dazpy import DazClient
from dazpy.exceptions import DazBusyError

client = DazClient()
try:
    result = client.execute("1+1;")
except DazBusyError as e:
    print(f"DAZ Studio is busy: {e.reason} — retry after {e.retry_after}s")
```

Opt in to automatic retry with backoff instead of handling the exception
yourself:

```python
result = client.execute("1+1;", retry_on_busy=True, max_wait=30.0)
```

`retry_on_busy`/`max_wait` are available on `execute`, `execute_file`,
`execute_async_submit`, `render_submit`, `render_batch_submit`, and
`render_animation_submit`. Retry is opt-in and off by default — callers
(and any LLM driving them) stay informed rather than silently blocked.

---

## What's New in v2.7.2

No functional changes to `dazpy`'s behavior. `2.7.1`'s version bump missed
three places that still said `2.7.0`: `dazpy.__version__` itself (already
baked into the published `2.7.1` wheel — the reason this needed a new
version rather than a doc fix), `openapi.yaml`'s `info.version` and two
response examples, and the plugin's own `DZSRV_VERSION_STR` (what
`/status`/`/health` actually return at runtime). All three now correctly
say `2.7.2`.

---

## What's New in v2.7.1

No functional changes. Republished to fix a stale PyPI package description —
the `2.7.0` wheel was uploaded to PyPI before the README fixes below (in
"What's New in v2.7.0") had landed, and PyPI has no way to update an
already-published version's metadata. `2.7.1`'s code is identical to
`2.7.0`'s.

---

## What's New in v2.7.0

### 🖼️ Iray Canvas Support — `DazRenderSettings`

Enumerate, create, and remove Iray Canvases (normal/depth/material-ID/etc.
render passes) and resolve their output file paths for a given render:

```python
from dazpy import DazClient, DazRenderSettings

client = DazClient()
rs = DazRenderSettings(client)

rs.add_canvas("Depth")
print(rs.list_canvases())
print(rs.canvas_output_paths("C:/renders/shot01.png"))
```

### 📸 Scene Checkpoints — `DazSceneState`

A full scene checkpoint in one call: every skeleton's complete pose
(bone-level, via `DazPose`) plus camera and light transforms/key
properties, captured and restored via raw property values so repeated
capture/apply cycles are idempotent — no more creeping drift on a
character's morph dials across repeated pose save/restore.

```python
from dazpy import DazClient, DazSceneState

client = DazClient()
state = DazSceneState(client)

snapshot = state.capture()
# ... pose the scene for a render ...
state.apply(snapshot)   # back to exactly where you started
```

### 🧱 Scene Editing — Node Creation, Deletion, Reparenting

`DazScene.create_camera()`/`create_light()`, `DazNode.delete()`, and
`DazNode.reparent()` round out the scene graph so a script can build and
restructure a scene, not just query and pose one.

### Also in this release

- **Clothing/prop fit control** — `DazNode.fit_to()`/`.unfit()`/`.fitted_items()`.
- **dForce simulation control** — freeze/unfreeze and run/clear simulations via a new `DazDForce` proxy and `DazScene` helpers.
- **Iray quality control** — `max_samples`/`max_time_secs`/`quality`/`set_quality_preset()` on `DazRenderSettings`, plus `active_engine()`/`set_active_engine()` to query/switch the render engine.
- **Per-frame animation rendering** — `POST /render/animation` and `DazClient.render_animation_submit()`.
- **Scene-change event stream** — `DazClient.stream_scene_events()` for watching or blocking on node/light/camera/selection/scene/time/render events.
- **Camera lens shift** — `DazCamera.lens_shift_x`/`.lens_shift_y`.
- **FBX/OBJ export** — `DazScene.export_fbx()`/`.export_obj()`.
- **Keyframe curve introspection** — `DazProperty.get_keys()`/`.remove_key()`/`.clear_keys()`.
- **Bulk property reads** — `DazElement.numeric_properties()` and `.class_name`.
- A handful of correctness fixes to `DazPose`/`DazViewport.capture()` (ERC-driven property inflation, bone selection restore, backdrop restore) and render camera selection — see [CHANGELOG.md](CHANGELOG.md#270---2026-07-19) for details.

---

## What's New in v2.6.0

### 💾 Scene Save Copy — `POST /scene/save-copy` + `DazScene.save_copy()`

Save the current scene to a new path without changing the scene's internal
filename pointer or dirty flag — the programmatic equivalent of a
**"Save a Copy As…"** menu option.

```python
from dazpy import DazClient, DazScene

client = DazClient()
scene  = DazScene(client)

result = scene.save_copy("C:/backups/scene_v2.duf")
print(result["method"])   # "copy", "serialize", or "serialize+restore"
```

For scenes with no unsaved changes the plugin uses `QFile::copy()` — a pure
file-system copy that produces a byte-identical file with zero DAZ Studio state
change.  For dirty scenes it serialises via `Scene.saveScene()` and restores
the original filename immediately.  The `method` field in the response tells
you which strategy was used.

See [`fundamentals/scene_save_copy`](https://github.com/bluemoonfoundry/daz-script-server-examples/tree/main/fundamentals/scene_save_copy) in the examples repo for a complete example
with `--compare` and `--dry-run` options.

---

## What's New in v2.5.0

### 🤝 Interaction Posing — Multi-Figure Poses and IK Alignment

The dazpy SDK now includes a full **interaction posing system** for placing two
figures together in physically plausible poses (seated, touching, kissing, combat
stances, etc.) and aligning individual limbs to world-space targets using an
iterative IK solver.

**Preset recipe builders** generate a ready-to-apply `InteractionRecipe` from a
pair of figure labels:

```python
from dazpy import DazClient, DazScene
from dazpy._interaction import build_sit_recipe, build_touch_recipe

client = DazClient()
scene  = DazScene(client)

recipe = build_sit_recipe("BobG8", "AliceG8")
scene.apply_interaction_recipe_to_scene(recipe)
```

Available presets: `build_sit_recipe`, `build_touch_recipe`, `build_kiss_recipe`,
`build_fight_recipe`. All presets produce an `InteractionRecipe` that can be
serialised to JSON, stored, and replayed.

**IK limb alignment** moves a hand or foot end-effector to a world-space target
using a Jacobian-based iterative solver running entirely inside a single batched
HTTP call sequence:

```python
from dazpy._interaction import align_hand_target, align_foot_target

skel   = scene.find_skeleton("BobG8")
result = align_hand_target(skel, target_position=(12.0, 95.0, 8.0))
print(f"converged={result.converged}  final_error={result.final_error:.3f} cm")
```

**Bulk scene snapshot** fetches every skeleton's bone world positions in a single
HTTP call, avoiding per-bone round-trips when building rig data:

```python
snapshot  = scene.scene_snapshot()
profiles  = build_rig_profiles_from_snapshot(snapshot)
```

**Body measurement accuracy improvements** in [`geometry/body_measurements`](https://github.com/bluemoonfoundry/daz-script-server-examples/tree/main/geometry/body_measurements):

- Slices now use centroid-weighted torso loop selection to filter arm cross-sections, correcting a ~70 cm overestimate on A-pose figures.
- The heuristic fallback for unlabelled figures (e.g. a character named
  `"MadisonG9"`) now uses robust outlier rejection before selecting the peak
  perimeter slice.
- Pass `--figure-type G9F` (or `G9M`, `G8F`, etc.) to force a calibration entry
  when the figure's scene label doesn't contain a gender keyword.

---

## What's New in v2.4.0

### 🎬 Render Endpoints — Trigger and Track DAZ Studio Renders

Three new HTTP endpoints let you submit renders, stream live progress, and batch
render variants — all without blocking the server.

**`POST /render`** — submit a render job and get back a `request_id`:

```python
from dazpy import DazClient, render, RenderVariant, FigureMorphs

client = DazClient()

# Simple render with default settings
result = render(client, width=1920, height=1080)
print(result.output_path)

# Render with morph overrides
result = render(client, width=1920, height=1080,
                figure_morphs=[FigureMorphs("Genesis 9", {"eCTRLSmileSimple": 1.0})])
```

**`POST /render/batch`** — submit multiple variants in one request:

```python
from dazpy import render_variants, RenderVariant, FigureMorphs

variants = [
    RenderVariant(label="neutral", figure_morphs=[FigureMorphs("Genesis 9", {})]),
    RenderVariant(label="smile",   figure_morphs=[FigureMorphs("Genesis 9", {"eCTRLSmileSimple": 1.0})]),
    RenderVariant(label="frown",   figure_morphs=[FigureMorphs("Genesis 9", {"eCTRLFrownSimple": 0.8})]),
]
results = render_variants(client, variants, width=1920, height=1080)
```

**`GET /render/:id/progress`** — SSE stream of render progress events:

```
data: {"stage":"rendering","progress":0.42,"elapsed_ms":4200}
data: {"stage":"complete","progress":1.0,"output_path":"/path/to/render.png","elapsed_ms":9800}
```

**`POST /render/:id/cancel`** — cancel a queued or running render job:

```python
# Submit without waiting, cancel later
job = render(client, r"C:\tmp\out.png", width=1920, height=1080, wait=False)
# ...
client.cancel_render(job.request_id)
```

Returns 400 if the `request_id` belongs to a non-render job, so you get a clear
error rather than silently cancelling the wrong request.

### 🎥 Scene Camera and Light Discovery

Two new `DazScene` methods make it easy to look up cameras and lights by label —
the same label string the `render()` `camera` parameter accepts:

```python
from dazpy import DazClient, DazScene
from dazpy._render_api import render

client = DazClient()
scene  = DazScene(client)

cam = scene.find_camera_by_label("Camera 1")
print(cam.focal_length, cam.pixels_width)

# Use the found camera name directly in a render
render(client, r"C:\tmp\out.png", camera="Camera 1", width=1920, height=1080)
```

### ↩️ Programmatic Undo / Redo

Step the DAZ Studio undo stack from Python:

```python
scene.set_frame(10)
scene.undo_last()   # step back (Ctrl+Z equivalent)
scene.redo_last()   # step forward (Ctrl+Y equivalent)
```

`undo_last()` / `redo_last()` step the global stack directly. Use the existing
`scene.undo("label")` context manager when you want to group a series of changes
into a single undoable operation.

### 🔌 Companion Plugin Route Registration

Third-party plugins can now register their own HTTP routes into the DazScript
Server. Routes are resolved via a `DzScriptServerPane` pointer published on
`qApp`, so companion plugins discovered at DAZ Studio startup are automatically
wired in. Registered routes support path parameters (e.g. `/export/:id/status`).

### 🐛 Bug Fixes

- Fixed CRT heap mismatch crash when a catch-all dispatcher routed to a
  companion plugin (mixed MSVC runtime allocator boundary).
- Fixed companion plugin routes silently dropped when registered after the
  server had already started listening.
- Fixed data race in the catch-all route dispatcher under concurrent requests.

---

## What's New in v2.3.0

### 🔔 Scene Events — Real-Time Push Notifications via SSE

Clients can now subscribe to live DAZ Studio scene changes over a persistent HTTP connection using **Server-Sent Events (SSE)**. No more polling for scene state.

```python
import requests, json

token = open(os.path.expanduser("~/.daz3d/dazscriptserver_token.txt")).read().strip()

with requests.get(
    "http://127.0.0.1:18811/scene/events",
    headers={"X-API-Token": token},
    stream=True
) as r:
    for line in r.iter_lines():
        if line.startswith(b"data: "):
            event = json.loads(line[6:])
            print(event["type"], event["data"])
```

**Event types:** `node.added`, `node.removed`, `skeleton.added/removed`, `light.added/removed`, `camera.added/removed`, `selection.list_changed`, `selection.primary_changed`, `scene.loading`, `scene.loaded`, `scene.saving`, `scene.saved`, `scene.clear_starting`, `scene.cleared`, `time.changed`, `playback.started`, `playback.finished`, `render.started`, `render.finished`

**Filter to only the categories you need:**
```
GET /scene/events?filter=node,selection,scene
```

All auth, IP whitelist, and security checks apply. The connection stays open until the client disconnects or the server stops. See [Scene Events (SSE)](#-scene-events-sse) for full documentation.

---

## What's New in v2.2.0

### 🦴 DazPose — Snapshot and Restore Poses

New module **`dazpy.DazPose`** captures a full skeleton pose in one call and
restores it later, with linear interpolation between any two stored poses.

```python
from dazpy import DazScene, DazPose

scene  = DazScene()
figure = scene.find_skeleton_by_label("Genesis 9")

neutral = DazPose.capture(figure)        # snapshot current pose
# ... dial morphs, animate, etc. ...
DazPose.blend(neutral, other_pose, t=0.5).apply(figure)  # 50 % mix
```

### 🎞 DazAnimation — Keyframe Read / Write

New module **`dazpy.DazAnimation`** exposes per-bone rotation and translation
tracks, timeline range queries, frame stepping, and pose baking.

```python
from dazpy import DazAnimation

anim = DazAnimation(figure)
print(anim.frame_range())          # (start, end)
anim.bake_pose_to_keyframes(start=0, end=60)
```

### 📐 math3 — Vec3, Quat, BoundingBox, AxisRemap

New module **`dazpy.math3`** provides lightweight value types returned throughout
the SDK: `Vec3` (positions, translations), `Quat` (rotations), and `BoundingBox`
(geometry bounds).  All support arithmetic operators and round-trip through JSON.
`AxisRemap` converts `Vec3`/`Quat`/`BoundingBox` values between axis conventions
via signed-axis permutations (e.g. the built-in `Y_UP_TO_Z_UP` preset for
converting DAZ Studio's Y-up scene data to Z-up tools like Blender).

### 🌐 Posed Vertex Export & USD Scene Export

**`DazGeometry.vertex_positions_posed()`** returns world-space deformed vertex
positions with skinning and morphs already applied — enabling downstream export
pipelines to read the final mesh without re-solving the rig.

New example **[`export/scene_to_usd`](https://github.com/bluemoonfoundry/daz-script-server-examples/tree/main/export/scene_to_usd)** uses this to export a full live
DAZ Studio scene to Pixar USD: posed meshes, cameras, lights, PBR materials, and
strand-based hair as `UsdGeom.BasisCurves`.  Pass `--morphs` to write blend
shapes as `UsdSkel` targets.

```bash
python scene_to_usd.py --output scene.usda
python scene_to_usd.py --output scene.usda --morphs
```

### 🏃 BVH Motion Capture Support

Three new interoperable example scripts:

| Script | Purpose |
|---|---|
| `bvh_import.py` | Parse a `.bvh` file and apply each frame to a DAZ skeleton |
| `bvh_discover.py` | Print a figure's bone hierarchy to help build bone maps |
| `bvh_bone_maps.py` | Canonical BVH ↔ DAZ bone-name tables for G8 / G9 |

### 🗂 New Examples

Four additional examples expanding SDK coverage:

| Script | What it shows |
|---|---|
| `animation_mixing.py` | Blend two stored poses at a configurable weight |
| `batch_operations.py` | Morph dials, material swaps, and camera moves in one batched request |
| `geometry_analysis.py` | Mesh vertex count, bounding box, and posed positions |
| `keyframe_baking.py` | Sample procedural animation and write explicit rotation keyframes |

### 🧪 Test Suite

`tests_dazpy.py` (unit) and `tests_dazpy_integration.py` (requires a live DAZ
Studio instance) now ship in the repo root.

### 📖 Docs & Ergonomics

- API reference pages for `DazPose`, `DazAnimation`, `Vec3`, `Quat`, `BoundingBox`, and `AxisRemap`
- Every script in [daz-script-server-examples](https://github.com/bluemoonfoundry/daz-script-server-examples) has an `if __name__ == "__main__":` guard and
  argparse `--help`, making all examples safe to import and self-documenting

---

## What's New in v2.0.0

v2.0 is a **backward-compatible** internal rewrite focused on correctness and reliability.
The HTTP API, authentication mechanism, and all settings are unchanged.

### dazpy Python SDK

A full-featured Python SDK ships alongside the plugin, installable as a wheel from the
release page or via `pip install dazpy`. It exposes DAZ Studio's scene graph as typed
Python objects: `DazScene`, `DazSkeleton`, `DazBone`, `DazMaterial`, `DazMorph`, and more.
See [dazpy Python SDK](#-dazpy-python-sdk) below for the complete reference.

### Bug Fixes

- **Concurrent request race condition fixed** — Under heavy load, more requests than the
  configured maximum could slip through. The active-request counter is now atomically
  managed under a `QMutex`.
- **DzScript memory safety** — Script objects are always destroyed on the main Qt thread,
  eliminating intermittent crashes from cross-thread deletion.
- **Signal/slot leak** — The `print()` capture connection is now always explicitly
  disconnected on early-return paths (auth failure, rate limit, etc.), preventing stale
  output from appearing in unrelated responses.

### Architecture

- Extracted `AuthenticationService`, `RateLimiterService`, `IPWhitelistService`,
  `MetricsCollector`, and `AsyncRequestManager` from the monolithic pane class
- `RequestValidator` and `RequestProcessor` replace inline dispatch logic
- `ServerSettings` / `ServerConfig` centralise all defaults and magic numbers

### New Documentation

- `openapi.yaml` — machine-readable OpenAPI 3.0 specification
- `ARCHITECTURE.md` — component and threading diagrams (Mermaid)
- `MIGRATION.md` — step-by-step upgrade guide from v1.x
- `CHANGELOG.md` — full version history
- `CONTRIBUTING.md` — developer guide

See the [full migration guide](MIGRATION.md) for upgrade steps and rollback instructions.

---

## What's New in v1.3.0

### ⚡ Async Script Execution

Long-running operations (renders, exports, batch jobs) no longer need to block the HTTP connection:

- **`POST /execute/async`** — Submit inline `script` or host-side `scriptFile` work asynchronously; returns a `request_id` immediately
- **`POST /scripts/:id/async`** — Submit a registered script asynchronously
- **`GET /requests/:id/status`** — Poll for progress (`queued`, `running`, `completed`, `failed`, `cancelled`)
- **`GET /requests/:id/result`** — Fetch the final result; supports `?wait=true` to long-poll until complete
- **`DELETE /requests/:id`** — Cancel a queued or running request
- **`GET /requests`** — List all active and recently completed requests

**Cancellation:** Queued requests are cancelled immediately. Running requests set a cancel flag and call `killRender()` — DAZ Studio honours the flag when the script returns.

**TTL:** Completed, failed, and cancelled requests are automatically purged after 1 hour (cleanup timer fires every 5 minutes).

**Stale running requests:** If a request has been `running` for more than 30 minutes without completing — e.g. a render blocked behind a DAZ Studio modal dialog — it's automatically marked `failed` so polling clients aren't left waiting forever. The underlying DAZ Studio operation may still be stuck; check the DAZ Studio window directly if this happens.

---

## What's New in v1.2.0

### 🔒 Security Enhancements
- **IP Whitelist** - Restrict access to specific IP addresses
- **Per-IP Rate Limiting** - Prevent brute force attacks with sliding window limits
- **Configurable Limits** - Adjust concurrent requests, body size, and script length

### 📦 Script Registry
- **Register Once, Call Many** - Upload scripts by name, execute by ID without retransmission
- **Session-Based Storage** - In-memory registry with register, list, execute, and delete endpoints
- **Auto-Recovery** - Returns 404 on stale IDs so clients can re-register after restarts

### ✨ Usability Improvements
- **Active Request Counter** - Real-time display of concurrent requests (X/max)
- **Auto-Start Option** - Start server automatically when pane opens
- **Better Error Messages** - Descriptive errors with actionable guidance
- **More Examples** - Added JavaScript/Node.js and PowerShell client examples

### 💾 Persistent Configuration
All settings (security, limits, monitoring) are saved via QSettings and restored between sessions.

---

## Requirements

- **DAZ Studio 4.5+** (for running the plugin)
- **DAZ Studio 4.5+ SDK** (for building from source)
- **CMake 3.5+**
- **Compiler:**
  - Windows: Visual Studio 2019 or 2022 (MSVC)
  - macOS: Xcode / clang with libc++

---

## 🐍 dazpy Python SDK

`dazpy` is a Python SDK that drives DAZ Studio through the Script Server.
It exposes the DAZ Studio scene graph as typed Python objects so you can write
automation code without authoring DazScript by hand.

### Installation

Download the `.whl` file from the [latest release](https://github.com/bluemoonfoundry/daz-script-server/releases/latest) and install it:

```bash
pip install dazpy-2.9.0-py3-none-any.whl
```

Or install directly from the repo for development:

```bash
pip install -e .
```

**Requirements:** Python 3.10+, `requests` (installed automatically).

---

### Jupyter Notebook

The repo ships an interactive Jupyter notebook (`notebooks/dazpy_intro.ipynb`) that
covers the full dazpy API with runnable examples. Launcher scripts handle installing
Jupyter and opening the notebook in one step.

**Prerequisites:** DAZ Studio must be running with the DazScriptServer plugin active before opening the notebook.

**Launch (macOS / Linux / Git Bash on Windows):**

```bash
./notebook.sh
```

**Launch (Windows PowerShell):**

```powershell
.\notebook.ps1
```

Both scripts install `dazpy` (editable) and `notebook` if they are not already present,
then open Jupyter in the `notebooks/` directory.

**Notebook sections:**

| Section | What it covers |
|---|---|
| 1. Server health | `client.health()` — verify the plugin is reachable |
| 2. Scene overview | `scene.num_nodes()`, `scene.nodes()` — list everything in the scene |
| 3. Find a figure / read a bone | `find_skeleton_by_label()`, `find_bone()`, `bone.local_euler` |
| 4. Raw DazScript | `client.execute()` — run arbitrary DazScript when the SDK doesn't cover it |
| 5. Error handling | Full exception hierarchy with `try/except` examples |
| 6. API browser | `dir(obj)` one-liner to list any object's public API surface |
| 7. Jupyter introspection | `obj?` / `obj??` inline help for any dazpy object |
| 8. Interactive bone rotator | `ipywidgets` sliders driving `bone.set_local_rotation()` in real time |
| 9. Morph / property explorer | List, search, and set morphs with `morph_values()` / `set_morph_values()` |
| 10. Scene tree pretty-printer | `scene.node_tree()` rendered as an indented tree with box-drawing characters |

**Interactive bone rotator** (section 8) requires ipywidgets:

```bash
pip install ipywidgets
```

---

### Connecting to DAZ Studio

```python
from dazpy import DazClient, DazScene

# Default: 127.0.0.1:18811, token auto-loaded from ~/.daz3d/dazscriptserver_token.txt
client = DazClient()

# Explicit connection
client = DazClient(host="127.0.0.1", port=18811, token="your-token", timeout=30.0)

scene = DazScene(client)     # or just DazScene() to use a default client
```

`DazClient` also exposes `status()`, `health()`, and `metrics()` for server introspection.

---

### Scene Graph

`DazScene` is the primary entry point. All methods execute DazScript on the server and
return typed Python objects.

```python
scene = DazScene()

# Node counts
print(scene.num_nodes())        # total nodes
print(scene.num_skeletons())    # figures only

# Get all nodes (returns DazSkeleton / DazCamera / DazLight / DazNode as appropriate)
for node in scene.nodes():
    print(node.name(), node.label(), node.position())

# Find nodes
node    = scene.find_node("Genesis9")
node    = scene.find_node_by_label("Genesis 9")

# Scene tree (hierarchy as nested dicts)
tree = scene.node_tree()

# All transforms in one round-trip
transforms = scene.all_node_transforms()

# Selection
selected = scene.selected_nodes()
primary  = scene.primary_selection()
scene.set_primary_selection(node)
scene.select_all(on=False)
```

#### DazNode

Every scene object is a `DazNode`. Common operations:

```python
node = scene.find_node_by_label("Cube")

# Transforms (world-space)
pos = node.position()                   # {"x": 0.0, "y": 0.0, "z": 0.0}
rot = node.rotation()                   # {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
node.set_position(10, 0, 0)
node.set_rotation(0, 45, 0)             # degrees

# Local-space transforms
lpos = node.local_position()
lrot = node.local_rotation()
node.set_local_position(0, 100, 0)
node.set_local_rotation(0, 0, 30)

# Scale
gs   = node.general_scale()            # uniform scale float
axes = node.scale()                     # {"x": 1.0, "y": 1.0, "z": 1.0, "general": 1.0}

# Visibility and scene membership
node.is_visible()
node.is_visible_in_render()
node.set_visible_in_render(False)
node.is_visible_in_viewport()
node.set_visible_in_viewport(True)
node.is_in_scene()
node.is_root()

# Bounding box
bb = node.bounding_box()                # {"min": {"x":…, "y":…, "z":…}, "max": {…}}

# Selection
node.is_selected()
node.select(True)

# Generic property access (fallback for anything not wrapped)
val = node.get_property("Some Property Label")
node.set_property("Some Property Label", 1.0)
```

---

### Figures — Skeletons and Bones

Figures in DAZ Studio are `DzSkeleton` instances. Posing a figure means setting
bone rotations.

```python
# Find a figure
figure = scene.find_skeleton_by_label("Genesis 9")
# or: scene.find_skeleton("Genesis9"), scene.skeletons()

# Bones
all_bones = figure.bones()              # list[DazBone]
forearm   = figure.find_bone("r_forearm")      # Genesis 9; use figure.bones() to list names
forearm   = figure.find_bone_by_label("Right Forearm")
n         = figure.num_bones()

# Follow target (clothing/hair fitted to a figure)
target = figure.follow_target()         # DazSkeleton | None

# DazBone — pose by setting local Euler angles (degrees)
rot = forearm.local_rotation()          # {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
forearm.set_local_rotation(0, 0, 45)    # bend forearm 45° on Z axis

pos   = forearm.local_position()
order = forearm.rotation_order()        # "XYZ", "ZYX", etc.
skel  = forearm.get_skeleton()          # back-reference to the figure

# Example: pose a figure's arm
with scene.undo("Pose arm"):
    figure.find_bone("lShldrBend").set_local_rotation(0, 0, -60)
    figure.find_bone("lForeArm").set_local_rotation(0, 0, -30)
```

`scene.nodes()` automatically returns `DazSkeleton` for figure nodes so you can
iterate and call `bones()` without an extra lookup.

---

### Morphs

Morphs control body shapes, facial expressions, and clothing fits.

```python
figure = scene.find_skeleton_by_label("Genesis 9")

# List all modifiers on a node
for mod in figure.modifiers():
    print(mod.name())

# Morphs only (DzMorph subclass)
for morph in figure.morphs():
    print(morph.name(), morph.value())

# Find and adjust a specific morph
smile = figure.find_modifier("PHMSmileOpen")
print(smile.value())        # 0.0–1.0
smile.set_value(0.8)

# Or via DazMorph properties
morph = figure.find_modifier("BodyMorphHeavy")
morph.value = 0.5           # property-style write
print(morph.min, morph.max)
```

---

### Materials

```python
node = scene.find_node_by_label("Genesis 9 Skin")

# All materials on a node
for mat in node.materials():
    print(mat.name(), mat.diffuse_color())

# Find a specific material
skin = node.find_material("Torso")

# Color and opacity
color = skin.diffuse_color()            # {"r": 255, "g": 220, "b": 200}
skin.set_diffuse_color(255, 210, 190)
print(skin.opacity())                   # 1.0
print(skin.color_map())                 # texture filename or None
print(skin.is_opaque())
print(skin.smoothing_angle())
print(skin.is_smoothing_on())

# Generic property fallback
skin.set_property("Glossy Reflectivity", 0.3)
```

---

### Cameras and Lights

```python
# Cameras
for cam in scene.cameras():
    print(cam.name(), cam.focal_length(), cam.is_view_camera())

cam = scene.cameras()[0]
cam.focal_length()          # mm
cam.frame_width()
cam.focal_distance()
cam.aspect_width()
cam.aspect_height()
cam.pixels_width()
cam.pixels_height()
cam.near_clipping_plane()
cam.far_clipping_plane()
cam.focal_point()           # {"x": …, "y": …, "z": …}
cam.aim_at(0, 150, 0)       # aim camera at world point

# Lights
for light in scene.lights():
    print(light.name(), light.is_on(), light.is_directional())

light = scene.lights()[0]
light.is_on()
light.is_directional()
light.is_area_light()
light.direction()           # {"x": …, "y": …, "z": …} (directional lights only)
light.set_color(1.0, 0.9, 0.8)
```

---

### Scene I/O and Timeline

```python
# Load and save
scene.load("/path/to/scene.duf")          # merge mode (does not clear existing scene)
scene.save("/path/to/output.duf")
scene.save_copy("/path/to/backup.duf")    # write copy; filename/dirty flag unchanged
print(scene.filename())
print(scene.needs_save())

# Timeline
print(scene.frame())
scene.set_frame(24)
print(scene.play_range())            # {"start": 0, "end": 240}
scene.set_play_range(0, 120)
scene.set_anim_range(0, 240)
print(scene.is_playing())
scene.loop_playback(True)
```

---

### Geometry

`DazGeometry` provides access to the raw mesh data of a node's shape.

```python
node = scene.find_node_by_label("My Prop")
geo  = node.geometry()

print(geo.num_vertices())
print(geo.num_faces())
print(geo.subdivision_level())
print(geo.tris_count(), geo.quads_count())

# Vertices (chunked — returns slice starting at offset)
verts = geo.vertices(start=0, count=1000)
# {"total": 5000, "start": 0, "vertices": [[x,y,z], …]}

# Faces (vertex indices per polygon)
faces = geo.face_vertex_indices(start=0, count=1000)
# {"total": 4800, "start": 0, "facets": [[v0,v1,v2,v3], …]}

# Normals
normals = geo.normals(start=0, count=5000)

# UV sets
print(geo.uv_set_count())
uvs = geo.uv_positions(uv_set=0, start=0, count=5000)

# Groups
print(geo.face_group_names())
print(geo.material_group_names())
```

---

### Advanced: Batch, Undo, and Async

#### Undo Groups

Wrap multiple changes in a single undo step visible in DAZ Studio's Edit menu:

```python
with scene.undo("Apply pose"):
    figure.find_bone("lShldrBend").set_local_rotation(0, 0, -60)
    figure.find_bone("rShldrBend").set_local_rotation(0, 0,  60)
    figure.find_modifier("PHMSmileOpen").set_value(0.5)
```

#### Batch Execution

`Batch` groups multiple DazScript snippets into a single HTTP round-trip:

```python
from dazpy import Batch

batch = Batch(client)
batch.add("(function(){ return Scene.getNumNodes(); })()")
batch.add("(function(){ return Scene.getNumSkeletons(); })()")
results = batch.execute()           # one HTTP request, list of ExecutionResult
print(results[0].value, results[1].value)

# BatchFuture — fire and collect later
future = batch.submit_async()       # returns BatchFuture
# ... do other work ...
results = future.collect()
```

#### Long-Running Operations

`execute_long` wraps the async submit/poll/collect cycle for operations like renders:

```python
from dazpy import execute_long

result = execute_long(
    client,
    script="App.getRenderMgr().doRender(); return 'done';",
    poll_interval=2.0,
    timeout=300.0,
)
print(result.value)
```

---

### Error Handling

All dazpy exceptions are in `dazpy.exceptions`:

```python
from dazpy import DazClient, DazScene
from dazpy.exceptions import (
    ConnectionError,       # DAZ Studio not reachable
    AuthenticationError,   # bad token or IP blocked
    ScriptSyntaxError,     # DazScript parse error
    ScriptRuntimeError,    # DazScript runtime exception
    TimeoutError,          # HTTP request timed out
    NodeNotFoundError,     # scene.find_node / find_skeleton raised
)

try:
    scene.find_skeleton_by_label("NonExistent")
except NodeNotFoundError as e:
    print(e)

try:
    client.execute("this is not valid { script")
except ScriptSyntaxError as e:
    print(e.request_id)    # correlate with server log
```

`ScriptRuntimeError` and `ScriptSyntaxError` both carry a `request_id` attribute
that matches the 8-character ID in the server's request log.

---

### Testing dazpy

The SDK ships with two test suites:

```bash
# Unit tests — no DAZ Studio needed (mock-based)
python tests_dazpy.py

# Integration tests — skip gracefully if server is down
python tests_dazpy_integration.py
```

Tests requiring a live DAZ Studio session are gated with `@skip_no_daz` and
silently skipped when the `Scene` global is unavailable.

---

## Getting the Plugin

There are two options for getting the plugin. For most users, Option A, downloading a pre-built release, is the easiest route. 

### A. Download a pre-built release

1. Browse to the latest stable release page: https://github.com/bluemoonfoundry/daz-script-server/releases/latest
2. Scroll down to the Assets section. Each release includes:
   - `DazScriptServer.dll` / `DazScriptServer.dylib` — the plugin
   - `dazpy-*.whl` — the Python SDK wheel (`pip install dazpy-*.whl`)
3. Download `DazScriptServer.dll` and copy it to the plugins folder in your DAZ Studio installation:
    - **Windows:** `C:\Program Files\DAZ 3D\DAZStudio4\plugins\`
    - **macOS:** `/Applications/DAZ 3D/DAZStudio4/plugins/`
    - Unsure where DAZ Studio is installed? Right-click its icon → Properties → Open File Location.

### B. Building it yourself from source

1. **Download the DAZ Studio SDK** from the [DAZ Developer portal](https://www.daz3d.com/daz-studio-4-5-sdk)

2. **Configure with CMake:**
   ```bash
   cmake -B build -S . -DDAZ_SDK_DIR="C:/path/to/DAZStudio4.5+ SDK"
   ```

3. **Build:**
   ```bash
   cmake --build build --config Release
   ```

   Output: `build/plugin/Release/DazScriptServer.dll` (Windows) or `build/plugin/DazScriptServer.dylib` (macOS)

### build.sh convenience script

`build.sh` auto-detects CMake and loads environment variables from `.env`.

**Commands** (first positional argument; defaults to `build`):

| Command | Description |
|---|---|
| `build` | Configure (if needed) and build (default) |
| `install` | Build and copy plugin to DAZ Studio plugins folder |
| `clean` | Delete the build directory and exit |
| `release <tag>` | Build plugin + dazpy wheel, create a GitHub release and attach both |

**Options** (flags, combinable with any command):

| Option | Description |
|---|---|
| `--clean` | Wipe the build directory before building |
| `--reconfigure` | Force CMake configure even if a cache already exists |
| `--debug` | Build Debug config instead of Release |
| `--verbose` | Pass `--verbose` to the CMake build step |
| `--title <title>` | Release title (`release` only; defaults to tag) |
| `--notes <text>` | Release notes text (`release` only) |
| `--update` | Update an existing release instead of creating a new one (`release` only) |
| `--no-wheel` | Skip building the dazpy wheel (`release` only) |
| `--help` | Show usage and exit |

```bash
./build.sh                                             # build
./build.sh build --clean --debug
./build.sh install --clean                             # DAZ Studio must not be running
./build.sh clean
./build.sh release v1.3.0 --title "v1.3.0" --notes "Bug fixes"
./build.sh release v1.3.0 --update                    # replace assets on existing release
./build.sh release v1.3.0 --no-wheel                  # plugin DLL only, skip wheel
```

### Installation

Copy the built plugin to DAZ Studio's plugins folder:

- **Windows:** `C:\Program Files\DAZ 3D\DAZStudio4\plugins\`
- **macOS:** `/Applications/DAZ 3D/DAZStudio4/plugins/`

**Or build and install in one step** (set `DAZ_STUDIO_EXE_DIR` in `.env` first):
```bash
./build.sh install

# Clean build + install
./build.sh install --clean
```

> **Note:** `install` requires DAZ Studio to be closed. The script detects if it is running and exits with a clear error rather than failing at link time.

---

## Starting the Server

1. Open DAZ Studio
2. Go to **Window → Panes → Daz Script Server**
3. Configure settings (see [Configuration](#-configuration) below)
4. Click **Start Server**

The server status will show "Running" with active requests counter when started successfully.

---

## ⚙️ Configuration

All settings are persisted via QSettings and restored between DAZ Studio sessions.

### Server Settings

| Setting | Default | Range | Description |
|---------|---------|-------|-------------|
| **Host** | `127.0.0.1` | - | IP address to bind to (`127.0.0.1` for localhost only, `0.0.0.0` for all interfaces) |
| **Port** | `18811` | 1024-65535 | Port number |
| **Timeout** | `30` seconds | 5-300 | Script execution timeout |
| **Auto-Start** | Disabled | - | Start server automatically when pane opens |

### 🔐 Authentication

| Setting | Default | Description |
|---------|---------|-------------|
| **Enable Authentication** | ✅ Enabled | Token-based authentication using cryptographically secure tokens (128-bit) |

**Token Security:**
- Auto-generated using OS crypto APIs (Windows: CryptoAPI, macOS/Linux: `/dev/urandom`)
- Stored in `~/.daz3d/dazscriptserver_token.txt`
- File permissions automatically set to `chmod 600` (owner-only) on Unix/macOS
- Copy token from UI using the **Copy** button
- Regenerate with **Regenerate** button if compromised
- ⚠️ **Disable at your own risk** - only on trusted networks

### 🛡️ IP Whitelist

| Setting | Default | Description |
|---------|---------|-------------|
| **Enable IP Whitelist** | ❌ Disabled | Restrict access to specific IP addresses |
| **Allowed IPs** | `127.0.0.1` | Comma-separated list (e.g., `127.0.0.1, 192.168.1.100`) |

- Exact match only (wildcards not supported in v1.2.0)
- Blocked IPs receive HTTP 403 Forbidden
- Checked before authentication (efficient)
- Essential for network-exposed deployments

### ⏱️ Rate Limiting

| Setting | Default | Range | Description |
|---------|---------|-------|-------------|
| **Enable Rate Limiting** | ❌ Disabled | - | Per-IP rate limiting to prevent abuse |
| **Max Requests** | `60` | 10-1000 | Maximum requests per time window |
| **Time Window** | `60` seconds | 10-300 | Time window in seconds |

- Uses sliding window algorithm for accuracy
- Separate tracking per IP address
- Exceeded IPs receive HTTP 429 Too Many Requests
- Logs violations with timestamp and client IP

### 🎛️ Advanced Limits

| Setting | Default | Range | Description |
|---------|---------|-------|-------------|
| **Max Concurrent Requests** | `10` | 5-50 | Maximum simultaneous requests |
| **Max Request Body Size** | `5` MB | 1-50 | Maximum request body size |
| **Max Script Text Length** | `1024` KB (1 MB) | 100-10240 | Maximum inline script size |

**Protection:**
- Prevents resource exhaustion
- Returns appropriate HTTP errors (413, 429)
- Use `scriptFile` for larger scripts

### 📊 Monitoring

- **Active Request Counter** - Real-time display: "Active Requests: 2 / 10"
- **Request Log** - Detailed log with:
  - Timestamps (HH:mm:ss)
  - Client IP addresses
  - Status codes (OK, ERR, WARN, AUTH FAILED, BLOCKED, RATE LIMIT)
  - Duration (milliseconds)
  - Request IDs (8-character UUID)
  - Script identifiers
- **Log Management** - Maximum 1000 lines, auto-remove old entries, "Clear Log" button

**Important:** Configuration changes (except auto-start) require stopping and restarting the server to take effect.

---

## 📡 API Reference

### Base URL
```
http://127.0.0.1:18811
```

### Authentication

All endpoints except `/status`, `/health`, and `/metrics` require authentication when enabled:

**Header Options:**
- `X-API-Token: YOUR_TOKEN_HERE`
- `Authorization: Bearer YOUR_TOKEN_HERE`

### HTTP Status Codes

| Code | Meaning |
|------|---------|
| `200` | Success (check `success` field in response) |
| `400` | Bad Request (malformed JSON, invalid parameters) |
| `401` | Unauthorized (missing or invalid token) |
| `403` | Forbidden (IP not whitelisted) |
| `413` | Payload Too Large (request body exceeds limit) |
| `429` | Too Many Requests (concurrent or rate limit exceeded) |

---

### `GET /status`

**Purpose:** Check if server is running
**Authentication:** Not required

**Response:**
```json
{
  "running": true,
  "version": "2.0.0"
}
```

---

### `GET /health`

**Purpose:** Health check for monitoring and load balancers
**Authentication:** Not required

**Response:**
```json
{
  "status": "ok",
  "version": "2.0.0",
  "running": true,
  "auth_enabled": true,
  "active_requests": 2,
  "uptime_seconds": 3600
}
```

---

### `GET /metrics`

**Purpose:** Request statistics and performance tracking
**Authentication:** Not required

**Response:**
```json
{
  "total_requests": 1523,
  "successful_requests": 1489,
  "failed_requests": 28,
  "auth_failures": 6,
  "active_requests": 2,
  "uptime_seconds": 86400,
  "success_rate_percent": 97.77
}
```

**Note:** Counters persist across DAZ Studio restarts (saved to QSettings).

---

### `POST /execute`

**Purpose:** Execute a DazScript and return the result
**Authentication:** Required (if enabled)

**Request Body:**

**Option 1: Inline script**
```json
{
  "script": "(function(){ return Scene.getNumNodes(); })()",
  "args": { "key": "value" }
}
```

**Option 2: Script file**
```json
{
  "scriptFile": "/absolute/path/to/script.dsa",
  "args": { "key": "value" }
}
```

**Parameters:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `script` | string | one of | Inline DazScript code (max configurable, default 1MB) |
| `scriptFile` | string | one of | Absolute path to `.dsa` file |
| `args` | object | optional | Arguments accessible via `getArguments()[0]` |

**Note:** If both `script` and `scriptFile` are provided, `scriptFile` takes precedence.

**Response:**
```json
{
  "success": true,
  "result": 42,
  "output": ["line 1", "line 2"],
  "error": null,
  "request_id": "a3f2b891"
}
```

**Response Fields:**

| Field | Description |
|-------|-------------|
| `success` | `true` if script executed without error |
| `result` | Script's return value, `null` on error |
| `output` | Lines printed via `print()` (max 10,000) |
| `error` | Error message with line number, or `null` |
| `request_id` | Unique 8-character ID for log correlation |

**Processing Order:**
1. Concurrent limit check
2. IP whitelist check (if enabled)
3. Rate limit check (if enabled)
4. Body size validation
5. Authentication (if enabled)
6. Input validation
7. Script execution

---

## 📦 Script Registry

The script registry allows you to register scripts once and execute them by name/ID on subsequent requests, avoiding retransmission of large script bodies.

**Key Features:**
- Session-only storage (cleared on DAZ Studio restart)
- Clients should re-register on HTTP 404
- Register, list, execute by ID, and delete operations
- Same response format as `/execute`

---

### `POST /scripts/register`

**Purpose:** Register or update a named script
**Authentication:** Required (if enabled)

**Request:**
```json
{
  "name": "scene-info",
  "description": "Return scene node count",
  "script": "(function(){ return { nodes: Scene.getNumNodes() }; })()"
}
```

**Parameters:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Script ID: 1-64 chars, `[A-Za-z0-9_-]` only |
| `script` | string | yes | DazScript source code |
| `description` | string | no | Human-readable description |

**Response:**
```json
{
  "success": true,
  "id": "scene-info",
  "registered_at": "2026-03-27T10:15:00",
  "updated": false
}
```

**Note:** Re-registering an existing name overwrites the script and sets `updated: true`.

---

### `GET /scripts`

**Purpose:** List all registered scripts
**Authentication:** Required (if enabled)

**Response:**
```json
{
  "scripts": [
    {
      "id": "scene-info",
      "description": "Return scene node count",
      "registered_at": "2026-03-27T10:15:00"
    }
  ],
  "count": 1
}
```

---

### `POST /scripts/:id/execute`

**Purpose:** Execute a registered script by ID
**Authentication:** Required (if enabled)

**Request:**
```json
{
  "args": { "label": "FN Ethan" }
}
```

**Response:** Same format as `POST /execute`

**Error Response (404):**
```json
{
  "success": false,
  "error": "Script not found: 'scene-info'"
}
```

**Handling 404:** Client should detect 404, re-register scripts, then retry.

---

### `DELETE /scripts/:id`

**Purpose:** Remove a script from the registry
**Authentication:** Required (if enabled)

**Response:**
```json
{
  "success": true,
  "id": "scene-info"
}
```

**Error Response (404):**
```json
{
  "success": false,
  "error": "Script not found: 'scene-info'"
}
```

---

## ⚡ Async Operations

For long-running scripts (renders, exports, batch jobs), use the async endpoints to avoid blocking the HTTP connection. Scripts still execute serially on DAZ Studio's main thread — async means the HTTP response is returned immediately while execution is queued.

**Typical async workflow:**

```python
import requests, time

BASE = "http://127.0.0.1:18811"
HEADERS = {"X-API-Token": token}

# 1. Submit asynchronously
r = requests.post(f"{BASE}/execute/async", headers=HEADERS,
                  json={"script": "App.getRenderMgr().doRender(); return 'done';"})
req_id = r.json()["request_id"]

# 2. Poll until complete
while True:
    status = requests.get(f"{BASE}/requests/{req_id}/status", headers=HEADERS).json()
    if status["status"] in ("completed", "failed", "cancelled"):
        break
    time.sleep(2)

# 3. Fetch result
result = requests.get(f"{BASE}/requests/{req_id}/result", headers=HEADERS).json()
print(result["result"])
```

**Or use `?wait=true` to long-poll in one step:**

```python
result = requests.get(f"{BASE}/requests/{req_id}/result?wait=true&timeout=300",
                      headers=HEADERS).json()
```

---

### `POST /execute/async`

**Purpose:** Submit an inline script or host-side script file for asynchronous execution
**Authentication:** Required (if enabled)

**Request Body:** Same as `POST /execute`, plus optional `reportFile` for
structured job observation.

`reportFile` is an absolute host-side path to a JSONL file owned by this job.
The server truncates it when the request is accepted. The script may then write
one JSON object per line. The path is injected into the script's argument object
as reserved field `getArguments()[0].__dssReportFile`, so callers do not have to
duplicate it inside `args`:

```jsonl
{"type":"progress","value":0.25,"current":1,"total":4,"phase":"render","message":"Plate 1"}
{"type":"log","level":"info","message":"Loaded scene"}
{"type":"output","path":"C:/renders/run/plate-1.png","kind":"image","label":"plate"}
```

Progress events require either `value` (0–1) or `current` plus `total`. Log
events require `message`. Output events require `path`; repeating a path updates
that manifest entry. A `manifest` event may provide an `outputs` array. Use a
unique report file for every job.
`reportFile` may not be the submitted `scriptFile`, because the server owns and
truncates the former before the job is queued.

DAZ Studio 6 ingests report events from polling workers, so progress, logs, and
outputs are visible while the main thread is occupied by the script. DAZ Studio
4's JSON parser is main-thread-only; Studio 4 therefore ingests the final report
after execution returns and does not expose report-driven progress while the job
is still running.

**Response (immediate):**
```json
{
  "request_id": "a3f2b891",
  "status": "queued",
  "submitted_at": "2026-04-09T10:15:00"
}
```

---

### `POST /scripts/:id/async`

**Purpose:** Submit a registered script for asynchronous execution
**Authentication:** Required (if enabled)

**Request Body:** Same as `POST /scripts/:id/execute`

**Response (immediate):** Same shape as `POST /execute/async`

---

### `GET /requests/:id/status`

**Purpose:** Poll the status of an async request
**Authentication:** Required (if enabled)

**Response:**
```json
{
  "request_id": "a3f2b891",
  "status": "running",
  "progress": 0.25,
  "observation": {
    "progress": {"value": 0.25, "current": 1, "total": 4, "phase": "render"},
    "log_tail": [{"level": "info", "source": "script", "message": "Loaded scene"}],
    "log_total": 1,
    "log_truncated": false,
    "output_manifest": {"count": 0, "outputs": []},
    "report_file": "C:/renders/run/job.jsonl"
  },
  "elapsed_ms": 1240,
  "queue_position": 0
}
```

**Status values:** `queued`, `running`, `completed`, `failed`, `cancelled`

`queue_position` is only meaningful when `status` is `queued`.

---

### `GET /requests/:id/result`

**Purpose:** Fetch the final result of an async request
**Authentication:** Required (if enabled)

**Query Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `wait` | `false` | Block until the request completes |
| `timeout` | `300` | Max seconds to wait when `wait=true` |

**Response (completed):**
```json
{
  "success": true,
  "result": "done",
  "output": [],
  "error": null,
  "request_id": "a3f2b891",
  "duration_ms": 45230,
  "completed_at": "2026-04-09T10:15:47",
  "status": "completed"
}
```

Completed, failed, and cancelled results also include `observation`. The log
tail is capped at the newest 100 entries; `log_total` and `log_truncated` make
the loss explicit. Ordinary captured `print()` output is folded into the same
tail at completion while remaining available in the legacy `output` field.

Returns HTTP 404 if the request ID is unknown or has been purged (TTL: 1 hour).

---

### `DELETE /requests/:id`

**Purpose:** Cancel a queued or running async request
**Authentication:** Required (if enabled)

**Cancellation behaviour:**
- `queued` → removed from queue immediately
- `running` → cancel flag set + `killRender()` called; DAZ Studio honours the flag when the script returns

**Response:**
```json
{
  "request_id": "a3f2b891",
  "status": "cancelled",
  "cancelled_at": "2026-04-09T10:15:05"
}
```

---

### `GET /requests`

**Purpose:** List all active and recently completed async requests
**Authentication:** Required (if enabled)

**Response:**
```json
{
  "requests": [
    {
      "request_id": "a3f2b891",
      "status": "running",
      "submitted_at": "2026-04-09T10:15:00",
      "elapsed_ms": 1240
    }
  ],
  "total": 1,
  "queued": 0,
  "running": 1,
  "completed": 0
}
```

**Note:** Completed, failed, and cancelled requests are automatically purged after 1 hour.

---

## 🔔 Scene Events (SSE)

`GET /scene/events` opens a persistent HTTP connection and streams DAZ Studio scene-change notifications as **Server-Sent Events**. Each event is a UTF-8 line in the form:

```
data: {"type":"node.added","ts":1716307200123,"data":{"node_id":"0x1a2b3c4d","node_name":"Genesis 9","node_type":"DzFigure"}}

```

A `:keepalive` comment is sent every 3 seconds of idle time so clients can detect disconnects without sending an event:

```
:keepalive

```

The connection stays open until the client disconnects or the server is stopped. All configured security checks (auth, IP whitelist) apply.

---

### `GET /scene/events`

**Purpose:** Subscribe to real-time scene-change notifications
**Authentication:** Required (if enabled)

**Query Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `filter` | _(all)_ | Comma-separated list of event categories to receive. Omit to receive all. |

**Filter categories:**

| Value | Events included |
|-------|----------------|
| `node` | `node.added`, `node.removed` |
| `skeleton` | `skeleton.added`, `skeleton.removed` |
| `light` | `light.added`, `light.removed` |
| `camera` | `camera.added`, `camera.removed` |
| `selection` | `selection.list_changed`, `selection.primary_changed` |
| `scene` | `scene.loading`, `scene.loaded`, `scene.saving`, `scene.saved`, `scene.clear_starting`, `scene.cleared` |
| `time` | `time.changed` _(debounced 150 ms)_, `playback.started`, `playback.finished` |
| `render` | `render.started`, `render.finished` |

**Response headers:**
```
Content-Type: text/event-stream
Cache-Control: no-cache
Transfer-Encoding: chunked
```

---

### Event reference

Every event shares the same envelope:

```json
{
  "type": "node.added",
  "ts": 1716307200123,
  "data": { ... }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | Dot-namespaced event name (see table below) |
| `ts` | integer | Unix timestamp in milliseconds |
| `data` | object | Event-specific payload (see below) |

**Node payload** (for `node.*`, `skeleton.*`, `light.*`, `camera.*`):

```json
{
  "node_id":   "0x1a2b3c4d",
  "node_name": "Genesis 9",
  "node_type": "DzFigure"
}
```

`node_id` is a session-stable hex pointer. Use it to correlate add/remove events for the same node within a session.

**Scene-save payload** (`scene.saving`, `scene.saved`):

```json
{ "filename": "/Users/me/Documents/MyScene.duf" }
```

**Time payload** (`time.changed`):

```json
{ "time_ticks": 4800, "time_secs": 1.0 }
```

`time.changed` is debounced — during playback it fires at most once per 150 ms regardless of frame rate.

**Empty payload** — all other events (`node.removed`, `selection.*`, `scene.loading`, `scene.loaded`, `scene.cleared`, `playback.*`, `render.*`):

```json
{}
```

**Full event type table:**

| `type` | Category | Payload fields |
|--------|----------|----------------|
| `node.added` | `node` | `node_id`, `node_name`, `node_type` |
| `node.removed` | `node` | `node_id`, `node_name`, `node_type` |
| `skeleton.added` | `skeleton` | `node_id`, `node_name`, `node_type` |
| `skeleton.removed` | `skeleton` | `node_id`, `node_name`, `node_type` |
| `light.added` | `light` | `node_id`, `node_name`, `node_type` |
| `light.removed` | `light` | `node_id`, `node_name`, `node_type` |
| `camera.added` | `camera` | `node_id`, `node_name`, `node_type` |
| `camera.removed` | `camera` | `node_id`, `node_name`, `node_type` |
| `selection.list_changed` | `selection` | _(empty)_ |
| `selection.primary_changed` | `selection` | `node_id`, `node_name`, `node_type` (or `{}` if deselected) |
| `scene.loading` | `scene` | _(empty)_ |
| `scene.loaded` | `scene` | _(empty)_ |
| `scene.saving` | `scene` | `filename` |
| `scene.saved` | `scene` | `filename` |
| `scene.clear_starting` | `scene` | _(empty)_ |
| `scene.cleared` | `scene` | _(empty)_ |
| `time.changed` | `time` | `time_ticks`, `time_secs` |
| `playback.started` | `time` | _(empty)_ |
| `playback.finished` | `time` | _(empty)_ |
| `render.started` | `render` | _(empty)_ |
| `render.finished` | `render` | _(empty)_ |

---

### Scene Events — Client Examples

#### curl

```bash
TOKEN=$(cat ~/.daz3d/dazscriptserver_token.txt)

# All events
curl -N -H "X-API-Token: $TOKEN" http://127.0.0.1:18811/scene/events

# Node and scene events only
curl -N -H "X-API-Token: $TOKEN" \
  "http://127.0.0.1:18811/scene/events?filter=node,scene"
```

#### Python — requests (no extra dependencies)

```python
import requests, json, os

token = open(os.path.expanduser("~/.daz3d/dazscriptserver_token.txt")).read().strip()

with requests.get(
    "http://127.0.0.1:18811/scene/events",
    headers={"X-API-Token": token},
    stream=True,
    timeout=None,
) as resp:
    resp.raise_for_status()
    for raw in resp.iter_lines():
        if not raw or raw.startswith(b":"):  # skip keepalives and blank lines
            continue
        if raw.startswith(b"data: "):
            event = json.loads(raw[6:])
            print(f"{event['type']}: {event['data']}")
```

#### Python — sseclient (cleaner API)

```bash
pip install sseclient-py
```

```python
import sseclient, requests, os

token = open(os.path.expanduser("~/.daz3d/dazscriptserver_token.txt")).read().strip()

response = requests.get(
    "http://127.0.0.1:18811/scene/events?filter=node,selection,scene",
    headers={"X-API-Token": token},
    stream=True,
)
client = sseclient.SSEClient(response)

for event in client.events():
    import json
    data = json.loads(event.data)
    print(data["type"], data["data"])
```

#### JavaScript — EventSource (browser)

The browser's built-in `EventSource` does not support custom headers, so pass the token as a query parameter instead (requires auth to accept it — which DazScriptServer does not currently support). Use `fetch` with `ReadableStream` for authenticated SSE from a browser:

```javascript
const token = "your-token-here";

const response = await fetch(
  "http://127.0.0.1:18811/scene/events?filter=node,scene",
  { headers: { "X-API-Token": token } }
);

const reader = response.body.getReader();
const decoder = new TextDecoder();
let buffer = "";

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  buffer += decoder.decode(value, { stream: true });

  const lines = buffer.split("\n");
  buffer = lines.pop();               // keep incomplete last line

  for (const line of lines) {
    if (line.startsWith("data: ")) {
      const event = JSON.parse(line.slice(6));
      console.log(event.type, event.data);
    }
  }
}
```

#### Node.js

```javascript
const http = require("http");
const fs   = require("fs");
const os   = require("os");

const token = fs.readFileSync(`${os.homedir()}/.daz3d/dazscriptserver_token.txt`, "utf8").trim();

const req = http.request(
  { hostname: "127.0.0.1", port: 18811, path: "/scene/events", method: "GET",
    headers: { "X-API-Token": token, Accept: "text/event-stream" } },
  (res) => {
    let buf = "";
    res.on("data", (chunk) => {
      buf += chunk.toString();
      const lines = buf.split("\n");
      buf = lines.pop();
      for (const line of lines) {
        if (line.startsWith("data: ")) {
          const event = JSON.parse(line.slice(6));
          console.log(event.type, event.data);
        }
      }
    });
  }
);
req.end();
```

---

### Notes

- **Multiple concurrent subscribers** are supported — each `GET /scene/events` request is independent.
- **High-frequency signals** (`timeChanging` during playback, `nodeSelectionListChanged` during multi-select) are debounced before dispatch so clients are not flooded.
- **Server stop** closes all open SSE connections cleanly; clients should reconnect automatically.
- **Reverse proxy:** If using nginx in front of the server, add `proxy_buffering off` and `proxy_http_version 1.1` to the SSE location block (see [Reverse Proxy Setup](#reverse-proxy-setup-https)).

---

## 🔒 Security Features

### Built-In Security

- **Cryptographically Secure Tokens** - 128-bit entropy using OS crypto APIs
- **IP Whitelist** - Exact IP matching for access control
- **Per-IP Rate Limiting** - Sliding window algorithm prevents brute force
- **Input Validation** - Request body, script size, and file path validation
- **Audit Logging** - All requests, auth failures, and blocked IPs logged
- **Concurrent Request Limiting** - Prevents resource exhaustion attacks
- **File Permissions** - Automatic `chmod 600` on token files (Unix/macOS)

### What's NOT Included

- **HTTPS/TLS** - Use a reverse proxy (nginx, Apache) for encryption
- **X-Forwarded-For** - IP whitelist uses direct TCP connection IP only
- **User Accounts** - Single token for all authenticated access
- **Persistent Sessions** - Each request is independently authenticated

---

## 🛡️ Security Best Practices

### Localhost-Only Access (Most Secure)

For controlling DAZ Studio from the same machine:

1. ✅ Keep host set to `127.0.0.1` (default)
2. ✅ Keep authentication enabled (default)
3. ✅ Protect token file (`~/.daz3d/dazscriptserver_token.txt`)
4. ℹ️ IP whitelist and rate limiting are optional

### Network Access (Remote Clients)

For controlling DAZ Studio from other machines:

1. ✅ Change host to `0.0.0.0` (accept external connections)
2. ✅ **Required:** Enable IP whitelist with specific allowed IPs
3. ✅ **Required:** Keep authentication enabled
4. ✅ **Recommended:** Enable rate limiting (e.g., 60 requests / 60 seconds)
5. ✅ **Recommended:** Use firewall rules to restrict port access
6. ⚠️ **Never** expose to the public internet without additional security (VPN, reverse proxy with HTTPS)

### Token Security

| Do | Don't |
|----|-------|
| ✅ Treat token like a password | ❌ Commit to version control |
| ✅ Copy from UI or token file | ❌ Share publicly or in logs |
| ✅ Use "Regenerate" if compromised | ❌ Email or message token |
| ✅ Set `chmod 600` on Unix/macOS | ❌ Use same token across environments |
| ✅ Restrict file access on Windows | ❌ Disable auth on untrusted networks |

**Token File Locations:**
- Unix/macOS: `~/.daz3d/dazscriptserver_token.txt`
- Windows: `%USERPROFILE%\.daz3d\dazscriptserver_token.txt`

### Monitoring & Auditing

- ✅ Check request log regularly for suspicious activity
- ✅ Monitor `/metrics` for high failure rates or auth failures
- ✅ Set up alerts for unusual patterns (rate limit violations, auth failures)
- ✅ Review BLOCKED and AUTH FAILED entries in the log

---

## 💻 Client Examples

The repository includes example clients in multiple languages.

### Python — dazpy SDK

**Install:**
```bash
pip install dazpy-*.whl      # from the release page
# or: pip install -e .       # from source
```

**Files:**
- `tests_dazpy.py` — SDK unit tests (mock-based, no server needed)
- `tests_dazpy_integration.py` — SDK integration tests (requires running server)

**Usage:**
```python
from dazpy import DazClient, DazScene

client = DazClient()          # auto-loads token
scene  = DazScene(client)

# Inspect scene
print(scene.num_nodes(), "nodes")
for node in scene.nodes():
    print(node.label(), node.position())

# Pose a figure
figure = scene.find_skeleton_by_label("Genesis 9")
with scene.undo("T-pose arms"):
    figure.find_bone("lShldrBend").set_local_rotation(0, 0, -90)
    figure.find_bone("rShldrBend").set_local_rotation(0, 0,  90)

# Adjust morphs
smile = figure.find_modifier("PHMSmileOpen")
smile.set_value(0.75)

# Render asynchronously
from dazpy import execute_long
result = execute_long(client, "App.getRenderMgr().doRender(); return 'done';",
                      timeout=300.0)
```

### Python — Raw HTTP

**Files:**
- `test-simple.py` — Basic raw-HTTP client
- `tests.py` — Comprehensive server integration test suite (72 tests)
- `test-performance.py` — Performance benchmarks and load tests

**Usage:**
```python
import requests
import os

token_path = os.path.expanduser("~/.daz3d/dazscriptserver_token.txt")
with open(token_path) as f:
    token = f.read().strip()

response = requests.post(
    "http://127.0.0.1:18811/execute",
    headers={"X-API-Token": token},
    json={"script": "(function(){ return 'Hello!'; })()", "args": {}}
)
print(response.json())
```

### JavaScript/Node.js

**File:** `test-client.js`

**Requirements:** Node.js 18+ (built-in fetch) or `npm install node-fetch`

**Usage:**
```javascript
const fs = require('fs');
const os = require('os');

const tokenPath = `${os.homedir()}/.daz3d/dazscriptserver_token.txt`;
const token = fs.readFileSync(tokenPath, 'utf8').trim();

const response = await fetch('http://127.0.0.1:18811/execute', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'X-API-Token': token
  },
  body: JSON.stringify({
    script: "(function(){ return 'Hello from Node.js!'; })()"
  })
});

const result = await response.json();
console.log(result);
```

### PowerShell

**File:** `test-client.ps1`

**Compatible:** PowerShell 5.1+ and PowerShell Core 6+

**Usage:**
```powershell
$tokenPath = "$env:USERPROFILE\.daz3d\dazscriptserver_token.txt"
$token = Get-Content $tokenPath

$body = @{
    script = "(function(){ return 'Hello there from PowerShell!'; })()"
} | ConvertTo-Json

$response = Invoke-RestMethod `
    -Uri "http://127.0.0.1:18811/execute" `
    -Method Post `
    -Headers @{"X-API-Token" = $token} `
    -ContentType "application/json" `
    -Body $body

$response
```

**Running examples:**
```bash
# dazpy unit tests (no server needed)
python tests_dazpy.py

# dazpy integration tests (requires server running)
python tests_dazpy_integration.py

# Server integration tests
python tests.py

# Python smoke tests
python test-simple.py

# Performance benchmarks and load tests
python test-performance.py
python test-performance.py --quick   # fewer iterations, suitable for CI

# Node.js
node test-client.js

# PowerShell
powershell -ExecutionPolicy Bypass -File test-client.ps1
# Or PowerShell Core:
pwsh test-client.ps1
```

All examples include error handling, argument passing, and output capture.

---

## Writing Scripts

### Accessing Arguments

Arguments are available via `getArguments()[0]`:

```javascript
var args = getArguments()[0];
print("Hello, " + args.name);
return args.value * 2;
```

### Returning Values

Wrap scripts in an IIFE (Immediately Invoked Function Expression):

```javascript
(function(){
    var node = Scene.findNodeByLabel("FN Ethan");
    return {
        label: node.getLabel(),
        position: node.getWSPos()
    };
})()
```

### Error Handling

Throw errors to populate the `error` field:

```javascript
var args = getArguments()[0];
if (!args.label) {
    throw new Error("label is required");
}

var node = Scene.findNodeByLabel(args.label);
if (!node) {
    throw "Node not found: " + args.label;
}

return node.getLabel();
```

### Using Include

Use `scriptFile` (not inline `script`) for scripts that use `include()`:

```javascript
// File: /path/to/main.dsa
var includeDir = DzFile(getScriptFileName()).path();
include(includeDir + "/utils.dsa");

var args = getArguments()[0];
return myUtilFunction(args);
```

**Request:**
```json
{
  "scriptFile": "/path/to/main.dsa",
  "args": { "value": 42 }
}
```

### Script Registry Pattern

Register once, call many times:

```python
import requests
import os

token_path = os.path.expanduser("~/.daz3d/dazscriptserver_token.txt")
with open(token_path) as f:
    token = f.read().strip()

BASE = "http://127.0.0.1:18811"
HEADERS = {"X-API-Token": token}

def register_scripts():
    """Register all scripts on startup or after 404."""
    requests.post(f"{BASE}/scripts/register", headers=HEADERS, json={
        "name": "node-count",
        "script": "(function(){ return Scene.getNumNodes(); })()"
    })

def call_script(name, args=None):
    """Execute a registered script by name."""
    r = requests.post(
        f"{BASE}/scripts/{name}/execute",
        headers=HEADERS,
        json={"args": args or {}}
    )

    # Handle DAZ Studio restart (registry cleared)
    if r.status_code == 404:
        register_scripts()
        r = requests.post(
            f"{BASE}/scripts/{name}/execute",
            headers=HEADERS,
            json={"args": args or {}}
        )

    r.raise_for_status()
    return r.json()["result"]

# Initialize
register_scripts()

# Use
node_count = call_script("node-count")
print(f"Scene has {node_count} nodes")
```

### Rendering Example

```javascript
(function(){
    var args = getArguments()[0];

    // Load scene
    Scene.load(args.scenePath);

    // Configure render settings
    var renderMgr = App.getRenderMgr();
    var renderOptions = renderMgr.getRenderOptions();
    renderOptions.setImageFilename(args.outputPath);
    renderOptions.setImageSize(args.width, args.height);

    // Trigger render (blocks until complete)
    renderMgr.doRender(renderOptions);

    return { status: "complete", output: args.outputPath };
})()
```

**Note:** Renders block the request until complete. Use appropriate timeout settings (30-300 seconds).

---

## 🔧 Troubleshooting

### Server Won't Start

**"Port already in use" or "Failed to bind":**
- Another application is using the port
- Check if another DAZ Studio instance is running the plugin
- Try a different port number
- Check what's using the port:
  - Windows: `netstat -ano | findstr :18811`
  - macOS/Linux: `lsof -i :18811` or `netstat -an | grep 18811`

**Server starts but immediately stops:**
- Check DAZ Studio log for error messages
- Verify permissions to bind to the configured host/port
- Ports < 1024 require root privileges (use ports > 1024)

### Connection Refused

**Cannot connect from localhost:**
- Verify server is running (check UI status)
- Verify correct port (default: 18811)
- Check host is `127.0.0.1` or `0.0.0.0`
- Firewall may be blocking (add exception for DAZ Studio)

**Cannot connect from remote machine:**
- Verify host is `0.0.0.0` (not `127.0.0.1`)
- Check IP whitelist includes client IP
- Verify firewall allows incoming connections on the port
- Verify network routing between client and server

### Authentication Errors (HTTP 401)

**"Invalid or missing authentication token":**
- Verify token file exists: `~/.daz3d/dazscriptserver_token.txt`
- Copy token exactly from UI or file (no extra spaces)
- Use correct header: `X-API-Token: <token>` or `Authorization: Bearer <token>`
- If token file is corrupted, use "Regenerate" button
- Verify authentication is enabled in UI

### HTTP 403 Forbidden

**"IP not whitelisted":**
- IP whitelist is enabled and your IP is not in the list
- Add client IP to whitelist (comma-separated)
- Check actual IP (may differ due to NAT/proxy)
- Temporarily disable IP whitelist for testing

### HTTP 429 Too Many Requests

**"Rate limit exceeded":**
- Per-IP rate limit exceeded
- Wait for time window to expire (default: 60 seconds)
- Increase max requests or time window
- Temporarily disable rate limiting for testing

**"Maximum concurrent requests limit reached":**
- Too many scripts running simultaneously
- Wait for requests to complete
- Increase max concurrent requests
- Optimize scripts for faster execution
- Add delays between requests in client

### HTTP 413 Payload Too Large

**"Request body too large":**
- Request exceeds configured max (default: 5MB)
- Increase max body size in Advanced Limits
- For large scripts, use `scriptFile` instead of inline `script`

### Script Execution Errors

**"Script execution failed" or error in response:**
- Check `error` field for details (includes line number)
- Verify script syntax is valid DazScript
- Check referenced files/assets exist
- Review `output` field for print statements
- Test script manually in DAZ Studio Script IDE first

**Script times out:**
- Script exceeds timeout (default: 30 seconds)
- Increase timeout in configuration (max: 300 seconds)
- Optimize script performance
- Break long operations into multiple smaller requests

### Token File Issues

**Token file not created:**
- Plugin may lack write permissions to home directory
- Manually create `~/.daz3d/` directory
- Windows: `%USERPROFILE%\.daz3d\`
- Check DAZ Studio log for permission errors

**Token file permissions warning (Unix/macOS):**
- Plugin automatically sets `chmod 600`
- If warning persists: `chmod 600 ~/.daz3d/dazscriptserver_token.txt`

---

## ❓ Frequently Asked Questions

### Is this safe to use?

The plugin is designed with security in mind:
- ✅ Cryptographically secure API tokens
- ✅ Optional IP whitelist and rate limiting
- ✅ Input validation and size limits
- ✅ Audit logging of all requests

**However:** Any client with a valid token can execute arbitrary DazScript code with full access to your DAZ Studio scene, file system (within script permissions), and system resources. **Treat your API token like a password** and only share it with trusted applications.

### Can I use this in production?

**Yes!** This plugin is production-ready:
- Concurrent request limiting prevents resource exhaustion
- Rate limiting prevents abuse
- Health and metrics endpoints for monitoring
- Configurable timeouts and limits
- Comprehensive error handling and logging

Many users run this plugin 24/7 for batch rendering, asset processing, and integration workflows.

### What's the performance impact?

**Idle:** Negligible CPU usage when not processing requests.

**Under load:** Performance depends on your scripts. The plugin adds < 10ms overhead per request. The limiting factor is usually DazScript execution time and DAZ Studio's single-threaded scene graph operations.

### Can I run multiple instances?

No. Each DAZ Studio process can only load the plugin once.

**Alternatives:**
- Run multiple DAZ Studio instances on different ports (separate processes)
- Use concurrent request limit for multiple simultaneous requests in one instance

### Does this work with DAZ Studio CLI/headless mode?

The plugin requires DAZ Studio GUI (it's a pane plugin). For headless automation, run DAZ Studio in a virtual display environment:
- Linux: Xvfb
- Windows: Hidden window

### Can I execute multiple scripts in parallel?

Yes, up to the configured concurrent request limit (default: 10).

**Important notes:**
- All scripts execute on DAZ Studio's main thread (SDK requirement)
- Scripts are executed serially, not truly in parallel
- The concurrent limit prevents too many requests from queuing
- Heavy scene operations may block other requests

### What DazScript features are supported?

**All standard DazScript features work:**
- Scene graph manipulation (load, modify, render)
- File I/O operations
- Include/import of other scripts (use `scriptFile`)
- App objects and APIs
- Print statements (captured in `output` array)

The only difference from manual script execution is that arguments are passed via the `args` JSON object instead of command-line parameters.

### How do I debug scripts?

1. **Use `print()` statements** - Captured in response `output` array
2. **Check the `error` field** - Includes line numbers
3. **Test manually first** - Run in DAZ Studio Script IDE
4. **Check UI request log** - Shows status and duration
5. **Use `request_id`** - Correlate requests between client and server logs

### Can I trigger renders?

**Yes!** Execute any DazScript that renders:

```javascript
(function(){
    var args = getArguments()[0];
    Scene.load(args.scenePath);

    var renderMgr = App.getRenderMgr();
    var renderOptions = renderMgr.getRenderOptions();
    renderOptions.setImageFilename(args.outputPath);

    renderMgr.doRender(renderOptions);
    return "Render complete";
})()
```

**Note:** Renders block the request until complete. Use appropriate timeout settings.

### How do I upgrade to a new version?

1. Stop the server in DAZ Studio
2. Close DAZ Studio
3. Replace the plugin DLL/dylib in plugins folder
4. Restart DAZ Studio
5. Start the server

Your API token and settings persist across upgrades (stored separately).

### Where are settings stored?

**Settings (QSettings):**
- Windows: Registry key `HKEY_CURRENT_USER\Software\DAZ 3D\DazScriptServer`
- macOS: `~/Library/Preferences/com.daz3d.DazScriptServer.plist`
- Linux: `~/.config/DAZ 3D/DazScriptServer.conf`

**API Token:**
- All platforms: `~/.daz3d/dazscriptserver_token.txt`

---

## Advanced Topics

### Performance Tuning

**For high-throughput scenarios:**
- Increase max concurrent requests (default: 10, max: 50)
- Increase timeout for long-running scripts
- Enable rate limiting to prevent monopolization
- Monitor `/metrics` endpoint for bottlenecks

**For resource-constrained environments:**
- Decrease max concurrent requests
- Decrease max body size and script length
- Decrease timeout to prevent blocking

### Integration Patterns

**Health Check / Polling:**
```python
import requests
import time

# Wait for server to be ready
while True:
    try:
        response = requests.get("http://localhost:18811/health")
        if response.json()["running"]:
            break
    except:
        time.sleep(1)
```

**Batch Processing with Retries:**
```python
import requests
import time

def process_batch(items, token):
    for item in items:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                result = execute_script(item, token)
                log_success(item, result)
                break
            except requests.HTTPError as e:
                if e.response.status_code == 429:
                    time.sleep(5)  # Wait for rate limit
                elif attempt == max_retries - 1:
                    log_error(item, e)
                else:
                    continue
```

**Docker/Kubernetes Health Probe:**
```bash
curl -f http://localhost:18811/health || exit 1
```

### Reverse Proxy Setup (HTTPS)

For production deployments requiring HTTPS, use a reverse proxy:

**nginx example:**
```nginx
server {
    listen 443 ssl;
    server_name daz-api.example.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    # SSE event stream — must disable buffering so events reach clients immediately
    location /scene/events {
        proxy_pass http://127.0.0.1:18811;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_http_version 1.1;        # required for chunked transfer encoding
        proxy_buffering off;           # disable buffering for SSE
        proxy_cache off;
        proxy_read_timeout 3600s;      # keep connection alive for long-lived streams
        chunked_transfer_encoding on;
    }

    location / {
        proxy_pass http://127.0.0.1:18811;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;  # For long-running scripts
    }
}
```

**Important:** The current version does not parse `X-Forwarded-For` headers. IP whitelist and rate limiting will see the reverse proxy's IP, not the original client IP. This is a known limitation.

### Deployment Checklist

When deploying to production:

- [ ] Enable authentication (default)
- [ ] Enable IP whitelist with specific allowed IPs
- [ ] Enable rate limiting (e.g., 60 requests / 60 seconds)
- [ ] Set appropriate concurrent request limit for workload
- [ ] Configure timeout based on expected script duration
- [ ] Secure token file permissions (`chmod 600` on Unix/macOS)
- [ ] Set up monitoring on `/health` and `/metrics` endpoints
- [ ] Configure firewall rules to restrict port access
- [ ] Test failover behavior (DAZ Studio crashes/restarts)
- [ ] Document token rotation procedure for team
- [ ] Consider HTTPS via reverse proxy for network exposure

---

## Contributing

Contributions are welcome! See areas for improvement:

**Security:**
- X-Forwarded-For support for reverse proxy deployments
- Wildcard IP matching (e.g., `192.168.1.*`)
- Per-endpoint authentication policies
- Token expiration and automatic rotation

**Features:**
- Per-node property/transform change events in SSE stream (currently scene-level only)
- Webhook callbacks — register a URL to receive HTTP POST on scene events (alternative to persistent SSE connection)
- Script result caching
- Request queueing with priorities
- Multiple API tokens with labels
- CORS header configuration

**Observability:**
- Prometheus metrics endpoint format
- Structured logging (JSON)
- Distributed tracing support

**Developer Experience:**
- Pre-built binaries for Windows/macOS
- Docker image with DAZ Studio and plugin
- More example clients (Go, Rust, C#)

Open a GitHub issue to request features or report bugs.

### Development

For plugin development, see `CLAUDE.md` for detailed architecture notes and development guidelines.

---

## License & Attribution

This project is provided under the terms of the AGPL v3 license for use with DAZ Studio.

**Dependencies:**
- [cpp-httplib](https://github.com/yhirose/cpp-httplib) - Header-only HTTP library (AGPL v3 License)
- [DAZ Studio SDK](https://www.daz3d.com/daz-studio-4-5-sdk) - Required for building

**Platform APIs:**
- Windows: CryptoAPI for secure random number generation
- macOS/Linux: `/dev/urandom` for secure random number generation

**Authors:**
- Original implementation: Blue Moon Foundry
- Production-ready improvements: BMF and Community contributors

For questions, issues, or feature requests, please open an issue on GitHub.
