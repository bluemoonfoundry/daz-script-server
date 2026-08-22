Batch & Async Execution
=======================

One HTTP request, one DazScript evaluation
-------------------------------------------

A :class:`~dazpy.Batch` combines every queued operation into a single
generated DazScript IIFE and sends it as **one** ``/execute`` request. A
batch of 20 operations is one evaluation on Studio's main thread; two
separate :meth:`~dazpy.Batch.execute` calls are two evaluations, even if
each only holds one operation. This is what batching buys you: fewer
main-thread handoffs, fewer JSON parses, fewer HTTP round-trips per
operation — not parallelism. Studio still runs every operation's generated
JS serially, in submission order, inside that one script; scene mutations
are not parallelized or reordered.

Whole-batch failure, no rollback
---------------------------------

If any operation in the batch throws, the entire ``/execute`` call fails —
:meth:`~dazpy.Batch.execute` raises the same
:class:`~dazpy.exceptions.ScriptError` a single failing call would, and no
partial per-operation results are available. Earlier operations in the same
script that already mutated the scene are **not** rolled back — a batch is
not a transaction. Order operations so that a failure midway through leaves
the scene in a state you can reason about, and keep destructive operations
late in the batch if a partial application would be hard to recover from.

Batch
-----

.. autoclass:: dazpy.Batch
   :members:
   :undoc-members:
   :show-inheritance:

``add()`` vs ``add_operation()``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:meth:`~dazpy.Batch.add` requires the caller's script lines to assign the
result to an internally generated ``_rN`` variable name, which means the
caller has to know or guess that name. :meth:`~dazpy.Batch.add_operation`
avoids this: pass ``body_lines`` (side effects only) and a
``result_expression`` (a JS expression evaluated once immediately after),
and the builder emits the ``var _rN = <result_expression>;`` assignment
itself. Prefer :meth:`~dazpy.Batch.add_operation` for anything generated
programmatically (loops building operations from data); reach for
:meth:`~dazpy.Batch.add` only for a handful of hand-written, one-off
operations where the exact key name doesn't matter.

``add_prelude()``
~~~~~~~~~~~~~~~~~~

:meth:`~dazpy.Batch.add_prelude` registers a shared setup block — e.g. a
node lookup — under a stable key. It is emitted once per unique key no
matter how many times it's called with that key, so several operations that
all need the same lookup (say, several property writes on one node) can
share one lookup instead of repeating it per operation. Pick keys that
collide exactly when — and only when — the generated lines are identical
(e.g. ``f"node:{node_name}"``).

Size limits
~~~~~~~~~~~

``Batch(client, max_operations=..., max_script_length=...)`` bounds a batch
in two ways:

- ``max_operations`` (default 500) — :meth:`~dazpy.Batch.add_operation`
  raises :class:`~dazpy.exceptions.BatchLimitExceededError` once the queue
  would exceed this count.
- ``max_script_length`` (default 900,000 characters, comfortably under the
  server's default 1 MB script cap) — :meth:`~dazpy.Batch.execute` raises
  :class:`~dazpy.exceptions.BatchLimitExceededError` if the *generated*
  script would exceed this length.

Both checks happen client-side before any HTTP call, so an oversized batch
never reaches Studio's main thread.

BatchFuture
-----------

.. autoclass:: dazpy.BatchFuture
   :members:
   :undoc-members:
   :show-inheritance:

execute_long
------------

.. autofunction:: dazpy.execute_long

execute_batch_async
--------------------

:meth:`~dazpy.DazClient.execute_batch_async` gives the one-script guarantee
of :class:`~dazpy.Batch` without holding an HTTP worker thread and a
blocking client call for the duration. Instead of ``add_operation()`` calls
on a ``Batch`` instance, pass a list of
``{"body_lines": [...], "result_expression": "..."}`` dicts directly — the
same shape :meth:`~dazpy.Batch.add_operation` takes, minus the futures. It
builds the identical combined script internally and submits it to
``/execute/async`` as a single queue item, returning a ``request_id``
immediately::

    from dazpy import DazClient

    client = DazClient()
    request_id = client.execute_batch_async([
        {"body_lines": ["var n = Scene.getNumNodes();"], "result_expression": "n"},
        {"body_lines": [], "result_expression": "Scene.getNumCameras()"},
    ])

    data = client.get_request_result(request_id, wait=True, wait_timeout=30)
    print(data["result"]["_r0"], data["result"]["_r1"])

Poll it like any other async request, with
:meth:`~dazpy.DazClient.get_request_status` /
:meth:`~dazpy.DazClient.get_request_result`. The completed result's
``result`` field is a dict keyed ``"_r0"``, ``"_r1"``, ... in submission
order — the same key scheme :class:`~dazpy.Batch` uses internally, just
without a ``BatchFuture`` wrapper resolving each one.

UndoGroup
---------

.. autoclass:: dazpy.UndoGroup
   :members:
   :undoc-members:
   :show-inheritance:
