"""
Live tests for pre-render scene checks (DazScene.check, dazpy.recipe.check).
Opt-in: skipped unless DAZ_LIVE_TESTS=1, and when DAZ Studio is not reachable.
Run scoped:
    DAZ_LIVE_TESTS=1 python -m pytest tests/test_scene_check_live.py -v

Starts from an empty scene (Scene.clear()) and leaves one behind. It refuses to
clear a scene that has content unless DAZ_LIVE_ALLOW_CLEAR=1.
"""

# Opt-in gate (tests/live_gate.py): skip this module unless DAZ_LIVE_TESTS=1
# (or it is run directly), before anything below contacts DAZ Studio.
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from live_gate import clear_scene, require_live  # noqa: E402
require_live(__name__)

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_recipe_live import _CLIENT, _BUSY_WAIT_S, _example, _new_scene, skip_if_down, skip_no_daz

from dazpy.recipe import apply, check, render

_OUT = "C:/temp/scene_check_live"
_ENV = """var h = null;
for (var i = 0; i < Scene.getNumNodes(); i++) if (Scene.getNode(i).inherits("DzEnvironmentNode")) h = Scene.getNode(i);
if (!h) { var o = App.getRenderMgr().getRenderElementObjects() || [];
          for (var j = 0; j < o.length; j++) if (o[j].inherits && o[j].inherits("DzEnvironmentNode")) h = o[j]; }"""


def _env(mode=None, intensity=None):
    """Set (when given) and return the environment mode and intensity."""
    sets = ""
    if mode is not None:
        sets += f'h.findProperty("Environment Mode").setValue({mode});'
    if intensity is not None:
        sets += f'h.findProperty("Environment Intensity").setValue({intensity});'
    return _CLIENT.execute(f"""(function(){{ {_ENV} if (!h) return null; {sets}
        return [h.findProperty("Environment Mode").getValue(), h.findProperty("Environment Intensity").getValue()];
    }})()""").value


def _lights_on(on: bool) -> None:
    _CLIENT.execute(f"""(function(){{ for (var i = 0; i < Scene.getNumNodes(); i++) {{
        var n = Scene.getNode(i); if (n.inherits("DzLight")) n.findProperty("Illumination").setValue({3 if on else 0});
    }} return true; }})()""")  # Illumination: 0 Off ... 3 On


def _figure_pixels(path: str):
    """(touches top row, touches bottom row) for the non-background pixels of a render.

    Studio 6 viewport renders have a transparent background (alpha 0) behind a
    near-black figure, so with alpha the figure is alpha > 0; Studio 4 renders
    are opaque, so the figure is what differs from the corner colour.
    """
    from PIL import Image
    im = Image.open(path)
    w, h = im.size
    if im.mode == "RGBA" and im.getpixel((1, 1))[3] == 0:
        def differs(p):
            return p[3] > 0
    else:
        im = im.convert("RGB")
        corner = im.getpixel((1, 1))

        def differs(p):
            return sum(abs(a - b) for a, b in zip(p, corner)) > 40

    top = any(differs(im.getpixel((x, 0))) for x in range(w))
    bottom = any(differs(im.getpixel((x, h - 1))) for x in range(w))
    return top, bottom


def _figure_rows(path: str):
    """(first, last) image rows holding figure pixels, and the image height."""
    from PIL import Image
    im = Image.open(path)
    w, h = im.size
    if im.mode == "RGBA" and im.getpixel((1, 1))[3] == 0:
        def differs(p):
            return p[3] > 0
    else:
        im = im.convert("RGB")
        corner = im.getpixel((1, 1))

        def differs(p):
            return sum(abs(a - b) for a, b in zip(p, corner)) > 40
    px = im.load()
    rows = [y for y in range(h) if any(differs(px[x, y]) for x in range(0, w, 2))]
    return rows[0], rows[-1], h


@skip_if_down
@skip_no_daz
class TestSceneCheckLive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wait = _CLIENT.waiting_out_busy(_BUSY_WAIT_S)
        cls.wait.__enter__()
        cls.recipe = _example("scene_check")
        for shot in cls.recipe["shots"]:
            shot["output"] = f"{_OUT}/{shot['id']}.png"
        cls.scene = _new_scene()
        result = apply(cls.recipe, cls.scene, require_clean=True)
        if not result.applied:
            raise AssertionError(f"apply failed: {result.error}")
        cls.apply_check = result.check
        # A cleared scene has no environment node until a render creates it.
        # The first Iray render after Studio starts can take ~9 min to reach
        # its first sample (seen on DS4 2026-11-20), hence the long timeout.
        from dazpy._render_api import render as render_one
        render_one(_CLIENT, f"{_OUT}/env_seed.png", camera=f"{cls.recipe['id']}:full_body",
                   engine="iray", width=32, height=24, iray_samples=1, timeout=900)
        cls.env0 = _env()
        if cls.env0 is None:
            raise AssertionError("no environment node after an Iray render")

    @classmethod
    def tearDownClass(cls):
        try:
            if cls.env0:
                _env(*cls.env0)
            clear_scene(_CLIENT)
        finally:
            cls.wait.__exit__(None, None, None)

    def cam(self, key):
        return f"{self.recipe['id']}:{key}"

    def test_applied_example_is_clean(self):
        self.assertTrue(self.apply_check.ok, self.apply_check.to_dict())
        report = check(self.recipe, self.scene)
        self.assertTrue(report.ok, report.to_dict())
        by_shot = {}
        for f in report.findings:
            by_shot.setdefault(f.shot, []).append(f)
        self.assertNotIn("full_body", by_shot, report.to_dict())
        # The close-up crops the body: a bottom-edge warning, nothing at the top.
        (crop,) = by_shot["close_up"]
        self.assertEqual(crop.code, "subject_out_of_frame")
        self.assertIn("bottom", crop.sides)
        self.assertNotIn("top", crop.sides)

    def test_crop_matches_the_rendered_image(self):
        for key, _expect_top in (("full_body", False), ("close_up", False)):
            report = self.scene.check(self.cam(key), engine="viewport", resolution=(320, 240))
            sides = {s for f in report.findings for s in f.sides}
            path = f"{_OUT}/frame_{key}.png"
            from dazpy._render_api import render as render_one
            render_one(_CLIENT, path, camera=self.cam(key), engine="viewport", width=320,
                       height=240, timeout=120)
            top, bottom = _figure_pixels(path)
            self.assertEqual("top" in sides, top, (key, report.to_dict()))
            self.assertEqual("bottom" in sides, bottom, (key, report.to_dict()))

    def test_full_body_fits_the_frame_height_at_any_aspect(self):
        # Studio applies Frame Width to the frame height (nnfk): full_body fits 210 cm
        # of height whatever the render aspect, so a standing figure fills
        # ~height/210 of the frame in landscape and portrait alike.
        fig_h = _CLIENT.execute("""(function(){ for (var i = 0; i < Scene.getNumNodes(); i++) {
            var n = Scene.getNode(i); if (n.inherits("DzFigure")) { var b = n.getWSBoundingBox();
            return b.max.y - b.min.y; } } return null; })()""").value
        from dazpy._render_api import render as render_one
        fills = {}
        for w, h in ((320, 240), (240, 320)):
            path = f"{_OUT}/fit_{w}x{h}.png"
            render_one(_CLIENT, path, camera=self.cam("full_body"), engine="viewport", width=w,
                       height=h, timeout=120)
            top, bottom, rows = _figure_rows(path)
            self.assertGreater(top, 0, path)
            self.assertLess(bottom, rows - 1, path)
            fills[(w, h)] = (bottom - top + 1) / rows
        expected = fig_h / 210.0
        for size, fill in fills.items():
            self.assertAlmostEqual(fill, expected, delta=0.08, msg=(size, fills, fig_h))
        self.assertAlmostEqual(fills[(320, 240)], fills[(240, 320)], delta=0.03, msg=fills)

    def test_head_cut_off(self):
        node = self.scene.find_node_by_label(self.cam("close_up"))
        pos = node.position
        try:
            node.set_position(pos["x"], pos["y"] - 25, pos["z"])
            report = self.scene.check(self.cam("close_up"), engine="viewport", resolution=(320, 240))
            sides = {s for f in report.findings for s in f.sides}
            self.assertIn("top", sides, report.to_dict())
            path = f"{_OUT}/head_cut.png"
            from dazpy._render_api import render as render_one
            render_one(_CLIENT, path, camera=self.cam("close_up"), engine="viewport", width=320,
                       height=240, timeout=120)
            self.assertEqual(_figure_pixels(path)[0], True)
        finally:
            node.set_position(pos["x"], pos["y"], pos["z"])

    def test_no_light(self):
        try:
            _lights_on(False)
            _env(mode=3, intensity=1)
            report = self.scene.check(self.cam("full_body"), engine="iray")
            self.assertEqual([f.code for f in report.errors], ["no_light"], report.to_dict())
            _env(mode=0, intensity=1)  # Dome and Scene lights an unlit scene
            self.assertTrue(self.scene.check(self.cam("full_body"), engine="iray").ok)
            _env(mode=0, intensity=0)
            self.assertFalse(self.scene.check(self.cam("full_body"), engine="iray").ok)
            _env(mode=3, intensity=1)
            with self.assertRaises(Exception) as cm:
                render(self.recipe, self.scene, require_clean=True)
            self.assertEqual(type(cm.exception).__name__, "SceneCheckError")
        finally:
            _lights_on(True)
            _env(*self.env0)
        self.assertTrue(self.scene.check(self.cam("full_body"), engine="iray").ok)

    def test_dazpy_environment_lookup_finds_the_node(self):
        # Studio 4 keeps the environment on a scene node, Studio 6 among the
        # render elements; dazpy's holder must reach it on both (n0bl).
        from dazpy._recipe_store import observe_environment_script
        from dazpy._render import DazRenderSettings
        rs = DazRenderSettings(_CLIENT)
        try:
            _env(intensity=0.37)
            self.assertAlmostEqual(rs._get_environment_property("Environment Intensity"), 0.37, places=4)
            rs._set_environment_property("Environment Intensity", 0.61)
            self.assertAlmostEqual(_env()[1], 0.61, places=4)
            observed = _CLIENT.execute(observe_environment_script(rs._environment_holder())).value
            self.assertIsNotNone(observed)
        finally:
            _env(*self.env0)

    def test_missing_camera(self):
        report = self.scene.check("no such camera")
        self.assertEqual([f.code for f in report.errors], ["camera_not_found"])


if __name__ == "__main__":
    unittest.main()
