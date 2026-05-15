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
        payload: dict = {"script": script}
        if args is not None:
            payload["args"] = args
        resp = self._post("/execute", payload)
        return _map_response(resp, script=script)

    def execute_file(self, script_file: str, args: object = None) -> ExecutionResult:
        payload: dict = {"scriptFile": script_file}
        if args is not None:
            payload["args"] = args
        resp = self._post("/execute", payload)
        return _map_response(resp)

    def execute_async_submit(self, script: str, args: object = None) -> str:
        payload: dict = {"script": script}
        if args is not None:
            payload["args"] = args
        resp = self._post("/execute/async", payload)
        if resp.status_code in (401, 403):
            raise AuthenticationError(f"HTTP {resp.status_code}")
        return resp.json().get("request_id", "")

    def get_request_status(self, request_id: str) -> dict:
        resp = self._get(f"/requests/{request_id}/status")
        if resp.status_code == 404:
            return {"status": "not_found"}
        return resp.json()

    def get_request_result(self, request_id: str, wait: bool = False, wait_timeout: int = 30) -> dict:
        params = {}
        if wait:
            params["wait"] = "true"
            params["timeout"] = str(wait_timeout)
        resp = self._get(f"/requests/{request_id}/result", params=params or None)
        if resp.status_code == 404:
            return {"status": "not_found"}
        return resp.json()

    def cancel_request(self, request_id: str) -> bool:
        try:
            resp = _requests.delete(
                f"{self._base}/requests/{request_id}",
                headers=self._headers,
                timeout=self._timeout,
            )
            return resp.status_code == 200
        except _requests.exceptions.RequestException:
            return False

    def status(self) -> dict:
        return self._get("/status").json()

    def health(self) -> dict:
        return self._get("/health").json()

    def metrics(self) -> dict:
        return self._get("/metrics").json()
