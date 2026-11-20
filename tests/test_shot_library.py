"""Unit tests for dazpy.shot_library (cinematic shot library). No Studio."""

import json
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dazpy.math3 import Quat, Vec3
from dazpy._shot_geometry import look_at_euler
from dazpy._recipe_validate import _KEY_RE
from dazpy.shots import (
    SHOT_SIZES, CoveragePlan, Framing, Keyframed, Orbit, Shot, framing_transform,
)
from dazpy import shot_library as sl
from dazpy.shot_library import DialogueBeat, LineOfAction

from test_shots import FakeCamera, FakeScene

# Alice faces Bob along -Z; cameras on side +1 stand on +X.
POS = {"alice": Vec3(0.0, 0.0, 0.0), "bob": Vec3(0.0, 0.0, -120.0)}


def line(side=1):
    return LineOfAction.between(POS, "alice", "bob", side)


def pose(shot, positions=POS):
    """(camera position, aim point) of a static shot."""
    c = shot.camera
    if isinstance(c, Framing):
        pts = [(positions[s], True) if isinstance(s, str) else (s, False) for s in c.subjects]
        return framing_transform(pts, c, shot.lens.focal_length)
    return c.position, c.look_at


def screen_x(cam, aim, point):
    """Normalised horizontal screen coordinate of *point*: -1 left edge .. +1 right edge (36mm @ f)."""
    fwd = (aim - cam).normalize()
    right = fwd.cross(Vec3(0, 1, 0)).normalize()
    rel = point - cam
    return rel.dot(right) / rel.dot(fwd)


def gaze_screen_dir(cam, aim, frm, to):
    right = (aim - cam).cross(Vec3(0, 1, 0)).normalize()
    return math.copysign(1.0, (to - frm).dot(right))


def eye(key):
    p = POS[key]
    return Vec3(p.x, p.y + sl.EYE_HEIGHT_CM, p.z)


class NamingTests(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(sl.shot_name("ots", "bob", over="alice"), "OTS_bob_over_alice")
        self.assertEqual(sl.shot_name("close_up", "anna", scene=3, index=12), "SC3_012_CU_anna")
        self.assertEqual(sl.shot_name("medium", "Genesis 9", tag="low"), "MS_low_Genesis-9")
        self.assertEqual(sl.shot_name("whip"), "WHIP")

    def test_names_are_recipe_keys(self):
        for name in (sl.shot_name("ots", "Bob Smith!", over="Alice.G9"), sl.shot_name("pov", "x" * 80)):
            self.assertRegex(name, _KEY_RE)


class LineOfActionTests(unittest.TestCase):
    def test_sides(self):
        ln = line()
        self.assertEqual(ln.side_of(Vec3(100, 0, -60)), 1)
        self.assertEqual(ln.side_of(Vec3(-100, 0, -60)), -1)
        self.assertEqual(ln.side_of(Vec3(0.5, 0, 300)), 0)
        self.assertEqual(ln.side_of(ln.midpoint + ln.normal * 50), 1)
        self.assertEqual(line(-1).side_of(line(-1).midpoint + line(-1).normal * 50), -1)
        self.assertEqual(ln.flipped().side, -1)
        self.assertEqual(ln.other("alice"), "bob")

    def test_invalid(self):
        with self.assertRaises(ValueError):
            LineOfAction("a", "b", Vec3(0, 0, 0), Vec3(0, 50, 0))
        with self.assertRaises(ValueError):
            LineOfAction("a", "a", Vec3(0, 0, 0), Vec3(1, 0, 0))
        with self.assertRaises(ValueError):
            line().other("carol")


class CompositionTests(unittest.TestCase):
    def test_headroom_puts_eyes_on_upper_third(self):
        self.assertAlmostEqual(sl.headroom_anchor("close_up"), 160 - 40 / 6)
        self.assertEqual(sl.headroom_anchor("extreme_wide", eye_height=50), 0.0)

    def test_lead_room(self):
        cam, aim = Vec3(0, 0, 300), Vec3(0, 0, 0)  # looking -Z; screen-right is +X
        self.assertEqual(sl.lead_room(cam, aim, Vec3(1, 0, 0)), "left_third")
        self.assertEqual(sl.lead_room(cam, aim, Vec3(-1, 0, 0)), "right_third")
        self.assertEqual(sl.lead_room(cam, aim, Vec3(0, 0, 1)), "center")


class ShotTypeTests(unittest.TestCase):
    def test_every_coverage_camera_is_on_the_line_side(self):
        for side in (1, -1):
            plan = sl.dialogue_coverage(line(side))
            for shot in plan.all_shots():
                p = sl.camera_position(shot, POS)
                self.assertEqual(line(side).side_of(p), side, shot.id)
            self.assertEqual(sl.check_axis(plan.all_shots(), line(side), POS), [])
            self.assertEqual(len(sl.check_axis(plan.all_shots(), line(-side), POS)), 6)

    def test_ots_geometry_and_thirds(self):
        shot = sl.over_the_shoulder(line(), "alice", "bob")
        self.assertEqual(shot.id, "OTS_bob_over_alice")
        cam, aim = pose(shot)
        # Behind Alice, further from Bob than she is, near eye height.
        self.assertGreater(cam.distance(POS["bob"]), POS["alice"].distance(POS["bob"]))
        self.assertAlmostEqual(cam.y, sl.EYE_HEIGHT_CM - sl.OTS_DROP_CM)
        # Bob on a third, Alice's head on the opposite side of the frame.
        half = 36.0 / 50.0 / 2  # half frame width over focal length at distance 1
        bx = screen_x(cam, aim, eye("bob")) / half
        ax = screen_x(cam, aim, eye("alice")) / half
        self.assertAlmostEqual(abs(bx), 1 / 3, places=2)
        self.assertLess(bx * ax, 0)

    def test_shot_reverse_shot_eyelines_match(self):
        s1, s2 = sl.shot_reverse_shot(line())
        c1, a1 = pose(s1)
        c2, a2 = pose(s2)
        bob_looks = gaze_screen_dir(c1, a1, eye("bob"), eye("alice"))
        alice_looks = gaze_screen_dir(c2, a2, eye("alice"), eye("bob"))
        self.assertEqual(bob_looks, -alice_looks)

    def test_crossing_the_line_breaks_eyelines(self):
        s1, _ = sl.shot_reverse_shot(line())
        _, s2 = sl.shot_reverse_shot(line(-1))
        c1, a1 = pose(s1)
        c2, a2 = pose(s2)
        self.assertEqual(gaze_screen_dir(c1, a1, eye("bob"), eye("alice")),
                         gaze_screen_dir(c2, a2, eye("alice"), eye("bob")))

    def test_single_has_lead_room_toward_partner(self):
        shot = sl.single(line(), "alice", size="close_up")
        self.assertEqual(shot.id, "CU_alice")
        cam, aim = pose(shot)
        looks = gaze_screen_dir(cam, aim, eye("alice"), eye("bob"))
        sx = screen_x(cam, aim, Vec3(0, framing_anchor(shot), 0))
        self.assertLess(sx * looks, 0)  # subject sits opposite the way they look
        self.assertEqual(shot.lens.focal_length, 85.0)

    def test_single_headroom(self):
        shot = sl.single(line(), "bob", size="medium", headroom=True, lead=False)
        self.assertEqual(shot.camera.anchor_cm, sl.headroom_anchor("medium"))
        self.assertEqual(shot.camera.composition, "center")

    def test_two_shot_widens_for_far_apart_actors(self):
        near = sl.two_shot(line())
        self.assertIsNone(near.camera.distance_cm)  # recipe-expressible
        far = sl.two_shot(LineOfAction.between({"a": Vec3(0, 0, 0), "b": Vec3(600, 0, 0)}, "a", "b"))
        self.assertGreater(far.camera.distance_cm, 600)

    def test_establishing_master(self):
        est = sl.establishing(line())
        self.assertEqual((est.camera.size, est.camera.elevation_deg, est.lens.focal_length),
                         ("extreme_wide", 10.0, 24.0))
        self.assertAlmostEqual(est.camera.azimuth_deg, 90.0)  # perpendicular, on +X
        self.assertEqual(sl.master(line()).id, "MST_alice-bob")

    def test_pov(self):
        shot = sl.pov(POS, "alice", "bob")
        self.assertEqual(shot.id, "POV_at-bob_alice")
        self.assertEqual(shot.camera.look_at, eye("bob"))
        self.assertAlmostEqual(shot.camera.position.z, -10.0)
        pt = sl.pov(POS, "alice", Vec3(0, 90, -50))
        self.assertEqual(pt.id, "POV_alice")

    def test_insert(self):
        shot = sl.insert(Vec3(10, 95, -60), name="cup", line=line())
        self.assertEqual((shot.id, shot.camera.size), ("INS_cup", "extreme_close_up"))
        self.assertAlmostEqual(shot.camera.azimuth_deg, 90.0)
        cam, _ = pose(shot)
        self.assertGreater(cam.y, 95)

    def test_ots_requires_line_actors(self):
        with self.assertRaises(ValueError):
            sl.over_the_shoulder(line(), "alice", "alice")


def framing_anchor(shot):
    return SHOT_SIZES[shot.camera.size][1]


class MoveTests(unittest.TestCase):
    def test_forward_inverts_look_at(self):
        for target in (Vec3(100, 50, -30), Vec3(-40, -20, 80), Vec3(0, 0, -1)):
            rot = look_at_euler(Vec3(0, 0, 0), target)
            f = sl.forward_from_rotation(rot)
            n = target.normalize()
            for a, b in zip((f.x, f.y, f.z), (n.x, n.y, n.z)):
                self.assertAlmostEqual(a, b, places=6)

    def test_forward_matches_studio_cameras(self):
        # Studio readbacks (getWSRot * -Z) for cameras posed by aimAt / set by hand, incl. roll.
        for rot, fwd in (((0, 33.69, 0), (-0.555, 0.0, -0.832)), ((2.74, -39.73, 0), (0.638, 0.048, -0.768)),
                         ((-177.26, 72.89, 180), (-0.955, 0.048, 0.294)),
                         ((-180, 85.35, -180), (-0.997, 0.0, 0.081))):
            f = sl.forward_from_rotation(rot)
            for a, b in zip((f.x, f.y, f.z), fwd):
                self.assertAlmostEqual(a, b, places=2)
            g = sl.forward_from_rotation(sl.canonical_rotation(rot))
            self.assertAlmostEqual(f.dot(g), 1.0, places=9)

    def test_canonical_rotation(self):
        x, y, z = sl.canonical_rotation((-177.26, 72.89, 180))
        self.assertAlmostEqual(x, 2.74, places=6)
        self.assertAlmostEqual(y, 107.11, places=6)
        self.assertAlmostEqual(z, 0.0, places=6)
        self.assertEqual(sl.canonical_rotation((10, 370, -5)), (10.0, 10.0, -5.0))

    def test_studio_quaternions(self):
        # getWSRot() readbacks of a camera whose rotation channels were set to these Eulers.
        for euler, dzq in (((10, 30, 0), (-0.0842, -0.2578, 0.0226, 0.9623)),
                           ((-20, 120, 15), (0.1974, -0.8342, -0.2134, 0.4686)),
                           ((5, -100, 0), (-0.028, 0.7653, -0.0334, 0.6422))):
            got = sl.euler_from_quaternion(dict(zip("xyzw", dzq)))
            for a, b in zip(got, euler):
                self.assertAlmostEqual(a, b, delta=0.05)

    def test_quaternion_pose(self):
        q = Quat.from_euler(-177.26, 72.89, 180, order="ZYX").conjugate()  # as Studio reports it
        e = sl.euler_from_quaternion({"x": q.x, "y": q.y, "z": q.z, "w": q.w})
        self.assertAlmostEqual(e[0], 2.74, places=6)
        self.assertAlmostEqual(sl.forward_from_rotation(e).dot(sl.forward_from_rotation((-177.26, 72.89, 180))), 1.0)
        a = sl.camera_move("tilt_up", Vec3(0, 0, 0), q, start=0, end=5).movement.keyframes[0].rotation
        for x, y in zip(a, e):
            self.assertAlmostEqual(x, y, places=9)

    def test_pan_from_flipped_euler_turns_right(self):
        shot = sl.camera_move("pan_right", Vec3(0, 0, 0), (-177.26, 72.89, 180), start=0, end=10, amount=10)
        k0, k1 = shot.movement.keyframes
        f0, f1 = sl.forward_from_rotation(k0.rotation), sl.forward_from_rotation(k1.rotation)
        right = f0.cross(Vec3(0, 1, 0)).normalize()
        self.assertGreater((f1 - f0).dot(right), 0)

    def keys(self, kind, **kw):
        shot = sl.camera_move(kind, Vec3(0, 150, 300), (0.0, 0.0, 0.0), start=0, end=60, **kw)
        self.assertIsInstance(shot.movement, Keyframed)
        self.assertEqual(shot.frame_range, (0, 60))
        return shot.movement.keyframes

    def test_translations(self):
        self.assertEqual(self.keys("dolly_in")[-1].position, Vec3(0, 150, 100))
        self.assertEqual(self.keys("dolly_out", amount=50)[-1].position, Vec3(0, 150, 350))
        self.assertEqual(self.keys("truck_right")[-1].position, Vec3(100, 150, 300))
        self.assertEqual(self.keys("crane_up")[-1].position, Vec3(0, 250, 300))
        self.assertEqual(self.keys("pedestal_down")[-1].position, Vec3(0, 100, 300))

    def test_rotations(self):
        pan = self.keys("pan_right")[-1].rotation
        self.assertGreater(sl.forward_from_rotation(pan).x, 0.5)  # now looking toward +X (screen right)
        tilt = self.keys("tilt_up")[-1].rotation
        self.assertGreater(sl.forward_from_rotation(tilt).y, 0.3)

    def test_handheld_is_repeatable_and_returns_home(self):
        a, b = self.keys("handheld", seed=7), self.keys("handheld", seed=7)
        self.assertEqual(a, b)
        self.assertNotEqual(a, self.keys("handheld", seed=8))
        self.assertEqual((a[0].position, a[-1].position), (Vec3(0, 150, 300), Vec3(0, 150, 300)))
        self.assertTrue(all(abs(k.position.x) <= 2.0 for k in a))

    def test_bad_moves(self):
        with self.assertRaises(ValueError):
            sl.camera_move("zoom", Vec3(0, 0, 0), (0, 0, 0), start=0, end=10)
        with self.assertRaises(ValueError):
            sl.camera_move("dolly_in", Vec3(0, 0, 0), (0, 0, 0), start=10, end=10)

    def test_push_in_and_pull_out(self):
        push = sl.push_in(POS, "bob", start=0, end=48, azimuth_deg=90)
        k0, k1 = push.movement.keyframes
        self.assertGreater(k0.position.distance(POS["bob"]), k1.position.distance(POS["bob"]))
        self.assertGreater(k1.look_at.y, k0.look_at.y)  # aim rises toward the face
        self.assertEqual(push.id, "PUSH_bob")
        pull = sl.pull_out(POS, "bob", start=0, end=48, line=line())
        self.assertEqual(pull.id, "PULL_bob")
        self.assertEqual(sl.check_axis([pull], line(), POS), [])

    def test_arc_crossing_the_line_is_reported(self):
        full = sl.arc("alice", start=0, end=90)
        self.assertIsInstance(full.movement, Orbit)
        issues = sl.check_axis([full], line(), POS)
        self.assertEqual([i.kind for i in issues], ["axis"])
        self.assertIn("moves across", issues[0].message)
        half = sl.arc("alice", start=0, end=90, start_azimuth_deg=20, end_azimuth_deg=160)
        self.assertEqual(sl.check_axis([half], line(), POS), [])


class PrimitiveTests(unittest.TestCase):
    def test_compose_aim(self):
        cam, target = Vec3(0, 160, 300), Vec3(0, 160, 0)
        for x in (sl.THIRD_X, -sl.THIRD_X, sl.GOLDEN_X, 0.0):
            aim = sl.compose_aim(cam, target, x, 50)
            self.assertAlmostEqual(screen_x(cam, aim, target) / (36 / 50 / 2), x, places=6)
        self.assertAlmostEqual(sl.GOLDEN_X, 0.2361, places=4)

    def test_look_rotation_roll(self):
        cam, aim = Vec3(100, 150, 200), Vec3(-20, 140, -50)
        flat = sl.look_rotation(cam, aim)
        dutch = sl.look_rotation(cam, aim, 15)
        f0, f1 = sl.forward_from_rotation(flat), sl.forward_from_rotation(dutch)
        self.assertAlmostEqual(f0.dot(f1), 1.0, places=9)  # roll keeps the view axis
        self.assertAlmostEqual(f1.dot((aim - cam).normalize()), 1.0, places=9)
        u0, u1 = sl.camera_up(flat), sl.camera_up(dutch)
        self.assertAlmostEqual(math.degrees(math.acos(u0.dot(u1))), 15.0, places=6)
        left = -f0.cross(Vec3(0, 1, 0)).normalize()
        self.assertGreater(u1.dot(left), 0)  # top tips toward screen-left

    def test_keyframed_arc(self):
        shot = sl.arc("alice", start=0, end=120, step_deg=90, positions=POS, radius=200)
        keys = shot.movement.keyframes
        self.assertEqual([k.frame for k in keys], [0, 30, 60, 90, 120])
        target = Vec3(0, sl.SHOT_SIZES["medium"][1], 0)
        for k in keys:
            self.assertAlmostEqual(k.position.distance(target), 200, places=6)
            self.assertEqual(k.look_at, target)
        with self.assertRaises(ValueError):
            sl.arc("alice", start=0, end=10, step_deg=0, positions=POS)


class FocusTests(unittest.TestCase):
    def test_rack_focus_with_holds(self):
        pull = sl.rack_focus(Vec3(0, 160, 300), "alice", "bob", start=0, end=60, positions=POS,
                             hold_from=10, hold_to=10)
        self.assertEqual([(k.frame, round(k.focal_distance)) for k in pull.keys],
                         [(0, 300), (10, 300), (50, 420), (60, 420)])

    def test_rack_focus_distances_and_collapse(self):
        pull = sl.rack_focus(Vec3(0, 0, 0), 100.0, 250, start=0, end=10, hold_from=8, hold_to=8)
        self.assertEqual([(k.frame, k.focal_distance) for k in pull.keys], [(0, 100.0), (10, 250.0)])
        with self.assertRaises(ValueError):
            sl.rack_focus(Vec3(0, 0, 0), "alice", 100.0, start=0, end=10)  # key without positions

    def test_depth_of_field_limits(self):
        near, far = sl.depth_of_field_limits(50, 2.8, 300)
        self.assertAlmostEqual(near, 273.0, delta=0.5)  # DoF calculators (c=0.03): 50mm f/2.8 @ 3 m
        self.assertAlmostEqual(far, 332.9, delta=0.5)
        self.assertIsNone(sl.depth_of_field_limits(24, 11, 1000)[1])  # past hyperfocal
        with self.assertRaises(ValueError):
            sl.depth_of_field_limits(50, 0, 100)

    def test_with_rack_focus(self):
        shot = sl.with_rack_focus(sl.over_the_shoulder(line(), "alice", "bob"), "alice", "bob",
                                  start=0, end=24, positions=POS, f_stop=2.0)
        self.assertTrue(shot.lens.depth_of_field)
        self.assertEqual(shot.lens.f_stop, 2.0)
        d0, d1 = shot.focus.keys[0].focal_distance, shot.focus.keys[-1].focal_distance
        self.assertLess(d0, d1)  # foreground shoulder first, then Bob


class ContinuityTests(unittest.TestCase):
    def ms(self, az, size="medium"):
        return Shot(id=f"s{az}{size}", camera=Framing(subjects=("bob",), size=size, azimuth_deg=az))

    def test_thirty_degree_rule(self):
        issues = sl.check_thirty_degree([self.ms(0), self.ms(10)], POS)
        self.assertEqual([(i.kind, i.shot_id, i.other_shot_id) for i in issues],
                         [("thirty_degree", "s10medium", "s0medium")])
        self.assertEqual(sl.check_thirty_degree([self.ms(0), self.ms(45)], POS), [])
        self.assertEqual(sl.check_thirty_degree([self.ms(0), self.ms(10, "close_up")], POS), [])
        self.assertEqual(sl.check_thirty_degree([self.ms(0), sl.single(line(), "alice")], POS), [])

    def test_check_continuity_combines(self):
        shots = [self.ms(90), self.ms(95), self.ms(-90, "close_up")]
        kinds = sorted(i.kind for i in sl.check_continuity(shots, POS, line=line()))
        self.assertEqual(kinds, ["axis", "thirty_degree"])

    def test_plan_line_infers_side(self):
        plan = sl.dialogue_coverage(line(-1))
        self.assertEqual(sl.plan_line(plan, POS).side, -1)
        self.assertEqual(sl.check_plan(plan, POS), [])
        self.assertIsNone(sl.plan_line(sl.subject_coverage("bob"), POS))


class CoverageTests(unittest.TestCase):
    def test_subject_presets(self):
        for preset, n in (("standard", 3), ("interview", 3), ("dramatic", 4), ("action", 4)):
            plan = sl.subject_coverage("bob", preset=preset, azimuth_deg=30)
            self.assertEqual(len(plan.all_shots()), n)
            self.assertEqual(CoveragePlan.from_dict(json.loads(json.dumps(plan.to_dict()))), plan)
        dramatic = sl.subject_coverage("bob", preset="dramatic")
        self.assertEqual([s.id for s in dramatic.all_shots()],
                         ["WS_bob", "MS_low_bob", "MS_high_bob", "MCU_profile_bob"])
        with self.assertRaises(ValueError):
            sl.subject_coverage("bob", preset="nope")

    def test_dialogue_coverage_converts_to_recipe(self):
        plan = sl.dialogue_coverage(line())
        self.assertEqual([s.id for s in plan.all_shots()],
                         ["MST_alice-bob", "2S_alice-bob", "OTS_bob_over_alice", "OTS_alice_over_bob",
                          "CU_alice", "CU_bob"])
        sections = plan.to_recipe_sections()
        self.assertEqual(len(sections["cameras"]), 6)
        self.assertEqual(sl.dialogue_coverage(line(), include=("ots",)).all_shots()[0].id, "OTS_bob_over_alice")
        with self.assertRaises(ValueError):
            sl.dialogue_coverage(line(), include=("drone",))

    def test_conversation(self):
        beats = [DialogueBeat("alice", 0, 47, "Where were you?"), DialogueBeat("bob", 48, 95, "Out."),
                 DialogueBeat("alice", 96, 120)]
        plan = sl.conversation(line(), beats, establish_frames=24)
        shots = plan.all_shots()
        self.assertEqual([(s.id, s.frame_range) for s in shots], [
            ("000_MST_alice-bob", (0, 23)), ("001_OTS_alice_over_bob", (24, 47)),
            ("002_OTS_bob_over_alice", (48, 95)), ("003_OTS_alice_over_bob", (96, 120))])
        self.assertEqual(plan.axis, ("alice", "bob"))
        self.assertEqual(shots[1].storyboard.dialogue, "Where were you?")
        self.assertEqual([(g.actor, g.look_at) for g in shots[2].gaze], [("bob", "alice"), ("alice", "bob")])
        self.assertEqual(sl.check_plan(plan, POS), [])
        self.assertEqual(CoveragePlan.from_dict(json.loads(json.dumps(plan.to_dict()))), plan)

        singles = sl.conversation(line(-1), beats, style="singles")
        self.assertEqual([s.id for s in singles.all_shots()], ["001_MCU_alice", "002_MCU_bob", "003_MCU_alice"])
        self.assertEqual(sl.check_plan(singles, POS), [])

    def test_establish_swallowing_first_beat(self):
        plan = sl.conversation(line(), [DialogueBeat("alice", 0, 10), DialogueBeat("bob", 11, 20)],
                               establish_frames=30)
        self.assertEqual([s.frame_range for s in plan.all_shots()], [(0, 10), (11, 20)])

    def test_conversation_validation(self):
        with self.assertRaises(ValueError):
            sl.conversation(line(), [])
        with self.assertRaises(ValueError):
            sl.conversation(line(), [DialogueBeat("carol", 0, 10)])
        with self.assertRaises(ValueError):
            sl.conversation(line(), [DialogueBeat("alice", 0, 10), DialogueBeat("bob", 10, 20)])
        with self.assertRaises(ValueError):
            sl.conversation(line(), [DialogueBeat("alice", 0, 10)], style="wides")
        with self.assertRaises(ValueError):
            DialogueBeat("alice", 10, 0)


class ApplyCoverageTests(unittest.TestCase):
    def test_cameras_named_after_shots(self):
        scene = FakeScene()
        plan = sl.dialogue_coverage(line(), include=("master", "ots"))
        cams = sl.apply_coverage(scene, plan, subjects=POS)
        self.assertEqual(list(cams), ["MST_alice-bob", "OTS_bob_over_alice", "OTS_alice_over_bob"])
        self.assertEqual([n for n, _ in scene.created], list(cams))
        self.assertIn(("set", "label", "MST_alice-bob"), scene.created[0][1].calls)

    def test_reuses_given_cameras(self):
        scene = FakeScene()
        existing = FakeCamera()
        cams = sl.apply_coverage(scene, [sl.single(line(), "bob")], subjects=POS, cameras={"MCU_bob": existing})
        self.assertIs(cams["MCU_bob"], existing)
        self.assertEqual(scene.created, [])


if __name__ == "__main__":
    unittest.main()
