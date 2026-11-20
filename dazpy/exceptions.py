class DazError(Exception):
    """Base class for all dazpy exceptions."""


class ConnectionError(DazError):
    """Raised when the SDK cannot reach the DAZ Studio Script Server."""


class AuthenticationError(DazError):
    """Raised on HTTP 401 or 403 (bad or missing API token, or IP blocked).

    Attributes:
        status_code: HTTP response status (401 or 403).
        error_code: Stable server error code when supplied (e.g.
            ``AUTH_INVALID_TOKEN``, ``IP_NOT_WHITELISTED``).
        detail: Optional structured detail from the server response.
        retryable: True when the server says an identical retry may succeed.
    """

    def __init__(self, message: str, status_code: int = 401, error_code: str = "", detail: str = "",
                 retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.detail = detail
        self.retryable = retryable


class ServerResponseError(DazError):
    """Raised when the Script Server rejects a protocol request.

    Attributes:
        status_code: HTTP response status.
        error_code: Stable server error code when supplied.
        detail: Optional structured detail from the server response.
        retryable: True when the server says an identical retry may succeed
            (e.g. queue full, ``IDEMPOTENCY_KEY_IN_FLIGHT``).
    """

    def __init__(self, message: str, status_code: int, error_code: str = "", detail: str = "",
                 retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.detail = detail
        self.retryable = retryable


class DazBusyError(DazError):
    """Base class for transient "DAZ Studio is busy, please retry" conditions.

    Attributes:
        reason: Human-readable explanation of why the server is busy.
        retry_after: Server-suggested seconds to wait before retrying.
    """

    def __init__(self, message: str, reason: str = "", retry_after: float = 2.0):
        super().__init__(message)
        self.reason = reason
        self.retry_after = retry_after


class StudioBusyError(DazBusyError):
    """Raised on HTTP 503 STUDIO_BUSY: DAZ Studio's main thread is occupied
    with a scene load, save, clear, or render and cannot service the request."""


class ConcurrencyLimitError(DazBusyError):
    """Raised on HTTP 429 CONCURRENT_LIMIT_EXCEEDED: too many requests are
    already in flight against the server."""


class ScriptError(DazError):
    """Base class for errors that originate inside a DazScript execution.

    Attributes:
        script: The DazScript source that was submitted (may be empty for
            file-based executions).
        request_id: The server-assigned request ID, useful for log correlation.
        output: Lines written to the DAZ Studio message log before the error
            (e.g. via print()), useful for tracing state leading up to a failure.
    """

    def __init__(
        self,
        message: str,
        script: str = "",
        request_id: str = "",
        output: "list[str] | None" = None,
    ):
        super().__init__(message)
        self.script = script
        self.request_id = request_id
        self.output = output or []

    @property
    def diagnostic(self) -> str:
        """Return a formatted string with line-numbered source and error details."""
        lines = []
        if self.script:
            numbered = "\n".join(f"{i+1:4d}: {line}" for i, line in enumerate(self.script.splitlines()))
            lines.append(numbered)
        lines.append(str(self))
        if self.output:
            lines.append("\nCaptured output:\n" + "\n".join(self.output))
        if self.request_id:
            lines.append(f"request_id: {self.request_id}")
        return "\n".join(lines)


class ScriptSyntaxError(ScriptError):
    """Raised when the DazScript engine reports a parse / syntax error."""


class ScriptRuntimeError(ScriptError):
    """Raised when a DazScript execution fails at runtime (TypeError, ReferenceError, etc.)."""


class TimeoutError(DazError):
    """Raised when an HTTP request or async poll exceeds its timeout."""


class NodeNotFoundError(DazError):
    """Raised when a requested scene node, bone, or skeleton cannot be found."""


class AsyncExecutionError(DazError):
    """Raised when an async request fails, is cancelled, or times out while polling.

    Attributes:
        request_id: The server-assigned request ID of the failed async job.
    """

    def __init__(self, message: str, request_id: str = ""):
        super().__init__(message)
        self.request_id = request_id


class RenderError(DazError):
    """Raised when a render job fails on the DAZ Studio side.

    Attributes:
        request_id: The server-assigned render request ID.
    """

    def __init__(self, message: str, request_id: str = ""):
        super().__init__(message)
        self.request_id = request_id


class BatchLimitExceededError(DazError):
    """Raised by :meth:`~dazpy.Batch.execute` (or ``add_operation``, for the
    operation-count limit) when a batch would exceed its configured
    operation-count or generated-script-length limit.

    Raised client-side before any HTTP call, so an oversized batch never
    reaches Studio's main thread.
    """


class MaterialError(DazError):
    """Raised when an Iray material/surface-property operation fails.

    Covers a missing material, a channel label that doesn't resolve to a
    property on the live material, or a failed ``setValue()``/``setMap()``.

    Attributes:
        request_id: The server-assigned render request ID.
    """

    def __init__(self, message: str, request_id: str = ""):
        super().__init__(message)
        self.request_id = request_id


class ServerVersionWarning(UserWarning):
    """Warned when the connected plugin is older than :data:`dazpy.MIN_SERVER_VERSION`.

    dazpy may call endpoints an older plugin doesn't have, which then fail with
    opaque HTTP errors. Upgrade the DazScriptServer plugin in that Daz Studio
    instance, or use a dazpy release that matches the plugin. Emitted once per
    running plugin; the result is also available as ``client.version_check``
    and through the ``on_version_check`` callback.

    Silence with ``DazClient(check_version=False)`` or the standard
    :mod:`warnings` filters.
    """


class RecipeValidationError(DazError):
    """Raised when a scene recipe fails offline validation.

    Attributes:
        report: The :class:`dazpy._recipe_validate.ValidationReport` with every
            error found (path, code, message, allowed values, suggestion).
    """

    def __init__(self, report):
        self.report = report
        lines = []
        for e in report.errors:
            line = f"{e.path}: [{e.code}] {e.message}"
            if e.suggestion:
                line += f" (did you mean {e.suggestion!r}?)"
            lines.append(line)
        super().__init__(
            f"scene recipe is invalid ({len(report.errors)} error(s)):\n" + "\n".join(lines))


class RecipeNotAppliedError(DazError):
    """Raised by ``dazpy.recipe.render`` when the scene does not match the recipe.

    Attributes:
        report: The :class:`dazpy.recipe.ObserveReport` that caused the refusal.
    """

    def __init__(self, message, report):
        self.report = report
        super().__init__(message)
