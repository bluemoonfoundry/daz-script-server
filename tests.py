"""
Unified test runner for DazScriptServer.

Suites:
  unit         tests/test_*.py minus LIVE_TEST_FILES  mocked, no server needed (pytest)
  api          tests/test_api.py                raw HTTP API, requires server
  integration  tests/test_dazpy_integration.py  dazpy SDK, requires DAZ Studio

Usage:
  python tests.py unit                   # unit tests only (no server needed)
  python tests.py api                    # HTTP API tests only
  python tests.py integration            # dazpy SDK integration tests only
  python tests.py unit integration       # any combination of suites
"""

import argparse
import os
import sys
import unittest
from pathlib import Path

VALID_SUITES = ("unit", "api", "integration")

TESTS_DIR = Path(__file__).parent / "tests"

# Test files that talk to a live DAZ Studio / ComfyUI (or parse CLI args at
# import). Every other tests/test_*.py is a unit test and runs under `unit`,
# so a new unit test file is picked up without editing this runner.
LIVE_TEST_FILES = frozenset({
    "test_api.py",                          # raw HTTP API, requires server
    "test_dazpy_integration.py",            # dazpy SDK, requires DAZ Studio
    "test_recipe_live.py",                  # scene recipes against DAZ Studio
    "test_shots_live.py",                   # shots / shot_library against DAZ Studio
    "test_scene_check_live.py",             # scene check + Iray render; clears the scene
    "test_comfyui_enhance_integration.py",  # DAZ Studio + ComfyUI when reachable
    "test_sprite_matrix_integration.py",    # DAZ Studio when reachable
    "test_performance.py",                  # load test; parse_args() at import
})


def unit_test_files():
    """Every tests/test_*.py that is not in LIVE_TEST_FILES, sorted."""
    return sorted(p for p in TESTS_DIR.glob("test_*.py") if p.name not in LIVE_TEST_FILES)


def _parse_args():
    p = argparse.ArgumentParser(
        description="DazScriptServer unified test runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "suites:\n"
            "  unit         tests/test_*.py minus live files mocked, no server needed\n"
            "  api          tests/test_api.py                raw HTTP API, requires server\n"
            "  integration  tests/test_dazpy_integration.py  dazpy SDK, requires DAZ Studio\n"
        ),
    )
    p.add_argument(
        "suites",
        nargs="*",
        choices=VALID_SUITES,
        metavar="suite",
        help=f"One or more suites to run: {', '.join(VALID_SUITES)}",
    )
    args = p.parse_args()
    if not args.suites:
        p.print_help()
        sys.exit(0)
    return args


def main():
    args = _parse_args()
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    if "unit" in args.suites:
        # Unit files mix unittest classes with plain pytest tests
        # (parametrize, pytest-asyncio), so they run under pytest.
        import pytest
        rc = pytest.main(["-q", *[str(p) for p in unit_test_files()]])
        if rc != 0:
            sys.exit(int(rc))
        if not ({"api", "integration"} & set(args.suites)):
            sys.exit(0)

    if {"api", "integration"} & set(args.suites):
        # Naming a live suite is the opt-in that tests/live_gate.py asks for.
        os.environ["DAZ_LIVE_TESTS"] = "1"

    if "api" in args.suites:
        from tests import test_api as _api
        if not _api.TOKEN:
            print(f"NOTE: No token file found at {_api.TOKEN_FILE}")
        if not _api.AUTH_ENABLED:
            print("NOTE: Authentication appears disabled — auth tests will be skipped.")
        suite.addTests(loader.loadTestsFromModule(_api))

    if "integration" in args.suites:
        from tests import test_dazpy_integration as _integration
        suite.addTests(loader.loadTestsFromModule(_integration))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
