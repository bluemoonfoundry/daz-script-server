"""USD export client — async job handle and convenience wrapper."""

from __future__ import annotations

import time

from ._client import DazClient
from .exceptions import TimeoutError, UsdExportError


class UsdExportJob:
    """Handle for a USD export job running in DAZ Studio.

    Obtain an instance via :func:`export_usd` rather than constructing
    directly.

    Attributes:
        job_id: Server-assigned job identifier.
    """

    def __init__(self, client: DazClient, job_id: str, output_path: str) -> None:
        self._client = client
        self._job_id = job_id
        self._output_path = output_path
        self._status: str = "queued"
        self._result_path: str | None = None
        self._error: str | None = None

    @property
    def job_id(self) -> str:
        """Server-assigned job ID."""
        return self._job_id

    @property
    def status(self) -> str:
        """Current job status.

        Fetches a fresh value from the server on each access.  Possible
        values: ``"queued"``, ``"running"``, ``"completed"``, ``"failed"``,
        ``"not_found"``.
        """
        self._refresh()
        return self._status

    @property
    def result_path(self) -> str | None:
        """Absolute path of the exported ``.usda`` file, or ``None`` if not yet complete."""
        self._refresh()
        return self._result_path

    def _refresh(self) -> None:
        """Update cached state from the server (no-op if already terminal)."""
        if self._status in ("completed", "failed", "not_found"):
            return
        data = self._client.get_usd_export_status(self._job_id)
        self._status = data.get("status", "unknown")
        if self._status == "completed":
            self._result_path = data.get("outputPath") or self._output_path
        elif self._status == "failed":
            self._error = data.get("error", "USD export failed")

    def wait(
        self,
        timeout: float = 120.0,
        poll_interval: float = 0.5,
    ) -> str:
        """Block until the export completes and return the output path.

        Args:
            timeout: Maximum seconds to wait before raising :exc:`~dazpy.exceptions.TimeoutError`.
            poll_interval: Seconds between status polls.

        Returns:
            Absolute path to the exported ``.usda`` file.

        Raises:
            UsdExportError: If DAZ Studio reports the export failed.
            TimeoutError: If *timeout* is exceeded before completion.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._refresh()
            if self._status == "completed":
                return self._result_path  # type: ignore[return-value]
            if self._status == "failed":
                raise UsdExportError(
                    self._error or "USD export failed", job_id=self._job_id
                )
            if self._status == "not_found":
                raise UsdExportError(
                    f"Export job {self._job_id!r} not found on server",
                    job_id=self._job_id,
                )
            # Not yet terminal — wait before next poll
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(poll_interval, remaining))

        raise TimeoutError(
            f"USD export timed out after {timeout}s (job_id={self._job_id!r})"
        )

    def __repr__(self) -> str:
        return (
            f"UsdExportJob(job_id={self._job_id!r}, status={self._status!r}, "
            f"output_path={self._output_path!r})"
        )


def export_usd(
    client: DazClient,
    output_path: str,
    *,
    include_geometry: bool = True,
    include_materials: bool = True,
    include_skeleton: bool = False,
    include_morphs: bool = False,
    include_lights: bool = False,
    include_camera: bool = False,
    wait: bool = False,
    timeout: float = 120.0,
    poll_interval: float = 0.5,
) -> UsdExportJob:
    """Export the current DAZ Studio scene to a USDA file.

    Submits an export job to the ``/export/usd`` endpoint and returns a
    :class:`UsdExportJob` handle immediately.  If *wait* is ``True`` the
    function blocks until the export finishes (equivalent to calling
    ``job.wait()``).

    Args:
        client: Connected :class:`~dazpy.DazClient`.
        output_path: Absolute path on the DAZ Studio host where the ``.usda``
            file should be written.
        include_geometry: Export mesh geometry (default ``True``).
        include_materials: Export PBR material prims (default ``True``).
        include_skeleton: Export UsdSkel armature and skin weights.
        include_morphs: Export active morphs as UsdSkelBlendShape prims.
        include_lights: Export scene lights using UsdLux prims.
        include_camera: Export the active render camera as UsdGeomCamera.
        wait: If ``True``, block until the export completes before returning.
        timeout: Maximum seconds to wait when *wait* is ``True``.
        poll_interval: Poll cadence in seconds when *wait* is ``True``.

    Returns:
        A :class:`UsdExportJob` handle.  When *wait* is ``True`` the job will
        already be in the ``"completed"`` state on return.

    Raises:
        ConnectionError: If the server cannot be reached.
        AuthenticationError: On HTTP 401/403.
        UsdExportError: If *wait* is ``True`` and the export fails.
        TimeoutError: If *wait* is ``True`` and *timeout* is exceeded.

    Example::

        from dazpy import DazClient
        from dazpy._usd import export_usd

        client = DazClient()

        # Fire-and-forget: poll manually
        job = export_usd(client, r"C:\\tmp\\scene.usda", include_skeleton=True)
        print(job.job_id)       # "a1b2c3d4e5f6g7h8"
        path = job.wait()       # blocks until done
        print(path)             # "C:\\tmp\\scene.usda"

        # One-shot blocking call
        job = export_usd(
            client, r"C:\\tmp\\scene.usda",
            include_skeleton=True,
            include_morphs=True,
            wait=True,
        )
        print(job.result_path)
    """
    data = client.export_usd_submit(
        output_path,
        include_geometry=include_geometry,
        include_materials=include_materials,
        include_skeleton=include_skeleton,
        include_morphs=include_morphs,
        include_lights=include_lights,
        include_camera=include_camera,
    )
    job = UsdExportJob(client, data["job_id"], output_path)

    if wait:
        job.wait(timeout=timeout, poll_interval=poll_interval)

    return job
