"""CPython-only tests for chumicro_sockets.sockets_factory.connector_factory.

These cases use pytest's ``monkeypatch`` fixture to swap the module-
level ``chumicro_sockets.connector`` symbol out for an in-test fake.
``monkeypatch`` is a pytest concept with no portable cross-runtime
equivalent, so the cases live here under the ``_pytest`` suffix and
run on CPython only.

The factory's runtime-correctness contract — "produces a working
connector on each board" — is exercised end-to-end on real hardware in
``functional_tests/test_real_get.py`` (HTTP) and
``functional_tests/test_real_get_tls.py`` (HTTPS).
"""

#: CPython-only lane (pytest fixtures / host stdlib); not cross-runtime.
__chumicro_runtimes__ = ("cpython",)

from chumicro_sockets.sockets_factory import connector_factory


class TestConnectorFactory:
    """The convenience factory maps ``use_tls`` onto ``connector(tls=)``."""

    def test_plain_tcp_maps_to_tls_false(self, monkeypatch):
        calls = []

        def fake_connector(host, port, *, tls, context, radio):
            calls.append((host, port, tls, context, radio))
            return "tcp-connector"

        monkeypatch.setattr("chumicro_sockets.connector", fake_connector)

        factory = connector_factory(radio="my-radio")
        result = factory("example.test", 80, False)
        assert result == "tcp-connector"
        assert calls == [("example.test", 80, False, None, "my-radio")]

    def test_tls_maps_to_tls_true_with_context(self, monkeypatch):
        calls = []

        def fake_connector(host, port, *, tls, context, radio):
            calls.append((host, port, tls, context, radio))
            return "tls-connector"

        monkeypatch.setattr("chumicro_sockets.connector", fake_connector)

        factory = connector_factory(radio=None, ssl_context="ctx")
        result = factory("example.test", 443, True)
        assert result == "tls-connector"
        assert calls == [("example.test", 443, True, "ctx", None)]

    def test_plain_tcp_ignores_ssl_context(self, monkeypatch):
        """A supplied *ssl_context* rides only the TLS hop — a plain-TCP
        hop passes ``context=None`` so the connector never wraps."""
        calls = []

        def fake_connector(host, port, *, tls, context, radio):
            calls.append((host, port, tls, context, radio))
            return "tcp-connector"

        monkeypatch.setattr("chumicro_sockets.connector", fake_connector)

        factory = connector_factory(radio=None, ssl_context="ctx")
        result = factory("example.test", 80, False)
        assert result == "tcp-connector"
        assert calls == [("example.test", 80, False, None, None)]
