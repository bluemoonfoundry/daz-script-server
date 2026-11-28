"""dazpy unit tests: DazNode / DazElement script generation: properties, modifiers, morphs, hierarchy, dForce.

Mock-based; no server or DAZ Studio required.
Shared fakes live in tests/dazpy_fakes.py.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dazpy._result import ExecutionResult
from dazpy._script_builder import ScriptBuilder
from dazpy._node import DazNode, NodeIdentifier
from dazpy._scene import DazScene
from dazpy import exceptions
from dazpy_fakes import mock_client


class TestDazNodeScriptGeneration(unittest.TestCase):
    def test_label_property_calls_execute(self):
        client = mock_client("Genesis 9")
        node = DazNode(client, NodeIdentifier("Genesis9"))
        result = node.label
        self.assertEqual(result, "Genesis 9")
        client.execute.assert_called_once()
        script = client.execute.call_args[0][0]
        self.assertIn("Genesis9", script)
        self.assertIn("getLabel", script)

    def test_position_returns_dict(self):
        client = mock_client({"x": 0.0, "y": 95.2, "z": -3.1})
        node = DazNode(client, NodeIdentifier("Genesis9"))
        pos = node.position
        self.assertEqual(pos["y"], 95.2)

    def test_set_position_calls_execute(self):
        client = mock_client(None)
        node = DazNode(client, NodeIdentifier("Genesis9"))
        node.set_position(1.0, 2.0, 3.0)
        script = client.execute.call_args[0][0]
        self.assertIn("setWSPos", script)
        self.assertIn("1.0", script)

    def test_rotation_returns_xyzw(self):
        client = mock_client({"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0})
        node = DazNode(client, NodeIdentifier("Genesis9"))
        rot = node.rotation
        self.assertIn("w", rot)
        self.assertEqual(rot["w"], 1.0)
        script = client.execute.call_args[0][0]
        self.assertIn("r.w", script)

    def test_general_scale_returns_float(self):
        client = mock_client(1.0)
        node = DazNode(client, NodeIdentifier("Genesis9"))
        gs = node.general_scale
        self.assertEqual(gs, 1.0)
        script = client.execute.call_args[0][0]
        self.assertIn("getScaleControl", script)
        self.assertNotIn("getXScaleControl", script)

    def test_scale_returns_dict_with_all_axes(self):
        client = mock_client({"x": 1.0, "y": 1.0, "z": 1.0, "general": 1.0})
        node = DazNode(client, NodeIdentifier("Genesis9"))
        s = node.scale
        self.assertIsInstance(s, dict)
        for key in ("x", "y", "z", "general"):
            self.assertIn(key, s)
        script = client.execute.call_args[0][0]
        self.assertIn("getXScaleControl", script)
        self.assertIn("getYScaleControl", script)
        self.assertIn("getZScaleControl", script)
        self.assertIn("getScaleControl", script)

    def test_visible_setter(self):
        client = mock_client(None)
        node = DazNode(client, NodeIdentifier("MyNode"))
        node.visible = False
        script = client.execute.call_args[0][0]
        self.assertIn("setVisible", script)
        self.assertIn("false", script)


class TestDazNodeNumericCandidates(unittest.TestCase):
    """DazNode.set_numeric_candidates() (5d6f.29: emotion/expression dials)."""

    def _node(self, return_value):
        client = mock_client(return_value)
        return DazNode(client, NodeIdentifier("Genesis 9", kind="label")), client

    def test_single_call_and_payload(self):
        node, client = self._node([
            {"matched": "Smile", "source": "property", "value": 0.6},
            {"matched": None, "source": None, "value": None},
        ])
        results = node.set_numeric_candidates([
            (["PHMSmile", "Smile"], 0.6),
            (("BrowUp",), 0.4),
        ])
        self.assertEqual(client.execute.call_count, 1)
        script = client.execute.call_args[0][0]
        self.assertIn("findProperty", script)
        self.assertIn("findPropertyByLabel", script)
        self.assertIn("DzMorph", script)
        self.assertIn("DzNumericProperty", script)
        self.assertIn('"PHMSmile"', script)
        self.assertEqual(results[0].matched, "Smile")
        self.assertEqual(results[0].source, "property")
        self.assertAlmostEqual(results[0].value, 0.6)
        self.assertEqual(results[0].candidates, ("PHMSmile", "Smile"))
        self.assertTrue(results[0].found)
        self.assertFalse(results[1].found)
        self.assertEqual(results[1].requested, 0.4)

    def test_missing_node_raises(self):
        node, _ = self._node(None)
        with self.assertRaises(exceptions.NodeNotFoundError):
            node.set_numeric_candidates([(["Smile"], 1.0)])

    def test_empty_slots_is_noop(self):
        node, client = self._node([])
        self.assertEqual(node.set_numeric_candidates([]), [])
        client.execute.assert_not_called()

    def test_rejects_string_candidates(self):
        # A bare string would be iterated per character -- refuse it.
        node, client = self._node([])
        with self.assertRaises(TypeError):
            node.set_numeric_candidates([("Smile", 1.0)])
        client.execute.assert_not_called()

    def test_names_are_json_escaped(self):
        node, client = self._node([{"matched": None, "source": None, "value": None}])
        node.set_numeric_candidates([(['a"); Scene.clear(); ("'], 1.0)])
        script = client.execute.call_args[0][0]
        self.assertNotIn('a"); Scene.clear()', script)


class TestNodeResolution(unittest.TestCase):
    """elementID identifiers, resolve_node, find_nodes (daz-mcp-server-nde)."""

    def test_element_id_identifier_uses_find_by_element_id(self):
        client = mock_client({"x": 0, "y": 0, "z": 0})
        DazNode(client, NodeIdentifier("4217", kind="element_id")).position
        self.assertIn("Scene.findNodeByElementID(4217)", client.execute.call_args[0][0])

    def test_element_id_skeleton_and_bone_lookup(self):
        from dazpy._skeleton import DazSkeleton
        client = mock_client(["head"])
        skel = DazSkeleton(client, NodeIdentifier("4217", kind="element_id"))
        skel.bone_names()
        script = client.execute.call_args[0][0]
        self.assertIn("_skels[_i].elementID === 4217", script)
        bone = skel.bones()[0]
        client.execute.return_value = ExecutionResult(value="Head", output=[], request_id="t")
        bone.label
        self.assertIn("_skels[_i].elementID === 4217", client.execute.call_args[0][0])

    def test_element_id_must_be_numeric(self):
        with self.assertRaises(ValueError):
            ScriptBuilder.find_node_expr(NodeIdentifier("abc", kind="element_id"))

    def test_resolve_node_returns_typed_element_id_proxy(self):
        from dazpy._skeleton import DazSkeleton
        client = mock_client({"status": "ok", "element_id": 77, "type": "DzSkeleton"})
        node = DazScene(client).resolve_node("Genesis 9")
        self.assertIsInstance(node, DazSkeleton)
        self.assertEqual(node._identifier, NodeIdentifier("77", kind="element_id"))
        script = client.execute.call_args[0][0]
        self.assertIn('"Genesis 9"', script)
        self.assertIn("findNodeChildByLabel", script)
        self.assertIn("findNodeByElementID", script)

    def test_lights_typed_before_cameras(self):
        # DzLight inherits DzCamera; a light must come back as DazLight.
        script_client = mock_client({"status": "ok", "element_id": 5, "type": "DzLight"})
        DazScene(script_client).resolve_node("Key")
        script = script_client.execute.call_args[0][0]
        self.assertLess(script.index('"DzLight"'), script.index('"DzCamera"'))
        client = mock_client([])
        DazScene(client).nodes()
        script = client.execute.call_args[0][0]
        self.assertLess(script.index('inherits("DzLight")'), script.index('inherits("DzCamera")'))

    def test_resolve_node_accepts_int(self):
        client = mock_client({"status": "ok", "element_id": 5, "type": "DzNode"})
        DazScene(client).resolve_node(5)
        self.assertIn('"5"', client.execute.call_args[0][0])

    def test_resolve_node_missing(self):
        client = mock_client({"status": "missing", "ref": "Ghost"})
        with self.assertRaises(exceptions.NodeNotFoundError):
            DazScene(client).resolve_node("Ghost")

    def test_resolve_node_ambiguous_lists_candidates(self):
        matches = [
            {"label": "Chair", "name": "Chair", "type": "DzNode", "element_id": 1, "parent": None},
            {"label": "Chair", "name": "Chair_2", "type": "DzNode", "element_id": 2, "parent": "Room"},
        ]
        client = mock_client({"status": "ambiguous", "ref": "Chair", "count": 2, "matches": matches})
        with self.assertRaises(exceptions.AmbiguousNodeError) as ctx:
            DazScene(client).resolve_node("Chair")
        err = ctx.exception
        self.assertEqual([m.element_id for m in err.matches], [1, 2])
        self.assertIn("elementID", str(err))
        self.assertIn("Room", str(err))

    def test_resolve_node_empty_ref(self):
        with self.assertRaises(ValueError):
            DazScene(mock_client(None)).resolve_node("")

    def test_find_nodes(self):
        client = mock_client([
            {"label": "Chair", "name": "Chair", "type": "DzNode", "element_id": 1, "parent": None}])
        found = DazScene(client).find_nodes("Chair")
        self.assertEqual(found[0].element_id, 1)
        self.assertIsNone(found[0].parent)


class TestKeyedCandidatesAndBones(unittest.TestCase):
    """key_numeric_candidates / key_bone_axes (timed expressions, ord)."""

    def test_key_numeric_candidates(self):
        client = mock_client([{"matched": "facs_ctrl_Happy", "source": "property", "value": None},
                               {"matched": None, "source": None, "value": None}])
        node = DazNode(client, NodeIdentifier("9", kind="element_id"))
        r = node.key_numeric_candidates([(["facs_ctrl_Happy"], [(0, 0.0), (10, 0.7)]),
                                         (["Nope"], [(0, 1.0)])])
        self.assertEqual(r[0].matched, "facs_ctrl_Happy")
        self.assertFalse(r[1].found)
        script = client.execute.call_args[0][0]
        self.assertIn("Scene.getTimeStep()", script)
        self.assertIn("[[0, 0.0], [10, 0.7]]", script)
        self.assertIn("findPropertyByLabel", script)

    def test_key_numeric_candidates_rejects_bare_string(self):
        node = DazNode(mock_client([]), NodeIdentifier("9", kind="element_id"))
        with self.assertRaises(TypeError):
            node.key_numeric_candidates([("Smile", [(0, 1.0)])])

    def test_key_bone_axes(self):
        from dazpy._skeleton import DazSkeleton
        client = mock_client(["lShldr"])
        skel = DazSkeleton(client, NodeIdentifier("9", kind="element_id"))
        missing = skel.key_bone_axes({"spine4": {"x": [(0, 0.0), (10, 2.1)]},
                                      "lShldr": {"z": [(0, 1.0)]}})
        self.assertEqual(missing, ["lShldr"])
        script = client.execute.call_args[0][0]
        self.assertIn("Scene.getTimeStep()", script)
        self.assertIn("getXRotControl", script)
        with self.assertRaises(ValueError):
            skel.key_bone_axes({"hip": {"w": [(0, 1.0)]}})


class TestTransformTypesAndTimeStep(unittest.TestCase):
    def test_all_node_transforms_types_lights_before_cameras(self):
        client = mock_client([])
        DazScene(client).all_node_transforms()
        script = client.execute.call_args[0][0]
        self.assertLess(script.index('inherits("DzLight")'), script.index('inherits("DzCamera")'))
        self.assertIn('"wearables"', script)
        self.assertIn("element_id: n.elementID", script)

    def test_time_step(self):
        self.assertEqual(DazScene(mock_client(160)).time_step(), 160)
        self.assertEqual(DazScene(mock_client(None)).time_step(), 160)
        self.assertEqual(DazScene(mock_client(True)).time_step(), 160)


class TestContentAssetMorphLoader(unittest.TestCase):
    """content listing, strand hair listing, support asset save, Morph Loader Pro (z2h)."""

    def test_content_categories_and_files(self):
        client = mock_client([{"name": "Poses", "path": "People/Poses", "duf_count": 3}])
        cats = DazScene(client).content_categories("/People/")
        self.assertEqual((cats[0].path, cats[0].duf_count), ("People/Poses", 3))
        script = client.execute.call_args[0][0]
        self.assertIn("getNumContentDirectories()", script)
        self.assertIn('"People"', script)
        client = mock_client([{"name": "Hero", "filename": "Hero.duf", "full_path": "D:/x/Hero.duf"}])
        files = DazScene(client).content_files("People/Poses")
        self.assertEqual(files[0].full_path, "D:/x/Hero.duf")

    def test_strand_hair_nodes(self):
        client = mock_client([{"label": "Hair", "name": "Hair", "target": "Genesis 9",
                                "has_geometry": True, "materials": ["Hair"], "element_id": 4}])
        nodes = DazScene(client).strand_hair_nodes()
        self.assertEqual(nodes[0]["target"], "Genesis 9")
        self.assertIn('inherits("DzStrandHairNode")', client.execute.call_args[0][0])

    def test_save_support_asset(self):
        client = mock_client({"status": "ok", "base": "D:/Lib"})
        node = DazNode(client, NodeIdentifier("9", kind="element_id"))
        self.assertEqual(node.save_support_asset("D:/Lib/data/x.duf", vendor="Me", smart_parent=True), "D:/Lib")
        script = client.execute.call_args[0][0]
        self.assertIn("DzNodeSupportAssetFilter", script)
        self.assertIn('"SmartParentProp", "yes"', script)
        self.assertIn('"RunSilent", "yes"', script)
        self.assertIn('replace(/\\\\/g, "/")', script)  # JS regex matching one backslash
        for status, exc in (("outside", ValueError), ("failed", exceptions.DazError),
                            ("unavailable", exceptions.DazError)):
            client = mock_client({"status": status, "dirs": ["D:/Lib"], "code": 3})
            with self.assertRaises(exc):
                DazNode(client, NodeIdentifier("9", kind="element_id")).save_support_asset("C:/x.duf")

    def test_load_morph(self):
        client = mock_client({"status": "ok", "morph": "MyMorph", "log": "",
                               "control": None})
        node = DazNode(client, NodeIdentifier("9", kind="element_id"))
        r = node.load_morph("C:/m.obj", morph_name="MyMorph", load_mode="PrimaryNode")
        self.assertEqual(r.morph_name, "MyMorph")
        script = client.execute.call_args[0][0]
        self.assertIn("new DzMorphLoader()", script)
        self.assertIn('"loadMode": "PrimaryNode"', script)
        client = mock_client({"status": "error", "message": "Unknown loadMode: Bad"})
        with self.assertRaises(exceptions.DazError):
            DazNode(client, NodeIdentifier("9", kind="element_id")).load_morph("C:/m.obj", load_mode="Bad")


class TestKeyColor(unittest.TestCase):
    def test_key_color(self):
        client = mock_client({"status": "ok", "keys": 2, "label": "Color"})
        n = DazNode(client, NodeIdentifier("9", kind="element_id")).key_color(
            "Color", [(0, (255, 200, 128)), (30, (128, 178, 255))])
        self.assertEqual(n, 2)
        script = client.execute.call_args[0][0]
        self.assertIn("setColorValue(k[0] * _step, new Color(k[1], k[2], k[3]))", script)
        self.assertIn("[0, 255, 200, 128]", script)

    def test_key_color_missing(self):
        client = mock_client({"status": "missing"})
        with self.assertRaises(exceptions.PropertyNotFoundError):
            DazNode(client, NodeIdentifier("9", kind="element_id")).key_color("Tint", [(0, (1, 2, 3))])


class TestDForceHelpers(unittest.TestCase):
    """dForce surface/weights/properties/freeze and the Transfer Utility (1kd)."""

    def _node(self, value):
        client = mock_client(value)
        return DazNode(client, NodeIdentifier("9", kind="element_id")), client

    def test_add_dynamic_surface(self):
        node, client = self._node({"status": "added"})
        self.assertTrue(node.add_dforce_dynamic_surface())
        script = client.execute.call_args[0][0]
        self.assertIn("DzAddDForceModifierDynamicSurfaceAction", script)
        self.assertLess(script.index("_findDForce("), script.index("trigger()"))
        node, _ = self._node({"status": "present"})
        self.assertFalse(node.add_dforce_dynamic_surface())

    def test_add_dynamic_surface_failed(self):
        node, _ = self._node({"status": "not_added"})
        with self.assertRaises(exceptions.DazError):
            node.add_dforce_dynamic_surface()

    def test_influence_weights(self):
        node, client = self._node({"status": "ok", "weights": [1.0, 0.0]})
        self.assertEqual(node.dforce_influence_weights(), [1.0, 0.0])
        node, _ = self._node({"status": "ok", "weights": None})
        self.assertIsNone(node.dforce_influence_weights())
        node, _ = self._node({"status": "no_dforce", "modifiers": ["obj:DzMorph"]})
        with self.assertRaises(exceptions.DazError) as ctx:
            node.dforce_influence_weights()
        self.assertIn("obj:DzMorph", str(ctx.exception))

    def test_set_influence_weights(self):
        node, client = self._node({"status": "ok", "vertex_count": 3, "overridden": 1})
        self.assertEqual(node.set_dforce_influence_weights(1.0, {2: 0.0, 9: 0.5}), (3, 1))
        script = client.execute.call_args[0][0]
        self.assertIn("new DzWeightMap()", script)
        self.assertIn('{"2": 0.0, "9": 0.5}', script)
        node, _ = self._node({"status": "no_vertex_count"})
        with self.assertRaises(exceptions.DazError):
            node.set_dforce_influence_weights()

    def test_set_dforce_property(self):
        node, client = self._node({"status": "ok", "modifier": "DzDForceModifier",
                                   "property": "Dynamics Strength", "old": 1.0, "new": 0.5})
        r = node.set_dforce_property("dynamics strength", 0.5)
        self.assertEqual((r["old_value"], r["new_value"]), (1.0, 0.5))
        node, _ = self._node({"status": "no_property", "available": ["A", "B"]})
        with self.assertRaises(exceptions.PropertyNotFoundError) as ctx:
            node.set_dforce_property("Nope", 1)
        self.assertIn("A, B", str(ctx.exception))

    def test_surface_properties(self):
        node, client = self._node({"status": "ok", "material": "Cloth", "properties": [
            {"name": "Friction", "label": "Friction", "type": "numeric", "value": 0.2}]})
        mat, props = node.dforce_surface_properties()
        self.assertEqual((mat, props[0]["name"]), ("Cloth", "Friction"))
        self.assertIn("findSimulationSettingsProvider", client.execute.call_args[0][0])
        node, _ = self._node({"status": "ok", "material": "Cloth", "property": "Friction",
                              "old": 0.2, "new": 0.4})
        r = node.set_dforce_surface_property("Friction", 0.4, material="Cloth")
        self.assertEqual(r["new_value"], 0.4)
        node, _ = self._node({"status": "no_provider", "material": "Cloth", "available": []})
        with self.assertRaises(exceptions.DazError):
            node.dforce_surface_properties("Cloth")

    def test_freeze_dforce(self):
        node, client = self._node(2)
        self.assertEqual(node.freeze_dforce(), 2)
        self.assertIn('findPropertyByLabel("Freeze Simulation")', client.execute.call_args[0][0])

    def test_scene_freeze_dforce(self):
        client = mock_client(3)
        self.assertEqual(DazScene(client).freeze_dforce(), 3)
        script = client.execute.call_args[0][0]
        self.assertIn("Scene.getNumNodes()", script)
        self.assertIn('findPropertyByLabel("Freeze Simulation")', script)

    def test_transfer_utility(self):
        from dazpy._node import DazNode as N
        client = mock_client({"ok": True})
        src, dst = N(client, NodeIdentifier("1", kind="element_id")), N(client, NodeIdentifier("2", kind="element_id"))
        DazScene(client).transfer_utility(src, dst, morphs=True, fit_to_figure=True)
        script = client.execute.call_args[0][0]
        self.assertIn("setSilentImporters(true)", script)
        self.assertIn("setTransferMorphs(true)", script)
        self.assertIn("setTransferUVs(false)", script)
        client = mock_client({"ok": False})
        with self.assertRaises(exceptions.DazError):
            DazScene(client).transfer_utility(src, dst)


class TestSubdivision(unittest.TestCase):
    def test_subdivision_reads_shape_levels(self):
        client = mock_client({"view": 1, "render": 3})
        self.assertEqual(DazNode(client, NodeIdentifier("9", kind="element_id")).subdivision(),
                         {"view": 1, "render": 3})
        script = client.execute.call_args[0][0]
        self.assertIn("getCurrentShape()", script)
        self.assertIn('"SubDIALevel"', script)

    def test_set_subdivision_returns_previous(self):
        client = mock_client({"status": "ok", "previous": {"view": 1, "render": 3},
                               "current": {"view": 2, "render": 3}})
        r = DazNode(client, NodeIdentifier("9", kind="element_id")).set_subdivision(2)
        self.assertEqual(r["previous"], {"view": 1, "render": 3})
        self.assertIn("var _render = null", client.execute.call_args[0][0])

    def test_set_subdivision_unsupported(self):
        client = mock_client({"status": "no_subd"})
        with self.assertRaises(exceptions.PropertyNotFoundError):
            DazNode(client, NodeIdentifier("9", kind="element_id")).set_subdivision(1)


class TestExportErrors(unittest.TestCase):
    def test_missing_exporter_raises(self):
        client = mock_client({"status": "no_exporter"})
        with self.assertRaises(exceptions.DazError):
            DazScene(client).export_fbx("C:/out.fbx")

    def test_write_error_raises(self):
        client = mock_client({"status": "error", "code": 5})
        with self.assertRaises(exceptions.DazError) as ctx:
            DazScene(client).export_obj("C:/out.obj")
        self.assertIn("5", str(ctx.exception))

    def test_ok(self):
        client = mock_client({"status": "ok"})
        DazScene(client).export_obj("C:/out.obj")
        self.assertIn("writeFile", client.execute.call_args[0][0])


class TestFittedItems(unittest.TestCase):
    def test_fitted_items_skip_bones_and_bind_by_element_id(self):
        client = mock_client([{"label": "Shirt", "name": "Shirt", "type": "clothing",
                                "element_id": 21}])
        items = DazNode(client, NodeIdentifier("9", kind="element_id")).fitted_items()
        self.assertEqual(items[0]._identifier, NodeIdentifier("21", kind="element_id"))
        self.assertIn('inherits("DzBone")', client.execute.call_args[0][0])

    def test_fitted_item_info(self):
        client = mock_client([{"label": "Hair", "name": "Hair", "type": "hair", "element_id": 5}])
        info = DazNode(client, NodeIdentifier("9", kind="element_id")).fitted_item_info()
        self.assertEqual((info[0].label, info[0].type, info[0].element_id), ("Hair", "hair", 5))
        self.assertIn('inherits("DzHair")', client.execute.call_args[0][0])


class TestPropertyDetailsAndBatchSet(unittest.TestCase):
    """property_details / property_detail / set_numeric_properties (daz-mcp-server-ksl)."""

    def test_property_details_filter(self):
        row = {"label": "X Translate", "name": "XTranslate", "type": "DzFloatProperty",
               "value": 0.0, "min": -1e4, "max": 1e4, "default": 0.0, "path": "Transforms",
               "is_animatable": True}
        client = mock_client([row])
        node = DazNode(client, NodeIdentifier("9", kind="element_id"))
        details = node.property_details("transform")
        self.assertEqual(details[0].path, "Transforms")
        self.assertIn('var _kind = "transform"', client.execute.call_args[0][0])
        # DzProperty has canAnimate(); isAnimatable() does not exist (always false)
        self.assertIn("p.canAnimate()", client.execute.call_args[0][0])

    def test_property_details_rejects_unknown_kind(self):
        node = DazNode(mock_client([]), NodeIdentifier("9", kind="element_id"))
        with self.assertRaises(ValueError):
            node.property_details("colour")

    def test_property_detail_missing(self):
        node = DazNode(mock_client({"status": "missing"}), NodeIdentifier("9", kind="element_id"))
        with self.assertRaises(exceptions.PropertyNotFoundError):
            node.property_detail("Nope")

    def test_property_detail(self):
        client = mock_client({"status": "ok", "detail": {
            "label": "Flux", "name": "Flux", "type": "DzFloatProperty", "value": 1500.0,
            "min": 0.0, "max": 1e5, "default": 1500.0, "path": "Light", "is_animatable": True}})
        d = DazNode(client, NodeIdentifier("9", kind="element_id")).property_detail("flux")
        self.assertEqual((d.label, d.default), ("Flux", 1500.0))

    def test_set_numeric_properties_one_call_per_op_errors(self):
        client = mock_client([
            {"ok": True, "node": "Genesis 9", "property": "X Translate", "value": 10},
            {"ok": False, "node": None, "error": "Ambiguous node 'Chair' (2 matches)"},
        ])
        results = DazScene(client).set_numeric_properties(
            [("Genesis 9", "x translate", 10), ("Chair", "Y Rotate", 5)])
        self.assertEqual(client.execute.call_count, 1)
        self.assertTrue(results[0].ok)
        self.assertEqual(results[0].property, "X Translate")
        self.assertFalse(results[1].ok)
        self.assertIn("Ambiguous", results[1].error)
        script = client.execute.call_args[0][0]
        self.assertIn("_findNumeric(", script)
        self.assertIn("_resolve(", script)

    def test_set_numeric_properties_empty(self):
        client = mock_client([])
        self.assertEqual(DazScene(client).set_numeric_properties([]), [])
        client.execute.assert_not_called()


class TestFrameKeys(unittest.TestCase):
    """find_numeric_property + frame-based keys (daz-mcp-server-scz). Keys are
    stored in DzTime ticks; frames convert with Scene.getTimeStep()."""

    def _prop(self, value=None):
        from dazpy._property import DazProperty
        client = mock_client(value)
        return DazProperty._from_locator(client, "PROP"), client

    def test_find_numeric_property(self):
        from dazpy._property import DazProperty
        client = mock_client(True)
        prop = DazNode(client, NodeIdentifier("9", kind="element_id")).find_numeric_property("x translate")
        self.assertIsInstance(prop, DazProperty)
        self.assertIn("_findNumeric(", prop._locator)
        self.assertIn('"x translate"', prop._locator)

    def test_find_numeric_property_missing(self):
        client = mock_client(False)
        with self.assertRaises(exceptions.PropertyNotFoundError):
            DazNode(client, NodeIdentifier("9", kind="element_id")).find_numeric_property("Nope")

    def test_set_key_at_frame_converts_to_ticks(self):
        prop, client = self._prop(5.0)
        self.assertEqual(prop.set_key_at_frame(30, 5), 5.0)
        script = client.execute.call_args[0][0]
        self.assertIn("30 * Scene.getTimeStep()", script)
        self.assertIn("setDoubleValue(_tm, 5.0)", script)

    def test_keys_by_frame(self):
        prop, client = self._prop([[0, 0.0], [30, 5.0]])
        self.assertEqual(prop.keys_by_frame(), [(0, 0.0), (30, 5.0)])
        self.assertIn("/ _step", client.execute.call_args[0][0])

    def test_remove_key_at_frame(self):
        prop, client = self._prop(True)
        self.assertTrue(prop.remove_key_at_frame(12))
        script = client.execute.call_args[0][0]
        self.assertIn("12 * Scene.getTimeStep()", script)
        self.assertIn("deleteKeys(new DzTimeRange(_tm, _tm))", script)

    def test_clear_keys_returns_count(self):
        prop, _ = self._prop(4)
        self.assertEqual(prop.clear_keys(), 4)


class TestDazNodeUnparent(unittest.TestCase):
    def test_unparent_moves_to_scene_root(self):
        client = mock_client(None)
        DazNode(client, NodeIdentifier("7", kind="element_id")).unparent()
        script = client.execute.call_args[0][0]
        self.assertIn("removeNodeChild(_node, true)", script)

    def test_unparent_keep_local(self):
        client = mock_client(None)
        DazNode(client, NodeIdentifier("7", kind="element_id")).unparent(preserve_world_transform=False)
        self.assertIn("removeNodeChild(_node, false)", client.execute.call_args[0][0])

    def test_unparent_failure_raises(self):
        client = mock_client("DzError code 3")
        with self.assertRaises(exceptions.ScriptRuntimeError):
            DazNode(client, NodeIdentifier("7", kind="element_id")).unparent()


class TestNodePropertySearch(unittest.TestCase):
    """describe / numeric_properties / set_numeric_property / morph_info (nde)."""

    def _node(self, value):
        client = mock_client(value)
        return DazNode(client, NodeIdentifier("12", kind="element_id")), client

    def test_describe(self):
        node, client = self._node({"name": "Chair", "label": "Chair", "type": "DzNode",
                                   "element_id": 12, "parent": "Room", "num_children": 3})
        info = node.describe()
        self.assertEqual((info.label, info.element_id, info.parent, info.num_children),
                         ("Chair", 12, "Room", 3))

    def test_describe_missing_raises(self):
        node, _ = self._node(None)
        with self.assertRaises(exceptions.NodeNotFoundError):
            node.describe()

    def test_numeric_properties_searches_modifiers(self):
        node, client = self._node({"X Translate": 0.0, "Smile": 0.4})
        self.assertEqual(node.numeric_properties(include_modifiers=True),
                         {"X Translate": 0.0, "Smile": 0.4})
        script = client.execute.call_args[0][0]
        self.assertIn("getNumModifiers", script)
        self.assertIn("getValueChannel", script)
        self.assertIn("DzNumericProperty", script)

    def test_numeric_properties_default_is_node_only(self):
        node, client = self._node({"X Translate": 0.0})
        node.numeric_properties()
        self.assertNotIn("getNumModifiers", client.execute.call_args[0][0])

    def test_set_numeric_property_exact(self):
        node, client = self._node({"status": "ok", "label": "Head Size", "name": "HeadSize",
                                   "value": 1.1})
        w = node.set_numeric_property("HeadSize", 1.1)
        self.assertEqual((w.label, w.name, w.value), ("Head Size", "HeadSize", 1.1))
        script = client.execute.call_args[0][0]
        self.assertIn("var _substring = false", script)
        self.assertIn("lock(false)", script)

    def test_set_numeric_property_substring_and_no_unlock(self):
        node, client = self._node({"status": "ok", "label": "Mouth Smile", "name": "eCTRLMouthSmile",
                                   "value": 0.8})
        node.set_numeric_property("smile", 0.8, substring_fallback=True, unlock=False)
        script = client.execute.call_args[0][0]
        self.assertIn("var _substring = true", script)
        self.assertIn("var _unlock = false", script)

    def test_set_numeric_property_not_found_and_not_numeric(self):
        node, _ = self._node({"status": "missing"})
        with self.assertRaises(exceptions.PropertyNotFoundError):
            node.set_numeric_property("Nope", 1)
        node, _ = self._node({"status": "not_numeric", "label": "Label"})
        with self.assertRaises(TypeError):
            node.set_numeric_property("Label", 1)

    def test_morph_info(self):
        node, client = self._node([{"name": "Smile", "label": "Smile", "value": 0.5,
                                    "path": "Morphs/Face"}])
        morphs = node.morph_info(pattern="SMI", include_zero=True)
        self.assertEqual(morphs[0].path, "Morphs/Face")
        script = client.execute.call_args[0][0]
        self.assertIn('"smi"', script)
        self.assertIn("var _includeZero = true", script)


class TestDazModifierScriptGeneration(unittest.TestCase):
    def _make_modifier(self, return_value=None, locator='Scene.findNode("MyNode").getObject().findModifier("MyMod")'):
        from dazpy._modifier import DazModifier
        client = mock_client(return_value)
        mod = DazModifier(client, locator)
        return mod, client

    def test_modifier_label_calls_getLabel(self):
        mod, client = self._make_modifier("My Morph")
        label = mod.modifier_label
        self.assertEqual(label, "My Morph")
        script = client.execute.call_args[0][0]
        self.assertIn("getLabel", script)

    def test_enabled_getter_calls_isEnabled(self):
        mod, client = self._make_modifier(True)
        val = mod.enabled
        self.assertTrue(val)
        script = client.execute.call_args[0][0]
        self.assertIn("isEnabled", script)

    def test_enabled_setter_calls_setEnabled(self):
        mod, client = self._make_modifier(None)
        mod.enabled = False
        script = client.execute.call_args[0][0]
        self.assertIn("setEnabled", script)
        self.assertIn("false", script)


class TestDazMorphScriptGeneration(unittest.TestCase):
    def _make_morph(self, return_value=None):
        from dazpy._morph import DazMorph
        client = mock_client(return_value)
        locator = 'Scene.findNode("Genesis9").getObject().findModifier("MyMorph")'
        morph = DazMorph(client, locator)
        return morph, client

    def test_value_getter_calls_getValueChannel(self):
        morph, client = self._make_morph(0.5)
        val = morph.value
        self.assertAlmostEqual(val, 0.5)
        script = client.execute.call_args[0][0]
        self.assertIn("getValueChannel", script)
        self.assertIn("getValue", script)

    def test_value_setter_calls_setValue(self):
        morph, client = self._make_morph(None)
        morph.value = 0.75
        script = client.execute.call_args[0][0]
        self.assertIn("getValueChannel", script)
        self.assertIn("setValue", script)
        self.assertIn("0.75", script)

    def test_min_calls_getMin(self):
        morph, client = self._make_morph(0.0)
        val = morph.min
        self.assertEqual(val, 0.0)
        script = client.execute.call_args[0][0]
        self.assertIn("getMin", script)

    def test_max_calls_getMax(self):
        morph, client = self._make_morph(1.0)
        val = morph.max
        self.assertEqual(val, 1.0)
        script = client.execute.call_args[0][0]
        self.assertIn("getMax", script)

    def test_value_setter_accepts_int(self):
        morph, client = self._make_morph(None)
        morph.value = 1
        script = client.execute.call_args[0][0]
        self.assertIn("1.0", script)


class TestDazNodeModifierMethods(unittest.TestCase):
    def test_modifiers_returns_list_of_daz_modifier(self):
        from dazpy._modifier import DazModifier
        from dazpy._morph import DazMorph
        client = mock_client([
            {"name": "SomeMod", "className": "DzSubDivisionModifier"},
            {"name": "MyMorph", "className": "DzMorph"},
        ])
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mods = node.modifiers()
        self.assertEqual(len(mods), 2)
        self.assertIsInstance(mods[0], DazModifier)
        self.assertIsInstance(mods[1], DazMorph)

    def test_modifiers_script_uses_getNumModifiers(self):
        client = mock_client([])
        node = DazNode(client, NodeIdentifier("Genesis9"))
        node.modifiers()
        script = client.execute.call_args[0][0]
        self.assertIn("getNumModifiers", script)
        self.assertIn("getObject", script)
        self.assertIn("className", script)

    def test_modifiers_empty_when_no_object(self):
        client = mock_client([])
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mods = node.modifiers()
        self.assertEqual(mods, [])

    def test_find_modifier_returns_daz_modifier(self):
        from dazpy._modifier import DazModifier
        client = mock_client({"name": "SomeMod", "className": "DzSubDivisionModifier"})
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mod = node.find_modifier("SomeMod")
        self.assertIsInstance(mod, DazModifier)

    def test_find_modifier_returns_daz_morph_when_class_is_dzmorph(self):
        from dazpy._morph import DazMorph
        client = mock_client({"name": "MyMorph", "className": "DzMorph"})
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mod = node.find_modifier("MyMorph")
        self.assertIsInstance(mod, DazMorph)

    def test_find_modifier_returns_none_when_not_found(self):
        client = mock_client(None)
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mod = node.find_modifier("NonExistent")
        self.assertIsNone(mod)

    def test_find_modifier_script_uses_findModifier(self):
        client = mock_client(None)
        node = DazNode(client, NodeIdentifier("Genesis9"))
        node.find_modifier("SomeMod")
        script = client.execute.call_args[0][0]
        self.assertIn("findModifier", script)
        self.assertIn("SomeMod", script)

    def test_morphs_filters_to_only_daz_morph(self):
        from dazpy._morph import DazMorph
        client = mock_client([
            {"name": "SomeMod", "className": "DzSubDivisionModifier"},
            {"name": "MyMorph", "className": "DzMorph"},
            {"name": "OtherMorph", "className": "DzMorph"},
        ])
        node = DazNode(client, NodeIdentifier("Genesis9"))
        morphs = node.morphs()
        self.assertEqual(len(morphs), 2)
        for m in morphs:
            self.assertIsInstance(m, DazMorph)

    def test_modifier_locator_uses_findModifier(self):
        client = mock_client(None)
        node = DazNode(client, NodeIdentifier("Genesis9"))
        loc = node._modifier_locator("MyMorph")
        self.assertIn("findModifier", loc)
        self.assertIn("MyMorph", loc)
        self.assertIn("getObject", loc)

    def test_find_modifier_returns_daz_dforce_when_class_is_dzdforcemodifier(self):
        from dazpy._dforce import DazDForce
        client = mock_client({"name": "MyCloth", "className": "DzDForceModifier"})
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mod = node.find_modifier("MyCloth")
        self.assertIsInstance(mod, DazDForce)

    def test_dforce_modifiers_filters_to_only_dzdforcemodifier(self):
        from dazpy._dforce import DazDForce
        client = mock_client([
            {"name": "SomeMod", "className": "DzSubDivisionModifier"},
            {"name": "MyMorph", "className": "DzMorph"},
            {"name": "MyCloth", "className": "DzDForceModifier"},
        ])
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mods = node.dforce_modifiers()
        self.assertEqual(len(mods), 1)
        self.assertIsInstance(mods[0], DazDForce)


class TestDazDForceScriptGeneration(unittest.TestCase):
    def _make_dforce(self, return_value=None):
        from dazpy._dforce import DazDForce
        client = mock_client(return_value)
        locator = 'Scene.findNode("Genesis9").getObject().findModifier("MyCloth")'
        mod = DazDForce(client, locator)
        return mod, client

    def test_freeze_simulation_getter_calls_findPropertyByLabel(self):
        mod, client = self._make_dforce(True)
        val = mod.freeze_simulation
        self.assertTrue(val)
        script = client.execute.call_args[0][0]
        self.assertIn("findPropertyByLabel", script)
        self.assertIn("Freeze Simulation", script)

    def test_freeze_simulation_setter_calls_setValue(self):
        mod, client = self._make_dforce(None)
        mod.freeze_simulation = True
        script = client.execute.call_args[0][0]
        self.assertIn("setValue", script)
        self.assertIn("true", script)

    def test_freeze_sets_freeze_simulation_true(self):
        mod, client = self._make_dforce(None)
        mod.freeze()
        script = client.execute.call_args[0][0]
        self.assertIn("Freeze Simulation", script)
        self.assertIn("true", script)

    def test_unfreeze_sets_freeze_simulation_false(self):
        mod, client = self._make_dforce(None)
        mod.unfreeze()
        script = client.execute.call_args[0][0]
        self.assertIn("Freeze Simulation", script)
        self.assertIn("false", script)


class TestDazNodeRotationAndSelection(unittest.TestCase):
    def _node(self, return_value=None):
        client = mock_client(return_value)
        return DazNode(client, NodeIdentifier("Genesis9")), client

    def test_set_rotation_uses_axis_controls(self):
        node, client = self._node(None)
        node.set_rotation(10.0, 20.0, 30.0)
        script = client.execute.call_args[0][0]
        self.assertIn("getXRotControl", script)
        self.assertIn("getYRotControl", script)
        self.assertIn("getZRotControl", script)
        self.assertIn("setValue", script)
        self.assertIn("10.0", script)
        self.assertIn("20.0", script)
        self.assertIn("30.0", script)

    def test_set_position_at_frame_converts_frame_to_ticks_and_calls_setWSPos(self):
        node, client = self._node(None)
        node.set_position_at_frame(5, 1.0, 2.0, 3.0)
        script = client.execute.call_args[0][0]
        self.assertIn("Scene.getTimeStep()", script)
        self.assertIn("5 *", script)
        self.assertIn("setWSPos", script)
        self.assertIn("DzVec3", script)
        self.assertIn("1.0", script)
        self.assertIn("2.0", script)
        self.assertIn("3.0", script)

    def test_set_rotation_at_frame_converts_frame_to_ticks_and_uses_axis_controls(self):
        node, client = self._node(None)
        node.set_rotation_at_frame(7, 10.0, 20.0, 30.0)
        script = client.execute.call_args[0][0]
        self.assertIn("Scene.getTimeStep()", script)
        self.assertIn("7 *", script)
        self.assertIn("getXRotControl", script)
        self.assertIn("getYRotControl", script)
        self.assertIn("getZRotControl", script)
        self.assertIn("setDoubleValue", script)
        self.assertIn("10.0", script)
        self.assertIn("20.0", script)
        self.assertIn("30.0", script)

    def test_clear_position_keys_calls_deleteAllKeys_on_all_axes(self):
        node, client = self._node(None)
        node.clear_position_keys()
        script = client.execute.call_args[0][0]
        self.assertIn("getXPosControl", script)
        self.assertIn("getYPosControl", script)
        self.assertIn("getZPosControl", script)
        self.assertEqual(script.count("deleteAllKeys"), 3)

    def test_clear_rotation_keys_calls_deleteAllKeys_on_all_axes(self):
        node, client = self._node(None)
        node.clear_rotation_keys()
        script = client.execute.call_args[0][0]
        self.assertIn("getXRotControl", script)
        self.assertIn("getYRotControl", script)
        self.assertIn("getZRotControl", script)
        self.assertEqual(script.count("deleteAllKeys"), 3)

    def test_local_position_calls_getLocalPos(self):
        node, client = self._node({"x": 1.0, "y": 2.0, "z": 3.0})
        pos = node.local_position
        self.assertEqual(pos["x"], 1.0)
        self.assertEqual(pos["y"], 2.0)
        self.assertEqual(pos["z"], 3.0)
        script = client.execute.call_args[0][0]
        self.assertIn("getLocalPos", script)

    def test_set_local_position_calls_setLocalPos(self):
        node, client = self._node(None)
        node.set_local_position(5.0, 10.0, 15.0)
        script = client.execute.call_args[0][0]
        self.assertIn("setLocalPos", script)
        self.assertIn("DzVec3", script)
        self.assertIn("5.0", script)
        self.assertIn("10.0", script)
        self.assertIn("15.0", script)

    def test_local_rotation_calls_getLocalRot_and_returns_xyzw(self):
        node, client = self._node({"x": 0.0, "y": 0.1, "z": 0.0, "w": 0.995})
        rot = node.local_rotation
        self.assertIn("w", rot)
        self.assertIn("x", rot)
        script = client.execute.call_args[0][0]
        self.assertIn("getLocalRot", script)
        self.assertIn("r.w", script)

    def test_set_local_rotation_uses_axis_controls(self):
        node, client = self._node(None)
        node.set_local_rotation(5.0, 15.0, 25.0)
        script = client.execute.call_args[0][0]
        self.assertIn("getXRotControl", script)
        self.assertIn("getYRotControl", script)
        self.assertIn("getZRotControl", script)
        self.assertIn("setValue", script)
        self.assertIn("5.0", script)
        self.assertIn("15.0", script)
        self.assertIn("25.0", script)

    def test_set_scale_uses_axis_controls(self):
        node, client = self._node(None)
        node.set_scale(1.5, 2.0, 0.5)
        script = client.execute.call_args[0][0]
        self.assertIn("getXScaleControl", script)
        self.assertIn("getYScaleControl", script)
        self.assertIn("getZScaleControl", script)
        self.assertIn("setValue", script)
        self.assertIn("1.5", script)
        self.assertIn("2.0", script)
        self.assertIn("0.5", script)

    def test_is_selected_calls_isSelected(self):
        node, client = self._node(True)
        result = node.is_selected()
        self.assertTrue(result)
        script = client.execute.call_args[0][0]
        self.assertIn("isSelected", script)

    def test_is_selected_returns_false(self):
        node, client = self._node(False)
        result = node.is_selected()
        self.assertFalse(result)

    def test_select_true_calls_select_true(self):
        node, client = self._node(None)
        node.select(True)
        script = client.execute.call_args[0][0]
        self.assertIn("select", script)
        self.assertIn("true", script)

    def test_select_false_calls_select_false(self):
        node, client = self._node(None)
        node.select(False)
        script = client.execute.call_args[0][0]
        self.assertIn("select", script)
        self.assertIn("false", script)

    def test_select_default_is_true(self):
        node, client = self._node(None)
        node.select()
        script = client.execute.call_args[0][0]
        self.assertIn("true", script)


class TestDazNodeAdditionalQueries(unittest.TestCase):
    def _node(self, return_value=None):
        client = mock_client(return_value)
        return DazNode(client, NodeIdentifier("Genesis9")), client

    def test_is_in_scene_calls_isInScene(self):
        node, client = self._node(True)
        result = node.is_in_scene()
        self.assertTrue(result)
        script = client.execute.call_args[0][0]
        self.assertIn("isInScene", script)

    def test_is_in_scene_false(self):
        node, client = self._node(False)
        self.assertFalse(node.is_in_scene())

    def test_is_root_calls_isRootNode(self):
        node, client = self._node(True)
        result = node.is_root()
        self.assertTrue(result)
        script = client.execute.call_args[0][0]
        self.assertIn("isRootNode", script)

    def test_is_root_false(self):
        node, client = self._node(False)
        self.assertFalse(node.is_root())

    def test_is_visible_in_render_calls_isVisibleInRender(self):
        node, client = self._node(True)
        result = node.is_visible_in_render()
        self.assertTrue(result)
        script = client.execute.call_args[0][0]
        self.assertIn("isVisibleInRender", script)

    def test_set_visible_in_render_true(self):
        node, client = self._node(None)
        node.set_visible_in_render(True)
        script = client.execute.call_args[0][0]
        self.assertIn("setVisibleInRender", script)
        self.assertIn("true", script)

    def test_set_visible_in_render_false(self):
        node, client = self._node(None)
        node.set_visible_in_render(False)
        script = client.execute.call_args[0][0]
        self.assertIn("setVisibleInRender", script)
        self.assertIn("false", script)

    def test_is_visible_in_viewport_calls_isVisibleInViewport(self):
        node, client = self._node(False)
        result = node.is_visible_in_viewport()
        self.assertFalse(result)
        script = client.execute.call_args[0][0]
        self.assertIn("isVisibleInViewport", script)

    def test_set_visible_in_viewport_true(self):
        node, client = self._node(None)
        node.set_visible_in_viewport(True)
        script = client.execute.call_args[0][0]
        self.assertIn("setVisibleInViewport", script)
        self.assertIn("true", script)

    def test_set_visible_in_viewport_false(self):
        node, client = self._node(None)
        node.set_visible_in_viewport(False)
        script = client.execute.call_args[0][0]
        self.assertIn("setVisibleInViewport", script)
        self.assertIn("false", script)

    def test_bounding_box_calls_getWSBoundingBox(self):
        bb = {"min": {"x": -1.0, "y": 0.0, "z": -1.0}, "max": {"x": 1.0, "y": 2.0, "z": 1.0}}
        node, client = self._node(bb)
        result = node.bounding_box()
        self.assertEqual(result["min"]["x"], -1.0)
        self.assertEqual(result["max"]["y"], 2.0)
        script = client.execute.call_args[0][0]
        self.assertIn("getWSBoundingBox", script)
        self.assertIn("bb.min.x", script)
        self.assertIn("bb.max.x", script)

    def test_bounding_box_returns_none_when_server_returns_none(self):
        node, client = self._node(None)
        result = node.bounding_box()
        self.assertIsNone(result)


class TestDazNodeDeleteAndReparent(unittest.TestCase):
    def _node(self, return_value=None):
        client = mock_client(return_value)
        return DazNode(client, NodeIdentifier("Prop1")), client

    def test_delete_calls_scene_remove_node(self):
        node, client = self._node(True)
        result = node.delete()
        self.assertTrue(result)
        script = client.execute.call_args[0][0]
        self.assertIn("Scene.removeNode(_node)", script)

    def test_delete_returns_false_when_server_returns_falsy(self):
        node, client = self._node(False)
        self.assertFalse(node.delete())

    def test_reparent_calls_remove_and_add_node_child(self):
        node, client = self._node(None)
        new_parent = DazNode(client, NodeIdentifier("NewParent"))
        node.reparent(new_parent)
        script = client.execute.call_args[0][0]
        self.assertIn("removeNodeChild(_node, true)", script)
        self.assertIn("addNodeChild(_node, true)", script)
        self.assertIn('Scene.findNode("NewParent")', script)
        self.assertIn("_err.valueOf()", script)

    def test_reparent_preserve_world_transform_false_uses_false_flag(self):
        node, client = self._node(None)
        new_parent = DazNode(client, NodeIdentifier("NewParent"))
        node.reparent(new_parent, preserve_world_transform=False)
        script = client.execute.call_args[0][0]
        self.assertIn("removeNodeChild(_node, false)", script)
        self.assertIn("addNodeChild(_node, false)", script)

    def test_reparent_raises_on_error_result(self):
        node, client = self._node("some dz error")
        new_parent = DazNode(client, NodeIdentifier("NewParent"))
        with self.assertRaises(exceptions.ScriptRuntimeError):
            node.reparent(new_parent)

    def test_reparent_succeeds_when_result_is_none(self):
        node, client = self._node(None)
        new_parent = DazNode(client, NodeIdentifier("NewParent"))
        node.reparent(new_parent)  # should not raise


class TestDazNodeFitting(unittest.TestCase):
    def _node(self, return_value=None):
        client = mock_client(return_value)
        return DazNode(client, NodeIdentifier("Outfit")), client

    def test_fit_to_uses_setFollowTarget_when_available(self):
        node, client = self._node("setFollowTarget")
        figure = DazNode(client, NodeIdentifier("Genesis9"))
        method = node.fit_to(figure)
        self.assertEqual(method, "setFollowTarget")
        script = client.execute.call_args[0][0]
        self.assertIn("setFollowTarget(_figure)", script)
        self.assertIn('Scene.findNode("Genesis9")', script)

    def test_fit_to_raises_when_node_not_found(self):
        node, client = self._node(None)
        figure = DazNode(client, NodeIdentifier("Genesis9"))
        with self.assertRaises(exceptions.NodeNotFoundError):
            node.fit_to(figure)

    def test_unfit_returns_previous_figure_and_actions(self):
        node, client = self._node(
            {"previous_figure": "Genesis9", "actions": ["cleared follow target"]}
        )
        result = node.unfit()
        self.assertEqual(result["previous_figure"], "Genesis9")
        self.assertEqual(result["actions"], ["cleared follow target"])
        script = client.execute.call_args[0][0]
        self.assertIn("setFollowTarget(null)", script)
        self.assertIn("removeNodeChild(_node, true)", script)

    def test_unfit_returns_defaults_when_server_returns_none(self):
        node, client = self._node(None)
        result = node.unfit()
        self.assertEqual(result, {"previous_figure": None, "actions": []})

    def test_fitted_items_returns_node_list(self):
        node, client = self._node([
            {"label": "Outfit Top", "name": "Top", "type": "clothing", "element_id": 1},
            {"label": "Hat", "name": "Hat", "type": "prop", "element_id": 2}])
        items = node.fitted_items()
        self.assertEqual(len(items), 2)
        self.assertIsInstance(items[0], DazNode)
        script = client.execute.call_args[0][0]
        self.assertIn("getFollowTarget", script)
        self.assertIn("getNodeParent", script)

    def test_fitted_items_empty_when_none_fitted(self):
        node, client = self._node([])
        self.assertEqual(node.fitted_items(), [])


class TestDazPropertyKeyframes(unittest.TestCase):
    def _prop(self, return_value=None):
        from dazpy._property import DazProperty
        client = mock_client(return_value)
        prop = DazProperty(client, "_node", "XRotate")
        return prop, client

    def test_get_keys_returns_time_value_list(self):
        prop, client = self._prop([{"time": 0, "value": 0.0}, {"time": 30, "value": 45.0}])
        keys = prop.get_keys()
        self.assertEqual(keys, [{"time": 0, "value": 0.0}, {"time": 30, "value": 45.0}])
        script = client.execute.call_args[0][0]
        self.assertIn("getNumKeys", script)
        self.assertIn("getKeyTime", script)
        self.assertIn("getDoubleValue", script)
        self.assertIn("t.valueOf()", script)

    def test_get_keys_empty_when_no_keys(self):
        prop, client = self._prop([])
        self.assertEqual(prop.get_keys(), [])

    def test_set_key_calls_setDoubleValue(self):
        prop, client = self._prop(None)
        prop.set_key(30, 45.0)
        script = client.execute.call_args[0][0]
        self.assertIn("setDoubleValue", script)
        self.assertIn("30", script)
        self.assertIn("45.0", script)
        self.assertNotIn("setKey(", script)

    def test_is_animated_true_when_keys_present(self):
        prop, client = self._prop(True)
        self.assertTrue(prop.is_animated)
        script = client.execute.call_args[0][0]
        self.assertIn("getNumKeys", script)
        self.assertIn("> 0", script)
        self.assertNotIn("isAnimated", script)

    def test_is_animated_false_when_no_keys(self):
        prop, client = self._prop(False)
        self.assertFalse(prop.is_animated)

    def test_remove_key_calls_delete_keys_with_zero_width_time_range(self):
        prop, client = self._prop(None)
        prop.remove_key(30)
        script = client.execute.call_args[0][0]
        self.assertIn("deleteKeys(new DzTimeRange(30, 30))", script)

    def test_clear_keys_calls_delete_all_keys(self):
        prop, client = self._prop(None)
        prop.clear_keys()
        script = client.execute.call_args[0][0]
        self.assertIn("deleteAllKeys", script)


class TestDazElementSnapshot(unittest.TestCase):
    def test_snapshot_issues_exactly_one_call(self):
        client = mock_client({"Smile": 0.8, "Blink": 0.0, "EyesClosed": None})
        from dazpy._element import DazElement
        el = DazElement(client, "Scene.findNode('Fig')")
        result = el.snapshot(["Smile", "Blink", "EyesClosed"])
        self.assertEqual(client.execute.call_count, 1)
        self.assertEqual(result, {"Smile": 0.8, "Blink": 0.0, "EyesClosed": None})

    def test_snapshot_escapes_labels_with_quotes_and_backslashes(self):
        client = mock_client({})
        from dazpy._element import DazElement
        el = DazElement(client, "Scene.findNode('Fig')")
        el.snapshot(['Weird "Label"', "Back\\slash"])
        script = client.execute.call_args[0][0]
        self.assertIn(json.dumps('Weird "Label"'), script)
        self.assertIn(json.dumps("Back\\slash"), script)

    def test_snapshot_missing_owner_returns_none_for_all_fields(self):
        client = mock_client(None)  # script's top-level `if (!obj) return null;`
        from dazpy._element import DazElement
        el = DazElement(client, "Scene.findNode('Missing')")
        result = el.snapshot(["Smile", "Blink"])
        self.assertEqual(result, {"Smile": None, "Blink": None})


class TestDazNodeSetTransform(unittest.TestCase):
    def test_all_components_issue_one_call(self):
        client = mock_client(None)
        from dazpy._node import DazNode, NodeIdentifier
        node = DazNode(client, NodeIdentifier("name", "Camera"))
        node.set_transform(position=(1.0, 2.0, 3.0), rotation=(4.0, 5.0, 6.0), scale=(1.5, 1.5, 1.5))
        self.assertEqual(client.execute.call_count, 1)
        script = client.execute.call_args[0][0]
        self.assertIn("setLocalPos", script)
        self.assertIn("getXRotControl", script)
        self.assertIn("getXScaleControl", script)

    def test_omitted_component_not_present_in_script(self):
        client = mock_client(None)
        from dazpy._node import DazNode, NodeIdentifier
        node = DazNode(client, NodeIdentifier("name", "Camera"))
        node.set_transform(position=(1.0, 2.0, 3.0))
        script = client.execute.call_args[0][0]
        self.assertIn("setLocalPos", script)
        self.assertNotIn("getXRotControl", script)
        self.assertNotIn("getXScaleControl", script)

    def test_no_arguments_is_a_noop(self):
        client = mock_client(None)
        from dazpy._node import DazNode, NodeIdentifier
        node = DazNode(client, NodeIdentifier("name", "Camera"))
        node.set_transform()
        client.execute.assert_not_called()


class TestDazElementSetProperties(unittest.TestCase):
    def test_multiple_mutations_issue_one_call(self):
        client = mock_client({"Smile": True, "Blink": True})
        from dazpy._element import DazElement
        el = DazElement(client, "Scene.findNode('Fig')")
        result = el.set_properties({"Smile": 0.8, "Blink": 0.2})
        self.assertEqual(client.execute.call_count, 1)
        self.assertEqual(result, {"Smile": True, "Blink": True})

    def test_missing_property_reported_false(self):
        client = mock_client({"Smile": True, "Nonexistent": False})
        from dazpy._element import DazElement
        el = DazElement(client, "Scene.findNode('Fig')")
        result = el.set_properties({"Smile": 0.8, "Nonexistent": 1.0})
        self.assertEqual(result, {"Smile": True, "Nonexistent": False})

    def test_labels_with_quotes_backslashes_newlines_are_json_safe(self):
        client = mock_client({})
        from dazpy._element import DazElement
        el = DazElement(client, "Scene.findNode('Fig')")
        el.set_properties({'Weird "Label"': 1, "Multi\nLine": 2, "Back\\Slash": 3})
        script = client.execute.call_args[0][0]
        payload = json.dumps({'Weird "Label"': 1, "Multi\nLine": 2, "Back\\Slash": 3})
        self.assertIn(payload, script)
        self.assertIn("hasOwnProperty", script)


if __name__ == "__main__":
    unittest.main()
