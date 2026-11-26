"""Poll-until-deadline helper shared by the tests.

Tests wait on a condition, never on a fixed delay: a sleep is either too
short on a slow machine (flaky) or too long on a fast one (slow suite).

Import it the same way whether the test runs as a script
(``python tests/test_api.py``) or as part of the ``tests`` package::

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from waiting import poll_until
"""
from __future__ import annotations

import time
from typing import TypeVar
from collections.abc import Callable

T = TypeVar("T")


def poll_until(
    fetch: Callable[[], T],
    done: Callable[[T], bool],
    timeout: float,
    interval: float = 0.05,
) -> tuple[T, bool]:
    """Call ``fetch()`` until ``done(value)`` is true or ``timeout`` seconds pass.

    Always calls ``fetch()`` at least once, and once more at the deadline, so
    a condition that becomes true during the last interval still counts.
    Returns ``(last_value, satisfied)``; callers assert on either.
    """
    deadline = time.monotonic() + timeout
    while True:
        value = fetch()
        if done(value):
            return value, True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return value, False
        time.sleep(min(interval, remaining))
