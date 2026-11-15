#!/usr/bin/env python3
"""
Live smoke-test matrix for DazScriptServer (ASSESSMENT #8, bd 5d6f.9).

A deliberately *small*, scoped check against a running DAZ Studio: API basics,
async jobs, both SSE streams, one tiny render per engine (Iray / Filament /
viewport) with live engine readback, and optionally the vangard-daz-mcp tools.
It is NOT the full integration suite (that one froze Studio when run live);
every stage here is bounded and read-mostly.

Scene contents are never touched. The only state it changes is Render
Settings (engine, image size, output filename), which it snapshots first,
reads back after every change, and restores at the end (also read back).

Usage:
    python tests/smoke_live.py                         # all stages, engines from /capabilities
    python tests/smoke_live.py --engines iray,viewport # chosen engines (unregistered -> skip)
    python tests/smoke_live.py --stages api,async      # no renders
    python tests/smoke_live.py --mcp-dir ../daz-mcp-server
    python tests/smoke_live.py --record                # write docs/smoke-results/<ver>-ds<N>.json

Exit code: 0 all pass/skip, 1 any failure, 2 server unreachable.
See docs/LIVE_SMOKE.md.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import platform
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests  # noqa: E402

from dazpy import DazClient, DazRenderSettings  # noqa: E402
from dazpy._render_api import _parse_sse_events  # noqa: E402
from dazpy._script_builder import ScriptBuilder  # noqa: E402

REPORT_SCHEMA = 1
ALL_STAGES = ("api", "async", "render", "mcp")
ALL_ENGINES = ("iray", "filament", "viewport")
RESULTS_DIR = ROOT / "docs" / "smoke-results"
RENDER_SIZE = 64
IRAY_SAMPLES = 4
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# Expected live readback per requested engine: (status, engine, render_type, class)
EXPECTED_ENGINE = {
    "iray": ("verified_iray", "iray", 2, "DzIrayRenderer"),
    "filament": ("verified_non_iray", "other_non_iray", 2, "DzFilamentRenderer"),
    "viewport": ("verified_non_iray", "viewport_gl", 0, None),
}


class SmokeFailure(AssertionError):
    pass


def iife(body: str) -> str:
    return ScriptBuilder.iife(body)


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise SmokeFailure(msg)


# ── Runner ────────────────────────────────────────────────────────────────────

class Smoke:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.base = f"http://{args.host}:{args.port}"
        self.client = DazClient(host=args.host, port=args.port, timeout=60.0)
        self.rs = DazRenderSettings(self.client)
        self.checks: list[dict] = []
        self.caps: dict = {}
        self.out_dir = Path(args.out_dir or tempfile.mkdtemp(prefix="dss_smoke_"))
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._snapshot: dict | None = None

    # -- bookkeeping --

    def run(self, stage: str, name: str, fn, *, skip: str = ""):
        entry = {"stage": stage, "name": name, "status": "pass", "duration_ms": 0, "detail": None}
        t0 = time.perf_counter()
        if skip:
            entry.update(status="skip", detail=skip)
        else:
            try:
                detail = fn()
                if detail is not None:
                    entry["detail"] = detail
            except SmokeFailure as exc:
                entry.update(status="fail", detail=str(exc))
            except Exception as exc:  # noqa: BLE001 - every error is a smoke failure
                entry.update(status="fail", detail=f"{type(exc).__name__}: {exc}")
                if self.args.verbose:
                    traceback.print_exc()
        entry["duration_ms"] = int((time.perf_counter() - t0) * 1000)
        self.checks.append(entry)
        mark = {"pass": "PASS", "fail": "FAIL", "skip": "skip"}[entry["status"]]
        line = f"  [{mark}] {stage}/{name}  ({entry['duration_ms']} ms)"
        if entry["status"] != "pass" or self.args.verbose:
            if entry["detail"] is not None:
                line += f"  -- {_short(entry['detail'])}"
        print(line, flush=True)
        return entry

    def _headers(self, token: str | None = None) -> dict:
        return {"X-API-Token": self.client._token if token is None else token}

    # -- stage: api --

    def stage_api(self):
        def status():
            r = requests.get(f"{self.base}/status", timeout=5)
            check(r.status_code == 200, f"/status HTTP {r.status_code}")
            body = r.json()
            check(body.get("running") is not False, f"/status says not running: {body}")
            return {"version": body.get("version")}

        def health():
            r = requests.get(f"{self.base}/health", timeout=5)
            check(r.status_code == 200, f"/health HTTP {r.status_code}")

        def capabilities():
            check(bool(self.caps), "GET /capabilities returned nothing")
            for key in ("server", "studio", "routes", "render_engines"):
                check(key in self.caps, f"/capabilities missing {key!r}")
            check(self.caps["studio"].get("sdk_major") in (4, 6),
                  f"unexpected sdk_major {self.caps['studio'].get('sdk_major')!r}")
            eng = self.caps["render_engines"]
            return {"selectable": eng.get("selectable"), "active_class": eng.get("active_class"),
                    "source": eng.get("source")}

        def execute_basic():
            res = self.client.execute(iife("return 6 * 7;"))
            check(res.value == 42, f"expected 42, got {res.value!r}")

        def execute_args():
            res = self.client.execute(iife("return getArguments()[0].a + 1;"), args={"a": 41})
            check(res.value == 42, f"expected 42, got {res.value!r}")

        def daz_globals():
            res = self.client.execute(
                iife("return {nodes: Scene.getNumNodes(), app: typeof App};"))
            check(isinstance(res.value, dict) and "nodes" in res.value, f"bad result {res.value!r}")
            return res.value

        def script_error_envelope():
            r = requests.post(f"{self.base}/execute", headers=self._headers(),
                              json={"script": "throw new Error('smoke');"}, timeout=10)
            check(r.status_code == 200, f"script error should be HTTP 200, got {r.status_code}")
            body = r.json()
            check(body.get("success") is False, "success should be false")
            check(body.get("error_code") == "SCRIPT_ERROR", f"error_code {body.get('error_code')!r}")

        def auth_rejects_bad_token():
            r = requests.post(f"{self.base}/execute", headers=self._headers("not-a-token"),
                              json={"script": "1;"}, timeout=5)
            check(r.status_code == 401, f"bad token got HTTP {r.status_code}")

        auth_on = bool(self.caps.get("security", {}).get("auth_enabled", True))
        self.run("api", "status", status)
        self.run("api", "health", health)
        self.run("api", "capabilities", capabilities)
        self.run("api", "execute_basic", execute_basic)
        self.run("api", "execute_args", execute_args)
        self.run("api", "daz_globals", daz_globals)
        self.run("api", "script_error_envelope", script_error_envelope)
        self.run("api", "auth_rejects_bad_token", auth_rejects_bad_token,
                 skip="" if auth_on else "auth disabled on server")

    # -- stage: async --

    def stage_async(self):
        state: dict = {}

        def submit_and_wait():
            rid = self.client.execute_async_submit(iife("return {answer: 42};"))
            state["rid"] = rid
            body = self._wait_result(rid, 60)
            check(body.get("status") == "completed", f"status {body.get('status')!r}: {body}")
            check((body.get("result") or {}).get("answer") == 42, f"result {body.get('result')!r}")
            return {"request_id": rid}

        def status_endpoint():
            check("rid" in state, "no request from previous check")
            st = self.client.get_request_status(state["rid"])
            check(st.get("status") == "completed", f"status {st!r}")

        def activity_fields():
            # A plain script (no reportFile) has no progress until it ends.
            check("rid" in state, "no request from previous check")
            st = self.client.get_request_status(state["rid"])
            check(st.get("progress_source") == "none", f"progress_source {st.get('progress_source')!r}")
            check(st.get("progress_supported") is False,
                  f"progress_supported {st.get('progress_supported')!r}")
            check(isinstance(st.get("last_activity_at"), str), f"last_activity_at {st.get('last_activity_at')!r}")
            check("idle_ms" not in st, f"idle_ms on a finished job: {st.get('idle_ms')!r}")
            return {"last_activity_at": st["last_activity_at"]}

        def idempotency_replay():
            key = f"smoke-{uuid.uuid4().hex}"
            a = self.client.execute_async_submit(iife("return 1;"), idempotency_key=key)
            b = self.client.execute_async_submit(iife("return 1;"), idempotency_key=key)
            check(a == b, f"same Idempotency-Key gave two jobs: {a} vs {b}")
            self._wait_result(a, 60)

        self.run("async", "submit_and_wait", submit_and_wait)
        self.run("async", "status_endpoint", status_endpoint)
        self.run("async", "activity_fields", activity_fields)
        self.run("async", "idempotency_replay", idempotency_replay)

    def _wait_result(self, rid: str, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            left = max(1, int(deadline - time.monotonic()))
            body = self.client.get_request_result(rid, wait=True, wait_timeout=min(left, 30))
            if body.get("status") in ("completed", "failed", "cancelled", "stale", "not_found"):
                return body
            if time.monotonic() >= deadline:
                raise SmokeFailure(f"{rid} not finished after {timeout}s (status {body.get('status')!r})")

    # -- stage: render --

    def snapshot_render_settings(self):
        def snap():
            state = self.rs.render_engine_state()
            check(state.get("status") != "unavailable", f"engine readback unavailable: {state}")
            self._snapshot = {
                "render_type": state["render_type"]["raw"],
                "renderer_class": state["active_renderer"]["class_name"],
                "resolution": self.rs.resolution,
                "output_path": self.rs.output_path,
            }
            # Host paths stay out of the (committed) report.
            return {k: v for k, v in self._snapshot.items() if k != "output_path"}
        self.run("render", "snapshot_settings", snap)

    def restore_render_settings(self):
        def restore():
            snap = self._snapshot
            check(snap is not None, "no snapshot taken; nothing to restore")
            if snap["renderer_class"]:
                self.rs.set_active_engine(snap["renderer_class"])   # also sets Software
            if snap["render_type"] in (0, 1):
                self.rs.set_active_engine("viewport" if snap["render_type"] == 0 else "multi_pass_opengl")
            if snap["resolution"]:
                self.rs.set_resolution(snap["resolution"]["width"], snap["resolution"]["height"])
            if snap["output_path"] is not None:
                self.rs.output_path = snap["output_path"]
            # Read everything back.
            state = self.rs.render_engine_state()
            got = (state["render_type"]["raw"], state["active_renderer"]["class_name"])
            want = (snap["render_type"], snap["renderer_class"])
            check(got == want, f"engine restore readback {got} != snapshot {want}")
            check(self.rs.resolution == snap["resolution"],
                  f"resolution restore readback {self.rs.resolution} != {snap['resolution']}")
            check(self.rs.output_path == snap["output_path"],
                  f"output path restore readback {self.rs.output_path!r} != {snap['output_path']!r}")
            return {"engine": got}
        self.run("render", "restore_settings", restore)

    def stage_render(self, engines: list[str]):
        selectable = set(self.caps.get("render_engines", {}).get("selectable") or [])
        self.snapshot_render_settings()
        if self._snapshot is None:
            self.run("render", "engines", lambda: None, skip="snapshot failed; refusing to change settings")
            return
        first = True
        try:
            for engine in engines:
                if engine not in selectable:
                    reason = f"{engine} not registered (selectable: {sorted(selectable)})"
                    if self.args.require_engines:
                        self.run("render", f"{engine}.render", lambda r=reason: check(False, r))
                    else:
                        self.run("render", f"{engine}.render", None, skip=reason)
                    continue
                self._render_engine(engine, watch_scene_events=first)
                first = False
            if "viewport" in engines:
                if "viewport" in selectable:
                    self._render_animation_frames()
                else:
                    self.run("render", "animation.frame_progress", None,
                             skip="viewport not registered")
        finally:
            self.restore_render_settings()

    def _render_engine(self, engine: str, *, watch_scene_events: bool):
        out = (self.out_dir / f"smoke_{engine}_{int(time.time())}.png").as_posix()
        st: dict = {}
        scene_events: list[str] = []
        stop = threading.Event()
        watcher = None

        if watch_scene_events:
            resp = self.client.stream_scene_events(
                ["render"], stream_timeout=self.args.render_timeout + 30.0)
            if resp is not None:
                def _watch():
                    try:
                        for ev_type, data in _parse_sse_events(resp):
                            t = data.get("type") if isinstance(data, dict) else None
                            if t:
                                scene_events.append(t)
                            if stop.is_set() or t == "render.finished":
                                break
                    except Exception:  # noqa: BLE001 - stream timeout/close ends the watch
                        pass
                    finally:
                        resp.close()
                watcher = threading.Thread(target=_watch, daemon=True)
                watcher.start()
                time.sleep(0.3)  # let the subscription register before rendering
            st["scene_stream"] = resp is not None

        def submit():
            kw = {"width": RENDER_SIZE, "height": RENDER_SIZE, "engine": engine}
            if engine == "iray":
                kw["iray_samples"] = IRAY_SAMPLES
            sub = self.client.render_submit(out, **kw)
            st["rid"] = sub["request_id"]
            return {"request_id": st["rid"]}

        def progress_sse():
            check("rid" in st, "no render request")
            resp = self.client.stream_render_progress(st["rid"], stream_timeout=self.args.render_timeout)
            check(resp is not None, "GET /render/{id}/progress did not open")
            seen = []
            try:
                for ev_type, data in _parse_sse_events(resp):
                    seen.append(ev_type)
                    if ev_type in ("complete", "error"):
                        st["sse_terminal"] = (ev_type, data)
                        break
            finally:
                resp.close()
            check("sse_terminal" in st, f"stream ended without a terminal event (saw {seen})")
            check(st["sse_terminal"][0] == "complete", f"terminal event {st['sse_terminal']}")
            return {"events": seen}

        def result():
            check("rid" in st, "no render request")
            body = self._wait_result(st["rid"], self.args.render_timeout)
            st["body"] = body
            check(body.get("status") == "completed", f"status {body.get('status')!r}: {_short(body)}")
            res = body.get("result") or {}
            check(res.get("success") is True, f"render reported success={res.get('success')!r}")
            return {"duration_ms": body.get("duration_ms")}

        def engine_readback():
            res = (st.get("body") or {}).get("result") or {}
            want_status, want_engine, want_type, want_class = EXPECTED_ENGINE[engine]
            rb = res.get("engine")
            check(isinstance(rb, dict), f"render result has no engine readback: {res!r}")
            check(rb.get("status") == want_status and rb.get("engine") == want_engine,
                  f"job readback {rb.get('status')}/{rb.get('engine')}, want {want_status}/{want_engine}")
            # Independent read after the change, outside the render job.
            live = self.rs.render_engine_state()
            check(live.get("status") == want_status and live.get("engine") == want_engine,
                  f"live readback {live.get('status')}/{live.get('engine')}, want {want_status}/{want_engine}")
            check(live["render_type"]["raw"] == want_type,
                  f"live renderType {live['render_type']['raw']} != {want_type}")
            if want_class:
                check(live["active_renderer"]["class_name"] == want_class,
                      f"live renderer {live['active_renderer']['class_name']} != {want_class}")
            check(self.rs.resolution == {"width": RENDER_SIZE, "height": RENDER_SIZE},
                  f"live resolution {self.rs.resolution}")
            return {"render_type": live["render_type"]["raw"],
                    "renderer": live["active_renderer"]["class_name"]}

        def iray_samples_readback():
            rb = ((st.get("body") or {}).get("result") or {}).get("iray_samples")
            check(isinstance(rb, dict), f"no iray_samples readback: {rb!r}")
            check(rb.get("applied") == IRAY_SAMPLES, f"applied {rb.get('applied')} != {IRAY_SAMPLES}")
            check(rb.get("restored") is True, f"Max Samples not restored: {rb}")
            live = self.rs.max_samples
            check(live == rb.get("previous"), f"live Max Samples {live} != previous {rb.get('previous')}")
            return rb

        def artifact():
            check("rid" in st, "no render request")
            listing = self.client.list_artifacts(st["rid"])
            avail = [a for a in listing.get("artifacts", []) if a.get("available")]
            check(avail, f"no available artifacts: {listing}")
            data = self.client.download_artifact(st["rid"], avail[0]["artifact_id"])
            check(isinstance(data, bytes) and len(data) > 0, "empty artifact download")
            check(data[:8] == PNG_MAGIC, f"artifact is not a PNG (first bytes {data[:8]!r})")
            return {"bytes": len(data)}

        def scene_events_sse():
            check(st.get("scene_stream"), "GET /scene/events did not open")
            if watcher:
                watcher.join(timeout=10)
            check("render.finished" in scene_events, f"no render.finished scene event (saw {scene_events})")
            return {"events": scene_events}

        sub = self.run("render", f"{engine}.submit", submit)
        if sub["status"] != "pass":
            stop.set()
            return
        self.run("render", f"{engine}.progress_sse", progress_sse)
        self.run("render", f"{engine}.result", result)
        self.run("render", f"{engine}.engine_readback", engine_readback)
        if engine == "iray":
            self.run("render", f"{engine}.iray_samples_readback", iray_samples_readback)
        self.run("render", f"{engine}.artifact", artifact)
        if watch_scene_events:
            stop.set()
            self.run("render", "scene_events_sse", scene_events_sse)

    def _render_animation_frames(self):
        """3-frame viewport animation: job status must report frame N of M."""
        frames = 3

        def frame_progress():
            pattern = (self.out_dir / f"smoke_anim_{int(time.time())}_{{frame}}.png").as_posix()
            sub = self.client.render_animation_submit(
                pattern, 0, frames - 1, width=RENDER_SIZE, height=RENDER_SIZE, engine="viewport")
            rid = sub["request_id"]
            seen_frames: set[int] = set()
            sse_frames: list[int] = []
            sse_end: dict = {}

            # GET /render/{id}/progress frame events (Studio 6 polls the frame
            # report; Studio 4 uses the print marker). Watched alongside status.
            resp = self.client.stream_render_progress(rid, stream_timeout=self.args.render_timeout)
            check(resp is not None, "GET /render/{id}/progress did not open")

            def _watch():
                try:
                    for ev_type, data in _parse_sse_events(resp):
                        if ev_type == "progress" and isinstance(data, dict)                                 and isinstance(data.get("frame"), int):
                            sse_frames.append(data["frame"])
                            sse_end["total_frames"] = data.get("total_frames")
                        if ev_type in ("complete", "error"):
                            sse_end["terminal"] = ev_type
                            break
                except Exception:  # noqa: BLE001 - stream timeout/close ends the watch
                    pass
                finally:
                    resp.close()
            watcher = threading.Thread(target=_watch, daemon=True)
            watcher.start()

            deadline = time.monotonic() + self.args.render_timeout
            st: dict = {}
            while time.monotonic() < deadline:
                st = self.client.get_request_status(rid)
                detail = (st.get("observation") or {}).get("progress") or {}
                if st.get("status") == "running" and isinstance(detail.get("frame"), int):
                    seen_frames.add(detail["frame"])
                if st.get("status") not in ("queued", "running"):
                    break
                time.sleep(0.05)
            check(st.get("status") == "completed", f"status {st.get('status')!r}: {_short(st)}")
            check(st.get("progress_source") == "frames", f"progress_source {st.get('progress_source')!r}")
            check(st.get("progress_supported") is True, f"progress_supported {st.get('progress_supported')!r}")
            check(isinstance(st.get("last_activity_at"), str), f"last_activity_at {st.get('last_activity_at')!r}")
            detail = (st.get("observation") or {}).get("progress") or {}
            check(detail.get("total") == frames and detail.get("current") == frames
                  and detail.get("phase") == "done", f"final frame progress {detail}")
            check("report_file" not in (st.get("observation") or {}),
                  "server-owned frame report leaked as report_file")
            watcher.join(timeout=10.0)
            check(sse_end.get("terminal") == "complete", f"SSE terminal {sse_end.get('terminal')!r}")
            check(sse_frames == sorted(set(sse_frames)),
                  f"SSE frame events duplicated or out of order: {sse_frames}")
            check(not sse_frames or sse_end.get("total_frames") == frames,
                  f"SSE total_frames {sse_end.get('total_frames')!r}, want {frames}")
            # Viewport frames can be faster than the poll; seeing any running
            # frame proves the live path, seeing none is reported, not failed.
            return {"frames_seen_running": sorted(seen_frames), "sse_frames": sse_frames}

        self.run("render", "animation.frame_progress", frame_progress)

    # -- stage: mcp --

    def stage_mcp(self):
        mcp_dir = self.args.mcp_dir
        if not mcp_dir:
            self.run("mcp", "tools", None, skip="pass --mcp-dir <daz-mcp-server checkout> to enable")
            return
        snippet = r"""
import asyncio, json, sys
from dazpy.aio import AsyncDazClient
from vangard_daz_mcp._client import DAZ_API_TOKEN, DAZ_HOST, DAZ_PORT, DAZ_TIMEOUT, set_async_daz_client
from vangard_daz_mcp._registry import _REGISTRY, _register_scripts
from vangard_daz_mcp.tools.utility import daz_status
from vangard_daz_mcp.tools.scene import daz_scene_info
from vangard_daz_mcp.tools.render import daz_get_render_settings

async def main():
    out = {}
    client = AsyncDazClient(host=DAZ_HOST, port=DAZ_PORT, token=DAZ_API_TOKEN, timeout=DAZ_TIMEOUT)
    set_async_daz_client(client)
    try:
        await _register_scripts(client)
        out["registered"] = len(_REGISTRY)
        for name, fn in (("daz_status", daz_status), ("daz_scene_info", daz_scene_info),
                         ("daz_get_render_settings", daz_get_render_settings)):
            try:
                r = await fn()
                out[name] = {"ok": True, "keys": sorted(r)[:12] if isinstance(r, dict) else None}
            except Exception as exc:
                out[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        set_async_daz_client(None)
        await client.aclose()
    print("SMOKE_JSON " + json.dumps(out))

asyncio.run(main())
"""
        env = dict(os.environ, DAZ_HOST=self.args.host, DAZ_PORT=str(self.args.port))
        state: dict = {}

        def launch():
            cmd = ["uv", "run", "--project", mcp_dir, "python", "-c", snippet]
            proc = subprocess.run(cmd, cwd=mcp_dir, env=env, capture_output=True, text=True, timeout=180)
            line = next((l for l in proc.stdout.splitlines() if l.startswith("SMOKE_JSON ")), None)
            check(line is not None,
                  f"exit {proc.returncode}; stderr tail: {proc.stderr.strip()[-400:]}")
            state.update(json.loads(line[len("SMOKE_JSON "):]))
            check(state.get("registered", 0) > 0, "MCP registered no scripts")
            return {"registered": state["registered"]}

        self.run("mcp", "register_scripts", launch)
        for tool in ("daz_status", "daz_scene_info", "daz_get_render_settings"):
            def one(t=tool):
                r = state.get(t)
                check(r is not None, "not run")
                check(r["ok"], r.get("error", "failed"))
            self.run("mcp", tool, one, skip="" if state else "MCP launch failed")

    # -- orchestration --

    def execute(self) -> dict:
        started = _now()
        print(f"DazScriptServer live smoke -> {self.base}")
        try:
            r = requests.get(f"{self.base}/status", timeout=3)
            r.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            print(f"server not reachable: {exc}")
            sys.exit(2)
        try:
            self.caps = self.client.capabilities()
        except Exception as exc:  # noqa: BLE001
            print(f"warning: /capabilities failed: {exc}")

        studio = self.caps.get("studio", {})
        server = self.caps.get("server", {})
        print(f"  server {server.get('version')}  studio {studio.get('version')}  "
              f"sdk_major {studio.get('sdk_major')}  out_dir {self.out_dir}")

        stages = self.args.stages
        engines = self.args.engines
        if "api" in stages:
            self.stage_api()
        if "async" in stages:
            self.stage_async()
        if "render" in stages:
            self.stage_render(engines)
        if "mcp" in stages:
            self.stage_mcp()

        summary = {s: sum(1 for c in self.checks if c["status"] == s) for s in ("pass", "fail", "skip")}
        report = {
            "schema": REPORT_SCHEMA,
            "started_at": started,
            "finished_at": _now(),
            "target": self.base,
            "host_os": f"{platform.system()} {platform.release()}",
            "server_version": server.get("version"),
            "studio_version": studio.get("version"),
            "sdk_major": studio.get("sdk_major"),
            "engines_requested": engines,
            "engines_selectable": self.caps.get("render_engines", {}).get("selectable"),
            "stages": stages,
            "summary": summary,
            "checks": self.checks,
        }
        print(f"\n{summary['pass']} passed, {summary['fail']} failed, {summary['skip']} skipped")
        return report


# ── Recording ─────────────────────────────────────────────────────────────────

def record(report: dict) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ver = report.get("server_version") or "unknown"
    path = RESULTS_DIR / f"v{ver}-ds{report.get('sdk_major') or 'X'}.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_index()
    return path


def write_index() -> Path:
    """Regenerate docs/smoke-results/README.md from every recorded report."""
    rows = []
    for p in sorted(RESULTS_DIR.glob("v*-ds*.json")):
        rep = json.loads(p.read_text(encoding="utf-8"))
        engines = {}
        for c in rep.get("checks", []):
            if c["stage"] == "render" and "." in c["name"]:
                eng = c["name"].split(".", 1)[0]
                cur = engines.get(eng, "pass")
                order = {"pass": 0, "skip": 1, "fail": 2}
                if order[c["status"]] > order[cur]:
                    cur = c["status"]
                engines[eng] = cur
        def cell(stage_or_engine, is_engine=False):
            if is_engine:
                return engines.get(stage_or_engine, "-")
            stat = [c["status"] for c in rep.get("checks", []) if c["stage"] == stage_or_engine]
            if not stat:
                return "-"
            return "fail" if "fail" in stat else ("pass" if "pass" in stat else "skip")
        s = rep.get("summary", {})
        rows.append("| {ver} | DS{sdk} {studio} | {api} | {asy} | {iray} | {fil} | {vp} | {mcp} | {p}/{f}/{k} | [{name}]({name}) |".format(
            ver=rep.get("server_version"), sdk=rep.get("sdk_major"), studio=rep.get("studio_version"),
            api=cell("api"), asy=cell("async"),
            iray=cell("iray", True), fil=cell("filament", True), vp=cell("viewport", True),
            mcp=cell("mcp"), p=s.get("pass", 0), f=s.get("fail", 0), k=s.get("skip", 0),
            name=p.name))
    text = (
        "# Live smoke results\n\n"
        "Generated by `python tests/smoke_live.py --record` — do not edit by hand.\n"
        "One row per release x SDK. See [../LIVE_SMOKE.md](../LIVE_SMOKE.md).\n\n"
        "| Server | Studio | API | Async | Iray | Filament | Viewport | MCP | pass/fail/skip | Report |\n"
        "|---|---|---|---|---|---|---|---|---|---|\n"
        + "\n".join(rows) + ("\n" if rows else "")
    )
    idx = RESULTS_DIR / "README.md"
    idx.write_text(text, encoding="utf-8")
    return idx


# ── helpers / CLI ─────────────────────────────────────────────────────────────

def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _short(obj, n: int = 300) -> str:
    s = obj if isinstance(obj, str) else json.dumps(obj, default=str)
    return s if len(s) <= n else s[: n - 3] + "..."


def _csv(choices):
    def parse(value: str) -> list[str]:
        items = [v.strip().lower() for v in value.split(",") if v.strip()]
        bad = [v for v in items if v not in choices]
        if bad:
            raise argparse.ArgumentTypeError(f"unknown {bad}; choose from {', '.join(choices)}")
        return items
    return parse


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default=os.environ.get("DAZ_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("DAZ_PORT", "18811")))
    p.add_argument("--stages", type=_csv(ALL_STAGES), default=list(ALL_STAGES),
                   help="comma list of: " + ",".join(ALL_STAGES))
    p.add_argument("--engines", type=_csv(ALL_ENGINES), default=list(ALL_ENGINES),
                   help="comma list of: " + ",".join(ALL_ENGINES) + " (unregistered ones are skipped)")
    p.add_argument("--require-engines", action="store_true",
                   help="fail (not skip) when a requested engine isn't registered")
    p.add_argument("--render-timeout", type=float, default=300.0, help="seconds per render")
    p.add_argument("--mcp-dir", default=os.environ.get("DAZ_MCP_DIR"),
                   help="daz-mcp-server checkout; enables the mcp stage (needs uv)")
    p.add_argument("--out-dir", help="host directory for render output (default: new temp dir)")
    p.add_argument("--report", help="also write the JSON report to this path")
    p.add_argument("--record", action="store_true",
                   help="write docs/smoke-results/v<server>-ds<sdk>.json and refresh its README")
    p.add_argument("--reindex", action="store_true", help="only regenerate docs/smoke-results/README.md")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.reindex:
        print(write_index())
        return 0
    report = Smoke(args).execute()
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"report: {args.report}")
    if args.record:
        print(f"recorded: {record(report)}")
    return 1 if report["summary"]["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
