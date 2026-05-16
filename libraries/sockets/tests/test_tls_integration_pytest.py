"""End-to-end TLS integration test on CPython.

Spins up a TLS echo server on a loopback port using a self-signed
certificate generated at test time, then exercises
``tls_client_socket`` + ``ssl_context_with_ca`` against it.  Real
``ssl.SSLContext.wrap_socket`` handshake, no monkey-patching — the
test catches regressions where the call shape (server_hostname,
load_verify_locations cadata) drifts from what stdlib expects.

The CPython adapter path is the same shape MP-mbedTLS and CP native
wifi take (``context.wrap_socket(socket, server_hostname=host)``),
so a passing handshake here establishes the contract every adapter
implements.

If your CPython doesn't ship the ``ssl`` module (highly unusual)
the whole class is skipped.
"""

from __future__ import annotations

#: CPython-only lane (pytest fixtures / host stdlib); not cross-runtime.
__chumicro_runtimes__ = ("cpython",)

import socket
import ssl
import threading
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from chumicro_sockets import ssl_context_with_ca, tls_client_socket

if TYPE_CHECKING:  # pragma: no cover — type-only
    from collections.abc import Iterator


# ---------------------------------------------------------------------------
# Self-signed cert generation
# ---------------------------------------------------------------------------


def _have_cryptography() -> bool:
    try:
        import cryptography  # type: ignore[import-not-found]  # noqa: F401  # noqa: PLC0415
    except ImportError:
        return False
    return True


@pytest.fixture(scope="module")
def self_signed_cert(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Build a self-signed cert + private key for ``localhost`` + 127.0.0.1.

    Uses the ``cryptography`` library if available (the chumicro venv
    pulls it via ruamel.yaml's transitive deps).  Falls back to a
    pre-baked stub set if cryptography isn't installed (skip the test
    suite in that case).
    """
    if not _have_cryptography():
        pytest.skip("cryptography not available — skipping live TLS test")

    from datetime import datetime, timedelta  # noqa: PLC0415

    from cryptography import x509  # noqa: PLC0415
    from cryptography.hazmat.primitives import hashes, serialization  # noqa: PLC0415
    from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: PLC0415
    from cryptography.x509.oid import NameOID  # noqa: PLC0415

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=5))
        .not_valid_after(datetime.now(UTC) + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(__import__("ipaddress").IPv4Address("127.0.0.1")),
            ]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )

    workdir = tmp_path_factory.mktemp("tls-cert")
    cert_path = workdir / "cert.pem"
    key_path = workdir / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ),
    )
    return cert_path, key_path


# ---------------------------------------------------------------------------
# TLS echo server fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def tls_echo_server(
    self_signed_cert: tuple[Path, Path],
) -> Iterator[tuple[str, int]]:
    """Spin up a one-shot TLS echo server.  Yields (host, port)."""
    cert_path, key_path = self_signed_cert
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=cert_path, keyfile=key_path)

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    host, port = listener.getsockname()

    stop_event = threading.Event()

    def _server_loop() -> None:
        listener.settimeout(0.5)
        while not stop_event.is_set():
            try:
                raw, _client_address = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            try:
                ssock = context.wrap_socket(raw, server_side=True)
            except ssl.SSLError:
                raw.close()
                continue
            try:
                while True:
                    chunk = ssock.recv(1024)
                    if not chunk:
                        break
                    ssock.sendall(chunk)  # echo
            except (ssl.SSLError, OSError):
                pass
            finally:
                try:
                    ssock.unwrap()
                except (ssl.SSLError, OSError):
                    pass
                ssock.close()

    server_thread = threading.Thread(target=_server_loop, daemon=True)
    server_thread.start()
    try:
        yield host, port
    finally:
        stop_event.set()
        listener.close()
        server_thread.join(timeout=2.0)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTLSAgainstSelfSignedServer:
    def test_handshake_with_custom_ca(
        self,
        tls_echo_server: tuple[str, int],
        self_signed_cert: tuple[Path, Path],
    ) -> None:
        """tls_client_socket(context=ssl_context_with_ca(...)) succeeds.

        Confirms ssl_context_with_ca actually configures the trust
        anchor — without it, TLS would fail with a verify error on a
        self-signed cert.
        """
        host, port = tls_echo_server
        cert_path, _ = self_signed_cert
        context = ssl_context_with_ca(cert_path.read_bytes())
        sock = tls_client_socket(host, port, context=context)
        try:
            sock.send(b"hello-tls\n")
            buffer = bytearray(64)
            # Loop briefly in case the echo arrives split across reads.
            chunks = bytearray()
            for _attempt in range(10):
                got = sock.recv_into(buffer, 64)
                if got == 0:
                    break
                chunks.extend(buffer[:got])
                if b"hello-tls\n" in chunks:
                    break
            assert b"hello-tls\n" in chunks
        finally:
            sock.close()

    def test_default_context_rejects_self_signed(
        self,
        tls_echo_server: tuple[str, int],
    ) -> None:
        """Without the custom CA, the handshake rejects the self-signed cert."""
        host, port = tls_echo_server
        with pytest.raises((ssl.SSLError, ssl.SSLCertVerificationError)):
            tls_client_socket(host, port)

    def test_send_recv_round_trip_multiple_messages(
        self,
        tls_echo_server: tuple[str, int],
        self_signed_cert: tuple[Path, Path],
    ) -> None:
        """Sustained TLS chatter: three round-trips on the same connection."""
        host, port = tls_echo_server
        cert_path, _ = self_signed_cert
        context = ssl_context_with_ca(cert_path.read_bytes())
        sock = tls_client_socket(host, port, context=context)
        try:
            for index in range(3):
                payload = f"chunk-{index}\n".encode()
                sock.send(payload)
                buffer = bytearray(32)
                received = bytearray()
                for _attempt in range(10):
                    got = sock.recv_into(buffer, 32)
                    if got == 0:
                        break
                    received.extend(buffer[:got])
                    if payload in received:
                        break
                assert payload in received
        finally:
            sock.close()
