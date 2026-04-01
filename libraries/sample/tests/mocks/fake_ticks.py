"""Simple fake tick source for heartbeat tests."""

from __future__ import annotations


class FakeTicks:
    """Provide deterministic tick values for host-side tests."""

    def __init__(self, start_ms: int = 0) -> None:
        """Create a fake tick source starting at the provided millisecond value."""
        self.current_ms = start_ms

    def advance(self, amount_ms: int) -> None:
        """Advance the current tick value by a fixed number of milliseconds."""
        self.current_ms += amount_ms

    def ticks_ms(self) -> int:
        """Return the current fake tick value."""
        return self.current_ms

    def ticks_diff(self, end: int, start: int) -> int:
        """Return the difference between two fake tick values."""
        return end - start

