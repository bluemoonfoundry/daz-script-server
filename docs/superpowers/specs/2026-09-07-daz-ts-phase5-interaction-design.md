# daz-ts Phase 5: interaction/IK (multi-figure posing)

## Context

This is the last child of the daz-ts epic (`daz-script-server-3v8r`), tracked
as `daz-script-server-sf7y`. It ports `dazpy/_interaction.py` (2063 lines,
dazpy's largest and most numerically involved module): rig-profile detection
across figure families (Genesis 1/2, 3/8, 9, generic), bone-chain/axis-limit
metadata, a damped-least-squares Jacobian IK solver for limb alignment, and
seven canned two-figure recipe builders (sit, touch, kiss, handshake, hug,
face-each-other, fight).

Phases 1-4 are closed. Every primitive Phase 5 needs already exists and is
tested on `DazSkeleton`/`DazScene`: `boneMetadata()`, `boneRotations()` /
`setBoneRotations()`, `evaluatePoseJacobian()`, `skeletons()`,
`findSkeletonByLabel()`, `sceneSnapshot()`. Phase 5 is pure orchestration and
data logic on top of those — no new DazScript strings need to be generated
or tested for exact output; the underlying scripts are already covered by
Phase 4's tests.

**Simplification over the Python source:** `_interaction.py` carries two
parallel code paths in its IK solver — a fast "batch" path (2 HTTP
calls/iteration via `evaluate_pose_jacobian`) used whenever the skeleton
object has a live `_client`, and a legacy per-bone-perturbation path for
skeleton-like objects without it (dazpy supports fake/test skeletons and
historically pre-batching skeletons). Every `daz-ts` `DazSkeleton` always has
the batch methods, so **the legacy path is dropped entirely** — it is dead
code in this port. Likewise `build_rig_profile`'s per-bone-property fallback
loop (for skeletons without `bone_metadata()`) is dropped; daz-ts always has
`boneMetadata()`.

## Decisions (confirmed with user)

- **Sub-issue decomposition**: split `sf7y` into three child issues, each
  its own implementation plan and PR:
  - **5A** — rig profiles + plan data model (`rigProfile.ts`,
    `interactionPlan.ts` minus limb-alignment wiring)
  - **5B** — IK solver (`interactionSolve.ts`), wires `alignLimbTargets`
    into `PreparedInteractionRecipe`
  - **5C** — recipe builders + `DazScene.applyInteractionRecipe` +
    exports/README
- **Batch-only IK**: drop the non-batch legacy alignment path and the
  per-bone-property rig-profile fallback (see above).
- **File layout**: three files by concern (`rigProfile.ts`,
  `interactionPlan.ts`, `interactionSolve.ts`) rather than one monolithic
  `interaction.ts` or a two-file split.
- **Module boundary**: `rigProfile.ts`/`interactionPlan.ts`/
  `interactionSolve.ts` never import `skeleton.ts` or `scene.ts`. They
  declare their own minimal structural interfaces for what they need
  (`boneMetadata()`, `label()`, `boneRotations()`, `setBoneRotations()`,
  `evaluatePoseJacobian()`, `skeletons()`, `findSkeletonByLabel()`,
  `sceneSnapshot()`); `DazSkeleton`/`DazScene` satisfy them structurally.
  Mirrors dazpy's `TYPE_CHECKING`-only import of `DazSkeleton` in
  `_interaction.py` today.
- **Alignment API shape**: standalone functions (`alignHandTarget(skeleton,
  point, opts)` / `alignFootTarget(skeleton, point, opts)`), not
  `DazSkeleton.handToTarget`/`footToTarget` methods. Matches the existing
  `poses.ts` precedent (functions over the skeleton, not methods on it) and
  avoids the lazy-import trick dazpy needs in `_skeleton.py` to dodge its
  circular import.
- **Vector representation**: `type Vector3 = [number, number, number]` and
  `type Rotation3 = [number, number, number]` — matches `skeleton.ts`'s
  existing `boneRotations()`/`setBoneRotations()` convention exactly, no
  conversion glue at the boundary. Not the `Vec3` class from `math3.ts`.

## Architecture

### `rigProfile.ts` (pure logic; depends on nothing new)

Ports, 1:1 in spirit (batch-only where applicable):

- `AxisLimit`, `BoneProfile`, `BoneChain`, `InteractionAnchor`,
  `ResolvedInteractionTarget` — plain data types with `toDict`/`fromDict`
  where the Python has them (round-trip is exercised by tests).
- `FigureRigProfile` class: `boneNames()`, `bone(name)`, `ancestry(name)`,
  `chainTo(name)`, `chainFor(name, role, side)`, `chainSuggestions()`,
  `suggestPrimaryChain(name)`, `anchorMap()`, `anchor(name)`,
  `anchorNames()`, `requireAnchor(name)`, `resolveAnchorTarget(target,
  rigProfiles?)`, `toDict`/`fromDict`.
- Name-matching helpers: `_normalizeName`, `_compactName`, `_sideFromName`
  (left/right/center/unknown, handles both `l_`/`r_` snake_case and
  camelCase `lHand`/`rHand` prefixes — Genesis 3/8 naming), `_matchTokens`,
  `_matchAny`, `_sideMatches`.
- `_detectFigureFamily(boneNames)` — genesis_9 / genesis_3_8 / genesis_1_2 /
  generic, via bone-name heuristics (`forearmBend` → 3/8, bare `forearm` →
  1/2, `l_`/`r_` prefix + forearm/twist/hand/foot tokens → 9).
- `_looksLikeTwist`, `_looksLikeHelper`.
- `defaultAxisLimitsForBone(name, family)` — loose per-region degree limits
  (head/neck, shoulder/clavicle/upper-arm, forearm/hand, thigh/shin/calf,
  foot/toe, spine/abdomen/chest/hip/pelvis).
- `buildRigProfile(skeleton: RigMetadataSource)` — `await
  skeleton.boneMetadata()`, one HTTP call, builds every `BoneProfile`.
- `buildRigProfilesFromSnapshot(snapshot)` — same, from a bulk
  `sceneSnapshot()` result; stores both figure label and internal name as
  keys (tolerant lookup), matching dazpy.
- `_lookupRigProfile(rigProfiles, label)` — exact match, then
  compact-name-insensitive match (`"Genesis9"` matches `"Genesis 9"`).

### `interactionPlan.ts` (depends on `rigProfile.ts`)

- Constraint types: `PoseTarget`, `AnchorTarget` (base for `HandTarget`/
  `FootTarget`), `ContactTarget`, `LookAtTarget`, `BalanceTarget` — plain
  data + `toDict`.
- `ValidationIssue`, `SolveOptions` (with `toDict`/`fromDict`).
- `InteractionPlan`: `actors`, `constraints` (discriminated union), `options`;
  `toDict`/`fromDict` (dispatches on `constraint.kind`), `validate(rigProfiles)`
  (returns `ValidationIssue[]`, one per unresolvable figure/bone/anchor —
  never throws), `resolveTargets(rigProfiles)` (resolves `HandTarget`/
  `FootTarget` via `resolveInteractionTarget`).
- `resolveInteractionTarget(target, rigProfiles)` — throws if the figure is
  unknown (matches dazpy: this one *does* throw, unlike `validate`).
- `InteractionRecipe`: `kind`, `actors`, `constraints`, `options`,
  `metadata`; `toPlan()`, `toDict`/`fromDict`.
- `InteractionPosePatch`: `figurePositions: Record<string, Vector3>`,
  `unresolvedTargets: ResolvedInteractionTarget[]`, `diagnostics`;
  `apply(scene: PatchTarget)` — one `findSkeletonByLabel` +
  `setPosition` per figure (no IK, coarse staging only).
- `PreparedInteractionRecipe`: `recipe`, `plan`, `resolvedTargets`,
  `rigProfiles`, `validationIssues`, `diagnostics`, `isValid` (getter: no
  `"error"`-severity issues); `buildPosePatch()` (ports the full averaging/
  contact-midpoint logic from `build_pose_patch` — this is the fiddliest
  pure-logic piece, see Testing below); `toDict`.
  - `apply(scene, opts)` and `alignLimbTargets(scene, opts)` are declared
    here but their bodies are filled in during **5B** (they need
    `interactionSolve.ts`, which depends on this file's types — so the
    dependency direction is: 5A ships these as pose-patch-only i.e.
    `alignLimbTargets` always empty / `apply`'s `alignLimbTargets` option
    ignored with a diagnostic note; 5B fills in the real bodies).
- `prepareInteractionRecipe(recipe, rigProfiles)` — compiles a recipe:
  validate + resolve + diagnostics.
- `PreparedInteractionResult`: `prepared`, `posePatch`, `alignmentResults`.

### `interactionSolve.ts` (depends on `rigProfile.ts`, `interactionPlan.ts` for types)

- Vector/rotation math: `vec3Add/Sub/Scale/Dot/Length`, `clamp`,
  `rotationWithAxisLimits`, `invert3x3`, `mul3x3Vec` — ported directly,
  these are simple closed-form functions.
- `dampedLeastSquaresStep(columns, error, damping)` — the numerical core:
  builds the 3×3 `J^T J + λI` normal-equations matrix from the Jacobian
  columns, inverts it, solves for the joint-angle delta. This is the one
  piece needing a dedicated numerical test against known inputs/outputs
  cross-checked against the Python implementation (see Testing).
- `LimbAlignmentResult` type.
- `alignmentChainNames(profile, chain)` — filters helper bones, caps chain
  length per role (hand/arm/foot/leg: 4, head/neck/pelvis: 2, spine/custom: 3).
- `alignSingleLimbTarget(skeleton: JacobianSource, profile, target, opts)` —
  the batch-only IK loop: `evaluatePoseJacobian` → check convergence →
  `dampedLeastSquaresStep` → clamp to `stepDegrees` → apply axis limits per
  bone → `setBoneRotations` → repeat until `tolerance` or `maxIterations`.
  Returns diagnostics-carrying results (never throws) for: missing target
  point, missing chain, missing effector position, already-aligned,
  converged, did-not-converge.
- `alignHandTarget(skeleton, targetPoint, opts)` / `alignFootTarget(...)` —
  thin wrappers: `buildRigProfile` → `resolveInteractionTarget` (with a
  synthetic `HandTarget`/`FootTarget`) → `alignSingleLimbTarget`.
- Fills in `PreparedInteractionRecipe.apply`/`alignLimbTargets` bodies from
  5A (see above) — this is the one cross-file edit 5B makes outside its own
  new file.

### 5C: recipe builders + scene integration

- `buildSitRecipe`, `buildTouchRecipe`, `buildKissRecipe`,
  `buildHandshakeRecipe`, `buildHugRecipe`, `buildFaceEachOtherRecipe`,
  `buildFightRecipe` — added to `interactionPlan.ts` near
  `InteractionRecipe`. Each is a small pure function assembling
  constraints; ported directly from the Python (including
  `_targetAnchorFromStrikeAnchor`'s hand/foot/chest dispatch for
  `buildFightRecipe`).
- `applyInteractionRecipeToScene(scene: RecipeSceneSource, recipe, opts)` —
  builds rig profiles from `sceneSnapshot()` if not supplied, then
  `prepareInteractionRecipe` + `.apply()`.
- `DazScene.applyInteractionRecipe(recipe, opts)` method on the real
  `DazScene` class in `scene.ts`, delegating to
  `applyInteractionRecipeToScene(this, recipe, opts)` — this is the one
  place `scene.ts` takes a real (type-only-safe, no cycle since
  `interactionPlan.ts` doesn't import `scene.ts`) dependency on the new
  module.
- Exports added to `index.ts` for every new public type/function.
- README updated with the new API surface (mirrors how prior phases updated
  it).

## Testing

Vitest, mirroring dazpy's `TestInteractionAdapter` test-by-test where it
maps cleanly onto ported code:

- **5A**: family detection (including the Genesis 8 camelCase
  `lHand`/`rHand`/`lForearmBend` case), anchor resolution, `chainFor`/
  `suggestPrimaryChain`, `InteractionPlan.validate`/round-trip,
  `resolveInteractionTarget` same-figure and cross-figure, compact-name
  figure-alias lookup (`"Genesis9"` vs `"Genesis 9"`), `buildRigProfile`
  via a fake client returning canned `boneMetadata()` JSON,
  `buildPosePatch`'s contact-midpoint/averaging logic across the same
  same-figure/cross-figure/both-unplaced permutations dazpy's test suite
  covers. All pure-function tests, no exact-script-string assertions
  needed (no new scripts are generated by this file).
- **5B**: a numerical unit test for `dampedLeastSquaresStep`/`invert3x3`
  against known Jacobian-column/error inputs, with expected outputs
  computed from (or cross-checked against) `_interaction.py`'s
  `_damped_least_squares_step` for the same inputs — this is the epic's
  acceptance criterion ("IK solver produces results within documented
  tolerance of dazpy's Python implementation for equivalent inputs").
  A fake-client test for `alignSingleLimbTarget`'s orchestration loop
  (asserting call sequence/count against a scripted fake
  `evaluatePoseJacobian`/`setBoneRotations`, and convergence behavior) —
  not exact script strings, since those scripts are already covered by
  Phase 4.
- **5C**: recipe builders' constraint shapes (one test per recipe,
  asserting the constraint list matches dazpy's builder for the same
  inputs), `applyInteractionRecipeToScene`/`DazScene.applyInteractionRecipe`
  via a fake client/scene.

## Error handling

Same posture as the rest of daz-ts and as dazpy: unresolvable figures/bones
during `validate()`/`resolveTargets()` become `ValidationIssue`s (data, not
exceptions). `alignSingleLimbTarget` returns a `LimbAlignmentResult` with a
`diagnostics.reason` for expected failure cases (missing target point,
missing chain, missing effector position) rather than throwing.
`resolveInteractionTarget` and `FigureRigProfile.requireAnchor` do throw on
an unknown figure/anchor, matching dazpy exactly (these are programmer
errors — a target referencing a figure/anchor that was never registered —
not runtime data-quality issues).

## Acceptance criteria (from `daz-script-server-sf7y`)

- IK solver produces results within documented tolerance of dazpy's Python
  implementation for equivalent inputs (verified via the 5B numerical test
  above).
- Recipe builders produce valid interaction plans for at least the same
  figure families dazpy supports (Genesis 8/9) (verified via 5A's family
  detection + 5C's recipe-builder tests).
