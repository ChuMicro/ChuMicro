"""Test helpers for libraries that depend on chumicro-timing.

Provides deterministic fakes that replace the real tick functions,
allowing host-side tests to control time without wall-clock waits.

Ships with the library per Decision 0010 so downstream consumers
import ready-made fakes rather than inventing ad-hoc mocks.

Usage from any library's tests::

    from chumicro_timing.testing import FakeTicks

    fake = FakeTicks()
    heartbeat = Heartbeat(period_ms=100, ticks=fake)
    fake.advance(100)
    assert heartbeat.poll(fake.ticks_ms()) is True
"""


class FakeTicks:
    """Deterministic tick source for host-side tests.

    Replaces the real ``ticks_ms`` / ``ticks_diff`` contract with values
    that only move when ``advance()`` is called explicitly.
    """

    def __init__(self, start_ms: int = 0) -> None:
        """Create a fake tick source starting at *start_ms*."""
        self.current_ms = start_ms

    def advance(self, amount_ms: int) -> None:
        """Move the clock forward by *amount_ms* milliseconds."""
        self.current_ms += amount_ms

    def ticks_ms(self) -> int:
        """Return the current fake tick value."""
        return self.current_ms

    def ticks_diff(self, end: int, start: int) -> int:
        """Return the signed difference *end* − *start*."""
        return end - start

    def ticks_add(self, ticks_val: int, delta: int) -> int:
        """Add *delta* milliseconds to a tick value."""
        return ticks_val + delta
