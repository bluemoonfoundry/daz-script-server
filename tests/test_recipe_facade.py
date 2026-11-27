"""Unit tests for the public scene-recipe facade (validate / plan / apply / observe)."""

import copy
import dataclasses
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
from dazpy.recipe import (ShotRender, apply, observe, plan, recipe_schema,
                          render, validate)
from recipe_fakes import (RID, SimStudio, fake_scene, live_matching, live_without,
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

    def test_recipe_schema_returns_v1_by_default_and_v2(self):
        self.assertEqual(recipe_schema()["properties"]["recipe_version"]["const"], 1)
        self.assertEqual(recipe_schema(2)["properties"]["recipe_version"]["const"], 2)
        with self.assertRaises(ValueError):
            recipe_schema(3)

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


class BusyWaitTests(unittest.TestCase):
    """Recipe calls wait out a busy Studio (Studio 6 after a load or clear)."""

    def scene(self):
        from dazpy import DazClient, DazScene
        from dazpy.exceptions import DazError
        client = DazClient(token="t", check_version=False)
        waits = []

        def execute(script, *a, **kw):
            waits.append(getattr(client.__dict__.get("_busy_wait"), "max_wait", None))
            raise DazError("stop")  # one recorded call is enough
        client.execute = execute
        return DazScene(client), waits

    def test_each_entry_point_waits_out_busy_and_stops_after(self):
        from dazpy.exceptions import DazError
        from dazpy.recipe import RECIPE_BUSY_WAIT_S
        r = {"recipe_version": 1, "id": "r", "assets": {"g": {"path": "C:/g.duf"}},
             "actors": {"a": {"asset": "g"}}, "cameras": {"c": {"frame": "a"}},
             "shots": [{"id": "s", "camera": "c", "output": "C:/o.png"}]}
        for fn in (dazpy.recipe.validate, dazpy.recipe.plan, dazpy.recipe.apply,
                   dazpy.recipe.observe, dazpy.recipe.render):
            scene, waits = self.scene()
            with self.assertRaises(DazError):
                fn(r, scene)
            self.assertEqual(waits, [RECIPE_BUSY_WAIT_S], fn.__name__)
            self.assertIsNone(scene._client.__dict__["_busy_wait"].max_wait, fn.__name__)


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

    def test_parts_an_asset_loads_with_are_not_foreign_children(self):
        # Genesis 9 loads Eyes/Mouth as child figures: removing the actor deletes it
        # with no has_foreign_children conflict, while a hand-added item still counts.
        self.sim = SimStudio(asset_parts=("Eyes", "Mouth"))
        self.assertTrue(apply(two_actor_recipe(), self.sim).applied)
        self.assert_no_op(two_actor_recipe())
        ben = self.sim.by_label(f"{RID}:ben")["name"]
        no_ben = two_actor_recipe()
        del no_ben["actors"]["ben"]
        result = apply(no_ben, self.sim)
        self.assertTrue(result.applied, result.conflicts)
        self.assertNotIn(ben, self.sim.nodes)
        self.assertNotIn(ben + "Eyes", self.sim.nodes)
        anna = self.sim.by_label(f"{RID}:anna")["name"]
        self.sim.add_node("Hat", parent=anna)
        no_anna = copy.deepcopy(no_ben)
        del no_anna["actors"]["anna"]
        del no_anna["cameras"]
        conflicts = plan(no_anna, self.sim).conflicts
        self.assertEqual([(c.path, c.kind, c.live) for c in conflicts],
                         [("actors.anna", "has_foreign_children", {"foreign_children": ["Hat"]})])

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

    def test_a_released_node_gives_up_the_recipe_label(self):
        # Kept, then re-added: the recreated node must be the only "<id>:ball".
        r = two_actor_recipe()
        r["props"] = {"ball": {"asset": "g9", "position": [0, 0, 100]}}
        self.assertTrue(apply(r, self.sim).applied)
        old = self.sim.by_label(f"{RID}:ball")
        old["position"][0] += 30.0  # hand tweak -> removal conflict
        self.assertTrue(apply(two_actor_recipe(), self.sim, on_conflict="scene_wins").applied)
        self.assertEqual(old["label"], "ball")
        self.assertTrue(apply(r, self.sim).applied)
        self.assertIsNot(self.sim.by_label(f"{RID}:ball"), old)

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


# ── v2: asset refs, finders, compatibility, pins (Task 13) ───────────────────

from dazpy._asset_finder import AssetCandidate
from dazpy._asset_resolve import ResolvedAsset
from dazpy.recipe import pin
from recipe_fakes import (FakeFinder, fig_payload, item_payload, live_entity_for, live_of)

HAIR = "/People/Genesis 9/Hair/Bob.duf"
HAIR_B = "/People/Genesis 9/Hair/Bob B.duf"
G8_HAIR = "/People/Genesis 8 Female/Hair/Long.duf"
SHAPE = "/People/Genesis 9/Shapes/Tall.duf"
COMPAT = {G9: {"bases": [], "known": True, "provides": "/Genesis 9"},
          HAIR: {"bases": ["/Genesis 9"], "known": True, "provides": None},
          SHAPE: {"bases": ["/Genesis 9"], "known": True, "provides": None},
          G8_HAIR: {"bases": ["/Genesis 8/Female"], "known": True, "provides": None}}


def cand(path=HAIR, product="Bob Hair", sku="123"):
    return AssetCandidate(path, product, sku, "a1", "Follower/Hair")


def v2_recipe(*wearing, presets=(), assets=None, abby_asset=G9, **abby) -> dict:
    actor = {"asset": abby_asset, **abby}
    if wearing:
        actor["wearing"] = list(wearing)
    if presets:
        actor["presets"] = list(presets)
    r = {"recipe_version": 2, "id": RID, "actors": {"abby": actor}}
    if assets:
        r["assets"] = assets
    return r


def codes(issues):
    return {(i.path, i.code) for i in issues}


class TestV2Facade(FacadeCase):
    def test_validate_reports_ambiguous_find(self):
        finder = FakeFinder(search=[cand(HAIR, "Bob Hair A"), cand(HAIR_B, "Bob Hair B", "124")])
        rep = validate(v2_recipe({"add": {"find": "bob hair"}, "key": "hair"}),
                       fake_scene(compat=COMPAT), finder=finder)
        self.assertFalse(rep.ok)
        self.assertIn(("actors.abby.wearing.hair", "ambiguous_asset"), codes(rep.errors))
        self.assertEqual(finder.calls, ["search:bob hair"])

    def test_validate_reports_incompatible(self):
        scene = fake_scene(compat=COMPAT)
        rep = validate(v2_recipe({"add": G8_HAIR, "key": "hair"}, presets=[SHAPE]), scene)
        self.assertFalse(rep.ok)
        self.assertEqual(codes(rep.errors), {("actors.abby.wearing.hair", "incompatible_asset")})
        self.assertIn("/Genesis 8/Female", rep.errors[0].message)
        # a created actor's base comes from its asset's metadata: no live figure read
        self.assertEqual(scene.scripts_with("recipe:figures"), [])

    def test_validate_unknown_compatibility_warns(self):
        rep = validate(v2_recipe({"add": "/My/own/hat.duf", "key": "hat"}), fake_scene(compat=COMPAT))
        self.assertTrue(rep.ok)
        self.assertEqual(codes(rep.warnings), {("actors.abby.wearing.hat", "compatibility_unknown")})

    def test_validate_taken_over_actor_uses_the_live_figure_base(self):
        scene = fake_scene(compat=COMPAT, figures=[
            fig_payload("Genesis8Female", "Abby", compat_base="/Genesis 8/Female")])
        rep = validate(v2_recipe({"add": HAIR, "key": "hair"}, node="Abby"), scene)
        self.assertEqual(codes(rep.errors), {("actors.abby.wearing.hair", "incompatible_asset")})
        self.assertEqual(len(scene.scripts_with("recipe:figures")), 1)

    def test_apply_incompatible_changes_nothing(self):
        scene = fake_scene(compat=COMPAT)
        r = v2_recipe({"add": G8_HAIR, "key": "hair"})
        for fn in (plan, apply):
            with self.assertRaises(RecipeValidationError) as cm:
                fn(r, scene)
            self.assertEqual(codes(cm.exception.report.errors),
                             {("actors.abby.wearing.hair", "incompatible_asset")})
        self.assertEqual(scene.ops.calls, [])
        self.assertFalse([s for s in scene._client.scripts
                          if "DzDeleteAction" in s or "loadContent" in s or "openFile" in s])

    def test_apply_wearing_error_raises_before_diff(self):
        scene = fake_scene(compat=COMPAT, figures=[fig_payload("G9", "Abby", compat_base="/Genesis 9")])
        r = v2_recipe({"replace": {"type": "hair"}, "with": HAIR, "key": "hair"}, node="Abby")
        with self.assertRaises(RecipeValidationError) as cm:
            apply(r, scene)
        self.assertEqual(codes(cm.exception.report.errors),
                         {("actors.abby.wearing.hair", "replace_target_missing")})
        self.assertEqual(scene.ops.calls, [])

    def test_apply_resolves_fits_and_records_source(self):
        scene = fake_scene(compat=COMPAT)
        result = apply(v2_recipe({"add": {"sku": "123"}, "key": "hair"}), scene,
                       finder=FakeFinder(files=[cand()]))
        self.assertTrue(result.applied, result.error)
        self.assertEqual([m for m in scene.ops.methods() if m in ("create", "fit")],
                         ["create", "fit"])
        records = {c[2].path: c[2] for c in scene.ops.calls_with_args if c[0] == "write_record"}
        self.assertEqual(records["actors.abby.wearing.hair"].source["path"], HAIR)
        self.assertEqual(records["actors.abby.wearing.hair"].source["sku"], "123")
        self.assertEqual(records["actors.abby"].source["path"], G9)

    def test_plan_names_finder(self):
        finder = FakeFinder(files=[cand()], name="fake")
        p = plan(v2_recipe({"add": {"product": "Bob Hair"}, "key": "hair"}), fake_scene(compat=COMPAT),
                 finder=finder)
        self.assertEqual(p.finder, "fake")
        self.assertEqual(p.to_dict()["finder"], "fake")
        self.assertIn("fit", [s.op for s in p.steps])
        # path references never consult (or probe for) a finder
        path_only = plan(v2_recipe({"add": HAIR, "key": "hair"}), fake_scene(compat=COMPAT),
                         finder=FakeFinder(name="unused"))
        self.assertEqual(path_only.finder, "path")
        v1 = plan(R, fake_scene())
        self.assertEqual(v1.finder, "path")
        self.assertNotIn("finder", v1.to_dict())

    def test_v1_recipe_makes_no_v2_round_trips(self):
        with patch("dazpy.recipe.select_finder") as sel:
            scene = fake_scene()
            self.assertTrue(apply(R, scene).applied)
            plan(R, scene)
            observe(R, scene)
            self.assertTrue(validate(R, scene).ok)
        sel.assert_not_called()
        for marker in ("recipe:compat", "recipe:figures", "asset_finder:"):
            self.assertEqual(scene.scripts_with(marker), [], marker)

    def test_compat_warnings_reach_plan_and_apply_result(self):
        r = v2_recipe({"add": "/My/own/hat.duf", "key": "hat"})
        p = plan(r, fake_scene(compat=COMPAT))
        self.assertIn(("actors.abby.wearing.hat", "compatibility_unknown"), codes(p.warnings))
        result = apply(r, fake_scene(compat=COMPAT))
        self.assertIn(("actors.abby.wearing.hat", "compatibility_unknown"), codes(result.warnings))

    def test_pin_fills_resolved(self):
        r = v2_recipe({"add": {"sku": "123"}, "key": "hair"}, presets=[SHAPE],
                      assets={"g9": G9}, abby_asset="g9")
        finder = FakeFinder(files=[cand()])
        out = pin(r, fake_scene(), finder=finder)
        self.assertEqual(out["assets"]["g9"], {"path": G9, "resolved": {"path": G9}})
        self.assertEqual(out["actors"]["abby"]["asset"], "g9")
        self.assertEqual(out["actors"]["abby"]["presets"], [{"path": SHAPE, "resolved": {"path": SHAPE}}])
        self.assertEqual(out["actors"]["abby"]["wearing"][0]["add"],
                         {"sku": "123", "resolved": {"path": HAIR, "sku": "123",
                                                     "product": "Bob Hair", "asset_id": "a1"}})
        self.assertTrue(validate(out).ok)
        # a pinned recipe resolves from its pins: the finder is not asked again
        again = FakeFinder()
        self.assertEqual(pin(out, fake_scene(), finder=again), out)
        self.assertEqual(again.calls, [])

    def test_pin_v1_recipe_becomes_v2(self):
        out = pin(R, fake_scene())
        self.assertEqual(out["recipe_version"], 2)
        self.assertEqual(out["assets"]["g9"]["resolved"], {"path": G9})
        self.assertTrue(validate(out).ok)

    def test_pin_unresolvable_raises(self):
        with self.assertRaises(RecipeValidationError) as cm:
            pin(v2_recipe({"add": {"find": "nothing"}, "key": "hair"}), fake_scene(),
                finder=FakeFinder())
        self.assertEqual(codes(cm.exception.report.errors),
                         {("actors.abby.wearing.hair", "asset_not_found")})

    def test_validate_env_browser_down_warns(self):
        import socket
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]  # closed once the socket is
        old = os.environ.get("DAZ_BROWSER_URL")
        os.environ["DAZ_BROWSER_URL"] = f"http://127.0.0.1:{port}"
        try:
            scene = fake_scene(compat=COMPAT, cms=[
                {"path": HAIR, "product": "Bob Hair", "sku": "123", "asset_id": "a1",
                 "type": "Follower/Hair"}])
            r = v2_recipe({"add": {"product": "Bob Hair"}, "key": "hair"})
            rep = validate(r, scene)
            self.assertTrue(rep.ok, rep.errors)
            self.assertIn(("", "finder_fallback"), codes(rep.warnings))
            self.assertEqual(len(scene.scripts_with("asset_finder:product_files")), 1)
        finally:
            if old is None:
                os.environ.pop("DAZ_BROWSER_URL", None)
            else:
                os.environ["DAZ_BROWSER_URL"] = old

    def _applied_with_hair(self, live_source: str):
        r = v2_recipe({"add": HAIR, "key": "hair"})
        model = SceneRecipe.from_dict(r)
        resolved = {"actors.abby.asset": ResolvedAsset(dazpy.AssetRef(path=G9), G9, None, None, None,
                                                       None, "path"),
                    "actors.abby.wearing.hair": ResolvedAsset(dazpy.AssetRef(path=HAIR), HAIR,
                                                              None, None, None, None, "path")}
        d = compute_desired(model, resolved)
        actor = live_entity_for(d["actors.abby"], node_name="Genesis 9")
        item = live_entity_for(d["actors.abby.wearing.hair"], group_nodes=("Bob",))
        item = dataclasses.replace(item, record=dataclasses.replace(
            item.record, source=resolved["actors.abby.wearing.hair"].to_dict(), primary=True))
        scene = fake_scene(live_of(actor, item), compat=COMPAT, figures=[fig_payload(
            "Genesis 9", f"{RID}:abby", compat_base="/Genesis 9",
            items=[item_payload("Bob", source_path=live_source, record=item.record)])])
        return r, scene

    def test_observe_source_changed(self):
        r, scene = self._applied_with_hair("/People/Genesis 9/Hair/Other.duf")
        rep = observe(r, scene)
        self.assertIn(("actors.abby.wearing.hair", "source_changed"), codes(rep.drift))
        self.assertFalse(rep.in_sync)

    def test_observe_same_source_is_not_drift(self):
        r, scene = self._applied_with_hair("/People/Genesis%209/Hair/Bob.duf")
        rep = observe(r, scene)
        self.assertNotIn("source_changed", [i.code for i in rep.drift])

    def test_unchanged_reference_reuses_the_recorded_resolution(self):
        r = v2_recipe({"add": {"sku": "123"}, "key": "hair"})
        first = fake_scene(compat=COMPAT)
        self.assertTrue(apply(r, first, finder=FakeFinder(files=[cand()])).applied)
        records = {c[2].path: c[2] for c in first.ops.calls_with_args if c[0] == "write_record"}
        entities = []
        for path, node_name in (("actors.abby", "Genesis 9"), ("actors.abby.wearing.hair", "Bob")):
            e = live_entity_for(compute_desired(SceneRecipe.from_dict(r), {
                "actors.abby.asset": ResolvedAsset(dazpy.AssetRef(path=G9), G9, None, None, None,
                                                   None, "path"),
                "actors.abby.wearing.hair": ResolvedAsset(dazpy.AssetRef(sku="123"), HAIR, "123",
                                                          None, None, None, "fake")})[path],
                node_name=node_name)
            entities.append(dataclasses.replace(e, record=records[path]))
        again = FakeFinder()
        p = plan(r, fake_scene(live_of(*entities), compat=COMPAT), finder=again)
        self.assertEqual((again.calls, p.finder), ([], "path"))
        self.assertNotIn("fit", [s.op for s in p.steps])

    def test_package_exports_v2(self):
        for name in ("pin", "AssetRef", "AssetFinder", "StudioFinder", "ContentBrowserFinder"):
            self.assertIn(name, dazpy.__all__)
            self.assertTrue(hasattr(dazpy, name))


# ── Task 13 fix round 1 ──────────────────────────────────────────────────────

def live_after(scene) -> LiveState:
    """The LiveState the records *scene*'s FakeOps wrote describe (last write wins)."""
    from dazpy._recipe_store import _kind_from_path
    ents = {}
    for _, node_name, r in (c for c in scene.ops.calls_with_args if c[0] == "write_record"):
        if not r.primary:
            continue
        kind = _kind_from_path(r.path)
        ents[r.path] = LiveEntity(path=r.path, node_name=node_name, kind=kind, record=r,
                                  observed=copy.deepcopy(r.observed), foreign_children=(),
                                  group_nodes=(node_name,) if kind == "item" else ())
    return live_of(*ents.values())


TALL = SHAPE
SHORT = "/People/Genesis 9/Shapes/Short.duf"


class TestV2FixRound1(FacadeCase):
    def test_v2_inline_missing_file_is_invalid_and_apply_raises_first(self):
        missing = "/Missing/G9.duf"
        for r in ({"recipe_version": 2, "id": RID, "actors": {"a": {"asset": missing}}},
                  {"recipe_version": 2, "id": RID, "actors": {"a": {"asset": {"path": missing}}}},
                  {"recipe_version": 2, "id": RID, "props": {"p": {"asset": missing}}}):
            scene = fake_scene(missing_files={missing})
            rep = validate(r, scene)
            self.assertFalse(rep.ok, r)
            self.assertEqual({e.code for e in rep.errors}, {"asset_not_found"})
            with self.assertRaises(RecipeValidationError):
                apply(r, scene)
            self.assertEqual(scene.ops.calls, [])

    def test_recorded_finder_and_preset_resolution_survive_a_second_apply(self):
        r1 = v2_recipe(presets=[{"find": "Tall"}])
        first = fake_scene(compat={**COMPAT, SHORT: COMPAT[SHAPE]})
        found = FakeFinder(search=[AssetCandidate(TALL, "Tall", "55", "t1", "Actor/Shape")],
                           name="studio")
        self.assertTrue(apply(r1, first, finder=found).applied)
        live = live_after(first)
        self.assertEqual(live.entities["actors.abby"].record.source["presets"][0]["finder"], "studio")
        r2 = v2_recipe(presets=[{"find": "Tall"}, SHORT])
        second = fake_scene(live, compat={**COMPAT, SHORT: COMPAT[SHAPE]})
        again = FakeFinder(name="unused")
        result = apply(r2, second, finder=again)
        self.assertTrue(result.applied, result.error)
        self.assertEqual(again.calls, [])  # the recorded preset resolution is re-used
        rec2 = live_after(second).entities["actors.abby"].record
        self.assertEqual([(x["path"], x["finder"]) for x in rec2.source["presets"]],
                         [(TALL, "studio"), (SHORT, "path")])
        self.assertEqual(rec2.source["presets"][0]["sku"], "55")

    def test_reused_item_resolution_keeps_its_finder(self):
        r = v2_recipe({"add": {"sku": "123"}, "key": "hair"})
        first = fake_scene(compat=COMPAT)
        self.assertTrue(apply(r, first, finder=FakeFinder(files=[cand()], name="studio")).applied)
        live = live_after(first)
        _, desired, _ = dazpy.recipe._plan(SceneRecipe.from_dict(r), fake_scene(live, compat=COMPAT),
                                           "ask", None, FakeFinder(name="unused"))
        self.assertEqual(desired["actors.abby.wearing.hair"].create["source"]["finder"], "studio")

    def test_created_actor_bases_share_one_compat_read(self):
        r = {"recipe_version": 2, "id": RID, "actors": {
            "abby": {"asset": G9, "presets": [SHAPE]},
            "ben": {"asset": G9 + "x", "presets": [SHAPE], "position": [100, 0, 0]}}}
        scene = fake_scene(compat={**COMPAT, G9 + "x": COMPAT[G9]})
        self.assertTrue(validate(r, scene).ok)
        self.assertEqual(len(scene.scripts_with("recipe:compat")), 1)

    def test_source_drift_matches_items_under_their_own_figure(self):
        r = {"recipe_version": 2, "id": RID, "actors": {
            "abby": {"asset": G9, "wearing": [{"add": HAIR, "key": "hair"}]},
            "ben": {"asset": G9, "position": [100, 0, 0],
                    "wearing": [{"add": HAIR, "key": "hair"}]}}}
        first = fake_scene(compat=COMPAT)
        first.ops.create_names = {"actors.abby": ["Abby"], "actors.ben": ["Ben"]}
        first.ops.fit_names = {"actors.abby.wearing.hair": ["Bob"],
                               "actors.ben.wearing.hair": ["Bob"]}
        self.assertTrue(apply(r, first).applied)
        live = live_after(first)
        rec_of = {p: e.record for p, e in live.entities.items()}
        figures = [
            fig_payload("Abby", f"{RID}:abby", compat_base="/Genesis 9", items=[item_payload(
                "Bob", source_path=HAIR, record=rec_of["actors.abby.wearing.hair"])]),
            fig_payload("Ben", f"{RID}:ben", compat_base="/Genesis 9", items=[item_payload(
                "Bob", source_path="/Other/hair.duf", record=rec_of["actors.ben.wearing.hair"])])]
        rep = observe(r, fake_scene(live, compat=COMPAT, figures=figures))
        self.assertEqual([(i.path, i.code) for i in rep.drift if i.code == "source_changed"],
                         [("actors.ben.wearing.hair", "source_changed")])

    def test_render_passes_finder_through(self):
        finder = FakeFinder(files=[cand()])
        self.assertEqual(render(v2_recipe({"add": {"sku": "123"}, "key": "hair"}),
                                fake_scene(compat=COMPAT), finder=finder, force=True), [])
        self.assertEqual(finder.calls, ["product_files:123"])

    def test_v1_apply_validates_offline_once(self):
        with patch("dazpy.recipe.validate_offline", wraps=dazpy.recipe.validate_offline) as vo:
            self.assertTrue(apply(R, fake_scene()).applied)
        self.assertEqual(vo.call_count, 1)


if __name__ == "__main__":
    unittest.main()
