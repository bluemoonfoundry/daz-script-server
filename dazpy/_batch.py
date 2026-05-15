from __future__ import annotations

from ._client import DazClient


class BatchFuture:
    """Placeholder for a single result within a :class:`Batch` execution.

    Created by :meth:`Batch.add`; the :attr:`value` property blocks until the
    batch has been executed.
    """

    def __init__(self, key: str):
        self._key = key
        self._resolved = False
        self._value = None

    @property
    def value(self) -> object:
        """The result value.

        Raises:
            RuntimeError: If :meth:`Batch.execute` has not been called yet.
        """
        if not self._resolved:
            raise RuntimeError("Batch has not been executed yet")
        return self._value

    def _resolve(self, value: object) -> None:
        self._value = value
        self._resolved = True


class Batch:
    """Collect multiple DazScript operations and execute them in a single HTTP round-trip.

    Usage as a context manager (recommended)::

        with Batch(client) as b:
            pos_future  = b.add(["var pos = Scene.findNode('Figure').getWSPos();",
                                  "var pos = [pos.x, pos.y, pos.z];"])
            name_future = b.add(["var name = Scene.findNode('Figure').getName();"])
        # Both futures resolved after the `with` block
        print(pos_future.value, name_future.value)

    Or manually::

        b = Batch(client)
        f = b.add(["var x = 42;"])
        b.execute()
        print(f.value)

    Args:
        client: The :class:`~dazpy.DazClient` to use.
    """

    def __init__(self, client: DazClient):
        self._client = client
        self._ops: list[tuple[str, list[str], BatchFuture]] = []
        self._counter = 0

    def add(self, lines: list[str]) -> BatchFuture:
        """Queue a list of DazScript lines to be included in the batch.

        The last line in *lines* should assign the desired result to a variable
        named after the key that will be referenced internally.

        Args:
            lines: DazScript source lines (no ``return`` needed).

        Returns:
            A :class:`BatchFuture` that resolves after :meth:`execute`.
        """
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
        """Execute all queued operations in a single HTTP request and resolve all futures."""
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
