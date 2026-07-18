"""One-shot HTTP fetch and streamed-body reads as generators.

Public entry points: :func:`fetch`, :func:`get`, :func:`post`,
:func:`put`, :func:`patch`, :func:`delete`, and :func:`stream`.
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
    """Streamed-body pull surface returned by :func:`stream`."""

    def __init__(self, client, handle):
        self._client = client
        self._handle = handle
        #: Final response (status, reason, headers).
        self.response = handle.response

    def read_into(self, buffer):
        """Fill caller-owned *buffer* with body bytes; return the count.

        Raises:
            HttpError: The request failed mid-body.
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
        """Abort the transfer: close the socket, fail the handle."""
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

    Args:
        transport_factory: Callable ``(host, port, use_tls) -> connector`` (the ``HttpClient`` contract).
        method: HTTP verb, sent verbatim.
        url: Absolute ``http://`` / ``https://`` URL.
        headers: Optional dict / iterable of ``(name, value)`` pairs.
        body: Optional ``bytes`` / ``str`` body (mutually exclusive with *json*).
        json: Optional JSON body; sets ``Content-Type: application/json``.
        max_redirects: Hops to follow before returning the 3xx as-is.
        max_body_bytes: Hard cap on the response body.
        timeout_ms: Deadline for the whole request, DNS lookup excluded.
        user_agent: Override the default ``User-Agent``.
        ticks: Optional ``chumicro_timing``-shaped tick source.

    Returns:
        :class:`~chumicro_requests.client.Response`.

    Raises:
        HttpTimeoutError: The request exceeded *timeout_ms* (DNS stall excluded).
        HttpOversizedError: Body exceeded *max_body_bytes*.
        HttpProtocolError: Response was not valid HTTP/1.1 or peer closed mid-response.
        HttpURLError: *url* or a redirect ``Location`` did not parse.
        HttpError: The transport failed.
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
    """Issue one request and return a :class:`BodyReader` for its body.

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
        # An abnormal exit before headers leaves the request in flight;
        # close its socket now. After a normal exit the BodyReader owns it.
        if handle.response is None and not handle.done:
            client.cancel()
    if handle.error is not None:
        raise handle.error
    return BodyReader(client, handle)


def get(transport_factory, url, **kwargs):
    """One-shot GET; call as ``yield from get(transport_factory, url)``."""
    return fetch(transport_factory, "GET", url, **kwargs)


def post(transport_factory, url, **kwargs):
    """One-shot POST; call as ``yield from post(transport_factory, url, json=...)``."""
    return fetch(transport_factory, "POST", url, **kwargs)


def put(transport_factory, url, **kwargs):
    """One-shot PUT; call as ``yield from put(transport_factory, url, body=...)``."""
    return fetch(transport_factory, "PUT", url, **kwargs)


def patch(transport_factory, url, **kwargs):
    """One-shot PATCH; call as ``yield from patch(transport_factory, url, body=...)``."""
    return fetch(transport_factory, "PATCH", url, **kwargs)


def delete(transport_factory, url, **kwargs):
    """One-shot DELETE; call as ``yield from delete(transport_factory, url)``."""
    return fetch(transport_factory, "DELETE", url, **kwargs)
