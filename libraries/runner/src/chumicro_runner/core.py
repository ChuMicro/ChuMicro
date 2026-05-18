"""Core tick-runner abstractions for the ChuMicro ecosystem.

Provides two ways to register work with a ``Runner``:

1. **Gate-based** — a check function decides whether a handler fires.
   Register with ``add(check_function, handler=function)`` (both callables) or
   ``add(obj)`` where *obj* has ``.check(now_ms) -> bool`` and
   ``.handle(now_ms)`` methods.
2. **Periodic** — ``add_periodic(handler, period_ms)``: the handler fires
   every *period_ms* milliseconds with no check.

All classes are cross-runtime compatible (CPython, MicroPython, CircuitPython).
"""

# Default tick source imported eagerly at module load.  Lazy import inside
# ``Runner.__init__`` would add ~1 s to the first test on MP mount-mode
# (each fresh import becomes an mpremote RPC); eager import pushes the
# cost to module-import time, before the harness starts its timer.
from chumicro_timing import ticks as _DEFAULT_TICKS


class TaskHandle:
    """Handle returned by ``Runner.add()`` or ``add_periodic()``.

    Inspect the task's state via the ``period_ms``, ``run_count``,
    and ``active`` attributes; mutate via ``set_period()`` or
    ``remove()``.
    """

    def __init__(self, check_function: object | None,
                 handler_function: object,
                 period_ms: int | None,
                 next_due_ms: int | None,
                 run_count: int | None,
                 runner: "Runner") -> None:
        self.check_function = check_function
        self.handler_function = handler_function
        self.period_ms = period_ms
        self.next_due_ms = next_due_ms
        self.run_count = run_count
        self.active = True
        self._runner = runner

    def set_period(self, period_ms: int | None) -> None:
        """Add, change, or remove the period for this task.

        Pass ``None`` to remove an existing period (task runs every tick).
        A non-None value resets the timer so the next fire is
        *period_ms* from now.

        Args:
            period_ms: New interval in milliseconds, or ``None`` to
                clear the period.
        """
        if period_ms is not None and period_ms <= 0:
            raise ValueError("period_ms must be greater than zero")
        self.period_ms = period_ms
        if period_ms is not None:
            ticks = self._runner._ticks
            now_ms = ticks.ticks_ms()
            self.next_due_ms = ticks.ticks_add(now_ms, period_ms)
        else:
            self.next_due_ms = None

    def remove(self) -> None:
        """Remove this task from the runner."""
        self._runner._remove(self)

    def __repr__(self) -> str:
        status = "active" if self.active else "removed"
        period = self.period_ms
        count = self.run_count
        parts = [f"period_ms={period}"]
        if count is not None:
            parts.append(f"run_count={count}")
        parts.append(status)
        return f"TaskHandle({', '.join(parts)})"


class Runner:
    """Run tasks on a tick-based schedule.

    Captures ``ticks_ms()`` once per ``tick()`` call and passes the
    shared timestamp to every due component.  Registration paths are
    documented on ``add()`` and ``add_periodic()``.

    Args:
        ticks: Optional tick source (must have ``ticks_ms``,
            ``ticks_diff``, and ``ticks_add`` methods).
            Defaults to the ``chumicro_timing`` module-level functions.
            Tests pass ``FakeTicks`` from ``chumicro_timing.testing``.
    """

    def __init__(self, ticks: object | None = None) -> None:
        self._entries = []
        self._pending = []
        self._ticking = False
        self._ticks = ticks if ticks is not None else _DEFAULT_TICKS

    def add(self, task: object | None = None,
            handler: object | None = None,
            period_ms: int | None = None,
            start_after_ms: int | None = None,
            run_count: int | None = None) -> TaskHandle:
        """Register a task with the runner.

        **Object-based** (task only): *task* must have
        ``.check(now_ms) -> bool`` and ``.handle(now_ms)`` methods.

        **Callable-based** (task + handler): *task* is a callable
        ``check_function(now_ms) -> bool`` that gates ``handler(now_ms)``.

        **Handler-only** (handler, no task): ``handler(now_ms)`` fires
        on every tick (or per period if *period_ms* is set).

        Returns a ``TaskHandle`` for runtime mutation.

        Args:
            task: Object with ``.check()`` and ``.handle()``, or a
                callable ``check_function(now_ms) -> bool``.
            handler: Optional callable ``handler(now_ms)``.
            period_ms: Optional interval in milliseconds.
            start_after_ms: Optional initial delay before the task
                becomes eligible.  Overrides the first period;
                subsequent fires use *period_ms* if set.
            run_count: Optional number of times the handler may fire
                before auto-removing.  ``None`` means unlimited.
        """
        if handler is not None:
            # Callable-based or handler-only.
            if task is not None and not callable(task):
                check_function = task.check
            else:
                check_function = task  # callable or None (handler-only)
            handler_function = handler
        elif task is not None:
            # Object-based: must have .check() and .handle().
            check_function = task.check
            handler_function = task.handle
        else:
            raise ValueError(
                "Provide a task object (with .check() and .handle()) "
                "or a handler callable"
            )

        if period_ms is not None and period_ms <= 0:
            raise ValueError("period_ms must be greater than zero")
        if run_count is not None and run_count <= 0:
            raise ValueError("run_count must be greater than zero")

        next_due_ms = self._initial_next_due_ms(start_after_ms, period_ms)

        handle = TaskHandle(
            check_function, handler_function, period_ms, next_due_ms,
            run_count, self,
        )
        self._entries.append(handle)
        return handle

    def add_periodic(self, handler: object, period_ms: int,
                     start_after_ms: int | None = None,
                     run_count: int | None = None) -> TaskHandle:
        """Register a periodic handler with no check.

        Convenience wrapper around ``add(handler=..., period_ms=...)``
        that requires *period_ms*.  Returns a ``TaskHandle`` for
        runtime mutation.

        Args:
            handler: Callable ``handler(now_ms)`` to fire periodically.
            period_ms: Interval in milliseconds (required).
            start_after_ms: Optional initial delay before first fire.
                Overrides the first period.
            run_count: Optional number of times the handler may fire
                before auto-removing.  ``None`` means unlimited.
        """
        if period_ms is None:
            raise ValueError("period_ms is required for add_periodic")
        return self.add(
            handler=handler, period_ms=period_ms,
            start_after_ms=start_after_ms, run_count=run_count,
        )

    def tick(self) -> int:
        """Capture time, check tasks, then batch-fire handlers.

        1. Check each entry (period gate -> check gate).
           Collect entries whose handlers should fire.
        2. Batch-fire all collected handlers.
        3. Decrement run counts; auto-remove exhausted entries.

        Returns:
            The tick timestamp used this cycle.
        """
        # Re-entrancy guard: a handler calling tick() on this runner
        # would corrupt the shared _pending list mid-iteration. Reject
        # it rather than queue deferred ops (no per-tick allocation).
        if self._ticking:
            raise RuntimeError(
                "Runner.tick() is not re-entrant; a handler must not call tick()",
            )
        self._ticking = True
        try:
            ticks = self._ticks
            now_ms = ticks.ticks_ms()
            ticks_diff = ticks.ticks_diff
            ticks_add = ticks.ticks_add
            pending = self._pending

            for entry in self._entries:
                # Time gate (period or start delay).
                if entry.next_due_ms is not None:
                    if ticks_diff(now_ms, entry.next_due_ms) < 0:
                        continue
                    # Advance: periodic → next period; one-shot → clear.
                    if entry.period_ms is not None:
                        entry.next_due_ms = ticks_add(now_ms, entry.period_ms)
                    else:
                        entry.next_due_ms = None

                # Check gate.
                if entry.check_function is not None:
                    if entry.check_function(now_ms):
                        pending.append(entry)
                else:
                    pending.append(entry)

            for entry in pending:
                entry.handler_function(now_ms)
                if entry.run_count is not None:
                    entry.run_count -= 1
                    if entry.run_count <= 0:
                        self._remove(entry)
            pending.clear()

            return now_ms
        finally:
            self._ticking = False

    def _initial_next_due_ms(self, start_after_ms: int | None,
                             period_ms: int | None) -> int | None:
        """Return the initial ``next_due_ms``; ``start_after_ms`` wins over ``period_ms``."""
        delay_ms = start_after_ms if start_after_ms is not None else period_ms
        if delay_ms is None:
            return None
        now_ms = self._ticks.ticks_ms()
        return self._ticks.ticks_add(now_ms, delay_ms)

    def _remove(self, handle: TaskHandle) -> None:
        """Remove *handle* from the runner (called by ``TaskHandle``)."""
        handle.active = False
        try:
            self._entries.remove(handle)
        except ValueError:
            pass
