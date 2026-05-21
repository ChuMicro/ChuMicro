"""Device-facing tests for the tick-based Runner on real hardware.

Exercises Runner with the real runtime clock to validate task
scheduling, periodic firing, check gates, run counts, and removal.
"""

import time

from chumicro_runner import Runner, TaskHandle


def _sleep_ms(duration_ms: int) -> None:
    """Sleep for the requested duration using the best available API.

    Args:
        duration_ms: Duration in milliseconds.
    """
    runtime_sleep_ms = getattr(time, "sleep_ms", None)
    if callable(runtime_sleep_ms):
        runtime_sleep_ms(duration_ms)
        return
    time.sleep(duration_ms / 1000)


def test_runner_add_periodic_fires() -> None:
    """A periodic handler should fire after its period elapses."""
    log = []

    def handler(now_ms: int) -> None:
        log.append(now_ms)

    runner = Runner()
    runner.add_periodic(handler, period_ms=30)

    # Tick before period: should not fire.
    runner.tick()
    assert len(log) == 0

    _sleep_ms(50)
    runner.tick()
    assert len(log) == 1


def test_runner_handler_only_fires_every_tick() -> None:
    """A handler with no period or check should fire on every tick."""
    count = [0]

    def handler(now_ms: int) -> None:
        count[0] += 1

    runner = Runner()
    runner.add(handler=handler)

    runner.tick()
    runner.tick()
    runner.tick()
    assert count[0] == 3


def test_runner_check_gate_controls_firing() -> None:
    """A handler behind a check gate should only fire when the gate passes."""
    log = []
    should_fire = [False]

    def check(now_ms: int) -> bool:
        return should_fire[0]

    def handler(now_ms: int) -> None:
        log.append(now_ms)

    runner = Runner()
    runner.add(check, handler=handler)

    runner.tick()
    assert len(log) == 0

    should_fire[0] = True
    runner.tick()
    assert len(log) == 1


def test_runner_run_count_limits_fires() -> None:
    """A task with run_count should auto-remove after exhausting its count."""
    count = [0]

    def handler(now_ms: int) -> None:
        count[0] += 1

    runner = Runner()
    handle = runner.add(handler=handler, run_count=3)

    for _iteration in range(5):
        runner.tick()

    assert count[0] == 3
    assert handle.active is False


def test_runner_task_handle_remove() -> None:
    """Removing a task via its handle should stop it from firing."""
    count = [0]

    def handler(now_ms: int) -> None:
        count[0] += 1

    runner = Runner()
    handle = runner.add(handler=handler)

    runner.tick()
    assert count[0] == 1

    handle.remove()
    runner.tick()
    assert count[0] == 1
    assert handle.active is False


def test_runner_tick_returns_timestamp() -> None:
    """tick should return a valid tick value."""
    runner = Runner()
    now = runner.tick()
    assert now >= 0
    assert now < (1 << 29)


def test_runner_add_returns_task_handle() -> None:
    """add should return a TaskHandle with the expected properties."""
    runner = Runner()

    def handler(now_ms: int) -> None:
        pass

    handle = runner.add(handler=handler, period_ms=100)
    assert isinstance(handle, TaskHandle)
    assert handle.period_ms == 100
    assert handle.active is True


def test_runner_object_based_task() -> None:
    """A task object with check/handle methods should work with add."""
    log = []

    class MyTask:
        def __init__(self):
            self.gate_open = False

        def check(self, now_ms: int) -> bool:
            return self.gate_open

        def handle(self, now_ms: int) -> None:
            log.append(now_ms)

    task = MyTask()
    runner = Runner()
    runner.add(task)

    runner.tick()
    assert len(log) == 0

    task.gate_open = True
    runner.tick()
    assert len(log) == 1


def test_runner_multiple_tasks_same_tick() -> None:
    """Multiple handlers should all fire in the same tick cycle."""
    results = []

    def make_handler(label: str):
        def handler(now_ms: int) -> None:
            results.append(label)
        return handler

    runner = Runner()
    runner.add(handler=make_handler("alpha"))
    runner.add(handler=make_handler("beta"))
    runner.add(handler=make_handler("gamma"))

    runner.tick()
    assert results == ["alpha", "beta", "gamma"]
