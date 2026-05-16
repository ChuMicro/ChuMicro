"""``FakeHttpClient`` — drive downstream code without a real network.

Designed for tests of code that takes an :class:`HttpClient` as a
constructor-injected dependency.  Mirrors the
production client's external surface (``get`` / ``check`` / ``handle``
/ ``busy`` / ``on_oversized``) but completes each request from a
scripted response queue instead of opening a socket.

Idiom — for a thing that fetches weather over HTTP::

    from chumicro_requests.testing import FakeHttpClient

    fake = FakeHttpClient()
    fake.enqueue_response(status=200, body=b'{"temp_f": 72}')
    weather = WeatherFetcher(http_client=fake)
    weather.tick(now_ms=0)               # internally calls fake.get(...)
    weather.tick(now_ms=10)              # one handle() tick completes
    assert weather.last_temperature == 72
    assert fake.calls[0].url == "http://api.example.test/weather"

The fake completes the in-flight request on the next :meth:`handle`
call after :meth:`get`, exercising the runner integration the same
way the real client would.  Scripted entries are consumed FIFO; an
empty queue raises :class:`HttpError` to surface "test forgot to
enqueue a response" as a clear failure.

This module is test-support — the ``__chumicro_test_support__``
marker below keeps it out of every bundle and every product / app /
functional device deploy, so it never lands on a shipped board (the
on-device unit sweep is the one path that stages it).
"""

#: Source bundle / sdist only -- never lands on a device.
__chumicro_test_support__ = True

from chumicro_requests._wire import (
    CaseInsensitiveDict,
    HttpBusyError,
    HttpError,
)
from chumicro_requests.client import RequestHandle, Response


class _ScriptedCall:
    """One call recorded by :class:`FakeHttpClient` (URL + headers + timeout)."""

    def __init__(self, *, method, url, headers, timeout_ms):
        self.method = method
        self.url = url
        self.headers = headers
        self.timeout_ms = timeout_ms


class FakeHttpClient:
    """In-memory :class:`HttpClient` stand-in for tests.

    Same external surface as :class:`HttpClient`.  Tests script
    responses via :meth:`enqueue_response` (success) or
    :meth:`enqueue_error` (failure); each :meth:`get` pops one entry
    off the queue head, and the next :meth:`handle` tick completes
    the in-flight :class:`RequestHandle`.
    """

    def __init__(self) -> None:
        self._scripted: list = []
        self._handle: RequestHandle | None = None
        self._url: str | None = None
        self._pending_outcome = None  # Response or HttpError, set in get()
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
        headers: object | None = None,
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
        """``True`` while a request is in flight (between get and handle)."""
        return self._handle is not None

    def get(
        self,
        url: str,
        *,
        headers: object | None = None,
        timeout_ms: int | None = None,
    ) -> RequestHandle:
        """Mirror :meth:`HttpClient.get` against the scripted queue.

        Pops the next scripted entry, builds the corresponding
        :class:`Response` (or readies the scripted error), and returns
        a fresh :class:`RequestHandle`.  The handle stays ``done=False``
        until the caller drives :meth:`handle` once.
        """
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
            method="GET", url=url, headers=headers, timeout_ms=timeout_ms,
        ))
        kind, payload = self._scripted.pop(0)
        if kind == "response":
            self._pending_outcome = Response(url=url, **payload)
        else:
            self._pending_outcome = payload  # HttpError instance
        self._handle = RequestHandle(url=url)
        self._url = url
        return self._handle

    def check(self, now_ms: int) -> bool:  # noqa: ARG002 — runner contract
        """Return ``True`` while a request is in flight."""
        return self._handle is not None

    def handle(self, now_ms: int) -> None:  # noqa: ARG002 — runner contract
        """Complete the in-flight request from the scripted outcome."""
        if self._handle is None:
            return
        outcome = self._pending_outcome
        if isinstance(outcome, Response):
            self._handle._set_response(outcome)  # noqa: SLF001 — internal handoff
        else:
            self._handle._set_error(outcome)  # noqa: SLF001 — internal handoff
        self._handle = None
        self._url = None
        self._pending_outcome = None
