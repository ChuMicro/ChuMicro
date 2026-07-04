"""mqtt client: multi-tick drain of a large steady-tier PUBLISH.

The 16K-buffer / 8K-payload drain test is the mqtt heap-budget floor
on the unix device lanes; it lives alone in this file so it runs with
as few co-resident test objects as possible (suite-slimming
convention — split from ``test_client_bounded_recv.py``).
"""

from chumicro_mqtt import (
    ProtocolState,
)
from chumicro_mqtt.testing import (
    canned_connack_bytes,
    canned_publish_bytes,
    drive,
    new_client,
)
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks


class TestBoundedRecvMultiTickDrain:
    def test_budget_eventually_drains_full_payload_across_ticks(self) -> None:
        """Multiple ticks accumulate.  A big blob arrives complete eventually.

        Configures a 16 KB ``rx_buffer_size`` so an 8 KB PUBLISH
        stays on the steady-state path (the default 256 B buffer
        would route it through the oversized-message handler and
        ``on_message`` wouldn't fire).
        """
        sock = FakeSocket()
        ticks = FakeTicks()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        client = new_client(
            sock, ticks, recv_budget_per_tick=1024, rx_buffer_size=16384,
        )
        client.connect()
        drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED

        received_payloads: list[bytes] = []
        client.on_message = lambda topic, payload: received_payloads.append(payload)

        big_payload = b"y" * 8192
        sock.enqueue_recv(canned_publish_bytes("topic/big", big_payload, qos=0))

        # Drive until the payload arrives (~9 ticks at 1024 B/tick
        # for 8192 + small header bytes total).
        for _ in range(20):
            drive(client, ticks, count=1)
            if received_payloads:
                break
        assert received_payloads == [big_payload]
