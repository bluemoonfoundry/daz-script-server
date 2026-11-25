"""
Live tests for dazpy.shots / dazpy.shot_library against DAZ Studio.  Skipped
when the script server is not reachable.  Run scoped:

    python -m pytest tests/test_shots_live.py -v

Each test applies a shot in Studio, reads the camera back with
``getWSPos(tm)`` / ``getWSRot(tm)`` / the focal-distance control at the keyed
frames, and compares it with the library's pure prediction.  The scene is not
cleared: cameras are named ``ShotLive_*`` (coverage cameras after their shot
ids) and deleted afterwards; the anim range and current frame are restored.

The daz-ts twin is ``daz-ts/test/integration/shots.integration.test.ts``; keep
the two scenario lists and tolerances in step.
"""

import json
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import requests as _req

from dazpy import DazClient, DazScene
from dazpy.math3 import Quat, Vec3
from dazpy import shot_library as sl
from dazpy.shot_library import LineOfAction
from dazpy.shots import (
    CameraKeyframe, Framing, Keyframed, Lens, Orbit, Placement, Shot, apply_shot, framing_transform,
)

_SERVER_UP = False
try:
    _SERVER_UP = _req.get("http://127.0.0.1:18811/status", timeout=2).status_code == 200
except Exception:
    pass

skip_if_down = unittest.skipUnless(_SERVER_UP, "DAZ Studio script server not reachable at 127.0.0.1:18811")

PREFIX = "ShotLive_"
# Alice faces Bob along -Z, off the origin so nothing lines up by accident.
POS = {"alice": Vec3(310.0, 0.0, -40.0), "bob": Vec3(330.0, 0.0, -160.0)}
POS_TOL = 0.01  # cm
DIR_TOL = 1e-4  # 1 - dot of unit directions (~0.8 degrees)

# One read-back script shared with the daz-ts suite: world pose and focal
# distance of node NAME at each of FRAMES.
_READBACK = """(function(){
  var n = Scene.findNode(%s); if (!n) return null;
  var step = Scene.getTimeStep(); var frames = %s; var out = [];
  for (var i = 0; i < frames.length; i++) {
    var tm = frames[i] * step; var p = n.getWSPos(tm, false); var q = n.getWSRot(tm, false);
    var fd = n.getFocalDistanceControl ? n.getFocalDistanceControl().getValue(tm) : null;
    out.push({frame: frames[i], pos: [p.x, p.y, p.z], rot: {x: q.x, y: q.y, z: q.z, w: q.w}, focal_distance: fd});
  }
  return out;
})()"""

_CLEANUP = """(function(){
  var gone = 0;
  for (var i = Scene.getNumNodes() - 1; i >= 0; i--) {
    var n = Scene.getNode(i); var name = n.getName();
    if (name.indexOf(%s) === 0 || %s.indexOf(name) >= 0) { Scene.removeNode(n); gone++; }
  }
  return gone;
})()"""


class _Pose:
    def __init__(self, d):
        self.frame = d["frame"]
        self.pos = Vec3(*d["pos"])
        q = Quat.from_dz(d["rot"])
        self.forward = q.rotate(Vec3(0.0, 0.0, -1.0)).normalize()
        self.up = q.rotate(Vec3(0.0, 1.0, 0.0)).normalize()
        self.focal_distance = d["focal_distance"]


@skip_if_down
class ShotsLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = DazClient()
        cls.scene = DazScene(cls.client)
        cls.range0 = cls.scene.anim_range()
        cls.frame0 = cls.scene.frame()
        cls._cleanup([])

    @classmethod
    def tearDownClass(cls):
        cls.scene.set_anim_range(cls.range0["start"], cls.range0["end"])
        cls.scene.set_frame(cls.frame0)

    @classmethod
    def _cleanup(cls, names):
        cls.client.execute(_CLEANUP % (json.dumps(PREFIX), json.dumps(list(names))))

    def setUp(self):
        self.extra_names = []

    def tearDown(self):
        self._cleanup(self.extra_names)

    # ---- helpers -----------------------------------------------------------

    def camera(self, tag):
        return self.scene.create_camera(f"{PREFIX}{tag}")

    def readback(self, cam, frames):
        data = self.client.execute(_READBACK % (json.dumps(cam.name), json.dumps(list(frames)))).value
        self.assertIsNotNone(data, "camera vanished")
        return [_Pose(d) for d in data]

    def assertVecClose(self, a, b, tol=POS_TOL, msg=None):
        self.assertLess(a.distance(b), tol, msg or f"{a} != {b}")

    def assertSameDirection(self, a, b, msg=None):
        self.assertLess(1.0 - a.normalize().dot(b.normalize()), DIR_TOL, msg or f"{a} vs {b}")

    def line(self, side=1):
        return LineOfAction.between(POS, "alice", "bob", side)

    # ---- static shots ------------------------------------------------------

    def test_framing_single_close_up(self):
        shot = sl.single(self.line(), "alice", size="close_up")
        cam = apply_shot(self.scene, shot, camera=self.camera("single"), subjects=POS)
        pos, aim = framing_transform([(POS["alice"], True)], shot.camera, shot.lens.focal_length)
        (p,) = self.readback(cam, [0])
        self.assertVecClose(p.pos, pos)
        self.assertSameDirection(p.forward, aim - pos)
        self.assertGreater(p.up.y, 0.9)  # aimAt leaves no roll
        self.assertAlmostEqual(cam.focal_length, 85.0, places=4)

    def test_framing_node_subject_is_raised(self):
        target = self.camera("target")
        target.set_position(250.0, 0.0, -90.0)
        shot = Shot(id="n", camera=Framing(subjects=(target,), size="medium", azimuth_deg=40))
        cam = apply_shot(self.scene, shot, camera=self.camera("node"))
        pos, aim = framing_transform([(Vec3(250.0, 0.0, -90.0), True)], shot.camera, 50.0)
        (p,) = self.readback(cam, [0])
        self.assertVecClose(p.pos, pos)
        self.assertSameDirection(p.forward, aim - pos)

    def test_over_the_shoulder_placement(self):
        shot = sl.over_the_shoulder(self.line(), "alice", "bob")
        cam = apply_shot(self.scene, shot, camera=self.camera("ots"), subjects=POS)
        (p,) = self.readback(cam, [0])
        self.assertVecClose(p.pos, shot.camera.position)
        self.assertSameDirection(p.forward, shot.camera.look_at - shot.camera.position)
        self.assertEqual(self.line().side_of(p.pos), 1)

    def test_dutch_rotation_rolls_toward_screen_left(self):
        position, aim = Vec3(400.0, 150.0, 200.0), Vec3(280.0, 140.0, -50.0)
        rot = sl.look_rotation(position, aim, 15.0)
        cam = apply_shot(self.scene, Shot(id="d", camera=Placement(position=position, rotation=rot)),
                         camera=self.camera("dutch"))
        (p,) = self.readback(cam, [0])
        self.assertSameDirection(p.forward, aim - position)
        self.assertSameDirection(p.up, sl.camera_up(rot))
        left = -(p.forward.cross(Vec3(0.0, 1.0, 0.0)).normalize())
        self.assertGreater(p.up.dot(left), 0.0)
        level_up = sl.camera_up(sl.look_rotation(position, aim))
        self.assertAlmostEqual(math.degrees(math.acos(max(-1.0, min(1.0, p.up.dot(level_up))))), 15.0, delta=0.1)

    # ---- moves -------------------------------------------------------------

    def test_camera_move_dolly_keys_both_ends(self):
        shot = sl.camera_move("dolly_in", Vec3(320.0, 150.0, 200.0), (5.0, 20.0, 0.0), start=0, end=24, amount=120)
        cam = apply_shot(self.scene, shot, camera=self.camera("dolly"))
        keys = shot.movement.keyframes
        for p, k in zip(self.readback(cam, [0, 24]), keys):
            self.assertVecClose(p.pos, k.position)
            self.assertSameDirection(p.forward, sl.forward_from_rotation(k.rotation))
        mid = self.readback(cam, [12])[0]
        self.assertLess(mid.pos.distance(keys[0].position), keys[0].position.distance(keys[1].position))

    def test_pan_from_studio_quaternion_turns_right(self):
        cam = self.camera("pan")
        cam.set_position(420.0, 150.0, 120.0)
        cam.aim_at(300.0, 140.0, -100.0)  # Studio may report this as a flipped (|x| > 90) Euler
        start = self.readback(cam, [0])[0]
        shot = sl.camera_move("pan_right", start.pos, cam.rotation, start=0, end=20, amount=20)
        apply_shot(self.scene, shot, camera=cam)
        p0, p1 = self.readback(cam, [0, 20])
        self.assertSameDirection(p0.forward, start.forward)  # the quaternion read back as the same view
        self.assertSameDirection(p1.forward, sl.forward_from_rotation(shot.movement.keyframes[-1].rotation))
        right = p0.forward.cross(Vec3(0.0, 1.0, 0.0)).normalize()
        self.assertGreater((p1.forward - p0.forward).dot(right), 0.0)

    def test_push_in_reaims_at_each_key(self):
        shot = sl.push_in(POS, "bob", start=0, end=30, line=self.line())
        cam = apply_shot(self.scene, shot, camera=self.camera("push"), subjects=POS)
        for p, k in zip(self.readback(cam, [0, 30]), shot.movement.keyframes):
            self.assertVecClose(p.pos, k.position)
            self.assertSameDirection(p.forward, k.look_at - k.position)
        self.assertEqual(sl.check_axis([shot], self.line(), POS), [])

    def test_keyframed_arc_waypoints(self):
        shot = sl.arc("alice", start=0, end=24, step_deg=45, positions=POS, radius=220,
                      start_azimuth_deg=30, end_azimuth_deg=150)
        cam = apply_shot(self.scene, shot, camera=self.camera("arc"), subjects=POS)
        keys = shot.movement.keyframes
        target = keys[0].look_at
        for p, k in zip(self.readback(cam, [k.frame for k in keys]), keys):
            self.assertVecClose(p.pos, k.position)
            self.assertAlmostEqual(p.pos.distance(target), 220.0, delta=POS_TOL)
            self.assertSameDirection(p.forward, target - p.pos)

    def test_keyframed_easing_curves(self):
        """v6rm: each easing lands on its analytic curve, on position and rotation."""
        curves = {
            "linear": lambda t: t,
            "smooth": lambda t: 3 * t * t - 2 * t ** 3,  # Studio's two-key default
            "ease_in": lambda t: t * t,
            "ease_out": lambda t: 2 * t - t * t,
        }
        p0, p1, yaw1 = Vec3(300.0, 150.0, 200.0), Vec3(360.0, 150.0, 200.0), 40.0
        for easing, curve in curves.items():
            with self.subTest(easing=easing):
                shot = Shot(id="e", camera=Placement(position=p0), movement=Keyframed(keyframes=(
                    CameraKeyframe(0, p0, rotation=(0.0, 0.0, 0.0)),
                    CameraKeyframe(24, p1, rotation=(0.0, yaw1, 0.0))), easing=easing))
                cam = apply_shot(self.scene, shot, camera=self.camera(f"ease_{easing}"))
                for p in self.readback(cam, [0, 6, 12, 18, 24]):
                    f = curve(p.frame / 24)
                    self.assertVecClose(p.pos, p0 + (p1 - p0) * f, msg=f"{easing} frame {p.frame}: {p.pos}")
                    yaw = math.radians(yaw1 * f)
                    self.assertSameDirection(p.forward, Vec3(-math.sin(yaw), 0.0, -math.cos(yaw)),
                                             msg=f"{easing} frame {p.frame} facing")

    def test_keyframed_constant_holds_until_next_key(self):
        p0, p1 = Vec3(300.0, 150.0, 200.0), Vec3(360.0, 150.0, 200.0)
        shot = Shot(id="c", camera=Placement(position=p0), movement=Keyframed(keyframes=(
            CameraKeyframe(0, p0, interpolation="constant"), CameraKeyframe(24, p1))))
        cam = apply_shot(self.scene, shot, camera=self.camera("hold"))
        poses = self.readback(cam, [0, 12, 23, 24])
        for p in poses[:3]:
            self.assertVecClose(p.pos, p0)
        self.assertVecClose(poses[3].pos, p1)

    def test_orbit_bake_sets_range_and_parks_on_last_frame(self):
        shot = Shot(id="o", camera=Framing(subjects=("alice",)), lens=Lens(focal_length=35),
                    movement=Orbit(radius=200, frame_start=0, frame_end=4, start_azimuth_deg=0, end_azimuth_deg=80))
        cam = apply_shot(self.scene, shot, camera=self.camera("orbit"), subjects=POS)
        self.assertEqual(self.scene.anim_range(), {"start": 0, "end": 4})
        self.assertEqual(self.scene.frame(), 4)
        last = sl.camera_positions(Shot(id="x", camera=shot.camera, movement=Orbit(
            radius=200, frame_start=0, frame_end=4, start_azimuth_deg=80, end_azimuth_deg=80)), POS)[0]
        (p,) = self.readback(cam, [4])
        self.assertVecClose(p.pos, last)
        self.assertAlmostEqual(cam.focal_length, 35.0, places=4)

    # ---- focus -------------------------------------------------------------

    def test_rack_focus_keys_focal_distance(self):
        shot = sl.with_rack_focus(sl.over_the_shoulder(self.line(), "alice", "bob"), "alice", "bob",
                                  start=0, end=24, positions=POS, f_stop=2.0, hold_from=4, hold_to=4)
        cam = apply_shot(self.scene, shot, camera=self.camera("rack"), subjects=POS)
        keys = shot.focus.keys
        for p, k in zip(self.readback(cam, [k.frame for k in keys]), keys):
            self.assertAlmostEqual(p.focal_distance, k.focal_distance, delta=0.01)
        self.assertIs(cam.depth_of_field, True)
        self.assertAlmostEqual(cam.f_stop, 2.0, places=4)

    # ---- chaining and coverage --------------------------------------------

    def test_clear_keys_false_chains_moves(self):
        cam = self.camera("chain")
        home = Vec3(300.0, 150.0, 250.0)
        dolly = sl.camera_move("dolly_in", home, (0.0, 0.0, 0.0), start=0, end=10, amount=50)
        apply_shot(self.scene, dolly, camera=cam)
        mid = dolly.movement.keyframes[-1].position
        truck = sl.camera_move("truck_right", mid, (0.0, 0.0, 0.0), start=10, end=20, amount=40)
        apply_shot(self.scene, truck, camera=cam, clear_keys=False)
        p0, p10, p20 = self.readback(cam, [0, 10, 20])
        self.assertVecClose(p0.pos, home)
        self.assertVecClose(p10.pos, mid)
        self.assertVecClose(p20.pos, truck.movement.keyframes[-1].position)
        apply_shot(self.scene, dolly, camera=cam)  # clear_keys=True drops the truck keys
        self.assertVecClose(self.readback(cam, [20])[0].pos, mid)

    def test_apply_coverage_names_cameras_and_keeps_the_line(self):
        plan = sl.dialogue_coverage(self.line(-1), include=("master", "ots"), plan_id="ShotLive_cov")
        cams = sl.apply_coverage(self.scene, plan, subjects=POS)
        self.extra_names = [c.name for c in cams.values()]
        self.assertEqual(list(cams), ["MST_alice-bob", "OTS_bob_over_alice", "OTS_alice_over_bob"])
        for shot_id, cam in cams.items():
            self.assertEqual(cam.label, shot_id)
            (p,) = self.readback(cam, [0])
            self.assertEqual(self.line(-1).side_of(p.pos), -1, shot_id)


if __name__ == "__main__":
    unittest.main()
