"""Unit and functional tests for examples/comfyui_enhance/file_watcher.py."""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "rendering", "comfyui_enhance"))

import file_watcher  # noqa: E402
from file_watcher import FileWatcher, _wait_for_stable  # noqa: E402


PNG_BYTES = bytes.fromhex("89504e470d0a") + b"data"


def _observed_watcher():
    """Patch FileWatcher's watchdog Observer so tests know when it is watching.

    FileWatcher only sees files created after its observer starts, so tests
    wait on the returned event before writing instead of sleeping and hoping.
    Returns ``(patcher, started)``.
    """
    started = threading.Event()

    class _SignallingObserver(file_watcher.Observer):
        def start(self):
            super().start()
            started.set()

    return patch("file_watcher.Observer", _SignallingObserver), started


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
            patcher, started = _observed_watcher()

            def _write_once_watching():
                if started.wait(timeout=5.0):
                    Path(target).write_bytes(PNG_BYTES)

            threading.Thread(target=_write_once_watching, daemon=True).start()

            with patcher:
                result = FileWatcher().watch(tmpdir, pattern="snap.png", timeout=5.0)
            self.assertEqual(os.path.normpath(result), os.path.normpath(target))

    def test_watch_timeout_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watcher = FileWatcher()
            with self.assertRaises(TimeoutError):
                watcher.watch(tmpdir, pattern="*.png", timeout=0.5)

    def test_watch_ignores_non_matching_pattern(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            patcher, started = _observed_watcher()

            def _write_wrong_then_right():
                if started.wait(timeout=5.0):
                    Path(os.path.join(tmpdir, "ignore.txt")).write_bytes(b"ignored")
                    Path(os.path.join(tmpdir, "snap.png")).write_bytes(PNG_BYTES)

            threading.Thread(target=_write_wrong_then_right, daemon=True).start()

            with patcher:
                result = FileWatcher().watch(tmpdir, pattern="*.png", timeout=5.0)
            self.assertTrue(result.endswith(".png"))

    def test_watch_async_calls_callback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "snap.png")
            received: list[str] = []
            done = threading.Event()

            def _cb(path: str) -> None:
                received.append(path)
                done.set()

            patcher, started = _observed_watcher()
            with patcher:
                FileWatcher().watch_async(tmpdir, _cb, pattern="*.png", timeout=5.0)
                self.assertTrue(started.wait(timeout=5.0), "watcher never started")
            Path(target).write_bytes(PNG_BYTES)

            self.assertTrue(done.wait(timeout=5.0), "callback never fired")
            self.assertEqual(len(received), 1)
            self.assertTrue(received[0].endswith(".png"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
