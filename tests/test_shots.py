"""Unit tests for dazpy.shots (typed Shot / Sequence / CoveragePlan models). No Studio."""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from dazpy.math3 import Vec3
from dazpy.shots import (
    CAMERA_ANGLES, SHOT_SIZES, AspectSettings, BlockingBeat, CameraKeyframe, CoveragePlan, FocusKey,
    FocusPull, Framing, GazeBeat, Keyframed, Lens, Orbit, Placement, RenderOutput, Sequence, Shot,
    Storyboard, apply_shot, framing_distance, framing_transform, shot_from_recipe_camera,
)
from dazpy._recipe_desired import compute_desired
from dazpy._recipe_model import SceneRecipe
from dazpy._recipe_validate import validate_offline


class FakeCamera:
    def __init__(self):
        self.calls = []
        self._client = MagicMock()

    def __setattr__(self, name, value):
        if name in ("calls", "_client"):
            object.__setattr__(self, name, value)
        else:
            self.calls.append(("set", name, value))
            object.__setattr__(self, name, value)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def record(*args, **kwargs):
            self.calls.append((name,) + args + ((kwargs,) if kwargs else ()))
        return record


class FakeScene:
    def __init__(self):
        self.created = []
        self.anim_ranges = []

    def create_camera(self, name=None):
        cam = FakeCamera()
        self.created.append((name, cam))
        return cam

    def set_anim_range(self, start, end):
        self.anim_ranges.append((start, end))


class _Node:
    position = {"x": 10.0, "y": 0.0, "z": 0.0}


def full_shot():
    return Shot(
        id="anna_mcu",
        camera=Framing(subjects=("anna",), size="medium_close_up", angle="low", azimuth_deg=30,
                       composition="left_third"),
        lens=Lens(focal_length=85, depth_of_field=True, focal_distance=120, f_stop=2.8),
        focus=FocusPull(keys=(FocusKey(0, 120.0), FocusKey(24, 300.0))),
        frame_range=(0, 48),
        aspect=AspectSettings(pixels_width=1920, pixels_height=1080),
        blocking=(BlockingBeat(0, "anna", Vec3(0, 0, 0), facing="ben", note="enters"),),
        gaze=(GazeBeat(12, "anna", "ben"), GazeBeat(30, "anna", Vec3(0, 160, 300))),
        lighting="day_key",
        storyboard=Storyboard(description="Anna reacts", dialogue="No.", beat="turn"),
        output=RenderOutput(path="C:/r/anna.png", engine="iray", resolution=(1080, 1350), iray_samples=100),
    )


class SerialisationTests(unittest.TestCase):
    def test_full_shot_round_trips_through_json(self):
        shot = full_shot()
        d = json.loads(json.dumps(shot.to_dict()))
        self.assertEqual(Shot.from_dict(d), shot)
        self.assertEqual(d["camera"]["kind"], "framing")

    def test_moving_shots_round_trip(self):
        orbit = Shot(id="o", camera=Placement(position=Vec3(0, 0, 0), look_at="anna"),
                     movement=Orbit(radius=200, frame_end=10))
        keyed = Shot(id="k", camera=Placement(position=Vec3(0, 100, 300)), movement=Keyframed(keyframes=(
            CameraKeyframe(0, Vec3(0, 100, 300), look_at="anna"),
            CameraKeyframe(24, Vec3(0, 150, 200), look_at=Vec3(0, 140, 0), look_at_offset_cm=5))))
        for s in (orbit, keyed):
            with self.subTest(s.id):
                self.assertEqual(Shot.from_dict(json.loads(json.dumps(s.to_dict()))), s)

    def test_defaults_are_omitted(self):
        d = Shot(id="s", camera=Framing(subjects=("a",))).to_dict()
        self.assertEqual(d, {"id": "s", "camera": {"kind": "framing", "subjects": ["a"]}})

    def test_coverage_plan_round_trips(self):
        plan = CoveragePlan(id="cafe", subjects=("anna", "ben"), axis=("anna", "ben"), lighting="day_key",
                            sequences=(Sequence(id="s1", shots=(full_shot(),), lighting="night"),),
                            storyboard=Storyboard(notes="keep left-to-right"))
        self.assertEqual(CoveragePlan.from_dict(json.loads(json.dumps(plan.to_dict()))), plan)

    def test_daznode_target_is_not_serialisable(self):
        shot = Shot(id="s", camera=Placement(position=Vec3(0, 0, 0), look_at=_Node()))
        with self.assertRaisesRegex(TypeError, r"camera\.look_at"):
            shot.to_dict()

    def test_daznode_detection_never_reads_position(self):
        class Spy:
            reads = 0

            @property
            def position(self):
                Spy.reads += 1
                return {"x": 0, "y": 0, "z": 0}
        Framing(subjects=(Spy(),))
        self.assertEqual(Spy.reads, 0)

    def test_from_dict_errors_name_the_path(self):
        cases = [
            ({"id": "s", "camera": {"kind": "framing", "subjects": ["a"], "size": "huge"}}, r"camera.*size"),
            ({"id": "s", "camera": {"kind": "framing", "subjects": ["a"], "zoom": 2}}, r"camera\.zoom: unknown"),
            ({"id": "s", "camera": {"subjects": ["a"]}}, r"camera: needs 'kind'"),
            ({"id": "s", "camera": {"kind": "placement", "position": [1, 2]}}, r"camera\.position"),
            ({"id": "s", "camera": {"kind": "framing", "subjects": ["a"]},
              "focus": {"keys": [{"frame": 5, "focal_distance": 1}, {"frame": 2, "focal_distance": 1}]}},
             r"focus.*ascending"),
        ]
        for data, pattern in cases:
            with self.subTest(pattern):
                with self.assertRaisesRegex(ValueError, pattern):
                    Shot.from_dict(data)

    def test_model_invariants(self):
        with self.assertRaises(ValueError):
            Framing(subjects=())
        with self.assertRaises(ValueError):
            Lens(focal_length=0)
        with self.assertRaises(ValueError):
            Shot(id="s", camera=Framing(subjects=("a",)), movement=Keyframed(keyframes=(
                CameraKeyframe(0, Vec3(0, 0, 0)), CameraKeyframe(1, Vec3(1, 0, 0)))))
        with self.assertRaisesRegex(ValueError, "duplicate shot id"):
            Sequence(id="q", shots=(Shot(id="a", camera=Framing(subjects=("x",))),) * 2)
        with self.assertRaisesRegex(ValueError, "not in subjects"):
            CoveragePlan(id="p", subjects=("anna",), axis=("anna", "ben"))
        a = Shot(id="a", camera=Framing(subjects=("x",)))
        with self.assertRaisesRegex(ValueError, "duplicate shot id"):
            CoveragePlan(id="p", sequences=(Sequence(id="1", shots=(a,)), Sequence(id="2", shots=(a,))))

    def test_lighting_continuity_falls_back_shot_sequence_plan(self):
        own = Shot(id="own", camera=Framing(subjects=("x",)), lighting="a")
        seq_lit = Shot(id="seq", camera=Framing(subjects=("x",)))
        plan_lit = Shot(id="plan", camera=Framing(subjects=("x",)))
        plan = CoveragePlan(id="p", lighting="c", sequences=(
            Sequence(id="1", shots=(own, seq_lit), lighting="b"), Sequence(id="2", shots=(plan_lit,))))
        self.assertEqual([plan.lighting_for(s) for s in plan.all_shots()], ["a", "b", "c"])


class GeometryTests(unittest.TestCase):
    def test_recipe_sizes_are_unchanged(self):
        self.assertEqual(SHOT_SIZES["full_body"], (210.0, 90.0))
        self.assertEqual(SHOT_SIZES["medium"], (100.0, 130.0))
        self.assertEqual(SHOT_SIZES["close_up"], (40.0, 160.0))

    def test_sizes_get_tighter_and_aim_higher(self):
        order = ["extreme_wide", "wide", "full_body", "medium_wide", "medium", "medium_close_up",
                 "close_up", "extreme_close_up"]
        fits = [SHOT_SIZES[s][0] for s in order]
        anchors = [SHOT_SIZES[s][1] for s in order]
        self.assertEqual(fits, sorted(fits, reverse=True))
        self.assertEqual(anchors, sorted(anchors))

    def test_distance_fits_the_frame(self):
        # Studio applies the lens FOV to the frame height: 36 mm spans the height at any aspect.
        self.assertAlmostEqual(framing_distance("close_up", 85), 40 * 85 / 36)
        self.assertAlmostEqual(framing_distance("close_up", 85, aspect=1.5), 40 * 85 / 36)

    def test_fitted_height_fills_the_frame_in_studios_projection(self):
        # Cross-check against _scene_check.frame_extent (live-verified, 5d6f.22): Studio's
        # vertical FOV is 2*atan(frame_width / (2*f)) at any aspect.
        import math
        from dazpy._scene_check import frame_extent
        f = 50.0
        pos, aim = framing_transform([(Vec3(0, 0, 0), True)],
                                     Framing(subjects=("a",), size="full_body", elevation_deg=0), f)
        self.assertAlmostEqual(pos.x, aim.x)  # looking straight down -Z: identity rotation
        cam = {"pos": [pos.x, pos.y, pos.z], "rot": [0.0, 0.0, 0.0, 1.0],
               "fov": 2 * math.atan(36.0 / (2 * f))}
        box = [-1.0, aim.y - 105.0, -1e-3, 1.0, aim.y + 105.0, 1e-3]  # 210 cm tall at the aim
        for w_over_h in (4 / 3, 2 / 3):
            (_, _, y0, y1), behind = frame_extent(cam, w_over_h, box)
            self.assertEqual(behind, 0)
            self.assertAlmostEqual(y0, -1.0, places=4)
            self.assertAlmostEqual(y1, 1.0, places=4)

    def test_angle_sets_elevation_unless_overridden(self):
        f = Framing(subjects=("a",), angle="high")
        self.assertEqual(f.effective_elevation_deg, CAMERA_ANGLES["high"])
        self.assertEqual(Framing(subjects=("a",), angle="high", elevation_deg=5).effective_elevation_deg, 5)
        pos, aim = framing_transform([(Vec3(0, 0, 0), True)], f, 50)
        self.assertGreater(pos.y, aim.y)

    def test_figure_points_are_raised_vec3_points_are_not(self):
        f = Framing(subjects=("a", "b"), size="medium")
        _, aim = framing_transform([(Vec3(0, 0, 0), True), (Vec3(100, 0, 0), False)], f, 50)
        self.assertEqual(aim, Vec3(50, 65, 0))

    def test_left_third_turns_the_camera_so_the_subject_sits_left(self):
        f = Framing(subjects=("a",), size="medium", composition="left_third")
        pos, aim = framing_transform([(Vec3(0, 0, 0), True)], f, 50)
        centre_pos, centre_aim = framing_transform([(Vec3(0, 0, 0), True)],
                                                   Framing(subjects=("a",), size="medium"), 50)
        self.assertEqual(pos, centre_pos)  # the camera does not move
        # Camera on +Z looking -Z: screen-right is +X; aim right so the subject is left.
        dist = framing_distance("medium", 50)
        # Frame height = 36 mm at f; width = height / aspect (h/w, 3/4 default).
        self.assertAlmostEqual(aim.x - centre_aim.x, dist * 36 / 50 / (3 / 4) / 6)
        right = framing_transform([(Vec3(0, 0, 0), True)],
                                  Framing(subjects=("a",), size="medium", composition="right_third"), 50)[1]
        self.assertAlmostEqual(right.x, -aim.x)

    def test_recipe_framing_uses_the_shared_geometry(self):
        recipe = SceneRecipe.from_dict({
            "recipe_version": 1, "id": "r", "assets": {"g": {"path": "/G.duf"}},
            "actors": {"anna": {"asset": "g", "position": [-60, 0, 0]}},
            "cameras": {"c": {"frame": "anna", "shot_type": "medium_close_up", "angle": "low",
                              "composition": "right_third", "focal_length": 85}}})
        t = compute_desired(recipe)["cameras.c"].channels["transform"]
        shot = shot_from_recipe_camera("c", {"frame": "anna", "shot_type": "medium_close_up", "angle": "low",
                                             "composition": "right_third", "focal_length": 85})
        pos, aim = framing_transform([(Vec3(-60, 0, 0), True)], shot.camera, 85)
        self.assertEqual(t["position"], (pos.x, pos.y, pos.z))
        self.assertEqual(t["aim"], (aim.x, aim.y, aim.z))


class ApplyTests(unittest.TestCase):
    def test_framing_resolves_keys_through_subjects(self):
        scene = FakeScene()
        shot = Shot(id="s", camera=Framing(subjects=("anna",), size="close_up"), lens=Lens(focal_length=85))
        cam = apply_shot(scene, shot, name="CU", subjects={"anna": Vec3(-60, 0, 0)})
        self.assertEqual(scene.created[0][0], "CU")
        aim = [c for c in cam.calls if c[0] == "aim_at"][0]
        self.assertEqual(aim, ("aim_at", -60.0, 160.0, 0.0))
        self.assertIn(("set", "focal_length", 85), cam.calls)
        self.assertNotIn("depth_of_field", [c[1] for c in cam.calls if c[0] == "set"])

    def test_framing_daznode_subject_is_raised(self):
        cam = apply_shot(FakeScene(), Shot(id="s", camera=Framing(subjects=(_Node(),), size="medium")))
        self.assertEqual([c for c in cam.calls if c[0] == "aim_at"], [("aim_at", 10.0, 130.0, 0.0)])

    def test_unresolved_key_raises_before_creating_a_camera(self):
        scene = FakeScene()
        with self.assertRaisesRegex(ValueError, "anna"):
            apply_shot(scene, Shot(id="s", camera=Framing(subjects=("anna",))))
        # framing resolves after creation; an orbit without a target fails first
        scene2 = FakeScene()
        with self.assertRaisesRegex(ValueError, "Orbit needs a target"):
            apply_shot(scene2, Shot(id="o", camera=Placement(position=Vec3(0, 0, 0)), movement=Orbit(radius=1)))
        self.assertEqual(scene2.created, [])

    def test_focus_pull_keys_focal_distance_and_enables_dof(self):
        cam = FakeCamera()
        apply_shot(FakeScene(), full_shot(), camera=cam, subjects={"anna": Vec3(0, 0, 0)})
        tail = cam.calls[-4:]
        self.assertEqual(tail, [("set", "depth_of_field", True), ("clear_focal_distance_keys",),
                                ("set_focal_distance_at_frame", 0, 120.0),
                                ("set_focal_distance_at_frame", 24, 300.0)])
        self.assertIn(("set", "f_stop", 2.8), cam.calls)
        self.assertIn(("set", "pixels_width", 1920), cam.calls)

    def test_clear_keys_false_keeps_existing_keys(self):
        cam = FakeCamera()
        shot = Shot(id="k", camera=Placement(position=Vec3(0, 0, 0)), movement=Keyframed(keyframes=(
            CameraKeyframe(0, Vec3(0, 0, 0), rotation=(0, 0, 0)), CameraKeyframe(9, Vec3(1, 0, 0), rotation=(0, 5, 0)))),
            focus=FocusPull(keys=(FocusKey(0, 100.0), FocusKey(9, 200.0))))
        apply_shot(FakeScene(), shot, camera=cam, clear_keys=False)
        names = [c[0] for c in cam.calls]
        for n in ("clear_position_keys", "clear_rotation_keys", "clear_focal_distance_keys"):
            self.assertNotIn(n, names)
        self.assertEqual(names.count("set_position_at_frame"), 2)
        apply_shot(FakeScene(), shot, camera=cam)
        self.assertIn("clear_position_keys", [c[0] for c in cam.calls])

    def test_keyframed_look_at_key_resolves_through_subjects(self):
        cam = FakeCamera()
        shot = Shot(id="k", camera=Placement(position=Vec3(0, 100, 300)), movement=Keyframed(keyframes=(
            CameraKeyframe(0, Vec3(0, 100, 300), look_at="anna", look_at_offset_cm=100),
            CameraKeyframe(10, Vec3(0, 100, 200), look_at="anna", look_at_offset_cm=100))))
        apply_shot(FakeScene(), shot, camera=cam, subjects={"anna": Vec3(0, 0, 0)})
        rots = [c for c in cam.calls if c[0] == "set_rotation_at_frame"]
        self.assertEqual(len(rots), 2)
        self.assertAlmostEqual(rots[0][2], 0.0)  # straight down -Z: no yaw
        self.assertAlmostEqual(rots[0][1], 0.0)  # level: aim at the camera's own height


class CameraKeyMethodTests(unittest.TestCase):
    def test_focal_distance_key_script(self):
        from dazpy._camera import DazCamera
        from dazpy._node import NodeIdentifier
        client = MagicMock()
        cam = DazCamera(client, NodeIdentifier("Camera 1"))
        cam.set_focal_distance_at_frame(12, 250)
        script = client.execute.call_args[0][0]
        self.assertIn("12 * Scene.getTimeStep()", script)
        self.assertIn("getFocalDistanceControl().setDoubleValue(_tm, 250.0)", script)
        cam.clear_focal_distance_keys()
        self.assertIn("getFocalDistanceControl().deleteAllKeys()", client.execute.call_args[0][0])


class RecipeConversionTests(unittest.TestCase):
    BASE = {"recipe_version": 1, "id": "cafe", "assets": {"g9": {"path": "/People/G9.duf"}},
            "actors": {"anna": {"asset": "g9", "position": [-60, 0, 0]},
                       "ben": {"asset": "g9", "position": [60, 0, 0]}}}

    def plan(self):
        two = Shot(id="two", camera=Framing(subjects=("anna", "ben"), size="wide", angle="high"),
                   lens=Lens(focal_length=35), output=RenderOutput(path="C:/r/two.png"))
        ots = Shot(id="ots", camera=Placement(position=Vec3(80, 160, 80), look_at="anna"),
                   lens=Lens(focal_length=50, depth_of_field=True, focal_distance=150),
                   output=RenderOutput(path="C:/r/ots.png", resolution=(1080, 1350)))
        cu = Shot(id="cu", camera=Framing(subjects=("anna",), size="close_up", elevation_deg=5,
                                          composition="left_third"), lens=Lens(focal_length=85),
                  storyboard=Storyboard(description="dropped in conversion"))
        return CoveragePlan(id="cafe", subjects=("anna", "ben"), axis=("anna", "ben"),
                            sequences=(Sequence(id="s", shots=(two, ots, cu)),))

    def test_coverage_plan_merges_into_a_valid_recipe(self):
        recipe = self.plan().merge_into_recipe(self.BASE)
        report = validate_offline(recipe)
        self.assertTrue(report.ok, report.errors)
        self.assertEqual([s["id"] for s in recipe["shots"]], ["two", "ots"])
        self.assertEqual(recipe["cameras"]["two"]["angle"], "high")
        self.assertEqual(recipe["shots"][1]["render"], {"resolution": [1080, 1350]})
        self.assertNotIn("cameras", self.BASE)  # input untouched

    def test_round_trip_through_recipe_preserves_the_camera(self):
        for shot in self.plan().all_shots():
            with self.subTest(shot.id):
                cam, spec = shot.to_recipe()
                back = shot_from_recipe_camera(shot.id, cam, spec)
                self.assertEqual(back.camera, shot.camera)
                self.assertEqual(back.output, shot.output)
                self.assertEqual(back.lens.focal_length, shot.lens.focal_length)

    def test_merge_refuses_clashes(self):
        recipe = dict(self.BASE, cameras={"two": {"frame": "anna"}})
        with self.assertRaisesRegex(ValueError, "two"):
            self.plan().merge_into_recipe(recipe)

    def test_unsupported_shots_refuse_to_convert(self):
        moving = Shot(id="m", camera=Placement(position=Vec3(0, 0, 0), look_at="anna"),
                      movement=Orbit(radius=100))
        pulled = Shot(id="f", camera=Framing(subjects=("anna",)),
                      focus=FocusPull(keys=(FocusKey(0, 1.0), FocusKey(1, 2.0))))
        vec_subject = Shot(id="v", camera=Framing(subjects=(Vec3(0, 0, 0),)))
        node = Shot(id="n", camera=Framing(subjects=(_Node(),)))
        for shot, exc in ((moving, ValueError), (pulled, ValueError), (vec_subject, ValueError),
                          (node, TypeError)):
            with self.subTest(shot.id):
                with self.assertRaises(exc):
                    shot.to_recipe()

    def test_recipe_camera_without_angle_keeps_the_ten_degree_default(self):
        shot = shot_from_recipe_camera("c", {"frame": "anna"})
        self.assertEqual(shot.camera.effective_elevation_deg, 10.0)
        cam, _ = shot.to_recipe()
        self.assertEqual(cam, {"frame": "anna", "elevation_deg": 10.0, "focal_length": 50.0})


class AdapterTests(unittest.TestCase):
    """The cinematics builders are adapters over Shot (behaviour tests live in test_dazpy.py)."""

    def test_each_builder_converts_to_a_shot(self):
        from dazpy.cinematics import CinematicAnimatedShot, CinematicStaticShot, FrameSubject, OrbitCamera
        static = CinematicStaticShot(position=Vec3(0, 0, 150), look_at=Vec3(0, 0, 0), pixels_width=640)
        self.assertIsInstance(static.to_shot().camera, Placement)
        self.assertEqual(static.to_shot().aspect, AspectSettings(pixels_width=640))
        self.assertIsNone(CinematicStaticShot(position=Vec3(0, 0, 1)).to_shot().aspect)
        fs = FrameSubject(subject=Vec3(0, 0, 0), shot_type="close_up").to_shot()
        self.assertEqual((fs.camera.distance_cm, fs.camera.anchor_cm), (60.0, 45.0))
        self.assertIsNone(fs.lens.depth_of_field)
        self.assertIsInstance(OrbitCamera(target=Vec3(0, 0, 0), radius=100).to_shot().movement, Orbit)
        anim = CinematicAnimatedShot(keyframes=(CameraKeyframe(0, Vec3(0, 0, 1)), CameraKeyframe(5, Vec3(1, 0, 1))))
        self.assertIsInstance(anim.to_shot().movement, Keyframed)

    def test_camera_keyframe_is_still_importable_from_cinematics(self):
        from dazpy import cinematics
        self.assertIs(cinematics.CameraKeyframe, CameraKeyframe)

    def test_animated_shot_easing_reaches_the_keyframed_move(self):
        from dazpy.cinematics import CinematicAnimatedShot
        keys = (CameraKeyframe(0, Vec3(0, 0, 1)), CameraKeyframe(5, Vec3(1, 0, 1)))
        self.assertEqual(CinematicAnimatedShot(keyframes=keys, easing="ease_out").to_shot().movement.easing, "ease_out")
        self.assertIsNone(CinematicAnimatedShot(keyframes=keys).to_shot().movement.easing)


def _keys(*interps):
    return tuple(CameraKeyframe(i * 10, Vec3(i, 0, 0), interpolation=k) for i, k in enumerate(interps))


class EasingTests(unittest.TestCase):
    """v6rm: per-key interpolation and whole-move easing on Keyframed."""

    def test_defaults_are_omitted_and_round_trip(self):
        plain = Keyframed(keyframes=_keys(None, None))
        self.assertNotIn("easing", plain.to_dict())
        self.assertNotIn("interpolation", plain.to_dict()["keyframes"][0])
        eased = Keyframed(keyframes=_keys("constant", None), easing="ease_in")
        d = eased.to_dict()
        self.assertEqual((d["easing"], d["keyframes"][0]["interpolation"]), ("ease_in", "constant"))
        self.assertEqual(Keyframed.from_dict(json.loads(json.dumps(d))), eased)

    def test_unknown_values_are_rejected_with_their_path(self):
        with self.assertRaisesRegex(ValueError, "interpolation"):
            CameraKeyframe(0, Vec3(0, 0, 0), interpolation="bezier")
        with self.assertRaisesRegex(ValueError, "easing"):
            Keyframed(keyframes=_keys(None, None), easing="ease-in")
        bad = {"kind": "keyframed", "keyframes": [{"frame": 0, "position": [0, 0, 0], "interpolation": "tcb"},
                                                  {"frame": 1, "position": [1, 0, 0]}]}
        with self.assertRaisesRegex(ValueError, r"keyframes\[0\]"):
            Keyframed.from_dict(bad)

    def test_key_interpolation_plan(self):
        self.assertIsNone(Keyframed(keyframes=_keys(None, None, None)).key_interpolation())
        self.assertEqual(Keyframed(keyframes=_keys(None, None), easing="linear").key_interpolation(),
                         (("linear", "linear"), False, False))
        self.assertEqual(Keyframed(keyframes=_keys(None, None), easing="smooth").key_interpolation(),
                         (("smooth", "smooth"), False, False))
        self.assertEqual(Keyframed(keyframes=_keys(None, None, None), easing="ease_in").key_interpolation(),
                         (("hermite",) * 3, False, True))
        self.assertEqual(Keyframed(keyframes=_keys(None, None, None), easing="ease_out").key_interpolation(),
                         (("hermite",) * 3, True, False))
        # A waypoint's own interpolation overrides the move's easing; without easing only it is set.
        self.assertEqual(Keyframed(keyframes=_keys(None, "constant", None), easing="ease_in").key_interpolation(),
                         (("hermite", "constant", "hermite"), False, True))
        self.assertEqual(Keyframed(keyframes=_keys("linear", None)).key_interpolation(),
                         (("linear", None), False, False))

    def test_apply_shot_sets_interpolation_after_the_keys(self):
        cam = FakeCamera()
        shot = Shot(id="k", camera=Placement(position=Vec3(0, 0, 0)),
                    movement=Keyframed(keyframes=(CameraKeyframe(0, Vec3(0, 0, 0), rotation=(0, 0, 0)),
                                                  CameraKeyframe(24, Vec3(9, 0, 0), rotation=(0, 5, 0))),
                                       easing="ease_out"))
        apply_shot(FakeScene(), shot, camera=cam)
        names = [c[0] for c in cam.calls]
        idx = names.index("set_transform_key_interpolation")
        self.assertGreater(idx, max(i for i, n in enumerate(names) if n == "set_rotation_at_frame"))
        self.assertEqual(cam.calls[idx], ("set_transform_key_interpolation", [0, 24], ("hermite", "hermite"),
                                          {"rotation": True, "fast_start": True, "fast_end": False}))

    def test_apply_shot_without_easing_sends_no_interpolation(self):
        cam = FakeCamera()
        shot = Shot(id="k", camera=Placement(position=Vec3(0, 0, 0)), movement=Keyframed(keyframes=_keys(None, None)))
        apply_shot(FakeScene(), shot, camera=cam)
        self.assertNotIn("set_transform_key_interpolation", [c[0] for c in cam.calls])

    def test_node_interpolation_script(self):
        from dazpy._camera import DazCamera
        from dazpy._node import NodeIdentifier
        client = MagicMock()
        cam = DazCamera(client, NodeIdentifier("Camera 1"))
        cam.set_transform_key_interpolation([0, 10, 30], ["hermite", "linear", None], fast_end=True)
        script = client.execute.call_args[0][0]
        self.assertIn('var _F = [0, 10, 30], _K = ["hermite", "linear", null]', script)
        for ctl in ("XPos", "YPos", "ZPos", "XRot", "YRot", "ZRot"):
            self.assertIn(f"_node.get{ctl}Control()", script)
        self.assertIn("_kiApply(_C[_c], _F, _K, false, true);", script)
        self.assertIn("DzProperty.InterpHermite", script)
        cam.set_transform_key_interpolation([0, 10], ["smooth", "smooth"], rotation=False)
        self.assertNotIn("XRotControl", client.execute.call_args[0][0])

    def test_key_interp_js_matches_daz_ts(self):
        """daz-ts/src/node.ts carries the same _kiApply helper, line for line."""
        import re
        from dazpy._node import _KEY_INTERP_JS
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
        with open(os.path.join(root, "daz-ts", "src", "node.ts"), encoding="utf-8") as fh:
            src = fh.read()
        block = re.search(r"const KEY_INTERP_JS =\n(.*?);\n", src, re.S)
        self.assertIsNotNone(block, "KEY_INTERP_JS not found in daz-ts/src/node.ts")
        lines = [json.loads(m) for m in re.findall(r'^\s*("(?:[^"\\]|\\.)*")(?: \+)?$', block.group(1), re.M)]
        self.assertEqual("".join(lines), _KEY_INTERP_JS)

    def test_node_interpolation_validation(self):
        from dazpy._node import DazNode, NodeIdentifier
        node = DazNode(MagicMock(), NodeIdentifier("n"))
        with self.assertRaisesRegex(ValueError, "same length"):
            node.set_transform_key_interpolation([0, 1], ["linear"])
        with self.assertRaisesRegex(ValueError, "ascending"):
            node.set_transform_key_interpolation([5, 1], ["linear", "linear"])
        with self.assertRaisesRegex(ValueError, "unknown key interpolation"):
            node.set_transform_key_interpolation([0, 1], ["ease_in", None])


if __name__ == "__main__":
    unittest.main()
