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

# -- Setup ---------------------------------------------------------------------

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
EXPORT_OUT = os.path.join(os.environ.get("TEMP", "C:/Temp"), "daz_usd_test_export.usdc")

# -- Test Harness --------------------------------------------------------------

_passed  = 0
_failed  = 0
_skipped = 0

def _safe_print(text: str) -> None:
    """Print to stdout, replacing unencodable characters so cp1252 consoles don't crash."""
    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((text + "\n").encode(sys.stdout.encoding, errors="replace"))

def check(label: str, condition: bool, detail: str = ""):
    global _passed, _failed
    if condition:
        _passed += 1
        _safe_print(f"  PASS  {label}")
    else:
        _failed += 1
        suffix = f" | {detail}" if detail else ""
        _safe_print(f"  FAIL  {label}{suffix}")

def skip(label: str, reason: str = ""):
    global _skipped
    _skipped += 1
    suffix = f" ({reason})" if reason else ""
    print(f"  SKIP  {label}{suffix}")

def section(title: str):
    print(f"\n{'-' * 60}")
    print(f"  {title}")
    print(f"{'-' * 60}")

def summary():
    total = _passed + _failed + _skipped
    print(f"\n{'=' * 60}")
    print(f"  Results: {_passed} passed, {_failed} failed, {_skipped} skipped  ({total} total)")  # noqa
    print(f"{'=' * 60}")  # noqa
    return _failed == 0

def get(path, **kw):
    return requests.get(f"{BASE_URL}{path}", **kw)

def post(path, **kw):
    return requests.post(f"{BASE_URL}{path}", **kw)

def poll_job(job_id: str, timeout: int = 600) -> dict:
    """Poll GET /export/usd/:id until terminal state or timeout.

    A connection reset or request timeout means the main thread is blocked by
    an active export; wait and retry rather than treating it as an error.
    USD exports of complex scenes can take several minutes.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = get(f"/export/usd/{job_id}", headers=AUTH, timeout=30)
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout):
            # Main thread busy with export — wait and retry
            time.sleep(3.0)
            continue
        if r.status_code != 200:
            return {"status": "error", "_http": r.status_code}
        data = r.json()
        if data.get("status") in ("completed", "failed"):
            return data
        time.sleep(2.0)
    return {"status": "timeout"}

# -- 1. Bridge availability probe ----------------------------------------------

section("1. Bridge availability (catch-all dispatcher)")

r = get("/export/usd/probe", headers=AUTH)
bridge_available = (
    r.status_code == 404
    and "error" in r.text
    and "probe" in r.text
)
check("GET /export/usd/probe -> 404 (routes registered)", bridge_available,
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

# -- 2. Catch-all dispatcher — unknown paths -----------------------------------

section("2. Catch-all dispatcher (unknown paths)")

r = get("/totally/unknown/path", headers=AUTH)
check("Unknown path -> 404", r.status_code == 404, f"got {r.status_code}")
try:
    body = r.json()
    check("Unknown path 404 body is JSON", isinstance(body, dict))
except Exception:
    check("Unknown path 404 body is JSON", False, r.text[:80])

r = post("/also/unknown", headers=AUTH, json={})
check("Unknown POST path -> 404", r.status_code == 404, f"got {r.status_code}")

# -- 3. POST /export/usd — validation ------------------------------------------

section("3. POST /export/usd — request validation")

r = post("/export/usd", headers=AUTH)
check("Empty body -> 400", r.status_code == 400, f"got {r.status_code}")
try:
    check("Empty body error has 'error' key", "error" in r.json())
except Exception:
    check("Empty body error has 'error' key", False, r.text[:80])

r = post("/export/usd", headers={**AUTH, "Content-Type": "application/json"}, data=b"not json")
check("Invalid JSON -> 400", r.status_code == 400, f"got {r.status_code}")

r = post("/export/usd", headers=AUTH, json={"includeGeometry": True})
check("Missing outputPath -> 400", r.status_code == 400, f"got {r.status_code}")
try:
    body = r.json()
    check("Missing outputPath error mentions 'outputPath'",
          "outputPath" in body.get("error", ""), body.get("error", ""))
except Exception:
    check("Missing outputPath error mentions 'outputPath'", False, r.text[:80])

# -- 4. POST /export/usd — successful submission -------------------------------

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
check("POST /export/usd -> 202", r.status_code == 202, f"got {r.status_code}")

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
check("Minimal payload (outputPath only) -> 202", r2.status_code == 202,
      f"got {r2.status_code}")

# -- 5. GET /export/usd/:id ----------------------------------------------------

section("5. GET /export/usd/:id — status polling")

if job_id:
    # First status check — may need to wait if export is already running.
    status_body = None
    for _attempt in range(20):
        try:
            r = get(f"/export/usd/{job_id}", headers=AUTH, timeout=30)
            status_body = r.json()
            break
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout, ValueError):
            time.sleep(3.0)

    if status_body is not None:
        check("GET /export/usd/:id -> 200", r.status_code == 200, f"got {r.status_code}")
        check("Status body has job_id",  status_body.get("job_id") == job_id,
              status_body.get("job_id"))
        check("Status body has status",  "status" in status_body)
        check("Status body has submittedAt", "submittedAt" in status_body)
    else:
        check("GET /export/usd/:id -> 200", False, "connection kept resetting")
        check("Status body has job_id",     False, "connection kept resetting")
        check("Status body has status",     False, "connection kept resetting")
        check("Status body has submittedAt", False, "connection kept resetting")

    # Unknown job id.
    r = get("/export/usd/nonexistent-job-id", headers=AUTH)
    check("Unknown job id -> 404", r.status_code == 404, f"got {r.status_code}")
    try:
        err = r.json()
        check("Unknown job error has 'error' key", "error" in err)
        check("Unknown job error mentions id",
              "nonexistent-job-id" in err.get("error", ""), err.get("error", ""))
    except Exception as e:
        check("Unknown job error has 'error' key", False, str(e))
        check("Unknown job error mentions id",      False, "parse failed")

    # Poll to terminal state.
    print(f"\n  Waiting for job {job_id} to complete (up to 300s)...")
    final = poll_job(job_id, timeout=300)
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
    skip("GET /export/usd/:id -> 200",         "no job_id from submission")
    skip("Status body has job_id",            "no job_id from submission")
    skip("Status body has status",            "no job_id from submission")
    skip("Status body has submittedAt",       "no job_id from submission")
    skip("Unknown job id -> 404",             "no job_id from submission")
    skip("Unknown job error has 'error' key", "no job_id from submission")
    skip("Unknown job error mentions id",     "no job_id from submission")
    skip("Job reaches terminal state",        "no job_id from submission")
    skip("Terminal status body has completedAt", "no job_id from submission")

# -- 6. Output file verification -----------------------------------------------

section("6. Output file verification (end-to-end)")

export_completed = (job_id is not None
                    and 'final' in dir()
                    and final.get("status") == "completed")

if export_completed:
    output_file = final.get("outputPath", EXPORT_OUT)

    check("Output file exists", os.path.isfile(output_file),
          f"path={output_file}")

    if os.path.isfile(output_file):
        file_size = os.path.getsize(output_file)
        check("Output file is non-empty", file_size > 0,
              f"size={file_size}")

        # Detect format by extension and validate header bytes.
        if output_file.lower().endswith(".usda"):
            with open(output_file, "r", encoding="utf-8", errors="replace") as fh:
                first_line = fh.readline().strip()
            check("USDA file has '#usda 1.0' header",
                  first_line == "#usda 1.0",
                  f"first_line={first_line!r}")
        elif output_file.lower().endswith(".usdc"):
            with open(output_file, "rb") as fh:
                magic = fh.read(8)
            check("USDC file has PXR-USDC magic",
                  magic[:8] == b"PXR-USDC",
                  f"magic={magic!r}")
        else:
            skip("USD header check", f"unknown extension: {output_file}")

        # For USDA, do a quick sanity scan: look for at least one 'def' prim.
        if output_file.lower().endswith(".usda"):
            with open(output_file, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read(65536)  # read first 64 KB
            has_root = "def Xform" in content or "def Mesh" in content
            check("USDA contains at least one prim definition", has_root,
                  "no 'def Xform' or 'def Mesh' found in first 64 KB")

        print(f"  (output file: {output_file}, size: {file_size:,} bytes)")

    # Clean up test output files.
    for f in [EXPORT_OUT]:
        try:
            if os.path.isfile(f):
                os.remove(f)
        except OSError:
            pass
else:
    reason = "export did not complete" if job_id else "no job_id from submission"
    skip("Output file exists",              reason)
    skip("Output file is non-empty",        reason)
    skip("USDC file has PXR-USDC magic",    reason)

# -----------------------------------------------------------------------------

ok = summary()
sys.exit(0 if ok else 1)
