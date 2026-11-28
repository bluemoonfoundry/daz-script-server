"""Transport-independent core shared by :class:`dazpy.DazClient` (``requests``)
and :class:`dazpy.aio.AsyncDazClient` (``httpx``).

Everything here works on a response object and plain data; nothing performs
I/O. Each client supplies the transport: a ``_send()`` adapter (sync or
``async``) plus its own busy-retry loop, ``waiting_out_busy`` scope storage and
version-check request. Public methods stay on the clients because their
``await`` points differ, but they build payloads and interpret responses with
the helpers below so the two cannot drift apart.
"""
from __future__ import annotations

import os
import re
import time
from typing import Any, Protocol
from collections.abc import Callable, Mapping

from .exceptions import (
    AuthenticationError,
    ConcurrencyLimitError,
    ConnectionError,
    DazBusyError,
    DazError,
    ScriptRuntimeError,
    ScriptSyntaxError,
    ServerResponseError,
    StudioBusyError,
    TimeoutError,
)
from ._result import ExecutionResult
from ._version import (
    VersionCheck,
    VersionTracker,
    evaluate_server_version,
    server_instance_id_from_status,
    server_version_from_status,
)


_TOKEN_FILE = os.path.expanduser("~/.daz3d/dazscriptserver_token.txt")
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 18811
_MAX_BACKOFF = 5.0


def _load_token() -> str:
    if os.path.exists(_TOKEN_FILE):
        with open(_TOKEN_FILE) as f:
            return f.read().strip()
    return ""


class _HTTPResponse(Protocol):
    """What the error helpers need from a response: satisfied structurally by
    both ``requests.Response`` (DazClient) and ``httpx.Response`` (AsyncDazClient)."""

    @property
    def status_code(self) -> int: ...
    @property
    def headers(self) -> Mapping[str, str]: ...
    @property
    def text(self) -> str: ...
    def json(self, **kwargs: Any) -> Any: ...


# ── Response mapping ─────────────────────────────────────────────────────────

def _parse_retry_after(resp: _HTTPResponse, default: float = 2.0) -> float:
    raw = resp.headers.get("Retry-After", "")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _retry_delay(exc: BaseException, backoff: float,
                 retry_server_errors: bool | Callable[[], bool] = True) -> float | None:
    """Seconds to wait before retrying after *exc*, or ``None`` if it is not
    retryable.

    Busy errors and any error the server marks ``retryable`` are retried,
    waiting at least the server's ``Retry-After`` and at least *backoff*.
    """
    if isinstance(exc, DazBusyError):
        return max(float(exc.retry_after or 0.0), backoff)
    if getattr(exc, "retryable", False) is not True:
        return None
    if callable(retry_server_errors):
        retry_server_errors = retry_server_errors()
    if retry_server_errors:
        return max(float(getattr(exc, "retry_after", 0.0) or 0.0), backoff)
    return None


def _authentication_error(resp: _HTTPResponse) -> AuthenticationError:
    """Build an AuthenticationError for a 401/403 response, keeping the server's
    ``ErrorResponse`` fields (``error_code``, ``detail``, ``retryable``)."""
    status = resp.status_code
    try:
        parsed = resp.json()
    except (TypeError, ValueError):
        parsed = {}
    data = parsed if isinstance(parsed, dict) else {}
    detail = data.get("detail")
    return AuthenticationError(
        f"HTTP {status}: {data.get('error') or resp.text[:200]}",
        status_code=status,
        error_code=str(data.get("error_code") or ""),
        detail="" if detail is None else str(detail),
        retryable=data.get("retryable") is True,
    )


def _is_artifact_refusal(resp: _HTTPResponse) -> bool:
    """True for a 403 that refuses an artifact outside the server's allowed
    folders: not an authentication problem, so it maps to ServerResponseError."""
    try:
        data = resp.json()
    except (TypeError, ValueError):
        return False
    return isinstance(data, dict) and data.get("error_code") == "ARTIFACT_OUTSIDE_ROOTS"


def _raise_for_error(resp: _HTTPResponse) -> None:
    """Raise a typed exception for authentication or server-busy responses.

    Leaves 2xx responses (and DazScript's own success:false runtime/syntax
    errors, which use HTTP 200) for the caller to handle.
    """
    status = resp.status_code
    if status == 401 or (status == 403 and not _is_artifact_refusal(resp)):
        raise _authentication_error(resp)
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
        raise StudioBusyError(error_msg, reason=str(data.get("detail") or error_msg), retry_after=retry_after)
    if error_code == "CONCURRENT_LIMIT_EXCEEDED":
        raise ConcurrencyLimitError(error_msg, reason=error_msg, retry_after=retry_after)
    raise ServerResponseError(
        error_msg,
        status_code=status,
        error_code=error_code,
        detail=str(data.get("detail", "")),
        retryable=bool(data.get("retryable", False)),
        retry_after=_parse_retry_after(resp, default=0.0),
    )


def _json_ok(resp: _HTTPResponse) -> Any:
    """Raise for an error response, else return its JSON body."""
    _raise_for_error(resp)
    return resp.json()


def _json_or_not_found(resp: _HTTPResponse) -> dict:
    """Like :func:`_json_ok`, but a 404 yields ``{"status": "not_found"}``."""
    if resp.status_code == 404:
        return {"status": "not_found"}
    return _json_ok(resp)


def _submitted_request_id(resp: _HTTPResponse) -> str:
    """The ``request_id`` of an accepted async submission."""
    return _json_ok(resp).get("request_id", "")


def _map_response(resp: _HTTPResponse, script: str = "") -> ExecutionResult:
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


# ── Request building ─────────────────────────────────────────────────────────

def _job_headers(idempotency_key: str | None, correlation_id: str | None) -> dict:
    """Optional request-identity headers for job submission routes.

    ``Idempotency-Key`` makes a retried submission (same route, same body)
    return the original ``request_id`` instead of queueing a second job, for
    as long as the server keeps the record (``limits.idempotency_ttl_seconds``
    in :meth:`DazClient.capabilities`; lost on a server restart, which shows
    as a changed ``server_instance_id``). ``X-Correlation-Id`` is echoed in
    the response and stored on the job record.
    """
    headers = {}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    if correlation_id:
        headers["X-Correlation-Id"] = correlation_id
    return headers


def _script_payload(source: dict, args: object = None, report_file: str | None = None) -> dict:
    """Body for the script routes: *source* (``{"script": ...}``,
    ``{"scriptFile": ...}`` or ``{}`` for a registered script) plus the
    optional ``args``/``reportFile``."""
    payload = dict(source)
    if args is not None:
        payload["args"] = args
    if report_file is not None:
        payload["reportFile"] = report_file
    return payload


def _batch_script(operations: list[dict]) -> str:
    """Combined script for :meth:`DazClient.execute_batch_async`."""
    from ._batch import build_operations_script

    return build_operations_script(
        [(op["body_lines"], op["result_expression"]) for op in operations])


def _render_view_fields(payload: dict, width: int, height: int, camera: str, engine: str) -> dict:
    if width and height:
        payload["width"] = width
        payload["height"] = height
    if camera:
        payload["camera"] = camera
    if engine:
        payload["engine"] = engine
    return payload


def _render_payload(output_path: str, *, figure: str | None, morphs: dict | None,
                    figures: list | None, width: int, height: int, camera: str,
                    engine: str, iray_samples: int, reset_morphs: bool) -> dict:
    """Body for ``POST /render``."""
    payload = _render_view_fields({"output_path": output_path}, width, height, camera, engine)
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
    return payload


def _render_batch_payload(variants: list, base: dict | None) -> dict:
    """Body for ``POST /render/batch``."""
    payload: dict = {"variants": variants}
    if base:
        payload["base"] = base
    return payload


def _render_animation_payload(output_path: str, start_frame: int, end_frame: int, *,
                              frame_padding: int, width: int, height: int,
                              camera: str, engine: str) -> dict:
    """Body for ``POST /render/animation``."""
    return _render_view_fields({
        "output_path": output_path,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "frame_padding": frame_padding,
    }, width, height, camera, engine)


def _result_query(wait: bool, wait_timeout: int) -> tuple[dict | None, float | None]:
    """``(params, http_timeout)`` for ``GET /requests/{id}/result``. A long
    poll gets an HTTP timeout 10 s past the server-side wait."""
    if not wait:
        return None, None
    return {"wait": "true", "timeout": str(wait_timeout)}, wait_timeout + 10.0


def _cancel_route(request_id: str) -> tuple[str, str]:
    """``(method, path)`` that cancels *request_id*: renders (``rnd-``) have
    their own cancel route, scripts are deleted."""
    if request_id.startswith("rnd-"):
        return "post", f"/render/{request_id}/cancel"
    return "delete", f"/requests/{request_id}"


def _range_header(byte_range: tuple[int, int | None] | None) -> dict:
    """``Range`` header for an artifact download, or ``{}`` for the whole file."""
    if byte_range is None:
        return {}
    start, end = byte_range
    if start < 0 or (end is not None and end < start):
        raise ValueError(f"invalid byte_range {byte_range!r}")
    return {"Range": f"bytes={start}-{'' if end is None else end}"}


def _thumbnail_params(size: int, format: str) -> dict:
    return {"thumbnail": int(size), "format": format}


def _safe_artifact_filename(name: str) -> str:
    """Base name safe to join under a download directory (no separators, no '..')."""
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", os.path.basename(name.replace("\\", "/")))
    return name if name.strip(". ") else "artifact"


def _artifact_targets(listing: dict, dest_dir: str | os.PathLike[str]) -> list[tuple[str, str]]:
    """``(artifact_id, local_path)`` for each available entry of a
    :meth:`DazClient.list_artifacts` listing, creating *dest_dir*. Files are
    named ``<artifact_id>_<filename>`` so equal base names can't collide."""
    os.makedirs(dest_dir, exist_ok=True)
    targets = []
    for entry in listing.get("artifacts", []):
        if not entry.get("available"):
            continue
        aid = str(entry["artifact_id"])
        name = _safe_artifact_filename(entry.get("filename") or "artifact")
        targets.append((aid, os.path.join(os.fspath(dest_dir), f"{aid}_{name}")))
    return targets


def _bytes_or_file(content: bytes, dest: str | os.PathLike[str] | None) -> bytes | str:
    """Return *content*, or write it to *dest* and return that path."""
    if dest is None:
        return content
    path = os.fspath(dest)
    with open(path, "wb") as f:
        f.write(content)
    return path


def _events_params(categories: list[str] | None) -> dict | None:
    return {"filter": ",".join(categories)} if categories else None


# ── Shared client state ──────────────────────────────────────────────────────

class _BaseClient:
    """State and helpers common to the sync and async clients.

    Subclasses set the ``_*_ERRORS`` exception tuples for their transport and
    implement ``_send(method, path, headers, timeout, **kwargs)`` (sync or
    ``async``), which ``_post``/``_get``/``_delete`` delegate to; on the async
    client those return awaitables.
    """

    # Transport exception classes, mapped by _transport_error in this order.
    _CONNECT_ERRORS: tuple[type[BaseException], ...] = ()
    _TIMEOUT_ERRORS: tuple[type[BaseException], ...] = ()
    _TRANSPORT_ERRORS: tuple[type[BaseException], ...] = ()

    # Class defaults keep instances built without __init__ (tests) check-free.
    _versions: VersionTracker = VersionTracker(enabled=False)
    _server_version: str | None = None
    _base: str
    _token: str
    _timeout: float

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
        self._versions = VersionTracker(enabled=check_version, on_version_check=on_version_check)
        self._server_version = None

    @property
    def _headers(self) -> dict:
        h = {}
        if self._token:
            h["X-API-Token"] = self._token
        return h

    def _merged_headers(self, extra: dict | None) -> dict:
        return {**self._headers, **extra} if extra else self._headers

    def _http_timeout(self, timeout: float | None) -> float:
        return self._timeout if timeout is None else timeout

    def _send(self, method: str, path: str, headers: dict | None,
              timeout: float | None, **kwargs: Any) -> Any:
        raise NotImplementedError

    def _post(self, path: str, payload: dict, headers: dict | None = None,
              timeout: float | None = None) -> Any:
        return self._send("post", path, headers, timeout, json=payload)

    def _get(self, path: str, params: dict | None = None, timeout: float | None = None) -> Any:
        return self._send("get", path, None, timeout, params=params)

    def _delete(self, path: str) -> Any:
        return self._send("delete", path, None, None)

    def _transport_error(self, exc: BaseException, timeout: float | None) -> DazError:
        """The dazpy error for a transport failure. Marks the version check
        stale: the server may have restarted by the next request."""
        self._versions.mark_stale()
        if isinstance(exc, self._CONNECT_ERRORS):
            return ConnectionError(f"Cannot reach DAZ Studio at {self._base}: {exc}")
        if isinstance(exc, self._TIMEOUT_ERRORS):
            return TimeoutError(f"Request timed out after {self._http_timeout(timeout)}s")
        return ConnectionError(f"HTTP transport failure for DAZ Studio: {exc}")

    def _observe(self, resp: Any) -> Any:
        try:
            self._versions.observe_instance(resp.headers.get("X-Server-Instance-Id"))
        except Exception:
            pass
        return resp

    def _version_check_from_status(self, resp: _HTTPResponse) -> VersionCheck:
        """Evaluate a ``GET /status`` response for the plugin version check,
        remembering the server version it reports."""
        data = resp.json()
        instance = server_instance_id_from_status(data)
        if instance is None:
            header = resp.headers.get("X-Server-Instance-Id")
            instance = header if isinstance(header, str) and header else None
        version = server_version_from_status(data)
        if version is not None:
            self._server_version = version
        return evaluate_server_version(self._base, version, instance)

    def _known_server_version(self) -> str | None:
        """The server version already known without a request, if any."""
        latest = self._versions.latest
        if latest is not None and latest.server_version is not None:
            return latest.server_version
        return self._server_version

    @property
    def version_check(self) -> VersionCheck | None:
        """The latest plugin version check, or ``None`` before one completes."""
        return self._versions.latest

    def _scoped_busy_wait(self) -> float | None:
        """``max_wait`` of the innermost ``waiting_out_busy`` block applying
        to the caller, or ``None``."""
        return None

    def _busy_deadline(self, retry_on_busy: bool, max_wait: float) -> float | None:
        """Monotonic deadline for busy retries, or ``None`` to call once."""
        if not retry_on_busy:
            scoped = self._scoped_busy_wait()
            if scoped is None:
                return None
            max_wait = scoped
        return time.monotonic() + max_wait

    @staticmethod
    def _retry_pause(exc: DazError, deadline: float, backoff: float,
                     retry_server_errors: bool | Callable[[], bool]) -> float | None:
        """Seconds to sleep before the next attempt, or ``None`` to re-raise
        *exc* (not retryable, or the deadline has passed)."""
        delay = _retry_delay(exc, backoff, retry_server_errors)
        remaining = deadline - time.monotonic()
        if delay is None or remaining <= 0:
            return None
        return min(delay, remaining)
