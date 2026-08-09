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
    supplies an already-open listener and skips the auto-built factory;
    otherwise construction stores a listener factory and the bind is
    deferred to the first ``handle()`` tick.  ``on_connection`` is
    required positional because it's a callback the user must provide."""

    def test_reads_max_message_bytes_from_config(self) -> None:
        listener = FakeListener()
        server = WebSocketServer.from_config(
            {"websockets.server.max_message_bytes": 4096},
            _noop_connection,
            listener=listener,
        )
        assert server._max_message_bytes == 4096  # noqa: SLF001
        assert server.io_socket is listener  # noqa: SLF001

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
        assert server.io_socket is listener  # noqa: SLF001

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
        """When no listener is passed, ``from_config`` builds a factory
        over ``chumicro_sockets.listener(host, port, radio=...)`` using
        config-supplied host/port (or the library defaults), and the
        bind fires on the first ``handle()`` tick, not at construction."""
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
            assert captured == {}
            assert server.io_socket is None
            server.handle(0)
        finally:
            sockets_mod.listener = original

        assert captured == {
            "host": "10.0.0.7", "port": 8443, "radio": "fake-radio",
        }
        assert server.io_socket is listener  # noqa: SLF001

    def test_auto_listener_falls_back_to_library_defaults(self) -> None:
        """Empty config → the first handle() binds 0.0.0.0:8765 (library-convention port)."""
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
            server = WebSocketServer.from_config({}, _noop_connection)
            server.handle(0)
        finally:
            sockets_mod.listener = original

        assert captured == {"host": "0.0.0.0", "port": 8765}

    def test_skipped_factory_module_raises_runtime_error(self) -> None:
        """When ``chumicro_sockets.sockets_factory`` is excluded via
        ``__chumicro_skip_factories__``, the default branch of
        ``from_config`` raises ``RuntimeError`` naming both bypass
        kwargs instead of leaking ``ImportError``.  CPython-only —
        the sys.modules None-sentinel is CPython-specific; the
        translation behavior itself is runtime-agnostic.
        """
        import sys

        from chumicro_test_harness import skip

        if sys.implementation.name != "cpython":
            skip("sys.modules None-sentinel is CPython-specific")

        original = sys.modules.get("chumicro_sockets.sockets_factory")
        sys.modules["chumicro_sockets.sockets_factory"] = None
        try:
            try:
                WebSocketServer.from_config({}, _noop_connection)
            except RuntimeError as exception:
                assert "listener=" in str(exception)
                assert "listener_factory=" in str(exception)
                assert "__chumicro_skip_factories__" in str(exception)
            else:
                raise AssertionError("expected RuntimeError")
        finally:
            if original is None:
                sys.modules.pop("chumicro_sockets.sockets_factory", None)
            else:
                sys.modules["chumicro_sockets.sockets_factory"] = original

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


class TestDeferredListenerBind:
    """A server built with ``listener_factory=`` stores the factory
    without calling it; the first ``handle()`` tick invokes it exactly
    once, and until then the reactor contract reports no I/O interest
    and no deadline."""

    def test_factory_not_called_at_construction(self) -> None:
        """Construction is side-effect-free and the first handle() binds once,
        with later handles reusing the same listener."""
        calls = [0]
        listener = FakeListener()

        def factory():
            calls[0] += 1
            return listener

        server = WebSocketServer(
            on_connection=_noop_connection, listener_factory=factory,
        )
        assert calls[0] == 0
        assert server.io_socket is None

        server.handle(0)
        assert calls[0] == 1
        assert server.io_socket is listener
        server.handle(0)
        assert calls[0] == 1

    def test_prebind_reactor_contract(self) -> None:
        """Before the bind, io_interest is 0 (nothing to poll) and
        next_deadline is None (no connections), and check() stays True
        so the runner keeps ticking handle() toward the bind."""
        server = WebSocketServer(
            on_connection=_noop_connection,
            listener_factory=FakeListener,
        )
        assert server.io_interest(0) == 0
        assert server.next_deadline(0) is None
        assert server.check(0) is True

    def test_close_before_bind_never_calls_factory(self) -> None:
        """close() on a never-bound server marks it closed without invoking
        the factory, and a later handle() does not resurrect it."""
        calls = [0]

        def factory():
            calls[0] += 1
            return FakeListener()

        server = WebSocketServer(
            on_connection=_noop_connection, listener_factory=factory,
        )
        server.close()
        assert server.closed is True
        server.handle(0)
        assert calls[0] == 0

    def test_listener_and_factory_are_mutually_exclusive(self) -> None:
        """Neither or both listener seams raise ValueError, and a missing
        on_connection raises ValueError too."""
        from chumicro_test_harness import raises

        with raises(ValueError):
            WebSocketServer(
                FakeListener(), _noop_connection,
                listener_factory=FakeListener,
            )
        with raises(ValueError):
            WebSocketServer(on_connection=_noop_connection)
        with raises(ValueError):
            WebSocketServer(listener_factory=FakeListener)

    def test_from_config_accepts_explicit_listener_factory(self) -> None:
        """listener_factory= rides from_config verbatim, skipping the
        chumicro_sockets auto-build."""
        listener = FakeListener()
        server = WebSocketServer.from_config(
            {}, _noop_connection, listener_factory=lambda: listener,
        )
        assert server.io_socket is None
        server.handle(0)
        assert server.io_socket is listener


class TestConstructorPassthrough:
    """Constructor knobs with no manifest key ride ``from_config`` as
    keywords, and an explicit keyword wins over its config-derived
    value."""

    def test_tuning_kwarg_reaches_constructor(self) -> None:
        server = WebSocketServer.from_config(
            {}, _noop_connection, listener=FakeListener(),
            send_budget_per_tick=99,
        )
        assert server._send_budget_per_tick == 99  # noqa: SLF001

    def test_explicit_kwarg_wins_over_config(self) -> None:
        server = WebSocketServer.from_config(
            {"websockets.server.max_message_bytes": 4096},
            _noop_connection,
            listener=FakeListener(),
            max_message_bytes=512,
        )
        assert server._max_message_bytes == 512  # noqa: SLF001
