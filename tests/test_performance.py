"""
Performance benchmarks and load tests for DazScriptServer.

Measures throughput, latency, and graceful-degradation behavior.
Run with: python tests/test_performance.py [--url http://127.0.0.1:18811]

Dependencies: requests  (pip install requests)

Results are printed to stdout. The script exits 0 only if all hard assertions pass.
Soft performance targets (throughput, p99 latency) are reported but do not fail the run
when the server runs inside DAZ Studio (which serializes script execution on the Qt thread).
"""

import argparse
import os
import statistics
import sys
import threading
import time
import requests

# ── Config ────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="DazScriptServer performance tests")
parser.add_argument("--url", default="http://127.0.0.1:18811", help="Server base URL")
parser.add_argument("--quick", action="store_true", help="Run fewer iterations (CI mode)")
args = parser.parse_args()

BASE_URL = args.url.rstrip("/")
TOKEN_FILE = os.path.expanduser("~/.daz3d/dazscriptserver_token.txt")

api_token = ""
if os.path.exists(TOKEN_FILE):
    with open(TOKEN_FILE) as f:
        api_token = f.read().strip()

AUTH = {"X-API-Token": api_token}

# ── Test harness ──────────────────────────────────────────────────────────────

_passed = 0
_failed = 0
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


def soft_check(label: str, condition: bool, detail: str = ""):
    """Non-failing check — reports WARN instead of FAIL when condition is False."""
    global _passed
    if condition:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        print(f"  WARN  {label} | {detail}")


def skip(label: str, reason: str = ""):
    global _skipped
    _skipped += 1
    print(f"  SKIP  {label}{(' (' + reason + ')') if reason else ''}")


def section(title: str):
    print(f"\n{'─' * 65}")
    print(f"  {title}")
    print(f"{'─' * 65}")


def summary() -> bool:
    total = _passed + _failed + _skipped
    print(f"\n{'═' * 65}")
    print(f"  Results: {_passed} passed, {_failed} failed, {_skipped} skipped  ({total} total)")
    print(f"{'═' * 65}")
    return _failed == 0


# ── Helpers ───────────────────────────────────────────────────────────────────

def get(path, **kwargs):
    return requests.get(f"{BASE_URL}{path}", **kwargs)


def post(path, **kwargs):
    return requests.post(f"{BASE_URL}{path}", **kwargs)


def delete(path, **kwargs):
    return requests.delete(f"{BASE_URL}{path}", **kwargs)


def iife(body: str) -> str:
    return f"(function() {{ {body} }})()"


def execute(script: str, args=None, timeout: int = 30) -> requests.Response:
    payload = {"script": script}
    if args is not None:
        payload["args"] = args
    return post("/execute", headers=AUTH, json=payload, timeout=timeout)


def poll_async(request_id: str, timeout: int = 60) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = get(f"/requests/{request_id}/status", headers=AUTH, timeout=5)
        if r.status_code != 200:
            return {"status": "error", "_http": r.status_code}
        data = r.json()
        if data.get("status") in ("completed", "failed", "cancelled"):
            return data
        time.sleep(0.1)
    return {"status": "timeout"}


# ── Pre-flight ────────────────────────────────────────────────────────────────

try:
    r = get("/status", timeout=5)
    if r.status_code != 200:
        print(f"ERROR: /status returned {r.status_code}")
        sys.exit(1)
    server_version = r.json().get("version", "unknown")
except requests.exceptions.ConnectionError:
    print(f"ERROR: Cannot connect to {BASE_URL}")
    print("Is DAZ Studio running with the DazScriptServer plugin loaded?")
    sys.exit(1)

auth_enabled = get("/health", timeout=5).json().get("auth_enabled", False)

ITERS_FULL = 50
ITERS_QUICK = 15
N = ITERS_QUICK if args.quick else ITERS_FULL

print(f"\nDazScriptServer Performance Benchmarks")
print(f"  Server : {BASE_URL}  (version {server_version})")
print(f"  Auth   : {'enabled' if auth_enabled else 'disabled'}")
print(f"  Mode   : {'quick (%d iters)' % N if args.quick else 'full (%d iters)' % N}")

# ══════════════════════════════════════════════════════════════════════════════
# 1. Baseline latency — sequential requests
# ══════════════════════════════════════════════════════════════════════════════
section("1. Baseline latency (sequential)")

latencies_ms = []
errors = 0

for i in range(N):
    t0 = time.perf_counter()
    try:
        r = execute(iife("return 1;"), timeout=10)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        if r.status_code == 200:
            latencies_ms.append(elapsed_ms)
        else:
            errors += 1
    except Exception:
        errors += 1

check("All sequential requests succeeded",
      errors == 0, f"{errors}/{N} failed")

if latencies_ms:
    latencies_ms.sort()
    p50 = latencies_ms[len(latencies_ms) // 2]
    p90 = latencies_ms[int(len(latencies_ms) * 0.90)]
    p99 = latencies_ms[min(int(len(latencies_ms) * 0.99), len(latencies_ms) - 1)]
    mean = statistics.mean(latencies_ms)
    print(f"  Latency — mean={mean:.1f}ms  p50={p50:.1f}ms  p90={p90:.1f}ms  p99={p99:.1f}ms")
    soft_check("p99 latency < 2000ms", p99 < 2000,
               f"p99={p99:.0f}ms (DazScript runs on Qt main thread, higher latency expected)")

# ══════════════════════════════════════════════════════════════════════════════
# 2. Throughput — sequential
# ══════════════════════════════════════════════════════════════════════════════
section("2. Throughput (sequential)")

t_start = time.perf_counter()
success_count = 0
for _ in range(N):
    try:
        r = execute(iife("return 1;"), timeout=10)
        if r.status_code == 200:
            success_count += 1
    except Exception:
        pass
elapsed = time.perf_counter() - t_start
rps = success_count / elapsed if elapsed > 0 else 0

print(f"  Throughput: {rps:.1f} req/sec  ({success_count}/{N} succeeded in {elapsed:.2f}s)")
check("At least 1 successful request in throughput test", success_count > 0)
soft_check("Throughput ≥ 5 req/sec",
           rps >= 5,
           f"got {rps:.1f} req/sec (DAZ Studio serializes all DazScript execution)")

# ══════════════════════════════════════════════════════════════════════════════
# 3. Concurrent load — fixed thread counts
# ══════════════════════════════════════════════════════════════════════════════
section("3. Concurrent load")


def run_concurrent(n_threads: int, script: str) -> dict:
    results = []
    lock = threading.Lock()

    def worker():
        try:
            r = execute(script, timeout=30)
            with lock:
                results.append(r.status_code)
        except Exception:
            with lock:
                results.append(-1)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    elapsed = time.perf_counter() - t0

    ok = sum(1 for c in results if c == 200)
    throttled = sum(1 for c in results if c == 429)
    errors = sum(1 for c in results if c not in (200, 429))
    return {"ok": ok, "throttled": throttled, "errors": errors,
            "elapsed": elapsed, "total": len(results)}


for n_threads in (5, 10, 20):
    res = run_concurrent(n_threads, iife("return 1;"))
    label = f"{n_threads} concurrent threads"
    check(f"{label} — no 5xx or connection errors",
          res["errors"] == 0,
          f"{res['errors']} error responses")
    check(f"{label} — all responses received",
          res["total"] == n_threads,
          f"only {res['total']}/{n_threads} responses")
    print(f"  {label}: {res['ok']} ok, {res['throttled']} throttled (429), "
          f"{res['errors']} errors  in {res['elapsed']:.2f}s")

# ══════════════════════════════════════════════════════════════════════════════
# 4. Concurrent limit enforcement (429)
# ══════════════════════════════════════════════════════════════════════════════
section("4. Concurrent limit enforcement")

# Send enough threads to guarantee exceeding default limit (10)
OVERLOAD = 25
res = run_concurrent(OVERLOAD, iife("var i; for(i=0;i<200000;i++){} i;"))
check("Server returns 200 or 429, never 5xx",
      res["errors"] == 0,
      f"{res['errors']} unexpected error responses")
check("At least some requests succeeded",
      res["ok"] > 0,
      "all requests were throttled or errored")

if res["throttled"] > 0:
    print(f"  429 returned for {res['throttled']}/{OVERLOAD} requests over concurrent limit — correct")
else:
    print(f"  No 429s observed; server queued all {OVERLOAD} requests (limit may be high or disabled)")

# ══════════════════════════════════════════════════════════════════════════════
# 5. Rate limit behavior
# ══════════════════════════════════════════════════════════════════════════════
section("5. Rate limit behavior")

health_data = get("/health", timeout=5).json()
rate_limit_enabled = health_data.get("rate_limit_enabled", False)

if not rate_limit_enabled:
    skip("Rate limit trigger test", "rate limiting disabled on server")
    skip("Recovery after rate limit", "rate limiting disabled on server")
else:
    rate_limit = health_data.get("rate_limit_requests", 60)
    print(f"  Rate limit: {rate_limit} req/window")

    # Blast enough requests to likely trigger the rate limit
    burst = min(rate_limit + 10, 80)
    statuses = []
    for _ in range(burst):
        try:
            r = execute(iife("return 1;"), timeout=5)
            statuses.append(r.status_code)
        except Exception:
            statuses.append(-1)

    got_429 = any(c == 429 for c in statuses)
    got_5xx = any(c >= 500 for c in statuses)
    check("Rate limit returns 429 (not 5xx) when exceeded",
          got_429 and not got_5xx,
          f"got_429={got_429}, got_5xx={got_5xx}")

# ══════════════════════════════════════════════════════════════════════════════
# 6. Payload size enforcement
# ══════════════════════════════════════════════════════════════════════════════
section("6. Payload size enforcement")

sizes_mb = [1, 4, 6]
for size_mb in sizes_mb:
    payload_bytes = "x" * (size_mb * 1024 * 1024)
    try:
        r = requests.post(
            f"{BASE_URL}/execute",
            headers={**AUTH, "Content-Type": "application/json"},
            data=f'{{"script": "{payload_bytes}"}}',
            timeout=30,
        )
        code = r.status_code
    except Exception as e:
        code = -1

    if size_mb <= 4:
        # Within default 5MB limit — should be 200 or 400 (script too long), not 413
        check(f"{size_mb}MB body accepted (not 413)",
              code != 413,
              f"got {code}")
    else:
        # Over limit — must be 413
        check(f"{size_mb}MB body rejected with 413",
              code == 413,
              f"got {code}")

# ══════════════════════════════════════════════════════════════════════════════
# 7. Async queue throughput
# ══════════════════════════════════════════════════════════════════════════════
section("7. Async queue throughput")

N_ASYNC = min(N, 20)
request_ids = []
t0 = time.perf_counter()
for _ in range(N_ASYNC):
    try:
        r = post("/execute/async",
                 headers=AUTH,
                 json={"script": iife("return 1;")},
                 timeout=10)
        if r.status_code == 200:
            request_ids.append(r.json()["request_id"])
    except Exception:
        pass
submit_elapsed = time.perf_counter() - t0

check("Async submissions succeeded",
      len(request_ids) > 0,
      f"0/{N_ASYNC} submissions accepted")
if request_ids:
    submit_rps = len(request_ids) / submit_elapsed if submit_elapsed > 0 else 0
    print(f"  Submit rate: {submit_rps:.1f} submissions/sec  ({len(request_ids)}/{N_ASYNC} accepted)")

    # Wait for all to complete
    t1 = time.perf_counter()
    all_complete = True
    for rid in request_ids:
        final = poll_async(rid, timeout=60)
        if final.get("status") not in ("completed", "failed"):
            all_complete = False
    total_elapsed = time.perf_counter() - t1

    check("All async requests reach terminal state", all_complete)
    if all_complete and request_ids:
        throughput = len(request_ids) / (submit_elapsed + total_elapsed)
        print(f"  End-to-end async throughput: {throughput:.2f} req/sec")

# ══════════════════════════════════════════════════════════════════════════════
# 8. Rapid reconnect stress
# ══════════════════════════════════════════════════════════════════════════════
section("8. Rapid reconnect stress")

RECONNECT_N = min(N, 20)
reconnect_errors = 0
for _ in range(RECONNECT_N):
    try:
        # Each call opens a new TCP connection (no session reuse)
        r = requests.get(f"{BASE_URL}/status", timeout=3)
        if r.status_code != 200:
            reconnect_errors += 1
    except Exception:
        reconnect_errors += 1

check("Rapid reconnect — no connection errors",
      reconnect_errors == 0,
      f"{reconnect_errors}/{RECONNECT_N} connections failed")

# ══════════════════════════════════════════════════════════════════════════════
# 9. Metrics update under load
# ══════════════════════════════════════════════════════════════════════════════
section("9. Metrics consistency")

before = get("/metrics", timeout=5).json()
baseline = before.get("total_requests", 0)

for _ in range(5):
    execute(iife("return 1;"), timeout=10)

after = get("/metrics", timeout=5).json()
new_total = after.get("total_requests", 0)

check("Metrics total_requests increments after requests",
      new_total > baseline,
      f"before={baseline} after={new_total}")

# ── Summary ───────────────────────────────────────────────────────────────────
ok = summary()
sys.exit(0 if ok else 1)
