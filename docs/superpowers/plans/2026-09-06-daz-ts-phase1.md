# daz-ts Phase 1: Client Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold the `daz-ts` npm package and implement its client core — `DazClient`, `ExecutionResult`, the exception hierarchy, `ScriptBuilder`, `Batch`/`BatchFuture`, async job polling, SSE plumbing, and the dependency-free `math3.ts` — as a faithful TypeScript port of dazpy's `_client.py`, `exceptions.py`, `_result.py`, `_script_builder.py`, `_batch.py`, `_polling.py`, and `math3.py`.

**Architecture:** A single `DazClient` class (no sync/async split — TS `async/await` covers both dazpy's `DazClient` and `AsyncDazClient`) backed by Node's built-in `fetch`/`AbortController`. Exceptions mirror dazpy's hierarchy 1:1 as `Error` subclasses. `Batch` preserves dazpy's exact non-transactional, single-script semantics. `math3.ts` is a pure, dependency-free port with no HTTP coupling.

**Tech Stack:** TypeScript 5.x (strict mode), Node.js >=18 (built-in `fetch`), Vitest for tests, no runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-09-06-daz-ts-design.md` (this plan implements that spec's Phase 1; beads issue `daz-script-server-xtni`)

## Global Constraints

- Node.js >=18 only; no browser support (no `EventSource`, no `axios`/`node-fetch` — use Node's built-in `fetch`/`AbortController`/`ReadableStream`).
- Zero runtime dependencies. `typescript`, `vitest`, `@types/node` are the only `devDependencies`.
- `package.json` name: `daz-ts`, version starts at `0.1.0`, `"type": "module"`.
- Every injected string value in generated DazScript MUST go through `JSON.stringify` (mirrors dazpy's `json.dumps()`-based escaping) — this is a security invariant, not a style choice.
- Method/property names use camelCase (TS convention) where dazpy used snake_case, e.g. `executeAsyncSubmit` for `execute_async_submit`, `requestId` for `request_id`. Field names inside HTTP payloads sent to the server stay exactly as the server expects (snake_case, e.g. `scriptFile` vs `script_file` — check `openapi.yaml`/dazpy's payload dict keys verbatim per endpoint; do not camelCase wire fields).
- `Batch`/`executeBatchAsync` must preserve: serial execution order, no parallelism, no transactionality/rollback. Document this in TSDoc, do not "fix" it.
- Every task's unit tests stub `global.fetch` (via `vi.stubGlobal("fetch", ...)`) — no real network calls in the unit suite.

---

## File Structure

```
daz-ts/
  package.json
  tsconfig.json
  vitest.config.ts
  .gitignore                    # node_modules, dist
  src/
    exceptions.ts               # Task 2
    result.ts                   # Task 2
    scriptBuilder.ts            # Task 3
    client.ts                   # Tasks 4-7
    batch.ts                    # Task 8
    polling.ts                  # Task 9
    math3.ts                    # Task 10
    index.ts                    # Task 11
  test/
    unit/
      exceptions.test.ts
      scriptBuilder.test.ts
      client.execute.test.ts
      client.async.test.ts
      client.render.test.ts
      client.sse.test.ts
      batch.test.ts
      polling.test.ts
      math3.test.ts
      injectionSafety.test.ts
    integration/
      client.integration.test.ts
```

---

### Task 1: Scaffold the daz-ts package

**Files:**
- Create: `daz-ts/package.json`
- Create: `daz-ts/tsconfig.json`
- Create: `daz-ts/vitest.config.ts`
- Create: `daz-ts/.gitignore`
- Create: `daz-ts/src/index.ts` (empty placeholder export, filled in Task 11)

**Interfaces:**
- Produces: a buildable, testable empty TS package that later tasks add source files to.

- [ ] **Step 1: Create `daz-ts/package.json`**

```json
{
  "name": "daz-ts",
  "version": "0.1.0",
  "description": "TypeScript SDK for the DAZ Studio Script Server",
  "type": "module",
  "main": "./dist/index.js",
  "types": "./dist/index.d.ts",
  "license": "MIT",
  "engines": {
    "node": ">=18"
  },
  "files": [
    "dist"
  ],
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "test": "vitest run test/unit",
    "test:integration": "vitest run test/integration",
    "test:watch": "vitest"
  },
  "devDependencies": {
    "@types/node": "^20.14.0",
    "typescript": "^5.5.0",
    "vitest": "^2.0.0"
  }
}
```

- [ ] **Step 2: Create `daz-ts/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022"],
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "strict": true,
    "declaration": true,
    "outDir": "dist",
    "rootDir": "src",
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true
  },
  "include": ["src"]
}
```

- [ ] **Step 3: Create `daz-ts/vitest.config.ts`**

```ts
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    globals: false,
  },
});
```

- [ ] **Step 4: Create `daz-ts/.gitignore`**

```
node_modules/
dist/
```

- [ ] **Step 5: Create placeholder `daz-ts/src/index.ts`**

```ts
export {};
```

- [ ] **Step 6: Install dependencies and verify the empty build/test run**

Run (from `daz-ts/`):
```bash
npm install
npm run build
npm test
```
Expected: `npm run build` succeeds with no errors (produces `dist/index.js`, `dist/index.d.ts`); `npm test` reports "no test files found" (expected — no test files exist yet).

- [ ] **Step 7: Commit**

```bash
git add daz-ts/package.json daz-ts/package-lock.json daz-ts/tsconfig.json daz-ts/vitest.config.ts daz-ts/.gitignore daz-ts/src/index.ts
git commit -m "$(cat <<'EOF'
chore(daz-ts): scaffold TypeScript package

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Cv6wGgj4P2TmYmPbBHUafn
EOF
)"
```

---

### Task 2: Exceptions and ExecutionResult

**Files:**
- Create: `daz-ts/src/exceptions.ts`
- Create: `daz-ts/src/result.ts`
- Test: `daz-ts/test/unit/exceptions.test.ts`

**Interfaces:**
- Produces: `DazError`, `ConnectionError`, `AuthenticationError`, `DazBusyError`, `StudioBusyError`, `ConcurrencyLimitError`, `ScriptError`, `ScriptSyntaxError`, `ScriptRuntimeError`, `DazTimeoutError`, `NodeNotFoundError`, `AsyncExecutionError`, `RenderError`, `BatchLimitExceededError`, `MaterialError` (all from `./exceptions.js`); `ExecutionResult` interface (from `./result.js`).

- [ ] **Step 1: Write the failing test**

Create `daz-ts/test/unit/exceptions.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  AsyncExecutionError,
  AuthenticationError,
  BatchLimitExceededError,
  ConcurrencyLimitError,
  ConnectionError,
  DazBusyError,
  DazError,
  DazTimeoutError,
  MaterialError,
  NodeNotFoundError,
  RenderError,
  ScriptError,
  ScriptRuntimeError,
  ScriptSyntaxError,
  StudioBusyError,
} from "../../src/exceptions.js";

describe("exception hierarchy", () => {
  it("DazError is the base of every exception and extends Error", () => {
    const e = new DazError("boom");
    expect(e).toBeInstanceOf(Error);
    expect(e.message).toBe("boom");
  });

  it("StudioBusyError and ConcurrencyLimitError extend DazBusyError with reason/retryAfter", () => {
    const busy = new StudioBusyError("busy", "scene is loading", 3.5);
    expect(busy).toBeInstanceOf(DazBusyError);
    expect(busy).toBeInstanceOf(DazError);
    expect(busy.reason).toBe("scene is loading");
    expect(busy.retryAfter).toBe(3.5);

    const limit = new ConcurrencyLimitError("too many requests");
    expect(limit).toBeInstanceOf(DazBusyError);
    expect(limit.retryAfter).toBe(2.0); // default
  });

  it("ScriptSyntaxError and ScriptRuntimeError extend ScriptError and carry diagnostic info", () => {
    const err = new ScriptRuntimeError(
      "Line 3: TypeError: x is not a function",
      "1+1;\n2+2;\nx();",
      "req-123",
      ["log line 1", "log line 2"],
    );
    expect(err).toBeInstanceOf(ScriptError);
    expect(err.script).toContain("x();");
    expect(err.requestId).toBe("req-123");
    expect(err.output).toEqual(["log line 1", "log line 2"]);
    expect(err.diagnostic).toContain("   1: 1+1;");
    expect(err.diagnostic).toContain("   3: x();");
    expect(err.diagnostic).toContain("TypeError");
    expect(err.diagnostic).toContain("Captured output:");
    expect(err.diagnostic).toContain("request_id: req-123");

    const syntaxErr = new ScriptSyntaxError("SyntaxError: unexpected token");
    expect(syntaxErr).toBeInstanceOf(ScriptError);
  });

  it("AsyncExecutionError and RenderError carry requestId", () => {
    const e1 = new AsyncExecutionError("failed", "req-1");
    expect(e1.requestId).toBe("req-1");
    const e2 = new RenderError("render failed", "req-2");
    expect(e2.requestId).toBe("req-2");
  });

  it("MaterialError carries requestId", () => {
    const e = new MaterialError("bad material", "req-3");
    expect(e.requestId).toBe("req-3");
  });

  it("simple leaf exceptions extend DazError", () => {
    for (const Cls of [ConnectionError, AuthenticationError, DazTimeoutError, NodeNotFoundError, BatchLimitExceededError]) {
      const e = new Cls("x");
      expect(e).toBeInstanceOf(DazError);
    }
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/exceptions.test.ts`
Expected: FAIL — `../../src/exceptions.js` does not exist.

- [ ] **Step 3: Write `daz-ts/src/result.ts`**

```ts
/** The result of a synchronous or asynchronous DazScript execution. */
export interface ExecutionResult {
  /** The return value of the script (JSON-decoded). */
  value: unknown;
  /** Lines written to the DAZ Studio message log during execution. */
  output: string[];
  /** The server-assigned request ID (empty for sync executions). */
  requestId: string;
  /** `true` if the script completed without error. */
  success: boolean;
  /** Error message returned by the server (empty when successful). */
  error: string;
  /** Wall-clock execution time in milliseconds as measured by the server. */
  durationMs: number;
}
```

- [ ] **Step 4: Write `daz-ts/src/exceptions.ts`**

```ts
/** Base class for all daz-ts exceptions. */
export class DazError extends Error {
  constructor(message: string) {
    super(message);
    this.name = new.target.name;
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/** Raised when the SDK cannot reach the DAZ Studio Script Server. */
export class ConnectionError extends DazError {}

/** Raised on HTTP 401 or 403 (bad or missing API token, or IP blocked). */
export class AuthenticationError extends DazError {}

/**
 * Base class for transient "DAZ Studio is busy, please retry" conditions.
 */
export class DazBusyError extends DazError {
  /** Human-readable explanation of why the server is busy. */
  readonly reason: string;
  /** Server-suggested seconds to wait before retrying. */
  readonly retryAfter: number;

  constructor(message: string, reason = "", retryAfter = 2.0) {
    super(message);
    this.reason = reason;
    this.retryAfter = retryAfter;
  }
}

/**
 * Raised on HTTP 503 STUDIO_BUSY: DAZ Studio's main thread is occupied
 * with a scene load, save, clear, or render and cannot service the request.
 */
export class StudioBusyError extends DazBusyError {}

/**
 * Raised on HTTP 429 CONCURRENT_LIMIT_EXCEEDED: too many requests are
 * already in flight against the server.
 */
export class ConcurrencyLimitError extends DazBusyError {}

/** Base class for errors that originate inside a DazScript execution. */
export class ScriptError extends DazError {
  /** The DazScript source that was submitted (may be empty for file-based executions). */
  readonly script: string;
  /** The server-assigned request ID, useful for log correlation. */
  readonly requestId: string;
  /** Lines written to the DAZ Studio message log before the error. */
  readonly output: string[];

  constructor(message: string, script = "", requestId = "", output: string[] = []) {
    super(message);
    this.script = script;
    this.requestId = requestId;
    this.output = output;
  }

  /** A formatted string with line-numbered source and error details. */
  get diagnostic(): string {
    const lines: string[] = [];
    if (this.script) {
      const numbered = this.script
        .split("\n")
        .map((line, i) => `${String(i + 1).padStart(4, " ")}: ${line}`)
        .join("\n");
      lines.push(numbered);
    }
    lines.push(this.message);
    if (this.output.length > 0) {
      lines.push("\nCaptured output:\n" + this.output.join("\n"));
    }
    if (this.requestId) {
      lines.push(`request_id: ${this.requestId}`);
    }
    return lines.join("\n");
  }
}

/** Raised when the DazScript engine reports a parse / syntax error. */
export class ScriptSyntaxError extends ScriptError {}

/** Raised when a DazScript execution fails at runtime (TypeError, ReferenceError, etc.). */
export class ScriptRuntimeError extends ScriptError {}

/**
 * Raised when an HTTP request or async poll exceeds its timeout.
 *
 * Named `DazTimeoutError` (not `TimeoutError`) to avoid shadowing the
 * platform's built-in exception name.
 */
export class DazTimeoutError extends DazError {}

/** Raised when a requested scene node, bone, or skeleton cannot be found. */
export class NodeNotFoundError extends DazError {}

/**
 * Raised when an async request fails, is cancelled, or times out while polling.
 */
export class AsyncExecutionError extends DazError {
  /** The server-assigned request ID of the failed async job. */
  readonly requestId: string;

  constructor(message: string, requestId = "") {
    super(message);
    this.requestId = requestId;
  }
}

/** Raised when a render job fails on the DAZ Studio side. */
export class RenderError extends DazError {
  /** The server-assigned render request ID. */
  readonly requestId: string;

  constructor(message: string, requestId = "") {
    super(message);
    this.requestId = requestId;
  }
}

/**
 * Raised by {@link Batch.execute} (or `addOperation`, for the operation-count
 * limit) when a batch would exceed its configured operation-count or
 * generated-script-length limit.
 *
 * Raised client-side before any HTTP call, so an oversized batch never
 * reaches Studio's main thread.
 */
export class BatchLimitExceededError extends DazError {}

/**
 * Raised when an Iray material/surface-property operation fails.
 *
 * Covers a missing material, a channel label that doesn't resolve to a
 * property on the live material, or a failed `setValue()`/`setMap()`.
 */
export class MaterialError extends DazError {
  /** The server-assigned render request ID. */
  readonly requestId: string;

  constructor(message: string, requestId = "") {
    super(message);
    this.requestId = requestId;
  }
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd daz-ts && npx vitest run test/unit/exceptions.test.ts`
Expected: PASS (all assertions green).

- [ ] **Step 6: Commit**

```bash
git add daz-ts/src/exceptions.ts daz-ts/src/result.ts daz-ts/test/unit/exceptions.test.ts
git commit -m "$(cat <<'EOF'
feat(daz-ts): port exception hierarchy and ExecutionResult

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Cv6wGgj4P2TmYmPbBHUafn
EOF
)"
```

---

### Task 3: ScriptBuilder

**Files:**
- Create: `daz-ts/src/scriptBuilder.ts`
- Test: `daz-ts/test/unit/scriptBuilder.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: `ScriptBuilder.escapeString(value: string): string`, `ScriptBuilder.iife(body: string): string`, `ScriptBuilder.serializeArg(value: unknown): string` — used by `client.ts`, `batch.ts`, and (Phase 2+) proxy classes.

- [ ] **Step 1: Write the failing test**

Create `daz-ts/test/unit/scriptBuilder.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { ScriptBuilder } from "../../src/scriptBuilder.js";

describe("ScriptBuilder", () => {
  it("escapeString produces a JSON-quoted, embeddable string literal", () => {
    expect(ScriptBuilder.escapeString("hello")).toBe('"hello"');
    expect(ScriptBuilder.escapeString('a"b\\c')).toBe('"a\\"b\\\\c"');
    expect(ScriptBuilder.escapeString("line1\nline2")).toBe('"line1\\nline2"');
  });

  it("iife wraps a body in an immediately-invoked function expression", () => {
    expect(ScriptBuilder.iife("return 1;")).toBe("(function(){\nreturn 1;\n})()");
  });

  it("serializeArg formats booleans as bare true/false", () => {
    expect(ScriptBuilder.serializeArg(true)).toBe("true");
    expect(ScriptBuilder.serializeArg(false)).toBe("false");
  });

  it("serializeArg formats numbers as bare literals", () => {
    expect(ScriptBuilder.serializeArg(42)).toBe("42");
    expect(ScriptBuilder.serializeArg(3.14)).toBe("3.14");
  });

  it("serializeArg formats strings as JSON-quoted literals", () => {
    expect(ScriptBuilder.serializeArg("hi")).toBe('"hi"');
  });

  it("serializeArg falls back to JSON.stringify for objects and arrays", () => {
    expect(ScriptBuilder.serializeArg({ a: 1, b: "x" })).toBe('{"a":1,"b":"x"}');
    expect(ScriptBuilder.serializeArg([1, 2, 3])).toBe("[1,2,3]");
    expect(ScriptBuilder.serializeArg(null)).toBe("null");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/scriptBuilder.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Write `daz-ts/src/scriptBuilder.ts`**

```ts
/**
 * Helpers for building injection-safe DazScript source strings.
 *
 * Every value interpolated into a generated script MUST go through
 * {@link ScriptBuilder.escapeString} or {@link ScriptBuilder.serializeArg} —
 * never concatenated raw. This is the port's core injection-safety
 * invariant (mirrors dazpy's `json.dumps()`-based escaping).
 */
export class ScriptBuilder {
  /** Return `value` as a JSON string literal, safe to embed in DazScript source. */
  static escapeString(value: string): string {
    return JSON.stringify(value);
  }

  /** Wrap `body` in an immediately-invoked function expression. */
  static iife(body: string): string {
    return `(function(){\n${body}\n})()`;
  }

  /**
   * Serialize an arbitrary argument value for embedding in generated
   * DazScript source. Booleans and numbers become bare literals; strings
   * and everything else are JSON-encoded.
   */
  static serializeArg(value: unknown): string {
    if (typeof value === "boolean") {
      return value ? "true" : "false";
    }
    if (typeof value === "number") {
      return String(value);
    }
    return JSON.stringify(value);
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd daz-ts && npx vitest run test/unit/scriptBuilder.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add daz-ts/src/scriptBuilder.ts daz-ts/test/unit/scriptBuilder.test.ts
git commit -m "$(cat <<'EOF'
feat(daz-ts): add ScriptBuilder injection-safe script helpers

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Cv6wGgj4P2TmYmPbBHUafn
EOF
)"
```

---

### Task 4: DazClient core — construction, token loading, execute/executeFile

**Files:**
- Create: `daz-ts/src/client.ts`
- Test: `daz-ts/test/unit/client.execute.test.ts`

**Interfaces:**
- Consumes: `ExecutionResult` (`./result.js`); `AuthenticationError`, `ConnectionError`, `DazBusyError`, `DazTimeoutError`, `ScriptRuntimeError`, `ScriptSyntaxError`, `StudioBusyError`, `ConcurrencyLimitError` (`./exceptions.js`).
- Produces: `DazClientOptions` interface, `DazClient` class with `constructor(options?: DazClientOptions)`, `execute(script, args?, opts?): Promise<ExecutionResult>`, `executeFile(scriptFile, args?, opts?): Promise<ExecutionResult>`. Internal (not exported): `mapResponse`, `raiseForError`, `withBusyRetry`, `post`, `get` — later tasks in this file add more public methods to the same `DazClient` class.

- [ ] **Step 1: Write the failing test**

Create `daz-ts/test/unit/client.execute.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import {
  AuthenticationError,
  ConnectionError,
  ScriptRuntimeError,
  ScriptSyntaxError,
  StudioBusyError,
} from "../../src/exceptions.js";

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DazClient construction", () => {
  it("uses 127.0.0.1:18811 by default and an explicit empty token disables auth", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(200, { success: true, result: 2, output: [], request_id: "r1", duration_ms: 1.2 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await client.execute("1+1;");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/execute");
    expect((init.headers as Record<string, string>)["X-API-Token"]).toBeUndefined();
  });

  it("sends an explicit token as the X-API-Token header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(200, { success: true, result: null, output: [], request_id: "r1", duration_ms: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "secret-token" });
    await client.execute("1;");

    const [, init] = fetchMock.mock.calls[0];
    expect((init.headers as Record<string, string>)["X-API-Token"]).toBe("secret-token");
  });
});

describe("DazClient.execute", () => {
  it("posts {script} and returns a mapped ExecutionResult on success", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(200, { success: true, result: 4, output: ["hi"], request_id: "req-1", duration_ms: 5.5 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const result = await client.execute("2+2;");

    expect(result).toEqual({
      value: 4,
      output: ["hi"],
      requestId: "req-1",
      success: true,
      error: "",
      durationMs: 5.5,
    });
    const [, init] = fetchMock.mock.calls[0];
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ script: "2+2;" });
  });

  it("includes args in the payload when provided", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(200, { success: true, result: null, output: [], request_id: "", duration_ms: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await client.execute("f();", { count: 3 });

    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body as string)).toEqual({ script: "f();", args: { count: 3 } });
  });

  it("throws ScriptSyntaxError when success is false and error mentions SyntaxError", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(200, { success: false, error: "Line 1: SyntaxError: unexpected token", output: [], request_id: "r2" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await expect(client.execute("(;")).rejects.toBeInstanceOf(ScriptSyntaxError);
  });

  it("throws ScriptRuntimeError when success is false and error does not mention SyntaxError", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(200, { success: false, error: "Line 1: TypeError: x is not a function", output: ["log"], request_id: "r3" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const err = await client.execute("x();").catch((e) => e);
    expect(err).toBeInstanceOf(ScriptRuntimeError);
    expect(err.script).toBe("x();");
    expect(err.requestId).toBe("r3");
    expect(err.output).toEqual(["log"]);
  });

  it("throws AuthenticationError on HTTP 401", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("bad token", { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "bad" });
    await expect(client.execute("1;")).rejects.toBeInstanceOf(AuthenticationError);
  });

  it("throws StudioBusyError on HTTP 503 with STUDIO_BUSY error_code", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(503, { error: "busy", error_code: "STUDIO_BUSY", detail: "scene is loading" }, { "Retry-After": "4" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const err = await client.execute("1;").catch((e) => e);
    expect(err).toBeInstanceOf(StudioBusyError);
    expect(err.reason).toBe("scene is loading");
    expect(err.retryAfter).toBe(4);
  });

  it("throws ConnectionError when fetch rejects with a network failure", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("fetch failed"));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await expect(client.execute("1;")).rejects.toBeInstanceOf(ConnectionError);
  });
});

describe("DazClient.executeFile", () => {
  it("posts {scriptFile} (not {script}) and maps the response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(200, { success: true, result: "ok", output: [], request_id: "r4", duration_ms: 2 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const result = await client.executeFile("C:\\scripts\\a.dsa");

    expect(result.value).toBe("ok");
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body as string)).toEqual({ scriptFile: "C:\\scripts\\a.dsa" });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/client.execute.test.ts`
Expected: FAIL — `../../src/client.js` does not exist.

- [ ] **Step 3: Write `daz-ts/src/client.ts` (core section)**

```ts
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import {
  AuthenticationError,
  ConnectionError,
  ConcurrencyLimitError,
  DazBusyError,
  DazTimeoutError,
  ScriptRuntimeError,
  ScriptSyntaxError,
  StudioBusyError,
} from "./exceptions.js";
import type { ExecutionResult } from "./result.js";

const TOKEN_FILE = path.join(os.homedir(), ".daz3d", "dazscriptserver_token.txt");
const DEFAULT_HOST = "127.0.0.1";
const DEFAULT_PORT = 18811;

function loadToken(): string {
  try {
    return fs.readFileSync(TOKEN_FILE, "utf-8").trim();
  } catch {
    return "";
  }
}

function parseRetryAfter(headers: Headers): number {
  const raw = headers.get("Retry-After");
  const value = raw !== null ? Number.parseFloat(raw) : NaN;
  return Number.isFinite(value) ? value : 2.0;
}

async function raiseForError(resp: Response): Promise<void> {
  const status = resp.status;
  if (status === 401 || status === 403) {
    const text = await resp.text();
    throw new AuthenticationError(`HTTP ${status}: ${text.slice(0, 200)}`);
  }
  if (status < 400) {
    return;
  }
  const data = (await resp.json()) as Record<string, unknown>;
  const errorCode = (data.error_code as string) ?? "";
  const errorMsg = (data.error as string) ?? `HTTP ${status}`;
  const retryAfter = parseRetryAfter(resp.headers);
  if (errorCode === "STUDIO_BUSY") {
    throw new StudioBusyError(errorMsg, (data.detail as string) ?? errorMsg, retryAfter);
  }
  if (errorCode === "CONCURRENT_LIMIT_EXCEEDED") {
    throw new ConcurrencyLimitError(errorMsg, errorMsg, retryAfter);
  }
}

async function mapResponse(resp: Response, script = ""): Promise<ExecutionResult> {
  await raiseForError(resp);
  const data = (await resp.json()) as Record<string, unknown>;
  const requestId = (data.request_id as string) ?? "";

  if (data.success === false) {
    const errorMsg = (data.error as string) ?? "Script failed";
    const output = (data.output as string[]) ?? [];
    if (errorMsg.includes("SyntaxError")) {
      throw new ScriptSyntaxError(errorMsg, script, requestId, output);
    }
    throw new ScriptRuntimeError(errorMsg, script, requestId, output);
  }

  return {
    value: data.result ?? null,
    output: (data.output as string[]) ?? [],
    requestId,
    success: true,
    error: "",
    durationMs: (data.duration_ms as number) ?? 0,
  };
}

function sleep(seconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, seconds * 1000));
}

/** Options accepted by the {@link DazClient} constructor. */
export interface DazClientOptions {
  /** Hostname or IP address of the Script Server. Default `"127.0.0.1"`. */
  host?: string;
  /** Listening port of the Script Server. Default `18811`. */
  port?: number;
  /**
   * API token. Pass `""` to disable authentication, or omit/`null` to
   * auto-load from `~/.daz3d/dazscriptserver_token.txt`.
   */
  token?: string | null;
  /** Per-request HTTP timeout in milliseconds. Default `30000`. */
  timeoutMs?: number;
}

/** Options accepted by "submit"-style methods that support busy-retry. */
export interface RetryOptions {
  /**
   * If `true`, transparently retry with backoff when the server reports
   * `StudioBusyError`/`ConcurrencyLimitError`, instead of raising immediately.
   */
  retryOnBusy?: boolean;
  /**
   * Maximum total seconds to retry when `retryOnBusy` is `true`, before
   * re-throwing the busy error.
   */
  maxWait?: number;
}

/**
 * HTTP client for the DAZ Studio Script Server.
 *
 * Handles authentication, request serialization, and response mapping for
 * all server endpoints. The token is loaded automatically from
 * `~/.daz3d/dazscriptserver_token.txt` when `token` is omitted.
 *
 * Unlike dazpy (which needs separate `DazClient`/`AsyncDazClient` classes
 * for Python's sync/async split), a single `DazClient` covers both cases
 * via `async`/`await`.
 */
export class DazClient {
  private readonly baseUrl: string;
  private readonly token: string;
  private readonly timeoutMs: number;

  constructor(options: DazClientOptions = {}) {
    const { host = DEFAULT_HOST, port = DEFAULT_PORT, token = null, timeoutMs = 30_000 } = options;
    this.baseUrl = `http://${host}:${port}`;
    this.token = token !== null ? token : loadToken();
    this.timeoutMs = timeoutMs;
  }

  private get headers(): Record<string, string> {
    return this.token ? { "X-API-Token": this.token } : {};
  }

  private async fetchWithTimeout(url: string, init: RequestInit): Promise<Response> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      return await fetch(url, { ...init, signal: controller.signal });
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") {
        throw new DazTimeoutError(`Request timed out after ${this.timeoutMs / 1000}s`);
      }
      const message = e instanceof Error ? e.message : String(e);
      throw new ConnectionError(`Cannot reach DAZ Studio at ${this.baseUrl}: ${message}`);
    } finally {
      clearTimeout(timer);
    }
  }

  private post(pathname: string, payload: unknown): Promise<Response> {
    return this.fetchWithTimeout(`${this.baseUrl}${pathname}`, {
      method: "POST",
      headers: { ...this.headers, "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  private get(pathname: string, params?: Record<string, string>): Promise<Response> {
    const url = new URL(`${this.baseUrl}${pathname}`);
    if (params) {
      for (const [k, v] of Object.entries(params)) {
        url.searchParams.set(k, v);
      }
    }
    return this.fetchWithTimeout(url.toString(), { method: "GET", headers: this.headers });
  }

  private async delete_(pathname: string): Promise<Response | null> {
    try {
      return await this.fetchWithTimeout(`${this.baseUrl}${pathname}`, { method: "DELETE", headers: this.headers });
    } catch {
      return null;
    }
  }

  private async withBusyRetry<T>(fn: () => Promise<T>, retryOnBusy: boolean, maxWait: number): Promise<T> {
    if (!retryOnBusy) {
      return fn();
    }
    const deadline = Date.now() + maxWait * 1000;
    let backoff = 1.0;
    for (;;) {
      try {
        return await fn();
      } catch (e) {
        if (!(e instanceof DazBusyError)) {
          throw e;
        }
        const remainingMs = deadline - Date.now();
        if (remainingMs <= 0) {
          throw e;
        }
        await sleep(Math.min(backoff, remainingMs / 1000));
        backoff = Math.min(backoff + 1.0, 5.0);
      }
    }
  }

  /**
   * Execute a DazScript string synchronously.
   *
   * @param script - DazScript source code to execute.
   * @param args - Optional value passed into the script as `getArguments()[0]`. Must be JSON-serializable.
   */
  async execute(script: string, args?: unknown, opts: RetryOptions = {}): Promise<ExecutionResult> {
    const { retryOnBusy = false, maxWait = 30.0 } = opts;
    const payload: Record<string, unknown> = { script };
    if (args !== undefined) {
      payload.args = args;
    }
    return this.withBusyRetry(
      async () => mapResponse(await this.post("/execute", payload), script),
      retryOnBusy,
      maxWait,
    );
  }

  /**
   * Execute a `.dsa` script file that resides on the DAZ Studio host.
   *
   * @param scriptFile - Absolute path to the `.dsa` file on the server host.
   * @param args - Optional argument passed to the script.
   */
  async executeFile(scriptFile: string, args?: unknown, opts: RetryOptions = {}): Promise<ExecutionResult> {
    const { retryOnBusy = false, maxWait = 30.0 } = opts;
    const payload: Record<string, unknown> = { scriptFile };
    if (args !== undefined) {
      payload.args = args;
    }
    return this.withBusyRetry(
      async () => mapResponse(await this.post("/execute", payload)),
      retryOnBusy,
      maxWait,
    );
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd daz-ts && npx vitest run test/unit/client.execute.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add daz-ts/src/client.ts daz-ts/test/unit/client.execute.test.ts
git commit -m "$(cat <<'EOF'
feat(daz-ts): add DazClient core with execute/executeFile

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Cv6wGgj4P2TmYmPbBHUafn
EOF
)"
```

---

### Task 5: DazClient async job methods

**Files:**
- Modify: `daz-ts/src/client.ts` (add methods to the `DazClient` class)
- Test: `daz-ts/test/unit/client.async.test.ts`

**Interfaces:**
- Consumes: the private `post`/`get`/`delete_`/`withBusyRetry` helpers and `RetryOptions` from Task 4 (same file, same class — add these as additional public methods on `DazClient`).
- Produces: `executeAsyncSubmit(script, args?, opts?): Promise<string>`, `executeFileAsyncSubmit(scriptFile, args?, opts?): Promise<string>`, `getRequestStatus(requestId): Promise<Record<string, unknown>>`, `getRequestResult(requestId, wait?, waitTimeout?): Promise<Record<string, unknown>>`, `listRequests(status?): Promise<Record<string, unknown>>`, `cancelRequest(requestId): Promise<boolean>`. (`executeBatchAsync` is added in Task 8, alongside `Batch`.)

- [ ] **Step 1: Write the failing test**

Create `daz-ts/test/unit/client.async.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { AuthenticationError } from "../../src/exceptions.js";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DazClient async job methods", () => {
  it("executeAsyncSubmit posts to /execute/async and returns request_id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { request_id: "abc123" }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const id = await client.executeAsyncSubmit("1+1;", { x: 1 });

    expect(id).toBe("abc123");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/execute/async");
    expect(JSON.parse(init.body as string)).toEqual({ script: "1+1;", args: { x: 1 } });
  });

  it("executeFileAsyncSubmit posts {scriptFile} to /execute/async", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { request_id: "abc456" }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const id = await client.executeFileAsyncSubmit("C:\\a.dsa");

    expect(id).toBe("abc456");
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body as string)).toEqual({ scriptFile: "C:\\a.dsa" });
  });

  it("getRequestStatus returns {status: 'not_found'} on 404", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("", { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const status = await client.getRequestStatus("missing");

    expect(status).toEqual({ status: "not_found" });
  });

  it("getRequestStatus returns the parsed body on success", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { status: "running", progress: 0.5 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const status = await client.getRequestStatus("req-1");

    expect(status).toEqual({ status: "running", progress: 0.5 });
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/requests/req-1/status");
  });

  it("getRequestResult adds wait/timeout query params when wait=true", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { success: true, result: 5 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await client.getRequestResult("req-1", true, 15);

    const [url] = fetchMock.mock.calls[0];
    const parsed = new URL(url as string);
    expect(parsed.pathname).toBe("/requests/req-1/result");
    expect(parsed.searchParams.get("wait")).toBe("true");
    expect(parsed.searchParams.get("timeout")).toBe("15");
  });

  it("getRequestResult omits query params when wait is not requested", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { success: true, result: 5 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await client.getRequestResult("req-1");

    const [url] = fetchMock.mock.calls[0];
    const parsed = new URL(url as string);
    expect(parsed.search).toBe("");
  });

  it("listRequests passes an optional status filter and throws AuthenticationError on 401", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("nope", { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "bad" });
    await expect(client.listRequests("queued")).rejects.toBeInstanceOf(AuthenticationError);

    const [url] = fetchMock.mock.calls[0];
    expect(new URL(url as string).searchParams.get("status")).toBe("queued");
  });

  it("cancelRequest returns true on HTTP 200 and false otherwise", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("", { status: 200 }))
      .mockResolvedValueOnce(new Response("", { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    expect(await client.cancelRequest("req-1")).toBe(true);
    expect(await client.cancelRequest("req-2")).toBe(false);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/requests/req-1");
    expect(init.method).toBe("DELETE");
  });

  it("cancelRequest returns false on a network error", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("network down"));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    expect(await client.cancelRequest("req-1")).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/client.async.test.ts`
Expected: FAIL — methods do not exist on `DazClient`.

- [ ] **Step 3: Add the async job methods to `daz-ts/src/client.ts`**

Add `AuthenticationError` to the existing import from `./exceptions.js` (it's already imported in Task 4's code), then add these methods inside the `DazClient` class, after `executeFile`:

```ts
  /**
   * Submit a script for asynchronous execution and return immediately.
   *
   * @returns The server-assigned `requestId`. Use it with {@link getRequestStatus}
   * or {@link getRequestResult} to poll for the outcome.
   */
  async executeAsyncSubmit(script: string, args?: unknown, opts: RetryOptions = {}): Promise<string> {
    const { retryOnBusy = false, maxWait = 30.0 } = opts;
    const payload: Record<string, unknown> = { script };
    if (args !== undefined) {
      payload.args = args;
    }
    return this.withBusyRetry(
      async () => {
        const resp = await this.post("/execute/async", payload);
        await raiseForError(resp);
        const data = (await resp.json()) as Record<string, unknown>;
        return (data.request_id as string) ?? "";
      },
      retryOnBusy,
      maxWait,
    );
  }

  /**
   * Submit a host-side `.dsa` file for asynchronous execution.
   *
   * The file is loaded by DAZ Studio when the queued job starts, preserving
   * its filename for `getScriptFileName()` and relative `include()` calls.
   */
  async executeFileAsyncSubmit(scriptFile: string, args?: unknown, opts: RetryOptions = {}): Promise<string> {
    const { retryOnBusy = false, maxWait = 30.0 } = opts;
    const payload: Record<string, unknown> = { scriptFile };
    if (args !== undefined) {
      payload.args = args;
    }
    return this.withBusyRetry(
      async () => {
        const resp = await this.post("/execute/async", payload);
        await raiseForError(resp);
        const data = (await resp.json()) as Record<string, unknown>;
        return (data.request_id as string) ?? "";
      },
      retryOnBusy,
      maxWait,
    );
  }

  /**
   * Return the current status of an async request.
   *
   * @returns A dict with at least a `status` key: `"queued"`, `"running"`,
   * `"completed"`, `"failed"`, `"cancelled"`, or `"not_found"`.
   */
  async getRequestStatus(requestId: string): Promise<Record<string, unknown>> {
    const resp = await this.get(`/requests/${requestId}/status`);
    if (resp.status === 404) {
      return { status: "not_found" };
    }
    return (await resp.json()) as Record<string, unknown>;
  }

  /**
   * Fetch the result of a completed async request.
   *
   * @param wait - If `true`, the server long-polls until the request completes or `waitTimeout` is reached.
   * @param waitTimeout - Maximum seconds the server should wait (only relevant when `wait` is `true`).
   */
  async getRequestResult(requestId: string, wait = false, waitTimeout = 30): Promise<Record<string, unknown>> {
    const params: Record<string, string> = {};
    if (wait) {
      params.wait = "true";
      params.timeout = String(waitTimeout);
    }
    const resp = await this.get(`/requests/${requestId}/result`, Object.keys(params).length ? params : undefined);
    if (resp.status === 404) {
      return { status: "not_found" };
    }
    return (await resp.json()) as Record<string, unknown>;
  }

  /**
   * List all tracked async requests (script and render) with their status.
   *
   * @param status - Optional filter: `"queued"`, `"running"`, `"completed"`, `"failed"`, `"cancelled"`.
   */
  async listRequests(status?: string): Promise<Record<string, unknown>> {
    const resp = await this.get("/requests", status ? { status } : undefined);
    if (resp.status === 401 || resp.status === 403) {
      throw new AuthenticationError(`HTTP ${resp.status}: ${(await resp.text()).slice(0, 200)}`);
    }
    return (await resp.json()) as Record<string, unknown>;
  }

  /**
   * Cancel a queued or running async request.
   *
   * @returns `true` if the server confirmed cancellation, `false` otherwise.
   */
  async cancelRequest(requestId: string): Promise<boolean> {
    const resp = await this.delete_(`/requests/${requestId}`);
    return resp !== null && resp.status === 200;
  }
```

Also update `delete_` (added in Task 4) so it never throws — it should return `null` on any failure, which it already does via its `try/catch`. Confirm that behavior is intact (no change needed if Task 4 was implemented as specified).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd daz-ts && npx vitest run test/unit/client.async.test.ts`
Expected: PASS.

- [ ] **Step 5: Run the full unit suite to confirm no regressions**

Run: `cd daz-ts && npm test`
Expected: All previously passing tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add daz-ts/src/client.ts daz-ts/test/unit/client.async.test.ts
git commit -m "$(cat <<'EOF'
feat(daz-ts): add DazClient async job submission and polling methods

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Cv6wGgj4P2TmYmPbBHUafn
EOF
)"
```

---

### Task 6: DazClient render/export/health methods

**Files:**
- Modify: `daz-ts/src/client.ts`
- Test: `daz-ts/test/unit/client.render.test.ts`

**Interfaces:**
- Consumes: same private helpers as Tasks 4-5, plus `AuthenticationError`.
- Produces (all added to `DazClient`): `renderSubmit(outputPath, opts?): Promise<Record<string, unknown>>`, `renderBatchSubmit(variants, base?, opts?): Promise<Record<string, unknown>>`, `renderAnimationSubmit(outputPath, startFrame, endFrame, opts?): Promise<Record<string, unknown>>`, `cancelRender(requestId): Promise<boolean>`, `exportUsdSubmit(outputPath, opts?): Promise<Record<string, unknown>>`, `getUsdExportStatus(jobId): Promise<Record<string, unknown>>`, `status(): Promise<Record<string, unknown>>`, `health(): Promise<Record<string, unknown>>`, `metrics(): Promise<Record<string, unknown>>`.

- [ ] **Step 1: Write the failing test**

Create `daz-ts/test/unit/client.render.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { AuthenticationError } from "../../src/exceptions.js";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DazClient render methods", () => {
  it("renderSubmit posts required + optional fields to /render", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { request_id: "r1", status: "queued", submitted_at: "now" }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await client.renderSubmit("C:\\out.png", {
      figure: "Genesis9",
      morphs: { Smile: 0.5 },
      width: 512,
      height: 512,
      camera: "MainCamera",
      engine: "iray",
      irayamples: undefined,
    });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/render");
    expect(JSON.parse(init.body as string)).toEqual({
      output_path: "C:\\out.png",
      width: 512,
      height: 512,
      camera: "MainCamera",
      engine: "iray",
      figure: "Genesis9",
      morphs: { Smile: 0.5 },
    });
  });

  it("renderSubmit prefers figures[] over figure/morphs when both are given", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { request_id: "r1" }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await client.renderSubmit("C:\\out.png", {
      figure: "ignored",
      figures: [{ name: "Genesis9", morphs: { Smile: 1 } }],
    });

    const [, init] = fetchMock.mock.calls[0];
    const body = JSON.parse(init.body as string);
    expect(body.figures).toEqual([{ name: "Genesis9", morphs: { Smile: 1 } }]);
    expect(body.figure).toBeUndefined();
  });

  it("renderBatchSubmit posts variants and optional base", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { batch_id: "b1", request_ids: ["r1", "r2"], total: 2 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const result = await client.renderBatchSubmit(
      [{ output_path: "a.png" }, { output_path: "b.png" }],
      { width: 256, height: 256 },
    );

    expect(result).toEqual({ batch_id: "b1", request_ids: ["r1", "r2"], total: 2 });
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body as string)).toEqual({
      variants: [{ output_path: "a.png" }, { output_path: "b.png" }],
      base: { width: 256, height: 256 },
    });
  });

  it("renderAnimationSubmit posts frame range fields with default padding", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { request_id: "r1", status: "queued" }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await client.renderAnimationSubmit("C:\\anim\\f_{frame}.png", 1, 10);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/render/animation");
    expect(JSON.parse(init.body as string)).toEqual({
      output_path: "C:\\anim\\f_{frame}.png",
      start_frame: 1,
      end_frame: 10,
      frame_padding: 4,
    });
  });

  it("cancelRender posts to /render/{id}/cancel and returns a boolean", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    expect(await client.cancelRender("r1")).toBe(true);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/render/r1/cancel");
    expect(init.method).toBe("POST");
  });
});

describe("DazClient USD export methods", () => {
  it("exportUsdSubmit posts camelCase wire fields with documented defaults", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { job_id: "j1", status: "queued" }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await client.exportUsdSubmit("C:\\out.usda");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/export/usd");
    expect(JSON.parse(init.body as string)).toEqual({
      outputPath: "C:\\out.usda",
      includeGeometry: true,
      includeMaterials: true,
      includeSkeleton: false,
      includeMorphs: false,
      includeLights: false,
      includeCamera: false,
    });
  });

  it("getUsdExportStatus returns not_found on 404 and throws on 401", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("", { status: 404 }))
      .mockResolvedValueOnce(new Response("nope", { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    expect(await client.getUsdExportStatus("j1")).toEqual({ job_id: "j1", status: "not_found" });
    await expect(client.getUsdExportStatus("j2")).rejects.toBeInstanceOf(AuthenticationError);
  });
});

describe("DazClient server health methods", () => {
  it("status/health/metrics GET their endpoints and throw AuthenticationError on 403", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("blocked", { status: 403 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await expect(client.status()).rejects.toBeInstanceOf(AuthenticationError);
    await expect(client.health()).rejects.toBeInstanceOf(AuthenticationError);
    await expect(client.metrics()).rejects.toBeInstanceOf(AuthenticationError);

    expect(fetchMock.mock.calls[0][0]).toBe("http://127.0.0.1:18811/status");
    expect(fetchMock.mock.calls[1][0]).toBe("http://127.0.0.1:18811/health");
    expect(fetchMock.mock.calls[2][0]).toBe("http://127.0.0.1:18811/metrics");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/client.render.test.ts`
Expected: FAIL — methods do not exist.

- [ ] **Step 3: Add render/export/health methods to `daz-ts/src/client.ts`**

Add these interfaces above the `DazClient` class:

```ts
/** Options accepted by {@link DazClient.renderSubmit}. */
export interface RenderSubmitOptions extends RetryOptions {
  figure?: string;
  morphs?: Record<string, number>;
  figures?: Array<{ name: string; morphs?: Record<string, number> }>;
  width?: number;
  height?: number;
  camera?: string;
  engine?: string;
  irayamples?: number;
  iraySamples?: number;
  resetMorphs?: boolean;
}

/** Options accepted by {@link DazClient.exportUsdSubmit}. */
export interface ExportUsdOptions {
  includeGeometry?: boolean;
  includeMaterials?: boolean;
  includeSkeleton?: boolean;
  includeMorphs?: boolean;
  includeLights?: boolean;
  includeCamera?: boolean;
}
```

Note: `irayamples` in the test above is a deliberate typo check — remove it; use only `iraySamples`. Correct the interface to:

```ts
export interface RenderSubmitOptions extends RetryOptions {
  figure?: string;
  morphs?: Record<string, number>;
  figures?: Array<{ name: string; morphs?: Record<string, number> }>;
  width?: number;
  height?: number;
  camera?: string;
  engine?: string;
  iraySamples?: number;
  resetMorphs?: boolean;
}
```

And in the test file written in Step 1, remove the stray `irayamples: undefined,` line from the first `renderSubmit` test's options object before running.

Add these methods inside the `DazClient` class, after `cancelRequest`:

```ts
  // ── Render ──────────────────────────────────────────────────────────────

  /** Submit a render job and return immediately. */
  async renderSubmit(outputPath: string, opts: RenderSubmitOptions = {}): Promise<Record<string, unknown>> {
    const { figure, morphs, figures, width, height, camera, engine, iraySamples, resetMorphs, retryOnBusy = false, maxWait = 30.0 } = opts;
    const payload: Record<string, unknown> = { output_path: outputPath };
    if (width && height) {
      payload.width = width;
      payload.height = height;
    }
    if (camera) payload.camera = camera;
    if (engine) payload.engine = engine;
    if (iraySamples) payload.iray_samples = iraySamples;
    if (resetMorphs) payload.reset_morphs = true;
    if (figures !== undefined) {
      payload.figures = figures;
    } else if (figure) {
      payload.figure = figure;
      if (morphs) payload.morphs = morphs;
    }

    return this.withBusyRetry(
      async () => {
        const resp = await this.post("/render", payload);
        await raiseForError(resp);
        return (await resp.json()) as Record<string, unknown>;
      },
      retryOnBusy,
      maxWait,
    );
  }

  /** Submit a batch render job (multiple variants sharing optional defaults) and return immediately. */
  async renderBatchSubmit(
    variants: Array<Record<string, unknown>>,
    base?: Record<string, unknown>,
    opts: RetryOptions = {},
  ): Promise<Record<string, unknown>> {
    const { retryOnBusy = false, maxWait = 30.0 } = opts;
    const payload: Record<string, unknown> = { variants };
    if (base) payload.base = base;

    return this.withBusyRetry(
      async () => {
        const resp = await this.post("/render/batch", payload);
        await raiseForError(resp);
        return (await resp.json()) as Record<string, unknown>;
      },
      retryOnBusy,
      maxWait,
    );
  }

  /** Submit an animation render job spanning a frame range and return immediately. */
  async renderAnimationSubmit(
    outputPath: string,
    startFrame: number,
    endFrame: number,
    opts: RetryOptions & { framePadding?: number; width?: number; height?: number; camera?: string; engine?: string } = {},
  ): Promise<Record<string, unknown>> {
    const { framePadding = 4, width, height, camera, engine, retryOnBusy = false, maxWait = 30.0 } = opts;
    const payload: Record<string, unknown> = {
      output_path: outputPath,
      start_frame: startFrame,
      end_frame: endFrame,
      frame_padding: framePadding,
    };
    if (width && height) {
      payload.width = width;
      payload.height = height;
    }
    if (camera) payload.camera = camera;
    if (engine) payload.engine = engine;

    return this.withBusyRetry(
      async () => {
        const resp = await this.post("/render/animation", payload);
        await raiseForError(resp);
        return (await resp.json()) as Record<string, unknown>;
      },
      retryOnBusy,
      maxWait,
    );
  }

  /** Cancel a queued or running render job. */
  async cancelRender(requestId: string): Promise<boolean> {
    try {
      const resp = await this.fetchWithTimeout(`${this.baseUrl}/render/${requestId}/cancel`, {
        method: "POST",
        headers: this.headers,
      });
      return resp.status === 200;
    } catch {
      return false;
    }
  }

  /** Open the SSE progress stream for a render request. Implemented in Task 7. */

  // ── USD export ──────────────────────────────────────────────────────────

  /** Submit a USD export job and return immediately. */
  async exportUsdSubmit(outputPath: string, opts: ExportUsdOptions = {}): Promise<Record<string, unknown>> {
    const {
      includeGeometry = true,
      includeMaterials = true,
      includeSkeleton = false,
      includeMorphs = false,
      includeLights = false,
      includeCamera = false,
    } = opts;
    const payload = {
      outputPath,
      includeGeometry,
      includeMaterials,
      includeSkeleton,
      includeMorphs,
      includeLights,
      includeCamera,
    };
    const resp = await this.post("/export/usd", payload);
    if (resp.status === 401 || resp.status === 403) {
      throw new AuthenticationError(`HTTP ${resp.status}: ${(await resp.text()).slice(0, 200)}`);
    }
    return (await resp.json()) as Record<string, unknown>;
  }

  /** Poll the status of a USD export job. */
  async getUsdExportStatus(jobId: string): Promise<Record<string, unknown>> {
    const resp = await this.get(`/export/usd/${jobId}`);
    if (resp.status === 401 || resp.status === 403) {
      throw new AuthenticationError(`HTTP ${resp.status}: ${(await resp.text()).slice(0, 200)}`);
    }
    if (resp.status === 404) {
      return { job_id: jobId, status: "not_found" };
    }
    return (await resp.json()) as Record<string, unknown>;
  }

  // ── Server health ───────────────────────────────────────────────────────

  /** Return the server status dict from `GET /status`. */
  async status(): Promise<Record<string, unknown>> {
    const resp = await this.get("/status");
    if (resp.status === 401 || resp.status === 403) {
      throw new AuthenticationError(`HTTP ${resp.status}: ${(await resp.text()).slice(0, 200)}`);
    }
    return (await resp.json()) as Record<string, unknown>;
  }

  /** Return the health check dict from `GET /health`. */
  async health(): Promise<Record<string, unknown>> {
    const resp = await this.get("/health");
    if (resp.status === 401 || resp.status === 403) {
      throw new AuthenticationError(`HTTP ${resp.status}: ${(await resp.text()).slice(0, 200)}`);
    }
    return (await resp.json()) as Record<string, unknown>;
  }

  /** Return the metrics dict from `GET /metrics`. */
  async metrics(): Promise<Record<string, unknown>> {
    const resp = await this.get("/metrics");
    if (resp.status === 401 || resp.status === 403) {
      throw new AuthenticationError(`HTTP ${resp.status}: ${(await resp.text()).slice(0, 200)}`);
    }
    return (await resp.json()) as Record<string, unknown>;
  }
```

- [ ] **Step 4: Fix the test file's stray field and run the test**

Remove the `irayamples: undefined,` line from `client.render.test.ts`'s first `renderSubmit` test (it was a placeholder to catch a naming mismatch during writing — the real field is `iraySamples`).

Run: `cd daz-ts && npx vitest run test/unit/client.render.test.ts`
Expected: PASS.

- [ ] **Step 5: Run the full unit suite**

Run: `cd daz-ts && npm test`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add daz-ts/src/client.ts daz-ts/test/unit/client.render.test.ts
git commit -m "$(cat <<'EOF'
feat(daz-ts): add DazClient render, USD export, and health endpoint methods

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Cv6wGgj4P2TmYmPbBHUafn
EOF
)"
```

---

### Task 7: SSE streaming — render progress and scene events

**Files:**
- Modify: `daz-ts/src/client.ts`
- Test: `daz-ts/test/unit/client.sse.test.ts`

**Interfaces:**
- Consumes: `fetchWithTimeout`/`headers` from Task 4 (same class).
- Produces: `DazClient.streamRenderProgress(requestId, streamTimeoutMs?): Promise<Response | null>`, `DazClient.streamSceneEvents(categories?, streamTimeoutMs?): Promise<Response | null>`, and a standalone exported helper `parseSseStream(response: Response): AsyncGenerator<{ event: string; data: string }>` for callers to consume the raw `Response`'s body.

- [ ] **Step 1: Write the failing test**

Create `daz-ts/test/unit/client.sse.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient, parseSseStream } from "../../src/client.js";

afterEach(() => {
  vi.unstubAllGlobals();
});

function sseBodyStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
}

describe("DazClient.streamRenderProgress", () => {
  it("returns the raw Response when the endpoint responds 200", async () => {
    const fakeResponse = new Response(sseBodyStream(["data: {}\n\n"]), { status: 200 });
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse);
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const resp = await client.streamRenderProgress("req-1");

    expect(resp).toBe(fakeResponse);
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/render/req-1/progress");
  });

  it("returns null when the endpoint is unavailable or errors", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("", { status: 404 }))
      .mockRejectedValueOnce(new TypeError("network down"));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    expect(await client.streamRenderProgress("req-1")).toBeNull();
    expect(await client.streamRenderProgress("req-2")).toBeNull();
  });
});

describe("DazClient.streamSceneEvents", () => {
  it("joins categories into a comma-separated filter query param when provided", async () => {
    const fakeResponse = new Response(sseBodyStream(["data: {}\n\n"]), { status: 200 });
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse);
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await client.streamSceneEvents(["node", "camera"]);

    const [url] = fetchMock.mock.calls[0];
    const parsed = new URL(url as string);
    expect(parsed.pathname).toBe("/scene/events");
    expect(parsed.searchParams.get("filter")).toBe("node,camera");
  });

  it("omits the filter param when categories is not provided", async () => {
    const fakeResponse = new Response(sseBodyStream(["data: {}\n\n"]), { status: 200 });
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse);
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await client.streamSceneEvents();

    const [url] = fetchMock.mock.calls[0];
    expect(new URL(url as string).search).toBe("");
  });
});

describe("parseSseStream", () => {
  it("yields parsed event/data pairs from an SSE byte stream, skipping keepalive comments", async () => {
    const response = new Response(
      sseBodyStream([
        ": keepalive\n\n",
        'event: node\ndata: {"id":"1"}\n\n',
        'data: {"id":"2"}\n\n',
      ]),
      { status: 200 },
    );

    const events: Array<{ event: string; data: string }> = [];
    for await (const evt of parseSseStream(response)) {
      events.push(evt);
    }

    expect(events).toEqual([
      { event: "node", data: '{"id":"1"}' },
      { event: "message", data: '{"id":"2"}' },
    ]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/client.sse.test.ts`
Expected: FAIL — `streamRenderProgress`, `streamSceneEvents`, `parseSseStream` do not exist.

- [ ] **Step 3: Add SSE methods and the standalone parser to `daz-ts/src/client.ts`**

Add this exported function near the top-level helpers (after `sleep`, before the `DazClientOptions` interface):

```ts
/**
 * Parse a Server-Sent-Events HTTP response body into `{event, data}` pairs.
 *
 * Lines starting with `:` are keepalive comments and are skipped. An event
 * block with no explicit `event:` line defaults to `"message"`, matching
 * the SSE specification.
 */
export async function* parseSseStream(response: Response): AsyncGenerator<{ event: string; data: string }> {
  const body = response.body;
  if (!body) {
    return;
  }
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });

      let boundary: number;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const rawEvent = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);

        let eventName = "message";
        const dataLines: string[] = [];
        for (const line of rawEvent.split("\n")) {
          if (line.startsWith(":") || line === "") {
            continue;
          }
          if (line.startsWith("event:")) {
            eventName = line.slice("event:".length).trim();
          } else if (line.startsWith("data:")) {
            dataLines.push(line.slice("data:".length).trim());
          }
        }
        if (dataLines.length > 0) {
          yield { event: eventName, data: dataLines.join("\n") };
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
```

Add these methods inside the `DazClient` class, after `cancelRender`:

```ts
  /**
   * Open the SSE progress stream for a render request.
   *
   * @returns The raw streaming `Response` on success, `null` if the
   * endpoint is unavailable. Pass the result to {@link parseSseStream} to
   * consume it, and remember to let the body drain or cancel the reader.
   */
  async streamRenderProgress(requestId: string, streamTimeoutMs = 305_000): Promise<Response | null> {
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), streamTimeoutMs);
      const resp = await fetch(`${this.baseUrl}/render/${requestId}/progress`, {
        headers: this.headers,
        signal: controller.signal,
      }).finally(() => clearTimeout(timer));
      return resp.status === 200 ? resp : null;
    } catch {
      return null;
    }
  }

  /**
   * Open the SSE stream for general scene-change events (`GET /scene/events`).
   *
   * @param categories - Optional subset of event categories to subscribe to
   * (`"node"`, `"skeleton"`, `"light"`, `"camera"`, `"selection"`, `"scene"`,
   * `"time"`, `"render"`). Omit to subscribe to all categories.
   * @param streamTimeoutMs - Socket timeout in milliseconds. Omit to wait
   * indefinitely — the server sends a keepalive comment every 15 seconds.
   */
  async streamSceneEvents(categories?: string[], streamTimeoutMs?: number): Promise<Response | null> {
    try {
      const url = new URL(`${this.baseUrl}/scene/events`);
      if (categories && categories.length > 0) {
        url.searchParams.set("filter", categories.join(","));
      }
      const controller = new AbortController();
      const timer = streamTimeoutMs !== undefined ? setTimeout(() => controller.abort(), streamTimeoutMs) : undefined;
      const resp = await fetch(url.toString(), { headers: this.headers, signal: controller.signal }).finally(() => {
        if (timer) clearTimeout(timer);
      });
      return resp.status === 200 ? resp : null;
    } catch {
      return null;
    }
  }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd daz-ts && npx vitest run test/unit/client.sse.test.ts`
Expected: PASS.

- [ ] **Step 5: Run the full unit suite**

Run: `cd daz-ts && npm test`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add daz-ts/src/client.ts daz-ts/test/unit/client.sse.test.ts
git commit -m "$(cat <<'EOF'
feat(daz-ts): add SSE streaming for render progress and scene events

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Cv6wGgj4P2TmYmPbBHUafn
EOF
)"
```

---

### Task 8: Batch and BatchFuture

**Files:**
- Create: `daz-ts/src/batch.ts`
- Modify: `daz-ts/src/client.ts` (add `executeBatchAsync`)
- Test: `daz-ts/test/unit/batch.test.ts`

**Interfaces:**
- Consumes: `DazClient` (`./client.js`), `BatchLimitExceededError` (`./exceptions.js`).
- Produces: `buildOperationsScript(operations: Array<[string[], string]>): string`, `BatchFuture` class with a `value` getter, `Batch` class (`constructor(client, options?)`, `add`, `addPrelude`, `addOperation`, `execute`), and `DazClient.executeBatchAsync(operations, args?): Promise<string>`.

- [ ] **Step 1: Write the failing test**

Create `daz-ts/test/unit/batch.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { Batch, buildOperationsScript } from "../../src/batch.js";
import { DazClient } from "../../src/client.js";
import { BatchLimitExceededError } from "../../src/exceptions.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("buildOperationsScript", () => {
  it("builds one IIFE returning a keyed object over _r0, _r1, ...", () => {
    const script = buildOperationsScript([
      [["var x = 1;"], "x"],
      [["var y = 2;"], "y"],
    ]);
    expect(script).toBe(
      '(function(){\nvar x = 1;\nvar _r0 = x;\nvar y = 2;\nvar _r1 = y;\nreturn {"_r0": _r0, "_r1": _r1};\n})()',
    );
  });
});

describe("BatchFuture", () => {
  it("throws when .value is read before the batch executes", async () => {
    const client = new DazClient({ token: "" });
    const batch = new Batch(client);
    const future = batch.addOperation(["var x = 1;"], "x");
    expect(() => future.value).toThrow(/has not been executed/i);
  });
});

describe("Batch", () => {
  it("issues exactly one HTTP call for multiple operations and resolves every future", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ success: true, result: { _r0: 42, _r1: "hi" }, output: [], request_id: "r1", duration_ms: 1 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const batch = new Batch(client);
    const f1 = batch.addOperation(["var a = 40 + 2;"], "a");
    const f2 = batch.addOperation(["var b = 'hi';"], "b");
    await batch.execute();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(f1.value).toBe(42);
    expect(f2.value).toBe("hi");
  });

  it("does nothing (no HTTP call) when execute() is called with no queued operations", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const batch = new Batch(client);
    await batch.execute();

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("as an async context-like helper: execute() resolves futures added via add()", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ success: true, result: { _r0: [1, 2, 3] }, output: [], request_id: "r1", duration_ms: 1 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const batch = new Batch(client);
    const future = batch.add(["var _r0 = [1,2,3];"]);
    await batch.execute();

    expect(future.value).toEqual([1, 2, 3]);
  });

  it("emits a shared prelude only once even when referenced by multiple operations", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ success: true, result: { _r0: 1, _r1: 2 }, output: [], request_id: "r1", duration_ms: 1 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const batch = new Batch(client);
    batch.addPrelude("node:Fig", ["var _node = Scene.findNode('Fig');"]);
    batch.addPrelude("node:Fig", ["var _node = Scene.findNode('Fig');"]); // no-op, same key
    batch.addOperation(["var a = 1;"], "a");
    batch.addOperation(["var b = 2;"], "b");
    await batch.execute();

    const [, init] = fetchMock.mock.calls[0];
    const script = JSON.parse(init.body as string).script as string;
    const occurrences = script.split("Scene.findNode('Fig')").length - 1;
    expect(occurrences).toBe(1);
  });

  it("addOperation raises BatchLimitExceededError client-side once maxOperations is reached", () => {
    const client = new DazClient({ token: "" });
    const batch = new Batch(client, { maxOperations: 1 });
    batch.addOperation(["var a = 1;"], "a");
    expect(() => batch.addOperation(["var b = 2;"], "b")).toThrow(BatchLimitExceededError);
  });

  it("execute() raises BatchLimitExceededError before any HTTP call when the script is too long", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const batch = new Batch(client, { maxScriptLength: 10 });
    batch.addOperation(["var a = 1;"], "a");

    await expect(batch.execute()).rejects.toBeInstanceOf(BatchLimitExceededError);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("DazClient.executeBatchAsync", () => {
  it("builds one combined script and submits it via /execute/async", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ request_id: "async-1" }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const id = await client.executeBatchAsync([
      { body_lines: ["var a = 1;"], result_expression: "a" },
      { body_lines: ["var b = 2;"], result_expression: "b" },
    ]);

    expect(id).toBe("async-1");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/execute/async");
    const body = JSON.parse(init.body as string);
    expect(body.script).toContain("_r0");
    expect(body.script).toContain("_r1");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/batch.test.ts`
Expected: FAIL — `../../src/batch.js` does not exist, `client.executeBatchAsync` does not exist.

- [ ] **Step 3: Write `daz-ts/src/batch.ts`**

```ts
import type { DazClient } from "./client.js";
import { BatchLimitExceededError } from "./exceptions.js";

export const DEFAULT_MAX_OPERATIONS = 500;
export const DEFAULT_MAX_SCRIPT_LENGTH = 900_000; // stays under the server's default 1MB script cap

/**
 * Build one IIFE script from a list of `[bodyLines, resultExpression]` pairs.
 *
 * Shared by {@link Batch}'s internal script builder and
 * {@link DazClient.executeBatchAsync} so both produce scripts with an
 * identical shape (keyed return object over `_r0`, `_r1`, ...).
 */
export function buildOperationsScript(operations: Array<[string[], string]>): string {
  const bodyLines: string[] = [];
  const returnParts: string[] = [];
  operations.forEach(([lines, resultExpression], i) => {
    const key = `_r${i}`;
    bodyLines.push(...lines);
    bodyLines.push(`var ${key} = ${resultExpression};`);
    returnParts.push(`"${key}": ${key}`);
  });
  const returnObj = `{${returnParts.join(", ")}}`;
  bodyLines.push(`return ${returnObj};`);
  const body = bodyLines.join("\n");
  return `(function(){\n${body}\n})()`;
}

/**
 * Placeholder for a single result within a {@link Batch} execution.
 *
 * Created by {@link Batch.add} or {@link Batch.addOperation}; the `value`
 * getter throws until the batch has been executed.
 */
export class BatchFuture {
  private resolved = false;
  private resultValue: unknown = undefined;

  constructor(private readonly key: string) {}

  /** The result value. Throws if {@link Batch.execute} has not been called yet. */
  get value(): unknown {
    if (!this.resolved) {
      throw new Error("Batch has not been executed yet");
    }
    return this.resultValue;
  }

  /** @internal */
  _resolve(value: unknown): void {
    this.resultValue = value;
    this.resolved = true;
  }

  /** @internal */
  get _key(): string {
    return this.key;
  }
}

/** Options accepted by the {@link Batch} constructor. */
export interface BatchOptions {
  /** Max queued operations before {@link Batch.addOperation} throws {@link BatchLimitExceededError}. */
  maxOperations?: number;
  /** Max generated script length (characters) before {@link Batch.execute} throws {@link BatchLimitExceededError}. */
  maxScriptLength?: number;
}

/**
 * Collect multiple DazScript operations and execute them in a single HTTP round-trip.
 *
 * Semantics (preserved exactly from dazpy, do not "improve" silently):
 * execution is **serial**, there is **no parallelism**, and the batch is
 * **not transactional** — if any operation throws, the whole call fails
 * the same way a single failing `execute()` call would, and earlier
 * mutations already applied to the live scene are **not** rolled back.
 * Order destructive/hard-to-recover operations last.
 *
 * @example
 * ```ts
 * const batch = new Batch(client);
 * const posFuture = batch.addOperation(
 *   ["var n = Scene.findNode('Figure');", "var p = [n.getWSPos().x, n.getWSPos().y, n.getWSPos().z];"],
 *   "p",
 * );
 * await batch.execute();
 * console.log(posFuture.value);
 * ```
 */
export class Batch {
  private readonly client: DazClient;
  private readonly ops: Array<{ key: string; lines: string[]; future: BatchFuture }> = [];
  private readonly preludes = new Map<string, string[]>();
  private readonly preludeOrder: string[] = [];
  private counter = 0;
  private readonly maxOperations: number;
  private readonly maxScriptLength: number;

  constructor(client: DazClient, options: BatchOptions = {}) {
    this.client = client;
    this.maxOperations = options.maxOperations ?? DEFAULT_MAX_OPERATIONS;
    this.maxScriptLength = options.maxScriptLength ?? DEFAULT_MAX_SCRIPT_LENGTH;
  }

  /**
   * Queue DazScript lines to be included in the batch.
   *
   * The last line in `lines` should assign the desired result to a
   * variable named after the internally generated key (`_r0`, `_r1`, ...
   * in call order). Prefer {@link addOperation}, which does not require
   * guessing the key name.
   */
  add(lines: string[]): BatchFuture {
    const key = `_r${this.counter++}`;
    const future = new BatchFuture(key);
    this.ops.push({ key, lines: [...lines], future });
    return future;
  }

  /**
   * Register a shared setup block, emitted once per unique `preludeKey`.
   *
   * Call this before {@link addOperation} calls whose bodies depend on the
   * prelude's bound variable(s). Repeated calls with the same `preludeKey`
   * are no-ops after the first.
   */
  addPrelude(preludeKey: string, lines: string[]): void {
    if (!this.preludes.has(preludeKey)) {
      this.preludes.set(preludeKey, [...lines]);
      this.preludeOrder.push(preludeKey);
    }
  }

  /**
   * Queue an operation whose result the builder assigns internally.
   *
   * @param bodyLines - DazScript source lines with no trailing result assignment.
   * @param resultExpression - A JS expression evaluated once after `bodyLines`
   * run, used as this operation's result. Mutation-only operations should pass `"null"`.
   * @throws {BatchLimitExceededError} If this call would exceed `maxOperations`.
   */
  addOperation(bodyLines: string[], resultExpression: string): BatchFuture {
    if (this.ops.length >= this.maxOperations) {
      throw new BatchLimitExceededError(
        `Batch already has ${this.ops.length} operations (maxOperations=${this.maxOperations})`,
      );
    }
    const key = `_r${this.counter++}`;
    const future = new BatchFuture(key);
    const lines = [...bodyLines, `var ${key} = ${resultExpression};`];
    this.ops.push({ key, lines, future });
    return future;
  }

  private buildScript(): string {
    const bodyLines: string[] = [];
    for (const preludeKey of this.preludeOrder) {
      bodyLines.push(...(this.preludes.get(preludeKey) ?? []));
    }
    const returnParts: string[] = [];
    for (const { key, lines } of this.ops) {
      bodyLines.push(...lines);
      returnParts.push(`"${key}": ${key}`);
    }
    const returnObj = `{${returnParts.join(", ")}}`;
    bodyLines.push(`return ${returnObj};`);
    const body = bodyLines.join("\n");
    return `(function(){\n${body}\n})()`;
  }

  /**
   * Execute all queued operations in a single HTTP request and resolve every future.
   *
   * @throws {BatchLimitExceededError} If the generated script exceeds
   * `maxScriptLength`. Raised before any HTTP call.
   */
  async execute(): Promise<void> {
    if (this.ops.length === 0) {
      return;
    }
    const script = this.buildScript();
    if (script.length > this.maxScriptLength) {
      throw new BatchLimitExceededError(
        `Generated batch script is ${script.length} characters (maxScriptLength=${this.maxScriptLength})`,
      );
    }
    const result = await this.client.execute(script);
    const data = (result.value as Record<string, unknown>) ?? {};
    for (const { key, future } of this.ops) {
      future._resolve(data[key]);
    }
  }
}
```

- [ ] **Step 4: Add `executeBatchAsync` to `daz-ts/src/client.ts`**

Add this method inside the `DazClient` class, after `executeFileAsyncSubmit`:

```ts
  /**
   * Submit multiple operations as one async request (one queue slot, one script).
   *
   * @param operations - `{bodyLines, resultExpression}` pairs — same shape as {@link Batch.addOperation}'s arguments.
   * @returns The server-assigned `requestId`. Poll it like any other async
   * request; the result's `result` field is a dict keyed `"_r0"`, `"_r1"`, ... in submission order.
   */
  async executeBatchAsync(
    operations: Array<{ body_lines: string[]; result_expression: string }>,
    args?: unknown,
  ): Promise<string> {
    const { buildOperationsScript } = await import("./batch.js");
    const pairs: Array<[string[], string]> = operations.map((op) => [op.body_lines, op.result_expression]);
    const script = buildOperationsScript(pairs);
    return this.executeAsyncSubmit(script, args);
  }
```

Note: this uses a dynamic `import()` for `buildOperationsScript` to avoid a circular static import between `client.ts` and `batch.ts` (`batch.ts` imports the `DazClient` *type* only, via `import type`, which does not create a runtime cycle — but `client.ts` importing `batch.ts`'s value export at the top of the file would. If your editor/linter flags this, an equally valid fix is to move `buildOperationsScript` into a third file, e.g. `scriptBuilder.ts`, imported by both — for Phase 1 keep it in `batch.ts` and use the dynamic import as shown).

- [ ] **Step 5: Run test to verify it passes**

Run: `cd daz-ts && npx vitest run test/unit/batch.test.ts`
Expected: PASS.

- [ ] **Step 6: Run the full unit suite**

Run: `cd daz-ts && npm test`
Expected: All PASS.

- [ ] **Step 7: Commit**

```bash
git add daz-ts/src/batch.ts daz-ts/src/client.ts daz-ts/test/unit/batch.test.ts
git commit -m "$(cat <<'EOF'
feat(daz-ts): port Batch/BatchFuture and DazClient.executeBatchAsync

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Cv6wGgj4P2TmYmPbBHUafn
EOF
)"
```

---

### Task 9: executeLong polling helper

**Files:**
- Create: `daz-ts/src/polling.ts`
- Test: `daz-ts/test/unit/polling.test.ts`

**Interfaces:**
- Consumes: `DazClient` (`./client.js`), `ExecutionResult` (`./result.js`), `AsyncExecutionError`, `DazTimeoutError` (`./exceptions.js`).
- Produces: `executeLong(client, script, args?, options?): Promise<ExecutionResult>`.

- [ ] **Step 1: Write the failing test**

Create `daz-ts/test/unit/polling.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { AsyncExecutionError, DazTimeoutError } from "../../src/exceptions.js";
import { executeLong } from "../../src/polling.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("executeLong", () => {
  it("submits async then returns a mapped result once the poll reports success", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ request_id: "req-1" })) // /execute/async
      .mockResolvedValueOnce(jsonResponse({ success: true, result: 42, output: ["ok"], duration_ms: 100 })); // /requests/:id/result
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const result = await executeLong(client, "longRunning();");

    expect(result).toEqual({
      value: 42,
      output: ["ok"],
      requestId: "req-1",
      success: true,
      error: "",
      durationMs: 100,
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("throws AsyncExecutionError when the polled result reports success: false", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ request_id: "req-1" }))
      .mockResolvedValueOnce(jsonResponse({ success: false, error: "boom" }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await expect(executeLong(client, "x();")).rejects.toBeInstanceOf(AsyncExecutionError);
  });

  it("throws AsyncExecutionError when the request is reported cancelled", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ request_id: "req-1" }))
      .mockResolvedValueOnce(jsonResponse({ status: "cancelled" }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const err = await executeLong(client, "x();").catch((e) => e);
    expect(err).toBeInstanceOf(AsyncExecutionError);
    expect(err.message).toMatch(/cancelled/i);
  });

  it("polls again on a non-terminal status before eventually succeeding", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ request_id: "req-1" }))
      .mockResolvedValueOnce(jsonResponse({ status: "running" }))
      .mockResolvedValueOnce(jsonResponse({ success: true, result: "done", output: [], duration_ms: 5 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    const result = await executeLong(client, "x();", undefined, { pollIntervalMs: 1 });

    expect(result.value).toBe("done");
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("throws DazTimeoutError when the timeout elapses before completion", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ request_id: "req-1" }))
      .mockResolvedValue(jsonResponse({ status: "running" }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    await expect(
      executeLong(client, "x();", undefined, { timeoutMs: 5, pollIntervalMs: 1 }),
    ).rejects.toBeInstanceOf(DazTimeoutError);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/polling.test.ts`
Expected: FAIL — `../../src/polling.js` does not exist.

- [ ] **Step 3: Write `daz-ts/src/polling.ts`**

```ts
import type { DazClient } from "./client.js";
import type { ExecutionResult } from "./result.js";
import { AsyncExecutionError, DazTimeoutError } from "./exceptions.js";

/** Options accepted by {@link executeLong}. */
export interface ExecuteLongOptions {
  /** Maximum total wall-clock milliseconds to wait. Default `120000`. */
  timeoutMs?: number;
  /** Milliseconds to sleep between short polls when the server returns before the long-poll timeout. Default `500`. */
  pollIntervalMs?: number;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Execute a potentially long-running script via the async endpoint with polling.
 *
 * Submits `script` asynchronously, then polls `/requests/:id/result` with
 * long-polling until the script completes or `timeoutMs` is exceeded.
 *
 * @throws {AsyncExecutionError} If the script fails or the request is cancelled.
 * @throws {DazTimeoutError} If `timeoutMs` is exceeded before the script completes.
 */
export async function executeLong(
  client: DazClient,
  script: string,
  args?: unknown,
  options: ExecuteLongOptions = {},
): Promise<ExecutionResult> {
  const { timeoutMs = 120_000, pollIntervalMs = 500 } = options;
  const requestId = await client.executeAsyncSubmit(script, args);
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const waitTimeoutSeconds = Math.min(30, Math.floor((deadline - Date.now()) / 1000) + 1);
    const data = await client.getRequestResult(requestId, true, waitTimeoutSeconds);
    const status = data.status as string | undefined;

    if (data.success !== undefined) {
      if (!data.success) {
        throw new AsyncExecutionError((data.error as string) ?? "Async script failed", requestId);
      }
      return {
        value: data.result ?? null,
        output: (data.output as string[]) ?? [],
        requestId,
        success: true,
        error: "",
        durationMs: (data.duration_ms as number) ?? 0,
      };
    }
    if (status === "failed") {
      throw new AsyncExecutionError((data.error as string) ?? "Async script failed", requestId);
    }
    if (status === "cancelled") {
      throw new AsyncExecutionError("Request was cancelled", requestId);
    }
    await sleep(pollIntervalMs);
  }

  throw new DazTimeoutError(`Async execution timed out after ${timeoutMs / 1000}s (requestId=${requestId})`);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd daz-ts && npx vitest run test/unit/polling.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add daz-ts/src/polling.ts daz-ts/test/unit/polling.test.ts
git commit -m "$(cat <<'EOF'
feat(daz-ts): port executeLong async polling helper

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Cv6wGgj4P2TmYmPbBHUafn
EOF
)"
```

---

### Task 10: math3.ts — Vec3, Quat, BoundingBox, AxisRemap

**Files:**
- Create: `daz-ts/src/math3.ts`
- Test: `daz-ts/test/unit/math3.test.ts`

**Interfaces:**
- Consumes: nothing (pure, dependency-free).
- Produces: `Vec3`, `Quat`, `BoundingBox`, `AxisRemap` classes, and the `Y_UP_TO_Z_UP` constant, all exported from `./math3.js`.

- [ ] **Step 1: Write the failing test**

Create `daz-ts/test/unit/math3.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { AxisRemap, BoundingBox, Quat, Vec3, Y_UP_TO_Z_UP } from "../../src/math3.js";

function approxEqual(a: number, b: number, eps = 1e-9): boolean {
  return Math.abs(a - b) < eps;
}

describe("Vec3", () => {
  it("constructs from dict/list and round-trips to dict/list", () => {
    const v = Vec3.fromDict({ x: 1, y: 2, z: 3 });
    expect(v.toDict()).toEqual({ x: 1, y: 2, z: 3 });
    expect(Vec3.fromList([4, 5, 6]).toList()).toEqual([4, 5, 6]);
  });

  it("supports add/sub/scale/negate", () => {
    const a = new Vec3(1, 2, 3);
    const b = new Vec3(4, 5, 6);
    expect(a.add(b).toList()).toEqual([5, 7, 9]);
    expect(b.sub(a).toList()).toEqual([3, 3, 3]);
    expect(a.mul(2).toList()).toEqual([2, 4, 6]);
    expect(a.div(2).toList()).toEqual([0.5, 1, 1.5]);
    expect(a.neg().toList()).toEqual([-1, -2, -3]);
  });

  it("computes dot, cross, length, and normalize", () => {
    const a = new Vec3(1, 0, 0);
    const b = new Vec3(0, 1, 0);
    expect(a.dot(b)).toBe(0);
    expect(a.cross(b).toList()).toEqual([0, 0, 1]);
    expect(new Vec3(3, 4, 0).length()).toBe(5);
    expect(Vec3.zero().normalize().toList()).toEqual([0, 0, 0]);
    expect(new Vec3(5, 0, 0).normalize().toList()).toEqual([1, 0, 0]);
  });

  it("computes distance and lerp", () => {
    const a = new Vec3(0, 0, 0);
    const b = new Vec3(10, 0, 0);
    expect(a.distance(b)).toBe(10);
    expect(a.lerp(b, 0.5).toList()).toEqual([5, 0, 0]);
  });

  it("reflects a vector about a unit normal", () => {
    const v = new Vec3(1, -1, 0);
    const n = new Vec3(0, 1, 0);
    expect(v.reflect(n).toList()).toEqual([1, 1, 0]);
  });
});

describe("Quat", () => {
  it("identity has no rotation effect", () => {
    const q = Quat.identity();
    const v = new Vec3(1, 2, 3);
    const rotated = q.rotate(v);
    expect(approxEqual(rotated.x, v.x)).toBe(true);
    expect(approxEqual(rotated.y, v.y)).toBe(true);
    expect(approxEqual(rotated.z, v.z)).toBe(true);
  });

  it("from_euler/to_euler round-trips for a simple XYZ rotation", () => {
    const q = Quat.fromEuler(30, 45, 60, "XYZ");
    const [x, y, z] = q.toEuler("XYZ");
    expect(approxEqual(x, 30, 1e-6)).toBe(true);
    expect(approxEqual(y, 45, 1e-6)).toBe(true);
    expect(approxEqual(z, 60, 1e-6)).toBe(true);
  });

  it("fromAxisAngle rotates a vector 90 degrees around Z", () => {
    const q = Quat.fromAxisAngle(new Vec3(0, 0, 1), 90);
    const rotated = q.rotate(new Vec3(1, 0, 0));
    expect(approxEqual(rotated.x, 0, 1e-9)).toBe(true);
    expect(approxEqual(rotated.y, 1, 1e-9)).toBe(true);
    expect(approxEqual(rotated.z, 0, 1e-9)).toBe(true);
  });

  it("slerp interpolates and always takes the shortest arc", () => {
    const a = Quat.identity();
    const b = Quat.fromAxisAngle(new Vec3(0, 0, 1), 180);
    const mid = a.slerp(b, 0.5);
    const [, , z] = mid.toEuler("XYZ");
    expect(approxEqual(Math.abs(z), 90, 1e-6)).toBe(true);
  });

  it("multiply composes rotations and conjugate inverts a unit quaternion", () => {
    const q = Quat.fromAxisAngle(new Vec3(0, 0, 1), 45);
    const inv = q.conjugate();
    const identity = q.multiply(inv);
    expect(approxEqual(identity.w, 1, 1e-9)).toBe(true);
    expect(approxEqual(identity.x, 0, 1e-9)).toBe(true);
  });
});

describe("BoundingBox", () => {
  it("computes center, size, and volume", () => {
    const bbox = new BoundingBox(new Vec3(0, 0, 0), new Vec3(2, 4, 6));
    expect(bbox.center.toList()).toEqual([1, 2, 3]);
    expect(bbox.size.toList()).toEqual([2, 4, 6]);
    expect(bbox.volume).toBe(48);
  });

  it("contains and overlaps report correctly", () => {
    const a = new BoundingBox(new Vec3(0, 0, 0), new Vec3(10, 10, 10));
    const b = new BoundingBox(new Vec3(5, 5, 5), new Vec3(15, 15, 15));
    const c = new BoundingBox(new Vec3(20, 20, 20), new Vec3(30, 30, 30));
    expect(a.contains(new Vec3(5, 5, 5))).toBe(true);
    expect(a.contains(new Vec3(20, 20, 20))).toBe(false);
    expect(a.overlaps(b)).toBe(true);
    expect(a.overlaps(c)).toBe(false);
  });

  it("fromPoints computes the tight bounding box", () => {
    const bbox = BoundingBox.fromPoints([new Vec3(1, 5, -2), new Vec3(-3, 0, 8)]);
    expect(bbox.min.toList()).toEqual([-3, 0, -2]);
    expect(bbox.max.toList()).toEqual([1, 5, 8]);
  });

  it("expand and union grow the box as expected", () => {
    const a = new BoundingBox(new Vec3(0, 0, 0), new Vec3(1, 1, 1));
    expect(a.expand(1).min.toList()).toEqual([-1, -1, -1]);
    expect(a.expand(1).max.toList()).toEqual([2, 2, 2]);

    const b = new BoundingBox(new Vec3(5, 5, 5), new Vec3(6, 6, 6));
    const union = a.union(b);
    expect(union.min.toList()).toEqual([0, 0, 0]);
    expect(union.max.toList()).toEqual([6, 6, 6]);
  });
});

describe("AxisRemap", () => {
  it("Y_UP_TO_Z_UP swaps Y and Z with the documented sign convention", () => {
    const pos = new Vec3(1, 2, 3);
    const remapped = Y_UP_TO_Z_UP.applyVec3(pos);
    expect(remapped.toList()).toEqual([1, -3, 2]);
  });

  it("rejects a remap that does not reference each axis exactly once", () => {
    expect(() => new AxisRemap("x", "x", "z")).toThrow();
  });

  it("applyQuat throws for a reflective (determinant -1) remap", () => {
    const reflect = new AxisRemap("x", "y", "-z"); // det = -1
    expect(() => reflect.applyQuat(Quat.identity())).toThrow(/reflection/i);
    // apply_vec3 still works for a reflective remap
    expect(reflect.applyVec3(new Vec3(1, 2, 3)).toList()).toEqual([1, 2, -3]);
  });

  it("applyQuat rotates correctly for a proper (determinant +1) remap", () => {
    const remap = Y_UP_TO_Z_UP;
    const q = Quat.fromAxisAngle(new Vec3(0, 1, 0), 90); // rotation around DAZ's up axis
    const remappedQuat = remap.applyQuat(q);
    // Rotating a remapped vector by the remapped quat should equal remapping the rotated vector.
    const v = new Vec3(1, 0, 0);
    const lhs = remap.applyVec3(q.rotate(v));
    const rhs = remappedQuat.rotate(remap.applyVec3(v));
    expect(approxEqual(lhs.x, rhs.x, 1e-9)).toBe(true);
    expect(approxEqual(lhs.y, rhs.y, 1e-9)).toBe(true);
    expect(approxEqual(lhs.z, rhs.z, 1e-9)).toBe(true);
  });

  it("applyBbox remaps and re-sorts corners", () => {
    const bbox = new BoundingBox(new Vec3(0, 0, 0), new Vec3(1, 2, 3));
    const remapped = Y_UP_TO_Z_UP.applyBbox(bbox);
    expect(remapped.min.x).toBeLessThanOrEqual(remapped.max.x);
    expect(remapped.min.y).toBeLessThanOrEqual(remapped.max.y);
    expect(remapped.min.z).toBeLessThanOrEqual(remapped.max.z);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd daz-ts && npx vitest run test/unit/math3.test.ts`
Expected: FAIL — `../../src/math3.js` does not exist.

- [ ] **Step 3: Write `daz-ts/src/math3.ts`**

```ts
/**
 * Pure TypeScript 3D math for DAZ Studio workflows.
 *
 * No external dependencies. Mirrors dazpy's `math3.py` exactly, providing
 * {@link Vec3}, {@link Quat}, {@link BoundingBox}, and {@link AxisRemap}
 * with direct support for the dict shapes returned by the daz-ts API
 * (once Phase 2 proxy classes exist).
 */

// ── Vec3 ──────────────────────────────────────────────────────────────────

/** Immutable 3-component vector. All methods return new {@link Vec3} instances. */
export class Vec3 {
  readonly x: number;
  readonly y: number;
  readonly z: number;

  constructor(x: number, y: number, z: number) {
    this.x = x;
    this.y = y;
    this.z = z;
  }

  static fromDict(d: { x: number; y: number; z: number }): Vec3 {
    return new Vec3(d.x, d.y, d.z);
  }

  static fromList(v: number[]): Vec3 {
    return new Vec3(v[0], v[1], v[2]);
  }

  static zero(): Vec3 {
    return new Vec3(0, 0, 0);
  }

  toDict(): { x: number; y: number; z: number } {
    return { x: this.x, y: this.y, z: this.z };
  }

  toList(): number[] {
    return [this.x, this.y, this.z];
  }

  add(other: Vec3): Vec3 {
    return new Vec3(this.x + other.x, this.y + other.y, this.z + other.z);
  }

  sub(other: Vec3): Vec3 {
    return new Vec3(this.x - other.x, this.y - other.y, this.z - other.z);
  }

  mul(scalar: number): Vec3 {
    return new Vec3(this.x * scalar, this.y * scalar, this.z * scalar);
  }

  div(scalar: number): Vec3 {
    return new Vec3(this.x / scalar, this.y / scalar, this.z / scalar);
  }

  neg(): Vec3 {
    return new Vec3(-this.x, -this.y, -this.z);
  }

  equals(other: Vec3): boolean {
    return this.x === other.x && this.y === other.y && this.z === other.z;
  }

  dot(other: Vec3): number {
    return this.x * other.x + this.y * other.y + this.z * other.z;
  }

  cross(other: Vec3): Vec3 {
    return new Vec3(
      this.y * other.z - this.z * other.y,
      this.z * other.x - this.x * other.z,
      this.x * other.y - this.y * other.x,
    );
  }

  lengthSq(): number {
    return this.x * this.x + this.y * this.y + this.z * this.z;
  }

  length(): number {
    return Math.sqrt(this.lengthSq());
  }

  normalize(): Vec3 {
    const mag = this.length();
    if (mag < 1e-10) {
      return new Vec3(0, 0, 0);
    }
    return this.div(mag);
  }

  distanceSq(other: Vec3): number {
    return this.sub(other).lengthSq();
  }

  distance(other: Vec3): number {
    return Math.sqrt(this.distanceSq(other));
  }

  lerp(other: Vec3, t: number): Vec3 {
    return new Vec3(
      this.x + (other.x - this.x) * t,
      this.y + (other.y - this.y) * t,
      this.z + (other.z - this.z) * t,
    );
  }

  /** Reflect this vector about `normal` (must be unit length). */
  reflect(normal: Vec3): Vec3 {
    return this.sub(normal.mul(2 * this.dot(normal)));
  }
}

// ── Quat ──────────────────────────────────────────────────────────────────

type RotationOrder = "XYZ" | "XZY" | "YXZ" | "YZX" | "ZXY" | "ZYX";

function eulerToQuat(hx: number, hy: number, hz: number, order: RotationOrder): [number, number, number, number] {
  const cx = Math.cos(hx), sx = Math.sin(hx);
  const cy = Math.cos(hy), sy = Math.sin(hy);
  const cz = Math.cos(hz), sz = Math.sin(hz);

  switch (order) {
    case "XYZ":
      return [sx*cy*cz + cx*sy*sz, cx*sy*cz - sx*cy*sz, cx*cy*sz + sx*sy*cz, cx*cy*cz - sx*sy*sz];
    case "XZY":
      return [sx*cy*cz - cx*sy*sz, cx*sy*cz - sx*cy*sz, cx*cy*sz + sx*sy*cz, cx*cy*cz + sx*sy*sz];
    case "YXZ":
      return [sx*cy*cz + cx*sy*sz, cx*sy*cz - sx*cy*sz, cx*cy*sz - sx*sy*cz, cx*cy*cz + sx*sy*sz];
    case "YZX":
      return [sx*cy*cz + cx*sy*sz, cx*sy*cz + sx*cy*sz, cx*cy*sz - sx*sy*cz, cx*cy*cz - sx*sy*sz];
    case "ZXY":
      return [sx*cy*cz - cx*sy*sz, cx*sy*cz + sx*cy*sz, cx*cy*sz + sx*sy*cz, cx*cy*cz - sx*sy*sz];
    case "ZYX":
      return [sx*cy*cz - cx*sy*sz, cx*sy*cz + sx*cy*sz, cx*cy*sz - sx*sy*cz, cx*cy*cz - sx*sy*sz];
    default:
      throw new Error(`Unknown rotation order: ${String(order)}. Expected one of XYZ XZY YXZ YZX ZXY ZYX.`);
  }
}

function quatToEuler(m: number[][], order: RotationOrder): [number, number, number] {
  const SAFE = 1.0 - 1e-6;
  const clamp = (v: number) => Math.max(-1, Math.min(1, v));
  const deg = (r: number) => (r * 180) / Math.PI;

  switch (order) {
    case "XYZ": {
      const sy = clamp(m[0][2]);
      const y = deg(Math.asin(sy));
      if (Math.abs(sy) < SAFE) {
        return [deg(Math.atan2(-m[1][2], m[2][2])), y, deg(Math.atan2(-m[0][1], m[0][0]))];
      }
      return [deg(Math.atan2(m[2][1], m[1][1])), y, 0];
    }
    case "XZY": {
      const sz = clamp(-m[0][1]);
      const z = deg(Math.asin(sz));
      if (Math.abs(sz) < SAFE) {
        return [deg(Math.atan2(m[2][1], m[1][1])), deg(Math.atan2(m[0][2], m[0][0])), z];
      }
      return [deg(Math.atan2(-m[1][2], m[2][2])), 0, z];
    }
    case "YXZ": {
      const sx = clamp(-m[1][2]);
      const x = deg(Math.asin(sx));
      if (Math.abs(sx) < SAFE) {
        return [x, deg(Math.atan2(m[0][2], m[2][2])), deg(Math.atan2(m[1][0], m[1][1]))];
      }
      return [x, deg(Math.atan2(-m[0][1], m[0][0])), 0];
    }
    case "YZX": {
      const sz = clamp(m[1][0]);
      const z = deg(Math.asin(sz));
      if (Math.abs(sz) < SAFE) {
        return [deg(Math.atan2(-m[1][2], m[1][1])), deg(Math.atan2(-m[2][0], m[0][0])), z];
      }
      return [deg(Math.atan2(m[0][1], m[2][1])), 0, z];
    }
    case "ZXY": {
      const sx = clamp(m[2][1]);
      const x = deg(Math.asin(sx));
      if (Math.abs(sx) < SAFE) {
        return [x, deg(Math.atan2(-m[2][0], m[2][2])), deg(Math.atan2(-m[0][1], m[1][1]))];
      }
      return [x, deg(Math.atan2(m[0][2], m[0][0])), 0];
    }
    case "ZYX": {
      const sy = clamp(-m[2][0]);
      const y = deg(Math.asin(sy));
      if (Math.abs(sy) < SAFE) {
        return [deg(Math.atan2(m[2][1], m[2][2])), y, deg(Math.atan2(m[1][0], m[0][0]))];
      }
      return [deg(Math.atan2(-m[0][1], m[1][1])), y, 0];
    }
    default:
      throw new Error(`Unknown rotation order: ${String(order)}. Expected one of XYZ XZY YXZ YZX ZXY ZYX.`);
  }
}

/**
 * Unit quaternion representing a 3D rotation.
 *
 * Stored as `(x, y, z, w)` — imaginary components first, scalar last —
 * matching the dict format returned by the DAZ Studio Script Server API.
 * All methods return new {@link Quat} instances.
 */
export class Quat {
  readonly x: number;
  readonly y: number;
  readonly z: number;
  readonly w: number;

  constructor(x: number, y: number, z: number, w: number) {
    this.x = x;
    this.y = y;
    this.z = z;
    this.w = w;
  }

  static identity(): Quat {
    return new Quat(0, 0, 0, 1);
  }

  static fromDict(d: { x: number; y: number; z: number; w: number }): Quat {
    return new Quat(d.x, d.y, d.z, d.w);
  }

  /** Create from Euler angles in degrees using intrinsic rotations (DAZ Studio's bone-rotation convention). */
  static fromEuler(x: number, y: number, z: number, order: RotationOrder = "XYZ"): Quat {
    const hx = ((x * Math.PI) / 180) * 0.5;
    const hy = ((y * Math.PI) / 180) * 0.5;
    const hz = ((z * Math.PI) / 180) * 0.5;
    const [qx, qy, qz, qw] = eulerToQuat(hx, hy, hz, order);
    return new Quat(qx, qy, qz, qw);
  }

  static fromAxisAngle(axis: Vec3, angleDeg: number): Quat {
    const n = axis.normalize();
    const half = ((angleDeg * Math.PI) / 180) * 0.5;
    const s = Math.sin(half);
    return new Quat(n.x * s, n.y * s, n.z * s, Math.cos(half));
  }

  toDict(): { x: number; y: number; z: number; w: number } {
    return { x: this.x, y: this.y, z: this.z, w: this.w };
  }

  /** Return the equivalent 3x3 rotation matrix (row-major, right-handed). */
  toMatrix(): number[][] {
    const { x, y, z, w } = this;
    const x2 = 2 * x * x, y2 = 2 * y * y, z2 = 2 * z * z;
    const xy = 2 * x * y, xz = 2 * x * z, yz = 2 * y * z;
    const wx = 2 * w * x, wy = 2 * w * y, wz = 2 * w * z;
    return [
      [1 - y2 - z2, xy - wz, xz + wy],
      [xy + wz, 1 - x2 - z2, yz - wx],
      [xz - wy, yz + wx, 1 - x2 - y2],
    ];
  }

  /** Extract Euler angles in degrees. Inverse of {@link fromEuler} for the same `order`. */
  toEuler(order: RotationOrder = "XYZ"): [number, number, number] {
    return quatToEuler(this.toMatrix(), order);
  }

  /** Hamilton product `this * other`. */
  multiply(other: Quat): Quat {
    const { x: ax, y: ay, z: az, w: aw } = this;
    const { x: bx, y: by, z: bz, w: bw } = other;
    return new Quat(
      aw * bx + ax * bw + ay * bz - az * by,
      aw * by - ax * bz + ay * bw + az * bx,
      aw * bz + ax * by - ay * bx + az * bw,
      aw * bw - ax * bx - ay * by - az * bz,
    );
  }

  conjugate(): Quat {
    return new Quat(-this.x, -this.y, -this.z, this.w);
  }

  length(): number {
    return Math.sqrt(this.x ** 2 + this.y ** 2 + this.z ** 2 + this.w ** 2);
  }

  normalize(): Quat {
    const mag = this.length();
    if (mag < 1e-10) {
      return Quat.identity();
    }
    return new Quat(this.x / mag, this.y / mag, this.z / mag, this.w / mag);
  }

  dot(other: Quat): number {
    return this.x * other.x + this.y * other.y + this.z * other.z + this.w * other.w;
  }

  /** Rotate vector `v` by this quaternion (sandwich product `q * v * q⁻¹`). */
  rotate(v: Vec3): Vec3 {
    const { x: qx, y: qy, z: qz, w: qw } = this;
    const { x: vx, y: vy, z: vz } = v;
    const tx = 2 * (qy * vz - qz * vy);
    const ty = 2 * (qz * vx - qx * vz);
    const tz = 2 * (qx * vy - qy * vx);
    return new Vec3(vx + qw * tx + qy * tz - qz * ty, vy + qw * ty + qz * tx - qx * tz, vz + qw * tz + qx * ty - qy * tx);
  }

  /** Spherical linear interpolation. Always takes the shortest arc. */
  slerp(other: Quat, t: number): Quat {
    let o = other;
    let d = this.dot(o);
    if (d < 0) {
      o = new Quat(-o.x, -o.y, -o.z, -o.w);
      d = -d;
    }
    d = Math.min(1, d);

    if (d > 0.9995) {
      const result = new Quat(
        this.x + t * (o.x - this.x),
        this.y + t * (o.y - this.y),
        this.z + t * (o.z - this.z),
        this.w + t * (o.w - this.w),
      );
      return result.normalize();
    }

    const theta0 = Math.acos(d);
    const sinTheta0 = Math.sin(theta0);
    const theta = theta0 * t;
    const sinTheta = Math.sin(theta);
    const cosTheta = Math.cos(theta);

    const s0 = cosTheta - (d * sinTheta) / sinTheta0;
    const s1 = sinTheta / sinTheta0;

    return new Quat(s0 * this.x + s1 * o.x, s0 * this.y + s1 * o.y, s0 * this.z + s1 * o.z, s0 * this.w + s1 * o.w);
  }

  equals(other: Quat): boolean {
    return this.x === other.x && this.y === other.y && this.z === other.z && this.w === other.w;
  }
}

// ── BoundingBox ───────────────────────────────────────────────────────────

/** Axis-aligned bounding box. */
export class BoundingBox {
  readonly min: Vec3;
  readonly max: Vec3;

  constructor(min: Vec3, max: Vec3) {
    this.min = min;
    this.max = max;
  }

  static fromDict(d: { min: { x: number; y: number; z: number }; max: { x: number; y: number; z: number } }): BoundingBox {
    return new BoundingBox(Vec3.fromDict(d.min), Vec3.fromDict(d.max));
  }

  static fromPoints(points: Vec3[]): BoundingBox {
    if (points.length === 0) {
      throw new Error("fromPoints requires at least one point");
    }
    const xs = points.map((p) => p.x);
    const ys = points.map((p) => p.y);
    const zs = points.map((p) => p.z);
    return new BoundingBox(
      new Vec3(Math.min(...xs), Math.min(...ys), Math.min(...zs)),
      new Vec3(Math.max(...xs), Math.max(...ys), Math.max(...zs)),
    );
  }

  toDict(): { min: { x: number; y: number; z: number }; max: { x: number; y: number; z: number } } {
    return { min: this.min.toDict(), max: this.max.toDict() };
  }

  get center(): Vec3 {
    return new Vec3((this.min.x + this.max.x) * 0.5, (this.min.y + this.max.y) * 0.5, (this.min.z + this.max.z) * 0.5);
  }

  get size(): Vec3 {
    return this.max.sub(this.min);
  }

  get volume(): number {
    const s = this.size;
    return s.x * s.y * s.z;
  }

  contains(point: Vec3): boolean {
    return (
      this.min.x <= point.x && point.x <= this.max.x &&
      this.min.y <= point.y && point.y <= this.max.y &&
      this.min.z <= point.z && point.z <= this.max.z
    );
  }

  overlaps(other: BoundingBox): boolean {
    return (
      this.min.x <= other.max.x && this.max.x >= other.min.x &&
      this.min.y <= other.max.y && this.max.y >= other.min.y &&
      this.min.z <= other.max.z && this.max.z >= other.min.z
    );
  }

  expand(amount: number): BoundingBox {
    const v = new Vec3(amount, amount, amount);
    return new BoundingBox(this.min.sub(v), this.max.add(v));
  }

  union(other: BoundingBox): BoundingBox {
    return new BoundingBox(
      new Vec3(Math.min(this.min.x, other.min.x), Math.min(this.min.y, other.min.y), Math.min(this.min.z, other.min.z)),
      new Vec3(Math.max(this.max.x, other.max.x), Math.max(this.max.y, other.max.y), Math.max(this.max.z, other.max.z)),
    );
  }
}

// ── AxisRemap ─────────────────────────────────────────────────────────────

const AXIS_INDEX: Record<string, number> = { x: 0, y: 1, z: 2 };

function parseAxisSpec(spec: string): [number, number] {
  if (!spec) {
    throw new Error(`Invalid axis spec ${JSON.stringify(spec)}; expected one of x, y, z, -x, -y, -z`);
  }
  let sign = 1;
  let name = spec;
  if (name[0] === "+" || name[0] === "-") {
    sign = name[0] === "-" ? -1 : 1;
    name = name.slice(1);
  }
  if (!(name in AXIS_INDEX)) {
    throw new Error(`Invalid axis spec ${JSON.stringify(spec)}; expected one of x, y, z, -x, -y, -z`);
  }
  return [AXIS_INDEX[name], sign];
}

function mat3Det(m: number[][]): number {
  return (
    m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) -
    m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) +
    m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
  );
}

function mat3ToQuat(m: number[][]): Quat {
  const trace = m[0][0] + m[1][1] + m[2][2];
  let x: number, y: number, z: number, w: number;
  if (trace > 0) {
    const s = Math.sqrt(trace + 1.0) * 2.0;
    w = 0.25 * s;
    x = (m[2][1] - m[1][2]) / s;
    y = (m[0][2] - m[2][0]) / s;
    z = (m[1][0] - m[0][1]) / s;
  } else if (m[0][0] > m[1][1] && m[0][0] > m[2][2]) {
    const s = Math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2.0;
    w = (m[2][1] - m[1][2]) / s;
    x = 0.25 * s;
    y = (m[0][1] + m[1][0]) / s;
    z = (m[0][2] + m[2][0]) / s;
  } else if (m[1][1] > m[2][2]) {
    const s = Math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2.0;
    w = (m[0][2] - m[2][0]) / s;
    x = (m[0][1] + m[1][0]) / s;
    y = 0.25 * s;
    z = (m[1][2] + m[2][1]) / s;
  } else {
    const s = Math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2.0;
    w = (m[1][0] - m[0][1]) / s;
    x = (m[0][2] + m[2][0]) / s;
    y = (m[1][2] + m[2][1]) / s;
    z = 0.25 * s;
  }
  return new Quat(x, y, z, w);
}

/**
 * Converts {@link Vec3}, {@link Quat}, and {@link BoundingBox} values
 * between axis conventions (e.g. Y-up to Z-up).
 *
 * A generic signed-axis-permutation remap. Each of `x`, `y`, `z` names
 * which source axis (optionally signed) the corresponding output axis is
 * derived from. All three source axes must be referenced exactly once
 * (signs aside).
 */
export class AxisRemap {
  private readonly specs: Array<[number, number]>;
  private readonly rotationQuat: Quat | null;

  constructor(x: string, y: string, z: string) {
    const specs: Array<[number, number]> = [parseAxisSpec(x), parseAxisSpec(y), parseAxisSpec(z)];
    const used = specs.map(([idx]) => idx).sort();
    if (used.join(",") !== "0,1,2") {
      throw new Error(`AxisRemap must reference each of x, y, z exactly once (got x=${x}, y=${y}, z=${z})`);
    }
    const matrix: number[][] = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
    specs.forEach(([idx, sign], row) => {
      matrix[row][idx] = sign;
    });
    const det = mat3Det(matrix);
    this.specs = specs;
    this.rotationQuat = det > 0 ? mat3ToQuat(matrix) : null;
  }

  /** Remap a vector or point. Works for any remap, proper or reflective. */
  applyVec3(v: Vec3): Vec3 {
    const comps = [v.x, v.y, v.z];
    const out = this.specs.map(([idx, sign]) => comps[idx] * sign);
    return new Vec3(out[0], out[1], out[2]);
  }

  /**
   * Remap a rotation.
   * @throws {Error} If this remap is a reflection (determinant -1). Use
   * {@link applyVec3} for vectors/points instead.
   */
  applyQuat(q: Quat): Quat {
    if (this.rotationQuat === null) {
      throw new Error(
        "AxisRemap represents a reflection (determinant -1); cannot remap a Quat. Use applyVec3 for vectors/points instead.",
      );
    }
    const r = this.rotationQuat;
    return r.multiply(q).multiply(r.conjugate());
  }

  /** Remap a bounding box. Both corners are remapped and re-sorted per axis. */
  applyBbox(b: BoundingBox): BoundingBox {
    const p1 = this.applyVec3(b.min);
    const p2 = this.applyVec3(b.max);
    const lo = new Vec3(Math.min(p1.x, p2.x), Math.min(p1.y, p2.y), Math.min(p1.z, p2.z));
    const hi = new Vec3(Math.max(p1.x, p2.x), Math.max(p1.y, p2.y), Math.max(p1.z, p2.z));
    return new BoundingBox(lo, hi);
  }
}

/**
 * Converts DAZ Studio's Y-up convention to a Z-up convention (e.g. Blender,
 * glTF-consuming tools converted to Z-up). Up (+Y) becomes +Z; DAZ's
 * forward (+Z) becomes -Y.
 */
export const Y_UP_TO_Z_UP = new AxisRemap("x", "-z", "y");
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd daz-ts && npx vitest run test/unit/math3.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add daz-ts/src/math3.ts daz-ts/test/unit/math3.test.ts
git commit -m "$(cat <<'EOF'
feat(daz-ts): port math3 (Vec3, Quat, BoundingBox, AxisRemap)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Cv6wGgj4P2TmYmPbBHUafn
EOF
)"
```

---

### Task 11: Injection-safety suite

**Files:**
- Test: `daz-ts/test/unit/injectionSafety.test.ts`

**Interfaces:**
- Consumes: `DazClient` (`./client.js`), `ScriptBuilder` (`./scriptBuilder.js`), `Batch` (`./batch.js`) — no new production code.

- [ ] **Step 1: Write the test**

Create `daz-ts/test/unit/injectionSafety.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { Batch } from "../../src/batch.js";
import { DazClient } from "../../src/client.js";
import { ScriptBuilder } from "../../src/scriptBuilder.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const ADVERSARIAL_STRINGS = [
  `"; Scene.deleteAllNodes(); //`,
  "line1\nline2\r\nline3",
  "unicode: \u2028\u2029\u0000",
  "backslashes: \\\\ \\n \\\" ",
  "'single quotes' and \"double quotes\"",
  "</script><script>alert(1)</script>",
  "very-long-" + "x".repeat(10_000),
];

describe("injection safety", () => {
  it("ScriptBuilder.escapeString produces a value that JSON.parse recovers unchanged", () => {
    for (const input of ADVERSARIAL_STRINGS) {
      const escaped = ScriptBuilder.escapeString(input);
      expect(JSON.parse(escaped)).toBe(input);
      // The escaped form must not contain an unescaped double-quote or raw newline
      // that would break out of the string literal in generated DazScript.
      const inner = escaped.slice(1, -1);
      expect(inner).not.toMatch(/(?<!\\)"/);
      expect(inner).not.toMatch(/\n/);
    }
  });

  it("ScriptBuilder.serializeArg never lets adversarial strings escape their quotes", () => {
    for (const input of ADVERSARIAL_STRINGS) {
      const serialized = ScriptBuilder.serializeArg(input);
      expect(JSON.parse(serialized)).toBe(input);
    }
  });

  it("DazClient.execute JSON-encodes args, never string-concatenates them into the script", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ success: true, result: null, output: [], request_id: "r1", duration_ms: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    for (const input of ADVERSARIAL_STRINGS) {
      await client.execute("f(getArguments()[0]);", input);
      const [, init] = fetchMock.mock.calls.at(-1)!;
      const body = JSON.parse(init.body as string);
      // args travels as a JSON payload field, never spliced into the script string.
      expect(body.args).toBe(input);
      expect(body.script).toBe("f(getArguments()[0]);");
    }
  });

  it("Batch.addOperation embeds adversarial result expressions without corrupting the combined script's JSON payload", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ success: true, result: { _r0: "ok" }, output: [], request_id: "r1", duration_ms: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DazClient({ token: "" });
    for (const input of ADVERSARIAL_STRINGS.slice(0, 4)) {
      const batch = new Batch(client);
      const future = batch.addOperation([`var s = ${ScriptBuilder.escapeString(input)};`], "s");
      await batch.execute();
      const [, init] = fetchMock.mock.calls.at(-1)!;
      // The whole HTTP payload must remain valid JSON even though the script
      // string itself contains an embedded, escaped adversarial literal.
      expect(() => JSON.parse(init.body as string)).not.toThrow();
      void future;
    }
  });
});
```

- [ ] **Step 2: Run the test**

Run: `cd daz-ts && npx vitest run test/unit/injectionSafety.test.ts`
Expected: PASS immediately — this task adds no new production code, only a regression suite over Tasks 3-4 and 8's existing implementation. If any assertion fails, it indicates a bug in `ScriptBuilder`, `DazClient.execute`, or `Batch` introduced in an earlier task — go back and fix that task's implementation, do not weaken this test.

- [ ] **Step 3: Run the full unit suite**

Run: `cd daz-ts && npm test`
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add daz-ts/test/unit/injectionSafety.test.ts
git commit -m "$(cat <<'EOF'
test(daz-ts): add injection-safety regression suite

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Cv6wGgj4P2TmYmPbBHUafn
EOF
)"
```

---

### Task 12: Public exports, gated integration test, and CI workflow

**Files:**
- Modify: `daz-ts/src/index.ts`
- Create: `daz-ts/test/integration/client.integration.test.ts`
- Create: `.github/workflows/build-daz-ts.yml`

**Interfaces:**
- Produces: the finished public surface of the `daz-ts` package for Phase 1 (everything importable from `daz-ts`).

- [ ] **Step 1: Write `daz-ts/src/index.ts`**

```ts
export { DazClient } from "./client.js";
export type { DazClientOptions, RetryOptions, RenderSubmitOptions, ExportUsdOptions } from "./client.js";
export { parseSseStream } from "./client.js";

export type { ExecutionResult } from "./result.js";

export {
  AsyncExecutionError,
  AuthenticationError,
  BatchLimitExceededError,
  ConcurrencyLimitError,
  ConnectionError,
  DazBusyError,
  DazError,
  DazTimeoutError,
  MaterialError,
  NodeNotFoundError,
  RenderError,
  ScriptError,
  ScriptRuntimeError,
  ScriptSyntaxError,
  StudioBusyError,
} from "./exceptions.js";

export { ScriptBuilder } from "./scriptBuilder.js";

export { Batch, BatchFuture, buildOperationsScript } from "./batch.js";
export type { BatchOptions } from "./batch.js";

export { executeLong } from "./polling.js";
export type { ExecuteLongOptions } from "./polling.js";

export { AxisRemap, BoundingBox, Quat, Vec3, Y_UP_TO_Z_UP } from "./math3.js";
```

- [ ] **Step 2: Write the gated integration test**

Create `daz-ts/test/integration/client.integration.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { DazClient } from "../../src/index.js";

const SERVER_URL = process.env.DAZ_SERVER_URL;

describe.skipIf(!SERVER_URL)("DazClient live integration", () => {
  it("executes a trivial script against a real DazScriptServer instance", async () => {
    const url = new URL(SERVER_URL!);
    const client = new DazClient({ host: url.hostname, port: Number(url.port) || 18811 });

    const result = await client.execute("1 + 1;");

    expect(result.success).toBe(true);
    expect(result.value).toBe(2);
  });

  it("round-trips server status", async () => {
    const url = new URL(SERVER_URL!);
    const client = new DazClient({ host: url.hostname, port: Number(url.port) || 18811 });

    const status = await client.status();

    expect(status).toHaveProperty("version");
  });
});
```

Note: this mirrors dazpy's `skip_no_daz` pattern — `describe.skipIf` reports the suite as skipped (not failed) when `DAZ_SERVER_URL` is unset, exactly like `unittest.skipUnless`.

- [ ] **Step 3: Run the integration test file with no server configured to confirm it skips cleanly**

Run: `cd daz-ts && npx vitest run test/integration/client.integration.test.ts`
Expected: Reports the suite as **skipped**, not failed (no `DAZ_SERVER_URL` set in this environment).

- [ ] **Step 4: If a live DazScriptServer instance is reachable, run the integration test against it**

Run (only if you have DAZ Studio + the plugin running locally):
```bash
cd daz-ts && DAZ_SERVER_URL=http://127.0.0.1:18811 npx vitest run test/integration/client.integration.test.ts
```
Expected: PASS. If it fails, investigate whether the live server's response shape has drifted from what Tasks 4-9 assumed — fix the implementation, not the test, unless the assumption was wrong.

- [ ] **Step 5: Create `.github/workflows/build-daz-ts.yml`**

```yaml
name: Build daz-ts Package

on:
  workflow_call:
    outputs:
      artifact-name:
        description: 'Name of the uploaded artifact'
        value: ${{ jobs.build.outputs.artifact-name }}

jobs:
  build:
    runs-on: ubuntu-latest
    outputs:
      artifact-name: ${{ steps.upload.outputs.artifact-name }}

    defaults:
      run:
        working-directory: daz-ts

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'

      - name: Install dependencies
        run: npm ci

      - name: Build
        run: npm run build

      - name: Run unit tests
        run: npm test

      - name: Pack tarball
        run: npm pack --pack-destination dist-pack

      - name: Verify pack artifact
        run: |
          TARBALL=$(ls dist-pack/daz-ts-*.tgz 2>/dev/null | head -1)
          if [ -z "$TARBALL" ]; then
            echo "Error: daz-ts tarball not found in dist-pack/"
            exit 1
          fi
          echo "Artifact built successfully:"
          ls -lh dist-pack/

      - name: Upload dist artifact
        id: upload
        uses: actions/upload-artifact@v4
        with:
          name: daz-ts-dist
          path: daz-ts/dist-pack/
          if-no-files-found: error
```

- [ ] **Step 6: Run the full build + unit test suite one final time**

Run:
```bash
cd daz-ts && npm run build && npm test
```
Expected: `tsc` builds with zero errors (strict mode); all unit tests PASS.

- [ ] **Step 7: Commit**

```bash
git add daz-ts/src/index.ts daz-ts/test/integration/client.integration.test.ts .github/workflows/build-daz-ts.yml
git commit -m "$(cat <<'EOF'
feat(daz-ts): finalize Phase 1 public exports, gated integration test, CI build

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Cv6wGgj4P2TmYmPbBHUafn
EOF
)"
```

- [ ] **Step 8: Close the beads issue for this phase**

```bash
bd close daz-script-server-xtni --reason="Phase 1 (client core, exceptions, batching, math3) implemented and tested per docs/superpowers/plans/2026-09-06-daz-ts-phase1.md"
```

---

## Self-Review Notes (for the plan author / next reviewer)

- **Spec coverage**: every Phase 1 item from `docs/superpowers/specs/2026-09-06-daz-ts-design.md` has a task — `DazClient` (Tasks 4-7), `ExecutionResult`/exceptions (Task 2), `ScriptBuilder` (Task 3), `Batch`/`BatchFuture` (Task 8), `executeLong` (Task 9), SSE plumbing (Task 7), `math3.ts` (Task 10), injection safety (Task 11), CI (Task 12).
- **Type consistency check**: `ExecutionResult.durationMs`/`requestId` (Task 2) are produced consistently by `mapResponse` (Task 4) and `executeLong` (Task 9). `Batch`'s `BatchOptions.maxOperations`/`maxScriptLength` (Task 8) match the constructor destructuring. `RetryOptions` (Task 4) is reused unchanged by Tasks 5-6.
- **Deferred to Phase 2+**: `NodeIdentifier`, `DazElement`, and the rest of the proxy/scene-graph layer, `DazRenderSettings`/`Canvas`/high-level `render()` helpers, domain modules, and `interaction.ts` — none of these belong in Phase 1 per the spec's phasing, and none of Phase 1's tasks depend on them.
