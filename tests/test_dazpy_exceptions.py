"""Public exception surface of dazpy and dazpy.aio (yau7.6.1, yau7.6.2)."""

import builtins
import inspect

import pytest

import dazpy
import dazpy.aio
from dazpy import exceptions

PUBLIC_ERRORS = sorted(
    name for name, obj in vars(exceptions).items()
    if inspect.isclass(obj)
    and issubclass(obj, (exceptions.DazError, Warning))
    and obj.__module__ == exceptions.__name__
)


@pytest.mark.parametrize("module", [dazpy, dazpy.aio], ids=["dazpy", "dazpy.aio"])
@pytest.mark.parametrize("name", PUBLIC_ERRORS)
def test_every_exception_is_exported(module, name):
    assert getattr(module, name, None) is getattr(exceptions, name)
    # Names that match a builtin stay out of __all__ so `from dazpy import *`
    # never shadows builtins.TimeoutError / ConnectionError in user code.
    assert (name in module.__all__) is not hasattr(builtins, name)


def test_base_classes_are_covered():
    for name in ("DazError", "AuthenticationError", "ServerResponseError",
                 "StudioBusyError", "ScriptRuntimeError", "ScriptSyntaxError"):
        assert name in PUBLIC_ERRORS


@pytest.mark.parametrize("name", ["TimeoutError", "ConnectionError"])
def test_sdk_error_is_caught_by_builtin_and_daz_error(name):
    sdk_cls = getattr(exceptions, name)
    builtin_cls = getattr(builtins, name)
    assert sdk_cls is not builtin_cls

    with pytest.raises(builtin_cls):
        raise sdk_cls("boom")
    with pytest.raises(exceptions.DazError):
        raise sdk_cls("boom")


@pytest.mark.parametrize("name", ["TimeoutError", "ConnectionError"])
def test_sdk_error_message_is_unchanged(name):
    err = getattr(exceptions, name)("could not reach 127.0.0.1:18811")
    assert str(err) == "could not reach 127.0.0.1:18811"
    assert err.args == ("could not reach 127.0.0.1:18811",)
