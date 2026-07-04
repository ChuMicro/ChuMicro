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
* ``ready`` — terminal; :attr:`socket` is the connected socket.
* ``failed`` — terminal; :attr:`last_error` is set; :attr:`socket` is ``None``.

*How* a runtime moves between phases is its own concern — CPython runs
three genuine non-blocking phases; MP collapses the TLS handshake into
one blocking tick (no ``do_handshake_on_connect=False`` on its mbedTLS
binding); CP collapses TCP + TLS into one blocking ``connect()`` call
and skips the ``awaiting_tls`` phase entirely.  Each per-runtime
adapter implements its own :meth:`tick` to encode that flow.

This base class owns the runner-contract surface
(``check`` / ``handle`` / ``io_socket`` / ``io_interest`` /
``next_deadline`` / ``cancel``) plus the
terminal-state bookkeeping (``_fail`` close-on-failure, ``cancel``
close-on-abort).
"""


STATE_AWAITING_DNS = "awaiting_dns"
STATE_AWAITING_TCP = "awaiting_tcp"
STATE_AWAITING_TLS = "awaiting_tls"
STATE_READY = "ready"
STATE_FAILED = "failed"

_TERMINAL = (STATE_READY, STATE_FAILED)

# Poll-interest bits for ``io_interest``; mirror ``chumicro_runner.IO_READ``
# / ``IO_WRITE`` by value.  Held as literals rather than imported so the
# sockets stack takes no dependency edge on the runner — a connector is
# driven by a runner but must never import one (bring-your-own-scheduler / duck
# typing).
_IO_READ = 1
_IO_WRITE = 2


class SocketConnector:
    """Base — runner-contract surface + terminal-state plumbing.

    Holds ``host`` / ``port`` / ``tls`` / ``context`` on the instance.
    The current phase lives on :attr:`state`; the current socket lives
    on :attr:`socket` throughout — the raw socket from
    ``awaiting_tcp`` entry until ``ready`` promotes it to the final
    (optionally TLS-wrapped) connected socket.  Consumers always read
    :attr:`socket`; ``io_socket`` is the registrable pollable for the
    runner.

    Subclasses implement :meth:`tick` with their full per-runtime
    state machine.  Any exception raised by :meth:`tick` transitions
    the connector to ``failed`` and closes :attr:`socket`.
    """

    def __init__(self, host, port, *, tls=False, context=None):
        self._host = host
        self._port = port
        self._tls = tls
        self._context = context

        self.state = STATE_AWAITING_DNS
        #: The current socket.  Set during ``awaiting_tcp`` once the
        #: raw socket is built, replaced with the TLS-wrapped or
        #: protocol-wrapped reference at ``awaiting_tls`` / ``ready``,
        #: cleared to ``None`` on ``failed`` / ``cancel``.
        self.socket = None
        #: Set when ``state == "failed"``; ``None`` otherwise.
        self.last_error = None

    # ------------------------------------------------------------------
    # Runner-contract surface
    # ------------------------------------------------------------------

    @property
    def io_socket(self):
        """The connector's socket-ish object for ``Runner.wait``, or ``None``.

        Returns :attr:`socket` as-is once built; the runner unwraps any
        ``.sock`` adapter wrapper to the registrable pollable at the
        poller.  ``None`` until the connector has built its socket and
        after cleanup on ``failed`` / ``cancel``.
        """
        if self.socket is None:
            return None
        return self.socket

    def io_interest(self, now_ms):  # noqa: ARG002 (runner contract)
        """Poll-interest bitmask (``IO_READ`` / ``IO_WRITE``) for ``Runner.wait``.

        Replaces the paired ``io_wants_read`` / ``io_wants_write`` bools.
        A TLS-handshake step both may consume inbound bytes (read) and
        needs writability (write); a bare TCP-connect step needs only
        write; every other phase (DNS resolution, terminal) registers
        nothing.
        """
        if self.state == STATE_AWAITING_TLS:
            return _IO_READ | _IO_WRITE
        if self.state == STATE_AWAITING_TCP:
            return _IO_WRITE
        return 0

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
        """Transition to ``failed`` and close any in-progress socket.

        Subclass ``tick`` overrides call this from their ``except``
        clause on any unexpected error.  The socket close is
        best-effort — a socket whose connect / handshake failed may
        not survive a clean close, so we swallow secondary errors here.
        """
        self.last_error = error
        self.state = STATE_FAILED
        if self.socket is not None:
            try:
                self.socket.close()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
            self.socket = None

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
        if self.socket is not None:
            try:
                self.socket.close()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
            self.socket = None
        self.state = STATE_FAILED
