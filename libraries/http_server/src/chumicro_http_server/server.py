"""HTTP/1.1 server built on chumicro-sockets + chumicro-timing.

:class:`HttpServer` is the entry point.  Runner-shaped —
:meth:`check(now_ms) -> bool` reports whether work is pending;
:meth:`handle(now_ms)` performs one tick of progress.  No threads,
no async — cooperative dispatch in the caller's tick loop.

Per-connection state machine::

    WANT_REQUEST_LINE
      -> WANT_HEADERS
        -> DISPATCHING        (handler runs synchronously here)
          -> WANT_SEND_HEADERS
            -> WANT_SEND_BODY
              -> DONE / CLOSING
                           \\-> ERROR (any state)

The handler is called once, after the full request (headers + any
``Content-Length`` body) has been parsed.  Bounded multi-connection
(``max_connections``), per-tick recv / send byte budgets, and a
``@server.route`` decorator with method dispatch + single trailing
path parameter are all wired up.
"""

import json

from chumicro_http_server._wire import (
    CRLF,
    DEFAULT_MAX_CONNECTIONS,
    DEFAULT_MAX_REQUEST_BODY_BYTES,
    DEFAULT_RECV_BUDGET_PER_TICK,
    DEFAULT_REQUEST_TIMEOUT_MS,
    DEFAULT_SEND_BUDGET_PER_TICK,
    CaseInsensitiveDict,
    RequestParser,
    RequestParseState,
    ServerError,
    ServerOversizedError,
    parse_query,
    split_target,
)


def _is_eagain(error):
    return getattr(error, "errno", None) in (11, 35)


#: Reason phrases for the status codes this server emits.
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
    500: "Internal Server Error",
    503: "Service Unavailable",
}


def _force_non_blocking(socket):
    """Best-effort ``setblocking(False)`` on a socket.

    Same shape as the equivalent helper in chumicro-requests and
    chumicro-mqtt — every accepted connection is flipped to non-
    blocking up front so the per-connection state machine never
    stalls on a read or write.
    """
    setblocking = getattr(socket, "setblocking", None)
    if setblocking is None:  # pragma: no cover - defensive (every supported sock has it)
        return
    try:
        setblocking(False)
    except (OSError, AttributeError):  # pragma: no cover — defensive
        pass


# ---------------------------------------------------------------------------
# Request + Response value objects
# ---------------------------------------------------------------------------


class Request:
    """Immutable view of a parsed HTTP request as the handler sees it.

    Attributes:
        method: HTTP verb (e.g. ``"GET"``).
        target: Raw request-target — e.g. ``"/api/widgets?page=2"``.
        path: Just the path component of the target.
        query: :class:`CaseInsensitiveDict` of query-string parameters.
            Percent-encoding is not decoded — most embedded REST APIs
            avoid encoded params.
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
        # Pattern-route handlers populate this dict at bind time
        # (HttpServer._dispatch_request).  Non-route requests leave it empty.
        self.path_params = {}

    def text(self) -> str:
        """Return :attr:`body` decoded as ``str`` using utf-8."""
        return self.body.decode("utf-8")

    def json(self) -> object:
        """Parse :attr:`body` as JSON; raises ``ValueError`` on bad data."""
        return json.loads(self.text())

    def __repr__(self) -> str:
        return f"Request({self.method!r} {self.target!r} from {self.peer!r})"


class Response:
    """Outbound HTTP response built by :meth:`HttpServer.respond`.

    Attributes:
        status_code: Integer HTTP status (e.g. ``200``).
        reason: Reason phrase (sourced from a small table; falls back
            to ``"Unknown"`` for non-canonical codes).
        headers: :class:`CaseInsensitiveDict` to send with the response.
            ``Content-Length`` and ``Connection: close`` are added
            automatically by the writer.
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


# ---------------------------------------------------------------------------
# Per-connection state machine
# ---------------------------------------------------------------------------


class _ConnState:
    """Per-connection states."""

    WANT_REQUEST_LINE = "want_request_line"
    WANT_HEADERS = "want_headers"
    WANT_BODY = "want_body"
    DISPATCHING = "dispatching"
    WANT_SEND_HEADERS = "want_send_headers"
    WANT_SEND_BODY = "want_send_body"
    DONE = "done"
    ERROR = "error"


class _Connection:
    """One in-flight HTTP/1.1 connection.

    Owns the accepted socket, the streaming :class:`RequestParser`,
    the response bytes once the handler runs, and a deadline.  The
    server's :meth:`HttpServer.handle` advances every connection by
    one budgeted slice per tick.
    """

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
    ):
        self._socket = socket
        self._peer = peer
        self._handler = handler
        self._deadline_ticks = deadline_ticks
        self._recv_budget = recv_budget
        self._send_budget = send_budget
        # No per-connection steady-state body buffer: every response
        # emits ``Connection: close`` so each :class:`_Connection`
        # serves exactly one request before being destroyed.  A
        # pre-allocated buffer here would have a use-once lifetime —
        # the same shape as the standalone case where
        # ``chumicro_requests``'s on-device fragmentation tests
        # measured a default-sized body buffer as a regression.  The
        # parser starts empty and the sized-rebind path in
        # :meth:`RequestParser._enter_body_state` does one allocation
        # of ``bytearray(content_length)`` for the request.  When
        # keep-alive lands and ``_Connection`` lives across requests,
        # revisit and pass a long-lived buffer in here.
        self._parser = RequestParser(max_body_bytes=max_request_body_bytes)
        # Pre-allocated recv scratch reused by every :meth:`_drive_recv` call
        # — mirrors :class:`chumicro_mqtt._wire.PacketDecoder` and
        # ``chumicro_websockets._session.WebSocketSession``.  A 4-conn
        # server with the default 1024-byte budget pins ~2 KB of steady-
        # state heap (4 × min(1024, 512)) instead of churning a fresh
        # bytearray per tick per connection.  Capped at 512 so a server
        # configured with a large recv_budget doesn't pin big buffers
        # per connection.
        recv_scratch_size = recv_budget if recv_budget <= 512 else 512
        self._recv_buffer = bytearray(recv_scratch_size)
        self._recv_view = memoryview(self._recv_buffer)
        self._response_bytes = b""
        self._response_view = memoryview(self._response_bytes)
        self._response_offset = 0
        self.state = _ConnState.WANT_REQUEST_LINE

    @property
    def is_done(self):
        return self.state in (_ConnState.DONE, _ConnState.ERROR)

    def tick(self, now_ms, *, ticks_diff_func):
        """Advance the connection by one tick's worth of work."""
        if self.is_done:  # pragma: no cover - HttpServer removes done conns immediately
            return
        if ticks_diff_func(self._deadline_ticks, now_ms) <= 0:
            self._fail()
            return
        try:
            if self.state in (
                _ConnState.WANT_REQUEST_LINE,
                _ConnState.WANT_HEADERS,
                _ConnState.WANT_BODY,
            ):
                self._drive_recv()
            if self.state == _ConnState.DISPATCHING:
                self._dispatch_handler()
            if self.state in (
                _ConnState.WANT_SEND_HEADERS,
                _ConnState.WANT_SEND_BODY,
            ):
                self._drive_send()
        except ServerOversizedError as oversized_error:
            # 413 before any body bytes were allocated — surface the
            # response cleanly instead of letting the connection die
            # silently with a TCP close.
            self._emit_error_response(413, str(oversized_error))
        except (OSError, ServerError):
            # Either side of the wire died — drop the connection.  The
            # writer's response state is already past the point where a
            # best-effort 400 would be useful, so we just fail; HttpServer
            # closes the socket on the next tick.
            self._fail()

    def close(self):
        """Best-effort socket close."""
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:  # pragma: no cover — defensive
                pass
            self._socket = None

    # ------------------------------------------------------------------
    # Recv / parser
    # ------------------------------------------------------------------

    def _drive_recv(self):
        """Drain the socket up to ``recv_budget``; feed the parser.

        Recv goes into the pre-allocated :attr:`_recv_buffer`; the
        :meth:`RequestParser.feed` call gets a ``memoryview`` window so
        neither the recv nor the feed allocates per tick.  Parser copies
        what it keeps before returning, so the memoryview is single-use.
        """
        consumed = 0
        budget = self._recv_budget
        scratch_size = len(self._recv_buffer)
        while consumed < budget and self._parser.state not in (
            RequestParseState.DONE, RequestParseState.ERROR,
        ):
            capacity = min(scratch_size, budget - consumed)
            try:
                got = self._socket.recv_into(self._recv_view, capacity)
            except OSError as socket_error:
                if _is_eagain(socket_error):
                    return
                raise
            if got == 0:
                self._parser.feed_eof()
                break
            self._parser.feed(self._recv_view[:got])
            consumed += got
        # Map parser state back to connection state.
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

    # ------------------------------------------------------------------
    # Handler dispatch + response encoding
    # ------------------------------------------------------------------

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
        except Exception as handler_error:  # noqa: BLE001 — anything in the handler is a 500
            response = _build_error_response(500, str(handler_error))
        if not isinstance(response, Response):
            response = _build_error_response(
                500,
                f"handler returned {type(response).__name__}, expected Response",
            )
        self._response_bytes = encode_response(response)
        self._response_view = memoryview(self._response_bytes)
        self._response_offset = 0
        self.state = _ConnState.WANT_SEND_HEADERS

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
                if _is_eagain(socket_error):
                    return
                raise
            if sent <= 0:  # pragma: no cover - non-blocking-EAGAIN backpressure path
                return
            self._response_offset += sent
            consumed += sent
        if self._response_offset >= total:
            self.state = _ConnState.DONE

    def _fail(self):
        self.state = _ConnState.ERROR

    def _emit_error_response(self, status_code: int, message: str) -> None:
        """Stage a pre-built error response for the send half of the tick.

        Used for failure modes that have a sensible HTTP-level reply
        (e.g. 413 from :class:`ServerOversizedError`).  After this,
        ``handle()`` keeps ticking the connection through send + DONE.
        """
        response = _build_error_response(status_code, message)
        self._response_bytes = encode_response(response)
        self._response_view = memoryview(self._response_bytes)
        self._response_offset = 0
        self.state = _ConnState.WANT_SEND_HEADERS


# ---------------------------------------------------------------------------
# Response encoding
# ---------------------------------------------------------------------------


def encode_response(response: Response) -> bytes:
    """Serialize a :class:`Response` into wire bytes.

    Adds ``Content-Length`` (if the caller didn't) and ``Connection:
    close`` — keep-alive is not supported, so every response closes
    its connection — then emits the status line + headers + body in
    one bytes blob.
    """
    headers = CaseInsensitiveDict()
    headers["Content-Length"] = str(len(response.body))
    headers["Connection"] = "close"
    _merge_headers(headers, response.headers)
    parts = [
        f"HTTP/1.1 {response.status_code} {response.reason}\r\n".encode("ascii"),
    ]
    for name, value in headers.items():
        parts.append(f"{name}: {value}\r\n".encode("ascii"))
    parts.append(CRLF)
    parts.append(response.body)
    return b"".join(parts)


def _build_error_response(status_code: int, message: str) -> Response:
    """Build a minimal text/plain error response.

    Used for handler exceptions + handler-returned-non-Response + 404
    fallthrough — all surface through the same path.  Kept module-level
    so callers + tests can mint canonical errors without going through
    HttpServer.
    """
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
    """Build a 405 with the ``Allow`` header per RFC 7231 §6.5.5.

    The Allow header is mandatory on 405 — clients use it to decide
    which method to retry with.
    """
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


# ---------------------------------------------------------------------------
# HttpServer
# ---------------------------------------------------------------------------


class HttpServer:
    """Non-blocking HTTP/1.1 server.

    Construct with a *listener_factory*, then either:

    * Register handlers via the :meth:`route` decorator
      (``@server.route("/path", methods=["GET", "POST"])``), or
    * Pass a single bare *handler* callable for non-routed servers.

    Drive via :meth:`check` / :meth:`handle` from a runner tick or
    hand-rolled loop.  The listener is opened lazily on the first
    :meth:`handle` call so construction is side-effect-free and
    testable.

    For config-driven construction, see :meth:`from_config` —
    one-line factory that builds the listener from
    ``http_server.bind_host`` / ``port`` (and optional
    ``tls.cert_path`` / ``tls.key_path``) and reads server limits
    from ``runtime_config.msgpack``.
    """

    @classmethod
    def from_config(
        cls,
        config: object,
        *,
        handler: object | None = None,
        radio: object | None = None,
        ssl_context: object | None = None,
        listener_factory: object | None = None,
    ) -> "HttpServer":
        """Build an :class:`HttpServer` from runtime config.

        Reads optional ``http_server.*`` keys (``bind_host`` /
        ``bind_port`` / ``max_connections`` / ``request_timeout_ms`` /
        ``max_request_body_bytes`` / ``tls.cert_path`` /
        ``tls.key_path``) from *config*.  All defaults apply when
        absent; a custom *listener_factory* bypasses the auto-build
        entirely, *ssl_context* opts into TLS without config paths,
        and exactly one half of the TLS pair raises
        :class:`chumicro_config.MissingConfigKey`.
        """
        if listener_factory is None:
            # Lazy import so users who pass their own listener_factory
            # don't pull chumicro_sockets into the deploy graph.  See
            # ``chumicro_http_server.sockets_factory`` for the helper itself.
            try:
                from chumicro_http_server.sockets_factory import (  # noqa: PLC0415 - lazy
                    chumicro_sockets_factory,
                )
            except ImportError as exception:
                raise RuntimeError(
                    "chumicro_http_server.sockets_factory not "
                    "available (excluded via __chumicro_skip_factories__ "
                    "or not on the board) — pass listener_factory= "
                    "explicitly.",
                ) from exception

            listener_factory = chumicro_sockets_factory(
                config, radio=radio, ssl_context=ssl_context,
            )
        return cls(
            listener_factory=listener_factory,
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
        )

    def __init__(
        self,
        *,
        listener_factory: object,
        handler: object | None = None,
        max_connections: int = DEFAULT_MAX_CONNECTIONS,
        request_timeout_ms: int = DEFAULT_REQUEST_TIMEOUT_MS,
        recv_budget_per_tick: int = DEFAULT_RECV_BUDGET_PER_TICK,
        send_budget_per_tick: int = DEFAULT_SEND_BUDGET_PER_TICK,
        max_request_body_bytes: int = DEFAULT_MAX_REQUEST_BODY_BYTES,
        ticks: object | None = None,
    ) -> None:
        """Wire up the server.

        Args:
            listener_factory: Callable ``() -> ListeningSocket`` that
                opens a non-blocking listener (typically
                ``lambda: tcp_listening_socket(host, port,
                radio=wifi.radio)``).  Invoked once on the first
                :meth:`handle` call.
            handler: Optional fallback callable
                ``(Request) -> Response`` for paths that don't match
                any route registered via :meth:`route`.  If ``None``
                (the default), unrouted paths return 404.  Useful for
                single-handler servers without route registration and
                for catch-alls under a routed server.
            max_connections: Cap on simultaneous in-flight connections.
                Default 4 — sized for Pi Pico W heap.
            request_timeout_ms: Per-connection deadline.  A connection
                that hasn't reached ``DONE`` is dropped + the socket
                is closed.
            recv_budget_per_tick: Per-connection recv cap per
                :meth:`handle` call.  Bounds tick latency.
            send_budget_per_tick: Per-connection send cap per
                :meth:`handle` call.  Higher than recv because
                response bodies are typically small + we want them
                drained in one tick when possible.
            max_request_body_bytes: Cap on a single buffered request
                body.  Default 16 KB.  Bigger bodies are rejected
                with 400.
            ticks: Optional tick source — any object exposing
                ``ticks_ms``, ``ticks_diff``, ``ticks_add`` (matches
                the ``chumicro_timing.ticks`` submodule shape).
                Defaults to that submodule (real clock); tests pass
                ``FakeTicks`` from ``chumicro_timing.testing``.
        """
        self._listener_factory = listener_factory
        self._fallback_handler = handler
        self._max_connections = max_connections
        self._request_timeout_ms = request_timeout_ms
        self._recv_budget_per_tick = recv_budget_per_tick
        self._send_budget_per_tick = send_budget_per_tick
        self._max_request_body_bytes = max_request_body_bytes

        if ticks is None:
            from chumicro_timing import ticks  # noqa: PLC0415 - DI fallback
        self._ticks = ticks

        self._listener = None
        self._connections = []

        # Routing tables — two-dict router lifted from tinyweb's
        # pattern.
        # _explicit_routes: (method, path) -> handler.  No path
        # parameters.  O(1) lookup.
        # _pattern_routes: list of (method, prefix, param_name, handler)
        # for paths shaped ``"/users/<id>"`` — prefix matches up to
        # the last ``/``, the trailing segment becomes the parameter
        # value bound to ``request.path_params[param_name]``.
        self._explicit_routes = {}
        self._pattern_routes = []

    # ------------------------------------------------------------------
    # Public route registration
    # ------------------------------------------------------------------

    def route(
        self,
        path: str,
        *,
        methods: object = ("GET",),
    ) -> object:
        """Decorator that registers *handler* for *path* + *methods*.

        Path syntax:

        * ``"/api/widgets"`` — exact match.
        * ``"/users/<id>"`` — single trailing parameter.  The matched
          segment populates ``request.path_params["id"]``.

        Multi-parameter routes (``"/users/<uid>/posts/<pid>"``) are
        not supported — file an issue if you hit the limit.

        Args:
            path: Route path, optionally containing a single ``<name>``
                segment as the last path component.
            methods: Iterable of HTTP method strings (default
                ``("GET",)``).  Each method gets registered
                independently; methods that hit the path but aren't
                registered get ``405 Method Not Allowed``.

        Returns:
            The decorator that registers and returns the handler
            unchanged.
        """
        def decorator(handler_func):
            for method in methods:
                self._register(method.upper(), path, handler_func)
            return handler_func
        return decorator

    def _register(self, method: str, path: str, handler_func: object) -> None:
        """Insert *handler_func* into the routing table.

        Detects ``<name>``-style trailing parameters and routes to the
        pattern dict; everything else lands in the explicit dict.
        Re-registering the same (method, path) overrides — last-wins,
        same as Flask / FastAPI.
        """
        last_slash = path.rfind("/")
        last_segment = path[last_slash + 1:] if last_slash != -1 else path
        if (
            len(last_segment) >= 2
            and last_segment[0] == "<"
            and last_segment[-1] == ">"
        ):
            param_name = last_segment[1:-1]
            prefix = path[:last_slash + 1] if last_slash != -1 else ""
            # Replace any prior pattern entry with the same prefix +
            # method (last-wins).
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

    # ------------------------------------------------------------------
    # Internal — request dispatch
    # ------------------------------------------------------------------

    def _dispatch_request(self, request: "Request") -> "Response":
        """Look up *request* in the routing tables; return a Response.

        Order:
        1. Exact (method, path) hit → call handler.
        2. Pattern hit on (method, prefix) → bind path_param + call
           handler.
        3. Path matches an explicit / pattern route on a *different*
           method → 405 Method Not Allowed.
        4. Fallback handler (if construction-time *handler=* was set)
           → call it.
        5. 404 Not Found.
        """
        method = request.method
        path = request.path

        # 1. Exact match.
        explicit_handler = self._explicit_routes.get((method, path))
        if explicit_handler is not None:
            return explicit_handler(request)

        # 2. Pattern match.  prefix is the path up to + including the
        # last ``/``; the trailing segment is the parameter value.
        last_slash = path.rfind("/")
        if last_slash != -1:
            prefix = path[:last_slash + 1]
            param_value = path[last_slash + 1:]
            for entry_method, entry_prefix, param_name, handler_func in (
                self._pattern_routes
            ):
                if entry_method == method and entry_prefix == prefix and param_value:
                    request.path_params[param_name] = param_value
                    return handler_func(request)

        # 3. 405: path matches at least one route on a different method.
        allowed = self._allowed_methods_for(path)
        if allowed:
            return _build_method_not_allowed_response(sorted(allowed))

        # 4. Fallback handler.
        if self._fallback_handler is not None:
            return self._fallback_handler(request)

        # 5. 404.
        return _build_error_response(404, "not found")

    def _allowed_methods_for(self, path: str) -> set:
        """Return every method registered for *path*, across both tables."""
        allowed = set()
        for entry_method, entry_path in self._explicit_routes:
            if entry_path == path:
                allowed.add(entry_method)
        last_slash = path.rfind("/")
        if last_slash != -1:
            prefix = path[:last_slash + 1]
            param_value = path[last_slash + 1:]
            if param_value:
                for entry_method, entry_prefix, _, _ in self._pattern_routes:
                    if entry_prefix == prefix:
                        allowed.add(entry_method)
        return allowed

    # ------------------------------------------------------------------
    # Public observation
    # ------------------------------------------------------------------

    @property
    def listening(self) -> bool:
        """``True`` once the listener has been opened."""
        return self._listener is not None

    @property
    def in_flight(self) -> int:
        """Number of connections currently mid-pipeline."""
        return len(self._connections)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self):
        """Close the listener + every in-flight connection."""
        for connection in self._connections:
            connection.close()
        self._connections = []
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:  # pragma: no cover — defensive
                pass
            self._listener = None

    # ------------------------------------------------------------------
    # Runner contract
    # ------------------------------------------------------------------

    def check(self, now_ms):  # noqa: ARG002 — runner contract
        """Always ``True``: the accept loop must run on every tick.

        Mirrors :class:`chumicro_websockets.WebSocketServer.check` —
        cheap to advance even with no in-flight connections, and the
        listener may have a pending accept at any moment.
        """
        return True

    def handle(self, now_ms):
        """One tick of progress: lazy-open listener, accept, advance conns."""
        if self._listener is None:
            self._listener = self._listener_factory()
            _force_non_blocking(self._listener)
        # Try to accept up to one new connection per tick.
        if len(self._connections) < self._max_connections:
            self._try_accept(now_ms)
        # Advance every in-flight connection.  Iterate over a copy so
        # connections can finish + be removed during the loop.
        for connection in list(self._connections):
            connection.tick(now_ms, ticks_diff_func=self._ticks.ticks_diff)
            if connection.is_done:
                connection.close()
                self._connections.remove(connection)

    def _try_accept(self, now_ms):
        """Best-effort accept of one pending connection."""
        try:
            accept_result = self._listener.accept()
        except OSError as accept_error:
            if _is_eagain(accept_error):
                return
            raise
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
        )
        self._connections.append(connection)

    # ------------------------------------------------------------------
    # Response builder
    # ------------------------------------------------------------------

    def respond(
        self,
        status: int = 200,
        *,
        body: bytes | str | None = None,
        json: object | None = None,
        text: str | None = None,
        html: str | None = None,
        headers: object | None = None,
    ) -> Response:
        """Build a :class:`Response` with sensible defaults.

        Pass at most one of *body* / *json* / *text* / *html*.  *text*
        defaults ``Content-Type: text/plain; charset=utf-8``; *html*
        defaults ``text/html; charset=utf-8``; *json* runs ``json.dumps``
        + sets ``application/json``.  Caller-supplied *headers* always
        override these defaults.
        """
        return build_response(
            status, body=body, json=json, text=text, html=html, headers=headers,
        )


# ---------------------------------------------------------------------------
# Module-level response builder (so handlers can build responses without
# needing a server reference — useful for tests and helper functions).
# ---------------------------------------------------------------------------


def build_response(
    status: int = 200,
    *,
    body: bytes | str | None = None,
    json=None,  # noqa: A002 — json is the conventional kwarg name
    text: str | None = None,
    html: str | None = None,
    headers: object | None = None,
) -> Response:
    """Build a :class:`Response` — same surface as :meth:`HttpServer.respond`.

    Exposed at module level so handlers + tests can build responses
    without a server reference.
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
    reason = _REASONS.get(status, "Unknown")
    return Response(
        status_code=status,
        reason=reason,
        headers=merged_headers,
        body=encoded_body,
    )


def _merge_headers(target, source):
    """Copy *source* header pairs into *target* :class:`CaseInsensitiveDict`.

    *source* may be ``None``, a ``dict``, a :class:`CaseInsensitiveDict`,
    or any iterable of ``(name, value)`` pairs.  Existing keys on
    *target* are overwritten.
    """
    if source is None:
        return
    if isinstance(source, (dict, CaseInsensitiveDict)):
        source = source.items()
    for name, value in source:
        target[name] = value


def _encode_response_body(body, json_body, text, html):
    """Convert one of body / json / text / html into ``(bytes, default_content_type)``."""
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
