"""Unit tests for dazpy._recipe_store (client.execute is mocked)."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dazpy._recipe_store import (EntityRecord, Manifest, read_live, remove_record_script,
                                 write_manifest_script, write_record_script)
from dazpy.exceptions import DazError
from recipe_fakes import fake_client, man, node, rec


class RecordTests(unittest.TestCase):
    def test_record_json_round_trip(self):
        r = EntityRecord("r1", "actors.anna", 1, {"transform": {"position": [1.0, 2.0, 3.0]}},
                         {"pose": {"snapshot": {"bones": {}}}})
        self.assertEqual(EntityRecord.from_json(r.to_json()), r)

    def test_record_native_round_trips_and_defaults_empty(self):
        r = EntityRecord("r1", "actors.anna", 1, {}, {}, native=("Genesis9Eyes", "Genesis9Mouth"))
        self.assertEqual(EntityRecord.from_json(r.to_json()), r)
        legacy = json.dumps({"recipe_id": "r1", "path": "actors.anna", "recipe_version": 1,
                             "desired": {}, "observed": {}})
        self.assertEqual(EntityRecord.from_json(legacy).native, ())

    def test_record_asset_uri_round_trips_and_is_omitted_by_default(self):
        r = EntityRecord("r1", "actors.a.wearing.hair", 2, {}, {},
                         asset_uri="/data/DAZ%203D/Kara%20Ponytail/Kara%20Ponytail%20Scalp/Scalp_1085.dsf")
        self.assertEqual(EntityRecord.from_json(r.to_json()), r)
        self.assertNotIn("asset_uri", EntityRecord("r1", "props.a", 1, {}, {}).to_json())
        legacy = json.dumps({"recipe_id": "r1", "path": "props.a", "recipe_version": 1,
                             "desired": {}, "observed": {}})
        self.assertIsNone(EntityRecord.from_json(legacy).asset_uri)

    def test_record_backward_compatible(self):
        v1 = json.dumps({"recipe_id": "r1", "path": "props.a", "recipe_version": 1,
                         "desired": {}, "observed": {}})
        r = EntityRecord.from_json(v1)
        self.assertEqual((r.source, r.group, r.primary, r.adopted_from_scene, r.done),
                         (None, None, True, False, ()))
        self.assertEqual(r.to_json(), EntityRecord("r1", "props.a", 1, {}, {}).to_json())
        self.assertNotIn("group", r.to_json())
        self.assertNotIn("members", r.to_json())
        full = EntityRecord("r1", "actors.a.wearing.hair", 1, {}, {}, source={"path": "/h.duf"},
                            group="actors.a.wearing.hair", primary=False, adopted_from_scene=True,
                            done=({"entry": 0, "op": "remove", "removed": []},))
        self.assertEqual(EntityRecord.from_json(full.to_json()), full)

    def test_manifest_json_round_trip(self):
        m = man("r1", ["a", "b"], rec("r1", "lighting.environment", {"environment": {"x": 1}}))
        self.assertEqual(Manifest.from_json(m.to_json()), m)
        m2 = man("r1", [])
        self.assertEqual(Manifest.from_json(m2.to_json()), m2)

    def test_manifest_deleted_round_trips_and_defaults_empty(self):
        m = Manifest("r1", ("a",), None, ("cameras.cu",))
        self.assertEqual(Manifest.from_json(m.to_json()), m)
        legacy = json.dumps({"recipe_id": "r1", "entities": ["a"], "environment": None})
        self.assertEqual(Manifest.from_json(legacy).deleted, ())


class ReadLiveTests(unittest.TestCase):
    def test_read_live_filters_by_recipe_id(self):
        client = fake_client(nodes=[node("A", rec("r1", "actors.anna")),
                                    node("B", rec("r2", "actors.anna"))])
        self.assertEqual([e.node_name for e in read_live(client, "r1").entities.values()], ["A"])

    def test_read_live_finds_node_by_record_not_label(self):
        client = fake_client(nodes=[node("Genesis 9", rec("r1", "actors.anna"), label="renamed by user")])
        e = read_live(client, "r1").entities["actors.anna"]
        self.assertEqual(e.label, "renamed by user")
        self.assertIn("n.getLabel()", client.execute.call_args_list[0][0][0])

    def test_foreign_children_listed(self):
        client = fake_client(nodes=[node("A", rec("r1", "actors.anna"),
                                         children=[node("Shirt", None)])])
        self.assertEqual(read_live(client, "r1").entities["actors.anna"].foreign_children, ("Shirt",))

    def test_child_owned_by_recipe_is_not_foreign(self):
        client = fake_client(nodes=[node("A", rec("r1", "actors.anna"),
                                         children=[node("P", rec("r1", "props.hat")),
                                                   node("Q", rec("r2", "props.hat"))])])
        self.assertEqual(read_live(client, "r1").entities["actors.anna"].foreign_children, ("Q",))

    def test_bone_children_not_foreign_but_walked(self):
        hand_prop = node("Sword", None)
        bones = node("hip", None, bone=True, children=[node("rHand", None, bone=True, children=[hand_prop])])
        client = fake_client(nodes=[node("A", rec("r1", "actors.anna"), kind="actor", children=[bones])])
        self.assertEqual(read_live(client, "r1").entities["actors.anna"].foreign_children, ("Sword",))

    def test_native_descendants_are_not_foreign(self):
        # Genesis 9 loads Eyes/Mouth/... as DzFigure children of the root: they came
        # with the asset, so they are not the user's items.
        r = EntityRecord("r1", "actors.anna", 1, {}, {}, native=("Genesis9Eyes", "Genesis9Mouth"))
        client = fake_client(nodes=[node("A", r, kind="actor", children=[
            node("Genesis9Eyes", None), node("Genesis9Mouth", None), node("Shirt", None)])])
        self.assertEqual(read_live(client, "r1").entities["actors.anna"].foreign_children, ("Shirt",))

    def test_item_parented_under_a_native_descendant_is_foreign(self):
        r = EntityRecord("r1", "actors.anna", 1, {}, {}, native=("Genesis9Eyes",))
        client = fake_client(nodes=[node("A", r, kind="actor", children=[
            node("Genesis9Eyes", None, children=[node("Monocle", None)])])])
        self.assertEqual(read_live(client, "r1").entities["actors.anna"].foreign_children, ("Monocle",))

    def test_owned_child_subtree_not_attributed_to_ancestor(self):
        owned = node("P", rec("r1", "props.hat"), children=[node("Grand", None)])
        client = fake_client(nodes=[node("A", rec("r1", "actors.anna"), children=[owned]),
                                    node("P", rec("r1", "props.hat"), children=[node("Grand", None)])])
        ents = read_live(client, "r1").entities
        self.assertEqual(ents["actors.anna"].foreign_children, ())
        self.assertEqual(ents["props.hat"].foreign_children, ("Grand",))

    def test_group_not_duplicate(self):
        path = "actors.abby.wearing.hair"
        g = lambda: EntityRecord("r1", path, 1, {}, {}, group=path)
        state = read_live(fake_client([node("hair", g()), node("cap", g())]), "r1")
        self.assertEqual(state.entities[path].group_nodes, ("hair", "cap"))
        self.assertEqual(state.duplicates, ())

    def test_group_members_missing(self):
        path = "actors.abby.wearing.hair"
        mk = lambda primary: EntityRecord("r1", path, 1, {}, {}, group=path, primary=primary,
                                          members=("hair", "cap"))
        full = read_live(fake_client([node("hair", mk(True)), node("cap", mk(False))]), "r1")
        self.assertEqual(full.entities[path].missing_members, ())
        one = read_live(fake_client([node("hair", mk(True))]), "r1").entities[path]
        self.assertEqual((one.group_nodes, one.missing_members), (("hair",), ("cap",)))
        only = read_live(fake_client([node("cap", mk(False))]), "r1")
        self.assertEqual(len(only.entities), 1)
        self.assertEqual(only.entities[path].node_name, "cap")
        self.assertEqual(only.entities[path].missing_members, ("hair",))
        self.assertEqual(only.duplicates, ())

    def test_group_primary_first(self):
        path = "actors.abby.wearing.hair"
        cap = EntityRecord("r1", path, 1, {}, {}, group=path, primary=False)
        hair = EntityRecord("r1", path, 1, {}, {}, group=path)
        state = read_live(fake_client([node("cap", cap), node("hair", hair)]), "r1")
        self.assertEqual(state.entities[path].node_name, "hair")
        self.assertEqual(state.entities[path].group_nodes, ("hair", "cap"))

    def test_item_kind_and_group_foreign_children(self):
        path = "actors.abby.wearing.hair"
        mk = lambda primary: EntityRecord("r1", path, 1, {}, {}, group=path, primary=primary,
                                          members=("hair", "cap"))
        client = fake_client([node("hair", mk(True), children=[node("Bow", None)]),
                              node("cap", mk(False), children=[node("Pin", None)])])
        ent = read_live(client, "r1").entities[path]
        self.assertEqual(ent.kind, "item")
        self.assertEqual(ent.foreign_children, ("Bow", "Pin"))
        self.assertEqual(ent.foreign_by_node, (("hair", ("Bow",)), ("cap", ("Pin",))))
        self.assertNotIn("pose", ent.observed)  # items are never pose-captured

    def test_same_path_without_group_is_duplicate(self):
        path = "props.ball"
        state = read_live(fake_client([node("a", rec("r1", path)), node("b", rec("r1", path))]), "r1")
        self.assertEqual(len(state.duplicates), 1)
        self.assertEqual(state.entities[path].group_nodes, ())

    def test_duplicate_record_keys_on_first_node_and_is_reported(self):
        client = fake_client(nodes=[node("A", rec("r1", "actors.anna"), kind="actor", element_id=5),
                                    node("B", rec("r1", "props.ball"), element_id=6),
                                    node("A copy", rec("r1", "actors.anna"), kind="actor",
                                         element_id=9)])
        st = read_live(client, "r1")
        self.assertEqual(st.entities["actors.anna"].node_name, "A")
        self.assertEqual(len(st.duplicates), 1)
        d = st.duplicates[0]
        self.assertEqual((d.path, d.node_names, d.element_ids), ("actors.anna", ("A", "A copy"), (5, 9)))
        self.assertEqual(client.execute.call_count, 2)  # one pose capture, not one per copy

    def test_rigged_prop_is_prop_without_pose(self):
        client = fake_client(nodes=[node("R", rec("r1", "props.robot"), kind="actor")])
        e = read_live(client, "r1").entities["props.robot"]
        self.assertEqual(e.kind, "prop")
        self.assertNotIn("pose", e.observed)
        self.assertEqual(client.execute.call_count, 1)

    def test_kind_from_path_prefix(self):
        client = fake_client(nodes=[node("C", rec("r1", "cameras.w")),
                                    node("L", rec("r1", "lighting.rigs.x.key"))])
        ents = read_live(client, "r1").entities
        self.assertEqual((ents["cameras.w"].kind, ents["lighting.rigs.x.key"].kind), ("camera", "light"))

    def test_manifest_lists_entity_missing_from_scene(self):
        st = read_live(fake_client(nodes=[], manifest=man("r1", ["cameras.wide"])), "r1")
        self.assertEqual(st.manifest.entities, ("cameras.wide",))
        self.assertEqual(st.entities, {})

    def test_no_manifest(self):
        st = read_live(fake_client(), "r1")
        self.assertIsNone(st.manifest)
        self.assertIsNone(st.environment_observed)
        self.assertEqual(st.duplicates, ())

    def test_one_script_call_for_non_actors(self):
        client = fake_client(nodes=[node("A", rec("r1", "props.a")), node("B", rec("r1", "props.b"))])
        read_live(client, "r1")
        self.assertEqual(client.execute.call_count, 1)

    def test_actor_gets_pose_snapshot_and_extra_call(self):
        client = fake_client(nodes=[node("A", rec("r1", "actors.anna"), kind="actor", element_id=7,
                                         position=(1, 2, 3), rotation=(0, 90, 0))],
                             pose={"bones": {"hip": [0, 1, 0]}, "morphs": {}, "props": {}})
        e = read_live(client, "r1").entities["actors.anna"]
        self.assertEqual(client.execute.call_count, 2)
        self.assertEqual(e.observed["pose"]["snapshot"]["bones"], {"hip": [0, 1, 0]})
        self.assertEqual(e.observed["transform"], {"position": [1, 2, 3], "rotation": [0, 90, 0]})
        self.assertEqual((e.kind, e.element_id), ("actor", 7))

    def test_actor_pose_snapshot_excludes_node_transform_props(self):
        props = {"XTranslate": 40.0, "YTranslate": 1.0, "ZTranslate": -3.0, "XRotate": 5.0,
                 "YRotate": 90.0, "ZRotate": 2.0, "Scale": 1.0, "Visibility": 1.0}
        client = fake_client(nodes=[node("A", rec("r1", "actors.anna"), kind="actor")],
                             pose={"bones": {}, "morphs": {}, "props": props})
        snap = read_live(client, "r1").entities["actors.anna"].observed["pose"]["snapshot"]
        self.assertEqual(snap["props"], {"Visibility": 1.0})

    def test_camera_and_light_channels(self):
        client = fake_client(nodes=[
            node("C", rec("r1", "cameras.w"), kind="camera", optics={"focal_length": 50.0}),
            node("L", rec("r1", "lighting.lights.k"), kind="light",
                 output={"intensity": 1.0, "color": [255, 255, 255]})])
        ents = read_live(client, "r1").entities
        self.assertEqual(ents["cameras.w"].observed["optics"], {"focal_length": 50.0})
        self.assertEqual(ents["lighting.lights.k"].observed["output"]["intensity"], 1.0)
        self.assertNotIn("pose", ents["cameras.w"].observed)

    def test_environment_observed_only_with_manifest_environment(self):
        env = {"intensity": 1.5}
        m = man("r1", [], rec("r1", "lighting.environment"))
        self.assertEqual(read_live(fake_client(manifest=m, environment=env), "r1").environment_observed, env)
        self.assertIsNone(read_live(fake_client(manifest=man("r1", []), environment=env), "r1")
                          .environment_observed)

    def test_corrupt_manifest_raises(self):
        client = fake_client()
        from dazpy._result import ExecutionResult
        client.execute.side_effect = None
        client.execute.return_value = ExecutionResult(value={"manifest": "{not json", "nodes": []})
        with self.assertRaisesRegex(DazError, "manifest"):
            read_live(client, "r1")

    def test_unparseable_record_is_ignored(self):
        client = fake_client(nodes=[node("A", rec("r1", "props.a"))])
        client.execute.side_effect = None
        from dazpy._result import ExecutionResult
        client.execute.return_value = ExecutionResult(value={"nodes": [
            {"name": "A", "record": "not json", "kind": "prop", "position": [0, 0, 0],
             "rotation": [0, 0, 0], "children": []}]})
        self.assertEqual(read_live(client, "r1").entities, {})

    def test_read_script_shape(self):
        client = fake_client()
        read_live(client, "r1")
        s = client.execute.call_args_list[0][0][0]
        for frag in ('"dazpy.scene_recipe"', '"dazpy.scene_recipe.r1"', "Scene.getNodeList()",
                     "getWSPos()", 'typeof n.getElementID === "function"', "findDataItem", "Environment Intensity"):
            self.assertIn(frag, s)


class ScriptBuilderTests(unittest.TestCase):
    def test_write_record_script_uses_simple_element_data(self):
        s = write_record_script("A", rec("r1", "actors.anna"))
        self.assertIn("DzSimpleElementData", s)
        self.assertIn('"dazpy.scene_recipe"', s)
        self.assertIn("removeDataItem", s)       # replaces an existing record
        self.assertIn('Scene.findNode("A")', s)

    def test_write_record_script_embeds_record_json(self):
        r = rec("r1", 'actors."q"')
        self.assertIn(json.dumps(r.to_json()), write_record_script("A", r))

    def test_remove_record_script(self):
        s = remove_record_script("A")
        self.assertIn("removeDataItem", s)
        self.assertNotIn("DzSimpleElementData", s)

    def test_write_manifest_script(self):
        s = write_manifest_script(man("r1", ["a"]))
        self.assertIn("DzSimpleSceneData", s)
        self.assertIn('"dazpy.scene_recipe.r1"', s)
        self.assertIn("Scene.addDataItem", s)


if __name__ == "__main__":
    unittest.main()
