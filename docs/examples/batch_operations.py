"""DAZ Studio Script Server example: read scene data for multiple figures in one HTTP call.

PURPOSE
-------
This script is a demonstration of what the DAZ Studio Script Server makes
possible.  It uses the Batch class to bundle multiple independent DazScript
reads into a single HTTP request, so that N figures can be interrogated with
1 round-trip instead of N (or N × K for K properties per figure).

It is an *example*, not a general-purpose scene profiler.  A production tool
would also handle nested hierarchies, attached props, and light rigs.  The goal
here is to show the performance pattern: collect what you want to read, execute
once, then unpack the results from the resolved futures.

WHAT IT DEMONSTRATES
--------------------
  - Queueing multiple independent reads with Batch.add()
  - Executing all queued operations in a single HTTP call (Batch.execute / context manager)
  - Resolving results from BatchFuture.value after execution
  - Comparing per-call vs. batched call counts for the same data

HOW BATCH WORKS
---------------
Each Batch.add(lines) call accepts a list of DazScript statements and
auto-generates an internal key (_r0, _r1, ...).  The last statement in the
list must assign the desired return value to a variable with that key name.
All operations are compiled into one IIFE that returns a single object mapping
each key to its value; the futures resolve when execute() is called.

    with Batch(client) as b:
        count_f = b.add(["var _r0 = Scene.getNumNodes();"])
        frame_f = b.add(["var _r1 = Scene.getFrame();"])
    # One HTTP call executed; futures now resolved.
    print(count_f.value, frame_f.value)

ENVIRONMENT SETUP
-----------------
1. DAZ Studio must be running with the DazScriptServer plugin loaded and its
   HTTP server active (default: 127.0.0.1:18811).  You can verify it is
   responding with:

       curl http://127.0.0.1:18811/health

2. Install the Python dependencies in a virtual environment:

       python -m venv .venv
       .venv\\Scripts\\activate          # Windows
       # source .venv/bin/activate     # macOS / Linux
       pip install requests

3. Install or develop-install the dazpy SDK (from the repo root):

       pip install -e .

4. Open a scene in DAZ Studio with one or more figures, then run:

       python docs/examples/batch_operations.py

Usage:
    python batch_operations.py
    python batch_operations.py --compare   # also run the naive per-call version
"""

import argparse
import time

from dazpy import Batch, DazClient, DazScene

if __name__ == "__main__":
    # ── CLI ───────────────────────────────────────────────────────────────────────

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--compare", action="store_true",
        help="Also run the naive per-call version and compare call counts",
    )
    args = parser.parse_args()

    # ── connect ───────────────────────────────────────────────────────────────────

    client = DazClient()
    scene  = DazScene(client)

    skeletons = scene.skeletons()
    if not skeletons:
        print("No figures found in scene.  Load a character and try again.")
        raise SystemExit(0)

    print(f"Found {len(skeletons)} skeleton(s) in scene.\n")

    # ── Part 1: batch — one HTTP call reads everything ────────────────────────────

    # Without Batch, reading label + bone_count + morph_count for N figures requires
    # 3N HTTP calls (one per property).  With Batch, all reads are compiled into a
    # single IIFE that returns one JSON object — 1 call regardless of N.
    #
    # Key naming rule: the first add() gets key _r0, the second _r1, and so on.
    # The DazScript lines in each add() must assign the result to that key name.

    print("=== Batched reads (1 HTTP call) ===")
    t0 = time.perf_counter()

    futures = []
    with Batch(client) as b:
        for i, skel in enumerate(skeletons):
            label_js = repr(skel._identifier.value)  # JS string literal
            key = f"_r{i}"

            # Build a self-contained JS snippet that locates this specific skeleton
            # and returns [label, bone_count, morph_count] as a three-element array.
            futures.append(b.add([
                f"var {key} = (function() {{",
                f"  var _sl = Scene.getSkeletonList();",
                f"  for (var _i = 0; _i < _sl.length; _i++) {{",
                f"    if (_sl[_i].getLabel() === {label_js}) {{",
                f"      var _s = _sl[_i];",
                f"      var _obj = _s.getObject();",
                f"      var _nm = _obj ? _obj.getNumModifiers() : 0;",
                f"      return [_s.getLabel(), _s.getAllBones().length, _nm];",
                f"    }}",
                f"  }}",
                f"  return null;",
                f"}})();",
            ]))

    elapsed_batch = time.perf_counter() - t0

    # futures are resolved now that the `with` block has exited and execute() ran.
    rows = []
    for skel, future in zip(skeletons, futures):
        data = future.value
        if data:
            label, n_bones, n_mods = data
            rows.append((label, n_bones, n_mods))
        else:
            rows.append((skel._identifier.value, "?", "?"))

    for label, n_bones, n_mods in rows:
        print(f"  {label:<30}  {n_bones:>5} bones  {n_mods:>5} modifiers")

    print(f"\n  1 HTTP call  ({elapsed_batch*1000:.1f} ms)")

    # ── Part 2: naive per-call version (optional comparison) ─────────────────────

    if args.compare:
        print("\n=== Naive per-call reads ===")
        t1 = time.perf_counter()
        call_count = 0

        naive_rows = []
        for skel in skeletons:
            # Each property access is an independent HTTP round-trip.
            label    = skel.label                           # 1 call
            n_bones  = skel.num_bones()                     # 1 call
            call_count += 2

            # morph count isn't a direct SDK property, so simulate with a raw call
            from dazpy._script_builder import ScriptBuilder
            import json as _json
            lookup = ScriptBuilder.skeleton_lookup(skel._identifier)
            script = f"""(function(){{
                {lookup}
                if (!_skel) return 0;
                var obj = _skel.getObject();
                return obj ? obj.getNumModifiers() : 0;
            }})()"""
            n_mods = client.execute(script).value or 0      # 1 call
            call_count += 1

            naive_rows.append((label, n_bones, n_mods))

        elapsed_naive = time.perf_counter() - t1

        for label, n_bones, n_mods in naive_rows:
            print(f"  {label:<30}  {n_bones:>5} bones  {n_mods:>5} modifiers")

        print(f"\n  {call_count} HTTP calls  ({elapsed_naive*1000:.1f} ms)")
        print(f"\n  Speedup: {elapsed_naive / elapsed_batch:.1f}× fewer round-trips with Batch")

    # ── Part 3: simple batch — reading independent scene scalars ──────────────────

    print("\n=== Simple batch: scene-level scalars (1 HTTP call) ===")

    with Batch(client) as b:
        node_count_f = b.add(["var _r0 = Scene.getNumNodes();"])
        frame_f      = b.add(["var _r1 = Scene.getFrame();"])
        skel_count_f = b.add(["var _r2 = Scene.getSkeletonList().length;"])

    # All three futures are resolved after the `with` block.
    print(f"  Total nodes  : {node_count_f.value}")
    print(f"  Current frame: {frame_f.value}")
    print(f"  Skeletons    : {skel_count_f.value}")
    print(f"\n  3 values fetched in 1 HTTP call.")
