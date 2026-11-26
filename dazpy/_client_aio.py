from __future__ import annotations

import asyncio
import contextvars
import json
import os
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator, cast

try:
    import httpx
except ImportError as e:  # pragma: no cover - exercised via test_client_aio_import_error
    raise ImportError(
        "dazpy.aio requires the 'httpx' package. Install it with `pip install dazpy[aio]` "
        "or `pip install httpx`."
    ) from e

from .exceptions import (
    ConnectionError,
    DazError,
    TimeoutError,
)
from ._geometry_frames import GeometryFrames, geometry_frames_payload, parse_geometry_frames
from ._result import ExecutionResult
from ._version import (
    VersionCheck,
    VersionTracker,
    evaluate_server_version,
    server_instance_id_from_status,
    server_version_from_status,
    ATOMIC_RENDER_BATCH_VERSION,
    server_at_least,
)
from ._client import (
    _DEFAULT_HOST, _DEFAULT_PORT, _job_headers, _load_token, _raise_for_error, _map_response,
    _safe_artifact_filename, _MAX_BACKOFF, _retry_delay,
)

# AsyncDazClient.waiting_out_busy scopes, keyed by id(client). A ContextVar
# makes a block apply to the current task (and tasks it starts) only.
_BUSY_WAIT: contextvars.ContextVar[dict[int, float]] = contextvars.ContextVar("dazpy_busy_wait")


class AsyncDazClient:
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

    # Class defaults keep instances built without __init__ (tests) check-free.
    _versions: VersionTracker = VersionTracker(enabled=False)
    _server_version: str | None = None

    def __init__(
        self,
        host: str = _DEFAULT_HOST,
        port: int = _DEFAULT_PORT,
        token: str | None = None,
        timeout: float = 30.0,
        check_version: bool = True,
        on_version_check: Callable[[VersionCheck], object] | None = None,
    ):
        self._base = f"http://{host}:{port}"
        self._token = token if token is not None else _load_token()
        self._timeout = timeout
        self._http = httpx.AsyncClient(timeout=timeout)
        self._versions = VersionTracker(enabled=check_version, on_version_check=on_version_check)
        self._server_version: str | None = None

    async def __aenter__(self) -> "AsyncDazClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying ``httpx.AsyncClient`` connection pool."""
        await self._http.aclose()

    @property
    def _headers(self) -> dict:
        h = {}
        if self._token:
            h["X-API-Token"] = self._token
        return h

    async def _check_server_version(self) -> None:
        """Best-effort plugin version check (see ``DazClient``)."""
        if not self._versions.claim_check():
            return
        check = None
        try:
            resp = await self._http.get(f"{self._base}/status", headers=self._headers)
            data = resp.json()
            instance = server_instance_id_from_status(data)
            if instance is None:
                header = resp.headers.get("X-Server-Instance-Id")
                instance = header if isinstance(header, str) and header else None
            version = server_version_from_status(data)
            check = evaluate_server_version(self._base, version, instance)
            if version is not None:
                self._server_version = version
        except Exception:
            check = None  # unreachable/odd server: let the real request report it
        finally:
            self._versions.finish_check(check)

    def _observe(self, resp: "httpx.Response") -> "httpx.Response":
        try:
            self._versions.observe_instance(resp.headers.get("X-Server-Instance-Id"))
        except Exception:
            pass
        return resp

    @property
    def version_check(self) -> VersionCheck | None:
        """The latest plugin version check, or ``None`` before one completes."""
        return self._versions.latest

    async def get_server_version(self) -> str | None:
        """The connected server's version string, or ``None`` if unknown."""
        latest = self._versions.latest
        if latest is not None and latest.server_version is not None:
            return latest.server_version
        if self._server_version is None:
            try:
                self._server_version = server_version_from_status(await self.status())
            except Exception:
                return None
        return self._server_version

    async def _post(
        self, path: str, payload: dict, headers: dict | None = None, timeout: float | None = None
    ) -> "httpx.Response":
        await self._check_server_version()
        merged = {**self._headers, **headers} if headers else self._headers
        extra: dict[str, Any] = {} if timeout is None else {"timeout": timeout}
        try:
            return self._observe(
                await self._http.post(f"{self._base}{path}", json=payload, headers=merged, **extra)
            )
        except httpx.ConnectError as e:
            self._versions.mark_stale()
            raise ConnectionError(f"Cannot reach DAZ Studio at {self._base}: {e}") from e
        except httpx.TimeoutException as e:
            self._versions.mark_stale()
            raise TimeoutError(f"Request timed out after {self._timeout if timeout is None else timeout}s") from e
        except httpx.HTTPError as e:
            self._versions.mark_stale()
            raise ConnectionError(f"HTTP transport failure for DAZ Studio: {e}") from e

    async def _get(
        self, path: str, params: dict | None = None, timeout: float | None = None
    ) -> "httpx.Response":
        await self._check_server_version()
        try:
            return self._observe(await self._http.get(
                f"{self._base}{path}", headers=self._headers, params=params,
                timeout=self._timeout if timeout is None else timeout,
            ))
        except httpx.ConnectError as e:
            self._versions.mark_stale()
            raise ConnectionError(f"Cannot reach DAZ Studio at {self._base}: {e}") from e
        except httpx.TimeoutException as e:
            self._versions.mark_stale()
            raise TimeoutError(f"Request timed out after {self._timeout if timeout is None else timeout}s") from e
        except httpx.HTTPError as e:
            self._versions.mark_stale()
            raise ConnectionError(f"HTTP transport failure for DAZ Studio: {e}") from e

    async def _delete(self, path: str) -> "httpx.Response":
        await self._check_server_version()
        try:
            return self._observe(
                await self._http.delete(f"{self._base}{path}", headers=self._headers)
            )
        except httpx.ConnectError as e:
            self._versions.mark_stale()
            raise ConnectionError(f"Cannot reach DAZ Studio at {self._base}: {e}") from e
        except httpx.TimeoutException as e:
            self._versions.mark_stale()
            raise TimeoutError(f"Request timed out after {self._timeout}s") from e
        except httpx.HTTPError as e:
            self._versions.mark_stale()
            raise ConnectionError(f"HTTP transport failure for DAZ Studio: {e}") from e

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

    async def _with_busy_retry(self, fn, retry_on_busy: bool, max_wait: float, *,
                               retry_server_errors: "bool | Callable[[], bool]" = True):
        """Await *fn* (a zero-arg async callable). See
        :meth:`dazpy.DazClient._with_busy_retry`."""
        if not retry_on_busy:
            waiting = _BUSY_WAIT.get({}).get(id(self))
            if waiting is None:
                return await fn()
            max_wait = waiting
        deadline = time.monotonic() + max_wait
        backoff = 1.0
        while True:
            try:
                return await fn()
            except DazError as exc:
                delay = _retry_delay(exc, backoff, retry_server_errors)
                remaining = deadline - time.monotonic()
                if delay is None or remaining <= 0:
                    raise
                await asyncio.sleep(min(delay, remaining))
                backoff = min(backoff + 1.0, _MAX_BACKOFF)

    async def execute(
        self, script: str, args: object = None, *, retry_on_busy: bool = False, max_wait: float = 30.0,
        timeout: float | None = None,
    ) -> ExecutionResult:
        """Execute a DazScript string. See :meth:`dazpy.DazClient.execute`."""
        payload: dict = {"script": script}
        if args is not None:
            payload["args"] = args

        async def _do():
            resp = await self._post("/execute", payload, timeout=timeout)
            return _map_response(resp, script=script)

        return await self._with_busy_retry(_do, retry_on_busy, max_wait)

    async def execute_file(
        self, script_file: str, args: object = None, *, retry_on_busy: bool = False, max_wait: float = 30.0
    ) -> ExecutionResult:
        """Execute a ``.dsa`` script file. See :meth:`dazpy.DazClient.execute_file`."""
        payload: dict = {"scriptFile": script_file}
        if args is not None:
            payload["args"] = args

        async def _do():
            resp = await self._post("/execute", payload)
            return _map_response(resp)

        return await self._with_busy_retry(_do, retry_on_busy, max_wait)

    async def execute_async_submit(
        self, script: str, args: object = None, *, report_file: str | None = None,
        retry_on_busy: bool = False, max_wait: float = 30.0,
        idempotency_key: str | None = None, correlation_id: str | None = None,
    ) -> str:
        """Submit a script for async execution. See :meth:`dazpy.DazClient.execute_async_submit`."""
        payload: dict = {"script": script}
        if args is not None:
            payload["args"] = args
        if report_file is not None:
            payload["reportFile"] = report_file

        async def _do():
            resp = await self._post("/execute/async", payload, _job_headers(idempotency_key, correlation_id))
            _raise_for_error(resp)
            return resp.json().get("request_id", "")

        return await self._with_busy_retry(_do, retry_on_busy, max_wait)

    async def execute_file_async_submit(
        self, script_file: str, args: object = None, *, report_file: str | None = None,
        retry_on_busy: bool = False, max_wait: float = 30.0,
        idempotency_key: str | None = None, correlation_id: str | None = None,
    ) -> str:
        """Submit a host-side ``.dsa`` file asynchronously.

        See :meth:`dazpy.DazClient.execute_file_async_submit`.
        """
        payload: dict = {"scriptFile": script_file}
        if args is not None:
            payload["args"] = args
        if report_file is not None:
            payload["reportFile"] = report_file

        async def _do():
            resp = await self._post("/execute/async", payload, _job_headers(idempotency_key, correlation_id))
            _raise_for_error(resp)
            return resp.json().get("request_id", "")

        return await self._with_busy_retry(_do, retry_on_busy, max_wait)

    async def execute_batch_async(
        self, operations: list[dict], args: object = None, *, report_file: str | None = None
    ) -> str:
        """Submit multiple operations as one async request. See :meth:`dazpy.DazClient.execute_batch_async`."""
        from ._batch import build_operations_script

        pairs = [(op["body_lines"], op["result_expression"]) for op in operations]
        script = build_operations_script(pairs)
        return await self.execute_async_submit(
            script, args=args, report_file=report_file
        )

    async def register_script(self, name: str, script: str, description: str = "") -> dict:
        """Register or replace a named DazScript on the server."""
        resp = await self._post(
            "/scripts/register",
            {"name": name, "description": description, "script": script},
        )
        _raise_for_error(resp)
        return resp.json()

    async def list_scripts(self) -> list[dict]:
        """Return the registered scripts. See :meth:`dazpy.DazClient.list_scripts`."""
        resp = await self._get("/scripts")
        _raise_for_error(resp)
        return resp.json().get("scripts", [])

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
        payload: dict = {}
        if args is not None:
            payload["args"] = args

        async def _do():
            return _map_response(await self._post(f"/scripts/{name}/execute", payload))

        return await self._with_busy_retry(_do, retry_on_busy, max_wait)

    async def execute_registered_async_submit(
        self, name: str, args: object = None, *, report_file: str | None = None,
        retry_on_busy: bool = False, max_wait: float = 30.0,
        idempotency_key: str | None = None, correlation_id: str | None = None,
    ) -> str:
        """Submit a registered script and return its async request id."""
        payload: dict = {}
        if args is not None:
            payload["args"] = args
        if report_file is not None:
            payload["reportFile"] = report_file

        async def _do():
            resp = await self._post(f"/scripts/{name}/async", payload, _job_headers(idempotency_key, correlation_id))
            _raise_for_error(resp)
            return resp.json().get("request_id", "")

        return await self._with_busy_retry(_do, retry_on_busy, max_wait)

    async def get_request_status(self, request_id: str) -> dict:
        """See :meth:`dazpy.DazClient.get_request_status`."""
        resp = await self._get(f"/requests/{request_id}/status")
        if resp.status_code == 404:
            return {"status": "not_found"}
        _raise_for_error(resp)
        return resp.json()

    async def get_request_result(self, request_id: str, wait: bool = False, wait_timeout: int = 30) -> dict:
        """See :meth:`dazpy.DazClient.get_request_result`."""
        params = {}
        if wait:
            params["wait"] = "true"
            params["timeout"] = str(wait_timeout)
        request_timeout = wait_timeout + 10.0 if wait else None
        resp = await self._get(
            f"/requests/{request_id}/result",
            params=params or None,
            timeout=request_timeout,
        )
        if resp.status_code == 404:
            return {"status": "not_found"}
        _raise_for_error(resp)
        return resp.json()

    async def list_requests(self, status: str | None = None) -> dict:
        """See :meth:`dazpy.DazClient.list_requests`."""
        params = {"status": status} if status else None
        resp = await self._get("/requests", params=params)
        _raise_for_error(resp)
        return resp.json()

    async def cancel_request_detail(self, request_id: str) -> dict:
        """Cancel a script or render request and return the server response."""
        if request_id.startswith("rnd-"):
            resp = await self._post(f"/render/{request_id}/cancel", {})
        else:
            resp = await self._delete(f"/requests/{request_id}")
        _raise_for_error(resp)
        return resp.json()

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
        resp = await self._get(f"/artifacts/{request_id}")
        _raise_for_error(resp)
        return resp.json()

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
        headers = dict(self._headers)
        if byte_range is not None:
            start, end = byte_range
            if start < 0 or (end is not None and end < start):
                raise ValueError(f"invalid byte_range {byte_range!r}")
            headers["Range"] = f"bytes={start}-{'' if end is None else end}"

        await self._check_server_version()
        url = f"{self._base}/artifacts/{request_id}/{artifact_id}"
        try:
            async with self._http.stream(
                "GET", url, headers=headers,
                timeout=self._timeout if timeout is None else timeout,
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
        except httpx.ConnectError as e:
            raise ConnectionError(f"Cannot reach DAZ Studio at {self._base}: {e}") from e
        except httpx.TimeoutException as e:
            raise TimeoutError(f"Request timed out after {self._timeout if timeout is None else timeout}s") from e
        except httpx.HTTPError as e:
            raise ConnectionError(f"HTTP transport failure for DAZ Studio: {e}") from e

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
        resp = await self._get(
            f"/artifacts/{request_id}/{artifact_id}",
            params={"thumbnail": int(size), "format": format},
            timeout=timeout,
        )
        _raise_for_error(resp)
        if dest is None:
            return resp.content
        path = os.fspath(dest)
        with open(path, "wb") as f:
            f.write(resp.content)
        return path

    async def download_artifacts(
        self, request_id: str, dest_dir: "str | os.PathLike[str]"
    ) -> "list[str]":
        """See :meth:`dazpy.DazClient.download_artifacts`."""
        os.makedirs(dest_dir, exist_ok=True)
        written: list[str] = []
        for entry in (await self.list_artifacts(request_id)).get("artifacts", []):
            if not entry.get("available"):
                continue
            aid = str(entry["artifact_id"])
            name = _safe_artifact_filename(entry.get("filename") or "artifact")
            # With a dest, download_artifact returns the written path (str).
            path = await self.download_artifact(
                request_id, aid, os.path.join(os.fspath(dest_dir), f"{aid}_{name}"))
            written.append(cast(str, path))
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
        payload: dict = {"output_path": output_path}
        if width and height:
            payload["width"] = width
            payload["height"] = height
        if camera:
            payload["camera"] = camera
        if engine:
            payload["engine"] = engine
        if iray_samples:
            payload["iray_samples"] = iray_samples
        if reset_morphs:
            payload["reset_morphs"] = True
        if figures is not None:
            payload["figures"] = figures
        elif figure:
            payload["figure"] = figure
            if morphs:
                payload["morphs"] = morphs

        async def _do():
            resp = await self._post("/render", payload, _job_headers(idempotency_key, correlation_id))
            _raise_for_error(resp)
            return resp.json()

        return await self._with_busy_retry(_do, retry_on_busy, max_wait)

    async def render_batch_submit(
        self, variants: list, base: dict | None = None, *, retry_on_busy: bool = False, max_wait: float = 30.0,
        idempotency_key: str | None = None, correlation_id: str | None = None,
    ) -> dict:
        """Submit a batch render job. See :meth:`dazpy.DazClient.render_batch_submit`."""
        payload: dict = {"variants": variants}
        if base:
            payload["base"] = base

        async def _do():
            resp = await self._post("/render/batch", payload, _job_headers(idempotency_key, correlation_id))
            _raise_for_error(resp)
            return resp.json()

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
        payload: dict = {
            "output_path": output_path,
            "start_frame": start_frame,
            "end_frame": end_frame,
            "frame_padding": frame_padding,
        }
        if width and height:
            payload["width"] = width
            payload["height"] = height
        if camera:
            payload["camera"] = camera
        if engine:
            payload["engine"] = engine

        async def _do():
            resp = await self._post("/render/animation", payload, _job_headers(idempotency_key, correlation_id))
            _raise_for_error(resp)
            return resp.json()

        return await self._with_busy_retry(_do, retry_on_busy, max_wait)

    async def cancel_render(self, request_id: str) -> bool:
        """See :meth:`dazpy.DazClient.cancel_render`."""
        if not request_id.startswith("rnd-"):
            return False
        return await self.cancel_request(request_id)

    async def stream_render_progress(self, request_id: str, stream_timeout: float = 305.0):
        """Async-iterate ``(event_type, data)`` SSE pairs from the render progress stream.

        Unlike :meth:`dazpy.DazClient.stream_render_progress` (which returns a
        raw ``requests.Response`` for the caller to parse), this yields
        already-parsed ``(event_type, data_dict)`` tuples, since ``httpx``
        streaming responses are only valid within their ``async with`` block.
        Yields nothing if the stream cannot be opened.
        """
        try:
            async with self._http.stream(
                "GET",
                f"{self._base}/render/{request_id}/progress",
                headers=self._headers,
                timeout=stream_timeout,
            ) as resp:
                _raise_for_error(resp)
                async for event_type, data in _aiter_sse_events(resp):
                    yield event_type, data
        except httpx.ConnectError as exc:
            raise ConnectionError(f"Cannot reach DAZ Studio at {self._base}: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise TimeoutError(f"Request timed out after {stream_timeout or self._timeout}s") from exc
        except httpx.HTTPError as exc:
            raise ConnectionError(f"HTTP transport failure for DAZ Studio: {exc}") from exc

    async def stream_scene_events(
        self,
        categories: "list[str] | None" = None,
        stream_timeout: "float | None" = None,
    ):
        """Async-iterate ``(event_type, data)`` SSE pairs from ``GET /scene/events``.

        See :meth:`stream_render_progress` for why this yields parsed tuples
        rather than a raw response object.
        """
        try:
            params = {"filter": ",".join(categories)} if categories else None
            async with self._http.stream(
                "GET",
                f"{self._base}/scene/events",
                headers=self._headers,
                params=params,
                timeout=stream_timeout,
            ) as resp:
                _raise_for_error(resp)
                async for event_type, data in _aiter_sse_events(resp):
                    yield event_type, data
        except httpx.ConnectError as exc:
            raise ConnectionError(f"Cannot reach DAZ Studio at {self._base}: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise TimeoutError(f"Request timed out after {stream_timeout or self._timeout}s") from exc
        except httpx.HTTPError as exc:
            raise ConnectionError(f"HTTP transport failure for DAZ Studio: {exc}") from exc

    # ── Server health ─────────────────────────────────────────────────────────

    async def status(self) -> dict:
        """See :meth:`dazpy.DazClient.status`."""
        resp = await self._get("/status")
        _raise_for_error(resp)
        return resp.json()

    async def health(self) -> dict:
        """See :meth:`dazpy.DazClient.health`."""
        resp = await self._get("/health")
        _raise_for_error(resp)
        return resp.json()

    async def metrics(self) -> dict:
        """See :meth:`dazpy.DazClient.metrics`."""
        resp = await self._get("/metrics")
        _raise_for_error(resp)
        return resp.json()

    async def capabilities(self) -> dict:
        """See :meth:`dazpy.DazClient.capabilities`."""
        resp = await self._get("/capabilities")
        _raise_for_error(resp)
        return resp.json()


async def _aiter_sse_events(resp: "httpx.Response"):
    """Yield ``(event_type, data_dict)`` pairs from a streaming httpx SSE response."""
    event_type = "message"
    data_lines: list[str] = []

    async for line in resp.aiter_lines():
        line = line.rstrip("\n")
        if not line:
            if data_lines:
                data_str = "\n".join(data_lines)
                try:
                    yield event_type, json.loads(data_str)
                except json.JSONDecodeError:
                    yield event_type, {"_raw": data_str}
            event_type = "message"
            data_lines = []
        elif line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())

    # A closed stream is also an event boundary. Servers normally terminate
    # SSE events with a blank line, but do not silently drop a complete final
    # event if the connection closes immediately after its data field.
    if data_lines:
        data_str = "\n".join(data_lines)
        try:
            yield event_type, json.loads(data_str)
        except json.JSONDecodeError:
            yield event_type, {"_raw": data_str}
