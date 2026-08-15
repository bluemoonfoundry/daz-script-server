# dazpy.cinematics — Static Camera Shots (design)

## Context

GitHub issue #31 ("AsyncIO Support, Type-Safe Models, Domain Submodules, and
Coordinate Math") proposes packaging common DazScript macros into first-class
Python submodules, including `dazpy.cinematics` with `OrbitCamera`,
`CinematicShot`, and `FrameSubject`. Tracked as beads issue
`daz-script-server-p1af`.

This spec covers the static/per-frame-placement slice of that submodule:
`CinematicStaticShot`, `OrbitCamera`, and `FrameSubject`. A true interpolated
`CinematicAnimatedShot` (real DazScript keyframes) is deferred to a separate
follow-up issue — DAZ Studio's keyframe/`addKey` DazScript surface hasn't
been confirmed against a live instance yet, and it's a genuinely separate
research effort. This mirrors how `HDRIEnvironment` was deferred out of the
`dazpy.lighting` slice pending IBL API confirmation.

The codebase already has a precedent for this kind of "domain macro built on
primitives" work in `dazpy/lighting.py` and `dazpy/poses.py`: frozen
dataclass specs plus a separate `apply_*` function. This design follows that
convention.

## Goals

- Let a caller place and configure a camera for a single framing
  (`CinematicStaticShot`) in one call — position, aim, and optics together.
- Let a caller sweep a camera around a target across a frame range
  (`OrbitCamera`) without hand-computing spherical placement per frame.
- Let a caller frame a subject at a named shot distance (`FrameSubject`:
  close-up / medium / full-body) without knowing exact DAZ Studio units.
- In all three cases, let the caller choose whether to create a new camera
  or reuse/mutate one they already have a handle to.
- Build entirely on existing primitives (`DazScene.create_camera`,
  `DazCamera` optics properties, `DazNode` position/rotation setters,
  `DazTimeline.frame`, `Vec3` math) — no new DazScript surface required.
- Deduplicate the spherical-placement math (`_spherical_offset`,
  `_look_at_euler`, target resolution) that `dazpy.lighting` already has, by
  extracting it into a shared private module rather than copy-pasting it
  into `cinematics.py`.
- Avoid head/foot clipping on tight framing by default. A figure's
  `DazNode.position` is its root joint — for `DazSkeleton` figures that's
  conventionally the hip, not the center of mass or the head. Aiming and
  placing the camera straight at that point with a close-up distance can
  put the head (and sometimes the feet) outside the frame. Target
  resolution needs a vertical-offset knob so framing defaults aim higher
  than the raw root position, with the caller able to override it.

## Non-goals

- `CinematicAnimatedShot` / real interpolated keyframes (separate issue,
  pending DazScript keyframe API research).
- Bounding-box-aware framing — `FrameSubject` uses fixed distance presets
  per shot type, not a computed bounding box (`DazNode` has no bounding-box
  query today). The vertical-offset heuristic (see Goals) is likewise a
  fixed-cm approximation tuned for an average adult figure, not a computed
  measurement — it does not know a specific figure's actual height.
- Multi-camera sequencing / shot lists / cuts. Each `apply_*` call
  configures one camera at a time; composing a sequence is left to the
  caller.

## Data model

### Shared helper extraction: `dazpy/_shot_geometry.py`

`dazpy/lighting.py` currently defines `_spherical_offset`, `_look_at_euler`,
and a target-resolution helper (`_resolve_target`) as private module-level
functions. `cinematics.py` needs the identical three. Rather than duplicate
them, they move to a new private module:

```python
# dazpy/_shot_geometry.py
def spherical_offset(target: Vec3, azimuth_deg: float, elevation_deg: float, distance: float) -> Vec3: ...
def look_at_euler(from_pos: Vec3, to_pos: Vec3) -> tuple[float, float, float]: ...
def resolve_target(target: Vec3 | DazNode, vertical_offset_cm: float = 0.0) -> Vec3: ...
```

(Names lose their leading underscore since they're now the public surface
of an internal module, imported by both `lighting.py` and `cinematics.py`.)
`lighting.py` is refactored to import these instead of defining its own
copies — no behavior change, existing lighting tests must continue to pass
unmodified. `lighting.py`'s call sites keep passing `vertical_offset_cm=0.0`
(the default) — light rigs don't need this adjustment, only camera framing
does.

`resolve_target` adds `vertical_offset_cm` to the resolved position's Y
component (DAZ Studio's up axis) *after* resolving a `DazNode` to its
`.position`, or directly to an explicit `Vec3`'s Y — so an explicit `Vec3`
target can also be nudged if the caller wants, though the offset exists
primarily to compensate for a figure's root-joint position.

### New file: `dazpy/cinematics.py`

```python
@dataclass(frozen=True)
class CinematicStaticShot:
    """A single camera placement and optics configuration."""
    position: Vec3
    look_at: Vec3 | DazNode | None = None    # aim_at() target; None = use `rotation` instead
    look_at_offset_cm: float = 0.0           # vertical offset applied to look_at when it's a DazNode; see resolve_target
    rotation: tuple[float, float, float] | None = None  # explicit (x,y,z) deg; ignored if look_at is set
    focal_length: float = 50.0
    depth_of_field: bool = False
    focal_distance: float | None = None      # None = leave DAZ's current value untouched
    aspect_width: float | None = None
    aspect_height: float | None = None
    pixels_width: int | None = None
    pixels_height: int | None = None


@dataclass(frozen=True)
class OrbitCamera:
    """A camera sweeping around a target across a frame range."""
    target: Vec3 | DazNode
    radius: float
    elevation_deg: float = 15.0
    start_azimuth_deg: float = 0.0
    end_azimuth_deg: float = 360.0
    frame_start: int = 0
    frame_end: int = 90
    focal_length: float = 50.0
    target_offset_cm: float = 25.0  # vertical offset above target's root position, assuming chest-height framing


_SHOT_DISTANCES = {"close_up": 60.0, "medium": 150.0, "full_body": 300.0}
_SHOT_TARGET_OFFSETS_CM = {"close_up": 45.0, "medium": 25.0, "full_body": 0.0}

@dataclass(frozen=True)
class FrameSubject:
    """A camera framing a subject at a named shot distance."""
    subject: Vec3 | DazNode
    shot_type: str = "medium"   # "close_up" | "medium" | "full_body"
    azimuth_deg: float = 0.0
    elevation_deg: float = 10.0
    focal_length: float = 50.0
    target_offset_cm: float | None = None  # None = use _SHOT_TARGET_OFFSETS_CM[shot_type]
```

`position`, `radius`, `elevation_deg` etc. use the same DAZ Studio unit
convention (cm) as `dazpy.lighting`'s `LightSpec.distance`.

`target_offset_cm` / `_SHOT_TARGET_OFFSETS_CM` are the fix for the
hip-joint clipping problem described in Goals: a figure's resolved
`.position` is generally its root/hip, so `resolve_target` (see above)
raises the actual look-at/orbit-center point by this many cm before any
spherical placement math runs. `_SHOT_TARGET_OFFSETS_CM` biases tighter
shots higher (close-up aims near chest/head height) and leaves full-body
shots at the root (a wide-enough shot to include the whole figure doesn't
need the correction). `OrbitCamera.target_offset_cm` defaults to a fixed
`25.0` (chest height) rather than a shot-type table, since orbit shots
don't carry a `shot_type` concept — callers doing a tight orbit should
raise it explicitly. `CinematicStaticShot.look_at_offset_cm` defaults to
`0.0` since that API already takes an explicit `position`/`look_at` the
caller fully controls; the knob exists for consistency, not because a
default correction is needed there.

## Behavior

### `_resolve_camera` (private, shared by all three `apply_*` functions)

```python
def _resolve_camera(scene: DazScene, camera: DazCamera | None, name: str | None) -> DazCamera:
    if camera is not None:
        return camera
    return scene.create_camera(name)
```

### `apply_static_shot`

```python
def apply_static_shot(
    scene: DazScene, shot: CinematicStaticShot, *, camera: DazCamera | None = None, name: str | None = None
) -> DazCamera:
```

1. `cam = _resolve_camera(scene, camera, name)`.
2. `cam.set_position(shot.position.x, shot.position.y, shot.position.z)`.
3. Orientation: if `shot.look_at` is set, resolve it via
   `resolve_target(shot.look_at, vertical_offset_cm=shot.look_at_offset_cm)`
   and call `cam.aim_at(x, y, z)`. Else if `shot.rotation` is set, call
   `cam.set_rotation(*shot.rotation)`. Else leave orientation untouched.
4. `cam.focal_length = shot.focal_length`.
5. `cam.depth_of_field = shot.depth_of_field`.
6. If `shot.focal_distance is not None`: `cam.focal_distance = shot.focal_distance`.
7. For each of `aspect_width`, `aspect_height`, `pixels_width`,
   `pixels_height`: if not `None`, write the corresponding `DazCamera`
   property.
8. Return `cam`.

### `apply_orbit_camera`

```python
def apply_orbit_camera(
    scene: DazScene, orbit: OrbitCamera, *, camera: DazCamera | None = None, name: str | None = None
) -> DazCamera:
```

1. `cam = _resolve_camera(scene, camera, name)`.
2. `target = resolve_target(orbit.target, vertical_offset_cm=orbit.target_offset_cm)`.
3. `cam.focal_length = orbit.focal_length`.
4. `timeline = DazTimeline(cam._client)`.
5. For each `frame` in `range(orbit.frame_start, orbit.frame_end + 1)`:
   - `t = (frame - orbit.frame_start) / (orbit.frame_end - orbit.frame_start)`
     if the range has more than one frame, else `0.0`.
   - `azimuth = lerp(orbit.start_azimuth_deg, orbit.end_azimuth_deg, t)`.
   - `pos = spherical_offset(target, azimuth, orbit.elevation_deg, orbit.radius)`.
   - `timeline.frame = frame`.
   - `cam.set_position(pos.x, pos.y, pos.z)`.
   - `cam.aim_at(target.x, target.y, target.z)`.
6. Return `cam`.

Each per-frame write is a plain `setValue()` at that timeline position (via
the existing `DazNode.set_position` / `DazCamera.aim_at` primitives), **not**
a real DazScript key — this matches `dazpy.poses.zero_figure`'s
"apply directly" style rather than `dazpy.animation`'s capture/replay
machinery. Whether these per-frame writes persist as visible motion when
scrubbing the timeline afterward depends on DAZ Studio's key/animation mode
at call time; that's the caller's responsibility, called out in the
docstring.

### `apply_frame_subject`

```python
def apply_frame_subject(
    scene: DazScene, frame: FrameSubject, *, camera: DazCamera | None = None, name: str | None = None
) -> DazCamera:
```

1. Validate `frame.shot_type in _SHOT_DISTANCES`, else `ValueError`.
2. `cam = _resolve_camera(scene, camera, name)`.
3. `offset = frame.target_offset_cm if frame.target_offset_cm is not None else _SHOT_TARGET_OFFSETS_CM[frame.shot_type]`.
4. `target = resolve_target(frame.subject, vertical_offset_cm=offset)`.
5. `pos = spherical_offset(target, frame.azimuth_deg, frame.elevation_deg, _SHOT_DISTANCES[frame.shot_type])`.
6. `cam.set_position(pos.x, pos.y, pos.z)`.
7. `cam.aim_at(target.x, target.y, target.z)`.
8. `cam.focal_length = frame.focal_length`.
9. Return `cam`.

## API surface / exports

Add to `dazpy/__init__.py`:

```python
from .cinematics import (
    CinematicStaticShot,
    OrbitCamera,
    FrameSubject,
    apply_static_shot,
    apply_orbit_camera,
    apply_frame_subject,
)
```

And the corresponding `__all__` entries.

## Testing

In `tests/test_dazpy.py` (mock-client style, matching existing lighting/pose
test conventions):

- Pure-Python tests for `dazpy/_shot_geometry.py`'s `spherical_offset` and
  `look_at_euler` (moved from the existing lighting tests, updated to the
  new import location) plus `resolve_target`, including its
  `vertical_offset_cm` behavior for both a `Vec3` and a `DazNode` target.
- Existing `dazpy.lighting` tests continue to pass unmodified after the
  refactor (same public behavior, internal helper relocation only).
- Mock-client tests for `apply_static_shot`:
  - Creates a new camera via `scene.create_camera(name)` when `camera=None`.
  - Reuses the given `camera` (no `create_camera` call) when passed.
  - Sets position; calls `aim_at` when `look_at` is set; calls
    `set_rotation` when only `rotation` is set; touches neither when both
    are `None`.
  - Writes focal_length/depth_of_field always; writes focal_distance/aspect/
    pixel fields only when not `None`.
- Mock-client tests for `apply_orbit_camera`:
  - Iterates `frame_start..frame_end` inclusive, setting `timeline.frame`
    before each position/aim_at write.
  - Interpolates azimuth linearly between `start_azimuth_deg` and
    `end_azimuth_deg`.
  - Resolves a `DazNode` target via `resolve_target`, applying
    `target_offset_cm` (default `25.0`).
- Mock-client tests for `apply_frame_subject`:
  - Resolves each `shot_type` to its documented distance.
  - Resolves each `shot_type` to its documented default target offset
    (`_SHOT_TARGET_OFFSETS_CM`) when `target_offset_cm` is `None`.
  - Honors an explicit `target_offset_cm` override, bypassing the
    shot-type default.
  - Raises `ValueError` on an unknown `shot_type`.
  - Sets focal_length, position, and aim_at correctly.

## Open questions / follow-ups

- `CinematicAnimatedShot` — separate issue, pending confirmation of what
  DazScript actually exposes for keyframe/`addKey` writes at specific
  frames/times. **Resolved 2026-08-15, see addendum below.**

## Addendum (2026-08-15): `CinematicAnimatedShot` (real keyframes)

Live-verified against a running DAZ Studio 4.x instance (see
`daz-script-server-v6sk`). Findings:

- `DzProperty.setKey()` / `.addKey()` / `.isAnimated()` — **do not exist**
  on a live `DzFloatProperty` (position/rotation axis controls). The
  existing `dazpy/_property.py` `DazProperty.set_key()`/`is_animated`
  methods call these and are broken; tracked separately as
  `daz-script-server-5lpx`.
- `DzNumericProperty.setDoubleValue(tm, val)` **does** create a real
  keyframe at DAZ time `tm` and DAZ Studio interpolates between existing
  keys correctly (confirmed: two keys at ticks 0/320 with values 0/100
  read back as 50 at the halfway tick). `canAnimate()` is `true` by
  default on camera position/rotation controls — no `setCanAnimate(true)`
  call is needed first.
- `DzNode.setWSPos(tm, DzVec3)` (documented, two-arg overload) also
  creates a real world-space-position keyframe and interpolates
  correctly — used instead of manually keying the X/Y/Z position controls,
  since it matches `apply_static_shot`'s existing `set_position` (which
  uses `setWSPos`) and handles any parent-transform math DAZ Studio itself
  applies.
- **Ticks-per-frame is not a fixed constant** — `Scene.getTimeStep()`
  returned `160` in the live test scene (30fps), not the commonly-assumed
  `4800`. Frame→tick conversion must call `Scene.getTimeStep()` at
  keyframe-write time, not hardcode a constant.
- **Newly created nodes can already carry a default key** (e.g. a preset
  camera spawn position) on their position/rotation controls. Writing new
  keyframes without first calling `deleteAllKeys()` on each axis control
  leaves the old default key in the curve, which distorts interpolation
  and produces wild extrapolation beyond the new keys (observed: a
  y/z drift to `190`/`370` on an axis that was never touched). New
  primitives clear existing keys before writing.
- No live-confirmed global constant names for `InterpolationType` enum
  values (`ELinear`, `ETCB`, etc. all resolved `undefined`); the default
  key interpolation type (numeric value `2`, presumably TCB/spline) is
  left untouched — out of scope for this slice, same as `CinematicStaticShot`
  not exposing interpolation control.

### New primitives (`dazpy/_node.py`)

- `DazNode.set_position_at_frame(frame, x, y, z)` — `_node.setWSPos(frame * Scene.getTimeStep(), new DzVec3(x,y,z))`.
- `DazNode.set_rotation_at_frame(frame, x, y, z)` — `setDoubleValue(frame * Scene.getTimeStep(), ...)` on each of `getXRotControl()`/`getYRotControl()`/`getZRotControl()`.
- `DazNode.clear_position_keys()` / `clear_rotation_keys()` — `deleteAllKeys()` on the three axis controls; called once per `apply_animated_shot` call before writing the new curve.

### New data model / behavior (`dazpy/cinematics.py`)

```python
@dataclass(frozen=True)
class CameraKeyframe:
    frame: int
    position: Vec3
    look_at: Vec3 | DazNode | None = None
    look_at_offset_cm: float = 0.0
    rotation: tuple[float, float, float] | None = None

@dataclass(frozen=True)
class CinematicAnimatedShot:
    keyframes: tuple[CameraKeyframe, ...]
    focal_length: float = 50.0
    depth_of_field: bool = False
    focal_distance: float | None = None
```

`apply_animated_shot(scene, shot, *, camera=None, name=None) -> DazCamera`:

1. Validate at least two keyframes; frames strictly ascending and unique;
   orientation (`look_at`/`rotation`) either given on every keyframe or
   none — a partial mix would leave the rotation curve keyed at only some
   waypoints, holding a stale value in between.
2. Resolve/create the camera; write `focal_length`/`depth_of_field`/
   `focal_distance` once (same as `apply_static_shot`).
3. `cam.clear_position_keys()` always; `cam.clear_rotation_keys()` only if
   any keyframe specifies an orientation.
4. For each keyframe: `cam.set_position_at_frame(frame, x, y, z)`; if
   `look_at` is set, resolve it via `resolve_target` and compute the
   rotation with the existing `look_at_euler`, then
   `cam.set_rotation_at_frame(frame, x, y, z)`; elif `rotation` is set,
   write it directly.

End-to-end smoke-tested against a live DAZ Studio instance: a 3-waypoint
move (frames 0/15/30) produced 3 real keys on the X position control at
ticks 0/2400/4800 (160 ticks/frame), with the mid-move frame (7) reading
back a correctly interpolated position and orientation.
