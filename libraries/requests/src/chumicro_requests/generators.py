"""One-shot HTTP fetch and streamed-body reads as generators.

Opt-in submodule — import explicitly::

    from chumicro_requests.generators import fetch, get, post, stream

A fetch is one request/response written top-to-bottom; the caller
delegates to it and receives the :class:`~chumicro_requests.client.Response`::

    def app(transport_factory):
        response = yield from get(transport_factory, "http://example.com/")
        print(response.status_code, response.json())

    handle = runner.add_generator(app(transport_factory))

:func:`stream` is the same lifecycle for a body too large to buffer —
it returns a :class:`BodyReader` once the response headers are in, and
the caller pulls the body chunk by chunk into its own buffer::

    def download(transport_factory, url, sink):
        reader = yield from stream(transport_factory, "GET", url,
                                   timeout_ms=120_000)
        buffer = bytearray(512)
        view = memoryview(buffer)
        while True:
            count = yield from reader.read_into(view)
            if count == 0:
                break
            sink(view[:count])

Both surfaces are thin adapters over :class:`HttpClient`: each call
builds a client for the injected ``transport_factory``, issues the
request, and yields the client itself as the scheduler wait token — an
``HttpClient`` already exposes the duck-typed wait surface
(``io_socket`` / ``io_interest(now_ms)`` / ``next_deadline(now_ms)``),
so the runner parks on the request's socket and wakes for its deadline
exactly as it would for the client registered as a service.  Every
resume threads the runner's ``now_ms`` into ``client.handle(now_ms)``.

Unlike a long-lived ``HttpClient`` these allocate their buffers per
call; they are for one-shot work, not a hot request loop.  Use
``HttpClient`` directly when you issue many requests from one client
and want the body buffer reused.
"""

from chumicro_requests._wire import (
    DEFAULT_MAX_BODY_BYTES,
    DEFAULT_STREAM_BUFFER_SIZE,
    DEFAULT_TIMEOUT_MS,
)
from chumicro_requests.client import HttpClient, WhenOversized


def _issue(
    transport_factory, method, url, *,
    headers, body, json, max_redirects, timeout_ms, user_agent, ticks,
    stream=False, max_body_bytes=DEFAULT_MAX_BODY_BYTES,
    stream_buffer_size=DEFAULT_STREAM_BUFFER_SIZE,
):
    """Build a per-call :class:`HttpClient` and start the request.

    Returns ``(client, handle, now_ms)`` — *now_ms* is the tick the
    request started at, the value the caller drives the first
    ``client.handle`` with before its first yield.  Oversize policy is
    pinned to ``DISCONNECT`` so a too-big buffered body raises
    :class:`HttpOversizedError` instead of completing empty (a
    generator caller has no oversize event hook to observe a drop).
    """
    if ticks is None:
        from chumicro_timing import ticks  # noqa: PLC0415 - DI fallback, like HttpClient
    client = HttpClient(
        transport_factory=transport_factory,
        max_body_bytes=max_body_bytes,
        when_oversized=WhenOversized.DISCONNECT,
        default_timeout_ms=timeout_ms,
        stream_buffer_size=stream_buffer_size,
        user_agent=user_agent,
        ticks=ticks,
    )
    handle = client.request(
        method, url,
        headers=headers, body=body, json=json,
        max_redirects=max_redirects, stream=stream,
    )
    return client, handle, ticks.ticks_ms()


class BodyReader:
    """Streamed-body pull surface returned by :func:`stream`.

    ``response`` carries the final hop's status / headers (a
    ``streamed=True`` :class:`~chumicro_requests.client.Response` with
    an empty ``body``); :meth:`read_into` pulls the body itself.  A
    caller that stops early calls :meth:`cancel` so the socket closes
    now instead of at the request timeout.
    """

    def __init__(self, client, handle):
        self._client = client
        self._handle = handle
        #: Final response — status, reason, headers — published before
        #: the body finished arriving.
        self.response = handle.response

    def read_into(self, buffer):
        """Fill caller-owned *buffer* with body bytes; return the count.

        Call as ``count = yield from reader.read_into(view)``.  Copies
        at most ``len(buffer)`` bytes and returns as soon as at least
        one is available, yielding the underlying client (parking the
        scheduler on the socket / request deadline) while none are.
        Returns ``0`` exactly once the body is complete.

        Raises:
            HttpError: The request failed mid-body — timeout, protocol
                error, socket error, or cancellation.  Raised before
                any bytes staged after the failure are handed out.
        """
        handle = self._handle
        client = self._client
        try:
            while True:
                if handle.error is not None:
                    raise handle.error
                count = handle.read_body_into(buffer)
                if count:
                    return count
                if handle.done:
                    return 0
                now_ms = yield client
                client.handle(now_ms)
        except BaseException:  # noqa: BLE001 - close the socket on GeneratorExit / thrown poll errors, then re-raise
            if not handle.done:
                client.cancel()
            raise

    def cancel(self):
        """Abort the transfer: close the socket, fail the handle.

        No-op once the request already finished.  A later
        :meth:`read_into` raises the cancellation ``HttpError``.
        """
        self._client.cancel()


def fetch(
    transport_factory,
    method,
    url,
    *,
    headers=None,
    body=None,
    json=None,
    max_redirects=None,
    max_body_bytes=DEFAULT_MAX_BODY_BYTES,
    timeout_ms=DEFAULT_TIMEOUT_MS,
    user_agent=None,
    ticks=None,
):
    """Issue one HTTP request and return the :class:`Response`.

    Call as ``response = yield from fetch(transport_factory, "GET", url)``
    from a generator registered with ``Runner.add_generator``.

    Args:
        transport_factory: Callable ``(host, port, use_tls) -> connector``
            returning a ``chumicro_sockets.SocketConnector``-shaped object
            (the same contract ``HttpClient`` accepts).
        method: HTTP verb, sent verbatim.
        url: Absolute ``http://`` / ``https://`` URL.
        headers: Optional dict / iterable of ``(name, value)`` pairs;
            overrides the encoder's defaults.
        body: Optional ``bytes`` / ``str`` body (mutually exclusive with *json*).
        json: Optional JSON-serializable body; sets ``Content-Type:
            application/json`` unless *headers* overrides it.
        max_redirects: Hops to follow before returning the redirect
            response as-is (default ``DEFAULT_MAX_REDIRECTS``).
        max_body_bytes: Hard cap on the response body; over it
            ``HttpOversizedError`` is raised.
        timeout_ms: Deadline for the whole request — the TCP connect,
            the TLS handshake, the request send, and the response read,
            summed across all redirect hops.  On expiry
            ``HttpTimeoutError`` is raised.  The one part not bounded is
            DNS resolution: the connector resolves the host with a
            synchronous ``getaddrinfo`` that is blocking-by-substrate on
            real boards, so a stall *inside* the lookup cannot be
            interrupted.
        user_agent: Override the default ``User-Agent``.
        ticks: Optional ``chumicro_timing``-shaped tick source; falls
            back to ``chumicro_timing.ticks``.

    Returns:
        :class:`~chumicro_requests.client.Response`.

    Raises:
        HttpTimeoutError: The request exceeded *timeout_ms* during the
            connect, TLS handshake, request send, or response read.  A
            stall inside DNS resolution is not bounded (blocking
            substrate).
        HttpOversizedError: Body exceeded *max_body_bytes*.
        HttpProtocolError: Response was not valid HTTP/1.1 or the peer
            closed mid-response.
        HttpURLError: *url* or a redirect ``Location`` did not parse.
        HttpError: The transport failed — connector failure or a
            non-retryable socket error.
        ValueError: Both *body* and *json* were given.
    """
    client, handle, now_ms = _issue(
        transport_factory, method, url,
        headers=headers, body=body, json=json,
        max_redirects=max_redirects, timeout_ms=timeout_ms,
        user_agent=user_agent, ticks=ticks,
        max_body_bytes=max_body_bytes,
    )
    try:
        while not handle.done:
            client.handle(now_ms)
            if handle.done:
                break
            now_ms = yield client
    finally:
        # Only an abnormal exit (GeneratorExit from a cancelled task, a
        # thrown poll error) leaves the request in flight; close its
        # socket now instead of leaking it until the timeout.
        if not handle.done:
            client.cancel()
    return handle.result


def stream(
    transport_factory,
    method,
    url,
    *,
    headers=None,
    body=None,
    json=None,
    max_redirects=None,
    timeout_ms=DEFAULT_TIMEOUT_MS,
    stream_buffer_size=DEFAULT_STREAM_BUFFER_SIZE,
    user_agent=None,
    ticks=None,
):
    """Issue one request and return a :class:`BodyReader` for its body.

    Call as ``reader = yield from stream(transport_factory, "GET", url)``.
    Returns once the final hop's headers are parsed — check
    ``reader.response.status_code`` before pulling the body with
    ``yield from reader.read_into(buffer)``.  Argument semantics match
    :func:`fetch` except there is no *max_body_bytes*: a streamed body
    may be any size, RAM-bounded by *stream_buffer_size* (the staging
    window between socket and caller, default 1024) plus the caller's
    own buffer.  *timeout_ms* bounds the whole transfer, consumption
    included — size it for the download, not for the round-trip.

    Raises:
        HttpTimeoutError: *timeout_ms* elapsed before headers arrived.
        HttpProtocolError: The response was not valid HTTP/1.1.
        HttpURLError: *url* or a redirect ``Location`` did not parse.
        HttpError: The transport failed before headers arrived.
        ValueError: Both *body* and *json* were given.
    """
    client, handle, now_ms = _issue(
        transport_factory, method, url,
        headers=headers, body=body, json=json,
        max_redirects=max_redirects, timeout_ms=timeout_ms,
        user_agent=user_agent, ticks=ticks,
        stream=True, stream_buffer_size=stream_buffer_size,
    )
    try:
        while handle.response is None and not handle.done:
            client.handle(now_ms)
            if handle.response is not None or handle.done:
                break
            now_ms = yield client
    finally:
        # Only an abnormal exit (GeneratorExit from a cancelled task, a
        # thrown poll error) leaves the request headerless-in-flight;
        # close its socket now instead of leaking it until the timeout.
        # After a normal exit the caller owns the transfer through the
        # BodyReader.
        if handle.response is None and not handle.done:
            client.cancel()
    if handle.error is not None:
        raise handle.error
    return BodyReader(client, handle)


def get(transport_factory, url, **kwargs):
    """``yield from get(transport_factory, url)`` — one-shot GET."""
    return fetch(transport_factory, "GET", url, **kwargs)


def post(transport_factory, url, **kwargs):
    """``yield from post(transport_factory, url, json=...)`` — one-shot POST."""
    return fetch(transport_factory, "POST", url, **kwargs)


def put(transport_factory, url, **kwargs):
    """``yield from put(transport_factory, url, body=...)`` — one-shot PUT."""
    return fetch(transport_factory, "PUT", url, **kwargs)


def patch(transport_factory, url, **kwargs):
    """``yield from patch(transport_factory, url, body=...)`` — one-shot PATCH."""
    return fetch(transport_factory, "PATCH", url, **kwargs)


def delete(transport_factory, url, **kwargs):
    """``yield from delete(transport_factory, url)`` — one-shot DELETE."""
    return fetch(transport_factory, "DELETE", url, **kwargs)
