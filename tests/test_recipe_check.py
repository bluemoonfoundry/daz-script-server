"""Unit tests for recipe.check and require_clean on recipe.apply / recipe.render."""

import json
import math
import os
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dazpy
from dazpy._recipe_desired import compute_desired
from dazpy._recipe_model import SceneRecipe
from dazpy._render_api import RenderResult
from dazpy._result import ExecutionResult
from dazpy.exceptions import SceneCheckError
from dazpy.recipe import apply, check, render, validate
from recipe_fakes import RID, empty_live, fake_scene, live_matching, patch_facade
from test_recipe_facade import recipe, shots_recipe

FOV = 2 * math.atan(36 / (2 * 65))
CUBE = [-50, 0, -50, 50, 100, 50]
SCENE_ONLY = {"mode": 3, "mode_name": "Scene Only", "intensity": 1.0}
DOME = {"mode": 0, "mode_name": "Dome and Scene", "intensity": 1.0}


def studio(scene, *, z=400.0, environment=DOME, lights=(), engine="DzIrayRenderer",
           missing=()):
    """Make *scene*'s client answer the gather script; returns the list of gathered label lists."""
    seen = []
    original = scene._client.execute.side_effect

    def execute(script, *a, **kw):
        if "getFieldOfView" not in script:
            return original(script, *a, **kw)
        labels = json.loads(re.search(r"var wanted = (\[.*?\]),", script).group(1))
        seen.append(labels)
        cams = [{"label": lb or "Perspective View", "missing": True} if lb in missing else
                {"label": lb or "Perspective View", "pos": [0, 50, z], "rot": [0, 0, 0, 1],
                 "fov": FOV, "headlamp": False} for lb in labels]
        return ExecutionResult(value={"cameras": cams, "figures": [{"label": "G9", "box": CUBE}],
                                      "lights": list(lights), "environment": environment,
                                      "engine": engine, "aspect": 1.5})

    scene._client.execute.side_effect = execute
    return seen


def codes(report):
    return [(f.code, f.shot) for f in report.findings]


RS = shots_recipe()
DS = compute_desired(SceneRecipe.from_dict(RS))
CAM = f"{RID}:cu"


class CheckTests(unittest.TestCase):
    def setUp(self):
        patch_facade(self)

    def test_clean_scene(self):
        scene = fake_scene(live_matching(DS))
        seen = studio(scene)
        report = check(RS, scene)
        self.assertTrue(report.ok)
        self.assertEqual(report.findings, ())
        self.assertEqual(seen, [[CAM, CAM, CAM]])  # one script for every shot

    def test_framing_per_shot_with_shot_resolution(self):
        scene = fake_scene(live_matching(DS))
        studio(scene, z=260)
        report = check(RS, scene)
        # Only the 4:5 'tall' shot is narrow enough to crop the cube's sides.
        self.assertEqual(codes(report), [("subject_out_of_frame", "tall")])
        self.assertEqual(report.findings[0].sides, ("left", "right"))
        self.assertTrue(report.ok)
        self.assertEqual(report.findings[0].camera, CAM)

    def test_allow_crop(self):
        r = shots_recipe()
        r["shots"][1]["allow_crop"] = True
        scene = fake_scene(live_matching(compute_desired(SceneRecipe.from_dict(r))))
        studio(scene, z=150)
        self.assertEqual([s for _, s in codes(check(r, scene))], ["wide", "other"])

    def test_lighting_reported_once_when_every_shot_agrees(self):
        r = shots_recipe()
        del r["shots"][2]["render"]["engine"]  # all iray
        scene = fake_scene(live_matching(compute_desired(SceneRecipe.from_dict(r))))
        studio(scene, environment=SCENE_ONLY)
        report = check(r, scene)
        self.assertEqual(codes(report), [("no_light", None)])
        self.assertFalse(report.ok)

    def test_lighting_per_shot_when_engines_differ(self):
        r = shots_recipe()
        r["shots"][2]["render"]["engine"] = "viewport"
        scene = fake_scene(live_matching(compute_desired(SceneRecipe.from_dict(r))))
        studio(scene, environment=SCENE_ONLY)
        self.assertEqual(codes(check(r, scene)), [("no_light", "wide"), ("no_light", "tall")])
        # Filament and Iray are both dark here, but the messages name the engine.
        scene = fake_scene(live_matching(DS))
        studio(scene, environment=SCENE_ONLY)
        self.assertEqual(codes(check(RS, scene)), [("no_light", "wide"), ("no_light", "tall"),
                                                    ("no_light", "other")])

    def test_unapplied_recipe_reports_missing_camera(self):
        scene = fake_scene(empty_live())
        studio(scene, missing={CAM})
        report = check(RS, scene, shots=["wide"])
        self.assertEqual(codes(report), [("camera_not_found", "wide")])

    def test_no_shots_checks_lighting_only(self):
        r = recipe()
        scene = fake_scene()
        seen = studio(scene, environment=SCENE_ONLY)
        self.assertEqual(codes(check(r, scene)), [("no_light", None)])
        self.assertEqual(seen, [[None]])

    def test_unknown_shot(self):
        with self.assertRaises(ValueError):
            check(RS, fake_scene(), shots=["nope"])

    def test_allow_crop_validation(self):
        r = shots_recipe()
        r["shots"][0]["allow_crop"] = "yes"
        rep = validate(r)
        self.assertEqual([(e.path, e.code) for e in rep.errors],
                         [("shots[0].allow_crop", "invalid_type")])
        r["shots"][0]["allow_crop"] = True
        self.assertTrue(validate(r).ok)
        self.assertTrue(SceneRecipe.from_dict(r).shots[0].allow_crop)
        self.assertTrue(SceneRecipe.from_dict(r).to_dict()["shots"][0]["allow_crop"])
        self.assertNotIn("allow_crop", SceneRecipe.from_dict(RS).to_dict()["shots"][0])

    def test_exports(self):
        for name in ("CheckReport", "CheckFinding", "SceneCheckError"):
            self.assertIn(name, dazpy.__all__)
        self.assertIn("check", dazpy.recipe.__all__)


class RenderRequireCleanTests(unittest.TestCase):
    def setUp(self):
        patch_facade(self)
        p = patch("dazpy.recipe.render_api.render",
                  side_effect=lambda client, out, **kw: RenderResult(True, out, 10, 5, "", "r1"))
        self.mock = p.start()
        self.addCleanup(p.stop)

    def test_refuses_and_renders_nothing(self):
        scene = fake_scene(live_matching(DS))
        studio(scene, environment=SCENE_ONLY)
        with self.assertRaises(SceneCheckError) as cm:
            render(RS, scene, require_clean=True)
        self.assertEqual(cm.exception.report.errors[0].code, "no_light")
        self.assertIn("no_light", str(cm.exception))
        self.mock.assert_not_called()

    def test_warnings_do_not_block(self):
        scene = fake_scene(live_matching(DS))
        studio(scene, z=260)
        self.assertEqual(len(render(RS, scene, require_clean=True)), 3)

    def test_not_checked_by_default(self):
        scene = fake_scene(live_matching(DS))
        seen = studio(scene, environment=SCENE_ONLY)
        render(RS, scene)
        self.assertEqual(seen, [])


class ApplyRequireCleanTests(unittest.TestCase):
    def setUp(self):
        patch_facade(self)

    def test_clean_apply_writes_manifest_and_reports_check(self):
        scene = fake_scene()
        studio(scene)
        result = apply(RS, scene, require_clean=True)
        self.assertTrue(result.applied)
        self.assertTrue(result.check.ok)
        self.assertEqual(scene.ops.methods()[-1], "write_manifest")
        json.dumps(result.to_dict())
        self.assertTrue(result.to_dict()["check"]["ok"])

    def test_check_errors_roll_back(self):
        scene = fake_scene()
        studio(scene, environment=SCENE_ONLY)
        result = apply(RS, scene, require_clean=True)
        self.assertFalse(result.applied)
        self.assertTrue(result.rolled_back)
        self.assertFalse(result.check.ok)
        self.assertIn("scene check", result.error)
        self.assertIn("no_light", result.error)
        self.assertNotIn("write_manifest", scene.ops.methods())

    def test_not_checked_by_default(self):
        scene = fake_scene()
        seen = studio(scene, environment=SCENE_ONLY)
        result = apply(RS, scene)
        self.assertTrue(result.applied)
        self.assertIsNone(result.check)
        self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main()
