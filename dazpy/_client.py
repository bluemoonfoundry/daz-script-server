from __future__ import annotations

import os
import re

import requests as _requests

from .exceptions import (
    AuthenticationError,
    ConnectionError,
    ScriptRuntimeError,
    ScriptSyntaxError,
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


def _map_response(resp: _requests.Response, script: str = "") -> ExecutionResult:
    status = resp.status_code
    if status == 401 or status == 403:
        raise AuthenticationError(f"HTTP {status}: {resp.text[:200]}")

    data = resp.json()
    request_id = data.get("request_id", "")

    if not data.get("success", True):
        error_msg = data.get("error", "Script failed")
        # SyntaxError comes from the parser; runtime errors (TypeError, ReferenceError,
        # Error, etc.) also include "Line N:" but never say "SyntaxError" explicitly.
        if "SyntaxError" in error_msg:
            raise ScriptSyntaxError(error_msg, script=script, request_id=request_id)
        raise ScriptRuntimeError(error_msg, script=script, request_id=request_id)

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
        """Return the server status dict from ``GET /status``."""
        return self._get("/status").json()

    def health(self) -> dict:
        """Return the health check dict from ``GET /health``."""
        return self._get("/health").json()

    def metrics(self) -> dict:
        """Return the metrics dict from ``GET /metrics``."""
        return self._get("/metrics").json()
