"""Tests for chumicro_websockets.sockets_factory.

Verifies the helper wiring: the factory lives in its own submodule,
``__init__.py`` doesn't re-export it, and the returned factory maps
``use_tls`` onto :func:`chumicro_sockets.connector` with the right
arguments.

Cross-runtime: pure-Python.  Module-level symbols are swapped via
``SwapAttribute`` from ``chumicro_test_harness.patching`` (instead of
``unittest.mock.patch``, which is CPython-only) so the tests run on
the MP / CP unix-ports too.
"""

import chumicro_sockets
from chumicro_test_harness.patching import SwapAttribute
from chumicro_websockets.sockets_factory import (
    chumicro_sockets_connector_factory,
    chumicro_sockets_listener,
)
from chumicro_websockets.testing import FakeListener


class TestSocketsFactory:
    def test_returns_callable(self):
        factory = chumicro_sockets_connector_factory()
        assert callable(factory)

    def test_plain_tcp_maps_to_tls_false(self):
        calls: list = []

        def fake_connector(host, port, *, tls, context, radio):
            calls.append((host, port, tls, context, radio))
            return "tcp-connector"

        factory = chumicro_sockets_connector_factory(radio="radio-handle")
        with SwapAttribute(chumicro_sockets, "connector", fake_connector):
            result = factory("example.com", 80, False)

        assert result == "tcp-connector"
        assert calls == [("example.com", 80, False, None, "radio-handle")]

    def test_tls_maps_to_tls_true_with_context(self):
        calls: list = []

        def fake_connector(host, port, *, tls, context, radio):
            calls.append((host, port, tls, context, radio))
            return "tls-connector"

        context = object()
        factory = chumicro_sockets_connector_factory(radio="radio", ssl_context=context)
        with SwapAttribute(chumicro_sockets, "connector", fake_connector):
            result = factory("example.com", 443, True)

        assert result == "tls-connector"
        assert calls == [("example.com", 443, True, context, "radio")]

    def test_default_ssl_context_is_none(self):
        calls: list = []

        def fake_connector(host, port, *, tls, context, radio):
            calls.append((host, port, tls, context, radio))
            return "tls-connector"

        factory = chumicro_sockets_connector_factory()
        with SwapAttribute(chumicro_sockets, "connector", fake_connector):
            factory("h", 443, True)

        assert calls == [("h", 443, True, None, None)]

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


class TestListenerFactory:
    def test_binds_via_listener_with_config_host_port(self):
        calls: list = []

        def fake_listener(host, port, *, radio):
            calls.append((host, port, radio))
            return "listener"

        config = {
            "websockets.server.host": "192.0.2.1",
            "websockets.server.port": 9001,
        }
        with SwapAttribute(chumicro_sockets, "listener", fake_listener):
            result = chumicro_sockets_listener(config, radio="radio-handle")

        assert result == "listener"
        assert calls == [("192.0.2.1", 9001, "radio-handle")]

    def test_defaults_to_all_interfaces_port_8765(self):
        calls: list = []

        def fake_listener(host, port, *, radio):
            calls.append((host, port, radio))
            return "listener"

        with SwapAttribute(chumicro_sockets, "listener", fake_listener):
            chumicro_sockets_listener({})

        assert calls == [("0.0.0.0", 8765, None)]

    def test_from_config_auto_listener_routes_through_the_factory(self):
        """No listener= means from_config builds one via the factory helper."""
        import chumicro_websockets.server as server_module
        from chumicro_websockets import WebSocketServer

        calls: list = []

        def fake_listener(host, port, *, radio):
            calls.append((host, port))
            return FakeListener()

        with SwapAttribute(chumicro_sockets, "listener", fake_listener):
            server = WebSocketServer.from_config(
                {"websockets.server.port": 7000}, _noop_connection,
            )

        assert calls == [("0.0.0.0", 7000)]
        assert server is not None
        del server_module  # imported only to assert the module path resolves

    def test_helper_not_re_exported_from_init(self):
        import chumicro_websockets

        assert "chumicro_sockets_listener" not in dir(chumicro_websockets)


def _noop_connection(connection):  # noqa: ARG001 - required on_connection shape
    return None
