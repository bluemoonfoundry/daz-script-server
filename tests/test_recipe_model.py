"""Unit tests for the scene-recipe schema file and SceneRecipe model."""

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from dazpy._asset_ref import AssetRef
from dazpy._recipe_model import SceneRecipe, TypeSelector, WearingEntry, actor_ref

FIXTURES = Path(__file__).parent / "fixtures" / "recipes"
SCHEMA = Path(__file__).parents[1] / "schemas" / "scene-recipe.v1.schema.json"


class SceneRecipeModelTests(unittest.TestCase):
    def test_schema_copies_are_identical(self):
        root = Path(__file__).parents[1]
        self.assertEqual((root / "schemas/scene-recipe.v1.schema.json").read_bytes(),
                         (root / "dazpy/schemas/scene-recipe.v1.schema.json").read_bytes())

    def test_round_trip_cafe_fixture(self):
        data = json.loads(FIXTURES.joinpath("valid/cafe.json").read_text())
        r = SceneRecipe.from_dict(data)
        self.assertEqual(r.cameras["anna_cu"].shot_type, "close_up")
        self.assertEqual(r.lights["practical"].color, (255, 200, 150))
        self.assertEqual(SceneRecipe.from_dict(r.to_dict()), r)

    def test_cafe_fields_parsed(self):
        r = SceneRecipe.from_json(FIXTURES.joinpath("valid/cafe.json").read_text())
        self.assertEqual(r.actors["anna"].facing, "ben")
        self.assertEqual(r.actors["ben"].rotation, (0.0, -90.0, 0.0))
        self.assertEqual(r.cameras["wide"].frame, ("anna", "ben"))
        self.assertEqual(r.cameras["manual"].look_at, (0.0, 120.0, 0.0))
        self.assertEqual(r.rigs["main"].key.intensity, 120)
        self.assertIsNone(r.rigs["main"].fill)
        self.assertEqual(r.environment.image_path, "C:/HDRI/cafe.hdr")
        self.assertEqual(r.shots[1].render.resolution, (1080, 1350))
        self.assertEqual(r.render.iray_samples, 200)

    def test_minimal_recipe_defaults_to_empty_sections(self):
        r = SceneRecipe.from_dict({"recipe_version": 1, "id": "m"})
        self.assertEqual((r.actors, r.shots, r.environment), ({}, (), None))

    def test_to_dict_output_is_json_and_schema_shaped(self):
        r = SceneRecipe.from_json(FIXTURES.joinpath("valid/cafe.json").read_text())
        d = r.to_dict()
        self.assertEqual(json.loads(json.dumps(d)), d)
        self.assertIn("rigs", d["lighting"])
        self.assertNotIn("lights", SceneRecipe.from_dict(
            {"recipe_version": 1, "id": "m"}).to_dict().get("lighting", {}))

    def test_fixtures_validate_against_schema(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        schema = json.loads(SCHEMA.read_text())
        for f in FIXTURES.joinpath("valid").glob("*.json"):
            jsonschema.validate(json.loads(f.read_text()), schema)
        r = SceneRecipe.from_json(FIXTURES.joinpath("valid/cafe.json").read_text())
        jsonschema.validate(r.to_dict(), schema)


class SceneRecipeV2ModelTests(unittest.TestCase):
    def test_v1_fixtures_unchanged(self):
        for f in sorted(FIXTURES.joinpath("valid").glob("*.json")):
            with self.subTest(f.name):
                d = json.loads(f.read_text())
                out = SceneRecipe.from_dict(d).to_dict()
                self.assertEqual(json.dumps(out, sort_keys=True),
                                 json.dumps(SceneRecipe.from_dict(out).to_dict(), sort_keys=True))
                for k, a in d.get("assets", {}).items():
                    self.assertEqual(out["assets"][k], a)
                for k, a in d.get("actors", {}).items():
                    self.assertIsInstance(out["actors"][k]["asset"], str)
                    self.assertEqual(SceneRecipe.from_dict(d).actors[k].asset, a["asset"])

    def test_v1_assets_stay_path_objects(self):
        d = {"recipe_version": 1, "id": "t", "assets": {"g": {"path": "/g.duf"}},
             "actors": {"a": {"asset": "g", "position": [1, 0, 0]}}}
        self.assertEqual(SceneRecipe.from_dict(d).to_dict(), d)

    def test_v2_abby_round_trip(self):
        d = json.loads(FIXTURES.joinpath("v2/valid/abby.json").read_text())
        self.assertEqual(SceneRecipe.from_dict(d).to_dict(), d)

    def test_wearing_parsed(self):
        r = SceneRecipe.from_json(FIXTURES.joinpath("v2/valid/abby.json").read_text())
        abby = r.actors["abby"]
        self.assertEqual(abby.wearing[0], WearingEntry(
            op="replace", key="hair", ref=AssetRef(find="Bunched Hair Updo"),
            target=TypeSelector("hair")))
        self.assertEqual(abby.wearing[1], WearingEntry(
            op="add", key="outfit", ref=AssetRef(find="Summer Outfit", type="wardrobe"),
            target=None))
        self.assertEqual(abby.wearing[2], WearingEntry(
            op="remove", key=None, ref=None, target=TypeSelector("hat"), if_missing="ignore"))
        self.assertEqual(r.actors["ben"].wearing[0].target, "Old Jacket")
        self.assertEqual(r.actors["ben"].wearing[0].if_missing, "add")
        self.assertEqual(abby.node, "Abby")
        self.assertEqual(abby.presets, (AssetRef(path="X:/Development/VisualNovelA/shapes/AbbyYoungShape.duf"),))

    def test_position_none_when_unset(self):
        r = SceneRecipe.from_dict({"recipe_version": 2, "id": "t", "actors": {"a": {"node": "A"}}})
        self.assertIsNone(r.actors["a"].position)
        self.assertNotIn("position", r.to_dict()["actors"]["a"])

    def test_actor_ref_resolves_indirection(self):
        r = SceneRecipe.from_json(FIXTURES.joinpath("v2/valid/abby.json").read_text())
        self.assertEqual(actor_ref(r, "abby"), AssetRef(product="Genesis 9 Female"))
        self.assertEqual(actor_ref(r, "ben"), AssetRef(product="Genesis 9 Female"))
        self.assertIsNone(actor_ref(SceneRecipe.from_dict(
            {"recipe_version": 2, "id": "t", "actors": {"a": {"node": "A"}}}), "a"))
        d = {"recipe_version": 2, "id": "t", "actors": {"a": {"asset": "/x.duf"}}}
        self.assertEqual(actor_ref(SceneRecipe.from_dict(d), "a"), AssetRef(path="/x.duf"))

    def test_v2_assets_accept_string_and_object(self):
        d = {"recipe_version": 2, "id": "t", "assets": {"a": "/a.duf", "b": {"sku": "1"}}}
        r = SceneRecipe.from_dict(d)
        self.assertEqual(r.assets["a"].ref, AssetRef(path="/a.duf"))
        self.assertEqual(r.to_dict(), d)

    def test_v2_schema_copies_are_identical(self):
        root = Path(__file__).parents[1]
        self.assertEqual((root / "schemas/scene-recipe.v2.schema.json").read_bytes(),
                         (root / "dazpy/schemas/scene-recipe.v2.schema.json").read_bytes())

    def test_recipe_schema_serves_v2(self):
        from dazpy.recipe import recipe_schema
        self.assertEqual(recipe_schema(2)["properties"]["recipe_version"], {"const": 2})


if __name__ == "__main__":
    unittest.main()
