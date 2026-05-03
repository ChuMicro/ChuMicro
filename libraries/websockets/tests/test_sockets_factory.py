"""Tests for chumicro_websockets.sockets_factory — slice 5.

Verifies the Decision 0042 sub-rule wiring: the helper lives in
its own submodule, ``__init__.py`` doesn't re-export it, and the
returned factory routes TLS / non-TLS to the right
:mod:`chumicro_sockets` constructor with the right arguments.
"""

from unittest import mock

from chumicro_websockets.sockets_factory import chumicro_sockets_factory


class TestSocketsFactory:
    def test_returns_callable(self):
        factory = chumicro_sockets_factory()
        assert callable(factory)

    def test_plain_tcp_routes_to_tcp_client_socket(self):
        factory = chumicro_sockets_factory(radio="radio-handle")
        with mock.patch(
            "chumicro_sockets.tcp_client_socket",
            return_value="tcp-socket",
        ) as tcp_mock, mock.patch(
            "chumicro_sockets.tls_client_socket",
            return_value="tls-socket",
        ) as tls_mock:
            result = factory("example.com", 80, False)
        tcp_mock.assert_called_once_with("example.com", 80, radio="radio-handle")
        tls_mock.assert_not_called()
        assert result == "tcp-socket"

    def test_tls_routes_to_tls_client_socket(self):
        context = object()
        factory = chumicro_sockets_factory(radio="radio", ssl_context=context)
        with mock.patch(
            "chumicro_sockets.tcp_client_socket",
            return_value="tcp-socket",
        ) as tcp_mock, mock.patch(
            "chumicro_sockets.tls_client_socket",
            return_value="tls-socket",
        ) as tls_mock:
            result = factory("example.com", 443, True)
        tls_mock.assert_called_once_with(
            "example.com",
            443,
            context=context,
            radio="radio",
        )
        tcp_mock.assert_not_called()
        assert result == "tls-socket"

    def test_default_ssl_context_is_none(self):
        factory = chumicro_sockets_factory()
        with mock.patch(
            "chumicro_sockets.tls_client_socket",
            return_value="tls-socket",
        ) as tls_mock, mock.patch("chumicro_sockets.tcp_client_socket"):
            factory("h", 443, True)
        tls_mock.assert_called_once_with("h", 443, context=None, radio=None)

    def test_helper_not_re_exported_from_init(self):
        """Decision 0042 sub-rule: __init__.py must NOT re-export the helper.

        The deploy-time AST walker only follows imports referenced by the
        user's app.  If __init__.py pulled in sockets_factory.py, every
        consumer would pay the chumicro-sockets deploy cost — even ones
        that inject a custom transport.
        """
        import chumicro_websockets

        assert "chumicro_sockets_factory" not in dir(chumicro_websockets)
        assert "chumicro_sockets_factory" not in chumicro_websockets.__all__
