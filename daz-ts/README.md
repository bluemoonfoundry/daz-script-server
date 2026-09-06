# daz-ts

TypeScript SDK for [DazScriptServer](../README.md), the HTTP server plugin
that embeds an HTTP API inside DAZ Studio for remotely executing DazScript
code. `daz-ts` is the Node.js/TypeScript counterpart to
[`dazpy`](../dazpy), the mature Python SDK — same wire protocol, same
server, a single `DazClient` class (no sync/async split; `async`/`await`
covers both). This is a Phase 1 release: client core (`execute`, async job
submission/polling, batching, render/USD submission, SSE plumbing) plus a
dependency-free `math3` module. Scene-graph proxies (nodes, materials,
skeletons, etc.) land in a later phase.

## Install

`daz-ts` is not published to the public npm registry. Install it as a git
dependency (npm runs the package's `prepare` script automatically, which
builds `dist/`):

```bash
npm install github:<owner>/<repo>#<branch-or-tag> --workspace-path daz-ts
# or, pointing at a subdirectory of this monorepo:
npm install "github:<owner>/<repo>#<ref>:daz-ts"
```

Alternatively, download the `daz-ts-*.tgz` tarball attached to a
[GitHub release](../../../releases) and install it directly:

```bash
npm install ./daz-ts-0.1.0.tgz
```

Requires Node.js >= 18 (for built-in `fetch`/`AbortController`).

## Auth

Same convention as `dazpy`: requests carry an `X-API-Token` header. By
default, `DazClient` auto-loads the token from
`~/.daz3d/dazscriptserver_token.txt` (the file DazScriptServer writes on
first run). You can also pass a token explicitly, or pass `token: ""` to
disable authentication (only if the server has auth disabled too):

```ts
import { DazClient } from "daz-ts";

const client = new DazClient(); // auto-loads token from ~/.daz3d/...
const explicit = new DazClient({ token: "your-token-here" });
const noAuth = new DazClient({ token: "" });
```

`DazClientOptions` also accepts `host` (default `"127.0.0.1"`), `port`
(default `18811`), and `timeoutMs` (default `30000`).

## Usage

### `DazClient.execute()`

Run a DazScript string synchronously and get back its result, captured
console output, and timing:

```ts
import { DazClient } from "daz-ts";

const client = new DazClient();

const result = await client.execute("2 + 2;");
console.log(result.value); // 4
console.log(result.output); // string[] of captured log lines
console.log(result.durationMs);
```

Pass a JSON-serializable `args` value as the script's `getArguments()[0]`:

```ts
await client.execute("var n = getArguments()[0].count; n * 2;", { count: 21 });
```

Script errors and busy/authentication failures throw typed exceptions
(`ScriptSyntaxError`, `ScriptRuntimeError`, `StudioBusyError`,
`ConcurrencyLimitError`, `AuthenticationError`, `ConnectionError`,
`DazTimeoutError`, ...) — see `src/exceptions.ts` for the full hierarchy.
Any method that accepts a trailing `{ retryOnBusy, maxWait }` option
(`RetryOptions`) will transparently retry with linear backoff on
`StudioBusyError`/`ConcurrencyLimitError` instead of throwing immediately:

```ts
await client.execute("doSomethingSlow();", undefined, { retryOnBusy: true, maxWait: 30 });
```

### `Batch`

Collect multiple operations and run them as a single HTTP round-trip
(one script, one `/execute` call). Execution is **serial**, with **no
parallelism** and **no transactionality** — a failing operation fails the
whole call, and earlier mutations already applied to the live scene are
**not** rolled back:

```ts
import { Batch, DazClient } from "daz-ts";

const client = new DazClient();
const batch = new Batch(client); // options: { maxOperations, maxScriptLength }

const nameFuture = batch.addOperation(["var n = Scene.findNode('Genesis9');"], "n.getLabel()");
const posFuture = batch.addOperation(
  ["var n = Scene.findNode('Genesis9');", "var p = n.getWSPos();"],
  "[p.x, p.y, p.z]",
);

await batch.execute(); // one HTTP call resolves every future

console.log(nameFuture.value, posFuture.value);
```

`addPrelude(preludeKey, lines)` registers a shared setup block emitted once
per unique key, useful when several operations depend on the same lookup.
`DazClient.executeBatchAsync(operations, args?)` submits the same
single-script batch shape to the async endpoint (`/execute/async`) for
long-running batches — poll it like any other async request.

### `executeLong()`

Run a potentially long-running script via the async endpoint, with polling
handled for you:

```ts
import { executeLong } from "daz-ts";

const result = await executeLong(client, "renderEverything();", undefined, {
  timeoutMs: 300_000, // default 120000
  pollIntervalMs: 500, // default 500
});
```

It submits the script with `executeAsyncSubmit`, then long-polls
`/requests/:id/result` until the script completes, fails, is cancelled, or
`timeoutMs` elapses (throwing `AsyncExecutionError` or `DazTimeoutError`
respectively).

## What else is here

- `math3.ts` — dependency-free `Vec3`, `Quat`, `BoundingBox`, `AxisRemap`
  math utilities (no HTTP coupling).
- `ScriptBuilder` — the injection-safety helpers (`escapeString`, `iife`,
  `serializeArg`) used internally to build generated DazScript source; every
  injected string goes through `JSON.stringify`.
- Render/USD-export submission methods (`renderSubmit`, `renderBatchSubmit`,
  `renderAnimationSubmit`, `exportUsdSubmit`, ...) and SSE streaming helpers
  (`streamRenderProgress`, `streamSceneEvents`, `parseSseStream`) on
  `DazClient` — see `src/client.ts` for full signatures.

See `docs/superpowers/specs/2026-09-06-daz-ts-design.md` (in the repo root)
for the full design spec and phased roadmap.
