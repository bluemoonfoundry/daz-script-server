"""Client/server version compatibility check (see ``ServerVersionWarning``)."""

from __future__ import annotations

import logging
import os
import re
import sys
import threading
import warnings
from dataclasses import dataclass
from typing import Callable

from .exceptions import ServerVersionWarning

_log = logging.getLogger(__name__)

#: Oldest DazScriptServer plugin (major.minor) this dazpy needs. Raise it only
#: when dazpy starts calling a plugin route or field that older plugins lack;
#: a dazpy-only release leaves it alone, so users aren't told to upgrade a
#: plugin that hasn't changed.
MIN_SERVER_VERSION = "2.12"

_RELEASES_URL = "https://github.com/bluemoonfoundry/daz-script-server/releases"


def parse_version(value: object) -> tuple[int, int] | None:
    """Return ``(major, minor)`` from a version string like ``"2.10.0"``."""
    if not isinstance(value, str):
        return None
    m = re.match(r"\s*v?(\d+)\.(\d+)", value)
    return (int(m.group(1)), int(m.group(2))) if m else None


def client_version() -> str:
    from . import __version__  # deferred: dazpy/__init__ imports the clients

    return __version__


def server_version_from_status(data: object) -> str | None:
    if isinstance(data, dict) and isinstance(data.get("version"), str):
        return data["version"]
    return None


def server_instance_id_from_status(data: object) -> str | None:
    """The plugin's per-run ``server_instance_id`` from a ``/status`` body."""
    if isinstance(data, dict):
        value = data.get("server_instance_id")
        if isinstance(value, str) and value:
            return value
    return None


@dataclass(frozen=True)
class VersionCheck:
    """Result of one plugin version check.

    - ``server_url``: base URL of the checked plugin, e.g. ``"http://127.0.0.1:18811"``.
    - ``server_version``: plugin version from ``GET /status``; ``None`` if unknown.
    - ``min_server_version``: :data:`MIN_SERVER_VERSION` at check time.
    - ``client_version``: this dazpy's version.
    - ``server_instance_id``: the plugin's per-run identity, if it reported one.
    - ``compatible``: ``True``/``False``; ``None`` when a version couldn't be parsed.
    - ``message``: upgrade advice when ``compatible`` is ``False``, else ``None``.
    """

    server_url: str
    server_version: str | None
    min_server_version: str
    client_version: str
    server_instance_id: str | None
    compatible: bool | None
    message: str | None


def evaluate_server_version(
    server_url: str, server_version: str | None, server_instance_id: str | None
) -> VersionCheck:
    """Compare a plugin version against ``MIN_SERVER_VERSION``."""
    minimum = MIN_SERVER_VERSION
    client = client_version()
    server, needed = parse_version(server_version), parse_version(minimum)
    compatible = None if server is None or needed is None else server >= needed
    message = None
    if compatible is False:
        message = (
            f"Daz Studio plugin at {server_url} is version {server_version}; dazpy "
            f"{client} needs {minimum} or newer. Upgrade the DazScriptServer plugin in "
            f"the Daz Studio instance at that address ({_RELEASES_URL}). If you can't, "
            f"a dazpy release matching the plugin also works."
        )
    return VersionCheck(
        server_url=server_url,
        server_version=server_version,
        min_server_version=minimum,
        client_version=client,
        server_instance_id=server_instance_id,
        compatible=compatible,
        message=message,
    )


class VersionTracker:
    """When to (re)check the plugin version, and what to do with each result.

    Thread-safe and I/O-free: a client asks :meth:`claim_check` before a
    request, fetches ``/status`` itself if it won the claim, and hands the
    outcome to :meth:`finish_check`. Transport failures (:meth:`mark_stale`)
    and a changed ``X-Server-Instance-Id`` (:meth:`observe_instance`) make the
    next request check again.
    """

    def __init__(
        self,
        enabled: bool = True,
        on_version_check: Callable[[VersionCheck], object] | None = None,
    ):
        self._enabled = enabled
        self._callback = on_version_check
        self._lock = threading.Lock()
        self._stale = True
        self._in_progress = False
        self._latest: VersionCheck | None = None
        self._instance: str | None = None
        self._warned: set[tuple[str, str | None]] = set()

    @property
    def latest(self) -> VersionCheck | None:
        return self._latest

    def claim_check(self) -> bool:
        """True if the caller should run a check now (and is the only one)."""
        if not self._enabled:
            return False
        with self._lock:
            if not self._stale or self._in_progress:
                return False
            self._in_progress = True
            return True

    def finish_check(self, check: VersionCheck | None) -> None:
        """Record a claimed check's outcome; ``None`` means it couldn't run."""
        warn = False
        with self._lock:
            self._in_progress = False
            if check is None:
                return
            self._latest = check
            self._stale = False
            if isinstance(check.server_instance_id, str) and check.server_instance_id:
                self._instance = check.server_instance_id
            if check.compatible is False:
                key = (
                    (check.server_url, check.server_instance_id)
                    if isinstance(check.server_instance_id, str)
                    else (check.server_url, check.server_version)
                )
                if key not in self._warned:
                    self._warned.add(key)
                    warn = True
        if warn:
            warnings.warn(check.message, ServerVersionWarning, stacklevel=_first_external_stacklevel())
        if self._callback is not None:
            try:
                self._callback(check)
            except Exception:  # never let a callback break the request
                _log.debug("on_version_check callback raised", exc_info=True)

    def mark_stale(self) -> None:
        """The connection failed: check again before the next request."""
        if not self._enabled:
            return
        with self._lock:
            self._stale = True

    def observe_instance(self, instance_id: object) -> None:
        """Note a response's ``X-Server-Instance-Id``; a change means a restart."""
        if not self._enabled or not isinstance(instance_id, str) or not instance_id:
            return
        with self._lock:
            if self._instance is None:
                self._instance = instance_id
                # The last completed check saw no ID (a plugin too old to send
                # one): an ID now means a different plugin answered.
                if self._latest is not None:
                    self._stale = True
            elif instance_id != self._instance:
                self._stale = True


_PKG_DIR = os.path.dirname(os.path.abspath(__file__))


def _first_external_stacklevel() -> int:
    """Stack level of the first frame outside dazpy, so the warning points at
    user code regardless of how deep the triggering client call was."""
    # stacklevel=1 is the warnings.warn caller (VersionTracker.finish_check).
    frame, level = sys._getframe(1), 1
    while frame is not None and os.path.abspath(frame.f_code.co_filename).startswith(_PKG_DIR):
        frame, level = frame.f_back, level + 1
    return level
