from __future__ import annotations

import fnmatch
import threading
import time
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler, FileCreatedEvent
from watchdog.observers import Observer


class _Handler(FileSystemEventHandler):
    def __init__(self, pattern: str, callback: Callable[[str], None]):
        super().__init__()
        self._pattern = pattern
        self._callback = callback
        self._fired = threading.Event()

    def on_created(self, event: FileCreatedEvent) -> None:
        if self._fired.is_set():
            return
        if not event.is_directory and fnmatch.fnmatch(Path(event.src_path).name, self._pattern):
            self._fired.set()
            self._callback(event.src_path)


def _wait_for_stable(path: str, interval: float = 0.1, stable_count: int = 3) -> None:
    prev_size = -1
    count = 0
    while count < stable_count:
        try:
            size = Path(path).stat().st_size
        except OSError:
            size = -1
        if size == prev_size and size >= 0:
            count += 1
        else:
            count = 0
        prev_size = size
        time.sleep(interval)


class FileWatcher:
    def watch(
        self,
        directory: str,
        pattern: str = "*.png",
        timeout: float = 30.0,
    ) -> str:
        """Block until a matching new file appears in *directory*. Returns its path."""
        result: list[str] = []
        ready = threading.Event()

        def _on_file(path: str) -> None:
            _wait_for_stable(path)
            result.append(path)
            ready.set()

        handler = _Handler(pattern, _on_file)
        observer = Observer()
        observer.schedule(handler, str(directory), recursive=False)
        observer.start()
        try:
            if not ready.wait(timeout=timeout):
                raise TimeoutError(
                    f"No {pattern!r} file appeared in {directory!r} within {timeout}s"
                )
        finally:
            observer.stop()
            observer.join()

        return result[0]

    def watch_async(
        self,
        directory: str,
        callback: Callable[[str], None],
        pattern: str = "*.png",
        timeout: float = 30.0,
    ) -> threading.Thread:
        """Start a background thread; call *callback* when the file appears."""

        def _run() -> None:
            try:
                path = self.watch(directory, pattern=pattern, timeout=timeout)
                callback(path)
            except TimeoutError as exc:
                callback.__class__  # silence pyflakes; caller handles via timeout
                raise exc

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return t
