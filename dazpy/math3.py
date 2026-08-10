"""Pure-Python 3D math for DAZ Studio workflows.

No external dependencies.  Provides :class:`Vec3`, :class:`Quat`, and
:class:`BoundingBox` with direct support for the dict formats returned by the
dazpy API.

Typical usage::

    from dazpy.math3 import Vec3, Quat, BoundingBox
    # or
    from dazpy import Vec3, Quat, BoundingBox

    # Convert API dicts to math objects
    pos  = Vec3.from_dict(node.position)       # {"x":...,"y":...,"z":...}
    rot  = Quat.from_dict(bone.local_rotation) # {"x":...,"y":...,"z":...,"w":...}
    bbox = BoundingBox.from_dict(node.bounding_box())

    # Slerp between two bone orientations
    a   = Quat.from_euler(*bone_a.local_euler, order="XYZ")
    b   = Quat.from_euler(*bone_b.local_euler, order="XYZ")
    mid = a.slerp(b, 0.5)
    x, y, z = mid.to_euler(order="XYZ")
    bone_a.set_local_rotation(x, y, z)
"""

from __future__ import annotations

import math


# ── Vec3 ──────────────────────────────────────────────────────────────────────

class Vec3:
    """Immutable 3-component vector.

    All arithmetic operators return new :class:`Vec3` instances.

    Args:
        x: X component.
        y: Y component.
        z: Z component.
    """

    __slots__ = ("x", "y", "z")

    def __init__(self, x: float, y: float, z: float) -> None:
        object.__setattr__(self, "x", float(x))
        object.__setattr__(self, "y", float(y))
        object.__setattr__(self, "z", float(z))

    def __setattr__(self, name, value):
        raise AttributeError("Vec3 is immutable")

    # ── construction ──────────────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, d: dict) -> "Vec3":
        """Create from an ``{"x", "y", "z"}`` dict (e.g. from :attr:`~dazpy.DazNode.position`)."""
        return cls(d["x"], d["y"], d["z"])

    @classmethod
    def from_list(cls, v: list[float]) -> "Vec3":
        """Create from a ``[x, y, z]`` list (e.g. a vertex from :meth:`~dazpy.DazGeometry.vertex_positions_all`)."""
        return cls(v[0], v[1], v[2])

    @classmethod
    def zero(cls) -> "Vec3":
        """Return the zero vector ``(0, 0, 0)``."""
        return cls(0.0, 0.0, 0.0)

    # ── serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Return ``{"x": float, "y": float, "z": float}``."""
        return {"x": self.x, "y": self.y, "z": self.z}

    def to_list(self) -> list[float]:
        """Return ``[x, y, z]``."""
        return [self.x, self.y, self.z]

    # ── arithmetic ────────────────────────────────────────────────────────────

    def __add__(self, other: "Vec3") -> "Vec3":
        return Vec3(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: "Vec3") -> "Vec3":
        return Vec3(self.x - other.x, self.y - other.y, self.z - other.z)

    def __mul__(self, scalar: float) -> "Vec3":
        return Vec3(self.x * scalar, self.y * scalar, self.z * scalar)

    def __rmul__(self, scalar: float) -> "Vec3":
        return self.__mul__(scalar)

    def __truediv__(self, scalar: float) -> "Vec3":
        return Vec3(self.x / scalar, self.y / scalar, self.z / scalar)

    def __neg__(self) -> "Vec3":
        return Vec3(-self.x, -self.y, -self.z)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Vec3):
            return NotImplemented
        return self.x == other.x and self.y == other.y and self.z == other.z

    def __repr__(self) -> str:
        return f"Vec3({self.x:.4g}, {self.y:.4g}, {self.z:.4g})"

    # ── geometry ──────────────────────────────────────────────────────────────

    def dot(self, other: "Vec3") -> float:
        """Dot product."""
        return self.x * other.x + self.y * other.y + self.z * other.z

    def cross(self, other: "Vec3") -> "Vec3":
        """Cross product (right-hand rule)."""
        return Vec3(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x,
        )

    def length_sq(self) -> float:
        """Squared length (avoids a sqrt)."""
        return self.x * self.x + self.y * self.y + self.z * self.z

    def length(self) -> float:
        """Euclidean length."""
        return math.sqrt(self.length_sq())

    def normalize(self) -> "Vec3":
        """Return a unit-length copy.  Returns the zero vector unchanged."""
        mag = self.length()
        if mag < 1e-10:
            return Vec3(0.0, 0.0, 0.0)
        return self / mag

    def distance_sq(self, other: "Vec3") -> float:
        """Squared distance to *other*."""
        return (self - other).length_sq()

    def distance(self, other: "Vec3") -> float:
        """Euclidean distance to *other*."""
        return math.sqrt(self.distance_sq(other))

    def lerp(self, other: "Vec3", t: float) -> "Vec3":
        """Linearly interpolate toward *other*.  ``t=0`` → self, ``t=1`` → other."""
        return Vec3(
            self.x + (other.x - self.x) * t,
            self.y + (other.y - self.y) * t,
            self.z + (other.z - self.z) * t,
        )

    def reflect(self, normal: "Vec3") -> "Vec3":
        """Reflect this vector about *normal* (normal must be unit length)."""
        return self - normal * (2.0 * self.dot(normal))


# ── Quat ──────────────────────────────────────────────────────────────────────

def _euler_to_quat(hx: float, hy: float, hz: float, order: str) -> tuple:
    """Return (x, y, z, w) given half-angles in radians and a rotation order."""
    cx, sx = math.cos(hx), math.sin(hx)
    cy, sy = math.cos(hy), math.sin(hy)
    cz, sz = math.cos(hz), math.sin(hz)

    # Formulae derived from composing per-axis quaternions:
    #   Q_order = Q_first * Q_second * Q_third
    # where Q_X=(sx,0,0,cx), Q_Y=(0,sy,0,cy), Q_Z=(0,0,sz,cz).
    if order == "XYZ":
        return (sx*cy*cz + cx*sy*sz,
                cx*sy*cz - sx*cy*sz,
                cx*cy*sz + sx*sy*cz,
                cx*cy*cz - sx*sy*sz)
    if order == "XZY":
        return (sx*cy*cz - cx*sy*sz,
                cx*sy*cz - sx*cy*sz,
                cx*cy*sz + sx*sy*cz,
                cx*cy*cz + sx*sy*sz)
    if order == "YXZ":
        return (sx*cy*cz + cx*sy*sz,
                cx*sy*cz - sx*cy*sz,
                cx*cy*sz - sx*sy*cz,
                cx*cy*cz + sx*sy*sz)
    if order == "YZX":
        return (sx*cy*cz + cx*sy*sz,
                cx*sy*cz + sx*cy*sz,
                cx*cy*sz - sx*sy*cz,
                cx*cy*cz - sx*sy*sz)
    if order == "ZXY":
        return (sx*cy*cz - cx*sy*sz,
                cx*sy*cz + sx*cy*sz,
                cx*cy*sz + sx*sy*cz,
                cx*cy*cz - sx*sy*sz)
    if order == "ZYX":
        return (sx*cy*cz - cx*sy*sz,
                cx*sy*cz + sx*cy*sz,
                cx*cy*sz - sx*sy*cz,
                cx*cy*cz + sx*sy*sz)
    raise ValueError(f"Unknown rotation order: {order!r}. Expected one of XYZ XZY YXZ YZX ZXY ZYX.")


def _quat_to_euler(m: list, order: str) -> tuple:
    """Extract Euler angles (degrees) from a 3×3 rotation matrix and order."""
    # Matrix rows/columns: m[row][col]
    SAFE = 1.0 - 1e-6  # threshold for gimbal-lock detection

    if order == "XYZ":
        # m[0][2] = sin(y)
        sy = max(-1.0, min(1.0, m[0][2]))
        y = math.degrees(math.asin(sy))
        if abs(sy) < SAFE:
            x = math.degrees(math.atan2(-m[1][2], m[2][2]))
            z = math.degrees(math.atan2(-m[0][1], m[0][0]))
        else:
            x = math.degrees(math.atan2(m[2][1], m[1][1]))
            z = 0.0
        return x, y, z

    if order == "XZY":
        # m[0][1] = -sin(z)
        sz = max(-1.0, min(1.0, -m[0][1]))
        z = math.degrees(math.asin(sz))
        if abs(sz) < SAFE:
            x = math.degrees(math.atan2(m[2][1], m[1][1]))
            y = math.degrees(math.atan2(m[0][2], m[0][0]))
        else:
            x = math.degrees(math.atan2(-m[1][2], m[2][2]))
            y = 0.0
        return x, y, z

    if order == "YXZ":
        # m[1][2] = -sin(x)
        sx = max(-1.0, min(1.0, -m[1][2]))
        x = math.degrees(math.asin(sx))
        if abs(sx) < SAFE:
            y = math.degrees(math.atan2(m[0][2], m[2][2]))
            z = math.degrees(math.atan2(m[1][0], m[1][1]))
        else:
            y = math.degrees(math.atan2(-m[0][1], m[0][0]))
            z = 0.0
        return x, y, z

    if order == "YZX":
        # m[1][0] = sin(z)
        sz = max(-1.0, min(1.0, m[1][0]))
        z = math.degrees(math.asin(sz))
        if abs(sz) < SAFE:
            x = math.degrees(math.atan2(-m[1][2], m[1][1]))
            y = math.degrees(math.atan2(-m[2][0], m[0][0]))
        else:
            x = math.degrees(math.atan2(m[0][1], m[2][1]))
            y = 0.0
        return x, y, z

    if order == "ZXY":
        # m[2][1] = sin(x)
        sx = max(-1.0, min(1.0, m[2][1]))
        x = math.degrees(math.asin(sx))
        if abs(sx) < SAFE:
            y = math.degrees(math.atan2(-m[2][0], m[2][2]))
            z = math.degrees(math.atan2(-m[0][1], m[1][1]))
        else:
            y = math.degrees(math.atan2(m[0][2], m[0][0]))
            z = 0.0
        return x, y, z

    if order == "ZYX":
        # m[2][0] = -sin(y)
        sy = max(-1.0, min(1.0, -m[2][0]))
        y = math.degrees(math.asin(sy))
        if abs(sy) < SAFE:
            x = math.degrees(math.atan2(m[2][1], m[2][2]))
            z = math.degrees(math.atan2(m[1][0], m[0][0]))
        else:
            x = math.degrees(math.atan2(-m[0][1], m[1][1]))
            z = 0.0
        return x, y, z

    raise ValueError(f"Unknown rotation order: {order!r}. Expected one of XYZ XZY YXZ YZX ZXY ZYX.")


class Quat:
    """Unit quaternion representing a 3D rotation.

    Stored as ``(x, y, z, w)`` — imaginary components first, scalar last.
    This matches the dict format returned by the dazpy API
    (``DazNode.rotation``, ``DazBone.local_rotation``).

    All methods return new :class:`Quat` instances.  The object is immutable.

    Args:
        x: i component.
        y: j component.
        z: k component.
        w: Scalar component.
    """


    __slots__ = ("x", "y", "z", "w")

    def __init__(self, x: float, y: float, z: float, w: float) -> None:
        object.__setattr__(self, "x", float(x))
        object.__setattr__(self, "y", float(y))
        object.__setattr__(self, "z", float(z))
        object.__setattr__(self, "w", float(w))

    def __setattr__(self, name, value):
        raise AttributeError("Quat is immutable")

    # ── construction ──────────────────────────────────────────────────────────

    @classmethod
    def identity(cls) -> "Quat":
        """Return the identity quaternion ``(0, 0, 0, 1)`` (no rotation)."""
        return cls(0.0, 0.0, 0.0, 1.0)

    @classmethod
    def from_dict(cls, d: dict) -> "Quat":
        """Create from an ``{"x", "y", "z", "w"}`` dict (e.g. from :attr:`~dazpy.DazNode.rotation`)."""
        return cls(d["x"], d["y"], d["z"], d["w"])

    @classmethod
    def from_euler(cls, x: float, y: float, z: float, order: str = "XYZ") -> "Quat":
        """Create from Euler angles in degrees using intrinsic rotations.

        Intrinsic means each rotation is applied in the frame left by the
        previous rotation — the same convention DAZ Studio uses for bone
        rotation channels.

        Args:
            x: Rotation around the X axis in degrees.
            y: Rotation around the Y axis in degrees.
            z: Rotation around the Z axis in degrees.
            order: Application order — one of ``XYZ``, ``XZY``, ``YXZ``,
                ``YZX``, ``ZXY``, ``ZYX``.  Matches :attr:`~dazpy.DazBone.rotation_order`.

        Returns:
            A unit quaternion.
        """
        hx = math.radians(x) * 0.5
        hy = math.radians(y) * 0.5
        hz = math.radians(z) * 0.5
        qx, qy, qz, qw = _euler_to_quat(hx, hy, hz, order)
        return cls(qx, qy, qz, qw)

    @classmethod
    def from_axis_angle(cls, axis: "Vec3", angle_deg: float) -> "Quat":
        """Create from an axis and angle in degrees.

        Args:
            axis: Rotation axis (need not be unit length — normalised internally).
            angle_deg: Rotation magnitude in degrees.

        Returns:
            A unit quaternion.
        """
        n = axis.normalize()
        half = math.radians(angle_deg) * 0.5
        s = math.sin(half)
        return cls(n.x * s, n.y * s, n.z * s, math.cos(half))

    # ── serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Return ``{"x": float, "y": float, "z": float, "w": float}``."""
        return {"x": self.x, "y": self.y, "z": self.z, "w": self.w}

    # ── conversion ────────────────────────────────────────────────────────────

    def to_matrix(self) -> list[list[float]]:
        """Return the equivalent 3×3 rotation matrix (row-major, right-handed)."""
        x, y, z, w = self.x, self.y, self.z, self.w
        x2 = 2.0 * x * x;  y2 = 2.0 * y * y;  z2 = 2.0 * z * z
        xy = 2.0 * x * y;  xz = 2.0 * x * z;  yz = 2.0 * y * z
        wx = 2.0 * w * x;  wy = 2.0 * w * y;  wz = 2.0 * w * z
        return [
            [1.0-y2-z2,  xy-wz,     xz+wy  ],
            [xy+wz,      1.0-x2-z2, yz-wx  ],
            [xz-wy,      yz+wx,     1.0-x2-y2],
        ]

    def to_euler(self, order: str = "XYZ") -> tuple[float, float, float]:
        """Extract Euler angles in degrees.

        The inverse of :meth:`from_euler` for the same *order*.  Gimbal-lock
        configurations (singularities) are handled by setting the last rotation
        in the order to zero.

        Args:
            order: One of ``XYZ``, ``XZY``, ``YXZ``, ``YZX``, ``ZXY``, ``ZYX``.

        Returns:
            ``(x, y, z)`` in degrees.
        """
        return _quat_to_euler(self.to_matrix(), order)

    # ── arithmetic ────────────────────────────────────────────────────────────

    def multiply(self, other: "Quat") -> "Quat":
        """Hamilton product ``self * other``.

        Composing rotations: ``a.multiply(b)`` applies *a* first, then *b*
        in the rotated frame (intrinsic), or equivalently *b* first then *a*
        in the world frame (extrinsic).
        """
        ax, ay, az, aw = self.x, self.y, self.z, self.w
        bx, by, bz, bw = other.x, other.y, other.z, other.w
        return Quat(
            aw*bx + ax*bw + ay*bz - az*by,
            aw*by - ax*bz + ay*bw + az*bx,
            aw*bz + ax*by - ay*bx + az*bw,
            aw*bw - ax*bx - ay*by - az*bz,
        )

    def conjugate(self) -> "Quat":
        """Return the conjugate ``(-x, -y, -z, w)``."""
        return Quat(-self.x, -self.y, -self.z, self.w)

    def length(self) -> float:
        """Quaternion norm."""
        return math.sqrt(self.x**2 + self.y**2 + self.z**2 + self.w**2)

    def normalize(self) -> "Quat":
        """Return a unit-length copy."""
        mag = self.length()
        if mag < 1e-10:
            return Quat.identity()
        return Quat(self.x/mag, self.y/mag, self.z/mag, self.w/mag)

    def dot(self, other: "Quat") -> float:
        """4D dot product (used internally by :meth:`slerp`)."""
        return self.x*other.x + self.y*other.y + self.z*other.z + self.w*other.w

    # ── rotation ──────────────────────────────────────────────────────────────

    def rotate(self, v: "Vec3") -> "Vec3":
        """Rotate vector *v* by this quaternion.

        Uses the sandwich product ``q * v * q⁻¹``.
        """
        # Equivalent to: p' = q * (0,v) * q*  (pure quaternion sandwich)
        qx, qy, qz, qw = self.x, self.y, self.z, self.w
        vx, vy, vz = v.x, v.y, v.z
        # t = 2 * cross(q.xyz, v)
        tx = 2.0 * (qy*vz - qz*vy)
        ty = 2.0 * (qz*vx - qx*vz)
        tz = 2.0 * (qx*vy - qy*vx)
        return Vec3(
            vx + qw*tx + qy*tz - qz*ty,
            vy + qw*ty + qz*tx - qx*tz,
            vz + qw*tz + qx*ty - qy*tx,
        )

    # ── interpolation ─────────────────────────────────────────────────────────

    def slerp(self, other: "Quat", t: float) -> "Quat":
        """Spherical linear interpolation.

        Always takes the shortest arc between the two orientations.

        Args:
            other: Target rotation (``t=1.0`` produces an exact copy of *other*).
            t: Blend factor in [0, 1].

        Returns:
            A unit quaternion at the interpolated orientation.
        """
        d = self.dot(other)

        # Ensure shortest-path by negating one operand if they're on opposite hemispheres.
        if d < 0.0:
            other = Quat(-other.x, -other.y, -other.z, -other.w)
            d = -d

        d = min(1.0, d)

        # For nearly identical quaternions fall back to normalised linear interpolation
        # to avoid division by sin(θ) ≈ 0.
        if d > 0.9995:
            result = Quat(
                self.x + t * (other.x - self.x),
                self.y + t * (other.y - self.y),
                self.z + t * (other.z - self.z),
                self.w + t * (other.w - self.w),
            )
            return result.normalize()

        theta_0 = math.acos(d)
        sin_theta_0 = math.sin(theta_0)
        theta = theta_0 * t
        sin_theta = math.sin(theta)
        cos_theta = math.cos(theta)

        s0 = cos_theta - d * sin_theta / sin_theta_0
        s1 = sin_theta / sin_theta_0

        return Quat(
            s0 * self.x + s1 * other.x,
            s0 * self.y + s1 * other.y,
            s0 * self.z + s1 * other.z,
            s0 * self.w + s1 * other.w,
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Quat):
            return NotImplemented
        return (self.x == other.x and self.y == other.y
                and self.z == other.z and self.w == other.w)

    def __repr__(self) -> str:
        return f"Quat({self.x:.4g}, {self.y:.4g}, {self.z:.4g}, {self.w:.4g})"


# ── BoundingBox ───────────────────────────────────────────────────────────────

class BoundingBox:
    """Axis-aligned bounding box.

    Args:
        min: Corner with the smallest coordinates.
        max: Corner with the largest coordinates.
    """

    __slots__ = ("min", "max")

    def __init__(self, min: "Vec3", max: "Vec3") -> None:
        object.__setattr__(self, "min", min)
        object.__setattr__(self, "max", max)

    def __setattr__(self, name, value):
        raise AttributeError("BoundingBox is immutable")

    # ── construction ──────────────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, d: dict) -> "BoundingBox":
        """Create from the dict returned by :meth:`~dazpy.DazNode.bounding_box`.

        Expected shape: ``{"min": {"x":..., "y":..., "z":...}, "max": {...}}``.
        """
        return cls(Vec3.from_dict(d["min"]), Vec3.from_dict(d["max"]))

    @classmethod
    def from_points(cls, points: list["Vec3"]) -> "BoundingBox":
        """Compute the tight bounding box around a list of :class:`Vec3` points."""
        if not points:
            raise ValueError("from_points requires at least one point")
        xs = [p.x for p in points]
        ys = [p.y for p in points]
        zs = [p.z for p in points]
        return cls(Vec3(min(xs), min(ys), min(zs)), Vec3(max(xs), max(ys), max(zs)))

    # ── serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Return ``{"min": {...}, "max": {...}}``."""
        return {"min": self.min.to_dict(), "max": self.max.to_dict()}

    # ── geometry ──────────────────────────────────────────────────────────────

    @property
    def center(self) -> "Vec3":
        """Geometric center of the box."""
        return Vec3(
            (self.min.x + self.max.x) * 0.5,
            (self.min.y + self.max.y) * 0.5,
            (self.min.z + self.max.z) * 0.5,
        )

    @property
    def size(self) -> "Vec3":
        """Width, height, and depth as a :class:`Vec3`."""
        return self.max - self.min

    @property
    def volume(self) -> float:
        """Signed volume (positive for valid boxes where min ≤ max on all axes)."""
        s = self.size
        return s.x * s.y * s.z

    def contains(self, point: "Vec3") -> bool:
        """Return ``True`` if *point* is inside or on the surface of the box."""
        return (self.min.x <= point.x <= self.max.x and
                self.min.y <= point.y <= self.max.y and
                self.min.z <= point.z <= self.max.z)

    def overlaps(self, other: "BoundingBox") -> bool:
        """Return ``True`` if this box and *other* share any volume."""
        return (self.min.x <= other.max.x and self.max.x >= other.min.x and
                self.min.y <= other.max.y and self.max.y >= other.min.y and
                self.min.z <= other.max.z and self.max.z >= other.min.z)

    def expand(self, amount: float) -> "BoundingBox":
        """Return a box uniformly expanded by *amount* on all sides."""
        v = Vec3(amount, amount, amount)
        return BoundingBox(self.min - v, self.max + v)

    def union(self, other: "BoundingBox") -> "BoundingBox":
        """Return the smallest box that contains both this box and *other*."""
        return BoundingBox(
            Vec3(min(self.min.x, other.min.x),
                 min(self.min.y, other.min.y),
                 min(self.min.z, other.min.z)),
            Vec3(max(self.max.x, other.max.x),
                 max(self.max.y, other.max.y),
                 max(self.max.z, other.max.z)),
        )

    def __repr__(self) -> str:
        return f"BoundingBox(min={self.min}, max={self.max})"


# ── AxisRemap ─────────────────────────────────────────────────────────────────

_AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


def _parse_axis_spec(spec: str) -> tuple[int, float]:
    """Parse an axis spec like ``"x"``, ``"-y"``, ``"+z"`` into ``(index, sign)``."""
    if not isinstance(spec, str) or not spec:
        raise ValueError(f"Invalid axis spec {spec!r}; expected one of x, y, z, -x, -y, -z")
    sign = 1.0
    name = spec
    if name[0] in "+-":
        sign = -1.0 if name[0] == "-" else 1.0
        name = name[1:]
    if name not in _AXIS_INDEX:
        raise ValueError(f"Invalid axis spec {spec!r}; expected one of x, y, z, -x, -y, -z")
    return _AXIS_INDEX[name], sign


def _mat3_det(m: list) -> float:
    """Determinant of a 3x3 matrix given as ``m[row][col]``."""
    return (
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    )


def _mat3_to_quat(m: list) -> "Quat":
    """Convert a 3x3 rotation matrix (``m[row][col]``, det == +1) to a unit quaternion."""
    trace = m[0][0] + m[1][1] + m[2][2]
    if trace > 0:
        s = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * s
        x = (m[2][1] - m[1][2]) / s
        y = (m[0][2] - m[2][0]) / s
        z = (m[1][0] - m[0][1]) / s
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2.0
        w = (m[2][1] - m[1][2]) / s
        x = 0.25 * s
        y = (m[0][1] + m[1][0]) / s
        z = (m[0][2] + m[2][0]) / s
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2.0
        w = (m[0][2] - m[2][0]) / s
        x = (m[0][1] + m[1][0]) / s
        y = 0.25 * s
        z = (m[1][2] + m[2][1]) / s
    else:
        s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2.0
        w = (m[1][0] - m[0][1]) / s
        x = (m[0][2] + m[2][0]) / s
        y = (m[1][2] + m[2][1]) / s
        z = 0.25 * s
    return Quat(x, y, z, w)


class AxisRemap:
    """Converts :class:`Vec3`, :class:`Quat`, and :class:`BoundingBox` values
    between axis conventions (e.g. Y-up to Z-up).

    A generic signed-axis-permutation remap — no application-specific
    knowledge (Blender/Unreal naming, camera or figure orientation fixups)
    is baked in beyond the :data:`Y_UP_TO_Z_UP` preset.

    Each of *x*, *y*, *z* names which source axis (optionally signed) the
    corresponding output axis is derived from. All three of the source
    axes ``x``, ``y``, ``z`` must be referenced exactly once (signs aside).

    Example::

        # DAZ Studio (Y-up) -> Blender-style Z-up
        remap = AxisRemap(x="x", y="-z", z="y")
        blender_pos = remap.apply_vec3(daz_pos)

    Args:
        x: Source axis for the output X component, e.g. ``"x"`` or ``"-z"``.
        y: Source axis for the output Y component.
        z: Source axis for the output Z component.
    """

    __slots__ = ("_specs", "_matrix", "_det", "_rotation_quat")

    def __init__(self, x: str, y: str, z: str) -> None:
        specs = (_parse_axis_spec(x), _parse_axis_spec(y), _parse_axis_spec(z))
        used = sorted(idx for idx, _ in specs)
        if used != [0, 1, 2]:
            raise ValueError(
                "AxisRemap must reference each of x, y, z exactly once "
                f"(got x={x!r}, y={y!r}, z={z!r})"
            )
        matrix = [[0.0, 0.0, 0.0] for _ in range(3)]
        for row, (idx, sign) in enumerate(specs):
            matrix[row][idx] = sign
        object.__setattr__(self, "_specs", specs)
        object.__setattr__(self, "_matrix", matrix)
        det = _mat3_det(matrix)
        object.__setattr__(self, "_det", det)
        object.__setattr__(
            self, "_rotation_quat", _mat3_to_quat(matrix) if det > 0 else None
        )

    def __setattr__(self, name, value):
        raise AttributeError("AxisRemap is immutable")

    def __repr__(self) -> str:
        axes = "xyz"
        parts = []
        for idx, sign in self._specs:
            parts.append(("-" if sign < 0 else "") + axes[idx])
        return f"AxisRemap(x={parts[0]!r}, y={parts[1]!r}, z={parts[2]!r})"

    # ── application ───────────────────────────────────────────────────────────

    def apply_vec3(self, v: "Vec3") -> "Vec3":
        """Remap a vector or point. Works for any remap, proper or reflective."""
        comps = (v.x, v.y, v.z)
        out = [comps[idx] * sign for idx, sign in self._specs]
        return Vec3(out[0], out[1], out[2])

    def apply_quat(self, q: "Quat") -> "Quat":
        """Remap a rotation.

        Raises:
            ValueError: If this remap is a reflection (determinant ``-1``).
                Reflections cannot be represented by a quaternion; use
                :meth:`apply_vec3` for vectors/points instead.
        """
        if self._rotation_quat is None:
            raise ValueError(
                "AxisRemap represents a reflection (determinant -1); cannot "
                "remap a Quat. Use apply_vec3 for vectors/points instead."
            )
        r = self._rotation_quat
        return r.multiply(q).multiply(r.conjugate())

    def apply_bbox(self, b: "BoundingBox") -> "BoundingBox":
        """Remap a bounding box.

        Both corners are remapped and the result is re-sorted per axis,
        since a sign-flipping remap can swap which corner is the minimum
        on a given axis.
        """
        p1 = self.apply_vec3(b.min)
        p2 = self.apply_vec3(b.max)
        lo = Vec3(min(p1.x, p2.x), min(p1.y, p2.y), min(p1.z, p2.z))
        hi = Vec3(max(p1.x, p2.x), max(p1.y, p2.y), max(p1.z, p2.z))
        return BoundingBox(lo, hi)
