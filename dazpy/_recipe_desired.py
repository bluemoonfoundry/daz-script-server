"""Pure desired-state computation for scene recipes.

Turns a validated :class:`SceneRecipe` into per-node desired channel values.
Everything is derived from the recipe's own positions, never the live scene.
Channel values are plain Python (tuples of floats, floats, bools, str/None).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Literal

from ._asset_ref import AssetRef
from ._recipe_model import RecipeCamera, RecipeLight, SceneRecipe, actor_ref, prop_ref
from ._shot_geometry import look_at_euler
from .shots import DEFAULT_ASPECT, DEFAULT_FRAME_WIDTH_MM, SHOT_SIZES, Framing, framing_transform
from .lighting import _DEFAULT_FILL, _DEFAULT_KEY, _DEFAULT_RIM, _resolve_light_position
from .math3 import Vec3

if TYPE_CHECKING:  # _asset_resolve imports _recipe_ops, which imports this module
    from ._asset_resolve import ResolvedAsset

EntityKind = Literal["actor", "prop", "item", "camera", "light", "environment"]

_RIG_DEFAULTS = (("key", _DEFAULT_KEY), ("fill", _DEFAULT_FILL), ("rim", _DEFAULT_RIM))


@dataclass(frozen=True)
class DesiredEntity:
    path: str
    kind: EntityKind
    label: str
    create: dict
    channels: dict


def _t(v: Any) -> tuple:
    return tuple(float(x) for x in v)


def _v(v: Any) -> Vec3:
    return Vec3(*(float(x) for x in v))


def _spec_position(spec: Any) -> Vec3:
    """An actor or prop position; an unset actor position is the origin (v1 default)."""
    return _v(spec.position if spec.position is not None else (0.0, 0.0, 0.0))


def _recipe_position(recipe: SceneRecipe, key: str) -> Vec3:
    spec = recipe.actors.get(key) or recipe.props.get(key)
    if spec is None:
        raise KeyError(f"recipe has no actor or prop {key!r}")
    return _spec_position(spec)


# Framing.  An actor's recipe position is its root, on the floor, so framing aims
# at a height above it, assuming a standing human (Genesis-scale, ~175 cm).  The
# camera stands back so that the shot size's fit height fills the frame
# vertically at the recipe's focal length (see dazpy.shots.SHOT_SIZES, shared
# with apply_shot).  Props have no known size: aim at their position.
_RIG_ANCHOR_CM = SHOT_SIZES["medium"][1]  # rig lights light the chest, not the feet


def _subject_point(recipe: SceneRecipe, key: str, anchor_cm: float) -> Vec3:
    """The point a camera or rig aims at for subject *key*: actors are raised by *anchor_cm*."""
    p = _recipe_position(recipe, key)
    return Vec3(p.x, p.y + anchor_cm, p.z) if key in recipe.actors else p


def _aim_point(recipe: SceneRecipe, ref: Any) -> Vec3:
    """An explicit ``look_at``: an actor key aims at the chest (like rig lights),
    a prop key at its position, an ``[x, y, z]`` literal as given."""
    return _subject_point(recipe, ref, _RIG_ANCHOR_CM) if isinstance(ref, str) else _v(ref)


def _aspect(recipe: SceneRecipe) -> float:
    res = recipe.render.resolution if recipe.render is not None else None
    return res[1] / res[0] if res else DEFAULT_ASPECT


def recipe_camera_framing(cam: RecipeCamera) -> Framing:
    """The :class:`~dazpy.shots.Framing` a recipe framing camera describes."""
    subjects = (cam.frame,) if isinstance(cam.frame, str) else tuple(cam.frame or ())
    return Framing(subjects=subjects, size=cam.shot_type, angle=cam.angle or "eye_level",
                   azimuth_deg=cam.azimuth_deg,
                   elevation_deg=None if cam.angle is not None else cam.elevation_deg,
                   composition=cam.composition)


def _resolve(recipe: SceneRecipe, ref: Any) -> Vec3:
    """Resolve an actor/prop key or an [x, y, z] literal to a recipe position."""
    return _v(ref) if not isinstance(ref, str) else _recipe_position(recipe, ref)


def _asset_path(ref: AssetRef | None) -> str | None:
    if ref is not None and ref.kind != "path":
        raise ValueError(f"asset reference {ref.to_dict()!r} is not a path; resolving "
                         "product/sku/find references is not supported yet")
    return ref.path if ref is not None else None


def _path_for(ref: AssetRef | None, recipe_path: str,
              resolved: Mapping[str, ResolvedAsset] | None) -> str | None:
    """The file a reference stands for: the resolved path when *resolved* is given
    (a missing entry is an error naming *recipe_path*), else the path reference's path."""
    if resolved is None:
        return _asset_path(ref)
    if ref is None:
        return None
    if recipe_path not in resolved:
        raise ValueError(f"asset reference at {recipe_path} was not resolved")
    return resolved[recipe_path].path


def _actor_entities(recipe: SceneRecipe, name: str,
                    resolved: Mapping[str, ResolvedAsset] | None) -> list[DesiredEntity]:
    a = recipe.actors[name]
    create: dict = {"asset_path": _path_for(actor_ref(recipe, name), f"actors.{name}.asset",
                                            resolved)}
    if a.node is not None:
        create["take_over"] = a.node
        create["label"] = a.node
        rp = f"actors.{name}.asset"
        if resolved is not None and rp in resolved:
            # provenance for the take-over record (source.requested); never a replace trigger
            create["source"] = resolved[rp].to_dict()
    channels: dict = {}
    if a.node is None:
        pos = _spec_position(a)
        channels["transform"] = {"position": _t((pos.x, pos.y, pos.z)),
                                 "rotation": _actor_rotation(recipe, name)}
    elif any(v is not None for v in (a.position, a.rotation, a.facing)):
        # A taken-over actor is moved only where the recipe says so: no implicit origin.
        if a.position is None and a.facing is not None:
            raise ValueError(f"actors.{name}: facing needs an explicit position on a "
                             "taken-over actor")
        t = {"rotation": _actor_rotation(recipe, name)}
        if a.position is not None:
            t = {"position": _t(a.position), **t}
        channels["transform"] = t
    channels["pose"] = {"pose_path": a.pose}
    if a.presets:
        channels["presets"] = {"paths": [
            _path_for(ref, f"actors.{name}.presets[{i}]", resolved)
            for i, ref in enumerate(a.presets)]}
    label = a.node if a.node is not None else f"{recipe.id}:{name}"
    out = [DesiredEntity(f"actors.{name}", "actor", label, create, channels)]
    for w in a.wearing:
        if w.op == "remove":
            continue
        rp = f"actors.{name}.wearing.{w.key}"
        if resolved is None or rp not in resolved:
            raise ValueError(f"asset reference at {rp} was not resolved")
        r = resolved[rp]
        out.append(DesiredEntity(rp, "item", f"{recipe.id}:{name}.{w.key}",
                                 {"asset_path": r.path, "fit_to": f"actors.{name}",
                                  "source": r.to_dict()}, {}))
    return out


def _actor_rotation(recipe: SceneRecipe, key: str) -> tuple:
    spec = recipe.actors[key]
    if spec.rotation is not None:
        return _t(spec.rotation)
    if spec.facing is not None:
        pos, tgt = _spec_position(spec), _resolve(recipe, spec.facing)
        yaw = math.degrees(math.atan2(tgt.x - pos.x, tgt.z - pos.z))
        return (0.0, yaw, 0.0)
    return (0.0, 0.0, 0.0)


def _camera(recipe: SceneRecipe, name: str, cam: RecipeCamera) -> DesiredEntity:
    if cam.frame is not None:
        framing = recipe_camera_framing(cam)
        # A recipe framing names its subjects by key (recipe_camera_framing).
        names = [s for s in framing.subjects if isinstance(s, str)]
        points = [(_recipe_position(recipe, s), s in recipe.actors) for s in names]
        pos, aim = framing_transform(points, framing, cam.focal_length,
                                     frame_width_mm=DEFAULT_FRAME_WIDTH_MM, aspect=_aspect(recipe))
        transform = {"position": _t((pos.x, pos.y, pos.z)), "aim": _t((aim.x, aim.y, aim.z)),
                     "rotation": None}
    else:
        look = _aim_point(recipe, cam.look_at) if cam.look_at is not None else None
        aim_t = _t((look.x, look.y, look.z)) if look is not None else None
        transform = {"position": _t(cam.position), "aim": aim_t,
                     "rotation": _t(cam.rotation) if cam.rotation is not None else None}
    optics = {"focal_length": float(cam.focal_length), "depth_of_field": bool(cam.depth_of_field),
              "focal_distance": None if cam.focal_distance is None else float(cam.focal_distance)}
    return DesiredEntity(f"cameras.{name}", "camera", f"{recipe.id}:{name}", {},
                         {"transform": transform, "optics": optics})


def _light(path: str, label: str, light_type: str, pos: Vec3, rotation: tuple,
           intensity: float, color: tuple) -> DesiredEntity:
    return DesiredEntity(
        path, "light", label, {"light_type": light_type},
        {"transform": {"position": _t((pos.x, pos.y, pos.z)), "rotation": rotation},
         "output": {"intensity": float(intensity), "color": tuple(int(c) for c in color)}})


def _recipe_light(recipe: SceneRecipe, name: str, spec: RecipeLight) -> DesiredEntity:
    pos = _v(spec.position)
    if spec.look_at is not None:
        rot = _t(look_at_euler(pos, _aim_point(recipe, spec.look_at)))
    elif spec.rotation is not None:
        rot = _t(spec.rotation)
    else:
        rot = (0.0, 0.0, 0.0)
    return _light(f"lighting.lights.{name}", f"{recipe.id}:{name}", spec.type, pos, rot,
                  spec.intensity, spec.color)


def compute_desired(recipe: SceneRecipe,
                    resolved: Mapping[str, ResolvedAsset] | None = None) -> dict[str, DesiredEntity]:
    """Compute every entity's desired channels, keyed by ``DesiredEntity.path``."""
    out: dict = {}

    def add(e: DesiredEntity) -> None:
        out[e.path] = e

    for name in recipe.actors:
        for e in _actor_entities(recipe, name, resolved):
            add(e)
    for name, p in recipe.props.items():
        add(DesiredEntity(
            f"props.{name}", "prop", f"{recipe.id}:{name}",
            {"asset_path": _path_for(prop_ref(recipe, name), f"props.{name}.asset", resolved)},
            {"transform": {"position": _t(p.position),
                           "rotation": _t(p.rotation) if p.rotation is not None else (0.0, 0.0, 0.0)}}))
    for name, cam in recipe.cameras.items():
        add(_camera(recipe, name, cam))
    for name, light in recipe.lights.items():
        add(_recipe_light(recipe, name, light))
    for name, rig in recipe.rigs.items():
        target = _subject_point(recipe, rig.target, _RIG_ANCHOR_CM)
        for role, default in _RIG_DEFAULTS:
            ov = getattr(rig, role)

            def pick(field: str, ov=ov, default=default):
                val = getattr(ov, field, None) if ov is not None else None
                return getattr(default, field) if val is None else val

            spec = default.__class__(
                role=role, azimuth_deg=pick("azimuth_deg"), elevation_deg=pick("elevation_deg"),
                distance=pick("distance"), intensity=pick("intensity"), color=pick("color"))
            pos = _resolve_light_position(target, spec)
            add(_light(f"lighting.rigs.{name}.{role}", f"{recipe.id}:{name}.{role}", rig.light_type,
                       pos, _t(look_at_euler(pos, target)), spec.intensity, spec.color))
    if recipe.environment is not None:
        e = recipe.environment
        add(DesiredEntity("lighting.environment", "environment", f"{recipe.id}:environment", {},
                          {"environment": {"type": e.type, "image_path": e.image_path,
                                           "intensity": float(e.intensity),
                                           "rotation_deg": float(e.rotation_deg),
                                           "mode": e.mode, "draw_dome": bool(e.draw_dome)}}))
    return out
