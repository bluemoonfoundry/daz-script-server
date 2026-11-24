"""Pre-render scene checks: is each figure in frame, and will anything light the render?

One Studio script (:func:`gather_script`) reads the cameras, figures, lights and
environment; the checks themselves (:func:`framing_findings`,
:func:`lighting_findings`) are pure Python over that data.

Projection (live-verified on Studio 4.24 against viewport renders of a 100 cm
cube at 3:2 and 2:3): the camera looks down its local ``-Z``; its field of view
(``DzCamera.getFieldOfView()``, radians, ``2*atan(frame_width / (2*focal_length))``)
spans the frame's *height* whatever the aspect ratio, and the width spans
``height * render aspect`` (``DzRenderOptions.aspect``, width / height).

Lighting (live-verified on Studio 4.24 with Iray): with no lights, environment
mode "Dome and Scene" or "Sun-Sky Only" at intensity 1 still lights the scene
(even with no environment map), while intensity 0 or "Scene Only" renders
black. On Studio 4 the environment settings live on a ``DzEnvironmentNode`` in
the scene; on Studio 6 among the render-element objects. A cleared scene has no
environment node until the next render creates the default one (Dome and
Scene, intensity 1), which lights it. The OpenGL engines always light the scene
(default lights), so they are not checked.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Mapping, Optional, Sequence

from ._recipe_json import to_jsonable
from ._script_builder import ScriptBuilder
from .exceptions import DazError
from .math3 import Quat, Vec3

if TYPE_CHECKING:
    from ._client import DazClient

Severity = Literal["error", "warning"]

# DzEnvironmentNode "Environment Mode" values that light the scene by themselves.
# 0 Dome and Scene, 1 Dome Only, 2 Sun-Sky Only, 3 Scene Only.
_LIT_ENVIRONMENT_MODES = (0, 1, 2)
_OPENGL_ENGINES = ("viewport", "multi_pass_opengl")
_EDGE_EPS = 1e-3  # NDC slack so a box touching the frame edge is not "out"


@dataclass(frozen=True)
class CheckFinding:
    """One problem found by a scene check.

    ``severity``: ``"error"`` (the render is almost certainly wrong) or
    ``"warning"`` (worth a look). ``code``: stable identifier. ``subject``: the
    figure, camera or ``"lighting"`` the finding is about. ``camera``: the camera
    label checked, when the finding is about framing. ``shot``: the recipe shot
    id (recipe checks only). ``sides``: for ``subject_out_of_frame``, which frame
    edges the figure crosses (``"top"``, ``"bottom"``, ``"left"``, ``"right"``,
    ``"behind"`` for a figure partly behind the camera).
    """

    severity: Severity
    code: str
    subject: str
    message: str
    camera: Optional[str] = None
    shot: Optional[str] = None
    sides: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return to_jsonable(self)


@dataclass(frozen=True)
class CheckReport:
    """Result of a scene check. ``ok`` is ``True`` when there are no errors."""

    findings: tuple[CheckFinding, ...] = ()
    ok: bool = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "findings", tuple(self.findings))
        object.__setattr__(self, "ok", not any(f.severity == "error" for f in self.findings))

    @property
    def errors(self) -> tuple[CheckFinding, ...]:
        return tuple(f for f in self.findings if f.severity == "error")

    @property
    def warnings(self) -> tuple[CheckFinding, ...]:
        return tuple(f for f in self.findings if f.severity == "warning")

    def to_dict(self) -> dict:
        return to_jsonable(self)


# ── framing ──────────────────────────────────────────────────────────────────

def _corners(box: Sequence[float]) -> list[Vec3]:
    x0, y0, z0, x1, y1, z1 = box
    return [Vec3(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]


def frame_extent(camera: Mapping[str, Any], aspect: float, box: Sequence[float]):
    """Where *box* (world ``[minx, miny, minz, maxx, maxy, maxz]``) lands in *camera*'s frame.

    Returns ``(x_min, x_max, y_min, y_max, behind)``: the projected extent in
    normalised frame coordinates (the frame is ``[-1, 1]`` on both axes, ``+y``
    up) of the corners in front of the camera, and how many corners are behind
    it. The extent is ``None`` when every corner is behind.
    """
    pos = Vec3(*camera["pos"])
    inv = Quat.from_dz(dict(zip("xyzw", camera["rot"]))).conjugate()
    tan_v = math.tan(camera["fov"] / 2.0)
    tan_h = tan_v * aspect
    xs: list[float] = []
    ys: list[float] = []
    behind = 0
    for c in _corners(box):
        v = inv.rotate(c - pos)
        depth = -v.z
        if depth <= 1e-6:
            behind += 1
            continue
        xs.append(v.x / depth / tan_h)
        ys.append(v.y / depth / tan_v)
    if not xs:
        return None, behind
    return (min(xs), max(xs), min(ys), max(ys)), behind


def framing_findings(camera: Mapping[str, Any], aspect: float,
                     figures: Sequence[Mapping[str, Any]], *, allow_crop: bool = False,
                     shot: Optional[str] = None) -> list[CheckFinding]:
    """Findings for each figure (``{"label", "box"}``) against *camera*.

    ``subject_out_of_frame`` (warning): part of the figure's bounding box is
    outside the frame. ``subject_not_in_frame`` (warning): none of it is in the
    frame. ``no_subject_in_frame`` (error): there are figures, and the camera
    sees none of them. *allow_crop* drops the two warnings (a deliberate crop).
    """
    label = camera["label"]
    out: list[CheckFinding] = []
    seen_any = False
    for fig in figures:
        name = fig["label"]
        extent, behind = frame_extent(camera, aspect, fig["box"])
        if extent is None:
            out.append(_not_in_frame(name, label, shot))
            continue
        x0, x1, y0, y1 = extent
        if x0 > 1 + _EDGE_EPS or x1 < -1 - _EDGE_EPS or y0 > 1 + _EDGE_EPS or y1 < -1 - _EDGE_EPS:
            if not behind:
                out.append(_not_in_frame(name, label, shot))
                continue
        seen_any = True
        sides = tuple(s for s, hit in (("top", y1 > 1 + _EDGE_EPS), ("bottom", y0 < -1 - _EDGE_EPS),
                                       ("left", x0 < -1 - _EDGE_EPS), ("right", x1 > 1 + _EDGE_EPS),
                                       ("behind", behind > 0)) if hit)
        if sides:
            out.append(CheckFinding(
                "warning", "subject_out_of_frame", name,
                f"Figure {name!r} extends past the {_join_sides(sides)} of camera {label!r}'s "
                "frame (a figure crossing the top or bottom usually has its head or feet cut off).",
                camera=label, shot=shot, sides=sides))
    if figures and not seen_any:
        names = ", ".join(repr(f["label"]) for f in figures)
        return [CheckFinding(
            "error", "no_subject_in_frame", label,
            f"Camera {label!r} sees none of the figures in the scene ({names}).",
            camera=label, shot=shot)]
    if allow_crop:
        return []
    return out


def _not_in_frame(name: str, camera: str, shot: Optional[str]) -> CheckFinding:
    return CheckFinding("warning", "subject_not_in_frame", name,
                        f"Figure {name!r} is entirely outside camera {camera!r}'s frame.",
                        camera=camera, shot=shot)


def _join_sides(sides: Sequence[str]) -> str:
    words = ["camera plane" if s == "behind" else f"{s} edge" for s in sides]
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


# ── lighting ─────────────────────────────────────────────────────────────────

def _light_is_lit(light: Mapping[str, Any]) -> bool:
    if not light.get("on") or not light.get("visible", True):
        return False
    return all(v is None or v > 0 for v in (light.get("intensity"), light.get("flux")))


def lighting_findings(engine: Optional[str], lights: Sequence[Mapping[str, Any]],
                      environment: Optional[Mapping[str, Any]], headlamp: bool = False,
                      ) -> list[CheckFinding]:
    """``no_light`` (error) when nothing will light a render on *engine*.

    Light sources counted: a light that is on, visible in the render, with
    non-zero ``intensity`` / ``flux``; an environment whose mode lights the scene
    (Dome and Scene, Dome Only, Sun-Sky Only) at non-zero intensity; the camera
    headlamp. *environment* ``None`` (no environment node yet, e.g. right after
    ``Scene.clear()``) counts as lit: Studio creates its default Dome and Scene
    environment at intensity 1 when the render starts. OpenGL engines
    (``viewport``, ``multi_pass_opengl``) are not checked. Emissive surfaces
    are not seen by this check.
    """
    if engine in _OPENGL_ENGINES:
        return []
    if headlamp or any(_light_is_lit(lt) for lt in lights):
        return []
    if environment is None:  # not created yet: Studio's default dome will light the render
        return []
    if environment.get("mode") in _LIT_ENVIRONMENT_MODES and (environment.get("intensity") or 0) > 0:
        return []
    if lights:
        dark = ", ".join(repr(lt["label"]) for lt in lights)
        why_lights = f"every light is off, hidden or at zero intensity ({dark})"
    else:
        why_lights = "the scene has no lights"
    why_env = (f"the environment is {environment.get('mode_name') or environment.get('mode')!r} "
               f"at intensity {environment.get('intensity')}")
    return [CheckFinding(
        "error", "no_light", "lighting",
        f"Nothing lights this {engine or 'render'} render: {why_lights}, {why_env}, and the "
        "camera headlamp is off. Expect a black image (unless an emissive surface lights it).")]


# ── gathering ────────────────────────────────────────────────────────────────

_ENGINE_CLASSES = {"DzIrayRenderer": "iray", "DzFilamentRenderer": "filament"}


def gather_script(cameras: Sequence[Optional[str]]) -> str:
    """One script returning the data every check needs.

    *cameras*: labels to look up (``None`` = the active viewport camera). The
    result: ``{"cameras": [{label, pos, rot, fov, headlamp} | {label, missing:
    true}], "figures", "lights", "environment", "engine", "aspect"}``.
    """
    labels = "[" + ", ".join("null" if c is None else ScriptBuilder.escape_string(c)
                             for c in cameras) + "]"
    return ScriptBuilder.iife(f"""
var mgr = App.getRenderMgr(), ro = mgr.getRenderOptions();
var engine;
if (ro.renderType === ro.ScreenShot) engine = "viewport";
else if (ro.renderType === ro.HardwareAssisted) engine = "multi_pass_opengl";
else {{ var r = mgr.getActiveRenderer(); engine = r ? r.className() : null; }}
var visibleInRender = function(n) {{ return n.isVisible() && (!n.isVisibleInRender || n.isVisibleInRender()); }};
var num = function(n, name) {{ var p = n.findProperty(name); return p ? p.getValue() : null; }};
var figures = [], lights = [], env = null, anyLit = false;
for (var i = 0; i < Scene.getNumNodes(); i++) {{
    var n = Scene.getNode(i);
    if (n.inherits("DzEnvironmentNode")) {{ env = n; continue; }}
    if (n.inherits("DzSkeleton")) {{
        if (n.getFollowTarget() || !visibleInRender(n)) continue;
        var b = n.getWSBoundingBox();
        figures.push({{label: n.getLabel(), box: [b.min.x, b.min.y, b.min.z, b.max.x, b.max.y, b.max.z]}});
    }} else if (n.inherits("DzLight")) {{
        var l = {{label: n.getLabel(), on: n.isOn(), visible: visibleInRender(n),
                 intensity: num(n, "Intensity"), flux: num(n, "Flux")}};
        if (l.on && l.visible && l.intensity !== 0 && l.flux !== 0) anyLit = true;
        lights.push(l);
    }}
}}
if (!env) {{
    var els = mgr.getRenderElementObjects() || [];
    for (var j = 0; j < els.length; j++) if (els[j] && els[j].inherits && els[j].inherits("DzEnvironmentNode")) env = els[j];
}}
var environment = null;
if (env) {{
    var mp = env.findProperty("Environment Mode");
    environment = {{mode: mp ? mp.getValue() : null, mode_name: mp ? mp.getStringValue() : null,
                   intensity: num(env, "Environment Intensity")}};
}}
var vm = MainWindow.getViewportMgr(), av = vm ? vm.getActiveViewport() : null;
var viewCam = av ? av.get3DViewport().getCamera() : null;
var wanted = {labels}, cams = [];
for (var k = 0; k < wanted.length; k++) {{
    var c = null;
    if (wanted[k] === null) c = viewCam;
    else {{ var f = Scene.findNodeByLabel(wanted[k]); if (f && f.inherits("DzCamera")) c = f; }}
    if (!c) {{ cams.push({{label: wanted[k] === null ? "(active viewport camera)" : wanted[k], missing: true}}); continue; }}
    var p = c.getWSPos(), q = c.getWSRot();
    cams.push({{label: c.getLabel(), pos: [p.x, p.y, p.z], rot: [q.x, q.y, q.z, q.w],
               fov: c.getFieldOfView(), headlamp: c.shouldDoHeadLight(anyLit, true)}});
}}
return {{cameras: cams, figures: figures, lights: lights, environment: environment,
         engine: engine, aspect: ro.aspect}};
""")


def gather(client: "DazClient", cameras: Sequence[Optional[str]]) -> dict:
    """Run :func:`gather_script`; raises :class:`~dazpy.exceptions.DazError` on no result."""
    data = client.execute(gather_script(cameras)).value
    if not isinstance(data, dict) or "cameras" not in data:
        raise DazError(f"scene check: Studio returned no data ({data!r})")
    return data


def engine_name(raw: Optional[str]) -> Optional[str]:
    return _ENGINE_CLASSES.get(raw, raw) if raw is not None else None


def findings_for_camera(data: Mapping[str, Any], cam: Mapping[str, Any], *,
                        aspect: Optional[float] = None, allow_crop: bool = False,
                        shot: Optional[str] = None) -> list[CheckFinding]:
    """Framing findings for one gathered camera (``camera_not_found`` if missing)."""
    if cam.get("missing"):
        return [CheckFinding("error", "camera_not_found", cam["label"],
                             f"Camera {cam['label']!r} is not in the scene.",
                             camera=cam["label"], shot=shot)]
    return framing_findings(cam, aspect or data["aspect"], data["figures"],
                            allow_crop=allow_crop, shot=shot)


def check_scene(client: "DazClient", camera: Optional[str] = None, *,
                engine: Optional[str] = None, resolution: Optional[tuple[int, int]] = None,
                allow_crop: bool = False) -> CheckReport:
    """See :meth:`dazpy.DazScene.check`."""
    data = gather(client, [camera])
    cam = data["cameras"][0]
    aspect = resolution[0] / resolution[1] if resolution else None
    findings = findings_for_camera(data, cam, aspect=aspect, allow_crop=allow_crop)
    findings += lighting_findings(engine or engine_name(data.get("engine")), data["lights"],
                                  data.get("environment"), bool(cam.get("headlamp")))
    return CheckReport(tuple(findings))
