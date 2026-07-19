"""Tests for chumicro_pytest_device.fixtures.tcp_echo."""

import socket
import time

from chumicro_pytest_device.fixtures.tcp_echo import start_tcp_echo_server


def test_start_tcp_echo_server_returns_handle_with_listening_port():
    """`start_tcp_echo_server('127.0.0.1')` returns a handle with a bound port and a clear stop event."""
    host, port, stop = start_tcp_echo_server("127.0.0.1")
    try:
        assert host == "127.0.0.1"
        assert isinstance(port, int) and 1024 < port < 65536
        assert stop is not None
        assert not stop.is_set()
    finally:
        stop.set()
        time.sleep(0.1)


def test_tcp_echo_server_echoes_stream_back_to_sender():
    """Connect, send one payload, read the same bytes back from the echo server."""
    host, port, stop = start_tcp_echo_server("127.0.0.1")
    try:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(2.0)
        client.connect((host, port))
        payload = b"chumicro-tcp-echo-fixture-test"
        client.sendall(payload)
        echoed = client.recv(4096)
        assert echoed == payload
        client.close()
    finally:
        stop.set()
        # Give the daemon thread a couple of 50 ms poll cycles to notice
        # the stop and close its listener before the test exits.
        time.sleep(0.1)


def test_tcp_echo_server_accepts_a_second_connection_after_the_first_closes():
    """A second client connecting after the first closes still gets its bytes echoed."""
    host, port, stop = start_tcp_echo_server("127.0.0.1")
    try:
        first = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        first.settimeout(2.0)
        first.connect((host, port))
        first.sendall(b"first")
        assert first.recv(4096) == b"first"
        first.close()

        second = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        second.settimeout(2.0)
        second.connect((host, port))
        second.sendall(b"second")
        assert second.recv(4096) == b"second"
        second.close()
    finally:
        stop.set()
        time.sleep(0.1)
