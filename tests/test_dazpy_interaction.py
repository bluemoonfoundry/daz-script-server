"""dazpy unit tests: interaction recipes, rig profiles and the limb solver.

Mock-based; no server or DAZ Studio required.
Shared fakes live in tests/dazpy_fakes.py.
"""

import math
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dazpy import (
    ANCHOR_SURFACE_RADIUS,
    EFFECTOR_REACH_FALLBACK,
    AxisLimit,
    BalanceTarget,
    BoneProfile,
    FigureRigProfile,
    FootTarget,
    InteractionPlan,
    InteractionRecipe,
    InteractionPosePatch,
    LimbAlignmentResult,
    PreparedInteractionRecipe,
    PreparedInteractionResult,
    HandTarget,
    LookAtTarget,
    PoseTarget,
    build_fight_recipe,
    build_face_each_other_recipe,
    build_handshake_recipe,
    build_hug_recipe,
    build_kiss_recipe,
    build_sit_recipe,
    build_touch_recipe,
    prepare_interaction_recipe,
    SolveOptions,
    ValidationIssue,
    build_rig_profile,
    build_rig_profiles_from_snapshot,
    align_hand_target,
    default_axis_limits_for_bone,
    resolve_interaction_target,
)
from dazpy._scene import DazScene
from dazpy_fakes import (FakeRigBone, FakeRigScene, FakeRigSkeleton, KinematicFakeBone,
    KinematicFakeSkeleton)


class TestInteractionAdapter(unittest.TestCase):
    def test_build_rig_profile_detects_family_and_anchors(self):
        hip = FakeRigBone("hip", "Hip")
        spine = FakeRigBone("spine", "Spine", parent=hip)
        chest = FakeRigBone("chest", "Chest", parent=spine)
        neck = FakeRigBone("neck", "Neck", parent=chest)
        head = FakeRigBone("head", "Head", parent=neck)
        l_hand = FakeRigBone("l_hand", "Left Hand", parent=chest)
        r_hand = FakeRigBone("r_hand", "Right Hand", parent=chest)
        l_foot = FakeRigBone("l_foot", "Left Foot", parent=hip)
        r_foot = FakeRigBone("r_foot", "Right Foot", parent=hip)
        skeleton = FakeRigSkeleton("Genesis 9", [hip, spine, chest, neck, head, l_hand, r_hand, l_foot, r_foot])

        profile = build_rig_profile(skeleton)
        anchors = profile.anchor_map()

        self.assertEqual(profile.family, "genesis_9")
        self.assertIn("l_hand", anchors)
        self.assertIn("r_hand", anchors)
        self.assertIn("l_foot", anchors)
        self.assertEqual(profile.anchor("r_hand").bone_name, "r_hand")
        self.assertEqual(profile.anchor("l_foot").role, "foot")

    def test_build_rig_profile_genesis_8_camel_case_anchors(self):
        """Genesis 8/3 camelCase bone names (rHand, lFoot) resolve via canonical r_hand/l_foot anchors."""
        hip = FakeRigBone("hip", "Hip")
        spine = FakeRigBone("abdomenLower", "Abdomen Lower", parent=hip)
        chest = FakeRigBone("chestLower", "Chest Lower", parent=spine)
        lCollar = FakeRigBone("lCollar", "Left Collar", parent=chest)
        rCollar = FakeRigBone("rCollar", "Right Collar", parent=chest)
        lForearmBend = FakeRigBone("lForearmBend", "Left Forearm Bend", parent=lCollar)
        rForearmBend = FakeRigBone("rForearmBend", "Right Forearm Bend", parent=rCollar)
        lHand = FakeRigBone("lHand", "Left Hand", parent=lForearmBend)
        rHand = FakeRigBone("rHand", "Right Hand", parent=rForearmBend)
        lFoot = FakeRigBone("lFoot", "Left Foot", parent=hip)
        rFoot = FakeRigBone("rFoot", "Right Foot", parent=hip)
        skeleton = FakeRigSkeleton(
            "Bob Genesis 8",
            [hip, spine, chest, lCollar, rCollar, lForearmBend, rForearmBend, lHand, rHand, lFoot, rFoot],
        )

        profile = build_rig_profile(skeleton)
        anchors = profile.anchor_map()

        self.assertEqual(profile.family, "genesis_3_8")
        self.assertIn("r_hand", anchors, "r_hand anchor must resolve for camelCase rHand bone")
        self.assertIn("l_hand", anchors, "l_hand anchor must resolve for camelCase lHand bone")
        self.assertIn("r_foot", anchors)
        self.assertIn("l_foot", anchors)
        self.assertEqual(profile.anchor("r_hand").bone_name, "rHand")
        self.assertEqual(profile.anchor("l_foot").bone_name, "lFoot")

    @staticmethod
    def _chain_profile(label, family, names):
        bones = [BoneProfile(name=names[0])]
        bones += [BoneProfile(name=name, parent_name=names[0]) for name in names[1:]]
        return FigureRigProfile(figure_label=label, family=family, bones=bones)

    def test_chest_and_hip_anchors_resolve_on_genesis_9_and_8(self):
        # lb1i: G9 has no chest-named bone (spine3/spine4) and nothing mapped to the hip joints.
        g9 = self._chain_profile("G9", "genesis_9", [
            "hip", "pelvis", "spine1", "spine2", "spine3", "spine4", "neck1", "head", "l_shoulder", "l_upperarm",
            "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot",
        ])
        g8 = self._chain_profile("G8", "genesis_3_8", [
            "hip", "pelvis", "abdomenLower", "abdomenUpper", "chestLower", "chestUpper", "neckLower", "head", "lCollar", "lShldrBend",
            "lThighBend", "lThighTwist", "lShin", "lFoot", "rThighBend", "rThighTwist", "rShin", "rFoot",
        ])
        expected = [
            (g9, {"chest": "spine3", "l_hip": "l_thigh", "r_hip": "r_thigh", "l_knee": "l_shin"}),
            (g8, {"chest": "chestLower", "l_hip": "lThighBend", "r_hip": "rThighBend", "l_knee": "lShin"}),
        ]
        for profile, anchors in expected:
            for anchor, bone in anchors.items():
                with self.subTest(figure=profile.figure_label, anchor=anchor):
                    self.assertEqual(profile.anchor(anchor).bone_name, bone)
            self.assertEqual(profile.anchor("l_hip").role, "hip")
            for strike in ("r_hand", "r_foot", "head"):
                target = build_fight_recipe("A", "B", strike_anchor=strike).metadata["strike_target"]
                with self.subTest(figure=profile.figure_label, strike=strike):
                    self.assertIsNotNone(profile.anchor(target))

    def test_looks_like_helper_ignores_bend_bones(self):
        """'end' is a whole token, not a substring: G3/G8 *Bend bones are real joints (i9b6)."""
        from dazpy._interaction_profile import _looks_like_helper

        for name, label in (
            ("lForearmBend", "Left Forearm Bend"),
            ("rShldrBend", "Right Shoulder Bend"),
            ("lThighBend", "Left Thigh Bend"),
        ):
            self.assertFalse(_looks_like_helper(name, label), name)
        for name, label in (
            ("lEyeEnd", None),
            ("hand_end", None),
            ("tip", "End Point"),
            ("Endpoint", None),
            ("hipHelper", None),
        ):
            self.assertTrue(_looks_like_helper(name, label), name)

    def test_build_rig_profile_genesis_8_shoulder_and_bend_chain(self):
        """G8 lShldrBend is the shoulder anchor/arm chain, and Bend bones stay in the alignment chain (i9b6)."""
        from dazpy._interaction_profile import _alignment_chain_names

        hip = FakeRigBone("hip", "Hip")
        chest = FakeRigBone("chestUpper", "Chest Upper", parent=hip)
        bones = [hip, chest]
        for side, word in (("l", "Left"), ("r", "Right")):
            collar = FakeRigBone(f"{side}Collar", f"{word} Collar", parent=chest)
            shldr_bend = FakeRigBone(f"{side}ShldrBend", f"{word} Shoulder Bend", parent=collar)
            shldr_twist = FakeRigBone(f"{side}ShldrTwist", f"{word} Shoulder Twist", parent=shldr_bend)
            fore_bend = FakeRigBone(f"{side}ForearmBend", f"{word} Forearm Bend", parent=shldr_twist)
            fore_twist = FakeRigBone(f"{side}ForearmTwist", f"{word} Forearm Twist", parent=fore_bend)
            hand = FakeRigBone(f"{side}Hand", f"{word} Hand", parent=fore_twist)
            bones += [collar, shldr_bend, shldr_twist, fore_bend, fore_twist, hand]
        profile = build_rig_profile(FakeRigSkeleton("Bob Genesis 8", bones))

        self.assertFalse(profile.bone("lForearmBend").is_helper)
        self.assertEqual(profile.anchor("l_shoulder").bone_name, "lShldrBend")
        self.assertEqual(profile.anchor("r_shoulder").bone_name, "rShldrBend")
        arm_chains = [c for c in profile.chain_suggestions() if c.role == "arm"]
        self.assertEqual(sorted(c.effector_bone for c in arm_chains), ["lShldrBend", "rShldrBend"])
        self.assertEqual(profile.suggest_primary_chain("lShldrBend").role, "arm")
        self.assertTrue(default_axis_limits_for_bone("lShldrBend"))

        hand_chain = profile.suggest_primary_chain("lHand")
        self.assertEqual(
            _alignment_chain_names(profile, hand_chain),
            ["lShldrBend", "lShldrTwist", "lForearmBend", "lForearmTwist"],
        )

    def test_interaction_plan_validate_and_round_trip(self):
        profile = FigureRigProfile(
            figure_label="Genesis 9",
            family="genesis_9",
            bones=[
                BoneProfile(name="hip"),
                BoneProfile(name="r_hand", parent_name="hip"),
                BoneProfile(name="l_foot", parent_name="hip"),
                BoneProfile(name="head", parent_name="hip"),
            ],
        )
        plan = InteractionPlan(
            actors=["Genesis 9"],
            constraints=[
                PoseTarget("Genesis 9", "r_hand", orientation=(0.0, 0.0, 0.0)),
                LookAtTarget("Genesis 9", "head", (0.0, 1.0, 2.0)),
                BalanceTarget("Genesis 9", "hip", support_points=[(0.0, 0.0, 0.0)]),
                HandTarget("Genesis 9", "r_hand", target_point=(1.0, 2.0, 3.0), offset=(0.0, 0.0, 0.0)),
                FootTarget("Genesis 9", "l_foot", target_figure="Genesis 9", target_anchor="r_hand"),
            ],
            options=SolveOptions(backend="auto", max_iterations=25),
            metadata={"scenario": "touch"},
        )

        data = plan.to_dict()
        restored = InteractionPlan.from_dict(data)
        issues = restored.validate({"Genesis 9": profile})

        self.assertEqual(data["options"]["backend"], "auto")
        self.assertEqual(len(data["constraints"]), 5)
        self.assertEqual(issues, [])

    def test_interaction_plan_accepts_compact_figure_aliases(self):
        profile = FigureRigProfile(
            figure_label="Genesis 9",
            family="genesis_9",
            bones=[
                BoneProfile(name="hip"),
                BoneProfile(name="r_hand", parent_name="hip"),
            ],
        )
        recipe = InteractionRecipe(
            kind="custom",
            actors=["Genesis 9"],
            constraints=[HandTarget("Genesis 9", "r_hand", target_point=(1.0, 2.0, 3.0))],
        )

        prepared = prepare_interaction_recipe(recipe, {"Genesis9": profile})

        self.assertTrue(prepared.is_valid)
        self.assertEqual(prepared.rig_profiles["Genesis9"].figure_label, "Genesis 9")
        self.assertEqual(prepared.diagnostics["resolved_target_count"], 1)

    def test_interaction_plan_validate_reports_missing_bone(self):
        profile = FigureRigProfile(
            figure_label="Genesis 9",
            family="genesis_9",
            bones=[BoneProfile(name="hip")],
        )
        plan = InteractionPlan(
            actors=["Genesis 9"],
            constraints=[PoseTarget("Genesis 9", "r_hand", orientation=(0.0, 0.0, 0.0))],
        )

        issues = plan.validate({"Genesis 9": profile})
        self.assertEqual(len(issues), 1)
        self.assertIsInstance(issues[0], ValidationIssue)
        self.assertEqual(issues[0].severity, "error")
        self.assertIn("r_hand", issues[0].message)

    def test_hand_and_foot_targets_round_trip(self):
        hand = HandTarget("Genesis 9", "r_hand", target_point=(1.0, 2.0, 3.0), offset=(0.1, 0.0, 0.0))
        foot = FootTarget("Genesis 9", "l_foot", target_figure="Partner", target_anchor="r_hand")

        hand_data = hand.to_dict()
        foot_data = foot.to_dict()
        hand_restored = HandTarget(
            figure_label=hand_data["figure_label"],
            anchor_name=hand_data["anchor_name"],
            target_figure=hand_data.get("target_figure"),
            target_anchor=hand_data.get("target_anchor"),
            target_point=tuple(hand_data["target_point"]) if hand_data.get("target_point") else None,
            offset=tuple(hand_data["offset"]),
        )
        foot_restored = FootTarget(
            figure_label=foot_data["figure_label"],
            anchor_name=foot_data["anchor_name"],
            target_figure=foot_data.get("target_figure"),
            target_anchor=foot_data.get("target_anchor"),
            target_point=tuple(foot_data["target_point"]) if foot_data.get("target_point") else None,
            offset=tuple(foot_data["offset"]),
        )

        self.assertEqual(hand_restored.anchor_name, "r_hand")
        self.assertEqual(hand_restored.offset, (0.1, 0.0, 0.0))
        self.assertEqual(foot_restored.target_anchor, "r_hand")

    def test_resolve_interaction_target_same_figure(self):
        hip = FakeRigBone("hip", "Hip")
        hand = FakeRigBone("r_hand", "Right Hand", parent=hip, local_position=(10.0, 20.0, 30.0))
        foot = FakeRigBone("l_foot", "Left Foot", parent=hip, local_position=(1.0, 2.0, 3.0))
        profile = build_rig_profile(FakeRigSkeleton("Genesis 9", [hip, hand, foot]))

        resolved = resolve_interaction_target(
            HandTarget("Genesis 9", "r_hand", target_point=(1.0, 2.0, 3.0), offset=(0.5, 0.0, -0.5)),
            {"Genesis 9": profile},
        )

        self.assertEqual(resolved.bone_name, "r_hand")
        self.assertEqual(resolved.target_point, (1.5, 2.0, 2.5))
        self.assertIsNone(resolved.target_bone)

    def test_resolve_interaction_target_cross_figure(self):
        source_hip = FakeRigBone("hip", "Hip")
        source_hand = FakeRigBone("r_hand", "Right Hand", parent=source_hip)
        source_profile = build_rig_profile(FakeRigSkeleton("Genesis 9", [source_hip, source_hand]))

        target_hip = FakeRigBone("hip", "Hip")
        target_hand = FakeRigBone("r_hand", "Right Hand", parent=target_hip, local_position=(4.0, 5.0, 6.0))
        target_profile = build_rig_profile(FakeRigSkeleton("Partner", [target_hip, target_hand]))

        resolved = resolve_interaction_target(
            FootTarget("Genesis 9", "r_hand", target_figure="Partner", target_anchor="r_hand"),
            {"Genesis 9": source_profile, "Partner": target_profile},
        )

        self.assertEqual(resolved.target_figure, "Partner")
        self.assertEqual(resolved.target_anchor, "r_hand")
        self.assertEqual(resolved.target_bone, "r_hand")
        self.assertEqual(resolved.target_point, (4.0, 5.0, 6.0))

    def test_resolve_interaction_target_without_point_stays_unresolved(self):
        # i4yf: the offset must not become the target point when nothing resolved one.
        hip = FakeRigBone("hip", "Hip")
        hand = FakeRigBone("r_hand", "Right Hand", parent=hip, local_position=(10.0, 20.0, 30.0))
        profile = build_rig_profile(FakeRigSkeleton("Genesis 9", [hip, hand]))
        profiles = {"Genesis 9": profile}

        no_point = resolve_interaction_target(HandTarget("Genesis 9", "r_hand", offset=(0.5, 0.0, 0.0)), profiles)
        unknown_figure = resolve_interaction_target(
            HandTarget("Genesis 9", "r_hand", target_figure="Nobody", target_anchor="r_hand"), profiles
        )

        self.assertIsNone(no_point.target_point)
        self.assertIsNone(unknown_figure.target_point)

    def test_pose_patch_lists_unknown_target_figure_as_unresolved(self):
        hip = FakeRigBone("hip", "Hip")
        hand = FakeRigBone("r_hand", "Right Hand", parent=hip, local_position=(10.0, 20.0, 30.0))
        profile = build_rig_profile(FakeRigSkeleton("Genesis 9", [hip, hand]))
        recipe = InteractionRecipe(
            kind="touch",
            actors=["Genesis 9", "Nobody"],
            constraints=[HandTarget("Genesis 9", "r_hand", target_figure="Nobody", target_anchor="r_hand")],
        )

        patch = prepare_interaction_recipe(recipe, {"Genesis 9": profile}).build_pose_patch()

        self.assertEqual(patch.figure_positions, {})
        self.assertEqual(len(patch.unresolved_targets), 1)

    def test_interaction_recipe_round_trip(self):
        recipe = InteractionRecipe(
            kind="touch",
            actors=["Genesis 9", "Partner"],
            constraints=[
                HandTarget("Genesis 9", "r_hand", target_figure="Partner", target_anchor="l_shoulder"),
            ],
            metadata={"scenario": "contact"},
        )

        data = recipe.to_dict()
        restored = InteractionRecipe.from_dict(data)

        self.assertEqual(restored.kind, "touch")
        self.assertEqual(restored.actors, ["Genesis 9", "Partner"])
        self.assertEqual(len(restored.constraints), 1)
        self.assertIsInstance(restored.constraints[0], HandTarget)

    def test_interaction_recipe_builders(self):
        sit = build_sit_recipe("Genesis 9", seat_point=(0.0, 1.0, 2.0), support_points=[(1.0, 0.0, 0.0), (-1.0, 0.0, 0.0)])
        touch = build_touch_recipe("Genesis 9", "Partner")
        kiss = build_kiss_recipe("Genesis 9", "Partner")
        fight = build_fight_recipe("Genesis 9", "Partner", strike_anchor="r_foot", target_anchor="head")

        self.assertEqual(sit.kind, "sit")
        self.assertEqual(touch.kind, "touch")
        self.assertEqual(kiss.kind, "kiss")
        self.assertEqual(fight.kind, "fight")
        self.assertEqual(sit.to_plan().actors, ["Genesis 9"])
        self.assertTrue(any(isinstance(constraint, BalanceTarget) for constraint in sit.constraints))
        self.assertTrue(any(isinstance(constraint, HandTarget) for constraint in touch.constraints))
        self.assertTrue(sum(isinstance(constraint, LookAtTarget) for constraint in kiss.constraints) >= 2)
        self.assertTrue(any(isinstance(constraint, FootTarget) for constraint in fight.constraints))

    def test_handshake_recipe_builder(self):
        handshake = build_handshake_recipe("Genesis 9", "Partner")
        self.assertEqual(handshake.kind, "handshake")
        self.assertEqual(handshake.actors, ["Genesis 9", "Partner"])
        hand_targets = [c for c in handshake.constraints if isinstance(c, HandTarget)]
        self.assertEqual(len(hand_targets), 2)
        self.assertTrue(sum(isinstance(c, LookAtTarget) for c in handshake.constraints) >= 2)
        # Mirrored: each actor's hand targets the other actor's hand.
        a_target = next(c for c in hand_targets if c.figure_label == "Genesis 9")
        b_target = next(c for c in hand_targets if c.figure_label == "Partner")
        self.assertEqual(a_target.target_figure, "Partner")
        self.assertEqual(b_target.target_figure, "Genesis 9")

    def test_hug_recipe_builder(self):
        hug = build_hug_recipe("Genesis 9", "Partner")
        self.assertEqual(hug.kind, "hug")
        self.assertEqual(hug.actors, ["Genesis 9", "Partner"])
        hand_targets = [c for c in hug.constraints if isinstance(c, HandTarget)]
        self.assertEqual(len(hand_targets), 2)
        # Each actor's hand reaches for the *far* shoulder (arms wrap around).
        a_target = next(c for c in hand_targets if c.figure_label == "Genesis 9")
        self.assertEqual(a_target.target_anchor, "l_shoulder")

    def test_hug_recipe_builder_mismatched_anchors_crosses_correctly(self):
        # Regression: with a_anchor == b_anchor (both "r_hand"), a_far_shoulder
        # and b_far_shoulder happen to be identical, hiding a bug where the two
        # were swapped between actors. Mismatched anchors expose it: actor_a's
        # hand target must derive its far shoulder from actor_a's own anchor
        # side, not actor_b's.
        hug = build_hug_recipe(
            "Genesis 9", "Partner", a_anchor="r_hand", b_anchor="l_hand"
        )
        hand_targets = [c for c in hug.constraints if isinstance(c, HandTarget)]
        a_target = next(c for c in hand_targets if c.figure_label == "Genesis 9")
        b_target = next(c for c in hand_targets if c.figure_label == "Partner")
        # a_anchor="r_hand" (right side) -> far shoulder is the left one.
        self.assertEqual(a_target.target_anchor, "l_shoulder")
        # b_anchor="l_hand" (left side) -> far shoulder is the right one.
        self.assertEqual(b_target.target_anchor, "r_shoulder")

    def test_face_each_other_recipe_builder(self):
        face = build_face_each_other_recipe("Genesis 9", "Partner")
        self.assertEqual(face.kind, "face_each_other")
        self.assertEqual(face.actors, ["Genesis 9", "Partner"])
        self.assertEqual(len(face.constraints), 2)
        self.assertTrue(all(isinstance(c, LookAtTarget) for c in face.constraints))
        self.assertFalse(any(isinstance(c, HandTarget) for c in face.constraints))

    def test_prepare_interaction_recipe_compiles_targets(self):
        source_hip = FakeRigBone("hip", "Hip")
        source_hand = FakeRigBone("r_hand", "Right Hand", parent=source_hip, local_position=(1.0, 2.0, 3.0))
        target_hip = FakeRigBone("hip", "Hip")
        target_shoulder = FakeRigBone("l_shoulder", "Left Shoulder", parent=target_hip, local_position=(4.0, 5.0, 6.0))
        source_profile = build_rig_profile(FakeRigSkeleton("Genesis 9", [source_hip, source_hand]))
        target_profile = build_rig_profile(FakeRigSkeleton("Partner", [target_hip, target_shoulder]))

        recipe = build_touch_recipe("Genesis 9", "Partner", source_anchor="r_hand", target_anchor="l_shoulder")
        prepared = prepare_interaction_recipe(recipe, {"Genesis 9": source_profile, "Partner": target_profile})

        self.assertIsInstance(prepared, PreparedInteractionRecipe)
        self.assertTrue(prepared.is_valid)
        self.assertEqual(prepared.diagnostics["recipe_kind"], "touch")
        self.assertEqual(prepared.diagnostics["resolved_target_count"], 1)
        self.assertEqual(len(prepared.resolved_targets), 1)
        self.assertEqual(prepared.resolved_targets[0].bone_name, "r_hand")
        self.assertEqual(prepared.resolved_targets[0].target_bone, "l_shoulder")
        self.assertEqual(prepared.resolved_targets[0].target_point, (4.0, 5.0, 6.0))
        self.assertEqual(prepared.to_dict()["plan"]["actors"], ["Genesis 9", "Partner"])

    def test_prepared_recipe_apply_moves_figures(self):
        source_hip = FakeRigBone("hip", "Hip")
        source_hand = FakeRigBone("r_hand", "Right Hand", parent=source_hip, local_position=(1.0, 2.0, 3.0))
        target_hip = FakeRigBone("hip", "Hip")
        target_shoulder = FakeRigBone("l_shoulder", "Left Shoulder", parent=target_hip, local_position=(4.0, 5.0, 6.0))
        source_skel = FakeRigSkeleton("Genesis 9", [source_hip, source_hand])
        target_skel = FakeRigSkeleton("Partner", [target_hip, target_shoulder])
        scene = FakeRigScene([source_skel, target_skel])

        source_profile = build_rig_profile(source_skel)
        target_profile = build_rig_profile(target_skel)
        # Joint-to-joint staging (no surface standoff) keeps the numbers simple.
        recipe = InteractionRecipe(
            kind="touch",
            actors=["Genesis 9", "Partner"],
            constraints=[HandTarget("Genesis 9", "r_hand", target_figure="Partner", target_anchor="l_shoulder", surface_standoff=0.0)],
        )
        prepared = prepare_interaction_recipe(recipe, {"Genesis 9": source_profile, "Partner": target_profile})

        result = prepared.apply(scene)

        self.assertIsInstance(result, PreparedInteractionResult)
        self.assertIsInstance(result.pose_patch, InteractionPosePatch)
        # Hand/foot staging is floor-locked: X/Z only, height kept (0 when unknown).
        self.assertEqual(source_skel.position_calls, [(1.5, 0.0, 1.5)])
        self.assertEqual(target_skel.position_calls, [(-1.5, 0.0, -1.5)])
        self.assertEqual(result.pose_patch.diagnostics["figure_count"], 2)
        self.assertEqual(result.pose_patch.diagnostics["unresolved_target_count"], 0)
        self.assertEqual(result.to_dict()["pose_patch"]["figure_positions"]["Genesis 9"], [1.5, 0.0, 1.5])
        self.assertEqual(result.to_dict()["pose_patch"]["figure_positions"]["Partner"], [-1.5, 0.0, -1.5])

    # -- 6r3b: staging from live-shaped profiles --------------------------------
    # Live boneMetadata/scene_snapshot report local_position as the bone's
    # translation channel (zero on an unposed figure); offsets have to come
    # from world_position - figure_position.

    @staticmethod
    def _live_profile(label, figure_position, world_positions):
        hip_world = world_positions.pop("hip", (0.0, 0.0, 0.0))
        bones = [BoneProfile(name="hip", local_position=(0.0, 0.0, 0.0), world_position=hip_world)]
        for name, world in world_positions.items():
            bones.append(BoneProfile(name=name, parent_name="hip", local_position=(0.0, 0.0, 0.0), world_position=world))
        return FigureRigProfile(figure_label=label, family="genesis_9", bones=bones, figure_position=figure_position)

    def test_bone_offset_uses_world_minus_figure_position(self):
        profile = self._live_profile("A", (10.0, 0.0, 5.0), {"r_hand": (-41.0, 100.0, 7.0)})
        self.assertEqual(profile.bone_offset("r_hand"), (-51.0, 100.0, 2.0))
        hand_built = FigureRigProfile(figure_label="B", family="genesis_9", bones=[BoneProfile(name="r_hand", local_position=(1.0, 2.0, 3.0))])
        self.assertEqual(hand_built.bone_offset("r_hand"), (1.0, 2.0, 3.0))

    def test_figure_position_round_trips(self):
        profile = self._live_profile("A", (10.0, 0.0, 5.0), {"r_hand": (-41.0, 100.0, 7.0)})
        restored = FigureRigProfile.from_dict(profile.to_dict())
        self.assertEqual(restored.figure_position, (10.0, 0.0, 5.0))
        self.assertEqual(restored.bone_offset("r_hand"), (-51.0, 100.0, 2.0))

    def test_live_touch_staging_separates_figures_on_the_floor(self):
        # Both figures at the origin, as freshly loaded (the 6r3b live case).
        a = self._live_profile("A", (0.0, 0.0, 0.0), {"r_hand": (-51.5, 99.8, 2.3)})
        b = self._live_profile("B", (0.0, 0.0, 0.0), {"l_shoulder": (3.5, 135.5, -3.6)})
        recipe = InteractionRecipe(kind="touch", actors=["A", "B"], constraints=[HandTarget("A", "r_hand", target_figure="B", target_anchor="l_shoulder")])

        prepared = prepare_interaction_recipe(recipe, {"A": a, "B": b})
        patch = prepared.build_pose_patch()

        pa, pb = patch.figure_positions["A"], patch.figure_positions["B"]
        self.assertEqual((pa[1], pb[1]), (0.0, 0.0))
        # Horizontally, A's hand lands a surface standoff short of B's shoulder (kwpq), on A's side.
        hand = (pa[0] - 51.5, pa[2] + 2.3)
        shoulder = (pb[0] + 3.5, pb[2] - 3.6)
        self.assertAlmostEqual(math.dist(hand, shoulder), prepared.resolved_targets[0].surface_standoff)
        self.assertGreater(hand[0], shoulder[0])
        self.assertGreater(abs(pa[0] - pb[0]), 50.0)

    def test_floor_lock_keeps_each_figures_current_height(self):
        a = self._live_profile("A", (0.0, 12.0, 0.0), {"r_hand": (-51.5, 111.8, 2.3)})
        recipe = InteractionRecipe(kind="custom", actors=["A"], constraints=[HandTarget("A", "r_hand", target_point=(0.0, 150.0, 40.0))])
        patch = prepare_interaction_recipe(recipe, {"A": a}).build_pose_patch()
        self.assertEqual(patch.figure_positions["A"], (51.5, 12.0, 37.7))

    def test_balance_target_sets_height_and_wins_over_floor_lock(self):
        a = self._live_profile("A", (0.0, 0.0, 0.0), {"hip": (0.0, 95.0, 0.0), "r_hand": (-51.5, 99.8, 2.3)})
        recipe = InteractionRecipe(
            kind="sit",
            actors=["A"],
            constraints=[
                BalanceTarget("A", "pelvis", center_of_mass_hint=(0.0, 50.0, 0.0)),
                HandTarget("A", "r_hand", target_point=(-51.5, 60.0, 2.3)),
            ],
        )
        patch = prepare_interaction_recipe(recipe, {"A": a}).build_pose_patch()
        self.assertEqual(patch.figure_positions["A"][1], -45.0)

    def test_balance_target_pelvis_accepts_anchor_or_bone_name(self):
        # kz3t: validate and build_pose_patch must agree on what pelvis_bone means.
        a = self._live_profile("A", (0.0, 0.0, 0.0), {"hip": (0.0, 95.0, 0.0)})
        for name in ("pelvis", "hip"):
            with self.subTest(pelvis_bone=name):
                plan = InteractionPlan(actors=["A"], constraints=[BalanceTarget("A", name, center_of_mass_hint=(0.0, 50.0, 0.0))])
                self.assertEqual(plan.validate({"A": a}), [])
                recipe = InteractionRecipe(kind="sit", actors=["A"], constraints=list(plan.constraints))
                patch = prepare_interaction_recipe(recipe, {"A": a}).build_pose_patch()
                self.assertEqual(patch.figure_positions["A"][1], -45.0)
                self.assertEqual(patch.diagnostics.get("unresolved_target_count", 0), 0)
        bad = InteractionPlan(actors=["A"], constraints=[BalanceTarget("A", "nope", center_of_mass_hint=(0.0, 50.0, 0.0))])
        self.assertEqual([issue.severity for issue in bad.validate({"A": a})], ["error"])

    def test_apply_shifts_cross_figure_targets_by_staging_displacement(self):
        a = self._live_profile("A", (0.0, 0.0, 0.0), {"r_hand": (-51.5, 99.8, 2.3)})
        b = self._live_profile("B", (0.0, 0.0, 0.0), {"l_shoulder": (3.5, 135.5, -3.6)})
        recipe = InteractionRecipe(kind="touch", actors=["A", "B"], constraints=[HandTarget("A", "r_hand", target_figure="B", target_anchor="l_shoulder", surface_standoff=0.0)])
        prepared = prepare_interaction_recipe(recipe, {"A": a, "B": b})
        moved = {}
        scene = MagicMock()
        scene.find_skeleton_by_label.side_effect = lambda label: MagicMock(set_position=lambda x, y, z, label=label: moved.__setitem__(label, (x, y, z)))
        seen = []
        with patch("dazpy._interaction_recipes.align_single_limb_target", side_effect=lambda skel, prof, resolved, **kw: seen.append(resolved.target_point) or MagicMock()):
            prepared.apply(scene, align_limb_targets=True)

        expected = (3.5 + moved["B"][0], 135.5 + moved["B"][1], -3.6 + moved["B"][2])
        for got, want in zip(seen[0], expected):
            self.assertAlmostEqual(got, want)
        # The hand target now coincides with the staged hand in X/Z.
        self.assertAlmostEqual(seen[0][0], moved["A"][0] - 51.5)

    @staticmethod
    def _arm_profile(label, figure_position, side, x_sign):
        """A Genesis 9 arm (clavicle -> upper arm -> forearm -> hand -> finger) on a figure at figure_position."""
        fx, fy, fz = figure_position
        chain = [
            ("hip", None, (0.0, 100.0, 0.0)),
            (f"{side}_shoulder", "hip", (x_sign * 3.0, 145.0, -2.0)),
            (f"{side}_upperarm", f"{side}_shoulder", (x_sign * 17.0, 140.0, -4.0)),
            (f"{side}_forearm", f"{side}_upperarm", (x_sign * 45.0, 140.0, -4.0)),
            (f"{side}_hand", f"{side}_forearm", (x_sign * 70.0, 140.0, -4.0)),
            (f"{side}_mid3", f"{side}_hand", (x_sign * 84.0, 140.0, -4.0)),
        ]
        bones = [
            BoneProfile(name=name, parent_name=parent, local_position=(0.0, 0.0, 0.0), world_position=(fx + x, fy + y, fz + z))
            for name, parent, (x, y, z) in chain
        ]
        return FigureRigProfile(figure_label=label, family="genesis_9", bones=bones, figure_position=figure_position)

    def test_genesis9_shoulder_anchor_is_the_upper_arm_joint_and_knee_the_shin(self):
        # G9's l_shoulder bone is the clavicle (origin by the sternum); kwpq.
        names = ["hip", "l_shoulder", "l_upperarm", "l_forearm", "l_hand", "l_thigh", "l_shin", "l_foot"]
        profile = FigureRigProfile(figure_label="G9", family="genesis_9", bones=[BoneProfile(name=n) for n in names])
        self.assertEqual(profile.anchor("l_shoulder").bone_name, "l_upperarm")
        self.assertEqual(profile.anchor("l_knee").bone_name, "l_shin")
        # Rigs without an upper-arm bone keep their shoulder bone.
        generic = FigureRigProfile(figure_label="X", family="generic", bones=[BoneProfile(name=n) for n in ["hip", "l_shoulder", "l_hand"]])
        self.assertEqual(generic.anchor("l_shoulder").bone_name, "l_shoulder")

    def test_effector_reach_is_distance_to_farthest_descendant(self):
        profile = self._arm_profile("A", (0.0, 0.0, 0.0), "r", -1.0)
        self.assertAlmostEqual(profile.effector_reach("r_hand"), 14.0)
        self.assertIsNone(FigureRigProfile(figure_label="B", family="generic", bones=[BoneProfile(name="r_hand")]).effector_reach("r_hand"))

    def test_anchor_to_anchor_target_resolves_a_surface_standoff(self):
        a = self._arm_profile("A", (60.0, 0.0, 0.0), "r", -1.0)
        b = self._arm_profile("B", (0.0, 0.0, 0.0), "l", 1.0)
        profiles = {"A": a, "B": b}
        resolved = resolve_interaction_target(HandTarget("A", "r_hand", target_figure="B", target_anchor="l_shoulder"), profiles)
        self.assertEqual(resolved.target_bone, "l_upperarm")
        self.assertEqual(resolved.target_point, (17.0, 140.0, -4.0))  # still the joint centre
        self.assertAlmostEqual(resolved.surface_standoff, ANCHOR_SURFACE_RADIUS["shoulder"] + 14.0)
        # Hand-to-hand meets palm to palm: half the hand's reach.
        b_hand = self._arm_profile("B", (0.0, 0.0, 0.0), "r", -1.0)
        handshake = resolve_interaction_target(HandTarget("A", "r_hand", target_figure="B", target_anchor="r_hand"), {"A": a, "B": b_hand})
        self.assertAlmostEqual(handshake.surface_standoff, 7.0)
        # An explicit point is the contact point; an explicit standoff wins.
        explicit = resolve_interaction_target(HandTarget("A", "r_hand", target_figure="B", target_anchor="l_shoulder", target_point=(1.0, 2.0, 3.0)), profiles)
        self.assertEqual(explicit.surface_standoff, 0.0)
        override = resolve_interaction_target(HandTarget("A", "r_hand", target_figure="B", target_anchor="l_shoulder", surface_standoff=4.5), profiles)
        self.assertEqual(override.surface_standoff, 4.5)
        # No finger bones: fall back to a nominal hand length.
        bare = FigureRigProfile(figure_label="C", family="genesis_9", bones=[BoneProfile(name="r_hand", world_position=(0.0, 0.0, 0.0))])
        fallback = resolve_interaction_target(HandTarget("C", "r_hand", target_figure="B", target_anchor="l_shoulder"), {"C": bare, "B": b})
        self.assertAlmostEqual(fallback.surface_standoff, ANCHOR_SURFACE_RADIUS["shoulder"] + EFFECTOR_REACH_FALLBACK["hand"])

    def test_surface_standoff_round_trips(self):
        plan = InteractionPlan(actors=["A", "B"], constraints=[HandTarget("A", "r_hand", target_figure="B", target_anchor="l_shoulder", surface_standoff=2.5)])
        restored = InteractionPlan.from_dict(plan.to_dict())
        self.assertEqual(restored.constraints[0].surface_standoff, 2.5)
        self.assertIsNone(InteractionPlan.from_dict(InteractionPlan(actors=["A"], constraints=[HandTarget("A", "r_hand")]).to_dict()).constraints[0].surface_standoff)

    def test_apply_aims_the_hand_at_the_partners_skin_not_the_joint(self):
        a = self._arm_profile("A", (60.0, 0.0, 0.0), "r", -1.0)
        b = self._arm_profile("B", (0.0, 0.0, 0.0), "l", 1.0)
        recipe = build_touch_recipe("A", "B")
        prepared = prepare_interaction_recipe(recipe, {"A": a, "B": b})
        standoff = prepared.resolved_targets[0].surface_standoff
        moved = {}
        scene = MagicMock()
        scene.find_skeleton_by_label.side_effect = lambda label: MagicMock(set_position=lambda x, y, z, label=label: moved.__setitem__(label, (x, y, z)))
        seen = []
        with patch(
            "dazpy._interaction_recipes.align_single_limb_target",
            side_effect=lambda skel, prof, resolved, **kw: seen.append(resolved.target_point) or LimbAlignmentResult(resolved.figure_label, resolved.anchor_name, resolved.bone_name, [], resolved.target_point),
        ):
            result = prepared.apply(scene, align_limb_targets=True)

        shift_b = tuple(moved["B"][i] - b.figure_position[i] for i in range(3))
        joint = (17.0 + shift_b[0], 140.0 + shift_b[1], -4.0 + shift_b[2])
        gap = [seen[0][i] - joint[i] for i in range(3)]
        self.assertAlmostEqual(math.sqrt(sum(g * g for g in gap)), standoff)
        # Pulled toward A's upper arm (A stands on +X of B), not deeper into B.
        shift_a = tuple(moved["A"][i] - a.figure_position[i] for i in range(3))
        a_root_x = a.bone("r_upperarm").world_position[0] + shift_a[0]
        self.assertGreater(seen[0][0], joint[0])
        self.assertLess(seen[0][0], a_root_x + 1e-9)
        diagnostics = result.alignment_results[0].diagnostics
        self.assertAlmostEqual(diagnostics["surface_standoff"], standoff)
        self.assertEqual(diagnostics["target_joint_point"], list(joint))

    def test_profile_builders_read_figure_position(self):
        snapshot = [{"name": "G9", "label": "A", "position": {"x": 10.0, "y": 0.0, "z": 5.0},
                     "bones": [{"name": "r_hand", "local_position": {"x": 0, "y": 0, "z": 0}, "world_position": {"x": -41.0, "y": 100.0, "z": 7.0}}]}]
        self.assertEqual(build_rig_profiles_from_snapshot(snapshot)["A"].bone_offset("r_hand"), (-51.0, 100.0, 2.0))

        skel = MagicMock()
        skel.label = "A"
        skel.position = {"x": 10.0, "y": 0.0, "z": 5.0}
        skel.bone_metadata.return_value = snapshot[0]["bones"]
        self.assertEqual(build_rig_profile(skel).figure_position, (10.0, 0.0, 5.0))

    def test_prepared_recipe_live_alignment_reduces_error(self):
        hip = KinematicFakeBone("hip", "Hip", local_position=(0.0, 0.0, 0.0))
        shoulder = KinematicFakeBone("l_shoulder", "Left Shoulder", parent=hip, local_position=(1.0, 0.0, 0.0))
        upper_arm = KinematicFakeBone("l_upper_arm", "Left Upper Arm", parent=shoulder, local_position=(1.0, 0.0, 0.0))
        forearm = KinematicFakeBone("l_forearm", "Left Forearm", parent=upper_arm, local_position=(1.0, 0.0, 0.0))
        hand = KinematicFakeBone("l_hand", "Left Hand", parent=forearm, local_position=(1.0, 0.0, 0.0))
        source_skel = KinematicFakeSkeleton("Genesis 9", [hip, shoulder, upper_arm, forearm, hand])
        scene = FakeRigScene([source_skel])

        profile = build_rig_profile(source_skel)
        recipe = InteractionRecipe(
            kind="custom",
            actors=["Genesis 9"],
            constraints=[HandTarget("Genesis 9", "l_hand", target_point=(3.0, 1.0, 0.0))],
        )
        prepared = prepare_interaction_recipe(recipe, {"Genesis 9": profile})

        result = prepared.apply(scene, align_limb_targets=True, max_iterations=20, step_degrees=2.0, damping=0.35, tolerance=0.05)

        self.assertEqual(len(result.alignment_results), 1)
        self.assertIsInstance(result.alignment_results[0], LimbAlignmentResult)
        self.assertLess(result.alignment_results[0].final_error, result.alignment_results[0].initial_error)
        self.assertTrue(result.alignment_results[0].final_error is not None)

    def test_hand_to_target_convenience_wrapper_aligns(self):
        hip = KinematicFakeBone("hip", "Hip", local_position=(0.0, 0.0, 0.0))
        shoulder = KinematicFakeBone("l_shoulder", "Left Shoulder", parent=hip, local_position=(1.0, 0.0, 0.0))
        upper_arm = KinematicFakeBone("l_upper_arm", "Left Upper Arm", parent=shoulder, local_position=(1.0, 0.0, 0.0))
        forearm = KinematicFakeBone("l_forearm", "Left Forearm", parent=upper_arm, local_position=(1.0, 0.0, 0.0))
        hand = KinematicFakeBone("l_hand", "Left Hand", parent=forearm, local_position=(1.0, 0.0, 0.0))
        skeleton = KinematicFakeSkeleton("Genesis 9", [hip, shoulder, upper_arm, forearm, hand])

        result = align_hand_target(skeleton, (3.0, 1.0, 0.0), source_anchor="l_hand", max_iterations=20, step_degrees=2.0, damping=0.35, tolerance=0.05)

        self.assertIsInstance(result, LimbAlignmentResult)
        self.assertLess(result.final_error, result.initial_error)

    def test_scene_level_interaction_applies_recipe(self):
        hip = KinematicFakeBone("hip", "Hip", local_position=(0.0, 0.0, 0.0))
        shoulder = KinematicFakeBone("l_shoulder", "Left Shoulder", parent=hip, local_position=(1.0, 0.0, 0.0))
        upper_arm = KinematicFakeBone("l_upper_arm", "Left Upper Arm", parent=shoulder, local_position=(1.0, 0.0, 0.0))
        forearm = KinematicFakeBone("l_forearm", "Left Forearm", parent=upper_arm, local_position=(1.0, 0.0, 0.0))
        hand = KinematicFakeBone("l_hand", "Left Hand", parent=forearm, local_position=(1.0, 0.0, 0.0))
        skeleton = KinematicFakeSkeleton("Genesis 9", [hip, shoulder, upper_arm, forearm, hand])
        scene = DazScene.__new__(DazScene)
        scene.skeletons = lambda: [skeleton]
        scene.find_skeleton_by_label = lambda label: skeleton

        recipe = InteractionRecipe(
            kind="custom",
            actors=["Genesis 9"],
            constraints=[HandTarget("Genesis 9", "l_hand", target_point=(3.0, 1.0, 0.0))],
        )
        result = DazScene.apply_interaction_recipe(
            scene,
            recipe,
            align_limb_targets=True,
            max_iterations=20,
            step_degrees=2.0,
            damping=0.35,
            tolerance=0.05,
        )

        self.assertIsInstance(result, PreparedInteractionResult)
        self.assertEqual(len(result.alignment_results), 1)
        self.assertLess(result.alignment_results[0].final_error, result.alignment_results[0].initial_error)

    # ── facing (y1td) ────────────────────────────────────────────────────────

    @staticmethod
    def _facing_profiles():
        """Two figures side by side, both facing +Z (the rest-pose live setup)."""

        def entry(label, x):
            def bone(name, parent, world):
                return {"name": name, "label": name, "parent_name": parent, "local_position": [0, 0, 0], "world_position": world}

            return {
                "name": label.replace(" ", ""),
                "label": label,
                "position": [x, 0, 0],
                "bones": [
                    bone("hip", None, [x, 100, 0]),
                    bone("r_shoulder", "hip", [x - 10, 145, 0]),
                    bone("r_upperarm", "r_shoulder", [x - 20, 140, 0]),
                    bone("r_hand", "r_upperarm", [x - 50, 100, 0]),
                    bone("l_shoulder", "hip", [x + 10, 145, 0]),
                    bone("l_upperarm", "l_shoulder", [x + 20, 140, 0]),
                    bone("l_hand", "l_upperarm", [x + 50, 100, 0]),
                    bone("head", "hip", [x, 165, 0]),
                ],
            }

        return build_rig_profiles_from_snapshot([entry("Genesis 9", -100), entry("Partner", 100)])

    def test_facing_turns_second_actor_of_look_at_recipes_only(self):
        from dazpy._interaction import figure_forward, plan_facing, rotate_about_y

        x, y, z = rotate_about_y((0.0, 5.0, 1.0), 90.0)
        self.assertAlmostEqual(x, 1.0)
        self.assertEqual(y, 5.0)
        self.assertAlmostEqual(z, 0.0)
        self.assertEqual(figure_forward(self._facing_profiles()["Genesis 9"]), (-0.0, 0.0, 1.0))
        for build in (build_hug_recipe, build_kiss_recipe, build_handshake_recipe, build_fight_recipe):
            facing = plan_facing(build("Genesis 9", "Partner").to_plan(), self._facing_profiles())
            self.assertEqual({k: v.to_dict() for k, v in facing.items()}, {"Partner": {"anchor": "Genesis 9", "yaw_degrees": 180.0}})
        self.assertEqual(plan_facing(build_touch_recipe("Genesis 9", "Partner").to_plan(), self._facing_profiles()), {})

    def test_face_each_other_turns_second_actor_in_place_toward_first(self):
        from dazpy._interaction import figure_forward

        # Partner at x=+100 faces +Z; Genesis 9 is at x=-100, so it turns to -X.
        prepared = prepare_interaction_recipe(build_face_each_other_recipe("Genesis 9", "Partner"), self._facing_profiles())
        self.assertEqual({k: v.to_dict() for k, v in prepared.facing.items()}, {"Partner": {"anchor": "Genesis 9", "yaw_degrees": -90.0}})
        self.assertAlmostEqual(figure_forward(prepared.rig_profiles["Partner"])[0], -1.0)
        patch = prepared.build_pose_patch()
        self.assertEqual(patch.figure_yaw_degrees, {"Partner": -90.0})
        self.assertEqual(patch.figure_positions, {})

    def test_face_each_other_coincident_origins_face_back_along_first_actor(self):
        from dataclasses import replace

        from dazpy._interaction import plan_facing

        profiles = self._facing_profiles()
        together = {label: replace(profile, figure_position=(0.0, 0.0, 0.0)) for label, profile in profiles.items()}
        facing = plan_facing(build_face_each_other_recipe("Genesis 9", "Partner").to_plan(), together)
        self.assertEqual({k: v.to_dict() for k, v in facing.items()}, {"Partner": {"anchor": "Genesis 9", "yaw_degrees": 180.0}})

    def test_hug_stages_turned_partner_in_front(self):
        from dazpy._interaction import WRAP_SEPARATION, figure_forward

        prepared = prepare_interaction_recipe(build_hug_recipe("Genesis 9", "Partner"), self._facing_profiles())
        self.assertAlmostEqual(figure_forward(prepared.rig_profiles["Partner"])[2], -1.0)
        patch = prepared.build_pose_patch()
        self.assertEqual(patch.figure_yaw_degrees, {"Partner": 180.0})
        self.assertEqual(list(patch.figure_positions), ["Partner"])
        x, y, z = patch.figure_positions["Partner"]
        self.assertEqual((x, y), (-100.0, 0.0))
        # Wrapped arms stage the partner at embrace distance, inside the reach minimum (3shz).
        self.assertEqual(z, WRAP_SEPARATION)
        # B's right hand -> A's left shoulder is on B's near side now, not behind it.
        self.assertEqual(prepared.resolved_targets[1].figure_label, "Partner")
        self.assertGreater(prepared.resolved_targets[1].target_point[0], -100.0)

        turns, moves = [], []
        scene = MagicMock()
        scene.find_skeleton_by_label.side_effect = lambda label: MagicMock(
            local_euler=(0.0, 10.0, 0.0),
            set_rotation=lambda *r, label=label: turns.append((label, r)),
            set_position=lambda *p, label=label: moves.append(label),
        )
        patch.apply(scene)
        self.assertEqual(turns, [("Partner", (0.0, 190.0, 0.0))])
        self.assertEqual(moves, ["Partner"])

    def test_hug_wraps_around_the_partners_side_to_its_back(self):
        from dazpy._interaction import WRAP_BACK_POINT, WRAP_SIDE_POINTS

        recipe = build_hug_recipe("Genesis 9", "Partner")
        self.assertTrue(all(c.wrap for c in recipe.constraints if isinstance(c, HandTarget)))
        self.assertEqual(InteractionRecipe.from_dict(recipe.to_dict()).to_dict(), recipe.to_dict())
        prepared = prepare_interaction_recipe(recipe, self._facing_profiles())
        partner_z = prepared.build_pose_patch().figure_positions["Partner"][2]
        bases = {id(prepared.rig_profiles["Genesis 9"]): (-100.0, 0.0, 0.0), id(prepared.rig_profiles["Partner"]): (-100.0, 0.0, partner_z)}
        # A's right hand -> Partner's left shoulder. Partner faces -Z, so its left is -X and its back is +Z.
        a_hand = prepared._contact_geometry(prepared.resolved_targets[0], bases)
        self.assertEqual(len(a_hand.waypoints), len(WRAP_SIDE_POINTS))
        for point, (lateral, back) in zip(a_hand.waypoints, WRAP_SIDE_POINTS):
            self.assertAlmostEqual(point[0], -100.0 - lateral)
            self.assertAlmostEqual(point[2], partner_z + back)
        self.assertAlmostEqual(a_hand.stop[0], -100.0 - WRAP_BACK_POINT[0])
        self.assertAlmostEqual(a_hand.stop[2], partner_z + WRAP_BACK_POINT[1])
        self.assertLess(a_hand.stop[1], 145.0)  # below the shoulder anchors
        # B's right hand -> Genesis 9's left shoulder: Genesis 9 faces +Z, left is +X, back is -Z.
        b_hand = prepared._contact_geometry(prepared.resolved_targets[1], bases)
        self.assertAlmostEqual(b_hand.stop[0], -100.0 + WRAP_BACK_POINT[0])
        self.assertAlmostEqual(b_hand.stop[2], -WRAP_BACK_POINT[1])

    def test_hug_alignment_passes_each_waypoint_then_the_back(self):
        prepared = prepare_interaction_recipe(build_hug_recipe("Genesis 9", "Partner"), self._facing_profiles())
        scene = MagicMock()
        scene.find_skeleton_by_label.side_effect = lambda label: MagicMock(local_euler=(0.0, 0.0, 0.0))
        seen: list = []

        def _fake(skel, prof, resolved, **kw):
            seen.append((resolved.figure_label, resolved.target_point))
            return LimbAlignmentResult(resolved.figure_label, resolved.anchor_name, resolved.bone_name, [], resolved.target_point, iterations=5, converged=True, initial_error=float(len(seen)), final_error=0.1)

        with patch("dazpy._interaction_recipes.align_single_limb_target", side_effect=_fake):
            result = prepared.apply(scene, align_limb_targets=True)
        a, b = result.alignment_results
        staged, original = result.pose_patch.figure_positions["Partner"], prepared.rig_profiles["Partner"].figure_position
        bases = prepared._staged_bases({"Partner": tuple(s - o for s, o in zip(staged, original))})
        geometry = prepared._contact_geometry(prepared.resolved_targets[0], bases)
        self.assertEqual([p for label, p in seen[:3]], [*geometry.waypoints, geometry.stop])
        self.assertEqual(a.target_point, geometry.stop)
        self.assertEqual(a.iterations, 15)
        self.assertEqual(a.initial_error, 1.0)  # the first pass's
        self.assertEqual(len(a.diagnostics["waypoint_errors"]), 2)
        self.assertEqual(b.figure_label, "Partner")

    def test_handshake_hands_aim_at_one_meeting_point(self):
        from dazpy._interaction import FACING_REACH_FRACTION

        prepared = prepare_interaction_recipe(build_handshake_recipe("Genesis 9", "Partner"), self._facing_profiles())
        scene = MagicMock()
        scene.find_skeleton_by_label.side_effect = lambda label: MagicMock(local_euler=(0.0, 0.0, 0.0))
        seen = []
        with patch(
            "dazpy._interaction_recipes.align_single_limb_target",
            side_effect=lambda skel, prof, resolved, **kw: seen.append(resolved.target_point) or LimbAlignmentResult(resolved.figure_label, resolved.anchor_name, resolved.bone_name, [], resolved.target_point),
        ):
            result = prepared.apply(scene, align_limb_targets=True)
        a, b = result.alignment_results
        self.assertEqual(a.diagnostics["meeting_point"], b.diagnostics["meeting_point"])
        meeting = a.diagnostics["meeting_point"]
        partner_z = result.pose_patch.figure_positions["Partner"][2]
        self.assertAlmostEqual(meeting[0], -100.0)
        self.assertAlmostEqual(meeting[2], partner_z / 2)
        self.assertLess(seen[0][2], meeting[2])
        self.assertGreater(seen[1][2], meeting[2])
        # Reach runs from the start of the last two long segments (r_shoulder -> r_upperarm -> r_hand), not the hip.
        reach = math.dist((-10, 145, 0), (-20, 140, 0)) + math.dist((-20, 140, 0), (-50, 100, 0))
        self.assertAlmostEqual(math.dist(seen[0], (-110, 145, 0)), reach * FACING_REACH_FRACTION, places=6)

    def test_default_axis_limits_for_bone(self):
        limits = default_axis_limits_for_bone("r_forearm")
        self.assertIsInstance(limits["x"], AxisLimit)
        self.assertLess(limits["x"].min_degrees, 0.0)
        self.assertGreater(limits["x"].max_degrees, 0.0)


if __name__ == "__main__":
    unittest.main()
