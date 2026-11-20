# Documentation index

Where each document lives. The full HTTP API reference is the top-level
[README](../README.md); [`openapi.yaml`](../openapi.yaml) is the route list.

## Using the server and SDKs

| Document | What it covers |
|---|---|
| [README](../README.md) | Install, settings, HTTP API reference, security |
| [openapi.yaml](../openapi.yaml) | Machine-readable spec for every route (CI checks it against the code) |
| [MIGRATION.md](../MIGRATION.md) | Upgrade notes between plugin versions |
| [CHANGELOG.md](../CHANGELOG.md) | Release history |
| [SECURITY.md](../SECURITY.md) | Supported versions and how to report a vulnerability |
| [dazpy docs](index.rst) | Sphinx site for the Python SDK: [quickstart](quickstart.rst), [scene recipes](scene_recipes.rst), [API reference](api/index.rst) |
| [daz-ts README](../daz-ts/README.md) | TypeScript SDK |
| [examples/](examples/README.md) | Pointer to the examples repository, plus [sample scene recipes](examples/recipes/) |

## Working on the code

| Document | What it covers |
|---|---|
| [CONTRIBUTING.md](../CONTRIBUTING.md) | Dev setup, build, tests, code style, PR checklist |
| [ARCHITECTURE.md](../ARCHITECTURE.md) | Threading model, request flow, job routes |
| [LIVE_SMOKE.md](LIVE_SMOKE.md) | Live smoke matrix (`tests/smoke_live.py`) against DS4/DS6 before a release |
| [smoke-results/](smoke-results/README.md) | Recorded smoke runs, one file per release and SDK |
| [REVIEW_FOLLOWUPS.md](REVIEW_FOLLOWUPS.md) | Open findings from the 2026-11-19 repo review |

## Design and planning

| Document | What it covers |
|---|---|
| [MCP_SERVER_DESIGN.md](MCP_SERVER_DESIGN.md) | Evaluation and design of an MCP server layered on the HTTP API |
| [superpowers/specs/](superpowers/specs/) | Feature design specs, one per feature |
| [superpowers/plans/](superpowers/plans/) | Implementation plans for features still in progress |
| [superpowers/plans/archive/](superpowers/plans/archive/) | Plans for features that have shipped, kept for history |
| [archive/](archive/README.md) | Older plans and assessments that no longer describe the code |

Open work is tracked in beads (`bd ready`), not in these documents.
