"""Tick-based scheduler for the ChuMicro libraries.

Register work with a ``Runner``, then call ``tick()`` in a loop.
Each ``tick()`` captures the current time once, checks every
registered task, and fires the handlers whose gates have passed.

Two registration shapes are accepted: object-based (``.check`` +
``.handle`` methods) and handler-only (fires every tick, or per
period if one is set).  See ``Runner.add`` for signatures.
``add_periodic`` is the periodic shortcut; ``add_generator`` drives
a linear generator flow.

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
# a service's ``io_interest(now_ms)`` bitmask into a poll eventmask
# without importing ``select`` on every loop.  The
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

# Poll-interest bits a service returns from ``io_interest(now_ms) -> int``.
# One bitmask replaces the paired ``io_wants_read`` / ``io_wants_write``
# hooks: ``Runner.wait`` reads it once per socket-bearing service each
# sweep and maps ``IO_READ`` -> ``POLLIN`` / ``IO_WRITE`` -> ``POLLOUT``
# with int math.  The values ARE the duck-typed contract — a service
# builds its mask from these (re-exported at ``chumicro_runner.IO_READ``
# / ``.IO_WRITE``) and never imports the runner to do it, so the numbers
# are pinned here and mirrored as literals wherever a service can't take
# the dependency edge.
IO_READ = 1
IO_WRITE = 2


class ReentrantTickError(RuntimeError):
    """Raised when ``tick()`` runs while a ``tick()`` is already in progress.

    A handler that calls ``runner.tick()`` re-enters the reactor mid-dispatch
    and would corrupt the shared pending-handler walk.  Re-entering the
    reactor is framework misuse (a structural programming error), not a
    service fault, so it propagates past ``tick()``'s handler-fault
    isolation rather than being counted in ``handler_errors``.  Subclasses
    ``RuntimeError`` so callers already catching ``RuntimeError`` keep
    working.
    """


# Pick a millisecond sleep once at import.  ``time.sleep_ms`` exists on
# MicroPython and CircuitPython; CPython falls back to seconds.
_native_sleep_ms = getattr(time, "sleep_ms", None)


def _pollable_of(io_socket: object) -> object:
    """Return the object ``select.poll`` can register for *io_socket*.

    Adapter wrappers from ``chumicro_sockets`` expose the runtime's
    pollable on ``.sock``; bare sockets pass through.  The unwrap lives
    here — at the one consumer — so a service's ``io_socket`` may
    return either shape and no producer has to remember the wrapper
    convention (six producer-side unwraps were audited into existence
    the hard way; a missed one hands the wrapper to ``poll.register``,
    which raises ``OSError`` on MicroPython).
    """
    return getattr(io_socket, "sock", io_socket)


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
        # ``io_socket`` (a property, so a live getattr each loop is
        # allocation-free) and ``next_deadline`` / ``io_error``.  ``None``
        # for handler-only registrations.
        self.service = service
        # The service's bound ``io_interest`` method, captured once here
        # rather than getattr-ed every sweep: ``io_interest`` is a method,
        # so a per-sweep ``getattr`` would allocate a fresh bound-method
        # object on the ``_sync_poll_set`` hot path.  Caching it (the same
        # way ``check_function`` / ``handler_function`` are cached) keeps
        # that sweep allocation-free.  ``None`` when the service exposes no
        # poll interest (or for handler-only registrations).
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

    Captures ``ticks_ms()`` once per ``tick()`` call and passes the
    shared timestamp to every due component.  Registration paths are
    documented on ``add()`` and ``add_periodic()``.  A handler that
    raises ``Exception`` is isolated: ``tick()`` counts it in
    ``handler_errors``, reports it to the optional ``on_handler_error``
    callback, and keeps firing the other due handlers, so one faulting
    service can't stop the reactor.  A handler that re-enters ``tick()``
    is the exception: it raises ``ReentrantTickError`` and propagates,
    since re-entering the reactor is framework misuse, not a service
    fault.

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
            handler raises ``Exception`` during ``tick()``.  Lets the
            app log the fault, remove the faulting task via
            ``handle.remove()``, or re-raise to fail fast.  A callback
            that itself raises is swallowed and counted, never
            propagated.
    """

    def __init__(self, ticks: object | None = None,
                 poller: object | None = None,
                 on_handler_error: object | None = None) -> None:
        self._entries = []
        self._pending = []
        self._ticking = False
        # Count of handler exceptions tick() has isolated, plus any
        # raised by the on_handler_error callback itself.  A climbing
        # count is the app's signal that a service is failing.
        self.handler_errors = 0
        self._on_handler_error = on_handler_error
        self._ticks = ticks if ticks is not None else _DEFAULT_TICKS
        # ``wait`` sleeps the idle timeout through the tick source when it
        # exposes ``sleep_ms``, falling back to the module ``_sleep_ms``.
        # Sleeping is the same time dependency as reading the clock: a
        # ``FakeTicks`` advances its own clock instead of burning wall
        # time.  Cached here so the socket-less ``wait`` path stays
        # allocation-free (no per-call ``getattr``).
        self._sleep_ms = getattr(self._ticks, "sleep_ms", _sleep_ms)
        self._poller = poller
        # id(sock) -> [sock, registered_mask, sweep_mask, sweep_generation]
        # for sockets in the poll set.  ``_sync_poll_set`` reuses these
        # slots in place on every ``wait`` — re-stamping the generation
        # and re-ORing the wanted mask — so a steady-state sync allocates
        # nothing and calls the poller only when a mask changed.
        # ``registered_mask`` is what the poller currently holds,
        # ``sweep_mask`` is the interest accumulated this sweep, and
        # ``sweep_generation`` marks the last sweep that touched the slot
        # so sockets no service wants any more fall out.
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
        # ``service`` is the originating task object when registration
        # was object-based — the shape that may also expose ``io_socket`` /
        # ``io_interest`` / ``io_error`` / ``next_deadline`` for
        # ``Runner.wait``.  Handler-only registrations have no service to
        # read.  ``io_interest`` (a method) is captured once here so the
        # per-sweep poll-set sync never getattr-allocates a bound method.
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

        *gen* is a freshly constructed generator object — call the
        generator function once at the call site so its arguments are
        captured (``runner.add_generator(echo_run(host, port, radio))``),
        but do not advance it yourself.  This method primes it, sending
        ``None`` into its first ``yield``; a generator already advanced
        past that yield would have its first wait silently skipped.

        The generator suspends by ``yield``-ing a duck-typed wait
        object — anything exposing ``io_socket`` / ``io_interest(now_ms)``
        / ``next_deadline``.  The runner reads those
        each ``wait()`` to register the socket with ipoll, and resumes
        the generator via ``.send(now_ms)`` once the socket is ready or
        the deadline elapses.  Sequential I/O state machines that would
        otherwise need an explicit per-state ``handle`` shape collapse
        to a top-to-bottom generator body.

        The returned ``GeneratorHandle`` carries ``.done`` (False until
        the generator finishes) and ``.cancel()`` (stop early, firing
        any ``finally`` blocks).  The wrapper self-removes from the
        runner on ``StopIteration`` so a finished generator does not
        linger as a dead entry.

        The generator machinery is imported lazily on the first call so
        an app that never registers a generator does not load it.  Make
        that first call at startup rather than mid-loop, so the one-time
        import does not land on a latency-sensitive tick.

        Args:
            gen: A freshly constructed generator object that has not been
                advanced.  This method primes it to its first yield
                before returning.
        """
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
                tick that fired it — at least *period_ms* between
                fires, drifting by the tick's lateness.
        """
        if period_ms is None:
            raise ValueError("period_ms is required for add_periodic")
        return self.add(
            handler=handler, period_ms=period_ms,
            start_after_ms=start_after_ms, run_count=run_count,
            preserve_phase=preserve_phase,
        )

    def tick(self) -> int:
        """Capture time, check tasks, then batch-fire handlers.

        1. Check each entry (period gate, then check gate).
           Collect entries whose handlers should fire.
        2. Batch-fire all collected handlers.
        3. Decrement run counts and auto-remove exhausted entries.

        A ``check`` function must not add or remove runner tasks: phase 1
        walks the entry list in place, so a task added or removed from
        inside a check is skipped or shifts a neighbor out of this tick's
        scan.  Mutate the task set from a handler instead — phase 2 fires
        handlers off a separate batched list, so ``add`` and
        ``handle.remove()`` from a handler are safe.

        A handler raising ``Exception`` is isolated: the error is
        counted in ``handler_errors``, reported to the optional
        ``on_handler_error`` callback, and the remaining due handlers
        still fire this tick.  ``KeyboardInterrupt`` / ``SystemExit`` /
        ``GeneratorExit`` are not ``Exception`` subclasses, so they
        still propagate and stop the loop.  A handler that re-enters
        ``tick()`` raises ``ReentrantTickError``, which propagates past
        the isolation because re-entering the reactor is framework
        misuse, not a service fault.

        Returns:
            The tick timestamp used this cycle.

        Raises:
            ReentrantTickError: A handler called ``tick()`` while this
                ``tick()`` was already running.
        """
        # Re-entrancy guard: a handler calling tick() on this runner
        # would corrupt the shared _pending list mid-iteration. Raise
        # ReentrantTickError, which the dispatch loop below re-raises
        # past the handler-fault isolation so the misuse surfaces loudly
        # instead of being silently counted (no per-tick allocation).
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
                        # Advance from the previous deadline in whole
                        # periods so fires stay aligned to the original
                        # schedule; a stall longer than one period skips
                        # the missed fires instead of bursting to catch
                        # up.  Constant-time and allocation-free.
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
                    # A handler re-entered tick(). That is framework
                    # misuse, not a service fault, so let it propagate
                    # loudly instead of counting it. The outer finally
                    # still clears _pending and _ticking on the way out.
                    raise
                except Exception as error:  # noqa: BLE001
                    # Isolate a faulting handler so one service's
                    # exception can't kill the reactor or skip the other
                    # handlers gated this tick.  KeyboardInterrupt /
                    # SystemExit / GeneratorExit are not Exception
                    # subclasses and still propagate.  ``wait()``'s
                    # io_error delivery funnels its faults through the
                    # same helper, so the count/report/swallow policy is
                    # one lane, not two.
                    self._record_handler_fault(entry, error)
                if entry.run_count is not None:
                    entry.run_count -= 1
                    if entry.run_count <= 0:
                        self._remove(entry)

            return now_ms
        finally:
            # Clear unconditionally: a handler that raised must not leave
            # already-fired entries in _pending to re-fire on the next
            # tick.
            self._pending.clear()
            self._ticking = False

    def wait(self, now_ms: int) -> None:
        """Idle until a registered socket is ready or the next deadline arrives.

        Companion to ``tick()``.  The application calls it in its loop
        right after ``tick()`` to let the CPU sleep between events::

            while True:
                now_ms = runner.tick()
                runner.wait(now_ms)

        On each call ``wait``:

        1. Re-reads each entry's optional ``io_socket`` and
           ``io_interest(now_ms)`` bitmask and syncs the registered poll
           set on diff (register new sockets, modify changed interest,
           unregister stale sockets).
        2. Computes the wait timeout as the minimum of every entry's
           ``next_due_ms`` and every service's
           ``next_deadline(now_ms)``, minus *now_ms*.
        3. Blocks in ``ipoll(timeout_ms)`` over the registered poll set
           if any socket is registered — indefinitely when no entry
           contributes a deadline, so a purely socket-driven service
           set parks the CPU until an event fires.  With no sockets
           registered, sleeps the timeout: the socket-less sleep
           delegates to the injected tick source's ``sleep_ms`` when it
           has one (so a ``FakeTicks`` advances its own clock instead
           of burning wall time), otherwise the runtime
           ``time.sleep_ms`` / ``time.sleep``.  Returns immediately
           when the next deadline is already due, or when there is
           neither a socket nor a deadline to wait on.

        For each ipoll event whose mask carries POLLERR or POLLHUP
        (socket error / hangup), looks up the registered service whose
        ``io_socket`` matches the polled object and calls its optional
        ``io_error(now_ms, eventmask)`` hook so the service can transition
        cleanly to a failure state.  That delivery runs on the one
        snapshot-iterated, ``_record_handler_fault``-isolated lane the
        tick handlers use, so an ``io_error`` that faults (or a generator
        service that lets the throw propagate) is counted and contained,
        never able to escape ``wait()`` or corrupt the entry list it
        dispatches over.  Services without ``io_error`` receive no
        notification; the runner ignores the error event and ``check``
        re-gates dispatch on the next ``tick`` as usual.

        POLLIN / POLLOUT events are wake signals only -- ``check`` and
        ``next_deadline`` decide what runs.  Waking the loop and
        dispatching handlers stay separate concerns.

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
                # poll-set onto it so it lines up with the bookkeeping
                # ``_sync_poll_set`` just produced.
                self._poller = _SelectPollAdapter()
                for slot in self._registered_interest.values():
                    self._poller.register(slot[0], slot[1])
            if timeout_ms is None:
                # Sockets registered but no deadline anywhere: park in
                # the poller until an event fires.  -1 blocks
                # indefinitely on every runtime's poll/ipoll.
                timeout_ms = -1
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
            if timeout_ms is None:
                # Neither sockets nor deadlines: nothing can wake a
                # sleep, so return and let the caller's loop proceed.
                return
            self._sleep_ms(timeout_ms)

    def run_until(self, predicate: object | None = None, *,
                  timeout_ms: int | None = None) -> bool:
        """Drive ``tick()`` + ``wait()`` until *predicate* is truthy.

        The one-call form of the standard ``while ...: tick(); wait()``
        loop that every demo would otherwise hand-roll::

            handle = runner.add_generator(echo_run(...))
            runner.run_until(handle)

        Ticks once, then loops: checks *predicate*, checks the timeout,
        then idles in ``wait()`` until the next event or deadline.

        Args:
            predicate: Either a generator handle (anything exposing
                ``done``) — the loop runs until it finishes, and if the
                task died (``handle.error`` set) the error is re-raised
                here so a demo fails loudly instead of exiting clean —
                or a zero-argument callable checked after each tick; the
                loop returns ``True`` once it is truthy.  ``None`` never
                completes on its own (pair with *timeout_ms*: the
                bare-timeout form reads as "run for this long", e.g. a
                QoS-ack drain window).
            timeout_ms: Optional budget, checked between ticks against the
                tick source.  Best-effort: if the loop is parked in
                ``wait()`` on a socket with no deadline, the timeout is
                only re-checked when an event wakes it, so give the runner
                a deadline source (a periodic task, a connector) when a
                hard bound matters.

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
        """Count and report one isolated handler / ``io_error`` fault.

        The single place both dispatch lanes — ``tick()``'s handler fire
        and ``wait()``'s ``io_error`` delivery — funnel a caught
        ``Exception``: bump ``handler_errors``, hand the fault to the
        optional ``on_handler_error`` callback, and swallow-and-count a
        callback that itself raises (so a buggy hook can't re-break the
        isolation it is reporting).  Folding both lanes onto this one
        wrapper is what closes the G1 asymmetry (an error lane hardened
        separately from the tick lane) structurally rather than by
        maintaining two copies of the policy.
        """
        self.handler_errors += 1
        on_error = self._on_handler_error
        if on_error is not None:
            try:
                on_error(entry, error)
            except Exception:  # noqa: BLE001
                self.handler_errors += 1

    def _dispatch_io_error(self, obj: object, eventmask: int, now_ms: int) -> None:
        """Deliver a POLLERR / POLLHUP to the faulted socket's service.

        Finds the registered service whose ``io_socket`` is *obj* (adapter
        wrappers unwrapped exactly as registration unwraps them; a CPython
        ``poll`` fileno matched through ``fileno()``) and calls its
        optional ``io_error(now_ms, eventmask)`` hook, isolated through the
        shared ``_record_handler_fault`` lane so a faulting hook — or a
        generator service that lets the thrown ``OSError`` propagate —
        is counted and contained instead of escaping ``wait()``.

        Iterates a **snapshot** (``tuple(self._entries)``): a generator
        service's ``io_error`` throws into its body, and an uncaught throw
        drops that service's entry from ``_entries`` mid-dispatch.
        Snapshotting makes the mutate-while-iterating class (RUN-2)
        structurally impossible rather than sidestepped by the single
        early ``return``.  This is not a steady-state path (it fires only
        on a socket error), so the snapshot copy is off the per-tick hot
        path the buffer audit protects.

        No-op when no service matches (a stale poll registration we have
        not observed yet) or the matched service exposes no ``io_error``
        (it opted out; the runner leaves it untouched).
        """
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
                # First match wins: the socket faulted once, one service
                # owns it, and the snapshot already guards the mutation
                # its io_error may cause.
                return

    def _sync_poll_set(self, now_ms: int) -> None:
        """Re-read each entry's ``io_socket`` / ``io_interest`` and update the poll set.

        Registers sockets newly wanted, modifies on changed interest,
        unregisters sockets that have gone away or dropped to no
        interest.  Idempotent: a no-change loop touches the poller zero
        times and allocates nothing.  The per-socket interest lives in
        the persistent ``_registered_interest`` slots, re-ORed in place
        and stamped with a per-sweep generation so a steady-state loop
        allocates no scratch container.
        """
        registered = self._registered_interest
        poller = self._poller
        generation = self._sweep_generation + 1
        self._sweep_generation = generation

        # Accumulate this sweep's wanted interest into each socket's
        # slot, OR-ing the eventmasks of every service that shares a
        # socket — a reader and a writer on one socket must both keep
        # their wake direction.  A new socket gets a slot; an existing
        # slot is re-stamped on first sight this sweep and OR-ed on
        # later sights, so no per-loop container is allocated.
        # ``wanted_count`` is the distinct sockets wanted this sweep,
        # used below to detect stale slots without a second pass.
        wanted_count = 0
        for entry in self._entries:
            interest_fn = entry.io_interest
            if interest_fn is None:
                # Handler-only entry, or a service exposing no poll
                # interest at all — nothing to register.
                continue
            sock = getattr(entry.service, "io_socket", None)
            if sock is None:
                continue
            # ``interest_fn`` is the service's cached bound ``io_interest``
            # method (bound once at ``add``), so this call allocates
            # nothing.  Map the returned bitmask to poll flags with int
            # math — one ``io_interest`` call replaces the two per-service
            # ``getattr`` the paired boolean hooks needed.
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

        # Reconcile the poller against each wanted slot: register a
        # socket whose registered mask is still 0, modify one whose
        # accumulated mask changed.  ``registered_mask`` tracks the
        # desired poll-set state even when ``poller is None`` (not yet
        # lazy-built), so the replay in ``wait`` lines up.
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
        if len(registered) > wanted_count:
            stale = [sid for sid in registered
                     if registered[sid][3] != generation]
            for sid in stale:
                slot = registered.pop(sid)
                if poller is not None:
                    try:
                        poller.unregister(slot[0])
                    except (KeyError, OSError, ValueError):
                        # Poll-set divergence (socket already closed at
                        # the OS level, or unregistered out-of-band): the
                        # registered_interest dict is the source of truth,
                        # keep it consistent and move on.  CPython's
                        # select.poll raises ValueError when the socket is
                        # closed (fileno() is -1) — a closed service socket
                        # is exactly this path, not an error.
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
