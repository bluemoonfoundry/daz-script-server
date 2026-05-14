import json
import os
import sys
import time
import requests

# ── Setup ─────────────────────────────────────────────────────────────────────

token_file = os.path.expanduser("~/.daz3d/dazscriptserver_token.txt")
api_token = ""

if os.path.exists(token_file):
    with open(token_file, 'r') as f:
        api_token = f.read().strip()
    print(f"Loaded API token from {token_file}")
else:
    print(f"Warning: Token file not found at {token_file}")

BASE_URL = "http://127.0.0.1:18811"
AUTH     = {"X-API-Token": api_token}

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
    print(f"\n{'═' * 60}")
    print(f"  Results: {_passed} passed, {_failed} failed, {_skipped} skipped  ({total} total)")
    print(f"{'═' * 60}")
    return _failed == 0

# ── Helpers ───────────────────────────────────────────────────────────────────

def get(path, **kwargs):
    return requests.get(f"{BASE_URL}{path}", **kwargs)

def post(path, **kwargs):
    return requests.post(f"{BASE_URL}{path}", **kwargs)

def delete(path, **kwargs):
    return requests.delete(f"{BASE_URL}{path}", **kwargs)

def poll_async(request_id: str, timeout: int = 30) -> dict:
    """Poll /requests/:id/status until terminal state or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = get(f"/requests/{request_id}/status", headers=AUTH)
        if r.status_code != 200:
            return {"status": "error", "_http": r.status_code}
        data = r.json()
        if data.get("status") in ("completed", "failed", "cancelled"):
            return data
        time.sleep(0.25)
    return {"status": "timeout"}

# ══════════════════════════════════════════════════════════════════════════════
# Section 1 — Observability endpoints (no auth required)
# ══════════════════════════════════════════════════════════════════════════════
section("1. Observability (no auth)")

r = get("/status")
check("GET /status returns 200",             r.status_code == 200)
check("GET /status has running=true",        r.json().get("running") is True)
check("GET /status has version field",       "version" in r.json())

r = get("/health")
check("GET /health returns 200",             r.status_code == 200)
check("GET /health has status field",        "status" in r.json())
check("GET /health has uptime_seconds",      "uptime_seconds" in r.json())

r = get("/metrics")
check("GET /metrics returns 200",            r.status_code == 200)
check("GET /metrics has total_requests",     "total_requests" in r.json())
check("GET /metrics has auth_failures",      "auth_failures" in r.json())

# ══════════════════════════════════════════════════════════════════════════════
# Section 2 — Synchronous /execute
# ══════════════════════════════════════════════════════════════════════════════
section("2. Synchronous /execute")

r = post("/execute", headers=AUTH,
         json={"script": "print('hello');", "args": {}})
check("POST /execute 200 for valid script",  r.status_code == 200)
check("POST /execute success=true",          r.json().get("success") is True)
check("POST /execute output contains hello", "hello" in str(r.json().get("output", [])))
check("POST /execute has request_id",        bool(r.json().get("request_id")))

r = post("/execute", headers=AUTH,
         json={"script": "var x = 6 * 7; x;", "args": {}})
check("POST /execute numeric result",        r.json().get("result") == 42)

r = post("/execute", headers=AUTH,
         json={"script": "var a = getArguments()[0]; a.greeting + ' world';",
               "args": {"greeting": "hello"}})
check("POST /execute args accessible",       r.json().get("result") == "hello world")

r = post("/execute", headers=AUTH,
         json={"script": "print('line1'); print('line2');", "args": {}})
output = r.json().get("output", [])
check("POST /execute multi-line output",     len(output) >= 2)

# Missing script field → 400
r = post("/execute", headers=AUTH, json={"args": {}})
check("POST /execute 400 missing script",    r.status_code == 400)

# Malformed JSON body → 400
r = requests.post(f"{BASE_URL}/execute",
                  headers={**AUTH, "Content-Type": "application/json"},
                  data="{bad json!}")
check("POST /execute 400 bad JSON",          r.status_code == 400)

# Auth failure — only meaningful when auth is enabled
_auth_enabled = get("/health").json().get("auth_enabled", False)
if _auth_enabled:
    r = post("/execute", headers={"X-API-Token": "invalid"},
             json={"script": "1;", "args": {}})
    check("POST /execute 401 bad token",         r.status_code == 401)

    r = post("/execute", json={"script": "1;", "args": {}})
    check("POST /execute 401 no token",          r.status_code == 401)
else:
    skip("POST /execute 401 bad token",  "auth disabled on server")
    skip("POST /execute 401 no token",   "auth disabled on server")

# Script file — conditional
SCRIPT_FILE = "y:/working/scripting/vangard-script-utils/vangard/scripts/CreateBasicCameraSU.dsa"
if os.path.exists(SCRIPT_FILE):
    r = post("/execute", headers=AUTH,
             json={"scriptFile": SCRIPT_FILE,
                   "args": {"cam_name": "test_cam", "cam_class": "SCAM", "focus": True}})
    check("POST /execute scriptFile 200",    r.status_code == 200)
else:
    skip("POST /execute scriptFile", "file not found")

# ══════════════════════════════════════════════════════════════════════════════
# Section 3 — Script Registry
# ══════════════════════════════════════════════════════════════════════════════
section("3. Script Registry")

SCRIPT_ID   = "test-greet-script"
SCRIPT_BODY = "var a = getArguments()[0]; 'Hi ' + a.name + '!';"

# Register
r = post("/scripts/register", headers=AUTH,
         json={"name": SCRIPT_ID, "description": "Test greeting", "script": SCRIPT_BODY})
check("POST /scripts/register 200",          r.status_code == 200)
check("POST /scripts/register success",      r.json().get("success") is True)

# Register duplicate — should overwrite, not error
r = post("/scripts/register", headers=AUTH,
         json={"name": SCRIPT_ID, "description": "Overwrite test", "script": SCRIPT_BODY})
check("POST /scripts/register overwrite ok", r.status_code == 200)

# List
r = get("/scripts", headers=AUTH)
check("GET /scripts returns 200",            r.status_code == 200)
ids = [s.get("name") for s in r.json().get("scripts", [])]
check("GET /scripts contains registered id", SCRIPT_ID in ids)

# Execute registered script
r = post(f"/scripts/{SCRIPT_ID}/execute", headers=AUTH,
         json={"args": {"name": "Tester"}})
check("POST /scripts/:id/execute 200",       r.status_code == 200)
check("POST /scripts/:id/execute result",    r.json().get("result") == "Hi Tester!")

# Execute with no args body
r = post(f"/scripts/{SCRIPT_ID}/execute", headers=AUTH, json={})
check("POST /scripts/:id/execute no args",   r.status_code == 200)

# Execute unknown script → 404
r = post("/scripts/does-not-exist/execute", headers=AUTH,
         json={"args": {}})
check("POST /scripts/:id/execute 404",       r.status_code == 404)

# Register validation: empty name → 400
r = post("/scripts/register", headers=AUTH,
         json={"name": "", "description": "", "script": "1;"})
check("POST /scripts/register 400 empty name", r.status_code == 400)

# Delete
r = delete(f"/scripts/{SCRIPT_ID}", headers=AUTH)
check("DELETE /scripts/:id 200",             r.status_code == 200)

# Confirm it's gone
r = post(f"/scripts/{SCRIPT_ID}/execute", headers=AUTH, json={"args": {}})
check("POST /scripts/:id/execute 404 after delete", r.status_code == 404)

# Delete non-existent → 404
r = delete("/scripts/no-such-script", headers=AUTH)
check("DELETE /scripts/:id 404 missing",     r.status_code == 404)

# Auth guard on registry
if _auth_enabled:
    r = post("/scripts/register", headers={"X-API-Token": "bad"},
             json={"name": "x", "description": "", "script": "1;"})
    check("POST /scripts/register 401 bad token", r.status_code == 401)
else:
    skip("POST /scripts/register 401 bad token", "auth disabled on server")

# ══════════════════════════════════════════════════════════════════════════════
# Section 4 — Async execution
# ══════════════════════════════════════════════════════════════════════════════
section("4. Async /execute/async")

# Submit async job
r = post("/execute/async", headers=AUTH,
         json={"script": "var x = 2 + 2; x;", "args": {}})
check("POST /execute/async 200",             r.status_code == 200)
data = r.json()
check("POST /execute/async has request_id",  bool(data.get("request_id")))
check("POST /execute/async status=queued",   data.get("status") == "queued")
check("POST /execute/async has submitted_at", bool(data.get("submitted_at")))

req_id = data.get("request_id", "")

# Status while potentially queued/running
r = get(f"/requests/{req_id}/status", headers=AUTH)
check("GET /requests/:id/status 200",        r.status_code == 200)
check("GET /requests/:id/status has status", "status" in r.json())
check("GET /requests/:id/status has id",     r.json().get("request_id") == req_id)

# Poll to completion
final = poll_async(req_id, timeout=30)
check("Async job reaches terminal state",    final.get("status") in ("completed", "failed"))
check("Async job completed (not failed)",    final.get("status") == "completed")

# Get result (no wait — already complete)
r = get(f"/requests/{req_id}/result", headers=AUTH)
check("GET /requests/:id/result 200",        r.status_code == 200)
result_data = r.json()
check("GET /requests/:id/result has result", "result" in result_data)
check("GET /requests/:id/result value=4",    result_data.get("result") == 4)
check("GET /requests/:id/result success",    result_data.get("success") is True)

# ── Async with wait=true (long-poll) ──────────────────────────────────────────
r = post("/execute/async", headers=AUTH,
         json={"script": "print('async output'); 99;", "args": {}})
check("POST /execute/async (long-poll test) 200", r.status_code == 200)
req_id2 = r.json().get("request_id", "")

r = get(f"/requests/{req_id2}/result?wait=true&timeout=30", headers=AUTH)
check("GET /requests/:id/result?wait=true 200",    r.status_code == 200)
check("GET /requests/:id/result?wait result=99",   r.json().get("result") == 99)
check("GET /requests/:id/result?wait has output",  "async output" in str(r.json().get("output", [])))

# ── List async requests ───────────────────────────────────────────────────────
r = get("/requests", headers=AUTH)
check("GET /requests 200",                   r.status_code == 200)
check("GET /requests is list or has items",  isinstance(r.json(), list) or "requests" in r.json())

# List with status filter
r = get("/requests?status=completed", headers=AUTH)
check("GET /requests?status=completed 200",  r.status_code == 200)

# ── Status for unknown request_id → 404 ──────────────────────────────────────
r = get("/requests/nonexistent-id/status", headers=AUTH)
check("GET /requests/:id/status 404 unknown", r.status_code == 404)

r = get("/requests/nonexistent-id/result", headers=AUTH)
check("GET /requests/:id/result 404 unknown", r.status_code == 404)

# ── Async missing script field → 400 ─────────────────────────────────────────
r = post("/execute/async", headers=AUTH, json={"args": {}})
check("POST /execute/async 400 missing script", r.status_code == 400)

# ── Async bad JSON → 400 ──────────────────────────────────────────────────────
r = requests.post(f"{BASE_URL}/execute/async",
                  headers={**AUTH, "Content-Type": "application/json"},
                  data="{invalid}")
check("POST /execute/async 400 bad JSON",    r.status_code == 400)

# ── Cancel a queued/running request ──────────────────────────────────────────
# Submit a long-running job so we can cancel it
r = post("/execute/async", headers=AUTH,
         json={"script": "var i; for(i=0;i<100000000;i++){} i;", "args": {}})
if r.status_code == 200:
    cancel_id = r.json().get("request_id", "")
    time.sleep(0.1)  # let it get picked up
    r_cancel = delete(f"/requests/{cancel_id}", headers=AUTH)
    check("DELETE /requests/:id cancel 200 or 409",
          r_cancel.status_code in (200, 409))
    # If accepted, status should eventually be cancelled
    if r_cancel.status_code == 200:
        final_c = poll_async(cancel_id, timeout=15)
        check("Cancelled job reaches terminal state",
              final_c.get("status") in ("cancelled", "completed", "failed"))
    else:
        skip("Cancel terminal state check", "cancel returned 409 (already terminal)")
else:
    skip("Cancel test", "could not submit job")

# ══════════════════════════════════════════════════════════════════════════════
# Section 5 — Async Script Registry
# ══════════════════════════════════════════════════════════════════════════════
section("5. Async Script Registry (/scripts/:id/async)")

ASYNC_SCRIPT_ID = "test-async-script"

# Register a script
r = post("/scripts/register", headers=AUTH,
         json={"name": ASYNC_SCRIPT_ID, "description": "Async test script",
               "script": "var a = getArguments()[0]; a.x * 2;"})
check("Register script for async test",      r.status_code == 200)

# Submit async via registry
r = post(f"/scripts/{ASYNC_SCRIPT_ID}/async", headers=AUTH,
         json={"args": {"x": 21}})
check("POST /scripts/:id/async 200",         r.status_code == 200)
ras_id = r.json().get("request_id", "")
check("POST /scripts/:id/async has request_id", bool(ras_id))
check("POST /scripts/:id/async status=queued", r.json().get("status") == "queued")

# Wait for result
r = get(f"/requests/{ras_id}/result?wait=true&timeout=30", headers=AUTH)
check("Async registry script result 200",    r.status_code == 200)
check("Async registry script result=42",     r.json().get("result") == 42)

# Async via unknown script → 404
r = post("/scripts/no-such-script/async", headers=AUTH, json={"args": {}})
check("POST /scripts/:id/async 404 unknown", r.status_code == 404)

# Cleanup
delete(f"/scripts/{ASYNC_SCRIPT_ID}", headers=AUTH)

# ══════════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════════
ok = summary()
sys.exit(0 if ok else 1)
