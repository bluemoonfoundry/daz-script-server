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

## Non-goals

- `CinematicAnimatedShot` / real interpolated keyframes (separate issue,
  pending DazScript keyframe API research).
- Bounding-box-aware framing — `FrameSubject` uses fixed distance presets
  per shot type, not a computed bounding box (`DazNode` has no bounding-box
  query today).
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
def resolve_target(target: Vec3 | DazNode) -> Vec3: ...
```

(Names lose their leading underscore since they're now the public surface
of an internal module, imported by both `lighting.py` and `cinematics.py`.)
`lighting.py` is refactored to import these instead of defining its own
copies — no behavior change, existing lighting tests must continue to pass
unmodified.

### New file: `dazpy/cinematics.py`

```python
@dataclass(frozen=True)
class CinematicStaticShot:
    """A single camera placement and optics configuration."""
    position: Vec3
    look_at: Vec3 | DazNode | None = None    # aim_at() target; None = use `rotation` instead
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


_SHOT_DISTANCES = {"close_up": 60.0, "medium": 150.0, "full_body": 300.0}

@dataclass(frozen=True)
class FrameSubject:
    """A camera framing a subject at a named shot distance."""
    subject: Vec3 | DazNode
    shot_type: str = "medium"   # "close_up" | "medium" | "full_body"
    azimuth_deg: float = 0.0
    elevation_deg: float = 10.0
    focal_length: float = 50.0
```

`position`, `radius`, `elevation_deg` etc. use the same DAZ Studio unit
convention (cm) as `dazpy.lighting`'s `LightSpec.distance`.

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
3. Orientation: if `shot.look_at` is set, resolve it via `resolve_target`
   (if it's a `DazNode`) and call `cam.aim_at(x, y, z)`. Else if
   `shot.rotation` is set, call `cam.set_rotation(*shot.rotation)`. Else
   leave orientation untouched.
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
2. `target = resolve_target(orbit.target)`.
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
3. `target = resolve_target(frame.subject)`.
4. `pos = spherical_offset(target, frame.azimuth_deg, frame.elevation_deg, _SHOT_DISTANCES[frame.shot_type])`.
5. `cam.set_position(pos.x, pos.y, pos.z)`.
6. `cam.aim_at(target.x, target.y, target.z)`.
7. `cam.focal_length = frame.focal_length`.
8. Return `cam`.

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
  new import location) plus `resolve_target`.
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
  - Resolves a `DazNode` target via `resolve_target`.
- Mock-client tests for `apply_frame_subject`:
  - Resolves each `shot_type` to its documented distance.
  - Raises `ValueError` on an unknown `shot_type`.
  - Sets focal_length, position, and aim_at correctly.

## Open questions / follow-ups

- `CinematicAnimatedShot` — separate issue, pending confirmation of what
  DazScript actually exposes for keyframe/`addKey` writes at specific
  frames/times.
