"""Opt-in gate for test files that talk to a live DAZ Studio.

Live test files change (and some clear) the open scene, so they must never run
just because Studio answers on 127.0.0.1:18811: a ``pytest tests/`` or a glob
like ``tests/test_recipe_*.py`` would otherwise wipe the user's work.

* Call ``require_live(__name__)`` at the top of a live test file, before it
  contacts Studio. Unless ``DAZ_LIVE_TESTS=1`` is set (or the file is run
  directly as a script), it raises ``unittest.SkipTest``, which both pytest
  and unittest treat as "skip this whole module".
* Clear the scene only through ``clear_scene(client)``. The first clear in a
  process refuses a scene that holds anything besides Studio's render-settings
  nodes, unless ``DAZ_LIVE_ALLOW_CLEAR=1`` is set. Once a clear has happened,
  the scene belongs to the tests and later clears go ahead.

``python tests.py api|integration`` sets ``DAZ_LIVE_TESTS=1`` itself: naming a
live suite is the opt-in. The scene-clear guard applies in every case.
"""
from __future__ import annotations

import os
import unittest

LIVE_ENV = "DAZ_LIVE_TESTS"
ALLOW_CLEAR_ENV = "DAZ_LIVE_ALLOW_CLEAR"

NOT_ENABLED_REASON = (
    f"live DAZ Studio test file: set {LIVE_ENV}=1 to run it (it changes the open scene)"
)

# Root nodes Studio creates for render settings; a scene holding only these is empty.
_SETTINGS_CLASSES = ("DzTonemapperNode", "DzEnvironmentNode")

_COUNT_USER_ROOTS = """(function(){
  var skip = %s, out = [];
  for (var i = 0; i < Scene.getNumNodes(); i++) {
    var n = Scene.getNode(i);
    if (n.getNodeParent()) continue;
    var settings = false;
    for (var j = 0; j < skip.length; j++) if (n.inherits(skip[j])) settings = true;
    if (!settings) out.push(n.getLabel());
  }
  return out;
})()""" % (list(_SETTINGS_CLASSES),)

_CLEAR = "(function(){ Scene.clear(); return true; })()"

_scene_owned = False  # pylint: disable=invalid-name


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip() == "1"


def live_enabled() -> bool:
    """True only when the user opted in with DAZ_LIVE_TESTS=1."""
    return _flag(LIVE_ENV)


def require_live(module_name: str = "") -> None:
    """Skip the calling module unless DAZ_LIVE_TESTS=1.

    Pass ``__name__``: a file run directly (``python tests/test_api.py``) is an
    explicit choice, so ``"__main__"`` goes ahead without the variable.
    """
    if module_name == "__main__":
        return
    if not live_enabled():
        raise unittest.SkipTest(NOT_ENABLED_REASON)


def _value(result):
    return getattr(result, "value", result)


def user_root_nodes(client) -> list:
    """Labels of the scene's root nodes, other than render-settings nodes."""
    return list(_value(client.execute(_COUNT_USER_ROOTS)) or [])


def clear_scene(client) -> None:
    """Scene.clear(), refusing (SkipTest) to wipe a scene the tests don't own.

    Raises ``unittest.SkipTest`` when this is the process's first clear, the
    scene has user content and DAZ_LIVE_ALLOW_CLEAR=1 is not set.
    """
    global _scene_owned  # pylint: disable=global-statement
    if not _scene_owned and not _flag(ALLOW_CLEAR_ENV):
        roots = user_root_nodes(client)
        if roots:
            shown = ", ".join(str(r) for r in roots[:5]) + (" ..." if len(roots) > 5 else "")
            raise unittest.SkipTest(
                f"refusing to clear a scene with content ({len(roots)} root nodes: {shown}). "
                f"Save your work, then set {ALLOW_CLEAR_ENV}=1 or open an empty scene."
            )
    client.execute(_CLEAR)
    _scene_owned = True


def scene_owned() -> bool:
    """True once clear_scene() has cleared the scene in this process."""
    return _scene_owned


def _reset_for_tests() -> None:
    global _scene_owned  # pylint: disable=global-statement
    _scene_owned = False
