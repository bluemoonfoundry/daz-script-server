"""Interpolate between two saved character states and render each step.

Loads two state files produced by character_state.py, interpolates all bone
rotations, morph values, and FACS properties across N steps using a
configurable easing curve, then renders each frame.

Python owns the animation math (easing, lerp).  DAZ Studio applies the
result at each step — it has no knowledge of the interpolation happening
outside it.

Usage:
    python pose_interpolation.py --a neutral.json --b smile.json --steps 10
    python pose_interpolation.py --a neutral.json --b smile.json \\
        --steps 30 --ease ease_in_out --out C:/interpolation --width 1920 --height 1080
"""

import argparse
import json
import math
import os

from dazpy import DazClient, DazRenderSettings

# ── easing functions ───────────────────────────────────────────────────────────
# All take t in [0, 1] and return a value in [0, 1].

EASING = {
    "linear":         lambda t: t,
    "ease_in":        lambda t: t ** 2,
    "ease_out":       lambda t: 1 - (1 - t) ** 2,
    "ease_in_out":    lambda t: 3*t**2 - 2*t**3,          # smoothstep
    "ease_in_cubic":  lambda t: t ** 3,
    "ease_out_cubic": lambda t: 1 - (1 - t) ** 3,
    "ease_in_out_cubic": lambda t: 4*t**3 if t < 0.5 else 1 - (-2*t + 2)**3 / 2,
    "bounce_out": lambda t: (
        7.5625*t*t if t < 1/2.75 else
        7.5625*(t - 1.5/2.75)**2 + 0.75 if t < 2/2.75 else
        7.5625*(t - 2.25/2.75)**2 + 0.9375 if t < 2.5/2.75 else
        7.5625*(t - 2.625/2.75)**2 + 0.984375
    ),
}

# ── interpolation helpers ──────────────────────────────────────────────────────

def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t

def lerp_state(state_a: dict, state_b: dict, t: float):
    """Return (morphs, props, bones) interpolated at position t."""
    a_morphs = state_a.get("morphs", {})
    b_morphs = state_b.get("morphs", {})
    morphs = {
        k: lerp(a_morphs.get(k, 0.0), b_morphs.get(k, 0.0), t)
        for k in set(a_morphs) | set(b_morphs)
    }

    a_props = state_a.get("props", {})
    b_props = state_b.get("props", {})
    props = {
        k: lerp(a_props.get(k, 0.0), b_props.get(k, 0.0), t)
        for k in set(a_props) | set(b_props)
    }

    a_bones = state_a.get("bones", {})
    b_bones = state_b.get("bones", {})
    bones = {
        k: [lerp(a_bones.get(k, [0.0, 0.0, 0.0])[i],
                 b_bones.get(k, [0.0, 0.0, 0.0])[i], t)
            for i in range(3)]
        for k in set(a_bones) | set(b_bones)
    }

    return morphs, props, bones

# ── DAZ Studio apply ───────────────────────────────────────────────────────────

def _skel_lookup(label: str) -> str:
    escaped = json.dumps(label)
    return (
        f"var _skel=null,_skels=Scene.getSkeletonList();"
        f"for(var _i=0;_i<_skels.length;_i++){{"
        f"if(_skels[_i].getLabel()==={escaped}){{_skel=_skels[_i];break;}}}}"
    )

def apply_state(client: DazClient, figure_label: str,
                morphs: dict, props: dict, bones: dict) -> None:
    """Push an interpolated state to DAZ Studio in a single HTTP call."""
    morph_lines = " ".join(
        f"var _m=obj.findModifier({json.dumps(n)});"
        f"if(_m)_m.getValueChannel().setValue({round(v, 6)});"
        for n, v in morphs.items()
    )
    prop_lines = " ".join(
        f"var _p=_skel.findProperty({json.dumps(n)});"
        f"if(_p&&_p.setValue)_p.setValue({round(v, 6)});"
        for n, v in props.items()
    )
    bone_lines = " ".join(
        f"var _b=_skel.findBone({json.dumps(n)});"
        f"if(_b){{"
        f"_b.getXRotControl().setValue({round(xyz[0], 6)});"
        f"_b.getYRotControl().setValue({round(xyz[1], 6)});"
        f"_b.getZRotControl().setValue({round(xyz[2], 6)});}}"
        for n, xyz in bones.items()
    )

    client.execute(f"""(function(){{
        {_skel_lookup(figure_label)}
        if (!_skel) return;
        var obj = _skel.getObject();
        if (obj) {{ {morph_lines} }}
        {prop_lines}
        {bone_lines}
    }})()""")

# ── CLI ────────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--a",     required=True, help="State A JSON file (start pose)")
parser.add_argument("--b",     required=True, help="State B JSON file (end pose)")
parser.add_argument("--steps", type=int, default=10, help="Number of frames to render (includes A and B)")
parser.add_argument("--ease",  default="ease_in_out", choices=sorted(EASING),
                    help="Easing function (default: ease_in_out)")
parser.add_argument("--out",   default="y:/tmp/interpolation")
parser.add_argument("--width",  type=int, default=1920)
parser.add_argument("--height", type=int, default=1080)
parser.add_argument("--figure", default=None,
                    help="Override figure label (default: taken from state A file)")
args = parser.parse_args()

with open(args.a, encoding="utf-8") as f:
    state_a = json.load(f)
with open(args.b, encoding="utf-8") as f:
    state_b = json.load(f)

figure_label = args.figure or state_a.get("figure")
if not figure_label:
    raise SystemExit("Could not determine figure label — use --figure.")

if args.steps < 2:
    raise SystemExit("--steps must be at least 2 (start and end).")

os.makedirs(args.out, exist_ok=True)

client = DazClient()
render = DazRenderSettings(client)
render.set_resolution(args.width, args.height)

ease_fn = EASING[args.ease]

print(f"Interpolating {args.steps} steps ({args.ease}) → {args.out}")
print(f"  A: {args.a}  ({len(state_a.get('bones', {}))} bones, "
      f"{len(state_a.get('morphs', {}))} morphs, {len(state_a.get('props', {}))} props)")
print(f"  B: {args.b}  ({len(state_b.get('bones', {}))} bones, "
      f"{len(state_b.get('morphs', {}))} morphs, {len(state_b.get('props', {}))} props)\n")

try:
    for i in range(args.steps):
        t_linear = i / (args.steps - 1)
        t_eased  = ease_fn(t_linear)

        morphs, props, bones = lerp_state(state_a, state_b, t_eased)
        apply_state(client, figure_label, morphs, props, bones)

        out_path = os.path.join(args.out, f"frame_{i:03d}.png")
        render.output_path = out_path
        render.render()
        print(f"  [{i+1}/{args.steps}] t={t_linear:.3f} → eased={t_eased:.3f}  {out_path}")

finally:
    # Restore state A so DAZ Studio is left at the starting pose.
    morphs, props, bones = lerp_state(state_a, state_b, 0.0)
    apply_state(client, figure_label, morphs, props, bones)
    print("\nRestored state A.")

print(f"\nDone. {args.steps} frames in {args.out}")
print (f"If you have ffmpeg installed and want to create an animation, copy and paste this command:\n")
print(f"ffmpeg -framerate 24 -i \"{os.path.join(args.out, 'frame_%03d.png')}\" interpolation.mp4")
