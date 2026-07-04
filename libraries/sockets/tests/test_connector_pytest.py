"""SocketConnector — base state machine + CPython adapter against loopback.

The cross-runtime fake-driven tests live in :file:`test_connector.py`
(no pytest), exercising the state machine via :class:`FakeSocketConnector`.
This file is CPython-only because the real-loopback tests need stdlib
``socket`` / ``ssl`` / pytest fixtures.
"""

from __future__ import annotations

#: CPython-only lane (pytest fixtures + stdlib socket / ssl).
__chumicro_runtimes__ = ("cpython",)

import select
import socket
import ssl

import pytest
from chumicro_runner import IO_READ, IO_WRITE
from chumicro_sockets import connector as make_connector
from chumicro_sockets._connector import (
    STATE_AWAITING_DNS,
    STATE_AWAITING_TCP,
    STATE_AWAITING_TLS,
    STATE_FAILED,
    STATE_READY,
)


def _drive(connector, *, max_ticks: int = 50, now_ms: int = 0) -> None:
    """Tick the connector up to *max_ticks* times or until terminal.

    Between ticks, ``select.select`` parks briefly on the connector's
    ``io_socket`` — same shape as ``Runner.wait`` in production, gives
    the kernel time to complete the in-flight connect / handshake.
    Without this, the test driver spins faster than the connect can
    complete and bursts through ``max_ticks`` before the kernel marks
    the socket writable.
    """
    for _ in range(max_ticks):
        if not connector.check(now_ms):
            return
        io_sock = connector.io_socket
        if io_sock is not None:
            interest = connector.io_interest(now_ms)
            read_list = [io_sock] if interest & IO_READ else []
            write_list = [io_sock] if interest & IO_WRITE else []
            select.select(read_list, write_list, [], 0.05)
        connector.tick(now_ms)
    raise AssertionError(
        f"connector did not reach terminal state in {max_ticks} ticks "
        f"(state {connector.state!r})",
    )


@pytest.fixture
def listener():
    """Loopback TCP listener; yield (host, port)."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    host, port = server.getsockname()
    yield host, port
    server.close()


class TestCPythonTCPConnector:
    def test_connects_to_loopback(self, listener) -> None:
        host, port = listener
        connector = make_connector(host, port)
        assert connector.state == STATE_AWAITING_DNS
        _drive(connector)
        assert connector.state == STATE_READY
        assert connector.socket is not None
        # Connected socket has a non-trivial fileno.
        assert connector.socket.fileno() > 0
        connector.socket.close()

    def test_state_progresses_through_phases(self, listener) -> None:
        # First tick should resolve DNS and land in awaiting_tcp.
        # Subsequent ticks complete the TCP connect.
        host, port = listener
        connector = make_connector(host, port)
        connector.tick(0)
        assert connector.state == STATE_AWAITING_TCP
        # io_interest is IO_WRITE only during awaiting_tcp.
        assert connector.io_interest(0) == IO_WRITE
        _drive(connector)
        assert connector.state == STATE_READY
        connector.socket.close()

    def test_io_socket_tracks_socket_after_ready(self, listener) -> None:
        host, port = listener
        connector = make_connector(host, port)
        _drive(connector)
        # io_socket is a thin delegate of self.socket throughout the
        # lifecycle — including after ready — so consumers can keep
        # ``runner.add(consumer)`` registered without re-attributing
        # the wake-target.  The runner stops dispatching ``handle``
        # to the connector via ``check()`` returning False (separate
        # test); io_socket exposing the connected socket doesn't drive
        # extra wakeups.
        assert connector.io_socket is connector.socket
        connector.socket.close()

    def test_check_returns_false_when_ready(self, listener) -> None:
        host, port = listener
        connector = make_connector(host, port)
        _drive(connector)
        assert connector.check(0) is False
        connector.socket.close()

    def test_next_deadline_is_none(self, listener) -> None:
        # Connector itself does not time out; consumers wrap with
        # an outer deadline.
        host, port = listener
        connector = make_connector(host, port)
        assert connector.next_deadline(0) is None
        _drive(connector)
        assert connector.next_deadline(0) is None
        connector.socket.close()

    def test_dns_failure_lands_in_failed(self) -> None:
        # RFC2606 invalid TLD; never resolves.
        connector = make_connector("no-such-host.invalid", 1)
        _drive(connector)
        assert connector.state == STATE_FAILED
        assert connector.last_error is not None

    def test_connect_refused_lands_in_failed(self) -> None:
        # Loopback with no listener — kernel returns ECONNREFUSED.
        connector = make_connector("127.0.0.1", 1)
        _drive(connector)
        assert connector.state == STATE_FAILED
        assert connector.last_error is not None

    def test_cancel_transitions_to_failed(self, listener) -> None:
        host, port = listener
        connector = make_connector(host, port)
        connector.tick(0)  # awaiting_dns -> awaiting_tcp
        connector.cancel()
        assert connector.state == STATE_FAILED
        assert connector.last_error is not None
        # Cancel is idempotent.
        connector.cancel()
        assert connector.state == STATE_FAILED

    def test_tick_in_terminal_is_noop(self, listener) -> None:
        # Driving the real CPython tick path past terminal must early-
        # return without re-entering the state machine.  Pinned because
        # the early-return branch in _CPythonConnector.tick is otherwise
        # only reachable via the consumer-side wrapper.
        host, port = listener
        connector = make_connector(host, port)
        _drive(connector)
        assert connector.state == STATE_READY
        ready_socket = connector.socket
        connector.tick(0)
        assert connector.state == STATE_READY
        assert connector.socket is ready_socket
        ready_socket.close()

    def test_tcp_ready_returns_false_when_socket_not_writable(self) -> None:
        # _tcp_ready returning False keeps the connector in awaiting_tcp;
        # a connect to a non-responsive routable target keeps select
        # writability False for the test window.  Hits the not-writable
        # branch of _tcp_ready that fast loopback skips.
        from chumicro_sockets._adapters.cpython import _CPythonConnector

        connector = _CPythonConnector("203.0.113.1", 9, tls=False, context=None)
        connector.tick(0)  # awaiting_dns -> awaiting_tcp
        assert connector.state == STATE_AWAITING_TCP
        connector.tick(0)  # issues non-blocking connect; sets connector.socket
        # Subsequent tick checks readiness; the kernel hasn't completed
        # the connect (203.0.113.0/24 is TEST-NET-3, RFC 5737, no peer).
        connector.tick(0)
        assert connector.state == STATE_AWAITING_TCP
        connector.cancel()


class TestCPythonTLSConnector:
    # Real TLS handshake exercise lives in the consumer test path
    # (``chumicro_mqtt`` over a real TLS broker) once the connector is
    # wired into MQTTClient.  Local TLS-only fixtures need a paired
    # server-side TLS listener with a mint-cert dance — the existing
    # ``test_factories_pytest.py`` has that machinery.  The cross-
    # runtime state-machine coverage for the TLS phase is in
    # ``test_connector.py`` via ``FakeSocketConnector(tls=True)``.

    def test_constructs_in_awaiting_dns(self, listener) -> None:
        host, port = listener
        connector = make_connector(host, port, tls=True)
        assert connector.state == STATE_AWAITING_DNS

    def test_handshake_want_signals_narrow_io_interest(self) -> None:
        # Each SSLWant* names the one direction the handshake is
        # blocked on; io_interest must track it so the poller parks
        # instead of busy-waking on an always-writable socket.  Driven
        # against a scripted handshake so the WantWrite leg — rare on a
        # real loopback — is exercised deterministically.
        from chumicro_sockets._adapters.cpython import _CPythonConnector

        connector = _CPythonConnector("host.example", 443, tls=True, context=None)
        connector.socket = _ScriptedHandshakeSocket(
            [ssl.SSLWantReadError(), ssl.SSLWantWriteError()],
        )
        connector.state = STATE_AWAITING_TLS
        assert connector.io_interest(0) == IO_READ | IO_WRITE
        connector.tick(0)  # WantRead — narrow to read.
        assert connector.state == STATE_AWAITING_TLS
        assert connector.io_interest(0) == IO_READ
        connector.tick(0)  # WantWrite — flip to write.
        assert connector.state == STATE_AWAITING_TLS
        assert connector.io_interest(0) == IO_WRITE
        connector.tick(0)  # Handshake completes.
        assert connector.state == STATE_READY


class _ScriptedHandshakeSocket:
    """do_handshake raises the next scripted signal, then succeeds.

    Carries the no-op socket surface ``_CPythonTLSSocketWrapper``
    binds at ready-promotion (``close`` / ``setblocking`` /
    ``settimeout``).
    """

    def __init__(self, signals) -> None:
        self._signals = list(signals)

    def do_handshake(self) -> None:
        if self._signals:
            raise self._signals.pop(0)

    def close(self) -> None:
        pass

    def setblocking(self, flag) -> None:
        pass

    def settimeout(self, seconds) -> None:
        pass
