"""Tests for chumicro_pytest_device.fixtures.udp_echo."""

import socket
import time

from chumicro_pytest_device.fixtures.udp_echo import start_udp_echo_server


def test_start_udp_echo_server_returns_handle_with_listening_port():
    """`start_udp_echo_server('127.0.0.1')` returns a handle with a bound port and a stop event."""
    host, port, stop = start_udp_echo_server("127.0.0.1")
    try:
        assert host == "127.0.0.1"
        assert isinstance(port, int) and 1024 < port < 65536
        assert stop is not None
        assert not stop.is_set()
    finally:
        stop.set()


def test_udp_echo_server_echoes_datagram_back_to_sender():
    """Send one datagram, read it back from the echo server."""
    host, port, stop = start_udp_echo_server("127.0.0.1")
    try:
        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client.settimeout(2.0)
        payload = b"chumicro-echo-fixture-test"
        client.sendto(payload, (host, port))
        echoed, peer = client.recvfrom(1500)
        assert echoed == payload
        assert peer[0] == host
        assert peer[1] == port
        client.close()
    finally:
        stop.set()
        # Give the daemon thread one timeout cycle to notice the
        # stop and close its socket before the test exits.
        time.sleep(0.1)
