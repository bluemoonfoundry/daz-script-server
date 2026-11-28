"""SSE responses are always closed; on_progress errors propagate (yau7.6.4)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from dazpy import DazClient
from dazpy._render_api import _wait_render_sse
from dazpy._render_api_aio import _wait_render_sse_async
from dazpy.exceptions import RenderError


def _sse_resp(*events: tuple[str, str]) -> MagicMock:
    lines: list[bytes] = []
    for event, data in events:
        lines += [f"event: {event}".encode(), f"data: {data}".encode(), b""]
    resp = MagicMock()
    resp.status_code = 200
    resp.iter_lines.return_value = iter(lines)
    return resp


def _sync_client(resp) -> MagicMock:
    client = MagicMock(spec=DazClient)
    client.stream_render_progress.return_value = resp
    client.get_request_result.return_value = {"success": True, "result": {"output_path": "polled"}}
    return client


# ── DazClient stream openers close a rejected response ─────────────────────

@pytest.mark.parametrize("method,args", [
    ("stream_render_progress", ("rnd-1",)),
    ("stream_scene_events", ()),
])
def test_stream_opener_closes_non_200_response(method, args):
    client = DazClient(check_version=False)
    rejected = MagicMock(status_code=404)
    client._session.get = MagicMock(return_value=rejected)
    assert getattr(client, method)(*args) is None
    rejected.close.assert_called_once()


# ── _wait_render_sse (sync) ────────────────────────────────────────────────

def test_sync_wait_closes_response_on_complete():
    resp = _sse_resp(("complete", '{"output_path": "C:/out.png", "file_size_bytes": 10}'))
    result = _wait_render_sse(_sync_client(resp), "rnd-1", timeout=5)
    assert result.output_path == "C:/out.png"
    resp.close.assert_called_once()


def test_sync_wait_closes_response_on_error_event():
    resp = _sse_resp(("error", '{"error": "boom"}'))
    with pytest.raises(RenderError, match="boom"):
        _wait_render_sse(_sync_client(resp), "rnd-1", timeout=5)
    resp.close.assert_called_once()


def test_sync_wait_propagates_on_progress_error_without_polling():
    resp = _sse_resp(("progress", '{"percent": 10}'), ("complete", '{"output_path": "x"}'))
    client = _sync_client(resp)

    def bad_callback(_data):
        raise KeyError("user bug")

    with pytest.raises(KeyError, match="user bug"):
        _wait_render_sse(client, "rnd-1", timeout=5, on_progress=bad_callback)
    client.get_request_result.assert_not_called()
    resp.close.assert_called_once()


def test_sync_wait_still_falls_back_to_polling_when_stream_breaks():
    resp = MagicMock(status_code=200)
    resp.iter_lines.side_effect = OSError("connection reset")
    client = _sync_client(resp)
    result = _wait_render_sse(client, "rnd-1", timeout=5)
    assert result.output_path == "polled"
    resp.close.assert_called_once()


# ── _wait_render_sse_async ─────────────────────────────────────────────────

class _AsyncClient:
    """Minimal async client whose progress stream records when it is closed."""

    def __init__(self, events):
        self.events = events
        self.stream_closed = False
        self.polled = False

    async def stream_render_progress(self, request_id, stream_timeout=None):
        try:
            for event in self.events:
                yield event
        finally:
            self.stream_closed = True

    async def get_request_result(self, request_id, wait=False, wait_timeout=None):
        self.polled = True
        return {"success": True, "result": {"output_path": "polled"}}


def test_async_wait_closes_stream_on_complete():
    client = _AsyncClient([("complete", {"output_path": "C:/out.png"}), ("progress", {})])

    async def run():
        result = await _wait_render_sse_async(client, "rnd-1", timeout=5)
        # Closed before returning, not whenever the generator is collected.
        assert client.stream_closed
        return result

    assert asyncio.run(run()).output_path == "C:/out.png"


def test_async_wait_propagates_on_progress_error_without_polling():
    client = _AsyncClient([("progress", {"percent": 10}), ("complete", {"output_path": "x"})])

    def bad_callback(_data):
        raise KeyError("user bug")

    async def run():
        with pytest.raises(KeyError, match="user bug"):
            await _wait_render_sse_async(client, "rnd-1", timeout=5, on_progress=bad_callback)
        assert client.stream_closed

    asyncio.run(run())
    assert not client.polled
