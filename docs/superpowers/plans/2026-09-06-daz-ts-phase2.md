# daz-ts Phase 2: Scene Graph Proxies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port dazpy's scene-graph proxy layer to `daz-ts` — `DazElement`, `DazProperty`, `DazNode`/`NodeIdentifier`, `DazScene`, `DazSkeleton`, `DazBone`, `DazCamera`, `DazLight`, `DazMaterial`, `DazModifier`/`DazMorph`/`DazDForce`, `DazGeometry`, `DazViewport`, `DazTimeline`, `UndoGroup` — as faithful, exact-script-string TypeScript ports of dazpy's `_element.py`, `_property.py`, `_node.py`, `_scene.py`, `_skeleton.py`, `_bone.py`, `_camera.py`, `_light.py`, `_material.py`, `_modifier.py`, `_morph.py`, `_dforce.py`, `_geometry.py`, `_viewport.py`, `_timeline.py`, `_undo.py`.

**Architecture:** Every proxy class wraps `(client: DazClient, locator: string)` where `locator` is a DazScript expression that resolves to the live object, exactly as dazpy's `DazElement`. Every call builds an IIFE via `ScriptBuilder.iife`, with every injected value passed through `ScriptBuilder.escapeString`/`serializeArg` (already implemented in Phase 1, `src/scriptBuilder.ts`). Because `DazClient.execute()` is `async`, every Python `@property` becomes a pair of plain TS methods on the proxy — a getter method named after the property (`label()`) and, for read/write properties, a setter method (`setLabel(value)`) — never a TS `get`/`set` accessor pair, so call sites read `await node.label()` / `await node.setLabel("x")` rather than the ambiguous `await node.label`. Python's `with scene.undo(label): ...` context manager has no TS equivalent statement, so `UndoGroup` is ported as an explicit `begin()`/`commit()`/`cancel()` API plus a `withUndo(client, label, fn)` higher-order helper that `DazScene.undo()` delegates to.

**Tech Stack:** TypeScript 5.x (strict mode), Node.js >=18, Vitest, zero runtime dependencies (same as Phase 1).

**Spec:** `docs/superpowers/specs/2026-09-06-daz-ts-design.md` (this plan implements that spec's Phase 2; beads issue `daz-script-server-56nz`, depends on Phase 1's `daz-script-server-xtni`, blocks Phase 3's `daz-script-server-37mg`)

**dazpy source ported (canonical reference, `daz-script-server/dazpy/`):** `_element.py`, `_property.py`, `_node.py`, `_scene.py`, `_skeleton.py`, `_bone.py`, `_camera.py`, `_light.py`, `_material.py`, `_modifier.py`, `_morph.py`, `_dforce.py`, `_geometry.py`, `_viewport.py`, `_timeline.py`, `_undo.py`, `_script_builder.py`.

**Existing Phase 1 code this plan builds on (`daz-ts/src/`, already implemented on branch `feature/daz-ts-phase1`):** `client.ts` (`DazClient`, `execute()` → `Promise<ExecutionResult>`), `scriptBuilder.ts` (`ScriptBuilder.iife`/`escapeString`/`serializeArg`), `exceptions.ts` (`NodeNotFoundError`, `ScriptRuntimeError`, etc.), `result.ts` (`ExecutionResult`), `math3.ts` (`Vec3`, `BoundingBox`).

## Global Constraints

- Node.js >=18 only; zero runtime dependencies (only `typescript`, `vitest`, `@types/node` as devDependencies) — same as Phase 1.
- Every injected string/value in generated DazScript MUST go through `ScriptBuilder.escapeString` (strings) or `ScriptBuilder.serializeArg` (arbitrary values) — never raw string concatenation. This is a security invariant, not style; the Phase 1 injection-safety test suite (`test/unit/injectionSafety.test.ts`) pattern extends to every new string-typed parameter added in this phase.
- Method/property names use camelCase; Python `snake_case` methods and `@property` attributes both become camelCase TS methods (e.g. `find_skeleton_by_label` → `findSkeletonByLabel`, `raw_value` property → `rawValue()` method).
- **Async-property convention (Phase-2-specific, not in the design spec — judgment call, confirm if it doesn't fit):** every Python `@property` (getter-only or read/write) becomes a TS method returning `Promise<T>`, since `DazClient.execute()` is async and JS accessor getters cannot be declared `async`. A read/write Python property `foo` becomes two methods: `foo(): Promise<T>` and `setFoo(value: T): Promise<void>`. A read-only property becomes just `foo(): Promise<T>`. This applies uniformly across every proxy class in this phase.
- Preserve, byte-for-byte, every documented live-server gotcha from dazpy — do not "fix" or "improve" any of these:
  - `DazProperty.rawValue()`/`setRawValue()` reads/writes `getRawValue()`/`setRawValue()` when present, falling back to `getValue()`/`setValue()` otherwise — this is the ERC-link-bypassing snapshot/restore path, required for idempotent round-trips on ERC-driven properties (e.g. Genesis "Scale" dial). Do not collapse it to a plain `value()` alias.
  - Keyframes are written via `setDoubleValue(time, value)`, **never** `setKey()`/`addKey()` — those don't exist on a live `DzProperty` and silently write nothing.
  - `isAnimated()` is computed as `getNumKeys() > 0` — `DzProperty.isAnimated()` does not exist on a live property and throws `ScriptRuntimeError`.
  - `DazScene.findSkeleton()` retries `Scene.getSkeletonList()` up to `retryAttempts` times (default 3) with `retryDelay * attemptNumber` (default 0.15s base) sleeps between attempts, because `getSkeletonList()` has been observed to transiently omit a present skeleton under main-thread load (dazpy bug reference: `daz-script-server-xtkd`). Do not simplify this to a single lookup.
  - `DazSkeleton`'s `_skeletonBody`/`_boneLocator` equivalents look the skeleton up via `Scene.getSkeletonList()` iteration (matching on `getLabel()` when `identifier.kind === "label"`, else `getName()`), **not** `Scene.findNode()` — `Scene.findNode()` returns a plain `DzNode` that lacks `DzSkeleton` methods like `findBone()`, and two figures of the same asset type share the same internal name so name-based lookup on `Scene` would collapse distinct figures into one.
  - `DazNode.findModifier`/`.modifiers()` dispatch to `DazMorph` for `DzMorph`-classed modifiers and `DazDForce` for `DzDForceModifier`-classed ones, defaulting to plain `DazModifier` otherwise — preserve this class dispatch table exactly.
  - `DazScene.nodes()` classifies each node's proxy subclass via `n.inherits("DzSkeleton"/"DzCamera"/"DzLight")` (QObject subclass check), not `className() ===`, so that subclasses of `DzFigure`/etc. still map correctly.
- Excluded from this phase (tracked separately, not silently dropped): `DazSkeleton.handToTarget`/`.footToTarget` and `DazScene.applyInteractionRecipe` all delegate to `_interaction.py`'s IK solver, which is Phase 5 (`daz-script-server-sf7y`) scope — omit them here and note the gap in a TSDoc `@remarks` on `DazSkeleton`/`DazScene` pointing at Phase 5. `DazViewport.capture_sprite()` depends on the Python `rembg` package (background removal) with no Node equivalent in scope — omit it; background removal for daz-ts is an open question for a future phase, not silently reintroduced later as a stub.
- `UndoGroup` is not a context manager (TypeScript has no `with` statement). Port it as `class UndoGroup { begin(): Promise<void>; commit(): Promise<void>; cancel(): Promise<void>; }` plus a standalone `async function withUndo<T>(client: DazClient, label: string, fn: () => Promise<T>): Promise<T>` that calls `begin()`, runs `fn()`, and calls `commit()` on success or `cancel()` if `fn()` throws (rethrowing after `cancel()`), mirroring `__enter__`/`__exit__`. `DazScene.undo<T>(label: string, fn: () => Promise<T>): Promise<T>` delegates to `withUndo`.
- Every unit test stubs `global.fetch` via `vi.stubGlobal("fetch", ...)` (see Phase 1's `test/unit/client.execute.test.ts` for the exact pattern) and asserts the *exact* generated DazScript string via `JSON.parse(init.body as string).script` — never a substring/regex match — mirroring dazpy's `TestDazNodeScriptGeneration`-style exactness.
- Every proxy class file re-exports its public type(s) from `src/index.ts` (Task-by-task addition, matching Phase 1's `index.ts` pattern of one barrel file).

## File Structure

```
daz-ts/src/
  element.ts       # DazElement base class: getProperty/setProperty/setProperties/listProperties/numericProperties/className/snapshot/refresh
  property.ts       # DazProperty extends DazElement: value/rawValue/label/min/max/keyframes
  node.ts            # NodeIdentifier type + findNodeExpr/nodeBody helpers + DazNode extends DazElement
  scene.ts           # DazScene: scene-level queries, node/camera/light/skeleton factories, I/O, playback, undo, dForce
  skeleton.ts        # DazSkeleton extends DazNode: bones, bulk bone/morph state, pose evaluation, keyframe baking
  bone.ts            # DazBone extends DazNode: skeleton-relative bone locator + rotation/position accessors
  camera.ts          # DazCamera extends DazNode: optical/sensor properties
  light.ts           # DazLight extends DazNode: intensity/color/type properties
  material.ts        # DazMaterial extends DazElement: surface color/opacity/smoothing
  modifier.ts        # DazModifier extends DazElement: label/enabled (+ modifier-class dispatch table used by node.ts)
  morph.ts           # DazMorph extends DazModifier: value/min/max
  dforce.ts          # DazDForce extends DazModifier: freezeSimulation/freeze/unfreeze
  geometry.ts        # DazGeometry extends DazElement: chunked vertex/face/UV/group access, bounding boxes, pure-TS triangulate/asVec3
  viewport.ts        # DazViewport: draw style, size query, two-pass overlay-hiding capture()
  timeline.ts        # DazTimeline: frame/time/range/play/pause
  undo.ts            # UndoGroup + withUndo()
  index.ts           # extended with Phase 2 re-exports (Modify, not Create)
daz-ts/test/unit/
  element.test.ts
  property.test.ts
  node.test.ts
  scene.test.ts
  skeleton.test.ts
  bone.test.ts
  camera.test.ts
  light.test.ts
  material.test.ts
  modifier.test.ts    # covers modifier.ts, morph.ts, dforce.ts together (small, tightly coupled classes)
  geometry.test.ts
  viewport.test.ts
  timeline.test.ts
  undo.test.ts
daz-ts/test/integration/
  proxies.integration.test.ts   # gated on DAZ_SERVER_URL, mirrors Phase 1's skip_no_daz pattern
```

---

### Task 1: `DazElement` base proxy

**Files:**
- Create: `daz-ts/src/element.ts`
- Test: `daz-ts/test/unit/element.test.ts`
- Modify: `daz-ts/src/index.ts` (add `export { DazElement } from "./element.js";`)

**Interfaces:**
- Consumes: `DazClient` (`src/client.ts`, `execute(script, args?, opts?): Promise<ExecutionResult>`), `ScriptBuilder.iife`/`escapeString`/`serializeArg` (`src/scriptBuilder.ts`).
- Produces: `class DazElement { protected readonly client: DazClient; protected readonly locator: string; constructor(client: DazClient, locator: string); getProperty(label: string): Promise<unknown>; setProperty(label: string, value: unknown): Promise<void>; setProperties(values: Record<string, unknown>): Promise<Record<string, boolean>>; listProperties(): Promise<Array<{label: string; name: string; type: string}>>; numericProperties(): Promise<Record<string, unknown>>; className(): Promise<string | null>; snapshot(fields: string[]): Promise<Record<string, unknown>>; refresh(): void; }` — every other proxy class in this phase extends this and consumes `protected client`/`protected locator`.

- [ ] **Step 1: Write the failing test for `getProperty`/`setProperty`/`className`**

```typescript
import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazElement } from "../../src/element.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DazElement", () => {
  it("getProperty builds an IIFE that looks up findPropertyByLabel and returns its value", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ success: true, result: 42, output: [], request_id: "r1", duration_ms: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const el = new DazElement(client, "Scene.findNode(\"Genesis9\")");
    const result = await el.getProperty("Scale");

    expect(result).toBe(42);
    const [, init] = fetchMock.mock.calls[0];
    const script = JSON.parse(init.body as string).script;
    expect(script).toBe(
      '(function(){\n' +
      '            var obj = Scene.findNode("Genesis9");\n' +
      '            if (!obj) return null;\n' +
      '            var prop = obj.findPropertyByLabel("Scale");\n' +
      '            if (!prop) return null;\n' +
      '            return prop.getValue();\n' +
      '        \n})()'
    );
  });

  it("setProperty serializes the value via ScriptBuilder.serializeArg", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ success: true, result: null, output: [], request_id: "r2", duration_ms: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const el = new DazElement(client, "Scene.findNode(\"Genesis9\")");
    await el.setProperty("Scale", 1.5);

    const [, init] = fetchMock.mock.calls[0];
    const script = JSON.parse(init.body as string).script;
    expect(script).toContain('prop.setValue(1.5);');
    expect(script).toContain('findPropertyByLabel("Scale")');
  });

  it("className returns null when the locator resolves to nothing", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ success: true, result: null, output: [], request_id: "r3", duration_ms: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const el = new DazElement(client, "Scene.findNode(\"Missing\")");
    expect(await el.className()).toBeNull();
    const [, init] = fetchMock.mock.calls[0];
    const script = JSON.parse(init.body as string).script;
    expect(script).toBe('(function(){\nvar obj = Scene.findNode("Missing"); return obj ? obj.className() : null;\n})()');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/element.test.ts`
Expected: FAIL with "Cannot find module '../../src/element.js'"

- [ ] **Step 3: Implement `DazElement`**

```typescript
import type { DazClient } from "./client.js";
import { ScriptBuilder } from "./scriptBuilder.js";

/**
 * Generic proxy for any `DzElement` subclass. Base class for every typed
 * proxy in this SDK (`DazNode`, `DazMaterial`, etc.).
 *
 * `locator` is a DazScript expression that evaluates to the underlying
 * `DzElement` instance inside DAZ Studio; every method wraps a small IIFE
 * around it via {@link ScriptBuilder.iife}.
 */
export class DazElement {
  protected readonly client: DazClient;
  protected readonly locator: string;
  private readonly cache = new Map<string, unknown>();

  constructor(client: DazClient, locator: string) {
    this.client = client;
    this.locator = locator;
  }

  /** Return the current value of a property looked up by its display label, or `null` if not found. */
  async getProperty(label: string): Promise<unknown> {
    const script = ScriptBuilder.iife(`
            var obj = ${this.locator};
            if (!obj) return null;
            var prop = obj.findPropertyByLabel(${ScriptBuilder.escapeString(label)});
            if (!prop) return null;
            return prop.getValue();
        `);
    return (await this.client.execute(script)).value;
  }

  /** Set a property value by display label. `value` must be JSON-serializable. */
  async setProperty(label: string, value: unknown): Promise<void> {
    const serialized = ScriptBuilder.serializeArg(value);
    const script = ScriptBuilder.iife(`
            var obj = ${this.locator};
            if (!obj) return {"error": "not_found"};
            var prop = obj.findPropertyByLabel(${ScriptBuilder.escapeString(label)});
            if (!prop) return {"error": "property_not_found"};
            prop.setValue(${serialized});
            return {"success": true};
        `);
    await this.client.execute(script);
  }

  /**
   * Set multiple property values by display label in one call.
   * @returns `{label: true}` for labels that resolved to a real property and were written, `{label: false}` otherwise.
   */
  async setProperties(values: Record<string, unknown>): Promise<Record<string, boolean>> {
    const dataJson = JSON.stringify(values);
    const script = ScriptBuilder.iife(`
            var obj = ${this.locator};
            if (!obj) return null;
            var _data = ${dataJson};
            var _result = {};
            for (var _label in _data) {
                if (!_data.hasOwnProperty(_label)) continue;
                var prop = obj.findPropertyByLabel(_label);
                if (prop) {
                    prop.setValue(_data[_label]);
                    _result[_label] = true;
                } else {
                    _result[_label] = false;
                }
            }
            return _result;
        `);
    return ((await this.client.execute(script)).value as Record<string, boolean>) ?? {};
  }

  /** Return metadata (`label`/`name`/`type`) for every property on this element. */
  async listProperties(): Promise<Array<{ label: string; name: string; type: string }>> {
    const script = ScriptBuilder.iife(`
            var obj = ${this.locator};
            if (!obj) return null;
            var result = [];
            for (var i = 0; i < obj.getNumProperties(); i++) {
                var p = obj.getProperty(i);
                result.push({"label": p.getLabel(), "name": p.getName(), "type": p.className()});
            }
            return result;
        `);
    return ((await this.client.execute(script)).value as Array<{ label: string; name: string; type: string }>) ?? [];
  }

  /** Return every numeric property on this element as `{label: value}` in a single HTTP round-trip. */
  async numericProperties(): Promise<Record<string, unknown>> {
    const script = ScriptBuilder.iife(`
            var obj = ${this.locator};
            if (!obj) return null;
            var result = {};
            for (var i = 0; i < obj.getNumProperties(); i++) {
                var p = obj.getProperty(i);
                if (p.inherits("DzNumericProperty")) {
                    result[p.getLabel()] = p.getValue();
                }
            }
            return result;
        `);
    return ((await this.client.execute(script)).value as Record<string, unknown>) ?? {};
  }

  /** The DazScript class name of this element (e.g. `"DzFigure"`), or `null` if the locator resolves to nothing. */
  async className(): Promise<string | null> {
    const script = ScriptBuilder.iife(`var obj = ${this.locator}; return obj ? obj.className() : null;`);
    return (await this.client.execute(script)).value as string | null;
  }

  /**
   * Read and cache a set of property values in a single call.
   * Missing owner or missing property both resolve to `null` for the affected label(s).
   */
  async snapshot(fields: string[]): Promise<Record<string, unknown>> {
    const fieldsJson = JSON.stringify(fields);
    const script = ScriptBuilder.iife(`
            var obj = ${this.locator};
            if (!obj) return null;
            var _fields = ${fieldsJson};
            var _result = {};
            for (var i = 0; i < _fields.length; i++) {
                var prop = obj.findPropertyByLabel(_fields[i]);
                _result[_fields[i]] = prop ? prop.getValue() : null;
            }
            return _result;
        `);
    const values = ((await this.client.execute(script)).value as Record<string, unknown>) ?? {};
    for (const field of fields) {
      this.cache.set(field, values[field] ?? null);
    }
    const out: Record<string, unknown> = {};
    for (const field of fields) {
      out[field] = this.cache.get(field);
    }
    return out;
  }

  /** Clear the local property cache populated by {@link snapshot} so the next read fetches live data. */
  refresh(): void {
    this.cache.clear();
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd daz-ts && npx vitest run test/unit/element.test.ts`
Expected: PASS (3 tests)

- [ ] **Step 5: Add the barrel export and commit**

```typescript
// daz-ts/src/index.ts — add this line among the existing exports
export { DazElement } from "./element.js";
```

```bash
git add daz-ts/src/element.ts daz-ts/test/unit/element.test.ts daz-ts/src/index.ts
git commit -m "feat(daz-ts): port DazElement base proxy from dazpy _element.py"
```

---

### Task 2: `DazProperty` (value/rawValue/keyframes)

**Files:**
- Create: `daz-ts/src/property.ts`
- Test: `daz-ts/test/unit/property.test.ts`
- Modify: `daz-ts/src/index.ts` (add `export { DazProperty } from "./property.js";`)

**Interfaces:**
- Consumes: `DazElement` (Task 1, `protected client`/`protected locator`), `ScriptBuilder`.
- Produces: `class DazProperty extends DazElement { constructor(client: DazClient, ownerLocator: string, propertyLabel: string); static fromLocator(client: DazClient, locator: string): DazProperty; value(): Promise<unknown>; setValue(v: unknown): Promise<void>; rawValue(): Promise<unknown>; setRawValue(v: unknown): Promise<void>; label(): Promise<string | null>; min(): Promise<number | null>; max(): Promise<number | null>; setKey(time: number, value: number): Promise<void>; isAnimated(): Promise<boolean | null>; getKeys(): Promise<Array<{time: number; value: unknown}>>; removeKey(time: number): Promise<void>; clearKeys(): Promise<void>; }` — `DazProperty.fromLocator` is consumed by `DazNode.findProperty`/`.findPropertyByLabel` in Task 4.

- [ ] **Step 1: Write the failing test for construction, `value`, and the `rawValue` ERC-bypass fallback**

```typescript
import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazProperty } from "../../src/property.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubExecute(value: unknown): ReturnType<typeof vi.fn> {
  const fetchMock = vi
    .fn()
    .mockResolvedValue(jsonResponse({ success: true, result: value, output: [], request_id: "r1", duration_ms: 0 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("DazProperty", () => {
  it("constructor builds a findPropertyByLabel locator from the owner locator", async () => {
    const fetchMock = stubExecute(3);
    const client = new DazClient({ token: "" });
    const prop = new DazProperty(client, 'Scene.findNode("Genesis9")', "Scale");
    await prop.value();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      'var p = (function(){var obj = Scene.findNode("Genesis9");return obj ? obj.findPropertyByLabel("Scale") : null;})(); return p ? p.getValue() : null;',
    );
  });

  it("value getter/setter round-trip through getValue/setValue", async () => {
    const fetchMock = stubExecute(null);
    const client = new DazClient({ token: "" });
    const prop = DazProperty.fromLocator(client, "PLOC");
    await prop.setValue(2.5);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe("var p = PLOC; if (p) p.setValue(2.5);");
  });

  it("rawValue reads getRawValue() when present, falling back to getValue()", async () => {
    const fetchMock = stubExecute(1.0);
    const client = new DazClient({ token: "" });
    const prop = DazProperty.fromLocator(client, "PLOC");
    await prop.rawValue();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "var p = PLOC;\n" +
      "            if (!p) return null;\n" +
      '            return (typeof p.getRawValue === "function") ? p.getRawValue() : p.getValue();',
    );
  });

  it("setKey writes via setDoubleValue, never setKey/addKey", async () => {
    const fetchMock = stubExecute(null);
    const client = new DazClient({ token: "" });
    const prop = DazProperty.fromLocator(client, "PLOC");
    await prop.setKey(240, 0.5);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("p.setDoubleValue(240, 0.5)");
    expect(script).not.toContain(".setKey(");
    expect(script).not.toContain(".addKey(");
  });

  it("isAnimated is computed as getNumKeys() > 0, not a nonexistent isAnimated()", async () => {
    const fetchMock = stubExecute(true);
    const client = new DazClient({ token: "" });
    const prop = DazProperty.fromLocator(client, "PLOC");
    await prop.isAnimated();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("p.getNumKeys() > 0");
    expect(script).not.toContain(".isAnimated()");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/property.test.ts`
Expected: FAIL with "Cannot find module '../../src/property.js'"

- [ ] **Step 3: Implement `DazProperty`**

```typescript
import type { DazClient } from "./client.js";
import { DazElement } from "./element.js";
import { ScriptBuilder } from "./scriptBuilder.js";

/**
 * Proxy for a `DzProperty` on any `DzElement`. Typed read/write access to a
 * single named property, including keyframe support for animated properties.
 */
export class DazProperty extends DazElement {
  constructor(client: DazClient, ownerLocator: string, propertyLabel: string) {
    const locator =
      `(function(){` +
      `var obj = ${ownerLocator};` +
      `return obj ? obj.findPropertyByLabel(${ScriptBuilder.escapeString(propertyLabel)}) : null;` +
      `})()`;
    super(client, locator);
  }

  /** Construct a `DazProperty` from a pre-built DazScript locator expression. */
  static fromLocator(client: DazClient, locator: string): DazProperty {
    const prop = Object.create(DazProperty.prototype) as DazProperty;
    DazElement.call(prop as unknown as DazElement, client, locator);
    return prop;
  }

  /** Current property value (read/write). */
  async value(): Promise<unknown> {
    const script = ScriptBuilder.iife(`var p = ${this.locator}; return p ? p.getValue() : null;`);
    return (await this.client.execute(script)).value;
  }

  async setValue(v: unknown): Promise<void> {
    const script = ScriptBuilder.iife(`var p = ${this.locator}; if (p) p.setValue(${ScriptBuilder.serializeArg(v)});`);
    await this.client.execute(script);
  }

  /**
   * This property's own dial value, excluding any `DzERCLink` contributions.
   *
   * A property driven by one or more `DzERCLink` controllers computes
   * {@link value} as `rawValue` plus every controller's contribution — a
   * `value()`/`setValue()` snapshot/restore round trip is therefore *not*
   * idempotent for such properties (the captured post-ERC total gets
   * written back into the raw slot, then the links add their contribution
   * again on top). Use `rawValue`/`setRawValue` for exact round trips.
   * Falls back to `getValue()`/`setValue()` for property types without a
   * raw accessor.
   */
  async rawValue(): Promise<unknown> {
    const script = ScriptBuilder.iife(`
            var p = ${this.locator};
            if (!p) return null;
            return (typeof p.getRawValue === "function") ? p.getRawValue() : p.getValue();
        `);
    return (await this.client.execute(script)).value;
  }

  async setRawValue(v: unknown): Promise<void> {
    const serialized = ScriptBuilder.serializeArg(v);
    const script = ScriptBuilder.iife(`
            var p = ${this.locator};
            if (!p) return;
            if (typeof p.setRawValue === "function") { p.setRawValue(${serialized}); }
            else { p.setValue(${serialized}); }
        `);
    await this.client.execute(script);
  }

  /** The display label of this property (read-only). */
  async label(): Promise<string | null> {
    const script = ScriptBuilder.iife(`var p = ${this.locator}; return p ? p.getLabel() : null;`);
    return (await this.client.execute(script)).value as string | null;
  }

  /** Minimum allowed value (read-only; `null` if not applicable). */
  async min(): Promise<number | null> {
    const script = ScriptBuilder.iife(`var p = ${this.locator}; return (p && p.getMin) ? p.getMin() : null;`);
    return (await this.client.execute(script)).value as number | null;
  }

  /** Maximum allowed value (read-only; `null` if not applicable). */
  async max(): Promise<number | null> {
    const script = ScriptBuilder.iife(`var p = ${this.locator}; return (p && p.getMax) ? p.getMax() : null;`);
    return (await this.client.execute(script)).value as number | null;
  }

  /**
   * Set a keyframe for this (numeric) property via `DzNumericProperty.setDoubleValue(tm, val)` —
   * the DazScript keyframe surface confirmed live against a running DAZ Studio instance.
   * `DzProperty.setKey()`/`.addKey()` do not exist on a live property and silently write nothing.
   */
  async setKey(time: number, value: number): Promise<void> {
    const script = ScriptBuilder.iife(`
            var p = ${this.locator};
            if (p && p.setDoubleValue) p.setDoubleValue(${time}, ${value});
        `);
    await this.client.execute(script);
  }

  /**
   * `true` if this property has keyframe animation data (read-only).
   * Implemented as `getNumKeys() > 0` — `DzProperty.isAnimated()` does not
   * exist on a live property and raises `ScriptRuntimeError` on every access.
   */
  async isAnimated(): Promise<boolean | null> {
    const script = ScriptBuilder.iife(`
            var p = ${this.locator};
            if (!p || !p.getNumKeys) return null;
            return p.getNumKeys() > 0;
        `);
    return (await this.client.execute(script)).value as boolean | null;
  }

  /** List all keyframes on this property's animation curve, ordered by time. */
  async getKeys(): Promise<Array<{ time: number; value: unknown }>> {
    const script = ScriptBuilder.iife(`
            var p = ${this.locator};
            if (!p || !p.getNumKeys) return [];
            var n = p.getNumKeys();
            var keys = [];
            for (var i = 0; i < n; i++) {
                var t = p.getKeyTime(i);
                keys.push({ time: t.valueOf(), value: p.getDoubleValue(t) });
            }
            return keys;
        `);
    return ((await this.client.execute(script)).value as Array<{ time: number; value: unknown }>) ?? [];
  }

  /** Remove a single keyframe at the given time (no-op if no key exists exactly there). */
  async removeKey(time: number): Promise<void> {
    const script = ScriptBuilder.iife(`
            var p = ${this.locator};
            if (p && p.deleteKeys) p.deleteKeys(new DzTimeRange(${time}, ${time}));
        `);
    await this.client.execute(script);
  }

  /** Remove all keyframes from this property's animation curve. */
  async clearKeys(): Promise<void> {
    const script = ScriptBuilder.iife(`
            var p = ${this.locator};
            if (p && p.deleteAllKeys) p.deleteAllKeys();
        `);
    await this.client.execute(script);
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd daz-ts && npx vitest run test/unit/property.test.ts`
Expected: PASS (5 tests)

- [ ] **Step 5: Add the barrel export and commit**

```typescript
// daz-ts/src/index.ts
export { DazProperty } from "./property.js";
```

```bash
git add daz-ts/src/property.ts daz-ts/test/unit/property.test.ts daz-ts/src/index.ts
git commit -m "feat(daz-ts): port DazProperty with rawValue/setDoubleValue/getNumKeys gotchas"
```

---

### Task 3: `NodeIdentifier` + `ScriptBuilder` node helpers + `DazNode` part 1 (transforms, visibility, hierarchy)

**Files:**
- Modify: `daz-ts/src/scriptBuilder.ts` (add `findNodeExpr`/`nodeBody`/`nodeBodyFromLocator`/`skeletonLookup` static methods)
- Create: `daz-ts/src/node.ts` (`NodeIdentifier` type + `DazNode` class, part 1 of its methods)
- Test: `daz-ts/test/unit/scriptBuilder.test.ts` (Modify — add cases for the new helpers)
- Test: `daz-ts/test/unit/node.test.ts` (Create)
- Modify: `daz-ts/src/index.ts` (add `export { DazNode, type NodeIdentifier } from "./node.js";`)

**Interfaces:**
- Consumes: `DazElement` (Task 1), `ScriptBuilder.iife`/`escapeString` (Phase 1).
- Produces: `interface NodeIdentifier { value: string; kind: "name" | "label"; }`; `ScriptBuilder.findNodeExpr(identifier: NodeIdentifier): string`, `ScriptBuilder.nodeBody(identifier: NodeIdentifier, body: string): string`, `ScriptBuilder.nodeBodyFromLocator(locator: string, body: string): string`, `ScriptBuilder.skeletonLookup(identifier: NodeIdentifier): string` (unwrapped snippet, binds `_skel`, used by Task 5's `DazSkeleton`); `class DazNode extends DazElement { readonly identifier: NodeIdentifier; constructor(client: DazClient, identifier: NodeIdentifier); label(): Promise<string|null>; setLabel(v: string): Promise<void>; name(): Promise<string|null>; position(): Promise<{x:number;y:number;z:number}|null>; setPosition(x:number,y:number,z:number): Promise<void>; rotation(): Promise<{x:number;y:number;z:number;w:number}|null>; generalScale(): Promise<number|null>; scale(): Promise<{x:number;y:number;z:number;general:number}|null>; setScale(x:number,y:number,z:number): Promise<void>; setTransform(opts:{position?:[number,number,number];rotation?:[number,number,number];scale?:[number,number,number]}): Promise<void>; visible(): Promise<boolean|null>; setVisible(v:boolean): Promise<void>; parent(): Promise<DazNode|null>; children(): Promise<DazNode[]>; delete(): Promise<boolean>; reparent(newParent: DazNode, opts?: {preserveWorldTransform?: boolean}): Promise<void>; setRotation(x:number,y:number,z:number): Promise<void>; setPositionAtFrame(frame:number,x:number,y:number,z:number): Promise<void>; setRotationAtFrame(frame:number,x:number,y:number,z:number): Promise<void>; clearPositionKeys(): Promise<void>; clearRotationKeys(): Promise<void>; localPosition(): Promise<{x:number;y:number;z:number}|null>; setLocalPosition(x:number,y:number,z:number): Promise<void>; localEuler(): Promise<[number,number,number]|null>; localRotation(): Promise<{x:number;y:number;z:number;w:number}|null>; setLocalRotation(x:number,y:number,z:number): Promise<void>; isSelected(): Promise<boolean>; select(on?:boolean): Promise<void>; isInScene(): Promise<boolean>; isRoot(): Promise<boolean>; isVisibleInRender(): Promise<boolean>; setVisibleInRender(on:boolean): Promise<void>; isVisibleInViewport(): Promise<boolean>; setVisibleInViewport(on:boolean): Promise<void>; }` — Task 4 adds more methods to this same class (same file). Consumed by `DazScene` (Task 13-14) and `DazSkeleton`/`DazBone`/`DazCamera`/`DazLight` (Tasks 5-9), which all extend `DazNode`.

- [ ] **Step 1: Write the failing test for the new `ScriptBuilder` helpers**

```typescript
// Append to daz-ts/test/unit/scriptBuilder.test.ts
import type { NodeIdentifier } from "../../src/node.js";

describe("ScriptBuilder node helpers", () => {
  it("findNodeExpr uses Scene.findNode for kind 'name'", () => {
    const id: NodeIdentifier = { value: "Genesis9", kind: "name" };
    expect(ScriptBuilder.findNodeExpr(id)).toBe('Scene.findNode("Genesis9")');
  });

  it("findNodeExpr uses Scene.findNodeByLabel for kind 'label'", () => {
    const id: NodeIdentifier = { value: "Genesis 9", kind: "label" };
    expect(ScriptBuilder.findNodeExpr(id)).toBe('Scene.findNodeByLabel("Genesis 9")');
  });

  it("nodeBody wraps body with a null-checked _node binding", () => {
    const id: NodeIdentifier = { value: "Genesis9", kind: "name" };
    expect(ScriptBuilder.nodeBody(id, "return _node.getLabel();")).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\nreturn _node.getLabel();\n})()',
    );
  });

  it("nodeBodyFromLocator wraps body around a pre-built locator", () => {
    expect(ScriptBuilder.nodeBodyFromLocator("LOC", "return 1;")).toBe(
      "(function(){\nvar _node = LOC;\nif (!_node) return null;\nreturn 1;\n})()",
    );
  });

  it("skeletonLookup matches by label when kind is 'label', by name otherwise, without wrapping in an IIFE", () => {
    const byLabel: NodeIdentifier = { value: "Genesis 9", kind: "label" };
    expect(ScriptBuilder.skeletonLookup(byLabel)).toBe(
      'var _skel=null,_skels=Scene.getSkeletonList();for(var _i=0;_i<_skels.length;_i++){if(_skels[_i].getLabel() === "Genesis 9"){_skel=_skels[_i];break;}}',
    );
    const byName: NodeIdentifier = { value: "Genesis9", kind: "name" };
    expect(ScriptBuilder.skeletonLookup(byName)).toContain('_skels[_i].getName() === "Genesis9"');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/scriptBuilder.test.ts`
Expected: FAIL — `ScriptBuilder.findNodeExpr is not a function`, and the `../../src/node.js` type import fails to resolve.

- [ ] **Step 3: Add the node helpers to `ScriptBuilder`**

```typescript
// Append inside the ScriptBuilder class in daz-ts/src/scriptBuilder.ts
import type { NodeIdentifier } from "./node.js";
// ... (add above the class, alongside the existing imports — scriptBuilder.ts currently has none)

  /** DazScript expression that resolves `identifier` via `Scene.findNode`/`.findNodeByLabel`. */
  static findNodeExpr(identifier: NodeIdentifier): string {
    if (identifier.kind === "label") {
      return `Scene.findNodeByLabel(${ScriptBuilder.escapeString(identifier.value)})`;
    }
    return `Scene.findNode(${ScriptBuilder.escapeString(identifier.value)})`;
  }

  /** Wrap `body` in an IIFE that resolves `identifier` to `_node` and null-guards it. */
  static nodeBody(identifier: NodeIdentifier, body: string): string {
    const expr = ScriptBuilder.findNodeExpr(identifier);
    return ScriptBuilder.iife(`var _node = ${expr};\nif (!_node) return null;\n${body}`);
  }

  /** Like {@link nodeBody} but uses a pre-built DazScript locator expression for `_node`. */
  static nodeBodyFromLocator(locator: string, body: string): string {
    return ScriptBuilder.iife(`var _node = ${locator};\nif (!_node) return null;\n${body}`);
  }

  /**
   * Return a JS snippet (not wrapped in an IIFE) that finds a skeleton by
   * `identifier` and binds it to `_skel`. Embed at the top of a larger body
   * and follow with `if (!_skel) return null;`.
   */
  static skeletonLookup(identifier: NodeIdentifier): string {
    const value = ScriptBuilder.escapeString(identifier.value);
    const match =
      identifier.kind === "label" ? `_skels[_i].getLabel() === ${value}` : `_skels[_i].getName() === ${value}`;
    return (
      `var _skel=null,_skels=Scene.getSkeletonList();` +
      `for(var _i=0;_i<_skels.length;_i++){` +
      `if(${match}){_skel=_skels[_i];break;}}`
    );
  }
```

- [ ] **Step 4: Run `scriptBuilder.test.ts` to verify the new cases pass**

Run: `cd daz-ts && npx vitest run test/unit/scriptBuilder.test.ts`
Expected: PASS (existing Phase 1 cases + 5 new cases)

- [ ] **Step 5: Write the failing test for `DazNode` transforms/visibility/hierarchy**

```typescript
import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazNode } from "../../src/node.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}
afterEach(() => vi.unstubAllGlobals());

function stub(value: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ success: true, result: value, output: [], request_id: "r", duration_ms: 0 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("DazNode transforms", () => {
  it("position() reads getWSPos as {x,y,z}", async () => {
    const fetchMock = stub({ x: 1, y: 2, z: 3 });
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await node.position()).toEqual({ x: 1, y: 2, z: 3 });
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\nvar _node = Scene.findNode("Genesis9");\nif (!_node) return null;\nvar p = _node.getWSPos(); return {x: p.x, y: p.y, z: p.z};\n})()',
    );
  });

  it("setPosition writes a new DzVec3 via setWSPos", async () => {
    const fetchMock = stub(null);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await node.setPosition(1, 2, 3);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("_node.setWSPos(new DzVec3(1, 2, 3));");
  });

  it("setTransform emits only the lines for the provided components, in position/rotation/scale order", async () => {
    const fetchMock = stub(null);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await node.setTransform({ position: [1, 0, 0], scale: [2, 2, 2] });
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("_node.setLocalPos(new DzVec3(1, 0, 0));");
    expect(script).toContain("_node.getXScaleControl().setValue(2)");
    expect(script).not.toContain("RotControl().setValue");
  });

  it("setTransform with no arguments makes no HTTP call", async () => {
    const fetchMock = stub(null);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await node.setTransform({});
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("parent() returns null for a root node and a DazNode wrapping the parent otherwise", async () => {
    const fetchMock = stub("Torso");
    const node = new DazNode(new DazClient({ token: "" }), { value: "Head", kind: "name" });
    const parent = await node.parent();
    expect(parent).toBeInstanceOf(DazNode);
    expect(parent?.identifier).toEqual({ value: "Torso", kind: "name" });
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("var p = _node.getNodeParent(); return p ? p.getName() : null;");
  });

  it("children() maps each returned name to a DazNode", async () => {
    stub(["Hand", "Foot"]);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Torso", kind: "name" });
    const children = await node.children();
    expect(children.map((c) => c.identifier.value)).toEqual(["Hand", "Foot"]);
  });

  it("delete() returns the boolean result of Scene.removeNode", async () => {
    const fetchMock = stub(true);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Prop", kind: "name" });
    expect(await node.delete()).toBe(true);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("return Scene.removeNode(_node);");
  });

  it("reparent throws ScriptRuntimeError when the server reports a non-null result", async () => {
    stub("new parent not found");
    const node = new DazNode(new DazClient({ token: "" }), { value: "Prop", kind: "name" });
    const other = new DazNode(new DazClient({ token: "" }), { value: "Ghost", kind: "name" });
    await expect(node.reparent(other)).rejects.toThrow(/reparent failed/);
  });

  it("visible getter/setter round-trip isVisible/setVisible", async () => {
    const fetchMock = stub(null);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Prop", kind: "name" });
    await node.setVisible(false);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("_node.setVisible(false);");
  });
});
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/node.test.ts`
Expected: FAIL with "Cannot find module '../../src/node.js'"

- [ ] **Step 7: Implement `NodeIdentifier` and `DazNode` part 1**

```typescript
import type { DazClient } from "./client.js";
import { DazElement } from "./element.js";
import { ScriptRuntimeError } from "./exceptions.js";
import { ScriptBuilder } from "./scriptBuilder.js";

/** Identifies a scene node by name or label. */
export interface NodeIdentifier {
  /** The name or label string used to look up the node. */
  value: string;
  /** `"name"` uses `Scene.findNode()`; `"label"` uses `Scene.findNodeByLabel()`. */
  kind: "name" | "label";
}

/**
 * Proxy for a `DzNode` in the active DAZ Studio scene. Provides access to
 * transforms, hierarchy, visibility, materials, modifiers, and geometry.
 * Instances are typically obtained from {@link DazScene} rather than
 * constructed directly. All reads may resolve to `null` if the node no
 * longer exists in the scene.
 */
export class DazNode extends DazElement {
  readonly identifier: NodeIdentifier;

  constructor(client: DazClient, identifier: NodeIdentifier) {
    super(client, ScriptBuilder.findNodeExpr(identifier));
    this.identifier = identifier;
  }

  protected nodeScript(body: string): string {
    return ScriptBuilder.nodeBody(this.identifier, body);
  }

  /** User-visible display label shown in the Scene panel (read/write). */
  async label(): Promise<string | null> {
    return (await this.client.execute(this.nodeScript("return _node.getLabel();"))).value as string | null;
  }

  async setLabel(value: string): Promise<void> {
    await this.client.execute(this.nodeScript(`_node.setLabel(${ScriptBuilder.escapeString(value)});`));
  }

  /** Internal node name used to look up the node (read-only). */
  async name(): Promise<string | null> {
    return (await this.client.execute(this.nodeScript("return _node.getName();"))).value as string | null;
  }

  /** World-space position as `{x, y, z}` (read-only; use {@link setPosition} to change). */
  async position(): Promise<{ x: number; y: number; z: number } | null> {
    return (await this.client.execute(this.nodeScript("var p = _node.getWSPos(); return {x: p.x, y: p.y, z: p.z};")))
      .value as { x: number; y: number; z: number } | null;
  }

  async setPosition(x: number, y: number, z: number): Promise<void> {
    await this.client.execute(this.nodeScript(`_node.setWSPos(new DzVec3(${x}, ${y}, ${z}));`));
  }

  /** World-space rotation as `{x, y, z, w}` quaternion (read-only; use {@link setRotation} for Euler degrees). */
  async rotation(): Promise<{ x: number; y: number; z: number; w: number } | null> {
    return (
      await this.client.execute(this.nodeScript("var r = _node.getWSRot(); return {x: r.x, y: r.y, z: r.z, w: r.w};"))
    ).value as { x: number; y: number; z: number; w: number } | null;
  }

  /** Uniform scale factor (read-only). */
  async generalScale(): Promise<number | null> {
    return (await this.client.execute(this.nodeScript("return _node.getScaleControl().getValue();"))).value as
      | number
      | null;
  }

  /** Per-axis and uniform scale as `{x, y, z, general}` (read-only; use {@link setScale} to change per-axis values). */
  async scale(): Promise<{ x: number; y: number; z: number; general: number } | null> {
    return (
      await this.client.execute(
        this.nodeScript(
          "return {x: _node.getXScaleControl().getValue(), y: _node.getYScaleControl().getValue(), z: _node.getZScaleControl().getValue(), general: _node.getScaleControl().getValue()};",
        ),
      )
    ).value as { x: number; y: number; z: number; general: number } | null;
  }

  /** Set per-axis local scale (does not affect the general/uniform scale dial; see {@link generalScale}). */
  async setScale(x: number, y: number, z: number): Promise<void> {
    await this.client.execute(
      this.nodeScript(
        `_node.getXScaleControl().setValue(${x}); _node.getYScaleControl().setValue(${y}); _node.getZScaleControl().setValue(${z});`,
      ),
    );
  }

  /** Set any combination of local position/rotation(Euler degrees)/scale in one round trip; omitted components are left untouched. */
  async setTransform(opts: {
    position?: [number, number, number];
    rotation?: [number, number, number];
    scale?: [number, number, number];
  }): Promise<void> {
    const lines: string[] = [];
    if (opts.position !== undefined) {
      const [x, y, z] = opts.position;
      lines.push(`_node.setLocalPos(new DzVec3(${x}, ${y}, ${z}));`);
    }
    if (opts.rotation !== undefined) {
      const [x, y, z] = opts.rotation;
      lines.push(
        `_node.getXRotControl().setValue(${x}); _node.getYRotControl().setValue(${y}); _node.getZRotControl().setValue(${z});`,
      );
    }
    if (opts.scale !== undefined) {
      const [x, y, z] = opts.scale;
      lines.push(
        `_node.getXScaleControl().setValue(${x}); _node.getYScaleControl().setValue(${y}); _node.getZScaleControl().setValue(${z});`,
      );
    }
    if (lines.length === 0) return;
    await this.client.execute(this.nodeScript(lines.join("\n")));
  }

  /** General visibility flag, affecting both viewport and render unless overridden per-channel (read/write). */
  async visible(): Promise<boolean | null> {
    return (await this.client.execute(this.nodeScript("return _node.isVisible();"))).value as boolean | null;
  }

  async setVisible(value: boolean): Promise<void> {
    await this.client.execute(this.nodeScript(`_node.setVisible(${value ? "true" : "false"});`));
  }

  /** Parent node in the scene hierarchy, or `null` for root nodes. */
  async parent(): Promise<DazNode | null> {
    const name = (await this.client.execute(
      this.nodeScript("var p = _node.getNodeParent(); return p ? p.getName() : null;"),
    )).value as string | null;
    if (name === null) return null;
    return new DazNode(this.client, { value: name, kind: "name" });
  }

  /** Direct child nodes. */
  async children(): Promise<DazNode[]> {
    const names =
      ((await this.client.execute(
        this.nodeScript(
          "var names = []; for (var i = 0; i < _node.getNumNodeChildren(); i++) { names.push(_node.getNodeChild(i).getName()); } return names;",
        ),
      )).value as string[]) ?? [];
    return names.map((n) => new DazNode(this.client, { value: n, kind: "name" }));
  }

  /** Remove this node from the scene entirely. @returns `true` if found and removed. */
  async delete(): Promise<boolean> {
    return Boolean((await this.client.execute(this.nodeScript("return Scene.removeNode(_node);"))).value);
  }

  /**
   * Move this node to a new position in the scene hierarchy via the
   * `removeNodeChild`/`addNodeChild` pattern.
   * @param preserveWorldTransform When `true` (default), keeps world-space transform, adjusting local transform to compensate.
   */
  async reparent(newParent: DazNode, opts: { preserveWorldTransform?: boolean } = {}): Promise<void> {
    const { preserveWorldTransform = true } = opts;
    const parentExpr = ScriptBuilder.findNodeExpr(newParent.identifier);
    const inPlace = preserveWorldTransform ? "true" : "false";
    const result = (await this.client.execute(
      this.nodeScript(`
            var _newParent = ${parentExpr};
            if (!_newParent) return "new parent not found";
            var _oldParent = _node.getNodeParent();
            if (_oldParent) _oldParent.removeNodeChild(_node, ${inPlace});
            var _err = _newParent.addNodeChild(_node, ${inPlace});
            var _errNum = _err ? _err.valueOf() : 0;
            return _errNum !== 0 ? ("DzError code " + _errNum) : null;
            `),
    )).value as string | null;
    if (result) {
      throw new ScriptRuntimeError(`reparent failed: ${result}`);
    }
  }

  /** Set the world-space rotation using Euler angles in degrees. */
  async setRotation(x: number, y: number, z: number): Promise<void> {
    await this.client.execute(
      this.nodeScript(
        `_node.getXRotControl().setValue(${x}); _node.getYRotControl().setValue(${y}); _node.getZRotControl().setValue(${z});`,
      ),
    );
  }

  /** Write a real position keyframe at timeline `frame` (converted to ticks via `Scene.getTimeStep()`). */
  async setPositionAtFrame(frame: number, x: number, y: number, z: number): Promise<void> {
    await this.client.execute(
      this.nodeScript(
        `var _tm = ${Math.trunc(frame)} * Scene.getTimeStep(); _node.setWSPos(_tm, new DzVec3(${x}, ${y}, ${z}));`,
      ),
    );
  }

  /** Write a real Euler rotation keyframe at timeline `frame`. See {@link setPositionAtFrame} for the tick conversion. */
  async setRotationAtFrame(frame: number, x: number, y: number, z: number): Promise<void> {
    await this.client.execute(
      this.nodeScript(
        `var _tm = ${Math.trunc(frame)} * Scene.getTimeStep(); ` +
          `_node.getXRotControl().setDoubleValue(_tm, ${x}); ` +
          `_node.getYRotControl().setDoubleValue(_tm, ${y}); ` +
          `_node.getZRotControl().setDoubleValue(_tm, ${z});`,
      ),
    );
  }

  /** Remove all keyframes from this node's X/Y/Z position controls (call before a fresh {@link setPositionAtFrame} curve). */
  async clearPositionKeys(): Promise<void> {
    await this.client.execute(
      this.nodeScript(
        "_node.getXPosControl().deleteAllKeys(); _node.getYPosControl().deleteAllKeys(); _node.getZPosControl().deleteAllKeys();",
      ),
    );
  }

  /** Remove all keyframes from this node's X/Y/Z rotation controls. See {@link clearPositionKeys}. */
  async clearRotationKeys(): Promise<void> {
    await this.client.execute(
      this.nodeScript(
        "_node.getXRotControl().deleteAllKeys(); _node.getYRotControl().deleteAllKeys(); _node.getZRotControl().deleteAllKeys();",
      ),
    );
  }

  /** Local-space position as `{x, y, z}` (read-only). */
  async localPosition(): Promise<{ x: number; y: number; z: number } | null> {
    return (await this.client.execute(this.nodeScript("var p = _node.getLocalPos(); return {x: p.x, y: p.y, z: p.z};")))
      .value as { x: number; y: number; z: number } | null;
  }

  async setLocalPosition(x: number, y: number, z: number): Promise<void> {
    await this.client.execute(this.nodeScript(`_node.setLocalPos(new DzVec3(${x}, ${y}, ${z}));`));
  }

  /** Local-space rotation as `(x, y, z)` Euler degrees; exact inverse of {@link setLocalRotation}. */
  async localEuler(): Promise<[number, number, number] | null> {
    const result = (await this.client.execute(
      this.nodeScript(
        "return [_node.getXRotControl().getValue(), _node.getYRotControl().getValue(), _node.getZRotControl().getValue()];",
      ),
    )).value as number[] | null;
    if (result === null) return null;
    return [result[0], result[1], result[2]];
  }

  /** Local-space rotation as `{x, y, z, w}` quaternion (read-only). */
  async localRotation(): Promise<{ x: number; y: number; z: number; w: number } | null> {
    return (
      await this.client.execute(this.nodeScript("var r = _node.getLocalRot(); return {x: r.x, y: r.y, z: r.z, w: r.w};"))
    ).value as { x: number; y: number; z: number; w: number } | null;
  }

  async setLocalRotation(x: number, y: number, z: number): Promise<void> {
    await this.client.execute(
      this.nodeScript(
        `_node.getXRotControl().setValue(${x}); _node.getYRotControl().setValue(${y}); _node.getZRotControl().setValue(${z});`,
      ),
    );
  }

  async isSelected(): Promise<boolean> {
    return Boolean((await this.client.execute(this.nodeScript("return _node.isSelected();"))).value);
  }

  async select(on = true): Promise<void> {
    await this.client.execute(this.nodeScript(`_node.select(${on ? "true" : "false"});`));
  }

  async isInScene(): Promise<boolean> {
    return Boolean((await this.client.execute(this.nodeScript("return _node.isInScene();"))).value);
  }

  /** `true` if this node has no parent (top-level node). */
  async isRoot(): Promise<boolean> {
    return Boolean((await this.client.execute(this.nodeScript("return _node.isRootNode();"))).value);
  }

  async isVisibleInRender(): Promise<boolean> {
    return Boolean((await this.client.execute(this.nodeScript("return _node.isVisibleInRender();"))).value);
  }

  async setVisibleInRender(on: boolean): Promise<void> {
    await this.client.execute(this.nodeScript(`_node.setVisibleInRender(${on ? "true" : "false"});`));
  }

  async isVisibleInViewport(): Promise<boolean> {
    return Boolean((await this.client.execute(this.nodeScript("return _node.isVisibleInViewport();"))).value);
  }

  async setVisibleInViewport(on: boolean): Promise<void> {
    await this.client.execute(this.nodeScript(`_node.setVisibleInViewport(${on ? "true" : "false"});`));
  }
}
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd daz-ts && npx vitest run test/unit/node.test.ts`
Expected: PASS (9 tests)

- [ ] **Step 9: Add the barrel export and commit**

```typescript
// daz-ts/src/index.ts
export { DazNode, type NodeIdentifier } from "./node.js";
```

```bash
git add daz-ts/src/scriptBuilder.ts daz-ts/src/node.ts daz-ts/test/unit/scriptBuilder.test.ts daz-ts/test/unit/node.test.ts daz-ts/src/index.ts
git commit -m "feat(daz-ts): add ScriptBuilder node helpers and DazNode transforms/hierarchy"
```

---

### Task 4: `DazMaterial`

**Files:**
- Create: `daz-ts/src/material.ts`
- Test: `daz-ts/test/unit/material.test.ts`
- Modify: `daz-ts/src/index.ts` (add `export { DazMaterial } from "./material.js";`)

**Interfaces:**
- Consumes: `DazElement` (Task 1).
- Produces: `class DazMaterial extends DazElement { materialName(): Promise<string|null>; diffuseColor(): Promise<{r:number;g:number;b:number}|null>; setDiffuseColor(rgb: {r:number;g:number;b:number} | [number,number,number]): Promise<void>; opacity(): Promise<number|null>; setOpacity(v:number): Promise<void>; colorMap(): Promise<string|null>; isSmoothingOn(): Promise<boolean|null>; smoothingAngle(): Promise<number|null>; setSmoothingAngle(v:number): Promise<void>; isOpaque(): Promise<boolean|null>; }` — consumed by `DazNode.materials()`/`.findMaterial()` in Task 6.

- [ ] **Step 1: Write the failing test**

```typescript
import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazMaterial } from "../../src/material.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}
afterEach(() => vi.unstubAllGlobals());
function stub(value: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ success: true, result: value, output: [], request_id: "r", duration_ms: 0 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("DazMaterial", () => {
  it("diffuseColor reads {r,g,b} from getDiffuseColor()", async () => {
    const fetchMock = stub({ r: 255, g: 0, b: 0 });
    const mat = new DazMaterial(new DazClient({ token: "" }), "MLOC");
    expect(await mat.diffuseColor()).toEqual({ r: 255, g: 0, b: 0 });
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      '(function(){\n            var m = MLOC;\n            if (!m) return null;\n            var c = m.getDiffuseColor();\n            return {r: c.red, g: c.green, b: c.blue};\n        \n})()',
    );
  });

  it("setDiffuseColor accepts a plain array and builds a new Color(...)", async () => {
    const fetchMock = stub(null);
    const mat = new DazMaterial(new DazClient({ token: "" }), "MLOC");
    await mat.setDiffuseColor([10, 20, 30]);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("new Color(10, 20, 30)");
  });

  it("opacity getter/setter round-trip getBaseOpacity/setBaseOpacity", async () => {
    const fetchMock = stub(null);
    const mat = new DazMaterial(new DazClient({ token: "" }), "MLOC");
    await mat.setOpacity(0.5);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("m.setBaseOpacity(0.5)");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/material.test.ts`
Expected: FAIL with "Cannot find module '../../src/material.js'"

- [ ] **Step 3: Implement `DazMaterial`**

```typescript
import { DazElement } from "./element.js";
import { ScriptBuilder } from "./scriptBuilder.js";

/** Proxy for a `DzMaterial` surface, obtained via `DazNode.materials()`/`.findMaterial()`. */
export class DazMaterial extends DazElement {
  async materialName(): Promise<string | null> {
    return (await this.client.execute(ScriptBuilder.iife(`var m = ${this.locator}; return m ? m.getName() : null;`)))
      .value as string | null;
  }

  /** Diffuse colour as `{r, g, b}` (0-255, read/write via {@link setDiffuseColor}). */
  async diffuseColor(): Promise<{ r: number; g: number; b: number } | null> {
    const script = ScriptBuilder.iife(`
            var m = ${this.locator};
            if (!m) return null;
            var c = m.getDiffuseColor();
            return {r: c.red, g: c.green, b: c.blue};
        `);
    return (await this.client.execute(script)).value as { r: number; g: number; b: number } | null;
  }

  async setDiffuseColor(value: { r: number; g: number; b: number } | [number, number, number]): Promise<void> {
    const [r, g, b] = Array.isArray(value) ? value : [value.r, value.g, value.b];
    const script = ScriptBuilder.iife(`
            var m = ${this.locator};
            if (!m) return;
            var c = new Color(${Math.trunc(r)}, ${Math.trunc(g)}, ${Math.trunc(b)});
            m.setDiffuseColor(c);
        `);
    await this.client.execute(script);
  }

  /** Base opacity/transparency (0.0 transparent - 1.0 opaque, read/write). */
  async opacity(): Promise<number | null> {
    return (await this.client.execute(ScriptBuilder.iife(`var m = ${this.locator}; return m ? m.getBaseOpacity() : null;`)))
      .value as number | null;
  }

  async setOpacity(value: number): Promise<void> {
    await this.client.execute(ScriptBuilder.iife(`var m = ${this.locator}; if (m) m.setBaseOpacity(${value});`));
  }

  /** File path of the diffuse colour texture, or `null`. */
  async colorMap(): Promise<string | null> {
    const script = ScriptBuilder.iife(`
            var m = ${this.locator};
            if (!m) return null;
            var t = m.getColorMap();
            return t ? t.getFilename() : null;
        `);
    return (await this.client.execute(script)).value as string | null;
  }

  async isSmoothingOn(): Promise<boolean | null> {
    return (await this.client.execute(ScriptBuilder.iife(`var m = ${this.locator}; return m ? m.isSmoothingOn() : null;`)))
      .value as boolean | null;
  }

  /** Normal smoothing angle in degrees (read/write). */
  async smoothingAngle(): Promise<number | null> {
    return (
      await this.client.execute(ScriptBuilder.iife(`var m = ${this.locator}; return m ? m.getSmoothingAngle() : null;`))
    ).value as number | null;
  }

  async setSmoothingAngle(value: number): Promise<void> {
    await this.client.execute(ScriptBuilder.iife(`var m = ${this.locator}; if (m) m.setSmoothingAngle(${value});`));
  }

  /** `true` if the material is fully opaque (opacity == 1.0). */
  async isOpaque(): Promise<boolean | null> {
    return (await this.client.execute(ScriptBuilder.iife(`var m = ${this.locator}; return m ? m.isOpaque() : null;`)))
      .value as boolean | null;
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd daz-ts && npx vitest run test/unit/material.test.ts`
Expected: PASS (3 tests)

- [ ] **Step 5: Add the barrel export and commit**

```typescript
// daz-ts/src/index.ts
export { DazMaterial } from "./material.js";
```

```bash
git add daz-ts/src/material.ts daz-ts/test/unit/material.test.ts daz-ts/src/index.ts
git commit -m "feat(daz-ts): port DazMaterial from dazpy _material.py"
```

---

### Task 5: `DazModifier`, `DazMorph`, `DazDForce`

**Files:**
- Create: `daz-ts/src/modifier.ts` (`DazModifier`)
- Create: `daz-ts/src/morph.ts` (`DazMorph extends DazModifier`)
- Create: `daz-ts/src/dforce.ts` (`DazDForce extends DazModifier`)
- Test: `daz-ts/test/unit/modifier.test.ts` (covers all three — small, tightly coupled classes)
- Modify: `daz-ts/src/index.ts` (add exports for all three)

**Interfaces:**
- Consumes: `DazElement` (Task 1).
- Produces: `class DazModifier extends DazElement { modifierLabel(): Promise<string|null>; enabled(): Promise<boolean|null>; setEnabled(v:boolean): Promise<void>; }`; `class DazMorph extends DazModifier { value(): Promise<number|null>; setValue(v:number): Promise<void>; min(): Promise<number|null>; max(): Promise<number|null>; }`; `class DazDForce extends DazModifier { freezeSimulation(): Promise<boolean|null>; setFreezeSimulation(v:boolean): Promise<void>; freeze(): Promise<void>; unfreeze(): Promise<void>; }` — all three consumed by `DazNode`'s modifier-dispatch table in Task 6.

- [ ] **Step 1: Write the failing tests**

```typescript
import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazModifier } from "../../src/modifier.js";
import { DazMorph } from "../../src/morph.js";
import { DazDForce } from "../../src/dforce.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}
afterEach(() => vi.unstubAllGlobals());
function stub(value: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ success: true, result: value, output: [], request_id: "r", duration_ms: 0 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("DazModifier", () => {
  it("enabled getter/setter round-trip isEnabled/setEnabled", async () => {
    const fetchMock = stub(null);
    const mod = new DazModifier(new DazClient({ token: "" }), "MODLOC");
    await mod.setEnabled(false);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe('(function(){\nvar m = MODLOC; if (m) m.setEnabled(false);\n})()');
  });
});

describe("DazMorph", () => {
  it("value getter/setter round-trip getValueChannel().getValue()/setValue()", async () => {
    const fetchMock = stub(null);
    const morph = new DazMorph(new DazClient({ token: "" }), "MORPHLOC");
    await morph.setValue(0.75);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe('(function(){\nvar m = MORPHLOC; if (m) m.getValueChannel().setValue(0.75);\n})()');
  });
});

describe("DazDForce", () => {
  it("freezeSimulation reads the 'Freeze Simulation' property by label", async () => {
    const fetchMock = stub(true);
    const dforce = new DazDForce(new DazClient({ token: "" }), "DFLOC");
    expect(await dforce.freezeSimulation()).toBe(true);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain('findPropertyByLabel("Freeze Simulation")');
  });

  it("freeze()/unfreeze() delegate to setFreezeSimulation(true/false)", async () => {
    const fetchMock = stub(null);
    const dforce = new DazDForce(new DazClient({ token: "" }), "DFLOC");
    await dforce.freeze();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("p.setValue(true)");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/modifier.test.ts`
Expected: FAIL with "Cannot find module '../../src/modifier.js'"

- [ ] **Step 3: Implement all three classes**

```typescript
// daz-ts/src/modifier.ts
import { DazElement } from "./element.js";
import { ScriptBuilder } from "./scriptBuilder.js";

/**
 * Proxy for a `DzModifier` (constraint, formula, etc.) on a node, obtained
 * via `DazNode.modifiers()`/`.findModifier()`. Morph/blendshape modifiers
 * are returned as the more specific {@link DazMorph} automatically; dForce
 * simulation modifiers as {@link DazDForce}.
 */
export class DazModifier extends DazElement {
  /** User-visible display label of this modifier (read-only). */
  async modifierLabel(): Promise<string | null> {
    return (await this.client.execute(ScriptBuilder.iife(`var m = ${this.locator}; return m ? m.getLabel() : null;`)))
      .value as string | null;
  }

  /** Whether this modifier is currently active (read/write). */
  async enabled(): Promise<boolean | null> {
    return (await this.client.execute(ScriptBuilder.iife(`var m = ${this.locator}; return m ? m.isEnabled() : null;`)))
      .value as boolean | null;
  }

  async setEnabled(value: boolean): Promise<void> {
    await this.client.execute(ScriptBuilder.iife(`var m = ${this.locator}; if (m) m.setEnabled(${value ? "true" : "false"});`));
  }
}
```

```typescript
// daz-ts/src/morph.ts
import { DazModifier } from "./modifier.js";
import { ScriptBuilder } from "./scriptBuilder.js";

/** Proxy for a `DzMorph` blendshape slider, returned by `DazNode.morphs()`/`.findModifier()`. */
export class DazMorph extends DazModifier {
  /** Current morph strength (typically 0.0-1.0, read/write). */
  async value(): Promise<number | null> {
    return (
      await this.client.execute(ScriptBuilder.iife(`var m = ${this.locator}; return m ? m.getValueChannel().getValue() : null;`))
    ).value as number | null;
  }

  async setValue(v: number): Promise<void> {
    await this.client.execute(ScriptBuilder.iife(`var m = ${this.locator}; if (m) m.getValueChannel().setValue(${v});`));
  }

  /** Minimum allowed value for this morph channel (read-only). */
  async min(): Promise<number | null> {
    return (
      await this.client.execute(ScriptBuilder.iife(`var m = ${this.locator}; return m ? m.getValueChannel().getMin() : null;`))
    ).value as number | null;
  }

  /** Maximum allowed value for this morph channel (read-only). */
  async max(): Promise<number | null> {
    return (
      await this.client.execute(ScriptBuilder.iife(`var m = ${this.locator}; return m ? m.getValueChannel().getMax() : null;`))
    ).value as number | null;
  }
}
```

```typescript
// daz-ts/src/dforce.ts
import { DazModifier } from "./modifier.js";
import { ScriptBuilder } from "./scriptBuilder.js";

/**
 * Proxy for a `DzDForceModifier` (cloth/hair dForce simulation modifier).
 * Tunables not covered here (e.g. "Dynamics Strength") are reachable via
 * the inherited `DazElement.getProperty`/`.setProperty`.
 */
export class DazDForce extends DazModifier {
  /** Whether the simulated result is frozen onto the mesh (read/write) — DAZ Studio's equivalent of "baking" a dForce result. */
  async freezeSimulation(): Promise<boolean | null> {
    const script = ScriptBuilder.iife(`
            var m = ${this.locator};
            if (!m) return null;
            var p = m.findPropertyByLabel("Freeze Simulation");
            return p ? p.getValue() : null;
        `);
    return (await this.client.execute(script)).value as boolean | null;
  }

  async setFreezeSimulation(value: boolean): Promise<void> {
    const flag = value ? "true" : "false";
    const script = ScriptBuilder.iife(`
            var m = ${this.locator};
            if (!m) return;
            var p = m.findPropertyByLabel("Freeze Simulation");
            if (p) p.setValue(${flag});
        `);
    await this.client.execute(script);
  }

  /** Bake the current simulated result onto the mesh. */
  async freeze(): Promise<void> {
    await this.setFreezeSimulation(true);
  }

  /** Release a frozen simulation so it resumes following the dForce solve. */
  async unfreeze(): Promise<void> {
    await this.setFreezeSimulation(false);
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd daz-ts && npx vitest run test/unit/modifier.test.ts`
Expected: PASS (4 tests)

- [ ] **Step 5: Add the barrel exports and commit**

```typescript
// daz-ts/src/index.ts
export { DazModifier } from "./modifier.js";
export { DazMorph } from "./morph.js";
export { DazDForce } from "./dforce.js";
```

```bash
git add daz-ts/src/modifier.ts daz-ts/src/morph.ts daz-ts/src/dforce.ts daz-ts/test/unit/modifier.test.ts daz-ts/src/index.ts
git commit -m "feat(daz-ts): port DazModifier/DazMorph/DazDForce from dazpy"
```

---

### Task 6: `DazNode` part 2 (modifiers, materials, fitting, bounding box)

**Files:**
- Modify: `daz-ts/src/node.ts` (add methods to the existing `DazNode` class from Task 3)
- Modify: `daz-ts/test/unit/node.test.ts` (add a new top-level `describe` block)

**Interfaces:**
- Consumes: `DazModifier`/`DazMorph`/`DazDForce` (Task 5), `DazMaterial` (Task 4), `DazProperty` (Task 2), `NodeNotFoundError` (Phase 1 `exceptions.ts`).
- Produces (added to `DazNode`): `modifiers(): Promise<DazModifier[]>; findModifier(name: string): Promise<DazModifier|null>; findModifierByLabel(label: string): Promise<DazModifier|null>; materials(): Promise<DazMaterial[]>; findMaterial(name: string): Promise<DazMaterial|null>; findProperty(name: string): Promise<DazProperty|null>; findPropertyByLabel(label: string): Promise<DazProperty|null>; morphs(): Promise<DazMorph[]>; dforceModifiers(): Promise<DazDForce[]>; boundingBox(): Promise<{min:{x:number;y:number;z:number};max:{x:number;y:number;z:number}}|null>; fitTo(figure: DazNode): Promise<string>; unfit(): Promise<{previousFigure: string|null; actions: string[]}>; fittedItems(): Promise<DazNode[]>; geometryVertexCount(): Promise<number|null>;` — consumed by `DazScene` (Tasks 12-14) and anywhere a caller walks a figure's modifier/material graph.

- [ ] **Step 1: Write the failing test**

```typescript
// Append to daz-ts/test/unit/node.test.ts
import { DazMorph } from "../../src/morph.js";
import { DazDForce } from "../../src/dforce.js";
import { DazModifier } from "../../src/modifier.js";
import { DazMaterial } from "../../src/material.js";

describe("DazNode modifiers/materials/fitting", () => {
  it("modifiers() dispatches DzMorph -> DazMorph, DzDForceModifier -> DazDForce, else DazModifier", async () => {
    stub([
      { name: "PHMSmile", className: "DzMorph" },
      { name: "Cloth Sim", className: "DzDForceModifier" },
      { name: "SomeConstraint", className: "DzMorphMod" },
    ]);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const mods = await node.modifiers();
    expect(mods[0]).toBeInstanceOf(DazMorph);
    expect(mods[1]).toBeInstanceOf(DazDForce);
    expect(mods[2]).toBeInstanceOf(DazModifier);
    expect(mods[2]).not.toBeInstanceOf(DazMorph);
  });

  it("materials() returns DazMaterial instances located via getCurrentShape().findMaterial()", async () => {
    stub(["Skin", "Eyes"]);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const mats = await node.materials();
    expect(mats).toHaveLength(2);
    expect(mats[0]).toBeInstanceOf(DazMaterial);
  });

  it("findModifier returns null when the server reports no match", async () => {
    stub(null);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await node.findModifier("Missing")).toBeNull();
  });

  it("fitTo raises NodeNotFoundError-style rejection when the script returns null", async () => {
    stub(null);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Shirt", kind: "name" });
    const figure = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await expect(node.fitTo(figure)).rejects.toThrow(/not found/);
  });

  it("unfit() defaults previousFigure to null and actions to [] when nothing was fitted", async () => {
    stub(null);
    const node = new DazNode(new DazClient({ token: "" }), { value: "Prop", kind: "name" });
    expect(await node.unfit()).toEqual({ previousFigure: null, actions: [] });
  });

  it("boundingBox() reads getWSBoundingBox() as {min,max}", async () => {
    const fetchMock = stub({ min: { x: 0, y: 0, z: 0 }, max: { x: 1, y: 1, z: 1 } });
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await node.boundingBox();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("_node.getWSBoundingBox()");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/node.test.ts`
Expected: FAIL — `node.modifiers is not a function`

- [ ] **Step 3: Add the imports and methods to `DazNode`**

```typescript
// daz-ts/src/node.ts — add these imports at the top, alongside the existing ones
import { DazDForce } from "./dforce.js";
import { DazMaterial } from "./material.js";
import { DazModifier } from "./modifier.js";
import { DazMorph } from "./morph.js";
import { DazProperty } from "./property.js";
import { NodeNotFoundError } from "./exceptions.js";

// ... and these methods inside the DazNode class body, after setVisibleInViewport()

  private modifierClassFor(className: string): typeof DazModifier {
    if (className === "DzMorph") return DazMorph;
    if (className === "DzDForceModifier") return DazDForce;
    return DazModifier;
  }

  private modifierLocator(modifierName: string): string {
    return (
      `(function(){` +
      ` var _o = ${this.locator};` +
      ` _o = _o ? _o.getObject() : null;` +
      ` return _o ? _o.findModifier(${ScriptBuilder.escapeString(modifierName)}) : null;` +
      `})()`
    );
  }

  /** Return all modifiers (morphs, constraints, etc.) on this node, typed via the DzMorph/DzDForceModifier dispatch table. */
  async modifiers(): Promise<DazModifier[]> {
    const items =
      ((await this.client.execute(
        this.nodeScript(`
            var obj = _node.getObject();
            if (!obj) return [];
            var mods = [];
            for (var i = 0; i < obj.getNumModifiers(); i++) {
                var m = obj.getModifier(i);
                mods.push({name: m.getName(), className: m.className()});
            }
            return mods;
            `),
      )).value as Array<{ name: string; className: string }>) ?? [];
    return items.map((item) => {
      const Cls = this.modifierClassFor(item.className);
      return new Cls(this.client, this.modifierLocator(item.name));
    });
  }

  /** Find a modifier by internal name. */
  async findModifier(name: string): Promise<DazModifier | null> {
    const result = (await this.client.execute(
      this.nodeScript(`
            var obj = _node.getObject();
            if (!obj) return null;
            var m = obj.findModifier(${ScriptBuilder.escapeString(name)});
            return m ? {name: m.getName(), className: m.className()} : null;
            `),
    )).value as { name: string; className: string } | null;
    if (result === null) return null;
    const Cls = this.modifierClassFor(result.className);
    return new Cls(this.client, this.modifierLocator(result.name));
  }

  /** Find a modifier by its user-visible label (the name shown in the DAZ UI), matching {@link findModifier}'s internal-name lookup on label instead. */
  async findModifierByLabel(label: string): Promise<DazModifier | null> {
    const result = (await this.client.execute(
      this.nodeScript(`
            var obj = _node.getObject();
            if (!obj) return null;
            for (var i = 0; i < obj.getNumModifiers(); i++) {
                var m = obj.getModifier(i);
                if (m.getLabel() === ${ScriptBuilder.escapeString(label)}) {
                    return {name: m.getName(), className: m.className()};
                }
            }
            return null;
            `),
    )).value as { name: string; className: string } | null;
    if (result === null) return null;
    const Cls = this.modifierClassFor(result.className);
    return new Cls(this.client, this.modifierLocator(result.name));
  }

  private materialLocator(materialName: string): string {
    return (
      `(function(){` +
      ` var _n = ${this.locator};` +
      ` if (!_n) return null;` +
      ` var _o = _n.getObject();` +
      ` if (!_o) return null;` +
      ` var _s = _o.getCurrentShape();` +
      ` return _s ? _s.findMaterial(${ScriptBuilder.escapeString(materialName)}) : null;` +
      `})()`
    );
  }

  /** Return all surface materials on this node's current shape. */
  async materials(): Promise<DazMaterial[]> {
    const names =
      ((await this.client.execute(
        this.nodeScript(`
            var obj = _node.getObject();
            if (!obj) return [];
            var shape = obj.getCurrentShape();
            if (!shape) return [];
            var names = [];
            for (var i = 0; i < shape.getNumMaterials(); i++) {
                names.push(shape.getMaterial(i).getName());
            }
            return names;
            `),
      )).value as string[]) ?? [];
    return names.map((n) => new DazMaterial(this.client, this.materialLocator(n)));
  }

  /** Find a surface material by name. */
  async findMaterial(name: string): Promise<DazMaterial | null> {
    const result = (await this.client.execute(
      this.nodeScript(`
            var obj = _node.getObject();
            if (!obj) return null;
            var shape = obj.getCurrentShape();
            if (!shape) return null;
            var m = shape.findMaterial(${ScriptBuilder.escapeString(name)});
            return m ? m.getName() : null;
            `),
    )).value as string | null;
    if (result === null) return null;
    return new DazMaterial(this.client, this.materialLocator(result));
  }

  /**
   * Find a node-level property by internal name via `DzNode::findProperty` —
   * covers pose controls/FACS dials that are not geometry modifiers and so
   * are invisible to {@link findModifier}.
   */
  async findProperty(name: string): Promise<DazProperty | null> {
    const locator = `(function(){var _n=${this.locator};return _n ? _n.findProperty(${ScriptBuilder.escapeString(
      name,
    )}) : null;})()`;
    const exists = (await this.client.execute(ScriptBuilder.iife(`return !!(${locator});`))).value;
    if (!exists) return null;
    return DazProperty.fromLocator(this.client, locator);
  }

  /** Like {@link findProperty} but matches `getLabel()` instead of `getName()`. */
  async findPropertyByLabel(label: string): Promise<DazProperty | null> {
    const locator = `(function(){var _n=${this.locator};return _n ? _n.findPropertyByLabel(${ScriptBuilder.escapeString(
      label,
    )}) : null;})()`;
    const exists = (await this.client.execute(ScriptBuilder.iife(`return !!(${locator});`))).value;
    if (!exists) return null;
    return DazProperty.fromLocator(this.client, locator);
  }

  /** Only the morph modifiers on this node (convenience filter over {@link modifiers}). */
  async morphs(): Promise<DazMorph[]> {
    return (await this.modifiers()).filter((m): m is DazMorph => m instanceof DazMorph);
  }

  /** Only the dForce simulation modifiers on this node (convenience filter over {@link modifiers}). */
  async dforceModifiers(): Promise<DazDForce[]> {
    return (await this.modifiers()).filter((m): m is DazDForce => m instanceof DazDForce);
  }

  /** World-space axis-aligned bounding box, or `null` if the node has no geometry. */
  async boundingBox(): Promise<{ min: { x: number; y: number; z: number }; max: { x: number; y: number; z: number } } | null> {
    const script = this.nodeScript(
      "var bb = _node.getWSBoundingBox(); return {min: {x: bb.min.x, y: bb.min.y, z: bb.min.z}, max: {x: bb.max.x, y: bb.max.y, z: bb.max.z}};",
    );
    return (await this.client.execute(script)).value as {
      min: { x: number; y: number; z: number };
      max: { x: number; y: number; z: number };
    } | null;
  }

  /**
   * Fit this clothing/hair/prop node to a base figure, preferring
   * `setFollowTarget`/`followSkeleton` (conforming items) and falling back
   * to parenting (plain props). @returns which DazScript API was used.
   */
  async fitTo(figure: DazNode): Promise<string> {
    const figureExpr = ScriptBuilder.findNodeExpr(figure.identifier);
    const result = (await this.client.execute(
      this.nodeScript(`
            var _figure = ${figureExpr};
            if (!_figure) return null;
            var _method;
            if (typeof _node.setFollowTarget === 'function') {
                _node.setFollowTarget(_figure);
                _method = "setFollowTarget";
            } else if (typeof _node.followSkeleton === 'function') {
                _node.followSkeleton(_figure);
                _method = "followSkeleton";
            } else {
                _figure.addNodeChild(_node, true);
                _method = "addNodeChild";
            }
            return _method;
            `),
    )).value as string | null;
    if (result === null) {
      throw new NodeNotFoundError("Could not fit node to figure: one of the nodes was not found.");
    }
    return result;
  }

  /** Remove this node's fitting relationship with its figure (follow-target and/or skeleton parenting). */
  async unfit(): Promise<{ previousFigure: string | null; actions: string[] }> {
    const script = this.nodeScript(`
            var _prevFigure = null;
            var _actions = [];
            if (typeof _node.getFollowTarget === 'function') {
                var _ft = _node.getFollowTarget();
                if (_ft) {
                    _prevFigure = _ft.getName();
                    if (typeof _node.setFollowTarget === 'function') {
                        _node.setFollowTarget(null);
                        _actions.push("cleared follow target");
                    }
                }
            }
            var _parent = _node.getNodeParent();
            if (_parent && _parent.inherits && _parent.inherits("DzSkeleton")) {
                _prevFigure = _prevFigure || _parent.getName();
                _parent.removeNodeChild(_node, true);
                _actions.push("detached from parent");
            }
            return {previous_figure: _prevFigure, actions: _actions};
        `);
    const result = (await this.client.execute(script)).value as
      | { previous_figure: string | null; actions: string[] }
      | null;
    return { previousFigure: result?.previous_figure ?? null, actions: result?.actions ?? [] };
  }

  /** Every clothing/hair/prop node fitted to this figure (following it, or directly parented to it). */
  async fittedItems(): Promise<DazNode[]> {
    const names =
      ((await this.client.execute(
        this.nodeScript(`
            var _fitted = [];
            var _numNodes = Scene.getNumNodes();
            for (var i = 0; i < _numNodes; i++) {
                var _n = Scene.getNode(i);
                if (!_n || _n === _node) continue;
                var _isFitted = false;
                if (typeof _n.getFollowTarget === 'function') {
                    var _ft = _n.getFollowTarget();
                    if (_ft && _ft.elementID === _node.elementID) _isFitted = true;
                }
                if (!_isFitted && typeof _n.getNodeParent === 'function') {
                    var _p = _n.getNodeParent();
                    if (_p && _p.elementID === _node.elementID) _isFitted = true;
                }
                if (_isFitted) _fitted.push(_n.getName());
            }
            return _fitted;
            `),
      )).value as string[]) ?? [];
    return names.map((n) => new DazNode(this.client, { value: n, kind: "name" }));
  }

  /** Total vertex count of this node's current geometry, or `null`. */
  async geometryVertexCount(): Promise<number | null> {
    const script = this.nodeScript(`
            var obj = _node.getObject();
            if (!obj) return null;
            var shape = obj.getCurrentShape();
            if (!shape) return null;
            var geo = shape.getGeometry();
            if (!geo) return null;
            return geo.getNumVertices();
        `);
    return (await this.client.execute(script)).value as number | null;
  }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd daz-ts && npx vitest run test/unit/node.test.ts`
Expected: PASS (15 tests total)

- [ ] **Step 5: Commit**

```bash
git add daz-ts/src/node.ts daz-ts/test/unit/node.test.ts
git commit -m "feat(daz-ts): add DazNode modifier/material/fitting methods"
```

---

### Task 7: `DazBone`

**Files:**
- Create: `daz-ts/src/bone.ts`
- Test: `daz-ts/test/unit/bone.test.ts`
- Modify: `daz-ts/src/index.ts` (add `export { DazBone } from "./bone.js";`)

**Interfaces:**
- Consumes: `DazNode`/`NodeIdentifier` (Task 3/6), `DazElement` (Task 1).
- Produces: `class DazBone extends DazNode { static fromLocator(client: DazClient, locator: string, name: string): DazBone; localEuler(): Promise<[number,number,number]|null>; localRotation(): Promise<{x:number;y:number;z:number;w:number}|null>; setLocalRotation(x:number,y:number,z:number): Promise<void>; localPosition(): Promise<{x:number;y:number;z:number}|null>; rotationOrder(): Promise<string|null>; getSkeleton(): Promise<DazSkeleton|null>; }` — `DazBone.fromLocator` is consumed by `DazSkeleton.bones()`/`.findBone()`/`.findBoneByLabel()` in Task 10.

- [ ] **Step 1: Write the failing test**

```typescript
import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazBone } from "../../src/bone.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}
afterEach(() => vi.unstubAllGlobals());
function stub(value: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ success: true, result: value, output: [], request_id: "r", duration_ms: 0 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("DazBone", () => {
  it("fromLocator wraps a pre-built skeleton-relative locator and keeps its name as identifier", async () => {
    stub([10, 20, 30]);
    const bone = DazBone.fromLocator(new DazClient({ token: "" }), "BONELOC", "r_forearm");
    expect(bone.identifier).toEqual({ value: "r_forearm", kind: "name" });
    await bone.localEuler();
  });

  it("localEuler reads the three rotation controls via a node-body-from-locator wrapper", async () => {
    const fetchMock = stub([1, 2, 3]);
    const bone = DazBone.fromLocator(new DazClient({ token: "" }), "BONELOC", "r_forearm");
    expect(await bone.localEuler()).toEqual([1, 2, 3]);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe(
      "(function(){\nvar _node = BONELOC;\nif (!_node) return null;\n" +
      "return [_node.getXRotControl().getValue(), _node.getYRotControl().getValue(), _node.getZRotControl().getValue()];\n})()",
    );
  });

  it("setLocalRotation writes all three rotation controls", async () => {
    const fetchMock = stub(null);
    const bone = DazBone.fromLocator(new DazClient({ token: "" }), "BONELOC", "r_forearm");
    await bone.setLocalRotation(1, 2, 3);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("_node.getXRotControl().setValue(1)");
    expect(script).toContain("_node.getZRotControl().setValue(3)");
  });

  it("getSkeleton returns null when getSkeleton() resolves to nothing", async () => {
    stub(null);
    const bone = DazBone.fromLocator(new DazClient({ token: "" }), "BONELOC", "r_forearm");
    expect(await bone.getSkeleton()).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/bone.test.ts`
Expected: FAIL with "Cannot find module '../../src/bone.js'"

- [ ] **Step 3: Implement `DazBone`**

```typescript
import type { DazClient } from "./client.js";
import { DazElement } from "./element.js";
import { DazNode, type NodeIdentifier } from "./node.js";
import { ScriptBuilder } from "./scriptBuilder.js";

/** Proxy for a `DzBone` (a single joint within a {@link DazSkeleton}). Extends `DazNode` with bone-specific rotation helpers. */
export class DazBone extends DazNode {
  /** Construct a `DazBone` from a pre-built skeleton-relative locator (see `DazSkeleton`'s bone lookup). */
  static fromLocator(client: DazClient, locator: string, name: string): DazBone {
    const bone = Object.create(DazBone.prototype) as DazBone;
    DazElement.call(bone as unknown as DazElement, client, locator);
    Object.assign(bone, { identifier: { value: name, kind: "name" } satisfies NodeIdentifier });
    return bone;
  }

  private nb(body: string): string {
    return ScriptBuilder.nodeBodyFromLocator(this.locator, body);
  }

  /** Local-space rotation as `(x, y, z)` Euler degrees; exact inverse of {@link setLocalRotation}. */
  async localEuler(): Promise<[number, number, number] | null> {
    const result = (await this.client.execute(
      this.nb(
        "return [_node.getXRotControl().getValue(), _node.getYRotControl().getValue(), _node.getZRotControl().getValue()];",
      ),
    )).value as number[] | null;
    if (result === null) return null;
    return [result[0], result[1], result[2]];
  }

  /** Local-space rotation as `{x, y, z, w}` quaternion (read-only). */
  async localRotation(): Promise<{ x: number; y: number; z: number; w: number } | null> {
    return (await this.client.execute(this.nb("var r = _node.getLocalRot(); return {x: r.x, y: r.y, z: r.z, w: r.w};")))
      .value as { x: number; y: number; z: number; w: number } | null;
  }

  async setLocalRotation(x: number, y: number, z: number): Promise<void> {
    await this.client.execute(
      this.nb(
        `_node.getXRotControl().setValue(${x}); _node.getYRotControl().setValue(${y}); _node.getZRotControl().setValue(${z});`,
      ),
    );
  }

  /** Local-space position as `{x, y, z}` (read-only). */
  async localPosition(): Promise<{ x: number; y: number; z: number } | null> {
    return (await this.client.execute(this.nb("var p = _node.getLocalPos(); return {x: p.x, y: p.y, z: p.z};"))).value as
      | { x: number; y: number; z: number }
      | null;
  }

  /** Rotation order string (e.g. `"XYZ"`), or `null`. */
  async rotationOrder(): Promise<string | null> {
    return (await this.client.execute(this.nb("return _node.getRotationOrder();"))).value as string | null;
  }

  /** The parent skeleton, or `null`. */
  async getSkeleton(): Promise<import("./skeleton.js").DazSkeleton | null> {
    const { DazSkeleton } = await import("./skeleton.js");
    const name = (await this.client.execute(this.nb("var s = _node.getSkeleton(); return s ? s.getName() : null;")))
      .value as string | null;
    if (name === null) return null;
    return new DazSkeleton(this.client, { value: name, kind: "name" });
  }
}
```

Note: `getSkeleton()` uses a dynamic `import("./skeleton.js")` (not a static top-level import) purely to break the `bone.ts` ↔ `skeleton.ts` circular reference (`DazSkeleton.bones()` constructs `DazBone`s; `DazBone.getSkeleton()` constructs a `DazSkeleton`) — mirrors dazpy's own lazy `from ._skeleton import DazSkeleton` inside the method.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd daz-ts && npx vitest run test/unit/bone.test.ts`
Expected: PASS (4 tests)

- [ ] **Step 5: Add the barrel export and commit**

```typescript
// daz-ts/src/index.ts
export { DazBone } from "./bone.js";
```

```bash
git add daz-ts/src/bone.ts daz-ts/test/unit/bone.test.ts daz-ts/src/index.ts
git commit -m "feat(daz-ts): port DazBone from dazpy _bone.py"
```

---

### Task 8: `DazCamera`

**Files:**
- Create: `daz-ts/src/camera.ts`
- Test: `daz-ts/test/unit/camera.test.ts`
- Modify: `daz-ts/src/index.ts` (add `export { DazCamera } from "./camera.js";`)

**Interfaces:**
- Consumes: `DazNode` (Task 3/6).
- Produces: `class DazCamera extends DazNode { focalLength(): Promise<number|null>; setFocalLength(v:number): Promise<void>; fov(): Promise<number|null>; depthOfField(): Promise<boolean|null>; setDepthOfField(v:boolean): Promise<void>; lensShiftX(): Promise<number|null>; setLensShiftX(v:number): Promise<void>; lensShiftY(): Promise<number|null>; setLensShiftY(v:number): Promise<void>; fStop(): Promise<number|null>; setFStop(v:number): Promise<void>; apertureBlades(): Promise<number|null>; setApertureBlades(v:number): Promise<void>; apertureBladeRotation(): Promise<number|null>; setApertureBladeRotation(v:number): Promise<void>; frameWidth(): Promise<number|null>; focalDistance(): Promise<number|null>; setFocalDistance(v:number): Promise<void>; aspectWidth(): Promise<number|null>; setAspectWidth(v:number): Promise<void>; aspectHeight(): Promise<number|null>; setAspectHeight(v:number): Promise<void>; pixelsWidth(): Promise<number|null>; setPixelsWidth(v:number): Promise<void>; pixelsHeight(): Promise<number|null>; setPixelsHeight(v:number): Promise<void>; nearClippingPlane(): Promise<number|null>; farClippingPlane(): Promise<number|null>; aimAt(x:number,y:number,z:number): Promise<void>; focalPoint(): Promise<{x:number;y:number;z:number}|null>; isViewCamera(): Promise<boolean|null>; }` — consumed by `DazScene.cameras()`/`.createCamera()`/`.findCameraByLabel()` in Task 12.

- [ ] **Step 1: Write the failing test**

```typescript
import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazCamera } from "../../src/camera.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}
afterEach(() => vi.unstubAllGlobals());
function stub(value: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ success: true, result: value, output: [], request_id: "r", duration_ms: 0 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("DazCamera", () => {
  it("focalLength getter/setter round-trip the .focalLength property directly (not findPropertyByLabel)", async () => {
    const fetchMock = stub(null);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.setFocalLength(50);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("_node.focalLength = 50;");
  });

  it("depthOfField/lensShiftX/fStop/apertureBlades go through getProperty/setProperty by label", async () => {
    const fetchMock = stub(true);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    expect(await cam.depthOfField()).toBe(true);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain('findPropertyByLabel("Depth of Field")');
  });

  it("aimAt writes a new DzVec3 argument", async () => {
    const fetchMock = stub(null);
    const cam = new DazCamera(new DazClient({ token: "" }), { value: "Camera", kind: "name" });
    await cam.aimAt(1, 2, 3);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("_node.aimAt(new DzVec3(1, 2, 3));");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/camera.test.ts`
Expected: FAIL with "Cannot find module '../../src/camera.js'"

- [ ] **Step 3: Implement `DazCamera`**

```typescript
import { DazNode } from "./node.js";
import { ScriptBuilder } from "./scriptBuilder.js";

/** Proxy for a `DzCamera` node. Extends `DazNode` with optical and image-sensor properties. */
export class DazCamera extends DazNode {
  /** Focal length in millimetres (read/write, direct `.focalLength` field access). */
  async focalLength(): Promise<number | null> {
    return (await this.client.execute(this.nodeScript("return _node.focalLength;"))).value as number | null;
  }
  async setFocalLength(value: number): Promise<void> {
    await this.client.execute(this.nodeScript(`_node.focalLength = ${value};`));
  }

  /** Field of view in degrees (read-only; derived from focal length). */
  async fov(): Promise<number | null> {
    return (await this.client.execute(this.nodeScript("return _node.getFieldOfView();"))).value as number | null;
  }

  async depthOfField(): Promise<boolean | null> {
    return (await this.getProperty("Depth of Field")) as boolean | null;
  }
  async setDepthOfField(value: boolean): Promise<void> {
    await this.setProperty("Depth of Field", value);
  }

  /** Horizontal lens shift in millimetres (read/write) — matches the render engine's own value, needed for depth-based effects. */
  async lensShiftX(): Promise<number | null> {
    return (await this.getProperty("Lens Shift X (mm)")) as number | null;
  }
  async setLensShiftX(value: number): Promise<void> {
    await this.setProperty("Lens Shift X (mm)", value);
  }

  /** Vertical lens shift in millimetres (read/write). See {@link lensShiftX}. */
  async lensShiftY(): Promise<number | null> {
    return (await this.getProperty("Lens Shift Y (mm)")) as number | null;
  }
  async setLensShiftY(value: number): Promise<void> {
    await this.setProperty("Lens Shift Y (mm)", value);
  }

  /** Aperture/f-stop — controls depth-of-field blur intensity (read/write); only affects render when {@link depthOfField} is on. */
  async fStop(): Promise<number | null> {
    return (await this.getProperty("F/Stop")) as number | null;
  }
  async setFStop(value: number): Promise<void> {
    await this.setProperty("F/Stop", value);
  }

  /** Bokeh blade count (read/write); `0` = circular bokeh, 3+ = polygonal. */
  async apertureBlades(): Promise<number | null> {
    return (await this.getProperty("Aperture Blades")) as number | null;
  }
  async setApertureBlades(value: number): Promise<void> {
    await this.setProperty("Aperture Blades", Math.trunc(value));
  }

  /** Bokeh polygon rotation angle in degrees (read/write); visible only when {@link apertureBlades} >= 3. */
  async apertureBladeRotation(): Promise<number | null> {
    return (await this.getProperty("Aperture Blade Rotation")) as number | null;
  }
  async setApertureBladeRotation(value: number): Promise<void> {
    await this.setProperty("Aperture Blade Rotation", value);
  }

  /** Sensor/film-gate width in millimetres (read-only). */
  async frameWidth(): Promise<number | null> {
    return (await this.client.execute(this.nodeScript("return _node.frameWidth;"))).value as number | null;
  }

  /** Distance to the focus plane (read/write). */
  async focalDistance(): Promise<number | null> {
    return (await this.client.execute(this.nodeScript("return _node.focalDistance;"))).value as number | null;
  }
  async setFocalDistance(value: number): Promise<void> {
    await this.client.execute(this.nodeScript(`_node.focalDistance = ${value};`));
  }

  async aspectWidth(): Promise<number | null> {
    return (await this.client.execute(this.nodeScript("return _node.aspectWidth;"))).value as number | null;
  }
  async setAspectWidth(value: number): Promise<void> {
    await this.client.execute(this.nodeScript(`_node.aspectWidth = ${value};`));
  }

  async aspectHeight(): Promise<number | null> {
    return (await this.client.execute(this.nodeScript("return _node.aspectHeight;"))).value as number | null;
  }
  async setAspectHeight(value: number): Promise<void> {
    await this.client.execute(this.nodeScript(`_node.aspectHeight = ${value};`));
  }

  async pixelsWidth(): Promise<number | null> {
    return (await this.client.execute(this.nodeScript("return _node.pixelsWidth;"))).value as number | null;
  }
  async setPixelsWidth(value: number): Promise<void> {
    await this.client.execute(this.nodeScript(`_node.pixelsWidth = ${Math.trunc(value)};`));
  }

  async pixelsHeight(): Promise<number | null> {
    return (await this.client.execute(this.nodeScript("return _node.pixelsHeight;"))).value as number | null;
  }
  async setPixelsHeight(value: number): Promise<void> {
    await this.client.execute(this.nodeScript(`_node.pixelsHeight = ${Math.trunc(value)};`));
  }

  async nearClippingPlane(): Promise<number | null> {
    return (await this.client.execute(this.nodeScript("return _node.nearClippingPlane;"))).value as number | null;
  }

  async farClippingPlane(): Promise<number | null> {
    return (await this.client.execute(this.nodeScript("return _node.farClippingPlane;"))).value as number | null;
  }

  /** Point the camera at a world-space coordinate. */
  async aimAt(x: number, y: number, z: number): Promise<void> {
    await this.client.execute(this.nodeScript(`_node.aimAt(new DzVec3(${x}, ${y}, ${z}));`));
  }

  /** World-space focal point as `{x, y, z}`. */
  async focalPoint(): Promise<{ x: number; y: number; z: number } | null> {
    return (
      await this.client.execute(this.nodeScript("var fp = _node.getFocalPoint(); return {x: fp.x, y: fp.y, z: fp.z};"))
    ).value as { x: number; y: number; z: number } | null;
  }

  /** `true` if this is the active viewport camera. */
  async isViewCamera(): Promise<boolean | null> {
    return (await this.client.execute(this.nodeScript("return _node.isViewCamera();"))).value as boolean | null;
  }
}
```

`ScriptBuilder` is imported for consistency with sibling files even though this file only calls inherited `nodeScript`/`getProperty`/`setProperty` — drop the unused import if the linter flags it.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd daz-ts && npx vitest run test/unit/camera.test.ts`
Expected: PASS (3 tests)

- [ ] **Step 5: Add the barrel export and commit**

```typescript
// daz-ts/src/index.ts
export { DazCamera } from "./camera.js";
```

```bash
git add daz-ts/src/camera.ts daz-ts/test/unit/camera.test.ts daz-ts/src/index.ts
git commit -m "feat(daz-ts): port DazCamera from dazpy _camera.py"
```

---

### Task 9: `DazLight`

**Files:**
- Create: `daz-ts/src/light.ts`
- Test: `daz-ts/test/unit/light.test.ts`
- Modify: `daz-ts/src/index.ts` (add `export { DazLight } from "./light.js";`)

**Interfaces:**
- Consumes: `DazNode` (Task 3/6).
- Produces: `class DazLight extends DazNode { intensity(): Promise<number|null>; setIntensity(v:number): Promise<void>; color(): Promise<{r:number;g:number;b:number}|null>; setColor(r:number,g:number,b:number): Promise<void>; shadowType(): Promise<string|null>; illumination(): Promise<string|null>; isOn(): Promise<boolean>; isDirectional(): Promise<boolean>; isAreaLight(): Promise<boolean>; direction(): Promise<{x:number;y:number;z:number}|null>; }` — consumed by `DazScene.lights()`/`.createLight()`/`.findLightByLabel()` in Task 12.

- [ ] **Step 1: Write the failing test**

```typescript
import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazLight } from "../../src/light.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}
afterEach(() => vi.unstubAllGlobals());
function stub(value: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ success: true, result: value, output: [], request_id: "r", duration_ms: 0 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("DazLight", () => {
  it("intensity getter/setter go through getProperty/setProperty(\"Intensity\")", async () => {
    const fetchMock = stub(100);
    const light = new DazLight(new DazClient({ token: "" }), { value: "Spotlight1", kind: "name" });
    expect(await light.intensity()).toBe(100);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain('findPropertyByLabel("Intensity")');
  });

  it("color() reads {r,g,b} from getDiffuseColor()", async () => {
    const fetchMock = stub({ r: 255, g: 255, b: 200 });
    const light = new DazLight(new DazClient({ token: "" }), { value: "Spotlight1", kind: "name" });
    expect(await light.color()).toEqual({ r: 255, g: 255, b: 200 });
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("_node.getDiffuseColor()");
  });

  it("setColor finds the 'Color' property by label and calls setColorValue", async () => {
    const fetchMock = stub(null);
    const light = new DazLight(new DazClient({ token: "" }), { value: "Spotlight1", kind: "name" });
    await light.setColor(1, 2, 3);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("findPropertyByLabel('Color')");
    expect(script).toContain("new Color(1, 2, 3)");
  });

  it("direction() returns null when the light is not directional", async () => {
    stub(null);
    const light = new DazLight(new DazClient({ token: "" }), { value: "PointLight1", kind: "name" });
    expect(await light.direction()).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/light.test.ts`
Expected: FAIL with "Cannot find module '../../src/light.js'"

- [ ] **Step 3: Implement `DazLight`**

```typescript
import { DazNode } from "./node.js";

/** Proxy for a `DzLight` node. Extends `DazNode` with light-specific properties. */
export class DazLight extends DazNode {
  async intensity(): Promise<number | null> {
    return (await this.getProperty("Intensity")) as number | null;
  }
  async setIntensity(value: number): Promise<void> {
    await this.setProperty("Intensity", value);
  }

  /** Diffuse colour as `{r, g, b}` (0-255, read-only; use {@link setColor} to change). */
  async color(): Promise<{ r: number; g: number; b: number } | null> {
    const script = this.nodeScript(`
            var c = _node.getDiffuseColor();
            return {r: c.red, g: c.green, b: c.blue};
        `);
    return (await this.client.execute(script)).value as { r: number; g: number; b: number } | null;
  }

  async setColor(r: number, g: number, b: number): Promise<void> {
    const script = this.nodeScript(
      `var p = _node.findPropertyByLabel('Color'); if (p) p.setColorValue(new Color(${Math.trunc(r)}, ${Math.trunc(
        g,
      )}, ${Math.trunc(b)}));`,
    );
    await this.client.execute(script);
  }

  async shadowType(): Promise<string | null> {
    return (await this.getProperty("Shadow Type")) as string | null;
  }

  async illumination(): Promise<string | null> {
    return (await this.getProperty("Illumination")) as string | null;
  }

  async isOn(): Promise<boolean> {
    return Boolean((await this.client.execute(this.nodeScript("return _node.isOn();"))).value);
  }

  async isDirectional(): Promise<boolean> {
    return Boolean((await this.client.execute(this.nodeScript("return _node.isDirectional();"))).value);
  }

  async isAreaLight(): Promise<boolean> {
    return Boolean((await this.client.execute(this.nodeScript("return _node.isAreaLight();"))).value);
  }

  /** World-space direction vector `{x, y, z}`, or `null` when the light is not directional. */
  async direction(): Promise<{ x: number; y: number; z: number } | null> {
    const script = this.nodeScript(
      "if (!_node.isDirectional()) return null; var d = _node.getWSDirection(); return {x: d.x, y: d.y, z: d.z};",
    );
    return (await this.client.execute(script)).value as { x: number; y: number; z: number } | null;
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd daz-ts && npx vitest run test/unit/light.test.ts`
Expected: PASS (4 tests)

- [ ] **Step 5: Add the barrel export and commit**

```typescript
// daz-ts/src/index.ts
export { DazLight } from "./light.js";
```

```bash
git add daz-ts/src/light.ts daz-ts/test/unit/light.test.ts daz-ts/src/index.ts
git commit -m "feat(daz-ts): port DazLight from dazpy _light.py"
```

---

### Task 10: `DazSkeleton` part 1 (bone lookup, bulk bone/morph state)

**Files:**
- Create: `daz-ts/src/skeleton.ts`
- Test: `daz-ts/test/unit/skeleton.test.ts`
- Modify: `daz-ts/src/index.ts` (add `export { DazSkeleton } from "./skeleton.js";`)

**Interfaces:**
- Consumes: `DazNode`/`NodeIdentifier` (Task 3/6), `DazBone` (Task 7), `NodeNotFoundError` (Phase 1 `exceptions.ts`), `ScriptBuilder.skeletonLookup` (Task 3).
- Produces: `class DazSkeleton extends DazNode { bones(): Promise<DazBone[]>; boneMetadata(): Promise<Array<Record<string, unknown>>>; findBone(name: string): Promise<DazBone>; findBoneByLabel(label: string): Promise<DazBone>; numBones(): Promise<number>; boneRotations(): Promise<Record<string,[number,number,number]>>; boneRotationsQuat(): Promise<Record<string,{x:number;y:number;z:number;w:number}>>; setBoneRotations(data: Record<string,[number,number,number]>): Promise<void>; setState(opts:{bones?:Record<string,[number,number,number]>;morphs?:Record<string,number>;props?:Record<string,unknown>}): Promise<void>; morphValues(nonzeroOnly?: boolean): Promise<Record<string,number>>; setMorphValues(data: Record<string,number>): Promise<void>; }` (part 1 methods only) — this is the same class Task 11 adds pose-evaluation/baking methods to.

- [ ] **Step 1: Write the failing test**

```typescript
import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazSkeleton } from "../../src/skeleton.js";
import { DazBone } from "../../src/bone.js";
import { NodeNotFoundError } from "../../src/exceptions.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}
afterEach(() => vi.unstubAllGlobals());
function stub(value: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ success: true, result: value, output: [], request_id: "r", duration_ms: 0 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("DazSkeleton bones", () => {
  it("bones() looks up the skeleton via getSkeletonList(), not Scene.findNode()", async () => {
    const fetchMock = stub(["hip", "chest"]);
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const bones = await skel.bones();
    expect(bones).toHaveLength(2);
    expect(bones[0]).toBeInstanceOf(DazBone);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("Scene.getSkeletonList()");
    expect(script).not.toContain("Scene.findNode(");
  });

  it("findBone rejects with NodeNotFoundError including a naming-convention hint", async () => {
    stub(null);
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await expect(skel.findBone("bogus")).rejects.toBeInstanceOf(NodeNotFoundError);
    await expect(skel.findBone("bogus")).rejects.toThrow(/Genesis 9 uses/);
  });

  it("setBoneRotations writes only the named bones' rotation controls", async () => {
    const fetchMock = stub(null);
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await skel.setBoneRotations({ r_forearm: [10, 0, 0] });
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain('{"r_forearm":[10,0,0]}');
  });

  it("morphValues(true) filters to |value| > 0.0001", async () => {
    const fetchMock = stub({ SmileFull: 0.8 });
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await skel.morphValues(true);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("var _nz = true;");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/skeleton.test.ts`
Expected: FAIL with "Cannot find module '../../src/skeleton.js'"

- [ ] **Step 3: Add `ScriptBuilder.skeletonLookupAsNode` and implement `DazSkeleton` part 1**

`ScriptBuilder.skeletonLookup` (Task 3) binds the found skeleton to `_skel`, but every `DazSkeleton` method below (mirroring dazpy's `_skeleton_body`) needs it bound to `_node` so the shared node-style body reads consistently. Add a second `ScriptBuilder` static, alongside `skeletonLookup`:

```typescript
// Add to daz-ts/src/scriptBuilder.ts, alongside skeletonLookup
  /** Like {@link skeletonLookup} but binds the result to `_node` instead of `_skel`, for callers using the shared `_node`-based body convention. */
  static skeletonLookupAsNode(identifier: NodeIdentifier): string {
    const value = ScriptBuilder.escapeString(identifier.value);
    const match =
      identifier.kind === "label" ? `_skels[_i].getLabel() === ${value}` : `_skels[_i].getName() === ${value}`;
    return (
      `var _node=null,_skels=Scene.getSkeletonList();` +
      `for(var _i=0;_i<_skels.length;_i++){` +
      `if(${match}){_node=_skels[_i];break;}}`
    );
  }
```

Add one test case to `test/unit/scriptBuilder.test.ts` for it (same shape as the `skeletonLookup` cases in Task 3, asserting `_node=null` and `_node=_skels[_i]` instead of `_skel`).

Then implement `DazSkeleton`:

```typescript
import type { DazClient } from "./client.js";
import { DazBone } from "./bone.js";
import { NodeNotFoundError } from "./exceptions.js";
import { DazNode } from "./node.js";
import { ScriptBuilder } from "./scriptBuilder.js";

/** Proxy for a `DzSkeleton` (a rigged figure such as Genesis 9). Extends `DazNode` with bone-access helpers. */
export class DazSkeleton extends DazNode {
  /**
   * Wrap `body` in an IIFE that resolves this skeleton via
   * `Scene.getSkeletonList()` (bound to `_node`), not `Scene.findNode()` —
   * `findNode()` returns a plain `DzNode` lacking `DzSkeleton` methods like
   * `findBone()`.
   */
  private skeletonScript(body: string): string {
    return ScriptBuilder.iife(`${ScriptBuilder.skeletonLookupAsNode(this.identifier)}\nif (!_node) return null;\n${body}`);
  }

  /** Build a locator that resolves a bone through this specific skeleton (keeps same-named figures distinct). */
  private boneLocator(boneName: string): string {
    const lookup = ScriptBuilder.skeletonLookup(this.identifier);
    return `(function(){${lookup}return _skel?_skel.findBone(${ScriptBuilder.escapeString(boneName)}):null;})()`;
  }

  /** Return all bones in this skeleton. */
  async bones(): Promise<DazBone[]> {
    const names =
      ((await this.client.execute(
        this.skeletonScript(
          "var bones = _node.getAllBones(); var names = []; for (var i = 0; i < bones.length; i++) { names.push(bones[i].getName()); } return names;",
        ),
      )).value as string[]) ?? [];
    return names.map((n) => DazBone.fromLocator(this.client, this.boneLocator(n), n));
  }

  /** Bulk metadata for every bone in one HTTP call (name/label/parentName/rotationOrder/localPosition/worldPosition/localEuler). */
  async boneMetadata(): Promise<Array<Record<string, unknown>>> {
    const script = this.skeletonScript(`
            var bones = _node.getAllBones();
            var result = [];
            for (var i = 0; i < bones.length; i++) {
                var b = bones[i];
                var parent = b.getNodeParent();
                var parent_name = null;
                if (parent && parent.className && parent.className() === "DzBone") {
                    parent_name = parent.getName();
                }
                var pos = b.getLocalPos();
                var wpos = b.getWSPos();
                result.push({
                    name: b.getName(),
                    label: b.getLabel(),
                    parent_name: parent_name,
                    rotation_order: b.getRotationOrder(),
                    local_position: {x: pos.x, y: pos.y, z: pos.z},
                    world_position: {x: wpos.x, y: wpos.y, z: wpos.z},
                    local_euler: {
                        x: b.getXRotControl().getValue(),
                        y: b.getYRotControl().getValue(),
                        z: b.getZRotControl().getValue()
                    }
                });
            }
            return result;
        `);
    return ((await this.client.execute(script)).value as Array<Record<string, unknown>>) ?? [];
  }

  /** Find a bone by internal name (naming conventions differ by figure generation — see {@link bones}). */
  async findBone(name: string): Promise<DazBone> {
    const script = this.skeletonScript(
      `var b = _node.findBone(${ScriptBuilder.escapeString(name)}); return b ? b.getName() : null;`,
    );
    const result = (await this.client.execute(script)).value as string | null;
    if (result === null) {
      throw new NodeNotFoundError(
        `Bone not found: ${JSON.stringify(name)}. ` +
          `Bone naming differs by figure generation — e.g. Genesis 9 uses ` +
          `'r_forearm', Genesis 3/8 uses 'rForearmBend', Genesis 1/2 uses 'rForeArm'. ` +
          `Call figure.bones() to list every bone name for this figure.`,
      );
    }
    return DazBone.fromLocator(this.client, this.boneLocator(result), result);
  }

  /** Find a bone by its user-visible label. */
  async findBoneByLabel(label: string): Promise<DazBone> {
    const script = this.skeletonScript(
      `var b = _node.findBoneByLabel(${ScriptBuilder.escapeString(label)}); return b ? b.getName() : null;`,
    );
    const result = (await this.client.execute(script)).value as string | null;
    if (result === null) {
      throw new NodeNotFoundError(`Bone with label not found: ${JSON.stringify(label)}`);
    }
    return DazBone.fromLocator(this.client, this.boneLocator(result), result);
  }

  async numBones(): Promise<number> {
    return ((await this.client.execute(this.skeletonScript("return _node.getAllBones().length;"))).value as number) ?? 0;
  }

  /** Euler rotations (degrees) for every bone in one HTTP call. */
  async boneRotations(): Promise<Record<string, [number, number, number]>> {
    const script = this.skeletonScript(`
            var _bones = _node.getAllBones();
            var _result = {};
            for (var i = 0; i < _bones.length; i++) {
                var _b = _bones[i];
                _result[_b.getName()] = [
                    _b.getXRotControl().getValue(),
                    _b.getYRotControl().getValue(),
                    _b.getZRotControl().getValue()
                ];
            }
            return _result;
        `);
    const raw = ((await this.client.execute(script)).value as Record<string, number[]>) ?? {};
    const out: Record<string, [number, number, number]> = {};
    for (const [name, v] of Object.entries(raw)) {
      out[name] = [v[0], v[1], v[2]];
    }
    return out;
  }

  /** Local-space quaternion rotations for every bone in one HTTP call — avoids per-bone Euler rotation-order ambiguity. */
  async boneRotationsQuat(): Promise<Record<string, { x: number; y: number; z: number; w: number }>> {
    const script = this.skeletonScript(`
            var _bones = _node.getAllBones();
            var _result = {};
            for (var i = 0; i < _bones.length; i++) {
                var _b = _bones[i];
                var _r = _b.getLocalRot();
                _result[_b.getName()] = {x: _r.x, y: _r.y, z: _r.z, w: _r.w};
            }
            return _result;
        `);
    return ((await this.client.execute(script)).value as Record<string, { x: number; y: number; z: number; w: number }>) ?? {};
  }

  /** Set Euler rotations for any subset of bones in one HTTP call; bones not named are left unchanged. */
  async setBoneRotations(data: Record<string, [number, number, number]>): Promise<void> {
    const dataJson = JSON.stringify(data);
    const script = this.skeletonScript(`
            var _data = ${dataJson};
            var _bones = _node.getAllBones();
            for (var i = 0; i < _bones.length; i++) {
                var _b = _bones[i];
                var _n = _b.getName();
                if (_data.hasOwnProperty(_n)) {
                    var _r = _data[_n];
                    _b.getXRotControl().setValue(_r[0]);
                    _b.getYRotControl().setValue(_r[1]);
                    _b.getZRotControl().setValue(_r[2]);
                }
            }
        `);
    await this.client.execute(script);
  }

  /**
   * Set bone rotations, morph values, and/or node properties in one call.
   * Each argument is independently optional and uses plain `setValue()`
   * writes (same as {@link setBoneRotations}/{@link setMorphValues}) — `props`
   * is NOT routed through any ERC-avoidance logic, so on ERC-driven node
   * properties this can double-apply a controller contribution the same
   * way `DazElement.setProperty` already can.
   */
  async setState(opts: {
    bones?: Record<string, [number, number, number]>;
    morphs?: Record<string, number>;
    props?: Record<string, unknown>;
  }): Promise<void> {
    const lines: string[] = [];
    if (opts.bones) {
      lines.push(`
                var _bonesData = ${JSON.stringify(opts.bones)};
                var _allBones = _node.getAllBones();
                for (var i = 0; i < _allBones.length; i++) {
                    var _b = _allBones[i];
                    var _bn = _b.getName();
                    if (_bonesData.hasOwnProperty(_bn)) {
                        var _r = _bonesData[_bn];
                        _b.getXRotControl().setValue(_r[0]);
                        _b.getYRotControl().setValue(_r[1]);
                        _b.getZRotControl().setValue(_r[2]);
                    }
                }
            `);
    }
    if (opts.morphs) {
      lines.push(`
                var _morphsData = ${JSON.stringify(opts.morphs)};
                var _obj = _node.getObject();
                if (_obj) {
                    for (var j = 0; j < _obj.getNumModifiers(); j++) {
                        var _m = _obj.getModifier(j);
                        if (_m.className() === "DzMorph" && _morphsData.hasOwnProperty(_m.getName())) {
                            _m.getValueChannel().setValue(_morphsData[_m.getName()]);
                        }
                    }
                }
            `);
    }
    if (opts.props) {
      lines.push(`
                var _propsData = ${JSON.stringify(opts.props)};
                for (var k = 0; k < _node.getNumProperties(); k++) {
                    var _p = _node.getProperty(k);
                    var _pl = _p.getLabel();
                    if (_propsData.hasOwnProperty(_pl)) {
                        _p.setValue(_propsData[_pl]);
                    }
                }
            `);
    }
    if (lines.length === 0) return;
    await this.client.execute(this.skeletonScript(lines.join("\n")));
  }

  /** Current value of every `DzMorph` modifier in one HTTP call; `nonzeroOnly` excludes values with `|v| <= 0.0001`. */
  async morphValues(nonzeroOnly = false): Promise<Record<string, number>> {
    const nzJs = nonzeroOnly ? "true" : "false";
    const script = this.skeletonScript(`
            var _obj = _node.getObject();
            if (!_obj) return {};
            var _result = {};
            var _nz = ${nzJs};
            for (var i = 0; i < _obj.getNumModifiers(); i++) {
                var _m = _obj.getModifier(i);
                if (_m.className() === "DzMorph") {
                    var _v = _m.getValueChannel().getValue();
                    if (!_nz || Math.abs(_v) > 0.0001) {
                        _result[_m.getName()] = _v;
                    }
                }
            }
            return _result;
        `);
    return ((await this.client.execute(script)).value as Record<string, number>) ?? {};
  }

  /** Set the value of any subset of morphs in one HTTP call; morphs not named are left unchanged. */
  async setMorphValues(data: Record<string, number>): Promise<void> {
    const dataJson = JSON.stringify(data);
    const script = this.skeletonScript(`
            var _data = ${dataJson};
            var _obj = _node.getObject();
            if (!_obj) return null;
            for (var i = 0; i < _obj.getNumModifiers(); i++) {
                var _m = _obj.getModifier(i);
                if (_m.className() === "DzMorph" && _data.hasOwnProperty(_m.getName())) {
                    _m.getValueChannel().setValue(_data[_m.getName()]);
                }
            }
        `);
    await this.client.execute(script);
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd daz-ts && npx vitest run test/unit/skeleton.test.ts test/unit/scriptBuilder.test.ts`
Expected: PASS (4 skeleton tests + updated scriptBuilder tests)

- [ ] **Step 5: Add the barrel export and commit**

```typescript
// daz-ts/src/index.ts
export { DazSkeleton } from "./skeleton.js";
```

```bash
git add daz-ts/src/skeleton.ts daz-ts/src/scriptBuilder.ts daz-ts/test/unit/skeleton.test.ts daz-ts/test/unit/scriptBuilder.test.ts daz-ts/src/index.ts
git commit -m "feat(daz-ts): port DazSkeleton bone lookup and bulk bone/morph state"
```

---

### Task 11: `DazSkeleton` part 2 (pose evaluation, keyframe baking, follow target)

**Files:**
- Modify: `daz-ts/src/skeleton.ts` (add methods to the `DazSkeleton` class from Task 10)
- Modify: `daz-ts/test/unit/skeleton.test.ts` (add a new `describe` block)

**Interfaces:**
- Consumes: nothing new beyond Task 10's imports.
- Produces (added to `DazSkeleton`): `evaluatePose(rotations: Record<string,[number,number,number]>, effectorBoneNames: string[]): Promise<Record<string,[number,number,number]>>; evaluatePoseJacobian(chainBoneNames: string[], effectorBoneName: string, stepDegrees?: number): Promise<{basePosition:[number,number,number]; columns: Array<[number,number,number]>} | null>; bakeBoneRotations(opts?: {start?: number; end?: number; boneNames?: string[]}): Promise<{framesBaked: number; bonesBaked: number}>; bakeMorphs(opts?: {start?: number; end?: number; morphNames?: string[]}): Promise<{framesBaked: number; morphsBaked: number}>; bake(opts?: {start?: number; end?: number; boneNames?: string[]; includeMorphs?: boolean; morphNames?: string[]}): Promise<{framesBaked: number; bonesBaked: number; morphsBaked: number}>; followTarget(): Promise<DazSkeleton|null>;` — this closes out `DazSkeleton`'s public surface for Phase 2 (IK-dependent `handToTarget`/`footToTarget` are explicitly out of scope; see Global Constraints).

- [ ] **Step 1: Write the failing test**

```typescript
// Append to daz-ts/test/unit/skeleton.test.ts
describe("DazSkeleton pose evaluation and baking", () => {
  it("evaluatePose restores original rotations after reading effector positions", async () => {
    const fetchMock = stub({ r_hand: [10, 20, 30] });
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const result = await skel.evaluatePose({ r_forearm: [45, 0, 0] }, ["r_hand"]);
    expect(result).toEqual({ r_hand: [10, 20, 30] });
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("_originals[_n]");
  });

  it("evaluatePoseJacobian returns null when the effector bone cannot be found", async () => {
    stub(null);
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await skel.evaluatePoseJacobian(["r_shoulder", "r_forearm"], "r_hand")).toBeNull();
  });

  it("bakeBoneRotations defaults start/end to the scene play range when omitted", async () => {
    const fetchMock = stub({ frames_baked: 30, bones_baked: 2 });
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const result = await skel.bakeBoneRotations();
    expect(result).toEqual({ framesBaked: 30, bonesBaked: 2 });
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("_prStart");
    expect(script).toContain("insertKey");
  });

  it("bake() combines bones and morphs when includeMorphs is true", async () => {
    const fetchMock = stub({ frames_baked: 10, bones_baked: 1, morphs_baked: 1 });
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await skel.bake({ includeMorphs: true });
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("_withMorphs = true");
  });

  it("followTarget returns null when no IK target is set", async () => {
    stub(null);
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await skel.followTarget()).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/skeleton.test.ts`
Expected: FAIL — `skel.evaluatePose is not a function`

- [ ] **Step 3: Add the methods to `DazSkeleton`**

```typescript
// Add inside the DazSkeleton class body, after setMorphValues()

  /**
   * Apply candidate rotations, read effector world positions, then restore —
   * the figure is left in its original state after this call.
   */
  async evaluatePose(
    rotations: Record<string, [number, number, number]>,
    effectorBoneNames: string[],
  ): Promise<Record<string, [number, number, number]>> {
    const rotationsJson = JSON.stringify(rotations);
    const effectorsJson = JSON.stringify(effectorBoneNames);
    const script = this.skeletonScript(`
            var _data = ${rotationsJson};
            var _effNames = ${effectorsJson};
            var _allBones = _node.getAllBones();

            var _originals = {};
            for (var i = 0; i < _allBones.length; i++) {
                var _b = _allBones[i]; var _n = _b.getName();
                if (_data.hasOwnProperty(_n)) {
                    _originals[_n] = [
                        _b.getXRotControl().getValue(),
                        _b.getYRotControl().getValue(),
                        _b.getZRotControl().getValue()
                    ];
                    var _r = _data[_n];
                    _b.getXRotControl().setValue(_r[0]);
                    _b.getYRotControl().setValue(_r[1]);
                    _b.getZRotControl().setValue(_r[2]);
                }
            }

            var _result = {};
            var _effSet = {};
            for (var j = 0; j < _effNames.length; j++) { _effSet[_effNames[j]] = true; }
            for (var i = 0; i < _allBones.length; i++) {
                var _b = _allBones[i]; var _n = _b.getName();
                if (_effSet.hasOwnProperty(_n)) {
                    var _p = _b.getWSPos();
                    _result[_n] = [_p.x, _p.y, _p.z];
                }
            }

            for (var i = 0; i < _allBones.length; i++) {
                var _b = _allBones[i]; var _n = _b.getName();
                if (_originals.hasOwnProperty(_n)) {
                    var _r = _originals[_n];
                    _b.getXRotControl().setValue(_r[0]);
                    _b.getYRotControl().setValue(_r[1]);
                    _b.getZRotControl().setValue(_r[2]);
                }
            }
            return _result;
        `);
    const raw = ((await this.client.execute(script)).value as Record<string, number[]>) ?? {};
    const out: Record<string, [number, number, number]> = {};
    for (const [name, v] of Object.entries(raw)) {
      out[name] = [v[0], v[1], v[2]];
    }
    return out;
  }

  /**
   * Compute the IK Jacobian for a bone chain server-side in one HTTP call:
   * perturbs each (bone, axis) pair by `stepDegrees`, reads the effector
   * world position, and restores the original rotation. The figure is left
   * unchanged. Returns `null` if the effector bone cannot be found.
   */
  async evaluatePoseJacobian(
    chainBoneNames: string[],
    effectorBoneName: string,
    stepDegrees = 1.0,
  ): Promise<{ basePosition: [number, number, number]; columns: Array<[number, number, number]> } | null> {
    const chainJson = JSON.stringify(chainBoneNames);
    const effectorJson = JSON.stringify(effectorBoneName);
    const script = this.skeletonScript(`
            var _chain = ${chainJson};
            var _effName = ${effectorJson};
            var _step = ${stepDegrees};

            var _allBones = _node.getAllBones();
            var _boneMap = {};
            for (var i = 0; i < _allBones.length; i++) {
                _boneMap[_allBones[i].getName()] = _allBones[i];
            }

            var _eff = _boneMap[_effName];
            if (!_eff) return null;

            var _bp = _eff.getWSPos();
            var _base = [_bp.x, _bp.y, _bp.z];

            var _columns = [];
            for (var c = 0; c < _chain.length; c++) {
                var _b = _boneMap[_chain[c]];
                if (!_b) {
                    _columns.push([0,0,0]); _columns.push([0,0,0]); _columns.push([0,0,0]);
                    continue;
                }
                var _ctrls = [_b.getXRotControl(), _b.getYRotControl(), _b.getZRotControl()];
                for (var axis = 0; axis < 3; axis++) {
                    var _ctrl = _ctrls[axis];
                    var _orig = _ctrl.getValue();
                    _ctrl.setValue(_orig + _step);
                    var _tp = _eff.getWSPos();
                    _ctrl.setValue(_orig);
                    _columns.push([
                        (_tp.x - _base[0]) / _step,
                        (_tp.y - _base[1]) / _step,
                        (_tp.z - _base[2]) / _step
                    ]);
                }
            }
            return {base_position: _base, columns: _columns};
        `);
    const result = (await this.client.execute(script)).value as
      | { base_position: [number, number, number]; columns: Array<[number, number, number]> }
      | null;
    if (result === null) return null;
    return { basePosition: result.base_position, columns: result.columns };
  }

  /** Bake bone rotation keyframes for every frame in the range via `insertKey`. The original frame is restored before returning. */
  async bakeBoneRotations(opts: { start?: number; end?: number; boneNames?: string[] } = {}): Promise<{
    framesBaked: number;
    bonesBaked: number;
  }> {
    const startJs = opts.start !== undefined ? String(opts.start) : "null";
    const endJs = opts.end !== undefined ? String(opts.end) : "null";
    const boneFilterJs = opts.boneNames !== undefined ? JSON.stringify(Object.fromEntries(opts.boneNames.map((n) => [n, true]))) : "null";
    const script = this.skeletonScript(`
            var _step    = Scene.getTimeStep();
            var _pr      = Scene.getPlayRange();
            var _prStart = Math.round(_pr.start / _step);
            var _prEnd   = Math.round(_pr.end   / _step);
            var _bkStart = (${startJs} !== null) ? ${startJs} : _prStart;
            var _bkEnd   = (${endJs}   !== null) ? ${endJs}   : _prEnd;
            var _filter  = ${boneFilterJs};

            var _all = _node.getAllBones();
            var _bones = [];
            for (var i = 0; i < _all.length; i++) {
                if (_filter === null || _filter.hasOwnProperty(_all[i].getName()))
                    _bones.push(_all[i]);
            }

            var _origFrame = Scene.getFrame();
            for (var f = _bkStart; f <= _bkEnd; f++) {
                Scene.setFrame(f);
                var _t = f * _step;
                for (var i = 0; i < _bones.length; i++) {
                    var _b = _bones[i];
                    _b.getXRotControl().insertKey(_t, _b.getXRotControl().getValue());
                    _b.getYRotControl().insertKey(_t, _b.getYRotControl().getValue());
                    _b.getZRotControl().insertKey(_t, _b.getZRotControl().getValue());
                }
            }
            Scene.setFrame(_origFrame);
            return {frames_baked: _bkEnd - _bkStart + 1, bones_baked: _bones.length};
        `);
    const result = (await this.client.execute(script)).value as { frames_baked: number; bones_baked: number } | null;
    return { framesBaked: result?.frames_baked ?? 0, bonesBaked: result?.bones_baked ?? 0 };
  }

  /** Bake morph channel keyframes for every frame in the range via `insertKey`. The original frame is restored before returning. */
  async bakeMorphs(opts: { start?: number; end?: number; morphNames?: string[] } = {}): Promise<{
    framesBaked: number;
    morphsBaked: number;
  }> {
    const startJs = opts.start !== undefined ? String(opts.start) : "null";
    const endJs = opts.end !== undefined ? String(opts.end) : "null";
    const morphFilterJs =
      opts.morphNames !== undefined ? JSON.stringify(Object.fromEntries(opts.morphNames.map((n) => [n, true]))) : "null";
    const script = this.skeletonScript(`
            var _step    = Scene.getTimeStep();
            var _pr      = Scene.getPlayRange();
            var _prStart = Math.round(_pr.start / _step);
            var _prEnd   = Math.round(_pr.end   / _step);
            var _bkStart = (${startJs} !== null) ? ${startJs} : _prStart;
            var _bkEnd   = (${endJs}   !== null) ? ${endJs}   : _prEnd;
            var _filter  = ${morphFilterJs};

            var _obj = _node.getObject();
            if (!_obj) return {frames_baked: 0, morphs_baked: 0};
            var _channels = [];
            for (var i = 0; i < _obj.getNumModifiers(); i++) {
                var _m = _obj.getModifier(i);
                if (_m.className() === "DzMorph" &&
                    (_filter === null || _filter.hasOwnProperty(_m.getName())))
                    _channels.push(_m.getValueChannel());
            }

            var _origFrame = Scene.getFrame();
            for (var f = _bkStart; f <= _bkEnd; f++) {
                Scene.setFrame(f);
                var _t = f * _step;
                for (var i = 0; i < _channels.length; i++) {
                    _channels[i].insertKey(_t, _channels[i].getValue());
                }
            }
            Scene.setFrame(_origFrame);
            return {frames_baked: _bkEnd - _bkStart + 1, morphs_baked: _channels.length};
        `);
    const result = (await this.client.execute(script)).value as { frames_baked: number; morphs_baked: number } | null;
    return { framesBaked: result?.frames_baked ?? 0, morphsBaked: result?.morphs_baked ?? 0 };
  }

  /** Bake bone rotations and optionally morphs in a single HTTP call (scrubs the timeline once instead of twice). */
  async bake(
    opts: {
      start?: number;
      end?: number;
      boneNames?: string[];
      includeMorphs?: boolean;
      morphNames?: string[];
    } = {},
  ): Promise<{ framesBaked: number; bonesBaked: number; morphsBaked: number }> {
    const startJs = opts.start !== undefined ? String(opts.start) : "null";
    const endJs = opts.end !== undefined ? String(opts.end) : "null";
    const boneFilterJs = opts.boneNames !== undefined ? JSON.stringify(Object.fromEntries(opts.boneNames.map((n) => [n, true]))) : "null";
    const morphFilterJs =
      opts.morphNames !== undefined ? JSON.stringify(Object.fromEntries(opts.morphNames.map((n) => [n, true]))) : "null";
    const withMorphsJs = opts.includeMorphs ? "true" : "false";
    const script = this.skeletonScript(`
            var _step    = Scene.getTimeStep();
            var _pr      = Scene.getPlayRange();
            var _prStart = Math.round(_pr.start / _step);
            var _prEnd   = Math.round(_pr.end   / _step);
            var _bkStart    = (${startJs} !== null) ? ${startJs} : _prStart;
            var _bkEnd      = (${endJs}   !== null) ? ${endJs}   : _prEnd;
            var _boneFilter = ${boneFilterJs};
            var _mFilter    = ${morphFilterJs};
            var _withMorphs = ${withMorphsJs};

            var _all = _node.getAllBones();
            var _bones = [];
            for (var i = 0; i < _all.length; i++) {
                if (_boneFilter === null || _boneFilter.hasOwnProperty(_all[i].getName()))
                    _bones.push(_all[i]);
            }

            var _mChannels = [];
            if (_withMorphs) {
                var _obj = _node.getObject();
                if (_obj) {
                    for (var i = 0; i < _obj.getNumModifiers(); i++) {
                        var _m = _obj.getModifier(i);
                        if (_m.className() === "DzMorph" &&
                            (_mFilter === null || _mFilter.hasOwnProperty(_m.getName())))
                            _mChannels.push(_m.getValueChannel());
                    }
                }
            }

            var _origFrame = Scene.getFrame();
            for (var f = _bkStart; f <= _bkEnd; f++) {
                Scene.setFrame(f);
                var _t = f * _step;
                for (var i = 0; i < _bones.length; i++) {
                    var _b = _bones[i];
                    _b.getXRotControl().insertKey(_t, _b.getXRotControl().getValue());
                    _b.getYRotControl().insertKey(_t, _b.getYRotControl().getValue());
                    _b.getZRotControl().insertKey(_t, _b.getZRotControl().getValue());
                }
                for (var i = 0; i < _mChannels.length; i++) {
                    _mChannels[i].insertKey(_t, _mChannels[i].getValue());
                }
            }
            Scene.setFrame(_origFrame);
            return {
                frames_baked: _bkEnd - _bkStart + 1,
                bones_baked:  _bones.length,
                morphs_baked: _mChannels.length
            };
        `);
    const result = (await this.client.execute(script)).value as
      | { frames_baked: number; bones_baked: number; morphs_baked: number }
      | null;
    return {
      framesBaked: result?.frames_baked ?? 0,
      bonesBaked: result?.bones_baked ?? 0,
      morphsBaked: result?.morphs_baked ?? 0,
    };
  }

  /**
   * The IK follow-target skeleton, or `null` if not set.
   * @remarks Aligning a limb *toward* a target ({@link DazSkeleton}'s Python
   * counterpart's `hand_to_target`/`foot_to_target`) requires the Jacobian
   * IK solver in `_interaction.py`, ported in Phase 5 (`daz-script-server-sf7y`) —
   * not available in this phase.
   */
  async followTarget(): Promise<DazSkeleton | null> {
    const name = (await this.client.execute(this.skeletonScript("var t = _node.getFollowTarget(); return t ? t.getName() : null;")))
      .value as string | null;
    if (name === null) return null;
    return new DazSkeleton(this.client, { value: name, kind: "name" });
  }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd daz-ts && npx vitest run test/unit/skeleton.test.ts`
Expected: PASS (9 tests total)

- [ ] **Step 5: Commit**

```bash
git add daz-ts/src/skeleton.ts daz-ts/test/unit/skeleton.test.ts
git commit -m "feat(daz-ts): add DazSkeleton pose evaluation and keyframe baking"
```

---

### Task 12: `DazScene` part 1 (node/camera/light/skeleton factories, selection)

**Files:**
- Create: `daz-ts/src/scene.ts`
- Test: `daz-ts/test/unit/scene.test.ts`
- Modify: `daz-ts/src/index.ts` (add `export { DazScene } from "./scene.js";`)

**Interfaces:**
- Consumes: `DazClient` (Phase 1), `DazNode`/`NodeIdentifier` (Task 3/6), `DazSkeleton` (Task 10/11), `DazCamera` (Task 8), `DazLight` (Task 9), `NodeNotFoundError` (Phase 1).
- Produces: `class DazScene { constructor(client?: DazClient); nodes(): Promise<DazNode[]>; findNode(name: string): Promise<DazNode>; findNodeByLabel(label: string): Promise<DazNode>; numNodes(): Promise<number>; cameras(): Promise<DazCamera[]>; lights(): Promise<DazLight[]>; findCameraByLabel(label: string): Promise<DazCamera>; createCamera(name?: string): Promise<DazCamera>; createLight(lightType: "spot"|"point"|"distant", name?: string): Promise<DazLight>; findLightByLabel(label: string): Promise<DazLight>; skeletons(): Promise<DazSkeleton[]>; findSkeleton(name: string, opts?: {retryAttempts?: number; retryDelay?: number}): Promise<DazSkeleton>; findSkeletonByLabel(label: string): Promise<DazSkeleton>; numSkeletons(): Promise<number>; selectedNodes(): Promise<DazNode[]>; primarySelection(): Promise<DazNode|null>; setPrimarySelection(node: DazNode): Promise<void>; selectAll(on?: boolean): Promise<void>; }` (part 1 methods only) — same class Tasks 13-14 extend.

- [ ] **Step 1: Write the failing test**

```typescript
import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazScene } from "../../src/scene.js";
import { DazSkeleton } from "../../src/skeleton.js";
import { DazCamera } from "../../src/camera.js";
import { DazLight } from "../../src/light.js";
import { DazNode } from "../../src/node.js";
import { NodeNotFoundError } from "../../src/exceptions.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}
afterEach(() => vi.unstubAllGlobals());
function stubSeq(...values: unknown[]) {
  const fetchMock = vi.fn();
  for (const v of values) {
    fetchMock.mockResolvedValueOnce(jsonResponse({ success: true, result: v, output: [], request_id: "r", duration_ms: 0 }));
  }
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("DazScene node/camera/light/skeleton factories", () => {
  it("nodes() classifies each entry using DazScript inherits(), returning typed proxies", async () => {
    stubSeq([
      { name: "Genesis9", className: "DzSkeleton" },
      { name: "Camera", className: "DzCamera" },
      { name: "Light1", className: "DzLight" },
      { name: "Prop1", className: "DzNode" },
    ]);
    const scene = new DazScene(new DazClient({ token: "" }));
    const nodes = await scene.nodes();
    expect(nodes[0]).toBeInstanceOf(DazSkeleton);
    expect(nodes[1]).toBeInstanceOf(DazCamera);
    expect(nodes[2]).toBeInstanceOf(DazLight);
    expect(nodes[3]).toBeInstanceOf(DazNode);
    expect(nodes[3]).not.toBeInstanceOf(DazSkeleton);
  });

  it("findNode rejects with NodeNotFoundError when Scene.findNode resolves to nothing", async () => {
    stubSeq(false);
    const scene = new DazScene(new DazClient({ token: "" }));
    await expect(scene.findNode("Missing")).rejects.toBeInstanceOf(NodeNotFoundError);
  });

  it("findNodeByLabel keeps kind='label' on the returned proxy (does not resolve to internal name)", async () => {
    stubSeq(true);
    const scene = new DazScene(new DazClient({ token: "" }));
    const node = await scene.findNodeByLabel("My Prop");
    expect(node.identifier).toEqual({ value: "My Prop", kind: "label" });
  });

  it("createLight rejects unknown light types before making any HTTP call", async () => {
    const fetchMock = stubSeq();
    const scene = new DazScene(new DazClient({ token: "" }));
    await expect(scene.createLight("halogen" as never)).rejects.toThrow(/Unknown light_type/);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("findSkeleton retries getSkeletonList() up to retryAttempts times before raising NodeNotFoundError", async () => {
    const fetchMock = stubSeq(false, false, false, []);
    const scene = new DazScene(new DazClient({ token: "" }));
    await expect(scene.findSkeleton("Ghost", { retryAttempts: 3, retryDelay: 0 })).rejects.toBeInstanceOf(NodeNotFoundError);
    expect(fetchMock).toHaveBeenCalledTimes(4); // 3 lookup attempts + 1 hint call
  });

  it("findSkeletonByLabel keeps kind='label' so same-named figures stay distinct", async () => {
    stubSeq(true);
    const scene = new DazScene(new DazClient({ token: "" }));
    const skel = await scene.findSkeletonByLabel("Genesis 9");
    expect(skel.identifier).toEqual({ value: "Genesis 9", kind: "label" });
  });

  it("primarySelection returns null when nothing is selected", async () => {
    stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    expect(await scene.primarySelection()).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/scene.test.ts`
Expected: FAIL with "Cannot find module '../../src/scene.js'"

- [ ] **Step 3: Implement `DazScene` part 1**

```typescript
import { DazCamera } from "./camera.js";
import { DazClient } from "./client.js";
import { NodeNotFoundError } from "./exceptions.js";
import { DazLight } from "./light.js";
import { DazNode, type NodeIdentifier } from "./node.js";
import { ScriptBuilder } from "./scriptBuilder.js";
import { DazSkeleton } from "./skeleton.js";

const LIGHT_TYPE_CLASSES: Record<string, string> = {
  spot: "DzSpotLight",
  point: "DzPointLight",
  distant: "DzDistantLight",
};

function sleep(seconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, seconds * 1000));
}

/**
 * High-level proxy for the active DAZ Studio scene (`Scene` global) — the
 * primary entry point for inspecting and manipulating the scene.
 */
export class DazScene {
  private readonly client: DazClient;

  constructor(client?: DazClient) {
    this.client = client ?? new DazClient();
  }

  /** All top-level and child nodes in the scene, typed via `inherits()` (DazSkeleton/DazCamera/DazLight/DazNode), scene-panel order. */
  async nodes(): Promise<DazNode[]> {
    const script = ScriptBuilder.iife(`
            var result = [];
            for (var i = 0; i < Scene.getNumNodes(); i++) {
                var n = Scene.getNode(i);
                var nodeType = "DzNode";
                if (n.inherits("DzSkeleton")) { nodeType = "DzSkeleton"; }
                else if (n.inherits("DzCamera")) { nodeType = "DzCamera"; }
                else if (n.inherits("DzLight")) { nodeType = "DzLight"; }
                result.push({name: n.getName(), className: nodeType});
            }
            return result;
        `);
    const items = ((await this.client.execute(script)).value as Array<{ name: string; className: string }>) ?? [];
    return items.map((item) => {
      const identifier: NodeIdentifier = { value: item.name, kind: "name" };
      if (item.className === "DzSkeleton") return new DazSkeleton(this.client, identifier);
      if (item.className === "DzCamera") return new DazCamera(this.client, identifier);
      if (item.className === "DzLight") return new DazLight(this.client, identifier);
      return new DazNode(this.client, identifier);
    });
  }

  /** Find a scene node by internal name. */
  async findNode(name: string): Promise<DazNode> {
    const exists = ScriptBuilder.iife(`return !!Scene.findNode(${ScriptBuilder.escapeString(name)});`);
    if (!(await this.client.execute(exists)).value) {
      throw new NodeNotFoundError(`Node not found: ${JSON.stringify(name)}`);
    }
    return new DazNode(this.client, { value: name, kind: "name" });
  }

  /** Find a scene node by its user-visible label. Anchored to the internal *name*, so it stays stable if the label later changes. */
  async findNodeByLabel(label: string): Promise<DazNode> {
    const exists = ScriptBuilder.iife(`return !!Scene.findNodeByLabel(${ScriptBuilder.escapeString(label)});`);
    if (!(await this.client.execute(exists)).value) {
      throw new NodeNotFoundError(`Node with label not found: ${JSON.stringify(label)}`);
    }
    return new DazNode(this.client, { value: label, kind: "label" });
  }

  async numNodes(): Promise<number> {
    return ((await this.client.execute(ScriptBuilder.iife("return Scene.getNumNodes();"))).value as number) ?? 0;
  }

  async cameras(): Promise<DazCamera[]> {
    const script = ScriptBuilder.iife(
      "var names = []; for (var i = 0; i < Scene.getNumCameras(); i++) { names.push(Scene.getCamera(i).getName()); } return names;",
    );
    const names = ((await this.client.execute(script)).value as string[]) ?? [];
    return names.map((n) => new DazCamera(this.client, { value: n, kind: "name" }));
  }

  async lights(): Promise<DazLight[]> {
    const script = ScriptBuilder.iife(
      "var names = []; for (var i = 0; i < Scene.getNumLights(); i++) { names.push(Scene.getLight(i).getName()); } return names;",
    );
    const names = ((await this.client.execute(script)).value as string[]) ?? [];
    return names.map((n) => new DazLight(this.client, { value: n, kind: "name" }));
  }

  /** Find a camera by its user-visible label (same value accepted by `render()`'s `camera` parameter in Phase 3). */
  async findCameraByLabel(label: string): Promise<DazCamera> {
    const exists = ScriptBuilder.iife(`return !!Scene.findCameraByLabel(${ScriptBuilder.escapeString(label)});`);
    if (!(await this.client.execute(exists)).value) {
      throw new NodeNotFoundError(`Camera with label not found: ${JSON.stringify(label)}`);
    }
    return new DazCamera(this.client, { value: label, kind: "label" });
  }

  /** Create a new basic camera node and add it to the scene. `name` omitted → DAZ Studio assigns its default (de-duplicated) name. */
  async createCamera(name?: string): Promise<DazCamera> {
    const nameExpr = name !== undefined ? ScriptBuilder.escapeString(name) : "null";
    const script = ScriptBuilder.iife(`
            var cam = new DzBasicCamera();
            if (${nameExpr} !== null) cam.setName(${nameExpr});
            Scene.addNode(cam);
            return cam.getName();
        `);
    const createdName = (await this.client.execute(script)).value as string;
    return new DazCamera(this.client, { value: createdName, kind: "name" });
  }

  /** Create a new light node (`"spot"`/`"point"`/`"distant"`) and add it to the scene. */
  async createLight(lightType: "spot" | "point" | "distant", name?: string): Promise<DazLight> {
    const className = LIGHT_TYPE_CLASSES[lightType];
    if (className === undefined) {
      throw new Error(`Unknown light_type ${JSON.stringify(lightType)}; expected one of ${JSON.stringify(Object.keys(LIGHT_TYPE_CLASSES).sort())}`);
    }
    const nameExpr = name !== undefined ? ScriptBuilder.escapeString(name) : "null";
    const script = ScriptBuilder.iife(`
            var light = new ${className}();
            if (${nameExpr} !== null) light.setName(${nameExpr});
            Scene.addNode(light);
            return light.getName();
        `);
    const createdName = (await this.client.execute(script)).value as string;
    return new DazLight(this.client, { value: createdName, kind: "name" });
  }

  async findLightByLabel(label: string): Promise<DazLight> {
    const exists = ScriptBuilder.iife(`return !!Scene.findLightByLabel(${ScriptBuilder.escapeString(label)});`);
    if (!(await this.client.execute(exists)).value) {
      throw new NodeNotFoundError(`Light with label not found: ${JSON.stringify(label)}`);
    }
    return new DazLight(this.client, { value: label, kind: "label" });
  }

  async skeletons(): Promise<DazSkeleton[]> {
    const script = ScriptBuilder.iife(
      "var names = []; var skels = Scene.getSkeletonList(); for (var i = 0; i < skels.length; i++) { names.push(skels[i].getName()); } return names;",
    );
    const names = ((await this.client.execute(script)).value as string[]) ?? [];
    return names.map((n) => new DazSkeleton(this.client, { value: n, kind: "name" }));
  }

  /**
   * Find a skeleton by internal name, retrying `Scene.getSkeletonList()` up
   * to `retryAttempts` times (default 3, `retryDelay * attemptNumber`
   * seconds apart, default base 0.15s) — `getSkeletonList()` has been
   * observed to transiently omit a present skeleton under main-thread load
   * (daz-script-server-xtkd); a momentary miss is retried rather than
   * immediately raised. Pass `retryAttempts: 1` to disable retrying.
   */
  async findSkeleton(name: string, opts: { retryAttempts?: number; retryDelay?: number } = {}): Promise<DazSkeleton> {
    const { retryAttempts = 3, retryDelay = 0.15 } = opts;
    const lookup = ScriptBuilder.iife(`
            var skels = Scene.getSkeletonList();
            for (var i = 0; i < skels.length; i++) {
                if (skels[i].getName() === ${ScriptBuilder.escapeString(name)}) return true;
            }
            return false;
        `);
    let found = false;
    for (let attempt = 0; attempt < retryAttempts; attempt++) {
      if ((await this.client.execute(lookup)).value) {
        found = true;
        break;
      }
      if (attempt < retryAttempts - 1) {
        await sleep(retryDelay * (attempt + 1));
      }
    }
    if (!found) {
      const hint = ScriptBuilder.iife(`
                var info = [];
                var skels = Scene.getSkeletonList();
                for (var i = 0; i < skels.length; i++) {
                    info.push(skels[i].getName() + "|" + skels[i].getLabel());
                }
                return info;
            `);
      const pairs = ((await this.client.execute(hint)).value as string[]) ?? [];
      if (pairs.length > 0) {
        const available = pairs
          .map((entry) => {
            const [n, l] = entry.split("|");
            return `${JSON.stringify(n)} (label: ${JSON.stringify(l)})`;
          })
          .join(", ");
        throw new NodeNotFoundError(
          `Skeleton not found: ${JSON.stringify(name)}. Available skeletons: ${available}. ` +
            `Tip: use findSkeletonByLabel() to search by the Scene-panel label.`,
        );
      }
      throw new NodeNotFoundError(`Skeleton not found: ${JSON.stringify(name)} (no skeletons in scene).`);
    }
    return new DazSkeleton(this.client, { value: name, kind: "name" });
  }

  /** Find a skeleton by its user-visible label. Kept as `kind: "label"` — same-asset figures share an internal name, so name-based lookup would collapse distinct figures into one. */
  async findSkeletonByLabel(label: string): Promise<DazSkeleton> {
    const exists = ScriptBuilder.iife(`return !!Scene.findSkeletonByLabel(${ScriptBuilder.escapeString(label)});`);
    if (!(await this.client.execute(exists)).value) {
      throw new NodeNotFoundError(`Skeleton with label not found: ${JSON.stringify(label)}`);
    }
    return new DazSkeleton(this.client, { value: label, kind: "label" });
  }

  async numSkeletons(): Promise<number> {
    return ((await this.client.execute(ScriptBuilder.iife("return Scene.getNumSkeletons();"))).value as number) ?? 0;
  }

  async selectedNodes(): Promise<DazNode[]> {
    const script = ScriptBuilder.iife(`
            var nodes = Scene.getSelectedNodeList();
            var names = [];
            for (var i = 0; i < nodes.length; i++) {
                names.push(nodes[i].getName());
            }
            return names;
        `);
    const names = ((await this.client.execute(script)).value as string[]) ?? [];
    return names.map((n) => new DazNode(this.client, { value: n, kind: "name" }));
  }

  async primarySelection(): Promise<DazNode | null> {
    const name = (await this.client.execute(ScriptBuilder.iife("var n = Scene.getPrimarySelection(); return n ? n.getName() : null;")))
      .value as string | null;
    if (name === null) return null;
    return new DazNode(this.client, { value: name, kind: "name" });
  }

  async setPrimarySelection(node: DazNode): Promise<void> {
    const findExpr = ScriptBuilder.findNodeExpr(node.identifier);
    await this.client.execute(ScriptBuilder.iife(`Scene.setPrimarySelection(${findExpr});`));
  }

  async selectAll(on = true): Promise<void> {
    await this.client.execute(ScriptBuilder.iife(`Scene.selectAllNodes(${on ? "true" : "false"});`));
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd daz-ts && npx vitest run test/unit/scene.test.ts`
Expected: PASS (7 tests)

- [ ] **Step 5: Add the barrel export and commit**

```typescript
// daz-ts/src/index.ts
export { DazScene } from "./scene.js";
```

```bash
git add daz-ts/src/scene.ts daz-ts/test/unit/scene.test.ts daz-ts/src/index.ts
git commit -m "feat(daz-ts): port DazScene node/camera/light/skeleton factories"
```

---

### Task 13: `DazScene` part 2 (bulk scene snapshots)

**Files:**
- Modify: `daz-ts/src/scene.ts` (add methods to `DazScene`)
- Modify: `daz-ts/test/unit/scene.test.ts` (add a new `describe` block)

**Interfaces:**
- Consumes: nothing new beyond Task 12's imports.
- Produces (added to `DazScene`): `sceneSnapshot(skeletonLabels?: string[]): Promise<Array<Record<string, unknown>>>; allNodeTransforms(): Promise<Array<Record<string, unknown>>>; nodeTree(): Promise<Array<Record<string, unknown>>>; nodeHierarchy(opts?: {root?: string; maxDepth?: number}): Promise<{node: string; hierarchy: Record<string, unknown> | null; totalDescendants: number}>; overview(): Promise<Record<string, unknown>>;`

- [ ] **Step 1: Write the failing test**

```typescript
// Append to daz-ts/test/unit/scene.test.ts
describe("DazScene bulk snapshots", () => {
  it("sceneSnapshot passes a JSON null filter when skeletonLabels is omitted", async () => {
    const fetchMock = stubSeq([]);
    const scene = new DazScene(new DazClient({ token: "" }));
    await scene.sceneSnapshot();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("var _filter = null;");
  });

  it("sceneSnapshot passes the label/name filter as a JSON array when provided", async () => {
    const fetchMock = stubSeq([]);
    const scene = new DazScene(new DazClient({ token: "" }));
    await scene.sceneSnapshot(["Genesis 9"]);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain('var _filter = ["Genesis 9"];');
  });

  it("nodeHierarchy raises NodeNotFoundError when the root cannot be found", async () => {
    stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    await expect(scene.nodeHierarchy({ root: "Ghost" })).rejects.toBeInstanceOf(NodeNotFoundError);
  });

  it("nodeHierarchy maps total_descendants to totalDescendants", async () => {
    stubSeq({ node: "Genesis 9", hierarchy: { label: "Genesis 9", name: "Genesis9", type: "DzFigure" }, total_descendants: 5 });
    const scene = new DazScene(new DazClient({ token: "" }));
    const result = await scene.nodeHierarchy({ root: "Genesis 9", maxDepth: 2 });
    expect(result.totalDescendants).toBe(5);
  });

  it("overview() falls back to an empty-scene default when the server returns null", async () => {
    stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    const result = await scene.overview();
    expect(result).toEqual({ scene_file: "", selected_node: null, figures: [], cameras: [], lights: [], total_nodes: 0 });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/scene.test.ts`
Expected: FAIL — `scene.sceneSnapshot is not a function`

- [ ] **Step 3: Add the methods to `DazScene`**

```typescript
// Add inside the DazScene class body, after selectAll()

  /**
   * Full skeleton and bone metadata for the scene in one HTTP call.
   * @param skeletonLabels Optional subset of skeleton names/labels to include; omit to return every skeleton.
   */
  async sceneSnapshot(skeletonLabels?: string[]): Promise<Array<Record<string, unknown>>> {
    const filterJs = skeletonLabels !== undefined ? JSON.stringify(skeletonLabels) : "null";
    const script = ScriptBuilder.iife(`
            var _filter = ${filterJs};
            var _skels = Scene.getSkeletonList();
            var _result = [];
            for (var _s = 0; _s < _skels.length; _s++) {
                var _skel = _skels[_s];
                if (_filter !== null) {
                    var _found = false;
                    for (var _f = 0; _f < _filter.length; _f++) {
                        if (_filter[_f] === _skel.getName() || _filter[_f] === _skel.getLabel()) {
                            _found = true; break;
                        }
                    }
                    if (!_found) continue;
                }
                var _bones = _skel.getAllBones();
                var _boneList = [];
                for (var _i = 0; _i < _bones.length; _i++) {
                    var _b = _bones[_i];
                    var _parent = _b.getNodeParent();
                    var _parentName = null;
                    if (_parent && _parent.className && _parent.className() === "DzBone") {
                        _parentName = _parent.getName();
                    }
                    var _lpos = _b.getLocalPos();
                    var _wpos = _b.getWSPos();
                    _boneList.push({
                        name: _b.getName(),
                        label: _b.getLabel(),
                        parent_name: _parentName,
                        rotation_order: _b.getRotationOrder(),
                        local_position: {x: _lpos.x, y: _lpos.y, z: _lpos.z},
                        world_position: {x: _wpos.x, y: _wpos.y, z: _wpos.z},
                        local_euler: {
                            x: _b.getXRotControl().getValue(),
                            y: _b.getYRotControl().getValue(),
                            z: _b.getZRotControl().getValue()
                        }
                    });
                }
                _result.push({
                    name: _skel.getName(),
                    label: _skel.getLabel(),
                    bones: _boneList
                });
            }
            return _result;
        `);
    return ((await this.client.execute(script)).value as Array<Record<string, unknown>>) ?? [];
  }

  /** World-space transforms (`name`/`label`/`position`/`rotation`/`visible`) for every node, in one HTTP call. */
  async allNodeTransforms(): Promise<Array<Record<string, unknown>>> {
    const script = ScriptBuilder.iife(`
            var result = [];
            for (var i = 0; i < Scene.getNumNodes(); i++) {
                var n = Scene.getNode(i);
                var pos = n.getWSPos();
                var rot = n.getWSRot();
                result.push({
                    name: n.getName(),
                    label: n.getLabel(),
                    position: [pos.x, pos.y, pos.z],
                    rotation: [rot.x, rot.y, rot.z],
                    visible: n.isVisible()
                });
            }
            return result;
        `);
    return ((await this.client.execute(script)).value as Array<Record<string, unknown>>) ?? [];
  }

  /** Full scene hierarchy as nested `{name, label, children}` dicts, one entry per root-level node. */
  async nodeTree(): Promise<Array<Record<string, unknown>>> {
    const script = ScriptBuilder.iife(`
            function nodeToDict(n) {
                var children = [];
                for (var i = 0; i < n.getNumNodeChildren(); i++) {
                    children.push(nodeToDict(n.getNodeChild(i)));
                }
                return {name: n.getName(), label: n.getLabel(), children: children};
            }
            var roots = [];
            for (var i = 0; i < Scene.getNumNodes(); i++) {
                var n = Scene.getNode(i);
                if (!n.getNodeParent()) roots.push(nodeToDict(n));
            }
            return roots;
        `);
    return ((await this.client.execute(script)).value as Array<Record<string, unknown>>) ?? [];
  }

  /**
   * Descendant tree rooted at a single node (searched by label first, then internal name), with an optional recursion-depth limit.
   * @throws NodeNotFoundError if `root` cannot be found.
   */
  async nodeHierarchy(opts: { root?: string; maxDepth?: number } = {}): Promise<{
    node: string;
    hierarchy: Record<string, unknown> | null;
    totalDescendants: number;
  }> {
    const rootJson = JSON.stringify(opts.root ?? null);
    const depthJs = opts.maxDepth ? String(Math.trunc(opts.maxDepth)) : "0";
    const script = ScriptBuilder.iife(`
            var _rootLabel = ${rootJson};
            var _node = Scene.findNodeByLabel(_rootLabel);
            if (!_node) _node = Scene.findNode(_rootLabel);
            if (!_node) return null;

            var _maxDepth = ${depthJs};
            var _totalDescendants = 0;

            function _build(n, depth) {
                if (_maxDepth > 0 && depth >= _maxDepth) return null;
                var info = {label: n.getLabel(), name: n.getName(), type: n.className()};
                var children = [];
                for (var i = 0; i < n.getNumNodeChildren(); i++) {
                    _totalDescendants++;
                    var childInfo = _build(n.getNodeChild(i), depth + 1);
                    if (childInfo) children.push(childInfo);
                }
                if (children.length > 0) info.children = children;
                return info;
            }

            var hierarchy = _build(_node, 0);
            return {node: _node.getLabel(), hierarchy: hierarchy, total_descendants: _totalDescendants};
        `);
    const result = (await this.client.execute(script)).value as
      | { node: string; hierarchy: Record<string, unknown> | null; total_descendants: number }
      | null;
    if (result === null) {
      throw new NodeNotFoundError(`Node not found: ${JSON.stringify(opts.root)}`);
    }
    return { node: result.node, hierarchy: result.hierarchy, totalDescendants: result.total_descendants };
  }

  /** Lightweight top-level snapshot: root-level figures, cameras, lights, scene file, and primary selection. Follower figures (parented under another figure) are excluded from `figures`. */
  async overview(): Promise<Record<string, unknown>> {
    const script = ScriptBuilder.iife(`
            var figures = [];
            for (var i = 0; i < Scene.getNumSkeletons(); i++) {
                var s = Scene.getSkeleton(i);
                var parent = s.getNodeParent();
                if (parent && parent.inherits("DzFigure")) continue;
                figures.push({name: s.getName(), label: s.getLabel(), type: s.className()});
            }
            var cameras = [];
            for (var i = 0; i < Scene.getNumCameras(); i++) {
                var c = Scene.getCamera(i);
                cameras.push({name: c.getName(), label: c.getLabel()});
            }
            var lights = [];
            for (var i = 0; i < Scene.getNumLights(); i++) {
                var l = Scene.getLight(i);
                lights.push({name: l.getName(), label: l.getLabel(), type: l.className()});
            }
            var sel = Scene.getPrimarySelection();
            return {
                scene_file: Scene.getFilename(),
                selected_node: sel ? sel.getLabel() : null,
                figures: figures,
                cameras: cameras,
                lights: lights,
                total_nodes: Scene.getNumNodes()
            };
        `);
    return (
      (await this.client.execute(script)).value as Record<string, unknown> | null
    ) ?? { scene_file: "", selected_node: null, figures: [], cameras: [], lights: [], total_nodes: 0 };
  }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd daz-ts && npx vitest run test/unit/scene.test.ts`
Expected: PASS (12 tests total)

- [ ] **Step 5: Commit**

```bash
git add daz-ts/src/scene.ts daz-ts/test/unit/scene.test.ts
git commit -m "feat(daz-ts): add DazScene bulk snapshot methods"
```

---

### Task 14: `UndoGroup`/`withUndo`, `DazClient.sceneSaveCopy`, and `DazScene` part 3 (I/O, playback, undo, dForce)

**Files:**
- Create: `daz-ts/src/undo.ts` (`UndoGroup`, `withUndo`)
- Test: `daz-ts/test/unit/undo.test.ts`
- Modify: `daz-ts/src/client.ts` (add `sceneSaveCopy(path: string): Promise<Record<string, unknown>>`, mirroring the existing `status()`/`health()`/`metrics()` auth-check pattern)
- Modify: `daz-ts/test/unit/client.execute.test.ts` or a new `daz-ts/test/unit/client.sceneSaveCopy.test.ts` (Create) — exact-payload test for the new client method
- Modify: `daz-ts/src/scene.ts` (add I/O/playback/undo/dForce methods to `DazScene`)
- Modify: `daz-ts/test/unit/scene.test.ts` (add a new `describe` block)
- Modify: `daz-ts/src/index.ts` (add `export { UndoGroup, withUndo } from "./undo.js";`)

**Interfaces:**
- Consumes: `DazClient` (Phase 1, extended here), `executeLong` (Phase 1 `polling.ts`), `ScriptRuntimeError` (Phase 1 `exceptions.ts`), `DazNode` (Task 3/6).
- Produces: `class UndoGroup { constructor(client: DazClient, label: string); begin(): Promise<void>; commit(): Promise<void>; cancel(): Promise<void>; }`; `function withUndo<T>(client: DazClient, label: string, fn: () => Promise<T>): Promise<T>`; `DazClient.sceneSaveCopy(path: string): Promise<Record<string, unknown>>`; (added to `DazScene`) `load(path: string): Promise<void>; save(path: string): Promise<void>; saveCopy(path: string): Promise<Record<string,unknown>>; exportFbx(path: string, opts?: {...}): Promise<void>; exportObj(path: string, opts?: {...}): Promise<void>; filename(): Promise<string>; needsSave(): Promise<boolean>; playRange(): Promise<{start:number;end:number}>; setPlayRange(start:number,end:number): Promise<void>; animRange(): Promise<{start:number;end:number}>; setAnimRange(start:number,end:number): Promise<void>; isPlaying(): Promise<boolean>; loopPlayback(on:boolean): Promise<void>; undoLast(): Promise<void>; redoLast(): Promise<void>; isSimulating(): Promise<boolean>; clearDforceSimulation(): Promise<void>; runDforceSimulation(nodes?: DazNode[], opts?: {wait?: boolean; timeout?: number}): Promise<string|null>; frame(): Promise<number>; setFrame(frame:number): Promise<void>; undo<T>(label: string, fn: () => Promise<T>): Promise<T>;` — this closes out `DazScene`'s Phase 2 public surface (`applyInteractionRecipe` is Phase 5 scope; see Global Constraints).

- [ ] **Step 1: Write the failing test for `UndoGroup`/`withUndo`**

```typescript
import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { UndoGroup, withUndo } from "../../src/undo.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}
afterEach(() => vi.unstubAllGlobals());
function stub() {
  const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ success: true, result: null, output: [], request_id: "r", duration_ms: 0 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("UndoGroup", () => {
  it("begin() calls beginUndo(), commit() calls acceptUndo(label)", async () => {
    const fetchMock = stub();
    const group = new UndoGroup(new DazClient({ token: "" }), "Move figure");
    await group.begin();
    await group.commit();
    const scripts = fetchMock.mock.calls.map((c) => JSON.parse(c[1].body as string).script);
    expect(scripts[0]).toContain("beginUndo();");
    expect(scripts[1]).toContain('acceptUndo("Move figure");');
  });

  it("cancel() calls cancelUndo()", async () => {
    const fetchMock = stub();
    const group = new UndoGroup(new DazClient({ token: "" }), "x");
    await group.cancel();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("cancelUndo();");
  });
});

describe("withUndo", () => {
  it("commits on success and returns fn's result", async () => {
    const fetchMock = stub();
    const client = new DazClient({ token: "" });
    const result = await withUndo(client, "Rotate arm", async () => 42);
    expect(result).toBe(42);
    const scripts = fetchMock.mock.calls.map((c) => JSON.parse(c[1].body as string).script);
    expect(scripts[0]).toContain("beginUndo();");
    expect(scripts[1]).toContain('acceptUndo("Rotate arm");');
  });

  it("cancels and rethrows when fn throws", async () => {
    const fetchMock = stub();
    const client = new DazClient({ token: "" });
    await expect(
      withUndo(client, "x", async () => {
        throw new Error("boom");
      }),
    ).rejects.toThrow("boom");
    const scripts = fetchMock.mock.calls.map((c) => JSON.parse(c[1].body as string).script);
    expect(scripts[1]).toContain("cancelUndo();");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/undo.test.ts`
Expected: FAIL with "Cannot find module '../../src/undo.js'"

- [ ] **Step 3: Implement `UndoGroup`/`withUndo`**

```typescript
import type { DazClient } from "./client.js";
import { ScriptBuilder } from "./scriptBuilder.js";

/**
 * Groups DAZ Studio operations into a single undo step. TypeScript has no
 * `with` statement, so this is not a context manager (unlike dazpy's
 * `UndoGroup`) — call {@link begin}, then either {@link commit} or
 * {@link cancel}, or prefer the {@link withUndo} helper / `DazScene.undo()`
 * which does this for you around a callback.
 */
export class UndoGroup {
  private readonly client: DazClient;
  private readonly label: string;

  constructor(client: DazClient, label: string) {
    this.client = client;
    this.label = label;
  }

  async begin(): Promise<void> {
    await this.client.execute(ScriptBuilder.iife("beginUndo();"));
  }

  /** Commit the grouped changes as a single undo step labeled per the constructor. */
  async commit(): Promise<void> {
    await this.client.execute(ScriptBuilder.iife(`acceptUndo(${ScriptBuilder.escapeString(this.label)});`));
  }

  /** Discard the undo grouping (the underlying changes are not reverted; this only cancels the *grouping*, matching dazpy's `cancelUndo()`). */
  async cancel(): Promise<void> {
    await this.client.execute(ScriptBuilder.iife("cancelUndo();"));
  }
}

/**
 * Run `fn` inside an {@link UndoGroup}: `begin()`, then `fn()`, then
 * `commit()` on success or `cancel()` (then rethrow) if `fn` throws —
 * the TS equivalent of dazpy's `with scene.undo(label): ...`.
 */
export async function withUndo<T>(client: DazClient, label: string, fn: () => Promise<T>): Promise<T> {
  const group = new UndoGroup(client, label);
  await group.begin();
  try {
    const result = await fn();
    await group.commit();
    return result;
  } catch (err) {
    await group.cancel();
    throw err;
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd daz-ts && npx vitest run test/unit/undo.test.ts`
Expected: PASS (4 tests)

- [ ] **Step 5: Write the failing test for `DazClient.sceneSaveCopy`**

```typescript
// daz-ts/test/unit/client.sceneSaveCopy.test.ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { AuthenticationError, DazError } from "../../src/exceptions.js";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}
afterEach(() => vi.unstubAllGlobals());

describe("DazClient.sceneSaveCopy", () => {
  it("posts {path} to /scene/save-copy and returns the parsed body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { ok: true, path: "C:/out.duf", source: "copy", method: "copy" }));
    vi.stubGlobal("fetch", fetchMock);
    const client = new DazClient({ token: "" });
    const result = await client.sceneSaveCopy("C:/out.duf");
    expect(result).toEqual({ ok: true, path: "C:/out.duf", source: "copy", method: "copy" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/scene/save-copy");
    expect(JSON.parse(init.body as string)).toEqual({ path: "C:/out.duf" });
  });

  it("throws AuthenticationError on HTTP 401/403", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("no", { status: 403 }));
    vi.stubGlobal("fetch", fetchMock);
    const client = new DazClient({ token: "" });
    await expect(client.sceneSaveCopy("x")).rejects.toBeInstanceOf(AuthenticationError);
  });

  it("throws DazError on other non-2xx statuses, including the server error message", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(500, { error: "disk full" }));
    vi.stubGlobal("fetch", fetchMock);
    const client = new DazClient({ token: "" });
    const err = await client.sceneSaveCopy("x").catch((e) => e);
    expect(err).toBeInstanceOf(DazError);
    expect(err.message).toContain("disk full");
  });
});
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/client.sceneSaveCopy.test.ts`
Expected: FAIL with "client.sceneSaveCopy is not a function"

- [ ] **Step 7: Add `sceneSaveCopy` to `DazClient`**

```typescript
// daz-ts/src/client.ts — extend the exceptions import at the top
import {
  AuthenticationError,
  ConnectionError,
  ConcurrencyLimitError,
  DazBusyError,
  DazError,
  DazTimeoutError,
  ScriptRuntimeError,
  ScriptSyntaxError,
  StudioBusyError,
} from "./exceptions.js";

// ... and add this method inside the DazClient class, near status()/health()/metrics()

  /**
   * Save a copy of the scene to `path` without changing the scene's current
   * file or dirty state (like "Save a Copy As..."). See dazpy's
   * `DazScene.save_copy` for the copy-vs-serialize tradeoff this makes
   * server-side.
   */
  async sceneSaveCopy(path: string): Promise<Record<string, unknown>> {
    const resp = await this.post("/scene/save-copy", { path });
    if (resp.status === 401 || resp.status === 403) {
      throw new AuthenticationError(`HTTP ${resp.status}: ${(await resp.text()).slice(0, 200)}`);
    }
    if (!resp.ok) {
      const body = (await resp.json().catch(() => ({}))) as Record<string, unknown>;
      const msg = (body.error as string) ?? (body.detail as string) ?? `HTTP ${resp.status}`;
      throw new DazError(`sceneSaveCopy failed (${resp.status}): ${msg}`);
    }
    return (await resp.json()) as Record<string, unknown>;
  }
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd daz-ts && npx vitest run test/unit/client.sceneSaveCopy.test.ts`
Expected: PASS (3 tests)

- [ ] **Step 9: Commit `UndoGroup`/`withUndo`/`sceneSaveCopy`**

```typescript
// daz-ts/src/index.ts
export { UndoGroup, withUndo } from "./undo.js";
```

```bash
git add daz-ts/src/undo.ts daz-ts/src/client.ts daz-ts/test/unit/undo.test.ts daz-ts/test/unit/client.sceneSaveCopy.test.ts daz-ts/src/index.ts
git commit -m "feat(daz-ts): add UndoGroup/withUndo and DazClient.sceneSaveCopy"
```

- [ ] **Step 10: Write the failing test for `DazScene` I/O/playback/undo/dForce**

```typescript
// Append to daz-ts/test/unit/scene.test.ts
import { UndoGroup } from "../../src/undo.js";

describe("DazScene I/O, playback, undo, dForce", () => {
  it("load() calls Scene.loadScene(path, 0) in merge mode", async () => {
    const fetchMock = stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    await scene.load("C:/scene.duf");
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain('Scene.loadScene("C:/scene.duf", 0);');
  });

  it("playRange() converts DzTimeRange ticks to frames via getTimeStep()", async () => {
    stubSeq({ start: 0, end: 90 });
    const scene = new DazScene(new DazClient({ token: "" }));
    expect(await scene.playRange()).toEqual({ start: 0, end: 90 });
  });

  it("setPlayRange multiplies frame numbers by Scene.getTimeStep()", async () => {
    const fetchMock = stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    await scene.setPlayRange(0, 30);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("new DzTimeRange(0 * step, 30 * step)");
  });

  it("undo() delegates to withUndo, committing on success", async () => {
    const fetchMock = stubSeq(null, null);
    const scene = new DazScene(new DazClient({ token: "" }));
    const result = await scene.undo("Move figure", async () => "done");
    expect(result).toBe("done");
    const scripts = fetchMock.mock.calls.map((c) => JSON.parse(c[1].body as string).script);
    expect(scripts[0]).toContain("beginUndo();");
    expect(scripts[1]).toContain('acceptUndo("Move figure");');
  });

  it("runDforceSimulation(wait: false) submits async and returns the requestId without polling", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ request_id: "job-1" }));
    vi.stubGlobal("fetch", fetchMock);
    const scene = new DazScene(new DazClient({ token: "" }));
    const requestId = await scene.runDforceSimulation(undefined, { wait: false });
    expect(requestId).toBe("job-1");
    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain("/execute/async");
  });
});
```

- [ ] **Step 11: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/scene.test.ts`
Expected: FAIL — `scene.load is not a function`

- [ ] **Step 12: Add the I/O/playback/undo/dForce methods to `DazScene`**

```typescript
// Add these imports at the top of daz-ts/src/scene.ts
import { executeLong } from "./polling.js";
import { ScriptRuntimeError } from "./exceptions.js";
import { withUndo } from "./undo.js";

// ... and these methods inside the DazScene class, after overview()

  private async exportViaNativeExporter(exporterClass: string, path: string, overrides: Record<string, unknown>): Promise<void> {
    const settingsCalls: string[] = [];
    for (const [key, value] of Object.entries(overrides)) {
      const jsKey = JSON.stringify(key);
      if (typeof value === "boolean") {
        settingsCalls.push(`settings.setBoolValue(${jsKey}, ${value ? "true" : "false"});`);
      } else if (Number.isInteger(value)) {
        settingsCalls.push(`settings.setIntValue(${jsKey}, ${value});`);
      } else if (typeof value === "number") {
        settingsCalls.push(`settings.setFloatValue(${jsKey}, ${value});`);
      } else {
        settingsCalls.push(`settings.setStringValue(${jsKey}, ${JSON.stringify(String(value))});`);
      }
    }
    const script = ScriptBuilder.iife(`
            var mgr = App.getExportMgr();
            var exp = mgr.findExporterByClassName(${JSON.stringify(exporterClass)});
            if (!exp) return;
            var settings = new DzFileIOSettings();
            exp.getDefaultOptions(settings);
            ${settingsCalls.join(" ")}
            exp.writeFile(${JSON.stringify(path)}, settings);
        `);
    await this.client.execute(script);
  }

  /** Load a scene file (merge mode — does not clear the existing scene). `path` is an absolute path on the server host. */
  async load(path: string): Promise<void> {
    await this.client.execute(ScriptBuilder.iife(`Scene.loadScene(${ScriptBuilder.escapeString(path)}, 0);`));
  }

  /** Save the scene to `path` (absolute path on the server host). */
  async save(path: string): Promise<void> {
    await this.client.execute(ScriptBuilder.iife(`Scene.saveScene(${ScriptBuilder.escapeString(path)});`));
  }

  /** Save a copy of the scene without changing its current file or dirty state. See `DazClient.sceneSaveCopy` for the copy-vs-serialize tradeoff. */
  async saveCopy(path: string): Promise<Record<string, unknown>> {
    return this.client.sceneSaveCopy(path);
  }

  /** Export the scene to FBX via DAZ Studio's built-in `DzFbxExporter` (synchronous — no async job to poll, unlike `DazClient.exportUsdSubmit`). */
  async exportFbx(
    path: string,
    opts: {
      selectedOnly?: boolean;
      includeFigures?: boolean;
      includeProps?: boolean;
      includeLights?: boolean;
      includeCameras?: boolean;
      includeAnimations?: boolean;
      embedTextures?: boolean;
      options?: Record<string, unknown>;
    } = {},
  ): Promise<void> {
    const overrides: Record<string, unknown> = {
      IncludeSelectedOnly: opts.selectedOnly ?? false,
      IncludeFigures: opts.includeFigures ?? true,
      IncludeProps: opts.includeProps ?? false,
      IncludeLights: opts.includeLights ?? false,
      IncludeCameras: opts.includeCameras ?? false,
      IncludeAnimations: opts.includeAnimations ?? false,
      EmbedTextures: opts.embedTextures ?? true,
      ...opts.options,
      RunSilent: 1,
    };
    await this.exportViaNativeExporter("DzFbxExporter", path, overrides);
  }

  /** Export the scene to OBJ via DAZ Studio's built-in `DzObjExporter` (synchronous, see {@link exportFbx}). */
  async exportObj(
    path: string,
    opts: {
      selectedOnly?: boolean;
      ignoreInvisible?: boolean;
      includeNormals?: boolean;
      collectMaps?: boolean;
      options?: Record<string, unknown>;
    } = {},
  ): Promise<void> {
    const overrides: Record<string, unknown> = {
      SelectedOnly: opts.selectedOnly ?? false,
      IgnoreInvisible: opts.ignoreInvisible ?? true,
      WriteVN: opts.includeNormals ?? false,
      CollectMaps: opts.collectMaps ?? false,
      ...opts.options,
      RunSilent: 1,
    };
    await this.exportViaNativeExporter("DzObjExporter", path, overrides);
  }

  async filename(): Promise<string> {
    return ((await this.client.execute(ScriptBuilder.iife("return Scene.getFilename();"))).value as string) ?? "";
  }

  async needsSave(): Promise<boolean> {
    return Boolean((await this.client.execute(ScriptBuilder.iife("return Scene.needsSave();"))).value);
  }

  /** Playback range as `{start, end}` in frames. */
  async playRange(): Promise<{ start: number; end: number }> {
    const script = ScriptBuilder.iife(
      "var r = Scene.getPlayRange(); var step = Scene.getTimeStep(); return {start: Math.round(r.start / step), end: Math.round(r.end / step)};",
    );
    return ((await this.client.execute(script)).value as { start: number; end: number }) ?? { start: 0, end: 0 };
  }

  async setPlayRange(start: number, end: number): Promise<void> {
    const script = ScriptBuilder.iife(
      `var step = Scene.getTimeStep();Scene.setPlayRange(new DzTimeRange(${Math.trunc(start)} * step, ${Math.trunc(
        end,
      )} * step));`,
    );
    await this.client.execute(script);
  }

  /** Animation range as `{start, end}` in frames. */
  async animRange(): Promise<{ start: number; end: number }> {
    const script = ScriptBuilder.iife(
      "var r = Scene.getAnimRange(); var step = Scene.getTimeStep(); return {start: Math.round(r.start / step), end: Math.round(r.end / step)};",
    );
    return ((await this.client.execute(script)).value as { start: number; end: number }) ?? { start: 0, end: 0 };
  }

  async setAnimRange(start: number, end: number): Promise<void> {
    const script = ScriptBuilder.iife(
      `var step = Scene.getTimeStep();Scene.setAnimRange(new DzTimeRange(${Math.trunc(start)} * step, ${Math.trunc(
        end,
      )} * step));`,
    );
    await this.client.execute(script);
  }

  async isPlaying(): Promise<boolean> {
    return Boolean((await this.client.execute(ScriptBuilder.iife("return Scene.isPlaying();"))).value);
  }

  async loopPlayback(on: boolean): Promise<void> {
    await this.client.execute(ScriptBuilder.iife(`Scene.loopPlayback(${on ? "true" : "false"});`));
  }

  /** Step back one level in DAZ Studio's undo stack (the *global* stack — use {@link undo} to group a series of changes instead). */
  async undoLast(): Promise<void> {
    await this.client.execute(ScriptBuilder.iife("App.getUndoStack().undo();"));
  }

  async redoLast(): Promise<void> {
    await this.client.execute(ScriptBuilder.iife("App.getUndoStack().redo();"));
  }

  async isSimulating(): Promise<boolean> {
    return Boolean((await this.client.execute(ScriptBuilder.iife("return App.getSimulationMgr().isSimulating();"))).value);
  }

  async clearDforceSimulation(): Promise<void> {
    await this.client.execute(ScriptBuilder.iife("App.getSimulationMgr().clearSimulation();"));
  }

  /**
   * Run a dForce simulation. `nodes` omitted simulates the whole scene via
   * `DzSimulationMgr.simulate()` (follows the configured Simulation
   * Settings frame range); `nodes` provided runs `customSimulate()` on
   * that subset via the active engine.
   * @param wait When `true` (default), block (via the async execute-and-poll endpoint, since dForce runs can take minutes) until finished, returning `null`. When `false`, submit and return the `requestId` immediately.
   * @throws ScriptRuntimeError if the simulation engine reports an error (only when `wait` is `true`).
   */
  async runDforceSimulation(nodes?: DazNode[], opts: { wait?: boolean; timeout?: number } = {}): Promise<string | null> {
    const { wait = true, timeout = 300.0 } = opts;
    let body: string;
    if (nodes && nodes.length > 0) {
      const nodeExprs = nodes.map((n) => ScriptBuilder.findNodeExpr(n.identifier)).join(",");
      body = `
                var mgr = App.getSimulationMgr();
                var engine = mgr.getActiveSimulationEngine();
                if (!engine) return {"error": "no_active_engine"};
                var err = engine.customSimulate([${nodeExprs}]);
                return {"error": err ? String(err) : null};
            `;
    } else {
      body = `
                var mgr = App.getSimulationMgr();
                var err = mgr.simulate();
                return {"error": err ? String(err) : null};
            `;
    }
    const script = ScriptBuilder.iife(body);

    if (!wait) {
      return this.client.executeAsyncSubmit(script);
    }

    const result = await executeLong(this.client, script, undefined, { timeoutMs: timeout * 1000 });
    const data = (result.value as { error: string | null } | null) ?? { error: null };
    if (data.error) {
      throw new ScriptRuntimeError(`dForce simulation failed: ${data.error}`);
    }
    return null;
  }

  async frame(): Promise<number> {
    return ((await this.client.execute(ScriptBuilder.iife("return Scene.getFrame();"))).value as number) ?? 0;
  }

  async setFrame(frame: number): Promise<void> {
    await this.client.execute(ScriptBuilder.iife(`Scene.setFrame(${Math.trunc(frame)});`));
  }

  /**
   * Run `fn` with all its changes grouped into a single undo step labeled
   * `label` (see {@link withUndo}). TS equivalent of dazpy's
   * `with scene.undo(label): ...` context manager.
   */
  async undo<T>(label: string, fn: () => Promise<T>): Promise<T> {
    return withUndo(this.client, label, fn);
  }
```

**@remarks note on `DazScene`:** add a TSDoc `@remarks` block to the `DazScene` class comment: `applyInteractionRecipe()` (dazpy's multi-figure IK recipe application) is Phase 5 scope (`daz-script-server-sf7y`), not implemented here.

- [ ] **Step 13: Run test to verify it passes**

Run: `cd daz-ts && npx vitest run test/unit/scene.test.ts`
Expected: PASS (17 tests total)

- [ ] **Step 14: Run the full unit suite so far and commit**

```bash
cd daz-ts && npx vitest run test/unit
git add daz-ts/src/scene.ts daz-ts/test/unit/scene.test.ts
git commit -m "feat(daz-ts): add DazScene I/O, playback, undo, and dForce simulation methods"
```

---

### Task 15: `DazGeometry`

**Files:**
- Create: `daz-ts/src/geometry.ts`
- Test: `daz-ts/test/unit/geometry.test.ts`
- Modify: `daz-ts/src/index.ts` (add `export { DazGeometry } from "./geometry.js";`)

**Interfaces:**
- Consumes: `DazElement` (Task 1), `NodeIdentifier`/`ScriptBuilder.findNodeExpr` (Task 3), `Vec3`/`BoundingBox` (Phase 1 `math3.ts`).
- Produces: `class DazGeometry extends DazElement { constructor(client: DazClient, identifier: NodeIdentifier); vertexCount(): Promise<number|null>; facetCount(): Promise<number|null>; vertexPositions(start?: number, count?: number): Promise<{total:number;start:number;count:number;vertices:number[][]}>; vertexPositionsAll(chunkSize?: number): Promise<number[][]>; faceVertexIndices(start?: number, count?: number): Promise<{total:number;start:number;facets:number[][]}>; faceVertexIndicesAll(chunkSize?: number): Promise<number[][]>; normals(start?: number, count?: number): Promise<{total:number;start:number;normals:number[][]}>; normalsAll(chunkSize?: number): Promise<number[][]>; uvSetCount(): Promise<number|null>; uvPositions(uvSet?: number, start?: number, count?: number): Promise<{total:number;start:number;uvs:number[][]}>; uvPositionsAll(uvSet?: number, chunkSize?: number): Promise<number[][]>; faceGroupNames(): Promise<Array<string|null>>; materialGroupNames(): Promise<Array<string|null>>; subdivisionLevel(): Promise<number|null>; vertexPositionsPosed(start?: number, count?: number): Promise<{total:number;start:number;count:number;vertices:number[][]}>; vertexPositionsPosedAll(chunkSize?: number): Promise<number[][]>; trisCount(): Promise<number|null>; quadsCount(): Promise<number|null>; meshInfo(): Promise<Record<string,unknown>|null>; boundingBox(): Promise<BoundingBox|null>; boundingBoxPosed(): Promise<BoundingBox|null>; faceGroupFaces(name: string): Promise<number[]>; materialGroupFaces(name: string): Promise<number[]>; static triangulate(faces: number[][]): number[][]; static asVec3(vertices: number[][]): Vec3[]; }`

**Excluded (see Global Constraints):** dazpy's `capture_sprite`-adjacent background-removal path lives on `DazViewport`, not `DazGeometry` — no exclusions here; this task is a complete, faithful port of `_geometry.py`.

- [ ] **Step 1: Write the failing test for vertex/facet counts and chunked/paginated vertex access**

```typescript
import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazGeometry } from "../../src/geometry.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}
afterEach(() => vi.unstubAllGlobals());
function stubSeq(...values: unknown[]) {
  const fetchMock = vi.fn();
  for (const v of values) fetchMock.mockResolvedValueOnce(jsonResponse({ success: true, result: v, output: [], request_id: "r", duration_ms: 0 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("DazGeometry counts and chunked vertex access", () => {
  it("constructor builds a locator via getObject().getCurrentShape().getGeometry()", async () => {
    const fetchMock = stubSeq(5000);
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await geo.vertexCount();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("sh.getGeometry()");
    expect(script).toContain('Scene.findNode("Genesis9")');
  });

  it("vertexPositionsAll paginates until it has consumed the reported total", async () => {
    stubSeq(
      { total: 3, start: 0, count: 2, vertices: [[0, 0, 0], [1, 1, 1]] },
      { total: 3, start: 2, count: 1, vertices: [[2, 2, 2]] },
    );
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const all = await geo.vertexPositionsAll(2);
    expect(all).toEqual([[0, 0, 0], [1, 1, 1], [2, 2, 2]]);
  });

  it("vertexPositionsAll stops early if a chunk returns no vertices, even under the reported total", async () => {
    stubSeq({ total: 10, start: 0, count: 0, vertices: [] });
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await geo.vertexPositionsAll(5)).toEqual([]);
  });
});

describe("DazGeometry.triangulate / .asVec3 (pure functions, no HTTP)", () => {
  it("triangulate splits quads along the 0-2 diagonal and passes triangles through unchanged", () => {
    expect(DazGeometry.triangulate([[0, 1, 2, 3], [4, 5, 6]])).toEqual([
      [0, 1, 2],
      [0, 2, 3],
      [4, 5, 6],
    ]);
  });

  it("triangulate silently skips faces with any other vertex count", () => {
    expect(DazGeometry.triangulate([[0, 1]])).toEqual([]);
  });

  it("asVec3 wraps [x,y,z] arrays as Vec3 instances", () => {
    const vecs = DazGeometry.asVec3([[1, 2, 3]]);
    expect(vecs[0]).toEqual({ x: 1, y: 2, z: 3 });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/geometry.test.ts`
Expected: FAIL with "Cannot find module '../../src/geometry.js'"

- [ ] **Step 3: Implement `DazGeometry`'s constructor, counts, and chunked/paginated vertex access**

```typescript
import type { DazClient } from "./client.js";
import { DazElement } from "./element.js";
import { BoundingBox, Vec3 } from "./math3.js";
import type { NodeIdentifier } from "./node.js";
import { ScriptBuilder } from "./scriptBuilder.js";

/** Chunked access to vertices, faces, normals, UV sets, and face/material groups for a node's current shape's geometry. */
export class DazGeometry extends DazElement {
  constructor(client: DazClient, identifier: NodeIdentifier) {
    const locator = `(function(){` +
      `var n = ${ScriptBuilder.findNodeExpr(identifier)};` +
      `if (!n) return null;` +
      `var obj = n.getObject();` +
      `if (!obj) return null;` +
      `var sh = obj.getCurrentShape();` +
      `return sh ? sh.getGeometry() : null;` +
      `})()`;
    super(client, locator);
  }

  async vertexCount(): Promise<number | null> {
    return (await this.client.execute(ScriptBuilder.iife(`var g = ${this.locator}; return g ? g.getNumVertices() : null;`)))
      .value as number | null;
  }

  async facetCount(): Promise<number | null> {
    return (await this.client.execute(ScriptBuilder.iife(`var g = ${this.locator}; return g ? g.getNumFacets() : null;`)))
      .value as number | null;
  }

  /** One chunk of vertex positions. `start`/`count` default to `0`/`5000`. */
  async vertexPositions(start = 0, count = 5000): Promise<{ total: number; start: number; count: number; vertices: number[][] }> {
    const script = ScriptBuilder.iife(`
            var g = ${this.locator};
            if (!g) return null;
            var total = g.getNumVertices();
            var end = Math.min(${start} + ${count}, total);
            var verts = [];
            for (var i = ${start}; i < end; i++) {
                var v = g.getVertex(i);
                verts.push([v.x, v.y, v.z]);
            }
            return {total: total, start: ${start}, count: verts.length, vertices: verts};
        `);
    return ((await this.client.execute(script)).value as { total: number; start: number; count: number; vertices: number[][] }) ?? {
      total: 0,
      start,
      count: 0,
      vertices: [],
    };
  }

  /** Every vertex position, auto-paginating by `chunkSize` (default `5000`). */
  async vertexPositionsAll(chunkSize = 5000): Promise<number[][]> {
    const first = await this.vertexPositions(0, chunkSize);
    const total = first.total;
    const all = [...first.vertices];
    let offset = all.length;
    while (offset < total) {
      const chunk = await this.vertexPositions(offset, chunkSize);
      if (chunk.vertices.length === 0) break;
      all.push(...chunk.vertices);
      offset += chunk.vertices.length;
    }
    return all;
  }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd daz-ts && npx vitest run test/unit/geometry.test.ts`
Expected: PASS (6 tests — the `triangulate`/`asVec3` cases fail until Step 7's static methods land; run again after Step 7)

- [ ] **Step 5: Write the failing test for face/normal/UV chunked access and group names**

```typescript
// Append to daz-ts/test/unit/geometry.test.ts
describe("DazGeometry faces/normals/UVs/groups", () => {
  it("faceVertexIndices returns a quad as [v0,v1,v2,v3] and a tri as [v0,v1,v2]", async () => {
    stubSeq({ total: 2, start: 0, facets: [[0, 1, 2, 3], [4, 5, 6]] });
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const result = await geo.faceVertexIndices(0, 1000);
    expect(result.facets).toEqual([[0, 1, 2, 3], [4, 5, 6]]);
  });

  it("uvPositions defaults to uvSet 0 using g.getUVs() rather than g.getUVSet(0)", async () => {
    const fetchMock = stubSeq({ total: 0, start: 0, uvs: [] });
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await geo.uvPositions();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("g.getUVs()");
  });

  it("faceGroupFaces returns [] when the named group does not exist", async () => {
    stubSeq([]);
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await geo.faceGroupFaces("Missing")).toEqual([]);
  });
});
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/geometry.test.ts`
Expected: FAIL — `geo.faceVertexIndices is not a function`

- [ ] **Step 7: Add faces/normals/UVs/groups/subdivision, mesh_info, bounding boxes, and the pure static helpers**

```typescript
// Add inside the DazGeometry class body, after vertexPositionsAll()

  /** One chunk of face vertex indices; each entry is `[v0,v1,v2]` (tri) or `[v0,v1,v2,v3]` (quad). `start`/`count` default `0`/`1000`. */
  async faceVertexIndices(start = 0, count = 1000): Promise<{ total: number; start: number; facets: number[][] }> {
    const script = ScriptBuilder.iife(`
            var g = ${this.locator};
            if (!g) return null;
            var total = g.getNumFacets();
            var end = Math.min(${start} + ${count}, total);
            var facets = [];
            for (var i = ${start}; i < end; i++) {
                var f = g.getFacet(i);
                if (f.isQuad()) {
                    facets.push([f.vertIdx1, f.vertIdx2, f.vertIdx3, f.vertIdx4]);
                } else {
                    facets.push([f.vertIdx1, f.vertIdx2, f.vertIdx3]);
                }
            }
            return {total: total, start: ${start}, facets: facets};
        `);
    return ((await this.client.execute(script)).value as { total: number; start: number; facets: number[][] }) ?? {
      total: 0,
      start,
      facets: [],
    };
  }

  /** Every face's vertex indices, auto-paginating by `chunkSize` (default `1000`). */
  async faceVertexIndicesAll(chunkSize = 1000): Promise<number[][]> {
    const first = await this.faceVertexIndices(0, chunkSize);
    const all = [...first.facets];
    let offset = all.length;
    while (offset < first.total) {
      const chunk = await this.faceVertexIndices(offset, chunkSize);
      if (chunk.facets.length === 0) break;
      all.push(...chunk.facets);
      offset += chunk.facets.length;
    }
    return all;
  }

  /** One chunk of face normals. `start`/`count` default `0`/`5000`. */
  async normals(start = 0, count = 5000): Promise<{ total: number; start: number; normals: number[][] }> {
    const script = ScriptBuilder.iife(`
            var g = ${this.locator};
            if (!g) return null;
            var total = g.getNumNormals ? g.getNumNormals() : 0;
            var end = Math.min(${start} + ${count}, total);
            var norms = [];
            for (var i = ${start}; i < end; i++) {
                var n = g.getNormal(i);
                norms.push([n.x, n.y, n.z]);
            }
            return {total: total, start: ${start}, normals: norms};
        `);
    return ((await this.client.execute(script)).value as { total: number; start: number; normals: number[][] }) ?? {
      total: 0,
      start,
      normals: [],
    };
  }

  /** Every face normal, auto-paginating by `chunkSize` (default `5000`). */
  async normalsAll(chunkSize = 5000): Promise<number[][]> {
    const first = await this.normals(0, chunkSize);
    const all = [...first.normals];
    let offset = all.length;
    while (offset < first.total) {
      const chunk = await this.normals(offset, chunkSize);
      if (chunk.normals.length === 0) break;
      all.push(...chunk.normals);
      offset += chunk.normals.length;
    }
    return all;
  }

  async uvSetCount(): Promise<number | null> {
    return (await this.client.execute(ScriptBuilder.iife(`var g = ${this.locator}; return g ? g.getNumUVSets() : null;`)))
      .value as number | null;
  }

  /** One chunk of UV coordinates for `uvSet` (default `0`, the primary set uses `g.getUVs()` rather than `g.getUVSet(0)`). */
  async uvPositions(uvSet = 0, start = 0, count = 5000): Promise<{ total: number; start: number; uvs: number[][] }> {
    const script = ScriptBuilder.iife(`
            var g = ${this.locator};
            if (!g) return null;
            var uvMap = (${uvSet} === 0) ? g.getUVs() : g.getUVSet(${uvSet});
            if (!uvMap) return null;
            var total = uvMap.getNumValues();
            var end = Math.min(${start} + ${count}, total);
            var uvs = [];
            for (var i = ${start}; i < end; i++) {
                var p = uvMap.getPnt2Vec(i);
                uvs.push([p.x, p.y]);
            }
            return {total: total, start: ${start}, uvs: uvs};
        `);
    return ((await this.client.execute(script)).value as { total: number; start: number; uvs: number[][] }) ?? {
      total: 0,
      start,
      uvs: [],
    };
  }

  /** Every UV coordinate for `uvSet`, auto-paginating by `chunkSize` (default `5000`). */
  async uvPositionsAll(uvSet = 0, chunkSize = 5000): Promise<number[][]> {
    const first = await this.uvPositions(uvSet, 0, chunkSize);
    const all = [...first.uvs];
    let offset = all.length;
    while (offset < first.total) {
      const chunk = await this.uvPositions(uvSet, offset, chunkSize);
      if (chunk.uvs.length === 0) break;
      all.push(...chunk.uvs);
      offset += chunk.uvs.length;
    }
    return all;
  }

  async faceGroupNames(): Promise<Array<string | null>> {
    const script = ScriptBuilder.iife(`
            var g = ${this.locator};
            if (!g || !g.getNumFaceGroups) return [];
            var n = g.getNumFaceGroups();
            var names = [];
            for (var i = 0; i < n; i++) {
                var grp = g.getFaceGroup(i);
                names.push(grp ? grp.getName() : null);
            }
            return names;
        `);
    return ((await this.client.execute(script)).value as Array<string | null>) ?? [];
  }

  async materialGroupNames(): Promise<Array<string | null>> {
    const script = ScriptBuilder.iife(`
            var g = ${this.locator};
            if (!g || !g.getNumMaterialGroups) return [];
            var n = g.getNumMaterialGroups();
            var names = [];
            for (var i = 0; i < n; i++) {
                var grp = g.getMaterialGroup(i);
                names.push(grp ? grp.getName() : null);
            }
            return names;
        `);
    return ((await this.client.execute(script)).value as Array<string | null>) ?? [];
  }

  /** Current subdivision level (`0` = base mesh, read-only). */
  async subdivisionLevel(): Promise<number | null> {
    const script = ScriptBuilder.iife(
      `var g = ${this.locator}; return (g && g.getCurrentSubDivisionLevel) ? g.getCurrentSubDivisionLevel() : null;`,
    );
    return (await this.client.execute(script)).value as number | null;
  }

  /** One chunk of fully-deformed world-space vertex positions (post morph-and-skinning), via `DzObject.getCachedGeom()`. */
  async vertexPositionsPosed(
    start = 0,
    count = 5000,
  ): Promise<{ total: number; start: number; count: number; vertices: number[][] }> {
    // identifier is not stored on DazGeometry (only the resolved geometry locator is); re-derive the owning node's
    // find-node expression from the locator built in the constructor is not possible here, so this method needs the
    // identifier retained as a private field — see the constructor amendment below.
    const script = ScriptBuilder.iife(`
            var n = ${this.nodeExpr};
            if (!n) return null;
            var obj = n.getObject();
            if (!obj) return null;
            obj.forceCacheUpdate(n, false);
            var cached = obj.getCachedGeom();
            if (!cached) return null;
            var total = cached.getNumVertices();
            var end = Math.min(${start} + ${count}, total);
            var verts = [];
            for (var i = ${start}; i < end; i++) {
                var v = cached.getVertex(i);
                verts.push([v.x, v.y, v.z]);
            }
            return {total: total, start: ${start}, count: verts.length, vertices: verts};
        `);
    return ((await this.client.execute(script)).value as {
      total: number;
      start: number;
      count: number;
      vertices: number[][];
    }) ?? { total: 0, start, count: 0, vertices: [] };
  }

  /** Every world-space posed+morphed vertex position, auto-paginating by `chunkSize` (default `5000`). */
  async vertexPositionsPosedAll(chunkSize = 5000): Promise<number[][]> {
    const first = await this.vertexPositionsPosed(0, chunkSize);
    const all = [...first.vertices];
    let offset = all.length;
    while (offset < first.total) {
      const chunk = await this.vertexPositionsPosed(offset, chunkSize);
      if (chunk.vertices.length === 0) break;
      all.push(...chunk.vertices);
      offset += chunk.vertices.length;
    }
    return all;
  }

  async trisCount(): Promise<number | null> {
    const script = ScriptBuilder.iife(`var g = ${this.locator}; return (g && g.getNumTris) ? g.getNumTris() : null;`);
    return (await this.client.execute(script)).value as number | null;
  }

  async quadsCount(): Promise<number | null> {
    const script = ScriptBuilder.iife(`var g = ${this.locator}; return (g && g.getNumQuads) ? g.getNumQuads() : null;`);
    return (await this.client.execute(script)).value as number | null;
  }

  /** All mesh metadata (vertex/facet/tri/quad counts, subdivision level, UV set count, group names) in a single HTTP call, instead of 7+ separate reads. */
  async meshInfo(): Promise<Record<string, unknown> | null> {
    const script = ScriptBuilder.iife(`
            var g = ${this.locator};
            if (!g) return null;
            var fgNames = [];
            if (g.getNumFaceGroups) {
                for (var i = 0; i < g.getNumFaceGroups(); i++) {
                    var fg = g.getFaceGroup(i);
                    fgNames.push(fg ? fg.getName() : null);
                }
            }
            var mgNames = [];
            if (g.getNumMaterialGroups) {
                for (var i = 0; i < g.getNumMaterialGroups(); i++) {
                    var mg = g.getMaterialGroup(i);
                    mgNames.push(mg ? mg.getName() : null);
                }
            }
            return {
                vertex_count:         g.getNumVertices(),
                facet_count:          g.getNumFacets(),
                tris_count:           g.getNumTris           ? g.getNumTris()                  : null,
                quads_count:          g.getNumQuads          ? g.getNumQuads()                 : null,
                subdivision_level:    g.getCurrentSubDivisionLevel ? g.getCurrentSubDivisionLevel() : null,
                uv_set_count:         g.getNumUVSets         ? g.getNumUVSets()                : null,
                face_group_names:     fgNames,
                material_group_names: mgNames
            };
        `);
    return (await this.client.execute(script)).value as Record<string, unknown> | null;
  }

  /** Axis-aligned bounding box of the base mesh, computed server-side in one HTTP call. `null` if unavailable or empty. */
  async boundingBox(): Promise<BoundingBox | null> {
    const script = ScriptBuilder.iife(`
            var g = ${this.locator};
            if (!g || g.getNumVertices() === 0) return null;
            var v = g.getVertex(0);
            var mnX = v.x, mnY = v.y, mnZ = v.z;
            var mxX = v.x, mxY = v.y, mxZ = v.z;
            var n = g.getNumVertices();
            for (var i = 1; i < n; i++) {
                v = g.getVertex(i);
                if (v.x < mnX) mnX = v.x; else if (v.x > mxX) mxX = v.x;
                if (v.y < mnY) mnY = v.y; else if (v.y > mxY) mxY = v.y;
                if (v.z < mnZ) mnZ = v.z; else if (v.z > mxZ) mxZ = v.z;
            }
            return {min: {x:mnX, y:mnY, z:mnZ}, max: {x:mxX, y:mxY, z:mxZ}};
        `);
    const result = (await this.client.execute(script)).value as
      | { min: { x: number; y: number; z: number }; max: { x: number; y: number; z: number } }
      | null;
    if (result === null) return null;
    return BoundingBox.fromDict(result);
  }

  /** AABB of the world-space posed-and-morphed mesh (after forcing a cache update), in one HTTP call. */
  async boundingBoxPosed(): Promise<BoundingBox | null> {
    const script = ScriptBuilder.iife(`
            var _nd = ${this.nodeExpr};
            if (!_nd) return null;
            var obj = _nd.getObject();
            if (!obj) return null;
            obj.forceCacheUpdate(_nd, false);
            var g = obj.getCachedGeom();
            if (!g || g.getNumVertices() === 0) return null;
            var v = g.getVertex(0);
            var mnX = v.x, mnY = v.y, mnZ = v.z;
            var mxX = v.x, mxY = v.y, mxZ = v.z;
            var n = g.getNumVertices();
            for (var i = 1; i < n; i++) {
                v = g.getVertex(i);
                if (v.x < mnX) mnX = v.x; else if (v.x > mxX) mxX = v.x;
                if (v.y < mnY) mnY = v.y; else if (v.y > mxY) mxY = v.y;
                if (v.z < mnZ) mnZ = v.z; else if (v.z > mxZ) mxZ = v.z;
            }
            return {min: {x:mnX, y:mnY, z:mnZ}, max: {x:mxX, y:mxY, z:mxZ}};
        `);
    const result = (await this.client.execute(script)).value as
      | { min: { x: number; y: number; z: number }; max: { x: number; y: number; z: number } }
      | null;
    if (result === null) return null;
    return BoundingBox.fromDict(result);
  }

  /** Face indices belonging to the named face group, or `[]` if it doesn't exist. */
  async faceGroupFaces(name: string): Promise<number[]> {
    const nameJs = ScriptBuilder.escapeString(name);
    const script = ScriptBuilder.iife(`
            var g = ${this.locator};
            if (!g || !g.getNumFaceGroups) return [];
            for (var i = 0; i < g.getNumFaceGroups(); i++) {
                var grp = g.getFaceGroup(i);
                if (grp && grp.getName() === ${nameJs}) {
                    var idx = [];
                    for (var j = 0; j < grp.count(); j++) idx.push(grp.getIndexAt(j));
                    return idx;
                }
            }
            return [];
        `);
    return ((await this.client.execute(script)).value as number[]) ?? [];
  }

  /** Face indices belonging to the named material group, or `[]` if it doesn't exist. */
  async materialGroupFaces(name: string): Promise<number[]> {
    const nameJs = ScriptBuilder.escapeString(name);
    const script = ScriptBuilder.iife(`
            var g = ${this.locator};
            if (!g || !g.getNumMaterialGroups) return [];
            for (var i = 0; i < g.getNumMaterialGroups(); i++) {
                var grp = g.getMaterialGroup(i);
                if (grp && grp.getName() === ${nameJs}) {
                    var idx = [];
                    for (var j = 0; j < grp.count(); j++) idx.push(grp.getIndexAt(j));
                    return idx;
                }
            }
            return [];
        `);
    return ((await this.client.execute(script)).value as number[]) ?? [];
  }

  /**
   * Convert face index arrays (tris or quads) to all-triangles. Quads split
   * along the 0->2 diagonal (`[v0,v1,v2,v3]` -> `[v0,v1,v2]` + `[v0,v2,v3]`).
   * Faces with any other vertex count are silently skipped. Pure function — no HTTP round-trip.
   */
  static triangulate(faces: number[][]): number[][] {
    const result: number[][] = [];
    for (const f of faces) {
      if (f.length === 3) {
        result.push([...f]);
      } else if (f.length === 4) {
        result.push([f[0], f[1], f[2]]);
        result.push([f[0], f[2], f[3]]);
      }
    }
    return result;
  }

  /** Wrap `[[x,y,z], ...]` vertex data as {@link Vec3} instances. Pure function — no HTTP round-trip. */
  static asVec3(vertices: number[][]): Vec3[] {
    return vertices.map((v) => Vec3.fromList(v));
  }
```

`vertexPositionsPosed`/`boundingBoxPosed` need the owning node's `Scene.findNode(...)`-style expression (`nodeExpr`), which isn't derivable from the already-built geometry `locator` — go back and amend the constructor from Step 3 to retain it as a private field:

```typescript
// Amend the constructor written in Step 3:
export class DazGeometry extends DazElement {
  private readonly nodeExpr: string;

  constructor(client: DazClient, identifier: NodeIdentifier) {
    const nodeExpr = ScriptBuilder.findNodeExpr(identifier);
    const locator = `(function(){` +
      `var n = ${nodeExpr};` +
      `if (!n) return null;` +
      `var obj = n.getObject();` +
      `if (!obj) return null;` +
      `var sh = obj.getCurrentShape();` +
      `return sh ? sh.getGeometry() : null;` +
      `})()`;
    super(client, locator);
    this.nodeExpr = nodeExpr;
  }
  // ...
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd daz-ts && npx vitest run test/unit/geometry.test.ts`
Expected: PASS (9 tests)

- [ ] **Step 9: Add the barrel export and commit**

```typescript
// daz-ts/src/index.ts
export { DazGeometry } from "./geometry.js";
```

```bash
git add daz-ts/src/geometry.ts daz-ts/test/unit/geometry.test.ts daz-ts/src/index.ts
git commit -m "feat(daz-ts): port DazGeometry from dazpy _geometry.py"
```

---

### Task 16: `DazViewport`

**Files:**
- Create: `daz-ts/src/viewport.ts`
- Test: `daz-ts/test/unit/viewport.test.ts`
- Modify: `daz-ts/src/index.ts` (add `export { DazViewport } from "./viewport.js";`)

**Interfaces:**
- Consumes: `DazClient` (Phase 1).
- Produces: `class DazViewport { constructor(client?: DazClient); isAvailable(): Promise<boolean>; drawStyle(): Promise<string|null>; setDrawStyle(style: string): Promise<void>; getSize(): Promise<{width:number;height:number}|null>; setSize(width: number, height: number): never; capture(path: string, opts?: {width?: number; height?: number; hideOverlays?: boolean; backdropColor?: [number,number,number]; convergenceWait?: number}): Promise<string>; }`

**Excluded (see Global Constraints):** `capture_sprite()` (rembg-based background removal) has no Node equivalent in scope and is not ported.

- [ ] **Step 1: Write the failing test for `isAvailable`/`drawStyle`/`setDrawStyle`/`getSize`/`setSize`**

```typescript
import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazViewport } from "../../src/viewport.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}
afterEach(() => vi.unstubAllGlobals());
function stubSeq(...values: unknown[]) {
  const fetchMock = vi.fn();
  for (const v of values) fetchMock.mockResolvedValueOnce(jsonResponse({ success: true, result: v, output: [], request_id: "r", duration_ms: 0 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("DazViewport basics", () => {
  it("setDrawStyle resolves a friendly alias ('iray' -> 'NVIDIA Iray') before sending", async () => {
    const fetchMock = stubSeq({ before: "Wireframe", after: "NVIDIA Iray" });
    const vp = new DazViewport(new DazClient({ token: "" }));
    await vp.setDrawStyle("iray");
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain('"NVIDIA Iray"');
  });

  it("setDrawStyle passes an unrecognized raw label straight through", async () => {
    const fetchMock = stubSeq({ before: "X", after: "Custom Style" });
    const vp = new DazViewport(new DazClient({ token: "" }));
    await vp.setDrawStyle("Custom Style");
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain('"Custom Style"');
  });

  it("setDrawStyle throws ValueError-equivalent when the style silently didn't change and wasn't already applied", async () => {
    stubSeq({ before: "Wireframe", after: "Wireframe" });
    const vp = new DazViewport(new DazClient({ token: "" }));
    await expect(vp.setDrawStyle("not_a_real_style")).rejects.toThrow(/Unknown viewport draw style/);
  });

  it("setSize throws — Dz3DViewport doesn't expose resize via DazScript", () => {
    const vp = new DazViewport(new DazClient({ token: "" }));
    expect(() => vp.setSize(800, 600)).toThrow(/not supported/);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/viewport.test.ts`
Expected: FAIL with "Cannot find module '../../src/viewport.js'"

- [ ] **Step 3: Implement `isAvailable`/`drawStyle`/`setDrawStyle`/`getSize`/`setSize`**

```typescript
import type { DazClient } from "./client.js";
import { DazClient as DazClientImpl } from "./client.js";
import { ScriptBuilder } from "./scriptBuilder.js";

const VIEWPORT_EXPR = "MainWindow.getViewportMgr().getActiveViewport().get3DViewport()";

/**
 * Friendly aliases for `Dz3DViewport.setUserDrawStyle()`'s label strings.
 * Confirmed against a live instance: `setUserDrawStyle()` takes the exact
 * label shown in the viewport's draw-style dropdown and silently no-ops if
 * the label isn't recognized — empirical, not derived from an SDK enum. A
 * raw label string (e.g. `"NVIDIA Iray"`) is also accepted directly.
 */
const DRAW_STYLE_ALIASES: Record<string, string> = {
  wire_bounding_box: "Wire Bounding Box",
  wireframe: "Wireframe",
  smooth_shaded: "Smooth Shaded",
  texture_shaded: "Texture Shaded",
  iray: "NVIDIA Iray",
};

/** Viewport control: draw style, size query, and screenshot capture for DAZ Studio's active 3D viewport. */
export class DazViewport {
  private readonly client: DazClient;

  constructor(client?: DazClient) {
    this.client = client ?? new DazClientImpl();
  }

  /** `true` if an active 3D viewport is accessible. */
  async isAvailable(): Promise<boolean> {
    const script = ScriptBuilder.iife(`var vp = ${VIEWPORT_EXPR}; return (vp !== null && vp !== undefined);`);
    return Boolean((await this.client.execute(script)).value);
  }

  /** Current draw style label (e.g. `"NVIDIA Iray"`). */
  async drawStyle(): Promise<string | null> {
    const script = ScriptBuilder.iife(`var vp = ${VIEWPORT_EXPR}; if (!vp) return null; return vp.getUserDrawStyle();`);
    return (await this.client.execute(script)).value as string | null;
  }

  /**
   * Set the viewport's draw style (preview quality). Accepts a friendly
   * alias (`"wireframe"`, `"wire_bounding_box"`, `"smooth_shaded"`,
   * `"texture_shaded"`, `"iray"`) or a raw DAZ Studio label directly.
   * @throws Error if the style isn't recognized — `setUserDrawStyle()`
   * silently no-ops on an unknown label, so this reads the style back
   * afterward and throws if it didn't change (and wasn't already applied).
   */
  async setDrawStyle(style: string): Promise<void> {
    const resolved = DRAW_STYLE_ALIASES[style.trim().toLowerCase()] ?? style;
    const script = ScriptBuilder.iife(`
            var vp = ${VIEWPORT_EXPR};
            if (!vp) return null;
            var before = vp.getUserDrawStyle();
            vp.setUserDrawStyle(${ScriptBuilder.escapeString(resolved)});
            return {before: before, after: vp.getUserDrawStyle()};
        `);
    const result = (await this.client.execute(script)).value as { before: string; after: string } | null;
    if (result === null) return;
    if (result.after !== resolved && result.after === result.before) {
      throw new Error(`Unknown viewport draw style: ${JSON.stringify(style)}`);
    }
  }

  /** Viewport dimensions as `{width, height}`. */
  async getSize(): Promise<{ width: number; height: number } | null> {
    const script = ScriptBuilder.iife(`
            var vp = ${VIEWPORT_EXPR};
            if (!vp) return null;
            var r = vp.geometry;
            return {width: r.width, height: r.height};
        `);
    return (await this.client.execute(script)).value as { width: number; height: number } | null;
  }

  /**
   * Not supported — `Dz3DViewport` does not expose resize via DazScript.
   * Resize the DAZ Studio viewport window manually before calling {@link capture}.
   */
  setSize(_width: number, _height: number): never {
    throw new Error(
      "Viewport resize via DazScript is not supported. Resize the DAZ Studio viewport window manually.",
    );
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd daz-ts && npx vitest run test/unit/viewport.test.ts`
Expected: PASS (4 tests)

- [ ] **Step 5: Write the failing test for `capture()`'s two-pass overlay-hiding flow**

```typescript
// Append to daz-ts/test/unit/viewport.test.ts
describe("DazViewport.capture", () => {
  it("hideOverlays (default) issues two script calls: prepare (returns prior state) then finish (captures and restores)", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        success: true,
        result: {
          axesOn: true, floorStyle: 1, showPoseTool: false, aspectOn: true, thirdsGuideOn: false, toolBarMode: 0,
          selectionName: null, selectionSkeletonName: null, tnVisible: true, envVisible: true,
        },
        output: [], request_id: "r1", duration_ms: 0,
      }),
    );
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ success: true, result: "C:/out.png", output: [], request_id: "r2", duration_ms: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const vp = new DazViewport(new DazClient({ token: "" }));
    const path = await vp.capture("C:/out.png", { convergenceWait: 0 });

    expect(path).toBe("C:/out.png");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const prepareScript = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    const finishScript = JSON.parse(fetchMock.mock.calls[1][1].body as string).script;
    expect(prepareScript).toContain("vp.axesOn        = false;");
    expect(finishScript).toContain("img = vp.captureImage();");
    expect(finishScript).toContain("prev.axesOn");
  });

  it("hideOverlays: false skips the selection/overlay bookkeeping and still returns the saved path", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce(jsonResponse({ success: true, result: { ok: true }, output: [], request_id: "r1", duration_ms: 0 }));
    fetchMock.mockResolvedValueOnce(jsonResponse({ success: true, result: "C:/out.png", output: [], request_id: "r2", duration_ms: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    const vp = new DazViewport(new DazClient({ token: "" }));
    const path = await vp.capture("C:/out.png", { hideOverlays: false, convergenceWait: 0 });
    expect(path).toBe("C:/out.png");
    const prepareScript = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(prepareScript).not.toContain("Scene.setPrimarySelection(null)");
  });

  it("falls back to the input path when the final script returns null (viewport became unavailable)", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce(jsonResponse({ success: true, result: null, output: [], request_id: "r1", duration_ms: 0 }));
    fetchMock.mockResolvedValueOnce(jsonResponse({ success: true, result: null, output: [], request_id: "r2", duration_ms: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    const vp = new DazViewport(new DazClient({ token: "" }));
    expect(await vp.capture("C:/out.png", { convergenceWait: 0 })).toBe("C:/out.png");
  });
});
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/viewport.test.ts`
Expected: FAIL — `vp.capture is not a function`

- [ ] **Step 7: Implement `capture()`**

```typescript
// Add inside the DazViewport class body, after setSize()

  /**
   * Capture the active 3D viewport to a PNG/JPEG file.
   *
   * Split into two script round-trips deliberately: every viewport-state
   * change this method makes to prepare the shot (toggling overlays,
   * deselecting, changing the backdrop) invalidates DAZ Studio's Iray
   * real-time preview and restarts its progressive convergence. A single
   * script that invalidates the preview and calls `captureImage()` on the
   * next line grabs the framebuffer at essentially sample 0-1 — confirmed
   * live to make fully-clothed figures look nude (clothing layers too
   * thin/transparent to resolve at that sample count). Waiting in this
   * method *before* calling a combined script wouldn't help, since the
   * invalidate-then-grab both happen inside one call with nothing outside
   * it to wait on — hence a real `convergenceWait` sleep between two
   * separate `execute()` calls: one to invalidate (and kick off a fresh
   * convergence pass), one to grab the now-converged frame and restore state.
   *
   * @param width,height Accepted for API compatibility but ignored — `Dz3DViewport` does not expose resize via DazScript.
   * @param hideOverlays When `true` (default), axes/floor/pose-tool/aspect-frame and the primary selection are hidden for the capture and restored after.
   * @param backdropColor Temporary `[r,g,b]` viewport background for the capture, restored after.
   * @param convergenceWait Seconds to sleep between the two passes (default `3.0`); `0` skips the wait (accepting a possibly-unconverged capture).
   */
  async capture(
    path: string,
    opts: {
      width?: number;
      height?: number;
      hideOverlays?: boolean;
      backdropColor?: [number, number, number];
      convergenceWait?: number;
    } = {},
  ): Promise<string> {
    const { hideOverlays = true, backdropColor, convergenceWait = 3.0 } = opts;
    const jsPath = JSON.stringify(path);

    const bgCaptureJs = backdropColor !== undefined ? "var prevBg = vp.background;" : "";
    let bgApplyJs = "";
    if (backdropColor !== undefined) {
      const [r, g, b] = backdropColor;
      const hex = `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b.toString(16).padStart(2, "0")}`;
      bgApplyJs = `vp.background = new QColor(${JSON.stringify(hex)});`;
    }
    const bgReturnField = backdropColor !== undefined ? ", bg: prevBg" : "";

    if (hideOverlays) {
      const prepareScript = ScriptBuilder.iife(`
                var vp = ${VIEWPORT_EXPR};
                if (!vp) return null;

                var prevAxes        = vp.axesOn;
                var prevFloor       = vp.floorStyle;
                var prevPose        = vp.showPoseTool;
                var prevAspect      = vp.aspectOn;
                var prevThirds      = vp.thirdsGuideOn;
                var prevToolBarMode = vp.toolBarMode;
                ${bgCaptureJs}

                var prevSelection = Scene.getPrimarySelection();
                var prevSelectionName = prevSelection ? prevSelection.getName() : null;
                var prevSelectionSkeletonName = null;
                if (prevSelection && prevSelection.isBoneSelectingNode && prevSelection.isBoneSelectingNode()) {
                    var _selSkel = prevSelection.getSkeleton ? prevSelection.getSkeleton() : null;
                    if (_selSkel) prevSelectionSkeletonName = _selSkel.getName();
                }
                var tnNode  = Scene.findNodeByLabel("Tonemapper Options");
                var envNode = Scene.findNodeByLabel("Environment Options");
                var prevTnVisible  = tnNode  ? tnNode.isVisibleInViewport()  : null;
                var prevEnvVisible = envNode ? envNode.isVisibleInViewport() : null;

                vp.axesOn        = false;
                vp.floorStyle    = 0;
                vp.showPoseTool  = false;
                vp.aspectOn      = false;
                vp.thirdsGuideOn = false;
                vp.toolBarMode   = 0;
                ${bgApplyJs}

                Scene.setPrimarySelection(null);
                if (tnNode)  tnNode.setVisibleInViewport(false);
                if (envNode) envNode.setVisibleInViewport(false);

                vp.updateGL();

                return {
                    axesOn: prevAxes, floorStyle: prevFloor, showPoseTool: prevPose,
                    aspectOn: prevAspect, thirdsGuideOn: prevThirds, toolBarMode: prevToolBarMode,
                    selectionName: prevSelectionName,
                    selectionSkeletonName: prevSelectionSkeletonName,
                    tnVisible: prevTnVisible, envVisible: prevEnvVisible${bgReturnField}
                };
            `);
      const prevState = ((await this.client.execute(prepareScript)).value as Record<string, unknown>) ?? {};

      if (convergenceWait > 0) {
        await new Promise((resolve) => setTimeout(resolve, convergenceWait * 1000));
      }

      let restoreBgJs = "";
      if (backdropColor !== undefined && prevState.bg !== null && prevState.bg !== undefined) {
        const pb = prevState.bg as { r: number; g: number; b: number; a?: number };
        restoreBgJs = `vp.background = new QColor(${Math.trunc(pb.r)}, ${Math.trunc(pb.g)}, ${Math.trunc(pb.b)}, ${Math.trunc(
          pb.a ?? 255,
        )});`;
      }

      // vp is deliberately re-fetched (not assumed available): it can become unavailable during the real
      // wall-clock convergenceWait sleep. Scene-level restoration always runs; only viewport-specific
      // properties and the capture itself are skipped if vp is gone.
      const finishScript = ScriptBuilder.iife(`
                var vp = ${VIEWPORT_EXPR};
                var prev = ${JSON.stringify(prevState)};
                var img = null;

                if (vp) {
                    vp.updateGL();
                    img = vp.captureImage();

                    vp.axesOn        = prev.axesOn;
                    vp.floorStyle    = prev.floorStyle;
                    vp.showPoseTool  = prev.showPoseTool;
                    vp.aspectOn      = prev.aspectOn;
                    vp.thirdsGuideOn = prev.thirdsGuideOn;
                    vp.toolBarMode   = prev.toolBarMode;
                    ${restoreBgJs}
                }

                var prevSel = null;
                if (prev.selectionName) {
                    prevSel = Scene.findNode(prev.selectionName);
                    if (!prevSel && prev.selectionSkeletonName) {
                        var _selSkel = Scene.findNode(prev.selectionSkeletonName);
                        if (_selSkel && _selSkel.findBone) prevSel = _selSkel.findBone(prev.selectionName);
                    }
                }
                Scene.setPrimarySelection(prevSel);
                var tnNode  = Scene.findNodeByLabel("Tonemapper Options");
                var envNode = Scene.findNodeByLabel("Environment Options");
                if (tnNode  && prev.tnVisible  !== null) tnNode.setVisibleInViewport(prev.tnVisible);
                if (envNode && prev.envVisible !== null) envNode.setVisibleInViewport(prev.envVisible);

                if (vp) vp.updateGL();

                if (!img) return null;
                img.save(${jsPath});
                return ${jsPath};
            `);
      const result = (await this.client.execute(finishScript)).value as string | null;
      return result ?? path;
    }

    const prepareScript = ScriptBuilder.iife(`
            var vp = ${VIEWPORT_EXPR};
            if (!vp) return null;
            ${bgCaptureJs}
            ${bgApplyJs}
            vp.updateGL();
            return {"ok": true${bgReturnField}};
        `);
    const prepResult = ((await this.client.execute(prepareScript)).value as Record<string, unknown>) ?? {};
    if (prepResult.ok && convergenceWait > 0) {
      await new Promise((resolve) => setTimeout(resolve, convergenceWait * 1000));
    }

    let restoreBgJs = "";
    if (backdropColor !== undefined && prepResult.bg !== null && prepResult.bg !== undefined) {
      const pb = prepResult.bg as { r: number; g: number; b: number; a?: number };
      restoreBgJs = `vp.background = new QColor(${Math.trunc(pb.r)}, ${Math.trunc(pb.g)}, ${Math.trunc(pb.b)}, ${Math.trunc(
        pb.a ?? 255,
      )});`;
    }

    const finishScript = ScriptBuilder.iife(`
            var vp = ${VIEWPORT_EXPR};
            if (!vp) return null;
            vp.updateGL();
            var img = vp.captureImage();
            ${restoreBgJs}
            vp.updateGL();
            if (!img) return null;
            img.save(${jsPath});
            return ${jsPath};
        `);
    const result = (await this.client.execute(finishScript)).value as string | null;
    return result ?? path;
  }
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd daz-ts && npx vitest run test/unit/viewport.test.ts`
Expected: PASS (7 tests total)

- [ ] **Step 9: Add the barrel export and commit**

```typescript
// daz-ts/src/index.ts
export { DazViewport } from "./viewport.js";
```

```bash
git add daz-ts/src/viewport.ts daz-ts/test/unit/viewport.test.ts daz-ts/src/index.ts
git commit -m "feat(daz-ts): port DazViewport draw style, size, and two-pass capture from dazpy"
```

---

### Task 17: `DazTimeline`

**Files:**
- Create: `daz-ts/src/timeline.ts`
- Test: `daz-ts/test/unit/timeline.test.ts`
- Modify: `daz-ts/src/index.ts` (add `export { DazTimeline } from "./timeline.js";`)

**Interfaces:**
- Consumes: `DazClient` (Phase 1).
- Produces: `class DazTimeline { constructor(client?: DazClient); frame(): Promise<number|null>; setFrame(v: number): Promise<void>; time(): Promise<number|null>; timeStep(): Promise<number|null>; frameRange(): Promise<{start:number;end:number}|null>; play(): Promise<void>; pause(): Promise<void>; }`

- [ ] **Step 1: Write the failing test**

```typescript
import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazTimeline } from "../../src/timeline.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}
afterEach(() => vi.unstubAllGlobals());
function stub(value: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ success: true, result: value, output: [], request_id: "r", duration_ms: 0 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("DazTimeline", () => {
  it("frame getter/setter round-trip Scene.getFrame()/setFrame()", async () => {
    const fetchMock = stub(null);
    const timeline = new DazTimeline(new DazClient({ token: "" }));
    await timeline.setFrame(42);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe("(function(){\nScene.setFrame(42);\n})()");
  });

  it("time() reads Scene.getTime().valueOf()", async () => {
    const fetchMock = stub(1440);
    const timeline = new DazTimeline(new DazClient({ token: "" }));
    expect(await timeline.time()).toBe(1440);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("Scene.getTime().valueOf()");
  });

  it("frameRange() reads Scene.getAnimRange() start/end", async () => {
    stub({ start: 0, end: 90 });
    const timeline = new DazTimeline(new DazClient({ token: "" }));
    expect(await timeline.frameRange()).toEqual({ start: 0, end: 90 });
  });

  it("play()/pause() call Scene.play()/Scene.stop()", async () => {
    const fetchMock = stub(null);
    const timeline = new DazTimeline(new DazClient({ token: "" }));
    await timeline.play();
    await timeline.pause();
    const scripts = fetchMock.mock.calls.map((c) => JSON.parse(c[1].body as string).script);
    expect(scripts[0]).toContain("Scene.play();");
    expect(scripts[1]).toContain("Scene.stop();");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/timeline.test.ts`
Expected: FAIL with "Cannot find module '../../src/timeline.js'"

- [ ] **Step 3: Implement `DazTimeline`**

```typescript
import type { DazClient } from "./client.js";
import { DazClient as DazClientImpl } from "./client.js";
import { ScriptBuilder } from "./scriptBuilder.js";

/**
 * Timeline and playback control for the active scene. A thin wrapper
 * around the `Scene` playback API — `DazScene` offers the same frame/range
 * methods; use `DazTimeline` when a focused, dedicated object is preferred.
 */
export class DazTimeline {
  private readonly client: DazClient;

  constructor(client?: DazClient) {
    this.client = client ?? new DazClientImpl();
  }

  /** Current timeline frame (read/write). */
  async frame(): Promise<number | null> {
    return (await this.client.execute(ScriptBuilder.iife("return Scene.getFrame();"))).value as number | null;
  }

  async setFrame(value: number): Promise<void> {
    await this.client.execute(ScriptBuilder.iife(`Scene.setFrame(${Math.trunc(value)});`));
  }

  /** Current time in DAZ ticks (use {@link frame} for frame-based access). */
  async time(): Promise<number | null> {
    return (await this.client.execute(ScriptBuilder.iife("return Scene.getTime().valueOf();"))).value as number | null;
  }

  /** Number of DAZ ticks per frame (read-only). */
  async timeStep(): Promise<number | null> {
    return (await this.client.execute(ScriptBuilder.iife("return Scene.getTimeStep();"))).value as number | null;
  }

  /** Animation range as `{start, end}` in frames (read-only). */
  async frameRange(): Promise<{ start: number; end: number } | null> {
    const script = ScriptBuilder.iife("return { start: Scene.getAnimRange().start, end: Scene.getAnimRange().end };");
    return (await this.client.execute(script)).value as { start: number; end: number } | null;
  }

  async play(): Promise<void> {
    await this.client.execute(ScriptBuilder.iife("Scene.play();"));
  }

  async pause(): Promise<void> {
    await this.client.execute(ScriptBuilder.iife("Scene.stop();"));
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd daz-ts && npx vitest run test/unit/timeline.test.ts`
Expected: PASS (4 tests)

- [ ] **Step 5: Add the barrel export and commit**

```typescript
// daz-ts/src/index.ts
export { DazTimeline } from "./timeline.js";
```

```bash
git add daz-ts/src/timeline.ts daz-ts/test/unit/timeline.test.ts daz-ts/src/index.ts
git commit -m "feat(daz-ts): port DazTimeline from dazpy _timeline.py"
```

---

### Task 18: Integration test suite, build verification, and Phase 2 wrap-up

**Files:**
- Create: `daz-ts/test/integration/proxies.integration.test.ts`
- Modify: `daz-ts/README.md` (add a Phase 2 section listing the new exports, mirroring Phase 1's section)

**Interfaces:**
- Consumes: every class produced by Tasks 1-17, plus Phase 1's `DazClient`.
- Produces: an integration suite gated on `DAZ_SERVER_URL`, mirroring Phase 1's `test/integration/client.integration.test.ts` `skip_no_daz`-style gating (check that file for the exact env-var-gate/skip pattern used and match it).

- [ ] **Step 1: Write the gated integration test**

```typescript
import { beforeAll, describe, expect, it } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazScene } from "../../src/scene.js";
import { DazViewport } from "../../src/viewport.js";

const serverUrl = process.env.DAZ_SERVER_URL;
const describeIfServer = serverUrl ? describe : describe.skip;

describeIfServer("daz-ts Phase 2 proxies against a live DAZ Studio server", () => {
  let client: DazClient;
  let scene: DazScene;

  beforeAll(() => {
    const url = new URL(serverUrl!);
    client = new DazClient({ host: url.hostname, port: Number(url.port) || 18811 });
    scene = new DazScene(client);
  });

  it("overview() returns a well-formed scene summary", async () => {
    const overview = await scene.overview();
    expect(overview).toHaveProperty("total_nodes");
  });

  it("nodes() returns typed proxies whose position()/rotation() resolve without error", async () => {
    const nodes = await scene.nodes();
    for (const node of nodes.slice(0, 3)) {
      await expect(node.position()).resolves.not.toBeUndefined();
    }
  });

  it("findSkeleton()'s retry logic tolerates a scene with zero skeletons by raising NodeNotFoundError, not hanging", async () => {
    const numSkeletons = await scene.numSkeletons();
    if (numSkeletons > 0) return;
    await expect(scene.findSkeleton("NoSuchFigure", { retryAttempts: 1 })).rejects.toThrow();
  });

  it("DazViewport.isAvailable() reflects whether a 3D viewport is open", async () => {
    const vp = new DazViewport(client);
    expect(typeof (await vp.isAvailable())).toBe("boolean");
  });
});
```

- [ ] **Step 2: Run the full unit suite (must stay green — integration tests skip without `DAZ_SERVER_URL`)**

Run: `cd daz-ts && npm test`
Expected: PASS — every unit test from Tasks 1-17, integration suite reports skipped

- [ ] **Step 3: Run `npm run build` (tsc strict mode) to catch any type errors across the whole proxy layer**

Run: `cd daz-ts && npm run build`
Expected: Exits 0 with no diagnostics. Fix any strict-mode errors surfaced by cross-file usage (e.g. a method added in a later task using a type only partially defined earlier) before proceeding — do not weaken `tsconfig.json`'s strictness to make this pass.

- [ ] **Step 4: Manually run the integration suite against a live DAZ Studio + DazScriptServer instance, if available**

Run: `DAZ_SERVER_URL=http://127.0.0.1:18811 npx vitest run test/integration/proxies.integration.test.ts`
Expected: PASS. If any live-API assumption from the ported dazpy code turns out stale on the current DAZ Studio build (e.g. a property label changed), fix the corresponding proxy method and its exact-string unit test together, then re-run both suites.

- [ ] **Step 5: Update `daz-ts/README.md` and commit**

Add a "Phase 2: Scene Graph Proxies" section listing every new export (`DazElement`, `DazProperty`, `DazNode`, `NodeIdentifier`, `DazScene`, `DazSkeleton`, `DazBone`, `DazCamera`, `DazLight`, `DazMaterial`, `DazModifier`, `DazMorph`, `DazDForce`, `DazGeometry`, `DazViewport`, `DazTimeline`, `UndoGroup`, `withUndo`) with one line each, matching the style of Phase 1's README section.

```bash
git add daz-ts/test/integration/proxies.integration.test.ts daz-ts/README.md
git commit -m "test(daz-ts): add Phase 2 integration suite and README section"
```

- [ ] **Step 6: Close out the beads issue**

```bash
bd close daz-script-server-56nz --reason="daz-ts Phase 2 scene graph proxies complete: DazElement/DazProperty/DazNode/DazScene/DazSkeleton/DazBone/DazCamera/DazLight/DazMaterial/DazModifier family/DazGeometry/DazViewport/DazTimeline/UndoGroup ported with exact-script-string unit coverage and a gated integration suite."
```

---

## Self-Review

**Spec coverage:** Every class named in the design spec's Phase 2 bullet (`DazElement`, `DazNode`/`NodeIdentifier`, `DazScene`, `DazSkeleton`, `DazBone`, `DazCamera`, `DazLight`, `DazMaterial`, `DazModifier`/`DazMorph`/`DazDForce`, `DazGeometry`, `DazViewport`, `DazTimeline`, `UndoGroup`) has a task (Tasks 1, 3+6, 12+13+14, 10+11, 7, 8, 9, 4, 5, 15, 16, 17, 14). `DazProperty` (needed by `DazElement`'s sibling gotchas and `DazNode.findProperty`) is added as Task 2, matching dazpy's own module layout even though the design spec's prose doesn't name it explicitly — it's required to satisfy the `rawValue`/`setDoubleValue`/`getNumKeys` gotchas the spec does call out by name. All four named live-server gotchas (`rawValue`, `setDoubleValue`, `getNumKeys`, `findSkeleton` retry) are implemented and covered by dedicated test assertions (Tasks 2, 12). The injection-safety and exact-script-string testing strategy from the spec's "Testing strategy" section is followed throughout — every step's test asserts `JSON.parse(init.body).script` against a literal string or `toContain` fragment, never a loose match.

**Placeholder scan:** No task step contains "TBD", "similar to Task N", or an unshown implementation — every step includes complete, compilable code. The one draft placeholder note under Task 10 (a `.replace()`-based `skeletonScript` shown then disclaimed) was found and rewritten as a direct, correct `skeletonLookupAsNode` addition before this document was finalized.

**Type consistency:** `NodeIdentifier` (Task 3) is used with the same `{value, kind}` shape everywhere it's constructed (Tasks 3, 6, 7, 10, 12). `DazModifier`/`DazMorph`/`DazDForce` (Task 5) are consumed by `DazNode`'s dispatch table (Task 6) via the same class references. `ExecutionResult`/`DazClient.execute` (Phase 1) are consumed identically across every proxy file (`(await this.client.execute(script)).value`). `BoundingBox.fromDict`/`Vec3.fromList` (Phase 1 `math3.ts`) are called with the exact static-method names and shapes that file exports (verified against the Phase 1 source directly, not assumed). The async-property convention (`foo()`/`setFoo()` instead of TS accessors) is applied uniformly with no task reverting to a bare getter.

**Judgment calls not explicit in the design spec (flagged for confirmation):**
1. **Async-property convention** — every dazpy `@property` becomes a `foo(): Promise<T>` / `setFoo(v): Promise<void>` method pair rather than a TS `get`/`set` accessor, since accessors can't be `async` and a promise-returning bare getter (`get label(): Promise<...>`) would make `await node.label` read ambiguously like a property. Stated as a Global Constraint; used identically in every task.
2. **`UndoGroup` shape** — ported as `begin()`/`commit()`/`cancel()` plus a `withUndo(client, label, fn)` higher-order helper (and `DazScene.undo(label, fn)` delegating to it), since TS has no context-manager statement to mirror Python's `with`.
3. **`capture_sprite()` and IK-dependent methods excluded** — `DazViewport.capture_sprite()` (Python `rembg` dependency) and `DazSkeleton.handToTarget`/`.footToTarget`/`DazScene.applyInteractionRecipe` (require the Phase 5 `_interaction.py` IK solver) are out of scope for this phase; each is called out explicitly in Global Constraints and/or a TSDoc `@remarks` rather than silently dropped.
4. **`DazGeometry` retains the owning node's `Scene.findNode(...)` expression** (`nodeExpr`, Task 15) as a private field alongside the resolved-geometry `locator`, since `vertexPositionsPosed`/`boundingBoxPosed` need to re-resolve the node (not just its geometry) after forcing a cache update — dazpy's Python version has the same requirement via `self._identifier`.
