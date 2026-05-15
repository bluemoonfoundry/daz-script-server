"""Unit tests for dazpy — mock DazClient.execute() to verify script generation."""

import json
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, ".")

from dazpy._result import ExecutionResult
from dazpy._script_builder import ScriptBuilder
from dazpy._batch import Batch
from dazpy._node import DazNode, NodeIdentifier
from dazpy._scene import DazScene
from dazpy._client import DazClient
from dazpy import exceptions


def _make_client(return_value=None, output=None):
    client = MagicMock(spec=DazClient)
    client.execute.return_value = ExecutionResult(
        value=return_value,
        output=output or [],
        request_id="test1234",
    )
    return client


class TestScriptBuilder(unittest.TestCase):
    def test_escape_string_basic(self):
        self.assertEqual(ScriptBuilder.escape_string("hello"), '"hello"')

    def test_escape_string_quotes(self):
        result = ScriptBuilder.escape_string('say "hi"')
        self.assertIn('\\"', result)

    def test_escape_string_backslash(self):
        result = ScriptBuilder.escape_string("C:\\path\\file")
        self.assertIn("\\\\", result)

    def test_escape_string_newline(self):
        result = ScriptBuilder.escape_string("line1\nline2")
        self.assertIn("\\n", result)

    def test_escape_string_null_byte(self):
        result = ScriptBuilder.escape_string("null\x00byte")
        self.assertIn("\\u0000", result)

    def test_iife_wraps_body(self):
        result = ScriptBuilder.iife("return 42;")
        self.assertTrue(result.startswith("(function(){"))
        self.assertIn("return 42;", result)
        self.assertTrue(result.rstrip().endswith(")()"))

    def test_find_node_by_name(self):
        ident = NodeIdentifier("Genesis9", kind="name")
        expr = ScriptBuilder.find_node_expr(ident)
        self.assertIn('Scene.findNode(', expr)
        self.assertIn('"Genesis9"', expr)

    def test_find_node_by_label(self):
        ident = NodeIdentifier("Genesis 9", kind="label")
        expr = ScriptBuilder.find_node_expr(ident)
        self.assertIn('Scene.findNodeByLabel(', expr)
        self.assertIn('"Genesis 9"', expr)

    def test_serialize_arg_bool(self):
        self.assertEqual(ScriptBuilder.serialize_arg(True), "true")
        self.assertEqual(ScriptBuilder.serialize_arg(False), "false")

    def test_serialize_arg_int(self):
        self.assertEqual(ScriptBuilder.serialize_arg(42), "42")

    def test_serialize_arg_float(self):
        self.assertEqual(ScriptBuilder.serialize_arg(3.14), "3.14")

    def test_serialize_arg_string(self):
        self.assertEqual(ScriptBuilder.serialize_arg("hi"), '"hi"')

    def test_serialize_arg_dict(self):
        result = ScriptBuilder.serialize_arg({"x": 1})
        parsed = json.loads(result)
        self.assertEqual(parsed, {"x": 1})


class TestInjectionSafety(unittest.TestCase):
    """Adversarial strings must not break the generated script syntax."""

    ADVERSARIAL = [
        'say "hello"',
        "it's a test",
        "line1\nline2",
        "tab\there",
        "back\\slash",
        "null\x00byte",
        "</script>",
        "${injection}",
        "'; DROP TABLE nodes; --",
    ]

    def _script_is_valid_json_strings(self, value: str):
        """Ensure escape_string produces valid JSON."""
        escaped = ScriptBuilder.escape_string(value)
        parsed = json.loads(escaped)
        self.assertEqual(parsed, value)

    def test_all_adversarial_strings(self):
        for s in self.ADVERSARIAL:
            with self.subTest(s=s):
                self._script_is_valid_json_strings(s)


class TestDazNodeScriptGeneration(unittest.TestCase):
    def test_label_property_calls_execute(self):
        client = _make_client("Genesis 9")
        node = DazNode(client, NodeIdentifier("Genesis9"))
        result = node.label
        self.assertEqual(result, "Genesis 9")
        client.execute.assert_called_once()
        script = client.execute.call_args[0][0]
        self.assertIn("Genesis9", script)
        self.assertIn("getLabel", script)

    def test_position_returns_dict(self):
        client = _make_client({"x": 0.0, "y": 95.2, "z": -3.1})
        node = DazNode(client, NodeIdentifier("Genesis9"))
        pos = node.position
        self.assertEqual(pos["y"], 95.2)

    def test_set_position_calls_execute(self):
        client = _make_client(None)
        node = DazNode(client, NodeIdentifier("Genesis9"))
        node.set_position(1.0, 2.0, 3.0)
        script = client.execute.call_args[0][0]
        self.assertIn("setWSPos", script)
        self.assertIn("1.0", script)

    def test_rotation_returns_xyzw(self):
        client = _make_client({"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0})
        node = DazNode(client, NodeIdentifier("Genesis9"))
        rot = node.rotation
        self.assertIn("w", rot)
        self.assertEqual(rot["w"], 1.0)
        script = client.execute.call_args[0][0]
        self.assertIn("r.w", script)

    def test_general_scale_returns_float(self):
        client = _make_client(1.0)
        node = DazNode(client, NodeIdentifier("Genesis9"))
        gs = node.general_scale
        self.assertEqual(gs, 1.0)
        script = client.execute.call_args[0][0]
        self.assertIn("getScaleControl", script)
        self.assertNotIn("getXScaleControl", script)

    def test_scale_returns_dict_with_all_axes(self):
        client = _make_client({"x": 1.0, "y": 1.0, "z": 1.0, "general": 1.0})
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
        client = _make_client(None)
        node = DazNode(client, NodeIdentifier("MyNode"))
        node.visible = False
        script = client.execute.call_args[0][0]
        self.assertIn("setVisible", script)
        self.assertIn("false", script)


class TestDazScene(unittest.TestCase):
    def test_nodes_returns_list(self):
        client = _make_client([
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
        client = _make_client([
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
        client = _make_client([])
        scene = DazScene(client)
        scene.nodes()
        script = client.execute.call_args[0][0]
        self.assertIn("inherits", script)
        self.assertIn("DzSkeleton", script)

    def test_num_nodes(self):
        client = _make_client(5)
        scene = DazScene(client)
        self.assertEqual(scene.num_nodes(), 5)

    def test_find_node_success(self):
        client = _make_client(True)
        scene = DazScene(client)
        node = scene.find_node("Genesis9")
        self.assertIsInstance(node, DazNode)

    def test_find_node_not_found(self):
        client = _make_client(False)
        scene = DazScene(client)
        with self.assertRaises(exceptions.NodeNotFoundError):
            scene.find_node("NonExistent")

    def test_all_node_transforms(self):
        data = [{"name": "n1", "label": "Node 1", "position": [0, 0, 0], "rotation": [0, 0, 0], "visible": True}]
        client = _make_client(data)
        scene = DazScene(client)
        transforms = scene.all_node_transforms()
        self.assertEqual(len(transforms), 1)
        self.assertEqual(transforms[0]["name"], "n1")


class TestBatch(unittest.TestCase):
    def test_batch_builds_single_script(self):
        client = _make_client({"_r0": 10, "_r1": 5})
        with Batch(client) as batch:
            f_count = batch.add(["var _r0 = Scene.getNumNodes();"])
            f_frame = batch.add(["var _r1 = Scene.getFrame();"])

        self.assertEqual(f_count.value, 10)
        self.assertEqual(f_frame.value, 5)
        client.execute.assert_called_once()

    def test_batch_script_contains_return_map(self):
        client = _make_client({"_r0": 42})
        batch = Batch(client)
        batch.add(["var _r0 = 42;"])
        batch.execute()
        script = client.execute.call_args[0][0]
        self.assertIn('"_r0"', script)
        self.assertIn("return", script)

    def test_future_raises_before_execute(self):
        client = _make_client({"_r0": 1})
        batch = Batch(client)
        future = batch.add(["var _r0 = 1;"])
        with self.assertRaises(RuntimeError):
            _ = future.value

    def test_empty_batch_no_call(self):
        client = _make_client(None)
        with Batch(client):
            pass
        client.execute.assert_not_called()


class TestErrorMapping(unittest.TestCase):
    def _client_from_response(self, response_data: dict, status: int = 200):
        import requests as req
        resp = MagicMock(spec=req.Response)
        resp.status_code = status
        resp.json.return_value = response_data
        resp.text = str(response_data)

        client = DazClient.__new__(DazClient)
        object.__setattr__(client, "_base", "http://127.0.0.1:18811")
        object.__setattr__(client, "_token", "")
        object.__setattr__(client, "_timeout", 30.0)

        with patch("dazpy._client._requests.post", return_value=resp):
            return client, resp

    def test_auth_error_401(self):
        import requests as req
        resp = MagicMock(spec=req.Response)
        resp.status_code = 401
        resp.json.return_value = {"error": "Unauthorized"}
        resp.text = "Unauthorized"
        client = DazClient.__new__(DazClient)
        object.__setattr__(client, "_base", "http://127.0.0.1:18811")
        object.__setattr__(client, "_token", "bad")
        object.__setattr__(client, "_timeout", 30.0)
        with patch("dazpy._client._requests.post", return_value=resp):
            with self.assertRaises(exceptions.AuthenticationError):
                client.execute("1;")

    def test_script_runtime_error(self):
        import requests as req
        resp = MagicMock(spec=req.Response)
        resp.status_code = 200
        resp.json.return_value = {"success": False, "error": "TypeError: undefined is not a function", "request_id": "abc"}
        resp.text = ""
        client = DazClient.__new__(DazClient)
        object.__setattr__(client, "_base", "http://127.0.0.1:18811")
        object.__setattr__(client, "_token", "")
        object.__setattr__(client, "_timeout", 30.0)
        with patch("dazpy._client._requests.post", return_value=resp):
            with self.assertRaises(exceptions.ScriptRuntimeError) as ctx:
                client.execute("bad();")
            self.assertEqual(ctx.exception.request_id, "abc")

    def test_script_syntax_error_line_number(self):
        import requests as req
        resp = MagicMock(spec=req.Response)
        resp.status_code = 200
        resp.json.return_value = {"success": False, "error": "SyntaxError at Line 3: unexpected token", "request_id": "def"}
        resp.text = ""
        client = DazClient.__new__(DazClient)
        object.__setattr__(client, "_base", "http://127.0.0.1:18811")
        object.__setattr__(client, "_token", "")
        object.__setattr__(client, "_timeout", 30.0)
        with patch("dazpy._client._requests.post", return_value=resp):
            with self.assertRaises(exceptions.ScriptSyntaxError):
                client.execute("{bad syntax")

    def test_connection_error(self):
        import requests as req
        client = DazClient.__new__(DazClient)
        object.__setattr__(client, "_base", "http://127.0.0.1:18811")
        object.__setattr__(client, "_token", "")
        object.__setattr__(client, "_timeout", 30.0)
        with patch("dazpy._client._requests.post", side_effect=req.exceptions.ConnectionError("refused")):
            with self.assertRaises(exceptions.ConnectionError):
                client.execute("1;")

    def test_diagnostic_includes_script(self):
        err = exceptions.ScriptRuntimeError("failed", script="var x = bad();", request_id="r1")
        diag = err.diagnostic
        self.assertIn("var x = bad();", diag)
        self.assertIn("r1", diag)


class TestDazCameraScriptGeneration(unittest.TestCase):
    def setUp(self):
        from dazpy._camera import DazCamera
        self.DazCamera = DazCamera

    def test_focal_length_getter_uses_direct_property(self):
        client = _make_client(50.0)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.focal_length
        self.assertEqual(val, 50.0)
        script = client.execute.call_args[0][0]
        self.assertIn("focalLength", script)
        self.assertNotIn("get_property", script)
        self.assertNotIn("Focal Length", script)

    def test_focal_length_setter_uses_direct_property(self):
        client = _make_client(None)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        cam.focal_length = 85.0
        script = client.execute.call_args[0][0]
        self.assertIn("focalLength", script)
        self.assertIn("85.0", script)
        self.assertNotIn("Focal Length", script)

    def test_frame_width_getter_uses_direct_property(self):
        client = _make_client(36.0)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.frame_width
        self.assertEqual(val, 36.0)
        script = client.execute.call_args[0][0]
        self.assertIn("frameWidth", script)
        self.assertNotIn("Frame Width", script)

    def test_focal_distance_getter(self):
        client = _make_client(200.0)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.focal_distance
        self.assertEqual(val, 200.0)
        script = client.execute.call_args[0][0]
        self.assertIn("focalDistance", script)

    def test_focal_distance_setter(self):
        client = _make_client(None)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        cam.focal_distance = 150.0
        script = client.execute.call_args[0][0]
        self.assertIn("focalDistance", script)
        self.assertIn("150.0", script)

    def test_aspect_width_getter(self):
        client = _make_client(16.0)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.aspect_width
        self.assertEqual(val, 16.0)
        script = client.execute.call_args[0][0]
        self.assertIn("aspectWidth", script)

    def test_aspect_width_setter(self):
        client = _make_client(None)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        cam.aspect_width = 16.0
        script = client.execute.call_args[0][0]
        self.assertIn("aspectWidth", script)
        self.assertIn("16.0", script)

    def test_aspect_height_getter(self):
        client = _make_client(9.0)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.aspect_height
        self.assertEqual(val, 9.0)
        script = client.execute.call_args[0][0]
        self.assertIn("aspectHeight", script)

    def test_aspect_height_setter(self):
        client = _make_client(None)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        cam.aspect_height = 9.0
        script = client.execute.call_args[0][0]
        self.assertIn("aspectHeight", script)
        self.assertIn("9.0", script)

    def test_pixels_width_getter(self):
        client = _make_client(1920)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.pixels_width
        self.assertEqual(val, 1920)
        script = client.execute.call_args[0][0]
        self.assertIn("pixelsWidth", script)

    def test_pixels_width_setter(self):
        client = _make_client(None)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        cam.pixels_width = 1920
        script = client.execute.call_args[0][0]
        self.assertIn("pixelsWidth", script)
        self.assertIn("1920", script)

    def test_pixels_height_getter(self):
        client = _make_client(1080)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.pixels_height
        self.assertEqual(val, 1080)
        script = client.execute.call_args[0][0]
        self.assertIn("pixelsHeight", script)

    def test_pixels_height_setter(self):
        client = _make_client(None)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        cam.pixels_height = 1080
        script = client.execute.call_args[0][0]
        self.assertIn("pixelsHeight", script)
        self.assertIn("1080", script)

    def test_near_clipping_plane_getter(self):
        client = _make_client(0.1)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.near_clipping_plane
        self.assertEqual(val, 0.1)
        script = client.execute.call_args[0][0]
        self.assertIn("nearClippingPlane", script)

    def test_far_clipping_plane_getter(self):
        client = _make_client(10000.0)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.far_clipping_plane
        self.assertEqual(val, 10000.0)
        script = client.execute.call_args[0][0]
        self.assertIn("farClippingPlane", script)

    def test_aim_at_generates_DzVec3(self):
        client = _make_client(None)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        cam.aim_at(1.0, 2.0, 3.0)
        script = client.execute.call_args[0][0]
        self.assertIn("aimAt", script)
        self.assertIn("DzVec3", script)
        self.assertIn("1.0", script)
        self.assertIn("2.0", script)
        self.assertIn("3.0", script)

    def test_focal_point_returns_xyz(self):
        client = _make_client({"x": 0.0, "y": 10.0, "z": 5.0})
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.focal_point()
        self.assertEqual(val, {"x": 0.0, "y": 10.0, "z": 5.0})
        script = client.execute.call_args[0][0]
        self.assertIn("getFocalPoint", script)

    def test_is_view_camera_returns_bool(self):
        client = _make_client(False)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.is_view_camera()
        self.assertFalse(val)
        script = client.execute.call_args[0][0]
        self.assertIn("isViewCamera", script)


class TestDazRenderSettingsScriptGeneration(unittest.TestCase):
    def setUp(self):
        from dazpy._render import DazRenderSettings
        self.DazRenderSettings = DazRenderSettings

    def _make_render(self, return_value=None):
        client = _make_client(return_value)
        return self.DazRenderSettings(client), client

    def test_resolution_getter_uses_imageSize(self):
        rs, client = self._make_render({"width": 1920, "height": 1080})
        val = rs.resolution
        self.assertEqual(val, {"width": 1920, "height": 1080})
        script = client.execute.call_args[0][0]
        self.assertIn("imageSize", script)
        self.assertNotIn("getImageSize", script)

    def test_set_resolution_uses_imageSize_and_applyChanges(self):
        rs, client = self._make_render(None)
        rs.set_resolution(1920, 1080)
        script = client.execute.call_args[0][0]
        self.assertIn("imageSize", script)
        self.assertIn("new QSize", script)
        self.assertIn("1920", script)
        self.assertIn("1080", script)
        self.assertIn("applyChanges", script)

    def test_output_path_getter_uses_renderImgFilename(self):
        rs, client = self._make_render("/tmp/render.png")
        val = rs.output_path
        self.assertEqual(val, "/tmp/render.png")
        script = client.execute.call_args[0][0]
        self.assertIn("renderImgFilename", script)
        self.assertNotIn("getImageFilename", script)

    def test_output_path_setter_uses_renderImgFilename(self):
        rs, client = self._make_render(None)
        rs.output_path = "/tmp/out.png"
        script = client.execute.call_args[0][0]
        self.assertIn("renderImgFilename", script)
        self.assertIn("/tmp/out.png", script)
        self.assertNotIn("setImageFilename", script)
        self.assertIn("applyChanges", script)

    def test_render_uses_doRender(self):
        rs, client = self._make_render(True)
        result = rs.render()
        self.assertTrue(result)
        script = client.execute.call_args[0][0]
        self.assertIn("doRender", script)
        self.assertNotIn("mgr.render()", script)

    def test_gamma_getter_uses_direct_property(self):
        rs, client = self._make_render(2.2)
        val = rs.gamma
        self.assertAlmostEqual(val, 2.2)
        script = client.execute.call_args[0][0]
        self.assertIn("opts.gamma", script)

    def test_gamma_setter_uses_direct_property(self):
        rs, client = self._make_render(None)
        rs.gamma = 2.2
        script = client.execute.call_args[0][0]
        self.assertIn("opts.gamma", script)
        self.assertIn("2.2", script)
        self.assertIn("applyChanges", script)

    def test_double_sided_getter_uses_direct_property(self):
        rs, client = self._make_render(False)
        val = rs.double_sided
        self.assertFalse(val)
        script = client.execute.call_args[0][0]
        self.assertIn("doubleSided", script)

    def test_double_sided_setter_uses_direct_property(self):
        rs, client = self._make_render(None)
        rs.double_sided = True
        script = client.execute.call_args[0][0]
        self.assertIn("doubleSided", script)
        self.assertIn("true", script)

    def test_null_guard_on_missing_mgr(self):
        rs, client = self._make_render(None)
        val = rs.resolution
        self.assertIsNone(val)

    def test_is_available_checks_mgr_not_null(self):
        rs, client = self._make_render(True)
        val = rs.is_available()
        self.assertTrue(val)
        script = client.execute.call_args[0][0]
        self.assertIn("getRenderMgr", script)

    def test_is_rendering(self):
        rs, client = self._make_render(False)
        val = rs.is_rendering()
        self.assertFalse(val)
        script = client.execute.call_args[0][0]
        self.assertIn("isRendering", script)

    def test_has_render(self):
        rs, client = self._make_render(True)
        val = rs.has_render()
        self.assertTrue(val)
        script = client.execute.call_args[0][0]
        self.assertIn("hasRender", script)


class TestDazSkeletonScriptGeneration(unittest.TestCase):
    def setUp(self):
        from dazpy._skeleton import DazSkeleton
        self.DazSkeleton = DazSkeleton

    def _make_skeleton(self, return_value=None):
        client = _make_client(return_value)
        skel = self.DazSkeleton(client, NodeIdentifier("Genesis9"))
        return skel, client

    def test_bones_calls_getAllBones(self):
        skel, client = self._make_skeleton(["hip", "lShldrBend"])
        bones = skel.bones()
        self.assertEqual(len(bones), 2)
        script = client.execute.call_args[0][0]
        self.assertIn("getAllBones", script)

    def test_bones_returns_daz_bone_instances(self):
        from dazpy._bone import DazBone
        skel, client = self._make_skeleton(["hip"])
        bones = skel.bones()
        self.assertIsInstance(bones[0], DazBone)

    def test_find_bone_calls_findBone(self):
        skel, client = self._make_skeleton("hip")
        bone = skel.find_bone("hip")
        script = client.execute.call_args[0][0]
        self.assertIn("findBone", script)
        self.assertIn("hip", script)

    def test_find_bone_not_found_raises(self):
        skel, client = self._make_skeleton(None)
        with self.assertRaises(exceptions.NodeNotFoundError):
            skel.find_bone("nonexistent")

    def test_find_bone_by_label_calls_findBoneByLabel(self):
        skel, client = self._make_skeleton("hip")
        skel.find_bone_by_label("Hip")
        script = client.execute.call_args[0][0]
        self.assertIn("findBoneByLabel", script)

    def test_num_bones_calls_getAllBones_length(self):
        skel, client = self._make_skeleton(42)
        count = skel.num_bones()
        self.assertEqual(count, 42)
        script = client.execute.call_args[0][0]
        self.assertIn("getAllBones", script)
        self.assertIn("length", script)

    def test_follow_target_returns_skeleton(self):
        skel, client = self._make_skeleton("Genesis9_2")
        target = skel.follow_target()
        self.assertIsInstance(target, self.DazSkeleton)
        script = client.execute.call_args[0][0]
        self.assertIn("getFollowTarget", script)

    def test_follow_target_returns_none_when_null(self):
        skel, client = self._make_skeleton(None)
        target = skel.follow_target()
        self.assertIsNone(target)


class TestDazBoneScriptGeneration(unittest.TestCase):
    def setUp(self):
        from dazpy._bone import DazBone
        self.DazBone = DazBone

    def _make_bone(self, return_value=None):
        client = _make_client(return_value)
        bone = self.DazBone(client, NodeIdentifier("hip"))
        return bone, client

    def test_local_rotation_returns_xyzw(self):
        bone, client = self._make_bone({"x": 0.0, "y": 0.1, "z": 0.0, "w": 0.995})
        rot = bone.local_rotation
        self.assertIn("w", rot)
        script = client.execute.call_args[0][0]
        self.assertIn("getLocalRot", script)
        self.assertIn("r.w", script)

    def test_set_local_rotation_uses_axis_controls(self):
        bone, client = self._make_bone(None)
        bone.set_local_rotation(10.0, 20.0, 30.0)
        script = client.execute.call_args[0][0]
        self.assertIn("getXRotControl", script)
        self.assertIn("getYRotControl", script)
        self.assertIn("getZRotControl", script)
        self.assertIn("setValue", script)
        self.assertIn("10.0", script)
        self.assertIn("20.0", script)
        self.assertIn("30.0", script)

    def test_local_position_returns_xyz(self):
        bone, client = self._make_bone({"x": 1.0, "y": 2.0, "z": 3.0})
        pos = bone.local_position
        self.assertEqual(pos["x"], 1.0)
        script = client.execute.call_args[0][0]
        self.assertIn("getLocalPos", script)

    def test_rotation_order_calls_getRotationOrder(self):
        bone, client = self._make_bone("XYZ")
        order = bone.rotation_order
        self.assertEqual(order, "XYZ")
        script = client.execute.call_args[0][0]
        self.assertIn("getRotationOrder", script)

    def test_get_skeleton_returns_daz_skeleton(self):
        from dazpy._skeleton import DazSkeleton
        bone, client = self._make_bone("Genesis9")
        skel = bone.get_skeleton()
        self.assertIsInstance(skel, DazSkeleton)
        script = client.execute.call_args[0][0]
        self.assertIn("getSkeleton", script)

    def test_get_skeleton_returns_none_when_null(self):
        bone, client = self._make_bone(None)
        skel = bone.get_skeleton()
        self.assertIsNone(skel)


class TestDazModifierScriptGeneration(unittest.TestCase):
    def _make_modifier(self, return_value=None, locator='Scene.findNode("MyNode").getObject().findModifier("MyMod")'):
        from dazpy._modifier import DazModifier
        client = _make_client(return_value)
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
        client = _make_client(return_value)
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
        client = _make_client([
            {"name": "SomeMod", "className": "DzSubDivisionModifier"},
            {"name": "MyMorph", "className": "DzMorph"},
        ])
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mods = node.modifiers()
        self.assertEqual(len(mods), 2)
        self.assertIsInstance(mods[0], DazModifier)
        self.assertIsInstance(mods[1], DazMorph)

    def test_modifiers_script_uses_getNumModifiers(self):
        client = _make_client([])
        node = DazNode(client, NodeIdentifier("Genesis9"))
        node.modifiers()
        script = client.execute.call_args[0][0]
        self.assertIn("getNumModifiers", script)
        self.assertIn("getObject", script)
        self.assertIn("className", script)

    def test_modifiers_empty_when_no_object(self):
        client = _make_client([])
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mods = node.modifiers()
        self.assertEqual(mods, [])

    def test_find_modifier_returns_daz_modifier(self):
        from dazpy._modifier import DazModifier
        client = _make_client({"name": "SomeMod", "className": "DzSubDivisionModifier"})
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mod = node.find_modifier("SomeMod")
        self.assertIsInstance(mod, DazModifier)

    def test_find_modifier_returns_daz_morph_when_class_is_dzmorph(self):
        from dazpy._morph import DazMorph
        client = _make_client({"name": "MyMorph", "className": "DzMorph"})
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mod = node.find_modifier("MyMorph")
        self.assertIsInstance(mod, DazMorph)

    def test_find_modifier_returns_none_when_not_found(self):
        client = _make_client(None)
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mod = node.find_modifier("NonExistent")
        self.assertIsNone(mod)

    def test_find_modifier_script_uses_findModifier(self):
        client = _make_client(None)
        node = DazNode(client, NodeIdentifier("Genesis9"))
        node.find_modifier("SomeMod")
        script = client.execute.call_args[0][0]
        self.assertIn("findModifier", script)
        self.assertIn("SomeMod", script)

    def test_morphs_filters_to_only_daz_morph(self):
        from dazpy._morph import DazMorph
        client = _make_client([
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
        client = _make_client(None)
        node = DazNode(client, NodeIdentifier("Genesis9"))
        loc = node._modifier_locator("MyMorph")
        self.assertIn("findModifier", loc)
        self.assertIn("MyMorph", loc)
        self.assertIn("getObject", loc)


class TestDazMaterialScriptGeneration(unittest.TestCase):
    def _make_material(self, return_value=None):
        from dazpy._material import DazMaterial
        client = _make_client(return_value)
        locator = 'Scene.findNode("Genesis9").getObject().getCurrentShape().findMaterial("Skin")'
        mat = DazMaterial(client, locator)
        return mat, client

    def test_material_name_calls_getName(self):
        mat, client = self._make_material("Skin")
        name = mat.material_name
        self.assertEqual(name, "Skin")
        script = client.execute.call_args[0][0]
        self.assertIn("getName", script)

    def test_diffuse_color_calls_getDiffuseColor(self):
        mat, client = self._make_material({"r": 200, "g": 180, "b": 160})
        color = mat.diffuse_color
        self.assertEqual(color, {"r": 200, "g": 180, "b": 160})
        script = client.execute.call_args[0][0]
        self.assertIn("getDiffuseColor", script)

    def test_diffuse_color_setter_calls_setDiffuseColor(self):
        mat, client = self._make_material(None)
        mat.diffuse_color = (255, 128, 0)
        script = client.execute.call_args[0][0]
        self.assertIn("setDiffuseColor", script)
        self.assertIn("255", script)
        self.assertIn("128", script)

    def test_diffuse_color_setter_accepts_dict(self):
        mat, client = self._make_material(None)
        mat.diffuse_color = {"r": 100, "g": 150, "b": 200}
        script = client.execute.call_args[0][0]
        self.assertIn("setDiffuseColor", script)
        self.assertIn("100", script)

    def test_opacity_calls_getBaseOpacity(self):
        mat, client = self._make_material(0.9)
        val = mat.opacity
        self.assertAlmostEqual(val, 0.9)
        script = client.execute.call_args[0][0]
        self.assertIn("getBaseOpacity", script)

    def test_opacity_setter_calls_setBaseOpacity(self):
        mat, client = self._make_material(None)
        mat.opacity = 0.5
        script = client.execute.call_args[0][0]
        self.assertIn("setBaseOpacity", script)
        self.assertIn("0.5", script)

    def test_color_map_calls_getColorMap(self):
        mat, client = self._make_material("/textures/skin.png")
        result = mat.color_map()
        self.assertEqual(result, "/textures/skin.png")
        script = client.execute.call_args[0][0]
        self.assertIn("getColorMap", script)
        self.assertIn("getFilename", script)

    def test_is_smoothing_on_calls_isSmoothingOn(self):
        mat, client = self._make_material(True)
        val = mat.is_smoothing_on()
        self.assertTrue(val)
        script = client.execute.call_args[0][0]
        self.assertIn("isSmoothingOn", script)

    def test_smoothing_angle_calls_getSmoothingAngle(self):
        mat, client = self._make_material(89.9)
        val = mat.smoothing_angle
        self.assertAlmostEqual(val, 89.9)
        script = client.execute.call_args[0][0]
        self.assertIn("getSmoothingAngle", script)

    def test_smoothing_angle_setter_calls_setSmoothingAngle(self):
        mat, client = self._make_material(None)
        mat.smoothing_angle = 45.0
        script = client.execute.call_args[0][0]
        self.assertIn("setSmoothingAngle", script)
        self.assertIn("45.0", script)

    def test_is_opaque_calls_isOpaque(self):
        mat, client = self._make_material(True)
        val = mat.is_opaque()
        self.assertTrue(val)
        script = client.execute.call_args[0][0]
        self.assertIn("isOpaque", script)


class TestDazNodeMaterialMethods(unittest.TestCase):
    def test_materials_returns_list_of_daz_material(self):
        from dazpy._material import DazMaterial
        client = _make_client(["Skin", "Eyes", "Teeth"])
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mats = node.materials()
        self.assertEqual(len(mats), 3)
        for m in mats:
            self.assertIsInstance(m, DazMaterial)

    def test_materials_script_uses_getNumMaterials(self):
        client = _make_client([])
        node = DazNode(client, NodeIdentifier("Genesis9"))
        node.materials()
        script = client.execute.call_args[0][0]
        self.assertIn("getNumMaterials", script)
        self.assertIn("getCurrentShape", script)
        self.assertIn("getObject", script)

    def test_materials_empty_when_no_object(self):
        client = _make_client([])
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mats = node.materials()
        self.assertEqual(mats, [])

    def test_find_material_returns_daz_material(self):
        from dazpy._material import DazMaterial
        client = _make_client("Skin")
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mat = node.find_material("Skin")
        self.assertIsInstance(mat, DazMaterial)

    def test_find_material_returns_none_when_not_found(self):
        client = _make_client(None)
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mat = node.find_material("NonExistent")
        self.assertIsNone(mat)

    def test_find_material_script_uses_findMaterial(self):
        client = _make_client(None)
        node = DazNode(client, NodeIdentifier("Genesis9"))
        node.find_material("Skin")
        script = client.execute.call_args[0][0]
        self.assertIn("findMaterial", script)
        self.assertIn("Skin", script)

    def test_material_locator_uses_findMaterial(self):
        client = _make_client(None)
        node = DazNode(client, NodeIdentifier("Genesis9"))
        loc = node._material_locator("Skin")
        self.assertIn("findMaterial", loc)
        self.assertIn("Skin", loc)
        self.assertIn("getCurrentShape", loc)
        self.assertIn("getObject", loc)


class TestDazNodeRotationAndSelection(unittest.TestCase):
    def _node(self, return_value=None):
        client = _make_client(return_value)
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
        client = _make_client(return_value)
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



class TestDazSceneSelection(unittest.TestCase):
    def test_selected_nodes_calls_getSelectedNodeList(self):
        client = _make_client(["Genesis9", "Camera 1"])
        scene = DazScene(client)
        nodes = scene.selected_nodes()
        self.assertEqual(len(nodes), 2)
        self.assertIsInstance(nodes[0], DazNode)
        script = client.execute.call_args[0][0]
        self.assertIn("getSelectedNodeList", script)

    def test_selected_nodes_empty_list(self):
        client = _make_client([])
        scene = DazScene(client)
        nodes = scene.selected_nodes()
        self.assertEqual(nodes, [])

    def test_primary_selection_returns_node(self):
        client = _make_client("Genesis9")
        scene = DazScene(client)
        node = scene.primary_selection()
        self.assertIsInstance(node, DazNode)
        script = client.execute.call_args[0][0]
        self.assertIn("getPrimarySelection", script)

    def test_primary_selection_returns_none_when_nothing_selected(self):
        client = _make_client(None)
        scene = DazScene(client)
        node = scene.primary_selection()
        self.assertIsNone(node)

    def test_set_primary_selection_calls_setPrimarySelection(self):
        client = _make_client(None)
        scene = DazScene(client)
        node = DazNode(client, NodeIdentifier("Genesis9"))
        scene.set_primary_selection(node)
        script = client.execute.call_args[0][0]
        self.assertIn("setPrimarySelection", script)
        self.assertIn("Genesis9", script)

    def test_select_all_true_calls_selectAllNodes_true(self):
        client = _make_client(None)
        scene = DazScene(client)
        scene.select_all(True)
        script = client.execute.call_args[0][0]
        self.assertIn("selectAllNodes", script)
        self.assertIn("true", script)

    def test_select_all_false_deselects(self):
        client = _make_client(None)
        scene = DazScene(client)
        scene.select_all(False)
        script = client.execute.call_args[0][0]
        self.assertIn("selectAllNodes", script)
        self.assertIn("false", script)

    def test_select_all_default_is_true(self):
        client = _make_client(None)
        scene = DazScene(client)
        scene.select_all()
        script = client.execute.call_args[0][0]
        self.assertIn("true", script)


class TestDazSceneIO(unittest.TestCase):
    def _scene(self, return_value):
        return DazScene(_make_client(return_value))

    def test_load_calls_loadScene_with_path(self):
        scene = self._scene(None)
        scene.load("/path/to/scene.duf")
        script = scene._client.execute.call_args[0][0]
        self.assertIn("loadScene", script)
        self.assertIn("/path/to/scene.duf", script)
        self.assertIn(", 0", script)

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


class TestDazLightScriptGeneration(unittest.TestCase):
    def setUp(self):
        from dazpy._light import DazLight
        self.DazLight = DazLight

    def _light(self, return_value=None):
        client = _make_client(return_value)
        return self.DazLight(client, NodeIdentifier("PointLight1")), client

    def test_is_on_calls_isOn(self):
        light, client = self._light(True)
        result = light.is_on()
        self.assertTrue(result)
        script = client.execute.call_args[0][0]
        self.assertIn("isOn", script)

    def test_is_on_false(self):
        light, client = self._light(False)
        self.assertFalse(light.is_on())

    def test_is_directional_calls_isDirectional(self):
        light, client = self._light(False)
        result = light.is_directional()
        self.assertFalse(result)
        script = client.execute.call_args[0][0]
        self.assertIn("isDirectional", script)

    def test_is_area_light_calls_isAreaLight(self):
        light, client = self._light(False)
        result = light.is_area_light()
        self.assertFalse(result)
        script = client.execute.call_args[0][0]
        self.assertIn("isAreaLight", script)

    def test_direction_calls_getWSDirection(self):
        light, client = self._light({"x": 0.0, "y": -1.0, "z": 0.0})
        result = light.direction()
        self.assertEqual(result, {"x": 0.0, "y": -1.0, "z": 0.0})
        script = client.execute.call_args[0][0]
        self.assertIn("getWSDirection", script)
        self.assertIn("isDirectional", script)

    def test_direction_returns_none_for_non_directional(self):
        light, client = self._light(None)
        result = light.direction()
        self.assertIsNone(result)

    def test_set_color_calls_findPropertyByLabel(self):
        light, client = self._light(None)
        light.set_color(255, 128, 0)
        script = client.execute.call_args[0][0]
        self.assertIn("findPropertyByLabel", script)
        self.assertIn("Diffuse Color", script)
        self.assertIn("255", script)
        self.assertIn("128", script)
        self.assertIn("0", script)
        self.assertIn("Color", script)


class TestDazGeometryScriptGeneration(unittest.TestCase):
    def _geo(self, return_value=None):
        from dazpy._geometry import DazGeometry
        client = _make_client(return_value)
        geo = DazGeometry(client, NodeIdentifier("Genesis9"))
        return geo, client

    def test_face_vertex_indices_uses_getFacet(self):
        geo, client = self._geo({"total": 100, "start": 0, "facets": [[0, 1, 2]]})
        result = geo.face_vertex_indices(start=0, count=10)
        self.assertIn("facets", result)
        script = client.execute.call_args[0][0]
        self.assertIn("getFacet", script)
        self.assertIn("vertIdx1", script)
        self.assertIn("isQuad", script)

    def test_face_vertex_indices_quad_has_four_indices(self):
        geo, client = self._geo({"total": 10, "start": 0, "facets": [[0, 1, 2, 3]]})
        result = geo.face_vertex_indices(start=0, count=5)
        self.assertEqual(result["facets"][0], [0, 1, 2, 3])

    def test_normals_uses_getNormal(self):
        geo, client = self._geo({"total": 50, "start": 0, "normals": [[0.0, 1.0, 0.0]]})
        result = geo.normals(start=0, count=10)
        self.assertIn("normals", result)
        script = client.execute.call_args[0][0]
        self.assertIn("getNormal", script)
        self.assertIn("getNumNormals", script)

    def test_uv_set_count_uses_getNumUVSets(self):
        geo, client = self._geo(2)
        count = geo.uv_set_count
        self.assertEqual(count, 2)
        script = client.execute.call_args[0][0]
        self.assertIn("getNumUVSets", script)

    def test_uv_positions_default_uses_getUVs(self):
        geo, client = self._geo({"total": 100, "start": 0, "uvs": [[0.5, 0.5]]})
        result = geo.uv_positions(uv_set=0, start=0, count=10)
        self.assertIn("uvs", result)
        script = client.execute.call_args[0][0]
        self.assertIn("getUVs", script)
        self.assertIn("getPnt2Vec", script)

    def test_uv_positions_nonzero_uses_getUVSet(self):
        geo, client = self._geo({"total": 100, "start": 0, "uvs": []})
        geo.uv_positions(uv_set=1)
        script = client.execute.call_args[0][0]
        self.assertIn("getUVSet", script)

    def test_face_group_names_uses_getFaceGroup(self):
        geo, client = self._geo(["Body", "Head"])
        names = geo.face_group_names()
        self.assertEqual(names, ["Body", "Head"])
        script = client.execute.call_args[0][0]
        self.assertIn("getFaceGroup", script)
        self.assertIn("getName", script)

    def test_material_group_names_uses_getMaterialGroup(self):
        geo, client = self._geo(["Skin", "Eyes"])
        names = geo.material_group_names()
        self.assertEqual(names, ["Skin", "Eyes"])
        script = client.execute.call_args[0][0]
        self.assertIn("getMaterialGroup", script)
        self.assertIn("getName", script)

    def test_subdivision_level_uses_getCurrentSubDivisionLevel(self):
        geo, client = self._geo(0)
        lvl = geo.subdivision_level
        self.assertEqual(lvl, 0)
        script = client.execute.call_args[0][0]
        self.assertIn("getCurrentSubDivisionLevel", script)

    def test_tris_count_uses_getNumTris(self):
        geo, client = self._geo(1500)
        count = geo.tris_count
        self.assertEqual(count, 1500)
        script = client.execute.call_args[0][0]
        self.assertIn("getNumTris", script)

    def test_quads_count_uses_getNumQuads(self):
        geo, client = self._geo(8000)
        count = geo.quads_count
        self.assertEqual(count, 8000)
        script = client.execute.call_args[0][0]
        self.assertIn("getNumQuads", script)


if __name__ == "__main__":
    unittest.main(verbosity=2)
