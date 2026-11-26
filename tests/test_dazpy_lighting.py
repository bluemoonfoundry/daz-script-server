"""dazpy unit tests: lights: script generation, three-point setup, HDRI environment.

Mock-based; no server or DAZ Studio required.
Shared fakes live in tests/dazpy_fakes.py.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dazpy._result import ExecutionResult
from dazpy._node import NodeIdentifier
from dazpy._client import DazClient
from dazpy_fakes import mock_client


def _hdri_client(intensity_readback):
    """Client whose ``_get_environment_property`` readback (a ``getValue()``
    script) returns *intensity_readback*; every write-side call returns
    ``None`` (mirroring a real holder's no-return ``setValue`` scripts)."""
    client = MagicMock(spec=DazClient)

    def _execute(script, *args, **kwargs):
        value = intensity_readback if "getValue" in script else None
        return ExecutionResult(value=value, output=[], request_id="test1234")

    client.execute.side_effect = _execute
    return client


class TestDazLightScriptGeneration(unittest.TestCase):
    def setUp(self):
        from dazpy._light import DazLight
        self.DazLight = DazLight

    def _light(self, return_value=None):
        client = mock_client(return_value)
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
        self.assertIn("'Color'", script)
        self.assertIn("setColorValue", script)
        self.assertIn("255", script)
        self.assertIn("128", script)
        self.assertIn("0", script)


class _FakeLightingLight:
    def __init__(self, light_type: str, name: str | None = None):
        self.light_type = light_type
        self.name = name
        self.position_calls: list[tuple[float, float, float]] = []
        self.rotation_calls: list[tuple[float, float, float]] = []
        self.color_calls: list[tuple[int, int, int]] = []
        self.intensity: float | None = None

    def set_position(self, x, y, z):
        self.position_calls.append((x, y, z))

    def set_rotation(self, x, y, z):
        self.rotation_calls.append((x, y, z))

    def set_color(self, r, g, b):
        self.color_calls.append((r, g, b))


class _FakeLightingScene:
    def __init__(self):
        self.created: list[_FakeLightingLight] = []

    def create_light(self, light_type: str, name: str | None = None) -> _FakeLightingLight:
        light = _FakeLightingLight(light_type, name)
        self.created.append(light)
        return light


class _FakeLightingTargetNode:
    def __init__(self, x: float, y: float, z: float):
        self.position = {"x": x, "y": y, "z": z}


class TestThreePointLightSetup(unittest.TestCase):
    def test_default_specs_have_expected_angles_and_intensities(self):
        from dazpy.lighting import ThreePointLightSetup
        from dazpy.math3 import Vec3
        setup = ThreePointLightSetup(target=Vec3(0, 0, 0))
        self.assertEqual(setup.key.role, "key")
        self.assertEqual(setup.key.azimuth_deg, 45.0)
        self.assertEqual(setup.key.elevation_deg, 30.0)
        self.assertEqual(setup.key.intensity, 100.0)
        self.assertEqual(setup.fill.role, "fill")
        self.assertEqual(setup.fill.azimuth_deg, -45.0)
        self.assertEqual(setup.fill.intensity, 50.0)
        self.assertEqual(setup.rim.role, "rim")
        self.assertEqual(setup.rim.azimuth_deg, 180.0)
        self.assertEqual(setup.rim.intensity, 75.0)
        self.assertEqual(setup.light_type, "spot")

    def test_light_spec_is_frozen(self):
        from dazpy.lighting import LightSpec
        spec = LightSpec(role="key", azimuth_deg=0.0, elevation_deg=0.0, distance=1.0, intensity=1.0)
        with self.assertRaises(Exception):
            spec.intensity = 2.0

    def test_apply_creates_three_lights_of_configured_type(self):
        from dazpy.lighting import ThreePointLightSetup, apply_three_point_light_setup
        from dazpy.math3 import Vec3
        scene = _FakeLightingScene()
        setup = ThreePointLightSetup(target=Vec3(0, 0, 0), light_type="distant")
        apply_three_point_light_setup(scene, setup)
        self.assertEqual(len(scene.created), 3)
        self.assertTrue(all(light.light_type == "distant" for light in scene.created))

    def test_apply_returns_rig_in_key_fill_rim_order(self):
        from dazpy.lighting import ThreePointLightSetup, apply_three_point_light_setup
        from dazpy.math3 import Vec3
        scene = _FakeLightingScene()
        setup = ThreePointLightSetup(target=Vec3(0, 0, 0))
        rig = apply_three_point_light_setup(scene, setup)
        self.assertIs(rig.key, scene.created[0])
        self.assertIs(rig.fill, scene.created[1])
        self.assertIs(rig.rim, scene.created[2])
        self.assertEqual(rig.key.name, "key")
        self.assertEqual(rig.fill.name, "fill")
        self.assertEqual(rig.rim.name, "rim")

    def test_apply_sets_position_rotation_intensity_color_from_spec(self):
        from dazpy.lighting import LightSpec, ThreePointLightSetup, apply_three_point_light_setup
        from dazpy.math3 import Vec3
        scene = _FakeLightingScene()
        key_spec = LightSpec(
            role="key", azimuth_deg=0.0, elevation_deg=0.0, distance=150.0,
            intensity=88.0, color=(200, 210, 220),
        )
        setup = ThreePointLightSetup(target=Vec3(0, 0, 0), key=key_spec)
        rig = apply_three_point_light_setup(scene, setup)
        self.assertEqual(len(rig.key.position_calls), 1)
        x, y, z = rig.key.position_calls[0]
        self.assertAlmostEqual(x, 0.0, places=6)
        self.assertAlmostEqual(y, 0.0, places=6)
        self.assertAlmostEqual(z, 150.0, places=6)
        self.assertEqual(len(rig.key.rotation_calls), 1)
        self.assertAlmostEqual(rig.key.rotation_calls[0][0], 0.0, places=6)
        self.assertAlmostEqual(rig.key.rotation_calls[0][1], 0.0, places=6)
        self.assertEqual(rig.key.intensity, 88.0)
        self.assertEqual(rig.key.color_calls, [(200, 210, 220)])

    def test_apply_resolves_dazNode_target_via_position(self):
        from dazpy.lighting import ThreePointLightSetup, apply_three_point_light_setup, _spherical_offset
        from dazpy.math3 import Vec3
        scene = _FakeLightingScene()
        node = _FakeLightingTargetNode(10.0, 20.0, 30.0)
        setup = ThreePointLightSetup(target=node)
        rig = apply_three_point_light_setup(scene, setup)
        # key defaults to azimuth=45, elevation=30, distance=150 relative to (10, 20, 30)
        expected = _spherical_offset(Vec3(10.0, 20.0, 30.0), 45.0, 30.0, 150.0)
        x, y, z = rig.key.position_calls[0]
        self.assertAlmostEqual(x, expected.x, places=6)
        self.assertAlmostEqual(y, expected.y, places=6)
        self.assertAlmostEqual(z, expected.z, places=6)

    def test_apply_honors_explicit_position_override(self):
        from dazpy.lighting import LightSpec, ThreePointLightSetup, apply_three_point_light_setup
        from dazpy.math3 import Vec3
        scene = _FakeLightingScene()
        override_spec = LightSpec(
            role="key", azimuth_deg=999.0, elevation_deg=999.0, distance=999.0,
            intensity=50.0, position=Vec3(1.0, 2.0, 3.0),
        )
        setup = ThreePointLightSetup(target=Vec3(0, 0, 0), key=override_spec)
        rig = apply_three_point_light_setup(scene, setup)
        self.assertEqual(rig.key.position_calls[0], (1.0, 2.0, 3.0))

    def test_apply_raises_value_error_when_target_node_has_no_position(self):
        from dazpy.lighting import ThreePointLightSetup, apply_three_point_light_setup

        class _DeletedTargetNode:
            position = None

        scene = _FakeLightingScene()
        setup = ThreePointLightSetup(target=_DeletedTargetNode())
        with self.assertRaisesRegex(ValueError, "no position"):
            apply_three_point_light_setup(scene, setup)


class TestHDRIEnvironment(unittest.TestCase):
    def test_defaults(self):
        from dazpy.lighting import HDRIEnvironment
        env = HDRIEnvironment(image_path="/tmp/studio.hdr")
        self.assertEqual(env.image_path, "/tmp/studio.hdr")
        self.assertEqual(env.intensity, 1.0)
        self.assertEqual(env.rotation_deg, 0.0)
        self.assertEqual(env.mode, "dome_only")
        self.assertFalse(env.draw_dome)
        self.assertIsNone(env.resolution)

    def test_is_frozen(self):
        from dazpy.lighting import HDRIEnvironment
        env = HDRIEnvironment(image_path="/tmp/studio.hdr")
        with self.assertRaises(Exception):
            env.intensity = 2.0

    def test_apply_raises_file_not_found_before_any_client_call(self):
        from dazpy._render import DazRenderSettings
        from dazpy.lighting import HDRIEnvironment, apply_hdri_environment
        import tempfile
        client = mock_client(None)
        rs = DazRenderSettings(client)
        missing_path = os.path.join(tempfile.gettempdir(), "definitely_not_a_real_hdri_file.hdr")
        self.assertFalse(os.path.isfile(missing_path))
        env = HDRIEnvironment(image_path=missing_path)
        with self.assertRaises(FileNotFoundError):
            apply_hdri_environment(rs, env)
        client.execute.assert_not_called()

    def test_apply_raises_value_error_on_invalid_mode_before_any_client_call(self):
        from dazpy._render import DazRenderSettings
        from dazpy.lighting import HDRIEnvironment, apply_hdri_environment
        import tempfile
        client = mock_client(None)
        rs = DazRenderSettings(client)
        with tempfile.NamedTemporaryFile(suffix=".hdr") as f:
            env = HDRIEnvironment(image_path=f.name, mode="sun_sky")
            with self.assertRaises(ValueError):
                apply_hdri_environment(rs, env)
        client.execute.assert_not_called()

    def test_apply_happy_path_sets_all_properties_in_order(self):
        from dazpy._render import DazRenderSettings
        from dazpy.lighting import HDRIEnvironment, apply_hdri_environment
        import tempfile
        client = _hdri_client(1.5)
        rs = DazRenderSettings(client)
        with tempfile.NamedTemporaryFile(suffix=".hdr") as f:
            env = HDRIEnvironment(
                image_path=f.name, intensity=1.5, rotation_deg=90.0,
                mode="dome_and_scene", draw_dome=True, resolution=1024,
            )
            apply_hdri_environment(rs, env)
            scripts = [call.args[0] for call in client.execute.call_args_list]
        self.assertEqual(len(scripts), 7)
        self.assertIn("setMap", scripts[0])
        self.assertIn("Environment Intensity", scripts[1])
        self.assertIn("1.5", scripts[1])
        self.assertIn("Dome Rotation", scripts[2])
        self.assertIn("90.0", scripts[2])
        self.assertIn("Environment Mode", scripts[3])
        self.assertIn("Dome and Scene", scripts[3])
        self.assertIn("Draw Dome", scripts[4])
        self.assertIn("true", scripts[4])
        self.assertIn("Environment Lighting Resolution", scripts[5])
        self.assertIn("1024", scripts[5])
        self.assertIn("Environment Intensity", scripts[6])
        self.assertIn("getValue", scripts[6])

    def test_apply_skips_resolution_property_when_none(self):
        from dazpy._render import DazRenderSettings
        from dazpy.lighting import HDRIEnvironment, apply_hdri_environment
        import tempfile
        client = _hdri_client(1.0)
        rs = DazRenderSettings(client)
        with tempfile.NamedTemporaryFile(suffix=".hdr") as f:
            env = HDRIEnvironment(image_path=f.name)
            apply_hdri_environment(rs, env)
            scripts = [call.args[0] for call in client.execute.call_args_list]
        self.assertEqual(len(scripts), 6)
        self.assertFalse(any("Environment Lighting Resolution" in s for s in scripts))

    def test_apply_maps_each_mode_to_correct_dazscript_label(self):
        from dazpy._render import DazRenderSettings
        from dazpy.lighting import HDRIEnvironment, apply_hdri_environment
        import tempfile
        expected = {
            "dome_only": "Dome Only",
            "dome_and_scene": "Dome and Scene",
            "scene_only": "Scene Only",
        }
        for mode, label in expected.items():
            with self.subTest(mode=mode):
                client = _hdri_client(1.0)
                rs = DazRenderSettings(client)
                with tempfile.NamedTemporaryFile(suffix=".hdr") as f:
                    env = HDRIEnvironment(image_path=f.name, mode=mode)
                    apply_hdri_environment(rs, env)
                    scripts = [call.args[0] for call in client.execute.call_args_list]
                mode_script = next(s for s in scripts if "Environment Mode" in s)
                self.assertIn(label, mode_script)

    def test_apply_raises_render_error_when_environment_holder_unavailable(self):
        """Simulates the Environment Options group being absent (render type not
        Software): every write silently no-ops and the readback returns None."""
        from dazpy._render import DazRenderSettings
        from dazpy.lighting import HDRIEnvironment, apply_hdri_environment
        from dazpy.exceptions import RenderError
        import tempfile
        client = mock_client(None)  # every execute() call returns value=None
        rs = DazRenderSettings(client)
        with tempfile.NamedTemporaryFile(suffix=".hdr") as f:
            env = HDRIEnvironment(image_path=f.name, intensity=1.5)
            with self.assertRaisesRegex(RenderError, "readback"):
                apply_hdri_environment(rs, env)

    def test_apply_raises_render_error_when_intensity_readback_mismatches(self):
        """Holder resolves but the readback value doesn't match what was set --
        should not be silently treated as success."""
        from dazpy._render import DazRenderSettings
        from dazpy.lighting import HDRIEnvironment, apply_hdri_environment
        from dazpy.exceptions import RenderError
        import tempfile
        client = _hdri_client(0.0)  # readback disagrees with requested 1.5
        rs = DazRenderSettings(client)
        with tempfile.NamedTemporaryFile(suffix=".hdr") as f:
            env = HDRIEnvironment(image_path=f.name, intensity=1.5)
            with self.assertRaisesRegex(RenderError, "readback"):
                apply_hdri_environment(rs, env)


class TestSetLightColor(unittest.TestCase):
    def test_calls_light_set_color_with_same_args(self):
        from dazpy.lighting import set_light_color
        light = _FakeLightingLight("spot", "Key")
        set_light_color(light, 255, 128, 0)
        self.assertEqual(light.color_calls, [(255, 128, 0)])

    def test_returns_none(self):
        from dazpy.lighting import set_light_color
        light = _FakeLightingLight("spot", "Key")
        result = set_light_color(light, 255, 255, 255)
        self.assertIsNone(result)


class TestLightingExports(unittest.TestCase):
    def test_lighting_symbols_importable_from_top_level_package(self):
        import dazpy
        self.assertTrue(hasattr(dazpy, "LightSpec"))
        self.assertTrue(hasattr(dazpy, "ThreePointLightSetup"))
        self.assertTrue(hasattr(dazpy, "ThreePointLightRig"))
        self.assertTrue(hasattr(dazpy, "apply_three_point_light_setup"))
        self.assertTrue(hasattr(dazpy, "HDRIEnvironment"))
        self.assertTrue(hasattr(dazpy, "apply_hdri_environment"))
        self.assertTrue(hasattr(dazpy, "set_light_color"))
        self.assertIn("LightSpec", dazpy.__all__)
        self.assertIn("ThreePointLightSetup", dazpy.__all__)
        self.assertIn("ThreePointLightRig", dazpy.__all__)
        self.assertIn("apply_three_point_light_setup", dazpy.__all__)
        self.assertIn("HDRIEnvironment", dazpy.__all__)
        self.assertIn("apply_hdri_environment", dazpy.__all__)
        self.assertIn("set_light_color", dazpy.__all__)


if __name__ == "__main__":
    unittest.main()
