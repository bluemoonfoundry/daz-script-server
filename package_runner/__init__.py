"""Package Runner harness code (daz-script-server-5sw).

dsp_runner.py is bundled/embedded into every per-package venv's on-disk
layout and invoked by direct file path -- this __init__.py only exists so
this directory's contents are importable for testing from the repo root
(see tests/test_dsp_runner.py); it is not itself part of what ships to a
package venv.
"""
