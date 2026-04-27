"""HTTP/1.1 server built on chumicro-sockets + chumicro-timing.

:class:`HttpServer` is the entry point.  Runner-shaped per Decision
0014 — :meth:`check(now_ms) -> bool` reports whether work is pending;
:meth:`handle(now_ms)` performs one tick of progress.  No threads,
no async — cooperative dispatch in the caller's tick loop.

Per-connection state machine (Decision 0041 §2)::

    WANT_REQUEST_LINE
      -> WANT_HEADERS
        -> DISPATCHING        (handler runs synchronously here)
          -> WANT_SEND_HEADERS
            -> WANT_SEND_BODY
              -> DONE / CLOSING
                           \\-> ERROR (any state)

The handler is called once, after headers parse + before the body is
buffered (slice 7b adds routing — slice 7a uses a single
caller-provided handler callable).  For requests with a body, the
handler can call ``request.body_bytes()`` to consume it (the runner
re-enters the connection until the body has arrived, then returns
to the handler's continuation — see slice 7c).

Slice 7a (this file): single connection at a time, single handler,
canned 200 response.  Routing + multi-connection + per-tick budgets
land in 7b / 7c.
"""

import json

from chumicro_timing import ticks_add, ticks_diff, ticks_ms

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
    parse_query,
    split_target,
)

#: Reason phrases for the status codes the slice-7a server emits.
#: Slice 7b's ``respond()`` helper ships a fuller table.
_REASONS = {
    200: "OK",
    201: "Created",
    204: "No Content",
    301: "Moved Permanently",
    302: "Found",
    400: "Bad Request",
    404: "Not Found",
    405: "Method Not Allowed",
    500: "Internal Server Error",
    503: "Service Unavailable",
}


def _no_callback(*_args, **_kwargs):  # pragma: no cover - default no-op stub
    """Default no-op callback so handlers can be stored unconditionally."""
    return None


def _force_non_blocking(socket):
    """Best-effort ``setblocking(False)`` on a socket.

    Mirrors :func:`chumicro_requests.client._force_non_blocking` and
    the equivalent in chumicro-mqtt — every accepted connection is
    flipped to non-blocking up front so the per-connection state
    machine never stalls on a read or write.
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
        query: :class:`CaseInsensitiveDict` of query-string parameters
            (slice 7a leaves percent-encoding raw — most embedded
            REST APIs avoid encoded params).
        http_version: e.g. ``"HTTP/1.1"``.
        headers: :class:`CaseInsensitiveDict` of request headers.
        body: Raw request body as ``bytes``.
        peer: ``(host, port)`` tuple of the connecting client.
    """

    __slots__ = (
        "body",
        "headers",
        "http_version",
        "method",
        "path",
        "peer",
        "query",
        "target",
    )

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

    __slots__ = ("body", "headers", "reason", "status_code")

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
    """Per-connection states (Decision 0041 §2)."""

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

    __slots__ = (
        "_deadline_ticks",
        "_handler",
        "_max_request_body_bytes",
        "_parser",
        "_peer",
        "_recv_budget",
        "_response_bytes",
        "_response_offset",
        "_send_budget",
        "_socket",
        "_state",
    )

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
        self._max_request_body_bytes = max_request_body_bytes
        self._parser = RequestParser(max_body_bytes=max_request_body_bytes)
        self._response_bytes = b""
        self._response_offset = 0
        self._state = _ConnState.WANT_REQUEST_LINE

    @property
    def state(self):
        return self._state

    @property
    def is_done(self):
        return self._state in (_ConnState.DONE, _ConnState.ERROR)

    def tick(self, now_ms, *, ticks_diff_func):
        """Advance the connection by one tick's worth of work."""
        if self.is_done:  # pragma: no cover - HttpServer removes done conns immediately
            return
        if ticks_diff_func(self._deadline_ticks, now_ms) <= 0:
            self._fail()
            return
        try:
            if self._state in (
                _ConnState.WANT_REQUEST_LINE,
                _ConnState.WANT_HEADERS,
                _ConnState.WANT_BODY,
            ):
                self._drive_recv()
            if self._state == _ConnState.DISPATCHING:
                self._dispatch_handler()
            if self._state in (
                _ConnState.WANT_SEND_HEADERS,
                _ConnState.WANT_SEND_BODY,
            ):
                self._drive_send()
        except (OSError, ServerError):
            # Either side of the wire died — drop the connection.
            # The slice 7b path will refine this with a 400 best-effort
            # write before close; for now we just close.
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
        consumed = 0
        budget = self._recv_budget
        scratch = bytearray(min(budget, 512))
        while consumed < budget and self._parser.state not in (
            RequestParseState.DONE, RequestParseState.ERROR,
        ):
            capacity = min(len(scratch), budget - consumed)
            try:
                got = self._socket.recv_into(scratch, capacity)
            except OSError as socket_error:
                errno = socket_error.args[0] if socket_error.args else None
                if errno in (11, 35):  # EAGAIN
                    return
                raise
            if got == 0:
                self._parser.feed_eof()
                break
            self._parser.feed(bytes(scratch[:got]))
            consumed += got
        # Map parser state back to connection state.
        parser_state = self._parser.state
        if parser_state == RequestParseState.ERROR:
            raise self._parser.error
        if parser_state == RequestParseState.DONE:
            self._state = _ConnState.DISPATCHING
            return
        if parser_state == RequestParseState.HEADERS:
            self._state = _ConnState.WANT_HEADERS
        elif parser_state == RequestParseState.BODY:
            self._state = _ConnState.WANT_BODY

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
        self._response_offset = 0
        self._state = _ConnState.WANT_SEND_HEADERS

    def _drive_send(self):
        consumed = 0
        budget = self._send_budget
        while self._response_offset < len(self._response_bytes) and consumed < budget:
            view = memoryview(self._response_bytes)[self._response_offset:]
            capacity = min(len(view), budget - consumed)
            chunk = view[:capacity]
            try:
                sent = self._socket.send(chunk)
            except OSError as socket_error:
                errno = socket_error.args[0] if socket_error.args else None
                if errno in (11, 35):  # EAGAIN
                    return
                raise
            if sent <= 0:  # pragma: no cover - non-blocking-EAGAIN backpressure path
                return
            self._response_offset += sent
            consumed += sent
        if self._response_offset >= len(self._response_bytes):
            self._state = _ConnState.DONE

    def _fail(self):
        self._state = _ConnState.ERROR


# ---------------------------------------------------------------------------
# Response encoding
# ---------------------------------------------------------------------------


def encode_response(response: Response) -> bytes:
    """Serialise a :class:`Response` into wire bytes.

    Adds ``Content-Length`` (if the caller didn't), defaults
    ``Connection: close`` (no keep-alive in v1, mirrors
    chumicro-requests' policy), and emits the status line + headers
    + body in one bytes blob.
    """
    headers = CaseInsensitiveDict()
    headers["Content-Length"] = str(len(response.body))
    headers["Connection"] = "close"
    if response.headers is not None:
        if isinstance(response.headers, (dict, CaseInsensitiveDict)):
            iterable = response.headers.items()
        else:
            iterable = response.headers
        for name, value in iterable:
            headers[name] = value
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

    Used for handler exceptions + handler-returned-non-Response — both
    surface through the same 500 path.  Kept module-level so callers
    + tests can mint canonical errors without going through HttpServer.
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


# ---------------------------------------------------------------------------
# HttpServer
# ---------------------------------------------------------------------------


class HttpServer:
    """Non-blocking HTTP/1.1 server.

    Construct with a *listener_factory* + a *handler*.  Drive via
    :meth:`check` / :meth:`handle` from a runner tick or hand-rolled
    loop.  The listener is opened lazily on the first :meth:`handle`
    call so construction is side-effect-free and testable.

    Slice 7a (this implementation): single connection at a time,
    single user-provided handler.  Routing + bounded multi-connection
    + per-tick budgets land in 7b / 7c.
    """

    def __init__(
        self,
        *,
        listener_factory: object,
        handler: object,
        max_connections: int = DEFAULT_MAX_CONNECTIONS,
        request_timeout_ms: int = DEFAULT_REQUEST_TIMEOUT_MS,
        recv_budget_per_tick: int = DEFAULT_RECV_BUDGET_PER_TICK,
        send_budget_per_tick: int = DEFAULT_SEND_BUDGET_PER_TICK,
        max_request_body_bytes: int = DEFAULT_MAX_REQUEST_BODY_BYTES,
        ticks_ms_func: object = ticks_ms,
        ticks_add_func: object = ticks_add,
        ticks_diff_func: object = ticks_diff,
    ) -> None:
        """Wire up the server.

        Args:
            listener_factory: Callable ``() -> ListeningSocket`` that
                opens a non-blocking listener (typically
                ``lambda: tcp_listening_socket(host, port,
                radio=wifi.radio)``).  Invoked once on the first
                :meth:`handle` call.
            handler: Callable ``(Request) -> Response`` invoked once
                per accepted connection after the request headers + body
                are fully parsed.  Slice 7b adds a ``@server.route``
                decorator that wraps this with a router; slice 7a
                takes the bare handler.
            max_connections: Cap on simultaneous in-flight connections.
                Default 4 — sized for Pi Pico W heap.  Slice 7a
                serialises to one in flight; the cap is enforced
                from 7c onward.
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
            ticks_ms_func: Inject a fake ``ticks_ms`` for testing.
            ticks_add_func: Inject a fake ``ticks_add`` for testing.
            ticks_diff_func: Inject a fake ``ticks_diff`` for testing.
        """
        self._listener_factory = listener_factory
        self._handler = handler
        self._max_connections = max_connections
        self._request_timeout_ms = request_timeout_ms
        self._recv_budget_per_tick = recv_budget_per_tick
        self._send_budget_per_tick = send_budget_per_tick
        self._max_request_body_bytes = max_request_body_bytes

        self._ticks_ms = ticks_ms_func
        self._ticks_add = ticks_add_func
        self._ticks_diff = ticks_diff_func

        self._listener = None
        self._connections = []

        # Optional event hook.
        self.on_error = _no_callback

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
    # Runner contract — Decision 0014
    # ------------------------------------------------------------------

    def check(self, now_ms):  # noqa: ARG002 — runner contract uses now_ms
        """Return ``True`` if there's accept work or in-flight work."""
        return self._listener is None or bool(self._connections) or True

    def handle(self, now_ms):
        """One tick of progress: lazy-open listener, accept, advance conns."""
        if self._listener is None:
            self._listener = self._listener_factory()
            _force_non_blocking(self._listener)
        # Try to accept up to one new connection per tick (Decision 0041 §4).
        if len(self._connections) < self._max_connections:
            self._try_accept(now_ms)
        # Advance every in-flight connection.  Iterate over a copy so
        # connections can finish + be removed during the loop.
        for connection in list(self._connections):
            connection.tick(now_ms, ticks_diff_func=self._ticks_diff)
            if connection.is_done:
                connection.close()
                self._connections.remove(connection)

    def _try_accept(self, now_ms):
        """Best-effort accept of one pending connection."""
        try:
            accept_result = self._listener.accept()
        except OSError as accept_error:
            errno = accept_error.args[0] if accept_error.args else None
            if errno in (11, 35):  # EAGAIN
                return
            raise
        if accept_result is None:
            return
        client_socket, peer = accept_result
        _force_non_blocking(client_socket)
        deadline = self._ticks_add(self._ticks_ms(), self._request_timeout_ms)
        connection = _Connection(
            client_socket,
            peer,
            handler=self._handler,
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
    if headers is not None:
        if isinstance(headers, (dict, CaseInsensitiveDict)):
            iterable = headers.items()
        else:
            iterable = headers
        for name, value in iterable:
            merged_headers[name] = value
    reason = _REASONS.get(status, "Unknown")
    return Response(
        status_code=status,
        reason=reason,
        headers=merged_headers,
        body=encoded_body,
    )


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
