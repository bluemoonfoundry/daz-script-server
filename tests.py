"""
Unified test runner for DazScriptServer.

Suites:
  unit         tests/test_dazpy.py (+ test_recipe_*)  mocked, no server needed
  api          tests/test_api.py                raw HTTP API, requires server
  integration  tests/test_dazpy_integration.py  dazpy SDK, requires DAZ Studio

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
            "  unit         tests/test_dazpy.py              mocked, no server needed\n"
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
        from tests import test_dazpy as _unit
        suite.addTests(loader.loadTestsFromModule(_unit))
        from tests import test_math3 as _math3
        suite.addTests(loader.loadTestsFromModule(_math3))
        from tests import test_route_security as _routes
        suite.addTests(loader.loadTestsFromModule(_routes))
        from tests import test_openapi_parity as _openapi
        suite.addTests(loader.loadTestsFromModule(_openapi))
        from tests import test_smoke_live as _smoke
        suite.addTests(loader.loadTestsFromModule(_smoke))
        # Scene-recipe unit tests (test_recipe_live.py needs DAZ Studio; excluded)
        import importlib
        from pathlib import Path
        for _p in sorted(Path(__file__).parent.joinpath("tests").glob("test_recipe_*.py")):
            if _p.stem != "test_recipe_live":
                suite.addTests(loader.loadTestsFromModule(
                    importlib.import_module(f"tests.{_p.stem}")))

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
