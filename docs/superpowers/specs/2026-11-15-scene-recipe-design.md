# Scene Recipe — Design

**Issue:** daz-script-server-5d6f.18 (ASSESSMENT #9) · **Date:** 2026-11-15
**Repos touched:** `daz-script-server` (dazpy + docs), `daz-mcp-server` (MCP tools)

## 1. Intent

Today the only way to build a scene through DazScriptServer is arbitrary
DazScript (inline or `.dsa`) or a sequence of imperative dazpy / MCP calls.
None of that can be validated before it runs, previewed, safely re-run, or
diffed.

A **scene recipe** is a versioned JSON document that declares what a scene
should contain — assets, actors and their placement/poses, lighting, cameras,
shots and render settings — plus five operations over it: **validate,
dry-run (plan), apply, observe, materialize (render)**.

**Primary author: an LLM, through the daz-mcp-server tools.** The expected
workflow is iterative: draft a recipe → apply → render → look → edit the recipe
(move a camera, swap a pose, brighten the key) → re-apply → render again. A
human may also nudge things by hand in the Daz Studio viewport between applies.
Every design choice below follows from those two facts.

## 2. Goals, non-goals, anti-goals

**Goals**
- A documented, versioned JSON schema that an LLM can fetch and follow. The
  canonical file lives at the repo root, `schemas/scene-recipe.v1.schema.json`,
  like `openapi.yaml`, so the TypeScript SDK (daz-ts) can validate against the
  same contract later. dazpy ships a copy as package data, and a unit test
  fails if the two differ. The apply engine itself is Python-only in v1.
- dazpy implements validate, plan, apply, observe, render.
- daz-mcp-server exposes each operation as an MCP tool.
- Re-apply is **incremental**: only what changed in the recipe changes in the
  scene.
- Hand tweaks are **never silently overwritten**; conflicts are surfaced and the
  caller chooses (see §5).
- An example recipe renders end to end (acceptance criterion).

**Non-goals for v1** (schema must leave room for each)
- Animated camera moves / keyframed blocking.
- Rich shot vocabulary — shot size/angle/eyeline models (5d6f.19), shot library
  and coverage patterns (5d6f.20).
- Asset search, compatibility checks, provenance (5d6f.21).
- Pre-render scene sanity checks — collisions, clipping, framing (5d6f.22).
- Migrating the existing keyword-template MCP tools (`daz_create_scene`,
  `daz_setup_shot_coverage`, …). They stay as they are; 5d6f.20 owns that.
- C++ server changes. Everything runs through existing script execution.

**Anti-goals** (failure even if it technically works)
- Apply that half-updates the scene and leaves it in an in-between state.
- Apply that silently overwrites a user's viewport tweak.
- Validation errors a model can't act on ("invalid recipe").
- Re-apply that reloads figures when only a camera moved.
- Recipes touching nodes they didn't create.

## 3. Constraints

- **Naming:** dazpy already has `InteractionRecipe` (`dazpy/_interaction.py`,
  multi-figure posing; `DazScene.apply_interaction_recipe`). The new type is
  **`SceneRecipe`**, in a new public module `dazpy/recipe.py` (private helpers in
  `dazpy/_recipe_*.py` as needed). Docs and tool names always say "scene recipe"
  where ambiguity is possible.
- **Units/axes:** DAZ native — centimetres, Y-up, degrees — matching the rest
  of dazpy.
- **Reuse existing dazpy primitives** for the actual scene mutations:
  `DazScene.load/create_camera/create_light`, `poses.apply_pose`,
  `cinematics.apply_frame_subject` / `apply_static_shot`,
  `lighting.apply_three_point_light_setup` / `apply_hdri_environment` /
  `set_light_color`, `render_api.render`. Extend them where a recipe needs
  something they lack rather than duplicating logic.
- **DS4 and DS6** must both work. Note the CRT rules (`feedback_crt_mismatch`,
  bd memory `ds4-qvariantlist-crt`) only matter if C++ changes; v1 has none.
- **Never trigger modal dialogs** from DazScript (e.g. bad map paths) — hangs
  the main thread. Validate file existence before calling into Studio.
- **Live testing:** never run the full `test_dazpy_integration.py` live; scope
  with `-k`. Use `tests/smoke_live.py` patterns for end-to-end checks.
- daz-mcp-server is currently on branch `land-phase4` with uncommitted files;
  MCP work goes on its own branch off that repo's default branch.

## 4. Schema (v1)

Top-level shape (illustrative; the JSON Schema file is the source of truth):

```json
{
  "recipe_version": 1,
  "id": "cafe-conversation",
  "assets": {
    "set":  { "path": "/Environments/Cafe/Cafe Interior.duf" },
    "g9":   { "path": "/People/Genesis 9/Genesis 9.duf" }
  },
  "actors": {
    "anna": { "asset": "g9", "position": [-60, 0, 0], "facing": "ben",
              "pose": "/Poses/Seated Talking 01.duf" },
    "ben":  { "asset": "g9", "position": [60, 0, 0], "rotation": [0, -90, 0],
              "pose": "/Poses/Seated Listening 02.duf" }
  },
  "props": {
    "cafe": { "asset": "set" }
  },
  "lighting": {
    "rigs":   { "main": { "type": "three_point", "target": "anna", "light_type": "spot",
                          "key": { "intensity": 120 } } },
    "lights": { "practical": { "type": "point", "position": [0, 180, -100],
                               "intensity": 40, "color": [255, 200, 150] } },
    "environment": { "type": "hdri", "image_path": "C:/HDRI/cafe.hdr", "intensity": 1.0 }
  },
  "cameras": {
    "wide":    { "frame": ["anna", "ben"], "shot_type": "full_body", "focal_length": 35 },
    "anna_cu": { "frame": "anna", "shot_type": "close_up", "azimuth_deg": 30, "focal_length": 85 },
    "manual":  { "position": [0, 160, 400], "look_at": [0, 120, 0], "focal_length": 50 }
  },
  "shots": [
    { "id": "wide",    "camera": "wide",    "output": "C:/renders/cafe/wide.png" },
    { "id": "anna_cu", "camera": "anna_cu", "output": "C:/renders/cafe/anna_cu.png",
      "render": { "resolution": [1080, 1350] } }
  ],
  "render": { "engine": "iray", "resolution": [1920, 1080], "iray_samples": 200 }
}
```

Rules:
- **Every addressable entity has a stable key** (actor/prop/camera/light/rig/
  shot id). Keys are the identity used for diffing and ownership — renaming a key
  means remove + add.
- `recipe_version` is required. dazpy rejects versions it doesn't know with a
  clear error. Additive optional fields don't bump the version; breaking changes
  do.
- **Unknown fields are errors** (`additionalProperties: false`), so typos from
  the model surface immediately.
- References (`asset`, `facing`, `target`, `frame`, `camera`) must resolve to keys
  in the same recipe.
- `facing` (actor key or `[x,y,z]`) and `rotation` are mutually exclusive.
  `facing` computes Y rotation only.
- Cameras: either *framing* (`frame` = actor key or list of keys, plus
  `shot_type` ∈ {close_up, medium, full_body}, `azimuth_deg`, `elevation_deg`)
  → `apply_frame_subject`, or *explicit* (`position` + `look_at`/`rotation`) →
  `apply_static_shot`. Common: `focal_length`, `depth_of_field`, `focal_distance`.
  Multi-subject framing frames the centroid; widening distance to fit all
  subjects is builder's call (see §9).
- Asset paths: content-library-relative (leading `/`, resolved through Daz's
  content manager) or absolute. v1 does existence checking only.
- `shots[].render` overrides top-level `render` per shot.
- The schema reserves (documents but rejects in v1) the keys later issues will
  fill: `shots[].movement`, `actors[].blocking`/`interaction`, `assets[].ref`
  (5d6f.21), `checks` (5d6f.22). Rejecting with a specific "not supported in
  recipe_version 1" error is better than a generic unknown-field error.

## 5. Ownership, last-applied state, and conflicts

### 5.1 Ownership
Apply only touches nodes it created. Each recipe-owned node carries a Daz
**element data item** (`DzElement.addDataItem` with a `DzSimpleElementData`,
which serializes into the `.duf`), holding:
- `recipe_id`, `entity_key` (e.g. `cameras.anna_cu`), `recipe_version`
- `last_applied`: the values apply last wrote for every property the recipe
  controls on that node (transform, focal length, light intensity/color, pose
  file path, …)

This makes ownership and hand-tweak detection survive save/reload. Nodes
without the tag are invisible to the recipe. For a loaded asset that creates
several nodes (a figure plus fitted items, or a set with many children), only
the root node(s) loaded for that entity are tagged.

**Render settings are render-time only.** Top-level `render` and
`shots[].render` are passed as arguments to `render_api.render()` for each shot.
Apply never writes them into the scene, so they aren't in the conflict model and
`render` doesn't need to save and restore anything.

**The HDRI environment is scene state.** Apply writes it, and its
`last_applied` lives in a scene-level data item (`DzScene.addDataItem` /
`DzSceneData`) under the same recipe id. `apply_hdri_environment` only works
under Iray, so `validate` rejects a recipe with `lighting.environment` unless
`render.engine` is `iray` (code `environment_requires_iray`). Apply never
switches the active engine as a side effect.

Data items aren't used anywhere in either repo yet. **The first implementation
task is a DS4 + DS6 spike** proving write → save → reload → read. If either
fails, fall back to a sidecar JSON next to the scene file (or, for an unsaved
scene, in the dazpy client's state dir), keyed by recipe id. The
ownership/conflict logic must not depend on which store is used.

One scene may host multiple recipes (distinct `recipe_id`s). A recipe never
touches another recipe's nodes.

### 5.2 Three-way comparison
For every controlled property, apply compares **desired** (recipe now),
**base** (`last_applied`), and **live** (read from the scene):

| recipe vs base | live vs base | Outcome |
|---|---|---|
| same | same | no-op |
| changed | same | apply change |
| same | changed | **hand tweak:** keep live value, emit warning |
| changed | changed | **conflict** (unless live already equals desired → no-op) |
| entity removed from recipe | node untouched | delete node |
| entity removed from recipe | node hand-tweaked | **conflict** |
| new entity | — | create |
| entity in base but node deleted by hand | — | **conflict** (recreate vs accept deletion) |

**Derived values (framing cameras, rigs, `facing`).** The three-way comparison
works on the **computed node values** (position, rotation, focal length,
intensity, …), not on the recipe spec, because spec fields like `shot_type`
can't be read back from a live node. "Desired" is computed from the
**recipe's** actor positions, never the live ones. So:
- moving `anna` in the recipe recomputes `anna_cu`, `wide` and `rigs.main`,
  and their computed values count as recipe changes;
- dragging `anna` in the viewport is a hand tweak on `anna` only. Cameras and
  lights that reference her don't move. `observe` reports her as drifted.
This keeps `plan` deterministic: it depends on the recipe and the base, not on
where things were nudged by hand.

**Poses.** After applying a pose, apply captures the figure's full pose with
`DazPose.capture()` (a sparse snapshot of bones, morphs and props) and stores it
in `last_applied`. Live is a fresh capture. Any channel that has drifted beyond
tolerance is a hand tweak on `actors.X.pose`. If the recipe also changes the
pose, that's a conflict, so hand posing is never silently overwritten under
`ask`. The conflict entry reports the pose file paths plus a short list of the
drifted channels, not the full snapshots.

**Foreign children.** If a recipe-owned node about to be deleted has
descendants that aren't recipe-owned (clothing or props the user parented to
it), that's a conflict of kind `has_foreign_children`. Resolving it in favour of
the recipe **unparents** those children to the scene root (preserving world
transform) and then deletes the recipe node. Apply never deletes a node it
didn't create.

Numeric comparisons use a tolerance (reuse `_DEFAULT_VERIFY_TOLERANCE` = 0.05
from `_scene_state.py` unless a property needs its own).

### 5.3 Conflict policy (caller-chosen, per call)
`apply(recipe, on_conflict="ask" | "recipe_wins" | "scene_wins", resolutions=None)`

- **`ask`** (default): if any conflict exists, **apply changes nothing at all**
  and returns every conflict. Apply is all-or-nothing in this mode.
- **`recipe_wins`** / **`scene_wins`**: resolve all conflicts that way, proceed,
  and report what was overwritten or kept.
- **`resolutions`**: `{"<path>": "recipe" | "scene"}` per-conflict choices,
  e.g. `{"lighting.rigs.main.key.position": "recipe", "actors.ben.pose": "scene"}`.
  Takes precedence over `on_conflict` for the paths it names. Under `ask`,
  any conflict not covered by `resolutions` still blocks the whole apply.

The point: an LLM can keep "always override", "always defer" or "ask me" as a
user preference in its memory and pass it on every call, or show the user the
conflicts and send back `resolutions`.

When `scene_wins` (or `"scene"`) keeps a hand tweak, `last_applied` for that
property is updated to the live value, so the tweak is no longer reported as a
warning on the next apply. A plain hand tweak (no conflict) keeps warning until
then. *(Builder's call — see §9 if this turns out noisy.)*

Each conflict entry: `{path, kind: "modified"|"removed_from_recipe"|"deleted_in_scene"|"has_foreign_children", desired, base, live}`.

### 5.4 Atomicity beyond conflicts
Conflict detection runs **fully before any mutation** (plan, then execute).

**If execution fails midway** (Studio error, missing file that passed
validation, Studio busy past retries), apply **really rolls back**, by
compensation. It does **not** rely on dazpy's `UndoGroup`: `cancelUndo()` in
`dazpy/_undo.py` only drops the undo grouping and leaves the changes in place,
and apply is many separate script calls anyway.

- Before each step, the plan already holds the step's prior live values (read
  during conflict detection) and the prior data-item payload.
- Apply keeps a journal of completed steps. On failure it walks the journal in
  reverse:
  - created nodes (including everything a `scene.load` added) are deleted;
  - deleted nodes can't be undeleted, so **deletions run last**, after every
    create and modify has succeeded. A failure during the deletion phase leaves
    only already-deleted nodes deleted, and the result says so;
  - modified properties are written back to their prior values (poses via
    `DazPose.apply_full` from the prior capture);
  - data items and scene-level data are restored to their prior payloads.
- The result reports `applied: false`, the failing step and error,
  `rolled_back: true`, and any compensation step that itself failed
  (`rollback_errors`). A failed compensation is the only way the scene can be
  left differing from its pre-apply state, and it is always reported.
- The rollback path gets its own unit tests (failure injected at each step type)
  and one live test (force a failure after a create + modify; scene matches a
  pre-apply `observe`).

## 6. Operations (dazpy API)

All live in `dazpy/recipe.py`. A `SceneRecipe` is a dataclass tree parsed from
JSON/dict (`SceneRecipe.from_dict / from_json / to_dict`). Functions take a
`DazScene` (or `DazClient` for render).

| Operation | Signature (sketch) | Touches Studio? | Returns |
|---|---|---|---|
| schema | `recipe_schema(version=1) -> dict` | no | JSON Schema |
| validate | `validate(recipe, scene=None) -> ValidationReport` | only if `scene` given (asset existence via content manager) | `{ok, errors[], warnings[]}` |
| plan (dry-run) | `plan(recipe, scene, on_conflict=..., resolutions=...) -> RecipePlan` | reads only | ordered steps + conflicts + warnings |
| apply | `apply(recipe, scene, on_conflict="ask", resolutions=None) -> ApplyResult` | yes | `{applied, steps[], conflicts[], warnings[], overwritten[], kept[]}` |
| observe | `observe(recipe, scene) -> ObserveReport` | reads only | per-entity drift: hand tweaks, missing nodes, conflicts-in-waiting |
| render (materialize) | `render(recipe, client, shots=None, wait=True) -> list[ShotRender]` | yes | per-shot `RenderResult` + artifact info |

Details:
- **Validation errors are model-actionable:** each has `path` (JSON pointer–ish
  dotted path, e.g. `cameras.anna_cu.shot_type`), `code` (stable string, e.g.
  `unknown_reference`, `invalid_enum`, `file_not_found`,
  `unsupported_in_version`), `message`, and where useful `allowed` /
  `suggestion` (closest key for a typo'd reference).
- `plan` against an empty scene lists a full build. Against a scene with prior
  applies, it is a diff ("camera anna_cu: position A → B; nothing else
  changes"). `apply` internally runs `plan` first. `plan`'s output for a given
  scene state is exactly what `apply` would do.
- `apply` with `on_conflict="ask"` and conflicts → `applied: false`, no
  mutation, conflicts listed.
- `render` refuses (structured error) if `observe` shows the recipe hasn't been
  applied or there are unresolved conflicts, unless `force=True`. Uses
  `render_api.render` per shot (camera by the recipe-owned camera's node name,
  engine, resolution, `iray_samples`). Output paths are absolute on the Studio
  host; parent dir is created if missing. Async/background rendering goes through
  the existing job/SSE machinery.
- Async variants in `dazpy/aio.py` follow the existing aio pattern
  (`_client_aio.py`, `_render_api_aio.py`).

## 7. daz-mcp-server

**Boundary.** All recipe logic (schema, validation, diff, conflicts, ownership
data) lives in dazpy. The MCP server only wraps it: no new embedded DazScript
goes into `_registry.py`. That follows ASSESSMENT.md's layering (MCP turns intent
into plans, dazpy owns domain primitives, the plugin executes). The wider
problem of the MCP server's ~106 embedded scripts duplicating dazpy is tracked
separately and isn't part of this work.

**Rename the existing tool.** `daz_materialize_recipe` (in `tools/workflow.py`)
runs a `.dsa`/`.ds` file as an async job and has nothing to do with scene
recipes. Rename it to **`daz_run_script_job`** with the same behaviour, and
update its docstring, the compact-profile help text, `SKILL_*.md`, README and
tests. No alias is kept, so it's a breaking change for anyone calling it by
name; record it in the MCP server's changelog/version bump.

New module `src/vangard_daz_mcp/tools/recipe.py`, registered like the others.
Each tool calls dazpy through `run_dazpy()` and maps errors via
`handle_dazpy_error()`. **All recipe tools are tagged for the `compact`
profile** (`tags=_DEFAULT_TAG`, as in `workflow.py`). The recipe is meant to be
the model's main way to build scenes, so it belongs in the default tool surface
alongside `daz_inspect_scene`, `daz_observe_job` and `daz_fetch_artifact`.

**The schema is an MCP resource, not a tool:** `daz://recipe/schema` (and
`daz://recipe/schema/{version}`), following the existing `daz://help/{topic}`
pattern, so it doesn't take up tool-selection context.

| Tool | Wraps |
|---|---|
| `daz_recipe_validate` | `validate(recipe, scene)` |
| `daz_recipe_plan` | `plan(...)` |
| `daz_recipe_apply` | `apply(..., on_conflict, resolutions)` |
| `daz_recipe_observe` | `observe(...)` |
| `daz_recipe_render` | `render(...)` |

Tool docstrings carry the workflow guidance for the model: validate → plan →
apply → render; how to read conflicts; how to pass `on_conflict` /
`resolutions`; that `on_conflict` is meant to reflect a user preference the
model should remember. Add a short `SKILL_RECIPE.md` alongside the existing
`SKILL_*.md` files describing the iterative loop. Bump the `dazpy>=` pin in
`pyproject.toml` to the dazpy release containing recipes (see Release in §8).

## 8. Docs, tests, acceptance

- **Docs:** `docs/` page for scene recipes (schema reference generated from or
  linked to the JSON Schema, operations, conflict model, worked example);
  `dazpy/ROADMAP.md` entry; README mention.
- **Example:** `docs/examples/recipes/` with at least one recipe that uses only
  content that ships with Daz Studio (Genesis 9 base figure, a default pose, no
  third-party set). This is the acceptance-test recipe.
- **Unit tests** (no Studio): schema validation (good + every error code),
  reference resolution, three-way diff table (every row of §5.2), policy and
  `resolutions` handling, atomic-ask behaviour, plan output stability. Use the
  existing mocked-client style in `tests/test_dazpy.py`.
- **Live tests** (scoped, `-k recipe`): data-item persistence spike; apply →
  modify recipe → re-apply touches only the changed node; hand-tweak → warning;
  hand-tweak + recipe change → conflict, each policy; remove entity → node
  deleted; end-to-end example renders a non-empty image on DS4 and DS6 (Iray at
  minimum; viewport/Filament where the smoke matrix supports it).
- **MCP tests:** tool registration + argument passthrough in daz-mcp-server's
  test style.
- **Release (last step of this work):** once dazpy and the docs are merged,
  cut a plugin + dazpy release with `./build.sh release vX.Y.0` (minor bump from
  the current 2.11.x; versions must stay in lockstep across plugin, dazpy and
  `openapi.yaml`). Then point daz-mcp-server's `dazpy>=` pin at it and bump the
  MCP server version (it also contains the breaking rename). **Ask the user
  before every push, tag, and release publish**, in both repos. Until the
  release exists, the MCP branch develops against the local dazpy checkout
  (editable install / uv path source), and that override is removed before the
  MCP PR merges.
- **Acceptance (from issue):** schema versioned + documented; dazpy implements
  validate/dry-run/apply; example recipe renders end to end. This design adds
  observe/render and the MCP tools to the same issue.

## 9. Calls made during design (not explicitly confirmed by the user)

- Name `SceneRecipe` / module `dazpy/recipe.py` (to avoid `InteractionRecipe`
  collision).
- JSON (not YAML) as the format; JSON Schema as the published contract.
- Ownership and `last_applied` stored in Daz element data items, sidecar file as
  fallback.
- Hand-deleted recipe nodes count as a conflict (recreate vs accept).
- Keeping a hand tweak via `scene_wins` adopts it into `last_applied`.
- `render` refuses on un-applied or conflicted recipes unless `force=True`.
- `facing` is yaw-only.
- Unknown fields are hard errors; reserved future fields get a dedicated error
  code.
- Derived cameras, rigs and `facing` are computed from the recipe's actor
  positions, and diffed on computed node values (§5.2).
- Pose hand tweaks are detected with a full `DazPose.capture()` snapshot; a pose
  swap after hand posing is a conflict.
- Deleting a recipe node that has user-parented children is a
  `has_foreign_children` conflict; the recipe winning unparents those children,
  never deletes them.
- Render settings are render-time arguments, not scene state. An HDRI
  environment requires `render.engine: iray` at validation.

## 10. Left to the builder

- Exact property set captured in `last_applied` per entity type (must cover
  every property the recipe can set).
- Multi-subject framing distance (centroid only vs widen to fit bounding boxes).
- Content-manager path resolution details and how loaded root nodes are
  identified after `scene.load` (node-list diff is fine).
- Internal step ordering in plans (assets → actors → props → lights → cameras →
  render settings is the natural order).
- Whether `validate` with a scene resolves assets in one batched script call.
- Data-item payload encoding (JSON string in a `DzSimpleElementData` value is
  the obvious choice).
