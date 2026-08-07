"""Unit tests for dazpy.aio.AsyncDazClient — mocked httpx.AsyncClient, no live server."""
from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
import respx

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import httpx

from dazpy import exceptions
from dazpy._result import ExecutionResult
from dazpy.aio import AsyncDazClient


def _client_with_mock_http(token: str = "") -> tuple[AsyncDazClient, MagicMock]:
    client = AsyncDazClient.__new__(AsyncDazClient)
    object.__setattr__(client, "_base", "http://127.0.0.1:18811")
    object.__setattr__(client, "_token", token)
    object.__setattr__(client, "_timeout", 30.0)
    mock_http = MagicMock()
    mock_http.post = AsyncMock()
    mock_http.get = AsyncMock()
    mock_http.delete = AsyncMock()
    mock_http.aclose = AsyncMock()
    object.__setattr__(client, "_http", mock_http)
    return client, mock_http


def _mock_resp(status_code: int = 200, json_data: dict | None = None, headers: dict | None = None):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = str(json_data)
    resp.headers = headers or {}
    return resp


class TestAsyncDazClientExecute:
    @pytest.mark.asyncio
    async def test_execute_success(self):
        client, mock_http = _client_with_mock_http()
        mock_http.post.return_value = _mock_resp(
            json_data={"success": True, "result": 2, "output": [], "request_id": "abc", "duration_ms": 1.5}
        )
        result = await client.execute("1 + 1;")
        assert isinstance(result, ExecutionResult)
        assert result.value == 2
        assert result.request_id == "abc"
        mock_http.post.assert_awaited_once()
        args, kwargs = mock_http.post.call_args
        assert args[0] == "http://127.0.0.1:18811/execute"
        assert kwargs["json"] == {"script": "1 + 1;"}

    @pytest.mark.asyncio
    async def test_execute_passes_args(self):
        client, mock_http = _client_with_mock_http()
        mock_http.post.return_value = _mock_resp(json_data={"success": True, "result": None, "request_id": "x"})
        await client.execute("f();", args={"a": 1})
        _, kwargs = mock_http.post.call_args
        assert kwargs["json"] == {"script": "f();", "args": {"a": 1}}

    @pytest.mark.asyncio
    async def test_execute_file(self):
        client, mock_http = _client_with_mock_http()
        mock_http.post.return_value = _mock_resp(json_data={"success": True, "result": 1, "request_id": "x"})
        await client.execute_file("C:/scripts/foo.dsa")
        _, kwargs = mock_http.post.call_args
        assert kwargs["json"] == {"scriptFile": "C:/scripts/foo.dsa"}

    @pytest.mark.asyncio
    async def test_auth_error_401(self):
        client, mock_http = _client_with_mock_http(token="bad")
        mock_http.post.return_value = _mock_resp(status_code=401, json_data={"error": "Unauthorized"})
        with pytest.raises(exceptions.AuthenticationError):
            await client.execute("1;")

    @pytest.mark.asyncio
    async def test_script_runtime_error(self):
        client, mock_http = _client_with_mock_http()
        mock_http.post.return_value = _mock_resp(
            json_data={"success": False, "error": "TypeError: undefined is not a function", "request_id": "abc"}
        )
        with pytest.raises(exceptions.ScriptRuntimeError) as excinfo:
            await client.execute("bad();")
        assert excinfo.value.request_id == "abc"

    @pytest.mark.asyncio
    async def test_script_syntax_error(self):
        client, mock_http = _client_with_mock_http()
        mock_http.post.return_value = _mock_resp(
            json_data={"success": False, "error": "SyntaxError at Line 3: unexpected token", "request_id": "def"}
        )
        with pytest.raises(exceptions.ScriptSyntaxError):
            await client.execute("{bad syntax")

    @pytest.mark.asyncio
    async def test_studio_busy_error_503(self):
        client, mock_http = _client_with_mock_http()
        mock_http.post.return_value = _mock_resp(
            status_code=503,
            json_data={
                "success": False,
                "error_code": "STUDIO_BUSY",
                "error": "DAZ Studio's main thread is busy; please retry shortly",
                "detail": "DAZ Studio is currently loading a scene",
            },
            headers={"Retry-After": "2"},
        )
        with pytest.raises(exceptions.StudioBusyError) as excinfo:
            await client.execute("1+1;")
        assert isinstance(excinfo.value, exceptions.DazBusyError)
        assert excinfo.value.retry_after == 2.0

    @pytest.mark.asyncio
    async def test_connect_error_maps_to_dazpy_connection_error(self):
        client, mock_http = _client_with_mock_http()
        mock_http.post.side_effect = httpx.ConnectError("boom", request=MagicMock())
        with pytest.raises(exceptions.ConnectionError):
            await client.execute("1;")

    @pytest.mark.asyncio
    async def test_timeout_error_maps_to_dazpy_timeout_error(self):
        client, mock_http = _client_with_mock_http()
        mock_http.post.side_effect = httpx.TimeoutException("boom", request=MagicMock())
        with pytest.raises(exceptions.TimeoutError):
            await client.execute("1;")


class TestAsyncDazClientRetryOnBusy:
    @pytest.mark.asyncio
    async def test_retries_then_succeeds(self, monkeypatch):
        client, mock_http = _client_with_mock_http()
        busy_resp = _mock_resp(
            status_code=503,
            json_data={"success": False, "error_code": "STUDIO_BUSY", "error": "busy", "detail": "busy"},
            headers={"Retry-After": "0"},
        )
        ok_resp = _mock_resp(json_data={"success": True, "result": 1, "request_id": "x"})
        mock_http.post.side_effect = [busy_resp, ok_resp]

        sleeps = []

        async def fake_sleep(seconds):
            sleeps.append(seconds)

        monkeypatch.setattr("asyncio.sleep", fake_sleep)

        result = await client.execute("1;", retry_on_busy=True, max_wait=5.0)
        assert result.value == 1
        assert mock_http.post.await_count == 2
        assert len(sleeps) == 1

    @pytest.mark.asyncio
    async def test_raises_after_max_wait_exceeded(self, monkeypatch):
        client, mock_http = _client_with_mock_http()
        busy_resp = _mock_resp(
            status_code=503,
            json_data={"success": False, "error_code": "STUDIO_BUSY", "error": "busy", "detail": "busy"},
            headers={"Retry-After": "0"},
        )
        mock_http.post.return_value = busy_resp

        clock = {"t": 0.0}

        def fake_time():
            return clock["t"]

        async def fake_sleep(seconds):
            clock["t"] += seconds + 0.01

        monkeypatch.setattr("asyncio.get_event_loop", lambda: MagicMock(time=fake_time))
        monkeypatch.setattr("asyncio.sleep", fake_sleep)

        with pytest.raises(exceptions.StudioBusyError):
            await client.execute("1;", retry_on_busy=True, max_wait=2.0)


class TestAsyncDazClientRequests:
    @pytest.mark.asyncio
    async def test_get_request_status_not_found(self):
        client, mock_http = _client_with_mock_http()
        mock_http.get.return_value = _mock_resp(status_code=404)
        result = await client.get_request_status("nope")
        assert result == {"status": "not_found"}

    @pytest.mark.asyncio
    async def test_get_request_status(self):
        client, mock_http = _client_with_mock_http()
        mock_http.get.return_value = _mock_resp(json_data={"status": "running"})
        result = await client.get_request_status("abc")
        assert result == {"status": "running"}

    @pytest.mark.asyncio
    async def test_cancel_request_true(self):
        client, mock_http = _client_with_mock_http()
        mock_http.delete.return_value = _mock_resp(status_code=200)
        assert await client.cancel_request("abc") is True

    @pytest.mark.asyncio
    async def test_cancel_request_false_on_http_error(self):
        client, mock_http = _client_with_mock_http()
        mock_http.delete.side_effect = httpx.ConnectError("boom", request=MagicMock())
        assert await client.cancel_request("abc") is False


class TestAsyncDazClientRender:
    @pytest.mark.asyncio
    async def test_render_submit(self):
        client, mock_http = _client_with_mock_http()
        mock_http.post.return_value = _mock_resp(
            json_data={"request_id": "r1", "status": "queued", "submitted_at": "now"}
        )
        result = await client.render_submit("C:/out.png", camera="Front Camera")
        assert result["request_id"] == "r1"
        _, kwargs = mock_http.post.call_args
        assert kwargs["json"]["camera"] == "Front Camera"


class TestAsyncDazClientHealth:
    @pytest.mark.asyncio
    async def test_status(self):
        client, mock_http = _client_with_mock_http()
        mock_http.get.return_value = _mock_resp(json_data={"running": True})
        result = await client.status()
        assert result == {"running": True}

    @pytest.mark.asyncio
    async def test_status_auth_error(self):
        client, mock_http = _client_with_mock_http()
        mock_http.get.return_value = _mock_resp(status_code=403, json_data={"error": "blocked"})
        with pytest.raises(exceptions.AuthenticationError):
            await client.status()


class TestAsyncDazClientContextManager:
    @pytest.mark.asyncio
    async def test_context_manager_closes_http_client(self):
        client, mock_http = _client_with_mock_http()
        async with client:
            pass
        mock_http.aclose.assert_awaited_once()


class TestAsyncDazClientRealHttpxWiring:
    """End-to-end sanity check against a real httpx.AsyncClient, mocked at the transport layer."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_over_real_transport(self):
        respx.post("http://127.0.0.1:18811/execute").mock(
            return_value=httpx.Response(200, json={"success": True, "result": 3, "request_id": "r"})
        )
        async with AsyncDazClient() as client:
            result = await client.execute("1 + 2;")
        assert result.value == 3

    @pytest.mark.asyncio
    @respx.mock
    async def test_stream_render_progress_parses_sse(self):
        sse_body = (
            b"event: progress\ndata: {\"pct\": 50}\n\n"
            b"event: complete\ndata: {\"output_path\": \"C:/out.png\"}\n\n"
        )
        respx.get("http://127.0.0.1:18811/render/r1/progress").mock(
            return_value=httpx.Response(200, content=sse_body, headers={"content-type": "text/event-stream"})
        )
        async with AsyncDazClient() as client:
            events = [e async for e in client.stream_render_progress("r1")]
        assert events == [
            ("progress", {"pct": 50}),
            ("complete", {"output_path": "C:/out.png"}),
        ]
