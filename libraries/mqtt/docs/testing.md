# Testing Helpers

`chumicro_mqtt.testing` provides pre-baked broker-response byte sequences for unit tests.  Tests typically drive `MQTTClient` against a `chumicro_sockets.testing.FakeSocket` — script the broker's responses with these helpers, let the client tick, then assert the wire-format on `sock.sent`.

The canned-bytes helpers stay in sync with the encoder/decoder, so a hand-rolled byte literal in a test doesn't drift if the wire format changes.

## Usage

Enqueue each broker response *just before* the client action that
expects it — the client drains the socket greedily, so a PUBACK
sitting in the recv queue before its PUBLISH has been sent is
treated as an unsolicited ack and faults the client.

```python
from chumicro_mqtt import MQTTClient, ProtocolState
from chumicro_mqtt.testing import (
    canned_connack_bytes,
    canned_puback_bytes,
    canned_suback_bytes,
    canned_publish_bytes,
)
from chumicro_sockets.testing import FakeSocket

def test_connect_publish_subscribe_roundtrip():
    sock = FakeSocket()
    sock.enqueue_recv(canned_connack_bytes(return_code=0))

    client = MQTTClient(sock, client_id="test")
    client.connect()
    while client.state != ProtocolState.CONNECTED:
        client.handle(now_ms=0)

    sock.enqueue_recv(canned_suback_bytes(packet_id=1))
    client.subscribe("commands/+")
    for _ in range(3):
        client.handle(now_ms=0)

    acked = []
    sock.enqueue_recv(canned_puback_bytes(packet_id=2))
    client.publish(
        "sensors/temp", b"21.5", qos=1,
        on_publish=lambda topic, payload: acked.append(topic),
    )
    for _ in range(3):
        client.handle(now_ms=0)

    assert acked == ["sensors/temp"]
    # Inspect what the client wrote on the wire.  `sock.sent` is a
    # bytearray of everything send()'d in order.
    assert sock.sent[0] == 0x10  # CONNECT fixed header
```

## Available helpers

| Helper | Returns |
|---|---|
| `canned_connack_bytes(return_code=0, session_present=False)` | CONNACK packet — `return_code=0` means accepted; 1-5 are rejection codes per MQTT 3.1.1 §3.2.2.3. |
| `canned_puback_bytes(packet_id)` | PUBACK packet — drives QoS-1 publish acknowledgment. |
| `canned_suback_bytes(packet_id, granted_qos=0)` | SUBACK packet — acknowledges a one-subscription SUBSCRIBE. |
| `canned_unsuback_bytes(packet_id)` | UNSUBACK packet — acknowledges an UNSUBSCRIBE. |
| `canned_pingresp_bytes()` | PINGRESP packet — keep-alive response. |
| `canned_publish_bytes(topic, payload, qos=0, retain=False, packet_id=None)` | PUBLISH packet shaped like the broker would send — feed it to `sock.enqueue_recv()` to simulate an inbound message. |

## Simulating a broker rejection

```python
def test_client_handles_connect_refusal():
    sock = FakeSocket()
    sock.enqueue_recv(canned_connack_bytes(return_code=4))   # bad credentials

    client = MQTTClient(sock, client_id="test")
    client.connect()
    client.handle(now_ms=0)

    assert client.state == ProtocolState.FAILED
```

## Simulating an inbound message

```python
def test_subscriber_receives_publish():
    sock = FakeSocket()
    sock.enqueue_recv(canned_connack_bytes(return_code=0))

    received = []
    client = MQTTClient(sock, client_id="test")
    client.on_message = lambda topic, payload: received.append((topic, payload))
    client.connect()
    while client.state != ProtocolState.CONNECTED:
        client.handle(now_ms=0)

    sock.enqueue_recv(canned_suback_bytes(packet_id=1))
    client.subscribe("sensors/+")
    for _ in range(3):
        client.handle(now_ms=0)

    # Broker now pushes a retained / fresh message on the subscription.
    sock.enqueue_recv(canned_publish_bytes("sensors/temp", b"22.1"))
    for _ in range(3):
        client.handle(now_ms=0)

    assert received == [("sensors/temp", b"22.1")]
```

## Usage from other libraries

Libraries that depend on `chumicro-mqtt` can import the helpers directly in their own test suites:

```python
from chumicro_mqtt.testing import canned_connack_bytes, canned_publish_bytes
```

Libraries that expose injectable services ship their own test fakes alongside the production code, so every consumer uses the same shared fake.

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
