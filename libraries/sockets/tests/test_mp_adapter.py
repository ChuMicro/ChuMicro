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
        def __init__(self, family: int, kind: int) -> None:
            self.family = family
            self.kind = kind
            self.connected_to: tuple[str, int] | None = None

        def connect(self, address: tuple[str, int]) -> None:
            self.connected_to = address

    fake_socket.socket = _StubSocket  # type: ignore[attr-defined]
    fake_socket.getaddrinfo = (  # type: ignore[attr-defined]
        lambda host, port: [(2, 1, 0, "", (host, port))]
    )

    fake_ssl = types.ModuleType("ssl")

    class _StubContext:
        def __init__(self) -> None:
            self.cadata: str | None = None
            self.wrapped: list[tuple[object, str]] = []

        def wrap_socket(
            self,
            sock: object,
            *,
            server_hostname: str,
        ) -> object:
            self.wrapped.append((sock, server_hostname))
            return sock

        def load_verify_locations(self, *, cadata: str) -> None:
            self.cadata = cadata

    def _stub_wrap_socket(sock: object, *, server_hostname: str) -> object:
        # Free-function form (older MP) — record on the module itself.
        fake_ssl._free_wrap_calls.append((sock, server_hostname))  # type: ignore[attr-defined]
        return sock

    fake_ssl.SSLContext = lambda _proto: _StubContext()  # type: ignore[attr-defined]
    fake_ssl.PROTOCOL_TLS_CLIENT = 1  # type: ignore[attr-defined]
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
        sock = mp_adapter.connect_tcp("broker.example.com", 1883)
        assert sock.connected_to == ("broker.example.com", 1883)
        assert sock.family == 2
        assert sock.kind == 1


class TestConnectTls:
    def test_default_uses_free_wrap_socket(self, mp_adapter: types.ModuleType) -> None:
        """`context=None` routes through the module-level ssl.wrap_socket
        — the older-MP-build call shape."""
        sock = mp_adapter.connect_tls("broker.example.com", 8883)
        # Free-function call recorded on the stub ssl module.
        wrap_calls = sys.modules["ssl"]._free_wrap_calls  # type: ignore[attr-defined]
        assert len(wrap_calls) == 1
        wrapped_sock, server_hostname = wrap_calls[0]
        assert wrapped_sock is sock
        assert server_hostname == "broker.example.com"
        assert sock.connected_to == ("broker.example.com", 8883)

    def test_explicit_context_uses_context_wrap(
        self, mp_adapter: types.ModuleType,
    ) -> None:
        """A pre-built SSLContext routes through `context.wrap_socket`."""
        stub_ssl = sys.modules["ssl"]
        context = stub_ssl._StubContext()  # type: ignore[attr-defined]
        sock = mp_adapter.connect_tls(
            "broker.example.com", 8883, context=context,
        )
        # Context-method form recorded on the context.
        assert len(context.wrapped) == 1
        wrapped_sock, server_hostname = context.wrapped[0]
        assert wrapped_sock is sock
        assert server_hostname == "broker.example.com"
        # Free-form should NOT have fired.
        assert sys.modules["ssl"]._free_wrap_calls == []  # type: ignore[attr-defined]


class TestSslContextWithCa:
    def test_loads_cadata_into_context(self, mp_adapter: types.ModuleType) -> None:
        ca_pem = b"-----BEGIN CERTIFICATE-----\nfake-ca\n-----END CERTIFICATE-----\n"
        context = mp_adapter.ssl_context_with_ca(ca_pem)
        assert "fake-ca" in context.cadata
