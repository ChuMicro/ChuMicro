"""``Runner`` and ``TaskHandle``: run registered jobs from one loop and sleep between them.

Register work with a ``Runner``, then call ``tick()`` on every pass of the loop to run what
is due, and ``wait()`` to idle the CPU until the next job is due.
"""

# Eager import: on MicroPython mount-mode a lazy import becomes an mpremote RPC that adds ~1 s per test.
import time

# Resolve poll flags once at import; the fallback constants match POSIX for a runtime without select.
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

# Poll-interest bits a service returns from io_interest(); a pinned contract, so keep the numbers stable.
IO_READ = 1
IO_WRITE = 2


class ReentrantTickError(RuntimeError):
    """Raised by ``Runner.tick`` when a job calls ``tick()`` on the runner that is running it."""


# time.sleep_ms exists on MicroPython and CircuitPython; CPython has only time.sleep, in seconds.
_native_sleep_ms = getattr(time, "sleep_ms", None)


def _pollable_of(io_socket: object) -> object:
    # chumicro_sockets adapters hold the real pollable on .sock; a bare socket passes through.
    return getattr(io_socket, "sock", io_socket)


def _fileno_of(pollable: object) -> int | None:
    # CPython keys its poll set by file descriptor and reads that descriptor back off
    # the object at unregister time, when a closed socket answers -1.  Record the
    # descriptor while the socket is still open so the drop sweep has a valid key.
    # MicroPython and CircuitPython key by object and never need this.
    fileno = getattr(pollable, "fileno", None)
    if fileno is None:
        return None
    try:
        descriptor = fileno()
    except (OSError, ValueError):  # pragma: no cover - closed before its first sweep
        return None
    return descriptor if descriptor >= 0 else None


def _sleep_ms(timeout_ms: int) -> None:
    if _native_sleep_ms is not None:
        _native_sleep_ms(timeout_ms)
    else:
        time.sleep(timeout_ms / 1000.0)


class _SelectPollAdapter:
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
        # MicroPython and CircuitPython expose allocation-free ipoll; CPython has only poll.
        if self._ipoll is not None:  # pragma: no cover
            return self._ipoll(timeout_ms)
        return self._poller.poll(timeout_ms)


class TaskHandle:
    """The handle ``Runner.add`` and ``Runner.add_periodic`` return for one registered job.

    Keep it to change the job's period with ``set_period`` or unregister it with ``remove``,
    from anywhere in the program, a job included.

    Attributes:
        period_ms: Milliseconds between runs, or None for a job that runs on every tick.
            Change it with ``set_period``.  Assigning it directly leaves the next run where
            it was.
        run_count: Runs left before the runner removes the job, or None for no limit.
        active: True while the job is registered, False once it has been removed.
        service: The object passed to ``Runner.add`` as ``task``, or None for a handler.
    """

    def __init__(self, check_function: object | None,
                 handler_function: object,
                 period_ms: int | None,
                 next_due_ms: int | None,
                 run_count: int | None,
                 runner: "Runner",
                 service: object | None = None,
                 preserve_phase: bool = False,
                 io_interest: object | None = None,
                 next_deadline: object | None = None) -> None:
        self.check_function = check_function
        self.handler_function = handler_function
        self.period_ms = period_ms
        self.next_due_ms = next_due_ms
        self.run_count = run_count
        self.preserve_phase = preserve_phase
        self.active = True
        self._runner = runner
        self.service = service
        # Cache the bound io_interest / next_deadline methods so the per-sweep
        # poll sync and the per-wait timeout scan never re-allocate them.
        self.io_interest = io_interest
        self.next_deadline = next_deadline

    def set_period(self, period_ms: int | None, now_ms: int | None = None) -> None:
        """Give the job a new period, or take its period away.

        With a period, the next run lands ``period_ms`` after ``now_ms``.  Without one, the
        job runs on every tick.

        Args:
            period_ms: The new interval in milliseconds, or None to run the job on every tick.
            now_ms: The tick to count the new period from.  Inside a job, pass the ``now_ms``
                the job received.  Defaults to a fresh clock reading.

        Raises:
            ValueError: ``period_ms`` is 0 or less.
        """
        if period_ms is not None and period_ms <= 0:
            raise ValueError("period_ms must be greater than zero")
        self.period_ms = period_ms
        if period_ms is not None:
            ticks = self._runner._ticks
            if now_ms is None:
                now_ms = ticks.ticks_ms()
            self.next_due_ms = ticks.ticks_add(now_ms, period_ms)
        else:
            self.next_due_ms = None

    def remove(self) -> None:
        """Unregister the job, so later ticks skip it, and set ``active`` to False.

        Calling it on a job already removed does nothing.
        """
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
    """A scheduler that runs every registered job from one ``while True:`` loop.

    Register work once with ``add``, ``add_periodic``, or ``add_generator``.  Then call
    ``now_ms = runner.tick()`` and ``runner.wait(now_ms)`` on every pass of the loop.
    ``tick`` runs whatever is due, and ``wait`` sleeps until the next job is due or a
    watched socket is ready.  A job that raises is caught and counted, and the loop goes on.

    Args:
        ticks: The clock every period and deadline is measured on: an object with
            ``ticks_ms()``, ``ticks_add()``, and ``ticks_diff()``.  Defaults to
            ``chumicro_timing.ticks``.  When ``wait`` has no socket to watch, a clock with a
            ``sleep_ms()`` method does the sleeping, which is how ``FakeTicks`` from
            ``chumicro_timing.testing`` makes a test idle instantly.
        poller: The object ``wait`` watches sockets through, with ``register``, ``modify``,
            ``unregister``, and ``ipoll``.  Defaults to ``select.poll()``, built on the first
            ``wait`` that has a socket to watch.
        on_handler_error: A function called as ``on_handler_error(task_handle, exception)``
            each time a job raises, after the runner counts the fault.  Without one, a
            failing job prints nothing.

    Attributes:
        handler_errors: How many exceptions the runner has caught from jobs, from
            ``io_error`` hooks, and from ``on_handler_error`` itself.
        last_handler_error: The most recent of those exceptions, or None while there has
            been none.
    """

    def __init__(self, ticks: object | None = None,
                 poller: object | None = None,
                 on_handler_error: object | None = None) -> None:
        self._entries = []
        self._pending = []
        self._ticking = False
        self.handler_errors = 0
        self.last_handler_error = None
        self._on_handler_error = on_handler_error
        if ticks is not None:
            self._ticks = ticks
        else:
            from chumicro_timing import (
                ticks as real_ticks,  # noqa: PLC0415 - DI fallback keeps the substrate off BYO-ticks deploys
            )
            self._ticks = real_ticks
        # Cache the tick source's sleep_ms (else the module one) so the socket-less wait allocates nothing.
        self._sleep_ms = getattr(self._ticks, "sleep_ms", _sleep_ms)
        self._poller = poller
        # Each id(sock) slot is [sock, registered_mask, sweep_mask, sweep_generation,
        # descriptor]; _sync_poll_set reuses it in place so a steady-state sync
        # allocates nothing.
        self._registered_interest: dict = {}
        self._sweep_generation = 0

    def add(self, task: object | None = None,
            handler: object | None = None,
            period_ms: int | None = None,
            start_after_ms: int | None = None,
            run_count: int | None = None,
            preserve_phase: bool = False) -> TaskHandle:
        """Register a service object or a handler function, and return its ``TaskHandle``.

        Pass exactly one of ``task`` and ``handler``.  A handler runs each time its period
        comes round, or on every tick when it has no period.  A service's ``check(now_ms)``
        runs on that schedule instead, and its ``handle(now_ms)`` runs on the ticks where
        ``check`` returned True.

        Args:
            task: A service: an object with ``check(now_ms)`` and ``handle(now_ms)``, and
                optionally the ``io_socket``, ``io_interest``, ``io_error``, and
                ``next_deadline`` members that ``wait`` reads.
            handler: A function called as ``handler(now_ms)``.
            period_ms: Milliseconds between runs, or None to run on every tick.
            start_after_ms: Milliseconds before the first run.  Defaults to ``period_ms``.
            run_count: How many runs before the runner removes the job, or None for no
                limit.  For a service, each ``handle`` call is one run.
            preserve_phase: True keeps runs on the schedule set at registration when ticks
                come late, so two runs can land closer together than ``period_ms`` while it
                catches up.  False, the default, counts each period from the tick that ran
                the job.  Needs ``period_ms``.

        Returns:
            The ``TaskHandle`` for changing or removing the job later.

        Raises:
            ValueError: Both or neither of ``task`` and ``handler`` were passed,
                ``period_ms`` or ``run_count`` is 0 or less, or ``preserve_phase`` is True
                with no ``period_ms``.
            AttributeError: ``task`` has no ``check`` or no ``handle``.
        """
        service: object | None = None
        io_interest: object | None = None
        next_deadline: object | None = None
        if task is not None and handler is not None:
            raise ValueError(
                "Pass a task object or a handler callable, never both. "
                "To gate a handler, give one object check() and "
                "handle(), or test the condition inside the handler."
            )
        if task is not None:
            check_function = task.check
            handler_function = task.handle
            service = task
            io_interest = getattr(task, "io_interest", None)
            next_deadline = getattr(task, "next_deadline", None)
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
            io_interest=io_interest, next_deadline=next_deadline,
        )
        self._entries.append(handle)
        return handle

    def add_generator(self, generator: object) -> "GeneratorHandle":  # noqa: F821 - GeneratorHandle is lazy-imported in the body to keep _generator off the eager import path, so the return annotation is a forward-ref string
        """Register a generator task, run it up to its first pause, and return its handle.

        Each ``yield`` in the generator pauses it while the other jobs run.  A bare ``yield``
        resumes on the next tick, and ``yield from sleep_until(until_ms)`` from
        ``chumicro_runner.generators`` resumes at a given tick.  An exception that escapes
        the generator ends the task and is counted like any job's.

        Args:
            generator: A generator that has not started yet, such as ``blink()`` for a
                function ``blink`` whose body contains ``yield``.

        Returns:
            The task's ``GeneratorHandle``.  Its ``done`` turns True once the generator
                returns, raises, or is cancelled.  Its ``error`` holds the exception that
                ended the generator, or None.  ``cancel()`` closes the generator and
                unregisters it.

        Raises:
            BaseException: Whatever the generator raises before its first ``yield``.  The
                task is already unregistered when it propagates.
        """
        # Lazy import: registering a generator is a startup call, so _generator loads then, not on a hot tick.
        from chumicro_runner._generator import (  # noqa: PLC0415
            GeneratorHandle,
            _GeneratorWrapper,
        )

        handle = GeneratorHandle()
        wrapper = _GeneratorWrapper(generator, handle, self._ticks.ticks_diff)
        task_handle = self.add(wrapper)
        wrapper._task_handle = task_handle
        handle._wrapper = wrapper
        wrapper.start()
        return handle

    def add_periodic(self, handler: object, period_ms: int,
                     start_after_ms: int | None = None,
                     run_count: int | None = None,
                     preserve_phase: bool = False) -> TaskHandle:
        """Register ``handler`` to run every ``period_ms`` milliseconds, and return its ``TaskHandle``.

        The first run comes one period after registration, or ``start_after_ms`` after it.

        Args:
            handler: A function called as ``handler(now_ms)``.
            period_ms: Milliseconds between runs.
            start_after_ms: Milliseconds before the first run.  Defaults to ``period_ms``.
            run_count: How many runs before the runner removes the job, or None for no limit.
            preserve_phase: True keeps runs on the schedule set at registration when ticks
                come late.  ``add`` describes the trade.

        Returns:
            The ``TaskHandle`` for changing or removing the job later.

        Raises:
            ValueError: ``period_ms`` is None or 0 or less, or ``run_count`` is 0 or less.
        """
        if period_ms is None:
            raise ValueError("period_ms is required for add_periodic")
        return self.add(
            handler=handler, period_ms=period_ms,
            start_after_ms=start_after_ms, run_count=run_count,
            preserve_phase=preserve_phase,
        )

    def tick(self) -> int:
        """Run every job that is due now, and return the tick it ran them at.

        ``tick`` reads the clock once.  It walks the jobs in registration order and calls
        ``check(now_ms)`` on each due service, then runs every due handler and the ``handle``
        of every service whose ``check`` returned True, in the same order.  A job that raises
        is counted in ``handler_errors`` and passed to ``on_handler_error``, and the rest
        still run.

        Returns:
            The tick every job saw this pass, in milliseconds.  Pass it to ``wait``.

        Raises:
            ReentrantTickError: A job called ``tick()`` on this runner while it was running.
        """
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
            pending_count = 0

            for entry in self._entries:
                if entry.next_due_ms is not None:
                    if ticks_diff(now_ms, entry.next_due_ms) < 0:
                        continue
                    if entry.period_ms is None:
                        entry.next_due_ms = None
                    elif entry.preserve_phase:
                        # Advance from the previous deadline in whole periods so fires stay aligned;
                        # a long stall skips the missed fires instead of bursting to catch up.
                        behind = ticks_diff(now_ms, entry.next_due_ms)
                        periods_missed = behind // entry.period_ms + 1
                        entry.next_due_ms = ticks_add(
                            entry.next_due_ms,
                            periods_missed * entry.period_ms,
                        )
                    else:
                        entry.next_due_ms = ticks_add(now_ms, entry.period_ms)

                if entry.check_function is not None and not entry.check_function(now_ms):
                    continue
                # Overwrite a slot when one exists; the list grows to a high-water
                # capacity and stays there.  list.clear() would shrink the backing
                # array on MicroPython and CircuitPython, forcing a re-grow
                # allocation on every tick with several due handlers.
                if pending_count < len(pending):
                    pending[pending_count] = entry
                else:
                    pending.append(entry)
                pending_count += 1

            for pending_index in range(pending_count):
                entry = pending[pending_index]
                try:
                    entry.handler_function(now_ms)
                except ReentrantTickError:
                    raise
                except Exception as error:  # noqa: BLE001
                    # Catch Exception, not BaseException, so KeyboardInterrupt / SystemExit /
                    # GeneratorExit are not Exceptions and still propagate.
                    self._record_handler_fault(entry, error)
                if entry.run_count is not None:
                    entry.run_count -= 1
                    if entry.run_count <= 0:
                        self._remove(entry)

            return now_ms
        finally:
            # Blank the slots in finally so a raised handler leaves no fired
            # entries pinned; the next tick rebuilds from index zero either way.
            for pending_index in range(len(self._pending)):
                self._pending[pending_index] = None
            self._ticking = False

    def wait(self, now_ms: int) -> None:
        """Sleep until the next job is due or a watched socket is ready.

        Call it once per pass of the loop, after ``tick``.  It is the only runner call that
        blocks.  It returns at once when a job is already due, and also when no job has a
        due time and no service watches a socket, which leaves a loop of every-tick jobs
        spinning.  A socket that reports ``POLLERR``, or ``POLLHUP`` with nothing left to
        read, is passed to its service's ``io_error(now_ms, eventmask)``.

        Args:
            now_ms: The tick the preceding ``tick()`` returned.
        """
        self._sync_poll_set(now_ms)
        timeout_ms = self._compute_timeout(now_ms)
        if timeout_ms is not None and timeout_ms <= 0:
            return

        if self._registered_interest:
            if self._poller is None:
                self._poller = _SelectPollAdapter()
                for slot in self._registered_interest.values():
                    self._poller.register(slot[0], slot[1])
            if timeout_ms is None:
                # No deadline but sockets registered: block indefinitely (-1) until an event fires.
                timeout_ms = -1
            for item in self._poller.ipoll(timeout_ms):
                # ipoll yields (sock, mask) on MicroPython/CircuitPython, (fileno, mask) on CPython.
                # Unpack now, before the next iteration, in case the reused buffer rotates.
                obj = item[0]
                eventmask = item[1]
                # POLLHUP alongside POLLIN is a peer that sent its last bytes and
                # closed: the reader still has data, then end-of-stream, to collect.
                # Only POLLERR, or a hang-up with nothing left to read, is a fault.
                if eventmask & _POLLERR or (
                    eventmask & _POLLHUP and not eventmask & _POLLIN
                ):
                    self._dispatch_io_error(obj, eventmask, now_ms)
        else:
            if timeout_ms is None:
                return
            self._sleep_ms(timeout_ms)

    def run_until(self, predicate: object | None = None, *,
                  timeout_ms: int | None = None) -> bool:
        """Call ``tick`` and ``wait`` in a loop until ``predicate`` is met or ``timeout_ms`` runs out.

        Args:
            predicate: What to wait for.  A ``GeneratorHandle``, or any object with ``done``,
                is met once its task finishes.  A function taking no arguments is met once it
                returns something truthy, checked after each tick.  None waits for the
                timeout alone, and with no timeout either the loop runs forever.
            timeout_ms: Milliseconds to run before giving up, or None for no limit.  The
                runner checks it after each tick, so it lands late when ``wait`` sleeps past
                it.

        Returns:
            True once ``predicate`` is met, False when ``timeout_ms`` runs out first.

        Raises:
            BaseException: The exception that ended the task, when ``predicate`` is a handle
                whose ``error`` is set.
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
        self.handler_errors += 1
        self.last_handler_error = error
        on_error = self._on_handler_error
        if on_error is not None:
            try:
                on_error(entry, error)
            except Exception as callback_error:  # noqa: BLE001
                self.handler_errors += 1
                self.last_handler_error = callback_error

    def _dispatch_io_error(self, obj: object, eventmask: int, now_ms: int) -> None:
        # Snapshot with tuple(): an io_error throw can drop its entry from _entries mid-loop.
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
                return

    def _sync_poll_set(self, now_ms: int) -> None:
        # Reconcile the poll set from each entry's io_interest.
        # A no-change sweep touches the poller zero times and allocates nothing.
        registered = self._registered_interest
        poller = self._poller
        generation = self._sweep_generation + 1
        self._sweep_generation = generation

        # OR the masks of every service sharing a socket; stamp this sweep's generation on each slot.
        wanted_count = 0
        for entry in self._entries:
            interest_fn = entry.io_interest
            if interest_fn is None:
                continue
            sock = getattr(entry.service, "io_socket", None)
            if sock is None:
                continue
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
                registered[sock_id] = [
                    sock, 0, eventmask, generation, _fileno_of(sock),
                ]
                wanted_count += 1
            elif slot[3] != generation:
                slot[2] = eventmask
                slot[3] = generation
                wanted_count += 1
            else:
                slot[2] |= eventmask

        # Register a slot whose mask is still 0, modify one whose mask changed.
        # The slot tracks desired state even when poller is None, so wait's replay lines up.
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

        # Drop sockets untouched this sweep.  Explicit loop, not a comprehension:
        # on MicroPython a comprehension heap-boxes its free vars (~64 B per socket-less wait).
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
                        # A socket closed before this sweep (a finished fetch is the
                        # common case) can no longer name its own descriptor, so
                        # CPython rejects the unregister and the descriptor would stay
                        # in the poll set, where poll() reports POLLNVAL the instant it
                        # is called and every later wait() busy-spins.  Retry with the
                        # descriptor recorded while the socket was open.
                        self._unregister_descriptor(poller, slot[4])

    def _unregister_descriptor(self, poller: object, descriptor: int | None) -> None:
        if descriptor is None:
            # No descriptor was ever available, so the poller keys by object and the
            # refused unregister was benign divergence rather than a stranded entry.
            return
        registered = self._registered_interest
        for sock_id in registered:
            # A freed descriptor is handed straight back to the next socket the
            # process opens, and that socket registered earlier in this same sweep.
            # Dropping the descriptor now would blind a live connection.
            if registered[sock_id][4] == descriptor:
                return
        try:
            poller.unregister(descriptor)
        except (KeyError, OSError, ValueError):
            # Nothing else can name this descriptor; a poller that still refuses it
            # has already forgotten it.
            pass

    def _compute_timeout(self, now_ms: int) -> int | None:
        ticks_diff = self._ticks.ticks_diff
        nearest = None
        for entry in self._entries:
            if entry.next_due_ms is not None:
                delta = ticks_diff(entry.next_due_ms, now_ms)
                if nearest is None or delta < nearest:
                    nearest = delta
            deadline_fn = entry.next_deadline
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
