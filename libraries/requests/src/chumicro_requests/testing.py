"""``FakeHttpClient`` plus low-level fixtures for the client test suite.

Two layers live here. :class:`FakeHttpClient` is a scripted in-memory
stand-in for an :class:`HttpClient` dependency: it mirrors the verb
surface (``get`` / ``post`` / ... / ``check`` / ``handle`` / ``busy``)
but completes each request from a scripted queue instead of opening a
socket. :func:`make_factory`, :func:`canned_response`,
:func:`drive_until_done`, and :func:`make_client` drive a real
:class:`HttpClient` against a
:class:`chumicro_sockets.testing.FakeSocket`.

Script responses with :meth:`FakeHttpClient.enqueue_response` or
:meth:`FakeHttpClient.enqueue_error`; each request pops one entry FIFO,
and the next :meth:`FakeHttpClient.handle` tick completes the in-flight
request. An empty queue raises :class:`HttpError` so a test that forgot
to enqueue fails clearly.
"""

#: Ships in the source bundle and sdist; never lands on a device.
__chumicro_test_support__ = True

from chumicro_sockets.testing import FakeSocket, FakeSocketConnector
from chumicro_timing.testing import FakeTicks

from chumicro_requests._wire import (
    CaseInsensitiveDict,
    HttpBusyError,
    HttpError,
)
from chumicro_requests.client import HttpClient, RequestHandle, Response


class _ScriptedCall:
    def __init__(
        self, *, method, url, headers, body, json_body,
        timeout_ms, max_redirects, stream=False,
    ):
        self.method = method
        self.url = url
        self.headers = headers
        self.body = body
        self.json = json_body
        self.timeout_ms = timeout_ms
        self.max_redirects = max_redirects
        self.stream = stream


class _ScriptedBodySource:
    """Serves a scripted body through ``read_body_into`` for streamed fakes."""

    def __init__(self, body):
        self._view = memoryview(bytes(body))
        self._offset = 0

    def read_body_into(self, buffer):
        remaining = len(self._view) - self._offset
        if remaining == 0:
            return 0
        count = len(buffer)
        if count > remaining:
            count = remaining
        start = self._offset
        buffer[:count] = self._view[start:start + count]
        self._offset = start + count
        return count


class FakeHttpClient:
    """In-memory :class:`HttpClient` stand-in for tests.

    Mirrors the production verb methods (``get`` / ``post`` / ``put`` /
    ``patch`` / ``delete``) and the runner-contract surface (``check``
    / ``handle`` / ``busy``).  Tests script responses via
    :meth:`enqueue_response` (success) or :meth:`enqueue_error`
    (failure); each request pops one entry off the queue head, and
    the next :meth:`handle` tick completes the in-flight
    :class:`RequestHandle` and invokes its ``on_done`` callback.
    """

    def __init__(self) -> None:
        self._scripted: list = []
        self._handle: RequestHandle | None = None
        self._url: str | None = None
        self._pending_outcome = None  # Response or HttpError, set in _start_request
        self.calls: list[_ScriptedCall] = []
        self.on_oversized = lambda *_args, **_kwargs: None

    # ------------------------------------------------------------------
    # Test scripting
    # ------------------------------------------------------------------

    def enqueue_response(
        self,
        *,
        status: int = 200,
        reason: str = "OK",
        http_version: str = "HTTP/1.1",
        headers: CaseInsensitiveDict | dict | list | tuple | None = None,
        body: bytes = b"",
        oversized_dropped: bool = False,
    ) -> None:
        """Script the next request to succeed with this response.

        Args:
            status: HTTP status code (default 200).
            reason: Reason phrase (default ``"OK"``).
            http_version: Protocol version string (default ``"HTTP/1.1"``).
            headers: ``dict`` / ``CaseInsensitiveDict`` / iterable of
                ``(name, value)``.  Folded into a
                :class:`CaseInsensitiveDict` for the response.
            body: Response body bytes (default empty).
            oversized_dropped: Set the matching flag on the response
                for tests that exercise oversize-policy branches.
        """
        folded = CaseInsensitiveDict()
        if headers is not None:
            iterable = headers.items() if isinstance(headers, dict) else headers
            for name, value in iterable:
                folded[name] = value
        self._scripted.append(("response", {
            "status_code": status,
            "reason": reason,
            "http_version": http_version,
            "headers": folded,
            "body": body,
            "oversized_dropped": oversized_dropped,
        }))

    def enqueue_error(self, error: HttpError) -> None:
        """Script the next request to fail with *error*."""
        if not isinstance(error, HttpError):
            raise TypeError(
                f"enqueue_error expects HttpError, got {type(error).__name__}",
            )
        self._scripted.append(("error", error))

    # ------------------------------------------------------------------
    # HttpClient surface
    # ------------------------------------------------------------------

    @property
    def busy(self) -> bool:
        """``True`` while a request is in flight (between request method and handle)."""
        return self._handle is not None

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
    ) -> RequestHandle:
        """Mirror :meth:`HttpClient.request` against the scripted queue."""
        return self._start_request(
            method, url, headers=headers, body=body, json_body=json,
            timeout_ms=timeout_ms, max_redirects=max_redirects,
            on_done=on_done, stream=stream,
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
    ) -> RequestHandle:
        """Mirror :meth:`HttpClient.get` against the scripted queue."""
        return self._start_request(
            "GET", url, headers=headers, body=None, json_body=None,
            timeout_ms=timeout_ms, max_redirects=max_redirects,
            on_done=on_done, stream=stream,
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
    ) -> RequestHandle:
        """Mirror :meth:`HttpClient.post` against the scripted queue.

        Passing both *body* and *json* raises ``ValueError`` to match
        the production validation.
        """
        return self._start_request(
            "POST", url, headers=headers, body=body, json_body=json,
            timeout_ms=timeout_ms, max_redirects=max_redirects,
            on_done=on_done, stream=stream,
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
    ) -> RequestHandle:
        """Mirror :meth:`HttpClient.put` against the scripted queue."""
        return self._start_request(
            "PUT", url, headers=headers, body=body, json_body=json,
            timeout_ms=timeout_ms, max_redirects=max_redirects,
            on_done=on_done, stream=stream,
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
    ) -> RequestHandle:
        """Mirror :meth:`HttpClient.patch` against the scripted queue."""
        return self._start_request(
            "PATCH", url, headers=headers, body=body, json_body=json,
            timeout_ms=timeout_ms, max_redirects=max_redirects,
            on_done=on_done, stream=stream,
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
    ) -> RequestHandle:
        """Mirror :meth:`HttpClient.delete` against the scripted queue.

        DELETE never carries a body in v1, matching HttpClient.
        """
        return self._start_request(
            "DELETE", url, headers=headers, body=None, json_body=None,
            timeout_ms=timeout_ms, max_redirects=max_redirects,
            on_done=on_done, stream=stream,
        )

    def check(self, now_ms: int) -> bool:  # noqa: ARG002 - runner contract
        """Return ``True`` while a request is in flight."""
        return self._handle is not None

    def handle(self, now_ms: int) -> None:  # noqa: ARG002 - runner contract
        """Complete the in-flight request from the scripted outcome.

        Fires the handle's ``on_done`` callback (if registered) after
        the fake has returned to idle, matching the production client. A
        streamed request's scripted body is installed as the handle's
        body source, so the code under test drains it via
        ``read_body_into`` after this tick.
        """
        if self._handle is None:
            return
        outcome = self._pending_outcome
        finished_handle = self._handle
        if isinstance(outcome, tuple):
            # Streamed success: (streamed Response, scripted body bytes).
            response, body_bytes = outcome
            finished_handle._publish_stream(  # noqa: SLF001 - internal handoff
                response, _ScriptedBodySource(body_bytes),
            )
            finished_handle._set_response(response)  # noqa: SLF001 - internal handoff
        elif isinstance(outcome, Response):
            finished_handle._set_response(outcome)  # noqa: SLF001 - internal handoff
        else:
            finished_handle._set_error(outcome)  # noqa: SLF001 - internal handoff
        self._handle = None
        self._url = None
        self._pending_outcome = None
        finished_handle._invoke_done()  # noqa: SLF001 - internal handoff

    def cancel(self) -> None:
        """Mirror :meth:`HttpClient.cancel`: fail the in-flight request.

        No-op when idle.  The handle finishes with
        ``HttpError("request ... cancelled")`` and its ``on_done``
        fires, matching the production client.
        """
        if self._handle is None:
            return
        finished_handle = self._handle
        cancelled_url = self._url
        self._handle = None
        self._url = None
        self._pending_outcome = None
        finished_handle._set_error(  # noqa: SLF001 - internal handoff
            HttpError(f"request to {cancelled_url!r} cancelled"),
        )
        finished_handle._invoke_done()  # noqa: SLF001 - internal handoff

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _start_request(
        self, method, url, *, headers, body, json_body,
        timeout_ms, max_redirects, on_done, stream=False,
    ):
        """Record the call, pop the scripted outcome, return a handle."""
        if body is not None and json_body is not None:
            raise ValueError("pass body= or json= but not both")
        if self._handle is not None:
            raise HttpBusyError(
                f"FakeHttpClient busy on {self._url!r}; "
                "await handle.done before issuing another",
            )
        if not self._scripted:
            raise HttpError(
                "FakeHttpClient has no scripted responses; "
                "call enqueue_response()/enqueue_error() in your test setup",
            )
        self.calls.append(_ScriptedCall(
            method=method, url=url, headers=headers,
            body=body, json_body=json_body,
            timeout_ms=timeout_ms, max_redirects=max_redirects,
            stream=stream,
        ))
        kind, payload = self._scripted.pop(0)
        if kind == "response":
            if stream:
                # Streamed: the Response carries no body; the scripted
                # bytes drain through read_body_into instead.
                streamed_payload = dict(payload)
                scripted_body = streamed_payload["body"]
                streamed_payload["body"] = b""
                self._pending_outcome = (
                    Response(url=url, streamed=True, **streamed_payload),
                    scripted_body,
                )
            else:
                self._pending_outcome = Response(url=url, **payload)
        else:
            self._pending_outcome = payload  # HttpError instance
        self._handle = RequestHandle(url=url, on_done=on_done, stream=stream)
        self._url = url
        return self._handle


# ---------------------------------------------------------------------------
# Low-level fixtures for the real-client test suite
# ---------------------------------------------------------------------------


def canned_response(*, status=200, reason="OK", body=b"", extra_headers=()):
    """Build an HTTP/1.1 response byte-string with ``Content-Length``."""
    lines = [f"HTTP/1.1 {status} {reason}\r\n".encode("ascii")]
    lines.append(f"Content-Length: {len(body)}\r\n".encode("ascii"))
    lines.append(b"Content-Type: text/plain\r\n")
    for name, value in extra_headers:
        lines.append(f"{name}: {value}\r\n".encode("ascii"))
    lines.append(b"\r\n")
    lines.append(body)
    return b"".join(lines)


def make_factory(socket_or_factory):
    """Return a transport_factory that wraps *socket_or_factory* in a
    happy-path :class:`FakeSocketConnector`.

    *socket_or_factory* is either a single :class:`FakeSocket` (wrapped
    on every call) or a zero-arg callable that builds a fresh socket
    on demand.  The connector script is the shortest happy path:
    ``dns_ok`` then ``tcp_ok``.  Tests that need pending/failure
    phases should build the connector directly.
    """
    def factory(host, port, use_tls):  # noqa: ARG001 - fake ignores args
        socket = socket_or_factory() if callable(socket_or_factory) else socket_or_factory
        return FakeSocketConnector(actions=["dns_ok", "tcp_ok"], socket=socket)

    return factory


def make_client(*, socket_or_factory=None, **kwargs):
    """Build an :class:`HttpClient` against ``FakeTicks`` + a ``FakeSocket``.

    Returns ``(client, ticks, socket)``.  ``kwargs`` forward to
    ``HttpClient``.
    """
    ticks = FakeTicks()
    socket = socket_or_factory if socket_or_factory is not None else FakeSocket()
    client = HttpClient(
        transport_factory=make_factory(socket),
        ticks=ticks,
        **kwargs,
    )
    return client, ticks, socket


def drive_until_done(client, handle, ticks, *, max_ticks=200, advance_ms=1):
    """Tick *client* until *handle*\\ ``.done`` flips True.

    Safety-caps at *max_ticks* iterations and raises
    :class:`AssertionError` if the handle never completes.
    """
    for _ in range(max_ticks):
        if handle.done:
            return
        if client.check(ticks.ticks_ms()):
            client.handle(ticks.ticks_ms())
        ticks.advance(advance_ms)
    raise AssertionError(f"handle never completed within {max_ticks} ticks")
