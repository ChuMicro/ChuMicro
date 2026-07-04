"""Task-lifetime controls: ``run_count`` and ``start_after_ms``.

Cross-runtime: runs on CPython (via pytest), MicroPython and CircuitPython
(via chumicro_test_harness).
"""


from _core_helpers import _GateTask
from chumicro_runner import Runner
from chumicro_test_harness import raises
from chumicro_timing.testing import FakeTicks

# -- run_count --


def test_run_count_fires_exactly_n_times() -> None:
    """Handler with run_count should fire exactly N times then stop."""
    fake = FakeTicks()
    received = []

    runner = Runner(ticks=fake)
    runner.add(handler=lambda now: received.append(now), run_count=3)

    for _i in range(5):
        fake.advance(10)
        runner.tick()

    assert len(received) == 3


def test_run_count_auto_removes() -> None:
    """Task should be inactive after run_count is exhausted."""
    fake = FakeTicks()
    runner = Runner(ticks=fake)
    handle = runner.add(handler=lambda now: None, run_count=1)

    runner.tick()
    assert handle.active is False


def test_run_count_with_period() -> None:
    """Periodic task with run_count should fire N periods then stop."""
    fake = FakeTicks()
    received = []

    runner = Runner(ticks=fake)
    runner.add_periodic(
        lambda now: received.append(now), period_ms=100, run_count=2,
    )

    # Period 1.
    fake.advance(100)
    runner.tick()
    assert len(received) == 1

    # Period 2.
    fake.advance(100)
    runner.tick()
    assert len(received) == 2

    # Period 3: should not fire.
    fake.advance(100)
    runner.tick()
    assert len(received) == 2


def test_run_count_one_is_one_shot() -> None:
    """run_count=1 should fire exactly once."""
    fake = FakeTicks()
    received = []

    runner = Runner(ticks=fake)
    runner.add_periodic(
        lambda now: received.append(now), period_ms=50, run_count=1,
    )

    fake.advance(50)
    runner.tick()
    assert received == [50]

    fake.advance(50)
    runner.tick()
    assert received == [50]


def test_run_count_property() -> None:
    """TaskHandle.run_count should reflect remaining count."""
    fake = FakeTicks()
    runner = Runner(ticks=fake)
    handle = runner.add(handler=lambda now: None, run_count=3)

    assert handle.run_count == 3

    runner.tick()
    assert handle.run_count == 2

    runner.tick()
    assert handle.run_count == 1


def test_run_count_none_by_default() -> None:
    """run_count should be None when not specified."""
    fake = FakeTicks()
    runner = Runner(ticks=fake)
    handle = runner.add(handler=lambda now: None)

    assert handle.run_count is None


def test_run_count_zero_raises() -> None:
    """run_count=0 should raise ValueError."""
    fake = FakeTicks()
    runner = Runner(ticks=fake)

    with raises(ValueError):
        runner.add(handler=lambda now: None, run_count=0)


def test_run_count_zero_raises_periodic() -> None:
    """run_count=0 on add_periodic should raise ValueError."""
    fake = FakeTicks()
    runner = Runner(ticks=fake)

    with raises(ValueError):
        runner.add_periodic(lambda now: None, period_ms=100, run_count=0)


def test_run_count_repr() -> None:
    """TaskHandle repr should include run_count when set."""
    fake = FakeTicks()
    runner = Runner(ticks=fake)
    handle = runner.add(handler=lambda now: None, run_count=5)

    result = repr(handle)
    assert "run_count=5" in result


# -- start_after_ms --


def test_start_after_ms_delays_handler() -> None:
    """Handler should not fire before start_after_ms elapses."""
    fake = FakeTicks()
    received = []

    runner = Runner(ticks=fake)
    runner.add(handler=lambda now: received.append(now), start_after_ms=500)

    # Before delay.
    fake.advance(200)
    runner.tick()
    assert received == []

    fake.advance(200)
    runner.tick()
    assert received == []

    # At delay.
    fake.advance(100)
    runner.tick()
    assert received == [500]


def test_start_after_ms_then_every_tick() -> None:
    """Handler-only with start_after_ms should run every tick after delay."""
    fake = FakeTicks()
    received = []

    runner = Runner(ticks=fake)
    runner.add(handler=lambda now: received.append(now), start_after_ms=100)

    runner.tick()
    assert received == []

    fake.advance(100)
    runner.tick()
    assert received == [100]

    # Now should fire every tick.
    fake.advance(10)
    runner.tick()
    assert len(received) == 2


def test_start_after_ms_with_period() -> None:
    """start_after_ms should delay first fire.  Subsequent fires use period_ms."""
    fake = FakeTicks()
    received = []

    runner = Runner(ticks=fake)
    runner.add_periodic(
        lambda now: received.append(now),
        period_ms=100,
        start_after_ms=500,
    )

    # Before start delay.
    fake.advance(400)
    runner.tick()
    assert received == []

    # At start delay: first fire.
    fake.advance(100)
    runner.tick()
    assert received == [500]

    # One period later: second fire.
    fake.advance(100)
    runner.tick()
    assert received == [500, 600]


def test_start_after_ms_with_check() -> None:
    """Object-based task with start_after_ms should delay check calls."""
    fake = FakeTicks()
    svc = _GateTask(should_fire=True)

    runner = Runner(ticks=fake)
    runner.add(svc, start_after_ms=200)

    # Before delay: check should not be called.
    fake.advance(100)
    runner.tick()
    assert svc.check_count == 0

    # After delay: check runs normally.
    fake.advance(100)
    runner.tick()
    assert svc.check_count == 1
    assert svc.handle_count == 1


def test_start_after_ms_zero_fires_immediately() -> None:
    """start_after_ms=0 should fire on the first tick."""
    fake = FakeTicks()
    received = []

    runner = Runner(ticks=fake)
    runner.add(handler=lambda now: received.append(now), start_after_ms=0)

    runner.tick()
    assert received == [0]
