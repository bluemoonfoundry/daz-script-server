from __future__ import annotations

from ._client import DazClient
from .exceptions import BatchLimitExceededError

DEFAULT_MAX_OPERATIONS = 500
DEFAULT_MAX_SCRIPT_LENGTH = 900_000  # stays under the server's default 1MB script cap


class BatchFuture:
    """Placeholder for a single result within a :class:`Batch` execution.

    Created by :meth:`Batch.add` or :meth:`Batch.add_operation`; the
    :attr:`value` property blocks until the batch has been executed.
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

    High-level helpers that generate operations programmatically should use
    :meth:`add_operation` instead of :meth:`add` — it does not require the
    caller to know the internally generated result-variable name, and
    :meth:`add_prelude` lets multiple operations share one setup block (e.g.
    a node lookup) emitted only once.

    Args:
        client: The :class:`~dazpy.DazClient` to use.
        max_operations: Maximum number of queued operations before
            :meth:`add_operation` raises :class:`~dazpy.exceptions.BatchLimitExceededError`.
        max_script_length: Maximum generated script length (characters)
            before :meth:`execute` raises :class:`~dazpy.exceptions.BatchLimitExceededError`.
    """

    def __init__(
        self,
        client: DazClient,
        max_operations: int = DEFAULT_MAX_OPERATIONS,
        max_script_length: int = DEFAULT_MAX_SCRIPT_LENGTH,
    ):
        self._client = client
        self._ops: list[tuple[str, list[str], BatchFuture]] = []
        self._preludes: dict[str, list[str]] = {}
        self._prelude_order: list[str] = []
        self._counter = 0
        self._max_operations = max_operations
        self._max_script_length = max_script_length

    def add(self, lines: list[str]) -> BatchFuture:
        """Queue a list of DazScript lines to be included in the batch.

        The last line in *lines* should assign the desired result to a
        variable named after the internally generated key (``_r0``, ``_r1``,
        ... in call order) — inspect a prior :meth:`execute` call's generated
        script if the exact naming matters, or prefer :meth:`add_operation`,
        which does not require guessing the key name.

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

    def add_prelude(self, prelude_key: str, lines: list[str]) -> None:
        """Register a shared setup block, emitted once per unique *prelude_key*.

        Call this before :meth:`add_operation` calls whose bodies depend on
        the prelude's bound variable(s) (e.g. a node lookup bound to
        ``_node_Fig``). Repeated calls with the same *prelude_key* are no-ops
        after the first — use this instead of re-emitting an identical lookup
        once per operation.

        Args:
            prelude_key: Stable identifier for this setup block (e.g.
                ``"node:Fig"``). Callers must pick keys that collide exactly
                when — and only when — the generated lines are identical.
            lines: DazScript source lines for the shared setup.
        """
        if prelude_key not in self._preludes:
            self._preludes[prelude_key] = list(lines)
            self._prelude_order.append(prelude_key)

    def add_operation(self, body_lines: list[str], result_expression: str) -> BatchFuture:
        """Queue an operation whose result the builder assigns internally.

        Unlike :meth:`add`, the caller does not need to know the generated
        key name — pass the JS expression that yields the result
        (*result_expression*, e.g. a variable set inside *body_lines*, or a
        literal expression), and the builder emits
        ``var _rN = <result_expression>;`` itself.

        Args:
            body_lines: DazScript source lines with no trailing result
                assignment (side effects only, e.g. property writes).
            result_expression: A JS expression evaluated once, immediately
                after *body_lines* run, and used as this operation's result.
                Mutation-only operations should pass ``"null"``.

        Returns:
            A :class:`BatchFuture` that resolves after :meth:`execute`.

        Raises:
            BatchLimitExceededError: If this call would exceed the batch's
                configured ``max_operations``.
        """
        if len(self._ops) >= self._max_operations:
            raise BatchLimitExceededError(
                f"Batch already has {len(self._ops)} operations "
                f"(max_operations={self._max_operations})"
            )
        key = f"_r{self._counter}"
        self._counter += 1
        future = BatchFuture(key)
        lines = list(body_lines) + [f"var {key} = {result_expression};"]
        self._ops.append((key, lines, future))
        return future

    def _build_script(self) -> str:
        body_lines = []
        for prelude_key in self._prelude_order:
            body_lines.extend(self._preludes[prelude_key])
        return_parts = []
        for key, lines, _ in self._ops:
            body_lines.extend(lines)
            return_parts.append(f'"{key}": {key}')
        return_obj = "{" + ", ".join(return_parts) + "}"
        body_lines.append(f"return {return_obj};")
        body = "\n".join(body_lines)
        return f"(function(){{\n{body}\n}})()"

    def execute(self) -> None:
        """Execute all queued operations in a single HTTP request and resolve all futures.

        Raises:
            BatchLimitExceededError: If the generated script exceeds
                ``max_script_length``. Raised before any HTTP call.
        """
        if not self._ops:
            return
        script = self._build_script()
        if len(script) > self._max_script_length:
            raise BatchLimitExceededError(
                f"Generated batch script is {len(script)} characters "
                f"(max_script_length={self._max_script_length})"
            )
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
