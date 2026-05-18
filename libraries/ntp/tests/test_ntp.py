"""Tests for chumicro_ntp.

Pure-Python, no third-party deps, no hardware.  Runs on CPython under
pytest and on the chumicro-test-harness on MicroPython / CircuitPython
unix ports.

The bus and parser logic is exercised through the public ``NTPClient``
API by injecting ``FakeUDPSocket`` from chumicro-sockets.  No NTP
server is contacted.
"""

import chumicro_ntp
from chumicro_ntp import NTPClient, NTPError, NTPResult
from chumicro_ntp.core import _CLIENT_REQUEST, NTP_TO_UNIX, _parse_response
from chumicro_sockets.testing import FakeUDPSocket
from chumicro_test_harness.assertions import raises
from chumicro_timing.testing import FakeTicks

# ---------------------------------------------------------------------------
# Helpers — synthesize SNTP responses
# ---------------------------------------------------------------------------


def _server_response(unix_seconds: int) -> bytes:
    """Build a minimal valid SNTP server response.

    LI=0, VN=4, Mode=4 (server) → first byte 0x24.  Stratum 1 ("primary
    reference") so the parser doesn't reject as kiss-of-death.  All
    other fields zero except the transmit timestamp (bytes 40-47).
    """
    seconds_1900 = unix_seconds + NTP_TO_UNIX
    packet = bytearray(48)
    packet[0] = 0x24  # LI=0, VN=4, Mode=4
    packet[1] = 1     # stratum 1
    packet[40] = (seconds_1900 >> 24) & 0xFF
    packet[41] = (seconds_1900 >> 16) & 0xFF
    packet[42] = (seconds_1900 >> 8) & 0xFF
    packet[43] = seconds_1900 & 0xFF
    return bytes(packet)


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_public_exports_present() -> None:
    for name in ("NTPClient", "NTPError", "NTPResult"):
        assert hasattr(chumicro_ntp, name)


def test_ntp_error_is_oserror_subclass() -> None:
    """``NTPError`` subclasses OSError so transport-error catchers see it."""
    error = NTPError("oops")
    assert isinstance(error, OSError)


# ---------------------------------------------------------------------------
# _build_request / _parse_response
# ---------------------------------------------------------------------------


def test_client_request_packet_shape() -> None:
    assert len(_CLIENT_REQUEST) == 48
    # First byte: LI=0 (00), VN=4 (100), Mode=3 (011) → 0b00100011 = 0x23
    assert _CLIENT_REQUEST[0] == 0x23
    # All other bytes zero.
    assert _CLIENT_REQUEST[1:] == b"\x00" * 47


def test_parse_response_extracts_unix_seconds() -> None:
    target = 1_700_000_000  # arbitrary recent timestamp
    packet = _server_response(target)
    assert _parse_response(packet) == target


def test_parse_response_handles_post_2036_era_rollover() -> None:
    """A ~2042 timestamp (NTP era 1, 32-bit field wrapped) decodes correctly."""
    target = 2_300_000_000  # past the 2036 era-0 rollover
    # _server_response writes only the low 32 bits, exactly as the wire
    # does once the era-0 seconds field overflows.
    assert _parse_response(_server_response(target)) == target


def test_parse_response_rejects_short_packet() -> None:
    with raises(NTPError):
        _parse_response(b"\x00" * 16)


def test_parse_response_rejects_wrong_mode() -> None:
    packet = bytearray(_server_response(1))
    packet[0] = 0x23  # client mode (3) — invalid in a response
    with raises(NTPError):
        _parse_response(bytes(packet))


def test_parse_response_rejects_kiss_of_death() -> None:
    packet = bytearray(_server_response(1))
    packet[1] = 0  # stratum 0 = kiss-of-death
    with raises(NTPError):
        _parse_response(bytes(packet))


# ---------------------------------------------------------------------------
# NTPClient construction
# ---------------------------------------------------------------------------


def test_default_construction() -> None:
    sock = FakeUDPSocket()
    client = NTPClient(socket=sock)
    assert client.server == "pool.ntp.org"
    assert client.port == 123
    assert client.timeout_ms == 5_000
    assert client.busy is False
    assert client.socket is sock


def test_constructor_rejects_nonpositive_timeout() -> None:
    sock = FakeUDPSocket()
    with raises(ValueError):
        NTPClient(socket=sock, timeout_ms=0)
    with raises(ValueError):
        NTPClient(socket=sock, timeout_ms=-1)


def test_custom_server_and_port() -> None:
    sock = FakeUDPSocket()
    client = NTPClient(socket=sock, server="time.example.com", port=8123)
    assert client.server == "time.example.com"
    assert client.port == 8123


# ---------------------------------------------------------------------------
# query / check / handle — happy path
# ---------------------------------------------------------------------------


def test_query_sends_packet_and_records_destination() -> None:
    sock = FakeUDPSocket()
    ticks = FakeTicks()
    client = NTPClient(socket=sock, ticks=ticks, server="time.test", port=4242)
    client.query()
    assert len(sock.sent) == 1
    data, host, port = sock.sent[0]
    assert host == "time.test"
    assert port == 4242
    assert len(data) == 48
    assert data[0] == 0x23  # client request mode


def test_query_marks_client_busy_until_handle_completes() -> None:
    sock = FakeUDPSocket()
    ticks = FakeTicks()
    client = NTPClient(socket=sock, ticks=ticks)
    request = client.query()
    assert client.busy is True
    assert client.check(now_ms=0) is True
    assert request.done is False

    sock.enqueue_recv(_server_response(1_700_000_000))
    client.handle(now_ms=ticks.ticks_ms())
    assert request.done is True
    assert client.busy is False
    assert request.unix_seconds == 1_700_000_000


def test_handle_with_no_in_flight_request_is_noop() -> None:
    sock = FakeUDPSocket()
    client = NTPClient(socket=sock)
    client.handle(now_ms=0)  # must not crash
    # ``handle`` on an idle client must not accidentally mark the client busy.
    assert client.busy is False


def test_check_returns_false_when_idle() -> None:
    sock = FakeUDPSocket()
    client = NTPClient(socket=sock)
    assert client.check(now_ms=0) is False


def test_query_while_busy_raises() -> None:
    sock = FakeUDPSocket()
    client = NTPClient(socket=sock)
    client.query()
    with raises(RuntimeError):
        client.query()


# ---------------------------------------------------------------------------
# NTPResult
# ---------------------------------------------------------------------------


def test_unix_seconds_before_done_raises() -> None:
    result = NTPResult(ticks_started_ms=0)
    with raises(RuntimeError):
        _ = result.unix_seconds


def test_unix_seconds_when_errored_raises_underlying() -> None:
    sock = FakeUDPSocket()
    ticks = FakeTicks()
    client = NTPClient(
        socket=sock,
        timeout_ms=10,
        ticks=ticks,
    )
    request = client.query()
    # No response queued; advance time past the timeout and handle.
    ticks.advance(100)
    sock.enqueue_eagain_for_recv()  # simulate "no data this tick"
    client.handle(now_ms=ticks.ticks_ms())
    assert request.done is True
    assert isinstance(request.error, NTPError)
    with raises(NTPError):
        _ = request.unix_seconds


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


def test_handle_swallows_eagain_until_timeout() -> None:
    sock = FakeUDPSocket()
    ticks = FakeTicks()
    client = NTPClient(socket=sock, timeout_ms=200, ticks=ticks)
    request = client.query()
    ticks.advance(50)
    sock.enqueue_eagain_for_recv()
    client.handle(now_ms=ticks.ticks_ms())
    assert request.done is False  # still waiting — under timeout


def test_handle_times_out_when_no_data_arrives() -> None:
    sock = FakeUDPSocket()
    ticks = FakeTicks()
    client = NTPClient(socket=sock, timeout_ms=200, ticks=ticks)
    request = client.query()
    # Advance past the timeout, then handle returns "no data + EAGAIN".
    ticks.advance(500)
    sock.enqueue_eagain_for_recv()
    client.handle(now_ms=ticks.ticks_ms())
    assert request.done is True
    assert isinstance(request.error, NTPError)
    assert "timed out" in str(request.error)


def test_handle_timeout_via_zero_byte_recv() -> None:
    """Empty queue (no EAGAIN) and timeout elapsed → fail."""
    sock = FakeUDPSocket()
    ticks = FakeTicks()
    client = NTPClient(socket=sock, timeout_ms=200, ticks=ticks)
    request = client.query()
    ticks.advance(500)
    client.handle(now_ms=ticks.ticks_ms())
    assert request.done is True
    assert isinstance(request.error, NTPError)


def test_handle_zero_byte_recv_under_timeout_keeps_waiting() -> None:
    sock = FakeUDPSocket()
    ticks = FakeTicks()
    client = NTPClient(socket=sock, timeout_ms=500, ticks=ticks)
    request = client.query()
    ticks.advance(50)
    client.handle(now_ms=ticks.ticks_ms())
    assert request.done is False


def test_send_failure_marks_request_failed() -> None:
    sock = FakeUDPSocket()
    sock.enqueue_eagain_for_send()  # simulate kernel rejecting send
    client = NTPClient(socket=sock)
    request = client.query()
    assert request.done is True
    assert isinstance(request.error, OSError)
    assert request.error.args[0] == 11
    # And the client is no longer busy — caller can retry.
    assert client.busy is False


def test_handle_propagates_non_eagain_socket_error() -> None:
    """A non-EAGAIN OSError on recv ends the exchange immediately."""

    class _BoomSocket:
        sent: list = []

        def sendto(self, data, host, port):
            self.sent.append((data, host, port))
            return len(data)

        def recvfrom_into(self, buffer, nbytes=0):
            raise OSError(99, "boom")

    sock = _BoomSocket()
    client = NTPClient(socket=sock)
    request = client.query()
    client.handle(now_ms=0)
    assert request.done is True
    assert isinstance(request.error, OSError)
    assert request.error.args[0] == 99


def test_handle_short_response_marks_failed() -> None:
    sock = FakeUDPSocket()
    sock.enqueue_recv(b"too short")
    client = NTPClient(socket=sock)
    request = client.query()
    client.handle(now_ms=0)
    assert request.done is True
    assert isinstance(request.error, NTPError)


def test_handle_invalid_mode_marks_failed() -> None:
    sock = FakeUDPSocket()
    bad_response = bytearray(_server_response(1))
    bad_response[0] = 0x23  # client mode in a "response"
    sock.enqueue_recv(bytes(bad_response))
    client = NTPClient(socket=sock)
    request = client.query()
    client.handle(now_ms=0)
    assert request.done is True
    assert isinstance(request.error, NTPError)


def test_handle_after_done_is_noop() -> None:
    sock = FakeUDPSocket()
    client = NTPClient(socket=sock)
    request = client.query()
    sock.enqueue_recv(_server_response(1_700_000_000))
    client.handle(now_ms=0)
    assert request.done is True
    # Calling again is harmless.
    client.handle(now_ms=0)
    assert request.unix_seconds == 1_700_000_000


# ---------------------------------------------------------------------------
# cancel
# ---------------------------------------------------------------------------


def test_cancel_idle_returns_false() -> None:
    sock = FakeUDPSocket()
    client = NTPClient(socket=sock)
    assert client.cancel() is False


def test_cancel_in_flight_marks_failed() -> None:
    sock = FakeUDPSocket()
    client = NTPClient(socket=sock)
    request = client.query()
    assert client.cancel() is True
    assert request.done is True
    assert isinstance(request.error, NTPError)
    assert "canceled" in str(request.error)


# ---------------------------------------------------------------------------
# from_config — config-aware construction
# ---------------------------------------------------------------------------


class TestFromConfig:
    """``NTPClient.from_config`` reads the manifest's optional keys with
    sensible fall-back defaults.  Unlike ``MQTTClient.from_config``, no
    key is ever required — the public NTP pool is the documented
    fallback for ``ntp.server`` and the auto-built socket factory reads
    zero config keys."""

    @staticmethod
    def _injected_factory(sock: FakeUDPSocket):
        """Return a socket_factory that hands back *sock*."""
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
            config, socket_factory=self._injected_factory(sock),
        )
        assert client.server == "time.example.com"
        assert client.port == 4242
        assert client.timeout_ms == 1234
        assert client.socket is sock

    def test_defaults_apply_when_keys_absent(self) -> None:
        """Empty config dict → every manifest key falls back to its default.

        This is the asymmetry vs ``MQTTClient.from_config``: ntp's
        public-pool fallback means an empty config is valid input.
        """
        sock = FakeUDPSocket()
        client = NTPClient.from_config(
            {}, socket_factory=self._injected_factory(sock),
        )
        assert client.server == "pool.ntp.org"
        assert client.port == 123
        assert client.timeout_ms == 5_000

    def test_partial_config_mixes_overrides_with_defaults(self) -> None:
        """Caller-set keys win; absent keys take defaults."""
        sock = FakeUDPSocket()
        client = NTPClient.from_config(
            {"ntp.timeout_ms": 250},
            socket_factory=self._injected_factory(sock),
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

    def test_explicit_socket_factory_is_called_once(self) -> None:
        """Passing a custom socket_factory delegates socket creation.
        Factory is invoked exactly once during from_config — eager
        construction since NTPClient takes its socket positionally."""
        call_count = [0]
        sock = FakeUDPSocket()

        def factory():
            call_count[0] += 1
            return sock

        client = NTPClient.from_config({}, socket_factory=factory)
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
            config, socket_factory=self._injected_factory(sock),
        )
        assert client.server == "time.rc.test"
        assert client.timeout_ms == 999
        assert client.port == 123  # default

    def test_default_factory_invokes_chumicro_sockets_factory(self) -> None:
        """When neither *socket* nor *socket_factory* is passed,
        ``from_config`` builds a factory that calls
        ``chumicro_ntp.sockets_factory.chumicro_sockets_factory(radio=...)``
        and sets the resulting socket non-blocking."""
        captured: dict = {}
        sock = FakeUDPSocket()

        def fake_chumicro_sockets_factory(*, radio=None, broadcast=False):
            captured["radio"] = radio
            captured["broadcast"] = broadcast
            return sock

        import chumicro_ntp.sockets_factory as sf  # noqa: PLC0415

        original = sf.chumicro_sockets_factory
        sf.chumicro_sockets_factory = fake_chumicro_sockets_factory
        try:
            client = NTPClient.from_config({}, radio="fake-radio")
        finally:
            sf.chumicro_sockets_factory = original

        assert captured == {"radio": "fake-radio", "broadcast": False}
        assert client.socket is sock
        # Non-blocking was applied — FakeUDPSocket records setblocking calls.
        assert sock._blocking is False  # noqa: SLF001

    def test_default_factory_does_not_raise_on_empty_config(self) -> None:
        """Documents the asymmetry vs MQTTClient.from_config: the
        ntp default factory reads zero config keys (server/port live
        on the NTPClient itself, not on the socket), so an empty
        config dict is valid input even without socket=/socket_factory=.
        Unlike mqtt, no MissingConfigKey is ever raised."""
        sock = FakeUDPSocket()

        def fake_chumicro_sockets_factory(*, radio=None, broadcast=False):
            return sock

        import chumicro_ntp.sockets_factory as sf  # noqa: PLC0415

        original = sf.chumicro_sockets_factory
        sf.chumicro_sockets_factory = fake_chumicro_sockets_factory
        try:
            # No raise: empty config + no socket override is fine.
            client = NTPClient.from_config({})
        finally:
            sf.chumicro_sockets_factory = original

        assert client.server == "pool.ntp.org"

    def test_skipped_factory_module_raises_runtime_error(self) -> None:
        """When ``chumicro_ntp.sockets_factory`` is excluded via
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

        original = sys.modules.get("chumicro_ntp.sockets_factory")
        sys.modules["chumicro_ntp.sockets_factory"] = None
        try:
            try:
                NTPClient.from_config({})
            except RuntimeError as exception:
                assert "socket_factory=" in str(exception)
                assert "socket=" in str(exception)
                assert "__chumicro_skip_factories__" in str(exception)
            else:
                raise AssertionError("expected RuntimeError")
        finally:
            if original is None:
                sys.modules.pop("chumicro_ntp.sockets_factory", None)
            else:
                sys.modules["chumicro_ntp.sockets_factory"] = original


# sockets_factory submodule lives in test_ntp_pytest.py — those tests
# poke CPython-internal stdlib socket state and the CP unix-port factory
# can't construct without a hardware ``radio=``.  The cross-runtime
# contract (factory returns a working UDP socket bound to ephemeral
# port, with sendto/recvfrom_into/getsockname) is exercised on real
# hardware in functional_tests/test_real_ntp.py.
