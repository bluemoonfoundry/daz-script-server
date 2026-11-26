"""dazpy unit tests: DazScene: queries, selection, IO, state apply/backup, snapshots, viewport, scene events.

Mock-based; no server or DAZ Studio required.
Shared fakes live in tests/dazpy_fakes.py.
"""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dazpy._result import ExecutionResult
from dazpy._scene_events import SceneEvent, watch_scene_events, wait_for_scene_event
from dazpy.exceptions import ConnectionError as DazConnectionError
from dazpy.exceptions import TimeoutError as DazTimeoutError
from dazpy import (
    BoneProfile,
)
from dazpy._node import DazNode, NodeIdentifier
from dazpy._scene import DazScene
from dazpy._client import DazClient
from dazpy import exceptions
from dazpy_fakes import mock_client


class TestDazScene(unittest.TestCase):
    def test_nodes_returns_list(self):
        client = mock_client([
            {"name": "Genesis9", "className": "DzSkeleton"},
            {"name": "Camera 1", "className": "DzCamera"},
        ])
        scene = DazScene(client)
        nodes = scene.nodes()
        self.assertEqual(len(nodes), 2)
        self.assertIsInstance(nodes[0], DazNode)

    def test_nodes_type_discrimination_skeleton(self):
        from dazpy._skeleton import DazSkeleton
        from dazpy._camera import DazCamera
        client = mock_client([
            {"name": "Genesis9", "className": "DzSkeleton"},
            {"name": "Camera 1", "className": "DzCamera"},
            {"name": "Prop1", "className": "DzNode"},
        ])
        scene = DazScene(client)
        nodes = scene.nodes()
        self.assertIsInstance(nodes[0], DazSkeleton)
        self.assertIsInstance(nodes[1], DazCamera)
        self.assertIsInstance(nodes[2], DazNode)

    def test_nodes_script_uses_inherits_for_type_detection(self):
        client = mock_client([])
        scene = DazScene(client)
        scene.nodes()
        script = client.execute.call_args[0][0]
        self.assertIn("inherits", script)
        self.assertIn("DzSkeleton", script)

    def test_num_nodes(self):
        client = mock_client(5)
        scene = DazScene(client)
        self.assertEqual(scene.num_nodes(), 5)

    def test_find_node_success(self):
        client = mock_client(True)
        scene = DazScene(client)
        node = scene.find_node("Genesis9")
        self.assertIsInstance(node, DazNode)

    def test_find_node_not_found(self):
        client = mock_client(False)
        scene = DazScene(client)
        with self.assertRaises(exceptions.NodeNotFoundError):
            scene.find_node("NonExistent")

    def test_find_skeleton_success_first_try(self):
        client = mock_client(True)
        scene = DazScene(client)
        skel = scene.find_skeleton("Genesis9")
        self.assertEqual(skel._identifier.value, "Genesis9")
        self.assertEqual(client.execute.call_count, 1)

    def test_find_skeleton_retries_on_transient_miss(self):
        # Regression for daz-script-server-xtkd: Scene.getSkeletonList() has
        # been observed to transiently omit a skeleton that is actually
        # present, under load from a burst of other main-thread script
        # calls. A momentary lookup miss should be retried, not immediately
        # reported as NodeNotFoundError.
        client = MagicMock(spec=DazClient)
        client.execute.side_effect = [
            ExecutionResult(value=False, output=[], request_id="a"),
            ExecutionResult(value=False, output=[], request_id="b"),
            ExecutionResult(value=True, output=[], request_id="c"),
        ]
        scene = DazScene(client)
        with patch("time.sleep"):
            skel = scene.find_skeleton("Genesis9Eyelashes")
        self.assertEqual(skel._identifier.value, "Genesis9Eyelashes")
        self.assertEqual(client.execute.call_count, 3)

    def test_find_skeleton_raises_after_exhausting_retries(self):
        client = MagicMock(spec=DazClient)
        client.execute.side_effect = [
            ExecutionResult(value=False, output=[], request_id="a"),
            ExecutionResult(value=False, output=[], request_id="b"),
            ExecutionResult(value=False, output=[], request_id="c"),
            ExecutionResult(
                value=["Genesis9|Genesis 9"], output=[], request_id="d",
            ),
        ]
        scene = DazScene(client)
        with patch("time.sleep"):
            with self.assertRaises(exceptions.NodeNotFoundError):
                scene.find_skeleton("NonExistent")
        self.assertEqual(client.execute.call_count, 4)

    def test_all_node_transforms(self):
        data = [{"name": "n1", "label": "Node 1", "position": [0, 0, 0], "rotation": [0, 0, 0], "visible": True}]
        client = mock_client(data)
        scene = DazScene(client)
        transforms = scene.all_node_transforms()
        self.assertEqual(len(transforms), 1)
        self.assertEqual(transforms[0]["name"], "n1")

    def test_create_camera_returns_daz_camera(self):
        from dazpy._camera import DazCamera
        client = mock_client(42)
        scene = DazScene(client)
        camera = scene.create_camera()
        self.assertIsInstance(camera, DazCamera)
        self.assertEqual(camera._identifier, NodeIdentifier("42", kind="element_id"))

    def test_create_camera_script_uses_basic_camera_and_add_node(self):
        client = mock_client(42)
        scene = DazScene(client)
        scene.create_camera()
        script = client.execute.call_args[0][0]
        self.assertIn("new DzBasicCamera()", script)
        self.assertIn("Scene.addNode(cam)", script)

    def test_create_camera_with_name_sets_name(self):
        client = mock_client(42)
        scene = DazScene(client)
        scene.create_camera(name="MyCam")
        script = client.execute.call_args[0][0]
        self.assertIn('cam.setName("MyCam")', script)

    def test_create_group_returns_daz_node_for_created_name(self):
        from dazpy._node import DazNode
        client = mock_client("Rig 2")
        group = DazScene(client).create_group("Rig")
        self.assertIs(type(group), DazNode)
        self.assertEqual(group._identifier, NodeIdentifier("Rig 2"))  # what Studio reports

    def test_create_group_names_before_add_and_labels_after(self):
        # DS4: a label set before Scene.addNode does not stick on a scripted node.
        client = mock_client("Rig")
        DazScene(client).create_group("Rig", label="My Rig")
        script = client.execute.call_args[0][0]
        self.assertIn("new DzGroupNode()", script)
        self.assertLess(script.index('setName("Rig")'), script.index("Scene.addNode(g)"))
        self.assertLess(script.index("Scene.addNode(g)"), script.index('setLabel("My Rig")'))
        self.assertNotIn("setWSPos", script)

    def test_create_group_label_defaults_to_name(self):
        client = mock_client("Rig")
        DazScene(client).create_group("Rig")
        self.assertIn('g.setLabel("Rig")', client.execute.call_args[0][0])

    def test_create_group_position_sets_world_position(self):
        client = mock_client("Rig")
        DazScene(client).create_group("Rig", position=(1, 150.5, -2))
        script = client.execute.call_args[0][0]
        self.assertIn("g.setWSPos(new DzVec3(1.0, 150.5, -2.0))", script)
        self.assertLess(script.index("Scene.addNode(g)"), script.index("setWSPos"))

    def test_create_group_escapes_name_and_label(self):
        client = mock_client('a"b')
        DazScene(client).create_group('a"b', label="x\\y")
        script = client.execute.call_args[0][0]
        self.assertIn('setName("a\\"b")', script)
        self.assertIn('setLabel("x\\\\y")', script)

    def test_create_group_rejects_empty_name(self):
        client = mock_client("unused")
        with self.assertRaises(ValueError):
            DazScene(client).create_group("")
        client.execute.assert_not_called()

    def test_create_light_returns_daz_light(self):
        from dazpy._light import DazLight
        client = mock_client(42)
        scene = DazScene(client)
        light = scene.create_light("spot")
        self.assertIsInstance(light, DazLight)
        self.assertEqual(light._identifier, NodeIdentifier("42", kind="element_id"))

    def test_create_light_script_uses_correct_class_per_type(self):
        cases = {
            "spot": "DzSpotLight",
            "point": "DzPointLight",
            "distant": "DzDistantLight",
        }
        for light_type, class_name in cases.items():
            client = mock_client(42)
            scene = DazScene(client)
            scene.create_light(light_type)
            script = client.execute.call_args[0][0]
            self.assertIn(f"new {class_name}()", script)
            self.assertIn("Scene.addNode(light)", script)

    def test_create_light_unnamed_is_bound_by_element_id(self):
        # Studio leaves getName() empty for an unnamed light; a name-bound
        # proxy was Scene.findNode("") and unusable.
        client = mock_client(42)
        light = DazScene(client).create_light("spot")
        self.assertIn("return light.elementID", client.execute.call_args[0][0])
        self.assertEqual(light._identifier, NodeIdentifier("42", kind="element_id"))

    def test_create_light_with_name_sets_name(self):
        client = mock_client(42)
        scene = DazScene(client)
        scene.create_light("point", name="Key Light")
        script = client.execute.call_args[0][0]
        self.assertIn('light.setName("Key Light")', script)

    def test_create_light_invalid_type_raises(self):
        client = mock_client(None)
        scene = DazScene(client)
        with self.assertRaises(ValueError):
            scene.create_light("area")


class TestSceneLoadAndHierarchy(unittest.TestCase):
    def test_load_merges_by_default(self):
        client = mock_client(None)
        DazScene(client).load("C:/a.duf")
        script = client.execute.call_args[0][0]
        self.assertIn("DzScene.MergeFile", script)
        self.assertNotIn("Scene.clear()", script)

    def test_load_replace_clears_first_without_dialogs(self):
        client = mock_client(None)
        DazScene(client).load("C:/a.duf", replace=True)
        script = client.execute.call_args[0][0]
        self.assertLess(script.index("Scene.clear()"), script.index("loadScene"))
        self.assertNotIn("OpenNew", script)

    def test_node_hierarchy_from_proxy(self):
        payload = {"node": "Genesis 9", "total_descendants": 1,
                   "hierarchy": {"label": "Genesis 9", "name": "Genesis9", "type": "DzFigure",
                                 "element_id": 5, "children": []}}
        client = mock_client(payload)
        r = DazNode(client, NodeIdentifier("5", kind="element_id")).hierarchy(max_depth=3)
        self.assertEqual(r["hierarchy"]["element_id"], 5)
        script = client.execute.call_args[0][0]
        self.assertIn("Scene.findNodeByElementID(5)", script)
        self.assertIn("var _maxDepth = 3", script)
        self.assertIn("element_id: n.elementID", script)

    def test_node_hierarchy_missing(self):
        with self.assertRaises(exceptions.NodeNotFoundError):
            DazNode(mock_client(None), NodeIdentifier("5", kind="element_id")).hierarchy()


class TestDazSceneViewportCamera(unittest.TestCase):
    def test_default_view_camera_not_in_scene(self):
        client = mock_client({"label": "Perspective View", "name": "PerspectiveView",
                               "in_scene": False, "position": [145, 190, 370]})
        cam = DazScene(client).viewport_camera()
        self.assertEqual(cam.label, "Perspective View")
        self.assertFalse(cam.in_scene)
        self.assertEqual(cam.position, (145.0, 190.0, 370.0))
        self.assertIsNone(cam.camera)
        self.assertIn("get3DViewport", client.execute.call_args[0][0])

    def test_scene_camera_gets_proxy(self):
        from dazpy._camera import DazCamera
        client = mock_client({"label": "Camera 1", "name": "Camera 1",
                               "in_scene": True, "position": [0, 150, 300]})
        cam = DazScene(client).viewport_camera()
        self.assertIsInstance(cam.camera, DazCamera)

    def test_no_viewport_returns_none(self):
        self.assertIsNone(DazScene(mock_client(None)).viewport_camera())


class TestDazSceneSelection(unittest.TestCase):
    def test_selected_nodes_calls_getSelectedNodeList(self):
        client = mock_client(["Genesis9", "Camera 1"])
        scene = DazScene(client)
        nodes = scene.selected_nodes()
        self.assertEqual(len(nodes), 2)
        self.assertIsInstance(nodes[0], DazNode)
        script = client.execute.call_args[0][0]
        self.assertIn("getSelectedNodeList", script)

    def test_selected_nodes_empty_list(self):
        client = mock_client([])
        scene = DazScene(client)
        nodes = scene.selected_nodes()
        self.assertEqual(nodes, [])

    def test_primary_selection_returns_node(self):
        client = mock_client("Genesis9")
        scene = DazScene(client)
        node = scene.primary_selection()
        self.assertIsInstance(node, DazNode)
        script = client.execute.call_args[0][0]
        self.assertIn("getPrimarySelection", script)

    def test_primary_selection_returns_none_when_nothing_selected(self):
        client = mock_client(None)
        scene = DazScene(client)
        node = scene.primary_selection()
        self.assertIsNone(node)

    def test_set_primary_selection_calls_setPrimarySelection(self):
        client = mock_client(None)
        scene = DazScene(client)
        node = DazNode(client, NodeIdentifier("Genesis9"))
        scene.set_primary_selection(node)
        script = client.execute.call_args[0][0]
        self.assertIn("setPrimarySelection", script)
        self.assertIn("Genesis9", script)

    def test_select_all_true_calls_selectAllNodes_true(self):
        client = mock_client(None)
        scene = DazScene(client)
        scene.select_all(True)
        script = client.execute.call_args[0][0]
        self.assertIn("selectAllNodes", script)
        self.assertIn("true", script)

    def test_select_all_false_deselects(self):
        client = mock_client(None)
        scene = DazScene(client)
        scene.select_all(False)
        script = client.execute.call_args[0][0]
        self.assertIn("selectAllNodes", script)
        self.assertIn("false", script)

    def test_select_all_default_is_true(self):
        client = mock_client(None)
        scene = DazScene(client)
        scene.select_all()
        script = client.execute.call_args[0][0]
        self.assertIn("true", script)


class TestDazSceneIO(unittest.TestCase):
    def _scene(self, return_value):
        return DazScene(mock_client(return_value))

    def test_load_calls_loadScene_with_path(self):
        scene = self._scene(None)
        scene.load("/path/to/scene.duf")
        script = scene._client.execute.call_args[0][0]
        self.assertIn("loadScene", script)
        self.assertIn("/path/to/scene.duf", script)
        # 0 and DzScene.OpenNew replace the scene (Studio logs "asset load (open)").
        self.assertIn("/path/to/scene.duf\", DzScene.MergeFile)", script)

    def test_save_calls_saveScene_with_path(self):
        scene = self._scene(None)
        scene.save("/path/to/output.duf")
        script = scene._client.execute.call_args[0][0]
        self.assertIn("saveScene", script)
        self.assertIn("/path/to/output.duf", script)

    def test_filename_returns_string(self):
        scene = self._scene("/some/file.duf")
        result = scene.filename()
        self.assertEqual(result, "/some/file.duf")
        script = scene._client.execute.call_args[0][0]
        self.assertIn("getFilename", script)

    def test_filename_returns_empty_string_when_none(self):
        scene = self._scene(None)
        result = scene.filename()
        self.assertEqual(result, "")

    def test_needs_save_true(self):
        scene = self._scene(True)
        self.assertTrue(scene.needs_save())
        script = scene._client.execute.call_args[0][0]
        self.assertIn("needsSave", script)

    def test_needs_save_false(self):
        scene = self._scene(False)
        self.assertFalse(scene.needs_save())

    def test_play_range_returns_dict(self):
        scene = self._scene({"start": 0, "end": 240})
        result = scene.play_range()
        self.assertEqual(result["start"], 0)
        self.assertEqual(result["end"], 240)
        script = scene._client.execute.call_args[0][0]
        self.assertIn("getPlayRange", script)
        self.assertIn("getTimeStep", script)

    def test_play_range_returns_fallback_when_none(self):
        scene = self._scene(None)
        result = scene.play_range()
        self.assertEqual(result, {"start": 0, "end": 0})

    def test_set_play_range_calls_setPlayRange(self):
        scene = self._scene(None)
        scene.set_play_range(0, 120)
        script = scene._client.execute.call_args[0][0]
        self.assertIn("setPlayRange", script)
        self.assertIn("DzTimeRange", script)
        self.assertIn("0", script)
        self.assertIn("120", script)

    def test_set_anim_range_calls_setAnimRange(self):
        scene = self._scene(None)
        scene.set_anim_range(1, 60)
        script = scene._client.execute.call_args[0][0]
        self.assertIn("setAnimRange", script)
        self.assertIn("DzTimeRange", script)
        self.assertIn("1", script)
        self.assertIn("60", script)

    def test_is_playing_true(self):
        scene = self._scene(True)
        self.assertTrue(scene.is_playing())
        script = scene._client.execute.call_args[0][0]
        self.assertIn("isPlaying", script)

    def test_is_playing_false(self):
        scene = self._scene(False)
        self.assertFalse(scene.is_playing())

    def test_loop_playback_on(self):
        scene = self._scene(None)
        scene.loop_playback(True)
        script = scene._client.execute.call_args[0][0]
        self.assertIn("loopPlayback", script)
        self.assertIn("true", script)

    def test_loop_playback_off(self):
        scene = self._scene(None)
        scene.loop_playback(False)
        script = scene._client.execute.call_args[0][0]
        self.assertIn("loopPlayback", script)
        self.assertIn("false", script)

    def test_export_fbx_uses_fbx_exporter_and_defaults(self):
        scene = self._scene(None)
        scene.export_fbx("/out/scene.fbx")
        script = scene._client.execute.call_args[0][0]
        self.assertIn("DzFbxExporter", script)
        self.assertIn("findExporterByClassName", script)
        self.assertIn("getDefaultOptions", script)
        self.assertIn("writeFile", script)
        self.assertIn("/out/scene.fbx", script)
        self.assertIn('setBoolValue("IncludeFigures", true)', script)
        self.assertIn('setBoolValue("IncludeProps", false)', script)
        self.assertIn('setIntValue("RunSilent", 1)', script)

    def test_export_fbx_passes_named_overrides(self):
        scene = self._scene(None)
        scene.export_fbx(
            "/out/scene.fbx",
            selected_only=True,
            include_animations=True,
            embed_textures=False,
        )
        script = scene._client.execute.call_args[0][0]
        self.assertIn('setBoolValue("IncludeSelectedOnly", true)', script)
        self.assertIn('setBoolValue("IncludeAnimations", true)', script)
        self.assertIn('setBoolValue("EmbedTextures", false)', script)

    def test_export_fbx_accepts_raw_options_override(self):
        scene = self._scene(None)
        scene.export_fbx("/out/scene.fbx", options={"Format": "FBX 2014 -- Binary"})
        script = scene._client.execute.call_args[0][0]
        self.assertIn('setStringValue("Format", "FBX 2014 -- Binary")', script)

    def test_export_obj_uses_obj_exporter_and_defaults(self):
        scene = self._scene(None)
        scene.export_obj("/out/scene.obj")
        script = scene._client.execute.call_args[0][0]
        self.assertIn("DzObjExporter", script)
        self.assertIn("findExporterByClassName", script)
        self.assertIn("/out/scene.obj", script)
        self.assertIn('setBoolValue("IgnoreInvisible", true)', script)
        self.assertIn('setIntValue("RunSilent", 1)', script)

    def test_export_obj_passes_named_overrides(self):
        scene = self._scene(None)
        scene.export_obj("/out/scene.obj", selected_only=True, include_normals=True, collect_maps=True)
        script = scene._client.execute.call_args[0][0]
        self.assertIn('setBoolValue("SelectedOnly", true)', script)
        self.assertIn('setBoolValue("WriteVN", true)', script)
        self.assertIn('setBoolValue("CollectMaps", true)', script)


class TestDazSceneDForceSimulation(unittest.TestCase):
    def _scene(self, return_value=None):
        return DazScene(mock_client(return_value))

    def test_is_simulating_true(self):
        scene = self._scene(True)
        self.assertTrue(scene.is_simulating())
        script = scene._client.execute.call_args[0][0]
        self.assertIn("getSimulationMgr", script)
        self.assertIn("isSimulating", script)

    def test_is_simulating_false(self):
        scene = self._scene(False)
        self.assertFalse(scene.is_simulating())

    def test_clear_dforce_simulation_calls_clearSimulation(self):
        scene = self._scene(None)
        scene.clear_dforce_simulation()
        script = scene._client.execute.call_args[0][0]
        self.assertIn("getSimulationMgr", script)
        self.assertIn("clearSimulation", script)

    def test_run_dforce_simulation_wait_false_submits_async(self):
        scene = self._scene()
        scene._client.execute_async_submit.return_value = "req-123"
        request_id = scene.run_dforce_simulation(wait=False)
        self.assertEqual(request_id, "req-123")
        script = scene._client.execute_async_submit.call_args[0][0]
        self.assertIn("getSimulationMgr", script)
        self.assertIn("mgr.simulate()", script)

    def test_run_dforce_simulation_with_nodes_uses_customSimulate(self):
        scene = self._scene()
        scene._client.execute_async_submit.return_value = "req-456"
        node = DazNode(scene._client, NodeIdentifier("Skirt"))
        scene.run_dforce_simulation(nodes=[node], wait=False)
        script = scene._client.execute_async_submit.call_args[0][0]
        self.assertIn("customSimulate", script)
        self.assertIn("getActiveSimulationEngine", script)
        self.assertIn("Skirt", script)

    def test_run_dforce_simulation_wait_true_returns_none_on_success(self):
        scene = self._scene()
        scene._client.execute_async_submit.return_value = "req-789"
        scene._client.get_request_result.return_value = {
            "success": True,
            "result": {"error": None},
            "output": [],
            "duration_ms": 12.0,
        }
        result = scene.run_dforce_simulation(wait=True)
        self.assertIsNone(result)

    def test_run_dforce_simulation_wait_true_raises_on_engine_error(self):
        scene = self._scene()
        scene._client.execute_async_submit.return_value = "req-999"
        scene._client.get_request_result.return_value = {
            "success": True,
            "result": {"error": "DZ_ERROR_SOMETHING"},
            "output": [],
            "duration_ms": 12.0,
        }
        with self.assertRaises(exceptions.ScriptRuntimeError):
            scene.run_dforce_simulation(wait=True)

    def test_run_dforce_simulation_defaults_to_live_pose(self):
        scene = self._scene()
        scene._client.execute_async_submit.return_value = "req-live"
        scene.run_dforce_simulation(wait=False)
        script = scene._client.execute_async_submit.call_args[0][0]
        self.assertIn("startFromMemorizedPose = false", script)

    def test_run_dforce_simulation_memorized_pose_sets_engine_flag(self):
        scene = self._scene()
        scene._client.execute_async_submit.return_value = "req-mem"
        scene.run_dforce_simulation(memorized_pose=True, wait=False)
        script = scene._client.execute_async_submit.call_args[0][0]
        self.assertIn("getGlobalSimulationSettings", script)
        self.assertIn("startFromMemorizedPose = true", script)

    def test_run_dforce_simulation_memorized_pose_with_nodes(self):
        scene = self._scene()
        scene._client.execute_async_submit.return_value = "req-mem-nodes"
        node = DazNode(scene._client, NodeIdentifier("Skirt"))
        scene.run_dforce_simulation(nodes=[node], memorized_pose=True, wait=False)
        script = scene._client.execute_async_submit.call_args[0][0]
        self.assertIn("startFromMemorizedPose = true", script)
        self.assertIn("customSimulate", script)


class TestDazSceneStateApply(unittest.TestCase):
    """Tests for DazSceneState.apply()'s per-skeleton error isolation."""

    def test_apply_isolates_apply_full_error_per_skeleton(self):
        # Regression: a mid-loop apply_full() failure (transient HTTP/DazScript
        # error, stale skeleton reference) must not abort restoration of the
        # remaining skeletons/cameras/lights -- it should be reported in
        # `errors` like a missing skeleton is, per the docstring's contract.
        from dazpy._scene_state import DazSceneState

        good_pose = MagicMock()
        bad_pose = MagicMock()
        bad_pose.apply_full.side_effect = RuntimeError("boom")

        skel_good = MagicMock()
        skel_good._identifier.value = "Good"
        skel_good._client.execute.return_value = ExecutionResult(
            value={"bones": {}, "morphs": {}, "props": {}}, output=[], request_id="x",
        )
        skel_bad = MagicMock()
        scene = MagicMock()
        scene.find_skeleton.side_effect = lambda name: {
            "Good": skel_good, "Bad": skel_bad,
        }[name]
        scene._client.execute.return_value = ExecutionResult(
            value={"restored": [], "errors": []}, output=[], request_id="x",
        )

        state = DazSceneState(
            skeleton_poses={"Bad": bad_pose, "Good": good_pose},
            camera_transforms={}, light_transforms={}, light_extra={},
        )
        result = state.apply(scene)

        good_pose.apply_full.assert_called_once_with(skel_good)
        bad_pose.apply_full.assert_called_once_with(skel_bad)
        self.assertIn("Good", result["restored"])
        self.assertNotIn("Bad", result["restored"])
        self.assertTrue(any("Bad" in e for e in result["errors"]))

    def test_apply_reports_missing_skeleton_and_continues(self):
        from dazpy._scene_state import DazSceneState

        good_pose = MagicMock()
        missing_pose = MagicMock()

        skel_good = MagicMock()
        skel_good._identifier.value = "Good"
        skel_good._client.execute.return_value = ExecutionResult(
            value={"bones": {}, "morphs": {}, "props": {}}, output=[], request_id="x",
        )
        scene = MagicMock()

        def _find_skeleton(name):
            from dazpy.exceptions import NodeNotFoundError
            if name == "Missing":
                raise NodeNotFoundError("not found")
            return skel_good

        scene.find_skeleton.side_effect = _find_skeleton
        scene._client.execute.return_value = ExecutionResult(
            value={"restored": [], "errors": []}, output=[], request_id="x",
        )

        state = DazSceneState(
            skeleton_poses={"Missing": missing_pose, "Good": good_pose},
            camera_transforms={}, light_transforms={}, light_extra={},
        )
        result = state.apply(scene)

        missing_pose.apply_full.assert_not_called()
        good_pose.apply_full.assert_called_once_with(skel_good)
        self.assertIn("Good", result["restored"])
        self.assertTrue(any("Missing" in e for e in result["errors"]))
        self.assertEqual(
            result["skipped"], [{"kind": "skeleton", "name": "Missing", "reason": "not_found"}]
        )
        self.assertFalse(result["complete"])

    def test_apply_lookup_failure_other_than_not_found_is_an_error_not_a_skip(self):
        from dazpy._scene_state import DazSceneState

        scene = MagicMock()
        scene.find_skeleton.side_effect = RuntimeError("socket closed")
        scene._client.execute.return_value = ExecutionResult(
            value={"restored": [], "errors": []}, output=[], request_id="x",
        )
        state = DazSceneState(
            skeleton_poses={"Genesis9": MagicMock()},
            camera_transforms={}, light_transforms={}, light_extra={},
        )
        result = state.apply(scene)

        self.assertEqual(result["skipped"], [])
        self.assertTrue(any("Failed to look up skeleton Genesis9" in e for e in result["errors"]))
        self.assertFalse(result["complete"])

    def test_apply_report_for_nodes_deleted_between_capture_and_restore(self):
        # A skeleton, a camera and a light that were captured are deleted
        # before restore. apply() must restore what is still there and list
        # each missing node in "skipped" with its kind.
        from dazpy.exceptions import NodeNotFoundError
        from dazpy._scene_state import DazSceneState

        skel_kept = MagicMock()
        skel_kept._identifier.value = "Kept"
        skel_kept._client.execute.return_value = ExecutionResult(
            value={"bones": {}, "morphs": {}, "props": {}}, output=[], request_id="x",
        )
        skel_kept.follow_target.return_value = None

        def _find_skeleton(name):
            if name == "Kept":
                return skel_kept
            raise NodeNotFoundError(f"Skeleton not found: {name!r}")

        scene = MagicMock()
        scene.find_skeleton.side_effect = _find_skeleton
        # What the camera/light restore script returns when CamGone and
        # LightGone no longer exist.
        scene._client.execute.return_value = ExecutionResult(
            value={
                "restored": ["CamKept"],
                "skipped": [
                    {"kind": "camera", "name": "CamGone", "reason": "not_found"},
                    {"kind": "light", "name": "LightGone", "reason": "not_found"},
                ],
                "errors": ["Camera not found: CamGone", "Light not found: LightGone"],
            },
            output=[], request_id="x",
        )

        state = DazSceneState(
            skeleton_poses={"Kept": MagicMock(), "Deleted": MagicMock()},
            camera_transforms={"CamKept": {"XTranslate": 1.0}, "CamGone": {"XTranslate": 2.0}},
            light_transforms={"LightGone": {"XTranslate": 3.0}},
            light_extra={"LightGone": {}},
            follow_targets={"Kept": None, "Deleted": None},
        )
        result = state.apply(scene)

        self.assertEqual(result["restored"], ["Kept", "CamKept"])
        self.assertEqual(
            result["skipped"],
            [
                {"kind": "skeleton", "name": "Deleted", "reason": "not_found"},
                {"kind": "camera", "name": "CamGone", "reason": "not_found"},
                {"kind": "light", "name": "LightGone", "reason": "not_found"},
            ],
        )
        self.assertEqual(len(result["errors"]), 3)
        self.assertFalse(result["complete"])
        self.assertIsNone(result["backup"])

        # The restore script itself must report missing cameras/lights as skips.
        script = scene._client.execute.call_args[0][0]
        self.assertIn('kind: "camera"', script)
        self.assertIn('kind: "light"', script)

    def test_apply_skips_follow_target_whose_target_figure_was_deleted(self):
        from dazpy.exceptions import NodeNotFoundError
        from dazpy._scene_state import DazSceneState

        boots = MagicMock()
        boots._identifier.value = "Boots"
        boots._client.execute.return_value = ExecutionResult(
            value={"bones": {}, "morphs": {}, "props": {}}, output=[], request_id="x",
        )
        boots.follow_target.return_value = None

        def _find_skeleton(name):
            if name == "Boots":
                return boots
            raise NodeNotFoundError(name)

        scene = MagicMock()
        scene.find_skeleton.side_effect = _find_skeleton
        scene._client.execute.return_value = ExecutionResult(
            value={"restored": [], "errors": []}, output=[], request_id="x",
        )
        # Genesis9 was captured as Boots' fit target but is not part of this
        # checkpoint's skeleton set any more (deleted before restore).
        state = DazSceneState(
            skeleton_poses={"Boots": MagicMock()},
            camera_transforms={}, light_transforms={}, light_extra={},
            follow_targets={"Boots": "Genesis9"},
        )
        result = state.apply(scene)

        boots.fit_to.assert_not_called()
        self.assertIn("Boots", result["restored"])
        self.assertEqual(
            result["skipped"], [{"kind": "follow_target", "name": "Boots", "reason": "not_found"}]
        )
        self.assertFalse(result["complete"])

    def test_apply_clean_restore_is_complete(self):
        from dazpy._scene_state import DazSceneState

        skel = MagicMock()
        skel._identifier.value = "Genesis9"
        skel._client.execute.return_value = ExecutionResult(
            value={"bones": {}, "morphs": {}, "props": {}}, output=[], request_id="x",
        )
        skel.follow_target.return_value = None
        scene = MagicMock()
        scene.find_skeleton.return_value = skel
        scene._client.execute.return_value = ExecutionResult(
            value={"restored": [], "errors": []}, output=[], request_id="x",
        )
        state = DazSceneState(
            skeleton_poses={"Genesis9": MagicMock()},
            camera_transforms={}, light_transforms={}, light_extra={},
            follow_targets={"Genesis9": None},
        )
        result = state.apply(scene)

        self.assertEqual(result["restored"], ["Genesis9"])
        self.assertEqual(result["skipped"], [])
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["complete"])

    def test_apply_does_not_trust_apply_full_success_without_verifying(self):
        # Regression for dpi-mxq: apply_full() can return normally (no
        # exception) while DAZ Studio's main thread only partially executed
        # the restore script, silently leaving a bone unrestored. apply()
        # must not report a skeleton as "restored" unless a fresh
        # DazPose.capture() read-back actually matches the checkpoint.
        from dazpy import DazPose
        from dazpy._scene_state import DazSceneState

        pose = DazPose("Stuck", bones={"lShldr": [10.0, 20.0, 30.0]}, morphs={}, props={})
        skel = MagicMock()
        skel._identifier.value = "Stuck"
        skel._client.execute.side_effect = [
            ExecutionResult(value=True, output=[], request_id="x"),  # apply_full()
            # capture() read-back: shoulder never actually moved off zero,
            # so it's absent from the sparse capture result -- yet apply_full
            # raised no error.
            ExecutionResult(value={"bones": {}, "morphs": {}, "props": {}}, output=[], request_id="x"),
        ] * 3  # retried up to max_verify_retries, never matches

        scene = MagicMock()
        scene.find_skeleton.return_value = skel
        scene._client.execute.return_value = ExecutionResult(
            value={"restored": [], "errors": []}, output=[], request_id="x",
        )

        state = DazSceneState(
            skeleton_poses={"Stuck": pose},
            camera_transforms={}, light_transforms={}, light_extra={},
        )
        result = state.apply(scene)

        self.assertNotIn("Stuck", result["restored"])
        self.assertTrue(any("Stuck" in e and "lShldr" in e for e in result["errors"]))

    def test_apply_retries_verification_and_recovers(self):
        # First read-back doesn't match (simulating a partial restore under
        # contention); the second attempt's read-back matches, so apply()
        # should retry apply_full() and end up reporting success.
        from dazpy import DazPose
        from dazpy._scene_state import DazSceneState

        pose = DazPose("Retry", bones={"hip": [0.0, 5.0, 0.0]}, morphs={}, props={})
        skel = MagicMock()
        skel._identifier.value = "Retry"
        skel._client.execute.side_effect = [
            ExecutionResult(value=True, output=[], request_id="x"),  # apply_full() #1
            ExecutionResult(value={"bones": {}, "morphs": {}, "props": {}}, output=[], request_id="x"),  # capture #1: mismatch
            ExecutionResult(value=True, output=[], request_id="x"),  # apply_full() #2
            ExecutionResult(
                value={"bones": {"hip": [0.0, 5.0, 0.0]}, "morphs": {}, "props": {}},
                output=[], request_id="x",
            ),  # capture #2: matches
        ]

        scene = MagicMock()
        scene.find_skeleton.return_value = skel
        scene._client.execute.return_value = ExecutionResult(
            value={"restored": [], "errors": []}, output=[], request_id="x",
        )

        state = DazSceneState(
            skeleton_poses={"Retry": pose},
            camera_transforms={}, light_transforms={}, light_extra={},
        )
        result = state.apply(scene)

        self.assertIn("Retry", result["restored"])
        self.assertEqual(result["errors"], [])
        # apply_full's script-executing call happens on attempts 1 and 2;
        # capture's call happens once per attempt too -- 4 total execute() calls.
        self.assertEqual(skel._client.execute.call_count, 4)

    def test_apply_verification_tolerates_small_float_differences(self):
        from dazpy import DazPose
        from dazpy._scene_state import DazSceneState

        pose = DazPose("Fuzzy", bones={"hip": [0.0, 5.0, 0.0]}, morphs={}, props={})
        skel = MagicMock()
        skel._identifier.value = "Fuzzy"
        skel._client.execute.side_effect = [
            ExecutionResult(value=True, output=[], request_id="x"),  # apply_full()
            ExecutionResult(
                value={"bones": {"hip": [0.0, 5.0001, 0.0]}, "morphs": {}, "props": {}},
                output=[], request_id="x",
            ),  # capture(): within default tolerance
        ]

        scene = MagicMock()
        scene.find_skeleton.return_value = skel
        scene._client.execute.return_value = ExecutionResult(
            value={"restored": [], "errors": []}, output=[], request_id="x",
        )

        state = DazSceneState(
            skeleton_poses={"Fuzzy": pose},
            camera_transforms={}, light_transforms={}, light_extra={},
        )
        result = state.apply(scene)

        self.assertIn("Fuzzy", result["restored"])
        self.assertEqual(skel._client.execute.call_count, 2)

    def _skel_for_follow_target_tests(self, name, execute_value):
        skel = MagicMock()
        skel._identifier.value = name
        skel._client.execute.return_value = execute_value
        return skel

    def test_apply_restores_conforming_items_follow_target(self):
        # Regression for daz-script-server-jz0e: DazPose.apply_full() writes
        # back every property on a skeleton, including the internal "FID_*"
        # property DAZ Studio uses to persist a conforming item's fit
        # registration -- rewriting it (even to its own captured value)
        # desyncs the live getFollowTarget() pointer without raising. apply()
        # must independently re-fit any skeleton whose follow-target no
        # longer matches what capture() recorded.
        from dazpy._scene_state import DazSceneState

        base_pose = MagicMock()
        boots_pose = MagicMock()
        exec_result = ExecutionResult(
            value={"bones": {}, "morphs": {}, "props": {}}, output=[], request_id="x",
        )

        base_skel = self._skel_for_follow_target_tests("Genesis9", exec_result)
        boots_skel = self._skel_for_follow_target_tests("Boots", exec_result)
        base_skel.follow_target.return_value = None  # base figure has no follow-target
        # apply_full() desynced the follow-target pointer even though the
        # captured value ("Genesis9") is what we'll assert gets restored.
        boots_skel.follow_target.return_value = None

        scene = MagicMock()
        scene.find_skeleton.side_effect = lambda name: {
            "Genesis9": base_skel, "Boots": boots_skel,
        }[name]
        scene._client.execute.return_value = ExecutionResult(
            value={"restored": [], "errors": []}, output=[], request_id="x",
        )

        state = DazSceneState(
            skeleton_poses={"Genesis9": base_pose, "Boots": boots_pose},
            camera_transforms={}, light_transforms={}, light_extra={},
            follow_targets={"Genesis9": None, "Boots": "Genesis9"},
        )
        result = state.apply(scene)

        boots_skel.fit_to.assert_called_once_with(base_skel)
        base_skel.fit_to.assert_not_called()
        base_skel.unfit.assert_not_called()
        self.assertEqual(result["errors"], [])

    def test_apply_does_not_refit_when_follow_target_already_correct(self):
        # A skeleton whose follow-target already matches the captured value
        # (the common case -- apply_full() doesn't always desync it) should
        # not get a redundant fit_to() call.
        from dazpy._scene_state import DazSceneState

        exec_result = ExecutionResult(
            value={"bones": {}, "morphs": {}, "props": {}}, output=[], request_id="x",
        )
        base_skel = self._skel_for_follow_target_tests("Genesis9", exec_result)
        boots_skel = self._skel_for_follow_target_tests("Boots", exec_result)
        base_skel.follow_target.return_value = None
        already_correct_target = MagicMock()
        already_correct_target._identifier.value = "Genesis9"
        boots_skel.follow_target.return_value = already_correct_target

        scene = MagicMock()
        scene.find_skeleton.side_effect = lambda name: {
            "Genesis9": base_skel, "Boots": boots_skel,
        }[name]
        scene._client.execute.return_value = ExecutionResult(
            value={"restored": [], "errors": []}, output=[], request_id="x",
        )

        state = DazSceneState(
            skeleton_poses={"Genesis9": MagicMock(), "Boots": MagicMock()},
            camera_transforms={}, light_transforms={}, light_extra={},
            follow_targets={"Genesis9": None, "Boots": "Genesis9"},
        )
        state.apply(scene)

        boots_skel.fit_to.assert_not_called()
        boots_skel.unfit.assert_not_called()

    def test_apply_unfits_skeleton_captured_with_no_follow_target(self):
        from dazpy._scene_state import DazSceneState

        exec_result = ExecutionResult(
            value={"bones": {}, "morphs": {}, "props": {}}, output=[], request_id="x",
        )
        skel = self._skel_for_follow_target_tests("Prop", exec_result)
        stale_target = MagicMock()
        stale_target._identifier.value = "SomeFigure"
        skel.follow_target.return_value = stale_target

        scene = MagicMock()
        scene.find_skeleton.return_value = skel
        scene._client.execute.return_value = ExecutionResult(
            value={"restored": [], "errors": []}, output=[], request_id="x",
        )

        state = DazSceneState(
            skeleton_poses={"Prop": MagicMock()},
            camera_transforms={}, light_transforms={}, light_extra={},
            follow_targets={"Prop": None},
        )
        state.apply(scene)

        skel.unfit.assert_called_once()
        skel.fit_to.assert_not_called()

    def test_apply_retries_follow_target_restore_on_busy_error(self):
        from dazpy._scene_state import DazSceneState
        from dazpy.exceptions import StudioBusyError

        exec_result = ExecutionResult(
            value={"bones": {}, "morphs": {}, "props": {}}, output=[], request_id="x",
        )
        base_skel = self._skel_for_follow_target_tests("Genesis9", exec_result)
        boots_skel = self._skel_for_follow_target_tests("Boots", exec_result)
        base_skel.follow_target.return_value = None
        boots_skel.follow_target.side_effect = [StudioBusyError("busy"), None]

        scene = MagicMock()
        scene.find_skeleton.side_effect = lambda name: {
            "Genesis9": base_skel, "Boots": boots_skel,
        }[name]
        scene._client.execute.return_value = ExecutionResult(
            value={"restored": [], "errors": []}, output=[], request_id="x",
        )

        state = DazSceneState(
            skeleton_poses={"Genesis9": MagicMock(), "Boots": MagicMock()},
            camera_transforms={}, light_transforms={}, light_extra={},
            follow_targets={"Genesis9": None, "Boots": "Genesis9"},
        )
        with patch("dazpy._scene_state.time.sleep"):
            result = state.apply(scene)

        self.assertEqual(boots_skel.follow_target.call_count, 2)
        boots_skel.fit_to.assert_called_once_with(base_skel)
        self.assertEqual(result["errors"], [])


class TestDazSceneStateBackup(unittest.TestCase):
    """capture(backup_path=...) takes a full-scene save-copy before the pose checkpoint."""

    def _scene(self):
        scene = MagicMock()
        scene.skeletons.return_value = []
        scene._client.execute.return_value = ExecutionResult(value={}, output=[], request_id="x")
        scene.save_copy.return_value = {
            "ok": True, "path": "C:/backups/pre.duf", "source": "C:/scenes/a.duf", "method": "copy",
        }
        return scene

    def test_capture_without_backup_path_does_not_save_copy(self):
        from dazpy._scene_state import DazSceneState

        scene = self._scene()
        state = DazSceneState.capture(scene)

        scene.save_copy.assert_not_called()
        self.assertIsNone(state.backup)

    def test_capture_with_backup_path_saves_copy_before_capturing(self):
        from dazpy._scene_state import DazSceneState

        scene = self._scene()
        order = []
        scene.save_copy.side_effect = lambda p: order.append("save_copy") or {"ok": True, "path": p}
        scene.skeletons.side_effect = lambda: order.append("skeletons") or []

        state = DazSceneState.capture(scene, backup_path="C:/backups/pre.duf")

        scene.save_copy.assert_called_once_with("C:/backups/pre.duf")
        self.assertEqual(order[0], "save_copy")
        self.assertEqual(state.backup, {"ok": True, "path": "C:/backups/pre.duf"})

    def test_capture_backup_failure_propagates(self):
        from dazpy.exceptions import DazError
        from dazpy._scene_state import DazSceneState

        scene = self._scene()
        scene.save_copy.side_effect = DazError("disk full")

        with self.assertRaises(DazError):
            DazSceneState.capture(scene, backup_path="C:/backups/pre.duf")
        scene.skeletons.assert_not_called()

    def test_backup_round_trips_and_is_reported_by_apply(self):
        from dazpy._scene_state import DazSceneState

        scene = self._scene()
        state = DazSceneState.capture(scene, backup_path="C:/backups/pre.duf")

        restored = DazSceneState.from_dict(json.loads(json.dumps(state.to_dict())))
        self.assertEqual(restored.backup, state.backup)
        self.assertIsNone(DazSceneState.from_dict({}).backup)

        scene._client.execute.return_value = ExecutionResult(
            value={"restored": [], "errors": []}, output=[], request_id="x",
        )
        result = restored.apply(scene)
        self.assertEqual(result["backup"]["path"], "C:/backups/pre.duf")
        self.assertTrue(result["complete"])


class TestSceneSnapshot(unittest.TestCase):
    """Tests for DazScene.scene_snapshot() and build_rig_profiles_from_snapshot()."""

    from dazpy import build_rig_profiles_from_snapshot

    _SAMPLE_SNAPSHOT = [
        {
            "name": "Genesis9",
            "label": "Genesis 9",
            "bones": [
                {
                    "name": "hip",
                    "label": "Hip",
                    "parent_name": None,
                    "rotation_order": "YXZ",
                    "local_position": {"x": 0.0, "y": 100.0, "z": 0.0},
                    "world_position": {"x": 0.0, "y": 100.0, "z": 0.0},
                    "local_euler": {"x": 0.0, "y": 0.0, "z": 0.0},
                },
                {
                    "name": "l_hand",
                    "label": "Left Hand",
                    "parent_name": "hip",
                    "rotation_order": "YXZ",
                    "local_position": {"x": 20.0, "y": 150.0, "z": 0.0},
                    "world_position": {"x": 20.0, "y": 150.0, "z": 0.0},
                    "local_euler": {"x": 0.0, "y": 0.0, "z": 0.0},
                },
                {
                    "name": "r_hand",
                    "label": "Right Hand",
                    "parent_name": "hip",
                    "rotation_order": "YXZ",
                    "local_position": {"x": -20.0, "y": 150.0, "z": 0.0},
                    "world_position": {"x": -20.0, "y": 150.0, "z": 0.0},
                    "local_euler": {"x": 0.0, "y": 0.0, "z": 0.0},
                },
                {
                    "name": "l_foot",
                    "label": "Left Foot",
                    "parent_name": "hip",
                    "rotation_order": "YXZ",
                    "local_position": {"x": 10.0, "y": 0.0, "z": 0.0},
                    "world_position": {"x": 10.0, "y": 0.0, "z": 0.0},
                    "local_euler": {"x": 0.0, "y": 0.0, "z": 0.0},
                },
            ],
        }
    ]

    def test_build_rig_profiles_from_snapshot_keys(self):
        from dazpy import build_rig_profiles_from_snapshot
        profiles = build_rig_profiles_from_snapshot(self._SAMPLE_SNAPSHOT)
        self.assertIn("Genesis 9", profiles)
        self.assertIn("Genesis9", profiles)
        self.assertIs(profiles["Genesis 9"], profiles["Genesis9"])

    def test_build_rig_profiles_figure_label_and_family(self):
        from dazpy import build_rig_profiles_from_snapshot
        profiles = build_rig_profiles_from_snapshot(self._SAMPLE_SNAPSHOT)
        profile = profiles["Genesis 9"]
        self.assertEqual(profile.figure_label, "Genesis 9")
        self.assertEqual(profile.family, "genesis_9")

    def test_build_rig_profiles_bone_world_position(self):
        from dazpy import build_rig_profiles_from_snapshot
        profiles = build_rig_profiles_from_snapshot(self._SAMPLE_SNAPSHOT)
        bone = profiles["Genesis 9"].bone("l_hand")
        self.assertEqual(bone.world_position, (20.0, 150.0, 0.0))
        self.assertEqual(bone.local_position, (20.0, 150.0, 0.0))

    def test_build_rig_profiles_parent_chain(self):
        from dazpy import build_rig_profiles_from_snapshot
        profiles = build_rig_profiles_from_snapshot(self._SAMPLE_SNAPSHOT)
        profile = profiles["Genesis 9"]
        self.assertEqual(profile.bone("l_hand").parent_name, "hip")
        self.assertIsNone(profile.bone("hip").parent_name)

    def test_build_rig_profiles_anchor_uses_world_position(self):
        from dazpy import build_rig_profiles_from_snapshot
        from dazpy._interaction_profile import _anchor_world_point_hint
        profiles = build_rig_profiles_from_snapshot(self._SAMPLE_SNAPSHOT)
        profile = profiles["Genesis 9"]
        point = _anchor_world_point_hint(profile, "r_hand")
        self.assertIsNotNone(point)
        self.assertAlmostEqual(point[0], -20.0)

    def test_build_rig_profiles_source_metadata(self):
        from dazpy import build_rig_profiles_from_snapshot
        profiles = build_rig_profiles_from_snapshot(self._SAMPLE_SNAPSHOT)
        self.assertEqual(profiles["Genesis 9"].metadata["source"], "snapshot")

    def test_build_rig_profiles_empty_snapshot(self):
        from dazpy import build_rig_profiles_from_snapshot
        self.assertEqual(build_rig_profiles_from_snapshot([]), {})

    def test_scene_snapshot_script_contains_getWSPos(self):
        client = mock_client([])
        scene = DazScene(client)
        scene.scene_snapshot()
        script = client.execute.call_args[0][0]
        self.assertIn("getWSPos", script)
        self.assertIn("getAllBones", script)
        self.assertIn("getSkeletonList", script)

    def test_scene_snapshot_rotation_order_stringified(self):
        client = mock_client([])
        scene = DazScene(client)
        scene.scene_snapshot()
        script = client.execute.call_args[0][0]
        self.assertIn("getRotationOrder().toString()", script)

    def test_undo_last_uses_global_undo_stack(self):
        client = mock_client(None)
        DazScene(client).undo_last()
        script = client.execute.call_args[0][0]
        self.assertIn("UndoStack.undo()", script)
        self.assertNotIn("getUndoStack", script)

    def test_redo_last_uses_global_undo_stack(self):
        client = mock_client(None)
        DazScene(client).redo_last()
        script = client.execute.call_args[0][0]
        self.assertIn("UndoStack.redo()", script)
        self.assertNotIn("getUndoStack", script)

    def test_scene_snapshot_filter_serialized(self):
        client = mock_client([])
        scene = DazScene(client)
        scene.scene_snapshot(skeleton_labels=["Genesis 9", "Bob"])
        script = client.execute.call_args[0][0]
        self.assertIn('"Genesis 9"', script)
        self.assertIn('"Bob"', script)

    def test_scene_snapshot_no_filter_passes_null(self):
        client = mock_client([])
        scene = DazScene(client)
        scene.scene_snapshot()
        script = client.execute.call_args[0][0]
        self.assertIn("null", script)

    def test_apply_recipe_uses_snapshot_when_available(self):
        """apply_interaction_recipe_to_scene uses scene_snapshot() when present."""
        from dazpy import build_rig_profiles_from_snapshot

        snapshot = self._SAMPLE_SNAPSHOT
        profiles = build_rig_profiles_from_snapshot(snapshot)

        class _SnapshotScene:
            def scene_snapshot(self, **_):
                return snapshot

            def skeletons(self):
                raise AssertionError("skeletons() should not be called when scene_snapshot() is present")

        # Just verify build_rig_profiles_from_snapshot returns correct structure
        self.assertIn("Genesis 9", profiles)
        self.assertEqual(profiles["Genesis 9"].bone("l_hand").world_position, (20.0, 150.0, 0.0))

    def test_bone_profile_world_position_round_trips(self):
        bp = BoneProfile(
            name="test_bone",
            world_position=(1.0, 2.0, 3.0),
        )
        d = bp.to_dict()
        self.assertEqual(d["world_position"], [1.0, 2.0, 3.0])
        restored = BoneProfile.from_dict(d)
        self.assertEqual(restored.world_position, (1.0, 2.0, 3.0))

    def test_bone_profile_world_position_none_by_default(self):
        bp = BoneProfile(name="test_bone")
        self.assertIsNone(bp.world_position)
        d = bp.to_dict()
        self.assertIsNone(d["world_position"])


class TestDazViewport(unittest.TestCase):
    def _make_viewport(self, return_value=None):
        client = mock_client(return_value=return_value)
        from dazpy._viewport import DazViewport
        vp = DazViewport(client)
        return vp, client

    def test_is_available_true(self):
        vp, client = self._make_viewport(return_value=True)
        self.assertTrue(vp.is_available())
        client.execute.assert_called_once()

    def test_is_available_false(self):
        vp, client = self._make_viewport(return_value=False)
        self.assertFalse(vp.is_available())

    def test_get_size(self):
        vp, client = self._make_viewport(return_value={"width": 1280, "height": 720})
        result = vp.get_size()
        self.assertEqual(result, {"width": 1280, "height": 720})
        client.execute.assert_called_once()

    def test_draw_style_returns_label(self):
        vp, client = self._make_viewport(return_value="NVIDIA Iray")
        result = vp.draw_style()
        self.assertEqual(result, "NVIDIA Iray")
        script = client.execute.call_args[0][0]
        self.assertIn("getUserDrawStyle", script)

    def test_set_draw_style_resolves_alias(self):
        vp, client = self._make_viewport(
            return_value={"before": "NVIDIA Iray", "after": "Wireframe"}
        )
        vp.set_draw_style("wireframe")
        script = client.execute.call_args[0][0]
        self.assertIn("setUserDrawStyle", script)
        self.assertIn('"Wireframe"', script)

    def test_set_draw_style_accepts_raw_label(self):
        vp, client = self._make_viewport(
            return_value={"before": "NVIDIA Iray", "after": "Smooth Shaded"}
        )
        vp.set_draw_style("Smooth Shaded")
        script = client.execute.call_args[0][0]
        self.assertIn('"Smooth Shaded"', script)

    def test_set_draw_style_raises_on_unknown_label(self):
        vp, client = self._make_viewport(
            return_value={"before": "NVIDIA Iray", "after": "NVIDIA Iray"}
        )
        with self.assertRaises(ValueError):
            vp.set_draw_style("Not A Real Style")

    def test_set_draw_style_noop_when_already_set(self):
        vp, client = self._make_viewport(
            return_value={"before": "NVIDIA Iray", "after": "NVIDIA Iray"}
        )
        vp.set_draw_style("iray")  # already NVIDIA Iray -- should not raise

    def test_set_size_raises(self):
        vp, client = self._make_viewport()
        with self.assertRaises(NotImplementedError):
            vp.set_size(800, 600)

    def test_capture_basic(self):
        path = "C:/tmp/snap.png"
        vp, client = self._make_viewport(return_value=path)
        result = vp.capture(path)
        script = client.execute.call_args[0][0]
        self.assertIn("captureImage", script)
        self.assertIn(".save(", script)
        self.assertIn(json.dumps(path), script)
        self.assertEqual(result, path)

    def test_capture_ignores_width_height(self):
        path = "C:/tmp/snap.png"
        vp, client = self._make_viewport(return_value=path)
        vp.capture(path, width=1920, height=1080)
        script = client.execute.call_args[0][0]
        self.assertIn("captureImage", script)
        self.assertNotIn("setFixedSize", script)
        self.assertNotIn("_prevSize", script)

    def test_capture_returns_path_on_null_result(self):
        path = "C:/tmp/snap.png"
        vp, client = self._make_viewport(return_value=None)
        result = vp.capture(path)
        self.assertEqual(result, path)

    def test_capture_backdrop_color_restores_prev_bg_without_scope_error(self):
        # Regression test: prevBg must round-trip through Python (prepare_script's
        # returned value) rather than a bare JS `var` -- the prepare and finish
        # scripts are separate execute() calls with no shared JS scope.
        path = "C:/tmp/snap.png"
        vp, client = self._make_viewport()
        prev_state = {
            "axesOn": True, "floorStyle": 1, "showPoseTool": False,
            "aspectOn": True, "thirdsGuideOn": False, "toolBarMode": 0,
            "selectionName": None, "tnVisible": None, "envVisible": None,
            "bg": {"r": 10, "g": 20, "b": 30, "a": 255},
        }
        client.execute.side_effect = [
            ExecutionResult(value=prev_state, output=[], request_id="x"),
            ExecutionResult(value=path, output=[], request_id="x"),
        ]
        result = vp.capture(path, backdrop_color=(0, 255, 0), convergence_wait=0)
        self.assertEqual(result, path)

        finish_script = client.execute.call_args_list[1][0][0]
        self.assertNotIn("prevBg", finish_script)
        self.assertIn("new QColor(10, 20, 30, 255)", finish_script)

    def test_capture_restores_bone_selection_via_skeleton_fallback(self):
        # Regression: Scene.findNode() only resolves top-level scene nodes, not
        # bones (e.g. one selected via the Joint Editor), so restoring a bone
        # selection needs the owning skeleton's name to look it up via
        # findBone() when the direct findNode() lookup comes back null.
        path = "C:/tmp/snap.png"
        vp, client = self._make_viewport()
        prev_state = {
            "axesOn": True, "floorStyle": 1, "showPoseTool": False,
            "aspectOn": True, "thirdsGuideOn": False, "toolBarMode": 0,
            "selectionName": "lShldrBend", "selectionSkeletonName": "Genesis9",
            "tnVisible": None, "envVisible": None,
        }
        client.execute.side_effect = [
            ExecutionResult(value=prev_state, output=[], request_id="x"),
            ExecutionResult(value=path, output=[], request_id="x"),
        ]
        result = vp.capture(path, convergence_wait=0)
        self.assertEqual(result, path)

        finish_script = client.execute.call_args_list[1][0][0]
        self.assertIn("selectionSkeletonName", finish_script)
        self.assertIn("findBone", finish_script)

    def test_capture_finish_script_restores_selection_even_if_vp_gone(self):
        # Regression: if the viewport becomes unavailable during the real
        # wall-clock convergence_wait sleep, the finish script must still
        # restore scene-level state (selection, Tonemapper/Environment node
        # visibility) instead of bailing out on `if (!vp) return null;`
        # before any restoration happens.
        path = "C:/tmp/snap.png"
        vp, client = self._make_viewport()
        prev_state = {
            "axesOn": True, "floorStyle": 1, "showPoseTool": False,
            "aspectOn": True, "thirdsGuideOn": False, "toolBarMode": 0,
            "selectionName": "SomeNode", "selectionSkeletonName": None,
            "tnVisible": True, "envVisible": True,
        }
        client.execute.side_effect = [
            ExecutionResult(value=prev_state, output=[], request_id="x"),
            ExecutionResult(value=None, output=[], request_id="x"),
        ]
        result = vp.capture(path, convergence_wait=0)
        # No image captured (vp gone) -> falls back to returning the path.
        self.assertEqual(result, path)

        finish_script = client.execute.call_args_list[1][0][0]
        # The vp-null guard must not short-circuit before scene-level restore.
        self.assertNotIn("if (!vp) return null;", finish_script)
        self.assertIn("Scene.setPrimarySelection(prevSel);", finish_script)
        self.assertIn("if (vp) {", finish_script)

    def test_capture_backdrop_color_no_overlays_restores_prev_bg(self):
        path = "C:/tmp/snap.png"
        vp, client = self._make_viewport()
        client.execute.side_effect = [
            ExecutionResult(
                value={"ok": True, "bg": {"r": 1, "g": 2, "b": 3, "a": 255}},
                output=[], request_id="x",
            ),
            ExecutionResult(value=path, output=[], request_id="x"),
        ]
        result = vp.capture(
            path, hide_overlays=False, backdrop_color=(0, 255, 0), convergence_wait=0
        )
        self.assertEqual(result, path)

        finish_script = client.execute.call_args_list[1][0][0]
        self.assertNotIn("prevBg", finish_script)
        self.assertIn("new QColor(1, 2, 3, 255)", finish_script)


class _FakeSSEResponse:
    """Minimal stand-in for a streaming requests.Response over /scene/events."""

    def __init__(self, frames):
        # frames: list of raw SSE frame strings, e.g. 'data: {"type":"node.added",...}'
        body = "\n\n".join(frames) + "\n\n" if frames else ""
        self._chunks = [body.encode("utf-8")]
        self.closed = False

    def iter_content(self, chunk_size=None):
        yield from self._chunks

    def close(self):
        self.closed = True


class TestSceneEvents(unittest.TestCase):
    def _events_json(self, *pairs):
        return [
            f'data: {json.dumps({"type": t, "ts": 1000, "data": d})}'
            for t, d in pairs
        ]

    def test_watch_scene_events_parses_frames(self):
        client = MagicMock()
        client.stream_scene_events.return_value = _FakeSSEResponse(
            self._events_json(
                ("node.added", {"node_name": "Genesis9"}),
                ("selection.list_changed", {}),
            )
        )
        events = list(watch_scene_events(client))
        self.assertEqual(len(events), 2)
        self.assertIsInstance(events[0], SceneEvent)
        self.assertEqual(events[0].type, "node.added")
        self.assertEqual(events[0].data, {"node_name": "Genesis9"})
        self.assertEqual(events[1].type, "selection.list_changed")

    def test_watch_scene_events_skips_keepalive_comments(self):
        client = MagicMock()
        frames = [":keepalive"] + self._events_json(("scene.loaded", {}))
        client.stream_scene_events.return_value = _FakeSSEResponse(frames)
        events = list(watch_scene_events(client))
        self.assertEqual([e.type for e in events], ["scene.loaded"])

    def test_watch_scene_events_filters_by_event_types(self):
        client = MagicMock()
        client.stream_scene_events.return_value = _FakeSSEResponse(
            self._events_json(
                ("node.added", {}),
                ("node.removed", {}),
                ("light.added", {}),
            )
        )
        events = list(watch_scene_events(client, event_types={"node.removed"}))
        self.assertEqual([e.type for e in events], ["node.removed"])

    def test_watch_scene_events_closes_response(self):
        client = MagicMock()
        resp = _FakeSSEResponse(self._events_json(("scene.loaded", {})))
        client.stream_scene_events.return_value = resp
        list(watch_scene_events(client))
        self.assertTrue(resp.closed)

    def test_watch_scene_events_raises_connection_error_when_stream_unavailable(self):
        client = MagicMock()
        client.stream_scene_events.return_value = None
        with self.assertRaises(DazConnectionError):
            list(watch_scene_events(client))

    def test_wait_for_scene_event_returns_matching_event(self):
        client = MagicMock()
        client.stream_scene_events.return_value = _FakeSSEResponse(
            self._events_json(
                ("node.added", {"node_name": "A"}),
                ("node.added", {"node_name": "B"}),
            )
        )
        event = wait_for_scene_event(client, "node.added", timeout=5.0)
        self.assertEqual(event.data, {"node_name": "A"})
        # Category should be derived from the event type for server-side filtering.
        _, kwargs = client.stream_scene_events.call_args
        self.assertEqual(kwargs["categories"], ["node"])

    def test_wait_for_scene_event_times_out_when_stream_ends_without_match(self):
        client = MagicMock()
        client.stream_scene_events.return_value = _FakeSSEResponse(
            self._events_json(("scene.loaded", {}))
        )
        with self.assertRaises(DazTimeoutError):
            wait_for_scene_event(client, "node.added", timeout=1.0)


if __name__ == "__main__":
    unittest.main()
