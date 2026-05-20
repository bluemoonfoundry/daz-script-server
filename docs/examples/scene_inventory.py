"""DAZ Studio Script Server example: dump a structured inventory of every scene node to JSON.

PURPOSE
-------
This script is a demonstration of what the DAZ Studio Script Server makes
possible.  It collects rich metadata for every node in a running DAZ Studio
scene in a single HTTP call and writes the result to JSON, without modifying
the scene or interacting with any UI element.

It is an *example*, not a production pipeline QC tool.  A full auditing
system would also report texture file paths, subdivision levels, simulation
settings, and scene memory estimates.  The goal here is to show that the
script server enables Python to extract a machine-readable scene manifest in
one pass — useful for debugging scene composition, asset auditing, and
feeding downstream pipeline tools.

WHAT IT DEMONSTRATES
--------------------
  - Gathering data for all scene nodes in a single DazScript call (no per-node
    round-trips regardless of scene size)
  - Collecting per-node type, label, world position, visibility flags,
    material names, vertex/face counts
  - Reporting skeleton-specific metadata: bone count and morph count
  - Reporting scene hierarchy (parent name and child count per node)
  - Writing results to stdout or to a file, with optional pretty-printing

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

4. Open any scene in DAZ Studio, then run:

       python docs/examples/scene_inventory.py

Usage:
    python scene_inventory.py
    python scene_inventory.py --out inventory.json
    python scene_inventory.py --out inventory.json --pretty
"""

import argparse
import json
import sys

from dazpy import DazClient

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--out",    default=None, help="Write JSON to this file (default: stdout)")
parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
args = parser.parse_args()

client = DazClient()

result = client.execute("""
(function() {
    var nodes = [];

    for (var i = 0; i < Scene.getNumNodes(); i++) {
        var n = Scene.getNode(i);

        // Node type
        var nodeType = "node";
        if (n.inherits("DzSkeleton")) nodeType = "skeleton";
        else if (n.inherits("DzCamera")) nodeType = "camera";
        else if (n.inherits("DzLight"))  nodeType = "light";

        // World position
        var pos = n.getWSPos();

        // Visibility
        var visible         = n.isVisible();
        var visibleRender   = n.isVisibleInRender();
        var visibleViewport = n.isVisibleInViewport();

        // Geometry
        var vertexCount = null;
        var faceCount   = null;
        var materials   = [];
        var obj = n.getObject();
        if (obj) {
            var shape = obj.getCurrentShape();
            if (shape) {
                var geo = shape.getGeometry();
                if (geo) {
                    vertexCount = geo.getNumVertices();
                    faceCount   = geo.getNumFacets();
                }
                for (var m = 0; m < shape.getNumMaterials(); m++) {
                    materials.push(shape.getMaterial(m).getName());
                }
            }
        }

        // Skeleton-specific
        var boneCount  = null;
        var morphCount = null;
        if (nodeType === "skeleton") {
            boneCount = n.getAllBones().length;
            if (obj) morphCount = obj.getNumModifiers();
        }

        // Hierarchy
        var parent   = n.getNodeParent();
        var children = n.getNumNodeChildren();

        nodes.push({
            name:             n.getName(),
            label:            n.getLabel(),
            type:             nodeType,
            position:         {x: pos.x, y: pos.y, z: pos.z},
            visible:          visible,
            visible_render:   visibleRender,
            visible_viewport: visibleViewport,
            vertex_count:     vertexCount,
            face_count:       faceCount,
            materials:        materials,
            material_count:   materials.length,
            bone_count:       boneCount,
            morph_count:      morphCount,
            parent:           parent ? parent.getName() : null,
            child_count:      children
        });
    }

    return {
        node_count: nodes.length,
        nodes:      nodes
    };
})()
""").value

if result is None:
    sys.exit("Error: could not collect scene inventory.")

indent = 2 if args.pretty else None

if args.out:
    with open(args.out, "w") as f:
        json.dump(result, f, indent=indent)
    print(f"Wrote {result['node_count']} nodes → {args.out}")
else:
    print(json.dumps(result, indent=indent))
