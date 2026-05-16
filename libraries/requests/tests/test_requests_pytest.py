"""CPython-only tests for chumicro_requests.sockets_factory.chumicro_sockets_factory.

These cases use pytest's ``monkeypatch`` fixture to swap the module-
level ``chumicro_sockets.tcp_client_socket`` / ``tls_client_socket``
symbols out for in-test fakes.  ``monkeypatch`` is a pytest concept
with no portable cross-runtime equivalent, so the cases live here
under the ``_pytest`` suffix and run on CPython only.

The factory's runtime-correctness contract — "produces a working
socket on each board" — is exercised end-to-end on real hardware in
``functional_tests/test_real_get.py`` (HTTP) and
``functional_tests/test_real_get_tls.py`` (HTTPS).
"""

#: CPython-only lane (pytest fixtures / host stdlib); not cross-runtime.
__chumicro_runtimes__ = ("cpython",)

from chumicro_requests.sockets_factory import chumicro_sockets_factory


class TestChumicroSocketsFactory:
    """The convenience factory dispatches on ``use_tls``."""

    def test_plain_tcp_routes_to_tcp_client_socket(self, monkeypatch):
        calls = []

        def fake_tcp(host, port, *, radio):
            calls.append(("tcp", host, port, radio))
            return "tcp-socket"

        def fake_tls(host, port, *, context, radio):
            calls.append(("tls", host, port, context, radio))
            return "tls-socket"  # pragma: no cover - shouldn't be hit here

        from chumicro_sockets import (
            tcp_client_socket as real_tcp,  # noqa: F401 — verify import path
        )

        monkeypatch.setattr("chumicro_sockets.tcp_client_socket", fake_tcp)
        monkeypatch.setattr("chumicro_sockets.tls_client_socket", fake_tls)

        factory = chumicro_sockets_factory(radio="my-radio")
        result = factory("example.test", 80, False)
        assert result == "tcp-socket"
        assert calls == [("tcp", "example.test", 80, "my-radio")]

    def test_tls_routes_to_tls_client_socket(self, monkeypatch):
        calls = []

        def fake_tcp(host, port, *, radio):
            calls.append(("tcp", host, port, radio))
            return "tcp-socket"  # pragma: no cover

        def fake_tls(host, port, *, context, radio):
            calls.append(("tls", host, port, context, radio))
            return "tls-socket"

        monkeypatch.setattr("chumicro_sockets.tcp_client_socket", fake_tcp)
        monkeypatch.setattr("chumicro_sockets.tls_client_socket", fake_tls)

        factory = chumicro_sockets_factory(radio=None, ssl_context="ctx")
        result = factory("example.test", 443, True)
        assert result == "tls-socket"
        assert calls == [("tls", "example.test", 443, "ctx", None)]
