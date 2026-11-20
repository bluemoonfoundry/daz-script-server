# Scene Recipe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add versioned, declarative scene recipes to dazpy (validate / plan / apply / observe / render with incremental re-apply, hand-tweak conflicts and real rollback), expose them as compact-profile MCP tools in daz-mcp-server, and ship a release.

**Architecture:** Pure layers first, Studio-touching layers last. Model and validation are pure. Desired-state computation is pure. The three-way diff is pure and does nothing but produce a `RecipePlan`. A `SceneOps` adapter is the only code that talks to Studio. The executor runs a plan through `SceneOps` with a journal and compensating rollback. `dazpy/recipe.py` is the public facade. The MCP server only wraps the facade.

**Tech Stack:** Python ≥3.10, dazpy (sync `DazClient`/`DazScene`), DazScript element/scene data items, JSON Schema draft 2020-12 (`jsonschema` as a test-only dependency), unittest + pytest; daz-mcp-server: FastMCP ≥3, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-11-15-scene-recipe-design.md`. Read it before any task.

## Global Constraints

- Type name `SceneRecipe`; public module `dazpy/recipe.py`; private helpers `dazpy/_recipe_*.py`. Don't reuse the names `ValidationIssue` or `LightSpec` (already exported by dazpy).
- DAZ units: centimetres, Y-up, degrees.
- `recipe_version` is `1`. Unknown fields are errors. Entity keys match `^[A-Za-z0-9_-]{1,64}$`.
- Numeric tolerance `0.05` (`_DEFAULT_VERIFY_TOLERANCE` in `dazpy/_scene_state.py`, import it, don't redefine it).
- dazpy runtime dependencies stay `requests` only. `jsonschema` is test-only.
- Canonical schema at `schemas/scene-recipe.v1.schema.json`, plus a byte-identical copy at `dazpy/schemas/scene-recipe.v1.schema.json` shipped as package data.
- No C++ changes. No new embedded DazScript in daz-mcp-server's `_registry.py`.
- Never trigger DazScript modal dialogs: check file existence in Python/ContentMgr before any Studio call that opens a file.
- Live tests: only `-k recipe`-scoped runs. Never the whole `test_dazpy_integration.py`.
- **Ask the user before every `git push`, tag, and release publish**, in both repos.
- daz-script-server work branch: `feat/scene-recipe`, cut from the current `fix/assessment-p1` HEAD (it holds the spec commit). Don't commit the untracked `posemaniacs_ball_game*/` or `toon_line_pass_render.py`.
- daz-mcp-server work branch: `feat/scene-recipe-tools`, cut from `master`, not from the current `land-phase4`. Leave that branch's uncommitted files alone.
- Created nodes are labelled `"<recipe.id>:<entity name>"` (e.g. `cafe-conversation:anna_cu`). Rig lights: `"<recipe.id>:<rig>.<role>"`.

## Plan-level refinements of the spec (decided here)

1. **What `last_applied` holds.** Each owned node's record stores two maps: `desired` (the computed inputs apply used, e.g. camera position + aim target, pose file path) and `observed` (a live readback taken right after apply, e.g. camera position + rotation, pose snapshot).
   - *Recipe changed* = `desired_now != record.desired`.
   - *Hand-tweaked* = `live_observed != record.observed`.
   - Conflict reports show `desired` = new desired, `base` = `record.desired`, `live` = live observed.
   - This is how the spec's §5.2 "compare computed values" is implemented without reverse-engineering Daz's aim math.
2. **Conflict paths are per channel**, `<entity path>.<channel>`. Channels by kind:
   - actor/prop: `transform`, `pose` (actors only)
   - camera: `transform`, `optics`
   - light / rig light: `transform`, `output`
   - environment: `environment`

   Example: `lighting.rigs.main.key.transform`. The spec's examples like `...key.position` map onto the `transform` channel.
3. **No `dazpy.aio` variants.** `dazpy/aio.py` exposes no scene-level API, and daz-mcp-server calls sync dazpy through `run_dazpy()`. This deviates from spec §6's "async variants" line; tell the user at hand-off.
4. Multi-subject framing (`frame: [a, b]`) frames the centroid of the subjects' recipe positions at `_SHOT_DISTANCES[shot_type]`. It doesn't widen to fit them.

## Review Focus

1. **Recipe edited between `plan` and `apply`, or the scene changed between them.** `apply` must re-plan from scratch, never reuse a stale plan. Test: Task 8 `test_apply_replans_against_current_live_state`.
2. **Two recipes in one scene sharing entity names** (both have `actors.anna`). Each recipe sees only its own nodes. Test: Task 5 `test_read_live_filters_by_recipe_id`.
3. **A recipe-owned node renamed or relabelled by hand in Studio.** Ownership comes from the data item, not the label, so it's still found. Test: Task 5 `test_read_live_finds_node_by_record_not_label`.
4. **The scene saved, closed and reopened between applies.** Records survive. Live test in Task 10 `test_recipe_reapply_after_save_reload`.
5. **Studio busy (`DazBusyError`) midway through apply.** Treated like any other step failure: full rollback, `rolled_back: true`. Test: Task 7 `test_busy_error_mid_apply_rolls_back`.

---

## File Map

| File | Responsibility |
|---|---|
| `schemas/scene-recipe.v1.schema.json` | Canonical JSON Schema (published contract) |
| `dazpy/schemas/scene-recipe.v1.schema.json` | Package-data copy |
| `dazpy/_recipe_model.py` | Frozen dataclasses, `from_dict`/`to_dict` |
| `dazpy/_recipe_validate.py` | Offline validation → `ValidationReport` with stable codes |
| `dazpy/_recipe_desired.py` | Recipe → `dict[str, DesiredEntity]` (pure math) |
| `dazpy/_recipe_store.py` | Record/manifest (de)serialization, data-item scripts, live readback |
| `dazpy/_recipe_diff.py` | Three-way diff + conflict policy → `RecipePlan` (pure) |
| `dazpy/_recipe_ops.py` | `SceneOps` protocol + `DazSceneOps` (only Studio-mutating code) |
| `dazpy/_recipe_apply.py` | Executor: journal, ordering, compensating rollback |
| `dazpy/recipe.py` | Public facade + result types |
| `tests/test_recipe_model.py`, `test_recipe_validate.py`, `test_recipe_desired.py`, `test_recipe_store.py`, `test_recipe_diff.py`, `test_recipe_apply.py`, `test_recipe_facade.py` | Unit tests (no Studio) |
| `tests/fixtures/recipes/valid/*.json`, `tests/fixtures/recipes/invalid/*.json` | Validation corpus |
| `tests/test_recipe_live.py` | Live tests (skip when server down) |
| `docs/examples/recipes/g9-portrait.json` | Acceptance example (stock content only) |
| `docs/scene_recipes.rst` | User docs |
| `scripts/spikes/recipe_data_item_spike.py` | Task 1 spike (kept as a diagnostic) |

---

### Task 1: Data-item persistence spike (DS4 + DS6, live)

Decides whether `_recipe_store.py` uses data items (default) or the sidecar fallback (spec §5.1).

**Files:**
- Create: `scripts/spikes/recipe_data_item_spike.py`

**Interfaces:**
- Produces: a yes/no recorded in bd notes on `daz-script-server-5d6f.18`: "data items persist on DS4: Y/N, DS6: Y/N".

- [ ] **Step 1: Write the spike script.** CLI args `--url`, `--token-file`, `--phase write|read`, `--scene-path`.
  - `write` runs DazScript that creates a null node labelled `recipe-spike`, then:
    ```js
    var d = new DzSimpleElementData("dazpy.scene_recipe", true);
    d.getSettings().setStringValue("record", '{"probe":42}');
    node.addDataItem(d);
    var s = new DzSimpleSceneData("dazpy.scene_recipe.spike", true);
    s.getSettings().setStringValue("manifest", '{"probe":7}');
    Scene.addDataItem(s);
    ```
    then saves the scene to `--scene-path` via `dazpy.DazScene.save`.
  - `read` loads `--scene-path` with `DazScene.load` and prints `findDataItem(...).getSettings().getStringValue(...)` for both items.
- [ ] **Step 2: Run on DS4.** `python scripts/spikes/recipe_data_item_spike.py --phase write --scene-path C:/temp/recipe_spike.duf`, then in Studio do File > New, then run `--phase read`. Expected: prints `{"probe":42}` and `{"probe":7}`.
- [ ] **Step 3: Repeat on DS6.** Same commands against the DS6 instance.
- [ ] **Step 4: Record the result.** `bd update daz-script-server-5d6f.18 --notes "spike: data items DS4=<Y/N> DS6=<Y/N>"`. If either is N, Task 5 implements `SidecarStore` (Step 5b) as the backend for that Studio version. Otherwise skip 5b.
- [ ] **Step 5: Commit.** `git add scripts/spikes/recipe_data_item_spike.py && git commit -m "spike: verify element/scene data item persistence (5d6f.18)"`

---

### Task 2: Schema file + model dataclasses

**Files:**
- Create: `schemas/scene-recipe.v1.schema.json`, `dazpy/schemas/scene-recipe.v1.schema.json`, `dazpy/schemas/__init__.py` (empty), `dazpy/_recipe_model.py`, `tests/test_recipe_model.py`, `tests/fixtures/recipes/valid/cafe.json` (spec §4 example, verbatim), `tests/fixtures/recipes/valid/minimal.json` (`{"recipe_version":1,"id":"m"}`)
- Modify: `pyproject.toml` (`[tool.setuptools.package-data] dazpy = ["py.typed", "schemas/*.json"]`), `tests.py` (unit suite also loads every `tests/test_recipe_*.py` except `test_recipe_live.py`)

**Interfaces:**
- Produces (in `dazpy/_recipe_model.py`; all `@dataclass(frozen=True)`; `Vec3T = tuple[float, float, float]`):
  - `AssetSpec(path: str)`
  - `ActorSpec(asset: str, position: Vec3T = (0,0,0), rotation: Vec3T | None = None, facing: str | Vec3T | None = None, pose: str | None = None)`
  - `PropSpec(asset: str, position: Vec3T = (0,0,0), rotation: Vec3T | None = None)`
  - `RigLightOverride(azimuth_deg: float | None = None, elevation_deg: float | None = None, distance: float | None = None, intensity: float | None = None, color: tuple[int,int,int] | None = None)`
  - `RecipeRig(type: Literal["three_point"], target: str, light_type: Literal["spot","point","distant"] = "spot", key: RigLightOverride | None = None, fill: ... = None, rim: ... = None)`
  - `RecipeLight(type: Literal["spot","point","distant"], position: Vec3T, look_at: str | Vec3T | None = None, rotation: Vec3T | None = None, intensity: float = 100.0, color: tuple[int,int,int] = (255,255,255))`
  - `RecipeEnvironment(type: Literal["hdri"], image_path: str, intensity: float = 1.0, rotation_deg: float = 0.0, mode: Literal["dome_only","dome_and_scene","scene_only"] = "dome_only", draw_dome: bool = False)`
  - `RecipeCamera(frame: str | tuple[str, ...] | None = None, shot_type: Literal["close_up","medium","full_body"] = "medium", azimuth_deg: float = 0.0, elevation_deg: float = 10.0, position: Vec3T | None = None, look_at: str | Vec3T | None = None, rotation: Vec3T | None = None, focal_length: float = 50.0, depth_of_field: bool = False, focal_distance: float | None = None)`
  - `RenderSpec(engine: Literal["iray","filament","viewport"] | None = None, resolution: tuple[int,int] | None = None, iray_samples: int | None = None)`
  - `ShotSpec(id: str, camera: str, output: str, render: RenderSpec | None = None)`
  - `SceneRecipe(recipe_version: int, id: str, assets: Mapping[str, AssetSpec], actors: Mapping[str, ActorSpec], props: Mapping[str, PropSpec], rigs: Mapping[str, RecipeRig], lights: Mapping[str, RecipeLight], environment: RecipeEnvironment | None, cameras: Mapping[str, RecipeCamera], shots: tuple[ShotSpec, ...], render: RenderSpec)` with `@classmethod from_dict(cls, data: dict) -> SceneRecipe`, `@classmethod from_json(cls, text: str) -> SceneRecipe`, `to_dict(self) -> dict`.
  - JSON `lighting.rigs` / `lighting.lights` / `lighting.environment` map to `rigs` / `lights` / `environment`. Every section is optional in JSON and defaults to empty.
  - `from_dict` calls `validate_offline` (Task 3) and raises `RecipeValidationError(report)` (Task 3) when `report.ok` is False. Until Task 3 lands, `from_dict` assumes valid input.

- [ ] **Step 1: Write the schema file.** It must encode spec §4 exactly:
  - `additionalProperties: false` everywhere;
  - entity-key `propertyNames` pattern `^[A-Za-z0-9_-]{1,64}$`;
  - `oneOf` for camera framing vs explicit;
  - `facing`/`rotation` mutually exclusive;
  - reserved keys (`shots[].movement`, `actors.*.blocking`, `actors.*.interaction`, `assets.*.ref`, top-level `checks`) present with `"not": {}` and a `description` saying "reserved; not supported in recipe_version 1".

  Copy it byte-for-byte to `dazpy/schemas/`.
- [ ] **Step 2: Write failing tests** in `tests/test_recipe_model.py`:
```python
def test_schema_copies_are_identical(self):
    root = Path(__file__).parents[1]
    self.assertEqual((root/"schemas/scene-recipe.v1.schema.json").read_bytes(),
                     (root/"dazpy/schemas/scene-recipe.v1.schema.json").read_bytes())

def test_round_trip_cafe_fixture(self):
    data = json.loads(FIXTURES.joinpath("valid/cafe.json").read_text())
    r = SceneRecipe.from_dict(data)
    self.assertEqual(r.cameras["anna_cu"].shot_type, "close_up")
    self.assertEqual(r.lights["practical"].color, (255, 200, 150))
    self.assertEqual(SceneRecipe.from_dict(r.to_dict()), r)

def test_minimal_recipe_defaults_to_empty_sections(self):
    r = SceneRecipe.from_dict({"recipe_version": 1, "id": "m"})
    self.assertEqual((r.actors, r.shots, r.environment), ({}, (), None))
```
- [ ] **Step 3: Run.** `python -m pytest tests/test_recipe_model.py -v`. Expected: FAIL (ImportError).
- [ ] **Step 4: Implement `dazpy/_recipe_model.py`.** Lists in JSON become tuples; mappings use plain `dict` (frozen dataclass with `field(default_factory=dict)`; equality is all that's needed).
- [ ] **Step 5: Run.** Same command. Expected: PASS. Also `python tests.py unit`, expected all green.
- [ ] **Step 6: Commit.** `git commit -m "feat(recipe): v1 JSON schema and SceneRecipe model (5d6f.18)"`

---

### Task 3: Offline validation

**Files:**
- Create: `dazpy/_recipe_validate.py`, `tests/test_recipe_validate.py`, `tests/fixtures/recipes/invalid/*.json` (one file per case below, each with a sibling `<name>.expected.json` = `{"path": ..., "code": ...}`)
- Modify: `.github/workflows/ci.yml` (`pip install -e ".[docs]" requests jsonschema`), `dazpy/_recipe_model.py` (wire `from_dict` → validate)

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) RecipeIssue(path: str, code: str, message: str, allowed: tuple[str, ...] | None = None, suggestion: str | None = None)`
  - `@dataclass(frozen=True) ValidationReport(ok: bool, errors: tuple[RecipeIssue, ...], warnings: tuple[RecipeIssue, ...])`
  - `class RecipeValidationError(DazError)` with attribute `.report: ValidationReport` (add to `dazpy/exceptions.py`)
  - `validate_offline(data: object) -> ValidationReport`
  - Error codes (stable strings): `unsupported_version`, `missing_field`, `unknown_field`, `unsupported_in_version`, `invalid_type`, `invalid_enum`, `out_of_range`, `invalid_id`, `unknown_reference`, `mutually_exclusive`, `duplicate_shot_id`, `environment_requires_iray`. (`file_not_found` is added in Task 8.)
  - Paths are dotted, using the JSON layout: `cameras.anna_cu.shot_type`, `shots[1].camera`, `lighting.rigs.main.target`.

- [ ] **Step 1: Write the invalid corpus**, one case per code, plus:
  - typo'd reference `facing: "bne"` → `unknown_reference` with `suggestion == "ben"`;
  - camera with both `frame` and `position` → `mutually_exclusive`;
  - `shot_type: "extreme"` → `invalid_enum` with `allowed == ("close_up","full_body","medium")`;
  - `focal_length: 0` → `out_of_range` (must be > 0);
  - `resolution: [0, 1080]` → `out_of_range`;
  - `shots[].movement` present → `unsupported_in_version`;
  - `recipe_version: 2` → `unsupported_version`;
  - environment with `render.engine: "filament"` → `environment_requires_iray`;
  - environment with engine omitted → `environment_requires_iray`.
- [ ] **Step 2: Write failing tests.**
```python
def test_invalid_corpus_reports_expected_path_and_code(self):
    for case in sorted(INVALID.glob("*.json")):
        if case.name.endswith(".expected.json"): continue
        with self.subTest(case.name):
            exp = json.loads(case.with_suffix(".expected.json").read_text())
            rep = validate_offline(json.loads(case.read_text()))
            self.assertFalse(rep.ok)
            self.assertIn((exp["path"], exp["code"]), [(e.path, e.code) for e in rep.errors])

def test_valid_corpus_passes(self):
    for case in VALID.glob("*.json"):
        with self.subTest(case.name):
            self.assertTrue(validate_offline(json.loads(case.read_text())).ok)

@unittest.skipUnless(HAVE_JSONSCHEMA, "jsonschema not installed")
def test_schema_agrees_with_validator_on_corpus(self):
    # every valid fixture passes the JSON Schema; every invalid fixture except
    # cross-reference codes (unknown_reference, duplicate_shot_id,
    # environment_requires_iray) fails it
    ...

def test_typo_reference_suggests_closest_key(self):
    rep = validate_offline(load_invalid("facing_typo"))
    self.assertEqual(rep.errors[0].suggestion, "ben")

def test_from_dict_raises_with_report(self):
    with self.assertRaises(RecipeValidationError) as cm:
        SceneRecipe.from_dict({"recipe_version": 1})
    self.assertEqual(cm.exception.report.errors[0].code, "missing_field")
```
- [ ] **Step 3: Run.** `python -m pytest tests/test_recipe_validate.py -v`. Expected: FAIL.
- [ ] **Step 4: Implement `validate_offline`.** Hand-written walker (no `jsonschema` at runtime). It collects *all* errors in one pass, not just the first. Suggestions come from `difflib.get_close_matches(name, keys, n=1, cutoff=0.6)`.
- [ ] **Step 5: Run.** Same command, then `python tests.py unit`. Expected: PASS.
- [ ] **Step 6: Commit.** `git commit -m "feat(recipe): offline validation with model-actionable issues (5d6f.18)"`

---

### Task 4: Desired-state computation (pure)

**Files:**
- Create: `dazpy/_recipe_desired.py`, `tests/test_recipe_desired.py`

**Interfaces:**
- Consumes: `SceneRecipe` (Task 2); `dazpy._shot_geometry.spherical_offset`; `dazpy.cinematics._SHOT_DISTANCES`, `_SHOT_TARGET_OFFSETS_CM`; `dazpy.lighting._DEFAULT_KEY/_DEFAULT_FILL/_DEFAULT_RIM`, `_resolve_light_position`, `_look_at_euler`.
- Produces:
  - `EntityKind = Literal["actor","prop","camera","light","environment"]`
  - `@dataclass(frozen=True) DesiredEntity(path: str, kind: EntityKind, label: str, create: dict, channels: dict[str, dict])`
    - `path`: `actors.anna`, `props.cafe`, `cameras.wide`, `lighting.lights.practical`, `lighting.rigs.main.key`, `lighting.environment`
    - `create`: `{"asset_path": str}` for actor/prop, `{"light_type": str}` for light, `{}` for camera/environment
    - `channels`, by kind:
      - actor: `transform` = `{"position": Vec3T, "rotation": Vec3T}`, `pose` = `{"pose_path": str | None}`
      - prop: `transform` only
      - camera: `transform` = `{"position": Vec3T, "aim": Vec3T | None, "rotation": Vec3T | None}`, `optics` = `{"focal_length", "depth_of_field", "focal_distance"}`
      - light: `transform` = `{"position", "rotation"}`, `output` = `{"intensity", "color"}`
      - environment: `environment` = all `RecipeEnvironment` fields
  - `compute_desired(recipe: SceneRecipe) -> dict[str, DesiredEntity]` (keyed by `path`)

- [ ] **Step 1: Write failing tests.**
```python
def test_facing_computes_yaw_only(self):
    d = compute_desired(recipe_with(actors={"a": {"asset":"g","position":[0,0,0],"facing":"b"},
                                            "b": {"asset":"g","position":[100,0,100]}}))
    self.assertAlmostEqual(d["actors.a"].channels["transform"]["rotation"][1], 45.0, places=4)
    self.assertEqual(d["actors.a"].channels["transform"]["rotation"][0], 0.0)

def test_framing_camera_uses_recipe_position_and_shot_tables(self):
    d = compute_desired(recipe_with(actors={"anna": {"asset":"g","position":[-60,0,0]}},
                                    cameras={"cu": {"frame":"anna","shot_type":"close_up"}}))
    t = d["cameras.cu"].channels["transform"]
    self.assertEqual(t["aim"], (-60.0, 45.0, 0.0))  # +_SHOT_TARGET_OFFSETS_CM["close_up"]
    self.assertAlmostEqual(dist(t["position"], t["aim"]), 60.0, places=4)

def test_multi_subject_frames_centroid(self): ...   # frame ["a","b"] → aim x == mean(a.x, b.x)

def test_moving_actor_changes_dependent_camera_and_rig(self):
    before, after = compute_desired(r1), compute_desired(r1_with_anna_moved)
    self.assertNotEqual(before["cameras.cu"].channels, after["cameras.cu"].channels)
    self.assertNotEqual(before["lighting.rigs.main.key"].channels, after["lighting.rigs.main.key"].channels)

def test_rig_expands_to_three_lights_with_overrides(self):
    d = compute_desired(recipe_with_rig(key={"intensity": 120}))
    self.assertEqual(d["lighting.rigs.main.key"].channels["output"]["intensity"], 120)
    self.assertEqual(d["lighting.rigs.main.fill"].channels["output"]["intensity"], 50.0)
    self.assertEqual(d["lighting.rigs.main.rim"].label, "r:main.rim")

def test_compute_desired_is_deterministic(self):
    self.assertEqual(compute_desired(r1), compute_desired(SceneRecipe.from_dict(r1.to_dict())))
```
- [ ] **Step 2: Run.** `python -m pytest tests/test_recipe_desired.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Facing yaw is `degrees(atan2(tx - px, tz - pz))`, with rotation `(0, yaw, 0)`.
  - Lights' rotation comes from `_look_at_euler(position, target)`.
  - Explicit cameras with a `look_at` actor key aim at that actor's recipe position (no vertical offset).
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(recipe): desired-state computation (5d6f.18)"`

---

### Task 5: Records, manifest, live readback

**Files:**
- Create: `dazpy/_recipe_store.py`, `tests/test_recipe_store.py`

**Interfaces:**
- Consumes: `DesiredEntity` (Task 4); `DazClient.execute`; `ScriptBuilder.iife/escape_string`; `DazPose.capture`.
- Produces:
  - `DATA_ITEM_NAME = "dazpy.scene_recipe"`; scene item name `f"dazpy.scene_recipe.{recipe_id}"`
  - `@dataclass(frozen=True) EntityRecord(recipe_id: str, path: str, recipe_version: int, desired: dict[str, dict], observed: dict[str, dict])` with `to_json() -> str` and `from_json(s) -> EntityRecord`
  - `@dataclass(frozen=True) Manifest(recipe_id: str, entities: tuple[str, ...], environment: EntityRecord | None)`
  - `@dataclass(frozen=True) LiveEntity(path: str, node_name: str, kind: EntityKind, record: EntityRecord, observed: dict[str, dict], foreign_children: tuple[str, ...])`
  - `@dataclass(frozen=True) LiveState(manifest: Manifest | None, entities: dict[str, LiveEntity], environment_observed: dict | None)`
  - `read_live(client: DazClient, recipe_id: str) -> LiveState`: one script call for all nodes, plus one `DazPose.capture` per actor that has a record (observed `pose` channel = `{"snapshot": pose.to_dict()}`).
  - `write_record_script(node_name: str, record: EntityRecord) -> str`, `remove_record_script(node_name: str) -> str`, `write_manifest_script(m: Manifest) -> str`. These are script builders; `DazSceneOps` (Task 6) executes them.
  - Observed channel shapes (what `read_live` returns and what `DazSceneOps.set_channels` accepts as a rollback target):
    - `transform` = `{"position", "rotation"}` (world)
    - `optics` = camera fields
    - `output` = `{"intensity", "color"}`
    - `pose` = `{"snapshot": dict}`
    - `environment` = Iray environment property values
- [ ] **Step 1: Write failing tests** (mock `client.execute` returning canned JSON, in the style of `tests/test_dazpy.py`):
```python
def test_record_json_round_trip(self): ...

def test_read_live_filters_by_recipe_id(self):
    client = fake_client(nodes=[node("A", rec("r1","actors.anna")), node("B", rec("r2","actors.anna"))])
    self.assertEqual([e.node_name for e in read_live(client, "r1").entities.values()], ["A"])

def test_read_live_finds_node_by_record_not_label(self):
    client = fake_client(nodes=[node("Genesis 9", rec("r1","actors.anna"), label="renamed by user")])
    self.assertIn("actors.anna", read_live(client, "r1").entities)

def test_foreign_children_listed(self):
    client = fake_client(nodes=[node("A", rec("r1","actors.anna"), children=[node("Shirt", None)])])
    self.assertEqual(read_live(client, "r1").entities["actors.anna"].foreign_children, ("Shirt",))

def test_manifest_lists_entity_missing_from_scene(self):
    st = read_live(fake_client(nodes=[], manifest=man("r1", ["cameras.wide"])), "r1")
    self.assertEqual(st.manifest.entities, ("cameras.wide",)); self.assertEqual(st.entities, {})

def test_write_record_script_uses_simple_element_data(self):
    s = write_record_script("A", rec("r1", "actors.anna"))
    self.assertIn("DzSimpleElementData", s); self.assertIn('"dazpy.scene_recipe"', s)
```
- [ ] **Step 2: Run.** `python -m pytest tests/test_recipe_store.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** The readback script walks `Scene.getNodeList()` and keeps nodes whose `findDataItem("dazpy.scene_recipe")` record has a matching `recipe_id`. For each it returns name, record string, world position/rotation, camera/light extras and the names of descendants without a matching record. The scene manifest is read via `Scene.findDataItem`.
- [ ] **Step 5b (only if Task 1 recorded N for a Studio version): implement `SidecarStore`.** JSON file at `<scene file>.recipes.json`; unsaved scene → `~/.daz3d/dazpy_recipes/<recipe_id>.json`. Same three script-builder entry points become file writes. The backend is chosen by the Studio major version in `client.status()["studio"]` (the field `src/DzScriptServerPane.cpp` emits as `"studio"`). Tests mirror the data-item tests against a temp dir.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(recipe): ownership records and live readback (5d6f.18)"`

---

### Task 6: Three-way diff and conflict policy (pure)

**Files:**
- Create: `dazpy/_recipe_diff.py`, `tests/test_recipe_diff.py`

**Interfaces:**
- Consumes: `DesiredEntity` (Task 4), `LiveState`/`LiveEntity`/`EntityRecord` (Task 5), `RecipeIssue` (Task 3), `_DEFAULT_VERIFY_TOLERANCE`.
- Produces:
  - `OnConflict = Literal["ask","recipe_wins","scene_wins"]`; `Resolution = Literal["recipe","scene"]`
  - `@dataclass(frozen=True) Conflict(path: str, kind: Literal["modified","removed_from_recipe","deleted_in_scene","has_foreign_children"], desired: object, base: object, live: object)`
  - `@dataclass(frozen=True) Step(op: Literal["create","modify","set_environment","adopt","unparent","delete"], path: str, channels: dict[str, dict], prior: dict[str, dict] | None, node_name: str | None)`
    - `adopt` = rewrite the record only (`scene_wins` kept a tweak).
    - `unparent.channels` = `{"children": {"names": [...]}}`.
  - `@dataclass(frozen=True) RecipePlan(steps: tuple[Step, ...], conflicts: tuple[Conflict, ...], warnings: tuple[RecipeIssue, ...], blocked: bool, overwritten: tuple[str, ...], kept: tuple[str, ...])`
  - `diff(desired: dict[str, DesiredEntity], live: LiveState, *, on_conflict: OnConflict = "ask", resolutions: Mapping[str, Resolution] | None = None, tolerance: float = _DEFAULT_VERIFY_TOLERANCE) -> RecipePlan`
  - Warning code for an unconflicted hand tweak: `hand_tweak_kept`, path = channel path.
  - Step order in `steps`: all `create`, then `modify`, `set_environment`, `adopt`, `unparent`, then all `delete` (spec §5.4: deletions last).
  - `blocked=True` iff `on_conflict == "ask"` and at least one conflict isn't covered by `resolutions`. When blocked, `steps == ()`.

- [ ] **Step 1: Write failing tests**, one per spec §5.2 row plus policy cases:
```python
def test_unchanged_is_noop(self):                 self.assertEqual(diff(D, live_matching(D)).steps, ())
def test_recipe_change_only_modifies_that_channel(self):
    p = diff(D_cam_moved, live_matching(D))
    self.assertEqual([(s.op, s.path, list(s.channels)) for s in p.steps], [("modify","cameras.cu",["transform"])])
def test_hand_tweak_kept_with_warning(self):
    p = diff(D, live_tweaked(D, "cameras.cu", "transform"))
    self.assertEqual(p.steps, ()); self.assertEqual(p.warnings[0].code, "hand_tweak_kept")
def test_both_changed_is_conflict_and_ask_blocks_everything(self):
    p = diff(D_cam_moved_and_light_changed, live_tweaked(D, "cameras.cu", "transform"))
    self.assertTrue(p.blocked); self.assertEqual(p.steps, ())
    self.assertEqual((p.conflicts[0].path, p.conflicts[0].kind), ("cameras.cu.transform", "modified"))
def test_live_already_equals_desired_is_noop_not_conflict(self): ...
def test_removed_untouched_entity_is_deleted_last(self):
    p = diff(D_without_light_plus_new_cam, live_matching(D))
    self.assertEqual(p.steps[-1].op, "delete"); self.assertEqual(p.steps[0].op, "create")
def test_removed_tweaked_entity_is_conflict(self): ...       # kind == "removed_from_recipe"
def test_hand_deleted_entity_is_conflict(self): ...          # in manifest, not in scene → "deleted_in_scene"
def test_foreign_children_on_removed_entity_is_conflict(self): ...
def test_recipe_wins_resolves_and_reports_overwritten(self):
    p = diff(D_cam_moved, live_tweaked(D, "cameras.cu", "transform"), on_conflict="recipe_wins")
    self.assertFalse(p.blocked); self.assertEqual(p.overwritten, ("cameras.cu.transform",))
def test_scene_wins_emits_adopt_step(self):
    p = diff(D_cam_moved, live_tweaked(D, "cameras.cu", "transform"), on_conflict="scene_wins")
    self.assertEqual([s.op for s in p.steps], ["adopt"]); self.assertEqual(p.kept, ("cameras.cu.transform",))
def test_resolutions_override_policy_per_path_and_ask_still_blocks_uncovered(self): ...
def test_recipe_wins_on_foreign_children_unparents_before_delete(self):
    ops = [s.op for s in diff(D_without_actor, live_with_children(D), on_conflict="recipe_wins").steps]
    self.assertLess(ops.index("unparent"), ops.index("delete"))
def test_deleted_in_scene_recipe_wins_recreates_scene_wins_drops_from_manifest(self): ...
def test_tolerance_ignores_float_noise(self): ...            # live off by 0.01 → no warning
def test_modify_steps_carry_prior_observed_values(self):
    s = diff(D_cam_moved, live_matching(D)).steps[0]
    self.assertEqual(s.prior["transform"], live_matching(D).entities["cameras.cu"].observed["transform"])
```
- [ ] **Step 2: Run.** `python -m pytest tests/test_recipe_diff.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `diff`.** Values are compared recursively: floats with `abs(a-b) <= tolerance`, tuples elementwise, everything else `==`. Pose snapshots go through `_pose_mismatches` from `_scene_state.py`.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(recipe): three-way diff and conflict policy (5d6f.18)"`

---

### Task 7: SceneOps adapter + executor with compensating rollback

**Files:**
- Create: `dazpy/_recipe_ops.py`, `dazpy/_recipe_apply.py`, `tests/test_recipe_apply.py`

**Interfaces:**
- Consumes: `RecipePlan`/`Step` (Task 6), `DesiredEntity` (Task 4), `EntityRecord`/`Manifest`/script builders (Task 5), dazpy primitives listed in spec §3.
- Produces:
  - `class SceneOps(Protocol)`:
    - `create(entity: DesiredEntity) -> list[str]`: created node names; the first is the owned root
    - `set_channels(node_name: str, kind: EntityKind, channels: dict[str, dict]) -> None`: accepts both desired-shaped and observed-shaped channel dicts
    - `observe(node_name: str, kind: EntityKind) -> dict[str, dict]`
    - `set_environment(values: dict) -> None`
    - `observe_environment() -> dict`
    - `unparent(child_names: list[str]) -> None`: to scene root, preserving world transform
    - `delete(node_name: str) -> None`
    - `write_record(node_name: str, record: EntityRecord) -> None`
    - `remove_record(node_name: str) -> None`
    - `write_manifest(manifest: Manifest) -> None`
  - `class DazSceneOps(SceneOps)`, `__init__(self, scene: DazScene)`. `create` for assets does a node-list diff around `scene.load(path)`. `set_channels(pose={"pose_path": p})` uses `poses.apply_pose`; `pose={"snapshot": s}` uses `DazPose(figure=s["figure"], bones=s["bones"], morphs=s["morphs"], props=s["props"]).apply_full(skeleton)`, where `s` is the `DazPose.to_dict()` shape.
  - `@dataclass(frozen=True) ApplyResult(applied: bool, steps: tuple[Step, ...], conflicts: tuple[Conflict, ...], warnings: tuple[RecipeIssue, ...], overwritten: tuple[str, ...], kept: tuple[str, ...], rolled_back: bool = False, failed_step: Step | None = None, error: str | None = None, rollback_errors: tuple[str, ...] = ())`
  - `execute(plan: RecipePlan, desired: dict[str, DesiredEntity], live: LiveState, ops: SceneOps, *, recipe_id: str, recipe_version: int) -> ApplyResult`
- Journal and rollback algorithm (not determined by the signatures):
```text
journal = []
for step in plan.steps:
    try: perform(step); journal.append(step + undo info)
         # create   → undo: delete every created node name
         # modify   → undo: set_channels(node, kind, step.prior)
         # set_environment → undo: set_environment(prior)
         # adopt / record writes → undo: write_record(prior record) or remove_record
         # unparent → undo: reparent children back to the original node
         # delete   → no undo (runs last); record that it happened
    except Exception as e:
        for done in reversed(journal): try undo(done) except → rollback_errors += str
        return ApplyResult(applied=False, rolled_back=True, failed_step=step, error=str(e), ...)
after all steps: for each created/modified entity → observe() → write_record({desired, observed});
                 write_manifest(all current entity paths)
                 (record/manifest writes are journaled too; a failure there rolls back the same way)
```
- [ ] **Step 1: Write failing tests** with a `FakeOps` that records calls and raises on the Nth call of a chosen method:
```python
def test_success_writes_records_and_manifest_after_mutations(self): ...
def test_failure_after_create_deletes_created_nodes(self):
    ops = FakeOps(fail_on=("set_channels", 1)); r = execute(plan_create_then_modify, D, L, ops, ...)
    self.assertTrue(r.rolled_back); self.assertIn(("delete", "cam_new"), ops.calls)
def test_failure_after_modify_restores_prior_values(self):
    self.assertIn(("set_channels", "Camera 1", "camera", PRIOR["transform"]), ops.calls_with_args)
def test_busy_error_mid_apply_rolls_back(self):
    ops = FakeOps(fail_on=("create", 2), exc=DazBusyError("busy")); r = execute(...)
    self.assertTrue(r.rolled_back); self.assertIsInstance(r.failed_step, Step)
def test_failure_in_delete_phase_reports_partial_deletes(self): ...
def test_rollback_error_is_reported_not_raised(self):
    ops = FakeOps(fail_on=[("set_channels", 2), ("delete", 1)]); r = execute(...)
    self.assertEqual(len(r.rollback_errors), 1)
def test_adopt_rewrites_record_with_live_observed_and_new_desired(self): ...
def test_blocked_plan_executes_nothing(self):
    r = execute(blocked_plan, D, L, ops := FakeOps(), ...)
    self.assertFalse(r.applied); self.assertEqual(ops.calls, [])
```
- [ ] **Step 2: Run.** `python -m pytest tests/test_recipe_apply.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `execute` and `DazSceneOps`.** Camera transform: `set_position` then `aim_at(*aim)` if `aim` is set, else `set_rotation`. Light transform: `set_position` + `set_rotation`. Environment uses `apply_hdri_environment(DazRenderSettings(scene._client), HDRIEnvironment(...))` (`DazRenderSettings` from `dazpy/_render.py`).
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(recipe): executor with compensating rollback (5d6f.18)"`

---

### Task 8: Public facade: validate / plan / apply / observe

**Files:**
- Create: `dazpy/recipe.py`, `tests/test_recipe_facade.py`
- Modify: `dazpy/__init__.py` (export `SceneRecipe`, `RecipeIssue`, `ValidationReport`, `RecipePlan`, `Conflict`, `ApplyResult`, `ObserveReport`, `ShotRender`, `RecipeValidationError`; add to `__all__`), `dazpy/_recipe_validate.py` (add `file_not_found`)

**Interfaces:**
- Consumes: Tasks 2–7.
- Produces (in `dazpy/recipe.py`):
  - `recipe_schema(version: int = 1) -> dict`: loads package data via `importlib.resources`
  - `validate(recipe: SceneRecipe | dict, scene: DazScene | None = None) -> ValidationReport`. With `scene`, one batched script resolves every asset path (`App.getContentMgr().findFile(rel, DzContentMgr.AllDirs)` for paths with a leading `/`, `DzFileInfo.exists()` for absolute ones), plus the HDRI `image_path`, and adds `file_not_found` at `assets.<k>.path` / `lighting.environment.image_path`.
  - `plan(recipe, scene, *, on_conflict: OnConflict = "ask", resolutions: Mapping[str, Resolution] | None = None) -> RecipePlan`
  - `apply(recipe, scene, *, on_conflict: OnConflict = "ask", resolutions=None) -> ApplyResult`: validates (offline + scene), then `read_live` → `compute_desired` → `diff` → `execute(..., DazSceneOps(scene))`. Invalid recipe → raises `RecipeValidationError`.
  - `@dataclass(frozen=True) ObserveReport(applied: bool, in_sync: bool, drift: tuple[RecipeIssue, ...], pending: tuple[str, ...], conflicts: tuple[Conflict, ...])`
    - `applied` = manifest exists
    - `drift` = `hand_tweak_kept` warnings + `deleted_in_scene`
    - `pending` = channel paths the recipe would change
  - `observe(recipe, scene) -> ObserveReport`
  - Each result type gets a `to_dict()` for JSON transport (used by MCP).

- [ ] **Step 1: Write failing tests** (mock client; reuse fakes from Tasks 5–7):
```python
def test_apply_replans_against_current_live_state(self):
    # plan() sees no conflict; the scene is tweaked; apply() must now block
    scene = fake_scene(live_matching(D)); self.assertFalse(plan(R2, scene).blocked)
    scene.tweak("cameras.cu", "transform"); self.assertFalse(apply(R2, scene).applied)
def test_apply_invalid_recipe_raises_before_touching_scene(self): ...
def test_validate_with_scene_reports_missing_asset(self):
    rep = validate(R, fake_scene(missing_files={"/People/Genesis 9/Genesis 9.duf"}))
    self.assertEqual((rep.errors[0].path, rep.errors[0].code), ("assets.g9.path", "file_not_found"))
def test_observe_reports_drift_and_pending(self): ...
def test_result_types_to_dict_are_json_serializable(self):
    json.dumps(apply(R, fake_scene(empty)).to_dict())
def test_recipe_schema_returns_v1(self):
    self.assertEqual(recipe_schema()["properties"]["recipe_version"]["const"], 1)
```
- [ ] **Step 2: Run.** `python -m pytest tests/test_recipe_facade.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `dazpy/recipe.py` and the exports.**
- [ ] **Step 4: Run.** Same, then `python tests.py unit`. Expected: PASS, no regressions.
- [ ] **Step 5: Commit.** `git commit -m "feat(recipe): public validate/plan/apply/observe facade (5d6f.18)"`

---

### Task 9: Render (materialize)

**Files:**
- Modify: `dazpy/recipe.py`, `tests/test_recipe_facade.py`

**Interfaces:**
- Consumes: `observe` (Task 8), `dazpy._render_api.render`, `RenderResult`.
- Produces:
  - `@dataclass(frozen=True) ShotRender(shot_id: str, camera_label: str, output: str, result: RenderResult)` with `to_dict()`
  - `render(recipe, scene, *, shots: Sequence[str] | None = None, force: bool = False, wait: bool = True, timeout: float = 300.0) -> list[ShotRender]`
  - New exception `RecipeNotAppliedError(DazError)` (in `dazpy/exceptions.py`) with `.report: ObserveReport`. Raised when `not force` and (`not report.applied` or `report.conflicts` or a shot's camera has drifted/was deleted).
  - Per shot: merge top-level `render` with `shot.render`, call `render_api.render(scene._client, shot.output, camera=<camera label>, engine=..., width=..., height=..., iray_samples=..., wait=wait, timeout=timeout)`. Create the output's parent directory on the Studio host first (`DzDir.mkpath` via one script). Pure pending recipe changes (`pending`) also refuse, with the message "recipe has unapplied changes; call apply first".

- [ ] **Step 1: Write failing tests.**
```python
def test_render_refuses_unapplied_recipe(self):
    with self.assertRaises(RecipeNotAppliedError): render(R, fake_scene(empty))
def test_render_force_skips_guard(self): ...
def test_shot_render_override_merges_over_top_level(self):
    calls = render(R_cafe, applied_scene, wait=False); kw = render_api_mock.call_args_list[1].kwargs
    self.assertEqual((kw["width"], kw["height"], kw["engine"], kw["iray_samples"]), (1080, 1350, "iray", 200))
def test_render_subset_by_shot_id(self): ...
def test_camera_label_is_recipe_scoped(self):
    self.assertEqual(render_api_mock.call_args.kwargs["camera"], "cafe-conversation:wide")
```
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** `python tests.py unit`. Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(recipe): render shots from an applied recipe (5d6f.18)"`

---

### Task 10: Example, live tests, docs

**Files:**
- Create: `docs/examples/recipes/g9-portrait.json`, `tests/test_recipe_live.py`, `docs/scene_recipes.rst`
- Modify: `docs/index.rst` (toctree), `dazpy/ROADMAP.md`, `README.md` (dazpy section: one paragraph + link), `CHANGELOG.md` (Unreleased: "Scene recipes (5d6f.18)")

**Interfaces:**
- Consumes: the whole facade.

- [ ] **Step 1: Write the example.** One Genesis 9 base figure, the stock G9 default/standing pose shipped with Studio (pick an installed path, confirm via `validate(recipe, scene)`), a three-point rig, two cameras (`full_body` and `close_up`), two shots to `C:/temp/recipe_example/*.png`, Iray, 640×480, `iray_samples: 50`. No environment block (avoids a third-party HDRI dependency).
- [ ] **Step 2: Write live tests** gated like `tests/test_dazpy_integration.py` (`skip_if_down`, `skip_no_daz`), each starting from File > New via `DazScene` and an `id` unique per test:
  - `test_recipe_example_renders_end_to_end`: apply, then render; both PNGs exist with size > 0.
  - `test_recipe_reapply_changes_only_moved_camera`: apply; move the camera in the recipe; `plan().steps` is one modify on `cameras.cu`.
  - `test_recipe_hand_tweak_warns_then_conflicts`: nudge a light via `DazNode.set_position`. Re-apply of the unchanged recipe → `hand_tweak_kept`. Then change that light in the recipe → `apply().applied is False`, conflict listed. Then `recipe_wins` → applied.
  - `test_recipe_remove_actor_deletes_node`
  - `test_recipe_rollback_restores_scene`: monkeypatch `DazSceneOps.set_channels` to raise on its 2nd call; afterwards `observe()` matches the pre-apply observe.
  - `test_recipe_reapply_after_save_reload`: apply, save to temp `.duf`, File > New, load, then `plan().steps == ()`.
- [ ] **Step 3: Run on DS4.** `python -m pytest tests/test_recipe_live.py -v -k recipe` with DS4 running. Expected: all PASS.
- [ ] **Step 4: Run on DS6.** Same with DS6. Expected: all PASS. Optionally add a viewport/filament variant of the end-to-end test if `tests/smoke_live.py` shows the engine available.
- [ ] **Step 5: Write docs.** `docs/scene_recipes.rst` covers:
  - schema reference: link to `schemas/scene-recipe.v1.schema.json` + a field table;
  - the iterative loop;
  - the conflict model (the spec §5.2 table, the `on_conflict`/`resolutions` examples);
  - rollback guarantees;
  - the example walkthrough.

  Then run `cd docs && make html`. Expected: no new warnings.
- [ ] **Step 6: Commit.** `git commit -m "docs+tests(recipe): example recipe, live tests, user docs (5d6f.18)"`

---

### Task 11: daz-mcp-server: rename `daz_materialize_recipe` → `daz_run_script_job`

Repo: `Y:/working/BlueMoonFoundry/daz-mcp-server`, branch `feat/scene-recipe-tools` from `master`.

**Files:**
- Modify: `src/vangard_daz_mcp/tools/workflow.py:73-88` (rename function + docstring: "Run a .dsa/.ds script file through the asynchronous job boundary"), compact-profile help text in the same file (~line 155), `tests/test_workflow_profile.py` (lines 20, 71–96), `README.md:120`, `SKILL_DAZ_STUDIO.md:10`, `CHANGELOG`/README changes section ("BREAKING: daz_materialize_recipe renamed to daz_run_script_job")

- [ ] **Step 1: Update the tests first.** Rename them to `test_run_script_job_delegates_file_job` / `test_run_script_job_rejects_non_script_file`, call `workflow.daz_run_script_job`, and change the compact-profile expected tool list.
- [ ] **Step 2: Run.** `uv run pytest tests/test_workflow_profile.py -v`. Expected: FAIL (AttributeError).
- [ ] **Step 3: Rename** the function, error text ("must be a .dsa or .ds file"), help text and docs.
- [ ] **Step 4: Run.** `uv run pytest tests/test_workflow_profile.py -v` then `grep -rn materialize_recipe src tests *.md`. Expected: PASS; grep finds nothing.
- [ ] **Step 5: Commit.** `git commit -m "refactor!: rename daz_materialize_recipe to daz_run_script_job"`

---

### Task 12: daz-mcp-server: recipe tools, schema resource, skill doc

**Files:**
- Create: `src/vangard_daz_mcp/tools/recipe.py`, `tests/test_recipe_tools.py`, `SKILL_RECIPE.md`
- Modify: `src/vangard_daz_mcp/tools/__init__.py` (import `recipe`), `tests/test_workflow_profile.py` (compact list gains the 5 recipe tools), `pyproject.toml` (temporary `[tool.uv.sources] dazpy = { path = "../daz-script-server", editable = true }`, removed in Task 13), `README.md`, `CLAUDE.md` (tool count + one line)

**Interfaces:**
- Consumes: `dazpy.recipe.{validate, plan, apply, observe, render, recipe_schema}`, `dazpy.SceneRecipe`, `RecipeValidationError`, `RecipeNotAppliedError`; `run_dazpy`, `get_scene`, `handle_dazpy_error`, `_DEFAULT_TAG` (as in `workflow.py`).
- Produces (all `@mcp.tool(tags=_DEFAULT_TAG)`, all taking `recipe: dict`):
  - `daz_recipe_validate(recipe: dict) -> dict` → `ValidationReport.to_dict()`
  - `daz_recipe_plan(recipe: dict, on_conflict: str = "ask", resolutions: dict[str, str] | None = None) -> dict`
  - `daz_recipe_apply(recipe: dict, on_conflict: str = "ask", resolutions: dict[str, str] | None = None) -> dict`
  - `daz_recipe_observe(recipe: dict) -> dict`
  - `daz_recipe_render(recipe: dict, shots: list[str] | None = None, force: bool = False) -> dict` → `{"shots": [ShotRender.to_dict(), ...]}`
  - Resources `daz://recipe/schema` and `daz://recipe/schema/{version}` → `json.dumps(recipe_schema(version))`
  - `RecipeValidationError` is **not** turned into a ToolError. The tool returns `{"ok": false, "errors": [...]}` so the model can fix its recipe. `RecipeNotAppliedError` returns `{"ok": false, "reason": ..., "observe": ...}`. Other dazpy errors go through `handle_dazpy_error`.
  - Docstrings carry the loop: validate → plan → apply → render. They explain how to read `conflicts`, and that `on_conflict` should reflect the user's remembered preference ("always override" → `recipe_wins`, "always defer" → `scene_wins`, otherwise `ask` and show the user the conflicts, then send `resolutions`).

- [ ] **Step 1: Write failing tests** (monkeypatch `dazpy.recipe` functions, in the style of `tests/test_workflow_profile.py`):
```python
async def test_apply_passes_policy_and_resolutions(monkeypatch): ...
async def test_validate_error_returned_as_data_not_toolerror(monkeypatch):
    out = await recipe.daz_recipe_apply({"recipe_version": 1})
    assert out["ok"] is False and out["errors"][0]["code"] == "missing_field"
async def test_render_not_applied_returns_reason(monkeypatch): ...
def test_compact_profile_includes_recipe_tools():
    assert {"daz_recipe_validate","daz_recipe_plan","daz_recipe_apply",
            "daz_recipe_observe","daz_recipe_render"} <= set(_profile_snapshot("compact")["tools"])
def test_schema_resource_available_in_compact(): ...
```
- [ ] **Step 2: Run.** `uv sync && uv run pytest tests/test_recipe_tools.py tests/test_workflow_profile.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `tools/recipe.py` and the registration. Write `SKILL_RECIPE.md` (the iterative loop, the conflict handling, one worked example from `docs/examples/recipes/g9-portrait.json`).
- [ ] **Step 4: Run** the full suite: `uv run pytest tests/ -v -m "not integration"` (or the repo's unit selector). Expected: PASS.
- [ ] **Step 5: Live check.** With DS running, start the MCP server (`uv run vangard-daz-mcp`) and call `daz_recipe_apply` then `daz_recipe_render` with the example recipe via the FastMCP client from a scratch script. Expected: `applied: true`, two PNGs.
- [ ] **Step 6: Commit.** `git commit -m "feat: scene recipe tools and schema resource in compact profile"`

---

### Task 13: Release (ask before every push / tag / publish)

**Files:**
- Modify (daz-script-server): version strings to `2.12.0`, everywhere `scripts/check_version_consistency.py` expects them (`pyproject.toml`, `dazpy/__init__.py`, plugin version header, `openapi.yaml` `info.version`); `CHANGELOG.md` (move Unreleased → 2.12.0)
- Modify (daz-mcp-server): `pyproject.toml` (`dazpy>=2.12.0`, remove `[tool.uv.sources]` override, `version = "0.7.0"`), `uv.lock`, changelog

- [ ] **Step 1: Final gates (daz-script-server).**
  - `python tests.py unit`
  - `python scripts/check_openapi_parity.py`
  - `python scripts/check_version_consistency.py`
  - `python scripts/check_sdk_tag.py`
  - `./build.sh build --clean` and `./build.sh build --sdk-version 6 --clean`
  - `python tests/smoke_live.py --record` on DS4 and DS6

  Expected: all pass. Commit smoke results.
- [ ] **Step 2: Bump versions to 2.12.0 and commit.** `git commit -m "release: 2.12.0 (scene recipes)"`
- [ ] **Step 3: ASK THE USER.** "Push `feat/scene-recipe` and open the PR to master?" On yes: `git push -u origin feat/scene-recipe` and `gh pr create` (body ends with the Claude Code attribution line). Wait for merge.
- [ ] **Step 4: ASK THE USER.** "Cut release v2.12.0 now?" On yes: on updated `master`, run `./build.sh release v2.12.0`.
- [ ] **Step 5: daz-mcp-server.** Bump the pin, remove the uv path source, `uv lock`, then `uv run pytest tests/ -v`. Expected: PASS against the released dazpy. Commit: `git commit -m "chore: require dazpy 2.12.0; v0.7.0"`.
- [ ] **Step 6: ASK THE USER.** "Push `feat/scene-recipe-tools` and open the PR?" On yes, push and `gh pr create`.
- [ ] **Step 7: Close out.** `bd close daz-script-server-5d6f.18`; `bd dolt push` (ask first, same as git push).
