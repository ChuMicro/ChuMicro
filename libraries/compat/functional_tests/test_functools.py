"""Device-facing tests for the compat polyfills on real hardware.

Validates that cross-runtime polyfills work correctly on CPython,
MicroPython, and CircuitPython.
"""

from chumicro_compat.functools import partial


def test_partial_basic_call() -> None:
    """partial should freeze positional arguments."""
    def add(left: int, right: int) -> int:
        return left + right

    add_ten = partial(add, 10)
    assert add_ten(5) == 15


def test_partial_keyword_args() -> None:
    """partial should freeze keyword arguments."""
    def greet(greeting: str, name: str = "world") -> str:
        return f"{greeting} {name}"

    hello = partial(greet, greeting="hello")
    assert hello() == "hello world"
    assert hello(name="board") == "hello board"


def test_partial_override_kwargs() -> None:
    """Call-site kwargs should override frozen kwargs."""
    def tag(key: str = "a", value: str = "b") -> str:
        return f"{key}={value}"

    tagged = partial(tag, key="sensor")
    assert tagged() == "sensor=b"
    assert tagged(value="42") == "sensor=42"
    assert tagged(key="pin", value="3") == "pin=3"


def test_partial_callable_attribute() -> None:
    """partial objects should expose the func attribute."""
    def target() -> None:
        pass

    wrapped = partial(target)
    assert wrapped.func is target


def test_partial_args_attribute() -> None:
    """partial objects should expose frozen positional args."""
    def target(left: int, right: int) -> int:
        return left + right

    wrapped = partial(target, 1, 2)
    assert wrapped.args == (1, 2)


def test_partial_not_callable_raises() -> None:
    """partial should reject non-callable first arguments."""
    raised = False
    try:
        partial(42)
    except TypeError:
        raised = True
    assert raised is True
