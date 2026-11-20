"""Guards for tests.py's unit-suite discovery (no server needed)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "_tests_runner", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tests.py"))
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


class TestUnitDiscovery(unittest.TestCase):
    def test_live_exclusions_exist(self):
        # A renamed/deleted live file must be dropped from the list, or a
        # replacement live file would silently run in the unit suite.
        for name in runner.LIVE_TEST_FILES:
            self.assertTrue((runner.TESTS_DIR / name).is_file(), name)

    def test_live_files_not_collected(self):
        names = {p.name for p in runner.unit_test_files()}
        self.assertFalse(names & runner.LIVE_TEST_FILES)

    def test_discovers_this_file(self):
        names = {p.name for p in runner.unit_test_files()}
        self.assertIn(os.path.basename(__file__), names)


if __name__ == "__main__":
    unittest.main()
