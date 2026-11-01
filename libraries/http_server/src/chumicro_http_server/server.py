"""``chumicro_http_server.server`` defines ``HttpServer``, the ``Request`` a route handler
receives, and the ``Response`` it returns.

``build_response`` makes a ``Response``, and ``encode_response`` turns one
into the bytes the server sends.
"""

import errno
import json

from chumicro_http_server._wire import (
    _PARSER_TERMINAL_STATES,
    CRLF,
    DEFAULT_MAX_CONNECTIONS,
    DEFAULT_MAX_HEADERS_BYTES,
    DEFAULT_MAX_REQUEST_BODY_BYTES,
    DEFAULT_MAX_REQUEST_LINE_BYTES,
    DEFAULT_RECV_BUDGET_PER_TICK,
    DEFAULT_REQUEST_TIMEOUT_MS,
    DEFAULT_SEND_BUDGET_PER_TICK,
    DEFAULT_STREAM_BUFFER_SIZE,
    CaseInsensitiveDict,
    RequestParser,
    RequestParseState,
    ServerError,
    ServerLimitError,
    ServerProtocolError,
    parse_charset,
    parse_query,
    split_target,
)

# Mirrors chumicro_runner.IO_READ; a literal to avoid a dependency on the runner.
_IO_READ = 1

# Caps Runner.wait while a connection is in flight, so an unpolled socket keeps advancing.
_CONNECTION_PROGRESS_INTERVAL_MS = 20

# Pre-encoded 500 fallback for when a handler's own Response can't be encoded.
_ENCODED_500_ERROR = (
    b"HTTP/1.1 500 Internal Server Error\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n"
    b"Content-Length: 21\r\n"
    b"Connection: close\r\n"
    b"\r\n"
    b"Internal Server Error"
)

_REASONS = {
    200: "OK",
    201: "Created",
    204: "No Content",
    301: "Moved Permanently",
    302: "Found",
    400: "Bad Request",
    404: "Not Found",
    405: "Method Not Allowed",
    413: "Payload Too Large",
    414: "URI Too Long",
    431: "Request Header Fields Too Large",
    500: "Internal Server Error",
    503: "Service Unavailable",
}

#: Reason phrase for a status code with no _REASONS entry.
_UNKNOWN_REASON = "Unknown"


def _force_non_blocking(socket):
    # Best-effort, matching the documented transport contract: a BYO
    # transport without setblocking is tolerated.
    setblocking = getattr(socket, "setblocking", None)
    if setblocking is not None:
        setblocking(False)


def _split_pattern_path(path):
    last_slash = path.rfind("/")
    if last_slash == -1:
        return "", ""
    return path[:last_slash + 1], path[last_slash + 1:]


class Request:
    """``Request`` holds one parsed HTTP request, as a route handler receives it.

    Attributes:
        method: HTTP method, such as ``"GET"``.
        target: Raw request target, such as ``"/api/widgets?page=2"``.
        path: Path part of the target, such as ``"/api/widgets"``.
        query: ``CaseInsensitiveDict`` of the query parameters, so
            ``query["page"]`` reads ``"2"``.  Percent-escapes stay as
            received.
        http_version: Version from the request line, such as ``"HTTP/1.1"``.
        headers: ``CaseInsensitiveDict`` of the request headers.
        body: Request body as ``bytes``, empty when the request has none.
        peer: ``(host, port)`` of the client.
        path_params: ``dict`` holding the segment a ``<name>`` route matched,
            so ``"/items/<item_id>"`` gives ``{"item_id": "7"}`` for
            ``/items/7``.
    """

    def __init__(
        self,
        *,
        method: str,
        target: str,
        http_version: str,
        headers: object,
        body: bytes,
        peer: tuple,
    ) -> None:
        self.method = method
        self.target = target
        self.http_version = http_version
        self.headers = headers
        self.body = body
        self.peer = peer
        self.path, raw_query = split_target(target)
        self.query = parse_query(raw_query)
        self.path_params = {}

    def text(self) -> str:
        """Return ``body`` decoded with the ``charset`` of the ``Content-Type`` header.

        A request whose header names no charset decodes as UTF-8.
        """
        return self.body.decode(parse_charset(self.headers.get("Content-Type")))

    def json(self) -> object:
        """Parse ``body`` as JSON and return the resulting object.

        Raises:
            ValueError: The body is not valid JSON.
        """
        return json.loads(self.text())

    def __repr__(self) -> str:
        return f"Request({self.method!r} {self.target!r} from {self.peer!r})"


class Response:
    """``Response`` holds the status, headers, and body a route handler returns.

    ``build_response`` creates one with the reason phrase and
    ``Content-Type`` filled in.

    Attributes:
        status_code: HTTP status as an ``int``, such as ``200``.
        reason: Reason phrase, such as ``"OK"``.  ``build_response`` uses
            ``"Unknown"`` for a status it has no phrase for.
        headers: ``CaseInsensitiveDict`` of headers to send.  The server adds
            ``Content-Length`` and ``Connection: close``.
        body: Body as ``bytes``, possibly empty.
    """

    def __init__(
        self,
        *,
        status_code: int,
        reason: str,
        headers: object,
        body: bytes,
    ) -> None:
        self.status_code = status_code
        self.reason = reason
        self.headers = headers
        self.body = body

    def __repr__(self) -> str:
        return (
            f"Response(status_code={self.status_code}, "
            f"reason={self.reason!r}, body={len(self.body)} bytes)"
        )


class _ConnState:
    WANT_REQUEST_LINE = "want_request_line"
    WANT_HEADERS = "want_headers"
    WANT_BODY = "want_body"
    DISPATCHING = "dispatching"
    WANT_SEND_HEADERS = "want_send_headers"
    WANT_SEND_BODY = "want_send_body"
    DONE = "done"
    ERROR = "error"


_DONE_STATES = (_ConnState.DONE, _ConnState.ERROR)

_RECV_STATES = (
    _ConnState.WANT_REQUEST_LINE,
    _ConnState.WANT_HEADERS,
    _ConnState.WANT_BODY,
)


class _Connection:
    def __init__(
        self,
        socket,
        peer,
        *,
        handler,
        deadline_ticks,
        recv_budget,
        send_budget,
        max_request_body_bytes,
        max_request_line_bytes,
        max_headers_bytes,
        stream_buffer_size,
    ):
        self._socket = socket
        self._peer = peer
        self._handler = handler
        self._deadline_ticks = deadline_ticks
        self._recv_budget = recv_budget
        self._send_budget = send_budget
        self._stream_buffer_size = stream_buffer_size
        # No reused body buffer: connections are use-once, so a per-request alloc fragments less.
        self._parser = RequestParser(
            max_body_bytes=max_request_body_bytes,
            max_request_line_bytes=max_request_line_bytes,
            max_headers_bytes=max_headers_bytes,
        )
        # Reused recv scratch, capped at 512 B to bound per-connection heap.
        recv_scratch_size = recv_budget if recv_budget <= 512 else 512
        self._recv_buffer = bytearray(recv_scratch_size)
        self._recv_view = memoryview(self._recv_buffer)
        self._response_bytes = b""
        self._response_view = memoryview(self._response_bytes)
        self._response_offset = 0
        # Streaming send state, minted only when a handler streams.
        self._stream = None
        self._stream_buffer = None
        self.state = _ConnState.WANT_REQUEST_LINE

    @property
    def is_done(self):
        return self.state in _DONE_STATES

    def tick(self, now_ms, *, ticks_diff_func):
        if self.is_done:  # pragma: no cover - HttpServer removes done conns immediately
            return
        if ticks_diff_func(self._deadline_ticks, now_ms) <= 0:
            self._fail()
            return
        try:
            if self.state in _RECV_STATES:
                self._drive_recv()
            if self.state == _ConnState.DISPATCHING:
                self._dispatch_handler()
            if self.state == _ConnState.WANT_SEND_HEADERS:
                self._drive_send()
            if self.state == _ConnState.WANT_SEND_BODY:
                self._drive_stream_body()
        except ServerLimitError as limit_error:
            # Surface the cap's status (413 / 414 / 431) instead of a silent TCP close.
            self._stage_response(
                _build_error_response(limit_error.status_code, str(limit_error)),
            )
        except (OSError, ServerError):
            # Wire died mid-exchange; a late 400 is useless, so just drop the connection.
            self._fail()

    def close(self):
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:  # pragma: no cover - defensive
                pass
            self._socket = None

    def _drive_recv(self):
        consumed = 0
        budget = self._recv_budget
        scratch_size = len(self._recv_buffer)
        while consumed < budget and self._parser.state not in _PARSER_TERMINAL_STATES:
            capacity = min(scratch_size, budget - consumed)
            try:
                got = self._socket.recv_into(self._recv_view, capacity)
            except OSError as socket_error:
                if socket_error.errno == errno.EAGAIN:
                    return
                raise
            if got == 0:
                self._parser.feed_eof()
                break
            # feed() copies what it keeps, so reusing the recv view next tick is safe.
            self._parser.feed(self._recv_view[:got])
            consumed += got
        parser_state = self._parser.state
        if parser_state == RequestParseState.ERROR:
            raise self._parser.error
        if parser_state == RequestParseState.DONE:
            self.state = _ConnState.DISPATCHING
            return
        if parser_state == RequestParseState.HEADERS:
            self.state = _ConnState.WANT_HEADERS
        elif parser_state == RequestParseState.BODY:
            self.state = _ConnState.WANT_BODY

    def _dispatch_handler(self):
        request = Request(
            method=self._parser.method,
            target=self._parser.target,
            http_version=self._parser.http_version,
            headers=self._parser.headers,
            body=self._parser.body,
            peer=self._peer,
        )
        # The request now owns its copy of the body; drop the parser so the
        # connection stops pinning a second full copy through the send phase.
        self._parser = None
        try:
            response = self._handler(request)
        except Exception as handler_error:  # noqa: BLE001 - anything in the handler is a 500
            response = _build_error_response(500, str(handler_error))
        if isinstance(response, Response):
            self._stage_response(response)
            return
        if getattr(response, "source", None) is not None:
            # Duck-type on ``source`` so a non-streaming server never imports the framing code.
            self._stage_streaming_response(response)
            return
        response = _build_error_response(
            500,
            f"handler returned {type(response).__name__}, expected Response",
        )
        self._stage_response(response)

    def _stage_response(self, response):
        try:
            self._response_bytes = encode_response(response)
        except Exception:  # noqa: BLE001 - an unencodable Response is a 500, not a crash
            # Fall back to the canned 500; an unencodable Response would otherwise re-fail forever.
            self._response_bytes = _ENCODED_500_ERROR
        self._response_view = memoryview(self._response_bytes)
        self._response_offset = 0
        self.state = _ConnState.WANT_SEND_HEADERS

    def _stage_streaming_response(self, response):
        # Lazy stub; the framing code loads only when a handler streams.
        from chumicro_http_server.streaming import (  # noqa: PLC0415
            stage_streaming_response,
        )
        stage_streaming_response(self, response)

    def _drive_send(self):
        total = len(self._response_bytes)
        view = self._response_view
        consumed = 0
        budget = self._send_budget
        while self._response_offset < total and consumed < budget:
            end = self._response_offset + min(total - self._response_offset, budget - consumed)
            chunk = view[self._response_offset:end]
            try:
                sent = self._socket.send(chunk)
            except OSError as socket_error:
                if socket_error.errno == errno.EAGAIN:
                    return
                raise
            if sent <= 0:  # pragma: no cover - non-blocking-EAGAIN backpressure path
                return
            self._response_offset += sent
            consumed += sent
        if self._response_offset >= total:
            # Streaming hands off to the body drain; a buffered response is done.
            if self._stream is not None:
                self.state = _ConnState.WANT_SEND_BODY
            else:
                self.state = _ConnState.DONE

    def _drive_stream_body(self):
        # Lazy stub; the drain loop loads only when streaming.
        from chumicro_http_server.streaming import (  # noqa: PLC0415
            drive_stream_body,
        )
        drive_stream_body(self)

    def _fail(self):
        self.state = _ConnState.ERROR


def _reject_control_chars(label: str, value: str) -> None:
    # Guards against response splitting via CR/LF/NUL in reflected request data.
    if "\r" in value or "\n" in value or "\x00" in value:
        raise ServerProtocolError(f"{label} contains a control character")


def _encode_head(status_code, reason, framing_headers, extra_headers):
    # Shared status-line + header-block builder for plain and streaming
    # responses; the caller supplies the framing header (Content-Length or
    # Transfer-Encoding) and appends any body.
    _reject_control_chars("reason", str(reason))
    framing_headers["Connection"] = "close"
    _merge_headers(framing_headers, extra_headers)
    parts = [
        f"HTTP/1.1 {status_code} {reason}\r\n".encode("ascii"),
    ]
    for name, value in framing_headers.items():
        _reject_control_chars("header name", str(name))
        _reject_control_chars("header value", str(value))
        parts.append(f"{name}: {value}\r\n".encode("ascii"))
    parts.append(CRLF)
    return parts


def encode_response(response: Response) -> bytes:
    """Return the bytes ``HttpServer`` sends for ``response``.

    The bytes hold the status line, the headers with ``Content-Length`` and
    ``Connection: close`` added, a blank line, and the body.

    Raises:
        ServerProtocolError: The reason phrase or a header name or value holds
            CR, LF, or NUL.
    """
    headers = CaseInsensitiveDict()
    headers["Content-Length"] = str(len(response.body))
    parts = _encode_head(response.status_code, response.reason, headers, response.headers)
    parts.append(response.body)
    return b"".join(parts)


def _build_error_response(status_code: int, message: str) -> Response:
    body = message.encode("utf-8")
    headers = CaseInsensitiveDict()
    headers["Content-Type"] = "text/plain; charset=utf-8"
    return Response(
        status_code=status_code,
        reason=_REASONS.get(status_code, _UNKNOWN_REASON),
        headers=headers,
        body=body,
    )


def _build_method_not_allowed_response(allowed_methods) -> Response:
    # RFC 7231 §6.5.5 requires the Allow header on a 405.
    body = b"method not allowed"
    headers = CaseInsensitiveDict()
    headers["Content-Type"] = "text/plain; charset=utf-8"
    headers["Allow"] = ", ".join(allowed_methods)
    return Response(
        status_code=405,
        reason=_REASONS[405],
        headers=headers,
        body=body,
    )


class HttpServer:
    """``HttpServer`` accepts HTTP connections and answers each request with the handler
    registered for its path.

    ``@server.route(path)`` registers a handler.  The main loop then calls
    ``check(now_ms)`` and ``handle(now_ms)``, or a ``Runner`` does after
    ``runner.add(server)``.  Each ``handle`` call accepts at most one new
    client and moves every open connection one step: it reads up to
    ``recv_budget_per_tick`` bytes, runs the handler once the request is
    complete, and sends up to ``send_budget_per_tick`` bytes.  The server
    answers one request per connection and then closes it.

    A route handler runs inside ``handle`` and holds the main loop until it
    returns.  An exception in a handler becomes a 500 response.  With TLS on
    MicroPython and CPython, accepting a client holds the loop for the TLS
    handshake.

    Attributes:
        io_socket: The listening socket, or ``None`` before the first
            ``handle`` call.
        accept_errors: Count of failed accepts, such as TLS handshakes a
            client broke off.  The server keeps listening after each.
    """

    @classmethod
    def from_config(
        cls,
        config: object,
        *,
        handler: object | None = None,
        radio: object | None = None,
        ssl_context: object | None = None,
        transport_factory: object | None = None,
        **constructor_kwargs: object,
    ) -> "HttpServer":
        """Build an ``HttpServer`` from deployed settings, listening through ``chumicro_sockets``.

        It reads ``http_server.bind_host``, default ``"0.0.0.0"``, and
        ``http_server.bind_port``, default 8080.  Setting both
        ``http_server.tls.cert_path`` and ``http_server.tls.key_path`` serves
        HTTPS with those files.  ``http_server.max_connections``,
        ``http_server.request_timeout_ms``,
        ``http_server.max_request_body_bytes``,
        ``http_server.max_request_line_bytes``,
        ``http_server.max_headers_bytes``, and
        ``http_server.stream_buffer_size`` set the constructor arguments of
        the same name.  Each keyword in ``constructor_kwargs`` passes straight
        to the constructor and wins over a value read here.

        Args:
            config: Flat settings dict or ``chumicro_config.RuntimeConfig``.
            handler: Fallback handler for paths no route matches, or ``None``
                to answer 404.
            radio: The CircuitPython radio, ``wifi.radio``.  MicroPython and
                CPython ignore it.
            ssl_context: Server-side ``ssl.SSLContext`` for HTTPS, used in
                place of the certificate files.
            transport_factory: Function that opens the listening socket, used
                in place of the ``chumicro_sockets`` listener.  The address,
                TLS, ``radio``, and ``ssl_context`` settings then go unused.
            **constructor_kwargs: Other constructor keywords, such as ``ticks=``.

        Returns:
            The new ``HttpServer``.

        Raises:
            chumicro_config.MissingConfigKey: Only one of
                ``http_server.tls.cert_path`` and ``http_server.tls.key_path``
                is set.
            RuntimeError: ``transport_factory`` is ``None`` and
                ``chumicro_sockets.sockets_factory`` is missing from the board.
        """
        if transport_factory is None:
            host = config.get("http_server.bind_host", "0.0.0.0")
            port = config.get("http_server.bind_port", 8080)
            cert_path = config.get("http_server.tls.cert_path")
            key_path = config.get("http_server.tls.key_path")
            if (cert_path is None) != (key_path is None):
                from chumicro_config import MissingConfigKey  # noqa: PLC0415 - lazy

                missing = (
                    "http_server.tls.cert_path" if cert_path is None
                    else "http_server.tls.key_path"
                )
                raise MissingConfigKey(
                    f"required config key {missing!r} is missing; TLS "
                    "requires both cert_path and key_path",
                )
            # Lazy import so a caller-supplied transport_factory doesn't pull in chumicro_sockets.
            try:
                from chumicro_sockets.sockets_factory import (  # noqa: PLC0415 - lazy
                    listener_factory,
                )
            except ImportError as exception:
                raise RuntimeError(
                    "chumicro_sockets.sockets_factory not "
                    "available (excluded via __chumicro_skip_factories__ "
                    "or not on the board); pass transport_factory= "
                    "explicitly.",
                ) from exception

            transport_factory = listener_factory(
                host, port,
                radio=radio, ssl_context=ssl_context,
                cert_path=cert_path, key_path=key_path,
            )
        kwargs = {
            "transport_factory": transport_factory,
            "handler": handler,
            "max_connections": config.get(
                "http_server.max_connections", DEFAULT_MAX_CONNECTIONS,
            ),
            "request_timeout_ms": config.get(
                "http_server.request_timeout_ms",
                DEFAULT_REQUEST_TIMEOUT_MS,
            ),
            "max_request_body_bytes": config.get(
                "http_server.max_request_body_bytes",
                DEFAULT_MAX_REQUEST_BODY_BYTES,
            ),
            "max_request_line_bytes": config.get(
                "http_server.max_request_line_bytes",
                DEFAULT_MAX_REQUEST_LINE_BYTES,
            ),
            "max_headers_bytes": config.get(
                "http_server.max_headers_bytes",
                DEFAULT_MAX_HEADERS_BYTES,
            ),
            "stream_buffer_size": config.get(
                "http_server.stream_buffer_size",
                DEFAULT_STREAM_BUFFER_SIZE,
            ),
        }
        kwargs.update(constructor_kwargs)
        return cls(**kwargs)

    def __init__(
        self,
        *,
        transport_factory: object,
        handler: object | None = None,
        max_connections: int = DEFAULT_MAX_CONNECTIONS,
        request_timeout_ms: int = DEFAULT_REQUEST_TIMEOUT_MS,
        recv_budget_per_tick: int = DEFAULT_RECV_BUDGET_PER_TICK,
        send_budget_per_tick: int = DEFAULT_SEND_BUDGET_PER_TICK,
        max_request_body_bytes: int = DEFAULT_MAX_REQUEST_BODY_BYTES,
        max_request_line_bytes: int = DEFAULT_MAX_REQUEST_LINE_BYTES,
        max_headers_bytes: int = DEFAULT_MAX_HEADERS_BYTES,
        stream_buffer_size: int = DEFAULT_STREAM_BUFFER_SIZE,
        ticks: object | None = None,
    ) -> None:
        """Create a server.  The listening socket opens on the first ``handle`` call.

        Args:
            transport_factory: Function with no arguments that opens the
                listening socket, such as
                ``lambda: chumicro_sockets.listener("0.0.0.0", 8080, radio=wifi.radio)``.
            handler: Function ``handler(request)`` returning a ``Response``
                for a path no route matches, or ``None`` to answer 404.
            max_connections: Most connections open at once.  Further clients
                wait in the listener's queue.  Default 4.
            request_timeout_ms: Time a connection gets from accept to its last
                byte sent, in ms.  A connection past it closes with no
                response.  Default 10000.
            recv_budget_per_tick: Most bytes one ``handle`` call reads from
                each connection.  Default 1024.
            send_budget_per_tick: Most bytes one ``handle`` call sends on each
                connection.  Default 4096.
            max_request_body_bytes: Largest request body, in bytes.  A larger
                ``Content-Length`` gets 413.  Default 16384.
            max_request_line_bytes: Longest request line, in bytes.  A longer
                one gets 414.  Default 1024.
            max_headers_bytes: Largest header section, in bytes.  A larger one
                gets 431.  Default 4096.
            stream_buffer_size: Size in bytes of the buffer a
                ``StreamingResponse`` body passes through.  A connection
                allocates it when it first streams.  Default 1024.
            ticks: Clock with ``ticks_ms``, ``ticks_diff``, and ``ticks_add``,
                or ``None`` for ``chumicro_timing.ticks``.
        """
        self._transport_factory = transport_factory
        self._fallback_handler = handler
        self._max_connections = max_connections
        self._request_timeout_ms = request_timeout_ms
        self._recv_budget_per_tick = recv_budget_per_tick
        self._send_budget_per_tick = send_budget_per_tick
        self._max_request_body_bytes = max_request_body_bytes
        self._max_request_line_bytes = max_request_line_bytes
        self._max_headers_bytes = max_headers_bytes
        self._stream_buffer_size = stream_buffer_size

        if ticks is None:
            from chumicro_timing import ticks  # noqa: PLC0415 - DI fallback
        self._ticks = ticks

        self.io_socket = None
        self._connections = []
        #: Count of accept-time errors swallowed as connection-scoped (e.g. TLS handshake failures).
        self.accept_errors = 0

        # _explicit_routes: (method, path) -> handler; _pattern_routes: (method, prefix, param_name, handler).
        self._explicit_routes = {}
        self._pattern_routes = []

    def route(
        self,
        path: str,
        *,
        methods: object = ("GET",),
    ) -> object:
        """Return a decorator that registers the decorated function as the handler for ``path``.

        Write ``@server.route("/status")`` above ``def status(request):``.
        The handler takes a ``Request`` and returns a ``Response`` or a
        ``StreamingResponse``.  A last segment written ``<name>`` matches any
        one segment and stores it in ``request.path_params[name]``, so
        ``"/items/<item_id>"`` matches ``/items/7``.  A request for a
        registered path with an unregistered method gets 405.  Registering a
        method and path again replaces the handler.

        Args:
            path: Path to match exactly, such as ``"/status"``, optionally
                ending in one ``<name>`` segment.
            methods: HTTP methods to register, such as ``("GET", "POST")``,
                in any letter case.

        Returns:
            The decorator.  It returns the handler unchanged.
        """
        def decorator(handler_func):
            for method in methods:
                self._register(method.upper(), path, handler_func)
            return handler_func
        return decorator

    def _register(self, method: str, path: str, handler_func: object) -> None:
        prefix, last_segment = _split_pattern_path(path)
        if (
            len(last_segment) >= 2
            and last_segment[0] == "<"
            and last_segment[-1] == ">"
        ):
            param_name = last_segment[1:-1]
            # Last-wins: replace any prior pattern entry with the same prefix and method.
            for existing_index, existing in enumerate(self._pattern_routes):
                existing_method, existing_prefix, _, _ = existing
                if existing_method == method and existing_prefix == prefix:
                    self._pattern_routes[existing_index] = (
                        method, prefix, param_name, handler_func,
                    )
                    return
            self._pattern_routes.append(
                (method, prefix, param_name, handler_func),
            )
            return
        self._explicit_routes[(method, path)] = handler_func

    def _dispatch_request(self, request: "Request") -> "Response":
        method = request.method
        path = request.path

        explicit_handler = self._explicit_routes.get((method, path))
        if explicit_handler is not None:
            return explicit_handler(request)

        prefix, param_value = _split_pattern_path(path)
        if param_value:
            for entry_method, entry_prefix, param_name, handler_func in (
                self._pattern_routes
            ):
                if entry_method == method and entry_prefix == prefix:
                    request.path_params[param_name] = param_value
                    return handler_func(request)

        allowed = self._allowed_methods_for(path)
        if allowed:
            return _build_method_not_allowed_response(sorted(allowed))

        if self._fallback_handler is not None:
            return self._fallback_handler(request)

        return _build_error_response(404, "not found")

    def _allowed_methods_for(self, path: str) -> set:
        allowed = set()
        for entry_method, entry_path in self._explicit_routes:
            if entry_path == path:
                allowed.add(entry_method)
        prefix, param_value = _split_pattern_path(path)
        if param_value:
            for entry_method, entry_prefix, _, _ in self._pattern_routes:
                if entry_prefix == prefix:
                    allowed.add(entry_method)
        return allowed

    @property
    def listening(self) -> bool:
        """``True`` while the listening socket is open.  It opens on the first ``handle`` call."""
        return self.io_socket is not None

    @property
    def in_flight(self) -> int:
        """Number of connections open right now."""
        return len(self._connections)

    def close(self):
        """Close the listening socket and every open connection.

        A later ``handle`` call opens a new listening socket.
        """
        for connection in self._connections:
            connection.close()
        self._connections = []
        if self.io_socket is not None:
            try:
                self.io_socket.close()
            except OSError:  # pragma: no cover - defensive
                pass
            self.io_socket = None

    def check(self, now_ms):  # noqa: ARG002 - runner contract
        """Return ``True`` on every call, because a client can connect at any moment."""
        return True

    def io_interest(self, now_ms):  # noqa: ARG002 (runner contract)
        """Return the poll bits ``Runner.wait`` watches on ``io_socket``.

        The result is the read bit while the listening socket is open and a
        connection slot is free, and 0 otherwise.
        """
        if self.io_socket is None:
            return 0
        return _IO_READ if len(self._connections) < self._max_connections else 0

    def next_deadline(self, now_ms):
        """Return the tick by which ``handle`` must run next, or ``None`` with no open connection.

        With connections open it is the earlier of the nearest connection
        timeout and ``now_ms`` plus 20 ms, so open connections keep moving.
        """
        if not self._connections:
            return None
        ticks_diff = self._ticks.ticks_diff
        nearest = None
        for connection in self._connections:
            candidate = connection._deadline_ticks
            if nearest is None or ticks_diff(candidate, nearest) < 0:
                nearest = candidate
        progress = self._ticks.ticks_add(now_ms, _CONNECTION_PROGRESS_INTERVAL_MS)
        if nearest is None or ticks_diff(progress, nearest) < 0:
            return progress
        return nearest

    def handle(self, now_ms):
        """Accept at most one waiting client and move every open connection one step.

        ``now_ms`` is the current time from ``ticks_ms()``.  The first call
        opens the listening socket through ``transport_factory``.  Route
        handlers run inside this call.  Finished and timed-out connections
        close here.
        """
        if self.io_socket is None:
            self.io_socket = self._transport_factory()
            _force_non_blocking(self.io_socket)
        if len(self._connections) < self._max_connections:
            self._try_accept(now_ms)
        # Reverse index walk: done connections pop in place, with no per-tick
        # list copy and no equality re-scan.
        connections = self._connections
        ticks_diff_func = self._ticks.ticks_diff
        for connection_index in range(len(connections) - 1, -1, -1):
            connection = connections[connection_index]
            connection.tick(now_ms, ticks_diff_func=ticks_diff_func)
            if connection.is_done:
                connection.close()
                connections.pop(connection_index)

    def _try_accept(self, now_ms):
        try:
            accept_result = self.io_socket.accept()
        except OSError as accept_error:
            if accept_error.errno == errno.EAGAIN:
                return
            # A TLS listener handshakes inside accept(), so a bad client raises here; keep listening.
            self.accept_errors += 1
            return
        if accept_result is None:
            return
        client_socket, peer = accept_result
        _force_non_blocking(client_socket)
        deadline = self._ticks.ticks_add(now_ms, self._request_timeout_ms)
        connection = _Connection(
            client_socket,
            peer,
            handler=self._dispatch_request,
            deadline_ticks=deadline,
            recv_budget=self._recv_budget_per_tick,
            send_budget=self._send_budget_per_tick,
            max_request_body_bytes=self._max_request_body_bytes,
            max_request_line_bytes=self._max_request_line_bytes,
            max_headers_bytes=self._max_headers_bytes,
            stream_buffer_size=self._stream_buffer_size,
        )
        self._connections.append(connection)


def build_response(
    status: int = 200,
    *,
    body: bytes | str | None = None,
    json=None,  # noqa: A002 - json is the conventional kwarg name
    text: str | None = None,
    html: str | None = None,
    headers: object | None = None,
) -> Response:
    """Build a ``Response`` with the reason phrase and ``Content-Type`` filled in.

    ``json`` takes an object and sends it as ``application/json``.  ``text``
    sends ``text/plain; charset=utf-8``, and ``html`` sends
    ``text/html; charset=utf-8``.  ``body`` sends bytes as given, with no
    ``Content-Type``.  An entry in ``headers`` replaces the default of the
    same name.

    Args:
        status: HTTP status code.
        body: Raw body as ``bytes``, ``bytearray``, or ``str``.
        text: String to send as plain text.
        html: String to send as HTML.
        headers: Extra headers as a dict, a ``CaseInsensitiveDict``, or
            ``(name, value)`` pairs.

    Returns:
        The new ``Response``.

    Raises:
        ValueError: More than one of ``body``, ``json``, ``text``, and
            ``html`` was given.
        TypeError: ``body`` is not ``bytes``, ``bytearray``, or ``str``.
    """
    body_count = sum(
        candidate is not None for candidate in (body, json, text, html)
    )
    if body_count > 1:
        raise ValueError(
            "pass at most one of body= / json= / text= / html=",
        )
    encoded_body, default_content_type = _encode_response_body(body, json, text, html)
    merged_headers = CaseInsensitiveDict()
    if default_content_type is not None:
        merged_headers["Content-Type"] = default_content_type
    _merge_headers(merged_headers, headers)
    reason = _REASONS.get(status, _UNKNOWN_REASON)
    return Response(
        status_code=status,
        reason=reason,
        headers=merged_headers,
        body=encoded_body,
    )


def _merge_headers(target, source):
    if source is None:
        return
    if isinstance(source, (dict, CaseInsensitiveDict)):
        source = source.items()
    for name, value in source:
        target[name] = value


def _encode_response_body(body, json_body, text, html):
    if json_body is not None:
        return json.dumps(json_body).encode("utf-8"), "application/json"
    if text is not None:
        return text.encode("utf-8"), "text/plain; charset=utf-8"
    if html is not None:
        return html.encode("utf-8"), "text/html; charset=utf-8"
    if body is None:
        return b"", None
    if isinstance(body, str):
        return body.encode("utf-8"), None
    if isinstance(body, (bytes, bytearray)):
        return bytes(body), None
    raise TypeError(
        f"body must be bytes / bytearray / str, got {type(body).__name__}",
    )
