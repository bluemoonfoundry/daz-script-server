"""Unit tests for the scene-recipe schema file and SceneRecipe model."""

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from dazpy._recipe_model import SceneRecipe

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


if __name__ == "__main__":
    unittest.main()
