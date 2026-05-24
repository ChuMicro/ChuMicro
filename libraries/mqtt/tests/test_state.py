"""Tests for ProtocolState + packet-id allocation + PendingResponse."""

from chumicro_mqtt import MQTTClient, ProtocolState
from chumicro_mqtt.client import (
    _AWAIT_PINGRESP,
    _AWAIT_SUBACK,
    InFlightPublish,
    PendingResponse,
)
from chumicro_sockets.testing import FakeSocket
from chumicro_test_harness.assertions import raises


def _new_client() -> MQTTClient:
    """A minimal MQTTClient against a fake socket.  Tests don't drive
    the protocol; they exercise the packet-id allocator directly."""
    return MQTTClient(FakeSocket(), client_id="test")


class TestProtocolState:
    def test_known_values(self) -> None:
        # The five lifecycle values.  Tests pin them in case a future
        # refactor renames silently.
        assert ProtocolState.DISCONNECTED == "disconnected"
        assert ProtocolState.AWAITING_TRANSPORT == "awaiting_transport"
        assert ProtocolState.CONNECTING == "connecting"
        assert ProtocolState.CONNECTED == "connected"
        assert ProtocolState.FAILED == "failed"


class TestAllocatePacketId:
    """Exercises MQTTClient._allocate_packet_id + the inlined in-flight dict."""

    def test_starts_at_one(self) -> None:
        client = _new_client()
        assert client._allocate_packet_id() == 1
        assert client._allocate_packet_id() == 2

    def test_skips_in_use(self) -> None:
        client = _new_client()
        first = client._allocate_packet_id()
        client._in_flight[first] = InFlightPublish(
            packet_id=first, packet_bytes=b"", deadline_ticks=0,
        )
        second = client._allocate_packet_id()
        assert second != first

    def test_wraps_around(self) -> None:
        client = _new_client()
        client._next_packet_id = 65534
        assert client._allocate_packet_id() == 65534
        assert client._allocate_packet_id() == 65535
        assert client._allocate_packet_id() == 1

    def test_raises_when_table_full(self) -> None:
        """All 65535 ids in use -> OverflowError.  A tiny mapping that
        claims every id is 'in' exercises the exhausted-id-space path
        without the per-entry heap cost."""
        client = _new_client()

        class _AlwaysFull:
            def __contains__(self, key: int) -> bool:
                return True

        client._in_flight = _AlwaysFull()
        with raises(OverflowError):
            client._allocate_packet_id()


class TestInFlightPublish:
    def test_default_retry_count_zero(self) -> None:
        entry = InFlightPublish(packet_id=1, packet_bytes=b"x", deadline_ticks=99)
        assert entry.retry_count == 0
        assert entry.callback is None

    def test_callback_carries_through(self) -> None:
        called: list[bool] = []

        def cb() -> None:
            called.append(True)

        entry = InFlightPublish(packet_id=1, packet_bytes=b"x", deadline_ticks=99, callback=cb)
        entry.callback()
        assert called == [True]


class TestPendingResponse:
    def test_default_packet_id_none(self) -> None:
        pending = PendingResponse(awaiting=_AWAIT_PINGRESP, deadline_ticks=42)
        assert pending.packet_id is None

    def test_carries_callback(self) -> None:
        captured: list[object] = []
        pending = PendingResponse(
            awaiting=_AWAIT_SUBACK,
            deadline_ticks=42,
            packet_id=7,
            callback=lambda granted: captured.append(granted),
        )
        pending.callback([0])
        assert captured == [[0]]
