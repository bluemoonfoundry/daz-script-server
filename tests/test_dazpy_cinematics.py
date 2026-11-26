"""dazpy unit tests: cinematic shots: static, orbit, frame-subject, animated.

Mock-based; no server or DAZ Studio required.
Shared fakes live in tests/dazpy_fakes.py.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))



class _FakeCinematicsCamera:
    def __init__(self, name: str | None = None):
        self.name = name
        self.position_calls: list[tuple[float, float, float]] = []
        self.rotation_calls: list[tuple[float, float, float]] = []
        self.aim_at_calls: list[tuple[float, float, float]] = []
        self.focal_length: float | None = None
        self.depth_of_field: bool | None = None
        self.focal_distance: float | None = None
        self.aspect_width: float | None = None
        self.aspect_height: float | None = None
        self.pixels_width: int | None = None
        self.pixels_height: int | None = None
        self.position_at_frame_calls: list[tuple[int, float, float, float]] = []
        self.rotation_at_frame_calls: list[tuple[int, float, float, float]] = []
        self.clear_position_keys_calls: int = 0
        self.clear_rotation_keys_calls: int = 0
        self._client = MagicMock()

    def set_position(self, x, y, z):
        self.position_calls.append((x, y, z))

    def set_rotation(self, x, y, z):
        self.rotation_calls.append((x, y, z))

    def aim_at(self, x, y, z):
        self.aim_at_calls.append((x, y, z))

    def set_position_at_frame(self, frame, x, y, z):
        self.position_at_frame_calls.append((frame, x, y, z))

    def set_rotation_at_frame(self, frame, x, y, z):
        self.rotation_at_frame_calls.append((frame, x, y, z))

    def clear_position_keys(self):
        self.clear_position_keys_calls += 1

    def clear_rotation_keys(self):
        self.clear_rotation_keys_calls += 1


class _FakeCinematicsScene:
    def __init__(self):
        self.created: list[_FakeCinematicsCamera] = []
        self.anim_range_calls: list[tuple[int, int]] = []

    def create_camera(self, name: str | None = None) -> _FakeCinematicsCamera:
        cam = _FakeCinematicsCamera(name)
        self.created.append(cam)
        return cam

    def set_anim_range(self, start: int, end: int) -> None:
        self.anim_range_calls.append((start, end))


class TestCinematicStaticShot(unittest.TestCase):
    def test_defaults(self):
        from dazpy.cinematics import CinematicStaticShot
        from dazpy.math3 import Vec3
        shot = CinematicStaticShot(position=Vec3(0, 0, 150))
        self.assertIsNone(shot.look_at)
        self.assertEqual(shot.look_at_offset_cm, 0.0)
        self.assertIsNone(shot.rotation)
        self.assertEqual(shot.focal_length, 50.0)
        self.assertFalse(shot.depth_of_field)
        self.assertIsNone(shot.focal_distance)
        self.assertIsNone(shot.aspect_width)
        self.assertIsNone(shot.aspect_height)
        self.assertIsNone(shot.pixels_width)
        self.assertIsNone(shot.pixels_height)

    def test_is_frozen(self):
        from dazpy.cinematics import CinematicStaticShot
        from dazpy.math3 import Vec3
        shot = CinematicStaticShot(position=Vec3(0, 0, 150))
        with self.assertRaises(Exception):
            shot.focal_length = 85.0

    def test_apply_creates_new_camera_when_none_given(self):
        from dazpy.cinematics import CinematicStaticShot, apply_static_shot
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        shot = CinematicStaticShot(position=Vec3(0, 0, 150))
        cam = apply_static_shot(scene, shot, name="Shot 1")
        self.assertEqual(len(scene.created), 1)
        self.assertIs(cam, scene.created[0])
        self.assertEqual(cam.name, "Shot 1")

    def test_apply_reuses_given_camera(self):
        from dazpy.cinematics import CinematicStaticShot, apply_static_shot
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        existing = _FakeCinematicsCamera("MyCam")
        shot = CinematicStaticShot(position=Vec3(0, 0, 150))
        cam = apply_static_shot(scene, shot, camera=existing)
        self.assertIs(cam, existing)
        self.assertEqual(len(scene.created), 0)

    def test_apply_sets_position(self):
        from dazpy.cinematics import CinematicStaticShot, apply_static_shot
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        shot = CinematicStaticShot(position=Vec3(1.0, 2.0, 3.0))
        cam = apply_static_shot(scene, shot)
        self.assertEqual(cam.position_calls, [(1.0, 2.0, 3.0)])

    def test_apply_calls_aim_at_when_look_at_vec3_given(self):
        from dazpy.cinematics import CinematicStaticShot, apply_static_shot
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        shot = CinematicStaticShot(position=Vec3(0, 0, 150), look_at=Vec3(0, 0, 0))
        cam = apply_static_shot(scene, shot)
        self.assertEqual(cam.aim_at_calls, [(0.0, 0.0, 0.0)])
        self.assertEqual(cam.rotation_calls, [])

    def test_apply_applies_look_at_offset_to_daznode_target(self):
        from dazpy.cinematics import CinematicStaticShot, apply_static_shot
        from dazpy.math3 import Vec3

        class _Node:
            position = {"x": 0.0, "y": 100.0, "z": 0.0}

        scene = _FakeCinematicsScene()
        shot = CinematicStaticShot(position=Vec3(0, 0, 150), look_at=_Node(), look_at_offset_cm=20.0)
        cam = apply_static_shot(scene, shot)
        self.assertEqual(cam.aim_at_calls, [(0.0, 120.0, 0.0)])

    def test_apply_calls_set_rotation_when_only_rotation_given(self):
        from dazpy.cinematics import CinematicStaticShot, apply_static_shot
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        shot = CinematicStaticShot(position=Vec3(0, 0, 150), rotation=(10.0, 20.0, 30.0))
        cam = apply_static_shot(scene, shot)
        self.assertEqual(cam.rotation_calls, [(10.0, 20.0, 30.0)])
        self.assertEqual(cam.aim_at_calls, [])

    def test_apply_touches_neither_orientation_when_both_none(self):
        from dazpy.cinematics import CinematicStaticShot, apply_static_shot
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        shot = CinematicStaticShot(position=Vec3(0, 0, 150))
        cam = apply_static_shot(scene, shot)
        self.assertEqual(cam.aim_at_calls, [])
        self.assertEqual(cam.rotation_calls, [])

    def test_apply_always_writes_focal_length_and_depth_of_field(self):
        from dazpy.cinematics import CinematicStaticShot, apply_static_shot
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        shot = CinematicStaticShot(position=Vec3(0, 0, 150), focal_length=85.0, depth_of_field=True)
        cam = apply_static_shot(scene, shot)
        self.assertEqual(cam.focal_length, 85.0)
        self.assertTrue(cam.depth_of_field)

    def test_apply_writes_optional_fields_only_when_not_none(self):
        from dazpy.cinematics import CinematicStaticShot, apply_static_shot
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        shot = CinematicStaticShot(position=Vec3(0, 0, 150))
        cam = apply_static_shot(scene, shot)
        self.assertIsNone(cam.focal_distance)
        self.assertIsNone(cam.aspect_width)
        self.assertIsNone(cam.aspect_height)
        self.assertIsNone(cam.pixels_width)
        self.assertIsNone(cam.pixels_height)

    def test_apply_writes_all_optional_fields_when_given(self):
        from dazpy.cinematics import CinematicStaticShot, apply_static_shot
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        shot = CinematicStaticShot(
            position=Vec3(0, 0, 150), focal_distance=175.0,
            aspect_width=16.0, aspect_height=9.0,
            pixels_width=1920, pixels_height=1080,
        )
        cam = apply_static_shot(scene, shot)
        self.assertEqual(cam.focal_distance, 175.0)
        self.assertEqual(cam.aspect_width, 16.0)
        self.assertEqual(cam.aspect_height, 9.0)
        self.assertEqual(cam.pixels_width, 1920)
        self.assertEqual(cam.pixels_height, 1080)


class TestOrbitCamera(unittest.TestCase):
    def test_defaults(self):
        from dazpy.cinematics import OrbitCamera
        from dazpy.math3 import Vec3
        orbit = OrbitCamera(target=Vec3(0, 0, 0), radius=200.0)
        self.assertEqual(orbit.elevation_deg, 15.0)
        self.assertEqual(orbit.start_azimuth_deg, 0.0)
        self.assertEqual(orbit.end_azimuth_deg, 360.0)
        self.assertEqual(orbit.frame_start, 0)
        self.assertEqual(orbit.frame_end, 90)
        self.assertEqual(orbit.focal_length, 50.0)
        self.assertEqual(orbit.target_offset_cm, 25.0)

    def test_apply_creates_new_camera_when_none_given(self):
        from dazpy.cinematics import OrbitCamera, apply_orbit_camera
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        orbit = OrbitCamera(target=Vec3(0, 0, 0), radius=200.0, frame_start=0, frame_end=2)
        cam = apply_orbit_camera(scene, orbit, name="Orbit Cam")
        self.assertEqual(len(scene.created), 1)
        self.assertIs(cam, scene.created[0])

    def test_apply_reuses_given_camera(self):
        from dazpy.cinematics import OrbitCamera, apply_orbit_camera
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        existing = _FakeCinematicsCamera("MyCam")
        orbit = OrbitCamera(target=Vec3(0, 0, 0), radius=200.0, frame_start=0, frame_end=2)
        cam = apply_orbit_camera(scene, orbit, camera=existing)
        self.assertIs(cam, existing)
        self.assertEqual(len(scene.created), 0)

    def test_apply_sets_focal_length_once(self):
        from dazpy.cinematics import OrbitCamera, apply_orbit_camera
        from dazpy.math3 import Vec3
        cam = _FakeCinematicsCamera()
        scene = _FakeCinematicsScene()
        orbit = OrbitCamera(target=Vec3(0, 0, 0), radius=200.0, frame_start=0, frame_end=2, focal_length=35.0)
        apply_orbit_camera(scene, orbit, camera=cam)
        self.assertEqual(cam.focal_length, 35.0)

    def test_apply_steps_timeline_frame_for_every_frame_inclusive(self):
        from dazpy.cinematics import OrbitCamera, apply_orbit_camera
        from dazpy.math3 import Vec3
        cam = _FakeCinematicsCamera()
        scene = _FakeCinematicsScene()
        orbit = OrbitCamera(target=Vec3(0, 0, 0), radius=200.0, frame_start=5, frame_end=8)
        apply_orbit_camera(scene, orbit, camera=cam)
        scripts = [call.args[0] for call in cam._client.execute.call_args_list]
        self.assertEqual(len(scripts), 4)
        for frame, script in zip(range(5, 9), scripts):
            self.assertIn(f"Scene.setFrame({frame})", script)

    def test_apply_writes_one_position_and_aim_at_per_frame(self):
        from dazpy.cinematics import OrbitCamera, apply_orbit_camera
        from dazpy.math3 import Vec3
        cam = _FakeCinematicsCamera()
        scene = _FakeCinematicsScene()
        orbit = OrbitCamera(target=Vec3(0, 0, 0), radius=200.0, frame_start=0, frame_end=3)
        apply_orbit_camera(scene, orbit, camera=cam)
        self.assertEqual(len(cam.position_calls), 4)
        self.assertEqual(len(cam.aim_at_calls), 4)

    def test_apply_interpolates_azimuth_linearly_across_frames(self):
        from dazpy.cinematics import OrbitCamera, apply_orbit_camera
        from dazpy._shot_geometry import spherical_offset
        from dazpy.math3 import Vec3
        cam = _FakeCinematicsCamera()
        scene = _FakeCinematicsScene()
        orbit = OrbitCamera(
            target=Vec3(0, 0, 0), radius=200.0, elevation_deg=0.0,
            start_azimuth_deg=0.0, end_azimuth_deg=90.0,
            frame_start=0, frame_end=2, target_offset_cm=0.0,
        )
        apply_orbit_camera(scene, orbit, camera=cam)
        expected_mid = spherical_offset(Vec3(0, 0, 0), 45.0, 0.0, 200.0)
        x, y, z = cam.position_calls[1]
        self.assertAlmostEqual(x, expected_mid.x, places=6)
        self.assertAlmostEqual(y, expected_mid.y, places=6)
        self.assertAlmostEqual(z, expected_mid.z, places=6)

    def test_apply_resolves_daznode_target_with_offset(self):
        from dazpy.cinematics import OrbitCamera, apply_orbit_camera

        class _Node:
            position = {"x": 0.0, "y": 0.0, "z": 0.0}

        cam = _FakeCinematicsCamera()
        scene = _FakeCinematicsScene()
        orbit = OrbitCamera(target=_Node(), radius=200.0, frame_start=0, frame_end=0, target_offset_cm=30.0)
        apply_orbit_camera(scene, orbit, camera=cam)
        self.assertEqual(cam.aim_at_calls, [(0.0, 30.0, 0.0)])

    def test_apply_single_frame_range_uses_start_azimuth(self):
        from dazpy.cinematics import OrbitCamera, apply_orbit_camera
        from dazpy._shot_geometry import spherical_offset
        from dazpy.math3 import Vec3
        cam = _FakeCinematicsCamera()
        scene = _FakeCinematicsScene()
        orbit = OrbitCamera(
            target=Vec3(0, 0, 0), radius=200.0, elevation_deg=0.0,
            start_azimuth_deg=10.0, end_azimuth_deg=350.0,
            frame_start=7, frame_end=7, target_offset_cm=0.0,
        )
        apply_orbit_camera(scene, orbit, camera=cam)
        expected = spherical_offset(Vec3(0, 0, 0), 10.0, 0.0, 200.0)
        x, y, z = cam.position_calls[0]
        self.assertAlmostEqual(x, expected.x, places=6)
        self.assertAlmostEqual(z, expected.z, places=6)

    def test_apply_extends_scene_anim_range_before_per_frame_writes(self):
        from dazpy.cinematics import OrbitCamera, apply_orbit_camera
        from dazpy.math3 import Vec3
        cam = _FakeCinematicsCamera()
        scene = _FakeCinematicsScene()
        orbit = OrbitCamera(target=Vec3(0, 0, 0), radius=200.0, frame_start=0, frame_end=90)
        apply_orbit_camera(scene, orbit, camera=cam)
        self.assertEqual(scene.anim_range_calls, [(0, 90)])
        # Anim range must be set before any per-frame position write, or a
        # fresh scene's default 0-30 range clamps early frames.
        self.assertEqual(len(cam.position_calls), 91)

    def test_apply_raises_value_error_when_frame_end_before_frame_start(self):
        from dazpy.cinematics import OrbitCamera, apply_orbit_camera
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        orbit = OrbitCamera(target=Vec3(0, 0, 0), radius=200.0, frame_start=10, frame_end=5)
        with self.assertRaises(ValueError):
            apply_orbit_camera(scene, orbit)
        self.assertEqual(scene.created, [])


class TestFrameSubject(unittest.TestCase):
    def test_defaults(self):
        from dazpy.cinematics import FrameSubject
        from dazpy.math3 import Vec3
        frame = FrameSubject(subject=Vec3(0, 0, 0))
        self.assertEqual(frame.shot_type, "medium")
        self.assertEqual(frame.azimuth_deg, 0.0)
        self.assertEqual(frame.elevation_deg, 10.0)
        self.assertEqual(frame.focal_length, 50.0)
        self.assertIsNone(frame.target_offset_cm)

    def test_apply_creates_new_camera_when_none_given(self):
        from dazpy.cinematics import FrameSubject, apply_frame_subject
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        frame = FrameSubject(subject=Vec3(0, 0, 0))
        cam = apply_frame_subject(scene, frame, name="Close Up")
        self.assertEqual(len(scene.created), 1)
        self.assertIs(cam, scene.created[0])

    def test_apply_reuses_given_camera(self):
        from dazpy.cinematics import FrameSubject, apply_frame_subject
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        existing = _FakeCinematicsCamera("MyCam")
        frame = FrameSubject(subject=Vec3(0, 0, 0))
        cam = apply_frame_subject(scene, frame, camera=existing)
        self.assertIs(cam, existing)
        self.assertEqual(len(scene.created), 0)

    def test_apply_resolves_each_shot_type_to_documented_distance(self):
        from dazpy.cinematics import FrameSubject, apply_frame_subject, _SHOT_DISTANCES
        from dazpy._shot_geometry import spherical_offset
        from dazpy.math3 import Vec3
        for shot_type, distance in _SHOT_DISTANCES.items():
            with self.subTest(shot_type=shot_type):
                cam = _FakeCinematicsCamera()
                scene = _FakeCinematicsScene()
                frame = FrameSubject(subject=Vec3(0, 0, 0), shot_type=shot_type, elevation_deg=0.0, target_offset_cm=0.0)
                apply_frame_subject(scene, frame, camera=cam)
                expected = spherical_offset(Vec3(0, 0, 0), 0.0, 0.0, distance)
                x, y, z = cam.position_calls[0]
                self.assertAlmostEqual(x, expected.x, places=6)
                self.assertAlmostEqual(z, expected.z, places=6)

    def test_apply_uses_shot_type_default_offset_when_none(self):
        from dazpy.cinematics import FrameSubject, apply_frame_subject, _SHOT_TARGET_OFFSETS_CM
        from dazpy.math3 import Vec3
        for shot_type, offset in _SHOT_TARGET_OFFSETS_CM.items():
            with self.subTest(shot_type=shot_type):
                cam = _FakeCinematicsCamera()
                scene = _FakeCinematicsScene()
                frame = FrameSubject(subject=Vec3(0, 0, 0), shot_type=shot_type, azimuth_deg=0.0, elevation_deg=0.0)
                apply_frame_subject(scene, frame, camera=cam)
                self.assertAlmostEqual(cam.aim_at_calls[0][1], offset, places=6)

    def test_apply_honors_explicit_target_offset_override(self):
        from dazpy.cinematics import FrameSubject, apply_frame_subject
        from dazpy.math3 import Vec3
        cam = _FakeCinematicsCamera()
        scene = _FakeCinematicsScene()
        frame = FrameSubject(subject=Vec3(0, 0, 0), shot_type="close_up", target_offset_cm=5.0)
        apply_frame_subject(scene, frame, camera=cam)
        self.assertAlmostEqual(cam.aim_at_calls[0][1], 5.0, places=6)

    def test_apply_raises_value_error_on_unknown_shot_type(self):
        from dazpy.cinematics import FrameSubject, apply_frame_subject
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        frame = FrameSubject(subject=Vec3(0, 0, 0), shot_type="extreme_wide")
        with self.assertRaises(ValueError):
            apply_frame_subject(scene, frame)
        self.assertEqual(scene.created, [])

    def test_apply_sets_focal_length(self):
        from dazpy.cinematics import FrameSubject, apply_frame_subject
        from dazpy.math3 import Vec3
        cam = _FakeCinematicsCamera()
        scene = _FakeCinematicsScene()
        frame = FrameSubject(subject=Vec3(0, 0, 0), focal_length=135.0)
        apply_frame_subject(scene, frame, camera=cam)
        self.assertEqual(cam.focal_length, 135.0)


class TestCinematicAnimatedShot(unittest.TestCase):
    def test_keyframe_defaults(self):
        from dazpy.cinematics import CameraKeyframe
        from dazpy.math3 import Vec3
        kf = CameraKeyframe(frame=0, position=Vec3(0, 0, 150))
        self.assertIsNone(kf.look_at)
        self.assertEqual(kf.look_at_offset_cm, 0.0)
        self.assertIsNone(kf.rotation)

    def test_shot_defaults(self):
        from dazpy.cinematics import CameraKeyframe, CinematicAnimatedShot
        from dazpy.math3 import Vec3
        shot = CinematicAnimatedShot(keyframes=(CameraKeyframe(frame=0, position=Vec3(0, 0, 0)),
                                                  CameraKeyframe(frame=10, position=Vec3(0, 0, 100))))
        self.assertEqual(shot.focal_length, 50.0)
        self.assertFalse(shot.depth_of_field)
        self.assertIsNone(shot.focal_distance)

    def test_is_frozen(self):
        from dazpy.cinematics import CameraKeyframe, CinematicAnimatedShot
        from dazpy.math3 import Vec3
        shot = CinematicAnimatedShot(keyframes=(CameraKeyframe(frame=0, position=Vec3(0, 0, 0)),
                                                  CameraKeyframe(frame=10, position=Vec3(0, 0, 100))))
        with self.assertRaises(Exception):
            shot.focal_length = 85.0

    def test_apply_raises_value_error_with_fewer_than_two_keyframes(self):
        from dazpy.cinematics import CameraKeyframe, CinematicAnimatedShot, apply_animated_shot
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        shot = CinematicAnimatedShot(keyframes=(CameraKeyframe(frame=0, position=Vec3(0, 0, 0)),))
        with self.assertRaises(ValueError):
            apply_animated_shot(scene, shot)
        self.assertEqual(scene.created, [])

    def test_apply_raises_value_error_on_non_ascending_frames(self):
        from dazpy.cinematics import CameraKeyframe, CinematicAnimatedShot, apply_animated_shot
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        shot = CinematicAnimatedShot(keyframes=(
            CameraKeyframe(frame=10, position=Vec3(0, 0, 0)),
            CameraKeyframe(frame=5, position=Vec3(0, 0, 100)),
        ))
        with self.assertRaises(ValueError):
            apply_animated_shot(scene, shot)

    def test_apply_raises_value_error_on_duplicate_frames(self):
        from dazpy.cinematics import CameraKeyframe, CinematicAnimatedShot, apply_animated_shot
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        shot = CinematicAnimatedShot(keyframes=(
            CameraKeyframe(frame=5, position=Vec3(0, 0, 0)),
            CameraKeyframe(frame=5, position=Vec3(0, 0, 100)),
        ))
        with self.assertRaises(ValueError):
            apply_animated_shot(scene, shot)

    def test_apply_raises_value_error_on_partial_orientation(self):
        from dazpy.cinematics import CameraKeyframe, CinematicAnimatedShot, apply_animated_shot
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        shot = CinematicAnimatedShot(keyframes=(
            CameraKeyframe(frame=0, position=Vec3(0, 0, 0), look_at=Vec3(0, 0, 0)),
            CameraKeyframe(frame=10, position=Vec3(0, 0, 100)),
        ))
        with self.assertRaises(ValueError):
            apply_animated_shot(scene, shot)

    def test_apply_creates_new_camera_when_none_given(self):
        from dazpy.cinematics import CameraKeyframe, CinematicAnimatedShot, apply_animated_shot
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        shot = CinematicAnimatedShot(keyframes=(CameraKeyframe(frame=0, position=Vec3(0, 0, 0)),
                                                  CameraKeyframe(frame=10, position=Vec3(0, 0, 100))))
        cam = apply_animated_shot(scene, shot, name="Move 1")
        self.assertEqual(len(scene.created), 1)
        self.assertIs(cam, scene.created[0])
        self.assertEqual(cam.name, "Move 1")

    def test_apply_reuses_given_camera(self):
        from dazpy.cinematics import CameraKeyframe, CinematicAnimatedShot, apply_animated_shot
        from dazpy.math3 import Vec3
        scene = _FakeCinematicsScene()
        existing = _FakeCinematicsCamera("MyCam")
        shot = CinematicAnimatedShot(keyframes=(CameraKeyframe(frame=0, position=Vec3(0, 0, 0)),
                                                  CameraKeyframe(frame=10, position=Vec3(0, 0, 100))))
        cam = apply_animated_shot(scene, shot, camera=existing)
        self.assertIs(cam, existing)
        self.assertEqual(len(scene.created), 0)

    def test_apply_sets_optics_once(self):
        from dazpy.cinematics import CameraKeyframe, CinematicAnimatedShot, apply_animated_shot
        from dazpy.math3 import Vec3
        cam = _FakeCinematicsCamera()
        scene = _FakeCinematicsScene()
        shot = CinematicAnimatedShot(
            keyframes=(CameraKeyframe(frame=0, position=Vec3(0, 0, 0)),
                       CameraKeyframe(frame=10, position=Vec3(0, 0, 100))),
            focal_length=85.0, depth_of_field=True, focal_distance=175.0,
        )
        apply_animated_shot(scene, shot, camera=cam)
        self.assertEqual(cam.focal_length, 85.0)
        self.assertTrue(cam.depth_of_field)
        self.assertEqual(cam.focal_distance, 175.0)

    def test_apply_clears_position_keys_always(self):
        from dazpy.cinematics import CameraKeyframe, CinematicAnimatedShot, apply_animated_shot
        from dazpy.math3 import Vec3
        cam = _FakeCinematicsCamera()
        scene = _FakeCinematicsScene()
        shot = CinematicAnimatedShot(keyframes=(CameraKeyframe(frame=0, position=Vec3(0, 0, 0)),
                                                  CameraKeyframe(frame=10, position=Vec3(0, 0, 100))))
        apply_animated_shot(scene, shot, camera=cam)
        self.assertEqual(cam.clear_position_keys_calls, 1)
        self.assertEqual(cam.clear_rotation_keys_calls, 0)

    def test_apply_clears_rotation_keys_when_orientation_given(self):
        from dazpy.cinematics import CameraKeyframe, CinematicAnimatedShot, apply_animated_shot
        from dazpy.math3 import Vec3
        cam = _FakeCinematicsCamera()
        scene = _FakeCinematicsScene()
        shot = CinematicAnimatedShot(keyframes=(
            CameraKeyframe(frame=0, position=Vec3(0, 0, 150), look_at=Vec3(0, 0, 0)),
            CameraKeyframe(frame=10, position=Vec3(0, 0, 100), look_at=Vec3(0, 0, 0)),
        ))
        apply_animated_shot(scene, shot, camera=cam)
        self.assertEqual(cam.clear_rotation_keys_calls, 1)

    def test_apply_writes_one_position_key_per_waypoint(self):
        from dazpy.cinematics import CameraKeyframe, CinematicAnimatedShot, apply_animated_shot
        from dazpy.math3 import Vec3
        cam = _FakeCinematicsCamera()
        scene = _FakeCinematicsScene()
        shot = CinematicAnimatedShot(keyframes=(
            CameraKeyframe(frame=0, position=Vec3(1, 2, 3)),
            CameraKeyframe(frame=10, position=Vec3(4, 5, 6)),
            CameraKeyframe(frame=20, position=Vec3(7, 8, 9)),
        ))
        apply_animated_shot(scene, shot, camera=cam)
        self.assertEqual(cam.position_at_frame_calls, [
            (0, 1.0, 2.0, 3.0), (10, 4.0, 5.0, 6.0), (20, 7.0, 8.0, 9.0),
        ])
        self.assertEqual(cam.rotation_at_frame_calls, [])

    def test_apply_writes_rotation_key_from_look_at(self):
        from dazpy.cinematics import CameraKeyframe, CinematicAnimatedShot, apply_animated_shot
        from dazpy._shot_geometry import look_at_euler
        from dazpy.math3 import Vec3
        cam = _FakeCinematicsCamera()
        scene = _FakeCinematicsScene()
        pos0 = Vec3(0, 0, 150)
        shot = CinematicAnimatedShot(keyframes=(
            CameraKeyframe(frame=0, position=pos0, look_at=Vec3(0, 0, 0)),
            CameraKeyframe(frame=10, position=Vec3(150, 0, 0), look_at=Vec3(0, 0, 0)),
        ))
        apply_animated_shot(scene, shot, camera=cam)
        expected = look_at_euler(pos0, Vec3(0, 0, 0))
        frame, x, y, z = cam.rotation_at_frame_calls[0]
        self.assertEqual(frame, 0)
        self.assertAlmostEqual(x, expected[0], places=6)
        self.assertAlmostEqual(y, expected[1], places=6)
        self.assertAlmostEqual(z, expected[2], places=6)

    def test_apply_applies_look_at_offset_to_daznode_target(self):
        from dazpy.cinematics import CameraKeyframe, CinematicAnimatedShot, apply_animated_shot
        from dazpy._shot_geometry import look_at_euler
        from dazpy.math3 import Vec3

        class _Node:
            position = {"x": 0.0, "y": 100.0, "z": 0.0}

        cam = _FakeCinematicsCamera()
        scene = _FakeCinematicsScene()
        pos0 = Vec3(0, 0, 150)
        shot = CinematicAnimatedShot(keyframes=(
            CameraKeyframe(frame=0, position=pos0, look_at=_Node(), look_at_offset_cm=20.0),
            CameraKeyframe(frame=10, position=Vec3(0, 0, 100), look_at=_Node(), look_at_offset_cm=20.0),
        ))
        apply_animated_shot(scene, shot, camera=cam)
        expected = look_at_euler(pos0, Vec3(0.0, 120.0, 0.0))
        frame, x, y, z = cam.rotation_at_frame_calls[0]
        self.assertAlmostEqual(x, expected[0], places=6)
        self.assertAlmostEqual(y, expected[1], places=6)
        self.assertAlmostEqual(z, expected[2], places=6)

    def test_apply_writes_rotation_key_from_explicit_rotation(self):
        from dazpy.cinematics import CameraKeyframe, CinematicAnimatedShot, apply_animated_shot
        from dazpy.math3 import Vec3
        cam = _FakeCinematicsCamera()
        scene = _FakeCinematicsScene()
        shot = CinematicAnimatedShot(keyframes=(
            CameraKeyframe(frame=0, position=Vec3(0, 0, 150), rotation=(1.0, 2.0, 3.0)),
            CameraKeyframe(frame=10, position=Vec3(0, 0, 100), rotation=(4.0, 5.0, 6.0)),
        ))
        apply_animated_shot(scene, shot, camera=cam)
        self.assertEqual(cam.rotation_at_frame_calls, [(0, 1.0, 2.0, 3.0), (10, 4.0, 5.0, 6.0)])


class TestCinematicsExports(unittest.TestCase):
    def test_cinematics_symbols_importable_from_top_level_package(self):
        import dazpy
        self.assertTrue(hasattr(dazpy, "CinematicStaticShot"))
        self.assertTrue(hasattr(dazpy, "OrbitCamera"))
        self.assertTrue(hasattr(dazpy, "FrameSubject"))
        self.assertTrue(hasattr(dazpy, "apply_static_shot"))
        self.assertTrue(hasattr(dazpy, "apply_orbit_camera"))
        self.assertTrue(hasattr(dazpy, "apply_frame_subject"))
        self.assertTrue(hasattr(dazpy, "CameraKeyframe"))
        self.assertTrue(hasattr(dazpy, "CinematicAnimatedShot"))
        self.assertTrue(hasattr(dazpy, "apply_animated_shot"))
        self.assertIn("CinematicStaticShot", dazpy.__all__)
        self.assertIn("OrbitCamera", dazpy.__all__)
        self.assertIn("FrameSubject", dazpy.__all__)
        self.assertIn("apply_static_shot", dazpy.__all__)
        self.assertIn("apply_orbit_camera", dazpy.__all__)
        self.assertIn("apply_frame_subject", dazpy.__all__)
        self.assertIn("CameraKeyframe", dazpy.__all__)
        self.assertIn("CinematicAnimatedShot", dazpy.__all__)
        self.assertIn("apply_animated_shot", dazpy.__all__)


if __name__ == "__main__":
    unittest.main()
