# Live smoke-test matrix

CI builds the plugin and runs the unit suite, but never talks to a real DAZ
Studio. `tests/smoke_live.py` is the scoped live check that fills that gap. Run
it by hand, or on a self-hosted runner, against each SDK build before a
release.

It is **not** the full integration suite. Running `test_dazpy_integration.py`
in full against a live Studio has frozen it before. Every smoke stage is
bounded: one 64×64 render per engine (Iray capped at 4 samples), a few
one-line scripts, and read-only MCP tools.

## What it checks

| Stage | Checks |
|---|---|
| `api` | `/status`, `/health`, `/capabilities` shape, sync `/execute` (plain + `args`), DAZ globals reachable, `SCRIPT_ERROR` envelope on HTTP 200, 401 on a bad token |
| `async` | `/execute/async` submit and long-poll result, `/requests/{id}/status` (incl. `progress_source`/`progress_supported`/`last_activity_at`), `Idempotency-Key` replay returns the same job |
| `render` | Per engine: `/render` submit → `/render/{id}/progress` SSE terminal event → job result → **engine readback** (in the job result *and* an independent live read afterwards) → artifact download is a PNG → `?thumbnail` of it is a PNG scaled to half the render size. Iray also checks the `iray_samples` readback (applied, then restored to the previous value). The first render also checks `GET /scene/events?filter=render` delivers `render.finished`. With viewport selected, a 3-frame 64×64 `/render/animation` checks the job status reports frame progress (`progress_source: frames`, final `current == total == 3`) and that its `/render/{id}/progress` stream ends `complete` with frame events in strict order and `total_frames == 3` (the frames seen are recorded; fast viewport frames may land between polls). |
| `mcp` | Optional (`--mcp-dir`). Spawns the `daz-mcp-server` package from a checkout, registers its scripts, and calls `daz_status`, `daz_scene_info`, `daz_get_render_settings`. This checkout's `dazpy` goes first on `PYTHONPATH` (not the MCP venv's wheel); `register_scripts` fails if another copy loads |

### Render settings are read back after every change

The only state the suite changes is Render Settings (engine, image size,
output filename). It:

1. snapshots `renderType`, the active renderer class, resolution and output
   path (`render/snapshot_settings`). If the snapshot fails, no renders run.
2. after each render, compares the job's engine readback and a fresh
   `DazRenderSettings.render_engine_state()` against the expected
   `(status, engine, renderType, renderer class)` for that engine.
3. restores the snapshot and reads every field back
   (`render/restore_settings`). This runs in a `finally`, so it happens even
   when a render fails.

Scene contents are never modified.

## Commands

Start DAZ Studio with the plugin, start the server from its pane, then:

| SDK | Engines | Command |
|---|---|---|
| DS4 (Qt 4.8) | Iray, viewport | `python tests/smoke_live.py --engines iray,viewport --require-engines` |
| DS6 (Qt 6) | Iray, viewport (+ Filament if registered) | `python tests/smoke_live.py --engines iray,filament,viewport` |
| any | one engine | `python tests/smoke_live.py --stages render --engines filament` |
| any | no renders | `python tests/smoke_live.py --stages api,async` |
| any | + MCP | add `--mcp-dir ../daz-mcp-server` (needs `uv`) |

Without `--require-engines`, an engine that isn't registered on this Studio
(e.g. Filament on DS4) is reported as `skip`, not `fail`. The list of
registered engines comes from `GET /capabilities` → `render_engines.selectable`.

**Filament on DS 6.26:** Filament ships as a viewport draw style
(`dsp_dzfilamentdrawstyle.dll`), not as a `DzRenderer`. Checked live on
2026-11-14: `DzRenderMgr` lists only `DzIrayRenderer`, and
`findRenderer("DzFilamentRenderer")` returns null. So `engine: "filament"` can't
be selected and the smoke run reports it as `skip`. Don't pass
`--require-engines` for Filament on DS6 until a build registers it as a
renderer.

Other flags: `--host/--port` (or `DAZ_HOST`/`DAZ_PORT`), `--render-timeout`
(default 300 s per render), `--out-dir` (host folder for renders), `--report
file.json`, `-v`.

Exit code: `0` all checks passed or skipped, `1` at least one failure, `2`
server unreachable.

## Recording results per release

For each release, run the matrix once per SDK build with `--record`:

```bash
python tests/smoke_live.py --engines iray,viewport --mcp-dir ../daz-mcp-server --record   # DS4
python tests/smoke_live.py --engines iray,filament,viewport --mcp-dir ../daz-mcp-server --record   # DS6 (filament skips on 6.26)
```

This writes `docs/smoke-results/v<server>-ds<sdk>.json` and regenerates
[`docs/smoke-results/README.md`](smoke-results/README.md), which has one row
per release × SDK. Commit both files with the release. Re-running for the same
version and SDK replaces that report. `--reindex` rebuilds the table from the
existing JSON files only. Reports don't include host file paths.

## Self-hosted runner

`.github/workflows/live-smoke.yml` runs the same command through
`workflow_dispatch` on a runner labelled `[self-hosted, windows, daz-studio]`.
That machine needs DAZ Studio running with the plugin's server started, and the
token file in the runner user's `~/.daz3d/`. The workflow uploads the JSON
report as an artifact. It never runs on push, so CI doesn't depend on a live
Studio.
