"""Tests for ProtocolState + InFlightTable + PendingResponse."""

from chumicro_mqtt import ProtocolState
from chumicro_mqtt.client import (
    Awaiting,
    InFlightPublish,
    InFlightTable,
    PendingResponse,
)
from chumicro_test_harness.assertions import raises


class TestProtocolState:
    def test_canonical_values(self) -> None:
        # The four spec'd values; tests pin them in case a future
        # refactor renames silently.
        assert ProtocolState.DISCONNECTED == "disconnected"
        assert ProtocolState.CONNECTING == "connecting"
        assert ProtocolState.CONNECTED == "connected"
        assert ProtocolState.FAILED == "failed"


class TestInFlightTable:
    def test_allocate_id_starts_at_one(self) -> None:
        table = InFlightTable()
        assert table.allocate_id() == 1
        assert table.allocate_id() == 2

    def test_allocate_id_skips_in_use(self) -> None:
        table = InFlightTable()
        first = table.allocate_id()
        table.add(InFlightPublish(packet_id=first, packet_bytes=b"", deadline_ticks=0))
        # Next allocate should get a different id (2).
        second = table.allocate_id()
        assert second != first

    def test_allocate_id_wraps_around(self) -> None:
        """After 65535 ids allocated, the counter wraps back to 1."""
        table = InFlightTable()
        # Fast-forward via internal state.
        table._next_id = 65534
        assert table.allocate_id() == 65534
        assert table.allocate_id() == 65535
        # Wrap.
        assert table.allocate_id() == 1

    def test_allocate_id_raises_when_table_full(self) -> None:
        """All 65535 ids in use -> OverflowError."""
        table = InFlightTable()
        # Allocating 65 535 real ``InFlightPublish`` entries blows the
        # heap on the MP / CP unix-ports.  ``allocate_id`` only does a
        # ``candidate not in self._entries`` membership probe, so a
        # tiny mapping that claims every id is "in" exercises the same
        # exhausted-id-space path without the per-entry overhead.
        class _AlwaysFull:
            def __contains__(self, key: int) -> bool:
                return True

        table._entries = _AlwaysFull()  # noqa: SLF001 — testing the wraparound
        with raises(OverflowError):
            table.allocate_id()

    def test_add_collision_raises(self) -> None:
        table = InFlightTable()
        entry = InFlightPublish(packet_id=42, packet_bytes=b"", deadline_ticks=0)
        table.add(entry)
        with raises(KeyError):
            table.add(entry)

    def test_get_returns_entry_or_none(self) -> None:
        table = InFlightTable()
        entry = InFlightPublish(packet_id=42, packet_bytes=b"x", deadline_ticks=99)
        table.add(entry)
        assert table.get(42) is entry
        assert table.get(99) is None

    def test_discard_removes_and_returns(self) -> None:
        table = InFlightTable()
        entry = InFlightPublish(packet_id=42, packet_bytes=b"x", deadline_ticks=99)
        table.add(entry)
        assert table.discard(42) is entry
        assert 42 not in table
        # Discarding a missing id is a no-op (returns None).
        assert table.discard(42) is None

    def test_in_operator_and_iteration(self) -> None:
        table = InFlightTable()
        first = InFlightPublish(packet_id=1, packet_bytes=b"a", deadline_ticks=0)
        second = InFlightPublish(packet_id=2, packet_bytes=b"b", deadline_ticks=0)
        table.add(first)
        table.add(second)
        assert 1 in table
        assert 2 in table
        assert len(table) == 2
        entries = sorted(table, key=lambda entry: entry.packet_id)
        assert entries == [first, second]


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
        pending = PendingResponse(awaiting=Awaiting.PINGRESP, deadline_ticks=42)
        assert pending.packet_id is None

    def test_carries_callback(self) -> None:
        captured: list[object] = []
        pending = PendingResponse(
            awaiting=Awaiting.SUBACK,
            deadline_ticks=42,
            packet_id=7,
            callback=lambda granted: captured.append(granted),
        )
        pending.callback([0])
        assert captured == [[0]]
