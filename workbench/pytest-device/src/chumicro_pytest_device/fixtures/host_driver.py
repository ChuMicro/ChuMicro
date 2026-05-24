"""Host-side HTTP client driven by board-printed sync markers.

For Category 1 server-side tests the board runs the server and prints
``SERVER_READY ip=<ip> port=<port>`` once it is accepting; the host
fixture opens a stdlib HTTP connection to that address and fires the
request.  This module exposes the client side of that handshake.

Surface:

* :func:`bind_to(runner)` — plain function, returns a ``hit(path, ...)``
  callable bound to the supplied :class:`DeviceBootstrapRunner`.  Use
  this when wiring runner + fixture directly from a test or helper
  outside the pytest fixture graph.
* :func:`http_client_against_board` — pytest fixture that returns
  :func:`bind_to` itself, so tests can write
  ``hit = http_client_against_board(runner)`` and stay inside the
  fixture-graph.

The runner is *not* created here.  A consumer fixture (out of scope
for this module) owns runner creation from the session's transport
cache + a board-side test file; this module only owns the
HTTP-client side of the handshake.
"""

from __future__ import annotations

import http.client
from collections.abc import Callable
from dataclasses import dataclass

import pytest

from ..concurrent_runner import DeviceBootstrapRunner


@dataclass(frozen=True)
class HttpResponseSnapshot:
    """The handful of fields a Category 1 test typically asserts on.

    Returned by :func:`bind_to`'s ``hit`` callable in place of the raw
    :class:`http.client.HTTPResponse` so the underlying socket can be
    closed before the call returns — no caller bookkeeping to remember.

    ``headers`` keys are lowercased so a test can match
    ``response.headers["content-type"]`` without worrying about how
    the server cased the header on the wire.
    """

    status: int
    reason: str
    headers: dict[str, str]
    body: bytes


def bind_to(runner: DeviceBootstrapRunner) -> Callable[..., HttpResponseSnapshot]:
    """Build a ``hit(path, ...)`` callable that drives HTTP against the runner's board.

    The returned callable:

    1. Calls :meth:`DeviceBootstrapRunner.wait_for` for the
       ``SERVER_READY`` marker, with the per-call ``timeout_s``.
    2. Opens :class:`http.client.HTTPConnection` to
       ``marker.values["ip"]`` and ``int(marker.values["port"])``,
       with the same ``timeout_s`` as the socket timeout.
    3. Fires the request (``GET`` by default; ``method`` + ``body``
       overridable) and reads the response.
    4. Closes the underlying connection before returning a
       :class:`HttpResponseSnapshot`.

    Args:
        runner: The runner whose marker queue the ``hit`` callable
            should block on.

    Returns:
        A function ``hit(path, *, timeout_s=10.0, method="GET",
        body=None) -> HttpResponseSnapshot``.
    """

    def hit(
        path: str,
        *,
        timeout_s: float = 10.0,
        method: str = "GET",
        body: bytes | None = None,
    ) -> HttpResponseSnapshot:
        marker = runner.wait_for("SERVER_READY", timeout_s=timeout_s)
        ip_address = marker.values["ip"]
        port_number = int(marker.values["port"])
        connection = http.client.HTTPConnection(
            ip_address, port_number, timeout=timeout_s,
        )
        try:
            connection.request(method, path, body=body)
            response = connection.getresponse()
            response_body = response.read()
            return HttpResponseSnapshot(
                status=response.status,
                reason=response.reason,
                headers={
                    name.lower(): value for name, value in response.getheaders()
                },
                body=response_body,
            )
        finally:
            connection.close()

    return hit


@pytest.fixture
def http_client_against_board() -> Callable[
    [DeviceBootstrapRunner], Callable[..., HttpResponseSnapshot],
]:
    """Pytest-fixture wrapper around :func:`bind_to`.

    Tests use it as::

        def test_real_serve(device_bootstrap_runner, http_client_against_board):
            hit = http_client_against_board(device_bootstrap_runner)
            response = hit("/")
            assert response.status == 200
    """
    return bind_to
