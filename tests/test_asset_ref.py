"""Unit tests for the shared asset reference schema and AssetRef."""

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from dazpy._asset_ref import AssetRef, ResolvedPin, parse_ref, ref_issues

try:
    import jsonschema
    HAVE_JSONSCHEMA = True
except ImportError:  # pragma: no cover
    HAVE_JSONSCHEMA = False

ROOT = Path(__file__).parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "asset_refs"
SCHEMA = ROOT / "schemas" / "asset-ref.v1.schema.json"
SCHEMA_COPY = ROOT / "dazpy" / "schemas" / "asset-ref.v1.schema.json"


class AssetRefTests(unittest.TestCase):
    def test_string_is_path_shorthand(self):
        ref = parse_ref("/People/x.duf")
        self.assertEqual(ref, AssetRef(path="/People/x.duf"))
        self.assertEqual(ref.kind, "path")
        self.assertEqual(ref.to_dict(), "/People/x.duf")

    def test_precedence(self):
        self.assertEqual(AssetRef(path="a", sku="1", find="f").kind, "path")
        self.assertEqual(AssetRef(sku="1", product="P").kind, "sku")
        self.assertEqual(AssetRef(product="P", find="f").kind, "product")
        self.assertEqual(AssetRef(find="f").kind, "find")

    def test_object_round_trip_with_pin(self):
        data = {"sku": "1", "file": "a.duf", "type": "hair",
                "resolved": {"path": "/a.duf", "sku": "1", "asset_id": "z"}}
        ref = parse_ref(data)
        self.assertEqual(ref.resolved, ResolvedPin(path="/a.duf", sku="1", asset_id="z"))
        self.assertEqual(ref.to_dict(), data)

    def test_resolved_only_is_invalid(self):
        self.assertEqual(ref_issues({"resolved": {"path": "a"}}, "x")[0].code, "invalid_asset_ref")

    def test_unknown_field_rejected(self):
        issues = ref_issues({"path": "a", "bogus": 1}, "x")
        self.assertEqual([(i.path, i.code) for i in issues], [("x.bogus", "unknown_field")])

    def test_unknown_field_suggestion(self):
        issue = ref_issues({"pth": "a", "path": "b"}, "x")[0]
        self.assertEqual(issue.suggestion, "path")
        self.assertIn("path", issue.allowed)

    def test_wrong_types(self):
        self.assertEqual(ref_issues(5, "x")[0].code, "invalid_type")
        self.assertEqual(ref_issues({"find": 5}, "x")[0].code, "invalid_type")
        self.assertEqual(ref_issues({"path": "a", "resolved": "r"}, "x")[0].code, "invalid_type")

    def test_valid_refs_have_no_issues(self):
        self.assertEqual(ref_issues("/a.duf", "x"), [])
        self.assertEqual(ref_issues({"sku": "1"}, "x"), [])

    @unittest.skipUnless(HAVE_JSONSCHEMA, "jsonschema not installed")
    def test_schema_matches_validator(self):
        schema = json.loads(SCHEMA.read_text())
        validator = jsonschema.Draft202012Validator(schema)
        for kind, expect in (("valid", True), ("invalid", False)):
            files = sorted((FIXTURES / kind).glob("*.json"))
            self.assertGreaterEqual(len(files), 3)
            for case in files:
                with self.subTest(f"{kind}/{case.name}"):
                    data = json.loads(case.read_text())
                    self.assertEqual(validator.is_valid(data), expect)
                    self.assertEqual(not ref_issues(data, "x"), expect)

    def test_schema_copies_identical(self):
        self.assertEqual(SCHEMA.read_bytes(), SCHEMA_COPY.read_bytes())


if __name__ == "__main__":
    unittest.main()
