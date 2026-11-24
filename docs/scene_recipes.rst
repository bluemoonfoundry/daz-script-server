Scene recipes
=============

A **scene recipe** is a versioned JSON document that declares what a DAZ Studio
scene should contain: assets, actors and their placement and poses, lighting,
cameras, shots and render settings. :mod:`dazpy.recipe` offers six operations
over it:

==============  =====================================================================
``validate``    check a recipe offline; with a scene, also check its files exist
``plan``        dry run: the steps, conflicts and warnings an apply would produce
``apply``       make the scene match the recipe, incrementally and safely
``observe``     how the scene differs from the recipe now (reads only)
``check``       pre-render checks: figures in frame, something lights the render
``render``      render the recipe's shots from an applied scene
==============  =====================================================================

Recipes are meant to be edited again and again: apply, render, look, change the
recipe, re-apply. Re-apply only changes what changed, and never silently
overwrites something you moved by hand in the viewport.

.. note::

   Scene recipes are unrelated to :class:`dazpy.InteractionRecipe` (multi-figure
   posing). Everything here is sync only: there are no ``dazpy.aio`` variants.
   Async callers, such as the MCP server, run these functions in a worker thread.

Units are DAZ native: centimetres, Y-up, degrees.

Quick start
-----------

.. code-block:: python

   import json
   from dazpy import DazScene
   from dazpy.recipe import validate, plan, apply, observe, render

   recipe = json.load(open("docs/examples/recipes/g9-portrait.json"))
   scene = DazScene()

   report = validate(recipe, scene)      # offline checks + files exist in Studio
   assert report.ok, report.errors

   print(plan(recipe, scene).steps)      # dry run
   result = apply(recipe, scene)         # build the scene
   shots = render(recipe, scene)         # one PNG per shot

Every function also accepts a :class:`dazpy._recipe_model.SceneRecipe`
(``SceneRecipe.from_dict`` / ``from_json`` / ``to_dict``). Offline-invalid
recipes make ``plan``, ``apply``, ``observe`` and ``render`` raise
:class:`dazpy.exceptions.RecipeValidationError` before the scene is touched.

Schema reference
----------------

The JSON Schema is ``schemas/scene-recipe.v1.schema.json`` at the repository
root (a byte-identical copy ships inside the package; get it with
``dazpy.recipe.recipe_schema()``). Unknown fields are errors, entity keys match
``^[A-Za-z0-9_-]{1,64}$``, and ``recipe_version`` must be ``1``. Actors and props
share one key namespace: a prop key that is also an actor key is a
``duplicate_key`` error (the schema cannot express this; ``validate`` checks it).

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Field
     - Meaning
   * - ``recipe_version``, ``id``
     - Required. ``id`` scopes ownership: nodes the recipe creates are labelled
       ``"<id>:<entity>"`` (rig lights ``"<id>:<rig>.<role>"``). Studio creates
       cameras and lights without a node name, so apply also names them after
       that label, with every character other than letters, digits and ``_``
       replaced by ``_``.
   * - ``assets.<key>.path``
     - A content-library path (leading ``/``, looked up in every Daz content
       directory, then tried as an absolute path for macOS) or an absolute path
       on the Studio host. v1 supports **single-root assets** only: an asset
       whose load adds more than one root node (some sets and scene subsets) is
       removed again and the apply fails with ``loads N root nodes``.
   * - ``actors.<key>``
     - ``asset`` (required), ``position``, ``rotation`` or ``facing`` (an actor
       key or ``[x, y, z]``; yaw only; not both), ``pose`` (a Daz pose preset,
       ``.duf`` / ``.dsf``, resolved like an asset path, or a dazpy pose
       ``.json`` file, which is read on the client machine).
   * - ``props.<key>``
     - ``asset``, ``position``, ``rotation``.
   * - ``lighting.rigs.<key>``
     - ``type: "three_point"``, ``target`` (actor or prop key), ``light_type``
       (``spot``, ``point``, ``distant``), and ``key`` / ``fill`` / ``rim``
       overrides: ``azimuth_deg``, ``elevation_deg``, ``distance``,
       ``intensity``, ``color``.
   * - ``lighting.lights.<key>``
     - ``type``, ``position`` (required), one of ``look_at`` / ``rotation``,
       ``intensity``, ``color`` (``[r, g, b]``, 0-255).
   * - ``lighting.environment``
     - HDRI: ``type: "hdri"``, ``image_path``, ``intensity``, ``rotation_deg``,
       ``mode``, ``draw_dome``. Needs ``render.engine`` to be ``iray``
       (``environment_requires_iray``). Scene state; the one thing besides nodes
       apply writes.
   * - ``cameras.<key>``
     - Either framing (``frame`` = actor key or list of keys, ``shot_type``,
       ``azimuth_deg``, ``elevation_deg`` *or* ``angle``, ``composition``) or
       explicit (``position`` plus ``look_at`` or ``rotation``). Common:
       ``focal_length``, ``depth_of_field``, ``focal_distance``. Framing
       assumes a standing human: each ``shot_type`` aims at a height above the
       actor's position and stands back so a height of subject fills the frame
       height at the camera's ``focal_length`` (Studio applies the 36 mm Frame
       Width to the frame height at any aspect, so the distance does not
       depend on the resolution). ``composition`` thirds use the frame width,
       which follows the recipe's ``render.resolution`` (4:3 if unset; a shot's
       own ``render`` override does not reframe its camera). Sizes (aim cm / fit cm): ``extreme_wide`` 90/600, ``wide``
       90/350, ``full_body`` 90/210, ``medium_wide`` 115/140, ``medium``
       130/100, ``medium_close_up`` 145/60, ``close_up`` 160/40,
       ``extreme_close_up`` 165/15. ``angle`` names the elevation
       (``eye_level`` 0, ``high`` 30, ``low`` -20, ``birds_eye`` 80,
       ``worms_eye`` -45 degrees); without it the elevation is
       ``elevation_deg`` (default 10). ``composition`` ``left_third`` /
       ``right_third`` turns the camera so the subject sits on that third.
       :mod:`dazpy.shots` builds these entries from typed
       :class:`~dazpy.shots.Shot` / :class:`~dazpy.shots.CoveragePlan` models.
       A framed prop is aimed at its position. Several framed subjects are
       framed at their centroid, without widening to fit them all. Rig lights,
       and an explicit camera's or light's ``look_at`` of an actor key, aim at
       the actor's chest (130 cm); a ``look_at`` of ``[x, y, z]`` is used as given.
   * - ``shots[]``
     - ``id``, ``camera``, ``output`` (absolute path on the Studio host; the
       folder is created), optional ``render`` override, optional
       ``allow_crop`` (``true``: the shot crops figures on purpose, so
       ``check`` skips its out-of-frame warnings).
   * - ``render``
     - ``engine`` (``iray``, ``filament``, ``viewport``), ``resolution``
       (``[w, h]``), ``iray_samples``. Used only at render time; never written
       into the scene, so it is not part of the conflict model.

References (``asset``, ``facing``, ``target``, ``frame``, ``camera``,
``look_at``) must resolve to keys in the same recipe. Keys reserved for later
versions (``shots[].movement``, ``actors[].blocking`` / ``interaction``,
``assets[].ref``, ``checks``) are rejected with ``unsupported_in_version``.

Validation errors are model-actionable: each has a dotted ``path`` (for example
``cameras.close_up.shot_type``), a stable ``code`` (``unknown_reference``,
``invalid_enum``, ``file_not_found``, ``unsupported_in_version``, ...), a
``message`` and, where useful, ``allowed`` values or a ``suggestion`` for a typo.

The iterative loop
------------------

1. **Draft** a recipe and ``validate(recipe, scene)``.
2. ``plan(recipe, scene)`` to preview. ``plan`` reads the scene and changes
   nothing; on an empty scene it lists a full build, on an applied scene only
   the difference.
3. ``apply(recipe, scene)``. It re-plans against the scene right then, so what
   runs is exactly what ``plan`` showed for that state.
4. ``render(recipe, scene)`` and look at the images.
5. **Edit** the recipe (move a camera, swap a pose, brighten the key) and go to 2.

``render`` refuses with :class:`dazpy.exceptions.RecipeNotAppliedError` (its
``report`` is the :class:`~dazpy.recipe.ObserveReport`) if the recipe was never
applied, has conflicts or unapplied changes, or a rendered shot's camera was
changed or deleted in the scene. Pass ``force=True`` to render anyway. Each shot
renders through the recipe's own camera node (found by its ownership record, so
renaming it in Studio is fine; normally labelled ``"<id>:<camera key>"``) with
the shot's ``render`` over the top-level ``render``; unset values use the
scene's defaults.

Pre-render checks
-----------------

``check(recipe, scene, shots=None)`` (and :meth:`dazpy.DazScene.check` for any
scene, recipe or not) runs one Studio script and returns a
:class:`dazpy.CheckReport`: ``ok`` (no errors) and ``findings``, each a
:class:`dazpy.CheckFinding` with ``severity`` (``error`` / ``warning``),
``code``, ``subject``, ``message``, ``camera``, ``shot`` and, for crops,
``sides``.

=========================  ========  ==========================================================
Code                       Severity  Meaning
=========================  ========  ==========================================================
``subject_out_of_frame``   warning   Part of a figure's bounding box is outside the shot's
                                     frame. ``sides`` lists the edges crossed (``top`` /
                                     ``bottom`` is usually a head or feet cut off; ``behind``:
                                     part of it is behind the camera). Skipped with
                                     ``allow_crop``.
``subject_not_in_frame``   warning   A figure is entirely outside the frame. Skipped with
                                     ``allow_crop``.
``no_subject_in_frame``    error     The scene has figures and the camera sees none of them.
``camera_not_found``       error     The shot's camera is not in the scene (apply first).
``no_light``               error     Nothing lights the render: no light is on, visible and
                                     above zero intensity, the environment is Scene Only or at
                                     intensity 0, and the camera headlamp is off. Not checked
                                     for the ``viewport`` engine. Reported once (``shot`` null)
                                     when every shot agrees.
=========================  ========  ==========================================================

Figures are the visible top-level figures (clothing and hair fitted to a figure
are skipped). Framing uses each shot's camera and resolution (the render
settings' aspect when the recipe sets none). The test is the figure's world
bounding box, which is loose: an outstretched arm can leave an empty box corner
outside the frame, so treat ``subject_out_of_frame`` as a prompt to look.
Emissive surfaces are not seen by ``no_light``.

To enforce the checks, pass ``require_clean=True``:

* ``apply(..., require_clean=True)`` checks every shot on the applied scene
  before the manifest is written. Errors roll the apply back like any other
  failure (``applied=False``, ``rolled_back=True``); ``ApplyResult.check`` has
  the report either way.
* ``render(..., require_clean=True)`` checks the shots it would render and
  raises :class:`dazpy.exceptions.SceneCheckError` (``report`` attribute) on
  errors, before rendering anything. It is independent of ``force``.

Warnings never block.

``observe`` reports ``applied`` (the recipe has a manifest in the scene),
``in_sync``, ``drift`` (hand edits kept, hand deletions), ``pending`` (what an
apply would change if the recipe won every conflict) and ``conflicts``.

What apply touches
------------------

Apply only touches nodes it created. Ownership and the last-applied state live
in a record stored on each owned node, plus one manifest per recipe in the
scene, so they survive save and reload. Nodes without a record are invisible to
the recipe, and one scene can host several recipes with different ids.

Changes are tracked per **channel** of an entity. Conflict, resolution and
warning paths are ``<entity path>.<channel>``:

=====================================  ==========================
Entity path                            Channels
=====================================  ==========================
``actors.<k>``                         ``transform``, ``pose``
``props.<k>``                          ``transform``
``cameras.<k>``                        ``transform``, ``optics``
``lighting.lights.<k>``                ``transform``, ``output``
``lighting.rigs.<rig>.<role>``          ``transform``, ``output``
``lighting.environment``               ``environment``
=====================================  ==========================

For example ``cameras.cu.transform`` or ``lighting.rigs.main.key.transform``.
Derived values (framing cameras, rigs, ``facing``) are computed from the
**recipe's** actor positions, never the live ones, and compared as computed node
values. Moving an actor in the recipe moves the cameras and lights that
reference it. Dragging her in the viewport is a hand tweak on that actor only.

A different asset or light type for an existing entity is a **replace**: the old
node goes through the same checks as a removal, then a new node is created. If
that check keeps the old node (``scene``), it stays in the scene but is
released: the recipe no longer owns it.

Conflict model
--------------

For every channel apply compares **desired** (the recipe now), **base** (what
the last apply recorded) and **live** (the scene now):

.. list-table::
   :header-rows: 1
   :widths: 30 20 50

   * - Recipe vs base
     - Live vs base
     - Outcome
   * - same
     - same
     - no-op
   * - changed
     - same
     - apply the change
   * - same
     - changed
     - hand tweak: keep the live value, warning ``hand_tweak_kept``
   * - changed
     - changed
     - conflict (no-op if live already equals desired)
   * - entity removed from recipe
     - untouched
     - delete the node
   * - entity removed from recipe
     - hand-tweaked
     - conflict ``removed_from_recipe``
   * - new entity
     - n/a
     - create
   * - recorded entity, node deleted by hand
     - n/a
     - conflict ``deleted_in_scene``

A node to be deleted that has children the recipe does not own (clothing or
props you parented to it) is a ``has_foreign_children`` conflict. Bones and the
parts the asset loaded with (a Genesis 9 figure's eyes, mouth, tear, lashes and
eyebrow cards) never count; an item parented to one of them does. If the recipe
wins, those children are unparented to the scene root (keeping their world
transform) and then the node is deleted. Apply never deletes a node it did not
create. A node is deleted the way Studio's **Delete** does it, together with
everything under it, so a node of this recipe that you parented under a deleted
one goes too (it is recreated on the next apply if the recipe still lists it).

Keeping a removed node (``scene`` on ``removed_from_recipe`` or
``has_foreign_children``) **releases** it: apply removes its ownership record
and drops it from the manifest, so the node stays in the scene as an ordinary,
unowned node and later applies no longer report it. It also loses the
``"<id>:"`` prefix of its label (``"<id>:ball"`` becomes ``"ball"``) unless you
renamed it, so a node the recipe creates for that entity later is the only one
with the recipe label (shot rendering finds cameras by it). To bring it back
under the recipe, delete it and add the entity again.

Poses are compared by a full pose capture, so a hand-posed figure is a hand
tweak, and a pose swap on top of it is a conflict.

If two nodes carry the same recipe record (duplicating a recipe node in Daz
Studio copies its record), the entity is a ``duplicate_record`` conflict and
warning naming both nodes and their element ids. Apply never modifies, deletes
or releases either node, whatever the policy: ``ask`` blocks, and
``recipe_wins`` / ``scene_wins`` / ``resolutions`` cannot resolve it (the rest
of the apply proceeds under those policies). Delete the extra node to resolve
it.

Numeric comparisons use a tolerance of 0.05.

Choosing a policy
~~~~~~~~~~~~~~~~~

.. code-block:: python

   result = apply(recipe, scene)                         # on_conflict="ask"
   if not result.applied and result.conflicts:           # nothing was written
       for c in result.conflicts:
           print(c.path, c.kind, c.desired, c.base, c.live)

   apply(recipe, scene, on_conflict="recipe_wins")       # overwrite hand edits
   apply(recipe, scene, on_conflict="scene_wins")        # keep hand edits

   apply(recipe, scene, resolutions={                    # per conflict
       "lighting.rigs.main.key.transform": "recipe",
       "actors.model.pose": "scene",
   })

- ``ask`` (default): any conflict means **nothing changes** and every conflict is
  returned (``applied`` is ``False``).
- ``recipe_wins`` / ``scene_wins`` resolve every conflict that way and report
  ``overwritten`` and ``kept`` paths.
- ``resolutions`` maps a conflict path to ``"recipe"`` or ``"scene"`` and wins
  over ``on_conflict`` for the paths it names; under ``ask`` an unnamed conflict
  still blocks the apply. A key matching no conflict yields an
  ``unknown_resolution`` warning.

Keeping a hand tweak with ``scene`` adopts the live value as the new base, so it
stops warning. A plain hand tweak keeps warning until then.

Tombstones and warnings
~~~~~~~~~~~~~~~~~~~~~~~

Accepting a hand deletion (resolution ``scene`` on ``deleted_in_scene``) records
a tombstone in the manifest, so later applies do not recreate the node and
instead warn ``hand_deleted_kept``. Resolve that path with ``recipe`` to bring
it back. Other warning codes: ``hand_tweak_kept``, ``duplicate_record``, ``removed_entity_kept`` (an
entity removed or replaced in the recipe whose node was kept and released),
``unknown_resolution`` and
``deleted_not_restored`` (see below).

Selection and a busy Studio
---------------------------

Apply clears the scene selection while it loads assets and deletes nodes:
loading a figure while another figure is selected makes Studio ask whether to
replace it, and deleting goes through Studio's Delete on an exact selection.
The selection is not restored afterwards.

Studio 6 reports itself busy for a moment after a load or a clear while it
streams in background content. Every ``dazpy.recipe`` function waits that out,
up to 120 seconds per call, through
:meth:`DazClient.waiting_out_busy() <dazpy.DazClient.waiting_out_busy>`; use the
same context manager around your own calls between recipe steps.

Rollback guarantees
-------------------

Conflict detection runs completely before any change. If execution then fails
midway (a Studio error, a file that passed validation but cannot load, Studio
busy past its retries), apply rolls back by compensation. dazpy's ``UndoGroup``
cannot do this: it only drops the undo grouping.

- Work is journaled. On failure the journal is walked in reverse: created nodes
  (including everything a load added) are deleted, modified channels are written
  back to their prior values (a write that fails halfway is restored too), the
  environment and records are restored (including records removed by a
  release), unparented children are reparented.
- Deletions and unparenting run **last**, after everything that can still fail,
  because a deleted node cannot be brought back. A failure in that phase leaves
  the deletes already done in place; ``result.steps`` lists them and each carries
  a ``deleted_not_restored`` warning.
- The manifest is written last.
- The result then has ``applied=False``, ``rolled_back=True``, ``failed_step``
  and ``error``. A compensation that itself fails is never raised; it is listed
  in ``rollback_errors``, and is the only way the scene can end up different from
  before the apply.
- One known case cannot be restored. If an apply sets an HDRI environment map on
  a scene that had none and later fails, the map cannot be cleared again:
  dazpy never calls the map setters with an empty path, since a bad map path can
  raise a modal dialog and hang Studio. The rollback reports
  ``environment map could not be restored: the scene had no map before`` in
  ``rollback_errors``.

Example walkthrough
-------------------

``docs/examples/recipes/g9-portrait.json`` uses the Genesis 9 base figure, one
of Daz's stock Genesis 9 base poses (``G9 Base Pose 12 Standing``), a three-point
rig, a full-body and a close-up camera, two shots and Iray at 640x480 with 50
samples. It has no ``environment`` block, so it needs no third-party HDRI.

.. literalinclude:: examples/recipes/g9-portrait.json
   :language: json

File checks run on the Studio host (one script for the whole recipe), so paths
are always as Studio sees them. The one exception is a dazpy pose ``.json``
file: dazpy reads it on the client, so ``validate`` checks it there.

A session against a running Studio:

.. code-block:: python

   recipe = json.load(open("docs/examples/recipes/g9-portrait.json"))
   scene = DazScene()

   apply(recipe, scene)                 # figure, pose, 3 lights, 2 cameras
   render(recipe, scene)                # C:/temp/recipe_example/*.png

   # Move the close-up around the figure. Only cameras.close_up changes.
   recipe["cameras"]["close_up"]["azimuth_deg"] = 45
   print(plan(recipe, scene).steps)     # one modify on cameras.close_up
   apply(recipe, scene)

   # Nudge the key light by hand in the viewport, then re-apply: the tweak is
   # kept and reported as a hand_tweak_kept warning.
   result = apply(recipe, scene)
   print([w.code for w in result.warnings])

   # Change that light in the recipe too: now it is a conflict.
   recipe["lighting"]["rigs"]["main"]["key"] = {"azimuth_deg": 60}
   apply(recipe, scene)                                  # applied=False
   apply(recipe, scene, on_conflict="recipe_wins")       # applied=True

If that pose is not installed, ``validate(recipe, scene)`` reports
``file_not_found`` with its path; point ``actors.model.pose`` at any installed
Genesis 9 pose.

API
---

.. automodule:: dazpy.recipe
   :members: validate, plan, apply, observe, render, recipe_schema, ObserveReport, ShotRender

Results
~~~~~~~

.. autoclass:: dazpy._recipe_validate.ValidationReport
   :members:

.. autoclass:: dazpy._recipe_validate.RecipeIssue
   :members:

.. autoclass:: dazpy._recipe_diff.RecipePlan
   :members:

.. autoclass:: dazpy._recipe_diff.Step
   :members:

.. autoclass:: dazpy._recipe_diff.Conflict
   :members:

.. autoclass:: dazpy._recipe_apply.ApplyResult
   :members:

.. autoclass:: dazpy._recipe_model.SceneRecipe
   :members: from_dict, from_json, to_dict
