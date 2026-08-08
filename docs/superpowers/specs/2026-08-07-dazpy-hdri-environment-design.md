# dazpy.lighting — HDRIEnvironment (design)

## Context

GitHub issue #31 proposed `dazpy.lighting.HDRIEnvironment` alongside
`ThreePointLightSetup` and `SetLightColor`. `ThreePointLightSetup` shipped
(beads `daz-script-server-p1af`); `SetLightColor` needed no new code (already
covered by `DazLight.set_color`). `HDRIEnvironment` was deferred pending
research into what DAZ Studio actually exposes for Iray environment/IBL
lighting — tracked as beads `daz-script-server-x6sy`.

That research is now done, confirmed live against a running DAZ Studio
instance:

- IBL/dome lighting is **not** a `DzLight` node. It lives on a global,
  singleton render-settings object: `App.getRenderMgr()
  .getRenderElementObjects()[3]`, class `DzEnvironmentNode`, labeled
  "Environment Options" — the fourth of the four fixed render-element groups
  already referenced in a comment at `dazpy/_render.py:223` ("General
  Render, Iray, Tonemapper, Environment").
- Properties confirmed present on that holder (name, type, and — for enums —
  live-enumerated item labels):
  - `Environment Mode` (enum): `Dome and Scene` / `Dome Only` /
    `Sun-Sky Only` / `Scene Only`
  - `Dome Mode` (enum): 6 sphere/box variants — not used by this design
  - `Draw Dome` (bool)
  - `Environment Map` (a *mappable* float property; the image is set via
    `.setMap(path)`, not `.setValue()`)
  - `Environment Intensity` (float)
  - `Dome Rotation` (float)
  - `Environment Lighting Resolution` (int, default `512`)
  - A large `SS *` (Sun-Sky) property family for procedural sky — out of
    scope; that's a different feature from image-based lighting.
- The access pattern is the same generic
  `holder.findProperty(name).getValue()/.setValue()` idiom `DazRenderSettings
  ._get_iray_property`/`_set_iray_property` already use for the Iray
  property holder — just against a different holder object.
- **Safety finding, load-bearing for the design below:** calling
  `.setMap()` with a path that does not exist on disk pops a blocking native
  file-not-found dialog. Because the HTTP `/execute` handler blocks the main
  Qt thread waiting for the script to finish (see "Threading Model" in
  `CLAUDE.md`), that dialog hangs the request indefinitely — and in a live
  test it crashed DAZ Studio outright. `apply_hdri_environment` must
  therefore validate the image path exists *before* ever calling `setMap`,
  and never pass caller-controlled unvalidated paths into it.

## Goals

- Let a caller apply image-based (HDRI/dome) lighting to a scene with one
  call, using sensible defaults.
- Follow the same "domain macro built on primitives" convention as
  `ThreePointLightSetup`: a frozen dataclass spec plus a standalone
  `apply_*` function, not a class with an `.apply()` method.
- Fail safely and immediately (a Python exception) on a bad image path,
  rather than risking a hung request or a DAZ Studio crash.

## Non-goals

- Procedural Sun-Sky lighting (`SS *` properties) — a different feature
  from image-based lighting; not part of this issue.
- `Dome Mode` (sphere/box shape, finite vs. infinite) — leaving DAZ Studio's
  default (`Infinite Sphere`) alone; no evidence any caller needs to change
  scene geometry bounds for IBL to work.
- `Environment Tint` and ground-plane properties (`Draw Ground`, `Ground
  Reflectivity`, etc.) — belong to backdrop/compositing concerns, not IBL
  itself.
- A standalone `SetLightColor` helper — redundant with `DazLight.set_color`
  (unchanged from the three-point-rig spec).

## Data model

Add to `dazpy/lighting.py`:

```python
@dataclass(frozen=True)
class HDRIEnvironment:
    """Image-based (HDRI/dome) lighting configuration.

    Args:
        image_path: Absolute path to an HDRI/environment map on disk. Must
            exist — validated before any DazScript call is made.
        intensity: Passed to the Iray "Environment Intensity" property.
        rotation_deg: Passed to the Iray "Dome Rotation" property.
        mode: One of ``"dome_only"``, ``"dome_and_scene"``, ``"scene_only"``.
            Maps to the DazScript "Environment Mode" enum. Procedural
            Sun-Sky mode is intentionally not exposed here.
        draw_dome: Whether the dome image is visible as a backdrop in the
            viewport/render (Iray "Draw Dome"), independent of whether it
            lights the scene.
        resolution: Iray "Environment Lighting Resolution" (IBL sampling
            quality). ``None`` leaves DAZ Studio's current value untouched.
    """

    image_path: str
    intensity: float = 1.0
    rotation_deg: float = 0.0
    mode: str = "dome_only"
    draw_dome: bool = False
    resolution: int | None = None
```

`mode` is a plain `str` (not a Python `Enum`) for consistency with
`light_type` on `ThreePointLightSetup`, which is also a validated string.

## Behavior

```python
def apply_hdri_environment(
    render_settings: DazRenderSettings, env: HDRIEnvironment
) -> None:
```

1. Validate `os.path.isfile(env.image_path)`; raise `FileNotFoundError` if
   the file doesn't exist. This check happens before any DazScript call.
2. Validate `env.mode` is one of `"dome_only"`, `"dome_and_scene"`,
   `"scene_only"`; raise `ValueError` otherwise.
3. Set the environment map via the new
   `DazRenderSettings._set_environment_map(path)` (re-validates existence as
   defense in depth, then calls `.setMap(path)` on the "Environment Map"
   property).
4. Set `Environment Intensity` to `env.intensity`.
5. Set `Dome Rotation` to `env.rotation_deg`.
6. Set `Environment Mode` via `setValueFromString` using the DazScript
   label for `env.mode` (`"dome_only"` → `"Dome Only"`,
   `"dome_and_scene"` → `"Dome and Scene"`, `"scene_only"` → `"Scene Only"`).
7. Set `Draw Dome` to `env.draw_dome`.
8. If `env.resolution is not None`, set `Environment Lighting Resolution`
   to `env.resolution`; otherwise this property is left untouched.

### `DazRenderSettings` additions (`dazpy/_render.py`)

Mirroring the existing `_iray_property_holder`/`_get_iray_property`/
`_set_iray_property` trio, which currently target
`getActiveRenderer().getPropertyHolder()`:

```python
def _environment_holder(self) -> str:
    # Index 3 of the 4 fixed render element groups (General Render, Iray,
    # Tonemapper, Environment) -- confirmed against a live instance.
    return f"{self._render_mgr()}.getRenderElementObjects()[3]"

def _get_environment_property(self, name: str): ...
def _set_environment_property(self, name: str, value: object) -> None: ...
def _set_environment_property_from_string(self, name: str, value: str) -> None: ...
def _set_environment_map(self, path: str) -> None: ...
```

`_get_environment_property`/`_set_environment_property` follow the exact
shape of their `_iray_property` counterparts, just against
`_environment_holder()`. `_set_environment_property_from_string` calls
`setValueFromString` on the named property (needed for the `Environment
Mode` enum — `setValue()` takes an integer index, and hardcoding enum
indices is fragile). `_set_environment_map` re-checks `os.path.isfile`
(the caller in `apply_hdri_environment` already checked, but this method
may be called directly) then calls `.setMap(path)`.

These are the only new methods on `DazRenderSettings`; no public
`environment`-prefixed properties are added there — `HDRIEnvironment`/
`apply_hdri_environment` in `lighting.py` is the sole public surface,
matching how `ThreePointLightSetup`/`apply_three_point_light_setup` is the
sole public surface over `DazScene`/`DazLight` primitives.

## API surface / exports

Add to `dazpy/__init__.py`:

```python
from .lighting import (
    ...,
    HDRIEnvironment,
    apply_hdri_environment,
)
```

And the corresponding `__all__` entries.

## Testing

In `tests/test_dazpy.py` (mock-client style, matching existing
`TestLightingMath`/three-point-rig test conventions):

- `apply_hdri_environment` raises `FileNotFoundError` immediately (no
  client calls made) when `image_path` doesn't exist on disk. Use
  `tempfile`/`os.path` to construct a guaranteed-nonexistent path.
- `apply_hdri_environment` raises `ValueError` for an invalid `mode`
  string, again with no client calls made.
- A happy-path case (using a real temp file for `image_path`) asserting the
  mock client receives calls setting the map, intensity, rotation, mode
  (correct DazScript label per `mode` value — parameterized over all
  three), and draw-dome flag.
- `resolution=None` (the default) results in no call touching
  `Environment Lighting Resolution`; `resolution=1024` results in exactly
  one such call.

## Open questions / follow-ups

None outstanding — `Dome Mode`, `Environment Tint`, and ground-plane
properties were deliberately scoped out (see Non-goals) rather than left
ambiguous, and can become their own follow-up issues if a real need shows
up.
