"""Interaction plans and recipes: validation, staging/lowering to pose patches, recipe builders."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal
from collections.abc import Callable

from ._interaction_profile import (
    BalanceTarget,
    ContactTarget,
    FigureRigProfile,
    FootTarget,
    HandTarget,
    LookAtTarget,
    PoseTarget,
    ResolvedInteractionTarget,
    ValidationIssue,
    Vector3,
    _as_tuple3,
    _lookup_rig_profile,
    _normalize_name,
    _side_from_name,
    _vec3_add,
    _vec3_average,
    _vec3_length,
    _vec3_midpoint,
    _vec3_scale,
    _vec3_sub,
    build_rig_profile,
    build_rig_profiles_from_snapshot,
    resolve_interaction_target,
)
from ._interaction_solver import (
    LimbAlignmentResult,
    _align_single_limb_batch,
    align_single_limb_target,
)
from ._interaction_facing import (
    FACING_FOOT_REACH_FRACTION,
    FACING_MIN_SEPARATION,
    FACING_REACH_FRACTION,
    FacingAssignment,
    WRAP_HAND_LIMIT,
    WRAP_SEPARATION,
    _ContactGeometry,
    _FACING_MAX_SEPARATION,
    _anchor_bone_offset,
    _apply_facing,
    _displacement_for_profile,
    _farthest_descendant,
    _limb_geometry,
    _limb_root_offset,
    _meeting_point,
    _pull_toward_root,
    _standoff_shift,
    _surface_contact_point,
    _wrap_path,
    figure_forward,
    plan_facing,
)


InteractionKind = Literal["PoseTarget", "ContactTarget", "LookAtTarget", "BalanceTarget", "HandTarget", "FootTarget"]
RecipeKind = Literal["sit", "touch", "kiss", "fight", "handshake", "hug", "face_each_other", "custom"]


@dataclass
class SolveOptions:
    """Tunable options for later solver phases."""

    backend: Literal["scipy", "pinocchio", "ikpy", "auto"] = "auto"
    max_iterations: int = 100
    use_joint_limits: bool = True
    rest_pose_weight: float = 0.15
    contact_weight: float = 1.0
    position_weight: float = 1.0
    orientation_weight: float = 0.25

    def to_dict(self) -> dict:
        return {
            "backend": self.backend,
            "max_iterations": self.max_iterations,
            "use_joint_limits": self.use_joint_limits,
            "rest_pose_weight": self.rest_pose_weight,
            "contact_weight": self.contact_weight,
            "position_weight": self.position_weight,
            "orientation_weight": self.orientation_weight,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SolveOptions:
        return cls(
            backend=data.get("backend", "auto"),
            max_iterations=int(data.get("max_iterations", 100)),
            use_joint_limits=bool(data.get("use_joint_limits", True)),
            rest_pose_weight=float(data.get("rest_pose_weight", 0.15)),
            contact_weight=float(data.get("contact_weight", 1.0)),
            position_weight=float(data.get("position_weight", 1.0)),
            orientation_weight=float(data.get("orientation_weight", 0.25)),
        )


def _as_optional_float(value: object | None) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]


@dataclass
class InteractionPlan:
    """A collection of interaction constraints across one or more figures."""

    actors: list[str]
    constraints: list[PoseTarget | ContactTarget | LookAtTarget | BalanceTarget | HandTarget | FootTarget] = field(default_factory=list)
    options: SolveOptions = field(default_factory=SolveOptions)
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "actors": list(self.actors),
            "constraints": [constraint.to_dict() for constraint in self.constraints],
            "options": self.options.to_dict(),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict) -> InteractionPlan:
        constraints: list[PoseTarget | ContactTarget | LookAtTarget | BalanceTarget | HandTarget | FootTarget] = []
        for item in data.get("constraints", []):
            kind = item.get("kind")
            if kind == "PoseTarget":
                constraints.append(
                    PoseTarget(
                        figure_label=item.get("figure_label", ""),
                        bone_name=item.get("bone_name", ""),
                        position=_as_tuple3(item.get("position")),
                        orientation=_as_tuple3(item.get("orientation")),
                    )
                )
            elif kind == "HandTarget":
                constraints.append(
                    HandTarget(
                        figure_label=item.get("figure_label", ""),
                        anchor_name=item.get("anchor_name", ""),
                        target_figure=item.get("target_figure"),
                        target_anchor=item.get("target_anchor"),
                        target_point=_as_tuple3(item.get("target_point")),
                        offset=_as_tuple3(item.get("offset")) or (0.0, 0.0, 0.0),
                        surface_standoff=_as_optional_float(item.get("surface_standoff")),
                        wrap=bool(item.get("wrap", False)),
                    )
                )
            elif kind == "FootTarget":
                constraints.append(
                    FootTarget(
                        figure_label=item.get("figure_label", ""),
                        anchor_name=item.get("anchor_name", ""),
                        target_figure=item.get("target_figure"),
                        target_anchor=item.get("target_anchor"),
                        target_point=_as_tuple3(item.get("target_point")),
                        offset=_as_tuple3(item.get("offset")) or (0.0, 0.0, 0.0),
                        surface_standoff=_as_optional_float(item.get("surface_standoff")),
                        wrap=bool(item.get("wrap", False)),
                    )
                )
            elif kind == "ContactTarget":
                constraints.append(
                    ContactTarget(
                        source_figure=item.get("source_figure", ""),
                        source_bone=item.get("source_bone", ""),
                        target_figure=item.get("target_figure"),
                        target_bone=item.get("target_bone"),
                        target_point=_as_tuple3(item.get("target_point")),
                    )
                )
            elif kind == "LookAtTarget":
                target_point = _as_tuple3(item.get("target_point"))
                if target_point is None:
                    continue
                constraints.append(
                    LookAtTarget(
                        figure_label=item.get("figure_label", ""),
                        bone_name=item.get("bone_name", ""),
                        target_point=target_point,
                    )
                )
            elif kind == "BalanceTarget":
                constraints.append(
                    BalanceTarget(
                        figure_label=item.get("figure_label", ""),
                        pelvis_bone=item.get("pelvis_bone", ""),
                        support_points=[tuple(point) for point in item.get("support_points", [])],
                        center_of_mass_hint=_as_tuple3(item.get("center_of_mass_hint")),
                    )
                )
        return cls(
            actors=list(data.get("actors", [])),
            constraints=constraints,
            options=SolveOptions.from_dict(data.get("options", {})),
            metadata=dict(data.get("metadata", {})),
        )

    def validate(self, rig_profiles: dict[str, FigureRigProfile]) -> list[ValidationIssue]:
        """Validate that all referenced figures and bones exist."""

        issues: list[ValidationIssue] = []
        for index, constraint in enumerate(self.constraints):
            if isinstance(constraint, PoseTarget):
                profile = _lookup_rig_profile(rig_profiles, constraint.figure_label)
                if profile is None:
                    issues.append(
                        ValidationIssue("error", constraint.figure_label, index, f"Unknown figure {constraint.figure_label!r}")
                    )
                    continue
                if constraint.bone_name not in profile.bone_names():
                    issues.append(
                        ValidationIssue("error", constraint.figure_label, index, f"Unknown bone {constraint.bone_name!r} on figure {constraint.figure_label!r}")
                    )
            elif isinstance(constraint, LookAtTarget):
                profile = _lookup_rig_profile(rig_profiles, constraint.figure_label)
                if profile is None:
                    issues.append(
                        ValidationIssue("error", constraint.figure_label, index, f"Unknown figure {constraint.figure_label!r}")
                    )
                    continue
                if constraint.bone_name not in profile.bone_names():
                    issues.append(
                        ValidationIssue("error", constraint.figure_label, index, f"Unknown bone {constraint.bone_name!r} on figure {constraint.figure_label!r}")
                    )
            elif isinstance(constraint, ContactTarget):
                profile = _lookup_rig_profile(rig_profiles, constraint.source_figure)
                if profile is None:
                    issues.append(
                        ValidationIssue("error", constraint.source_figure, index, f"Unknown source figure {constraint.source_figure!r}")
                    )
                    continue
                if constraint.source_bone not in profile.bone_names():
                    issues.append(
                        ValidationIssue("error", constraint.source_figure, index, f"Unknown source bone {constraint.source_bone!r} on figure {constraint.source_figure!r}")
                    )
                if constraint.target_figure and constraint.target_bone:
                    target_profile = _lookup_rig_profile(rig_profiles, constraint.target_figure)
                    if target_profile is None:
                        issues.append(
                            ValidationIssue("error", constraint.target_figure, index, f"Unknown target figure {constraint.target_figure!r}")
                        )
                    elif constraint.target_bone not in target_profile.bone_names():
                        issues.append(
                            ValidationIssue("error", constraint.target_figure, index, f"Unknown target bone {constraint.target_bone!r} on figure {constraint.target_figure!r}")
                        )
            elif isinstance(constraint, BalanceTarget):
                profile = _lookup_rig_profile(rig_profiles, constraint.figure_label)
                if profile is None:
                    issues.append(
                        ValidationIssue("error", constraint.figure_label, index, f"Unknown figure {constraint.figure_label!r}")
                    )
                    continue
                if profile.anchor_or_bone(constraint.pelvis_bone) is None:
                    issues.append(
                        ValidationIssue("error", constraint.figure_label, index, f"Unknown pelvis anchor or bone {constraint.pelvis_bone!r} on figure {constraint.figure_label!r}")
                    )
            elif isinstance(constraint, (HandTarget, FootTarget)):
                profile = _lookup_rig_profile(rig_profiles, constraint.figure_label)
                if profile is None:
                    issues.append(
                        ValidationIssue("error", constraint.figure_label, index, f"Unknown figure {constraint.figure_label!r}")
                    )
                    continue
                if constraint.anchor_name not in profile.anchor_names():
                        issues.append(
                            ValidationIssue("error", constraint.figure_label, index, f"Unknown anchor {constraint.anchor_name!r} on figure {constraint.figure_label!r}")
                        )
                if constraint.target_figure and constraint.target_anchor:
                    target_profile = _lookup_rig_profile(rig_profiles, constraint.target_figure)
                    if target_profile is None:
                        issues.append(
                            ValidationIssue("error", constraint.target_figure, index, f"Unknown target figure {constraint.target_figure!r}")
                        )
                    elif constraint.target_anchor not in target_profile.anchor_names():
                        issues.append(
                            ValidationIssue("error", constraint.target_figure, index, f"Unknown target anchor {constraint.target_anchor!r} on figure {constraint.target_figure!r}")
                        )
        return issues

    def resolve_targets(self, rig_profiles: dict[str, FigureRigProfile]) -> list[ResolvedInteractionTarget]:
        """Resolve hand and foot goals into concrete anchors and points."""

        resolved: list[ResolvedInteractionTarget] = []
        for constraint in self.constraints:
            if isinstance(constraint, (HandTarget, FootTarget)):
                profile = _lookup_rig_profile(rig_profiles, constraint.figure_label)
                if profile is None:
                    continue
                resolved.append(resolve_interaction_target(constraint, rig_profiles))
        return resolved


@dataclass
class InteractionRecipe:
    """A higher-level interaction preset that expands into an interaction plan."""

    kind: RecipeKind
    actors: list[str]
    constraints: list[PoseTarget | ContactTarget | LookAtTarget | BalanceTarget | HandTarget | FootTarget] = field(default_factory=list)
    options: SolveOptions = field(default_factory=SolveOptions)
    metadata: dict[str, object] = field(default_factory=dict)

    def to_plan(self) -> InteractionPlan:
        return InteractionPlan(
            actors=list(self.actors),
            constraints=list(self.constraints),
            options=self.options,
            metadata=dict(self.metadata),
        )

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "actors": list(self.actors),
            "constraints": [constraint.to_dict() for constraint in self.constraints],
            "options": self.options.to_dict(),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict) -> InteractionRecipe:
        plan = InteractionPlan.from_dict(data)
        return cls(
            kind=data.get("kind", "custom"),
            actors=plan.actors,
            constraints=plan.constraints,
            options=plan.options,
            metadata=plan.metadata,
        )


@dataclass
class PreparedInteractionRecipe:
    """A compiled recipe ready for a live DAZ session or a future solver."""

    recipe: InteractionRecipe
    plan: InteractionPlan
    resolved_targets: list[ResolvedInteractionTarget] = field(default_factory=list)
    rig_profiles: dict[str, FigureRigProfile] = field(default_factory=dict)
    validation_issues: list[ValidationIssue] = field(default_factory=list)
    diagnostics: dict[str, object] = field(default_factory=dict)
    # Partner figure label -> the figure it is turned to face and by how much.
    # ``rig_profiles`` (and so ``resolved_targets``) already have these turns
    # applied; ``build_pose_patch`` stages each partner a limb target links in
    # front of its anchor (a look-only partner is only turned).
    facing: dict[str, FacingAssignment] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.validation_issues)

    def to_dict(self) -> dict:
        return {
            "recipe": self.recipe.to_dict(),
            "plan": self.plan.to_dict(),
            "resolved_targets": [target.to_dict() for target in self.resolved_targets],
            "rig_profiles": {label: profile.to_dict() for label, profile in self.rig_profiles.items()},
            "validation_issues": [issue.to_dict() for issue in self.validation_issues],
            "diagnostics": dict(self.diagnostics),
            "facing": {label: assignment.to_dict() for label, assignment in self.facing.items()},
        }

    def build_pose_patch(self) -> InteractionPosePatch:
        """Build a coarse live-placement patch from the prepared recipe.

        Intentionally conservative: translates figures so their anchors are
        staged near their requested targets (hand/foot targets in X/Z only, a
        ``BalanceTarget`` also sets height). A faced partner (see ``facing``)
        is turned and placed straight in front of its anchor figure, as far as
        the shortest limb between them comfortably reaches. Does not solve bone
        rotations (that's ``align_limb_targets``).
        """

        # Each staged position records whether it sets the figure's height.
        # Hand/foot targets are floor-locked (X/Z only; IK handles reach), a
        # BalanceTarget (sit) sets full 3D.
        figure_positions: dict[str, list[tuple[Vector3, bool]]] = {}
        unresolved: list[ResolvedInteractionTarget] = []

        def _floor_height(label: str) -> float:
            profile = _lookup_rig_profile(self.rig_profiles, label)
            if profile is not None and profile.figure_position is not None:
                return profile.figure_position[1]
            return 0.0

        def _append_position(label: str, point: Vector3, sets_height: bool = False) -> None:
            figure_positions.setdefault(label, []).append((point, sets_height))

        def _staged_position(label: str | None) -> Vector3 | None:
            if not label or not figure_positions.get(label):
                return None
            entries = figure_positions[label]
            xz = _vec3_average([point for point, _ in entries])
            assert xz is not None  # entries is non-empty
            heights = [point[1] for point, sets_height in entries if sets_height]
            y = sum(heights) / len(heights) if heights else _floor_height(label)
            return (xz[0], y, xz[2])

        for constraint in self.plan.constraints:
            if isinstance(constraint, BalanceTarget):
                profile = _lookup_rig_profile(self.rig_profiles, constraint.figure_label)
                if profile is None:
                    continue
                pelvis_bone = profile.anchor_or_bone(constraint.pelvis_bone)
                if pelvis_bone is None:
                    unresolved.append(
                        ResolvedInteractionTarget(
                            figure_label=constraint.figure_label,
                            anchor_name=constraint.pelvis_bone,
                            bone_name=constraint.pelvis_bone,
                        )
                    )
                    continue
                pelvis_offset = profile.bone_offset(pelvis_bone)
                target_point = constraint.center_of_mass_hint
                if target_point is None and constraint.support_points:
                    target_point = _vec3_average(list(constraint.support_points))
                if target_point is None or pelvis_offset is None:
                    unresolved.append(
                        ResolvedInteractionTarget(
                            figure_label=constraint.figure_label,
                            anchor_name=constraint.pelvis_bone,
                            bone_name=pelvis_bone,
                            target_point=target_point,
                        )
                    )
                    continue
                _append_position(constraint.figure_label, _vec3_sub(target_point, pelvis_offset), sets_height=True)

        # Faced pairs: the partner goes straight in front of its anchor figure.
        faced_targets: set[int] = set()
        figure_yaw_degrees: dict[str, float] = {}
        for partner_label, assignment in self.facing.items():
            figure_yaw_degrees[partner_label] = assignment.yaw_degrees
            anchor_profile = _lookup_rig_profile(self.rig_profiles, assignment.anchor)
            partner_profile = _lookup_rig_profile(self.rig_profiles, partner_label)
            if anchor_profile is None or partner_profile is None or partner_profile.figure_position is None:
                continue
            forward = figure_forward(anchor_profile)
            anchor_base = _staged_position(assignment.anchor) or anchor_profile.figure_position
            if forward is None or anchor_base is None:
                continue
            faced = self._stage_faced_partner(anchor_profile, partner_profile, anchor_base, forward)
            if faced is None:
                continue
            partner_position, between = faced
            _append_position(partner_label, partner_position)
            faced_targets.update(id(target) for target in between)

        for resolved in self.resolved_targets:
            if id(resolved) in faced_targets:
                continue
            profile = _lookup_rig_profile(self.rig_profiles, resolved.figure_label)
            if profile is None:
                unresolved.append(resolved)
                continue
            source_anchor = profile.anchor(resolved.anchor_name)
            if source_anchor is None:
                unresolved.append(resolved)
                continue
            source_offset = profile.bone_offset(source_anchor.bone_name)
            if source_offset is None:
                unresolved.append(resolved)
                continue
            target_profile = _lookup_rig_profile(self.rig_profiles, resolved.target_figure) if resolved.target_figure else None
            target_offset = _anchor_bone_offset(target_profile, resolved.target_anchor) if (target_profile and resolved.target_anchor) else None
            source_base = _staged_position(resolved.figure_label)
            target_base = _staged_position(resolved.target_figure)

            if target_profile is not None and resolved.target_figure is not None:
                if target_base is not None and resolved.target_point is not None and source_base is None:
                    world_target = _vec3_add(target_base, resolved.target_point)
                    _append_position(resolved.figure_label, _vec3_sub(world_target, source_offset))
                    continue

                if target_offset is not None:
                    # Stage the effector a surface standoff short of the target
                    # joint, on the source limb's side, so IK starts at the
                    # contact point instead of folding the arm back to it.
                    root_offset = _limb_root_offset(profile, source_anchor.bone_name)
                    if source_base is None and target_base is None:
                        contact_center = _vec3_midpoint(source_offset, target_offset)
                        source_position = _vec3_sub(contact_center, source_offset)
                        target_position = _vec3_sub(contact_center, target_offset)
                        gap = _standoff_shift(contact_center, source_position, root_offset, resolved.surface_standoff)
                        _append_position(resolved.figure_label, _vec3_add(source_position, _vec3_scale(gap, 0.5)))
                        _append_position(resolved.target_figure, _vec3_sub(target_position, _vec3_scale(gap, 0.5)))
                    elif source_base is None and target_base is not None:
                        target_world = _vec3_add(target_base, target_offset)
                        source_position = _vec3_sub(target_world, source_offset)
                        gap = _standoff_shift(target_world, source_position, root_offset, resolved.surface_standoff)
                        _append_position(resolved.figure_label, _vec3_add(source_position, gap))
                    elif source_base is not None and target_base is None:
                        source_world = _vec3_add(source_base, source_offset)
                        target_world = _vec3_sub(source_world, target_offset)
                        gap = _standoff_shift(source_world, source_base, root_offset, resolved.surface_standoff)
                        _append_position(resolved.target_figure, _vec3_sub(target_world, gap))
                    continue

            if resolved.target_point is None:
                unresolved.append(resolved)
                continue
            _append_position(resolved.figure_label, _vec3_sub(resolved.target_point, source_offset))

        averaged_positions: dict[str, Vector3] = {}
        for label in figure_positions:
            staged = _staged_position(label)
            if staged is not None:
                averaged_positions[label] = staged
        diagnostics: dict[str, object] = {
            "figure_count": len(averaged_positions),
            "unresolved_target_count": len(unresolved),
        }
        return InteractionPosePatch(
            figure_positions=averaged_positions,
            figure_yaw_degrees=figure_yaw_degrees,
            unresolved_targets=unresolved,
            diagnostics=diagnostics,
        )

    def apply(
        self,
        scene: Any,
        *,
        align_limb_targets: bool = False,
        max_iterations: int | None = None,
        step_degrees: float = 1.0,
        damping: float = 0.25,
        tolerance: float = 0.15,
    ) -> PreparedInteractionResult:
        """Apply the compiled recipe, optionally aligning a single limb chain."""

        patch = self.build_pose_patch()
        patch.apply(scene)
        result = PreparedInteractionResult(
            prepared=self,
            pose_patch=patch,
        )
        if align_limb_targets:
            result.alignment_results = self.align_limb_targets(
                scene,
                max_iterations=max_iterations,
                step_degrees=step_degrees,
                damping=damping,
                tolerance=tolerance,
                figure_displacements=self._staging_displacements(patch),
            )
        return result

    def _staging_displacements(self, patch: InteractionPosePatch) -> dict[str, Vector3]:
        """How far the patch moved each figure whose original position is known."""

        displacements: dict[str, Vector3] = {}
        for label, position in patch.figure_positions.items():
            profile = _lookup_rig_profile(self.rig_profiles, label)
            if profile is not None and profile.figure_position is not None:
                displacements[label] = _vec3_sub(position, profile.figure_position)
        return displacements

    def align_limb_targets(
        self,
        scene: Any,
        *,
        max_iterations: int | None = None,
        step_degrees: float = 1.0,
        damping: float = 0.25,
        tolerance: float = 0.15,
        figure_displacements: dict[str, Vector3] | None = None,
    ) -> list[LimbAlignmentResult]:
        """Apply live limb alignment for resolved hand and foot targets.

        ``figure_displacements`` (label -> how far staging moved that figure)
        shifts targets that point at another figure's anchor, whose resolved
        point was captured before staging. ``apply`` passes it.
        """

        alignment_results: list[LimbAlignmentResult] = []
        for resolved in self.resolved_targets:
            if resolved.target_point is None:
                continue
            if figure_displacements and resolved.target_figure and resolved.target_anchor:
                # Match by resolved profile, so label aliases ("Genesis9") still match.
                target_profile = _lookup_rig_profile(self.rig_profiles, resolved.target_figure)
                shift = next(
                    (
                        displacement
                        for label, displacement in figure_displacements.items()
                        if target_profile is not None and _lookup_rig_profile(self.rig_profiles, label) is target_profile
                    ),
                    None,
                )
                if shift is not None:
                    resolved = replace(resolved, target_point=_vec3_add(resolved.target_point, shift))
            skeleton = scene.find_skeleton_by_label(resolved.figure_label)
            profile = _lookup_rig_profile(self.rig_profiles, resolved.figure_label)
            if profile is None:
                continue
            # Checked at the loop top, but replace() above drops mypy's narrowing.
            joint_point = resolved.target_point
            if joint_point is None:
                continue
            solve = dict(
                max_iterations=max_iterations or self.plan.options.max_iterations,
                step_degrees=step_degrees,
                damping=damping,
                tolerance=tolerance,
            )
            if resolved.wrap:
                wrapped = self._align_wrap(skeleton, profile, resolved, self._staged_bases(figure_displacements), solve)
                if wrapped is not None:
                    alignment_results.append(wrapped)
                    continue
            # Hand-to-hand both ways (handshake): both hands meet halfway
            # instead of chasing each other's rest positions.
            meeting = (
                self._contact_geometry(resolved, self._staged_bases(figure_displacements))
                if self._mutual_target(resolved) is not None
                else None
            )
            if meeting is not None:
                resolved = replace(resolved, target_point=meeting.stop)
            elif resolved.surface_standoff > 0.0:
                source_shift = _displacement_for_profile(self.rig_profiles, profile, figure_displacements)
                resolved = replace(resolved, target_point=_surface_contact_point(profile, resolved, source_shift))
            result = align_single_limb_target(
                skeleton,
                profile,
                resolved,
                max_iterations=max_iterations or self.plan.options.max_iterations,
                step_degrees=step_degrees,
                damping=damping,
                tolerance=tolerance,
            )
            if meeting is not None:
                result.diagnostics["meeting_point"] = list(meeting.joint)
            if resolved.surface_standoff > 0.0:
                result.diagnostics["surface_standoff"] = resolved.surface_standoff
                result.diagnostics["target_joint_point"] = list(joint_point)
            alignment_results.append(result)
        return alignment_results

    def _align_wrap(
        self,
        skeleton: Any,
        profile: FigureRigProfile,
        resolved: ResolvedInteractionTarget,
        bases: dict[int, Vector3],
        solve: dict[str, Any],
    ) -> LimbAlignmentResult | None:
        """IK passes for a wrap target: through each waypoint around the partner, then to the stop on its back.

        Returns the last pass, with iterations and initial error covering all
        of them. None when the wrap geometry is unknown (the caller falls
        back to a direct reach).
        """
        geometry = self._contact_geometry(resolved, bases)
        if geometry is None or not geometry.waypoints:
            return None
        passes = [
            align_single_limb_target(skeleton, profile, replace(resolved, target_point=point), **solve)
            for point in (*geometry.waypoints, geometry.stop)
        ]
        final = passes[-1]
        diagnostics = dict(final.diagnostics)
        diagnostics.update(
            wrap_waypoints=[list(point) for point in geometry.waypoints],
            waypoint_errors=[p.final_error for p in passes[:-1]],
        )
        if geometry.finger_point is not None:
            diagnostics.update(self._aim_wrap_hand(skeleton, profile, resolved.bone_name, geometry.finger_point, solve))
        return replace(
            final,
            iterations=sum(p.iterations for p in passes),
            initial_error=passes[0].initial_error,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _aim_wrap_hand(
        skeleton: Any, profile: FigureRigProfile, hand_bone: str, finger_point: Vector3, solve: dict[str, Any]
    ) -> dict[str, object]:
        """Turn the wrapped hand (its bone alone) so its fingertips lie across the partner's back.

        The wrist stays put. Each axis is held within ``WRAP_HAND_LIMIT`` of
        rest. Returns diagnostics; empty when the hand has no finger bones or
        the skeleton has no batch Jacobian.
        """
        tip = _farthest_descendant(profile, hand_bone)
        if tip is None or not hasattr(skeleton, "evaluate_pose_jacobian"):
            return {}
        aim = ResolvedInteractionTarget(figure_label=profile.figure_label, anchor_name=hand_bone, bone_name=tip, target_point=finger_point)
        result = _align_single_limb_batch(
            skeleton, profile, [hand_bone], aim,
            max_iterations=40, step_degrees=solve["step_degrees"], damping=solve["damping"], tolerance=1.0,
        )
        rotation = result.applied_rotations.get(hand_bone)
        if rotation is None:
            return {"hand_aim": "no_rotation"}
        clamped = tuple(max(-WRAP_HAND_LIMIT, min(WRAP_HAND_LIMIT, value)) for value in rotation)
        if clamped != tuple(rotation):
            skeleton.set_bone_rotations({hand_bone: clamped})
        return {"hand_aim_bone": tip, "hand_aim_rotation": list(clamped), "hand_aim_clamped": clamped != tuple(rotation)}

    def _stage_faced_partner(
        self,
        anchor_profile: FigureRigProfile,
        partner_profile: FigureRigProfile,
        anchor_base: Vector3,
        forward: Vector3,
    ) -> tuple[Vector3, list[ResolvedInteractionTarget]] | None:
        """Partner origin straight in front of the anchor, and the targets between them.

        The separation is the shortest any limb between them comfortably
        reaches, but at least ``FACING_MIN_SEPARATION``. None when no target
        between them has known geometry.
        """
        assert partner_profile.figure_position is not None
        partner_y = partner_profile.figure_position[1]

        def _partner_base(d: float) -> Vector3:
            return (anchor_base[0] + forward[0] * d, partner_y, anchor_base[2] + forward[2] * d)

        def _bases_at(d: float) -> dict[int, Vector3]:
            return {id(anchor_profile): anchor_base, id(partner_profile): _partner_base(d)}

        pairs = ((anchor_profile, partner_profile), (partner_profile, anchor_profile))
        between = [
            target
            for target in self.resolved_targets
            if target.target_anchor is not None
            and any(
                _lookup_rig_profile(self.rig_profiles, target.figure_label) is source
                and _lookup_rig_profile(self.rig_profiles, target.target_figure) is dest
                for source, dest in pairs
            )
        ]
        separations: list[float] = []
        for target in between:
            separation = self._faced_separation(target, _bases_at)
            if separation is not None:
                # A wrap sets its own (embrace) distance; reaches keep two torsos apart.
                separations.append(separation if target.wrap else max(FACING_MIN_SEPARATION, separation))
        if not separations:
            return None
        return _partner_base(min(separations)), between

    def _mutual_target(self, target: ResolvedInteractionTarget) -> ResolvedInteractionTarget | None:
        """The reverse of a hand/foot-to-hand/foot target (B's hand -> A's hand for A's hand -> B's hand), if any."""
        if target.target_figure is None or target.target_anchor is None:
            return None
        source = _lookup_rig_profile(self.rig_profiles, target.figure_label)
        partner = _lookup_rig_profile(self.rig_profiles, target.target_figure)
        if source is None or partner is None or source is partner:
            return None
        for other in self.resolved_targets:
            if (
                other is not target
                and other.anchor_name == target.target_anchor
                and other.target_anchor == target.anchor_name
                and _lookup_rig_profile(self.rig_profiles, other.figure_label) is partner
                and _lookup_rig_profile(self.rig_profiles, other.target_figure) is source
            ):
                return other
        return None

    def _staged_bases(self, figure_displacements: dict[str, Vector3] | None) -> dict[int, Vector3]:
        """Figure origins after staging (profile id -> position plus displacement)."""
        bases: dict[int, Vector3] = {}
        for profile in self.rig_profiles.values():
            if profile.figure_position is None or id(profile) in bases:
                continue
            shift = _displacement_for_profile(self.rig_profiles, profile, figure_displacements)
            bases[id(profile)] = _vec3_add(profile.figure_position, shift) if shift is not None else profile.figure_position
        return bases

    def _contact_geometry(self, target: ResolvedInteractionTarget, bases: dict[int, Vector3]) -> _ContactGeometry | None:
        """Where ``target``'s effector should stop with the figure origins at ``bases`` (keyed by profile id).

        The target joint pulled back toward the source limb root by the surface
        standoff; for a mutual hand-to-hand pair the joint is the meeting point
        between both shoulders. ``root`` is the reach root (shoulder/hip joint)
        and ``limb_length`` its reach. None when the geometry is unknown.
        """
        source = _lookup_rig_profile(self.rig_profiles, target.figure_label)
        partner = _lookup_rig_profile(self.rig_profiles, target.target_figure)
        if source is None or partner is None or target.target_anchor is None:
            return None
        limb = _limb_geometry(source, target.bone_name, bases.get(id(source), source.figure_position))
        if limb is None:
            return None
        chain_root, root, length = limb
        partner_base = bases.get(id(partner), partner.figure_position)
        if target.wrap:
            path = _wrap_path(partner, partner_base, target.target_anchor)
            if path is None:
                return None
            waypoints, back, fingers = path
            return _ContactGeometry(root=root, joint=back, stop=back, limb_length=length, waypoints=tuple(waypoints), finger_point=fingers)
        joint: Vector3 | None = None
        mutual = self._mutual_target(target)
        if mutual is not None:
            other = _limb_geometry(partner, mutual.bone_name, partner_base)
            if other is not None:
                joint = _meeting_point(root, length, other[1], other[2])
        else:
            offset = _anchor_bone_offset(partner, target.target_anchor)
            if offset is not None and partner_base is not None:
                joint = _vec3_add(_vec3_add(partner_base, offset), target.offset)
        if joint is None:
            return None
        return _ContactGeometry(root=root, joint=joint, stop=_pull_toward_root(joint, chain_root, target.surface_standoff), limb_length=length)

    def _faced_separation(
        self, target: ResolvedInteractionTarget, bases_at: Callable[[float], dict[int, Vector3]]
    ) -> float | None:
        """How far in front of its anchor a faced partner can stand (origin to origin, cm).

        The separation at which ``target``'s limb reaches its stop point at
        ``FACING_REACH_FRACTION`` (``FACING_FOOT_REACH_FRACTION`` for a leg) of
        its reach; ``bases_at(d)`` places the figures for separation ``d``.
        Never closer than ``FACING_MIN_SEPARATION``.
        """
        if target.wrap:
            # Reach doesn't bound a wrap: its arm must get its elbow beside the
            # partner's ribs, which only an embrace distance allows.
            return WRAP_SEPARATION
        profile = _lookup_rig_profile(self.rig_profiles, target.figure_label)
        chain = profile.suggest_primary_chain(target.bone_name) if profile is not None else None
        fraction = FACING_FOOT_REACH_FRACTION if chain is not None and chain.role in ("foot", "leg") else FACING_REACH_FRACTION

        def _gap(d: float) -> tuple[float, float] | None:
            geometry = self._contact_geometry(target, bases_at(d))
            if geometry is None:
                return None
            return _vec3_length(_vec3_sub(geometry.stop, geometry.root)), geometry.limb_length * fraction

        low, high = FACING_MIN_SEPARATION, _FACING_MAX_SEPARATION
        at_low = _gap(low)
        if at_low is None:
            return None
        if at_low[0] >= at_low[1]:
            return low
        at_high = _gap(high)
        assert at_high is not None
        if at_high[0] <= at_high[1]:
            return high
        for _ in range(40):
            mid = (low + high) / 2.0
            at_mid = _gap(mid)
            assert at_mid is not None
            if at_mid[0] <= at_mid[1]:
                low = mid
            else:
                high = mid
        return low


@dataclass
class InteractionPosePatch:
    """A coarse figure-placement patch built from a prepared interaction.

    Figure translations, plus yaw turns (degrees added to a figure's Y
    rotation) for figures staged to face a partner.
    """

    figure_positions: dict[str, Vector3] = field(default_factory=dict)
    unresolved_targets: list[ResolvedInteractionTarget] = field(default_factory=list)
    diagnostics: dict[str, object] = field(default_factory=dict)
    figure_yaw_degrees: dict[str, float] = field(default_factory=dict)

    def apply(self, scene: Any) -> None:
        for figure_label, yaw in self.figure_yaw_degrees.items():
            if abs(yaw) < 1e-6:
                continue
            skeleton = scene.find_skeleton_by_label(figure_label)
            if not hasattr(skeleton, "local_euler") or not hasattr(skeleton, "set_rotation"):
                raise TypeError(f"Cannot turn {figure_label} to face its partner: skeleton has no local_euler/set_rotation")
            x, y, z = skeleton.local_euler or (0.0, 0.0, 0.0)  # a property on DazNode
            skeleton.set_rotation(x, y + yaw, z)
        for figure_label, position in self.figure_positions.items():
            skeleton = scene.find_skeleton_by_label(figure_label)
            skeleton.set_position(*position)

    def to_dict(self) -> dict:
        return {
            "figure_positions": {label: list(position) for label, position in self.figure_positions.items()},
            "figure_yaw_degrees": dict(self.figure_yaw_degrees),
            "unresolved_targets": [target.to_dict() for target in self.unresolved_targets],
            "diagnostics": dict(self.diagnostics),
        }


@dataclass
class PreparedInteractionResult:
    """The result of applying a prepared recipe as a live staging pass."""

    prepared: PreparedInteractionRecipe
    pose_patch: InteractionPosePatch
    alignment_results: list[LimbAlignmentResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "prepared": self.prepared.to_dict(),
            "pose_patch": self.pose_patch.to_dict(),
            "alignment_results": [result.to_dict() for result in self.alignment_results],
        }


def prepare_interaction_recipe(
    recipe: InteractionRecipe,
    rig_profiles: dict[str, FigureRigProfile],
) -> PreparedInteractionRecipe:
    """Compile a recipe into a validated, resolved planning object.

    This is the next step toward a live-facing interaction system: it doesn't
    solve the pose yet, but it does normalize the recipe into concrete targets
    that a DAZ session or future solver can consume directly.
    """

    plan = recipe.to_plan()
    # Turned partners' profiles replace the originals before resolution.
    facing = plan_facing(plan, rig_profiles)
    profiles = _apply_facing(rig_profiles, facing)
    validation_issues = plan.validate(profiles)
    resolved_targets = plan.resolve_targets(profiles)
    diagnostics: dict[str, object] = {
        "recipe_kind": recipe.kind,
        "actor_count": len(recipe.actors),
        "constraint_count": len(recipe.constraints),
        "resolved_target_count": len(resolved_targets),
        "faced_figure_count": len(facing),
    }
    return PreparedInteractionRecipe(
        recipe=recipe,
        plan=plan,
        resolved_targets=resolved_targets,
        rig_profiles=profiles,
        validation_issues=validation_issues,
        diagnostics=diagnostics,
        facing=facing,
    )


def apply_interaction_recipe_to_scene(
    scene: object,
    recipe: InteractionRecipe,
    *,
    rig_profiles: dict[str, FigureRigProfile] | None = None,
    align_limb_targets: bool = False,
    max_iterations: int | None = None,
    step_degrees: float = 1.0,
    damping: float = 0.25,
    tolerance: float = 0.15,
) -> PreparedInteractionResult:
    """Prepare and apply an interaction recipe against a live scene object."""

    if rig_profiles is None:
        if not hasattr(scene, "skeletons"):
            raise TypeError("apply_interaction_recipe_to_scene expects a scene-like object")
        if hasattr(scene, "scene_snapshot") and hasattr(scene, "_client"):
            rig_profiles = build_rig_profiles_from_snapshot(scene.scene_snapshot())
        else:
            rig_profiles = {}
            for skeleton in scene.skeletons():
                profile = build_rig_profile(skeleton)
                rig_profiles[profile.figure_label] = profile
                if skeleton._identifier.value and skeleton._identifier.value != profile.figure_label:
                    rig_profiles[skeleton._identifier.value] = profile
    prepared = prepare_interaction_recipe(recipe, rig_profiles)
    return prepared.apply(
        scene,
        align_limb_targets=align_limb_targets,
        max_iterations=max_iterations,
        step_degrees=step_degrees,
        damping=damping,
        tolerance=tolerance,
    )


def _target_anchor_from_strike_anchor(anchor_name: str) -> str:
    lowered = _normalize_name(anchor_name)
    if "hand" in lowered:
        return "l_shoulder"
    if "foot" in lowered:
        return "l_hip"
    return "chest"


def build_sit_recipe(
    actor_label: str,
    *,
    seat_point: Vector3 | None = None,
    support_points: list[Vector3] | None = None,
    foot_anchors: tuple[str, str] = ("l_foot", "r_foot"),
) -> InteractionRecipe:
    """Build a seat/lean preset for a single character."""

    constraints: list[PoseTarget | ContactTarget | LookAtTarget | BalanceTarget | HandTarget | FootTarget] = [
        BalanceTarget(
            figure_label=actor_label,
            pelvis_bone="pelvis",
            support_points=list(support_points or ([] if seat_point is None else [seat_point])),
            center_of_mass_hint=seat_point,
        )
    ]
    for index, anchor_name in enumerate(foot_anchors):
        target_point = None
        if support_points:
            target_point = support_points[min(index, len(support_points) - 1)]
        elif seat_point is not None:
            target_point = seat_point
        constraints.append(
            FootTarget(
                figure_label=actor_label,
                anchor_name=anchor_name,
                target_point=target_point,
            )
        )
    return InteractionRecipe(
        kind="sit",
        actors=[actor_label],
        constraints=constraints,
        metadata={"seat_point": list(seat_point) if seat_point else None},
    )


def build_touch_recipe(
    source_label: str,
    target_label: str,
    *,
    source_anchor: str = "r_hand",
    target_anchor: str = "l_shoulder",
    target_point: Vector3 | None = None,
) -> InteractionRecipe:
    """Build a touch/contact preset between two figures."""

    return InteractionRecipe(
        kind="touch",
        actors=[source_label, target_label],
        constraints=[
            HandTarget(
                figure_label=source_label,
                anchor_name=source_anchor,
                target_figure=target_label,
                target_anchor=target_anchor,
                target_point=target_point,
            )
        ],
        metadata={
            "source_anchor": source_anchor,
            "target_anchor": target_anchor,
        },
    )


def build_kiss_recipe(
    actor_a: str,
    actor_b: str,
    *,
    a_anchor: str = "r_hand",
    b_anchor: str = "l_shoulder",
) -> InteractionRecipe:
    """Build a face-to-face interaction preset with a stabilizing contact plan."""

    b_anchor = "l_shoulder" if _side_from_name(a_anchor) == "right" else "r_shoulder"
    return InteractionRecipe(
        kind="kiss",
        actors=[actor_a, actor_b],
        constraints=[
            LookAtTarget(actor_a, "head", (0.0, 0.0, 0.0)),
            LookAtTarget(actor_b, "head", (0.0, 0.0, 0.0)),
            HandTarget(actor_a, a_anchor, target_figure=actor_b, target_anchor=b_anchor),
            # B's mirrored hand on A's opposite shoulder: straight ahead once they face each other.
            HandTarget(actor_b, "l_hand" if _side_from_name(a_anchor) == "right" else "r_hand", target_figure=actor_a, target_anchor="r_shoulder" if _side_from_name(a_anchor) == "right" else "l_shoulder"),
        ],
        metadata={"interaction": "kiss"},
    )


def build_handshake_recipe(
    actor_a: str,
    actor_b: str,
    *,
    a_anchor: str = "r_hand",
    b_anchor: str = "r_hand",
) -> InteractionRecipe:
    """Build a mirrored hand-to-hand greeting preset for two figures."""

    return InteractionRecipe(
        kind="handshake",
        actors=[actor_a, actor_b],
        constraints=[
            LookAtTarget(actor_a, "head", (0.0, 0.0, 0.0)),
            LookAtTarget(actor_b, "head", (0.0, 0.0, 0.0)),
            HandTarget(actor_a, a_anchor, target_figure=actor_b, target_anchor=b_anchor),
            HandTarget(actor_b, b_anchor, target_figure=actor_a, target_anchor=a_anchor),
        ],
        metadata={"interaction": "handshake"},
    )


def build_hug_recipe(
    actor_a: str,
    actor_b: str,
    *,
    a_anchor: str = "r_hand",
    b_anchor: str = "r_hand",
) -> InteractionRecipe:
    """Build a mutual arms-around-each-other embrace preset for two figures.

    Each arm wraps the partner's side (toward its far shoulder) and the hand
    rests on its upper back (``HandTarget.wrap``).
    """

    a_far_shoulder = "l_shoulder" if _side_from_name(a_anchor) == "right" else "r_shoulder"
    b_far_shoulder = "l_shoulder" if _side_from_name(b_anchor) == "right" else "r_shoulder"
    return InteractionRecipe(
        kind="hug",
        actors=[actor_a, actor_b],
        constraints=[
            LookAtTarget(actor_a, "head", (0.0, 0.0, 0.0)),
            LookAtTarget(actor_b, "head", (0.0, 0.0, 0.0)),
            HandTarget(actor_a, a_anchor, target_figure=actor_b, target_anchor=a_far_shoulder, wrap=True),
            HandTarget(actor_b, b_anchor, target_figure=actor_a, target_anchor=b_far_shoulder, wrap=True),
        ],
        metadata={"interaction": "hug"},
    )


def build_face_each_other_recipe(actor_a: str, actor_b: str) -> InteractionRecipe:
    """Build a mutual eye-contact preset for two figures, with no limb contact."""

    return InteractionRecipe(
        kind="face_each_other",
        actors=[actor_a, actor_b],
        constraints=[
            LookAtTarget(actor_a, "head", (0.0, 0.0, 0.0)),
            LookAtTarget(actor_b, "head", (0.0, 0.0, 0.0)),
        ],
        metadata={"interaction": "face_each_other"},
    )


def build_fight_recipe(
    attacker: str,
    defender: str,
    *,
    strike_anchor: str = "r_hand",
    target_anchor: str = "head",
) -> InteractionRecipe:
    """Build a simple strike/contact preset for fight choreography."""

    strike_target = _target_anchor_from_strike_anchor(strike_anchor)
    strike_constraint: PoseTarget | ContactTarget | LookAtTarget | BalanceTarget | HandTarget | FootTarget
    if "foot" in _normalize_name(strike_anchor):
        strike_constraint = FootTarget(
            figure_label=attacker,
            anchor_name=strike_anchor,
            target_figure=defender,
            target_anchor=target_anchor,
        )
    else:
        strike_constraint = HandTarget(
            figure_label=attacker,
            anchor_name=strike_anchor,
            target_figure=defender,
            target_anchor=target_anchor,
        )
    return InteractionRecipe(
        kind="fight",
        actors=[attacker, defender],
        constraints=[
            strike_constraint,
            LookAtTarget(attacker, "head", (0.0, 0.0, 0.0)),
            LookAtTarget(defender, "head", (0.0, 0.0, 0.0)),
        ],
        metadata={
            "strike_anchor": strike_anchor,
            "target_anchor": target_anchor,
            "strike_target": strike_target,
        },
    )
