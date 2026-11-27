"""Unit tests for dazpy._recipe_diff (pure three-way diff + conflict policy)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dazpy._recipe_desired import DesiredEntity
from dazpy._recipe_diff import Conflict, RecipePlan, Step, diff
from dazpy._recipe_store import EntityRecord, LiveEntity, LiveState
from recipe_fakes import (ENV_PATH, d_actor, d_camera, d_environment, d_light, d_prop, ds,
                          live_matching, live_tweaked, live_with_children, live_with_duplicate,
                          live_without, with_observed)

ANNA = d_actor("anna", position=(0.0, 0.0, 0.0), pose_path="/poses/stand.duf")
CU = d_camera("cu")
KEY = d_light("key")
ENV = d_environment()

D = ds(ANNA, CU, KEY)
D_cam_moved = ds(ANNA, d_camera("cu", position=(50.0, 150.0, 300.0)), KEY)
D_cam_moved_and_light_changed = ds(ANNA, d_camera("cu", position=(50.0, 150.0, 300.0)),
                                   d_light("key", intensity=2.0))
D_without_light_plus_new_cam = ds(ANNA, CU, d_camera("wide", position=(0.0, 150.0, 800.0)))
D_without_actor = ds(CU, KEY)


def ops(plan: RecipePlan) -> list:
    return [(s.op, s.path) for s in plan.steps]


class ThreeWayRowTests(unittest.TestCase):
    """One test per spec §5.2 row."""

    def test_unchanged_is_noop(self):
        p = diff(D, live_matching(D))
        self.assertEqual(p.steps, ())
        self.assertEqual((p.conflicts, p.warnings, p.blocked), ((), (), False))

    def test_recipe_change_only_modifies_that_channel(self):
        p = diff(D_cam_moved, live_matching(D))
        self.assertEqual([(s.op, s.path, list(s.channels)) for s in p.steps],
                         [("modify", "cameras.cu", ["transform"])])
        self.assertEqual(p.steps[0].channels["transform"], D_cam_moved["cameras.cu"].channels["transform"])
        self.assertEqual(p.steps[0].node_name, "r1:cu")

    def test_modify_steps_carry_prior_observed_values(self):
        s = diff(D_cam_moved, live_matching(D)).steps[0]
        self.assertEqual(s.prior["transform"], live_matching(D).entities["cameras.cu"].observed["transform"])
        self.assertEqual(list(s.prior), ["transform"])

    def test_hand_tweak_kept_with_warning(self):
        p = diff(D, live_tweaked(D, "cameras.cu", "transform"))
        self.assertEqual(p.steps, ())
        self.assertEqual(p.warnings[0].code, "hand_tweak_kept")
        self.assertEqual(p.warnings[0].path, "cameras.cu.transform")
        self.assertEqual(p.conflicts, ())

    def test_both_changed_is_conflict_and_ask_blocks_everything(self):
        p = diff(D_cam_moved_and_light_changed, live_tweaked(D, "cameras.cu", "transform"))
        self.assertTrue(p.blocked)
        self.assertEqual(p.steps, ())
        self.assertEqual((p.conflicts[0].path, p.conflicts[0].kind), ("cameras.cu.transform", "modified"))
        c = p.conflicts[0]
        self.assertEqual(c.desired, D_cam_moved["cameras.cu"].channels["transform"])
        self.assertEqual(c.base, D["cameras.cu"].channels["transform"])
        self.assertEqual(c.live["position"][0], 25.0)

    def test_live_already_equals_desired_is_noop_not_conflict(self):
        moved = ds(ANNA, CU, d_light("key", position=(130.0, 200.0, 100.0)))
        live = with_observed(live_matching(D), "lighting.lights.key", "transform",
                             {"position": [130.0, 200.0, 100.0], "rotation": [-30.0, 45.0, 0.0]})
        p = diff(moved, live)
        self.assertEqual(p.conflicts, ())
        self.assertFalse(p.blocked)
        # the record catches up; nothing is written to Studio
        self.assertEqual(ops(p), [("adopt", "lighting.lights.key")])
        self.assertEqual(p.steps[0].channels, {"transform": moved["lighting.lights.key"].channels["transform"]})
        self.assertEqual(p.steps[0].prior, {"transform": live.entities["lighting.lights.key"].observed["transform"]})

    def test_live_equals_desired_shortcut_never_applies_to_camera_transform(self):
        moved = ds(ANNA, d_camera("cu", position=(50.0, 150.0, 300.0)), KEY)
        live = with_observed(live_matching(D), "cameras.cu", "transform",
                             {"position": [50.0, 150.0, 300.0], "rotation": [0.0, 0.0, 0.0]})
        p = diff(moved, live)
        self.assertEqual([(c.path, c.kind) for c in p.conflicts], [("cameras.cu.transform", "modified")])

    def test_new_entity_is_created(self):
        p = diff(ds(ANNA, CU, KEY, d_prop("ball")), live_matching(D))
        self.assertEqual(ops(p), [("create", "props.ball")])
        self.assertEqual(p.steps[0].channels, d_prop("ball").channels)
        self.assertIsNone(p.steps[0].node_name)
        self.assertIsNone(p.steps[0].prior)

    def test_first_apply_with_no_manifest_creates_everything(self):
        p = diff(ds(ANNA, CU, ENV), LiveState(None, {}, None))
        self.assertEqual(ops(p), [("create", "actors.anna"), ("create", "cameras.cu"),
                                  ("set_environment", ENV_PATH)])

    def test_removed_untouched_entity_is_deleted_last(self):
        p = diff(D_without_light_plus_new_cam, live_matching(D))
        self.assertEqual(p.steps[-1].op, "delete")
        self.assertEqual(p.steps[0].op, "create")
        self.assertEqual(ops(p), [("create", "cameras.wide"), ("delete", "lighting.lights.key")])
        self.assertEqual(p.steps[-1].node_name, "r1:key")

    def test_removed_tweaked_entity_is_conflict(self):
        p = diff(ds(ANNA, CU), live_tweaked(D, "lighting.lights.key", "output"))
        self.assertTrue(p.blocked)
        self.assertEqual([(c.path, c.kind) for c in p.conflicts],
                         [("lighting.lights.key", "removed_from_recipe")])
        self.assertIsNone(p.conflicts[0].desired)

    def test_hand_deleted_entity_is_conflict(self):
        p = diff(D, live_without(live_matching(D), "cameras.cu"))
        self.assertTrue(p.blocked)
        self.assertEqual([(c.path, c.kind) for c in p.conflicts], [("cameras.cu", "deleted_in_scene")])

    def test_foreign_children_on_removed_entity_is_conflict(self):
        p = diff(D_without_actor, live_with_children(D, "actors.anna", ("Shirt", "Hat")))
        self.assertTrue(p.blocked)
        self.assertEqual([(c.path, c.kind) for c in p.conflicts], [("actors.anna", "has_foreign_children")])
        self.assertEqual(p.conflicts[0].live["foreign_children"], ["Shirt", "Hat"])

    def test_foreign_children_on_kept_entity_is_not_a_conflict(self):
        p = diff(D, live_with_children(D, "actors.anna", ("Shirt",)))
        self.assertEqual((p.steps, p.conflicts), ((), ()))


class PolicyTests(unittest.TestCase):
    def test_recipe_wins_resolves_and_reports_overwritten(self):
        p = diff(D_cam_moved, live_tweaked(D, "cameras.cu", "transform"), on_conflict="recipe_wins")
        self.assertFalse(p.blocked)
        self.assertEqual(p.overwritten, ("cameras.cu.transform",))
        self.assertEqual(ops(p), [("modify", "cameras.cu")])
        self.assertEqual(p.steps[0].prior["transform"]["position"][0], 25.0)
        self.assertEqual(len(p.conflicts), 1)  # still reported

    def test_scene_wins_emits_adopt_step(self):
        live = live_tweaked(D, "cameras.cu", "transform")
        p = diff(D_cam_moved, live, on_conflict="scene_wins")
        self.assertEqual([s.op for s in p.steps], ["adopt"])
        self.assertEqual(p.kept, ("cameras.cu.transform",))
        s = p.steps[0]
        self.assertEqual(s.channels, {"transform": D_cam_moved["cameras.cu"].channels["transform"]})
        self.assertEqual(s.prior, {"transform": live.entities["cameras.cu"].observed["transform"]})

    def test_resolutions_override_policy_per_path_and_ask_still_blocks_uncovered(self):
        moved = ds(ANNA, d_camera("cu", position=(50.0, 150.0, 300.0)), d_light("key", intensity=3.0))
        live = live_tweaked(D, "lighting.lights.key", "output",
                            live=live_tweaked(D, "cameras.cu", "transform"))
        partial = diff(moved, live, resolutions={"cameras.cu.transform": "recipe"})
        self.assertTrue(partial.blocked)
        self.assertEqual(partial.steps, ())
        self.assertEqual(len(partial.conflicts), 2)

        full = diff(moved, live, resolutions={"cameras.cu.transform": "recipe",
                                              "lighting.lights.key.output": "scene"})
        self.assertFalse(full.blocked)
        self.assertEqual(ops(full), [("modify", "cameras.cu"), ("adopt", "lighting.lights.key")])
        self.assertEqual((full.overwritten, full.kept),
                         (("cameras.cu.transform",), ("lighting.lights.key.output",)))

        # resolutions beat on_conflict for the paths they name
        mixed = diff(moved, live, on_conflict="scene_wins", resolutions={"cameras.cu.transform": "recipe"})
        self.assertEqual(ops(mixed), [("modify", "cameras.cu"), ("adopt", "lighting.lights.key")])

    def test_recipe_wins_on_removed_tweaked_entity_deletes(self):
        p = diff(ds(ANNA, CU), live_tweaked(D, "lighting.lights.key", "output"), on_conflict="recipe_wins")
        self.assertEqual(ops(p), [("delete", "lighting.lights.key")])
        self.assertEqual(p.overwritten, ("lighting.lights.key",))

    def test_scene_wins_on_removed_tweaked_entity_releases_node_with_warning(self):
        p = diff(ds(ANNA, CU), live_tweaked(D, "lighting.lights.key", "output"), on_conflict="scene_wins")
        self.assertEqual(ops(p), [("release", "lighting.lights.key")])
        self.assertEqual(p.steps[0].node_name, "r1:key")
        self.assertEqual(p.kept, ("lighting.lights.key",))
        self.assertEqual([(w.code, w.path) for w in p.warnings],
                         [("removed_entity_kept", "lighting.lights.key")])

    def test_recipe_wins_on_foreign_children_unparents_before_delete(self):
        p = diff(D_without_actor, live_with_children(D), on_conflict="recipe_wins")
        ops_ = [s.op for s in p.steps]
        self.assertLess(ops_.index("unparent"), ops_.index("delete"))
        unparent = p.steps[ops_.index("unparent")]
        self.assertEqual(unparent.channels, {"children": {"names": ["Shirt"]}})
        self.assertEqual(unparent.node_name, "r1:anna")

    def test_scene_wins_on_foreign_children_releases_node_with_warning(self):
        p = diff(D_without_actor, live_with_children(D), on_conflict="scene_wins")
        self.assertEqual(ops(p), [("release", "actors.anna")])
        self.assertEqual([w.code for w in p.warnings], ["removed_entity_kept"])

    def test_deleted_in_scene_recipe_wins_recreates_scene_wins_drops_from_manifest(self):
        live = live_without(live_matching(D), "cameras.cu")
        rw = diff(D, live, on_conflict="recipe_wins")
        self.assertEqual(ops(rw), [("create", "cameras.cu")])
        self.assertEqual(rw.tombstones, ())
        self.assertEqual(rw.overwritten, ("cameras.cu",))

        sw = diff(D, live, on_conflict="scene_wins")
        self.assertEqual(sw.steps, ())
        self.assertEqual(sw.tombstones, ("cameras.cu",))
        self.assertEqual(sw.kept, ("cameras.cu",))

    def test_accepted_hand_deletion_stays_accepted_on_later_apply(self):
        live = live_without(live_matching(D, deleted=("cameras.cu",)), "cameras.cu")
        p = diff(D, live)
        self.assertFalse(p.blocked)
        self.assertEqual((p.steps, p.conflicts), ((), ()))
        self.assertEqual(p.tombstones, ("cameras.cu",))
        self.assertEqual([(w.code, w.path) for w in p.warnings], [("hand_deleted_kept", "cameras.cu")])

    def test_tombstone_recreated_under_recipe_wins_or_recipe_resolution(self):
        live = live_without(live_matching(D, deleted=("cameras.cu",)), "cameras.cu")
        for kwargs in ({"on_conflict": "recipe_wins"}, {"resolutions": {"cameras.cu": "recipe"}}):
            p = diff(D, live, **kwargs)
            self.assertEqual(ops(p), [("create", "cameras.cu")])
            self.assertEqual(p.tombstones, ())

    def test_tombstone_removed_from_recipe_is_dropped_silently(self):
        live = live_without(live_matching(D, deleted=("cameras.cu",)), "cameras.cu")
        p = diff(ds(ANNA, KEY), live)
        self.assertEqual((p.steps, p.conflicts, p.warnings, p.tombstones), ((), (), (), ()))

    def test_blocked_plan_is_all_or_nothing_even_with_safe_changes(self):
        p = diff(ds(ANNA, d_camera("cu", position=(50.0, 150.0, 300.0)), KEY, d_prop("ball")),
                 live_tweaked(D, "cameras.cu", "transform"))
        self.assertTrue(p.blocked)
        self.assertEqual((p.steps, p.overwritten, p.kept), ((), (), ()))


class ChannelGranularityTests(unittest.TestCase):
    def test_modified_and_tweaked_channels_split(self):
        moved = ds(ANNA, d_camera("cu", focal_length=85.0), KEY)
        p = diff(moved, live_tweaked(D, "cameras.cu", "transform"))
        self.assertEqual([(s.op, s.path, list(s.channels)) for s in p.steps],
                         [("modify", "cameras.cu", ["optics"])])
        self.assertEqual(list(p.steps[0].prior), ["optics"])
        self.assertEqual([(w.code, w.path) for w in p.warnings],
                         [("hand_tweak_kept", "cameras.cu.transform")])

    def test_step_order_follows_spec(self):
        D0 = ds(ANNA, CU, KEY, ENV)
        live = live_with_children(D0, "actors.anna", ("Shirt",))
        live = live_tweaked(D0, "lighting.lights.key", "output", live=live)
        D1 = ds(d_camera("cu", position=(10.0, 150.0, 300.0)), d_light("key", intensity=4.0),
                d_environment(intensity=2.0), d_prop("ball"))
        p = diff(D1, live, on_conflict="scene_wins", resolutions={"actors.anna": "recipe"})
        self.assertEqual([s.op for s in p.steps],
                         ["create", "modify", "set_environment", "adopt", "unparent", "delete"])

    def test_release_runs_with_the_reversible_steps_before_removals(self):
        D0 = ds(ANNA, CU, KEY, d_prop("ball"))
        live = live_with_children(D0, "actors.anna", ("Shirt",))
        live = live_tweaked(D0, "props.ball", "transform", live=live)
        p = diff(ds(CU, KEY), live, resolutions={"actors.anna": "recipe", "props.ball": "scene"})
        self.assertEqual([s.op for s in p.steps], ["release", "unparent", "delete"])


class PoseTests(unittest.TestCase):
    def test_hand_posed_actor_is_tweak(self):
        p = diff(D, live_tweaked(D, "actors.anna", "pose"))
        self.assertEqual([(w.code, w.path) for w in p.warnings], [("hand_tweak_kept", "actors.anna.pose")])

    def test_pose_noise_within_tolerance_is_ignored(self):
        live = live_matching(D)
        snap = dict(live.entities["actors.anna"].observed["pose"]["snapshot"])
        snap["bones"] = {"hip": [0.01, 0.0, 0.0]}
        p = diff(D, with_observed(live, "actors.anna", "pose", {"snapshot": snap}))
        self.assertEqual((p.steps, p.warnings), ((), ()))

    def test_pose_change_on_hand_posed_actor_is_conflict_reporting_drift(self):
        D1 = ds(d_actor("anna", pose_path="/poses/sit.duf"), CU, KEY)
        p = diff(D1, live_tweaked(D, "actors.anna", "pose"))
        self.assertTrue(p.blocked)
        c = p.conflicts[0]
        self.assertEqual((c.path, c.kind), ("actors.anna.pose", "modified"))
        self.assertEqual((c.desired, c.base), ({"pose_path": "/poses/sit.duf"},
                                               {"pose_path": "/poses/stand.duf"}))
        self.assertEqual(len(c.live["drifted"]), 1)
        self.assertIn("rForeArm", c.live["drifted"][0])

    def test_node_transform_props_in_pose_snapshots_are_ignored(self):
        # Records written before C1 still carry the figure's own transform in the
        # snapshot; a moved actor must not read as a hand pose edit.
        live = live_matching(D)
        e = live.entities["actors.anna"]
        old = {"snapshot": dict(e.record.observed["pose"]["snapshot"],
                                props={"XTranslate": 0.0, "YRotate": 10.0, "Scale": 1.0})}
        now = {"snapshot": dict(old["snapshot"], props={"XTranslate": 60.0, "YRotate": 45.0,
                                                        "Scale": 1.0})}
        rec = EntityRecord(e.record.recipe_id, e.path, 1, e.record.desired,
                           dict(e.record.observed, pose=old))
        ents = dict(live.entities)
        ents[e.path] = LiveEntity(e.path, e.node_name, e.kind, rec, dict(e.observed, pose=now), ())
        p = diff(D, LiveState(live.manifest, ents, None))
        self.assertEqual((p.steps, p.warnings), ((), ()))

    def test_pose_change_only_modifies_pose(self):
        D1 = ds(d_actor("anna", pose_path="/poses/sit.duf"), CU, KEY)
        p = diff(D1, live_matching(D))
        self.assertEqual([(s.op, list(s.channels)) for s in p.steps], [("modify", ["pose"])])


class EnvironmentTests(unittest.TestCase):
    D0 = ds(ANNA, ENV)

    def test_environment_change_is_set_environment(self):
        p = diff(ds(ANNA, d_environment(intensity=2.0)), live_matching(self.D0))
        self.assertEqual(ops(p), [("set_environment", ENV_PATH)])
        self.assertIsNone(p.steps[0].node_name)
        self.assertEqual(p.steps[0].prior, {"environment": live_matching(self.D0).environment_observed})

    def test_environment_hand_tweak_kept(self):
        p = diff(self.D0, live_tweaked(self.D0, ENV_PATH, "environment"))
        self.assertEqual([(w.code, w.path) for w in p.warnings],
                         [("hand_tweak_kept", "lighting.environment.environment")])

    def test_environment_both_changed_is_conflict_even_if_equal(self):
        live = live_tweaked(self.D0, ENV_PATH, "environment")  # intensity 1 -> 2
        p = diff(ds(ANNA, d_environment(intensity=2.0)), live)
        self.assertEqual([(c.path, c.kind) for c in p.conflicts],
                         [("lighting.environment.environment", "modified")])
        sw = diff(ds(ANNA, d_environment(intensity=2.0)), live, on_conflict="scene_wins")
        self.assertEqual(ops(sw), [("adopt", ENV_PATH)])
        rw = diff(ds(ANNA, d_environment(intensity=2.0)), live, on_conflict="recipe_wins")
        self.assertEqual(ops(rw), [("set_environment", ENV_PATH)])

    def test_environment_removed_from_recipe_is_left_in_scene(self):
        p = diff(ds(ANNA), live_matching(self.D0))
        self.assertEqual(p.steps, ())
        self.assertEqual([(w.code, w.path) for w in p.warnings], [("environment_left_in_scene", ENV_PATH)])


class ToleranceTests(unittest.TestCase):
    def test_tolerance_ignores_float_noise(self):
        live = with_observed(live_matching(D), "cameras.cu", "transform",
                             {"position": [0.01, 150.01, 299.99], "rotation": [0.0, 0.0, 0.0]})
        p = diff(D, live)
        self.assertEqual((p.steps, p.warnings), ((), ()))

    def test_recipe_change_within_tolerance_is_noop(self):
        p = diff(ds(ANNA, d_camera("cu", position=(0.01, 150.0, 300.0)), KEY), live_matching(D))
        self.assertEqual(p.steps, ())

    def test_custom_tolerance(self):
        live = with_observed(live_matching(D), "cameras.cu", "transform",
                             {"position": [1.0, 150.0, 300.0], "rotation": [0.0, 0.0, 0.0]})
        self.assertEqual(diff(D, live, tolerance=2.0).warnings, ())
        self.assertEqual(len(diff(D, live).warnings), 1)


class DuplicateRecordTests(unittest.TestCase):
    def test_duplicate_blocks_under_ask_with_conflict_and_warning(self):
        p = diff(D, live_with_duplicate(live_matching(D), "cameras.cu"))
        self.assertTrue(p.blocked)
        c = p.conflicts[0]
        self.assertEqual((c.path, c.kind), ("cameras.cu", "duplicate_record"))
        self.assertEqual(c.live, {"nodes": ["r1:cu", "copy"], "element_ids": [None, 2]})
        w = [x for x in p.warnings if x.code == "duplicate_record"]
        self.assertEqual([x.path for x in w], ["cameras.cu"])
        self.assertIn("'copy'", w[0].message)
        self.assertIn("r1:cu", w[0].message)

    def test_duplicate_is_not_resolvable_by_policy_or_resolution(self):
        live = live_with_duplicate(live_matching(D), "cameras.cu")
        self.assertTrue(diff(D_cam_moved, live, resolutions={"cameras.cu": "recipe"}).blocked)
        for policy in ("recipe_wins", "scene_wins"):
            p = diff(D_cam_moved_and_light_changed, live, on_conflict=policy)
            self.assertFalse(p.blocked)
            self.assertEqual(ops(p), [("modify", "lighting.lights.key")])  # cu untouched
            self.assertEqual((p.overwritten, p.kept), ((), ()))
            self.assertEqual([c.kind for c in p.conflicts], ["duplicate_record"])

    def test_duplicated_entity_removed_from_recipe_is_never_deleted(self):
        live = live_with_duplicate(live_matching(D), "lighting.lights.key")
        for policy in ("recipe_wins", "scene_wins"):
            p = diff(ds(ANNA, CU), live, on_conflict=policy)
            self.assertEqual(p.steps, ())
            self.assertEqual([(c.path, c.kind) for c in p.conflicts],
                             [("lighting.lights.key", "duplicate_record")])

    def test_resolution_for_a_duplicate_is_not_unknown(self):
        p = diff(D, live_with_duplicate(live_matching(D), "cameras.cu"),
                 resolutions={"cameras.cu": "recipe"})
        self.assertNotIn("unknown_resolution", [w.code for w in p.warnings])


class ShapeTests(unittest.TestCase):
    def test_types_are_frozen(self):
        s = Step("create", "a", {}, None, None)
        c = Conflict("a", "modified", 1, 2, 3)
        for obj in (s, c, diff(D, live_matching(D))):
            with self.assertRaises(Exception):
                obj.path = "x"  # type: ignore[misc]


class FixRound1Tests(unittest.TestCase):
    """Review fix round 1: resolution validation, unknown keys, tombstones, replace."""

    def test_invalid_resolution_value_raises_naming_path_and_allowed(self):
        live = live_tweaked(D, "cameras.cu", "transform")
        with self.assertRaises(ValueError) as cm:
            diff(D_cam_moved, live, resolutions={"cameras.cu.transform": "Recipe"})
        msg = str(cm.exception)
        for part in ("cameras.cu.transform", "'recipe'", "'scene'"):
            self.assertIn(part, msg)

    def test_invalid_on_conflict_raises(self):
        with self.assertRaises(ValueError) as cm:
            diff(D, live_matching(D), on_conflict="recipe")  # type: ignore[arg-type]
        self.assertIn("recipe_wins", str(cm.exception))

    def test_unknown_resolution_key_warns_without_blocking(self):
        live = live_tweaked(D, "cameras.cu", "transform")
        p = diff(D_cam_moved, live, resolutions={"cameras.cu.transform": "recipe",
                                                 "cameras.cu.transform.position": "scene"})
        self.assertFalse(p.blocked)
        w = [x for x in p.warnings if x.code == "unknown_resolution"]
        self.assertEqual([x.path for x in w], ["cameras.cu.transform.position"])
        self.assertIn("<entity>.<channel>", w[0].message)
        self.assertIn("cameras.cu.transform", w[0].message.split("Conflict paths")[1])

    def test_unknown_resolution_does_not_cover_a_real_conflict(self):
        p = diff(D_cam_moved, live_tweaked(D, "cameras.cu", "transform"),
                 resolutions={"cameras.cu.transform.position": "recipe"})
        self.assertTrue(p.blocked)
        self.assertIn("unknown_resolution", [w.code for w in p.warnings])

    def test_tombstone_resolution_key_is_not_unknown(self):
        live = live_without(live_matching(D, deleted=("cameras.cu",)), "cameras.cu")
        p = diff(D, live, resolutions={"cameras.cu": "scene"})
        self.assertNotIn("unknown_resolution", [w.code for w in p.warnings])

    def test_tombstone_recreate_is_reported_overwritten(self):
        live = live_without(live_matching(D, deleted=("cameras.cu",)), "cameras.cu")
        for kwargs in ({"on_conflict": "recipe_wins"}, {"resolutions": {"cameras.cu": "recipe"}}):
            self.assertEqual(diff(D, live, **kwargs).overwritten, ("cameras.cu",))

    # replace on create-info change
    @staticmethod
    def _new_asset():
        return ds(DesiredEntity(ANNA.path, ANNA.kind, ANNA.label, {"asset_path": "/g8.duf"},
                                ANNA.channels), CU, KEY)

    def test_create_info_change_replaces_untouched_node(self):
        D1 = self._new_asset()
        p = diff(D1, live_matching(D))
        self.assertEqual(ops(p), [("create", "actors.anna"), ("delete", "actors.anna")])
        self.assertEqual(p.steps[0].channels, D1["actors.anna"].channels)
        self.assertEqual(p.steps[1].node_name, "r1:anna")

    def test_light_type_change_replaces(self):
        D1 = ds(ANNA, CU, DesiredEntity(KEY.path, KEY.kind, KEY.label, {"light_type": "point"},
                                        KEY.channels))
        self.assertEqual(ops(diff(D1, live_matching(D))),
                         [("create", "lighting.lights.key"), ("delete", "lighting.lights.key")])

    def test_replace_of_tweaked_node_is_removed_from_recipe_conflict(self):
        D1 = self._new_asset()
        live = live_tweaked(D, "actors.anna", "transform")
        p = diff(D1, live)
        self.assertTrue(p.blocked)
        self.assertEqual([(c.path, c.kind) for c in p.conflicts], [("actors.anna", "removed_from_recipe")])
        self.assertEqual(p.conflicts[0].desired["_create"], {"asset_path": "/g8.duf"})
        rw = diff(D1, live, on_conflict="recipe_wins")
        self.assertEqual(ops(rw), [("create", "actors.anna"), ("delete", "actors.anna")])
        self.assertEqual(rw.overwritten, ("actors.anna",))
        sw = diff(D1, live, on_conflict="scene_wins")
        # kept replace: the old node is released (kept, unowned), the new asset created
        self.assertEqual(ops(sw), [("create", "actors.anna"), ("release", "actors.anna")])
        self.assertEqual(sw.steps[1].node_name, "r1:anna")
        self.assertEqual(sw.kept, ("actors.anna",))
        self.assertEqual([(w.code, w.path) for w in sw.warnings], [("removed_entity_kept", "actors.anna")])

    def test_replace_with_foreign_children(self):
        D1 = self._new_asset()
        live = live_with_children(D, "actors.anna", ("Shirt",))
        p = diff(D1, live)
        self.assertEqual([(c.path, c.kind) for c in p.conflicts], [("actors.anna", "has_foreign_children")])
        rw = diff(D1, live, resolutions={"actors.anna": "recipe"})
        self.assertEqual([s.op for s in rw.steps], ["create", "unparent", "delete"])
        sw = diff(D1, live, on_conflict="scene_wins")
        self.assertEqual([s.op for s in sw.steps], ["create", "release"])
        self.assertEqual([w.code for w in sw.warnings], ["removed_entity_kept"])

    def test_record_without_create_info_is_not_replaced(self):
        D1 = self._new_asset()
        live = live_matching(D)
        e = live.entities["actors.anna"]
        r = e.record
        stripped = {k: v for k, v in r.desired.items() if k != "_create"}
        ents = dict(live.entities)
        ents["actors.anna"] = LiveEntity(e.path, e.node_name, e.kind,
                                         EntityRecord(r.recipe_id, r.path, r.recipe_version,
                                                      stripped, r.observed),
                                         e.observed, e.foreign_children)
        p = diff(D1, LiveState(live.manifest, ents, live.environment_observed))
        self.assertEqual(p.steps, ())


# ── v2: take-over, presets, fitted items, one-shot unfits (Task 12) ──────────

from dazpy._recipe_diff import _STEP_ORDER  # noqa: E402
from dazpy._recipe_wearing import TakeOver, Unfit, WearingPlan  # noqa: E402
from recipe_fakes import d_item, d_taken, live_entity_for, live_of  # noqa: E402

ABBY = d_taken("abby")
HAIR_A = d_item("abby", "hair", "/hair/a.duf")
HAIR_B = d_item("abby", "hair", "/hair/b.duf")
HAND_HAIR = ({"label": "Hand Hair", "type": "Follower/Hair", "source_path": "/hand/hair.duf"},)
UNFIT = Unfit("actors.abby", "hair", ("HandHair",), HAND_HAIR)


def _abby_live(*extra, done=()):
    return live_of(live_entity_for(ABBY, node_name="Abby", adopted=True, done=done), *extra)


class V2DiffTests(unittest.TestCase):
    def test_step_order_removes_last(self):
        self.assertEqual(list(_STEP_ORDER), [
            "create", "take_over", "preset", "fit", "modify", "set_environment", "adopt",
            "release", "unparent", "unfit", "delete"])

    def test_item_create_is_fit(self):
        p = diff(ds(ABBY, HAIR_A), _abby_live())
        self.assertEqual(ops(p), [("fit", HAIR_A.path)])
        self.assertEqual(p.steps[0].channels, {})

    def test_take_over_step_from_wearing_plan(self):
        actor = d_taken("abby", presets=("/m/skin.duf",), pose_path="/p/stand.duf")
        w = WearingPlan(take_overs=(TakeOver("actors.abby", "Genesis 9"),))
        p = diff(ds(actor, HAIR_A), LiveState(None, {}, None), wearing=w)
        self.assertEqual(ops(p), [("take_over", "actors.abby"), ("preset", "actors.abby"),
                                  ("fit", HAIR_A.path)])
        take = p.steps[0]
        self.assertEqual(take.node_name, "Genesis 9")
        self.assertEqual(take.channels, {"pose": {"pose_path": "/p/stand.duf"}})  # no presets
        self.assertEqual(p.steps[1].channels, {"presets": {"paths": ["/m/skin.duf"]}})

    def test_item_asset_change_fits_then_deletes_group(self):
        L = _abby_live(live_entity_for(HAIR_A, group_nodes=("Hair", "Cap")))
        p = diff(ds(ABBY, HAIR_B), L)
        self.assertEqual(ops(p), [("fit", HAIR_A.path), ("delete", HAIR_A.path)])
        self.assertEqual(p.steps[1].channels, {"group": {"names": ["Hair", "Cap"]}})

    def test_item_source_metadata_change_is_not_a_replace(self):
        L = _abby_live(live_entity_for(HAIR_A, group_nodes=("Hair",)))
        p = diff(ds(ABBY, d_item("abby", "hair", "/hair/a.duf", finder="record")), L)
        self.assertEqual(p.steps, ())

    def test_removed_item_deletes_whole_group(self):
        L = _abby_live(live_entity_for(HAIR_A, group_nodes=("Hair", "Cap")))
        p = diff(ds(ABBY), L)
        self.assertEqual(ops(p), [("delete", HAIR_A.path)])
        self.assertEqual(p.steps[0].channels, {"group": {"names": ["Hair", "Cap"]}})

    def test_unfit_steps_from_wearing_plan(self):
        w = WearingPlan(unfits=(UNFIT,), done_entries=(("actors.abby", "remove.1"),))
        p = diff(ds(ABBY, HAIR_A), _abby_live(), wearing=w)
        self.assertEqual(ops(p), [("fit", HAIR_A.path), ("unfit", "actors.abby.wearing.hair")])
        self.assertEqual(p.steps[1].channels["unfit"], {
            "actor": "actors.abby", "entry": "hair", "op": "replace", "names": ["HandHair"],
            "removed": list(HAND_HAIR)})
        self.assertEqual(p.done_log, (
            ("actors.abby", {"entry": "hair", "op": "replace", "removed": list(HAND_HAIR)}),
            ("actors.abby", {"entry": "remove.1", "op": "remove", "removed": []})))

    def test_wearing_conflict_blocks_ask(self):
        c = Conflict("actors.abby.wearing.hair", "has_foreign_children", "type 'hair'",
                     {"node": "HandHair"}, ["Bow"])
        w = WearingPlan(unfits=(UNFIT,), conflicts=(c,))
        p = diff(ds(ABBY, HAIR_A), _abby_live(), wearing=w)
        self.assertTrue(p.blocked)
        self.assertEqual((p.steps, p.done_log), ((), ()))
        self.assertEqual(p.conflicts, (c,))
        # recipe: foreign children are moved out of the item before it is removed
        p = diff(ds(ABBY, HAIR_A), _abby_live(), wearing=w, on_conflict="recipe_wins")
        self.assertEqual(ops(p), [("fit", HAIR_A.path), ("unparent", c.path), ("unfit", c.path)])
        self.assertEqual((p.steps[1].node_name, p.steps[1].channels),
                         ("HandHair", {"children": {"names": ["Bow"]}}))
        # scene: the hand item stays, the entry is not marked done
        p = diff(ds(ABBY, HAIR_A), _abby_live(), wearing=w, on_conflict="scene_wins")
        self.assertEqual(ops(p), [("fit", HAIR_A.path)])
        self.assertEqual(p.done_log, ())

    def test_removed_taken_over_actor_released_not_deleted(self):
        actor = d_taken("abby", pose_path="/p/stand.duf")
        L = live_of(live_entity_for(actor, node_name="Abby", adopted=True),
                    live_entity_for(HAIR_A, group_nodes=("Hair", "Cap")))
        L = live_tweaked(None, "actors.abby", "pose", live=L)  # hand-edited: still never deleted
        p = diff({}, L, on_conflict="recipe_wins")
        self.assertEqual(ops(p), [("release", "actors.abby"), ("release", HAIR_A.path)])
        self.assertEqual(p.steps[1].channels, {"group": {"names": ["Hair", "Cap"]}})
        self.assertNotIn("delete", [s.op for s in p.steps])
        self.assertEqual(p.conflicts, ())

    def test_taken_over_actor_never_replaced(self):
        L = _abby_live()
        changed = d_taken("abby")
        changed.create["asset_path"] = "/other.duf"
        self.assertEqual(diff(ds(changed), L).steps, ())

    def test_group_node_deleted_by_hand_is_deleted_in_scene(self):
        L = _abby_live(live_entity_for(HAIR_A, group_nodes=("Hair",), missing=("Cap",)))
        p = diff(ds(ABBY, HAIR_A), L)
        self.assertTrue(p.blocked)
        self.assertEqual([(c.path, c.kind) for c in p.conflicts],
                         [(HAIR_A.path, "deleted_in_scene")])
        p = diff(ds(ABBY, HAIR_A), L, on_conflict="recipe_wins")
        self.assertEqual(ops(p), [("fit", HAIR_A.path), ("delete", HAIR_A.path)])
        self.assertEqual(p.steps[1].channels, {"group": {"names": ["Hair"]}})
        p = diff(ds(ABBY, HAIR_A), L, on_conflict="scene_wins")
        self.assertEqual(ops(p), [("release", HAIR_A.path)])
        self.assertEqual(p.tombstones, (HAIR_A.path,))

    def test_preset_change_is_preset_step(self):
        old = d_taken("abby", presets=("/m/a.duf",))
        new = d_taken("abby", presets=("/m/a.duf", "/m/b.duf"))
        p = diff(ds(new), live_of(live_entity_for(old, node_name="Abby", adopted=True)))
        self.assertEqual([(s.op, s.channels, s.node_name) for s in p.steps],
                         [("preset", {"presets": {"paths": ["/m/a.duf", "/m/b.duf"]}}, "Abby")])

    def test_preset_dropped_warns(self):
        old = d_taken("abby", presets=("/m/a.duf", "/m/b.duf"))
        new = d_taken("abby", presets=("/m/a.duf",))
        p = diff(ds(new), live_of(live_entity_for(old, node_name="Abby", adopted=True)))
        self.assertEqual([w.code for w in p.warnings], ["preset_dropped"])
        self.assertIn("/m/b.duf", p.warnings[0].message)
        self.assertNotIn("preset", [s.op for s in p.steps])
        # record-only catch-up so the warning does not repeat on every apply
        self.assertEqual([(s.op, s.channels) for s in p.steps],
                         [("adopt", {"presets": {"paths": ["/m/a.duf"]}})])

    def test_unchanged_recipe_zero_steps_after_replace(self):
        done = ({"entry": "hair", "op": "replace", "removed": list(HAND_HAIR)},)
        L = _abby_live(live_entity_for(HAIR_A, group_nodes=("Hair",)), done=done)
        # plan_wearing skips done entries, so the wearing plan is empty
        p = diff(ds(ABBY, HAIR_A), L, wearing=WearingPlan())
        self.assertEqual((p.steps, p.conflicts, p.warnings, p.done_log), ((), (), (), ()))

    def test_item_refit_when_actor_replaced(self):
        anna = d_actor("anna")
        hair = d_item("anna", "hair")
        L = live_of(live_entity_for(anna), live_entity_for(hair, group_nodes=("Hair",)))
        anna2 = DesiredEntity(anna.path, "actor", anna.label, {"asset_path": "/g8.duf"},
                              anna.channels)
        p = diff(ds(anna2, hair), L)
        self.assertEqual(ops(p), [("create", anna.path), ("fit", hair.path),
                                  ("delete", hair.path), ("delete", anna.path)])

    def test_wearing_errors_refused(self):
        from dazpy._recipe_issue import RecipeIssue
        w = WearingPlan(errors=(RecipeIssue("actors.abby.node", "node_not_found", "x"),))
        with self.assertRaises(ValueError):
            diff(ds(ABBY), _abby_live(), wearing=w)


if __name__ == "__main__":
    unittest.main()
