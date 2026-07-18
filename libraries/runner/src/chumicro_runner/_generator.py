"""Generator adapter for ``Runner.add_generator``.

Bridges a plain Python generator (``def`` + ``yield``) into the runner's
check / handle / io_* protocol.  The generator suspends by ``yield``-ing
a duck-typed wait object whose optional ``io_socket`` /
``io_interest(now_ms)`` / ``next_deadline`` / ``ready(now_ms)``
attributes tell the wrapper when to resume it; a bare ``yield`` resumes
on the next tick.  ``GeneratorHandle`` is the public handle returned to
callers; ``_GeneratorWrapper`` is the internal adapter.
"""

from chumicro_timing.ticks import ticks_diff


class _NextTickWait:
    """Bare-``yield`` wait with no hooks, so the wrapper resumes next tick.

    One module-level instance serves every generator.
    """


_NEXT_TICK_WAIT = _NextTickWait()


class GeneratorHandle:
    """Public handle returned by ``Runner.add_generator``.

    ``.done`` is False while the generator runs, True once it returns,
    raises, or is cancelled.  ``.error`` is ``None`` on a normal return
    or cancel and the exception instance when the body raised, so a
    driver can report why a task ended.  ``.cancel()`` stops a running
    generator early, firing any ``finally`` blocks inside it.
    """

    def __init__(self) -> None:
        self.done = False
        self.error: BaseException | None = None
        # Set by Runner.add_generator after construction; cancel clears it
        # so a second cancel is a no-op without a separate flag.
        self._wrapper: _GeneratorWrapper | None = None

    def cancel(self) -> None:
        """Stop the generator and remove it from the runner.

        Sends ``GeneratorExit`` into the generator at its current yield
        via ``gen.close()`` so any ``finally`` block runs.  Idempotent:
        calling ``cancel`` on an already-done handle is a no-op.
        """
        wrapper = self._wrapper
        if wrapper is not None:
            self._wrapper = None
            wrapper._close()


class _GeneratorWrapper:
    """Runner-protocol adapter that drives a generator via wait-tokens."""

    def __init__(self, gen: object, handle: GeneratorHandle) -> None:
        self._gen = gen
        self._wait: object | None = None
        self._handle = handle
        # Set by Runner.add_generator after it appends this wrapper's
        # TaskHandle; used to self-remove when the generator finishes.
        self._task_handle: object | None = None

    def start(self) -> None:
        """Prime the generator to its first yield.  Called once at registration."""
        self._advance(None)

    def check(self, now_ms: int) -> bool:
        wait = self._wait
        if wait is None:
            return False
        # A socket-driven wait resumes every tick so its EAGAIN loop retries
        # on each wake (ipoll gates the sleep).  Any next_deadline it also
        # carries only shortens the sleep; it must not delay this resume, or
        # ready bytes would sit unread until the deadline.
        if getattr(wait, "io_socket", None) is not None:
            return True
        # An event wait exposes ready(now_ms): resume once it fires or its
        # next_deadline elapses, else stay suspended so it is not busy-polled.
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
        # Resume the generator with now_ms, the value it receives at its
        # yield expression (most helpers ignore it).
        self._advance(now_ms)

    @property
    def io_socket(self) -> object | None:
        wait = self._wait
        if wait is None:
            return None
        return getattr(wait, "io_socket", None)

    def io_interest(self, now_ms: int) -> int:
        """Poll-interest bitmask of the current wait, or 0 when idle.

        Forwards to the yielded wait's ``io_interest(now_ms)``; a wait
        that exposes none contributes 0 to the poll set.
        """
        wait = self._wait
        if wait is None:
            return 0
        interest = getattr(wait, "io_interest", None)
        if interest is None:
            return 0
        return interest(now_ms)

    def io_error(self, now_ms: int, eventmask: int) -> None:
        """POLLERR / POLLHUP on the awaited socket: throw ``OSError`` into the generator.

        The generator can catch it with ``except OSError`` and recover, or
        let it propagate so the wrapper marks done and removes itself.
        """
        self._advance_throw(OSError("POLLERR / POLLHUP on awaited socket"))

    def next_deadline(self, now_ms: int) -> int | None:
        """Absolute tick at which the generator should be re-checked, or ``None``.

        Reads the yielded wait's ``next_deadline(now_ms)``; a wait without
        it, or one that returns ``None``, is socket-driven or unbounded.
        """
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
            # Generator raised, so it has terminated.  Record the death on
            # the handle and drop the runner entry before re-raising.
            self._handle.error = error
            self._mark_done()
            raise
        else:
            # A bare yield sends None; substitute the next-tick wait so a
            # None wait slot strictly means the generator finished.
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
        # gen.close() raises GeneratorExit at the current yield so finally
        # blocks run.  A generator that ignores GeneratorExit makes close()
        # raise RuntimeError; let it propagate, there is no recovery here.
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
            # Clear _task_handle first so a repeat call removes nothing.
            self._task_handle = None
            task_handle.remove()
