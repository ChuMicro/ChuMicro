"""HTTP/1.1 client built on chumicro-sockets + chumicro-timing.

:class:`HttpClient` is the entry point.  Runner-shaped —
:meth:`check(now_ms) -> bool` reports whether work is pending;
:meth:`handle(now_ms)` performs one tick of progress.  No threads,
no async — cooperative dispatch in the caller's tick loop.

Single-in-flight in v1: :meth:`HttpClient.get` / ``post`` / etc.
while a request is still running raises :class:`HttpBusyError`.  The
user pattern::

    client = HttpClient(connector_factory=...)
    handle = client.get("http://api.example.com/now", timeout_ms=5000)

    while not handle.done:
        if client.check(now_ms()):
            client.handle(now_ms())

    response = handle.result   # raises on failure

This module ships GET / POST / PUT / PATCH / DELETE over HTTP and
HTTPS (an ``https://`` URL selects TLS), JSON request bodies via
``json=...``, automatic 3xx redirect following (capped, and
method-preserving where the status requires it), and response
bodies via ``Content-Length``, ``Transfer-Encoding: chunked``, or
read-until-close.
"""

import errno
import json

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

# EWOULDBLOCK is absent from MicroPython's errno; fall back to EAGAIN
# (they're the same value on the platforms that define both).
_EWOULDBLOCK = getattr(errno, "EWOULDBLOCK", errno.EAGAIN)


def _is_would_block(socket_error):
    """Return whether *socket_error* means "no progress yet, retry later".

    A non-blocking plain socket raises ``OSError(EAGAIN | EWOULDBLOCK)``.
    A non-blocking ``ssl.SSLSocket`` on CPython instead raises
    ``SSLWantReadError`` / ``SSLWantWriteError`` (``OSError`` subclasses
    whose ``errno`` is ``SSL_ERROR_WANT_READ`` / ``WANT_WRITE``, not
    EAGAIN), so treating only EAGAIN as would-block turned every HTTPS
    request into a fatal error.  Matched by exception-class name to stay
    dependency-free across runtimes (the MicroPython / CircuitPython TLS
    adapters already normalize to EAGAIN, so the name never matches
    there).
    """
    if socket_error.errno in (errno.EAGAIN, _EWOULDBLOCK):
        return True
    return type(socket_error).__name__ in (
        "SSLWantReadError",
        "SSLWantWriteError",
    )


# ---------------------------------------------------------------------------
# WhenOversized policy
# ---------------------------------------------------------------------------


class WhenOversized:
    """Policy for response bodies exceeding ``max_body_bytes``."""

    #: Drop the body silently.  The request finishes as ``done`` with
    #: an empty body and the headers intact — useful when callers only
    #: care about the status code (e.g. liveness checks).
    DROP_SILENT = "drop_silent"

    #: Default.  Drop the body, fire ``client.on_oversized(reported_length,
    #: url)`` if set, otherwise behave like :data:`DROP_SILENT`.
    DROP_WITH_EVENT = "drop_with_event"

    #: Fail the request with :class:`HttpOversizedError`.  Use when
    #: the application can't tolerate truncated payloads.
    DISCONNECT = "disconnect"


def _encode_body(body, json_body):
    """Convert *body* / *json_body* into ``bytes`` (or ``None``).

    At most one of *body* / *json_body* is non-None (caller validates).
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
    pairs.  Lets a default like ``Content-Type: application/json``
    apply only when the caller hasn't supplied that header.
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

    The tick-based RX path expects ``recv_into`` to raise EAGAIN when
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

    Body decoding:

    * :attr:`encoding` — charset sniffed from ``Content-Type``,
      defaulting to ``"utf-8"``.  Settable so callers can override
      a wrong / missing server hint.
    * :attr:`text` — body decoded as a ``str`` using :attr:`encoding`.
    * :meth:`json` — body parsed as JSON into Python objects.
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

    Returned from :meth:`HttpClient.get`.  Two ways to read the
    outcome:

    * Poll :attr:`done`; when ``True``, :attr:`result` returns the
      :class:`Response` (or raises the :class:`HttpError` that killed
      the request).  :attr:`error` is the same exception, returned
      instead of raised — useful when the caller wants to branch
      rather than catch.
    * Pass ``on_done=`` to the request call.  The client invokes that
      callback with this handle when the request finishes, success or
      failure, so the response handling stays bound to the request
      that produced it instead of polling a shared slot.  The callback
      fires after the client returns to idle, so it may issue the next
      request directly.

    :attr:`url` records the requested URL (the original one, not the
    final redirect target), so a completion callback can tell which
    request it's handling.
    """

    def __init__(self, *, url, on_done=None):
        self.url = url
        self.done = False
        self.response = None
        self.error = None
        self._on_done = on_done

    def _invoke_done(self):
        """Fire the completion callback, if one was registered.

        Called by the client once the request has finished and all
        per-request state has been cleared, so a callback that issues
        a follow-up request sees an idle client.
        """
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
        """Internal: client calls this on success."""
        self.response = response
        self.done = True

    def _set_error(self, error):
        """Internal: client calls this on failure."""
        self.error = error
        self.done = True


# ---------------------------------------------------------------------------
# HttpClient — runner-shaped, single-in-flight
# ---------------------------------------------------------------------------


class _RequestState:
    """Internal request-pipeline states.

    Lifecycle for one in-flight request::

        IDLE -> AWAITING_TRANSPORT -> SENDING -> RECEIVING -> IDLE

    ``AWAITING_TRANSPORT`` is the phase during which the connector
    object returned by *connector_factory* is driving DNS / TCP / TLS
    across multiple ticks.  On ``ready`` the socket is promoted and the
    state moves to ``SENDING``.  On ``failed`` the handle is set to
    error and the state returns to ``IDLE``.
    """

    IDLE = "idle"
    AWAITING_TRANSPORT = "awaiting_transport"
    SENDING = "sending"
    RECEIVING = "receiving"


class HttpClient:
    """Non-blocking HTTP/1.1 client.

    Construct with a *connector_factory* callable; then issue requests
    via :meth:`get` and drive via :meth:`check` / :meth:`handle` from a
    runner tick or hand-rolled loop.

    The factory signature is::

        connector_factory(host: str, port: int, use_tls: bool) -> connector

    The returned *connector* is a structural type: an object with
    ``state`` / ``socket`` / ``last_error`` attributes, ``tick(now_ms)``
    / ``cancel()`` methods, and the runner-poll surface ``io_socket`` /
    ``io_wants_read`` / ``io_wants_write`` / ``next_deadline(now_ms)``.
    Any object of that shape works — the client never imports a specific
    class.

    For a board with WiFi + chumicro-sockets, use
    :func:`chumicro_requests.sockets_factory.chumicro_sockets_connector_factory`
    to wire up the default::

        from chumicro_requests import HttpClient
        from chumicro_requests.sockets_factory import (
            chumicro_sockets_connector_factory,
        )
        client = HttpClient(
            connector_factory=chumicro_sockets_connector_factory(),
        )

    The connector advances the TCP connect across ticks; the DNS lookup
    and, on MicroPython / CircuitPython, the TLS handshake block the
    runner for their duration.

    For config-driven construction, see :meth:`from_config` —
    one-line factory that reads the per-call defaults
    (``requests.default_timeout_ms``, ``requests.user_agent``,
    etc.) from ``runtime_config.msgpack``.
    """

    @classmethod
    def from_config(
        cls,
        config: object,
        *,
        radio: object | None = None,
        ssl_context: object | None = None,
        connector_factory: object | None = None,
    ) -> "HttpClient":
        """Build an :class:`HttpClient` from runtime config.

        Reads the ``[tool.chumicro.config]`` keys — all optional with
        sensible defaults:

        * ``requests.default_timeout_ms`` defaults to
          :data:`DEFAULT_TIMEOUT_MS` (10 000 ms).
        * ``requests.default_max_redirects`` defaults to
          :data:`DEFAULT_MAX_REDIRECTS` (5).
        * ``requests.user_agent`` defaults to the built-in
          ``"chumicro-requests/0.1"``.
        * ``requests.max_body_bytes`` defaults to
          :data:`DEFAULT_MAX_BODY_BYTES`.

        No key is required; empty ``config`` is valid input.  When
        *connector_factory* is supplied, the caller owns the
        connection-opening behavior and *radio* / *ssl_context* are
        ignored.  Otherwise an auto-built factory wires through
        :func:`chumicro_sockets_connector_factory` using *radio* /
        *ssl_context*.
        """
        if connector_factory is None:
            try:
                from chumicro_requests.sockets_factory import (  # noqa: PLC0415 - lazy
                    chumicro_sockets_connector_factory,
                )
            except ImportError as exception:
                raise RuntimeError(
                    "chumicro_requests.sockets_factory not available "
                    "(excluded via __chumicro_skip_factories__ or "
                    "not on the board) — pass connector_factory= "
                    "explicitly.",
                ) from exception

            connector_factory = chumicro_sockets_connector_factory(
                radio=radio, ssl_context=ssl_context,
            )
        return cls(
            connector_factory=connector_factory,
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
        connector_factory: object,
        recv_budget_per_tick: int = DEFAULT_RECV_BUDGET_PER_TICK,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        when_oversized: str = WhenOversized.DROP_WITH_EVENT,
        default_timeout_ms: int = DEFAULT_TIMEOUT_MS,
        default_max_redirects: int = DEFAULT_MAX_REDIRECTS,
        user_agent: str | None = None,
        ticks: object | None = None,
    ) -> None:
        """Wire up the client.

        Args:
            connector_factory: Callable ``(host: str, port: int,
                use_tls: bool) -> connector`` invoked per request hop
                to bring up the underlying socket without blocking the
                runner.  The connector is a duck-typed object — see
                the class docstring for the structural contract.  It
                is ticked across multiple ``handle()`` calls during
                ``AWAITING_TRANSPORT``; once
                ``connector.state == "ready"`` the underlying socket is
                promoted and must expose:

                * ``recv_into(buffer: memoryview, nbytes: int) -> int``
                  — raises ``OSError(EAGAIN | EWOULDBLOCK)`` on no
                  data, returns 0 on peer-close, otherwise bytes
                  written.
                * ``send(payload: bytes) -> int`` — raises
                  ``OSError(EAGAIN | EWOULDBLOCK)`` when the send
                  buffer is full, otherwise bytes sent (may be
                  partial).
                * ``close() -> None``
                * ``setblocking(flag: bool) -> None`` — best-effort;
                  absence is tolerated.

                :func:`chumicro_sockets_connector_factory` is one
                valid producer; any zero-network-side fake or wrapper
                returning a connector-shaped object works too.
            recv_budget_per_tick: Soft cap on bytes drained from the
                socket in a single :meth:`handle` call.  Default 1024.
                The recv scratch is 512 B, so against a fast peer a
                larger budget drains in up to ``budget // 512``
                recv-and-feed iterations per tick — raising it trades
                tick latency for throughput.  Keep it small (a few
                hundred bytes to a couple KB) so concurrent runner tasks
                (LED blink, control loop) keep getting CPU time within
                the per-tick budget.
            max_body_bytes: Cap on a single response body.  Default
                64 KB — minimum supported board has 256 KB MCU RAM,
                so 64 KB leaves headroom.
            when_oversized: Policy for responses above the cap.  See
                :class:`WhenOversized`.
            default_timeout_ms: Default per-request timeout in ms.
                Overridable per-call via ``timeout_ms=...``.  Default
                10 000 ms.
            default_max_redirects: Default cap on 3xx hops the client
                follows.  When the budget is exhausted the last 3xx
                response is returned as-is (not an ``HttpError``), same
                as ``max_redirects=0``.  Overridable per-call via
                ``max_redirects=...``.
                ``0`` returns the 3xx response as-is without
                following.  Default 5.
            user_agent: Override the default ``User-Agent`` header.
            ticks: Optional tick source — any object exposing
                ``ticks_ms``, ``ticks_diff``, ``ticks_add`` (matches
                the ``chumicro_timing.ticks`` submodule shape).
                Defaults to that submodule (real clock); tests pass
                ``FakeTicks`` from ``chumicro_timing.testing``.
        """
        self._connector_factory = connector_factory
        self._connector = None
        self._recv_budget_per_tick = recv_budget_per_tick
        # Pre-allocated recv scratch reused on every tick — _drive_recv
        # passes a memoryview into this buffer to socket.recv_into
        # instead of allocating per call.  Capped at 512 B so a
        # generous recv_budget_per_tick (say 64K) doesn't pin a 64K
        # resident buffer for what's only ever a sliced-down working
        # window.
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
        self.url = None
        self._tx_buffer = b""  # request bytes pending send
        self._tx_offset = 0
        self._parser = None
        # Long-lived body buffer reused across requests.  The parser
        # is constructed fresh per request, but the body buffer is
        # the largest per-request alloc; holding it on the client
        # and passing it to each new parser means a per-request body
        # allocation happens only when the response would exceed
        # body_buffer_size.
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

        ``Runner.wait`` registers this object with ``select.poll``.
        While in ``AWAITING_TRANSPORT`` this forwards to the
        connector's in-flight pollable so the runner parks on the
        right handle between connect phases.  Once promoted, adapter
        wrappers from ``chumicro_sockets`` store the underlying
        pollable on ``.sock``; bare CPython sockets and CircuitPython
        TCP / TLS clients pass through unchanged.
        """
        if self._state == _RequestState.AWAITING_TRANSPORT:
            return self._connector.io_socket if self._connector is not None else None
        sock = self._socket
        if sock is None:
            return None
        return getattr(sock, "sock", sock)

    @property
    def io_wants_read(self):
        """``True`` while waiting on response bytes from the server (or
        TLS-handshake inbound during connect)."""
        if self._state == _RequestState.AWAITING_TRANSPORT:
            return self._connector.io_wants_read if self._connector is not None else False
        return self._state == _RequestState.RECEIVING

    @property
    def io_wants_write(self):
        """``True`` while there are request bytes still to send (or a
        TCP / TLS handshake phase needs writability)."""
        if self._state == _RequestState.AWAITING_TRANSPORT:
            return self._connector.io_wants_write if self._connector is not None else False
        return self._state == _RequestState.SENDING

    def next_deadline(self, now_ms):
        """Return the per-request timeout deadline, or ``None`` when idle.

        Lets ``Runner.wait`` shorten its central poll so the loop wakes
        for timeout enforcement even on a quiescent socket.  *now_ms*
        is the runner's tick and is accepted for the contract; the
        deadline is an absolute tick captured at request start.

        While ``AWAITING_TRANSPORT`` with no pollable yet (the connector
        is still resolving DNS, so ``io_socket`` is ``None`` and
        ``Runner.wait`` has nothing to park on), this returns *now_ms* —
        an immediate deadline that keeps the loop ticking the
        tick-driven connector forward instead of sleeping toward the far
        request deadline.  Once a pollable exists (TCP-connect onward) or
        the connect phase ends, the per-request budget governs again and
        still times out a stuck handshake.
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

    def get(
        self,
        url: str,
        *,
        headers: CaseInsensitiveDict | dict | list | tuple | None = None,
        timeout_ms: int | None = None,
        max_redirects: int | None = None,
        on_done: object | None = None,
    ) -> "RequestHandle":
        """Issue a GET request; return a :class:`RequestHandle`.

        Poll ``handle.done``, then read ``handle.result`` for the
        :class:`Response`.  Alternatively pass ``on_done=callback`` to
        have the client call ``callback(handle)`` when the request
        finishes (see :class:`RequestHandle`).  ``max_redirects=0``
        returns a 3xx as-is.  Raises :class:`HttpBusyError` if a request
        is already in flight, :class:`HttpURLError` if *url* doesn't parse.
        """
        return self._start_request(
            "GET", url, headers=headers, timeout_ms=timeout_ms,
            max_redirects=max_redirects, on_done=on_done,
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
    ) -> "RequestHandle":
        """Issue a POST request; return a :class:`RequestHandle`.

        Pass exactly one of *body* or *json*.  *json* auto-encodes via
        :func:`json.dumps` and sets ``Content-Type: application/json``
        unless the caller overrides it via *headers*.  *body* as ``str``
        is encoded UTF-8.  ``Content-Length`` is auto-added.  Passing
        both *body* and *json* raises ``ValueError``.  ``on_done`` is the
        optional completion callback (see :class:`RequestHandle`).
        """
        return self._start_request(
            "POST", url,
            body=body, json_body=json,
            headers=headers, timeout_ms=timeout_ms,
            max_redirects=max_redirects, on_done=on_done,
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
    ) -> "RequestHandle":
        """Issue a PUT request.  Same body / json semantics as :meth:`post`."""
        return self._start_request(
            "PUT", url,
            body=body, json_body=json,
            headers=headers, timeout_ms=timeout_ms,
            max_redirects=max_redirects, on_done=on_done,
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
    ) -> "RequestHandle":
        """Issue a PATCH request.  Same body / json semantics as :meth:`post`."""
        return self._start_request(
            "PATCH", url,
            body=body, json_body=json,
            headers=headers, timeout_ms=timeout_ms,
            max_redirects=max_redirects, on_done=on_done,
        )

    def delete(
        self,
        url: str,
        *,
        headers: CaseInsensitiveDict | dict | list | tuple | None = None,
        timeout_ms: int | None = None,
        max_redirects: int | None = None,
        on_done: object | None = None,
    ) -> "RequestHandle":
        """Issue a DELETE request.  No body — the verb is intransitive in v1."""
        return self._start_request(
            "DELETE", url, headers=headers, timeout_ms=timeout_ms,
            max_redirects=max_redirects, on_done=on_done,
        )

    # ------------------------------------------------------------------
    # Runner contract
    # ------------------------------------------------------------------

    def check(self, now_ms):  # noqa: ARG002 - runner contract uses now_ms
        """Return ``True`` if there's outbound bytes to send or readable bytes."""
        return self._state != _RequestState.IDLE

    def handle(self, now_ms):
        """One tick of progress on the in-flight request.

        Advances the connector while ``AWAITING_TRANSPORT``, sends
        queued request bytes, drains inbound bytes (up to
        ``recv_budget_per_tick``), feeds the parser, and finishes the
        handle when the response is complete.

        Per-request ``timeout_ms`` is checked at the top of each tick
        and applies during ``AWAITING_TRANSPORT`` too — a stuck
        handshake fails the same way a stuck recv would.  On expiry
        the request fails with :class:`HttpTimeoutError` and the
        socket / connector is closed.
        """
        if self._state == _RequestState.IDLE:
            return

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
                # Connector reached ``ready`` — fall through and start sending.
            if self._state == _RequestState.SENDING:
                self._drive_send()
            if self._state == _RequestState.RECEIVING:
                self._drive_recv()
        except HttpError as protocol_error:
            self._fail(protocol_error)
        except OSError as socket_error:
            self._fail(HttpError(f"socket error: {socket_error}"))

    def _advance_connector(self, now_ms):
        """Tick the in-flight connector one phase; promote socket when ``ready``.

        Returns ``True`` when the connector reached ``ready`` this tick
        — in which case the socket is promoted to ``self._socket``,
        forced non-blocking, and the state moves to ``SENDING``.
        Returns ``False`` when the connector is still in flight (state
        unchanged) or has failed (state is now ``IDLE`` with the
        handle marked errored).
        """
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
    # Internal — request lifecycle
    # ------------------------------------------------------------------

    def _start_request(
        self, method, url, *, headers, timeout_ms,
        body=None, json_body=None, max_redirects=None, on_done=None,
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
        # Capture the user's request shape for 307/308 redirect replay
        # — we need method + body + headers + the json-default-content-
        # type flag to rebuild the on-the-wire bytes for the next hop.
        self._original_method = method
        self._original_headers = headers
        self._original_body = encoded_body
        self._original_json_body = json_body
        self._redirects_remaining = (
            max_redirects if max_redirects is not None else self._default_max_redirects
        )
        timeout = timeout_ms if timeout_ms is not None else self._default_timeout_ms
        self._deadline_ticks = self._ticks.ticks_add(self._ticks.ticks_ms(), timeout)
        self._handle = RequestHandle(url=url, on_done=on_done)
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
        self._connector = self._connector_factory(host, port, use_tls)
        self.url = url
        self._tx_buffer = request_bytes
        self._tx_offset = 0
        # Per-request parser, but we hand it the long-lived body buffer
        # so per-request body alloc only happens for oversize responses.
        self._parser = ResponseParser(
            max_body_bytes=self._max_body_bytes,
            body_buffer=self._body_buffer,
            body_buffer_view=self._body_buffer_view,
        )
        # Defer the SENDING transition until the connector reaches
        # ``ready`` inside :meth:`_advance_connector`; until then the
        # tick path stays in AWAITING_TRANSPORT and yields between
        # connect phases.
        self._state = _RequestState.AWAITING_TRANSPORT

    def _drive_send(self):
        """Push queued request bytes onto the socket; transition on completion."""
        # Bind the buffer view once, not per iteration: a backpressured
        # send loops here, and rebuilding memoryview(self._tx_buffer) each
        # pass allocates a fresh base view every time.
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
                return  # Socket would block — wait for next tick.
            self._tx_offset += sent
        self._state = _RequestState.RECEIVING

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
                got = self._socket.recv_into(self._recv_view, capacity)
            except OSError as socket_error:
                if _is_would_block(socket_error):
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
        """Follow a redirect or hand the response to the handle.

        Checks the redirect path against the parser directly so the
        body-snapshot (``bytes(memoryview)`` inside ``parser.body``)
        only fires when we're about to return the response.
        """
        parser = self._parser
        status_code = parser.status_code
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
        """Resolve the next URL, swap state, and re-issue the request.

        For 301 / 302 / 303 the next hop is always GET with no body —
        matches long-standing browser + RFC 7231 §6.4 guidance.  For
        307 / 308 the original method + body are preserved.
        """
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
                HttpError(f"connector factory failed during redirect: {factory_error}"),
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
                self.on_oversized(error.reported_length, self.url)
                self._complete_oversized_drop()
                return
            # DISCONNECT — fall through to fail path.
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
        """Close the socket / connector but leave the handle + deadline
        + redirect bookkeeping intact.  Used between redirect hops
        where the request as a whole is still in flight."""
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
        # Drop the parser instance — the long-lived body buffer it was
        # using stays alive on ``self._body_buffer`` and gets handed to
        # the next request's parser.  Only the small parser scaffolding
        # (cursor, headers dict, etc.) is freed here.
        self._parser = None
        self._state = _RequestState.IDLE  # Brief — _start_hop flips back.

    def _reset_socket(self):
        """Close the socket best-effort and clear all per-request state.

        Fires the finished handle's completion callback last, after the
        client is fully idle, so a callback that issues the next request
        doesn't trip :class:`HttpBusyError`.
        """
        self._close_socket_only()
        finished_handle = self._handle
        self._handle = None
        self.url = None
        self._original_method = None
        self._original_headers = None
        self._original_body = None
        self._original_json_body = None
        self._deadline_ticks = None
        self._redirects_remaining = 0
        if finished_handle is not None:
            finished_handle._invoke_done()  # noqa: SLF001 - internal handoff
