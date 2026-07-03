"""Cross-runtime tests for the harness `raises` context manager.

Uses `raises` to assert against itself — the outer block catches the
AssertionError or wrong-type exception the inner block would have
raised. Self-circular but self-consistent: if `raises` is broken,
both layers misbehave in detectable ways. Keeps the harness's tests
free of pytest so this file runs on CPython + MP / CP unix-port +
real silicon, the same way every networking library's tests do.
"""

from chumicro_test_harness.assertions import raises
from chumicro_test_harness.skip import _SkipException, skip


def test_raises_catches_expected_exception():
    """`raises(ValueError)` suppresses a ValueError raised inside the block."""
    with raises(ValueError):
        raise ValueError("bad")


def test_raises_captures_exception_instance():
    """`raises` exposes the caught exception via `.exception`."""
    with raises(ValueError) as ctx:
        raise ValueError("detail")

    assert ctx.exception is not None
    assert str(ctx.exception) == "detail"


def test_raises_fails_when_no_exception():
    """When the block exits without raising, `raises` raises AssertionError."""
    with raises(AssertionError, match="Expected ValueError"):
        with raises(ValueError):
            pass


def test_raises_propagates_unexpected_exception():
    """A different exception type passes through `raises` to the caller."""
    with raises(TypeError):
        with raises(ValueError):
            raise TypeError("wrong type")


def test_raises_catches_subclass():
    """`raises(Exception)` catches every subclass of Exception."""
    with raises(Exception):
        raise ValueError("subclass of Exception")


def test_raises_match_accepts_when_message_matches():
    """`raises(match=...)` suppresses when the regex hits the exception message."""
    with raises(ValueError, match="bad input"):
        raise ValueError("got bad input value")


def test_raises_match_uses_search_not_fullmatch():
    """`match` runs `re.search`, so a pattern hits anywhere in the message."""
    with raises(RuntimeError, match="oops"):
        raise RuntimeError("prefix oops suffix")


def test_raises_match_supports_regex_metacharacters():
    """`match` patterns are real regexes, not literal substrings."""
    with raises(ValueError, match=r"port \d+"):
        raise ValueError("port 8080 is busy")


def test_raises_match_fails_when_message_does_not_match():
    """When the type matches but `match` misses, `raises` raises AssertionError."""
    with raises(AssertionError, match="matching 'expected'"):
        with raises(ValueError, match="expected"):
            raise ValueError("something else entirely")


def test_raises_match_does_not_suppress_wrong_type():
    """A type mismatch propagates even when `match=` is set."""
    with raises(TypeError):
        with raises(ValueError, match="anything"):
            raise TypeError("wrong type")


def test_raises_value_alias_mirrors_exception():
    """`.value` is a pytest-compatible alias for `.exception`."""
    with raises(ValueError) as ctx:
        raise ValueError("hi")

    assert ctx.value is ctx.exception
    assert isinstance(ctx.value, ValueError)


def test_raises_value_is_none_until_block_exits():
    """`.value` and `.exception` are both None until `__exit__` runs."""
    ctx = raises(ValueError)
    assert ctx.value is None
    assert ctx.exception is None


def test_raises_does_not_suppress_skip():
    """`raises(Exception)` lets a `skip()` propagate instead of swallowing it.

    `skip()` raises a BaseException-derived sentinel (pytest's `Skipped`
    on the host, `_SkipException` on device), not an `Exception` subclass.
    An over-broad `raises(Exception)` wrapping `skip()` therefore does not
    treat the skip as the expected exception; it propagates, matching
    pytest semantics on both host and device.
    """
    propagated = False
    try:
        with raises(Exception):
            skip("skip must propagate through raises(Exception)")
    except _SkipException:
        propagated = True
    assert propagated
