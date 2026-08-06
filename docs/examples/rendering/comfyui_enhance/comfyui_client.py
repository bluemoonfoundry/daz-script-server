from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

import requests


class ComfyUIError(Exception):
    pass


class ComfyUIExecutionError(ComfyUIError):
    """A queued prompt reached ComfyUI's terminal 'error' status during
    execution (e.g. a node raised an exception) -- distinct from a
    TimeoutError, which means the prompt never reached a terminal state at
    all within the polling window."""

    def __init__(self, prompt_id: str, node_type: str, message: str):
        self.prompt_id = prompt_id
        self.node_type = node_type
        self.message = message
        super().__init__(f"ComfyUI prompt {prompt_id} failed in {node_type}: {message}")


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
        """Poll history until the prompt completes. Returns the outputs dict.

        Raises ComfyUIExecutionError promptly if a node raises during
        execution (status_str == "error") rather than polling to timeout --
        a failed prompt's "outputs" stays empty forever, so without this
        check every execution error would otherwise look identical to a
        prompt that's merely still running, all the way until `timeout`.
        """
        deadline = time.monotonic() + timeout
        delay = 0.5
        while time.monotonic() < deadline:
            history = self.get_history(prompt_id)
            entry = history.get(prompt_id)
            if entry and entry.get("outputs"):
                return entry["outputs"]
            if entry and entry.get("status", {}).get("status_str") == "error":
                raise ComfyUIExecutionError(prompt_id, *_extract_execution_error(entry))
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


def _extract_execution_error(entry: dict) -> tuple[str, str]:
    """Pull (node_type, exception_message) out of a failed history entry's
    status.messages list. Falls back to generic text if the shape ever
    changes -- this is best-effort diagnostic detail, not load-bearing."""
    for msg_type, payload in entry.get("status", {}).get("messages", []):
        if msg_type == "execution_error":
            return payload.get("node_type", "?"), payload.get("exception_message", "unknown error")
    return "?", "unknown error"
