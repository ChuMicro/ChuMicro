"""Tests for FakeTime — deterministic seconds-domain time source."""

from __future__ import annotations

from chumicro_testing import FakeTime


class TestFakeTimeMonotonic:
    """Tests for FakeTime.monotonic."""

    def test_starts_at_zero_by_default(self) -> None:
        """Default start value should be 0.0."""
        fake = FakeTime()
        assert fake.monotonic() == 0.0

    def test_starts_at_custom_value(self) -> None:
        """Custom start value should be returned by monotonic()."""
        fake = FakeTime(start=42.5)
        assert fake.monotonic() == 42.5

    def test_stable_without_advance(self) -> None:
        """Repeated calls without advance should return the same value."""
        fake = FakeTime()
        assert fake.monotonic() == fake.monotonic()


class TestFakeTimeSleep:
    """Tests for FakeTime.sleep."""

    def test_sleep_advances_clock(self) -> None:
        """sleep() should advance the clock by the given duration."""
        fake = FakeTime()
        fake.sleep(1.5)
        assert fake.monotonic() == 1.5

    def test_multiple_sleeps_accumulate(self) -> None:
        """Multiple sleep() calls should accumulate."""
        fake = FakeTime()
        fake.sleep(1.0)
        fake.sleep(2.0)
        assert fake.monotonic() == 3.0

    def test_zero_sleep_does_not_advance(self) -> None:
        """sleep(0) should not change the clock."""
        fake = FakeTime()
        fake.sleep(0)
        assert fake.monotonic() == 0.0


class TestFakeTimeAdvance:
    """Tests for FakeTime.advance."""

    def test_advance_moves_clock_forward(self) -> None:
        """advance() should move the clock forward."""
        fake = FakeTime()
        fake.advance(5.0)
        assert fake.monotonic() == 5.0

    def test_advance_and_sleep_combine(self) -> None:
        """advance() and sleep() should both contribute to the clock."""
        fake = FakeTime()
        fake.sleep(1.0)
        fake.advance(2.0)
        fake.sleep(0.5)
        assert fake.monotonic() == 3.5


class TestFakeTimeReExport:
    """Tests for the chumicro_testing package re-export."""

    def test_importable_from_package(self) -> None:
        """FakeTime should be importable from chumicro_testing."""
        from chumicro_testing import FakeTime as imported

        assert imported is FakeTime

    def test_importable_from_fake_time_module(self) -> None:
        """FakeTime should be importable from chumicro_testing.fake_time."""
        from chumicro_testing.fake_time import FakeTime as imported

        assert imported is FakeTime

