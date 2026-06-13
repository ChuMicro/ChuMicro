"""One-shot HTTP fetch as a generator for runner-driven sequential I/O.

Opt-in submodule — import explicitly::

    from chumicro_requests.generators import fetch, get, post

A fetch is one request/response written top-to-bottom; the caller
delegates to it and receives the :class:`~chumicro_requests.client.Response`::

    def app(connector_factory):
        response = yield from get(connector_factory, "http://example.com/")
        print(response.status_code, response.json())

    handle = runner.add_generator(app(connector_factory))

The generator builds a connector per hop via the injected
``connector_factory(host, port, use_tls)`` (the same contract
``HttpClient`` takes), drives it to a connected socket with
``chumicro_sockets.generators.connect``, sends the encoded request, and
feeds the streaming ``ResponseParser`` until the response completes —
following redirects and enforcing ``timeout_ms`` and ``max_body_bytes``
along the way.

Unlike the long-lived ``HttpClient`` this allocates the response body
per call; it is for one-shot fetches, not a hot request loop.  Use
``HttpClient`` when you issue many requests from one client and want the
body buffer reused.
"""

import errno

from chumicro_requests._wire import (
    DEFAULT_MAX_BODY_BYTES,
    DEFAULT_MAX_REDIRECTS,
    DEFAULT_TIMEOUT_MS,
    METHOD_PRESERVING_REDIRECT_STATUS_CODES,
    REDIRECT_STATUS_CODES,
    HttpTimeoutError,
    ParseState,
    ResponseParser,
    encode_request,
    parse_url,
    resolve_redirect_url,
)
from chumicro_requests.client import Response, _encode_body, _merge_default_header

_RECV_CHUNK_SIZE = 512


class _ReadDeadlineWait:
    """Read-wait with a timeout: ``io_socket`` + ``io_wants_read`` + ``next_deadline``.

    The runner wrapper resumes a socket-driven wait every tick so the
    recv loop re-tries on each wake, while ``next_deadline`` only
    shortens ``Runner.wait``'s ipoll sleep — so the loop also wakes at
    the deadline when the peer goes silent, letting the recv loop's own
    deadline check fire.
    """

    io_wants_read = True

    def __init__(self, sock, deadline_ms):
        # Unwrap to the registrable pollable (the adapter wrapper stores
        # it on ``.sock``); select.poll can't register the wrapper.
        self.io_socket = getattr(sock, "sock", sock)
        self.next_deadline = deadline_ms


def fetch(
    connector_factory,
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

    Call as ``response = yield from fetch(connector_factory, "GET", url)``
    from a generator registered with ``Runner.add_generator``.

    Args:
        connector_factory: Callable ``(host, port, use_tls) -> connector``
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
        max_body_bytes: Hard cap on the response body; over it the
            parser raises ``HttpOversizedError``.
        timeout_ms: Deadline for the receive phase across all hops.
        user_agent: Override the default ``User-Agent``.
        ticks: Optional ``chumicro_timing``-shaped tick source; falls
            back to ``chumicro_timing.ticks``.

    Returns:
        :class:`~chumicro_requests.client.Response`.

    Raises:
        HttpTimeoutError: Receive phase exceeded *timeout_ms*.
        HttpOversizedError: Body exceeded *max_body_bytes*.
        HttpProtocolError: Response was not valid HTTP/1.1 or the peer
            closed mid-response.
        HttpURLError: *url* or a redirect ``Location`` did not parse.
        ValueError: Both *body* and *json* were given.
    """
    if body is not None and json is not None:
        raise ValueError("pass body= or json= but not both")
    if ticks is None:
        from chumicro_timing import ticks  # noqa: PLC0415 - DI fallback, like HttpClient
    # Opt-in substrate: imported here, not at module top, so importing
    # chumicro_requests does not pull chumicro_sockets for BYO-socket users.
    from chumicro_sockets.generators import connect, send_all  # noqa: PLC0415

    encoded_body = _encode_body(body, json)
    current_method = method
    current_body = encoded_body
    json_default_content_type = json is not None
    redirects_remaining = (
        max_redirects if max_redirects is not None else DEFAULT_MAX_REDIRECTS
    )
    deadline_ms = ticks.ticks_add(ticks.ticks_ms(), timeout_ms)
    current_url = url

    scratch = bytearray(_RECV_CHUNK_SIZE)
    scratch_view = memoryview(scratch)

    while True:
        merged_headers = headers
        if json_default_content_type:
            merged_headers = _merge_default_header(
                headers, "Content-Type", "application/json",
            )
        scheme, host, port, path = parse_url(current_url)
        use_tls = scheme == "https"
        default_port = 443 if use_tls else 80
        host_header = host if port == default_port else f"{host}:{port}"
        request_bytes = encode_request(
            current_method,
            host_header,
            path,
            headers=merged_headers,
            body=current_body,
            user_agent=user_agent,
        )
        connector = connector_factory(host, port, use_tls)
        sock = yield from connect(connector)
        try:
            yield from send_all(sock, request_bytes)
            parser = ResponseParser(max_body_bytes=max_body_bytes)
            read_wait = _ReadDeadlineWait(sock, deadline_ms)
            while parser.state not in (ParseState.DONE, ParseState.ERROR):
                if ticks.ticks_diff(deadline_ms, ticks.ticks_ms()) <= 0:
                    raise HttpTimeoutError(
                        f"request to {current_url!r} exceeded {timeout_ms} ms",
                    )
                try:
                    received = sock.recv_into(scratch_view)
                except OSError as socket_error:
                    if socket_error.args[0] == errno.EAGAIN:
                        yield read_wait
                        continue
                    raise
                if received == 0:
                    parser.feed_eof()
                    break
                parser.feed(scratch_view[:received])
            if parser.state == ParseState.ERROR:
                raise parser.error
        finally:
            sock.close()

        status_code = parser.status_code
        if redirects_remaining > 0 and status_code in REDIRECT_STATUS_CODES:
            location = parser.headers.get("Location")
            if location is not None:
                current_url = resolve_redirect_url(current_url, location)
                if status_code not in METHOD_PRESERVING_REDIRECT_STATUS_CODES:
                    # 301 / 302 / 303 — drop body, switch to GET.
                    current_method = "GET"
                    current_body = None
                    json_default_content_type = False
                redirects_remaining -= 1
                continue

        return Response(
            status_code=status_code,
            reason=parser.reason,
            http_version=parser.http_version,
            headers=parser.headers,
            body=parser.body,
            url=current_url,
        )


def get(connector_factory, url, **kwargs):
    """``yield from get(connector_factory, url)`` — one-shot GET."""
    return fetch(connector_factory, "GET", url, **kwargs)


def post(connector_factory, url, **kwargs):
    """``yield from post(connector_factory, url, json=...)`` — one-shot POST."""
    return fetch(connector_factory, "POST", url, **kwargs)


def put(connector_factory, url, **kwargs):
    """``yield from put(connector_factory, url, body=...)`` — one-shot PUT."""
    return fetch(connector_factory, "PUT", url, **kwargs)


def patch(connector_factory, url, **kwargs):
    """``yield from patch(connector_factory, url, body=...)`` — one-shot PATCH."""
    return fetch(connector_factory, "PATCH", url, **kwargs)


def delete(connector_factory, url, **kwargs):
    """``yield from delete(connector_factory, url)`` — one-shot DELETE."""
    return fetch(connector_factory, "DELETE", url, **kwargs)
