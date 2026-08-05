"""Shared render helper for render_stage.py and render_shot.py.

Iray Canvas output has a confirmed live quirk in this DAZ Studio version:
when ``canvases_enabled`` is True, ``DazRenderSettings.render()``'s primary
saved image ends up containing the *last configured canvas's* content (e.g.
a surface-normal map) instead of the true composited beauty pass -- even
with an explicit "Beauty" canvas defined first. The canvas EXR files
themselves are written correctly regardless. Verified with
canvases_enabled=False alone producing a correct beauty render.

Workaround: render twice to the same output_path when canvases are
requested -- once with canvases enabled (writes correct AOV EXRs, corrupts
the primary PNG) and once immediately after with canvases disabled
(overwrites the corrupted PNG with the correct beauty composite; the
already-written canvas EXRs are untouched since no canvas processing runs
on the second pass). Doubles render time when AOVs are requested, but is
the only known way to get both a correct beauty image and correct AOVs out
of this DAZ Studio build.
"""
from __future__ import annotations


def render_beauty_and_canvases(rs, *, output_path: str, camera_label: str, canvases: tuple[str, ...]):
    """Render *output_path* from *camera_label*, working around the canvas quirk.

    Returns the :class:`~dazpy.RenderOutcome` from the pass that produced the
    final (correct) beauty image.
    """
    if not canvases:
        rs.canvases_enabled = False
        rs.output_path = output_path
        return rs.render(camera_label=camera_label)

    rs.canvases_enabled = True
    rs.output_path = output_path
    outcome = rs.render(camera_label=camera_label)
    if not outcome.success:
        return outcome

    rs.canvases_enabled = False
    rs.output_path = output_path
    return rs.render(camera_label=camera_label)
