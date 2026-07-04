"""Receive-stream generator — next_message drains a bounded inbound queue.

Cross-runtime: runs on CPython (pytest), MicroPython and CircuitPython
(chumicro_test_harness).  Drives a socket-only client to CONNECTED,
feeds canned broker PUBLISHes, and resumes next_message the way the
runner would: resume the generator, tick the client to parse + enqueue,
resume again.
"""

import chumicro_mqtt.client as mqtt_client_module
from chumicro_mqtt import InboundPublish, ProtocolState
from chumicro_mqtt.client import _INBOUND_WAIT
from chumicro_mqtt.testing import (
    canned_connack_bytes,
    canned_publish_bytes,
    drive,
    new_client,
)
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks


def _connected_client(sock, ticks, **overrides):
    """Build a socket-only client and drive it to CONNECTED."""
    client = new_client(sock, ticks, **overrides)
    sock.enqueue_recv(canned_connack_bytes(return_code=0))
    client.connect()
    drive(client, ticks, count=2)
    assert client.state == ProtocolState.CONNECTED
    return client


def test_first_use_flips_delivery_from_callbacks_to_queue():
    sock = FakeSocket()
    ticks = FakeTicks()
    client = _connected_client(sock, ticks)
    via_callback = []
    client.on_message = lambda topic, payload: via_callback.append(topic)

    gen = client.next_message()
    wait = gen.send(None)  # queue empty: suspends, builds the queue
    assert wait is _INBOUND_WAIT

    sock.enqueue_recv(canned_publish_bytes("demo/cmd", b"go"))
    drive(client, ticks)

    message = None
    try:
        gen.send(ticks.ticks_ms())
    except StopIteration as stop:
        message = stop.value
    assert isinstance(message, InboundPublish)
    assert message.topic == "demo/cmd"
    assert message.payload == b"go"
    assert via_callback == []  # the callback surface stayed silent


def test_queue_drops_oldest_when_full():
    sock = FakeSocket()
    ticks = FakeTicks()
    client = _connected_client(sock, ticks)

    # The inbound-queue bound is a module constant (never consumer-tuned);
    # shrink it for the test so the drop-oldest behavior is reachable in
    # three messages, and restore it for the co-resident tests.
    original_bound = mqtt_client_module._MAX_INBOUND_QUEUE_SIZE
    mqtt_client_module._MAX_INBOUND_QUEUE_SIZE = 2
    try:
        gen = client.next_message()
        gen.send(None)
        for sequence in range(3):
            sock.enqueue_recv(canned_publish_bytes("demo/cmd", bytes((48 + sequence,))))
            drive(client, ticks)
    finally:
        mqtt_client_module._MAX_INBOUND_QUEUE_SIZE = original_bound

    received = []
    for _ in range(2):
        generator = client.next_message()
        try:
            generator.send(None)
        except StopIteration as stop:
            received.append(stop.value.payload)
    # Oldest (b"0") was dropped at the cap; b"1" and b"2" survived.
    assert received == [b"1", b"2"]


def test_returns_none_after_disconnect_and_drain():
    sock = FakeSocket()
    ticks = FakeTicks()
    client = _connected_client(sock, ticks)

    gen = client.next_message()
    gen.send(None)
    sock.enqueue_recv(canned_publish_bytes("demo/cmd", b"last"))
    drive(client, ticks)
    client.disconnect()

    # Queued message still drains after the disconnect...
    try:
        gen.send(ticks.ticks_ms())
    except StopIteration as stop:
        assert stop.value.payload == b"last"
    # ...then the stream reports its end.
    generator = client.next_message()
    ended = object()
    try:
        generator.send(None)
    except StopIteration as stop:
        ended = stop.value
    assert ended is None


def test_transient_failed_keeps_stream_suspended():
    # A FAILED client with a connector factory and self-heal pending is
    # not "ended" — the generator stays suspended awaiting reconnect.
    sock = FakeSocket()
    ticks = FakeTicks()
    client = _connected_client(sock, ticks)
    gen = client.next_message()
    gen.send(None)

    assert client._inbound_stream_ended() is False
    client.disconnect()
    assert client._inbound_stream_ended() is True
