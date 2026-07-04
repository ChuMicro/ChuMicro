"""End-to-end TLS integration test on CPython.

Spins up a TLS echo server on a loopback port using a self-signed
certificate generated at test time, then drives
``connector(tls=True)`` + ``ssl_context_with_ca`` against it to a
terminal state.  Real ``ssl.SSLContext.wrap_socket`` handshake, no
monkey-patching — the test catches regressions where the call shape
(server_hostname, load_verify_locations cadata) drifts from what
stdlib expects.

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

import errno
import select
import socket
import ssl
import threading
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from chumicro_sockets import connector, ssl_context_with_ca

if TYPE_CHECKING:  # pragma: no cover — type-only
    from collections.abc import Iterator


def _connect_tls(host: str, port: int, context: object | None = None) -> object:
    """Drive ``connector(tls=True)`` to terminal; return the ready socket.

    Between ticks, ``select.select`` parks briefly on the connector's
    declared ``io_interest`` — the same wait shape ``Runner.wait``
    uses in production.  This makes the helper a live busy-poll
    regression check: mid-handshake the connector narrows its interest
    to the direction the last ``SSLWant*`` signal named, and a
    connector that kept advertising write interest on the
    always-writable socket would spin through the 200-tick budget in
    microseconds and trip the stuck-state assert below.  Raises the
    connector's ``last_error`` on failure so callers see the same
    exception the handshake produced.
    """
    tls_connector = connector(host, port, tls=True, context=context)
    for _ in range(200):
        if tls_connector.state in ("ready", "failed"):
            break
        io_sock = tls_connector.io_socket
        if io_sock is not None:
            interest = tls_connector.io_interest(0)
            read_list = [io_sock] if interest & 1 else []
            write_list = [io_sock] if interest & 2 else []
            select.select(read_list, write_list, [], 0.05)
        tls_connector.tick(0)
    if tls_connector.state == "failed":
        raise tls_connector.last_error
    assert tls_connector.state == "ready", (
        f"connector stuck in {tls_connector.state!r}"
    )
    return tls_connector.socket


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
        """connector(tls=True, context=ssl_context_with_ca(...)) reaches ready.

        Confirms ssl_context_with_ca actually configures the trust
        anchor — without it, TLS would fail with a verify error on a
        self-signed cert.
        """
        host, port = tls_echo_server
        cert_path, _ = self_signed_cert
        context = ssl_context_with_ca(cert_path.read_bytes())
        sock = _connect_tls(host, port, context)
        # The connector hands back a non-blocking socket; this test's
        # echo round-trip wants blocking reads.
        sock.setblocking(True)
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

    def test_nonblocking_recv_into_reports_eagain_not_sslwant(
        self,
        tls_echo_server: tuple[str, int],
        self_signed_cert: tuple[Path, Path],
    ) -> None:
        """A non-blocking TLS recv with no data pending raises
        ``OSError(EAGAIN)``, not ``ssl.SSLWantReadError`` — the adapter
        normalizes the would-block signal so tick-driven recv loops
        (and websockets / mqtt over TLS) branch on EAGAIN uniformly."""
        host, port = tls_echo_server
        cert_path, _ = self_signed_cert
        context = ssl_context_with_ca(cert_path.read_bytes())
        sock = _connect_tls(host, port, context)
        try:
            # The raw SSLSocket stays reachable on ``.sock`` — the runner
            # registers that pollable, not the wrapper.
            assert isinstance(sock.sock, ssl.SSLSocket)
            sock.setblocking(False)
            buffer = bytearray(64)
            # We sent nothing, so the echo server has nothing to return;
            # a raw non-blocking SSLSocket would raise SSLWantReadError.
            with pytest.raises(OSError) as captured:
                sock.recv_into(buffer, 64)
            assert captured.value.args[0] == errno.EAGAIN
            assert not isinstance(captured.value, ssl.SSLWantReadError)
        finally:
            sock.close()

    def test_default_context_rejects_self_signed(
        self,
        tls_echo_server: tuple[str, int],
    ) -> None:
        """Without the custom CA, the handshake rejects the self-signed cert."""
        host, port = tls_echo_server
        with pytest.raises((ssl.SSLError, ssl.SSLCertVerificationError)):
            _connect_tls(host, port)

    def test_send_recv_round_trip_multiple_messages(
        self,
        tls_echo_server: tuple[str, int],
        self_signed_cert: tuple[Path, Path],
    ) -> None:
        """Sustained TLS chatter: three round-trips on the same connection."""
        host, port = tls_echo_server
        cert_path, _ = self_signed_cert
        context = ssl_context_with_ca(cert_path.read_bytes())
        sock = _connect_tls(host, port, context)
        sock.setblocking(True)
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


class _FakeSSLSocket:
    """Minimal ssl.SSLSocket stand-in for the wrapper unit tests.

    ``recv`` / ``recv_into`` / ``send`` raise a scripted ``SSLWant*``
    error or return a scripted value; the forwarded lifecycle methods
    record that they fired.
    """

    def __init__(self, *, raise_error=None) -> None:
        self._raise_error = raise_error
        self.blocking: bool | None = None
        self.timeout: float | None = None
        self.closed = False
        self.sent = bytearray()

    def recv(self, nbytes: int) -> bytes:
        if self._raise_error is not None:
            raise self._raise_error
        return b"x" * nbytes

    def recv_into(self, buffer: bytearray, nbytes: int = 0) -> int:
        if self._raise_error is not None:
            raise self._raise_error
        count = nbytes if nbytes else len(buffer)
        buffer[:count] = b"a" * count
        return count

    def send(self, data: bytes) -> int:
        if self._raise_error is not None:
            raise self._raise_error
        self.sent.extend(data)
        return len(data)

    def setblocking(self, flag: bool) -> None:
        self.blocking = flag

    def settimeout(self, seconds: float | None) -> None:
        self.timeout = seconds

    def close(self) -> None:
        self.closed = True


class TestCPythonTLSSocketWrapper:
    """Unit checks of ``_CPythonTLSSocketWrapper``'s SSLWant* -> EAGAIN translation."""

    def _wrapper(self, inner: _FakeSSLSocket) -> object:
        from chumicro_sockets._adapters.cpython import (  # noqa: PLC0415
            _CPythonTLSSocketWrapper,
        )

        return _CPythonTLSSocketWrapper(inner)

    def test_recv_translates_want_read_to_eagain(self) -> None:
        wrapper = self._wrapper(_FakeSSLSocket(raise_error=ssl.SSLWantReadError()))
        with pytest.raises(OSError) as captured:
            wrapper.recv(16)
        assert captured.value.args[0] == errno.EAGAIN

    def test_recv_into_translates_want_write_to_eagain(self) -> None:
        wrapper = self._wrapper(_FakeSSLSocket(raise_error=ssl.SSLWantWriteError()))
        with pytest.raises(OSError) as captured:
            wrapper.recv_into(bytearray(8), 8)
        assert captured.value.args[0] == errno.EAGAIN

    def test_send_translates_want_write_to_eagain(self) -> None:
        wrapper = self._wrapper(_FakeSSLSocket(raise_error=ssl.SSLWantWriteError()))
        with pytest.raises(OSError) as captured:
            wrapper.send(b"payload")
        assert captured.value.args[0] == errno.EAGAIN

    def test_passthrough_and_lifecycle_forwarding(self) -> None:
        inner = _FakeSSLSocket()
        wrapper = self._wrapper(inner)
        assert wrapper.recv(4) == b"xxxx"
        assert wrapper.send(b"hi") == 2
        # Default-nbytes path fills the whole buffer; explicit-nbytes clamps.
        buffer = bytearray(4)
        assert wrapper.recv_into(buffer) == 4
        assert wrapper.recv_into(buffer, 2) == 2
        wrapper.setblocking(False)
        wrapper.settimeout(1.5)
        wrapper.close()
        assert inner.blocking is False
        assert inner.timeout == 1.5
        assert inner.closed is True
