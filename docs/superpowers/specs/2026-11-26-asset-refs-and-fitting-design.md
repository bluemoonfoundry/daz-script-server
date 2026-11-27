# Asset References, Compatibility and Fitting for Scene Recipes — Design

Issue: `daz-script-server-5d6f.21` (ASSESSMENT #13). Builds on the scene recipe
design (`2026-11-15-scene-recipe-design.md`) and its implementation in
`dazpy/_recipe_*.py`, `dazpy/recipe.py`, `schemas/scene-recipe.v1.schema.json`.

## 1. Intent

Today a recipe names content only by file path, and the user finds out an asset
was wrong only after it is in the scene: clothing or hair that does not fit, or
Studio's modal "this product is for a different figure" dialog (which also
blocks the main thread while a script is driving Studio).

This work lets a recipe:

1. name content three first-class ways (path, product name/SKU, or a search
   phrase), with one shared reference format that daz-content-browser-mcp also
   emits;
2. check every asset is compatible with its target figure **before the scene
   changes**;
3. build actors in layers (base figure → presets → fitted items) and take over
   actors the user built by hand;
4. add, replace and remove items fitted to an actor (hair, clothing,
   accessories), by exact name or by content type;
5. record where every loaded asset came from.

Driving example (from the user):

- Load a Genesis 9 Female character and name it "Abby".
- Apply the shape `X:/Development/VisualNovelA/shapes/AbbyYoungShape.duf`.
- Find hair "something like Flirty Casual Ponytail" and fit it to Abby.
- Later: change Abby's hair to "Bunched Hair Updo", usually on a scene where
  Abby was built by hand.

## 2. Goals, non-goals, anti-goals

**Goals**

- Shared asset reference format (JSON Schema in this repo), accepted anywhere a
  recipe takes an asset today, and returned by daz-content-browser-mcp.
- Resolution of every reference to one concrete file before any scene change;
  ambiguity is an error that lists the candidates.
- Compatibility check of every preset and fitted item against the target
  actor's figure before any scene change; incompatible = error.
- Actors can be created by the recipe or taken over by Studio node name.
- `add` / `replace` / `remove` operations for fitted items; replace/remove
  targets by exact Scene-pane name or by content type ("whatever hair she has").
- Provenance on every recipe-owned node: what was requested, what it resolved
  to (file, product, SKU), which finder answered, what it is fitted to.
- Pluggable finder for `find:` references: Studio's own content search by
  default, daz-content-browser REST when configured.
- Fitted content that loads several nodes (hair plus a separate cap, outfit /
  wearables presets that load many garments) is supported: one `add` entry
  owns the whole group (§6.6).

**Non-goals (this round)**

- Auto-fit of items made for a different figure (e.g. Genesis 8 clothing on
  Genesis 9). The user may revisit this later as an explicit opt-in.
- dazpy discovering MCP tools. MCP-level search is done by the AI client, which
  then writes a resolved reference into the recipe.
- Managing parts of a taken-over actor the recipe does not mention.
- Multi-root assets for actors and props created at scene root (still
  unsupported, as in v1). Multi-node *fitted* content is in scope (§6.6).

**Anti-goals (failure even if it "works")**

- Any modal dialog popping during validate, plan or apply.
- The scene changing at all when a reference is ambiguous, missing or
  incompatible.
- Silently picking one of several search matches.
- A recipe apply touching hand-built parts of an actor it did not mention.

## 3. Constraints

- All existing recipe constraints stand: frozen dataclass model, JSON Schema as
  the contract, Studio-side file resolution (`resolve_files`), threading rules
  (everything Studio-side runs as DazScript through `/execute`), rollback on
  failure, delete via `DzDeleteAction` on an exact selection (never
  `Scene.removeNode`), merge-load with nothing selected.
- Must work on DS4 and DS6. Every new Studio API used (see §7) must be verified
  live on both early, with `tests/smoke_live.py`-style scoped runs, never the
  full integration suite.
- Never call DazScript that can raise a modal (see memory: blocking dialogs).
  Compatibility is checked by reading metadata, never by attempting a load.
- dazpy must not hard-depend on daz-content-browser; the content-browser finder
  is optional and uses only the stdlib HTTP stack dazpy already uses.

## 4. Asset reference format

New schema `schemas/asset-ref.v1.schema.json` (copied to `dazpy/schemas/` like
the recipe schema). An asset reference is either a plain string (shorthand for
`{"path": ...}`, so every v1 recipe stays valid) or an object:

| Field | Meaning |
|---|---|
| `path` | Content-relative (`/People/...`) or absolute file path |
| `product` | Product name (exact, case-insensitive) |
| `sku` | Product SKU |
| `find` | Free-text search phrase |
| `file` | Disambiguates a file within a product (`product`/`sku`) — content-relative path or filename |
| `type` | Expected content type (friendly name or raw Daz type, §6.3); narrows search and is checked after resolution |
| `resolved` | Optional, written by tools: `{path, sku, product, asset_id}` from a prior resolution |

Rules:

- At least one of `path`, `product`, `sku`, `find` is required.
- Precedence when several are given: `path` > `sku` (+`file`) > `product`
  (+`file`) > `find`. Extra fields act as cross-checks (e.g. `path` plus `sku`:
  error if the file does not belong to that SKU, when the product database can
  tell).
- A product with several loadable files and no `file` (and no `type` that
  narrows it to one) is ambiguous → error listing the files.
- `resolved` is a **pin**: when present and its `path` still resolves on the
  Studio host, it is used without searching; the other fields are
  cross-checked against it and a mismatch is a warning. If the pinned file is
  gone, the reference resolves fresh from its other fields (warning). A ref
  with only `resolved` is invalid (one of `path`/`product`/`sku`/`find` is
  still required, so a ref always says what was meant).
- dazpy offers `pin(recipe, scene) -> dict`: resolves every reference and
  returns the recipe JSON with `resolved` filled in, so users can freeze a
  recipe against library changes. dazpy never rewrites a recipe on its own;
  the stored resolutions used on re-apply live in records (§5, §9).
- daz-content-browser-mcp's `get_product_assets` (and `search_products` where
  it lists files) adds an `asset_ref` object per file in this shape:
  `{"sku", "product", "path", "type"?}`. That is the "shared with
  daz-content-browser-mcp" half of the acceptance criterion; the schema file
  is the single source and that repo references it by URL/version.

## 5. Finders (resolving `find`, `product`, `sku`)

`dazpy` gets a small finder protocol:

```python
class AssetFinder(Protocol):
    name: str
    def search(self, phrase: str, *, type: str | None, figure: str | None,
               limit: int) -> list[AssetCandidate]: ...
    def product_files(self, *, sku: str | None, product: str | None) -> list[AssetCandidate]: ...
```

`AssetCandidate` = `{path, product, sku, asset_id, type, score}`.

- **Default: `StudioFinder`** — Studio's content database via DazScript
  (`DzAssetMgr.searchForAssets` / product lookups). Plain text match. Needs the
  CMS running; if it is not, `find`/`product`/`sku` references fail validation
  with a clear "content database unavailable" error (paths still work).
- **`ContentBrowserFinder`** — daz-content-browser REST API (`POST
  /api/v1/query`, `GET /api/v1/products/{sku}/assets`), configured by URL
  (+ optional token), from an explicit argument or `DAZ_BROWSER_URL` /
  `DAZ_BROWSER_TOKEN` env vars (same names as daz-content-browser-mcp).
- Selection: an explicit `finder=` argument on `validate/plan/apply`, else
  ContentBrowserFinder if configured and reachable, else StudioFinder. An
  unreachable configured content browser falls back to StudioFinder with a
  warning; the report always names the finder that answered.
- **Picking a match:** a search result is accepted only when it is a clear
  single winner. Exact (case-insensitive) product-name match wins outright;
  otherwise one candidate after filtering by `type` and target figure
  compatibility. Anything else → `ambiguous_asset` error with the top
  candidates (name, SKU, path). The builder decides any score-gap heuristic,
  but it must err toward reporting ambiguity.
- **Stability:** once resolved, the exact file/SKU is stored in the node's
  record. On later applies an unchanged reference re-uses the recorded
  resolution (no re-search), so library changes do not silently swap content.
  A changed reference resolves fresh.

## 6. Actors in layers

### 6.1 Schema additions (actor)

```jsonc
"actors": {
  "abby": {
    "node": "Abby",                       // take over this Studio node if present
    "asset": {"product": "Genesis 9 Female"}, // create from this if not present
    "presets": [
      "X:/Development/VisualNovelA/shapes/AbbyYoungShape.duf"
    ],
    "wearing": [
      {"replace": {"type": "hair"}, "key": "hair",
       "with": {"find": "Bunched Hair Updo"}},
      {"replace": "Old Jacket", "key": "jacket", "with": {"sku": "12345"}},
      {"add": {"find": "Summer Outfit", "type": "wardrobe"}, "key": "outfit"},
      {"remove": {"type": "hat"}}
    ],
    "position": [0, 0, 0]
  }
}
```

- `asset` becomes an asset reference (string still accepted). Today `asset`
  names an entry in the top-level `assets` map; that indirection stays valid
  (a top-level `assets` entry becomes an asset reference too), and an inline
  reference is also allowed.
- `node` (optional): the Scene-pane **label** (`getLabel()`) of the figure to
  take over — what the user sees and renames, not `getName()` (which usually
  stays e.g. `Genesis9Female` after a rename). Matching is exact and
  case-sensitive among figure nodes at any depth.
- Every `add` and `replace` entry has a `key` (same pattern as entity keys,
  unique within the actor). It identifies the owned item across applies.
- `presets` (optional): ordered list of asset references applied to the figure
  (shape, materials, etc.).
- `wearing` (optional): ordered list of fitted-item operations.
- Props get `asset` as an asset reference too; nothing else changes for props.

### 6.2 Create vs take over

- After take-over the node carries its record and is found by the record on
  later applies (as v1 does), so a later rename does not lose it. Its
  `getName()` and label are left unchanged.
- `node` given and a figure with that label exists → **take over**. The recipe now
  manages only what it mentions: presets it lists, `wearing` operations, and
  transform/pose **only if the recipe sets them** (for taken-over actors,
  `position` has no implicit `(0,0,0)` default — an omitted transform is left
  alone). The node's record notes `adopted_from_scene: true`; releasing the
  recipe never deletes a taken-over actor.
- `node` given but no such figure → create from `asset`; the label is set to
  `node` (instead of v1's `<recipe id>:<key>`), `getName()` follows v1.
  Error if `asset` is absent.
- `node` absent → create from `asset` exactly as v1 does.
- Two figures with the `node` label (and neither carrying this recipe's
  record) → error (`ambiguous_node`), no change.
- A taken-over actor's base figure is never replaced by the recipe. Changing
  `asset` on a taken-over actor is a validation error, not a delete+create.

### 6.3 Content types

Each Studio node exposes its content type through
`node.getPresentation().type` (e.g. `Follower/Hair`,
`Follower/Wardrobe/Top`). Files in the CMS also carry a `contentType`.
Friendly names map to type prefixes; a raw type string is accepted as-is and
matches as a prefix:

| Friendly | Daz type prefix |
|---|---|
| `hair` | `Follower/Hair` |
| `top` | `Follower/Wardrobe/Shirt`, `Follower/Wardrobe/Outerwear/Top` |
| `bottom` | `Follower/Wardrobe/Pant`, `Follower/Wardrobe/Skirt`, `Follower/Wardrobe/Outerwear/Bottom` |
| `dress` | `Follower/Wardrobe/Dress` |
| `outerwear` | `Follower/Wardrobe/Outerwear` |
| `shoes` | `Follower/Wardrobe/Footwear`, `Follower/Wardrobe/Shoes` |
| `hat` | `Follower/Wardrobe/Headwear` |
| `accessory` | `Follower/Accessory` |
| `wardrobe` | `Follower/Wardrobe` |

Strings confirmed on DS4 4.24 against Studio's own type list
(`DzAssetMgr.getType`) and real Genesis 9 content (§15.3; DS6 pending). Studio
has no `Follower/Wardrobe/Top`, `.../Pants`, `.../Shoe` or `.../Hat`. `hat` no
longer includes `Follower/Accessory/Head`, which covers ear, eye (glasses), nose
and mouth accessories, not hats. `outerwear` also covers `Outerwear/Top` and
`Outerwear/Bottom`, so it can overlap `top`/`bottom`. A wearables preset file's
own type is `Preset/Wearables` (§15.3). Items whose
presentation type is empty never match a `type` selector (they can still be
targeted by name).

### 6.4 Fitted-item operations

Targets ("selectors") for `replace`/`remove`: a string = exact Scene-pane
label; `{"type": T}` = every item fitted to this actor whose type matches T.
Only items fitted to the actor (nodes following the figure) are candidates —
never items on another actor, never the figure itself. Items owned by this
recipe are never selector candidates; owned items change through their own
`add`/`replace` entry.

**Two kinds of entry.** This is what keeps the user's rule ("change what the
recipe mentions, leave the rest alone") consistent across applies:

- `add` / the `with` part of `replace` are **declarative owned items**,
  identified by `key`. They behave like v1 entities: desired state, three-way
  comparison, the existing conflict model. Changing the reference on an
  existing key swaps the owned item (v1 "replace" semantics). Deleting the
  entry removes the owned item (v1 removal checks). To change hair that a
  recipe added, the user edits that entry's reference.
- The *selector* part of `replace`, and `remove`, are **one-shot
  instructions** against content the recipe does not own. They run the first
  time the entry applies; the record (on the actor) notes the entry as
  done, with what was removed and its source. After that they are inert:
  a later apply never re-runs them.

Details:

- **replace** — on first apply the selector must match ≥1 item, else
  `replace_target_missing` error (option `"if_missing": "add"` turns it into a
  plain add). The replacement is fitted, then all matches are removed (§8).
- **remove** — on first apply the selector must match ≥1 item, else error
  (option `"if_missing": "ignore"`).
- Removing non-owned items that a `replace`/`remove` names is **not** a
  conflict under `on_conflict="ask"`: the recipe asked for it explicitly. The
  dry run lists every node that will be removed. Exception: a matched item
  that has children not fitted by Studio (props the user parented to it) is a
  `has_foreign_children` conflict, as in v1.
- **Hand changes after the fact.** If the user later swaps the recipe's owned
  hair by hand, that is v1's `deleted_in_scene` conflict on the owned key
  (`ask` blocks; `recipe_wins` refits it; `scene_wins` releases the key) —
  the one-shot selector is not re-run. Any new hand-loaded hair is simply
  non-owned content and is left alone. `observe()` reports the owned item as
  missing.
- `wearing` entries are evaluated in list order during planning: each entry's
  selector sees the scene as earlier entries in the list will leave it.
  Execution order is still the phase order of §8.

### 6.6 Multi-node fitted content

A fitted file may add several nodes (hair plus cap; a wearables / outfit
preset that loads several garments, each fitted to the actor).

- One `add`/`replace` entry owns the whole **group**: every node the load
  added (found by the before/after node diff v1 already uses). Each node gets
  a record with the same `group` id (`<actor key>.<entry key>`) and the
  shared `source`; one is marked primary (the first root of the load).
- Every node in the group must end up fitted to this actor (or be a child of
  a node that is). A load that adds anything else (e.g. a light, or a figure
  fitted to nothing) is removed again and fails, like v1's multi-root rule.
- Removing / swapping the entry removes the whole group with one exact-
  selection delete.
- Type matching for selectors looks at each node individually, so
  `remove: {type: hat}` can take the hat out of a hand-loaded outfit. Owned
  groups are never selector candidates (above), so a group is never split by
  a selector.
- Compatibility (§7) is checked per file, and for presets that load several
  items, per item the preset references when the metadata can tell; unknown
  items warn as in §7.4.
- Conflict tracking (hand edits, deletion) works per group: deleting any one
  node of an owned group by hand is `deleted_in_scene` for the entry.

### 6.5 Presets

Presets are applied in order on create, on take-over, and whenever the preset
list changes (by recorded resolution). They are not nodes, so there is no
remove; dropping a preset from the list does not undo it (documented,
dry-run warns). The pose channel keeps its v1 behavior.

## 7. Compatibility check

For every preset and fitted item, before any scene change:

1. Determine the target figure's compatibility base — for an existing node via
   `App.getAssetMgr().getCompatibilityBasePathForNode(node)`; for an actor the
   recipe will create, from the base asset's CMS metadata
   (`DzAsset.compatibilityBase`).
2. Determine the item's compatibility — CMS asset metadata
   (`DzAsset.compatibilities` via `findAssetsForFile`), falling back to the
   file's presentation `preferredBase` / `extendedBases` when it carries them.
3. Compatible if the target base (or one of its ancestors in the base
   hierarchy) is among the item's compatibilities. Otherwise →
   `incompatible_asset` error naming the item, its bases and the target base.
4. Compatibility unknown (no CMS record, no presentation data — e.g. a user's
   own shape file outside the CMS) → **warning**, not an error, so the user's
   project files keep working. The dry run shows it.

Items made for another figure that Studio could auto-fit are errors (§2).

## 8. Order of an apply

1. Offline validation (schema, refs) — as v1.
2. Resolve every asset reference (finders, `resolve_files`).
3. Read live state; locate taken-over nodes; evaluate every selector.
4. Compatibility checks.
5. Plan/diff (existing conflict model; new steps `fit`, `unfit`, `preset`,
   `take_over`).
6. Only if steps 2–5 produced no errors: execute, in order: creates → presets →
   fits (adds, replacements) → channels → removes (selector matches, dropped
   owned items) **last**, as v1 runs deletes last because they cannot be
   undone.
7. A failure before the remove phase rolls back everything done in step 6;
   the removed-items list is still untouched, so a replaced hand-loaded hair
   is simply still there. A failure *during* the remove phase reloads items
   already removed from the file they came from (`getAssetUriForNode` /
   record) and refits them; this loses hand material/morph edits on those
   items, which is accepted. If a to-be-removed item's source file cannot be
   determined, the **dry run** warns ("cannot be restored if removal fails")
   before any apply.

`validate()` covers 1, 2 and 4 where possible without a scene; `plan()` covers
1–5 and changes nothing.

## 9. Provenance

Every recipe-owned node's `EntityRecord` gains:

```jsonc
"source": {
  "requested": { ...the asset reference as written... },
  "resolved": {"path": "...", "sku": "...", "product": "...", "asset_id": "..."},
  "finder": "studio" | "content_browser" | "path",
  "fitted_to": "abby",          // actor key, fitted items only
  "group": "abby.hair",         // multi-node fitted content (§6.6)
  "primary": true,
  "type": "Follower/Hair"
}
```

Taken-over actors get `adopted_from_scene: true` plus `source.resolved` from
`getAssetUriForNode` where available. `observe()` reports a fitted item whose
live node no longer matches its recorded source (e.g. swapped by hand) as a
drift entry. Removed (non-owned) items are recorded in the manifest's apply log
with their source, for rollback and audit.

## 10. Versioning

New fields are additive but the v1 validator rejects unknown keys, so this is
`recipe_version: 2` with `schemas/scene-recipe.v2.schema.json`. v1 recipes
load unchanged (string asset = path). The MCP tools in daz-mcp-server accept v2.

## 11. Cross-repo work

- **daz-script-server / dazpy:** schemas, model, validator, finders, ops,
  diff/apply/observe, docs (`docs/scene_recipes.rst`), tests (unit with fake
  SceneOps/finder; scoped live tests DS4/DS6).
- **daz-content-browser-mcp:** add `asset_ref` to asset tool results; README
  section on using refs in recipes. (Its README also says `get_product_assets`
  wraps `GET /api/v1/assets/{sku}` while the browser serves
  `/api/v1/products/{sku}/assets` — check and fix while there.)
- **daz-mcp-server:** expose v2 recipes; tool docs mention passing content
  browser refs.

## 12. Acceptance

- Abby example works end-to-end on DS4 and DS6, both from an empty scene and on
  a hand-built Abby, including the hair swap by `{type: hair}`.
- A Genesis 8 hair on a Genesis 9 actor fails at validate/plan with
  `incompatible_asset` and the scene is unchanged; no modal appears.
- An ambiguous `find` lists candidates and changes nothing.
- A forced failure during the fit phase leaves the replaced hand-loaded hair
  in place, untouched, and removes the partly fitted replacement.
- A multi-node hair (hair + cap) and a wearables outfit preset can be added,
  swapped and removed as one entry on DS4 and DS6.
- daz-content-browser-mcp results carry `asset_ref` objects that validate
  against the shared schema and resolve in a recipe.
- Every recipe-owned node carries `source` provenance.

## 13. Calls made during design (not explicitly confirmed by the user)

- String asset = `{path}` shorthand; v2 schema version bump.
- Reference field precedence and `file` disambiguation field.
- Recorded resolution is reused on re-apply (stability over freshness).
- Unknown compatibility (no metadata) is a warning, not an error.
- `replace`/`remove` with no match is an error by default, with `if_missing`
  options.
- `{type}` replace removes **all** matching items.
- Taken-over actors: no implicit transform default; base figure never replaced;
  never deleted on release.
- Presets are not undone when dropped from the list.
- Finder fallback order and env var names; CMS-down makes `find/product/sku`
  fail while paths still work.
- Friendly content-type names table.
- Removes run last; only a failure during the remove phase reloads items
  from their source file (losing hand edits); dry run warns when it cannot.
- `node` and string selectors match the Scene-pane label; a created
  `node:` actor gets that label; taken-over nodes are found by record later.
- `add`/`replace` entries need a `key`; owned items are declarative,
  `replace` selectors and `remove` are one-shot and inert once done.
- Explicit removal of non-owned items is not a conflict under `ask`
  (except `has_foreign_children`).
- `resolved` is an authoritative pin that falls back to fresh resolution if
  the file is gone; new `pin()` helper; dazpy never rewrites recipes itself.
- Multi-node fitted content: one entry owns the group; selectors match per
  node but never split an owned group.

## 14. Left to the builder

- Exact content-type prefix strings (verified on real content).
- Search scoring/score-gap heuristic within the "err toward ambiguity" rule.
- How fitting is performed in DazScript (e.g. `DzFigure.setFollowTarget` vs
  loading with the actor as primary selection), provided no modal can appear.
- Internal module layout, step names, error-code spellings.
- How `StudioFinder` maps to `DzAssetMgr` search calls.

## 15. Live probe findings (DS4/DS6)

Probe: `tests/live_probe_asset_apis.py` (Task 1). Content used: figure
`/People/Genesis 9/Genesis 9.duf` (labelled `Abby`), hair `/People/Genesis
9/Hair/Daz Originals/Kara Ponytail/Kara Ponytail.duf` (SKU 93714), wearables
preset `/People/Genesis 9/Clothing/Daz Originals/Detective Outfit/Detective
!Outfit.duf` (SKU 105542, six garments), incompatible item `/People/Genesis 8
Female/Hair/Goldtassel/Cafe Curls/Cafe Curls.duf` (read from metadata only,
never loaded).

| Studio | Status |
|---|---|
| DS4 4.24.0.4, CMS connected | probed 2026-11-27 (below) |
| DS6 | **pending**: re-run the probe after Studio is switched |

### 15.1 Loading and paths

- `Scene.loadScene(path, DzScene.MergeFile)` needs an **absolute** path. A
  content-relative path (`/People/...`) pops a modal "could not find file"
  dialog (the probe's first run did this). Every load must use the path
  `resolve_files` returns (`findFile` over the content dirs, then
  `DzFileInfo.exists`), never the raw reference.
- `DzContentMgr.findFile("/People/...")` returns the absolute path (original
  case); `getRelativePath(abs, true)` gives back `/People/...` with a leading
  slash.
- After a load, Studio selects what it loaded (method (a): the first new root).
- After fitting the dForce hair, Studio answered the next request with
  `StudioBusyError` (503) for a while; it cleared without any dialog. Calls
  after a load/fit need `retry_on_busy`.

### 15.2 Per call: what DS4 returns

| Call | DS4 result |
|---|---|
| `DzAssetMgr.findAssetsForFile(rel, true, true)` | Array of `DzAsset`, 1 per file here. Works with or without the leading `/`. |
| `DzAsset.contentType` | File type: figure `Actor/Character`, hair `Follower/Hair`, wearables preset `Preset/Wearables`. |
| `DzAsset.compatibilities` | Bases the file is for: figure `["/Genesis 9/Base"]`, hair and outfit `["/Genesis 9/Base"]`, G8 hair `["/Genesis 8/Female"]`. Some items name the parent base (`["/Genesis 9"]`). `vendorCompatibilities` is the same list and `userCompatibilities` is empty. |
| `DzAsset.compatibilityBase` | The base the file *provides*: figure `/Genesis 9/Base`; also set on items (hair `/dForce Kara Ponytail for Genesis 9/Kara Ponytail`, outfit `/dForce Detective Outfit for Genesis 9`); G8 hair `""`. Only meaningful as "actor base" for figure files. |
| `DzAsset.productName` / `.productID` / `.storeID` | `"Genesis 9 Starter Essentials"` / `"86958"` (the SKU, a string) / `"DAZ 3D"`. |
| `DzAsset.getProduct()` | `DzProductAssetContainer`: `.title`, `.token` (= SKU), `.store`, `.guid`. |
| `DzAsset.getRelativeFilePath()` | `People/Genesis 9/Genesis 9.duf` (**no** leading `/`). |
| `DzAsset.getAsLocalFile()` | Absolute but **lower-cased** (`x:/daz libraries/project/people/genesis 9/genesis 9.duf`). |
| `DzAsset.assetID()`, `DzAsset.getAsFilePath()` | **Do not exist** (`undefined`). No asset id is exposed; use product GUID + relative path if an id is needed. |
| `DzAssetMgr.findProductsForFile(rel)` | Products owning the file (`title`, `token`). |
| `DzAssetMgr.findProductByStoreToken("DAZ 3D", sku)` | Product, synchronous. `getNumAssets()` / `getAsset(i)` work directly (592 assets for SKU 86958). |
| `DzAssetMgr.findProductsByName(name)` | Exact-title product list, synchronous. |
| `DzAssetMgr.searchForAssets(text, cats, bases, types, sort)` | Returns a `DzSearchContainer` that is **empty when returned** and fills **asynchronously**: the script must pump `processEvents()` until the count is stable (first results after 30–850 ms, stable within ~1.6 s). Without pumping, every search returns 0 assets. Text matches broadly (`ponytail`: 772 hits incl. material presets). Base and type filters work (`ponytail` + `/Genesis 9/Base` + `Follower/Hair`: 10). An **unknown type string is ignored** (no filtering). Results are **capped at 1200**, and `hasMoreSearchResults()` stays false at the cap. Sort: `DzAssetMgr.NoSort` = 0, `NameSort` = 1. |
| `DzAssetMgr.searchForProducts(...)` | Needs **6 arguments** `(text, cats, bases, types, installStateFlags, sort)`; the 5-argument call is a syntax error. Async like `searchForAssets`. The text barely filters (`"Genesis 9 Starter Essentials"` → 2212 products), so not usable for exact product lookup. `DzAssetMgr.InstalledState` = 1. |
| `DzAssetMgr.searchForProductAssets(product, ...)` | Async; same 592 as the product's direct `getNumAssets()`. |
| `DzAssetMgr.getTypeForContentFile(abs)` | Same string as the CMS `contentType`. |
| `DzAssetMgr.getCompatibilityBasePathForNode(figure)` | `/Genesis 9/Base`. For an item node: the item's own base (`/dForce Detective Outfit for Genesis 9/Detective Shoes`). |
| `DzAssetMgr.getAssetUriForNode(node)` | The node's **data (`.dsf`) URI**, URL-encoded, with `#id`: figure `/data/Daz%203D/Genesis%209/Base/Genesis9.dsf#Genesis9`, hair `/data/DAZ%203D/Kara%20Ponytail/Kara%20Ponytail%20Scalp/Scalp_1085.dsf#Scalp_1085`. It is **not** the `.duf` the user loaded, so it cannot be compared with a recorded `.duf` path. |
| `DzAssetMgr.getTypeForNode(node)` | Same as `node.getPresentation().type`. |
| `node.getPresentation().type` | Figure `Actor` (not `Actor/Character`); items: the garment's own type (see 15.3); G9's own followers `Follower/Attachment/Head/Face/{Eyelashes,Tears,Eyes,Mouth}`, `Follower/Attachment/Head/Forehead/Eyebrows`. |
| `.preferredBase` | Items: `/Genesis 9/Base` (the figure they are for). Figure: `""`. |
| `.extendedBases` | `[]` on every node probed. |
| `.autoFitBase` | A **property** (string), not the documented method: calling `autoFitBase()` throws. Figure `/Genesis 9/Base`, G9 eyelashes/eyes/mouth/tear `/Genesis 9/<part>`, hair/garments `""`. |
| `DzSkeleton.getFollowTarget()` | Figure: `null`. Fitted item: the figure. Sub-parts of an item (Kara Ponytail's band, braid, ...) follow the item's root (`Scalp_1085`), not the figure. |
| Node identity in script | Two wrappers of the same node are `==` but **not `===`**: `item.getFollowTarget() === figure` is false. Compare with `==` or by `elementID`. |
| `node.elementID` | A numeric **property** (e.g. 85534). `getElementID()` does **not** exist on DS4. |
| CMS off | Not tested: switching the CMS off is not safe to script. `isConnectedToCMS()` returned true. |

### 15.3 Content types seen

Studio's own vocabulary (`DzAssetMgr.getType(i)`) for wardrobe:
`Follower/Wardrobe` + `/Dress`, `/Full-Body`, `/Footwear` (`/Left`, `/Right`),
`/Shoes`, `/Glove(s)`, `/Headwear`, `/Outerwear` (`/Top`, `/Bottom`), `/Pant`,
`/Shirt`, `/Skirt`, `/Sock(s)`, `/Underwear` (`/Top`, `/Bottom`). Hair:
`Follower/Hair` (+ `/Animal/...`). Accessories: `Follower/Accessory/...` (Arm,
Arms, Head/{Ear,Eye,Eyes,Eyelashes,Mouth,Nose}, Leg(s), Neck, Waist, Torso).
Figure parts: `Follower/Attachment/...`. Presets: `Preset/Wearables`,
`Preset/Character`, `Preset/Materials/...`, `Preset/Morph/...`, `Preset/Pose`.

Node types on the loaded Detective Outfit: Shoes `Follower/Wardrobe/Footwear`,
Pants `Follower/Wardrobe/Pant`, Shirt and Vest `Follower/Wardrobe/Shirt`, Coat
`Follower/Wardrobe/Outerwear`, Hat `Follower/Wardrobe/Headwear`. Hair
`Follower/Hair`. The §6.3 table is corrected to these strings.

Consequences:
- A wearables preset *file* has type `Preset/Wearables`, not a
  `Follower/Wardrobe/...` type, so a `find` filtered by `wardrobe`/`top`/...
  on the CMS `contentType` never returns an outfit preset. File type filtering
  must treat `Preset/Wearables` as matching any wardrobe friendly name (or skip
  the type filter for it and check node types after load).
- A raw prefix `Follower` matches the figure's own eyes, mouth, eyebrows,
  eyelashes and tear (`Follower/Attachment/...`); no friendly name does.

### 15.4 Fitting method (chosen: (a))

Probed on the same figure with nothing else changed:

| | (a) nothing selected, then `setFollowTarget(fig)` + `fig.addNodeChild(item, true)` | (b) figure as sole primary selection, then load |
|---|---|---|
| Dialog for a compatible item | none (hair, 6-garment preset) | none (hair, 6-garment preset) |
| Nodes added | hair: 1 root (`Scalp_1085`) with 5 sub-parts that follow it; outfit: **6 roots**, one per garment, each a `DzFigure` with a `DzPushModifierWeightNode` child ("Clothing Expander ...") | the same nodes, already parented to the figure |
| After | follow target = figure, parent = figure, smoothing modifier's Collision Item = figure (set by `setFollowTarget`) | identical readback |
| Load time | hair 7.0 s, outfit 1.6 s | hair 7.0 s, outfit 2.4 s |

Readback (follow target, parent, presentation, collision item) is identical.
**Chosen: (a)**, as Task 11's provisional `_fit_script` does: the load never
depends on the selection (so it cannot take the "replace the selected figure"
or auto-fit dialog paths), the added nodes arrive as scene roots that the
before/after diff finds, and only `DzFigure` roots are fitted. Method (b) is not
needed. It would also put an incompatible item on Studio's auto-fit path, which
§2 forbids. Not measured: morph projection / auto-follow details beyond the
readback above.

Before/after diff: on DS4 the snapshot key must be `node.elementID`. Node
names repeat when a file is loaded again (the second hair is again `Scalp_1085`,
labelled `Kara Ponytail (2)`), so a name-keyed snapshot misses every node of a
repeated load.

### 15.5 Compatibility check (§7)

- §7 step 1 works: `getCompatibilityBasePathForNode(figure)` gives
  `/Genesis 9/Base`, and for a figure file to be created `DzAsset.compatibilityBase`
  gives the same.
- Step 2 works from `DzAsset.compatibilities`. A preset's own record already
  says what it is for (`Preset/Wearables` → `["/Genesis 9/Base"]`).
- Step 3: an item base can be an ancestor (`/Genesis 9`) of the figure base,
  so the `/`-boundary prefix match is needed. G8 hair (`/Genesis 8/Female`) vs
  `/Genesis 9/Base` → incompatible, decided from metadata alone.
- `preferredBase` on a loaded item node is the target base, a usable fallback
  for nodes. Files cannot be read this way without loading them, so the
  "presentation fallback" in step 2 applies only to scene nodes.
