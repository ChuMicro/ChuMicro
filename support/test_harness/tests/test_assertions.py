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

