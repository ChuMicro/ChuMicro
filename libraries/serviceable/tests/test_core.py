"""Tests for the core serviceable-pattern abstractions.

Cross-runtime: runs on CPython (via pytest), MicroPython and CircuitPython
(via the lightweight test harness).
"""

import pytest
from chumicro_serviceable import ServiceHandle, ServiceRunner
from chumicro_serviceable.testing import CallRecorder
from chumicro_timing.testing import FakeTicks

# -- Helpers --


class _GateService:
    """Minimal gate-based serviceable component for testing."""

    def __init__(self, should_fire=True):
        """Create a stub that returns *should_fire* from service()."""
        self.should_fire = should_fire
        self.service_count = 0
        self.handle_count = 0

    def service(self, now_ms):
        """Return whether the handler should fire."""
        self.service_count += 1
        return self.should_fire

    def handle(self, now_ms):
        """Record that the handler was called."""
        self.handle_count += 1


# -- ServiceHandle --


def test_add_returns_service_handle():
    """add() should return a ServiceHandle."""
    fake = FakeTicks()
    runner = ServiceRunner(ticks=fake)
    handle = runner.add(_GateService())

    assert isinstance(handle, ServiceHandle)


def test_service_handle_active_when_added():
    """ServiceHandle should report active when first added."""
    fake = FakeTicks()
    runner = ServiceRunner(ticks=fake)
    handle = runner.add(_GateService())

    assert handle.active is True


def test_service_handle_period_ms_none_by_default():
    """period_ms should be None when no period is configured."""
    fake = FakeTicks()
    runner = ServiceRunner(ticks=fake)
    handle = runner.add(_GateService())

    assert handle.period_ms is None


def test_service_handle_period_ms_when_set():
    """period_ms should reflect the configured period."""
    fake = FakeTicks()
    runner = ServiceRunner(ticks=fake)
    handle = runner.add(_GateService(), period_ms=200)

    assert handle.period_ms == 200


def test_service_handle_set_period_adds():
    """set_period() should add a period to a previously non-periodic service."""
    fake = FakeTicks()
    runner = ServiceRunner(ticks=fake)
    handle = runner.add(_GateService())

    assert handle.period_ms is None
    handle.set_period(300)
    assert handle.period_ms == 300


def test_service_handle_set_period_changes():
    """set_period() should replace the existing period."""
    fake = FakeTicks()
    runner = ServiceRunner(ticks=fake)
    handle = runner.add(_GateService(), period_ms=100)

    handle.set_period(500)
    assert handle.period_ms == 500


def test_service_handle_set_period_none_removes():
    """set_period(None) should remove the period (service runs every tick)."""
    fake = FakeTicks()
    runner = ServiceRunner(ticks=fake)
    handle = runner.add(_GateService(), period_ms=100)

    handle.set_period(None)
    assert handle.period_ms is None


def test_service_handle_remove():
    """remove() should deactivate the handle."""
    fake = FakeTicks()
    runner = ServiceRunner(ticks=fake)
    handle = runner.add(_GateService())
    handle.remove()

    assert handle.active is False


def test_service_handle_remove_idempotent():
    """Calling remove() twice should not raise."""
    fake = FakeTicks()
    runner = ServiceRunner(ticks=fake)
    handle = runner.add(_GateService())
    handle.remove()
    handle.remove()  # should not raise


def test_service_handle_repr():
    """ServiceHandle repr should include period and status."""
    fake = FakeTicks()
    runner = ServiceRunner(ticks=fake)
    handle = runner.add(_GateService(), period_ms=100)

    r = repr(handle)
    assert "100" in r
    assert "active" in r


def test_service_handle_repr_after_remove():
    """ServiceHandle repr should show removed after remove()."""
    fake = FakeTicks()
    runner = ServiceRunner(ticks=fake)
    handle = runner.add(_GateService())
    handle.remove()

    assert "removed" in repr(handle)


# -- ServiceRunner: object-based (service with .service() and .handle()) --


def test_object_service_fires_handler_when_true():
    """Object-based service should fire .handle() when .service() returns True."""
    fake = FakeTicks()
    svc = _GateService(should_fire=True)

    runner = ServiceRunner(ticks=fake)
    runner.add(svc)

    fake.advance(10)
    runner.service_once()

    assert svc.service_count == 1
    assert svc.handle_count == 1


def test_object_service_skips_handler_when_false():
    """Object-based service should not fire .handle() when .service() returns False."""
    fake = FakeTicks()
    svc = _GateService(should_fire=False)

    runner = ServiceRunner(ticks=fake)
    runner.add(svc)

    runner.service_once()

    assert svc.service_count == 1
    assert svc.handle_count == 0


def test_object_service_with_period():
    """Object-based service with period should only be checked when due."""
    fake = FakeTicks()
    svc = _GateService(should_fire=True)

    runner = ServiceRunner(ticks=fake)
    runner.add(svc, period_ms=100)

    # Not due yet.
    runner.service_once()
    assert svc.service_count == 0

    # Now due.
    fake.advance(100)
    runner.service_once()
    assert svc.service_count == 1
    assert svc.handle_count == 1


def test_object_service_handler_override():
    """Passing handler= with an object should override .handle()."""
    fake = FakeTicks()
    svc = _GateService(should_fire=True)
    received = []

    runner = ServiceRunner(ticks=fake)
    runner.add(svc, handler=lambda now: received.append(now))

    fake.advance(5)
    runner.service_once()

    # Custom handler was called, not .handle().
    assert received == [5]
    assert svc.handle_count == 0
    assert svc.service_count == 1


# -- ServiceRunner: callable-based (check_fn + handler) --


def test_callable_check_gates_handler():
    """Callable check_fn should gate handler_fn."""
    fake = FakeTicks()
    received = []
    gate_open = [True]

    runner = ServiceRunner(ticks=fake)
    runner.add(
        lambda now: gate_open[0],
        handler=lambda now: received.append(now),
    )

    fake.advance(10)
    runner.service_once()
    assert received == [10]

    # Close the gate.
    gate_open[0] = False
    received.clear()
    fake.advance(10)
    runner.service_once()
    assert received == []


def test_callable_check_with_period():
    """Callable check with period should only be checked when due."""
    fake = FakeTicks()
    received = []

    runner = ServiceRunner(ticks=fake)
    runner.add(
        lambda now: True,
        handler=lambda now: received.append(now),
        period_ms=100,
    )

    runner.service_once()
    assert received == []

    fake.advance(100)
    runner.service_once()
    assert received == [100]


# -- ServiceRunner: handler-only (no check) --


def test_handler_only_fires_every_tick():
    """Handler-only registration should fire every tick."""
    fake = FakeTicks()
    received = []

    runner = ServiceRunner(ticks=fake)
    runner.add(handler=lambda now: received.append(now))

    runner.service_once()
    assert received == [0]

    fake.advance(10)
    runner.service_once()
    assert received == [0, 10]


def test_handler_only_with_period():
    """Handler-only with period should fire per period."""
    fake = FakeTicks()
    received = []

    runner = ServiceRunner(ticks=fake)
    runner.add(handler=lambda now: received.append(now), period_ms=100)

    runner.service_once()
    assert received == []

    fake.advance(100)
    runner.service_once()
    assert received == [100]


# -- ServiceRunner: add_periodic --


def test_periodic_fires_on_schedule():
    """Periodic handler should fire when the period elapses."""
    fake = FakeTicks()
    received = []

    runner = ServiceRunner(ticks=fake)
    runner.add_periodic(lambda now: received.append(now), period_ms=100)

    runner.service_once()
    assert received == []

    fake.advance(100)
    runner.service_once()
    assert received == [100]


def test_periodic_repeats():
    """Periodic handler should fire repeatedly."""
    fake = FakeTicks()
    received = []

    runner = ServiceRunner(ticks=fake)
    runner.add_periodic(lambda now: received.append(now), period_ms=50)

    fake.advance(50)
    runner.service_once()
    assert len(received) == 1

    fake.advance(50)
    runner.service_once()
    assert len(received) == 2


def test_periodic_set_period_changes_rate():
    """Changing period at runtime should take effect."""
    fake = FakeTicks()
    received = []

    runner = ServiceRunner(ticks=fake)
    handle = runner.add_periodic(lambda now: received.append(now), period_ms=100)

    fake.advance(100)
    runner.service_once()
    assert len(received) == 1

    handle.set_period(50)
    fake.advance(50)
    runner.service_once()
    assert len(received) == 2


def test_periodic_remove():
    """Removed periodic handler should no longer fire."""
    fake = FakeTicks()
    received = []

    runner = ServiceRunner(ticks=fake)
    handle = runner.add_periodic(lambda now: received.append(1), period_ms=50)

    fake.advance(50)
    runner.service_once()
    assert len(received) == 1

    handle.remove()
    fake.advance(50)
    runner.service_once()
    assert len(received) == 1


def test_periodic_handler_receives_now_ms():
    """Periodic handler should receive the shared now_ms timestamp."""
    fake = FakeTicks()
    received = []

    runner = ServiceRunner(ticks=fake)
    runner.add_periodic(lambda now: received.append(now), period_ms=100)

    fake.advance(100)
    runner.service_once()

    assert received == [100]


# -- ServiceRunner: batch firing and ordering --


def test_handlers_fire_in_batch():
    """All handlers should fire after all services are checked."""
    fake = FakeTicks()
    order = []

    class _OrderedGate:
        """Gate that records when it is checked."""

        def __init__(self, name):
            """Create a gate with the given name."""
            self._name = name

        def service(self, now_ms):
            """Record the check and return True."""
            order.append(f"check:{self._name}")
            return True

        def handle(self, now_ms):
            """Record the handle call."""
            order.append(f"fire:{self._name}")

    runner = ServiceRunner(ticks=fake)
    runner.add(_OrderedGate("a"))
    runner.add(_OrderedGate("b"))

    runner.service_once()

    assert order == ["check:a", "check:b", "fire:a", "fire:b"]


# -- ServiceRunner: shared timestamps --


def test_runner_returns_shared_timestamp():
    """service_once() should return the captured now_ms."""
    fake = FakeTicks()
    runner = ServiceRunner(ticks=fake)

    fake.advance(42)
    assert runner.service_once() == 42


def test_runner_passes_same_timestamp_to_all():
    """All services should receive the same now_ms on a single tick."""
    fake = FakeTicks()
    timestamps = []

    class _Recorder:
        """Record each now_ms received."""

        def service(self, now_ms):
            """Append now_ms to the shared list."""
            timestamps.append(now_ms)
            return False

    runner = ServiceRunner(ticks=fake)
    runner.add(_Recorder(), handler=lambda now: None)
    runner.add(_Recorder(), handler=lambda now: None)
    runner.add(_Recorder(), handler=lambda now: None)

    fake.advance(77)
    runner.service_once()

    assert timestamps == [77, 77, 77]


def test_runner_defaults_to_real_ticks():
    """ServiceRunner with no ticks argument should use chumicro_timing.ticks_ms."""
    runner = ServiceRunner()

    now = runner.service_once()

    assert isinstance(now, int)
    assert now >= 0


# -- ServiceRunner: period gating --


def test_period_gates_service():
    """Service with period should only be called when the period elapses."""
    fake = FakeTicks()
    svc = _GateService(should_fire=True)

    runner = ServiceRunner(ticks=fake)
    runner.add(svc, period_ms=100)

    runner.service_once()
    assert svc.service_count == 0

    fake.advance(100)
    runner.service_once()
    assert svc.service_count == 1


def test_period_does_not_fire_early():
    """Service should not be called before the period elapses."""
    fake = FakeTicks()
    svc = _GateService(should_fire=True)

    runner = ServiceRunner(ticks=fake)
    runner.add(svc, period_ms=100)

    fake.advance(99)
    runner.service_once()

    assert svc.service_count == 0


def test_period_repeats():
    """Heartbeat should fire again after another period elapses."""
    fake = FakeTicks()
    svc = _GateService(should_fire=True)

    runner = ServiceRunner(ticks=fake)
    runner.add(svc, period_ms=100)

    fake.advance(100)
    runner.service_once()
    assert svc.handle_count == 1

    fake.advance(100)
    runner.service_once()
    assert svc.handle_count == 2


def test_multiple_periods():
    """Multiple services with different periods should fire independently."""
    fake = FakeTicks()
    fast_received = []
    slow_received = []

    runner = ServiceRunner(ticks=fake)
    runner.add_periodic(lambda now: fast_received.append(1), period_ms=50)
    runner.add_periodic(lambda now: slow_received.append(1), period_ms=200)

    # At 50ms: fast fires, slow does not.
    fake.advance(50)
    runner.service_once()
    assert len(fast_received) == 1
    assert len(slow_received) == 0

    # At 100ms: fast fires again, slow still not.
    fake.advance(50)
    runner.service_once()
    assert len(fast_received) == 2
    assert len(slow_received) == 0

    # At 200ms: both fire.
    fake.advance(100)
    runner.service_once()
    assert len(fast_received) == 3
    assert len(slow_received) == 1


def test_period_and_no_period_together():
    """Both periodic and every-tick services should work together."""
    fake = FakeTicks()
    always = _GateService(should_fire=True)
    periodic_received = []

    runner = ServiceRunner(ticks=fake)
    runner.add(always)
    runner.add_periodic(lambda now: periodic_received.append(1), period_ms=100)

    # Tick 0: always fires, periodic not due.
    runner.service_once()
    assert always.handle_count == 1
    assert len(periodic_received) == 0

    # Advance past period: both fire.
    fake.advance(100)
    runner.service_once()
    assert always.handle_count == 2
    assert len(periodic_received) == 1


# -- ServiceRunner: runtime mutation --


def test_remove_stops_service():
    """Removed service should no longer be called."""
    fake = FakeTicks()
    svc = _GateService(should_fire=True)

    runner = ServiceRunner(ticks=fake)
    handle = runner.add(svc)

    runner.service_once()
    assert svc.service_count == 1

    handle.remove()
    runner.service_once()
    assert svc.service_count == 1


def test_set_period_at_runtime():
    """Adding a period at runtime should take effect."""
    fake = FakeTicks()
    svc = _GateService(should_fire=True)

    runner = ServiceRunner(ticks=fake)
    handle = runner.add(svc)

    # Runs every tick.
    runner.service_once()
    assert svc.service_count == 1

    # Add a period — should stop calling until period elapses.
    handle.set_period(200)
    runner.service_once()
    assert svc.service_count == 1

    fake.advance(200)
    runner.service_once()
    assert svc.service_count == 2


def test_remove_period_at_runtime():
    """Removing a period should make the service run every tick again."""
    fake = FakeTicks()
    svc = _GateService(should_fire=True)

    runner = ServiceRunner(ticks=fake)
    handle = runner.add(svc, period_ms=100)

    runner.service_once()
    assert svc.service_count == 0

    handle.set_period(None)
    runner.service_once()
    assert svc.service_count == 1


# -- ServiceRunner: error cases --


def test_add_no_args_raises():
    """add() with no service and no handler should raise ValueError."""
    fake = FakeTicks()
    runner = ServiceRunner(ticks=fake)

    with pytest.raises(ValueError):
        runner.add()


# -- Mixed patterns --


def test_all_patterns_together():
    """Object-based, callable-based, handler-only, and periodic all in one runner."""
    fake = FakeTicks()
    results = []

    svc = _GateService(should_fire=True)

    runner = ServiceRunner(ticks=fake)
    runner.add(svc)  # object-based
    runner.add(lambda now: True, handler=lambda now: results.append("callable"))
    runner.add(handler=lambda now: results.append("handler-only"))
    runner.add_periodic(lambda now: results.append("periodic"), period_ms=100)

    fake.advance(100)
    runner.service_once()

    assert svc.handle_count == 1
    assert "callable" in results
    assert "handler-only" in results
    assert "periodic" in results


# -- CallRecorder --


def test_call_recorder_records_calls():
    """CallRecorder should record all invocations."""
    recorder = CallRecorder()
    recorder(10)
    recorder(20)

    assert recorder.calls == [10, 20]
    assert len(recorder) == 2


def test_call_recorder_clear():
    """CallRecorder.clear should discard all recorded calls."""
    recorder = CallRecorder()
    recorder(10)
    recorder.clear()

    assert len(recorder) == 0
    assert recorder.calls == []


def test_call_recorder_as_handler():
    """CallRecorder should work as a handler in ServiceRunner."""
    fake = FakeTicks()
    recorder = CallRecorder()

    runner = ServiceRunner(ticks=fake)
    runner.add_periodic(recorder, period_ms=100)

    runner.service_once()
    assert len(recorder) == 0

    fake.advance(100)
    runner.service_once()
    assert recorder.calls == [100]
