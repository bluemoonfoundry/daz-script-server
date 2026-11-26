"""Server-sent events parsing shared by every dazpy SSE consumer.

One frame parser serves the sync render-progress stream
(:mod:`dazpy._render_api`), the async client (:mod:`dazpy._client_aio`) and
the scene-event watcher (:mod:`dazpy._scene_events`), so they agree on frame
boundaries, the ``event:`` field and malformed payloads.

Frames follow the SSE spec closely enough for the server's output
(``event: <type>\\ndata: <json>\\n\\n``, and ``: keepalive`` comments):

* A blank line dispatches the pending event; so does end of stream, so a
  final event is not lost if the connection closes right after its data.
* ``event:`` sets the type for the pending event (default ``"message"``);
  it resets after each dispatch.
* Multiple ``data:`` lines are joined with ``\\n``.
* Comment lines (``:``) and frames without data dispatch nothing.
* The data is decoded as JSON; text that is not JSON is yielded as
  ``{"_raw": text}`` so callers can choose whether to drop it.
"""

from __future__ import annotations

import json
from typing import Any
from collections.abc import AsyncIterable, AsyncIterator, Iterable, Iterator

SseEvent = tuple[str, Any]


class _FrameParser:
    """Incremental line-at-a-time frame state shared by the sync and async parsers."""

    __slots__ = ("event_type", "data_lines")

    def __init__(self) -> None:
        self.event_type = "message"
        self.data_lines: list[str] = []

    def feed(self, line: str | bytes) -> SseEvent | None:
        if isinstance(line, bytes):
            line = line.decode("utf-8", errors="replace")
        line = line.rstrip("\r\n")
        if not line:
            return self.flush()
        if line.startswith("event:"):
            self.event_type = line[6:].strip()
        elif line.startswith("data:"):
            value = line[5:]
            self.data_lines.append(value[1:] if value.startswith(" ") else value)
        return None

    def flush(self) -> SseEvent | None:
        event: SseEvent | None = None
        if self.data_lines:
            text = "\n".join(self.data_lines)
            try:
                data: Any = json.loads(text)
            except json.JSONDecodeError:
                data = {"_raw": text}
            event = (self.event_type, data)
        self.event_type = "message"
        self.data_lines = []
        return event


def iter_sse_events(lines: Iterable[str | bytes]) -> Iterator[SseEvent]:
    """Yield ``(event_type, data)`` pairs from SSE text lines."""
    parser = _FrameParser()
    for line in lines:
        event = parser.feed(line)
        if event is not None:
            yield event
    event = parser.flush()
    if event is not None:
        yield event


async def aiter_sse_events(lines: AsyncIterable[str | bytes]) -> AsyncIterator[SseEvent]:
    """Async twin of :func:`iter_sse_events` (e.g. over ``httpx.Response.aiter_lines()``)."""
    parser = _FrameParser()
    async for line in lines:
        event = parser.feed(line)
        if event is not None:
            yield event
    event = parser.flush()
    if event is not None:
        yield event


def iter_response_lines(response: Any) -> Iterator[str]:
    """Yield decoded text lines from a streaming ``requests`` response.

    Reads with ``iter_content(chunk_size=None)`` so each network chunk is
    delivered as soon as it arrives, instead of waiting for a fixed-size
    buffer to fill (which would delay low-rate event streams).
    """
    buf = b""
    for chunk in response.iter_content(chunk_size=None):
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            yield line.decode("utf-8", errors="replace")
    if buf:
        yield buf.decode("utf-8", errors="replace")
