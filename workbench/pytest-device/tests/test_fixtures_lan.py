"""Tests for chumicro_pytest_device.fixtures.lan."""

from chumicro_pytest_device.fixtures.lan import (
    find_free_port,
    wait_until_listening,
)


def test_find_free_port_returns_open_port_on_loopback():
    """`find_free_port('127.0.0.1')` returns an ephemeral port the OS allocated."""
    port = find_free_port("127.0.0.1")
    assert isinstance(port, int)
    assert 1024 < port < 65536


def test_find_free_port_returns_distinct_ports_across_calls():
    """Consecutive `find_free_port` calls usually return different ports (OS rotation)."""
    ports = {find_free_port("127.0.0.1") for _ in range(8)}
    # Not strictly guaranteed, but the OS rotates the ephemeral pool;
    # collisions across 8 quick calls indicate a real bug.
    assert len(ports) > 1


def test_wait_until_listening_returns_false_when_nothing_is_listening():
    """`wait_until_listening` times out cleanly when the target port isn't accepting."""
    # Pick a port we know is free, but don't bind a listener — the
    # poll should time out and return False without raising.
    port = find_free_port("127.0.0.1")
    assert wait_until_listening("127.0.0.1", port, deadline_seconds=0.05) is False


def test_wait_until_listening_returns_true_when_listener_is_up():
    """`wait_until_listening` returns True once a real listener accepts."""
    import socket  # noqa: PLC0415 — local-only, host-side test

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    _host, port = listener.getsockname()
    try:
        assert wait_until_listening("127.0.0.1", port, deadline_seconds=1.0) is True
    finally:
        listener.close()
