"""Unit tests for tests/fixtures/rendering/sprite_matrix/canvas_convert.py's
multiply_blend() lineart composite helper.

No live Daz Studio or ComfyUI required -- exercises the pure OpenCV/numpy
blend math against small synthetic in-memory images written to temp files.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

import cv2
import numpy as np

_SPRITE_MATRIX_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "rendering", "sprite_matrix"
)
sys.path.insert(0, _SPRITE_MATRIX_DIR)

from canvas_convert import multiply_blend  # noqa: E402


class TestMultiplyBlend(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

    def _path(self, name):
        return os.path.join(self._tmpdir.name, name)

    def _write_color(self, bgr_value=(60, 120, 200), size=(8, 8)):
        img = np.full((size[0], size[1], 3), bgr_value, dtype=np.uint8)
        path = self._path("color.png")
        cv2.imwrite(path, img)
        return path

    def _write_lineart(self, values, size=(8, 8)):
        """values: single scalar (uniform) or a 2D array of gray values."""
        if np.isscalar(values):
            img = np.full(size, values, dtype=np.uint8)
        else:
            img = np.array(values, dtype=np.uint8)
        path = self._path("lineart.png")
        cv2.imwrite(path, img)
        return path

    def test_opacity_zero_is_noop(self):
        color_path = self._write_color(bgr_value=(60, 120, 200))
        # Half-black/half-white lineart -- should not matter at opacity=0.
        lineart = np.zeros((8, 8), dtype=np.uint8)
        lineart[:, 4:] = 255
        lineart_path = self._write_lineart(lineart)
        out_path = self._path("out.png")

        result_path = multiply_blend(color_path, lineart_path, 0.0, out_path)
        self.assertEqual(result_path, out_path)

        color_img = cv2.imread(color_path, cv2.IMREAD_COLOR)
        out_img = cv2.imread(out_path, cv2.IMREAD_COLOR)
        np.testing.assert_array_equal(out_img, color_img)

    def test_opacity_one_full_multiply(self):
        color_value = (60, 120, 200)
        color_path = self._write_color(bgr_value=color_value)
        lineart = np.zeros((8, 8), dtype=np.uint8)
        lineart[:, 4:] = 255  # left half black line, right half white background
        lineart_path = self._write_lineart(lineart)
        out_path = self._path("out.png")

        multiply_blend(color_path, lineart_path, 1.0, out_path)
        out_img = cv2.imread(out_path, cv2.IMREAD_COLOR)

        # Under the black lineart pixel (L=0): full multiply darkens to 0.
        np.testing.assert_array_equal(out_img[0, 0], [0, 0, 0])
        # Under the white lineart pixel (L=255): full multiply leaves color unchanged.
        np.testing.assert_array_equal(out_img[0, 7], list(color_value))

    def test_mid_opacity_between_unblended_and_full(self):
        color_value = (60, 120, 200)
        color_path = self._write_color(bgr_value=color_value)
        lineart_path = self._write_lineart(0)  # uniform black line everywhere
        out_path = self._path("out.png")

        multiply_blend(color_path, lineart_path, 0.5, out_path)
        out_img = cv2.imread(out_path, cv2.IMREAD_COLOR)
        pixel = out_img[0, 0].astype(np.int32)

        color_arr = np.array(color_value, dtype=np.int32)
        full_multiply = np.zeros(3, dtype=np.int32)  # L=0 everywhere -> C*L/255 == 0

        # Mid-opacity result should sit strictly between the unblended color
        # and the fully-multiplied (here: black) result, on every channel.
        for c, unblended, full in zip(pixel, color_arr, full_multiply):
            self.assertLess(c, unblended)
            self.assertGreater(c, full)

    def test_resizes_mismatched_lineart(self):
        color_path = self._write_color(bgr_value=(60, 120, 200), size=(8, 8))
        lineart_path = self._write_lineart(0, size=(4, 4))  # smaller than color
        out_path = self._path("out.png")

        result_path = multiply_blend(color_path, lineart_path, 1.0, out_path)
        out_img = cv2.imread(result_path, cv2.IMREAD_COLOR)
        self.assertEqual(out_img.shape[:2], (8, 8))


if __name__ == "__main__":
    unittest.main()
