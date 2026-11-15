"""Parser for the binary DZGF payload returned by ``POST /geometry/frames``."""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .exceptions import ServerResponseError

_MAGIC = b"DZGF"
_HEADER = struct.Struct("<4s7I")  # magic, version, numFrames, numVerts, numBones, flags, reserved[2]
_FLAG_INDICES = 0x1

Point = tuple[float, float, float]


@dataclass(frozen=True)
class GeometryFrames:
    """Deformed figure vertices and bone origins for a list of frames.

    Returned by :meth:`dazpy.DazClient.export_geometry_frames`.

    Attributes:
        frames: Frame numbers, in the order they were evaluated.
        vertices: ``vertices[f][v]`` is the ``(x, y, z)`` position of vertex
            *v* at ``frames[f]``.
        bones: ``bones[f][b]`` is the world-space origin of ``bone_names[b]``
            at ``frames[f]``.
        bone_names: The bone names passed in the request, in payload order.
        indices: Mesh vertex index of each returned vertex when a subset
            (``indices`` or ``surfaces``) was requested, otherwise ``None``
            (``vertices[f][v]`` is then mesh vertex *v*).
        raw: The unparsed payload, e.g. for ``numpy.frombuffer``.
    """

    frames: list[int]
    vertices: list[list[Point]]
    bones: list[list[Point]]
    bone_names: list[str] = field(default_factory=list)
    indices: list[int] | None = None
    raw: bytes = field(default=b"", repr=False)

    @property
    def num_frames(self) -> int:
        return len(self.frames)

    @property
    def num_vertices(self) -> int:
        """Vertices per frame (the subset size if a subset was requested)."""
        return len(self.vertices[0]) if self.vertices else 0

    def frame(self, frame: int) -> list[Point]:
        """Vertices for frame number *frame* (not a list position)."""
        try:
            return self.vertices[self.frames.index(frame)]
        except ValueError:
            raise KeyError(f"frame {frame} not in payload {self.frames}") from None

    def bone(self, name: str) -> list[Point]:
        """World-space origin of bone *name* for every frame, in frame order."""
        try:
            b = self.bone_names.index(name)
        except ValueError:
            raise KeyError(f"bone {name!r} not in payload {self.bone_names}") from None
        return [per_frame[b] for per_frame in self.bones]


def _points(data: bytes, offset: int, count: int) -> list[Point]:
    flat = struct.unpack_from(f"<{count * 3}f", data, offset)
    return [flat[i:i + 3] for i in range(0, len(flat), 3)]


def parse_geometry_frames(data: bytes, bone_names: list[str] | None = None) -> GeometryFrames:
    """Decode a DZGF payload (see ``POST /geometry/frames`` in the README).

    Args:
        data: The raw response body.
        bone_names: The ``bones`` list sent in the request, used to label the
            bone section. Must match the payload's bone count when given.

    Raises:
        ServerResponseError: If the payload is truncated, has the wrong magic
            or an unsupported version.
    """
    def bad(msg: str) -> ServerResponseError:
        return ServerResponseError(f"Invalid DZGF payload: {msg}", status_code=200,
                                   error_code="INVALID_PAYLOAD")

    if len(data) < _HEADER.size:
        raise bad(f"{len(data)} bytes is shorter than the {_HEADER.size}-byte header")
    magic, version, n_frames, n_verts, n_bones, flags, _r0, _r1 = _HEADER.unpack_from(data, 0)
    if magic != _MAGIC:
        raise bad(f"magic {magic!r}, expected {_MAGIC!r}")
    if version != 1:
        raise bad(f"unsupported version {version}")
    has_indices = bool(flags & _FLAG_INDICES)
    expected = (_HEADER.size + 4 * n_frames + (4 * n_verts if has_indices else 0)
                + 12 * n_frames * n_verts + 12 * n_frames * n_bones)
    if len(data) != expected:
        raise bad(f"{len(data)} bytes, header implies {expected}")
    if bone_names is not None and len(bone_names) != n_bones:
        raise bad(f"{n_bones} bones in payload, {len(bone_names)} requested")

    off = _HEADER.size
    frames = list(struct.unpack_from(f"<{n_frames}i", data, off))
    off += 4 * n_frames
    indices = None
    if has_indices:
        indices = list(struct.unpack_from(f"<{n_verts}I", data, off))
        off += 4 * n_verts
    vertices = []
    for _ in range(n_frames):
        vertices.append(_points(data, off, n_verts))
        off += 12 * n_verts
    bones = []
    for _ in range(n_frames):
        bones.append(_points(data, off, n_bones))
        off += 12 * n_bones

    return GeometryFrames(
        frames=frames, vertices=vertices, bones=bones,
        bone_names=list(bone_names) if bone_names is not None else [],
        indices=indices, raw=bytes(data),
    )


def geometry_frames_payload(
    frames, node: str | None, indices, surfaces, bones, resolution: str, scene_update: bool,
) -> dict:
    """Request body for ``POST /geometry/frames`` (shared by the sync and async clients)."""
    frames = [int(f) for f in frames]
    if not frames:
        raise ValueError("frames must contain at least one frame number")
    if resolution not in ("base", "current"):
        raise ValueError(f"resolution must be 'base' or 'current', got {resolution!r}")
    payload: dict = {"frames": frames}
    if node is not None:
        payload["node"] = node
    if indices is not None:
        payload["indices"] = [int(i) for i in indices]
    if surfaces is not None:
        payload["surfaces"] = list(surfaces)
    if bones is not None:
        payload["bones"] = list(bones)
    if resolution != "base":
        payload["resolution"] = resolution
    if not scene_update:
        payload["sceneUpdate"] = False
    return payload
