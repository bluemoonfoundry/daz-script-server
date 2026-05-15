# dazpy SDK — Implementation Roadmap

This document is a self-contained punchlist for completing the dazpy SDK.
Each session should read this file, pick one section, implement it, run the
test suites, then check the item off.

---

## Context

`dazpy/` is a Python SDK that drives DAZ Studio by sending DazScript to a
local HTTP server (the DazScriptServer plugin at `127.0.0.1:18811`).

**Key facts for every session:**
- The DAZ Studio global is `Scene` (not `dzScene`).
- `App` is the application object.
- Scripts must be wrapped in an IIFE: `(function(){ ... })()`
- All user strings pass through `json.dumps()` for injection safety — see
  `_script_builder.py:ScriptBuilder.escape_string()`.
- `DazElement.get_property(label)` / `set_property(label, value)` are the
  generic fallback for anything not wrapped explicitly.
- Unit tests live in `tests_dazpy.py` (mock-based, no server needed).
- Integration tests live in `tests_dazpy_integration.py` (skip gracefully
  when server is down; further skip with `@skip_no_daz` when `Scene` global
  is unavailable).

**Run tests:**
```
python tests_dazpy.py
python tests_dazpy_integration.py
```

**DAZ API reference:** use the `mcp__daz-api__get_class_details` MCP tool,
e.g. `get_class_details("DzSkeleton")`.

---

## Bugs to fix first (before adding new features)

### B1 — `DazNode.rotation` drops quaternion `w`
**File:** `dazpy/_node.py`  
`getWSRot()` returns a `DzQuat`. The current script does:
```js
var r = _node.getWSRot(); return {x: r.x, y: r.y, z: r.z};
```
This silently discards `w`, making the value geometrically meaningless.  
**Fix:** Return `{x, y, z, w}` (full quaternion), OR convert to Euler angles
using the node's rotation order:
```js
var r = _node.getWSRot(); return {x: r.x, y: r.y, z: r.z, w: r.w};
```
Add a unit test and an integration test asserting `w` is present.

### B2 — `DazNode.scale` is a misleading scalar
**File:** `dazpy/_node.py`  
`getScaleControl().getValue()` is the *general* (uniform) scale float.
Per-axis scale lives on `getXScaleControl()` etc.  
**Fix:** Rename to `general_scale`. Add `scale` as a dict property returning
`{x, y, z, general}` using all four controls.  
Update any integration test that asserts `scale` type.

### B3 — `DazCamera` and `DazLight` use property-label lookup for direct properties
**File:** `dazpy/_camera.py`, `dazpy/_light.py`  
`focal_length` uses `get_property("Focal Length")` but `DzCamera` exposes
`focalLength` as a direct JS property (no label lookup needed, faster, locale-safe).
Same for `frame_width` → `frameWidth`.  
**Fix:** Use direct property access in the generated script:
```js
return _node.focalLength;
```

### B4 — `DazRenderSettings` is unverified
**File:** `dazpy/_render.py`  
`App.getRenderMgr()` returned an empty value in live testing. The whole class
is untested against a live server.  
**Fix:** Probe `App.getRenderMgr()` interactively, find the correct API path,
update the class, add integration tests (or mark with a dedicated skip flag
`skip_no_renderer`).

---

## Section 1 — Critical: Skeleton and Bone (highest value, biggest gap)

Figures in DAZ Studio are `DzSkeleton` instances, not plain `DzNode`s.
Posing a figure means setting bone rotations. Without this, dazpy can't
do the most common DAZ automation task.

### 1a — `DazSkeleton` proxy class
**New file:** `dazpy/_skeleton.py`  
Extends `DazNode`. DAZ API class: `DzSkeleton`.

Methods to implement:
- `bones() -> list[DazBone]` — `getAllBones()` returns an array, use names
  to build proxies
- `find_bone(name: str) -> DazBone` — `findBone(name)`
- `find_bone_by_label(label: str) -> DazBone` — `findBoneByLabel(label)`
- `num_bones() -> int` — `getAllBones().length`
- `follow_target() -> DazSkeleton | None` — `getFollowTarget()`

### 1b — `DazBone` proxy class
**New file:** `dazpy/_bone.py`  
Extends `DazNode`. DAZ API class: `DzBone`.

Bones are posed by setting *local* rotation (not world-space).

Methods to implement:
- `local_rotation() -> dict` — `{x, y, z, w}` from `getLocalRot()`; also
  expose as Euler angles via the rotation order
- `set_local_rotation(x, y, z)` — set Euler angles using
  `getXRotControl().setValue(x)` etc. (individual axis controls, in degrees)
- `local_position() -> dict` — `getLocalPos()`
- `rotation_order() -> str` — `getRotationOrder()`; values like `"XYZ"`, `"ZYX"`
- `get_skeleton() -> DazSkeleton` — traverse up via `getSkeleton()`

Note: bone rotation in DAZ is set via the individual float properties
(`getXRotControl()`, `getYRotControl()`, `getZRotControl()`), not by setting
a quaternion directly. The values are in degrees.

### 1c — Scene-level skeleton accessors
**File:** `dazpy/_scene.py`

Add:
- `skeletons() -> list[DazSkeleton]` — `getSkeletonList()`
- `find_skeleton(name: str) -> DazSkeleton` — `findSkeleton(name)`
- `find_skeleton_by_label(label: str) -> DazSkeleton` — `findSkeletonByLabel(label)`
- `num_skeletons() -> int` — `getNumSkeletons()`

### 1d — `NodeIdentifier` type discrimination
**File:** `dazpy/_scene.py`, `dazpy/_node.py`  
`scene.nodes()` currently returns `DazNode` for everything. Figures should
return `DazSkeleton`. Add a type probe in the bulk node fetch:
```js
Scene.getNode(i).className()  // returns "DzSkeleton", "DzCamera", etc.
```
Update `nodes()` to return the correct subclass. Add a `_NODE_CLASS_MAP` dict
in `__init__.py`.

### 1e — Tests
Add integration tests in `tests_dazpy_integration.py`:
- `TestDazSkeleton` class (gated with `@skip_no_daz`) — assert
  `scene.skeletons()` returns a list, `find_skeleton` works/raises,
  `skeleton.bones()` returns `DazBone` instances
- `TestDazBone` — `local_rotation` has x/y/z/w, `set_local_rotation` round-trips

---

## Section 2 — Critical: Morph access

The #1 DAZ automation task after posing: controlling morph sliders
(body shapes, expressions, clothing fits).

### 2a — `node.modifiers()` and `node.find_modifier(name)`
**File:** `dazpy/_node.py`

Add to `DazNode`:
```python
def modifiers(self) -> list[DazModifier]:
    # getObject().getNumModifiers(), getObject().getModifier(i).getName()
    ...

def find_modifier(self, name: str) -> DazModifier | None:
    # getObject().findModifier(name)
    ...
```
Fix `DazModifier.__init__` to accept a locator string directly (not just
index), so `find_modifier` can return a usable object.

### 2b — `DazMorph` class
**New file:** `dazpy/_morph.py`  
Extends `DazModifier`. DAZ API class: `DzMorph`.

Properties:
- `value -> float` — `getValueChannel().getValue()` (current morph strength, 0.0–1.0)
- `value` setter — `getValueChannel().setValue(v)`
- `min -> float`, `max -> float` — from `getValueChannel()`

The locator for a morph found by name on a node:
```js
Scene.findNode("NodeName").getObject().findModifier("MorphName")
```

### 2c — `node.morphs()` convenience
**File:** `dazpy/_node.py`

Add:
```python
def morphs(self) -> list[DazMorph]:
    # filter modifiers by className() == "DzMorph"
```

### 2d — Tests
Unit test: `DazMorph` value read/write generates correct script.  
Integration test (gated `@skip_no_daz`): find a node with morphs, read a
value, set it, read back.

---

## Section 3 — Critical: Material access path

`DazMaterial` exists but there's no way to reach it from a `DazNode`.

### 3a — `node.materials()` and `node.find_material(name)`
**File:** `dazpy/_node.py`

Add to `DazNode`:
```python
def materials(self) -> list[DazMaterial]:
    # getObject().getCurrentShape().getNumMaterials()
    # getObject().getCurrentShape().getMaterial(i).getName() for names
    ...

def find_material(self, name: str) -> DazMaterial | None:
    # getObject().getCurrentShape().findMaterial(name)
    ...
```

Fix `DazMaterial.__init__` to accept a pre-built locator string (not
node_locator + index), so `find_material` can return by name directly.

### 3b — Fix `DazMaterial` direct property access
**File:** `dazpy/_material.py`

`diffuse_color` uses `findPropertyByLabel("Diffuse Color")`. Use the direct
DAZ API instead:
```js
var c = m.getDiffuseColor(); return {r: c.red, g: c.green, b: c.blue};
```
Add `set_diffuse_color(r, g, b)` using `setDiffuseColor()`.  
Fix `opacity` to use `getBaseOpacity()` / `setBaseOpacity()` directly.  
Add `color_map() -> str | None` returning the texture filename via
`getColorMap()`.  
Add `is_smoothing_on()`, `smoothing_angle`, `is_opaque()`.

### 3c — Tests
Integration test: `node.materials()` returns a list, `find_material` works,
`diffuse_color` returns a dict with r/g/b keys.

---

## Section 4 — High: Node rotation and selection

### 4a — `DazNode.set_rotation()`
**File:** `dazpy/_node.py`

Add world-space rotation setter using `setWSRot()` and per-axis controls.
The simplest approach is via the individual rotation controls, same as bones:
```python
def set_rotation(self, x: float, y: float, z: float) -> None:
    # Sets X/Y/Z rotation controls in degrees
    # _node.getXRotControl().setValue(x), etc.
```

### 4b — `DazNode` local-space transforms
**File:** `dazpy/_node.py`

Add:
- `local_position -> dict` — `getLocalPos()`; return `{x, y, z}`
- `set_local_position(x, y, z)` — `setLocalPos()`
- `local_rotation -> dict` — `getLocalRot()`; return `{x, y, z, w}`
- `set_local_rotation(x, y, z)` — via axis controls (degrees)

### 4c — Selection
**File:** `dazpy/_node.py`, `dazpy/_scene.py`

Add to `DazNode`:
- `is_selected() -> bool` — `isSelected()`
- `select(on: bool = True) -> None` — `select(onOff)`

Add to `DazScene`:
- `selected_nodes() -> list[DazNode]` — `getSelectedNodeList()`
- `primary_selection() -> DazNode | None` — `getPrimarySelection()`
- `set_primary_selection(node: DazNode) -> None` — `setPrimarySelection()`
- `select_all(on: bool = True) -> None` — `selectAllNodes(onOff)`

---

## Section 5 — High: Scene I/O and state

**File:** `dazpy/_scene.py`

Add:
- `load(path: str) -> None` — `Scene.loadScene(path, 0)`  
  (second arg is `DzOpenMethod`; 0 = merge/default)
- `save(path: str) -> None` — `Scene.saveScene(path)`
- `filename() -> str` — `Scene.getFilename()`
- `needs_save() -> bool` — `Scene.needsSave()`
- `play_range() -> dict` — `{start, end}` from `getPlayRange()`
- `set_play_range(start: int, end: int) -> None` — `setPlayRange()`
- `set_anim_range(start: int, end: int) -> None` — `setAnimRange()`
- `is_playing() -> bool` — `isPlaying()`
- `loop_playback(on: bool) -> None` — `loopPlayback(onOff)`

---

## Section 6 — Medium: Camera and Light improvements

### 6a — DazCamera
**File:** `dazpy/_camera.py`

Fix `focal_length` and `frame_width` to use direct JS properties (Bug B3).  
Add:
- `focal_distance -> float` (r/w) — direct `focalDistance` property
- `aspect_width`, `aspect_height` (r/w) — direct properties
- `pixels_width`, `pixels_height` (r/w)
- `near_clipping_plane`, `far_clipping_plane` (read-only)
- `aim_at(x: float, y: float, z: float) -> None` — `aimAt(new DzVec3(x,y,z))`
- `focal_point() -> dict` — `getFocalPoint()`; return `{x, y, z}`
- `is_view_camera() -> bool` — `isViewCamera()`

### 6b — DazLight
**File:** `dazpy/_light.py`

Add:
- `is_on() -> bool` — `isOn()`
- `set_color(r: float, g: float, b: float) -> None` — set diffuse color via property
- `is_directional() -> bool` — `isDirectional()`
- `is_area_light() -> bool` — `isAreaLight()`
- `direction() -> dict | None` — `getWSDirection()`; return `{x, y, z}`
  (only valid for directional lights)

---

## Section 7 — Medium: Geometry improvements

**File:** `dazpy/_geometry.py`

Add:
- `face_vertex_indices(start: int = 0, count: int = 1000) -> dict` — chunked
  access to `getFacet(i)` vertex indices; returns `{total, start, facets: [[v0,v1,v2,v3], ...]}`
- `normals(start: int = 0, count: int = 5000) -> dict` — `getNormal(i)`
- `uv_set_count() -> int` — number of UV sets
- `uv_positions(uv_set: int = 0, start: int = 0, count: int = 5000) -> dict`
- `face_group_names() -> list[str]` — `getFaceGroup(i).getName()`
- `material_group_names() -> list[str]` — `getMaterialGroup(i).getName()`
- `subdivision_level() -> int` — `getCurrentSubDivisionLevel()`
- `tris_count() -> int`, `quads_count() -> int`

---

## Section 8 — Low: DazNode additional queries

**File:** `dazpy/_node.py`

Add:
- `is_in_scene() -> bool` — `isInScene()`
- `is_root() -> bool` — `isRootNode()`
- `is_visible_in_render() -> bool` / `set_visible_in_render(on: bool)` — `isVisibleInRender()` / `setVisibleInRender()`
- `is_visible_in_viewport() -> bool` / `set_visible_in_viewport(on: bool)`
- `bounding_box() -> dict` — `getWSBoundingBox()`; return `{min: {x,y,z}, max: {x,y,z}}`
- ~~`duplicate() -> DazNode`~~ — removed; `DzNode.duplicate()` requires the Qt event loop and deadlocks under synchronous script execution

---

## Checklist

Copy this into the session notes and check off items as you complete them.

```
Bugs
[x] B1  DazNode.rotation — add w component to quaternion
[x] B2  DazNode.scale — rename to general_scale, add dict scale property
[x] B3  DazCamera focal_length/frame_width — use direct JS properties
[x] B4  DazRenderSettings — verify App.getRenderMgr() and fix

Section 1 — Skeleton/Bone
[x] 1a  DazSkeleton proxy class
[x] 1b  DazBone proxy class
[x] 1c  scene.skeletons(), find_skeleton(), find_skeleton_by_label()
[x] 1d  scene.nodes() returns correct subclass (DazSkeleton vs DazNode)
[x] 1e  Integration tests for skeletons and bones

Section 2 — Morphs
[x] 2a  node.modifiers() and node.find_modifier(name)
[x] 2b  DazMorph class with value r/w
[x] 2c  node.morphs() convenience accessor
[x] 2d  Tests

Section 3 — Material access
[x] 3a  node.materials() and node.find_material(name)
[x] 3b  Fix DazMaterial to use direct DAZ API (not property labels)
[x] 3c  Tests

Section 4 — Node rotation/selection
[x] 4a  DazNode.set_rotation()
[x] 4b  local_position, local_rotation, set_local_position, set_local_rotation
[x] 4c  Selection: is_selected, select, scene.selected_nodes, primary_selection

Section 5 — Scene I/O
[x] 5a  load(), save(), filename(), needs_save()
[x] 5b  play_range(), set_play_range(), set_anim_range()
[x] 5c  is_playing(), loop_playback()

Section 6 — Camera/Light
[x] 6a  DazCamera: focal_distance, aspect/pixel dims, aim_at, focal_point, is_view_camera
[x] 6b  DazLight: is_on, set_color, is_directional, is_area_light, direction

Section 7 — Geometry
[x] 7a  face_vertex_indices(), normals(), UV sets
[x] 7b  face/material group names, subdivision level, tri/quad counts

Section 8 — Node queries
[x] 8a  is_in_scene, is_root, render/viewport visibility, bounding_box (duplicate removed — deadlocks)
```

---

## How to start a session

1. Read this file.
2. Pick the first unchecked item.
3. Run `mcp__daz-api__get_class_details("DzXxx")` for the relevant class.
4. Implement in the appropriate `dazpy/_xxx.py` file.
5. Add unit tests to `tests_dazpy.py` (mock-based).
6. Add integration tests to `tests_dazpy_integration.py` (gated with `@skip_no_daz`).
7. Run both test suites and confirm green.
8. Check off the item in this file.
