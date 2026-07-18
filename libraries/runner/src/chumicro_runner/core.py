"""Tick-based scheduler for the ChuMicro libraries.

Register work with a ``Runner``, then call ``tick()`` in a loop; each
``tick()`` captures the time once and fires the handlers whose gates
have passed.  The optional ``Runner.wait(now_ms)`` companion idles the
CPU between ticks.  Runs on CPython, MicroPython, and CircuitPython.
"""

# Imported eagerly, not lazily in ``Runner.__init__``: on MicroPython
# mount-mode a lazy import becomes an mpremote RPC that adds ~1 s per test.
import time

from chumicro_timing import ticks as _DEFAULT_TICKS

# Resolve the POSIX poll flags once at import so ``wait`` can map a
# service's io_interest bitmask to a poll eventmask without importing
# ``select`` each loop.  The numeric fallbacks match POSIX; every test
# runtime ships ``select``, so the pragma branch below is never reached.
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

# Poll-interest bits a service returns from ``io_interest(now_ms) -> int``.
# ``Runner.wait`` maps IO_READ -> POLLIN and IO_WRITE -> POLLOUT.  The
# values are a pinned contract: a service builds its mask from these
# without importing the runner, so keep the numbers stable.
IO_READ = 1
IO_WRITE = 2


class ReentrantTickError(RuntimeError):
    """Raised when ``tick()`` runs while another ``tick()`` is in progress.

    Re-entering the reactor from a handler is framework misuse, so this
    propagates past ``tick()``'s handler-fault isolation instead of being
    counted in ``handler_errors``.  Subclasses ``RuntimeError``.
    """


# Pick a millisecond sleep once at import.  ``time.sleep_ms`` exists on
# MicroPython and CircuitPython; CPython falls back to seconds.
_native_sleep_ms = getattr(time, "sleep_ms", None)


def _pollable_of(io_socket: object) -> object:
    # Adapter wrappers from chumicro_sockets hold the real pollable on
    # ``.sock``; a bare socket passes through unchanged.
    return getattr(io_socket, "sock", io_socket)


def _sleep_ms(timeout_ms: int) -> None:
    if _native_sleep_ms is not None:
        _native_sleep_ms(timeout_ms)
    else:
        time.sleep(timeout_ms / 1000.0)


class _SelectPollAdapter:
    """Wrap ``select.poll()`` so ``Runner.wait`` can call ``ipoll`` on every runtime."""

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
        # MicroPython / CircuitPython expose allocation-free ``ipoll``;
        # CPython does not, so this branch (pragma) is never hit in tests.
        if self._ipoll is not None:  # pragma: no cover
            return self._ipoll(timeout_ms)
        return self._poller.poll(timeout_ms)


class TaskHandle:
    """Handle returned by ``Runner.add()`` or ``add_periodic()``.

    Inspect state via the ``period_ms``, ``run_count``, ``preserve_phase``,
    and ``active`` attributes.  Mutate via ``set_period()`` or ``remove()``.
    """

    def __init__(self, check_function: object | None,
                 handler_function: object,
                 period_ms: int | None,
                 next_due_ms: int | None,
                 run_count: int | None,
                 runner: "Runner",
                 service: object | None = None,
                 preserve_phase: bool = False,
                 io_interest: object | None = None) -> None:
        self.check_function = check_function
        self.handler_function = handler_function
        self.period_ms = period_ms
        self.next_due_ms = next_due_ms
        self.run_count = run_count
        self.preserve_phase = preserve_phase
        self.active = True
        self._runner = runner
        # Retained so ``Runner.wait`` can read the service's optional
        # io_socket / next_deadline / io_error hooks (None if handler-only).
        self.service = service
        # The service's bound io_interest method, cached once so the
        # per-sweep poll sync never re-allocates a bound method each loop.
        self.io_interest = io_interest

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

    Captures ``ticks_ms()`` once per ``tick()`` and passes that shared
    timestamp to every due task.  A handler that raises is isolated and
    counted in ``handler_errors`` so one faulting service can't stop the
    reactor.  Registration is documented on ``add()`` and ``add_periodic()``.

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
        on_handler_error: Optional callback
            ``on_handler_error(handle, exception)`` invoked when a
            handler raises during ``tick()``.  Lets the app log the fault,
            remove the faulting task, or re-raise to fail fast.  A callback
            that itself raises is swallowed and counted.
    """

    def __init__(self, ticks: object | None = None,
                 poller: object | None = None,
                 on_handler_error: object | None = None) -> None:
        self._entries = []
        self._pending = []
        self._ticking = False
        # Count of handler exceptions tick() isolated (plus any raised by
        # the on_handler_error callback); a rising count means trouble.
        self.handler_errors = 0
        self._on_handler_error = on_handler_error
        self._ticks = ticks if ticks is not None else _DEFAULT_TICKS
        # ``wait`` sleeps through the tick source's ``sleep_ms`` when it has
        # one (so a FakeTicks advances its own clock), else the module
        # ``_sleep_ms``.  Cached so the socket-less wait path stays alloc-free.
        self._sleep_ms = getattr(self._ticks, "sleep_ms", _sleep_ms)
        self._poller = poller
        # id(sock) -> [sock, registered_mask, sweep_mask, sweep_generation]
        # for each socket in the poll set.  ``_sync_poll_set`` reuses these
        # slots in place every ``wait`` (re-stamping generation, re-ORing
        # the wanted mask) so a steady-state sync allocates nothing.
        self._registered_interest: dict = {}
        self._sweep_generation = 0

    def add(self, task: object | None = None,
            handler: object | None = None,
            period_ms: int | None = None,
            start_after_ms: int | None = None,
            run_count: int | None = None,
            preserve_phase: bool = False) -> TaskHandle:
        """Register a task with the runner.

        **Object-based** (task only): *task* must have
        ``.check(now_ms) -> bool`` and ``.handle(now_ms)`` methods.

        **Callable-based** (task + handler): *task* is a callable
        ``check_function(now_ms) -> bool`` that gates ``handler(now_ms)``.

        **Handler-only** (handler, no task): ``handler(now_ms)`` fires
        on every tick (or per period if *period_ms* is set).

        Returns a ``TaskHandle`` for runtime mutation.

        Args:
            task: Object with ``.check()`` and ``.handle()``.
                Mutually exclusive with *handler*.
            handler: Callable ``handler(now_ms)`` fired on schedule
                (pair with *period_ms* / *run_count*).  Mutually
                exclusive with *task*.
            period_ms: Optional interval in milliseconds.
            start_after_ms: Optional initial delay before the task
                becomes eligible.  Overrides the first period.
                Subsequent fires use *period_ms* if set.
            run_count: Optional number of times the handler may fire
                before auto-removing.  ``None`` means unlimited.
            preserve_phase: When ``True``, a fired periodic reschedules
                from its previous deadline in whole periods, so fires
                stay aligned to the original schedule even when ticks
                run late; a stall longer than one period skips the
                missed fires rather than bursting.  When ``False``
                (default), the next fire is *period_ms* after the tick
                that fired it, guaranteeing at least *period_ms*
                between fires but drifting by the tick's lateness.
                Requires *period_ms*.
        """
        # ``service`` is the task object for object-based registrations (the
        # shape that may expose io_socket / io_interest / next_deadline for
        # Runner.wait); handler-only registrations have none.
        service: object | None = None
        io_interest: object | None = None
        if task is not None and handler is not None:
            raise ValueError(
                "Pass a task object OR a handler callable, not both "
                "(the separate check-plus-handler shape was removed; "
                "give the object a handle() or gate inside the handler)"
            )
        if task is not None:
            # Object-based: must have .check() and .handle().
            check_function = task.check
            handler_function = task.handle
            service = task
            # Optional poll surface; bound once (see TaskHandle.io_interest).
            io_interest = getattr(task, "io_interest", None)
        elif handler is not None:
            check_function = None
            handler_function = handler
        else:
            raise ValueError(
                "Provide a task object (with .check() and .handle()) "
                "or a handler callable"
            )

        if period_ms is not None and period_ms <= 0:
            raise ValueError("period_ms must be greater than zero")
        if run_count is not None and run_count <= 0:
            raise ValueError("run_count must be greater than zero")
        if preserve_phase and period_ms is None:
            raise ValueError("preserve_phase requires period_ms")

        next_due_ms = self._initial_next_due_ms(start_after_ms, period_ms)

        handle = TaskHandle(
            check_function, handler_function, period_ms, next_due_ms,
            run_count, self, service=service, preserve_phase=preserve_phase,
            io_interest=io_interest,
        )
        self._entries.append(handle)
        return handle

    def add_generator(self, gen: object) -> "GeneratorHandle":  # noqa: F821 - GeneratorHandle is lazy-imported in the body to keep _generator off the eager import path, so the return annotation is a forward-ref string
        """Register a generator-driven service with the runner.

        Pass a freshly constructed generator (call the generator function
        at the call site, e.g. ``runner.add_generator(echo_run(host, port))``,
        but do not advance it): this method primes it to its first
        ``yield``.  The generator suspends by ``yield``-ing a duck-typed
        wait object and resumes via ``.send(now_ms)`` once its socket is
        ready or its deadline elapses.  Returns a ``GeneratorHandle``
        carrying ``.done`` and ``.cancel()``.

        Args:
            gen: A freshly constructed generator object that has not been
                advanced.  This method primes it to its first yield
                before returning.
        """
        # Lazy import: an app that never registers a generator never loads
        # _generator.  Prefer the first call at startup, not a hot tick.
        from chumicro_runner._generator import (  # noqa: PLC0415
            GeneratorHandle,
            _GeneratorWrapper,
        )

        handle = GeneratorHandle()
        wrapper = _GeneratorWrapper(gen, handle)
        task_handle = self.add(wrapper)
        wrapper._task_handle = task_handle
        handle._wrapper = wrapper
        wrapper.start()
        return handle

    def add_periodic(self, handler: object, period_ms: int,
                     start_after_ms: int | None = None,
                     run_count: int | None = None,
                     preserve_phase: bool = False) -> TaskHandle:
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
            preserve_phase: When ``True``, fires stay aligned to the
                original schedule even when ticks run late (missed
                fires are skipped, never bursted).  When ``False``
                (default), each fire reschedules *period_ms* from the
                tick that fired it: at least *period_ms* between fires,
                drifting by the tick's lateness.
        """
        if period_ms is None:
            raise ValueError("period_ms is required for add_periodic")
        return self.add(
            handler=handler, period_ms=period_ms,
            start_after_ms=start_after_ms, run_count=run_count,
            preserve_phase=preserve_phase,
        )

    def tick(self) -> int:
        """Capture time, check tasks, then batch-fire due handlers.

        It runs in three passes: the first checks each entry (period gate,
        then check gate) and collects those whose handlers should fire; the
        second fires them; the third decrements run counts and auto-removes
        exhausted entries.

        A ``check`` function must not add or remove runner tasks (the first
        pass walks the entry list in place); mutate the task set from a
        handler instead, which the second pass fires from a separate batched
        list.  A handler that raises is isolated and counted in
        ``handler_errors``; one that re-enters ``tick()`` raises
        ``ReentrantTickError`` and propagates.

        Returns:
            The tick timestamp used this cycle.

        Raises:
            ReentrantTickError: A handler called ``tick()`` while this
                ``tick()`` was already running.
        """
        # Re-entrancy guard: a handler calling tick() would corrupt the
        # shared _pending walk, so surface it loudly instead of counting it.
        if self._ticking:
            raise ReentrantTickError(
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
                    if entry.period_ms is None:
                        entry.next_due_ms = None
                    elif entry.preserve_phase:
                        # Advance from the previous deadline in whole periods
                        # so fires stay aligned; a stall over one period skips
                        # the missed fires instead of bursting to catch up.
                        behind = ticks_diff(now_ms, entry.next_due_ms)
                        periods_missed = behind // entry.period_ms + 1
                        entry.next_due_ms = ticks_add(
                            entry.next_due_ms,
                            periods_missed * entry.period_ms,
                        )
                    else:
                        entry.next_due_ms = ticks_add(now_ms, entry.period_ms)

                # Check gate.
                if entry.check_function is not None:
                    if entry.check_function(now_ms):
                        pending.append(entry)
                else:
                    pending.append(entry)

            for entry in pending:
                try:
                    entry.handler_function(now_ms)
                except ReentrantTickError:
                    # Framework misuse, not a service fault: let it
                    # propagate loudly instead of counting it.
                    raise
                except Exception as error:  # noqa: BLE001
                    # Isolate a faulting handler so one service can't stop
                    # the reactor.  KeyboardInterrupt / SystemExit /
                    # GeneratorExit are not Exceptions and still propagate.
                    self._record_handler_fault(entry, error)
                if entry.run_count is not None:
                    entry.run_count -= 1
                    if entry.run_count <= 0:
                        self._remove(entry)

            return now_ms
        finally:
            # Clear unconditionally so a handler that raised does not leave
            # already-fired entries in _pending to re-fire next tick.
            self._pending.clear()
            self._ticking = False

    def wait(self, now_ms: int) -> None:
        """Idle until a registered socket is ready or the next deadline arrives.

        Companion to ``tick()``, called right after it so the CPU can
        sleep between events::

            while True:
                now_ms = runner.tick()
                runner.wait(now_ms)

        Each call syncs the poll set from every entry's ``io_socket`` /
        ``io_interest(now_ms)``, computes the timeout as the nearest of
        every ``next_due_ms`` and every service's ``next_deadline(now_ms)``,
        then blocks in ``ipoll`` over the registered sockets (indefinitely
        when no deadline contributes) or sleeps the timeout when no socket
        is registered.  Returns immediately when the nearest deadline is
        already due, or when there is neither a socket nor a deadline to
        wait on.

        For each ipoll event carrying POLLERR or POLLHUP, calls the owning
        service's optional ``io_error(now_ms, eventmask)`` hook, isolated
        on the same fault-counting lane as tick handlers.  POLLIN / POLLOUT
        events are wake signals only; ``check`` and ``next_deadline``
        decide what actually runs.

        Args:
            now_ms: Current tick, typically the value returned by the
                preceding ``tick()`` call.
        """
        self._sync_poll_set(now_ms)
        timeout_ms = self._compute_timeout(now_ms)
        if timeout_ms is not None and timeout_ms <= 0:
            return

        if self._registered_interest:
            if self._poller is None:
                # Lazy-build the default adapter and replay the current
                # poll set onto it to match ``_sync_poll_set``'s bookkeeping.
                self._poller = _SelectPollAdapter()
                for slot in self._registered_interest.values():
                    self._poller.register(slot[0], slot[1])
            if timeout_ms is None:
                # Sockets registered but no deadline: park in the poller
                # until an event fires.  -1 blocks indefinitely on poll/ipoll.
                timeout_ms = -1
            for item in self._poller.ipoll(timeout_ms):
                # ipoll yields (sock, eventmask) on MP/CircuitPython, but
                # (fileno, eventmask) on CPython.  Unpack before the next
                # iteration in case the reused buffer rotates.
                obj = item[0]
                eventmask = item[1]
                if eventmask & _POLL_ERROR_MASK:
                    self._dispatch_io_error(obj, eventmask, now_ms)
        else:
            if timeout_ms is None:
                # Neither sockets nor deadlines: nothing can wake a sleep,
                # so return and let the caller's loop proceed.
                return
            self._sleep_ms(timeout_ms)

    def run_until(self, predicate: object | None = None, *,
                  timeout_ms: int | None = None) -> bool:
        """Drive ``tick()`` + ``wait()`` until *predicate* is truthy.

        The one-call form of the standard ``while ...: tick(); wait()``
        loop::

            handle = runner.add_generator(echo_run(...))
            runner.run_until(handle)

        Ticks once, then loops: checks *predicate*, checks the timeout,
        then idles in ``wait()`` until the next event or deadline.

        Args:
            predicate: A generator handle (anything exposing ``done``), in
                which case the loop runs until it finishes and re-raises
                ``handle.error`` if the task died; or a zero-argument
                callable checked after each tick, returning ``True`` once
                it is truthy.  ``None`` never completes on its own (pair
                with *timeout_ms*).
            timeout_ms: Optional budget, checked between ticks against the
                tick source.  Best-effort: while parked in ``wait()`` on a
                socket with no deadline it is only re-checked on the next
                wake, so give the runner a deadline source when a hard
                bound matters.

        Returns:
            ``True`` when *predicate* became truthy (or the handle
            finished cleanly), ``False`` on timeout.

        Raises:
            BaseException: The handle form re-raises ``handle.error``
                when the awaited task died.
        """
        handle = None
        if predicate is not None and not callable(predicate):
            handle = predicate
            predicate = None
        ticks = self._ticks
        deadline = None
        if timeout_ms is not None:
            deadline = ticks.ticks_add(ticks.ticks_ms(), timeout_ms)
        while True:
            now_ms = self.tick()
            if handle is not None and handle.done:
                error = getattr(handle, "error", None)
                if error is not None:
                    raise error
                return True
            if predicate is not None and predicate():
                return True
            if deadline is not None and ticks.ticks_diff(now_ms, deadline) >= 0:
                return False
            self.wait(now_ms)

    def _record_handler_fault(self, entry: "TaskHandle", error: Exception) -> None:
        # Both dispatch lanes (tick handler fire, wait's io_error delivery)
        # funnel a caught Exception here: count it, report to the optional
        # callback, and swallow-and-count a callback that itself raises.
        self.handler_errors += 1
        on_error = self._on_handler_error
        if on_error is not None:
            try:
                on_error(entry, error)
            except Exception:  # noqa: BLE001
                self.handler_errors += 1

    def _dispatch_io_error(self, obj: object, eventmask: int, now_ms: int) -> None:
        # Snapshot the entries: a generator service's io_error throws into
        # its body, and an uncaught throw drops its entry from _entries
        # mid-dispatch, so iterating a copy keeps this loop safe.
        for entry in tuple(self._entries):
            service = entry.service
            if service is None:
                continue
            sock = getattr(service, "io_socket", None)
            if sock is None:
                continue
            sock = _pollable_of(sock)
            if sock is obj or (
                isinstance(obj, int)
                and hasattr(sock, "fileno")
                and sock.fileno() == obj
            ):
                handler = getattr(service, "io_error", None)
                if handler is not None:
                    try:
                        handler(now_ms, eventmask)
                    except Exception as error:  # noqa: BLE001
                        self._record_handler_fault(entry, error)
                # First match wins: one service owns the socket, and the
                # snapshot already guards any mutation its io_error causes.
                return

    def _sync_poll_set(self, now_ms: int) -> None:
        # Re-read each entry's io_socket / io_interest and reconcile the
        # poll set: register sockets newly wanted, modify on changed
        # interest, unregister those gone away.  Idempotent, and a
        # no-change loop touches the poller zero times and allocates nothing.
        registered = self._registered_interest
        poller = self._poller
        generation = self._sweep_generation + 1
        self._sweep_generation = generation

        # Accumulate this sweep's wanted interest into each socket's slot,
        # OR-ing the masks of every service sharing a socket (a reader and a
        # writer on one socket both keep their wake direction).  wanted_count
        # is the distinct sockets seen, used below to spot stale slots.
        wanted_count = 0
        for entry in self._entries:
            interest_fn = entry.io_interest
            if interest_fn is None:
                # Handler-only entry, or a service with no poll interest:
                # nothing to register.
                continue
            sock = getattr(entry.service, "io_socket", None)
            if sock is None:
                continue
            # interest_fn is the cached bound io_interest method, so this
            # call allocates nothing.  Map its bitmask to poll flags below.
            interest = interest_fn(now_ms)
            eventmask = 0
            if interest & IO_READ:
                eventmask |= _POLLIN
            if interest & IO_WRITE:
                eventmask |= _POLLOUT
            if eventmask == 0:
                continue
            sock = _pollable_of(sock)
            sock_id = id(sock)
            slot = registered.get(sock_id)
            if slot is None:
                registered[sock_id] = [sock, 0, eventmask, generation]
                wanted_count += 1
            elif slot[3] != generation:
                slot[2] = eventmask
                slot[3] = generation
                wanted_count += 1
            else:
                slot[2] |= eventmask

        # Reconcile the poller against each wanted slot: register a socket
        # whose mask is still 0, modify one whose mask changed.  The slot
        # tracks desired state even when poller is None, so wait's replay lines up.
        for sock_id in registered:
            slot = registered[sock_id]
            if slot[3] != generation:
                continue
            sweep_mask = slot[2]
            if slot[1] != sweep_mask:
                if poller is not None:
                    if slot[1] == 0:
                        poller.register(slot[0], sweep_mask)
                    else:
                        poller.modify(slot[0], sweep_mask)
                slot[1] = sweep_mask

        # Drop sockets no service wants any more (untouched this sweep).
        # An explicit loop, not a comprehension: on MP a comprehension boxes
        # its free vars into heap cells, churning 64 B on every socket-less wait.
        if len(registered) > wanted_count:
            stale = []
            for sid in registered:
                if registered[sid][3] != generation:
                    stale.append(sid)
            for sid in stale:
                slot = registered.pop(sid)
                if poller is not None:
                    try:
                        poller.unregister(slot[0])
                    except (KeyError, OSError, ValueError):
                        # Poll-set divergence: the socket was already closed
                        # (CPython raises ValueError on a closed fileno) or
                        # unregistered out-of-band.  Not an error here.
                        pass

    def _compute_timeout(self, now_ms: int) -> int | None:
        """Nearest of every ``next_due_ms`` / ``next_deadline`` minus *now_ms*, or ``None``."""
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
        handle.active = False
        try:
            self._entries.remove(handle)
        except ValueError:
            pass
