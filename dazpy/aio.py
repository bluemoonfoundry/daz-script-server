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
from ._render_api_aio import render, render_variants

__all__ = ["AsyncDazClient", "render", "render_variants"]
