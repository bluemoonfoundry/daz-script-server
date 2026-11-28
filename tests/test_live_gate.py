"""tests/live_gate.py: live test files are opt-in and never clear a user's scene."""
import ast
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import importlib.util  # noqa: E402

import live_gate  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location("_tests_runner_gate", REPO / "tests.py")
_runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_runner)
LIVE_TEST_FILES = _runner.LIVE_TEST_FILES


def _calls_require_live(stmt) -> bool:
    return any(isinstance(n, ast.Call) and getattr(n.func, "id", None) == "require_live"
               for n in ast.walk(stmt))


def _gate_comes_first(body) -> bool:
    for stmt in body:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue  # docstring
        if isinstance(stmt, ast.ImportFrom) and stmt.module in ("__future__", "live_gate"):
            continue
        if isinstance(stmt, ast.Import) and all(a.name in ("os", "sys") for a in stmt.names):
            continue
        if isinstance(stmt, ast.Expr) and "path.insert" in ast.unparse(stmt):
            continue
        return _calls_require_live(stmt)
    return False


class _Result:
    def __init__(self, value):
        self.value = value


class FakeClient:
    def __init__(self, roots):
        self.roots = roots
        self.scripts = []

    def execute(self, script):
        self.scripts.append(script)
        if "Scene.clear()" in script:
            self.roots = []
            return _Result(True)
        return _Result(list(self.roots))


def _env(**overrides):
    env = {k: v for k, v in os.environ.items()
           if k not in (live_gate.LIVE_ENV, live_gate.ALLOW_CLEAR_ENV)}
    env.update(overrides)
    return env


class RequireLiveTests(unittest.TestCase):
    def test_skips_without_opt_in(self):
        with mock.patch.dict(os.environ, _env(), clear=True):
            with self.assertRaises(unittest.SkipTest) as cm:
                live_gate.require_live()
        self.assertIn("DAZ_LIVE_TESTS=1", str(cm.exception))

    def test_other_values_are_not_an_opt_in(self):
        for value in ("", "0", "true", "yes"):
            with mock.patch.dict(os.environ, _env(DAZ_LIVE_TESTS=value), clear=True):
                with self.assertRaises(unittest.SkipTest):
                    live_gate.require_live()

    def test_running_the_file_directly_is_an_opt_in(self):
        with mock.patch.dict(os.environ, _env(), clear=True):
            live_gate.require_live("__main__")
            with self.assertRaises(unittest.SkipTest):
                live_gate.require_live("tests.test_api")

    def test_passes_with_opt_in(self):
        with mock.patch.dict(os.environ, _env(DAZ_LIVE_TESTS="1"), clear=True):
            live_gate.require_live()


class ClearSceneTests(unittest.TestCase):
    def setUp(self):
        live_gate._reset_for_tests()
        self.addCleanup(live_gate._reset_for_tests)

    def _clears(self, client):
        return sum("Scene.clear()" in s for s in client.scripts)

    def test_refuses_a_scene_with_content(self):
        client = FakeClient(["Jerry", "Camera 1"])
        with mock.patch.dict(os.environ, _env(), clear=True):
            with self.assertRaises(unittest.SkipTest) as cm:
                live_gate.clear_scene(client)
        self.assertEqual(self._clears(client), 0)
        self.assertIn("Jerry", str(cm.exception))
        self.assertIn("DAZ_LIVE_ALLOW_CLEAR=1", str(cm.exception))
        self.assertFalse(live_gate.scene_owned())

    def test_refusal_repeats_so_teardown_cannot_clear(self):
        client = FakeClient(["Jerry"])
        with mock.patch.dict(os.environ, _env(), clear=True):
            for _ in range(2):
                with self.assertRaises(unittest.SkipTest):
                    live_gate.clear_scene(client)
        self.assertEqual(self._clears(client), 0)

    def test_clears_an_empty_scene_then_owns_it(self):
        client = FakeClient([])
        with mock.patch.dict(os.environ, _env(), clear=True):
            live_gate.clear_scene(client)
            self.assertTrue(live_gate.scene_owned())
            client.roots = ["recipe:main.key"]  # the tests' own content
            live_gate.clear_scene(client)
        self.assertEqual(self._clears(client), 2)

    def test_allow_clear_overrides(self):
        client = FakeClient(["Jerry"])
        with mock.patch.dict(os.environ, _env(DAZ_LIVE_ALLOW_CLEAR="1"), clear=True):
            live_gate.clear_scene(client)
        self.assertEqual(self._clears(client), 1)

    def test_query_skips_render_settings_nodes(self):
        self.assertIn("DzTonemapperNode", live_gate._COUNT_USER_ROOTS)
        self.assertIn("DzEnvironmentNode", live_gate._COUNT_USER_ROOTS)
        self.assertIn("getNodeParent", live_gate._COUNT_USER_ROOTS)


class LiveFilesAreGatedTests(unittest.TestCase):
    """Every live test file gates itself before it can contact Studio."""

    def test_every_live_file_calls_require_live_first(self):
        # The gate block (import os/sys, sys.path.insert, from live_gate import)
        # must be followed directly by the require_live() call, before any
        # other statement can import a client or probe Studio.
        for name in sorted(LIVE_TEST_FILES):
            tree = ast.parse((REPO / "tests" / name).read_text(encoding="utf-8"))
            with self.subTest(name):
                self.assertTrue(_gate_comes_first(tree.body), "require_live() is not first")

    def test_no_direct_scene_clear_in_live_files(self):
        for name in sorted(LIVE_TEST_FILES):
            text = (REPO / "tests" / name).read_text(encoding="utf-8")
            with self.subTest(name):
                self.assertNotIn("Scene.clear(); return", text,
                                 "clear through live_gate.clear_scene()")

    def test_importing_a_live_file_without_opt_in_skips_it(self):
        # In a subprocess, so nothing here can reach a running Studio.
        for name in ("test_recipe_live", "test_scene_check_live", "test_dazpy_integration"):
            with self.subTest(name):
                proc = subprocess.run(
                    [sys.executable, "-c",
                     f"import unittest\ntry:\n    import tests.{name}\n"
                     f"except unittest.SkipTest:\n    print('SKIPPED')\n"],
                    cwd=REPO, env=_env(), capture_output=True, text=True, timeout=60,
                )
                self.assertEqual(proc.stdout.strip(), "SKIPPED", proc.stderr)


if __name__ == "__main__":
    unittest.main()
