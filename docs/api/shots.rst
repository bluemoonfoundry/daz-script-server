Shots
=====

Typed, serialisable shot models -- :class:`~dazpy.shots.Shot`,
:class:`~dazpy.shots.Sequence` and :class:`~dazpy.shots.CoveragePlan` -- and
:func:`~dazpy.shots.apply_shot`, the single apply path the
:doc:`cinematics` builders are adapters over.

.. code-block:: python

   from dazpy.shots import CoveragePlan, Framing, Lens, RenderOutput, Sequence, Shot, apply_shot

   cu = Shot(id="anna_cu",
             camera=Framing(subjects=("anna",), size="close_up", angle="low",
                            composition="left_third"),
             lens=Lens(focal_length=85),
             output=RenderOutput(path="C:/renders/anna_cu.png"))
   apply_shot(scene, cu, subjects={"anna": scene.find_node("Genesis 9")})

   # Static shots drop straight into a scene recipe
   plan = CoveragePlan(id="cafe", subjects=("anna", "ben"), axis=("anna", "ben"),
                       sequences=(Sequence(id="talk", shots=(cu,)),))
   recipe = plan.merge_into_recipe(recipe)

Blocking beats, gaze beats, the lighting continuity key and storyboard notes
are planning data: they serialise and round-trip, but :func:`apply_shot` does
not apply them, and recipe conversion drops them. Camera movement and focus
pulls apply through :func:`apply_shot` but are not part of recipe_version 1.

.. automodule:: dazpy.shots
   :members:
   :undoc-members:
   :show-inheritance:
