"""Frozen dataclass model for scene recipes (schema: scene-recipe.v1.schema.json).

Units are centimetres, Y-up, degrees. JSON lists become tuples; entity mappings
are plain dicts (the dataclasses are frozen, but the dicts are not deep-frozen).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, MISSING
from typing import Any, Literal
from collections.abc import Mapping

from ._asset_ref import AssetRef, parse_ref

Vec3T = tuple[float, float, float]
LightKind = Literal["spot", "point", "distant"]
RefOrVec = str | Vec3T


@dataclass(frozen=True)
class TypeSelector:
    """Selects every fitted item whose content type matches *type* (friendly name or raw prefix)."""
    type: str


Selector = str | TypeSelector  # str = exact Scene-pane label


@dataclass(frozen=True)
class WearingEntry:
    """One fitted-item operation of an actor (spec 6.4).

    ``add``: *ref* is the item; ``replace``: *ref* is the ``with`` item and *target*
    the selector; ``remove``: only *target*.
    """
    op: Literal["add", "replace", "remove"]
    key: str | None
    ref: AssetRef | None
    target: Selector | None
    if_missing: Literal["error", "add", "ignore"] = "error"


@dataclass(frozen=True)
class AssetSpec:
    ref: AssetRef


@dataclass(frozen=True)
class ActorSpec:
    # str = key into the top-level ``assets`` when it names one, else a path reference
    asset: str | AssetRef | None = None
    # None = "not set"; compute_desired applies the v1 default (0, 0, 0)
    position: Vec3T | None = None
    rotation: Vec3T | None = None
    facing: RefOrVec | None = None
    pose: str | None = None
    node: str | None = None
    presets: tuple[AssetRef, ...] = ()
    wearing: tuple[WearingEntry, ...] = ()


@dataclass(frozen=True)
class PropSpec:
    asset: str | AssetRef
    position: Vec3T = (0.0, 0.0, 0.0)
    rotation: Vec3T | None = None


@dataclass(frozen=True)
class RigLightOverride:
    azimuth_deg: float | None = None
    elevation_deg: float | None = None
    distance: float | None = None
    intensity: float | None = None
    color: tuple[int, int, int] | None = None


@dataclass(frozen=True)
class RecipeRig:
    type: Literal["three_point"]
    target: str
    light_type: LightKind = "spot"
    key: RigLightOverride | None = None
    fill: RigLightOverride | None = None
    rim: RigLightOverride | None = None


@dataclass(frozen=True)
class RecipeLight:
    type: LightKind
    position: Vec3T
    look_at: RefOrVec | None = None
    rotation: Vec3T | None = None
    intensity: float = 100.0
    color: tuple[int, int, int] = (255, 255, 255)


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
    frame: str | tuple[str, ...] | None = None
    shot_type: Literal["extreme_wide", "wide", "full_body", "medium_wide", "medium",
                       "medium_close_up", "close_up", "extreme_close_up"] = "medium"
    azimuth_deg: float = 0.0
    elevation_deg: float = 10.0
    angle: Literal["eye_level", "high", "low", "birds_eye", "worms_eye"] | None = None
    composition: Literal["center", "left_third", "right_third"] = "center"
    position: Vec3T | None = None
    look_at: RefOrVec | None = None
    rotation: Vec3T | None = None
    focal_length: float = 50.0
    depth_of_field: bool = False
    focal_distance: float | None = None


@dataclass(frozen=True)
class RenderSpec:
    engine: Literal["iray", "filament", "viewport"] | None = None
    resolution: tuple[int, int] | None = None
    iray_samples: int | None = None


@dataclass(frozen=True)
class ShotSpec:
    id: str
    camera: str
    output: str
    render: RenderSpec | None = None
    allow_crop: bool = False


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


def _selector_from_json(v: Any) -> Selector:
    return TypeSelector(v["type"]) if isinstance(v, Mapping) else v


def _wearing_from_json(e: Mapping[str, Any]) -> WearingEntry:
    if "add" in e:
        return WearingEntry("add", e["key"], parse_ref(e["add"]), None)
    if "replace" in e:
        return WearingEntry("replace", e["key"], parse_ref(e["with"]),
                            _selector_from_json(e["replace"]), e.get("if_missing", "error"))
    return WearingEntry("remove", None, None, _selector_from_json(e["remove"]),
                        e.get("if_missing", "error"))


def _wearing_to_json(w: WearingEntry) -> dict:
    sel = {"type": w.target.type} if isinstance(w.target, TypeSelector) else w.target
    if w.op == "add":
        return {"add": w.ref.to_dict(), "key": w.key}  # type: ignore[union-attr]
    out: dict = {w.op: sel}
    if w.op == "replace":
        out["with"] = w.ref.to_dict()  # type: ignore[union-attr]
        out["key"] = w.key
    if w.if_missing != "error":
        out["if_missing"] = w.if_missing
    return out


def _asset_value(v: Any) -> str | AssetRef:
    """An actor/prop ``asset``: a string stays a string, an object becomes an AssetRef."""
    return parse_ref(v) if isinstance(v, Mapping) else v


def _build_actor(data: Mapping[str, Any]) -> ActorSpec:
    kwargs = {k: _from_value(v) for k, v in data.items()
              if k not in ("asset", "presets", "wearing")}
    if "asset" in data:
        kwargs["asset"] = _asset_value(data["asset"])
    kwargs["presets"] = tuple(parse_ref(r) for r in data.get("presets") or ())
    kwargs["wearing"] = tuple(_wearing_from_json(e) for e in data.get("wearing") or ())
    return ActorSpec(**kwargs)


def _build_prop(data: Mapping[str, Any]) -> PropSpec:
    kwargs = {k: _from_value(v) for k, v in data.items() if k != "asset"}
    return PropSpec(asset=_asset_value(data["asset"]), **kwargs)


def _build_asset(data: Any) -> AssetSpec:
    return AssetSpec(parse_ref(data))  # v1 {"path": ...} objects are valid asset refs


def _to_value(value: Any) -> Any:
    if isinstance(value, AssetRef):
        return value.to_dict()
    if isinstance(value, WearingEntry):
        return _wearing_to_json(value)
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
        out[f.name] = _dump(value) if _is_dc(value) and not isinstance(
            value, (AssetRef, WearingEntry)) else _to_value(value)
    return out


_NESTED: dict[Any, Mapping[str, Any]] = {
    RecipeLight: {}, RecipeEnvironment: {}, RecipeCamera: {},
    RecipeRig: {"key": RigLightOverride, "fill": RigLightOverride, "rim": RigLightOverride},
    ShotSpec: {"render": RenderSpec},
}


def _entities(cls: Any, section: Mapping[str, Any] | None) -> dict:
    build = {ActorSpec: _build_actor, PropSpec: _build_prop, AssetSpec: _build_asset}.get(cls)
    return {k: build(v) if build else _build(cls, v, _NESTED[cls])
            for k, v in (section or {}).items()}


def _resolve_key(recipe: SceneRecipe, asset: str | AssetRef | None) -> AssetRef | None:
    if isinstance(asset, str):
        spec = recipe.assets.get(asset)
        return spec.ref if spec is not None else AssetRef(path=asset)
    return asset


def actor_ref(recipe: SceneRecipe, key: str) -> AssetRef | None:
    """The actor's base-figure reference; a key into ``assets`` is resolved through it."""
    return _resolve_key(recipe, recipe.actors[key].asset)


def prop_ref(recipe: SceneRecipe, key: str) -> AssetRef:
    """The prop's asset reference; a key into ``assets`` is resolved through it."""
    return _resolve_key(recipe, recipe.props[key].asset)  # type: ignore[return-value]


@dataclass(frozen=True)
class SceneRecipe:
    recipe_version: int
    id: str
    assets: Mapping[str, AssetSpec] = field(default_factory=dict)
    actors: Mapping[str, ActorSpec] = field(default_factory=dict)
    props: Mapping[str, PropSpec] = field(default_factory=dict)
    rigs: Mapping[str, RecipeRig] = field(default_factory=dict)
    lights: Mapping[str, RecipeLight] = field(default_factory=dict)
    environment: RecipeEnvironment | None = None
    cameras: Mapping[str, RecipeCamera] = field(default_factory=dict)
    shots: tuple[ShotSpec, ...] = ()
    render: RenderSpec = field(default_factory=RenderSpec)

    @classmethod
    def from_dict(cls, data: dict) -> SceneRecipe:
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
    def from_json(cls, text: str) -> SceneRecipe:
        return cls.from_dict(json.loads(text))

    def to_dict(self) -> dict:
        """JSON-compatible dict; empty sections and default-valued fields are omitted."""
        out: dict = {"recipe_version": self.recipe_version, "id": self.id}
        if self.assets:
            # v1 assets are {"path": ...} objects; v2 assets are asset references
            out["assets"] = {k: {"path": v.ref.path} if self.recipe_version == 1 else v.ref.to_dict()
                             for k, v in self.assets.items()}
        for key, section in (("actors", self.actors), ("props", self.props)):
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
