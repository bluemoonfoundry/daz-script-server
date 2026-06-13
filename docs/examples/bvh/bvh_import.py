"""DAZ Studio Script Server example: apply a BVH motion capture file to a DAZ figure, frame by frame.

PURPOSE
-------
This script is a demonstration of what the DAZ Studio Script Server makes
possible.  It parses a BVH file entirely in Python, retargets the bone
rotations to the DAZ Studio internal naming for the detected generation, and
drives the live rig one frame at a time over HTTP — optionally rendering each
frame.

It is an *example*, not a production mocap pipeline.  A real pipeline would
bake the animation to the DAZ timeline, handle root-motion scaling accurately,
and cover finger and facial bones.  The goal here is to show a clean
separation of responsibilities: Python owns all the file parsing and animation
math; DAZ Studio applies the result per frame over a single HTTP call.

WHAT IT DEMONSTRATES
--------------------
  - Pure-Python BVH file parsing (HIERARCHY + MOTION sections, no external deps)
  - Per-bone Euler rotation-order conversion via a 3x3 rotation matrix, so BVH
    data is applied correctly even when the BVH and DAZ rotation orders differ
  - Auto-detection of BVH convention (CMU, Mixamo) and DAZ generation from the
    live scene
  - Batching all bone rotations for one frame into a single DazScript call
  - Zeroing unmapped DAZ bones (twist helpers, etc.) each frame to prevent
    ERC/JCM accumulation from prior frames
  - Optional root translation with a configurable scale factor
  - Optional per-frame render with ffmpeg assembly hint

ENVIRONMENT SETUP
-----------------
1. DAZ Studio must be running with the DazScriptServer plugin loaded and its
   HTTP server active (default: 127.0.0.1:18811).  You can verify it is
   responding with:

       curl http://127.0.0.1:18811/health

2. Install the Python dependencies in a virtual environment:

       python -m venv .venv
       .venv\\Scripts\\activate          # Windows
       # source .venv/bin/activate     # macOS / Linux
       pip install requests

3. Install or develop-install the dazpy SDK (from the repo root):

       pip install -e .

4. Open a scene in DAZ Studio with a Genesis figure, then run:

       python docs/examples/bvh/bvh_import.py walk.bvh

Usage:
    python bvh_import.py walk.bvh
    python bvh_import.py walk.bvh --figure "Genesis 9" --generation genesis9
    python bvh_import.py walk.bvh --frames 0:60 --render --out C:/renders/walk
    python bvh_import.py walk.bvh --root-translation --root-scale 0.1
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from dataclasses import dataclass, field

from dazpy import DazClient, DazRenderSettings
from bvh_bone_maps import (
    BVH_TO_CANONICAL, CANONICAL_TO_DAZ,
    build_bvh_to_daz, detect_convention,
)

# ── rotation order utilities ───────────────────────────────────────────────────
# BVH specifies a rotation order per joint (e.g. Zrotation Xrotation Yrotation →
# ZXY).  DAZ Studio has its own rotation order per bone.  Naively copying the
# X/Y/Z values without reordering produces the wrong pose for any bone whose
# orders differ.  These helpers convert between intrinsic Euler orders via a
# 3×3 rotation matrix (no external dependencies).

_EPS = 1e-7
_DAZ_INT_TO_ORDER = {0: "XYZ", 1: "XZY", 2: "YXZ", 3: "YZX", 4: "ZXY", 5: "ZYX"}


def _normalize_order(order) -> str:
    """Normalise a DAZ rotation-order value to a 3-char string like 'YXZ'.

    Handles all forms that DazScript may return for a DzRotationOrder:
      - int 0-5  (from .order property)
      - str "YXZ" / "LocalYXZ" (from .toString())
      - dict {"order": 2, "firstAxis": 1, ...}  (whole object serialised)
    """
    if isinstance(order, int):
        return _DAZ_INT_TO_ORDER.get(order, "XYZ")
    if isinstance(order, dict):
        # DzRotationOrder serialised as a JS object — use .order integer
        o = order.get("order")
        if isinstance(o, int):
            return _DAZ_INT_TO_ORDER.get(o, "XYZ")
    if isinstance(order, str):
        s = order.strip().upper()
        if s.startswith("LOCAL"):      # "LocalYXZ" → "YXZ"
            s = s[5:]
        if s in _DAZ_INT_TO_ORDER.values():
            return s
        try:
            return _DAZ_INT_TO_ORDER.get(int(s), "XYZ")
        except ValueError:
            pass
    return "XYZ"


def _bvh_channel_order(channels: list[str]) -> str:
    """Return the rotation axis order implied by a BVH CHANNELS list (e.g. 'ZXY')."""
    return "".join(ch[0].upper() for ch in channels if ch.lower().endswith("rotation"))


def _rx(a: float) -> list:
    c, s = math.cos(a), math.sin(a)
    return [[1, 0, 0], [0, c, -s], [0, s, c]]


def _ry(a: float) -> list:
    c, s = math.cos(a), math.sin(a)
    return [[c, 0, s], [0, 1, 0], [-s, 0, c]]


def _rz(a: float) -> list:
    c, s = math.cos(a), math.sin(a)
    return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


_RFNS: dict = {"X": _rx, "Y": _ry, "Z": _rz}


def _mm(A: list, B: list) -> list:
    return [[sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _euler_to_matrix(x_deg: float, y_deg: float, z_deg: float, order: str) -> list:
    """Compose a 3×3 rotation matrix from Euler angles in the given intrinsic order."""
    v = {"X": math.radians(x_deg), "Y": math.radians(y_deg), "Z": math.radians(z_deg)}
    M = [[1 if i == j else 0 for j in range(3)] for i in range(3)]
    for ax in order:
        M = _mm(M, _RFNS[ax](v[ax]))
    return M


def _matrix_to_euler(M: list, order: str) -> tuple[float, float, float]:
    """Decompose a 3×3 rotation matrix to Euler angles (degrees) in intrinsic order."""
    def _asin(v: float) -> float:
        return math.asin(max(-1.0, min(1.0, v)))

    x = y = z = 0.0
    if order == "XYZ":
        y = _asin(M[0][2])
        if abs(M[0][2]) < 1 - _EPS:
            x, z = math.atan2(-M[1][2], M[2][2]), math.atan2(-M[0][1], M[0][0])
        else:
            x = math.atan2(M[2][1], M[1][1])
    elif order == "XZY":
        z = _asin(-M[0][1])
        if abs(M[0][1]) < 1 - _EPS:
            x, y = math.atan2(M[2][1], M[1][1]), math.atan2(M[0][2], M[0][0])
        else:
            x = math.atan2(-M[2][0], M[2][2])
    elif order == "YXZ":
        x = _asin(-M[1][2])
        if abs(M[1][2]) < 1 - _EPS:
            y, z = math.atan2(M[0][2], M[2][2]), math.atan2(M[1][0], M[1][1])
        else:
            y = math.atan2(-M[0][1], M[0][0])
    elif order == "YZX":
        z = _asin(M[1][0])
        if abs(M[1][0]) < 1 - _EPS:
            y, x = math.atan2(-M[2][0], M[0][0]), math.atan2(-M[1][2], M[1][1])
        else:
            y = math.atan2(M[2][1], M[2][2])
    elif order == "ZXY":
        x = _asin(M[2][1])
        if abs(M[2][1]) < 1 - _EPS:
            z, y = math.atan2(-M[0][1], M[1][1]), math.atan2(-M[2][0], M[2][2])
        else:
            z = math.atan2(M[1][0], M[0][0])
    elif order == "ZYX":
        y = _asin(-M[2][0])
        if abs(M[2][0]) < 1 - _EPS:
            z, x = math.atan2(M[1][0], M[0][0]), math.atan2(M[2][1], M[2][2])
        else:
            z = math.atan2(-M[0][1], M[1][1])
    else:
        raise ValueError(f"Unknown rotation order: {order!r}")
    return math.degrees(x), math.degrees(y), math.degrees(z)


def _reorder_euler(x: float, y: float, z: float, src: str, dst: str) -> tuple[float, float, float]:
    """Re-express Euler angles from one intrinsic rotation order to another."""
    if src == dst:
        return x, y, z
    return _matrix_to_euler(_euler_to_matrix(x, y, z, src), dst)

# ── BVH data model ─────────────────────────────────────────────────────────────

@dataclass
class BvhJoint:
    name: str
    channels: list[str]   # e.g. ["Zrotation", "Xrotation", "Yrotation"]
    col: int              # starting column index in MOTION frame data

@dataclass
class BvhFile:
    root_name: str
    joints: list[BvhJoint]   # ordered as in HIERARCHY (determines column order)
    frame_count: int
    frame_time: float        # seconds per frame
    frames: list[list[float]]

    @property
    def fps(self) -> float:
        return 1.0 / self.frame_time if self.frame_time > 0 else 30.0

    @property
    def duration(self) -> float:
        return self.frame_count * self.frame_time

# ── BVH parser ─────────────────────────────────────────────────────────────────

def _parse_hierarchy(text: str) -> tuple[list[BvhJoint], str]:
    tokens = iter(text.split())
    joints: list[BvhJoint] = []
    root_name: str | None = None
    pending_name: str | None = None
    in_end_site = False
    col = 0

    for tok in tokens:
        up = tok.upper()
        if up in ("ROOT", "JOINT"):
            pending_name = next(tokens)
            if root_name is None:
                root_name = pending_name
            in_end_site = False
        elif up == "END":
            next(tokens)  # "Site"
            in_end_site = True
        elif up == "CHANNELS" and not in_end_site:
            n = int(next(tokens))
            channels = [next(tokens) for _ in range(n)]
            joints.append(BvhJoint(name=pending_name, channels=channels, col=col))
            col += n
            pending_name = None
        elif up == "OFFSET":
            next(tokens); next(tokens); next(tokens)
        # { } and other keywords are ignored

    return joints, root_name or ""


def _parse_motion(text: str, total_channels: int) -> tuple[int, float, list[list[float]]]:
    tokens = text.split()
    it = iter(tokens)
    next(it)             # "MOTION"
    next(it)             # "Frames:"
    frame_count = int(next(it))
    next(it)             # "Frame"
    next(it)             # "Time:"
    frame_time = float(next(it))

    vals = [float(v) for v in it]
    frames = [
        vals[i * total_channels : (i + 1) * total_channels]
        for i in range(frame_count)
    ]
    return frame_count, frame_time, frames


def parse_bvh(path: str) -> BvhFile:
    """Parse a BVH file and return a :class:`BvhFile` with all frame data."""
    with open(path, encoding="utf-8") as f:
        text = f.read()

    motion_start = text.upper().find("MOTION")
    if motion_start == -1:
        raise ValueError(f"No MOTION section in {path!r}")

    joints, root_name = _parse_hierarchy(text[:motion_start])
    total_channels = sum(len(j.channels) for j in joints)
    frame_count, frame_time, frames = _parse_motion(text[motion_start:], total_channels)

    return BvhFile(
        root_name=root_name,
        joints=joints,
        frame_count=frame_count,
        frame_time=frame_time,
        frames=frames,
    )

# ── rotation extraction ────────────────────────────────────────────────────────

def _rotations(joint: BvhJoint, frame: list[float]) -> tuple[float, float, float]:
    """Extract (x_deg, y_deg, z_deg) from a frame row for one joint."""
    x = y = z = 0.0
    for i, ch in enumerate(joint.channels):
        v = frame[joint.col + i]
        if ch == "Xrotation":
            x = v
        elif ch == "Yrotation":
            y = v
        elif ch == "Zrotation":
            z = v
    return x, y, z


def _translation(joint: BvhJoint, frame: list[float]) -> tuple[float, float, float]:
    """Extract (tx, ty, tz) from a frame row for the root joint."""
    tx = ty = tz = 0.0
    for i, ch in enumerate(joint.channels):
        v = frame[joint.col + i]
        if ch == "Xposition":
            tx = v
        elif ch == "Yposition":
            ty = v
        elif ch == "Zposition":
            tz = v
    return tx, ty, tz

# ── DAZ Studio apply ───────────────────────────────────────────────────────────

def _skel_lookup(label: str) -> str:
    esc = json.dumps(label)
    return (
        f"var _skel=null,_skels=Scene.getSkeletonList();"
        f"for(var _i=0;_i<_skels.length;_i++){{"
        f"if(_skels[_i].getLabel()==={esc}){{_skel=_skels[_i];break;}}}}"
    )


def _query_bone_rotation_orders(
    client: DazClient,
    figure_label: str,
    daz_bones: list[str],
) -> dict[str, str]:
    """Batch-query the rotation order of each DAZ bone in a single HTTP call.

    Returns a mapping of DAZ bone name → order string (e.g. ``"YXZ"``).
    Bones not found in the scene fall back to ``"XYZ"``.
    """
    esc = json.dumps(figure_label)
    blist = json.dumps(daz_bones)
    # Extract the .order integer from the DzRotationOrder object returned by
    # getRotationOrder().  Storing the whole object produces a serialised dict
    # that is not a plain int/string and would defeat _normalize_order.
    script = (
        f"(function(){{"
        f"var _skel=null,_skels=Scene.getSkeletonList();"
        f"for(var _i=0;_i<_skels.length;_i++){{"
        f"if(_skels[_i].getLabel()==={esc}){{_skel=_skels[_i];break;}}}}"
        f"if(!_skel)return null;"
        f"var bones={blist},out={{}};"
        f"for(var _i=0;_i<bones.length;_i++){{"
        f"var _b=_skel.findBone(bones[_i]);"
        f"if(_b)out[bones[_i]]=_b.getRotationOrder().order;}}"
        f"return out;"
        f"}})()"
    )
    raw = client.execute(script).value or {}
    result = {name: _normalize_order(order) for name, order in raw.items()}
    return result


def apply_frame(
    client: DazClient,
    figure_label: str,
    frame: list[float],
    joint_map: dict[str, tuple[BvhJoint, str]],  # BVH name → (joint, daz_bone)
    daz_bone_orders: dict[str, str],              # daz_bone → rotation order string
    zero_bones: list[str],                         # DAZ bones to zero each frame
    root_joint: BvhJoint | None = None,
    root_translation: bool = False,
    root_scale: float = 1.0,
    debug: bool = False,
) -> None:
    """Send one HTTP call that sets all bone rotations for a single frame.

    Args:
        client:            Active DAZ client.
        figure_label:      Scene label of the target figure.
        frame:             Full frame channel row from :attr:`BvhFile.frames`.
        joint_map:         Pre-built {bvh_joint_name: (BvhJoint, daz_bone_name)} dict.
        daz_bone_orders:   Rotation order per DAZ bone, queried once at setup.
        zero_bones:        DAZ bones with no BVH counterpart; zeroed each frame so
                           ERC/JCM leftovers from prior frames don't accumulate.
        root_joint:        BVH root joint, used for translation extraction.
        root_translation:  When True, move the skeleton to match root translation.
        root_scale:        Scale factor applied to BVH translation values.
    """
    lines: list[str] = []

    # Zero out unmapped bones (e.g. twist helpers) for a clean per-frame state.
    for daz_bone in zero_bones:
        daz = json.dumps(daz_bone)
        lines.append(
            f"_b=_skel.findBone({daz});"
            f"if(_b){{"
            f"_b.getXRotControl().setValue(0);"
            f"_b.getYRotControl().setValue(0);"
            f"_b.getZRotControl().setValue(0);}}"
        )

    if root_translation and root_joint is not None:
        tx, ty, tz = _translation(root_joint, frame)
        tx *= root_scale; ty *= root_scale; tz *= root_scale
        lines.append(
            f"_skel.getXPosControl().setValue({tx:.6f});"
            f"_skel.getYPosControl().setValue({ty:.6f});"
            f"_skel.getZPosControl().setValue({tz:.6f});"
        )

    for bvh_name, (joint, daz_bone) in joint_map.items():
        x, y, z = _rotations(joint, frame)
        bvh_order = _bvh_channel_order(joint.channels)
        daz_order = daz_bone_orders.get(daz_bone, "XYZ")
        xc, yc, zc = _reorder_euler(x, y, z, bvh_order, daz_order)
        if debug:
            if abs(x - xc) > 0.001 or abs(y - yc) > 0.001 or abs(z - zc) > 0.001:
                print(f"  {bvh_name:20s} -> {daz_bone:22s}  "
                      f"bvh={bvh_order}({x:.1f},{y:.1f},{z:.1f})  "
                      f"daz={daz_order}({xc:.1f},{yc:.1f},{zc:.1f})")
        x, y, z = xc, yc, zc
        daz = json.dumps(daz_bone)
        lines.append(
            f"_b=_skel.findBone({daz});"
            f"if(_b){{"
            f"_b.getXRotControl().setValue({x:.6f});"
            f"_b.getYRotControl().setValue({y:.6f});"
            f"_b.getZRotControl().setValue({z:.6f});}}"
        )

    body = "\n".join(lines)
    script = (
        f"(function(){{"
        f"{_skel_lookup(figure_label)}"
        f"if(!_skel)return;"
        f"var _b;"
        f"{body}"
        f"}})()"
    )
    client.execute(script)

# ── helpers ────────────────────────────────────────────────────────────────────

def _detect_generation(client: DazClient, figure_label: str) -> str | None:
    """Probe the live figure for generation-specific bone names."""
    esc = json.dumps(figure_label)
    probes = {
        "l_thigh":    "genesis9",
        "lThighBend": "genesis3",
        "abdomen2":   "genesis2",
        "abdomen":    "genesis1",
    }
    probe_list = json.dumps(list(probes.keys()))
    script = (
        f"(function(){{"
        f"var _skel=null,_skels=Scene.getSkeletonList();"
        f"for(var _i=0;_i<_skels.length;_i++){{"
        f"if(_skels[_i].getLabel()==={esc}){{_skel=_skels[_i];break;}}}}"
        f"if(!_skel)return null;"
        f"var probes={probe_list};"
        f"for(var _i=0;_i<probes.length;_i++){{"
        f"if(_skel.findBone(probes[_i]))return probes[_i];}}"
        f"return null;"
        f"}})()"
    )
    probe_hit = client.execute(script).value
    return probes.get(probe_hit)


def _primary_label(client: DazClient) -> str | None:
    script = "(function(){var n=Scene.getPrimarySelection();return n?n.getLabel():null;})()"
    return client.execute(script).value


if __name__ == "__main__":
    # ── CLI ────────────────────────────────────────────────────────────────────────

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("bvh",         help="Path to .bvh file")
    parser.add_argument("--figure",    default=None,
                        help="Figure label in DAZ Studio (default: primary selection)")
    parser.add_argument("--generation", default=None, choices=list(CANONICAL_TO_DAZ),
                        help="DAZ generation key (default: auto-detect from live scene)")
    parser.add_argument("--convention", default=None, choices=list(BVH_TO_CANONICAL),
                        help="BVH naming convention (default: auto-detect from file)")
    parser.add_argument("--frames",    default=None,
                        help="Frame range as START:END, e.g. 0:60 (default: all frames)")
    parser.add_argument("--render",    action="store_true",
                        help="Render each frame to disk")
    parser.add_argument("--out",       default="y:/tmp/bvh_render",
                        help="Output directory for rendered frames (default: y:/tmp/bvh_render)")
    parser.add_argument("--width",     type=int, default=1920)
    parser.add_argument("--height",    type=int, default=1080)
    parser.add_argument("--root-translation", action="store_true",
                        help="Apply root bone translation to figure position")
    parser.add_argument("--root-scale", type=float, default=1.0,
                        help="Scale factor for root translation (e.g. 0.1 if BVH is in mm)")
    parser.add_argument("--no-zero-unmapped", action="store_true",
                        help="Skip zeroing DAZ bones that have no BVH counterpart each frame")
    parser.add_argument("--debug-frame", action="store_true",
                        help="Print BVH angles and converted DAZ angles for the first frame")
    args = parser.parse_args()

    # ── parse BVH ──────────────────────────────────────────────────────────────────

    bvh = parse_bvh(args.bvh)

    # auto-detect convention from BVH bone names
    convention = args.convention or detect_convention([j.name for j in bvh.joints])
    if convention is None:
        raise SystemExit(
            "Could not auto-detect BVH convention. "
            f"Use --convention ({', '.join(BVH_TO_CANONICAL)})."
        )

    # frame range
    if args.frames:
        parts = args.frames.split(":")
        frame_start, frame_end = int(parts[0]), int(parts[1])
    else:
        frame_start, frame_end = 0, bvh.frame_count - 1

    frame_end = min(frame_end, bvh.frame_count - 1)
    frame_indices = range(frame_start, frame_end + 1)
    n_frames = len(frame_indices)

    # ── connect to DAZ Studio ──────────────────────────────────────────────────────

    client = DazClient()

    figure_label = args.figure or _primary_label(client)
    if not figure_label:
        raise SystemExit("No figure found — use --figure or select one in DAZ Studio.")

    generation = args.generation or _detect_generation(client, figure_label)
    if generation is None:
        raise SystemExit(
            f"Could not detect generation for {figure_label!r}. "
            f"Use --generation ({', '.join(CANONICAL_TO_DAZ)})."
        )

    # ── build joint map ────────────────────────────────────────────────────────────
    # Maps BVH joint name → (BvhJoint, daz_bone_name) for every bone that has
    # a counterpart in this generation. Built once, reused for every frame.

    bvh_to_daz = build_bvh_to_daz(convention, generation)
    joint_by_name = {j.name: j for j in bvh.joints}

    joint_map: dict[str, tuple[BvhJoint, str]] = {}
    unmapped: list[str] = []
    for bvh_name, daz_bone in bvh_to_daz.items():
        if bvh_name in joint_by_name:
            joint_map[bvh_name] = (joint_by_name[bvh_name], daz_bone)
        else:
            unmapped.append(bvh_name)

    root_joint = joint_by_name.get(bvh.root_name)

    # ── query DAZ bone rotation orders ─────────────────────────────────────────────
    # One HTTP call returns the rotation order string for each mapped bone so
    # apply_frame() can convert BVH Euler angles to the correct DAZ order.

    mapped_daz_bones = [daz_bone for (_, daz_bone) in joint_map.values()]
    daz_bone_orders = _query_bone_rotation_orders(client, figure_label, mapped_daz_bones)

    # Diagnostic: show a compact summary of queried rotation orders.
    order_summary: dict[str, list[str]] = {}
    for bone, ord_ in daz_bone_orders.items():
        order_summary.setdefault(ord_, []).append(bone)
    print("DAZ bone rotation orders:")
    for ord_, bones in sorted(order_summary.items()):
        print(f"  {ord_}: {', '.join(sorted(bones))}")

    # Warn if any bone returned an unexpected value (helps diagnose DAZ API changes).
    unknown = [b for b in mapped_daz_bones if b not in daz_bone_orders]
    if unknown:
        print(f"WARNING: Could not query rotation order for: {', '.join(unknown)}  (defaulting to XYZ)")

    # ── build zero_bones ───────────────────────────────────────────────────────────
    # DAZ bones that exist in this generation but have no BVH counterpart (twist
    # helpers, extra spine segments, etc.) are zeroed each frame so residual values
    # from ERC formulas or prior frames don't accumulate.

    if args.no_zero_unmapped:
        zero_bones: list[str] = []
    else:
        mapped_daz_set = set(mapped_daz_bones)
        gen_all_daz = {b for b in CANONICAL_TO_DAZ[generation].values() if b is not None}
        zero_bones = sorted(gen_all_daz - mapped_daz_set)

    # ── summary ────────────────────────────────────────────────────────────────────

    print(f"BVH file   : {args.bvh}")
    print(f"Convention : {convention}")
    print(f"Figure     : {figure_label}  ({generation})")
    print(f"Frames     : {frame_start}–{frame_end}  ({n_frames} frames @ {bvh.fps:.1f} fps)")
    print(f"Bones mapped: {len(joint_map)} of {len(bvh_to_daz)} expected")
    if unmapped:
        print(f"  Not in BVH: {', '.join(unmapped)}")
    if zero_bones:
        print(f"Zeroing {len(zero_bones)} unmapped DAZ bones each frame: {', '.join(zero_bones)}")
    if args.render:
        print(f"Rendering  : {args.out}  ({args.width}×{args.height})")
    print()

    # ── render setup ──────────────────────────────────────────────────────────────

    render: DazRenderSettings | None = None
    if args.render:
        os.makedirs(args.out, exist_ok=True)
        render = DazRenderSettings(client)
        render.set_resolution(args.width, args.height)

    # ── main loop ─────────────────────────────────────────────────────────────────

    t_start = time.perf_counter()

    for seq, fi in enumerate(frame_indices):
        frame_data = bvh.frames[fi]

        if args.debug_frame and seq == 0:
            print("Frame 0 rotation conversions (only bones where values changed):")
        apply_frame(
            client,
            figure_label,
            frame_data,
            joint_map,
            daz_bone_orders,
            zero_bones,
            root_joint=root_joint,
            root_translation=args.root_translation,
            root_scale=args.root_scale,
            debug=(args.debug_frame and seq == 0),
        )

        if render is not None:
            out_path = os.path.join(args.out, f"frame_{seq:04d}.png")
            render.output_path = out_path
            render.render()

        elapsed = time.perf_counter() - t_start
        rate = (seq + 1) / elapsed
        eta = (n_frames - seq - 1) / rate if rate > 0 else 0
        suffix = f"  rendered → {out_path}" if render else ""
        print(
            f"  [{seq + 1:>{len(str(n_frames))}}/{n_frames}]"
            f"  BVH frame {fi:04d}"
            f"  {elapsed:.1f}s elapsed  ETA {eta:.0f}s"
            f"{suffix}"
        )

    total = time.perf_counter() - t_start
    print(f"\nDone. {n_frames} frames in {total:.1f}s ({n_frames/total:.1f} frames/s)")

    if render is not None:
        pattern = os.path.join(args.out, "frame_%04d.png")
        print(f"\nTo create a video:")
        print(f'  ffmpeg -framerate {bvh.fps:.0f} -i "{pattern}" bvh_output.mp4')
