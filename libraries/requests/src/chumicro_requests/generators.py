"""``chumicro_requests.generators`` runs a whole HTTP request inside a generator, as
``response = yield from get(transport_factory, url)``.

The generator runs under ``Runner.add_generator``.  ``fetch`` and the
per-method helpers ``get``, ``post``, ``put``, ``patch``, and ``delete``
return the ``Response``.  ``stream`` returns a ``BodyReader`` that reads a
large body one piece at a time.  Each helper builds its own ``HttpClient``.
This module loads only when imported by name, as in
``from chumicro_requests.generators import get``.
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
    if ticks is None:
        from chumicro_timing import ticks  # noqa: PLC0415 - DI fallback, like HttpClient
    client = HttpClient(
        transport_factory=transport_factory,
        max_body_bytes=max_body_bytes,
        # Pin DISCONNECT: a generator caller has no event hook to see a
        # dropped oversized body, so raise instead.
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
    """``BodyReader`` reads the body of a ``stream`` request one piece at a time.

    ``count = yield from reader.read_into(buffer)`` in a loop reads the body
    until the count is 0.

    Attributes:
        response: The ``Response`` with the status and headers.  Its ``body``
            is empty.
    """

    def __init__(self, client, handle):
        self._client = client
        self._handle = handle
        self.response = handle.response

    def read_into(self, buffer):
        """Fill ``buffer`` with the next body bytes and return how many arrived, or 0 at the end of the body.

        It is a generator: call it as
        ``count = yield from reader.read_into(buffer)``, where ``buffer`` is a
        ``bytearray`` or ``memoryview``.  While no body bytes are waiting it
        yields the ``HttpClient`` for the runner to poll.

        Raises:
            HttpError: The request failed or timed out mid-body.
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
        """Abort the transfer and close its socket.

        When the transfer was still running, a later ``read_into`` call
        raises ``HttpError``.
        """
        self._client.cancel()


def fetch(
    transport_factory: object,
    method: str,
    url: str,
    *,
    headers: object | None = None,
    body: object | None = None,
    json: object | None = None,
    max_redirects: int | None = None,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    user_agent: str | None = None,
    ticks: object | None = None,
) -> object:
    """Run one HTTP request and return its ``Response``.

    Call it as ``response = yield from fetch(transport_factory, "GET", url)``
    inside a generator that ``Runner.add_generator`` drives.  The generator
    yields while it waits for the server.  Opening the connection can hold the
    main loop, as with ``HttpClient``.  A failed, timed-out, or abandoned
    request closes its socket.

    Args:
        transport_factory: Function ``(host, port, use_tls)`` that returns a
            connector, the same one ``HttpClient`` takes.
        method: HTTP method, such as ``"GET"``.
        url: Absolute ``http://`` or ``https://`` URL.
        headers: Extra headers as a dict or ``(name, value)`` pairs.
        body: Request body as ``bytes`` or ``str``.  Pass at most one of
            ``body`` and ``json``.
        json: Object to send as a JSON body, with
            ``Content-Type: application/json``.
        max_redirects: Redirects to follow, or ``None`` for 5.
        max_body_bytes: Largest response body to accept, in bytes.  Default
            65536.
        timeout_ms: Time limit in ms for the whole request, counted from the
            first step.  The limit is checked between steps, so it cannot cut
            a blocking DNS lookup or handshake short.  Default 10000.
        user_agent: ``User-Agent`` header value, or ``None`` for the default.
        ticks: Clock with ``ticks_ms``, ``ticks_diff``, and ``ticks_add``, or
            ``None`` for ``chumicro_timing.ticks``.

    Yields:
        The ``HttpClient``, for the runner to poll, while the request is in
            flight.

    Returns:
        The ``Response``.

    Raises:
        HttpTimeoutError: ``timeout_ms`` passed before the response finished.
        HttpOversizedError: The body is larger than ``max_body_bytes``.
        HttpProtocolError: The response broke HTTP/1.1, or the server closed
            the connection early.
        HttpURLError: ``url`` or a redirect ``Location`` did not parse.
        HttpError: The connection failed.
        ValueError: Both ``body`` and ``json`` were given.
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
        # An abnormal exit (GeneratorExit, thrown poll error) leaves the
        # request in flight; close its socket now, not at the timeout.
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
    """Start one HTTP request, wait for its headers, and return a ``BodyReader`` for its body.

    Call it as ``reader = yield from stream(transport_factory, "GET", url)``.
    ``reader.response`` holds the status and headers, and
    ``reader.read_into`` reads the body.  The body passes through a window of
    ``stream_buffer_size`` bytes, so its size has no limit.  The other
    arguments match ``fetch``, and ``timeout_ms`` covers the body as well as
    the headers.  Until the headers arrive the generator yields the
    ``HttpClient`` for the runner to poll.

    Raises:
        HttpTimeoutError: ``timeout_ms`` passed before the headers arrived.
        HttpProtocolError: The response broke HTTP/1.1.
        HttpURLError: ``url`` or a redirect ``Location`` did not parse.
        HttpError: The connection failed before the headers arrived.
        ValueError: Both ``body`` and ``json`` were given.
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
        # An abnormal exit before headers leaves the request in flight;
        # close its socket now. After a normal exit the BodyReader owns it.
        if handle.response is None and not handle.done:
            client.cancel()
    if handle.error is not None:
        raise handle.error
    return BodyReader(client, handle)


def get(transport_factory, url, **kwargs):
    """Run a GET request for ``url`` and return its ``Response``.

    Call it as ``response = yield from get(transport_factory, url)``.  The
    keywords pass to ``fetch``.
    """
    return fetch(transport_factory, "GET", url, **kwargs)


def post(transport_factory, url, **kwargs):
    """Run a POST request and return its ``Response``.

    Call it as ``response = yield from post(transport_factory, url, json=data)``.
    The keywords pass to ``fetch``.
    """
    return fetch(transport_factory, "POST", url, **kwargs)


def put(transport_factory, url, **kwargs):
    """Run a PUT request and return its ``Response``.

    Call it as ``response = yield from put(transport_factory, url, body=data)``.
    The keywords pass to ``fetch``.
    """
    return fetch(transport_factory, "PUT", url, **kwargs)


def patch(transport_factory, url, **kwargs):
    """Run a PATCH request and return its ``Response``.

    Call it as ``response = yield from patch(transport_factory, url, json=data)``.
    The keywords pass to ``fetch``.
    """
    return fetch(transport_factory, "PATCH", url, **kwargs)


def delete(transport_factory, url, **kwargs):
    """Run a DELETE request for ``url`` and return its ``Response``.

    Call it as ``response = yield from delete(transport_factory, url)``.  The
    keywords pass to ``fetch``.
    """
    return fetch(transport_factory, "DELETE", url, **kwargs)
