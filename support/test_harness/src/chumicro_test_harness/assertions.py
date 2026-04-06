"""Cross-runtime assertion helpers for the lightweight test harness.

These helpers provide pytest-like assertion APIs that work on CPython,
MicroPython, and CircuitPython.  Unit tests that need to run across
all three runtimes should import from here instead of ``pytest``.
"""


class raises:
    """Context manager that asserts a specific exception type is raised.

    Usage::

        with raises(ValueError):
            do_something_invalid()

    If the block exits without raising the expected exception, an
    ``AssertionError`` is raised.  If a different exception type is
    raised, it propagates normally.
    """

    def __init__(self, expected):
        """Accept the expected exception type."""
        self.expected = expected
        self.exception = None

    def __enter__(self):
        """Enter the assertion context."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Check that the expected exception was raised."""
        if exc_type is None:
            raise AssertionError(
                f"Expected {self.expected.__name__} but no exception was raised"
            )
        if issubclass(exc_type, self.expected):
            self.exception = exc_val
            return True  # suppress the expected exception
        return False  # let unexpected exceptions propagate
