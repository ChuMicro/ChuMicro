"""Cross-runtime tests for the CircuitPython adapter.

The CP adapter (``chumicro_sockets._adapters.cp``) imports
``socketpool`` at module load time (stubbed here via ``sys.modules``
before the adapter import) and ``ssl`` lazily inside function bodies,
so we can drive it from any runtime by stubbing both modules.

Mirrors the shape of ``test_mp_adapter_pytest.py`` (per-test stubbed
modules, protocol-shape verification) but uses the ``SwapAttribute``
/ ``SwapItem`` / ``FakeModule`` cross-runtime helpers from
``chumicro_test_harness.patching`` — so it runs on CPython,
MicroPython unix-port, and CircuitPython unix-port.

This is the host-side complement to:

* the on-device functional tests under ``functional_tests/`` (real
  ``socketpool`` against ``wifi.radio`` on actual CP boards), and
* the dispatcher routing tests in ``test_factories_routing.py``
  (verify the package entry reaches the cp adapter, not what the cp
  adapter does).

It catches regressions in the call shapes the CP adapter expects
``socketpool`` to expose, plus the protocol the wrapper classes
present back to ``chumicro-sockets`` callers.
"""

#: Host-only lane: drives runtime-specific CircuitPython source
#: through host fakes and asserts off-target behaviour, so it runs
#: on every host interpreter (CPython + MP/CP unix-port) but never
#: on real silicon.
__chumicro_host_only__ = True

import sys

from _swap_helpers import SocketpoolStub

sys.modules.setdefault("socketpool", SocketpoolStub())


from chumicro_sockets import (  # noqa: E402 — load-order dependency on the stub above
    UnsupportedSSLConfigError,
)
from chumicro_test_harness.assertions import raises  # noqa: E402
from chumicro_test_harness.patching import (  # noqa: E402
    FakeModule,
    SwapAttribute,
    SwapItem,
)

# ---------------------------------------------------------------------------
# Stubs — minimum surface the CP adapter touches
# ---------------------------------------------------------------------------


class _StubSocket:
    """Stub CP socketpool socket — bare minimum the adapter touches."""

    def __init__(self, family, kind):
        self.family = family
        self.kind = kind
        self.connected_to = None
        self.bound_to = None
        self.listening_backlog = None
        self.blocking_flag = None
        self.timeout = None
        self.setsockopt_calls = []
        self.sendto_calls = []
        self.closed = False
        self._fileno = 42
        # Fail-mode knobs the per-test methods can enable.
        self.raise_setsockopt = None  # set to an exception to raise on next setsockopt
        self.no_setsockopt = False  # set True to delete setsockopt entirely
        self.no_getsockname = False
        self.recv_into_returns = (0, ("0.0.0.0", 0))

    def connect(self, address):
        self.connected_to = address

    def bind(self, address):
        self.bound_to = address

    def listen(self, backlog):
        self.listening_backlog = backlog

    def accept(self):
        return _StubSocket(self.family, self.kind), ("10.0.0.42", 12345)

    def setblocking(self, flag):
        self.blocking_flag = flag

    def settimeout(self, seconds):
        self.timeout = seconds

    def setsockopt(self, level, opt, value):
        if self.no_setsockopt:
            raise AttributeError("no setsockopt")
        if self.raise_setsockopt is not None:
            error_to_raise = self.raise_setsockopt
            self.raise_setsockopt = None
            raise error_to_raise
        self.setsockopt_calls.append((level, opt, value))

    def sendto(self, data, address):
        self.sendto_calls.append((bytes(data), address))
        return len(data)

    def recvfrom_into(self, buffer, nbytes=0):
        return self.recv_into_returns

    def close(self):
        self.closed = True

    def fileno(self):
        return self._fileno

    def getsockname(self):
        if self.no_getsockname:
            raise AttributeError("no getsockname")
        return (self.bound_to or ("0.0.0.0", 0))


class _StubPool:
    """Stub ``socketpool.SocketPool`` — records sockets handed out."""

    AF_INET = 2
    SOCK_STREAM = 1
    SOCK_DGRAM = 5  # arbitrary; CP socketpool happens to use 2 — we just need a distinct constant
    SOL_SOCKET = 1
    SO_BROADCAST = 6
    SO_REUSEADDR = 4

    def __init__(self, radio):
        self.radio = radio
        self.sockets = []  # every socket() call appended here

    def socket(self, family, kind):
        sock = _StubSocket(family, kind)
        self.sockets.append(sock)
        return sock

    def getaddrinfo(self, host, port, family, kind):
        # Stub: return a single addrinfo tuple in the same shape
        # stdlib uses — (family, socktype, proto, canonname, sockaddr).
        return [(family, kind, 0, "", (host, port))]


def _install_socketpool_stub():
    """Swap the CP adapter's module-level ``socketpool`` with a fake.

    Returns the (context-manager, fake-module) pair so the test can
    later look up the most-recently-created pool via the fake module's
    recorded list.  This file's module-level ``sys.modules.setdefault``
    seeds ``socketpool`` at import time so ``import socketpool`` at
    cp.py module top succeeds; per-test swaps target the adapter's
    binding directly so tests do not race against the cached
    ``cp.socketpool`` reference.
    """
    from chumicro_sockets._adapters import cp as cp_adapter

    fake = FakeModule()
    fake.SocketPool = _StubPool
    fake.created_pools = []  # filled by the patched constructor below

    # Wrap _StubPool to record every constructed pool on the module.
    original_init = _StubPool.__init__

    def recording_init(self, radio):
        original_init(self, radio)
        fake.created_pools.append(self)

    fake.SocketPool = type(
        "SocketPool",
        (_StubPool,),
        {"__init__": recording_init},
    )
    return SwapAttribute(cp_adapter, "socketpool", fake), fake


def _install_ssl_stub(create_default_context_factory=None):
    """Stub ``sys.modules['ssl']`` and return (swap, module).

    *create_default_context_factory* is the zero-arg callable
    ``ssl.create_default_context`` will return.  When ``None``, returns
    a placeholder ``_StubContext`` so callers that don't care about
    context shape still get a working stub.
    """
    fake = FakeModule()
    contexts_built = []

    def factory():
        if create_default_context_factory is not None:
            context = create_default_context_factory()
        else:
            context = _StubContext()
        contexts_built.append(context)
        return context

    fake.create_default_context = factory
    fake.contexts_built = contexts_built
    return SwapItem(sys.modules, "ssl", fake), fake


class _StubContext:
    """Stub ``ssl.SSLContext`` — captures wrap/load calls."""

    def __init__(self):
        self.cadata = None
        self.cert_chain_calls = []
        self.wrap_calls = []
        self.server_side_wrap_calls = []

    def load_verify_locations(self, *, cadata):
        self.cadata = cadata

    def load_cert_chain(self, cert_path, key_path):
        self.cert_chain_calls.append((cert_path, key_path))

    def wrap_socket(self, sock, *, server_hostname=None, server_side=False):
        if server_side:
            self.server_side_wrap_calls.append(sock)
        else:
            self.wrap_calls.append((sock, server_hostname))
        return sock


def _clear_pool_cache():
    """Reset the CP adapter's module-level pool cache between tests."""
    from chumicro_sockets._adapters import cp as cp_adapter
    cp_adapter._POOL = None


# ---------------------------------------------------------------------------
# _pool_for
# ---------------------------------------------------------------------------


class TestPoolFor:
    def test_constructs_pool_via_socketpool_module(self) -> None:
        from chumicro_sockets._adapters import cp as cp_adapter
        _clear_pool_cache()
        radio = object()
        pool_swap, fake_pool_module = _install_socketpool_stub()
        with pool_swap:
            pool = cp_adapter._pool_for(radio)
        assert pool is fake_pool_module.created_pools[0]
        assert pool.radio is radio

    def test_memoizes_single_pool(self) -> None:
        """Two calls return the same pool; constructor runs once."""
        from chumicro_sockets._adapters import cp as cp_adapter
        _clear_pool_cache()
        radio = object()
        pool_swap, fake_pool_module = _install_socketpool_stub()
        with pool_swap:
            first = cp_adapter._pool_for(radio)
            second = cp_adapter._pool_for(radio)
        assert first is second
        assert len(fake_pool_module.created_pools) == 1

    def test_none_radio_raises_typeerror(self) -> None:
        """``radio=None`` is rejected — adapter does not import ``wifi``
        to backfill a missing radio.  Callers pass ``wifi.radio``
        explicitly or whichever radio object their board exposes.
        """
        from chumicro_sockets._adapters import cp as cp_adapter
        _clear_pool_cache()
        with raises(TypeError, match="radio="):
            cp_adapter._pool_for(None)


# ---------------------------------------------------------------------------
# udp_socket + _CPUDPWrapper
# ---------------------------------------------------------------------------


class TestUdpSocket:
    def test_creates_dgram_socket_and_binds(self) -> None:
        from chumicro_sockets._adapters import cp as cp_adapter
        _clear_pool_cache()
        radio = object()
        pool_swap, fake_pool_module = _install_socketpool_stub()
        with pool_swap:
            wrapper = cp_adapter.udp_socket(
                bind_host="0.0.0.0", bind_port=5353, radio=radio,
            )
        pool = fake_pool_module.created_pools[0]
        sock = pool.sockets[0]
        assert sock.family == _StubPool.AF_INET
        assert sock.kind == _StubPool.SOCK_DGRAM
        assert sock.bound_to == ("0.0.0.0", 5353)
        # Wrapper exposes the underlying socket.
        assert wrapper.sock is sock

    def test_broadcast_true_sets_so_broadcast(self) -> None:
        from chumicro_sockets._adapters import cp as cp_adapter
        _clear_pool_cache()
        pool_swap, fake_pool_module = _install_socketpool_stub()
        with pool_swap:
            cp_adapter.udp_socket(radio=object(), broadcast=True)
        sock = fake_pool_module.created_pools[0].sockets[0]
        assert (
            _StubPool.SOL_SOCKET, _StubPool.SO_BROADCAST, 1,
        ) in sock.setsockopt_calls

    def test_broadcast_false_does_not_set_so_broadcast(self) -> None:
        from chumicro_sockets._adapters import cp as cp_adapter
        _clear_pool_cache()
        pool_swap, fake_pool_module = _install_socketpool_stub()
        with pool_swap:
            cp_adapter.udp_socket(radio=object(), broadcast=False)
        sock = fake_pool_module.created_pools[0].sockets[0]
        assert sock.setsockopt_calls == []

    def test_broadcast_setsockopt_oserror_swallowed(self) -> None:
        """Older CP firmware lacks SO_BROADCAST — non-fatal."""
        from chumicro_sockets._adapters import cp as cp_adapter
        _clear_pool_cache()
        pool_swap, fake_pool_module = _install_socketpool_stub()

        # Pre-arm the next-built socket to raise on setsockopt.
        original_socket = _StubPool.socket

        def socket_with_failing_setsockopt(self, family, kind):
            sock = original_socket(self, family, kind)
            sock.raise_setsockopt = OSError(99, "SO_BROADCAST not supported")
            return sock

        with pool_swap, SwapAttribute(
            fake_pool_module.SocketPool, "socket", socket_with_failing_setsockopt,
        ):
            wrapper = cp_adapter.udp_socket(radio=object(), broadcast=True)
        # No exception; wrapper still constructed; bind still happened.
        assert wrapper.sock.bound_to == ("0.0.0.0", 0)

    def test_broadcast_setsockopt_attributeerror_swallowed(self) -> None:
        """Older CP firmware may lack ``setsockopt`` entirely — non-fatal."""
        from chumicro_sockets._adapters import cp as cp_adapter
        _clear_pool_cache()
        pool_swap, fake_pool_module = _install_socketpool_stub()

        original_socket = _StubPool.socket

        def socket_without_setsockopt(self, family, kind):
            sock = original_socket(self, family, kind)
            sock.no_setsockopt = True
            return sock

        with pool_swap, SwapAttribute(
            fake_pool_module.SocketPool, "socket", socket_without_setsockopt,
        ):
            wrapper = cp_adapter.udp_socket(radio=object(), broadcast=True)
        # Wrapper still constructed; bind still happened — the missing
        # ``setsockopt`` was swallowed, not propagated.
        assert wrapper.sock.bound_to == ("0.0.0.0", 0)


class TestCpUdpWrapper:
    def test_sendto_separated_signature(self) -> None:
        """Wrapper takes ``(data, host, port)`` and forwards as ``(data, (host, port))``."""
        from chumicro_sockets._adapters import cp as cp_adapter
        _clear_pool_cache()
        pool_swap, fake_pool_module = _install_socketpool_stub()
        with pool_swap:
            wrapper = cp_adapter.udp_socket(radio=object())
            wrapper.sendto(b"hello", "10.0.0.5", 1234)
        sock = fake_pool_module.created_pools[0].sockets[0]
        assert sock.sendto_calls == [(b"hello", ("10.0.0.5", 1234))]

    def test_recvfrom_into_forwarded(self) -> None:
        from chumicro_sockets._adapters import cp as cp_adapter
        _clear_pool_cache()
        pool_swap, fake_pool_module = _install_socketpool_stub()
        with pool_swap:
            wrapper = cp_adapter.udp_socket(radio=object())
        sock = fake_pool_module.created_pools[0].sockets[0]
        sock.recv_into_returns = (5, ("10.0.0.5", 1234))
        buffer = bytearray(64)
        nbytes, address = wrapper.recvfrom_into(buffer)
        assert nbytes == 5
        assert address == ("10.0.0.5", 1234)

    def test_close_setblocking_getsockname_forwarded(self) -> None:
        from chumicro_sockets._adapters import cp as cp_adapter
        _clear_pool_cache()
        pool_swap, fake_pool_module = _install_socketpool_stub()
        with pool_swap:
            wrapper = cp_adapter.udp_socket(
                bind_host="192.168.1.1", bind_port=1234, radio=object(),
            )
        sock = fake_pool_module.created_pools[0].sockets[0]
        wrapper.setblocking(False)
        assert sock.blocking_flag is False
        wrapper.settimeout(2.5)
        assert sock.timeout == 2.5
        assert wrapper.getsockname() == ("192.168.1.1", 1234)
        wrapper.close()
        assert sock.closed is True

    def test_getsockname_absent_on_bare_metal_sockets(self) -> None:
        """Bare-metal socketpool lacks getsockname; the wrapper mirrors that."""
        from chumicro_sockets._adapters.cp import _CPUDPWrapper

        class _BareMetalSocket:
            close = staticmethod(lambda: None)
            setblocking = staticmethod(lambda _flag: None)
            recvfrom_into = staticmethod(lambda _buffer: (0, ("", 0)))

        wrapper = _CPUDPWrapper(_BareMetalSocket())
        assert not hasattr(wrapper, "getsockname")


# ---------------------------------------------------------------------------
# listener — plain TCP
# ---------------------------------------------------------------------------


class TestListenerTcp:
    def test_binds_listens_and_sets_nonblocking(self) -> None:
        from chumicro_sockets._adapters import cp as cp_adapter
        _clear_pool_cache()
        pool_swap, fake_pool_module = _install_socketpool_stub()
        with pool_swap:
            listener = cp_adapter.listener(
                "0.0.0.0", 8080, backlog=8, radio=object(),
            )
        sock = fake_pool_module.created_pools[0].sockets[0]
        assert listener is sock
        assert sock.family == _StubPool.AF_INET
        assert sock.kind == _StubPool.SOCK_STREAM
        assert sock.bound_to == ("0.0.0.0", 8080)
        assert sock.listening_backlog == 8
        assert sock.blocking_flag is False

    def test_default_backlog_is_4(self) -> None:
        from chumicro_sockets._adapters import cp as cp_adapter
        _clear_pool_cache()
        pool_swap, fake_pool_module = _install_socketpool_stub()
        with pool_swap:
            cp_adapter.listener("0.0.0.0", 8080, radio=object())
        sock = fake_pool_module.created_pools[0].sockets[0]
        assert sock.listening_backlog == 4

    def test_so_reuseaddr_set_when_supported(self) -> None:
        from chumicro_sockets._adapters import cp as cp_adapter
        _clear_pool_cache()
        pool_swap, fake_pool_module = _install_socketpool_stub()
        with pool_swap:
            cp_adapter.listener("0.0.0.0", 8080, radio=object())
        sock = fake_pool_module.created_pools[0].sockets[0]
        assert (
            _StubPool.SOL_SOCKET, _StubPool.SO_REUSEADDR, 1,
        ) in sock.setsockopt_calls

    def test_so_reuseaddr_attributeerror_swallowed(self) -> None:
        """Older CP firmware lacks setsockopt — non-fatal."""
        from chumicro_sockets._adapters import cp as cp_adapter
        _clear_pool_cache()
        pool_swap, fake_pool_module = _install_socketpool_stub()

        original_socket = _StubPool.socket

        def socket_without_setsockopt(self, family, kind):
            sock = original_socket(self, family, kind)
            sock.no_setsockopt = True
            return sock

        with pool_swap, SwapAttribute(
            fake_pool_module.SocketPool, "socket", socket_without_setsockopt,
        ):
            listener = cp_adapter.listener("0.0.0.0", 8080, radio=object())
        # Bind / listen / setblocking still happened.
        assert listener.bound_to == ("0.0.0.0", 8080)
        assert listener.listening_backlog == 4
        assert listener.blocking_flag is False


# ---------------------------------------------------------------------------
# ssl_context_with_cert_and_key (in-memory) — refused on CP
# ---------------------------------------------------------------------------


class TestSslContextWithCertAndKeyRefused:
    def test_in_memory_pem_raises_unsupported(self) -> None:
        """CP's load_cert_chain only accepts paths — bytes raise."""
        from chumicro_sockets._adapters import cp as cp_adapter
        with raises(UnsupportedSSLConfigError, match="filesystem paths"):
            cp_adapter.ssl_context_with_cert_and_key(b"-----BEGIN", b"-----BEGIN")


# ---------------------------------------------------------------------------
# ssl_context_with_cert_and_key_paths
# ---------------------------------------------------------------------------


class TestSslContextWithCertAndKeyPaths:
    def test_calls_load_verify_then_load_cert_chain(self) -> None:
        """Mirrors adafruit_httpserver: empty cadata then cert chain."""
        from chumicro_sockets._adapters import cp as cp_adapter
        ssl_swap, fake_ssl = _install_ssl_stub()
        with ssl_swap:
            context = cp_adapter.ssl_context_with_cert_and_key_paths(
                "/lib/server_cert.pem", "/lib/server_key.pem",
            )
        # One default context built.
        assert len(fake_ssl.contexts_built) == 1
        assert context is fake_ssl.contexts_built[0]
        # Empty-cadata load_verify_locations call (CP mbedtls binding
        # requires this before load_cert_chain).
        assert context.cadata == ""
        # Cert chain loaded with the supplied paths.
        assert context.cert_chain_calls == [
            ("/lib/server_cert.pem", "/lib/server_key.pem"),
        ]


# ---------------------------------------------------------------------------
# listener — TLS
# ---------------------------------------------------------------------------


class TestListenerTls:
    def test_wraps_then_binds_listens_nonblocking(self) -> None:
        """Listener socket gets ``server_side=True`` wrap before bind/listen."""
        from chumicro_sockets._adapters import cp as cp_adapter
        _clear_pool_cache()
        pool_swap, fake_pool_module = _install_socketpool_stub()
        context = _StubContext()
        with pool_swap:
            listener = cp_adapter.listener(
                "0.0.0.0", 8443, tls=True, context=context, backlog=8, radio=object(),
            )
        raw = fake_pool_module.created_pools[0].sockets[0]
        # Server-side wrap fired against the raw pool socket, then bind /
        # listen / setblocking ran on the wrap result; the stub's
        # ``wrap_socket`` returns the same socket so ``listener is raw``.
        assert context.server_side_wrap_calls == [raw]
        assert raw.bound_to == ("0.0.0.0", 8443)
        assert raw.listening_backlog == 8
        assert raw.blocking_flag is False
        assert listener is raw

    def test_default_backlog_is_4(self) -> None:
        from chumicro_sockets._adapters import cp as cp_adapter
        _clear_pool_cache()
        pool_swap, fake_pool_module = _install_socketpool_stub()
        with pool_swap:
            cp_adapter.listener(
                "0.0.0.0", 8443, tls=True, context=_StubContext(), radio=object(),
            )
        raw = fake_pool_module.created_pools[0].sockets[0]
        assert raw.listening_backlog == 4


# ---------------------------------------------------------------------------
# ssl_context_with_ca
# ---------------------------------------------------------------------------


class TestSslContextWithCa:
    def test_str_input_passed_through(self) -> None:
        from chumicro_sockets._adapters import cp as cp_adapter
        ssl_swap, fake_ssl = _install_ssl_stub()
        ca_pem = (
            "-----BEGIN CERTIFICATE-----\n"
            "fake-payload\n"
            "-----END CERTIFICATE-----\n"
        )
        with ssl_swap:
            context = cp_adapter.ssl_context_with_ca(ca_pem)
        assert context is fake_ssl.contexts_built[0]
        assert context.cadata == ca_pem

    def test_bytes_input_decoded_to_str(self) -> None:
        """CP's load_verify_locations expects a ``str`` — bytes coerced."""
        from chumicro_sockets._adapters import cp as cp_adapter
        ssl_swap, fake_ssl = _install_ssl_stub()
        ca_pem_bytes = (
            b"-----BEGIN CERTIFICATE-----\n"
            b"fake-payload\n"
            b"-----END CERTIFICATE-----\n"
        )
        with ssl_swap:
            context = cp_adapter.ssl_context_with_ca(ca_pem_bytes)
        # Recorded value is the str form, not the bytes.
        assert isinstance(context.cadata, str)
        assert "fake-payload" in context.cadata

    def test_bytearray_input_also_accepted(self) -> None:
        """Public signature is ``bytes | str``; bytearray is bytes-shaped too."""
        from chumicro_sockets._adapters import cp as cp_adapter
        ssl_swap, fake_ssl = _install_ssl_stub()
        ca_pem = bytearray(
            b"-----BEGIN CERTIFICATE-----\n"
            b"more-payload\n"
            b"-----END CERTIFICATE-----\n"
        )
        with ssl_swap:
            context = cp_adapter.ssl_context_with_ca(ca_pem)
        assert isinstance(context.cadata, str)
        assert "more-payload" in context.cadata

    def test_der_bytes_rejected_with_clear_error(self) -> None:
        """CP's binding can't take DER — reject up front with a clear
        message instead of a cryptic UnicodeDecodeError deep in
        ``.decode('ascii')``."""
        from chumicro_sockets._adapters import cp as cp_adapter
        der = b"\x30\x82\x01\x23\xff\xfe\x00\x80"  # not ASCII-decodable
        try:
            cp_adapter.ssl_context_with_ca(der)
        except ValueError as error:
            assert "PEM" in str(error)
            assert "DER" in str(error)
        else:
            raise AssertionError("expected ValueError for DER input on CP")

    def test_str_non_pem_rejected(self) -> None:
        """A str that isn't PEM is rejected with the same clear error."""
        from chumicro_sockets._adapters import cp as cp_adapter
        try:
            cp_adapter.ssl_context_with_ca("definitely not a pem")
        except ValueError as error:
            assert "PEM" in str(error)
        else:
            raise AssertionError("expected ValueError for non-PEM str on CP")


class TestSslContextNoVerify:
    def test_clears_bundle_and_check_hostname(self) -> None:
        """CP's no-verify shape: ``load_verify_locations("")`` empties
        the firmware bundle attachment and ``check_hostname = False``
        completes the opt-out.  The combination resolves to
        ``MBEDTLS_SSL_VERIFY_NONE`` at handshake time."""
        from chumicro_sockets._adapters import cp as cp_adapter
        ssl_swap, fake_ssl = _install_ssl_stub()
        with ssl_swap:
            context = cp_adapter.ssl_context_no_verify()
        assert context is fake_ssl.contexts_built[0]
        # Empty-string cadata is the CP idiom for "no CAs, fall through
        # to VERIFY_NONE".  See shared-module/ssl/SSLSocket.c.
        assert context.cadata == ""
        assert context.check_hostname is False


class TestCPConnector:
    def test_tcp_connector_phases_dns_then_tcp_then_ready(self) -> None:
        # CP substrate blocks per phase, but the connector still
        # splits DNS from TCP: tick 1 resolves, tick 2 connects.
        from chumicro_sockets._adapters import cp as cp_adapter
        _clear_pool_cache()
        radio = object()
        pool_swap, fake_pool_module = _install_socketpool_stub()
        with pool_swap:
            connector = cp_adapter.connector(
                "broker.example.com", 1883, radio=radio,
            )
            assert connector.state == "awaiting_dns"
            connector.tick(0)
            assert connector.state == "awaiting_tcp"
            # DNS resolved but no socket created yet.
            pool = fake_pool_module.created_pools[0]
            assert pool.sockets == []
            connector.tick(0)
            assert connector.state == "ready"
            # Socket created on the TCP tick.
            assert len(pool.sockets) == 1
            assert connector.socket is pool.sockets[0]
            assert connector.socket.connected_to == ("broker.example.com", 1883)

    def test_tls_connector_skips_awaiting_tls_phase(self) -> None:
        # CP collapses TCP + TLS handshake into one connect() call —
        # the connector goes straight to ready, skipping awaiting_tls.
        from chumicro_sockets._adapters import cp as cp_adapter
        _clear_pool_cache()
        radio = object()
        context = _StubContext()
        pool_swap, fake_pool_module = _install_socketpool_stub()
        with pool_swap:
            connector = cp_adapter.connector(
                "broker.example.com", 8883,
                tls=True, context=context, radio=radio,
            )
            connector.tick(0)  # awaiting_dns -> awaiting_tcp
            assert connector.state == "awaiting_tcp"
            connector.tick(0)  # awaiting_tcp -> ready (no awaiting_tls phase)
            assert connector.state == "ready"
            # Wrap happened before connect.
            assert len(context.wrap_calls) == 1
            wrapped_sock, server_hostname = context.wrap_calls[0]
            assert server_hostname == "broker.example.com"
            # Wrapped socket received the connect call.
            assert wrapped_sock.connected_to == ("broker.example.com", 8883)
            assert connector.socket is wrapped_sock

    def test_tls_connector_builds_default_context_when_none(self) -> None:
        # context=None routes through ssl.create_default_context on the
        # connector's TLS wrap path.
        from chumicro_sockets._adapters import cp as cp_adapter
        _clear_pool_cache()
        radio = object()
        pool_swap, _ = _install_socketpool_stub()
        ssl_swap, fake_ssl = _install_ssl_stub()
        with pool_swap, ssl_swap:
            connector = cp_adapter.connector(
                "secure.example.com", 443, tls=True, radio=radio,
            )
            connector.tick(0)
            connector.tick(0)
        assert connector.state == "ready"
        assert len(fake_ssl.contexts_built) == 1
