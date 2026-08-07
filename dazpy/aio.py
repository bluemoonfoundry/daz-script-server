"""Async variant of :class:`dazpy.DazClient`, backed by ``httpx``.

Requires the optional ``httpx`` dependency::

    pip install dazpy[aio]

Example::

    from dazpy.aio import AsyncDazClient

    async def main():
        async with AsyncDazClient() as client:
            result = await client.execute("1 + 1;")
            print(result.value)
"""

from ._client_aio import AsyncDazClient

__all__ = ["AsyncDazClient"]
