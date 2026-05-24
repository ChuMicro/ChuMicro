"""Tick-based scheduler for the ChuMicro libraries.

Register work with a ``Runner``, then call ``tick()`` in a loop.
Each ``tick()`` captures the current time once, checks every
registered task, and fires the handlers whose gates have passed.

Three registration shapes are accepted: object-based (``.check`` +
``.handle`` methods), callable-based (check function + handler),
and handler-only (fires every tick, or per period if one is set).
See ``Runner.add`` for signatures.  ``add_periodic`` is the periodic
shortcut.

``TaskHandle`` (returned from registration) carries runtime state
and supports ``set_period`` / ``remove``.

The optional ``Runner.wait(now_ms)`` companion idles the CPU between
ticks, blocking on a ``select.poll`` over each service's exposed
sockets (or sleeping until the next deadline when no socket is
registered).  See ``Runner.wait`` for the contract.

Cross-runtime: CPython, MicroPython, CircuitPython.
"""

# Default tick source imported eagerly at module load.  Lazy import inside
# ``Runner.__init__`` would add ~1 s to the first test on MP mount-mode
# (each fresh import becomes an mpremote RPC).  Eager import pushes the
# cost to module-import time, before the harness starts its timer.
import time

from chumicro_timing import ticks as _DEFAULT_TICKS

# POSIX poll flags resolved once at import time so ``wait`` can translate
# the duck-typed ``io_wants_read`` / ``io_wants_write`` bools into a
# poll eventmask without an attribute lookup on every loop.  The
# numeric fallbacks match POSIX (0x001 / 0x004 / 0x008 / 0x010) for
# runtimes whose ``select`` module is unimportable at runner load time.
# POLLERR + POLLHUP are surfaced to services via the ``io_error`` hook
# from ``Runner.wait``; see the docstring there.
# pragma below: CPython, MicroPython, and CircuitPython all ship
# ``select``.  The fallback covers hypothetical embedded runtimes
# that don't, so no test runtime reaches it.
try:
    import select as _select

    _POLLIN = _select.POLLIN
    _POLLOUT = _select.POLLOUT
    _POLLERR = _select.POLLERR
    _POLLHUP = _select.POLLHUP
    del _select
except ImportError:  # pragma: no cover
    _POLLIN = 0x001
    _POLLOUT = 0x004
    _POLLERR = 0x008
    _POLLHUP = 0x010

_POLL_ERROR_MASK = _POLLERR | _POLLHUP


# Pick a millisecond sleep once at import.  ``time.sleep_ms`` exists on
# MicroPython and CircuitPython; CPython falls back to seconds.
_native_sleep_ms = getattr(time, "sleep_ms", None)


def _sleep_ms(timeout_ms: int) -> None:
    """Sleep approximately *timeout_ms* milliseconds across runtimes."""
    if _native_sleep_ms is not None:
        _native_sleep_ms(timeout_ms)
    else:
        time.sleep(timeout_ms / 1000.0)


class _SelectPollAdapter:
    """Wraps ``select.poll()`` so ``Runner.wait`` can call ``ipoll`` on
    every runtime.

    MicroPython and CircuitPython ship ``select.poll().ipoll`` which
    reuses one internal tuple and allocates nothing steady-state.
    CPython exposes only ``poll`` (returning a list of ``(fd, flags)``
    pairs).  The adapter dispatches to ``ipoll`` when present and to
    ``poll`` otherwise.  ``Runner.wait`` discards the iteration result
    either way — ``check`` re-gates dispatch on the next ``tick``.

    Built lazily inside ``Runner.wait`` so applications that never call
    ``wait`` pay nothing.
    """

    def __init__(self) -> None:
        import select

        self._poller = select.poll()
        self._ipoll = getattr(self._poller, "ipoll", None)

    def register(self, obj: object, eventmask: int) -> None:
        self._poller.register(obj, eventmask)

    def modify(self, obj: object, eventmask: int) -> None:
        self._poller.modify(obj, eventmask)

    def unregister(self, obj: object) -> None:
        self._poller.unregister(obj)

    def ipoll(self, timeout_ms: int) -> object:
        # pragma below: MicroPython and CircuitPython expose ``ipoll``
        # (allocation-free reused tuple); CPython does not, so the
        # ipoll-preferring branch is unreachable on the test runtime.
        if self._ipoll is not None:  # pragma: no cover
            return self._ipoll(timeout_ms)
        return self._poller.poll(timeout_ms)


class TaskHandle:
    """Handle returned by ``Runner.add()`` or ``add_periodic()``.

    Inspect state via the ``period_ms``, ``run_count``, and ``active``
    attributes.  Mutate via ``set_period()`` or ``remove()``.
    """

    def __init__(self, check_function: object | None,
                 handler_function: object,
                 period_ms: int | None,
                 next_due_ms: int | None,
                 run_count: int | None,
                 runner: "Runner",
                 service: object | None = None) -> None:
        self.check_function = check_function
        self.handler_function = handler_function
        self.period_ms = period_ms
        self.next_due_ms = next_due_ms
        self.run_count = run_count
        self.active = True
        self._runner = runner
        # Retained so ``Runner.wait`` can read the service's optional
        # ``io_socket`` / ``io_wants_read`` / ``io_wants_write`` and
        # ``next_deadline`` attributes each loop.  ``None`` for
        # callable-based or handler-only registrations.
        self.service = service

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
        poller: Optional poll-shaped object exposing
            ``register(obj, eventmask)`` / ``modify(obj, eventmask)`` /
            ``unregister(obj)`` / ``ipoll(timeout_ms)``.  Only consulted
            by ``wait``; the default ``select.poll`` adapter is built
            lazily on the first ``wait`` call that has a socket to
            register.  Tests pass ``FakePoller`` from
            ``chumicro_runner.testing``.
    """

    def __init__(self, ticks: object | None = None,
                 poller: object | None = None) -> None:
        self._entries = []
        self._pending = []
        self._ticking = False
        self._ticks = ticks if ticks is not None else _DEFAULT_TICKS
        self._poller = poller
        # id(sock) -> (sock, eventmask) for sockets currently in the
        # poll set.  ``_sync_poll_set`` diffs against this on every
        # ``wait`` so register / modify / unregister fire only on change.
        self._registered_interest: dict = {}

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
                becomes eligible.  Overrides the first period.
                Subsequent fires use *period_ms* if set.
            run_count: Optional number of times the handler may fire
                before auto-removing.  ``None`` means unlimited.
        """
        # ``service`` is the originating task object when registration was
        # object-based or "task-with-check + handler" — those are the
        # shapes that may also expose ``io_*`` / ``next_deadline`` for
        # ``Runner.wait``.  Pure callable / handler-only registrations
        # have no service to read.
        service: object | None = None
        if handler is not None:
            # Callable-based or handler-only.
            if task is not None and not callable(task):
                check_function = task.check
                service = task
            else:
                check_function = task  # callable or None (handler-only)
            handler_function = handler
        elif task is not None:
            # Object-based: must have .check() and .handle().
            check_function = task.check
            handler_function = task.handle
            service = task
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
            run_count, self, service=service,
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

        1. Check each entry (period gate, then check gate).
           Collect entries whose handlers should fire.
        2. Batch-fire all collected handlers.
        3. Decrement run counts and auto-remove exhausted entries.

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
                    # Advance: periodic tasks reschedule, one-shot tasks clear.
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

    def wait(self, now_ms: int) -> None:
        """Idle until a registered socket is ready or the next deadline arrives.

        Companion to ``tick()``.  The application calls it in its loop
        right after ``tick()`` to let the CPU sleep between events::

            while True:
                now_ms = runner.tick()
                runner.wait(now_ms)

        On each call ``wait``:

        1. Re-reads each entry's optional ``io_socket`` /
           ``io_wants_read`` / ``io_wants_write`` attributes and syncs
           the registered poll set on diff (register new sockets,
           modify changed interest, unregister stale sockets).
        2. Computes the wait timeout as the minimum of every entry's
           ``next_due_ms`` and every service's
           ``next_deadline(now_ms)``, minus *now_ms*.
        3. Blocks in ``ipoll(timeout_ms)`` over the registered poll set
           if any socket is registered, otherwise sleeps the timeout
           via ``time.sleep_ms``.  Returns immediately if no timeout
           source applies or the next deadline is already in the past.

        For each ipoll event whose mask carries POLLERR or POLLHUP
        (socket error / hangup), looks up the registered service whose
        ``io_socket`` matches the polled object and calls its optional
        ``io_error(now_ms, eventmask)`` hook so the service can transition
        cleanly to a failure state.  Services without ``io_error``
        receive no notification; the runner ignores the error event
        and ``check`` re-gates dispatch on the next ``tick`` as usual.

        POLLIN / POLLOUT events are wake signals only -- ``check`` and
        ``next_deadline`` decide what runs.  Waking the loop and
        dispatching handlers stay separate concerns.

        Args:
            now_ms: Current tick, typically the value returned by the
                preceding ``tick()`` call.
        """
        self._sync_poll_set()
        timeout_ms = self._compute_timeout(now_ms)
        if timeout_ms is None or timeout_ms <= 0:
            return

        if self._registered_interest:
            if self._poller is None:
                # Lazy-build the default adapter and replay the current
                # poll-set onto it so it lines up with the bookkeeping
                # ``_sync_poll_set`` just produced.
                self._poller = _SelectPollAdapter()
                for sock, eventmask in self._registered_interest.values():
                    self._poller.register(sock, eventmask)
            for item in self._poller.ipoll(timeout_ms):
                # MicroPython / CircuitPython ipoll yields a reused
                # tuple ``(sock, eventmask)``; CPython poll().poll()
                # yields ``(fileno, eventmask)``.  Unpack into locals
                # before the next iteration in case the buffer rotates.
                obj = item[0]
                eventmask = item[1]
                if eventmask & _POLL_ERROR_MASK:
                    self._dispatch_io_error(obj, eventmask, now_ms)
        else:
            _sleep_ms(timeout_ms)

    def _dispatch_io_error(self, obj: object, eventmask: int, now_ms: int) -> None:
        """Find the registered service whose ``io_socket`` is *obj* and
        call its optional ``io_error(now_ms, eventmask)`` hook.

        No-op when no service matches (a stale poll registration we
        haven't observed yet) or the matched service doesn't expose
        ``io_error`` (it opted out of error notifications, the runner
        leaves it alone).
        """
        for entry in self._entries:
            service = entry.service
            if service is None:
                continue
            sock = getattr(service, "io_socket", None)
            if sock is None:
                continue
            if sock is obj or (
                isinstance(obj, int)
                and hasattr(sock, "fileno")
                and sock.fileno() == obj
            ):
                handler = getattr(service, "io_error", None)
                if handler is not None:
                    handler(now_ms, eventmask)
                return

    def _sync_poll_set(self) -> None:
        """Re-read each entry's ``io_*`` attributes and update the poll set.

        Registers sockets newly wanted, modifies on changed interest,
        unregisters sockets that have gone away or dropped to no
        interest.  Idempotent: a no-change loop touches the poller
        zero times.
        """
        registered = self._registered_interest
        # IDs of sockets wanted this loop.  Second pass below diffs
        # against the registered set to unregister anything that has
        # gone away.
        wanted_now = []
        poller = self._poller
        for entry in self._entries:
            service = entry.service
            if service is None:
                continue
            sock = getattr(service, "io_socket", None)
            if sock is None:
                continue
            eventmask = 0
            if getattr(service, "io_wants_read", False):
                eventmask |= _POLLIN
            if getattr(service, "io_wants_write", False):
                eventmask |= _POLLOUT
            if eventmask == 0:
                continue
            sock_id = id(sock)
            wanted_now.append(sock_id)
            previous = registered.get(sock_id)
            if previous is None:
                registered[sock_id] = (sock, eventmask)
                if poller is not None:
                    poller.register(sock, eventmask)
            elif previous[1] != eventmask:
                registered[sock_id] = (sock, eventmask)
                if poller is not None:
                    poller.modify(sock, eventmask)

        # Drop sockets no service wants any more.
        if len(registered) > len(wanted_now):
            stale = [sid for sid in registered if sid not in wanted_now]
            for sid in stale:
                sock, _ = registered.pop(sid)
                if poller is not None:
                    try:
                        poller.unregister(sock)
                    except (KeyError, OSError):
                        # Poll-set divergence (socket already closed at
                        # the OS level, or unregistered out-of-band):
                        # the registered_interest dict is the source of
                        # truth, keep it consistent and move on.
                        pass

    def _compute_timeout(self, now_ms: int) -> int | None:
        """Return ``min(every next_due_ms, every next_deadline) - now_ms``.

        ``None`` when no entry contributes a deadline.  May be zero or
        negative when the nearest deadline has already passed.
        """
        ticks_diff = self._ticks.ticks_diff
        nearest = None
        for entry in self._entries:
            if entry.next_due_ms is not None:
                delta = ticks_diff(entry.next_due_ms, now_ms)
                if nearest is None or delta < nearest:
                    nearest = delta
            service = entry.service
            if service is None:
                continue
            deadline_fn = getattr(service, "next_deadline", None)
            if deadline_fn is None:
                continue
            deadline = deadline_fn(now_ms)
            if deadline is None:
                continue
            delta = ticks_diff(deadline, now_ms)
            if nearest is None or delta < nearest:
                nearest = delta
        return nearest

    def _initial_next_due_ms(self, start_after_ms: int | None,
                             period_ms: int | None) -> int | None:
        """Return the initial ``next_due_ms``.  ``start_after_ms`` wins over ``period_ms``."""
        delay_ms = start_after_ms if start_after_ms is not None else period_ms
        if delay_ms is None:
            return None
        now_ms = self._ticks.ticks_ms()
        return self._ticks.ticks_add(now_ms, delay_ms)

    def _remove(self, handle: TaskHandle) -> None:
        """Remove *handle* from the runner."""
        handle.active = False
        try:
            self._entries.remove(handle)
        except ValueError:
            pass
