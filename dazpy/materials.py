"""Domain-level Iray Uber Base material setup built on the DazMaterial primitive.

Provides :class:`IrayMaterial` (declarative material spec), :class:`TextureMap`
(texture-slot assignment with file-existence validation), and
:class:`SurfaceProperty` (generic named Iray surface-channel override) plus
:func:`apply_iray_material` / :func:`apply_texture_map` to apply them, and
:func:`get_surface_property` / :func:`set_surface_property` for ad hoc access
to channels not covered by :class:`IrayMaterial`'s typed fields.

``DzMaterial`` has no dedicated Iray property-holder indirection the way
``DzRenderMgr.getActiveRenderer().getPropertyHolder()`` does for render
settings -- it inherits ``findProperty``/``findPropertyByLabel`` directly
from ``DzElement``, and Iray Uber Base channels (Base Color, Metallic
Weight, Glossy Roughness, ...) are ordinary named properties on the material
itself. Texture-slot assignment goes through the *property* object's
``setMap(path)`` (defined on ``DzNumericProperty``), not through the
material. The channel labels in ``_CHANNEL_LABELS`` are confirmed against a
live DAZ Studio instance -- see
``docs/superpowers/specs/2026-08-15-dazpy-materials-design.md`` for details.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ._script_builder import ScriptBuilder
from .exceptions import MaterialError

if TYPE_CHECKING:
    from ._material import DazMaterial


# Iray Uber Base shader channel display labels -- confirmed against a live
# DAZ Studio instance (a prop's default Iray Uber Base material, and a
# Genesis 9 figure's eye-moisture/tear materials, both of which use the
# classic Uber Base shader rather than the PBRSkin variant). Note the label
# ("Metallicity", "Base Bump") can differ from the underlying property name
# ("Metallic Weight", "Bump Strength") -- findPropertyByLabel() matches on
# the former.
_CHANNEL_LABELS: dict[str, str] = {
    "base_color": "Base Color",
    "metallic_weight": "Metallicity",
    "roughness": "Glossy Roughness",
    "glossy_reflectivity": "Glossy Reflectivity",
    "cutout_opacity": "Cutout Opacity",
    "bump_strength": "Base Bump",
    "top_coat_weight": "Top Coat Weight",
    "normal": "Normal Map",
    "bump": "Base Bump",
    "diffuse": "Base Color",
    "metallic": "Metallicity",
}


@dataclass(frozen=True)
class TextureMap:
    """One texture-slot assignment for an Iray material channel.

    Args:
        channel: A key into the known Iray channel labels (e.g.
            ``"base_color"``, ``"normal"``, ``"bump"``, ``"metallic"``,
            ``"roughness"``, ``"cutout_opacity"``) or an arbitrary DazScript
            property display label not in that table.
        file_path: Absolute path to an image file on disk. Must exist --
            validated by :func:`apply_texture_map` before any DazScript call
            is made, since an invalid path passed to ``setMap()`` can hang
            or crash DAZ Studio via a blocking file-not-found dialog.
    """

    channel: str
    file_path: str


@dataclass(frozen=True)
class SurfaceProperty:
    """Generic named Iray surface-channel override.

    For channels not covered by :class:`IrayMaterial`'s typed fields.

    Args:
        label: The DazScript property display label (``getLabel()``).
        value: The value to set. Must be JSON-serialisable.
    """

    label: str
    value: object


@dataclass(frozen=True)
class IrayMaterial:
    """Declarative Iray Uber Base material spec.

    Targets the classic Iray Uber Base shader specifically. Figures using
    the PBRSkin shader variant (e.g. default Genesis 9 skin materials, which
    have no ``Cutout Opacity``/``Glossy Roughness`` channels at all) need
    different channel labels -- use :class:`SurfaceProperty` /
    :func:`set_surface_property` with PBRSkin's own labels instead.

    Args:
        base_color: ``(r, g, b)`` in the 0-255 range.
        metallic_weight: 0.0-1.0.
        roughness: 0.0-1.0 (Glossy Roughness).
        glossy_reflectivity: 0.0-1.0.
        cutout_opacity: 0.0 (fully cut out) - 1.0 (opaque).
        bump_strength: Bump map strength multiplier.
        top_coat_weight: 0.0-1.0.
        textures: Texture-slot assignments, applied after the typed fields
            above.
        properties: Ad hoc named-channel overrides, applied last so they can
            supersede any typed field or texture set in the same call.
    """

    base_color: tuple[int, int, int] | None = None
    metallic_weight: float | None = None
    roughness: float | None = None
    glossy_reflectivity: float | None = None
    cutout_opacity: float | None = None
    bump_strength: float | None = None
    top_coat_weight: float | None = None
    textures: tuple[TextureMap, ...] = field(default_factory=tuple)
    properties: tuple[SurfaceProperty, ...] = field(default_factory=tuple)


def _channel_label(channel: str) -> str:
    return _CHANNEL_LABELS.get(channel, channel)


def _set_channel_value(material: "DazMaterial", label: str, value: object) -> None:
    serialized = ScriptBuilder.serialize_arg(value)
    script = ScriptBuilder.iife(f"""
        var m = {material._locator};
        if (!m) return {{"error": "material_not_found"}};
        var p = m.findPropertyByLabel({json.dumps(label)});
        if (!p) return {{"error": "property_not_found"}};
        p.setValue({serialized});
        return {{"success": true}};
    """)
    result = material._client.execute(script).value
    if not isinstance(result, dict) or result.get("success") is not True:
        error = result.get("error") if isinstance(result, dict) else "unknown_error"
        raise MaterialError(f"Failed to set Iray channel {label!r}: {error}")


def _get_channel_value(material: "DazMaterial", label: str) -> object:
    script = ScriptBuilder.iife(f"""
        var m = {material._locator};
        if (!m) return {{"error": "material_not_found"}};
        var p = m.findPropertyByLabel({json.dumps(label)});
        if (!p) return {{"error": "property_not_found"}};
        return {{"success": true, "value": p.getValue()}};
    """)
    result = material._client.execute(script).value
    if not isinstance(result, dict) or result.get("success") is not True:
        error = result.get("error") if isinstance(result, dict) else "unknown_error"
        raise MaterialError(f"Failed to read Iray channel {label!r}: {error}")
    return result.get("value")


def _set_channel_map(material: "DazMaterial", label: str, path: str) -> None:
    if not os.path.isabs(path):
        raise ValueError(f"Texture map path must be absolute: {path}")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Texture map not found: {path}")
    script = ScriptBuilder.iife(f"""
        var m = {material._locator};
        if (!m) return {{"error": "material_not_found"}};
        var p = m.findPropertyByLabel({json.dumps(label)});
        if (!p) return {{"error": "property_not_found"}};
        p.setMap({json.dumps(path)});
        return {{"success": true}};
    """)
    result = material._client.execute(script).value
    if not isinstance(result, dict) or result.get("success") is not True:
        error = result.get("error") if isinstance(result, dict) else "unknown_error"
        raise MaterialError(f"Failed to set texture map on channel {label!r}: {error}")


def apply_texture_map(material: "DazMaterial", texture: TextureMap) -> None:
    """Assign *texture* to *material*'s corresponding Iray channel.

    Args:
        material: The target material.
        texture: The texture-slot assignment.

    Raises:
        ValueError: If ``texture.file_path`` is not an absolute path.
        FileNotFoundError: If ``texture.file_path`` does not exist on disk.
            Checked before any DazScript call is made.
        MaterialError: If the material or the resolved channel property
            cannot be found on the live material.
    """
    _set_channel_map(material, _channel_label(texture.channel), texture.file_path)


def get_surface_property(material: "DazMaterial", label: str) -> object:
    """Return the current value of the named Iray surface property.

    Args:
        material: The target material.
        label: The DazScript property display label.

    Raises:
        MaterialError: If the material or property cannot be found.
    """
    return _get_channel_value(material, label)


def set_surface_property(material: "DazMaterial", prop: SurfaceProperty) -> None:
    """Set a single named Iray surface property.

    Args:
        material: The target material.
        prop: The label/value pair to set.

    Raises:
        MaterialError: If the material or property cannot be found.
    """
    _set_channel_value(material, prop.label, prop.value)


_TYPED_FIELDS = (
    "base_color",
    "metallic_weight",
    "roughness",
    "glossy_reflectivity",
    "cutout_opacity",
    "bump_strength",
    "top_coat_weight",
)


def apply_iray_material(material: "DazMaterial", spec: IrayMaterial) -> None:
    """Apply *spec* to *material* in typed-fields -> textures -> properties order.

    Args:
        material: The target material.
        spec: The material configuration. ``None``-valued typed fields are
            skipped. ``spec.properties`` is applied last, so it can
            supersede any typed field or texture set earlier in the same
            call.

    Raises:
        ValueError: If any ``spec.textures[*].file_path`` is not absolute.
        FileNotFoundError: If any ``spec.textures[*].file_path`` does not
            exist on disk. All texture paths are validated before any
            DazScript call is made, for the same reason as
            :func:`apply_texture_map`.
        MaterialError: If the material or a resolved channel property
            cannot be found on the live material.
    """
    for texture in spec.textures:
        path = texture.file_path
        if not os.path.isabs(path):
            raise ValueError(f"Texture map path must be absolute: {path}")
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Texture map not found: {path}")

    for field_name in _TYPED_FIELDS:
        value = getattr(spec, field_name)
        if value is not None:
            _set_channel_value(material, _channel_label(field_name), value)

    for texture in spec.textures:
        _set_channel_map(material, _channel_label(texture.channel), texture.file_path)

    for prop in spec.properties:
        _set_channel_value(material, prop.label, prop.value)
