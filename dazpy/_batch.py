from __future__ import annotations

from ._client import DazClient


class BatchFuture:
    def __init__(self, key: str):
        self._key = key
        self._resolved = False
        self._value = None

    @property
    def value(self) -> object:
        if not self._resolved:
            raise RuntimeError("Batch has not been executed yet")
        return self._value

    def _resolve(self, value: object) -> None:
        self._value = value
        self._resolved = True


class Batch:
    def __init__(self, client: DazClient):
        self._client = client
        self._ops: list[tuple[str, list[str], BatchFuture]] = []
        self._counter = 0

    def add(self, lines: list[str]) -> BatchFuture:
        key = f"_r{self._counter}"
        self._counter += 1
        future = BatchFuture(key)
        self._ops.append((key, lines, future))
        return future

    def _build_script(self) -> str:
        body_lines = []
        return_parts = []
        for key, lines, _ in self._ops:
            body_lines.extend(lines)
            return_parts.append(f'"{key}": {key}')
        return_obj = "{" + ", ".join(return_parts) + "}"
        body_lines.append(f"return {return_obj};")
        body = "\n".join(body_lines)
        return f"(function(){{\n{body}\n}})()"

    def execute(self) -> None:
        if not self._ops:
            return
        script = self._build_script()
        result = self._client.execute(script)
        data = result.value or {}
        for key, _, future in self._ops:
            future._resolve(data.get(key))

    def __enter__(self) -> "Batch":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is None:
            self.execute()
        return False
