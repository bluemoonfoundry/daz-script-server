"""DAZ Studio viewport capture utility.

Modes
-----
raw     Capture the viewport exactly as it appears (all overlays visible).
clean   Hide overlays, deselect nodes, and mute environment nodes before
        capture, then restore everything.  Good for reference screenshots.
sprite  Clean capture + AI background removal (rembg).  Saves a transparent
        PNG ready to use as a game/UI sprite.

Examples
--------
# Basic clean screenshot
python examples/capture_viewport.py --output C:/tmp/snap.png

# Sprite with transparent background (default mode)
python examples/capture_viewport.py --mode sprite --output C:/tmp/sprite.png

# Sprite with a custom backdrop colour to improve edge separation
python examples/capture_viewport.py --mode sprite --backdrop 0,0,255 --output C:/tmp/sprite.png

# Sprite without alpha matting (faster, lower quality edges)
python examples/capture_viewport.py --mode sprite --no-alpha-matting --output C:/tmp/sprite.png

# Raw capture -- no overlay hiding
python examples/capture_viewport.py --mode raw --output C:/tmp/raw.png

# Connect to a non-default DAZ Studio server
python examples/capture_viewport.py --daz-url http://192.168.1.10:18811 --output C:/tmp/snap.png
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from dazpy import DazClient, DazViewport


def _parse_backdrop(value: str) -> tuple[int, int, int]:
    parts = value.split(",")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(
            f"backdrop must be R,G,B (e.g. 0,255,0), got: {value!r}"
        )
    try:
        r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"backdrop values must be integers 0-255, got: {value!r}"
        )
    if not all(0 <= v <= 255 for v in (r, g, b)):
        raise argparse.ArgumentTypeError(
            f"backdrop values must be in range 0-255, got: {value!r}"
        )
    return (r, g, b)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Capture the DAZ Studio viewport to a file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Examples")[1] if "Examples" in __doc__ else "",
    )
    p.add_argument(
        "--mode",
        choices=["raw", "clean", "sprite"],
        default="clean",
        help="Capture mode: raw / clean / sprite (default: clean)",
    )
    p.add_argument(
        "--output", "-o",
        metavar="PATH",
        required=True,
        help="Output file path (.png recommended)",
    )
    p.add_argument(
        "--backdrop",
        metavar="R,G,B",
        type=_parse_backdrop,
        default=None,
        help="Override viewport background colour during capture (e.g. 0,255,0). "
             "Useful in sprite mode to separate edge colours from the backdrop.",
    )
    p.add_argument(
        "--no-alpha-matting",
        action="store_true",
        help="Sprite mode: disable alpha matting (faster, lower edge quality)",
    )
    p.add_argument(
        "--daz-url",
        metavar="URL",
        default="http://127.0.0.1:18811",
        help="DAZ Studio script server URL (default: http://127.0.0.1:18811)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen without executing",
    )
    return p.parse_args()


def _fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    args = _parse_args()

    if args.dry_run:
        print("=== Dry run ===")
        print(f"  Mode:           {args.mode}")
        print(f"  Output:         {args.output}")
        print(f"  Backdrop:       {args.backdrop or '(unchanged)'}")
        if args.mode == "sprite":
            print(f"  Alpha matting:  {'off' if args.no_alpha_matting else 'on'}")
        print(f"  DAZ server:     {args.daz_url}")
        print("  (dry run — no actions taken)")
        return

    if args.mode == "sprite" and not args.output.lower().endswith(".png"):
        print("WARNING: sprite mode output should be a .png file to preserve transparency.")

    # Connect
    print("Connecting to DAZ Studio...", end=" ", flush=True)
    try:
        host, port_str = args.daz_url.replace("http://", "").rsplit(":", 1)
        client = DazClient(host=host, port=int(port_str))
        vp = DazViewport(client)
        if not vp.is_available():
            _fail("Connected but no 3D viewport is open in DAZ Studio.")
    except Exception as exc:
        _fail(f"Cannot reach DAZ Studio at {args.daz_url}: {exc}")
    print("OK")

    print(f"Capturing ({args.mode})...", end=" ", flush=True)
    t0 = time.monotonic()

    try:
        if args.mode == "raw":
            vp.capture(args.output, hide_overlays=False, backdrop_color=args.backdrop)

        elif args.mode == "clean":
            vp.capture(args.output, hide_overlays=True, backdrop_color=args.backdrop)

        elif args.mode == "sprite":
            _capture_sprite(vp, args)

    except Exception as exc:
        print()
        _fail(str(exc))

    elapsed = time.monotonic() - t0
    size_kb = os.path.getsize(args.output) // 1024
    print(f"done ({elapsed:.1f}s, {size_kb} KB)")
    print(f"\nSaved: {args.output}")


def _capture_sprite(vp: DazViewport, args: argparse.Namespace) -> None:
    try:
        from rembg import remove as rembg_remove, new_session
    except ImportError:
        _fail("sprite mode requires rembg: pip install rembg")

    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp_path = f.name
    try:
        vp.capture(tmp_path, hide_overlays=True, backdrop_color=args.backdrop)
        with open(tmp_path, "rb") as f:
            input_data = f.read()
    finally:
        os.unlink(tmp_path)

    session = new_session("u2net")
    if args.no_alpha_matting:
        output_data = rembg_remove(input_data, session=session)
    else:
        output_data = rembg_remove(
            input_data,
            session=session,
            alpha_matting=True,
            alpha_matting_foreground_threshold=240,
            alpha_matting_background_threshold=10,
            alpha_matting_erode_size=10,
        )

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "wb") as f:
        f.write(output_data)


if __name__ == "__main__":
    main()
