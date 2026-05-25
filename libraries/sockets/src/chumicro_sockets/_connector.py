"""Advance a non-blocking TCP/TLS connect across multiple ``tick(now_ms)`` calls.

The non-blocking counterpart to ``tcp_client_socket`` /
``tls_client_socket``.  Library methods that perform network I/O do not
block: a runner-shaped library constructs a connector and advances it
across ticks instead of calling a synchronous factory.  The synchronous
factory stays for non-runner contexts (one-shot scripts, REPL, ``main``
before the runner loop starts).

Each call to :meth:`SocketConnector.tick` advances the connector by one
phase.  Phase boundaries are uniform across runtimes:

* ``awaiting_dns`` — resolve ``host`` to an address.
* ``awaiting_tcp`` — TCP connect in progress.
* ``awaiting_tls`` — TLS handshake in progress.
* ``ready`` — terminal; :attr:`socket` is set.
* ``failed`` — terminal; :attr:`last_error` is set.

*How* a runtime moves between phases is its own concern — CPython runs
three genuine non-blocking phases; MP collapses the TLS handshake into
one blocking tick (no ``do_handshake_on_connect=False`` on its mbedTLS
binding); CP collapses TCP + TLS into one blocking ``connect()`` call
and skips the ``awaiting_tls`` phase entirely.  Each per-runtime
adapter implements its own :meth:`tick` to encode that flow.

This base class owns the runner-contract surface
(``check`` / ``handle`` / ``io_socket`` / ``io_wants_read`` /
``io_wants_write`` / ``next_deadline`` / ``cancel``) plus the
terminal-state bookkeeping (``_fail`` close-on-failure, ``cancel``
close-on-abort).
"""


STATE_AWAITING_DNS = "awaiting_dns"
STATE_AWAITING_TCP = "awaiting_tcp"
STATE_AWAITING_TLS = "awaiting_tls"
STATE_READY = "ready"
STATE_FAILED = "failed"

_TERMINAL = (STATE_READY, STATE_FAILED)


class SocketConnector:
    """Base — runner-contract surface + terminal-state plumbing.

    Holds ``host`` / ``port`` / ``tls`` / ``context`` on the instance.
    The current phase lives on :attr:`state`; the in-progress socket
    lives on :attr:`_inflight_socket` between phases and is promoted
    to :attr:`socket` once :attr:`state` reaches ``ready``.

    Subclasses implement :meth:`tick` with their full per-runtime
    state machine.  Any exception raised by :meth:`tick` transitions
    the connector to ``failed`` and closes the in-progress socket.
    """

    def __init__(self, host, port, *, tls=False, context=None):
        self._host = host
        self._port = port
        self._tls = tls
        self._context = context

        self.state = STATE_AWAITING_DNS
        #: Set when ``state == "ready"``; ``None`` otherwise.
        self.socket = None
        #: Set when ``state == "failed"``; ``None`` otherwise.
        self.last_error = None

        # In-progress socket between phases.  Holds the raw socket
        # during ``awaiting_tcp`` and the TLS-wrapped socket during
        # ``awaiting_tls``.  Promoted to ``self.socket`` on entry to
        # ``ready``; closed in :meth:`cancel` and :meth:`_fail`.
        self._inflight_socket = None

    # ------------------------------------------------------------------
    # Runner-contract surface
    # ------------------------------------------------------------------

    @property
    def io_socket(self):
        """Underlying pollable while the handshake is in flight, else ``None``.

        ``Runner.wait`` reads this to register the right socket with
        ``ipoll``.  Terminal states return ``None`` so the runner does
        not keep waking on a dead handle.
        """
        if self.state in _TERMINAL:
            return None
        if self._inflight_socket is None:
            return None
        return getattr(self._inflight_socket, "sock", self._inflight_socket)

    @property
    def io_wants_read(self):
        """``True`` while a TLS handshake step might consume inbound bytes."""
        return self.state == STATE_AWAITING_TLS

    @property
    def io_wants_write(self):
        """``True`` while a TCP-connect / TLS-handshake step needs writability."""
        return self.state in (STATE_AWAITING_TCP, STATE_AWAITING_TLS)

    def check(self, now_ms):  # noqa: ARG002 (runner contract)
        """``True`` while the connector wants a ``handle()`` this tick.

        Returns ``False`` once the connector reaches ``ready`` or
        ``failed`` — the consumer is responsible for inspecting state
        at that point and either grabbing the socket or surfacing the
        error.
        """
        return self.state not in _TERMINAL

    def handle(self, now_ms):
        """Alias for :meth:`tick` — lets ``Runner.add(connector)`` work directly."""
        self.tick(now_ms)

    def next_deadline(self, now_ms):  # noqa: ARG002 (runner contract)
        """Connector does not time out on its own.

        Consumers wrap the connect attempt in an outer deadline.
        ``None`` here lets the runner's ``wait`` park indefinitely
        until ``io_*`` fires or another service's deadline elapses.
        """
        return None

    # ------------------------------------------------------------------
    # Driver — overridden per runtime
    # ------------------------------------------------------------------

    def tick(self, now_ms):  # noqa: ARG002 (subclass contract)
        """Advance the state machine by one phase.

        Subclass overrides own the full state progression — see the
        per-runtime adapter files in ``_adapters/``.  The override
        wraps its body in ``try / except Exception`` and calls
        :meth:`_fail` on any error so the public surface stays
        uniform (``state == "failed"`` + ``last_error`` set).
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Terminal-state bookkeeping
    # ------------------------------------------------------------------

    def _fail(self, error):
        """Transition to ``failed`` and close the in-progress socket.

        Subclass ``tick`` overrides call this from their ``except``
        clause on any unexpected error.  The in-progress socket close
        is best-effort — a socket whose connect / handshake failed may
        not survive a clean close, so we swallow secondary errors here.
        """
        self.last_error = error
        self.state = STATE_FAILED
        if self._inflight_socket is not None:
            try:
                self._inflight_socket.close()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
            self._inflight_socket = None

    def cancel(self):
        """Close any in-flight socket and transition to ``failed``.

        No-op when already terminal.  Used by consumers that need to
        abort a connect attempt (per-connector deadline elapsed,
        higher-level shutdown, etc.).
        """
        if self.state in _TERMINAL:
            return
        if self.last_error is None:
            self.last_error = OSError("connector cancelled")
        if self._inflight_socket is not None:
            try:
                self._inflight_socket.close()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
            self._inflight_socket = None
        self.state = STATE_FAILED
