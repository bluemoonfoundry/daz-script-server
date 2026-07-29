"""One-shot harness for running a Package Runner .dzpkg entry point
(daz-script-server-5sw).

Invoked by direct file path (never `-m package_runner.dsp_runner` -- a
per-package venv only ever has `dazpy` + that package's own declared
dependencies installed into it by PackageDependencyInstaller, nothing else
importable by name; see daz-python-bridge's daemon/app.py commit 2efdc23 for
the exact bug this avoids) as:

    <package_venv_python> <path-to-dsp_runner.py> <entryPointPath> <inputsJsonPath>

Loads the package's entry point module (a plain .py file, not installed as a
package), calls its `run(inputs: dict) -> Any` function with the dialog-
collected (or empty, for non-interactive packages) inputs loaded from
inputsJsonPath, and prints exactly one final JSON line to stdout:

    {"success": true,  "result": <json>, "output": ["print() lines..."], "error": ""}
    {"success": false, "result": null,   "output": [...], "error": "<message>"}

The entry point's own print() output is captured (not left on the real
stdout) so it can neither corrupt anything reading this process's stdout for
the final envelope line, nor be lost -- it comes back as `output`, mirroring
daz-python-bridge's worker_runtime.py hardening (a plugin/package author's
ordinary print()-debugging must never break the calling process's ability to
parse the result).
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import traceback


def _load_entry(entry_path: str):
    spec = importlib.util.spec_from_file_location("package_entry", entry_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load package entry point: {entry_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(entry_path: str, inputs_path: str) -> dict:
    with open(inputs_path, "r", encoding="utf-8") as f:
        inputs = json.load(f)

    try:
        module = _load_entry(entry_path)
    except Exception as exc:
        return {"success": False, "result": None, "output": [], "error": str(exc)}

    run_func = getattr(module, "run", None)
    if run_func is None:
        return {
            "success": False,
            "result": None,
            "output": [],
            "error": f"{entry_path} does not define a run(inputs) function",
        }

    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output):
            result = run_func(inputs)
        json.dumps(result)  # fail fast if the result can't cross the wire as JSON
    except Exception as exc:
        return {
            "success": False,
            "result": None,
            "output": output.getvalue().splitlines(),
            "error": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip(),
        }

    return {"success": True, "result": result, "output": output.getvalue().splitlines(), "error": ""}


def main() -> None:
    if len(sys.argv) != 3:
        envelope = {
            "success": False,
            "result": None,
            "output": [],
            "error": f"usage: dsp_runner.py <entryPointPath> <inputsJsonPath> (got {sys.argv[1:]!r})",
        }
    else:
        envelope = run(sys.argv[1], sys.argv[2])

    sys.stdout.write(json.dumps(envelope) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
