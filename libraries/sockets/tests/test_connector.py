"""Cross-runtime tests for the SocketConnector state machine.

Exercises the runtime-agnostic state-machine behaviour against
:class:`FakeSocketConnector` (a scripted test double).  The real-loopback
CPython adapter tests live in :file:`test_connector_pytest.py`.

These tests are also the conformance suite that the per-runtime
adapters must satisfy — the observable surface is identical regardless
of substrate.
"""

from chumicro_runner import IO_READ, IO_WRITE
from chumicro_sockets._connector import (
    STATE_AWAITING_DNS,
    STATE_AWAITING_TCP,
    STATE_AWAITING_TLS,
    STATE_FAILED,
    STATE_READY,
)
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector
from chumicro_test_harness.assertions import raises


class TestFakeStateMachine:
    def test_initial_state_is_awaiting_dns(self) -> None:
        connector = FakeSocketConnector()
        assert connector.state == STATE_AWAITING_DNS
        assert connector.socket is None
        assert connector.last_error is None

    def test_dns_then_tcp_then_ready_for_plain(self) -> None:
        connector = FakeSocketConnector(actions=["dns_ok", "tcp_ok"])
        connector.tick(0)
        assert connector.state == STATE_AWAITING_TCP
        connector.tick(0)
        assert connector.state == STATE_READY
        assert connector.socket is not None
        assert connector.last_error is None

    def test_dns_then_tcp_then_tls_then_ready_for_tls(self) -> None:
        connector = FakeSocketConnector(
            tls=True, actions=["dns_ok", "tcp_ok", "tls_ok"],
        )
        connector.tick(0)
        assert connector.state == STATE_AWAITING_TCP
        connector.tick(0)
        assert connector.state == STATE_AWAITING_TLS
        connector.tick(0)
        assert connector.state == STATE_READY

    def test_tcp_pending_stays_in_awaiting_tcp(self) -> None:
        # Simulates an EINPROGRESS round-trip — first tcp tick said
        # "not yet," second tick says "done."
        connector = FakeSocketConnector(
            actions=["dns_ok", "tcp_pending", "tcp_ok"],
        )
        connector.tick(0)
        connector.tick(0)
        assert connector.state == STATE_AWAITING_TCP
        connector.tick(0)
        assert connector.state == STATE_READY

    def test_tls_pending_stays_in_awaiting_tls(self) -> None:
        connector = FakeSocketConnector(
            tls=True,
            actions=["dns_ok", "tcp_ok", "tls_pending", "tls_ok"],
        )
        for _ in range(3):
            connector.tick(0)
        assert connector.state == STATE_AWAITING_TLS
        connector.tick(0)
        assert connector.state == STATE_READY

    def test_fail_action_lands_in_failed(self) -> None:
        connector = FakeSocketConnector(actions=["fail:dns lookup failed"])
        connector.tick(0)
        assert connector.state == STATE_FAILED
        assert connector.last_error is not None
        assert "dns lookup failed" in str(connector.last_error)

    def test_fail_mid_handshake_lands_in_failed(self) -> None:
        connector = FakeSocketConnector(
            tls=True, actions=["dns_ok", "tcp_ok", "fail:bad cert"],
        )
        for _ in range(3):
            connector.tick(0)
        assert connector.state == STATE_FAILED
        assert "bad cert" in str(connector.last_error)


class TestFakeRunnerSurface:
    def test_check_true_in_non_terminal(self) -> None:
        connector = FakeSocketConnector(actions=["dns_ok", "tcp_ok"])
        assert connector.check(0) is True
        connector.tick(0)
        assert connector.check(0) is True

    def test_check_false_in_ready(self) -> None:
        connector = FakeSocketConnector(actions=["dns_ok", "tcp_ok"])
        connector.tick(0)
        connector.tick(0)
        assert connector.check(0) is False

    def test_check_false_in_failed(self) -> None:
        connector = FakeSocketConnector(actions=["fail:nope"])
        connector.tick(0)
        assert connector.check(0) is False

    def test_io_interest_write_during_tcp_phase(self) -> None:
        connector = FakeSocketConnector(actions=["dns_ok"])
        connector.tick(0)
        assert connector.io_interest(0) == IO_WRITE

    def test_io_interest_read_and_write_at_tls_phase_entry(self) -> None:
        # Before the first handshake step names a direction, the
        # connector doesn't know which way the handshake will block.
        connector = FakeSocketConnector(
            tls=True, actions=["dns_ok", "tcp_ok"],
        )
        for _ in range(2):
            connector.tick(0)
        assert connector.io_interest(0) == IO_READ | IO_WRITE

    def test_io_interest_narrows_to_read_after_tls_pending(self) -> None:
        # A pending handshake step (real connector: SSLWantReadError)
        # drops WRITE interest — an always-writable connected socket
        # would otherwise wake the poller every tick until the peer's
        # handshake flight arrives.
        connector = FakeSocketConnector(
            tls=True, actions=["dns_ok", "tcp_ok", "tls_pending"],
        )
        for _ in range(3):
            connector.tick(0)
        assert connector.state == STATE_AWAITING_TLS
        assert connector.io_interest(0) == IO_READ

    def test_io_socket_is_live_socket_in_ready(self) -> None:
        # At ``ready`` the connector keeps its socket live, so the
        # registrable pollable is that socket — matching the real
        # connector, whose consumers read ``connector.socket`` at
        # promotion.
        target = FakeSocket()
        connector = FakeSocketConnector(
            actions=["dns_ok", "tcp_ok"], socket=target,
        )
        connector.tick(0)
        connector.tick(0)
        assert connector.state == STATE_READY
        assert connector.io_socket is target

    def test_io_socket_none_in_failed(self) -> None:
        # ``fail:`` clears the socket, so the pollable goes ``None`` —
        # the runner does not wake on a dead handle.
        connector = FakeSocketConnector(actions=["fail:dns lookup failed"])
        connector.tick(0)
        assert connector.state == STATE_FAILED
        assert connector.io_socket is None

    def test_io_socket_live_during_connect_phases(self) -> None:
        # The socket is built at ``awaiting_tcp`` entry and the pollable
        # tracks it through the connect, so the runner can park on the
        # in-flight handle.
        connector = FakeSocketConnector(actions=["dns_ok"])
        assert connector.io_socket is None  # awaiting_dns, no socket yet
        connector.tick(0)
        assert connector.state == STATE_AWAITING_TCP
        assert connector.io_socket is not None

    def test_handle_aliases_tick(self) -> None:
        # ``runner.add(connector)`` calls .handle(); make sure that
        # advances the state machine the same way .tick() does.
        connector = FakeSocketConnector(actions=["dns_ok", "tcp_ok"])
        connector.handle(0)
        assert connector.state == STATE_AWAITING_TCP

    def test_next_deadline_is_none(self) -> None:
        connector = FakeSocketConnector(actions=["dns_ok", "tcp_ok"])
        assert connector.next_deadline(0) is None

    def test_cancel_transitions_to_failed(self) -> None:
        connector = FakeSocketConnector(actions=["dns_ok"])
        connector.tick(0)
        connector.cancel()
        assert connector.state == STATE_FAILED
        assert connector.last_error is not None
        assert connector.socket is None
        assert connector.io_socket is None

    def test_cancel_is_idempotent_in_terminal(self) -> None:
        connector = FakeSocketConnector(actions=["dns_ok", "tcp_ok"])
        connector.tick(0)
        connector.tick(0)
        assert connector.state == STATE_READY
        connector.cancel()  # No-op; doesn't clobber ready state.
        assert connector.state == STATE_READY

    def test_tick_in_terminal_is_noop(self) -> None:
        connector = FakeSocketConnector(actions=["dns_ok", "tcp_ok"])
        connector.tick(0)
        connector.tick(0)
        ready_socket = connector.socket
        connector.tick(0)
        assert connector.state == STATE_READY
        assert connector.socket is ready_socket


class TestFakeUsesProvidedSocket:
    def test_target_socket_surfaces_on_ready(self) -> None:
        # Consumer passes the FakeSocket it wants the connector to
        # deliver — same shape as injecting a FakeSocket directly into
        # MQTTClient today.
        target = FakeSocket()
        connector = FakeSocketConnector(
            actions=["dns_ok", "tcp_ok"], socket=target,
        )
        connector.tick(0)
        connector.tick(0)
        assert connector.socket is target


class TestFakeRejectsInvalidActions:
    def test_dns_action_in_tcp_state_raises(self) -> None:
        connector = FakeSocketConnector(actions=["dns_ok", "dns_ok"])
        connector.tick(0)
        with raises(AssertionError, match="dns_ok"):
            connector.tick(0)

    def test_tls_action_in_tcp_state_raises(self) -> None:
        # tls=False, so the connector reaches "awaiting_tcp" and never
        # advances to "awaiting_tls"; a "tls_ok" action in that state
        # is an invalid script.
        connector = FakeSocketConnector(actions=["dns_ok", "tls_ok"])
        connector.tick(0)
        with raises(AssertionError, match="tls_ok"):
            connector.tick(0)
