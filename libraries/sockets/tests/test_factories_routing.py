"""Host-only tests for the runtime-routing entries.

Every test here fakes a runtime identity by swapping
``chumicro_sockets._adapter`` to a named per-runtime adapter (or a
``FakeModule`` stand-in), then asserts which adapter the entry
dispatched to.  That makes each test pass only against the adapter
module it names — on every other runtime the named module isn't
staged and the import fails.  Routing is a host-verified concern as a
category, so these run on CPython + the MicroPython / CircuitPython
unix-ports but never on real silicon.

The swaps use ``SwapAttribute`` / ``SwapItem`` / ``FakeModule`` from
``chumicro_test_harness.patching`` — cross-runtime equivalents of
``unittest.mock.patch.object`` / ``patch.dict`` and a module-shaped
fake, since ``unittest`` and ``types`` don't exist on the MP / CP
unix-ports.

CPython-only tests — real loopback sockets, real TLS handshakes,
``cryptography``-minted certs, real stdlib ``ssl`` / ``socket``
patching — live in the sibling ``test_factories_pytest.py``.  The
runtime-independent public-surface checks (``UnsupportedSSLConfigError``)
stay in the cross-runtime ``test_factories.py``.
"""

#: Host-only lane: fakes a runtime identity and asserts the entry's
#: adapter route, so it runs on every host interpreter (CPython + MP/CP
#: unix-port) but never on real silicon.
__chumicro_host_only__ = True

import sys

from _swap_helpers import BareStub, SocketpoolStub

# ``socketpool`` is a firmware module absent from every host interpreter,
# so the cp-adapter import always needs the stub.
sys.modules.setdefault("socketpool", SocketpoolStub())
# ``socket`` / ``ssl`` / ``select`` are real, importable stdlib on
# CPython, and pytest's own machinery (``selectors`` needs
# ``select.select``) depends on them — stubbing them via
# ``setdefault`` in an interpreter that hasn't imported them yet
# poisons ``sys.modules`` for the whole session.  Only the
# MicroPython / CircuitPython unix-ports lack an adapter-ready copy,
# so install the placeholders there alone.
if sys.implementation.name != "cpython":
    sys.modules.setdefault("socket", BareStub())
    sys.modules.setdefault("ssl", BareStub())
    sys.modules.setdefault("select", BareStub())


import chumicro_sockets  # noqa: E402 — load-order dependency on the stub above
from chumicro_sockets import (  # noqa: E402
    connector,
    listener,
    set_default_ca_bundle,
    ssl_context_no_verify,
    ssl_context_with_ca,
    ssl_context_with_cert_and_key,
    ssl_context_with_cert_and_key_paths,
)
from chumicro_test_harness import raises  # noqa: E402
from chumicro_test_harness.patching import (  # noqa: E402
    FakeModule,
    SwapAttribute,
    SwapItem,
)


def _set_runtime(name):
    """Return a ``SwapAttribute`` that swaps ``chumicro_sockets._adapter`` to *name*'s adapter.

    The package resolves ``_adapter`` once at import time from
    ``sys.implementation.name``.  Tests that need to drive a different
    runtime's adapter swap the binding directly; the swap stack restores
    the host's real adapter on exit.
    """
    if name == "circuitpython":
        from chumicro_sockets._adapters import cp as target_adapter
    elif name == "micropython":
        from chumicro_sockets._adapters import mp as target_adapter
    else:
        from chumicro_sockets._adapters import cpython as target_adapter
    return SwapAttribute(chumicro_sockets, "_adapter", target_adapter)


def _stub_mp_adapter(**attrs):
    """Build a fake mp-adapter and swap ``chumicro_sockets._adapter`` to it.

    Returned as a list so the call site can extend a context-manager
    stack uniformly with the other ``Swap*`` contexts.
    """
    fake = FakeModule()
    for attr, value in attrs.items():
        setattr(fake, attr, value)
    return [SwapAttribute(chumicro_sockets, "_adapter", fake)]


# ---------------------------------------------------------------------------
# connector routing — patch the adapter binding to simulate runtimes
# ---------------------------------------------------------------------------


class TestConnectorRouting:
    """``connector`` dispatches to the runtime-appropriate adapter with its kwargs intact."""

    def test_cpython_runtime_routes_to_cpython_adapter(self) -> None:
        captured: dict = {}

        def fake_connector(host, port, *, tls, context, **_kwargs):
            captured["called"] = (host, port, tls, context)
            return "fake-cpython-connector"

        from chumicro_sockets._adapters import cpython as cpython_adapter

        with _set_runtime("cpython"), \
                SwapAttribute(cpython_adapter, "connector", fake_connector):
            result = connector("h", 1)

        assert result == "fake-cpython-connector"
        assert captured["called"] == ("h", 1, False, None)

    def test_circuitpython_runtime_routes_to_cp_adapter(self) -> None:
        captured: dict = {}

        from chumicro_sockets._adapters import cp as cp_adapter

        def fake_connector(host, port, *, tls, context, radio, **_kwargs):
            captured["called"] = (host, port, tls, context, radio)
            return "fake-cp-connector"

        with _set_runtime("circuitpython"), \
                SwapAttribute(cp_adapter, "connector", fake_connector):
            result = connector("h", 1, radio="fake-radio")

        assert result == "fake-cp-connector"
        assert captured["called"] == ("h", 1, False, None, "fake-radio")

    def test_micropython_runtime_routes_to_mp_adapter(self) -> None:
        captured: dict = {}

        def fake_connector(host, port, *, tls, context, **_kwargs):
            captured["called"] = (host, port, tls, context)
            return "fake-mp-connector"

        contexts = [_set_runtime("micropython")]
        contexts.extend(_stub_mp_adapter(connector=fake_connector))

        # Manually enter / exit because we have a variable-length stack.
        for context in contexts:
            context.__enter__()
        try:
            result = connector("h", 1, tls=True, context="ctx")
        finally:
            for context in reversed(contexts):
                context.__exit__(None, None, None)

        assert result == "fake-mp-connector"
        assert captured["called"] == ("h", 1, True, "ctx")


# ---------------------------------------------------------------------------
# listener routing
# ---------------------------------------------------------------------------


class TestListenerRouting:
    """``listener`` dispatches to the runtime-appropriate adapter."""

    def test_circuitpython_runtime_routes_to_cp_adapter(self) -> None:
        captured: dict = {}

        def fake_listener(host, port, *, tls, context, backlog, radio, **_kwargs):
            captured["called"] = (host, port, tls, context, backlog, radio)
            return "cp-listener"

        from chumicro_sockets._adapters import cp as cp_adapter

        with _set_runtime("circuitpython"), \
                SwapAttribute(cp_adapter, "listener", fake_listener):
            result = listener("0.0.0.0", 8080, radio="fake-radio")

        assert result == "cp-listener"
        assert captured["called"] == ("0.0.0.0", 8080, False, None, 4, "fake-radio")

    def test_micropython_runtime_routes_to_mp_adapter(self) -> None:
        captured: dict = {}

        def fake_listener(host, port, *, tls, context, backlog, **_kwargs):
            captured["called"] = (host, port, tls, context, backlog)
            return "mp-listener"

        contexts = [_set_runtime("micropython")]
        contexts.extend(_stub_mp_adapter(listener=fake_listener))

        for context in contexts:
            context.__enter__()
        try:
            result = listener("0.0.0.0", 8080, backlog=8)
        finally:
            for context in reversed(contexts):
                context.__exit__(None, None, None)

        assert result == "mp-listener"
        assert captured["called"] == ("0.0.0.0", 8080, False, None, 8)

    def test_cpython_tls_listener_routes_with_context(self) -> None:
        captured: dict = {}

        def fake_listener(host, port, *, tls, context, backlog, **_kwargs):
            captured["called"] = (host, port, tls, context, backlog)
            return "cpython-tls-listener"

        from chumicro_sockets._adapters import cpython as cpython_adapter

        with _set_runtime("cpython"), \
                SwapAttribute(cpython_adapter, "listener", fake_listener):
            result = listener("0.0.0.0", 8443, tls=True, context="fake-ctx")

        assert result == "cpython-tls-listener"
        assert captured["called"] == ("0.0.0.0", 8443, True, "fake-ctx", 4)

    def test_tls_without_context_raises_before_dispatch(self) -> None:
        """``listener(tls=True)`` with no context raises ValueError at the
        package entry — the adapter is never consulted, so the error is
        identical on every runtime."""
        captured: dict = {"dispatched": False}

        def fake_listener(*_args, **_kwargs):
            captured["dispatched"] = True

        contexts = [_set_runtime("micropython")]
        contexts.extend(_stub_mp_adapter(listener=fake_listener))

        for context in contexts:
            context.__enter__()
        try:
            with raises(ValueError):
                listener("0.0.0.0", 8443, tls=True)
        finally:
            for context in reversed(contexts):
                context.__exit__(None, None, None)

        assert captured["dispatched"] is False


# ---------------------------------------------------------------------------
# ssl_context_with_cert_and_key_paths — CP routing
# ---------------------------------------------------------------------------


class TestSslContextWithCertAndKeyPathsRouting:
    """Path-based helper dispatches to the CP adapter on CP."""

    def test_circuitpython_routes_to_path_adapter(self) -> None:
        captured: dict = {}

        def fake_helper(cert_path, key_path):
            captured["called"] = (cert_path, key_path)
            return "cp-server-ctx"

        from chumicro_sockets._adapters import cp as cp_adapter

        with _set_runtime("circuitpython"), \
                SwapAttribute(cp_adapter, "ssl_context_with_cert_and_key_paths", fake_helper):
            result = ssl_context_with_cert_and_key_paths(
                "/lib/cert.pem", "/lib/key.pem",
            )

        assert result == "cp-server-ctx"
        assert captured["called"] == ("/lib/cert.pem", "/lib/key.pem")


# ---------------------------------------------------------------------------
# ssl_context_with_cert_and_key — routing
# ---------------------------------------------------------------------------


class TestSslContextWithCertAndKeyRouting:
    """``ssl_context_with_cert_and_key`` dispatches to per-runtime adapter."""

    def test_circuitpython_routes_to_cp_adapter(self) -> None:
        from chumicro_sockets._adapters import cp as cp_adapter

        captured: dict = {}

        def fake_helper(cert_pem, key_pem):
            captured["called"] = (cert_pem, key_pem)
            return "cp-server-ctx"

        with _set_runtime("circuitpython"), \
                SwapAttribute(cp_adapter, "ssl_context_with_cert_and_key", fake_helper):
            result = ssl_context_with_cert_and_key(b"cert", b"key")

        assert result == "cp-server-ctx"
        assert captured["called"] == (b"cert", b"key")

    def test_micropython_routes_to_mp_adapter(self) -> None:
        captured: dict = {}

        def fake_helper(cert_pem, key_pem):
            captured["called"] = (cert_pem, key_pem)
            return "mp-server-ctx"

        contexts = [_set_runtime("micropython")]
        contexts.extend(_stub_mp_adapter(ssl_context_with_cert_and_key=fake_helper))

        for context in contexts:
            context.__enter__()
        try:
            result = ssl_context_with_cert_and_key(b"cert", b"key")
        finally:
            for context in reversed(contexts):
                context.__exit__(None, None, None)

        assert result == "mp-server-ctx"
        assert captured["called"] == (b"cert", b"key")


# ---------------------------------------------------------------------------
# CPython TLS default context — the connector's context=None resolution
# ---------------------------------------------------------------------------


class TestCPythonDefaultTLSContext:
    """``_resolve_default_context`` is what the CPython connector's TLS
    phase calls with the constructor's ``context``; ``None`` must build
    stdlib's secure default rather than skipping verification."""

    def test_none_builds_stdlib_default_context(self) -> None:
        from chumicro_sockets._adapters import cpython as cpython_adapter

        captured: dict = {}

        def fake_default_context():
            captured["used_default_context"] = True
            return "default-ctx"

        fake_ssl = FakeModule()
        fake_ssl.create_default_context = fake_default_context

        # The cpython adapter imports ``ssl`` at module top, so swap the
        # adapter's module-level binding directly.
        with SwapAttribute(cpython_adapter, "ssl", fake_ssl):
            result = cpython_adapter._resolve_default_context(None)

        assert result == "default-ctx"
        assert captured.get("used_default_context") is True

    def test_explicit_context_passes_through_unchanged(self) -> None:
        from chumicro_sockets._adapters import cpython as cpython_adapter

        sentinel = object()
        assert cpython_adapter._resolve_default_context(sentinel) is sentinel


# ---------------------------------------------------------------------------
# CircuitPython TLS — the CP connector passes contexts through wrap_socket
# ---------------------------------------------------------------------------


class TestCircuitPythonTLSPassthrough:
    """The CP connector delegates to the supplied context's ``wrap_socket``."""

    def test_passes_context_to_wrap_socket(self) -> None:
        captured: dict = {}

        from chumicro_sockets._adapters import cp as cp_adapter

        class _FakeRawSocket:
            def connect(self, address):
                captured["connected_to"] = address

        class _FakePool:
            AF_INET = 2
            SOCK_STREAM = 1

            def socket(self, family, kind):
                return _FakeRawSocket()

            def getaddrinfo(self, host, port, family, kind):
                return [(family, kind, 0, "", (host, port))]

        class _FakeContext:
            def wrap_socket(self, sock, *, server_hostname):
                captured["wrapped"] = True
                captured["server_hostname"] = server_hostname
                return sock

        with _set_runtime("circuitpython"), \
                SwapAttribute(cp_adapter, "_pool_for", lambda radio: _FakePool()):
            cp_connector = connector(
                "broker.example.com", 8883,
                tls=True,
                context=_FakeContext(),
                radio="fake-radio",
            )
            cp_connector.tick(0)  # awaiting_dns -> awaiting_tcp
            cp_connector.tick(0)  # wrap + blocking connect -> ready

        assert cp_connector.state == "ready"
        assert captured.get("wrapped") is True
        assert captured.get("server_hostname") == "broker.example.com"
        assert captured.get("connected_to") == ("broker.example.com", 8883)

    def test_default_context_on_cp_uses_ssl_create_default_context(self) -> None:
        """``connector(tls=True, context=None)`` on CP routes through
        ``ssl.create_default_context()`` before wrapping."""
        captured: dict = {}

        from chumicro_sockets._adapters import cp as cp_adapter

        class _FakeRawSocket:
            def connect(self, address):
                pass

        class _FakePool:
            AF_INET = 2
            SOCK_STREAM = 1

            def socket(self, family, kind):
                return _FakeRawSocket()

            def getaddrinfo(self, host, port, family, kind):
                return [(family, kind, 0, "", (host, port))]

        class _FakeContext:
            def wrap_socket(self, sock, *, server_hostname):
                captured["used_default"] = True
                return sock

        fake_ssl = FakeModule()
        fake_ssl.create_default_context = lambda: _FakeContext()

        with _set_runtime("circuitpython"), \
                SwapItem(sys.modules, "ssl", fake_ssl), \
                SwapAttribute(cp_adapter, "_pool_for", lambda radio: _FakePool()):
            cp_connector = connector("h", 8883, tls=True, radio="fake-radio")
            cp_connector.tick(0)
            cp_connector.tick(0)

        assert cp_connector.state == "ready"
        assert captured.get("used_default") is True

    def test_ssl_context_with_ca_works_on_cp(self) -> None:
        """Custom-CA helper builds a context via the stubbed ``ssl`` module."""
        captured: dict = {}

        class _FakeContext:
            def load_verify_locations(self, *, cadata):
                captured["cadata"] = cadata

        fake_ssl = FakeModule()
        fake_ssl.create_default_context = lambda: _FakeContext()

        with _set_runtime("circuitpython"), \
                SwapItem(sys.modules, "ssl", fake_ssl):
            result = ssl_context_with_ca(
                b"-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n",
            )

        assert isinstance(result, _FakeContext)
        assert "fake" in captured["cadata"]


# ---------------------------------------------------------------------------
# ssl_context_with_ca — CPython routing
# ---------------------------------------------------------------------------


class TestSslContextWithCa:
    def test_routes_through_cpython_adapter(self) -> None:
        """Stub ``ssl.create_default_context`` + confirm CPython adapter wiring.

        Confirms the helper feeds *ca_pem* into ``load_verify_locations``.
        """
        captured: dict = {}

        class _RecordingContext:
            def load_verify_locations(self, *, cadata):
                captured["cadata"] = cadata

        fake_ssl = FakeModule()
        fake_ssl.create_default_context = lambda: _RecordingContext()

        with _set_runtime("cpython"), \
                SwapItem(sys.modules, "ssl", fake_ssl):
            ca_pem = b"-----BEGIN CERTIFICATE-----\nfake-bytes\n-----END CERTIFICATE-----\n"
            result = ssl_context_with_ca(ca_pem)

        assert isinstance(result, _RecordingContext)
        # PEM bytes are decoded to str for stdlib's cadata.
        assert isinstance(captured["cadata"], str)
        assert "fake-bytes" in captured["cadata"]

    def test_cpython_der_bytes_passed_through(self) -> None:
        """stdlib ``load_verify_locations`` accepts DER as bytes-like
        ``cadata``; the CPython adapter passes raw DER through unchanged
        (cross-runtime parity with MP's DER acceptance)."""
        captured: dict = {}

        class _RecordingContext:
            def load_verify_locations(self, *, cadata):
                captured["cadata"] = cadata

        fake_ssl = FakeModule()
        fake_ssl.create_default_context = lambda: _RecordingContext()
        der = b"\x30\x82\x01\x10" + b"\x00" * 40

        with _set_runtime("cpython"), \
                SwapItem(sys.modules, "ssl", fake_ssl):
            ssl_context_with_ca(der)

        assert captured["cadata"] == der
        assert isinstance(captured["cadata"], bytes)

    def test_cpython_non_cert_input_raises(self) -> None:
        """Neither PEM nor DER raises a clear ValueError, not a silent
        empty-trust context."""
        fake_ssl = FakeModule()
        fake_ssl.create_default_context = lambda: object()

        with _set_runtime("cpython"), \
                SwapItem(sys.modules, "ssl", fake_ssl):
            try:
                ssl_context_with_ca(b"plainly not a certificate")
            except ValueError as error:
                assert "PEM" in str(error) and "DER" in str(error)
            else:
                raise AssertionError("expected ValueError for non-cert input")


# ---------------------------------------------------------------------------
# ssl_context_no_verify — per-runtime opt-out shape
# ---------------------------------------------------------------------------


class TestSslContextNoVerifyRouting:
    def test_cpython_route_inverts_default_secure_context(self) -> None:
        """CPython adapter: ``create_default_context`` + flip
        ``check_hostname`` and ``verify_mode = CERT_NONE``."""
        fake_ssl = FakeModule()
        fake_ssl.CERT_NONE = 0

        class _CtxStub:
            check_hostname = True
            verify_mode = None

        fake_ssl.create_default_context = lambda: _CtxStub()

        with _set_runtime("cpython"), \
                SwapItem(sys.modules, "ssl", fake_ssl):
            result = ssl_context_no_verify()

        assert isinstance(result, _CtxStub)
        # Must set check_hostname False BEFORE verify_mode (stdlib
        # refuses verify_mode=CERT_NONE while check_hostname is true).
        assert result.check_hostname is False
        assert result.verify_mode == fake_ssl.CERT_NONE

    def test_cp_route_uses_empty_string_load_verify_idiom(self) -> None:
        """CP adapter: ``load_verify_locations(cadata="")`` falls through
        the firmware-bundle/cacert_buf checks to VERIFY_NONE at handshake."""
        captured: dict = {}

        class _CtxStub:
            check_hostname = True

            def load_verify_locations(self, *, cadata):
                captured["cadata"] = cadata

        fake_ssl = FakeModule()
        fake_ssl.create_default_context = lambda: _CtxStub()

        with _set_runtime("circuitpython"), \
                SwapItem(sys.modules, "ssl", fake_ssl):
            result = ssl_context_no_verify()

        assert isinstance(result, _CtxStub)
        assert captured["cadata"] == ""
        assert result.check_hostname is False

    def test_mp_route_delegates_to_mp_adapter(self) -> None:
        """MP routing delegates to the adapter's ``ssl_context_no_verify``."""
        captured: dict = {"called": False}

        def fake_factory():
            captured["called"] = True
            return "fake-no-verify-context"

        contexts = [_set_runtime("micropython")]
        contexts.extend(_stub_mp_adapter(ssl_context_no_verify=fake_factory))

        for context in contexts:
            context.__enter__()
        try:
            result = ssl_context_no_verify()
        finally:
            for context in reversed(contexts):
                context.__exit__(None, None, None)

        assert result == "fake-no-verify-context"
        assert captured["called"] is True


# ---------------------------------------------------------------------------
# set_default_ca_bundle — only MP delegates
# ---------------------------------------------------------------------------


class TestSetDefaultCaBundleRouting:
    def test_mp_route_delegates_to_mp_adapter(self) -> None:
        captured: dict = {}

        def fake_setter(pem):
            captured["pem"] = pem

        contexts = [_set_runtime("micropython")]
        contexts.extend(_stub_mp_adapter(set_default_ca_bundle=fake_setter))

        for context in contexts:
            context.__enter__()
        try:
            set_default_ca_bundle(b"fake-pem")
        finally:
            for context in reversed(contexts):
                context.__exit__(None, None, None)

        assert captured["pem"] == b"fake-pem"

    def test_cp_route_is_noop(self) -> None:
        """CP gets trust from the firmware bundle — the cp adapter has no
        ``set_default_ca_bundle``, so the package function silently no-ops."""
        from chumicro_sockets._adapters import cp as cp_adapter

        assert not hasattr(cp_adapter, "set_default_ca_bundle")
        with _set_runtime("circuitpython"):
            set_default_ca_bundle(b"ignored")  # must not raise

    def test_cpython_route_is_noop(self) -> None:
        """CPython gets trust from the OS store — the cpython adapter has no
        ``set_default_ca_bundle``, so the package function silently no-ops."""
        from chumicro_sockets._adapters import cpython as cpython_adapter

        assert not hasattr(cpython_adapter, "set_default_ca_bundle")
        with _set_runtime("cpython"):
            set_default_ca_bundle(None)  # must not raise


# TestCpListenerTlsRefusesOnRp2 lives in test_factories_pytest.py — the
# tests need to monkeypatch ``sys.platform``, but on MicroPython /
# CircuitPython unix-ports ``sys`` is read-only at the C level and
# ``setattr(sys, "platform", ...)`` raises ``AttributeError``.  No
# portable way to simulate "running on RP2040" from a non-RP2 host.


# ---------------------------------------------------------------------------
# ssl_context_with_ca — MP routing
# ---------------------------------------------------------------------------


class TestSslContextWithCaMPRouting:
    """``ssl_context_with_ca`` on micropython routes through the MP adapter."""

    def test_micropython_runtime_routes_to_mp_adapter(self) -> None:
        captured: dict = {}

        def fake_helper(ca_pem):
            captured["ca_pem"] = ca_pem
            return "mp-ca-context"

        contexts = [_set_runtime("micropython")]
        contexts.extend(_stub_mp_adapter(ssl_context_with_ca=fake_helper))

        for context in contexts:
            context.__enter__()
        try:
            result = ssl_context_with_ca(
                b"-----BEGIN CERTIFICATE-----\nx\n-----END CERTIFICATE-----\n",
            )
        finally:
            for context in reversed(contexts):
                context.__exit__(None, None, None)

        assert result == "mp-ca-context"
        assert captured["ca_pem"].startswith(b"-----BEGIN CERTIFICATE-----")
