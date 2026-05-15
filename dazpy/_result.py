from dataclasses import dataclass, field


@dataclass
class ExecutionResult:
    """The result of a synchronous or asynchronous DazScript execution.

    Attributes:
        value: The return value of the script (JSON-decoded).  May be ``None``,
            a ``bool``, ``int``, ``float``, ``str``, ``list``, or ``dict``.
        output: Lines written to the DAZ Studio message log during execution.
        request_id: The server-assigned request ID (empty for sync executions).
        success: ``True`` if the script completed without error.
        error: Error message returned by the server (empty when successful).
        duration_ms: Wall-clock execution time in milliseconds as measured by
            the server.
    """

    value: object
    output: list[str] = field(default_factory=list)
    request_id: str = ""
    success: bool = True
    error: str = ""
    duration_ms: float = 0.0
