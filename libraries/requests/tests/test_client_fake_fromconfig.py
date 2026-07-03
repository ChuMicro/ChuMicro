"""requests client: FakeHttpClient, from_config."""

from chumicro_requests import (
    HttpBusyError,
    HttpClient,
    HttpError,
    HttpTimeoutError,
)
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector
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

    def test_post_records_body_and_method(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(body=b"created")
        handle = fake.post("http://api.example.test/widgets", body=b"payload")
        fake.handle(now_ms=0)
        assert handle.result.body == b"created"
        assert fake.calls[0].method == "POST"
        assert fake.calls[0].body == b"payload"
        assert fake.calls[0].json is None

    def test_post_records_json_payload(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(body=b"")
        fake.post("http://api.example.test/", json={"key": "value"})
        assert fake.calls[0].json == {"key": "value"}
        assert fake.calls[0].body is None

    def test_post_body_and_json_mutually_exclusive(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        with raises(ValueError, match="not both"):
            fake.post("http://api.example.test/", body=b"x", json={"k": "v"})

    def test_put_body_and_json_mutually_exclusive(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        with raises(ValueError, match="not both"):
            fake.put("http://api.example.test/", body=b"x", json={"k": "v"})

    def test_patch_body_and_json_mutually_exclusive(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        with raises(ValueError, match="not both"):
            fake.patch("http://api.example.test/", body=b"x", json={"k": "v"})

    def test_put_records_method(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(body=b"")
        fake.put("http://api.example.test/r/42", body=b"updated")
        assert fake.calls[0].method == "PUT"
        assert fake.calls[0].body == b"updated"

    def test_patch_records_method(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(body=b"")
        fake.patch("http://api.example.test/r/42", json={"name": "x"})
        assert fake.calls[0].method == "PATCH"
        assert fake.calls[0].json == {"name": "x"}

    def test_delete_records_method_no_body(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(body=b"")
        fake.delete("http://api.example.test/r/42")
        assert fake.calls[0].method == "DELETE"
        assert fake.calls[0].body is None
        assert fake.calls[0].json is None

    def test_on_done_fires_after_handle(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(body=b"hi")
        received = []
        handle = fake.get("http://api.example.test/", on_done=received.append)
        assert received == []
        fake.handle(now_ms=0)
        assert received == [handle]
        assert received[0].result.body == b"hi"

    def test_on_done_fires_on_error(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_error(HttpTimeoutError("simulated"))
        received = []
        fake.post(
            "http://api.example.test/", body=b"x", on_done=received.append,
        )
        fake.handle(now_ms=0)
        assert len(received) == 1
        assert isinstance(received[0].error, HttpTimeoutError)

    def test_max_redirects_passed_through_to_call_record(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(body=b"")
        fake.get("http://api.example.test/", max_redirects=3)
        assert fake.calls[0].max_redirects == 3

    def test_busy_blocks_any_verb(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(body=b"")
        fake.post("http://api.example.test/one", body=b"x")
        with raises(HttpBusyError):
            fake.delete("http://api.example.test/two")


class TestFromConfig:
    """``HttpClient.from_config`` reads the manifest's optional keys with
    sensible fall-back defaults.  No key is ever required — host/port
    live on each request URL, so the auto-built connector_factory
    reads zero config keys."""

    @staticmethod
    def _injected_factory():
        """Return a connector_factory that hands back a scripted
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
        client = HttpClient.from_config(config, connector_factory=factory)
        assert client._default_timeout_ms == 1234  # noqa: SLF001
        assert client._default_max_redirects == 9  # noqa: SLF001
        assert client._user_agent == "test-agent/1.0"  # noqa: SLF001
        assert client._max_body_bytes == 4096  # noqa: SLF001

    def test_defaults_apply_when_keys_absent(self):
        """An empty config dict leaves every manifest key at its default.

        The auto-built connector_factory reads zero config keys
        (host/port live on each request URL), so an empty config is
        valid input and no ``MissingConfigKey`` is ever raised.
        """
        from chumicro_requests._wire import (
            DEFAULT_MAX_BODY_BYTES,
            DEFAULT_MAX_REDIRECTS,
            DEFAULT_TIMEOUT_MS,
        )

        factory, _ = self._injected_factory()
        client = HttpClient.from_config({}, connector_factory=factory)
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
            connector_factory=factory,
        )
        assert client._user_agent == "halfway/0.1"  # noqa: SLF001
        assert client._default_timeout_ms == DEFAULT_TIMEOUT_MS  # noqa: SLF001 — default
        assert client._default_max_redirects == DEFAULT_MAX_REDIRECTS  # noqa: SLF001 — default

    def test_explicit_connector_factory_bypasses_auto_factory(self):
        """Passing a connector_factory skips the auto-built one entirely
        — caller owns the connection-opening behavior."""

        factory, _ = self._injected_factory()
        client = HttpClient.from_config({}, connector_factory=factory)
        assert client._connector_factory is factory  # noqa: SLF001

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
        client = HttpClient.from_config(config, connector_factory=factory)
        assert client._default_timeout_ms == 7777  # noqa: SLF001
        assert client._user_agent == "rc-test/2"  # noqa: SLF001

    def test_default_factory_threads_radio_and_ssl_context(self):
        """When neither *connector_factory* is passed, ``from_config``
        builds one via ``chumicro_sockets_connector_factory(radio=…, ssl_context=…)``.
        Validates the wiring without needing a real socket by replacing
        the symbol on its home module (``chumicro_requests.sockets_factory``);
        from_config lazy-imports through that path."""
        import chumicro_requests.sockets_factory as sockets_factory_mod  # noqa: PLC0415

        captured: dict = {}
        sentinel_factory = lambda host, port, use_tls: FakeSocket()  # noqa: ARG005,E731

        def fake_chumicro_sockets_connector_factory(*, radio=None, ssl_context=None):
            captured["radio"] = radio
            captured["ssl_context"] = ssl_context
            return sentinel_factory

        original = sockets_factory_mod.chumicro_sockets_connector_factory
        sockets_factory_mod.chumicro_sockets_connector_factory = (
            fake_chumicro_sockets_connector_factory
        )
        try:
            client = HttpClient.from_config(
                {}, radio="fake-radio", ssl_context="fake-ctx",
            )
        finally:
            sockets_factory_mod.chumicro_sockets_connector_factory = original

        assert captured == {"radio": "fake-radio", "ssl_context": "fake-ctx"}
        assert client._connector_factory is sentinel_factory  # noqa: SLF001

    def test_default_factory_does_not_raise_on_empty_config(self):
        """The requests default factory reads zero config keys
        (per-request URL carries host/port), so empty config plus no
        override is fine.  No MissingConfigKey is ever raised.
        """
        import chumicro_requests.sockets_factory as sockets_factory_mod  # noqa: PLC0415

        sentinel_factory = lambda host, port, use_tls: FakeSocket()  # noqa: ARG005,E731

        def fake_chumicro_sockets_connector_factory(*, radio=None, ssl_context=None):
            return sentinel_factory

        original = sockets_factory_mod.chumicro_sockets_connector_factory
        sockets_factory_mod.chumicro_sockets_connector_factory = (
            fake_chumicro_sockets_connector_factory
        )
        try:
            # No raise: empty config + no factory override is fine.
            client = HttpClient.from_config({})
        finally:
            sockets_factory_mod.chumicro_sockets_connector_factory = original

        assert client._connector_factory is sentinel_factory  # noqa: SLF001

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
                assert "connector_factory=" in str(exception)
                assert "__chumicro_skip_factories__" in str(exception)
            else:
                raise AssertionError("expected RuntimeError")
        finally:
            if original is None:
                sys.modules.pop("chumicro_requests.sockets_factory", None)
            else:
                sys.modules["chumicro_requests.sockets_factory"] = original
