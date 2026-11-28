# Asset References, Compatibility and Fitting — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scene recipes (v2) name content by path / product / SKU / search, check
compatibility before the scene changes, build actors in layers (take over or
create → presets → fitted items, including multi-node items) and record
provenance.

**Architecture:** New pure modules for references, content types, finders,
resolution and compatibility feed the existing pipeline
(`validate → compute_desired → read_live → diff → execute`). Fitted items
become ordinary recipe entities (`actors.<a>.wearing.<key>`, kind `"item"`)
so they reuse the v1 three-way diff, conflicts and rollback; one-shot
`replace`/`remove` selectors become `unfit` steps planned separately.
Everything Studio-side remains DazScript through `client.execute`.

**Tech Stack:** Python 3.10+ stdlib (dazpy has no runtime deps), DazScript,
`unittest` + `tests/recipe_fakes.py`, JSON Schema files (checked with
`jsonschema` in tests when installed). Cross-repo: daz-content-browser-mcp
(httpx/FastMCP, pytest), daz-mcp-server (pytest).

**Spec:** `docs/superpowers/specs/2026-11-26-asset-refs-and-fitting-design.md`
(section numbers below, e.g. §6.4, refer to it).

## Global Constraints

- Work on branch `feature/asset-refs-5d6f.21`. Never `git push` without asking the user.
- No modal dialog may be triggered by validate, plan or apply. Compatibility is read from metadata, never by attempting a load. Load with nothing selected except where Task 1 proves a figure-selected load cannot pop a modal for an already-compatibility-checked item.
- Delete only through `DzDeleteAction` on an exact selection (existing `_delete_script` / `_DELETE_SELECTED_JS`), never `Scene.removeNode`.
- Never store `std::string` in plugin structures (not expected to be touched here; all work is Python/DazScript).
- Live tests: scoped runs only (`-k`), never the full integration suite; ask the user to close/restart Studio, never close it programmatically.
- dazpy keeps zero runtime dependencies; HTTP via `urllib.request`.
- `recipe_version: 2`; v1 recipes must load and behave exactly as before (all existing `tests/test_recipe_*.py` stay green).
- Error codes (exact spellings): `ambiguous_asset`, `asset_not_found`, `content_database_unavailable`, `incompatible_asset`, `ambiguous_node`, `node_not_found`, `replace_target_missing`, `remove_target_missing`, `take_over_asset_changed`, `invalid_asset_ref`. Warning codes: `compatibility_unknown`, `pin_mismatch`, `pin_file_missing`, `finder_fallback`, `preset_dropped`, `unrestorable_removal`, `similar_node_label`.
- Friendly content types and prefixes exactly as §6.3 until Task 1 corrects them (then update the table in the spec too).

## Review Focus

1. A hand-built actor whose label differs only in case from `node` ("abby") — must not be taken over; the plan warns `similar_node_label` naming the near match, so the user sees why a second Abby would be created.
2. `find:` phrase with an exact product-name match *and* other fuzzy hits — exact name must win, no `ambiguous_asset`.
3. A multi-node outfit where one loaded node is not fitted to the actor (e.g. a stray prop) — whole load removed, `DazError`, scene unchanged.
4. Re-apply of an unchanged recipe after a successful `replace` — zero steps, the one-shot selector does not fire again even though new hand-loaded hair is present.
5. Content browser configured but down — falls back to Studio search with `finder_fallback` warning, never raises a connection error out of `validate`.

Each is pinned by a test in the owning task (Tasks 3, 6, 11, 10, 5 respectively).

---

### Task 1: Live probe of the Studio APIs the design depends on

Gate for everything Studio-side. Results may change Tasks 6, 7, 8, 11.

**Files:**
- Create: `tests/live_probe_asset_apis.py` (script, not collected by `tests.py`)
- Modify: spec §6.3 table / §7 if findings differ

**Interfaces:**
- Produces: a findings section appended to the spec (`## 15. Live probe findings (DS4/DS6)`) stating, per Studio version, what each call returns.

- [ ] **Step 1: Write the probe** — uses `dazpy.DazClient` against `127.0.0.1:18811`, takes `--figure-label` and `--hair-path`, `--outfit-path` (wearables preset), `--g8-hair-path` (incompatible item). Read-only first, then one load into a scratch scene the user confirms. It prints JSON for:
  - `node.getPresentation().type`, `.preferredBase`, `.extendedBases`, `.autoFitBase()` for the figure and each item fitted to it;
  - `App.getAssetMgr().getCompatibilityBasePathForNode(figure)`;
  - `getAssetUriForNode(item)`;
  - `findAssetsForFile(relPath, true, true)` → each asset's `compatibilityBase`, `compatibilities`, `contentType`, product name / SKU (via the asset's product container);
  - `searchForAssets("ponytail", [], [], [], <sort>)` result shape and whether it works with CMS off;
  - how a follower is found: `DzFigure.getFollowTarget()` on items;
  - fitting: (a) load with nothing selected then `item.setFollowTarget(figure)` (+ parent to figure); (b) load with figure as sole primary selection. Record whether either shows a dialog for a compatible item, and which nodes a wearables preset adds (roots, parents).
- [ ] **Step 2: Run on DS4, then (after the user switches Studio) on DS6**

Run: `python tests/live_probe_asset_apis.py --figure-label Abby --hair-path "/People/Genesis 9/Hair/..." ...`
Expected: JSON printed, no modal in Studio.

- [ ] **Step 3: Record findings in spec §15; fix §6.3 prefixes; pick the fitting method** (state it in §15; Task 11 implements it).
- [ ] **Step 4: Commit** `git commit -m "test: live probe of asset/compat/fitting APIs (5d6f.21)"`

---

### Task 2: Shared asset reference schema and `AssetRef`

**Files:**
- Create: `schemas/asset-ref.v1.schema.json`, `dazpy/schemas/asset-ref.v1.schema.json` (identical copy), `dazpy/_asset_ref.py`
- Test: `tests/test_asset_ref.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class ResolvedPin:  path: str; sku: str | None = None; product: str | None = None; asset_id: str | None = None
  @dataclass(frozen=True)
  class AssetRef:
      path: str | None = None; product: str | None = None; sku: str | None = None
      find: str | None = None; file: str | None = None; type: str | None = None
      resolved: ResolvedPin | None = None
      def to_dict(self) -> dict | str   # str when only `path` is set (round-trips shorthand)
      @property
      def kind(self) -> Literal["path", "sku", "product", "find"]   # precedence §4
  def parse_ref(value: str | Mapping) -> AssetRef        # assumes already validated
  def ref_issues(value: object, path: str) -> list[RecipeIssue]   # code "invalid_asset_ref" / "invalid_type"
  ```

- [ ] **Step 1: Failing tests**
  - `test_string_is_path_shorthand`: `parse_ref("/People/x.duf") == AssetRef(path="/People/x.duf")`; `.kind == "path"`; `.to_dict() == "/People/x.duf"`.
  - `test_precedence`: `AssetRef(path="a", sku="1", find="f").kind == "path"`; `AssetRef(sku="1", product="P").kind == "sku"`; `AssetRef(product="P", find="f").kind == "product"`.
  - `test_resolved_only_is_invalid`: `ref_issues({"resolved": {"path": "a"}}, "x")[0].code == "invalid_asset_ref"`.
  - `test_unknown_field_rejected`: `ref_issues({"path": "a", "bogus": 1}, "x")` has code `unknown_field` (same code the recipe validator uses for unknown keys).
  - `test_schema_matches_validator` (skip without jsonschema): every case in `tests/fixtures/asset_refs/{valid,invalid}/*.json` is accepted/rejected identically by schema and `ref_issues`. Create ≥4 valid (string, sku+file, find+type, path+resolved) and ≥3 invalid (empty object, resolved only, non-string find).
  - `test_schema_copies_identical`: the two schema files are byte-equal.
- [ ] **Step 2: Run** `python -m pytest tests/test_asset_ref.py -v` → FAIL (module missing)
- [ ] **Step 3: Implement** schema (`$id` `https://bluemoonfoundry.github.io/schemas/asset-ref.v1.schema.json`, `oneOf` string | object with `anyOf` required of path/product/sku/find, `additionalProperties: false`) and `_asset_ref.py`.
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `feat(dazpy): shared asset reference schema and AssetRef (5d6f.21)`

---

### Task 3: Content types

**Files:**
- Create: `dazpy/_content_types.py`
- Test: `tests/test_content_types.py`

**Interfaces:**
- Produces:
  ```python
  FRIENDLY_TYPES: Mapping[str, tuple[str, ...]]     # §6.3 (as corrected by Task 1)
  def type_prefixes(t: str) -> tuple[str, ...]      # friendly -> prefixes; raw "Follower/..." -> (t,)
  def type_matches(t: str, presentation_type: str | None) -> bool   # prefix match on "/" boundary; empty/None never matches
  def is_known_type(t: str) -> bool                 # friendly name or contains "/"
  ```

- [ ] **Step 1: Failing tests**
  - `test_friendly_hair`: `type_matches("hair", "Follower/Hair")` and `type_matches("hair", "Follower/Hair/Accessory")`.
  - `test_prefix_boundary`: `not type_matches("Follower/Hat", "Follower/Hatband")`.
  - `test_raw_type`: `type_matches("Follower/Wardrobe/Dress", "Follower/Wardrobe/Dress")`.
  - `test_empty_never_matches`: `not type_matches("wardrobe", "")`, `not type_matches("wardrobe", None)`.
  - `test_bottom_two_prefixes`: `type_matches("bottom", "Follower/Wardrobe/Skirt")`.
  - `test_unknown_friendly`: `not is_known_type("hairs")`.
- [ ] **Step 2: Run** `python -m pytest tests/test_content_types.py -v` → FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `feat(dazpy): content-type names and matching (5d6f.21)`

---

### Task 4: Recipe v2 schema, model and offline validation

**Files:**
- Create: `schemas/scene-recipe.v2.schema.json`, `dazpy/schemas/scene-recipe.v2.schema.json`
- Modify: `dazpy/_recipe_model.py`, `dazpy/_recipe_validate.py`, `dazpy/recipe.py` (`_SCHEMA_VERSIONS = (1, 2)`)
- Test: `tests/test_recipe_validate.py`, `tests/test_recipe_model.py`, fixtures `tests/fixtures/recipes/v2/{valid,invalid}/`

**Interfaces:**
- Consumes: `AssetRef`, `parse_ref`, `ref_issues` (Task 2); `is_known_type` (Task 3).
- Produces (model):
  ```python
  Selector = str | TypeSelector             # str = exact Scene-pane label
  @dataclass(frozen=True) class TypeSelector: type: str
  @dataclass(frozen=True)
  class WearingEntry:
      op: Literal["add", "replace", "remove"]
      key: str | None                         # required for add/replace
      ref: AssetRef | None                    # add: the item; replace: `with`
      target: Selector | None                 # replace/remove
      if_missing: Literal["error", "add", "ignore"] = "error"
  AssetSpec.path -> AssetSpec.ref: AssetRef  (top-level `assets` entries; string still accepted)
  ActorSpec: asset: str | AssetRef | None  (str = key into `assets` when it names one, else path ref)
             node: str | None = None
             presets: tuple[AssetRef, ...] = ()
             wearing: tuple[WearingEntry, ...] = ()
             position: Vec3T | None = None   # None = "not set" (v1 default (0,0,0) applied in compute_desired for non-taken-over actors)
  PropSpec.asset: str | AssetRef
  def actor_ref(recipe: SceneRecipe, key: str) -> AssetRef | None   # resolves `assets` indirection
  ```
  JSON for wearing entries exactly as spec §6.1: `{"add": REF, "key": K}`, `{"replace": SEL, "with": REF, "key": K, "if_missing"?: "add"}`, `{"remove": SEL, "if_missing"?: "ignore"}`; `SEL` = string or `{"type": T}`.
- Validator rules (v2 only; v1 unchanged, v2 fields in a v1 recipe → `unknown_field`):
  - `recipe_version` ∈ {1, 2}; message for other values lists both.
  - actor requires `asset` or `node`; `wearing` keys unique per actor (`duplicate_key`), match `^[A-Za-z0-9_-]{1,64}$`; `add`/`replace` need `key`; `if_missing` allowed values per op (`add`/`ignore` only on replace/remove respectively, else `invalid_value`); unknown friendly type → `invalid_value` with `allowed` = friendly names.

- [ ] **Step 1: Failing tests**
  - `test_v1_fixtures_unchanged`: every existing `tests/fixtures/recipes/valid/*.json` loads; `to_dict()` round-trips byte-identically to v1 (string asset stays string).
  - `test_v2_abby_round_trip`: fixture `v2/valid/abby.json` (actor with `node`, `asset` product ref, one preset path, wearing replace-by-type + add outfit + remove hat) → `SceneRecipe.from_dict(d).to_dict() == d`.
  - `test_wearing_parsed`: `recipe.actors["abby"].wearing[0] == WearingEntry(op="replace", key="hair", ref=AssetRef(find="Bunched Hair Updo"), target=TypeSelector("hair"))`.
  - `test_v2_field_in_v1_rejected`: v1 recipe with `actors.a.node` → code `unknown_field`.
  - invalid fixtures (each with `.expected.json`, same convention as v1): `add_without_key`, `duplicate_wearing_key`, `bad_type_name`, `replace_if_missing_ignore`, `actor_without_asset_or_node`, `bad_asset_ref`, `version_3`.
  - `test_v2_schema_agrees` (skip without jsonschema): same agreement test as v1 over `v2/` fixtures, with cross-reference codes exempt.
- [ ] **Step 2: Run** `python -m pytest tests/test_recipe_validate.py tests/test_recipe_model.py -v` → new tests FAIL
- [ ] **Step 3: Implement** schema v2 (copy v1, extend `$defs.actor`, `$defs.asset` → `$ref` to asset-ref schema inlined as `$defs.assetRef`), model, validator.
- [ ] **Step 4: Run** full unit suite `python tests.py unit` → PASS
- [ ] **Step 5: Commit** `feat(dazpy): scene recipe v2 schema and model for asset refs, presets, wearing (5d6f.21)`

---

### Task 5: Finders

**Files:**
- Create: `dazpy/_asset_finder.py`
- Test: `tests/test_asset_finder.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class AssetCandidate: path: str; product: str | None; sku: str | None; asset_id: str | None; type: str | None; score: float = 0.0
  class FinderUnavailable(DazError): ...
  class AssetFinder(Protocol):
      name: str                                          # "studio" | "content_browser"
      def search(self, phrase: str, *, type: str | None, limit: int = 10) -> list[AssetCandidate]
      def product_files(self, *, sku: str | None = None, product: str | None = None) -> list[AssetCandidate]
  class StudioFinder:            name = "studio";          def __init__(self, client: DazClient)
  class ContentBrowserFinder:    name = "content_browser"; def __init__(self, url: str, token: str | None = None, timeout: float = 10.0)
  def select_finder(client: DazClient, finder: AssetFinder | None = None,
                    env: Mapping[str, str] = os.environ) -> tuple[AssetFinder, list[RecipeIssue]]
  ```
  - `StudioFinder` raises `FinderUnavailable("content_database_unavailable")` when the CMS is off (script returns `{"cms": false}`); uses the calls Task 1 confirmed.
  - `ContentBrowserFinder`: `POST {url}/api/v1/query` `{"prompt": phrase, "limit": limit}` (add `compatible_figure`/category filters only if Task 1/the browser supports them), `GET {url}/api/v1/products/{sku}/assets`; candidates use each file's `resolved_path` when set else `path + "/" + filename` content-relative; connection error / non-2xx → `FinderUnavailable`.
  - `select_finder`: explicit → as-is, no probe. Else if `DAZ_BROWSER_URL` set: probe `GET {url}/api/v1/filters` once with a 2 s timeout (cheap; `/info` is documented as expensive); on failure return `StudioFinder` + warning `finder_fallback`. Else `StudioFinder`.

- [ ] **Step 1: Failing tests**
  - `test_studio_search_parses_script_result`: fake client returning `{"cms": true, "assets": [{"path": "/People/G9/Hair/x.duf", "product": "Flirty Casual Ponytail", "sku": "123", "type": "Follower/Hair"}]}` → one `AssetCandidate` with those values; the executed script contains `searchForAssets`.
  - `test_studio_cms_off_raises`: `{"cms": false}` → `FinderUnavailable` whose message contains `content_database_unavailable`.
  - `test_content_browser_search` and `test_content_browser_product_files`: local `http.server` on an ephemeral port serving canned JSON (shape from `daz-content-browser/src/api/schemas.py` `Product`, `AssetFiles`); token sent as `Authorization: Bearer t`.
  - `test_select_explicit_wins`, `test_select_env_down_falls_back` (env URL to a closed port → `StudioFinder`, warnings `[finder_fallback]`), `test_select_env_up` (server up → `ContentBrowserFinder`).
- [ ] **Step 2: Run** `python -m pytest tests/test_asset_finder.py -v` → FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `feat(dazpy): pluggable asset finders (Studio CMS, content browser) (5d6f.21)`

---

### Task 6: Reference resolution

**Files:**
- Create: `dazpy/_asset_resolve.py`
- Test: `tests/test_asset_resolve.py`

**Interfaces:**
- Consumes: `AssetRef` (2), `type_matches` (3), finders (5), `resolve_files` (`dazpy/_recipe_ops.py:315`).
- Produces:
  ```python
  @dataclass(frozen=True)
  class ResolvedAsset:
      requested: AssetRef; path: str            # absolute file on the Studio host
      sku: str | None; product: str | None; asset_id: str | None
      type: str | None; finder: Literal["path", "studio", "content_browser", "pin", "record"]
      def to_dict(self) -> dict                 # the `source` shape of spec §9 minus fitted_to/group/primary
  @dataclass(frozen=True)
  class ResolveReport:
      resolved: dict[str, ResolvedAsset]        # keyed by recipe path of the ref, e.g. "actors.abby.wearing.hair"
      errors: tuple[RecipeIssue, ...]; warnings: tuple[RecipeIssue, ...]; finder: str
  def recipe_refs(recipe: SceneRecipe) -> list[tuple[str, AssetRef]]
      # every ref with its recipe path: actors.<a>.asset, actors.<a>.presets.<i>, actors.<a>.wearing.<key>,
      # props.<p>.asset, assets.<k> (only if referenced). Not pose/HDRI (they stay plain files, v1 path).
  def resolve_refs(client: DazClient, refs: list[tuple[str, AssetRef]], finder: AssetFinder,
                   prior: Mapping[str, dict] | None = None) -> ResolveReport
      # prior: recipe path -> recorded `source` dict (from EntityRecord) for reuse (§5 stability)
  ```
- Rules (all from spec §4–§5):
  - Order per ref: `prior` reuse if `prior[p]["requested"] == ref.to_dict()` and its path still resolves (`finder="record"`); else pin (`ref.resolved`) if its path resolves (`finder="pin"`; cross-check mismatches → `pin_mismatch` warning; missing → `pin_file_missing` warning, continue); else by `kind`.
  - `path`: `resolve_files`; missing → `asset_not_found`.
  - `sku`/`product`: `finder.product_files`; filter by `file` (match content-relative path or filename, case-insensitive) then `type`; exactly one → ok; zero → `asset_not_found`; several → `ambiguous_asset` with `allowed` = up to 10 candidate paths.
  - `find`: `finder.search(phrase, type=ref.type)`; then filter by `type`; winner = the single candidate whose `product` equals the phrase case-insensitively, else the only candidate; else `ambiguous_asset` listing up to 10 as `"<product> (<sku>): <path>"`. Product with several files → treat as several candidates.
  - `FinderUnavailable` → one `content_database_unavailable` error per non-path ref; path refs unaffected.
  - All candidate paths go through one batched `resolve_files` call at the end; unresolvable → `asset_not_found`.

- [ ] **Step 1: Failing tests** (fake finder class in the test module; fake client from `recipe_fakes` extended with a `resolve` answer for `recipe:resolve` scripts — add `fake_resolve_client(found: dict[str,str])` helper to `tests/recipe_fakes.py`)
  - `test_path_ref`, `test_path_missing_is_asset_not_found`
  - `test_find_exact_name_beats_fuzzy` (Review Focus 2): candidates "Bunched Hair Updo", "Bunched Hair Updo Texture Add-on", "Bun Updo" → resolves to the first; no errors.
  - `test_find_ambiguous_lists_candidates`: two non-exact → error `ambiguous_asset`, `allowed` has both.
  - `test_find_type_filter`: phrase matches a hair and a top; `type="hair"` → hair.
  - `test_sku_multi_file_needs_file`: 2 files → `ambiguous_asset`; with `file="Updo.duf"` → that file.
  - `test_pin_used_without_search`: finder `search` not called.
  - `test_pin_missing_falls_back`: warning `pin_file_missing`, resolved via find.
  - `test_record_reuse`: prior source with identical requested → `finder == "record"`, finder not called; changed requested → fresh.
  - `test_finder_unavailable`: product ref → `content_database_unavailable`; path ref in same call still resolved.
- [ ] **Step 2: Run** `python -m pytest tests/test_asset_resolve.py -v` → FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `feat(dazpy): resolve asset references with pins, record reuse and ambiguity errors (5d6f.21)`

---

### Task 7: Live scene readback for figures and fitted items

**Files:**
- Create: `dazpy/_recipe_fitted.py`
- Modify: `dazpy/_recipe_store.py` (`EntityRecord` new fields; `read_live` grouping)
- Test: `tests/test_recipe_fitted.py`, `tests/test_recipe_store.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class FittedItem:
      name: str; label: str; type: str | None; source_path: str | None   # getAssetUriForNode file part
      record: EntityRecord | None; foreign_children: tuple[str, ...]
  @dataclass(frozen=True)
  class FigureInfo:
      name: str; label: str; record: EntityRecord | None
      compat_base: str | None; items: tuple[FittedItem, ...]
  def figures_script(labels: list[str], owned_names: list[str]) -> str
  def read_figures(client: DazClient, labels: list[str], owned_names: list[str]) -> dict[str, list[FigureInfo]]
      # label -> every figure with that exact label (len > 1 → ambiguous), plus owned_names (by getName())
  ```
  `EntityRecord` gains (defaulted, JSON-backward-compatible): `source: dict | None = None`, `group: str | None = None`, `primary: bool = True`, `adopted_from_scene: bool = False`, `done: tuple[dict, ...] = ()` (one-shot log on actor records: `{"entry": key_or_index, "op", "removed": [{"label","type","source_path"}]}`).
  `read_live`: several nodes with the same record path **and** a non-null `group` equal to that path are one group, not a `DuplicateRecord`; `LiveEntity` gains `group_nodes: tuple[str, ...] = ()` (all node names, primary first).
  Fitted = node whose `getFollowTarget()` (or method chosen in Task 1) is the figure, plus their non-fitted descendants counted as part of the item unless they carry a record of their own (then foreign).

- [ ] **Step 1: Failing tests**
  - `test_record_backward_compatible`: `EntityRecord.from_json(<v1 json>)` → new fields default; round-trip of a record with `source`/`group` preserves them.
  - `test_group_not_duplicate`: canned nodes `hair` and `cap` both recorded `actors.abby.wearing.hair` with `group` set → one `LiveEntity`, `group_nodes == ("hair", "cap")`, `duplicates == ()`.
  - `test_same_path_without_group_is_duplicate`: unchanged v1 behavior.
  - `test_read_figures_by_label`: fake client payload → `FigureInfo` with items typed; two figures labelled "Abby" → list length 2.
  - `test_figures_script_case_sensitive`: generated script compares `getLabel() === label` (string match in script text).
- [ ] **Step 2: Run** `python -m pytest tests/test_recipe_fitted.py tests/test_recipe_store.py -v` → FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run** `python tests.py unit` → PASS
- [ ] **Step 5: Commit** `feat(dazpy): read figures, fitted items and record groups (5d6f.21)`

---

### Task 8: Compatibility check

**Files:**
- Create: `dazpy/_asset_compat.py`
- Test: `tests/test_asset_compat.py`

**Interfaces:**
- Consumes: `ResolvedAsset` (6), `FigureInfo` (7).
- Produces:
  ```python
  @dataclass(frozen=True)
  class CompatInfo: path: str; bases: tuple[str, ...]; known: bool      # file's compatibilities
  def compat_script(paths: list[str]) -> str
  def read_compat(client: DazClient, paths: list[str]) -> dict[str, CompatInfo]
  def base_of_asset(client: DazClient, path: str) -> str | None           # figure base for an actor the recipe will create
  def is_compatible(target_base: str, item_bases: tuple[str, ...]) -> bool
      # true if target_base equals a base or is a descendant path of one ("/Genesis 9/Female" under "/Genesis 9")
  def check_compat(target_base: str | None, items: Mapping[str, ResolvedAsset],
                   info: Mapping[str, CompatInfo]) -> tuple[list[RecipeIssue], list[RecipeIssue]]
      # (errors incompatible_asset, warnings compatibility_unknown); unknown target base → every item warns
  ```
  `incompatible_asset` message: `"<product or path> is made for <bases joined>; actor '<key>' is <target_base>"`; issue path = the ref's recipe path.

- [ ] **Step 1: Failing tests**
  - `test_descendant_base_compatible`: `is_compatible("/Genesis 9/Female", ("/Genesis 9",))`.
  - `test_other_generation_incompatible`: `not is_compatible("/Genesis 9", ("/Genesis 8/Female",))`.
  - `test_check_compat_errors_and_warnings`: one G8 hair → `incompatible_asset` at `actors.abby.wearing.hair`; one unknown shape → `compatibility_unknown`.
  - `test_compat_script_reads_metadata_only`: script text contains `findAssetsForFile` and does not contain `openFile`, `loadScene` or `mergeFile`.
- [ ] **Step 2: Run** `python -m pytest tests/test_asset_compat.py -v` → FAIL
- [ ] **Step 3: Implement** (presentation `preferredBase`/`extendedBases` fallback per Task 1 findings)
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `feat(dazpy): compatibility check before load (5d6f.21)`

---

### Task 9: Desired state for layered actors and items

**Files:**
- Modify: `dazpy/_recipe_desired.py`
- Test: `tests/test_recipe_desired.py`

**Interfaces:**
- Consumes: model (4), `ResolvedAsset` (6).
- Produces: `compute_desired(recipe: SceneRecipe, resolved: Mapping[str, ResolvedAsset] | None = None) -> dict[str, DesiredEntity]` (`None` keeps v1 behavior: `asset_path` from the path ref). `EntityKind` adds `"item"`.
  - Actor `create`: `{"asset_path": <resolved path or None>, "take_over": <node label or None>, "label": <node or v1 label>}`; channels: `transform` only when the actor is not taken over or `position`/`rotation`/`facing` is set (else omitted), `pose` as v1, new `presets`: `{"paths": [resolved preset paths in order]}` (omitted when no presets).
  - Item entity per `add`/`replace` entry: path `actors.<a>.wearing.<key>`, kind `"item"`, label `f"{recipe.id}:{a}.{key}"`, `create = {"asset_path": p, "fit_to": "actors.<a>", "source": resolved.to_dict()}`, `channels = {}`.
  - Desired dict order: actors before their items (executor relies on it).

- [ ] **Step 1: Failing tests**
  - `test_v1_unchanged`: existing tests pass with `resolved=None`.
  - `test_taken_over_actor_without_position_has_no_transform`: `"transform" not in d["actors.abby"].channels`; `create["take_over"] == "Abby"`.
  - `test_created_actor_default_position`: no `node` → transform position `(0,0,0)` as v1.
  - `test_items_from_wearing`: replace+add entries → `actors.abby.wearing.hair`, `actors.abby.wearing.outfit` with `fit_to == "actors.abby"`; `remove` entry produces no entity.
  - `test_presets_channel_order`.
- [ ] **Step 2: Run** `python -m pytest tests/test_recipe_desired.py -v` → FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `feat(dazpy): desired state for taken-over actors, presets and fitted items (5d6f.21)`

---

### Task 10: Planning take-over and one-shot selectors

**Files:**
- Create: `dazpy/_recipe_wearing.py`
- Test: `tests/test_recipe_wearing.py`

**Interfaces:**
- Consumes: model (4), `FigureInfo` (7), `type_matches` (3).
- Produces:
  ```python
  @dataclass(frozen=True)
  class TakeOver: actor_path: str; node_name: str          # figure to adopt (no record yet)
  @dataclass(frozen=True)
  class Unfit: actor_path: str; entry: str; node_names: tuple[str, ...]
               removed: tuple[dict, ...]                      # {"label","type","source_path"} for done-log + restore
  @dataclass(frozen=True)
  class WearingPlan: take_overs: tuple[TakeOver, ...]; unfits: tuple[Unfit, ...]
                     errors: tuple[RecipeIssue, ...]; conflicts: tuple[Conflict, ...]; warnings: tuple[RecipeIssue, ...]
  def plan_wearing(recipe: SceneRecipe, figures: Mapping[str, list[FigureInfo]],
                   live: LiveState) -> WearingPlan
  ```
  Rules (§6.2, §6.4):
  - Actor with `node`: if `live.entities` has the actor path → already owned, no take-over. Else figures[label]: 1 → `TakeOver`; >1 → `ambiguous_node`; 0 → create from `asset` (no TakeOver), or `node_not_found` error when the actor has no `asset`. Matching is exact (§6.1); when 0 match but a figure label is close (`_closest`, which includes case-only differences), add warning `similar_node_label` naming it.
  - Taken-over actor whose record `source.requested` differs from the current `asset` ref → `take_over_asset_changed` error.
  - Entry is one-shot-done when the actor record's `done` has its entry id (`key` or `"remove.<index>"`) → skipped.
  - Otherwise simulate in list order over the actor's current items minus recipe-owned ones: selector matches (label exact / `type_matches`) → `Unfit`; matched items removed from the simulated list for later entries. Zero matches → `replace_target_missing` / `remove_target_missing` unless `if_missing` (`add` → no Unfit, item still added; `ignore` → nothing, entry marked done).
  - Matched item with `foreign_children` → `Conflict(path=f"{actor}.wearing.{entry}", kind="has_foreign_children", ...)`.
  - `source_path is None` for a matched item → warning `unrestorable_removal`.

- [ ] **Step 1: Failing tests**
  - `test_take_over_single_label`, `test_ambiguous_label`, `test_label_case_mismatch_creates_and_warns` (Review Focus 1: figure "Abby", recipe `node: "abby"` with asset → no TakeOver, warning `similar_node_label` mentioning "Abby"), `test_label_missing_without_asset_errors` (`node_not_found`)
  - `test_replace_by_type_matches_all_hair`: two hair items → one `Unfit` with both names.
  - `test_owned_items_never_selected`
  - `test_replace_missing_errors` / `test_if_missing_add` / `test_remove_if_missing_ignore`
  - `test_list_order_simulation`: `remove: "Hat A"` then `replace: {type: hat}` → second sees no hat → `replace_target_missing`.
  - `test_done_entries_skipped` (Review Focus 4): actor record `done` contains `"hair"`, scene has new hand-loaded hair → no Unfit, no error.
  - `test_foreign_children_conflict`, `test_unrestorable_warning`, `test_take_over_asset_changed`.
- [ ] **Step 2: Run** `python -m pytest tests/test_recipe_wearing.py -v` → FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `feat(dazpy): plan actor take-over and one-shot replace/remove (5d6f.21)`

---

### Task 11: Scene ops — take over, presets, fit (multi-node), unfit, restore

**Files:**
- Modify: `dazpy/_recipe_ops.py` (`SceneOps` protocol + `DazSceneOps`), `tests/recipe_fakes.py` (fake ops used by `test_recipe_apply.py`)
- Test: `tests/test_recipe_ops.py`

**Interfaces:**
- Consumes: Task 1 fitting method; `DesiredEntity` item shape (9).
- Produces (`SceneOps` additions):
  ```python
  def take_over(self, node_name: str) -> None                       # no scene change; validates node exists
  def apply_presets(self, node_name: str, paths: list[str]) -> None  # in order, figure as sole primary selection, prior selection restored (like _pose_preset_script)
  def fit(self, entity: DesiredEntity, figure_name: str) -> list[str]
      # load create["asset_path"], fit every added node to figure; returns all added root names, primary first
  def unfit(self, node_names: list[str]) -> None                     # one exact-selection delete
  def restore(self, source_paths: list[str], figure_name: str) -> list[str]   # reload + fit, for rollback of removals
  ```
  `fit` rules: snapshot before/after (existing `_SNAPSHOT_SCRIPT`); every added root must end up fitted to `figure_name` (or be a descendant of one that is); otherwise remove all added (existing `_remove_added`) and raise `DazError("<path>: loading it added nodes that are not fitted to <figure>: <names>; every node it added was removed")`. Added nodes are made uniquely named (reuse `_claim_script` naming part), first gets label `entity.label`.

- [ ] **Step 1: Failing tests** (script-level, fake client)
  - `test_fit_multi_node_returns_all`: fake reports two new nodes both fitted → returns both, primary first.
  - `test_fit_stray_node_removes_all` (Review Focus 3): one new node unfitted → `DazError`, a delete script for both names was executed.
  - `test_unfit_single_delete`: one `DzDeleteAction` script with both names.
  - `test_apply_presets_order_and_selection_restore`: scripts in order; each script restores previous primary selection.
  - `test_no_modal_prone_calls`: no generated script contains `Scene.removeNode` or loads while another *figure* is selected (assert the selection-clear line precedes the load in `fit`, per Task 1 method).
- [ ] **Step 2: Run** `python -m pytest tests/test_recipe_ops.py -v` → FAIL
- [ ] **Step 3: Implement** in `DazSceneOps`; add the same methods to the fake ops in `tests/recipe_fakes.py` (recording calls, configurable failures).
- [ ] **Step 4: Run** `python tests.py unit` → PASS
- [ ] **Step 5: Commit** `feat(dazpy): scene ops for take-over, presets, multi-node fit and unfit (5d6f.21)`

---

### Task 12: Diff and executor integration

**Files:**
- Modify: `dazpy/_recipe_diff.py`, `dazpy/_recipe_apply.py`
- Test: `tests/test_recipe_diff.py`, `tests/test_recipe_apply.py`

**Interfaces:**
- Consumes: Tasks 7, 9, 10, 11.
- Produces:
  - `StepOp` adds `"take_over"`, `"preset"`, `"fit"`, `"unfit"`. `_STEP_ORDER` = `create, take_over, preset, fit, modify, set_environment, adopt, release, unparent, unfit, delete` (removes last, §8).
  - `diff(desired, live, *, on_conflict, resolutions, wearing: WearingPlan | None = None) -> RecipePlan`: item entities produce `fit` (not `create`); item asset change = replace → `fit` new + `delete` old group; take-overs → `take_over` steps; `wearing.unfits` → `unfit` steps; `wearing.conflicts` join the conflict list (so `ask` blocks); preset channel change → `preset` step (dropped presets → `preset_dropped` warning, no step).
  - Removing a taken-over actor (record `adopted_from_scene`) from the recipe → `release`, never `delete`.
  - Deleting any node of an owned group by hand → `deleted_in_scene` for the item path.
  - Executor: `take_over` writes the record (`adopted_from_scene=True`, `source` from `getAssetUriForNode` if Task 7 read it); `fit` calls `ops.fit` with the actor's node name (created earlier in the same run or live), writes one record per node with `group=path`, `primary` on first, `source = create["source"] | {"fitted_to": actor key, "group": path}`; `unfit` calls `ops.unfit` and appends to the actor record's `done`; rollback of an `unfit` calls `ops.restore(source_paths, figure)`; rollback of `fit` deletes the group; failure before the unfit phase leaves unfit targets untouched (they have not run).

- [ ] **Step 1: Failing tests**
  - diff: `test_step_order_removes_last`, `test_item_create_is_fit`, `test_item_asset_change_fits_then_deletes_group`, `test_unfit_steps_from_wearing_plan`, `test_wearing_conflict_blocks_ask`, `test_removed_taken_over_actor_released_not_deleted`, `test_group_node_deleted_by_hand_is_deleted_in_scene`, `test_preset_dropped_warns`, `test_unchanged_recipe_zero_steps_after_replace` (Review Focus 4, with `done` populated).
  - apply (fake ops): `test_fit_writes_group_records_with_source`, `test_fit_failure_leaves_hand_hair` (fit raises → `unfit` never called, `ops.restore` never called, created actor rolled back), `test_unfit_failure_restores_removed` (second unfit raises → `restore` called for the first's source paths), `test_take_over_record_adopted`.
- [ ] **Step 2: Run** `python -m pytest tests/test_recipe_diff.py tests/test_recipe_apply.py -v` → FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run** `python tests.py unit` → PASS
- [ ] **Step 5: Commit** `feat(dazpy): plan and execute fit/unfit/take-over/preset steps with rollback (5d6f.21)`

---

### Task 13: Facade — validate, plan, apply, observe, pin

**Files:**
- Modify: `dazpy/recipe.py`, `dazpy/__init__.py` (export `pin`, `AssetRef`, `AssetFinder`, `StudioFinder`, `ContentBrowserFinder`), `dazpy/exceptions.py` if a new error type is needed
- Test: `tests/test_recipe_facade.py`

**Interfaces:**
- Produces:
  ```python
  def validate(recipe, scene=None, *, finder: AssetFinder | None = None) -> ValidationReport
  def plan(recipe, scene, *, on_conflict="ask", resolutions=None, finder=None) -> RecipePlan
  def apply(recipe, scene, *, on_conflict="ask", resolutions=None, finder=None, ...) -> ApplyResult
  def observe(recipe, scene, *, finder=None) -> ObserveReport
  def pin(recipe: SceneRecipe | dict, scene: DazScene, *, finder: AssetFinder | None = None) -> dict
  ```
  Pipeline for `plan`/`apply` (§8): offline validate → `read_live` → `select_finder` → `resolve_refs(prior=sources from live records)` → `read_figures` → `read_compat` + `check_compat` per actor (target base: live figure `compat_base`, or `base_of_asset` for actors to be created) → `compute_desired(model, resolved)` → `plan_wearing` → `diff(..., wearing=...)` → execute. Any resolve/compat/wearing **error** raises `RecipeValidationError` before any scene change, from both `plan` and `apply` (as both already do for invalid recipes). Warnings go into `RecipePlan.warnings` (and so `ApplyResult`). `RecipePlan` gains `finder: str = "path"` naming the finder that answered.
  `validate(recipe, scene)` adds resolution + compatibility issues (no live figure needed for created actors; taken-over actors use `read_figures`).
  `observe`: an owned item group whose nodes are gone → missing (existing behavior); a recipe-owned item node whose `getAssetUriForNode` file differs from its `source.resolved.path` → drift entry `source_changed`.
  `pin`: returns `recipe.to_dict()` with every ref's `resolved` filled (string refs become objects).

- [ ] **Step 1: Failing tests** (fake client + fake finder through `finder=`)
  - `test_validate_reports_ambiguous_find`, `test_validate_reports_incompatible`, `test_apply_incompatible_changes_nothing` (no load/delete script executed), `test_plan_names_finder`, `test_pin_fills_resolved`, `test_validate_env_browser_down_warns` (Review Focus 5: `DAZ_BROWSER_URL` to closed port, product ref resolved by fake Studio CMS answer, warning `finder_fallback`, no exception), `test_observe_source_changed`.
- [ ] **Step 2: Run** `python -m pytest tests/test_recipe_facade.py -v` → FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run** `python tests.py unit` → PASS
- [ ] **Step 5: Commit** `feat(dazpy): recipe facade resolves, checks compatibility and pins references (5d6f.21)`

---

### Task 14: Live acceptance on DS4 and DS6, docs

**Files:**
- Modify: `tests/test_recipe_live.py` (new class `AssetFittingLiveTests`), `docs/scene_recipes.rst` (new sections: Asset references, Finders, Actors in layers, Fitted items, Compatibility, Provenance, v1→v2), `dazpy/README.md` (short section), `CHANGELOG.md`, `tests/fixtures/recipes/v2/valid/abby_live.json` (content paths configurable by env: `DAZ_LIVE_G9F`, `DAZ_LIVE_HAIR_A`, `DAZ_LIVE_HAIR_B`, `DAZ_LIVE_HAIR_MULTI`, `DAZ_LIVE_OUTFIT`, `DAZ_LIVE_G8_HAIR`; tests skip when unset)
- Test: live

- [ ] **Step 1: Write live tests** mirroring spec §12:
  `test_empty_scene_build_abby`, `test_take_over_hand_built_and_swap_hair_by_type`, `test_g8_hair_rejected_scene_unchanged` (node count and labels equal before/after; no modal = call returns within timeout), `test_ambiguous_find_changes_nothing`, `test_fit_failure_keeps_hand_hair` (monkeypatch `DazSceneOps.fit` to raise on its second call, after the first real fit), `test_multi_node_hair_and_outfit_add_swap_remove`, `test_records_have_source`.
- [ ] **Step 2: Run on DS4**

Run: `python -m pytest tests/test_recipe_live.py -k AssetFitting -v` (Studio running, env vars set)
Expected: all PASS. Ask the user to switch to DS6 (never close Studio programmatically), re-run, expect PASS.

- [ ] **Step 3: Write docs** (every error/warning code listed with meaning; Abby example from spec §1 as the worked example).
- [ ] **Step 4: Run** `python tests.py unit` and `python scripts/check_openapi_parity.py` → PASS (no route changes expected)
- [ ] **Step 5: Commit** `test/docs: live acceptance and docs for asset refs and fitting (5d6f.21)`

---

### Task 15: daz-content-browser-mcp emits `asset_ref`

Repo: `Y:/working/BlueMoonFoundry/daz-content-browser-mcp` (own branch `feature/asset-ref`).

**Files:**
- Modify: `src/daz_content_browser_mcp/client.py` (`get_assets`), `src/daz_content_browser_mcp/server.py` (`get_product_assets` docstring), `README.md`
- Test: `tests/test_tools.py`, `tests/test_client.py`

**Interfaces:**
- Produces: every file in `get_product_assets` results gains `"asset_ref": {"sku": <sku>, "product": <name or omitted>, "path": <path + "/" + filename, content-relative>, "type": <content_type, omitted if null>}` — valid against `asset-ref.v1.schema.json` (vendored copy at `src/daz_content_browser_mcp/asset-ref.v1.schema.json` with a test asserting it equals the daz-script-server copy when that repo is a sibling, skipped otherwise).

- [ ] **Step 1: Check the route** — daz-content-browser serves `GET /api/v1/products/{sku}/assets` (`src/api/routers/products.py:46`); the client calls `/api/v1/assets/{sku}`. Confirm against a running browser (`make demo-server` there); if `/api/v1/assets/{sku}` 404s, switch the client to the products route (test pins the URL).
- [ ] **Step 2: Failing tests** `test_get_product_assets_adds_asset_ref` (respx/mocked transport per existing test style), `test_asset_ref_validates_against_schema`.
- [ ] **Step 3: Run** `python -m pytest -v` → FAIL
- [ ] **Step 4: Implement**; README section "Using results in scene recipes" with one recipe snippet.
- [ ] **Step 5: Run** → PASS; commit `feat: asset_ref in product asset results (daz-script-server-5d6f.21)`.

---

### Task 16: daz-mcp-server accepts v2 recipes

Repo: `Y:/working/BlueMoonFoundry/daz-mcp-server` (own branch `feature/recipe-v2`).

**Files:**
- Modify: `src/daz_mcp_server/tools/recipe.py` (tool docstrings: v2, asset refs, `find`, content-browser refs; schema resources serve v1 and v2; optional `finder` not exposed — env `DAZ_BROWSER_URL` is picked up by dazpy), dependency pin on the new dazpy version in `pyproject.toml`
- Test: `tests/test_recipe_tools.py`

- [ ] **Step 1: Failing tests** `test_schema_resource_v2`, `test_validate_tool_accepts_v2_recipe` (patched dazpy facade, asserts pass-through of a v2 dict).
- [ ] **Step 2: Run** `python -m pytest tests/test_recipe_tools.py -v` → FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `feat: scene recipe v2 (asset refs, fitting) in recipe tools (daz-script-server-5d6f.21)`

---

## Done when

All unit suites green in the three repos, Task 14 live tests pass on DS4 and
DS6, spec §15 records the probe findings, and `bd close daz-script-server-5d6f.21`
(then the epic, which has no other open children).
