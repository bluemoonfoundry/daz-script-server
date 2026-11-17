"""Unit tests for dazpy's plugin version check policy (``dazpy._version``)."""

from __future__ import annotations

import threading
import warnings
from unittest.mock import MagicMock

import pytest

from dazpy import exceptions
from dazpy._version import VersionTracker, evaluate_server_version

URL = "http://h:1"


@pytest.fixture(autouse=True)
def _versions(monkeypatch):
    monkeypatch.setattr("dazpy._version.client_version", lambda: "2.13.0")
    monkeypatch.setattr("dazpy._version.MIN_SERVER_VERSION", "2.12")


def _check(version="2.12.0", instance="i1"):
    return evaluate_server_version(URL, version, instance)


def _record(fn):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fn()
    return [w for w in caught if issubclass(w.category, exceptions.ServerVersionWarning)]


def _finish(tracker, check):
    tracker.mark_stale()
    assert tracker.claim_check()
    tracker.finish_check(check)


# -- evaluate_server_version ------------------------------------------------


def test_evaluate_compatible_at_minimum():
    c = evaluate_server_version(URL, "2.12.0", "i1")
    assert c.compatible is True
    assert c.message is None
    assert c.min_server_version == "2.12"
    assert c.client_version == "2.13.0"
    assert c.server_instance_id == "i1"
    assert c.server_url == URL
    assert c.server_version == "2.12.0"


@pytest.mark.parametrize("version", ["2.13.4", "3.0.0"])
def test_evaluate_newer_plugin_ok(version):
    assert evaluate_server_version(URL, version, None).compatible is True


def test_evaluate_older_plugin():
    c = evaluate_server_version(URL, "2.11.9", None)
    assert c.compatible is False
    for part in (URL, "2.11.9", "2.13.0", "2.12 or newer", "daz-script-server/releases"):
        assert part in c.message
    assert "pip install" not in c.message


@pytest.mark.parametrize("version", [None, "garbage"])
def test_evaluate_unknown_version(version):
    c = evaluate_server_version(URL, version, None)
    assert c.compatible is None
    assert c.message is None


# -- VersionTracker ---------------------------------------------------------


def test_tracker_first_claim_then_busy():
    t = VersionTracker()
    assert t.claim_check() is True
    assert t.claim_check() is False


def test_tracker_failed_check_stays_stale():
    t = VersionTracker()
    assert t.claim_check()
    t.finish_check(None)
    assert t.claim_check() is True
    assert t.latest is None


def test_tracker_success_not_stale():
    t = VersionTracker()
    c = _check()
    assert t.claim_check()
    t.finish_check(c)
    assert t.claim_check() is False
    assert t.latest is c


def test_tracker_mark_stale_rechecks():
    t = VersionTracker()
    _finish(t, _check())
    t.mark_stale()
    assert t.claim_check() is True


def test_tracker_instance_change_rechecks():
    t = VersionTracker()
    _finish(t, _check(instance="i1"))
    t.observe_instance("i1")
    assert t.claim_check() is False
    t.observe_instance("i2")
    assert t.claim_check() is True


def test_tracker_ignores_missing_instance():
    t = VersionTracker()
    _finish(t, _check(instance=None))
    for value in (None, MagicMock(), ""):
        t.observe_instance(value)
        assert t.claim_check() is False


def test_tracker_first_observed_instance_is_remembered():
    t = VersionTracker()
    _finish(t, _check(instance=None))
    t.observe_instance("i1")
    assert t.claim_check() is False
    t.observe_instance("i2")
    assert t.claim_check() is True


def test_tracker_warns_once_per_instance():
    t = VersionTracker()
    old = _check(version="2.11.0", instance="i1")
    caught = _record(lambda: [_finish(t, old) for _ in range(3)])
    assert len(caught) == 1
    caught = _record(lambda: _finish(t, _check(version="2.11.0", instance="i2")))
    assert len(caught) == 1


def test_tracker_warns_once_without_instance():
    t = VersionTracker()
    old = _check(version="2.11.0", instance=None)
    caught = _record(lambda: [_finish(t, old) for _ in range(2)])
    assert len(caught) == 1


def test_tracker_compatible_check_does_not_warn():
    t = VersionTracker()
    assert _record(lambda: _finish(t, _check())) == []


def test_tracker_callback_every_check():
    seen = []
    t = VersionTracker(on_version_check=seen.append)
    ok, old = _check(), _check(version="2.11.0")
    _finish(t, ok)
    _record(lambda: _finish(t, old))
    assert seen == [ok, old]


def test_tracker_callback_exception_swallowed():
    def boom(_check):
        raise RuntimeError("callback failed")

    t = VersionTracker(on_version_check=boom)
    c = _check()
    assert t.claim_check()
    t.finish_check(c)
    assert t.latest is c


def test_tracker_disabled():
    t = VersionTracker(enabled=False)
    assert t.claim_check() is False
    t.mark_stale()
    t.observe_instance("x")
    assert t.claim_check() is False


def test_claim_is_atomic_across_threads():
    t = VersionTracker()
    barrier = threading.Barrier(20)
    results = []
    lock = threading.Lock()

    def worker():
        barrier.wait()
        r = t.claim_check()
        with lock:
            results.append(r)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert results.count(True) == 1


def test_public_exports():
    import dazpy
    from dazpy import MIN_SERVER_VERSION, VersionCheck  # noqa: F401  (import is the check)

    assert MIN_SERVER_VERSION == "2.12"  # the re-export, unaffected by the fixture
    assert "VersionCheck" in dazpy.__all__
    assert "MIN_SERVER_VERSION" in dazpy.__all__
    assert not hasattr(dazpy._version, "warn_if_server_older")
