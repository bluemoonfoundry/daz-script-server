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
import uuid
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from waiting import poll_until  # noqa: E402

BASE_URL = "http://127.0.0.1:18811"
TOKEN_FILE = os.path.expanduser("~/.daz3d/dazscriptserver_token.txt")
# Must match "Max Body Size (MB)" in the DAZ Studio pane (default 5).
MAX_BODY_SIZE_MB = int(os.environ.get("DAZ_MAX_BODY_SIZE_MB", "5"))


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


def studio_qt_major():
    """Major Qt version of the running Studio (4 = Studio 4, 6 = Studio 6),
    from /capabilities; None when unknown (server down or older plugin)."""
    try:
        caps = requests.get(f"{BASE_URL}/capabilities", headers=auth_headers(), timeout=5).json()
        version = str(caps.get("studio", {}).get("qt_version") or caps.get("qt_version") or "")
        return int(version.split(".")[0]) if version else None
    except (requests.exceptions.RequestException, ValueError):
        return None


IS_STUDIO_4 = studio_qt_major() == 4
# ARCHITECTURE.md threading rules 2 and 6: Studio 4 submits async jobs on the
# main thread (its JSON parser needs QScriptEngine) and parses job reports
# only when the job completes, so it can't enqueue or report live progress
# while a script is running.
DS6_ASYNC_ONLY = unittest.skipIf(
    IS_STUDIO_4, "Studio 4 submits async jobs and reads job reports on the main thread")


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

def async_execute(script=None, script_file=None, args=None, report_file=None, headers=None):
    """POST /execute/async and return the raw response."""
    payload = {}
    if script is not None:
        payload["script"] = script
    if script_file is not None:
        payload["scriptFile"] = script_file
    if args is not None:
        payload["args"] = args
    if report_file is not None:
        payload["reportFile"] = report_file
    h = auth_headers() if headers is None else headers
    return requests.post(f"{BASE_URL}/execute/async", headers=h, json=payload, timeout=10)


TERMINAL_STATUSES = (
    "completed", "failed", "cancelled",
    "completed_after_cancel_request", "completed_after_stale",
)


def poll_status(request_id, timeout=15):
    """Poll /requests/{id}/status until terminal or timeout. Returns the last body
    dict (non-terminal on timeout; callers assert on its status)."""
    body, _ = poll_until(
        lambda: requests.get(f"{BASE_URL}/requests/{request_id}/status",
                             headers=auth_headers(), timeout=5).json(),
        lambda b: b.get("status") in TERMINAL_STATUSES,
        timeout=timeout, interval=0.2)
    return body


def get_result(request_id, wait=False, timeout=15):
    """GET /requests/{id}/result, optionally with long-poll."""
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

    @DS6_ASYNC_ONLY
    def test_queued_request_can_be_cancelled_while_main_thread_runs(self):
        blocker = async_execute(script=iife(
            "var start = Date.now(); "
            "while (Date.now() - start < 4000) {} "
            "return 'blocker-complete';"
        ))
        self.assertEqual(blocker.status_code, 200, blocker.text)
        blocker_id = blocker.json()["request_id"]

        submit_started = time.monotonic()
        queued = async_execute(script=iife("return 'must-not-run';"))
        submit_seconds = time.monotonic() - submit_started
        self.assertEqual(queued.status_code, 200, queued.text)
        queued_id = queued.json()["request_id"]

        status = requests.get(
            f"{BASE_URL}/requests/{queued_id}/status",
            headers=auth_headers(), timeout=5,
        ).json()
        cancelled = requests.delete(
            f"{BASE_URL}/requests/{queued_id}",
            headers=auth_headers(), timeout=5,
        )
        final = poll_status(queued_id, timeout=10)
        blocker_result = get_result(blocker_id, wait=True, timeout=10).json()

        self.assertLess(submit_seconds, 2.0)
        self.assertEqual(status.get("status"), "queued")
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(final.get("status"), "cancelled")
        self.assertEqual(blocker_result.get("status"), "completed")

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

    def test_async_inline_after_scriptfile_has_empty_file_identity(self):
        script_path = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".dsa", delete=False, encoding="utf-8"
            ) as script_file:
                script_file.write(iife("return getScriptFileName();"))
                script_path = os.path.abspath(script_file.name)

            file_request = async_execute(
                script=iife("return 'inline-should-not-run';"),
                script_file=script_path,
            )
            self.assertEqual(file_request.status_code, 200, file_request.text)
            file_result = get_result(
                file_request.json()["request_id"], wait=True, timeout=20
            ).json()
            self.assertTrue(file_result.get("success"), file_result.get("error"))
            self.assertEqual(
                os.path.normcase(os.path.normpath(file_result.get("result"))),
                os.path.normcase(os.path.normpath(script_path)),
            )

            inline_request = async_execute(
                script=iife("return getScriptFileName();")
            )
            self.assertEqual(inline_request.status_code, 200, inline_request.text)
            inline_result = get_result(
                inline_request.json()["request_id"], wait=True, timeout=20
            ).json()
            self.assertTrue(inline_result.get("success"), inline_result.get("error"))
            # No file identity leaks from the previous job. Studio 4 reports
            # an inline script's file name as null, Studio 6 as "".
            self.assertIn(inline_result.get("result"), ("", None))
        finally:
            if script_path and os.path.exists(script_path):
                os.unlink(script_path)

    def test_async_report_file_cannot_overwrite_script_file(self):
        script_path = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".dsa", delete=False, encoding="utf-8"
            ) as script_file:
                script_file.write(iife("return 1;"))
                script_path = os.path.abspath(script_file.name)

            r = async_execute(script_file=script_path, report_file=script_path)
            self.assertEqual(r.status_code, 503)
            with open(script_path, encoding="utf-8") as script_file:
                self.assertIn("return 1", script_file.read())
        finally:
            if script_path and os.path.exists(script_path):
                os.unlink(script_path)

    def test_async_report_file_alias_cannot_overwrite_script_file(self):
        script_path = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".dsa", delete=False, encoding="utf-8"
            ) as script_file:
                script_file.write(iife("return 1;"))
                script_path = os.path.abspath(script_file.name)

            alias_path = os.path.join(
                os.path.dirname(script_path), ".", os.path.basename(script_path)
            )
            self.assertNotEqual(alias_path, script_path)
            r = async_execute(script_file=script_path, report_file=alias_path)
            self.assertEqual(r.status_code, 503)
            with open(script_path, encoding="utf-8") as script_file:
                self.assertIn("return 1", script_file.read())
        finally:
            if script_path and os.path.exists(script_path):
                os.unlink(script_path)

    def test_sync_scriptfile_preserves_file_identity(self):
        script_path = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".dsa", delete=False, encoding="utf-8"
            ) as script_file:
                script_file.write(iife("return getScriptFileName();"))
                script_path = os.path.abspath(script_file.name)

            body = execute(script_file=script_path).json()
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

    def test_async_cancel_running_script_reports_real_outcome(self):
        # A busy-loop script long enough to still be RUNNING when we cancel it.
        # A plain script can't be interrupted (killRender() only stops renders),
        # so the cancel must report cancel_requested -- not a "cancelled" that
        # isn't true -- and the script's real result must be kept once it
        # returns (ASSESSMENT #2, GH #34). ~8s on a live DAZ Studio 4 instance.
        script = iife("var x = 0; for (var i = 0; i < 500000000; i++) { x += i; } return 'done';")
        r = async_execute(script=script)
        request_id = r.json()["request_id"]

        # Wait for it to actually start running before cancelling.
        status, _ = poll_until(
            lambda: requests.get(f"{BASE_URL}/requests/{request_id}/status",
                                 headers=auth_headers(), timeout=5).json().get("status"),
            lambda s: s == "running",
            timeout=5)
        self.assertEqual(status, "running", "request never reached running state")

        cancel_r = requests.delete(f"{BASE_URL}/requests/{request_id}",
                                   headers=auth_headers(), timeout=5)
        self.assertEqual(cancel_r.status_code, 200)
        self.assertEqual(cancel_r.json().get("status"), "cancel_requested")
        self.assertIn("cancel_requested_at", cancel_r.json())

        status_r = requests.get(f"{BASE_URL}/requests/{request_id}/status",
                                headers=auth_headers(), timeout=5)
        self.assertEqual(status_r.json().get("status"), "cancel_requested")

        # Cancelling again is idempotent while the script is still running.
        again = requests.delete(f"{BASE_URL}/requests/{request_id}",
                                headers=auth_headers(), timeout=5)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json().get("status"), "cancel_requested")

        body = get_result(request_id, wait=True, timeout=60).json()
        self.assertEqual(body.get("status"), "completed_after_cancel_request")
        self.assertTrue(body.get("success"))
        self.assertEqual(body.get("result"), "done")
        self.assertIn("cancel_requested_at", body)

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

    @DS6_ASYNC_ONLY
    def test_async_job_report_tracks_live_progress_logs_and_outputs(self):
        report_path = ""
        output_path = os.path.join(tempfile.gettempdir(), "dss-observed-output.png")
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
            ) as report:
                # Submission owns/truncates this file; this stale event must
                # never leak into the new job record.
                report.write('{"type":"output","path":"stale.png"}\n')
                report_path = os.path.abspath(report.name)

            script = iife(
                "var cfg = getArguments()[0]; "
                "var events = ''; "
                "function emit(e) { "
                "  events += JSON.stringify(e) + '\\n'; "
                "  var f = new DzFile(cfg.__dssReportFile); "
                "  if (!f.open(DzFile.WriteOnly)) throw 'report open failed'; "
                "  f.write(events); f.close(); "
                "} "
                "emit({type:'progress', value:0.25, current:1, total:4, "
                "      phase:'setup', message:'Scene ready'}); "
                "emit({type:'log', level:'info', message:'started'}); "
                "var start = Date.now(); while (Date.now() - start < 2500) {} "
                "for (var i = 0; i < 105; i++) "
                "  emit({type:'log', level:'debug', message:'line-' + i}); "
                "emit({type:'output', path:cfg.outputPath, kind:'image', label:'plate'}); "
                "emit({type:'progress', value:1, current:4, total:4, "
                "      phase:'done', message:'Complete'}); "
                "return 'reported';"
            )
            r = async_execute(
                script=script,
                args={"outputPath": output_path},
                report_file=report_path,
            )
            self.assertEqual(r.status_code, 200)
            request_id = r.json()["request_id"]

            # A prior cancellation test leaves a non-render script finishing
            # on Daz's main thread, so this job may remain queued for ~8 seconds.
            _, saw_live_progress = poll_until(
                lambda: requests.get(
                    f"{BASE_URL}/requests/{request_id}/status",
                    headers=auth_headers(), timeout=5,
                ).json(),
                lambda s: s.get("status") == "running"
                and (s.get("observation", {}).get("progress") or {}).get("value") == 0.25,
                timeout=20)
            self.assertTrue(saw_live_progress, "structured progress was not visible while running")

            body = get_result(request_id, wait=True, timeout=20).json()
            self.assertEqual(body.get("status"), "completed")
            observation = body["observation"]
            self.assertEqual(observation["progress"]["value"], 1)
            self.assertEqual(observation["progress"]["phase"], "done")
            self.assertEqual(observation["log_total"], 106)
            self.assertEqual(len(observation["log_tail"]), 100)
            self.assertTrue(observation["log_truncated"])
            manifest = observation["output_manifest"]
            self.assertEqual(manifest["count"], 1)
            self.assertEqual(manifest["outputs"][0]["path"], output_path)
            self.assertNotIn("stale.png", str(manifest))

            listed = requests.get(
                f"{BASE_URL}/requests", headers=auth_headers(), timeout=5
            ).json()["requests"]
            summary = next(x for x in listed if x["request_id"] == request_id)
            self.assertEqual(summary["observation_summary"]["output_count"], 1)
            self.assertEqual(summary["observation_summary"]["log_total"], 106)
        finally:
            if report_path and os.path.exists(report_path):
                os.unlink(report_path)


# ─── Response shape ───────────────────────────────────────────────────────────

class TestRenderIraySamples(unittest.TestCase):
    """iray_samples must be applied (and read back) or rejected -- never ignored."""

    def _render(self, payload):
        return requests.post(f"{BASE_URL}/render", headers=auth_headers(),
                             json=payload, timeout=10)

    def _out(self, name):
        return os.path.join(tempfile.gettempdir(), name).replace("\\", "/")

    def test_rejects_non_integer(self):
        for bad in ("100", 1.5, True, None):
            r = self._render({"output_path": self._out("x.png"), "iray_samples": bad})
            self.assertEqual(r.status_code, 400, bad)
            self.assertIn("iray_samples", r.text)

    def test_rejects_negative(self):
        r = self._render({"output_path": self._out("x.png"), "iray_samples": -1})
        self.assertEqual(r.status_code, 400)

    def test_rejects_non_iray_engine(self):
        for engine in ("viewport", "filament"):
            r = self._render({"output_path": self._out("x.png"),
                              "engine": engine, "iray_samples": 50})
            self.assertEqual(r.status_code, 400, engine)

    def test_batch_rejects_bad_variant(self):
        r = requests.post(f"{BASE_URL}/render/batch", headers=auth_headers(), json={
            "base": {"iray_samples": 10},
            "variants": [{"output_path": self._out("a.png")},
                         {"output_path": self._out("b.png"), "iray_samples": "lots"}],
        }, timeout=10)
        self.assertEqual(r.status_code, 400)
        self.assertIn("variants[1]", r.text)

    @unittest.skipUnless(os.environ.get("DSS_LIVE_RENDER"),
                         "set DSS_LIVE_RENDER=1 to run a real Iray render")
    def test_live_iray_render_applies_and_restores_samples(self):
        read_max = iife("return Number(App.getRenderMgr().getActiveRenderer()"
                        ".getPropertyHolder().findProperty('Max Samples').getValue());")
        before = execute(read_max).json()["result"]
        out = self._out("dss_iray_samples_test.png")
        r = self._render({"output_path": out, "engine": "iray",
                          "width": 64, "height": 64, "iray_samples": 7})
        self.assertEqual(r.status_code, 200, r.text)
        body = get_result(r.json()["request_id"], wait=True, timeout=300).json()
        self.assertEqual(body.get("status"), "completed", body)
        readback = body["result"]["iray_samples"]
        self.assertEqual(readback["requested"], 7)
        self.assertEqual(readback["applied"], 7)
        self.assertEqual(readback["previous"], before)
        self.assertTrue(readback["restored"])
        self.assertEqual(execute(read_max).json()["result"], before)


class TestArtifacts(unittest.TestCase):
    """GET /artifacts/{job_id}[/{artifact_id}] (5d6f.7): authenticated, Range
    capable downloads of exactly the files a job declared."""

    PAYLOAD = bytes(range(256)) * 4  # 1024 bytes, every offset distinct mod 256

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="dss-artifacts-")
        cls.image = os.path.join(cls.tmp, "plate.png")
        with open(cls.image, "wb") as f:
            f.write(cls.PAYLOAD)
        # Same directory, never declared: must not be reachable.
        with open(os.path.join(cls.tmp, "secret.txt"), "w") as f:
            f.write("not an artifact")
        cls.report = os.path.join(cls.tmp, "report.jsonl")
        outputs = [
            {"path": cls.image, "kind": "image", "label": "plate"},     # 0
            {"path": os.path.join(cls.tmp, "missing.png")},             # 1
            {"path": cls.tmp},                                          # 2 directory
            {"path": "relative/plate.png"},                             # 3
            {"path": cls.image, "kind": "image", "label": "re-declared"},  # updates 0
        ]
        script = iife(
            "var cfg = getArguments()[0]; "
            "var f = new DzFile(cfg.__dssReportFile); "
            "if (!f.open(DzFile.WriteOnly)) throw 'report open failed'; "
            "f.write(JSON.stringify({type:'manifest', outputs:cfg.outputs}) + '\\n'); "
            "f.close(); return 'declared';"
        )
        r = async_execute(script=script, args={"outputs": outputs}, report_file=cls.report)
        assert r.status_code == 200, r.text
        cls.rid = r.json()["request_id"]
        body = get_result(cls.rid, wait=True, timeout=30).json()
        assert body.get("status") == "completed", body
        cls.manifest = body["observation"]["output_manifest"]

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _get(self, path, headers=None, method="GET"):
        h = auth_headers()
        h.update(headers or {})
        return requests.request(method, f"{BASE_URL}{path}", headers=h, timeout=10)

    def assertError(self, r, status, code):
        self.assertEqual(r.status_code, status, r.text)
        self.assertFalse(r.json()["success"])
        self.assertEqual(r.json()["error_code"], code)

    # ── manifest ────────────────────────────────────────────────────────────

    def test_manifest_entries_carry_ids_and_urls(self):
        outputs = self.manifest["outputs"]
        self.assertEqual(self.manifest["count"], 4)  # re-declaration updated entry 0
        self.assertEqual([o["artifact_id"] for o in outputs], ["0", "1", "2", "3"])
        self.assertEqual(outputs[0]["url"], f"/artifacts/{self.rid}/0")
        self.assertEqual(outputs[0]["label"], "re-declared")

    def test_list_reports_metadata(self):
        r = self._get(f"/artifacts/{self.rid}")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["request_id"], self.rid)
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["count"], 4)
        first, missing, directory, relative = body["artifacts"]
        self.assertTrue(first["available"])
        self.assertEqual(first["size"], len(self.PAYLOAD))
        self.assertEqual(first["content_type"], "image/png")
        self.assertEqual(first["filename"], "plate.png")
        for entry in (missing, directory, relative):
            self.assertFalse(entry["available"], entry)
            self.assertIsNone(entry["size"])

    # ── downloads ───────────────────────────────────────────────────────────

    def test_full_download(self):
        r = self._get(f"/artifacts/{self.rid}/0")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, self.PAYLOAD)
        self.assertEqual(r.headers["Content-Type"], "image/png")
        self.assertEqual(r.headers["Content-Length"], str(len(self.PAYLOAD)))
        self.assertEqual(r.headers["Accept-Ranges"], "bytes")
        self.assertIn('filename="plate.png"', r.headers["Content-Disposition"])

    def test_range_requests(self):
        n = len(self.PAYLOAD)
        cases = [
            ("bytes=10-19", self.PAYLOAD[10:20], f"bytes 10-19/{n}"),
            ("bytes=1000-", self.PAYLOAD[1000:], f"bytes 1000-{n - 1}/{n}"),
            ("bytes=-5", self.PAYLOAD[-5:], f"bytes {n - 5}-{n - 1}/{n}"),
            ("bytes=0-99999", self.PAYLOAD, f"bytes 0-{n - 1}/{n}"),
        ]
        for rng, expected, content_range in cases:
            with self.subTest(range=rng):
                r = self._get(f"/artifacts/{self.rid}/0", {"Range": rng})
                self.assertEqual(r.status_code, 206, r.text)
                self.assertEqual(r.content, expected)
                self.assertEqual(r.headers["Content-Range"], content_range)

    def test_unsatisfiable_range(self):
        r = self._get(f"/artifacts/{self.rid}/0", {"Range": "bytes=5000-6000"})
        self.assertEqual(r.status_code, 416)

    def test_head_returns_metadata_without_body(self):
        r = self._get(f"/artifacts/{self.rid}/0", method="HEAD")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["Content-Length"], str(len(self.PAYLOAD)))
        self.assertEqual(r.content, b"")

    # ── rejection ───────────────────────────────────────────────────────────

    def test_declared_but_unusable_paths_are_gone(self):
        for aid in ("1", "2", "3"):  # missing file, directory, relative path
            with self.subTest(artifact_id=aid):
                self.assertError(self._get(f"/artifacts/{self.rid}/{aid}"),
                                 410, "ARTIFACT_UNAVAILABLE")

    def test_undeclared_artifact(self):
        self.assertError(self._get(f"/artifacts/{self.rid}/99"), 404, "ARTIFACT_NOT_FOUND")

    def test_unknown_job(self):
        for path in ("/artifacts/no-such-job", "/artifacts/no-such-job/0"):
            with self.subTest(path=path):
                self.assertError(self._get(path), 404, "REQUEST_NOT_FOUND")

    def test_path_like_ids_are_rejected(self):
        for aid in ("0.png", "secret.txt", "%2e%2e", "..%5csecret.txt"):
            with self.subTest(artifact_id=aid):
                self.assertError(self._get(f"/artifacts/{self.rid}/{aid}"),
                                 400, "INVALID_FIELD")
        # An encoded slash decodes to a different path, which matches no route.
        for path in (f"/artifacts/{self.rid}/..%2Fsecret.txt",
                     f"/artifacts/{self.rid}/0%2F..%2F..%2Fsecret.txt"):
            with self.subTest(path=path):
                r = self._get(path)
                self.assertIn(r.status_code, (400, 404), r.text)
                self.assertNotIn(b"not an artifact", r.content)

    @unittest.skipUnless(AUTH_ENABLED, "authentication disabled in plugin")
    def test_requires_token(self):
        for path in (f"/artifacts/{self.rid}", f"/artifacts/{self.rid}/0"):
            for headers in ({}, {"X-API-Token": "wrong-token"}):
                with self.subTest(path=path, headers=headers):
                    r = requests.get(f"{BASE_URL}{path}", headers=headers, timeout=5)
                    self.assertEqual(r.status_code, 401)
                    self.assertNotEqual(r.content, self.PAYLOAD)

    @unittest.skipUnless(os.environ.get("DSS_LIVE_RENDER"),
                         "set DSS_LIVE_RENDER=1 to run a real viewport render")
    def test_render_output_is_an_artifact(self):
        out = os.path.join(self.tmp, "render.png").replace("\\", "/")
        r = requests.post(f"{BASE_URL}/render", headers=auth_headers(), json={
            "output_path": out, "engine": "viewport", "width": 64, "height": 64,
        }, timeout=10)
        self.assertEqual(r.status_code, 200, r.text)
        rid = r.json()["request_id"]
        body = get_result(rid, wait=True, timeout=120).json()
        self.assertEqual(body.get("status"), "completed", body)
        entry = body["observation"]["output_manifest"]["outputs"][0]
        self.assertEqual(entry["kind"], "render")
        dl = self._get(entry["url"])
        self.assertEqual(dl.status_code, 200)
        with open(out, "rb") as f:
            self.assertEqual(dl.content, f.read())

    @unittest.skipUnless(os.environ.get("DSS_LIVE_RENDER"),
                         "set DSS_LIVE_RENDER=1 to run a real viewport render")
    @unittest.skipUnless(sys.platform == "win32", "needs an unmapped drive letter")
    def test_render_that_writes_no_file_fails(self):
        # alaz: a render to an unwritable path (unmapped drive) used to report
        # "completed" with file_size_bytes 0. It must fail instead.
        drive = next((c for c in "RQPONMLKJIHGFEDCBA" if not os.path.exists(f"{c}:/")), None)
        if drive is None:
            self.skipTest("no unmapped drive letter")
        out = f"{drive}:/dss_no_such_dir_alaz/x.png"
        r = requests.post(f"{BASE_URL}/render", headers=auth_headers(), json={
            "output_path": out, "engine": "viewport", "width": 64, "height": 64,
        }, timeout=10)
        self.assertEqual(r.status_code, 200, r.text)
        rid = r.json()["request_id"]
        body = get_result(rid, wait=True, timeout=120).json()
        self.assertEqual(body.get("status"), "failed", body)
        self.assertEqual(body.get("error_code"), "SCRIPT_ERROR", body)
        self.assertIn("no file", body.get("error", ""), body)
        self.assertEqual(body["observation"]["output_manifest"]["count"], 0, body)
        # The progress stream keeps its terminal event for late subscribers.
        sse = requests.get(f"{BASE_URL}/render/{rid}/progress", headers=auth_headers(),
                           stream=True, timeout=10)
        terminal = None
        try:
            for line in sse.iter_lines(decode_unicode=True):
                if line in ("event: error", "event: complete"):
                    terminal = line
                    break
        finally:
            sse.close()
        self.assertEqual(terminal, "event: error")


class TestArtifactRoots(unittest.TestCase):
    """Artifact trust boundary (x7ul.33): GET /artifacts serves a declared
    output only when its real path (symlinks resolved) is inside an allowed
    artifact folder, and never anything under ~/.daz3d. Defaults: temp,
    Documents, Pictures, Desktop, Downloads -- so a folder directly under the
    home folder is outside them."""

    @classmethod
    def setUpClass(cls):
        caps = requests.get(f"{BASE_URL}/capabilities", headers=auth_headers(), timeout=10).json()
        security = caps.get("security", {})
        if not security.get("artifact_roots_enabled"):
            raise unittest.SkipTest("artifact folder restriction is disabled on this server")
        cls.roots = security.get("artifact_roots", [])

        cls.inside_dir = tempfile.mkdtemp(prefix="dss-roots-in-")
        cls.outside_dir = tempfile.mkdtemp(prefix=".dss-roots-out-", dir=os.path.expanduser("~"))
        cls.inside = os.path.join(cls.inside_dir, "inside.png")
        cls.outside = os.path.join(cls.outside_dir, "outside.png")
        for p in (cls.inside, cls.outside):
            with open(p, "wb") as f:
                f.write(b"artifact bytes")
        cls.token_file = os.path.expanduser("~/.daz3d/dazscriptserver_token.txt")

        # A symlink inside an allowed folder pointing outside of it. Creating
        # one needs Developer Mode or admin on Windows; skip that case if not.
        cls.link = os.path.join(cls.inside_dir, "link.png")
        try:
            os.symlink(cls.outside, cls.link)
        except (OSError, NotImplementedError):
            cls.link = None

        outputs = [{"path": cls.inside}, {"path": cls.outside}, {"path": cls.token_file}]
        if cls.link:
            outputs.append({"path": cls.link})
        report = os.path.join(cls.inside_dir, "report.jsonl")
        script = iife(
            "var cfg = getArguments()[0]; "
            "var f = new DzFile(cfg.__dssReportFile); "
            "if (!f.open(DzFile.WriteOnly)) throw 'report open failed'; "
            "f.write(JSON.stringify({type:'manifest', outputs:cfg.outputs}) + '\\n'); "
            "f.close(); return 'declared';"
        )
        r = async_execute(script=script, args={"outputs": outputs}, report_file=report)
        assert r.status_code == 200, r.text
        cls.rid = r.json()["request_id"]
        body = get_result(cls.rid, wait=True, timeout=30).json()
        assert body.get("status") == "completed", body

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.inside_dir, ignore_errors=True)
        shutil.rmtree(cls.outside_dir, ignore_errors=True)

    def _get(self, artifact_id):
        return requests.get(f"{BASE_URL}/artifacts/{self.rid}/{artifact_id}",
                            headers=auth_headers(), timeout=10)

    def assertOutsideRoots(self, r):
        self.assertEqual(r.status_code, 403, r.text)
        body = r.json()
        self.assertEqual(body["error_code"], "ARTIFACT_OUTSIDE_ROOTS")
        self.assertFalse(body["retryable"])

    def test_capabilities_list_the_roots(self):
        self.assertTrue(self.roots, "no effective artifact roots reported")

    def test_file_inside_a_root_is_served(self):
        r = self._get(0)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.content, b"artifact bytes")

    def test_file_outside_the_roots_is_refused(self):
        self.assertOutsideRoots(self._get(1))

    def test_token_folder_is_always_refused(self):
        self.assertOutsideRoots(self._get(2))

    def test_symlink_out_of_a_root_is_refused(self):
        if not self.link:
            self.skipTest("cannot create symlinks here (needs Developer Mode/admin on Windows)")
        self.assertOutsideRoots(self._get(3))

    def test_listing_marks_refused_files_unavailable(self):
        r = requests.get(f"{BASE_URL}/artifacts/{self.rid}", headers=auth_headers(), timeout=10)
        self.assertEqual(r.status_code, 200, r.text)
        available = [a["available"] for a in r.json()["artifacts"]]
        self.assertEqual(available[:3], [True, False, False])
        if self.link:
            self.assertFalse(available[3])


class TestArtifactThumbnails(unittest.TestCase):
    """GET /artifacts/{job_id}/{artifact_id}?thumbnail=<px> (5d6f.24): scaled
    previews of image artifacts, decoded on the main thread."""

    @staticmethod
    def _png(width, height, rgba=False):
        import struct, zlib
        channels = 4 if rgba else 3
        row = bytes([0]) + bytes((x * 7) % 256 for x in range(width * channels))
        raw = row * height

        def chunk(tag, data):
            body = tag + data
            return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

        ihdr = struct.pack(">IIBBBBB", width, height, 8, 6 if rgba else 2, 0, 0, 0)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))

    @staticmethod
    def _png_size(data):
        import struct
        assert data[:8] == b"\x89PNG\r\n\x1a\n", data[:16]
        return struct.unpack(">II", data[16:24])

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="dss-thumbs-")
        cls.wide = os.path.join(cls.tmp, "wide.png")       # 300x150 RGB
        cls.alpha = os.path.join(cls.tmp, "alpha.png")     # 40x80 RGBA
        cls.fake = os.path.join(cls.tmp, "fake.png")       # .png, not an image
        cls.text = os.path.join(cls.tmp, "notes.txt")      # no decoder for .txt
        with open(cls.wide, "wb") as f:
            f.write(cls._png(300, 150))
        with open(cls.alpha, "wb") as f:
            f.write(cls._png(40, 80, rgba=True))
        with open(cls.fake, "wb") as f:
            f.write(b"definitely not a png" * 10)
        with open(cls.text, "w") as f:
            f.write("hello")
        outputs = [{"path": p, "kind": "image"} for p in (cls.wide, cls.alpha, cls.fake, cls.text)]
        outputs.append({"path": os.path.join(cls.tmp, "missing.png")})
        script = iife(
            "var cfg = getArguments()[0]; "
            "var f = new DzFile(cfg.__dssReportFile); "
            "if (!f.open(DzFile.WriteOnly)) throw 'report open failed'; "
            "f.write(JSON.stringify({type:'manifest', outputs:cfg.outputs}) + '\\n'); "
            "f.close(); return 'declared';"
        )
        r = async_execute(script=script, args={"outputs": outputs},
                          report_file=os.path.join(cls.tmp, "report.jsonl"))
        assert r.status_code == 200, r.text
        cls.rid = r.json()["request_id"]
        body = get_result(cls.rid, wait=True, timeout=30).json()
        assert body.get("status") == "completed", body

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _thumb(self, aid, query, headers=None):
        h = auth_headers()
        h.update(headers or {})
        return requests.get(f"{BASE_URL}/artifacts/{self.rid}/{aid}?{query}", headers=h, timeout=30)

    def assertError(self, r, status, code):
        self.assertEqual(r.status_code, status, r.text)
        self.assertFalse(r.json()["success"])
        self.assertEqual(r.json()["error_code"], code)

    def test_capabilities_advertise_thumbnails(self):
        caps = requests.get(f"{BASE_URL}/capabilities", headers=auth_headers(), timeout=10).json()
        self.assertTrue(caps["features"]["artifact_thumbnails"])
        self.assertEqual(caps["limits"]["thumbnail_min_px"], 16)
        self.assertEqual(caps["limits"]["thumbnail_max_px"], 1024)
        self.assertIn("png", caps["thumbnail_source_formats"])

    def test_list_reports_thumbnail_supported(self):
        r = requests.get(f"{BASE_URL}/artifacts/{self.rid}", headers=auth_headers(), timeout=10)
        flags = [a["thumbnail_supported"] for a in r.json()["artifacts"]]
        # wide, alpha, fake (extension only; content is checked on request), text, missing
        self.assertEqual(flags, [True, True, True, False, False])

    def test_scales_longest_edge_and_caches(self):
        first = self._thumb(0, "thumbnail=64")
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.headers["Content-Type"], "image/png")
        self.assertEqual(self._png_size(first.content), (64, 32))
        self.assertIn("wide.png.thumb.png", first.headers["Content-Disposition"])
        again = self._thumb(0, "thumbnail=64")
        self.assertEqual(again.headers["X-Thumbnail-Cache"], "hit")
        self.assertEqual(again.content, first.content)

    def test_tall_image_and_never_upscales(self):
        r = self._thumb(1, "thumbnail=20")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._png_size(r.content), (10, 20))
        r = self._thumb(0, "thumbnail=1024")
        self.assertEqual(self._png_size(r.content), (300, 150))

    def test_jpeg_format(self):
        for fmt in ("jpeg", "jpg"):
            with self.subTest(format=fmt):
                r = self._thumb(1, f"thumbnail=32&format={fmt}")
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.headers["Content-Type"], "image/jpeg")
                self.assertEqual(r.content[:2], b"\xff\xd8")

    def test_bad_params(self):
        for query in ("thumbnail=", "thumbnail=8", "thumbnail=2000", "thumbnail=abc",
                      "thumbnail=-64", "thumbnail=64px", "thumbnail=64&format=gif"):
            with self.subTest(query=query):
                self.assertError(self._thumb(0, query), 400, "INVALID_FIELD")

    def test_undecodable_and_unsupported(self):
        self.assertError(self._thumb(2, "thumbnail=64"), 422, "THUMBNAIL_UNSUPPORTED")
        self.assertError(self._thumb(3, "thumbnail=64"), 422, "THUMBNAIL_UNSUPPORTED")
        self.assertError(self._thumb(4, "thumbnail=64"), 410, "ARTIFACT_UNAVAILABLE")
        self.assertError(self._thumb(99, "thumbnail=64"), 404, "ARTIFACT_NOT_FOUND")

    def test_error_bodies_are_not_labelled_as_images(self):
        r = self._thumb(3, "thumbnail=64")
        self.assertTrue(r.headers["Content-Type"].startswith("application/json"))
        self.assertNotIn("Content-Disposition", r.headers)

    def test_requires_auth(self):
        if not auth_headers():
            self.skipTest("auth disabled")
        r = requests.get(f"{BASE_URL}/artifacts/{self.rid}/0?thumbnail=64", timeout=10)
        self.assertEqual(r.status_code, 401)


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


# ─── Capabilities ─────────────────────────────────────────────────────────────

class TestCapabilities(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.resp = requests.get(f"{BASE_URL}/capabilities", headers=auth_headers(), timeout=10)
        cls.doc = cls.resp.json() if cls.resp.status_code == 200 else {}

    def test_returns_200(self):
        self.assertEqual(self.resp.status_code, 200, self.resp.text)

    @unittest.skipUnless(AUTH_ENABLED, "Authentication is disabled in the running plugin")
    def test_requires_auth(self):
        r = requests.get(f"{BASE_URL}/capabilities",
                         headers={"X-API-Token": "invalid-token-xyz"}, timeout=5)
        self.assertEqual(r.status_code, 401)

    def test_top_level_shape(self):
        for key in ("schema_version", "compatibility_hash", "server", "studio", "routes",
                    "plugin_routes", "features", "limits", "rate_limit", "security",
                    "render_engines"):
            self.assertIn(key, self.doc)
        self.assertEqual(self.doc["schema_version"], 1)
        self.assertRegex(self.doc["compatibility_hash"], r"^[0-9a-f]{16}$")

    def test_versions_match_status(self):
        status = requests.get(f"{BASE_URL}/status", timeout=5).json()
        self.assertEqual(self.doc["server"]["version"], status["version"])
        self.assertIn(self.doc["studio"]["sdk_major"], (4, 6))
        self.assertTrue(self.doc["studio"]["version"])

    def test_routes_include_core_endpoints(self):
        routes = {(r["method"], r["path"]) for r in self.doc["routes"]}
        for key in (("POST", "/execute"), ("GET", "/capabilities"),
                    ("GET", "/requests/{id}/status"), ("GET", "/scene/events")):
            self.assertIn(key, routes)
        public = {(r["method"], r["path"]) for r in self.doc["routes"] if not r["auth"]}
        self.assertEqual(public, {("GET", "/status"), ("GET", "/health"), ("GET", "/metrics")})

    def test_limits_are_positive(self):
        for key in ("max_body_size_mb", "max_script_length_kb", "max_concurrent_requests",
                    "max_batch_variants", "max_animation_frames"):
            self.assertGreater(self.doc["limits"][key], 0, key)

    def test_render_engines_read_live(self):
        engines = self.doc["render_engines"]
        self.assertIn(engines["source"], ("live", "snapshot"))
        self.assertIn("viewport", engines["selectable"])
        self.assertTrue(engines["registered"], "DzRenderMgr reported no renderers")
        active = [e for e in engines["registered"] if e["active"]]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["class_name"], engines["active_class"])

    def test_hash_is_stable_across_calls(self):
        again = requests.get(f"{BASE_URL}/capabilities", headers=auth_headers(), timeout=10).json()
        self.assertEqual(again["compatibility_hash"], self.doc["compatibility_hash"])


# ─── Request identity, idempotency and the error envelope (5d6f.8) ────────────

ERROR_ENVELOPE_KEYS = ("success", "error_code", "error", "retryable")


def unique_key(prefix="idem"):
    return f"{prefix}-{uuid.uuid4().hex}"


class TestServerIdentity(unittest.TestCase):

    def test_status_reports_instance_and_revision(self):
        r = requests.get(f"{BASE_URL}/status", timeout=5)
        body = r.json()
        self.assertRegex(body["server_instance_id"], r"^srv-[0-9a-f]{16}$")
        self.assertIsInstance(body["scene_revision"], int)
        self.assertEqual(r.headers.get("X-Server-Instance-Id"), body["server_instance_id"])

    def test_instance_id_is_stable_within_a_run(self):
        a = requests.get(f"{BASE_URL}/status", timeout=5).json()["server_instance_id"]
        b = requests.get(f"{BASE_URL}/health", timeout=5).json()["server_instance_id"]
        caps = requests.get(f"{BASE_URL}/capabilities", headers=auth_headers(), timeout=10).json()
        self.assertEqual(a, b)
        self.assertEqual(caps["server"]["instance_id"], a)
        self.assertTrue(caps["features"]["idempotency_key"])
        self.assertGreater(caps["limits"]["idempotency_ttl_seconds"], 0)

    def test_instance_header_on_error_responses(self):
        r = requests.get(f"{BASE_URL}/requests/does-not-exist/status",
                         headers=auth_headers(), timeout=5)
        self.assertEqual(r.status_code, 404)
        self.assertTrue(r.headers.get("X-Server-Instance-Id", "").startswith("srv-"))

    def test_scene_revision_advances_after_execute(self):
        before = requests.get(f"{BASE_URL}/status", timeout=5).json()["scene_revision"]
        r = execute(script="1 + 1;")
        self.assertEqual(r.status_code, 200)
        self.assertGreater(r.json()["scene_revision"], before)


class TestCorrelationId(unittest.TestCase):

    def test_generated_when_absent(self):
        r = async_execute(script="1;")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body["correlation_id"].startswith("cor-"))
        self.assertEqual(r.headers.get("X-Correlation-Id"), body["correlation_id"])
        self.assertTrue(body["server_instance_id"].startswith("srv-"))

    def test_client_value_echoed_and_stored_on_job(self):
        corr = unique_key("trace")
        r = async_execute(script="1;", headers={**auth_headers(), "X-Correlation-Id": corr})
        self.assertEqual(r.status_code, 200, r.text)
        rid = r.json()["request_id"]
        self.assertEqual(r.json()["correlation_id"], corr)
        status = poll_status(rid)
        self.assertEqual(status["correlation_id"], corr)
        self.assertEqual(status["server_instance_id"], r.json()["server_instance_id"])
        result = get_result(rid).json()
        self.assertEqual(result["correlation_id"], corr)
        listed = requests.get(f"{BASE_URL}/requests", headers=auth_headers(), timeout=5).json()
        match = [x for x in listed["requests"] if x["request_id"] == rid]
        self.assertEqual(match[0]["correlation_id"], corr)

    def test_sync_execute_echoes_correlation_id(self):
        corr = unique_key("trace")
        r = execute(script="1;", headers={**auth_headers(), "X-Correlation-Id": corr})
        self.assertEqual(r.json()["correlation_id"], corr)
        self.assertEqual(r.headers.get("X-Correlation-Id"), corr)

    def test_invalid_correlation_id_rejected(self):
        r = async_execute(script="1;", headers={**auth_headers(), "X-Correlation-Id": "has space"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error_code"], "INVALID_FIELD")


class TestIdempotencyKey(unittest.TestCase):

    def _submit(self, key, script="1;"):
        return async_execute(script=script, headers={**auth_headers(), "Idempotency-Key": key})

    def test_repeat_returns_original_request_id(self):
        key = unique_key()
        first = self._submit(key)
        self.assertEqual(first.status_code, 200, first.text)
        second = self._submit(key)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["request_id"], first.json()["request_id"])
        self.assertTrue(second.json()["idempotent_replay"])
        self.assertEqual(second.headers.get("Idempotent-Replayed"), "true")
        self.assertNotIn("idempotent_replay", first.json())
        # The replay reports the ORIGINAL correlation id, not a new one.
        self.assertEqual(second.json()["correlation_id"], first.json()["correlation_id"])

    def test_different_keys_create_different_jobs(self):
        a = self._submit(unique_key()).json()["request_id"]
        b = self._submit(unique_key()).json()["request_id"]
        self.assertNotEqual(a, b)

    def test_same_key_different_body_is_rejected(self):
        key = unique_key()
        self.assertEqual(self._submit(key, "1;").status_code, 200)
        r = self._submit(key, "2;")
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error_code"], "IDEMPOTENCY_KEY_REUSED")
        self.assertFalse(r.json()["retryable"])

    def test_key_is_scoped_by_route(self):
        key = unique_key()
        reg = requests.post(f"{BASE_URL}/scripts/register", headers=auth_headers(),
                            json={"name": "idem-scope-probe", "script": "1;"}, timeout=5)
        self.assertEqual(reg.status_code, 200)
        a = self._submit(key)
        b = requests.post(f"{BASE_URL}/scripts/idem-scope-probe/async",
                          headers={**auth_headers(), "Idempotency-Key": key}, json={}, timeout=10)
        self.assertEqual(b.status_code, 200, b.text)
        self.assertNotEqual(a.json()["request_id"], b.json()["request_id"])

    def test_failed_submission_is_not_cached(self):
        key = unique_key()
        bad = requests.post(f"{BASE_URL}/execute/async",
                            headers={**auth_headers(), "Idempotency-Key": key},
                            data="{not json", timeout=5)
        self.assertEqual(bad.status_code, 400)
        again = requests.post(f"{BASE_URL}/execute/async",
                              headers={**auth_headers(), "Idempotency-Key": key},
                              data="{not json", timeout=5)
        self.assertEqual(again.status_code, 400)
        self.assertNotIn("idempotent_replay", again.json())

    def test_invalid_key_rejected(self):
        r = self._submit("x" * 300)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error_code"], "INVALID_FIELD")


class TestErrorEnvelope(unittest.TestCase):

    def assertEnvelope(self, body, code):
        for key in ERROR_ENVELOPE_KEYS:
            self.assertIn(key, body)
        self.assertFalse(body["success"])
        self.assertEqual(body["error_code"], code)
        self.assertIsInstance(body["retryable"], bool)

    def test_unknown_request(self):
        for method, path in (("GET", "/requests/nope/status"), ("GET", "/requests/nope/result"),
                             ("DELETE", "/requests/nope")):
            with self.subTest(path=path):
                r = requests.request(method, f"{BASE_URL}{path}", headers=auth_headers(), timeout=5)
                self.assertEqual(r.status_code, 404)
                self.assertEnvelope(r.json(), "REQUEST_NOT_FOUND")

    def test_unknown_route(self):
        r = requests.get(f"{BASE_URL}/definitely/not/a/route", headers=auth_headers(), timeout=5)
        self.assertEqual(r.status_code, 404)
        self.assertEnvelope(r.json(), "ROUTE_NOT_FOUND")

    def test_unknown_registered_script_delete(self):
        r = requests.delete(f"{BASE_URL}/scripts/no-such-script-xyz", headers=auth_headers(), timeout=5)
        self.assertEqual(r.status_code, 404)
        self.assertEnvelope(r.json(), "SCRIPT_NOT_FOUND")

    def test_sync_script_failure(self):
        r = execute(script="throw new Error('boom');")
        self.assertEqual(r.status_code, 200)
        self.assertEnvelope(r.json(), "SCRIPT_ERROR")
        self.assertIn("boom", r.json()["error"])

    def test_async_script_failure(self):
        rid = async_execute(script="throw new Error('boom');").json()["request_id"]
        poll_status(rid)
        body = get_result(rid).json()
        self.assertEqual(body["status"], "failed")
        self.assertEnvelope(body, "SCRIPT_ERROR")


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

    def test_disconnected_queued_requests_release_their_slots(self):
        """daz-script-server-3w3y: sync requests queued behind a busy main
        thread must give up when their client disconnects. They used to block
        forever (BlockingQueuedConnection has no timeout) and pin every
        concurrency slot, so every later request got 429."""
        def active():
            return requests.get(f"{BASE_URL}/health", timeout=3).json()["active_requests"]

        busy_ms = 8000
        blocker_result = {}
        blocker = threading.Thread(target=lambda: blocker_result.update(r=execute(script=iife(
            "var t = Date.now(); while (Date.now() - t < %d) {} return 'done';" % busy_ms))))
        blocker.start()
        # Let the blocker be accepted (and so reach the main thread first).
        _, started = poll_until(active, lambda n: n >= 1, timeout=5.0)
        self.assertTrue(started, "blocker request was never accepted")

        marker_dir = tempfile.mkdtemp(prefix="dss_3w3y_")
        self.addCleanup(lambda: __import__("shutil").rmtree(marker_dir, ignore_errors=True))

        def queued(i):
            # Writes a marker file if it ever runs; it must not.
            path = os.path.join(marker_dir, f"ran_{i}.txt").replace("\\", "/")
            script = iife("var f = new DzFile(%r); f.open(DzFile.WriteOnly); "
                          "f.write('x'); f.close(); return %d;" % (path, i))
            try:
                requests.post(f"{BASE_URL}/execute", headers=auth_headers(),
                              json={"script": script}, timeout=1.5)
            except requests.exceptions.RequestException:
                pass  # expected: the client gives up while the script is queued

        clients = [threading.Thread(target=queued, args=(i,)) for i in range(6)]
        for t in clients:
            t.start()
        for t in clients:
            t.join(timeout=10)

        # Only the blocker should still hold a slot, well before it finishes.
        poll_until(active, lambda n: n <= 1, timeout=3.0, interval=0.1)
        self.assertLessEqual(active(), 1,
                             "abandoned queued requests still hold concurrency slots")
        self.assertTrue(blocker.is_alive(), "blocker finished too early to prove anything")

        blocker.join(timeout=30)
        self.assertEqual(blocker_result["r"].json().get("result"), "done")
        execute(script=iife("return 1;"))  # drain anything still queued
        self.assertEqual(os.listdir(marker_dir), [],
                         "an abandoned queued script ran after its client left")
        self.assertEqual(active(), 0)


# ─── Stress ───────────────────────────────────────────────────────────────────

class TestStress(unittest.TestCase):

    # Every POST route family must reject bodies over the configured limit
    # (daz-script-server-5d6f.1). The body is only slightly over the limit:
    # httplib stops reading once it passes the cap, and a large unread tail
    # makes the server's close send a TCP RST that can hide the 413 from
    # the client.
    OVERSIZE_ROUTES = (
        "/execute",
        "/execute/async",
        "/scripts/register",
        "/scripts/size-limit-probe/execute",
        "/scripts/size-limit-probe/async",
        "/render",
        "/render/batch",
        "/render/animation",
        "/scene/save-copy",
        "/geometry/frames",
    )

    def test_oversized_body_returns_413_on_every_post_route(self):
        limit = MAX_BODY_SIZE_MB * 1024 * 1024
        padding = "x" * (limit + 1024)
        body = f'{{"script": "{padding}"}}'.encode("ascii")
        for path in self.OVERSIZE_ROUTES:
            with self.subTest(path=path):
                r = requests.post(
                    f"{BASE_URL}{path}",
                    headers={**auth_headers(), "Content-Type": "application/json"},
                    data=body,
                    timeout=30,
                )
                self.assertEqual(r.status_code, 413)
                self.assertEqual(r.json().get("error_code"), "BODY_TOO_LARGE")

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
