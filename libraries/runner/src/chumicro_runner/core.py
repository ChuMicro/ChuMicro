"""Core tick-runner abstractions for the Chumicro ecosystem.

Provides two ways to register work with a ``Runner``:

1. **Gate-based** — a check function decides whether a handler fires.
   Register with ``add(check_function, handler=function)`` (both callables) or
   ``add(obj)`` where *obj* has ``.check(now_ms) -> bool`` and
   ``.handle(now_ms)`` methods.
2. **Periodic** — ``add_periodic(handler, period_ms)``: the handler fires
   every *period_ms* milliseconds with no check.

All classes are cross-runtime compatible (CPython, MicroPython, CircuitPython).

See ``plans/decisions/0014-runner-pattern.md`` for the design rationale.
"""


class _TaskEntry:
    """Internal record for a single task registered with the runner.

    Each entry holds the check/handler callables, timing state, and a
    run counter.  The runner iterates over entries every ``tick()`` to
    decide which handlers fire.

    Attributes:
        check_function: Optional callable ``check_function(now_ms) -> bool``
            that gates the handler.  ``None`` means no check gate (handler
            fires whenever the time gate passes).
        handler_function: Callable ``handler_function(now_ms)`` invoked when
            the task is due.
        period_ms: Interval in milliseconds between firings, or
            ``None`` for non-periodic tasks (fire every tick once any
            initial delay expires).
        next_due_ms: Tick value at which the task becomes eligible, or
            ``None`` if it is eligible immediately.  Updated after each
            firing for periodic tasks.
        run_count: Remaining number of times the handler may fire, or
            ``None`` for unlimited.  Decremented by the runner after
            each firing; the entry is auto-removed when it reaches zero.
        active: ``True`` while the entry is registered.  Set to
            ``False`` by ``Runner._remove_entry`` so that in-progress
            iteration can skip it safely.
    """

    __slots__ = (
        "check_function", "handler_function", "period_ms", "next_due_ms",
        "run_count", "active",
    )

    def __init__(self, check_function, handler_function, period_ms,
                 next_due_ms, run_count):
        """Create a task entry.

        Args:
            check_function: Optional check callable, or ``None``.
            handler_function: Handler callable invoked when the task fires.
            period_ms: Repeat interval in ms, or ``None``.
            next_due_ms: First eligible tick value, or ``None``.
            run_count: Remaining fires, or ``None`` for unlimited.
        """
        self.check_function = check_function
        self.handler_function = handler_function
        self.period_ms = period_ms
        self.next_due_ms = next_due_ms
        self.run_count = run_count
        self.active = True


class TaskHandle:
    """Opaque handle returned by ``Runner.add()`` or ``add_periodic()``.

    Provides runtime mutation of a registered task: change its period
    or remove it from the runner entirely.

    Read-only properties expose the current state for inspection and
    testing.
    """

    __slots__ = ("_entry", "_runner")

    def __init__(self, entry, runner):
        """Create a handle wrapping *entry* owned by *runner*."""
        self._entry = entry
        self._runner = runner

    @property
    def period_ms(self):
        """Return the task period in milliseconds, or ``None``."""
        return self._entry.period_ms

    @property
    def run_count(self):
        """Return the remaining run count, or ``None`` if unlimited."""
        return self._entry.run_count

    @property
    def active(self):
        """Return whether the task is still registered."""
        return self._entry.active

    def set_period(self, period_ms):
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
        self._entry.period_ms = period_ms
        if period_ms is not None:
            ticks = self._runner._ticks
            now_ms = ticks.ticks_ms()
            self._entry.next_due_ms = ticks.ticks_add(now_ms, period_ms)
        else:
            self._entry.next_due_ms = None

    def remove(self):
        """Remove this task from the runner."""
        self._runner._remove_entry(self._entry)

    def __repr__(self):
        """Return a developer-friendly representation."""
        status = "active" if self._entry.active else "removed"
        period = self._entry.period_ms
        count = self._entry.run_count
        parts = [f"period_ms={period}"]
        if count is not None:
            parts.append(f"run_count={count}")
        parts.append(status)
        return f"TaskHandle({', '.join(parts)})"


class Runner:
    """Run tasks on a tick-based schedule.

    Captures ``ticks_ms()`` once per ``tick()`` call and passes
    the shared timestamp to every due component, ensuring all components
    see the same moment in time.

    Registration paths:

    - ``add(obj)`` — *obj* has ``.check(now_ms) -> bool`` and
      ``.handle(now_ms)``.  The runner calls ``.check()``; if ``True``,
      ``.handle()`` is queued.
    - ``add(check_function, handler=function)`` — callable check gates
      callable handler.
    - ``add(handler=function)`` — handler fires every tick (or per period).
    - ``add_periodic(handler, period_ms)`` — fires ``handler(now_ms)``
      every *period_ms* milliseconds.

    ``tick()`` runs in two phases:

    1. Check all entries (period gate, then check gate) and collect
       due handlers.
    2. Batch-fire all collected handlers.

    Period gating uses ``ticks_diff`` and ``ticks_add`` directly —
    no ``Heartbeat`` objects are created internally.

    Args:
        ticks: Optional tick source (must have ``ticks_ms``,
            ``ticks_diff``, and ``ticks_add`` methods).
            Defaults to the ``chumicro_timing`` module-level functions.
    """

    __slots__ = ("_entries", "_pending", "_ticks")

    def __init__(self, ticks=None):
        """Create a runner.

        Args:
            ticks: Optional tick source (must have ``ticks_ms``,
                ``ticks_diff``, and ``ticks_add`` methods).
                Defaults to the ``chumicro_timing.ticks`` module.
                Constructor injection per Decision 0010; pass
                ``FakeTicks`` from ``chumicro_timing.testing`` in tests.
        """
        self._entries = []
        self._pending = []
        if ticks is not None:
            self._ticks = ticks
        else:
            from chumicro_timing import ticks as _ticks_mod

            self._ticks = _ticks_mod

    def add(self, task=None, handler=None, period_ms=None,
            start_after_ms=None, run_count=None):
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

        next_due_ms = None
        if start_after_ms is not None:
            now_ms = self._ticks.ticks_ms()
            next_due_ms = self._ticks.ticks_add(now_ms, start_after_ms)
        elif period_ms is not None:
            now_ms = self._ticks.ticks_ms()
            next_due_ms = self._ticks.ticks_add(now_ms, period_ms)

        entry = _TaskEntry(
            check_function, handler_function, period_ms, next_due_ms,
            run_count,
        )
        self._entries.append(entry)
        return TaskHandle(entry, self)

    def add_periodic(self, handler, period_ms, start_after_ms=None,
                     run_count=None):
        """Register a periodic handler with no check.

        ``handler(now_ms)`` is called every *period_ms* milliseconds.
        Returns a ``TaskHandle`` for runtime mutation.

        Args:
            handler: Callable ``handler(now_ms)`` to fire periodically.
            period_ms: Interval in milliseconds (required).
            start_after_ms: Optional initial delay before first fire.
                Overrides the first period.
            run_count: Optional number of times the handler may fire
                before auto-removing.  ``None`` means unlimited.
        """
        if period_ms <= 0:
            raise ValueError("period_ms must be greater than zero")
        if run_count is not None and run_count <= 0:
            raise ValueError("run_count must be greater than zero")

        now_ms = self._ticks.ticks_ms()
        if start_after_ms is not None:
            next_due_ms = self._ticks.ticks_add(now_ms, start_after_ms)
        else:
            next_due_ms = self._ticks.ticks_add(now_ms, period_ms)

        entry = _TaskEntry(
            None, handler, period_ms, next_due_ms, run_count,
        )
        self._entries.append(entry)
        return TaskHandle(entry, self)

    def tick(self):
        """Capture time, check tasks, then batch-fire handlers.

        1. Check each entry (period gate -> check gate).
           Collect entries whose handlers should fire.
        2. Batch-fire all collected handlers.
        3. Decrement run counts; auto-remove exhausted entries.

        Returns:
            The ``now_ms`` value used this tick.
        """
        ticks = self._ticks
        now_ms = ticks.ticks_ms()
        ticks_diff = ticks.ticks_diff
        ticks_add = ticks.ticks_add
        pending = self._pending

        for entry in self._entries:
            if not entry.active:
                continue

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
                    self._remove_entry(entry)
        pending.clear()

        return now_ms

    def _remove_entry(self, entry):
        """Remove *entry* from the runner (called by ``TaskHandle``)."""
        entry.active = False
        try:
            self._entries.remove(entry)
        except ValueError:
            pass
