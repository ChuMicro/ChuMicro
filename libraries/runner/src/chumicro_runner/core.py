"""Tick-based scheduler for the ChuMicro libraries.

Register work with a ``Runner``, then call ``tick()`` in a loop; ``wait()`` idles the CPU between ticks.
"""

# Eager import: on MicroPython mount-mode a lazy import becomes an mpremote RPC that adds ~1 s per test.
import time

from chumicro_timing import ticks as _DEFAULT_TICKS

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

_POLL_ERROR_MASK = _POLLERR | _POLLHUP

# Poll-interest bits a service returns from io_interest(); a pinned contract, so keep the numbers stable.
IO_READ = 1
IO_WRITE = 2


class ReentrantTickError(RuntimeError):
    """Raised when ``tick()`` runs while another ``tick()`` is in progress."""


# time.sleep_ms exists on MicroPython and CircuitPython; CPython has only time.sleep, in seconds.
_native_sleep_ms = getattr(time, "sleep_ms", None)


def _pollable_of(io_socket: object) -> object:
    # chumicro_sockets adapters hold the real pollable on .sock; a bare socket passes through.
    return getattr(io_socket, "sock", io_socket)


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
    """Handle returned by ``Runner.add()`` or ``add_periodic()``."""

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
        self.service = service
        # Cache the bound io_interest method so the per-sweep poll sync never re-allocates it.
        self.io_interest = io_interest

    def set_period(self, period_ms: int | None) -> None:
        """Add, change, or remove the period for this task.

        Args:
            period_ms: New interval in milliseconds, or ``None`` to clear the period.
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

    Args:
        ticks: Optional source (``ticks_ms``, ``ticks_diff``, ``ticks_add``); default ``chumicro_timing``.
        poller: Optional poll object (register/modify/unregister/ipoll); default ``select.poll`` adapter.
        on_handler_error: Optional ``(handle, exception)`` callback invoked when a handler raises.
    """

    def __init__(self, ticks: object | None = None,
                 poller: object | None = None,
                 on_handler_error: object | None = None) -> None:
        self._entries = []
        self._pending = []
        self._ticking = False
        self.handler_errors = 0
        self._on_handler_error = on_handler_error
        self._ticks = ticks if ticks is not None else _DEFAULT_TICKS
        # Cache the tick source's sleep_ms (else the module one) so the socket-less wait allocates nothing.
        self._sleep_ms = getattr(self._ticks, "sleep_ms", _sleep_ms)
        self._poller = poller
        # Each id(sock) slot is [sock, registered_mask, sweep_mask, sweep_generation];
        # _sync_poll_set reuses it in place so a steady-state sync allocates nothing.
        self._registered_interest: dict = {}
        self._sweep_generation = 0

    def add(self, task: object | None = None,
            handler: object | None = None,
            period_ms: int | None = None,
            start_after_ms: int | None = None,
            run_count: int | None = None,
            preserve_phase: bool = False) -> TaskHandle:
        """Register a task with the runner.

        Args:
            task: Object with ``.check(now_ms)`` and ``.handle(now_ms)``; mutually exclusive with *handler*.
            handler: Callable ``handler(now_ms)`` fired on schedule; mutually exclusive with *task*.
            period_ms: Optional interval in milliseconds.
            start_after_ms: Optional initial delay before the first fire; overrides the first period.
            run_count: Optional number of fires before auto-removing; ``None`` means unlimited.
            preserve_phase: When ``True``, fires stay aligned under late ticks; needs *period_ms*.

        Returns:
            A ``TaskHandle`` for runtime mutation.
        """
        service: object | None = None
        io_interest: object | None = None
        if task is not None and handler is not None:
            raise ValueError(
                "Pass a task object OR a handler callable, not both "
                "(the separate check-plus-handler shape was removed; "
                "give the object a handle() or gate inside the handler)"
            )
        if task is not None:
            check_function = task.check
            handler_function = task.handle
            service = task
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

        Args:
            gen: A fresh, not-yet-advanced generator; this method primes it to its first yield.

        Returns:
            A ``GeneratorHandle`` carrying ``.done`` and ``.cancel()``.
        """
        # Lazy import: registering a generator is a startup call, so _generator loads then, not on a hot tick.
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

        Args:
            handler: Callable ``handler(now_ms)`` to fire periodically.
            period_ms: Interval in milliseconds (required).
            start_after_ms: Optional initial delay before the first fire.
            run_count: Optional number of fires before auto-removing; ``None`` means unlimited.
            preserve_phase: When ``True``, fires stay aligned under late ticks.

        Returns:
            A ``TaskHandle`` for runtime mutation.
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

        Returns:
            The tick timestamp used this cycle.

        Raises:
            ReentrantTickError: A handler called ``tick()`` while this ``tick()`` was already running.
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

                if entry.check_function is not None:
                    if entry.check_function(now_ms):
                        pending.append(entry)
                else:
                    pending.append(entry)

            for entry in pending:
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
            # Clear in finally so a raised handler leaves no fired entries to re-fire next tick.
            self._pending.clear()
            self._ticking = False

    def wait(self, now_ms: int) -> None:
        """Idle until a registered socket is ready or the next deadline arrives.

        Args:
            now_ms: Current tick, typically the value returned by the preceding ``tick()`` call.
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
                if eventmask & _POLL_ERROR_MASK:
                    self._dispatch_io_error(obj, eventmask, now_ms)
        else:
            if timeout_ms is None:
                return
            self._sleep_ms(timeout_ms)

    def run_until(self, predicate: object | None = None, *,
                  timeout_ms: int | None = None) -> bool:
        """Drive ``tick()`` and ``wait()`` until *predicate* is truthy.

        Args:
            predicate: A handle (exposes ``done``), a zero-arg callable checked each tick, or ``None``.
            timeout_ms: Optional budget (ms), checked between ticks; best-effort under socket waits.

        Returns:
            ``True`` when *predicate* became truthy or the handle finished cleanly, ``False`` on timeout.

        Raises:
            BaseException: The handle form re-raises ``handle.error`` when the awaited task died.
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
        on_error = self._on_handler_error
        if on_error is not None:
            try:
                on_error(entry, error)
            except Exception:  # noqa: BLE001
                self.handler_errors += 1

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
                registered[sock_id] = [sock, 0, eventmask, generation]
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
                        # The socket was already closed or unregistered out-of-band
                        # (CPython raises ValueError on a closed fileno); not an error here.
                        pass

    def _compute_timeout(self, now_ms: int) -> int | None:
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
