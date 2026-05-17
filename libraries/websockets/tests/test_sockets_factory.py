"""Tests for chumicro_websockets.sockets_factory.

Verifies the helper wiring: the factory lives in its own submodule,
``__init__.py`` doesn't re-export it, and the returned factory routes
TLS / non-TLS to the right :mod:`chumicro_sockets` constructor with
the right arguments.

Cross-runtime: pure-Python.  The original suite used
``unittest.mock.patch`` (CPython-only) to swap module-level symbols;
this version does the same swap manually with ``setattr`` /
``try`` / ``finally`` so the tests run on the MP / CP unix-ports too.
"""

import chumicro_sockets
from chumicro_websockets.sockets_factory import chumicro_sockets_factory


class _SwapAttribute:
    """Context manager — swap ``module.name`` with a stand-in, restore on exit."""

    def __init__(self, module: object, name: str, replacement: object) -> None:
        self.module = module
        self.name = name
        self.replacement = replacement
        self._original: object = None
        self._had_attr: bool = False

    def __enter__(self) -> "_SwapAttribute":
        self._had_attr = hasattr(self.module, self.name)
        if self._had_attr:
            self._original = getattr(self.module, self.name)
        setattr(self.module, self.name, self.replacement)
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback) -> bool:
        if self._had_attr:
            setattr(self.module, self.name, self._original)
        else:
            delattr(self.module, self.name)
        return False


class TestSocketsFactory:
    def test_returns_callable(self):
        factory = chumicro_sockets_factory()
        assert callable(factory)

    def test_plain_tcp_routes_to_tcp_client_socket(self):
        tcp_calls: list = []
        tls_calls: list = []

        def fake_tcp(host, port, *, radio):
            tcp_calls.append((host, port, radio))
            return "tcp-socket"

        def fake_tls(host, port, *, context, radio):
            tls_calls.append((host, port, context, radio))
            return "tls-socket"

        factory = chumicro_sockets_factory(radio="radio-handle")
        with _SwapAttribute(chumicro_sockets, "tcp_client_socket", fake_tcp), \
                _SwapAttribute(chumicro_sockets, "tls_client_socket", fake_tls):
            result = factory("example.com", 80, False)

        assert result == "tcp-socket"
        assert tcp_calls == [("example.com", 80, "radio-handle")]
        assert tls_calls == []

    def test_tls_routes_to_tls_client_socket(self):
        tcp_calls: list = []
        tls_calls: list = []

        def fake_tcp(host, port, *, radio):
            tcp_calls.append((host, port, radio))
            return "tcp-socket"

        def fake_tls(host, port, *, context, radio):
            tls_calls.append((host, port, context, radio))
            return "tls-socket"

        context = object()
        factory = chumicro_sockets_factory(radio="radio", ssl_context=context)
        with _SwapAttribute(chumicro_sockets, "tcp_client_socket", fake_tcp), \
                _SwapAttribute(chumicro_sockets, "tls_client_socket", fake_tls):
            result = factory("example.com", 443, True)

        assert result == "tls-socket"
        assert tls_calls == [("example.com", 443, context, "radio")]
        assert tcp_calls == []

    def test_default_ssl_context_is_none(self):
        tls_calls: list = []

        def fake_tls(host, port, *, context, radio):
            tls_calls.append((host, port, context, radio))
            return "tls-socket"

        def fake_tcp(host, port, *, radio):
            return "tcp-socket"

        factory = chumicro_sockets_factory()
        with _SwapAttribute(chumicro_sockets, "tls_client_socket", fake_tls), \
                _SwapAttribute(chumicro_sockets, "tcp_client_socket", fake_tcp):
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

        assert "chumicro_sockets_factory" not in dir(chumicro_websockets)
        assert "chumicro_sockets_factory" not in chumicro_websockets.__all__
