from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

import requests


class ComfyUIError(Exception):
    pass


class ComfyUIClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8188",
        client_id: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id or str(uuid.uuid4())

    def _get(self, path: str, **kwargs: Any) -> requests.Response:
        resp = requests.get(f"{self.base_url}{path}", **kwargs)
        if not resp.ok:
            raise ComfyUIError(f"GET {path} returned {resp.status_code}: {resp.text}")
        return resp

    def _post(self, path: str, **kwargs: Any) -> requests.Response:
        resp = requests.post(f"{self.base_url}{path}", **kwargs)
        if not resp.ok:
            raise ComfyUIError(f"POST {path} returned {resp.status_code}: {resp.text}")
        return resp

    def get_system_stats(self) -> dict:
        return self._get("/system_stats").json()

    def upload_image(self, path: str) -> str:
        """Upload a local image to ComfyUI. Returns 'subfolder/filename' ref."""
        with open(path, "rb") as f:
            resp = self._post(
                "/upload/image",
                files={"image": (Path(path).name, f, "image/png")},
            )
        data = resp.json()
        subfolder = data.get("subfolder", "")
        name = data.get("name", Path(path).name)
        return f"{subfolder}/{name}" if subfolder else name

    def queue_prompt(self, workflow: dict) -> str:
        """Submit a workflow dict. Returns prompt_id."""
        payload = {"prompt": workflow, "client_id": self.client_id}
        data = self._post("/prompt", json=payload).json()
        return data["prompt_id"]

    def get_history(self, prompt_id: str) -> dict:
        return self._get(f"/history/{prompt_id}").json()

    def wait_for_result(
        self, prompt_id: str, timeout: float = 120.0
    ) -> dict:
        """Poll history until the prompt completes. Returns the outputs dict."""
        deadline = time.monotonic() + timeout
        delay = 0.5
        while time.monotonic() < deadline:
            history = self.get_history(prompt_id)
            entry = history.get(prompt_id)
            if entry and entry.get("outputs"):
                return entry["outputs"]
            time.sleep(delay)
            delay = min(delay * 1.5, 2.0)
        raise TimeoutError(f"ComfyUI prompt {prompt_id} did not complete within {timeout}s")

    def download_image(
        self,
        filename: str,
        subfolder: str = "",
        folder_type: str = "output",
    ) -> bytes:
        params = {"filename": filename, "subfolder": subfolder, "type": folder_type}
        return self._get("/view", params=params).content

    def save_result(
        self,
        prompt_id: str,
        output_path: str,
        timeout: float = 120.0,
    ) -> str:
        """Wait for a prompt to complete, download its first output image, save to disk."""
        outputs = self.wait_for_result(prompt_id, timeout=timeout)
        image_data = self._first_output_image(outputs)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(image_data)
        return output_path

    def _first_output_image(self, outputs: dict) -> bytes:
        for node_outputs in outputs.values():
            images = node_outputs.get("images", [])
            if images:
                img = images[0]
                return self.download_image(
                    img["filename"],
                    subfolder=img.get("subfolder", ""),
                    folder_type=img.get("type", "output"),
                )
        raise ComfyUIError("No output images found in prompt result")
