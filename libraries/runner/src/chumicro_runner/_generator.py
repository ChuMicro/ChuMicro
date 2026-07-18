from chumicro_timing.ticks import ticks_diff


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
    def __init__(self, gen: object, handle: GeneratorHandle) -> None:
        self._gen = gen
        self._wait: object | None = None
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
        ready = getattr(wait, "ready", None)
        if ready is not None:
            if ready(now_ms):
                return True
            deadline = self.next_deadline(now_ms)
            return deadline is not None and ticks_diff(now_ms, deadline) >= 0
        deadline = self.next_deadline(now_ms)
        if deadline is not None:
            return ticks_diff(now_ms, deadline) >= 0
        return True

    def handle(self, now_ms: int) -> None:
        self._advance(now_ms)

    @property
    def io_socket(self) -> object | None:
        wait = self._wait
        if wait is None:
            return None
        return getattr(wait, "io_socket", None)

    def io_interest(self, now_ms: int) -> int:
        wait = self._wait
        if wait is None:
            return 0
        interest = getattr(wait, "io_interest", None)
        if interest is None:
            return 0
        return interest(now_ms)

    def io_error(self, now_ms: int, eventmask: int) -> None:
        self._advance_throw(OSError("POLLERR / POLLHUP on awaited socket"))

    def next_deadline(self, now_ms: int) -> int | None:
        wait = self._wait
        if wait is None:
            return None
        deadline = getattr(wait, "next_deadline", None)
        if deadline is None:
            return None
        return deadline(now_ms)

    def _advance(self, value: object) -> None:
        try:
            wait = self._gen.send(value)
        except StopIteration:
            self._mark_done()
        except BaseException as error:
            self._handle.error = error
            self._mark_done()
            raise
        else:
            # A bare yield gets the next-tick wait, so _wait is None only when the generator finishes.
            self._wait = wait if wait is not None else _NEXT_TICK_WAIT

    def _advance_throw(self, error: BaseException) -> None:
        try:
            wait = self._gen.throw(error)
        except StopIteration:
            self._mark_done()
        except BaseException as died:
            self._handle.error = died
            self._mark_done()
            raise
        else:
            self._wait = wait if wait is not None else _NEXT_TICK_WAIT

    def _close(self) -> None:
        if self._handle.done:
            return
        try:
            self._gen.close()
        finally:
            self._mark_done()

    def _mark_done(self) -> None:
        self._wait = None
        self._handle.done = True
        task_handle = self._task_handle
        if task_handle is not None:
            # Clear _task_handle before remove() so a repeat call is a no-op.
            self._task_handle = None
            task_handle.remove()
