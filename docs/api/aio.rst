Async Client
============

``dazpy.aio`` mirrors :class:`~dazpy.DazClient`'s full method surface as
``async def`` methods, backed by ``httpx.AsyncClient``. Requires the
optional ``httpx`` dependency: ``pip install dazpy[aio]``.

.. code-block:: python

   from dazpy.aio import AsyncDazClient

   async def main():
       async with AsyncDazClient() as client:
           result = await client.execute("1 + 1;")
           print(result.value)

AsyncDazClient
--------------

.. autoclass:: dazpy.aio.AsyncDazClient
   :members:
   :undoc-members:
   :show-inheritance:

Render helpers
--------------

.. autofunction:: dazpy.aio.render

.. autofunction:: dazpy.aio.render_variants
