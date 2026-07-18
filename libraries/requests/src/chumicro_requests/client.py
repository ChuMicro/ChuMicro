"""HTTP/1.1 client built on chumicro-sockets + chumicro-timing.

:class:`HttpClient` is the entry point. It is runner-shaped:
:meth:`HttpClient.check` reports whether work is pending and
:meth:`HttpClient.handle` performs one tick of progress, with no threads
or async. v1 runs one request at a time; issuing another while one is in
flight raises :class:`HttpBusyError`. The client does GET / POST / PUT /
PATCH / DELETE over HTTP and HTTPS, JSON bodies via ``json=``, capped
redirect following, and response bodies buffered whole or streamed into
a caller-owned buffer with ``stream=True``.
"""

import errno
import json

from chumicro_requests._wire import (
    DEFAULT_BODY_BUFFER_SIZE,
    DEFAULT_MAX_BODY_BYTES,
    DEFAULT_MAX_REDIRECTS,
    DEFAULT_RECV_BUDGET_PER_TICK,
    DEFAULT_STREAM_BUFFER_SIZE,
    DEFAULT_TIMEOUT_MS,
    METHOD_PRESERVING_REDIRECT_STATUS_CODES,
    REDIRECT_STATUS_CODES,
    CaseInsensitiveDict,
    HttpBusyError,
    HttpError,
    HttpOversizedError,
    HttpTimeoutError,
    ParseState,
    ResponseParser,
    encode_request,
    parse_charset,
    parse_url,
    resolve_redirect_url,
)

# Poll-interest bits for ``io_interest``, mirroring chumicro_runner's
# IO_READ / IO_WRITE by value. Kept as literals so the client needs no
# runner import (bring-your-own-scheduler).
_IO_READ = 1
_IO_WRITE = 2

# EWOULDBLOCK is absent from MicroPython's errno; fall back to EAGAIN
# (they're the same value on the platforms that define both).
_EWOULDBLOCK = getattr(errno, "EWOULDBLOCK", errno.EAGAIN)


def _is_would_block(socket_error):
    """Return whether *socket_error* means "no progress yet, retry later"."""
    if socket_error.errno in (errno.EAGAIN, _EWOULDBLOCK):
        return True
    # CPython's non-blocking SSLSocket raises SSLWantRead/WriteError (not
    # EAGAIN); match by class name so HTTPS reads aren't treated as fatal.
    # MicroPython / CircuitPython TLS already normalize to EAGAIN.
    return type(socket_error).__name__ in (
        "SSLWantReadError",
        "SSLWantWriteError",
    )


# ---------------------------------------------------------------------------
# WhenOversized policy
# ---------------------------------------------------------------------------


class WhenOversized:
    """Policy for response bodies exceeding ``max_body_bytes``."""

    #: Drop the body silently: the request finishes ``done`` with an
    #: empty body and headers intact, for callers that only need the
    #: status code.
    DROP_SILENT = "drop_silent"

    #: Default.  Drop the body, fire ``client.on_oversized(reported_length,
    #: url)`` if set, otherwise behave like :data:`DROP_SILENT`.
    DROP_WITH_EVENT = "drop_with_event"

    #: Fail the request with :class:`HttpOversizedError`.  Use when
    #: the application can't tolerate truncated payloads.
    DISCONNECT = "disconnect"


def _encode_body(body, json_body):
    """Convert *body* or *json_body* into ``bytes`` (or ``None``)."""
    if json_body is not None:
        return json.dumps(json_body).encode("utf-8")
    if body is None:
        return None
    if isinstance(body, str):
        return body.encode("utf-8")
    if isinstance(body, (bytes, bytearray)):
        return bytes(body)
    raise TypeError(
        f"body must be bytes / bytearray / str, got {type(body).__name__}",
    )


def _merge_default_header(user_headers, name, value):
    """Return a CaseInsensitiveDict with *name=value* set unless *user_headers* overrides it."""
    merged = CaseInsensitiveDict()
    merged[name] = value
    if user_headers is None:
        return merged
    if isinstance(user_headers, CaseInsensitiveDict):
        iterable = user_headers.items()
    elif isinstance(user_headers, dict):
        iterable = user_headers.items()
    else:
        iterable = user_headers
    for header_name, header_value in iterable:
        merged[header_name] = header_value
    return merged


def _force_non_blocking(socket):
    """Best-effort ``setblocking(False)`` on a chumicro-sockets socket."""
    # The tick RX path needs recv_into to raise EAGAIN, never block;
    # MicroPython sockets start blocking, so enforce it here.
    setblocking = getattr(socket, "setblocking", None)
    if setblocking is None:
        return
    try:
        setblocking(False)
    except (OSError, AttributeError):  # pragma: no cover - defensive
        pass


# ---------------------------------------------------------------------------
# Response + RequestHandle
# ---------------------------------------------------------------------------


class Response:
    """Result of a completed HTTP request.

    Constructed by the client when the response parser hits ``DONE``;
    callers read but don't mutate.

    Attributes:
        status_code: Integer HTTP status (e.g. ``200``).
        reason: Reason phrase from the status line (e.g. ``"OK"``).
        http_version: Protocol version string (e.g. ``"HTTP/1.1"``).
        headers: :class:`CaseInsensitiveDict` of response headers.
        body: Raw response body as ``bytes``. Empty (``b""``) when
            :attr:`streamed`, where the body never materializes; read it
            through ``RequestHandle.read_body_into``.
        url: The URL that was requested.
        oversized_dropped: ``True`` when the body was dropped per
            ``when_oversized`` policy (``False`` for normal responses).
        streamed: ``True`` when the request was issued with ``stream=True``:
            status and headers are final, the body is consumed
            incrementally, and :attr:`text` / :meth:`json` refuse rather
            than decode an empty body.
    """

    def __init__(
        self,
        *,
        status_code: int,
        reason: str,
        http_version: str,
        headers: CaseInsensitiveDict,
        body: bytes,
        url: str,
        oversized_dropped: bool = False,
        encoding: str | None = None,
        streamed: bool = False,
    ) -> None:
        self.status_code = status_code
        self.reason = reason
        self.http_version = http_version
        self.headers = headers
        self.body = body
        self.url = url
        self.oversized_dropped = oversized_dropped
        self.streamed = streamed
        self._encoding_override = encoding

    def __repr__(self) -> str:
        return (
            f"Response(status_code={self.status_code}, "
            f"reason={self.reason!r}, url={self.url!r}, "
            f"body={len(self.body)} bytes)"
        )

    @property
    def encoding(self) -> str:
        """Charset used to decode :attr:`body` into :attr:`text`.

        Sniffed from the ``Content-Type`` header (default ``"utf-8"``).
        Set the property to override a wrong or missing server hint.
        """
        if self._encoding_override is not None:
            return self._encoding_override
        return parse_charset(self.headers.get("Content-Type"))

    @encoding.setter
    def encoding(self, value: str) -> None:
        self._encoding_override = value

    @property
    def text(self) -> str:
        """:attr:`body` decoded to ``str`` using :attr:`encoding`.

        Override :attr:`encoding` first if the server's Content-Type is
        wrong.

        Raises:
            UnicodeError: The body bytes don't match the encoding.
            HttpError: The response is :attr:`streamed`, so no whole body
                exists to decode.
        """
        if self.streamed:
            raise HttpError(
                "streamed response has no whole body; read it via "
                "RequestHandle.read_body_into",
            )
        return self.body.decode(self.encoding)

    def json(self) -> object:
        """Parse :attr:`body` as JSON and return the decoded object.

        Raises:
            ValueError: The body is not valid JSON (``json.JSONDecodeError``
                on CPython).
        """
        return json.loads(self.text)


class RequestHandle:
    """Caller-visible handle to an in-flight (or completed) request.

    Returned from :meth:`HttpClient.get`. Read the outcome in one of two
    ways: poll :attr:`done` and then read :attr:`result` (which returns
    the :class:`Response` or raises the failure; :attr:`error` is that
    same exception returned instead of raised), or pass ``on_done=`` to
    the request call to have the client invoke a callback with this
    handle when the request finishes. The callback fires after the client
    returns to idle, so it may issue the next request directly.

    :attr:`url` records the originally requested URL, not the final
    redirect target. For a ``stream=True`` request, :attr:`response` is
    set as soon as the final hop's headers are parsed, before
    :attr:`done`, and the body arrives incrementally through
    :meth:`read_body_into`.
    """

    def __init__(self, *, url, on_done=None, stream=False):
        self.url = url
        self.done = False
        self.response = None
        self.error = None
        self._on_done = on_done
        self._stream = stream
        # Object serving read_body_into for a streamed request. Held so
        # staged bytes stay readable after the client goes idle.
        self._body_source = None

    def read_body_into(self, buffer):
        """Copy received body bytes into caller-owned *buffer*; return the count.

        For requests issued with ``stream=True`` only. Returns ``0`` when
        no bytes are staged this tick; once :attr:`done` is ``True`` with
        :attr:`error` unset, ``0`` means end of body. Bytes staged before
        a failure stay readable, so check :attr:`error` and treat them as
        partial.

        Raises:
            HttpError: The request was not issued with ``stream=True``.
        """
        if not self._stream:
            raise HttpError(
                "read_body_into requires a request issued with stream=True",
            )
        source = self._body_source
        if source is None:
            return 0
        return source.read_body_into(buffer)

    def _publish_stream(self, response, body_source):
        """Set :attr:`response` (leaving :attr:`done` False) and install the body source."""
        self.response = response
        self._body_source = body_source

    def _invoke_done(self):
        """Fire the completion callback, if one was registered."""
        if self._on_done is not None:
            self._on_done(self)

    @property
    def result(self):
        """Return the :class:`Response`; raise the failure if any.

        Raises:
            HttpError: The request failed (timeout, protocol error,
                socket close mid-response, etc.).  Calling ``result``
                before ``done`` is ``True`` is a programming error
                and raises :class:`HttpError`.
        """
        if not self.done:
            raise HttpError(
                "RequestHandle.result accessed before done; "
                "poll handle.done first",
            )
        if self.error is not None:
            raise self.error
        return self.response

    def _set_response(self, response):
        self.response = response
        self.done = True

    def _set_error(self, error):
        self.error = error
        self.done = True


# ---------------------------------------------------------------------------
# HttpClient: runner-shaped, single-in-flight
# ---------------------------------------------------------------------------


class _RequestState:
    """Request-pipeline states: IDLE -> AWAITING_TRANSPORT -> SENDING -> RECEIVING -> IDLE."""

    IDLE = "idle"
    AWAITING_TRANSPORT = "awaiting_transport"
    SENDING = "sending"
    RECEIVING = "receiving"


class HttpClient:
    """Non-blocking HTTP/1.1 client.

    Construct with a *transport_factory* callable, then issue requests
    via :meth:`get` and drive them with :meth:`check` / :meth:`handle`
    from a runner tick or hand-rolled loop. The factory has the signature
    ``transport_factory(host, port, use_tls) -> connector``; the returned
    connector is a structural type (an object with ``state`` / ``socket``
    / ``last_error`` attributes, ``tick`` / ``cancel`` methods, and the
    runner-poll surface ``io_socket`` / ``io_interest`` /
    ``next_deadline``), so any object of that shape works and the client
    never imports a specific class.

    For a board with WiFi and chumicro-sockets,
    :func:`chumicro_requests.sockets_factory.chumicro_sockets_connector_factory`
    supplies the default factory, and :meth:`from_config` builds a client
    from runtime config.
    """

    @classmethod
    def from_config(
        cls,
        config: object,
        *,
        radio: object | None = None,
        ssl_context: object | None = None,
        transport_factory: object | None = None,
    ) -> "HttpClient":
        """Build an :class:`HttpClient` from runtime config.

        Reads these optional ``[tool.chumicro.config]`` keys, each with a
        default:

        * ``requests.default_timeout_ms`` (default :data:`DEFAULT_TIMEOUT_MS`).
        * ``requests.default_max_redirects`` (default :data:`DEFAULT_MAX_REDIRECTS`).
        * ``requests.user_agent`` (default ``"chumicro-requests/0.1"``).
        * ``requests.max_body_bytes`` (default :data:`DEFAULT_MAX_BODY_BYTES`).

        No key is required; an empty ``config`` is valid. When
        *transport_factory* is supplied the caller owns connection opening
        and *radio* / *ssl_context* are ignored; otherwise a factory is
        built from :func:`chumicro_sockets_connector_factory` using
        *radio* / *ssl_context*.
        """
        if transport_factory is None:
            try:
                from chumicro_requests.sockets_factory import (  # noqa: PLC0415 - lazy
                    chumicro_sockets_connector_factory,
                )
            except ImportError as exception:
                raise RuntimeError(
                    "chumicro_requests.sockets_factory not available "
                    "(excluded via __chumicro_skip_factories__ or "
                    "not on the board): pass transport_factory= "
                    "explicitly.",
                ) from exception

            transport_factory = chumicro_sockets_connector_factory(
                radio=radio, ssl_context=ssl_context,
            )
        return cls(
            transport_factory=transport_factory,
            default_timeout_ms=config.get(
                "requests.default_timeout_ms", DEFAULT_TIMEOUT_MS,
            ),
            default_max_redirects=config.get(
                "requests.default_max_redirects", DEFAULT_MAX_REDIRECTS,
            ),
            user_agent=config.get("requests.user_agent"),
            max_body_bytes=config.get(
                "requests.max_body_bytes", DEFAULT_MAX_BODY_BYTES,
            ),
        )

    def __init__(
        self,
        *,
        transport_factory: object,
        recv_budget_per_tick: int = DEFAULT_RECV_BUDGET_PER_TICK,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        when_oversized: str = WhenOversized.DROP_WITH_EVENT,
        default_timeout_ms: int = DEFAULT_TIMEOUT_MS,
        default_max_redirects: int = DEFAULT_MAX_REDIRECTS,
        stream_buffer_size: int = DEFAULT_STREAM_BUFFER_SIZE,
        user_agent: str | None = None,
        ticks: object | None = None,
    ) -> None:
        """Wire up the client.

        Args:
            transport_factory: Callable ``(host, port, use_tls) ->
                connector`` used per request hop to open the socket
                without blocking the runner.
            recv_budget_per_tick: Soft cap on bytes drained from the
                socket in a single :meth:`handle` call.
            max_body_bytes: Cap on a single buffered response body; not
                applied to requests issued with ``stream=True``.
            when_oversized: Policy for responses above the cap (see
                :class:`WhenOversized`).
            default_timeout_ms: Default per-request timeout in ms,
                overridable per call via ``timeout_ms=``.
            default_max_redirects: Default cap on 3xx hops to follow;
                ``0`` returns the 3xx response as-is.
            stream_buffer_size: Staging capacity in bytes for each
                ``stream=True`` request's body window.
            user_agent: Override for the default ``User-Agent`` header.
            ticks: Optional tick source matching the
                ``chumicro_timing.ticks`` shape; defaults to that
                submodule.
        """
        self._transport_factory = transport_factory
        self._connector = None
        self._recv_budget_per_tick = recv_budget_per_tick
        # Pre-allocated recv scratch reused every tick (a memoryview goes
        # to recv_into, no per-call alloc). Capped at 512 B so a generous
        # recv_budget_per_tick doesn't pin a large resident buffer.
        self._recv_buffer = bytearray(min(recv_budget_per_tick, 512))
        self._recv_view = memoryview(self._recv_buffer)
        self._max_body_bytes = max_body_bytes
        self._when_oversized = when_oversized
        self._default_timeout_ms = default_timeout_ms
        self._user_agent = user_agent or "chumicro-requests/0.1"

        if ticks is None:
            from chumicro_timing import ticks  # noqa: PLC0415 - DI fallback
        self._ticks = ticks

        self._default_max_redirects = default_max_redirects

        self._state = _RequestState.IDLE
        self._socket = None
        self._handle = None  # current RequestHandle
        # Handle whose on_done callback is due to fire, drained by
        # _fire_completion after the pipeline tick so a raising callback
        # reaches the caller's loop, not the pipeline's error handling.
        self._completed_handle = None
        self.url = None
        self._tx_buffer = b""  # request bytes pending send
        self._tx_offset = 0
        self._parser = None
        # Long-lived body buffer reused across requests and passed to each
        # fresh parser, so a per-request body alloc happens only when a
        # response exceeds body_buffer_size.
        self._body_buffer = bytearray(DEFAULT_BODY_BUFFER_SIZE)
        self._body_buffer_view = memoryview(self._body_buffer)
        self._stream_buffer_size = stream_buffer_size
        # True while the in-flight request was issued with stream=True.
        self._stream = False
        self._deadline_ticks = None
        # Per-request redirect bookkeeping captured at _start_request, so
        # each hop sees the same budget and the original method/body for
        # 307/308 replay.
        self._redirects_remaining = 0
        self._original_method = None
        self._original_headers = None
        self._original_body = None
        self._original_json_body = None

        # Optional event hooks.
        self.on_oversized = lambda *_args, **_kwargs: None

    # ------------------------------------------------------------------
    # Public observation
    # ------------------------------------------------------------------

    @property
    def busy(self):
        """``True`` while a request is in flight."""
        return self._state != _RequestState.IDLE

    # ------------------------------------------------------------------
    # Runner I/O interest (read by ``Runner.wait``)
    # ------------------------------------------------------------------

    @property
    def io_socket(self):
        """Underlying pollable socket while in flight, else ``None``.

        ``Runner.wait`` registers this with ``select.poll``. During
        ``AWAITING_TRANSPORT`` it forwards to the connector's in-flight
        pollable so the runner parks on the right handle between connect
        phases; once promoted, the socket is returned as-is.
        """
        if self._state == _RequestState.AWAITING_TRANSPORT:
            return self._connector.io_socket if self._connector is not None else None
        return self._socket

    def io_interest(self, now_ms):
        """Poll-interest bitmask OR-ing ``_IO_READ`` / ``_IO_WRITE``.

        ``_IO_READ`` while waiting on response bytes, ``_IO_WRITE`` while
        request bytes remain to send, the connector's mask during
        ``AWAITING_TRANSPORT``, and ``0`` when idle. A streamed request
        whose staging window is full also reports ``0`` (registering read
        interest would spin the poll loop until the caller drains);
        ``next_deadline`` still wakes the runner for timeout enforcement.
        """
        if self._state == _RequestState.AWAITING_TRANSPORT:
            return self._connector.io_interest(now_ms) if self._connector is not None else 0
        if self._state == _RequestState.RECEIVING:
            if (
                self._stream
                and self._parser is not None
                and self._parser.body_free() == 0
            ):
                return 0
            return _IO_READ
        if self._state == _RequestState.SENDING:
            return _IO_WRITE
        return 0

    def next_deadline(self, now_ms):
        """Return the per-request timeout deadline, or ``None`` when idle.

        Lets ``Runner.wait`` wake for timeout enforcement even on a
        quiescent socket. While ``AWAITING_TRANSPORT`` with no pollable
        yet (the connector is still resolving DNS), this returns *now_ms*
        so the loop keeps ticking the connector forward instead of
        sleeping toward the far deadline; once a pollable exists the
        per-request budget governs again.
        """
        if self._state == _RequestState.IDLE:
            return None
        if (
            self._state == _RequestState.AWAITING_TRANSPORT
            and self.io_socket is None
        ):
            return now_ms
        return self._deadline_ticks

    # ------------------------------------------------------------------
    # Public request API
    # ------------------------------------------------------------------

    def request(
        self,
        method: str,
        url: str,
        *,
        body: bytes | str | None = None,
        json: object | None = None,
        headers: CaseInsensitiveDict | dict | list | tuple | None = None,
        timeout_ms: int | None = None,
        max_redirects: int | None = None,
        on_done: object | None = None,
        stream: bool = False,
    ) -> "RequestHandle":
        """Issue *method* against *url*; return a :class:`RequestHandle`.

        Generic entry behind the per-verb methods: *method* is sent
        verbatim, and body / json / redirect / timeout semantics match
        :meth:`post`. Pass ``stream=True`` to consume the body
        incrementally: ``handle.response`` is set once the final hop's
        headers are parsed, and the body is read tick by tick via
        ``handle.read_body_into(buffer)`` (``0`` after ``handle.done``
        means end of body). ``max_body_bytes`` and the ``WhenOversized``
        policy do not apply to streamed bodies.
        """
        return self._start_request(
            method, url,
            body=body, json_body=json,
            headers=headers, timeout_ms=timeout_ms,
            max_redirects=max_redirects, on_done=on_done, stream=stream,
        )

    def get(
        self,
        url: str,
        *,
        headers: CaseInsensitiveDict | dict | list | tuple | None = None,
        timeout_ms: int | None = None,
        max_redirects: int | None = None,
        on_done: object | None = None,
        stream: bool = False,
    ) -> "RequestHandle":
        """Issue a GET request; return a :class:`RequestHandle`.

        Poll ``handle.done``, then read ``handle.result`` for the
        :class:`Response`.  Alternatively pass ``on_done=callback`` to
        have the client call ``callback(handle)`` when the request
        finishes (see :class:`RequestHandle`).  ``max_redirects=0``
        returns a 3xx as-is.  ``stream=True`` delivers the body
        incrementally (see :meth:`request`).  Raises
        :class:`HttpBusyError` if a request is already in flight,
        :class:`HttpURLError` if *url* doesn't parse.
        """
        return self._start_request(
            "GET", url, headers=headers, timeout_ms=timeout_ms,
            max_redirects=max_redirects, on_done=on_done, stream=stream,
        )

    def post(
        self,
        url: str,
        *,
        body: bytes | str | None = None,
        json: object | None = None,
        headers: CaseInsensitiveDict | dict | list | tuple | None = None,
        timeout_ms: int | None = None,
        max_redirects: int | None = None,
        on_done: object | None = None,
        stream: bool = False,
    ) -> "RequestHandle":
        """Issue a POST request; return a :class:`RequestHandle`.

        Pass exactly one of *body* or *json*.  *json* auto-encodes via
        :func:`json.dumps` and sets ``Content-Type: application/json``
        unless the caller overrides it via *headers*.  *body* as ``str``
        is encoded UTF-8.  ``Content-Length`` is auto-added.  Passing
        both *body* and *json* raises ``ValueError``.  ``on_done`` is the
        optional completion callback (see :class:`RequestHandle`);
        ``stream=True`` delivers the response body incrementally (see
        :meth:`request`).
        """
        return self._start_request(
            "POST", url,
            body=body, json_body=json,
            headers=headers, timeout_ms=timeout_ms,
            max_redirects=max_redirects, on_done=on_done, stream=stream,
        )

    def put(
        self,
        url: str,
        *,
        body: bytes | str | None = None,
        json: object | None = None,
        headers: CaseInsensitiveDict | dict | list | tuple | None = None,
        timeout_ms: int | None = None,
        max_redirects: int | None = None,
        on_done: object | None = None,
        stream: bool = False,
    ) -> "RequestHandle":
        """Issue a PUT request.  Same body / json / stream semantics as :meth:`post`."""
        return self._start_request(
            "PUT", url,
            body=body, json_body=json,
            headers=headers, timeout_ms=timeout_ms,
            max_redirects=max_redirects, on_done=on_done, stream=stream,
        )

    def patch(
        self,
        url: str,
        *,
        body: bytes | str | None = None,
        json: object | None = None,
        headers: CaseInsensitiveDict | dict | list | tuple | None = None,
        timeout_ms: int | None = None,
        max_redirects: int | None = None,
        on_done: object | None = None,
        stream: bool = False,
    ) -> "RequestHandle":
        """Issue a PATCH request.  Same body / json / stream semantics as :meth:`post`."""
        return self._start_request(
            "PATCH", url,
            body=body, json_body=json,
            headers=headers, timeout_ms=timeout_ms,
            max_redirects=max_redirects, on_done=on_done, stream=stream,
        )

    def delete(
        self,
        url: str,
        *,
        headers: CaseInsensitiveDict | dict | list | tuple | None = None,
        timeout_ms: int | None = None,
        max_redirects: int | None = None,
        on_done: object | None = None,
        stream: bool = False,
    ) -> "RequestHandle":
        """Issue a DELETE request. No body: the verb is intransitive in v1."""
        return self._start_request(
            "DELETE", url, headers=headers, timeout_ms=timeout_ms,
            max_redirects=max_redirects, on_done=on_done, stream=stream,
        )

    # ------------------------------------------------------------------
    # Runner contract
    # ------------------------------------------------------------------

    def check(self, now_ms):  # noqa: ARG002 - runner contract uses now_ms
        """Return ``True`` if there's outbound bytes to send or readable bytes."""
        return self._state != _RequestState.IDLE

    def handle(self, now_ms):
        """One tick of progress on the in-flight request.

        Advances the connector while ``AWAITING_TRANSPORT``, sends queued
        request bytes, drains inbound bytes (up to
        ``recv_budget_per_tick``), feeds the parser, and finishes the
        handle when the response is complete. The per-request
        ``timeout_ms`` is checked at the top of each tick, so a stuck
        handshake or recv fails with :class:`HttpTimeoutError` and the
        socket is closed.
        """
        if self._state == _RequestState.IDLE:
            return
        self._drive_tick(now_ms)
        # Fire on_done after the pipeline tick: a callback that raises or
        # issues a follow-up request must reach the caller's loop, not be
        # caught by _drive_tick's error handlers.
        self._fire_completion()

    def cancel(self):
        """Abort the in-flight request; no-op when idle.

        Closes the socket, fails the handle with :class:`HttpError`,
        fires its ``on_done`` callback, and returns the client to idle so
        the next request can be issued immediately. The exit for a caller
        that decides mid-response to stop, without waiting for
        ``timeout_ms``.
        """
        if self._state == _RequestState.IDLE:
            return
        self._fail(HttpError(f"request to {self.url!r} cancelled"))
        self._fire_completion()

    def _drive_tick(self, now_ms):
        """Run one pipeline tick (timeout check, connector, send, recv); no callbacks."""
        if self._deadline_ticks is not None and self._ticks.ticks_diff(
            self._deadline_ticks, now_ms,
        ) <= 0:
            self._fail(HttpTimeoutError(
                f"request to {self.url!r} timed out after deadline",
            ))
            return

        try:
            if self._state == _RequestState.AWAITING_TRANSPORT:
                if not self._advance_connector(now_ms):
                    return
                # Connector reached ``ready``; fall through and start sending.
            if self._state == _RequestState.SENDING:
                self._drive_send()
            if self._state == _RequestState.RECEIVING:
                self._drive_recv()
        except HttpError as protocol_error:
            self._fail(protocol_error)
        except OSError as socket_error:
            self._fail(HttpError(f"socket error: {socket_error}"))

    def _fire_completion(self):
        """Invoke the finished handle's on_done callback, if one is pending."""
        finished_handle = self._completed_handle
        self._completed_handle = None
        if finished_handle is not None:
            finished_handle._invoke_done()  # noqa: SLF001 - internal handoff

    def _advance_connector(self, now_ms):
        """Tick the connector one phase; promote its socket and return True when ``ready``."""
        connector = self._connector
        connector.tick(now_ms)
        if connector.state == "ready":
            self._socket = connector.socket
            self._connector = None
            _force_non_blocking(self._socket)
            self._state = _RequestState.SENDING
            return True
        if connector.state == "failed":
            error = connector.last_error
            self._connector = None
            self._fail(HttpError(f"connector failed: {error}"))
            return False
        return False

    # ------------------------------------------------------------------
    # Internal: request lifecycle
    # ------------------------------------------------------------------

    def _start_request(
        self, method, url, *, headers, timeout_ms,
        body=None, json_body=None, max_redirects=None, on_done=None,
        stream=False,
    ):
        """Common path for GET / POST / PUT / PATCH / DELETE."""
        if self._state != _RequestState.IDLE:
            raise HttpBusyError(
                f"client busy on {self.url!r}; await handle.done before issuing another",
            )
        if body is not None and json_body is not None:
            raise ValueError(
                "pass body= or json= but not both",
            )
        encoded_body = _encode_body(body, json_body)
        self._stream = stream
        self._redirects_remaining = (
            max_redirects if max_redirects is not None else self._default_max_redirects
        )
        # Capture the request shape for 307/308 redirect replay. The body
        # is kept only when a redirect can fire; with redirects disabled
        # it would pin a duplicate of the whole body for nothing.
        self._original_method = method
        self._original_headers = headers
        self._original_body = encoded_body if self._redirects_remaining > 0 else None
        self._original_json_body = json_body
        timeout = timeout_ms if timeout_ms is not None else self._default_timeout_ms
        self._deadline_ticks = self._ticks.ticks_add(self._ticks.ticks_ms(), timeout)
        self._handle = RequestHandle(url=url, on_done=on_done, stream=stream)
        self._start_hop(url, method, encoded_body, headers, json_body is not None)
        return self._handle

    def _start_hop(
        self, url, method, encoded_body, user_headers, json_default_content_type,
    ):
        """Open a socket and queue the request bytes for *url* (one redirect hop)."""
        merged_headers = user_headers
        if json_default_content_type:
            merged_headers = _merge_default_header(
                user_headers, "Content-Type", "application/json",
            )
        scheme, host, port, path = parse_url(url)
        use_tls = scheme == "https"
        default_port = 443 if use_tls else 80
        host_header = host if port == default_port else f"{host}:{port}"
        request_bytes = encode_request(
            method,
            host_header,
            path,
            headers=merged_headers,
            body=encoded_body,
            user_agent=self._user_agent,
        )
        self._connector = self._transport_factory(host, port, use_tls)
        self.url = url
        self._tx_buffer = request_bytes
        self._tx_offset = 0
        # Per-request parser. Buffered requests reuse the long-lived body
        # buffer; streamed requests get a fresh per-hop window instead,
        # since the handle keeps it alive after the client goes idle and
        # sharing would let the next request clobber a finished stream.
        if self._stream:
            self._parser = ResponseParser(
                max_body_bytes=self._max_body_bytes,
                stream_body=True,
                body_buffer=bytearray(self._stream_buffer_size),
            )
        else:
            self._parser = ResponseParser(
                max_body_bytes=self._max_body_bytes,
                body_buffer=self._body_buffer,
                body_buffer_view=self._body_buffer_view,
            )
        # Defer the SENDING transition until the connector reaches
        # ``ready``; until then the tick path stays in AWAITING_TRANSPORT.
        self._state = _RequestState.AWAITING_TRANSPORT

    def _drive_send(self):
        """Push queued request bytes onto the socket; transition on completion."""
        # Bind the buffer view once, not per iteration: a backpressured
        # send loops here, and rebuilding it each pass would allocate.
        tx_view = memoryview(self._tx_buffer)
        while self._tx_offset < len(self._tx_buffer):
            view = tx_view[self._tx_offset:]
            try:
                sent = self._socket.send(view)
            except OSError as socket_error:
                if _is_would_block(socket_error):
                    return
                raise
            if sent <= 0:
                return  # Socket would block; wait for next tick.
            self._tx_offset += sent
        # Release the sent request bytes before receiving: the response
        # path never re-reads them, and holding them pinned would keep a
        # second copy of the body resident for the whole exchange.
        self._tx_buffer = b""
        self._tx_offset = 0
        self._state = _RequestState.RECEIVING

    def _drive_recv(self):
        """Drain the socket up to ``recv_budget_per_tick`` and feed the parser."""
        consumed = 0
        budget = self._recv_budget_per_tick
        scratch_size = len(self._recv_buffer)
        parser = self._parser
        streaming = self._stream
        while consumed < budget and parser.state not in (
            ParseState.DONE, ParseState.ERROR,
        ):
            capacity = min(scratch_size, budget - consumed)
            if streaming:
                free = parser.body_free()
                if capacity > free:
                    capacity = free
                if capacity == 0:
                    # Staging full; wait for read_body_into to drain.
                    return
            # recv into the pre-allocated scratch and feed a memoryview
            # window into it, so neither recv nor feed allocates per tick.
            try:
                got = self._socket.recv_into(self._recv_view, capacity)
            except OSError as socket_error:
                if _is_would_block(socket_error):
                    return
                raise
            if got == 0:
                # Peer close: feed_eof so the parser decides end-of-body
                # (length-unknown) vs. protocol error (Content-Length short).
                parser.feed_eof()
                break
            parser.feed(self._recv_view[:got])
            if streaming:
                self._sync_stream_state()
            consumed += got
        if parser.state == ParseState.ERROR:
            raise parser.error
        if parser.state == ParseState.DONE:
            self._complete()

    def _sync_stream_state(self):
        """Publish or discard a streamed response once its headers are in."""
        parser = self._parser
        if not parser.headers_complete or parser.state == ParseState.ERROR:
            return
        handle = self._handle
        if handle.response is not None:
            return
        if (
            self._redirects_remaining > 0
            and parser.status_code in REDIRECT_STATUS_CODES
            and parser.headers.get("Location") is not None
        ):
            parser.discard_body()
            return
        response = Response(
            status_code=parser.status_code,
            reason=parser.reason,
            http_version=parser.http_version,
            headers=parser.headers,
            body=b"",
            url=self.url,
            streamed=True,
        )
        handle._publish_stream(response, parser)  # noqa: SLF001 - internal handoff

    def _complete(self):
        """Follow a redirect or hand the finished response to the handle."""
        parser = self._parser
        status_code = parser.status_code
        if self._stream:
            # feed_eof can reach DONE without a trailing feed, so run
            # the publish/discard decision once more before finishing.
            self._sync_stream_state()
            handle = self._handle
            if handle.response is None:
                # Only a followable redirect hop reaches DONE without a
                # published response, so Location is present here.
                self._follow_redirect(status_code, parser.headers.get("Location"))
                return
            # Mark the already-published response done; the handle keeps
            # the parser, so staged bytes stay readable after reset.
            handle._set_response(handle.response)  # noqa: SLF001 - internal handoff
            self._reset_socket()
            return
        if self._redirects_remaining > 0 and status_code in REDIRECT_STATUS_CODES:
            location = parser.headers.get("Location")
            if location is not None:
                self._follow_redirect(status_code, location)
                return
        response = Response(
            status_code=status_code,
            reason=parser.reason,
            http_version=parser.http_version,
            headers=parser.headers,
            body=parser.body,
            url=self.url,
            oversized_dropped=False,
        )
        self._handle._set_response(response)  # noqa: SLF001 - internal handoff
        self._reset_socket()

    def _follow_redirect(self, status_code, location):
        """Resolve the next URL, swap state, and re-issue the request."""
        try:
            new_url = resolve_redirect_url(self.url, location)
        except HttpError as redirect_error:
            self._handle._set_error(redirect_error)  # noqa: SLF001
            self._reset_socket()
            return
        if status_code in METHOD_PRESERVING_REDIRECT_STATUS_CODES:
            next_method = self._original_method
            next_body = self._original_body
            next_json_default_content_type = self._original_json_body is not None
        else:
            # 301 / 302 / 303: drop body, switch to GET.
            next_method = "GET"
            next_body = None
            next_json_default_content_type = False
        # Tear down the current socket but keep the handle, deadline, and
        # original-request capture: the request as a whole is still in flight.
        self._close_socket_only()
        self._redirects_remaining -= 1
        try:
            self._start_hop(
                new_url, next_method, next_body,
                self._original_headers, next_json_default_content_type,
            )
        except OSError as factory_error:
            self._handle._set_error(  # noqa: SLF001
                HttpError(f"connector factory failed during redirect: {factory_error}"),
            )
            self._reset_socket()
        except HttpError as redirect_error:
            self._handle._set_error(redirect_error)  # noqa: SLF001
            self._reset_socket()
        except Exception as unexpected_error:  # noqa: BLE001 - the socket is already torn down; any escape here leaves the handle unresolved and unreachable
            self._handle._set_error(  # noqa: SLF001
                HttpError(f"redirect hop failed: {unexpected_error}"),
            )
            self._reset_socket()

    def _fail(self, error):
        """Attach *error* to the in-flight handle, close the socket, reset."""
        # If the parser raised oversized while we were configured to
        # drop, swap the error for an oversized-event hook firing.
        if isinstance(error, HttpOversizedError):
            if self._when_oversized == WhenOversized.DROP_SILENT:
                self._complete_oversized_drop()
                return
            if self._when_oversized == WhenOversized.DROP_WITH_EVENT:
                self.on_oversized(error.reported_length, self.url)
                self._complete_oversized_drop()
                return
            # DISCONNECT: fall through to fail path.
        if self._handle is not None:
            self._handle._set_error(error)  # noqa: SLF001 - internal handoff
        self._reset_socket()

    def _complete_oversized_drop(self):
        """Finish the request as a drop: empty body, oversized_dropped=True."""
        response = Response(
            status_code=self._parser.status_code,
            reason=self._parser.reason,
            http_version=self._parser.http_version,
            headers=self._parser.headers,
            body=b"",
            url=self.url,
            oversized_dropped=True,
        )
        self._handle._set_response(response)  # noqa: SLF001 - internal handoff
        self._reset_socket()

    def _close_socket_only(self):
        """Close the socket but leave the handle, deadline, and redirect bookkeeping intact."""
        if self._connector is not None:
            self._connector.cancel()
            self._connector = None
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:  # pragma: no cover - defensive
                pass
        self._socket = None
        self._tx_buffer = b""
        self._tx_offset = 0
        # Drop the parser; the long-lived body buffer stays on
        # self._body_buffer for the next request's parser to reuse.
        self._parser = None
        self._state = _RequestState.IDLE  # Brief; _start_hop flips back.

    def _reset_socket(self):
        """Close the socket and clear all per-request state, queuing the on_done callback."""
        self._close_socket_only()
        finished_handle = self._handle
        self._handle = None
        self.url = None
        self._stream = False
        self._original_method = None
        self._original_headers = None
        self._original_body = None
        self._original_json_body = None
        self._deadline_ticks = None
        self._redirects_remaining = 0
        if finished_handle is not None:
            self._completed_handle = finished_handle
