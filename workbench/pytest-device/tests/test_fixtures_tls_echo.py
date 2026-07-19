"""Tests for chumicro_pytest_device.fixtures.tls_echo."""

import socket
import ssl
import time

from chumicro_pytest_device.fixtures.tls_echo import (
    generate_self_signed_cert,
    start_tls_echo_server,
)


def test_generate_self_signed_cert_writes_cert_and_key(tmp_path):
    """`generate_self_signed_cert(workdir)` writes a PEM cert + PEM key whose paths exist."""
    cert_path, key_path = generate_self_signed_cert(tmp_path)
    assert cert_path.exists()
    assert key_path.exists()
    assert cert_path.read_bytes().startswith(b"-----BEGIN CERTIFICATE-----")
    assert b"PRIVATE KEY" in key_path.read_bytes()


def test_generated_cert_loads_into_a_server_ssl_context(tmp_path):
    """The generated cert + key load into a PROTOCOL_TLS_SERVER context without error."""
    cert_path, key_path = generate_self_signed_cert(tmp_path)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=cert_path, keyfile=key_path)


def test_start_tls_echo_server_returns_handle_with_listening_port(tmp_path):
    """`start_tls_echo_server` returns a handle with a bound port and a clear stop event."""
    cert_path, key_path = generate_self_signed_cert(tmp_path)
    host, port, stop = start_tls_echo_server("127.0.0.1", cert_path, key_path)
    try:
        assert host == "127.0.0.1"
        assert isinstance(port, int) and 1024 < port < 65536
        assert stop is not None
        assert not stop.is_set()
    finally:
        stop.set()
        time.sleep(0.1)


def _client_context(cert_path) -> ssl.SSLContext:
    """Build a client context that trusts only the in-test self-signed cert."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=cert_path)
    return context


def test_tls_echo_server_echoes_plaintext_back_over_the_tunnel(tmp_path):
    """Handshake against the 127.0.0.1 IP SAN, send a payload, read the same bytes back."""
    cert_path, key_path = generate_self_signed_cert(tmp_path)
    host, port, stop = start_tls_echo_server("127.0.0.1", cert_path, key_path)
    try:
        context = _client_context(cert_path)
        raw = socket.create_connection((host, port), timeout=2.0)
        # server_hostname must match a SAN entry; the cert covers
        # 127.0.0.1 as an IP SAN, so the IP literal verifies.
        tls = context.wrap_socket(raw, server_hostname="127.0.0.1")
        payload = b"chumicro-tls-echo-fixture-test"
        tls.sendall(payload)
        echoed = tls.recv(4096)
        assert echoed == payload
        tls.close()
    finally:
        stop.set()
        time.sleep(0.1)


def test_tls_echo_server_rejects_a_handshake_with_a_wrong_cert(tmp_path):
    """A client trusting a different cert than the server presents fails the handshake."""
    server_dir = tmp_path / "server"
    other_dir = tmp_path / "other"
    server_dir.mkdir()
    other_dir.mkdir()
    server_cert, server_key = generate_self_signed_cert(server_dir)
    other_cert, _other_key = generate_self_signed_cert(other_dir)
    host, port, stop = start_tls_echo_server("127.0.0.1", server_cert, server_key)
    try:
        context = _client_context(other_cert)
        raw = socket.create_connection((host, port), timeout=2.0)
        try:
            error_raised = False
            try:
                context.wrap_socket(raw, server_hostname="127.0.0.1")
            except ssl.SSLError:
                error_raised = True
            assert error_raised
        finally:
            raw.close()
    finally:
        stop.set()
        time.sleep(0.1)
