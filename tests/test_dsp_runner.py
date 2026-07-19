"""
Unit tests for package_runner/dsp_runner.py (daz-script-server-5sw).

No DAZ Studio or server required -- exercises the harness directly (via its
run() function) and end-to-end as a real subprocess (matching exactly how
DzPackageImporter/PackageDependencyInstaller will invoke it: by direct file
path, never `-m package_runner.dsp_runner`).

Run standalone:  python tests/test_dsp_runner.py
Via runner:      python tests.py unit
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from package_runner import dsp_runner

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "dsp_runner")
DSP_RUNNER_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "package_runner", "dsp_runner.py"
)


def _write_inputs(tmp_dir, inputs):
    path = os.path.join(tmp_dir, "inputs.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(inputs, f)
    return path


class TestDspRunnerDirectCall(unittest.TestCase):
    """Exercises dsp_runner.run() directly -- fast, no subprocess."""

    def test_successful_run_returns_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            inputs_path = _write_inputs(tmp, {"name": "DazScript"})
            entry_path = os.path.join(FIXTURES_DIR, "hello_entry.py")

            envelope = dsp_runner.run(entry_path, inputs_path)

            self.assertEqual(envelope, {
                "success": True,
                "result": "Hello, DazScript!",
                "output": [],
                "error": "",
            })

    def test_print_output_is_captured_not_left_on_real_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            inputs_path = _write_inputs(tmp, {"value": 42})
            entry_path = os.path.join(FIXTURES_DIR, "noisy_entry.py")

            envelope = dsp_runner.run(entry_path, inputs_path)

            self.assertTrue(envelope["success"])
            self.assertEqual(envelope["result"], 42)
            self.assertEqual(envelope["output"], ["noisy: starting", "noisy: about to return 42"])

    def test_entry_point_exception_reports_failure_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            inputs_path = _write_inputs(tmp, {})
            entry_path = os.path.join(FIXTURES_DIR, "broken_entry.py")

            envelope = dsp_runner.run(entry_path, inputs_path)

            self.assertFalse(envelope["success"])
            self.assertIn("boom: this is a deliberate test failure", envelope["error"])

    def test_missing_run_function_reports_a_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            inputs_path = _write_inputs(tmp, {})
            entry_path = os.path.join(FIXTURES_DIR, "no_run_entry.py")

            envelope = dsp_runner.run(entry_path, inputs_path)

            self.assertFalse(envelope["success"])
            self.assertIn("does not define a run(inputs) function", envelope["error"])

    def test_non_json_serializable_result_reports_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            inputs_path = _write_inputs(tmp, {})
            entry_path = os.path.join(FIXTURES_DIR, "not_json_entry.py")

            envelope = dsp_runner.run(entry_path, inputs_path)

            self.assertFalse(envelope["success"])

    def test_missing_entry_point_reports_failure_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            inputs_path = _write_inputs(tmp, {})
            entry_path = os.path.join(FIXTURES_DIR, "does_not_exist.py")

            envelope = dsp_runner.run(entry_path, inputs_path)

            self.assertFalse(envelope["success"])
            self.assertIsNone(envelope["result"])


class TestDspRunnerAsSubprocess(unittest.TestCase):
    """End-to-end: invokes dsp_runner.py by direct file path, exactly how
    PackageDependencyInstaller/DzPackageImporter will spawn it from C++."""

    def test_direct_file_path_invocation_matches_the_real_call_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            inputs_path = _write_inputs(tmp, {"name": "subprocess"})
            entry_path = os.path.join(FIXTURES_DIR, "hello_entry.py")

            completed = subprocess.run(
                [sys.executable, DSP_RUNNER_PATH, entry_path, inputs_path],
                capture_output=True, text=True, timeout=15,
            )

            self.assertEqual(completed.returncode, 0)
            envelope = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertEqual(envelope["success"], True)
            self.assertEqual(envelope["result"], "Hello, subprocess!")

    def test_wrong_argument_count_reports_failure_not_a_traceback(self):
        completed = subprocess.run(
            [sys.executable, DSP_RUNNER_PATH, "only-one-arg"],
            capture_output=True, text=True, timeout=15,
        )

        self.assertEqual(completed.returncode, 0)
        envelope = json.loads(completed.stdout.strip().splitlines()[-1])
        self.assertFalse(envelope["success"])
        self.assertIn("usage:", envelope["error"])


if __name__ == "__main__":
    unittest.main()
