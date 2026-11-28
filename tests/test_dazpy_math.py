"""dazpy unit tests: Vec3, Quat, BoundingBox and shot-geometry math.

Mock-based; no server or DAZ Studio required.
Shared fakes live in tests/dazpy_fakes.py.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))



# ══════════════════════════════════════════════════════════════════════════════
# math3 — Vec3, Quat, BoundingBox
# ══════════════════════════════════════════════════════════════════════════════

class TestVec3(unittest.TestCase):

    def _v(self, x=1.0, y=2.0, z=3.0):
        from dazpy import Vec3
        return Vec3(x, y, z)

    def test_construction_and_components(self):
        v = self._v(1, 2, 3)
        self.assertAlmostEqual(v.x, 1.0)
        self.assertAlmostEqual(v.y, 2.0)
        self.assertAlmostEqual(v.z, 3.0)

    def test_immutable(self):
        from dazpy import Vec3
        v = Vec3(1, 2, 3)
        with self.assertRaises(AttributeError):
            v.x = 9

    def test_from_dict(self):
        from dazpy import Vec3
        v = Vec3.from_dict({"x": 1, "y": 2, "z": 3})
        self.assertEqual(v, Vec3(1, 2, 3))

    def test_from_list(self):
        from dazpy import Vec3
        v = Vec3.from_list([4, 5, 6])
        self.assertEqual(v, Vec3(4, 5, 6))

    def test_zero(self):
        from dazpy import Vec3
        v = Vec3.zero()
        self.assertEqual(v, Vec3(0, 0, 0))

    def test_to_dict(self):
        v = self._v(1, 2, 3)
        self.assertEqual(v.to_dict(), {"x": 1.0, "y": 2.0, "z": 3.0})

    def test_to_list(self):
        v = self._v(1, 2, 3)
        self.assertEqual(v.to_list(), [1.0, 2.0, 3.0])

    def test_add(self):
        from dazpy import Vec3
        r = Vec3(1, 2, 3) + Vec3(4, 5, 6)
        self.assertEqual(r, Vec3(5, 7, 9))

    def test_sub(self):
        from dazpy import Vec3
        r = Vec3(4, 5, 6) - Vec3(1, 2, 3)
        self.assertEqual(r, Vec3(3, 3, 3))

    def test_mul_scalar(self):
        from dazpy import Vec3
        r = Vec3(1, 2, 3) * 2.0
        self.assertEqual(r, Vec3(2, 4, 6))

    def test_rmul_scalar(self):
        from dazpy import Vec3
        r = 3.0 * Vec3(1, 2, 3)
        self.assertEqual(r, Vec3(3, 6, 9))

    def test_div_scalar(self):
        from dazpy import Vec3
        r = Vec3(2, 4, 6) / 2.0
        self.assertEqual(r, Vec3(1, 2, 3))

    def test_neg(self):
        from dazpy import Vec3
        r = -Vec3(1, 2, 3)
        self.assertEqual(r, Vec3(-1, -2, -3))

    def test_dot(self):
        from dazpy import Vec3
        r = Vec3(1, 0, 0).dot(Vec3(0, 1, 0))
        self.assertAlmostEqual(r, 0.0)
        r2 = Vec3(1, 2, 3).dot(Vec3(4, 5, 6))
        self.assertAlmostEqual(r2, 32.0)

    def test_cross_orthogonal(self):
        from dazpy import Vec3
        r = Vec3(1, 0, 0).cross(Vec3(0, 1, 0))
        self.assertAlmostEqual(r.x, 0.0)
        self.assertAlmostEqual(r.y, 0.0)
        self.assertAlmostEqual(r.z, 1.0)

    def test_length(self):
        from dazpy import Vec3
        self.assertAlmostEqual(Vec3(3, 4, 0).length(), 5.0)

    def test_normalize(self):
        from dazpy import Vec3
        n = Vec3(3, 0, 0).normalize()
        self.assertAlmostEqual(n.x, 1.0)
        self.assertAlmostEqual(n.length(), 1.0)

    def test_normalize_zero_vector(self):
        from dazpy import Vec3
        n = Vec3(0, 0, 0).normalize()
        self.assertEqual(n, Vec3(0, 0, 0))

    def test_distance(self):
        from dazpy import Vec3
        self.assertAlmostEqual(Vec3(0, 0, 0).distance(Vec3(3, 4, 0)), 5.0)

    def test_lerp_midpoint(self):
        from dazpy import Vec3
        r = Vec3(0, 0, 0).lerp(Vec3(2, 4, 6), 0.5)
        self.assertAlmostEqual(r.x, 1.0)
        self.assertAlmostEqual(r.y, 2.0)
        self.assertAlmostEqual(r.z, 3.0)

    def test_lerp_identity(self):
        from dazpy import Vec3
        v = Vec3(1, 2, 3)
        self.assertEqual(v.lerp(Vec3(4, 5, 6), 0.0), v)

    def test_reflect(self):
        from dazpy import Vec3
        incoming = Vec3(1, -1, 0).normalize()
        normal   = Vec3(0, 1, 0)
        r = incoming.reflect(normal)
        self.assertAlmostEqual(r.y, -incoming.y, places=5)

    def test_repr(self):
        from dazpy import Vec3
        s = repr(Vec3(1, 2, 3))
        self.assertIn("Vec3", s)


class TestQuat(unittest.TestCase):

    def _approx_quat(self, q1, q2, places=5):
        """Assert two quats are equal (allowing sign flip)."""
        d = abs(q1.x*q2.x + q1.y*q2.y + q1.z*q2.z + q1.w*q2.w)
        self.assertAlmostEqual(d, 1.0, places=places)

    def test_identity(self):
        from dazpy import Quat
        q = Quat.identity()
        self.assertAlmostEqual(q.w, 1.0)
        self.assertAlmostEqual(q.x, 0.0)

    def test_immutable(self):
        from dazpy import Quat
        q = Quat.identity()
        with self.assertRaises(AttributeError):
            q.w = 0

    def test_from_dict(self):
        from dazpy import Quat
        q = Quat.from_dict({"x": 0, "y": 0, "z": 0, "w": 1})
        self.assertEqual(q, Quat.identity())

    def test_to_dict(self):
        from dazpy import Quat
        q = Quat(0, 0, 0, 1)
        d = q.to_dict()
        self.assertIn("w", d)
        self.assertAlmostEqual(d["w"], 1.0)

    def test_normalize_unit(self):
        from dazpy import Quat
        q = Quat(1, 0, 0, 0).normalize()
        self.assertAlmostEqual(q.length(), 1.0)

    def test_conjugate(self):
        from dazpy import Quat
        q = Quat(1, 2, 3, 4).normalize()
        c = q.conjugate()
        self.assertAlmostEqual(c.x, -q.x)
        self.assertAlmostEqual(c.w, q.w)

    def test_multiply_identity(self):
        from dazpy import Quat
        qi = Quat.identity()
        from dazpy import Vec3
        ax = Quat.from_axis_angle(Vec3(0, 1, 0), 45)
        self.assertAlmostEqual((ax.multiply(qi)).x, ax.x, places=6)

    def test_from_axis_angle_90_x(self):
        from dazpy import Quat, Vec3
        import math
        q = Quat.from_axis_angle(Vec3(1, 0, 0), 90)
        self.assertAlmostEqual(q.x, math.sin(math.radians(45)), places=6)
        self.assertAlmostEqual(q.w, math.cos(math.radians(45)), places=6)

    def test_rotate_x_axis(self):
        from dazpy import Quat, Vec3
        q = Quat.from_axis_angle(Vec3(0, 0, 1), 90)
        v = q.rotate(Vec3(1, 0, 0))
        self.assertAlmostEqual(v.x, 0.0, places=5)
        self.assertAlmostEqual(v.y, 1.0, places=5)
        self.assertAlmostEqual(v.z, 0.0, places=5)

    def test_slerp_t0_identity(self):
        from dazpy import Quat, Vec3
        a = Quat.identity()
        b = Quat.from_axis_angle(Vec3(0, 1, 0), 90)
        r = a.slerp(b, 0.0)
        self._approx_quat(r, a)

    def test_slerp_t1_target(self):
        from dazpy import Quat, Vec3
        a = Quat.identity()
        b = Quat.from_axis_angle(Vec3(0, 1, 0), 90)
        r = a.slerp(b, 1.0)
        self._approx_quat(r, b)

    def test_slerp_midpoint_half_angle(self):
        from dazpy import Quat, Vec3
        a = Quat.identity()
        b = Quat.from_axis_angle(Vec3(0, 1, 0), 90)
        mid = a.slerp(b, 0.5)
        expected = Quat.from_axis_angle(Vec3(0, 1, 0), 45)
        self._approx_quat(mid, expected)

    def test_slerp_identical_quats(self):
        from dazpy import Quat, Vec3
        q = Quat.from_axis_angle(Vec3(1, 0, 0), 30)
        r = q.slerp(q, 0.5)
        self._approx_quat(r, q)

    def test_to_matrix_identity(self):
        from dazpy import Quat
        m = Quat.identity().to_matrix()
        for r in range(3):
            for c in range(3):
                expected = 1.0 if r == c else 0.0
                self.assertAlmostEqual(m[r][c], expected, places=6)

    # ── Euler round-trip for all 6 orders ─────────────────────────────────────

    def _euler_roundtrip(self, x, y, z, order):
        from dazpy import Quat
        q = Quat.from_euler(x, y, z, order)
        x2, y2, z2 = q.to_euler(order)
        q2 = Quat.from_euler(x2, y2, z2, order)
        self._approx_quat(q, q2)

    def test_euler_roundtrip_XYZ(self):
        self._euler_roundtrip(10, 20, 30, "XYZ")

    def test_euler_roundtrip_XZY(self):
        self._euler_roundtrip(10, 20, 30, "XZY")

    def test_euler_roundtrip_YXZ(self):
        self._euler_roundtrip(10, 20, 30, "YXZ")

    def test_euler_roundtrip_YZX(self):
        self._euler_roundtrip(10, 20, 30, "YZX")

    def test_euler_roundtrip_ZXY(self):
        self._euler_roundtrip(10, 20, 30, "ZXY")

    def test_euler_roundtrip_ZYX(self):
        self._euler_roundtrip(10, 20, 30, "ZYX")
        self._euler_roundtrip(10, 20, 15, "ZYX")
        self._euler_roundtrip(-25, 40, 65, "ZYX")

    def test_from_euler_ZYX_w_sign(self):
        # Regression test for daz-script-server-z0c1: the ZYX branch of
        # _euler_to_quat previously flipped the sign on the sx*sy*sz term,
        # producing the wrong w. Verify against the Hamilton product of the
        # per-axis quaternions (qz.multiply(qy).multiply(qx)), independent of
        # _euler_to_quat's own formula.
        from dazpy import Quat, Vec3
        x, y, z = 10, 20, 15
        qx = Quat.from_axis_angle(Vec3(1, 0, 0), x)
        qy = Quat.from_axis_angle(Vec3(0, 1, 0), y)
        qz = Quat.from_axis_angle(Vec3(0, 0, 1), z)
        expected = qz.multiply(qy).multiply(qx)
        actual = Quat.from_euler(x, y, z, "ZYX")
        self._approx_quat(actual, expected)

    def test_euler_identity_is_no_rotation(self):
        from dazpy import Quat
        q = Quat.from_euler(0, 0, 0, "XYZ")
        self._approx_quat(q, Quat.identity())

    def test_from_euler_invalid_order(self):
        from dazpy import Quat
        with self.assertRaises(ValueError):
            Quat.from_euler(10, 20, 30, "ABC")

    def test_repr(self):
        from dazpy import Quat
        self.assertIn("Quat", repr(Quat.identity()))


class TestBoundingBox(unittest.TestCase):

    def _box(self):
        from dazpy import BoundingBox, Vec3
        return BoundingBox(Vec3(0, 0, 0), Vec3(2, 4, 6))

    def test_from_dict(self):
        from dazpy import BoundingBox
        d = {"min": {"x": 0, "y": 0, "z": 0}, "max": {"x": 1, "y": 1, "z": 1}}
        bb = BoundingBox.from_dict(d)
        self.assertAlmostEqual(bb.max.x, 1.0)

    def test_to_dict_roundtrip(self):
        bb = self._box()
        d = bb.to_dict()
        from dazpy import BoundingBox
        bb2 = BoundingBox.from_dict(d)
        self.assertAlmostEqual(bb2.min.x, bb.min.x)
        self.assertAlmostEqual(bb2.max.z, bb.max.z)

    def test_from_points(self):
        from dazpy import BoundingBox, Vec3
        pts = [Vec3(1, 2, 3), Vec3(-1, 5, 0), Vec3(3, 0, 7)]
        bb = BoundingBox.from_points(pts)
        self.assertAlmostEqual(bb.min.x, -1.0)
        self.assertAlmostEqual(bb.max.z, 7.0)

    def test_from_points_single(self):
        from dazpy import BoundingBox, Vec3
        bb = BoundingBox.from_points([Vec3(1, 2, 3)])
        self.assertAlmostEqual(bb.min.x, bb.max.x)

    def test_from_points_empty_raises(self):
        from dazpy import BoundingBox
        with self.assertRaises(ValueError):
            BoundingBox.from_points([])

    def test_immutable(self):
        bb = self._box()
        with self.assertRaises(AttributeError):
            bb.min = None

    def test_center(self):
        bb = self._box()
        c = bb.center
        self.assertAlmostEqual(c.x, 1.0)
        self.assertAlmostEqual(c.y, 2.0)
        self.assertAlmostEqual(c.z, 3.0)

    def test_size(self):
        bb = self._box()
        s = bb.size
        self.assertAlmostEqual(s.x, 2.0)
        self.assertAlmostEqual(s.y, 4.0)
        self.assertAlmostEqual(s.z, 6.0)

    def test_volume(self):
        bb = self._box()
        self.assertAlmostEqual(bb.volume, 48.0)

    def test_contains_inside(self):
        from dazpy import Vec3
        bb = self._box()
        self.assertTrue(bb.contains(Vec3(1, 2, 3)))

    def test_contains_outside(self):
        from dazpy import Vec3
        bb = self._box()
        self.assertFalse(bb.contains(Vec3(3, 2, 3)))

    def test_contains_surface(self):
        from dazpy import Vec3
        bb = self._box()
        self.assertTrue(bb.contains(Vec3(2, 4, 6)))

    def test_overlaps_true(self):
        from dazpy import BoundingBox, Vec3
        a = BoundingBox(Vec3(0, 0, 0), Vec3(2, 2, 2))
        b = BoundingBox(Vec3(1, 1, 1), Vec3(3, 3, 3))
        self.assertTrue(a.overlaps(b))
        self.assertTrue(b.overlaps(a))

    def test_overlaps_false(self):
        from dazpy import BoundingBox, Vec3
        a = BoundingBox(Vec3(0, 0, 0), Vec3(1, 1, 1))
        b = BoundingBox(Vec3(2, 2, 2), Vec3(3, 3, 3))
        self.assertFalse(a.overlaps(b))

    def test_expand(self):
        bb = self._box()
        e = bb.expand(1.0)
        self.assertAlmostEqual(e.min.x, -1.0)
        self.assertAlmostEqual(e.max.x, 3.0)

    def test_union(self):
        from dazpy import BoundingBox, Vec3
        a = BoundingBox(Vec3(0, 0, 0), Vec3(1, 1, 1))
        b = BoundingBox(Vec3(-1, -1, -1), Vec3(0.5, 0.5, 0.5))
        u = a.union(b)
        self.assertAlmostEqual(u.min.x, -1.0)
        self.assertAlmostEqual(u.max.x, 1.0)

    def test_repr(self):
        self.assertIn("BoundingBox", repr(self._box()))


class TestShotGeometryMath(unittest.TestCase):
    def test_spherical_offset_at_zero_azimuth_elevation(self):
        from dazpy._shot_geometry import spherical_offset
        from dazpy.math3 import Vec3
        result = spherical_offset(Vec3(0, 0, 0), azimuth_deg=0.0, elevation_deg=0.0, distance=150.0)
        self.assertAlmostEqual(result.x, 0.0, places=6)
        self.assertAlmostEqual(result.y, 0.0, places=6)
        self.assertAlmostEqual(result.z, 150.0, places=6)

    def test_spherical_offset_at_90_azimuth(self):
        from dazpy._shot_geometry import spherical_offset
        from dazpy.math3 import Vec3
        result = spherical_offset(Vec3(0, 0, 0), azimuth_deg=90.0, elevation_deg=0.0, distance=150.0)
        self.assertAlmostEqual(result.x, 150.0, places=6)
        self.assertAlmostEqual(result.y, 0.0, places=6)
        self.assertAlmostEqual(result.z, 0.0, places=6)

    def test_spherical_offset_at_90_elevation_ignores_azimuth(self):
        from dazpy._shot_geometry import spherical_offset
        from dazpy.math3 import Vec3
        result = spherical_offset(Vec3(0, 0, 0), azimuth_deg=45.0, elevation_deg=90.0, distance=150.0)
        self.assertAlmostEqual(result.x, 0.0, places=6)
        self.assertAlmostEqual(result.y, 150.0, places=6)
        self.assertAlmostEqual(result.z, 0.0, places=6)

    def test_spherical_offset_is_relative_to_target(self):
        from dazpy._shot_geometry import spherical_offset
        from dazpy.math3 import Vec3
        result = spherical_offset(Vec3(10, 20, 30), azimuth_deg=0.0, elevation_deg=0.0, distance=150.0)
        self.assertAlmostEqual(result.x, 10.0, places=6)
        self.assertAlmostEqual(result.y, 20.0, places=6)
        self.assertAlmostEqual(result.z, 180.0, places=6)

    def test_look_at_euler_default_offset_is_zero_rotation(self):
        from dazpy._shot_geometry import look_at_euler
        from dazpy.math3 import Vec3
        x, y, z = look_at_euler(Vec3(0, 0, 150), Vec3(0, 0, 0))
        self.assertAlmostEqual(x, 0.0, places=6)
        self.assertAlmostEqual(y, 0.0, places=6)
        self.assertAlmostEqual(z, 0.0, places=6)

    def test_look_at_euler_yaws_toward_90_azimuth_offset(self):
        from dazpy._shot_geometry import look_at_euler
        from dazpy.math3 import Vec3
        x, y, z = look_at_euler(Vec3(150, 0, 0), Vec3(0, 0, 0))
        self.assertAlmostEqual(x, 0.0, places=6)
        self.assertAlmostEqual(y, 90.0, places=6)
        self.assertAlmostEqual(z, 0.0, places=6)

    def test_look_at_euler_pitches_up_when_light_is_above(self):
        from dazpy._shot_geometry import look_at_euler
        from dazpy.math3 import Vec3
        x, y, z = look_at_euler(Vec3(0, 150, 0), Vec3(0, 0, 0))
        self.assertAlmostEqual(x, -90.0, places=6)
        self.assertAlmostEqual(z, 0.0, places=6)

    def test_look_at_euler_handles_directly_above_without_error(self):
        # Degenerate case: horizontal component is exactly zero, yaw must
        # default to 0.0 rather than raising or returning NaN.
        from dazpy._shot_geometry import look_at_euler
        from dazpy.math3 import Vec3
        x, y, z = look_at_euler(Vec3(0, 150, 0), Vec3(0, 0, 0))
        self.assertEqual(y, 0.0)

    def test_resolve_target_returns_vec3_unchanged_with_zero_offset(self):
        from dazpy._shot_geometry import resolve_target
        from dazpy.math3 import Vec3
        result = resolve_target(Vec3(10, 20, 30))
        self.assertAlmostEqual(result.x, 10.0, places=6)
        self.assertAlmostEqual(result.y, 20.0, places=6)
        self.assertAlmostEqual(result.z, 30.0, places=6)

    def test_resolve_target_applies_vertical_offset_to_vec3(self):
        from dazpy._shot_geometry import resolve_target
        from dazpy.math3 import Vec3
        result = resolve_target(Vec3(10, 20, 30), vertical_offset_cm=25.0)
        self.assertAlmostEqual(result.x, 10.0, places=6)
        self.assertAlmostEqual(result.y, 45.0, places=6)
        self.assertAlmostEqual(result.z, 30.0, places=6)

    def test_resolve_target_applies_vertical_offset_to_daznode_position(self):
        from dazpy._shot_geometry import resolve_target

        class _Node:
            position = {"x": 1.0, "y": 2.0, "z": 3.0}

        result = resolve_target(_Node(), vertical_offset_cm=10.0)
        self.assertAlmostEqual(result.x, 1.0, places=6)
        self.assertAlmostEqual(result.y, 12.0, places=6)
        self.assertAlmostEqual(result.z, 3.0, places=6)

    def test_resolve_target_raises_value_error_when_node_has_no_position(self):
        from dazpy._shot_geometry import resolve_target

        class _DeletedNode:
            position = None

        with self.assertRaisesRegex(ValueError, "no position"):
            resolve_target(_DeletedNode())


if __name__ == "__main__":
    unittest.main()
