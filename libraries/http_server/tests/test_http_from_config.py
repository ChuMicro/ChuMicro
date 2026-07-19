"""http_server: from_config construction."""

from chumicro_http_server import (
    HttpServer,
    build_response,
)
from chumicro_http_server.testing import FakeListener
from chumicro_test_harness.assertions import raises


class TestFromConfig:
    """``HttpServer.from_config`` reads the manifest's optional keys
    with sensible fall-back defaults.  Like ntp / requests / websockets
    (and unlike mqtt), no key is required — the auto-built listener
    factory binds to ``0.0.0.0:8080`` when nothing is configured.

    TLS is opt-in and requires *both* ``tls.cert_path`` and
    ``tls.key_path``: a single half raises ``MissingConfigKey`` so a
    half-configured TLS deploy fails loudly instead of silently
    dropping into plain TCP."""

    def test_reads_all_non_tls_keys(self) -> None:
        """A complete config dict populates every non-TLS manifest key."""
        config = {
            "http_server.bind_host": "127.0.0.1",
            "http_server.bind_port": 9090,
            "http_server.max_connections": 8,
            "http_server.request_timeout_ms": 30_000,
            "http_server.max_request_body_bytes": 64_000,
        }
        # transport_factory= bypasses the host/port-driven auto-build,
        # so we can assert the constructor knobs without touching
        # chumicro_sockets.
        server = HttpServer.from_config(
            config, transport_factory=lambda: FakeListener([]),
        )
        assert server._max_connections == 8  # noqa: SLF001
        assert server._request_timeout_ms == 30_000  # noqa: SLF001
        assert server._max_request_body_bytes == 64_000  # noqa: SLF001

    def test_defaults_apply_when_keys_absent(self) -> None:
        """Empty config dict makes every manifest key fall back to its default.

        Documents the asymmetry vs ``MQTTClient.from_config``: empty
        config is valid input — the auto-built listener factory binds
        to ``0.0.0.0:8080`` rather than refusing to construct.
        """
        from chumicro_http_server._wire import (
            DEFAULT_MAX_CONNECTIONS,
            DEFAULT_MAX_REQUEST_BODY_BYTES,
            DEFAULT_REQUEST_TIMEOUT_MS,
        )

        server = HttpServer.from_config(
            {}, transport_factory=lambda: FakeListener([]),
        )
        assert server._max_connections == DEFAULT_MAX_CONNECTIONS  # noqa: SLF001
        assert server._request_timeout_ms == DEFAULT_REQUEST_TIMEOUT_MS  # noqa: SLF001
        assert server._max_request_body_bytes == DEFAULT_MAX_REQUEST_BODY_BYTES  # noqa: SLF001

    def test_partial_config_mixes_overrides_with_defaults(self) -> None:
        """Caller-set keys win; absent keys take defaults."""
        from chumicro_http_server._wire import DEFAULT_REQUEST_TIMEOUT_MS

        server = HttpServer.from_config(
            {"http_server.max_connections": 16},
            transport_factory=lambda: FakeListener([]),
        )
        assert server._max_connections == 16  # noqa: SLF001
        assert server._request_timeout_ms == DEFAULT_REQUEST_TIMEOUT_MS  # noqa: SLF001

    def test_handler_kwarg_passes_through(self) -> None:
        """``handler=`` reaches the constructor as the fallback handler."""
        my_handler = lambda request: build_response(200, text="hi")  # noqa: E731
        server = HttpServer.from_config(
            {}, handler=my_handler,
            transport_factory=lambda: FakeListener([]),
        )
        assert server._fallback_handler is my_handler  # noqa: SLF001

    def test_runtime_config_wrapper_works_too(self) -> None:
        """Real ``RuntimeConfig`` instance — same flat-key reads as a dict."""
        from chumicro_config import RuntimeConfig

        config = RuntimeConfig({"http_server.max_connections": 12})
        server = HttpServer.from_config(
            config, transport_factory=lambda: FakeListener([]),
        )
        assert server._max_connections == 12  # noqa: SLF001

    def test_explicit_transport_factory_bypasses_auto_build(self) -> None:
        """Passing transport_factory= skips the chumicro_sockets path
        — caller owns the bind / TLS behavior."""
        listener = FakeListener([])
        custom_factory = lambda: listener  # noqa: E731
        server = HttpServer.from_config(
            {"http_server.bind_host": "ignored"},
            transport_factory=custom_factory,
        )
        assert server._transport_factory is custom_factory  # noqa: SLF001

    def test_default_factory_routes_plain_tcp_when_no_tls_config(self) -> None:
        """Empty config makes the factory call ``listener`` with
        the library defaults (``0.0.0.0:8080``)."""
        import chumicro_sockets as sockets_mod

        captured: dict = {}
        sentinel_listener = FakeListener([])

        def fake_tcp(host, port, *, tls=False, context=None, radio=None):
            captured["host"] = host
            captured["port"] = port
            captured["radio"] = radio
            return sentinel_listener

        original = sockets_mod.listener
        sockets_mod.listener = fake_tcp
        try:
            server = HttpServer.from_config({}, radio="fake-radio")
            server._transport_factory()  # noqa: SLF001 — trigger lazy
        finally:
            sockets_mod.listener = original

        assert captured["host"] == "0.0.0.0"
        assert captured["port"] == 8080
        assert captured["radio"] == "fake-radio"

    def test_default_factory_routes_tls_when_both_paths_set(self) -> None:
        """Setting both ``tls.cert_path`` and ``tls.key_path`` makes the
        factory build an SSLContext and route through ``listener(tls=True)``."""
        import chumicro_sockets as sockets_mod

        captured: dict = {}
        sentinel_context = object()
        sentinel_listener = FakeListener([])

        def fake_ssl_paths(*, cert_path, key_path):
            captured["cert_path"] = cert_path
            captured["key_path"] = key_path
            return sentinel_context

        def fake_tls(host, port, *, tls=False, context=None, radio=None):
            captured["host"] = host
            captured["port"] = port
            captured["context"] = context
            captured["radio"] = radio
            return sentinel_listener

        original_ssl = sockets_mod.ssl_context_with_cert_and_key_paths
        original_tls = sockets_mod.listener
        sockets_mod.ssl_context_with_cert_and_key_paths = fake_ssl_paths
        sockets_mod.listener = fake_tls
        try:
            server = HttpServer.from_config(
                {
                    "http_server.bind_port": 8443,
                    "http_server.tls.cert_path": "/etc/cert.pem",
                    "http_server.tls.key_path": "/etc/key.pem",
                },
            )
            server._transport_factory()  # noqa: SLF001 — trigger lazy
        finally:
            sockets_mod.ssl_context_with_cert_and_key_paths = original_ssl
            sockets_mod.listener = original_tls

        assert captured["cert_path"] == "/etc/cert.pem"
        assert captured["key_path"] == "/etc/key.pem"
        assert captured["context"] is sentinel_context
        assert captured["host"] == "0.0.0.0"
        assert captured["port"] == 8443

    def test_default_factory_routes_tls_when_explicit_ssl_context(self) -> None:
        """An explicit ``ssl_context=`` arg forces TLS without needing
        cert/key paths in config — the caller built the context already."""
        import chumicro_sockets as sockets_mod

        captured: dict = {}
        sentinel_context = object()

        def fake_tls(host, port, *, tls=False, context=None, radio=None):
            captured["context"] = context
            return FakeListener([])

        original_tls = sockets_mod.listener
        sockets_mod.listener = fake_tls
        try:
            server = HttpServer.from_config({}, ssl_context=sentinel_context)
            server._transport_factory()  # noqa: SLF001
        finally:
            sockets_mod.listener = original_tls

        assert captured["context"] is sentinel_context

    def test_half_tls_config_raises_missing_config_key(self) -> None:
        """``cert_path`` set but ``key_path`` missing (or vice versa)
        raises ``MissingConfigKey``.  Both-or-neither is the only valid
        TLS config shape."""
        from chumicro_config import MissingConfigKey

        with raises(MissingConfigKey):
            HttpServer.from_config(
                {"http_server.tls.cert_path": "/etc/cert.pem"},
            )
        with raises(MissingConfigKey):
            HttpServer.from_config(
                {"http_server.tls.key_path": "/etc/key.pem"},
            )

    def test_does_not_raise_on_empty_config(self) -> None:
        """Documents the asymmetry vs ``MQTTClient.from_config``:
        empty config + no transport_factory override is valid input.
        Unlike mqtt, no MissingConfigKey is ever raised when nothing
        is configured (both-or-neither TLS is the only loud check)."""
        import chumicro_sockets as sockets_mod

        original = sockets_mod.listener
        sockets_mod.listener = (
            lambda host, port, *, radio=None: FakeListener([])
        )
        try:
            server = HttpServer.from_config({})
        finally:
            sockets_mod.listener = original
        assert server._max_connections > 0  # noqa: SLF001 — sanity

    def test_skipped_factory_module_raises_runtime_error(self) -> None:
        """When ``chumicro_sockets.sockets_factory`` is excluded
        via ``__chumicro_skip_factories__``, the default branch of
        ``from_config`` raises ``RuntimeError`` naming the bypass
        kwarg instead of leaking ``ImportError``.  CPython-only —
        sys.modules None-sentinel is CPython-specific; the
        translation behavior itself is runtime-agnostic.
        """
        import sys  # noqa: PLC0415

        from chumicro_test_harness import skip  # noqa: PLC0415

        if sys.implementation.name != "cpython":
            skip("sys.modules None-sentinel is CPython-specific")

        original = sys.modules.get("chumicro_sockets.sockets_factory")
        sys.modules["chumicro_sockets.sockets_factory"] = None
        try:
            try:
                HttpServer.from_config({})
            except RuntimeError as exception:
                assert "transport_factory=" in str(exception)
                assert "__chumicro_skip_factories__" in str(exception)
            else:
                raise AssertionError("expected RuntimeError")
        finally:
            if original is None:
                sys.modules.pop("chumicro_sockets.sockets_factory", None)
            else:
                sys.modules["chumicro_sockets.sockets_factory"] = original
