Shot library
============

Common cinematic shots, coverage and continuity rules built on
:doc:`shots`. Every builder is pure: it takes actor root positions and returns
:class:`~dazpy.shots.Shot` / :class:`~dazpy.shots.CoveragePlan` models, which
:func:`~dazpy.shots.apply_shot` or :func:`~dazpy.shot_library.apply_coverage`
put into a scene.

.. code-block:: python

   from dazpy import shot_library as sl
   from dazpy.math3 import Vec3

   positions = {"anna": Vec3.from_dict(anna.position), "ben": Vec3.from_dict(ben.position)}
   line = sl.LineOfAction.between(positions, "anna", "ben", side=1)

   # Master, two-shot, OTS shot/reverse and clean singles, all on one side of the line
   plan = sl.dialogue_coverage(line)
   assert sl.check_plan(plan, positions) == []      # no camera crosses the 180-degree line
   cameras = sl.apply_coverage(scene, plan, subjects=positions)

   # Cut a conversation: one OTS per beat, frame ranges, gaze beats, dialogue text
   talk = sl.conversation(line, [sl.DialogueBeat("anna", 0, 47, "Where were you?"),
                                 sl.DialogueBeat("ben", 48, 95, "Out.")], establish_frames=24)

   # Moves and focus
   push = sl.push_in(positions, "anna", start=0, end=72, line=line)
   ots = sl.with_rack_focus(sl.over_the_shoulder(line, "ben", "anna"), "ben", "anna",
                            start=24, end=48, positions=positions, f_stop=2.0)

The **line of action** decides which side cameras stand on. Shot/reverse pairs
built on one line keep eyelines matched; :meth:`~dazpy.shot_library.LineOfAction.flipped`
gives the other side for a deliberate cross. :func:`~dazpy.shot_library.check_axis`
reports a camera (or a move, or an arc) on the wrong side, and
:func:`~dazpy.shot_library.check_thirty_degree` a jump cut between near-identical setups.

Shot ids come from :func:`~dazpy.shot_library.shot_name`
(``OTS_ben_over_anna``, ``SC3_012_CU_anna``) and are valid scene-recipe keys.
Static shots without ``distance_cm``/``anchor_cm`` convert to recipe cameras;
a two-shot of actors standing far apart, or a single with ``headroom=True``,
does not.

.. automodule:: dazpy.shot_library
   :members:
   :undoc-members:
   :show-inheritance:
