"""DAZ Studio Script Server example: execute raw DazScript via the low-level HTTP client.

PURPOSE
-------
This script is a demonstration of what the DAZ Studio Script Server makes
possible.  It bypasses the dazpy typed wrappers and posts a hand-written
DazScript IIFE directly to the server, returning a structured JSON result to
Python.

It is an *example*, not a general-purpose scripting harness.  The goal here is
to show that dazpy's high-level API is built on a simple HTTP call, and you
can drop down to that level whenever you need to access DAZ APIs that the SDK
doesn't expose yet — or when you want to prototype something quickly.

WHAT IT DEMONSTRATES
--------------------
  - Using DazClient directly instead of the higher-level dazpy wrappers
  - Sending an arbitrary DazScript expression (wrapped in an IIFE) to the server
  - Accessing the return value via result.value (JSON-decoded automatically)
  - Reading basic geometry info from the primary selection (vertices, faces)

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

4. Open a scene in DAZ Studio and select any node, then run:

       python docs/examples/raw_script.py

Usage:
    python raw_script.py
"""

import argparse
import json

from dazpy import DazClient

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.parse_args()

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
