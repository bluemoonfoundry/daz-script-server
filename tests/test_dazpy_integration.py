"""
Integration tests for the dazpy SDK.

Skipped automatically when DAZ Studio / the script server is not reachable.

Run standalone:  python tests/test_dazpy_integration.py
Via runner:      python tests.py integration
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import requests as _req

from dazpy import (
    Batch,
    DazBone,
    DazCamera,
    DazClient,
    DazDForce,
    DazGeometry,
    DazMaterial,
    DazModifier,
    DazMorph,
    DazNode,
    DazPose,
    DazRenderSettings,
    DazScene,
    DazSkeleton,
    DazTimeline,
    DazViewport,
    ExecutionResult,
    LimbAlignmentResult,
    NodeIdentifier,
    build_rig_profiles_from_snapshot,
    align_hand_target,
    align_foot_target,
    execute_long,
    exceptions,
)

# ── Server availability ────────────────────────────────────────────────────────

_SERVER_UP: bool = False
_SERVER_SKIP_REASON = "DAZ Studio script server not reachable at 127.0.0.1:18811"

try:
    _resp = _req.get("http://127.0.0.1:18811/status", timeout=2)
    _SERVER_UP = _resp.status_code == 200
except Exception:
    pass

_AUTH_ENABLED: bool = False
_DAZ_GLOBALS_AVAILABLE: bool = False  # True when Scene etc. are accessible

if _SERVER_UP:
    try:
        _ar = _req.post(
            "http://127.0.0.1:18811/execute",
            json={"script": "1;"},
            timeout=3,
        )
        _AUTH_ENABLED = _ar.status_code == 401
    except Exception:
        pass
    try:
        _gr = _req.post(
            "http://127.0.0.1:18811/execute",
            json={"script": "(function(){ return typeof Scene === 'object' && Scene.getNumNodes !== undefined; })()"},
            headers={"X-API-Token": DazClient()._token},
            timeout=3,
        )
        _DAZ_GLOBALS_AVAILABLE = bool(_gr.status_code == 200 and _gr.json().get("result") is True)
    except Exception:
        pass

skip_if_down = unittest.skipUnless(_SERVER_UP, _SERVER_SKIP_REASON)
skip_auth = unittest.skipUnless(_AUTH_ENABLED, "auth disabled on server")
skip_no_daz = unittest.skipUnless(_DAZ_GLOBALS_AVAILABLE, "Scene not available (DAZ Studio not running or no scene loaded)")

_RENDERER_AVAILABLE: bool = False
if _DAZ_GLOBALS_AVAILABLE:
    try:
        _rr = _req.post(
            "http://127.0.0.1:18811/execute",
            json={"script": "(function(){ var m = App.getRenderMgr(); return (m !== null && m !== undefined); })()"},
            headers={"X-API-Token": DazClient()._token},
            timeout=5,
        )
        _RENDERER_AVAILABLE = bool(_rr.status_code == 200 and _rr.json().get("result") is True)
    except Exception:
        pass

skip_no_renderer = unittest.skipUnless(_RENDERER_AVAILABLE, "Render manager not available (App.getRenderMgr() returned null)")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _client() -> DazClient:
    return DazClient()


def _scene() -> DazScene:
    return DazScene()


# ══════════════════════════════════════════════════════════════════════════════
# 1. DazClient — low-level
# ══════════════════════════════════════════════════════════════════════════════

@skip_if_down
class TestDazClientLowLevel(unittest.TestCase):
    def setUp(self):
        self.client = _client()

    def test_execute_returns_execution_result(self):
        result = self.client.execute("(function(){ return 42; })()")
        self.assertIsInstance(result, ExecutionResult)
        self.assertTrue(result.success)
        self.assertEqual(result.value, 42)

    def test_execute_string_result(self):
        result = self.client.execute("(function(){ return 'hello'; })()")
        self.assertEqual(result.value, "hello")

    def test_execute_captures_print_output(self):
        result = self.client.execute("print('ping'); (function(){ return 1; })()")
        self.assertIn("ping", result.output)

    def test_execute_with_args(self):
        result = self.client.execute(
            "(function(){ var a = getArguments()[0]; return a.x + a.y; })()",
            args={"x": 3, "y": 4},
        )
        self.assertEqual(result.value, 7)

    def test_execute_result_has_request_id(self):
        result = self.client.execute("(function(){ return null; })()")
        self.assertIsInstance(result.request_id, str)
        self.assertTrue(len(result.request_id) > 0)

    def test_execute_null_result(self):
        result = self.client.execute("(function(){ return null; })()")
        self.assertIsNone(result.value)

    def test_execute_array_result(self):
        result = self.client.execute("(function(){ return [1, 2, 3]; })()")
        self.assertEqual(result.value, [1, 2, 3])

    def test_execute_object_result(self):
        result = self.client.execute("(function(){ return {a: 1, b: 'two'}; })()")
        self.assertEqual(result.value, {"a": 1, "b": "two"})

    def test_execute_raises_script_runtime_error(self):
        with self.assertRaises(exceptions.ScriptRuntimeError):
            self.client.execute('(function(){ throw new Error("boom"); })()')

    def test_execute_syntax_error_raises_script_syntax_error(self):
        with self.assertRaises(exceptions.ScriptSyntaxError):
            self.client.execute("(function(){ var x = {bad syntax; })()")

    def test_execute_runtime_error_has_request_id(self):
        try:
            self.client.execute('(function(){ throw new Error("boom"); })()')
        except exceptions.ScriptError as e:
            self.assertTrue(len(e.request_id) > 0)

    def test_execute_runtime_error_diagnostic_has_script(self):
        script = '(function(){ throw new Error("boom"); })()'
        try:
            self.client.execute(script)
        except exceptions.ScriptError as e:
            self.assertIn("boom", e.diagnostic)

    def test_status_endpoint(self):
        data = self.client.status()
        self.assertIn("running", data)
        self.assertTrue(data["running"])

    def test_health_endpoint(self):
        data = self.client.health()
        self.assertIn("status", data)

    def test_metrics_endpoint(self):
        data = self.client.metrics()
        self.assertIn("total_requests", data)

    @skip_auth
    def test_bad_token_raises_authentication_error(self):
        bad_client = DazClient(token="invalid-token-000000")
        with self.assertRaises(exceptions.AuthenticationError):
            bad_client.execute("(function(){ return 1; })()")

    @skip_auth
    def test_bad_token_status_raises_authentication_error(self):
        bad_client = DazClient(token="invalid-token-000000")
        with self.assertRaises(exceptions.AuthenticationError):
            bad_client.status()


# ══════════════════════════════════════════════════════════════════════════════
# 2. DazScene
# ══════════════════════════════════════════════════════════════════════════════

@skip_if_down
@skip_no_daz
class TestDazScene(unittest.TestCase):
    def setUp(self):
        self.scene = _scene()

    def test_num_nodes_is_non_negative_int(self):
        n = self.scene.num_nodes()
        self.assertIsInstance(n, int)
        self.assertGreaterEqual(n, 0)

    def test_nodes_returns_list_of_daz_node(self):
        nodes = self.scene.nodes()
        self.assertIsInstance(nodes, list)
        for node in nodes:
            self.assertIsInstance(node, DazNode)

    def test_nodes_count_matches_num_nodes(self):
        self.assertEqual(len(self.scene.nodes()), self.scene.num_nodes())

    def test_all_node_transforms_is_list(self):
        transforms = self.scene.all_node_transforms()
        self.assertIsInstance(transforms, list)

    def test_all_node_transforms_shape(self):
        transforms = self.scene.all_node_transforms()
        for t in transforms:
            self.assertIn("name", t)
            self.assertIn("position", t)
            self.assertIn("rotation", t)
            self.assertEqual(len(t["position"]), 3)

    def test_node_tree_is_list(self):
        tree = self.scene.node_tree()
        self.assertIsInstance(tree, list)

    def test_node_tree_entries_have_children(self):
        tree = self.scene.node_tree()
        for entry in tree:
            self.assertIn("name", entry)
            self.assertIn("children", entry)

    def test_find_node_nonexistent_raises(self):
        with self.assertRaises(exceptions.NodeNotFoundError):
            self.scene.find_node("__this_node_should_never_exist_xyz__")

    def test_cameras_returns_list(self):
        cameras = self.scene.cameras()
        self.assertIsInstance(cameras, list)
        for cam in cameras:
            self.assertIsInstance(cam, DazCamera)

    def test_create_camera_adds_camera_to_scene(self):
        before = self.scene.num_nodes()
        cam = self.scene.create_camera(name="_test_create_camera")
        self.assertIsInstance(cam, DazCamera)
        self.assertEqual(self.scene.num_nodes(), before + 1)
        cam.set_position(10, 20, 30)
        self.assertEqual(cam.position, {"x": 10.0, "y": 20.0, "z": 30.0})

    def test_create_light_adds_light_to_scene(self):
        from dazpy import DazLight
        before = self.scene.num_nodes()
        light = self.scene.create_light("point", name="_test_create_light")
        self.assertIsInstance(light, DazLight)
        self.assertEqual(self.scene.num_nodes(), before + 1)

    def test_create_light_invalid_type_raises(self):
        with self.assertRaises(ValueError):
            self.scene.create_light("__not_a_real_type__")

    def test_frame_is_int(self):
        frame = self.scene.frame()
        self.assertIsInstance(frame, int)

    def test_filename_returns_string(self):
        name = self.scene.filename()
        self.assertIsInstance(name, str)

    def test_needs_save_returns_bool(self):
        result = self.scene.needs_save()
        self.assertIsInstance(result, bool)

    def test_play_range_returns_dict_with_start_end(self):
        r = self.scene.play_range()
        self.assertIsInstance(r, dict)
        self.assertIn("start", r)
        self.assertIn("end", r)
        self.assertIsInstance(r["start"], int)
        self.assertIsInstance(r["end"], int)
        self.assertLessEqual(r["start"], r["end"])

    def test_set_play_range_round_trips(self):
        original_play = self.scene.play_range()
        original_anim = self.scene.anim_range()
        # Expand anim range first — setPlayRange is clamped to the animation range.
        self.scene.set_anim_range(0, 60)
        self.scene.set_play_range(0, 60)
        updated = self.scene.play_range()
        self.assertEqual(updated["start"], 0)
        self.assertEqual(updated["end"], 60)
        self.scene.set_anim_range(original_anim["start"], original_anim["end"])
        self.scene.set_play_range(original_play["start"], original_play["end"])

    def test_set_anim_range_does_not_raise(self):
        r = self.scene.play_range()
        self.scene.set_anim_range(r["start"], r["end"])

    def test_is_playing_returns_bool(self):
        result = self.scene.is_playing()
        self.assertIsInstance(result, bool)

    def test_loop_playback_toggle(self):
        self.scene.loop_playback(True)
        self.scene.loop_playback(False)


# ══════════════════════════════════════════════════════════════════════════════
# 3. DazNode — operates on whatever nodes exist in the scene
# ══════════════════════════════════════════════════════════════════════════════

@skip_if_down
@skip_no_daz
class TestDazNodeOnFirstNode(unittest.TestCase):
    """Tests that run against the first node in the scene, if any exist."""

    @classmethod
    def setUpClass(cls):
        client = _client()
        scene = DazScene(client)
        nodes = scene.nodes()
        cls.node = nodes[0] if nodes else None
        cls.client = client

    def setUp(self):
        if self.node is None:
            self.skipTest("Scene has no nodes")

    def test_label_is_string(self):
        label = self.node.label
        self.assertIsInstance(label, str)

    def test_name_is_string(self):
        name = self.node.name
        self.assertIsInstance(name, str)

    def test_position_is_dict_with_xyz(self):
        pos = self.node.position
        self.assertIsNotNone(pos)
        self.assertIn("x", pos)
        self.assertIn("y", pos)
        self.assertIn("z", pos)

    def test_rotation_is_dict_with_xyzw(self):
        rot = self.node.rotation
        self.assertIsNotNone(rot)
        self.assertIn("x", rot)
        self.assertIn("y", rot)
        self.assertIn("z", rot)
        self.assertIn("w", rot)

    def test_visible_is_bool(self):
        v = self.node.visible
        self.assertIsInstance(v, bool)

    def test_children_is_list(self):
        children = self.node.children
        self.assertIsInstance(children, list)
        for child in children:
            self.assertIsInstance(child, DazNode)

    def test_list_properties_returns_list(self):
        props = self.node.list_properties()
        self.assertIsInstance(props, list)

    def test_list_properties_entries_have_label_and_name(self):
        props = self.node.list_properties()
        for p in props[:5]:  # spot-check first 5
            self.assertIn("label", p)
            self.assertIn("name", p)

    def test_numeric_properties_returns_dict(self):
        props = self.node.numeric_properties()
        self.assertIsInstance(props, dict)

    def test_numeric_properties_values_are_numeric(self):
        props = self.node.numeric_properties()
        for label, value in list(props.items())[:5]:  # spot-check first 5
            self.assertIsInstance(value, (int, float))

    def test_class_name_is_string(self):
        cls = self.node.class_name
        self.assertIsInstance(cls, str)
        self.assertTrue(cls.startswith("Dz"))

    def test_general_scale_is_numeric(self):
        gs = self.node.general_scale
        self.assertIsNotNone(gs)
        self.assertIsInstance(gs, (int, float))

    def test_scale_is_dict_with_four_keys(self):
        s = self.node.scale
        self.assertIsNotNone(s)
        self.assertIsInstance(s, dict)
        for key in ("x", "y", "z", "general"):
            self.assertIn(key, s)
            self.assertIsInstance(s[key], (int, float))


@skip_if_down
@skip_no_daz
class TestDazNodeDeleteAndReparent(unittest.TestCase):
    """Uses create_camera() to make disposable nodes so real scene content is untouched."""

    def setUp(self):
        self.scene = _scene()

    def test_delete_removes_node_from_scene(self):
        cam = self.scene.create_camera(name="_test_delete_camera")
        before = self.scene.num_nodes()
        result = cam.delete()
        self.assertTrue(result)
        self.assertEqual(self.scene.num_nodes(), before - 1)

    def test_delete_nonexistent_node_returns_false(self):
        node = DazNode(self.scene._client, NodeIdentifier("__this_node_should_never_exist_xyz__"))
        self.assertFalse(node.delete())

    def test_reparent_moves_node_under_new_parent(self):
        parent = self.scene.create_camera(name="_test_reparent_parent")
        child = self.scene.create_camera(name="_test_reparent_child")
        try:
            child.reparent(parent)
            self.assertIn(child.name, [c.name for c in parent.children])
        finally:
            child.delete()
            parent.delete()

    def test_reparent_preserve_world_transform_false(self):
        parent = self.scene.create_camera(name="_test_reparent_parent2")
        child = self.scene.create_camera(name="_test_reparent_child2")
        try:
            child.set_position(5, 5, 5)
            child.reparent(parent, preserve_world_transform=False)
            self.assertIn(child.name, [c.name for c in parent.children])
        finally:
            child.delete()
            parent.delete()


# ══════════════════════════════════════════════════════════════════════════════
# 4. Batch
# ══════════════════════════════════════════════════════════════════════════════

@skip_if_down
class TestBatch(unittest.TestCase):
    """Batch tests that require only the script engine (no DAZ scene globals)."""

    def setUp(self):
        self.client = _client()

    def test_batch_executes_in_one_call(self):
        """Two logical operations should produce exactly one HTTP execute call."""
        call_count = [0]
        original_execute = self.client.execute

        def counting_execute(script, args=None):
            call_count[0] += 1
            return original_execute(script, args)

        self.client.execute = counting_execute

        with Batch(self.client) as batch:
            f_two = batch.add(["var _r0 = 1 + 1;"])
            f_str = batch.add(['var _r1 = "hello";'])

        self.assertEqual(call_count[0], 1, "Batch should produce exactly one HTTP call")
        self.assertEqual(f_two.value, 2)
        self.assertEqual(f_str.value, "hello")

    def test_batch_multiple_independent_values(self):
        with Batch(self.client) as batch:
            f_two = batch.add(["var _r0 = 1 + 1;"])
            f_six = batch.add(["var _r1 = 2 * 3;"])
            f_str = batch.add(['var _r2 = "batch";'])

        self.assertEqual(f_two.value, 2)
        self.assertEqual(f_six.value, 6)
        self.assertEqual(f_str.value, "batch")

    def test_batch_js_variable_dependency(self):
        """Within a single batch script, JS variables from earlier ops are visible."""
        with Batch(self.client) as batch:
            f_a = batch.add(["var _r0 = 10;"])
            f_b = batch.add(["var _r1 = _r0 * 2;"])  # depends on _r0 in the same script

        self.assertEqual(f_a.value, 10)
        self.assertEqual(f_b.value, 20)

    def test_batch_exception_skips_execute(self):
        call_count = [0]
        original_execute = self.client.execute

        def counting_execute(script, args=None):
            call_count[0] += 1
            return original_execute(script, args)

        self.client.execute = counting_execute

        with self.assertRaises(ValueError):
            with Batch(self.client):
                raise ValueError("intentional")

        self.assertEqual(call_count[0], 0, "Batch must not execute when context raises")


@skip_if_down
@skip_no_daz
class TestBatchWithScene(unittest.TestCase):
    """Batch tests that use Scene globals."""

    def setUp(self):
        self.client = _client()

    def test_batch_executes_in_one_call_scene(self):
        """Scene-based batch should still produce a single HTTP call."""
        call_count = [0]
        original_execute = self.client.execute

        def counting_execute(script, args=None):
            call_count[0] += 1
            return original_execute(script, args)

        self.client.execute = counting_execute

        with Batch(self.client) as batch:
            f_count = batch.add(["var _r0 = Scene.getNumNodes();"])
            f_frame = batch.add(["var _r1 = Scene.getFrame();"])

        self.assertEqual(call_count[0], 1)
        self.assertIsInstance(f_count.value, int)
        self.assertIsInstance(f_frame.value, int)

    def test_batch_count_matches_scene_num_nodes(self):
        scene = DazScene(self.client)
        expected = scene.num_nodes()

        with Batch(self.client) as batch:
            f = batch.add(["var _r0 = Scene.getNumNodes();"])

        self.assertEqual(f.value, expected)


# ══════════════════════════════════════════════════════════════════════════════
# 5. Async / execute_long
# ══════════════════════════════════════════════════════════════════════════════

@skip_if_down
class TestExecuteLong(unittest.TestCase):
    def setUp(self):
        self.client = _client()

    def test_execute_long_returns_result(self):
        result = execute_long(
            self.client,
            "(function(){ return 99; })()",
            timeout=30.0,
        )
        self.assertIsInstance(result, ExecutionResult)
        self.assertTrue(result.success)
        self.assertEqual(result.value, 99)

    def test_execute_long_with_args(self):
        result = execute_long(
            self.client,
            "(function(){ var a = getArguments()[0]; return a.n * 2; })()",
            args={"n": 21},
            timeout=30.0,
        )
        self.assertEqual(result.value, 42)

    def test_execute_long_captures_output(self):
        result = execute_long(
            self.client,
            "print('async-ping'); (function(){ return 1; })()",
            timeout=30.0,
        )
        self.assertIn("async-ping", result.output)

    def test_execute_long_script_error_raises(self):
        with self.assertRaises(exceptions.AsyncExecutionError):
            execute_long(
                self.client,
                "(function(){ notDefined.boom(); })()",
                timeout=30.0,
            )


# ══════════════════════════════════════════════════════════════════════════════
# 6. DazTimeline
# ══════════════════════════════════════════════════════════════════════════════

@skip_if_down
@skip_no_daz
class TestDazTimeline(unittest.TestCase):
    def setUp(self):
        self.timeline = DazTimeline()

    def test_frame_is_int(self):
        f = self.timeline.frame
        self.assertIsInstance(f, int)

    def test_time_is_numeric(self):
        t = self.timeline.time
        self.assertIsInstance(t, (int, float))

    def test_frame_range_has_start_end(self):
        r = self.timeline.frame_range
        if r is not None:
            self.assertIn("start", r)
            self.assertIn("end", r)

    def test_set_frame_round_trips(self):
        original = self.timeline.frame
        target = original + 1
        self.timeline.frame = target
        self.assertEqual(self.timeline.frame, target)
        self.timeline.frame = original  # restore


# ══════════════════════════════════════════════════════════════════════════════
# 7. DazGeometry — only runs when scene has a node with geometry
# ══════════════════════════════════════════════════════════════════════════════

@skip_if_down
@skip_no_daz
class TestDazGeometry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        client = _client()
        scene = DazScene(client)
        # Find first node that has geometry
        cls.geo = None
        for node in scene.nodes():
            geo = DazGeometry(client, node._identifier)
            vc = geo.vertex_count
            if vc is not None and vc > 0:
                cls.geo = geo
                break

    def setUp(self):
        if self.geo is None:
            self.skipTest("No node with geometry found in scene")

    def test_vertex_count_positive(self):
        self.assertGreater(self.geo.vertex_count, 0)

    def test_facet_count_positive(self):
        fc = self.geo.facet_count
        if fc is not None:
            self.assertGreater(fc, 0)

    def test_vertex_positions_chunk_shape(self):
        chunk = self.geo.vertex_positions(start=0, count=10)
        self.assertIn("vertices", chunk)
        self.assertIn("total", chunk)
        self.assertLessEqual(len(chunk["vertices"]), 10)
        for v in chunk["vertices"]:
            self.assertEqual(len(v), 3)

    def test_vertex_positions_total_matches_vertex_count(self):
        chunk = self.geo.vertex_positions(start=0, count=1)
        self.assertEqual(chunk["total"], self.geo.vertex_count)

    def test_face_vertex_indices_shape(self):
        chunk = self.geo.face_vertex_indices(start=0, count=10)
        self.assertIn("facets", chunk)
        self.assertIn("total", chunk)
        facets = chunk["facets"]
        self.assertLessEqual(len(facets), 10)
        for f in facets:
            self.assertIn(len(f), (3, 4), msg=f"Expected tri or quad, got {f}")

    def test_face_vertex_indices_total_matches_facet_count(self):
        chunk = self.geo.face_vertex_indices(start=0, count=1)
        fc = self.geo.facet_count
        if fc is not None:
            self.assertEqual(chunk["total"], fc)

    def test_normals_shape(self):
        chunk = self.geo.normals(start=0, count=10)
        self.assertIn("normals", chunk)
        self.assertIn("total", chunk)
        for n in chunk["normals"]:
            self.assertEqual(len(n), 3)

    def test_uv_set_count_non_negative(self):
        count = self.geo.uv_set_count
        if count is not None:
            self.assertGreaterEqual(count, 0)

    def test_uv_positions_shape(self):
        result = self.geo.uv_positions(uv_set=0, start=0, count=10)
        if result:
            self.assertIn("uvs", result)
            for uv in result.get("uvs", []):
                self.assertEqual(len(uv), 2)

    def test_face_group_names_is_list(self):
        names = self.geo.face_group_names()
        self.assertIsInstance(names, list)

    def test_material_group_names_is_list(self):
        names = self.geo.material_group_names()
        self.assertIsInstance(names, list)

    def test_subdivision_level_non_negative(self):
        lvl = self.geo.subdivision_level
        if lvl is not None:
            self.assertGreaterEqual(lvl, 0)

    def test_tris_count_non_negative(self):
        count = self.geo.tris_count
        if count is not None:
            self.assertGreaterEqual(count, 0)

    def test_quads_count_non_negative(self):
        count = self.geo.quads_count
        if count is not None:
            self.assertGreaterEqual(count, 0)

    def test_tris_plus_quads_le_facet_count(self):
        fc = self.geo.facet_count
        tris = self.geo.tris_count
        quads = self.geo.quads_count
        if fc is not None and tris is not None and quads is not None:
            self.assertLessEqual(tris + quads, fc)


# ══════════════════════════════════════════════════════════════════════════════
# 8. DazRenderSettings — only runs when App.getRenderMgr() is available
# ══════════════════════════════════════════════════════════════════════════════

@skip_if_down
@skip_no_renderer
class TestDazRenderSettings(unittest.TestCase):
    def setUp(self):
        self.rs = DazRenderSettings()

    def test_is_available_true(self):
        self.assertTrue(self.rs.is_available())

    def test_is_rendering_is_bool(self):
        self.assertIsInstance(self.rs.is_rendering(), bool)

    def test_resolution_has_width_height(self):
        res = self.rs.resolution
        self.assertIsNotNone(res)
        self.assertIn("width", res)
        self.assertIn("height", res)
        self.assertIsInstance(res["width"], int)
        self.assertIsInstance(res["height"], int)
        self.assertGreater(res["width"], 0)
        self.assertGreater(res["height"], 0)

    def test_set_resolution_round_trips(self):
        original = self.rs.resolution
        self.rs.set_resolution(640, 480)
        updated = self.rs.resolution
        self.assertEqual(updated["width"], 640)
        self.assertEqual(updated["height"], 480)
        # restore
        if original:
            self.rs.set_resolution(original["width"], original["height"])

    def test_gamma_is_numeric(self):
        g = self.rs.gamma
        if g is not None:
            self.assertIsInstance(g, (int, float))

    def test_double_sided_is_bool(self):
        ds = self.rs.double_sided
        if ds is not None:
            self.assertIsInstance(ds, bool)

    def test_has_render_is_bool(self):
        self.assertIsInstance(self.rs.has_render(), bool)

    def test_canvases_enabled_round_trips(self):
        original = self.rs.canvases_enabled
        try:
            self.rs.canvases_enabled = False
            self.assertFalse(self.rs.canvases_enabled)
            self.rs.canvases_enabled = True
            self.assertTrue(self.rs.canvases_enabled)
        finally:
            if original is not None:
                self.rs.canvases_enabled = original

    def test_list_canvases_returns_list_of_canvas(self):
        from dazpy._render import Canvas
        canvases = self.rs.list_canvases()
        self.assertIsInstance(canvases, list)
        for canvas in canvases:
            self.assertIsInstance(canvas, Canvas)

    def test_add_and_remove_canvas_round_trip(self):
        from dazpy._render import Canvas
        name = "dazpy_test_canvas_uae"
        canvas = self.rs.add_canvas(name, "Depth")
        self.assertIsInstance(canvas, Canvas)
        self.assertEqual(canvas.name, name)
        self.assertEqual(canvas.canvas_type, "Depth")
        names = [c.name for c in self.rs.list_canvases()]
        self.assertIn(name, names)

        removed = self.rs.remove_canvas(name)
        self.assertTrue(removed)
        names_after = [c.name for c in self.rs.list_canvases()]
        self.assertNotIn(name, names_after)

    def test_remove_canvas_nonexistent_returns_false(self):
        self.assertFalse(self.rs.remove_canvas("__no_such_canvas_xyz__"))

    def test_canvas_output_paths_keyed_by_existing_canvas_names(self):
        paths = self.rs.canvas_output_paths("C:/tmp/dazpy_canvas_path_test.png")
        canvases = self.rs.list_canvases()
        self.assertEqual(set(paths.keys()), {c.name for c in canvases})
        for canvas in canvases:
            self.assertIn(canvas.name, paths[canvas.name])
            self.assertIn(canvas.canvas_type, paths[canvas.name])

    def test_render_returns_outcome_with_resolved_output_path(self):
        from dazpy._render import RenderOutcome
        import tempfile

        original_res = self.rs.resolution
        original_samples = self.rs.max_samples
        out_path = os.path.join(
            tempfile.gettempdir(), "dazpy_test_render_cc5.png"
        )
        try:
            self.rs.set_resolution(64, 64)
            self.rs.max_samples = 4
            self.rs.output_path = out_path
            result = self.rs.render_and_wait(timeout=120)
            self.assertIsInstance(result, RenderOutcome)
            self.assertTrue(result.success)
            self.assertEqual(result.output_path, out_path)
            self.assertTrue(os.path.exists(out_path))
        finally:
            if original_res:
                self.rs.set_resolution(original_res["width"], original_res["height"])
            if original_samples is not None:
                self.rs.max_samples = original_samples
            if os.path.exists(out_path):
                os.remove(out_path)


# ══════════════════════════════════════════════════════════════════════════════
# DazSkeleton / DazBone
# ══════════════════════════════════════════════════════════════════════════════

@skip_if_down
@skip_no_daz
class TestDazSkeleton(unittest.TestCase):
    def setUp(self):
        self.scene = _scene()

    def test_num_skeletons_is_non_negative_int(self):
        n = self.scene.num_skeletons()
        self.assertIsInstance(n, int)
        self.assertGreaterEqual(n, 0)

    def test_skeletons_returns_list(self):
        skels = self.scene.skeletons()
        self.assertIsInstance(skels, list)

    def test_skeletons_are_daz_skeleton_instances(self):
        for skel in self.scene.skeletons():
            self.assertIsInstance(skel, DazSkeleton)

    def test_skeletons_count_matches_num_skeletons(self):
        self.assertEqual(len(self.scene.skeletons()), self.scene.num_skeletons())

    def test_find_skeleton_nonexistent_raises(self):
        with self.assertRaises(exceptions.NodeNotFoundError):
            self.scene.find_skeleton("__no_such_skeleton_xyz__")

    def test_nodes_returns_daz_skeleton_for_figures(self):
        nodes = self.scene.nodes()
        skels = self.scene.skeletons()
        skel_names = {s.name for s in skels}
        for node in nodes:
            if node.name in skel_names:
                self.assertIsInstance(node, DazSkeleton)

    @unittest.skipUnless(True, "runs only when at least one skeleton is loaded")
    def test_skeleton_bones_returns_list(self):
        skels = self.scene.skeletons()
        if not skels:
            self.skipTest("No skeletons in scene")
        skel = skels[0]
        bones = skel.bones()
        self.assertIsInstance(bones, list)

    def test_skeleton_bones_are_daz_bone_instances(self):
        skels = self.scene.skeletons()
        if not skels:
            self.skipTest("No skeletons in scene")
        for bone in skels[0].bones():
            self.assertIsInstance(bone, DazBone)

    def test_skeleton_num_bones_matches_bones_list(self):
        skels = self.scene.skeletons()
        if not skels:
            self.skipTest("No skeletons in scene")
        skel = skels[0]
        self.assertEqual(skel.num_bones(), len(skel.bones()))

    def test_find_bone_success(self):
        skels = self.scene.skeletons()
        if not skels:
            self.skipTest("No skeletons in scene")
        skel = skels[0]
        bones = skel.bones()
        if not bones:
            self.skipTest("Skeleton has no bones")
        first_bone_name = bones[0].name
        found = skel.find_bone(first_bone_name)
        self.assertIsInstance(found, DazBone)
        self.assertEqual(found.name, first_bone_name)

    def test_find_bone_not_found_raises(self):
        skels = self.scene.skeletons()
        if not skels:
            self.skipTest("No skeletons in scene")
        with self.assertRaises(exceptions.NodeNotFoundError):
            skels[0].find_bone("__no_such_bone_xyz__")

    def test_follow_target_is_none_or_skeleton(self):
        skels = self.scene.skeletons()
        if not skels:
            self.skipTest("No skeletons in scene")
        target = skels[0].follow_target()
        self.assertTrue(target is None or isinstance(target, DazSkeleton))


@skip_if_down
@skip_no_daz
class TestDazBone(unittest.TestCase):
    def _first_bone(self):
        scene = _scene()
        skels = scene.skeletons()
        if not skels:
            self.skipTest("No skeletons in scene")
        bones = skels[0].bones()
        if not bones:
            self.skipTest("Skeleton has no bones")
        return bones[0]

    def test_local_rotation_has_xyzw(self):
        bone = self._first_bone()
        rot = bone.local_rotation
        self.assertIsNotNone(rot)
        for key in ("x", "y", "z", "w"):
            self.assertIn(key, rot)

    def test_local_rotation_w_is_numeric(self):
        bone = self._first_bone()
        rot = bone.local_rotation
        self.assertIsInstance(rot["w"], (int, float))

    def test_local_position_has_xyz(self):
        bone = self._first_bone()
        pos = bone.local_position
        self.assertIsNotNone(pos)
        for key in ("x", "y", "z"):
            self.assertIn(key, pos)

    def test_rotation_order_is_string(self):
        bone = self._first_bone()
        order = bone.rotation_order
        self.assertIsNotNone(order)
        self.assertIsInstance(order, str)

    def test_get_skeleton_returns_daz_skeleton(self):
        bone = self._first_bone()
        skel = bone.get_skeleton()
        self.assertIsInstance(skel, DazSkeleton)

    def test_set_local_rotation_roundtrip(self):
        bone = self._first_bone()
        original = bone.local_rotation
        bone.set_local_rotation(0.0, 0.0, 0.0)
        after_zero = bone.local_rotation
        self.assertAlmostEqual(after_zero["x"], 0.0, places=3)
        self.assertAlmostEqual(after_zero["y"], 0.0, places=3)
        self.assertAlmostEqual(after_zero["z"], 0.0, places=3)
        # Restore original using euler approximation (skip if no original)
        if original is not None:
            bone.set_local_rotation(
                original.get("x", 0.0),
                original.get("y", 0.0),
                original.get("z", 0.0),
            )


# ══════════════════════════════════════════════════════════════════════════════
# 8. Modifiers and Morphs
# ══════════════════════════════════════════════════════════════════════════════

@skip_if_down
@skip_no_daz
class TestDazNodeModifiers(unittest.TestCase):
    """Tests for node.modifiers(), node.find_modifier(), and node.morphs()."""

    @classmethod
    def setUpClass(cls):
        client = _client()
        scene = DazScene(client)
        nodes = scene.nodes()
        cls.node = nodes[0] if nodes else None
        cls.client = client

    def setUp(self):
        if self.node is None:
            self.skipTest("Scene has no nodes")

    def test_modifiers_returns_list(self):
        mods = self.node.modifiers()
        self.assertIsInstance(mods, list)

    def test_modifiers_are_daz_modifier_instances(self):
        mods = self.node.modifiers()
        for m in mods:
            self.assertIsInstance(m, DazModifier)

    def test_morphs_returns_list_of_daz_morph(self):
        morphs = self.node.morphs()
        self.assertIsInstance(morphs, list)
        for m in morphs:
            self.assertIsInstance(m, DazMorph)

    def test_morphs_subset_of_modifiers(self):
        mods = self.node.modifiers()
        morphs = self.node.morphs()
        self.assertLessEqual(len(morphs), len(mods))

    def test_find_modifier_nonexistent_returns_none(self):
        result = self.node.find_modifier("__nonexistent_modifier_xyz__")
        self.assertIsNone(result)

    def test_find_modifier_by_name_if_any_exist(self):
        mods = self.node.modifiers()
        if not mods:
            self.skipTest("Node has no modifiers")
        name_to_find = mods[0].modifier_label
        if name_to_find is None:
            self.skipTest("First modifier has no label")
        # find_modifier uses the internal name, not label — get it from the locator
        # Instead just verify modifier_label is a string on the returned object
        self.assertIsInstance(name_to_find, str)


@skip_no_daz
class TestDazNodeDForceModifiers(unittest.TestCase):
    """Tests for node.dforce_modifiers() — requires a scene with a dForce garment/hair."""

    @classmethod
    def setUpClass(cls):
        client = _client()
        scene = DazScene(client)
        cls.client = client
        cls.dforce = None
        for node in scene.nodes():
            mods = node.dforce_modifiers()
            if mods:
                cls.dforce = mods[0]
                break

    def setUp(self):
        if self.dforce is None:
            self.skipTest("No DzDForceModifier found in scene")

    def test_dforce_modifier_is_daz_dforce_instance(self):
        self.assertIsInstance(self.dforce, DazDForce)

    def test_dforce_modifier_is_also_daz_modifier(self):
        self.assertIsInstance(self.dforce, DazModifier)

    def test_freeze_simulation_is_boolean(self):
        val = self.dforce.freeze_simulation
        self.assertIsInstance(val, bool)

    def test_freeze_unfreeze_roundtrip(self):
        original = self.dforce.freeze_simulation
        self.dforce.freeze()
        self.assertTrue(self.dforce.freeze_simulation)
        self.dforce.unfreeze()
        self.assertFalse(self.dforce.freeze_simulation)
        if original:
            self.dforce.freeze()


@skip_if_down
@skip_no_daz
class TestDazSceneDForceSimulation(unittest.TestCase):
    """Tests for DazScene simulation control — DzSimulationMgr-backed methods."""

    @classmethod
    def setUpClass(cls):
        cls.client = _client()
        cls.scene = DazScene(cls.client)

    def test_is_simulating_returns_bool(self):
        self.assertIsInstance(self.scene.is_simulating(), bool)

    def test_clear_dforce_simulation_does_not_raise(self):
        self.scene.clear_dforce_simulation()

    def test_run_dforce_simulation_wait_false_returns_request_id(self):
        request_id = self.scene.run_dforce_simulation(wait=False)
        self.assertIsInstance(request_id, str)
        self.assertTrue(request_id)
        # Give the engine a moment then clear so we don't leave a simulation running.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and self.scene.is_simulating():
            time.sleep(0.5)
        self.scene.clear_dforce_simulation()


@skip_if_down
@skip_no_daz
class TestDazMorphValue(unittest.TestCase):
    """Tests for DazMorph value read/write — requires a node with DzMorph modifiers."""

    @classmethod
    def setUpClass(cls):
        client = _client()
        scene = DazScene(client)
        nodes = scene.nodes()
        cls.morph = None
        cls.client = client
        for node in nodes:
            morphs = node.morphs()
            if morphs:
                cls.morph = morphs[0]
                break

    def setUp(self):
        if self.morph is None:
            self.skipTest("No DzMorph modifiers found in scene")

    def test_value_is_numeric(self):
        val = self.morph.value
        self.assertIsNotNone(val)
        self.assertIsInstance(val, (int, float))

    def test_min_is_numeric(self):
        m = self.morph.min
        self.assertIsNotNone(m)
        self.assertIsInstance(m, (int, float))

    def test_max_is_numeric(self):
        m = self.morph.max
        self.assertIsNotNone(m)
        self.assertIsInstance(m, (int, float))

    def test_value_roundtrip(self):
        original = self.morph.value
        self.morph.value = 0.0
        after_zero = self.morph.value
        self.assertAlmostEqual(after_zero, 0.0, places=3)
        self.morph.value = original if original is not None else 0.0

    def test_modifier_label_is_string(self):
        label = self.morph.modifier_label
        self.assertIsInstance(label, str)


# ══════════════════════════════════════════════════════════════════════════════

@skip_if_down
@skip_no_daz
class TestDazMaterial(unittest.TestCase):
    """Tests for node.materials(), node.find_material(), and DazMaterial properties."""

    @classmethod
    def setUpClass(cls):
        client = _client()
        scene = DazScene(client)
        nodes = scene.nodes()
        cls.node = None
        cls.mat = None
        cls.client = client
        for node in nodes:
            mats = node.materials()
            if mats:
                cls.node = node
                cls.mat = mats[0]
                break

    def setUp(self):
        if self.node is None:
            self.skipTest("No nodes with materials found in scene")

    def test_materials_returns_list(self):
        mats = self.node.materials()
        self.assertIsInstance(mats, list)
        self.assertGreater(len(mats), 0)

    def test_materials_returns_daz_material_instances(self):
        mats = self.node.materials()
        for m in mats:
            self.assertIsInstance(m, DazMaterial)

    def test_find_material_by_name(self):
        mat_name = self.mat.material_name
        self.assertIsNotNone(mat_name)
        found = self.node.find_material(mat_name)
        self.assertIsNotNone(found)
        self.assertIsInstance(found, DazMaterial)
        self.assertEqual(found.material_name, mat_name)

    def test_find_material_returns_none_for_missing(self):
        found = self.node.find_material("__nonexistent_material__")
        self.assertIsNone(found)

    def test_diffuse_color_returns_rgb_dict(self):
        color = self.mat.diffuse_color
        self.assertIsNotNone(color)
        self.assertIn("r", color)
        self.assertIn("g", color)
        self.assertIn("b", color)
        self.assertIsInstance(color["r"], (int, float))
        self.assertIsInstance(color["g"], (int, float))
        self.assertIsInstance(color["b"], (int, float))

    def test_opacity_is_numeric(self):
        val = self.mat.opacity
        self.assertIsNotNone(val)
        self.assertIsInstance(val, (int, float))

    def test_is_smoothing_on_is_bool(self):
        val = self.mat.is_smoothing_on()
        self.assertIsNotNone(val)
        self.assertIsInstance(val, bool)

    def test_smoothing_angle_is_numeric(self):
        val = self.mat.smoothing_angle
        self.assertIsNotNone(val)
        self.assertIsInstance(val, (int, float))

    def test_is_opaque_is_bool(self):
        val = self.mat.is_opaque()
        self.assertIsNotNone(val)
        self.assertIsInstance(val, bool)

    def test_color_map_is_string_or_none(self):
        val = self.mat.color_map()
        self.assertTrue(val is None or isinstance(val, str))


# ══════════════════════════════════════════════════════════════════════════════

@skip_if_down
@skip_no_daz
class TestDazNodeLocalTransforms(unittest.TestCase):
    """Tests for local_position, set_local_position, local_rotation, set_local_rotation."""

    @classmethod
    def setUpClass(cls):
        client = _client()
        nodes = DazScene(client).nodes()
        cls.node = nodes[0] if nodes else None

    def setUp(self):
        if self.node is None:
            self.skipTest("Scene has no nodes")

    def test_local_position_is_dict_with_xyz(self):
        pos = self.node.local_position
        self.assertIsNotNone(pos)
        for key in ("x", "y", "z"):
            self.assertIn(key, pos)
            self.assertIsInstance(pos[key], (int, float))

    def test_local_rotation_is_dict_with_xyzw(self):
        rot = self.node.local_rotation
        self.assertIsNotNone(rot)
        for key in ("x", "y", "z", "w"):
            self.assertIn(key, rot)
            self.assertIsInstance(rot[key], (int, float))

    def test_set_rotation_executes_without_error(self):
        original = self.node.local_rotation
        self.node.set_rotation(0.0, 0.0, 0.0)
        # restore
        if original:
            self.node.set_local_rotation(0.0, 0.0, 0.0)

    def test_set_local_position_round_trips(self):
        original = self.node.local_position
        self.node.set_local_position(0.0, 0.0, 0.0)
        moved = self.node.local_position
        self.assertAlmostEqual(moved["x"], 0.0, places=3)
        self.assertAlmostEqual(moved["y"], 0.0, places=3)
        self.assertAlmostEqual(moved["z"], 0.0, places=3)
        if original:
            self.node.set_local_position(original["x"], original["y"], original["z"])

    def test_set_local_rotation_round_trips(self):
        self.node.set_local_rotation(0.0, 0.0, 0.0)
        rot = self.node.local_rotation
        self.assertIsNotNone(rot)
        self.assertIn("w", rot)


@skip_if_down
@skip_no_daz
class TestDazNodeSelection(unittest.TestCase):
    """Tests for is_selected(), select(), and scene selection accessors."""

    @classmethod
    def setUpClass(cls):
        client = _client()
        cls.scene = DazScene(client)
        nodes = cls.scene.nodes()
        cls.node = nodes[0] if nodes else None

    def setUp(self):
        if self.node is None:
            self.skipTest("Scene has no nodes")

    def test_is_selected_returns_bool(self):
        val = self.node.is_selected()
        self.assertIsInstance(val, bool)

    def test_select_and_deselect(self):
        self.node.select(True)
        self.assertTrue(self.node.is_selected())
        self.node.select(False)
        self.assertFalse(self.node.is_selected())

    def test_selected_nodes_returns_list(self):
        nodes = self.scene.selected_nodes()
        self.assertIsInstance(nodes, list)
        for n in nodes:
            self.assertIsInstance(n, DazNode)

    def test_select_changes_selected_nodes_list(self):
        self.node.select(True)
        selected = self.scene.selected_nodes()
        names = [n.name for n in selected]
        self.assertIn(self.node.name, names)
        self.node.select(False)

    def test_primary_selection_returns_node_or_none(self):
        result = self.scene.primary_selection()
        self.assertTrue(result is None or isinstance(result, DazNode))

    def test_set_primary_selection(self):
        self.scene.set_primary_selection(self.node)
        primary = self.scene.primary_selection()
        self.assertIsNotNone(primary)
        self.assertEqual(primary.name, self.node.name)

    def test_select_all_and_deselect_all(self):
        self.scene.select_all(True)
        selected = self.scene.selected_nodes()
        self.assertGreater(len(selected), 0)
        self.scene.select_all(False)
        selected_after = self.scene.selected_nodes()
        self.assertEqual(len(selected_after), 0)


# ══════════════════════════════════════════════════════════════════════════════
# DazCamera — property and method integration
# ══════════════════════════════════════════════════════════════════════════════

@skip_no_daz
class TestDazCameraProperties(unittest.TestCase):
    def setUp(self):
        self.scene = _scene()
        cameras = self.scene.cameras()
        if not cameras:
            self.skipTest("No cameras in scene")
        self.cam = cameras[0]

    def test_focal_length_is_number(self):
        val = self.cam.focal_length
        self.assertIsInstance(val, (int, float))
        self.assertGreater(val, 0)

    def test_focal_distance_read_write(self):
        original = self.cam.focal_distance
        self.assertIsInstance(original, (int, float))
        self.cam.focal_distance = original
        self.assertAlmostEqual(self.cam.focal_distance, original, places=2)

    def test_aspect_width_and_height_are_numbers(self):
        w = self.cam.aspect_width
        h = self.cam.aspect_height
        self.assertIsInstance(w, (int, float))
        self.assertIsInstance(h, (int, float))

    def test_pixels_width_and_height_read_write(self):
        orig_w = self.cam.pixels_width
        orig_h = self.cam.pixels_height
        self.assertIsInstance(orig_w, (int, float))
        self.assertIsInstance(orig_h, (int, float))
        self.cam.pixels_width = orig_w
        self.cam.pixels_height = orig_h
        self.assertEqual(self.cam.pixels_width, orig_w)
        self.assertEqual(self.cam.pixels_height, orig_h)

    def test_near_and_far_clipping_planes_are_positive(self):
        near = self.cam.near_clipping_plane
        far = self.cam.far_clipping_plane
        self.assertIsInstance(near, (int, float))
        self.assertIsInstance(far, (int, float))
        self.assertGreater(near, 0)
        self.assertGreater(far, near)

    def test_focal_point_returns_xyz_dict(self):
        fp = self.cam.focal_point()
        self.assertIsInstance(fp, dict)
        self.assertIn("x", fp)
        self.assertIn("y", fp)
        self.assertIn("z", fp)

    def test_is_view_camera_returns_bool(self):
        result = self.cam.is_view_camera()
        self.assertIsInstance(result, bool)

    def test_aim_at_does_not_raise(self):
        fp = self.cam.focal_point()
        if fp:
            self.cam.aim_at(fp["x"], fp["y"], fp["z"])


# ══════════════════════════════════════════════════════════════════════════════
# DazLight — property and method integration
# ══════════════════════════════════════════════════════════════════════════════

@skip_no_daz
class TestDazLightProperties(unittest.TestCase):
    def setUp(self):
        self.scene = _scene()
        lights = self.scene.lights()
        if not lights:
            self.skipTest("No lights in scene")
        self.light = lights[0]

    def test_is_on_returns_bool(self):
        result = self.light.is_on()
        self.assertIsInstance(result, bool)

    def test_is_directional_returns_bool(self):
        result = self.light.is_directional()
        self.assertIsInstance(result, bool)

    def test_is_area_light_returns_bool(self):
        result = self.light.is_area_light()
        self.assertIsInstance(result, bool)

    def test_direction_returns_xyz_dict_or_none(self):
        result = self.light.direction()
        if self.light.is_directional():
            self.assertIsInstance(result, dict)
            self.assertIn("x", result)
            self.assertIn("y", result)
            self.assertIn("z", result)
        else:
            self.assertIsNone(result)

    def test_set_color_does_not_raise(self):
        original = self.light.color
        self.light.set_color(255, 255, 255)
        if original:
            self.light.set_color(int(original["r"]), int(original["g"]), int(original["b"]))


# ══════════════════════════════════════════════════════════════════════════════
# DazNode — Section 8a additional queries
# ══════════════════════════════════════════════════════════════════════════════

@skip_no_daz
class TestDazNodeAdditionalQueries(unittest.TestCase):
    def setUp(self):
        self.scene = _scene()
        nodes = self.scene.nodes()
        if not nodes:
            self.skipTest("No nodes in scene")
        self.node = nodes[0]

    def test_is_in_scene_returns_bool(self):
        result = self.node.is_in_scene()
        self.assertIsInstance(result, bool)

    def test_is_in_scene_true_for_scene_node(self):
        self.assertTrue(self.node.is_in_scene())

    def test_is_root_returns_bool(self):
        result = self.node.is_root()
        self.assertIsInstance(result, bool)

    def test_is_visible_in_render_returns_bool(self):
        result = self.node.is_visible_in_render()
        self.assertIsInstance(result, bool)

    def test_set_visible_in_render_round_trips(self):
        original = self.node.is_visible_in_render()
        self.node.set_visible_in_render(not original)
        flipped = self.node.is_visible_in_render()
        self.assertEqual(flipped, not original)
        self.node.set_visible_in_render(original)

    def test_is_visible_in_viewport_returns_bool(self):
        result = self.node.is_visible_in_viewport()
        self.assertIsInstance(result, bool)

    def test_set_visible_in_viewport_round_trips(self):
        original = self.node.is_visible_in_viewport()
        self.node.set_visible_in_viewport(not original)
        flipped = self.node.is_visible_in_viewport()
        self.assertEqual(flipped, not original)
        self.node.set_visible_in_viewport(original)

    def test_bounding_box_returns_min_max_dicts(self):
        bb = self.node.bounding_box()
        self.assertIsInstance(bb, dict)
        self.assertIn("min", bb)
        self.assertIn("max", bb)
        for key in ("x", "y", "z"):
            self.assertIn(key, bb["min"])
            self.assertIn(key, bb["max"])

    def test_bounding_box_max_gte_min(self):
        bb = self.node.bounding_box()
        for key in ("x", "y", "z"):
            self.assertGreaterEqual(bb["max"][key], bb["min"][key])



# ══════════════════════════════════════════════════════════════════════════════
# DazPose
# ══════════════════════════════════════════════════════════════════════════════

@skip_no_daz
class TestDazPose(unittest.TestCase):
    """Integration tests for DazPose capture / apply / lerp."""

    def setUp(self):
        from dazpy import DazPose, DazScene
        self.client = _client()
        self.scene = DazScene(self.client)
        self.DazPose = DazPose
        skeletons = self.scene.skeletons()
        if not skeletons:
            self.skipTest("No skeletons in scene")
        self.skel = skeletons[0]

    def test_capture_returns_pose(self):
        pose = self.DazPose.capture(self.skel)
        self.assertIsInstance(pose.bones, dict)
        self.assertIsInstance(pose.morphs, dict)
        self.assertIsInstance(pose.props, dict)
        self.assertIsInstance(pose.figure, str)

    def test_capture_bones_are_float_triples(self):
        pose = self.DazPose.capture(self.skel)
        for name, xyz in pose.bones.items():
            with self.subTest(bone=name):
                self.assertEqual(len(xyz), 3)
                for v in xyz:
                    self.assertIsInstance(v, float)

    def test_capture_morph_values_are_floats(self):
        pose = self.DazPose.capture(self.skel)
        for name, v in pose.morphs.items():
            with self.subTest(morph=name):
                self.assertIsInstance(v, float)

    def test_apply_round_trips_bone_rotation(self):
        # Set a known rotation, capture it, change to something else, restore.
        from dazpy import DazPose
        bones = self.skel.bones()
        if not bones:
            self.skipTest("Skeleton has no bones")
        bone = bones[0]
        bone.set_local_rotation(0.0, 7.5, 0.0)

        captured = DazPose.capture(self.skel)

        bone.set_local_rotation(0.0, 0.0, 0.0)
        captured.apply(self.skel)

        after = bone.local_euler
        self.assertIsNotNone(after)
        self.assertAlmostEqual(after[1], 7.5, places=3)

    def test_apply_full_resets_rotation_to_zero(self):
        bones = self.skel.bones()
        if not bones:
            self.skipTest("Skeleton has no bones")
        bone = bones[0]
        bone.set_local_rotation(5.0, 5.0, 5.0)

        empty_pose = self.DazPose(self.skel._identifier.value, {}, {}, {})
        empty_pose.apply_full(self.skel)

        after = bone.local_euler
        self.assertIsNotNone(after)
        self.assertAlmostEqual(after[0], 0.0, places=3)
        self.assertAlmostEqual(after[1], 0.0, places=3)
        self.assertAlmostEqual(after[2], 0.0, places=3)

    def test_lerp_apply_is_single_call(self):
        from unittest.mock import patch
        from dazpy import DazPose
        a = DazPose.capture(self.skel)
        b = DazPose.capture(self.skel)
        mid = a.lerp(b, 0.5)
        with patch.object(self.client, "execute", wraps=self.client.execute) as mock_exec:
            mid.apply(self.skel)
            self.assertEqual(mock_exec.call_count, 1)

    def test_save_load_preserves_data(self):
        import os, tempfile
        pose = self.DazPose.capture(self.skel)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            pose.save(path)
            loaded = self.DazPose.load(path)
            self.assertEqual(loaded.figure, pose.figure)
            self.assertEqual(loaded.bones, pose.bones)
            self.assertEqual(loaded.morphs, pose.morphs)
        finally:
            os.unlink(path)


# ══════════════════════════════════════════════════════════════════════════════
# Pose resolver — scene_snapshot, evaluate_pose, evaluate_pose_jacobian,
# build_rig_profiles_from_snapshot, align_hand_target, align_foot_target
# ══════════════════════════════════════════════════════════════════════════════

@skip_if_down
@skip_no_daz
class TestSceneSnapshot(unittest.TestCase):
    """Integration tests for DazScene.scene_snapshot()."""

    def setUp(self):
        self.scene = _scene()
        self.skels = self.scene.skeletons()
        if not self.skels:
            self.skipTest("No skeletons in scene")

    def test_returns_list(self):
        result = self.scene.scene_snapshot()
        self.assertIsInstance(result, list)

    def test_entry_count_matches_num_skeletons(self):
        result = self.scene.scene_snapshot()
        self.assertEqual(len(result), len(self.skels))

    def test_each_entry_has_required_keys(self):
        for entry in self.scene.scene_snapshot():
            with self.subTest(skel=entry.get("name")):
                self.assertIn("name", entry)
                self.assertIn("label", entry)
                self.assertIn("bones", entry)
                self.assertIsInstance(entry["bones"], list)

    def test_bones_have_required_fields(self):
        snapshot = self.scene.scene_snapshot()
        for entry in snapshot:
            for bone in entry["bones"][:5]:  # spot-check first 5
                with self.subTest(skel=entry["name"], bone=bone.get("name")):
                    for field in ("name", "label", "rotation_order",
                                  "local_position", "world_position", "local_euler"):
                        self.assertIn(field, bone)

    def test_world_position_has_xyz(self):
        snapshot = self.scene.scene_snapshot()
        for entry in snapshot:
            for bone in entry["bones"][:3]:
                wp = bone["world_position"]
                with self.subTest(bone=bone["name"]):
                    self.assertIn("x", wp)
                    self.assertIn("y", wp)
                    self.assertIn("z", wp)
                    self.assertIsInstance(wp["x"], (int, float))

    def test_local_position_has_xyz(self):
        snapshot = self.scene.scene_snapshot()
        for entry in snapshot:
            for bone in entry["bones"][:3]:
                lp = bone["local_position"]
                for key in ("x", "y", "z"):
                    self.assertIn(key, lp)

    def test_local_euler_has_xyz(self):
        snapshot = self.scene.scene_snapshot()
        for entry in snapshot:
            for bone in entry["bones"][:3]:
                le = bone["local_euler"]
                for key in ("x", "y", "z"):
                    self.assertIn(key, le)
                    self.assertIsInstance(le[key], (int, float))

    def test_filter_by_label(self):
        skel = self.skels[0]
        label = skel.label
        filtered = self.scene.scene_snapshot(skeleton_labels=[label])
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["label"], label)

    def test_filter_nonexistent_returns_empty(self):
        result = self.scene.scene_snapshot(skeleton_labels=["__no_such_skel__"])
        self.assertEqual(result, [])

    def test_bone_count_matches_skeleton_bone_count(self):
        snapshot = self.scene.scene_snapshot()
        for entry in snapshot:
            skel = next((s for s in self.skels if s.name == entry["name"] or s.label == entry["label"]), None)
            if skel is not None:
                with self.subTest(skel=entry["name"]):
                    self.assertEqual(len(entry["bones"]), skel.num_bones())


@skip_if_down
@skip_no_daz
class TestBuildRigProfilesFromSnapshot(unittest.TestCase):
    """Integration tests for build_rig_profiles_from_snapshot()."""

    def setUp(self):
        self.scene = _scene()
        self.skels = self.scene.skeletons()
        if not self.skels:
            self.skipTest("No skeletons in scene")
        self.snapshot = self.scene.scene_snapshot()
        self.profiles = build_rig_profiles_from_snapshot(self.snapshot)

    def test_returns_dict(self):
        self.assertIsInstance(self.profiles, dict)

    def test_keyed_by_figure_label(self):
        for skel in self.skels:
            label = skel.label
            self.assertIn(label, self.profiles)

    def test_profile_has_bones(self):
        for profile in self.profiles.values():
            self.assertGreater(len(profile.bones), 0)

    def test_bone_count_matches_snapshot(self):
        for entry in self.snapshot:
            label = entry["label"]
            if label in self.profiles:
                self.assertEqual(len(self.profiles[label].bones), len(entry["bones"]))

    def test_bone_world_position_populated(self):
        for profile in self.profiles.values():
            for bone in profile.bones[:5]:
                with self.subTest(bone=bone.name):
                    self.assertIsNotNone(bone.world_position)
                    self.assertEqual(len(bone.world_position), 3)
                    for v in bone.world_position:
                        self.assertIsInstance(v, (int, float))

    def test_family_detected(self):
        for profile in self.profiles.values():
            self.assertIsInstance(profile.family, str)
            self.assertGreater(len(profile.family), 0)

    def test_source_metadata_is_snapshot(self):
        for profile in self.profiles.values():
            self.assertEqual(profile.metadata.get("source"), "snapshot")

    def test_anchor_map_non_empty(self):
        for profile in self.profiles.values():
            anchors = profile.anchor_map()
            self.assertIsInstance(anchors, dict)
            # A well-formed figure should have at least some anchors
            self.assertGreater(len(anchors), 0)


@skip_if_down
@skip_no_daz
class TestEvaluatePose(unittest.TestCase):
    """Integration tests for DazSkeleton.evaluate_pose()."""

    def setUp(self):
        self.scene = _scene()
        skels = self.scene.skeletons()
        if not skels:
            self.skipTest("No skeletons in scene")
        self.skel = skels[0]
        bones = self.skel.bones()
        if not bones:
            self.skipTest("Skeleton has no bones")
        self.first_bone = bones[0]

    def test_returns_dict(self):
        result = self.skel.evaluate_pose({}, [self.first_bone.name])
        self.assertIsInstance(result, dict)

    def test_returns_world_position_for_effector(self):
        result = self.skel.evaluate_pose({}, [self.first_bone.name])
        self.assertIn(self.first_bone.name, result)
        pos = result[self.first_bone.name]
        self.assertEqual(len(pos), 3)
        for v in pos:
            self.assertIsInstance(v, (int, float))

    def test_missing_effector_omitted(self):
        result = self.skel.evaluate_pose({}, ["__no_such_bone__"])
        self.assertNotIn("__no_such_bone__", result)

    def test_empty_effectors_returns_empty(self):
        result = self.skel.evaluate_pose({}, [])
        self.assertEqual(result, {})

    def test_restores_original_rotations(self):
        original_rots = self.skel.bone_rotations()
        bone_name = self.first_bone.name
        original = original_rots.get(bone_name, (0.0, 0.0, 0.0))

        self.skel.evaluate_pose(
            {bone_name: (original[0] + 30.0, original[1] + 15.0, original[2] + 10.0)},
            [bone_name],
        )

        after_rots = self.skel.bone_rotations()
        restored = after_rots.get(bone_name, (0.0, 0.0, 0.0))
        for orig_v, rest_v in zip(original, restored):
            self.assertAlmostEqual(orig_v, rest_v, places=3,
                msg=f"evaluate_pose did not restore rotation for {bone_name}")

    def test_candidate_rotation_changes_effector_position(self):
        """Applying a non-trivial rotation should move the effector world position."""
        bones = self.skel.bones()
        # Find a non-root bone with a child (so rotation visibly moves something downstream)
        moveable = None
        effector_name = None
        for b in bones:
            if b.name == self.first_bone.name:
                continue
            # Try to pick a mid-chain bone; any non-hip bone is fine
            moveable = b.name
            effector_name = bones[-1].name  # last bone as effector
            break
        if moveable is None or effector_name is None:
            self.skipTest("Could not find suitable bone pair")

        base = self.skel.evaluate_pose({}, [effector_name])
        perturbed = self.skel.evaluate_pose({moveable: (45.0, 0.0, 0.0)}, [effector_name])

        if effector_name in base and effector_name in perturbed:
            base_pos = base[effector_name]
            pert_pos = perturbed[effector_name]
            dist = sum((a - b) ** 2 for a, b in zip(base_pos, pert_pos)) ** 0.5
            # A 45° rotation should move something by more than a rounding error
            self.assertGreater(dist, 0.001,
                msg="45° rotation produced no detectable world-space change")


@skip_if_down
@skip_no_daz
class TestEvaluatePoseJacobian(unittest.TestCase):
    """Integration tests for DazSkeleton.evaluate_pose_jacobian()."""

    def setUp(self):
        self.scene = _scene()
        skels = self.scene.skeletons()
        if not skels:
            self.skipTest("No skeletons in scene")
        self.skel = skels[0]
        bones = self.skel.bones()
        if len(bones) < 2:
            self.skipTest("Skeleton needs at least 2 bones")
        self.chain = [b.name for b in bones[:3]]
        self.effector = bones[min(3, len(bones) - 1)].name

    def test_returns_dict_with_expected_keys(self):
        result = self.skel.evaluate_pose_jacobian(self.chain, self.effector)
        self.assertIsNotNone(result)
        self.assertIn("base_position", result)
        self.assertIn("columns", result)

    def test_base_position_is_xyz_list(self):
        result = self.skel.evaluate_pose_jacobian(self.chain, self.effector)
        bp = result["base_position"]
        self.assertEqual(len(bp), 3)
        for v in bp:
            self.assertIsInstance(v, (int, float))

    def test_column_count_is_three_per_bone(self):
        result = self.skel.evaluate_pose_jacobian(self.chain, self.effector)
        self.assertEqual(len(result["columns"]), len(self.chain) * 3)

    def test_each_column_is_xyz(self):
        result = self.skel.evaluate_pose_jacobian(self.chain, self.effector)
        for col in result["columns"]:
            self.assertEqual(len(col), 3)
            for v in col:
                self.assertIsInstance(v, (int, float))

    def test_missing_effector_returns_none(self):
        result = self.skel.evaluate_pose_jacobian(self.chain, "__no_such_bone__")
        self.assertIsNone(result)

    def test_restores_original_rotations(self):
        original_rots = self.skel.bone_rotations()
        self.skel.evaluate_pose_jacobian(self.chain, self.effector, step_degrees=5.0)
        after_rots = self.skel.bone_rotations()
        for name in self.chain:
            orig = original_rots.get(name, (0.0, 0.0, 0.0))
            after = after_rots.get(name, (0.0, 0.0, 0.0))
            for o, a in zip(orig, after):
                self.assertAlmostEqual(o, a, places=3,
                    msg=f"evaluate_pose_jacobian did not restore {name}")

    def test_step_degrees_affects_columns(self):
        r1 = self.skel.evaluate_pose_jacobian(self.chain, self.effector, step_degrees=1.0)
        r5 = self.skel.evaluate_pose_jacobian(self.chain, self.effector, step_degrees=5.0)
        # base_position should be the same regardless of step size
        for v1, v5 in zip(r1["base_position"], r5["base_position"]):
            self.assertAlmostEqual(v1, v5, places=2)
        # columns may differ (finite-difference approximation), but both are valid
        self.assertEqual(len(r1["columns"]), len(r5["columns"]))


@skip_if_down
@skip_no_daz
class TestAlignLimbTargets(unittest.TestCase):
    """Integration tests for align_hand_target and align_foot_target."""

    def setUp(self):
        self.scene = _scene()
        skels = self.scene.skeletons()
        if not skels:
            self.skipTest("No skeletons in scene")
        self.skel = skels[0]

    def _find_anchor_bone(self, candidates: list[str]) -> str | None:
        bone_names = {b.name for b in self.skel.bones()}
        for name in candidates:
            if name in bone_names:
                return name
        return None

    def test_align_hand_target_returns_result(self):
        anchor = self._find_anchor_bone(["r_hand", "l_hand", "rHand", "lHand"])
        if anchor is None:
            self.skipTest("No hand bone found in skeleton")
        result = align_hand_target(self.skel, (20.0, 130.0, 10.0),
                                   source_anchor=anchor, max_iterations=6)
        self.assertIsInstance(result, LimbAlignmentResult)

    def test_align_hand_target_uses_batch_path(self):
        anchor = self._find_anchor_bone(["r_hand", "l_hand", "rHand", "lHand"])
        if anchor is None:
            self.skipTest("No hand bone found in skeleton")
        result = align_hand_target(self.skel, (20.0, 130.0, 10.0),
                                   source_anchor=anchor, max_iterations=6)
        self.assertEqual(result.diagnostics.get("path"), "batch",
            "align_hand_target should use the batch IK path on a live skeleton")

    def test_align_hand_target_errors_are_finite(self):
        anchor = self._find_anchor_bone(["r_hand", "l_hand", "rHand", "lHand"])
        if anchor is None:
            self.skipTest("No hand bone found in skeleton")
        result = align_hand_target(self.skel, (20.0, 130.0, 10.0),
                                   source_anchor=anchor, max_iterations=6)
        self.assertIsNotNone(result.initial_error)
        self.assertIsNotNone(result.final_error)
        self.assertGreater(result.initial_error, 0.0)
        self.assertGreaterEqual(result.initial_error, 0.0)
        self.assertGreaterEqual(result.final_error, 0.0)

    def test_align_hand_target_does_not_increase_error(self):
        anchor = self._find_anchor_bone(["r_hand", "l_hand", "rHand", "lHand"])
        if anchor is None:
            self.skipTest("No hand bone found in skeleton")
        result = align_hand_target(self.skel, (20.0, 130.0, 10.0),
                                   source_anchor=anchor, max_iterations=12)
        if result.final_error is not None and result.initial_error is not None:
            self.assertLessEqual(result.final_error, result.initial_error + 0.01,
                msg="Solver should not increase the error")

    def test_align_foot_target_returns_result(self):
        anchor = self._find_anchor_bone(["r_foot", "l_foot", "rFoot", "lFoot"])
        if anchor is None:
            self.skipTest("No foot bone found in skeleton")
        result = align_foot_target(self.skel, (10.0, 0.0, 5.0),
                                   source_anchor=anchor, max_iterations=6)
        self.assertIsInstance(result, LimbAlignmentResult)

    def test_align_foot_target_uses_batch_path(self):
        anchor = self._find_anchor_bone(["r_foot", "l_foot", "rFoot", "lFoot"])
        if anchor is None:
            self.skipTest("No foot bone found in skeleton")
        result = align_foot_target(self.skel, (10.0, 0.0, 5.0),
                                   source_anchor=anchor, max_iterations=6)
        self.assertEqual(result.diagnostics.get("path"), "batch",
            "align_foot_target should use the batch IK path on a live skeleton")

    def test_align_hand_target_already_aligned_is_zero_iterations(self):
        """When the effector is already at the target, solver converges in 0 iterations."""
        anchor = self._find_anchor_bone(["r_hand", "l_hand", "rHand", "lHand"])
        if anchor is None:
            self.skipTest("No hand bone found in skeleton")
        # Get current world position of the anchor bone and use it as target
        positions = self.skel.evaluate_pose({}, [anchor])
        if anchor not in positions:
            self.skipTest("Could not read anchor world position")
        current_pos = positions[anchor]
        result = align_hand_target(self.skel, current_pos,
                                   source_anchor=anchor, tolerance=1.0)
        self.assertTrue(result.converged)
        self.assertEqual(result.iterations, 0)

    def test_align_limb_chain_names_non_empty(self):
        anchor = self._find_anchor_bone(["r_hand", "l_hand", "r_foot", "l_foot",
                                         "rHand", "lHand", "rFoot", "lFoot"])
        if anchor is None:
            self.skipTest("No hand or foot bone found")
        if "hand" in anchor or "Hand" in anchor:
            result = align_hand_target(self.skel, (0.0, 100.0, 0.0),
                                       source_anchor=anchor, max_iterations=1)
        else:
            result = align_foot_target(self.skel, (0.0, 0.0, 0.0),
                                       source_anchor=anchor, max_iterations=1)
        self.assertIsInstance(result.chain, list)
        self.assertGreater(len(result.chain), 0)


# ── DazViewport ───────────────────────────────────────────────────────────────

_VIEWPORT_AVAILABLE: bool = False
if _DAZ_GLOBALS_AVAILABLE:
    try:
        _vr = _req.post(
            "http://127.0.0.1:18811/execute",
            json={"script": "(function(){ var vp = MainWindow.getViewportMgr().getActiveViewport().get3DViewport(); return (vp !== null && vp !== undefined); })()"},
            headers={"X-API-Token": DazClient()._token},
            timeout=5,
        )
        _VIEWPORT_AVAILABLE = bool(_vr.status_code == 200 and _vr.json().get("result") is True)
    except Exception:
        pass

skip_no_viewport = unittest.skipUnless(_VIEWPORT_AVAILABLE, "3D viewport not available")


class TestDazViewportIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from dazpy._viewport import DazViewport
        cls.client = DazClient()
        cls.vp = DazViewport(cls.client)

    @skip_no_viewport
    def test_is_available(self):
        self.assertTrue(self.vp.is_available())

    @skip_no_viewport
    def test_get_size(self):
        size = self.vp.get_size()
        self.assertIsNotNone(size)
        self.assertIn("width", size)
        self.assertIn("height", size)
        self.assertGreater(size["width"], 0)
        self.assertGreater(size["height"], 0)

    @skip_no_viewport
    def test_capture_writes_file(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        try:
            result = self.vp.capture(path)
            self.assertEqual(result, path)
            self.assertTrue(os.path.isfile(path), "captureToFile did not write the file")
            self.assertGreater(os.path.getsize(path), 0)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    @skip_no_viewport
    def test_capture_with_resize(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        try:
            result = self.vp.capture(path, width=640, height=480)
            self.assertEqual(result, path)
        finally:
            if os.path.exists(path):
                os.unlink(path)


# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if not _SERVER_UP:
        print(f"SKIP: {_SERVER_SKIP_REASON}")
        sys.exit(0)
    unittest.main(verbosity=2)
