class _NextTickWait:
    """Bare-yield wait with no hooks; the wrapper resumes it next tick."""


_NEXT_TICK_WAIT = _NextTickWait()


class GeneratorHandle:
    """Handle returned by ``Runner.add_generator``."""

    def __init__(self) -> None:
        self.done = False
        self.error: BaseException | None = None
        self._wrapper: _GeneratorWrapper | None = None

    def cancel(self) -> None:
        """Stop the generator and remove it from the runner."""
        wrapper = self._wrapper
        if wrapper is not None:
            self._wrapper = None
            wrapper._close()


class _GeneratorWrapper:
    def __init__(self, generator: object, handle: GeneratorHandle,
                 ticks_diff: object) -> None:
        self._generator = generator
        # The runner's injected clock, not chumicro_timing's: a caller who passed
        # ticks= to Runner must have every deadline compared in their own units.
        self._ticks_diff = ticks_diff
        self._wait: object | None = None
        # Bound hook methods of the current wait, resolved once per yield.  A
        # per-tick getattr would allocate a fresh bound method on MicroPython
        # and CircuitPython inside check() / io_interest() / next_deadline().
        self._wait_ready: object | None = None
        self._wait_io_interest: object | None = None
        self._wait_next_deadline: object | None = None
        self._handle = handle
        self._task_handle: object | None = None

    def start(self) -> None:
        self._advance(None)

    def check(self, now_ms: int) -> bool:
        wait = self._wait
        if wait is None:
            return False
        # A socket wait resumes every tick even when it carries a deadline, so ready bytes are not stuck.
        if getattr(wait, "io_socket", None) is not None:
            return True
        ready = self._wait_ready
        if ready is not None:
            if ready(now_ms):
                return True
            deadline = self.next_deadline(now_ms)
            return deadline is not None and self._ticks_diff(now_ms, deadline) >= 0
        deadline = self.next_deadline(now_ms)
        if deadline is not None:
            return self._ticks_diff(now_ms, deadline) >= 0
        return True

    def handle(self, now_ms: int) -> None:
        self._advance(now_ms)

    @property
    def io_socket(self) -> object | None:
        wait = self._wait
        if wait is None:
            return None
        # Resolved per call, not cached at yield time: a connector wait grows
        # its socket after the yield, so the attribute must be read live.
        return getattr(wait, "io_socket", None)

    def io_interest(self, now_ms: int) -> int:
        interest = self._wait_io_interest
        if interest is None:
            return 0
        return interest(now_ms)

    def io_error(self, now_ms: int, eventmask: int) -> None:
        self._advance_throw(OSError("POLLERR / POLLHUP on awaited socket"))

    def next_deadline(self, now_ms: int) -> int | None:
        deadline = self._wait_next_deadline
        if deadline is None:
            return None
        return deadline(now_ms)

    def _set_wait(self, wait: object | None) -> None:
        # A bare yield gets the next-tick wait, so _wait is None only when the generator finishes.
        if wait is None:
            wait = _NEXT_TICK_WAIT
        if wait is self._wait:
            return
        self._wait = wait
        self._wait_ready = getattr(wait, "ready", None)
        self._wait_io_interest = getattr(wait, "io_interest", None)
        self._wait_next_deadline = getattr(wait, "next_deadline", None)

    def _advance(self, value: object) -> None:
        try:
            wait = self._generator.send(value)
        except StopIteration:
            self._mark_done()
        except BaseException as error:
            self._handle.error = error
            self._mark_done()
            raise
        else:
            self._set_wait(wait)

    def _advance_throw(self, error: BaseException) -> None:
        try:
            wait = self._generator.throw(error)
        except StopIteration:
            self._mark_done()
        except BaseException as died:
            self._handle.error = died
            self._mark_done()
            raise
        else:
            self._set_wait(wait)

    def _close(self) -> None:
        if self._handle.done:
            return
        try:
            self._generator.close()
        finally:
            self._mark_done()

    def _mark_done(self) -> None:
        self._wait = None
        self._wait_ready = None
        self._wait_io_interest = None
        self._wait_next_deadline = None
        self._handle.done = True
        task_handle = self._task_handle
        if task_handle is not None:
            # Clear _task_handle before remove() so a repeat call is a no-op.
            self._task_handle = None
            task_handle.remove()
