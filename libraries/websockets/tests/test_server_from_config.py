"""WebSocket server tests (chumicro_websockets.server): from_config."""

from chumicro_websockets import WebSocketServer
from chumicro_websockets.testing import FakeListener


def _noop_connection(_conn):
    """Default ``on_connection`` for tests that don't care about callbacks."""


class TestServerFromConfig:
    """``WebSocketServer.from_config`` reads the server-side keys from
    the ``[tool.chumicro.config]`` manifest with sensible defaults.
    All optional — defaults to ``0.0.0.0:8765`` with the library's
    default ``max_message_bytes``.

    Like ntp's from_config (and unlike mqtt's), no key is required —
    a sensible bind target exists when none is supplied.  ``listener=``
    overrides the auto-built listener; ``on_connection`` is required
    positional because it's a callback the user must provide."""

    def test_reads_max_message_bytes_from_config(self) -> None:
        listener = FakeListener()
        server = WebSocketServer.from_config(
            {"websockets.server.max_message_bytes": 4096},
            _noop_connection,
            listener=listener,
        )
        assert server._max_message_bytes == 4096  # noqa: SLF001
        assert server._listener is listener  # noqa: SLF001

    def test_defaults_apply_when_keys_absent(self) -> None:
        """Empty config → max_message_bytes falls back to library default."""
        from chumicro_websockets._wire import DEFAULT_MAX_MESSAGE_BYTES
        listener = FakeListener()
        server = WebSocketServer.from_config(
            {}, _noop_connection, listener=listener,
        )
        assert server._max_message_bytes == DEFAULT_MAX_MESSAGE_BYTES  # noqa: SLF001

    def test_explicit_listener_bypasses_auto_built(self) -> None:
        """Passing listener= skips the chumicro_sockets.listener
        path entirely — caller owns the bind/listen behavior."""
        listener = FakeListener()
        server = WebSocketServer.from_config(
            {
                "websockets.server.host": "ignored.test",
                "websockets.server.port": 9999,
            },
            _noop_connection,
            listener=listener,
        )
        assert server._listener is listener  # noqa: SLF001

    def test_runtime_config_wrapper_works_too(self) -> None:
        """Real ``RuntimeConfig`` instance — same flat-key reads as a dict."""
        from chumicro_config import RuntimeConfig
        listener = FakeListener()
        config = RuntimeConfig({"websockets.server.max_message_bytes": 8192})
        server = WebSocketServer.from_config(
            config, _noop_connection, listener=listener,
        )
        assert server._max_message_bytes == 8192  # noqa: SLF001

    def test_auto_listener_threads_host_port_and_radio(self) -> None:
        """When no listener is passed, ``from_config`` builds one via
        ``chumicro_sockets.listener(host, port, radio=...)``
        using config-supplied host/port (or the library defaults)."""
        import chumicro_sockets as sockets_mod

        listener = FakeListener()
        captured: dict = {}

        def fake_listener(host, port, *, radio=None):
            captured["host"] = host
            captured["port"] = port
            captured["radio"] = radio
            return listener

        original = sockets_mod.listener
        sockets_mod.listener = fake_listener
        try:
            server = WebSocketServer.from_config(
                {
                    "websockets.server.host": "10.0.0.7",
                    "websockets.server.port": 8443,
                },
                _noop_connection,
                radio="fake-radio",
            )
        finally:
            sockets_mod.listener = original

        assert captured == {
            "host": "10.0.0.7", "port": 8443, "radio": "fake-radio",
        }
        assert server._listener is listener  # noqa: SLF001

    def test_auto_listener_falls_back_to_library_defaults(self) -> None:
        """Empty config → bind to 0.0.0.0:8765 (library-convention port)."""
        import chumicro_sockets as sockets_mod

        listener = FakeListener()
        captured: dict = {}

        def fake_listener(host, port, *, radio=None):
            captured["host"] = host
            captured["port"] = port
            return listener

        original = sockets_mod.listener
        sockets_mod.listener = fake_listener
        try:
            WebSocketServer.from_config({}, _noop_connection)
        finally:
            sockets_mod.listener = original

        assert captured == {"host": "0.0.0.0", "port": 8765}

    def test_accept_path_kwarg_passes_through(self) -> None:
        """accept_path is a per-deploy app-routing knob, not a config
        manifest key.  from_config still accepts it as a kwarg."""
        listener = FakeListener()
        server = WebSocketServer.from_config(
            {}, _noop_connection,
            listener=listener,
            accept_path="/echo",
        )
        assert server._accept_path == "/echo"  # noqa: SLF001
