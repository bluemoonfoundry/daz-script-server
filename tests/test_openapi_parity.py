"""
Route ↔ openapi.yaml parity (daz-script-server-5d6f.6).

Runs scripts/check_openapi_parity.py against the real tree, then against
mutated copies of the route table / spec to prove each kind of drift fails.
No running server needed (part of `python tests.py unit`).
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "check_openapi_parity", ROOT / "scripts" / "check_openapi_parity.py")
parity = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(parity)

# A synthetic companion plugin, so these tests don't depend on which real
# plugins companion_plugins.json currently declares.
DEMO_PLUGIN = "demo-plugin"
DEMO_ROUTES = {("POST", "/demo"), ("GET", "/demo/:id")}
DEMO_YAML = """
  /demo:
    post:
      tags: [CompanionPlugins]
      summary: Demo plugin submit
      responses:
        '200':
          description: OK
  /demo/{id}:
    get:
      tags: [CompanionPlugins]
      summary: Demo plugin status
      responses:
        '200':
          description: OK
"""


def with_demo_paths(yaml: str) -> str:
    """openapi.yaml text with the demo plugin's two operations added."""
    i = yaml.index("\ncomponents:")
    return yaml[:i] + "\n" + DEMO_YAML.strip("\n") + yaml[i:]


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
        self.cpp = (ROOT / "src" / "PaneRoutes.cpp").read_text(encoding="utf-8")
        self.yaml = (ROOT / "openapi.yaml").read_text(encoding="utf-8")

    def _run(self, cpp=None, yaml=None, plugin_src=None):
        cpp_path = Path(self.tmp.name) / "routes.cpp"
        yaml_path = Path(self.tmp.name) / "openapi.yaml"
        cpp_path.write_text(cpp if cpp is not None else self.cpp, encoding="utf-8")
        yaml_path.write_text(yaml if yaml is not None else self.yaml, encoding="utf-8")
        with mock.patch.object(parity, "ROUTES_CPP", cpp_path), \
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

    def _run_demo(self, yaml=None, plugin_src=None):
        with mock.patch.dict(parity.COMPANION_PLUGIN_ROUTES, {DEMO_PLUGIN: set(DEMO_ROUTES)}):
            return self._run(yaml=yaml if yaml is not None else with_demo_paths(self.yaml),
                             plugin_src=plugin_src)

    def test_declared_and_documented_plugin_passes(self):
        self.assertEqual(self._run_demo(), "")

    def test_missing_plugin_route_fails(self):
        yaml = with_demo_paths(self.yaml)
        start = yaml.index("  /demo/{id}:")
        end = yaml.index("\ncomponents:", start)
        out = self._run_demo(yaml=yaml[:start] + yaml[end:])
        self.assertIn("companion-plugin routes missing from openapi.yaml", out)

    def test_plugin_route_without_tag_fails(self):
        yaml = with_demo_paths(self.yaml).replace("tags: [CompanionPlugins]", "tags: [Scene]")
        self.assertIn("documented without tag", self._run_demo(yaml=yaml))

    def test_documented_plugin_route_nobody_declares_fails(self):
        out = self._run(yaml=with_demo_paths(self.yaml))
        self.assertIn("operations no known plugin registers", out)

    def test_plugin_source_drift_fails(self):
        src = Path(self.tmp.name) / "plugin"
        src.mkdir()
        (src / "Server.cpp").write_text(
            'QString m = "POST", p = "/demo", s = "a";\n'
            'QString g = "GET",  q = "/demo/:id/extra", t = "b";\n'
            'invokeMethod(pane, "registerPluginRoute");\n', encoding="utf-8")
        out = self._run_demo(plugin_src={DEMO_PLUGIN: src})
        self.assertIn("out of date", out)

    def test_plugin_source_match_passes(self):
        src = Path(self.tmp.name) / "plugin"
        src.mkdir()
        (src / "Server.cpp").write_text(
            'QString mPost = "POST",  pPost = "/demo",      sPost = "h1";\n'
            'QString mGet  = "GET",   pGet  = "/demo/:id",  sGet  = "h2";\n'
            'invokeMethod(pane, "registerPluginRoute");\n', encoding="utf-8")
        self.assertEqual(self._run_demo(plugin_src={DEMO_PLUGIN: src}), "")

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

    # ── W38 (yau7.7.5): registrations the literal regex can't read ──

    def test_non_literal_route_registration_fails(self):
        cpp = self.cpp.replace(
            'm_pServer->Get("/capabilities"',
            'm_pServer->Get(kNewPath, nullptr);\n\tm_pServer->Get("/capabilities"', 1)
        out = self._run(cpp=cpp)
        self.assertIn("route registrations the parity check can't read", out)
        self.assertIn("kNewPath", out)

    def test_registration_through_alias_pointer_fails(self):
        cpp = self.cpp.replace(
            'm_pServer->Get("/capabilities"',
            'srv->Post("/aliased", nullptr);\n\tm_pServer->Get("/capabilities"', 1)
        self.assertIn("POST /aliased", self._run(cpp=cpp))

    def test_duplicate_route_registration_fails(self):
        cpp = self.cpp.replace(
            'm_pServer->Get("/capabilities"',
            'm_pServer->Get("/capabilities", nullptr);\n\tm_pServer->Get("/capabilities"', 1)
        out = self._run(cpp=cpp)
        self.assertIn("registered more than once", out)
        self.assertIn("GET /capabilities", out)

    def test_sdk_call_with_unlisted_prefix_is_seen(self):
        src = Path(self.tmp.name) / "sdk"
        src.mkdir()
        (src / "c.py").write_text('self._post("/brand-new/thing", {})\n'
                                  'url = f"{self._base}/other/{rid}/events"\n', encoding="utf-8")
        with mock.patch.object(parity, "ROOT", Path(self.tmp.name)):
            calls = parity.sdk_calls(src, "*.py", parity.DAZPY_CALL_RE, parity.DAZPY_SSE_RE)
        self.assertIn(("POST", "/brand-new/thing"), calls)
        self.assertIn(("GET", "/other/{}/events"), calls)


class TestMainLiveFailure(unittest.TestCase):
    """W37 (yau7.7.4): a failed --live fetch must not hide static results."""

    def test_static_errors_and_report_survive_live_failure(self):
        import contextlib
        import io
        import urllib.error
        with tempfile.TemporaryDirectory() as d:
            report = Path(d) / "cov.md"
            err = io.StringIO()
            with mock.patch.object(parity, "check",
                                   return_value=(["static drift here"], {}, {"dazpy": {}})), \
                 mock.patch.object(parity, "fetch_capabilities",
                                   side_effect=urllib.error.URLError("refused")), \
                 contextlib.redirect_stderr(err):
                rc = parity.main(["--live", "http://127.0.0.1:1",
                                  "--sdk-report", str(report)])
            self.assertEqual(rc, 2)
            self.assertTrue(report.exists())
            self.assertIn("static drift here", err.getvalue())
            self.assertIn("--live", err.getvalue())



class TestCompanionRegistry(unittest.TestCase):
    """companion_plugins.json loading and the --live /capabilities comparison."""

    def setUp(self):
        yaml_path = Path(tempfile.mkdtemp()) / "openapi.yaml"
        self.addCleanup(lambda: yaml_path.unlink(missing_ok=True))
        yaml_path.write_text(with_demo_paths((ROOT / "openapi.yaml").read_text(encoding="utf-8")),
                             encoding="utf-8")
        self.ops = parity.openapi_operations(yaml_path.read_text(encoding="utf-8"))
        patcher = mock.patch.dict(parity.COMPANION_PLUGIN_ROUTES,
                                  {DEMO_PLUGIN: set(DEMO_ROUTES)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_registry_file_loads(self):
        reg = parity.load_companion_registry()
        self.assertIsInstance(reg, dict)

    def test_registry_routes_parsed(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "c.json"
            f.write_text('{"plugins":[{"name":"a","routes":[{"method":"get","path":"/a/:id"}]}]}',
                         encoding="utf-8")
            self.assertEqual(parity.load_companion_registry(f), {"a": {("GET", "/a/:id")}})

    def test_duplicate_plugin_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "c.json"
            f.write_text('{"plugins":[{"name":"a","routes":[]},{"name":"a","routes":[]}]}',
                         encoding="utf-8")
            with self.assertRaises(ValueError):
                parity.load_companion_registry(f)

    @staticmethod
    def _caps(*plugins):
        return {"companion_plugins": list(plugins)}

    @staticmethod
    def _plugin(name=DEMO_PLUGIN, registered=True, version="0.2.0", routes=None):
        routes = routes if routes is not None else [
            {"method": "POST", "path": "/demo", "auth": True},
            {"method": "GET", "path": "/demo/:id", "auth": True}]
        return {"name": name, "registered": registered, "version": version, "routes": routes}

    def test_matching_live_plugin_passes(self):
        errors, notes = parity.check_live(self._caps(self._plugin()), self.ops)
        self.assertEqual(errors, [])
        self.assertEqual(notes, [])

    def test_undeclared_live_plugin_fails(self):
        live = self._plugin(name="mystery", routes=[])
        errors, _ = parity.check_live(self._caps(self._plugin(), live), self.ops)
        self.assertTrue(any("'mystery'" in e and "not declared" in e for e in errors), errors)

    def test_live_route_drift_fails(self):
        live = self._plugin(routes=[{"method": "POST", "path": "/demo"}])
        errors, _ = parity.check_live(self._caps(live), self.ops)
        self.assertTrue(any("differ from companion_plugins.json" in e for e in errors), errors)

    def test_undocumented_live_route_fails(self):
        with mock.patch.dict(parity.COMPANION_PLUGIN_ROUTES,
                             {"x": {("GET", "/x/nope")}}):
            live = self._plugin(name="x", routes=[{"method": "GET", "path": "/x/nope"}])
            errors, _ = parity.check_live(self._caps(live), self.ops)
        self.assertTrue(any("missing from openapi.yaml" in e for e in errors), errors)

    def test_unattributed_declared_routes_are_a_note(self):
        live = self._plugin(name="DemoServer", registered=False, version=None)
        errors, notes = parity.check_live(self._caps(live), self.ops)
        self.assertEqual(errors, [])
        self.assertTrue(any("without a plugin name" in n for n in notes), notes)
        self.assertTrue(any("not loaded" in n for n in notes), notes)

    def test_old_server_without_registry_fails(self):
        errors, _ = parity.check_live({"plugin_routes": []}, self.ops)
        self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
