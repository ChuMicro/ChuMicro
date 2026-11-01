"""``WebSocketClient`` connects to a WebSocket server and exchanges messages one step at a time."""

from chumicro_websockets._session import (
    _IO_READ,
    _IO_WRITE,
    WhenOversized,
    _BaseSession,
    _force_non_blocking,
    _no_callback,
)
from chumicro_websockets._wire import (
    CLOSE_NORMAL,
    DEFAULT_CLOSE_TIMEOUT_MS,
    DEFAULT_HANDSHAKE_TIMEOUT_MS,
    DEFAULT_MAX_INBOUND_QUEUE_SIZE,
    DEFAULT_MAX_MESSAGE_BYTES,
    DEFAULT_MAX_TX_QUEUE_SIZE,
    DEFAULT_PONG_TIMEOUT_MS,
    DEFAULT_RECV_BUDGET_PER_TICK,
    DEFAULT_SEND_BUDGET_PER_TICK,
    OPCODE_PING,
    HandshakeParseState,
    HandshakeResponseParser,
    WebSocketHandshakeError,
    WebSocketState,
    WebSocketStateError,
    derive_accept_key,
    encode_client_handshake,
    make_mask_key,
    make_websocket_key,
    parse_ws_url,
)

__all__ = ["WebSocketClient"]


class ConnectingPhase:
    """Steps a ``WebSocketClient`` takes while its ``state`` is ``CONNECTING``, in order.

    Attributes:
        AWAITING_TRANSPORT: The connector opens the TCP or TLS connection.
        SENDING_HANDSHAKE: The client writes its HTTP upgrade request.
        RECEIVING_HANDSHAKE: The client reads the server's
            ``101 Switching Protocols`` reply.
    """

    AWAITING_TRANSPORT = "awaiting_transport"
    SENDING_HANDSHAKE = "sending_handshake"
    RECEIVING_HANDSHAKE = "receiving_handshake"


class WebSocketClient(_BaseSession):
    """Connects to a ``ws://`` or ``wss://`` WebSocket server, one non-blocking step per loop pass.

    ``connect(url)`` starts the connection and returns at once.  The main
    loop then calls ``check(now_ms)`` and ``handle(now_ms)`` on every pass,
    where ``now_ms`` comes from ``chumicro_timing.ticks_ms()``.  A
    ``chumicro_runner.Runner`` makes both calls itself after
    ``runner.add(client)``.  ``on_open`` fires once ``state`` is ``OPEN``.
    From then on ``send_text()`` and ``send_binary()`` queue messages.
    A client connects once.  After ``CLOSED``, a new connection needs a new
    client.

    Every ``on_*`` callback below starts as a function that does nothing.
    The client calls them from inside ``handle()``.  ``close()`` on a client
    that is still connecting calls ``on_close`` itself.

    Attributes:
        state: The current ``WebSocketState`` value.
        url: The URL passed to ``connect()``, or ``""`` before it.
        last_error: The ``WebSocketError`` behind a failed or timed-out
            connection, or ``None``.
        last_close_code: Status code the connection closed with, such as
            ``CLOSE_NORMAL`` (1000).  ``None`` while the connection runs and
            after a CLOSE frame that carried no code.  A failed connection
            reports ``CLOSE_INTERNAL_ERROR`` (1011).
        last_close_reason: Reason text that came with ``last_close_code``.
        on_open: Called as ``on_open()`` when the opening handshake
            completes.
        on_text: Called as ``on_text(text)`` for each complete text message,
            with ``text`` a ``str`` already checked as valid UTF-8.
        on_binary: Called as ``on_binary(data)`` for each complete binary
            message, with ``data`` as ``bytes``.
        on_ping: Called as ``on_ping(payload)`` when the server sends a PING.
            The client has already queued the PONG reply.
        on_pong: Called as ``on_pong(payload)`` when the server answers a
            PING.
        on_close: Called as ``on_close(code, reason)`` once ``state`` reaches
            ``CLOSED``, after a clean close, a dropped link, or a failed
            connection attempt.
        on_oversized: Called as ``on_oversized(reported_length)`` when a
            message bigger than ``max_message_bytes`` is dropped under
            ``WhenOversized.DROP_WITH_EVENT``.  ``reported_length`` is the
            size in bytes the message's frame headers announced.
    """

    _peer_label = "server"
    _inbound_mask_required = False  # servers MUST NOT mask outbound (RFC 6455 §5.1)

    @classmethod
    def from_config(
        cls,
        config: object,
        *,
        radio: object | None = None,
        ssl_context: object | None = None,
        transport_factory: object | None = None,
        ticks: object | None = None,
        **constructor_kwargs: object,
    ) -> "WebSocketClient":
        """Build a client from a flat config mapping, with a transport from ``chumicro_sockets``.

        With no ``transport_factory`` given, the client opens its TCP or TLS
        connection through ``chumicro_sockets.sockets_factory``.  The only
        config key it reads is ``websockets.client.max_message_bytes``
        (default 16384).

        Args:
            config: A ``dict`` or other mapping with ``get()``.
            radio: The CircuitPython radio, such as ``wifi.radio``.
                MicroPython and CPython ignore it.
            ssl_context: TLS settings for ``wss://`` URLs.  ``None`` checks
                the server's certificate against the runtime's trust roots.
            transport_factory: Connector factory to use instead of the
                default one.
            ticks: Clock object, passed to the constructor.
            **constructor_kwargs: Any other constructor argument.  A keyword
                given here wins over the config value.

        Returns:
            A new ``WebSocketClient`` that has not connected yet.

        Raises:
            RuntimeError: No ``transport_factory`` was given, and
                ``chumicro_sockets.sockets_factory`` is missing from the
                board.
        """
        if transport_factory is None:
            try:
                from chumicro_sockets.sockets_factory import (  # noqa: PLC0415
                    connector_factory,
                )
            except ImportError as exception:
                raise RuntimeError(
                    "chumicro_sockets.sockets_factory not "
                    "available (excluded via __chumicro_skip_factories__ "
                    "or not on the board); pass transport_factory= "
                    "explicitly.",
                ) from exception
            transport_factory = connector_factory(
                radio=radio, ssl_context=ssl_context,
            )
        kwargs = {
            "max_message_bytes": config.get(
                "websockets.client.max_message_bytes",
                DEFAULT_MAX_MESSAGE_BYTES,
            ),
            "ticks": ticks,
        }
        kwargs.update(constructor_kwargs)
        return cls(transport_factory, **kwargs)

    def __init__(
        self,
        transport_factory: object,
        *,
        max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
        recv_budget_per_tick: int = DEFAULT_RECV_BUDGET_PER_TICK,
        send_budget_per_tick: int = DEFAULT_SEND_BUDGET_PER_TICK,
        max_tx_queue_size: int = DEFAULT_MAX_TX_QUEUE_SIZE,
        when_oversized: str = WhenOversized.DROP_WITH_EVENT,
        ping_interval_ms: int | None = None,
        pong_timeout_ms: int = DEFAULT_PONG_TIMEOUT_MS,
        handshake_timeout_ms: int = DEFAULT_HANDSHAKE_TIMEOUT_MS,
        close_timeout_ms: int = DEFAULT_CLOSE_TIMEOUT_MS,
        max_inbound_queue_size: int = DEFAULT_MAX_INBOUND_QUEUE_SIZE,
        ticks: object | None = None,
    ) -> None:
        """Build a client.  Network traffic starts at ``connect()``.

        Args:
            transport_factory: Callable ``(host, port, use_tls)`` that returns
                a connector, an object that opens the TCP or TLS connection
                over several ``tick(now_ms)`` calls.
                ``chumicro_sockets.sockets_factory.connector_factory()``
                builds one.
            max_message_bytes: Largest incoming message, in bytes, the client
                keeps.  A bigger one is dropped under ``when_oversized``.
                Defaults to 16384.
            recv_budget_per_tick: Most bytes one ``handle()`` call reads.
                Defaults to 1024.
            send_budget_per_tick: Most bytes one ``handle()`` call writes.
                Defaults to 1024.
            max_tx_queue_size: Most messages that can wait to be sent.  One
                more ``send_text()`` or ``send_binary()`` raises
                ``WebSocketBackpressureError``.  Defaults to 8.
            when_oversized: A ``WhenOversized`` value.
            ping_interval_ms: Milliseconds between automatic PINGs once the
                connection is ``OPEN``, or ``None`` for no automatic PINGs.
            pong_timeout_ms: Milliseconds a PING may wait for its PONG
                before the connection fails.  Defaults to 30000.
            handshake_timeout_ms: Milliseconds from ``connect()`` until the
                opening handshake must finish.  Defaults to 10000.
            close_timeout_ms: Milliseconds ``close()`` waits for the
                server's CLOSE before dropping the connection.  Defaults to
                5000.
            max_inbound_queue_size: Most messages the ``next_message()``
                queue holds.  Defaults to 16.
            ticks: Clock object with ``ticks_ms()``, ``ticks_add()``, and
                ``ticks_diff()``.  ``None`` selects ``chumicro_timing.ticks``.
        """
        if ticks is None:
            from chumicro_timing import ticks  # noqa: PLC0415 - DI fallback
        # socket is None until connect() fills it in.
        self._init_session_state(
            socket=None,
            max_message_bytes=max_message_bytes,
            recv_budget_per_tick=recv_budget_per_tick,
            send_budget_per_tick=send_budget_per_tick,
            max_tx_queue_size=max_tx_queue_size,
            when_oversized=when_oversized,
            pong_timeout_ms=pong_timeout_ms,
            handshake_timeout_ms=handshake_timeout_ms,
            close_timeout_ms=close_timeout_ms,
            max_inbound_queue_size=max_inbound_queue_size,
            ticks=ticks,
        )

        self._transport_factory = transport_factory
        self._connector = None
        self._ping_interval_ms = ping_interval_ms

        self._connect_called = False
        self._connecting_phase = None
        self.url = ""

        # Captured at connect(), consumed by _on_transport_ready once the socket is live.
        self._pending_handshake_host = None
        self._pending_handshake_port = None
        self._pending_handshake_path = None
        self._pending_handshake_extra_headers = None

        self._handshake_response_parser = None

        self._next_auto_ping_ticks = None

        self.on_open = _no_callback

    def connect(
        self,
        url: str,
        *,
        timeout_ms: int | None = None,
        extra_headers: object | None = None,
    ) -> None:
        """Start connecting to ``url`` and return at once.

        Later ``handle()`` calls open the TCP or TLS connection, send the
        HTTP upgrade request, and read the server's reply.  ``on_open`` fires
        when the handshake completes.  A ``wss://`` URL uses TLS.  A client
        connects once.

        Args:
            url: Server address, such as ``"ws://192.168.1.42:8765/"``.
            timeout_ms: Milliseconds this connection's handshake may take,
                or ``None`` for ``handshake_timeout_ms``.
            extra_headers: Headers to add to the upgrade request, as a
                ``dict`` or an iterable of ``(name, value)`` pairs.  The
                client's own upgrade headers win over a header of the same
                name.

        Raises:
            WebSocketURLError: ``url`` is not a usable ``ws://`` or
                ``wss://`` URL.
            WebSocketStateError: ``connect()`` was already called on this
                client.
        """
        if self._connect_called:
            raise WebSocketStateError(
                f"connect() may only be called once per WebSocketClient; "
                f"current state is {self.state}",
            )
        # Parse first: a malformed URL raises and leaves the client unused.
        scheme, host, port, path = parse_ws_url(url)
        use_tls = scheme == "wss"
        self._connect_called = True
        self.url = url

        self._connector = self._transport_factory(host, port, use_tls)
        # Capture params now; encode the request once the connector hands back a live socket.
        self._pending_handshake_host = host
        self._pending_handshake_port = port
        self._pending_handshake_path = path
        self._pending_handshake_extra_headers = extra_headers

        budget_ms = self._handshake_timeout_ms if timeout_ms is None else timeout_ms
        self._handshake_deadline_ticks = self._ticks.ticks_add(
            self._ticks.ticks_ms(),
            budget_ms,
        )

        self.state = WebSocketState.CONNECTING
        self._connecting_phase = ConnectingPhase.AWAITING_TRANSPORT

    def _on_transport_ready(self, now_ms: int) -> None:  # noqa: ARG002 - hook signature
        self._socket = self._connector.socket
        self._connector = None
        _force_non_blocking(self._socket)

        client_key = make_websocket_key()
        self._handshake_send_buffer = encode_client_handshake(
            self._pending_handshake_host,
            self._pending_handshake_port,
            self._pending_handshake_path,
            client_key,
            extra_headers=self._pending_handshake_extra_headers,
        )
        self._handshake_send_view = memoryview(self._handshake_send_buffer)
        self._handshake_send_offset = 0
        self._handshake_response_parser = HandshakeResponseParser(
            derive_accept_key(client_key),
        )
        self._pending_handshake_host = None
        self._pending_handshake_port = None
        self._pending_handshake_path = None
        self._pending_handshake_extra_headers = None

        self._connecting_phase = ConnectingPhase.SENDING_HANDSHAKE

    def check(self, now_ms: int) -> bool:
        """Return ``True`` when ``handle()`` has work: from ``connect()`` until the connection is ``CLOSED``.

        Args:
            now_ms: Current ``ticks_ms()`` reading.  The client ignores it.
        """
        return self._connect_called and self.state != WebSocketState.CLOSED

    def _connecting_wants_read(self, now_ms) -> bool:
        if self._connecting_phase == ConnectingPhase.AWAITING_TRANSPORT:
            if self._connector is None:
                return False
            return bool(self._connector.io_interest(now_ms) & _IO_READ)
        return self._connecting_phase == ConnectingPhase.RECEIVING_HANDSHAKE

    def _connecting_wants_write(self, now_ms) -> bool:
        if self._connecting_phase == ConnectingPhase.AWAITING_TRANSPORT:
            if self._connector is None:
                return False
            return bool(self._connector.io_interest(now_ms) & _IO_WRITE)
        return self._connecting_phase == ConnectingPhase.SENDING_HANDSHAKE

    @property
    def io_socket(self):
        """Socket ``Runner.wait()`` watches for this client, or ``None`` when there is none to watch.

        While the TCP or TLS connection opens, it is the connector's socket.
        Once ``CLOSED``, it is ``None``.
        """
        # CircuitPython cannot resolve super() inside a property getter,
        # so the base getter's body is inlined.
        if self._connecting_phase == ConnectingPhase.AWAITING_TRANSPORT:
            return self._connector.io_socket if self._connector is not None else None
        if self._socket is None:
            return None
        if self.state == WebSocketState.CLOSED:
            return None
        return self._socket

    def next_deadline(self, now_ms: int) -> int | None:
        """Return the ``ticks_ms()`` value by which ``handle()`` must run, or ``None`` with no timer set.

        While the connector has no socket to watch yet, the client asks for
        ``now_ms``, a turn at once.  After that it reports the nearest of
        its handshake, close, and PONG deadlines and its next automatic
        PING.

        Args:
            now_ms: Current ``ticks_ms()`` reading.
        """
        if (
            self._connecting_phase == ConnectingPhase.AWAITING_TRANSPORT
            and self.io_socket is None
        ):
            return now_ms
        return _BaseSession.next_deadline(self, now_ms)

    def handle(self, now_ms: int) -> None:
        """Do one bounded step of network work, whenever ``check()`` returns ``True``.

        While connecting, one call advances the connector or moves the
        handshake one step.  Once ``OPEN``, one call reads up to
        ``recv_budget_per_tick`` bytes and delivers the messages they
        complete, writes up to ``send_budget_per_tick`` bytes of queued
        frames, and queues an automatic PING when one is due.  Callbacks run
        inside this call.  A timeout, a protocol error, or a socket error
        closes the connection and lands in ``last_error`` instead of raising.
        An exception a callback raises propagates out of ``handle()``.

        Args:
            now_ms: Current ``ticks_ms()`` reading.  Every deadline is
                measured against it.
        """
        if self.state == WebSocketState.CLOSED or not self._connect_called:
            return

        # Timeouts first: an expired handshake / close / pong overrides other work.
        if self._check_timeouts(now_ms):
            return

        if self.state == WebSocketState.CONNECTING:
            if self._connecting_phase == ConnectingPhase.AWAITING_TRANSPORT:
                self._advance_connector(now_ms)
            elif self._connecting_phase == ConnectingPhase.SENDING_HANDSHAKE:
                self._send_handshake_chunk(now_ms)
            elif self._connecting_phase == ConnectingPhase.RECEIVING_HANDSHAKE:
                self._receive_handshake_chunk(now_ms)
            return

        # Drain inbound first: the peer may have sent a CLOSE we must acknowledge.
        self._drain_inbound(now_ms)
        self._drain_outbound()

        if self.state == WebSocketState.OPEN:
            self._maybe_emit_auto_ping(now_ms)

    def _advance_connector(self, now_ms: int) -> None:
        connector = self._connector
        connector.tick(now_ms)
        if connector.state == "ready":
            self._on_transport_ready(now_ms)
            return
        if connector.state == "failed":
            error = connector.last_error
            self._connector = None
            self._fail_with_error(
                WebSocketStateError(f"connector failed: {error}"),
            )

    def _outbound_mask(self):
        # Clients MUST mask outbound frames (RFC 6455 §5.1).
        return make_mask_key()

    def _on_handshake_send_complete(self, now_ms: int) -> None:  # noqa: ARG002 - hook signature
        self._connecting_phase = ConnectingPhase.RECEIVING_HANDSHAKE

    def close(self, code: int = CLOSE_NORMAL, reason: str = "") -> None:
        """Close the connection, or abandon a connection attempt still in progress.

        An ``OPEN`` client queues a CLOSE frame and moves to ``CLOSING``.
        Later ``handle()`` calls send it and wait up to ``close_timeout_ms``
        for the server's CLOSE.  Then ``on_close`` fires.  A client still
        ``CONNECTING`` drops the connection at once, moves to ``CLOSED``,
        and calls ``on_close(code, reason)`` before returning.

        Args:
            code: Status code for the server, one of the ``CLOSE_*``
                constants, such as ``CLOSE_NORMAL`` (1000) or
                ``CLOSE_GOING_AWAY`` (1001).
            reason: Short text for the server, at most 123 bytes in UTF-8.

        Raises:
            WebSocketStateError: ``state`` is already ``CLOSING`` or
                ``CLOSED``.
        """
        if self.state in (WebSocketState.CLOSING, WebSocketState.CLOSED):
            raise WebSocketStateError(
                f"close() not allowed in state {self.state}",
            )
        if self.state == WebSocketState.CONNECTING:
            if self.last_close_code is None:
                self.last_close_code = code
                self.last_close_reason = reason
            self._drop_transport()
            self._on_finalized()
            self.on_close(self.last_close_code, self.last_close_reason)
            return
        self._send_close(code, reason, None)

    def _on_finalized(self) -> None:
        self._handshake_deadline_ticks = None
        self._next_auto_ping_ticks = None
        if self._connector is not None:
            # Cancel a still-held connector so its half-open socket doesn't leak the pool.
            try:
                self._connector.cancel()
            except Exception:  # noqa: BLE001 - best-effort connector teardown
                pass
            self._connector = None
        self._connecting_phase = None

    def _receive_handshake_chunk(self, now_ms: int) -> None:
        chunk = self._recv_chunk(self._recv_budget_per_tick)
        if chunk is None:
            return
        if not chunk:
            self._fail_with_error(
                WebSocketHandshakeError(
                    "peer closed connection mid-handshake",
                ),
            )
            return
        try:
            self._handshake_response_parser.feed(chunk)
        except WebSocketHandshakeError as handshake_error:
            self._fail_with_error(handshake_error)
            return
        if self._handshake_response_parser.state == HandshakeParseState.DONE:
            self._post_handshake_carry = self._handshake_response_parser.leftover
            self._handshake_send_view = None
            self._handshake_send_buffer = None
            self._handshake_response_parser = None
            self._connecting_phase = None
            self._handshake_deadline_ticks = None
            self.state = WebSocketState.OPEN
            self._arm_auto_ping(now_ms)
            self.on_open()
            # The peer may have piggybacked frame bytes after the handshake; drain the carry.
            if self._post_handshake_carry:
                self._feed_frame_bytes(self._post_handshake_carry, now_ms)
                self._post_handshake_carry = b""

    def _arm_auto_ping(self, now_ms: int) -> None:
        if self._ping_interval_ms is None:
            return
        self._next_auto_ping_ticks = self._ticks.ticks_add(
            now_ms,
            self._ping_interval_ms,
        )

    def _maybe_emit_auto_ping(self, now_ms: int) -> None:
        if self._next_auto_ping_ticks is None:
            return
        if self._ticks.ticks_diff(self._next_auto_ping_ticks, now_ms) > 0:
            return
        self._enqueue_internal_frame(OPCODE_PING, b"")
        self._arm_pong_deadline(now_ms)
        self._next_auto_ping_ticks = self._ticks.ticks_add(
            now_ms,
            self._ping_interval_ms,
        )
