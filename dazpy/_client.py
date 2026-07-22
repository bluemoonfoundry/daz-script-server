from __future__ import annotations

import os
import re

import requests as _requests

from .exceptions import (
    AuthenticationError,
    ConcurrencyLimitError,
    ConnectionError,
    DazBusyError,
    ScriptRuntimeError,
    ScriptSyntaxError,
    StudioBusyError,
    TimeoutError,
)
from ._result import ExecutionResult


_TOKEN_FILE = os.path.expanduser("~/.daz3d/dazscriptserver_token.txt")
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 18811


def _load_token() -> str:
    if os.path.exists(_TOKEN_FILE):
        with open(_TOKEN_FILE) as f:
            return f.read().strip()
    return ""


def _parse_retry_after(resp: _requests.Response) -> float:
    raw = resp.headers.get("Retry-After", "")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 2.0


def _raise_for_error(resp: _requests.Response) -> None:
    """Raise a typed exception for authentication or server-busy responses.

    Leaves 2xx responses (and DazScript's own success:false runtime/syntax
    errors, which use HTTP 200) for the caller to handle.
    """
    status = resp.status_code
    if status == 401 or status == 403:
        raise AuthenticationError(f"HTTP {status}: {resp.text[:200]}")
    if status < 400:
        return
    data = resp.json()
    error_code = data.get("error_code", "")
    error_msg = data.get("error") or f"HTTP {status}"
    retry_after = _parse_retry_after(resp)
    if error_code == "STUDIO_BUSY":
        raise StudioBusyError(error_msg, reason=data.get("detail", error_msg), retry_after=retry_after)
    if error_code == "CONCURRENT_LIMIT_EXCEEDED":
        raise ConcurrencyLimitError(error_msg, reason=error_msg, retry_after=retry_after)


def _map_response(resp: _requests.Response, script: str = "") -> ExecutionResult:
    _raise_for_error(resp)

    data = resp.json()
    request_id = data.get("request_id", "")

    if not data.get("success", True):
        error_msg = data.get("error", "Script failed")
        output = data.get("output", [])
        # SyntaxError comes from the parser; runtime errors (TypeError, ReferenceError,
        # Error, etc.) also include "Line N:" but never say "SyntaxError" explicitly.
        if "SyntaxError" in error_msg:
            raise ScriptSyntaxError(error_msg, script=script, request_id=request_id, output=output)
        raise ScriptRuntimeError(error_msg, script=script, request_id=request_id, output=output)

    return ExecutionResult(
        value=data.get("result"),
        output=data.get("output", []),
        request_id=request_id,
        success=True,
        error="",
        duration_ms=data.get("duration_ms", 0.0),
    )


class DazClient:
    """HTTP client for the DAZ Studio Script Server.

    Handles authentication, request serialisation, and response mapping for
    all server endpoints.  The token is loaded automatically from
    ``~/.daz3d/dazscriptserver_token.txt`` when *token* is ``None``.

    Args:
        host: Hostname or IP address of the Script Server.
        port: Listening port of the Script Server.
        token: API token.  Pass an empty string to disable authentication or
            ``None`` to auto-load from the default token file.
        timeout: Per-request HTTP timeout in seconds.

    Example::

        client = DazClient()                          # default 127.0.0.1:18811
        client = DazClient(token="my-secret-token")   # explicit token
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

    @property
    def _headers(self) -> dict:
        h = {}
        if self._token:
            h["X-API-Token"] = self._token
        return h

    def _post(self, path: str, payload: dict) -> _requests.Response:
        try:
            return _requests.post(
                f"{self._base}{path}",
                json=payload,
                headers=self._headers,
                timeout=self._timeout,
            )
        except _requests.exceptions.ConnectionError as e:
            raise ConnectionError(f"Cannot reach DAZ Studio at {self._base}: {e}") from e
        except _requests.exceptions.Timeout as e:
            raise TimeoutError(f"Request timed out after {self._timeout}s") from e

    def _get(self, path: str, params: dict | None = None) -> _requests.Response:
        try:
            return _requests.get(
                f"{self._base}{path}",
                headers=self._headers,
                params=params,
                timeout=self._timeout,
            )
        except _requests.exceptions.ConnectionError as e:
            raise ConnectionError(f"Cannot reach DAZ Studio at {self._base}: {e}") from e
        except _requests.exceptions.Timeout as e:
            raise TimeoutError(f"Request timed out after {self._timeout}s") from e

    def execute(self, script: str, args: object = None) -> ExecutionResult:
        """Execute a DazScript string synchronously.

        Args:
            script: DazScript source code to execute.
            args: Optional value passed into the script as ``getArguments()[0]``.
                Must be JSON-serialisable.

        Returns:
            The execution result containing the script return value and any
            console output.

        Raises:
            ConnectionError: If the server cannot be reached.
            AuthenticationError: If the token is invalid or the IP is blocked.
            ScriptSyntaxError: If the script contains a parse error.
            ScriptRuntimeError: If the script raises a runtime exception.
            TimeoutError: If the request exceeds *timeout* seconds.
        """
        payload: dict = {"script": script}
        if args is not None:
            payload["args"] = args
        resp = self._post("/execute", payload)
        return _map_response(resp, script=script)

    def execute_file(self, script_file: str, args: object = None) -> ExecutionResult:
        """Execute a ``.dsa`` script file that resides on the DAZ Studio host.

        Args:
            script_file: Absolute path to the ``.dsa`` file on the server host.
            args: Optional argument passed to the script.

        Returns:
            The execution result.

        Raises:
            ConnectionError: If the server cannot be reached.
            AuthenticationError: On auth failure.
            ScriptSyntaxError: On parse error.
            ScriptRuntimeError: On runtime error.
            TimeoutError: On HTTP timeout.
        """
        payload: dict = {"scriptFile": script_file}
        if args is not None:
            payload["args"] = args
        resp = self._post("/execute", payload)
        return _map_response(resp)

    def execute_async_submit(self, script: str, args: object = None) -> str:
        """Submit a script for asynchronous execution and return immediately.

        Args:
            script: DazScript source code.
            args: Optional argument for the script.

        Returns:
            The server-assigned ``request_id`` string.  Use it with
            :meth:`get_request_status` or :meth:`get_request_result` to poll
            for the outcome.

        Raises:
            ConnectionError: If the server cannot be reached.
            AuthenticationError: On auth failure.
        """
        payload: dict = {"script": script}
        if args is not None:
            payload["args"] = args
        resp = self._post("/execute/async", payload)
        if resp.status_code in (401, 403):
            raise AuthenticationError(f"HTTP {resp.status_code}")
        return resp.json().get("request_id", "")

    def get_request_status(self, request_id: str) -> dict:
        """Return the current status of an async request.

        Args:
            request_id: The ID returned by :meth:`execute_async_submit`.

        Returns:
            A dict with at least a ``"status"`` key.  Possible values:
            ``"queued"``, ``"running"``, ``"completed"``, ``"failed"``,
            ``"cancelled"``, or ``"not_found"``.
        """
        resp = self._get(f"/requests/{request_id}/status")
        if resp.status_code == 404:
            return {"status": "not_found"}
        return resp.json()

    def get_request_result(self, request_id: str, wait: bool = False, wait_timeout: int = 30) -> dict:
        """Fetch the result of a completed async request.

        Args:
            request_id: The ID returned by :meth:`execute_async_submit`.
            wait: If ``True``, the server will long-poll until the request
                completes or *wait_timeout* is reached.
            wait_timeout: Maximum number of seconds the server should wait
                before returning (only relevant when *wait* is ``True``).

        Returns:
            A dict containing ``success``, ``result``, ``output``, ``error``,
            ``duration_ms``, and ``status`` keys.
        """
        params = {}
        if wait:
            params["wait"] = "true"
            params["timeout"] = str(wait_timeout)
        resp = self._get(f"/requests/{request_id}/result", params=params or None)
        if resp.status_code == 404:
            return {"status": "not_found"}
        return resp.json()

    def list_requests(self, status: str | None = None) -> dict:
        """List all tracked async requests (script and render) with their status.

        Args:
            status: Optional filter, one of ``"queued"``, ``"running"``,
                ``"completed"``, ``"failed"``, ``"cancelled"``. Omit to list
                requests in every status.

        Returns:
            A dict with a ``"requests"`` list (each item has ``request_id``,
            ``status``, ``progress``, ``submitted_at``) plus ``total`` and a
            per-status count for every status value.
        """
        params = {"status": status} if status else None
        resp = self._get("/requests", params=params)
        if resp.status_code in (401, 403):
            raise AuthenticationError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def cancel_request(self, request_id: str) -> bool:
        """Cancel a queued or running async request.

        Args:
            request_id: The ID returned by :meth:`execute_async_submit`.

        Returns:
            ``True`` if the server confirmed cancellation, ``False`` otherwise.
        """
        try:
            resp = _requests.delete(
                f"{self._base}/requests/{request_id}",
                headers=self._headers,
                timeout=self._timeout,
            )
            return resp.status_code == 200
        except _requests.exceptions.RequestException:
            return False

    # ── Render ────────────────────────────────────────────────────────────────

    def render_submit(
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
    ) -> dict:
        """Submit a render job and return immediately.

        Args:
            output_path: Absolute path on the DAZ Studio host to write the image.
            figure: Label of the figure to configure morphs on.
            morphs: Morph values to apply ``{label: value}``.
            figures: List of ``{"name": ..., "morphs": {...}}`` dicts for multi-figure scenes.
            width: Image width in pixels (must be paired with *height*).
            height: Image height in pixels (must be paired with *width*).
            camera: Camera label to render from.
            engine: Render engine (``"iray"``, ``"filament"``).
            iray_samples: iRay sample count (0 = use scene default).
            reset_morphs: If ``True``, reset all morphs to defaults before applying.

        Returns:
            A dict with ``request_id``, ``status`` (``"queued"``), and
            ``submitted_at`` keys.

        Raises:
            ConnectionError: If the server cannot be reached.
            AuthenticationError: On HTTP 401/403.
        """
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
        resp = self._post("/render", payload)
        if resp.status_code in (401, 403):
            raise AuthenticationError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def render_batch_submit(self, variants: list, base: dict | None = None) -> dict:
        """Submit a batch render job and return immediately.

        Args:
            variants: List of variant dicts, each with at least ``output_path``.
                Supported keys mirror :meth:`render_submit` optional fields.
            base: Optional shared defaults applied to all variants.

        Returns:
            A dict with ``batch_id``, ``request_ids`` (list), and ``total`` keys.

        Raises:
            ConnectionError: If the server cannot be reached.
            AuthenticationError: On HTTP 401/403.
        """
        payload: dict = {"variants": variants}
        if base:
            payload["base"] = base
        resp = self._post("/render/batch", payload)
        if resp.status_code in (401, 403):
            raise AuthenticationError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def render_animation_submit(
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
    ) -> dict:
        """Submit an animation render job spanning a frame range and return immediately.

        Renders each frame in ``[start_frame, end_frame]`` to a separate file,
        as a single trackable async request (mirrors :meth:`render_submit`'s
        request-tracking shape, not :meth:`render_batch_submit`'s fan-out).

        Args:
            output_path: Output path pattern containing the literal token
                ``"{frame}"``, e.g. ``r"C:\\tmp\\anim\\frame_{frame}.png"``.
                The token is replaced with the frame number, zero-padded to
                *frame_padding* digits.
            start_frame: First frame to render (inclusive).
            end_frame: Last frame to render (inclusive).
            frame_padding: Zero-padding width for the frame number (default ``4``).
            width: Image width in pixels (must be paired with *height*).
            height: Image height in pixels (must be paired with *width*).
            camera: Camera label to render from.
            engine: Render engine (``"iray"``, ``"filament"``).

        Returns:
            A dict with ``request_id``, ``status`` (``"queued"``), and
            ``submitted_at`` keys.

        Raises:
            ConnectionError: If the server cannot be reached.
            AuthenticationError: On HTTP 401/403.
        """
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
        resp = self._post("/render/animation", payload)
        if resp.status_code in (401, 403):
            raise AuthenticationError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def cancel_render(self, request_id: str) -> bool:
        """Cancel a queued or running render job.

        Args:
            request_id: The ``request_id`` from :meth:`render_submit` or a
                :class:`~dazpy._render_api.RenderResult` with ``wait=False``.

        Returns:
            ``True`` if the server confirmed cancellation, ``False`` otherwise
            (already finished, not found, or connection error).
        """
        try:
            resp = _requests.post(
                f"{self._base}/render/{request_id}/cancel",
                headers=self._headers,
                timeout=self._timeout,
            )
            return resp.status_code == 200
        except _requests.exceptions.RequestException:
            return False

    def stream_render_progress(self, request_id: str, stream_timeout: float = 305.0) -> "object | None":
        """Open the SSE progress stream for a render request.

        Returns a streaming :class:`requests.Response` on success, or ``None``
        if the endpoint is unavailable.  Callers must close the response when done.
        """
        try:
            resp = _requests.get(
                f"{self._base}/render/{request_id}/progress",
                headers=self._headers,
                stream=True,
                timeout=stream_timeout,
            )
            return resp if resp.status_code == 200 else None
        except _requests.exceptions.RequestException:
            return None

    def stream_scene_events(
        self,
        categories: "list[str] | None" = None,
        stream_timeout: "float | None" = None,
    ) -> "object | None":
        """Open the SSE stream for general scene-change events (GET /scene/events).

        Args:
            categories: Optional subset of event categories to subscribe to
                (``"node"``, ``"skeleton"``, ``"light"``, ``"camera"``,
                ``"selection"``, ``"scene"``, ``"time"``, ``"render"``).
                ``None`` (default) subscribes to all categories.
            stream_timeout: Socket timeout in seconds. ``None`` (default)
                waits indefinitely — the server sends a keepalive comment
                every 15 seconds, so the connection never idles out.

        Returns:
            A streaming :class:`requests.Response` on success, or ``None``
            if the endpoint is unavailable. Callers must close the response
            when done (e.g. via a ``with`` statement).
        """
        try:
            params = {"filter": ",".join(categories)} if categories else None
            resp = _requests.get(
                f"{self._base}/scene/events",
                headers=self._headers,
                params=params,
                stream=True,
                timeout=stream_timeout,
            )
            return resp if resp.status_code == 200 else None
        except _requests.exceptions.RequestException:
            return None

    # ── USD export ────────────────────────────────────────────────────────────

    def export_usd_submit(
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
        """Submit a USD export job and return immediately.

        Args:
            output_path: Absolute path on the DAZ Studio host where the
                ``.usda`` file should be written.
            include_geometry: Export mesh geometry (default ``True``).
            include_materials: Export PBR material prims (default ``True``).
            include_skeleton: Export UsdSkel armature and skin weights.
            include_morphs: Export active morphs as UsdSkelBlendShape prims.
            include_lights: Export scene lights using UsdLux prims.
            include_camera: Export the active render camera as UsdGeomCamera.

        Returns:
            A dict with ``job_id``, ``status`` (``"queued"``), and
            ``submittedAt`` keys.

        Raises:
            ConnectionError: If the server cannot be reached.
            AuthenticationError: On HTTP 401/403.
        """
        payload = {
            "outputPath": output_path,
            "includeGeometry": include_geometry,
            "includeMaterials": include_materials,
            "includeSkeleton": include_skeleton,
            "includeMorphs": include_morphs,
            "includeLights": include_lights,
            "includeCamera": include_camera,
        }
        resp = self._post("/export/usd", payload)
        if resp.status_code in (401, 403):
            raise AuthenticationError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def get_usd_export_status(self, job_id: str) -> dict:
        """Poll the status of a USD export job.

        Args:
            job_id: The ID returned by :meth:`export_usd_submit`.

        Returns:
            A dict with ``job_id``, ``status``, and (on completion)
            ``outputPath`` or ``error`` keys.

        Raises:
            ConnectionError: If the server cannot be reached.
            AuthenticationError: On HTTP 401/403.
        """
        resp = self._get(f"/export/usd/{job_id}")
        if resp.status_code in (401, 403):
            raise AuthenticationError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        if resp.status_code == 404:
            return {"job_id": job_id, "status": "not_found"}
        return resp.json()

    # ── Server health ─────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Return the server status dict from ``GET /status``.

        Raises:
            AuthenticationError: On HTTP 401/403.
        """
        resp = self._get("/status")
        if resp.status_code in (401, 403):
            raise AuthenticationError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def health(self) -> dict:
        """Return the health check dict from ``GET /health``.

        Raises:
            AuthenticationError: On HTTP 401/403.
        """
        resp = self._get("/health")
        if resp.status_code in (401, 403):
            raise AuthenticationError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def metrics(self) -> dict:
        """Return the metrics dict from ``GET /metrics``.

        Raises:
            AuthenticationError: On HTTP 401/403.
        """
        resp = self._get("/metrics")
        if resp.status_code in (401, 403):
            raise AuthenticationError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()
