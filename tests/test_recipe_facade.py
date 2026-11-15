"""Unit tests for the public scene-recipe facade (validate / plan / apply / observe)."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dazpy
from dazpy._recipe_desired import compute_desired
from dazpy._recipe_model import SceneRecipe
from dazpy.exceptions import RecipeValidationError
from dazpy.recipe import ObserveReport, apply, observe, plan, recipe_schema, validate
from recipe_fakes import RID, empty_live, fake_scene, live_matching, live_without, patch_facade

G9 = "/People/Genesis 9/Genesis 9.duf"
POSE = "/Poses/Stand.duf"
HDRI = "C:/HDRI/sky.hdr"


def recipe(cam_x: float = 0.0, focal: float = 50.0) -> dict:
    return {
        "recipe_version": 1, "id": RID,
        "assets": {"g9": {"path": G9}},
        "actors": {"anna": {"asset": "g9", "pose": POSE}},
        "lighting": {"environment": {"type": "hdri", "image_path": HDRI}},
        "render": {"engine": "iray"},
        "cameras": {"cu": {"position": [cam_x, 150, 300], "look_at": [0, 100, 0],
                           "focal_length": focal}},
    }


R = recipe()
R2 = recipe(cam_x=40.0, focal=85.0)
D = compute_desired(SceneRecipe.from_dict(R))


class FacadeCase(unittest.TestCase):
    def setUp(self):
        patch_facade(self)


class TestValidate(FacadeCase):
    def test_offline_only_without_scene(self):
        self.assertTrue(validate(R).ok)
        self.assertFalse(validate({"recipe_version": 1}).ok)

    def test_accepts_scene_recipe_object(self):
        self.assertTrue(validate(SceneRecipe.from_dict(R)).ok)

    def test_with_scene_reports_missing_asset(self):
        rep = validate(R, fake_scene(missing_files={G9}))
        self.assertFalse(rep.ok)
        self.assertEqual((rep.errors[0].path, rep.errors[0].code), ("assets.g9.path", "file_not_found"))

    def test_with_scene_reports_missing_pose_and_hdri(self):
        rep = validate(R, fake_scene(missing_files={POSE, HDRI}))
        self.assertEqual({(e.path, e.code) for e in rep.errors},
                         {("actors.anna.pose", "file_not_found"),
                          ("lighting.environment.image_path", "file_not_found")})

    def test_existing_files_pass_in_one_batched_script(self):
        scene = fake_scene()
        self.assertTrue(validate(R, scene).ok)
        self.assertEqual(len(scene._client.scripts), 1)
        self.assertIn("DzFileInfo", scene._client.scripts[0])
        self.assertIn("findFile", scene._client.scripts[0])

    def test_offline_errors_skip_the_scene_check(self):
        scene = fake_scene()
        self.assertFalse(validate({"recipe_version": 1, "id": "x", "bogus": 1}, scene).ok)
        self.assertEqual(scene._client.scripts, [])


class TestPlanApply(FacadeCase):
    def test_plan_is_read_only(self):
        scene = fake_scene()
        p = plan(R, scene)
        self.assertTrue(p.steps and not p.blocked)
        self.assertEqual(scene.ops.calls, [])

    def test_apply_empty_scene_creates_and_writes_manifest(self):
        scene = fake_scene()
        result = apply(R, scene)
        self.assertTrue(result.applied)
        self.assertEqual(scene.ops.methods()[-1], "write_manifest")

    def test_apply_replans_against_current_live_state(self):
        scene = fake_scene(live_matching(D))
        self.assertFalse(plan(R2, scene).blocked)
        scene.tweak("cameras.cu", "transform")
        result = apply(R2, scene)
        self.assertFalse(result.applied)
        self.assertEqual([c.path for c in result.conflicts], ["cameras.cu.transform"])
        self.assertEqual(scene.ops.calls, [])

    def test_apply_invalid_recipe_raises_before_touching_scene(self):
        scene = fake_scene()
        with self.assertRaises(RecipeValidationError):
            apply({"recipe_version": 1}, scene)
        self.assertEqual((scene.ops.calls, scene._client.scripts), ([], []))

    def test_apply_missing_file_raises_before_touching_scene(self):
        scene = fake_scene(missing_files={HDRI})
        with self.assertRaises(RecipeValidationError) as cm:
            apply(R, scene)
        self.assertEqual(cm.exception.report.errors[0].code, "file_not_found")
        self.assertEqual(scene.ops.calls, [])

    def test_invalid_on_conflict_propagates(self):
        with self.assertRaises(ValueError):
            plan(R, fake_scene(), on_conflict="nope")
        with self.assertRaises(ValueError):
            apply(R, fake_scene(), resolutions={"cameras.cu.transform": "nope"})


class TestObserve(FacadeCase):
    def test_never_applied(self):
        rep = observe(R, fake_scene())
        self.assertFalse(rep.applied)
        self.assertFalse(rep.in_sync)
        self.assertIn("cameras.cu", rep.pending)

    def test_in_sync(self):
        rep = observe(R, fake_scene(live_matching(D)))
        self.assertEqual((rep.applied, rep.in_sync, rep.drift, rep.pending, rep.conflicts),
                         (True, True, (), (), ()))

    def test_reports_drift_and_pending(self):
        scene = fake_scene(live_matching(D))
        scene.tweak("cameras.cu", "optics")
        rep = observe(R2, scene)  # R2 changes transform (+ optics, which was tweaked)
        self.assertFalse(rep.in_sync)
        self.assertIn("cameras.cu.transform", rep.pending)
        self.assertEqual([c.path for c in rep.conflicts], ["cameras.cu.optics"])
        scene2 = fake_scene(live_matching(D))
        scene2.tweak("cameras.cu", "transform")
        rep2 = observe(R, scene2)
        self.assertEqual([(i.path, i.code) for i in rep2.drift],
                         [("cameras.cu.transform", "hand_tweak_kept")])
        self.assertFalse(rep2.in_sync)

    def test_reports_deleted_in_scene(self):
        rep = observe(R, fake_scene(live_without(live_matching(D), "cameras.cu")))
        self.assertEqual([(i.path, i.code) for i in rep.drift], [("cameras.cu", "deleted_in_scene")])
        self.assertIn("cameras.cu", rep.pending)


class TestSerialisation(FacadeCase):
    def test_result_types_to_dict_are_json_serializable(self):
        scene = fake_scene()
        json.dumps(apply(R, scene).to_dict())
        json.dumps(plan(R, fake_scene()).to_dict())
        json.dumps(validate(R, fake_scene(missing_files={G9})).to_dict())
        live = live_matching(D)
        s = fake_scene(live)
        s.tweak("cameras.cu", "transform")
        json.dumps(observe(R2, s).to_dict())
        blocked = apply(R2, s)
        out = json.dumps(blocked.to_dict())
        self.assertIn("cameras.cu.transform", out)

    def test_to_dict_turns_tuples_into_lists(self):
        d = plan(R, fake_scene()).to_dict()
        self.assertIsInstance(d["steps"], list)
        self.assertIsInstance(d["steps"][0]["channels"], dict)

    def test_recipe_schema_returns_v1(self):
        self.assertEqual(recipe_schema()["properties"]["recipe_version"]["const"], 1)
        with self.assertRaises(ValueError):
            recipe_schema(2)

    def test_package_exports(self):
        for name in ("SceneRecipe", "RecipeIssue", "ValidationReport", "RecipePlan", "Conflict",
                     "ApplyResult", "ObserveReport", "RecipeValidationError"):
            self.assertIn(name, dazpy.__all__)
            self.assertTrue(hasattr(dazpy, name))


if __name__ == "__main__":
    unittest.main()
