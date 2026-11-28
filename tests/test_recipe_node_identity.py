"""Final review C1: nodes the recipe did not create are addressed by elementID.

Hand-built figures and items share ``getName()`` whenever a file is loaded
twice (spec 15.4: a second Kara Ponytail is again ``Scalp_1085``), so take-over
targets, selector matches and their scripts use the element ID captured at read
time, never a scene-wide name lookup.
"""

import dataclasses
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dazpy._asset_ref import AssetRef
from dazpy._node import NodeIdentifier
from dazpy._recipe_fitted import FigureInfo, FittedItem, figures_script, read_figures
from dazpy._recipe_model import ActorSpec, SceneRecipe, TypeSelector, WearingEntry
from dazpy._recipe_ops import DazSceneOps, _fit_script, _preset_script, _unfit_script
from dazpy._recipe_store import (EntityRecord, LiveState, eid_ref, node_ident, observe_node_script,
                                 read_live, remove_record_script, write_record_script)
from dazpy._recipe_wearing import plan_wearing
from dazpy._result import ExecutionResult
from recipe_fakes import fake_client, node, rec

BASE = AssetRef(path="/People/Genesis 9/Genesis 9.duf")
HAIR = TypeSelector("hair")


def item(name, eid, type_="Follower/Hair", foreign=()):
    return FittedItem(name, "Kara Ponytail", type_, "/data/x.dsf", None, tuple(foreign), str(eid))


def fig(label, eid, items=(), name="Genesis9"):
    return FigureInfo(name, label, None, "/Genesis 9/Base", tuple(items), str(eid))


def recipe(*entries, node="Abby"):
    return SceneRecipe(2, "r1", actors={"abby": ActorSpec(asset=BASE, node=node, wearing=tuple(entries))})


def remove(target):
    return WearingEntry("remove", None, None, target, "error")


class RefTests(unittest.TestCase):
    def test_eid_ref_and_ident(self):
        self.assertEqual(eid_ref("85534"), "elementID:85534")
        self.assertEqual(eid_ref(85534), "elementID:85534")
        self.assertIsNone(eid_ref(None))
        self.assertIsNone(eid_ref("Genesis9"))   # _key fell back to the name: no id
        self.assertEqual(node_ident("elementID:7"), NodeIdentifier("7", kind="element_id"))
        self.assertEqual(node_ident("Genesis9"), NodeIdentifier("Genesis9"))

    def test_name_scripts_are_unchanged_and_ref_scripts_never_find_by_name(self):
        r = EntityRecord("r1", "actors.abby", 2, {}, {})
        for build in (lambda n: write_record_script(n, r), remove_record_script, observe_node_script,
                      lambda n: _preset_script(n, "C:/p.duf")):
            self.assertIn('Scene.findNode("Genesis9")', build("Genesis9"))
            by_id = build("elementID:85534")
            self.assertNotIn("Scene.findNode(", by_id)
            self.assertIn("elementID", by_id)
            self.assertIn('"85534"', by_id)


class PlanTests(unittest.TestCase):
    def two_actors(self, abby_items, kara_items=None):
        kara = fig("Kara", 12, kara_items if kara_items is not None else [item("Scalp_1085", 22)])
        return {"Abby": [fig("Abby", 11, abby_items)], "Kara": [kara]}

    def test_take_over_and_unfit_use_element_ids(self):
        p = plan_wearing(recipe(remove(HAIR)), self.two_actors([item("Scalp_1085", 21)]),
                         LiveState(None, {}, None))
        self.assertEqual(p.take_overs[0].node_name, "elementID:11")
        self.assertEqual(p.unfits[0].node_names, ("elementID:21",))

    def test_duplicate_items_on_one_actor_are_both_removed(self):
        p = plan_wearing(recipe(remove(HAIR)),
                         self.two_actors([item("Scalp_1085", 21), item("Scalp_1085", 23)]),
                         LiveState(None, {}, None))
        self.assertEqual(p.unfits[0].node_names, ("elementID:21", "elementID:23"))

    def test_duplicate_item_conflicts_get_distinct_paths(self):
        p = plan_wearing(recipe(remove(HAIR)),
                         self.two_actors([item("Scalp_1085", 21, foreign=("Bow",)),
                                          item("Scalp_1085", 23, foreign=("Pin",))]),
                         LiveState(None, {}, None))
        self.assertEqual(len({c.path for c in p.conflicts}), 2)
        self.assertEqual({c.base["node"] for c in p.conflicts}, {"elementID:21", "elementID:23"})

    def test_same_label_same_name_figures_are_ambiguous(self):
        figs = {"Abby": [fig("Abby", 11), fig("Abby", 12)]}
        p = plan_wearing(recipe(), figs, LiveState(None, {}, None))
        self.assertEqual([e.code for e in p.errors], ["ambiguous_node"])

    def test_adopted_actor_found_by_its_element_ref(self):
        r = dataclasses.replace(rec("r1", "actors.abby"), adopted_from_scene=True)
        from dazpy._recipe_store import LiveEntity
        ent = LiveEntity("actors.abby", "elementID:11", "actor", r, {}, ())
        figs = {"elementID:11": [fig("Abby", 11, [item("Scalp_1085", 21)])]}
        p = plan_wearing(recipe(remove(HAIR)), figs, LiveState(None, {"actors.abby": ent}, None))
        self.assertEqual(p.unfits[0].node_names, ("elementID:21",))


class FiguresScriptTests(unittest.TestCase):
    def test_figures_are_deduplicated_by_element_id_not_name(self):
        s = figures_script(["Abby"], ["elementID:11"])
        self.assertNotIn("_seen[n.getName()]", s)
        self.assertIn("_seen[_key(n)]", s)
        self.assertIn("element_id: _key(fig)", s)
        self.assertIn("element_id: _key(it)", s)
        self.assertNotIn("Scene.findNode(_owned", s)

    def test_read_figures_keeps_same_named_figures_and_finds_owned_refs(self):
        payload = {"figures": [
            {"name": "Genesis9", "label": "Abby", "element_id": "11", "record": None,
             "compat_base": None, "items": [{"name": "Scalp_1085", "label": "Kara Ponytail",
                                             "element_id": "21", "type": "Follower/Hair",
                                             "source_path": None, "record": None, "foreign": []}]},
            {"name": "Genesis9", "label": "Abby", "element_id": "12", "record": None,
             "compat_base": None, "items": []}]}
        c = mock.Mock()
        c.execute.return_value = ExecutionResult(value=payload)
        out = read_figures(c, ["Abby"], ["elementID:12"])
        self.assertEqual([f.element_id for f in out["Abby"]], ["11", "12"])
        self.assertEqual([f.element_id for f in out["elementID:12"]], ["12"])
        self.assertEqual(out["Abby"][0].items[0].ref, "elementID:21")


class ReadLiveTests(unittest.TestCase):
    def test_adopted_entity_is_addressed_by_element_id(self):
        adopted = dataclasses.replace(rec("r1", "actors.abby"), adopted_from_scene=True)
        nodes = [node("Genesis9", adopted, kind="actor"), node("Ball", rec("r1", "props.ball"))]
        nodes[0]["key"], nodes[1]["key"] = "11", "12"
        live = read_live(fake_client(nodes), "r1")
        self.assertEqual(live.entities["actors.abby"].node_name, "elementID:11")
        self.assertEqual(live.entities["props.ball"].node_name, "Ball")  # created: by name, as v1

    def test_read_script_reports_the_element_key(self):
        from dazpy._recipe_store import _read_script
        self.assertIn("info.key", _read_script("r1", "null"))


class OpsTests(unittest.TestCase):
    def _ops(self, results):
        client = mock.Mock()
        client.execute.side_effect = [SimpleNamespace(value=v) for v in results]
        return DazSceneOps(SimpleNamespace(_client=client)), client

    def test_unfit_with_figure_verifies_each_item_follows_it(self):
        s = _unfit_script(["elementID:21"], "elementID:11")
        self.assertIn("_f != _fig", s)
        self.assertNotIn("Scene.findNode(_names", s)
        ops, client = self._ops([["elementID:21: not fitted to elementID:11"]])
        from dazpy.exceptions import DazError
        with self.assertRaisesRegex(DazError, "not fitted"):
            ops.unfit(["elementID:21"], figure="elementID:11")

    def test_fit_finds_a_taken_over_figure_by_element_id(self):
        s = _fit_script(["Hair"], "elementID:11")
        self.assertNotIn('Scene.findNode("elementID:11")', s)
        self.assertIn('"11"', s)

    def test_set_channels_address_the_node_by_element_id(self):
        ops, client = self._ops([])
        with mock.patch("dazpy._recipe_ops.DazNode") as dn:
            ops.set_channels("elementID:11", "actor", {"transform": {"position": [1, 2, 3]}})
        self.assertEqual(dn.call_args.args[1], NodeIdentifier("11", kind="element_id"))


class ExecutorTests(unittest.TestCase):
    def test_one_shot_unfit_is_checked_against_the_figure(self):
        from dazpy._recipe_apply import execute
        from dazpy._recipe_diff import diff
        from dazpy._recipe_wearing import TakeOver, Unfit, WearingPlan
        from recipe_fakes import FakeOps, d_taken, ds
        hand = ({"label": "Kara Ponytail", "type": "Follower/Hair", "source_path": None},)
        w = WearingPlan(take_overs=(TakeOver("actors.abby", "elementID:11"),),
                        unfits=(Unfit("actors.abby", "remove.type=hair", ("elementID:21",), hand),))
        D = ds(d_taken("abby"))
        L = LiveState(None, {}, None)
        ops = FakeOps()
        r = execute(diff(D, L, wearing=w), D, L, ops, recipe_id="r1", recipe_version=2)
        self.assertTrue(r.applied, r.error)
        self.assertEqual(ops.unfit_figures, [(["elementID:21"], "elementID:11")])
        self.assertIn(("write_record", "elementID:11"), ops.calls)
        self.assertIn(("take_over", "elementID:11"), ops.calls)


if __name__ == "__main__":
    unittest.main()
