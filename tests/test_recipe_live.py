"""
Live tests for scene recipes (dazpy.recipe).  Opt-in: skipped unless
DAZ_LIVE_TESTS=1, and when DAZ Studio is not reachable.  Run scoped:
    DAZ_LIVE_TESTS=1 python -m pytest tests/test_recipe_live.py -v -k recipe

Each TestSceneRecipeLive test uses its own recipe id and output dir under
C:/temp/recipe_live/<test> and starts from an empty scene (Scene.clear()). It
refuses to clear a scene that has content unless DAZ_LIVE_ALLOW_CLEAR=1.
AssetFittingLiveTests (scene recipe v2 asset refs and fitting) never clears the
scene; run it on its own: python -m pytest tests/test_recipe_live.py -v -k AssetFitting
Its tests skip unless the DAZ_LIVE_* content paths they need are set (see the
section comment above AssetFittingLiveTests).

Known issue (2026-11-27, DS4 4.24): test_take_over_hand_built_and_swap_hair_by_type
hung Studio's main thread once (every call answered busy; cause unknown, possibly
another client driving the same Studio at the time). It still needs a clean
re-run (its G8 and release checks are now the separate
test_g8_hair_on_taken_over_figure_rejected and test_release_keeps_taken_over_figure),
as do test_fit_failure_keeps_hand_hair,
test_multi_node_hair_and_outfit_add_swap_remove and test_records_have_source (none
of these ran live yet), and the whole class on DS6.
"""

# Opt-in gate (tests/live_gate.py): skip this module unless DAZ_LIVE_TESTS=1
# (or it is run directly), before anything below contacts DAZ Studio.
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from live_gate import clear_scene, require_live  # noqa: E402
require_live(__name__)

import copy
import json
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import requests as _req

from dazpy import DazClient, DazScene
from dazpy._recipe_ops import DazSceneOps
from dazpy._recipe_store import read_live
from dazpy.exceptions import RecipeValidationError
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


# One client for the whole module, waiting out busy replies: Studio 6 reports
# busy for a moment after a clear or load, and the tests' own calls (clear,
# find, move, save, load) are not recipe calls, which wait by themselves.
_CLIENT = DazClient() if _SERVER_UP else None
_BUSY_WAIT_S = 120.0


def _new_scene() -> DazScene:
    """File > New equivalent: an empty scene (no save prompt).

    Skips the test instead when the open scene has content the tests didn't
    make (live_gate.clear_scene; DAZ_LIVE_ALLOW_CLEAR=1 overrides).
    """
    scene = DazScene(_CLIENT)
    clear_scene(_CLIENT)
    return scene


@skip_if_down
@skip_no_daz
class TestSceneRecipeLive(unittest.TestCase):
    def setUp(self):
        wait = _CLIENT.waiting_out_busy(_BUSY_WAIT_S)  # enterContext needs 3.11
        wait.__enter__()
        self.addCleanup(wait.__exit__, None, None, None)

    def tearDown(self):
        # Leave Studio with an empty scene, whatever the test did (never the
        # user's scene: clear_scene refuses until the tests have cleared once).
        try:
            clear_scene(_CLIENT)
        except Exception:
            pass

    def assertApplied(self, result) -> None:
        """Fail with the apply's own diagnosis, not just "False is not true"."""
        if not result.applied:
            step = result.failed_step
            self.fail(f"apply failed: error={result.error!r} "
                      f"failed_step={f'{step.op} {step.path}' if step else None} "
                      f"conflicts={[c.path for c in result.conflicts]} "
                      f"rolled_back={result.rolled_back} "
                      f"rollback_errors={list(result.rollback_errors)}")

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
        self.assertApplied(apply(recipe, scene))
        renders = render(recipe, scene)
        self.assertEqual([r.shot_id for r in renders], ["full_body", "close_up"])
        for shot in renders:
            self.assertTrue(os.path.isfile(shot.output), shot.output)
            self.assertGreater(os.path.getsize(shot.output), 0)

    def test_recipe_reapply_changes_only_moved_camera(self):
        recipe = _example("moved_camera")
        scene = _new_scene()
        self.assertApplied(apply(recipe, scene))
        moved = copy.deepcopy(recipe)
        moved["cameras"]["close_up"]["azimuth_deg"] = 45
        steps = plan(moved, scene).steps
        self.assertEqual([(s.op, s.path) for s in steps], [("modify", "cameras.close_up")])

    def test_recipe_hand_tweak_warns_then_conflicts(self):
        recipe = _example("hand_tweak")
        scene = _new_scene()
        self.assertApplied(apply(recipe, scene))
        key = scene.find_node_by_label(f"{recipe['id']}:main.key")
        pos = key.position
        key.set_position(pos["x"] + 30, pos["y"], pos["z"])

        same = apply(recipe, scene)
        self.assertApplied(same)
        self.assertIn("hand_tweak_kept", [w.code for w in same.warnings])

        changed = copy.deepcopy(recipe)
        changed["lighting"]["rigs"]["main"]["key"] = {"azimuth_deg": 60}
        blocked = apply(changed, scene)
        self.assertFalse(blocked.applied)
        self.assertEqual([c.path for c in blocked.conflicts], ["lighting.rigs.main.key.transform"])

        won = apply(changed, scene, on_conflict="recipe_wins")
        self.assertApplied(won)

    def test_recipe_remove_actor_deletes_node(self):
        recipe = _example("remove_actor")
        scene = _new_scene()
        self.assertApplied(apply(recipe, scene))
        label = f"{recipe['id']}:model"
        scene.find_node_by_label(label)  # exists
        # Drop the actor and everything that references it.
        bare = {"recipe_version": 1, "id": recipe["id"], "assets": recipe["assets"]}
        result = apply(bare, scene)
        self.assertApplied(result)
        self.assertIn(("delete", "actors.model"), [(s.op, s.path) for s in result.steps])
        with self.assertRaises(Exception):
            scene.find_node_by_label(label)

    def test_recipe_rollback_restores_scene(self):
        recipe = _example("rollback")
        scene = _new_scene()
        self.assertApplied(apply(recipe, scene))
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

    def test_recipe_pose_only_change_keeps_recipe_transform(self):
        """5d6f.30 item 5: a pose preset that also moves the figure's root
        (common in prop-interaction poses) must not move a recipe actor off
        its recipe transform when the pose is the only thing that changed."""
        recipe = _example("pose_only")
        scene = _new_scene()
        self.assertApplied(apply(recipe, scene))
        figure = scene.find_node_by_label(f"{recipe['id']}:model")
        before_pos, before_rot = figure.position, figure.rotation

        os.makedirs(f"{_OUT}/pose_only", exist_ok=True)
        preset = f"{_OUT}/pose_only/root_moving_pose.duf"
        with open(preset, "w", encoding="utf-8") as fh:
            json.dump({
                "file_version": "0.6.0.0",
                "asset_info": {"id": "/root_moving_pose.duf", "type": "preset_pose",
                               "contributor": {"author": "dazpy tests"}, "revision": "1.0"},
                "scene": {"animations": [
                    {"url": "name://@selection:?translation/x/value", "keys": [[0, 55.0]]},
                    {"url": "name://@selection:?translation/z/value", "keys": [[0, -120.0]]},
                    {"url": "name://@selection:?rotation/y/value", "keys": [[0, 40.0]]},
                ]},
            }, fh)

        posed = copy.deepcopy(recipe)
        posed["actors"]["model"]["pose"] = preset
        steps = plan(posed, scene).steps
        self.assertEqual([(s.op, s.path) for s in steps], [("modify", "actors.model")])
        self.assertApplied(apply(posed, scene))

        after_pos, after_rot = figure.position, figure.rotation
        for axis in "xyz":
            self.assertAlmostEqual(after_pos[axis], before_pos[axis], places=2, msg=f"position {axis}")
            self.assertAlmostEqual(after_rot[axis], before_rot[axis], places=2, msg=f"rotation {axis}")
        self.assertEqual(list(plan(posed, scene).steps), [], "re-plan after apply is not clean")

    def test_recipe_reapply_after_save_reload(self):
        recipe = _example("save_reload")
        scene = _new_scene()
        self.assertApplied(apply(recipe, scene))
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
        self.assertApplied(apply(recipe, scene))
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
        self.assertApplied(apply(recipe, scene))
        tweaked = self._tweak_key(recipe, scene)
        changed = copy.deepcopy(recipe)
        changed["lighting"]["rigs"]["main"]["key"] = {"azimuth_deg": 60}
        result = apply(changed, scene, on_conflict="scene_wins")
        self.assertApplied(result)
        self.assertEqual(result.kept, ("lighting.rigs.main.key.transform",))
        key = scene.find_node_by_label(f"{recipe['id']}:main.key")
        self.assertAlmostEqual(key.position["x"], tweaked["x"], places=1)
        again = plan(changed, scene)  # the tweak was adopted into the record
        self.assertEqual((again.steps, again.warnings, again.conflicts), ((), (), ()))


# ── Scene recipe v2: asset references, compatibility, fitting (5d6f.21) ───────
#
# Spec docs/superpowers/specs/2026-11-26-asset-refs-and-fitting-design.md §12.
# Content paths come from the environment (content-relative or absolute), so the
# tests run on any library; each test skips when a path it needs is unset:
#
#   DAZ_LIVE_G9F         a Genesis 9 figure        /People/Genesis 9/Genesis 9.duf
#   DAZ_LIVE_HAIR_A      a Genesis 9 hair          (the "hand-built" / first hair)
#   DAZ_LIVE_HAIR_B      another Genesis 9 hair    (the swap target)
#   DAZ_LIVE_HAIR_MULTI  a G9 hair loading several root nodes (hair + cap / flower)
#   DAZ_LIVE_OUTFIT      a G9 wearables preset loading several garments
#   DAZ_LIVE_G8_HAIR     a Genesis 8 hair (never loaded: must fail compatibility)
#   DAZ_LIVE_PRESET      optional: a G9 figure preset (shape / materials) for Abby
#   DAZ_LIVE_AMBIGUOUS_FIND  optional search phrase matching several hairs (default "ponytail")
#
# Unlike the v1 tests above, these never clear the scene (Studio may be shared):
# every test works on figures with its own label ("Abby-live-<test>"), loads
# only through recipe apply (resolve_files, nothing selected), and removes what
# it created with the recipe delete (DzDeleteAction on an exact selection).
# setUp records the scene's root nodes; if any of them disappears during a test,
# something outside the test changed the scene and the test stops with an
# "environment interference" failure instead of carrying on.

_FIXTURE_ABBY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "recipes",
                             "v2", "valid", "abby_live.json")
_LIVE_VARS = ("DAZ_LIVE_G9F", "DAZ_LIVE_HAIR_A", "DAZ_LIVE_HAIR_B", "DAZ_LIVE_HAIR_MULTI",
              "DAZ_LIVE_OUTFIT", "DAZ_LIVE_G8_HAIR", "DAZ_LIVE_PRESET")
# A loaded G9 plus a dForce hair fit takes ~30 s on DS4; nothing here should
# come near this unless a modal dialog blocks Studio's main thread.
_NO_MODAL_S = 120.0

_ROOTS_SCRIPT = """(function(){
var l = Scene.getNodeList(), o = [];
for (var i = 0; i < l.length; i++) {
    var n = l[i];
    if (!n.getNodeParent()) o.push([n.getName(), n.getLabel()]);
}
return {count: l.length, roots: o};
})()"""


def _env(name: str) -> str | None:
    return os.environ.get(name) or None


def _roots() -> tuple[int, list[tuple[str, str]]]:
    """``(node count, [(name, label)] of root nodes)``; read-only."""
    value = _CLIENT.execute(_ROOTS_SCRIPT).value or {}
    return int(value.get("count") or 0), [tuple(r) for r in value.get("roots") or []]


_MANIFEST_PREFIX = "dazpy.scene_recipe."
_LIVE_IDS = ("live-af-", "live-hand-")  # recipe ids these tests use, and only these


def _live_manifests() -> list[str]:
    """Names of the scene-level recipe manifests for this class's recipe ids; read-only."""
    names = _CLIENT.execute(
        "(function(){var o=[];for(var i=0;i<Scene.getNumDataItems();i++)"
        "o.push(Scene.getDataItem(i).name);return o;})()").value or []
    return [n for n in names
            if n.startswith(_MANIFEST_PREFIX) and n[len(_MANIFEST_PREFIX):].startswith(_LIVE_IDS)]


def _remove_manifests(names: list[str]) -> None:
    """Remove the named scene-level manifests (only names from _live_manifests())."""
    if names:
        _CLIENT.execute(
            "(function(){var n=" + json.dumps(names) + ";for(var i=0;i<n.length;i++){"
            "var d=Scene.findDataItem(n[i]);if(d)Scene.removeDataItem(d);}return true;})()")


def _scene_revision() -> int | None:
    try:
        return _req.get("http://127.0.0.1:18811/status", timeout=5).json().get("scene_revision")
    except Exception:
        return None


def _abby_fixture(rid: str, label: str) -> dict:
    """``abby_live.json`` with the content paths from the environment, *rid* and *label*.

    The preset is dropped when ``DAZ_LIVE_PRESET`` is unset."""
    with open(_FIXTURE_ABBY, encoding="utf-8") as f:
        text = f.read()
    for name in _LIVE_VARS:
        value = _env(name)
        if value is not None:
            text = text.replace("${" + name + "}", json.dumps(value)[1:-1])
    data = json.loads(text)
    data["id"] = rid
    actor = data["actors"]["abby"]
    actor["node"] = label
    if _env("DAZ_LIVE_PRESET") is None:
        del actor["presets"]
    return data


class EnvironmentInterference(AssertionError):
    """The scene changed in a way the running test did not cause."""


@skip_if_down
@skip_no_daz
class AssetFittingLiveTests(unittest.TestCase):
    """Spec §12 acceptance on a live Studio (scoped: ``-k AssetFitting``)."""

    # The content each test needs (the only list: tests read the values with _env);
    # checked before setUp sends anything to Studio.
    _NEEDS = {
        "test_empty_scene_build_abby": ("DAZ_LIVE_G9F", "DAZ_LIVE_HAIR_A"),
        "test_take_over_hand_built_and_swap_hair_by_type":
            ("DAZ_LIVE_G9F", "DAZ_LIVE_HAIR_A", "DAZ_LIVE_HAIR_B"),
        "test_g8_hair_on_taken_over_figure_rejected":
            ("DAZ_LIVE_G9F", "DAZ_LIVE_HAIR_A", "DAZ_LIVE_G8_HAIR"),
        "test_release_keeps_taken_over_figure": ("DAZ_LIVE_G9F", "DAZ_LIVE_HAIR_A"),
        "test_g8_hair_rejected_scene_unchanged": ("DAZ_LIVE_G9F", "DAZ_LIVE_G8_HAIR"),
        "test_ambiguous_find_changes_nothing": ("DAZ_LIVE_G9F",),
        "test_fit_failure_keeps_hand_hair":
            ("DAZ_LIVE_G9F", "DAZ_LIVE_HAIR_A", "DAZ_LIVE_HAIR_B", "DAZ_LIVE_OUTFIT"),
        "test_multi_node_hair_and_outfit_add_swap_remove":
            ("DAZ_LIVE_G9F", "DAZ_LIVE_OUTFIT", "DAZ_LIVE_HAIR_MULTI"),
        "test_records_have_source": ("DAZ_LIVE_G9F", "DAZ_LIVE_HAIR_A", "DAZ_LIVE_OUTFIT"),
    }

    def setUp(self):
        self.need(*self._NEEDS[self._testMethodName])  # every test has an entry
        wait = _CLIENT.waiting_out_busy(_BUSY_WAIT_S)  # enterContext needs 3.11
        wait.__enter__()
        self.addCleanup(wait.__exit__, None, None, None)
        self.scene = DazScene(_CLIENT)
        self.count0, self.roots0 = _roots()
        self.manifests0 = set(_live_manifests())
        self.rev0 = _scene_revision()
        print(f"\n[{self._testMethodName}] scene_revision={self.rev0} nodes={self.count0} "
              f"roots={[label for _, label in self.roots0]}")
        self._labels: list[str] = []
        self.addCleanup(self._cleanup)

    # ── helpers ───────────────────────────────────────────────────────────────

    def need(self, *names: str) -> None:
        missing = [n for n in names if _env(n) is None]
        if missing:
            self.skipTest(f"set {', '.join(missing)} to run this test")

    def label(self, test: str) -> str:
        """A figure label unique to *test*; the figure is deleted after the test."""
        label = f"Abby-live-{test}"
        if self.figures(label):
            raise EnvironmentInterference(
                f"a figure labelled {label!r} is already in the scene (left by an earlier run "
                "or another session); remove it by hand and re-run")
        self._labels.append(label)
        return label

    def figures(self, label: str):
        from dazpy._recipe_fitted import read_figures
        return read_figures(_CLIENT, [label], [])[label]

    def figure(self, label: str):
        figs = self.figures(label)
        self.check_environment()
        self.assertEqual(len(figs), 1, f"expected one figure labelled {label!r}, found {len(figs)}")
        return figs[0]

    def hair(self, fig) -> list:
        return [it for it in fig.items if (it.type or "").startswith("Follower/Hair")]

    def check_environment(self) -> None:
        """Stop when a root node that was in the scene before the test is gone."""
        _, roots = _roots()
        gone = [r for r in self.roots0 if r not in roots]
        if gone:
            raise EnvironmentInterference(
                f"root nodes present when the test started are gone: {gone} (scene_revision was "
                f"{self.rev0}, now {_scene_revision()}); something outside this test changed the "
                "scene. Not retrying.")

    def assertApplied(self, result) -> None:
        if not result.applied:
            step = result.failed_step
            self.fail(f"apply failed: error={result.error!r} "
                      f"failed_step={f'{step.op} {step.path}' if step else None} "
                      f"conflicts={[c.path for c in result.conflicts]} "
                      f"rolled_back={result.rolled_back} "
                      f"rollback_errors={list(result.rollback_errors)}")

    def timed(self, fn, *args, **kwargs):
        """Call *fn*; fail if it took longer than a modal-free call could."""
        t0 = time.monotonic()
        try:
            return fn(*args, **kwargs)
        finally:
            took = time.monotonic() - t0
            self.assertLess(took, _NO_MODAL_S, f"{fn.__name__} took {took:.0f}s (modal dialog?)")

    def hand_built(self, label: str, hair: str) -> list[str]:
        """A figure labelled *label* wearing *hair*, owned by no recipe: built by a
        helper recipe, whose ownership records are then removed.  Returns the
        hair's node names."""
        rid = f"live-hand-{label}"
        self.assertApplied(apply({"recipe_version": 2, "id": rid, "actors": {"abby": {
            "node": label, "asset": _env("DAZ_LIVE_G9F"),
            "wearing": [{"add": hair, "key": "hair"}]}}}, self.scene))
        ops = DazSceneOps(self.scene)
        for entity in read_live(_CLIENT, rid).entities.values():
            for name in dict.fromkeys((entity.node_name,) + entity.group_nodes):
                ops.remove_record(name)
        fig = self.figure(label)
        self.assertIsNone(fig.record)
        names = [it.name for it in self.hair(fig)]
        self.assertTrue(names, "the hand-built figure has no hair")
        self.assertTrue(all(it.record is None for it in self.hair(fig)))
        return names

    def _cleanup(self) -> None:
        """Delete the figures this test created (recipe delete: DzDeleteAction on
        the figure, which takes its fitted items with it).  Only figures with
        this test's labels that were not in the scene when it started."""
        before = {name for name, _ in self.roots0}
        ops = DazSceneOps(self.scene)
        for label in self._labels:
            try:
                for fig in self.figures(label):
                    if fig.name not in before:
                        ops.delete(fig.name)
            except Exception as e:  # report, never retry against a stuck Studio
                print(f"cleanup of {label!r} failed: {e}")
        # Deleting the figures leaves each recipe's scene-level manifest behind, and a
        # re-run of the same recipe id would then see "deleted in scene" conflicts.
        # Remove only the live-test manifests this test added.
        try:
            _remove_manifests(sorted(set(_live_manifests()) - self.manifests0))
        except Exception as e:
            print(f"cleanup of recipe manifests failed: {e}")

    # ── tests ─────────────────────────────────────────────────────────────────

    def test_empty_scene_build_abby(self):
        """Abby (spec §1) from nothing: create + optional preset + fitted hair."""
        label = self.label("build")
        recipe = _abby_fixture("live-af-build", label)
        report = self.timed(validate, recipe, self.scene)
        self.assertTrue(report.ok, report.errors)
        self.assertNotIn("incompatible_asset", [w.code for w in report.warnings])

        result = self.timed(apply, recipe, self.scene)
        self.assertApplied(result)
        ops = [s.op for s in result.steps]
        self.assertEqual(ops[0], "create")
        self.assertIn("fit", ops)
        if _env("DAZ_LIVE_PRESET"):
            self.assertIn("preset", ops)

        fig = self.figure(label)
        self.assertTrue(fig.compat_base, "the figure reports no compatibility base")
        live = read_live(_CLIENT, recipe["id"])
        hair = live.entities["actors.abby.wearing.hair"]
        item_names = {it.name for it in fig.items}
        self.assertTrue(set((hair.node_name,) + hair.group_nodes) <= item_names,
                        "the recipe's hair is not fitted to Abby")
        again = plan(recipe, self.scene)
        self.assertEqual(again.steps, (), "re-plan after apply is not clean")

    def test_take_over_hand_built_and_swap_hair_by_type(self):
        """A hand-built Abby is taken over and her hair swapped by ``{type: hair}``."""
        hair_a, hair_b = _env("DAZ_LIVE_HAIR_A"), _env("DAZ_LIVE_HAIR_B")
        label = self.label("takeover")
        hand_hair = self.hand_built(label, hair_a)
        fig0 = self.figure(label)

        recipe = {"recipe_version": 2, "id": "live-af-takeover", "actors": {"abby": {
            "node": label,
            "wearing": [{"replace": {"type": "hair"}, "key": "hair",
                         "with": {"path": hair_b, "type": "hair"}}]}}}
        p = self.timed(plan, recipe, self.scene)
        self.assertEqual([s.op for s in p.steps if s.op in ("take_over", "fit", "unfit")],
                         ["take_over", "fit", "unfit"])
        # hand content has no record, so it cannot be restored once removed: the dry run says so
        self.assertIn("unrestorable_removal", [w.code for w in p.warnings])

        self.assertApplied(self.timed(apply, recipe, self.scene))
        fig = self.figure(label)
        self.assertEqual(fig.name, fig0.name, "the taken-over figure was replaced")
        self.assertEqual(fig.label, label)
        self.assertTrue(fig.record is not None and fig.record.adopted_from_scene)
        hair = self.hair(fig)
        self.assertTrue(hair)
        self.assertFalse({it.name for it in hair} & set(hand_hair), "the hand hair is still there")
        self.assertTrue(all(it.record is not None and it.record.recipe_id == recipe["id"]
                            for it in hair), "hair not owned by the recipe is on Abby")
        # the replace selector is one-shot: inert on the next apply
        self.assertEqual(plan(recipe, self.scene).steps, ())


    def test_g8_hair_on_taken_over_figure_rejected(self):
        """A Genesis 8 hair for a live (hand-built) Genesis 9 figure fails the plan
        from the live figure's base; nothing loads."""
        hair_a, g8_hair = _env("DAZ_LIVE_HAIR_A"), _env("DAZ_LIVE_G8_HAIR")
        label = self.label("takeover-g8")
        self.hand_built(label, hair_a)
        recipe = {"recipe_version": 2, "id": "live-af-takeover-g8", "actors": {"abby": {
            "node": label, "wearing": [{"add": g8_hair, "key": "g8hair"}]}}}
        before = _roots()
        for fn in (plan, apply):
            with self.assertRaises(RecipeValidationError) as cm:
                self.timed(fn, recipe, self.scene)
            self.assertIn(("actors.abby.wearing.g8hair", "incompatible_asset"),
                          [(e.path, e.code) for e in cm.exception.report.errors])
        self.check_environment()
        self.assertEqual(_roots(), before, "the scene changed")
        self.assertIsNone(self.figure(label).record, "the figure was taken over")

    def test_release_keeps_taken_over_figure(self):
        """Dropping a taken-over actor releases it: the figure is never deleted."""
        label = self.label("release")
        self.hand_built(label, _env("DAZ_LIVE_HAIR_A"))
        rid = "live-af-release"
        self.assertApplied(self.timed(apply, {"recipe_version": 2, "id": rid, "actors": {
            "abby": {"node": label}}}, self.scene))
        fig0 = self.figure(label)
        self.assertTrue(fig0.record is not None and fig0.record.adopted_from_scene)
        released = self.timed(apply, {"recipe_version": 2, "id": rid}, self.scene)
        self.assertApplied(released)
        self.assertNotIn("delete", [s.op for s in released.steps])
        self.assertIn("release", [s.op for s in released.steps])
        fig = self.figure(label)
        self.assertEqual(fig.name, fig0.name)
        self.assertIsNone(fig.record)

    def test_g8_hair_rejected_scene_unchanged(self):
        """An incompatible hair fails validate/plan/apply before anything loads."""
        label = self.label("g8")
        recipe = {"recipe_version": 2, "id": "live-af-g8", "actors": {"abby": {
            "node": label, "asset": _env("DAZ_LIVE_G9F"),
            "wearing": [{"add": _env("DAZ_LIVE_G8_HAIR"), "key": "hair"}]}}}
        before = _roots()
        report = self.timed(validate, recipe, self.scene)
        self.assertFalse(report.ok)
        self.assertEqual([(e.path, e.code) for e in report.errors],
                         [("actors.abby.wearing.hair", "incompatible_asset")])
        for fn in (plan, apply):
            with self.assertRaises(RecipeValidationError) as cm:
                self.timed(fn, recipe, self.scene)
            self.assertEqual([(e.path, e.code) for e in cm.exception.report.errors],
                             [("actors.abby.wearing.hair", "incompatible_asset")])
        self.check_environment()
        self.assertEqual(_roots(), before, "the scene changed")
        self.assertEqual(self.figures(label), [])

    def test_ambiguous_find_changes_nothing(self):
        """A ``find`` matching several hairs lists them and changes nothing."""
        phrase = os.environ.get("DAZ_LIVE_AMBIGUOUS_FIND") or "ponytail"
        label = self.label("ambiguous")
        recipe = {"recipe_version": 2, "id": "live-af-ambiguous", "actors": {"abby": {
            "node": label, "asset": _env("DAZ_LIVE_G9F"),
            "wearing": [{"add": {"find": phrase, "type": "hair"}, "key": "hair"}]}}}
        before = _roots()
        report = self.timed(validate, recipe, self.scene)
        errors = [e for e in report.errors if e.code == "ambiguous_asset"]
        self.assertEqual([e.path for e in errors], ["actors.abby.wearing.hair"], report.errors)
        self.assertGreater(len(errors[0].allowed or ()), 1, "the candidates are not listed")
        with self.assertRaises(RecipeValidationError) as cm:
            self.timed(apply, recipe, self.scene)
        self.assertIn(("actors.abby.wearing.hair", "ambiguous_asset"),
                      [(e.path, e.code) for e in cm.exception.report.errors])
        self.check_environment()
        self.assertEqual(_roots(), before, "the scene changed")

    def test_fit_failure_keeps_hand_hair(self):
        """A failure in the fit phase removes the new hair and keeps the hand hair."""
        hair_a, hair_b, outfit = (_env("DAZ_LIVE_HAIR_A"), _env("DAZ_LIVE_HAIR_B"),
                                  _env("DAZ_LIVE_OUTFIT"))
        label = self.label("fitfail")
        hand_hair = self.hand_built(label, hair_a)
        items0 = sorted(it.name for it in self.figure(label).items)
        recipe = {"recipe_version": 2, "id": "live-af-fitfail", "actors": {"abby": {
            "node": label,
            "wearing": [{"replace": {"type": "hair"}, "key": "hair", "with": hair_b},
                        {"add": outfit, "key": "outfit"}]}}}

        real = DazSceneOps.fit
        calls = {"n": 0}

        def flaky(self_, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("injected failure on the second fit")
            return real(self_, *args, **kwargs)

        with mock.patch.object(DazSceneOps, "fit", flaky):
            result = self.timed(apply, recipe, self.scene)
        self.assertEqual(calls["n"], 2, "the second fit was never reached")
        self.assertFalse(result.applied)
        self.assertTrue(result.rolled_back)
        self.assertEqual(result.rollback_errors, ())

        fig = self.figure(label)
        self.assertEqual(sorted(it.name for it in fig.items), items0,
                         "Abby's fitted items differ from before the failed apply")
        self.assertEqual(sorted(it.name for it in self.hair(fig)), sorted(hand_hair))
        self.assertTrue(all(it.record is None for it in fig.items))
        self.assertIsNone(fig.record, "the take-over was not rolled back")
        self.assertEqual(read_live(_CLIENT, recipe["id"]).entities, {})

    def test_multi_node_hair_and_outfit_add_swap_remove(self):
        """One entry owns a multi-node group: add an outfit, swap it for a
        multi-node hair, remove it."""
        outfit, multi = _env("DAZ_LIVE_OUTFIT"), _env("DAZ_LIVE_HAIR_MULTI")
        label = self.label("multi")
        rid = "live-af-multi"

        def recipe(*wearing):
            actor = {"node": label, "asset": _env("DAZ_LIVE_G9F")}
            if wearing:
                actor["wearing"] = list(wearing)
            return {"recipe_version": 2, "id": rid, "actors": {"abby": actor}}

        def group(fig):
            entity = read_live(_CLIENT, rid).entities.get("actors.abby.wearing.look")
            if entity is None:
                return []
            names = list(entity.group_nodes) or [entity.node_name]
            self.assertTrue(set(names) <= {it.name for it in fig.items},
                            f"group nodes {names} are not all fitted to Abby")
            return names

        self.assertApplied(self.timed(apply, recipe({"add": outfit, "key": "look"}), self.scene))
        garments = group(self.figure(label))
        self.assertGreater(len(garments), 1, "the outfit loaded a single node")

        swapped = self.timed(apply, recipe({"add": multi, "key": "look"}), self.scene)
        self.assertApplied(swapped)
        fig = self.figure(label)
        hair = group(fig)
        self.assertGreater(len(hair), 1, "the multi-node hair loaded a single node")
        self.assertFalse(set(garments) & {it.name for it in fig.items},
                         "outfit garments survived the swap")

        removed = self.timed(apply, recipe(), self.scene)
        self.assertApplied(removed)
        fig = self.figure(label)
        self.assertFalse(set(hair) & {it.name for it in fig.items}, "hair nodes survived removal")
        self.assertNotIn("actors.abby.wearing.look", read_live(_CLIENT, rid).entities)

    def test_records_have_source(self):
        """Every recipe-owned node carries ``source`` provenance (spec §9)."""
        outfit = _env("DAZ_LIVE_OUTFIT")
        label = self.label("source")
        recipe = _abby_fixture("live-af-source", label)
        recipe["actors"]["abby"]["wearing"].append({"add": outfit, "key": "outfit"})
        self.assertApplied(self.timed(apply, recipe, self.scene))
        self.check_environment()

        live = read_live(_CLIENT, recipe["id"])
        actor = live.entities["actors.abby"].record
        # a path-only ref is recorded in its shorthand (string) form, as AssetRef.to_dict gives it
        self.assertEqual(actor.source["requested"], _env("DAZ_LIVE_G9F"))
        self.assertEqual(actor.source["finder"], "path")
        self.assertTrue(actor.source["path"])
        if _env("DAZ_LIVE_PRESET"):
            self.assertEqual(len(actor.source.get("presets") or ()), 1)

        # every node of every fitted group, read from the scene (not just primaries)
        fig = self.figure(label)
        by_path: dict[str, list] = {}
        for it in fig.items:
            if it.record is not None and it.record.recipe_id == recipe["id"]:
                by_path.setdefault(it.record.path, []).append(it)
        self.assertEqual(sorted(by_path), ["actors.abby.wearing.hair", "actors.abby.wearing.outfit"])
        for path, items in by_path.items():
            self.assertEqual(sum(1 for it in items if it.record.source["primary"]), 1, path)
            for it in items:
                src = it.record.source
                with self.subTest(node=it.name):
                    self.assertIn("requested", src)
                    self.assertTrue(src["path"])
                    self.assertEqual(src["finder"], "path")
                    self.assertEqual(src["fitted_to"], "abby")
                    self.assertEqual(src["group"], path)
                    self.assertTrue(it.record.asset_uri, "no asset_uri recorded")
        self.assertEqual(by_path["actors.abby.wearing.hair"][0].record.source["requested"],
                         {"path": _env("DAZ_LIVE_HAIR_A"), "type": "hair"})
        self.assertEqual(len(by_path["actors.abby.wearing.outfit"]),
                         len(live.entities["actors.abby.wearing.outfit"].group_nodes))


if __name__ == "__main__":
    unittest.main()
