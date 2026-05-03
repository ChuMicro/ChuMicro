"""HTTP/1.1 client built on chumicro-sockets + chumicro-timing.

:class:`HttpClient` is the entry point.  Runner-shaped per Decision
0014 — :meth:`check(now_ms) -> bool` reports whether work is pending;
:meth:`handle(now_ms)` performs one tick of progress.  No threads,
no async — cooperative dispatch in the caller's tick loop.

Single-in-flight in v1 (Decision 0040 §1): :meth:`HttpClient.get` /
``post`` / etc. while a request is still running raises
:class:`HttpBusyError`.  The user pattern::

    client = HttpClient(connection_factory=...)
    handle = client.get("http://api.example.com/now", timeout_ms=5000)

    while not handle.done:
        if client.check(now_ms()):
            client.handle(now_ms())

    response = handle.result   # raises on failure

Slice 3a (this file): plain HTTP GET, status line + headers + body
bytes via ``Content-Length`` or read-until-close.  TLS, POST, JSON,
redirects, and chunked encoding ship in subsequent slices.
"""

import json

from chumicro_timing import ticks_add, ticks_diff, ticks_ms

from chumicro_requests._wire import (
    DEFAULT_BODY_BUFFER_SIZE,
    DEFAULT_MAX_BODY_BYTES,
    DEFAULT_MAX_REDIRECTS,
    DEFAULT_RECV_BUDGET_PER_TICK,
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

# ---------------------------------------------------------------------------
# WhenOversized policy
# ---------------------------------------------------------------------------


class WhenOversized:
    """Policy for response bodies exceeding ``max_body_bytes``.

    Mirrors :class:`chumicro_mqtt.WhenOversized` — the third user is
    when we factor a shared one out of ``chumicro_compat``.  Until
    then, copy-don't-couple keeps each library's policy enum local
    to its concerns.
    """

    #: Drop the body silently.  The request finishes as ``done`` with
    #: an empty body and the headers intact — useful when callers only
    #: care about the status code (e.g. liveness checks).
    DROP_SILENT = "drop_silent"

    #: Default.  Drop the body, fire ``client.on_oversized(url,
    #: reported_length)`` if set, otherwise behave like
    #: :data:`DROP_SILENT`.
    DROP_WITH_EVENT = "drop_with_event"

    #: Fail the request with :class:`HttpOversizedError`.  Use when
    #: the application can't tolerate truncated payloads.
    DISCONNECT = "disconnect"


def _no_callback(*_args, **_kwargs):
    """Default no-op callback so handlers can be stored unconditionally."""
    return None


def _encode_body(body, json_body):
    """Convert *body* / *json_body* into ``bytes`` (or ``None``).

    Mirrors `HttpClient._start_request`'s contract: at most one of
    *body* / *json_body* is non-None (caller already validated).
    Pulled out so the redirect-replay path can re-encode without
    repeating the type-check ladder.
    """
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
    """Return a CaseInsensitiveDict with *name=value* applied unless overridden.

    *user_headers* may be ``None``, a ``dict``, a
    :class:`CaseInsensitiveDict`, or an iterable of ``(name, value)``
    pairs.  Used by :meth:`HttpClient.post` to default
    ``Content-Type: application/json`` when the caller passed
    ``json=...`` without setting Content-Type explicitly.
    """
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
    """Best-effort ``setblocking(False)`` on a chumicro-sockets socket.

    Mirrors :func:`chumicro_mqtt.client._force_non_blocking` — the
    tick-based RX path expects ``recv_into`` to raise EAGAIN when
    no data is available, never to block.  MicroPython's stdlib
    socket starts in blocking mode and chumicro_sockets' MP adapter
    doesn't override that, so we enforce here.
    """
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
        body: Raw response body as ``bytes``.
        url: The URL that was requested.
        oversized_dropped: ``True`` when the body was dropped per
            ``when_oversized`` policy (``False`` for normal responses).

    Body decoding (slice 3b):

    * :attr:`encoding` — charset sniffed from ``Content-Type``,
      defaulting to ``"utf-8"``.  Settable so callers can override
      a wrong / missing server hint.
    * :attr:`text` — body decoded as a ``str`` using :attr:`encoding`.
    * :meth:`json` — body parsed as JSON into Python objects.
    """

    __slots__ = (
        "_encoding_override",
        "body",
        "headers",
        "http_version",
        "oversized_dropped",
        "reason",
        "status_code",
        "url",
    )

    def __init__(
        self,
        *,
        status_code: int,
        reason: str,
        http_version: str,
        headers: object,
        body: bytes,
        url: str,
        oversized_dropped: bool = False,
        encoding: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.reason = reason
        self.http_version = http_version
        self.headers = headers
        self.body = body
        self.url = url
        self.oversized_dropped = oversized_dropped
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

        Sniffed from the ``Content-Type`` response header on first
        access (default ``"utf-8"`` when absent or charset-less).
        Set the property to override — useful when a server's
        Content-Type lies or omits the charset.
        """
        if self._encoding_override is not None:
            return self._encoding_override
        return parse_charset(self.headers.get("Content-Type"))

    @encoding.setter
    def encoding(self, value: str) -> None:
        self._encoding_override = value

    @property
    def text(self) -> str:
        """:attr:`body` decoded using :attr:`encoding`.

        Raises ``UnicodeError`` if the body bytes don't match
        the encoding.  Override :attr:`encoding` first if you know
        the server's Content-Type is wrong.
        """
        return self.body.decode(self.encoding)

    def json(self) -> object:
        """Parse :attr:`body` as JSON and return the decoded object.

        Decodes via :attr:`text` first so the JSON parser sees a
        properly-decoded string (matching CPython ``requests``
        semantics).  Raises ``ValueError`` (specifically
        ``json.JSONDecodeError`` on CPython) when the body isn't
        valid JSON.
        """
        return json.loads(self.text)


class RequestHandle:
    """Caller-visible handle to an in-flight (or completed) request.

    Returned from :meth:`HttpClient.get`.  The caller polls
    :attr:`done`; when ``True``, :attr:`result` returns the
    :class:`Response` (or raises the :class:`HttpError` that killed
    the request).  :attr:`error` is the same exception, returned
    instead of raised — useful when the caller wants to branch
    rather than catch.
    """

    __slots__ = ("_done", "_error", "_response", "_url")

    def __init__(self, *, url):
        self._url = url
        self._done = False
        self._response = None
        self._error = None

    @property
    def url(self):
        """The URL that was requested."""
        return self._url

    @property
    def done(self):
        """``True`` once the request finishes (success or failure)."""
        return self._done

    @property
    def response(self):
        """The :class:`Response` if the request succeeded, else ``None``."""
        return self._response

    @property
    def error(self):
        """The :class:`HttpError` if the request failed, else ``None``."""
        return self._error

    @property
    def result(self):
        """Return the :class:`Response`; raise the failure if any.

        Raises:
            HttpError: The request failed (timeout, protocol error,
                socket close mid-response, etc.).  Calling ``result``
                before ``done`` is ``True`` is a programming error
                and raises :class:`HttpError`.
        """
        if not self._done:
            raise HttpError(
                "RequestHandle.result accessed before done; "
                "poll handle.done first",
            )
        if self._error is not None:
            raise self._error
        return self._response

    def _set_response(self, response):
        """Internal: client calls this on success."""
        self._response = response
        self._done = True

    def _set_error(self, error):
        """Internal: client calls this on failure."""
        self._error = error
        self._done = True


# ---------------------------------------------------------------------------
# HttpClient — runner-shaped, single-in-flight
# ---------------------------------------------------------------------------


class _RequestState:
    """Internal request-pipeline states (Decision 0040 §1)."""

    IDLE = "idle"
    SENDING = "sending"
    RECEIVING = "receiving"


class HttpClient:
    """Non-blocking HTTP/1.1 client.

    Construct with a *connection_factory* callable; then issue requests
    via :meth:`get` and drive via :meth:`check` / :meth:`handle` from a
    runner tick or hand-rolled loop.

    The factory signature is::

        connection_factory(host: str, port: int, use_tls: bool) -> TCPClientSocket

    For a board with WiFi + chumicro-sockets, use
    :func:`chumicro_sockets_factory` to wire up the default::

        from chumicro_requests import HttpClient, chumicro_sockets_factory
        client = HttpClient(connection_factory=chumicro_sockets_factory())
    """

    def __init__(
        self,
        *,
        connection_factory: object,
        recv_budget_per_tick: int = DEFAULT_RECV_BUDGET_PER_TICK,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        when_oversized: str = WhenOversized.DROP_WITH_EVENT,
        default_timeout_ms: int = DEFAULT_TIMEOUT_MS,
        default_max_redirects: int = DEFAULT_MAX_REDIRECTS,
        user_agent: str | None = None,
        ticks_ms_func: object = ticks_ms,
        ticks_add_func: object = ticks_add,
        ticks_diff_func: object = ticks_diff,
    ) -> None:
        """Wire up the client.

        Args:
            connection_factory: Callable ``(host, port, use_tls) ->
                TCPClientSocket`` that opens a connected socket.  Use
                :func:`chumicro_sockets_factory` for the default
                wiring on a board.
            recv_budget_per_tick: Soft cap on bytes drained from the
                socket in a single :meth:`handle` call.  Default 1024.
                Bounds tick latency so concurrent runner tasks (LED
                blink, control loop) keep getting CPU time.  Mirrors
                :data:`chumicro_mqtt.MQTTClient` default.
            max_body_bytes: Cap on a single response body.  Default
                64 KB — Decision 0015 minimum board has 256 KB MCU
                RAM, so 64 KB leaves headroom.
            when_oversized: Policy for responses above the cap.  See
                :class:`WhenOversized`.
            default_timeout_ms: Default per-request timeout in ms.
                Overridable per-call via ``timeout_ms=...``.  Default
                10 000 ms.
            default_max_redirects: Default cap on 3xx hops the client
                follows before failing with :class:`HttpError`.
                Overridable per-call via ``max_redirects=...``.
                ``0`` returns the 3xx response as-is without
                following.  Default 5.
            user_agent: Override the default ``User-Agent`` header.
            ticks_ms_func: Inject a fake ``ticks_ms`` for testing;
                defaults to :func:`chumicro_timing.ticks_ms`.
            ticks_add_func: Inject a fake ``ticks_add`` for testing;
                defaults to :func:`chumicro_timing.ticks_add`.
            ticks_diff_func: Inject a fake ``ticks_diff`` for testing;
                defaults to :func:`chumicro_timing.ticks_diff`.
        """
        self._connection_factory = connection_factory
        self._recv_budget_per_tick = recv_budget_per_tick
        # Pre-allocated recv scratch buffer — reused on every tick so we
        # don't churn the heap with per-call allocations.  Mirrors the
        # static-buffer pattern in :class:`chumicro_mqtt._wire.PacketDecoder`
        # and ``chumicro_websockets._session.WebSocketSession`` — both caught
        # the per-tick alloc on a Pi Pico W's 124 KB heap.  Capped at 512 B
        # so a client with ``recv_budget_per_tick=64K`` doesn't pin 64 KB of
        # steady-state heap for a buffer that gets sliced down per call.
        recv_scratch_size = recv_budget_per_tick if recv_budget_per_tick <= 512 else 512
        self._recv_buffer = bytearray(recv_scratch_size)
        self._recv_view = memoryview(self._recv_buffer)
        self._max_body_bytes = max_body_bytes
        self._when_oversized = when_oversized
        self._default_timeout_ms = default_timeout_ms
        self._user_agent = user_agent or "chumicro-requests/0.1"

        self._ticks_ms = ticks_ms_func
        self._ticks_add = ticks_add_func
        self._ticks_diff = ticks_diff_func

        self._default_max_redirects = default_max_redirects

        self._state = _RequestState.IDLE
        self._socket = None
        self._handle = None  # current RequestHandle
        self._url = None
        self._original_url = None  # URL the user called get/post with
        self._tx_buffer = b""  # request bytes pending send
        self._tx_offset = 0
        self._parser = None
        # Long-lived body buffer reused across requests — the parser is
        # constructed per-request (Decision 0040 §1: single-in-flight)
        # but the body buffer is the only per-request alloc big enough
        # to fragment small-tier free lists on Lolin S2.  We hold the
        # buffer here and hand it to each parser so per-request body
        # alloc happens only when ``Content-Length > body_buffer_size``.
        # Live-board MP signal (``test_large_body_no_leak_no_fragmentation
        # _on_device``) caught the per-request body alloc churn at the
        # 1024 tier.
        self._body_buffer = bytearray(DEFAULT_BODY_BUFFER_SIZE)
        self._body_buffer_view = memoryview(self._body_buffer)
        self._deadline_ticks = None
        # Per-request redirect bookkeeping — captured at _start_request
        # so each follow-redirect hop sees the same budget + the
        # original method/body for 307/308 replay.
        self._redirects_remaining = 0
        self._original_method = None
        self._original_headers = None
        self._original_body = None
        self._original_json_body = None

        # Optional event hooks.
        self.on_oversized = _no_callback

    # ------------------------------------------------------------------
    # Public observation
    # ------------------------------------------------------------------

    @property
    def busy(self):
        """``True`` while a request is in flight."""
        return self._state != _RequestState.IDLE

    # ------------------------------------------------------------------
    # Public request API
    # ------------------------------------------------------------------

    def get(
        self,
        url: str,
        *,
        headers: object | None = None,
        timeout_ms: int | None = None,
        max_redirects: int | None = None,
    ) -> "RequestHandle":
        """Issue a GET request; return a :class:`RequestHandle`.

        The handle is the runnable thing — poll ``handle.done``, then
        read ``handle.result`` for the :class:`Response`.

        Args:
            url: Absolute URL — ``http://...`` or ``https://...``.
            headers: Optional ``dict`` / ``CaseInsensitiveDict`` /
                iterable of ``(name, value)`` pairs to override the
                defaults (``Host``, ``User-Agent``, ``Accept``,
                ``Accept-Encoding``, ``Connection``).
            timeout_ms: Per-request timeout override.  Falls back to
                the client's ``default_timeout_ms``.
            max_redirects: Per-request redirect budget override.
                ``0`` returns the 3xx response as-is; ``None`` falls
                back to the client's ``default_max_redirects``.

        Raises:
            HttpBusyError: A request is already in flight.
            HttpURLError: *url* didn't parse as a valid HTTP URL.
        """
        return self._start_request(
            "GET", url, headers=headers, timeout_ms=timeout_ms,
            max_redirects=max_redirects,
        )

    def post(
        self,
        url: str,
        *,
        body: bytes | str | None = None,
        json: object | None = None,
        headers: object | None = None,
        timeout_ms: int | None = None,
        max_redirects: int | None = None,
    ) -> "RequestHandle":
        """Issue a POST request; return a :class:`RequestHandle`.

        Pass exactly one of *body* or *json*.  *json* auto-encodes via
        :func:`json.dumps` and sets ``Content-Type: application/json``
        unless the caller overrides it via *headers*.  *body* as ``str``
        is encoded UTF-8.

        Args:
            url: Absolute URL — ``http://...`` or ``https://...``.
            body: Raw request body — ``bytes`` (passed verbatim) or
                ``str`` (encoded UTF-8).
            json: Python object to serialize as the JSON body.
                Mutually exclusive with *body*.
            headers: Optional header overrides.  Same shape as
                :meth:`get`.  ``Content-Length`` is auto-added.
            timeout_ms: Per-request timeout override.

        Raises:
            HttpBusyError: A request is already in flight.
            HttpURLError: *url* didn't parse as a valid HTTP URL.
            ValueError: Both *body* and *json* supplied.
        """
        return self._start_request(
            "POST", url,
            body=body, json_body=json,
            headers=headers, timeout_ms=timeout_ms,
            max_redirects=max_redirects,
        )

    def put(
        self,
        url: str,
        *,
        body: bytes | str | None = None,
        json: object | None = None,
        headers: object | None = None,
        timeout_ms: int | None = None,
        max_redirects: int | None = None,
    ) -> "RequestHandle":
        """Issue a PUT request.  Same body / json semantics as :meth:`post`."""
        return self._start_request(
            "PUT", url,
            body=body, json_body=json,
            headers=headers, timeout_ms=timeout_ms,
            max_redirects=max_redirects,
        )

    def patch(
        self,
        url: str,
        *,
        body: bytes | str | None = None,
        json: object | None = None,
        headers: object | None = None,
        timeout_ms: int | None = None,
        max_redirects: int | None = None,
    ) -> "RequestHandle":
        """Issue a PATCH request.  Same body / json semantics as :meth:`post`."""
        return self._start_request(
            "PATCH", url,
            body=body, json_body=json,
            headers=headers, timeout_ms=timeout_ms,
            max_redirects=max_redirects,
        )

    def delete(
        self,
        url: str,
        *,
        headers: object | None = None,
        timeout_ms: int | None = None,
        max_redirects: int | None = None,
    ) -> "RequestHandle":
        """Issue a DELETE request.  No body — the verb is intransitive in v1."""
        return self._start_request(
            "DELETE", url, headers=headers, timeout_ms=timeout_ms,
            max_redirects=max_redirects,
        )

    # ------------------------------------------------------------------
    # Runner contract — Decision 0014
    # ------------------------------------------------------------------

    def check(self, now_ms):  # noqa: ARG002 — runner contract uses now_ms
        """Return ``True`` if there's outbound bytes to send or readable bytes."""
        return self._state != _RequestState.IDLE

    def handle(self, now_ms):
        """One tick of progress on the in-flight request.

        Sends queued request bytes, drains inbound bytes (up to
        ``recv_budget_per_tick``), feeds the parser, and finishes
        the handle when the response is complete.

        Per-request ``timeout_ms`` is checked at the top of each tick.
        On expiry the request fails with :class:`HttpTimeoutError`
        and the socket is closed.
        """
        if self._state == _RequestState.IDLE:
            return

        if self._deadline_ticks is not None and self._ticks_diff(
            self._deadline_ticks, now_ms,
        ) <= 0:
            self._fail(HttpTimeoutError(
                f"request to {self._url!r} timed out after deadline",
            ))
            return

        try:
            if self._state == _RequestState.SENDING:
                self._drive_send()
            if self._state == _RequestState.RECEIVING:
                self._drive_recv()
        except HttpError as protocol_error:
            self._fail(protocol_error)
        except OSError as socket_error:
            self._fail(HttpError(f"socket error: {socket_error}"))

    # ------------------------------------------------------------------
    # Internal — request lifecycle
    # ------------------------------------------------------------------

    def _start_request(
        self, method, url, *, headers, timeout_ms,
        body=None, json_body=None, max_redirects=None,
    ):
        """Common path for GET / POST / PUT / PATCH / DELETE."""
        if self._state != _RequestState.IDLE:
            raise HttpBusyError(
                f"client busy on {self._url!r}; await handle.done before issuing another",
            )
        if body is not None and json_body is not None:
            raise ValueError(
                "pass body= or json= but not both",
            )
        encoded_body = _encode_body(body, json_body)
        # Capture the user's request shape for 307/308 redirect replay
        # — we need method + body + headers + the json-default-content-
        # type flag to rebuild the on-the-wire bytes for the next hop.
        self._original_url = url
        self._original_method = method
        self._original_headers = headers
        self._original_body = encoded_body
        self._original_json_body = json_body
        self._redirects_remaining = (
            max_redirects if max_redirects is not None else self._default_max_redirects
        )
        timeout = timeout_ms if timeout_ms is not None else self._default_timeout_ms
        self._deadline_ticks = self._ticks_add(self._ticks_ms(), timeout)
        self._handle = RequestHandle(url=url)
        self._start_hop(url, method, encoded_body, headers, json_body is not None)
        return self._handle

    def _start_hop(
        self, url, method, encoded_body, user_headers, json_default_content_type,
    ):
        """Open a socket and queue the request bytes for *url*.

        Reused by both first-issue and redirect-follow paths.  The
        per-request handle, deadline, and redirect budget are *not*
        reset here — they belong to the request as a whole, not to
        any one hop.
        """
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
        self._socket = self._connection_factory(host, port, use_tls)
        _force_non_blocking(self._socket)
        self._url = url
        self._tx_buffer = request_bytes
        self._tx_offset = 0
        # Per-request parser, but we hand it the long-lived body buffer
        # so per-request body alloc only happens for oversize responses.
        self._parser = ResponseParser(
            max_body_bytes=self._max_body_bytes,
            body_buffer=self._body_buffer,
            body_buffer_view=self._body_buffer_view,
        )
        self._state = _RequestState.SENDING

    def _drive_send(self):
        """Push queued request bytes onto the socket; transition on completion."""
        while self._tx_offset < len(self._tx_buffer):
            view = memoryview(self._tx_buffer)[self._tx_offset:]
            sent = self._send_raw(view)
            if sent <= 0:
                return  # Socket would block — wait for next tick.
            self._tx_offset += sent
        self._state = _RequestState.RECEIVING

    def _send_raw(self, payload):
        """Send *payload*; return bytes sent (may be 0 on EAGAIN)."""
        try:
            return self._socket.send(payload)
        except OSError as socket_error:
            errno = socket_error.args[0] if socket_error.args else None
            if errno in (11, 35):  # EAGAIN
                return 0
            raise

    def _drive_recv(self):
        """Drain the socket up to ``recv_budget_per_tick``; feed the parser.

        Recv goes into the pre-allocated :attr:`_recv_buffer`; the
        :meth:`ResponseParser.feed` call gets a ``memoryview`` window into
        that buffer so neither the recv nor the feed allocates per tick.
        The parser copies the bytes it keeps (into ``_buffer`` or ``_body``)
        before returning, so the memoryview's lifetime ends with the call.
        """
        consumed = 0
        budget = self._recv_budget_per_tick
        scratch_size = len(self._recv_buffer)
        while consumed < budget and self._parser.state not in (
            ParseState.DONE, ParseState.ERROR,
        ):
            capacity = min(scratch_size, budget - consumed)
            try:
                got = self._socket.recv_into(self._recv_view[:capacity], capacity)
            except OSError as socket_error:
                errno = socket_error.args[0] if socket_error.args else None
                if errno in (11, 35):  # EAGAIN
                    return
                raise
            if got == 0:
                # Peer close — feed_eof so the parser can decide if
                # this is end-of-body (length-unknown) or a protocol
                # error (Content-Length short).
                self._parser.feed_eof()
                break
            self._parser.feed(self._recv_view[:got])
            consumed += got
        if self._parser.state == ParseState.ERROR:
            raise self._parser.error
        if self._parser.state == ParseState.DONE:
            self._complete()

    def _complete(self):
        """Build the :class:`Response`; either follow a redirect or attach to handle."""
        body = self._parser.body
        oversized_dropped = False
        # The DROP_SILENT / DROP_WITH_EVENT branches don't use
        # HttpOversizedError; they would have arrived here only if
        # the parser stayed under the cap.  Keep the hook for the
        # next slice that makes oversize a runtime-not-parse decision.
        response = Response(
            status_code=self._parser.status_code,
            reason=self._parser.reason,
            http_version=self._parser.http_version,
            headers=self._parser.headers,
            body=body,
            url=self._url,
            oversized_dropped=oversized_dropped,
        )
        if self._should_follow_redirect(response):
            self._follow_redirect(response)
            return
        self._handle._set_response(response)  # noqa: SLF001 — internal handoff
        self._reset_socket()

    def _should_follow_redirect(self, response):
        """Return True iff the response is a 3xx with a Location header
        and the per-request redirect budget is non-zero."""
        if self._redirects_remaining <= 0:
            return False
        if response.status_code not in REDIRECT_STATUS_CODES:
            return False
        return response.headers.get("Location") is not None

    def _follow_redirect(self, response):
        """Resolve the next URL, swap state, and re-issue the request.

        For 301 / 302 / 303 the next hop is always GET with no body —
        matches long-standing browser + RFC 7231 §6.4 guidance.  For
        307 / 308 the original method + body are preserved.
        """
        try:
            new_url = resolve_redirect_url(
                self._url, response.headers["Location"],
            )
        except HttpError as redirect_error:
            self._handle._set_error(redirect_error)  # noqa: SLF001
            self._reset_socket()
            return
        if response.status_code in METHOD_PRESERVING_REDIRECT_STATUS_CODES:
            next_method = self._original_method
            next_body = self._original_body
            next_json_default_content_type = self._original_json_body is not None
        else:
            # 301 / 302 / 303 — drop body, switch to GET.
            next_method = "GET"
            next_body = None
            next_json_default_content_type = False
        # Tear down the current socket but keep the handle + deadline +
        # original-request capture in place — the request as a whole
        # is still in flight.
        self._close_socket_only()
        self._redirects_remaining -= 1
        try:
            self._start_hop(
                new_url, next_method, next_body,
                self._original_headers, next_json_default_content_type,
            )
        except OSError as factory_error:
            self._handle._set_error(  # noqa: SLF001
                HttpError(f"socket factory failed during redirect: {factory_error}"),
            )
            self._reset_socket()
        except HttpError as redirect_error:
            self._handle._set_error(redirect_error)  # noqa: SLF001
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
                self.on_oversized(self._url, error)
                self._complete_oversized_drop()
                return
            # DISCONNECT — fall through to fail path.
        if self._handle is not None:
            self._handle._set_error(error)  # noqa: SLF001 — internal handoff
        self._reset_socket()

    def _complete_oversized_drop(self):
        """Finish the request as a drop: empty body, oversized_dropped=True."""
        response = Response(
            status_code=self._parser.status_code,
            reason=self._parser.reason,
            http_version=self._parser.http_version,
            headers=self._parser.headers,
            body=b"",
            url=self._url,
            oversized_dropped=True,
        )
        self._handle._set_response(response)  # noqa: SLF001 — internal handoff
        self._reset_socket()

    def _close_socket_only(self):
        """Close the socket but leave the handle + deadline + redirect
        bookkeeping intact.  Used between redirect hops where the
        request as a whole is still in flight."""
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:  # pragma: no cover — defensive
                pass
        self._socket = None
        self._tx_buffer = b""
        self._tx_offset = 0
        # Drop the parser instance — the long-lived body buffer it was
        # using stays alive on ``self._body_buffer`` and gets handed to
        # the next request's parser.  Only the small parser scaffolding
        # (cursor, headers dict, etc.) is freed here.
        self._parser = None
        self._state = _RequestState.IDLE  # Brief — _start_hop flips back.

    def _reset_socket(self):
        """Close the socket best-effort and clear all per-request state."""
        self._close_socket_only()
        self._handle = None
        self._url = None
        self._original_url = None
        self._original_method = None
        self._original_headers = None
        self._original_body = None
        self._original_json_body = None
        self._deadline_ticks = None
        self._redirects_remaining = 0


# ---------------------------------------------------------------------------
# chumicro-sockets convenience factory
# ---------------------------------------------------------------------------


def chumicro_sockets_factory(*, radio=None, ssl_context=None):
    """Return a connection factory wired to :mod:`chumicro_sockets`.

    The returned callable matches the
    ``connection_factory(host, port, use_tls) -> TCPClientSocket``
    signature :class:`HttpClient` expects.  Plain TCP routes to
    :func:`chumicro_sockets.tcp_client_socket`; TLS routes to
    :func:`chumicro_sockets.tls_client_socket` with the supplied
    *ssl_context* (or the runtime default when omitted).

    *radio* defaults to ``wifi.radio`` on CircuitPython (auto-detected);
    ignored on MicroPython and CPython.  Pass explicitly for multi-radio
    prototypes or boards without a ``wifi`` module.

    Lazy-imports :mod:`chumicro_sockets` so the requests library
    can be unit-tested with a hand-rolled factory + ``FakeSocket``
    without pulling the transport into the test path.
    """
    def factory(host, port, use_tls):
        from chumicro_sockets import (  # noqa: PLC0415 — lazy
            tcp_client_socket,
            tls_client_socket,
        )

        if use_tls:
            return tls_client_socket(host, port, context=ssl_context, radio=radio)
        return tcp_client_socket(host, port, radio=radio)

    return factory
