"""Device-facing test that Runner + Timing + Msgpack work together
on real hardware.

Three integration paths: a runner handler collects records that
round-trip through msgpack, a periodic runner task scheduled on the
real clock round-trips through msgpack, and a raw tick timestamp
survives the same round-trip.
"""

import time

from chumicro_msgpack import packb, unpackb
from chumicro_runner import Runner
from chumicro_timing.ticks import ticks_ms


def _sleep_ms(duration_ms: int) -> None:
    """Sleep for the requested duration using the best available API.

    Args:
        duration_ms: Duration in milliseconds.
    """
    runtime_sleep_ms = getattr(time, "sleep_ms", None)
    if callable(runtime_sleep_ms):
        runtime_sleep_ms(duration_ms)
        return
    time.sleep(duration_ms / 1000)


def test_runner_collects_and_serializes_readings() -> None:
    """Runner should schedule a handler that collects and serializes data."""
    readings = []

    def collect_reading(now_ms: int) -> None:
        readings.append({"tick": now_ms, "value": len(readings)})

    runner = Runner()
    runner.add(handler=collect_reading, run_count=3)

    for _iteration in range(5):
        runner.tick()

    assert len(readings) == 3
    for entry in readings:
        assert "tick" in entry
        assert "value" in entry

    # Serialize all readings through msgpack.
    packed = packb(readings)
    assert isinstance(packed, (bytes, bytearray))

    unpacked = unpackb(packed)
    assert len(unpacked) == 3
    for index, entry in enumerate(unpacked):
        assert entry["value"] == index


def test_runner_periodic_with_msgpack_roundtrip() -> None:
    """Periodic tasks + msgpack should work together on the real clock."""
    events = []

    def handler(now_ms: int) -> None:
        events.append(now_ms)

    runner = Runner()
    runner.add_periodic(handler, period_ms=25)

    # Tick a few times without enough elapsed time.
    runner.tick()
    runner.tick()
    assert len(events) == 0

    _sleep_ms(40)
    runner.tick()
    assert len(events) == 1

    # Serialize the event record.
    record = {"events": events, "count": len(events)}
    packed = packb(record)
    restored = unpackb(packed)
    assert restored["count"] == 1
    assert len(restored["events"]) == 1


def test_ticks_and_msgpack_timestamp_roundtrip() -> None:
    """A tick timestamp captured from the runtime should survive msgpack."""
    now = ticks_ms()
    packed = packb({"timestamp": now})
    restored = unpackb(packed)
    assert restored["timestamp"] == now
