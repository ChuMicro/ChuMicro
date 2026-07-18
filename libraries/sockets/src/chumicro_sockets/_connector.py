"""Advance a non-blocking TCP or TLS connect across repeated ``tick(now_ms)`` calls.

``chumicro_sockets.connector()`` returns a per-runtime subclass of
:class:`SocketConnector`. Each ``tick`` advances one phase: ``awaiting_dns``,
``awaiting_tcp``, optional ``awaiting_tls``, then terminal ``ready`` (the
connected socket is on :attr:`socket`) or ``failed`` (the error is on
:attr:`last_error`). This base class owns the runner-contract surface and the
terminal-state bookkeeping; each adapter subclass implements :meth:`tick` for
its own runtime flow.
"""


STATE_AWAITING_DNS = "awaiting_dns"
STATE_AWAITING_TCP = "awaiting_tcp"
STATE_AWAITING_TLS = "awaiting_tls"
STATE_READY = "ready"
STATE_FAILED = "failed"

_TERMINAL = (STATE_READY, STATE_FAILED)

# Poll-interest bits for ``io_interest``, matching ``chumicro_runner.IO_READ``
# / ``IO_WRITE`` by value. Held as literals, not imported, so this library
# takes no dependency edge on the runner that drives it.
_IO_READ = 1
_IO_WRITE = 2


class SocketConnector:
    """Base connector: runner-contract surface plus terminal-state plumbing.

    Holds ``host`` / ``port`` / ``tls`` / ``context``. The current phase is on
    :attr:`state` and the current socket on :attr:`socket` throughout (the raw
    socket from ``awaiting_tcp`` entry until ``ready`` promotes it to the final,
    optionally TLS-wrapped socket). Subclasses implement :meth:`tick`; any
    exception it raises moves the connector to ``failed`` and closes
    :attr:`socket`.
    """

    def __init__(self, host, port, *, tls=False, context=None):
        self._host = host
        self._port = port
        self._tls = tls
        self._context = context

        self.state = STATE_AWAITING_DNS
        # Poll interest during ``awaiting_tls``: read+write until the first
        # handshake step names a direction, then narrowed to that direction so
        # an always-writable socket does not wake the poller every tick.
        self._tls_interest = _IO_READ | _IO_WRITE
        #: The current socket: the raw socket from ``awaiting_tcp``, replaced by
        #: the wrapped socket at ``ready``, cleared to ``None`` on failure.
        self.socket = None
        #: Set when ``state == "failed"``; ``None`` otherwise.
        self.last_error = None

    # ------------------------------------------------------------------
    # Runner-contract surface
    # ------------------------------------------------------------------

    @property
    def io_socket(self):
        """The socket for ``Runner.wait`` once built, or ``None`` before and after."""
        if self.socket is None:
            return None
        return self.socket

    def io_interest(self, now_ms):  # noqa: ARG002 (runner contract)
        """Poll-interest bitmask for ``Runner.wait``: the handshake direction
        during ``awaiting_tls``, write during ``awaiting_tcp``, nothing else."""
        if self.state == STATE_AWAITING_TLS:
            return self._tls_interest
        if self.state == STATE_AWAITING_TCP:
            return _IO_WRITE
        return 0

    def check(self, now_ms):  # noqa: ARG002 (runner contract)
        """``True`` while the connector wants a ``handle()``, ``False`` once terminal."""
        return self.state not in _TERMINAL

    def handle(self, now_ms):
        """Alias for :meth:`tick` so ``Runner.add(connector)`` works directly."""
        self.tick(now_ms)

    def next_deadline(self, now_ms):  # noqa: ARG002 (runner contract)
        """``None``: the connector never times out on its own, so consumers wrap
        the connect attempt in an outer deadline."""
        return None

    # ------------------------------------------------------------------
    # Driver: overridden per runtime
    # ------------------------------------------------------------------

    def tick(self, now_ms):  # noqa: ARG002 (subclass contract)
        """Advance the state machine by one phase (overridden per runtime)."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Terminal-state bookkeeping
    # ------------------------------------------------------------------

    def _fail(self, error):
        self.last_error = error
        self.state = STATE_FAILED
        if self.socket is not None:
            try:
                self.socket.close()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
            self.socket = None

    def cancel(self):
        """Abort an in-flight connect: close any socket and move to ``failed``.

        No-op when already terminal.
        """
        if self.state in _TERMINAL:
            return
        if self.last_error is None:
            self.last_error = OSError("connector cancelled")
        if self.socket is not None:
            try:
                self.socket.close()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
            self.socket = None
        self.state = STATE_FAILED
