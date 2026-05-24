"""Integration test: DeviceBootstrapRunner + bind_to against a real stdlib HTTP server.

Proves the marker-dispatch + wait_for + http.client compose end-to-end
on real TCP — not just by mocking out the HTTP call.  The board side
is stood in for by :class:`FakeTransport`; the HTTP target is a
genuine in-process :class:`http.server.HTTPServer` on 127.0.0.1.
"""

from __future__ import annotations

import http.server
import threading
from typing import Any

import pytest
from chumicro_deploy.testing import FakeTransport
from chumicro_pytest_device.concurrent_runner import DeviceBootstrapRunner
from chumicro_pytest_device.fixtures.host_driver import (
    HttpResponseSnapshot,
    bind_to,
    http_client_against_board,
)

# Re-export the fixture so pytest's fixture-discovery picks it up
# when a test in this module asks for it by name.  Functional fixtures
# don't autoload across packages without an explicit import + reference.
_ = http_client_against_board


class _OkHandler(http.server.BaseHTTPRequestHandler):
    """Replies ``200 OK`` with a fixed body and a ``text/plain`` header."""

    response_body = b"hello from in-process server"

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(self.response_body)))
        self.end_headers()
        self.wfile.write(self.response_body)

    def log_message(
        self, format: str, *args: Any,  # noqa: A002 - stdlib signature
    ) -> None:
        # Silence the default stderr log so test output stays clean.
        pass


@pytest.fixture
def in_process_http_server():
    """Start a stdlib HTTP server on 127.0.0.1:<random> and yield the port.

    Teardown calls :meth:`http.server.HTTPServer.shutdown` so the
    server thread exits before pytest moves to the next test.
    """
    server = http.server.HTTPServer(("127.0.0.1", 0), _OkHandler)
    port = server.server_port
    server_thread = threading.Thread(
        target=server.serve_forever, name="test-http-server", daemon=True,
    )
    server_thread.start()
    try:
        yield port
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2.0)


class TestBindToAgainstRealHttpServer:
    """bind_to + DeviceBootstrapRunner drives real HTTP against a real server."""

    def test_round_trips_get_request_after_marker_arrives(
        self, in_process_http_server: int,
    ) -> None:
        marker_line = (
            f"SERVER_READY ip=127.0.0.1 port={in_process_http_server}\n"
        )
        transport = FakeTransport(
            execute_output=marker_line + "PASS test_ok (0.001s)\n",
        )
        runner = DeviceBootstrapRunner(transport, "boot")
        runner.start()
        try:
            hit = bind_to(runner)
            response = hit("/", timeout_s=2.0)
            assert isinstance(response, HttpResponseSnapshot)
            assert response.status == 200
            assert response.body == _OkHandler.response_body
            assert response.headers["content-type"].startswith("text/plain")
            assert response.headers["content-length"] == str(
                len(_OkHandler.response_body),
            )
        finally:
            runner.wait_for_completion(timeout_s=2.0)
            runner.shutdown()

    def test_hit_raises_marker_timeout_when_server_ready_never_arrives(
        self,
    ) -> None:
        # Bootstrap finishes without ever printing SERVER_READY — the
        # hit call should surface that as a MarkerTimeoutError, not
        # a hung test.
        from chumicro_pytest_device.markers import MarkerTimeoutError

        transport = FakeTransport(
            execute_output="PASS some_other_test (0.001s)\n",
        )
        runner = DeviceBootstrapRunner(transport, "boot")
        runner.start()
        try:
            hit = bind_to(runner)
            with pytest.raises(MarkerTimeoutError, match=r"SERVER_READY"):
                hit("/", timeout_s=0.2)
        finally:
            runner.wait_for_completion(timeout_s=2.0)
            runner.shutdown()


class TestHttpClientAgainstBoardFixture:
    """The pytest fixture returns bind_to itself; sanity-check the wiring."""

    def test_fixture_returns_bind_to_callable(
        self, http_client_against_board, in_process_http_server: int,
    ) -> None:
        marker_line = (
            f"SERVER_READY ip=127.0.0.1 port={in_process_http_server}\n"
        )
        transport = FakeTransport(execute_output=marker_line)
        runner = DeviceBootstrapRunner(transport, "boot")
        runner.start()
        try:
            hit = http_client_against_board(runner)
            response = hit("/", timeout_s=2.0)
            assert response.status == 200
        finally:
            runner.wait_for_completion(timeout_s=2.0)
            runner.shutdown()
