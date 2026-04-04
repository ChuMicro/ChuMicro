"""Tests for the ServiceRunner.

Cross-runtime: runs on CPython (via pytest), MicroPython and CircuitPython
(via the lightweight test harness).
"""

from chumicro_serviceable import ServiceRunner
from chumicro_serviceable.testing import FakeService
from chumicro_timing.testing import FakeTicks


def test_runner_tick_returns_current_time():
    """tick() should capture and return the current timestamp."""
    fake = FakeTicks()
    runner = ServiceRunner(ticks=fake)

    fake.advance(42)
    assert runner.tick() == 42


def test_runner_services_all_components():
    """tick() should call service(now_ms) on every registered component."""
    fake = FakeTicks()
    svc_a = FakeService()
    svc_b = FakeService()
    runner = ServiceRunner(services=[svc_a, svc_b], ticks=fake)

    fake.advance(100)
    runner.tick()

    assert svc_a.ticks == [100]
    assert svc_b.ticks == [100]


def test_runner_passes_same_timestamp_to_all():
    """All components should receive the same now_ms on a single tick."""
    fake = FakeTicks()
    timestamps = []

    class _Recorder:
        """Record each now_ms received."""

        def service(self, now_ms):
            """Append now_ms to the shared list."""
            timestamps.append(now_ms)

    runner = ServiceRunner(services=[_Recorder(), _Recorder(), _Recorder()], ticks=fake)
    fake.advance(77)
    runner.tick()

    assert timestamps == [77, 77, 77]


def test_runner_add():
    """Components added via add() should be serviced on subsequent ticks."""
    fake = FakeTicks()
    svc = FakeService()
    runner = ServiceRunner(ticks=fake)
    runner.add(svc)

    fake.advance(50)
    runner.tick()

    assert svc.ticks == [50]


def test_runner_handles_no_services():
    """tick() should work with no registered services."""
    fake = FakeTicks()
    runner = ServiceRunner(ticks=fake)

    fake.advance(10)
    assert runner.tick() == 10


def test_runner_multiple_ticks():
    """Each tick() should capture a fresh timestamp."""
    fake = FakeTicks()
    svc = FakeService()
    runner = ServiceRunner(services=[svc], ticks=fake)

    fake.advance(10)
    runner.tick()
    fake.advance(20)
    runner.tick()

    assert svc.ticks == [10, 30]


def test_fake_service_records_calls():
    """FakeService should record every service(now_ms) call."""
    svc = FakeService()
    svc.service(1)
    svc.service(2)
    svc.service(3)

    assert svc.ticks == [1, 2, 3]


def test_runner_defaults_to_real_ticks():
    """ServiceRunner with no ticks argument should use chumicro_timing.ticks_ms."""
    runner = ServiceRunner()
    now = runner.tick()

    assert isinstance(now, int)
    assert now >= 0

