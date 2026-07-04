"""Generator adapter for ``Runner.add_generator``.

Bridges a Python generator function (``def`` + ``yield`` / ``yield from``)
into the runner's check / handle / io_* protocol.  The wrapper is
fully duck-typed: a generator yields *anything* that exposes the
attributes the wrapper inspects.  No named protocol classes required.

The duck-typed wait protocol — every attribute optional, defaults to
None / False:

* ``io_socket``: the underlying pollable the runner should register
  with ipoll, or ``None``.
* ``io_wants_read`` / ``io_wants_write``: ``True`` to register the
  socket for that direction.
* ``next_deadline``: absolute tick at which the wrapper should resume
  the generator; ``None`` means "resume on the next tick after an
  ipoll wake or any other deadline elapses."
* ``ready(now_ms) -> bool``: optional event predicate.  A wait
  exposing it (and no socket) suspends the generator until ``ready``
  returns True or ``next_deadline`` elapses (the timeout path) — the
  shape ``chumicro_timing.waits.Signal`` implements for
  completions that originate in callback-style services.

A bare ``yield`` (sending ``None``) suspends for exactly one tick:
the wrapper substitutes a private next-tick wait, so ``None`` in the
wait slot strictly means the generator finished.

The ``SocketConnector`` from ``chumicro_sockets`` already exposes
these attributes natively, so a generator that wraps it can simply
``yield connector`` — no extra wrapping needed.  Helper functions
build small private wait objects for the other cases: the socket
helpers in ``chumicro_sockets.generators`` for a bare socket,
``sleep_until`` in ``chumicro_runner.generators`` for a deadline,
``Signal`` / ``wait_for`` in ``chumicro_timing.waits`` for a
callback-completed event.

Sequential I/O state machines that would otherwise need an explicit
per-state ``check`` / ``handle`` object collapse to a top-to-bottom
generator body.  The substrate is plain Python generators driven via
``.send()`` / ``.throw()`` / ``.close()`` — no ``async`` / ``await``
keywords involved, and no event loop other than the runner's own tick
loop.

``GeneratorHandle`` is the public face returned by ``add_generator``;
``_GeneratorWrapper`` is the runner-protocol adapter that users never
touch directly.
"""

from chumicro_timing.ticks import ticks_diff


class _NextTickWait:
    """Wait stored for a bare ``yield``: no socket, no deadline, no
    ready predicate, so the wrapper resumes the generator on the next
    tick.  One module-level instance serves every generator."""


_NEXT_TICK_WAIT = _NextTickWait()


class GeneratorHandle:
    """Public handle returned by ``Runner.add_generator``.

    Observe completion via ``.done`` (False while the generator is
    running, True after it returns normally, dies on an exception, or
    is cancelled).  ``.error`` distinguishes the outcomes: ``None`` for
    a normal return or cancel, the exception instance when the body
    raised — so a ``while not handle.done`` driver can report *why* a
    task ended instead of discovering a silent death by timeout.
    Stop a long-running generator early via ``.cancel()``, which fires
    any ``finally`` blocks inside the generator body — the natural place
    to put socket close, deadline timer cancel, and so on.
    """

    def __init__(self) -> None:
        self.done = False
        self.error: BaseException | None = None
        # Set by ``Runner.add_generator`` immediately after construction.
        # ``cancel`` clears it so the second call is a no-op without
        # needing a separate already-cancelled flag.
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
    """Runner-protocol adapter that drives a generator via wait-tokens.

    Constructed by ``Runner.add_generator``; never used directly by
    library callers.  Satisfies the duck-typed contract the runner reads:
    ``check`` / ``handle`` for tick scheduling, ``io_socket`` /
    ``io_wants_read`` / ``io_wants_write`` for poll-set membership,
    ``io_error`` for POLLERR / POLLHUP dispatch, and ``next_deadline``
    so a deadline-bearing wait (``sleep_until``) gates the wake timeout
    in ``Runner.wait``.

    The wrapper writes ``handle.done = True`` and removes its
    ``TaskHandle`` from the runner the moment the generator finishes
    (either by returning normally or by being cancelled), so the
    consumer's ``while not handle.done`` loop exits cleanly without
    leaving a dead entry in the runner.
    """

    def __init__(self, gen: object, handle: GeneratorHandle) -> None:
        self._gen = gen
        self._wait: object | None = None
        self._handle = handle
        # Set by ``Runner.add_generator`` after the runner has appended
        # this wrapper's TaskHandle to its ``_entries`` list.  The
        # wrapper uses it to self-remove on ``StopIteration`` so a
        # finished generator does not linger as a dead entry.
        self._task_handle: object | None = None

    def start(self) -> None:
        """Prime the generator to its first yield.  Called once at registration."""
        self._advance(None)

    def check(self, now_ms: int) -> bool:
        wait = self._wait
        if wait is None:
            return False
        # A socket-driven wait resumes every tick so its EAGAIN loop
        # re-tries on each wake; ipoll in Runner.wait gates the sleep.
        # When such a wait also carries next_deadline (a socket read
        # with a timeout), that deadline only shortens Runner.wait's
        # sleep — it must not delay the resume, or ready bytes would
        # sit unread until the deadline.  A sleep-only wait (no socket)
        # gates the resume on its deadline.
        if getattr(wait, "io_socket", None) is not None:
            return True
        # An event wait exposes ready(now_ms): resume once it fires, or
        # when its next_deadline elapses (the timeout path); otherwise
        # stay suspended so the wait is not busy-polled.
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
        # check returning True is the gate; wait is non-None here.
        # Resume the generator with now_ms — the value the gen receives
        # at its yield expression.  Most helpers ignore it; long-running
        # state machines can use it to advance internal deadlines
        # without a second ticks_ms call.
        self._advance(now_ms)

    @property
    def io_socket(self) -> object | None:
        wait = self._wait
        if wait is None:
            return None
        return getattr(wait, "io_socket", None)

    @property
    def io_wants_read(self) -> bool:
        wait = self._wait
        return bool(getattr(wait, "io_wants_read", False)) if wait is not None else False

    @property
    def io_wants_write(self) -> bool:
        wait = self._wait
        return bool(getattr(wait, "io_wants_write", False)) if wait is not None else False

    def io_error(self, now_ms: int, eventmask: int) -> None:
        """POLLERR / POLLHUP on the awaited socket — throw into the generator.

        The generator can catch with ``except OSError:`` and recover, or
        let it propagate so the wrapper marks done and removes itself.
        The eventmask is not forwarded; if a future caller needs the
        bitmask, attach it to the exception.
        """
        self._advance_throw(OSError("POLLERR / POLLHUP on awaited socket"))

    def next_deadline(self, now_ms: int) -> int | None:
        """Absolute tick at which the generator should be re-checked.

        Reads the yielded wait's ``next_deadline`` — one convention
        only: a callable taking ``now_ms`` and returning an absolute
        tick or ``None`` (the ``SocketConnector`` shape, matching the
        runner's service contract).  A wait without the attribute, or
        whose call returns ``None``, is socket-driven (ipoll wake-up)
        or unbounded.  ``Runner.wait`` mins this against every other
        entry's deadline to compute its ipoll timeout.
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
            # Generator raised — it has terminated.  Record the death on
            # the handle (per-task attribution for the driver's
            # ``while not handle.done`` loop) and drop the runner entry
            # before re-raising so a dead wrapper does not linger if a
            # caller catches the exception further up the stack.
            self._handle.error = error
            self._mark_done()
            raise
        else:
            # A bare ``yield`` sends None; substitute the next-tick
            # wait so a None wait slot strictly means finished.
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
        """Cancellation path: close the generator and remove from runner.

        ``gen.close()`` raises ``GeneratorExit`` inside the generator at
        its current yield; ``finally`` blocks run.  A well-formed
        generator catches nothing (or catches and re-raises) and exits.
        A misbehaving generator that ignores ``GeneratorExit`` causes
        ``gen.close()`` itself to raise ``RuntimeError`` — let it
        propagate to the cancel caller; there is no recovery here.
        """
        if self._handle.done:
            return
        try:
            self._gen.close()
        finally:
            self._mark_done()

    def _mark_done(self) -> None:
        """Finalize the generator: clear the wait, set ``handle.done``, remove the runner entry.

        Removing the entry clears ``_task_handle``, so a repeat call
        removes nothing.
        """
        self._wait = None
        self._handle.done = True
        task_handle = self._task_handle
        if task_handle is not None:
            self._task_handle = None
            task_handle.remove()
