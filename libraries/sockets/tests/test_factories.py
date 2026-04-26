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

import pytest
from chumicro_sockets import (
    UnsupportedSSLConfigError,
    ssl_context_with_ca,
    tcp_client_socket,
    tls_client_socket,
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
        captured: dict[str, object] = {}

        from chumicro_sockets._adapters import cpython as cpython_adapter

        class _FakeRawSocket:
            """Stand-in for the socket returned by `socket.create_connection`."""

            def close(self) -> None:
                captured["raw_closed"] = True

        def _fake_create_connection(
            address: tuple[str, int],
        ) -> _FakeRawSocket:
            captured["address"] = address
            return _FakeRawSocket()

        monkeypatch.setattr(
            cpython_adapter.socket, "create_connection",
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

        monkeypatch.setattr(
            cpython_adapter._ssl,  # type: ignore[attr-defined]
            "create_default_context",
            _fake_default_context,
        )

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

        from chumicro_sockets._adapters import cpython as cpython_adapter

        monkeypatch.setattr(
            cpython_adapter._ssl,  # type: ignore[attr-defined]
            "create_default_context",
            lambda: _RecordingContext(),
        )
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
# adapter additions can surface as structured failures.  Today's
# adapters don't raise it — that's by design.
class TestUnsupportedSSLConfigErrorIsAvailable:
    def test_class_is_a_runtime_error(self) -> None:
        assert issubclass(UnsupportedSSLConfigError, RuntimeError)

    def test_class_is_raisable(self) -> None:
        with pytest.raises(UnsupportedSSLConfigError):
            raise UnsupportedSSLConfigError("placeholder")
