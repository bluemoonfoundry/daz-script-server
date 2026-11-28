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
``^[A-Za-z0-9_-]{1,64}$``, and ``recipe_version`` must be ``1`` (``2`` for the
v2 schema, ``schemas/scene-recipe.v2.schema.json``, which adds the fields in
`Recipe version 2: asset references, compatibility and fitting`_). Actors and props
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

Recipe version 2: asset references, compatibility and fitting
-------------------------------------------------------------

``recipe_version: 2`` (schema ``schemas/scene-recipe.v2.schema.json``,
``recipe_schema(2)``) adds four things to v1:

- name content by path, product, SKU or search phrase (**asset references**);
- check every preset and fitted item against its figure **before the scene
  changes**;
- build actors in layers (base figure, then presets, then fitted items) and
  **take over** actors built by hand;
- **add, replace and remove** hair, clothing and accessories fitted to an actor,
  by Scene-pane label or by content type.

Every loaded node also records where it came from. Each validation,
compatibility or wearing error raises before apply changes anything: an
ambiguous, missing or incompatible reference leaves the scene exactly as it was,
and no modal dialog can appear.

Asset references
~~~~~~~~~~~~~~~~

Anywhere a recipe takes an asset (``assets.<k>``, ``actors.<k>.asset``,
``props.<k>.asset``, ``presets[]`` and ``wearing`` entries), v2 accepts an
**asset reference** (shared schema ``schemas/asset-ref.v1.schema.json``, also
emitted by daz-content-browser-mcp). A plain string is a path, so every v1 asset
value is still valid. The object form has these fields:

============  ==============================================================================
Field         Meaning
============  ==============================================================================
``path``      Content-relative (``/People/...``) or absolute file path
``product``   Product name (exact, case-insensitive)
``sku``       Product SKU
``find``      Free-text search phrase
``file``      Picks one file of a ``product`` / ``sku``: content-relative path or file name
``type``      Expected content type (friendly name or raw Daz type, see below). It narrows a
              search and filters a product's files
``resolved``  A **pin**: ``{path, sku?, product?, asset_id?}`` from an earlier resolution
============  ==============================================================================

At least one of ``path``, ``product``, ``sku`` and ``find`` is required, even
with a pin, so a reference always says what was meant. When several are given,
``path`` wins over ``sku`` (plus ``file``), then ``product`` (plus ``file``), then ``find``.
A product with several matching files and no ``file`` is ambiguous.

A ``resolved`` pin is used as is while its file still exists on the Studio
host (finder ``pin``). If the file is gone, the reference resolves again from its
other fields (warning ``pin_file_missing``). A pin whose SKU or product differs
from the reference's warns ``pin_mismatch``. ``dazpy.recipe.pin(recipe, scene)``
returns the recipe as a dict with every reference's ``resolved`` filled in, so
you can freeze a recipe against library changes. dazpy never rewrites a recipe on
its own.

**Stability:** once a reference resolves, the file is stored in the node's
record. Later applies reuse it while the reference is unchanged (no new
search), so installing a new product never silently swaps content. A changed
reference resolves again.

Finders
~~~~~~~

``find``, ``product`` and ``sku`` are answered by a **finder** (``path``
references never use one):

- :class:`dazpy.StudioFinder`, the default: Studio's own content database
  (needs the CMS). Studio searches asynchronously; dazpy waits until the result
  stops growing, at most 5 seconds. When that bound is hit, the partial result
  is still used and the reference gets ``search_incomplete``. A search with no hit
  takes about 3 seconds to come back empty. Studio returns at most 1200 results.
- :class:`dazpy.ContentBrowserFinder`: the daz-content-browser REST API, from
  ``DAZ_BROWSER_URL`` (and ``DAZ_BROWSER_TOKEN``) or constructed explicitly.

Pass ``finder=`` to ``validate`` / ``plan`` / ``apply`` / ``observe`` /
``pin`` to choose. Otherwise dazpy uses the content browser when
``DAZ_BROWSER_URL`` is set and reachable, and Studio's database when it is not
(warning ``finder_fallback``). ``RecipePlan.finder`` names the finder that
answered.

**Choosing a match.** A ``find``'s candidates are first filtered by ``type``,
then by the target figure: a candidate whose compatibility metadata says it is
made for another figure is dropped (one with no metadata stays). The figure is
the actor's live figure, or the figure file of an actor the recipe will create.
A result is then accepted only when it is a clear single winner: one candidate
whose product name equals the phrase (case-insensitive), or exactly one
candidate left. Several left is ``ambiguous_asset``: for a ``find`` the
error's ``allowed`` lists up to ten as ``"<product> (<sku>): <path>"``; for a
``product`` / ``sku`` with several matching files it lists the file paths.
When every candidate was dropped as incompatible the error is
``incompatible_asset``, naming the best of them, not ``asset_not_found``. Studio's text search matches broadly. On a
typical library a phrase such as ``"Flirty Casual Ponytail"`` with ``type:
"hair"`` returns several ponytail hairs, not just that one. **Expect a ``find``
to come back ambiguous: pick one of the listed candidates and pin it**, either
with ``pin()`` or by writing its path into ``resolved`` (or using it as ``path``).

Content types
~~~~~~~~~~~~~

``type`` in a reference or a selector is a friendly name or a raw Daz type
string, which matches as a prefix (``Follower/Wardrobe/Gloves``):

=============  ======================================================================
Friendly name  Daz type prefixes
=============  ======================================================================
``hair``       ``Follower/Hair``
``top``        ``Follower/Wardrobe/Shirt``, ``Follower/Wardrobe/Outerwear/Top``
``bottom``     ``Follower/Wardrobe/Pant``, ``Follower/Wardrobe/Skirt``,
               ``Follower/Wardrobe/Outerwear/Bottom``
``dress``      ``Follower/Wardrobe/Dress``
``outerwear``  ``Follower/Wardrobe/Outerwear``
``shoes``      ``Follower/Wardrobe/Footwear``, ``Follower/Wardrobe/Shoes``
``hat``        ``Follower/Wardrobe/Headwear``
``accessory``  ``Follower/Accessory``
``wardrobe``   ``Follower/Wardrobe``
=============  ======================================================================

A wearables (outfit) preset file has the type ``Preset/Wearables``. When
filtering files, it matches only ``wardrobe`` (or raw ``Follower/Wardrobe``),
never a narrow name such as ``hat``. Scene nodes are matched by their own type,
so ``{"type": "hat"}`` finds the hat inside a hand-loaded outfit. A node with no
type never matches a type selector.

Actors in layers
~~~~~~~~~~~~~~~~

An actor gains ``node``, ``presets`` and ``wearing``. It needs ``asset``,
``node`` or both.

- ``node`` is a Scene-pane **label** (exact, case-sensitive). If one figure has
  that label, the actor **takes it over**. The recipe then manages only what it
  mentions: its presets, its ``wearing`` entries, and transform or pose only if
  the recipe sets them (a taken-over actor has no implicit ``position``). The
  base figure is never replaced. Changing ``asset`` on a taken-over actor is a
  ``take_over_asset_changed`` error, and dropping the actor from the recipe
  *releases* it (removes its record); it is never deleted. After take-over the
  actor is found by its record, so renaming it later is fine.
- With ``node`` but no such figure, the actor is created from ``asset`` and
  labelled ``node``. Without an ``asset`` that is ``node_not_found``. Two figures
  with the label are ``ambiguous_node``.
- ``presets`` are applied in order to the figure (shape, materials, ...) on
  create, on take-over and whenever the list changes. Presets cannot be undone,
  so dropping one leaves its effect on the figure (warning ``preset_dropped``).

Fitted items
~~~~~~~~~~~~

``wearing`` is an ordered list of entries:

.. code-block:: json

   [
     {"add": {"product": "dForce Detective Outfit for Genesis 9", "type": "wardrobe"},
      "key": "outfit"},
     {"replace": {"type": "hair"}, "key": "hair", "with": {"sku": "93669"}},
     {"replace": "Old Jacket", "key": "jacket", "with": {"product": "Leather Jacket"},
      "if_missing": "add"},
     {"remove": {"type": "hat"}, "if_missing": "ignore"}
   ]

- ``add`` (with a ``key``) is an **owned** item: like any recipe entity it is
  created once, compared on every apply and removed when the entry goes.
  Changing its reference swaps it. The key is unique within the actor.
- ``replace`` (selector, ``with``, ``key``) and ``remove`` (selector) act on
  content the recipe does **not** own. A selector is a label string or
  ``{"type": T}`` (every matching item fitted to this actor). On the first apply the
  selector must match at least one item, else ``replace_target_missing`` /
  ``remove_target_missing``. ``"if_missing": "add"`` turns a replace into a
  plain add, and ``"if_missing": "ignore"`` skips a remove. The selector part is
  **one-shot**: it runs once, is logged on the actor's record and is inert
  after that. The ``with`` item is owned under ``key`` like an ``add``. A
  ``remove`` is logged by its selector (``remove.type=hat``,
  ``remove.label=Old Jacket``), so reordering the ``wearing`` list never
  re-arms it.
- Only items following this actor's figure are candidates; never the figure,
  never another actor's items, never items this recipe owns. Removing them is
  not a conflict under ``ask`` (the recipe asked for it), except for an item
  carrying another node you parented to it, with or without a record
  (``has_foreign_children``; only the item's own bones, fitted sub-parts and
  outfit helper nodes do not count). Entries are planned in list order, each
  seeing the scene as the earlier ones leave it.
- Figures and items the recipe did not create are addressed by Studio's
  element ID, not their internal name (a file loaded twice repeats every
  name), so a plan's ``take_over`` / ``unfit`` steps name them as
  ``elementID:<id>``. Each removed item must still follow the actor's figure
  when the removal runs.
- **Multi-node items.** A hair with a separate cap, or an outfit preset that
  loads six garments, is one entry: every node the load added belongs to it
  (records share ``group`` = ``"<actor>.<key>"``) and is fitted, swapped and
  removed together. A load that adds anything not fitted to the actor (a light,
  a stray figure) is removed again and fails.
- Fitting loads the file with a temporary empty null node selected as the
  only (primary) selection: some items name the selection in their file, and
  with nothing selected Studio can pop its modal "Choose Content to Replace"
  dialog. Each new figure is then made to follow the actor and parented to her,
  and the null is deleted. Items for another figure are never auto-fitted.

Apply order is: creates, presets, fits, channels, then removals **last**. A
failure before the removals rolls everything back, so a hand-loaded hair being
replaced is simply still there. The exception is presets: a preset applied to
a figure the recipe did not create in this apply (an existing or taken-over
actor) cannot be undone, and the rollback reports it in ``rollback_errors``. A failure *during* the removals reloads the
items already removed from their recorded source file and fits them again
(their hand edits are lost). Hand-loaded content has no record, so it cannot
be reloaded. The dry run warns ``unrestorable_removal`` for it, and rollback skips it;
after a rollback, every removed item that was not brought back (no source, or
the reload failed) is reported again as ``unrestorable_removal``, and its
``unfit`` step stays in ``ApplyResult.steps``.

Plan steps for v2: ``take_over``, ``preset``, ``fit`` and ``unfit`` (the
one-shot removal), next to v1's ``create`` / ``modify`` / ``delete`` / ``release``.

Compatibility
~~~~~~~~~~~~~

Before any scene change, every preset and fitted item is checked against its
actor's figure, from asset metadata only (nothing is loaded to find out). The
actor's base comes from the live figure for a taken-over or existing actor
(``getCompatibilityBasePathForNode``), and from the figure file's CMS record
(``compatibilityBase``) for one the recipe will create. The item's bases come
from its CMS record. An item is compatible when the actor's base equals one of
them or lies below it (``/Genesis 9/Base`` is below ``/Genesis 9``). Otherwise it is
``incompatible_asset``. No metadata (for example your own shape file outside the
CMS) gives the warning ``compatibility_unknown``, so project files keep working.

Provenance
~~~~~~~~~~

Every node a v2 recipe loads carries ``source`` in its record:

.. code-block:: json

   {"requested": {"sku": "93714", "file": "Kara Ponytail.duf"},
    "path": "X:/Daz Libraries/People/Genesis 9/Hair/Daz Originals/Kara Ponytail/Kara Ponytail.duf",
    "sku": "93714", "product": "dForce Kara Ponytail for Genesis 9",
    "type": "Follower/Hair", "finder": "studio",
    "fitted_to": "abby", "group": "actors.abby.wearing.hair", "primary": true}

``finder`` is ``path``, ``pin``, ``studio`` or ``content_browser``. Fitted
nodes also record ``asset_uri``, the node's data (``.dsf``) file at fit time.
``observe`` reports an owned item whose live data file differs from it as
``source_changed`` drift (swapped by hand). A taken-over actor's record has
``adopted_from_scene: true``. One-shot removals are logged on the actor's record
with each removed item's label, type and source file.

Codes
~~~~~

Errors (``plan`` / ``apply`` raise :class:`~dazpy.exceptions.RecipeValidationError`
before any change). ``validate`` with a scene reports the reference and
compatibility errors; ``ambiguous_node``, ``node_not_found``,
``take_over_asset_changed``, ``replace_target_missing`` and
``remove_target_missing`` need the scene's figures and fitted items, so only
``plan`` / ``apply`` report them:

=================================  ===================================================================
Code                               Meaning
=================================  ===================================================================
``invalid_asset_ref``              A reference names none of ``path`` / ``product`` / ``sku`` /
                                   ``find``, or has a ``resolved`` pin without ``path``. Also a
                                   preset whose file is a figure, hair / clothing, outfit preset or
                                   prop (by its CMS content type): use ``asset`` / ``wearing``.
``asset_not_found``                The path does not exist on the Studio host, the search found
                                   nothing, or the product has no matching file.
``ambiguous_asset``                Several files match. ``allowed`` lists them (``find``:
                                   ``"<product> (<sku>): <path>"``; ``product`` / ``sku``: paths).
                                   Add ``file`` / ``type`` or pin one. A ``find`` whose search
                                   was cut off (100 candidates, or Studio's cap) never picks one
                                   of several, even after compatibility narrowing.
``content_database_unavailable``   A ``find`` / ``product`` / ``sku`` needs Studio's content
                                   database (CMS) and it is not running. Paths still work.
``incompatible_asset``             A preset or fitted item is made for another figure; the message
                                   names its bases and the actor's base. Also when every ``find``
                                   candidate is made for another figure (``allowed`` lists them).
``ambiguous_node``                 Several figures carry the actor's ``node`` label (even when they
                                   also share an internal name).
``node_not_found``                 No figure has the ``node`` label and the actor has no ``asset`` to
                                   create it from (``suggestion``: a near label).
``take_over_asset_changed``        The ``asset`` of a taken-over actor changed; the base figure is
                                   never replaced. Adding a ``resolved`` pin is not a change.
``replace_target_missing``         A ``replace`` selector matches nothing on its first apply.
``remove_target_missing``          A ``remove`` selector matches nothing on its first apply.
=================================  ===================================================================

Warnings (never block):

=========================  =========================================================================
Code                       Meaning
=========================  =========================================================================
``compatibility_unknown``  No metadata to check an item against the figure (or the actor's base is
                           unknown, or a preset's file has no content type); it is loaded
                           unchecked.
``pin_mismatch``           A ``resolved`` pin's SKU or product differs from the reference's; the pin
                           is used.
``pin_file_missing``       The pinned file is gone; the reference was resolved again.
``finder_fallback``        ``DAZ_BROWSER_URL`` is set but the content browser is unreachable;
                           Studio's database answered.
``search_incomplete``      Studio's search hit its time bound (5 s); the match was chosen from a
                           possibly partial result.
``similar_node_label``     No figure has the ``node`` label but one is close (``suggestion``); the
                           actor will be created. Labels match exactly.
``unrestorable_removal``   An item a ``replace`` / ``remove`` will delete has no recorded source
                           (hand-loaded), so a failure during removal cannot bring it back. After a
                           rollback: an item that was removed and not restored.
``preset_dropped``         A preset was removed from the list; its effect stays on the figure.
=========================  =========================================================================

Plus the drift code ``source_changed`` from ``observe`` (see Provenance).

Worked example: Abby
~~~~~~~~~~~~~~~~~~~~

Load a Genesis 9 figure and name it "Abby", apply her shape, give her a
ponytail:

.. code-block:: json

   {
     "recipe_version": 2,
     "id": "vn-a",
     "actors": {
       "abby": {
         "node": "Abby",
         "asset": {"path": "/People/Genesis 9/Genesis 9.duf"},
         "presets": ["X:/Development/VisualNovelA/shapes/AbbyYoungShape.duf"],
         "wearing": [
           {"add": {"find": "Flirty Casual Ponytail", "type": "hair"}, "key": "hair"}
         ],
         "position": [0, 0, 0]
       }
     }
   }

.. code-block:: python

   from dazpy import DazScene
   from dazpy.exceptions import RecipeValidationError
   from dazpy.recipe import apply, pin, plan, validate

   scene = DazScene()
   report = validate(recipe, scene)
   for e in report.errors:          # typically: ambiguous_asset on actors.abby.wearing.hair
       print(e.path, e.code, e.allowed)

The shape file is the user's own (not in the CMS), so it warns
``compatibility_unknown`` and is still applied. The ``find`` usually lists
several ponytails. Pick the one you mean and pin it:

.. code-block:: json

   {"add": {"find": "Flirty Casual Ponytail", "type": "hair",
            "resolved": {"path": "/People/Genesis 9/Hair/Out Of Touch/OOT Flirty Casual Ponytail Hair/Flirty Casual Ponytail Hair.duf"}},
    "key": "hair"}

Now ``apply(recipe, scene)`` creates the figure labelled ``Abby``, applies the
shape, and loads and fits the hair. Re-applying changes nothing.

**Later: change her hair, on a scene where Abby was built by hand.** A recipe
that only names her takes her over and swaps whatever hair she has:

.. code-block:: json

   {
     "recipe_version": 2,
     "id": "vn-a-hair",
     "actors": {
       "abby": {
         "node": "Abby",
         "wearing": [
           {"replace": {"type": "hair"}, "key": "hair",
            "with": {"find": "Bunched Hair Updo", "type": "hair"}}
         ]
       }
     }
   }

``plan`` shows ``take_over``, ``fit`` and ``unfit`` steps and warns
``unrestorable_removal`` for her hand-loaded hair. ``apply`` fits the new hair,
then removes the old one. Her shape, pose, position and everything else she
wears are left alone. On the next apply the replace is inert; to change the
hair again, edit ``with``. Had the new hair been made for Genesis 8, the plan
would have stopped with ``incompatible_asset`` and nothing would have loaded.

v1 to v2
~~~~~~~~

- v1 recipes keep working unchanged, with exactly the v1 behaviour: no finder,
  no compatibility read.
- To use any v2 field, set ``"recipe_version": 2``. String asset values still
  mean a path and ``assets`` keys still work. Under v2 an inline asset path is
  resolved (and existence-checked) like any reference, reported at the
  reference's own path (``actors.<k>.asset``) rather than as ``file_not_found``.
- ``pin()`` on a v1 recipe returns a v2 recipe.
- The v1 validator rejects v2 fields (``unknown_field``), so a recipe that uses
  them must say ``2``.

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
   :members: validate, plan, apply, observe, render, pin, recipe_schema, ObserveReport, ShotRender

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

Asset references and finders
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``AssetRef``, ``AssetFinder``, ``StudioFinder`` and ``ContentBrowserFinder``
are importable from ``dazpy``. Pass a finder as ``finder=`` to ``validate``,
``plan``, ``apply``, ``observe``, ``render`` or ``pin``; without one, dazpy
uses daz-content-browser when ``DAZ_BROWSER_URL`` answers and Studio's
content database otherwise (``finder_fallback`` warning).

.. autoclass:: dazpy._asset_ref.AssetRef
   :members:

.. autoclass:: dazpy._asset_ref.ResolvedPin
   :members:

.. autoclass:: dazpy._asset_finder.AssetFinder
   :members:

.. autoclass:: dazpy._asset_finder.AssetCandidate
   :members:

.. autoclass:: dazpy._asset_finder.StudioFinder
   :members: search, product_files

.. autoclass:: dazpy._asset_finder.ContentBrowserFinder
   :members: search, product_files
