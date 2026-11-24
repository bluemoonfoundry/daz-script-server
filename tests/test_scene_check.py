"""Unit tests for pre-render scene checks (dazpy._scene_check). No Studio needed."""

import math
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dazpy._scene_check import (CheckFinding, CheckReport, check_scene, frame_extent,
                                framing_findings, gather_script, lighting_findings)
from dazpy.math3 import Quat, Vec3

FOV_65MM = 2 * math.atan(36 / (2 * 65))  # Studio default lens, frame width 36 mm
IDENTITY = [0.0, 0.0, 0.0, 1.0]
CUBE = [-50, 0, -50, 50, 100, 50]  # Studio's default 1 m cube primitive


def cam(z=400.0, y=50.0, x=0.0, rot=IDENTITY, label="Cam"):
    return {"label": label, "pos": [x, y, z], "rot": list(rot), "fov": FOV_65MM}


def fig(box, label="Genesis 9"):
    return {"label": label, "box": list(box)}


def codes(findings):
    return [f.code for f in findings]


class FrameExtentTests(unittest.TestCase):
    def test_matches_live_render_measurements(self):
        # Live Studio 4.24 viewport renders of CUBE from (0, 50, 400) at 65 mm:
        # 300x200 -> 34% of the width, 51% of the height; 200x300 -> 77% / 51%.
        (x0, x1, y0, y1), behind = frame_extent(cam(), 1.5, CUBE)
        self.assertEqual(behind, 0)
        self.assertAlmostEqual(x1 - x0, 2 * 0.34, delta=0.02)
        self.assertAlmostEqual(y1 - y0, 2 * 0.51, delta=0.02)
        (x0, x1, y0, y1), _ = frame_extent(cam(), 2 / 3, CUBE)
        self.assertAlmostEqual(x1 - x0, 2 * 0.77, delta=0.02)
        self.assertAlmostEqual(y1 - y0, 2 * 0.513, delta=0.02)

    def test_rotation_uses_studio_quaternion_convention(self):
        # A camera at the origin turned to look down +X (yaw -90 deg about Y)
        # sees a cube placed on +X centred in frame.
        q = Quat.from_axis_angle(Vec3(0, 1, 0), -90).to_dz()
        c = cam(z=0, y=50, rot=[q["x"], q["y"], q["z"], q["w"]])
        (x0, x1, y0, y1), behind = frame_extent(c, 1.0, [350, 0, -50, 450, 100, 50])
        self.assertEqual(behind, 0)
        self.assertAlmostEqual(x0 + x1, 0.0, places=6)
        self.assertAlmostEqual(y0 + y1, 0.0, places=6)

    def test_all_corners_behind(self):
        extent, behind = frame_extent(cam(), 1.5, [-50, 0, 500, 50, 100, 600])
        self.assertIsNone(extent)
        self.assertEqual(behind, 8)


class FramingTests(unittest.TestCase):
    def test_figure_inside_frame_has_no_findings(self):
        self.assertEqual(framing_findings(cam(), 1.5, [fig(CUBE)]), [])

    def test_close_camera_crops_every_side(self):
        (f,) = framing_findings(cam(z=150), 1.5, [fig(CUBE)])
        self.assertEqual((f.severity, f.code, f.subject, f.camera), ("warning", "subject_out_of_frame",
                                                                     "Genesis 9", "Cam"))
        self.assertEqual(f.sides, ("top", "bottom", "left", "right"))

    def test_head_cut_off_reports_top_only(self):
        # Tall narrow figure, camera aimed level at its middle but too close vertically.
        tall = [-10, -40, -10, 10, 140, 10]
        (f,) = framing_findings(cam(z=250), 1.5, [fig(tall)])
        self.assertEqual(f.sides, ("top", "bottom"))
        (f,) = framing_findings(cam(z=350, y=10), 1.5, [fig([-10, 0, -10, 10, 140, 10])])
        self.assertEqual(f.sides, ("top",))
        self.assertIn("top edge", f.message)

    def test_one_figure_out_of_view_is_a_warning(self):
        found = framing_findings(cam(), 1.5, [fig(CUBE), fig([900, 0, -50, 1000, 100, 50], "Bob")])
        self.assertEqual(codes(found), ["subject_not_in_frame"])
        self.assertEqual((found[0].severity, found[0].subject), ("warning", "Bob"))

    def test_no_figure_in_view_is_an_error(self):
        found = framing_findings(cam(), 1.5, [fig([900, 0, -50, 1000, 100, 50]),
                                              fig([-50, 0, 500, 50, 100, 600], "Behind")])
        self.assertEqual(codes(found), ["no_subject_in_frame"])
        self.assertEqual(found[0].severity, "error")
        self.assertIn("'Behind'", found[0].message)

    def test_partly_behind_camera(self):
        (f,) = framing_findings(cam(z=0), 1.5, [fig([-50, 0, -300, 50, 100, 50])])
        self.assertIn("behind", f.sides)

    def test_allow_crop_drops_warnings_keeps_error(self):
        self.assertEqual(framing_findings(cam(z=150), 1.5, [fig(CUBE)], allow_crop=True), [])
        found = framing_findings(cam(), 1.5, [fig([900, 0, -50, 1000, 100, 50])], allow_crop=True)
        self.assertEqual(codes(found), ["no_subject_in_frame"])

    def test_no_figures_no_findings(self):
        self.assertEqual(framing_findings(cam(), 1.5, []), [])

    def test_shot_is_carried(self):
        (f,) = framing_findings(cam(z=150), 1.5, [fig(CUBE)], shot="s1")
        self.assertEqual(f.shot, "s1")


DOME = {"mode": 0, "mode_name": "Dome and Scene", "intensity": 1.0}
SCENE_ONLY = {"mode": 3, "mode_name": "Scene Only", "intensity": 1.0}


def light(on=True, intensity=1.0, flux=None, visible=True, label="Spot"):
    return {"label": label, "on": on, "visible": visible, "intensity": intensity, "flux": flux}


class LightingTests(unittest.TestCase):
    def test_dome_lights_an_empty_scene(self):
        self.assertEqual(lighting_findings("iray", [], DOME), [])
        self.assertEqual(lighting_findings("iray", [], dict(DOME, mode=2)), [])

    def test_scene_only_without_lights_is_dark(self):
        (f,) = lighting_findings("iray", [], SCENE_ONLY)
        self.assertEqual((f.severity, f.code, f.subject), ("error", "no_light", "lighting"))
        self.assertIn("no lights", f.message)
        self.assertIn("'Scene Only'", f.message)

    def test_zero_intensity_dome_is_dark(self):
        self.assertEqual(codes(lighting_findings("iray", [], dict(DOME, intensity=0))), ["no_light"])

    def test_one_lit_light_is_enough(self):
        self.assertEqual(lighting_findings("iray", [light(on=False, label="A"), light()], SCENE_ONLY), [])

    def test_off_hidden_or_zero_lights_are_dark(self):
        for lt in (light(on=False), light(visible=False), light(intensity=0), light(flux=0)):
            (f,) = lighting_findings("iray", [lt], SCENE_ONLY)
            self.assertIn("'Spot'", f.message)

    def test_headlamp_counts(self):
        self.assertEqual(lighting_findings("iray", [], SCENE_ONLY, headlamp=True), [])

    def test_opengl_engines_are_not_checked(self):
        for engine in ("viewport", "multi_pass_opengl"):
            self.assertEqual(lighting_findings(engine, [], SCENE_ONLY), [])

    def test_missing_environment_is_studios_default_dome(self):
        # Live Studio 4.24: after Scene.clear() there is no environment node, and
        # an unlit Iray render is still lit (the default dome is created then).
        self.assertEqual(lighting_findings("iray", [], None), [])
        self.assertEqual(lighting_findings("iray", [light(on=False)], None), [])


class ReportTests(unittest.TestCase):
    def test_ok_and_split(self):
        w = CheckFinding("warning", "subject_out_of_frame", "A", "m")
        e = CheckFinding("error", "no_light", "lighting", "m")
        self.assertTrue(CheckReport((w,)).ok)
        r = CheckReport((w, e))
        self.assertFalse(r.ok)
        self.assertEqual((r.errors, r.warnings), ((e,), (w,)))
        d = r.to_dict()
        self.assertFalse(d["ok"])
        self.assertEqual(d["findings"][1]["code"], "no_light")


class FakeClient:
    def __init__(self, data):
        self.data, self.scripts = data, []

    def execute(self, script):
        self.scripts.append(script)
        return SimpleNamespace(value=self.data)


def gathered(**over):
    d = {"cameras": [dict(cam(z=150), headlamp=False)], "figures": [fig(CUBE)], "lights": [],
         "environment": SCENE_ONLY, "engine": "DzIrayRenderer", "aspect": 1.5}
    d.update(over)
    return d


class CheckSceneTests(unittest.TestCase):
    def test_gather_script_escapes_labels(self):
        s = gather_script([None, 'Cam "A"'])
        self.assertIn('[null, "Cam \\"A\\""]', s)

    def test_combines_framing_and_lighting(self):
        client = FakeClient(gathered())
        report = check_scene(client)
        self.assertEqual(codes(report.findings), ["subject_out_of_frame", "no_light"])
        self.assertFalse(report.ok)
        self.assertIn("[null]", client.scripts[0])
        self.assertIn("iray render", report.errors[0].message)

    def test_engine_override_and_resolution(self):
        report = check_scene(FakeClient(gathered(cameras=[dict(cam(), headlamp=False)])),
                             "Cam", engine="viewport", resolution=(100, 1000))
        # 1:10 portrait: the cube is far wider than the frame.
        self.assertEqual(codes(report.findings), ["subject_out_of_frame"])
        self.assertEqual(report.findings[0].sides, ("left", "right"))

    def test_missing_camera(self):
        report = check_scene(FakeClient(gathered(cameras=[{"label": "Nope", "missing": True}],
                                                 environment=DOME)), "Nope")
        self.assertEqual(codes(report.findings), ["camera_not_found"])

    def test_no_result_raises(self):
        from dazpy.exceptions import DazError
        with self.assertRaises(DazError):
            check_scene(FakeClient(None))

    def test_headlamp_from_camera(self):
        report = check_scene(FakeClient(gathered(cameras=[dict(cam(), headlamp=True)])))
        self.assertTrue(report.ok)
        self.assertEqual(report.findings, ())


if __name__ == "__main__":
    unittest.main()
