"""Unit and functional tests for examples/comfyui_enhance/file_watcher.py."""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "rendering", "comfyui_enhance"))

from file_watcher import FileWatcher, _wait_for_stable


class TestWaitForStable(unittest.TestCase):
    def test_stable_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x" * 100)
            path = f.name
        try:
            # Should return quickly once size stabilises
            _wait_for_stable(path, interval=0.01, stable_count=3)
        finally:
            os.unlink(path)

    def test_growing_then_stable(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name

        sizes = [0, 50, 100, 100, 100]
        idx = [0]

        def _fake_stat():
            s = MagicMock()
            s.st_size = sizes[min(idx[0], len(sizes) - 1)]
            idx[0] += 1
            return s

        with patch("file_watcher.Path") as MockPath:
            instance = MagicMock()
            instance.stat.side_effect = _fake_stat
            MockPath.return_value = instance
            _wait_for_stable(path, interval=0.001, stable_count=3)

        os.unlink(path)


class TestFileWatcherFunctional(unittest.TestCase):
    """Functional tests that write real files to a temp directory."""

    def test_watch_detects_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "snap.png")

            def _write_after_delay():
                time.sleep(0.3)
                Path(target).write_bytes(b"\x89PNG\r\ndata")

            t = threading.Thread(target=_write_after_delay, daemon=True)
            t.start()

            watcher = FileWatcher()
            result = watcher.watch(tmpdir, pattern="snap.png", timeout=5.0)
            self.assertEqual(os.path.normpath(result), os.path.normpath(target))

    def test_watch_timeout_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watcher = FileWatcher()
            with self.assertRaises(TimeoutError):
                watcher.watch(tmpdir, pattern="*.png", timeout=0.5)

    def test_watch_ignores_non_matching_pattern(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            def _write_wrong_then_right():
                time.sleep(0.2)
                Path(os.path.join(tmpdir, "ignore.txt")).write_bytes(b"ignored")
                time.sleep(0.2)
                Path(os.path.join(tmpdir, "snap.png")).write_bytes(b"\x89PNG\r\ndata")

            t = threading.Thread(target=_write_wrong_then_right, daemon=True)
            t.start()

            watcher = FileWatcher()
            result = watcher.watch(tmpdir, pattern="*.png", timeout=5.0)
            self.assertTrue(result.endswith(".png"))

    def test_watch_async_calls_callback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "snap.png")
            received: list[str] = []
            done = threading.Event()

            def _cb(path: str) -> None:
                received.append(path)
                done.set()

            watcher = FileWatcher()
            watcher.watch_async(tmpdir, _cb, pattern="*.png", timeout=5.0)

            time.sleep(0.2)
            Path(target).write_bytes(b"\x89PNG\r\ndata")

            self.assertTrue(done.wait(timeout=5.0), "callback never fired")
            self.assertEqual(len(received), 1)
            self.assertTrue(received[0].endswith(".png"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
