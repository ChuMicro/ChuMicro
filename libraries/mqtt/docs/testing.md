# Testing Helpers

`chumicro_mqtt.testing` provides pre-baked broker-response byte sequences plus two fixtures for building a client and ticking it.  Tests drive `MQTTClient` against a `chumicro_sockets.testing.FakeSocket`: script the broker's responses with these helpers, let the client tick, then assert the wire format on `sock.sent`.  The helpers stay on the host: `chumicro-deploy` reads the test-support marker at the top of the module and leaves it out of every device bundle it builds.

Each helper spells out one packet shape once, so a test reads `canned_suback_bytes(packet_id=1)` instead of a byte literal nobody can check by eye.

## Building a client and ticking it

`new_client(sock, ticks, **overrides)` builds an `MQTTClient` on *sock* with test defaults: client id `"test-client"`, a 60-second keep-alive, a 5-second ack timeout, and two publish retries.  Any keyword you pass replaces one of those defaults or sets another `MQTTClient` argument.  `drive(client, ticks, count=1)` calls `client.handle(ticks.ticks_ms())` *count* times, which is the loop most tests need after an action that expects a broker response.

Pass a hand-driven clock as *ticks* so the test decides when keep-alives and ack timeouts fire.  `chumicro_timing.testing.FakeTicks` is one, and it only moves when you call `advance()`:

```python
from chumicro_mqtt import ProtocolState
from chumicro_mqtt.testing import canned_connack_bytes, drive, new_client
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks


def test_client_reaches_connected():
    sock = FakeSocket()
    ticks = FakeTicks()
    sock.enqueue_recv(canned_connack_bytes(return_code=0))

    client = new_client(sock, ticks, keep_alive_seconds=30)
    client.connect()
    drive(client, ticks, count=3)

    assert client.state == ProtocolState.CONNECTED
```

Give the client and the tick values you drive it with the same source.  A client left on the real clock and then handed a made-up `now_ms` sees every deadline as long past, and it fails on the first response it gets.

## A full round-trip

Enqueue each broker response just before the client action that expects it.  The client drains the socket greedily, so a PUBACK sitting in the recv queue before its PUBLISH has been sent counts as an unsolicited ack and faults the client.

```python
from chumicro_mqtt.testing import (
    canned_connack_bytes,
    canned_puback_bytes,
    canned_suback_bytes,
    drive,
    new_client,
)
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks


def test_connect_subscribe_publish_roundtrip():
    sock = FakeSocket()
    ticks = FakeTicks()
    sock.enqueue_recv(canned_connack_bytes(return_code=0))

    client = new_client(sock, ticks)
    client.connect()
    drive(client, ticks, count=3)

    sock.enqueue_recv(canned_suback_bytes(packet_id=1))
    client.subscribe("commands/+")
    drive(client, ticks, count=3)

    acked = []
    sock.enqueue_recv(canned_puback_bytes(packet_id=2))
    client.publish(
        "sensors/temp", b"21.5", qos=1,
        on_publish=lambda topic, payload: acked.append(topic),
    )
    drive(client, ticks, count=3)

    assert acked == ["sensors/temp"]
    # Inspect what the client wrote on the wire.  `sock.sent` is a
    # bytearray of everything send()'d in order.
    assert sock.sent[0] == 0x10  # CONNECT fixed header
```

Packet ids start at 1 and count up per outbound packet that needs one, which is why the SUBSCRIBE above is acked with `packet_id=1` and the PUBLISH with `packet_id=2`.

## Available helpers

| Helper | Returns |
|---|---|
| `canned_connack_bytes(*, return_code=0, session_present=False)` | CONNACK packet.  `return_code=0` means accepted; 1 to 5 are the rejection codes in MQTT 3.1.1 §3.2.2.3. |
| `canned_puback_bytes(packet_id)` | PUBACK packet, which acknowledges a QoS 1 publish. |
| `canned_suback_bytes(packet_id, granted_qos=0)` | SUBACK packet acknowledging a one-subscription SUBSCRIBE. |
| `canned_unsuback_bytes(packet_id)` | UNSUBACK packet acknowledging an UNSUBSCRIBE. |
| `canned_pingresp_bytes()` | PINGRESP packet, the keep-alive response. |
| `canned_publish_bytes(topic, payload, *, qos=0, retain=False, packet_id=None)` | PUBLISH packet shaped like the broker would send.  Feed it to `sock.enqueue_recv()` to simulate an inbound message. |

Arguments after the `*` are keyword-only: `canned_connack_bytes(return_code=4)` works, `canned_connack_bytes(4)` raises `TypeError`.

## Simulating a broker rejection

```python
def test_client_handles_connect_refusal():
    sock = FakeSocket()
    ticks = FakeTicks()
    sock.enqueue_recv(canned_connack_bytes(return_code=4))   # bad credentials

    client = new_client(sock, ticks)
    client.connect()
    drive(client, ticks, count=3)

    assert client.state == ProtocolState.FAILED
```

## Simulating an inbound message

```python
def test_subscriber_receives_publish():
    sock = FakeSocket()
    ticks = FakeTicks()
    sock.enqueue_recv(canned_connack_bytes(return_code=0))

    received = []
    client = new_client(sock, ticks)
    client.on_message = lambda topic, payload: received.append((topic, payload))
    client.connect()
    drive(client, ticks, count=3)

    sock.enqueue_recv(canned_suback_bytes(packet_id=1))
    client.subscribe("sensors/+")
    drive(client, ticks, count=3)

    # Broker now pushes a retained or fresh message on the subscription.
    sock.enqueue_recv(canned_publish_bytes("sensors/temp", b"22.1"))
    drive(client, ticks, count=3)

    assert received == [("sensors/temp", b"22.1")]
```

## Using these fakes in your own tests

Your own test suite imports the helpers the same way, and needs nothing beyond the `chumicro-mqtt` install itself:

```python
from chumicro_mqtt.testing import canned_connack_bytes, canned_publish_bytes
```

Project convention: libraries that expose injectable services ship their own test fakes alongside the production code.

## API Reference

::: chumicro_mqtt.testing

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt) · \
[PyPI](https://pypi.org/project/chumicro-mqtt/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
