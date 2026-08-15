"""Unit tests for dazpy._render_api.render()'s on_progress callback — mocked DazClient, no server required."""

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from dazpy._render_api import render
from dazpy.exceptions import RenderError


def _sse_response(lines: list[bytes]):
    resp = MagicMock()
    resp.iter_lines.return_value = lines
    return resp


class TestRenderOnProgress(unittest.TestCase):
    def test_animation_progress_events_forwarded(self):
        client = MagicMock()
        client.render_submit.return_value = {"request_id": "rnd-1"}
        client.stream_render_progress.return_value = _sse_response([
            b'event: progress',
            b'data: {"request_id": "rnd-1", "percent": 0.0, "frame": 1, "total_frames": 4}',
            b'',
            b'event: progress',
            b'data: {"request_id": "rnd-1", "percent": 25.0, "frame": 2, "total_frames": 4}',
            b'',
            b'event: complete',
            b'data: {"output_path": "C:/out_0001.png", "file_size_bytes": 100, "duration_ms": 500}',
            b'',
        ])

        seen: list[dict] = []
        result = render(
            client, "C:/out_{frame}.png",
            on_progress=seen.append,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.output_path, "C:/out_0001.png")
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0]["frame"], 1)
        self.assertEqual(seen[1]["percent"], 25.0)

    def test_on_progress_not_required(self):
        client = MagicMock()
        client.render_submit.return_value = {"request_id": "r1"}
        client.stream_render_progress.return_value = _sse_response([
            b'event: complete',
            b'data: {"output_path": "C:/out.png"}',
            b'',
        ])
        result = render(client, "C:/out.png")
        self.assertTrue(result.success)

    def test_error_event_raises_without_calling_on_progress(self):
        client = MagicMock()
        client.render_submit.return_value = {"request_id": "r1"}
        client.stream_render_progress.return_value = _sse_response([
            b'event: progress',
            b'data: {"percent": 0.0}',
            b'',
            b'event: error',
            b'data: {"error": "Iray render failed"}',
            b'',
        ])
        seen: list[dict] = []
        with self.assertRaises(RenderError):
            render(client, "C:/out.png", on_progress=seen.append)
        self.assertEqual(len(seen), 1)


if __name__ == "__main__":
    unittest.main()
