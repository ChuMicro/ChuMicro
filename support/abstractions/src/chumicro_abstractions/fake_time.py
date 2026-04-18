"""Deterministic seconds-domain time fake for host-side tests.

``FakeTime`` replaces Python's ``time`` module in production code
that accepts a ``time`` dependency via constructor injection.  It
bundles ``monotonic()`` and ``sleep()`` into a single object so
tests never touch wall-clock time.

Design decisions:

- ``monotonic()`` is **stable** — repeated calls return the same
  value until the clock is explicitly advanced.
- ``sleep(duration)`` auto-advances the clock by *duration*, so
  production code that sleeps moves the fake clock forward
  without any real wait.
- ``advance(seconds)`` moves the clock forward explicitly, for
  scenarios where the production code does not sleep but the test
  needs to simulate elapsed time (e.g., timeout expiry).

This mirrors the semantics of Kotlin's ``TestCoroutineScheduler``:
time only moves when the test (or a sleep call) says it does.
"""


class FakeTime:
    """Deterministic seconds-domain time source for host-side tests.

    Bundles ``monotonic()`` and ``sleep()`` into a single injectable
    object.  The clock is stable — ``monotonic()`` returns the same
    value until ``advance()`` or ``sleep()`` is called.

    Example::

        fake = FakeTime()
        assert fake.monotonic() == 0.0

        fake.sleep(1.5)
        assert fake.monotonic() == 1.5

        fake.advance(0.5)
        assert fake.monotonic() == 2.0
    """

    __slots__ = ("_current",)

    def __init__(self, start: float = 0.0) -> None:
        """Create a fake time source starting at *start* seconds.

        Args:
            start: Initial monotonic value in seconds.
        """
        self._current = start

    def monotonic(self) -> float:
        """Return the current fake time in seconds.

        The value is stable — calling ``monotonic()`` repeatedly
        returns the same value until ``advance()`` or ``sleep()``
        is called.
        """
        return self._current

    def sleep(self, duration: float) -> None:
        """Advance the clock by *duration* seconds (no wall-clock wait).

        Args:
            duration: Seconds to advance.
        """
        self._current += duration

    def advance(self, seconds: float) -> None:
        """Move the clock forward by *seconds*.

        Use this when the production code does not sleep but the
        test needs to simulate elapsed time — for example, pushing
        past a timeout deadline.

        Args:
            seconds: Seconds to advance.
        """
        self._current += seconds
