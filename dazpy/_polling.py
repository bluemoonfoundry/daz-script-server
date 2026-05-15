from __future__ import annotations

import time

from ._client import DazClient
from ._result import ExecutionResult
from .exceptions import AsyncExecutionError, TimeoutError


def execute_long(
    client: DazClient,
    script: str,
    args: object = None,
    timeout: float = 120.0,
    poll_interval: float = 0.5,
) -> ExecutionResult:
    """Execute a potentially long-running script via the async endpoint with polling.

    Submits *script* asynchronously, then polls ``/requests/:id/result`` with
    long-polling until the script completes or *timeout* is exceeded.

    Args:
        client: The :class:`~dazpy.DazClient` to use.
        script: DazScript source code.
        args: Optional argument passed to the script.
        timeout: Maximum total wall-clock seconds to wait.
        poll_interval: Seconds to sleep between short polls when the server
            returns before the long-poll timeout.

    Returns:
        An :class:`~dazpy.ExecutionResult` on success.

    Raises:
        AsyncExecutionError: If the script fails or the request is cancelled.
        TimeoutError: If *timeout* is exceeded before the script completes.
    """
    request_id = client.execute_async_submit(script, args)
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        data = client.get_request_result(request_id, wait=True, wait_timeout=min(30, int(deadline - time.monotonic()) + 1))
        status = data.get("status") or ("completed" if data.get("success") is not None else None)
        if data.get("success") is not None:
            if not data.get("success"):
                raise AsyncExecutionError(data.get("error", "Async script failed"), request_id=request_id)
            return ExecutionResult(
                value=data.get("result"),
                output=data.get("output", []),
                request_id=request_id,
                success=True,
                duration_ms=data.get("duration_ms", 0.0),
            )
        if status == "failed":
            raise AsyncExecutionError(data.get("error", "Async script failed"), request_id=request_id)
        if status == "cancelled":
            raise AsyncExecutionError("Request was cancelled", request_id=request_id)
        time.sleep(poll_interval)

    raise TimeoutError(f"Async execution timed out after {timeout}s (request_id={request_id})")
