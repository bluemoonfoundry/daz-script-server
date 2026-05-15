"""
Unified test runner for DazScriptServer.

Suites:
  unit         tests_dazpy.py              mocked, no server needed
  api          tests_api.py                raw HTTP API, requires server
  integration  tests_dazpy_integration.py  dazpy SDK, requires DAZ Studio

Usage:
  python tests.py unit                   # unit tests only (no server needed)
  python tests.py api                    # HTTP API tests only
  python tests.py integration            # dazpy SDK integration tests only
  python tests.py unit integration       # any combination of suites
"""

import argparse
import sys
import unittest

VALID_SUITES = ("unit", "api", "integration")


def _parse_args():
    p = argparse.ArgumentParser(
        description="DazScriptServer unified test runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "suites:\n"
            "  unit         tests_dazpy.py              mocked, no server needed\n"
            "  api          tests_api.py                raw HTTP API, requires server\n"
            "  integration  tests_dazpy_integration.py  dazpy SDK, requires DAZ Studio\n"
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
        import tests_dazpy as _unit
        suite.addTests(loader.loadTestsFromModule(_unit))

    if "api" in args.suites:
        import tests_api as _api
        if not _api.TOKEN:
            print(f"NOTE: No token file found at {_api.TOKEN_FILE}")
        if not _api.AUTH_ENABLED:
            print("NOTE: Authentication appears disabled — auth tests will be skipped.")
        suite.addTests(loader.loadTestsFromModule(_api))

    if "integration" in args.suites:
        import tests_dazpy_integration as _integration
        suite.addTests(loader.loadTestsFromModule(_integration))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
