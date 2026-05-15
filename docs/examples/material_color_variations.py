"""Render a node's material in multiple diffuse colours.

Useful for product shots, clothing swatches, or any scene where you want
the same composition in different colours without manual material edits.

The original colour is saved before the loop and restored afterward
(including if the run is interrupted).

Usage:
    python material_color_variations.py --node "Cube" --material "Default"
    python material_color_variations.py \\
        --node "Shirt" --material "Fabric" \\
        --colors "#C0392B" "#2980B9" "#27AE60" "#8E44AD" \\
        --out C:/swatches --width 1920 --height 1080
"""

import argparse
import os
import re

from dazpy import DazScene, DazRenderSettings

# ── default swatch palette ─────────────────────────────────────────────────────
DEFAULT_COLORS = [
    ("#C0392B", "crimson"),
    ("#E67E22", "orange"),
    ("#F1C40F", "yellow"),
    ("#27AE60", "green"),
    ("#2980B9", "blue"),
    ("#8E44AD", "purple"),
    ("#ECF0F1", "white"),
    ("#2C3E50", "charcoal"),
]

# ── helpers ────────────────────────────────────────────────────────────────────

def parse_hex(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"Expected 6-digit hex color, got: {hex_color!r}")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

def safe_filename(s: str) -> str:
    return re.sub(r"[^\w\-]", "_", s).strip("_") or "color"

# ── CLI ────────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--node",     required=True, help="Node label in the Scene panel")
parser.add_argument("--material", required=True, help="Material name on the node")
parser.add_argument("--colors",   nargs="+", metavar="HEX",
                    help="Hex colours to render e.g. '#FF0000' '#00FF00'. Default: built-in palette.")
parser.add_argument("--out",      default="y:/tmp/swatches")
parser.add_argument("--width",    type=int, default=1920)
parser.add_argument("--height",   type=int, default=1080)
args = parser.parse_args()

os.makedirs(args.out, exist_ok=True)

scene  = DazScene()
render = DazRenderSettings()

node = scene.find_node_by_label(args.node)
mat  = node.find_material(args.material)
if mat is None:
    available = [m.material_name for m in node.materials()]
    raise SystemExit(
        f"Material {args.material!r} not found on {args.node!r}.\n"
        f"Available: {available}"
    )

if args.colors:
    swatches = [(c, safe_filename(c)) for c in args.colors]
else:
    swatches = DEFAULT_COLORS

render.set_resolution(args.width, args.height)

original_color = mat.diffuse_color
print(f"Original colour: {original_color}")
print(f"Rendering {len(swatches)} variation(s) → {args.out}\n")

try:
    for hex_color, name in swatches:
        r, g, b = parse_hex(hex_color)
        mat.diffuse_color = (r, g, b)
        out_path = os.path.join(args.out, f"{safe_filename(name)}.png")
        render.output_path = out_path
        render.render()
        print(f"  {hex_color}  {name:20s} → {out_path}")
finally:
    if original_color:
        mat.diffuse_color = original_color
        print(f"\nRestored original colour: {original_color}")

print("Done.")
