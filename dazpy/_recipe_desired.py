"""Pure desired-state computation for scene recipes.

Turns a validated :class:`SceneRecipe` into per-node desired channel values.
Everything is derived from the recipe's own positions, never the live scene.
Channel values are plain Python (tuples of floats, floats, bools, str/None).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal, Optional

from ._recipe_model import RecipeCamera, RecipeLight, SceneRecipe
from ._shot_geometry import look_at_euler
from .shots import DEFAULT_ASPECT, DEFAULT_FRAME_WIDTH_MM, SHOT_SIZES, Framing, framing_transform
from .lighting import _DEFAULT_FILL, _DEFAULT_KEY, _DEFAULT_RIM, _resolve_light_position
from .math3 import Vec3

EntityKind = Literal["actor", "prop", "camera", "light", "environment"]

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


def _recipe_position(recipe: SceneRecipe, key: str) -> Vec3:
    spec = recipe.actors.get(key) or recipe.props.get(key)
    return _v(spec.position)


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
    subjects = (cam.frame,) if isinstance(cam.frame, str) else tuple(cam.frame)
    return Framing(subjects=subjects, size=cam.shot_type, angle=cam.angle or "eye_level",
                   azimuth_deg=cam.azimuth_deg,
                   elevation_deg=None if cam.angle is not None else cam.elevation_deg,
                   composition=cam.composition)


def _resolve(recipe: SceneRecipe, ref: Any) -> Vec3:
    """Resolve an actor/prop key or an [x, y, z] literal to a recipe position."""
    return _v(ref) if not isinstance(ref, str) else _recipe_position(recipe, ref)


def _asset_path(recipe: SceneRecipe, key: str) -> str:
    return recipe.assets[key].path


def _actor_rotation(recipe: SceneRecipe, key: str) -> tuple:
    spec = recipe.actors[key]
    if spec.rotation is not None:
        return _t(spec.rotation)
    if spec.facing is not None:
        pos, tgt = _v(spec.position), _resolve(recipe, spec.facing)
        yaw = math.degrees(math.atan2(tgt.x - pos.x, tgt.z - pos.z))
        return (0.0, yaw, 0.0)
    return (0.0, 0.0, 0.0)


def _camera(recipe: SceneRecipe, name: str, cam: RecipeCamera) -> DesiredEntity:
    if cam.frame is not None:
        framing = recipe_camera_framing(cam)
        points = [(_recipe_position(recipe, s), s in recipe.actors) for s in framing.subjects]
        pos, aim = framing_transform(points, framing, cam.focal_length,
                                     frame_width_mm=DEFAULT_FRAME_WIDTH_MM, aspect=_aspect(recipe))
        transform = {"position": _t((pos.x, pos.y, pos.z)), "aim": _t((aim.x, aim.y, aim.z)),
                     "rotation": None}
    else:
        look = _aim_point(recipe, cam.look_at) if cam.look_at is not None else None
        aim = _t((look.x, look.y, look.z)) if look is not None else None
        transform = {"position": _t(cam.position), "aim": aim,
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


def compute_desired(recipe: SceneRecipe) -> "dict[str, DesiredEntity]":
    """Compute every entity's desired channels, keyed by ``DesiredEntity.path``."""
    out: dict = {}

    def add(e: DesiredEntity) -> None:
        out[e.path] = e

    for name, a in recipe.actors.items():
        add(DesiredEntity(
            f"actors.{name}", "actor", f"{recipe.id}:{name}",
            {"asset_path": _asset_path(recipe, a.asset)},
            {"transform": {"position": _t(a.position), "rotation": _actor_rotation(recipe, name)},
             "pose": {"pose_path": a.pose}}))
    for name, p in recipe.props.items():
        add(DesiredEntity(
            f"props.{name}", "prop", f"{recipe.id}:{name}",
            {"asset_path": _asset_path(recipe, p.asset)},
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

            def pick(field: str):
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
