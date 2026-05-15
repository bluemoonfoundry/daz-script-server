"""Dump the full scene hierarchy and node transforms as JSON.

Demonstrates read-only scene introspection — no DAZ Studio interaction
required beyond having the plugin running.  Output can be piped or
redirected to feed downstream tools.

Usage:
    python scene_introspection.py
    python scene_introspection.py | jq '.tree[0]'
"""

import json
from dazpy import DazScene

scene = DazScene()

output = {
    "tree":       scene.node_tree(),
    "transforms": scene.all_node_transforms(),
}

print(json.dumps(output, indent=2))
