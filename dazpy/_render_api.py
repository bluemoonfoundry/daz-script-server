"""High-level render API — dataclasses and convenience wrappers for /render and /render/batch."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Callable

from ._client import DazClient
from .exceptions import RenderError, TimeoutError


@dataclass
class FigureMorphs:
    """A figure and the morph values to apply before rendering."""

    name: str | None
    morphs: dict[str, float] = field(default_factory=dict)


@dataclass
class RenderVariant:
    """A single output variant for batch rendering."""

    output_path: str
    figure: str | None = None
    morphs: dict[str, float] = field(default_factory=dict)
    figures: list[FigureMorphs] = field(default_factory=list)
    width: int = 0
    height: int = 0
    camera: str = ""
    engine: str = ""


@dataclass
class RenderBase:
    """Shared defaults applied to all variants in a batch render."""

    figure: str | None = None
    morphs: dict[str, float] = field(default_factory=dict)
    figures: list[FigureMorphs] = field(default_factory=list)
    width: int = 0
    height: int = 0
    camera: str = ""
    engine: str = ""


@dataclass
class RenderResult:
    """Result of a single render operation."""

    success: bool
    output_path: str
    file_size_bytes: int = -1
    duration_ms: int = 0
    error: str = ""
    request_id: str = ""


# ── Internal helpers ──────────────────────────────────────────────────────────


def _variant_to_dict(v: RenderVariant) -> dict:
    d: dict = {"output_path": v.output_path}
    if v.figures:
        d["figures"] = [{"name": f.name, "morphs": f.morphs} for f in v.figures]
    elif v.figure:
        d["figure"] = v.figure
        if v.morphs:
            d["morphs"] = v.morphs
    if v.width and v.height:
        d["width"] = v.width
        d["height"] = v.height
    if v.camera:
        d["camera"] = v.camera
    if v.engine:
        d["engine"] = v.engine
    return d


def _base_to_dict(b: RenderBase) -> dict:
    d: dict = {}
    if b.figures:
        d["figures"] = [{"name": f.name, "morphs": f.morphs} for f in b.figures]
    elif b.figure:
        d["figure"] = b.figure
        if b.morphs:
            d["morphs"] = b.morphs
    if b.width and b.height:
        d["width"] = b.width
        d["height"] = b.height
    if b.camera:
        d["camera"] = b.camera
    if b.engine:
        d["engine"] = b.engine
    return d


def _parse_sse_events(response: object):
    """Yield ``(event_type, data_dict)`` pairs from a streaming SSE response."""
    event_type = "message"
    data_lines: list[str] = []

    for raw_line in response.iter_lines():
        line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else raw_line
        if not line:
            if data_lines:
                data_str = "\n".join(data_lines)
                try:
                    yield event_type, json.loads(data_str)
                except json.JSONDecodeError:
                    yield event_type, {"_raw": data_str}
            event_type = "message"
            data_lines = []
        elif line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())


def _wait_render_sse(client: DazClient, request_id: str, timeout: float) -> RenderResult:
    """Wait for a render to complete using the SSE progress stream.

    Falls back to request-result polling if the SSE stream cannot be established
    or if the server returns a non-200 status.
    """
    deadline = time.monotonic() + timeout

    # Try SSE first — it delivers the complete event with file_size_bytes.
    try:
        resp = client.stream_render_progress(request_id, stream_timeout=timeout + 5.0)
        if resp is not None:
            for event_type, data in _parse_sse_events(resp):
                if time.monotonic() > deadline:
                    break
                if event_type == "complete":
                    return RenderResult(
                        success=True,
                        output_path=data.get("output_path", ""),
                        file_size_bytes=int(data.get("file_size_bytes", -1)),
                        duration_ms=int(data.get("duration_ms", 0)),
                    )
                if event_type == "error":
                    raise RenderError(data.get("error", "Render failed"), request_id=request_id)
                # "progress" → render is running, keep reading
    except (RenderError, TimeoutError):
        raise
    except Exception:
        pass  # SSE unavailable — fall through to polling

    # Polling fallback
    while time.monotonic() < deadline:
        remaining = max(1, int(deadline - time.monotonic()) + 1)
        data = client.get_request_result(request_id, wait=True, wait_timeout=min(30, remaining))
        if data.get("success") is not None:
            if not data["success"]:
                raise RenderError(data.get("error", "Render failed"), request_id=request_id)
            result_val = data.get("result") or {}
            out_path = result_val.get("output_path", "") if isinstance(result_val, dict) else ""
            return RenderResult(
                success=True,
                output_path=out_path,
                duration_ms=int(data.get("duration_ms", 0)),
            )
        status = data.get("status")
        if status == "failed":
            raise RenderError(data.get("error", "Render failed"), request_id=request_id)
        if status == "cancelled":
            raise RenderError("Render was cancelled", request_id=request_id)
        time.sleep(0.5)

    raise TimeoutError(f"Render timed out after {timeout}s (request_id={request_id!r})")


# ── Public API ────────────────────────────────────────────────────────────────


def render(
    client: DazClient,
    output_path: str,
    *,
    figure: str | None = None,
    morphs: dict[str, float] | None = None,
    figures: list[FigureMorphs] | None = None,
    width: int = 0,
    height: int = 0,
    camera: str = "",
    engine: str = "",
    iray_samples: int = 0,
    reset_morphs: bool = False,
    wait: bool = True,
    timeout: float = 300.0,
) -> RenderResult:
    """Render the DAZ Studio scene to *output_path*.

    Uses the SSE progress stream (``GET /render/:id/progress``) when available;
    falls back to long-poll on ``/requests/:id/result`` otherwise.

    Args:
        client: Connected :class:`~dazpy.DazClient`.
        output_path: Absolute path on the DAZ Studio host to write the image.
        figure: Label of the figure to configure morphs on.
        morphs: Morph values to apply ``{label: value}``.  Only used when
            *figure* is set.
        figures: List of :class:`FigureMorphs` for multi-figure scenes.
            Mutually exclusive with *figure*.
        width: Image width in pixels (must be paired with *height*).
        height: Image height in pixels (must be paired with *width*).
        camera: Camera label to render from.  Defaults to the active viewport camera.
        engine: Render engine (``"iray"``, ``"3delight"``, ``"filament"``).
        iray_samples: iRay sample count (0 = use scene default).
        reset_morphs: If ``True``, reset all figure morph values to defaults
            before applying *morphs*.
        wait: If ``True`` (default), block until the render completes and return
            a fully populated :class:`RenderResult`.  If ``False``, return
            immediately after the job is accepted; the result will have
            ``file_size_bytes=-1`` and ``duration_ms=0``.
        timeout: Maximum seconds to wait when *wait* is ``True``.

    Returns:
        A :class:`RenderResult`.

    Raises:
        RenderError: If the render fails.
        TimeoutError: If *timeout* is exceeded.
        ConnectionError: If the server cannot be reached.
        AuthenticationError: On HTTP 401/403.

    Example::

        from dazpy import DazClient
        from dazpy._render_api import render, FigureMorphs

        client = DazClient()
        result = render(client, r"C:\\tmp\\out.png", width=1920, height=1080)
        print(result.output_path, result.file_size_bytes)
    """
    figures_payload = (
        [{"name": f.name, "morphs": f.morphs} for f in figures]
        if figures else None
    )
    data = client.render_submit(
        output_path,
        figure=figure,
        morphs=morphs,
        figures=figures_payload,
        width=width,
        height=height,
        camera=camera,
        engine=engine,
        iray_samples=iray_samples,
        reset_morphs=reset_morphs,
    )
    request_id: str = data.get("request_id", "")

    if not wait:
        return RenderResult(success=True, output_path=output_path, request_id=request_id)

    return _wait_render_sse(client, request_id, timeout)


def render_variants(
    client: DazClient,
    variants: list[RenderVariant],
    base: RenderBase | None = None,
    *,
    on_progress: Callable[[int, int], None] | None = None,
    timeout: float = 300.0,
) -> list[RenderResult]:
    """Render multiple variants via ``POST /render/batch``.

    Submits all variants in a single batch request, then waits for each render
    to complete sequentially, calling *on_progress* after each one finishes.

    Args:
        client: Connected :class:`~dazpy.DazClient`.
        variants: Ordered list of :class:`RenderVariant` specs.
        base: Shared defaults (figure, size, camera, engine) applied to all
            variants unless overridden per-variant.
        on_progress: Optional callback called with ``(completed, total)`` after
            each render finishes.
        timeout: Maximum total seconds to wait for all renders to finish.

    Returns:
        A list of :class:`RenderResult` in the same order as *variants*.
        If a variant fails its result will have ``success=False`` and
        ``error`` set; subsequent variants are still attempted.

    Raises:
        TimeoutError: If *timeout* is exceeded.
        ConnectionError: If the server cannot be reached.
        AuthenticationError: On HTTP 401/403.

    Example::

        from dazpy import DazClient
        from dazpy._render_api import RenderVariant, RenderBase, render_variants

        client = DazClient()
        results = render_variants(
            client,
            [
                RenderVariant(r"C:\\tmp\\smile.png", figure="Genesis 9", morphs={"Smile": 1.0}),
                RenderVariant(r"C:\\tmp\\neutral.png", figure="Genesis 9"),
            ],
            base=RenderBase(width=1920, height=1080, engine="iray"),
            on_progress=lambda done, total: print(f"{done}/{total}"),
        )
    """
    variants_payload = [_variant_to_dict(v) for v in variants]
    base_payload = _base_to_dict(base) if base else None

    data = client.render_batch_submit(variants_payload, base_payload)
    request_ids: list[str] = data.get("request_ids", [])
    total = len(request_ids)

    results: list[RenderResult] = []
    deadline = time.monotonic() + timeout
    completed = 0

    for i, request_id in enumerate(request_ids):
        remaining = max(1.0, deadline - time.monotonic())
        try:
            result = _wait_render_sse(client, request_id, remaining)
        except RenderError as exc:
            result = RenderResult(
                success=False,
                output_path=variants[i].output_path if i < len(variants) else "",
                error=str(exc),
            )
        results.append(result)
        completed += 1
        if on_progress is not None:
            on_progress(completed, total)

    return results
