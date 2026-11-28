"""dazpy unit tests: materials, surfaces and Iray material helpers.

Mock-based; no server or DAZ Studio required.
Shared fakes live in tests/dazpy_fakes.py.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dazpy._node import DazNode, NodeIdentifier
from dazpy._scene import DazScene
from dazpy import exceptions
from dazpy_fakes import mock_client


class TestMaterialTools(unittest.TestCase):
    """material_info / resolve_material / property_values / set_property_value /
    copy_from (daz-mcp-server-et7)."""

    def _node(self, value):
        client = mock_client(value)
        return DazNode(client, NodeIdentifier("9", kind="element_id")), client

    def test_material_info(self):
        node, client = self._node([{"index": 0, "name": "Skin", "label": "Skin",
                                    "shader": "DzUberIrayMaterial"}])
        info = node.material_info()
        self.assertEqual((info[0].label, info[0].shader), ("Skin", "DzUberIrayMaterial"))
        self.assertIn("getNumMaterials", client.execute.call_args[0][0])

    def test_resolve_material_by_label(self):
        from dazpy._material import DazMaterial
        node, client = self._node({"status": "ok", "name": "1_SkinFace"})
        mat = node.resolve_material("Face")
        self.assertIsInstance(mat, DazMaterial)
        self.assertIn('findMaterial("1_SkinFace")', mat._locator)
        self.assertIn("if (lbl === _want)", client.execute.call_args[0][0])

    def test_resolve_material_missing_lists_available(self):
        node, _ = self._node({"status": "missing", "available": ["Skin", "Lips"]})
        with self.assertRaises(exceptions.MaterialError) as ctx:
            node.resolve_material("Hair")
        self.assertIn("Skin, Lips", str(ctx.exception))

    def test_resolve_material_no_shape(self):
        node, _ = self._node({"status": "no_shape"})
        with self.assertRaises(exceptions.MaterialError):
            node.resolve_material("Skin")

    def _material(self, value):
        from dazpy._material import DazMaterial
        client = mock_client(value)
        return DazMaterial(client, "MAT"), client

    def test_property_values(self):
        mat, client = self._material([{"name": "Diffuse Color", "label": "Base Color",
                                       "type": "color", "value": "#ff8040"}])
        props = mat.property_values()
        self.assertEqual((props[0].label, props[0].type, props[0].value),
                         ("Base Color", "color", "#ff8040"))
        script = client.execute.call_args[0][0]
        self.assertIn("getFloatColorValue", script)
        self.assertIn("DzImageProperty", script)

    def test_describe(self):
        mat, _ = self._material({"index": 2, "name": "Skin", "label": "Skin", "shader": "X"})
        self.assertEqual(mat.describe().index, 2)

    def test_set_property_value_color_and_numeric(self):
        mat, client = self._material({"status": "ok", "label": "Base Color", "type": "color",
                                      "value": "#3a6ea5"})
        w = mat.set_property_value("Diffuse Color", "#3A6EA5")
        self.assertEqual((w.type, w.value), ("color", "#3a6ea5"))
        script = client.execute.call_args[0][0]
        self.assertIn("findPropertyByLabel", script)
        self.assertIn("new QColor", script)
        mat, client = self._material({"status": "ok", "label": "Roughness", "type": "numeric",
                                      "value": 0.4})
        mat.set_property_value("Glossy Roughness", 0.4)

    def test_set_property_value_errors(self):
        mat, _ = self._material({"status": "missing"})
        with self.assertRaises(exceptions.MaterialError):
            mat.set_property_value("Nope", 1)
        mat, _ = self._material({"status": "unsupported", "label": "Base Color Map"})
        with self.assertRaises(exceptions.MaterialError):
            mat.set_property_value("Base Color Map", 1)
        mat, client = self._material(None)
        with self.assertRaises(ValueError):
            mat.set_property_value("Base Color", "#12")
        client.execute.assert_not_called()

    def test_copy_from(self):
        from dazpy._material import DazMaterial
        mat, client = self._material({"copied": 40, "skipped": 2})
        src = DazMaterial(client, "SRC")
        self.assertEqual(mat.copy_from(src), (40, 2))
        script = client.execute.call_args[0][0]
        self.assertIn("var _src = SRC", script)
        self.assertIn("var _dst = MAT", script)


class TestSurfacePreset(unittest.TestCase):
    def test_apply_surface_preset_selects_surfaces_and_preflights(self):
        client = mock_client({"status": "ok", "materials": [
            {"index": 0, "name": "Skin", "label": "Skin", "shader": "DzUberIrayMaterial"}]})
        node = DazNode(client, NodeIdentifier("9", kind="element_id"))
        mats = node.apply_surface_preset("C:/p.duf", map_paths=["/Runtime/Textures/a.jpg"])
        self.assertEqual(mats[0].shader, "DzUberIrayMaterial")
        script = client.execute.call_args[0][0]
        self.assertIn("getMaterial(s).select(true)", script)
        self.assertIn("DzFileIOSettings", script)
        self.assertIn('"/Runtime/Textures/a.jpg"', script)
        self.assertIn("var _allowMissing = false", script)
        self.assertLess(script.index("_missing.length"), script.index("openFile("))

    def test_apply_surface_preset_missing_maps(self):
        client = mock_client({"status": "missing_maps", "missing": ["a.jpg"]})
        with self.assertRaises(exceptions.MaterialError) as ctx:
            DazNode(client, NodeIdentifier("9", kind="element_id")).apply_surface_preset("C:/p.duf")
        self.assertIn("a.jpg", str(ctx.exception))

    def test_apply_surface_preset_open_failed(self):
        client = mock_client({"status": "open_failed"})
        with self.assertRaises(exceptions.MaterialError):
            DazNode(client, NodeIdentifier("9", kind="element_id")).apply_surface_preset("C:/p.duf")

    def test_content_path(self):
        client = mock_client("D:/Lib/Shader Presets/x.duf")
        self.assertEqual(DazScene(client).content_path("Shader Presets/x.duf"),
                         "D:/Lib/Shader Presets/x.duf")
        self.assertIn("getAbsolutePath", client.execute.call_args[0][0])
        self.assertIsNone(DazScene(mock_client("")).content_path("nope.duf"))


class TestDazMaterialScriptGeneration(unittest.TestCase):
    def _make_material(self, return_value=None):
        from dazpy._material import DazMaterial
        client = mock_client(return_value)
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
        client = mock_client(["Skin", "Eyes", "Teeth"])
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mats = node.materials()
        self.assertEqual(len(mats), 3)
        for m in mats:
            self.assertIsInstance(m, DazMaterial)

    def test_materials_script_uses_getNumMaterials(self):
        client = mock_client([])
        node = DazNode(client, NodeIdentifier("Genesis9"))
        node.materials()
        script = client.execute.call_args[0][0]
        self.assertIn("getNumMaterials", script)
        self.assertIn("getCurrentShape", script)
        self.assertIn("getObject", script)

    def test_materials_empty_when_no_object(self):
        client = mock_client([])
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mats = node.materials()
        self.assertEqual(mats, [])

    def test_find_material_returns_daz_material(self):
        from dazpy._material import DazMaterial
        client = mock_client("Skin")
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mat = node.find_material("Skin")
        self.assertIsInstance(mat, DazMaterial)

    def test_find_material_returns_none_when_not_found(self):
        client = mock_client(None)
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mat = node.find_material("NonExistent")
        self.assertIsNone(mat)

    def test_find_material_script_uses_findMaterial(self):
        client = mock_client(None)
        node = DazNode(client, NodeIdentifier("Genesis9"))
        node.find_material("Skin")
        script = client.execute.call_args[0][0]
        self.assertIn("findMaterial", script)
        self.assertIn("Skin", script)

    def test_material_locator_uses_findMaterial(self):
        client = mock_client(None)
        node = DazNode(client, NodeIdentifier("Genesis9"))
        loc = node._material_locator("Skin")
        self.assertIn("findMaterial", loc)
        self.assertIn("Skin", loc)
        self.assertIn("getCurrentShape", loc)
        self.assertIn("getObject", loc)


class TestIrayMaterial(unittest.TestCase):
    def test_is_frozen(self):
        from dazpy.materials import IrayMaterial
        spec = IrayMaterial(base_color=(255, 0, 0))
        with self.assertRaises(Exception):
            spec.base_color = (0, 255, 0)

    def test_texture_map_is_frozen(self):
        from dazpy.materials import TextureMap
        tex = TextureMap(channel="base_color", file_path="/tmp/x.png")
        with self.assertRaises(Exception):
            tex.file_path = "/tmp/y.png"

    def test_surface_property_is_frozen(self):
        from dazpy.materials import SurfaceProperty
        prop = SurfaceProperty(label="Base Color", value=1.0)
        with self.assertRaises(Exception):
            prop.value = 2.0


class TestApplyTextureMap(unittest.TestCase):
    def test_raises_file_not_found_before_any_client_call(self):
        from dazpy._material import DazMaterial
        from dazpy.materials import TextureMap, apply_texture_map
        import tempfile
        client = mock_client(None)
        material = DazMaterial(client, "_mat")
        missing_path = os.path.join(tempfile.gettempdir(), "definitely_not_a_real_texture.png")
        self.assertFalse(os.path.isfile(missing_path))
        texture = TextureMap(channel="base_color", file_path=missing_path)
        with self.assertRaises(FileNotFoundError):
            apply_texture_map(material, texture)
        client.execute.assert_not_called()

    def test_raises_value_error_on_relative_path_before_any_client_call(self):
        from dazpy._material import DazMaterial
        from dazpy.materials import TextureMap, apply_texture_map
        client = mock_client(None)
        material = DazMaterial(client, "_mat")
        texture = TextureMap(channel="base_color", file_path="relative/texture.png")
        with self.assertRaises(ValueError):
            apply_texture_map(material, texture)
        client.execute.assert_not_called()

    def test_happy_path_calls_set_map_on_resolved_channel_label(self):
        from dazpy._material import DazMaterial
        from dazpy.materials import TextureMap, apply_texture_map
        import tempfile
        client = mock_client({"success": True})
        material = DazMaterial(client, "_mat")
        with tempfile.NamedTemporaryFile(suffix=".png") as f:
            texture = TextureMap(channel="normal", file_path=f.name)
            apply_texture_map(material, texture)
        script = client.execute.call_args.args[0]
        self.assertIn("Normal Map", script)
        self.assertIn("setMap", script)

    def test_raises_material_error_when_property_not_found(self):
        from dazpy._material import DazMaterial
        from dazpy.materials import TextureMap, apply_texture_map
        from dazpy.exceptions import MaterialError
        import tempfile
        client = mock_client({"error": "property_not_found"})
        material = DazMaterial(client, "_mat")
        with tempfile.NamedTemporaryFile(suffix=".png") as f:
            texture = TextureMap(channel="base_color", file_path=f.name)
            with self.assertRaises(MaterialError):
                apply_texture_map(material, texture)


class TestSurfaceProperty(unittest.TestCase):
    def test_get_surface_property_returns_value(self):
        from dazpy._material import DazMaterial
        from dazpy.materials import get_surface_property
        client = mock_client({"success": True, "value": 0.5})
        material = DazMaterial(client, "_mat")
        result = get_surface_property(material, "Glossy Anisotropy")
        self.assertEqual(result, 0.5)
        script = client.execute.call_args.args[0]
        self.assertIn("Glossy Anisotropy", script)
        self.assertIn("getValue", script)

    def test_get_surface_property_raises_material_error_when_not_found(self):
        from dazpy._material import DazMaterial
        from dazpy.materials import get_surface_property
        from dazpy.exceptions import MaterialError
        client = mock_client({"error": "property_not_found"})
        material = DazMaterial(client, "_mat")
        with self.assertRaises(MaterialError):
            get_surface_property(material, "Nonexistent Channel")

    def test_set_surface_property_calls_set_value(self):
        from dazpy._material import DazMaterial
        from dazpy.materials import SurfaceProperty, set_surface_property
        client = mock_client({"success": True})
        material = DazMaterial(client, "_mat")
        set_surface_property(material, SurfaceProperty(label="Top Coat Weight", value=0.25))
        script = client.execute.call_args.args[0]
        self.assertIn("Top Coat Weight", script)
        self.assertIn("setValue", script)
        self.assertIn("0.25", script)

    def test_set_surface_property_raises_material_error_on_failure(self):
        from dazpy._material import DazMaterial
        from dazpy.materials import SurfaceProperty, set_surface_property
        from dazpy.exceptions import MaterialError
        client = mock_client({"error": "material_not_found"})
        material = DazMaterial(client, "_mat")
        with self.assertRaises(MaterialError):
            set_surface_property(material, SurfaceProperty(label="Base Color", value=(255, 0, 0)))


class TestApplyIrayMaterial(unittest.TestCase):
    def test_raises_file_not_found_before_any_client_call(self):
        from dazpy._material import DazMaterial
        from dazpy.materials import IrayMaterial, TextureMap, apply_iray_material
        import tempfile
        client = mock_client({"success": True})
        material = DazMaterial(client, "_mat")
        missing_path = os.path.join(tempfile.gettempdir(), "definitely_not_a_real_texture2.png")
        self.assertFalse(os.path.isfile(missing_path))
        spec = IrayMaterial(
            base_color=(255, 0, 0),
            textures=(TextureMap(channel="base_color", file_path=missing_path),),
        )
        with self.assertRaises(FileNotFoundError):
            apply_iray_material(material, spec)
        client.execute.assert_not_called()

    def test_skips_none_typed_fields(self):
        from dazpy._material import DazMaterial
        from dazpy.materials import IrayMaterial, apply_iray_material
        client = mock_client({"success": True})
        material = DazMaterial(client, "_mat")
        spec = IrayMaterial(roughness=0.5)
        apply_iray_material(material, spec)
        scripts = [call.args[0] for call in client.execute.call_args_list]
        self.assertEqual(len(scripts), 1)
        self.assertIn("Glossy Roughness", scripts[0])
        self.assertIn("0.5", scripts[0])

    def test_applies_typed_fields_then_textures_then_properties_in_order(self):
        from dazpy._material import DazMaterial
        from dazpy.materials import (
            IrayMaterial, TextureMap, SurfaceProperty, apply_iray_material,
        )
        import tempfile
        client = mock_client({"success": True})
        material = DazMaterial(client, "_mat")
        with tempfile.NamedTemporaryFile(suffix=".png") as f:
            spec = IrayMaterial(
                base_color=(200, 200, 200),
                roughness=0.4,
                textures=(TextureMap(channel="normal", file_path=f.name),),
                properties=(SurfaceProperty(label="Base Color", value=(10, 10, 10)),),
            )
            apply_iray_material(material, spec)
            scripts = [call.args[0] for call in client.execute.call_args_list]
        self.assertEqual(len(scripts), 4)
        self.assertIn("Base Color", scripts[0])
        self.assertIn("Glossy Roughness", scripts[1])
        self.assertIn("Normal Map", scripts[2])
        self.assertIn("setMap", scripts[2])
        self.assertIn("Base Color", scripts[3])
        self.assertIn("10", scripts[3])

    def test_raises_material_error_when_channel_property_not_found(self):
        from dazpy._material import DazMaterial
        from dazpy.materials import IrayMaterial, apply_iray_material
        from dazpy.exceptions import MaterialError
        client = mock_client({"error": "property_not_found"})
        material = DazMaterial(client, "_mat")
        spec = IrayMaterial(metallic_weight=0.8)
        with self.assertRaises(MaterialError):
            apply_iray_material(material, spec)


class TestMaterialsExports(unittest.TestCase):
    def test_materials_symbols_importable_from_top_level_package(self):
        import dazpy
        self.assertTrue(hasattr(dazpy, "IrayMaterial"))
        self.assertTrue(hasattr(dazpy, "TextureMap"))
        self.assertTrue(hasattr(dazpy, "SurfaceProperty"))
        self.assertTrue(hasattr(dazpy, "apply_iray_material"))
        self.assertTrue(hasattr(dazpy, "apply_texture_map"))
        self.assertTrue(hasattr(dazpy, "get_surface_property"))
        self.assertTrue(hasattr(dazpy, "set_surface_property"))
        self.assertTrue(hasattr(dazpy, "MaterialError"))
        self.assertIn("IrayMaterial", dazpy.__all__)
        self.assertIn("TextureMap", dazpy.__all__)
        self.assertIn("SurfaceProperty", dazpy.__all__)
        self.assertIn("apply_iray_material", dazpy.__all__)
        self.assertIn("apply_texture_map", dazpy.__all__)
        self.assertIn("get_surface_property", dazpy.__all__)
        self.assertIn("set_surface_property", dazpy.__all__)
        self.assertIn("MaterialError", dazpy.__all__)


if __name__ == "__main__":
    unittest.main()
