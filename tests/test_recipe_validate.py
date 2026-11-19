"""Unit tests for offline scene-recipe validation."""

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from dazpy._recipe_model import SceneRecipe
from dazpy._recipe_validate import validate_offline
from dazpy.exceptions import DazError, RecipeValidationError

try:
    import jsonschema
    HAVE_JSONSCHEMA = True
except ImportError:  # pragma: no cover
    HAVE_JSONSCHEMA = False

FIXTURES = Path(__file__).parent / "fixtures" / "recipes"
VALID = FIXTURES / "valid"
INVALID = FIXTURES / "invalid"
SCHEMA = Path(__file__).parents[1] / "schemas" / "scene-recipe.v1.schema.json"
# Codes the JSON Schema cannot express (validator-only).
CROSS_REFERENCE_CODES = {"unknown_reference", "duplicate_shot_id", "duplicate_key",
                         "environment_requires_iray"}


def load_invalid(name):
    return json.loads((INVALID / f"{name}.json").read_text())


def invalid_cases():
    for case in sorted(INVALID.glob("*.json")):
        if not case.name.endswith(".expected.json"):
            yield case, json.loads(case.with_suffix(".expected.json").read_text())


class ValidateOfflineTests(unittest.TestCase):
    def test_invalid_corpus_reports_expected_path_and_code(self):
        for case, exp in invalid_cases():
            with self.subTest(case.name):
                rep = validate_offline(json.loads(case.read_text()))
                self.assertFalse(rep.ok)
                self.assertIn((exp["path"], exp["code"]), [(e.path, e.code) for e in rep.errors])

    def test_every_error_code_is_covered_by_corpus(self):
        codes = {exp["code"] for _, exp in invalid_cases()}
        self.assertEqual(codes, {
            "unsupported_version", "missing_field", "unknown_field", "unsupported_in_version",
            "invalid_type", "invalid_enum", "out_of_range", "invalid_id", "unknown_reference",
            "mutually_exclusive", "duplicate_shot_id", "duplicate_key", "environment_requires_iray"})

    def test_actor_and_prop_keys_share_one_namespace(self):
        rep = validate_offline(load_invalid("duplicate_key"))
        self.assertEqual([(e.path, e.code) for e in rep.errors], [("props.anna", "duplicate_key")])
        self.assertIn("actors.anna", rep.errors[0].message)

    def test_valid_corpus_passes(self):
        for case in VALID.glob("*.json"):
            with self.subTest(case.name):
                rep = validate_offline(json.loads(case.read_text()))
                self.assertTrue(rep.ok, rep.errors)

    @unittest.skipUnless(HAVE_JSONSCHEMA, "jsonschema not installed")
    def test_schema_agrees_with_validator_on_corpus(self):
        schema = json.loads(SCHEMA.read_text())
        validator = jsonschema.Draft202012Validator(schema)
        for case in VALID.glob("*.json"):
            with self.subTest(case.name):
                self.assertEqual(list(validator.iter_errors(json.loads(case.read_text()))), [])
        for case, exp in invalid_cases():
            if exp["code"] in CROSS_REFERENCE_CODES:
                continue
            with self.subTest(case.name):
                self.assertTrue(list(validator.iter_errors(json.loads(case.read_text()))),
                                "schema accepted a recipe the validator rejects")

    def test_typo_reference_suggests_closest_key(self):
        rep = validate_offline(load_invalid("facing_typo"))
        self.assertEqual(len(rep.errors), 1)
        self.assertEqual(rep.errors[0].suggestion, "ben")
        self.assertEqual(rep.errors[0].allowed, ("anna", "ben", "cafe"))

    def test_invalid_enum_lists_allowed_values(self):
        rep = validate_offline(load_invalid("invalid_enum"))
        self.assertEqual(rep.errors[0].allowed, ("close_up", "extreme_close_up", "extreme_wide", "full_body",
                                                 "medium", "medium_close_up", "medium_wide", "wide"))

    def test_collects_all_errors_in_one_pass(self):
        rep = validate_offline({"recipe_version": 1, "id": 3, "bogus": 1,
                                "cameras": {"c": {"frame": "a", "focal_length": -1}}})
        self.assertGreaterEqual({e.code for e in rep.errors},
                                {"invalid_type", "unknown_field", "out_of_range",
                                 "unknown_reference"})

    def test_unknown_field_suggests_closest_field(self):
        rep = validate_offline({"recipe_version": 1, "id": "t", "actors": {
            "a": {"asset": "x", "positon": [0, 0, 0]}}})
        err = [e for e in rep.errors if e.code == "unknown_field"][0]
        self.assertEqual((err.path, err.suggestion), ("actors.a.positon", "position"))

    def test_non_object_root(self):
        rep = validate_offline([])
        self.assertEqual([(e.path, e.code) for e in rep.errors], [("$", "invalid_type")])

    def test_bool_is_not_a_number(self):
        rep = validate_offline({"recipe_version": True, "id": "t"})
        self.assertEqual(rep.errors[0].code, "invalid_type")

    def test_from_dict_raises_with_report(self):
        with self.assertRaises(RecipeValidationError) as cm:
            SceneRecipe.from_dict({"recipe_version": 1})
        self.assertEqual(cm.exception.report.errors[0].code, "missing_field")
        self.assertIsInstance(cm.exception, DazError)
        self.assertIn("id", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
