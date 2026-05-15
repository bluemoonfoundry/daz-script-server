"""
Unified test runner for DazScriptServer.

Suites:
  unit         tests_dazpy.py              mocked, no server needed
  api          tests_api.py                raw HTTP API, requires server
  integration  tests_dazpy_integration.py  dazpy SDK, requires DAZ Studio

Usage:
  python tests.py                        # run all suites
  python tests.py --unit                 # unit tests only (no server needed)
  python tests.py --api                  # HTTP API tests only
  python tests.py --integration          # dazpy SDK integration tests only
  python tests.py --unit --integration   # any combination of suites
"""

import argparse
import sys
import unittest


def _parse_args():
    p = argparse.ArgumentParser(
        description="DazScriptServer unified test runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "suites:\n"
            "  --unit         tests_dazpy.py              mocked, no server needed\n"
            "  --api          tests_api.py                raw HTTP API, requires server\n"
            "  --integration  tests_dazpy_integration.py  dazpy SDK, requires DAZ Studio\n"
        ),
    )
    p.add_argument("--unit", action="store_true", help="Run unit tests (no server needed)")
    p.add_argument("--api", action="store_true", help="Run HTTP API integration tests")
    p.add_argument("--integration", action="store_true", help="Run dazpy SDK integration tests")
    args = p.parse_args()
    if not any([args.unit, args.api, args.integration]):
        args.unit = args.api = args.integration = True
    return args


def main():
    args = _parse_args()
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    if args.unit:
        import tests_dazpy as _unit
        suite.addTests(loader.loadTestsFromModule(_unit))

    if args.api:
        import tests_api as _api
        if not _api.TOKEN:
            print(f"NOTE: No token file found at {_api.TOKEN_FILE}")
        if not _api.AUTH_ENABLED:
            print("NOTE: Authentication appears disabled — auth tests will be skipped.")
        suite.addTests(loader.loadTestsFromModule(_api))

    if args.integration:
        import tests_dazpy_integration as _integration
        suite.addTests(loader.loadTestsFromModule(_integration))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
