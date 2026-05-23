class DazError(Exception):
    """Base class for all dazpy exceptions."""


class ConnectionError(DazError):
    """Raised when the SDK cannot reach the DAZ Studio Script Server."""


class AuthenticationError(DazError):
    """Raised on HTTP 401 or 403 (bad or missing API token, or IP blocked)."""


class ScriptError(DazError):
    """Base class for errors that originate inside a DazScript execution.

    Attributes:
        script: The DazScript source that was submitted (may be empty for
            file-based executions).
        request_id: The server-assigned request ID, useful for log correlation.
    """

    def __init__(self, message: str, script: str = "", request_id: str = ""):
        super().__init__(message)
        self.script = script
        self.request_id = request_id

    @property
    def diagnostic(self) -> str:
        """Return a formatted string with line-numbered source and error details."""
        lines = []
        if self.script:
            numbered = "\n".join(f"{i+1:4d}: {line}" for i, line in enumerate(self.script.splitlines()))
            lines.append(numbered)
        lines.append(str(self))
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


class UsdExportError(DazError):
    """Raised when a USD export job fails on the DAZ Studio side.

    Attributes:
        job_id: The server-assigned export job ID.
    """

    def __init__(self, message: str, job_id: str = ""):
        super().__init__(message)
        self.job_id = job_id
