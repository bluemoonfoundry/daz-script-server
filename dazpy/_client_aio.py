from __future__ import annotations

import asyncio
import contextvars
import os
import time  # noqa: F401  (patched by tests: dazpy._client_aio.time.monotonic)
from contextlib import contextmanager
from typing import Any, Callable, Iterator, cast

try:
    import httpx
except ImportError as e:  # pragma: no cover - exercised via test_client_aio_import_error
    raise ImportError(
        "dazpy.aio requires the 'httpx' package. Install it with `pip install dazpy[aio]` "
        "or `pip install httpx`."
    ) from e

from .exceptions import DazError
from ._geometry_frames import GeometryFrames, geometry_frames_payload, parse_geometry_frames
from ._result import ExecutionResult
from ._sse import aiter_sse_events
from ._version import (
    VersionCheck,
    server_version_from_status,
    ATOMIC_RENDER_BATCH_VERSION,
    server_at_least,
)
from ._client_base import (
    _BaseClient,
    _DEFAULT_HOST,
    _DEFAULT_PORT,
    _MAX_BACKOFF,
    _artifact_targets,
    _batch_script,
    _bytes_or_file,
    _cancel_route,
    _events_params,
    _job_headers,
    _json_ok,
    _json_or_not_found,
    _map_response,
    _raise_for_error,
    _range_header,
    _render_animation_payload,
    _render_batch_payload,
    _render_payload,
    _result_query,
    _script_payload,
    _submitted_request_id,
    _thumbnail_params,
)

# AsyncDazClient.waiting_out_busy scopes, keyed by id(client). A ContextVar
# makes a block apply to the current task (and tasks it starts) only.
_BUSY_WAIT: contextvars.ContextVar[dict[int, float]] = contextvars.ContextVar("dazpy_busy_wait")


class AsyncDazClient(_BaseClient):
    """Async HTTP client for the DAZ Studio Script Server, backed by ``httpx``.

    Mirrors :class:`dazpy.DazClient`'s API surface as ``async def`` methods.
    Requires the optional ``httpx`` dependency (``pip install dazpy[aio]``).

    Can be used as an async context manager to ensure the underlying
    connection pool is closed::

        async with AsyncDazClient() as client:
            result = await client.execute("1 + 1;")

    Or managed manually via :meth:`aclose`.

    ``check_version`` and ``on_version_check`` behave as on
    :class:`dazpy.DazClient`. The callback must be a plain (sync) callable; it
    runs on the event loop thread.
    """

    _CONNECT_ERRORS = (httpx.ConnectError,)
    _TIMEOUT_ERRORS = (httpx.TimeoutException,)
    _TRANSPORT_ERRORS = (httpx.HTTPError,)

    def __init__(
        self,
        host: str = _DEFAULT_HOST,
        port: int = _DEFAULT_PORT,
        token: str | None = None,
        timeout: float = 30.0,
        check_version: bool = True,
        on_version_check: Callable[[VersionCheck], object] | None = None,
    ):
        super().__init__(host, port, token, timeout, check_version, on_version_check)
        self._http = httpx.AsyncClient(timeout=timeout)

    async def __aenter__(self) -> "AsyncDazClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying ``httpx.AsyncClient`` connection pool."""
        await self._http.aclose()

    async def _send(self, method: str, path: str, headers: dict | None,
                    timeout: float | None, **kwargs: Any) -> "httpx.Response":
        """Issue one request (``_post``/``_get``/``_delete``)."""
        await self._check_server_version()
        try:
            return self._observe(await getattr(self._http, method)(
                f"{self._base}{path}",
                headers=self._merged_headers(headers),
                timeout=self._http_timeout(timeout),
                **kwargs,
            ))
        except self._TRANSPORT_ERRORS as e:
            raise self._transport_error(e, timeout) from e

    async def _check_server_version(self) -> None:
        """Best-effort plugin version check (see ``DazClient``)."""
        if not self._versions.claim_check():
            return
        check = None
        try:
            check = self._version_check_from_status(
                await self._http.get(f"{self._base}/status", headers=self._headers))
        except Exception:
            check = None  # unreachable/odd server: let the real request report it
        finally:
            self._versions.finish_check(check)

    async def get_server_version(self) -> str | None:
        """The connected server's version string, or ``None`` if unknown."""
        known = self._known_server_version()
        if known is None:
            try:
                known = self._server_version = server_version_from_status(await self.status())
            except Exception:
                return None
        return known

    @contextmanager
    def waiting_out_busy(self, max_wait: float) -> Iterator["AsyncDazClient"]:
        """Within the block, this client's script execution and submission calls
        made from the current task retry a busy Studio for up to *max_wait*
        seconds, as if passed ``retry_on_busy=True``. See
        :meth:`dazpy.DazClient.waiting_out_busy`.

        A plain ``with`` block (usable inside ``async def``). It applies to the
        current task and to tasks started inside it; other tasks are
        unaffected. Nested blocks keep the longer wait.
        """
        scopes = _BUSY_WAIT.get({})
        prev = scopes.get(id(self))
        wait = float(max_wait) if prev is None else max(prev, float(max_wait))
        token = _BUSY_WAIT.set({**scopes, id(self): wait})
        try:
            yield self
        finally:
            _BUSY_WAIT.reset(token)

    def _scoped_busy_wait(self) -> float | None:
        return _BUSY_WAIT.get({}).get(id(self))

    async def _with_busy_retry(self, fn, retry_on_busy: bool, max_wait: float, *,
                               retry_server_errors: "bool | Callable[[], bool]" = True):
        """Await *fn* (a zero-arg async callable). See
        :meth:`dazpy.DazClient._with_busy_retry`."""
        deadline = self._busy_deadline(retry_on_busy, max_wait)
        if deadline is None:
            return await fn()
        backoff = 1.0
        while True:
            try:
                return await fn()
            except DazError as exc:
                pause = self._retry_pause(exc, deadline, backoff, retry_server_errors)
                if pause is None:
                    raise
                await asyncio.sleep(pause)
                backoff = min(backoff + 1.0, _MAX_BACKOFF)

    async def execute(
        self, script: str, args: object = None, *, retry_on_busy: bool = False, max_wait: float = 30.0,
        timeout: float | None = None,
    ) -> ExecutionResult:
        """Execute a DazScript string. See :meth:`dazpy.DazClient.execute`."""
        payload = _script_payload({"script": script}, args)

        async def _do():
            return _map_response(await self._post("/execute", payload, timeout=timeout), script=script)

        return await self._with_busy_retry(_do, retry_on_busy, max_wait)

    async def execute_file(
        self, script_file: str, args: object = None, *, retry_on_busy: bool = False, max_wait: float = 30.0
    ) -> ExecutionResult:
        """Execute a ``.dsa`` script file. See :meth:`dazpy.DazClient.execute_file`."""
        payload = _script_payload({"scriptFile": script_file}, args)

        async def _do():
            return _map_response(await self._post("/execute", payload))

        return await self._with_busy_retry(_do, retry_on_busy, max_wait)

    async def execute_async_submit(
        self, script: str, args: object = None, *, report_file: str | None = None,
        retry_on_busy: bool = False, max_wait: float = 30.0,
        idempotency_key: str | None = None, correlation_id: str | None = None,
    ) -> str:
        """Submit a script for async execution. See :meth:`dazpy.DazClient.execute_async_submit`."""
        payload = _script_payload({"script": script}, args, report_file)

        async def _do():
            return _submitted_request_id(await self._post(
                "/execute/async", payload, _job_headers(idempotency_key, correlation_id)))

        return await self._with_busy_retry(_do, retry_on_busy, max_wait)

    async def execute_file_async_submit(
        self, script_file: str, args: object = None, *, report_file: str | None = None,
        retry_on_busy: bool = False, max_wait: float = 30.0,
        idempotency_key: str | None = None, correlation_id: str | None = None,
    ) -> str:
        """Submit a host-side ``.dsa`` file asynchronously.

        See :meth:`dazpy.DazClient.execute_file_async_submit`.
        """
        payload = _script_payload({"scriptFile": script_file}, args, report_file)

        async def _do():
            return _submitted_request_id(await self._post(
                "/execute/async", payload, _job_headers(idempotency_key, correlation_id)))

        return await self._with_busy_retry(_do, retry_on_busy, max_wait)

    async def execute_batch_async(
        self, operations: list[dict], args: object = None, *, report_file: str | None = None
    ) -> str:
        """Submit multiple operations as one async request. See :meth:`dazpy.DazClient.execute_batch_async`."""
        return await self.execute_async_submit(
            _batch_script(operations), args=args, report_file=report_file)

    async def register_script(self, name: str, script: str, description: str = "") -> dict:
        """Register or replace a named DazScript on the server."""
        return _json_ok(await self._post(
            "/scripts/register",
            {"name": name, "description": description, "script": script},
        ))

    async def list_scripts(self) -> list[dict]:
        """Return the registered scripts. See :meth:`dazpy.DazClient.list_scripts`."""
        return _json_ok(await self._get("/scripts")).get("scripts", [])

    async def delete_script(self, name: str, *, missing_ok: bool = False) -> bool:
        """Remove a registered script. See :meth:`dazpy.DazClient.delete_script`."""
        resp = await self._delete(f"/scripts/{name}")
        if resp.status_code == 404 and missing_ok:
            return False
        _raise_for_error(resp)
        return True

    async def export_geometry_frames(
        self,
        frames,
        *,
        node: str | None = None,
        indices=None,
        surfaces=None,
        bones=None,
        resolution: str = "base",
        scene_update: bool = True,
        timeout: float | None = None,
    ) -> GeometryFrames:
        """Export deformed figure vertices and bone origins for several frames.

        See :meth:`dazpy.DazClient.export_geometry_frames`.
        """
        payload = geometry_frames_payload(
            frames, node, indices, surfaces, bones, resolution, scene_update)
        resp = await self._post("/geometry/frames", payload, timeout=timeout)
        _raise_for_error(resp)
        return parse_geometry_frames(resp.content, payload.get("bones", []))

    async def execute_registered(
        self, name: str, args: object = None, *, retry_on_busy: bool = False,
        max_wait: float = 30.0,
    ) -> ExecutionResult:
        """Execute a registered script by name."""
        payload = _script_payload({}, args)

        async def _do():
            return _map_response(await self._post(f"/scripts/{name}/execute", payload))

        return await self._with_busy_retry(_do, retry_on_busy, max_wait)

    async def execute_registered_async_submit(
        self, name: str, args: object = None, *, report_file: str | None = None,
        retry_on_busy: bool = False, max_wait: float = 30.0,
        idempotency_key: str | None = None, correlation_id: str | None = None,
    ) -> str:
        """Submit a registered script and return its async request id."""
        payload = _script_payload({}, args, report_file)

        async def _do():
            return _submitted_request_id(await self._post(
                f"/scripts/{name}/async", payload, _job_headers(idempotency_key, correlation_id)))

        return await self._with_busy_retry(_do, retry_on_busy, max_wait)

    async def get_request_status(self, request_id: str) -> dict:
        """See :meth:`dazpy.DazClient.get_request_status`."""
        return _json_or_not_found(await self._get(f"/requests/{request_id}/status"))

    async def get_request_result(self, request_id: str, wait: bool = False, wait_timeout: int = 30) -> dict:
        """See :meth:`dazpy.DazClient.get_request_result`."""
        params, request_timeout = _result_query(wait, wait_timeout)
        return _json_or_not_found(await self._get(
            f"/requests/{request_id}/result", params=params, timeout=request_timeout))

    async def list_requests(self, status: str | None = None) -> dict:
        """See :meth:`dazpy.DazClient.list_requests`."""
        return _json_ok(await self._get("/requests", params={"status": status} if status else None))

    async def cancel_request_detail(self, request_id: str) -> dict:
        """Cancel a script or render request and return the server response."""
        method, path = _cancel_route(request_id)
        return _json_ok(await (self._post(path, {}) if method == "post" else self._delete(path)))

    async def cancel_request(self, request_id: str) -> bool:
        """See :meth:`dazpy.DazClient.cancel_request`."""
        try:
            await self.cancel_request_detail(request_id)
            return True
        except DazError:
            return False

    # ── Artifacts ─────────────────────────────────────────────────────────────

    async def list_artifacts(self, request_id: str) -> dict:
        """See :meth:`dazpy.DazClient.list_artifacts`."""
        return _json_ok(await self._get(f"/artifacts/{request_id}"))

    async def download_artifact(
        self,
        request_id: str,
        artifact_id: str | int,
        dest: "str | os.PathLike[str] | None" = None,
        *,
        byte_range: "tuple[int, int | None] | None" = None,
        chunk_size: int = 1 << 20,
        timeout: float | None = None,
    ) -> "bytes | str":
        """See :meth:`dazpy.DazClient.download_artifact`."""
        headers = self._merged_headers(_range_header(byte_range))
        await self._check_server_version()
        try:
            async with self._http.stream(
                "GET", f"{self._base}/artifacts/{request_id}/{artifact_id}",
                headers=headers, timeout=self._http_timeout(timeout),
            ) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    _raise_for_error(resp)
                if dest is None:
                    return await resp.aread()
                path = os.fspath(dest)
                with open(path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size):
                        f.write(chunk)
                return path
        except self._TRANSPORT_ERRORS as e:
            raise self._transport_error(e, timeout) from e

    async def get_artifact_thumbnail(
        self,
        request_id: str,
        artifact_id: str | int,
        size: int = 256,
        *,
        format: str = "png",
        dest: "str | os.PathLike[str] | None" = None,
        timeout: float | None = None,
    ) -> "bytes | str":
        """See :meth:`dazpy.DazClient.get_artifact_thumbnail`."""
        resp = await self._get(f"/artifacts/{request_id}/{artifact_id}",
                               params=_thumbnail_params(size, format), timeout=timeout)
        _raise_for_error(resp)
        return _bytes_or_file(resp.content, dest)

    async def download_artifacts(
        self, request_id: str, dest_dir: "str | os.PathLike[str]"
    ) -> "list[str]":
        """See :meth:`dazpy.DazClient.download_artifacts`."""
        written: list[str] = []
        for aid, path in _artifact_targets(await self.list_artifacts(request_id), dest_dir):
            # With a dest, download_artifact returns the written path (str).
            written.append(cast(str, await self.download_artifact(request_id, aid, path)))
        return written

    # ── Render ────────────────────────────────────────────────────────────────

    async def render_submit(
        self,
        output_path: str,
        *,
        figure: str | None = None,
        morphs: dict | None = None,
        figures: list | None = None,
        width: int = 0,
        height: int = 0,
        camera: str = "",
        engine: str = "",
        iray_samples: int = 0,
        reset_morphs: bool = False,
        retry_on_busy: bool = False,
        max_wait: float = 30.0,
        idempotency_key: str | None = None, correlation_id: str | None = None,
    ) -> dict:
        """Submit a render job. See :meth:`dazpy.DazClient.render_submit`."""
        payload = _render_payload(
            output_path, figure=figure, morphs=morphs, figures=figures, width=width,
            height=height, camera=camera, engine=engine, iray_samples=iray_samples,
            reset_morphs=reset_morphs)

        async def _do():
            return _json_ok(await self._post("/render", payload, _job_headers(idempotency_key, correlation_id)))

        return await self._with_busy_retry(_do, retry_on_busy, max_wait)

    async def render_batch_submit(
        self, variants: list, base: dict | None = None, *, retry_on_busy: bool = False, max_wait: float = 30.0,
        idempotency_key: str | None = None, correlation_id: str | None = None,
    ) -> dict:
        """Submit a batch render job. See :meth:`dazpy.DazClient.render_batch_submit`."""
        payload = _render_batch_payload(variants, base)

        async def _do():
            return _json_ok(await self._post("/render/batch", payload, _job_headers(idempotency_key, correlation_id)))

        # See DazClient.render_batch_submit: resubmit only on an atomic-batch plugin.
        return await self._with_busy_retry(
            _do, retry_on_busy, max_wait,
            retry_server_errors=lambda: server_at_least(self.version_check, ATOMIC_RENDER_BATCH_VERSION))

    async def render_animation_submit(
        self,
        output_path: str,
        start_frame: int,
        end_frame: int,
        *,
        frame_padding: int = 4,
        width: int = 0,
        height: int = 0,
        camera: str = "",
        engine: str = "",
        retry_on_busy: bool = False,
        max_wait: float = 30.0,
        idempotency_key: str | None = None, correlation_id: str | None = None,
    ) -> dict:
        """Submit an animation render job. See :meth:`dazpy.DazClient.render_animation_submit`."""
        payload = _render_animation_payload(
            output_path, start_frame, end_frame, frame_padding=frame_padding,
            width=width, height=height, camera=camera, engine=engine)

        async def _do():
            return _json_ok(await self._post("/render/animation", payload, _job_headers(idempotency_key, correlation_id)))

        return await self._with_busy_retry(_do, retry_on_busy, max_wait)

    async def cancel_render(self, request_id: str) -> bool:
        """See :meth:`dazpy.DazClient.cancel_render`."""
        if not request_id.startswith("rnd-"):
            return False
        return await self.cancel_request(request_id)

    async def _stream_sse(self, path: str, params: dict | None, stream_timeout: float | None):
        """Async-iterate parsed ``(event_type, data)`` pairs from an SSE route."""
        try:
            async with self._http.stream(
                "GET", f"{self._base}{path}", headers=self._headers,
                params=params, timeout=stream_timeout,
            ) as resp:
                _raise_for_error(resp)
                async for event_type, data in _aiter_sse_events(resp):
                    yield event_type, data
        except self._TRANSPORT_ERRORS as exc:
            raise self._transport_error(exc, stream_timeout or self._timeout) from exc

    async def stream_render_progress(self, request_id: str, stream_timeout: float = 305.0):
        """Async-iterate ``(event_type, data)`` SSE pairs from the render progress stream.

        Unlike :meth:`dazpy.DazClient.stream_render_progress` (which returns a
        raw ``requests.Response`` for the caller to parse), this yields
        already-parsed ``(event_type, data_dict)`` tuples, since ``httpx``
        streaming responses are only valid within their ``async with`` block.
        Yields nothing if the stream cannot be opened.
        """
        async for event in self._stream_sse(f"/render/{request_id}/progress", None, stream_timeout):
            yield event

    async def stream_scene_events(
        self,
        categories: "list[str] | None" = None,
        stream_timeout: "float | None" = None,
    ):
        """Async-iterate ``(event_type, data)`` SSE pairs from ``GET /scene/events``.

        See :meth:`stream_render_progress` for why this yields parsed tuples
        rather than a raw response object.
        """
        async for event in self._stream_sse("/scene/events", _events_params(categories), stream_timeout):
            yield event

    # ── Server health ─────────────────────────────────────────────────────────

    async def status(self) -> dict:
        """See :meth:`dazpy.DazClient.status`."""
        return _json_ok(await self._get("/status"))

    async def health(self) -> dict:
        """See :meth:`dazpy.DazClient.health`."""
        return _json_ok(await self._get("/health"))

    async def metrics(self) -> dict:
        """See :meth:`dazpy.DazClient.metrics`."""
        return _json_ok(await self._get("/metrics"))

    async def capabilities(self) -> dict:
        """See :meth:`dazpy.DazClient.capabilities`."""
        return _json_ok(await self._get("/capabilities"))


def _aiter_sse_events(resp: "httpx.Response"):
    """Yield ``(event_type, data_dict)`` pairs from a streaming httpx SSE response."""
    return aiter_sse_events(resp.aiter_lines())
