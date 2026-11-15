"""
Live tests for scene recipes (dazpy.recipe).  Skipped when DAZ Studio is not
reachable.  Run scoped:  python -m pytest tests/test_recipe_live.py -v -k recipe

Each test uses its own recipe id and output dir under C:/temp/recipe_live/<test>
and starts from an empty scene (Scene.clear()).
"""

import copy
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import requests as _req

from dazpy import DazClient, DazScene
from dazpy._recipe_ops import DazSceneOps
from dazpy.recipe import apply, observe, plan, render, validate

# ── Server availability (same detection as test_dazpy_integration.py) ─────────

_SERVER_UP: bool = False
_SERVER_SKIP_REASON = "DAZ Studio script server not reachable at 127.0.0.1:18811"

try:
    _resp = _req.get("http://127.0.0.1:18811/status", timeout=2)
    _SERVER_UP = _resp.status_code == 200
except Exception:
    pass

_DAZ_GLOBALS_AVAILABLE: bool = False

if _SERVER_UP:
    try:
        _gr = _req.post(
            "http://127.0.0.1:18811/execute",
            json={"script": "(function(){ return typeof Scene === 'object' && Scene.getNumNodes !== undefined; })()"},
            headers={"X-API-Token": DazClient()._token},
            timeout=3,
        )
        _DAZ_GLOBALS_AVAILABLE = bool(_gr.status_code == 200 and _gr.json().get("result") is True)
    except Exception:
        pass

skip_if_down = unittest.skipUnless(_SERVER_UP, _SERVER_SKIP_REASON)
skip_no_daz = unittest.skipUnless(
    _DAZ_GLOBALS_AVAILABLE, "Scene not available (DAZ Studio not running or no scene loaded)")

# ── Helpers ───────────────────────────────────────────────────────────────────

_EXAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "examples",
                        "recipes", "g9-portrait.json")
_OUT = "C:/temp/recipe_live"


def _example(test: str) -> dict:
    """The shipped example with an id and output dir unique to *test*."""
    with open(_EXAMPLE, encoding="utf-8") as f:
        data = json.load(f)
    data["id"] = f"live-{test}"
    for shot in data["shots"]:
        shot["output"] = f"{_OUT}/{test}/{shot['id']}.png"
    return data


def _new_scene() -> DazScene:
    """File > New equivalent: an empty scene (no save prompt)."""
    scene = DazScene()
    scene._client.execute("(function(){ Scene.clear(); return true; })()")
    return scene


@skip_if_down
@skip_no_daz
class TestSceneRecipeLive(unittest.TestCase):
    def tearDown(self):
        # Leave Studio with an empty scene, whatever the test did.
        try:
            DazScene()._client.execute("(function(){ Scene.clear(); return true; })()")
        except Exception:
            pass

    def _tweak_key(self, recipe: dict, scene: DazScene) -> dict:
        """Move the rig's key light 30 cm by hand; return its new position."""
        key = scene.find_node_by_label(f"{recipe['id']}:main.key")
        pos = key.position
        key.set_position(pos["x"] + 30, pos["y"], pos["z"])
        return key.position

    def test_recipe_example_renders_end_to_end(self):
        recipe = _example("end_to_end")
        scene = _new_scene()
        self.assertTrue(validate(recipe, scene).ok)
        self.assertTrue(apply(recipe, scene).applied)
        renders = render(recipe, scene)
        self.assertEqual([r.shot_id for r in renders], ["full_body", "close_up"])
        for shot in renders:
            self.assertTrue(os.path.isfile(shot.output), shot.output)
            self.assertGreater(os.path.getsize(shot.output), 0)

    def test_recipe_reapply_changes_only_moved_camera(self):
        recipe = _example("moved_camera")
        scene = _new_scene()
        self.assertTrue(apply(recipe, scene).applied)
        moved = copy.deepcopy(recipe)
        moved["cameras"]["close_up"]["azimuth_deg"] = 45
        steps = plan(moved, scene).steps
        self.assertEqual([(s.op, s.path) for s in steps], [("modify", "cameras.close_up")])

    def test_recipe_hand_tweak_warns_then_conflicts(self):
        recipe = _example("hand_tweak")
        scene = _new_scene()
        self.assertTrue(apply(recipe, scene).applied)
        key = scene.find_node_by_label(f"{recipe['id']}:main.key")
        pos = key.position
        key.set_position(pos["x"] + 30, pos["y"], pos["z"])

        same = apply(recipe, scene)
        self.assertTrue(same.applied)
        self.assertIn("hand_tweak_kept", [w.code for w in same.warnings])

        changed = copy.deepcopy(recipe)
        changed["lighting"]["rigs"]["main"]["key"] = {"azimuth_deg": 60}
        blocked = apply(changed, scene)
        self.assertFalse(blocked.applied)
        self.assertEqual([c.path for c in blocked.conflicts], ["lighting.rigs.main.key.transform"])

        won = apply(changed, scene, on_conflict="recipe_wins")
        self.assertTrue(won.applied)

    def test_recipe_remove_actor_deletes_node(self):
        recipe = _example("remove_actor")
        scene = _new_scene()
        self.assertTrue(apply(recipe, scene).applied)
        label = f"{recipe['id']}:model"
        scene.find_node_by_label(label)  # exists
        # Drop the actor and everything that references it.
        bare = {"recipe_version": 1, "id": recipe["id"], "assets": recipe["assets"]}
        result = apply(bare, scene)
        self.assertTrue(result.applied)
        self.assertIn(("delete", "actors.model"), [(s.op, s.path) for s in result.steps])
        with self.assertRaises(Exception):
            scene.find_node_by_label(label)

    def test_recipe_rollback_restores_scene(self):
        recipe = _example("rollback")
        scene = _new_scene()
        self.assertTrue(apply(recipe, scene).applied)
        edited = copy.deepcopy(recipe)
        edited["cameras"]["close_up"]["focal_length"] = 120
        edited["cameras"]["full_body"]["focal_length"] = 35
        before = observe(edited, scene)

        real = DazSceneOps.set_channels
        calls = {"n": 0}

        def flaky(self_, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("injected failure")
            return real(self_, *args, **kwargs)

        with mock.patch.object(DazSceneOps, "set_channels", flaky):
            result = apply(edited, scene)
        self.assertFalse(result.applied)
        self.assertTrue(result.rolled_back)
        self.assertEqual(result.rollback_errors, ())
        self.assertEqual(observe(edited, scene), before)

    def test_recipe_reapply_after_save_reload(self):
        recipe = _example("save_reload")
        scene = _new_scene()
        self.assertTrue(apply(recipe, scene).applied)
        path = f"{_OUT}/save_reload/scene.duf"
        scene._client.execute(
            f'(function(){{ new DzDir("{_OUT}/save_reload").mkpath("{_OUT}/save_reload"); return true; }})()')
        scene.save(path)
        scene = _new_scene()
        scene.load(path)
        after = plan(recipe, scene)
        self.assertEqual(after.steps, ())
        self.assertEqual(after.warnings, ())

    def test_recipe_ask_conflict_changes_nothing(self):
        recipe = _example("ask_blocks")
        scene = _new_scene()
        self.assertTrue(apply(recipe, scene).applied)
        tweaked = self._tweak_key(recipe, scene)
        changed = copy.deepcopy(recipe)
        changed["lighting"]["rigs"]["main"]["key"] = {"azimuth_deg": 60}
        changed["cameras"]["close_up"]["focal_length"] = 120  # a safe change, blocked too
        before = observe(changed, scene)
        result = apply(changed, scene, on_conflict="ask")
        self.assertFalse(result.applied)
        self.assertEqual([c.path for c in result.conflicts], ["lighting.rigs.main.key.transform"])
        self.assertEqual(observe(changed, scene), before)
        key = scene.find_node_by_label(f"{recipe['id']}:main.key")
        self.assertAlmostEqual(key.position["x"], tweaked["x"], places=1)

    def test_recipe_scene_wins_keeps_tweak_and_adopts_it(self):
        recipe = _example("scene_wins")
        scene = _new_scene()
        self.assertTrue(apply(recipe, scene).applied)
        tweaked = self._tweak_key(recipe, scene)
        changed = copy.deepcopy(recipe)
        changed["lighting"]["rigs"]["main"]["key"] = {"azimuth_deg": 60}
        result = apply(changed, scene, on_conflict="scene_wins")
        self.assertTrue(result.applied)
        self.assertEqual(result.kept, ("lighting.rigs.main.key.transform",))
        key = scene.find_node_by_label(f"{recipe['id']}:main.key")
        self.assertAlmostEqual(key.position["x"], tweaked["x"], places=1)
        again = plan(changed, scene)  # the tweak was adopted into the record
        self.assertEqual((again.steps, again.warnings, again.conflicts), ((), (), ()))


if __name__ == "__main__":
    unittest.main()
