"""DAZ Studio Script Server example: save a copy of the current scene without
changing its filename or dirty state.

PURPOSE
-------
Demonstrates ``DazScene.save_copy()``, which calls ``POST /scene/save-copy``
to write the current scene to a new path — equivalent to DAZ Studio's
"Save a Copy As…" menu option — while leaving the scene's internal filename
pointer and dirty flag completely unchanged.

The plugin uses the most side-effect-free strategy available:

- **clean scenes** (no unsaved changes, file already saved):
  ``QFile::copy()`` — a pure file-system copy; DAZ Studio state is not
  touched at all.  The copy is byte-identical to the original.

- **dirty/unsaved scenes** (unsaved changes present):
  ``Scene.saveScene(dest)`` to serialise, then restores the original
  filename if the internal pointer changed.  As a side effect, any unsaved
  changes are also flushed to the original file (unavoidable without the
  ``doSave(saveOnly=true)`` API, which is compiled out of current
  DAZ Studio 4.x builds).  The response ``method`` field tells you which
  strategy was used.

WHAT IT DEMONSTRATES
--------------------
- ``DazScene.save_copy(path)`` — write current scene to a new path
- ``DazScene.filename()``      — query the scene's current file path
- ``DazScene.needs_save()``    — check whether the scene has unsaved changes
- ``POST /scene/save-copy``    — the underlying HTTP endpoint

ENVIRONMENT SETUP
-----------------
1. DAZ Studio must be running with the DazScriptServer plugin loaded and its
   HTTP server active (default: 127.0.0.1:18811).  Verify with:

       curl http://127.0.0.1:18811/health

2. Install / develop-install the dazpy SDK (from the repo root):

       pip install -e .

3. Open any saved scene in DAZ Studio, then run:

       python docs/examples/fundamentals/scene_save_copy.py --dest C:/tmp/backup.duf

Usage:
    python scene_save_copy.py --dest <path>
    python scene_save_copy.py --dest C:/backups/scene_v2.duf
    python scene_save_copy.py --dest C:/backups/scene_v2.duf --compare
    python scene_save_copy.py --dest C:/backups/scene_v2.duf --dry-run
"""

import argparse
import filecmp
import os
import sys

from dazpy import DazClient, DazScene


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dest", required=True, metavar="PATH",
        help="Destination path for the copy (absolute, on the DAZ Studio host)",
    )
    parser.add_argument(
        "--compare", action="store_true",
        help="After saving, compare the copy to the source and print size / identity",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would happen without writing anything",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Server host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=18811, help="Server port (default: 18811)")
    args = parser.parse_args()

    client = DazClient(host=args.host, port=args.port)
    scene  = DazScene(client)

    src       = scene.filename()
    is_dirty  = scene.needs_save()

    print(f"Scene file : {src or '(unsaved)'}")
    print(f"Dirty flag : {is_dirty}")
    print(f"Destination: {args.dest}")

    if args.dry_run:
        if not src:
            print("Strategy  : serialize  (unsaved scene — no source file to copy)")
        elif is_dirty:
            print("Strategy  : serialize+restore  (dirty scene — will write, then restore filename)")
        else:
            print("Strategy  : copy  (clean scene — QFile::copy, no DAZ state change)")
        print("Dry run — no files written.")
        return

    result = scene.save_copy(args.dest)

    print(f"ok     : {result.get('ok')}")
    print(f"path   : {result.get('path')}")
    print(f"source : {result.get('source') or '(none)'}")
    print(f"method : {result.get('method')}")

    if result.get("method") in ("serialize+restore",):
        print(
            "\nNote: the scene had unsaved changes. They have been written to the\n"
            "original file as a side effect of the serialize+restore strategy."
        )

    if args.compare:
        dest_path = args.dest.replace("/", os.sep)
        src_path  = src.replace("/", os.sep) if src else None

        if not os.path.exists(dest_path):
            print(f"\nCompare: ERROR — copy not found at {dest_path}", file=sys.stderr)
            sys.exit(1)

        dest_size = os.path.getsize(dest_path)
        print(f"\nCopy size  : {dest_size:,} bytes")

        if src_path and os.path.exists(src_path):
            src_size  = os.path.getsize(src_path)
            identical = filecmp.cmp(src_path, dest_path, shallow=False)
            print(f"Source size: {src_size:,} bytes")
            print(f"Identical  : {identical}")
        else:
            print("Source size: (unavailable — original file path unknown or inaccessible)")


if __name__ == "__main__":
    main()
