"""General scene-change event stream — SSE-based watcher for GET /scene/events.

Mirrors the shape of the render-progress stream (``stream_render_progress`` /
``_render_api._parse_sse_events``) but for the broader set of scene-change
notifications DAZ Studio emits: nodes/skeletons/lights/cameras added or
removed, selection changes, time scrubs, scene load/save, and render start/end.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterator

from ._client import DazClient
from .exceptions import ConnectionError, TimeoutError

_VALID_CATEGORIES = {
    "node", "skeleton", "light", "camera",
    "selection", "scene", "time", "render",
}


@dataclass
class SceneEvent:
    """A single scene-change event received from the SSE stream."""

    type: str
    ts: int
    data: dict


def _iter_sse_lines(response: object) -> Iterator[str]:
    """Yield text lines from a streaming SSE response, decoded from UTF-8."""
    buf = b""
    for chunk in response.iter_content(chunk_size=None):
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            yield line.decode("utf-8", errors="replace")


def _parse_scene_events(response: object) -> Iterator[SceneEvent]:
    """Parse ``GET /scene/events`` SSE frames into :class:`SceneEvent` objects.

    Comment lines (keepalives, starting with ``:``) and malformed payloads
    are silently skipped.
    """
    for line in _iter_sse_lines(response):
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if not payload:
            continue
        try:
            raw = json.loads(payload)
        except json.JSONDecodeError:
            continue
        yield SceneEvent(type=raw.get("type", ""), ts=raw.get("ts", 0), data=raw.get("data", {}))


def watch_scene_events(
    client: DazClient,
    categories: "list[str] | None" = None,
    event_types: "set[str] | None" = None,
    stream_timeout: "float | None" = None,
) -> Iterator[SceneEvent]:
    """Yield :class:`SceneEvent` objects as DAZ Studio reports scene changes.

    Opens an SSE connection to ``GET /scene/events`` and yields events as they
    arrive, filtered server-side by *categories* and optionally client-side by
    exact *event_types* (e.g. ``{"node.added", "node.removed"}``).

    The connection stays open until the caller stops iterating (e.g. via
    ``break``) or the server closes the stream.

    Args:
        client: Connected :class:`~dazpy.DazClient`.
        categories: Optional subset of event categories to subscribe to
            server-side (see :data:`_VALID_CATEGORIES`). ``None`` subscribes
            to all categories.
        event_types: Optional set of exact event types to keep; all others
            are dropped client-side. ``None`` yields every event received.
        stream_timeout: Socket timeout in seconds. ``None`` (default) waits
            indefinitely — the server sends a keepalive comment every 15
            seconds, so the connection never idles out.

    Raises:
        ConnectionError: If the SSE endpoint could not be reached.

    Example::

        from dazpy import DazClient
        from dazpy._scene_events import watch_scene_events

        client = DazClient()
        for event in watch_scene_events(client, categories=["node", "selection"]):
            print(event.type, event.data)
            if event.type == "node.added":
                break
    """
    resp = client.stream_scene_events(categories=categories, stream_timeout=stream_timeout)
    if resp is None:
        raise ConnectionError("Could not open /scene/events stream")
    try:
        for event in _parse_scene_events(resp):
            if event_types is not None and event.type not in event_types:
                continue
            yield event
    finally:
        resp.close()


def wait_for_scene_event(
    client: DazClient,
    event_type: str,
    timeout: float = 300.0,
) -> SceneEvent:
    """Block until a scene event of *event_type* arrives, then return it.

    Args:
        client: Connected :class:`~dazpy.DazClient`.
        event_type: Exact event type to wait for, e.g. ``"node.added"`` or
            ``"render.finished"``. The category prefix (text before the
            first ``.``) is used to narrow the server-side subscription.
        timeout: Maximum seconds to wait.

    Returns:
        The matching :class:`SceneEvent`.

    Raises:
        TimeoutError: If *timeout* elapses before a matching event arrives.
        ConnectionError: If the SSE endpoint could not be reached.
    """
    category = event_type.split(".")[0]
    categories = [category] if category in _VALID_CATEGORIES else None

    try:
        for event in watch_scene_events(
            client,
            categories=categories,
            event_types={event_type},
            stream_timeout=timeout + 5.0,
        ):
            return event
    except ConnectionError:
        raise
    except Exception:
        pass  # stream read timed out or connection dropped — fall through

    raise TimeoutError(f"Timed out after {timeout}s waiting for '{event_type}'")
