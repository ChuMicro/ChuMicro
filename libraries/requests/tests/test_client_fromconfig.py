"""requests client: ``HttpClient.from_config`` manifest key handling."""

from chumicro_requests import HttpClient
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector


class TestFromConfig:
    """``HttpClient.from_config`` reads the manifest's optional keys with
    sensible fall-back defaults.  No key is ever required — host/port
    live on each request URL, so the auto-built transport_factory
    reads zero config keys."""

    @staticmethod
    def _injected_factory():
        """Return a transport_factory that hands back a scripted
        FakeSocketConnector per call — host/port/use_tls captured for
        assertions."""
        captured: list = []

        def factory(host, port, use_tls):
            captured.append((host, port, use_tls))
            return FakeSocketConnector(
                actions=["dns_ok", "tcp_ok"], socket=FakeSocket(),
            )

        return factory, captured

    def test_reads_all_keys_from_config(self):
        """A complete config dict populates every documented manifest key."""

        factory, _ = self._injected_factory()
        config = {
            "requests.default_timeout_ms": 1234,
            "requests.default_max_redirects": 9,
            "requests.user_agent": "test-agent/1.0",
            "requests.max_body_bytes": 4096,
        }
        client = HttpClient.from_config(config, transport_factory=factory)
        assert client._default_timeout_ms == 1234  # noqa: SLF001
        assert client._default_max_redirects == 9  # noqa: SLF001
        assert client._user_agent == "test-agent/1.0"  # noqa: SLF001
        assert client._max_body_bytes == 4096  # noqa: SLF001

    def test_defaults_apply_when_keys_absent(self):
        """An empty config dict leaves every manifest key at its default.

        The auto-built transport_factory reads zero config keys
        (host/port live on each request URL), so an empty config is
        valid input and no ``MissingConfigKey`` is ever raised.
        """
        from chumicro_requests._wire import (
            DEFAULT_MAX_BODY_BYTES,
            DEFAULT_MAX_REDIRECTS,
            DEFAULT_TIMEOUT_MS,
        )

        factory, _ = self._injected_factory()
        client = HttpClient.from_config({}, transport_factory=factory)
        assert client._default_timeout_ms == DEFAULT_TIMEOUT_MS  # noqa: SLF001
        assert client._default_max_redirects == DEFAULT_MAX_REDIRECTS  # noqa: SLF001
        # user_agent=None falls through to the library default string.
        assert client._user_agent == "chumicro-requests/0.1"  # noqa: SLF001
        assert client._max_body_bytes == DEFAULT_MAX_BODY_BYTES  # noqa: SLF001

    def test_partial_config_mixes_overrides_with_defaults(self):
        """Caller-set keys win; absent keys take defaults."""
        from chumicro_requests._wire import (
            DEFAULT_MAX_REDIRECTS,
            DEFAULT_TIMEOUT_MS,
        )

        factory, _ = self._injected_factory()
        client = HttpClient.from_config(
            {"requests.user_agent": "halfway/0.1"},
            transport_factory=factory,
        )
        assert client._user_agent == "halfway/0.1"  # noqa: SLF001
        assert client._default_timeout_ms == DEFAULT_TIMEOUT_MS  # noqa: SLF001 — default
        assert client._default_max_redirects == DEFAULT_MAX_REDIRECTS  # noqa: SLF001 — default

    def test_explicit_transport_factory_bypasses_auto_factory(self):
        """Passing a transport_factory skips the auto-built one entirely
        — caller owns the connection-opening behavior."""

        factory, _ = self._injected_factory()
        client = HttpClient.from_config({}, transport_factory=factory)
        assert client._transport_factory is factory  # noqa: SLF001

    def test_runtime_config_wrapper_works_too(self):
        """Real ``RuntimeConfig`` instance — same flat-key reads as a
        plain dict.  Confirms compatibility with ``chumicro_config.config``
        on a real device."""
        from chumicro_config import RuntimeConfig  # noqa: PLC0415

        factory, _ = self._injected_factory()
        config = RuntimeConfig({
            "requests.default_timeout_ms": 7777,
            "requests.user_agent": "rc-test/2",
        })
        client = HttpClient.from_config(config, transport_factory=factory)
        assert client._default_timeout_ms == 7777  # noqa: SLF001
        assert client._user_agent == "rc-test/2"  # noqa: SLF001

    def test_default_factory_threads_radio_and_ssl_context(self):
        """When neither *transport_factory* is passed, ``from_config``
        builds one via ``connector_factory(radio=…, ssl_context=…)``.
        Validates the wiring without needing a real socket by replacing
        the symbol on its home module (``chumicro_sockets.sockets_factory``);
        from_config lazy-imports through that path."""
        import chumicro_sockets.sockets_factory as sockets_factory_mod  # noqa: PLC0415

        captured: dict = {}
        sentinel_factory = lambda host, port, use_tls: FakeSocket()  # noqa: ARG005,E731

        def fake_connector_factory(*, radio=None, ssl_context=None):
            captured["radio"] = radio
            captured["ssl_context"] = ssl_context
            return sentinel_factory

        original = sockets_factory_mod.connector_factory
        sockets_factory_mod.connector_factory = fake_connector_factory
        try:
            client = HttpClient.from_config(
                {}, radio="fake-radio", ssl_context="fake-ctx",
            )
        finally:
            sockets_factory_mod.connector_factory = original

        assert captured == {"radio": "fake-radio", "ssl_context": "fake-ctx"}
        assert client._transport_factory is sentinel_factory  # noqa: SLF001

    def test_default_factory_does_not_raise_on_empty_config(self):
        """The requests default factory reads zero config keys
        (per-request URL carries host/port), so empty config plus no
        override is fine.  No MissingConfigKey is ever raised.
        """
        import chumicro_sockets.sockets_factory as sockets_factory_mod  # noqa: PLC0415

        sentinel_factory = lambda host, port, use_tls: FakeSocket()  # noqa: ARG005,E731

        def fake_connector_factory(*, radio=None, ssl_context=None):
            return sentinel_factory

        original = sockets_factory_mod.connector_factory
        sockets_factory_mod.connector_factory = fake_connector_factory
        try:
            # No raise: empty config + no factory override is fine.
            client = HttpClient.from_config({})
        finally:
            sockets_factory_mod.connector_factory = original

        assert client._transport_factory is sentinel_factory  # noqa: SLF001

    def test_skipped_factory_module_raises_runtime_error(self):
        """When ``chumicro_sockets.sockets_factory`` is excluded via
        ``__chumicro_skip_factories__``, the default branch of
        ``from_config`` raises ``RuntimeError`` naming the bypass
        kwarg instead of leaking ``ImportError``.  CPython-only
        because the sys.modules None-sentinel trick used to simulate
        the skipped state is CPython-specific; the translation
        behavior itself is runtime-agnostic.
        """
        import sys  # noqa: PLC0415

        from chumicro_test_harness import skip  # noqa: PLC0415

        if sys.implementation.name != "cpython":
            skip("sys.modules None-sentinel is CPython-specific")

        original = sys.modules.get("chumicro_sockets.sockets_factory")
        sys.modules["chumicro_sockets.sockets_factory"] = None
        try:
            try:
                HttpClient.from_config({})
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
