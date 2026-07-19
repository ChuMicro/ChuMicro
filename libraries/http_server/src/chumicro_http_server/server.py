"""HTTP/1.1 server built on chumicro-sockets and chumicro-timing.

The entry point is :class:`HttpServer`.
"""

import errno
import json

from chumicro_http_server._wire import (
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


def _force_non_blocking(socket):
    socket.setblocking(False)


def _split_pattern_path(path):
    last_slash = path.rfind("/")
    if last_slash == -1:
        return "", ""
    return path[:last_slash + 1], path[last_slash + 1:]


class Request:
    """Immutable view of a parsed HTTP request as the handler sees it.

    Attributes:
        method: HTTP verb (e.g. ``"GET"``).
        target: Raw request-target, e.g. ``"/api/widgets?page=2"``.
        path: Just the path component of the target.
        query: :class:`CaseInsensitiveDict` of query params; percent-encoding is not decoded.
        http_version: e.g. ``"HTTP/1.1"``.
        headers: :class:`CaseInsensitiveDict` of request headers.
        body: Raw request body as ``bytes``.
        peer: ``(host, port)`` tuple of the connecting client.
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
        """Return :attr:`body` decoded with the request's Content-Type charset."""
        return self.body.decode(parse_charset(self.headers.get("Content-Type")))

    def json(self) -> object:
        """Parse :attr:`body` as JSON; raises ``ValueError`` on bad data."""
        return json.loads(self.text())

    def __repr__(self) -> str:
        return f"Request({self.method!r} {self.target!r} from {self.peer!r})"


class Response:
    """Outbound HTTP response built by :func:`build_response`.

    Attributes:
        status_code: Integer HTTP status (e.g. ``200``).
        reason: Reason phrase; falls back to ``"Unknown"`` for codes outside the table.
        headers: :class:`CaseInsensitiveDict` to send; the writer adds Content-Length and Connection: close.
        body: Bytes to send as the response body (may be ``b""``).
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

_PARSER_TERMINAL_STATES = (RequestParseState.DONE, RequestParseState.ERROR)


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


def encode_response(response: Response) -> bytes:
    """Serialize a :class:`Response` into wire bytes.

    Raises:
        ServerProtocolError: The reason phrase or a header name or value carries a CR, LF, or NUL.
    """
    _reject_control_chars("reason", str(response.reason))
    headers = CaseInsensitiveDict()
    headers["Content-Length"] = str(len(response.body))
    headers["Connection"] = "close"
    _merge_headers(headers, response.headers)
    parts = [
        f"HTTP/1.1 {response.status_code} {response.reason}\r\n".encode("ascii"),
    ]
    for name, value in headers.items():
        _reject_control_chars("header name", str(name))
        _reject_control_chars("header value", str(value))
        parts.append(f"{name}: {value}\r\n".encode("ascii"))
    parts.append(CRLF)
    parts.append(response.body)
    return b"".join(parts)


def _build_error_response(status_code: int, message: str) -> Response:
    body = message.encode("utf-8")
    headers = CaseInsensitiveDict()
    headers["Content-Type"] = "text/plain; charset=utf-8"
    return Response(
        status_code=status_code,
        reason=_REASONS.get(status_code, "Error"),
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
    """Non-blocking HTTP/1.1 server."""

    @classmethod
    def from_config(
        cls,
        config: object,
        *,
        handler: object | None = None,
        radio: object | None = None,
        ssl_context: object | None = None,
        transport_factory: object | None = None,
    ) -> "HttpServer":
        """Build an :class:`HttpServer` from runtime config.

        Raises:
            MissingConfigKey: Exactly one of the TLS ``cert_path`` / ``key_path`` pair is set.
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
        return cls(
            transport_factory=transport_factory,
            handler=handler,
            max_connections=config.get(
                "http_server.max_connections", DEFAULT_MAX_CONNECTIONS,
            ),
            request_timeout_ms=config.get(
                "http_server.request_timeout_ms",
                DEFAULT_REQUEST_TIMEOUT_MS,
            ),
            max_request_body_bytes=config.get(
                "http_server.max_request_body_bytes",
                DEFAULT_MAX_REQUEST_BODY_BYTES,
            ),
            max_request_line_bytes=config.get(
                "http_server.max_request_line_bytes",
                DEFAULT_MAX_REQUEST_LINE_BYTES,
            ),
            max_headers_bytes=config.get(
                "http_server.max_headers_bytes",
                DEFAULT_MAX_HEADERS_BYTES,
            ),
            stream_buffer_size=config.get(
                "http_server.stream_buffer_size",
                DEFAULT_STREAM_BUFFER_SIZE,
            ),
        )

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
        """Wire up the server.

        Args:
            transport_factory: Callable ``() -> ListeningSocket``; opens the listener on first handle().
            handler: Optional fallback ``(Request) -> Response`` for unmatched paths; ``None`` returns 404.
            max_connections: Cap on simultaneous in-flight connections.
            request_timeout_ms: Per-connection deadline; a stalled connection is dropped and closed.
            recv_budget_per_tick: Per-connection recv cap per :meth:`handle` call.
            send_budget_per_tick: Per-connection send cap per :meth:`handle` call.
            max_request_body_bytes: Buffered-body cap; bigger bodies are rejected with 413.
            max_request_line_bytes: Request-line cap; a longer line without a CRLF is rejected with 414.
            max_headers_bytes: Header-section cap; more is rejected with 431.
            stream_buffer_size: Staging-window bytes for a StreamingResponse; minted lazily and reused.
            ticks: Tick source (ticks_ms / ticks_diff / ticks_add); defaults to chumicro_timing.ticks.
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

        self._listener = None
        self._connections = []
        #: Count of accept-time errors swallowed as connection-scoped (e.g. TLS handshake failures).
        self.accept_errors = 0
        self.last_accept_error = None

        # _explicit_routes: (method, path) -> handler; _pattern_routes: (method, prefix, param_name, handler).
        self._explicit_routes = {}
        self._pattern_routes = []

    def route(
        self,
        path: str,
        *,
        methods: object = ("GET",),
    ) -> object:
        """Decorator that registers a handler for *path* and *methods*.

        Args:
            path: Route path, optionally ending in one ``<name>`` segment.
            methods: Methods to register (default ("GET",)); an unknown method on a matched path returns 405.

        Returns:
            The decorator, which registers and returns the handler unchanged.
        """
        def decorator(handler_func):
            for method in methods:
                self._register(method.upper(), path, handler_func)
            return handler_func
        return decorator

    def _register(self, method: str, path: str, handler_func: object) -> None:
        last_slash = path.rfind("/")
        last_segment = path[last_slash + 1:] if last_slash != -1 else path
        if (
            len(last_segment) >= 2
            and last_segment[0] == "<"
            and last_segment[-1] == ">"
        ):
            param_name = last_segment[1:-1]
            prefix = path[:last_slash + 1] if last_slash != -1 else ""
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
        """``True`` once the listener has been opened."""
        return self._listener is not None

    @property
    def in_flight(self) -> int:
        """Number of connections currently mid-pipeline."""
        return len(self._connections)

    def close(self):
        """Close the listener and every in-flight connection."""
        for connection in self._connections:
            connection.close()
        self._connections = []
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:  # pragma: no cover - defensive
                pass
            self._listener = None

    def check(self, now_ms):  # noqa: ARG002 - runner contract
        """Always ``True``: the accept loop must run on every tick."""
        return True

    @property
    def io_socket(self):
        """The listener socket once opened, else ``None``."""
        if self._listener is None:
            return None
        return self._listener

    def io_interest(self, now_ms):  # noqa: ARG002 (runner contract)
        """Poll-interest bitmask for ``Runner.wait``: read when the listener is open, else none."""
        return _IO_READ if self._listener is not None else 0

    def next_deadline(self, now_ms):
        """Earliest tick at which ``handle()`` must run."""
        ticks_diff = self._ticks.ticks_diff
        nearest = None
        for connection in self._connections:
            candidate = connection._deadline_ticks
            if nearest is None or ticks_diff(candidate, nearest) < 0:
                nearest = candidate
        if not self._connections:
            return nearest
        progress = self._ticks.ticks_add(now_ms, _CONNECTION_PROGRESS_INTERVAL_MS)
        if nearest is None or ticks_diff(progress, nearest) < 0:
            return progress
        return nearest

    def handle(self, now_ms):
        """One tick of progress: lazy-open listener, accept, advance conns."""
        if self._listener is None:
            self._listener = self._transport_factory()
            _force_non_blocking(self._listener)
        if len(self._connections) < self._max_connections:
            self._try_accept(now_ms)
        # Iterate a copy so a connection can be removed mid-loop.
        if self._connections:
            for connection in list(self._connections):
                connection.tick(now_ms, ticks_diff_func=self._ticks.ticks_diff)
                if connection.is_done:
                    connection.close()
                    self._connections.remove(connection)

    def _try_accept(self, now_ms):
        try:
            accept_result = self._listener.accept()
        except OSError as accept_error:
            if accept_error.errno == errno.EAGAIN:
                return
            # A TLS listener handshakes inside accept(), so a bad client raises here; keep listening.
            self.accept_errors += 1
            self.last_accept_error = accept_error
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
    """Build a :class:`Response` with sensible defaults."""
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
    reason = _REASONS.get(status, "Unknown")
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
