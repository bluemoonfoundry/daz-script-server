"""Offline (no Studio) validation of scene-recipe documents.

Hand-written walker that mirrors schemas/scene-recipe.v1.schema.json and adds
cross-reference checks the schema cannot express. Collects every error in one
pass. Issues are written to be read by an LLM: precise dotted paths
(``shots[1].camera``), stable codes, the allowed values, and a closest-match
suggestion for typos.

Actor and prop keys share one namespace (``duplicate_key``).  Reference
namespaces: ``actor.asset``/``prop.asset`` name an entry in ``assets``; ``shots[].camera`` names a ``cameras`` entry; ``rig.target``,
``facing``, ``look_at`` and camera ``frame`` name an actor or prop.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Any
from collections.abc import Iterable

from ._recipe_json import to_jsonable

_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_LIGHT_TYPES = ("distant", "point", "spot")
_ENGINES = ("filament", "iray", "viewport")
_SHOT_TYPES = ("close_up", "extreme_close_up", "extreme_wide", "full_body", "medium",
               "medium_close_up", "medium_wide", "wide")
_ANGLES = ("birds_eye", "eye_level", "high", "low", "worms_eye")
_COMPOSITIONS = ("center", "left_third", "right_third")


@dataclass(frozen=True)
class RecipeIssue:
    path: str
    code: str
    message: str
    allowed: tuple[str, ...] | None = None
    suggestion: str | None = None

    def to_dict(self) -> dict:
        return to_jsonable(self)


@dataclass(frozen=True)
class ValidationReport:
    ok: bool
    errors: tuple[RecipeIssue, ...]
    warnings: tuple[RecipeIssue, ...]

    def to_dict(self) -> dict:
        return to_jsonable(self)


def file_not_found(path: str, file: str) -> RecipeIssue:
    """The issue for a recipe *path* naming *file*, which Studio cannot find."""
    return RecipeIssue(path, "file_not_found",
                       f"File not found: {file!r}. Content paths starting with '/' are looked "
                       "up in every Daz content directory; other paths must be absolute and exist.")


def _closest(name: Any, candidates: Iterable[str]) -> str | None:
    if not isinstance(name, str):
        return None
    m = difflib.get_close_matches(name, list(candidates), n=1, cutoff=0.6)
    return m[0] if m else None


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_int(v: Any) -> bool:
    return (isinstance(v, int) and not isinstance(v, bool)) or (
        isinstance(v, float) and v.is_integer())


def _join(base: str, name: str) -> str:
    return f"{base}.{name}" if base else name


class _Validator:
    def __init__(self, data: Any):
        self.data = data
        self.errors: list[RecipeIssue] = []
        self.refs: list[tuple[str, Any, str]] = []  # (path, value, namespace)

    def err(self, path, code, message, allowed=None, suggestion=None):
        self.errors.append(RecipeIssue(
            path, code, message,
            tuple(allowed) if allowed is not None else None, suggestion))

    # ---- generic helpers -------------------------------------------------
    def obj(self, v, path, fields, required=(), reserved=()) -> bool:
        """Check v is an object; report unknown/reserved/missing fields."""
        if not isinstance(v, dict):
            self.err(path, "invalid_type", "must be an object")
            return False
        for k in v:
            if k in fields:
                continue
            p = _join(path, k)
            if k in reserved:
                self.err(p, "unsupported_in_version",
                         f"'{k}' is reserved and not supported in recipe_version 1")
            else:
                self.err(p, "unknown_field", f"unknown field '{k}'",
                         allowed=sorted(fields), suggestion=_closest(k, fields))
        for k in required:
            if k not in v:
                self.err(_join(path, k), "missing_field", f"missing required field '{k}'")
        return True

    def string(self, v, path) -> None:
        if not isinstance(v, str):
            self.err(path, "invalid_type", "must be a string")
        elif not v:
            self.err(path, "invalid_type", "must be a non-empty string")

    def number(self, v, path, minimum=None, exclusive_min=None) -> None:
        if not _is_num(v):
            self.err(path, "invalid_type", "must be a number")
        elif exclusive_min is not None and v <= exclusive_min:
            self.err(path, "out_of_range", f"must be > {exclusive_min}")
        elif minimum is not None and v < minimum:
            self.err(path, "out_of_range", f"must be >= {minimum}")

    def integer(self, v, path, minimum) -> None:
        if not _is_int(v):
            self.err(path, "invalid_type", "must be an integer")
        elif v < minimum:
            self.err(path, "out_of_range", f"must be >= {minimum}")

    def boolean(self, v, path) -> None:
        if not isinstance(v, bool):
            self.err(path, "invalid_type", "must be a boolean")

    def enum(self, v, path, values) -> None:
        if not (isinstance(v, str) and v in values):
            self.err(path, "invalid_enum", f"must be one of {sorted(values)}",
                     allowed=sorted(values), suggestion=_closest(v, values))

    def vec3(self, v, path) -> None:
        if not (isinstance(v, list) and len(v) == 3):
            self.err(path, "invalid_type", "must be an array of 3 numbers")
            return
        for i, x in enumerate(v):
            if not _is_num(x):
                self.err(f"{path}[{i}]", "invalid_type", "must be a number")

    def color(self, v, path) -> None:
        if not (isinstance(v, list) and len(v) == 3):
            self.err(path, "invalid_type", "must be an array of 3 integers (0-255)")
            return
        for i, x in enumerate(v):
            if not _is_int(x):
                self.err(f"{path}[{i}]", "invalid_type", "must be an integer")
            elif not 0 <= x <= 255:
                self.err(f"{path}[{i}]", "out_of_range", "must be between 0 and 255")

    def ref(self, v, path, ns) -> None:
        """Record a reference to resolve once all entity keys are known."""
        if not isinstance(v, str):
            self.err(path, "invalid_type", "must be a string key")
        elif not _KEY_RE.match(v):
            self.err(path, "invalid_id", "must match ^[A-Za-z0-9_-]{1,64}$")
        else:
            self.refs.append((path, v, ns))

    def ref_or_vec3(self, v, path) -> None:
        if isinstance(v, str):
            self.ref(v, path, "actor_or_prop")
        elif isinstance(v, list):
            self.vec3(v, path)
        else:
            self.err(path, "invalid_type", "must be an entity key (string) or [x, y, z]")

    def entities(self, v, path, check) -> dict[str, Any]:
        if not isinstance(v, dict):
            self.err(path, "invalid_type", "must be an object")
            return {}
        for k, item in v.items():
            p = _join(path, k)
            if not _KEY_RE.match(k):
                self.err(p, "invalid_id", "entity key must match ^[A-Za-z0-9_-]{1,64}$")
            check(item, p)
        return v

    # ---- sections --------------------------------------------------------
    def render(self, v, path) -> None:
        if not self.obj(v, path, ("engine", "resolution", "iray_samples")):
            return
        if "engine" in v:
            self.enum(v["engine"], f"{path}.engine", _ENGINES)
        if "resolution" in v:
            r, p = v["resolution"], f"{path}.resolution"
            if not (isinstance(r, list) and len(r) == 2):
                self.err(p, "invalid_type", "must be an array of 2 integers [width, height]")
            else:
                for i, x in enumerate(r):
                    self.integer(x, f"{p}[{i}]", 1)
        if "iray_samples" in v:
            self.integer(v["iray_samples"], f"{path}.iray_samples", 1)

    def asset(self, v, p) -> None:
        if self.obj(v, p, ("path",), ("path",), ("ref",)) and "path" in v:
            self.string(v["path"], f"{p}.path")

    def placed(self, v, p, extra=(), reserved=()) -> bool:
        fields = ("asset", "position", "rotation") + tuple(extra)
        if not self.obj(v, p, fields, ("asset",), reserved):
            return False
        if "asset" in v:
            self.ref(v["asset"], f"{p}.asset", "asset")
        if "position" in v:
            self.vec3(v["position"], f"{p}.position")
        if "rotation" in v:
            self.vec3(v["rotation"], f"{p}.rotation")
        return True

    def actor(self, v, p) -> None:
        if not self.placed(v, p, ("facing", "pose"), ("blocking", "interaction")):
            return
        if "facing" in v:
            self.ref_or_vec3(v["facing"], f"{p}.facing")
        if "pose" in v:
            self.string(v["pose"], f"{p}.pose")
        if "facing" in v and "rotation" in v:
            self.err(f"{p}.rotation", "mutually_exclusive",
                     "'facing' and 'rotation' are mutually exclusive; remove one")

    def prop(self, v, p) -> None:
        self.placed(v, p)

    def rig(self, v, p) -> None:
        if not self.obj(v, p, ("type", "target", "light_type", "key", "fill", "rim"),
                        ("type", "target")):
            return
        if "type" in v and v["type"] != "three_point":
            self.enum(v["type"], f"{p}.type", ("three_point",))
        if "target" in v:
            self.ref(v["target"], f"{p}.target", "actor_or_prop")
        if "light_type" in v:
            self.enum(v["light_type"], f"{p}.light_type", _LIGHT_TYPES)
        for role in ("key", "fill", "rim"):
            if role in v:
                self.rig_override(v[role], f"{p}.{role}")

    def rig_override(self, v, p) -> None:
        if not self.obj(v, p, ("azimuth_deg", "elevation_deg", "distance", "intensity", "color")):
            return
        for k in ("azimuth_deg", "elevation_deg"):
            if k in v:
                self.number(v[k], f"{p}.{k}")
        if "distance" in v:
            self.number(v["distance"], f"{p}.distance", exclusive_min=0)
        if "intensity" in v:
            self.number(v["intensity"], f"{p}.intensity", minimum=0)
        if "color" in v:
            self.color(v["color"], f"{p}.color")

    def light(self, v, p) -> None:
        if not self.obj(v, p, ("type", "position", "look_at", "rotation", "intensity", "color"),
                        ("type", "position")):
            return
        if "type" in v:
            self.enum(v["type"], f"{p}.type", _LIGHT_TYPES)
        if "position" in v:
            self.vec3(v["position"], f"{p}.position")
        if "look_at" in v:
            self.ref_or_vec3(v["look_at"], f"{p}.look_at")
        if "rotation" in v:
            self.vec3(v["rotation"], f"{p}.rotation")
        if "intensity" in v:
            self.number(v["intensity"], f"{p}.intensity", minimum=0)
        if "color" in v:
            self.color(v["color"], f"{p}.color")
        if "look_at" in v and "rotation" in v:
            self.err(f"{p}.rotation", "mutually_exclusive",
                     "'look_at' and 'rotation' are mutually exclusive; remove one")

    def environment(self, v, p) -> None:
        if not self.obj(v, p, ("type", "image_path", "intensity", "rotation_deg", "mode",
                               "draw_dome"), ("type", "image_path")):
            return
        if "type" in v and v["type"] != "hdri":
            self.enum(v["type"], f"{p}.type", ("hdri",))
        if "image_path" in v:
            self.string(v["image_path"], f"{p}.image_path")
        if "intensity" in v:
            self.number(v["intensity"], f"{p}.intensity", minimum=0)
        if "rotation_deg" in v:
            self.number(v["rotation_deg"], f"{p}.rotation_deg")
        if "mode" in v:
            self.enum(v["mode"], f"{p}.mode", ("dome_only", "dome_and_scene", "scene_only"))
        if "draw_dome" in v:
            self.boolean(v["draw_dome"], f"{p}.draw_dome")

    def camera(self, v, p) -> None:
        if not self.obj(v, p, ("frame", "shot_type", "azimuth_deg", "elevation_deg", "angle",
                               "composition", "position", "look_at", "rotation", "focal_length",
                               "depth_of_field", "focal_distance")):
            return
        if "frame" in v:
            f, fp = v["frame"], f"{p}.frame"
            if isinstance(f, list):
                if not f:
                    self.err(fp, "out_of_range", "must list at least one entity key")
                for i, x in enumerate(f):
                    self.ref(x, f"{fp}[{i}]", "actor_or_prop")
            else:
                self.ref(f, fp, "actor_or_prop")
        if "shot_type" in v:
            self.enum(v["shot_type"], f"{p}.shot_type", _SHOT_TYPES)
        if "angle" in v:
            self.enum(v["angle"], f"{p}.angle", _ANGLES)
            if "elevation_deg" in v:
                self.err(f"{p}.elevation_deg", "mutually_exclusive",
                         "'angle' and 'elevation_deg' both set the camera elevation; remove one")
        if "composition" in v:
            self.enum(v["composition"], f"{p}.composition", _COMPOSITIONS)
        for k in ("azimuth_deg", "elevation_deg"):
            if k in v:
                self.number(v[k], f"{p}.{k}")
        if "position" in v:
            self.vec3(v["position"], f"{p}.position")
        if "look_at" in v:
            self.ref_or_vec3(v["look_at"], f"{p}.look_at")
        if "rotation" in v:
            self.vec3(v["rotation"], f"{p}.rotation")
        if "focal_length" in v:
            self.number(v["focal_length"], f"{p}.focal_length", exclusive_min=0)
        if "depth_of_field" in v:
            self.boolean(v["depth_of_field"], f"{p}.depth_of_field")
        if "focal_distance" in v:
            self.number(v["focal_distance"], f"{p}.focal_distance", exclusive_min=0)
        self.camera_mode(v, p)

    def camera_mode(self, v, p) -> None:
        """A camera is either framing (frame) or explicit (position + look_at/rotation)."""
        explicit_keys = [k for k in ("position", "look_at", "rotation") if k in v]
        if "frame" in v:
            for k in explicit_keys:
                self.err(f"{p}.{k}", "mutually_exclusive",
                         f"'frame' (auto-framing) and '{k}' (explicit placement) are mutually "
                         "exclusive; remove one")
        elif explicit_keys:
            if "position" not in v:
                self.err(f"{p}.position", "missing_field",
                         "explicit cameras need 'position' plus 'look_at' or 'rotation'")
            if "look_at" not in v and "rotation" not in v:
                self.err(f"{p}.look_at", "missing_field",
                         "explicit cameras need 'look_at' or 'rotation'")
            for k in ("shot_type", "azimuth_deg", "elevation_deg", "angle", "composition"):
                if k in v:
                    self.err(f"{p}.{k}", "mutually_exclusive",
                             f"'{k}' only applies to framing cameras (with 'frame'); remove it "
                             "or use 'frame' instead of explicit placement")
        else:
            self.err(f"{p}.frame", "missing_field",
                     "camera needs 'frame' (auto-framing) or 'position' plus "
                     "'look_at'/'rotation' (explicit)")

    def shots(self, v, path) -> list[Any]:
        if not isinstance(v, list):
            self.err(path, "invalid_type", "must be an array")
            return []
        seen: dict[str, int] = {}
        for i, s in enumerate(v):
            p = f"{path}[{i}]"
            if not self.obj(s, p, ("id", "camera", "output", "render", "allow_crop"),
                            ("id", "camera", "output"), ("movement",)):
                continue
            if "id" in s:
                sid = s["id"]
                if not isinstance(sid, str):
                    self.err(f"{p}.id", "invalid_type", "must be a string")
                elif not _KEY_RE.match(sid):
                    self.err(f"{p}.id", "invalid_id", "must match ^[A-Za-z0-9_-]{1,64}$")
                elif sid in seen:
                    self.err(f"{p}.id", "duplicate_shot_id",
                             f"shot id '{sid}' already used by shots[{seen[sid]}]")
                else:
                    seen[sid] = i
            if "camera" in s:
                self.ref(s["camera"], f"{p}.camera", "camera")
            if "output" in s:
                self.string(s["output"], f"{p}.output")
            if "render" in s:
                self.render(s["render"], f"{p}.render")
            if "allow_crop" in s:
                self.boolean(s["allow_crop"], f"{p}.allow_crop")
        return v

    # ---- driver ----------------------------------------------------------
    def run(self) -> None:
        d = self.data
        if not isinstance(d, dict):
            self.err("$", "invalid_type", "recipe must be a JSON object")
            return
        if "recipe_version" in d:
            rv = d["recipe_version"]
            if isinstance(rv, bool) or not isinstance(rv, int):
                self.err("recipe_version", "invalid_type", "must be the integer 1")
                return
            if rv != 1:
                self.err("recipe_version", "unsupported_version",
                         f"recipe_version {rv} is not supported; this dazpy reads version 1",
                         allowed=("1",))
                return
        top = ("recipe_version", "id", "assets", "actors", "props", "lighting", "cameras",
               "shots", "render")
        self.obj(d, "", top, ("recipe_version", "id"), ("checks",))
        if "id" in d:
            self.string(d["id"], "id")
        assets = self.entities(d["assets"], "assets", self.asset) if "assets" in d else {}
        actors = self.entities(d["actors"], "actors", self.actor) if "actors" in d else {}
        props = self.entities(d["props"], "props", self.prop) if "props" in d else {}
        cameras = self.entities(d["cameras"], "cameras", self.camera) if "cameras" in d else {}
        env = None
        if "lighting" in d:
            lg = d["lighting"]
            if self.obj(lg, "lighting", ("rigs", "lights", "environment")):
                if "rigs" in lg:
                    self.entities(lg["rigs"], "lighting.rigs", self.rig)
                if "lights" in lg:
                    self.entities(lg["lights"], "lighting.lights", self.light)
                if "environment" in lg:
                    env = lg["environment"]
                    self.environment(env, "lighting.environment")
        shots = self.shots(d["shots"], "shots") if "shots" in d else []
        if "render" in d:
            self.render(d["render"], "render")
        for k in props:
            if k in actors:
                self.err(f"props.{k}", "duplicate_key",
                         f"key '{k}' is already used by actors.{k}; actor and prop keys share one "
                         "namespace (node labels, facing/frame/target references)")
        self.resolve_refs(assets, actors, props, cameras)
        if isinstance(env, dict):
            self.check_environment_engine(d, shots)

    def resolve_refs(self, assets, actors, props, cameras) -> None:
        spaces = {
            "asset": ("assets", sorted(assets)),
            "camera": ("cameras", sorted(cameras)),
            "actor_or_prop": ("actors or props", sorted(set(actors) | set(props))),
        }
        for path, value, ns in self.refs:
            label, keys = spaces[ns]
            if value in keys:
                continue
            self.err(path, "unknown_reference",
                     f"'{value}' is not defined in {label}" +
                     ("" if keys else f" (there are no {label})"),
                     allowed=keys, suggestion=_closest(value, keys))

    def check_environment_engine(self, d, shots) -> None:
        render = d.get("render")
        engine = render.get("engine") if isinstance(render, dict) else None
        if engine != "iray":
            shown = "omitted" if engine is None else repr(engine)
            self.err("render.engine", "environment_requires_iray",
                     f"lighting.environment (HDRI) is only rendered by iray, but render.engine "
                     f"is {shown}; set render.engine to 'iray' or remove the environment",
                     allowed=("iray",))
        for i, s in enumerate(shots):
            r = s.get("render") if isinstance(s, dict) else None
            eng = r.get("engine") if isinstance(r, dict) else None
            if eng is not None and eng != "iray":
                self.err(f"shots[{i}].render.engine", "environment_requires_iray",
                         f"lighting.environment (HDRI) is only rendered by iray, but this shot "
                         f"uses {eng!r}", allowed=("iray",))


def validate_offline(data: object) -> ValidationReport:
    """Validate a recipe dict without contacting DAZ Studio; collects all errors."""
    v = _Validator(data)
    v.run()
    errors = tuple(v.errors)
    return ValidationReport(ok=not errors, errors=errors, warnings=())
