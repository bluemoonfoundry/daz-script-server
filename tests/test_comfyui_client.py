"""Unit tests for examples/comfyui_enhance/comfyui_client.py.

No live servers required — all HTTP calls are mocked with unittest.mock.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "rendering", "comfyui_enhance"
))

from comfyui_client import ComfyUIClient, ComfyUIError, ComfyUIExecutionError


def _mock_resp(status_code: int = 200, json_data: object = None, content: bytes = b""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = (status_code < 400)
    resp.json.return_value = json_data or {}
    resp.content = content
    resp.text = str(json_data)
    return resp


class TestComfyUIClientUpload(unittest.TestCase):
    def test_upload_returns_ref_with_subfolder(self):
        with patch("requests.post") as mock_post:
            mock_post.return_value = _mock_resp(json_data={"name": "snap.png", "subfolder": "input"})
            client = ComfyUIClient()
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                f.write(b"\x89PNG\r\n")
                path = f.name
            try:
                ref = client.upload_image(path)
            finally:
                os.unlink(path)
        self.assertEqual(ref, "input/snap.png")

    def test_upload_returns_ref_without_subfolder(self):
        with patch("requests.post") as mock_post:
            mock_post.return_value = _mock_resp(json_data={"name": "snap.png", "subfolder": ""})
            client = ComfyUIClient()
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                f.write(b"\x89PNG\r\n")
                path = f.name
            try:
                ref = client.upload_image(path)
            finally:
                os.unlink(path)
        self.assertEqual(ref, "snap.png")

    def test_upload_raises_on_error(self):
        with patch("requests.post") as mock_post:
            mock_post.return_value = _mock_resp(status_code=500)
            client = ComfyUIClient()
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                f.write(b"\x89PNG\r\n")
                path = f.name
            try:
                with self.assertRaises(ComfyUIError):
                    client.upload_image(path)
            finally:
                os.unlink(path)


class TestComfyUIClientQueue(unittest.TestCase):
    def test_queue_prompt_returns_id(self):
        with patch("requests.post") as mock_post:
            mock_post.return_value = _mock_resp(json_data={"prompt_id": "abc-123"})
            client = ComfyUIClient(client_id="test-client")
            pid = client.queue_prompt({"1": {}})
        self.assertEqual(pid, "abc-123")
        payload = mock_post.call_args[1]["json"]
        self.assertEqual(payload["client_id"], "test-client")
        self.assertIn("prompt", payload)

    def test_queue_raises_on_error(self):
        with patch("requests.post") as mock_post:
            mock_post.return_value = _mock_resp(status_code=400)
            client = ComfyUIClient()
            with self.assertRaises(ComfyUIError):
                client.queue_prompt({})


class TestComfyUIClientWait(unittest.TestCase):
    def test_wait_returns_outputs_on_second_poll(self):
        outputs = {"8": {"images": [{"filename": "out.png", "subfolder": "", "type": "output"}]}}
        responses = [
            _mock_resp(json_data={"pid": {}}),
            _mock_resp(json_data={"pid": {"outputs": outputs}}),
        ]
        with patch("requests.get", side_effect=responses), \
             patch("time.sleep"):
            client = ComfyUIClient()
            result = client.wait_for_result("pid", timeout=10.0)
        self.assertEqual(result, outputs)

    def test_wait_raises_timeout(self):
        with patch("requests.get", return_value=_mock_resp(json_data={})), \
             patch("time.sleep"), \
             patch("time.monotonic", side_effect=[0.0, 0.1, 999.0]):
            client = ComfyUIClient()
            with self.assertRaises(TimeoutError):
                client.wait_for_result("pid", timeout=1.0)

    def test_wait_raises_execution_error_promptly_not_timeout(self):
        # A failed prompt's history entry never gets "outputs" -- without
        # status_str=="error" detection this would spin until the timeout
        # instead of failing fast.
        entry = {
            "status": {
                "status_str": "error",
                "completed": False,
                "messages": [
                    ["execution_error", {
                        "node_type": "IPAdapterFaceID",
                        "exception_message": "InsightFace: No face detected.",
                    }],
                ],
            },
        }
        with patch("requests.get", return_value=_mock_resp(json_data={"pid": entry})), \
             patch("time.sleep"):
            client = ComfyUIClient()
            with self.assertRaises(ComfyUIExecutionError) as ctx:
                client.wait_for_result("pid", timeout=10.0)
        self.assertEqual(ctx.exception.node_type, "IPAdapterFaceID")
        self.assertEqual(ctx.exception.message, "InsightFace: No face detected.")

    def test_wait_execution_error_falls_back_when_messages_unrecognized(self):
        entry = {"status": {"status_str": "error", "completed": False, "messages": []}}
        with patch("requests.get", return_value=_mock_resp(json_data={"pid": entry})), \
             patch("time.sleep"):
            client = ComfyUIClient()
            with self.assertRaises(ComfyUIExecutionError) as ctx:
                client.wait_for_result("pid", timeout=10.0)
        self.assertEqual(ctx.exception.node_type, "?")
        self.assertEqual(ctx.exception.message, "unknown error")


class TestComfyUIClientDownload(unittest.TestCase):
    def test_download_returns_bytes(self):
        img_bytes = b"\x89PNG\r\nfakedata"
        with patch("requests.get") as mock_get:
            mock_get.return_value = _mock_resp(content=img_bytes)
            client = ComfyUIClient()
            data = client.download_image("out.png", subfolder="", folder_type="output")
        self.assertEqual(data, img_bytes)
        params = mock_get.call_args[1]["params"]
        self.assertEqual(params["filename"], "out.png")
        self.assertEqual(params["type"], "output")

    def test_download_raises_on_error(self):
        with patch("requests.get", return_value=_mock_resp(status_code=404)):
            client = ComfyUIClient()
            with self.assertRaises(ComfyUIError):
                client.download_image("missing.png")


class TestComfyUIClientSaveResult(unittest.TestCase):
    def test_save_result_writes_file(self):
        img_bytes = b"\x89PNG\r\nfakedata"
        outputs = {"8": {"images": [{"filename": "out.png", "subfolder": "", "type": "output"}]}}

        with patch("requests.get") as mock_get, \
             patch("time.sleep"):
            mock_get.side_effect = [
                _mock_resp(json_data={"pid": {"outputs": outputs}}),
                _mock_resp(content=img_bytes),
            ]
            client = ComfyUIClient()
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                out_path = f.name
            try:
                result = client.save_result("pid", out_path, timeout=10.0)
                self.assertEqual(result, out_path)
                self.assertEqual(open(out_path, "rb").read(), img_bytes)
            finally:
                os.unlink(out_path)

    def test_first_output_image_raises_when_no_images(self):
        client = ComfyUIClient()
        with self.assertRaises(ComfyUIError):
            client._first_output_image({"8": {"images": []}})

    def test_first_output_image_raises_when_empty_outputs(self):
        client = ComfyUIClient()
        with self.assertRaises(ComfyUIError):
            client._first_output_image({})


if __name__ == "__main__":
    unittest.main(verbosity=2)
