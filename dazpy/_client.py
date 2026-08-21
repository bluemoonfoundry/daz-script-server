from __future__ import annotations

import os
import re
import time

import requests as _requests

from .exceptions import (
    AuthenticationError,
    ConcurrencyLimitError,
    ConnectionError,
    DazError,
    DazBusyError,
    ScriptRuntimeError,
    ScriptSyntaxError,
    StudioBusyError,
    ServerResponseError,
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
    try:
        parsed = resp.json()
    except (TypeError, ValueError):
        parsed = {}
    data = parsed if isinstance(parsed, dict) else {}
    error_code = data.get("error_code", "")
    error_msg = data.get("error") or resp.text[:200] or f"HTTP {status}"
    retry_after = _parse_retry_after(resp)
    if error_code == "STUDIO_BUSY":
        raise StudioBusyError(error_msg, reason=data.get("detail", error_msg), retry_after=retry_after)
    if error_code == "CONCURRENT_LIMIT_EXCEEDED":
        raise ConcurrencyLimitError(error_msg, reason=error_msg, retry_after=retry_after)
    raise ServerResponseError(
        error_msg,
        status_code=status,
        error_code=error_code,
        detail=str(data.get("detail", "")),
    )


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

    Requests are issued through a pooled ``requests.Session`` for connection
    reuse. Call :meth:`close` when done, or use as a context manager::

        client = DazClient()                          # default 127.0.0.1:18811
        client = DazClient(token="my-secret-token")   # explicit token

        with DazClient() as client:
            result = client.execute("1 + 1;")
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
        self._session = _requests.Session()

    def __enter__(self) -> "DazClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying ``requests.Session``'s pooled connections."""
        self._session.close()

    @property
    def _headers(self) -> dict:
        h = {}
        if self._token:
            h["X-API-Token"] = self._token
        return h

    def _post(self, path: str, payload: dict) -> _requests.Response:
        try:
            return self._session.post(
                f"{self._base}{path}",
                json=payload,
                headers=self._headers,
                timeout=self._timeout,
            )
        except _requests.exceptions.ConnectionError as e:
            raise ConnectionError(f"Cannot reach DAZ Studio at {self._base}: {e}") from e
        except _requests.exceptions.Timeout as e:
            raise TimeoutError(f"Request timed out after {self._timeout}s") from e
        except _requests.exceptions.RequestException as e:
            raise ConnectionError(f"HTTP transport failure for DAZ Studio: {e}") from e

    def _get(
        self, path: str, params: dict | None = None, timeout: float | None = None
    ) -> _requests.Response:
        try:
            return self._session.get(
                f"{self._base}{path}",
                headers=self._headers,
                params=params,
                timeout=self._timeout if timeout is None else timeout,
            )
        except _requests.exceptions.ConnectionError as e:
            raise ConnectionError(f"Cannot reach DAZ Studio at {self._base}: {e}") from e
        except _requests.exceptions.Timeout as e:
            raise TimeoutError(f"Request timed out after {self._timeout}s") from e
        except _requests.exceptions.RequestException as e:
            raise ConnectionError(f"HTTP transport failure for DAZ Studio: {e}") from e

    def _delete(self, path: str) -> _requests.Response:
        try:
            return self._session.delete(
                f"{self._base}{path}", headers=self._headers, timeout=self._timeout
            )
        except _requests.exceptions.ConnectionError as e:
            raise ConnectionError(f"Cannot reach DAZ Studio at {self._base}: {e}") from e
        except _requests.exceptions.Timeout as e:
            raise TimeoutError(f"Request timed out after {self._timeout}s") from e
        except _requests.exceptions.RequestException as e:
            raise ConnectionError(f"HTTP transport failure for DAZ Studio: {e}") from e

    def _with_busy_retry(self, fn, retry_on_busy: bool, max_wait: float):
        """Run *fn* (a zero-arg callable), retrying on DazBusyError while
        *retry_on_busy* is true, up to *max_wait* seconds total."""
        if not retry_on_busy:
            return fn()
        deadline = time.monotonic() + max_wait
        backoff = 1.0
        while True:
            try:
                return fn()
            except DazBusyError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise
                time.sleep(min(backoff, remaining))
                backoff = min(backoff + 1.0, 5.0)

    def execute(
        self, script: str, args: object = None, *, retry_on_busy: bool = False, max_wait: float = 30.0
    ) -> ExecutionResult:
        """Execute a DazScript string synchronously.

        Args:
            script: DazScript source code to execute.
            args: Optional value passed into the script as ``getArguments()[0]``.
                Must be JSON-serialisable.
            retry_on_busy: If ``True``, transparently retry with backoff when
                the server reports ``StudioBusyError``/``ConcurrencyLimitError``,
                instead of raising immediately.
            max_wait: Maximum total seconds to retry when *retry_on_busy* is
                ``True``, before re-raising the busy error.

        Returns:
            The execution result containing the script return value and any
            console output.

        Raises:
            ConnectionError: If the server cannot be reached.
            AuthenticationError: If the token is invalid or the IP is blocked.
            ScriptSyntaxError: If the script contains a parse error.
            ScriptRuntimeError: If the script raises a runtime exception.
            StudioBusyError: If DAZ Studio's main thread is busy and
                *retry_on_busy* is ``False`` or *max_wait* is exceeded.
            ConcurrencyLimitError: If too many concurrent requests are in
                flight and *retry_on_busy* is ``False`` or *max_wait* is
                exceeded.
            TimeoutError: If the request exceeds *timeout* seconds.
        """
        payload: dict = {"script": script}
        if args is not None:
            payload["args"] = args

        def _do():
            resp = self._post("/execute", payload)
            return _map_response(resp, script=script)

        return self._with_busy_retry(_do, retry_on_busy, max_wait)

    def execute_file(
        self, script_file: str, args: object = None, *, retry_on_busy: bool = False, max_wait: float = 30.0
    ) -> ExecutionResult:
        """Execute a ``.dsa`` script file that resides on the DAZ Studio host.

        Args:
            script_file: Absolute path to the ``.dsa`` file on the server host.
            args: Optional argument passed to the script.
            retry_on_busy: If ``True``, transparently retry with backoff when
                the server reports ``StudioBusyError``/``ConcurrencyLimitError``,
                instead of raising immediately.
            max_wait: Maximum total seconds to retry when *retry_on_busy* is
                ``True``, before re-raising the busy error.

        Returns:
            The execution result.

        Raises:
            ConnectionError: If the server cannot be reached.
            AuthenticationError: On auth failure.
            ScriptSyntaxError: On parse error.
            ScriptRuntimeError: On runtime error.
            StudioBusyError: If DAZ Studio's main thread is busy and
                *retry_on_busy* is ``False`` or *max_wait* is exceeded.
            ConcurrencyLimitError: If too many concurrent requests are in
                flight and *retry_on_busy* is ``False`` or *max_wait* is
                exceeded.
            TimeoutError: On HTTP timeout.
        """
        payload: dict = {"scriptFile": script_file}
        if args is not None:
            payload["args"] = args

        def _do():
            resp = self._post("/execute", payload)
            return _map_response(resp)

        return self._with_busy_retry(_do, retry_on_busy, max_wait)

    def execute_async_submit(
        self, script: str, args: object = None, *, report_file: str | None = None,
        retry_on_busy: bool = False, max_wait: float = 30.0
    ) -> str:
        """Submit a script for asynchronous execution and return immediately.

        Args:
            script: DazScript source code.
            args: Optional argument for the script.
            report_file: Optional host-side JSONL file used by the script to
                report structured progress, logs, and output artefacts.
            retry_on_busy: If ``True``, transparently retry with backoff when
                the server reports ``StudioBusyError``/``ConcurrencyLimitError``,
                instead of raising immediately.
            max_wait: Maximum total seconds to retry when *retry_on_busy* is
                ``True``, before re-raising the busy error.

        Returns:
            The server-assigned ``request_id`` string.  Use it with
            :meth:`get_request_status` or :meth:`get_request_result` to poll
            for the outcome.

        Raises:
            ConnectionError: If the server cannot be reached.
            AuthenticationError: On auth failure.
            StudioBusyError: If DAZ Studio's main thread is busy and
                *retry_on_busy* is ``False`` or *max_wait* is exceeded.
            ConcurrencyLimitError: If too many concurrent requests are in
                flight and *retry_on_busy* is ``False`` or *max_wait* is
                exceeded.
        """
        payload: dict = {"script": script}
        if args is not None:
            payload["args"] = args
        if report_file is not None:
            payload["reportFile"] = report_file

        def _do():
            resp = self._post("/execute/async", payload)
            _raise_for_error(resp)
            return resp.json().get("request_id", "")

        return self._with_busy_retry(_do, retry_on_busy, max_wait)

    def execute_file_async_submit(
        self, script_file: str, args: object = None, *, report_file: str | None = None,
        retry_on_busy: bool = False, max_wait: float = 30.0
    ) -> str:
        """Submit a host-side ``.dsa`` file for asynchronous execution.

        The file is loaded by DAZ Studio when the queued job starts, preserving
        its filename for ``getScriptFileName()`` and relative ``include()``
        calls. Returns the server-assigned request id immediately; use the
        request status/result/cancel methods to manage its lifecycle.
        """
        payload: dict = {"scriptFile": script_file}
        if args is not None:
            payload["args"] = args
        if report_file is not None:
            payload["reportFile"] = report_file

        def _do():
            resp = self._post("/execute/async", payload)
            _raise_for_error(resp)
            return resp.json().get("request_id", "")

        return self._with_busy_retry(_do, retry_on_busy, max_wait)

    def execute_batch_async(
        self, operations: list[dict], args: object = None, *, report_file: str | None = None
    ) -> str:
        """Submit multiple operations as one async request (one queue slot, one script).

        Args:
            operations: List of ``{"body_lines": [...], "result_expression": "..."}``
                dicts — same shape as :meth:`~dazpy.Batch.add_operation`'s arguments.
            args: Optional argument passed to the combined script.
            report_file: Optional host-side JSONL file used for structured job
                observation, as in :meth:`execute_async_submit`.

        Returns:
            The server-assigned ``request_id``. Poll it like any other async
            request; the result's ``result`` field is a dict keyed ``"_r0"``,
            ``"_r1"``, ... in submission order.
        """
        from ._batch import build_operations_script

        pairs = [(op["body_lines"], op["result_expression"]) for op in operations]
        script = build_operations_script(pairs)
        return self.execute_async_submit(script, args=args, report_file=report_file)

    def register_script(self, name: str, script: str, description: str = "") -> dict:
        """Register or replace a named DazScript on the server."""
        resp = self._post(
            "/scripts/register",
            {"name": name, "description": description, "script": script},
        )
        _raise_for_error(resp)
        return resp.json()

    def execute_registered(
        self, name: str, args: object = None, *, retry_on_busy: bool = False,
        max_wait: float = 30.0,
    ) -> ExecutionResult:
        """Execute a registered script by name."""
        payload: dict = {}
        if args is not None:
            payload["args"] = args

        def _do():
            return _map_response(self._post(f"/scripts/{name}/execute", payload))

        return self._with_busy_retry(_do, retry_on_busy, max_wait)

    def execute_registered_async_submit(
        self, name: str, args: object = None, *, report_file: str | None = None,
        retry_on_busy: bool = False, max_wait: float = 30.0,
    ) -> str:
        """Submit a registered script and return its async request id."""
        payload: dict = {}
        if args is not None:
            payload["args"] = args
        if report_file is not None:
            payload["reportFile"] = report_file

        def _do():
            resp = self._post(f"/scripts/{name}/async", payload)
            _raise_for_error(resp)
            return resp.json().get("request_id", "")

        return self._with_busy_retry(_do, retry_on_busy, max_wait)

    def get_request_status(self, request_id: str) -> dict:
        """Return the current status of an async request.

        Args:
            request_id: The ID returned by :meth:`execute_async_submit`.

        Returns:
            A dict with at least ``"status"`` and ``"observation"`` keys.
            Observation contains structured progress, the bounded log tail,
            and the output manifest. Possible status values:
            ``"queued"``, ``"running"``, ``"completed"``, ``"failed"``,
            ``"cancelled"``, or ``"not_found"``.
        """
        resp = self._get(f"/requests/{request_id}/status")
        if resp.status_code == 404:
            return {"status": "not_found"}
        _raise_for_error(resp)
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
            ``duration_ms``, ``status``, and ``observation`` keys.
        """
        params = {}
        if wait:
            params["wait"] = "true"
            params["timeout"] = str(wait_timeout)
        request_timeout = wait_timeout + 10.0 if wait else None
        resp = self._get(
            f"/requests/{request_id}/result",
            params=params or None,
            timeout=request_timeout,
        )
        if resp.status_code == 404:
            return {"status": "not_found"}
        _raise_for_error(resp)
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
        _raise_for_error(resp)
        return resp.json()

    def cancel_request_detail(self, request_id: str) -> dict:
        """Cancel a script or render request and return the server response."""
        if request_id.startswith("rnd-"):
            resp = self._post(f"/render/{request_id}/cancel", {})
        else:
            resp = self._delete(f"/requests/{request_id}")
        _raise_for_error(resp)
        return resp.json()

    def cancel_request(self, request_id: str) -> bool:
        """Cancel a queued or running async request.

        Args:
            request_id: The ID returned by :meth:`execute_async_submit`.

        Returns:
            ``True`` if the server confirmed cancellation, ``False`` otherwise.
        """
        try:
            self.cancel_request_detail(request_id)
            return True
        except DazError:
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
        retry_on_busy: bool = False,
        max_wait: float = 30.0,
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
            engine: Render engine (``"iray"``, ``"viewport"``, ``"filament"``).
            iray_samples: iRay sample count (0 = use scene default).
            reset_morphs: If ``True``, reset all morphs to defaults before applying.
            retry_on_busy: If ``True``, transparently retry with backoff when
                the server reports ``StudioBusyError``/``ConcurrencyLimitError``,
                instead of raising immediately.
            max_wait: Maximum total seconds to retry when *retry_on_busy* is
                ``True``, before re-raising the busy error.

        Returns:
            A dict with ``request_id``, ``status`` (``"queued"``), and
            ``submitted_at`` keys.

        Raises:
            ConnectionError: If the server cannot be reached.
            AuthenticationError: On HTTP 401/403.
            StudioBusyError: If DAZ Studio's main thread is busy and
                *retry_on_busy* is ``False`` or *max_wait* is exceeded.
            ConcurrencyLimitError: If too many concurrent requests are in
                flight and *retry_on_busy* is ``False`` or *max_wait* is
                exceeded.
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

        def _do():
            resp = self._post("/render", payload)
            _raise_for_error(resp)
            return resp.json()

        return self._with_busy_retry(_do, retry_on_busy, max_wait)

    def render_batch_submit(
        self, variants: list, base: dict | None = None, *, retry_on_busy: bool = False, max_wait: float = 30.0
    ) -> dict:
        """Submit a batch render job and return immediately.

        Args:
            variants: List of variant dicts, each with at least ``output_path``.
                Supported keys mirror :meth:`render_submit` optional fields.
            base: Optional shared defaults applied to all variants.
            retry_on_busy: If ``True``, transparently retry with backoff when
                the server reports ``StudioBusyError``/``ConcurrencyLimitError``,
                instead of raising immediately.
            max_wait: Maximum total seconds to retry when *retry_on_busy* is
                ``True``, before re-raising the busy error.

        Returns:
            A dict with ``batch_id``, ``request_ids`` (list), and ``total`` keys.

        Raises:
            ConnectionError: If the server cannot be reached.
            AuthenticationError: On HTTP 401/403.
            StudioBusyError: If DAZ Studio's main thread is busy and
                *retry_on_busy* is ``False`` or *max_wait* is exceeded.
            ConcurrencyLimitError: If too many concurrent requests are in
                flight and *retry_on_busy* is ``False`` or *max_wait* is
                exceeded.
        """
        payload: dict = {"variants": variants}
        if base:
            payload["base"] = base

        def _do():
            resp = self._post("/render/batch", payload)
            _raise_for_error(resp)
            return resp.json()

        return self._with_busy_retry(_do, retry_on_busy, max_wait)

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
        retry_on_busy: bool = False,
        max_wait: float = 30.0,
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
            engine: Render engine (``"iray"``, ``"viewport"``, ``"filament"``).
            retry_on_busy: If ``True``, transparently retry with backoff when
                the server reports ``StudioBusyError``/``ConcurrencyLimitError``,
                instead of raising immediately.
            max_wait: Maximum total seconds to retry when *retry_on_busy* is
                ``True``, before re-raising the busy error.

        Returns:
            A dict with ``request_id``, ``status`` (``"queued"``), and
            ``submitted_at`` keys.

        Raises:
            ConnectionError: If the server cannot be reached.
            AuthenticationError: On HTTP 401/403.
            StudioBusyError: If DAZ Studio's main thread is busy and
                *retry_on_busy* is ``False`` or *max_wait* is exceeded.
            ConcurrencyLimitError: If too many concurrent requests are in
                flight and *retry_on_busy* is ``False`` or *max_wait* is
                exceeded.
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

        def _do():
            resp = self._post("/render/animation", payload)
            _raise_for_error(resp)
            return resp.json()

        return self._with_busy_retry(_do, retry_on_busy, max_wait)

    def cancel_render(self, request_id: str) -> bool:
        """Cancel a queued or running render job.

        Args:
            request_id: The ``request_id`` from :meth:`render_submit` or a
                :class:`~dazpy._render_api.RenderResult` with ``wait=False``.

        Returns:
            ``True`` if the server confirmed cancellation, ``False`` otherwise
            (already finished, not found, or connection error).
        """
        if not request_id.startswith("rnd-"):
            return False
        return self.cancel_request(request_id)

    def stream_render_progress(self, request_id: str, stream_timeout: float = 305.0) -> "object | None":
        """Open the SSE progress stream for a render request.

        Returns a streaming :class:`requests.Response` on success, or ``None``
        if the endpoint is unavailable.  Callers must close the response when done.
        """
        try:
            resp = self._session.get(
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
            resp = self._session.get(
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
        _raise_for_error(resp)
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
        if resp.status_code == 404:
            return {"job_id": job_id, "status": "not_found"}
        _raise_for_error(resp)
        return resp.json()

    # ── Server health ─────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Return the server status dict from ``GET /status``.

        Raises:
            AuthenticationError: On HTTP 401/403.
        """
        resp = self._get("/status")
        _raise_for_error(resp)
        return resp.json()

    def health(self) -> dict:
        """Return the health check dict from ``GET /health``.

        Raises:
            AuthenticationError: On HTTP 401/403.
        """
        resp = self._get("/health")
        _raise_for_error(resp)
        return resp.json()

    def metrics(self) -> dict:
        """Return the metrics dict from ``GET /metrics``.

        Raises:
            AuthenticationError: On HTTP 401/403.
        """
        resp = self._get("/metrics")
        _raise_for_error(resp)
        return resp.json()
