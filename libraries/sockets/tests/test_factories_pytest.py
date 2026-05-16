"""CPython-only tests for the runtime-routing factories.

These tests need:

* Real loopback ``socket.socket()`` instances (CPython stdlib).
* The ``cryptography`` library to mint self-signed X.509 certs at
  test time.
* ``threading`` to drive accept loops in the background.

None of those are available cross-runtime: stdlib ``socket`` isn't
on the CP unix-port; ``cryptography`` is a CPython-only PyPI package;
``threading`` isn't on the unix-ports either.  CPython is the right
home for them.

The cross-runtime routing tests — same dispatcher coverage, just
exercised against fakes instead of real I/O — live in the sibling
``test_factories.py``.
"""

from __future__ import annotations

#: CPython-only lane (pytest fixtures / host stdlib); not cross-runtime.
__chumicro_runtimes__ = ("cpython",)

import socket
import ssl
from datetime import UTC

import pytest
from chumicro_sockets import (
    UnsupportedSSLConfigError,
    ssl_context_with_cert_and_key_paths,
    tcp_client_socket,
    tcp_listening_socket,
    tls_listening_socket,
)

# ---------------------------------------------------------------------------
# CPython adapter — real factory call against a loopback echo server
# ---------------------------------------------------------------------------


@pytest.fixture
def echo_server():
    """Spin up a one-shot loopback TCP server; yield (host, port)."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    host, port = server.getsockname()
    yield host, port
    server.close()


class TestCPythonTCP:
    def test_factory_returns_connected_socket(self, echo_server) -> None:
        host, port = echo_server
        sock = tcp_client_socket(host, port)
        try:
            # Real socket has fileno > 0.
            assert sock.fileno() > 0
        finally:
            sock.close()

    def test_send_returns_byte_count_on_connected_socket(self, echo_server) -> None:
        """``tcp_client_socket`` returns a socket whose ``send`` reaches the kernel.

        The fixture is a bind-and-listen target, not a real echo
        server (no accept loop is running), so we can't drive a
        round-trip here — that lives in
        ``functional_tests/test_real_tcp.py`` against real hardware
        + real network.  This test asserts the contract a host-side
        unit test can: ``send`` returns the byte count, doesn't
        raise, and doesn't silently drop bytes.
        """
        host, port = echo_server
        sock = tcp_client_socket(host, port)
        try:
            sent = sock.send(b"hi")
            assert sent == 2
        finally:
            sock.close()

    def test_unknown_host_raises_oserror(self) -> None:
        # ``no-such-host.invalid`` is reserved by RFC2606 and should
        # never resolve.  Any failure mode (DNS NXDOMAIN, EAI_*,
        # ConnectionRefused) is wrapped in OSError on stdlib.
        with pytest.raises(OSError):
            tcp_client_socket("no-such-host.invalid", 1)


class TestCPythonListener:
    """``tcp_listening_socket`` — non-blocking accept loop on CPython."""

    def test_listener_accepts_loopback_connection(self) -> None:
        import time as time_module

        listener = tcp_listening_socket("127.0.0.1", 0)
        try:
            host, port = listener.getsockname()
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                client.connect((host, port))
                # Non-blocking accept may race ahead of the kernel's
                # accept queue update on macOS even on loopback; retry
                # a handful of times before declaring failure.
                accepted = None
                peer = None
                for _ in range(20):
                    try:
                        accepted, peer = listener.accept()
                        break
                    except (BlockingIOError, OSError) as accept_error:
                        if accept_error.args and accept_error.args[0] not in (11, 35):
                            raise
                        time_module.sleep(0.01)
                assert accepted is not None, "non-blocking accept never returned a connection"
                try:
                    assert accepted.fileno() > 0
                finally:
                    accepted.close()
            finally:
                client.close()
        finally:
            listener.close()

    def test_listener_is_non_blocking(self) -> None:
        """``accept()`` raises EAGAIN when no connection is queued."""
        listener = tcp_listening_socket("127.0.0.1", 0)
        try:
            with pytest.raises((BlockingIOError, OSError)):
                listener.accept()
        finally:
            listener.close()

    def test_so_reuseaddr_set(self) -> None:
        """Quick rebind on the same port doesn't trip EADDRINUSE."""
        listener = tcp_listening_socket("127.0.0.1", 0)
        host, port = listener.getsockname()
        listener.close()
        # Immediate rebind on the same port — would fail without
        # SO_REUSEADDR on most platforms during TIME_WAIT.
        rebound = tcp_listening_socket("127.0.0.1", port)
        try:
            assert rebound.getsockname()[1] == port
        finally:
            rebound.close()


class TestSslContextWithCertAndKey:
    """``ssl_context_with_cert_and_key`` builds a server-side context."""

    def test_routes_through_cpython_adapter(self) -> None:
        from datetime import datetime, timedelta  # noqa: PLC0415

        from chumicro_sockets import ssl_context_with_cert_and_key

        # Generate a tiny self-signed cert via the cryptography library
        # (already a dev dep for our other server-side tests).
        from cryptography import x509  # noqa: PLC0415
        from cryptography.hazmat.primitives import hashes, serialization  # noqa: PLC0415
        from cryptography.hazmat.primitives.asymmetric import ec  # noqa: PLC0415
        from cryptography.x509.oid import NameOID  # noqa: PLC0415

        private_key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "test.local"),
        ])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(UTC) - timedelta(minutes=5))
            .not_valid_after(datetime.now(UTC) + timedelta(hours=1))
            .add_extension(
                x509.SubjectAlternativeName([x509.DNSName("test.local")]),
                critical=False,
            )
            .sign(private_key, hashes.SHA256())
        )
        cert_pem = cert.public_bytes(serialization.Encoding.PEM)
        key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        context = ssl_context_with_cert_and_key(cert_pem, key_pem)
        assert context.get_ciphers() is not None  # built successfully

    def test_str_input_accepted(self) -> None:
        from datetime import datetime, timedelta  # noqa: PLC0415

        from chumicro_sockets import ssl_context_with_cert_and_key

        # Build via bytes first (so we have valid PEM), then re-feed
        # as str to verify the str-input path.
        from cryptography import x509  # noqa: PLC0415
        from cryptography.hazmat.primitives import hashes, serialization  # noqa: PLC0415
        from cryptography.hazmat.primitives.asymmetric import ec  # noqa: PLC0415
        from cryptography.x509.oid import NameOID  # noqa: PLC0415

        private_key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "x")])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(private_key.public_key())
            .serial_number(1)
            .not_valid_before(datetime.now(UTC) - timedelta(minutes=5))
            .not_valid_after(datetime.now(UTC) + timedelta(hours=1))
            .sign(private_key, hashes.SHA256())
        )
        cert_str = cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
        key_str = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("ascii")
        context = ssl_context_with_cert_and_key(cert_str, key_str)
        assert context.get_ciphers() is not None


class TestSslContextWithCertAndKeyPathsLoopback:
    """The path-based helper actually loads from disk on CPython.

    The cross-runtime routing test (CP adapter dispatch) lives in
    ``test_factories.py``; this is the real-disk-load path.
    """

    def test_cpython_loads_from_paths(self, tmp_path) -> None:
        """Generate a self-signed cert + key, write to disk, load from path."""
        from datetime import datetime, timedelta  # noqa: PLC0415

        from cryptography import x509  # noqa: PLC0415
        from cryptography.hazmat.primitives import hashes, serialization  # noqa: PLC0415
        from cryptography.hazmat.primitives.asymmetric import ec  # noqa: PLC0415
        from cryptography.x509.oid import NameOID  # noqa: PLC0415

        private_key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "test.local"),
        ])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(private_key.public_key())
            .serial_number(1)
            .not_valid_before(datetime.now(UTC) - timedelta(minutes=5))
            .not_valid_after(datetime.now(UTC) + timedelta(hours=1))
            .sign(private_key, hashes.SHA256())
        )
        cert_path = tmp_path / "cert.pem"
        key_path = tmp_path / "key.pem"
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ))

        context = ssl_context_with_cert_and_key_paths(
            str(cert_path), str(key_path),
        )
        assert context.get_ciphers() is not None


class TestCPythonTLSListener:
    """Real loopback TLS handshake — exercises the listen_tls path."""

    def test_handshake_round_trip(self) -> None:
        """Open a TLS listener, connect with stdlib, complete handshake."""
        import threading
        from datetime import datetime, timedelta  # noqa: PLC0415

        from chumicro_sockets import ssl_context_with_cert_and_key

        # Generate a cert.
        from cryptography import x509  # noqa: PLC0415
        from cryptography.hazmat.primitives import hashes, serialization  # noqa: PLC0415
        from cryptography.hazmat.primitives.asymmetric import ec  # noqa: PLC0415
        from cryptography.x509.oid import NameOID  # noqa: PLC0415

        private_key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "test.local"),
        ])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(UTC) - timedelta(minutes=5))
            .not_valid_after(datetime.now(UTC) + timedelta(hours=1))
            .add_extension(
                x509.SubjectAlternativeName([
                    x509.DNSName("test.local"),
                ]),
                critical=False,
            )
            .sign(private_key, hashes.SHA256())
        )
        cert_pem = cert.public_bytes(serialization.Encoding.PEM)
        key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

        server_context = ssl_context_with_cert_and_key(cert_pem, key_pem)
        listener = tls_listening_socket("127.0.0.1", 0, context=server_context)
        host, port = listener._raw.getsockname()  # noqa: SLF001

        # Listener is non-blocking; drive the accept in a background thread.
        accepted_holder: list = []

        def background_accept():
            import time as time_module  # noqa: PLC0415
            for _ in range(100):
                try:
                    sock, _peer_address = listener.accept()
                    accepted_holder.append(sock)
                    return
                except (BlockingIOError, OSError) as accept_error:
                    if accept_error.args and accept_error.args[0] not in (11, 35):
                        raise
                    time_module.sleep(0.01)

        accept_thread = threading.Thread(target=background_accept, daemon=True)
        accept_thread.start()

        # Build a client context that trusts our self-signed cert.
        client_context = ssl.create_default_context()
        client_context.load_verify_locations(cadata=cert_pem.decode("ascii"))
        # Server's hostname must match the cert SAN.
        client_context.check_hostname = True

        client_raw = socket.create_connection((host, port))
        try:
            client_tls = client_context.wrap_socket(
                client_raw, server_hostname="test.local",
            )
            try:
                accept_thread.join(timeout=2.0)
                assert len(accepted_holder) == 1
                accepted = accepted_holder[0]
                # Round-trip a byte to confirm the handshake established.
                accepted.send(b"H")
                received = client_tls.recv(1)
                assert received == b"H"
                accepted.close()
            finally:
                client_tls.close()
        finally:
            try:
                client_raw.close()
            except OSError:
                pass
            listener.close()


class TestCpListenTlsRefusesOnRp2:
    """``cp_adapter.listen_tls`` short-circuits on RP2040 / RP2350 platforms.

    Lives here (not in the cross-runtime ``test_factories.py``) because
    the assertions monkeypatch ``sys.platform`` — on MicroPython /
    CircuitPython unix-ports ``sys`` is read-only at the C level and
    ``setattr(sys, "platform", ...)`` raises ``AttributeError``.
    """

    def test_rp2040_platform_raises_unsupported(self, monkeypatch) -> None:
        from chumicro_sockets._adapters import cp as cp_adapter
        monkeypatch.setattr("sys.platform", "RP2040")
        with pytest.raises(UnsupportedSSLConfigError) as captured:
            cp_adapter.listen_tls(
                "0.0.0.0", 8443, context=object(), backlog=4, radio=object(),
            )
        assert "rp2" in str(captured.value).lower()

    def test_rp2350_platform_also_refused(self, monkeypatch) -> None:
        from chumicro_sockets._adapters import cp as cp_adapter
        monkeypatch.setattr("sys.platform", "RP2350")
        with pytest.raises(UnsupportedSSLConfigError):
            cp_adapter.listen_tls(
                "0.0.0.0", 8443, context=object(), backlog=4, radio=object(),
            )

    def test_non_rp2_platform_does_not_short_circuit(self, monkeypatch) -> None:
        from chumicro_sockets._adapters import cp as cp_adapter
        monkeypatch.setattr("sys.platform", "Espressif ESP32-S2")
        with pytest.raises(Exception) as captured:  # noqa: PT011, BLE001
            cp_adapter.listen_tls(
                "0.0.0.0", 8443, context=object(), backlog=4, radio=object(),
            )
        assert not isinstance(captured.value, UnsupportedSSLConfigError)
