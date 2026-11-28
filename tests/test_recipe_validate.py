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


SCHEMA_V2 = Path(__file__).parents[1] / "schemas" / "scene-recipe.v2.schema.json"
V2 = FIXTURES / "v2"
# Needs the content-type vocabulary, which the schema cannot express.
V2_VALIDATOR_ONLY = {"bad_type_name"}


def v2_invalid_cases():
    for case in sorted((V2 / "invalid").glob("*.json")):
        if not case.name.endswith(".expected.json"):
            yield case, json.loads(case.with_suffix(".expected.json").read_text())


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


class ValidateV2Tests(unittest.TestCase):
    def test_v2_invalid_corpus_reports_expected_path_and_code(self):
        for case, exp in v2_invalid_cases():
            with self.subTest(case.name):
                rep = validate_offline(json.loads(case.read_text()))
                self.assertFalse(rep.ok)
                self.assertIn((exp["path"], exp["code"]), [(e.path, e.code) for e in rep.errors])

    def test_v2_valid_corpus_passes(self):
        for case in (V2 / "valid").glob("*.json"):
            with self.subTest(case.name):
                rep = validate_offline(json.loads(case.read_text()))
                self.assertTrue(rep.ok, rep.errors)

    def test_v2_field_in_v1_rejected(self):
        rep = validate_offline({"recipe_version": 1, "id": "t", "assets": {"g": {"path": "/g.duf"}},
                                "actors": {"a": {"asset": "g", "node": "Abby"}}})
        self.assertIn(("actors.a.node", "unknown_field"), [(e.path, e.code) for e in rep.errors])

    def test_version_message_lists_both(self):
        rep = validate_offline({"recipe_version": 3, "id": "t"})
        self.assertEqual(rep.errors[0].allowed, ("1", "2"))
        self.assertIn("1", rep.errors[0].message)
        self.assertIn("2", rep.errors[0].message)

    def test_unknown_type_lists_friendly_names(self):
        rep = validate_offline(json.loads((V2 / "invalid/bad_type_name.json").read_text()))
        err = [e for e in rep.errors if e.code == "invalid_value"][0]
        self.assertIn("hair", err.allowed)
        self.assertEqual(err.suggestion, "hat")

    def test_raw_daz_type_accepted(self):
        rep = validate_offline({"recipe_version": 2, "id": "t", "actors": {"a": {
            "asset": "/a.duf", "wearing": [{"remove": {"type": "Follower/Wardrobe/Belt"}}]}}})
        self.assertTrue(rep.ok, rep.errors)

    def test_if_missing_allowed_values_per_op(self):
        def run(entry):
            return validate_offline({"recipe_version": 2, "id": "t", "actors": {"a": {
                "asset": "/a.duf", "wearing": [entry]}}})
        self.assertTrue(run({"replace": "J", "key": "j", "with": "/c.duf", "if_missing": "add"}).ok)
        self.assertTrue(run({"remove": "J", "if_missing": "ignore"}).ok)
        self.assertFalse(run({"remove": "J", "if_missing": "add"}).ok)
        self.assertFalse(run({"add": "/c.duf", "key": "j", "if_missing": "add"}).ok)

    def test_wearing_entry_needs_exactly_one_op(self):
        rep = validate_offline({"recipe_version": 2, "id": "t", "actors": {"a": {
            "asset": "/a.duf", "wearing": [{"add": "/c.duf", "remove": "J", "key": "k"}, {}]}}})
        codes = [(e.path, e.code) for e in rep.errors]
        self.assertIn(("actors.a.wearing[0]", "mutually_exclusive"), codes)
        self.assertIn(("actors.a.wearing[1]", "missing_field"), codes)

    def test_replace_needs_with_and_key_pattern(self):
        rep = validate_offline({"recipe_version": 2, "id": "t", "actors": {"a": {
            "asset": "/a.duf", "wearing": [{"replace": "J", "key": "bad key"}]}}})
        codes = [(e.path, e.code) for e in rep.errors]
        self.assertIn(("actors.a.wearing[0].with", "missing_field"), codes)
        self.assertIn(("actors.a.wearing[0].key", "invalid_id"), codes)

    def test_node_only_actor_is_valid(self):
        rep = validate_offline({"recipe_version": 2, "id": "t", "actors": {"a": {"node": "Abby"}}})
        self.assertTrue(rep.ok, rep.errors)

    def test_actor_asset_key_resolution_in_v2(self):
        base = {"recipe_version": 2, "id": "t", "assets": {"g": {"path": "/g.duf"}}}
        self.assertTrue(validate_offline({**base, "actors": {"a": {"asset": "g"}}}).ok)
        self.assertTrue(validate_offline({**base, "actors": {"a": {"asset": "/other.duf"}}}).ok)

    def test_v1_unknown_asset_key_still_unknown_reference(self):
        rep = validate_offline({"recipe_version": 1, "id": "t", "actors": {"a": {"asset": "/x.duf"}}})
        self.assertIn(("actors.a.asset", "invalid_id"), [(e.path, e.code) for e in rep.errors])
        rep = validate_offline({"recipe_version": 1, "id": "t", "actors": {"a": {"asset": "nope"}}})
        self.assertIn(("actors.a.asset", "unknown_reference"), [(e.path, e.code) for e in rep.errors])

    def test_v2_asset_ref_issues_have_paths(self):
        rep = validate_offline({"recipe_version": 2, "id": "t", "actors": {"a": {
            "asset": {"sku": ""}, "presets": ["ok", {"bogus": 1}]}}})
        codes = [(e.path, e.code) for e in rep.errors]
        self.assertIn(("actors.a.asset.sku", "invalid_type"), codes)
        self.assertIn(("actors.a.presets[1].bogus", "unknown_field"), codes)

    @unittest.skipUnless(HAVE_JSONSCHEMA, "jsonschema not installed")
    def test_v2_schema_agrees(self):
        validator = jsonschema.Draft202012Validator(json.loads(SCHEMA_V2.read_text()))
        for case in (V2 / "valid").glob("*.json"):
            with self.subTest(case.name):
                self.assertEqual(list(validator.iter_errors(json.loads(case.read_text()))), [])
        for case, exp in v2_invalid_cases():
            if exp["code"] in CROSS_REFERENCE_CODES or case.stem in V2_VALIDATOR_ONLY:
                continue
            with self.subTest(case.name):
                self.assertTrue(list(validator.iter_errors(json.loads(case.read_text()))),
                                "schema accepted a recipe the validator rejects")

    @unittest.skipUnless(HAVE_JSONSCHEMA, "jsonschema not installed")
    def test_v2_asset_ref_def_matches_standalone_schema(self):
        root = Path(__file__).parents[1]
        v2 = json.loads(SCHEMA_V2.read_text())
        standalone = json.loads((root / "schemas/asset-ref.v1.schema.json").read_text())
        for k in ("$id", "$schema", "title", "description"):
            standalone.pop(k, None)
        inline = dict(v2["$defs"]["assetRef"])
        inline.pop("description", None)
        self.assertEqual(inline, standalone)


if __name__ == "__main__":
    unittest.main()
