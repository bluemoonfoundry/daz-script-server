"""Offline tests for tests/smoke_live.py (no server needed): CLI parsing,
engine expectations, and the per-release results index."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from tests import smoke_live  # noqa: E402


def _report(ver, sdk, statuses):
    checks = [{"stage": st, "name": nm, "status": s, "duration_ms": 1, "detail": None}
              for st, nm, s in statuses]
    summary = {k: sum(1 for c in checks if c["status"] == k) for k in ("pass", "fail", "skip")}
    return {"schema": 1, "server_version": ver, "sdk_major": sdk, "studio_version": f"{sdk}.x",
            "summary": summary, "checks": checks}


class TestCli(unittest.TestCase):
    def test_defaults_cover_full_matrix(self):
        args = smoke_live.parse_args([])
        self.assertEqual(args.stages, list(smoke_live.ALL_STAGES))
        self.assertEqual(args.engines, ["iray", "filament", "viewport"])
        self.assertFalse(args.require_engines)

    def test_csv_lists_are_validated(self):
        args = smoke_live.parse_args(["--engines", "Iray, viewport", "--stages", "api"])
        self.assertEqual(args.engines, ["iray", "viewport"])
        self.assertEqual(args.stages, ["api"])
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            smoke_live.parse_args(["--engines", "3delight"])

    def test_every_engine_has_a_readback_expectation(self):
        self.assertEqual(set(smoke_live.EXPECTED_ENGINE), set(smoke_live.ALL_ENGINES))
        # Viewport is a ScreenShot render; the other two are Software renders.
        self.assertEqual(smoke_live.EXPECTED_ENGINE["viewport"][2], 0)
        self.assertEqual(smoke_live.EXPECTED_ENGINE["iray"][2], 2)
        self.assertEqual(smoke_live.EXPECTED_ENGINE["filament"][3], "DzFilamentRenderer")


class TestResultsIndex(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(smoke_live, "RESULTS_DIR", Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_record_writes_report_and_row(self):
        rep = _report("9.9.9", 6, [
            ("api", "status", "pass"),
            ("render", "snapshot_settings", "pass"),
            ("render", "iray.submit", "pass"),
            ("render", "iray.engine_readback", "fail"),
            ("render", "filament.render", "skip"),
            ("render", "viewport.result", "pass"),
            ("mcp", "tools", "skip"),
        ])
        path = smoke_live.record(rep)
        self.assertEqual(path.name, "v9.9.9-ds6.json")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["server_version"], "9.9.9")
        index = (Path(self.tmp.name) / "README.md").read_text(encoding="utf-8")
        row = next(l for l in index.splitlines() if l.startswith("| 9.9.9"))
        cells = [c.strip() for c in row.strip("|").split("|")]
        # Server | Studio | API | Async | Iray | Filament | Viewport | MCP | totals | report
        self.assertEqual(cells[2:8], ["pass", "-", "fail", "skip", "pass", "skip"])
        self.assertEqual(cells[8], "4/1/2")

    def test_index_has_one_row_per_release_and_sdk(self):
        smoke_live.record(_report("1.0.0", 4, [("api", "status", "pass")]))
        smoke_live.record(_report("1.0.0", 6, [("api", "status", "pass")]))
        smoke_live.record(_report("1.0.0", 6, [("api", "status", "fail")]))  # re-run replaces
        rows = [l for l in (Path(self.tmp.name) / "README.md").read_text(encoding="utf-8").splitlines()
                if l.startswith("| 1.0.0")]
        self.assertEqual(len(rows), 2)
        self.assertIn("fail", rows[1])


if __name__ == "__main__":
    unittest.main()
