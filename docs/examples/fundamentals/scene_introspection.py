"""DAZ Studio Script Server example: dump the full scene hierarchy and node transforms as JSON.

PURPOSE
-------
This script is a demonstration of what the DAZ Studio Script Server makes
possible.  It interrogates a running DAZ Studio instance over HTTP and prints
the entire scene hierarchy and per-node world transforms as JSON — without
touching DAZ Studio's UI or modifying the scene.

It is an *example*, not a production scene-analysis tool.  The goal here is
to show that the script server gives Python read-only access to scene structure
that is normally only visible through DAZ Studio's Scene panel.

WHAT IT DEMONSTRATES
--------------------
  - Read-only scene access through the dazpy DazScene wrapper
  - Retrieving the full node hierarchy (DazScene.node_tree)
  - Retrieving world-space transforms for every node (DazScene.all_node_transforms)
  - Piping JSON output to downstream tools (jq, grep, etc.)

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

       python docs/examples/fundamentals/scene_introspection.py

Usage:
    python scene_introspection.py
    python scene_introspection.py | jq '.tree[0]'
"""

import argparse
import json

from dazpy import DazScene

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.parse_args()

    scene = DazScene()

    output = {
        "tree":       scene.node_tree(),
        "transforms": scene.all_node_transforms(),
    }

    print(json.dumps(output, indent=2))
