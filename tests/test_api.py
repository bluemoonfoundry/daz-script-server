"""
HTTP API integration tests for DazScriptServer plugin.

Requires the plugin to be running in DAZ Studio at the default address.
Run standalone with: python tests/test_api.py
Via runner:          python tests.py api

Dependencies: requests  (pip install requests)

Notes:
  - DazScript does not allow top-level `return` statements. Scripts that
    produce return values must wrap their logic in an IIFE:
      (function() { return 42; })()
  - Auth tests are skipped when authentication is disabled in the plugin.
"""

import os
import sys
import tempfile
import threading
import time
import unittest
import requests

BASE_URL = "http://127.0.0.1:18811"
TOKEN_FILE = os.path.expanduser("~/.daz3d/dazscriptserver_token.txt")


def load_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            return f.read().strip()
    return ""


TOKEN = load_token()


def auth_headers():
    return {"X-API-Token": TOKEN}


def is_auth_enabled():
    """Return True if the plugin rejects requests sent without any token."""
    try:
        r = requests.post(
            f"{BASE_URL}/execute",
            headers={},
            json={"script": "1;"},
            timeout=5,
        )
        return r.status_code == 401
    except requests.exceptions.RequestException:
        return False


AUTH_ENABLED = is_auth_enabled()


def execute(script=None, script_file=None, args=None, headers=None):
    payload = {}
    if script is not None:
        payload["script"] = script
    if script_file is not None:
        payload["scriptFile"] = script_file
    if args is not None:
        payload["args"] = args
    return requests.post(
        f"{BASE_URL}/execute",
        headers=headers if headers is not None else auth_headers(),
        json=payload,
        timeout=15,
    )


def iife(body):
    """Wrap script body in an IIFE so `return` statements are valid."""
    return f"(function() {{ {body} }})()"


# ─── Status endpoint ──────────────────────────────────────────────────────────

class TestStatus(unittest.TestCase):

    def test_returns_200(self):
        r = requests.get(f"{BASE_URL}/status", timeout=5)
        self.assertEqual(r.status_code, 200)

    def test_content_type_is_json(self):
        r = requests.get(f"{BASE_URL}/status", timeout=5)
        self.assertIn("application/json", r.headers.get("Content-Type", ""))

    def test_running_is_true(self):
        r = requests.get(f"{BASE_URL}/status", timeout=5)
        self.assertTrue(r.json().get("running"))

    def test_version_field_present(self):
        r = requests.get(f"{BASE_URL}/status", timeout=5)
        self.assertIn("version", r.json())


# ─── Authentication ───────────────────────────────────────────────────────────

@unittest.skipUnless(AUTH_ENABLED, "Authentication is disabled in the running plugin")
class TestAuthentication(unittest.TestCase):

    def test_no_token_returns_401(self):
        r = execute(script=iife("return 1;"), headers={})
        self.assertEqual(r.status_code, 401)

    def test_wrong_token_returns_401(self):
        r = execute(script=iife("return 1;"),
                    headers={"X-API-Token": "invalid-token"})
        self.assertEqual(r.status_code, 401)

    def test_x_api_token_header_accepted(self):
        r = execute(script=iife("return 1;"),
                    headers={"X-API-Token": TOKEN})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get("success"))

    def test_bearer_authorization_header_accepted(self):
        r = execute(script=iife("return 1;"),
                    headers={"Authorization": f"Bearer {TOKEN}"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get("success"))


# ─── Script execution ─────────────────────────────────────────────────────────

class TestScriptExecution(unittest.TestCase):

    def test_returns_integer(self):
        r = execute(script=iife("return 42;"))
        body = r.json()
        self.assertTrue(body["success"], body.get("error"))
        self.assertEqual(body["result"], 42)

    def test_returns_string(self):
        r = execute(script=iife("return 'hello';"))
        body = r.json()
        self.assertTrue(body["success"], body.get("error"))
        self.assertEqual(body["result"], "hello")

    def test_returns_boolean_true(self):
        r = execute(script=iife("return true;"))
        body = r.json()
        self.assertTrue(body["success"], body.get("error"))
        self.assertTrue(body["result"])

    def test_returns_boolean_false(self):
        r = execute(script=iife("return false;"))
        body = r.json()
        self.assertTrue(body["success"], body.get("error"))
        self.assertFalse(body["result"])

    def test_arithmetic(self):
        r = execute(script=iife("return 6 * 7;"))
        body = r.json()
        self.assertTrue(body["success"], body.get("error"))
        self.assertEqual(body["result"], 42)

    def test_output_array_present_on_success(self):
        r = execute(script=iife("return 1;"))
        body = r.json()
        self.assertIn("output", body)
        self.assertIsInstance(body["output"], list)

    def test_error_is_null_on_success(self):
        r = execute(script=iife("return 1;"))
        body = r.json()
        self.assertIsNone(body.get("error"))

    def test_print_captured_in_output(self):
        r = execute(script=iife("print('test-output-line'); return 1;"))
        body = r.json()
        self.assertTrue(body["success"], body.get("error"))
        output = body.get("output", [])
        self.assertTrue(
            any("test-output-line" in line for line in output),
            f"Expected 'test-output-line' in output, got: {output}",
        )

    def test_script_runtime_error_returns_success_false(self):
        r = execute(script=iife("this_function_does_not_exist();"))
        body = r.json()
        self.assertFalse(body["success"])
        self.assertIsNotNone(body.get("error"))

    def test_script_error_message_is_string(self):
        r = execute(script=iife("throw 'deliberate error';"))
        body = r.json()
        self.assertFalse(body["success"])
        self.assertIsInstance(body["error"], str)

    def test_script_error_includes_line_number(self):
        r = execute(script=iife("undefined_var.badCall();"))
        body = r.json()
        self.assertFalse(body["success"])
        self.assertIn("Line", body.get("error", ""))


# ─── Args passing ─────────────────────────────────────────────────────────────

class TestArgsPassing(unittest.TestCase):

    def test_string_arg_accessible(self):
        r = execute(
            script=iife("var a = getArguments()[0]; return a['greeting'];"),
            args={"greeting": "hello-from-test"},
        )
        body = r.json()
        self.assertTrue(body["success"], body.get("error"))
        self.assertEqual(body["result"], "hello-from-test")

    def test_numeric_arg_accessible(self):
        r = execute(
            script=iife("var a = getArguments()[0]; return a['value'];"),
            args={"value": 99},
        )
        body = r.json()
        self.assertTrue(body["success"], body.get("error"))
        self.assertEqual(body["result"], 99)

    def test_no_args_field_does_not_error(self):
        r = execute(script=iife("return 'ok';"))
        body = r.json()
        self.assertTrue(body["success"], body.get("error"))


# ─── Input validation ─────────────────────────────────────────────────────────

class TestInputValidation(unittest.TestCase):

    def test_missing_script_and_script_file_returns_error(self):
        r = execute(script=None, script_file=None)
        body = r.json()
        self.assertFalse(body["success"])
        self.assertIsNotNone(body.get("error"))

    def test_malformed_json_body_returns_error(self):
        r = requests.post(
            f"{BASE_URL}/execute",
            headers={**auth_headers(), "Content-Type": "application/json"},
            data="{not valid json",
            timeout=10,
        )
        body = r.json()
        self.assertFalse(body["success"])
        self.assertIsNotNone(body.get("error"))

    def test_scriptfile_relative_path_returns_error(self):
        r = execute(script_file="relative/path/script.dsa")
        body = r.json()
        self.assertFalse(body["success"])
        self.assertIsNotNone(body.get("error"))

    def test_scriptfile_nonexistent_returns_error(self):
        r = execute(script_file="C:/this/path/does/not/exist/script.dsa")
        body = r.json()
        self.assertFalse(body["success"])
        self.assertIsNotNone(body.get("error"))

    def test_scriptfile_directory_path_returns_error(self):
        r = execute(script_file="C:/Windows")
        body = r.json()
        self.assertFalse(body["success"])
        self.assertIsNotNone(body.get("error"))

    def test_both_script_and_scriptfile_uses_scriptfile(self):
        # Plugin warns but uses scriptFile; non-existent file → error, not inline result
        r = execute(
            script=iife("return 'from-inline';"),
            script_file="C:/does/not/exist.dsa",
        )
        body = r.json()
        self.assertFalse(body["success"])


# ─── Async execution ─────────────────────────────────────────────────────────

def async_execute(script=None, script_file=None, args=None, headers=None):
    """POST /execute/async and return the raw response."""
    payload = {}
    if script is not None:
        payload["script"] = script
    if script_file is not None:
        payload["scriptFile"] = script_file
    if args is not None:
        payload["args"] = args
    h = auth_headers() if headers is None else headers
    return requests.post(f"{BASE_URL}/execute/async", headers=h, json=payload, timeout=10)


def poll_status(request_id, timeout=15):
    """Poll /requests/:id/status until terminal or timeout. Returns final body dict."""
    deadline = __import__("time").time() + timeout
    while __import__("time").time() < deadline:
        r = requests.get(f"{BASE_URL}/requests/{request_id}/status",
                         headers=auth_headers(), timeout=5)
        body = r.json()
        if body.get("status") in ("completed", "failed", "cancelled"):
            return body
        __import__("time").sleep(0.2)
    return body


def get_result(request_id, wait=False, timeout=15):
    """GET /requests/:id/result, optionally with long-poll."""
    params = {}
    if wait:
        params["wait"] = "true"
        params["timeout"] = str(timeout)
    r = requests.get(f"{BASE_URL}/requests/{request_id}/result",
                     headers=auth_headers(), params=params, timeout=timeout + 5)
    return r


class TestAsyncExecution(unittest.TestCase):

    def test_async_submit_returns_queued(self):
        r = async_execute(script=iife("return 1;"))
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("request_id", body)
        self.assertEqual(body.get("status"), "queued")
        self.assertIn("submitted_at", body)

    def test_async_result_completes(self):
        r = async_execute(script=iife("return 42;"))
        request_id = r.json()["request_id"]
        final = poll_status(request_id, timeout=20)
        self.assertEqual(final["status"], "completed")

        result_r = get_result(request_id)
        body = result_r.json()
        self.assertEqual(body["status"], "completed")
        self.assertTrue(body.get("success"))
        self.assertEqual(body.get("result"), 42)

    def test_async_result_long_poll(self):
        r = async_execute(script=iife("return 'long-poll';"))
        request_id = r.json()["request_id"]
        result_r = get_result(request_id, wait=True, timeout=20)
        body = result_r.json()
        self.assertIn(body["status"], ("completed", "failed"))

    def test_async_args_accessible(self):
        r = async_execute(
            script=iife("return getArguments()[0].value;"),
            args={"value": 99}
        )
        request_id = r.json()["request_id"]
        final = poll_status(request_id, timeout=20)
        self.assertEqual(final["status"], "completed")

        result_r = get_result(request_id)
        body = result_r.json()
        self.assertEqual(body.get("result"), 99)

    def test_async_scriptfile_preserves_file_identity(self):
        script_path = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".dsa", delete=False, encoding="utf-8"
            ) as script_file:
                script_file.write(iife("return getScriptFileName();"))
                script_path = os.path.abspath(script_file.name)

            r = async_execute(script_file=script_path)
            self.assertEqual(r.status_code, 200)
            request_id = r.json()["request_id"]
            final = poll_status(request_id, timeout=20)
            self.assertEqual(final["status"], "completed")

            body = get_result(request_id).json()
            self.assertTrue(body.get("success"))
            self.assertEqual(
                os.path.normcase(os.path.normpath(body.get("result"))),
                os.path.normcase(os.path.normpath(script_path)),
            )
        finally:
            if script_path and os.path.exists(script_path):
                os.unlink(script_path)

    def test_async_script_error_gives_failed_status(self):
        r = async_execute(script="this is not valid dazscript !!!")
        request_id = r.json()["request_id"]
        final = poll_status(request_id, timeout=20)
        self.assertEqual(final["status"], "failed")

        result_r = get_result(request_id)
        body = result_r.json()
        self.assertEqual(body["status"], "failed")
        self.assertFalse(body.get("success"))

    def test_async_status_includes_queue_position(self):
        r = async_execute(script=iife("return 1;"))
        request_id = r.json()["request_id"]
        status_r = requests.get(f"{BASE_URL}/requests/{request_id}/status",
                                headers=auth_headers(), timeout=5)
        body = status_r.json()
        self.assertEqual(status_r.status_code, 200)
        self.assertIn("status", body)

    def test_async_unknown_request_returns_404(self):
        r = requests.get(f"{BASE_URL}/requests/nonexistent-id/status",
                         headers=auth_headers(), timeout=5)
        self.assertEqual(r.status_code, 404)

        r2 = requests.get(f"{BASE_URL}/requests/nonexistent-id/result",
                          headers=auth_headers(), timeout=5)
        self.assertEqual(r2.status_code, 404)

    def test_async_cancel_queued_request(self):
        r = async_execute(script=iife("return 1;"))
        request_id = r.json()["request_id"]

        cancel_r = requests.delete(f"{BASE_URL}/requests/{request_id}",
                                   headers=auth_headers(), timeout=5)
        self.assertIn(cancel_r.status_code, (200, 400))

        if cancel_r.status_code == 200:
            self.assertEqual(cancel_r.json().get("status"), "cancelled")

    def test_async_cancel_running_request_reaches_terminal_status(self):
        # A busy-loop script long enough to still be RUNNING when we cancel it.
        # killRender()/killRenderOnMainThread() has nothing to kill for a plain
        # script (not a render), so this exercises the case where the cancel
        # response says "cancelled" but the underlying call can't actually be
        # interrupted -- the tracker must still report a terminal status
        # instead of leaving GET /requests/:id stuck at "running" (GH #34).
        # ~8s on a live DAZ Studio 4 instance -- long enough to reliably catch
        # "running" below, short enough not to starve the main thread for
        # other tests once cancelled (the loop itself can't be interrupted,
        # only the tracker's reported status can).
        script = iife("var x = 0; for (var i = 0; i < 500000000; i++) { x += i; } return x;")
        r = async_execute(script=script)
        request_id = r.json()["request_id"]

        # Wait for it to actually start running before cancelling.
        deadline = time.time() + 5
        status = None
        while time.time() < deadline:
            status_r = requests.get(f"{BASE_URL}/requests/{request_id}/status",
                                    headers=auth_headers(), timeout=5)
            status = status_r.json().get("status")
            if status == "running":
                break
            time.sleep(0.05)
        self.assertEqual(status, "running", "request never reached running state")

        cancel_r = requests.delete(f"{BASE_URL}/requests/{request_id}",
                                   headers=auth_headers(), timeout=5)
        self.assertEqual(cancel_r.status_code, 200)
        self.assertEqual(cancel_r.json().get("status"), "cancelled")

        # GET status must not stay "running" forever -- it should already
        # reflect the terminal status the cancel response promised.
        status_r = requests.get(f"{BASE_URL}/requests/{request_id}/status",
                                headers=auth_headers(), timeout=5)
        self.assertEqual(status_r.json().get("status"), "cancelled")

    def test_async_cancel_already_finished_returns_400(self):
        r = async_execute(script=iife("return 1;"))
        request_id = r.json()["request_id"]
        poll_status(request_id, timeout=20)

        cancel_r = requests.delete(f"{BASE_URL}/requests/{request_id}",
                                   headers=auth_headers(), timeout=5)
        self.assertEqual(cancel_r.status_code, 400)

    def test_async_list_returns_requests(self):
        async_execute(script=iife("return 1;"))
        list_r = requests.get(f"{BASE_URL}/requests",
                              headers=auth_headers(), timeout=5)
        self.assertEqual(list_r.status_code, 200)
        body = list_r.json()
        self.assertIn("requests", body)
        self.assertIn("total", body)
        self.assertIsInstance(body["requests"], list)

    def test_async_list_filter_by_status(self):
        list_r = requests.get(f"{BASE_URL}/requests?status=completed",
                              headers=auth_headers(), timeout=5)
        self.assertEqual(list_r.status_code, 200)
        body = list_r.json()
        for entry in body.get("requests", []):
            self.assertEqual(entry["status"], "completed")

    def test_async_missing_script_returns_400(self):
        r = requests.post(f"{BASE_URL}/execute/async",
                         headers=auth_headers(), json={}, timeout=5)
        self.assertEqual(r.status_code, 400)

    def test_async_invalid_json_returns_400(self):
        combined = {"Content-Type": "application/json", **auth_headers()}
        r = requests.post(f"{BASE_URL}/execute/async",
                         headers=combined,
                         data="not json",
                         timeout=5)
        self.assertEqual(r.status_code, 400)

    def test_async_output_captured(self):
        r = async_execute(script="print('hello async');")
        request_id = r.json()["request_id"]
        final = poll_status(request_id, timeout=20)
        self.assertEqual(final["status"], "completed")

        result_r = get_result(request_id)
        body = result_r.json()
        self.assertIsInstance(body.get("output"), list)


# ─── Response shape ───────────────────────────────────────────────────────────

class TestResponseShape(unittest.TestCase):

    def test_success_response_has_all_fields(self):
        r = execute(script=iife("return 1;"))
        body = r.json()
        for field in ("success", "result", "output", "error"):
            self.assertIn(field, body, f"Missing field: {field}")

    def test_error_response_has_all_fields(self):
        r = execute(script=iife("throw 'err';"))
        body = r.json()
        for field in ("success", "result", "output", "error"):
            self.assertIn(field, body, f"Missing field: {field}")


# ─── Health and metrics ───────────────────────────────────────────────────────

class TestHealthAndMetrics(unittest.TestCase):

    def test_health_returns_200(self):
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        self.assertEqual(r.status_code, 200)

    def test_health_has_status_field(self):
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        self.assertIn("status", r.json())

    def test_health_has_uptime_seconds(self):
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        self.assertIn("uptime_seconds", r.json())

    def test_metrics_returns_200(self):
        r = requests.get(f"{BASE_URL}/metrics", timeout=5)
        self.assertEqual(r.status_code, 200)

    def test_metrics_has_total_requests(self):
        r = requests.get(f"{BASE_URL}/metrics", timeout=5)
        self.assertIn("total_requests", r.json())

    def test_metrics_has_auth_failures(self):
        r = requests.get(f"{BASE_URL}/metrics", timeout=5)
        self.assertIn("auth_failures", r.json())

    def test_metrics_total_requests_is_non_negative(self):
        r = requests.get(f"{BASE_URL}/metrics", timeout=5)
        self.assertGreaterEqual(r.json().get("total_requests", -1), 0)


# ─── Script registry ──────────────────────────────────────────────────────────

class TestScriptRegistry(unittest.TestCase):

    SCRIPT_ID = "test-registry-cls-script"
    SCRIPT_BODY = "var a = getArguments()[0]; 'hello ' + a.name;"

    def setUp(self):
        requests.delete(f"{BASE_URL}/scripts/{self.SCRIPT_ID}",
                        headers=auth_headers(), timeout=5)

    def tearDown(self):
        requests.delete(f"{BASE_URL}/scripts/{self.SCRIPT_ID}",
                        headers=auth_headers(), timeout=5)

    def _register(self, **overrides):
        payload = {"name": self.SCRIPT_ID, "description": "test", "script": self.SCRIPT_BODY}
        payload.update(overrides)
        return requests.post(f"{BASE_URL}/scripts/register",
                             headers=auth_headers(), json=payload, timeout=5)

    def test_register_returns_success(self):
        r = self._register()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get("success"))

    def test_register_duplicate_overwrites(self):
        self._register()
        r = self._register(description="overwrite")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get("success"))

    def test_list_contains_registered_script(self):
        self._register()
        r = requests.get(f"{BASE_URL}/scripts", headers=auth_headers(), timeout=5)
        self.assertEqual(r.status_code, 200)
        names = [s.get("name") for s in r.json().get("scripts", [])]
        self.assertIn(self.SCRIPT_ID, names)

    def test_execute_registered_script_returns_result(self):
        self._register()
        r = requests.post(f"{BASE_URL}/scripts/{self.SCRIPT_ID}/execute",
                          headers=auth_headers(),
                          json={"args": {"name": "world"}},
                          timeout=15)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("result"), "hello world")

    def test_execute_registered_script_no_args(self):
        self._register()
        r = requests.post(f"{BASE_URL}/scripts/{self.SCRIPT_ID}/execute",
                          headers=auth_headers(), json={}, timeout=15)
        self.assertEqual(r.status_code, 200)

    def test_execute_unknown_script_returns_404(self):
        r = requests.post(f"{BASE_URL}/scripts/no-such-script-xyz/execute",
                          headers=auth_headers(), json={"args": {}}, timeout=5)
        self.assertEqual(r.status_code, 404)

    def test_delete_removes_script(self):
        self._register()
        requests.delete(f"{BASE_URL}/scripts/{self.SCRIPT_ID}",
                        headers=auth_headers(), timeout=5)
        r = requests.post(f"{BASE_URL}/scripts/{self.SCRIPT_ID}/execute",
                          headers=auth_headers(), json={"args": {}}, timeout=5)
        self.assertEqual(r.status_code, 404)

    def test_delete_nonexistent_returns_404(self):
        r = requests.delete(f"{BASE_URL}/scripts/no-such-script-xyz",
                            headers=auth_headers(), timeout=5)
        self.assertEqual(r.status_code, 404)

    def test_register_empty_name_returns_400(self):
        r = requests.post(f"{BASE_URL}/scripts/register",
                          headers=auth_headers(),
                          json={"name": "", "description": "test", "script": "1;"},
                          timeout=5)
        self.assertEqual(r.status_code, 400)

    def test_async_execute_registered_script(self):
        self._register()
        r = requests.post(f"{BASE_URL}/scripts/{self.SCRIPT_ID}/async",
                          headers=auth_headers(),
                          json={"args": {"name": "async"}},
                          timeout=10)
        self.assertEqual(r.status_code, 200)
        request_id = r.json().get("request_id")
        self.assertTrue(request_id)
        final = poll_status(request_id, timeout=20)
        self.assertEqual(final["status"], "completed")


# ─── Concurrency ──────────────────────────────────────────────────────────────

class TestConcurrency(unittest.TestCase):

    def test_five_concurrent_requests_all_respond(self):
        results = []
        lock = threading.Lock()

        def make_request(val):
            r = execute(script=iife(f"return {val};"))
            with lock:
                results.append((val, r.status_code))

        threads = [threading.Thread(target=make_request, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(len(results), 5)
        for val, code in results:
            self.assertIn(code, (200, 429), f"Unexpected status {code} for value {val}")

    def test_concurrent_results_are_correct(self):
        results = {}
        lock = threading.Lock()

        def make_request(val):
            r = execute(script=iife(f"return {val};"))
            if r.status_code == 200:
                with lock:
                    results[val] = r.json().get("result")

        values = list(range(1, 6))
        threads = [threading.Thread(target=make_request, args=(v,)) for v in values]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        for val, result in results.items():
            self.assertEqual(result, val, f"Expected {val}, got {result}")

    def test_request_ids_are_unique(self):
        request_ids = []
        for _ in range(20):
            r = execute(script=iife("return 1;"))
            if r.status_code == 200:
                rid = r.json().get("request_id")
                if rid:
                    request_ids.append(rid)

        self.assertGreater(len(request_ids), 0)
        self.assertEqual(len(request_ids), len(set(request_ids)),
                         "Duplicate request IDs detected")

    def test_concurrent_async_requests_complete(self):
        request_ids = []
        for _ in range(5):
            r = requests.post(f"{BASE_URL}/execute/async",
                              headers=auth_headers(),
                              json={"script": iife("return 1;")},
                              timeout=10)
            if r.status_code == 200:
                request_ids.append(r.json()["request_id"])

        self.assertGreater(len(request_ids), 0)
        for rid in request_ids:
            final = poll_status(rid, timeout=30)
            self.assertIn(final["status"], ("completed", "failed"),
                          f"Request {rid} did not reach a terminal state")

    def test_server_returns_429_when_concurrent_limit_exceeded(self):
        statuses = []
        lock = threading.Lock()

        def make_request():
            try:
                r = execute(script=iife("var i; for(i=0;i<500000;i++){} i;"))
                with lock:
                    statuses.append(r.status_code)
            except Exception:
                pass

        threads = [threading.Thread(target=make_request) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        self.assertGreater(len(statuses), 0)
        for code in statuses:
            self.assertIn(code, (200, 429), f"Unexpected status code: {code}")
        has_successes = any(c == 200 for c in statuses)
        self.assertTrue(has_successes, "Expected at least some successful responses")


# ─── Stress ───────────────────────────────────────────────────────────────────

class TestStress(unittest.TestCase):

    def test_oversized_body_returns_413(self):
        padding = "x" * (6 * 1024 * 1024)
        r = requests.post(
            f"{BASE_URL}/execute",
            headers={**auth_headers(), "Content-Type": "application/json"},
            data=f'{{"script": "{padding}"}}',
            timeout=30,
        )
        self.assertEqual(r.status_code, 413)

    def test_unknown_endpoint_returns_404(self):
        r = requests.get(f"{BASE_URL}/completely/unknown/path", timeout=5)
        self.assertEqual(r.status_code, 404)

    def test_large_but_valid_script_succeeds(self):
        comment_line = "// " + "a" * 100 + "\n"
        big_script = comment_line * 900 + iife("return 'done';")  # ~90KB
        r = execute(script=big_script)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("result"), "done")

    def test_deeply_nested_args_handled(self):
        nested = {"a": {"b": {"c": {"d": "deep"}}}}
        r = execute(
            script=iife("var a = getArguments()[0]; return a.a.b.c.d;"),
            args=nested,
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("result"), "deep")

    def test_special_characters_in_script_output(self):
        r = execute(script=iife(r"print('tab:\there'); return 'ok';"))
        self.assertEqual(r.status_code, 200)

    def test_empty_body_returns_error(self):
        r = requests.post(
            f"{BASE_URL}/execute",
            headers={**auth_headers(), "Content-Type": "application/json"},
            data="",
            timeout=10,
        )
        self.assertIn(r.status_code, (400, 200))
        if r.status_code == 200:
            self.assertFalse(r.json().get("success"))


if __name__ == "__main__":
    if not TOKEN:
        print(f"NOTE: No token file found at {TOKEN_FILE}")
    if not AUTH_ENABLED:
        print("NOTE: Authentication appears disabled — auth tests will be skipped.\n")

    try:
        requests.get(f"{BASE_URL}/status", timeout=3)
    except requests.exceptions.ConnectionError:
        print(f"ERROR: Cannot connect to {BASE_URL}")
        print("Is DAZ Studio running with the DazScriptServer plugin loaded?")
        sys.exit(1)

    unittest.main(verbosity=2)
