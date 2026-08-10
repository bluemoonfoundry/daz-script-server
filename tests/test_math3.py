"""
Unit tests for dazpy.math3 — AxisRemap coordinate-space conversion.

No server or DAZ Studio required.

Run standalone:  python tests/test_math3.py
Via runner:      python tests.py unit
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from dazpy.math3 import AxisRemap, Vec3


class TestAxisRemapConstruction(unittest.TestCase):
    def test_identity_remap_is_valid(self):
        remap = AxisRemap(x="x", y="y", z="z")
        self.assertEqual(remap.apply_vec3(Vec3(1, 2, 3)), Vec3(1, 2, 3))

    def test_rejects_invalid_axis_name(self):
        with self.assertRaises(ValueError):
            AxisRemap(x="q", y="y", z="z")

    def test_rejects_duplicate_axis_reference(self):
        with self.assertRaises(ValueError):
            AxisRemap(x="y", y="y", z="z")

    def test_rejects_missing_axis_reference(self):
        # x and y both read from 'x' (duplicate), 'z' never referenced.
        with self.assertRaises(ValueError):
            AxisRemap(x="x", y="x", z="y")

    def test_accepts_signed_axis_names(self):
        remap = AxisRemap(x="-x", y="y", z="z")
        self.assertEqual(remap.apply_vec3(Vec3(1, 2, 3)), Vec3(-1, 2, 3))

    def test_is_immutable(self):
        remap = AxisRemap(x="x", y="y", z="z")
        with self.assertRaises(AttributeError):
            remap._det = 5.0


class TestAxisRemapApplyVec3(unittest.TestCase):
    def test_y_up_to_z_up_preset_maps_up_to_z(self):
        remap = AxisRemap(x="x", y="-z", z="y")
        self.assertEqual(remap.apply_vec3(Vec3(0, 1, 0)), Vec3(0, 0, 1))

    def test_y_up_to_z_up_preset_maps_forward_to_negative_y(self):
        remap = AxisRemap(x="x", y="-z", z="y")
        self.assertEqual(remap.apply_vec3(Vec3(0, 0, 1)), Vec3(0, -1, 0))

    def test_reflection_remap_applies_to_vec3(self):
        # Swapping x and y with no sign flip is a reflection (det == -1),
        # but apply_vec3 must still work.
        remap = AxisRemap(x="y", y="x", z="z")
        self.assertEqual(remap.apply_vec3(Vec3(1, 2, 3)), Vec3(2, 1, 3))


if __name__ == "__main__":
    unittest.main()
