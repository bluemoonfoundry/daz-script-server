"""Client/server version compatibility check (see ``ServerVersionWarning``)."""

from __future__ import annotations

import os
import re
import sys
import warnings

from .exceptions import ServerVersionWarning


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


def warn_if_server_older(server_version: str | None, base_url: str) -> None:
    """Warn when the server's major.minor is older than this dazpy's.

    Patch differences are ignored: server and client ship in lockstep, and a
    plugin one patch behind is normal. Unknown versions are not warned about.
    """
    server = parse_version(server_version)
    client = parse_version(client_version())
    if server is None or client is None or server >= client:
        return
    warnings.warn(
        f"DAZ Script Server at {base_url} is version {server_version}, older than "
        f"dazpy {client_version()}. Features added since {server[0]}.{server[1]} may "
        f"fail. Upgrade the DAZ Studio plugin, or install a matching client "
        f"(pip install \"dazpy=={server_version}\"). Pass check_version=False to "
        f"silence this.",
        ServerVersionWarning,
        stacklevel=_first_external_stacklevel(),
    )


_PKG_DIR = os.path.dirname(os.path.abspath(__file__))


def _first_external_stacklevel() -> int:
    """Stack level of the first frame outside dazpy, so the warning points at
    user code regardless of how deep the triggering client call was."""
    # stacklevel=1 is warn_if_server_older itself (the warnings.warn caller).
    frame, level = sys._getframe(1), 1
    while frame is not None and os.path.abspath(frame.f_code.co_filename).startswith(_PKG_DIR):
        frame, level = frame.f_back, level + 1
    return level
