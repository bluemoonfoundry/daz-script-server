"""Dump a structured inventory of every node in the scene to JSON.

Collects per-node: type, label, world position, visibility, material names,
vertex count, and (for figures) bone count and morph count.  Everything is
gathered in a single DazScript call so the report is fast regardless of
scene size.

Useful for pipeline QC, asset auditing, and debugging scene composition.

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
