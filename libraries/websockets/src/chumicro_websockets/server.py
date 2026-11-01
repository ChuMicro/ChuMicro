"""``WebSocketServer`` accepts WebSocket clients and runs each as a ``Connection``, one step at a time."""

import errno

try:
    from micropython import const
except ImportError:
    def const(value):
        return value

from chumicro_websockets._session import (
    _IO_READ,
    WhenOversized,
    _BaseSession,
    _force_non_blocking,
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
    HandshakeParseState,
    HandshakeRequestParser,
    WebSocketError,
    WebSocketHandshakeError,
    WebSocketState,
    WebSocketStateError,
    encode_server_handshake_response,
    encode_server_rejection,
)

# Caps Runner.wait while a connection is in flight, so an unpolled
# connection socket keeps advancing.
_CONNECTION_PROGRESS_INTERVAL_MS = const(20)


class ServerHandshakePhase:
    """Steps a ``Connection`` takes while its ``state`` is ``CONNECTING``, in order.

    Attributes:
        READING_REQUEST: The connection reads the client's HTTP upgrade
            request.
        SENDING_RESPONSE: The connection writes the
            ``101 Switching Protocols`` reply.
    """

    READING_REQUEST = "reading_request"
    SENDING_RESPONSE = "sending_response"


class Connection(_BaseSession):
    """One client connected to a ``WebSocketServer``, handed to the server's ``on_connection`` callback.

    The server builds a ``Connection`` for each accepted socket and runs the
    opening handshake.  Once the connection is ``OPEN``, the server calls
    ``on_connection(connection)``, the place to set the callbacks below.  The
    server also calls ``handle()`` on every connection, so a program adds
    only the server to its runner.  ``send_text()`` and ``send_binary()``
    queue messages to this client.

    Every ``on_*`` callback below starts as a function that does nothing.
    The server calls them from inside its own ``handle()``.  A client the
    server turns away during the handshake never reaches ``on_connection``.
    No callback fires for that client.

    Attributes:
        state: The current ``WebSocketState`` value.
        request_path: Path from the client's request, such as ``"/ws"``,
            with any query string.  ``""`` until the handshake request
            arrives.
        request_headers: Headers of the client's upgrade request, or
            ``None`` before the request arrives.
            ``request_headers.get("Origin")`` looks one up by name in any
            letter case.
        last_error: The ``WebSocketError`` behind a failed, refused, or
            timed-out connection, or ``None``.
        last_close_code: Status code the connection closed with, or ``None``
            while it runs and after a CLOSE frame that carried no code.  A
            failed connection reports ``CLOSE_INTERNAL_ERROR`` (1011).
        last_close_reason: Reason text that came with ``last_close_code``.
        on_text: Called as ``on_text(text)`` for each complete text message
            from the client, with ``text`` a ``str``.
        on_binary: Called as ``on_binary(data)`` for each complete binary
            message from the client, with ``data`` as ``bytes``.
        on_ping: Called as ``on_ping(payload)`` when the client sends a
            PING, after the PONG reply is queued.
        on_pong: Called as ``on_pong(payload)`` when the client answers a
            PING from ``send_ping()``.
        on_close: Called as ``on_close(code, reason)`` once ``state`` reaches
            ``CLOSED``.
        on_oversized: Called as ``on_oversized(reported_length)`` when a
            message bigger than ``max_message_bytes`` is dropped under
            ``WhenOversized.DROP_WITH_EVENT``.
    """

    _peer_label = "client"
    _inbound_mask_required = True  # clients MUST mask outbound (RFC 6455 §5.1)

    def __init__(
        self,
        socket,
        now_ms: int,
        *,
        accept_path: str | None,
        max_message_bytes: int,
        recv_budget_per_tick: int,
        send_budget_per_tick: int,
        max_tx_queue_size: int,
        when_oversized: str,
        pong_timeout_ms: int,
        handshake_timeout_ms: int,
        close_timeout_ms: int,
        ticks,
        on_connection_callback,
        max_inbound_queue_size: int = DEFAULT_MAX_INBOUND_QUEUE_SIZE,
    ) -> None:
        _force_non_blocking(socket)
        self._init_session_state(
            socket=socket,
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

        self._accept_path = accept_path
        self._on_connection_callback = on_connection_callback

        self._handshake_phase = ServerHandshakePhase.READING_REQUEST
        self._handshake_request_parser = HandshakeRequestParser()
        self._handshake_deadline_ticks = self._ticks.ticks_add(
            now_ms,
            handshake_timeout_ms,
        )

        self.request_path = ""
        self.request_headers = None

    def check(self, now_ms: int) -> bool:  # noqa: ARG002 - runner contract
        """Return ``True`` until the connection is ``CLOSED``.

        Args:
            now_ms: Current ``ticks_ms()`` reading.  The connection ignores
                it.
        """
        return self.state != WebSocketState.CLOSED

    def _connecting_wants_read(self, now_ms) -> bool:  # noqa: ARG002 - runner contract
        return self._handshake_phase == ServerHandshakePhase.READING_REQUEST

    def _connecting_wants_write(self, now_ms) -> bool:  # noqa: ARG002 - runner contract
        return self._handshake_phase == ServerHandshakePhase.SENDING_RESPONSE

    def handle(self, now_ms: int) -> None:
        """Do one bounded step of work for this connection.  ``WebSocketServer.handle()`` calls it.

        During the handshake, one call reads part of the client's request or
        writes part of the reply.  Once ``OPEN``, one call reads up to
        ``recv_budget_per_tick`` bytes and delivers the messages they
        complete, then writes up to ``send_budget_per_tick`` bytes of queued
        frames.

        Args:
            now_ms: Current ``ticks_ms()`` reading.
        """
        if self.state == WebSocketState.CLOSED:
            return

        if self._check_timeouts(now_ms):
            return

        if self.state == WebSocketState.CONNECTING:
            if self._handshake_phase == ServerHandshakePhase.READING_REQUEST:
                self._receive_handshake_chunk()
            elif self._handshake_phase == ServerHandshakePhase.SENDING_RESPONSE:
                self._send_handshake_chunk(now_ms)
            return

        # Drain inbound first: the peer may have sent a CLOSE we must acknowledge.
        self._drain_inbound(now_ms)
        self._drain_outbound()

    def _outbound_mask(self):
        # Servers MUST NOT mask outbound frames (RFC 6455 §5.1).
        return None

    def _on_finalized(self) -> None:
        self._handshake_deadline_ticks = None

    def _receive_handshake_chunk(self) -> None:
        chunk = self._recv_chunk(self._recv_budget_per_tick)
        if chunk is None:
            return
        if not chunk:
            self._fail_with_error(
                WebSocketHandshakeError(
                    "client closed connection mid-handshake",
                ),
            )
            return
        try:
            self._handshake_request_parser.feed(chunk)
        except WebSocketHandshakeError as handshake_error:
            self._reject(400, "Bad Request", str(handshake_error))
            return
        if self._handshake_request_parser.state != HandshakeParseState.DONE:
            return
        if (
            self._accept_path is not None
            and self._handshake_request_parser.path != self._accept_path
        ):
            self._reject(
                404,
                "Not Found",
                f"path {self._handshake_request_parser.path!r} not handled",
            )
            return
        self._handshake_send_buffer = encode_server_handshake_response(
            self._handshake_request_parser.client_key,
        )
        self._handshake_send_view = memoryview(self._handshake_send_buffer)
        self._handshake_send_offset = 0
        self.request_path = self._handshake_request_parser.path
        self.request_headers = self._handshake_request_parser.headers
        self._post_handshake_carry = self._handshake_request_parser.leftover
        self._handshake_phase = ServerHandshakePhase.SENDING_RESPONSE

    def _on_handshake_send_complete(self, now_ms: int) -> None:
        self._enter_open(now_ms)

    def _enter_open(self, now_ms: int) -> None:
        self._handshake_request_parser = None
        self._handshake_send_view = None
        self._handshake_send_buffer = None
        self._handshake_phase = None
        self._handshake_deadline_ticks = None
        self.state = WebSocketState.OPEN
        # Hand off to the user's callback; a raising callback closes us with CLOSE_INTERNAL_ERROR.
        try:
            self._on_connection_callback(self)
        except Exception as callback_error:  # noqa: BLE001 - user code
            self._fail_with_error(
                WebSocketError(
                    f"on_connection callback raised: {callback_error!r}",
                ),
            )
            return
        # The client may have piggybacked frame bytes after the request; drain the carry.
        if self._post_handshake_carry:
            self._feed_frame_bytes(self._post_handshake_carry, now_ms)
            self._post_handshake_carry = b""

    def _reject(self, status_code: int, reason_phrase: str, message: str) -> None:
        self._send_rejection_response(
            status_code, reason_phrase, message.encode("utf-8"),
        )
        self.last_error = WebSocketHandshakeError(message)

    def _send_rejection_response(
        self,
        status_code: int,
        reason_phrase: str,
        body: bytes,
    ) -> None:
        response = encode_server_rejection(status_code, reason_phrase, body=body)
        try:
            self._socket.send(response)
        except Exception:  # noqa: BLE001 - best-effort
            pass
        self._drop_transport()
        # No on_close here: the callback's contract is a WebSocket close code,
        # and user code only wires it inside on_connection, which a rejected
        # handshake never reaches.


class WebSocketServer:
    """Listens for WebSocket clients and runs each as a ``Connection``, one non-blocking step per loop pass.

    The main loop calls ``check(now_ms)`` and ``handle(now_ms)`` on every
    pass, where ``now_ms`` comes from ``chumicro_timing.ticks_ms()``.  A
    ``chumicro_runner.Runner`` makes both calls itself after
    ``runner.add(server)``.  Each ``handle()`` call accepts waiting clients
    and gives every ``Connection`` one turn.  ``on_connection(connection)``
    runs once per client, when its opening handshake completes.

    Attributes:
        io_socket: The listening socket, or ``None`` before the first
            ``handle()`` opens it from ``listener_factory`` and after
            ``close()``.
        closed: ``True`` after ``close()``.
        last_error: The most recent ``OSError`` from accepting a client,
            or ``None``.  The server keeps listening after one.
    """

    @classmethod
    def from_config(
        cls,
        config: object,
        on_connection: object,
        *,
        radio: object | None = None,
        listener: object | None = None,
        listener_factory: object | None = None,
        accept_path: str | None = None,
        max_connections: int = 2,
        ticks: object | None = None,
        **constructor_kwargs: object,
    ) -> "WebSocketServer":
        """Build a server from a flat config mapping, listening on the config's host and port.

        With neither ``listener`` nor ``listener_factory`` given, the server
        listens through ``chumicro_sockets.sockets_factory`` on
        ``websockets.server.host`` (default ``"0.0.0.0"``, every interface)
        and ``websockets.server.port`` (default 8765).  The listening socket
        opens at the first ``handle()``, so building the server touches no
        network.  The server also reads
        ``websockets.server.max_message_bytes`` (default 16384).

        Args:
            config: A ``dict`` or other mapping with ``get()``.
            on_connection: Called as ``on_connection(connection)`` once per
                client, when its opening handshake completes.
            radio: The CircuitPython radio, such as ``wifi.radio``.
                MicroPython and CPython ignore it.
            listener: Open listening socket to use instead of the config's
                address.
            listener_factory: Zero-argument callable that returns a
                listening socket, used instead of the config's address.
            accept_path: Request path to accept, such as ``"/ws"``, or
                ``None`` to accept every path.
            max_connections: Most clients connected at once.
            ticks: Clock object, passed to the constructor.
            **constructor_kwargs: Any other constructor argument.  A keyword
                given here wins over the config value.

        Returns:
            A new ``WebSocketServer``.

        Raises:
            RuntimeError: Neither ``listener`` nor ``listener_factory`` was
                given, and ``chumicro_sockets.sockets_factory`` is missing
                from the board.
        """
        if listener is None and listener_factory is None:
            # Lazy import so a client-only deploy never pulls chumicro_sockets onto the board.
            try:
                from chumicro_sockets.sockets_factory import (  # noqa: PLC0415 - lazy
                    listener_factory as sockets_listener_factory,
                )
            except ImportError as exception:
                raise RuntimeError(
                    "chumicro_sockets.sockets_factory not available "
                    "(excluded via __chumicro_skip_factories__ or "
                    "not on the board); pass listener= or "
                    "listener_factory= explicitly.",
                ) from exception
            listener_factory = sockets_listener_factory(
                config.get("websockets.server.host", "0.0.0.0"),
                config.get("websockets.server.port", 8765),
                radio=radio,
            )
        kwargs = {
            "listener": listener,
            "listener_factory": listener_factory,
            "on_connection": on_connection,
            "max_connections": max_connections,
            "accept_path": accept_path,
            "max_message_bytes": config.get(
                "websockets.server.max_message_bytes",
                DEFAULT_MAX_MESSAGE_BYTES,
            ),
            "ticks": ticks,
        }
        kwargs.update(constructor_kwargs)
        return cls(**kwargs)

    def __init__(
        self,
        listener: object | None = None,
        on_connection: object | None = None,
        *,
        listener_factory: object | None = None,
        max_connections: int = 2,
        accept_path: str | None = None,
        max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
        recv_budget_per_tick: int = DEFAULT_RECV_BUDGET_PER_TICK,
        send_budget_per_tick: int = DEFAULT_SEND_BUDGET_PER_TICK,
        max_tx_queue_size: int = DEFAULT_MAX_TX_QUEUE_SIZE,
        when_oversized: str = WhenOversized.DROP_WITH_EVENT,
        pong_timeout_ms: int = DEFAULT_PONG_TIMEOUT_MS,
        handshake_timeout_ms: int = DEFAULT_HANDSHAKE_TIMEOUT_MS,
        close_timeout_ms: int = DEFAULT_CLOSE_TIMEOUT_MS,
        max_inbound_queue_size: int = DEFAULT_MAX_INBOUND_QUEUE_SIZE,
        ticks: object | None = None,
    ) -> None:
        """Build a server.  Every argument after ``accept_path`` applies to each ``Connection`` separately.

        Args:
            listener: Open listening socket with ``accept()`` and
                ``close()``, such as one from ``chumicro_sockets.listener()``.
                Pass ``listener`` or ``listener_factory``, never both.
            on_connection: Called as ``on_connection(connection)`` once per
                client, when its opening handshake completes.  Required.
            listener_factory: Zero-argument callable that returns a listening
                socket.  The server calls it at the first ``handle()``.
            max_connections: Most clients connected at once.  At the limit
                the server stops accepting until a connection closes.
            accept_path: Request path to accept, such as ``"/ws"``, or
                ``None`` to accept every path.  A client asking for another
                path gets an HTTP 404 reply.
            max_message_bytes: Largest incoming message, in bytes, a
                connection keeps.  A bigger one is dropped under
                ``when_oversized``.  Defaults to 16384.
            recv_budget_per_tick: Most bytes one connection reads per
                ``handle()``.  Defaults to 1024.
            send_budget_per_tick: Most bytes one connection writes per
                ``handle()``.  Defaults to 1024.
            max_tx_queue_size: Most messages that can wait to be sent on one
                connection.  Defaults to 8.
            when_oversized: A ``WhenOversized`` value.
            pong_timeout_ms: Milliseconds a PING from ``send_ping()`` may
                wait for its PONG before the connection fails.  Defaults to
                30000.
            handshake_timeout_ms: Milliseconds from accept until the opening
                handshake must finish.  Defaults to 10000.
            close_timeout_ms: Milliseconds ``close()`` waits for the client's
                CLOSE before dropping the connection.  Defaults to 5000.
            max_inbound_queue_size: Most messages each connection's
                ``next_message()`` queue holds.  Defaults to 16.
            ticks: Clock object with ``ticks_ms()``, ``ticks_add()``, and
                ``ticks_diff()``.  ``None`` selects ``chumicro_timing.ticks``.

        Raises:
            ValueError: The call passed both or neither of ``listener`` and
                ``listener_factory``, or ``on_connection`` is ``None``.
        """
        if (listener is None) == (listener_factory is None):
            raise ValueError(
                "provide exactly one of listener= or listener_factory= "
                "(the factory defers the bind to the first handle() tick)"
            )
        if on_connection is None:
            raise ValueError("on_connection is required")
        self.io_socket = listener
        self._listener_factory = listener_factory
        self._on_connection = on_connection
        self._max_connections = max_connections
        self._accept_path = accept_path
        self._max_message_bytes = max_message_bytes
        self._recv_budget_per_tick = recv_budget_per_tick
        self._send_budget_per_tick = send_budget_per_tick
        self._max_tx_queue_size = max_tx_queue_size
        self._when_oversized = when_oversized
        self._pong_timeout_ms = pong_timeout_ms
        self._handshake_timeout_ms = handshake_timeout_ms
        self._close_timeout_ms = close_timeout_ms
        self._max_inbound_queue_size = max_inbound_queue_size

        if ticks is None:
            from chumicro_timing import ticks  # noqa: PLC0415 - DI fallback
        self._ticks = ticks

        self._connections: list[Connection] = []
        self.closed = False
        self.last_error: BaseException | None = None

    @property
    def connections(self) -> tuple:
        """Every ``Connection`` the server holds right now, as a new tuple.

        The tuple includes connections still in the opening handshake.
        ``send_text()`` on one of those raises ``WebSocketStateError``.
        """
        return tuple(self._connections)

    @property
    def connection_count(self) -> int:
        """Number of connections the server holds right now, without building the ``connections`` tuple."""
        return len(self._connections)

    def io_interest(self, now_ms: int) -> int:  # noqa: ARG002 - runner contract
        """Return the socket events ``Runner.wait()`` should wake for on the listening socket.

        The server returns ``1``, asking to wake when the listening socket is
        readable, while it is open, its listening socket exists, and it holds
        fewer than ``max_connections`` connections.  A readable listening
        socket has a client waiting to be accepted.  Otherwise the server
        returns ``0``.

        Args:
            now_ms: Current ``ticks_ms()`` reading.  The server ignores it.
        """
        if self.closed or self.io_socket is None:
            return 0
        return _IO_READ if len(self._connections) < self._max_connections else 0

    def next_deadline(self, now_ms: int) -> int | None:
        """Return the ``ticks_ms()`` value by which ``handle()`` must run, or ``None`` with no connections.

        ``Runner.wait()`` watches only the listening socket, never the
        connection sockets.  While any connection exists, the server asks for
        a turn within 20 ms so the connections keep moving, or sooner when a
        connection deadline falls earlier.

        Args:
            now_ms: Current ``ticks_ms()`` reading.
        """
        if self.closed or not self._connections:
            return None
        ticks_diff = self._ticks.ticks_diff
        nearest = self._ticks.ticks_add(now_ms, _CONNECTION_PROGRESS_INTERVAL_MS)
        for connection in self._connections:
            candidate = connection.next_deadline(now_ms)
            if candidate is not None and ticks_diff(candidate, nearest) < 0:
                nearest = candidate
        return nearest

    def close(self) -> None:
        """Close the listening socket and every connection, and mark the server ``closed``.

        Each ``OPEN`` connection writes a CLOSE frame with ``CLOSE_NORMAL``
        and the reason ``"server shutting down"``, as far as its socket
        accepts it.  The server then drops every connection without waiting
        for replies.  Each connection's ``on_close`` fires before ``close()``
        returns.  A closed server stays closed.
        """
        if self.closed:
            return
        if self.io_socket is not None:
            try:
                self.io_socket.close()
            except Exception:  # noqa: BLE001 - best-effort
                pass
            self.io_socket = None
        for connection in list(self._connections):
            if connection.state == WebSocketState.CONNECTING:
                # No 101 has gone out yet, so a CLOSE frame would precede the
                # handshake on the wire; just drop the socket.
                connection._finalize_closed()
                continue
            if connection.state != WebSocketState.CLOSED:
                try:
                    connection.close(CLOSE_NORMAL, "server shutting down")
                except WebSocketStateError:
                    pass
                # Force-finalize so on_close fires even when the close handshake can't complete.
                connection._finalize_closed()
        self._connections.clear()
        self.closed = True

    def check(self, now_ms: int) -> bool:  # noqa: ARG002 - runner contract
        """Return ``True`` when ``handle()`` has work to do: from construction until ``close()``.

        Args:
            now_ms: Current ``ticks_ms()`` reading.  The server ignores it.
        """
        return not self.closed

    def handle(self, now_ms: int) -> None:
        """Accept waiting clients and give every connection one bounded step of work.

        The first call opens the listening socket from ``listener_factory``.
        An error opening it raises from that call.  Each call accepts
        clients until ``max_connections`` is reached or none are waiting,
        then calls ``handle()`` on every connection and drops the ones that
        reached ``CLOSED``.

        Args:
            now_ms: Current ``ticks_ms()`` reading, passed to every
                connection.
        """
        if self.closed:
            return
        if self.io_socket is None:
            self.io_socket = self._listener_factory()
            _force_non_blocking(self.io_socket)
        self._accept_pending(now_ms)
        # Reverse index walk: closed connections pop in place with no per-tick
        # list copy and no membership re-scans.
        connections = self._connections
        for connection_index in range(len(connections) - 1, -1, -1):
            connection = connections[connection_index]
            if connection.state == WebSocketState.CLOSED:
                connections.pop(connection_index)
                continue
            connection.handle(now_ms)
            # A callback may call server.close(), clearing every connection; stop if so.
            if self.closed:
                return
            if connection.state == WebSocketState.CLOSED:
                connections.pop(connection_index)

    def _accept_pending(self, now_ms: int) -> None:
        while True:
            if len(self._connections) >= self._max_connections:
                return
            try:
                accepted = self.io_socket.accept()
            except OSError as accept_error:
                if accept_error.errno == errno.EAGAIN:
                    return
                self.last_error = accept_error
                return
            if accepted is None:
                return
            client_socket, _address = accepted
            connection = Connection(
                client_socket,
                now_ms,
                accept_path=self._accept_path,
                max_message_bytes=self._max_message_bytes,
                recv_budget_per_tick=self._recv_budget_per_tick,
                send_budget_per_tick=self._send_budget_per_tick,
                max_tx_queue_size=self._max_tx_queue_size,
                when_oversized=self._when_oversized,
                pong_timeout_ms=self._pong_timeout_ms,
                handshake_timeout_ms=self._handshake_timeout_ms,
                close_timeout_ms=self._close_timeout_ms,
                max_inbound_queue_size=self._max_inbound_queue_size,
                ticks=self._ticks,
                on_connection_callback=self._on_connection,
            )
            self._connections.append(connection)
