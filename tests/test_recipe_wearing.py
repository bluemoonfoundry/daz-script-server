import dataclasses
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dazpy._asset_ref import AssetRef
from dazpy._recipe_fitted import FigureInfo, FittedItem
from dazpy._recipe_model import ActorSpec, SceneRecipe, TypeSelector, WearingEntry
from dazpy._recipe_store import LiveEntity, LiveState
from dazpy._recipe_wearing import TakeOver, plan_wearing
from recipe_fakes import rec

BASE = AssetRef(path="/People/Genesis 9/Genesis 9.duf")


def item(name, type_="Follower/Hair", label=None, source="/data/x.dsf", record=None, foreign=()):
    return FittedItem(name, label or name, type_, source, record, tuple(foreign))


def fig(label, items=(), name=None):
    return FigureInfo(name or label, label, None, None, tuple(items))


def recipe(*entries, node="Abby", asset=BASE, actor="abby"):
    return SceneRecipe(2, "r1", actors={actor: ActorSpec(asset=asset, node=node, wearing=tuple(entries))})


def live(**ents):
    return LiveState(None, ents, None)


def owned(record, node_name="Abby", group_nodes=()):
    return LiveEntity("actors.abby", node_name, "actor", record, {}, (), group_nodes=group_nodes)


def replace(target, key="k", if_missing="error"):
    return WearingEntry("replace", key, AssetRef(path="/x"), target, if_missing)


def remove(target, if_missing="error"):
    return WearingEntry("remove", None, None, target, if_missing)


HAIR = TypeSelector("hair")


class WearingTests(unittest.TestCase):
    def test_take_over_single_label(self):
        p = plan_wearing(recipe(), {"Abby": [fig("Abby", name="Genesis9")]}, live())
        self.assertEqual(p.take_overs, (TakeOver("actors.abby", "Genesis9"),))
        self.assertEqual(p.errors, ())

    def test_already_owned_no_take_over(self):
        r = rec("r1", "actors.abby")
        p = plan_wearing(recipe(), {"Abby": [fig("Abby")]}, live(**{"actors.abby": owned(r)}))
        self.assertEqual(p.take_overs, ())

    def test_ambiguous_label(self):
        p = plan_wearing(recipe(), {"Abby": [fig("Abby", name="G1"), fig("Abby", name="G2")]}, live())
        self.assertEqual([e.code for e in p.errors], ["ambiguous_node"])
        self.assertEqual(p.errors[0].path, "actors.abby.node")
        self.assertEqual(p.take_overs, ())

    def test_label_case_mismatch_creates_and_warns(self):
        p = plan_wearing(recipe(node="abby"), {"Abby": [fig("Abby")]}, live())
        self.assertEqual(p.take_overs, ())
        self.assertEqual(p.errors, ())
        self.assertEqual([w.code for w in p.warnings], ["similar_node_label"])
        self.assertIn("Abby", p.warnings[0].message)

    def test_label_missing_without_asset_errors(self):
        p = plan_wearing(recipe(asset=None), {"Abby": []}, live())
        self.assertEqual([e.code for e in p.errors], ["node_not_found"])

    def test_replace_by_type_matches_all_hair(self):
        f = fig("Abby", [item("H1"), item("H2"), item("Shoes", "Follower/Shoes")])
        p = plan_wearing(recipe(replace(HAIR)), {"Abby": [f]}, live())
        self.assertEqual(len(p.unfits), 1)
        self.assertEqual(p.unfits[0].node_names, ("H1", "H2"))
        self.assertEqual(p.unfits[0].entry, "k")
        self.assertEqual(p.unfits[0].removed[0],
                         {"label": "H1", "type": "Follower/Hair", "source_path": "/data/x.dsf"})

    def test_replace_by_label_exact(self):
        f = fig("Abby", [item("H1", label="Bob"), item("H2", label="bob")])
        p = plan_wearing(recipe(replace("Bob")), {"Abby": [f]}, live())
        self.assertEqual(p.unfits[0].node_names, ("H1",))

    def test_owned_items_never_selected(self):
        mine = item("MyHair", record=rec("r1", "actors.abby.wearing.hair"))
        other = item("TheirHair", record=rec("other", "actors.x.wearing.h"))
        p = plan_wearing(recipe(replace(HAIR)), {"Abby": [fig("Abby", [mine, other])]}, live())
        self.assertEqual(p.unfits[0].node_names, ("TheirHair",))

    def test_replace_missing_errors(self):
        p = plan_wearing(recipe(replace(HAIR)), {"Abby": [fig("Abby")]}, live())
        self.assertEqual([e.code for e in p.errors], ["replace_target_missing"])
        self.assertEqual(p.errors[0].path, "actors.abby.wearing.k")
        self.assertEqual(p.unfits, ())

    def test_if_missing_add(self):
        p = plan_wearing(recipe(replace(HAIR, if_missing="add")), {"Abby": [fig("Abby")]}, live())
        self.assertEqual((p.errors, p.unfits), ((), ()))

    def test_remove_missing_errors_and_ignore(self):
        p = plan_wearing(recipe(remove(HAIR)), {"Abby": [fig("Abby")]}, live())
        self.assertEqual([(e.code, e.path) for e in p.errors],
                         [("remove_target_missing", "actors.abby.wearing.remove.0")])
        p = plan_wearing(recipe(remove(HAIR, if_missing="ignore")), {"Abby": [fig("Abby")]}, live())
        self.assertEqual((p.errors, p.unfits), ((), ()))

    def test_replace_on_created_actor(self):
        p = plan_wearing(recipe(replace(HAIR)), {"Abby": []}, live())
        self.assertEqual([e.code for e in p.errors], ["replace_target_missing"])
        p = plan_wearing(recipe(replace(HAIR, if_missing="add")), {"Abby": []}, live())
        self.assertEqual(p.errors, ())

    def test_list_order_simulation(self):
        f = fig("Abby", [item("HatA", "Follower/Hat")])
        p = plan_wearing(recipe(remove("HatA"), replace(TypeSelector("hat"))), {"Abby": [f]}, live())
        self.assertEqual(len(p.unfits), 1)
        self.assertEqual([e.code for e in p.errors], ["replace_target_missing"])
        self.assertEqual(p.errors[0].path, "actors.abby.wearing.k")

    def test_done_entries_skipped(self):
        r = dataclasses.replace(rec("r1", "actors.abby"), done=({"entry": "k", "op": "replace", "removed": []},))
        f = fig("Abby", [item("NewHair")])
        p = plan_wearing(recipe(replace(HAIR)), {"Abby": [f]}, live(**{"actors.abby": owned(r)}))
        self.assertEqual((p.unfits, p.errors), ((), ()))

    def test_done_remove_entry_skipped(self):
        r = dataclasses.replace(rec("r1", "actors.abby"), done=({"entry": "remove.0"},))
        p = plan_wearing(recipe(remove(HAIR)), {"Abby": [fig("Abby")]}, live(**{"actors.abby": owned(r)}))
        self.assertEqual(p.errors, ())

    def test_foreign_children_conflict(self):
        f = fig("Abby", [item("H1", foreign=("Cap",))])
        p = plan_wearing(recipe(replace(HAIR)), {"Abby": [f]}, live())
        self.assertEqual(len(p.conflicts), 1)
        c = p.conflicts[0]
        self.assertEqual((c.path, c.kind), ("actors.abby.wearing.k", "has_foreign_children"))
        self.assertEqual(c.live, ["Cap"])
        self.assertEqual(c.base, {"node": "H1"})  # the item to unparent from

    def test_own_group_members_are_not_foreign(self):
        r = rec("r1", "actors.abby")
        f = fig("Abby", [item("H1", foreign=("Mine",))])
        lv = live(**{"actors.abby": owned(r, group_nodes=("Abby", "Mine"))})
        p = plan_wearing(recipe(replace(HAIR)), {"Abby": [f]}, lv)
        self.assertEqual(p.conflicts, ())

    def test_unrestorable_warning(self):
        f = fig("Abby", [item("H1", source=None)])
        p = plan_wearing(recipe(remove(HAIR)), {"Abby": [f]}, live())
        self.assertEqual([w.code for w in p.warnings], ["unrestorable_removal"])
        self.assertEqual(len(p.unfits), 1)

    def test_take_over_asset_changed(self):
        old = {"path": "/People/Genesis 8/Genesis 8.duf"}
        r = dataclasses.replace(rec("r1", "actors.abby"), adopted_from_scene=True, source={"requested": old})
        p = plan_wearing(recipe(), {"Abby": [fig("Abby")]}, live(**{"actors.abby": owned(r)}))
        self.assertEqual([e.code for e in p.errors], ["take_over_asset_changed"])

    def test_take_over_asset_unchanged_or_unrecorded(self):
        same = dataclasses.replace(rec("r1", "actors.abby"), adopted_from_scene=True,
                                   source={"requested": BASE.to_dict()})
        none = dataclasses.replace(rec("r1", "actors.abby"), adopted_from_scene=True)
        created = dataclasses.replace(rec("r1", "actors.abby"), source={"requested": {"path": "/z"}})
        for r in (same, none, created):
            p = plan_wearing(recipe(), {"Abby": [fig("Abby")]}, live(**{"actors.abby": owned(r)}))
            self.assertEqual(p.errors, ())

    def test_ignore_and_add_fallback_mark_done(self):
        r = recipe(remove(HAIR, if_missing="ignore"), replace(HAIR, key="k2", if_missing="add"))
        p = plan_wearing(r, {"Abby": [fig("Abby")]}, live())
        self.assertEqual(p.done_entries, (("actors.abby", "remove.0"), ("actors.abby", "k2")))
        self.assertEqual((p.unfits, p.errors), ((), ()))

    def test_done_fallback_blocks_later_hand_loaded_match(self):
        rc = dataclasses.replace(rec("r1", "actors.abby"), done=({"entry": "k2"},))
        r = recipe(replace(HAIR, key="k2", if_missing="add"))
        p = plan_wearing(r, {"Abby": [fig("Abby", [item("NewHair")])]}, live(**{"actors.abby": owned(rc)}))
        self.assertEqual((p.unfits, p.errors, p.done_entries), ((), (), ()))

    def test_unresolved_node_skips_entry_errors(self):
        r = recipe(replace(HAIR))
        p = plan_wearing(r, {"Abby": [fig("Abby", name="G1"), fig("Abby", name="G2")]}, live())
        self.assertEqual([e.code for e in p.errors], ["ambiguous_node"])
        p = plan_wearing(recipe(replace(HAIR), asset=None), {"Abby": []}, live())
        self.assertEqual([e.code for e in p.errors], ["node_not_found"])

    def test_scene_labels_drive_similar_warning(self):
        p = plan_wearing(recipe(node="abby"), {"abby": []}, live(), scene_labels=["Abby", "Other"])
        self.assertEqual([w.code for w in p.warnings], ["similar_node_label"])
        self.assertIn("Abby", p.warnings[0].message)

    def test_owned_actor_figure_missing_skips_entries(self):
        r = rec("r1", "actors.abby")
        p = plan_wearing(recipe(replace(HAIR)), {}, live(**{"actors.abby": owned(r)}))
        self.assertEqual((p.errors, p.unfits, p.warnings), ((), (), ()))


if __name__ == "__main__":
    unittest.main()
