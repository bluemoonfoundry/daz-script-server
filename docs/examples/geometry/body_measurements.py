"""DAZ Studio Script Server example: compute body measurements from a figure mesh.

PURPOSE
-------
This script demonstrates one practical way to measure a DAZ figure from Python:
pull the posed mesh into Python, slice it with horizontal planes, and measure
the perimeter of each cross-section.

It is designed for Genesis 8, Genesis 8.1, and Genesis 9 figures, but it works
with any figure whose torso can be approximated by the same slice-based method.

For best results:
  - Put the figure in a neutral A-pose or T-pose.
  - Zero out body morphs if you want repeatable "standard" measurements.
  - Keep the figure upright in the scene so world-space Y still maps to height.

WHAT IT DEMONSTRATES
--------------------
  - Selecting a figure by Scene-panel label
  - Fetching the fully deformed mesh from DAZ Studio
  - Building a local mesh in Python with optional ``trimesh``
  - Measuring height and circumference from horizontal slices
  - Using bone heights as anchors for bust / underbust / waist / low hip

DEPENDENCIES
------------
In addition to ``dazpy``, this example expects:

    pip install trimesh

``trimesh`` brings in ``numpy`` automatically.  The script exits with a helpful
message if the package is missing.

USAGE
-----
    python body_measurements.py --figure "Genesis 9"
    python body_measurements.py --figure "Genesis 8" --out measurements.json
    python body_measurements.py --figure "Genesis 8.1" --sample-step 0.25
    python body_measurements.py --figure "Genesis 9 Female" --clothing

Output is printed as a readable summary and can optionally be written to JSON.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from dazpy import DazGeometry, DazScene
from dazpy._node import NodeIdentifier

try:
    import trimesh
except ImportError:  # pragma: no cover - exercised by the user environment
    trimesh = None


TORSO_BUST_BONES = ["chestUpper", "chestLower", "chest"]
TORSO_UNDERBUST_BONES = ["abdomenLower", "abdomenUpper", "abdomen"]
TORSO_LOW_HIP_BONES = ["pelvis", "hip"]
CM_PER_INCH = 2.54
HIGH_HIP_OFFSET_CM = 7.5  # ~3 in above full hip bone
GENESIS_9_BONES = {"hip", "pelvis", "spine1", "spine2", "spine3", "spine4", "neck1", "neck2", "head"}
GENESIS_8_BONES = {"hip", "pelvis", "abdomen", "abdomen2", "chest", "chestLower", "chestUpper", "neck", "head"}
PECTORAL_LEFT_CANDIDATES = [
    "lPectoral",
    "lPectoralis",
    "l_pectoral",
    "l_pectoralis",
    "Left Pectoral",
    "Left Pectoralis",
]
PECTORAL_RIGHT_CANDIDATES = [
    "rPectoral",
    "rPectoralis",
    "r_pectoral",
    "r_pectoralis",
    "Right Pectoral",
    "Right Pectoralis",
]


@dataclass(slots=True)
class SliceMeasurement:
    name: str
    value_cm: float | None
    value_in: float | None
    slice_y: float | None
    source: str
    note: str | None = None


@dataclass(slots=True)
class FigureProfile:
    name: str
    bust_left_candidates: list[str]
    bust_right_candidates: list[str]
    bust_bones: list[str]
    underbust_bones: list[str]
    waist_bones: list[str]
    low_hip_bones: list[str]
    nape_bones: list[str]
    shoulder_left_bones: list[str]
    shoulder_right_bones: list[str]
    crotch_left_bones: list[str]
    crotch_right_bones: list[str]
    wrist_left_bones: list[str]
    wrist_right_bones: list[str]
    neck_bones: list[str]
    high_bust_left_bones: list[str]
    high_bust_right_bones: list[str]
    thigh_left_bones: list[str]
    thigh_right_bones: list[str]
    knee_left_bones: list[str]
    knee_right_bones: list[str]
    ankle_left_bones: list[str]
    ankle_right_bones: list[str]
    upper_arm_left_bones: list[str]
    upper_arm_right_bones: list[str]
    elbow_left_bones: list[str]
    elbow_right_bones: list[str]
    wrist_circ_left_bones: list[str]
    wrist_circ_right_bones: list[str]


@dataclass(slots=True)
class MeasurementCalibration:
    target_cm: float | None
    band_below_cm: float
    band_above_cm: float
    fallback_mode: str


@dataclass(slots=True)
class FigureCalibration:
    bust: MeasurementCalibration
    underbust: MeasurementCalibration
    waist: MeasurementCalibration
    low_hip: MeasurementCalibration


@dataclass(slots=True)
class BraSizeEstimate:
    us: str
    uk: str
    eu: str
    note: str
    difference_in: float | None = None
    underbust_in: float | None = None
    bust_in: float | None = None


@dataclass(slots=True)
class DressSizeEstimate:
    us: str
    uk: str
    eu: str
    note: str
    bust_in: float | None = None
    waist_in: float | None = None
    hip_in: float | None = None


@dataclass(slots=True)
class ClothingEstimate:
    bra: BraSizeEstimate | None
    dress: DressSizeEstimate | None
    note: str | None = None


CALIBRATION_FILE = Path(__file__).with_name("body_measurements.calibration.json")


def _measurement_calibration_from_dict(payload: dict) -> MeasurementCalibration:
    target_cm = payload.get("target_cm")
    return MeasurementCalibration(
        target_cm=None if target_cm is None else float(target_cm),
        band_below_cm=float(payload["band_below_cm"]),
        band_above_cm=float(payload["band_above_cm"]),
        fallback_mode=str(payload["fallback_mode"]),
    )


def _figure_calibration_from_dict(payload: dict) -> FigureCalibration:
    return FigureCalibration(
        bust=_measurement_calibration_from_dict(payload["bust"]),
        underbust=_measurement_calibration_from_dict(payload["underbust"]),
        waist=_measurement_calibration_from_dict(payload["waist"]),
        low_hip=_measurement_calibration_from_dict(payload["low_hip"]),
    )


def _load_calibrations(path: Path = CALIBRATION_FILE) -> dict[str, FigureCalibration]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"Missing calibration file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid calibration JSON in {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise SystemExit(f"Calibration file must contain a JSON object: {path}")

    calibrations: dict[str, FigureCalibration] = {}
    for figure_name, figure_payload in payload.items():
        if not isinstance(figure_payload, dict):
            raise SystemExit(f"Calibration entry for {figure_name!r} must be a JSON object")
        calibrations[str(figure_name)] = _figure_calibration_from_dict(figure_payload)
    return calibrations


CALIBRATIONS: dict[str, FigureCalibration] = _load_calibrations()

US_BRA_CUPS = ["AA", "A", "B", "C", "D", "DD/E", "DDD/F", "G", "H", "I", "J", "K"]
UK_BRA_CUPS = ["AA", "A", "B", "C", "D", "DD", "E", "F", "FF", "G", "GG", "H", "HH", "J", "JJ", "K"]
DRESS_SIZE_CHART = [
    {"us": 2, "uk": 6, "eu": 34, "bust_in": 33.0, "waist_in": 25.0, "hip_in": 35.0},
    {"us": 4, "uk": 8, "eu": 36, "bust_in": 34.0, "waist_in": 26.0, "hip_in": 36.0},
    {"us": 6, "uk": 10, "eu": 38, "bust_in": 35.0, "waist_in": 27.0, "hip_in": 37.0},
    {"us": 8, "uk": 12, "eu": 40, "bust_in": 36.0, "waist_in": 28.0, "hip_in": 38.0},
    {"us": 10, "uk": 14, "eu": 42, "bust_in": 37.5, "waist_in": 29.5, "hip_in": 39.5},
    {"us": 12, "uk": 16, "eu": 44, "bust_in": 39.0, "waist_in": 31.0, "hip_in": 41.0},
    {"us": 14, "uk": 18, "eu": 46, "bust_in": 41.0, "waist_in": 33.0, "hip_in": 43.0},
    {"us": 16, "uk": 20, "eu": 48, "bust_in": 43.0, "waist_in": 35.0, "hip_in": 45.0},
    {"us": 18, "uk": 22, "eu": 50, "bust_in": 45.0, "waist_in": 37.0, "hip_in": 47.0},
    {"us": 20, "uk": 24, "eu": 52, "bust_in": 47.0, "waist_in": 39.0, "hip_in": 49.0},
]


def frange(start: float, stop: float, step: float) -> Iterable[float]:
    current = start
    while current <= stop + 1e-9:
        yield current
        current += step


def _distance_2d(a, b) -> float:
    return math.dist((float(a[0]), float(a[2])), (float(b[0]), float(b[2])))


def _loop_perimeter(loop) -> float:
    points = list(loop)
    if len(points) < 2:
        return 0.0
    total = 0.0
    for idx in range(1, len(points)):
        total += _distance_2d(points[idx - 1], points[idx])
    total += _distance_2d(points[-1], points[0])
    return total


def _best_loop_perimeter(section) -> float | None:
    if section is None:
        return None
    best = None
    for loop in section.discrete:
        length = _loop_perimeter(loop)
        if length <= 0:
            continue
        if best is None or length > best:
            best = length
    return best


def _loop_centroid(loop) -> tuple[float, float]:
    points = list(loop)
    if not points:
        return 0.0, 0.0
    sx = 0.0
    sz = 0.0
    for point in points:
        sx += float(point[0])
        sz += float(point[2])
    inv = 1.0 / len(points)
    return sx * inv, sz * inv


def _select_torso_loop(section):
    if section is None:
        return None
    loops = list(section.discrete)
    if not loops:
        return None
    # Prefer loops whose centroid stays closest to the torso centerline.
    # This helps avoid arm and shoulder contours when the slice intersects
    # multiple disconnected pieces.
    scored = []
    for loop in loops:
        perimeter = _loop_perimeter(loop)
        if perimeter <= 0:
            continue
        cx, cz = _loop_centroid(loop)
        score = (abs(cx) * 2.0) + abs(cz)
        scored.append((score, perimeter, loop))
    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], -item[1]))
    return scored[0][2]


def _find_anchor_y(figure, bone_names: list[str]) -> tuple[float | None, str]:
    for bone_name in bone_names:
        try:
            bone = figure.find_bone(bone_name)
        except Exception:
            continue
        pos = bone.position
        if pos and "y" in pos:
            return float(pos["y"]), bone_name
    return None, "fallback"


def _find_pair_anchor_y(figure, left_candidates: list[str], right_candidates: list[str]) -> tuple[float | None, str]:
    left_y = None
    right_y = None
    left_src = None
    right_src = None

    for candidate in left_candidates:
        try:
            left_bone = figure.find_bone(candidate)
            pos = left_bone.position
            if pos and "y" in pos:
                left_y = float(pos["y"])
                left_src = candidate
                break
        except Exception:
            try:
                left_bone = figure.find_bone_by_label(candidate)
                pos = left_bone.position
                if pos and "y" in pos:
                    left_y = float(pos["y"])
                    left_src = candidate
                    break
            except Exception:
                continue

    for candidate in right_candidates:
        try:
            right_bone = figure.find_bone(candidate)
            pos = right_bone.position
            if pos and "y" in pos:
                right_y = float(pos["y"])
                right_src = candidate
                break
        except Exception:
            try:
                right_bone = figure.find_bone_by_label(candidate)
                pos = right_bone.position
                if pos and "y" in pos:
                    right_y = float(pos["y"])
                    right_src = candidate
                    break
            except Exception:
                continue

    if left_y is not None and right_y is not None:
        return (left_y + right_y) * 0.5, f"pectoral pair ({left_src}, {right_src})"
    if left_y is not None:
        return left_y, f"left pectoral ({left_src})"
    if right_y is not None:
        return right_y, f"right pectoral ({right_src})"
    return None, "fallback"


def _avg_pair_y(figure, left_bones: list[str], right_bones: list[str]) -> tuple[float | None, str]:
    left_y, left_src = _find_anchor_y(figure, left_bones)
    right_y, right_src = _find_anchor_y(figure, right_bones)
    if left_y is not None and right_y is not None:
        return (left_y + right_y) * 0.5, f"avg({left_src}, {right_src})"
    if left_y is not None:
        return left_y, left_src
    if right_y is not None:
        return right_y, right_src
    return None, "fallback"


def _vertical_distance(top_y: float | None, bottom_y: float | None) -> float | None:
    if top_y is None or bottom_y is None:
        return None
    return abs(top_y - bottom_y)


def _figure_profile(figure) -> FigureProfile:
    bone_names = set()
    try:
        bone_names = {bone.name for bone in figure.bones()}
    except Exception:
        bone_names = set()

    if bone_names & GENESIS_9_BONES:
        return FigureProfile(
            name="Genesis 9",
            bust_left_candidates=PECTORAL_LEFT_CANDIDATES,
            bust_right_candidates=PECTORAL_RIGHT_CANDIDATES,
            bust_bones=["spine4", "spine3"],
            underbust_bones=["spine3", "spine2"],
            waist_bones=["spine2", "spine1"],
            low_hip_bones=["pelvis", "hip"],
            nape_bones=["neck2", "neck1", "neckLower"],
            shoulder_left_bones=["lShldrBend", "lShldr"],
            shoulder_right_bones=["rShldrBend", "rShldr"],
            crotch_left_bones=["lThighBend", "lThigh"],
            crotch_right_bones=["rThighBend", "rThigh"],
            wrist_left_bones=["lHand", "lCarpal1"],
            wrist_right_bones=["rHand", "rCarpal1"],
            neck_bones=["neck1", "neck2", "neckLower"],
            high_bust_left_bones=["lShldrBend", "lShldr"],
            high_bust_right_bones=["rShldrBend", "rShldr"],
            thigh_left_bones=["lThighBend", "lThigh"],
            thigh_right_bones=["rThighBend", "rThigh"],
            knee_left_bones=["lShin", "lKnee"],
            knee_right_bones=["rShin", "rKnee"],
            ankle_left_bones=["lFoot", "lAnkle"],
            ankle_right_bones=["rFoot", "rAnkle"],
            upper_arm_left_bones=["lShldrBend", "lShldr"],
            upper_arm_right_bones=["rShldrBend", "rShldr"],
            elbow_left_bones=["lForeArm", "lForeArmBend"],
            elbow_right_bones=["rForeArm", "rForeArmBend"],
            wrist_circ_left_bones=["lHand", "lCarpal1"],
            wrist_circ_right_bones=["rHand", "rCarpal1"],
        )

    if bone_names & GENESIS_8_BONES:
        return FigureProfile(
            name="Genesis 8/8.1",
            bust_left_candidates=PECTORAL_LEFT_CANDIDATES,
            bust_right_candidates=PECTORAL_RIGHT_CANDIDATES,
            bust_bones=["chestUpper", "chestLower", "chest"],
            underbust_bones=["chestLower", "abdomenUpper", "abdomen"],
            waist_bones=["abdomenUpper", "abdomenLower", "pelvis"],
            low_hip_bones=["pelvis", "hip"],
            nape_bones=["neckLower", "neck"],
            shoulder_left_bones=["lShldrBend", "lShldr"],
            shoulder_right_bones=["rShldrBend", "rShldr"],
            crotch_left_bones=["lThighBend", "lThigh"],
            crotch_right_bones=["rThighBend", "rThigh"],
            wrist_left_bones=["lHand", "lCarpal1"],
            wrist_right_bones=["rHand", "rCarpal1"],
            neck_bones=["neck", "neckLower"],
            high_bust_left_bones=["lShldrBend", "lShldr"],
            high_bust_right_bones=["rShldrBend", "rShldr"],
            thigh_left_bones=["lThigh", "lThighBend"],
            thigh_right_bones=["rThigh", "rThighBend"],
            knee_left_bones=["lShin"],
            knee_right_bones=["rShin"],
            ankle_left_bones=["lFoot"],
            ankle_right_bones=["rFoot"],
            upper_arm_left_bones=["lShldrBend", "lShldr"],
            upper_arm_right_bones=["rShldrBend", "rShldr"],
            elbow_left_bones=["lForeArm", "lForeArmBend"],
            elbow_right_bones=["rForeArm", "rForeArmBend"],
            wrist_circ_left_bones=["lHand", "lCarpal1"],
            wrist_circ_right_bones=["rHand", "rCarpal1"],
        )

    return FigureProfile(
        name="generic",
        bust_left_candidates=PECTORAL_LEFT_CANDIDATES,
        bust_right_candidates=PECTORAL_RIGHT_CANDIDATES,
        bust_bones=TORSO_BUST_BONES,
        underbust_bones=TORSO_UNDERBUST_BONES,
        waist_bones=["abdomen", "abdomen2", "spine2", "spine3", "pelvis"],
        low_hip_bones=TORSO_LOW_HIP_BONES,
        nape_bones=["neck2", "neck1", "neckLower", "neck"],
        shoulder_left_bones=["lShldrBend", "lShldr"],
        shoulder_right_bones=["rShldrBend", "rShldr"],
        crotch_left_bones=["lThighBend", "lThigh"],
        crotch_right_bones=["rThighBend", "rThigh"],
        wrist_left_bones=["lHand", "lCarpal1"],
        wrist_right_bones=["rHand", "rCarpal1"],
        neck_bones=["neck1", "neck2", "neckLower", "neck"],
        high_bust_left_bones=["lShldrBend", "lShldr"],
        high_bust_right_bones=["rShldrBend", "rShldr"],
        thigh_left_bones=["lThighBend", "lThigh"],
        thigh_right_bones=["rThighBend", "rThigh"],
        knee_left_bones=["lShin", "lKnee"],
        knee_right_bones=["rShin", "rKnee"],
        ankle_left_bones=["lFoot", "lAnkle"],
        ankle_right_bones=["rFoot", "rAnkle"],
        upper_arm_left_bones=["lShldrBend", "lShldr"],
        upper_arm_right_bones=["rShldrBend", "rShldr"],
        elbow_left_bones=["lForeArm", "lForeArmBend"],
        elbow_right_bones=["rForeArm", "rForeArmBend"],
        wrist_circ_left_bones=["lHand", "lCarpal1"],
        wrist_circ_right_bones=["rHand", "rCarpal1"],
    )


def _figure_variant(figure_label: str) -> str | None:
    label = figure_label.lower()
    if "female" in label:
        return "Female"
    if "male" in label:
        return "Male"
    return None


def _figure_type_to_calibration_name(figure_type: str) -> str:
    match = re.fullmatch(r"G(?P<gen>\d+(?:\.\d+)?)(?P<sex>[MF])", figure_type.strip(), re.IGNORECASE)
    if match is None:
        raise SystemExit(
            "Invalid --figure-type value. Use G<gen><gender>, such as G9M, G9F, G8M, or G8.1F."
        )
    gen = match.group("gen")
    sex = "Male" if match.group("sex").upper() == "M" else "Female"
    if gen.endswith(".0"):
        gen = gen[:-2]
    return f"Genesis {gen} {sex}"


def _section_perimeter(mesh, y: float) -> float | None:
    section = mesh.section(
        plane_origin=(0.0, float(y), 0.0),
        plane_normal=(0.0, 1.0, 0.0),
    )
    if section is None:
        return None
    loop = _select_torso_loop(section)
    if loop is None:
        return None
    return _loop_perimeter(loop)


def _section_torso_perimeter(mesh, y: float) -> float | None:
    return _section_perimeter(mesh, y)


def _scan_extreme(mesh, start_y: float, stop_y: float, step: float, mode: str) -> tuple[float | None, float | None]:
    best_y = None
    best_value = None
    for y in frange(start_y, stop_y, step):
        value = _section_perimeter(mesh, y)
        if value is None:
            continue
        if best_value is None:
            best_y, best_value = y, value
            continue
        if mode == "max" and value > best_value:
            best_y, best_value = y, value
        elif mode == "min" and value < best_value:
            best_y, best_value = y, value
    return best_y, best_value


def _scan_profile(mesh, start_y: float, stop_y: float, step: float) -> list[tuple[float, float]]:
    profile: list[tuple[float, float]] = []
    for y in frange(start_y, stop_y, step):
        value = _section_perimeter(mesh, y)
        if value is not None:
            profile.append((y, value))
    return profile


def _robust_profile_max(profile: list[tuple[float, float]], max_multiplier: float = 1.35) -> tuple[float | None, float | None]:
    if not profile:
        return None, None
    values = sorted(v for _, v in profile)
    median = values[len(values) // 2]
    allowed = [(y, v) for y, v in profile if v <= median * max_multiplier]
    if not allowed:
        allowed = profile
    return max(allowed, key=lambda item: item[1])


def _calibration_for(figure_label: str, profile_name: str, figure_type: str | None = None) -> tuple[FigureCalibration, str]:
    candidates: list[str] = []
    if figure_type is not None:
        candidates.append(_figure_type_to_calibration_name(figure_type))
    candidates.append(figure_label)
    variant = _figure_variant(figure_label)
    if variant is not None and profile_name == "Genesis 9":
        candidates.append(f"Genesis 9 {variant}")
    if variant is not None and profile_name == "Genesis 8/8.1":
        candidates.append(f"Genesis 8 {variant}")
        candidates.append(f"Genesis 8.1 {variant}")
    candidates.append(profile_name)

    for candidate in candidates:
        if candidate in CALIBRATIONS:
            return CALIBRATIONS[candidate], candidate

    return FigureCalibration(
        bust=MeasurementCalibration(target_cm=None, band_below_cm=7.0, band_above_cm=3.0, fallback_mode="max"),
        underbust=MeasurementCalibration(target_cm=None, band_below_cm=8.0, band_above_cm=4.0, fallback_mode="min"),
        waist=MeasurementCalibration(target_cm=None, band_below_cm=10.0, band_above_cm=6.0, fallback_mode="min"),
        low_hip=MeasurementCalibration(target_cm=None, band_below_cm=10.0, band_above_cm=6.0, fallback_mode="max"),
    ), "heuristic"


def _scan_calibrated_band(
    mesh,
    center_y: float,
    calibration: MeasurementCalibration,
    step: float,
) -> tuple[float | None, float | None]:
    start = center_y - calibration.band_below_cm
    stop = center_y + calibration.band_above_cm
    profile: list[tuple[float, float]] = []
    for y in frange(start, stop, step):
        value = _section_perimeter(mesh, y)
        if value is not None:
            profile.append((y, value))
    if not profile:
        return None, None
    if calibration.target_cm is not None:
        return min(
            profile,
            key=lambda item: (abs(item[1] - calibration.target_cm), abs(item[0] - center_y)),
        )
    if calibration.fallback_mode == "min":
        return min(profile, key=lambda item: item[1])
    return _robust_profile_max(profile)


def _section_limb_pair_perimeter(mesh, y: float) -> float | None:
    """Average perimeter of the left+right symmetric limb loops at height y.

    Prefers cross-section loops whose centroid is laterally displaced from the
    body centerline (|x| large), so arm and leg contours are favoured over any
    co-planar torso contour at the same height.  Returns the mean of the two
    most-displaced loops when a symmetric pair is detected; otherwise the single
    best-displaced loop.
    """
    section = mesh.section(
        plane_origin=(0.0, float(y), 0.0),
        plane_normal=(0.0, 1.0, 0.0),
    )
    if section is None:
        return None
    loops = list(section.discrete)
    if not loops:
        return None

    candidates = []
    for loop in loops:
        perimeter = _loop_perimeter(loop)
        if perimeter <= 0:
            continue
        cx, _ = _loop_centroid(loop)
        candidates.append((abs(cx), perimeter))

    if not candidates:
        return None

    candidates.sort(key=lambda item: -item[0])

    if len(candidates) >= 2:
        d1, p1 = candidates[0]
        d2, p2 = candidates[1]
        if d1 > 0.5 and d2 > 0.3 and d2 / d1 > 0.5:
            return (p1 + p2) * 0.5

    return candidates[0][1]


def _scan_limb_band(
    mesh,
    center_y: float,
    below_cm: float,
    above_cm: float,
    mode: str,
    step: float,
) -> tuple[float | None, float | None]:
    start = center_y - below_cm
    stop = center_y + above_cm
    profile: list[tuple[float, float]] = []
    for y in frange(start, stop, step):
        value = _section_limb_pair_perimeter(mesh, y)
        if value is not None:
            profile.append((y, value))
    if not profile:
        return None, None
    if mode == "min":
        return min(profile, key=lambda item: item[1])
    return max(profile, key=lambda item: item[1])


def _build_mesh(vertices: list[list[float]], faces: list[list[int]]):
    if trimesh is None:
        raise SystemExit(
            "Missing dependency: trimesh. Install it with `pip install trimesh`."
        )
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


def _cm_to_in(value_cm: float | None) -> float | None:
    if value_cm is None:
        return None
    return value_cm / CM_PER_INCH


def _figure_gender(figure_label: str, figure_type: str | None, calibration_name: str) -> str | None:
    if figure_type is not None:
        if figure_type.strip().upper().endswith("F"):
            return "Female"
        if figure_type.strip().upper().endswith("M"):
            return "Male"
    label = figure_label.lower()
    if "female" in label:
        return "Female"
    if "male" in label:
        return "Male"
    if calibration_name.endswith("Female"):
        return "Female"
    if calibration_name.endswith("Male"):
        return "Male"
    return None


def _bra_band_from_underbust(underbust_in: float) -> int:
    # US traditional method: round underbust to nearest inch, add 4 if even or 5 if odd.
    # This always produces an even band number.
    rounded = int(round(underbust_in))
    band = rounded # + (4 if rounded % 2 == 0 else 5)
    return max(28, band)


def _cup_from_difference(diff_in: float, cups: list[str]) -> str:
    index = int(round(diff_in))
    if index < 0:
        index = 0
    if index >= len(cups):
        index = len(cups) - 1
    return cups[index]


def _bra_size_estimate(bust_cm: float | None, underbust_cm: float | None) -> BraSizeEstimate | None:
    if bust_cm is None or underbust_cm is None:
        return None
    bust_in = bust_cm / CM_PER_INCH
    underbust_in = underbust_cm / CM_PER_INCH
    band_us = _bra_band_from_underbust(underbust_in)
    band_uk = band_us
    band_eu = int(round((underbust_cm / 5.0))) * 5
    if band_eu < 60:
        band_eu = 60
    diff_us = bust_in - float(band_us)
    diff_uk = bust_in - float(band_uk)
    cup_us = _cup_from_difference(diff_us, US_BRA_CUPS)
    cup_uk = _cup_from_difference(diff_uk, UK_BRA_CUPS)
    cup_eu = cup_uk
    note = (
        "US traditional method: band = underbust rounded to nearest inch + 4 (if even) "
        "or + 5 (if odd); cup = bust minus band rounded to nearest inch (1\"=A, 2\"=B, "
        "3\"=C, 4\"=D, 5\"=DD, 6\"=DDD, …)"
    )
    return BraSizeEstimate(
        us=f"{band_us}{cup_us}",
        uk=f"{band_uk}{cup_uk}",
        eu=f"{band_eu}{cup_eu}",
        note=note,
        difference_in=diff_us,
        underbust_in=underbust_in,
        bust_in=bust_in,
    )


def _dress_size_estimate(bust_cm: float | None, waist_cm: float | None, hip_cm: float | None) -> DressSizeEstimate | None:
    if bust_cm is None or waist_cm is None or hip_cm is None:
        return None
    bust_in = bust_cm / CM_PER_INCH
    waist_in = waist_cm / CM_PER_INCH
    hip_in = hip_cm / CM_PER_INCH
    best = None
    best_score = None
    for entry in DRESS_SIZE_CHART:
        score = max(
            abs(bust_in - entry["bust_in"]) / 1.5,
            abs(waist_in - entry["waist_in"]) / 1.0,
            abs(hip_in - entry["hip_in"]) / 1.5,
        )
        if best_score is None or score < best_score:
            best = entry
            best_score = score
    if best is None:
        return None
    note = (
        "heuristic dress estimate; chart row chosen by closest bust/waist/hip match, "
        "and fit can vary by brand"
    )
    return DressSizeEstimate(
        us=str(best["us"]),
        uk=str(best["uk"]),
        eu=str(best["eu"]),
        note=note,
        bust_in=bust_in,
        waist_in=waist_in,
        hip_in=hip_in,
    )


def _clothing_estimate(result: dict, gender: str | None) -> ClothingEstimate | None:
    if gender != "Female":
        return None
    measurements = result["measurements"]
    bra = _bra_size_estimate(
        measurements["bust_circumference"]["value_cm"],
        measurements["underbust_circumference"]["value_cm"],
    )
    dress = _dress_size_estimate(
        measurements["bust_circumference"]["value_cm"],
        measurements["waist_circumference"]["value_cm"],
        measurements["low_hip_circumference"]["value_cm"],
    )
    if bra is None and dress is None:
        return None
    return ClothingEstimate(bra=bra, dress=dress, note="heuristic clothing estimate for female figures")


def measure_figure(
    figure_label: str,
    sample_step: float,
    search_window: float,
    torso_only: bool,
    figure_type: str | None,
    include_clothing: bool,
) -> dict:
    scene = DazScene()
    figure = scene.find_skeleton_by_label(figure_label)
    geometry = DazGeometry(scene._client, NodeIdentifier(figure_label, kind="label"))
    profile = _figure_profile(figure)
    calibration, calibration_name = _calibration_for(figure_label, profile.name, figure_type)
    gender = _figure_gender(figure_label, figure_type, calibration_name)

    verts = geometry.vertex_positions_posed_all()
    faces = DazGeometry.triangulate(geometry.face_vertex_indices_all())
    if not verts or not faces:
        raise SystemExit(f"Figure {figure_label!r} has no usable geometry.")

    mesh = _build_mesh(verts, faces)
    bounds = mesh.bounds
    min_y = float(bounds[0][1])
    max_y = float(bounds[1][1])
    height = max_y - min_y

    bust_y, bust_source = _find_pair_anchor_y(figure, profile.bust_left_candidates, profile.bust_right_candidates)
    if bust_y is None:
        bust_y, bust_source = _find_anchor_y(figure, profile.bust_bones)
    underbust_y, underbust_source = _find_anchor_y(figure, profile.underbust_bones)
    waist_y, waist_source = _find_anchor_y(figure, profile.waist_bones)
    lowhip_y, lowhip_source = _find_anchor_y(figure, profile.low_hip_bones)

    nape_y, nape_source = _find_anchor_y(figure, profile.nape_bones)
    shoulder_y, shoulder_source = _avg_pair_y(figure, profile.shoulder_left_bones, profile.shoulder_right_bones)
    crotch_y, crotch_source = _avg_pair_y(figure, profile.crotch_left_bones, profile.crotch_right_bones)
    wrist_y, wrist_source = _avg_pair_y(figure, profile.wrist_left_bones, profile.wrist_right_bones)

    neck_y, neck_source = _find_anchor_y(figure, profile.neck_bones)
    high_bust_y, high_bust_source = _avg_pair_y(figure, profile.high_bust_left_bones, profile.high_bust_right_bones)
    thigh_y, thigh_source = _avg_pair_y(figure, profile.thigh_left_bones, profile.thigh_right_bones)
    knee_y, knee_source = _avg_pair_y(figure, profile.knee_left_bones, profile.knee_right_bones)
    ankle_y, ankle_source = _avg_pair_y(figure, profile.ankle_left_bones, profile.ankle_right_bones)
    upper_arm_y, upper_arm_source = _avg_pair_y(figure, profile.upper_arm_left_bones, profile.upper_arm_right_bones)
    elbow_y, elbow_source = _avg_pair_y(figure, profile.elbow_left_bones, profile.elbow_right_bones)

    # Figure-specific calibration shifts the sample bands toward the measurement
    # convention used by product pages / Measure Metrics.
    bust_center = (bust_y if bust_y is not None else min_y + height * 0.78)
    underbust_center = (underbust_y if underbust_y is not None else min_y + height * 0.70)
    waist_center = (waist_y if waist_y is not None else min_y + height * 0.62)
    lowhip_center = (lowhip_y if lowhip_y is not None else min_y + height * 0.58)

    neck_center = neck_y if neck_y is not None else min_y + height * 0.93
    high_bust_center = high_bust_y if high_bust_y is not None else min_y + height * 0.83
    high_hip_center = (lowhip_y + HIGH_HIP_OFFSET_CM) if lowhip_y is not None else min_y + height * 0.61
    thigh_center = thigh_y if thigh_y is not None else min_y + height * 0.50
    knee_center = knee_y if knee_y is not None else min_y + height * 0.28
    ankle_center = ankle_y if ankle_y is not None else min_y + height * 0.07
    upper_arm_center = upper_arm_y if upper_arm_y is not None else min_y + height * 0.78
    elbow_center = elbow_y if elbow_y is not None else min_y + height * 0.65
    wrist_circ_center = wrist_y if wrist_y is not None else min_y + height * 0.55

    bust_cal = calibration.bust
    if torso_only:
        bust_cal = MeasurementCalibration(
            target_cm=bust_cal.target_cm,
            band_below_cm=bust_cal.band_below_cm * 0.75,
            band_above_cm=bust_cal.band_above_cm * 0.75,
            fallback_mode=bust_cal.fallback_mode,
        )

    bust_slice_y, bust_value = _scan_calibrated_band(mesh, bust_center, bust_cal, sample_step)
    underbust_slice_y, underbust_value = _scan_calibrated_band(mesh, underbust_center, calibration.underbust, sample_step)
    waist_slice_y, waist_value = _scan_calibrated_band(mesh, waist_center, calibration.waist, sample_step)
    lowhip_slice_y, lowhip_value = _scan_calibrated_band(mesh, lowhip_center, calibration.low_hip, sample_step)

    neck_slice_y, neck_value = _scan_calibrated_band(
        mesh, neck_center, MeasurementCalibration(None, 2.0, 2.0, "min"), sample_step
    )
    high_bust_slice_y, high_bust_value = _scan_calibrated_band(
        mesh, high_bust_center, MeasurementCalibration(None, 3.0, 3.0, "max"), sample_step
    )
    high_hip_slice_y, high_hip_value = _scan_calibrated_band(
        mesh, high_hip_center, MeasurementCalibration(None, 4.0, 4.0, "max"), sample_step
    )
    thigh_slice_y, thigh_value = _scan_limb_band(mesh, thigh_center, 15.0, 2.0, "max", sample_step)
    knee_slice_y, knee_value = _scan_limb_band(mesh, knee_center, 4.0, 4.0, "min", sample_step)
    calf_slice_y, calf_value = _scan_limb_band(mesh, knee_center, 20.0, 2.0, "max", sample_step)
    ankle_slice_y, ankle_value = _scan_limb_band(mesh, ankle_center, 3.0, 3.0, "min", sample_step)
    upper_arm_slice_y, upper_arm_value = _scan_limb_band(mesh, upper_arm_center, 12.0, 2.0, "max", sample_step)
    elbow_slice_y, elbow_value = _scan_limb_band(mesh, elbow_center, 4.0, 4.0, "min", sample_step)
    wrist_circ_slice_y, wrist_circ_value = _scan_limb_band(mesh, wrist_circ_center, 3.0, 3.0, "min", sample_step)

    measurements = {
        "height": SliceMeasurement(
            name="Height",
            value_cm=height,
            value_in=_cm_to_in(height),
            slice_y=None,
            source="mesh bounds",
            note=f"min_y={min_y:.3f}, max_y={max_y:.3f}",
        ),
        "neck_circumference": SliceMeasurement(
            name="Neck Circumference",
            value_cm=neck_value,
            value_in=_cm_to_in(neck_value),
            slice_y=neck_slice_y,
            source=neck_source,
            note=f"anchor_y={neck_center:.3f}",
        ),
        "high_bust_circumference": SliceMeasurement(
            name="High Bust Circumference",
            value_cm=high_bust_value,
            value_in=_cm_to_in(high_bust_value),
            slice_y=high_bust_slice_y,
            source=high_bust_source,
            note=f"anchor_y={high_bust_center:.3f}",
        ),
        "bust_circumference": SliceMeasurement(
            name="Bust Circumference",
            value_cm=bust_value,
            value_in=_cm_to_in(bust_value),
            slice_y=bust_slice_y,
            source=bust_source,
            note=f"anchor_y={bust_y:.3f}" if bust_y is not None else f"anchor_y={bust_center:.3f}; target_cm={bust_cal.target_cm}",
        ),
        "underbust_circumference": SliceMeasurement(
            name="Underbust Circumference",
            value_cm=underbust_value,
            value_in=_cm_to_in(underbust_value),
            slice_y=underbust_slice_y,
            source=underbust_source,
            note=f"anchor_y={underbust_center:.3f}; target_cm={calibration.underbust.target_cm}",
        ),
        "waist_circumference": SliceMeasurement(
            name="Waist Circumference",
            value_cm=waist_value,
            value_in=_cm_to_in(waist_value),
            slice_y=waist_slice_y,
            source=waist_source if waist_y is not None else "calibrated band",
            note=f"anchor_y={waist_center:.3f}; target_cm={calibration.waist.target_cm}",
        ),
        "high_hip_circumference": SliceMeasurement(
            name="High Hip Circumference",
            value_cm=high_hip_value,
            value_in=_cm_to_in(high_hip_value),
            slice_y=high_hip_slice_y,
            source=lowhip_source,
            note=f"anchor_y={high_hip_center:.3f}; +{HIGH_HIP_OFFSET_CM:.1f}cm above low hip",
        ),
        "low_hip_circumference": SliceMeasurement(
            name="Low Hip Circumference",
            value_cm=lowhip_value,
            value_in=_cm_to_in(lowhip_value),
            slice_y=lowhip_slice_y,
            source=lowhip_source,
            note=f"anchor_y={lowhip_center:.3f}; target_cm={calibration.low_hip.target_cm}",
        ),
        "thigh_circumference": SliceMeasurement(
            name="Thigh Circumference",
            value_cm=thigh_value,
            value_in=_cm_to_in(thigh_value),
            slice_y=thigh_slice_y,
            source=thigh_source,
            note=f"anchor_y={thigh_center:.3f}; scan 15cm below hip joint",
        ),
        "knee_circumference": SliceMeasurement(
            name="Knee Circumference",
            value_cm=knee_value,
            value_in=_cm_to_in(knee_value),
            slice_y=knee_slice_y,
            source=knee_source,
            note=f"anchor_y={knee_center:.3f}",
        ),
        "calf_circumference": SliceMeasurement(
            name="Calf Circumference",
            value_cm=calf_value,
            value_in=_cm_to_in(calf_value),
            slice_y=calf_slice_y,
            source=knee_source,
            note=f"anchor_y={knee_center:.3f}; scan 20cm below knee joint",
        ),
        "ankle_circumference": SliceMeasurement(
            name="Ankle Circumference",
            value_cm=ankle_value,
            value_in=_cm_to_in(ankle_value),
            slice_y=ankle_slice_y,
            source=ankle_source,
            note=f"anchor_y={ankle_center:.3f}",
        ),
        "upper_arm_circumference": SliceMeasurement(
            name="Upper Arm Circumference",
            value_cm=upper_arm_value,
            value_in=_cm_to_in(upper_arm_value),
            slice_y=upper_arm_slice_y,
            source=upper_arm_source,
            note=f"anchor_y={upper_arm_center:.3f}; scan 12cm below shoulder joint",
        ),
        "elbow_circumference": SliceMeasurement(
            name="Elbow Circumference",
            value_cm=elbow_value,
            value_in=_cm_to_in(elbow_value),
            slice_y=elbow_slice_y,
            source=elbow_source,
            note=f"anchor_y={elbow_center:.3f}",
        ),
        "wrist_circumference": SliceMeasurement(
            name="Wrist Circumference",
            value_cm=wrist_circ_value,
            value_in=_cm_to_in(wrist_circ_value),
            slice_y=wrist_circ_slice_y,
            source=wrist_source,
            note=f"anchor_y={wrist_circ_center:.3f}",
        ),
        "back_waist_length": SliceMeasurement(
            name="Back Waist Length",
            value_cm=_vertical_distance(nape_y, waist_y),
            value_in=_cm_to_in(_vertical_distance(nape_y, waist_y)),
            slice_y=None,
            source=f"{nape_source} → {waist_source}",
        ),
        "front_waist_length": SliceMeasurement(
            name="Front Waist Length",
            value_cm=_vertical_distance(shoulder_y, waist_y),
            value_in=_cm_to_in(_vertical_distance(shoulder_y, waist_y)),
            slice_y=None,
            source=f"{shoulder_source} → {waist_source}",
        ),
        "torso_length": SliceMeasurement(
            name="Torso Length",
            value_cm=_vertical_distance(shoulder_y, lowhip_y),
            value_in=_cm_to_in(_vertical_distance(shoulder_y, lowhip_y)),
            slice_y=None,
            source=f"{shoulder_source} → {lowhip_source}",
        ),
        "inseam": SliceMeasurement(
            name="Inseam",
            value_cm=_vertical_distance(crotch_y, min_y),
            value_in=_cm_to_in(_vertical_distance(crotch_y, min_y)),
            slice_y=None,
            source=f"{crotch_source} → floor",
        ),
        "outseam": SliceMeasurement(
            name="Outseam",
            value_cm=_vertical_distance(waist_y, min_y),
            value_in=_cm_to_in(_vertical_distance(waist_y, min_y)),
            slice_y=None,
            source=f"{waist_source} → floor",
        ),
        "sleeve_length": SliceMeasurement(
            name="Sleeve Length",
            value_cm=_vertical_distance(shoulder_y, wrist_y),
            value_in=_cm_to_in(_vertical_distance(shoulder_y, wrist_y)),
            slice_y=None,
            source=f"{shoulder_source} → {wrist_source}",
        ),
        "shoulder_to_bust": SliceMeasurement(
            name="Shoulder to Bust",
            value_cm=_vertical_distance(shoulder_y, bust_y),
            value_in=_cm_to_in(_vertical_distance(shoulder_y, bust_y)),
            slice_y=None,
            source=f"{shoulder_source} → {bust_source}",
        ),
        "waist_to_hip": SliceMeasurement(
            name="Waist to Hip",
            value_cm=_vertical_distance(waist_y, lowhip_y),
            value_in=_cm_to_in(_vertical_distance(waist_y, lowhip_y)),
            slice_y=None,
            source=f"{waist_source} → {lowhip_source}",
        ),
        "crotch_depth": SliceMeasurement(
            name="Crotch Depth",
            value_cm=_vertical_distance(waist_y, crotch_y),
            value_in=_cm_to_in(_vertical_distance(waist_y, crotch_y)),
            slice_y=None,
            source=f"{waist_source} → {crotch_source}",
        ),
    }

    clothing = _clothing_estimate({"measurements": {key: asdict(value) for key, value in measurements.items()}}, gender) if include_clothing else None

    return {
        "figure": figure_label,
        "profile": profile.name,
        "calibration": calibration_name,
        "gender": gender,
        "units": "scene units (usually centimeters)",
        "torso_only": torso_only,
        "figure_type": figure_type,
        "mesh": {
            "vertex_count": len(verts),
            "face_count": len(faces),
            "bounds": {"min_y": min_y, "max_y": max_y},
        },
        "measurements": {key: asdict(value) for key, value in measurements.items()},
        "clothing": asdict(clothing) if clothing is not None else None,
    }


def _fmt_value(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _fmt_measurement(item: dict) -> str:
    cm = _fmt_value(item["value_cm"])
    inches = _fmt_value(item["value_in"])
    return f"{cm} cm / {inches} in"


def _fmt_size_triplet(item: dict) -> str:
    return f"US {item['us']}, UK {item['uk']}, EU {item['eu']}"


def _bra_interpretation(item: dict) -> str:
    bust_in = item.get("bust_in")
    underbust_in = item.get("underbust_in")
    diff_in = item.get("difference_in")
    if bust_in is None or underbust_in is None or diff_in is None:
        return "Cup estimate is heuristic and based on the measured bust-minus-underbust difference."
    return (
        f"Bust {bust_in:.2f} in minus underbust {underbust_in:.2f} in gives "
        f"about {diff_in:.2f} in for the cup estimate."
    )


def _dress_interpretation(item: dict) -> str:
    bust_in = item.get("bust_in")
    waist_in = item.get("waist_in")
    hip_in = item.get("hip_in")
    if bust_in is None or waist_in is None or hip_in is None:
        return "Dress estimate is heuristic and based on the closest chart match."
    return (
        f"Closest chart match from bust {bust_in:.2f} in, waist {waist_in:.2f} in, "
        f"and hip {hip_in:.2f} in."
    )


def _format_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))
    lines = []
    header_line = "  ".join(header.ljust(widths[idx]) for idx, header in enumerate(headers))
    divider_line = "  ".join("-" * widths[idx] for idx in range(len(headers)))
    lines.append(header_line)
    lines.append(divider_line)
    for row in rows:
        lines.append("  ".join(row[idx].ljust(widths[idx]) for idx in range(len(headers))))
    return "\n".join(lines)


_CIRCUMFERENCE_KEYS = [
    "height",
    "neck_circumference",
    "high_bust_circumference",
    "bust_circumference",
    "underbust_circumference",
    "waist_circumference",
    "high_hip_circumference",
    "low_hip_circumference",
    "thigh_circumference",
    "knee_circumference",
    "calf_circumference",
    "ankle_circumference",
    "upper_arm_circumference",
    "elbow_circumference",
    "wrist_circumference",
]

_LENGTH_KEYS = [
    "back_waist_length",
    "front_waist_length",
    "torso_length",
    "inseam",
    "outseam",
    "sleeve_length",
    "shoulder_to_bust",
    "waist_to_hip",
    "crotch_depth",
]


def _measurement_rows(result: dict) -> list[list[str]]:
    rows = []
    for key in _CIRCUMFERENCE_KEYS + _LENGTH_KEYS:
        item = result["measurements"][key]
        rows.append(
            [
                item["name"],
                _fmt_measurement(item),
                _fmt_value(item["slice_y"]),
                item["source"],
                item.get("note") or "",
            ]
        )
    return rows


def _clothing_rows(result: dict) -> list[list[str]]:
    clothing = result.get("clothing") or {}
    rows = []
    bra = clothing.get("bra")
    if bra:
        rows.append(
            [
                "Bra",
                _fmt_size_triplet(bra),
                _bra_interpretation(bra),
            ]
        )
    dress = clothing.get("dress")
    if dress:
        rows.append(
            [
                "Dress",
                _fmt_size_triplet(dress),
                _dress_interpretation(dress),
            ]
        )
    return rows


def _bra_check_rows(result: dict) -> list[list[str]]:
    clothing = result.get("clothing") or {}
    bra = clothing.get("bra")
    if not bra:
        return []
    bust_in = bra.get("bust_in")
    underbust_in = bra.get("underbust_in")
    diff_in = bra.get("difference_in")
    if bust_in is None or underbust_in is None or diff_in is None:
        return []
    return [
        ["Bust", f"{bust_in:.2f} in", f"{bust_in * CM_PER_INCH:.2f} cm"],
        ["Underbust", f"{underbust_in:.2f} in", f"{underbust_in * CM_PER_INCH:.2f} cm"],
        ["Difference", f"{diff_in:.2f} in", f"{diff_in * CM_PER_INCH:.2f} cm"],
    ]


def _print_summary(result: dict, pretty: bool = False) -> None:
    print(f"Figure: {result['figure']}")
    print(f"Profile: {result['profile']}")
    print(f"Calibration: {result['calibration']}")
    if result.get("gender"):
        print(f"Gender: {result['gender']}")
    if result.get("figure_type"):
        print(f"Figure type: {result['figure_type']}")
    print(f"Torso-only bust filter: {'on' if result['torso_only'] else 'off'}")
    print(f"Units:   {result['units']}")
    mesh = result["mesh"]
    print(f"Mesh:    {mesh['vertex_count']:,} vertices, {mesh['face_count']:,} triangles")
    print(f"Bounds:  y={mesh['bounds']['min_y']:.2f} to {mesh['bounds']['max_y']:.2f}")
    print("")
    if pretty:
        print("Measurements:")
        print(
            _format_table(
                ["Measurement", "Value", "Slice Y", "Source", "Note"],
                _measurement_rows(result),
            )
        )
    else:
        for key in _CIRCUMFERENCE_KEYS + _LENGTH_KEYS:
            item = result["measurements"][key]
            suffix = f"{_fmt_measurement(item)}"
            details = f"  (slice_y={_fmt_value(item['slice_y'])}, source={item['source']})"
            if item.get("note"):
                details += f"  [{item['note']}]"
            print(f"{item['name']}: {suffix}{details}")

    clothing_rows = _clothing_rows(result)
    if clothing_rows:
        print("")
        if pretty:
            print("Clothing:")
            print(_format_table(["Item", "Sizes", "Interpretation"], clothing_rows))
            clothing = result.get("clothing") or {}
            bra_check_rows = _bra_check_rows(result)
            if bra_check_rows:
                print("")
                print("Bra Check:")
                print(_format_table(["Measure", "Inches", "Centimeters"], bra_check_rows))
            if clothing.get("note"):
                print(f"Note: {clothing['note']}")
        else:
            print("Clothing:")
            for row in clothing_rows:
                print(f"  {row[0]}: {row[1]}")
                print(f"    {row[2]}")
            clothing = result.get("clothing")
            if clothing and clothing.get("note"):
                print(f"  Note: {clothing['note']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--figure", default="Genesis 9", help="Figure label in the Scene panel")
    parser.add_argument(
        "--sample-step",
        type=float,
        default=0.5,
        help="Slice spacing in scene units when searching for local extrema",
    )
    parser.add_argument(
        "--search-window",
        type=float,
        default=5.0,
        help="Half-width of the bust / underbust / low-hip search window",
    )
    parser.add_argument(
        "--torso-only",
        action="store_true",
        help="Use a robust bust slice selector that ignores obvious arm-spread outliers",
    )
    parser.add_argument(
        "--clothing",
        action="store_true",
        help="Estimate female clothing sizes such as bra and dress sizes from the measured body",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Render the summary as cleaner tables instead of a debug-style listing",
    )
    parser.add_argument(
        "--figure-type",
        default=None,
        help="Explicit figure type override in the form G<gen><gender>, such as G9M or G8.1F",
    )
    parser.add_argument(
        "--out",
        default="measurements.json",
        help="Write the computed measurements to JSON",
    )
    args = parser.parse_args()

    result = measure_figure(
        args.figure,
        args.sample_step,
        args.search_window,
        args.torso_only,
        args.figure_type,
        args.clothing,
    )
    _print_summary(result, args.pretty)

    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"\nSaved JSON to {args.out}")
