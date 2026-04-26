"""MQTT quickstart against a FakeSocket — runs identically on every runtime.

Drives :class:`MQTTClient` through a CONNECT → SUBSCRIBE → PUBLISH →
inbound-message round trip without touching the network.  Real-network
use is identical except you call ``tcp_client_socket(host, port,
radio=...)`` instead of ``FakeSocket()``.

Example output::

    state: disconnected
    state: connected
    sent: True
    received: ('temp/back-porch', b'21')
    state: disconnected
"""

from chumicro_mqtt import MQTTClient
from chumicro_mqtt.testing import (
    canned_connack_bytes,
    canned_publish_bytes,
    canned_suback_bytes,
)
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks


def run_quickstart() -> None:
    sock = FakeSocket()
    ticks = FakeTicks()
    client = MQTTClient(
        sock,
        client_id="quickstart-thing",
        ticks_ms_func=ticks.ticks_ms,
        ticks_add_func=ticks.ticks_add,
        ticks_diff_func=ticks.ticks_diff,
    )

    # Script the broker's responses.
    sock.enqueue_recv(canned_connack_bytes(return_code=0))
    sock.enqueue_recv(canned_suback_bytes(packet_id=1, granted_qos=0))
    sock.enqueue_recv(canned_publish_bytes("temp/back-porch", b"21", qos=0))

    received = []
    client.on_message = lambda topic, payload: received.append((topic, payload))

    print(f"state: {client.state}")
    client.connect()
    client.handle(ticks.ticks_ms())
    client.handle(ticks.ticks_ms())
    print(f"state: {client.state}")

    client.subscribe("temp/+", qos=0)
    client.handle(ticks.ticks_ms())
    client.handle(ticks.ticks_ms())

    client.publish("temp/back-porch", b"21", qos=0)
    client.handle(ticks.ticks_ms())
    print(f"sent: {b'temp/back-porch' in bytes(sock.sent)}")

    client.handle(ticks.ticks_ms())
    print(f"received: {received[0] if received else None}")

    client.disconnect()
    print(f"state: {client.state}")


run_quickstart()
