"""Tests for the MicroPython adapter, exercised on CPython.

The MP adapter imports ``socket`` and ``ssl`` at module-load time, so
testing it from CPython means stubbing both modules in ``sys.modules``,
reloading the adapter, and calling its functions against the stubs.
That brings the device-only code paths into coverage without needing
to actually spin up a MicroPython unix-port.

Real cross-runtime coverage (against a live MP unix-port) happens via
``run.py test-micropython``; these tests are the host-side
complement that catches regressions in the call shapes we expect MP
to expose.
"""

from __future__ import annotations

import importlib
import sys
import types
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:  # pragma: no cover — type-only
    from collections.abc import Iterator


@pytest.fixture
def mp_adapter() -> Iterator[types.ModuleType]:
    """Stub ``socket`` + ``ssl`` and yield a freshly-reloaded MP adapter.

    Captures sent calls into ``adapter._calls`` (we add the attribute
    on the stub-side socket module) so individual tests can assert
    against it.  Restores the original modules on teardown.
    """

    real_socket = sys.modules.get("socket")
    real_ssl = sys.modules.get("ssl")

    fake_socket = types.ModuleType("socket")

    class _StubSocket:
        """Stub MP socket — bare minimum the wrapper attribute-copies."""

        def __init__(self, family: int, kind: int) -> None:
            self.family = family
            self.kind = kind
            self.connected_to: tuple[str, int] | None = None
            self.sent: bytearray = bytearray()
            self.recv_queue: list[bytes] = []
            self._closed: bool = False
            self._blocking: bool = True
            self._timeout: float | None = None
            self._fileno: int = 7

        def connect(self, address: tuple[str, int]) -> None:
            self.connected_to = address

        def send(self, data: bytes) -> int:
            self.sent.extend(data)
            return len(data)

        def recv(self, size: int) -> bytes:
            if not self.recv_queue:
                return b""
            chunk = self.recv_queue.pop(0)
            return chunk[:size] if len(chunk) > size else chunk

        def close(self) -> None:
            self._closed = True

        def setblocking(self, flag: bool) -> None:
            self._blocking = flag

        def settimeout(self, seconds: float | None) -> None:
            self._timeout = seconds

        def fileno(self) -> int:
            return self._fileno

    fake_socket.socket = _StubSocket  # type: ignore[attr-defined]
    fake_socket.getaddrinfo = (  # type: ignore[attr-defined]
        lambda host, port: [(2, 1, 0, "", (host, port))]
    )

    fake_ssl = types.ModuleType("ssl")

    class _StubContext:
        def __init__(self) -> None:
            self.cadata: bytes | str | None = None
            self.wrapped: list[tuple[object, str]] = []
            self.verify_mode: int | None = None

        def wrap_socket(
            self,
            sock: object,
            *,
            server_hostname: str,
        ) -> object:
            self.wrapped.append((sock, server_hostname))
            return sock

        def load_verify_locations(self, *, cadata: bytes | str) -> None:
            self.cadata = cadata

    def _stub_wrap_socket(sock: object, *, server_hostname: str) -> object:
        # Free-function form (older MP) — record on the module itself.
        fake_ssl._free_wrap_calls.append((sock, server_hostname))  # type: ignore[attr-defined]
        return sock

    fake_ssl.SSLContext = lambda _proto: _StubContext()  # type: ignore[attr-defined]
    fake_ssl.PROTOCOL_TLS_CLIENT = 1  # type: ignore[attr-defined]
    fake_ssl.CERT_REQUIRED = 2  # type: ignore[attr-defined]
    fake_ssl.CERT_NONE = 0  # type: ignore[attr-defined]
    fake_ssl.wrap_socket = _stub_wrap_socket  # type: ignore[attr-defined]
    fake_ssl._free_wrap_calls = []  # type: ignore[attr-defined]
    fake_ssl._StubContext = _StubContext  # type: ignore[attr-defined]

    sys.modules["socket"] = fake_socket
    sys.modules["ssl"] = fake_ssl
    # Drop a cached mp adapter (if any) so the reload picks up our stubs.
    sys.modules.pop("chumicro_sockets._adapters.mp", None)
    mp_module = importlib.import_module("chumicro_sockets._adapters.mp")

    yield mp_module

    # Teardown: restore originals + drop the stubbed adapter so the
    # next-test reload re-stubs cleanly.
    sys.modules.pop("chumicro_sockets._adapters.mp", None)
    if real_socket is not None:
        sys.modules["socket"] = real_socket
    else:  # pragma: no cover — only matters if the test was run before socket imported
        sys.modules.pop("socket", None)
    if real_ssl is not None:
        sys.modules["ssl"] = real_ssl
    else:  # pragma: no cover — only matters if the test was run before ssl imported
        sys.modules.pop("ssl", None)


class TestConnectTcp:
    def test_connects_via_getaddrinfo(self, mp_adapter: types.ModuleType) -> None:
        wrapper = mp_adapter.connect_tcp("broker.example.com", 1883)
        # The factory returns a _MpSocketWrapper around the raw stub.
        underlying = wrapper._sock  # type: ignore[attr-defined]
        assert underlying.connected_to == ("broker.example.com", 1883)
        assert underlying.family == 2
        assert underlying.kind == 1

    def test_recv_into_polyfilled_via_recv(
        self, mp_adapter: types.ModuleType,
    ) -> None:
        """MP rp2/esp32 stream sockets expose recv() but NOT recv_into.

        Live-board acceptance run on Lolin S2 MP + Pi Pico W MP confirmed
        ``AttributeError("'socket' object has no attribute 'recv_into'")``;
        the wrapper polyfills it.  This test pins the polyfill in place
        on every refactor.
        """
        wrapper = mp_adapter.connect_tcp("broker.example.com", 1883)
        underlying = wrapper._sock  # type: ignore[attr-defined]
        underlying.recv_queue.append(b"hello world")
        buffer = bytearray(32)
        nbytes_read = wrapper.recv_into(buffer, 32)
        assert nbytes_read == 11
        assert bytes(buffer[:11]) == b"hello world"

    def test_recv_into_default_uses_buffer_length(
        self, mp_adapter: types.ModuleType,
    ) -> None:
        wrapper = mp_adapter.connect_tcp("broker.example.com", 1883)
        underlying = wrapper._sock  # type: ignore[attr-defined]
        underlying.recv_queue.append(b"abc")
        buffer = bytearray(4)
        nbytes_read = wrapper.recv_into(buffer, 0)
        assert nbytes_read == 3
        assert bytes(buffer[:3]) == b"abc"

    def test_recv_into_zero_on_clean_close(
        self, mp_adapter: types.ModuleType,
    ) -> None:
        """Empty bytes from MP recv() means clean peer close — return 0."""
        wrapper = mp_adapter.connect_tcp("broker.example.com", 1883)
        # No queued data + recv() returns b"" by stub default.
        buffer = bytearray(8)
        nbytes_read = wrapper.recv_into(buffer, 8)
        assert nbytes_read == 0

    def test_send_close_setblocking_settimeout_fileno_forward(
        self, mp_adapter: types.ModuleType,
    ) -> None:
        """All other protocol methods are direct attribute forwards."""
        wrapper = mp_adapter.connect_tcp("broker.example.com", 1883)
        underlying = wrapper._sock  # type: ignore[attr-defined]
        wrapper.send(b"ping")
        assert bytes(underlying.sent) == b"ping"
        wrapper.setblocking(False)
        assert underlying._blocking is False
        wrapper.settimeout(2.5)
        assert underlying._timeout == 2.5
        assert wrapper.fileno() == 7
        wrapper.close()
        assert underlying._closed is True

    def test_missing_settimeout_falls_back_to_noop(
        self, mp_adapter: types.ModuleType,
    ) -> None:
        """Some MP SSLSocket impls drop settimeout — wrapper must not trip.

        Live-board acceptance on Lolin S2 ESP32 surfaced
        AttributeError("'SSLSocket' object has no attribute 'settimeout'");
        the wrapper falls back to a no-op stub.  This test pins that
        in place so future refactors can't reintroduce the hard error.
        """

        class _SSLishSocket:
            def __init__(self) -> None:
                self.sent: bytearray = bytearray()
                self._closed: bool = False

            def send(self, data: bytes) -> int:
                self.sent.extend(data)
                return len(data)

            def recv(self, _size: int) -> bytes:
                return b""

            def close(self) -> None:
                self._closed = True
            # No setblocking, no settimeout, no fileno — like the live
            # MP SSLSocket on the supported boards.

        wrapper = mp_adapter._MpSocketWrapper(_SSLishSocket())
        # No-ops succeed silently.
        wrapper.setblocking(False)
        wrapper.settimeout(2.5)
        assert wrapper.fileno() == -1  # "no real fd" sentinel
        wrapper.send(b"hi")
        wrapper.close()


class TestConnectTls:
    def test_default_uses_free_wrap_socket(self, mp_adapter: types.ModuleType) -> None:
        """`context=None` routes through the module-level ssl.wrap_socket
        — the older-MP-build call shape."""
        wrapper = mp_adapter.connect_tls("broker.example.com", 8883)
        wrap_calls = sys.modules["ssl"]._free_wrap_calls  # type: ignore[attr-defined]
        assert len(wrap_calls) == 1
        wrapped_sock, server_hostname = wrap_calls[0]
        # The wrapper holds the wrapped (TLS) socket; the wrap call
        # received the raw underlying socket.
        underlying = wrapper._sock  # type: ignore[attr-defined]
        assert wrapped_sock is underlying
        assert server_hostname == "broker.example.com"
        assert underlying.connected_to == ("broker.example.com", 8883)

    def test_explicit_context_uses_context_wrap(
        self, mp_adapter: types.ModuleType,
    ) -> None:
        """A pre-built SSLContext routes through `context.wrap_socket`."""
        stub_ssl = sys.modules["ssl"]
        context = stub_ssl._StubContext()  # type: ignore[attr-defined]
        wrapper = mp_adapter.connect_tls(
            "broker.example.com", 8883, context=context,
        )
        underlying = wrapper._sock  # type: ignore[attr-defined]
        assert len(context.wrapped) == 1
        wrapped_sock, server_hostname = context.wrapped[0]
        assert wrapped_sock is underlying
        assert server_hostname == "broker.example.com"
        # Free-form should NOT have fired.
        assert sys.modules["ssl"]._free_wrap_calls == []  # type: ignore[attr-defined]


class TestSslContextWithCa:
    def test_pem_input_converted_to_der_before_load(
        self, mp_adapter: types.ModuleType,
    ) -> None:
        """``ssl_context_with_ca`` accepts a PEM and passes DER bytes
        to ``load_verify_locations``.

        Empirical finding (Phase 7 TLS investigation, 2026-04-26):
        the rp2 MP build ships mbedTLS *without* ``MBEDTLS_PEM_PARSE_C``,
        so PEM input raises ``ValueError('invalid cert')`` on the
        Pi Pico W.  Converting to DER before passing is the
        lowest-common-denominator path that works on every MP port.
        Test pins the wrapper to the conversion behavior.
        """
        # Real-shape PEM: header / body / footer with valid base64 body.
        # ``b"\xde\xad\xbe\xef"`` → ``b"3q2+7w=="`` after base64.
        ca_pem = (
            b"-----BEGIN CERTIFICATE-----\n"
            b"3q2+7w==\n"
            b"-----END CERTIFICATE-----\n"
        )
        context = mp_adapter.ssl_context_with_ca(ca_pem)
        # The stub records whatever was passed to load_verify_locations;
        # PEM was decoded to raw DER bytes before the call.
        assert context.cadata == b"\xde\xad\xbe\xef"

    def test_str_pem_input_also_accepted(
        self, mp_adapter: types.ModuleType,
    ) -> None:
        """Public signature is ``str | bytes``; both shapes work."""
        ca_pem_str = (
            "-----BEGIN CERTIFICATE-----\n"
            "3q2+7w==\n"
            "-----END CERTIFICATE-----\n"
        )
        context = mp_adapter.ssl_context_with_ca(ca_pem_str)
        assert context.cadata == b"\xde\xad\xbe\xef"

    def test_pem_with_extra_whitespace_and_crlf(
        self, mp_adapter: types.ModuleType,
    ) -> None:
        """Tolerates CRLF, leading/trailing whitespace, and blank lines."""
        ca_pem = (
            b"  \r\n"
            b"-----BEGIN CERTIFICATE-----\r\n"
            b"  3q2+7w==  \r\n"
            b"\r\n"
            b"-----END CERTIFICATE-----\r\n"
        )
        context = mp_adapter.ssl_context_with_ca(ca_pem)
        assert context.cadata == b"\xde\xad\xbe\xef"

    def test_multi_cert_pem_bundle_concatenates_to_combined_der(
        self, mp_adapter: types.ModuleType,
    ) -> None:
        """Two BEGIN/END pairs back-to-back ship as concatenated DER.

        mbedTLS's ``mbedtls_x509_crt_parse`` walks a buffer of
        sequential DER certs natively, so emitting one big DER blob
        from two PEM blocks works on every MP port.
        """
        # First cert body decodes to b"\xde\xad\xbe\xef";
        # second cert body decodes to b"\xca\xfe\xba\xbe".
        ca_pem = (
            b"-----BEGIN CERTIFICATE-----\n"
            b"3q2+7w==\n"
            b"-----END CERTIFICATE-----\n"
            b"-----BEGIN CERTIFICATE-----\n"
            b"yv66vg==\n"
            b"-----END CERTIFICATE-----\n"
        )
        context = mp_adapter.ssl_context_with_ca(ca_pem)
        assert context.cadata == b"\xde\xad\xbe\xef\xca\xfe\xba\xbe"

    def test_default_verify_mode_is_cert_required(
        self, mp_adapter: types.ModuleType,
    ) -> None:
        """Loading a custom CA only makes sense if you intend to
        verify against it; default ``verify_mode`` is ``CERT_REQUIRED``
        so callers don't accidentally end up with blind trust."""
        import ssl as fake_ssl_module
        ca_pem = (
            b"-----BEGIN CERTIFICATE-----\n"
            b"3q2+7w==\n"
            b"-----END CERTIFICATE-----\n"
        )
        context = mp_adapter.ssl_context_with_ca(ca_pem)
        assert context.verify_mode == fake_ssl_module.CERT_REQUIRED
