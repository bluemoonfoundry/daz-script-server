"""Unit tests for the scene-recipe executor (dazpy._recipe_apply) and DazSceneOps.

The executor runs against ``FakeOps`` (records calls, fails on chosen calls);
``DazSceneOps`` runs against a mocked client and asserts the scripts / dazpy
calls it makes.  No DAZ Studio needed.
"""

import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dazpy._recipe_apply import ApplyResult, execute
from dazpy._recipe_diff import Step, diff
from dazpy._recipe_ops import DazSceneOps
from dazpy._recipe_store import (EntityRecord, LiveState, Manifest, remove_record_script,
                                 write_manifest_script, write_record_script)
from dazpy._pose import DazPose
from dazpy._scene import DazScene
from dazpy.exceptions import DazBusyError, DazError
from dazpy.lighting import HDRIEnvironment
from recipe_fakes import (ENV_PATH, FAKE_OBSERVED, RID, FakeOps, d_actor, d_camera,
                          d_environment, d_light, d_prop, ds, live_matching, live_with_children,
                          live_without, scripted_client, with_observed, live_tweaked)

EMPTY = LiveState(None, {}, None)


def run(D, L, ops, **kw):
    plan = diff(D, L, **kw)
    return plan, execute(plan, D, L, ops, recipe_id=RID, recipe_version=1)


def written_records(ops) -> dict:
    """node name -> last EntityRecord written for it."""
    return {c[1]: c[2] for c in ops.calls_with_args if c[0] == "write_record"}


def written_manifest(ops) -> Manifest:
    return [c[1] for c in ops.calls_with_args if c[0] == "write_manifest"][-1]


# Camera "one" + light "key" applied earlier; the new recipe adds camera "new"
# and changes camera one's focal length: plan = [create cameras.new, modify cameras.one].
D_OLD = ds(d_camera("one"), d_light("key"))
L_OLD = live_matching(D_OLD)
D_CREATE_MODIFY = ds(d_camera("one", focal_length=85.0), d_light("key"), d_camera("new"))
NAMES = {"cameras.new": ["cam_new"]}


class ExecuteSuccessTests(unittest.TestCase):
    def test_success_writes_records_and_manifest_after_mutations(self):
        ops = FakeOps(create_names=NAMES)
        plan, r = run(D_CREATE_MODIFY, L_OLD, ops)
        self.assertEqual([s.op for s in plan.steps], ["create", "modify"])
        self.assertIsInstance(r, ApplyResult)
        self.assertTrue(r.applied)
        self.assertFalse(r.rolled_back)
        self.assertEqual(r.steps, plan.steps)
        m = ops.methods()
        last_mutation = max(i for i, x in enumerate(m) if x in ("create", "set_channels"))
        self.assertLess(last_mutation, m.index("write_record"))
        self.assertEqual(m[-1], "write_manifest")
        self.assertEqual(m.count("write_manifest"), 1)

    def test_create_record_stores_all_desired_plus_create_info_and_fresh_observed(self):
        ops = FakeOps(create_names=NAMES)
        run(D_CREATE_MODIFY, L_OLD, ops)
        r = written_records(ops)["cam_new"]
        self.assertEqual(r.recipe_id, RID)
        self.assertEqual(r.path, "cameras.new")
        self.assertEqual(r.desired, dict(D_CREATE_MODIFY["cameras.new"].channels, _create={}))
        self.assertEqual(r.observed, FAKE_OBSERVED)

    def test_create_applies_every_desired_channel_to_the_owned_root(self):
        ops = FakeOps(create_names={"cameras.new": ["cam_new", "cam_extra"]})
        run(D_CREATE_MODIFY, L_OLD, ops)
        self.assertIn(("set_channels", "cam_new", "camera", D_CREATE_MODIFY["cameras.new"].channels),
                      ops.calls_with_args)

    def test_modify_record_merges_only_changed_channels(self):
        # Light key: transform hand-tweaked (kept), output changed by the recipe.
        D = ds(d_camera("one"), d_light("key", intensity=2.0))
        L = live_tweaked(D_OLD, "lighting.lights.key", "transform")
        fresh = {"transform": {"position": [9.0, 9.0, 9.0], "rotation": [0.0, 0.0, 0.0]},
                 "output": {"intensity": 2.0, "color": [255, 255, 255]}}
        ops = FakeOps(observed={"r1:key": fresh})
        plan, r = run(D, L, ops)
        self.assertTrue(r.applied)
        old = L.entities["lighting.lights.key"].record
        new = written_records(ops)["r1:key"]
        self.assertEqual(new.desired["output"], D["lighting.lights.key"].channels["output"])
        self.assertEqual(new.observed["output"], fresh["output"])
        self.assertEqual(new.desired["transform"], old.desired["transform"])
        self.assertEqual(new.observed["transform"], old.observed["transform"])
        self.assertEqual(new.desired["_create"], old.desired["_create"])

    def test_adopt_rewrites_record_with_live_observed_and_new_desired(self):
        D = ds(d_camera("one"), d_light("key", intensity=2.0))
        live_out = {"intensity": 2.0, "color": [255, 255, 255]}
        L = with_observed(L_OLD, "lighting.lights.key", "output", live_out)
        ops = FakeOps()
        plan, r = run(D, L, ops)
        self.assertEqual([s.op for s in plan.steps], ["adopt"])
        self.assertTrue(r.applied)
        self.assertNotIn("set_channels", ops.methods())
        old = L.entities["lighting.lights.key"].record
        new = written_records(ops)["r1:key"]
        self.assertEqual(new.desired["output"], D["lighting.lights.key"].channels["output"])
        self.assertEqual(new.observed["output"], live_out)
        self.assertEqual(new.desired["transform"], old.desired["transform"])
        self.assertEqual(new.desired["_create"], old.desired["_create"])

    def test_manifest_lists_owned_nodes_and_tombstones(self):
        # box deleted by hand (accepted -> tombstone); ball removed from recipe but
        # hand-tweaked (kept); camera one untouched.
        D_old = ds(d_camera("one"), d_prop("ball"), d_prop("box"))
        L = live_tweaked(D_old, "props.ball", "transform", live=live_without(live_matching(D_old), "props.box"))
        D = ds(d_camera("one"), d_prop("box"))
        ops = FakeOps()
        plan, r = run(D, L, ops, on_conflict="scene_wins")
        self.assertEqual(plan.steps, ())
        self.assertTrue(r.applied)
        self.assertEqual(ops.methods(), ["write_manifest"])
        m = written_manifest(ops)
        self.assertEqual(set(m.entities), {"cameras.one", "props.ball"})
        self.assertEqual(m.deleted, ("props.box",))
        self.assertIsNone(m.environment)

    def test_manifest_drops_deleted_entities(self):
        D_old = ds(d_camera("one"), d_prop("ball"))
        ops = FakeOps()
        plan, r = run(ds(d_camera("one")), live_matching(D_old), ops)
        self.assertEqual([s.op for s in plan.steps], ["delete"])
        self.assertIn(("delete", "r1:ball"), ops.calls)
        self.assertEqual(written_manifest(ops).entities, ("cameras.one",))

    def test_first_environment_records_desired_and_observed(self):
        env_obs = {"intensity": 1.0, "rotation_deg": 0.0, "mode": 0, "draw_dome": True,
                   "image_path": "/hdri/sky.hdr"}
        D = ds(d_environment())
        ops = FakeOps(environment=env_obs)
        plan, r = run(D, EMPTY, ops)
        self.assertTrue(r.applied)
        self.assertIn(("set_environment", D[ENV_PATH].channels["environment"]), ops.calls_with_args)
        env = written_manifest(ops).environment
        self.assertEqual(env, EntityRecord(RID, ENV_PATH, 1, {"environment": D[ENV_PATH].channels["environment"]},
                                           {"environment": env_obs}))

    def test_untouched_environment_keeps_previous_record(self):
        D_old = ds(d_camera("one"), d_environment())
        L = live_matching(D_old)
        ops = FakeOps()
        run(ds(d_camera("one", focal_length=85.0), d_environment()), L, ops)
        self.assertEqual(written_manifest(ops).environment, L.manifest.environment)

    def test_blocked_plan_executes_nothing(self):
        D = ds(d_camera("one"), d_light("key", intensity=2.0))
        L = live_tweaked(D_OLD, "lighting.lights.key", "output")
        ops = FakeOps()
        plan, r = run(D, L, ops)
        self.assertTrue(plan.blocked)
        self.assertFalse(r.applied)
        self.assertFalse(r.rolled_back)
        self.assertEqual(r.conflicts, plan.conflicts)
        self.assertEqual(ops.calls, [])


class RollbackTests(unittest.TestCase):
    def test_failure_after_create_deletes_created_nodes(self):
        ops = FakeOps(fail_on=("set_channels", 1), create_names={"cameras.new": ["cam_new", "cam_2"]})
        plan, r = run(D_CREATE_MODIFY, L_OLD, ops)
        self.assertFalse(r.applied)
        self.assertTrue(r.rolled_back)
        self.assertEqual(r.failed_step.op, "create")
        self.assertIn("set_channels failed", r.error)
        self.assertIn(("delete", "cam_new"), ops.calls)
        self.assertIn(("delete", "cam_2"), ops.calls)
        self.assertNotIn("write_record", ops.methods())
        self.assertNotIn("write_manifest", ops.methods())

    def test_failure_after_modify_restores_prior_values(self):
        D = dict(D_CREATE_MODIFY, **ds(d_environment()))
        ops = FakeOps(fail_on=("set_environment", 1), create_names=NAMES)
        plan, r = run(D, L_OLD, ops)
        prior = next(s.prior for s in plan.steps if s.op == "modify")
        self.assertTrue(r.rolled_back)
        self.assertEqual(r.failed_step.op, "set_environment")
        self.assertEqual(ops.calls_with_args[-2:],
                         [("set_channels", "r1:one", "camera", prior), ("delete", "cam_new")])

    def test_failed_modify_itself_is_restored(self):
        # A modify can fail halfway (position written, rotation not): restore it too.
        ops = FakeOps(fail_on=("set_channels", 2), create_names=NAMES)
        plan, r = run(D_CREATE_MODIFY, L_OLD, ops)
        prior = next(s.prior for s in plan.steps if s.op == "modify")
        self.assertEqual(r.failed_step.op, "modify")
        self.assertIn(("set_channels", "r1:one", "camera", prior), ops.calls_with_args)

    def test_busy_error_mid_apply_rolls_back(self):
        ops = FakeOps(fail_on=("create", 2), exc=DazBusyError("busy"))
        plan, r = run(ds(d_camera("a"), d_camera("b")), EMPTY, ops)
        self.assertTrue(r.rolled_back)
        self.assertIsInstance(r.failed_step, Step)
        self.assertEqual(r.failed_step.path, "cameras.b")
        self.assertEqual(r.error, "busy")
        self.assertIn(("delete", "r1:a"), ops.calls)
        self.assertEqual(r.rollback_errors, ())

    def test_failure_in_delete_phase_reports_partial_deletes(self):
        D_old = ds(d_light("key"), d_prop("ball"), d_prop("box"))
        L = live_matching(D_old)
        ops = FakeOps(fail_on=("delete", 2))
        plan, r = run(ds(d_light("key", intensity=2.0)), L, ops)
        self.assertEqual([s.op for s in plan.steps], ["modify", "delete", "delete"])
        self.assertTrue(r.rolled_back)
        self.assertEqual(r.failed_step.path, "props.box")
        self.assertEqual(r.steps, (plan.steps[1],))  # the delete that cannot be undone
        self.assertIn(("props.ball", "deleted_not_restored"), [(w.path, w.code) for w in r.warnings])
        # the light is restored, record and values
        self.assertIn(("set_channels", "r1:key", "light", plan.steps[0].prior), ops.calls_with_args)
        self.assertEqual(ops.calls_with_args[-2],
                         ("write_record", "r1:key", L.entities["lighting.lights.key"].record))
        self.assertNotIn("write_manifest", ops.methods())

    def test_deletes_run_after_records(self):
        D_old = ds(d_light("key"), d_prop("ball"))
        ops = FakeOps()
        run(ds(d_light("key", intensity=2.0)), live_matching(D_old), ops)
        m = ops.methods()
        self.assertLess(m.index("write_record"), m.index("delete"))
        self.assertEqual(m[-1], "write_manifest")

    def test_unparent_undone_when_owner_not_deleted(self):
        D_old = ds(d_prop("ball"), d_actor("anna"))
        L = live_with_children(D_old, "actors.anna", ("Shirt",))
        ops = FakeOps(fail_on=("delete", 2))  # ball deleted, anna fails
        plan, r = run(ds(), L, ops, on_conflict="recipe_wins")
        self.assertEqual([s.op for s in plan.steps], ["unparent", "delete", "delete"])
        self.assertTrue(r.rolled_back)
        self.assertIn(("unparent", ["Shirt"]), ops.calls_with_args)
        self.assertIn(("reparent", ["Shirt"], "r1:anna"), ops.calls_with_args)

    def test_unparent_not_undone_when_owner_already_deleted(self):
        D_old = ds(d_actor("anna"), d_prop("ball"))
        L = live_with_children(D_old, "actors.anna", ("Shirt",))
        ops = FakeOps(fail_on=("delete", 2))  # anna deleted, ball fails
        plan, r = run(ds(), L, ops, on_conflict="recipe_wins")
        self.assertTrue(r.rolled_back)
        self.assertNotIn("reparent", ops.methods())
        self.assertEqual(r.rollback_errors, ())

    def test_rollback_error_is_reported_not_raised(self):
        ops = FakeOps(fail_on=[("set_channels", 2), ("delete", 1)], create_names=NAMES)
        plan, r = run(D_CREATE_MODIFY, L_OLD, ops)
        self.assertTrue(r.rolled_back)
        self.assertEqual(len(r.rollback_errors), 1)
        self.assertIn("cam_new", r.rollback_errors[0])

    def test_environment_restored_from_pre_apply_observation(self):
        prior_env = {"intensity": 0.5, "rotation_deg": 90.0, "mode": 2, "draw_dome": False,
                     "image_path": "C:/old.hdr"}
        ops = FakeOps(fail_on=("write_record", 1), environment=prior_env)
        plan, r = run(ds(d_environment(), d_camera("new")), EMPTY, ops)
        self.assertTrue(r.rolled_back)
        self.assertIsNone(r.failed_step)  # failed while writing records, not in a plan step
        self.assertIn("cameras.new", r.error)
        self.assertEqual(ops.calls_with_args[-2:], [("set_environment", prior_env), ("delete", "r1:new")])

    def test_record_write_failure_restores_previous_record(self):
        ops = FakeOps(fail_on=("write_manifest", 1))
        plan, r = run(ds(d_camera("one"), d_light("key", intensity=2.0)), L_OLD, ops)
        self.assertTrue(r.rolled_back)
        self.assertIn(("write_record", "r1:key", L_OLD.entities["lighting.lights.key"].record),
                      ops.calls_with_args)

    def test_created_nodes_get_no_record_compensation(self):
        # they are deleted anyway; removing their record first only adds failure points
        ops = FakeOps(fail_on=("write_manifest", 1), create_names=NAMES)
        run(D_CREATE_MODIFY, L_OLD, ops)
        self.assertNotIn("remove_record", ops.methods())
        self.assertIn(("delete", "cam_new"), ops.calls)


# ── DazSceneOps against a mocked client ──────────────────────────────────────

class DazSceneOpsCreateTests(unittest.TestCase):
    def ops(self, *responses):
        client = scripted_client(*responses)
        return client, DazSceneOps(DazScene(client))

    def test_create_camera_labels_the_new_root(self):
        client, ops = self.ops(("recipe:snapshot", ["11", "12"]), ("new DzBasicCamera", "Camera 3"),
                               ("recipe:claim", ["Camera 3"]))
        names = ops.create(d_camera("new"))
        self.assertEqual(names, ["Camera 3"])
        roots = next(i for i, s in enumerate(client.scripts) if "recipe:snapshot" in s)
        make = next(i for i, s in enumerate(client.scripts) if "new DzBasicCamera" in s)
        claim = next(i for i, s in enumerate(client.scripts) if "recipe:claim" in s)
        self.assertLess(roots, make)
        self.assertLess(make, claim)
        self.assertIn(json.dumps("r1:new"), client.scripts[claim])
        self.assertIn('"11"', client.scripts[claim])
        self.assertIn("setName", client.scripts[claim])  # unique-name fix happens in the claim

    def test_create_light_uses_light_type(self):
        client, ops = self.ops(("recipe:snapshot", []), ("new DzSpotLight", "Spotlight 1"),
                               ("recipe:claim", ["Spotlight 1"]))
        self.assertEqual(ops.create(d_light("key")), ["Spotlight 1"])

    def test_asset_content_path_resolved_then_loaded(self):
        client, ops = self.ops(("findFile", "C:/Lib/g9.duf"), ("recipe:snapshot", ["1"]),
                               ("recipe:claim", ["Genesis 9", "Genesis 9 Eyes"]))
        names = ops.create(d_actor("anna"))
        self.assertEqual(names, ["Genesis 9", "Genesis 9 Eyes"])
        find = next(s for s in client.scripts if "findFile" in s)
        self.assertIn(json.dumps("/g9.duf"), find)
        load = [s for s in client.scripts if "loadScene" in s]
        self.assertEqual(len(load), 1)
        self.assertIn(json.dumps("C:/Lib/g9.duf"), load[0])

    def test_missing_content_path_raises_before_load(self):
        client, ops = self.ops(("findFile", ""))
        with patch("dazpy._recipe_ops.os.path.isfile", return_value=False):
            with self.assertRaises(DazError):
                ops.create(d_actor("anna"))
        self.assertFalse(any("loadScene" in s for s in client.scripts))

    def test_missing_absolute_path_raises_without_any_studio_call(self):
        client, ops = self.ops()
        entity = d_prop("ball")
        entity = type(entity)(entity.path, entity.kind, entity.label, {"asset_path": "C:/nope.duf"},
                              entity.channels)
        with patch("dazpy._recipe_ops.os.path.isfile", return_value=False):
            with self.assertRaises(DazError):
                ops.create(entity)
        self.assertEqual(client.scripts, [])

    def test_load_adding_no_root_node_removes_added_nodes_and_raises(self):
        client, ops = self.ops(("findFile", "C:/Lib/ball.duf"), ("recipe:snapshot", ["1", "2"]),
                               ("recipe:claim", []), ("recipe:cleanup", 1))
        with self.assertRaises(DazError):
            ops.create(d_prop("ball"))
        cleanup = [s for s in client.scripts if "recipe:cleanup" in s]
        self.assertEqual(len(cleanup), 1)
        self.assertIn('["1", "2"]', cleanup[0])  # all pre-load nodes, not just roots
        self.assertIn("Scene.removeNode", cleanup[0])
        self.assertLess(client.scripts.index(next(s for s in client.scripts if "loadScene" in s)),
                        client.scripts.index(cleanup[0]))

    def test_claim_failure_after_load_removes_added_nodes_and_reraises(self):
        def claim(script):
            raise RuntimeError("setLabel blew up")
        client, ops = self.ops(("findFile", "C:/Lib/ball.duf"), ("recipe:snapshot", ["1"]),
                               ("recipe:claim", claim), ("recipe:cleanup", 3))
        with self.assertRaisesRegex(RuntimeError, "setLabel blew up"):
            ops.create(d_prop("ball"))
        self.assertTrue(any("recipe:cleanup" in s for s in client.scripts))

    def test_failed_cleanup_is_reported_with_the_cause(self):
        def boom(script):
            raise RuntimeError("cleanup broke")
        client, ops = self.ops(("findFile", "C:/Lib/ball.duf"), ("recipe:snapshot", ["1"]),
                               ("recipe:claim", []), ("recipe:cleanup", boom))
        with self.assertRaisesRegex(DazError, "cleanup broke"):
            ops.create(d_prop("ball"))

    def test_snapshot_lists_every_node_not_only_roots(self):
        client, ops = self.ops(("recipe:snapshot", []), ("new DzBasicCamera", "Camera"),
                               ("recipe:claim", ["Camera"]))
        ops.create(d_camera("new"))
        snap = next(s for s in client.scripts if "recipe:snapshot" in s)
        self.assertNotIn("getNodeParent", snap)


class DazSceneOpsChannelTests(unittest.TestCase):
    def setUp(self):
        self.client = scripted_client()
        self.ops = DazSceneOps(DazScene(self.client))

    def joined(self) -> str:
        return "\n".join(self.client.scripts)

    def test_camera_with_aim_positions_then_aims(self):
        self.ops.set_channels("Cam", "camera", {"transform": {"position": (1.0, 2.0, 3.0),
                                                              "aim": (0.0, 1.0, 0.0), "rotation": None}})
        s = self.client.scripts
        self.assertIn("setWSPos(new DzVec3(1.0, 2.0, 3.0))", s[0])
        self.assertIn("aimAt(new DzVec3(0.0, 1.0, 0.0))", s[1])
        self.assertNotIn("getXRotControl().setValue", self.joined())

    def test_camera_without_aim_sets_rotation(self):
        self.ops.set_channels("Cam", "camera", {"transform": {"position": (1.0, 2.0, 3.0),
                                                              "aim": None, "rotation": (5.0, 6.0, 7.0)}})
        self.assertIn("getXRotControl().setValue(5.0)", self.joined())
        self.assertNotIn("aimAt", self.joined())

    def test_observed_transform_sets_position_and_rotation(self):
        self.ops.set_channels("Spot", "light", {"transform": {"position": [1.0, 2.0, 3.0],
                                                              "rotation": [10.0, 20.0, 30.0]}})
        self.assertIn("setWSPos(new DzVec3(1.0, 2.0, 3.0))", self.joined())
        self.assertIn("getZRotControl().setValue(30.0)", self.joined())

    def test_optics_skip_none(self):
        self.ops.set_channels("Cam", "camera", {"optics": {"focal_length": 85.0, "depth_of_field": True,
                                                           "focal_distance": None}})
        self.assertIn("focalLength = 85.0", self.joined())
        self.assertIn("Depth of Field", self.joined())
        self.assertNotIn("focalDistance", self.joined())

    def test_output_sets_intensity_and_color(self):
        self.ops.set_channels("Spot", "light", {"output": {"intensity": 2.0, "color": [10, 20, 30]}})
        self.assertIn('"Intensity"', self.joined())
        self.assertIn("new Color(10, 20, 30)", self.joined())

    def test_pose_snapshot_uses_apply_full(self):
        snap = {"figure": "Genesis 9", "bones": {"lForeArm": [0.0, 0.0, 10.0]}, "morphs": {}, "props": {}}
        with patch.object(DazPose, "apply_full", autospec=True) as apply_full:
            self.ops.set_channels("Genesis 9", "actor", {"pose": {"snapshot": snap}})
        pose, skeleton = apply_full.call_args[0]
        self.assertEqual(pose.to_dict(), snap)
        self.assertEqual(skeleton._identifier.value, "Genesis 9")

    def test_pose_path_uses_apply_pose_and_none_is_noop(self):
        with patch("dazpy._recipe_ops.apply_pose") as apply_pose:
            self.ops.set_channels("Genesis 9", "actor", {"pose": {"pose_path": "C:/p.json"}})
            self.ops.set_channels("Genesis 9", "actor", {"pose": {"pose_path": None}})
        self.assertEqual(apply_pose.call_count, 1)
        self.assertEqual(apply_pose.call_args[0][1], "C:/p.json")

    def test_pose_preset_resolved_selected_and_merged(self):
        self.client = scripted_client(("findFile", "C:/Lib/Poses/Sit.duf"), ("openFile", True))
        self.ops = DazSceneOps(DazScene(self.client))
        with patch("dazpy._recipe_ops.apply_pose") as apply_pose:
            self.ops.set_channels("Genesis 9", "actor", {"pose": {"pose_path": "/Poses/Sit.DUF"}})
        apply_pose.assert_not_called()
        find, open_ = self.client.scripts
        self.assertIn(json.dumps("/Poses/Sit.DUF"), find)
        self.assertIn('Scene.setPrimarySelection(_node)', open_)
        self.assertIn('openFile("C:/Lib/Poses/Sit.duf", true)', open_)
        self.assertLess(open_.index("setPrimarySelection"), open_.index("openFile"))

    def test_missing_pose_preset_raises_without_opening(self):
        self.client = scripted_client(("findFile", ""))
        self.ops = DazSceneOps(DazScene(self.client))
        with patch("dazpy._recipe_ops.os.path.isfile", return_value=False):
            with self.assertRaises(DazError):
                self.ops.set_channels("G9", "actor", {"pose": {"pose_path": "/Poses/Missing.dsf"}})
        self.assertFalse(any("openFile" in s for s in self.client.scripts))

    def test_unsupported_pose_extension_raises(self):
        with self.assertRaisesRegex(DazError, r"\.duf.*\.json"):
            self.ops.set_channels("G9", "actor", {"pose": {"pose_path": "C:/p.bvh"}})
        self.assertEqual(self.client.scripts, [])

    def test_desired_environment_goes_through_apply_hdri_environment(self):
        env = d_environment().channels["environment"]
        with patch("dazpy._recipe_ops.apply_hdri_environment") as apply_env:
            self.ops.set_environment(env)
        self.assertEqual(apply_env.call_args[0][1],
                         HDRIEnvironment(image_path="/hdri/sky.hdr", intensity=1.0, rotation_deg=0.0,
                                         mode="dome_and_scene", draw_dome=True))

    def test_observed_environment_writes_mode_as_raw_int(self):
        with patch("dazpy._render.os.path.isfile", return_value=True),                 patch("dazpy._render.os.path.isabs", return_value=True):
            self.ops.set_environment({"intensity": 0.5, "rotation_deg": 90.0, "mode": 2,
                                      "draw_dome": False, "image_path": "C:/old.hdr"})
        mode = [s for s in self.client.scripts if '"Environment Mode"' in s]
        self.assertEqual(len(mode), 1)
        self.assertIn("setValue(2)", mode[0])
        self.assertNotIn("setValueFromString", self.joined())
        self.assertIn('setMap("C:/old.hdr")', self.joined())

    def test_unparent_reparent_delete_scripts(self):
        self.ops.unparent(["Shirt"])
        self.assertIn("removeNodeChild(_n, true)", self.client.scripts[-1])
        self.assertIn(json.dumps(["Shirt"]), self.client.scripts[-1])
        self.ops.reparent(["Shirt"], "Genesis 9")
        self.assertIn("addNodeChild(_n, true)", self.client.scripts[-1])
        self.ops.delete("Genesis 9")
        self.assertIn("Scene.removeNode", self.client.scripts[-1])

    def test_record_and_manifest_scripts(self):
        r = EntityRecord(RID, "props.ball", 1, {}, {})
        m = Manifest(RID, ("props.ball",), None)
        self.ops.write_record("Ball", r)
        self.ops.remove_record("Ball")
        self.ops.write_manifest(m)
        self.assertEqual(self.client.scripts, [write_record_script("Ball", r), remove_record_script("Ball"),
                                               write_manifest_script(m)])


class DazSceneOpsObserveTests(unittest.TestCase):
    INFO = {"is_camera": True, "is_light": False, "position": [1.0, 2.0, 3.0],
            "rotation": [0.0, 90.0, 0.0], "optics": {"focal_length": 50.0, "depth_of_field": False,
                                                    "focal_distance": 300.0}, "output": None}

    def test_observe_camera(self):
        ops = DazSceneOps(DazScene(scripted_client(("_observe(_n)", self.INFO))))
        self.assertEqual(ops.observe("Cam", "camera"),
                         {"transform": {"position": [1.0, 2.0, 3.0], "rotation": [0.0, 90.0, 0.0]},
                          "optics": self.INFO["optics"]})

    def test_observe_actor_captures_pose(self):
        info = dict(self.INFO, is_camera=False, optics=None)
        pose = DazPose("Genesis 9", {"hip": [1.0, 0.0, 0.0]}, {}, {})
        ops = DazSceneOps(DazScene(scripted_client(("_observe(_n)", info))))
        with patch.object(DazPose, "capture", return_value=pose):
            obs = ops.observe("Genesis 9", "actor")
        self.assertEqual(obs["pose"], {"snapshot": pose.to_dict()})

    def test_observe_missing_node_raises(self):
        ops = DazSceneOps(DazScene(scripted_client(("_observe(_n)", None))))
        with self.assertRaises(DazError):
            ops.observe("Gone", "prop")

    def test_observe_environment(self):
        env = {"intensity": 1.0, "rotation_deg": 0.0, "mode": 0, "draw_dome": True, "image_path": ""}
        ops = DazSceneOps(DazScene(scripted_client(("_environment()", env))))
        self.assertEqual(ops.observe_environment(), env)


if __name__ == "__main__":
    unittest.main()
