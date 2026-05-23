"""USD bridge route tests — verifies POST /export/usd and GET /export/usd/:id.

The daz-bridge-usd plugin registers these routes via registerPluginRoute() after
the server starts.  This test file:

  1. Probes for bridge availability (404 with JSON body = routes registered).
  2. Tests all POST /export/usd validation paths.
  3. Submits a real export job and polls it to a terminal state.
  4. Tests GET /export/usd/:id for known and unknown job ids.
  5. Verifies the catch-all dispatcher returns JSON 404 for unknown paths.

Run with DAZ Studio open (scene loaded) and both plugins active:
    C:\\Python312\\python.exe test-usd-bridge.py
"""

import json
import os
import sys
import time
import requests

# ── Setup ─────────────────────────────────────────────────────────────────────

token_file = os.path.expanduser("~/.daz3d/dazscriptserver_token.txt")
api_token = ""

if os.path.exists(token_file):
    with open(token_file, "r") as f:
        api_token = f.read().strip()
    print(f"Loaded API token from {token_file}")
else:
    print(f"Warning: Token file not found at {token_file}")

BASE_URL = "http://127.0.0.1:18811"
AUTH     = {"X-API-Token": api_token}

# Temp output path for test exports.
EXPORT_OUT = os.path.join(os.environ.get("TEMP", "C:/Temp"), "daz_usd_test_export.usda")

# ── Test Harness ──────────────────────────────────────────────────────────────

_passed  = 0
_failed  = 0
_skipped = 0

def check(label: str, condition: bool, detail: str = ""):
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        suffix = f" | {detail}" if detail else ""
        print(f"  FAIL  {label}{suffix}")

def skip(label: str, reason: str = ""):
    global _skipped
    _skipped += 1
    suffix = f" ({reason})" if reason else ""
    print(f"  SKIP  {label}{suffix}")

def section(title: str):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")

def summary():
    total = _passed + _failed + _skipped
    print(f"\n{'=' * 60}")
    print(f"  Results: {_passed} passed, {_failed} failed, {_skipped} skipped  ({total} total)")
    print(f"{'=' * 60}")
    return _failed == 0

def get(path, **kw):
    return requests.get(f"{BASE_URL}{path}", **kw)

def post(path, **kw):
    return requests.post(f"{BASE_URL}{path}", **kw)

def poll_job(job_id: str, timeout: int = 60) -> dict:
    """Poll GET /export/usd/:id until terminal state or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = get(f"/export/usd/{job_id}", headers=AUTH)
        if r.status_code != 200:
            return {"status": "error", "_http": r.status_code}
        data = r.json()
        if data.get("status") in ("completed", "failed"):
            return data
        time.sleep(0.5)
    return {"status": "timeout"}

# ── 1. Bridge availability probe ──────────────────────────────────────────────

section("1. Bridge availability (catch-all dispatcher)")

r = get("/export/usd/probe", headers=AUTH)
bridge_available = (
    r.status_code == 404
    and "error" in r.text
    and "probe" in r.text
)
check("GET /export/usd/probe → 404 (routes registered)", bridge_available,
      f"status={r.status_code} body={r.text[:120]}")

if not bridge_available:
    print("\n  USD bridge routes not found — is daz-bridge-usd loaded and enabled?")
    print("  Remaining tests will be skipped.\n")
    summary()
    sys.exit(1)

# Verify response is JSON, not an empty body.
try:
    err_body = r.json()
    check("Probe 404 body is valid JSON", isinstance(err_body, dict))
    check("Probe 404 body has 'error' key", "error" in err_body)
except Exception as e:
    check("Probe 404 body is valid JSON", False, str(e))
    check("Probe 404 body has 'error' key", False, "parse failed")

# ── 2. Catch-all dispatcher — unknown paths ───────────────────────────────────

section("2. Catch-all dispatcher (unknown paths)")

r = get("/totally/unknown/path", headers=AUTH)
check("Unknown path → 404", r.status_code == 404, f"got {r.status_code}")
try:
    body = r.json()
    check("Unknown path 404 body is JSON", isinstance(body, dict))
except Exception:
    check("Unknown path 404 body is JSON", False, r.text[:80])

r = post("/also/unknown", headers=AUTH, json={})
check("Unknown POST path → 404", r.status_code == 404, f"got {r.status_code}")

# ── 3. POST /export/usd — validation ──────────────────────────────────────────

section("3. POST /export/usd — request validation")

r = post("/export/usd", headers=AUTH)
check("Empty body → 400", r.status_code == 400, f"got {r.status_code}")
try:
    check("Empty body error has 'error' key", "error" in r.json())
except Exception:
    check("Empty body error has 'error' key", False, r.text[:80])

r = post("/export/usd", headers=AUTH, data=b"not json", content_type="application/json")
check("Invalid JSON → 400", r.status_code == 400, f"got {r.status_code}")

r = post("/export/usd", headers=AUTH, json={"includeGeometry": True})
check("Missing outputPath → 400", r.status_code == 400, f"got {r.status_code}")
try:
    body = r.json()
    check("Missing outputPath error mentions 'outputPath'",
          "outputPath" in body.get("error", ""), body.get("error", ""))
except Exception:
    check("Missing outputPath error mentions 'outputPath'", False, r.text[:80])

# ── 4. POST /export/usd — successful submission ───────────────────────────────

section("4. POST /export/usd — job submission")

payload = {
    "outputPath":       EXPORT_OUT,
    "includeGeometry":  True,
    "includeMaterials": True,
    "includeSkeleton":  False,
    "includeMorphs":    False,
    "includeLights":    False,
    "includeCamera":    False,
}
r = post("/export/usd", headers=AUTH, json=payload)
check("POST /export/usd → 202", r.status_code == 202, f"got {r.status_code}")

job_id = None
try:
    body = r.json()
    job_id = body.get("job_id")
    check("Response has job_id",     bool(job_id), str(body))
    check("Response has status",     "status" in body, str(body))
    check("Initial status is queued", body.get("status") == "queued",
          body.get("status"))
    check("Response has submittedAt", "submittedAt" in body, str(body))
except Exception as e:
    check("Response is valid JSON",  False, str(e))
    check("Response has job_id",     False, "parse failed")
    check("Response has status",     False, "parse failed")
    check("Initial status is queued", False, "parse failed")
    check("Response has submittedAt", False, "parse failed")

# Optional fields submission (no validation errors expected).
r2 = post("/export/usd", headers=AUTH, json={"outputPath": EXPORT_OUT + ".opt.usda"})
check("Minimal payload (outputPath only) → 202", r2.status_code == 202,
      f"got {r2.status_code}")

# ── 5. GET /export/usd/:id ────────────────────────────────────────────────────

section("5. GET /export/usd/:id — status polling")

if job_id:
    r = get(f"/export/usd/{job_id}", headers=AUTH)
    check("GET /export/usd/:id → 200", r.status_code == 200, f"got {r.status_code}")
    try:
        status_body = r.json()
        check("Status body has job_id",  status_body.get("job_id") == job_id,
              status_body.get("job_id"))
        check("Status body has status",  "status" in status_body)
        check("Status body has submittedAt", "submittedAt" in status_body)
    except Exception as e:
        check("Status body is valid JSON", False, str(e))
        check("Status body has job_id",    False, "parse failed")
        check("Status body has status",    False, "parse failed")
        check("Status body has submittedAt", False, "parse failed")

    # Unknown job id.
    r = get("/export/usd/nonexistent-job-id", headers=AUTH)
    check("Unknown job id → 404", r.status_code == 404, f"got {r.status_code}")
    try:
        err = r.json()
        check("Unknown job error has 'error' key", "error" in err)
        check("Unknown job error mentions id",
              "nonexistent-job-id" in err.get("error", ""), err.get("error", ""))
    except Exception as e:
        check("Unknown job error has 'error' key", False, str(e))
        check("Unknown job error mentions id",      False, "parse failed")

    # Poll to terminal state.
    print(f"\n  Waiting for job {job_id} to complete (up to 60s)...")
    final = poll_job(job_id, timeout=60)
    terminal = final.get("status") in ("completed", "failed")
    check("Job reaches terminal state", terminal, f"status={final.get('status')}")

    if terminal:
        check("Terminal status body has completedAt", "completedAt" in final, str(final))
        if final.get("status") == "completed":
            check("Completed job has outputPath", "outputPath" in final, str(final))
        elif final.get("status") == "failed":
            check("Failed job has error field", "error" in final, str(final))
            print(f"  (export failed — error: {final.get('error', '')[:120]})")
else:
    skip("GET /export/usd/:id → 200",         "no job_id from submission")
    skip("Status body has job_id",            "no job_id from submission")
    skip("Status body has status",            "no job_id from submission")
    skip("Status body has submittedAt",       "no job_id from submission")
    skip("Unknown job id → 404",             "no job_id from submission")
    skip("Unknown job error has 'error' key", "no job_id from submission")
    skip("Unknown job error mentions id",     "no job_id from submission")
    skip("Job reaches terminal state",        "no job_id from submission")
    skip("Terminal status body has completedAt", "no job_id from submission")

# ─────────────────────────────────────────────────────────────────────────────

ok = summary()
sys.exit(0 if ok else 1)
