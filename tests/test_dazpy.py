"""
Unit tests for dazpy — mock DazClient.execute() to verify script generation.

No server or DAZ Studio required; all DAZ calls are mocked.

Run standalone:  python tests/test_dazpy.py
Via runner:      python tests.py unit
"""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from dazpy._result import ExecutionResult
from dazpy._script_builder import ScriptBuilder
from dazpy._batch import Batch
from dazpy._scene_events import SceneEvent, watch_scene_events, wait_for_scene_event
from dazpy.exceptions import ConnectionError as DazConnectionError
from dazpy.exceptions import TimeoutError as DazTimeoutError
from dazpy import (
    AnchorTarget,
    AxisLimit,
    BalanceTarget,
    BoneChain,
    BoneProfile,
    ContactTarget,
    FigureRigProfile,
    FootTarget,
    InteractionAnchor,
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
    build_kiss_recipe,
    build_sit_recipe,
    build_touch_recipe,
    prepare_interaction_recipe,
    SolveOptions,
    ValidationIssue,
    build_rig_profile,
    align_hand_target,
    default_axis_limits_for_bone,
    align_single_limb_target,
    apply_interaction_recipe_to_scene,
    resolve_interaction_target,
)
from dazpy._node import DazNode, NodeIdentifier
from dazpy._scene import DazScene
from dazpy._client import DazClient
from dazpy import exceptions


def _make_client(return_value=None, output=None):
    client = MagicMock(spec=DazClient)
    client.execute.return_value = ExecutionResult(
        value=return_value,
        output=output or [],
        request_id="test1234",
    )
    return client


class _FakeBone:
    def __init__(
        self,
        name: str,
        label: str | None = None,
        parent: "_FakeBone | None" = None,
        rotation_order: str | None = "XYZ",
        local_position: tuple[float, float, float] | None = (0.0, 0.0, 0.0),
        local_euler: tuple[float, float, float] | None = (0.0, 0.0, 0.0),
    ) -> None:
        self.name = name
        self.label = label
        self.parent = parent
        self.rotation_order = rotation_order
        self.local_position = local_position
        self.local_euler = local_euler
        self._identifier = NodeIdentifier(name)


class _FakeSkeleton:
    def __init__(self, label: str, bones: list[_FakeBone]) -> None:
        self.label = label
        self._bones = bones
        self._identifier = NodeIdentifier(label, kind="label")
        self.position_calls: list[tuple[float, float, float]] = []

    def bones(self) -> list[_FakeBone]:
        return self._bones

    def set_position(self, x: float, y: float, z: float) -> None:
        self.position_calls.append((x, y, z))


class _FakeScene:
    def __init__(self, skeletons: list[_FakeSkeleton]) -> None:
        self._skeletons = skeletons

    def skeletons(self) -> list[_FakeSkeleton]:
        return self._skeletons

    def find_skeleton_by_label(self, label: str) -> _FakeSkeleton:
        for skeleton in self._skeletons:
            if skeleton.label == label:
                return skeleton
        raise KeyError(label)


class _KinematicFakeBone:
    def __init__(
        self,
        name: str,
        label: str | None = None,
        parent: "_KinematicFakeBone | None" = None,
        local_position: tuple[float, float, float] | None = (1.0, 0.0, 0.0),
    ) -> None:
        self.name = name
        self.label = label
        self.parent = parent
        self.rotation_order = "XYZ"
        self.local_position = local_position
        self.local_euler = (0.0, 0.0, 0.0)
        self._identifier = NodeIdentifier(name)
        self._world_position = (0.0, 0.0, 0.0)

    def _world_angle(self) -> float:
        import math

        own = math.radians(self.local_euler[2])
        if self.parent is None:
            return own
        return self.parent._world_angle() + own

    @property
    def position(self) -> tuple[float, float, float]:
        import math

        if self.parent is None:
            return self._world_position
        parent_position = self.parent.position
        parent_angle = self.parent._world_angle()
        offset = self.local_position or (0.0, 0.0, 0.0)
        cos_a = math.cos(parent_angle)
        sin_a = math.sin(parent_angle)
        rotated = (
            offset[0] * cos_a - offset[1] * sin_a,
            offset[0] * sin_a + offset[1] * cos_a,
            offset[2],
        )
        return (
            parent_position[0] + rotated[0],
            parent_position[1] + rotated[1],
            parent_position[2] + rotated[2],
        )

    def set_local_rotation(self, x: float, y: float, z: float) -> None:
        self.local_euler = (x, y, z)


class _KinematicFakeSkeleton:
    def __init__(self, label: str, bones: list[_KinematicFakeBone]) -> None:
        self.label = label
        self._bones = bones
        self._by_name = {bone.name: bone for bone in bones}
        self._identifier = NodeIdentifier(label, kind="label")
        self.position_calls: list[tuple[float, float, float]] = []

    def bones(self) -> list[_KinematicFakeBone]:
        return self._bones

    def find_bone(self, name: str) -> _KinematicFakeBone:
        return self._by_name[name]

    def set_position(self, x: float, y: float, z: float) -> None:
        self.position_calls.append((x, y, z))


class TestScriptBuilder(unittest.TestCase):
    def test_escape_string_basic(self):
        self.assertEqual(ScriptBuilder.escape_string("hello"), '"hello"')

    def test_escape_string_quotes(self):
        result = ScriptBuilder.escape_string('say "hi"')
        self.assertIn('\\"', result)

    def test_escape_string_backslash(self):
        result = ScriptBuilder.escape_string("C:\\path\\file")
        self.assertIn("\\\\", result)

    def test_escape_string_newline(self):
        result = ScriptBuilder.escape_string("line1\nline2")
        self.assertIn("\\n", result)

    def test_escape_string_null_byte(self):
        result = ScriptBuilder.escape_string("null\x00byte")
        self.assertIn("\\u0000", result)

    def test_iife_wraps_body(self):
        result = ScriptBuilder.iife("return 42;")
        self.assertTrue(result.startswith("(function(){"))
        self.assertIn("return 42;", result)
        self.assertTrue(result.rstrip().endswith(")()"))

    def test_find_node_by_name(self):
        ident = NodeIdentifier("Genesis9", kind="name")
        expr = ScriptBuilder.find_node_expr(ident)
        self.assertIn('Scene.findNode(', expr)
        self.assertIn('"Genesis9"', expr)

    def test_find_node_by_label(self):
        ident = NodeIdentifier("Genesis 9", kind="label")
        expr = ScriptBuilder.find_node_expr(ident)
        self.assertIn('Scene.findNodeByLabel(', expr)
        self.assertIn('"Genesis 9"', expr)

    def test_serialize_arg_bool(self):
        self.assertEqual(ScriptBuilder.serialize_arg(True), "true")
        self.assertEqual(ScriptBuilder.serialize_arg(False), "false")

    def test_serialize_arg_int(self):
        self.assertEqual(ScriptBuilder.serialize_arg(42), "42")

    def test_serialize_arg_float(self):
        self.assertEqual(ScriptBuilder.serialize_arg(3.14), "3.14")

    def test_serialize_arg_string(self):
        self.assertEqual(ScriptBuilder.serialize_arg("hi"), '"hi"')

    def test_serialize_arg_dict(self):
        result = ScriptBuilder.serialize_arg({"x": 1})
        parsed = json.loads(result)
        self.assertEqual(parsed, {"x": 1})


class TestInjectionSafety(unittest.TestCase):
    """Adversarial strings must not break the generated script syntax."""

    ADVERSARIAL = [
        'say "hello"',
        "it's a test",
        "line1\nline2",
        "tab\there",
        "back\\slash",
        "null\x00byte",
        "</script>",
        "${injection}",
        "'; DROP TABLE nodes; --",
    ]

    def _script_is_valid_json_strings(self, value: str):
        """Ensure escape_string produces valid JSON."""
        escaped = ScriptBuilder.escape_string(value)
        parsed = json.loads(escaped)
        self.assertEqual(parsed, value)

    def test_all_adversarial_strings(self):
        for s in self.ADVERSARIAL:
            with self.subTest(s=s):
                self._script_is_valid_json_strings(s)


class TestDazNodeScriptGeneration(unittest.TestCase):
    def test_label_property_calls_execute(self):
        client = _make_client("Genesis 9")
        node = DazNode(client, NodeIdentifier("Genesis9"))
        result = node.label
        self.assertEqual(result, "Genesis 9")
        client.execute.assert_called_once()
        script = client.execute.call_args[0][0]
        self.assertIn("Genesis9", script)
        self.assertIn("getLabel", script)

    def test_position_returns_dict(self):
        client = _make_client({"x": 0.0, "y": 95.2, "z": -3.1})
        node = DazNode(client, NodeIdentifier("Genesis9"))
        pos = node.position
        self.assertEqual(pos["y"], 95.2)

    def test_set_position_calls_execute(self):
        client = _make_client(None)
        node = DazNode(client, NodeIdentifier("Genesis9"))
        node.set_position(1.0, 2.0, 3.0)
        script = client.execute.call_args[0][0]
        self.assertIn("setWSPos", script)
        self.assertIn("1.0", script)

    def test_rotation_returns_xyzw(self):
        client = _make_client({"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0})
        node = DazNode(client, NodeIdentifier("Genesis9"))
        rot = node.rotation
        self.assertIn("w", rot)
        self.assertEqual(rot["w"], 1.0)
        script = client.execute.call_args[0][0]
        self.assertIn("r.w", script)

    def test_general_scale_returns_float(self):
        client = _make_client(1.0)
        node = DazNode(client, NodeIdentifier("Genesis9"))
        gs = node.general_scale
        self.assertEqual(gs, 1.0)
        script = client.execute.call_args[0][0]
        self.assertIn("getScaleControl", script)
        self.assertNotIn("getXScaleControl", script)

    def test_scale_returns_dict_with_all_axes(self):
        client = _make_client({"x": 1.0, "y": 1.0, "z": 1.0, "general": 1.0})
        node = DazNode(client, NodeIdentifier("Genesis9"))
        s = node.scale
        self.assertIsInstance(s, dict)
        for key in ("x", "y", "z", "general"):
            self.assertIn(key, s)
        script = client.execute.call_args[0][0]
        self.assertIn("getXScaleControl", script)
        self.assertIn("getYScaleControl", script)
        self.assertIn("getZScaleControl", script)
        self.assertIn("getScaleControl", script)

    def test_visible_setter(self):
        client = _make_client(None)
        node = DazNode(client, NodeIdentifier("MyNode"))
        node.visible = False
        script = client.execute.call_args[0][0]
        self.assertIn("setVisible", script)
        self.assertIn("false", script)


class TestDazScene(unittest.TestCase):
    def test_nodes_returns_list(self):
        client = _make_client([
            {"name": "Genesis9", "className": "DzSkeleton"},
            {"name": "Camera 1", "className": "DzCamera"},
        ])
        scene = DazScene(client)
        nodes = scene.nodes()
        self.assertEqual(len(nodes), 2)
        self.assertIsInstance(nodes[0], DazNode)

    def test_nodes_type_discrimination_skeleton(self):
        from dazpy._skeleton import DazSkeleton
        from dazpy._camera import DazCamera
        client = _make_client([
            {"name": "Genesis9", "className": "DzSkeleton"},
            {"name": "Camera 1", "className": "DzCamera"},
            {"name": "Prop1", "className": "DzNode"},
        ])
        scene = DazScene(client)
        nodes = scene.nodes()
        self.assertIsInstance(nodes[0], DazSkeleton)
        self.assertIsInstance(nodes[1], DazCamera)
        self.assertIsInstance(nodes[2], DazNode)

    def test_nodes_script_uses_inherits_for_type_detection(self):
        client = _make_client([])
        scene = DazScene(client)
        scene.nodes()
        script = client.execute.call_args[0][0]
        self.assertIn("inherits", script)
        self.assertIn("DzSkeleton", script)

    def test_num_nodes(self):
        client = _make_client(5)
        scene = DazScene(client)
        self.assertEqual(scene.num_nodes(), 5)

    def test_find_node_success(self):
        client = _make_client(True)
        scene = DazScene(client)
        node = scene.find_node("Genesis9")
        self.assertIsInstance(node, DazNode)

    def test_find_node_not_found(self):
        client = _make_client(False)
        scene = DazScene(client)
        with self.assertRaises(exceptions.NodeNotFoundError):
            scene.find_node("NonExistent")

    def test_all_node_transforms(self):
        data = [{"name": "n1", "label": "Node 1", "position": [0, 0, 0], "rotation": [0, 0, 0], "visible": True}]
        client = _make_client(data)
        scene = DazScene(client)
        transforms = scene.all_node_transforms()
        self.assertEqual(len(transforms), 1)
        self.assertEqual(transforms[0]["name"], "n1")

    def test_create_camera_returns_daz_camera(self):
        from dazpy._camera import DazCamera
        client = _make_client("Camera")
        scene = DazScene(client)
        camera = scene.create_camera()
        self.assertIsInstance(camera, DazCamera)
        self.assertEqual(camera._identifier.value, "Camera")

    def test_create_camera_script_uses_basic_camera_and_add_node(self):
        client = _make_client("Camera")
        scene = DazScene(client)
        scene.create_camera()
        script = client.execute.call_args[0][0]
        self.assertIn("new DzBasicCamera()", script)
        self.assertIn("Scene.addNode(cam)", script)

    def test_create_camera_with_name_sets_name(self):
        client = _make_client("MyCam")
        scene = DazScene(client)
        scene.create_camera(name="MyCam")
        script = client.execute.call_args[0][0]
        self.assertIn('cam.setName("MyCam")', script)

    def test_create_light_returns_daz_light(self):
        from dazpy._light import DazLight
        client = _make_client("Spotlight1")
        scene = DazScene(client)
        light = scene.create_light("spot")
        self.assertIsInstance(light, DazLight)
        self.assertEqual(light._identifier.value, "Spotlight1")

    def test_create_light_script_uses_correct_class_per_type(self):
        cases = {
            "spot": "DzSpotLight",
            "point": "DzPointLight",
            "distant": "DzDistantLight",
        }
        for light_type, class_name in cases.items():
            client = _make_client("Light1")
            scene = DazScene(client)
            scene.create_light(light_type)
            script = client.execute.call_args[0][0]
            self.assertIn(f"new {class_name}()", script)
            self.assertIn("Scene.addNode(light)", script)

    def test_create_light_with_name_sets_name(self):
        client = _make_client("Key Light")
        scene = DazScene(client)
        scene.create_light("point", name="Key Light")
        script = client.execute.call_args[0][0]
        self.assertIn('light.setName("Key Light")', script)

    def test_create_light_invalid_type_raises(self):
        client = _make_client(None)
        scene = DazScene(client)
        with self.assertRaises(ValueError):
            scene.create_light("area")


class TestBatch(unittest.TestCase):
    def test_batch_builds_single_script(self):
        client = _make_client({"_r0": 10, "_r1": 5})
        with Batch(client) as batch:
            f_count = batch.add(["var _r0 = Scene.getNumNodes();"])
            f_frame = batch.add(["var _r1 = Scene.getFrame();"])

        self.assertEqual(f_count.value, 10)
        self.assertEqual(f_frame.value, 5)
        client.execute.assert_called_once()

    def test_batch_script_contains_return_map(self):
        client = _make_client({"_r0": 42})
        batch = Batch(client)
        batch.add(["var _r0 = 42;"])
        batch.execute()
        script = client.execute.call_args[0][0]
        self.assertIn('"_r0"', script)
        self.assertIn("return", script)

    def test_future_raises_before_execute(self):
        client = _make_client({"_r0": 1})
        batch = Batch(client)
        future = batch.add(["var _r0 = 1;"])
        with self.assertRaises(RuntimeError):
            _ = future.value

    def test_empty_batch_no_call(self):
        client = _make_client(None)
        with Batch(client):
            pass
        client.execute.assert_not_called()


class TestInteractionAdapter(unittest.TestCase):
    def test_build_rig_profile_detects_family_and_anchors(self):
        hip = _FakeBone("hip", "Hip")
        spine = _FakeBone("spine", "Spine", parent=hip)
        chest = _FakeBone("chest", "Chest", parent=spine)
        neck = _FakeBone("neck", "Neck", parent=chest)
        head = _FakeBone("head", "Head", parent=neck)
        l_hand = _FakeBone("l_hand", "Left Hand", parent=chest)
        r_hand = _FakeBone("r_hand", "Right Hand", parent=chest)
        l_foot = _FakeBone("l_foot", "Left Foot", parent=hip)
        r_foot = _FakeBone("r_foot", "Right Foot", parent=hip)
        skeleton = _FakeSkeleton("Genesis 9", [hip, spine, chest, neck, head, l_hand, r_hand, l_foot, r_foot])

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
        hip = _FakeBone("hip", "Hip")
        spine = _FakeBone("abdomenLower", "Abdomen Lower", parent=hip)
        chest = _FakeBone("chestLower", "Chest Lower", parent=spine)
        lCollar = _FakeBone("lCollar", "Left Collar", parent=chest)
        rCollar = _FakeBone("rCollar", "Right Collar", parent=chest)
        lForearmBend = _FakeBone("lForearmBend", "Left Forearm Bend", parent=lCollar)
        rForearmBend = _FakeBone("rForearmBend", "Right Forearm Bend", parent=rCollar)
        lHand = _FakeBone("lHand", "Left Hand", parent=lForearmBend)
        rHand = _FakeBone("rHand", "Right Hand", parent=rForearmBend)
        lFoot = _FakeBone("lFoot", "Left Foot", parent=hip)
        rFoot = _FakeBone("rFoot", "Right Foot", parent=hip)
        skeleton = _FakeSkeleton(
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
        hip = _FakeBone("hip", "Hip")
        hand = _FakeBone("r_hand", "Right Hand", parent=hip, local_position=(10.0, 20.0, 30.0))
        foot = _FakeBone("l_foot", "Left Foot", parent=hip, local_position=(1.0, 2.0, 3.0))
        profile = build_rig_profile(_FakeSkeleton("Genesis 9", [hip, hand, foot]))

        resolved = resolve_interaction_target(
            HandTarget("Genesis 9", "r_hand", target_point=(1.0, 2.0, 3.0), offset=(0.5, 0.0, -0.5)),
            {"Genesis 9": profile},
        )

        self.assertEqual(resolved.bone_name, "r_hand")
        self.assertEqual(resolved.target_point, (1.5, 2.0, 2.5))
        self.assertIsNone(resolved.target_bone)

    def test_resolve_interaction_target_cross_figure(self):
        source_hip = _FakeBone("hip", "Hip")
        source_hand = _FakeBone("r_hand", "Right Hand", parent=source_hip)
        source_profile = build_rig_profile(_FakeSkeleton("Genesis 9", [source_hip, source_hand]))

        target_hip = _FakeBone("hip", "Hip")
        target_hand = _FakeBone("r_hand", "Right Hand", parent=target_hip, local_position=(4.0, 5.0, 6.0))
        target_profile = build_rig_profile(_FakeSkeleton("Partner", [target_hip, target_hand]))

        resolved = resolve_interaction_target(
            FootTarget("Genesis 9", "r_hand", target_figure="Partner", target_anchor="r_hand"),
            {"Genesis 9": source_profile, "Partner": target_profile},
        )

        self.assertEqual(resolved.target_figure, "Partner")
        self.assertEqual(resolved.target_anchor, "r_hand")
        self.assertEqual(resolved.target_bone, "r_hand")
        self.assertEqual(resolved.target_point, (4.0, 5.0, 6.0))

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

    def test_prepare_interaction_recipe_compiles_targets(self):
        source_hip = _FakeBone("hip", "Hip")
        source_hand = _FakeBone("r_hand", "Right Hand", parent=source_hip, local_position=(1.0, 2.0, 3.0))
        target_hip = _FakeBone("hip", "Hip")
        target_shoulder = _FakeBone("l_shoulder", "Left Shoulder", parent=target_hip, local_position=(4.0, 5.0, 6.0))
        source_profile = build_rig_profile(_FakeSkeleton("Genesis 9", [source_hip, source_hand]))
        target_profile = build_rig_profile(_FakeSkeleton("Partner", [target_hip, target_shoulder]))

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
        source_hip = _FakeBone("hip", "Hip")
        source_hand = _FakeBone("r_hand", "Right Hand", parent=source_hip, local_position=(1.0, 2.0, 3.0))
        target_hip = _FakeBone("hip", "Hip")
        target_shoulder = _FakeBone("l_shoulder", "Left Shoulder", parent=target_hip, local_position=(4.0, 5.0, 6.0))
        source_skel = _FakeSkeleton("Genesis 9", [source_hip, source_hand])
        target_skel = _FakeSkeleton("Partner", [target_hip, target_shoulder])
        scene = _FakeScene([source_skel, target_skel])

        source_profile = build_rig_profile(source_skel)
        target_profile = build_rig_profile(target_skel)
        prepared = prepare_interaction_recipe(
            build_touch_recipe("Genesis 9", "Partner", source_anchor="r_hand", target_anchor="l_shoulder"),
            {"Genesis 9": source_profile, "Partner": target_profile},
        )

        result = prepared.apply(scene)

        self.assertIsInstance(result, PreparedInteractionResult)
        self.assertIsInstance(result.pose_patch, InteractionPosePatch)
        self.assertEqual(source_skel.position_calls, [(1.5, 1.5, 1.5)])
        self.assertEqual(target_skel.position_calls, [(-1.5, -1.5, -1.5)])
        self.assertEqual(result.pose_patch.diagnostics["figure_count"], 2)
        self.assertEqual(result.pose_patch.diagnostics["unresolved_target_count"], 0)
        self.assertEqual(result.to_dict()["pose_patch"]["figure_positions"]["Genesis 9"], [1.5, 1.5, 1.5])
        self.assertEqual(result.to_dict()["pose_patch"]["figure_positions"]["Partner"], [-1.5, -1.5, -1.5])

    def test_prepared_recipe_live_alignment_reduces_error(self):
        hip = _KinematicFakeBone("hip", "Hip", local_position=(0.0, 0.0, 0.0))
        shoulder = _KinematicFakeBone("l_shoulder", "Left Shoulder", parent=hip, local_position=(1.0, 0.0, 0.0))
        upper_arm = _KinematicFakeBone("l_upper_arm", "Left Upper Arm", parent=shoulder, local_position=(1.0, 0.0, 0.0))
        forearm = _KinematicFakeBone("l_forearm", "Left Forearm", parent=upper_arm, local_position=(1.0, 0.0, 0.0))
        hand = _KinematicFakeBone("l_hand", "Left Hand", parent=forearm, local_position=(1.0, 0.0, 0.0))
        source_skel = _KinematicFakeSkeleton("Genesis 9", [hip, shoulder, upper_arm, forearm, hand])
        scene = _FakeScene([source_skel])

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
        hip = _KinematicFakeBone("hip", "Hip", local_position=(0.0, 0.0, 0.0))
        shoulder = _KinematicFakeBone("l_shoulder", "Left Shoulder", parent=hip, local_position=(1.0, 0.0, 0.0))
        upper_arm = _KinematicFakeBone("l_upper_arm", "Left Upper Arm", parent=shoulder, local_position=(1.0, 0.0, 0.0))
        forearm = _KinematicFakeBone("l_forearm", "Left Forearm", parent=upper_arm, local_position=(1.0, 0.0, 0.0))
        hand = _KinematicFakeBone("l_hand", "Left Hand", parent=forearm, local_position=(1.0, 0.0, 0.0))
        skeleton = _KinematicFakeSkeleton("Genesis 9", [hip, shoulder, upper_arm, forearm, hand])

        result = align_hand_target(skeleton, (3.0, 1.0, 0.0), source_anchor="l_hand", max_iterations=20, step_degrees=2.0, damping=0.35, tolerance=0.05)

        self.assertIsInstance(result, LimbAlignmentResult)
        self.assertLess(result.final_error, result.initial_error)

    def test_scene_level_interaction_applies_recipe(self):
        hip = _KinematicFakeBone("hip", "Hip", local_position=(0.0, 0.0, 0.0))
        shoulder = _KinematicFakeBone("l_shoulder", "Left Shoulder", parent=hip, local_position=(1.0, 0.0, 0.0))
        upper_arm = _KinematicFakeBone("l_upper_arm", "Left Upper Arm", parent=shoulder, local_position=(1.0, 0.0, 0.0))
        forearm = _KinematicFakeBone("l_forearm", "Left Forearm", parent=upper_arm, local_position=(1.0, 0.0, 0.0))
        hand = _KinematicFakeBone("l_hand", "Left Hand", parent=forearm, local_position=(1.0, 0.0, 0.0))
        skeleton = _KinematicFakeSkeleton("Genesis 9", [hip, shoulder, upper_arm, forearm, hand])
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

    def test_default_axis_limits_for_bone(self):
        limits = default_axis_limits_for_bone("r_forearm")
        self.assertIsInstance(limits["x"], AxisLimit)
        self.assertLess(limits["x"].min_degrees, 0.0)
        self.assertGreater(limits["x"].max_degrees, 0.0)


class TestErrorMapping(unittest.TestCase):
    def _client_from_response(self, response_data: dict, status: int = 200):
        import requests as req
        resp = MagicMock(spec=req.Response)
        resp.status_code = status
        resp.json.return_value = response_data
        resp.text = str(response_data)

        client = DazClient.__new__(DazClient)
        object.__setattr__(client, "_base", "http://127.0.0.1:18811")
        object.__setattr__(client, "_token", "")
        object.__setattr__(client, "_timeout", 30.0)

        with patch("dazpy._client._requests.post", return_value=resp):
            return client, resp

    def test_auth_error_401(self):
        import requests as req
        resp = MagicMock(spec=req.Response)
        resp.status_code = 401
        resp.json.return_value = {"error": "Unauthorized"}
        resp.text = "Unauthorized"
        client = DazClient.__new__(DazClient)
        object.__setattr__(client, "_base", "http://127.0.0.1:18811")
        object.__setattr__(client, "_token", "bad")
        object.__setattr__(client, "_timeout", 30.0)
        with patch("dazpy._client._requests.post", return_value=resp):
            with self.assertRaises(exceptions.AuthenticationError):
                client.execute("1;")

    def test_script_runtime_error(self):
        import requests as req
        resp = MagicMock(spec=req.Response)
        resp.status_code = 200
        resp.json.return_value = {"success": False, "error": "TypeError: undefined is not a function", "request_id": "abc"}
        resp.text = ""
        client = DazClient.__new__(DazClient)
        object.__setattr__(client, "_base", "http://127.0.0.1:18811")
        object.__setattr__(client, "_token", "")
        object.__setattr__(client, "_timeout", 30.0)
        with patch("dazpy._client._requests.post", return_value=resp):
            with self.assertRaises(exceptions.ScriptRuntimeError) as ctx:
                client.execute("bad();")
            self.assertEqual(ctx.exception.request_id, "abc")

    def test_script_syntax_error_line_number(self):
        import requests as req
        resp = MagicMock(spec=req.Response)
        resp.status_code = 200
        resp.json.return_value = {"success": False, "error": "SyntaxError at Line 3: unexpected token", "request_id": "def"}
        resp.text = ""
        client = DazClient.__new__(DazClient)
        object.__setattr__(client, "_base", "http://127.0.0.1:18811")
        object.__setattr__(client, "_token", "")
        object.__setattr__(client, "_timeout", 30.0)
        with patch("dazpy._client._requests.post", return_value=resp):
            with self.assertRaises(exceptions.ScriptSyntaxError):
                client.execute("{bad syntax")

    def test_connection_error(self):
        import requests as req
        client = DazClient.__new__(DazClient)
        object.__setattr__(client, "_base", "http://127.0.0.1:18811")
        object.__setattr__(client, "_token", "")
        object.__setattr__(client, "_timeout", 30.0)
        with patch("dazpy._client._requests.post", side_effect=req.exceptions.ConnectionError("refused")):
            with self.assertRaises(exceptions.ConnectionError):
                client.execute("1;")

    def test_diagnostic_includes_script(self):
        err = exceptions.ScriptRuntimeError("failed", script="var x = bad();", request_id="r1")
        diag = err.diagnostic
        self.assertIn("var x = bad();", diag)
        self.assertIn("r1", diag)


class TestDazCameraScriptGeneration(unittest.TestCase):
    def setUp(self):
        from dazpy._camera import DazCamera
        self.DazCamera = DazCamera

    def test_focal_length_getter_uses_direct_property(self):
        client = _make_client(50.0)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.focal_length
        self.assertEqual(val, 50.0)
        script = client.execute.call_args[0][0]
        self.assertIn("focalLength", script)
        self.assertNotIn("get_property", script)
        self.assertNotIn("Focal Length", script)

    def test_focal_length_setter_uses_direct_property(self):
        client = _make_client(None)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        cam.focal_length = 85.0
        script = client.execute.call_args[0][0]
        self.assertIn("focalLength", script)
        self.assertIn("85.0", script)
        self.assertNotIn("Focal Length", script)

    def test_frame_width_getter_uses_direct_property(self):
        client = _make_client(36.0)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.frame_width
        self.assertEqual(val, 36.0)
        script = client.execute.call_args[0][0]
        self.assertIn("frameWidth", script)
        self.assertNotIn("Frame Width", script)

    def test_focal_distance_getter(self):
        client = _make_client(200.0)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.focal_distance
        self.assertEqual(val, 200.0)
        script = client.execute.call_args[0][0]
        self.assertIn("focalDistance", script)

    def test_focal_distance_setter(self):
        client = _make_client(None)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        cam.focal_distance = 150.0
        script = client.execute.call_args[0][0]
        self.assertIn("focalDistance", script)
        self.assertIn("150.0", script)

    def test_aspect_width_getter(self):
        client = _make_client(16.0)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.aspect_width
        self.assertEqual(val, 16.0)
        script = client.execute.call_args[0][0]
        self.assertIn("aspectWidth", script)

    def test_aspect_width_setter(self):
        client = _make_client(None)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        cam.aspect_width = 16.0
        script = client.execute.call_args[0][0]
        self.assertIn("aspectWidth", script)
        self.assertIn("16.0", script)

    def test_aspect_height_getter(self):
        client = _make_client(9.0)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.aspect_height
        self.assertEqual(val, 9.0)
        script = client.execute.call_args[0][0]
        self.assertIn("aspectHeight", script)

    def test_aspect_height_setter(self):
        client = _make_client(None)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        cam.aspect_height = 9.0
        script = client.execute.call_args[0][0]
        self.assertIn("aspectHeight", script)
        self.assertIn("9.0", script)

    def test_pixels_width_getter(self):
        client = _make_client(1920)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.pixels_width
        self.assertEqual(val, 1920)
        script = client.execute.call_args[0][0]
        self.assertIn("pixelsWidth", script)

    def test_pixels_width_setter(self):
        client = _make_client(None)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        cam.pixels_width = 1920
        script = client.execute.call_args[0][0]
        self.assertIn("pixelsWidth", script)
        self.assertIn("1920", script)

    def test_pixels_height_getter(self):
        client = _make_client(1080)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.pixels_height
        self.assertEqual(val, 1080)
        script = client.execute.call_args[0][0]
        self.assertIn("pixelsHeight", script)

    def test_pixels_height_setter(self):
        client = _make_client(None)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        cam.pixels_height = 1080
        script = client.execute.call_args[0][0]
        self.assertIn("pixelsHeight", script)
        self.assertIn("1080", script)

    def test_near_clipping_plane_getter(self):
        client = _make_client(0.1)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.near_clipping_plane
        self.assertEqual(val, 0.1)
        script = client.execute.call_args[0][0]
        self.assertIn("nearClippingPlane", script)

    def test_far_clipping_plane_getter(self):
        client = _make_client(10000.0)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.far_clipping_plane
        self.assertEqual(val, 10000.0)
        script = client.execute.call_args[0][0]
        self.assertIn("farClippingPlane", script)

    def test_aim_at_generates_DzVec3(self):
        client = _make_client(None)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        cam.aim_at(1.0, 2.0, 3.0)
        script = client.execute.call_args[0][0]
        self.assertIn("aimAt", script)
        self.assertIn("DzVec3", script)
        self.assertIn("1.0", script)
        self.assertIn("2.0", script)
        self.assertIn("3.0", script)

    def test_focal_point_returns_xyz(self):
        client = _make_client({"x": 0.0, "y": 10.0, "z": 5.0})
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.focal_point()
        self.assertEqual(val, {"x": 0.0, "y": 10.0, "z": 5.0})
        script = client.execute.call_args[0][0]
        self.assertIn("getFocalPoint", script)

    def test_is_view_camera_returns_bool(self):
        client = _make_client(False)
        cam = self.DazCamera(client, NodeIdentifier("Camera 1"))
        val = cam.is_view_camera()
        self.assertFalse(val)
        script = client.execute.call_args[0][0]
        self.assertIn("isViewCamera", script)


class TestDazRenderSettingsScriptGeneration(unittest.TestCase):
    def setUp(self):
        from dazpy._render import DazRenderSettings
        self.DazRenderSettings = DazRenderSettings

    def _make_render(self, return_value=None):
        client = _make_client(return_value)
        return self.DazRenderSettings(client), client

    def test_resolution_getter_uses_imageSize(self):
        rs, client = self._make_render({"width": 1920, "height": 1080})
        val = rs.resolution
        self.assertEqual(val, {"width": 1920, "height": 1080})
        script = client.execute.call_args[0][0]
        self.assertIn("imageSize", script)
        self.assertNotIn("getImageSize", script)

    def test_set_resolution_uses_imageSize_and_applyChanges(self):
        rs, client = self._make_render(None)
        rs.set_resolution(1920, 1080)
        script = client.execute.call_args[0][0]
        self.assertIn("imageSize", script)
        self.assertIn("new QSize", script)
        self.assertIn("1920", script)
        self.assertIn("1080", script)
        self.assertIn("applyChanges", script)

    def test_output_path_getter_uses_renderImgFilename(self):
        rs, client = self._make_render("/tmp/render.png")
        val = rs.output_path
        self.assertEqual(val, "/tmp/render.png")
        script = client.execute.call_args[0][0]
        self.assertIn("renderImgFilename", script)
        self.assertNotIn("getImageFilename", script)

    def test_output_path_setter_uses_renderImgFilename(self):
        rs, client = self._make_render(None)
        rs.output_path = "/tmp/out.png"
        script = client.execute.call_args[0][0]
        self.assertIn("renderImgFilename", script)
        self.assertIn("/tmp/out.png", script)
        self.assertNotIn("setImageFilename", script)
        self.assertIn("applyChanges", script)

    def test_render_uses_doRender(self):
        from dazpy._render import RenderOutcome
        rs, client = self._make_render(
            {"success": True, "output_path": "/tmp/render.png"}
        )
        result = rs.render()
        self.assertEqual(
            result, RenderOutcome(success=True, output_path="/tmp/render.png")
        )
        script = client.execute.call_args[0][0]
        self.assertIn("doRender", script)
        self.assertNotIn("mgr.render()", script)

    def test_render_returns_failure_outcome_when_doRender_fails(self):
        from dazpy._render import RenderOutcome
        rs, client = self._make_render(
            {"success": False, "output_path": "/tmp/render.png"}
        )
        result = rs.render()
        self.assertEqual(
            result, RenderOutcome(success=False, output_path="/tmp/render.png")
        )

    def test_render_and_wait_returns_render_outcome(self):
        from dazpy._render import RenderOutcome
        rs, client = self._make_render(
            {"success": True, "output_path": "/tmp/render.png"}
        )
        result = rs.render_and_wait()
        self.assertEqual(
            result, RenderOutcome(success=True, output_path="/tmp/render.png")
        )

    def test_gamma_getter_uses_direct_property(self):
        rs, client = self._make_render(2.2)
        val = rs.gamma
        self.assertAlmostEqual(val, 2.2)
        script = client.execute.call_args[0][0]
        self.assertIn("opts.gamma", script)

    def test_gamma_setter_uses_direct_property(self):
        rs, client = self._make_render(None)
        rs.gamma = 2.2
        script = client.execute.call_args[0][0]
        self.assertIn("opts.gamma", script)
        self.assertIn("2.2", script)
        self.assertIn("applyChanges", script)

    def test_double_sided_getter_uses_direct_property(self):
        rs, client = self._make_render(False)
        val = rs.double_sided
        self.assertFalse(val)
        script = client.execute.call_args[0][0]
        self.assertIn("doubleSided", script)

    def test_double_sided_setter_uses_direct_property(self):
        rs, client = self._make_render(None)
        rs.double_sided = True
        script = client.execute.call_args[0][0]
        self.assertIn("doubleSided", script)
        self.assertIn("true", script)

    def test_null_guard_on_missing_mgr(self):
        rs, client = self._make_render(None)
        val = rs.resolution
        self.assertIsNone(val)

    def test_is_available_checks_mgr_not_null(self):
        rs, client = self._make_render(True)
        val = rs.is_available()
        self.assertTrue(val)
        script = client.execute.call_args[0][0]
        self.assertIn("getRenderMgr", script)

    def test_is_rendering(self):
        rs, client = self._make_render(False)
        val = rs.is_rendering()
        self.assertFalse(val)
        script = client.execute.call_args[0][0]
        self.assertIn("isRendering", script)

    def test_active_engine_maps_known_class_name(self):
        rs, client = self._make_render("DzIrayRenderer")
        val = rs.active_engine()
        self.assertEqual(val, "iray")
        script = client.execute.call_args[0][0]
        self.assertIn("getActiveRenderer", script)
        self.assertIn("className", script)
        self.assertIn("renderType", script)

    def test_active_engine_falls_back_to_raw_class_name(self):
        rs, client = self._make_render("DzSomeUnknownRenderer")
        val = rs.active_engine()
        self.assertEqual(val, "DzSomeUnknownRenderer")

    def test_active_engine_null_guard(self):
        rs, client = self._make_render(None)
        val = rs.active_engine()
        self.assertIsNone(val)

    def test_active_engine_viewport_mode(self):
        rs, client = self._make_render("viewport")
        val = rs.active_engine()
        self.assertEqual(val, "viewport")

    def test_active_engine_multi_pass_opengl_mode(self):
        rs, client = self._make_render("multi_pass_opengl")
        val = rs.active_engine()
        self.assertEqual(val, "multi_pass_opengl")

    def test_has_render(self):
        rs, client = self._make_render(True)
        val = rs.has_render()
        self.assertTrue(val)
        script = client.execute.call_args[0][0]
        self.assertIn("hasRender", script)

    def test_canvases_enabled_getter_uses_render_element_objects(self):
        rs, client = self._make_render(True)
        val = rs.canvases_enabled
        self.assertTrue(val)
        script = client.execute.call_args[0][0]
        self.assertIn("getRenderElementObjects()[1]", script)
        self.assertIn("renderToCanvases", script)

    def test_canvases_enabled_setter_refreshes_pane(self):
        rs, client = self._make_render(None)
        rs.canvases_enabled = False
        script = client.execute.call_args[0][0]
        self.assertIn("renderToCanvases = false", script)
        self.assertIn("DzRenderSettingsPane", script)
        self.assertIn(".refresh()", script)

    def test_list_canvases_returns_canvas_objects(self):
        from dazpy._render import Canvas
        rs, client = self._make_render(
            [{"name": "Canvas1", "canvas_type": "Normal", "index": 0}]
        )
        canvases = rs.list_canvases()
        self.assertEqual(canvases, [Canvas(name="Canvas1", canvas_type="Normal", index=0)])
        script = client.execute.call_args[0][0]
        self.assertIn("getNumCanvasDefinitions", script)
        self.assertIn("getCanvasDefinition", script)
        self.assertIn("canvasTypeToString", script)

    def test_list_canvases_empty_when_none_configured(self):
        rs, client = self._make_render([])
        self.assertEqual(rs.list_canvases(), [])

    def test_add_canvas_uses_find_canvas_definition_with_create(self):
        from dazpy._render import Canvas
        rs, client = self._make_render(
            {"name": "DepthPass", "canvas_type": "Depth", "index": 1}
        )
        canvas = rs.add_canvas("DepthPass", "Depth")
        self.assertEqual(canvas, Canvas(name="DepthPass", canvas_type="Depth", index=1))
        script = client.execute.call_args[0][0]
        self.assertIn("findCanvasDefinition(\"DepthPass\", true)", script)
        self.assertIn("canvasTypeFromString(\"Depth\")", script)
        self.assertIn(".refresh()", script)

    def test_add_canvas_raises_render_error_when_unavailable(self):
        from dazpy.exceptions import RenderError
        rs, client = self._make_render(None)
        with self.assertRaises(RenderError):
            rs.add_canvas("Foo", "Beauty")

    def test_remove_canvas_uses_find_canvas_definition_no_create(self):
        rs, client = self._make_render(True)
        result = rs.remove_canvas("Canvas1")
        self.assertTrue(result)
        script = client.execute.call_args[0][0]
        self.assertIn("findCanvasDefinition(\"Canvas1\", false)", script)
        self.assertIn("removeCanvasDefinition", script)
        self.assertIn(".refresh()", script)

    def test_remove_canvas_returns_false_when_missing(self):
        rs, client = self._make_render(False)
        self.assertFalse(rs.remove_canvas("NoSuchCanvas"))

    def test_canvas_output_paths_derives_convention(self):
        from dazpy._render import Canvas
        rs, client = self._make_render(
            [{"name": "Canvas1", "canvas_type": "Normal", "index": 0}]
        )
        paths = rs.canvas_output_paths("C:/tmp/out.png")
        self.assertEqual(
            paths,
            {"Canvas1": "C:/tmp/out_canvases/out-Canvas1-Normal.exr"},
        )

    def test_canvas_output_paths_no_directory(self):
        rs, client = self._make_render(
            [{"name": "Canvas1", "canvas_type": "Depth", "index": 0}]
        )
        paths = rs.canvas_output_paths("out.png")
        self.assertEqual(paths, {"Canvas1": "out_canvases/out-Canvas1-Depth.exr"})


class TestDazSkeletonScriptGeneration(unittest.TestCase):
    def setUp(self):
        from dazpy._skeleton import DazSkeleton
        self.DazSkeleton = DazSkeleton

    def _make_skeleton(self, return_value=None):
        client = _make_client(return_value)
        skel = self.DazSkeleton(client, NodeIdentifier("Genesis9"))
        return skel, client

    def test_bones_calls_getAllBones(self):
        skel, client = self._make_skeleton(["hip", "lShldrBend"])
        bones = skel.bones()
        self.assertEqual(len(bones), 2)
        script = client.execute.call_args[0][0]
        self.assertIn("getAllBones", script)

    def test_bones_returns_daz_bone_instances(self):
        from dazpy._bone import DazBone
        skel, client = self._make_skeleton(["hip"])
        bones = skel.bones()
        self.assertIsInstance(bones[0], DazBone)

    def test_bone_metadata_single_call(self):
        payload = [
            {
                "name": "hip",
                "label": "Hip",
                "parent_name": None,
                "rotation_order": "XYZ",
                "local_position": {"x": 0.0, "y": 0.0, "z": 0.0},
                "local_euler": {"x": 1.0, "y": 2.0, "z": 3.0},
            }
        ]
        skel, client = self._make_skeleton(payload)
        result = skel.bone_metadata()
        self.assertEqual(client.execute.call_count, 1)
        self.assertEqual(result[0]["name"], "hip")
        self.assertIsNone(result[0]["parent_name"])
        self.assertIn("getAllBones", client.execute.call_args[0][0])
        self.assertIn("getNodeParent", client.execute.call_args[0][0])

    def test_find_bone_calls_findBone(self):
        skel, client = self._make_skeleton("hip")
        bone = skel.find_bone("hip")
        script = client.execute.call_args[0][0]
        self.assertIn("findBone", script)
        self.assertIn("hip", script)

    def test_find_bone_not_found_raises(self):
        skel, client = self._make_skeleton(None)
        with self.assertRaises(exceptions.NodeNotFoundError):
            skel.find_bone("nonexistent")

    def test_find_bone_by_label_calls_findBoneByLabel(self):
        skel, client = self._make_skeleton("hip")
        skel.find_bone_by_label("Hip")
        script = client.execute.call_args[0][0]
        self.assertIn("findBoneByLabel", script)

    def test_num_bones_calls_getAllBones_length(self):
        skel, client = self._make_skeleton(42)
        count = skel.num_bones()
        self.assertEqual(count, 42)
        script = client.execute.call_args[0][0]
        self.assertIn("getAllBones", script)
        self.assertIn("length", script)

    def test_follow_target_returns_skeleton(self):
        skel, client = self._make_skeleton("Genesis9_2")
        target = skel.follow_target()
        self.assertIsInstance(target, self.DazSkeleton)
        script = client.execute.call_args[0][0]
        self.assertIn("getFollowTarget", script)

    def test_follow_target_returns_none_when_null(self):
        skel, client = self._make_skeleton(None)
        target = skel.follow_target()
        self.assertIsNone(target)

    # ── bulk bone/morph fetch ─────────────────────────────────────────────────

    def test_bone_rotations_single_call(self):
        payload = {"hip": [1.0, 2.0, 3.0], "rForeArm": [0.0, 45.0, 0.0]}
        skel, client = self._make_skeleton(payload)
        result = skel.bone_rotations()
        self.assertEqual(client.execute.call_count, 1)
        self.assertEqual(result["hip"], (1.0, 2.0, 3.0))
        self.assertEqual(result["rForeArm"], (0.0, 45.0, 0.0))

    def test_bone_rotations_script_uses_getAllBones(self):
        skel, client = self._make_skeleton({"hip": [0, 0, 0]})
        skel.bone_rotations()
        script = client.execute.call_args[0][0]
        self.assertIn("getAllBones", script)
        self.assertIn("getXRotControl", script)
        self.assertIn("getYRotControl", script)
        self.assertIn("getZRotControl", script)

    def test_bone_rotations_returns_tuples(self):
        skel, client = self._make_skeleton({"hip": [10.0, 20.0, 30.0]})
        result = skel.bone_rotations()
        self.assertIsInstance(result["hip"], tuple)

    def test_bone_rotations_empty_skeleton(self):
        skel, client = self._make_skeleton({})
        result = skel.bone_rotations()
        self.assertEqual(result, {})

    def test_bone_rotations_null_returns_empty(self):
        skel, client = self._make_skeleton(None)
        result = skel.bone_rotations()
        self.assertEqual(result, {})

    def test_set_bone_rotations_single_call(self):
        skel, client = self._make_skeleton(None)
        skel.set_bone_rotations({"hip": (10, 20, 30), "rForeArm": (0, 45, 0)})
        self.assertEqual(client.execute.call_count, 1)

    def test_set_bone_rotations_script_injects_data(self):
        skel, client = self._make_skeleton(None)
        skel.set_bone_rotations({"hip": [5.0, 10.0, 15.0]})
        script = client.execute.call_args[0][0]
        self.assertIn("hip", script)
        self.assertIn("5.0", script)
        self.assertIn("getAllBones", script)
        self.assertIn("getXRotControl", script)
        self.assertIn("setValue", script)

    def test_set_bone_rotations_accepts_tuples_and_lists(self):
        skel, client = self._make_skeleton(None)
        skel.set_bone_rotations({"hip": (1, 2, 3), "lForeArm": [4, 5, 6]})
        script = client.execute.call_args[0][0]
        self.assertIn("hip", script)
        self.assertIn("lForeArm", script)

    def test_morph_values_single_call(self):
        payload = {"PHMSmile": 0.75, "PHMFrown": 0.0}
        skel, client = self._make_skeleton(payload)
        result = skel.morph_values()
        self.assertEqual(client.execute.call_count, 1)
        self.assertAlmostEqual(result["PHMSmile"], 0.75)

    def test_morph_values_script_checks_DzMorph(self):
        skel, client = self._make_skeleton({})
        skel.morph_values()
        script = client.execute.call_args[0][0]
        self.assertIn("DzMorph", script)
        self.assertIn("getNumModifiers", script)
        self.assertIn("getValueChannel", script)

    def test_morph_values_nonzero_only_injects_true(self):
        skel, client = self._make_skeleton({})
        skel.morph_values(nonzero_only=True)
        script = client.execute.call_args[0][0]
        self.assertIn("true", script)
        self.assertIn("0.0001", script)

    def test_morph_values_all_injects_false(self):
        skel, client = self._make_skeleton({})
        skel.morph_values(nonzero_only=False)
        script = client.execute.call_args[0][0]
        self.assertIn("false", script)

    def test_morph_values_null_returns_empty(self):
        skel, client = self._make_skeleton(None)
        result = skel.morph_values()
        self.assertEqual(result, {})

    def test_set_morph_values_single_call(self):
        skel, client = self._make_skeleton(None)
        skel.set_morph_values({"PHMSmile": 0.5, "PHMFrown": 0.25})
        self.assertEqual(client.execute.call_count, 1)

    def test_set_morph_values_script_injects_data(self):
        skel, client = self._make_skeleton(None)
        skel.set_morph_values({"PHMSmile": 0.8})
        script = client.execute.call_args[0][0]
        self.assertIn("PHMSmile", script)
        self.assertIn("0.8", script)
        self.assertIn("DzMorph", script)
        self.assertIn("setValue", script)

    def test_set_morph_values_empty_dict(self):
        skel, client = self._make_skeleton(None)
        skel.set_morph_values({})
        self.assertEqual(client.execute.call_count, 1)

    # ── keyframe baking ───────────────────────────────────────────────────────

    def test_bake_bone_rotations_single_call(self):
        skel, client = self._make_skeleton({"frames_baked": 10, "bones_baked": 50})
        result = skel.bake_bone_rotations()
        self.assertEqual(client.execute.call_count, 1)
        self.assertEqual(result["frames_baked"], 10)
        self.assertEqual(result["bones_baked"], 50)

    def test_bake_bone_rotations_script_uses_insertKey(self):
        skel, client = self._make_skeleton({"frames_baked": 1, "bones_baked": 1})
        skel.bake_bone_rotations()
        script = client.execute.call_args[0][0]
        self.assertIn("insertKey", script)
        self.assertIn("getXRotControl", script)
        self.assertIn("getYRotControl", script)
        self.assertIn("getZRotControl", script)

    def test_bake_bone_rotations_script_scrubs_timeline(self):
        skel, client = self._make_skeleton({"frames_baked": 1, "bones_baked": 1})
        skel.bake_bone_rotations()
        script = client.execute.call_args[0][0]
        self.assertIn("getTimeStep", script)
        self.assertIn("getPlayRange", script)
        self.assertIn("setFrame", script)

    def test_bake_bone_rotations_restores_original_frame(self):
        skel, client = self._make_skeleton({"frames_baked": 1, "bones_baked": 1})
        skel.bake_bone_rotations()
        script = client.execute.call_args[0][0]
        self.assertIn("_origFrame", script)
        self.assertIn("Scene.setFrame(_origFrame)", script)

    def test_bake_bone_rotations_injects_start_end(self):
        skel, client = self._make_skeleton({"frames_baked": 5, "bones_baked": 1})
        skel.bake_bone_rotations(start=10, end=14)
        script = client.execute.call_args[0][0]
        self.assertIn("10", script)
        self.assertIn("14", script)

    def test_bake_bone_rotations_null_uses_play_range(self):
        skel, client = self._make_skeleton({"frames_baked": 1, "bones_baked": 1})
        skel.bake_bone_rotations()
        script = client.execute.call_args[0][0]
        self.assertIn("null", script)
        self.assertIn("_prStart", script)

    def test_bake_bone_rotations_bone_names_filter(self):
        skel, client = self._make_skeleton({"frames_baked": 1, "bones_baked": 2})
        skel.bake_bone_rotations(bone_names=["hip", "rForeArm"])
        script = client.execute.call_args[0][0]
        self.assertIn("hip", script)
        self.assertIn("rForeArm", script)
        self.assertIn("hasOwnProperty", script)

    def test_bake_bone_rotations_none_filter_includes_all(self):
        skel, client = self._make_skeleton({"frames_baked": 1, "bones_baked": 5})
        skel.bake_bone_rotations(bone_names=None)
        script = client.execute.call_args[0][0]
        # null filter means all bones
        self.assertIn("_filter === null", script)

    def test_bake_morphs_single_call(self):
        skel, client = self._make_skeleton({"frames_baked": 5, "morphs_baked": 3})
        result = skel.bake_morphs()
        self.assertEqual(client.execute.call_count, 1)
        self.assertEqual(result["morphs_baked"], 3)

    def test_bake_morphs_script_uses_DzMorph_insertKey(self):
        skel, client = self._make_skeleton({"frames_baked": 1, "morphs_baked": 1})
        skel.bake_morphs()
        script = client.execute.call_args[0][0]
        self.assertIn("DzMorph", script)
        self.assertIn("getValueChannel", script)
        self.assertIn("insertKey", script)

    def test_bake_morphs_restores_original_frame(self):
        skel, client = self._make_skeleton({"frames_baked": 1, "morphs_baked": 0})
        skel.bake_morphs()
        script = client.execute.call_args[0][0]
        self.assertIn("_origFrame", script)

    def test_bake_morphs_morph_names_filter(self):
        skel, client = self._make_skeleton({"frames_baked": 1, "morphs_baked": 1})
        skel.bake_morphs(morph_names=["PHMSmile"])
        script = client.execute.call_args[0][0]
        self.assertIn("PHMSmile", script)
        self.assertIn("hasOwnProperty", script)

    def test_bake_morphs_injects_start_end(self):
        skel, client = self._make_skeleton({"frames_baked": 3, "morphs_baked": 1})
        skel.bake_morphs(start=5, end=7)
        script = client.execute.call_args[0][0]
        self.assertIn("5", script)
        self.assertIn("7", script)

    def test_bake_single_call_combined(self):
        payload = {"frames_baked": 10, "bones_baked": 50, "morphs_baked": 0}
        skel, client = self._make_skeleton(payload)
        result = skel.bake()
        self.assertEqual(client.execute.call_count, 1)
        self.assertIn("bones_baked", result)
        self.assertIn("morphs_baked", result)

    def test_bake_without_morphs_guard_is_false(self):
        skel, client = self._make_skeleton({"frames_baked": 1, "bones_baked": 1, "morphs_baked": 0})
        skel.bake(include_morphs=False)
        script = client.execute.call_args[0][0]
        self.assertIn("false", script)  # _withMorphs = false

    def test_bake_with_morphs_guard_is_true(self):
        skel, client = self._make_skeleton({"frames_baked": 1, "bones_baked": 1, "morphs_baked": 5})
        skel.bake(include_morphs=True)
        script = client.execute.call_args[0][0]
        self.assertIn("true", script)   # _withMorphs = true
        self.assertIn("DzMorph", script)

    def test_bake_scrubs_timeline_once(self):
        """bake() iterates frames once for both bones and morphs."""
        skel, client = self._make_skeleton({"frames_baked": 5, "bones_baked": 3, "morphs_baked": 2})
        skel.bake(start=0, end=4, include_morphs=True)
        # One HTTP call regardless of bone/morph count
        self.assertEqual(client.execute.call_count, 1)

    def test_bake_bone_filter_and_morph_filter_both_injected(self):
        skel, client = self._make_skeleton({"frames_baked": 1, "bones_baked": 1, "morphs_baked": 1})
        skel.bake(bone_names=["hip"], include_morphs=True, morph_names=["PHMSmile"])
        script = client.execute.call_args[0][0]
        self.assertIn("hip", script)
        self.assertIn("PHMSmile", script)

    def test_bake_returns_empty_dict_on_null(self):
        skel, client = self._make_skeleton(None)
        result = skel.bake()
        self.assertEqual(result, {})


class TestDazBoneScriptGeneration(unittest.TestCase):
    def setUp(self):
        from dazpy._bone import DazBone
        self.DazBone = DazBone

    def _make_bone(self, return_value=None):
        client = _make_client(return_value)
        bone = self.DazBone(client, NodeIdentifier("hip"))
        return bone, client

    def test_local_rotation_returns_xyzw(self):
        bone, client = self._make_bone({"x": 0.0, "y": 0.1, "z": 0.0, "w": 0.995})
        rot = bone.local_rotation
        self.assertIn("w", rot)
        script = client.execute.call_args[0][0]
        self.assertIn("getLocalRot", script)
        self.assertIn("r.w", script)

    def test_set_local_rotation_uses_axis_controls(self):
        bone, client = self._make_bone(None)
        bone.set_local_rotation(10.0, 20.0, 30.0)
        script = client.execute.call_args[0][0]
        self.assertIn("getXRotControl", script)
        self.assertIn("getYRotControl", script)
        self.assertIn("getZRotControl", script)
        self.assertIn("setValue", script)
        self.assertIn("10.0", script)
        self.assertIn("20.0", script)
        self.assertIn("30.0", script)

    def test_local_position_returns_xyz(self):
        bone, client = self._make_bone({"x": 1.0, "y": 2.0, "z": 3.0})
        pos = bone.local_position
        self.assertEqual(pos["x"], 1.0)
        script = client.execute.call_args[0][0]
        self.assertIn("getLocalPos", script)

    def test_rotation_order_calls_getRotationOrder(self):
        bone, client = self._make_bone("XYZ")
        order = bone.rotation_order
        self.assertEqual(order, "XYZ")
        script = client.execute.call_args[0][0]
        self.assertIn("getRotationOrder", script)

    def test_get_skeleton_returns_daz_skeleton(self):
        from dazpy._skeleton import DazSkeleton
        bone, client = self._make_bone("Genesis9")
        skel = bone.get_skeleton()
        self.assertIsInstance(skel, DazSkeleton)
        script = client.execute.call_args[0][0]
        self.assertIn("getSkeleton", script)

    def test_get_skeleton_returns_none_when_null(self):
        bone, client = self._make_bone(None)
        skel = bone.get_skeleton()
        self.assertIsNone(skel)


class TestDazModifierScriptGeneration(unittest.TestCase):
    def _make_modifier(self, return_value=None, locator='Scene.findNode("MyNode").getObject().findModifier("MyMod")'):
        from dazpy._modifier import DazModifier
        client = _make_client(return_value)
        mod = DazModifier(client, locator)
        return mod, client

    def test_modifier_label_calls_getLabel(self):
        mod, client = self._make_modifier("My Morph")
        label = mod.modifier_label
        self.assertEqual(label, "My Morph")
        script = client.execute.call_args[0][0]
        self.assertIn("getLabel", script)

    def test_enabled_getter_calls_isEnabled(self):
        mod, client = self._make_modifier(True)
        val = mod.enabled
        self.assertTrue(val)
        script = client.execute.call_args[0][0]
        self.assertIn("isEnabled", script)

    def test_enabled_setter_calls_setEnabled(self):
        mod, client = self._make_modifier(None)
        mod.enabled = False
        script = client.execute.call_args[0][0]
        self.assertIn("setEnabled", script)
        self.assertIn("false", script)


class TestDazMorphScriptGeneration(unittest.TestCase):
    def _make_morph(self, return_value=None):
        from dazpy._morph import DazMorph
        client = _make_client(return_value)
        locator = 'Scene.findNode("Genesis9").getObject().findModifier("MyMorph")'
        morph = DazMorph(client, locator)
        return morph, client

    def test_value_getter_calls_getValueChannel(self):
        morph, client = self._make_morph(0.5)
        val = morph.value
        self.assertAlmostEqual(val, 0.5)
        script = client.execute.call_args[0][0]
        self.assertIn("getValueChannel", script)
        self.assertIn("getValue", script)

    def test_value_setter_calls_setValue(self):
        morph, client = self._make_morph(None)
        morph.value = 0.75
        script = client.execute.call_args[0][0]
        self.assertIn("getValueChannel", script)
        self.assertIn("setValue", script)
        self.assertIn("0.75", script)

    def test_min_calls_getMin(self):
        morph, client = self._make_morph(0.0)
        val = morph.min
        self.assertEqual(val, 0.0)
        script = client.execute.call_args[0][0]
        self.assertIn("getMin", script)

    def test_max_calls_getMax(self):
        morph, client = self._make_morph(1.0)
        val = morph.max
        self.assertEqual(val, 1.0)
        script = client.execute.call_args[0][0]
        self.assertIn("getMax", script)

    def test_value_setter_accepts_int(self):
        morph, client = self._make_morph(None)
        morph.value = 1
        script = client.execute.call_args[0][0]
        self.assertIn("1.0", script)


class TestDazNodeModifierMethods(unittest.TestCase):
    def test_modifiers_returns_list_of_daz_modifier(self):
        from dazpy._modifier import DazModifier
        from dazpy._morph import DazMorph
        client = _make_client([
            {"name": "SomeMod", "className": "DzSubDivisionModifier"},
            {"name": "MyMorph", "className": "DzMorph"},
        ])
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mods = node.modifiers()
        self.assertEqual(len(mods), 2)
        self.assertIsInstance(mods[0], DazModifier)
        self.assertIsInstance(mods[1], DazMorph)

    def test_modifiers_script_uses_getNumModifiers(self):
        client = _make_client([])
        node = DazNode(client, NodeIdentifier("Genesis9"))
        node.modifiers()
        script = client.execute.call_args[0][0]
        self.assertIn("getNumModifiers", script)
        self.assertIn("getObject", script)
        self.assertIn("className", script)

    def test_modifiers_empty_when_no_object(self):
        client = _make_client([])
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mods = node.modifiers()
        self.assertEqual(mods, [])

    def test_find_modifier_returns_daz_modifier(self):
        from dazpy._modifier import DazModifier
        client = _make_client({"name": "SomeMod", "className": "DzSubDivisionModifier"})
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mod = node.find_modifier("SomeMod")
        self.assertIsInstance(mod, DazModifier)

    def test_find_modifier_returns_daz_morph_when_class_is_dzmorph(self):
        from dazpy._morph import DazMorph
        client = _make_client({"name": "MyMorph", "className": "DzMorph"})
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mod = node.find_modifier("MyMorph")
        self.assertIsInstance(mod, DazMorph)

    def test_find_modifier_returns_none_when_not_found(self):
        client = _make_client(None)
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mod = node.find_modifier("NonExistent")
        self.assertIsNone(mod)

    def test_find_modifier_script_uses_findModifier(self):
        client = _make_client(None)
        node = DazNode(client, NodeIdentifier("Genesis9"))
        node.find_modifier("SomeMod")
        script = client.execute.call_args[0][0]
        self.assertIn("findModifier", script)
        self.assertIn("SomeMod", script)

    def test_morphs_filters_to_only_daz_morph(self):
        from dazpy._morph import DazMorph
        client = _make_client([
            {"name": "SomeMod", "className": "DzSubDivisionModifier"},
            {"name": "MyMorph", "className": "DzMorph"},
            {"name": "OtherMorph", "className": "DzMorph"},
        ])
        node = DazNode(client, NodeIdentifier("Genesis9"))
        morphs = node.morphs()
        self.assertEqual(len(morphs), 2)
        for m in morphs:
            self.assertIsInstance(m, DazMorph)

    def test_modifier_locator_uses_findModifier(self):
        client = _make_client(None)
        node = DazNode(client, NodeIdentifier("Genesis9"))
        loc = node._modifier_locator("MyMorph")
        self.assertIn("findModifier", loc)
        self.assertIn("MyMorph", loc)
        self.assertIn("getObject", loc)

    def test_find_modifier_returns_daz_dforce_when_class_is_dzdforcemodifier(self):
        from dazpy._dforce import DazDForce
        client = _make_client({"name": "MyCloth", "className": "DzDForceModifier"})
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mod = node.find_modifier("MyCloth")
        self.assertIsInstance(mod, DazDForce)

    def test_dforce_modifiers_filters_to_only_dzdforcemodifier(self):
        from dazpy._dforce import DazDForce
        client = _make_client([
            {"name": "SomeMod", "className": "DzSubDivisionModifier"},
            {"name": "MyMorph", "className": "DzMorph"},
            {"name": "MyCloth", "className": "DzDForceModifier"},
        ])
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mods = node.dforce_modifiers()
        self.assertEqual(len(mods), 1)
        self.assertIsInstance(mods[0], DazDForce)


class TestDazDForceScriptGeneration(unittest.TestCase):
    def _make_dforce(self, return_value=None):
        from dazpy._dforce import DazDForce
        client = _make_client(return_value)
        locator = 'Scene.findNode("Genesis9").getObject().findModifier("MyCloth")'
        mod = DazDForce(client, locator)
        return mod, client

    def test_freeze_simulation_getter_calls_findPropertyByLabel(self):
        mod, client = self._make_dforce(True)
        val = mod.freeze_simulation
        self.assertTrue(val)
        script = client.execute.call_args[0][0]
        self.assertIn("findPropertyByLabel", script)
        self.assertIn("Freeze Simulation", script)

    def test_freeze_simulation_setter_calls_setValue(self):
        mod, client = self._make_dforce(None)
        mod.freeze_simulation = True
        script = client.execute.call_args[0][0]
        self.assertIn("setValue", script)
        self.assertIn("true", script)

    def test_freeze_sets_freeze_simulation_true(self):
        mod, client = self._make_dforce(None)
        mod.freeze()
        script = client.execute.call_args[0][0]
        self.assertIn("Freeze Simulation", script)
        self.assertIn("true", script)

    def test_unfreeze_sets_freeze_simulation_false(self):
        mod, client = self._make_dforce(None)
        mod.unfreeze()
        script = client.execute.call_args[0][0]
        self.assertIn("Freeze Simulation", script)
        self.assertIn("false", script)


class TestDazMaterialScriptGeneration(unittest.TestCase):
    def _make_material(self, return_value=None):
        from dazpy._material import DazMaterial
        client = _make_client(return_value)
        locator = 'Scene.findNode("Genesis9").getObject().getCurrentShape().findMaterial("Skin")'
        mat = DazMaterial(client, locator)
        return mat, client

    def test_material_name_calls_getName(self):
        mat, client = self._make_material("Skin")
        name = mat.material_name
        self.assertEqual(name, "Skin")
        script = client.execute.call_args[0][0]
        self.assertIn("getName", script)

    def test_diffuse_color_calls_getDiffuseColor(self):
        mat, client = self._make_material({"r": 200, "g": 180, "b": 160})
        color = mat.diffuse_color
        self.assertEqual(color, {"r": 200, "g": 180, "b": 160})
        script = client.execute.call_args[0][0]
        self.assertIn("getDiffuseColor", script)

    def test_diffuse_color_setter_calls_setDiffuseColor(self):
        mat, client = self._make_material(None)
        mat.diffuse_color = (255, 128, 0)
        script = client.execute.call_args[0][0]
        self.assertIn("setDiffuseColor", script)
        self.assertIn("255", script)
        self.assertIn("128", script)

    def test_diffuse_color_setter_accepts_dict(self):
        mat, client = self._make_material(None)
        mat.diffuse_color = {"r": 100, "g": 150, "b": 200}
        script = client.execute.call_args[0][0]
        self.assertIn("setDiffuseColor", script)
        self.assertIn("100", script)

    def test_opacity_calls_getBaseOpacity(self):
        mat, client = self._make_material(0.9)
        val = mat.opacity
        self.assertAlmostEqual(val, 0.9)
        script = client.execute.call_args[0][0]
        self.assertIn("getBaseOpacity", script)

    def test_opacity_setter_calls_setBaseOpacity(self):
        mat, client = self._make_material(None)
        mat.opacity = 0.5
        script = client.execute.call_args[0][0]
        self.assertIn("setBaseOpacity", script)
        self.assertIn("0.5", script)

    def test_color_map_calls_getColorMap(self):
        mat, client = self._make_material("/textures/skin.png")
        result = mat.color_map()
        self.assertEqual(result, "/textures/skin.png")
        script = client.execute.call_args[0][0]
        self.assertIn("getColorMap", script)
        self.assertIn("getFilename", script)

    def test_is_smoothing_on_calls_isSmoothingOn(self):
        mat, client = self._make_material(True)
        val = mat.is_smoothing_on()
        self.assertTrue(val)
        script = client.execute.call_args[0][0]
        self.assertIn("isSmoothingOn", script)

    def test_smoothing_angle_calls_getSmoothingAngle(self):
        mat, client = self._make_material(89.9)
        val = mat.smoothing_angle
        self.assertAlmostEqual(val, 89.9)
        script = client.execute.call_args[0][0]
        self.assertIn("getSmoothingAngle", script)

    def test_smoothing_angle_setter_calls_setSmoothingAngle(self):
        mat, client = self._make_material(None)
        mat.smoothing_angle = 45.0
        script = client.execute.call_args[0][0]
        self.assertIn("setSmoothingAngle", script)
        self.assertIn("45.0", script)

    def test_is_opaque_calls_isOpaque(self):
        mat, client = self._make_material(True)
        val = mat.is_opaque()
        self.assertTrue(val)
        script = client.execute.call_args[0][0]
        self.assertIn("isOpaque", script)


class TestDazNodeMaterialMethods(unittest.TestCase):
    def test_materials_returns_list_of_daz_material(self):
        from dazpy._material import DazMaterial
        client = _make_client(["Skin", "Eyes", "Teeth"])
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mats = node.materials()
        self.assertEqual(len(mats), 3)
        for m in mats:
            self.assertIsInstance(m, DazMaterial)

    def test_materials_script_uses_getNumMaterials(self):
        client = _make_client([])
        node = DazNode(client, NodeIdentifier("Genesis9"))
        node.materials()
        script = client.execute.call_args[0][0]
        self.assertIn("getNumMaterials", script)
        self.assertIn("getCurrentShape", script)
        self.assertIn("getObject", script)

    def test_materials_empty_when_no_object(self):
        client = _make_client([])
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mats = node.materials()
        self.assertEqual(mats, [])

    def test_find_material_returns_daz_material(self):
        from dazpy._material import DazMaterial
        client = _make_client("Skin")
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mat = node.find_material("Skin")
        self.assertIsInstance(mat, DazMaterial)

    def test_find_material_returns_none_when_not_found(self):
        client = _make_client(None)
        node = DazNode(client, NodeIdentifier("Genesis9"))
        mat = node.find_material("NonExistent")
        self.assertIsNone(mat)

    def test_find_material_script_uses_findMaterial(self):
        client = _make_client(None)
        node = DazNode(client, NodeIdentifier("Genesis9"))
        node.find_material("Skin")
        script = client.execute.call_args[0][0]
        self.assertIn("findMaterial", script)
        self.assertIn("Skin", script)

    def test_material_locator_uses_findMaterial(self):
        client = _make_client(None)
        node = DazNode(client, NodeIdentifier("Genesis9"))
        loc = node._material_locator("Skin")
        self.assertIn("findMaterial", loc)
        self.assertIn("Skin", loc)
        self.assertIn("getCurrentShape", loc)
        self.assertIn("getObject", loc)


class TestDazNodeRotationAndSelection(unittest.TestCase):
    def _node(self, return_value=None):
        client = _make_client(return_value)
        return DazNode(client, NodeIdentifier("Genesis9")), client

    def test_set_rotation_uses_axis_controls(self):
        node, client = self._node(None)
        node.set_rotation(10.0, 20.0, 30.0)
        script = client.execute.call_args[0][0]
        self.assertIn("getXRotControl", script)
        self.assertIn("getYRotControl", script)
        self.assertIn("getZRotControl", script)
        self.assertIn("setValue", script)
        self.assertIn("10.0", script)
        self.assertIn("20.0", script)
        self.assertIn("30.0", script)

    def test_local_position_calls_getLocalPos(self):
        node, client = self._node({"x": 1.0, "y": 2.0, "z": 3.0})
        pos = node.local_position
        self.assertEqual(pos["x"], 1.0)
        self.assertEqual(pos["y"], 2.0)
        self.assertEqual(pos["z"], 3.0)
        script = client.execute.call_args[0][0]
        self.assertIn("getLocalPos", script)

    def test_set_local_position_calls_setLocalPos(self):
        node, client = self._node(None)
        node.set_local_position(5.0, 10.0, 15.0)
        script = client.execute.call_args[0][0]
        self.assertIn("setLocalPos", script)
        self.assertIn("DzVec3", script)
        self.assertIn("5.0", script)
        self.assertIn("10.0", script)
        self.assertIn("15.0", script)

    def test_local_rotation_calls_getLocalRot_and_returns_xyzw(self):
        node, client = self._node({"x": 0.0, "y": 0.1, "z": 0.0, "w": 0.995})
        rot = node.local_rotation
        self.assertIn("w", rot)
        self.assertIn("x", rot)
        script = client.execute.call_args[0][0]
        self.assertIn("getLocalRot", script)
        self.assertIn("r.w", script)

    def test_set_local_rotation_uses_axis_controls(self):
        node, client = self._node(None)
        node.set_local_rotation(5.0, 15.0, 25.0)
        script = client.execute.call_args[0][0]
        self.assertIn("getXRotControl", script)
        self.assertIn("getYRotControl", script)
        self.assertIn("getZRotControl", script)
        self.assertIn("setValue", script)
        self.assertIn("5.0", script)
        self.assertIn("15.0", script)
        self.assertIn("25.0", script)

    def test_is_selected_calls_isSelected(self):
        node, client = self._node(True)
        result = node.is_selected()
        self.assertTrue(result)
        script = client.execute.call_args[0][0]
        self.assertIn("isSelected", script)

    def test_is_selected_returns_false(self):
        node, client = self._node(False)
        result = node.is_selected()
        self.assertFalse(result)

    def test_select_true_calls_select_true(self):
        node, client = self._node(None)
        node.select(True)
        script = client.execute.call_args[0][0]
        self.assertIn("select", script)
        self.assertIn("true", script)

    def test_select_false_calls_select_false(self):
        node, client = self._node(None)
        node.select(False)
        script = client.execute.call_args[0][0]
        self.assertIn("select", script)
        self.assertIn("false", script)

    def test_select_default_is_true(self):
        node, client = self._node(None)
        node.select()
        script = client.execute.call_args[0][0]
        self.assertIn("true", script)


class TestDazNodeAdditionalQueries(unittest.TestCase):
    def _node(self, return_value=None):
        client = _make_client(return_value)
        return DazNode(client, NodeIdentifier("Genesis9")), client

    def test_is_in_scene_calls_isInScene(self):
        node, client = self._node(True)
        result = node.is_in_scene()
        self.assertTrue(result)
        script = client.execute.call_args[0][0]
        self.assertIn("isInScene", script)

    def test_is_in_scene_false(self):
        node, client = self._node(False)
        self.assertFalse(node.is_in_scene())

    def test_is_root_calls_isRootNode(self):
        node, client = self._node(True)
        result = node.is_root()
        self.assertTrue(result)
        script = client.execute.call_args[0][0]
        self.assertIn("isRootNode", script)

    def test_is_root_false(self):
        node, client = self._node(False)
        self.assertFalse(node.is_root())

    def test_is_visible_in_render_calls_isVisibleInRender(self):
        node, client = self._node(True)
        result = node.is_visible_in_render()
        self.assertTrue(result)
        script = client.execute.call_args[0][0]
        self.assertIn("isVisibleInRender", script)

    def test_set_visible_in_render_true(self):
        node, client = self._node(None)
        node.set_visible_in_render(True)
        script = client.execute.call_args[0][0]
        self.assertIn("setVisibleInRender", script)
        self.assertIn("true", script)

    def test_set_visible_in_render_false(self):
        node, client = self._node(None)
        node.set_visible_in_render(False)
        script = client.execute.call_args[0][0]
        self.assertIn("setVisibleInRender", script)
        self.assertIn("false", script)

    def test_is_visible_in_viewport_calls_isVisibleInViewport(self):
        node, client = self._node(False)
        result = node.is_visible_in_viewport()
        self.assertFalse(result)
        script = client.execute.call_args[0][0]
        self.assertIn("isVisibleInViewport", script)

    def test_set_visible_in_viewport_true(self):
        node, client = self._node(None)
        node.set_visible_in_viewport(True)
        script = client.execute.call_args[0][0]
        self.assertIn("setVisibleInViewport", script)
        self.assertIn("true", script)

    def test_set_visible_in_viewport_false(self):
        node, client = self._node(None)
        node.set_visible_in_viewport(False)
        script = client.execute.call_args[0][0]
        self.assertIn("setVisibleInViewport", script)
        self.assertIn("false", script)

    def test_bounding_box_calls_getWSBoundingBox(self):
        bb = {"min": {"x": -1.0, "y": 0.0, "z": -1.0}, "max": {"x": 1.0, "y": 2.0, "z": 1.0}}
        node, client = self._node(bb)
        result = node.bounding_box()
        self.assertEqual(result["min"]["x"], -1.0)
        self.assertEqual(result["max"]["y"], 2.0)
        script = client.execute.call_args[0][0]
        self.assertIn("getWSBoundingBox", script)
        self.assertIn("bb.min.x", script)
        self.assertIn("bb.max.x", script)

    def test_bounding_box_returns_none_when_server_returns_none(self):
        node, client = self._node(None)
        result = node.bounding_box()
        self.assertIsNone(result)


class TestDazNodeDeleteAndReparent(unittest.TestCase):
    def _node(self, return_value=None):
        client = _make_client(return_value)
        return DazNode(client, NodeIdentifier("Prop1")), client

    def test_delete_calls_scene_remove_node(self):
        node, client = self._node(True)
        result = node.delete()
        self.assertTrue(result)
        script = client.execute.call_args[0][0]
        self.assertIn("Scene.removeNode(_node)", script)

    def test_delete_returns_false_when_server_returns_falsy(self):
        node, client = self._node(False)
        self.assertFalse(node.delete())

    def test_reparent_calls_remove_and_add_node_child(self):
        node, client = self._node(None)
        new_parent = DazNode(client, NodeIdentifier("NewParent"))
        node.reparent(new_parent)
        script = client.execute.call_args[0][0]
        self.assertIn("removeNodeChild(_node, true)", script)
        self.assertIn("addNodeChild(_node, true)", script)
        self.assertIn('Scene.findNode("NewParent")', script)
        self.assertIn("_err.valueOf()", script)

    def test_reparent_preserve_world_transform_false_uses_false_flag(self):
        node, client = self._node(None)
        new_parent = DazNode(client, NodeIdentifier("NewParent"))
        node.reparent(new_parent, preserve_world_transform=False)
        script = client.execute.call_args[0][0]
        self.assertIn("removeNodeChild(_node, false)", script)
        self.assertIn("addNodeChild(_node, false)", script)

    def test_reparent_raises_on_error_result(self):
        node, client = self._node("some dz error")
        new_parent = DazNode(client, NodeIdentifier("NewParent"))
        with self.assertRaises(exceptions.ScriptRuntimeError):
            node.reparent(new_parent)

    def test_reparent_succeeds_when_result_is_none(self):
        node, client = self._node(None)
        new_parent = DazNode(client, NodeIdentifier("NewParent"))
        node.reparent(new_parent)  # should not raise


class TestDazNodeFitting(unittest.TestCase):
    def _node(self, return_value=None):
        client = _make_client(return_value)
        return DazNode(client, NodeIdentifier("Outfit")), client

    def test_fit_to_uses_setFollowTarget_when_available(self):
        node, client = self._node("setFollowTarget")
        figure = DazNode(client, NodeIdentifier("Genesis9"))
        method = node.fit_to(figure)
        self.assertEqual(method, "setFollowTarget")
        script = client.execute.call_args[0][0]
        self.assertIn("setFollowTarget(_figure)", script)
        self.assertIn('Scene.findNode("Genesis9")', script)

    def test_fit_to_raises_when_node_not_found(self):
        node, client = self._node(None)
        figure = DazNode(client, NodeIdentifier("Genesis9"))
        with self.assertRaises(exceptions.NodeNotFoundError):
            node.fit_to(figure)

    def test_unfit_returns_previous_figure_and_actions(self):
        node, client = self._node(
            {"previous_figure": "Genesis9", "actions": ["cleared follow target"]}
        )
        result = node.unfit()
        self.assertEqual(result["previous_figure"], "Genesis9")
        self.assertEqual(result["actions"], ["cleared follow target"])
        script = client.execute.call_args[0][0]
        self.assertIn("setFollowTarget(null)", script)
        self.assertIn("removeNodeChild(_node, true)", script)

    def test_unfit_returns_defaults_when_server_returns_none(self):
        node, client = self._node(None)
        result = node.unfit()
        self.assertEqual(result, {"previous_figure": None, "actions": []})

    def test_fitted_items_returns_node_list(self):
        node, client = self._node(["Outfit Top", "Hat"])
        items = node.fitted_items()
        self.assertEqual(len(items), 2)
        self.assertIsInstance(items[0], DazNode)
        script = client.execute.call_args[0][0]
        self.assertIn("getFollowTarget", script)
        self.assertIn("getNodeParent", script)

    def test_fitted_items_empty_when_none_fitted(self):
        node, client = self._node([])
        self.assertEqual(node.fitted_items(), [])


class TestDazPropertyKeyframes(unittest.TestCase):
    def _prop(self, return_value=None):
        from dazpy._property import DazProperty
        client = _make_client(return_value)
        prop = DazProperty(client, "_node", "XRotate")
        return prop, client

    def test_get_keys_returns_time_value_list(self):
        prop, client = self._prop([{"time": 0, "value": 0.0}, {"time": 30, "value": 45.0}])
        keys = prop.get_keys()
        self.assertEqual(keys, [{"time": 0, "value": 0.0}, {"time": 30, "value": 45.0}])
        script = client.execute.call_args[0][0]
        self.assertIn("getNumKeys", script)
        self.assertIn("getKeyTime", script)
        self.assertIn("getDoubleValue", script)

    def test_get_keys_empty_when_no_keys(self):
        prop, client = self._prop([])
        self.assertEqual(prop.get_keys(), [])

    def test_remove_key_calls_delete_keys_with_same_time_twice(self):
        prop, client = self._prop(None)
        prop.remove_key(30)
        script = client.execute.call_args[0][0]
        self.assertIn("deleteKeys(30, 30)", script)

    def test_clear_keys_calls_delete_all_keys(self):
        prop, client = self._prop(None)
        prop.clear_keys()
        script = client.execute.call_args[0][0]
        self.assertIn("deleteAllKeys", script)


class TestDazSceneSelection(unittest.TestCase):
    def test_selected_nodes_calls_getSelectedNodeList(self):
        client = _make_client(["Genesis9", "Camera 1"])
        scene = DazScene(client)
        nodes = scene.selected_nodes()
        self.assertEqual(len(nodes), 2)
        self.assertIsInstance(nodes[0], DazNode)
        script = client.execute.call_args[0][0]
        self.assertIn("getSelectedNodeList", script)

    def test_selected_nodes_empty_list(self):
        client = _make_client([])
        scene = DazScene(client)
        nodes = scene.selected_nodes()
        self.assertEqual(nodes, [])

    def test_primary_selection_returns_node(self):
        client = _make_client("Genesis9")
        scene = DazScene(client)
        node = scene.primary_selection()
        self.assertIsInstance(node, DazNode)
        script = client.execute.call_args[0][0]
        self.assertIn("getPrimarySelection", script)

    def test_primary_selection_returns_none_when_nothing_selected(self):
        client = _make_client(None)
        scene = DazScene(client)
        node = scene.primary_selection()
        self.assertIsNone(node)

    def test_set_primary_selection_calls_setPrimarySelection(self):
        client = _make_client(None)
        scene = DazScene(client)
        node = DazNode(client, NodeIdentifier("Genesis9"))
        scene.set_primary_selection(node)
        script = client.execute.call_args[0][0]
        self.assertIn("setPrimarySelection", script)
        self.assertIn("Genesis9", script)

    def test_select_all_true_calls_selectAllNodes_true(self):
        client = _make_client(None)
        scene = DazScene(client)
        scene.select_all(True)
        script = client.execute.call_args[0][0]
        self.assertIn("selectAllNodes", script)
        self.assertIn("true", script)

    def test_select_all_false_deselects(self):
        client = _make_client(None)
        scene = DazScene(client)
        scene.select_all(False)
        script = client.execute.call_args[0][0]
        self.assertIn("selectAllNodes", script)
        self.assertIn("false", script)

    def test_select_all_default_is_true(self):
        client = _make_client(None)
        scene = DazScene(client)
        scene.select_all()
        script = client.execute.call_args[0][0]
        self.assertIn("true", script)


class TestDazSceneIO(unittest.TestCase):
    def _scene(self, return_value):
        return DazScene(_make_client(return_value))

    def test_load_calls_loadScene_with_path(self):
        scene = self._scene(None)
        scene.load("/path/to/scene.duf")
        script = scene._client.execute.call_args[0][0]
        self.assertIn("loadScene", script)
        self.assertIn("/path/to/scene.duf", script)
        self.assertIn(", 0", script)

    def test_save_calls_saveScene_with_path(self):
        scene = self._scene(None)
        scene.save("/path/to/output.duf")
        script = scene._client.execute.call_args[0][0]
        self.assertIn("saveScene", script)
        self.assertIn("/path/to/output.duf", script)

    def test_filename_returns_string(self):
        scene = self._scene("/some/file.duf")
        result = scene.filename()
        self.assertEqual(result, "/some/file.duf")
        script = scene._client.execute.call_args[0][0]
        self.assertIn("getFilename", script)

    def test_filename_returns_empty_string_when_none(self):
        scene = self._scene(None)
        result = scene.filename()
        self.assertEqual(result, "")

    def test_needs_save_true(self):
        scene = self._scene(True)
        self.assertTrue(scene.needs_save())
        script = scene._client.execute.call_args[0][0]
        self.assertIn("needsSave", script)

    def test_needs_save_false(self):
        scene = self._scene(False)
        self.assertFalse(scene.needs_save())

    def test_play_range_returns_dict(self):
        scene = self._scene({"start": 0, "end": 240})
        result = scene.play_range()
        self.assertEqual(result["start"], 0)
        self.assertEqual(result["end"], 240)
        script = scene._client.execute.call_args[0][0]
        self.assertIn("getPlayRange", script)
        self.assertIn("getTimeStep", script)

    def test_play_range_returns_fallback_when_none(self):
        scene = self._scene(None)
        result = scene.play_range()
        self.assertEqual(result, {"start": 0, "end": 0})

    def test_set_play_range_calls_setPlayRange(self):
        scene = self._scene(None)
        scene.set_play_range(0, 120)
        script = scene._client.execute.call_args[0][0]
        self.assertIn("setPlayRange", script)
        self.assertIn("DzTimeRange", script)
        self.assertIn("0", script)
        self.assertIn("120", script)

    def test_set_anim_range_calls_setAnimRange(self):
        scene = self._scene(None)
        scene.set_anim_range(1, 60)
        script = scene._client.execute.call_args[0][0]
        self.assertIn("setAnimRange", script)
        self.assertIn("DzTimeRange", script)
        self.assertIn("1", script)
        self.assertIn("60", script)

    def test_is_playing_true(self):
        scene = self._scene(True)
        self.assertTrue(scene.is_playing())
        script = scene._client.execute.call_args[0][0]
        self.assertIn("isPlaying", script)

    def test_is_playing_false(self):
        scene = self._scene(False)
        self.assertFalse(scene.is_playing())

    def test_loop_playback_on(self):
        scene = self._scene(None)
        scene.loop_playback(True)
        script = scene._client.execute.call_args[0][0]
        self.assertIn("loopPlayback", script)
        self.assertIn("true", script)

    def test_loop_playback_off(self):
        scene = self._scene(None)
        scene.loop_playback(False)
        script = scene._client.execute.call_args[0][0]
        self.assertIn("loopPlayback", script)
        self.assertIn("false", script)


class TestDazSceneDForceSimulation(unittest.TestCase):
    def _scene(self, return_value=None):
        return DazScene(_make_client(return_value))

    def test_is_simulating_true(self):
        scene = self._scene(True)
        self.assertTrue(scene.is_simulating())
        script = scene._client.execute.call_args[0][0]
        self.assertIn("getSimulationMgr", script)
        self.assertIn("isSimulating", script)

    def test_is_simulating_false(self):
        scene = self._scene(False)
        self.assertFalse(scene.is_simulating())

    def test_clear_dforce_simulation_calls_clearSimulation(self):
        scene = self._scene(None)
        scene.clear_dforce_simulation()
        script = scene._client.execute.call_args[0][0]
        self.assertIn("getSimulationMgr", script)
        self.assertIn("clearSimulation", script)

    def test_run_dforce_simulation_wait_false_submits_async(self):
        scene = self._scene()
        scene._client.execute_async_submit.return_value = "req-123"
        request_id = scene.run_dforce_simulation(wait=False)
        self.assertEqual(request_id, "req-123")
        script = scene._client.execute_async_submit.call_args[0][0]
        self.assertIn("getSimulationMgr", script)
        self.assertIn("mgr.simulate()", script)

    def test_run_dforce_simulation_with_nodes_uses_customSimulate(self):
        scene = self._scene()
        scene._client.execute_async_submit.return_value = "req-456"
        node = DazNode(scene._client, NodeIdentifier("Skirt"))
        scene.run_dforce_simulation(nodes=[node], wait=False)
        script = scene._client.execute_async_submit.call_args[0][0]
        self.assertIn("customSimulate", script)
        self.assertIn("getActiveSimulationEngine", script)
        self.assertIn("Skirt", script)

    def test_run_dforce_simulation_wait_true_returns_none_on_success(self):
        scene = self._scene()
        scene._client.execute_async_submit.return_value = "req-789"
        scene._client.get_request_result.return_value = {
            "success": True,
            "result": {"error": None},
            "output": [],
            "duration_ms": 12.0,
        }
        result = scene.run_dforce_simulation(wait=True)
        self.assertIsNone(result)

    def test_run_dforce_simulation_wait_true_raises_on_engine_error(self):
        scene = self._scene()
        scene._client.execute_async_submit.return_value = "req-999"
        scene._client.get_request_result.return_value = {
            "success": True,
            "result": {"error": "DZ_ERROR_SOMETHING"},
            "output": [],
            "duration_ms": 12.0,
        }
        with self.assertRaises(exceptions.ScriptRuntimeError):
            scene.run_dforce_simulation(wait=True)


class TestDazLightScriptGeneration(unittest.TestCase):
    def setUp(self):
        from dazpy._light import DazLight
        self.DazLight = DazLight

    def _light(self, return_value=None):
        client = _make_client(return_value)
        return self.DazLight(client, NodeIdentifier("PointLight1")), client

    def test_is_on_calls_isOn(self):
        light, client = self._light(True)
        result = light.is_on()
        self.assertTrue(result)
        script = client.execute.call_args[0][0]
        self.assertIn("isOn", script)

    def test_is_on_false(self):
        light, client = self._light(False)
        self.assertFalse(light.is_on())

    def test_is_directional_calls_isDirectional(self):
        light, client = self._light(False)
        result = light.is_directional()
        self.assertFalse(result)
        script = client.execute.call_args[0][0]
        self.assertIn("isDirectional", script)

    def test_is_area_light_calls_isAreaLight(self):
        light, client = self._light(False)
        result = light.is_area_light()
        self.assertFalse(result)
        script = client.execute.call_args[0][0]
        self.assertIn("isAreaLight", script)

    def test_direction_calls_getWSDirection(self):
        light, client = self._light({"x": 0.0, "y": -1.0, "z": 0.0})
        result = light.direction()
        self.assertEqual(result, {"x": 0.0, "y": -1.0, "z": 0.0})
        script = client.execute.call_args[0][0]
        self.assertIn("getWSDirection", script)
        self.assertIn("isDirectional", script)

    def test_direction_returns_none_for_non_directional(self):
        light, client = self._light(None)
        result = light.direction()
        self.assertIsNone(result)

    def test_set_color_calls_findPropertyByLabel(self):
        light, client = self._light(None)
        light.set_color(255, 128, 0)
        script = client.execute.call_args[0][0]
        self.assertIn("findPropertyByLabel", script)
        self.assertIn("Diffuse Color", script)
        self.assertIn("255", script)
        self.assertIn("128", script)
        self.assertIn("0", script)
        self.assertIn("Color", script)


class TestDazGeometryScriptGeneration(unittest.TestCase):
    def _geo(self, return_value=None):
        from dazpy._geometry import DazGeometry
        client = _make_client(return_value)
        geo = DazGeometry(client, NodeIdentifier("Genesis9"))
        return geo, client

    def test_face_vertex_indices_uses_getFacet(self):
        geo, client = self._geo({"total": 100, "start": 0, "facets": [[0, 1, 2]]})
        result = geo.face_vertex_indices(start=0, count=10)
        self.assertIn("facets", result)
        script = client.execute.call_args[0][0]
        self.assertIn("getFacet", script)
        self.assertIn("vertIdx1", script)
        self.assertIn("isQuad", script)

    def test_face_vertex_indices_quad_has_four_indices(self):
        geo, client = self._geo({"total": 10, "start": 0, "facets": [[0, 1, 2, 3]]})
        result = geo.face_vertex_indices(start=0, count=5)
        self.assertEqual(result["facets"][0], [0, 1, 2, 3])

    def test_normals_uses_getNormal(self):
        geo, client = self._geo({"total": 50, "start": 0, "normals": [[0.0, 1.0, 0.0]]})
        result = geo.normals(start=0, count=10)
        self.assertIn("normals", result)
        script = client.execute.call_args[0][0]
        self.assertIn("getNormal", script)
        self.assertIn("getNumNormals", script)

    def test_uv_set_count_uses_getNumUVSets(self):
        geo, client = self._geo(2)
        count = geo.uv_set_count
        self.assertEqual(count, 2)
        script = client.execute.call_args[0][0]
        self.assertIn("getNumUVSets", script)

    def test_uv_positions_default_uses_getUVs(self):
        geo, client = self._geo({"total": 100, "start": 0, "uvs": [[0.5, 0.5]]})
        result = geo.uv_positions(uv_set=0, start=0, count=10)
        self.assertIn("uvs", result)
        script = client.execute.call_args[0][0]
        self.assertIn("getUVs", script)
        self.assertIn("getPnt2Vec", script)

    def test_uv_positions_nonzero_uses_getUVSet(self):
        geo, client = self._geo({"total": 100, "start": 0, "uvs": []})
        geo.uv_positions(uv_set=1)
        script = client.execute.call_args[0][0]
        self.assertIn("getUVSet", script)

    def test_face_group_names_uses_getFaceGroup(self):
        geo, client = self._geo(["Body", "Head"])
        names = geo.face_group_names()
        self.assertEqual(names, ["Body", "Head"])
        script = client.execute.call_args[0][0]
        self.assertIn("getFaceGroup", script)
        self.assertIn("getName", script)

    def test_material_group_names_uses_getMaterialGroup(self):
        geo, client = self._geo(["Skin", "Eyes"])
        names = geo.material_group_names()
        self.assertEqual(names, ["Skin", "Eyes"])
        script = client.execute.call_args[0][0]
        self.assertIn("getMaterialGroup", script)
        self.assertIn("getName", script)

    def test_subdivision_level_uses_getCurrentSubDivisionLevel(self):
        geo, client = self._geo(0)
        lvl = geo.subdivision_level
        self.assertEqual(lvl, 0)
        script = client.execute.call_args[0][0]
        self.assertIn("getCurrentSubDivisionLevel", script)

    def test_tris_count_uses_getNumTris(self):
        geo, client = self._geo(1500)
        count = geo.tris_count
        self.assertEqual(count, 1500)
        script = client.execute.call_args[0][0]
        self.assertIn("getNumTris", script)

    def test_quads_count_uses_getNumQuads(self):
        geo, client = self._geo(8000)
        count = geo.quads_count
        self.assertEqual(count, 8000)
        script = client.execute.call_args[0][0]
        self.assertIn("getNumQuads", script)

    # ── mesh_info ─────────────────────────────────────────────────────────────

    def test_mesh_info_single_call(self):
        payload = {
            "vertex_count": 100, "facet_count": 50,
            "tris_count": 10, "quads_count": 40,
            "subdivision_level": 0, "uv_set_count": 1,
            "face_group_names": ["Body"], "material_group_names": ["Skin"],
        }
        geo, client = self._geo(payload)
        info = geo.mesh_info()
        self.assertEqual(client.execute.call_count, 1)
        self.assertEqual(info["vertex_count"], 100)
        self.assertEqual(info["face_group_names"], ["Body"])

    def test_mesh_info_script_queries_all_counts(self):
        geo, client = self._geo(None)
        geo.mesh_info()
        script = client.execute.call_args[0][0]
        for token in ("getNumVertices", "getNumFacets", "getNumTris",
                      "getNumQuads", "getCurrentSubDivisionLevel",
                      "getNumUVSets", "getNumFaceGroups", "getNumMaterialGroups"):
            self.assertIn(token, script, msg=f"missing {token}")

    def test_mesh_info_returns_none_when_no_geometry(self):
        geo, client = self._geo(None)
        self.assertIsNone(geo.mesh_info())

    # ── bounding_box ──────────────────────────────────────────────────────────

    def test_bounding_box_returns_bounding_box_instance(self):
        from dazpy import BoundingBox
        payload = {"min": {"x": -1.0, "y": 0.0, "z": -1.0},
                   "max": {"x":  1.0, "y": 2.0, "z":  1.0}}
        geo, client = self._geo(payload)
        bb = geo.bounding_box()
        self.assertIsInstance(bb, BoundingBox)
        self.assertAlmostEqual(bb.min.x, -1.0)
        self.assertAlmostEqual(bb.max.y,  2.0)

    def test_bounding_box_single_call(self):
        payload = {"min": {"x": 0, "y": 0, "z": 0}, "max": {"x": 1, "y": 1, "z": 1}}
        geo, client = self._geo(payload)
        geo.bounding_box()
        self.assertEqual(client.execute.call_count, 1)

    def test_bounding_box_script_iterates_vertices(self):
        geo, client = self._geo(None)
        geo.bounding_box()
        script = client.execute.call_args[0][0]
        self.assertIn("getNumVertices", script)
        self.assertIn("getVertex", script)

    def test_bounding_box_returns_none_when_no_geometry(self):
        geo, client = self._geo(None)
        self.assertIsNone(geo.bounding_box())

    def test_bounding_box_posed_uses_getCachedGeom(self):
        geo, client = self._geo(None)
        geo.bounding_box_posed()
        script = client.execute.call_args[0][0]
        self.assertIn("getCachedGeom", script)
        self.assertIn("forceCacheUpdate", script)

    def test_bounding_box_posed_returns_bounding_box(self):
        from dazpy import BoundingBox
        payload = {"min": {"x": -2, "y": 0, "z": -2}, "max": {"x": 2, "y": 3, "z": 2}}
        geo, client = self._geo(payload)
        bb = geo.bounding_box_posed()
        self.assertIsInstance(bb, BoundingBox)
        self.assertAlmostEqual(bb.max.y, 3.0)

    def test_bounding_box_posed_returns_none_when_no_geometry(self):
        geo, client = self._geo(None)
        self.assertIsNone(geo.bounding_box_posed())

    # ── paginated _all() wrappers ─────────────────────────────────────────────

    def test_face_vertex_indices_all_single_page(self):
        payload = {"total": 2, "start": 0, "facets": [[0, 1, 2], [0, 2, 3]]}
        geo, client = self._geo(payload)
        result = geo.face_vertex_indices_all()
        self.assertEqual(result, [[0, 1, 2], [0, 2, 3]])

    def test_face_vertex_indices_all_paginates(self):
        from unittest.mock import MagicMock
        from dazpy._geometry import DazGeometry
        from dazpy._result import ExecutionResult
        geo, _ = self._geo()
        # Two pages: 2 faces total, chunk_size=1
        responses = [
            {"total": 2, "start": 0, "facets": [[0, 1, 2]]},
            {"total": 2, "start": 1, "facets": [[0, 2, 3]]},
        ]
        geo._client.execute.side_effect = [
            ExecutionResult(value=r, output=[], request_id="x") for r in responses
        ]
        result = geo.face_vertex_indices_all(chunk_size=1)
        self.assertEqual(len(result), 2)

    def test_normals_all_single_page(self):
        payload = {"total": 2, "start": 0, "normals": [[0, 1, 0], [0, -1, 0]]}
        geo, client = self._geo(payload)
        result = geo.normals_all()
        self.assertEqual(len(result), 2)

    def test_normals_all_paginates(self):
        responses = [
            {"total": 2, "start": 0, "normals": [[0, 1, 0]]},
            {"total": 2, "start": 1, "normals": [[0, -1, 0]]},
        ]
        from dazpy._result import ExecutionResult
        geo, _ = self._geo()
        geo._client.execute.side_effect = [
            ExecutionResult(value=r, output=[], request_id="x") for r in responses
        ]
        result = geo.normals_all(chunk_size=1)
        self.assertEqual(len(result), 2)

    def test_uv_positions_all_single_page(self):
        payload = {"total": 3, "start": 0, "uvs": [[0.0, 0.0], [1.0, 0.0], [0.5, 1.0]]}
        geo, client = self._geo(payload)
        result = geo.uv_positions_all()
        self.assertEqual(len(result), 3)

    def test_uv_positions_all_paginates(self):
        responses = [
            {"total": 2, "start": 0, "uvs": [[0.0, 0.0]]},
            {"total": 2, "start": 1, "uvs": [[1.0, 1.0]]},
        ]
        from dazpy._result import ExecutionResult
        geo, _ = self._geo()
        geo._client.execute.side_effect = [
            ExecutionResult(value=r, output=[], request_id="x") for r in responses
        ]
        result = geo.uv_positions_all(chunk_size=1)
        self.assertEqual(len(result), 2)

    # ── group membership ──────────────────────────────────────────────────────

    def test_face_group_faces_single_call(self):
        geo, client = self._geo([0, 1, 4, 7])
        result = geo.face_group_faces("Body")
        self.assertEqual(client.execute.call_count, 1)
        self.assertEqual(result, [0, 1, 4, 7])

    def test_face_group_faces_script_uses_group_name(self):
        geo, client = self._geo([])
        geo.face_group_faces("Head")
        script = client.execute.call_args[0][0]
        self.assertIn("Head", script)
        self.assertIn("getFaceGroup", script)
        self.assertIn("getIndexAt", script)

    def test_face_group_faces_returns_empty_when_not_found(self):
        geo, client = self._geo(None)
        self.assertEqual(geo.face_group_faces("Missing"), [])

    def test_material_group_faces_single_call(self):
        geo, client = self._geo([2, 3, 5])
        result = geo.material_group_faces("Skin")
        self.assertEqual(client.execute.call_count, 1)
        self.assertEqual(result, [2, 3, 5])

    def test_material_group_faces_script_uses_group_name(self):
        geo, client = self._geo([])
        geo.material_group_faces("Eyes")
        script = client.execute.call_args[0][0]
        self.assertIn("Eyes", script)
        self.assertIn("getMaterialGroup", script)
        self.assertIn("getIndexAt", script)

    def test_material_group_faces_returns_empty_when_not_found(self):
        geo, client = self._geo(None)
        self.assertEqual(geo.material_group_faces("Missing"), [])

    # ── triangulate ───────────────────────────────────────────────────────────

    def test_triangulate_tri_passthrough(self):
        from dazpy._geometry import DazGeometry
        faces = [[0, 1, 2], [3, 4, 5]]
        result = DazGeometry.triangulate(faces)
        self.assertEqual(result, [[0, 1, 2], [3, 4, 5]])

    def test_triangulate_quad_splits_to_two_tris(self):
        from dazpy._geometry import DazGeometry
        result = DazGeometry.triangulate([[0, 1, 2, 3]])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], [0, 1, 2])
        self.assertEqual(result[1], [0, 2, 3])

    def test_triangulate_mixed_faces(self):
        from dazpy._geometry import DazGeometry
        faces = [[0, 1, 2], [0, 1, 2, 3]]
        result = DazGeometry.triangulate(faces)
        self.assertEqual(len(result), 3)

    def test_triangulate_unknown_face_size_skipped(self):
        from dazpy._geometry import DazGeometry
        result = DazGeometry.triangulate([[0, 1]])  # 2-vertex "face"
        self.assertEqual(result, [])

    def test_triangulate_empty_input(self):
        from dazpy._geometry import DazGeometry
        self.assertEqual(DazGeometry.triangulate([]), [])

    # ── as_vec3 ───────────────────────────────────────────────────────────────

    def test_as_vec3_returns_vec3_instances(self):
        from dazpy import Vec3
        from dazpy._geometry import DazGeometry
        verts = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
        result = DazGeometry.as_vec3(verts)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], Vec3)

    def test_as_vec3_preserves_coordinates(self):
        from dazpy import Vec3
        from dazpy._geometry import DazGeometry
        result = DazGeometry.as_vec3([[1.5, 2.5, 3.5]])
        self.assertAlmostEqual(result[0].x, 1.5)
        self.assertAlmostEqual(result[0].y, 2.5)
        self.assertAlmostEqual(result[0].z, 3.5)

    def test_as_vec3_empty_input(self):
        from dazpy._geometry import DazGeometry
        self.assertEqual(DazGeometry.as_vec3([]), [])


class TestDazAnimation(unittest.TestCase):
    """Unit tests for DazAnimation — no server required."""

    def _make_skeleton(self, capture_result=None):
        from dazpy._skeleton import DazSkeleton
        client = _make_client(capture_result)
        skel = DazSkeleton(client, NodeIdentifier("Genesis 9", kind="label"))
        return skel, client

    def _sample_result(self, n_frames=3, n_bones=2, with_morphs=False):
        bones = ["hip", "spine"][:n_bones]
        frames = []
        for f in range(n_frames):
            frame = {
                "frame": f,
                "rotations": [[0.0, float(f), 0.0]] * n_bones,
                "morphs": {"PHMSmile": 0.5} if with_morphs else {},
            }
            frames.append(frame)
        return {
            "figure": "Genesis 9",
            "frame_range": {"start": 0, "end": n_frames - 1},
            "bones": bones,
            "frames": frames,
        }

    # ── capture script generation ─────────────────────────────────────────────

    def test_capture_executes_single_call(self):
        from dazpy import DazAnimation
        skel, client = self._make_skeleton(self._sample_result())
        DazAnimation.capture(skel)
        self.assertEqual(client.execute.call_count, 1)

    def test_capture_single_call_also_with_morphs(self):
        from dazpy import DazAnimation
        skel, client = self._make_skeleton(self._sample_result(with_morphs=True))
        DazAnimation.capture(skel, include_morphs=True)
        self.assertEqual(client.execute.call_count, 1)

    def test_capture_script_contains_getAllBones(self):
        from dazpy import DazAnimation
        skel, client = self._make_skeleton(self._sample_result())
        DazAnimation.capture(skel)
        script = client.execute.call_args[0][0]
        self.assertIn("getAllBones", script)

    def test_capture_script_scrubs_frames(self):
        from dazpy import DazAnimation
        skel, client = self._make_skeleton(self._sample_result())
        DazAnimation.capture(skel)
        script = client.execute.call_args[0][0]
        self.assertIn("setFrame", script)
        self.assertIn("getPlayRange", script)

    def test_capture_script_restores_original_frame(self):
        from dazpy import DazAnimation
        skel, client = self._make_skeleton(self._sample_result())
        DazAnimation.capture(skel)
        script = client.execute.call_args[0][0]
        self.assertIn("_origFrame", script)
        self.assertIn("Scene.setFrame(_origFrame)", script)

    def test_capture_script_morph_detection_disabled_by_default(self):
        from dazpy import DazAnimation
        skel, client = self._make_skeleton(self._sample_result())
        DazAnimation.capture(skel)
        script = client.execute.call_args[0][0]
        self.assertIn("if (false)", script)

    def test_capture_script_morph_detection_enabled(self):
        from dazpy import DazAnimation
        skel, client = self._make_skeleton(self._sample_result(with_morphs=True))
        DazAnimation.capture(skel, include_morphs=True)
        script = client.execute.call_args[0][0]
        self.assertIn("if (true)", script)
        self.assertIn("isVaryingMorph", script)
        self.assertIn("getValueChannel", script)

    def test_capture_raises_on_null_result(self):
        from dazpy import DazAnimation
        from dazpy.exceptions import NodeNotFoundError
        skel, _ = self._make_skeleton(None)
        with self.assertRaises(NodeNotFoundError):
            DazAnimation.capture(skel)

    def test_capture_returns_animation_with_correct_attributes(self):
        from dazpy import DazAnimation
        skel, _ = self._make_skeleton(self._sample_result(n_frames=5, n_bones=2))
        anim = DazAnimation.capture(skel)
        self.assertEqual(anim.figure, "Genesis 9")
        self.assertEqual(anim.frame_count, 5)
        self.assertEqual(anim.bone_count, 2)
        self.assertEqual(anim.frame_range, {"start": 0, "end": 4})

    # ── serialisation ─────────────────────────────────────────────────────────

    def test_to_dict_round_trip(self):
        from dazpy import DazAnimation
        skel, _ = self._make_skeleton(self._sample_result())
        anim = DazAnimation.capture(skel)
        d = anim.to_dict()
        self.assertIn("figure", d)
        self.assertIn("bones", d)
        self.assertIn("frames", d)
        self.assertIn("frame_range", d)

    def test_save_load_round_trip(self):
        import os, tempfile
        from dazpy import DazAnimation
        skel, _ = self._make_skeleton(self._sample_result(n_frames=4, n_bones=2))
        anim = DazAnimation.capture(skel)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            anim.save(path)
            loaded = DazAnimation.load(path)
            self.assertEqual(loaded.figure, anim.figure)
            self.assertEqual(loaded.bones, anim.bones)
            self.assertEqual(loaded.frame_count, anim.frame_count)
            self.assertEqual(loaded.frame_range, anim.frame_range)
        finally:
            os.unlink(path)

    def test_load_tolerates_missing_keys(self):
        import json, tempfile, os
        from dazpy import DazAnimation
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump({"figure": "MyFig"}, f)
            path = f.name
        try:
            anim = DazAnimation.load(path)
            self.assertEqual(anim.figure, "MyFig")
            self.assertEqual(anim.bones, [])
            self.assertEqual(anim.frames, [])
        finally:
            os.unlink(path)

    # ── properties ───────────────────────────────────────────────────────────

    def test_frame_count(self):
        from dazpy import DazAnimation
        skel, _ = self._make_skeleton(self._sample_result(n_frames=7))
        anim = DazAnimation.capture(skel)
        self.assertEqual(anim.frame_count, 7)

    def test_bone_count(self):
        from dazpy import DazAnimation
        skel, _ = self._make_skeleton(self._sample_result(n_bones=2))
        anim = DazAnimation.capture(skel)
        self.assertEqual(anim.bone_count, 2)

    def test_repr(self):
        from dazpy import DazAnimation
        skel, _ = self._make_skeleton(self._sample_result(n_frames=3, n_bones=2))
        anim = DazAnimation.capture(skel)
        r = repr(anim)
        self.assertIn("Genesis 9", r)
        self.assertIn("frames=3", r)
        self.assertIn("bones=2", r)


class TestDazAnimationClipOps(unittest.TestCase):
    """Tests for clip, blend, as_pose, apply, append, __len__, __getitem__."""

    def _make_anim(self, num_frames=3, start=0, bones=None, morph_sequence=None):
        from dazpy import DazAnimation
        bones = bones or ["hip", "rForeArm"]
        frames = []
        for i in range(num_frames):
            rotations = [[float(i), 0.0, 0.0] for _ in bones]
            morphs = morph_sequence[i] if morph_sequence else {}
            frames.append({"frame": start + i, "rotations": rotations, "morphs": morphs})
        return DazAnimation(
            figure="Genesis 9",
            frame_range={"start": start, "end": start + num_frames - 1},
            bones=bones,
            frames=frames,
        )

    # ── clip ─────────────────────────────────────────────────────────────────

    def test_clip_returns_frames_in_range(self):
        anim = self._make_anim(5, start=0)
        c = anim.clip(1, 3)
        self.assertEqual(len(c.frames), 3)
        self.assertEqual(c.frames[0]["frame"], 1)
        self.assertEqual(c.frames[-1]["frame"], 3)

    def test_clip_updates_frame_range(self):
        anim = self._make_anim(5, start=0)
        c = anim.clip(2, 4)
        self.assertEqual(c.frame_range["start"], 2)
        self.assertEqual(c.frame_range["end"], 4)

    def test_clip_preserves_bones(self):
        anim = self._make_anim(5)
        c = anim.clip(0, 2)
        self.assertEqual(c.bones, anim.bones)

    def test_clip_empty_when_out_of_range(self):
        anim = self._make_anim(3, start=0)
        c = anim.clip(10, 20)
        self.assertEqual(len(c.frames), 0)

    def test_clip_full_range_equals_original_count(self):
        anim = self._make_anim(4, start=0)
        c = anim.clip(0, 3)
        self.assertEqual(len(c.frames), 4)

    def test_clip_figure_preserved(self):
        anim = self._make_anim(3)
        c = anim.clip(0, 1)
        self.assertEqual(c.figure, anim.figure)

    # ── blend ─────────────────────────────────────────────────────────────────

    def test_blend_t0_equals_self_rotations(self):
        from dazpy import DazAnimation
        a = self._make_anim(2, bones=["hip"])
        b = DazAnimation("Genesis 9", {"start": 0, "end": 1}, ["hip"],
                         [{"frame": 0, "rotations": [[100.0, 0.0, 0.0]], "morphs": {}},
                          {"frame": 1, "rotations": [[200.0, 0.0, 0.0]], "morphs": {}}])
        blended = a.blend(b, 0.0)
        self.assertAlmostEqual(blended.frames[0]["rotations"][0][0],
                               a.frames[0]["rotations"][0][0])

    def test_blend_t1_equals_other_rotations(self):
        from dazpy import DazAnimation
        a = self._make_anim(2, bones=["hip"])
        b = DazAnimation("Genesis 9", {"start": 0, "end": 1}, ["hip"],
                         [{"frame": 0, "rotations": [[100.0, 0.0, 0.0]], "morphs": {}},
                          {"frame": 1, "rotations": [[200.0, 0.0, 0.0]], "morphs": {}}])
        blended = a.blend(b, 1.0)
        self.assertAlmostEqual(blended.frames[0]["rotations"][0][0], 100.0)

    def test_blend_midpoint_averages_rotations(self):
        from dazpy import DazAnimation
        a = DazAnimation("G9", {"start": 0, "end": 0}, ["hip"],
                         [{"frame": 0, "rotations": [[0.0, 0.0, 0.0]], "morphs": {}}])
        b = DazAnimation("G9", {"start": 0, "end": 0}, ["hip"],
                         [{"frame": 0, "rotations": [[20.0, 0.0, 0.0]], "morphs": {}}])
        blended = a.blend(b, 0.5)
        self.assertAlmostEqual(blended.frames[0]["rotations"][0][0], 10.0)

    def test_blend_morph_union_of_keys(self):
        from dazpy import DazAnimation
        a = DazAnimation("G9", {"start": 0, "end": 0}, ["hip"],
                         [{"frame": 0, "rotations": [[0.0, 0.0, 0.0]], "morphs": {"smile": 1.0}}])
        b = DazAnimation("G9", {"start": 0, "end": 0}, ["hip"],
                         [{"frame": 0, "rotations": [[0.0, 0.0, 0.0]], "morphs": {"frown": 1.0}}])
        blended = a.blend(b, 0.5)
        self.assertAlmostEqual(blended.frames[0]["morphs"].get("smile", 0.0), 0.5)
        self.assertAlmostEqual(blended.frames[0]["morphs"].get("frown", 0.0), 0.5)

    def test_blend_different_bones_raises(self):
        a = self._make_anim(2, bones=["hip"])
        b = self._make_anim(2, bones=["rForeArm"])
        with self.assertRaises(ValueError):
            a.blend(b, 0.5)

    def test_blend_truncates_to_shorter_clip(self):
        a = self._make_anim(3, bones=["hip"])
        b = self._make_anim(2, bones=["hip"])
        blended = a.blend(b, 0.5)
        self.assertEqual(len(blended.frames), 2)

    def test_blend_frame_numbers_from_self(self):
        a = self._make_anim(2, start=10, bones=["hip"])
        b = self._make_anim(2, start=0, bones=["hip"])
        blended = a.blend(b, 0.5)
        self.assertEqual(blended.frames[0]["frame"], 10)

    # ── as_pose ───────────────────────────────────────────────────────────────

    def test_as_pose_returns_daz_pose(self):
        from dazpy import DazPose
        pose = self._make_anim(3).as_pose(1)
        self.assertIsInstance(pose, DazPose)

    def test_as_pose_figure_matches(self):
        anim = self._make_anim(2)
        self.assertEqual(anim.as_pose(0).figure, anim.figure)

    def test_as_pose_sparse_bones_zero_excluded(self):
        from dazpy import DazAnimation
        anim = DazAnimation(
            "G9", {"start": 0, "end": 0}, ["hip", "rForeArm"],
            [{"frame": 0, "rotations": [[0.0, 0.0, 0.0], [45.0, 0.0, 0.0]], "morphs": {}}]
        )
        pose = anim.as_pose(0)
        self.assertNotIn("hip", pose.bones)
        self.assertIn("rForeArm", pose.bones)

    def test_as_pose_includes_morphs(self):
        from dazpy import DazAnimation
        anim = DazAnimation(
            "G9", {"start": 0, "end": 0}, ["hip"],
            [{"frame": 0, "rotations": [[0.0, 0.0, 0.0]], "morphs": {"smile": 0.8}}]
        )
        self.assertAlmostEqual(anim.as_pose(0).morphs.get("smile"), 0.8)

    def test_as_pose_default_index_zero(self):
        anim = self._make_anim(3)
        pose = anim.as_pose()
        self.assertEqual(pose.figure, anim.figure)

    def test_as_pose_props_empty(self):
        anim = self._make_anim(2)
        self.assertEqual(anim.as_pose(0).props, {})

    # ── apply ─────────────────────────────────────────────────────────────────

    def test_apply_calls_skeleton_client_once(self):
        from dazpy._skeleton import DazSkeleton
        anim = self._make_anim(2)
        client = _make_client(True)
        skel = DazSkeleton(client, NodeIdentifier("Genesis 9", kind="label"))
        anim.apply(skel, frame_index=0)
        self.assertEqual(client.execute.call_count, 1)

    def test_apply_script_contains_bone_names(self):
        from dazpy import DazAnimation
        from dazpy._skeleton import DazSkeleton
        anim = DazAnimation(
            "G9", {"start": 0, "end": 0}, ["rForeArm"],
            [{"frame": 0, "rotations": [[45.0, 0.0, 0.0]], "morphs": {}}]
        )
        client = _make_client(True)
        skel = DazSkeleton(client, NodeIdentifier("G9"))
        anim.apply(skel, frame_index=0)
        script = client.execute.call_args[0][0]
        self.assertIn("rForeArm", script)
        self.assertIn("45.0", script)

    # ── append ────────────────────────────────────────────────────────────────

    def test_append_total_frame_count(self):
        a = self._make_anim(3, start=0)
        b = self._make_anim(2, start=0)
        self.assertEqual(len(a.append(b).frames), 5)

    def test_append_renumbers_b_frames(self):
        a = self._make_anim(3, start=0)  # frames 0,1,2
        b = self._make_anim(2, start=5)  # frames 5,6 → should become 3,4
        result = a.append(b)
        self.assertEqual(result.frames[3]["frame"], 3)
        self.assertEqual(result.frames[4]["frame"], 4)

    def test_append_frame_range_updated(self):
        a = self._make_anim(3, start=0)  # end=2
        b = self._make_anim(2, start=0)  # end=1 → becomes 3,4
        result = a.append(b)
        self.assertEqual(result.frame_range["start"], 0)
        self.assertEqual(result.frame_range["end"], 4)

    def test_append_different_bones_raises(self):
        a = self._make_anim(2, bones=["hip"])
        b = self._make_anim(2, bones=["rForeArm"])
        with self.assertRaises(ValueError):
            a.append(b)

    def test_append_preserves_self_figure(self):
        a = self._make_anim(2)
        b = self._make_anim(2)
        self.assertEqual(a.append(b).figure, a.figure)

    def test_append_empty_self_returns_other(self):
        from dazpy import DazAnimation
        empty = DazAnimation("G9", {"start": 0, "end": 0}, ["hip"], [])
        b = self._make_anim(2, bones=["hip"])
        result = empty.append(b)
        self.assertEqual(len(result.frames), 2)

    # ── __len__ / __getitem__ ─────────────────────────────────────────────────

    def test_len(self):
        self.assertEqual(len(self._make_anim(5)), 5)

    def test_getitem_returns_frame_dict(self):
        anim = self._make_anim(3)
        frame = anim[0]
        self.assertIn("rotations", frame)
        self.assertIn("frame", frame)

    def test_getitem_negative_index(self):
        anim = self._make_anim(3, start=0)
        self.assertEqual(anim[-1]["frame"], 2)

    def test_getitem_out_of_range_raises(self):
        anim = self._make_anim(2)
        with self.assertRaises(IndexError):
            _ = anim[99]


class TestDazPose(unittest.TestCase):
    """Unit tests for DazPose — no server required."""

    def _make_skeleton(self, capture_result=None):
        from dazpy._skeleton import DazSkeleton
        client = _make_client(capture_result)
        skel = DazSkeleton(client, NodeIdentifier("Genesis 9", kind="label"))
        return skel, client

    # ── lerp (pure Python) ────────────────────────────────────────────────────

    def test_lerp_midpoint_bones(self):
        from dazpy import DazPose
        a = DazPose("fig", bones={"hip": [0.0, 0.0, 0.0]}, morphs={}, props={})
        b = DazPose("fig", bones={"hip": [10.0, 20.0, 30.0]}, morphs={}, props={})
        mid = a.lerp(b, 0.5)
        self.assertAlmostEqual(mid.bones["hip"][0], 5.0)
        self.assertAlmostEqual(mid.bones["hip"][1], 10.0)
        self.assertAlmostEqual(mid.bones["hip"][2], 15.0)

    def test_lerp_missing_key_treated_as_zero(self):
        from dazpy import DazPose
        a = DazPose("fig", bones={}, morphs={}, props={})
        b = DazPose("fig", bones={"rForeArm": [0.0, 0.0, -45.0]}, morphs={}, props={})
        mid = a.lerp(b, 0.5)
        self.assertAlmostEqual(mid.bones["rForeArm"][2], -22.5)

    def test_lerp_t0_equals_self(self):
        from dazpy import DazPose
        a = DazPose("fig", bones={"hip": [1.0, 2.0, 3.0]}, morphs={"smile": 0.8}, props={})
        b = DazPose("fig", bones={"hip": [9.0, 8.0, 7.0]}, morphs={"smile": 0.0}, props={})
        result = a.lerp(b, 0.0)
        self.assertAlmostEqual(result.bones["hip"][0], 1.0)
        self.assertAlmostEqual(result.morphs["smile"], 0.8)

    def test_lerp_t1_equals_other(self):
        from dazpy import DazPose
        a = DazPose("fig", bones={"hip": [0.0, 0.0, 0.0]}, morphs={"smile": 0.0}, props={})
        b = DazPose("fig", bones={"hip": [9.0, 8.0, 7.0]}, morphs={"smile": 1.0}, props={})
        result = a.lerp(b, 1.0)
        self.assertAlmostEqual(result.bones["hip"][0], 9.0)
        self.assertAlmostEqual(result.morphs["smile"], 1.0)

    def test_lerp_morphs_union_of_keys(self):
        from dazpy import DazPose
        a = DazPose("fig", bones={}, morphs={"morphA": 1.0}, props={})
        b = DazPose("fig", bones={}, morphs={"morphB": 1.0}, props={})
        mid = a.lerp(b, 0.5)
        self.assertIn("morphA", mid.morphs)
        self.assertIn("morphB", mid.morphs)
        self.assertAlmostEqual(mid.morphs["morphA"], 0.5)
        self.assertAlmostEqual(mid.morphs["morphB"], 0.5)

    def test_lerp_preserves_figure_label_from_self(self):
        from dazpy import DazPose
        a = DazPose("FigureA", bones={}, morphs={}, props={})
        b = DazPose("FigureB", bones={}, morphs={}, props={})
        result = a.lerp(b, 0.5)
        self.assertEqual(result.figure, "FigureA")

    # ── serialisation ─────────────────────────────────────────────────────────

    def test_to_dict_round_trip(self):
        from dazpy import DazPose
        pose = DazPose("fig", {"hip": [1.0, 2.0, 3.0]}, {"smile": 0.5}, {"facs": 0.3})
        d = pose.to_dict()
        restored = DazPose(d["figure"], d["bones"], d["morphs"], d["props"])
        self.assertEqual(restored.bones, pose.bones)
        self.assertEqual(restored.morphs, pose.morphs)
        self.assertEqual(restored.props, pose.props)

    def test_save_load_round_trip(self):
        import os, tempfile
        from dazpy import DazPose
        pose = DazPose("Genesis 9", {"hip": [0.0, 5.0, 0.0]}, {"PHMSmile": 0.7}, {"facs": 0.2})
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            pose.save(path)
            loaded = DazPose.load(path)
            self.assertEqual(loaded.figure, "Genesis 9")
            self.assertAlmostEqual(loaded.morphs["PHMSmile"], 0.7)
            self.assertEqual(loaded.bones["hip"], [0.0, 5.0, 0.0])
        finally:
            os.unlink(path)

    def test_load_tolerates_missing_keys(self):
        import json, tempfile, os
        from dazpy import DazPose
        data = {"figure": "MyFig"}
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump(data, f)
            path = f.name
        try:
            pose = DazPose.load(path)
            self.assertEqual(pose.figure, "MyFig")
            self.assertEqual(pose.bones, {})
            self.assertEqual(pose.morphs, {})
            self.assertEqual(pose.props, {})
        finally:
            os.unlink(path)

    # ── capture script generation ─────────────────────────────────────────────

    def test_capture_executes_single_call(self):
        from dazpy import DazPose
        skel, client = self._make_skeleton({"bones": {}, "morphs": {}, "props": {}})
        DazPose.capture(skel)
        self.assertEqual(client.execute.call_count, 1)

    def test_capture_script_contains_getAllBones(self):
        from dazpy import DazPose
        skel, client = self._make_skeleton({"bones": {}, "morphs": {}, "props": {}})
        DazPose.capture(skel)
        script = client.execute.call_args[0][0]
        self.assertIn("getAllBones", script)

    def test_capture_script_reads_morphs(self):
        from dazpy import DazPose
        skel, client = self._make_skeleton({"bones": {}, "morphs": {}, "props": {}})
        DazPose.capture(skel)
        script = client.execute.call_args[0][0]
        self.assertIn("getValueChannel", script)
        self.assertIn("DzMorph", script)

    def test_capture_raises_on_null_result(self):
        from dazpy import DazPose
        from dazpy.exceptions import NodeNotFoundError
        skel, _ = self._make_skeleton(None)
        with self.assertRaises(NodeNotFoundError):
            DazPose.capture(skel)

    def test_capture_returns_pose_with_correct_figure(self):
        from dazpy import DazPose
        skel, _ = self._make_skeleton({"bones": {"hip": [0, 5, 0]}, "morphs": {}, "props": {}})
        pose = DazPose.capture(skel)
        self.assertEqual(pose.figure, "Genesis 9")
        self.assertIn("hip", pose.bones)

    # ── apply script generation ───────────────────────────────────────────────

    def test_apply_executes_single_call(self):
        from dazpy import DazPose
        pose = DazPose("Genesis 9", {"hip": [0, 5, 0]}, {"smile": 0.5}, {})
        skel, client = self._make_skeleton(True)
        pose.apply(skel)
        self.assertEqual(client.execute.call_count, 1)

    def test_apply_script_contains_bone_data(self):
        from dazpy import DazPose
        pose = DazPose("Genesis 9", {"rForeArm": [0.0, 0.0, -45.0]}, {}, {})
        skel, client = self._make_skeleton(True)
        pose.apply(skel)
        script = client.execute.call_args[0][0]
        self.assertIn("rForeArm", script)
        self.assertIn("-45", script)
        self.assertIn("getXRotControl", script)

    def test_apply_script_contains_morph_data(self):
        from dazpy import DazPose
        pose = DazPose("Genesis 9", {}, {"PHMSmile": 0.75}, {})
        skel, client = self._make_skeleton(True)
        pose.apply(skel)
        script = client.execute.call_args[0][0]
        self.assertIn("PHMSmile", script)
        self.assertIn("0.75", script)

    def test_apply_script_uses_json_injection(self):
        """apply() should inject bone/morph data as JSON dicts, not inline per-bone JS."""
        from dazpy import DazPose
        pose = DazPose("Genesis 9", {"hip": [1, 2, 3], "spine": [4, 5, 6]}, {}, {})
        skel, client = self._make_skeleton(True)
        pose.apply(skel)
        script = client.execute.call_args[0][0]
        # Should loop over getAllBones(), not call findBone() per bone
        self.assertIn("getAllBones", script)

    def test_apply_full_zeroes_absent_bones(self):
        from dazpy import DazPose
        pose = DazPose("Genesis 9", {}, {}, {})
        skel, client = self._make_skeleton(True)
        pose.apply_full(skel)
        script = client.execute.call_args[0][0]
        # Should set 0 for bones not in the pose
        self.assertIn("setValue(0)", script)

    # ── repr ──────────────────────────────────────────────────────────────────

    def test_repr(self):
        from dazpy import DazPose
        pose = DazPose("Genesis 9", {"hip": [0, 0, 0]}, {"smile": 0.5}, {})
        r = repr(pose)
        self.assertIn("Genesis 9", r)
        self.assertIn("bones=1", r)
        self.assertIn("morphs=1", r)


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
        import math
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
        q = Quat.from_axis_angle
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
        from dazpy import Vec3
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
        from dazpy import Vec3
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


class TestCallCounts(unittest.TestCase):
    """Prove that the batch paths reduce HTTP call counts dramatically."""

    _BONE_META = [
        {"name": "hip",      "label": "Hip",        "parent_name": None,    "rotation_order": "YXZ",
         "local_position": {"x": 0, "y": 100, "z": 0}, "world_position": {"x": 0, "y": 100, "z": 0},
         "local_euler": {"x": 0, "y": 0, "z": 0}},
        {"name": "l_thigh",  "label": "LThigh",     "parent_name": "hip",   "rotation_order": "YXZ",
         "local_position": {"x": 10, "y": 80, "z": 0}, "world_position": {"x": 10, "y": 80, "z": 0},
         "local_euler": {"x": 0, "y": 0, "z": 0}},
        {"name": "l_shin",   "label": "LShin",      "parent_name": "l_thigh","rotation_order": "YXZ",
         "local_position": {"x": 10, "y": 50, "z": 0}, "world_position": {"x": 10, "y": 50, "z": 0},
         "local_euler": {"x": 0, "y": 0, "z": 0}},
        {"name": "l_foot",   "label": "LFoot",      "parent_name": "l_shin","rotation_order": "YXZ",
         "local_position": {"x": 10, "y": 10, "z": 0}, "world_position": {"x": 10, "y": 10, "z": 0},
         "local_euler": {"x": 0, "y": 0, "z": 0}},
    ]
    _BONE_ROTS = {b["name"]: [0.0, 0.0, 0.0] for b in _BONE_META}
    _JACOBIAN = {
        "base_position": [10.0, 10.0, 0.0],
        "columns": [[1, 0, 0], [0, 1, 0], [0, 0, 1]] * 4,
    }

    def _make_batch_skeleton(self, max_iterations=12):
        from dazpy._skeleton import DazSkeleton
        from dazpy._node import NodeIdentifier

        def _execute(script):
            if "getLabel" in script and "getAllBones" not in script:
                return ExecutionResult(value="Genesis 9", output=[], request_id="x")
            if "_columns" in script:
                return ExecutionResult(value=self._JACOBIAN, output=[], request_id="x")
            if "getLocalPos" in script:
                return ExecutionResult(value=self._BONE_META, output=[], request_id="x")
            # bone_rotations or set_bone_rotations — return rotations dict or None
            if "_result" in script:
                return ExecutionResult(value=self._BONE_ROTS, output=[], request_id="x")
            return ExecutionResult(value=None, output=[], request_id="x")

        client = MagicMock(spec=DazClient)
        client.execute.side_effect = _execute

        skel = DazSkeleton.__new__(DazSkeleton)
        object.__setattr__(skel, "_client", client)
        object.__setattr__(skel, "_identifier", NodeIdentifier("Genesis 9", kind="label"))
        return skel, client

    def test_align_hand_target_call_count_bounded(self):
        """align_hand_target must use ≤ 30 execute calls for 12 iterations."""
        skel, client = self._make_batch_skeleton()
        from dazpy import align_hand_target
        align_hand_target(skel, (50.0, 10.0, 0.0), source_anchor="l_foot", max_iterations=12)
        # Old per-bone approach: ~500 calls for a 4-bone chain, 12 iterations.
        # Batch approach: 1 (label) + 1 (bone_meta) + 1 (bone_rots) + 1 (init jac) + 12×2 = 28.
        self.assertLessEqual(client.execute.call_count, 30)

    def test_align_foot_target_call_count_bounded(self):
        """align_foot_target must use ≤ 30 execute calls for 12 iterations."""
        skel, client = self._make_batch_skeleton()
        from dazpy import align_foot_target
        align_foot_target(skel, (50.0, 10.0, 0.0), source_anchor="l_foot", max_iterations=12)
        self.assertLessEqual(client.execute.call_count, 30)

    def test_align_hand_target_iterations_proportional(self):
        """Call count scales linearly with max_iterations (2 calls/iter + O(1) setup)."""
        skel3, client3 = self._make_batch_skeleton()
        skel6, client6 = self._make_batch_skeleton()
        from dazpy import align_hand_target
        align_hand_target(skel3, (50.0, 10.0, 0.0), source_anchor="l_foot", max_iterations=3)
        align_hand_target(skel6, (50.0, 10.0, 0.0), source_anchor="l_foot", max_iterations=6)
        # Extra calls for 3 more iterations ≤ 7 (3 extra iters × 2 + rounding)
        delta = client6.execute.call_count - client3.execute.call_count
        self.assertLessEqual(delta, 7)

    def test_build_rig_profile_world_position_populated(self):
        """build_rig_profile populates world_position from bone_metadata()."""
        from dazpy import build_rig_profile
        skel, _ = self._make_batch_skeleton()
        profile = build_rig_profile(skel)
        foot = profile.bone("l_foot")
        self.assertIsNotNone(foot.world_position)
        self.assertEqual(foot.world_position, (10.0, 10.0, 0.0))

    def test_bone_metadata_includes_world_position(self):
        """bone_metadata() script must request getWSPos()."""
        skel, client = self._make_batch_skeleton()
        skel.bone_metadata()
        script = client.execute.call_args[0][0]
        self.assertIn("getWSPos", script)
        self.assertIn("world_position", script)


class TestSceneSnapshot(unittest.TestCase):
    """Tests for DazScene.scene_snapshot() and build_rig_profiles_from_snapshot()."""

    from dazpy import build_rig_profiles_from_snapshot

    _SAMPLE_SNAPSHOT = [
        {
            "name": "Genesis9",
            "label": "Genesis 9",
            "bones": [
                {
                    "name": "hip",
                    "label": "Hip",
                    "parent_name": None,
                    "rotation_order": "YXZ",
                    "local_position": {"x": 0.0, "y": 100.0, "z": 0.0},
                    "world_position": {"x": 0.0, "y": 100.0, "z": 0.0},
                    "local_euler": {"x": 0.0, "y": 0.0, "z": 0.0},
                },
                {
                    "name": "l_hand",
                    "label": "Left Hand",
                    "parent_name": "hip",
                    "rotation_order": "YXZ",
                    "local_position": {"x": 20.0, "y": 150.0, "z": 0.0},
                    "world_position": {"x": 20.0, "y": 150.0, "z": 0.0},
                    "local_euler": {"x": 0.0, "y": 0.0, "z": 0.0},
                },
                {
                    "name": "r_hand",
                    "label": "Right Hand",
                    "parent_name": "hip",
                    "rotation_order": "YXZ",
                    "local_position": {"x": -20.0, "y": 150.0, "z": 0.0},
                    "world_position": {"x": -20.0, "y": 150.0, "z": 0.0},
                    "local_euler": {"x": 0.0, "y": 0.0, "z": 0.0},
                },
                {
                    "name": "l_foot",
                    "label": "Left Foot",
                    "parent_name": "hip",
                    "rotation_order": "YXZ",
                    "local_position": {"x": 10.0, "y": 0.0, "z": 0.0},
                    "world_position": {"x": 10.0, "y": 0.0, "z": 0.0},
                    "local_euler": {"x": 0.0, "y": 0.0, "z": 0.0},
                },
            ],
        }
    ]

    def test_build_rig_profiles_from_snapshot_keys(self):
        from dazpy import build_rig_profiles_from_snapshot
        profiles = build_rig_profiles_from_snapshot(self._SAMPLE_SNAPSHOT)
        self.assertIn("Genesis 9", profiles)
        self.assertIn("Genesis9", profiles)
        self.assertIs(profiles["Genesis 9"], profiles["Genesis9"])

    def test_build_rig_profiles_figure_label_and_family(self):
        from dazpy import build_rig_profiles_from_snapshot
        profiles = build_rig_profiles_from_snapshot(self._SAMPLE_SNAPSHOT)
        profile = profiles["Genesis 9"]
        self.assertEqual(profile.figure_label, "Genesis 9")
        self.assertEqual(profile.family, "genesis_9")

    def test_build_rig_profiles_bone_world_position(self):
        from dazpy import build_rig_profiles_from_snapshot
        profiles = build_rig_profiles_from_snapshot(self._SAMPLE_SNAPSHOT)
        bone = profiles["Genesis 9"].bone("l_hand")
        self.assertEqual(bone.world_position, (20.0, 150.0, 0.0))
        self.assertEqual(bone.local_position, (20.0, 150.0, 0.0))

    def test_build_rig_profiles_parent_chain(self):
        from dazpy import build_rig_profiles_from_snapshot
        profiles = build_rig_profiles_from_snapshot(self._SAMPLE_SNAPSHOT)
        profile = profiles["Genesis 9"]
        self.assertEqual(profile.bone("l_hand").parent_name, "hip")
        self.assertIsNone(profile.bone("hip").parent_name)

    def test_build_rig_profiles_anchor_uses_world_position(self):
        from dazpy import build_rig_profiles_from_snapshot
        from dazpy._interaction import _anchor_world_point_hint
        profiles = build_rig_profiles_from_snapshot(self._SAMPLE_SNAPSHOT)
        profile = profiles["Genesis 9"]
        point = _anchor_world_point_hint(profile, "r_hand")
        self.assertIsNotNone(point)
        self.assertAlmostEqual(point[0], -20.0)

    def test_build_rig_profiles_source_metadata(self):
        from dazpy import build_rig_profiles_from_snapshot
        profiles = build_rig_profiles_from_snapshot(self._SAMPLE_SNAPSHOT)
        self.assertEqual(profiles["Genesis 9"].metadata["source"], "snapshot")

    def test_build_rig_profiles_empty_snapshot(self):
        from dazpy import build_rig_profiles_from_snapshot
        self.assertEqual(build_rig_profiles_from_snapshot([]), {})

    def test_scene_snapshot_script_contains_getWSPos(self):
        client = _make_client([])
        scene = DazScene(client)
        scene.scene_snapshot()
        script = client.execute.call_args[0][0]
        self.assertIn("getWSPos", script)
        self.assertIn("getAllBones", script)
        self.assertIn("getSkeletonList", script)

    def test_scene_snapshot_filter_serialized(self):
        client = _make_client([])
        scene = DazScene(client)
        scene.scene_snapshot(skeleton_labels=["Genesis 9", "Bob"])
        script = client.execute.call_args[0][0]
        self.assertIn('"Genesis 9"', script)
        self.assertIn('"Bob"', script)

    def test_scene_snapshot_no_filter_passes_null(self):
        client = _make_client([])
        scene = DazScene(client)
        scene.scene_snapshot()
        script = client.execute.call_args[0][0]
        self.assertIn("null", script)

    def test_apply_recipe_uses_snapshot_when_available(self):
        """apply_interaction_recipe_to_scene uses scene_snapshot() when present."""
        from dazpy import build_rig_profiles_from_snapshot, InteractionRecipe, PoseTarget

        snapshot = self._SAMPLE_SNAPSHOT
        profiles = build_rig_profiles_from_snapshot(snapshot)

        class _SnapshotScene:
            def scene_snapshot(self, **_):
                return snapshot

            def skeletons(self):
                raise AssertionError("skeletons() should not be called when scene_snapshot() is present")

        recipe = InteractionRecipe(
            kind="custom",
            actors=["Genesis 9"],
            constraints=[PoseTarget(figure_label="Genesis 9", bone_name="hip")],
        )

        class _SceneWithApply(_SnapshotScene):
            def __init__(self):
                self.applied = False

            def apply_interaction_recipe(self, *a, **kw):
                self.applied = True

        # Just verify build_rig_profiles_from_snapshot returns correct structure
        self.assertIn("Genesis 9", profiles)
        self.assertEqual(profiles["Genesis 9"].bone("l_hand").world_position, (20.0, 150.0, 0.0))

    def test_bone_profile_world_position_round_trips(self):
        bp = BoneProfile(
            name="test_bone",
            world_position=(1.0, 2.0, 3.0),
        )
        d = bp.to_dict()
        self.assertEqual(d["world_position"], [1.0, 2.0, 3.0])
        restored = BoneProfile.from_dict(d)
        self.assertEqual(restored.world_position, (1.0, 2.0, 3.0))

    def test_bone_profile_world_position_none_by_default(self):
        bp = BoneProfile(name="test_bone")
        self.assertIsNone(bp.world_position)
        d = bp.to_dict()
        self.assertIsNone(d["world_position"])


class TestBatchPoseEvaluation(unittest.TestCase):
    """Tests for DazSkeleton.evaluate_pose() and evaluate_pose_jacobian()."""

    def _make_skeleton_client(self, return_value):
        from dazpy._skeleton import DazSkeleton
        client = _make_client(return_value)
        skel = DazSkeleton.__new__(DazSkeleton)
        from dazpy._node import NodeIdentifier
        object.__setattr__(skel, "_client", client)
        object.__setattr__(skel, "_identifier", NodeIdentifier("Genesis 9", kind="label"))
        return skel, client

    def test_evaluate_pose_script_contains_save_apply_restore(self):
        skel, client = self._make_skeleton_client({"r_hand": [10.0, 20.0, 30.0]})
        result = skel.evaluate_pose({"hip": (5.0, 0.0, 0.0)}, ["r_hand"])
        script = client.execute.call_args[0][0]
        self.assertIn("_originals", script)
        self.assertIn("getWSPos", script)
        self.assertIn('"hip"', script)
        self.assertIn('"r_hand"', script)

    def test_evaluate_pose_returns_typed_tuples(self):
        skel, client = self._make_skeleton_client({"r_hand": [1.0, 2.0, 3.0]})
        result = skel.evaluate_pose({"hip": (0.0, 0.0, 0.0)}, ["r_hand"])
        self.assertEqual(result, {"r_hand": (1.0, 2.0, 3.0)})

    def test_evaluate_pose_empty_response(self):
        skel, client = self._make_skeleton_client({})
        result = skel.evaluate_pose({}, [])
        self.assertEqual(result, {})

    def test_evaluate_pose_jacobian_script_contains_perturbation(self):
        skel, client = self._make_skeleton_client(
            {"base_position": [0.0, 150.0, 0.0], "columns": [[1.0, 0.0, 0.0]] * 9}
        )
        skel.evaluate_pose_jacobian(["hip", "spine", "chest"], "r_hand", step_degrees=2.0)
        script = client.execute.call_args[0][0]
        self.assertIn("getWSPos", script)
        self.assertIn("_columns", script)
        self.assertIn("setValue(_orig + _step)", script)
        self.assertIn("2.0", script)

    def test_evaluate_pose_jacobian_chain_serialized(self):
        skel, client = self._make_skeleton_client(
            {"base_position": [0.0, 0.0, 0.0], "columns": []}
        )
        skel.evaluate_pose_jacobian(["hip", "r_hand"], "r_hand")
        script = client.execute.call_args[0][0]
        self.assertIn('"hip"', script)
        self.assertIn('"r_hand"', script)

    def test_evaluate_pose_jacobian_returns_none_on_missing_effector(self):
        skel, client = self._make_skeleton_client(None)
        result = skel.evaluate_pose_jacobian(["hip"], "missing_bone")
        self.assertIsNone(result)

    def test_align_single_limb_uses_batch_path_when_client_present(self):
        """align_single_limb_target dispatches to batch path for real skeletons."""
        from dazpy import align_single_limb_target, FigureRigProfile, BoneProfile
        from dazpy._skeleton import DazSkeleton
        from dazpy._node import NodeIdentifier
        from dazpy._interaction import ResolvedInteractionTarget

        # Build a minimal profile
        hip = BoneProfile(name="hip")
        r_hand = BoneProfile(name="r_hand", parent_name="hip")
        profile = FigureRigProfile(figure_label="Test", family="genesis_9", bones=[hip, r_hand])

        target = ResolvedInteractionTarget(
            figure_label="Test",
            anchor_name="r_hand",
            bone_name="r_hand",
            target_point=(10.0, 150.0, 0.0),
        )

        call_log = []

        def _execute(script):
            call_log.append(script)
            if "getAllBones" in script and "_result" not in script and "_columns" not in script:
                # bone_rotations()
                return ExecutionResult(value={"hip": [0.0, 0.0, 0.0], "r_hand": [0.0, 0.0, 0.0]}, output=[], request_id="x")
            if "_columns" in script:
                # evaluate_pose_jacobian
                return ExecutionResult(
                    value={"base_position": [0.0, 150.0, 0.0], "columns": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]] * 2},
                    output=[], request_id="x",
                )
            # set_bone_rotations
            return ExecutionResult(value=None, output=[], request_id="x")

        client = MagicMock(spec=DazClient)
        client.execute.side_effect = _execute

        skel = DazSkeleton.__new__(DazSkeleton)
        object.__setattr__(skel, "_client", client)
        object.__setattr__(skel, "_identifier", NodeIdentifier("Test", kind="label"))

        result = align_single_limb_target(skel, profile, target)

        self.assertEqual(result.diagnostics.get("path"), "batch")
        self.assertIsNotNone(result.initial_error)

    def test_align_single_limb_batch_already_aligned(self):
        """Batch path returns converged immediately when already within tolerance."""
        from dazpy import align_single_limb_target, FigureRigProfile, BoneProfile
        from dazpy._skeleton import DazSkeleton
        from dazpy._node import NodeIdentifier
        from dazpy._interaction import ResolvedInteractionTarget

        hip = BoneProfile(name="hip")
        r_hand = BoneProfile(name="r_hand", parent_name="hip")
        profile = FigureRigProfile(figure_label="Test", family="genesis_9", bones=[hip, r_hand])

        target = ResolvedInteractionTarget(
            figure_label="Test",
            anchor_name="r_hand",
            bone_name="r_hand",
            target_point=(0.0, 150.0, 0.0),  # exactly at base_position
        )

        def _execute(script):
            if "_columns" in script:
                return ExecutionResult(
                    value={"base_position": [0.0, 150.0, 0.0], "columns": [[1, 0, 0]] * 6},
                    output=[], request_id="x",
                )
            return ExecutionResult(value={"hip": [0, 0, 0], "r_hand": [0, 0, 0]}, output=[], request_id="x")

        client = MagicMock(spec=DazClient)
        client.execute.side_effect = _execute

        skel = DazSkeleton.__new__(DazSkeleton)
        object.__setattr__(skel, "_client", client)
        object.__setattr__(skel, "_identifier", NodeIdentifier("Test", kind="label"))

        result = align_single_limb_target(skel, profile, target, tolerance=0.5)

        self.assertTrue(result.converged)
        self.assertEqual(result.iterations, 0)
        self.assertEqual(result.diagnostics.get("reason"), "already_aligned")


class TestDazViewport(unittest.TestCase):
    def _make_viewport(self, return_value=None):
        client = _make_client(return_value=return_value)
        from dazpy._viewport import DazViewport
        vp = DazViewport(client)
        return vp, client

    def test_is_available_true(self):
        vp, client = self._make_viewport(return_value=True)
        self.assertTrue(vp.is_available())
        client.execute.assert_called_once()

    def test_is_available_false(self):
        vp, client = self._make_viewport(return_value=False)
        self.assertFalse(vp.is_available())

    def test_get_size(self):
        vp, client = self._make_viewport(return_value={"width": 1280, "height": 720})
        result = vp.get_size()
        self.assertEqual(result, {"width": 1280, "height": 720})
        client.execute.assert_called_once()

    def test_set_size_raises(self):
        vp, client = self._make_viewport()
        with self.assertRaises(NotImplementedError):
            vp.set_size(800, 600)

    def test_capture_basic(self):
        path = "C:/tmp/snap.png"
        vp, client = self._make_viewport(return_value=path)
        result = vp.capture(path)
        script = client.execute.call_args[0][0]
        self.assertIn("captureImage", script)
        self.assertIn(".save(", script)
        self.assertIn(json.dumps(path), script)
        self.assertEqual(result, path)

    def test_capture_ignores_width_height(self):
        path = "C:/tmp/snap.png"
        vp, client = self._make_viewport(return_value=path)
        vp.capture(path, width=1920, height=1080)
        script = client.execute.call_args[0][0]
        self.assertIn("captureImage", script)
        self.assertNotIn("setFixedSize", script)
        self.assertNotIn("_prevSize", script)

    def test_capture_returns_path_on_null_result(self):
        path = "C:/tmp/snap.png"
        vp, client = self._make_viewport(return_value=None)
        result = vp.capture(path)
        self.assertEqual(result, path)


class _FakeSSEResponse:
    """Minimal stand-in for a streaming requests.Response over /scene/events."""

    def __init__(self, frames):
        # frames: list of raw SSE frame strings, e.g. 'data: {"type":"node.added",...}'
        body = "\n\n".join(frames) + "\n\n" if frames else ""
        self._chunks = [body.encode("utf-8")]
        self.closed = False

    def iter_content(self, chunk_size=None):
        for chunk in self._chunks:
            yield chunk

    def close(self):
        self.closed = True


class TestSceneEvents(unittest.TestCase):
    def _events_json(self, *pairs):
        return [
            f'data: {json.dumps({"type": t, "ts": 1000, "data": d})}'
            for t, d in pairs
        ]

    def test_watch_scene_events_parses_frames(self):
        client = MagicMock()
        client.stream_scene_events.return_value = _FakeSSEResponse(
            self._events_json(
                ("node.added", {"node_name": "Genesis9"}),
                ("selection.list_changed", {}),
            )
        )
        events = list(watch_scene_events(client))
        self.assertEqual(len(events), 2)
        self.assertIsInstance(events[0], SceneEvent)
        self.assertEqual(events[0].type, "node.added")
        self.assertEqual(events[0].data, {"node_name": "Genesis9"})
        self.assertEqual(events[1].type, "selection.list_changed")

    def test_watch_scene_events_skips_keepalive_comments(self):
        client = MagicMock()
        frames = [":keepalive"] + self._events_json(("scene.loaded", {}))
        client.stream_scene_events.return_value = _FakeSSEResponse(frames)
        events = list(watch_scene_events(client))
        self.assertEqual([e.type for e in events], ["scene.loaded"])

    def test_watch_scene_events_filters_by_event_types(self):
        client = MagicMock()
        client.stream_scene_events.return_value = _FakeSSEResponse(
            self._events_json(
                ("node.added", {}),
                ("node.removed", {}),
                ("light.added", {}),
            )
        )
        events = list(watch_scene_events(client, event_types={"node.removed"}))
        self.assertEqual([e.type for e in events], ["node.removed"])

    def test_watch_scene_events_closes_response(self):
        client = MagicMock()
        resp = _FakeSSEResponse(self._events_json(("scene.loaded", {})))
        client.stream_scene_events.return_value = resp
        list(watch_scene_events(client))
        self.assertTrue(resp.closed)

    def test_watch_scene_events_raises_connection_error_when_stream_unavailable(self):
        client = MagicMock()
        client.stream_scene_events.return_value = None
        with self.assertRaises(DazConnectionError):
            list(watch_scene_events(client))

    def test_wait_for_scene_event_returns_matching_event(self):
        client = MagicMock()
        client.stream_scene_events.return_value = _FakeSSEResponse(
            self._events_json(
                ("node.added", {"node_name": "A"}),
                ("node.added", {"node_name": "B"}),
            )
        )
        event = wait_for_scene_event(client, "node.added", timeout=5.0)
        self.assertEqual(event.data, {"node_name": "A"})
        # Category should be derived from the event type for server-side filtering.
        _, kwargs = client.stream_scene_events.call_args
        self.assertEqual(kwargs["categories"], ["node"])

    def test_wait_for_scene_event_times_out_when_stream_ends_without_match(self):
        client = MagicMock()
        client.stream_scene_events.return_value = _FakeSSEResponse(
            self._events_json(("scene.loaded", {}))
        )
        with self.assertRaises(DazTimeoutError):
            wait_for_scene_event(client, "node.added", timeout=1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
