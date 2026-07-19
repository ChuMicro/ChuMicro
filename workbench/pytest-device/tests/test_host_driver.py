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
from chumicro_pytest_device.fixtures.host_driver import (
    HttpResponseSnapshot,
    bind_to,
    http_client_against_board,
)
from chumicro_workspace.device_runner import DeviceBootstrapRunner

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
        # poll_interval bounds how long shutdown() blocks: serve_forever only
        # notices the stop flag once per poll, and the stdlib default is 0.5s.
        target=lambda: server.serve_forever(poll_interval=0.01),
        name="test-http-server", daemon=True,
    )
    server_thread.start()
    try:
        yield port
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2.0)


class TestBindToCachesMarker:
    """``hit`` only consumes SERVER_READY once — subsequent calls
    against the same bound runner reuse the cached address.  The
    board prints SERVER_READY once at startup, so re-waiting per
    call would hang forever after the first request."""

    def test_two_calls_resolve_marker_once(
        self, in_process_http_server: int,
    ) -> None:
        marker_line = (
            f"SERVER_READY ip=127.0.0.1 port={in_process_http_server}\n"
        )
        # Only ONE SERVER_READY in the captured output; a hit that
        # tried to wait_for it twice would time out on the second call.
        transport = FakeTransport(execute_output=marker_line)
        runner = DeviceBootstrapRunner(transport, "boot")
        runner.start()
        try:
            hit = bind_to(runner)
            first = hit("/", timeout_s=2.0)
            second = hit("/", timeout_s=2.0)
            assert first.status == 200
            assert second.status == 200
        finally:
            runner.wait_for_completion(timeout_s=2.0)
            runner.shutdown()


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
        from chumicro_workspace.markers import MarkerTimeoutError

        transport = FakeTransport(
            execute_output="PASS some_other_test (0.001s)\n",
        )
        runner = DeviceBootstrapRunner(transport, "boot")
        runner.start()
        try:
            hit = bind_to(runner)
            with pytest.raises(MarkerTimeoutError, match=r"SERVER_READY"):
                hit("/", timeout_s=0.05)
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


class TestResolveBoardFile:
    """`_resolve_board_file` picks the paired board file from a host test."""

    def _make_request_stub(
        self, host_file_path, marker_args=None,
    ):
        """Stand-in for ``pytest.FixtureRequest`` with only the fields the
        resolver reads — fspath + node.get_closest_marker."""

        class _Marker:
            def __init__(self, args):
                self.args = args

        class _Node:
            def __init__(self, marker):
                self._marker = marker

            def get_closest_marker(self, name):  # noqa: ARG002
                return self._marker

        class _Request:
            def __init__(self, fspath, marker):
                self.fspath = fspath
                self.node = _Node(marker)

        return _Request(
            host_file_path,
            _Marker(marker_args) if marker_args is not None else None,
        )

    def test_sibling_name_rule_strips_host_suffix(
        self, tmp_path,
    ) -> None:
        from chumicro_pytest_device.fixtures.host_driver import (
            _resolve_board_file,
        )

        board_file = tmp_path / "test_real_serve.py"
        host_file = tmp_path / "test_real_serve_host.py"
        board_file.write_text("# board side\n")
        host_file.write_text("# host side\n")

        request = self._make_request_stub(str(host_file))
        assert _resolve_board_file(request) == board_file

    def test_explicit_marker_overrides_sibling_rule(
        self, tmp_path,
    ) -> None:
        from chumicro_pytest_device.fixtures.host_driver import (
            _resolve_board_file,
        )

        host_file = tmp_path / "test_real_serve_host.py"
        host_file.write_text("# host side\n")
        # The marker names a file that is NOT the sibling default.
        custom_board = tmp_path / "alternate_board.py"
        custom_board.write_text("# alt board\n")

        request = self._make_request_stub(
            str(host_file), marker_args=("alternate_board.py",),
        )
        assert _resolve_board_file(request) == custom_board

    def test_fail_when_host_file_not_suffixed_and_no_marker(
        self, tmp_path,
    ) -> None:
        # A host file that doesn't end in `_host.py` and has no marker
        # — the resolver can't guess the pairing; surface fast rather
        # than silently picking the wrong file.
        from chumicro_pytest_device.fixtures.host_driver import (
            _resolve_board_file,
        )

        host_file = tmp_path / "test_real_serve_driver.py"
        host_file.write_text("# weirdly-named host file\n")

        request = self._make_request_stub(str(host_file))
        with pytest.raises(BaseException, match=r"_host\.py"):
            _resolve_board_file(request)

    def test_fail_when_resolved_board_file_does_not_exist(
        self, tmp_path,
    ) -> None:
        from chumicro_pytest_device.fixtures.host_driver import (
            _resolve_board_file,
        )

        host_file = tmp_path / "test_real_serve_host.py"
        host_file.write_text("# host side\n")
        # No sibling test_real_serve.py exists.

        request = self._make_request_stub(str(host_file))
        with pytest.raises(BaseException, match=r"does not exist"):
            _resolve_board_file(request)
