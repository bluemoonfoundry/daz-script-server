"""
Unit tests for dazpy.math3 — AxisRemap coordinate-space conversion.

No server or DAZ Studio required.

Run standalone:  python tests/test_math3.py
Via runner:      python tests.py unit
"""

import itertools
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from dazpy.math3 import AxisRemap, BoundingBox, Quat, Vec3


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


class TestAxisRemapApplyQuat(unittest.TestCase):
    def test_identity_remap_leaves_quat_unchanged(self):
        remap = AxisRemap(x="x", y="y", z="z")
        q = Quat.from_axis_angle(Vec3(0, 1, 0), 90)
        result = remap.apply_quat(q)
        self.assertAlmostEqual(result.x, q.x, places=9)
        self.assertAlmostEqual(result.y, q.y, places=9)
        self.assertAlmostEqual(result.z, q.z, places=9)
        self.assertAlmostEqual(result.w, q.w, places=9)

    def test_y_up_to_z_up_rotates_rotation_axis_consistently(self):
        # A rotation about the Y-up "up" axis should become a rotation about
        # the Z-up "up" axis, applied to the correspondingly-remapped vector.
        remap = AxisRemap(x="x", y="-z", z="y")
        q = Quat.from_axis_angle(Vec3(0, 1, 0), 90)  # rotate 90 deg around Y-up
        v = Vec3(1, 0, 0)

        rotated_then_remapped = remap.apply_vec3(q.rotate(v))
        remapped_then_rotated = remap.apply_quat(q).rotate(remap.apply_vec3(v))

        self.assertAlmostEqual(rotated_then_remapped.x, remapped_then_rotated.x, places=9)
        self.assertAlmostEqual(rotated_then_remapped.y, remapped_then_rotated.y, places=9)
        self.assertAlmostEqual(rotated_then_remapped.z, remapped_then_rotated.z, places=9)

    def test_reflection_remap_rejects_apply_quat(self):
        remap = AxisRemap(x="y", y="x", z="z")  # det == -1
        q = Quat.identity()
        with self.assertRaises(ValueError):
            remap.apply_quat(q)


class TestAxisRemapApplyBbox(unittest.TestCase):
    def test_identity_remap_leaves_bbox_unchanged(self):
        remap = AxisRemap(x="x", y="y", z="z")
        box = BoundingBox(Vec3(-1, -2, -3), Vec3(1, 2, 3))
        result = remap.apply_bbox(box)
        self.assertEqual(result.min, box.min)
        self.assertEqual(result.max, box.max)

    def test_sign_flip_keeps_min_max_correctly_ordered(self):
        # y='-z' -> negating z means the box's old z-max becomes the new
        # y-min, so apply_bbox must re-sort per axis, not just remap corners.
        remap = AxisRemap(x="x", y="-z", z="y")
        box = BoundingBox(Vec3(0, 0, 0), Vec3(1, 2, 3))
        result = remap.apply_bbox(box)
        self.assertEqual(result.min, Vec3(0, -3, 0))
        self.assertEqual(result.max, Vec3(1, 0, 2))


class TestAxisRemapEquality(unittest.TestCase):
    def test_equal_specs_are_equal_and_hash_equal(self):
        a = AxisRemap(x="x", y="-z", z="y")
        b = AxisRemap(x="x", y="-z", z="y")
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))

    def test_different_specs_are_unequal(self):
        a = AxisRemap(x="x", y="y", z="z")
        b = AxisRemap(x="x", y="-z", z="y")
        self.assertNotEqual(a, b)

    def test_eq_against_other_type_is_not_implemented(self):
        remap = AxisRemap(x="x", y="y", z="z")
        self.assertNotEqual(remap, "not a remap")


class TestMat3ToQuatBranchCoverage(unittest.TestCase):
    """Sweeps all 24 proper (det == +1) signed axis permutations so every
    branch of dazpy.math3._mat3_to_quat (trace>0 and the three
    diagonal-dominant cases) gets exercised, not just trace>0.
    """

    AXES = ("x", "y", "z")
    _PROBE_VECTORS = (Vec3(1, 0, 0), Vec3(0, 1, 0), Vec3(0, 0, 1), Vec3(1, 2, 3))

    @classmethod
    def _proper_remaps(cls):
        remaps = []
        for perm in itertools.permutations(cls.AXES):
            for signs in itertools.product((1, -1), repeat=3):
                specs = [("-" if s < 0 else "") + axis for axis, s in zip(perm, signs)]
                remap = AxisRemap(x=specs[0], y=specs[1], z=specs[2])
                if remap._rotation_quat is not None:
                    remaps.append(remap)
        return remaps

    def test_exactly_24_proper_permutations_exist(self):
        # 3! axis orderings * 2^3 sign choices = 48 total; exactly half
        # (24) have determinant +1 (proper rotations).
        self.assertEqual(len(self._proper_remaps()), 24)

    def test_rotation_quat_matches_matrix_for_all_proper_permutations(self):
        for remap in self._proper_remaps():
            q = remap._rotation_quat
            for v in self._PROBE_VECTORS:
                expected = remap.apply_vec3(v)
                actual = q.rotate(v)
                self.assertAlmostEqual(actual.x, expected.x, places=9, msg=repr(remap))
                self.assertAlmostEqual(actual.y, expected.y, places=9, msg=repr(remap))
                self.assertAlmostEqual(actual.z, expected.z, places=9, msg=repr(remap))

    def test_rotation_quat_is_unit_length_for_all_proper_permutations(self):
        for remap in self._proper_remaps():
            self.assertAlmostEqual(remap._rotation_quat.length(), 1.0, places=9, msg=repr(remap))


class TestYUpToZUpPreset(unittest.TestCase):
    def test_preset_matches_manual_equivalent(self):
        manual = AxisRemap(x="x", y="-z", z="y")
        from dazpy.math3 import Y_UP_TO_Z_UP
        self.assertEqual(Y_UP_TO_Z_UP.apply_vec3(Vec3(1, 2, 3)), manual.apply_vec3(Vec3(1, 2, 3)))

    def test_preset_importable_from_dazpy_package(self):
        from dazpy import AxisRemap as PkgAxisRemap
        from dazpy import Y_UP_TO_Z_UP as PkgPreset
        self.assertIsInstance(PkgPreset, PkgAxisRemap)


# Captured live from DAZ Studio 4 (Genesis 9, 2026-11-19, bd 0pga): rotation
# channel values as Studio applied them (after joint limits), the bone's
# getRotationOrder()/getOrientation(), and the resulting getLocalRot().
_LIVE_BONES = [
    {"name": "l_hand", "order": "XYZ", "vals": (10, 30, 20),
     "orient": {"w": 0.926597115209923, "x": 0.0342056607995472, "y": 0.11667538626529, "z": 0.355857574169442},
     "local": {"w": 0.951548532113196, "x": -0.178874742342876, "y": -0.196265627486259, "z": -0.155045222604303}},
    {"name": "l_thigh", "order": "YZX", "vals": (30, 50, 20),
     "orient": {"w": 0.998708501902959, "x": -0.0158161208513694, "y": -0.0435336276449156, "z": -0.0208806564081596},
     "local": {"w": 0.881120356041757, "x": -0.167559419586953, "y": -0.35995317082981, "z": -0.256874432137761}},
    {"name": "l_upperarm", "order": "XYZ", "vals": (30, 40, 20),
     "orient": {"w": 0.913774293765234, "x": -0.00570622770112479, "y": 0.013546899678335, "z": 0.405956229818408},
     "local": {"w": 0.909255368408199, "x": -0.392627261813084, "y": -0.111276994846015, "z": -0.0819508311127546}},
]


def _same_rotation(a, b, tol=1e-6):
    d = max(abs(a.x - b.x), abs(a.y - b.y), abs(a.z - b.z), abs(a.w - b.w))
    e = max(abs(a.x + b.x), abs(a.y + b.y), abs(a.z + b.z), abs(a.w + b.w))
    return min(d, e) < tol


class TestDzQuatConvention(unittest.TestCase):
    """DzQuat stores the conjugate of the math3 quaternion for the same rotation."""

    def test_from_dz_conjugates(self):
        q = Quat.from_dz({"x": 0.1, "y": -0.2, "z": 0.3, "w": 0.9})
        self.assertEqual((q.x, q.y, q.z, q.w), (-0.1, 0.2, -0.3, 0.9))

    def test_to_dz_round_trips(self):
        d = {"x": 0.1, "y": -0.2, "z": 0.3, "w": 0.9}
        self.assertEqual(Quat.from_dz(d).to_dz(), d)

    def test_camera_from_dz_euler_identity_orientation(self):
        # Camera (no orientation, Studio order XYZ): live getLocalRot() was
        # conj(from_euler(x, y, z, "ZYX")).
        dz = Quat.from_euler(30, 50, 20, order="ZYX").conjugate().to_dict()
        q = Quat.from_dz_euler(30, 50, 20, "XYZ")
        self.assertTrue(_same_rotation(q, Quat.from_dz(dz)))

    def test_bones_from_dz_euler_match_live_local_rot(self):
        for b in _LIVE_BONES:
            with self.subTest(bone=b["name"]):
                q = Quat.from_dz_euler(*b["vals"], b["order"], orientation=Quat.from_dz(b["orient"]))
                self.assertTrue(_same_rotation(q, Quat.from_dz(b["local"]), tol=1e-6), b["name"])

    def test_to_dz_euler_inverts_from_dz_euler(self):
        for b in _LIVE_BONES:
            with self.subTest(bone=b["name"]):
                o = Quat.from_dz(b["orient"])
                q = Quat.from_dz_euler(*b["vals"], b["order"], orientation=o)
                x, y, z = q.to_dz_euler(b["order"], orientation=o)
                for got, want in zip((x, y, z), b["vals"]):
                    self.assertAlmostEqual(got, want, places=6)

    def test_rejects_bad_rotation_order(self):
        with self.assertRaises(ValueError):
            Quat.from_dz_euler(0, 0, 0, "XXY")


if __name__ == "__main__":
    unittest.main()
