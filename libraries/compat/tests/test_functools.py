"""Tests for the functools.partial polyfill.

On CPython, ``chumicro_compat.functools.partial`` re-exports the real
``functools.partial``.  These tests exercise ``_PurePythonPartial``
directly — that is the code that will run on MicroPython and
CircuitPython where the C implementation is absent.
"""

from chumicro_compat.functools import _PurePythonPartial as partial
from chumicro_test_harness import raises


def test_partial_freezes_positional_args() -> None:
    """Frozen positional args should be prepended to call-time args."""
    def add(left: int, right: int) -> int:
        """Return a + b."""
        return left + right

    add_five = partial(add, 5)
    assert add_five(3) == 8


def test_partial_freezes_keyword_args() -> None:
    """Frozen keyword args should be passed to the wrapped function."""
    def greet(name: str, greeting: str = "hello") -> str:
        """Return a greeting string."""
        return f"{greeting} {name}"

    hi = partial(greet, greeting="hi")
    assert hi("world") == "hi world"


def test_partial_call_time_kwargs_override_frozen() -> None:
    """Call-time keyword args should override frozen keyword args."""
    def greet(name: str, greeting: str = "hello") -> str:
        """Return a greeting string."""
        return f"{greeting} {name}"

    hi = partial(greet, greeting="hi")
    assert hi("world", greeting="hey") == "hey world"


def test_partial_combines_positional_and_keyword() -> None:
    """Both frozen positional and keyword args should combine correctly."""
    def tag(text: str, wrapper: str = "*") -> str:
        """Wrap text with a character."""
        return f"{wrapper}{text}{wrapper}"

    bold = partial(tag, wrapper="**")
    assert bold("hello") == "**hello**"


def test_partial_no_frozen_args() -> None:
    """Partial with no frozen args should behave like a plain call."""
    def identity(value: object) -> object:
        """Return value."""
        return value

    wrapped = partial(identity)
    assert wrapped(42) == 42


def test_partial_func_attribute() -> None:
    """The .func attribute should be the original callable."""
    def original() -> None:
        """Placeholder."""

    wrapped = partial(original)
    assert wrapped.func is original


def test_partial_args_attribute() -> None:
    """The .args attribute should be a tuple of frozen positional args."""
    wrapped = partial(int, "42")
    assert wrapped.args == ("42",)


def test_partial_keywords_attribute() -> None:
    """The .keywords attribute should be a dict of frozen keyword args."""
    wrapped = partial(int, base=16)
    assert wrapped.keywords == {"base": 16}


def test_partial_rejects_non_callable() -> None:
    """Wrapping a non-callable should raise TypeError."""
    with raises(TypeError):
        partial(42)


def test_partial_repr() -> None:
    """repr should show the function and frozen args."""
    wrapped = partial(int, "ff", base=16)
    result = repr(wrapped)
    assert "partial(" in result
    assert "int" in result
    assert "'ff'" in result
    assert "base=16" in result


def test_partial_multiple_positional_args() -> None:
    """Multiple frozen positional args should be passed in order."""
    results = []

    def collect(*args: object) -> None:
        """Record all positional args."""
        results.extend(args)

    wrapped = partial(collect, 1, 2)
    wrapped(3, 4)
    assert results == [1, 2, 3, 4]


def test_partial_returns_function_result() -> None:
    """The return value of the wrapped function should be passed through."""
    wrapped = partial(str.upper)
    assert wrapped("hello") == "HELLO"
