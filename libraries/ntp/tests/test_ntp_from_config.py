"""``NTPClient.from_config`` + transport-factory construction tests.

Split from ``test_ntp.py`` so each file's whole-file load fits the
CircuitPython unix-lane heap budget (the CP lane execs whole files;
the state-machine suite and this construction suite together exceeded
the default budget).

Pure-Python, no third-party deps, no hardware.  Runs on CPython under
pytest and on the chumicro-test-harness on MicroPython / CircuitPython
unix ports.
"""

from chumicro_ntp import NTPClient
from chumicro_sockets.testing import FakeUDPSocket

# ---------------------------------------------------------------------------
# from_config — config-aware construction
# ---------------------------------------------------------------------------


class TestFromConfig:
    """``NTPClient.from_config`` reads the manifest's optional keys with
    sensible fall-back defaults.  Every key is optional — the public NTP
    pool is the documented fallback for ``ntp.server`` and the auto-built
    socket factory reads zero config keys, so an empty config is valid
    input."""

    @staticmethod
    def _injected_factory(sock: FakeUDPSocket):
        """Return a transport_factory that hands back *sock*."""
        return lambda: sock

    def test_reads_all_keys_from_config(self) -> None:
        """A complete config dict populates every documented manifest key."""
        sock = FakeUDPSocket()
        config = {
            "ntp.server": "time.example.com",
            "ntp.port": 4242,
            "ntp.timeout_ms": 1234,
        }
        client = NTPClient.from_config(
            config, transport_factory=self._injected_factory(sock),
        )
        assert client.server == "time.example.com"
        assert client.port == 4242
        assert client.timeout_ms == 1234
        # Deferred open: the factory is stored, not called, until query().
        assert client.socket is None
        client.query()
        assert client.socket is sock

    def test_defaults_apply_when_keys_absent(self) -> None:
        """Empty config dict falls back to every default."""
        sock = FakeUDPSocket()
        client = NTPClient.from_config(
            {}, transport_factory=self._injected_factory(sock),
        )
        assert client.server == "pool.ntp.org"
        assert client.port == 123
        assert client.timeout_ms == 5_000

    def test_partial_config_mixes_overrides_with_defaults(self) -> None:
        """Caller-set keys win; absent keys take defaults."""
        sock = FakeUDPSocket()
        client = NTPClient.from_config(
            {"ntp.timeout_ms": 250},
            transport_factory=self._injected_factory(sock),
        )
        assert client.server == "pool.ntp.org"  # default
        assert client.port == 123                # default
        assert client.timeout_ms == 250          # override

    def test_explicit_socket_bypasses_factory(self) -> None:
        """Passing a pre-built socket skips the auto-built factory entirely
        — caller owns the connection."""
        sock = FakeUDPSocket()
        client = NTPClient.from_config({}, socket=sock)
        assert client.socket is sock

    def test_explicit_transport_factory_is_deferred_to_first_query(self) -> None:
        """A custom transport_factory delegates socket creation, deferred:
        construction is side-effect-free and query() invokes the
        factory exactly once."""
        call_count = [0]
        sock = FakeUDPSocket()

        def factory():
            call_count[0] += 1
            return sock

        client = NTPClient.from_config({}, transport_factory=factory)
        assert call_count[0] == 0
        client.query()
        assert call_count[0] == 1
        assert client.socket is sock

    def test_runtime_config_wrapper_works_too(self) -> None:
        """Real ``RuntimeConfig`` instance — same flat-key reads as a
        plain dict.  Confirms compatibility with ``chumicro_config.config``
        on a real device."""
        from chumicro_config import RuntimeConfig  # noqa: PLC0415

        sock = FakeUDPSocket()
        config = RuntimeConfig({
            "ntp.server": "time.rc.test",
            "ntp.timeout_ms": 999,
        })
        client = NTPClient.from_config(
            config, transport_factory=self._injected_factory(sock),
        )
        assert client.server == "time.rc.test"
        assert client.timeout_ms == 999
        assert client.port == 123  # default

    def test_default_factory_invokes_udp_socket_factory(self) -> None:
        """When neither *socket* nor *transport_factory* is passed,
        ``from_config`` builds its transport off
        ``chumicro_sockets.sockets_factory.udp_socket_factory(radio=...)``.
        The ``radio`` binds at construction, but the socket only opens on
        the first query and comes out non-blocking."""
        captured: dict = {}
        opened: dict = {}
        sock = FakeUDPSocket()

        def fake_udp_socket_factory(*, radio=None):
            captured["radio"] = radio

            def _open():
                opened["socket"] = sock
                return sock

            return _open

        import chumicro_sockets.sockets_factory as sf  # noqa: PLC0415

        original = sf.udp_socket_factory
        sf.udp_socket_factory = fake_udp_socket_factory
        try:
            client = NTPClient.from_config({}, radio="fake-radio")
            # radio binds at construction; the socket stays deferred.
            assert captured == {"radio": "fake-radio"}
            assert opened == {}
            client.query()
        finally:
            sf.udp_socket_factory = original

        assert opened == {"socket": sock}
        assert client.socket is sock
        # Non-blocking was applied — FakeUDPSocket records setblocking calls.
        assert sock.blocking is False

    def test_default_factory_does_not_raise_on_empty_config(self) -> None:
        """Empty config dict is valid input even without socket=/transport_factory=.

        The default factory reads zero config keys (server/port live on
        the NTPClient itself, not on the socket), so there is nothing
        to require.
        """
        sock = FakeUDPSocket()

        def fake_udp_socket_factory(*, radio=None):
            return lambda: sock

        import chumicro_sockets.sockets_factory as sf  # noqa: PLC0415

        original = sf.udp_socket_factory
        sf.udp_socket_factory = fake_udp_socket_factory
        try:
            # No raise: empty config + no socket override is fine.
            client = NTPClient.from_config({})
        finally:
            sf.udp_socket_factory = original

        assert client.server == "pool.ntp.org"

    def test_skipped_factory_module_raises_runtime_error(self) -> None:
        """When ``chumicro_sockets.sockets_factory`` is excluded via
        ``__chumicro_skip_factories__``, the default branch of
        ``from_config`` raises ``RuntimeError`` naming the bypass
        kwargs instead of leaking ``ImportError``.  CPython-only —
        sys.modules None-sentinel is CPython-specific; the
        translation behavior itself is runtime-agnostic.
        """
        import sys  # noqa: PLC0415

        from chumicro_test_harness import skip  # noqa: PLC0415

        if sys.implementation.name != "cpython":
            skip("sys.modules None-sentinel is CPython-specific")

        original = sys.modules.get("chumicro_sockets.sockets_factory")
        sys.modules["chumicro_sockets.sockets_factory"] = None
        try:
            try:
                NTPClient.from_config({})
            except RuntimeError as exception:
                assert "transport_factory=" in str(exception)
                assert "socket=" in str(exception)
                assert "__chumicro_skip_factories__" in str(exception)
            else:
                raise AssertionError("expected RuntimeError")
        finally:
            if original is None:
                sys.modules.pop("chumicro_sockets.sockets_factory", None)
            else:
                sys.modules["chumicro_sockets.sockets_factory"] = original


def test_transport_factory_defers_open_to_first_query():
    """Construction with a factory is side-effect-free; query() opens once."""
    opened = []

    def factory():
        opened.append(1)
        return FakeUDPSocket()

    client = NTPClient(transport_factory=factory)
    assert opened == []
    assert client.socket is None

    client.query()
    assert opened == [1]
    assert client.socket is not None

    # A later query reuses the same socket — the factory ran once.
    client._result = None  # clear the in-flight guard for the re-query
    client.query()
    assert opened == [1]


def test_socket_and_factory_are_mutually_exclusive():
    from chumicro_test_harness import raises  # noqa: PLC0415

    with raises(ValueError):
        NTPClient(socket=FakeUDPSocket(), transport_factory=FakeUDPSocket)
    with raises(ValueError):
        NTPClient()


# udp_socket_factory socket-binding coverage lives in test_ntp_pytest.py
# (CPython-only; see that file's docstring for why).
