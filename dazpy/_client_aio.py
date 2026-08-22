from __future__ import annotations

import asyncio
import json

try:
    import httpx
except ImportError as e:  # pragma: no cover - exercised via test_client_aio_import_error
    raise ImportError(
        "dazpy.aio requires the 'httpx' package. Install it with `pip install dazpy[aio]` "
        "or `pip install httpx`."
    ) from e

from .exceptions import (
    AuthenticationError,
    ConnectionError,
    DazBusyError,
    TimeoutError,
)
from ._result import ExecutionResult
from ._client import _DEFAULT_HOST, _DEFAULT_PORT, _load_token, _raise_for_error, _map_response


class AsyncDazClient:
    """Async HTTP client for the DAZ Studio Script Server, backed by ``httpx``.

    Mirrors :class:`dazpy.DazClient`'s API surface as ``async def`` methods.
    Requires the optional ``httpx`` dependency (``pip install dazpy[aio]``).

    Can be used as an async context manager to ensure the underlying
    connection pool is closed::

        async with AsyncDazClient() as client:
            result = await client.execute("1 + 1;")

    Or managed manually via :meth:`aclose`.
    """

    def __init__(
        self,
        host: str = _DEFAULT_HOST,
        port: int = _DEFAULT_PORT,
        token: str | None = None,
        timeout: float = 30.0,
    ):
        self._base = f"http://{host}:{port}"
        self._token = token if token is not None else _load_token()
        self._timeout = timeout
        self._http = httpx.AsyncClient(timeout=timeout)

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

    async def _post(self, path: str, payload: dict) -> "httpx.Response":
        try:
            return await self._http.post(f"{self._base}{path}", json=payload, headers=self._headers)
        except httpx.ConnectError as e:
            raise ConnectionError(f"Cannot reach DAZ Studio at {self._base}: {e}") from e
        except httpx.TimeoutException as e:
            raise TimeoutError(f"Request timed out after {self._timeout}s") from e

    async def _get(self, path: str, params: dict | None = None) -> "httpx.Response":
        try:
            return await self._http.get(f"{self._base}{path}", headers=self._headers, params=params)
        except httpx.ConnectError as e:
            raise ConnectionError(f"Cannot reach DAZ Studio at {self._base}: {e}") from e
        except httpx.TimeoutException as e:
            raise TimeoutError(f"Request timed out after {self._timeout}s") from e

    async def _with_busy_retry(self, fn, retry_on_busy: bool, max_wait: float):
        """Await *fn* (a zero-arg async callable), retrying on DazBusyError
        while *retry_on_busy* is true, up to *max_wait* seconds total."""
        if not retry_on_busy:
            return await fn()
        deadline = asyncio.get_event_loop().time() + max_wait
        backoff = 1.0
        while True:
            try:
                return await fn()
            except DazBusyError:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    raise
                await asyncio.sleep(min(backoff, remaining))
                backoff = min(backoff + 1.0, 5.0)

    async def execute(
        self, script: str, args: object = None, *, retry_on_busy: bool = False, max_wait: float = 30.0
    ) -> ExecutionResult:
        """Execute a DazScript string. See :meth:`dazpy.DazClient.execute`."""
        payload: dict = {"script": script}
        if args is not None:
            payload["args"] = args

        async def _do():
            resp = await self._post("/execute", payload)
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
        self, script: str, args: object = None, *, retry_on_busy: bool = False, max_wait: float = 30.0
    ) -> str:
        """Submit a script for async execution. See :meth:`dazpy.DazClient.execute_async_submit`."""
        payload: dict = {"script": script}
        if args is not None:
            payload["args"] = args

        async def _do():
            resp = await self._post("/execute/async", payload)
            _raise_for_error(resp)
            return resp.json().get("request_id", "")

        return await self._with_busy_retry(_do, retry_on_busy, max_wait)

    async def execute_file_async_submit(
        self, script_file: str, args: object = None, *, retry_on_busy: bool = False, max_wait: float = 30.0
    ) -> str:
        """Submit a host-side ``.dsa`` file asynchronously.

        See :meth:`dazpy.DazClient.execute_file_async_submit`.
        """
        payload: dict = {"scriptFile": script_file}
        if args is not None:
            payload["args"] = args

        async def _do():
            resp = await self._post("/execute/async", payload)
            _raise_for_error(resp)
            return resp.json().get("request_id", "")

        return await self._with_busy_retry(_do, retry_on_busy, max_wait)

    async def execute_batch_async(self, operations: list[dict], args: object = None) -> str:
        """Submit multiple operations as one async request. See :meth:`dazpy.DazClient.execute_batch_async`."""
        from ._batch import build_operations_script

        pairs = [(op["body_lines"], op["result_expression"]) for op in operations]
        script = build_operations_script(pairs)
        return await self.execute_async_submit(script, args=args)

    async def get_request_status(self, request_id: str) -> dict:
        """See :meth:`dazpy.DazClient.get_request_status`."""
        resp = await self._get(f"/requests/{request_id}/status")
        if resp.status_code == 404:
            return {"status": "not_found"}
        return resp.json()

    async def get_request_result(self, request_id: str, wait: bool = False, wait_timeout: int = 30) -> dict:
        """See :meth:`dazpy.DazClient.get_request_result`."""
        params = {}
        if wait:
            params["wait"] = "true"
            params["timeout"] = str(wait_timeout)
        resp = await self._get(f"/requests/{request_id}/result", params=params or None)
        if resp.status_code == 404:
            return {"status": "not_found"}
        return resp.json()

    async def list_requests(self, status: str | None = None) -> dict:
        """See :meth:`dazpy.DazClient.list_requests`."""
        params = {"status": status} if status else None
        resp = await self._get("/requests", params=params)
        if resp.status_code in (401, 403):
            raise AuthenticationError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    async def cancel_request(self, request_id: str) -> bool:
        """See :meth:`dazpy.DazClient.cancel_request`."""
        try:
            resp = await self._http.delete(f"{self._base}/requests/{request_id}", headers=self._headers)
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

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
            resp = await self._post("/render", payload)
            _raise_for_error(resp)
            return resp.json()

        return await self._with_busy_retry(_do, retry_on_busy, max_wait)

    async def render_batch_submit(
        self, variants: list, base: dict | None = None, *, retry_on_busy: bool = False, max_wait: float = 30.0
    ) -> dict:
        """Submit a batch render job. See :meth:`dazpy.DazClient.render_batch_submit`."""
        payload: dict = {"variants": variants}
        if base:
            payload["base"] = base

        async def _do():
            resp = await self._post("/render/batch", payload)
            _raise_for_error(resp)
            return resp.json()

        return await self._with_busy_retry(_do, retry_on_busy, max_wait)

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
            resp = await self._post("/render/animation", payload)
            _raise_for_error(resp)
            return resp.json()

        return await self._with_busy_retry(_do, retry_on_busy, max_wait)

    async def cancel_render(self, request_id: str) -> bool:
        """See :meth:`dazpy.DazClient.cancel_render`."""
        try:
            resp = await self._http.post(f"{self._base}/render/{request_id}/cancel", headers=self._headers)
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

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
                if resp.status_code != 200:
                    return
                async for event_type, data in _aiter_sse_events(resp):
                    yield event_type, data
        except httpx.HTTPError:
            return

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
                if resp.status_code != 200:
                    return
                async for event_type, data in _aiter_sse_events(resp):
                    yield event_type, data
        except httpx.HTTPError:
            return

    # ── USD export ────────────────────────────────────────────────────────────

    async def export_usd_submit(
        self,
        output_path: str,
        *,
        include_geometry: bool = True,
        include_materials: bool = True,
        include_skeleton: bool = False,
        include_morphs: bool = False,
        include_lights: bool = False,
        include_camera: bool = False,
    ) -> dict:
        """See :meth:`dazpy.DazClient.export_usd_submit`."""
        payload = {
            "outputPath": output_path,
            "includeGeometry": include_geometry,
            "includeMaterials": include_materials,
            "includeSkeleton": include_skeleton,
            "includeMorphs": include_morphs,
            "includeLights": include_lights,
            "includeCamera": include_camera,
        }
        resp = await self._post("/export/usd", payload)
        if resp.status_code in (401, 403):
            raise AuthenticationError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    async def get_usd_export_status(self, job_id: str) -> dict:
        """See :meth:`dazpy.DazClient.get_usd_export_status`."""
        resp = await self._get(f"/export/usd/{job_id}")
        if resp.status_code in (401, 403):
            raise AuthenticationError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        if resp.status_code == 404:
            return {"job_id": job_id, "status": "not_found"}
        return resp.json()

    # ── Server health ─────────────────────────────────────────────────────────

    async def status(self) -> dict:
        """See :meth:`dazpy.DazClient.status`."""
        resp = await self._get("/status")
        if resp.status_code in (401, 403):
            raise AuthenticationError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    async def health(self) -> dict:
        """See :meth:`dazpy.DazClient.health`."""
        resp = await self._get("/health")
        if resp.status_code in (401, 403):
            raise AuthenticationError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    async def metrics(self) -> dict:
        """See :meth:`dazpy.DazClient.metrics`."""
        resp = await self._get("/metrics")
        if resp.status_code in (401, 403):
            raise AuthenticationError(f"HTTP {resp.status_code}: {resp.text[:200]}")
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
