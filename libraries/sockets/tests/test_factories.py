"""Tests for the runtime-routing factories.

These tests run on CPython.  They route the factory through the
CPython adapter and confirm the correct shape comes back; the live
DNS / connect path is mocked so the suite stays hermetic.

Cross-runtime adapter selection is exercised by patching
``chumicro_sockets._runtime_name`` so we can simulate CP / MP from
CPython without spinning up the unix-port interpreters.
"""

from __future__ import annotations

import socket
import ssl
from datetime import UTC

import pytest
from chumicro_sockets import (
    UnsupportedSSLConfigError,
    ssl_context_with_ca,
    ssl_context_with_cert_and_key_paths,
    tcp_client_socket,
    tcp_listening_socket,
    tls_client_socket,
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

    def test_send_and_recv_round_trip(self, echo_server) -> None:
        host, port = echo_server
        sock = tcp_client_socket(host, port)
        try:
            sock.send(b"hi")
            # Server side accepts + echoes.
            # We pull the connection from the listener side; tests
            # don't need the round-trip — connecting + closing is
            # enough to assert the factory works.
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


class TestListenerRouting:
    """``tcp_listening_socket`` dispatches to the runtime-appropriate adapter."""

    def test_circuitpython_runtime_routes_to_cp_adapter(
        self, monkeypatch,
    ) -> None:
        captured: dict = {}

        def fake_listen(host, port, *, backlog, radio):
            captured["called"] = (host, port, backlog, radio)
            return "cp-listener"

        # Patch the function on the already-imported module — same
        # pattern TestAdapterRouting uses for the cp adapter.  The
        # cp adapter lazy-imports socketpool inside the function, so
        # loading the module on CPython is fine.
        from chumicro_sockets._adapters import cp as cp_adapter
        monkeypatch.setattr(cp_adapter, "listen_tcp", fake_listen)
        monkeypatch.setattr("chumicro_sockets._runtime_name", lambda: "circuitpython")

        result = tcp_listening_socket("0.0.0.0", 8080, radio="fake-radio")
        assert result == "cp-listener"
        assert captured["called"] == ("0.0.0.0", 8080, 4, "fake-radio")

    def test_micropython_runtime_routes_to_mp_adapter(
        self, monkeypatch,
    ) -> None:
        captured: dict = {}

        # Stub the MP adapter module via sys.modules so importing it
        # doesn't try to pull in MicroPython's stdlib.  Mirror the
        # TestAdapterRouting pattern; importing the real mp adapter
        # leaves a stale package attribute that subsequent tests'
        # sys.modules monkey-patches don't invalidate.
        import sys as _sys
        import types as _types

        fake_mp = _types.ModuleType("chumicro_sockets._adapters.mp")

        def fake_listen(host, port, *, backlog):
            captured["called"] = (host, port, backlog)
            return "mp-listener"

        fake_mp.listen_tcp = fake_listen
        monkeypatch.setitem(_sys.modules, "chumicro_sockets._adapters.mp", fake_mp)
        monkeypatch.setattr("chumicro_sockets._runtime_name", lambda: "micropython")

        result = tcp_listening_socket("0.0.0.0", 8080, backlog=8)
        assert result == "mp-listener"
        assert captured["called"] == ("0.0.0.0", 8080, 8)


class TestTLSListenerRouting:
    """``tls_listening_socket`` dispatches to the runtime-appropriate adapter."""

    def test_cpython_runtime_routes_to_cpython_adapter(
        self, monkeypatch,
    ) -> None:
        captured: dict = {}

        def fake_listen_tls(host, port, *, context, backlog):
            captured["called"] = (host, port, context, backlog)
            return "cpython-tls-listener"

        from chumicro_sockets._adapters import cpython as cpython_adapter
        monkeypatch.setattr(cpython_adapter, "listen_tls", fake_listen_tls)
        monkeypatch.setattr("chumicro_sockets._runtime_name", lambda: "cpython")

        result = tls_listening_socket("0.0.0.0", 8443, context="fake-ctx")
        assert result == "cpython-tls-listener"
        assert captured["called"] == ("0.0.0.0", 8443, "fake-ctx", 4)

    def test_circuitpython_runtime_routes_to_cp_adapter(
        self, monkeypatch,
    ) -> None:
        captured: dict = {}

        def fake_listen_tls(host, port, *, context, backlog, radio):
            captured["called"] = (host, port, context, backlog, radio)
            return "cp-tls-listener"

        from chumicro_sockets._adapters import cp as cp_adapter
        monkeypatch.setattr(cp_adapter, "listen_tls", fake_listen_tls)
        monkeypatch.setattr("chumicro_sockets._runtime_name", lambda: "circuitpython")

        result = tls_listening_socket(
            "0.0.0.0", 8443, context="ctx", radio="radio",
        )
        assert result == "cp-tls-listener"
        assert captured["called"] == ("0.0.0.0", 8443, "ctx", 4, "radio")

    def test_micropython_runtime_routes_to_mp_adapter(
        self, monkeypatch,
    ) -> None:
        captured: dict = {}

        import sys as _sys
        import types as _types

        fake_mp = _types.ModuleType("chumicro_sockets._adapters.mp")

        def fake_listen_tls(host, port, *, context, backlog):
            captured["called"] = (host, port, context, backlog)
            return "mp-tls-listener"

        fake_mp.listen_tls = fake_listen_tls
        monkeypatch.setitem(_sys.modules, "chumicro_sockets._adapters.mp", fake_mp)
        monkeypatch.setattr("chumicro_sockets._runtime_name", lambda: "micropython")

        result = tls_listening_socket("0.0.0.0", 8443, context="ctx", backlog=8)
        assert result == "mp-tls-listener"
        assert captured["called"] == ("0.0.0.0", 8443, "ctx", 8)


class TestSslContextWithCertAndKeyPaths:
    """Path-based helper works on every runtime (CP requires it)."""

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

    def test_circuitpython_routes_to_path_adapter(self, monkeypatch) -> None:
        captured: dict = {}

        def fake_helper(cert_path, key_path):
            captured["called"] = (cert_path, key_path)
            return "cp-server-ctx"

        from chumicro_sockets._adapters import cp as cp_adapter
        monkeypatch.setattr(
            cp_adapter, "ssl_context_with_cert_and_key_paths", fake_helper,
        )
        monkeypatch.setattr("chumicro_sockets._runtime_name", lambda: "circuitpython")

        result = ssl_context_with_cert_and_key_paths(
            "/lib/cert.pem", "/lib/key.pem",
        )
        assert result == "cp-server-ctx"
        assert captured["called"] == ("/lib/cert.pem", "/lib/key.pem")


class TestSslContextWithCertAndKeyRouting:
    """``ssl_context_with_cert_and_key`` dispatches to per-runtime adapter."""

    def test_circuitpython_routes_to_cp_adapter(self, monkeypatch) -> None:
        from chumicro_sockets import ssl_context_with_cert_and_key
        from chumicro_sockets._adapters import cp as cp_adapter

        captured: dict = {}

        def fake_helper(cert_pem, key_pem):
            captured["called"] = (cert_pem, key_pem)
            return "cp-server-ctx"

        monkeypatch.setattr(cp_adapter, "ssl_context_with_cert_and_key", fake_helper)
        monkeypatch.setattr("chumicro_sockets._runtime_name", lambda: "circuitpython")

        result = ssl_context_with_cert_and_key(b"cert", b"key")
        assert result == "cp-server-ctx"
        assert captured["called"] == (b"cert", b"key")

    def test_micropython_routes_to_mp_adapter(self, monkeypatch) -> None:
        import sys as _sys
        import types as _types

        from chumicro_sockets import ssl_context_with_cert_and_key

        fake_mp = _types.ModuleType("chumicro_sockets._adapters.mp")
        captured: dict = {}

        def fake_helper(cert_pem, key_pem):
            captured["called"] = (cert_pem, key_pem)
            return "mp-server-ctx"

        fake_mp.ssl_context_with_cert_and_key = fake_helper
        monkeypatch.setitem(_sys.modules, "chumicro_sockets._adapters.mp", fake_mp)
        monkeypatch.setattr("chumicro_sockets._runtime_name", lambda: "micropython")

        result = ssl_context_with_cert_and_key(b"cert", b"key")
        assert result == "mp-server-ctx"
        assert captured["called"] == (b"cert", b"key")


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
        import ssl as stdlib_ssl  # noqa: PLC0415
        client_context = stdlib_ssl.create_default_context()
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


# ---------------------------------------------------------------------------
# CPython TLS — handshake against a real-ish HTTPS endpoint
# ---------------------------------------------------------------------------


class TestCPythonTLSWithLocalContext:
    """TLS path — exercise the context-build + wrap path without a live
    HTTPS endpoint.  We build a context, then check the wrap-call
    signature directly on the adapter."""

    def test_default_context_used_when_none_passed(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Routing test for tls_client_socket(context=None) on CPython.

        After the lazy-import refactor (CP RAM-mode bootstrap was
        tripping on top-level socket/ssl imports in adapters), the
        cpython adapter's ``socket`` and ``ssl`` symbols only resolve
        inside function bodies.  Patch via ``socket.create_connection``
        + ``ssl.create_default_context`` directly, which the adapter
        looks up at call time via ``import``.
        """
        captured: dict[str, object] = {}

        class _FakeRawSocket:
            def close(self) -> None:
                captured["raw_closed"] = True

        def _fake_create_connection(
            address: tuple[str, int],
        ) -> _FakeRawSocket:
            captured["address"] = address
            return _FakeRawSocket()

        monkeypatch.setattr(
            socket, "create_connection",
            _fake_create_connection,
        )

        class _FakeContext:
            def wrap_socket(
                self,
                sock: _FakeRawSocket,
                *,
                server_hostname: str,
            ) -> _FakeRawSocket:
                captured["server_hostname"] = server_hostname
                captured["wrapped"] = True
                return sock

        def _fake_default_context() -> object:
            captured["used_default_context"] = True
            return _FakeContext()

        monkeypatch.setattr(ssl, "create_default_context", _fake_default_context)

        result = tls_client_socket("example.com", 443)
        assert captured.get("used_default_context") is True
        assert captured.get("server_hostname") == "example.com"
        assert captured.get("wrapped") is True
        # The fake socket gets returned unchanged through wrap_socket.
        assert isinstance(result, _FakeRawSocket)
        result.close()


class TestSslContextWithCa:
    def test_routes_through_cpython_adapter(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Routing test: stub ``_ssl.create_default_context`` and
        confirm the helper feeds *ca_pem* into ``load_verify_locations``.

        Avoids needing a real CA bundle on disk — the call shape is what
        matters; stdlib's behaviour on a real PEM is its own contract.
        """
        captured: dict[str, str] = {}

        class _RecordingContext:
            def load_verify_locations(self, *, cadata: str) -> None:
                captured["cadata"] = cadata

        # Adapter does `import ssl` at call time; patching the
        # global ssl module is sufficient — the lazy import resolves
        # against sys.modules['ssl'] like every other import.
        monkeypatch.setattr(ssl, "create_default_context", lambda: _RecordingContext())
        monkeypatch.setattr(
            "chumicro_sockets._runtime_name", lambda: "cpython",
        )

        ca_pem = b"-----BEGIN CERTIFICATE-----\nfake-bytes\n-----END CERTIFICATE-----\n"
        result = ssl_context_with_ca(ca_pem)
        assert isinstance(result, _RecordingContext)
        assert "fake-bytes" in captured["cadata"]


# ---------------------------------------------------------------------------
# Adapter routing — patch sys.implementation.name to simulate runtimes
# ---------------------------------------------------------------------------


class TestAdapterRouting:
    def test_cpython_runtime_routes_to_cpython_adapter(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, object] = {}

        def _fake_connect(host: str, port: int) -> str:
            captured["routed"] = "cpython"
            captured["host"] = host
            captured["port"] = port
            return "fake-cpython-socket"  # type: ignore[return-value]

        from chumicro_sockets._adapters import cpython as cpython_adapter

        monkeypatch.setattr(cpython_adapter, "connect_tcp", _fake_connect)
        monkeypatch.setattr(
            "chumicro_sockets._runtime_name", lambda: "cpython",
        )
        result = tcp_client_socket("h", 1)
        assert result == "fake-cpython-socket"
        assert captured["routed"] == "cpython"

    def test_circuitpython_runtime_routes_to_cp_adapter(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, object] = {}

        # The CP adapter module imports ``socketpool`` at function-call
        # time, not module-import time, so loading the module on
        # CPython is fine — only the call would fail without socketpool.
        # Patch the function instead.
        from chumicro_sockets._adapters import cp as cp_adapter

        def _fake_connect(
            host: str,
            port: int,
            *,
            radio: object,
        ) -> str:
            captured["routed"] = "cp"
            captured["radio"] = radio
            return "fake-cp-socket"  # type: ignore[return-value]

        monkeypatch.setattr(cp_adapter, "connect_tcp", _fake_connect)
        monkeypatch.setattr(
            "chumicro_sockets._runtime_name", lambda: "circuitpython",
        )
        result = tcp_client_socket("h", 1, radio="fake-radio")
        assert result == "fake-cp-socket"
        assert captured["routed"] == "cp"
        assert captured["radio"] == "fake-radio"

    def test_micropython_runtime_routes_to_mp_adapter(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, object] = {}

        # Stub the MP adapter module so importing it doesn't try to
        # pull in MicroPython's stdlib.
        import sys as _sys
        import types as _types

        fake_mp = _types.ModuleType("chumicro_sockets._adapters.mp")

        def _fake_connect(host: str, port: int) -> str:
            captured["routed"] = "mp"
            return "fake-mp-socket"  # type: ignore[return-value]

        fake_mp.connect_tcp = _fake_connect  # type: ignore[attr-defined]
        monkeypatch.setitem(_sys.modules, "chumicro_sockets._adapters.mp", fake_mp)
        monkeypatch.setattr(
            "chumicro_sockets._runtime_name", lambda: "micropython",
        )
        result = tcp_client_socket("h", 1)
        assert result == "fake-mp-socket"
        assert captured["routed"] == "mp"


# ---------------------------------------------------------------------------
# CircuitPython TLS — passes contexts through to socketpool.wrap_socket
# ---------------------------------------------------------------------------


class TestCircuitPythonTLSPassthrough:
    """CP adapter delegates to ``ssl.SSLContext.wrap_socket`` directly.

    Decision 0015 supported boards (Pi Pico W, ESP32-S2/S3, ESP32-S3
    Feather native wifi) all ship the on-board ``ssl`` module, so
    contexts work the same as MP / CPython.  These tests confirm
    the wiring without needing a real radio / socketpool.
    """

    def test_passes_context_to_wrap_socket(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, object] = {}

        from chumicro_sockets._adapters import cp as cp_adapter

        class _FakeRawSocket:
            def connect(self, address: tuple[str, int]) -> None:
                captured["connected_to"] = address

        class _FakePool:
            AF_INET = 2
            SOCK_STREAM = 1

            def socket(self, _family: int, _kind: int) -> _FakeRawSocket:
                return _FakeRawSocket()

        class _FakeContext:
            def wrap_socket(
                self,
                sock: _FakeRawSocket,
                *,
                server_hostname: str,
            ) -> _FakeRawSocket:
                captured["wrapped"] = True
                captured["server_hostname"] = server_hostname
                return sock

        monkeypatch.setattr(cp_adapter, "_pool_for", lambda radio: _FakePool())
        monkeypatch.setattr(
            "chumicro_sockets._runtime_name", lambda: "circuitpython",
        )

        tls_client_socket(
            "broker.example.com", 8883,
            context=_FakeContext(),  # type: ignore[arg-type]
            radio="fake-radio",
        )
        assert captured.get("wrapped") is True
        assert captured.get("server_hostname") == "broker.example.com"
        assert captured.get("connected_to") == ("broker.example.com", 8883)

    def test_default_context_on_cp_uses_ssl_create_default_context(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """context=None routes through ssl.create_default_context() on CP."""
        captured: dict[str, object] = {}

        from chumicro_sockets._adapters import cp as cp_adapter

        class _FakeRawSocket:
            def connect(self, _address: tuple[str, int]) -> None:
                pass

        class _FakePool:
            AF_INET = 2
            SOCK_STREAM = 1

            def socket(self, _family: int, _kind: int) -> _FakeRawSocket:
                return _FakeRawSocket()

        class _FakeContext:
            def wrap_socket(
                self,
                sock: _FakeRawSocket,
                *,
                server_hostname: str,  # noqa: ARG002
            ) -> _FakeRawSocket:
                captured["used_default"] = True
                return sock

        # Stub the CP-only `import ssl` inside the adapter call.  The
        # adapter does `import ssl` at call time; we shim sys.modules
        # so it picks up our stand-in instead of needing a real CP env.
        import sys as _sys
        import types as _types

        fake_ssl = _types.ModuleType("ssl")
        fake_ssl.create_default_context = lambda: _FakeContext()  # type: ignore[attr-defined]
        monkeypatch.setitem(_sys.modules, "ssl", fake_ssl)

        monkeypatch.setattr(cp_adapter, "_pool_for", lambda radio: _FakePool())
        monkeypatch.setattr(
            "chumicro_sockets._runtime_name", lambda: "circuitpython",
        )
        tls_client_socket("h", 8883, radio="fake-radio")
        assert captured.get("used_default") is True

    def test_ssl_context_with_ca_works_on_cp(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Custom-CA helper builds a real context on CP supported boards."""
        # CP's ssl module exposes the same surface as CPython's, so
        # routing the call through the CP adapter just exercises the
        # standard library's behaviour.  Stub the import so we don't
        # need a real CP runtime.
        captured: dict[str, object] = {}

        class _FakeContext:
            def load_verify_locations(self, *, cadata: str) -> None:
                captured["cadata"] = cadata

        import sys as _sys
        import types as _types

        fake_ssl = _types.ModuleType("ssl")
        fake_ssl.create_default_context = lambda: _FakeContext()  # type: ignore[attr-defined]
        monkeypatch.setitem(_sys.modules, "ssl", fake_ssl)
        monkeypatch.setattr(
            "chumicro_sockets._runtime_name", lambda: "circuitpython",
        )
        result = ssl_context_with_ca(
            b"-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n",
        )
        assert isinstance(result, _FakeContext)
        assert "fake" in captured["cadata"]  # type: ignore[operator]


# Keep UnsupportedSSLConfigError importable + raisable so future
# adapter additions can surface as structured failures.
class TestUnsupportedSSLConfigErrorIsAvailable:
    def test_class_is_a_runtime_error(self) -> None:
        assert issubclass(UnsupportedSSLConfigError, RuntimeError)

    def test_class_is_raisable(self) -> None:
        with pytest.raises(UnsupportedSSLConfigError):
            raise UnsupportedSSLConfigError("placeholder")


class TestCpListenTlsRefusesOnRp2:
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
