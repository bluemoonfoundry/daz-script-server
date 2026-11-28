"""Unit tests for dazpy._sse — the one SSE frame parser shared by the sync
render stream, the async client and the scene-event watcher (W30)."""

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from dazpy._sse import aiter_sse_events, iter_response_lines, iter_sse_events


async def _alines(lines):
    for line in lines:
        yield line


def _acollect(lines):
    async def run():
        return [ev async for ev in aiter_sse_events(_alines(lines))]
    return asyncio.run(run())


class TestIterSseEvents(unittest.TestCase):
    def test_event_field_and_blank_line_dispatch(self):
        lines = ["event: progress", 'data: {"percent": 5}', "",
                 'data: {"x": 1}', ""]
        self.assertEqual(list(iter_sse_events(lines)),
                         [("progress", {"percent": 5}), ("message", {"x": 1})])

    def test_event_type_resets_after_dispatch(self):
        lines = ["event: complete", 'data: {}', "", 'data: {}', ""]
        self.assertEqual([t for t, _ in iter_sse_events(lines)], ["complete", "message"])

    def test_multiline_data_joined_with_newline(self):
        lines = ['data: {"a":', 'data: 1}', ""]
        self.assertEqual(list(iter_sse_events(lines)), [("message", {"a": 1})])

    def test_malformed_json_yields_raw(self):
        self.assertEqual(list(iter_sse_events(["data: not json", ""])),
                         [("message", {"_raw": "not json"})])

    def test_comments_and_empty_frames_skipped(self):
        lines = [": keepalive", "", "event: progress", "", 'data: {"ok": true}', ""]
        # An event: line with no data dispatches nothing, but it still sets
        # the type for the data that follows before the next blank line.
        self.assertEqual(list(iter_sse_events(lines)), [("message", {"ok": True})])

    def test_final_event_flushed_at_end_of_stream(self):
        self.assertEqual(list(iter_sse_events(["event: complete", 'data: {"done": 1}'])),
                         [("complete", {"done": 1})])

    def test_bytes_and_crlf_lines_accepted(self):
        lines = [b"event: progress\r", b'data: {"p": 1}\r', b"\r"]
        self.assertEqual(list(iter_sse_events(lines)), [("progress", {"p": 1})])

    def test_async_matches_sync(self):
        lines = ["event: progress", 'data: {"p": 1}', "", ": ka", "", "data: bad",
                 "", "event: complete", 'data: {"done": true}']
        self.assertEqual(_acollect(lines), list(iter_sse_events(lines)))


class _ChunkedResponse:
    def __init__(self, chunks):
        self._chunks = chunks

    def iter_content(self, chunk_size=None):
        assert chunk_size is None  # unbuffered: deliver each chunk as it arrives
        yield from self._chunks


class TestIterResponseLines(unittest.TestCase):
    def test_splits_across_chunk_boundaries(self):
        resp = _ChunkedResponse([b"data: {\"a\"", b": 1}\n\nda", b"ta: 2\n"])
        self.assertEqual(list(iter_response_lines(resp)), ['data: {"a": 1}', "", "data: 2"])

    def test_trailing_partial_line_yielded(self):
        resp = _ChunkedResponse([b"data: 1\n", b"data: 2"])
        self.assertEqual(list(iter_response_lines(resp)), ["data: 1", "data: 2"])

    def test_invalid_utf8_replaced(self):
        self.assertEqual(list(iter_response_lines(_ChunkedResponse([b"\xff\n"]))), ["�"])


class TestSceneEventsUseSharedParser(unittest.TestCase):
    def _parse(self, body: bytes):
        from dazpy._scene_events import _parse_scene_events
        return list(_parse_scene_events(_ChunkedResponse([body])))

    def test_malformed_and_non_object_payloads_dropped(self):
        body = (b"data: not json\n\n"
                b"data: [1, 2]\n\n"
                b'data: {"type": "node.added", "ts": 7, "data": {"n": 1}}\n\n')
        events = self._parse(body)
        self.assertEqual([(e.type, e.ts, e.data) for e in events], [("node.added", 7, {"n": 1})])

    def test_multiline_data_is_one_event(self):
        body = b'data: {"type": "scene.loaded",\ndata:  "ts": 1}\n\n'
        self.assertEqual([e.type for e in self._parse(body)], ["scene.loaded"])


if __name__ == "__main__":
    unittest.main()
