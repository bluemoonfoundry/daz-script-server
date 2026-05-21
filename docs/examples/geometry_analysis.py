"""DAZ Studio Script Server example: inspect and analyse a figure's mesh geometry.

PURPOSE
-------
This script is a demonstration of what the DAZ Studio Script Server makes
possible.  It retrieves a figure's mesh metadata, computes axis-aligned bounding
boxes for both the rest and posed mesh, lists face and material groups with their
face counts, and demonstrates Python-side mesh utilities such as quad-to-triangle
conversion and Vec3-wrapped vertex access.

It is an *example*, not a production mesh exporter.  A full tool would stream
vertex data to disk in chunks, handle multiple UV sets, and resolve sub-division
levels before export.  The goal here is to show that the script server exposes
enough of the geometry model for Python to answer the questions a downstream
pipeline (game engine import, collision mesh generation, LOD selection) typically
asks before processing a mesh.

WHAT IT DEMONSTRATES
--------------------
  - Fetching all mesh metadata in one HTTP call (DazGeometry.mesh_info)
  - Computing the rest-mesh bounding box server-side (DazGeometry.bounding_box)
  - Computing the posed+morphed bounding box server-side (DazGeometry.bounding_box_posed)
  - Listing face groups and retrieving their face indices (DazGeometry.face_group_faces)
  - Listing material groups and retrieving their face indices (DazGeometry.material_group_faces)
  - Fetching all face indices with automatic pagination (DazGeometry.face_vertex_indices_all)
  - Converting a mixed tri/quad mesh to all-triangles in Python (DazGeometry.triangulate)
  - Wrapping vertex positions in Vec3 objects (DazGeometry.as_vec3)
  - Using BoundingBox spatial operations: center, size, volume, contains, overlaps

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

4. Open a scene in DAZ Studio containing a figure, then run:

       python docs/examples/geometry_analysis.py --figure "Genesis 9"

Usage:
    python geometry_analysis.py --figure "Genesis 9"
    python geometry_analysis.py --figure "Genesis 9" --groups
    python geometry_analysis.py --figure "Genesis 9" --triangulate --out tris.json
"""

import argparse
import json
import sys

from dazpy import BoundingBox, DazGeometry, DazScene
from dazpy._node import NodeIdentifier

if __name__ == "__main__":
    # ── CLI ───────────────────────────────────────────────────────────────────────

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--figure",     default="Genesis 9", help="Figure label")
    parser.add_argument("--groups",     action="store_true",
                        help="Print face/material group details")
    parser.add_argument("--triangulate",action="store_true",
                        help="Export all-triangle face list")
    parser.add_argument("--out",        default="triangles.json",
                        help="Output path for --triangulate")
    args = parser.parse_args()

    # ── connect and find figure ───────────────────────────────────────────────────

    scene = DazScene()
    geo = DazGeometry(scene._client, NodeIdentifier(args.figure, kind="label"))

    # ── bulk metadata — one HTTP call ─────────────────────────────────────────────

    # mesh_info() consolidates what would otherwise be 7+ separate property reads
    # (vertex_count, facet_count, tris_count, quads_count, subdivision_level,
    # uv_set_count, face_group_names, material_group_names) into a single call.
    # Returns None if the figure is not found in the scene.
    info = geo.mesh_info()
    if info is None:
        sys.exit(f"Error: figure {args.figure!r} not found in scene or has no geometry.")

    print(f"=== Mesh info: {args.figure!r} ===")
    print(f"  Vertices      : {info['vertex_count']:,}")
    print(f"  Faces         : {info['facet_count']:,}  "
          f"(tris={info['tris_count'] or '?'}  quads={info['quads_count'] or '?'})")
    print(f"  UV sets       : {info['uv_set_count'] or '?'}")
    print(f"  Subd level    : {info['subdivision_level'] or 0}")
    print(f"  Face groups   : {len(info['face_group_names'])}")
    print(f"  Material groups: {len(info['material_group_names'])}")

    # ── bounding boxes — one HTTP call each ───────────────────────────────────────

    # bounding_box() iterates all base-mesh vertices server-side and returns
    # {min, max} — no need to transfer every vertex to Python just to compute an AABB.
    bb_rest = geo.bounding_box()
    bb_posed = geo.bounding_box_posed()

    def _fmt_bb(bb: BoundingBox) -> str:
        c = bb.center
        s = bb.size
        return (f"center=({c.x:.1f}, {c.y:.1f}, {c.z:.1f})  "
                f"size=({s.x:.1f} × {s.y:.1f} × {s.z:.1f})  "
                f"volume={bb.volume:.0f}")

    print(f"\n=== Bounding boxes ===")
    if bb_rest:
        print(f"  Rest mesh : {_fmt_bb(bb_rest)}")
    if bb_posed:
        print(f"  Posed     : {_fmt_bb(bb_posed)}")

    # BoundingBox supports spatial queries entirely in Python — no extra HTTP calls.
    if bb_rest and bb_posed:
        drift = bb_rest.center.distance(bb_posed.center)
        print(f"  Center drift (rest → posed): {drift:.2f} units")
        print(f"  Posed AABB contains rest center: {bb_posed.contains(bb_rest.center)}")

    # ── face and material groups ───────────────────────────────────────────────────

    if args.groups:
        print(f"\n=== Face groups ===")
        for name in info["face_group_names"] or []:
            # face_group_faces() returns the list of face indices that belong to
            # the named group — one HTTP call per group.
            indices = geo.face_group_faces(name)
            print(f"  {name:<30}  {len(indices):>6} faces")

        print(f"\n=== Material groups ===")
        for name in info["material_group_names"] or []:
            indices = geo.material_group_faces(name)
            print(f"  {name:<30}  {len(indices):>6} faces")

    # ── triangulate and export ─────────────────────────────────────────────────────

    if args.triangulate:
        print(f"\nFetching all face indices…")

        # face_vertex_indices_all() paginates automatically; each page is one HTTP
        # call.  The total number of calls is ceil(facet_count / chunk_size).
        faces = geo.face_vertex_indices_all()
        print(f"  {len(faces)} faces fetched")

        # triangulate() is pure Python — no HTTP round-trip.
        # Quads are split along the 0→2 diagonal: [v0,v1,v2,v3] → two tris.
        tris = DazGeometry.triangulate(faces)
        quad_count = sum(1 for f in faces if len(f) == 4)
        print(f"  {quad_count} quads → {quad_count * 2} tris  "
              f"(total: {len(tris)} triangles)")

        # as_vec3() wraps the raw vertex list in Vec3 objects — pure Python.
        # Useful for downstream math (distances, normals, projections).
        print("Fetching all vertex positions…")
        raw_verts = geo.vertex_positions_all()
        verts = DazGeometry.as_vec3(raw_verts)
        print(f"  {len(verts)} vertices as Vec3 objects")
        if verts:
            print(f"  First vertex: {verts[0]}")

        output = {
            "figure": args.figure,
            "vertex_count": len(verts),
            "triangle_count": len(tris),
            "triangles": tris,
        }
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2)
        print(f"Saved all-triangle mesh → {args.out}")

    print("\nDone.")
