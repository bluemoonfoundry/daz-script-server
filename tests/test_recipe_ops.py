"""Unit tests for dazpy._recipe_ops.DazSceneOps internals (no server needed)."""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from dazpy._recipe_ops import DazSceneOps  # noqa: E402
from dazpy.exceptions import NodeNotFoundError  # noqa: E402

SAVED = {"XPos": 0.0, "YPos": 0.0, "ZPos": 0.0, "XRot": 0.0, "YRot": 15.0, "ZRot": 0.0,
         "XScale": 1.0, "YScale": 1.0, "ZScale": 1.0, "Scale": 1.0}


def _ops(results):
    """DazSceneOps whose client answers execute() with *results* in order and
    records every script it was sent."""
    client = mock.Mock()
    client.execute.side_effect = [SimpleNamespace(value=v) for v in results]
    return DazSceneOps(SimpleNamespace(_client=client)), client


class TestSetTransformWithoutPosition(unittest.TestCase):
    def test_no_position_key_does_not_move_the_node(self):
        ops, _ = _ops([])
        with mock.patch("dazpy._recipe_ops.DazNode") as node_cls:
            ops._set_transform(mock.Mock(), "actor", {"rotation": (0.0, 30.0, 0.0)})
        node_cls.return_value.set_position.assert_not_called()
        node_cls.return_value.set_rotation.assert_called_once_with(0.0, 30.0, 0.0)


class TestPoseKeepsNodeTransform(unittest.TestCase):
    """5d6f.30 item 5: a pose preset can carry a root transform; the pose
    channel must not move the figure node (the transform channel owns it)."""

    def test_preset_pose_is_wrapped_in_read_and_restore(self):
        ops, client = _ops([SAVED, True, True])
        with mock.patch.object(DazSceneOps, "_resolve_asset", return_value="C:/p/pose.duf"):
            ops.set_channels("Genesis 9", "actor", {"pose": {"pose_path": "/Poses/pose.duf"}})
        scripts = [c.args[0] for c in client.execute.call_args_list]
        self.assertEqual(len(scripts), 3)
        self.assertIn("recipe:read-xform", scripts[0])
        self.assertIn("openFile", scripts[1])
        self.assertIn("recipe:write-xform", scripts[2])
        self.assertIn('["YRot", 15.0]', scripts[2])
        self.assertNotIn(" in _v)", scripts[2])  # no for-in: Studio 6 enumerates extra keys

    def test_changed_transform_still_wins_after_the_pose(self):
        ops, client = _ops([SAVED, True, True])
        with mock.patch.object(DazSceneOps, "_resolve_asset", return_value="C:/p/pose.duf"), \
             mock.patch.object(DazSceneOps, "_set_transform") as set_transform:
            set_transform.side_effect = lambda *a: client.execute("// set-transform")
            client.execute.side_effect = [SimpleNamespace(value=v) for v in (SAVED, True, True, None)]
            ops.set_channels("Genesis 9", "actor", {
                "transform": {"position": [10, 0, 0], "rotation": [0, 0, 0]},
                "pose": {"pose_path": "/Poses/pose.duf"},
            })
        scripts = [c.args[0] for c in client.execute.call_args_list]
        self.assertIn("recipe:write-xform", scripts[2])
        self.assertEqual(scripts[3], "// set-transform")

    def test_missing_node_raises_before_posing(self):
        ops, client = _ops([None])
        with self.assertRaises(NodeNotFoundError):
            ops.set_channels("Gone", "actor", {"pose": {"pose_path": "/Poses/pose.duf"}})
        self.assertEqual(client.execute.call_count, 1)



class TestSceneOpsFitting(unittest.TestCase):
    """Task 11: take over, presets, multi-node fit, unfit, restore."""

    @staticmethod
    def _entity():
        from dazpy._recipe_desired import DesiredEntity
        return DesiredEntity(path="items.anna.outfit", kind="item", label="r:anna.outfit",
                             create={"asset_path": "/Outfit.duf", "fit_to": "actors.anna"},
                             channels={})

    def _fit_ops(self, names, fitted, extra=()):
        # resolve, snapshot, load, claim, fit, then cleanup (failure) or settle (success)
        fit_out = {"error": "", "fitted": fitted, "unfitted": [n for n in names if n not in fitted]}
        return _ops([{"/Outfit.duf": "C:/Outfit.duf"}, ["k1"], True, names, fit_out, *(extra or (True,))])

    def test_fit_multi_node_returns_all(self):
        ops, client = self._fit_ops(["Top", "Skirt"], ["Top", "Skirt"])
        self.assertEqual(ops.fit(self._entity(), "Genesis 9"), ["Top", "Skirt"])
        scripts = [c.args[0] for c in client.execute.call_args_list]
        self.assertIn("setFollowTarget", scripts[4])
        self.assertIn("r:anna.outfit", scripts[3])

    def test_fit_stray_node_removes_all(self):
        from dazpy.exceptions import DazError
        ops, client = self._fit_ops(["Top", "Prop"], ["Top"], extra=(1,))
        with self.assertRaises(DazError) as cm:
            ops.fit(self._entity(), "Genesis 9")
        self.assertIn("not fitted to Genesis 9: Prop", str(cm.exception))
        self.assertIn("every node it added was removed", str(cm.exception))
        last = client.execute.call_args_list[-1].args[0]
        self.assertIn("recipe:cleanup", last)

    def test_fit_loads_with_selection_cleared_and_never_removes_node(self):
        ops, client = self._fit_ops(["Top"], ["Top"])
        ops.fit(self._entity(), "Genesis 9")
        scripts = [c.args[0] for c in client.execute.call_args_list]
        load = next(s for s in scripts if "recipe:load" in s)
        self.assertLess(load.index("selectAllNodes(false)"), load.index("loadScene"))
        for s in scripts:
            self.assertNotIn("Scene.removeNode", s)

    def test_unfit_single_delete(self):
        ops, client = _ops([[]])
        ops.unfit(["Top", "Skirt"])
        self.assertEqual(client.execute.call_count, 1)
        script = client.execute.call_args.args[0]
        self.assertIn("DzDeleteAction", script)
        self.assertIn('["Top", "Skirt"]', script)
        self.assertNotIn("Scene.removeNode", script)

    def test_unfit_checked_refuses_foreign_descendant(self):
        from dazpy._recipe_store import EntityRecord
        from dazpy.exceptions import DazError
        mine = EntityRecord("r1", "actors.a.wearing.h", 2, {}, {}, native=("HairMesh",)).to_json()
        clean = {"record": mine, "children": [
            {"name": "HairMesh", "record": None, "bone": False, "children": []}]}
        dirty = {"record": mine, "children": [
            {"name": "Bow", "record": None, "bone": False, "children": []}]}
        ops, client = _ops([clean, dirty])
        with self.assertRaisesRegex(DazError, "Bow"):
            ops.unfit(["Hair", "Cap"], owner_recipe="r1")
        scripts = [c.args[0] for c in client.execute.call_args_list]
        self.assertFalse(any("DzDeleteAction" in s for s in scripts))  # nothing deleted
        ops, client = _ops([clean, clean, []])
        ops.unfit(["Hair", "Cap"], owner_recipe="r1")
        self.assertIn("DzDeleteAction", client.execute.call_args.args[0])

    def test_apply_presets_order_and_selection_restore(self):
        ops, client = _ops([{"/a.duf": "C:/a.duf"}, True, {"/b.duf": "C:/b.duf"}, True])
        ops.apply_presets("Genesis 9", ["/a.duf", "/b.duf"])
        scripts = [c.args[0] for c in client.execute.call_args_list]
        opens = [s for s in scripts if "openFile" in s]
        self.assertEqual(len(opens), 2)
        self.assertIn("C:/a.duf", opens[0])
        self.assertIn("C:/b.duf", opens[1])
        for s in opens:
            self.assertIn("setPrimarySelection(_prev)", s)

    def test_take_over_validates_node(self):
        ops, client = _ops([True])
        ops.take_over("Genesis 9")
        self.assertEqual(client.execute.call_count, 1)
        ops, _ = _ops([False])
        with self.assertRaises(NodeNotFoundError):
            ops.take_over("Nope")

    def test_restore_reloads_and_fits_each_source(self):
        fit = {"error": "", "fitted": ["Top"], "unfitted": []}
        ops, client = _ops([{"/o.duf": "C:/o.duf"}, ["k"], True, ["Top"], fit, True])
        self.assertEqual(ops.restore(["/o.duf"], "Genesis 9"), ["Top"])
        claim = client.execute.call_args_list[3].args[0]
        self.assertNotIn("setLabel", claim)


class TestDs4ProbeFindings(unittest.TestCase):
    """Task 1b: DS4 live-probe findings applied to the Studio scripts (spec 15)."""

    def test_node_key_uses_element_id_property(self):
        # DS4 has no getElementID(); elementID is a numeric property.  A name key
        # would hide every node of a second load of the same file.
        from dazpy._recipe_ops import _KEY_JS, _SNAPSHOT_SCRIPT
        self.assertIn("n.elementID !== undefined", _KEY_JS)
        self.assertIn("String(n.elementID)", _KEY_JS)
        self.assertIn('typeof n.getElementID === "function"', _KEY_JS)
        self.assertIn("return n.getName();", _KEY_JS)   # last-resort fallback
        self.assertIn("n.elementID", _SNAPSHOT_SCRIPT)

    def _entity(self):
        from dazpy._recipe_desired import DesiredEntity
        return DesiredEntity(path="items.anna.outfit", kind="item", label="r:anna.outfit",
                             create={"asset_path": "/Outfit.duf", "fit_to": "actors.anna"},
                             channels={})

    def test_calls_after_the_load_retry_while_studio_is_busy(self):
        fit_out = {"error": "", "fitted": ["Top"], "unfitted": []}
        ops, client = _ops([{"/Outfit.duf": "C:/Outfit.duf"}, ["k1"], True, ["Top"], fit_out, True])
        ops.fit(self._entity(), "Genesis 9")
        calls = client.execute.call_args_list
        by_tag = {tag: c for c in calls for tag in ("recipe:claim", "recipe:fit", "recipe:load")
                  if tag in c.args[0]}
        self.assertTrue(by_tag["recipe:claim"].kwargs.get("retry_on_busy"))
        self.assertTrue(by_tag["recipe:fit"].kwargs.get("retry_on_busy"))
        # the load itself is not retried: a busy reply there means it did not run
        self.assertFalse(by_tag["recipe:load"].kwargs.get("retry_on_busy", False))

    def test_fit_waits_out_busy_before_returning(self):
        # DS4: Studio answers busy for a while after a fit returns, so the next
        # operation's first call would fail; the fit settles before returning.
        fit_out = {"error": "", "fitted": ["Top"], "unfitted": []}
        ops, client = _ops([{"/Outfit.duf": "C:/Outfit.duf"}, ["k1"], True, ["Top"], fit_out, True])
        self.assertEqual(ops.fit(self._entity(), "Genesis 9"), ["Top"])
        last = client.execute.call_args_list[-1]
        self.assertIn("recipe:settle", last.args[0])
        self.assertTrue(last.kwargs.get("retry_on_busy"))

    def test_cleanup_after_a_failed_fit_retries_while_busy(self):
        from dazpy.exceptions import DazError
        fit_out = {"error": "", "fitted": ["Top"], "unfitted": ["Prop"]}
        ops, client = _ops([{"/Outfit.duf": "C:/Outfit.duf"}, ["k1"], True, ["Top", "Prop"],
                            fit_out, 1])
        with self.assertRaises(DazError):
            ops.fit(self._entity(), "Genesis 9")
        last = client.execute.call_args_list[-1]
        self.assertIn("recipe:cleanup", last.args[0])
        self.assertTrue(last.kwargs.get("retry_on_busy"))

    def test_apply_presets_clears_selection_first(self):
        ops, client = _ops([{"/a.duf": "C:/a.duf"}, True])
        ops.apply_presets("Genesis 9", ["/a.duf"])
        js = next(c.args[0] for c in client.execute.call_args_list if "openFile" in c.args[0])
        self.assertLess(js.index("Scene.selectAllNodes(false)"), js.index("setPrimarySelection(_node)"))
        self.assertIn("getSelectedNodeList()", js)   # the previous selection is restored

    def test_pose_preset_selection_handling_unchanged(self):
        # v1 pose channel: same script as before (no selection clearing)
        from dazpy._recipe_ops import _pose_preset_script
        js = _pose_preset_script("Genesis 9", "C:/p.duf")
        self.assertNotIn("selectAllNodes", js)
        self.assertIn("setPrimarySelection(_prev)", js)

    def test_asset_uris_script_is_read_only(self):
        ops, client = _ops([{"Top": "/data/x/Top.dsf", "Gone": ""}])
        self.assertEqual(ops.asset_uris(["Top", "Gone"]), {"Top": "/data/x/Top.dsf"})
        js = client.execute.call_args.args[0]
        self.assertIn("getAssetUriForNode", js)
        self.assertIn('indexOf("#")', js)
        for bad in ("loadScene", "openFile", "setFollowTarget", "removeNode", "DzDeleteAction"):
            self.assertNotIn(bad, js)


if __name__ == "__main__":
    unittest.main()
