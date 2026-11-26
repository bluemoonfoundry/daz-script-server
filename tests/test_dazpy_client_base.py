"""Shared sync/async client core (dazpy/_client_base.py, W29)."""
from __future__ import annotations

import asyncio
import os
import sys

import httpx
import pytest
import requests

from dazpy import exceptions
from dazpy._client import DazClient
from dazpy._client_aio import AsyncDazClient
from dazpy._client_base import (
    _BaseClient,
    _cancel_route,
    _range_header,
    _render_payload,
    _result_query,
    _script_payload,
)
from dazpy._version import VersionTracker

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dazpy_fakes import async_client, sync_client  # noqa: E402


def _stale(tracker: VersionTracker) -> bool:
    return tracker._stale


def _fresh_tracker() -> VersionTracker:
    t = VersionTracker(enabled=True)
    t._stale = False
    return t


def test_both_clients_share_the_base():
    assert issubclass(DazClient, _BaseClient)
    assert issubclass(AsyncDazClient, _BaseClient)


@pytest.mark.parametrize("cls, exc, expected", [
    (DazClient, requests.exceptions.ConnectionError("x"), exceptions.ConnectionError),
    # ConnectTimeout is both a ConnectionError and a Timeout: connect wins.
    (DazClient, requests.exceptions.ConnectTimeout("x"), exceptions.ConnectionError),
    (DazClient, requests.exceptions.ReadTimeout("x"), exceptions.TimeoutError),
    (DazClient, requests.exceptions.TooManyRedirects("x"), exceptions.ConnectionError),
    (AsyncDazClient, httpx.ConnectError("x"), exceptions.ConnectionError),
    (AsyncDazClient, httpx.ReadTimeout("x"), exceptions.TimeoutError),
    (AsyncDazClient, httpx.RemoteProtocolError("x"), exceptions.ConnectionError),
])
def test_transport_error_mapping_marks_stale(cls, exc, expected):
    client, _ = (sync_client if cls is DazClient else async_client)()
    client._versions = _fresh_tracker()
    err = client._transport_error(exc, 7.0)
    assert type(err) is expected
    if expected is exceptions.TimeoutError:
        assert "7.0s" in str(err)
    assert _stale(client._versions)


def test_sync_artifact_download_failure_marks_version_check_stale():
    client, session = sync_client()
    client._versions = _fresh_tracker()
    session.get.side_effect = requests.exceptions.ConnectionError("down")
    with pytest.raises(exceptions.ConnectionError):
        client.download_artifact("req", 0)
    assert _stale(client._versions)


def test_async_delete_timeout_reports_client_timeout():
    client, http = async_client(timeout=12.0)
    http.delete.side_effect = httpx.ReadTimeout("slow")
    with pytest.raises(exceptions.TimeoutError, match="12.0s"):
        asyncio.run(client.delete_script("x"))
    assert http.delete.call_args.kwargs["timeout"] == 12.0


def test_payload_helpers():
    assert _script_payload({"script": "1"}) == {"script": "1"}
    assert _script_payload({}, {"a": 1}, "r.jsonl") == {"args": {"a": 1}, "reportFile": "r.jsonl"}
    assert _render_payload(
        "o.png", figure="G", morphs={"m": 1}, figures=None, width=10, height=0,
        camera="", engine="iray", iray_samples=0, reset_morphs=True,
    ) == {"output_path": "o.png", "engine": "iray", "reset_morphs": True,
          "figure": "G", "morphs": {"m": 1}}
    assert _result_query(False, 30) == (None, None)
    assert _result_query(True, 30) == ({"wait": "true", "timeout": "30"}, 40.0)
    assert _cancel_route("rnd-1") == ("post", "/render/rnd-1/cancel")
    assert _cancel_route("abc") == ("delete", "/requests/abc")
    assert _range_header(None) == {}
    assert _range_header((5, None)) == {"Range": "bytes=5-"}
    with pytest.raises(ValueError):
        _range_header((5, 2))
