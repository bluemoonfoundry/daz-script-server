"""dazpy unit tests: DazCamera and DazRenderSettings script generation.

Mock-based; no server or DAZ Studio required.
Shared fakes live in tests/dazpy_fakes.py.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dazpy._node import NodeIdentifier
from dazpy._scene import DazScene
from dazpy import exceptions
from dazpy_fakes import mock_client


class TestDazCameraScriptGeneration(unittest.TestCase):
    def setUp(self):
        from dazpy._camera import DazCamera
        self.DazCamera = DazCamera

    def test_focal_length_getter_uses_direct_property(self):
        client = mock_client(50.0)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.focal_length
        self.assertEqual(val, 50.0)
        script = client.execute.call_args[0][0]
        self.assertIn("focalLength", script)
        self.assertNotIn("get_property", script)
        self.assertNotIn("Focal Length", script)

    def test_depth_of_field_is_a_real_bool(self):
        # The bool property's getValue() reports 1/0 (seen live on Studio 6).
        for raw, expected in ((1, True), (0, False), (None, None)):
            cam = self.DazCamera(mock_client(raw), NodeIdentifier("Camera 1"))
            self.assertIs(cam.depth_of_field, expected)

    def test_focal_length_setter_uses_direct_property(self):
        client = mock_client(None)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        cam.focal_length = 85.0
        script = client.execute.call_args[0][0]
        self.assertIn("focalLength", script)
        self.assertIn("85.0", script)
        self.assertNotIn("Focal Length", script)

    def test_frame_width_getter_uses_direct_property(self):
        client = mock_client(36.0)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.frame_width
        self.assertEqual(val, 36.0)
        script = client.execute.call_args[0][0]
        self.assertIn("frameWidth", script)
        self.assertNotIn("Frame Width", script)

    def test_focal_distance_getter(self):
        client = mock_client(200.0)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.focal_distance
        self.assertEqual(val, 200.0)
        script = client.execute.call_args[0][0]
        self.assertIn("focalDistance", script)

    def test_focal_distance_setter(self):
        client = mock_client(None)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        cam.focal_distance = 150.0
        script = client.execute.call_args[0][0]
        self.assertIn("focalDistance", script)
        self.assertIn("150.0", script)

    def test_aspect_width_getter(self):
        client = mock_client(16.0)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.aspect_width
        self.assertEqual(val, 16.0)
        script = client.execute.call_args[0][0]
        self.assertIn("aspectWidth", script)

    def test_aspect_width_setter(self):
        client = mock_client(None)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        cam.aspect_width = 16.0
        script = client.execute.call_args[0][0]
        self.assertIn("aspectWidth", script)
        self.assertIn("16.0", script)

    def test_aspect_height_getter(self):
        client = mock_client(9.0)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.aspect_height
        self.assertEqual(val, 9.0)
        script = client.execute.call_args[0][0]
        self.assertIn("aspectHeight", script)

    def test_aspect_height_setter(self):
        client = mock_client(None)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        cam.aspect_height = 9.0
        script = client.execute.call_args[0][0]
        self.assertIn("aspectHeight", script)
        self.assertIn("9.0", script)

    def test_pixels_width_getter(self):
        client = mock_client(1920)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.pixels_width
        self.assertEqual(val, 1920)
        script = client.execute.call_args[0][0]
        self.assertIn("pixelsWidth", script)

    def test_pixels_width_setter(self):
        client = mock_client(None)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        cam.pixels_width = 1920
        script = client.execute.call_args[0][0]
        self.assertIn("pixelsWidth", script)
        self.assertIn("1920", script)

    def test_pixels_height_getter(self):
        client = mock_client(1080)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.pixels_height
        self.assertEqual(val, 1080)
        script = client.execute.call_args[0][0]
        self.assertIn("pixelsHeight", script)

    def test_pixels_height_setter(self):
        client = mock_client(None)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        cam.pixels_height = 1080
        script = client.execute.call_args[0][0]
        self.assertIn("pixelsHeight", script)
        self.assertIn("1080", script)

    def test_near_clipping_plane_getter(self):
        client = mock_client(0.1)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.near_clipping_plane
        self.assertEqual(val, 0.1)
        script = client.execute.call_args[0][0]
        self.assertIn("nearClippingPlane", script)

    def test_far_clipping_plane_getter(self):
        client = mock_client(10000.0)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.far_clipping_plane
        self.assertEqual(val, 10000.0)
        script = client.execute.call_args[0][0]
        self.assertIn("farClippingPlane", script)

    def test_lens_shift_x_getter_uses_property_label(self):
        client = mock_client(2.5)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.lens_shift_x
        self.assertEqual(val, 2.5)
        script = client.execute.call_args[0][0]
        self.assertIn("Lens Shift X (mm)", script)
        self.assertIn("findPropertyByLabel", script)

    def test_lens_shift_x_setter_uses_property_label(self):
        client = mock_client(None)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        cam.lens_shift_x = -1.5
        script = client.execute.call_args[0][0]
        self.assertIn("Lens Shift X (mm)", script)
        self.assertIn("-1.5", script)

    def test_lens_shift_y_getter_uses_property_label(self):
        client = mock_client(0.0)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.lens_shift_y
        self.assertEqual(val, 0.0)
        script = client.execute.call_args[0][0]
        self.assertIn("Lens Shift Y (mm)", script)

    def test_lens_shift_y_setter_uses_property_label(self):
        client = mock_client(None)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        cam.lens_shift_y = 3.0
        script = client.execute.call_args[0][0]
        self.assertIn("Lens Shift Y (mm)", script)
        self.assertIn("3.0", script)

    def test_f_stop_getter_uses_property_label(self):
        client = mock_client(2.8)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.f_stop
        self.assertEqual(val, 2.8)
        script = client.execute.call_args[0][0]
        self.assertIn("F/Stop", script)
        self.assertIn("findPropertyByLabel", script)

    def test_f_stop_setter_uses_property_label(self):
        client = mock_client(None)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        cam.f_stop = 5.6
        script = client.execute.call_args[0][0]
        self.assertIn("F/Stop", script)
        self.assertIn("5.6", script)

    def test_aperture_blades_getter_uses_property_label(self):
        client = mock_client(6)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.aperture_blades
        self.assertEqual(val, 6)
        script = client.execute.call_args[0][0]
        self.assertIn("Aperture Blades", script)

    def test_aperture_blades_setter_uses_property_label(self):
        client = mock_client(None)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        cam.aperture_blades = 6
        script = client.execute.call_args[0][0]
        self.assertIn("Aperture Blades", script)
        self.assertIn("6", script)

    def test_aperture_blade_rotation_getter_uses_property_label(self):
        client = mock_client(15.0)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.aperture_blade_rotation
        self.assertEqual(val, 15.0)
        script = client.execute.call_args[0][0]
        self.assertIn("Aperture Blade Rotation", script)

    def test_aperture_blade_rotation_setter_uses_property_label(self):
        client = mock_client(None)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        cam.aperture_blade_rotation = 15.0
        script = client.execute.call_args[0][0]
        self.assertIn("Aperture Blade Rotation", script)
        self.assertIn("15.0", script)

    def test_aim_at_generates_DzVec3(self):
        client = mock_client(None)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        cam.aim_at(1.0, 2.0, 3.0)
        script = client.execute.call_args[0][0]
        self.assertIn("aimAt", script)
        self.assertIn("DzVec3", script)
        self.assertIn("1.0", script)
        self.assertIn("2.0", script)
        self.assertIn("3.0", script)

    def test_focal_point_returns_xyz(self):
        client = mock_client({"x": 0.0, "y": 10.0, "z": 5.0})
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.focal_point()
        self.assertEqual(val, {"x": 0.0, "y": 10.0, "z": 5.0})
        script = client.execute.call_args[0][0]
        self.assertIn("getFocalPoint", script)

    def test_is_view_camera_returns_bool(self):
        client = mock_client(False)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.is_view_camera()
        self.assertFalse(val)
        script = client.execute.call_args[0][0]
        self.assertIn("isViewCamera", script)


class TestDazRenderSettingsScriptGeneration(unittest.TestCase):
    def setUp(self):
        from dazpy._render import DazRenderSettings
        self.DazRenderSettings = DazRenderSettings

    def _make_render(self, return_value=None, output=None):
        client = mock_client(return_value, output=output)
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
        from dazpy._render import RenderOutcome
        rs, client = self._make_render(
            {"success": True, "output_path": "/tmp/render.png"}
        )
        result = rs.render()
        self.assertEqual(
            result, RenderOutcome(success=True, output_path="/tmp/render.png")
        )
        script = client.execute.call_args[0][0]
        self.assertIn("doRender", script)
        self.assertNotIn("mgr.render()", script)

    def test_render_uses_renderFinished_signal_not_doRender_return_value(self):
        # Regression: doRender()'s own return value is undocumented in the
        # DAZ SDK (no "Returns:" section) and was observed live to report
        # success even for a render the user cancelled mid-progress via the
        # DAZ Studio UI. renderFinished(bool succeeded) is the SDK's named,
        # documented completion signal -- SceneEventBroker.cpp already
        # trusts it as the "guaranteed exit path" -- so render() must derive
        # success from that signal, not from doRender()'s return code.
        rs, client = self._make_render({"success": True, "output_path": "/tmp/render.png"})
        rs.render()
        script = client.execute.call_args[0][0]
        self.assertIn("renderFinished(bool)", script)
        self.assertIn("_finishedBound", script)
        self.assertNotIn('mgr["renderFinished(bool)"].connect(', script)
        self.assertIn("renderSucceeded === true", script)
        self.assertNotIn("err === 0", script)
        self.assertNotIn("err === true", script)

    def test_render_forces_active_canvas_back_to_beauty(self):
        # Regression (GH #32): findCanvasDefinition(name, true) implicitly
        # reassigns "Active Canvas" as a side effect, so once any non-Beauty
        # canvas (Depth, MaterialID, ...) has been added, doRender() saves
        # that canvas's pass as the primary output instead of the true
        # beauty image -- the "clown render" bug. render() must always pin
        # Active Canvas back to Beauty before rendering.
        rs, client = self._make_render({"success": True, "output_path": "/tmp/render.png"})
        rs.render()
        script = client.execute.call_args[0][0]
        self.assertIn("renderToCanvases", script)
        self.assertIn('findCanvasDefinition("Beauty", true)', script)
        self.assertIn('canvasTypeFromString("Beauty")', script)
        self.assertIn('findProperty("Active Canvas")', script)
        self.assertIn('setValueFromString("Beauty")', script)

    def test_render_camera_name_uses_findCamera(self):
        rs, client = self._make_render({"success": True, "output_path": "/tmp/render.png"})
        rs.render(camera_name="Camera")
        script = client.execute.call_args[0][0]
        self.assertIn("Scene.findCamera(", script)
        self.assertNotIn("findCameraByLabel", script)

    def test_render_camera_label_uses_findCameraByLabel(self):
        rs, client = self._make_render({"success": True, "output_path": "/tmp/render.png"})
        rs.render(camera_label="Front Camera")
        script = client.execute.call_args[0][0]
        self.assertIn("Scene.findCameraByLabel(", script)
        self.assertIn("Front Camera", script)

    def test_render_camera_name_and_label_mutually_exclusive(self):
        rs, client = self._make_render({"success": True, "output_path": "/tmp/render.png"})
        with self.assertRaises(ValueError):
            rs.render(camera_name="Camera", camera_label="Front Camera")

    def test_render_returns_failure_outcome_when_doRender_fails(self):
        from dazpy._render import RenderOutcome
        rs, client = self._make_render(
            {"success": False, "output_path": "/tmp/render.png"}
        )
        result = rs.render()
        self.assertEqual(
            result, RenderOutcome(success=False, output_path="/tmp/render.png")
        )

    def test_render_and_wait_returns_render_outcome(self):
        from dazpy._render import RenderOutcome
        rs, client = self._make_render(
            {"success": True, "output_path": "/tmp/render.png"}
        )
        result = rs.render_and_wait()
        self.assertEqual(
            result, RenderOutcome(success=True, output_path="/tmp/render.png")
        )

    def test_render_outcome_bool_reflects_success(self):
        from dazpy._render import RenderOutcome
        self.assertTrue(RenderOutcome(success=True, output_path="/tmp/render.png"))
        self.assertFalse(RenderOutcome(success=False, output_path="/tmp/render.png"))
        self.assertFalse(RenderOutcome(success=False, output_path=None))

    def test_render_truthiness_check_reflects_failure(self):
        # Regression: `if rs.render():` must behave like the old bool contract --
        # a failed render must not evaluate truthy just because RenderOutcome
        # is a non-empty object.
        rs, client = self._make_render(
            {"success": False, "output_path": "/tmp/render.png"}
        )
        outcome = rs.render()
        if outcome:
            self.fail("RenderOutcome(success=False) evaluated truthy")

    def test_render_and_wait_truthiness_check_reflects_success(self):
        rs, client = self._make_render(
            {"success": True, "output_path": "/tmp/render.png"}
        )
        outcome = rs.render_and_wait()
        self.assertTrue(bool(outcome))

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

    def test_active_engine_maps_known_class_name(self):
        rs, client = self._make_render("DzIrayRenderer")
        val = rs.active_engine()
        self.assertEqual(val, "iray")
        script = client.execute.call_args[0][0]
        self.assertIn("getActiveRenderer", script)
        self.assertIn("className", script)
        self.assertIn("renderType", script)

    def test_active_engine_falls_back_to_raw_class_name(self):
        rs, client = self._make_render("DzSomeUnknownRenderer")
        val = rs.active_engine()
        self.assertEqual(val, "DzSomeUnknownRenderer")

    def test_active_engine_null_guard(self):
        rs, client = self._make_render(None)
        val = rs.active_engine()
        self.assertIsNone(val)

    def test_active_engine_viewport_mode(self):
        rs, client = self._make_render("viewport")
        val = rs.active_engine()
        self.assertEqual(val, "viewport")

    def test_active_engine_multi_pass_opengl_mode(self):
        rs, client = self._make_render("multi_pass_opengl")
        val = rs.active_engine()
        self.assertEqual(val, "multi_pass_opengl")

    @staticmethod
    def _engine_readback(
        render_type=2,
        renderer_class="DzIrayRenderer",
        renderer_name="NVIDIA Iray",
    ):
        return {
            "read_schema": 1,
            "ok": True,
            "reason": None,
            "render_type": render_type,
            "active_renderer_class": renderer_class,
            "active_renderer_name": renderer_name,
        }

    def test_render_engine_state_iray_has_exact_schema_raw_facts_and_provenance(self):
        rs, client = self._make_render(self._engine_readback())

        state = rs.render_engine_state()

        self.assertEqual(
            set(state),
            {
                "selector_schema",
                "status",
                "engine",
                "method",
                "reason",
                "render_type",
                "active_renderer",
            },
        )
        self.assertEqual(state["selector_schema"], 1)
        self.assertEqual(state["status"], "verified_iray")
        self.assertEqual(state["engine"], "iray")
        self.assertEqual(state["method"], "render_settings_engine_selector")
        self.assertIsNone(state["reason"])
        self.assertEqual(
            state["render_type"],
            {
                "raw": 2,
                "name": "Software",
                "provenance": {
                    "kind": "live_readback",
                    "source": "DzRenderOptions.renderType",
                },
            },
        )
        self.assertEqual(
            state["active_renderer"],
            {
                "class_name": "DzIrayRenderer",
                "name": "NVIDIA Iray",
                "provenance": {
                    "kind": "live_readback",
                    "source": "DzRenderMgr.getActiveRenderer",
                },
            },
        )
        script = client.execute.call_args[0][0]
        self.assertIn("Number(opts.renderType)", script)
        self.assertIn("renderer.className()", script)
        self.assertIn("renderer.getName()", script)

    def test_render_engine_state_viewport_overrules_retained_iray_identity(self):
        rs, _client = self._make_render(self._engine_readback(render_type=0))
        state = rs.render_engine_state()
        self.assertEqual(state["status"], "verified_non_iray")
        self.assertEqual(state["engine"], "viewport_gl")
        self.assertEqual(state["render_type"]["name"], "ScreenShot")
        self.assertEqual(state["active_renderer"]["class_name"], "DzIrayRenderer")

    def test_render_engine_state_hardware_assisted_is_viewport_gl(self):
        rs, _client = self._make_render(self._engine_readback(render_type=1))
        state = rs.render_engine_state()
        self.assertEqual(state["status"], "verified_non_iray")
        self.assertEqual(state["engine"], "viewport_gl")
        self.assertEqual(state["render_type"]["name"], "HardwareAssisted")

    def test_render_engine_state_other_software_renderer_is_non_iray(self):
        rs, _client = self._make_render(
            self._engine_readback(
                render_type=2,
                renderer_class="DzFilamentRenderer",
                renderer_name="Filament",
            )
        )
        state = rs.render_engine_state()
        self.assertEqual(state["status"], "verified_non_iray")
        self.assertEqual(state["engine"], "other_non_iray")

    def test_render_engine_state_malformed_or_missing_software_renderer_is_unavailable(self):
        cases = [
            None,
            {"read_schema": 2, "ok": True},
            self._engine_readback(render_type="2"),
            self._engine_readback(render_type=2, renderer_class=None, renderer_name=None),
        ]
        for raw in cases:
            with self.subTest(raw=raw):
                rs, _client = self._make_render(raw)
                state = rs.render_engine_state()
                self.assertEqual(state["status"], "unavailable")
                self.assertIsNone(state["engine"])

    def test_set_render_engine_iray_exact_success_schema_and_operation_order(self):
        raw = {
            "mutation_schema": 1,
            "ok": True,
            "requested_engine": "iray",
            "persisted": True,
            "reason": None,
            "readback": self._engine_readback(),
        }
        rs, client = self._make_render(raw)

        result = rs.set_render_engine(" IRAY ")

        self.assertEqual(
            set(result),
            {
                "mutation_schema",
                "success",
                "requested_engine",
                "persisted",
                "reason",
                "readback",
            },
        )
        self.assertEqual(result["mutation_schema"], 1)
        self.assertTrue(result["success"])
        self.assertEqual(result["requested_engine"], "iray")
        self.assertTrue(result["persisted"])
        self.assertEqual(result["readback"]["status"], "verified_iray")
        script = client.execute.call_args[0][0]
        set_renderer = script.index("setActiveRenderer")
        set_render_type = script.index("opts.renderType = opts.Software")
        self.assertLess(set_renderer, set_render_type)
        self.assertLess(set_render_type, script.index("opts.applyChanges"))
        self.assertLess(script.index("opts.applyChanges"), script.index("var readback"))

    def test_set_render_engine_viewport_requires_exact_screenshot_readback(self):
        raw = {
            "mutation_schema": 1,
            "ok": True,
            "requested_engine": "viewport",
            "persisted": True,
            "reason": None,
            "readback": self._engine_readback(render_type=0),
        }
        rs, client = self._make_render(raw)
        result = rs.set_render_engine("viewport")
        self.assertEqual(result["readback"]["engine"], "viewport_gl")
        self.assertIn("opts.renderType = opts.ScreenShot", client.execute.call_args[0][0])

    def test_set_render_engine_rejects_invalid_requests_before_dispatch(self):
        rs, client = self._make_render(None)
        for invalid in (None, "", "filament", "not-an-engine"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    rs.set_render_engine(invalid)
        client.execute.assert_not_called()

    def test_set_render_engine_fails_closed_for_lookup_mutation_and_apply_failures(self):
        from dazpy.exceptions import RenderError

        for reason in (
            "iray_renderer_unavailable",
            "mutation_failed",
            "render_manager_unavailable",
            "render_options_unavailable",
        ):
            with self.subTest(reason=reason):
                raw = {
                    "mutation_schema": 1,
                    "ok": False,
                    "requested_engine": "iray",
                    "persisted": False,
                    "reason": reason,
                    "readback": self._engine_readback(),
                }
                rs, _client = self._make_render(raw)
                with self.assertRaisesRegex(RenderError, reason):
                    rs.set_render_engine("iray")

    def test_set_render_engine_rejects_apply_readback_mismatch_even_if_provider_says_ok(self):
        from dazpy.exceptions import RenderError

        raw = {
            "mutation_schema": 1,
            "ok": True,
            "requested_engine": "iray",
            "persisted": True,
            "reason": None,
            "readback": self._engine_readback(render_type=0),
        }
        rs, _client = self._make_render(raw)
        with self.assertRaisesRegex(RenderError, "readback_mismatch"):
            rs.set_render_engine("iray")

    def test_set_render_engine_rejects_malformed_mutation_schema(self):
        from dazpy.exceptions import RenderError

        rs, _client = self._make_render({"mutation_schema": 2, "ok": True})
        with self.assertRaisesRegex(RenderError, "malformed_response"):
            rs.set_render_engine("iray")

    def test_set_active_engine_iray(self):
        rs, client = self._make_render(True)
        rs.set_active_engine("iray")
        script = client.execute.call_args[0][0]
        self.assertIn("findRenderer", script)
        self.assertIn("DzIrayRenderer", script)
        self.assertIn("setActiveRenderer", script)
        self.assertIn("opts.Software", script)

    def test_set_active_engine_raw_class_name(self):
        rs, client = self._make_render(True)
        rs.set_active_engine("DzFilamentRenderer")
        script = client.execute.call_args[0][0]
        self.assertIn("DzFilamentRenderer", script)

    def test_set_active_engine_raises_when_renderer_unavailable(self):
        from dazpy.exceptions import RenderError
        rs, client = self._make_render(False)
        with self.assertRaises(RenderError):
            rs.set_active_engine("filament")

    def test_set_active_engine_viewport(self):
        rs, client = self._make_render(True)
        rs.set_active_engine("Viewport")
        script = client.execute.call_args[0][0]
        self.assertIn("opts.ScreenShot", script)
        self.assertNotIn("findRenderer", script)

    def test_set_active_engine_multi_pass_opengl(self):
        rs, client = self._make_render(True)
        rs.set_active_engine("multi_pass_opengl")
        script = client.execute.call_args[0][0]
        self.assertIn("opts.HardwareAssisted", script)
        self.assertNotIn("findRenderer", script)

    def test_has_render(self):
        rs, client = self._make_render(True)
        val = rs.has_render()
        self.assertTrue(val)
        script = client.execute.call_args[0][0]
        self.assertIn("hasRender", script)

    def test_canvases_enabled_getter_uses_render_element_objects(self):
        rs, client = self._make_render(True)
        val = rs.canvases_enabled
        self.assertTrue(val)
        script = client.execute.call_args[0][0]
        self.assertIn('inherits("DzIrayPropertyHolder")', script)
        self.assertNotIn("getRenderElementObjects()[1]", script)
        self.assertIn("renderToCanvases", script)

    def test_iray_holder_lookup_order_class_then_label_then_index(self):
        rs, _ = self._make_render(None)
        expr = rs._iray_render_options_holder()
        cls_pos = expr.index('inherits("DzIrayPropertyHolder")')
        label_pos = expr.index('"NVIDIA Iray Render Options"')
        index_pos = expr.index("_objs[1]")
        self.assertLess(cls_pos, label_pos)
        self.assertLess(label_pos, index_pos)
        self.assertIn("_objs.length > 1", expr)

    def test_holder_fallback_output_becomes_runtime_warning(self):
        from dazpy._render import _HOLDER_FALLBACK_MARKER
        rs, _ = self._make_render(
            True,
            output=[f"{_HOLDER_FALLBACK_MARKER} DzIrayPropertyHolder not found; using index 1"],
        )
        with self.assertWarnsRegex(RuntimeWarning, "DzIrayPropertyHolder not found"):
            self.assertTrue(rs.canvases_enabled)

    def test_holder_lookup_without_fallback_emits_no_warning(self):
        import warnings as _w
        rs, _ = self._make_render(True, output=["unrelated log line"])
        with _w.catch_warnings():
            _w.simplefilter("error")
            self.assertTrue(rs.canvases_enabled)

    def test_render_uses_class_based_canvas_holder_lookup(self):
        rs, client = self._make_render({"success": True, "output_path": "C:/x.png"})
        try:
            rs.render()
        except Exception:
            pass
        scripts = [c.args[0] for c in client.execute.call_args_list]
        self.assertTrue(any('inherits("DzIrayPropertyHolder")' in s for s in scripts))

    def test_canvases_enabled_setter_refreshes_pane(self):
        rs, client = self._make_render(None)
        rs.canvases_enabled = False
        script = client.execute.call_args[0][0]
        self.assertIn("renderToCanvases = false", script)
        self.assertIn("DzRenderSettingsPane", script)
        self.assertIn(".refresh()", script)

    def test_list_canvases_returns_canvas_objects(self):
        from dazpy._render import Canvas
        rs, client = self._make_render(
            [{"name": "Canvas1", "canvas_type": "Normal", "index": 0}]
        )
        canvases = rs.list_canvases()
        self.assertEqual(canvases, [Canvas(name="Canvas1", canvas_type="Normal", index=0)])
        script = client.execute.call_args[0][0]
        self.assertIn("getNumCanvasDefinitions", script)
        self.assertIn("getCanvasDefinition", script)
        self.assertIn("canvasTypeToString", script)

    def test_list_canvases_empty_when_none_configured(self):
        rs, client = self._make_render([])
        self.assertEqual(rs.list_canvases(), [])

    def test_add_canvas_uses_find_canvas_definition_with_create(self):
        from dazpy._render import Canvas
        rs, client = self._make_render(
            {"name": "DepthPass", "canvas_type": "Depth", "index": 1}
        )
        canvas = rs.add_canvas("DepthPass", "Depth")
        self.assertEqual(canvas, Canvas(name="DepthPass", canvas_type="Depth", index=1))
        script = client.execute.call_args[0][0]
        self.assertIn("findCanvasDefinition(\"DepthPass\", true)", script)
        self.assertIn("canvasTypeFromString(\"Depth\")", script)
        self.assertIn(".refresh()", script)

    def test_add_canvas_raises_render_error_when_unavailable(self):
        from dazpy.exceptions import RenderError
        rs, client = self._make_render(None)
        with self.assertRaises(RenderError):
            rs.add_canvas("Foo", "Beauty")

    def test_remove_canvas_uses_find_canvas_definition_no_create(self):
        rs, client = self._make_render(True)
        result = rs.remove_canvas("Canvas1")
        self.assertTrue(result)
        script = client.execute.call_args[0][0]
        self.assertIn("findCanvasDefinition(\"Canvas1\", false)", script)
        self.assertIn("removeCanvasDefinition", script)
        self.assertIn(".refresh()", script)

    def test_remove_canvas_returns_false_when_missing(self):
        rs, client = self._make_render(False)
        self.assertFalse(rs.remove_canvas("NoSuchCanvas"))

    def test_canvas_output_paths_derives_convention(self):
        rs, client = self._make_render(
            [{"name": "Canvas1", "canvas_type": "Normal", "index": 0}]
        )
        paths = rs.canvas_output_paths("C:/tmp/out.png")
        self.assertEqual(
            paths,
            {"Canvas1": "C:/tmp/out_canvases/out-Canvas1-Normal.exr"},
        )

    def test_canvas_output_paths_no_directory(self):
        rs, client = self._make_render(
            [{"name": "Canvas1", "canvas_type": "Depth", "index": 0}]
        )
        paths = rs.canvas_output_paths("out.png")
        self.assertEqual(paths, {"Canvas1": "out_canvases/out-Canvas1-Depth.exr"})


class TestDazRenderSettingsEnvironment(unittest.TestCase):
    def setUp(self):
        from dazpy._render import DazRenderSettings
        self.DazRenderSettings = DazRenderSettings

    def _make_render(self, return_value=None):
        client = mock_client(return_value)
        return self.DazRenderSettings(client), client

    def test_environment_holder_looks_up_by_class_with_index_3_fallback(self):
        rs, client = self._make_render(1.0)
        rs._get_environment_property("Environment Intensity")
        script = client.execute.call_args[0][0]
        self.assertIn('inherits("DzEnvironmentNode")', script)
        self.assertIn('"Environment Options"', script)
        self.assertIn("_objs[3]", script)
        self.assertNotIn("getRenderElementObjects()[3]", script)

    def test_environment_holder_searches_scene_nodes_before_render_elements(self):
        # Studio 4 keeps the environment on a scene node, not a render element.
        rs, client = self._make_render(1.0)
        rs._get_environment_property("Environment Intensity")
        script = client.execute.call_args[0][0]
        self.assertIn("Scene.getNumNodes()", script)
        self.assertLess(script.index("Scene.getNode("), script.index("getRenderElementObjects()"))

    def test_get_environment_property_reads_named_property(self):
        rs, client = self._make_render(1.0)
        val = rs._get_environment_property("Environment Intensity")
        self.assertEqual(val, 1.0)
        script = client.execute.call_args[0][0]
        self.assertIn("findProperty", script)
        self.assertIn("Environment Intensity", script)
        self.assertIn("getValue", script)

    def test_set_environment_property_writes_named_property(self):
        rs, client = self._make_render(None)
        rs._set_environment_property("Environment Intensity", 2.5)
        script = client.execute.call_args[0][0]
        self.assertIn("Environment Intensity", script)
        self.assertIn("setValue", script)
        self.assertIn("2.5", script)

    def test_set_environment_property_from_string_uses_setValueFromString(self):
        rs, client = self._make_render(None)
        rs._set_environment_property_from_string("Environment Mode", "Dome Only")
        script = client.execute.call_args[0][0]
        self.assertIn("Environment Mode", script)
        self.assertIn("setValueFromString", script)
        self.assertIn("Dome Only", script)

    def test_set_environment_map_raises_when_file_missing(self):
        import tempfile
        rs, client = self._make_render(None)
        missing_path = os.path.join(tempfile.gettempdir(), "definitely_not_a_real_hdri_file.hdr")
        self.assertFalse(os.path.isfile(missing_path))
        with self.assertRaises(FileNotFoundError):
            rs._set_environment_map(missing_path)
        client.execute.assert_not_called()

    def test_set_environment_map_calls_setMap_when_file_exists(self):
        import tempfile
        rs, client = self._make_render(None)
        with tempfile.NamedTemporaryFile(suffix=".hdr") as f:
            rs._set_environment_map(f.name)
            script = client.execute.call_args[0][0]
            self.assertIn("Environment Map", script)
            self.assertIn("setMap", script)
            self.assertIn(f.name.replace("\\", "\\\\"), script)

    def test_set_environment_map_raises_when_path_relative(self):
        rs, client = self._make_render(None)
        with self.assertRaises(ValueError):
            rs._set_environment_map("studio.hdr")
        client.execute.assert_not_called()


class TestCameraLightHelpers(unittest.TestCase):
    """viewport camera setter, camera/light listings, environment mode (qrd)."""

    def test_set_viewport_camera(self):
        from dazpy._camera import DazCamera
        client = mock_client({"status": "ok", "previous": "Perspective View"})
        cam = DazCamera(client, NodeIdentifier("12", kind="element_id"))
        self.assertEqual(DazScene(client).set_viewport_camera(cam), "Perspective View")
        script = client.execute.call_args[0][0]
        self.assertIn("setCamera(_cam)", script)
        self.assertIn("Scene.findNodeByElementID(12)", script)

    def test_set_viewport_camera_by_view_label(self):
        client = mock_client({"status": "ok", "previous": "Camera 1"})
        DazScene(client).set_viewport_camera("Perspective View")
        script = client.execute.call_args[0][0]
        self.assertIn("getViewCamera(j)", script)
        self.assertIn('"Perspective View"', script)

    def test_set_viewport_camera_errors(self):
        from dazpy._camera import DazCamera
        for status, exc in (("missing", exceptions.NodeNotFoundError),
                            ("not_camera", TypeError), ("no_viewport", RuntimeError)):
            client = mock_client({"status": status})
            with self.assertRaises(exc):
                DazScene(client).set_viewport_camera(DazCamera(client, NodeIdentifier("1")))

    def test_camera_and_light_info(self):
        client = mock_client([{"index": 0, "label": "Camera 1", "name": "Camera_1",
                                "type": "DzBasicCamera", "element_id": 7,
                                "position": [0, 150, 300], "focal_length": 65.0}])
        cams = DazScene(client).camera_info()
        self.assertEqual((cams[0].label, cams[0].position, cams[0].focal_length),
                         ("Camera 1", (0.0, 150.0, 300.0), 65.0))
        client = mock_client([{"index": 0, "label": "Key", "name": "Key", "type": "DzSpotLight",
                                "element_id": 8, "position": [1, 2, 3], "flux": 2000.0,
                                "on": True}])
        lights = DazScene(client).light_info()
        self.assertEqual((lights[0].flux, lights[0].on), (2000.0, True))

    def test_light_aim_at(self):
        from dazpy._light import DazLight
        client = mock_client(None)
        DazLight(client, NodeIdentifier("3", kind="element_id")).aim_at(0, 150, 0)
        self.assertIn("_node.aimAt(new DzVec3(0.0, 150.0, 0.0))", client.execute.call_args[0][0])

    def test_draw_ground_plane(self):
        from dazpy import DazRenderSettings
        client = mock_client(True)
        rs = DazRenderSettings(client)
        self.assertTrue(rs.draw_ground_plane)
        rs.draw_ground_plane = False
        script = client.execute.call_args[0][0]
        self.assertIn("opts.drawGroundPlane = false", script)
        self.assertIn("applyChanges()", script)

    def test_set_environment_properties(self):
        from dazpy import DazRenderSettings
        client = mock_client({"holder": True, "matched": ["Environment Intensity", None]})
        r = DazRenderSettings(client).set_environment_properties(
            [(["Environment Intensity", "Dome Intensity"], 0.5), (["Sun Intensity"], 2.0)])
        self.assertEqual(r, ["Environment Intensity", None])
        script = client.execute.call_args[0][0]
        self.assertIn("DzEnvironmentNode", script)
        self.assertIn("findPropertyByLabel", script)
        client = mock_client({"holder": False})
        self.assertIsNone(DazRenderSettings(client).set_environment_properties([(["X"], 1)]))

    def test_environment_mode(self):
        from dazpy import DazRenderSettings
        client = mock_client(True)
        self.assertTrue(DazRenderSettings(client).set_environment_mode("scene_only"))
        script = client.execute.call_args[0][0]
        self.assertIn('findProperty("Environment Mode")', script)
        self.assertIn("setValue(3)", script)
        with self.assertRaises(ValueError):
            DazRenderSettings(client).set_environment_mode("sunny")
        client = mock_client(2)
        self.assertEqual(DazRenderSettings(client).environment_mode, "sun_sky")


if __name__ == "__main__":
    unittest.main()
