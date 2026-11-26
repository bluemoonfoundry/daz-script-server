"""Busy/retryable retry loop in DazClient and AsyncDazClient (yau7.6.3)."""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dazpy import DazClient
from dazpy._client import _raise_for_error
from dazpy.aio import AsyncDazClient
from dazpy_fakes import async_client, sync_client  # noqa: E402
from dazpy.exceptions import (
    AuthenticationError,
    ConcurrencyLimitError,
    ScriptRuntimeError,
    ServerResponseError,
    StudioBusyError,
)


class FakeClock:
    """monotonic() that only advances when the code under test sleeps."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(round(seconds, 6))
        self.now += seconds

    async def asleep(self, seconds):
        self.sleep(seconds)


def _failing(*errors, result="ok"):
    """Zero-arg callable that raises *errors* in order, then returns *result*."""
    it = iter(errors)
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        err = next(it, None)
        if err is not None:
            raise err
        return result

    fn.calls = calls
    return fn


def _async(fn):
    async def afn():
        return fn()
    afn.calls = fn.calls
    return afn


def _busy(retry_after=2.0):
    return StudioBusyError("busy", retry_after=retry_after)


def _retryable(code="RATE_LIMIT_EXCEEDED", retry_after=0.0):
    return ServerResponseError("slow down", status_code=429, error_code=code,
                               retryable=True, retry_after=retry_after)


@pytest.fixture
def clock():
    c = FakeClock()
    with patch("dazpy._client.time.monotonic", c.monotonic), \
         patch("dazpy._client.time.sleep", c.sleep), \
         patch("dazpy._client_aio.time.monotonic", c.monotonic, create=True), \
         patch("dazpy._client_aio.asyncio.sleep", c.asleep):
        yield c


def _sync_retry(fn, retry_on_busy=True, max_wait=30.0):
    return DazClient(check_version=False)._with_busy_retry(fn, retry_on_busy, max_wait)


def _async_retry(fn, retry_on_busy=True, max_wait=30.0):
    client = AsyncDazClient(check_version=False)

    async def run():
        async with client:
            return await client._with_busy_retry(_async(fn), retry_on_busy, max_wait)

    return asyncio.run(run())


RUNNERS = pytest.mark.parametrize("retry", [_sync_retry, _async_retry], ids=["sync", "async"])


@RUNNERS
def test_waits_at_least_server_retry_after(clock, retry):
    assert retry(_failing(_busy(retry_after=3.0))) == "ok"
    assert clock.sleeps == [3.0]


@RUNNERS
def test_backoff_grows_when_retry_after_is_shorter(clock, retry):
    fn = _failing(_busy(0.5), ConcurrencyLimitError("full", retry_after=0.5), _busy(0.5))
    assert retry(fn) == "ok"
    assert clock.sleeps == [1.0, 2.0, 3.0]


@RUNNERS
@pytest.mark.parametrize("code", ["RATE_LIMIT_EXCEEDED", "SERVER_UNAVAILABLE", "IDEMPOTENCY_KEY_IN_FLIGHT"])
def test_retries_server_errors_marked_retryable(clock, retry, code):
    fn = _failing(_retryable(code, retry_after=1.5))
    assert retry(fn) == "ok"
    assert fn.calls["n"] == 2
    assert clock.sleeps == [1.5]


@RUNNERS
@pytest.mark.parametrize("error", [
    ServerResponseError("bad", status_code=400, error_code="INVALID_JSON", retryable=False),
    AuthenticationError("nope"),
    ScriptRuntimeError("ReferenceError"),
], ids=["not-retryable", "auth", "script"])
def test_non_retryable_errors_raise_immediately(clock, retry, error):
    fn = _failing(error)
    with pytest.raises(type(error)):
        retry(fn)
    assert fn.calls["n"] == 1
    assert clock.sleeps == []


@RUNNERS
def test_gives_up_at_max_wait_and_caps_last_sleep(clock, retry):
    fn = _failing(*[_busy(10.0)] * 5)
    with pytest.raises(StudioBusyError):
        retry(fn, max_wait=4.0)
    assert clock.sleeps == [4.0]


@RUNNERS
def test_no_retry_when_disabled(clock, retry):
    fn = _failing(_busy())
    with pytest.raises(StudioBusyError):
        retry(fn, retry_on_busy=False)
    assert clock.sleeps == []


# ── Retry-After on ServerResponseError ─────────────────────────────────────

def _resp(status, body, headers=None):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body
    resp.text = str(body)
    resp.headers = headers or {}
    return resp


def test_server_response_error_carries_retry_after():
    body = {"success": False, "error_code": "IDEMPOTENCY_KEY_IN_FLIGHT", "error": "x", "retryable": True}
    with pytest.raises(ServerResponseError) as info:
        _raise_for_error(_resp(409, body, {"Retry-After": "1"}))
    assert info.value.retry_after == 1.0
    assert info.value.retryable is True


def test_server_response_error_retry_after_defaults_to_zero():
    body = {"success": False, "error_code": "RATE_LIMIT_EXCEEDED", "error": "x", "retryable": True}
    with pytest.raises(ServerResponseError) as info:
        _raise_for_error(_resp(429, body))
    assert info.value.retry_after == 0.0


# ── execute(retry_on_busy=...) wiring, through each client's transport ─────

_BUSY_BODY = {"success": False, "error_code": "STUDIO_BUSY", "error": "busy", "detail": "rendering"}
_OK_BODY = {"success": True, "result": 2, "output": [], "request_id": "ok1"}


def _sync_execute(responses, **kwargs):
    client, session = sync_client()
    session.post.side_effect = responses
    try:
        return client.execute("1+1;", **kwargs)
    finally:
        _sync_execute.posts = session.post.call_count


def _async_execute(responses, **kwargs):
    client, http = async_client()
    http.post.side_effect = responses
    try:
        return asyncio.run(client.execute("1+1;", **kwargs))
    finally:
        _async_execute.posts = http.post.await_count


EXECUTORS = pytest.mark.parametrize("run", [_sync_execute, _async_execute], ids=["sync", "async"])


@EXECUTORS
def test_execute_retry_on_busy_retries_until_success(clock, run):
    busy = _resp(503, _BUSY_BODY, {"Retry-After": "1"})
    result = run([busy, busy, _resp(200, _OK_BODY)], retry_on_busy=True, max_wait=10.0)
    assert result.value == 2
    assert run.posts == 3
    assert clock.sleeps == [1.0, 2.0]


@EXECUTORS
def test_execute_retry_on_busy_gives_up_at_max_wait(clock, run):
    busy = _resp(503, _BUSY_BODY, {"Retry-After": "4"})
    with pytest.raises(StudioBusyError):
        run([busy] * 5, retry_on_busy=True, max_wait=6.0)
    assert run.posts == 3  # last sleep is capped at the deadline, then one final try
    assert clock.sleeps == [4.0, 2.0]


@EXECUTORS
def test_execute_does_not_retry_by_default(clock, run):
    with pytest.raises(StudioBusyError):
        run([_resp(503, _BUSY_BODY, {"Retry-After": "1"}), _resp(200, _OK_BODY)])
    assert run.posts == 1
    assert clock.sleeps == []


# ── AsyncDazClient.waiting_out_busy ────────────────────────────────────────

def test_async_waiting_out_busy_enables_retry_for_the_block(clock):
    client = AsyncDazClient(check_version=False)

    async def run():
        async with client:
            fn = _failing(_busy(1.0))
            with client.waiting_out_busy(10):
                assert await client._with_busy_retry(_async(fn), False, 30.0) == "ok"
            with pytest.raises(StudioBusyError):
                await client._with_busy_retry(_async(_failing(_busy(1.0))), False, 30.0)

    asyncio.run(run())
    assert clock.sleeps == [1.0]


def test_async_waiting_out_busy_nested_keeps_longer_wait(clock):
    client = AsyncDazClient(check_version=False)

    async def run():
        async with client:
            with client.waiting_out_busy(10):
                with client.waiting_out_busy(2):
                    with pytest.raises(StudioBusyError):
                        await client._with_busy_retry(_async(_failing(*[_busy(4.0)] * 9)), False, 30.0)

    asyncio.run(run())
    assert clock.sleeps == [4.0, 4.0, 2.0]


def test_async_waiting_out_busy_is_per_task_and_per_client(clock):
    client = AsyncDazClient(check_version=False)
    other = AsyncDazClient(check_version=False)

    async def outside_task():
        with pytest.raises(StudioBusyError):
            await client._with_busy_retry(_async(_failing(_busy())), False, 30.0)

    async def run():
        async with client, other:
            started = asyncio.Event()
            release = asyncio.Event()

            async def holder():
                with client.waiting_out_busy(10):
                    started.set()
                    await release.wait()

            task = asyncio.create_task(holder())
            await started.wait()
            await outside_task()
            with client.waiting_out_busy(10):
                with pytest.raises(StudioBusyError):
                    await other._with_busy_retry(_async(_failing(_busy())), False, 30.0)
            release.set()
            await task

    asyncio.run(run())
    assert clock.sleeps == []


# ── /render/batch: a retryable 503 can follow a partial accept ─────────────

def _partial_batch_error():
    return ServerResponseError("Queue full after accepting 2 of 5 variants", status_code=503,
                               error_code="SERVER_UNAVAILABLE", retryable=True)


def test_sync_render_batch_does_not_resubmit_after_partial_accept(clock):
    client = DazClient(check_version=False)
    client._post = MagicMock(side_effect=_partial_batch_error())
    with pytest.raises(ServerResponseError):
        client.render_batch_submit([{"output_path": "a.png"}], retry_on_busy=True)
    assert client._post.call_count == 1
    assert clock.sleeps == []


def test_async_render_batch_does_not_resubmit_after_partial_accept(clock):
    client = AsyncDazClient(check_version=False)
    calls = {"n": 0}

    async def post(*args, **kwargs):
        calls["n"] += 1
        raise _partial_batch_error()

    async def run():
        async with client:
            client._post = post
            with pytest.raises(ServerResponseError):
                await client.render_batch_submit([{"output_path": "a.png"}], retry_on_busy=True)

    asyncio.run(run())
    assert calls["n"] == 1
    assert clock.sleeps == []


def test_sync_render_batch_still_retries_busy(clock):
    client = DazClient(check_version=False)
    ok = MagicMock(status_code=200)
    ok.json.return_value = {"batch_id": "b", "request_ids": [], "total": 0}
    client._post = MagicMock(side_effect=[_busy(1.0), ok])
    assert client.render_batch_submit([{"output_path": "a.png"}], retry_on_busy=True)["batch_id"] == "b"
    assert clock.sleeps == [1.0]


# 9qph: from plugin 2.17 a rejected batch enqueued nothing, so its retryable
# 503 is resubmitted; older plugins may have partially accepted it.

def _version(v):
    from dazpy._version import VersionCheck
    return VersionCheck(server_url="http://127.0.0.1:18811", server_version=v,
                        min_server_version="2.12", client_version="2.17.0",
                        server_instance_id="i", compatible=True, message=None)


def _queue_full():
    return ServerResponseError("No variants queued: Queue full", status_code=503,
                               error_code="SERVER_UNAVAILABLE", retryable=True, retry_after=0.0)


@pytest.mark.parametrize("server_version,expected_posts", [("2.16.0", 1), ("2.17.0", 2), ("3.0.0", 2)])
def test_sync_render_batch_retry_depends_on_plugin_version(clock, server_version, expected_posts):
    from unittest.mock import PropertyMock
    client = DazClient(check_version=False)
    ok = MagicMock(status_code=200)
    ok.json.return_value = {"batch_id": "b", "request_ids": ["r"], "total": 1}
    client._post = MagicMock(side_effect=[_queue_full(), ok])
    with patch.object(DazClient, "version_check", new_callable=PropertyMock,
                      return_value=_version(server_version)):
        if expected_posts == 1:
            with pytest.raises(ServerResponseError):
                client.render_batch_submit([{"output_path": "a.png"}], retry_on_busy=True)
        else:
            assert client.render_batch_submit([{"output_path": "a.png"}], retry_on_busy=True)["batch_id"] == "b"
    assert client._post.call_count == expected_posts


@pytest.mark.parametrize("server_version,expected_posts", [("2.16.0", 1), ("2.17.0", 2)])
def test_async_render_batch_retry_depends_on_plugin_version(clock, server_version, expected_posts):
    from unittest.mock import PropertyMock
    client = AsyncDazClient(check_version=False)
    calls = {"n": 0}
    ok = MagicMock(status_code=200)
    ok.json.return_value = {"batch_id": "b", "request_ids": ["r"], "total": 1}

    async def post(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _queue_full()
        return ok

    async def run():
        async with client:
            client._post = post
            if expected_posts == 1:
                with pytest.raises(ServerResponseError):
                    await client.render_batch_submit([{"output_path": "a.png"}], retry_on_busy=True)
            else:
                await client.render_batch_submit([{"output_path": "a.png"}], retry_on_busy=True)

    with patch.object(AsyncDazClient, "version_check", new_callable=PropertyMock,
                      return_value=_version(server_version)):
        asyncio.run(run())
    assert calls["n"] == expected_posts
