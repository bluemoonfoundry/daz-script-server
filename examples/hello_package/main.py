"""Minimal example .dzpkg entry point for validating the Package Runner
end to end (daz-script-server-5sw). Not part of the automated test suite --
see tests/fixtures/dsp_runner/ for those.

Every package's entryPoint must define run(inputs: dict) -> Any: dsp_runner
(the harness bundled into this package's venv alongside dazpy) imports this
module and calls run() with the values collected by DzPackageInputsDialog
(or {} for a non-interactive package). Whatever run() returns must be
JSON-serializable -- it becomes the envelope's "result".

Demonstrates the actual point of a .dzpkg: calling back into the live DAZ
Studio session that opened it, via dazpy against daz-script-server's
existing port 18811 -- no separate daemon involved at all.
"""

from dazpy import DazClient


def run(inputs):
    name = inputs.get("name", "world")
    repeat_count = inputs.get("repeatCount", 1)

    # DazClient() with no args connects to 127.0.0.1:18811 and auto-loads
    # ~/.daz3d/dazscriptserver_token.txt -- the same token file DAZ Studio's
    # own DzScriptServerPane already generates, no new auth setup needed.
    client = DazClient()
    node_count = client.execute("Scene.getNodeList().length").value

    greeting = f"Hello, {name}!"
    for _ in range(repeat_count):
        print(greeting)

    return {
        "greeting": greeting,
        "sceneNodeCount": node_count,
    }
