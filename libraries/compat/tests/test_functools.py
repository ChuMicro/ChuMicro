"""Tests for the functools.partial polyfill.

On CPython, ``chumicro_compat.functools.partial`` re-exports the real
``functools.partial``.  These tests exercise ``_PurePythonPartial``
directly.  That is the code that runs on MicroPython and CircuitPython,
where the C implementation is absent.
"""

from chumicro_compat.functools import _PurePythonPartial as partial
from chumicro_test_harness import raises


def test_partial_freezes_positional_args() -> None:
    """Frozen positional args should be prepended to call-time args."""
    def add(left: int, right: int) -> int:
        return left + right

    add_five = partial(add, 5)
    assert add_five(3) == 8


def test_partial_freezes_keyword_args() -> None:
    """Frozen keyword args should be passed to the wrapped function."""
    def greet(name: str, greeting: str = "hello") -> str:
        return f"{greeting} {name}"

    hi = partial(greet, greeting="hi")
    assert hi("world") == "hi world"


def test_partial_call_time_kwargs_override_frozen() -> None:
    """Call-time keyword args should override frozen keyword args."""
    def greet(name: str, greeting: str = "hello") -> str:
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
        return value

    wrapped = partial(identity)
    assert wrapped(42) == 42


def test_partial_func_attribute() -> None:
    """The .func attribute should be the original callable."""
    def original() -> None:
        pass

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
        results.extend(args)

    wrapped = partial(collect, 1, 2)
    wrapped(3, 4)
    assert results == [1, 2, 3, 4]


def test_partial_returns_function_result() -> None:
    """The return value of the wrapped function should be passed through."""
    wrapped = partial(str.upper)
    assert wrapped("hello") == "HELLO"


def test_partial_flattens_nested_partial() -> None:
    """A partial wrapping a partial flattens to a single level, matching
    CPython: .func is the innermost callable and .args / .keywords merge."""
    inner = partial(sorted, key=abs)
    outer = partial(inner, reverse=True)
    assert outer.func is sorted
    assert outer.keywords == {"key": abs, "reverse": True}
    assert outer([-3, 1, -2]) == [-3, -2, 1]


def test_partial_flatten_outer_keyword_overrides_inner() -> None:
    inner = partial(dict, a=1)
    outer = partial(inner, a=2)
    assert outer.func is dict
    assert outer.keywords == {"a": 2}
    assert outer() == {"a": 2}


def test_partial_call_without_kwargs_does_not_mutate_frozen_keywords() -> None:
    frozen = partial(dict, a=1)
    frozen()  # no call-time kwargs; must not disturb the frozen dict
    frozen(b=2)
    assert frozen.keywords == {"a": 1}
