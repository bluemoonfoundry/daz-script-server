"""
Route ↔ openapi.yaml parity (daz-script-server-5d6f.6).

Runs scripts/check_openapi_parity.py against the real tree, then against
mutated copies of the route table / spec to prove each kind of drift fails.
No running server needed (part of `python tests.py unit`).
"""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "check_openapi_parity", ROOT / "scripts" / "check_openapi_parity.py")
parity = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(parity)


class TestNormalize(unittest.TestCase):

    def test_param_spellings_collapse(self):
        for p in ("/requests/([^/]+)/status", "/requests/{id}/status",
                  "/requests/:id/status", "/requests/{request_id}/status",
                  "/requests/${requestId}/status",
                  "/requests/${encodeURIComponent(requestId)}/status"):
            with self.subTest(path=p):
                self.assertEqual(parity.normalize(p), "/requests/{}/status")

    def test_query_string_dropped(self):
        self.assertEqual(parity.normalize("/requests?status=queued"), "/requests")


class TestParity(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cpp = (ROOT / "src" / "DzScriptServerPane.cpp").read_text(encoding="utf-8")
        self.yaml = (ROOT / "openapi.yaml").read_text(encoding="utf-8")

    def _run(self, cpp=None, yaml=None, plugin_src=None):
        cpp_path = Path(self.tmp.name) / "pane.cpp"
        yaml_path = Path(self.tmp.name) / "openapi.yaml"
        cpp_path.write_text(cpp if cpp is not None else self.cpp, encoding="utf-8")
        yaml_path.write_text(yaml if yaml is not None else self.yaml, encoding="utf-8")
        with mock.patch.object(parity, "PANE_CPP", cpp_path), \
             mock.patch.object(parity, "OPENAPI", yaml_path):
            errors, _, _ = parity.check(plugin_src or {})
        return "\n".join(errors)

    def test_real_tree_is_in_parity(self):
        self.assertEqual(self._run(), "")

    def test_undocumented_server_route_fails(self):
        cpp = self.cpp.replace(
            'm_pServer->Get("/capabilities"',
            'm_pServer->Get("/brand-new", nullptr);\n\tm_pServer->Get("/capabilities"', 1)
        self.assertIn("GET /brand-new", self._run(cpp=cpp))
        self.assertIn("missing from openapi.yaml", self._run(cpp=cpp))

    def test_documented_but_unregistered_route_fails(self):
        cpp = self.cpp.replace('m_pServer->Post("/geometry/frames"', 'm_pServer->Post("/geometry/gone"', 1)
        out = self._run(cpp=cpp)
        self.assertIn("not registered in setupRoutes()", out)
        self.assertIn("POST /geometry/frames", out)

    def test_wrong_method_fails(self):
        yaml = self.yaml.replace("  /geometry/frames:\n    post:", "  /geometry/frames:\n    put:", 1)
        self.assertNotEqual(yaml, self.yaml)
        out = self._run(yaml=yaml)
        self.assertIn("POST /geometry/frames", out)
        self.assertIn("PUT /geometry/frames", out)

    def test_missing_plugin_route_fails(self):
        start = self.yaml.index("  /export/usd/{id}:")
        end = self.yaml.index("\ncomponents:", start)
        out = self._run(yaml=self.yaml[:start] + self.yaml[end:])
        self.assertIn("companion-plugin routes missing from openapi.yaml", out)

    def test_plugin_route_without_tag_fails(self):
        yaml = self.yaml.replace("tags: [CompanionPlugins]", "tags: [Scene]")
        self.assertIn("documented without tag", self._run(yaml=yaml))

    def test_plugin_source_drift_fails(self):
        src = Path(self.tmp.name) / "plugin"
        src.mkdir()
        (src / "Server.cpp").write_text(
            'QString m = "POST", p = "/export/usd", s = "a";\n'
            'QString g = "GET",  q = "/export/usd/:id/extra", t = "b";\n'
            'invokeMethod(pane, "registerPluginRoute");\n', encoding="utf-8")
        out = self._run(plugin_src={"daz-bridge-usd": src})
        self.assertIn("out of date", out)

    def test_plugin_source_match_passes(self):
        src = Path(self.tmp.name) / "plugin"
        src.mkdir()
        (src / "Server.cpp").write_text(
            'QString mPost = "POST",  pPost = "/export/usd",      sPost = "h1";\n'
            'QString mGet  = "GET",   pGet  = "/export/usd/:id",  sGet  = "h2";\n'
            'invokeMethod(pane, "registerPluginRoute");\n', encoding="utf-8")
        self.assertEqual(self._run(plugin_src={"daz-bridge-usd": src}), "")

    def test_sdk_calling_undocumented_endpoint_fails(self):
        fake = {"dazpy": {("GET", "/scene/nope"): ["dazpy/_x.py:1"]}}
        with mock.patch.object(parity, "collect_sdks", return_value=fake):
            out = self._run()
        self.assertIn("dazpy calls endpoints missing from openapi.yaml", out)
        self.assertIn("dazpy/_x.py:1", out)

    def test_sdk_report_lists_every_operation(self):
        errors, ops, sdks = parity.check({})
        report = parity.sdk_report(ops, sdks)
        self.assertEqual(report.count("\n| `"), len(ops))
        self.assertIn("dazpy:", report)


if __name__ == "__main__":
    unittest.main()
