"""Tests for chumicro_websockets.sockets_factory.

Verifies the helper wiring: the factory lives in its own submodule,
``__init__.py`` doesn't re-export it, and the returned factory routes
TLS / non-TLS to the right :mod:`chumicro_sockets` connector with
the right arguments.

Cross-runtime: pure-Python.  Module-level symbols are swapped via
``SwapAttribute`` from ``chumicro_test_harness.patching`` (instead of
``unittest.mock.patch``, which is CPython-only) so the tests run on
the MP / CP unix-ports too.
"""

import chumicro_sockets
from chumicro_test_harness.patching import SwapAttribute
from chumicro_websockets.sockets_factory import chumicro_sockets_connector_factory


class TestSocketsFactory:
    def test_returns_callable(self):
        factory = chumicro_sockets_connector_factory()
        assert callable(factory)

    def test_plain_tcp_routes_to_tcp_client_connector(self):
        tcp_calls: list = []
        tls_calls: list = []

        def fake_tcp(host, port, *, radio):
            tcp_calls.append((host, port, radio))
            return "tcp-connector"

        def fake_tls(host, port, *, context, radio):
            tls_calls.append((host, port, context, radio))
            return "tls-connector"

        factory = chumicro_sockets_connector_factory(radio="radio-handle")
        with SwapAttribute(chumicro_sockets, "tcp_client_connector", fake_tcp), \
                SwapAttribute(chumicro_sockets, "tls_client_connector", fake_tls):
            result = factory("example.com", 80, False)

        assert result == "tcp-connector"
        assert tcp_calls == [("example.com", 80, "radio-handle")]
        assert tls_calls == []

    def test_tls_routes_to_tls_client_connector(self):
        tcp_calls: list = []
        tls_calls: list = []

        def fake_tcp(host, port, *, radio):
            tcp_calls.append((host, port, radio))
            return "tcp-connector"

        def fake_tls(host, port, *, context, radio):
            tls_calls.append((host, port, context, radio))
            return "tls-connector"

        context = object()
        factory = chumicro_sockets_connector_factory(radio="radio", ssl_context=context)
        with SwapAttribute(chumicro_sockets, "tcp_client_connector", fake_tcp), \
                SwapAttribute(chumicro_sockets, "tls_client_connector", fake_tls):
            result = factory("example.com", 443, True)

        assert result == "tls-connector"
        assert tls_calls == [("example.com", 443, context, "radio")]
        assert tcp_calls == []

    def test_default_ssl_context_is_none(self):
        tls_calls: list = []

        def fake_tls(host, port, *, context, radio):
            tls_calls.append((host, port, context, radio))
            return "tls-connector"

        def fake_tcp(host, port, *, radio):
            return "tcp-connector"

        factory = chumicro_sockets_connector_factory()
        with SwapAttribute(chumicro_sockets, "tls_client_connector", fake_tls), \
                SwapAttribute(chumicro_sockets, "tcp_client_connector", fake_tcp):
            factory("h", 443, True)

        assert tls_calls == [("h", 443, None, None)]

    def test_helper_not_re_exported_from_init(self):
        """``__init__.py`` must NOT re-export the helper.

        The deploy-time AST walker only follows imports referenced by the
        user's app.  If __init__.py pulled in sockets_factory.py, every
        consumer would pay the chumicro-sockets deploy cost — even ones
        that inject a custom transport.
        """
        import chumicro_websockets

        assert "chumicro_sockets_connector_factory" not in dir(chumicro_websockets)
        assert "chumicro_sockets_connector_factory" not in chumicro_websockets.__all__
