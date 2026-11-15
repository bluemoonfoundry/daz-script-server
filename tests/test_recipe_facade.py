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
from dazpy._recipe_store import LiveEntity, LiveState
from unittest.mock import patch

from dazpy._render_api import RenderResult
from dazpy.exceptions import DazError, RecipeNotAppliedError, RecipeValidationError
from dazpy.recipe import (ObserveReport, ShotRender, apply, observe, plan, recipe_schema,
                          render, validate)
from recipe_fakes import (RID, SimStudio, empty_live, fake_scene, live_matching, live_without,
                          patch_facade, patch_sim)

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
        self.assertIn("recipe:resolve", scene._client.scripts[0])
        self.assertIn("DzFileInfo", scene._client.scripts[0])
        self.assertIn("findFile", scene._client.scripts[0])

    def test_absolute_files_are_checked_studio_side_not_with_os_path(self):
        scene = fake_scene(missing_files={HDRI})
        with patch("dazpy._recipe_ops.os.path.isfile", return_value=True) as isfile, \
                patch("dazpy.recipe.os.path.isfile", return_value=True, create=True):
            rep = validate(R, scene)
        self.assertEqual([(e.path, e.code) for e in rep.errors],
                         [("lighting.environment.image_path", "file_not_found")])
        isfile.assert_not_called()

    def test_json_pose_files_are_checked_client_side(self):
        r = recipe()
        r["actors"]["anna"]["pose"] = "C:/poses/wave.JSON"
        scene = fake_scene()
        with patch("dazpy._recipe_ops.os.path.isfile", return_value=False) as isfile:
            rep = validate(r, scene)
        isfile.assert_called_once_with("C:/poses/wave.JSON")
        self.assertEqual([(e.path, e.code) for e in rep.errors], [("actors.anna.pose", "file_not_found")])
        self.assertNotIn("wave.JSON", scene._client.scripts[0])

    def test_null_existence_result_raises(self):
        scene = fake_scene()
        scene._client.execute.side_effect = lambda *a, **kw: __import__(
            "dazpy._result", fromlist=["ExecutionResult"]).ExecutionResult(value=None)
        with self.assertRaises(DazError) as cm:
            validate(R, scene)
        self.assertNotIsInstance(cm.exception, RecipeValidationError)

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

    def test_accepted_hand_deletion_is_in_sync(self):
        live = live_without(live_matching(D, deleted=("cameras.cu",)), "cameras.cu")
        rep = observe(R, fake_scene(live))
        self.assertEqual((rep.applied, rep.in_sync, rep.pending, rep.conflicts),
                         (True, True, (), ()))

    def test_reports_deleted_in_scene(self):
        rep = observe(R, fake_scene(live_without(live_matching(D), "cameras.cu")))
        self.assertEqual([(i.path, i.code) for i in rep.drift], [("cameras.cu", "deleted_in_scene")])
        self.assertIn("cameras.cu", rep.pending)


def shots_recipe(**extra) -> dict:
    r = recipe()
    del r["lighting"]  # an HDRI would forbid the filament shot
    r["render"] = {"engine": "iray", "resolution": [1080, 1080], "iray_samples": 200}
    r["shots"] = [
        {"id": "wide", "camera": "cu", "output": "C:/out/shots/wide.png"},
        {"id": "tall", "camera": "cu", "output": "C:/out/shots/tall.png",
         "render": {"resolution": [1080, 1350]}},
        {"id": "other", "camera": "cu", "output": "D:\\out2\\other.png",
         "render": {"engine": "filament", "iray_samples": 8}},
    ]
    r.update(extra)
    return r


RS = shots_recipe()
DS = compute_desired(SceneRecipe.from_dict(RS))


class TestRender(FacadeCase):
    def setUp(self):
        super().setUp()
        p = patch("dazpy.recipe.render_api.render",
                  side_effect=lambda client, out, **kw: RenderResult(True, out, 10, 5, "", "r1"))
        self.mock = p.start()
        self.addCleanup(p.stop)

    def applied(self):
        return fake_scene(live_matching(DS))

    def test_refuses_unapplied_recipe(self):
        with self.assertRaises(RecipeNotAppliedError) as cm:
            render(RS, fake_scene())
        self.assertIsInstance(cm.exception, DazError)
        self.assertFalse(cm.exception.report.applied)
        self.mock.assert_not_called()

    def test_refuses_conflicts(self):
        scene = self.applied()
        scene.tweak("cameras.cu", "transform")
        with self.assertRaises(RecipeNotAppliedError):
            render(shots_recipe(cameras={"cu": {"position": [9, 150, 300], "look_at": [0, 100, 0],
                                                 "focal_length": 50.0}}), scene)

    def test_refuses_pending_changes(self):
        scene = self.applied()
        changed = shots_recipe(cameras={"cu": {"position": [9, 150, 300], "look_at": [0, 100, 0],
                                                "focal_length": 50.0}})
        with self.assertRaises(RecipeNotAppliedError) as cm:
            render(changed, scene)
        self.assertIn("recipe has unapplied changes; call apply first", str(cm.exception))

    def test_refuses_when_shot_camera_drifted(self):
        scene = self.applied()
        scene.tweak("cameras.cu", "transform")
        with self.assertRaises(RecipeNotAppliedError) as cm:
            render(RS, scene)
        self.assertEqual([i.path for i in cm.exception.report.drift], ["cameras.cu.transform"])

    def test_refuses_when_shot_camera_deleted(self):
        with self.assertRaises(RecipeNotAppliedError):
            render(RS, fake_scene(live_without(live_matching(DS), "cameras.cu")))

    def test_drift_on_unrelated_camera_does_not_block(self):
        rec = shots_recipe()
        rec["cameras"]["side"] = {"position": [100, 150, 0], "look_at": [0, 100, 0],
                                  "focal_length": 50.0}
        d = compute_desired(SceneRecipe.from_dict(rec))
        scene = fake_scene(live_matching(d))
        scene.tweak("cameras.side", "transform")
        out = render(rec, scene, wait=False)
        self.assertEqual(len(out), 3)

    def test_force_skips_guard(self):
        out = render(RS, fake_scene(), force=True)
        self.assertEqual(len(out), 3)
        self.assertEqual(self.mock.call_count, 3)

    def test_shot_render_override_merges_over_top_level(self):
        out = render(RS, self.applied(), wait=False)
        kw = self.mock.call_args_list[1].kwargs
        self.assertEqual((kw["width"], kw["height"], kw["engine"], kw["iray_samples"]),
                         (1080, 1350, "iray", 200))
        kw3 = self.mock.call_args_list[2].kwargs
        self.assertEqual((kw3["width"], kw3["height"], kw3["engine"], kw3["iray_samples"]),
                         (1080, 1080, "filament", 8))
        self.assertFalse(kw["wait"])
        self.assertEqual([s.shot_id for s in out], ["wide", "tall", "other"])

    def test_missing_values_pass_scene_defaults(self):
        rec = recipe()
        rec.pop("render")
        del rec["lighting"]
        rec["shots"] = [{"id": "a", "camera": "cu", "output": "C:/o/a.png"}]
        scene = fake_scene(live_matching(compute_desired(SceneRecipe.from_dict(rec))))
        render(rec, scene)
        kw = self.mock.call_args.kwargs
        self.assertEqual((kw["width"], kw["height"], kw["engine"], kw["iray_samples"]),
                         (0, 0, "", 0))
        self.assertEqual(kw["timeout"], 300.0)

    def test_subset_by_shot_id(self):
        out = render(RS, self.applied(), shots=["tall"])
        self.assertEqual([s.shot_id for s in out], ["tall"])
        self.assertEqual(self.mock.call_count, 1)

    def test_unknown_shot_id_names_unknown_and_valid(self):
        with self.assertRaises(ValueError) as cm:
            render(RS, self.applied(), shots=["tall", "nope"])
        msg = str(cm.exception)
        self.assertIn("nope", msg)
        for valid in ("wide", "tall", "other"):
            self.assertIn(valid, msg)
        self.mock.assert_not_called()

    def test_camera_label_is_recipe_scoped(self):
        render(RS, self.applied(), shots=["wide"])
        self.assertEqual(self.mock.call_args.kwargs["camera"], f"{RID}:cu")
        self.assertEqual(self.mock.call_args.args[1], "C:/out/shots/wide.png")

    def test_renders_through_the_cameras_current_label(self):
        live = live_matching(DS)
        e = live.entities["cameras.cu"]
        ents = dict(live.entities)
        ents["cameras.cu"] = LiveEntity(e.path, e.node_name, e.kind, e.record, e.observed,
                                        e.foreign_children, e.element_id, label="Hero Cam")
        scene = fake_scene(LiveState(live.manifest, ents, live.environment_observed))
        out = render(RS, scene, shots=["wide"])
        self.assertEqual(self.mock.call_args.kwargs["camera"], "Hero Cam")
        self.assertEqual(out[0].camera_label, "Hero Cam")

    def test_reads_the_scene_once(self):
        with patch("dazpy.recipe.read_live", side_effect=lambda c, rid: live_matching(DS)) as rl:
            render(RS, fake_scene())
        self.assertEqual(rl.call_count, 1)

    def test_one_mkdir_script_for_unique_parent_dirs(self):
        scene = self.applied()
        scene._client.scripts.clear()
        render(RS, scene)
        mk = [s for s in scene._client.scripts if "mkpath" in s]
        self.assertEqual(len(mk), 1)
        self.assertIn('"C:/out/shots"', mk[0])
        self.assertIn(ScriptBuilderEsc("D:\\out2"), mk[0])
        self.assertEqual(mk[0].count("mkpath"), 2)

    def test_shot_render_to_dict(self):
        out = render(RS, self.applied(), shots=["wide"])
        d = out[0].to_dict()
        json.dumps(d)
        self.assertEqual((d["shot_id"], d["camera_label"], d["output"]),
                         ("wide", f"{RID}:cu", "C:/out/shots/wide.png"))
        self.assertTrue(d["result"]["success"])
        self.assertIsInstance(out[0], ShotRender)

    def test_no_shots_renders_nothing(self):
        out = render(R, fake_scene(live_matching(D)))
        self.assertEqual(out, [])
        self.mock.assert_not_called()

    def test_exports(self):
        for name in ("ShotRender", "RecipeNotAppliedError"):
            self.assertIn(name, dazpy.__all__)
            self.assertTrue(hasattr(dazpy, name))
        self.assertIsNot(dazpy.render, render)


def ScriptBuilderEsc(v):
    from dazpy._script_builder import ScriptBuilder
    return ScriptBuilder.escape_string(v)


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


def two_actor_recipe(anna_pos=(0, 0, 0)) -> dict:
    return {
        "recipe_version": 1, "id": RID,
        "assets": {"g9": {"path": G9}},
        "actors": {"anna": {"asset": "g9", "position": list(anna_pos), "pose": POSE},
                   "ben": {"asset": "g9", "position": [120, 0, 0], "facing": "anna"}},
        "cameras": {"cu": {"frame": "anna", "shot_type": "close_up", "focal_length": 85}},
    }


class RoundTripTests(unittest.TestCase):
    """apply -> record JSON in the (simulated) scene -> read_live -> diff, end to end."""

    def setUp(self):
        patch_sim(self)
        self.sim = SimStudio()

    def assert_no_op(self, recipe, **kw):
        p = plan(recipe, self.sim, **kw)
        self.assertEqual((p.steps, p.conflicts), ((), ()))
        return p

    def test_moving_an_actor_in_the_recipe_round_trips_to_a_no_op(self):
        self.assertTrue(apply(two_actor_recipe(), self.sim).applied)
        self.assertEqual(plan(two_actor_recipe(), self.sim).warnings, ())
        moved = two_actor_recipe(anna_pos=(-40, 0, 60))
        result = apply(moved, self.sim)
        self.assertTrue(result.applied)
        self.assertIn(("modify", "actors.anna"), [(s.op, s.path) for s in result.steps])
        self.assertIn(("modify", "actors.ben"), [(s.op, s.path) for s in result.steps])
        self.assertEqual(self.assert_no_op(moved).warnings, ())
        self.assertTrue(observe(moved, self.sim).in_sync)

    def test_kept_removal_releases_ownership_and_round_trips_to_a_no_op(self):
        r = two_actor_recipe()
        r["props"] = {"ball": {"asset": "g9", "position": [0, 0, 100]}}
        self.assertTrue(apply(r, self.sim).applied)
        ball = self.sim.by_label(f"{RID}:ball")
        ball["position"][0] += 30.0  # hand tweak
        bare = two_actor_recipe()
        self.assertTrue(plan(bare, self.sim).blocked)  # removed_from_recipe conflict
        result = apply(bare, self.sim, on_conflict="scene_wins")
        self.assertTrue(result.applied)
        self.assertIn("removed_entity_kept", [w.code for w in result.warnings])
        self.assertIn(ball["name"], self.sim.nodes)  # kept in the scene ...
        self.assertIsNone(ball["record"])            # ... but no longer owned
        self.assertEqual(self.assert_no_op(bare).warnings, ())
        self.assertTrue(observe(bare, self.sim).in_sync)

    def test_accepted_hand_deletion_round_trips_to_a_no_op(self):
        r = two_actor_recipe()
        self.assertTrue(apply(r, self.sim).applied)
        self.sim.delete(self.sim.by_label(f"{RID}:cu")["name"])  # deleted by hand
        self.assertFalse(observe(r, self.sim).in_sync)
        self.assertTrue(apply(r, self.sim, on_conflict="scene_wins").applied)
        p = self.assert_no_op(r)
        self.assertEqual([(w.code, w.path) for w in p.warnings], [("hand_deleted_kept", "cameras.cu")])
        rep = observe(r, self.sim)
        self.assertEqual((rep.in_sync, rep.pending), (True, ()))


if __name__ == "__main__":
    unittest.main()
