"""Pose/expression preset library loading and combo layering.

Pose presets are plain :class:`dazpy.DazPose` JSON files (see
``author_pose_preset.py``). Expression presets are a thin parallel type that
only ever touches morph channels, never bone rotations -- see
:class:`ExpressionPreset`.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from dazpy import DazPose

if TYPE_CHECKING:
    from dazpy import DazSkeleton
    from schema import ComboEntry


@dataclass
class ExpressionPreset:
    """A named collection of facial morph values -- the expression analog of DazPose.

    Deliberately excludes bones/props: applying an expression must never
    disturb the body pose already applied to the figure.
    """

    figure: str
    morphs: dict[str, float] = field(default_factory=dict)

    @classmethod
    def capture(cls, skeleton: "DazSkeleton") -> "ExpressionPreset":
        pose = DazPose.capture(skeleton)
        return cls(figure=pose.figure, morphs=pose.morphs)

    @classmethod
    def load(cls, path: str | Path) -> "ExpressionPreset":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls(figure=data.get("figure", ""), morphs=data.get("morphs", {}))

    def save(self, path: str | Path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    def to_dict(self) -> dict:
        return {"figure": self.figure, "morphs": self.morphs}

    def apply(self, skeleton: "DazSkeleton") -> None:
        # bones={} / props={} -> DazPose.apply() only touches morph channels,
        # leaving whatever body pose was applied earlier untouched.
        DazPose(figure=self.figure, bones={}, morphs=self.morphs, props={}).apply(skeleton)


def pose_preset_path(pose_library_dir: str, pose_name: str) -> str:
    return os.path.join(pose_library_dir, f"{pose_name}.json")


def expression_preset_path(expression_library_dir: str, expression_name: str) -> str:
    return os.path.join(expression_library_dir, f"{expression_name}.json")


def merge_overrides(base: dict, overrides: dict) -> dict:
    """Layer *overrides* (``{"bones": {...}, "morphs": {...}, "props": {...}}``)
    on top of *base* of the same shape. Pure dict merge, no I/O.
    """
    result = {"bones": dict(base.get("bones", {})), "morphs": dict(base.get("morphs", {})), "props": dict(base.get("props", {}))}
    for key in ("bones", "morphs", "props"):
        result[key].update(overrides.get(key, {}))
    return result


def build_override_pose(figure: str, overrides: dict) -> DazPose:
    return DazPose(
        figure=figure,
        bones=overrides.get("bones", {}),
        morphs=overrides.get("morphs", {}),
        props=overrides.get("props", {}),
    )


def apply_combo(
    skeleton: "DazSkeleton",
    figure: str,
    pose_library_dir: str,
    expression_library_dir: str,
    combo: "ComboEntry",
) -> None:
    """Apply a combo's pose, expression, then overrides (in that order) to *skeleton*.

    Caller is responsible for restoring a pristine baseline before calling
    this -- see render_stage.py.
    """
    pose = DazPose.load(pose_preset_path(pose_library_dir, combo.pose))
    pose.apply(skeleton)

    expression = ExpressionPreset.load(expression_preset_path(expression_library_dir, combo.expression))
    expression.apply(skeleton)

    if combo.overrides:
        build_override_pose(figure, combo.overrides).apply(skeleton)
