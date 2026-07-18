STATE_AWAITING_DNS = "awaiting_dns"
STATE_AWAITING_TCP = "awaiting_tcp"
STATE_AWAITING_TLS = "awaiting_tls"
STATE_READY = "ready"
STATE_FAILED = "failed"

_TERMINAL = (STATE_READY, STATE_FAILED)

# Match ``chumicro_runner.IO_READ`` / ``IO_WRITE`` by value; kept as literals so
# this library takes no dependency edge on the runner.
_IO_READ = 1
_IO_WRITE = 2


class SocketConnector:
    """Base connector: runner-contract surface plus terminal-state plumbing."""

    def __init__(self, host, port, *, tls=False, context=None):
        self._host = host
        self._port = port
        self._tls = tls
        self._context = context

        self.state = STATE_AWAITING_DNS
        # read+write until the first handshake step narrows to one direction.
        self._tls_interest = _IO_READ | _IO_WRITE
        self.socket = None
        self.last_error = None

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
        """``None``: the connector never times out on its own."""
        return None

    def tick(self, now_ms):  # noqa: ARG002 (subclass contract)
        """Advance the state machine by one phase (overridden per runtime)."""
        raise NotImplementedError

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
        """Abort an in-flight connect: close any socket and move to ``failed``."""
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
