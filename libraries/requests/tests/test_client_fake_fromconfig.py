"""requests client: FakeHttpClient, from_config."""

from chumicro_requests import (
    HttpBusyError,
    HttpClient,
    HttpError,
    HttpTimeoutError,
)
from chumicro_sockets.testing import FakeSocket
from chumicro_test_harness.assertions import raises


class TestFakeHttpClient:
    """The host-only :class:`FakeHttpClient` mirrors the real client surface."""

    def test_scripted_response_completes_after_handle(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(
            status=200,
            body=b'{"temp_f": 72}',
            headers={"Content-Type": "application/json"},
        )
        handle = fake.get("http://api.example.test/weather")
        assert not handle.done
        assert fake.busy is True
        assert fake.check(now_ms=0) is True

        fake.handle(now_ms=0)
        assert handle.done
        assert fake.busy is False
        response = handle.result
        assert response.status_code == 200
        assert response.body == b'{"temp_f": 72}'
        assert response.headers["content-type"] == "application/json"
        assert response.url == "http://api.example.test/weather"

    def test_call_recording(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(body=b"")
        fake.get("http://example.test/", headers={"X-Foo": "bar"}, timeout_ms=99)

        assert len(fake.calls) == 1
        call = fake.calls[0]
        assert call.method == "GET"
        assert call.url == "http://example.test/"
        assert call.headers == {"X-Foo": "bar"}
        assert call.timeout_ms == 99

    def test_scripted_error_propagates(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_error(HttpTimeoutError("simulated timeout"))
        handle = fake.get("http://example.test/")
        fake.handle(now_ms=0)
        assert handle.done
        assert isinstance(handle.error, HttpTimeoutError)
        with raises(HttpTimeoutError, match="simulated"):
            _ = handle.result

    def test_enqueue_error_rejects_non_http_error(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        with raises(TypeError, match="HttpError"):
            fake.enqueue_error(ValueError("not an HttpError"))

    def test_get_without_scripted_response_raises(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        with raises(HttpError, match="no scripted responses"):
            fake.get("http://example.test/")

    def test_busy_during_in_flight(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(body=b"")
        fake.get("http://example.test/")
        with raises(HttpBusyError, match="busy"):
            fake.get("http://example.test/two")

    def test_check_false_when_idle(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        assert fake.check(now_ms=0) is False

    def test_handle_when_idle_is_noop(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.handle(now_ms=0)  # safe no-op
        # ``handle`` on an idle client must not accidentally start work.
        assert fake.check(now_ms=0) is False

    def test_responses_consumed_fifo(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(status=200, body=b"first")
        fake.enqueue_response(status=404, body=b"")

        handle_one = fake.get("http://example.test/one")
        fake.handle(now_ms=0)
        assert handle_one.result.body == b"first"

        handle_two = fake.get("http://example.test/two")
        fake.handle(now_ms=0)
        assert handle_two.result.status_code == 404

    def test_headers_as_iterable(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(headers=[("X-Custom", "v"), ("Server", "nginx")])
        handle = fake.get("http://example.test/")
        fake.handle(now_ms=0)
        assert handle.result.headers["x-custom"] == "v"
        assert handle.result.headers["server"] == "nginx"

    def test_oversized_dropped_flag_round_trip(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(status=200, body=b"", oversized_dropped=True)
        handle = fake.get("http://example.test/")
        fake.handle(now_ms=0)
        assert handle.result.oversized_dropped is True


class TestFromConfig:
    """``HttpClient.from_config`` reads the manifest's optional keys with
    sensible fall-back defaults.  Like ntp's from_config (and unlike
    mqtt's), no key is ever required — host/port live on each request
    URL, so the auto-built connection_factory reads zero config keys."""

    @staticmethod
    def _injected_factory():
        """Return a connection_factory that hands back a FakeSocket
        per call — host/port/use_tls captured for assertions."""
        captured: list = []

        def factory(host, port, use_tls):
            captured.append((host, port, use_tls))
            return FakeSocket()

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
        client = HttpClient.from_config(config, connection_factory=factory)
        assert client._default_timeout_ms == 1234  # noqa: SLF001
        assert client._default_max_redirects == 9  # noqa: SLF001
        assert client._user_agent == "test-agent/1.0"  # noqa: SLF001
        assert client._max_body_bytes == 4096  # noqa: SLF001

    def test_defaults_apply_when_keys_absent(self):
        """Empty config dict → every manifest key falls back to its default.

        Documents the asymmetry vs ``MQTTClient.from_config``: the
        auto-built connection_factory reads zero config keys (host/port
        live on each request URL), so an empty config is valid input
        and no ``MissingConfigKey`` is ever raised.
        """
        from chumicro_requests._wire import (
            DEFAULT_MAX_BODY_BYTES,
            DEFAULT_MAX_REDIRECTS,
            DEFAULT_TIMEOUT_MS,
        )

        factory, _ = self._injected_factory()
        client = HttpClient.from_config({}, connection_factory=factory)
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
            connection_factory=factory,
        )
        assert client._user_agent == "halfway/0.1"  # noqa: SLF001
        assert client._default_timeout_ms == DEFAULT_TIMEOUT_MS  # noqa: SLF001 — default
        assert client._default_max_redirects == DEFAULT_MAX_REDIRECTS  # noqa: SLF001 — default

    def test_explicit_connection_factory_bypasses_auto_factory(self):
        """Passing a connection_factory skips the auto-built one entirely
        — caller owns the connection-opening behavior."""

        factory, _ = self._injected_factory()
        client = HttpClient.from_config({}, connection_factory=factory)
        assert client._connection_factory is factory  # noqa: SLF001

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
        client = HttpClient.from_config(config, connection_factory=factory)
        assert client._default_timeout_ms == 7777  # noqa: SLF001
        assert client._user_agent == "rc-test/2"  # noqa: SLF001

    def test_default_factory_threads_radio_and_ssl_context(self):
        """When neither *connection_factory* is passed, ``from_config``
        builds one via ``chumicro_sockets_factory(radio=…, ssl_context=…)``.
        Validates the wiring without needing a real socket by replacing
        the symbol on its home module (``chumicro_requests.sockets_factory``);
        from_config lazy-imports through that path."""
        import chumicro_requests.sockets_factory as sockets_factory_mod  # noqa: PLC0415

        captured: dict = {}
        sentinel_factory = lambda host, port, use_tls: FakeSocket()  # noqa: ARG005,E731

        def fake_chumicro_sockets_factory(*, radio=None, ssl_context=None):
            captured["radio"] = radio
            captured["ssl_context"] = ssl_context
            return sentinel_factory

        original = sockets_factory_mod.chumicro_sockets_factory
        sockets_factory_mod.chumicro_sockets_factory = fake_chumicro_sockets_factory
        try:
            client = HttpClient.from_config(
                {}, radio="fake-radio", ssl_context="fake-ctx",
            )
        finally:
            sockets_factory_mod.chumicro_sockets_factory = original

        assert captured == {"radio": "fake-radio", "ssl_context": "fake-ctx"}
        assert client._connection_factory is sentinel_factory  # noqa: SLF001

    def test_default_factory_does_not_raise_on_empty_config(self):
        """Documents the asymmetry vs MQTTClient.from_config: the
        requests default factory reads zero config keys (per-request
        URL carries host/port), so empty config + no override is fine.
        Unlike mqtt, no MissingConfigKey is ever raised."""
        import chumicro_requests.sockets_factory as sockets_factory_mod  # noqa: PLC0415

        sentinel_factory = lambda host, port, use_tls: FakeSocket()  # noqa: ARG005,E731

        def fake_chumicro_sockets_factory(*, radio=None, ssl_context=None):
            return sentinel_factory

        original = sockets_factory_mod.chumicro_sockets_factory
        sockets_factory_mod.chumicro_sockets_factory = fake_chumicro_sockets_factory
        try:
            # No raise: empty config + no factory override is fine.
            client = HttpClient.from_config({})
        finally:
            sockets_factory_mod.chumicro_sockets_factory = original

        assert client._connection_factory is sentinel_factory  # noqa: SLF001

    def test_skipped_factory_module_raises_runtime_error(self):
        """When ``chumicro_requests.sockets_factory`` is excluded via
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

        original = sys.modules.get("chumicro_requests.sockets_factory")
        sys.modules["chumicro_requests.sockets_factory"] = None
        try:
            try:
                HttpClient.from_config({})
            except RuntimeError as exception:
                assert "connection_factory=" in str(exception)
                assert "__chumicro_skip_factories__" in str(exception)
            else:
                raise AssertionError("expected RuntimeError")
        finally:
            if original is None:
                sys.modules.pop("chumicro_requests.sockets_factory", None)
            else:
                sys.modules["chumicro_requests.sockets_factory"] = original
