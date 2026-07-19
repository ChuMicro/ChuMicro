"""Cross-runtime tests for the generic transport factories.

Everything here swaps package-level bindings (``connector`` /
``listener`` / ``udp_socket`` / the TLS context builder) for recorders,
so it touches no per-runtime adapter and runs unmodified on CPython,
both unix-ports, and real boards.
"""

import chumicro_sockets
from chumicro_sockets import sockets_factory
from chumicro_test_harness.patching import SwapAttribute


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return object()


class TestConnectorFactory:
    def test_dispatches_host_port_tls(self):
        recorder = _Recorder()
        with SwapAttribute(chumicro_sockets, "connector", recorder):
            factory = sockets_factory.connector_factory(
                radio="R", ssl_context="CTX",
            )
            factory("example.com", 443, True)
        (args, kwargs), = recorder.calls
        assert args == ("example.com", 443)
        assert kwargs == {"tls": True, "context": "CTX", "radio": "R"}

    def test_plain_call_drops_context(self):
        recorder = _Recorder()
        with SwapAttribute(chumicro_sockets, "connector", recorder):
            factory = sockets_factory.connector_factory(ssl_context="CTX")
            factory("example.com", 80, False)
        (_, kwargs), = recorder.calls
        assert kwargs == {"tls": False, "context": None, "radio": None}

    def test_tls_call_without_context_passes_none(self):
        recorder = _Recorder()
        with SwapAttribute(chumicro_sockets, "connector", recorder):
            factory = sockets_factory.connector_factory()
            factory("h", 443, True)
        (args, kwargs), = recorder.calls
        assert args == ("h", 443)
        assert kwargs == {"tls": True, "context": None, "radio": None}


class TestFixedConnectorFactory:
    def test_closes_over_endpoint(self):
        recorder = _Recorder()
        with SwapAttribute(chumicro_sockets, "connector", recorder):
            factory = sockets_factory.fixed_connector_factory(
                "broker.local", 8883, ssl_context="CTX",
            )
            factory()
            factory()
        assert len(recorder.calls) == 2
        args, kwargs = recorder.calls[0]
        assert args == ("broker.local", 8883)
        assert kwargs == {"tls": True, "context": "CTX", "radio": None}

    def test_no_tls_without_context(self):
        recorder = _Recorder()
        with SwapAttribute(chumicro_sockets, "connector", recorder):
            sockets_factory.fixed_connector_factory("broker.local", 1883)()
        (_, kwargs), = recorder.calls
        assert kwargs["tls"] is False and kwargs["context"] is None


class TestListenerFactory:
    def test_plain(self):
        recorder = _Recorder()
        with SwapAttribute(chumicro_sockets, "listener", recorder):
            sockets_factory.listener_factory("0.0.0.0", 8080, radio="R")()
        (args, kwargs), = recorder.calls
        assert args == ("0.0.0.0", 8080)
        assert kwargs == {"radio": "R"}

    def test_tls_from_paths(self):
        listener_rec = _Recorder()
        context_rec = _Recorder()
        with SwapAttribute(chumicro_sockets, "listener", listener_rec), \
                SwapAttribute(
                    chumicro_sockets,
                    "ssl_context_with_cert_and_key_paths",
                    context_rec,
                ):
            sockets_factory.listener_factory(
                "0.0.0.0", 8443, cert_path="c.pem", key_path="k.pem",
            )()
        (_, ctx_kwargs), = context_rec.calls
        assert ctx_kwargs == {"cert_path": "c.pem", "key_path": "k.pem"}
        (args, kwargs), = listener_rec.calls
        assert args == ("0.0.0.0", 8443)
        assert kwargs["tls"] is True and kwargs["radio"] is None

    def test_explicit_context_wins(self):
        listener_rec = _Recorder()
        context_rec = _Recorder()
        with SwapAttribute(chumicro_sockets, "listener", listener_rec), \
                SwapAttribute(
                    chumicro_sockets,
                    "ssl_context_with_cert_and_key_paths",
                    context_rec,
                ):
            sockets_factory.listener_factory("h", 1, ssl_context="CTX")()
        assert context_rec.calls == []
        (_, kwargs), = listener_rec.calls
        assert kwargs["context"] == "CTX"


class TestUdpSocketFactory:
    def test_fresh_socket_per_call(self):
        recorder = _Recorder()
        with SwapAttribute(chumicro_sockets, "udp_socket", recorder):
            factory = sockets_factory.udp_socket_factory(radio="R")
            factory()
            factory()
        assert len(recorder.calls) == 2
        assert recorder.calls[0][1] == {"radio": "R"}
