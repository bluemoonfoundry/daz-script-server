# dazpy.lighting — Three-Point Light Rig (design)

## Context

GitHub issue #31 ("AsyncIO Support, Type-Safe Models, Domain Submodules, and
Coordinate Math") proposes packaging common DazScript macros into first-class
Python submodules, including `dazpy.lighting` with `ThreePointLightSetup`,
`HDRIEnvironment`, and `SetLightColor`. Tracked as beads issue
`daz-script-server-p1af`.

This spec covers the first slice of that submodule: a three-point light rig
builder. `HDRIEnvironment` is deferred to a separate issue — DAZ Studio's
IBL/environment-dome DazScript surface hasn't been confirmed yet, and it's a
genuinely separate research effort. `SetLightColor` is not implemented here
because it's already fully covered by the existing `DazLight.set_color()` /
`DazLight.color` — no new code needed.

The codebase already has a precedent for this kind of "domain macro built on
primitives" work in `dazpy/_interaction.py`: frozen dataclass specs/recipes
plus a separate `apply_*_to_scene` function, rather than classes with an
`.apply()` method. This design follows that convention.

## Goals

- Let a caller stand up a conventional three-point light rig (key/fill/rim)
  around a target with one call, using sensible photographic defaults.
- Support both the common case (angle/distance around a target) and the
  power-user case (exact world-space position per light), without two
  separate APIs.
- Build entirely on existing primitives (`DazScene.create_light`, `DazNode`
  position/rotation setters, `DazLight.set_color`, `Vec3` math) — no new
  DazScript surface required.

## Non-goals

- `HDRIEnvironment` / IBL dome lighting (separate issue, pending DazScript
  API research).
- A standalone `SetLightColor` helper (redundant with `DazLight.set_color`).
- Area lights, light linking/exclusion, or any Iray-specific shader tuning.

## Data model

New file: `dazpy/lighting.py`.

```python
@dataclass(frozen=True)
class LightSpec:
    """One light's placement and output within a rig."""
    role: str                                   # "key" | "fill" | "rim" (informational)
    azimuth_deg: float                          # 0 = facing target from +Z, increases clockwise
    elevation_deg: float                        # 0 = level with target, +90 = directly above
    distance: float                              # from target, in DAZ Studio units (cm)
    intensity: float                             # passed straight to DazLight.intensity
    color: tuple[int, int, int] = (255, 255, 255)  # 0-255 RGB, passed to set_color
    position: Vec3 | None = None                 # explicit override — when set, azimuth/elevation/distance are ignored

@dataclass(frozen=True)
class ThreePointLightSetup:
    """Input spec for a three-point light rig."""
    target: Vec3 | DazNode                        # explicit point, or a node (figure/camera) whose .position is used
    key: LightSpec = _DEFAULT_KEY                  # azimuth=45,  elevation=30, distance=150, intensity=100
    fill: LightSpec = _DEFAULT_FILL                # azimuth=-45, elevation=15, distance=150, intensity=50
    rim: LightSpec = _DEFAULT_RIM                  # azimuth=180, elevation=45, distance=150, intensity=75
    light_type: str = "spot"                       # forwarded to DazScene.create_light

@dataclass(frozen=True)
class ThreePointLightRig:
    """Result: handles to the three created lights."""
    key: DazLight
    fill: DazLight
    rim: DazLight
```

Defaults (`_DEFAULT_KEY`/`_DEFAULT_FILL`/`_DEFAULT_RIM`) are module-level
`LightSpec` instances so `ThreePointLightSetup()` with no overrides produces
a reasonable rig out of the box.

## Behavior

```python
def apply_three_point_light_setup(
    scene: DazScene, setup: ThreePointLightSetup
) -> ThreePointLightRig:
```

1. Resolve `setup.target` to a `Vec3`: if it's a `DazNode`, read `.position`
   and convert via `Vec3.from_dict`; if it's already a `Vec3`, use it as-is.
2. For each of `key`, `fill`, `rim` (in that order):
   - Resolve the light's world position:
     - If `spec.position` is set, use it directly.
     - Otherwise compute it via a new `_spherical_offset(target, azimuth_deg,
       elevation_deg, distance) -> Vec3` helper (pure `Vec3` math, no
       DazScript).
   - Create the light: `scene.create_light(setup.light_type)`.
   - `light.set_position(pos.x, pos.y, pos.z)`.
   - Compute orientation via a new `_look_at_euler(from_pos, to_pos) ->
     tuple[float, float, float]` helper (degrees, XYZ order) and call
     `light.set_rotation(x, y, z)`. This is necessary because `aimAt()` only
     exists on `DzCamera` in the DazScript API, not on light nodes.
   - `light.intensity = spec.intensity`.
   - `light.set_color(*spec.color)`.
3. Return `ThreePointLightRig(key=key_light, fill=fill_light, rim=rim_light)`.

### `_spherical_offset` and `_look_at_euler`

Both are private, pure-Python helpers local to `dazpy/lighting.py` (not
added to `math3.py`, since they're specific to this rig-building use case
rather than general-purpose vector math). `_look_at_euler` only needs to
produce yaw/pitch (no roll) since lights have no "up" concept that matters
for aiming.

## API surface / exports

Add to `dazpy/__init__.py`:

```python
from .lighting import (
    LightSpec,
    ThreePointLightSetup,
    ThreePointLightRig,
    apply_three_point_light_setup,
)
```

And the corresponding `__all__` entries.

## Testing

In `tests/test_dazpy.py` (mock-client style, matching existing conventions):

- Pure-Python tests for `_spherical_offset` and `_look_at_euler` — no client
  needed, just numeric assertions against known angle/position pairs.
- Mock-client tests asserting `apply_three_point_light_setup`:
  - Issues three `create_light` calls (or the equivalent scripted calls) in
    key → fill → rim order.
  - Sets position, rotation, intensity, and color on each light matching the
    resolved `LightSpec`.
  - Correctly resolves a `DazNode` target via its `.position`.
  - Honors an explicit `position` override on a `LightSpec`, skipping the
    spherical computation for that light.
  - Returns a `ThreePointLightRig` with the three `DazLight` handles.

## Open questions / follow-ups

- `HDRIEnvironment` — separate issue, pending confirmation of what DazScript
  actually exposes for environment/dome lighting.
