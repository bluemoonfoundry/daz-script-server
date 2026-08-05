"""Unit tests for docs/examples/rendering/sprite_matrix/render_util.py.

No live Daz Studio required -- exercises the canvas-quirk workaround
(render twice when canvases are requested) against a mock DazRenderSettings.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock

_SPRITE_MATRIX_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "docs", "examples", "rendering", "sprite_matrix"
)
sys.path.insert(0, _SPRITE_MATRIX_DIR)

from render_util import render_beauty_and_canvases  # noqa: E402


def _mock_rs(outcomes):
    rs = MagicMock()
    rs.render.side_effect = outcomes
    return rs


class TestRenderBeautyAndCanvases(unittest.TestCase):
    def test_no_canvases_renders_once_with_canvases_disabled(self):
        outcome = MagicMock(success=True)
        rs = _mock_rs([outcome])
        result = render_beauty_and_canvases(rs, output_path="/out/front.png", camera_label="Front", canvases=())
        self.assertIs(result, outcome)
        self.assertEqual(rs.render.call_count, 1)
        self.assertFalse(rs.canvases_enabled)
        self.assertEqual(rs.output_path, "/out/front.png")

    def test_with_canvases_renders_twice(self):
        first = MagicMock(success=True)
        second = MagicMock(success=True)
        rs = _mock_rs([first, second])
        result = render_beauty_and_canvases(
            rs, output_path="/out/front.png", camera_label="Front", canvases=("Normal", "Depth")
        )
        self.assertIs(result, second)
        self.assertEqual(rs.render.call_count, 2)

    def test_canvases_enabled_toggled_true_then_false(self):
        rs = _mock_rs([MagicMock(success=True), MagicMock(success=True)])
        toggled = []
        type(rs).canvases_enabled = property(
            lambda self: None, lambda self, v: toggled.append(v)
        )
        render_beauty_and_canvases(rs, output_path="/out/front.png", camera_label="Front", canvases=("Normal",))
        self.assertEqual(toggled, [True, False])

    def test_stops_after_first_pass_if_it_fails(self):
        failed = MagicMock(success=False)
        rs = _mock_rs([failed])
        result = render_beauty_and_canvases(
            rs, output_path="/out/front.png", camera_label="Front", canvases=("Normal",)
        )
        self.assertIs(result, failed)
        self.assertEqual(rs.render.call_count, 1)

    def test_camera_label_passed_through(self):
        outcome = MagicMock(success=True)
        rs = _mock_rs([outcome])
        render_beauty_and_canvases(rs, output_path="/out/front.png", camera_label="Front Camera", canvases=())
        rs.render.assert_called_once_with(camera_label="Front Camera")


if __name__ == "__main__":
    unittest.main(verbosity=2)
