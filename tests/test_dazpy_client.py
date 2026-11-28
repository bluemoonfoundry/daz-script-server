"""dazpy unit tests: DazClient transport: requests, errors, artifacts, registered scripts, version checks.

Mock-based; no server or DAZ Studio required.
Shared fakes live in tests/dazpy_fakes.py.
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dazpy._scene import DazScene
from dazpy._client import DazClient
from dazpy import exceptions
from dazpy_fakes import sync_client


class TestDazClientAsyncFileSubmit(unittest.TestCase):
    def test_posts_script_file_to_async_endpoint_and_returns_request_id(self):
        client, _ = sync_client()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"request_id": "execute-file-123", "status": "queued"}
        response.headers = {}
        client._session.post.return_value = response

        request_id = client.execute_file_async_submit(
            "C:/scripts/pose-probe.dsa",
            args={"mode": "probe"},
            report_file="C:/runs/probe/job.jsonl",
        )

        self.assertEqual(request_id, "execute-file-123")
        client._session.post.assert_called_once_with(
            "http://127.0.0.1:18811/execute/async",
            json={
                "scriptFile": "C:/scripts/pose-probe.dsa",
                "args": {"mode": "probe"},
                "reportFile": "C:/runs/probe/job.jsonl",
            },
            headers={},
            timeout=30.0,
        )


class TestDazClientExecuteTimeout(unittest.TestCase):
    """Per-request timeout on execute() (ekkc)."""

    def _client(self):
        client, _ = sync_client()
        response = MagicMock(status_code=200, headers={})
        response.json.return_value = {"success": True, "result": 1, "output": []}
        client._session.post.return_value = response
        return client

    def test_execute_uses_client_timeout_by_default(self):
        client = self._client()
        client.execute("1;")
        self.assertEqual(client._session.post.call_args.kwargs["timeout"], 30.0)

    def test_execute_timeout_overrides_client_timeout(self):
        client = self._client()
        client.execute("1;", timeout=300.0)
        self.assertEqual(client._session.post.call_args.kwargs["timeout"], 300.0)

    def test_timeout_error_reports_the_timeout_that_applied(self):
        import requests
        client = self._client()
        client._session.post.side_effect = requests.exceptions.Timeout("slow")
        with self.assertRaisesRegex(exceptions.TimeoutError, "after 300.0s"):
            client.execute("1;", timeout=300.0)


class TestDazClientRequestIdentity(unittest.TestCase):
    """Idempotency-Key / X-Correlation-Id headers and the error envelope (5d6f.8)."""

    def _client(self, status_code=200, response_json=None):
        client, _ = sync_client()
        response = MagicMock(status_code=status_code, headers={})
        response.json.return_value = response_json or {"request_id": "execute-1"}
        response.text = ""
        client._session.post.return_value = response
        return client

    def test_no_identity_headers_by_default(self):
        client = self._client()
        client.execute_async_submit("1;")
        self.assertEqual(client._session.post.call_args.kwargs["headers"], {})

    def test_submit_methods_send_identity_headers(self):
        calls = [
            ("/execute/async", lambda c, kw: c.execute_async_submit("1;", **kw)),
            ("/execute/async", lambda c, kw: c.execute_file_async_submit("C:/a.dsa", **kw)),
            ("/scripts/s/async", lambda c, kw: c.execute_registered_async_submit("s", **kw)),
            ("/render", lambda c, kw: c.render_submit("C:/o.png", **kw)),
            ("/render/batch", lambda c, kw: c.render_batch_submit([{"output_path": "C:/o.png"}], **kw)),
            ("/render/animation", lambda c, kw: c.render_animation_submit("C:/o.png", 1, 2, **kw)),
        ]
        for path, call in calls:
            with self.subTest(path=path):
                client = self._client()
                call(client, {"idempotency_key": "job-42", "correlation_id": "trace-7"})
                args, kwargs = client._session.post.call_args
                self.assertTrue(args[0].endswith(path))
                self.assertEqual(kwargs["headers"],
                                 {"Idempotency-Key": "job-42", "X-Correlation-Id": "trace-7"})

    def test_error_envelope_retryable_is_exposed(self):
        client = self._client(409, {
            "success": False, "error_code": "IDEMPOTENCY_KEY_IN_FLIGHT",
            "error": "still processing", "retryable": True,
        })
        with self.assertRaises(exceptions.ServerResponseError) as cm:
            client.execute_async_submit("1;", idempotency_key="k")
        self.assertEqual(cm.exception.error_code, "IDEMPOTENCY_KEY_IN_FLIGHT")
        self.assertTrue(cm.exception.retryable)

    def test_error_envelope_retryable_defaults_false(self):
        client = self._client(422, {"success": False, "error_code": "IDEMPOTENCY_KEY_REUSED",
                                    "error": "different body"})
        with self.assertRaises(exceptions.ServerResponseError) as cm:
            client.execute_async_submit("1;", idempotency_key="k")
        self.assertFalse(cm.exception.retryable)


class TestDazClientArtifacts(unittest.TestCase):
    """GET /artifacts/{id}[/{artifact_id}] helpers (5d6f.7)."""

    def _client(self, status_code=200, json_data=None, content=b""):
        client, _ = sync_client()
        response = MagicMock(status_code=status_code, headers={})
        response.json.return_value = json_data or {}
        response.text = json.dumps(json_data or {})
        response.content = content
        response.iter_content.return_value = [content[:3], content[3:]]
        client._session.get.return_value = response
        return client, response

    def test_list_artifacts(self):
        body = {"success": True, "request_id": "rnd-1", "count": 1,
                "artifacts": [{"artifact_id": "0", "available": True, "filename": "a.png"}]}
        client, _ = self._client(json_data=body)
        self.assertEqual(client.list_artifacts("rnd-1"), body)
        self.assertEqual(client._session.get.call_args.args[0],
                         "http://127.0.0.1:18811/artifacts/rnd-1")

    def test_download_returns_bytes_and_closes(self):
        client, resp = self._client(content=b"PNGDATA")
        self.assertEqual(client.download_artifact("rnd-1", 0), b"PNGDATA")
        call = client._session.get.call_args
        self.assertEqual(call.args[0], "http://127.0.0.1:18811/artifacts/rnd-1/0")
        self.assertTrue(call.kwargs["stream"])
        self.assertNotIn("Range", call.kwargs["headers"])
        resp.close.assert_called_once()

    def test_download_range_header(self):
        for byte_range, header in (((0, 99), "bytes=0-99"), ((100, None), "bytes=100-")):
            with self.subTest(byte_range=byte_range):
                client, _ = self._client(status_code=206, content=b"x")
                client.download_artifact("rnd-1", "0", byte_range=byte_range)
                self.assertEqual(client._session.get.call_args.kwargs["headers"]["Range"], header)

    def test_download_rejects_bad_range(self):
        client, _ = self._client()
        for bad in ((-1, 5), (10, 2)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                client.download_artifact("rnd-1", "0", byte_range=bad)
        client._session.get.assert_not_called()

    def test_download_to_file(self):
        import tempfile
        client, _ = self._client(content=b"PNGDATA")
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "out.png")
            self.assertEqual(client.download_artifact("rnd-1", "0", dest), dest)
            with open(dest, "rb") as f:
                self.assertEqual(f.read(), b"PNGDATA")

    def test_undeclared_artifact_raises_typed_error(self):
        client, resp = self._client(status_code=404, json_data={
            "success": False, "error_code": "ARTIFACT_NOT_FOUND",
            "error": "Artifact not found", "retryable": False})
        with self.assertRaises(exceptions.ServerResponseError) as cm:
            client.download_artifact("rnd-1", "7")
        self.assertEqual(cm.exception.error_code, "ARTIFACT_NOT_FOUND")
        self.assertEqual(cm.exception.status_code, 404)
        resp.close.assert_called_once()

    def test_artifact_outside_roots_is_not_an_auth_error(self):
        client, _ = self._client(status_code=403, json_data={
            "success": False, "error_code": "ARTIFACT_OUTSIDE_ROOTS",
            "error": "Artifact file is outside the server's allowed artifact folders",
            "retryable": False})
        with self.assertRaises(exceptions.ServerResponseError) as cm:
            client.download_artifact("rnd-1", "0")
        self.assertNotIsInstance(cm.exception, exceptions.AuthenticationError)
        self.assertEqual(cm.exception.error_code, "ARTIFACT_OUTSIDE_ROOTS")
        self.assertEqual(cm.exception.status_code, 403)

    def test_other_403_is_still_an_auth_error(self):
        client, _ = self._client(status_code=403, json_data={
            "success": False, "error_code": "IP_NOT_WHITELISTED", "error": "IP not allowed",
            "retryable": False})
        with self.assertRaises(exceptions.AuthenticationError):
            client.download_artifact("rnd-1", "0")

    def test_thumbnail_sends_params(self):
        client, _ = self._client(content=b"\x89PNG")
        self.assertEqual(client.get_artifact_thumbnail("rnd-1", 0, 128, format="jpeg"), b"\x89PNG")
        call = client._session.get.call_args
        self.assertEqual(call.args[0], "http://127.0.0.1:18811/artifacts/rnd-1/0")
        self.assertEqual(call.kwargs["params"], {"thumbnail": 128, "format": "jpeg"})

    def test_thumbnail_defaults_and_dest(self):
        import tempfile
        client, _ = self._client(content=b"\x89PNG")
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "t.png")
            self.assertEqual(client.get_artifact_thumbnail("rnd-1", "0", dest=dest), dest)
            with open(dest, "rb") as f:
                self.assertEqual(f.read(), b"\x89PNG")
        self.assertEqual(client._session.get.call_args.kwargs["params"],
                         {"thumbnail": 256, "format": "png"})

    def test_thumbnail_unsupported_is_typed(self):
        client, _ = self._client(status_code=422, json_data={
            "success": False, "error_code": "THUMBNAIL_UNSUPPORTED", "error": "x",
            "retryable": False})
        with self.assertRaises(exceptions.ServerResponseError) as cm:
            client.get_artifact_thumbnail("rnd-1", "0")
        self.assertEqual(cm.exception.error_code, "THUMBNAIL_UNSUPPORTED")
        self.assertEqual(cm.exception.status_code, 422)
        self.assertFalse(cm.exception.retryable)

    def test_thumbnail_busy_raises_studio_busy(self):
        client, resp = self._client(status_code=503, json_data={
            "success": False, "error_code": "STUDIO_BUSY", "error": "rendering",
            "retryable": True})
        resp.headers = {"Retry-After": "2"}
        with self.assertRaises(exceptions.StudioBusyError):
            client.get_artifact_thumbnail("rnd-1", "0")

    def test_download_artifacts_skips_unavailable_and_sanitizes_names(self):
        import tempfile
        client = DazClient(token="")
        manifest = {"artifacts": [
            {"artifact_id": "0", "available": True, "filename": "../../evil.png"},
            {"artifact_id": "1", "available": False, "filename": "gone.png"},
            {"artifact_id": "2", "available": True, "filename": "frame.png"},
        ]}
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(client, "list_artifacts", return_value=manifest), \
                patch.object(client, "download_artifact", side_effect=lambda r, a, d: d) as dl:
            paths = client.download_artifacts("rnd-1", tmp)
        self.assertEqual([os.path.basename(p) for p in paths], ["0_evil.png", "2_frame.png"])
        self.assertTrue(all(os.path.dirname(p) == tmp for p in paths))
        self.assertEqual([c.args[1] for c in dl.call_args_list], ["0", "2"])


class TestDazClientRegisteredScripts(unittest.TestCase):
    def _client(self, response_json):
        client, _ = sync_client()
        response = MagicMock(status_code=200, headers={})
        response.json.return_value = response_json
        client._session.post.return_value = response
        return client

    def test_register_script_owns_registry_payload(self):
        client = self._client({"success": True, "id": "scene-info"})
        result = client.register_script("scene-info", "1;", "Scene info")
        self.assertEqual(result["id"], "scene-info")
        client._session.post.assert_called_once_with(
            "http://127.0.0.1:18811/scripts/register",
            json={"name": "scene-info", "description": "Scene info", "script": "1;"},
            headers={}, timeout=30.0,
        )

    def test_execute_registered_maps_execution_result(self):
        client = self._client({"success": True, "result": 42, "output": [], "request_id": "r1"})
        result = client.execute_registered("scene-info", {"detail": True})
        self.assertEqual(result.value, 42)

    def test_submit_registered_async_owns_report_payload(self):
        client = self._client({"request_id": "script-1", "status": "queued"})
        request_id = client.execute_registered_async_submit(
            "scene-info", {"detail": True}, report_file="C:/run/job.jsonl"
        )
        self.assertEqual(request_id, "script-1")
        self.assertEqual(
            client._session.post.call_args.kwargs["json"],
            {"args": {"detail": True}, "reportFile": "C:/run/job.jsonl"},
        )

    def test_cancel_render_does_not_cancel_script_request(self):
        client = self._client({})
        self.assertFalse(client.cancel_render("script-1"))
        client._session.post.assert_not_called()
        client._session.delete.assert_not_called()


class TestScriptRegistryManagement(unittest.TestCase):
    """GET /scripts and DELETE /scripts/{id} (5d6f.25)."""

    def _client(self, status_code=200, json_data=None):
        client, _ = sync_client()
        response = MagicMock(status_code=status_code, headers={})
        response.json.return_value = json_data or {}
        response.text = json.dumps(json_data or {})
        client._session.get.return_value = response
        client._session.delete.return_value = response
        return client

    def test_list_scripts_returns_script_list(self):
        scripts = [{"name": "scene-info", "description": "d", "registered_at": "2026-11-14T10:00:00"}]
        client = self._client(json_data={"scripts": scripts, "count": 1})
        self.assertEqual(client.list_scripts(), scripts)
        self.assertEqual(client._session.get.call_args.args[0], "http://127.0.0.1:18811/scripts")

    def test_list_scripts_empty_registry(self):
        self.assertEqual(self._client(json_data={"scripts": [], "count": 0}).list_scripts(), [])

    def test_delete_script(self):
        client = self._client(json_data={"success": True, "id": "scene-info"})
        self.assertTrue(client.delete_script("scene-info"))
        self.assertEqual(client._session.delete.call_args.args[0],
                         "http://127.0.0.1:18811/scripts/scene-info")

    def test_delete_unknown_script_raises(self):
        body = {"success": False, "error_code": "SCRIPT_NOT_FOUND", "error": "Unknown script",
                "retryable": False, "detail": "nope"}
        client = self._client(status_code=404, json_data=body)
        with self.assertRaises(exceptions.ServerResponseError) as ctx:
            client.delete_script("nope")
        self.assertEqual(ctx.exception.error_code, "SCRIPT_NOT_FOUND")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_delete_unknown_script_missing_ok(self):
        client = self._client(status_code=404, json_data={"error_code": "SCRIPT_NOT_FOUND"})
        self.assertFalse(client.delete_script("nope", missing_ok=True))

    def test_delete_missing_ok_still_raises_auth_errors(self):
        client = self._client(status_code=401, json_data={"error": "Unauthorized"})
        with self.assertRaises(exceptions.AuthenticationError):
            client.delete_script("nope", missing_ok=True)


class TestErrorMapping(unittest.TestCase):
    def _client_with_mock_session(self, token: str = ""):
        return sync_client(token=token)

    def _client_from_response(self, response_data: dict, status: int = 200):
        import requests as req
        resp = MagicMock(spec=req.Response)
        resp.status_code = status
        resp.json.return_value = response_data
        resp.text = str(response_data)

        client, mock_session = self._client_with_mock_session()
        mock_session.post.return_value = resp
        return client, resp

    def test_auth_error_401(self):
        import requests as req
        resp = MagicMock(spec=req.Response)
        resp.status_code = 401
        resp.json.return_value = {"error": "Unauthorized"}
        resp.text = "Unauthorized"
        client, mock_session = self._client_with_mock_session(token="bad")
        mock_session.post.return_value = resp
        with self.assertRaises(exceptions.AuthenticationError):
            client.execute("1;")

    def test_script_runtime_error(self):
        import requests as req
        resp = MagicMock(spec=req.Response)
        resp.status_code = 200
        resp.json.return_value = {"success": False, "error": "TypeError: undefined is not a function", "request_id": "abc"}
        resp.text = ""
        client, mock_session = self._client_with_mock_session()
        mock_session.post.return_value = resp
        with self.assertRaises(exceptions.ScriptRuntimeError) as ctx:
            client.execute("bad();")
        self.assertEqual(ctx.exception.request_id, "abc")

    def test_script_syntax_error_line_number(self):
        import requests as req
        resp = MagicMock(spec=req.Response)
        resp.status_code = 200
        resp.json.return_value = {"success": False, "error": "SyntaxError at Line 3: unexpected token", "request_id": "def"}
        resp.text = ""
        client, mock_session = self._client_with_mock_session()
        mock_session.post.return_value = resp
        with self.assertRaises(exceptions.ScriptSyntaxError):
            client.execute("{bad syntax")

    def test_studio_busy_error_503(self):
        import requests as req
        resp = MagicMock(spec=req.Response)
        resp.status_code = 503
        resp.json.return_value = {
            "success": False,
            "error_code": "STUDIO_BUSY",
            "error": "DAZ Studio's main thread is busy; please retry shortly",
            "detail": "DAZ Studio is currently loading a scene",
        }
        resp.headers = {"Retry-After": "2"}
        resp.text = ""
        client, mock_session = self._client_with_mock_session()
        mock_session.post.return_value = resp
        with self.assertRaises(exceptions.StudioBusyError) as ctx:
            client.execute("1+1;")
        self.assertIsInstance(ctx.exception, exceptions.DazBusyError)
        self.assertEqual(ctx.exception.retry_after, 2.0)
        self.assertIn("loading a scene", ctx.exception.reason)

    def test_concurrency_limit_error_429(self):
        import requests as req
        resp = MagicMock(spec=req.Response)
        resp.status_code = 429
        resp.json.return_value = {
            "success": False,
            "error_code": "CONCURRENT_LIMIT_EXCEEDED",
            "error": "Server busy: maximum concurrent requests reached, please retry",
        }
        resp.headers = {}
        resp.text = ""
        client, mock_session = self._client_with_mock_session()
        mock_session.post.return_value = resp
        with self.assertRaises(exceptions.ConcurrencyLimitError) as ctx:
            client.execute("1+1;")
        self.assertIsInstance(ctx.exception, exceptions.DazBusyError)
        self.assertNotIsInstance(ctx.exception, exceptions.ScriptRuntimeError)
        self.assertEqual(ctx.exception.retry_after, 2.0)

    def _busy_resp(self):
        import requests as req
        resp = MagicMock(spec=req.Response)
        resp.status_code = 503
        resp.json.return_value = {
            "success": False,
            "error_code": "STUDIO_BUSY",
            "error": "DAZ Studio's main thread is busy; please retry shortly",
            "detail": "DAZ Studio is currently rendering",
        }
        resp.headers = {"Retry-After": "1"}
        resp.text = ""
        return resp

    def _success_resp(self):
        import requests as req
        resp = MagicMock(spec=req.Response)
        resp.status_code = 200
        resp.json.return_value = {"success": True, "result": 2, "output": [], "request_id": "ok1"}
        resp.headers = {}
        resp.text = ""
        return resp

    def test_execute_without_retry_on_busy_raises_immediately(self):
        client, mock_session = self._client_with_mock_session()
        mock_session.post.return_value = self._busy_resp()
        with self.assertRaises(exceptions.StudioBusyError):
            client.execute("1+1;")
        self.assertEqual(mock_session.post.call_count, 1)

    def test_waiting_out_busy_retries_plain_execute_calls_inside_the_block(self):
        client, mock_session = self._client_with_mock_session()
        mock_session.post.side_effect = [self._busy_resp(), self._success_resp()]
        with patch("dazpy._client.time.sleep"):
            with client.waiting_out_busy(60.0):
                self.assertEqual(client.execute("1+1;").value, 2)
        self.assertEqual(mock_session.post.call_count, 2)

    def test_waiting_out_busy_ends_with_the_block(self):
        client, mock_session = self._client_with_mock_session()
        mock_session.post.return_value = self._busy_resp()
        with client.waiting_out_busy(60.0):
            pass
        with self.assertRaises(exceptions.StudioBusyError):
            client.execute("1+1;")
        self.assertEqual(mock_session.post.call_count, 1)

    def test_nested_waiting_out_busy_keeps_the_longer_wait(self):
        client, _ = self._client_with_mock_session()
        with client.waiting_out_busy(600.0):
            with client.waiting_out_busy(120.0):
                self.assertEqual(client.__dict__["_busy_wait"].max_wait, 600.0)
            self.assertEqual(client.__dict__["_busy_wait"].max_wait, 600.0)
        self.assertIsNone(client.__dict__["_busy_wait"].max_wait)

    def test_waiting_out_busy_is_per_thread(self):
        import threading
        client, mock_session = self._client_with_mock_session()
        mock_session.post.return_value = self._busy_resp()
        errors = []

        def other():
            try:
                client.execute("1+1;")
            except exceptions.StudioBusyError as e:
                errors.append(e)

        with client.waiting_out_busy(60.0):
            t = threading.Thread(target=other)
            t.start()
            t.join()
        self.assertEqual(len(errors), 1)  # the other thread did not wait

    def test_connection_error(self):
        import requests as req
        client, mock_session = self._client_with_mock_session()
        mock_session.post.side_effect = req.exceptions.ConnectionError("refused")
        with self.assertRaises(exceptions.ConnectionError):
            client.execute("1;")

    def test_other_transport_error_is_typed(self):
        import requests as req
        client, mock_session = self._client_with_mock_session()
        mock_session.post.side_effect = req.exceptions.ChunkedEncodingError("broken response")
        with self.assertRaises(exceptions.ConnectionError):
            client.execute("1;")

    def test_close_closes_session(self):
        client, mock_session = self._client_with_mock_session()
        client.close()
        mock_session.close.assert_called_once()

    def test_context_manager_closes_session(self):
        client, mock_session = self._client_with_mock_session()
        with client:
            pass
        mock_session.close.assert_called_once()

    def test_diagnostic_includes_script(self):
        err = exceptions.ScriptRuntimeError("failed", script="var x = bad();", request_id="r1")
        diag = err.diagnostic
        self.assertIn("var x = bad();", diag)
        self.assertIn("r1", diag)


class TestExecuteBatchAsync(unittest.TestCase):
    def test_submits_one_request_for_multiple_operations(self):
        client, _ = sync_client()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"request_id": "batch-async-1", "status": "queued"}
        response.headers = {}
        client._session.post.return_value = response

        request_id = client.execute_batch_async([
            {"body_lines": ["var x = 1;"], "result_expression": "x"},
            {"body_lines": ["var y = 2;"], "result_expression": "y"},
        ])

        self.assertEqual(request_id, "batch-async-1")
        client._session.post.assert_called_once()
        call_args = client._session.post.call_args
        self.assertEqual(call_args[0][0], "http://127.0.0.1:18811/execute/async")
        submitted_script = call_args[1]["json"]["script"]
        self.assertIn("var x = 1;", submitted_script)
        self.assertIn("var y = 2;", submitted_script)
        self.assertIn('"_r0"', submitted_script)
        self.assertIn('"_r1"', submitted_script)

    def test_passes_args_through(self):
        client, _ = sync_client()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"request_id": "batch-async-2", "status": "queued"}
        response.headers = {}
        client._session.post.return_value = response

        client.execute_batch_async(
            [{"body_lines": [], "result_expression": "1"}],
            args={"mode": "probe"},
            report_file="C:/runs/probe/batch.jsonl",
        )

        submitted_payload = client._session.post.call_args[1]["json"]
        self.assertEqual(submitted_payload["args"], {"mode": "probe"})
        self.assertEqual(
            submitted_payload["reportFile"], "C:/runs/probe/batch.jsonl"
        )


class TestObservationThreadingContract(unittest.TestCase):
    """Source ratchets for the SDK4/SDK6 report-ingestion boundary.

    The C++ plugin is not built in Python CI, so keep the worker/main-thread
    split mechanically visible to the gate that runs on every PR.
    """

    @classmethod
    def setUpClass(cls):
        source_path = Path(__file__).resolve().parents[1] / "src" / "AsyncRequestManager.cpp"
        cls.source = source_path.read_text(encoding="utf-8")

    def test_worker_endpoints_use_sdk_guarded_report_ingestion(self):
        start = self.source.index(
            "std::pair<int, std::string> AsyncRequestManager::getStatusJson"
        )
        end = self.source.index("// ─── Main-thread API", start)
        worker_api = self.source[start:end]

        # Workers never ingest under the lock (yau7.2.6): status, result and
        # list prefetch the report first.
        self.assertNotIn("ingestReportLocked(", worker_api)
        self.assertEqual(worker_api.count("prefetchReport("), 2)
        self.assertEqual(worker_api.count("prefetchAllReports("), 1)

        helper_start = self.source.index("void AsyncRequestManager::prefetchReport")
        helper_end = self.source.index(
            "void AsyncRequestManager::prefetchAllReports", helper_start
        )
        helper = self.source[helper_start:helper_end]
        # Studio 4 parses JSON with QScriptEngine: no worker-side ingestion.
        self.assertIn("#if DAZ_SDK_MAJOR_VERSION >= 6", helper)
        # The file is read before the lock that applies it is taken.
        read_at = helper.index("readAll()")
        self.assertLess(read_at, helper.rindex("QMutexLocker locker(&m_mutex);"))
        self.assertIn("applyReportBytesLocked(", helper)

    def test_main_thread_completion_ingests_before_terminal_guard(self):
        start = self.source.index("void AsyncRequestManager::markCompleted")
        end = self.source.index("void AsyncRequestManager::markCancelled", start)
        completion = self.source[start:end]

        self.assertLess(
            completion.index("ingestReportLocked(req, true);"),
            completion.index("if (!isActive(req.status)) return;"),
        )

    def test_late_completion_keeps_real_outcome(self):
        # ASSESSMENT #2: a cancel request or stale timeout must not discard
        # the outcome of a script that returns afterwards.
        start = self.source.index("void AsyncRequestManager::markCompleted")
        end = self.source.index("void AsyncRequestManager::markCancelled", start)
        completion = self.source[start:end]
        self.assertIn("REQUEST_COMPLETED_AFTER_CANCEL_REQUEST", completion)
        self.assertIn("REQUEST_COMPLETED_AFTER_STALE", completion)

        cancel = self.source[self.source.index("AsyncRequestManager::cancelImpl("):]
        cancel = cancel[:cancel.index("std::string AsyncRequestManager::listJson")]
        self.assertIn("req.status = REQUEST_CANCEL_REQUESTED;", cancel)
        # Only a still-queued request may be marked CANCELLED synchronously.
        self.assertEqual(cancel.count("req.status      = REQUEST_CANCELLED;"), 1)

    def test_render_reporting_failure_without_cancel_is_failed(self):
        # rzp1: a render script that returns success:false with no client
        # cancel (figure gone, stopped in Studio's UI) used to be "completed"
        # and send SSE "complete". It must be FAILED and send "error".
        start = self.source.index("void AsyncRequestManager::markCompleted")
        end = self.source.index("void AsyncRequestManager::markCancelled", start)
        completion = self.source[start:end]
        cancelled = completion.index("if (req.cancelRequested && renderAborted)")
        aborted = completion.index("} else if (renderAborted) {")
        executed = completion.index("} else if (executed) {")
        self.assertLess(cancelled, aborted)
        self.assertLess(aborted, executed)
        branch = completion[aborted:executed]
        self.assertIn("req.status     = REQUEST_FAILED;", branch)
        self.assertIn("outRenderError = req.error;", branch)

        pane = (Path(__file__).resolve().parents[1] / "src" / "ScriptJobs.cpp").read_text(
            encoding="utf-8")
        start = pane.index("void DzScriptServerPane::processNextAsyncRequest()")
        process = pane[start:pane.index("// Drain the queue", start)]
        self.assertIn(
            "const bool succeeded = executed && !wasCancelled && renderError.isEmpty();", process)
        # Only a succeeded render sends "complete"; everything else "error".
        self.assertLess(process.index("if (succeeded) {"),
                        process.index("notifyCompleted("))
        self.assertIn("renderError.isEmpty() ? errorMsg : renderError", process)
        self.assertIn("m_metrics.recordRequest(succeeded);", process)

    def test_render_progress_stream_ends_cleanly_after_draining(self):
        # 7qv4: the stream ends with sink.done() once the queue is closed and
        # drained; returning false aborted the connection, and ending right
        # after a write could drop a terminal event still queued.
        pane = (Path(__file__).resolve().parents[1] / "src" / "PaneRoutes.cpp").read_text(
            encoding="utf-8")
        start = pane.index("// GET /render/:id/progress")
        provider = pane[start:pane.index("applyPluginRoutes();", start)]
        code = "\n".join(line.split("//")[0] for line in provider.splitlines())
        self.assertIn("sink.done();", code)
        self.assertNotIn("return false", code)
        self.assertNotIn("!queue->isClosed();", provider)


class TestCapabilities(unittest.TestCase):
    """DazClient.capabilities() wraps GET /capabilities."""

    def _client(self, status_code=200, json_data=None):
        import requests as req

        client = DazClient(token="", check_version=False)
        client._session.close()
        session = MagicMock()
        resp = MagicMock(spec=req.Response)
        resp.status_code = status_code
        resp.json.return_value = json_data or {}
        resp.text = str(json_data)
        resp.headers = {}
        session.get.return_value = resp
        client._session = session
        return client, session

    def test_returns_document(self):
        doc = {"schema_version": 1, "render_engines": {"selectable": ["viewport", "iray"]}}
        client, session = self._client(json_data=doc)
        self.assertEqual(client.capabilities(), doc)
        self.assertTrue(session.get.call_args[0][0].endswith("/capabilities"))

    def test_old_server_404_raises(self):
        client, _ = self._client(status_code=404, json_data={"error": "not found"})
        with self.assertRaises(exceptions.ServerResponseError) as cm:
            client.capabilities()
        self.assertEqual(cm.exception.status_code, 404)

    def test_auth_failure_raises(self):
        client, _ = self._client(status_code=401, json_data={"error": "bad token"})
        with self.assertRaises(exceptions.AuthenticationError):
            client.capabilities()


class TestServerVersionCheck(unittest.TestCase):
    """DazClient checks the plugin against MIN_SERVER_VERSION and re-checks when
    the target may have changed."""

    def setUp(self):
        p1 = patch("dazpy._version.client_version", return_value="2.13.0")
        p2 = patch("dazpy._version.MIN_SERVER_VERSION", "2.12")
        p1.start()
        p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)

    @staticmethod
    def _status(json_data):
        import requests as req

        status = MagicMock(spec=req.Response)
        status.status_code = 200
        status.json.return_value = json_data
        status.headers = {}
        return status

    def _client(self, status_json=None, status_exc=None, status_side_effect=None,
                execute_headers=None, **kwargs):
        import requests as req

        client = DazClient(token="", **kwargs)
        client._session.close()
        session = MagicMock()
        execute = MagicMock(spec=req.Response)
        execute.status_code = 200
        execute.json.return_value = {"success": True, "result": 1, "request_id": "r"}
        execute.headers = execute_headers if execute_headers is not None else {}
        if status_side_effect is not None:
            session.get.side_effect = status_side_effect
        elif status_exc is not None:
            session.get.side_effect = status_exc
        else:
            session.get.return_value = self._status(status_json or {})
        session.post.return_value = execute
        client._session = session
        return client, session, execute

    def _run(self, client, times=1):
        import warnings

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            for _ in range(times):
                client.execute("1;")
        return [w for w in caught if issubclass(w.category, exceptions.ServerVersionWarning)]

    def test_older_than_minimum_warns_once(self):
        client, session, _ = self._client({"version": "2.11.0"})
        caught = self._run(client, times=3)
        self.assertEqual(len(caught), 1)
        self.assertIn("2.11.0", str(caught[0].message))
        self.assertIn("2.12 or newer", str(caught[0].message))
        self.assertEqual(session.get.call_count, 1)
        self.assertIs(client.version_check.compatible, False)
        self.assertEqual(client.server_version, "2.11.0")

    def test_minimum_or_newer_does_not_warn(self):
        for server in ("2.12.0", "2.12.7", "2.13.0", "3.0.0"):
            client, _, _ = self._client({"version": server})
            self.assertEqual(self._run(client), [], server)
            self.assertIs(client.version_check.compatible, True, server)

    def test_plugin_one_minor_behind_dazpy_does_not_warn(self):
        client, _, _ = self._client({"version": "2.12.0"})
        self.assertEqual(self._run(client), [])

    def test_check_failures_are_ignored(self):
        import requests as req

        for kwargs in ({"status_json": {}}, {"status_json": {"version": "garbage"}},
                       {"status_exc": req.exceptions.ConnectionError("down")}):
            client, session, _ = self._client(**kwargs)
            self.assertEqual(self._run(client), [], kwargs)
            session.post.assert_called_once()  # real request still sent

    def test_unreachable_first_check_retries(self):
        import requests as req

        client, session, _ = self._client(status_side_effect=[
            req.exceptions.ConnectionError("down"), self._status({"version": "2.11.0"}),
        ])
        caught = self._run(client, times=2)
        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(len(caught), 1)

    def test_transport_failure_triggers_recheck(self):
        import requests as req

        client, session, execute = self._client({"version": "2.12.0"})
        self._run(client)
        self.assertEqual(session.get.call_count, 1)
        session.post.side_effect = req.exceptions.ConnectionError("gone")
        with self.assertRaises(exceptions.ConnectionError):
            client.execute("1;")
        session.post.side_effect = None
        session.post.return_value = execute
        self._run(client)
        self.assertEqual(session.get.call_count, 2)

    def test_instance_change_triggers_recheck(self):
        client, session, execute = self._client(
            {"version": "2.12.0", "server_instance_id": "i1"},
            execute_headers={"X-Server-Instance-Id": "i1"},
        )
        self._run(client, times=2)
        self.assertEqual(session.get.call_count, 1)
        execute.headers = {"X-Server-Instance-Id": "i2"}
        self._run(client)  # response reveals the restart
        self.assertEqual(session.get.call_count, 1)
        self._run(client)  # next request re-checks
        self.assertEqual(session.get.call_count, 2)

    def test_no_instance_id_no_loop(self):
        client, session, _ = self._client({"version": "2.12.0"})
        self._run(client, times=5)
        self.assertEqual(session.get.call_count, 1)

    def test_callback_receives_checks(self):
        seen = []
        client, _, _ = self._client({"version": "2.12.0"}, on_version_check=seen.append)
        self._run(client)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].server_url, "http://127.0.0.1:18811")

    def test_callback_exception_does_not_break_request(self):
        def boom(_check):
            raise RuntimeError("callback failed")

        client, _, _ = self._client({"version": "2.12.0"}, on_version_check=boom)
        self.assertEqual(client.execute("1;").value, 1)

    def test_delete_as_first_request_checks_version(self):
        import warnings

        client, session, _ = self._client({"version": "2.11.0"})
        session.delete.return_value = MagicMock(status_code=200, headers={})
        session.delete.return_value.json.return_value = {"status": "cancelled"}
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            client.cancel_request_detail("abcd1234")
        caught = [w for w in caught if issubclass(w.category, exceptions.ServerVersionWarning)]
        self.assertEqual(len(caught), 1)
        session.get.assert_called_once()

    def test_check_version_false_skips_status_call(self):
        client, session, _ = self._client({"version": "1.0.0"}, check_version=False)
        self.assertEqual(self._run(client), [])
        session.get.assert_not_called()
        self.assertIsNone(client.version_check)


class TestParseVersion(unittest.TestCase):
    def test_parse(self):
        from dazpy._version import parse_version

        self.assertEqual(parse_version("2.10.0"), (2, 10))
        self.assertEqual(parse_version("v2.9.3"), (2, 9))
        self.assertEqual(parse_version("2.10"), (2, 10))
        self.assertIsNone(parse_version("abc"))
        self.assertIsNone(parse_version(None))
        self.assertIsNone(parse_version(2.1))


class TestAuthenticationErrorFields(unittest.TestCase):
    """401/403 keep the server's ErrorResponse fields (review W13)."""

    def _client(self, status_code, json_data=None, text=None):
        client, _ = sync_client()
        response = MagicMock(status_code=status_code, headers={})
        if json_data is None:
            response.json.side_effect = ValueError("not json")
        else:
            response.json.return_value = json_data
        response.text = text if text is not None else json.dumps(json_data)
        client._session.post.return_value = response
        client._session.get.return_value = response
        return client

    def test_401_keeps_error_response_fields(self):
        body = {"success": False, "error_code": "AUTH_INVALID_TOKEN", "error": "Invalid API token",
                "retryable": False, "detail": "token mismatch"}
        client = self._client(401, body)
        with self.assertRaises(exceptions.AuthenticationError) as ctx:
            client.execute("1;")
        err = ctx.exception
        self.assertEqual(err.status_code, 401)
        self.assertEqual(err.error_code, "AUTH_INVALID_TOKEN")
        self.assertEqual(err.detail, "token mismatch")
        self.assertFalse(err.retryable)
        self.assertEqual(str(err), "HTTP 401: Invalid API token")

    def test_403_ip_blocked(self):
        body = {"success": False, "error_code": "IP_NOT_WHITELISTED", "error": "IP not allowed",
                "retryable": False}
        client = self._client(403, body)
        with self.assertRaises(exceptions.AuthenticationError) as ctx:
            client.status()
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.error_code, "IP_NOT_WHITELISTED")
        self.assertEqual(ctx.exception.detail, "")

    def test_non_json_body_falls_back_to_text(self):
        client = self._client(401, None, text="Unauthorized")
        with self.assertRaises(exceptions.AuthenticationError) as ctx:
            client.execute("1;")
        self.assertEqual(ctx.exception.error_code, "")
        self.assertEqual(str(ctx.exception), "HTTP 401: Unauthorized")

    def test_scene_save_copy_keeps_fields(self):
        client = self._client(401, {"error_code": "AUTH_MISSING_TOKEN", "error": "Missing token"})
        with self.assertRaises(exceptions.AuthenticationError) as ctx:
            DazScene(client).save_copy("C:/x.duf")
        self.assertEqual(ctx.exception.error_code, "AUTH_MISSING_TOKEN")

    def test_old_positional_constructor_still_works(self):
        err = exceptions.AuthenticationError("HTTP 401: x")
        self.assertEqual((err.status_code, err.error_code, err.detail, err.retryable), (401, "", "", False))


if __name__ == "__main__":
    unittest.main()
