"""Async high-level render API — mirrors :mod:`dazpy._render_api` for :class:`dazpy.aio.AsyncDazClient`."""

from __future__ import annotations

import asyncio
import time
from typing import Callable

from ._client_aio import AsyncDazClient
from ._render_api import FigureMorphs, RenderBase, RenderResult, RenderVariant, _base_to_dict, _variant_to_dict
from .exceptions import RenderError, TimeoutError


async def _wait_render_sse_async(
    client: AsyncDazClient,
    request_id: str,
    timeout: float,
    on_progress: Callable[[dict], None] | None = None,
) -> RenderResult:
    """Async equivalent of :func:`dazpy._render_api._wait_render_sse`.

    Uses :meth:`AsyncDazClient.stream_render_progress` (an async generator that
    parses SSE internally, since ``httpx`` streaming responses are only valid
    within their ``async with`` block) with a ``get_request_result(wait=True)``
    polling fallback.
    """
    deadline = time.monotonic() + timeout

    try:
        async for event_type, data in client.stream_render_progress(request_id, stream_timeout=timeout + 5.0):
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
            if event_type == "progress" and on_progress is not None:
                on_progress(data)
    except (RenderError, TimeoutError):
        raise
    except Exception:
        pass  # SSE unavailable — fall through to polling

    # Polling fallback
    while time.monotonic() < deadline:
        remaining = max(1, int(deadline - time.monotonic()) + 1)
        data = await client.get_request_result(request_id, wait=True, wait_timeout=min(30, remaining))
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
        await asyncio.sleep(0.5)

    raise TimeoutError(f"Render timed out after {timeout}s (request_id={request_id!r})")


async def render(
    client: AsyncDazClient,
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
    on_progress: Callable[[dict], None] | None = None,
) -> RenderResult:
    """Async equivalent of :func:`dazpy._render_api.render`. See its docstring for details."""
    figures_payload = (
        [{"name": f.name, "morphs": f.morphs} for f in figures]
        if figures else None
    )
    data = await client.render_submit(
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

    return await _wait_render_sse_async(client, request_id, timeout, on_progress=on_progress)


async def render_variants(
    client: AsyncDazClient,
    variants: list[RenderVariant],
    base: RenderBase | None = None,
    *,
    on_progress: Callable[[int, int], None] | None = None,
    timeout: float = 300.0,
) -> list[RenderResult]:
    """Async equivalent of :func:`dazpy._render_api.render_variants`. See its docstring for details."""
    variants_payload = [_variant_to_dict(v) for v in variants]
    base_payload = _base_to_dict(base) if base else None

    data = await client.render_batch_submit(variants_payload, base_payload)
    request_ids: list[str] = data.get("request_ids", [])
    total = len(request_ids)

    results: list[RenderResult] = []
    deadline = time.monotonic() + timeout
    completed = 0

    for i, request_id in enumerate(request_ids):
        remaining = max(1.0, deadline - time.monotonic())
        try:
            result = await _wait_render_sse_async(client, request_id, remaining)
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
