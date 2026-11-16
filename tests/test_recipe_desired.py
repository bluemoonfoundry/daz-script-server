"""Unit tests for pure desired-state computation."""

import copy
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from dazpy._recipe_desired import compute_desired
from dazpy._recipe_model import SceneRecipe


def recipe_with(actors=None, cameras=None, rigs=None, lights=None, props=None, env=None):
    d = {"recipe_version": 1, "id": "r", "assets": {"g": {"path": "/People/G.duf"},
                                                    "chair": {"path": "/Props/C.duf"}},
         "actors": actors or {"a": {"asset": "g"}}}
    if props:
        d["props"] = props
    if cameras:
        d["cameras"] = cameras
    lighting = {}
    if rigs:
        lighting["rigs"] = rigs
    if lights:
        lighting["lights"] = lights
    if env:
        lighting["environment"] = env
    if lighting:
        d["lighting"] = lighting
    if env:
        d["render"] = {"engine": "iray"}
    return SceneRecipe.from_dict(d)


def dist(a, b):
    return math.dist(a, b)


class DesiredTests(unittest.TestCase):
    def test_facing_computes_yaw_only(self):
        d = compute_desired(recipe_with(actors={"a": {"asset": "g", "position": [0, 0, 0], "facing": "b"},
                                                "b": {"asset": "g", "position": [100, 0, 100]}}))
        rot = d["actors.a"].channels["transform"]["rotation"]
        self.assertAlmostEqual(rot[1], 45.0, places=4)
        self.assertEqual(rot[0], 0.0)
        self.assertEqual(d["actors.a"].create, {"asset_path": "/People/G.duf"})
        self.assertEqual(d["actors.a"].label, "r:a")

    def test_framing_camera_aims_at_the_actors_face_for_a_close_up(self):
        # Actor positions are on the floor: a close-up aims at face height (160 cm)
        # and stands back far enough that 40 cm of subject fills a 4:3 frame
        # (Daz frame width 36 mm, so 27 mm vertical) at the recipe's focal length.
        d = compute_desired(recipe_with(actors={"anna": {"asset": "g", "position": [-60, 0, 0]}},
                                        cameras={"cu": {"frame": "anna", "shot_type": "close_up",
                                                        "focal_length": 85}}))
        t = d["cameras.cu"].channels["transform"]
        self.assertEqual(t["aim"], (-60.0, 160.0, 0.0))
        self.assertAlmostEqual(dist(t["position"], t["aim"]), 40 * 85 / 27, places=4)
        self.assertIsNone(t["rotation"])

    def test_full_body_fits_a_standing_figure(self):
        d = compute_desired(recipe_with(actors={"anna": {"asset": "g"}},
                                        cameras={"w": {"frame": "anna", "shot_type": "full_body"}}))
        t = d["cameras.w"].channels["transform"]
        self.assertEqual(t["aim"], (0.0, 90.0, 0.0))
        self.assertAlmostEqual(dist(t["position"], t["aim"]), 210 * 50 / 27, places=4)

    def test_framing_distance_follows_the_render_aspect(self):
        r = recipe_with(actors={"anna": {"asset": "g"}},
                        cameras={"m": {"frame": "anna", "shot_type": "medium"}}).to_dict()
        r["render"] = {"resolution": [600, 900]}  # portrait: 36 * 900/600 = 54 mm vertical
        t = compute_desired(SceneRecipe.from_dict(r))["cameras.m"].channels["transform"]
        self.assertEqual(t["aim"], (0.0, 130.0, 0.0))
        self.assertAlmostEqual(dist(t["position"], t["aim"]), 100 * 50 / 54, places=4)

    def test_framing_a_prop_aims_at_its_position(self):
        d = compute_desired(recipe_with(props={"chair": {"asset": "chair", "position": [5, 0, 7]}},
                                        cameras={"c": {"frame": "chair", "shot_type": "close_up"}}))
        self.assertEqual(d["cameras.c"].channels["transform"]["aim"], (5.0, 0.0, 7.0))

    def test_multi_subject_frames_centroid(self):
        d = compute_desired(recipe_with(
            actors={"a": {"asset": "g", "position": [0, 0, 0]}, "b": {"asset": "g", "position": [100, 0, 40]}},
            cameras={"w": {"frame": ["a", "b"], "shot_type": "full_body"}}))
        t = d["cameras.w"].channels["transform"]
        self.assertEqual(t["aim"], (50.0, 90.0, 20.0))
        self.assertAlmostEqual(dist(t["position"], t["aim"]), 210 * 50 / 27, places=4)

    def test_rig_lights_aim_at_the_actors_chest(self):
        d = compute_desired(recipe_with(actors={"anna": {"asset": "g", "position": [0, 0, 0]}},
                                        rigs={"main": {"type": "three_point", "target": "anna"}}))
        key = d["lighting.rigs.main.key"].channels["transform"]
        from dazpy._shot_geometry import look_at_euler
        from dazpy.math3 import Vec3
        self.assertGreater(key["position"][1], 130.0)
        expected = look_at_euler(Vec3(*key["position"]), Vec3(0.0, 130.0, 0.0))
        for got, want in zip(key["rotation"], expected):
            self.assertAlmostEqual(got, want, places=4)

    def test_explicit_camera_look_at_actor_aims_at_its_chest(self):
        d = compute_desired(recipe_with(
            actors={"a": {"asset": "g", "position": [10, 5, 20]}},
            cameras={"m": {"position": [0, 100, 300], "look_at": "a"}}))
        t = d["cameras.m"].channels["transform"]
        self.assertEqual(t["aim"], (10.0, 135.0, 20.0))
        self.assertEqual(t["position"], (0.0, 100.0, 300.0))

    def _r(self, x):
        return recipe_with(actors={"anna": {"asset": "g", "position": [x, 0, 0]}},
                           cameras={"cu": {"frame": "anna"}},
                           rigs={"main": {"type": "three_point", "target": "anna"}})

    def test_moving_actor_changes_dependent_camera_and_rig(self):
        before, after = compute_desired(self._r(0)), compute_desired(self._r(50))
        self.assertNotEqual(before["cameras.cu"].channels, after["cameras.cu"].channels)
        self.assertNotEqual(before["lighting.rigs.main.key"].channels,
                            after["lighting.rigs.main.key"].channels)

    def test_rig_expands_to_three_lights_with_overrides(self):
        d = compute_desired(recipe_with(rigs={"main": {"type": "three_point", "target": "a",
                                                       "key": {"intensity": 120}}}))
        self.assertEqual(d["lighting.rigs.main.key"].channels["output"]["intensity"], 120)
        self.assertEqual(d["lighting.rigs.main.fill"].channels["output"]["intensity"], 50.0)
        self.assertEqual(d["lighting.rigs.main.rim"].label, "r:main.rim")
        self.assertEqual(d["lighting.rigs.main.rim"].create, {"light_type": "spot"})

    def test_lights_environment_props(self):
        d = compute_desired(recipe_with(
            props={"c": {"asset": "chair", "position": [1, 2, 3]}},
            lights={"p": {"type": "point", "position": [0, 100, 0], "look_at": [0, 0, 0],
                          "intensity": 80, "color": [255, 200, 150]}},
            env={"type": "hdri", "image_path": "C:/x.hdr"}))
        self.assertEqual(d["props.c"].channels["transform"]["position"], (1.0, 2.0, 3.0))
        p = d["lighting.lights.p"]
        self.assertAlmostEqual(p.channels["transform"]["rotation"][0], -90.0, places=4)
        self.assertEqual(p.channels["output"]["color"], (255, 200, 150))
        self.assertEqual(d["lighting.environment"].channels["environment"]["mode"], "dome_only")
        self.assertEqual(d["lighting.environment"].create, {})

    def test_compute_desired_is_deterministic(self):
        r = self._r(10)
        self.assertEqual(compute_desired(r), compute_desired(SceneRecipe.from_dict(copy.deepcopy(r.to_dict()))))


if __name__ == "__main__":
    unittest.main()
