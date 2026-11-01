# Testing Helpers

`chumicro_mqtt.testing` stands in for the MQTT broker.  It holds the byte packets a broker sends back and two helpers that build an `MQTTClient` and tick it.  A test queues the broker's replies on a `FakeSocket` from `chumicro_sockets.testing`, ticks the client, and reads the bytes the client wrote from `sock.sent`.  `pip install chumicro-mqtt pytest` installs everything the tests on this page import, `chumicro-sockets` and `chumicro-timing` included.  Project deploys and the board bundles leave the module out.

## The smallest test

Save this as `test_mqtt_connect.py` and run `pytest test_mqtt_connect.py`:

```python
from chumicro_mqtt import ProtocolState
from chumicro_mqtt.testing import canned_connack_bytes, drive, new_client
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks


def test_client_reaches_connected():
    sock = FakeSocket()
    ticks = FakeTicks()
    sock.enqueue_recv(canned_connack_bytes(return_code=0))

    client = new_client(sock, ticks)
    client.connect()
    drive(client, ticks, count=3)

    assert client.state == ProtocolState.CONNECTED
```

The CONNACK waits on the socket from the start.  The client reads it after its CONNECT goes out.  `drive` ticks the client three times, enough to send CONNECT and read the reply.

## `new_client` and `drive`

| Helper | What it does |
|---|---|
| `new_client(sock, ticks, **overrides)` | Builds an `MQTTClient` on `sock` with client id `"test-client"`, a 60-second keep-alive, a 5-second ack timeout, and two publish retries.  Each keyword replaces one of those or sets another `MQTTClient` argument. |
| `drive(client, ticks, count=1)` | Calls `client.handle(ticks.ticks_ms())` `count` times. |

Pass a `FakeTicks` as `ticks`, so the test decides when keep-alives and ack timeouts fire.  The client and the `now_ms` it is driven with share that clock.  A client left on the real clock and handed a made-up `now_ms` sees every deadline as long past and fails on the first reply.

## Broker packets

| Helper | Returns |
|---|---|
| `canned_connack_bytes(*, return_code=0, session_present=False)` | A CONNACK.  `return_code=0` accepts the connection, and 1 to 5 are the MQTT 3.1.1 refusal codes. |
| `canned_puback_bytes(packet_id)` | A PUBACK, which acknowledges a QoS 1 publish. |
| `canned_suback_bytes(packet_id, granted_qos=0)` | A SUBACK for a one-topic SUBSCRIBE. |
| `canned_unsuback_bytes(packet_id)` | An UNSUBACK. |
| `canned_pingresp_bytes()` | A PINGRESP, the reply to a keep-alive ping. |
| `canned_publish_bytes(topic, payload, *, qos=0, retain=False, packet_id=None)` | A PUBLISH from the broker, for a message arriving on a subscription.  QoS 1 or 2 needs a `packet_id`. |

`canned_connack_bytes` takes its arguments by keyword only, as in `canned_connack_bytes(return_code=4)`.

Queue each reply just before the client action that expects it.  The client reads everything waiting on the socket, so a PUBACK queued before its PUBLISH goes out counts as an unasked-for ack and faults the client.  Packet ids start at 1 and count up for each outgoing packet that needs one:

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


def test_subscribe_then_publish():
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
    assert sock.sent[0] == 0x10
```

`sock.sent` holds every byte the client wrote, in order.  Its first byte, `0x10`, opens the CONNECT packet.

A refusal code in the CONNACK plays a broker that turns the client away:

```python
from chumicro_mqtt import ProtocolState
from chumicro_mqtt.testing import canned_connack_bytes, drive, new_client
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks


def test_bad_credentials_fail_the_client():
    sock = FakeSocket()
    ticks = FakeTicks()
    sock.enqueue_recv(canned_connack_bytes(return_code=4))

    client = new_client(sock, ticks)
    client.connect()
    drive(client, ticks, count=3)

    assert client.state == ProtocolState.FAILED
```

`canned_publish_bytes` delivers a message on a subscription:

```python
from chumicro_mqtt.testing import (
    canned_connack_bytes,
    canned_publish_bytes,
    canned_suback_bytes,
    drive,
    new_client,
)
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks


def test_subscriber_receives_a_message():
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

    sock.enqueue_recv(canned_publish_bytes("sensors/temp", b"22.1"))
    drive(client, ticks, count=3)

    assert received == [("sensors/temp", b"22.1")]
```

The [sockets Testing Helpers](https://chumicro.com/ChuMicro/sockets/stable/testing/) page covers `FakeSocket`, including how it simulates a dropped connection.

## API reference

::: chumicro_mqtt.testing

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt) · \
[PyPI](https://pypi.org/project/chumicro-mqtt/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
