#!/usr/bin/env python3
"""
IK test: move a specified bone on one figure toward a named target node.

Usage examples
--------------
# Move MadisonG9's right hand toward a prop called "HandTarget"
python test_ik_bone_to_target.py --source MadisonG9 --bone r_hand --target HandTarget

# Move BobG8's left foot toward AliceG8 (uses her world-space origin)
python test_ik_bone_to_target.py --source BobG8 --bone lFoot --target AliceG8 --restore

# Dry-run: print what would happen without actually moving anything
python test_ik_bone_to_target.py --source MadisonG9 --bone r_hand --target HandTarget --dry-run

Options
-------
--source         Label of the figure whose bone should move  (required)
--bone           Name of the effector bone to move           (required)
--target         Label of the target scene node              (required)
--host           DazScriptServer host    (default: 127.0.0.1)
--port           DazScriptServer port    (default: 18811)
--max-iter       IK max iterations       (default: 20)
--step           Step size in degrees    (default: 1.0)
--damping        DLS damping factor      (default: 0.25)
--tolerance      Convergence distance    (default: 0.15)
--restore        Restore pose after test
--dry-run        Print plan but do not execute IK
"""

from __future__ import annotations

import argparse
import sys


# ── colour helpers ──────────────────────────────────────────────────────────────

_USE_COLOR = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


def green(t: str) -> str:  return _c("32", t)
def red(t: str) -> str:    return _c("31", t)
def yellow(t: str) -> str: return _c("33", t)
def bold(t: str) -> str:   return _c("1",  t)
def dim(t: str) -> str:    return _c("2",  t)


# ── helpers ─────────────────────────────────────────────────────────────────────

def _fmt_vec(v: object) -> str:
    if isinstance(v, dict):
        return f"({v.get('x', '?'):.2f}, {v.get('y', '?'):.2f}, {v.get('z', '?'):.2f})"
    if isinstance(v, (list, tuple)) and len(v) == 3:
        return f"({v[0]:.2f}, {v[1]:.2f}, {v[2]:.2f})"
    return repr(v)


def _node_world_pos(node) -> tuple[float, float, float] | None:
    """Return world-space position of any DazNode as a plain tuple."""
    pos = node.position
    if pos is None:
        return None
    if isinstance(pos, dict):
        return (float(pos["x"]), float(pos["y"]), float(pos["z"]))
    if isinstance(pos, (list, tuple)) and len(pos) == 3:
        return (float(pos[0]), float(pos[1]), float(pos[2]))
    return None


# ── main ─────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Move a figure bone toward a named target node via IK.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--source",    required=True, metavar="FIGURE_LABEL",
                        help="Label of the source figure (e.g. 'MadisonG9')")
    parser.add_argument("--bone",      required=True, metavar="BONE_NAME",
                        help="Effector bone name to move (e.g. 'r_hand', 'rHand')")
    parser.add_argument("--target",    required=True, metavar="NODE_LABEL",
                        help="Label of the target scene node")
    parser.add_argument("--host",      default="127.0.0.1")
    parser.add_argument("--port",      type=int, default=18811)
    parser.add_argument("--max-iter",  type=int,   default=20,   dest="max_iter",
                        help="IK max iterations (default: 20)")
    parser.add_argument("--step",      type=float, default=1.0,
                        help="Step size in degrees per IK iteration (default: 1.0)")
    parser.add_argument("--damping",   type=float, default=0.25,
                        help="DLS damping factor (default: 0.25)")
    parser.add_argument("--tolerance", type=float, default=0.15,
                        help="Convergence distance in scene units (default: 0.15)")
    parser.add_argument("--restore",   action="store_true",
                        help="Restore the figure's pose after the test")
    parser.add_argument("--dry-run",   action="store_true", dest="dry_run",
                        help="Print the plan but do not execute IK")
    args = parser.parse_args()

    print(bold("\n══ IK bone-to-target test ══"))
    print(f"  Source figure : {args.source}")
    print(f"  Effector bone : {args.bone}")
    print(f"  Target node   : {args.target}")
    print(f"  IK params     : max_iter={args.max_iter}, step={args.step}°, "
          f"damping={args.damping}, tolerance={args.tolerance}")
    if args.dry_run:
        print(yellow("  [dry-run — IK will NOT be applied]"))
    if args.restore:
        print(dim("  Pose will be restored after test."))
    print()

    # ── connect ──────────────────────────────────────────────────────────────────

    try:
        from dazpy import DazClient, DazScene
    except ImportError as exc:
        print(red(f"ERROR: cannot import dazpy — {exc}"))
        sys.exit(1)

    client = DazClient(host=args.host, port=args.port)

    try:
        status = client.status()
        print(f"  {green('Connected')} — DAZ Studio {status.get('version', '?')}")
    except Exception as exc:
        print(red(f"ERROR: cannot reach DAZ Studio at {args.host}:{args.port} — {exc}"))
        sys.exit(1)

    scene = DazScene(client)

    # ── resolve target node ───────────────────────────────────────────────────────

    print(f"\nResolving target node {args.target!r} …")
    try:
        target_node = scene.find_node_by_label(args.target)
        target_pos = _node_world_pos(target_node)
        if target_pos is None:
            # Fallback: try to get position as a skeleton
            try:
                target_skel = scene.find_skeleton_by_label(args.target)
                target_pos = _node_world_pos(target_skel)
            except Exception:
                pass
        if target_pos is None:
            print(red(f"ERROR: could not read world position from target node {args.target!r}"))
            sys.exit(1)
        print(f"  {green('OK')} — target world position: {_fmt_vec(target_pos)}")
    except Exception as exc:
        print(red(f"ERROR: target node {args.target!r} not found — {exc}"))
        print("  Tip: use the exact label shown in the DAZ Studio Scene panel.")
        sys.exit(1)

    # ── resolve source skeleton ───────────────────────────────────────────────────

    print(f"\nResolving source figure {args.source!r} …")
    try:
        skeleton = scene.find_skeleton_by_label(args.source)
        print(f"  {green('OK')} — skeleton handle acquired")
    except Exception as exc:
        print(red(f"ERROR: source figure {args.source!r} not found — {exc}"))
        sys.exit(1)

    # ── build rig profile ─────────────────────────────────────────────────────────

    print("\nBuilding rig profile from scene snapshot …")
    try:
        snap = scene.scene_snapshot(skeleton_labels=[args.source])
        from dazpy import build_rig_profiles_from_snapshot
        profiles = build_rig_profiles_from_snapshot(snap)
        profile = profiles.get(args.source)
        if profile is None:
            print(red(f"ERROR: snapshot did not contain a profile for {args.source!r}"))
            sys.exit(1)
        print(f"  {green('OK')} — {len(profile.bones)} bones, family={profile.family!r}")
    except Exception as exc:
        print(red(f"ERROR: could not build rig profile — {exc}"))
        sys.exit(1)

    # ── verify the bone exists in the profile ─────────────────────────────────────

    if args.bone not in profile.bone_names():
        close = [n for n in profile.bone_names() if args.bone.lower() in n.lower()]
        msg = f"Bone {args.bone!r} not found in {args.source!r} rig profile."
        if close:
            msg += f"\n  Similar names: {close[:8]}"
        print(red(f"ERROR: {msg}"))
        sys.exit(1)

    bone_profile = profile.bone(args.bone)
    print(f"  Effector {args.bone!r} found "
          f"(parent={bone_profile.parent_name!r}, "
          f"world_pos={_fmt_vec(bone_profile.world_position) if bone_profile.world_position else 'n/a'})")

    # ── show the suggested chain ──────────────────────────────────────────────────

    chain = profile.suggest_primary_chain(args.bone)
    if chain is not None:
        from dazpy._interaction import _alignment_chain_names
        chain_names = _alignment_chain_names(profile, chain)
        print(f"  IK chain ({chain.role}/{chain.side}): {chain_names}")
    else:
        print(yellow("  WARNING: no IK chain suggestion for this bone — solver may skip"))

    if args.dry_run:
        print(yellow("\n[dry-run] Would call align_single_limb_target with:"))
        print(f"  figure    = {args.source!r}")
        print(f"  bone      = {args.bone!r}")
        print(f"  target    = {_fmt_vec(target_pos)}")
        print()
        sys.exit(0)

    # ── save pose if restore requested ────────────────────────────────────────────

    saved_pose: dict | None = None
    if args.restore:
        saved_pose = skeleton.bone_rotations()
        print(dim("\n  Pose saved — will restore after test."))

    # ── run IK ───────────────────────────────────────────────────────────────────

    print(f"\nRunning IK: moving {args.bone!r} toward {_fmt_vec(target_pos)} …")

    try:
        from dazpy._interaction import align_single_limb_target, ResolvedInteractionTarget

        resolved = ResolvedInteractionTarget(
            figure_label=args.source,
            anchor_name=args.bone,
            bone_name=args.bone,
            target_point=target_pos,
        )

        result = align_single_limb_target(
            skeleton,
            profile,
            resolved,
            max_iterations=args.max_iter,
            step_degrees=args.step,
            damping=args.damping,
            tolerance=args.tolerance,
        )

    except Exception as exc:
        print(red(f"ERROR: IK solver failed — {type(exc).__name__}: {exc}"))
        if saved_pose is not None:
            skeleton.set_bone_rotations(saved_pose)
            print(dim("  Pose restored after error."))
        sys.exit(1)

    # ── report ────────────────────────────────────────────────────────────────────

    print()
    print(bold("══ Results ══"))
    converged_tag = green("CONVERGED") if result.converged else yellow("NOT CONVERGED")
    print(f"  Status         : [{converged_tag}]")
    print(f"  IK path        : {result.diagnostics.get('path', 'single-call')}")
    print(f"  Chain          : {result.chain}")
    print(f"  Iterations     : {result.iterations}")
    if result.initial_error is not None:
        print(f"  Initial error  : {result.initial_error:.3f} scene units")
    if result.final_error is not None:
        print(f"  Final error    : {result.final_error:.3f} scene units")
        if result.initial_error is not None and result.initial_error > 0:
            reduction = (1.0 - result.final_error / result.initial_error) * 100
            print(f"  Error reduction: {reduction:.1f}%")
    if result.diagnostics.get("reason"):
        print(f"  Note           : {result.diagnostics['reason']}")

    if result.applied_rotations:
        print(f"\n  Applied rotations ({len(result.applied_rotations)} bones):")
        for bone_name, rot in result.applied_rotations.items():
            print(f"    {bone_name:30s}  x={rot[0]:+7.2f}°  y={rot[1]:+7.2f}°  z={rot[2]:+7.2f}°")

    # ── restore ───────────────────────────────────────────────────────────────────

    if saved_pose is not None:
        skeleton.set_bone_rotations(saved_pose)
        print(dim(f"\n  Pose of {args.source!r} restored."))

    print()
    if not result.converged and result.final_error is not None and result.final_error > args.tolerance:
        print(yellow("  Tip: try --max-iter 50 or smaller --step/--damping for harder targets."))

    sys.exit(0 if result.chain else 1)


if __name__ == "__main__":
    main()
