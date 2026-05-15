"""Execute raw DazScript directly via the low-level client.

dazpy's typed API covers the most common operations, but the underlying
HTTP server accepts any DazScript.  This example shows how to drop to raw
script when you need something the SDK doesn't expose yet.

Usage:
    python raw_script.py
"""

import json
from dazpy import DazClient

client = DazClient()

# Any DazScript expression wrapped in an IIFE — return value is JSON-serialised
# and handed back to Python as result.value.
result = client.execute("""
    (function() {
        var node = Scene.getPrimarySelection();
        if (!node) return null;
        var obj  = node.getObject();
        var geo  = obj ? obj.getCurrentShape().getGeometry() : null;
        return {
            name:     node.getName(),
            label:    node.getLabel(),
            vertices: geo ? geo.getNumVertices() : null,
            faces:    geo ? geo.getNumFacets()   : null
        };
    })()
""")

print(json.dumps(result.value, indent=2))
