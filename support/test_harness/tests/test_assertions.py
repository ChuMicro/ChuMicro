"""Tests for the cross-runtime assertion helpers."""

import pytest
from chumicro_test_harness.assertions import raises


def test_raises_catches_expected_exception():
    """raises() should suppress the expected exception type."""
    with raises(ValueError):
        raise ValueError("bad")


def test_raises_captures_exception_instance():
    """The context manager should expose the caught exception."""
    with raises(ValueError) as ctx:
        raise ValueError("detail")

    assert ctx.exception is not None
    assert str(ctx.exception) == "detail"


def test_raises_fails_when_no_exception():
    """raises() should raise AssertionError when no exception occurs."""
    with pytest.raises(AssertionError, match="Expected ValueError"):
        with raises(ValueError):
            pass  # no exception raised


def test_raises_propagates_unexpected_exception():
    """raises() should not catch exceptions of a different type."""
    with pytest.raises(TypeError):
        with raises(ValueError):
            raise TypeError("wrong type")


def test_raises_catches_subclass():
    """raises() should catch subclasses of the expected type."""
    with raises(Exception):
        raise ValueError("subclass of Exception")


def test_raises_match_accepts_when_message_matches():
    """raises(match=...) suppresses when the regex hits the message."""
    with raises(ValueError, match="bad input"):
        raise ValueError("got bad input value")


def test_raises_match_uses_search_not_fullmatch():
    """``match`` semantics mirror pytest: re.search, not re.fullmatch."""
    with raises(RuntimeError, match="oops"):
        raise RuntimeError("prefix oops suffix")


def test_raises_match_supports_regex_metacharacters():
    """Patterns are real regexes, not literal substrings."""
    with raises(ValueError, match=r"port \d+"):
        raise ValueError("port 8080 is busy")


def test_raises_match_fails_when_message_does_not_match():
    """raises(match=...) must raise AssertionError when the regex misses."""
    with pytest.raises(AssertionError, match="matching 'expected'"):
        with raises(ValueError, match="expected"):
            raise ValueError("something else entirely")


def test_raises_match_does_not_suppress_wrong_type():
    """A type mismatch still propagates even with match= set."""
    with pytest.raises(TypeError):
        with raises(ValueError, match="anything"):
            raise TypeError("wrong type")


def test_raises_value_alias_mirrors_exception():
    """`.value` is a pytest-compatible alias for `.exception`."""
    with raises(ValueError) as ctx:
        raise ValueError("hi")

    assert ctx.value is ctx.exception
    assert isinstance(ctx.value, ValueError)


def test_raises_value_is_none_until_block_exits():
    """`.value` mirrors `.exception`. Both unset until __exit__ runs."""
    ctx = raises(ValueError)
    assert ctx.value is None
    assert ctx.exception is None
