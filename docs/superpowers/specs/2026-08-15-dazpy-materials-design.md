# dazpy.materials — Iray Uber Base material setup (design)

## Context

GitHub issue #31 ("AsyncIO Support, Type-Safe Models, Domain Submodules, and
Coordinate Math") proposes packaging common DazScript macros into first-class
Python submodules. `dazpy.lighting` and `dazpy.poses` already ship this way;
this spec covers the last of the four, `dazpy.materials`, tracked as beads
issue `daz-script-server-no7b` (blocking parent epic
`daz-script-server-p1af`).

The codebase already has a precedent for "domain macro built on primitives"
work in `dazpy/lighting.py` and `dazpy/poses.py`: frozen dataclass specs plus
a separate `apply_*(target, spec)` function, rather than classes with an
`.apply()` method. This design follows that convention, built on top of the
existing `DazMaterial` primitive (`dazpy/_material.py`).

**Key API constraint** (confirmed via `daz_script_spec.d.ts`): `DzMaterial`
has no dedicated Iray property-holder indirection the way
`DzRenderMgr.getActiveRenderer().getPropertyHolder()` does for render
settings. `DzMaterial` inherits `findProperty`/`findPropertyByLabel` from
`DzElement`, and Iray Uber Base channels (Base Color, Metallic Weight,
Glossy Roughness, ...) are ordinary named properties reached directly on the
material object. Texture-slot assignment goes through the *property*
object's `setMap(path)` method (defined on `DzNumericProperty`), not through
the material itself. No Iray channel label string exists anywhere in this
codebase prior to this change — they must be live-confirmed against a real
DAZ Studio instance before being trusted, matching the project's established
skepticism toward unverified DazScript property names (see the
`_render.py` environment-holder-index comments and the GH #32 "clown render"
precedent).

## Goals

- Let a caller set up a material's core Iray Uber Base channels (base color,
  metallic, roughness, glossy reflectivity, cutout opacity, bump, top coat)
  with one declarative call, without hand-assembling DazScript.
- Support texture-slot assignment (diffuse/normal/bump/roughness/metallic/
  opacity maps) with file-existence validation *before* any DazScript call,
  matching `HDRIEnvironment`'s precedent for avoiding a blocking
  file-not-found dialog.
- Provide a generic named-channel get/set escape hatch (`SurfaceProperty`)
  for Iray channels not covered by `IrayMaterial`'s typed fields.
- Fail loudly (raise) when a channel label doesn't resolve on the live
  material, rather than silently no-op'ing like `DazElement.set_property`
  currently does.

## Non-goals

- RSL/3Delight materials (`DzShaderMaterial`) — legacy, not Iray.
- The legacy brick shader (`DzBrickMaterial`/`convertUberIrayMaterial`).
- Any change to the existing low-level `DazMaterial` primitive's own
  properties (`diffuse_color`, `opacity`, `color_map`, etc.) — those already
  work and are out of scope here.

## Data model

New file: `dazpy/materials.py`.

```python
@dataclass(frozen=True)
class TextureMap:
    """One texture-slot assignment for an Iray material channel."""
    channel: str       # key into _CHANNEL_LABELS, e.g. "base_color", "normal"
    file_path: str     # absolute path to an image file on disk

@dataclass(frozen=True)
class SurfaceProperty:
    """Generic named Iray surface-channel override."""
    label: str          # DazScript property display label
    value: object

@dataclass(frozen=True)
class IrayMaterial:
    """Declarative Iray Uber Base material spec."""
    base_color: tuple[int, int, int] | None = None
    metallic_weight: float | None = None
    roughness: float | None = None
    glossy_reflectivity: float | None = None
    cutout_opacity: float | None = None
    bump_strength: float | None = None
    top_coat_weight: float | None = None
    textures: tuple[TextureMap, ...] = ()
    properties: tuple[SurfaceProperty, ...] = ()
```

`_CHANNEL_LABELS: dict[str, str]` maps each typed field name (and each
`TextureMap.channel` key) to its DazScript property display label. Seeded
with the standard Iray Uber Base labels; flagged in a code comment as
unconfirmed until corrected by the live-verification pass below.

## Behavior

Private helpers, built directly against `material._client`/`material._locator`
(not via `DazElement.get_property`/`set_property`, which silently discard
`"property_not_found"` — see `_element.py:44-60`):

- `_set_channel_value(material, label, value)` — `findPropertyByLabel` →
  `setValue()`; raises `MaterialError` if the material or property lookup
  fails.
- `_set_channel_map(material, label, path)` — validates `os.path.isabs` +
  `os.path.isfile(path)` before any DazScript call (mirrors
  `HDRIEnvironment`'s `_set_environment_map` validation in
  `lighting.py:254-276`); then `findPropertyByLabel` → `setMap(path)`.
- `_get_channel_value(material, label)` — `findPropertyByLabel` →
  `getValue()`.

Public functions:

```python
def apply_texture_map(material: DazMaterial, texture: TextureMap) -> None: ...

def apply_iray_material(material: DazMaterial, spec: IrayMaterial) -> None:
    """
    1. Validate every spec.textures[*].file_path up front (raise before any
       client call).
    2. Apply typed fields in declaration order, skipping None.
    3. Apply spec.textures.
    4. Apply spec.properties last, so ad hoc overrides can supersede typed
       fields set in the same call.
    """

def get_surface_property(material: DazMaterial, label: str) -> object: ...
def set_surface_property(material: DazMaterial, prop: SurfaceProperty) -> None: ...
```

`MaterialError(DazError)` is added to `dazpy/exceptions.py`, following the
`RenderError` shape (`message`, optional `request_id`).

## API surface / exports

Add to `dazpy/__init__.py`:

```python
from .materials import (
    IrayMaterial,
    TextureMap,
    SurfaceProperty,
    apply_iray_material,
    apply_texture_map,
    get_surface_property,
    set_surface_property,
)
from .exceptions import MaterialError
```

And the corresponding `__all__` entries.

## Testing

In `tests/test_dazpy.py` (mock-client style, matching
`TestThreePointLightSetup`):

- Dataclasses are frozen.
- `apply_texture_map` raises `FileNotFoundError`/`ValueError` before any
  client call for a missing/relative path.
- `apply_iray_material` issues scripts in typed-fields → textures →
  properties order, skipping `None` fields.
- `_set_channel_value`/`_set_channel_map` raise `MaterialError` on a
  server-side `"property_not_found"`/`"material_not_found"` result.
- `get_surface_property`/`set_surface_property` round-trip against a mocked
  client.

## Live verification

Done, against a running DAZ Studio instance with a Genesis 9 figure and a
primitive `Cube` prop loaded. Findings:

- The default Genesis 9 body/limb/mouth materials use the **PBRSkin**
  shader variant, not classic Iray Uber Base — its channel set differs (no
  `Cutout Opacity` or `Glossy Roughness`/`Glossy Reflectivity` at all; uses
  `Diffuse Roughness`, `Specular Lobe 1/2 Roughness`, etc. instead). The
  Genesis 9 eye-moisture and tear materials, and a plain prop's default
  material, *do* use classic Iray Uber Base — those were used to confirm
  `_CHANNEL_LABELS`.
- `findPropertyByLabel()` matches on the property's **display label**, which
  can differ from its underlying property **name**. Two of the originally
  seeded labels were wrong and have been corrected:
  - `metallic_weight`/`metallic`: label is `"Metallicity"` (property name is
    `"Metallic Weight"`), not `"Metallic Weight"`.
  - `bump_strength`/`bump`: label is `"Base Bump"` (property name is
    `"Bump Strength"`), not `"Bump Strength"`.
  - `base_color`, `roughness` ("Glossy Roughness"), `glossy_reflectivity`
    ("Glossy Reflectivity"), `cutout_opacity` ("Cutout Opacity"),
    `top_coat_weight` ("Top Coat Weight"), and `normal` ("Normal Map") were
    all confirmed correct as originally seeded.
- End-to-end round trip confirmed: `apply_iray_material()` with
  `metallic_weight`/`roughness`/`top_coat_weight` set, then read back via
  `get_surface_property()`, matched the requested values (float rounding
  aside); reverted to the prop's original (all-zero) values afterward.
  `MaterialError` was also confirmed raised live for a nonexistent channel
  label.

## Open questions / follow-ups

- `IrayMaterial`'s typed fields target classic Iray Uber Base. Figures using
  PBRSkin (e.g. default Genesis 9 skin materials) need different channel
  labels for an equivalent typed spec — out of scope here; use
  `SurfaceProperty`/`set_surface_property` with PBRSkin's own labels
  (`"Metallicity"`, `"Base Color"`, `"Diffuse Roughness"`, ...) in the
  meantime. A future `PBRSkinMaterial` spec (or shader-variant detection)
  is a candidate follow-up but is not part of this issue's scope.
