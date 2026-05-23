"""``SocketConnector`` — tick-driven non-blocking connect state machine.

The non-blocking counterpart to ``tcp_client_socket`` / ``tls_client_socket``.
Library methods that perform network I/O do not block: a runner-shaped
library constructs a connector and advances it across ticks instead of
calling a synchronous factory.  The synchronous factory stays for
non-runner contexts (one-shot scripts, REPL, ``main`` before the runner
loop starts).

Each call to :meth:`SocketConnector.tick` advances one phase:

* ``awaiting_dns`` — resolve ``host`` to an address.
* ``awaiting_tcp`` — non-blocking TCP connect; first tick issues the
  connect, subsequent ticks poll for completion (POLLOUT + SO_ERROR).
* ``awaiting_tls`` — TLS handshake step; loops until done or `WantRead` /
  `WantWrite` (the connector yields between handshake rounds).
* ``ready`` — terminal; :attr:`socket` is set.
* ``failed`` — terminal; :attr:`last_error` is set.

The base class implements the runtime-agnostic state-machine driving,
the runner-contract surface (``check`` / ``handle`` / ``io_*`` /
``next_deadline`` / ``cancel``), and the OSError → ``failed`` trapping.
Per-runtime subclasses override :meth:`_resolve_dns`,
:meth:`_start_tcp_connect`, :meth:`_check_tcp_connect`,
:meth:`_wrap_tls`, and :meth:`_step_tls_handshake` with the
runtime-specific calls.  ``next_deadline`` returns ``None`` — the
connector does not time out on its own; consumers wrap the connect in
an outer deadline.
"""

#: Source bundle.  Pure-Python state machine; runs on every runtime.
#  (No ``__chumicro_runtimes__`` marker — adapter subclasses carry
#  their own runtime markers in ``_adapters/<runtime>.py``.)


STATE_AWAITING_DNS = "awaiting_dns"
STATE_AWAITING_TCP = "awaiting_tcp"
STATE_AWAITING_TLS = "awaiting_tls"
STATE_READY = "ready"
STATE_FAILED = "failed"

_NON_TERMINAL = (STATE_AWAITING_DNS, STATE_AWAITING_TCP, STATE_AWAITING_TLS)
_TERMINAL = (STATE_READY, STATE_FAILED)


class SocketConnector:
    """Tick-driven non-blocking connect.

    Constructor stores the dial parameters; ``tick(now_ms)`` advances
    one phase per call.  Subclasses provide the runtime-specific
    advance methods (DNS resolve, async TCP connect, TLS handshake
    step).  See module docstring for the state diagram and rationale.
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
        # ``ready``; closed in :meth:`cancel`.
        self._inflight_socket = None
        # Resolved address info from DNS; consumed by the TCP step.
        # Shape is adapter-specific (CPython uses tuples from
        # ``getaddrinfo``; CP uses host/port directly).
        self._addr_info = None

    # ------------------------------------------------------------------
    # Runner-contract surface
    # ------------------------------------------------------------------

    @property
    def io_socket(self):
        """Underlying pollable while the handshake is in flight, else ``None``.

        ``Runner.wait`` reads this to register the right socket with
        ``ipoll``.  Terminal states return ``None`` so the runner
        doesn't keep waking on a dead handle.
        """
        if self.state in _TERMINAL:
            return None
        if self._inflight_socket is None:
            return None
        return getattr(self._inflight_socket, "_sock", self._inflight_socket)

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

        Consumers wrap the connect attempt in an outer deadline (e.g.
        ``ack_timeout_seconds`` for MQTT CONNECT).  ``None`` here lets
        the runner's ``wait`` park indefinitely until ``io_*`` fires or
        another service's deadline elapses.
        """
        return None

    # ------------------------------------------------------------------
    # Driver
    # ------------------------------------------------------------------

    def tick(self, now_ms):
        """Advance the state machine by one phase.

        Any exception other than ``BlockingIOError`` / EAGAIN-style
        soft errors transitions to ``failed`` with the error captured
        in ``last_error``.
        """
        if self.state in _TERMINAL:
            return
        try:
            if self.state == STATE_AWAITING_DNS:
                self._addr_info = self._resolve_dns(self._host, self._port)
                self.state = STATE_AWAITING_TCP
                return
            if self.state == STATE_AWAITING_TCP:
                if self._inflight_socket is None:
                    self._inflight_socket = self._start_tcp_connect(self._addr_info)
                if not self._check_tcp_connect(self._inflight_socket):
                    return
                self._enter_post_tcp()
                return
            if self.state == STATE_AWAITING_TLS:
                if self._step_tls_handshake(self._inflight_socket):
                    self.socket = self._inflight_socket
                    self._inflight_socket = None
                    self.state = STATE_READY
                return
        except Exception as error:  # noqa: BLE001 - any failure stops the machine
            self._fail(error)

    def _enter_post_tcp(self):
        """TCP done — either wrap for TLS or land in ``ready``."""
        if not self._tls:
            self.socket = self._inflight_socket
            self._inflight_socket = None
            self.state = STATE_READY
            return
        self._inflight_socket = self._wrap_tls(
            self._inflight_socket, self._host, self._context,
        )
        self.state = STATE_AWAITING_TLS

    def _fail(self, error):
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
        abort a connect attempt (e.g. ``MQTTClient.disconnect()``
        called while in ``AWAITING_TRANSPORT``).
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

    # ------------------------------------------------------------------
    # Per-runtime overrides
    # ------------------------------------------------------------------

    def _resolve_dns(self, host, port):
        """Return adapter-specific address info for the TCP step.

        Most runtimes resolve synchronously in one tick.  Subclasses
        return whatever shape :meth:`_start_tcp_connect` expects.
        """
        raise NotImplementedError

    def _start_tcp_connect(self, addr_info):
        """Create a non-blocking socket and issue ``connect``.

        Returns the in-progress socket object; raise ``OSError`` on
        immediate failure.  Implementations that block to completion
        (CP socketpool) leave the socket fully connected — the
        ``_check_tcp_connect`` call following this MUST return ``True``
        on that substrate.
        """
        raise NotImplementedError

    def _check_tcp_connect(self, sock):
        """Return ``True`` when the in-progress connect has completed.

        ``False`` means "not yet, try again next tick."  Raise
        ``OSError`` (or runtime-equivalent) when the connect attempt
        has failed.  Substrates that block to completion in
        ``_start_tcp_connect`` return ``True`` here.
        """
        raise NotImplementedError

    def _wrap_tls(self, sock, host, context):
        """Wrap *sock* for TLS, returning the SSL socket object.

        Should set ``do_handshake_on_connect=False`` where the
        substrate supports it so the handshake can be driven by
        :meth:`_step_tls_handshake` across multiple ticks.  Substrates
        that hand-shake inline at wrap time (MP without
        ``do_handshake_on_connect``, CP) return a fully-handshaken
        socket and the following ``_step_tls_handshake`` call MUST
        return ``True``.
        """
        raise NotImplementedError

    def _step_tls_handshake(self, sock):
        """Run one TLS handshake step.

        Return ``True`` when the handshake is complete.  Return
        ``False`` (or raise the runtime's want-read / want-write
        sentinel and let :meth:`tick` swallow it as a non-terminal
        condition) when the handshake needs another round.
        """
        raise NotImplementedError
