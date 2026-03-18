"""
Integration tests for DazScriptServer plugin.

Requires the plugin to be running in DAZ Studio at the default address.
Run with: python tests.py

Dependencies: requests  (pip install requests)

Notes:
  - DazScript does not allow top-level `return` statements. Scripts that
    produce return values must wrap their logic in an IIFE:
      (function() { return 42; })()
  - Auth tests are skipped when authentication is disabled in the plugin.
"""

import os
import sys
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
