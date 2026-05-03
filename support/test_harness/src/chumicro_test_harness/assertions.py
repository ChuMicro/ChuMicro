"""Cross-runtime assertion helpers for the lightweight test harness.

These helpers provide pytest-like assertion APIs that work on CPython,
MicroPython, and CircuitPython.  Unit tests that need to run across
all three runtimes should import from here instead of ``pytest``.
"""

import re


class raises:
    """Context manager that asserts a specific exception type is raised.

    Usage::

        with raises(ValueError):
            do_something_invalid()

        with raises(ValueError, match="bad input"):
            raise ValueError("bad input value")

    If the block exits without raising the expected exception, an
    ``AssertionError`` is raised.  If a different exception type is
    raised, it propagates normally.  When ``match`` is given, the
    exception's ``str()`` form must match the regular expression via
    ``re.search`` (same semantics as ``pytest.raises(..., match=...)``).
    """

    def __init__(self, expected, match=None):
        """Accept the expected exception type and optional message regex.

        Args:
            expected: Exception class to catch.
            match: Optional regex pattern; the caught exception's
                ``str()`` form must match it via ``re.search``.
        """
        self.expected = expected
        self.match = match
        self.exception = None

    @property
    def value(self):
        """Pytest-compatible alias for :attr:`exception`.

        Tests converted from ``pytest.raises(...) as ctx`` reach for
        ``ctx.value`` to read the captured exception; expose the same
        name so the conversion is mechanical.
        """
        return self.exception

    def __enter__(self):
        """Enter the assertion context."""
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        """Check that the expected exception was raised (and matches)."""
        if exc_type is None:
            raise AssertionError(
                f"Expected {self.expected.__name__} but no exception was raised"
            )
        if not issubclass(exc_type, self.expected):
            return False  # let unexpected exceptions propagate
        if self.match is not None and re.search(self.match, str(exc_value)) is None:
            raise AssertionError(
                f"Expected {self.expected.__name__} matching {self.match!r}, "
                f"got {exc_type.__name__}({str(exc_value)!r})"
            )
        self.exception = exc_value
        return True  # suppress the expected exception
