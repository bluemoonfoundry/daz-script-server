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
from .exceptions import (
    AmbiguousNodeError,
    AsyncExecutionError,
    AuthenticationError,
    BatchLimitExceededError,
    ConcurrencyLimitError,
    ConnectionError as ConnectionError,  # re-export; not in __all__
    DazBusyError,
    DazError,
    MaterialError,
    NodeNotFoundError,
    PropertyNotFoundError,
    RecipeNotAppliedError,
    RecipeValidationError,
    RenderError,
    SceneCheckError,
    ScriptError,
    ScriptRuntimeError,
    ScriptSyntaxError,
    ServerResponseError,
    ServerVersionWarning,
    StudioBusyError,
    TimeoutError as TimeoutError,  # re-export; not in __all__
)

# Exceptions are re-exported so async code needs one import; see dazpy/__init__.py
# for why ConnectionError and TimeoutError are not in __all__.
__all__ = ["AsyncDazClient", "render", "render_variants",
           "AmbiguousNodeError",
           "AsyncExecutionError",
           "AuthenticationError",
           "BatchLimitExceededError",
           "ConcurrencyLimitError",
           "DazBusyError",
           "DazError",
           "MaterialError",
           "NodeNotFoundError",
           "PropertyNotFoundError",
           "RecipeNotAppliedError",
           "RecipeValidationError",
           "RenderError",
           "SceneCheckError",
           "ScriptError",
           "ScriptRuntimeError",
           "ScriptSyntaxError",
           "ServerResponseError",
           "ServerVersionWarning",
           "StudioBusyError",
           ]
