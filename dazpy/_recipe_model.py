"""Frozen dataclass model for scene recipes (schema: scene-recipe.v1.schema.json).

Units are centimetres, Y-up, degrees. JSON lists become tuples; entity mappings
are plain dicts (the dataclasses are frozen, but the dicts are not deep-frozen).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, MISSING
from typing import Any, Literal, Mapping, Optional, Tuple, Union

Vec3T = Tuple[float, float, float]
LightKind = Literal["spot", "point", "distant"]
RefOrVec = Union[str, Vec3T]


@dataclass(frozen=True)
class AssetSpec:
    path: str


@dataclass(frozen=True)
class ActorSpec:
    asset: str
    position: Vec3T = (0.0, 0.0, 0.0)
    rotation: Optional[Vec3T] = None
    facing: Optional[RefOrVec] = None
    pose: Optional[str] = None


@dataclass(frozen=True)
class PropSpec:
    asset: str
    position: Vec3T = (0.0, 0.0, 0.0)
    rotation: Optional[Vec3T] = None


@dataclass(frozen=True)
class RigLightOverride:
    azimuth_deg: Optional[float] = None
    elevation_deg: Optional[float] = None
    distance: Optional[float] = None
    intensity: Optional[float] = None
    color: Optional[Tuple[int, int, int]] = None


@dataclass(frozen=True)
class RecipeRig:
    type: Literal["three_point"]
    target: str
    light_type: LightKind = "spot"
    key: Optional[RigLightOverride] = None
    fill: Optional[RigLightOverride] = None
    rim: Optional[RigLightOverride] = None


@dataclass(frozen=True)
class RecipeLight:
    type: LightKind
    position: Vec3T
    look_at: Optional[RefOrVec] = None
    rotation: Optional[Vec3T] = None
    intensity: float = 100.0
    color: Tuple[int, int, int] = (255, 255, 255)


@dataclass(frozen=True)
class RecipeEnvironment:
    type: Literal["hdri"]
    image_path: str
    intensity: float = 1.0
    rotation_deg: float = 0.0
    mode: Literal["dome_only", "dome_and_scene", "scene_only"] = "dome_only"
    draw_dome: bool = False


@dataclass(frozen=True)
class RecipeCamera:
    frame: Optional[Union[str, Tuple[str, ...]]] = None
    shot_type: Literal["extreme_wide", "wide", "full_body", "medium_wide", "medium",
                       "medium_close_up", "close_up", "extreme_close_up"] = "medium"
    azimuth_deg: float = 0.0
    elevation_deg: float = 10.0
    angle: Optional[Literal["eye_level", "high", "low", "birds_eye", "worms_eye"]] = None
    composition: Literal["center", "left_third", "right_third"] = "center"
    position: Optional[Vec3T] = None
    look_at: Optional[RefOrVec] = None
    rotation: Optional[Vec3T] = None
    focal_length: float = 50.0
    depth_of_field: bool = False
    focal_distance: Optional[float] = None


@dataclass(frozen=True)
class RenderSpec:
    engine: Optional[Literal["iray", "filament", "viewport"]] = None
    resolution: Optional[Tuple[int, int]] = None
    iray_samples: Optional[int] = None


@dataclass(frozen=True)
class ShotSpec:
    id: str
    camera: str
    output: str
    render: Optional[RenderSpec] = None


# ---- generic (de)serialisation ------------------------------------------

def _is_dc(cls: Any) -> bool:
    return hasattr(cls, "__dataclass_fields__")


def _from_value(value: Any) -> Any:
    """JSON value -> model value: lists become tuples (recursively)."""
    if isinstance(value, list):
        return tuple(_from_value(v) for v in value)
    return value


def _build(cls: Any, data: Mapping[str, Any], nested: Mapping[str, Any] = {}) -> Any:
    kwargs = {}
    for name, value in data.items():
        sub = nested.get(name)
        kwargs[name] = _build(sub, value) if sub is not None else _from_value(value)
    return cls(**kwargs)


def _to_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_to_value(v) for v in value]
    return value


def _dump(obj: Any) -> dict:
    """Dataclass -> JSON dict, omitting fields equal to their default."""
    out: dict = {}
    for f in fields(obj):
        value = getattr(obj, f.name)
        if f.default is not MISSING and value == f.default:
            continue
        out[f.name] = _dump(value) if _is_dc(value) else _to_value(value)
    return out


_NESTED = {
    ActorSpec: {}, PropSpec: {}, AssetSpec: {}, RecipeLight: {},
    RecipeEnvironment: {}, RecipeCamera: {},
    RecipeRig: {"key": RigLightOverride, "fill": RigLightOverride, "rim": RigLightOverride},
    ShotSpec: {"render": RenderSpec},
}


def _entities(cls: Any, section: Optional[Mapping[str, Any]]) -> dict:
    return {k: _build(cls, v, _NESTED[cls]) for k, v in (section or {}).items()}


@dataclass(frozen=True)
class SceneRecipe:
    recipe_version: int
    id: str
    assets: Mapping[str, AssetSpec] = field(default_factory=dict)
    actors: Mapping[str, ActorSpec] = field(default_factory=dict)
    props: Mapping[str, PropSpec] = field(default_factory=dict)
    rigs: Mapping[str, RecipeRig] = field(default_factory=dict)
    lights: Mapping[str, RecipeLight] = field(default_factory=dict)
    environment: Optional[RecipeEnvironment] = None
    cameras: Mapping[str, RecipeCamera] = field(default_factory=dict)
    shots: Tuple[ShotSpec, ...] = ()
    render: RenderSpec = field(default_factory=RenderSpec)

    @classmethod
    def from_dict(cls, data: dict) -> "SceneRecipe":
        from ._recipe_validate import validate_offline
        from .exceptions import RecipeValidationError

        report = validate_offline(data)
        if not report.ok:
            raise RecipeValidationError(report)
        lighting = data.get("lighting") or {}
        env = lighting.get("environment")
        return cls(
            recipe_version=data["recipe_version"],
            id=data["id"],
            assets=_entities(AssetSpec, data.get("assets")),
            actors=_entities(ActorSpec, data.get("actors")),
            props=_entities(PropSpec, data.get("props")),
            rigs=_entities(RecipeRig, lighting.get("rigs")),
            lights=_entities(RecipeLight, lighting.get("lights")),
            environment=_build(RecipeEnvironment, env) if env is not None else None,
            cameras=_entities(RecipeCamera, data.get("cameras")),
            shots=tuple(_build(ShotSpec, s, _NESTED[ShotSpec]) for s in data.get("shots") or ()),
            render=_build(RenderSpec, data.get("render") or {}),
        )

    @classmethod
    def from_json(cls, text: str) -> "SceneRecipe":
        return cls.from_dict(json.loads(text))

    def to_dict(self) -> dict:
        """JSON-compatible dict; empty sections and default-valued fields are omitted."""
        out: dict = {"recipe_version": self.recipe_version, "id": self.id}
        for key, section in (("assets", self.assets), ("actors", self.actors), ("props", self.props)):
            if section:
                out[key] = {k: _dump(v) for k, v in section.items()}
        lighting: dict = {}
        if self.rigs:
            lighting["rigs"] = {k: _dump(v) for k, v in self.rigs.items()}
        if self.lights:
            lighting["lights"] = {k: _dump(v) for k, v in self.lights.items()}
        if self.environment is not None:
            lighting["environment"] = _dump(self.environment)
        if lighting:
            out["lighting"] = lighting
        if self.cameras:
            out["cameras"] = {k: _dump(v) for k, v in self.cameras.items()}
        if self.shots:
            out["shots"] = [_dump(s) for s in self.shots]
        render = _dump(self.render)
        if render:
            out["render"] = render
        return out
