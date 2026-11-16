"""The shipped example recipe stays valid (offline, no Studio)."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dazpy._recipe_model import SceneRecipe
from dazpy.recipe import validate

EXAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "docs", "examples", "recipes", "g9-portrait.json")


class TestExampleRecipe(unittest.TestCase):
    def setUp(self):
        with open(EXAMPLE, encoding="utf-8") as f:
            self.data = json.load(f)

    def test_validates_offline(self):
        report = validate(self.data)
        self.assertTrue(report.ok, report.errors)
        self.assertEqual(report.warnings, ())

    def test_matches_documented_shape(self):
        r = SceneRecipe.from_dict(self.data)
        self.assertEqual(sorted(r.cameras), ["close_up", "full_body"])
        self.assertEqual([s.id for s in r.shots], ["full_body", "close_up"])
        self.assertIsNone(r.environment)


if __name__ == "__main__":
    unittest.main()
