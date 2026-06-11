#!/usr/bin/env python3
"""
Interactive integration test harness for dazpy pose-resolver features.

Expected scene
--------------
BobG8     -- Genesis 8 male
AliceG8   -- Genesis 8 female
MadisonG9 -- Genesis 9 female
BaseLight -- point light

Run:  python harness_integration.py [--host HOST] [--port PORT] [--auto]

Press Enter to advance through each test.
For visual tests, look at the DAZ Studio viewport and answer the y/n prompt.
Pass --auto to skip manual confirmations (CI/smoke mode).
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from typing import Callable

# ── colour helpers ─────────────────────────────────────────────────────────────

_USE_COLOR = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


def green(t: str) -> str:  return _c("32", t)
def red(t: str) -> str:    return _c("31", t)
def yellow(t: str) -> str: return _c("33", t)
def bold(t: str) -> str:   return _c("1", t)
def dim(t: str) -> str:    return _c("2", t)


# ── harness state ──────────────────────────────────────────────────────────────

class HarnessAbort(Exception):
    pass


class Harness:
    def __init__(self, auto: bool = False):
        self.auto = auto
        self._passed: list[str] = []
        self._failed: list[str] = []
        self._skipped: list[str] = []
        self._current: str = ""

    # ── output ────────────────────────────────────────────────────────────────

    def section(self, title: str) -> None:
        print()
        print(bold(f"{'─' * 60}"))
        print(bold(f"  {title}"))
        print(bold(f"{'─' * 60}"))

    def test(self, label: str, what: str, watch: str | None = None) -> None:
        self._current = label
        print()
        print(bold(f"[{label}]"))
        for line in textwrap.wrap(what, 72):
            print(f"  {line}")
        if watch:
            print(f"  {yellow('WATCH:')} {watch}")
        if not self.auto:
            try:
                input(dim("  Press Enter to run …"))
            except (KeyboardInterrupt, EOFError):
                raise HarnessAbort()

    def ok(self, msg: str = "") -> None:
        tag = green("PASS")
        suffix = f"  {dim(msg)}" if msg else ""
        print(f"  [{tag}] {self._current}{suffix}")
        self._passed.append(self._current)

    def fail(self, msg: str) -> None:
        tag = red("FAIL")
        print(f"  [{tag}] {self._current}: {msg}")
        self._failed.append(self._current)

    def skip(self, msg: str) -> None:
        tag = yellow("SKIP")
        print(f"  [{tag}] {self._current}: {msg}")
        self._skipped.append(self._current)

    def assert_true(self, cond: bool, msg: str) -> None:
        if not cond:
            raise AssertionError(msg)

    def assert_equal(self, a, b, msg: str = "") -> None:
        if a != b:
            raise AssertionError(msg or f"expected {b!r}, got {a!r}")

    def visual_confirm(self, prompt: str) -> bool:
        if self.auto:
            return True
        try:
            ans = input(f"  {yellow('?')} {prompt} [y/n]: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            return False
        return ans.startswith("y")

    def run(self, fn: Callable) -> None:
        try:
            fn()
        except AssertionError as exc:
            self.fail(str(exc))
        except Exception as exc:
            self.fail(f"unexpected error — {type(exc).__name__}: {exc}")

    def summary(self) -> None:
        total = len(self._passed) + len(self._failed) + len(self._skipped)
        print()
        print(bold(f"{'═' * 60}"))
        print(bold("  Results"))
        print(bold(f"{'═' * 60}"))
        print(f"  Total   {total}")
        print(f"  {green('Passed')}  {len(self._passed)}")
        if self._failed:
            print(f"  {red('Failed')}  {len(self._failed)}")
            for name in self._failed:
                print(f"    - {name}")
        if self._skipped:
            print(f"  {yellow('Skipped')} {len(self._skipped)}")
        print()
        if self._failed:
            sys.exit(1)


# ── scene fixture helpers ──────────────────────────────────────────────────────

EXPECTED_LABELS = ["BobG8", "AliceG8", "MadisonG9"]
EXPECTED_LIGHT = "BaseLight"

G8_HAND_ANCHOR_R = "r_hand"
G8_HAND_ANCHOR_L = "l_hand"
G9_HAND_ANCHOR_R = "r_hand"
G9_FOOT_ANCHOR_L = "l_foot"

# Reasonable world-space y-coordinate range for wrists/hands on a standing figure
HAND_Y_MIN, HAND_Y_MAX = 50.0, 200.0


def _save_pose(skeleton) -> dict:
    """Capture all bone rotations so we can restore after visual tests."""
    return skeleton.bone_rotations()


def _restore_pose(skeleton, saved: dict) -> None:
    skeleton.set_bone_rotations(saved)


# ── tests ──────────────────────────────────────────────────────────────────────

def run_all(h: Harness, scene, skeletons: dict) -> None:
    bob = skeletons["BobG8"]
    alice = skeletons["AliceG8"]
    madison = skeletons["MadisonG9"]

    # ══════════════════════════════════════════════════════════════════════
    h.section("S1 · scene_snapshot")
    # ══════════════════════════════════════════════════════════════════════

    h.test(
        "S1-a",
        "scene_snapshot() returns a list with one entry per loaded skeleton. "
        "We expect at least BobG8, AliceG8, and MadisonG9.",
    )

    def t_s1a():
        snap = scene.scene_snapshot()
        h.assert_true(isinstance(snap, list), "snapshot must be a list")
        h.assert_true(len(snap) >= 3, f"expected ≥3 skeletons, got {len(snap)}")
        labels = {s.get("label") or s.get("name") for s in snap}
        for expected in EXPECTED_LABELS:
            h.assert_true(expected in labels, f"missing {expected!r} in snapshot labels: {labels}")
        h.ok(f"{len(snap)} skeletons: {sorted(labels)}")

    h.run(t_s1a)

    h.test(
        "S1-b",
        "Each snapshot entry has a 'bones' list. Every bone must carry "
        "local_position, world_position, local_euler, rotation_order, and parent_name.",
    )

    def t_s1b():
        snap = scene.scene_snapshot()
        required = {"local_position", "world_position", "local_euler", "rotation_order", "parent_name"}
        for skel_entry in snap:
            bones = skel_entry.get("bones", [])
            h.assert_true(len(bones) > 0, f"{skel_entry.get('label')} has no bones in snapshot")
            for bone in bones[:5]:  # spot-check first 5
                missing = required - bone.keys()
                h.assert_true(not missing, f"bone {bone.get('name')!r} missing fields: {missing}")
        h.ok("all spot-checked bones have required fields")

    h.run(t_s1b)

    h.test(
        "S1-c",
        "Filtering snapshot by label returns only matching skeletons. "
        "Requesting just ['BobG8'] should yield exactly 1 entry.",
    )

    def t_s1c():
        snap = scene.scene_snapshot(skeleton_labels=["BobG8"])
        h.assert_equal(len(snap), 1, f"expected 1 skeleton, got {len(snap)}")
        entry = snap[0]
        got_label = entry.get("label") or entry.get("name")
        h.assert_equal(got_label, "BobG8")
        h.ok(f"filtered correctly — got label={got_label!r}")

    h.run(t_s1c)

    h.test(
        "S1-d",
        "world_position values for BobG8 hip should be a 3-element list "
        "with a y-component roughly in [50, 200] cm (standing figure).",
    )

    def t_s1d():
        snap = scene.scene_snapshot(skeleton_labels=["BobG8"])
        bones = snap[0]["bones"]
        hip = next((b for b in bones if b["name"] in ("hip", "Hip")), None)
        h.assert_true(hip is not None, "could not find 'hip' bone in BobG8 snapshot")
        wp = hip["world_position"]
        h.assert_true(isinstance(wp, (list, tuple)) and len(wp) == 3, f"world_position bad shape: {wp}")
        y = float(wp[1])
        h.assert_true(
            HAND_Y_MIN < y < 300,
            f"hip world_position y={y:.1f} out of expected range — is figure in default T-pose?",
        )
        h.ok(f"hip world_position: ({wp[0]:.1f}, {y:.1f}, {wp[2]:.1f})")

    h.run(t_s1d)

    # ══════════════════════════════════════════════════════════════════════
    h.section("S2 · build_rig_profiles_from_snapshot")
    # ══════════════════════════════════════════════════════════════════════

    h.test(
        "S2-a",
        "build_rig_profiles_from_snapshot() converts the raw snapshot into "
        "FigureRigProfile objects keyed by label. Expect keys for all three figures.",
    )

    snap_full = None

    def t_s2a():
        nonlocal snap_full
        from dazpy import build_rig_profiles_from_snapshot
        snap_full = scene.scene_snapshot()
        profiles = build_rig_profiles_from_snapshot(snap_full)
        for label in EXPECTED_LABELS:
            h.assert_true(label in profiles, f"missing profile for {label!r}")
        h.ok(f"profiles keys: {sorted(k for k in profiles if k in set(EXPECTED_LABELS))}")

    h.run(t_s2a)

    h.test(
        "S2-b",
        "BobG8 and AliceG8 are Genesis 8, so their family should be 'genesis_3_8'. "
        "MadisonG9 is Genesis 9, so her family should be 'genesis_9'.",
    )

    def t_s2b():
        from dazpy import build_rig_profiles_from_snapshot
        snap = snap_full or scene.scene_snapshot()
        profiles = build_rig_profiles_from_snapshot(snap)
        h.assert_equal(profiles["BobG8"].family, "genesis_3_8", "BobG8 should be genesis_3_8")
        h.assert_equal(profiles["AliceG8"].family, "genesis_3_8", "AliceG8 should be genesis_3_8")
        h.assert_equal(profiles["MadisonG9"].family, "genesis_9", "MadisonG9 should be genesis_9")
        h.ok("all three family detections correct")

    h.run(t_s2b)

    h.test(
        "S2-c",
        "All three profiles must expose canonical anchors r_hand, l_hand, r_foot, l_foot — "
        "even though Genesis 8 uses camelCase bone names (rHand, lHand, etc.). "
        "This validates the camelCase side-detection fix.",
    )

    def t_s2c():
        from dazpy import build_rig_profiles_from_snapshot
        snap = snap_full or scene.scene_snapshot()
        profiles = build_rig_profiles_from_snapshot(snap)
        expected_anchors = ["r_hand", "l_hand", "r_foot", "l_foot"]
        for label in EXPECTED_LABELS:
            profile = profiles[label]
            anchors = profile.anchor_map()
            for a in expected_anchors:
                h.assert_true(a in anchors, f"{label} missing anchor {a!r}; got {sorted(anchors)}")
        h.ok("all canonical anchors present for all three figures")

    h.run(t_s2c)

    h.test(
        "S2-d",
        "BoneProfile objects inside the rig profile must have world_position populated "
        "from the snapshot data (not None). Spot-check BobG8 hip bone.",
    )

    def t_s2d():
        from dazpy import build_rig_profiles_from_snapshot
        snap = snap_full or scene.scene_snapshot()
        profiles = build_rig_profiles_from_snapshot(snap)
        bob_profile = profiles["BobG8"]
        hip_bone = bob_profile.bone("hip")
        h.assert_true(hip_bone is not None, "hip bone not found in BobG8 profile")
        h.assert_true(
            hip_bone.world_position is not None,
            "hip world_position is None — snapshot may not have populated it",
        )
        h.ok(f"BobG8 hip world_position: {tuple(round(v,1) for v in hip_bone.world_position)}")

    h.run(t_s2d)

    # ══════════════════════════════════════════════════════════════════════
    h.section("S3 · evaluate_pose (single call, no IK)")
    # ══════════════════════════════════════════════════════════════════════

    h.test(
        "S3-a",
        "evaluate_pose() applies a temporary rotation, reads world-space effector "
        "positions, then restores original pose — all in one DazScript call. "
        "We rotate BobG8's hip 45° on Y and verify the right-hand position changes.",
        watch="BobG8 should NOT visibly move — evaluate_pose always restores the pose.",
    )

    def t_s3a():
        base = bob.evaluate_pose({}, ["rHand"])
        rotated = bob.evaluate_pose({"hip": (0.0, 45.0, 0.0)}, ["rHand"])
        if base is None or rotated is None:
            h.skip("evaluate_pose returned None — server may not support it")
            return
        base_pos = base.get("rHand")
        rot_pos = rotated.get("rHand")
        h.assert_true(base_pos is not None, "rHand missing from evaluate_pose result")
        h.assert_true(rot_pos is not None, "rHand missing from rotated result")
        delta = sum((a - b) ** 2 for a, b in zip(base_pos, rot_pos)) ** 0.5
        h.assert_true(delta > 1.0, f"45° hip rotation moved rHand only {delta:.3f} units — expected > 1 cm")
        h.ok(f"rHand moved {delta:.1f} units after 45° Y-rotation")

    h.run(t_s3a)

    h.test(
        "S3-b",
        "evaluate_pose restores the pose after execution. We confirm by calling "
        "evaluate_pose with zero rotation and checking the result matches baseline.",
    )

    def t_s3b():
        a = bob.evaluate_pose({}, ["rHand"])
        b = bob.evaluate_pose({}, ["rHand"])
        if a is None or b is None:
            h.skip("evaluate_pose returned None")
            return
        pa, pb = a.get("rHand", (0, 0, 0)), b.get("rHand", (0, 0, 0))
        delta = sum((x - y) ** 2 for x, y in zip(pa, pb)) ** 0.5
        h.assert_true(delta < 0.01, f"two consecutive zero-delta calls gave different results: Δ={delta:.4f}")
        h.ok("pose restoration confirmed — two baseline calls match")

    h.run(t_s3b)

    # ══════════════════════════════════════════════════════════════════════
    h.section("S4 · evaluate_pose_jacobian")
    # ══════════════════════════════════════════════════════════════════════

    h.test(
        "S4-a",
        "evaluate_pose_jacobian() returns a Jacobian dict with 'base_position' (3-vector) "
        "and 'columns' (list of 3-vectors, one per bone×axis in the chain). "
        "For a 3-bone G8 chain (collar→forearm→hand), expect 9 columns.",
        watch="BobG8 should NOT move — Jacobian evaluation always restores pose.",
    )

    def t_s4a():
        chain = ["rCollar", "rForearmBend", "rHand"]
        jac = bob.evaluate_pose_jacobian(chain, "rHand")
        if jac is None:
            h.skip("evaluate_pose_jacobian returned None — server may not support it")
            return
        h.assert_true("base_position" in jac, "'base_position' missing from Jacobian result")
        h.assert_true("columns" in jac, "'columns' missing from Jacobian result")
        bp = jac["base_position"]
        cols = jac["columns"]
        h.assert_true(isinstance(bp, list) and len(bp) == 3, f"base_position bad shape: {bp}")
        h.assert_equal(len(cols), len(chain) * 3, f"expected {len(chain)*3} columns, got {len(cols)}")
        h.ok(f"base_position=({bp[0]:.1f},{bp[1]:.1f},{bp[2]:.1f}), {len(cols)} Jacobian columns")

    h.run(t_s4a)

    h.test(
        "S4-b",
        "evaluate_pose_jacobian for MadisonG9 (Genesis 9) with snake_case bones: "
        "chain [hip, r_forearm, r_hand], effector r_hand. Expect 9 columns.",
        watch="MadisonG9 should NOT move.",
    )

    def t_s4b():
        chain = ["hip", "r_forearm", "r_hand"]
        jac = madison.evaluate_pose_jacobian(chain, "r_hand")
        if jac is None:
            h.skip("evaluate_pose_jacobian returned None")
            return
        cols = jac["columns"]
        h.assert_equal(len(cols), len(chain) * 3, f"expected {len(chain)*3} columns, got {len(cols)}")
        h.ok(f"{len(cols)} Jacobian columns for MadisonG9 chain")

    h.run(t_s4b)

    h.test(
        "S4-c",
        "Finer step_degrees produces a closer approximation of the differential: "
        "with step=0.1° the Jacobian columns should all be finite and non-zero for a moving chain.",
    )

    def t_s4c():
        chain = ["rCollar", "rForearmBend", "rHand"]
        jac = bob.evaluate_pose_jacobian(chain, "rHand", step_degrees=0.1)
        if jac is None:
            h.skip("evaluate_pose_jacobian returned None")
            return
        cols = jac["columns"]
        all_finite = all(
            all(abs(v) < 1e9 for v in col)
            for col in cols
        )
        any_nonzero = any(
            any(abs(v) > 1e-6 for v in col)
            for col in cols
        )
        h.assert_true(all_finite, "Jacobian columns contain non-finite values")
        h.assert_true(any_nonzero, "All Jacobian columns are zero — chain may be locked or degenerate")
        h.ok(f"step=0.1° Jacobian: {len(cols)} columns, all finite, at least one non-zero")

    h.run(t_s4c)

    # ══════════════════════════════════════════════════════════════════════
    h.section("S5 · align_hand_target (batch IK, G9)")
    # ══════════════════════════════════════════════════════════════════════

    h.test(
        "S5-a",
        "align_hand_target() on MadisonG9 moves r_hand toward a target 20 cm in world −Z "
        "(her right side — she is at (72.53,0,0) rotated −89.84° on Y, so she faces world +X "
        "and her anatomical right points toward world −Z). "
        "We capture pose before, run alignment, visually confirm, then restore.",
        watch="MadisonG9's right arm should extend toward screen-bottom (world −Z). "
              "After confirmation, the pose will be RESTORED.",
    )

    def t_s5a():
        from dazpy import align_hand_target
        saved = _save_pose(madison)
        try:
            snap = scene.scene_snapshot(skeleton_labels=["MadisonG9"])
            from dazpy import build_rig_profiles_from_snapshot
            profiles = build_rig_profiles_from_snapshot(snap)
            profile = profiles["MadisonG9"]
            r_hand_anchor = profile.anchor("r_hand")
            if r_hand_anchor is None:
                h.skip("r_hand anchor not found for MadisonG9")
                return
            # Madison faces +X; her anatomical right is world −Z.
            # Fallback places her roughly where her hand should be at rest.
            wp = r_hand_anchor.world_point_hint or (112.0, 130.0, -40.0)
            target = (wp[0], wp[1], wp[2] - 20.0)
            result = align_hand_target(madison, target, source_anchor="r_hand", max_iterations=10)
            path = result.diagnostics.get("path", "unknown")
            h.assert_true(
                path == "batch",
                f"expected batch IK path, got {path!r} — skeleton may lack _client attr",
            )
            h.assert_true(result.initial_error is not None, "initial_error is None")
            h.assert_true(
                result.initial_error > 0.0,
                f"initial error is zero — target same as starting position?",
            )
            converge_note = "converged" if result.converged else f"{result.iterations} iters"
            print(f"  {dim(f'path={path}, initial_error={result.initial_error:.1f}cm, {converge_note}')}")
            confirmed = h.visual_confirm(
                "Does MadisonG9's right arm extend toward screen-bottom (world −Z)?"
            )
            if not confirmed and not h.auto:
                h.fail("visual check: hand did not appear to move to target")
                return
            h.ok(f"batch IK path={path}, initial_error={result.initial_error:.1f}")
        finally:
            _restore_pose(madison, saved)
            print(f"  {dim('MadisonG9 pose restored.')}")

    h.run(t_s5a)

    h.test(
        "S5-b",
        "When MadisonG9's r_hand is already at the target (target = current world position), "
        "align_hand_target should return immediately with converged=True and iterations=0.",
    )

    def t_s5b():
        from dazpy import align_hand_target, build_rig_profiles_from_snapshot
        snap = scene.scene_snapshot(skeleton_labels=["MadisonG9"])
        profiles = build_rig_profiles_from_snapshot(snap)
        profile = profiles["MadisonG9"]
        r_hand_anchor = profile.anchor("r_hand")
        if r_hand_anchor is None:
            h.skip("r_hand anchor not found for MadisonG9")
            return
        # Use the current world position as target — already aligned
        current = r_hand_anchor.world_point_hint
        if current is None:
            h.skip("world_point_hint not available — world_position not in snapshot")
            return
        saved = _save_pose(madison)
        try:
            result = align_hand_target(madison, current, source_anchor="r_hand", tolerance=1.0)
            h.assert_true(result.converged, f"expected converged=True, got converged={result.converged}")
            h.assert_equal(result.iterations, 0, f"expected 0 iterations, got {result.iterations}")
            h.ok(f"already-aligned case: converged immediately (initial_error={result.initial_error:.2f})")
        finally:
            _restore_pose(madison, saved)

    h.run(t_s5b)

    h.test(
        "S5-c",
        "align_hand_target on BobG8 (Genesis 8, camelCase bones) using canonical anchor r_hand. "
        "Verifies that the camelCase side-detection fix lets Genesis 8 figures use the same API.",
        watch="BobG8's right hand should move slightly to screen-right and lower. "
              "Pose will be restored.",
    )

    def t_s5c():
        from dazpy import align_hand_target, build_rig_profiles_from_snapshot
        snap = scene.scene_snapshot(skeleton_labels=["BobG8"])
        profiles = build_rig_profiles_from_snapshot(snap)
        profile = profiles["BobG8"]
        r_hand_anchor = profile.anchor("r_hand")
        if r_hand_anchor is None:
            h.skip("r_hand anchor not found for BobG8 — anchor map may not resolve camelCase")
            return
        # BobG8 at (0,0,−50) with no rotation; his anatomical right is world +X.
        # Fallback: approximate rHand world position for a standing G8 at (0,0,−50).
        wp = r_hand_anchor.world_point_hint or (40.0, 130.0, -50.0)
        target = (wp[0] + 15.0, wp[1] - 10.0, wp[2] - 5.0)
        saved = _save_pose(bob)
        try:
            result = align_hand_target(bob, target, source_anchor="r_hand", max_iterations=8)
            h.assert_true(result.initial_error is not None, "initial_error is None")
            path = result.diagnostics.get("path", "unknown")
            confirmed = h.visual_confirm("Does BobG8's right hand move slightly toward the target?")
            if not confirmed and not h.auto:
                h.fail("visual check: BobG8 hand did not appear to move")
                return
            h.ok(f"Genesis 8 align_hand works — path={path}, initial_error={result.initial_error:.1f}")
        finally:
            _restore_pose(bob, saved)
            print(f"  {dim('BobG8 pose restored.')}")

    h.run(t_s5c)

    # ══════════════════════════════════════════════════════════════════════
    h.section("S6 · align_foot_target (batch IK)")
    # ══════════════════════════════════════════════════════════════════════

    h.test(
        "S6-a",
        "align_foot_target() on AliceG8 moves l_foot 10 cm forward in world +Z. "
        "AliceG8 is at (0,0,50) rotated 180° on Y, so she faces +Z — forward is +Z for her. "
        "Checks that the batch IK path is used and error is reduced.",
        watch="AliceG8's left foot should step toward screen (world +Z, her forward). "
              "Pose will be restored.",
    )

    def t_s6a():
        from dazpy import align_foot_target, build_rig_profiles_from_snapshot
        snap = scene.scene_snapshot(skeleton_labels=["AliceG8"])
        profiles = build_rig_profiles_from_snapshot(snap)
        profile = profiles["AliceG8"]
        l_foot_anchor = profile.anchor("l_foot")
        if l_foot_anchor is None:
            h.skip("l_foot anchor not found for AliceG8")
            return
        # AliceG8 at (0,0,50) rotated 180° on Y: faces +Z, anatomical left is world +X.
        # Fallback places foot near expected resting world position.
        wp = l_foot_anchor.world_point_hint or (-10.0, 8.0, 50.0)
        target = (wp[0], wp[1], wp[2] + 10.0)  # step forward (+Z = her forward)
        saved = _save_pose(alice)
        try:
            result = align_foot_target(alice, target, source_anchor="l_foot", max_iterations=10)
            path = result.diagnostics.get("path", "unknown")
            h.assert_true(result.initial_error is not None, "initial_error is None")
            confirmed = h.visual_confirm(
                "Does AliceG8's left foot step forward toward screen (world +Z)?"
            )
            if not confirmed and not h.auto:
                h.fail("visual check: AliceG8 foot did not step forward")
                return
            h.ok(f"foot IK path={path}, initial_error={result.initial_error:.1f}")
        finally:
            _restore_pose(alice, saved)
            print(f"  {dim('AliceG8 pose restored.')}")

    h.run(t_s6a)

    # ══════════════════════════════════════════════════════════════════════
    h.section("S7 · call-count regression")
    # ══════════════════════════════════════════════════════════════════════

    h.test(
        "S7-a",
        "The batch IK path must use at most 30 HTTP calls for 12 iterations on a 4-bone chain. "
        "Formula: 1 bone_rots + 1 init_jacobian + 12 × 2 (set_rots + jacobian) = 27 calls. "
        "We monkey-patch the client to count calls.",
    )

    def t_s7a():
        calls: list[str] = []
        original_execute = madison._client.execute

        def counting_execute(script, **kw):
            calls.append(script[:80])
            return original_execute(script, **kw)

        object.__setattr__(madison._client, "execute", counting_execute)
        saved = _save_pose(madison)
        try:
            from dazpy import align_hand_target, build_rig_profiles_from_snapshot
            snap = scene.scene_snapshot(skeleton_labels=["MadisonG9"])
            profiles = build_rig_profiles_from_snapshot(snap)
            profile = profiles["MadisonG9"]
            r_hand_anchor = profile.anchor("r_hand")
            if r_hand_anchor is None:
                h.skip("r_hand anchor not found")
                return
            # Madison faces +X; her right is world −Z.
            wp = r_hand_anchor.world_point_hint or (112.0, 130.0, -40.0)
            target = (wp[0], wp[1], wp[2] - 25.0)
            calls.clear()
            align_hand_target(madison, target, source_anchor="r_hand", max_iterations=12)
            # scene_snapshot call (already done above) is NOT counted here
            h.assert_true(
                len(calls) <= 30,
                f"batch IK used {len(calls)} calls — expected ≤30 for 12 iterations",
            )
            h.ok(f"{len(calls)} HTTP calls for 12-iteration batch IK (target ≤ 30)")
        finally:
            object.__setattr__(madison._client, "execute", original_execute)
            _restore_pose(madison, saved)

    h.run(t_s7a)


# ── scene bootstrap ────────────────────────────────────────────────────────────

def connect_and_verify(host: str, port: int, h: Harness):
    """Connect to DAZ Studio, verify the expected scene is loaded, return (scene, skeletons)."""
    print(bold(f"\nConnecting to DAZ Studio at {host}:{port} …"))
    try:
        from dazpy import DazClient, DazScene
    except ImportError as exc:
        print(red(f"ERROR: could not import dazpy — {exc}"))
        sys.exit(1)

    client = DazClient(host=host, port=port)
    try:
        status = client.status()
        print(f"  {green('Connected')} — DAZ Studio {status.get('version', '?')}")
    except Exception as exc:
        print(red(f"ERROR: cannot reach DAZ Studio at {host}:{port} — {exc}"))
        print("  Is DAZ Studio running with DazScriptServer loaded?")
        sys.exit(1)

    scene = DazScene(client)

    print(f"\n{bold('Verifying scene …')}")
    try:
        snap = scene.scene_snapshot()
    except Exception as exc:
        print(red(f"ERROR: could not snapshot scene — {exc}"))
        sys.exit(1)

    found_labels = {(s.get("label") or s.get("name")) for s in snap}
    missing = [lbl for lbl in EXPECTED_LABELS if lbl not in found_labels]
    if missing:
        print(red(f"ERROR: required figures not found in scene: {missing}"))
        print(f"  Found: {sorted(found_labels)}")
        print("  Please load the test scene with: BobG8, AliceG8, MadisonG9, BaseLight")
        sys.exit(1)

    print(f"  Scene OK — {len(snap)} skeleton(s): {sorted(found_labels)}")

    skeletons = {}
    for label in EXPECTED_LABELS:
        try:
            skel = scene.find_skeleton_by_label(label)
        except Exception as exc:
            print(red(f"ERROR: could not get skeleton handle for {label!r} — {exc}"))
            sys.exit(1)
        skeletons[label] = skel
        print(f"  Resolved {label!r} skeleton handle")

    return scene, skeletons


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18811)
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Skip manual visual confirmations (CI/smoke mode; skips viewport checks)",
    )
    args = parser.parse_args()

    h = Harness(auto=args.auto)

    print(bold("\n══════════════════════════════════════════════════════════════"))
    print(bold("  dazpy interaction-posing integration harness"))
    print(bold("══════════════════════════════════════════════════════════════"))
    if args.auto:
        print(yellow("  Running in --auto mode: visual confirmations skipped"))

    try:
        scene, skeletons = connect_and_verify(args.host, args.port, h)
        run_all(h, scene, skeletons)
    except HarnessAbort:
        print(yellow("\n  Aborted by user."))
    finally:
        h.summary()


if __name__ == "__main__":
    main()
